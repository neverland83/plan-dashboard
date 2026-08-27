"""适配器注册表。

新增厂商：写一个 adapter 文件（继承 BaseAdapter），在这里注册即可，
核心路由/调度器零改动 —— 符合 docs/new-provider-checklist.md 的接入规范。
"""
from __future__ import annotations

from .base import BaseAdapter
from .zhipu import ZhipuAdapter
from .minimax import MiniMaxAdapter
from .deepseek import DeepSeekAdapter
from .kimi import KimiAdapter
from .ark import ArkAdapter
from .manual import ManualAdapter

# provider type id -> adapter 单例
_REGISTRY: dict[str, BaseAdapter] = {}
for _cls in (ZhipuAdapter, MiniMaxAdapter, DeepSeekAdapter, KimiAdapter, ArkAdapter, ManualAdapter):
    _inst = _cls()
    _REGISTRY[_inst.provider_id] = _inst

# 前端配置面板用的厂商元数据清单
PROVIDER_META: list[dict] = [
    {
        "id": "zhipu",
        "name": "智谱 GLM Coding（含 Z.ai）",
        "kind": "windows",
        "needs_key": True,
        "extra_fields": [
            {"key": "host", "label": "Host（Z.ai 填 https://api.z.ai，留空为国内）", "required": False},
            {"key": "team_organization_id", "label": "团队版 Organization ID（可选）", "required": False},
            {"key": "team_project_id", "label": "团队版 Project ID（可选）", "required": False},
        ],
    },
    {
        "id": "minimax",
        "name": "MiniMax Coding Plan",
        "kind": "windows",
        "needs_key": True,
        "extra_fields": [
            {"key": "region", "label": "区域：cn（默认）/ intl 国际版", "required": False},
        ],
    },
    {
        "id": "deepseek",
        "name": "DeepSeek（余额）",
        "kind": "balance",
        "needs_key": True,
        "extra_fields": [],
    },
    {
        "id": "kimi",
        "name": "Kimi / Moonshot（余额）",
        "kind": "balance",
        "needs_key": True,
        "extra_fields": [
            {"key": "host", "label": "Host（国际版 api.kimi.ai，留空为国内）", "required": False},
        ],
    },
    {
        "id": "ark",
        "name": "火山方舟（AK/SK 签名）",
        "kind": "windows",
        "needs_key": True,
        "extra_fields": [
            {"key": "access_key", "label": "AccessKey ID（或直接填在 API Key 栏）", "required": True},
            {"key": "secret_key", "label": "Secret Access Key", "required": True},
            {"key": "plan_quota", "label": "套餐总配额（Tokens，如 50000000）", "required": True},
            {"key": "object_names", "label": "模型过滤（逗号分隔，可选）", "required": False},
            {"key": "region", "label": "Region（默认 cn-beijing）", "required": False},
        ],
    },
    {
        "id": "manual",
        "name": "手动录入（兜底）",
        "kind": "windows",
        "needs_key": False,
        "extra_fields": [],
    },
]


def get_adapter(provider_type: str) -> BaseAdapter | None:
    return _REGISTRY.get(provider_type)


def all_adapters() -> dict[str, BaseAdapter]:
    return dict(_REGISTRY)
