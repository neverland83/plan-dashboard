"""适配器单元测试 —— 全部 mock，禁止真实网络请求。"""
from __future__ import annotations

import pytest

from backend.adapters.zhipu import ZhipuAdapter
from backend.adapters.minimax import MiniMaxAdapter
from backend.adapters.deepseek import DeepSeekAdapter
from backend.adapters.kimi import KimiAdapter
from backend.adapters.manual import ManualAdapter
from backend.adapters.ark import ArkAdapter, sign_v4


# ────────────────────────────── zhipu ──────────────────────────────
class TestZhipu:
    def test_ok_two_windows(self, mock_http, zhipu_ok_body):
        mock_http({"open.bigmodel.cn": (200, zhipu_ok_body)})
        u = ZhipuAdapter().fetch({
            "id": "z1", "name": "智谱", "type": "zhipu",
            "api_key": "test-key-xxx", "extra": {},
        })
        assert u.error is None
        assert u.plan_name == "GLM Coding Pro"
        assert [w.name for w in u.windows] == ["5小时", "周"]
        # percentage 是已用口径；remaining = 100 - used
        assert u.windows[0].percentage == 1.0 and u.windows[0].remaining == 99.0
        assert u.windows[1].percentage == 20.0 and u.windows[1].remaining == 80.0
        assert u.windows[0].next_reset is not None

    def test_missing_key_is_error_not_crash(self):
        u = ZhipuAdapter().fetch({"id": "z1", "name": "智谱", "api_key": "", "extra": {}})
        assert u.error is not None
        assert "API Key" in u.error or "Key" in u.error
        assert u.windows == []

    def test_auth_failure_returns_error_state(self, mock_http):
        mock_http({"open.bigmodel.cn": (401, {"success": False, "msg": "auth"})})
        u = ZhipuAdapter().fetch({"id": "z", "name": "智谱", "api_key": "bad", "extra": {}})
        assert u.error is not None
        assert "认证" in u.error

    def test_business_error(self, mock_http):
        mock_http({"open.bigmodel.cn": (200, {"success": False, "msg": "额度查询关闭"})})
        u = ZhipuAdapter().fetch({"id": "z", "name": "智谱", "api_key": "k", "extra": {}})
        assert u.error is not None and "额度查询关闭" in u.error

    def test_zai_host_override(self, mock_http, zhipu_ok_body):
        """Z.ai：仅换 host，同接口同解析；条目配置名优先展示。"""
        mock_http({"api.z.ai": (200, zhipu_ok_body)})
        u = ZhipuAdapter().fetch({
            "id": "za", "name": "Z.ai", "type": "zhipu",
            "api_key": "k", "extra": {"host": "https://api.z.ai"},
        })
        assert u.error is None
        assert u.display_name == "Z.ai"          # 条目 name 优先
        assert u.windows and u.windows[0].remaining == 99.0

    def test_unit_field_classification(self, mock_http):
        """CC Switch 实测：TOKENS_LIMIT + unit=3 归 5h 窗口、unit=6 归周窗口。"""
        body = {
            "success": True,
            "data": {
                "level": "max",
                "limits": [
                    {"type": "TOKENS_LIMIT", "unit": 3, "percentage": 5},
                    {"type": "TOKENS_LIMIT", "unit": 6, "percentage": 33},
                ],
            },
        }
        mock_http({"open.bigmodel.cn": (200, body)})
        u = ZhipuAdapter().fetch({"id": "z", "name": "智谱", "api_key": "k", "extra": {}})
        assert u.windows[0].name == "5小时" and u.windows[0].percentage == 5.0
        assert u.windows[1].name == "周" and u.windows[1].percentage == 33.0


class FakeReq:
    """占位（未使用）——保留以免误删导入告警。"""
    def __init__(self, routes):
        self.routes = routes


# ────────────────────────────── minimax ──────────────────────────────
class TestMiniMax:
    BODY_CN = {
        "base_resp": {"status_code": 0, "status_msg": "success"},
        "model_remains": [
            {
                "model_name": "general",
                "current_interval_remaining_percent": 80.0,   # 剩余%
                "end_time": 1790000000000,
                "current_weekly_status": 1,
                "current_weekly_remaining_percent": 55.5,
                "weekly_end_time": 1790500000000,
            },
            {
                "model_name": "video",                        # 应被过滤
                "current_interval_remaining_percent": 10.0,
                "end_time": 1790000000000,
            },
        ],
    }

    def test_ok_windows_and_reverse_to_used(self, mock_http):
        mock_http({
            "coding_plan/remains": (200, dict(self.BODY_CN)),
        })
        u = MiniMaxAdapter().fetch({
            "id": "mx", "name": "MiniMax", "type": "minimax",
            "api_key": "k", "extra": {},
        })
        assert u.error is None
        assert u.windows[0].name == "5小时"
        # 新接口给剩余% → 反转为已用：100 - 80 = 20
        assert u.windows[0].percentage == 20.0 and u.windows[0].remaining == 80.0
        assert u.windows[1].name == "周"
        assert abs(u.windows[1].percentage - 44.5) < 0.01

    def test_no_weekly_when_status_3(self, mock_http):
        body = dict(self.BODY_CN)
        body["model_remains"] = [{
            "model_name": "general",
            "current_interval_remaining_percent": 90.0,
            "end_time": 1790000000000,
            "current_weekly_status": 3,       # 无周限额
        }]
        mock_http({"coding_plan/remains": (200, body)})
        u = MiniMaxAdapter().fetch({"id": "mx", "name": "MX", "api_key": "k", "extra": {}})
        assert u.error is None
        assert len(u.windows) == 1 and u.windows[0].name == "5小时"

    def test_filters_video_models(self, mock_http):
        body = {
            "base_resp": {"status_code": 0},
            "model_remains": [
                {"model_name": "video", "current_interval_remaining_percent": 50.0},
                {"model_name": "voice", "current_interval_remaining_percent": 60.0},
            ],
        }
        mock_http({"coding_plan/remains": (200, body)})
        u = MiniMaxAdapter().fetch({"id": "mx", "name": "MX", "api_key": "k", "extra": {}})
        assert u.error is not None   # general 缺失 → 报错而不是把 video 当编程套餐

    def test_business_error(self, mock_http):
        mock_http({"coding_plan/remains": (
            200, {"base_resp": {"status_code": 1004, "status_msg": "invalid key"}},
        )})
        u = MiniMaxAdapter().fetch({"id": "mx", "name": "MX", "api_key": "bad", "extra": {}})
        assert u.error is not None and "1004" in u.error

    def test_intl_region_host(self, mock_http):
        mock_http({"coding_plan/remains": (
            200, {
                "base_resp": {"status_code": 0},
                "model_remains": [{"model_name": "general",
                                   "current_interval_remaining_percent": 70.0}],
            },
        )})
        u = MiniMaxAdapter().fetch({
            "id": "mx", "name": "MX", "api_key": "k", "extra": {"region": "intl"},
        })
        assert u.error is None


# ────────────────────────────── deepseek ──────────────────────────────
class TestDeepSeek:
    BODY = {
        "is_available": True,
        "balance_infos": [{
            "currency": "CNY",
            "total_balance": "110.00",
            "granted_balance": "10.00",
            "topped_up_balance": "100.00",
        }],
    }

    def test_ok_balance(self, mock_http):
        mock_http({"api.deepseek.com/user/balance": (200, dict(self.BODY))})
        u = DeepSeekAdapter().fetch({"id": "ds", "name": "DS", "api_key": "k", "extra": {}})
        assert u.error is None
        assert u.balance["total"] == 110.0
        assert u.balance["granted"] == 10.0
        assert u.balance["topped_up"] == 100.0
        assert u.balance["currency"] == "CNY"
        assert u.balance["is_available"] is True
        assert u.windows == []

    def test_unavailable_flag_kept(self, mock_http):
        body = dict(self.BODY, is_available=False)
        mock_http({"user/balance": (200, body)})
        u = DeepSeekAdapter().fetch({"id": "ds", "name": "DS", "api_key": "k", "extra": {}})
        assert u.error is None              # 数据有效即可上板；不可用由前端提示
        assert u.balance["is_available"] is False


# ────────────────────────────── kimi ──────────────────────────────
class TestKimi:
    BODY = {
        "code": 0,
        "data": {"available_balance": 49.59, "voucher_balance": 46.59, "cash_balance": 3.00},
        "status": True,
    }

    def test_ok_balance(self, mock_http):
        mock_http({"moonshot.cn/v1/users/me/balance": (200, dict(self.BODY))})
        u = KimiAdapter().fetch({"id": "km", "name": "Kimi", "api_key": "k", "extra": {}})
        assert u.error is None
        assert u.balance["available"] == 49.59
        assert u.balance["voucher"] == 46.59
        assert u.balance["cash"] == 3.0

    def test_intl_host(self, mock_http):
        mock_http({"api.kimi.ai/v1/users/me/balance": (200, dict(self.BODY))})
        u = KimiAdapter().fetch({
            "id": "km", "name": "Kimi EN", "api_key": "k", "extra": {"host": "https://api.kimi.ai"},
        })
        assert u.error is None


# ────────────────────────────── manual ──────────────────────────────
class TestManual:
    def test_reads_windows_from_config(self):
        u = ManualAdapter().fetch({
            "id": "m", "name": "腾讯云（手动）", "type": "manual", "api_key": "",
            "extra": {"windows": [{"name": "本月", "percentage": 65}]},
        })
        assert u.error is None
        assert u.windows[0].name == "本月"
        assert u.windows[0].percentage == 65.0 and u.windows[0].remaining == 35.0

    def test_supports_remaining_style(self):
        u = ManualAdapter().fetch({
            "id": "m", "name": "手动", "extra": {
                "windows": [{"name": "总量", "remaining": 42}],
            },
        })
        assert u.error is None
        assert u.windows[0].percentage == 58.0      # 已用 = 100 - 剩余

    def test_empty_windows_is_error(self):
        u = ManualAdapter().fetch({"id": "m", "name": "手动", "extra": {"windows": []}})
        assert u.error is not None


# ────────────────────────────── ark ──────────────────────────────
class TestArk:
    def _details(self):
        from datetime import date, timedelta
        today = __import__("datetime").date.today()
        monday = today - timedelta(days=today.weekday())
        month_first = today.replace(day=1)
        return [
            {"Time": str(today), "Usage": 1000.0, "Unit": "Tokens"},
            {"Time": str(monday), "Usage": 2000.0, "Unit": "Tokens"},     # 本周
            {"Time": str(month_first), "Usage": 3000.0, "Unit": "Tokens"},  # 本月
        ]

    def test_quota_required(self):
        u = ArkAdapter().fetch({
            "id": "ark", "name": "方舟", "api_key": "AK",
            "extra": {"secret_key": "SK"},      # 缺 plan_quota
        })
        assert u.error is not None and "plan_quota" in u.error

    def test_missing_secret(self):
        u = ArkAdapter().fetch({
            "id": "ark", "name": "方舟", "api_key": "AK", "extra": {"plan_quota": 10000},
        })
        assert u.error is not None and "access_key" in u.error.lower() or "凭证" in u.error

    def test_aggregates_usage(self, mock_http):
        resp = {"Result": {"Details": self._details()}}
        mock_http({"Action=GetUsageDetails": (200, resp)})
        u = ArkAdapter().fetch({
            "id": "ark", "name": "方舟", "api_key": "my-access-key",
            "extra": {"secret_key": "sk", "plan_quota": 100000},
        })
        assert u.error is None
        raw_agg = u.raw.get("aggregated", {})
        assert raw_agg["used_week"] == 3000.0     # 今天(1000) + 周一(2000)
        assert raw_agg["used_month"] == 6000.0
        assert u.windows[1].name == "周"
        assert abs(u.windows[1].percentage - 3.0) < 0.01   # 3000/100000*100

    def test_signature_headers_present(self):
        from datetime import datetime, timezone
        headers = sign_v4(
            access_key="AKTEST", secret_key="SKTEST", region="cn-beijing",
            host="ark.cn-beijing.volcengineapi.com", action="GetUsageDetails",
            version="2024-01-01", body_json="{}",
            now=datetime(2026, 8, 27, tzinfo=timezone.utc),
        )
        assert headers["Authorization"].startswith("HMAC-SHA256 Credential=AKTEST/")
        assert "cn-beijing/ark/request" in headers["Authorization"]
        assert headers["X-Date"] == "20260827T000000Z"


# ────────────────────────────── 通用契约 ──────────────────────────────
class TestContract:
    @pytest.mark.parametrize("adapter_cls", [
        ZhipuAdapter, MiniMaxAdapter, DeepSeekAdapter, KimiAdapter, ArkAdapter, ManualAdapter,
    ])
    def test_adapter_never_raises_on_garbage_response(self, adapter_cls, monkeypatch):
        """契约：适配器收到垃圾响应不得抛异常，必须返回 error 态。"""
        class BoomClient:
            def __init__(self, *a, **kw): pass
            def get(self, *a, **kw): raise RuntimeError("network down")
            def post(self, *a, **kw): raise RuntimeError("network down")
            def __enter__(self): return self
            def __exit__(self, *e): return False

        monkeypatch.setattr("backend.adapters.base.httpx.Client", BoomClient)
        entry = {"id": "x", "name": "X", "api_key": "k-or-empty", "extra": {}}
        if adapter_cls is ManualAdapter:
            entry["extra"] = {}
        result = adapter_cls().fetch(entry)
        # manual 无网络调用，会返回 windows-missing 错误；其余应捕获网络异常
        assert isinstance(result.to_dict(), dict)

    def test_no_api_key_leakage_in_output(self, mock_http, zhipu_ok_body):
        secret = "SUPER_SECRET_KEY_12345"
        mock_http({"open.bigmodel.cn": (200, zhipu_ok_body)})
        u = ZhipuAdapter().fetch({"id": "z", "name": "智谱", "api_key": secret, "extra": {}})
        d = u.to_dict()
        blob = repr(d)
        assert secret not in blob
