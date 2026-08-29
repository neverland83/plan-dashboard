"""MiniMax Coding Plan 用量查询。

接口档案：docs/research/providers/minimax.md（标注"开发时从 CC Switch 源码确认"）。
以下端点/字段已按 brief 要求从 CC Switch 源码（src-tauri/src/services/coding_plan.rs，
v3.16.2+ 的 MiniMax 分支）提取确认：

- GET https://api.minimaxi.com/v1/api/openplatform/coding_plan/remains   （CN）
- GET https://api.minimax.io/v1/api/openplatform/coding_plan/remains     （国际）
- Authorization: Bearer <key>
- 业务错误：base_resp.status_code != 0（status_msg 为错误描述）
- 响应 model_remains[]：只取 model_name == "general"（过滤 video 等非编程模型）
- current_interval_remaining_percent → 5h 窗口**剩余**%（反转为已用）
- end_time / weekly_end_time → 毫秒时间戳
- 周窗口仅当 current_weekly_status == 1 才存在；=3 等表示无周限额，跳过
- extra.region: "cn"(默认) | "intl"
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .base import WIN_5H, WIN_WEEK, BaseAdapter
from ..models import PlanUsage, UsageWindow

HOST_CN = "https://api.minimaxi.com"
HOST_INTL = "https://api.minimax.io"
REMAINS_PATH = "/v1/api/openplatform/coding_plan/remains"
MODELS_PATH = "/v1/models"          # OpenAI 兼容 List Models


class MiniMaxAdapter(BaseAdapter):
    provider_id = "minimax"
    display_name = "MiniMax Coding Plan"

    def _fetch(self, api_key: str, extra: dict, usage: PlanUsage) -> PlanUsage:
        region = str(extra.get("region") or "cn").lower()
        host = HOST_INTL if region in ("intl", "en", "global") else HOST_CN
        url = f"{host}{REMAINS_PATH}"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }

        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, headers=headers)

        if resp.status_code in (401, 403):
            return self._fail(usage, f"认证失败 (HTTP {resp.status_code})：Key 无效或已过期")
        if resp.status_code >= 400:
            return self._fail(usage, f"API 错误 (HTTP {resp.status_code})")

        try:
            body = resp.json()
        except ValueError:
            return self._fail(usage, "响应不是合法 JSON")

        usage.raw = body if isinstance(body, dict) else {}

        base_resp = body.get("base_resp") or {}
        status_code = base_resp.get("status_code")
        if status_code not in (None, 0):
            msg = base_resp.get("status_msg") or "未知错误"
            return self._fail(usage, f"API 业务错误 (code {status_code})：{msg}")

        remains = body.get("model_remains")
        if not isinstance(remains, list):
            return self._fail(usage, "响应缺少 model_remains 字段")

        # 过滤非编程模型：只取 general
        item = None
        for candidate in remains:
            if isinstance(candidate, dict) and candidate.get("model_name") == "general":
                item = candidate
                break
        if item is None:
            return self._fail(usage, "未找到编程套餐（general）用量数据")

        usage.plan_name = "MiniMax Coding Plan"

        remain_pct = self._to_float(item.get("current_interval_remaining_percent"))
        if remain_pct is not None:
            # 新接口返回剩余百分比 → 统一口径反转为已用百分比
            used = self._clamp_pct(100.0 - remain_pct)
            usage.windows.append(
                UsageWindow(WIN_5H, used, self._ms_to_iso(item.get("end_time")))
            )

        # 周桶：仅当 status==1 时激活；status=3 表示该套餐无周限额
        if item.get("current_weekly_status") == 1:
            weekly_remain = self._to_float(item.get("current_weekly_remaining_percent"))
            if weekly_remain is not None:
                used_w = self._clamp_pct(100.0 - weekly_remain)
                usage.windows.append(
                    UsageWindow(WIN_WEEK, used_w, self._ms_to_iso(item.get("weekly_end_time")))
                )

        if not usage.windows:
            return self._fail(usage, "响应中未解析出任何用量窗口")
        return usage

    @staticmethod
    def _ms_to_iso(value) -> str | None:
        try:
            ms = int(value)
        except (TypeError, ValueError):
            return None
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat(timespec="seconds")

    # ---- 卡片详情扩展 -----------------------------------------------------
    def _host_for(self, extra: dict) -> str:
        region = str(extra.get("region") or "cn").lower()
        return HOST_INTL if region in ("intl", "en", "global") else HOST_CN

    def fetch_models(self, api_key: str, extra: dict) -> list[str]:
        """GET {host}/v1/models（OpenAI 兼容 List Models）。失败返回 []。"""
        return self._fetch_models_openai_compat(
            f"{self._host_for(extra)}{MODELS_PATH}", api_key)

    def fetch_plan_name(self, api_key: str, extra: dict) -> str | None:
        """MiniMax Coding Plan 只有 1 档：remains 查通即 'MiniMax Coding Plan'。

        查不通（无 key/失败）返回 None，交给 config 手填回退。
        """
        if not (api_key or "").strip():
            return None
        url = f"{self._host_for(extra)}{REMAINS_PATH}"
        headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(url, headers=headers)
        except Exception:  # noqa: BLE001
            return None
        if resp.status_code >= 400:
            return None
        try:
            body = resp.json()
        except ValueError:
            return None
        base_resp = body.get("base_resp") or {}
        if base_resp.get("status_code") not in (None, 0):
            return None
        remains = body.get("model_remains")
        if isinstance(remains, list) and any(
            isinstance(c, dict) and c.get("model_name") == "general" for c in remains
        ):
            return "MiniMax Coding Plan"
        return None
