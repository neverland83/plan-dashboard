"""Kimi / Moonshot 账户余额查询（余额型，无窗口）。

接口档案：docs/research/providers/kimi.md
- GET https://api.moonshot.cn/v1/users/me/balance   （CN）
- GET https://api.kimi.ai/v1/users/me/balance       （EN）
- Authorization: Bearer <key>
- data.available_balance / voucher_balance / cash_balance
"""
from __future__ import annotations

import httpx

from .base import BaseAdapter
from ..models import PlanUsage

HOST_CN = "https://api.moonshot.cn"
BALANCE_PATH = "/v1/users/me/balance"


class KimiAdapter(BaseAdapter):
    provider_id = "kimi"
    display_name = "Kimi (Moonshot)"
    kind = "balance"

    def _fetch(self, api_key: str, extra: dict, usage: PlanUsage) -> PlanUsage:
        host = (extra.get("host") or HOST_CN).rstrip("/")
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

        if body.get("code") not in (None, 0):
            return self._fail(usage, f"API 业务错误 (code {body.get('code')})")
        data = body.get("data")
        if not isinstance(data, dict):
            return self._fail(usage, "响应缺少 data 字段")

        usage.balance = {
            "currency": str(extra.get("currency") or "CNY"),
            "available": self._to_float(data.get("available_balance"), 0.0),
            "voucher": self._to_float(data.get("voucher_balance"), 0.0),
            "cash": self._to_float(data.get("cash_balance"), 0.0),
        }
        return usage
