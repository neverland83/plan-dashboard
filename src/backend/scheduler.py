"""定时刷新调度器。

- 后台守护线程按 refresh_interval_minutes（可配，默认 30）周期触发
- 触发时刷新所有启用的 provider 条目，结果缓存进 UsageStore
- 线程内逐条目串行 + 各条目独立容错，单厂商失败不影响其他
"""
from __future__ import annotations

import logging
import threading

from .config import load_config
from .store import UsageStore

logger = logging.getLogger(__name__)


class RefreshScheduler:
    def __init__(self, store: UsageStore) -> None:
        self._store = store
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="refresh-scheduler", daemon=True)
        self._thread.start()
        logger.info("scheduler started")

    def stop(self) -> None:
        self._stop.set()

    def interval_seconds(self, config: dict | None = None) -> int:
        cfg = config or load_config()
        try:
            minutes = float(cfg.get("refresh_interval_minutes") or 30)
        except (TypeError, ValueError):
            minutes = 30.0
        return max(60, int(minutes * 60))  # 下限 1 分钟，防止打爆厂商接口

    def _run(self) -> None:
        # 启动即做一次首刷，让看板打开就有数据；之后按周期轮转
        try:
            self._store.refresh_all()
        except Exception:  # noqa: BLE001 —— 调度线程绝不退出
            logger.exception("initial refresh failed")
        while not self._stop.wait(self.interval_seconds()):
            try:
                logger.info("scheduled refresh triggered")
                self._store.refresh_all()
            except Exception:  # noqa: BLE001 —— 调度线程绝不退出
                logger.exception("scheduled refresh failed")
