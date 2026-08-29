"""卡片详情路由测试：/api/plans/{id}/info 与 /api/plans/{id}/refresh-info。

覆盖验收标准：
- 首次 GET → 实际查一次（mock）→ 写缓存 → 第二次 GET 直接返回缓存（不再请求）
- POST refresh-info 忽略缓存强制重查
- plan_name 三层回退：adapter → config.json 手填 → 按量/未知
- 配置变更（plan_name 手填）后 refresh-info 能看到来源切回 config
- 错误态：无 key / 第三方失败 → 带 error 但保留已有缓存
- 前端契约：modal HTML 含「详情」「刷新」按钮
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from tests.conftest import write_config

ZHIPU_MODELS = {"object": "list", "data": [
    {"id": "glm-4-plus", "owned_by": "zhipu"},
    {"id": "glm-4-flash", "owned_by": "zhipu"},
]}
ZHIPU_QUOTA_LITE = {
    "success": True,
    "data": {"level": "lite", "limits": [
        {"type": "TIME_LIMIT", "percentage": 1, "nextResetTime": 1790000000000}]},
}


@pytest.fixture()
def client(isolated_config, mock_http, tmp_path, monkeypatch):
    """干净的 app + 缓存路径指向临时目录（测试互不污染真实 data/）。"""
    import backend.main as main_mod
    from backend.model_cache import ModelCacheService
    from backend.store import UsageStore

    main_mod.store = UsageStore()
    cache_svc = ModelCacheService(tmp_path / "mc" / "model_cache.json")
    monkeypatch.setattr(main_mod, "model_cache", cache_svc)
    with TestClient(main_mod.app) as tc:
        yield tc, mock_http, cache_svc


class TestInfoRoutes:
    def test_unknown_entry_404(self, client):
        tc, _, _ = client
        resp = tc.get("/api/plans/ghost/info")
        assert resp.status_code == 404
        assert tc.post("/api/plans/ghost/refresh-info").status_code == 404
        assert tc.delete("/api/plans/ghost/info").status_code == 404

    def test_first_get_fetches_second_get_uses_cache(self, client):
        """核心失效策略（D2）：首查一次 → 之后读缓存。"""
        tc, mock_http_fn, cache = client
        routes = {"open.bigmodel.cn/api/paas/v4/models": (200, ZHIPU_MODELS),
                  "quota/limit": (200, ZHIPU_QUOTA_LITE)}
        mock_http_fn(routes)
        write_config(tc.app and __import__("backend.config", fromlist=["x"]).CONFIG_PATH, [
            {"id": "z", "name": "智谱", "type": "zhipu",
             "api_key": "K", "extra": {}, "enabled": True},
        ])

        r1 = tc.get("/api/plans/z/info").json()
        assert r1["ok"] is True
        assert r1["plan_name"] == "GLM Coding Lite"
        assert r1["plan_name_source"] == "adapter"
        assert [m["id"] for m in r1["models"]] == ["glm-4-flash", "glm-4-plus"]
        assert r1["fetched_at"] is not None
        assert cache.has("z")

        # 拆掉 mock：第二次 GET 必须直接吃缓存，不再发请求
        mock_http_fn({})
        r2 = tc.get("/api/plans/z/info").json()
        assert r2 == r1

    def test_refresh_info_forces_refetch(self, client):
        """POST refresh-info 忽略缓存强制重查。"""
        tc, mock_http_fn, cache = client
        mock_http_fn({"api.deepseek.com/models": (200, {"data": [{"id": "deepseek-chat"}]})})
        import backend.config as cfg_mod
        write_config(cfg_mod.CONFIG_PATH, [
            {"id": "ds", "name": "DS", "type": "deepseek",
             "api_key": "K", "extra": {}, "enabled": True},
        ])
        r1 = tc.get("/api/plans/ds/info").json()
        assert [m["id"] for m in r1["models"]] == ["deepseek-chat"]

        # 换数据再强刷 → 拿到新列表
        mock_http_fn({"api.deepseek.com/models": (200, {"data": [
            {"id": "deepseek-chat"}, {"id": "deepseek-reasoner"}]})})
        r2 = tc.post("/api/plans/ds/refresh-info").json()
        assert [m["id"] for m in r2["models"]] == ["deepseek-chat", "deepseek-reasoner"]
        assert cache.get("ds")["models"] == r2["models"]

    def test_delete_clears_cache_then_next_get_refetches(self, client):
        tc, mock_http_fn, cache = client
        mock_http_fn({"api.deepseek.com/models": (200, {"data": [{"id": "deepseek-chat"}]})})
        import backend.config as cfg_mod
        write_config(cfg_mod.CONFIG_PATH, [
            {"id": "ds", "name": "DS", "type": "deepseek",
             "api_key": "K", "extra": {}, "enabled": True},
        ])
        tc.get("/api/plans/ds/info")
        assert cache.has("ds")
        assert tc.delete("/api/plans/ds/info").json()["cleared"] == "ds"
        assert not cache.has("ds")
        # 无 mock 保护拆除 → 重新首查会再请求（仍被 mock 住，返回同样数据）
        r = tc.get("/api/plans/ds/info").json()
        assert [m["id"] for m in r["models"]] == ["deepseek-chat"]

    def test_api_contract_untouched_plans_route(self, client):
        """不改动既有 /api/plans 契约：结构仍为 {ok, plans, generated_at}。"""
        tc, _, _ = client
        import backend.config as cfg_mod
        write_config(cfg_mod.CONFIG_PATH, [
            {"id": "m", "name": "手动", "type": "manual", "api_key": "",
             "extra": {"windows": [{"name": "月", "percentage": 10}]}, "enabled": True},
        ])
        data = tc.get("/api/plans").json()
        assert data["ok"] is True and "generated_at" in data
        assert data["plans"][0]["entry_id"] == "m"


class TestPlanNameFallback:
    """三层回退（D5'）：adapter 自报 → config.json 手填 → 按量/未知。"""

    def _cfg(self, path, plan_name=None):
        entry = {"id": "ds", "name": "DS", "type": "deepseek",
                 "api_key": "K", "extra": {}, "enabled": True}
        if plan_name is not None:
            entry["plan_name"] = plan_name
        write_config(path, [entry])

    def test_layer1_adapter_wins_over_config(self, client):
        tc, mock_http_fn, _ = client
        mock_http_fn({"api.deepseek.com/models": (200, {"data": [{"id": "deepseek-chat"}]})})
        import backend.config as cfg_mod
        self._cfg(cfg_mod.CONFIG_PATH, plan_name="手填档名")
        data = tc.get("/api/plans/ds/info").json()
        # deepseek 无套餐 → adapter None → 落到 config 手填
        assert data["plan_name"] == "手填档名"
        assert data["plan_name_source"] == "config"

    def test_layer1_adapter_used_when_available(self, client):
        tc, mock_http_fn, _ = client
        mock_http_fn({
            "open.bigmodel.cn/api/paas/v4/models": (200, ZHIPU_MODELS),
            "quota/limit": (200, ZHIPU_QUOTA_LITE),
        })
        import backend.config as cfg_mod
        write_config(cfg_mod.CONFIG_PATH, [
            {"id": "z", "name": "智谱", "type": "zhipu", "api_key": "K",
             "plan_name": "手填档名", "extra": {}, "enabled": True},
        ])
        data = tc.get("/api/plans/z/info").json()
        assert data["plan_name"] == "GLM Coding Lite"   # adapter 赢过手填
        assert data["plan_name_source"] == "adapter"

    def test_layer3_all_missing_shows_payg(self, client):
        tc, mock_http_fn, _ = client
        mock_http_fn({"api.deepseek.com/models": (200, {"data": [{"id": "deepseek-chat"}]})})
        import backend.config as cfg_mod
        self._cfg(cfg_mod.CONFIG_PATH)                  # 无手填
        data = tc.get("/api/plans/ds/info").json()
        assert data["plan_name"] is None
        assert data["plan_name_source"] == "none"       # 前端显示「按量调用/未知档级」

    def test_config_change_visible_after_refresh(self, client):
        """验收 4：config.json 里 plan_name 变更后，前端刷新按钮触发能看到来源切回 config。"""
        tc, mock_http_fn, cache = client
        mock_http_fn({"api.deepseek.com/models": (200, {"data": [{"id": "deepseek-chat"}]})})
        import backend.config as cfg_mod
        self._cfg(cfg_mod.CONFIG_PATH, plan_name="旧档名")
        r1 = tc.get("/api/plans/ds/info").json()
        assert r1["plan_name"] == "旧档名" and r1["plan_name_source"] == "config"

        # 用户改配置：换成新档名
        self._cfg(cfg_mod.CONFIG_PATH, plan_name="DeepSeek 手动备注档")
        r2 = tc.post("/api/plans/ds/refresh-info").json()
        assert r2["plan_name"] == "DeepSeek 手动备注档"
        assert r2["plan_name_source"] == "config"
        assert cache.get("ds")["plan_name"] == "DeepSeek 手动备注档"

    def test_adapter_failure_falls_back_to_config(self, client):
        """models 查询失败（401）→ 返回错误态；plan_name 仍走手填回退。"""
        tc, mock_http_fn, _ = client
        mock_http_fn({"api.deepseek.com/models": (401, {"error": "bad"})})
        import backend.config as cfg_mod
        self._cfg(cfg_mod.CONFIG_PATH, plan_name="手动档")
        data = tc.post("/api/plans/ds/refresh-info").json()
        assert data["error"] is not None
        assert data["models"] == []
        assert data["plan_name"] == "手动档"
        assert data["plan_name_source"] == "config"


class TestErrorStates:
    def test_missing_key_keeps_old_cache(self, client):
        """验收错误态：key 被清掉后 refresh-info 报错但仍展示已有缓存。"""
        tc, mock_http_fn, cache = client
        mock_http_fn({"api.deepseek.com/models": (200, {"data": [{"id": "deepseek-chat"}]})})
        import backend.config as cfg_mod
        path = cfg_mod.CONFIG_PATH
        write_config(path, [{"id": "ds", "name": "DS", "type": "deepseek",
                             "api_key": "K", "extra": {}, "enabled": True}])
        r1 = tc.get("/api/plans/ds/info").json()
        assert r1["error"] is None

        write_config(path, [{"id": "ds", "name": "DS", "type": "deepseek",
                             "api_key": "", "extra": {}, "enabled": True}])
        r2 = tc.post("/api/plans/ds/refresh-info").json()
        assert "API Key" in r2["error"]
        assert [m["id"] for m in r2["models"]] == ["deepseek-chat"]   # 旧缓存保留
        assert r2["fetched_at"] == r1["fetched_at"]                   # 时间戳不前移

    def test_unknown_provider_type_reports_error(self, client):
        tc, _, _ = client
        import backend.config as cfg_mod
        write_config(cfg_mod.CONFIG_PATH, [
            {"id": "weird", "name": "神秘", "type": "ghost",
             "api_key": "", "extra": {}, "enabled": True},
        ])
        data = tc.get("/api/plans/weird/info").json()
        assert "未知厂商类型" in data["error"]
        assert data["models"] == []

    def test_manual_entry_reports_empty_models(self, client):
        """手动型条目：详情可用但无模型数据（不报错）。"""
        tc, _, _ = client
        import backend.config as cfg_mod
        write_config(cfg_mod.CONFIG_PATH, [
            {"id": "m", "name": "手动", "type": "manual", "api_key": "",
             "extra": {"windows": [{"name": "月", "percentage": 10}]},
              "plan_name": "自填套餐", "enabled": True},
        ])
        data = tc.get("/api/plans/m/info").json()
        assert data["error"] is None
        assert data["models"] == []
        assert data["plan_name"] == "自填套餐"
        assert data["plan_name_source"] == "config"

    def test_response_never_contains_api_key(self, client):
        tc, mock_http_fn, _ = client
        secret = "SECRET_INFO_KEY_42"
        mock_http_fn({"api.deepseek.com/models": (200, {"data": [{"id": "deepseek-chat"}]})})
        import backend.config as cfg_mod
        write_config(cfg_mod.CONFIG_PATH, [
            {"id": "ds", "name": "DS", "type": "deepseek",
             "api_key": secret, "extra": {}, "enabled": True},
        ])
        text = tc.get("/api/plans/ds/info").text + tc.post(
            "/api/plans/ds/refresh-info").text
        assert secret not in text


class TestFrontendContract:
    """验收 5/前端：modal HTML 出现「详情」「刷新」按钮与搜索框。"""

    def test_modal_html_markers(self):
        html = (__import__("pathlib").Path(__file__).resolve().parent.parent
                / "frontend" / "index.html").read_text(encoding="utf-8")
        assert 'id="info-dialog"' in html
        assert "详情" in html
        assert "刷新 ↻" in html
        assert 'id="info-search"' in html
        assert 'id="info-model-list"' in html
        assert 'data-action="detail"' in html
        # 原生 <dialog>（D3）
        assert "<dialog" in html

    def test_info_button_rendered_per_card(self):
        """每张卡片的 footer 都渲染「详情」入口（cardHTML 模板含 detail 按钮）。"""
        html = (__import__("pathlib").Path(__file__).resolve().parent.parent
                / "frontend" / "index.html").read_text(encoding="utf-8")
        assert 'class="detail-btn"' in html
        assert "card-foot" in html
