"""DeepSeek 账户余额查询（余额型，无窗口）。

接口档案：docs/research/providers/deepseek.md
- GET https://api.deepseek.com/user/balance
- Authorization: Bearer <key>
- balance_infos[]: currency / total_balance / granted_balance / topped_up_balance
- is_available: 账户是否可用
"""
from __future__ import annotations

import httpx

from .base import BaseAdapter
from ..models import PlanUsage

DEFAULT_HOST = "https://api.deepseek.com"
BALANCE_PATH = "/user/balance"


class DeepSeekAdapter(BaseAdapter):
    provider_id = "deepseek"
    display_name = "DeepSeek"
    kind = "balance"

    def _fetch(self, api_key: str, extra: dict, usage: PlanUsage) -> PlanUsage:
        host = (extra.get("host") or DEFAULT_HOST).rstrip("/")
        url = f"{host}{BALANCE_PATH}"
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

        infos = body.get("balance_infos")
        if not isinstance(infos, list) or not infos:
            return self._fail(usage, "响应缺少 balance_infos 字段")

        first = infos[0] if isinstance(infos[0], dict) else {}
        usage.balance = {
            "currency": str(first.get("currency") or "CNY"),
            "total": self._to_float(first.get("total_balance"), 0.0),
            "granted": self._to_float(first.get("granted_balance"), 0.0),
            "topped_up": self._to_float(first.get("topped_up_balance"), 0.0),
            # 数据有效即上板；is_available=False 由前端黄字提示"账户不可用"
            "is_available": bool(body.get("is_available", True)),
        }
        return usage
