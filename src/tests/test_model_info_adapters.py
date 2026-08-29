"""各 adapter 的 fetch_models / fetch_plan_name 测试（brief 2026-08-29）。

- 正常路径返回正确
- HTTP 错误 / 401 / 503 / 垃圾响应 → 返回空值（[] / None）而不是抛异常
- 全部 mock 网络，禁止真实请求

注意：base.fetch_models / fetch_plan_name 的默认实现（manual 不支持）与
三层回退的路由层测试分别在 test_adapters.py 契约段与本文件末尾。
"""
from __future__ import annotations

import pytest

from backend.adapters.zhipu import ZhipuAdapter
from backend.adapters.minimax import MiniMaxAdapter
from backend.adapters.deepseek import DeepSeekAdapter
from backend.adapters.kimi import KimiAdapter
from backend.adapters.ark import ArkAdapter
from backend.adapters.stepfun import StepFunAdapter
from backend.adapters.bailian import BailianAdapter
from backend.adapters.manual import ManualAdapter


MODELS_BODY = {
    "object": "list",
    "data": [
        {"id": "model-b", "object": "model", "owned_by": "vendor"},
        {"id": "model-a", "object": "model", "owned_by": "vendor"},
        {"id": "model-a", "object": "model", "owned_by": "vendor"},   # 重复 → 去重
    ],
}


# ────────────────────────────── zhipu ──────────────────────────────
class TestZhipuInfo:
    def test_fetch_models_ok(self, mock_http):
        mock_http({"open.bigmodel.cn/api/paas/v4/models": (200, MODELS_BODY)})
        ids = ZhipuAdapter().fetch_models("k", {})
        assert ids == ["model-a", "model-b"]          # 去重 + 排序

    def test_fetch_models_zai_host(self, mock_http):
        mock_http({"api.z.ai/api/paas/v4/models": (200, MODELS_BODY)})
        ids = ZhipuAdapter().fetch_models("k", {"host": "https://api.z.ai"})
        assert ids == ["model-a", "model-b"]

    def test_fetch_plan_name_adapter_level(self, mock_http):
        """quota/limit 响应 data.level=lite → 'GLM Coding Lite'（adapter 层）。"""
        mock_http({"open.bigmodel.cn/api/monitor/usage/quota/limit": (200, {
            "success": True,
            "data": {"level": "lite", "limits": []},
        })})
        assert ZhipuAdapter().fetch_plan_name("k", {}) == "GLM Coding Lite"

    def test_fetch_plan_name_unknown_level_passthrough(self, mock_http):
        mock_http({"quota/limit": (200, {"success": True, "data": {"level": "team-x"}})})
        assert ZhipuAdapter().fetch_plan_name("k", {}) == "team-x"

    def test_fetch_plan_name_no_key_returns_none(self):
        assert ZhipuAdapter().fetch_plan_name("", {}) is None

    def test_fetch_plan_name_auth_error_returns_none(self, mock_http):
        mock_http({"quota/limit": (401, {"success": False})})
        assert ZhipuAdapter().fetch_plan_name("bad", {}) is None

    def test_fetch_models_error_paths_return_empty(self, mock_http):
        """401 / 500 / 非 JSON → 返回 [] 而不是抛异常。"""
        for status, payload in ((401, {"error": "bad key"}), (503, {"busy": True}),
                                (200, "-not-json-")):
            mock_http({"open.bigmodel.cn/api/paas/v4/models": (status, payload)})
            assert ZhipuAdapter().fetch_models("k", {}) == []


# ────────────────────────────── minimax ──────────────────────────────
class TestMiniMaxInfo:
    def test_fetch_models_ok(self, mock_http):
        mock_http({"api.minimaxi.com/v1/models": (200, MODELS_BODY)})
        assert MiniMaxAdapter().fetch_models("k", {}) == ["model-a", "model-b"]

    def test_fetch_models_intl_host(self, mock_http):
        mock_http({"api.minimax.io/v1/models": (200, MODELS_BODY)})
        assert MiniMaxAdapter().fetch_models("k", {"region": "intl"}) == ["model-a", "model-b"]

    def test_fetch_models_401_returns_empty(self, mock_http):
        mock_http({"api.minimaxi.com/v1/models": (401, {"error": "x"})})
        assert MiniMaxAdapter().fetch_models("bad", {}) == []

    def test_fetch_plan_name_general_present(self, mock_http):
        mock_http({"coding_plan/remains": (200, {
            "base_resp": {"status_code": 0},
            "model_remains": [
                {"model_name": "video", "current_interval_remaining_percent": 5},
                {"model_name": "general", "current_interval_remaining_percent": 80},
            ],
        })})
        assert MiniMaxAdapter().fetch_plan_name("k", {}) == "MiniMax Coding Plan"

    def test_fetch_plan_name_business_error_returns_none(self, mock_http):
        mock_http({"coding_plan/remains": (
            200, {"base_resp": {"status_code": 1004, "status_msg": "invalid"}})})
        assert MiniMaxAdapter().fetch_plan_name("bad", {}) is None

    def test_fetch_plan_name_no_key_returns_none(self):
        assert MiniMaxAdapter().fetch_plan_name("", {}) is None


# ────────────────────────────── deepseek ──────────────────────────────
class TestDeepSeekInfo:
    def test_fetch_models_ok(self, mock_http):
        mock_http({"api.deepseek.com/models": (200, MODELS_BODY)})
        assert DeepSeekAdapter().fetch_models("k", {}) == ["model-a", "model-b"]

    def test_fetch_models_401_and_503_return_empty(self, mock_http):
        mock_http({"api.deepseek.com/models": (401, {"error": "x"})})
        assert DeepSeekAdapter().fetch_models("bad", {}) == []
        mock_http({"api.deepseek.com/models": (503, {"error": "busy"})})
        assert DeepSeekAdapter().fetch_models("k", {}) == []

    def test_fetch_plan_name_is_none_payg(self):
        """DeepSeek 按量计费无套餐 → None（回退 config 手填）。"""
        assert DeepSeekAdapter().fetch_plan_name("k", {}) is None


# ────────────────────────────── kimi ──────────────────────────────
class TestKimiInfo:
    def test_fetch_models_ok(self, mock_http):
        mock_http({"api.moonshot.cn/v1/models": (200, MODELS_BODY)})
        assert KimiAdapter().fetch_models("k", {}) == ["model-a", "model-b"]

    def test_fetch_models_intl_host(self, mock_http):
        mock_http({"api.kimi.ai/v1/models": (200, MODELS_BODY)})
        assert KimiAdapter().fetch_models("k", {"host": "https://api.kimi.ai"}) == ["model-a", "model-b"]

    def test_fetch_models_garbage_returns_empty(self, mock_http):
        mock_http({"api.moonshot.cn/v1/models": (200, "-not-json-")})
        assert KimiAdapter().fetch_models("k", {}) == []

    def test_fetch_plan_name_is_none_payg(self):
        assert KimiAdapter().fetch_plan_name("k", {}) is None


# ────────────────────────────── ark ──────────────────────────────
class TestArkInfo:
    ENTRY_AK, ENTRY_SK = "AKTEST", "SKTEST"

    def _extra(self) -> dict:
        return {"access_key": self.ENTRY_AK, "secret_key": self.ENTRY_SK,
                "region": "cn-beijing"}

    def test_fetch_models_via_list_foundation_models(self, mock_http):
        mock_http({"Action=ListFoundationModels": (200, {
            "ResponseMetadata": {},
            "Result": {"Models": [
                {"ModelName": "doubao-seed-1.8"},
                {"ModelName": "doubao-seed-code"},
                {"ModelName": "doubao-seed-1.8"},      # 去重
                "garbage",                              # 跳过
            ]},
        })})
        ids = ArkAdapter().fetch_models(self.ENTRY_AK, self._extra())
        assert ids == ["doubao-seed-1.8", "doubao-seed-code"]

    def test_fetch_models_missing_credentials_return_empty(self):
        assert ArkAdapter().fetch_models("AK-only", {}) == []

    def test_fetch_models_auth_error_returns_empty(self, mock_http):
        mock_http({"Action=ListFoundationModels": (403, {"ResponseMetadata": {}})})
        assert ArkAdapter().fetch_models(self.ENTRY_AK, self._extra()) == []

    def test_fetch_models_business_error_returns_empty(self, mock_http):
        mock_http({"Action=ListFoundationModels": (200, {
            "ResponseMetadata": {"Error": {"Code": "InternalError", "Message": "boom"}},
        })})
        assert ArkAdapter().fetch_models(self.ENTRY_AK, self._extra()) == []

    def test_fetch_plan_name_from_plan_type(self, mock_http):
        """Result.PlanType 优先 → 'Agent Plan Pro'（adapter 层自报档级）。"""
        mock_http({"Action=GetAFPUsage": (200, {
            "ResponseMetadata": {},
            "Result": {"PlanType": "Pro", "AFPFiveHour": {"Quota": 1, "Used": 0}},
        })})
        assert ArkAdapter().fetch_plan_name(self.ENTRY_AK, self._extra()) == "Agent Plan Pro"

    def test_fetch_plan_name_from_quota_map_max_tier(self, mock_http):
        """PlanType 缺失 → PlanNameToPurchaseQuotaMap 取配额最大档。"""
        mock_http({"Action=GetAFPUsage": (200, {
            "ResponseMetadata": {},
            "Result": {
                "PlanNameToPurchaseQuotaMap": {"Small": 100, "Medium": 500, "Large": 200},
            },
        })})
        name = ArkAdapter().fetch_plan_name(self.ENTRY_AK, self._extra())
        assert name == "Agent Plan Medium"

    def test_fetch_plan_name_quota_map_bad_values_skipped(self, mock_http):
        """配额非法（非数值/负数）→ 跳过该档；全非法 → None。"""
        mock_http({"Action=GetAFPUsage": (200, {
            "ResponseMetadata": {},
            "Result": {"PlanNameToPurchaseQuotaMap": {"Small": "bad", "Tiny": -5}},
        })})
        assert ArkAdapter().fetch_plan_name(self.ENTRY_AK, self._extra()) is None

    def test_fetch_plan_name_falls_to_coding_plan_active(self, mock_http):
        """AFP 无档级 → 探测 GetCodingPlanUsage，Status=Active → 'Coding Plan'。"""
        mock_http({
            "Action=GetAFPUsage": (200, {"ResponseMetadata": {}, "Result": {}}),
            "Action=GetCodingPlanUsage": (200, {
                "ResponseMetadata": {}, "Result": {"Status": "Active"}}),
        })
        assert ArkAdapter().fetch_plan_name(self.ENTRY_AK, self._extra()) == "Coding Plan"

    def test_fetch_plan_name_all_probes_fail_returns_none(self, mock_http):
        mock_http({"Action=GetAFPUsage": (500, {"ResponseMetadata": {}})})
        assert ArkAdapter().fetch_plan_name(self.ENTRY_AK, self._extra()) is None

    def test_fetch_plan_name_no_credentials_returns_none(self):
        assert ArkAdapter().fetch_plan_name("", {}) is None


# ────────────────────────────── stepfun ──────────────────────────────
class TestStepFunInfo:
    def test_fetch_models_ok(self, mock_http):
        mock_http({"api.stepfun.com/v1/models": (200, MODELS_BODY)})
        assert StepFunAdapter().fetch_models("k", {}) == ["model-a", "model-b"]

    def test_fetch_models_401_returns_empty(self, mock_http):
        mock_http({"api.stepfun.com/v1/models": (401, {"error": "x"})})
        assert StepFunAdapter().fetch_models("bad", {}) == []

    def test_fetch_plan_name_is_none_no_api(self):
        """Step Plan 月池官方无查询 API → None（brief 指定）。"""
        assert StepFunAdapter().fetch_plan_name("k", {}) is None


# ────────────────────────────── bailian ──────────────────────────────
class TestBailianInfo:
    @staticmethod
    def _proc(stdout="", stderr="", returncode=0):
        from types import SimpleNamespace
        return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)

    @pytest.fixture()
    def mock_bl(self, monkeypatch):
        holder = {"which": "bl", "proc": self._proc()}
        monkeypatch.setattr(
            "backend.adapters.bailian.shutil.which", lambda name: holder["which"])
        monkeypatch.setattr(
            "backend.adapters.bailian.subprocess.run",
            lambda cmd, **kw: holder["proc"])
        return holder

    def test_fetch_models_requires_api_key(self):
        """bl CLI 登录态查不了推理面：无 key 返回 []（不发请求）。"""
        assert BailianAdapter().fetch_models("", {}) == []

    def test_fetch_models_with_key(self, mock_http):
        mock_http({"dashscope.aliyuncs.com/compatible-mode/v1/models": (200, MODELS_BODY)})
        assert BailianAdapter().fetch_models("k", {}) == ["model-a", "model-b"]

    def test_fetch_plan_name_token_plan_from_cli(self, mock_bl):
        mock_bl["proc"] = self._proc(
            stdout='{"per1WeekPercentage": 0.5, "per1WeekResetTime": 1788145140000}')
        assert BailianAdapter().fetch_plan_name("", {}) == "Token Plan"

    def test_fetch_plan_name_cli_missing_returns_none(self, mock_bl):
        mock_bl["which"] = None
        assert BailianAdapter().fetch_plan_name("", {}) is None

    def test_fetch_plan_name_cli_error_returns_none(self, mock_bl):
        mock_bl["proc"] = self._proc(stderr="auth failed", returncode=1)
        assert BailianAdapter().fetch_plan_name("", {}) is None

    def test_fetch_plan_name_cli_bad_json_returns_none(self, mock_bl):
        mock_bl["proc"] = self._proc(stdout="<html>nope</html>", returncode=0)
        assert BailianAdapter().fetch_plan_name("", {}) is None

    def test_fetch_plan_name_cli_output_without_percentage_returns_none(self, mock_bl):
        mock_bl["proc"] = self._proc(stdout='{"unexpected": true}', returncode=0)
        assert BailianAdapter().fetch_plan_name("", {}) is None


# ────────────────────────────── 默认实现 / 通用契约 ──────────────────────────────
class TestDefaultImplementations:
    def test_manual_fetch_models_returns_empty(self):
        """manual 不支持模型查询 → []（基类默认实现）。"""
        assert ManualAdapter().fetch_models("", {}) == []

    def test_manual_fetch_plan_name_returns_none(self):
        assert ManualAdapter().fetch_plan_name("", {}) is None

    def test_all_adapters_never_raise_on_garbage(self, mock_http, monkeypatch):
        """契约：任何 adapter 的 fetch_models / fetch_plan_name 都不抛异常。"""

        class BoomClient:
            def __init__(self, *a, **kw): pass
            def get(self, *a, **kw): raise RuntimeError("network down")
            def __enter__(self): return self
            def __exit__(self, *e): return False

        monkeypatch.setattr("backend.adapters.base.httpx.Client", BoomClient)

        def boom_run(*a, **kw):
            raise RuntimeError("cli down")

        monkeypatch.setattr("backend.adapters.bailian.subprocess.run", boom_run)
        monkeypatch.setattr("backend.adapters.bailian.shutil.which", lambda name: "bl")

        classes = [ZhipuAdapter, MiniMaxAdapter, DeepSeekAdapter, KimiAdapter,
                   ArkAdapter, StepFunAdapter, BailianAdapter, ManualAdapter]
        for cls in classes:
            adapter = cls()
            assert adapter.fetch_models("k", {}) == [], cls.__name__
            assert adapter.fetch_plan_name("k", {}) is None, cls.__name__

    def test_models_body_shape_variants(self, mock_http):
        """OpenAI 兼容结构变体：data 缺失/非列表/条目非对象 → []。"""
        for body in ({}, {"data": None}, {"data": "nope"},
                     {"data": [1, 2, None, {"id": 123}]}):
            mock_http({"api.deepseek.com/models": (200, body)})
            ids = DeepSeekAdapter().fetch_models("k", {})
            # 数字 id 不收；全非法时为 []
            assert all(isinstance(i, str) for i in ids)
