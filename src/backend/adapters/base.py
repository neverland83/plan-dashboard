"""适配器基类 —— docs/architecture.md「适配器统一契约」。

关键约定：
- fetch(api_key, config) -> PlanUsage
- **适配器不得向调用方抛异常**：任何失败都要返回带 error 的 PlanUsage
- raw 字段放原始响应（调试用）；不得把 api_key 放进结果
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

import httpx

from ..models import PlanUsage

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15.0


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class BaseAdapter(ABC):
    """所有厂商适配器的基类。子类设置 `provider_id` / `display_name`。"""

    provider_id: str = "base"
    display_name: str = "未命名"
    needs_key: bool = True          # 是否必须 API Key 才能查询
    kind: str = "windows"           # "windows" | "balance"
    supports_models: bool = True    # 是否有模型列表查询能力（manual 为 False；仅详情弹框用）

    @abstractmethod
    def _fetch(self, api_key: str, extra: dict, usage: PlanUsage) -> PlanUsage:
        """实际请求逻辑（子类实现）。

        usage 为已按条目填充 provider/display_name/updated_at 的壳对象，
        子类填充 windows/balance/raw/error 后返回。extra 为该条目的额外配置。
        """

    # ---- 对外入口：统一容错，绝不抛异常 ----------------------------------
    def fetch(self, entry: dict) -> PlanUsage:
        entry_id = entry.get("id") or self.provider_id
        display_name = entry.get("name") or self.display_name
        api_key = (entry.get("api_key") or "").strip()
        extra = entry.get("extra") or {}
        if not isinstance(extra, dict):
            extra = {}

        usage = PlanUsage(
            provider=self.provider_id,
            display_name=display_name,
            updated_at=utc_now_iso(),
        )

        if self.needs_key and not api_key:
            usage.error = "缺少 API Key（请在配置面板填写）"
            logger.warning("adapter %s entry=%s: %s", self.provider_id, entry_id, usage.error)
            return usage

        try:
            return self._fetch(api_key, extra, usage)
        except Exception as exc:  # noqa: BLE001 —— 契约要求绝不抛异常
            usage.error = f"{type(exc).__name__}: {exc}"
            logger.warning("adapter %s entry=%s failed: %s", self.provider_id, entry_id, usage.error)
            return usage

    # ---- 卡片详情扩展（brief 2026-08-29：Model Info + Plan 档级缓存） ------
    def fetch_models(self, api_key: str, extra: dict) -> list[str]:
        """返回该 provider 支持的模型 id 列表（详情弹框用）。

        返回 [] 表示不支持查询（如手动型）或查询失败。
        与 fetch 同契约：**适配器不应抛异常**；失败请 return []。
        """
        return []

    def fetch_plan_name(self, api_key: str, extra: dict) -> str | None:
        """返回当前购买的 Plan 档级名（如 'GLM Coding Lite'），无法判定返回 None。

        与 fetch 同契约：**适配器不应抛异常**；失败请 return None。
        None 时由路由层按「adapter → config.json 手填 → 按量/未知」三层回退。
        """
        return None

    # ---- 共用小工具 -------------------------------------------------------
    def _fetch_models_openai_compat(self, url: str, api_key: str) -> list[str]:
        """GET OpenAI 兼容 /models 并提取模型 id 列表（去重 + 稳定排序）。

        各家（智谱/MiniMax/DeepSeek/Kimi/StepFun/百炼兼容模式）的模型列表
        端点均为 `Authorization: Bearer <key>` + `{"data": [{"id": ...}]}` 结构，
        统一走这里，失败（网络/HTTP>=400/非 JSON/结构异常）一律返回 []。
        """
        headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
                resp = client.get(url, headers=headers)
        except Exception as exc:  # noqa: BLE001 —— 契约要求绝不抛异常
            logger.warning("fetch_models %s failed: %s", url, exc)
            return []
        if resp.status_code >= 400:
            logger.warning("fetch_models %s: HTTP %s", url, resp.status_code)
            return []
        try:
            body = resp.json()
        except ValueError:
            return []
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list):
            return []
        ids: list[str] = []
        for item in data:
            if isinstance(item, dict):
                mid = item.get("id")
            elif isinstance(item, str):
                mid = item
            else:
                continue
            if isinstance(mid, str) and mid.strip():
                ids.append(mid.strip())
        return sorted(set(ids))

    @staticmethod
    def _http_get(
        url: str,
        headers: dict[str, str],
        extra_headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        merged = {**headers, **(extra_headers or {})}
        with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url, headers=merged)
            resp.raise_for_status()
            return resp

    @staticmethod
    def _http_post_json(url: str, payload: dict, headers: dict[str, str]) -> dict:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    def _fail(usage: PlanUsage, message: str) -> PlanUsage:
        """错误态收尾：填入 error 并原样返回（保持条目名等已填字段）。"""
        usage.error = message
        logger.warning("%s: %s", usage.display_name, message)
        return usage

    @staticmethod
    def _to_float(value: Any, default: float | None = None) -> float | None:
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clamp_pct(value: float) -> float:
        return max(0.0, min(100.0, float(value)))


# 常见窗口名（与 CC Switch 对齐）
WIN_5H = "5小时"
WIN_WEEK = "周"          # 智谱 TOKENS_LIMIT 文档口径为 7 天/周
WIN_7D = "7天"
WIN_MONTH = "本月"
