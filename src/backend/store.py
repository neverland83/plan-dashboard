"""用量数据仓库：调度刷新 + 缓存最近一次结果（含首次拉取）。

- GET /api/plans 直接读缓存；无缓存时同步刷新一次
- 每个条目独立容错：单条目异常不会中断整体，错误进入该条目的 error 字段
"""
from __future__ import annotations

import logging
import threading

from .adapters import get_adapter
from .config import load_config

logger = logging.getLogger(__name__)


class UsageStore:
    def __init__(self) -> None:
        self._cache: dict[str, dict] = {}      # entry_id -> PlanUsage.to_dict()
        self._order: list[str] = []            # 保持配置顺序
        self._lock = threading.Lock()
        self._refresh_lock = threading.Lock()  # 防并发全量刷新打爆厂商

    # ---- 对外 -------------------------------------------------------------
    def get_all(self, force_refresh_if_empty: bool = True) -> list[dict]:
        def snapshot() -> list[dict | None]:
            with self._lock:
                return [self._cache.get(k) for k in list(self._order)]

        cached = snapshot()
        # 全空（首次调用或配置刚失效）→ 同步拉取一次再返回
        if force_refresh_if_empty and all(item is None for item in cached):
            self.refresh_all()
            cached = snapshot()
        return [item for item in cached if item is not None]

    def refresh_all(self) -> list[dict]:
        with self._refresh_lock:
            config = load_config()
            results: list[dict] = []
            for entry in config.get("providers", []):
                if not isinstance(entry, dict):
                    continue
                if not entry.get("enabled", True):
                    continue
                usage = self._refresh_entry(entry)
                results.append(usage)
            return results

    # ---- 内部 -------------------------------------------------------------
    def _refresh_entry(self, entry: dict) -> dict:
        entry_id = str(entry.get("id") or "")
        ptype = str(entry.get("type") or "manual")
        adapter = get_adapter(ptype)
        if adapter is None:
            from .models import PlanUsage
            usage = PlanUsage(
                provider=ptype,
                display_name=str(entry.get("name") or entry_id),
                error=f"未知厂商类型：{ptype}",
                updated_at=__import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat(timespec="seconds"),
            )
            result = usage.to_dict()
        else:
            try:
                result = adapter.fetch(entry).to_dict()
            except Exception as exc:  # noqa: BLE001 —— 双保险，理论上 adapter 不抛
                logger.exception("adapter %s raised unexpectedly", ptype)
                from .models import PlanUsage
                from .adapters.base import utc_now_iso
                usage = PlanUsage(
                    provider=ptype,
                    display_name=str(entry.get("name") or entry_id),
                    error=f"{type(exc).__name__}: {exc}",
                    updated_at=utc_now_iso(),
                )
                result = usage.to_dict()

        with self._lock:
            if entry_id and entry_id not in self._order:
                self._order.append(entry_id)
            elif not entry_id:
                entry_id = f"__anon{len(self._order)}"
                while entry_id in self._cache:
                    entry_id += "x"
                self._order.append(entry_id)
            result["entry_id"] = entry_id     # 前端卡片排序以此为稳定身份（config 条目 id）
            self._cache[entry_id] = result
        return result

    def invalidate(self) -> None:
        """配置变更后清空缓存顺序与旧条目（保留不存在的会自动淘汰）。"""
        with self._lock:
            self._cache.clear()
            self._order.clear()
