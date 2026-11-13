"""火山方舟（Volcengine Ark）套餐用量查询（管控面 OpenAPI，自动探测套餐）。

接口档案：docs/research/providers/ark.md
- 认证：账号级 AccessKey/SecretKey（IAM 凭证，非 ark- 推理 API Key），
  走火山引擎管控面 OpenAPI V4 签名（HMAC-SHA256，纯 stdlib 实现；
  签名已用真实凭证实测通过）
- 端点：POST https://open.volcengineapi.com/?Action=...&Version=2024-01-01&Region=cn-beijing
- 自动探测（与 CC Switch 对齐）：
  1) GetAFPUsage（Agent Plan，绝对额度 Quota/Used，5小时/周/月；Quota<=0 视为未订阅跳过）
  2) 无数据 → GetCodingPlanUsage（Coding Plan，百分比）
  3) 两者皆无 → 返回「无有效套餐」状态（不报错，照实显示）
- 认证失败（HTTP 401/403 或业务错误码命中 _AUTH_ERROR_CODES）→ error 态并终止探测
- 配置：extra.access_key（可填在 api_key 字段）、extra.secret_key、
  extra.region 默认 cn-beijing
"""
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone

import httpx

from .base import WIN_5H, WIN_WEEK, WIN_MONTH, BaseAdapter
from ..models import PlanUsage, UsageWindow

OPENAPI_HOST = "open.volcengineapi.com"
API_VERSION = "2024-01-01"
REGION_DEFAULT = "cn-beijing"
SERVICE = "ark"
CONTENT_TYPE = "application/json"
SIGNED_HEADERS = "host;x-date;x-content-sha256;content-type"

# 认证类错误码（火山管控面网关注册表；命中即认定凭证问题，终止探测）
_AUTH_ERROR_CODES = {
    "InvalidAccessKey",
    "InvalidCredential",
    "SignatureDoesNotMatch",
    "AccessDenied",
    "Forbidden",
    "InvalidAction",
    "UnauthorizedOperation",
    "AuthFailure",
    "InvalidSecretKey",
    "MissingAuthenticationToken",
}

# GetCodingPlanUsage.Result.Status → 视为「未订阅/已回收」的状态集合
_STATUS_NOT_SUBSCRIBED = {"reclaimed", "inactive", "expired", "none", "unsubscribed"}

# Coding Plan 层级字段别名（不同 API 版本命名不一致）
_LEVEL_NAMES: dict[str, str] = {
    "session": WIN_5H, "5h": WIN_5H, "fivehour": WIN_5H,
    "five_hour": WIN_5H, "rolling_5h": WIN_5H,
    "weekly": WIN_WEEK, "week": WIN_WEEK, "7d": WIN_WEEK,
    "monthly": WIN_MONTH, "month": WIN_MONTH,
}


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def sign_v4(
    access_key: str,
    secret_key: str,
    region: str,
    host: str,
    action: str,
    version: str,
    now: datetime,
) -> dict[str, str]:
    """构造火山引擎管控面 OpenAPI V4 签名请求头。

    与 CC Switch src-tauri/src/services/coding_plan.rs 的 volcengine_sign 对齐：
    - canonical headers **固定顺序**（host → x-date → x-content-sha256 → content-type），不排序
    - 派生密钥 SK 不加 AWS4 前缀
    - body 为空；x-content-sha256 = sha256(空串)
    """
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    credential_scope = f"{date_stamp}/{region}/{SERVICE}/request"
    payload_hash = _sha256_hex(b"")

    query = f"Action={action}&Region={region}&Version={version}"

    x_date = amz_date
    canonical_headers = (
        f"host:{host}\n"
        f"x-date:{x_date}\n"
        f"x-content-sha256:{payload_hash}\n"
        f"content-type:{CONTENT_TYPE}\n"
    )
    canonical_request = "\n".join([
        "POST",
        "/",
        query,
        canonical_headers,
        SIGNED_HEADERS,
        payload_hash,
    ])
    string_to_sign = "\n".join([
        "HMAC-SHA256",
        amz_date,
        credential_scope,
        _sha256_hex(canonical_request.encode("utf-8")),
    ])

    k_date = _hmac_sha256(secret_key.encode("utf-8"), date_stamp)
    k_region = _hmac_sha256(k_date, region)
    k_service = _hmac_sha256(k_region, SERVICE)
    k_signing = _hmac_sha256(k_service, "request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    return {
        "Authorization": (
            f"HMAC-SHA256 Credential={access_key}/{credential_scope}, "
            f"SignedHeaders={SIGNED_HEADERS}, Signature={signature}"
        ),
        "Content-Type": CONTENT_TYPE,
        "X-Date": x_date,
        "X-Content-Sha256": payload_hash,
    }


def _parse_error(body: dict) -> tuple[str | None, str | None]:
    """从响应体提取 (code, message)；无错误返回 (None, None)。"""
    meta = body.get("ResponseMetadata")
    err = meta.get("Error") if isinstance(meta, dict) else None
    if not isinstance(err, dict):
        return (None, None)
    code = err.get("Code")
    msg = err.get("Message")
    return (str(code) if code else None, str(msg) if msg else None)


class ArkAdapter(BaseAdapter):
    provider_id = "ark"
    display_name = "火山方舟"
    # 凭证是账号级 IAM AK/SK（可能只填在 extra 里），不是 API Key ——
    # 交给 config_error 判定，否则基类会先按「缺少 API Key」误拦截。
    needs_key = False

    def config_error(self, api_key: str, extra: dict) -> str | None:
        """凭证缺失文案：明确区分 IAM AK/SK 与 ark- 推理 Key。"""
        access_key = (extra.get("access_key") or api_key or "").strip()
        secret_key = (extra.get("secret_key") or "").strip()
        if not access_key or not secret_key:
            return (
                "缺少账号级凭证：需要 IAM AccessKey/SecretKey"
                "（ark- 开头的是推理 API Key，不可用于套餐查询）"
            )
        return None

    def _call(self, access_key: str, secret_key: str, region: str, action: str) -> httpx.Response:
        now = datetime.now(timezone.utc)
        url = (
            f"https://{OPENAPI_HOST}/?Action={action}"
            f"&Region={region}&Version={API_VERSION}"
        )
        headers = sign_v4(access_key, secret_key, region, OPENAPI_HOST, action, API_VERSION, now)
        with httpx.Client(timeout=20.0) as client:
            return client.post(url, headers=headers, content=b"")

    def _fetch(self, api_key: str, extra: dict, usage: PlanUsage) -> PlanUsage:
        # fetch() 已用 config_error 拦截；这里保留兜底，防止子类/直调路径漏检
        missing = self.config_error(api_key, extra)
        if missing:
            return self._fail(usage, missing)
        access_key = (extra.get("access_key") or api_key or "").strip()
        secret_key = (extra.get("secret_key") or "").strip()

        region = str(extra.get("region") or REGION_DEFAULT).strip() or REGION_DEFAULT

        # 依次探测：Agent Plan → Coding Plan；任一命中即返回
        raw_results: dict[str, dict] = {}
        for action, parser in (
            ("GetAFPUsage", self._parse_afp_tiers),
            ("GetCodingPlanUsage", self._parse_coding_plan_tiers),
        ):
            resp = self._call(access_key, secret_key, region, action)
            try:
                body = resp.json() or {}
            except ValueError:
                body = {}
            if not isinstance(body, dict):
                body = {}

            kind = self._handle_error(usage, resp, body)
            if kind == "auth":
                return usage              # 凭证问题：终止探测，直接返回错误态
            if kind is not None:
                continue                  # 单接口故障（非认证类）：尝试下一探测

            result = body.get("Result")
            result = result if isinstance(result, dict) else {}
            raw_results[action] = result
            tiers = parser(result)
            if not tiers:
                continue

            usage.error = None            # 清掉此前探测可能留下的非致命错误
            if action == "GetAFPUsage":
                plan_type = str(result.get("PlanType") or "").strip()
                usage.plan_name = f"Agent Plan {plan_type}".strip() if plan_type else "Agent Plan"
            else:
                usage.plan_name = "Coding Plan"
            usage.windows = tiers
            usage.raw = {"action": action, "result": result}
            return usage

        # 两个探测都没拿到窗口
        coding_result = raw_results.get("GetCodingPlanUsage")
        if coding_result is not None:
            # 接口可达但无套餐数据（未订阅/已回收）→ 照实显示，不报错
            usage.error = None
            usage.plan_name = self._no_plan_label(coding_result)
            usage.raw = {"probes": raw_results}
            return usage
        # 全部接口失败（非认证类）→ 保留最后一次 error
        return usage

    # ---- 错误处理 ---------------------------------------------------------
    def _handle_error(self, usage: PlanUsage, resp: httpx.Response, body: dict) -> str | None:
        """统一错误检查（绝不抛异常）。

        返回：None = 响应正常；"auth" = 认证失败；"error" = 其他错误。
        失败时已把 error 写入 usage；调用方成功拿到数据后应自行清除。
        """
        code, msg = _parse_error(body)
        detail = f"（{code}: {msg}）" if code else ""

        if resp.status_code in (401, 403) or (code is not None and code in _AUTH_ERROR_CODES):
            hint = "请检查 AccessKey/SecretKey，并确认 IAM 账号已授权 Ark 只读访问策略"
            self._fail(usage, f"认证失败 (HTTP {resp.status_code}) {detail} {hint}".strip())
            return "auth"
        if resp.status_code >= 400:
            self._fail(usage, f"API 错误 (HTTP {resp.status_code}) {detail}".strip())
            return "error"
        if code is not None:
            self._fail(usage, f"API 业务错误（{code}: {msg}）")
            return "error"
        return None

    @staticmethod
    def _no_plan_label(result: dict) -> str:
        """无套餐时的展示文案；带上原始 Status 便于识别（如 Coding Plan Reclaimed）。"""
        status = str(result.get("Status") or "").strip()
        if not status:
            return "无有效套餐"
        if status.lower() in _STATUS_NOT_SUBSCRIBED:
            return f"无有效套餐（未订阅/已回收）· Coding Plan {status}"
        return f"无有效套餐（Status: {status}）"

    # ---- 解析 -------------------------------------------------------------
    def _afp_plan_quota_map(self, result: dict) -> dict:
        """提取 GetAFPUsage.Result.PlanNameToPurchaseQuotaMap（档级名 → 购买配额）。

        字段在官方响应中可能缺失或结构变化 → 统一返回 dict（可能为空）。
        """
        raw = result.get("PlanNameToPurchaseQuotaMap")
        return raw if isinstance(raw, dict) else {}

    def _parse_afp_tiers(self, result: dict) -> list[UsageWindow]:
        """GetAFPUsage：AFPFiveHour/AFPWeekly/AFPMonthly，Quota<=0 视为未订阅跳过。"""
        tiers: list[UsageWindow] = []
        for key, name in [
            ("AFPFiveHour", WIN_5H),
            ("AFPWeekly", WIN_WEEK),
            ("AFPMonthly", WIN_MONTH),
        ]:
            win = result.get(key)
            if not isinstance(win, dict):
                continue
            quota = self._to_float(win.get("Quota"), 0.0) or 0.0
            if quota <= 0:
                continue
            used = self._to_float(win.get("Used"), 0.0) or 0.0
            pct = self._clamp_pct(used / quota * 100.0)
            tiers.append(UsageWindow(name, pct, self._ts_to_iso(win.get("ResetTime"))))
        return tiers

    def _parse_coding_plan_tiers(self, result: dict) -> list[UsageWindow]:
        """GetCodingPlanUsage：QuotaUsage/Usages/Details[]，字段 Level/Percent/ResetTime。

        Percent 语义为**已用百分比**（与全局口径一致，无需反转）。
        """
        arr = None
        for key in ("QuotaUsage", "Usages", "Details", "Data"):
            candidate = result.get(key)
            if isinstance(candidate, list):
                arr = candidate
                break
        if arr is None:
            return []

        tiers: list[UsageWindow] = []
        for item in arr:
            if not isinstance(item, dict):
                continue
            name = None
            for key in ("Level", "Type", "Period", "Window", "Name"):
                raw = item.get(key)
                if raw:
                    name = _LEVEL_NAMES.get(str(raw).strip().lower())
                    break
            if not name:
                continue

            # 百分比字段逐个别名取值；缺失时兜底用绝对额度 Used/Quota 换算
            pct: float | None = None
            for key in ("Percent", "UsedPercent", "UsagePercent", "Percentage"):
                pct = self._to_float(item.get(key))
                if pct is not None:
                    break
            if pct is None:
                quota = self._to_float(item.get("Quota"), 0.0) or 0.0
                used = self._to_float(item.get("Used"), 0.0) or 0.0
                if quota > 0:
                    pct = used / quota * 100.0
            if pct is None:
                continue

            reset = None
            for key in ("ResetTime", "ResetTimestamp", "ResetAt"):
                if item.get(key) is not None:
                    reset = self._ts_to_iso(item.get(key))
                    break
            tiers.append(UsageWindow(name, self._clamp_pct(pct), reset))
        return tiers

    @staticmethod
    def _ts_to_iso(value) -> str | None:
        try:
            n = int(value)
        except (TypeError, ValueError):
            return None
        if n <= 0:
            return None
        # 秒级 < 1e12，毫秒级 >= 1e12
        if n < 1_000_000_000_000:
            n *= 1000
        return datetime.fromtimestamp(n / 1000.0, tz=timezone.utc).isoformat(timespec="seconds")

    # ---- 卡片详情扩展 -----------------------------------------------------
    def _credentials(self, api_key: str, extra: dict) -> tuple[str, str] | None:
        """从 extra/api_key 提取 AK/SK；缺失返回 None（调用方报错态）。"""
        access_key = (extra.get("access_key") or api_key or "").strip()
        secret_key = (extra.get("secret_key") or "").strip()
        return (access_key, secret_key) if access_key and secret_key else None

    def fetch_models(self, api_key: str, extra: dict) -> list[str]:
        """管控面 ListFoundationModels（V4 签名，同 GetAFPUsage 认证）。

        响应 Result.Models[]（别名 Items/Data）取 ModelName 字段；
        失败（凭证缺失/网络/HTTP 错误）返回 []。
        """
        creds = self._credentials(api_key, extra)
        if creds is None:
            return []
        access_key, secret_key = creds
        region = str(extra.get("region") or REGION_DEFAULT).strip() or REGION_DEFAULT
        try:
            resp = self._call(access_key, secret_key, region, "ListFoundationModels")
        except Exception:  # noqa: BLE001 —— 契约要求绝不抛异常
            return []
        try:
            body = resp.json() or {}
        except ValueError:
            return []
        # 不复用 _handle_error（会把 error 写进 usage），这里静默失败返回 []
        if not isinstance(body, dict):
            return []
        meta = body.get("ResponseMetadata")
        err = meta.get("Error") if isinstance(meta, dict) else None
        if resp.status_code >= 400 or isinstance(err, dict):
            return []
        result = body.get("Result")
        result = result if isinstance(result, dict) else {}
        items: list = []
        for key in ("Models", "Items", "Data", "List"):
            candidate = result.get(key)
            if isinstance(candidate, list):
                items = candidate
                break
        ids: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("ModelName") or item.get("Name") or item.get("Model")
            if isinstance(name, str) and name.strip():
                ids.append(name.strip())
        return sorted(set(ids))

    def fetch_plan_name(self, api_key: str, extra: dict) -> str | None:
        """GetAFPUsage 响应内的档级信息 → 'Agent Plan <档级>'。

        三层来源（brief 指定，取先命中者）：
        1. Result.PlanType（当前档级，如 'Pro'）
        2. PlanNameToPurchaseQuotaMap 里配额最大的一档
        失败返回 None，交给 config 手填回退。
        """
        creds = self._credentials(api_key, extra)
        if creds is None:
            return None
        access_key, secret_key = creds
        region = str(extra.get("region") or REGION_DEFAULT).strip() or REGION_DEFAULT
        try:
            resp = self._call(access_key, secret_key, region, "GetAFPUsage")
        except Exception:  # noqa: BLE001 —— 契约要求绝不抛异常
            return None
        try:
            body = resp.json() or {}
        except ValueError:
            return None
        if not isinstance(body, dict):
            return None
        code, _msg = _parse_error(body)
        if resp.status_code >= 400 or (code is not None and code in _AUTH_ERROR_CODES):
            return None
        result = body.get("Result")
        result = result if isinstance(result, dict) else {}

        plan_type = str(result.get("PlanType") or "").strip()
        if plan_type:
            return f"Agent Plan {plan_type}"

        quota_map = self._afp_plan_quota_map(result)
        best_name, best_quota = None, 0.0
        for name, quota in quota_map.items():
            q = self._to_float(quota)
            if q is None or q <= 0:
                continue                       # 配额非法/非正数的档级不采信
            if q > best_quota:
                best_name, best_quota = str(name), q
        if best_name:
            return f"Agent Plan {best_name}"

        # AFP 无档级 → 探测 Coding Plan（订阅型，有 Status=Active 即算一档）
        try:
            resp2 = self._call(access_key, secret_key, region, "GetCodingPlanUsage")
        except Exception:  # noqa: BLE001
            return None
        try:
            body2 = resp2.json() or {}
        except ValueError:
            return None
        if not isinstance(body2, dict):
            return None
        code2, _ = _parse_error(body2)
        if resp2.status_code >= 400 or (code2 is not None and code2 in _AUTH_ERROR_CODES):
            return None
        result2 = body2.get("Result")
        result2 = result2 if isinstance(result2, dict) else {}
        if str(result2.get("Status") or "").strip().lower() in ("active", "ok", "running"):
            return "Coding Plan"
        return None
