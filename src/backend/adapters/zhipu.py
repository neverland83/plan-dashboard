"""智谱 GLM Coding Plan（含 Z.ai 国际版复用，host 可配）。

接口档案：docs/research/providers/zhipu.md（国内）/ zai.md（国际）
- GET {host}/api/monitor/usage/quota/limit
- Authorization: <裸 key>（无 Bearer 前缀）
- data.limits[]: type=TIME_LIMIT(5小时) / TOKENS_LIMIT(周)，percentage 为已用%
- nextResetTime: 毫秒时间戳
- extra.host 可覆盖（Z.ai 用 https://api.z.ai）
- extra.team_organization_id / team_project_id → 团队版 header（CodexBar 口径）

CC Switch 源码补充细节（coding_plan.rs）：
- 窗口归类按 limits[].unit 字段：unit=3 → 5小时，unit=6 → 周；无 unit 时归为周窗口
- type 大小写不敏感匹配 TOKENS_LIMIT / CREDIT_LIMIT 才纳入；TIME_LIMIT 视为 5h 窗口
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .base import WIN_5H, WIN_WEEK, BaseAdapter, utc_now_iso
from ..models import PlanUsage, UsageWindow

DEFAULT_HOST = "https://open.bigmodel.cn"
QUOTA_PATH = "/api/monitor/usage/quota/limit"
MODELS_PATH = "/api/paas/v4/models"

LEVEL_NAMES = {"lite": "GLM Coding Lite", "pro": "GLM Coding Pro", "max": "GLM Coding Max"}


def _display_from(extra: dict) -> str:
    host = (extra.get("host") or DEFAULT_HOST).rstrip("/")
    return "Z.ai Coding" if "z.ai" in host else "智谱 GLM Coding"


class ZhipuAdapter(BaseAdapter):
    provider_id = "zhipu"
    display_name = "智谱 GLM Coding"

    def _fetch(self, api_key: str, extra: dict, usage: PlanUsage) -> PlanUsage:
        host = (extra.get("host") or DEFAULT_HOST).rstrip("/")
        url = f"{host}{QUOTA_PATH}"

        headers = {
            # 注意：智谱裸 key 认证，不加 Bearer
            "Authorization": api_key,
            "Accept": "application/json",
            "Accept-Language": "en-US,en",
        }
        org = extra.get("team_organization_id")
        project = extra.get("team_project_id")
        if org:
            headers["Bigmodel-Organization"] = str(org)
        if project:
            headers["Bigmodel-Project"] = str(project)

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

        if body.get("success") is False:
            msg = body.get("msg") or "未知错误"
            return self._fail(usage, f"API 业务错误：{msg}")

        data = body.get("data")
        if not isinstance(data, dict):
            return self._fail(usage, "响应缺少 data 字段")

        level = str(data.get("level") or "").lower()
        usage.plan_name = LEVEL_NAMES.get(level, level)

        five_hour = None
        weekly = None
        unclassified: list[dict] = []
        for item in data.get("limits") or []:
            if not isinstance(item, dict):
                continue
            ltype = str(item.get("type") or "")
            pct = self._to_float(item.get("percentage"), 0.0) or 0.0
            entry = {"pct": pct, "reset": self._ms_to_iso(item.get("nextResetTime"))}
            unit = item.get("unit")
            if ltype.upper() == "TIME_LIMIT":
                if five_hour is None:
                    five_hour = entry
            elif ltype.upper() in ("TOKENS_LIMIT", "CREDIT_LIMIT"):
                # CC Switch 实测：unit=3 → 5小时，unit=6 → 周；无 unit 时归为周窗口
                if unit == 3:
                    if five_hour is None:
                        five_hour = entry
                elif weekly is None:
                    weekly = entry
            else:
                unclassified.append(entry)
        # 未识别类型的兜底分配
        for entry in unclassified:
            if five_hour is None:
                five_hour = entry
            elif weekly is None:
                weekly = entry

        if five_hour:
            usage.windows.append(UsageWindow(WIN_5H, five_hour["pct"], five_hour["reset"]))
        if weekly:
            usage.windows.append(UsageWindow(WIN_WEEK, weekly["pct"], weekly["reset"]))
        if not usage.windows:
            return self._fail(usage, "响应中未找到任何用量窗口")
        return usage

    @staticmethod
    def _ms_to_iso(value) -> str | None:
        try:
            ms = int(value)
        except (TypeError, ValueError):
            return None
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat(timespec="seconds")

    # ---- 卡片详情扩展 -----------------------------------------------------
    def fetch_models(self, api_key: str, extra: dict) -> list[str]:
        """GET {host}/api/paas/v4/models（OpenAI 兼容，Bearer 认证；含 Z.ai 变体）。

        智谱 key 认证特殊（裸 key 无 Bearer）仅限管控面 quota 接口；
        paas/v4 推理面为标准 Bearer。失败返回 []。
        """
        host = (extra.get("host") or DEFAULT_HOST).rstrip("/")
        return self._fetch_models_openai_compat(f"{host}{MODELS_PATH}", api_key)

    def fetch_plan_name(self, api_key: str, extra: dict) -> str | None:
        """复用 quota/limit 响应里的 data.level → 'GLM Coding Lite/Pro/Max'。

        与 _fetch 同 URL 同 header；任何失败（无 key/网络/结构异常）返回 None。
        """
        if not (api_key or "").strip():
            return None
        host = (extra.get("host") or DEFAULT_HOST).rstrip("/")
        url = f"{host}{QUOTA_PATH}"
        headers = {
            "Authorization": api_key,
            "Accept": "application/json",
            "Accept-Language": "en-US,en",
        }
        org = extra.get("team_organization_id")
        project = extra.get("team_project_id")
        if org:
            headers["Bigmodel-Organization"] = str(org)
        if project:
            headers["Bigmodel-Project"] = str(project)
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
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            return None
        level = str(data.get("level") or "").lower()
        return LEVEL_NAMES.get(level) or (level or None)
