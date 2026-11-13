"""适配器单元测试 —— 全部 mock，禁止真实网络请求。"""
from __future__ import annotations

import pytest

from backend.adapters.zhipu import ZhipuAdapter
from backend.adapters.minimax import MiniMaxAdapter
from backend.adapters.deepseek import DeepSeekAdapter
from backend.adapters.kimi import KimiAdapter
from backend.adapters.manual import ManualAdapter
from backend.adapters.stepfun import StepFunAdapter
from backend.adapters.ark import ArkAdapter, sign_v4
from backend.adapters.bailian import BailianAdapter


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
def _ds_body(infos: list[dict]) -> dict:
    """构造 DeepSeek /user/balance 响应体。"""
    return {"is_available": True, "balance_infos": infos}


def _ds_info(currency: str, total: str) -> dict:
    return {
        "currency": currency,
        "total_balance": total,
        "granted_balance": "0.00" if total == "0.00" else "10.00",
        "topped_up_balance": "100.00",
    }


class TestDeepSeek:
    BODY = _ds_body([{
        "currency": "CNY",
        "total_balance": "110.00",
        "granted_balance": "10.00",
        "topped_up_balance": "100.00",
    }])

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
        # 单币种：currencies 也照出（单条），兼容字段与主币种一致
        assert u.balance["currencies"] == [{
            "currency": "CNY", "total": 110.0, "granted": 10.0, "topped_up": 100.0,
        }]

    def test_unavailable_flag_kept(self, mock_http):
        body = dict(self.BODY, is_available=False)
        mock_http({"user/balance": (200, body)})
        u = DeepSeekAdapter().fetch({"id": "ds", "name": "DS", "api_key": "k", "extra": {}})
        assert u.error is None              # 数据有效即可上板；不可用由前端提示
        assert u.balance["is_available"] is False

    # ---- balance_infos 多币种：全量解析进 currencies，顺序不稳定需稳定排序 ----
    def test_multi_currency_usd_zero_first_all_shown(self, mock_http):
        """用例 A：实测顺序 USD(0) 在前 → 两币种都返回，CNY 为主币种排首位。"""
        mock_http({"user/balance": (200, _ds_body([
            _ds_info("USD", "0.00"), _ds_info("CNY", "10.00"),
        ]))})
        u = DeepSeekAdapter().fetch({"id": "ds", "name": "DS", "api_key": "k", "extra": {}})
        assert u.error is None
        # currencies 全量且有序：CNY(有余额) 在前
        assert u.balance["currencies"] == [
            {"currency": "CNY", "total": 10.0, "granted": 10.0, "topped_up": 100.0},
            {"currency": "USD", "total": 0.0, "granted": 0.0, "topped_up": 100.0},
        ]
        # 兼容字段 = 主币种
        assert u.balance["currency"] == "CNY"
        assert u.balance["total"] == 10.0
        assert u.balance["topped_up"] == 100.0

    def test_multi_currency_cny_first_same_output(self, mock_http):
        """用例 B：CNY(10) 在前 → 输出与 A 完全一致（排序无关输入顺序）。"""
        mock_http({"user/balance": (200, _ds_body([
            _ds_info("CNY", "10.00"), _ds_info("USD", "0.00"),
        ]))})
        u = DeepSeekAdapter().fetch({"id": "ds", "name": "DS", "api_key": "k", "extra": {}})
        assert u.error is None
        assert u.balance["currencies"] == [
            {"currency": "CNY", "total": 10.0, "granted": 10.0, "topped_up": 100.0},
            {"currency": "USD", "total": 0.0, "granted": 0.0, "topped_up": 100.0},
        ]
        assert u.balance["currency"] == "CNY"
        assert u.balance["total"] == 10.0

    def test_all_zero_prefers_cny_not_error(self, mock_http):
        """用例 C：全为 0 → CNY 兜底为主币种（并列时 CNY 优先），不报错。"""
        mock_http({"user/balance": (200, _ds_body([
            _ds_info("USD", "0.00"), _ds_info("CNY", "0.00"),
        ]))})
        u = DeepSeekAdapter().fetch({"id": "ds", "name": "DS", "api_key": "k", "extra": {}})
        assert u.error is None
        assert u.balance["currency"] == "CNY"
        assert u.balance["total"] == 0.0
        assert [c["currency"] for c in u.balance["currencies"]] == ["CNY", "USD"]

    def test_all_zero_without_cny_falls_back_to_first(self, mock_http):
        """全 0 且无 CNY（如 EUR/USD）→ 按字母序兜底，不报错。"""
        mock_http({"user/balance": (200, _ds_body([
            _ds_info("USD", "0.00"), _ds_info("EUR", "0.00"),
        ]))})
        u = DeepSeekAdapter().fetch({"id": "ds", "name": "DS", "api_key": "k", "extra": {}})
        assert u.error is None
        assert u.balance["currency"] == "EUR"
        assert u.balance["total"] == 0.0
        assert [c["currency"] for c in u.balance["currencies"]] == ["EUR", "USD"]

    def test_only_usd_has_balance_usd_is_main(self, mock_http):
        """用例 D：海外用户仅 USD 有余额 → USD 为主币种排首位。"""
        mock_http({"user/balance": (200, _ds_body([
            _ds_info("CNY", "0.00"), _ds_info("USD", "5.50"),
        ]))})
        u = DeepSeekAdapter().fetch({"id": "ds", "name": "DS", "api_key": "k", "extra": {}})
        assert u.error is None
        assert u.balance["currency"] == "USD"
        assert u.balance["total"] == 5.5
        assert [c["currency"] for c in u.balance["currencies"]] == ["USD", "CNY"]

    def test_non_dict_entries_skipped(self, mock_http):
        """数组混入非法元素 → 跳过后仍全量解析剩余币种，绝不抛异常。"""
        mock_http({"user/balance": (200, {
            "is_available": True,
            "balance_infos": ["garbage", _ds_info("USD", "0.00"), _ds_info("CNY", "8.00")],
        })})
        u = DeepSeekAdapter().fetch({"id": "ds", "name": "DS", "api_key": "k", "extra": {}})
        assert u.error is None
        assert [c["currency"] for c in u.balance["currencies"]] == ["CNY", "USD"]
        assert u.balance["currencies"][0]["total"] == 8.0
        assert u.balance["currency"] == "CNY"
        assert u.balance["total"] == 8.0


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
    """二期重写后的 ark：sign_v4 新签名 + GetAFPUsage/GetCodingPlanUsage 自动探测。"""

    AFP_OK = {
        "ResponseMetadata": {"Action": "GetAFPUsage", "Service": "ark"},
        "Result": {
            "PlanType": "Pro",
            "AFPFiveHour": {"Quota": 10000, "Used": 2500, "ResetTime": 1790000000},
            "AFPWeekly": {"Quota": 50000, "Used": 10000, "ResetTime": 1790500000},
            "AFPMonthly": {"Quota": 200000, "Used": 50000, "ResetTime": 1791000000},
        },
    }
    AFP_NOT_SUBSCRIBED = {
        "ResponseMetadata": {"Action": "GetAFPUsage"},
        "Result": {
            "PlanType": "",
            "AFPFiveHour": {"Quota": 0, "Used": 0, "ResetTime": 0},
            "AFPWeekly": {"Quota": 0, "Used": 0, "ResetTime": 0},
            "AFPMonthly": {"Quota": 0, "Used": 0, "ResetTime": 0},
        },
    }
    CODING_OK = {
        "ResponseMetadata": {"Action": "GetCodingPlanUsage"},
        "Result": {
            "Status": "Active",
            "QuotaUsage": [
                {"Level": "session", "Percent": 12.5, "ResetTime": 1790000000},
                {"Level": "weekly", "Percent": 40, "ResetTime": 1790500000},
                {"Level": "monthly", "Percent": 8, "ResetTime": 1791000000},
            ],
        },
    }
    CODING_RECLAIMED = {
        "ResponseMetadata": {"Action": "GetCodingPlanUsage"},
        "Result": {"Status": "Reclaimed", "UpdateTimestamp": 1787887081, "HasReward": False},
    }

    ENTRY = {"id": "ark", "name": "方舟", "type": "ark",
             "api_key": "AKTEST", "extra": {"secret_key": "SKTEST", "region": "cn-beijing"}}

    def test_signature_headers_new_canonical(self):
        """新签名：固定顺序 canonical headers、SK 不加 AWS4 前缀、body 为空。"""
        from datetime import datetime, timezone
        headers = sign_v4(
            access_key="AKTEST", secret_key="SKTEST", region="cn-beijing",
            host="open.volcengineapi.com", action="GetAFPUsage",
            version="2024-01-01",
            now=datetime(2026, 8, 28, tzinfo=timezone.utc),
        )
        assert headers["Authorization"].startswith("HMAC-SHA256 Credential=AKTEST/")
        assert "cn-beijing/ark/request" in headers["Authorization"]
        assert "SignedHeaders=host;x-date;x-content-sha256;content-type" in headers["Authorization"]
        assert headers["X-Date"] == "20260828T000000Z"
        # body 为空 → x-content-sha256 是空串摘要
        import hashlib
        assert headers["X-Content-Sha256"] == hashlib.sha256(b"").hexdigest()

    def test_afp_usage_parsed(self, mock_http):
        """GetAFPUsage：绝对额度换算已用百分比，Quota>0 才出窗口。"""
        mock_http({"Action=GetAFPUsage": (200, dict(self.AFP_OK))})
        u = ArkAdapter().fetch(dict(self.ENTRY))
        assert u.error is None
        assert u.plan_name == "Agent Plan Pro"
        assert [w.name for w in u.windows] == ["5小时", "周", "本月"]
        # 已用% = used/quota*100
        assert abs(u.windows[0].percentage - 25.0) < 0.01
        assert abs(u.windows[1].percentage - 20.0) < 0.01
        assert abs(u.windows[2].percentage - 25.0) < 0.01
        assert u.windows[0].remaining == 75.0
        assert u.windows[0].next_reset is not None   # 秒级时间戳已转 ISO
        assert u.raw["action"] == "GetAFPUsage"

    def test_afp_zero_quota_skipped_falls_to_coding_plan(self, mock_http):
        """AFP 全部 Quota<=0 → 探测落到 GetCodingPlanUsage。"""
        mock_http({
            "Action=GetAFPUsage": (200, dict(self.AFP_NOT_SUBSCRIBED)),
            "Action=GetCodingPlanUsage": (200, dict(self.CODING_OK)),
        })
        u = ArkAdapter().fetch(dict(self.ENTRY))
        assert u.error is None
        assert u.plan_name == "Coding Plan"
        assert [w.name for w in u.windows] == ["5小时", "周", "本月"]
        assert u.windows[0].percentage == 12.5       # Percent 已是已用口径，无需反转
        assert u.windows[1].remaining == 60.0
        assert u.raw["action"] == "GetCodingPlanUsage"

    def test_no_plan_returns_status_not_error(self, mock_http):
        """两探测皆空（未订阅/已回收）→ 照实显示状态文案，不置 error。"""
        mock_http({
            "Action=GetAFPUsage": (200, dict(self.AFP_NOT_SUBSCRIBED)),
            "Action=GetCodingPlanUsage": (200, dict(self.CODING_RECLAIMED)),
        })
        u = ArkAdapter().fetch(dict(self.ENTRY))
        assert u.error is None                       # 无套餐≠出错
        assert "无有效套餐" in u.plan_name
        assert "Reclaimed" in u.plan_name
        assert u.windows == []

    def test_auth_error_code_terminates_probe(self, mock_http):
        """业务错误码命中 _AUTH_ERROR_CODES → 认证失败且不再二次探测。"""
        bad = {"ResponseMetadata": {"Error": {
            "Code": "SignatureDoesNotMatch", "Message": "签名不匹配"}}}
        mock_http({"Action=GetAFPUsage": (200, bad)})
        u = ArkAdapter().fetch(dict(self.ENTRY))
        assert u.error is not None
        assert "认证失败" in u.error and "SignatureDoesNotMatch" in u.error
        assert u.windows == []

    def test_http_403_auth_failure(self, mock_http):
        mock_http({"Action=GetAFPUsage": (403, {"ResponseMetadata": {}})})
        u = ArkAdapter().fetch(dict(self.ENTRY))
        assert u.error is not None and "认证失败" in u.error

    def test_missing_credentials_is_error(self):
        # 有 api_key 但缺 SK → 适配器报凭证缺失
        u = ArkAdapter().fetch({"id": "ark", "name": "方舟", "api_key": "AK", "extra": {}})
        assert u.error is not None and "凭证" in u.error and u.windows == []
        # api_key 为空 → 不再被基类「缺少 API Key」误拦截，文案仍指向 IAM 凭证
        u2 = ArkAdapter().fetch({"id": "ark", "name": "方舟", "api_key": "",
                                 "extra": {"secret_key": "SK"}})
        assert u2.error is not None and "凭证" in u2.error and u2.windows == []
        assert "API Key（请在配置面板填写）" not in u2.error

    def test_credentials_only_in_extra_still_queries(self, mock_http):
        """回归：AK/SK 只填在 extra、api_key 留空时，仍必须真正发起请求。

        旧实现 needs_key=True 会在基类按「缺少 API Key」直接返回，
        用户即使填对了 IAM 凭证也永远看不到数据。
        """
        mock_http({"Action=GetAFPUsage": (200, self.AFP_OK)})
        entry = {"id": "ark", "name": "方舟", "type": "ark", "api_key": "",
                 "extra": {"access_key": "AKTEST", "secret_key": "SKTEST",
                           "region": "cn-beijing"}}
        u = ArkAdapter().fetch(entry)
        assert u.error is None
        assert [(w.name, w.percentage) for w in u.windows] == [
            ("5小时", 25.0), ("周", 20.0), ("本月", 25.0),
        ]
        assert u.plan_name == "Agent Plan Pro"

    def test_field_alias_compat_coding_plan(self, mock_http):
        """_parse_coding_plan_tiers 字段兼容：Usages/别名键/绝对额度兜底。"""
        body = {"Result": {"Status": "Active", "Usages": [
            {"Type": "5h", "UsedPercent": 30.0},                        # 别名 Level→Type、Percent→UsedPercent
            {"Period": "Monthly", "Percentage": 66.0},                  # 别名 Period/Percentage
            {"Name": "Weekly", "Quota": 200.0, "Used": 50.0},           # 绝对额度兜底换算
            {"Level": "UnknownLevel", "Percent": 10.0},                 # 未知层级 → 跳过
            "garbage",                                                   # 非法元素 → 跳过
        ]}}
        mock_http({
            "Action=GetAFPUsage": (200, dict(self.AFP_NOT_SUBSCRIBED)),
            "Action=GetCodingPlanUsage": (200, body),
        })
        u = ArkAdapter().fetch(dict(self.ENTRY))
        assert u.error is None
        assert [(w.name, w.percentage) for w in u.windows] == [
            ("5小时", 30.0), ("本月", 66.0), ("周", 25.0),
        ]

    def test_single_probe_failure_still_falls_through(self, mock_http):
        """AFP 接口 500（非认证类）→ 不终止，继续探测 Coding Plan。"""
        mock_http({
            "Action=GetAFPUsage": (500, {"ResponseMetadata": {"Error": {
                "Code": "InternalError", "Message": "boom"}}}),
            "Action=GetCodingPlanUsage": (200, dict(self.CODING_OK)),
        })
        u = ArkAdapter().fetch(dict(self.ENTRY))
        assert u.error is None                       # 后续探测成功则清掉前次错误
        assert u.plan_name == "Coding Plan" and len(u.windows) == 3


# ────────────────────────────── stepfun ──────────────────────────────
class TestStepFun:
    BODY = {
        "object": "account",
        "type": "prepaid",
        "balance": -0.07,
        "total_cash_balance": 0,
        "total_voucher_balance": 0,
    }

    def test_ok_balance(self, mock_http):
        mock_http({"api.stepfun.com/v1/accounts": (200, dict(self.BODY))})
        u = StepFunAdapter().fetch({
            "id": "sf", "name": "StepFun", "type": "stepfun",
            "api_key": "k", "extra": {},
        })
        assert u.error is None
        assert u.balance["total"] == -0.07
        assert u.balance["topped_up"] == 0.0
        assert u.balance["voucher"] == 0.0
        assert u.balance["currency"] == "CNY"
        assert u.windows == []
        assert u.plan_name == "Step Plan（控制台查看）"

    def test_manual_credits_merged_as_windows(self, mock_http):
        """extra.manual_credits 合并为窗口；remaining=剩余% → 反转为已用%。"""
        mock_http({"api.stepfun.com/v1/accounts": (200, dict(self.BODY))})
        u = StepFunAdapter().fetch({
            "id": "sf", "name": "StepFun", "api_key": "k",
            "extra": {"manual_credits": [
                {"name": "加油包", "remaining": 45},
                {"name": "月池", "percentage": 20, "next_reset": "2026-09-01T00:00:00+00:00"},
                "garbage",                                  # 非法元素跳过
                {"remaining": "bad"},                       # 无 name/数值 → 跳过
            ]},
        })
        assert u.error is None
        assert u.balance["total"] == -0.07                  # 余额照常解析
        assert [w.name for w in u.windows] == ["加油包", "月池"]
        assert u.windows[0].percentage == 55.0 and u.windows[0].remaining == 45.0
        assert u.windows[1].percentage == 20.0
        assert u.windows[1].next_reset == "2026-09-01T00:00:00+00:00"

    def test_manual_credits_accepts_json_string(self, mock_http):
        """配置面板文本框存的是字符串 → 兼容 JSON 数组字符串。"""
        mock_http({"api.stepfun.com/v1/accounts": (200, dict(self.BODY))})
        u = StepFunAdapter().fetch({
            "id": "sf", "name": "StepFun", "api_key": "k",
            "extra": {"manual_credits": '[{"name":"加油包","remaining":45}]'},
        })
        assert u.error is None
        assert u.windows[0].name == "加油包" and u.windows[0].percentage == 55.0

    def test_auth_failure(self, mock_http):
        mock_http({"api.stepfun.com/v1/accounts": (401, {"error": "invalid key"})})
        u = StepFunAdapter().fetch({"id": "sf", "name": "StepFun", "api_key": "bad", "extra": {}})
        assert u.error is not None
        assert "认证失败" in u.error and "401" in u.error

    def test_garbage_response_no_raise(self, mock_http):
        """垃圾响应（非 JSON / 非对象）→ 返回错误态，绝不抛异常。"""
        for status, payload in ((200, "-not-json-"), (200, ["a", "list"])):
            mock_http({"api.stepfun.com/v1/accounts": (status, payload)})
            u = StepFunAdapter().fetch({"id": "sf", "name": "StepFun", "api_key": "k", "extra": {}})
            assert u.error is not None
            assert u.balance is None


# ────────────────────────────── bailian ──────────────────────────────
class TestBailian:
    """经 subprocess 调本机 bl CLI 查询 Token Plan 配额（全部 mock，不真调 CLI）。"""

    OK_JSON = '{"per1WeekPercentage": 0.8936928449999999, "per1WeekResetTime": 1788145140000}'

    @staticmethod
    def _proc(stdout="", stderr="", returncode=0):
        from types import SimpleNamespace
        return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)

    @pytest.fixture()
    def mock_bl(self, monkeypatch):
        """替换 shutil.which + subprocess.run，记录调用参数并可编程返回。

        holder["result"] 支持两种形态：
        - 单个 proc 对象 → 每次调用都返回它（向后兼容老的测试）
        - [proc1, proc2, ...] → 序列返回（用于 retry 行为测试）
        """
        holder = {"result": self._proc(), "results_idx": 0}
        calls = {"count": 0, "cmd": None, "kwargs": None}

        def fake_run(cmd, **kwargs):
            calls["count"] += 1
            calls["cmd"] = cmd
            calls["kwargs"] = kwargs
            result = holder["result"]
            if isinstance(result, list):
                idx = holder["results_idx"]
                holder["results_idx"] = idx + 1
                return result[idx] if idx < len(result) else result[-1]
            return result

        monkeypatch.setattr("backend.adapters.bailian.shutil.which", lambda name: "bl")
        monkeypatch.setattr("backend.adapters.bailian.subprocess.run", fake_run)
        holder["calls"] = calls
        return holder

    ENTRY = {"id": "bl1", "name": "百炼", "type": "bailian", "api_key": "", "extra": {}}

    def test_ok_week_window(self, mock_bl):
        """正常：比例 0-1 → 已用百分比；毫秒时间戳 → ISO；无 5h 窗口。"""
        mock_bl["result"] = self._proc(stdout=self.OK_JSON)
        u = BailianAdapter().fetch(dict(self.ENTRY))
        assert u.error is None
        assert u.provider == "bailian"
        assert u.display_name == "百炼"
        assert [w.name for w in u.windows] == ["周"]
        assert abs(u.windows[0].percentage - 89.3692845) < 0.01   # 已用口径
        assert abs(u.windows[0].remaining - 10.6) < 0.1           # remaining = 100 - used
        # 1788145140000 ms → 2026-08-31T02:59:00+00:00（UTC）
        assert u.windows[0].next_reset == "2026-08-31T02:59:00+00:00"
        assert u.raw == {"per1WeekPercentage": 0.8936928449999999,
                         "per1WeekResetTime": 1788145140000}
        # 调用参数核对：--output json、capture_output、utf-8
        assert mock_bl["calls"]["cmd"][0].endswith("bl")
        assert mock_bl["calls"]["cmd"][1:] == ["usage", "token-plan", "--output", "json"]
        assert mock_bl["calls"]["kwargs"]["capture_output"] is True
        assert mock_bl["calls"]["kwargs"]["encoding"] == "utf-8"

    def test_zero_and_full_boundaries(self, mock_bl):
        mock_bl["result"] = self._proc(
            stdout='{"per1WeekPercentage": 0, "per1WeekResetTime": 1788145140000}')
        u = BailianAdapter().fetch(dict(self.ENTRY))
        assert u.error is None and u.windows[0].percentage == 0.0

        mock_bl["result"] = self._proc(
            stdout='{"per1WeekPercentage": 1, "per1WeekResetTime": 1788145140000}')
        u = BailianAdapter().fetch(dict(self.ENTRY))
        assert u.error is None
        assert u.windows[0].percentage == 100.0 and u.windows[0].remaining == 0.0

    def test_missing_reset_time_still_ok(self, mock_bl):
        """缺 reset 字段 → 窗口照出，reset 为 None。"""
        mock_bl["result"] = self._proc(stdout='{"per1WeekPercentage": 0.5}')
        u = BailianAdapter().fetch(dict(self.ENTRY))
        assert u.error is None
        assert u.windows[0].percentage == 50.0
        assert u.windows[0].next_reset is None

    def test_nonzero_return_code_is_error(self, mock_bl):
        mock_bl["result"] = self._proc(
            stdout="token expired", stderr="bl: auth failed, run `bl auth login`",
            returncode=1)
        u = BailianAdapter().fetch(dict(self.ENTRY))
        assert u.error is not None
        assert "退出码 1" in u.error and "auth failed" in u.error
        assert u.windows == []

    def test_invalid_json_is_error(self, mock_bl):
        mock_bl["result"] = self._proc(stdout="<table>usage</table>", returncode=0)
        u = BailianAdapter().fetch(dict(self.ENTRY))
        assert u.error is not None
        assert "JSON" in u.error
        assert u.windows == []

    def test_missing_percentage_field_is_error(self, mock_bl):
        mock_bl["result"] = self._proc(stdout='{"unexpected": true}', returncode=0)
        u = BailianAdapter().fetch(dict(self.ENTRY))
        assert u.error is not None and "per1WeekPercentage" in u.error
        assert u.windows == []

    def test_bl_not_found_is_friendly_error(self, monkeypatch):
        # which 解析不到（未安装）→ 友好错误
        monkeypatch.setattr("backend.adapters.bailian.shutil.which", lambda name: None)
        u = BailianAdapter().fetch(dict(self.ENTRY))
        assert u.error is not None
        assert "未找到 bl 命令" in u.error and "bailian-cli" in u.error
        assert u.windows == []

        def raise_fnf(cmd, **kwargs):
            raise FileNotFoundError("bl")

        # which 命中但执行瞬间消失 → 同样友好错误
        monkeypatch.setattr("backend.adapters.bailian.shutil.which", lambda name: "bl")
        monkeypatch.setattr("backend.adapters.bailian.subprocess.run", raise_fnf)
        u2 = BailianAdapter().fetch(dict(self.ENTRY))
        assert u2.error is not None
        assert "未找到 bl 命令" in u2.error

    def test_timeout_is_error(self, monkeypatch):
        import subprocess as sp

        def raise_timeout(cmd, **kwargs):
            raise sp.TimeoutExpired(cmd, 20)

        monkeypatch.setattr("backend.adapters.bailian.shutil.which", lambda name: "bl")
        monkeypatch.setattr("backend.adapters.bailian.subprocess.run", raise_timeout)
        u = BailianAdapter().fetch(dict(self.ENTRY))
        assert u.error is not None and "超时" in u.error
        assert u.windows == []

    # ────────────────────────── OAuth transient 重试 ──────────────────────────
    def _expired_proc(self):
        """模拟 bl CLI 在 OAuth access_token 短过期时的 stdout/stderr/returncode。"""
        return self._proc(
            stdout="",
            stderr='{"error":{"code":3,"message":"Console session is not logged in or has expired.","hint":"Run `bl auth login --console` to sign in or refresh your console session."}}',
            returncode=3,
        )

    def _disable_sleep(self, monkeypatch):
        """屏蔽真实 time.sleep，避免重试测试真的等 1.5 秒。"""
        monkeypatch.setattr("backend.adapters.bailian.time.sleep", lambda _s: None)

    def test_retry_on_expired_succeeds(self, mock_bl, monkeypatch):
        """OAuth 短过期 → 第 2 次 retry 拿到 OK → windows 正常出。"""
        self._disable_sleep(monkeypatch)
        mock_bl["result"] = [self._expired_proc(), self._proc(stdout=self.OK_JSON)]
        u = BailianAdapter().fetch(dict(self.ENTRY))
        assert u.error is None
        assert [w.name for w in u.windows] == ["周"]
        assert abs(u.windows[0].percentage - 89.3692845) < 0.01
        # 首次 expired + 1 次 retry = 共 2 次子进程调用
        assert mock_bl["calls"]["count"] == 2

    def test_retry_on_expired_exhausted_returns_error(self, mock_bl, monkeypatch):
        """3 次都 expired → 用尽 2 次重试，最终报错。"""
        self._disable_sleep(monkeypatch)
        mock_bl["result"] = [self._expired_proc(), self._expired_proc(), self._expired_proc()]
        u = BailianAdapter().fetch(dict(self.ENTRY))
        assert u.error is not None
        assert "退出码 3" in u.error
        assert "Console session" in u.error
        assert u.windows == []
        # 首次 + 2 次 retry = 3 次
        assert mock_bl["calls"]["count"] == 3

    def test_non_expired_nonzero_return_code_no_retry(self, mock_bl, monkeypatch):
        """非 expired 错误（普通子进程错误）→ 不重试，直接报错，避免被 retry 拖慢。"""
        self._disable_sleep(monkeypatch)
        mock_bl["result"] = self._proc(
            stdout="unparseable junk", stderr="bl: command failed", returncode=1,
        )
        u = BailianAdapter().fetch(dict(self.ENTRY))
        assert u.error is not None
        assert "退出码 1" in u.error
        assert u.windows == []
        # 不该 retry → 只调 1 次
        assert mock_bl["calls"]["count"] == 1

    def test_retry_then_invalid_json_still_error(self, mock_bl, monkeypatch):
        """expired 重试成功，但第二次的 stdout 不是合法 JSON → 走 JSON 错误路径。"""
        self._disable_sleep(monkeypatch)
        mock_bl["result"] = [
            self._expired_proc(),
            self._proc(stdout="<not json>", returncode=0),
        ]
        u = BailianAdapter().fetch(dict(self.ENTRY))
        assert u.error is not None and "JSON" in u.error
        assert u.windows == []


# ────────────────────────────── 通用契约 ──────────────────────────────
class TestContract:
    @pytest.mark.parametrize("adapter_cls", [
        ZhipuAdapter, MiniMaxAdapter, DeepSeekAdapter, KimiAdapter, ArkAdapter,
        StepFunAdapter, ManualAdapter, BailianAdapter,
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

        # bailian 不走 httpx，把 subprocess.run 一并炸掉，验证同样不抛异常
        def boom_run(*a, **kw):
            raise RuntimeError("cli down")

        monkeypatch.setattr("backend.adapters.bailian.subprocess.run", boom_run)

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
