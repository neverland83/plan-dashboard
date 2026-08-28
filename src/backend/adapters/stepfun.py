"""StepFun 账户余额查询（余额型；Step Plan 月池/加油包无公开查询 API）。

接口档案：docs/research/providers/stepfun.md
- GET https://api.stepfun.com/v1/accounts
- Authorization: Bearer <key>
- 返回 object/type/balance/total_cash_balance/total_voucher_balance
- 说明：Step Plan 月池 Credit 与加油包（30 天周期）在控制台展示，官方无查询接口。
  如需在看板展示加油包/月池余量，请在 extra.manual_credits 配置手动窗口，
  格式：[{"name": "加油包", "remaining": 45}]（remaining=剩余百分比；
  也可直接填 percentage=已用百分比，或附 next_reset ISO 时间）。

注意：Step Plan 专用 Base URL 是 https://api.stepfun.com/step_plan/v1，
但账户余额接口在标准端点 /v1/accounts（step_plan 路径下实测 404）。
"""
from __future__ import annotations

import json

import httpx

from .base import BaseAdapter
from ..models import PlanUsage, UsageWindow

HOST = "https://api.stepfun.com"
ACCOUNT_PATH = "/v1/accounts"


class StepFunAdapter(BaseAdapter):
    provider_id = "stepfun"
    display_name = "StepFun"
    kind = "balance"

    def _fetch(self, api_key: str, extra: dict, usage: PlanUsage) -> PlanUsage:
        host = (extra.get("host") or HOST).rstrip("/")
        url = f"{host}{ACCOUNT_PATH}"
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
        if not isinstance(body, dict):
            return self._fail(usage, "响应结构异常（非对象）")

        usage.raw = body

        usage.balance = {
            "currency": str(body.get("currency") or "CNY"),
            "total": self._to_float(body.get("balance"), 0.0),
            "topped_up": self._to_float(body.get("total_cash_balance"), 0.0),
            "voucher": self._to_float(body.get("total_voucher_balance"), 0.0),
        }

        # 手动录入的 Step Plan 月池 / 加油包窗口（官方无查询 API）
        self._merge_manual_windows(usage, extra.get("manual_credits"))

        if not usage.windows:
            usage.plan_name = "Step Plan（控制台查看）"
        return usage

    @classmethod
    def _merge_manual_windows(cls, usage: PlanUsage, manual_windows) -> None:
        """把 extra.manual_credits 合并为窗口（兼容 remaining/percentage 两种写法）。

        配置面板的文本框会把值存成字符串，这里同时兼容 list 与 JSON 字符串。
        """
        if isinstance(manual_windows, str):
            try:
                manual_windows = json.loads(manual_windows)
            except ValueError:
                return
        if not isinstance(manual_windows, list):
            return
        for item in manual_windows:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "额度").strip()
            percentage = cls._to_float(item.get("percentage"))
            if percentage is None:
                remaining = cls._to_float(item.get("remaining"))
                if remaining is None:
                    continue
                percentage = 100.0 - cls._clamp_pct(remaining)
            usage.windows.append(UsageWindow(
                name,
                cls._clamp_pct(percentage),
                item.get("next_reset") or None,
            ))
