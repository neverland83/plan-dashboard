"""API 路由测试 —— FastAPI TestClient，全 mock，无真实网络。

覆盖验收标准：
- /api/plans 正确结构（manual 成功、zhipu 无 key 返回错误态不崩）
- 单厂商失败不影响其他
- /api/config GET 脱敏 / POST 保存（含 key 保留语义）
- /api/providers 厂商清单
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import write_config

ZHIPU_OK = {
    "success": True,
    "data": {
        "level": "pro",
        "limits": [
            {"type": "TIME_LIMIT", "percentage": 1, "nextResetTime": 1790000000000},
            {"type": "TOKENS_LIMIT", "percentage": 20, "nextResetTime": 1790500000000},
        ],
    },
}
MINIMAX_OK = {
    "base_resp": {"status_code": 0},
    "model_remains": [{
        "model_name": "general",
        "current_interval_remaining_percent": 80.0,
        "end_time": 1790000000000,
    }],
}


@pytest.fixture()
def client(isolated_config, mock_http):
    """干净的 app（新 store）+ 已安装的 http mock。返回 (TestClient, mock 安装器)。"""
    from backend.store import UsageStore
    import backend.main as main_mod

    main_mod.store = UsageStore()
    with TestClient(main_mod.app) as tc:
        yield tc, mock_http


class TestPlans:
    def test_plans_structure_with_manual_ok_and_zhipu_keyless(self, client):
        tc, _mock = client
        import backend.config as cfg_mod
        write_config(cfg_mod.CONFIG_PATH, [
            {"id": "zhipu-entry", "name": "智谱 GLM Coding", "type": "zhipu",
             "api_key": "", "extra": {}, "enabled": True},
            {"id": "manual-entry", "name": "腾讯云（手动）", "type": "manual",
             "api_key": "", "extra": {"windows": [{"name": "本月", "percentage": 65}]},
             "enabled": True},
        ])

        resp = tc.get("/api/plans")
        assert resp.status_code == 200
        plans = resp.json()["plans"]
        assert len(plans) == 2

        by_id = {p["display_name"]: p for p in plans}
        manual = by_id["腾讯云（手动）"]
        assert manual["error"] is None
        assert manual["windows"][0]["remaining"] == 35.0

        zhipu = by_id["智谱 GLM Coding"]
        assert zhipu["error"] is not None       # 无 key → 错误态而不崩
        assert zhipu["windows"] == []
        assert "API Key" in zhipu["error"]

    def test_success_paths_via_mock(self, client):
        """zhipu / minimax / deepseek 三厂商成功路径 + 数据结构与 key 脱敏。"""
        tc, mock_http_fn = client
        mock_http_fn({
            "open.bigmodel.cn": (200, ZHIPU_OK),
            "coding_plan/remains": (200, MINIMAX_OK),
            "api.deepseek.com/user/balance": (
                200,
                {"is_available": True,
                 "balance_infos": [{"currency": "CNY", "total_balance": "42.50",
                                    "granted_balance": "2.50", "topped_up_balance": "40.00"}]},
            ),
        })
        import backend.config as cfg_mod
        write_config(cfg_mod.CONFIG_PATH, [
            {"id": "z", "name": "智谱", "type": "zhipu",
             "api_key": "SECRETZ", "extra": {}, "enabled": True},
            {"id": "mx", "name": "MiniMax", "type": "minimax",
             "api_key": "SECRETMX", "extra": {}, "enabled": True},
            {"id": "ds", "name": "DeepSeek", "type": "deepseek",
             "api_key": "SECRETDS", "extra": {}, "enabled": True},
            {"id": "m1", "name": "手动A", "type": "manual",
             "api_key": "", "extra": {"windows": [{"name": "5h", "percentage": 10}]},
             "enabled": True},
        ])

        resp = tc.get("/api/plans")
        assert resp.status_code == 200
        text = resp.text
        # key 绝不出现在响应里
        for secret in ("SECRETZ", "SECRETMX", "SECRETDS"):
            assert secret not in text

        plans = resp.json()["plans"]
        by_name = {p["display_name"]: p for p in plans}
        assert len(plans) == 4

        zp = by_name["智谱"]
        assert zp["error"] is None and len(zp["windows"]) == 2
        assert zp["windows"][0]["remaining"] == 99.0

        mx = by_name["MiniMax"]
        assert mx["error"] is None and mx["windows"][0]["percentage"] == 20.0

        ds = by_name["DeepSeek"]
        assert ds["kind"] == "balance"
        assert ds["balance"]["total"] == 42.5 and ds["balance"]["is_available"] is True

    def test_single_provider_failure_does_not_affect_others(self, client):
        tc, mock_http_fn = client
        # minimax 模拟网络层崩溃；其余不受影响
        class BoomClientProps(dict):
            pass
        mock_http_fn({"coding_plan/remains": None})   # 先占位避免漏网保护失效

        # 用一个抛异常的 spec：FakeClient._match 返回 None 会崩在调用处，
        # 交给 adapter 层捕获 → error 态
        from tests.helpers import FakeResponse
        mock_routes = {"coding_plan/remains": "INVALID-JSON-BODY"}
        # 重装 routes：直接 monkeypatch 无法二次生效，改用带原始文本的响应迫使 json() 失败
        import backend.config as cfg_mod
        write_config(cfg_mod.CONFIG_PATH, [
            {"id": "mx", "name": "MiniMax", "type": "minimax",
             "api_key": "k", "extra": {}, "enabled": True},
            {"id": "m1", "name": "手动A", "type": "manual",
             "api_key": "", "extra": {"windows": [{"name": "5h", "percentage": 10}]},
             "enabled": True},
            {"id": "m2", "name": "手动B", "type": "manual",
             "api_key": "", "extra": {"windows": [{"name": "周", "percentage": 90}]},
             "enabled": True},
        ])
        resp = tc.get("/api/plans")
        plans = resp.json()["plans"]
        by_name = {p["display_name"]: p for p in plans}
        assert by_name["MiniMax"]["error"] is not None      # 非法 JSON → 该条目失败
        assert by_name["手动A"]["error"] is None
        assert by_name["手动B"]["error"] is None

    def test_unknown_type_reported_not_crash(self, client):
        tc, _ = client
        import backend.config as cfg_mod
        write_config(cfg_mod.CONFIG_PATH, [
            {"id": "weird", "name": "神秘厂商", "type": "no-such-type",
             "api_key": "", "extra": {}, "enabled": True},
        ])
        resp = tc.get("/api/plans")
        plan = resp.json()["plans"][0]
        assert "未知厂商类型" in plan["error"]

    def test_disabled_entry_excluded(self, client):
        tc, _ = client
        import backend.config as cfg_mod
        write_config(cfg_mod.CONFIG_PATH, [
            {"id": "off", "name": "停用条目", "type": "manual",
             "api_key": "", "extra": {"windows": [{"name": "月", "percentage": 1}]},
             "enabled": False},
        ])
        resp = tc.get("/api/plans")
        assert resp.json()["plans"] == []


class TestConfig:
    def test_get_config_sanitized(self, client):
        tc, _ = client
        import backend.config as cfg_mod
        write_config(cfg_mod.CONFIG_PATH, [
            {"id": "z", "name": "智谱", "type": "zhipu",
             "api_key": "SECRETVALUE123", "extra": {}, "enabled": True},
        ])
        resp = tc.get("/api/config")
        assert "SECRETVALUE123" not in resp.text
        entry = resp.json()["config"]["providers"][0]
        assert entry["has_key"] is True and "api_key" not in entry

    def test_post_config_preserves_existing_key(self, client):
        tc, _ = client
        import backend.config as cfg_mod
        path = cfg_mod.CONFIG_PATH
        write_config(path, [
            {"id": "z", "name": "智谱", "type": "zhipu",
             "api_key": "OLD_REAL_KEY", "extra": {}, "enabled": True},
        ])

        # 前端回显不带 key → api_key 为空字符串 → 后端应保留 OLD_REAL_KEY
        resp = tc.post("/api/config", json={
            "refresh_interval_minutes": 15,
            "providers": [
                {"id": "z", "name": "智谱改", "type": "zhipu",
                 "api_key": "", "extra": {}, "enabled": True},
                {"id": "new1", "name": "新条目", "type": "manual",
                 "api_key": "", "extra": {"windows": [{"name": "月", "percentage": 30}]},
                 "enabled": True},
            ],
        })
        assert resp.status_code == 200
        saved = cfg_mod.load_config()
        assert saved["providers"][0]["api_key"] == "OLD_REAL_KEY"
        assert saved["providers"][0]["name"] == "智谱改"
        assert saved["refresh_interval_minutes"] == 15
        assert len(saved["providers"]) == 2
        assert "OLD_REAL_KEY" not in resp.text

    def test_post_config_sets_new_key(self, client):
        tc, _ = client
        import backend.config as cfg_mod
        resp = tc.post("/api/config", json={
            "refresh_interval_minutes": 30,
            "providers": [{"id": "ds", "name": "DS", "type": "deepseek",
                           "api_key": "NEWKEY999", "extra": {}, "enabled": True}],
        })
        assert resp.status_code == 200
        saved = cfg_mod.load_config()
        assert saved["providers"][0]["api_key"] == "NEWKEY999"


class TestProviders:
    def test_list_providers(self, client):
        tc, _ = client
        data = tc.get("/api/providers").json()
        ids = [p["id"] for p in data["providers"]]
        assert set(ids) >= {"zhipu", "minimax", "deepseek", "kimi", "ark", "manual"}
        for p in data["providers"]:
            assert "name" in p and "needs_key" in p


class TestRefresh:
    def test_refresh_endpoint(self, client):
        tc, _ = client
        import backend.config as cfg_mod
        write_config(cfg_mod.CONFIG_PATH, [
            {"id": "m1", "name": "手动A", "type": "manual",
             "api_key": "", "extra": {"windows": [{"name": "月", "percentage": 20}]},
             "enabled": True},
        ])
        data = tc.post("/api/refresh").json()
        assert data["ok"] is True
        assert data["refreshed"] == 1 and data["succeeded"] == 1 and data["failed"] == 0

    def test_refresh_partial_failure_counted(self, client):
        tc, _ = client
        import backend.config as cfg_mod
        write_config(cfg_mod.CONFIG_PATH, [
            {"id": "m1", "name": "OK", "type": "manual",
             "api_key": "", "extra": {"windows": [{"name": "月", "percentage": 20}]},
             "enabled": True},
            {"id": "bad", "name": "坏类型", "type": "ghost",
             "api_key": "", "extra": {}, "enabled": True},
        ])
        data = tc.post("/api/refresh").json()
        assert data["refreshed"] == 2 and data["succeeded"] == 1 and data["failed"] == 1
