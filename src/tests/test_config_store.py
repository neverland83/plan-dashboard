"""config.py / scheduler 单元测试。"""
from __future__ import annotations

import threading

import pytest

import backend.config as cfg_mod


class TestConfigModule:
    def test_load_missing_returns_default(self, isolated_config):
        cfg = cfg_mod.load_config()
        assert cfg["refresh_interval_minutes"] == 30
        assert cfg["providers"] == []

    def test_save_and_roundtrip(self, isolated_config):
        data = {
            "refresh_interval_minutes": 45,
            "providers": [{"id": "a", "name": "A", "type": "manual",
                           "api_key": "k", "extra": {}, "enabled": True}],
        }
        cfg_mod.save_config(data)
        loaded = cfg_mod.load_config()
        assert loaded == data

    def test_corrupt_json_falls_back(self, isolated_config):
        isolated_config.write_text("{not valid json", encoding="utf-8")
        cfg = cfg_mod.load_config()
        assert cfg["providers"] == []

    def test_sanitize_hides_key_and_sensitive_extra(self, isolated_config):
        cfg = {
            "refresh_interval_minutes": 30,
            "providers": [
                {"id": "z", "name": "智谱", "type": "zhipu", "api_key": "PLAINTEXT",
                 "extra": {"secret_key": "SKSECRET", "host": "https://x"}, "enabled": True},
            ],
        }
        safe = cfg_mod.sanitize_for_frontend(cfg)
        entry = safe["providers"][0]
        assert "api_key" not in entry
        assert entry["has_key"] is True
        assert "secret_key" not in entry["extra"]
        assert entry["extra"]["host"] == "https://x"

    def test_merge_key_semantics(self, isolated_config):
        cfg = {"refresh_interval_minutes": 30, "providers": [
            {"id": "z", "name": "Z", "type": "zhipu", "api_key": "OLD", "extra": {}, "enabled": True},
        ]}
        # None / 空串 = 不修改
        cfg_mod.merge_key_into_entry(cfg, "z", None)
        assert cfg["providers"][0]["api_key"] == "OLD"
        cfg_mod.merge_key_into_entry(cfg, "z", "")
        assert cfg["providers"][0]["api_key"] == "OLD"
        cfg_mod.merge_key_into_entry(cfg, "z", "NEW")
        assert cfg["providers"][0]["api_key"] == "NEW"


class TestScheduler:
    def test_interval_bounds(self, isolated_config):
        from backend.scheduler import RefreshScheduler
        from backend.store import UsageStore
        s = RefreshScheduler(UsageStore())
        assert s.interval_seconds({"refresh_interval_minutes": 30}) == 1800
        assert s.interval_seconds({}) == 1800                      # 默认
        assert s.interval_seconds({"refresh_interval_minutes": 0.001}) == 60   # 下限 1 分钟

    def test_thread_lifecycle(self, isolated_config):
        from backend.scheduler import RefreshScheduler
        from backend.store import UsageStore
        s = RefreshScheduler(UsageStore())
        s.start()
        assert s._thread.is_alive()
        s.stop()
        s._thread.join(timeout=5)
        assert not s._thread.is_alive()

    def test_scheduler_refreshes_in_background(self, isolated_config, mock_http):
        """后台线程真正调用 refresh_all（等一拍验证缓存被填充）。"""
        from tests.conftest import write_config
        write_config(isolated_config, [
            {"id": "m", "name": "手动", "type": "manual",
             "api_key": "", "extra": {"windows": [{"name": "月", "percentage": 5}]},
             "enabled": True},
        ])
        from backend.scheduler import RefreshScheduler
        from backend.store import UsageStore
        store = UsageStore()
        s = RefreshScheduler(store)
        s.start()
        try:
            for _ in range(50):
                if store.get_all(force_refresh_if_empty=False):
                    break
                import time
                time.sleep(0.1)
            else:
                pytest.fail("调度线程 5 秒内未完成首次刷新")
            plans = store.get_all(force_refresh_if_empty=False)
            assert plans[0]["error"] is None
        finally:
            s.stop()
            s._thread.join(timeout=5)
