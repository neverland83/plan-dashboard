"""数据模型 —— 与 docs/architecture.md「适配器统一契约」严格一致。

约定：
- UsageWindow.percentage 统一为**已用百分比**（0-100），前端计算剩余 = 100 - percentage
- 纯余额型厂商（DeepSeek/Kimi）：windows 为空，用 balance 字段
- percentage_remaining 冗余存一份剩余值，方便前端直接渲染
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class UsageWindow:
    name: str                    # 窗口名："5小时" / "周" / "本月"
    percentage: float            # 已用百分比 0-100（统一口径）
    next_reset: str | None = None   # ISO 8601 时间或 None
    remaining: float = field(default=0.0)  # 剩余百分比 = 100 - percentage

    def __post_init__(self) -> None:
        # 统一口径：夹紧到 [0, 100]，并派生剩余
        self.percentage = max(0.0, min(100.0, float(self.percentage)))
        self.remaining = round(100.0 - self.percentage, 1)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "percentage": self.percentage,
            "remaining": self.remaining,
            "next_reset": self.next_reset,
        }


@dataclass
class PlanUsage:
    provider: str              # 厂商 id（adapter 类型 id）
    display_name: str          # 显示名（来自配置条目 name）
    plan_name: str = ""        # 套餐名（可选，如 lite/pro/max）
    windows: list[UsageWindow] = field(default_factory=list)
    balance: dict | None = None   # 余额型厂商：{"currency","total","granted","topped_up","available",...}
    raw: dict = field(default_factory=dict)   # 原始响应（调试用）
    error: str | None = None      # 出错信息；None 表示成功
    updated_at: str = ""          # ISO 更新时间

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "display_name": self.display_name,
            "plan_name": self.plan_name,
            "kind": "balance" if (self.windows == [] and self.balance) else "windows",
            "windows": [w.to_dict() for w in self.windows],
            "balance": self.balance,
            "error": self.error,
            "updated_at": self.updated_at,
        }
