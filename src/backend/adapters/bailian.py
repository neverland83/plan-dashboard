"""阿里云百炼 Token Plan 配额查询（经由官方 bailian-cli）。

不调 HTTP API：百炼 Token Plan 配额暂无公开用量接口，官方提供 CLI 工具
bailian-cli（命令 `bl`），需先 `bl auth login`（console OAuth）完成登录。
本适配器通过 subprocess 调用 CLI 查询：

    bl usage token-plan --output json

实测输出（JSON，单周窗口，无 5h 字段——控制台标注 5h 可能无限）：
    {"per1WeekPercentage": 0.8936928449999999, "per1WeekResetTime": 1788145140000}

- per1WeekPercentage：已用比例 0-1（0.8937 = 已用 89.37%）→ 换算为已用百分比
- per1WeekResetTime：毫秒时间戳 → 转 ISO（UTC）

注意（Windows）：`bl` 是 npm 全局安装的 PowerShell 包装脚本，subprocess 直接
调 `bl`（PATH 内可寻址）；stderr 可能混有 wrapper 噪音，解析只看 stdout。

OAuth transient 防御：`bl usage token-plan` 强 Console gateway 鉴权，OAuth
access_token 短过期（默认 1-2 小时）时会返回 code 3 + 文案 "Console session
is not logged in or has expired."。bl CLI 内部会自动 refresh（写回
~/.bailian/config.json），本适配器检测到该错误后最多重试 2 次（每次 1.5 秒），
不再把这种 transient 错误暴露给上层。其它非 transient 错误（普通的子进程
错误）不在重试范围。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from datetime import datetime, timezone

from .base import WIN_WEEK, BaseAdapter
from ..models import PlanUsage, UsageWindow

BL_CMD = "bl"
CLI_TIMEOUT = 20.0          # 秒；CLI 冷启动 + 网络往返留足余量
STDERR_SNIPPET = 200        # 错误态文案里携带的 stderr 截断长度
MAX_RETRIES = 2             # OAuth transient 时重试次数（不含首次）
RETRY_DELAY = 1.5           # 秒；给 bl CLI 内置 refresh 留时间
# 百炼 OpenAI 兼容模式模型列表（有 API Key 的条目才能查；bl CLI 登录态查不了推理面）
DASHSCOPE_HOST = "https://dashscope.aliyuncs.com"
COMPAT_MODELS_PATH = "/compatible-mode/v1/models"


def _is_oauth_expiry_error(text: str) -> bool:
    """判定 subprocess 输出是否为 OAuth transient 过期错误（值得重试的那一种）。"""
    if not text:
        return False
    if "Console session" in text:
        return True
    return "expired" in text.lower()


class BailianAdapter(BaseAdapter):
    provider_id = "bailian"
    display_name = "阿里云百炼"
    kind = "windows"
    needs_key = False          # 使用本机 bl CLI + console 登录凭证，无需 API Key

    def _fetch(self, api_key: str, extra: dict, usage: PlanUsage) -> PlanUsage:
        # extra 预留（当前 CLI 无可配参数），api_key 不使用（无 key 厂商）。
        # Windows 上 npm 全局包没有 bl.exe（只有 bl.cmd/bl.ps1），subprocess 不解析
        # PATHEXT，需用 shutil.which 解析到可执行形态；解析失败即未安装。
        bl_path = shutil.which(BL_CMD)
        if not bl_path:
            return self._fail(usage, "未找到 bl 命令，请先安装 bailian-cli（npm i -g bailian-cli）")

        proc = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                proc = subprocess.run(
                    [bl_path, "usage", "token-plan", "--output", "json"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=CLI_TIMEOUT,
                )
            except FileNotFoundError:
                return self._fail(usage, "未找到 bl 命令，请先安装 bailian-cli（npm i -g bailian-cli）")
            except subprocess.TimeoutExpired:
                return self._fail(usage, f"bl 命令超时（>{int(CLI_TIMEOUT)}s），请检查网络或重试")

            if proc.returncode == 0:
                break  # 跳出 retry 循环进入 JSON 解析

            detail = (proc.stderr or proc.stdout or "").strip()[:STDERR_SNIPPET]
            if attempt < MAX_RETRIES and _is_oauth_expiry_error(detail):
                # OAuth access_token 短过期；等 1.5 秒让 bl CLI 内置 refresh 续期
                time.sleep(RETRY_DELAY)
                continue

            # 非 transient 错误或重试用尽 → 报错
            suffix = f"：{detail}" if detail else ""
            return self._fail(usage, f"bl 命令执行失败（退出码 {proc.returncode}）{suffix}")

        # proc.returncode == 0：JSON 解析逻辑
        try:
            body = json.loads(proc.stdout)
        except ValueError:
            detail = (proc.stdout or "").strip()[:STDERR_SNIPPET]
            return self._fail(usage, f"bl 输出不是合法 JSON：{detail}")
        if not isinstance(body, dict):
            return self._fail(usage, "bl 输出结构异常（非 JSON 对象）")

        usage.raw = body

        used_pct = self._to_float(body.get("per1WeekPercentage"))
        if used_pct is None:
            return self._fail(usage, "bl 输出缺少 per1WeekPercentage 字段")
        # 比例（0-1）→ 已用百分比（0-100）；兼容个别版本直接给百分比的情况
        if used_pct <= 1.0:
            used_pct *= 100.0

        reset_iso = self._ms_to_iso(body.get("per1WeekResetTime"))
        usage.windows.append(UsageWindow(WIN_WEEK, self._clamp_pct(used_pct), reset_iso))
        return usage

    @staticmethod
    def _ms_to_iso(value) -> str | None:
        """毫秒时间戳 → ISO 8601（UTC），非法值返回 None。"""
        try:
            ms = int(value)
        except (TypeError, ValueError):
            return None
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat(timespec="seconds")

    # ---- 卡片详情扩展 -----------------------------------------------------
    def fetch_models(self, api_key: str, extra: dict) -> list[str]:
        """GET dashscope compatible-mode/v1/models（OpenAI 兼容）。

        bl CLI 登录态只覆盖管控面（Token Plan 配额），模型列表在推理面，
        需要条目配了 API Key（extra.api_key 或 api_key 字段）。失败返回 []。
        """
        key = (extra.get("api_key") or api_key or "").strip()
        if not key:
            return []
        return self._fetch_models_openai_compat(
            f"{DASHSCOPE_HOST}{COMPAT_MODELS_PATH}", key)

    def fetch_plan_name(self, api_key: str, extra: dict) -> str | None:
        """尝试从 bl CLI 的 Token Plan 输出拉套餐档级名。

        实测输出只有 per1WeekPercentage/per1WeekResetTime，无档级字段 ——
        CLI 查通即视为 Token Plan 生效，返回 'Token Plan'；失败返回 None。
        """
        bl_path = shutil.which(BL_CMD)
        if not bl_path:
            return None
        try:
            proc = subprocess.run(
                [bl_path, "usage", "token-plan", "--output", "json"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=CLI_TIMEOUT,
            )
        except Exception:  # noqa: BLE001 —— 契约要求绝不抛异常（含 OSError/超时/其它运行时错误）
            return None
        if proc.returncode != 0:
            return None
        try:
            body = json.loads(proc.stdout)
        except ValueError:
            return None
        if not isinstance(body, dict):
            return None
        if self._to_float(body.get("per1WeekPercentage")) is not None:
            return "Token Plan"
        return None
