"""手动录入兜底适配器。

接口档案：docs/research/providers/manual.md
- 从配置 extra.windows 直接读百分比返回，不发任何网络请求
- extra.windows: [{ "name": "本月", "percentage": 65 }, ...]
  percentage 语义遵循全局口径 = **已用百分比**（剩余 = 100 - 已用）；
  也兼容直接填 remaining（剩余百分比）的写法
- 不需要 API Key
"""
from __future__ import annotations

from .base import BaseAdapter
from ..models import PlanUsage, UsageWindow


class ManualAdapter(BaseAdapter):
    provider_id = "manual"
    display_name = "手动录入"
    needs_key = False
    supports_models = False     # 手动型无模型列表查询能力（详情弹框显示空列表）

    def _fetch(self, api_key: str, extra: dict, usage: PlanUsage) -> PlanUsage:
        windows_cfg = extra.get("windows")
        note = extra.get("note")
        if isinstance(note, str) and note:
            usage.plan_name = note

        if not isinstance(windows_cfg, list):
            return self._fail(usage, "手动条目缺少 extra.windows 配置")

        for i, w in enumerate(windows_cfg):
            if not isinstance(w, dict):
                continue
            name = str(w.get("name") or f"窗口{i + 1}")
            pct = self._to_float(w.get("percentage"))
            if pct is None:
                remaining = self._to_float(w.get("remaining"))
                if remaining is None:
                    continue
                pct = 100.0 - self._clamp_pct(remaining)
            reset = w.get("next_reset") or None
            usage.windows.append(UsageWindow(name, self._clamp_pct(pct), reset))

        if not usage.windows:
            return self._fail(usage, "extra.windows 中没有有效的窗口数据")
        return usage
