"""火山方舟（Volcengine Ark）套餐用量查询。

接口档案：docs/research/providers/ark.md
- OpenAPI: POST https://ark.cn-beijing.volcengineapi.com/?Action=GetUsageDetails&Version=2024-01-01
- 火山引擎 V4 签名（AccessKey/SecretKey），本实现为纯 stdlib 签名（hmac/hashlib），
  与官方签名算法一致，避免引入庞大的 volcengine 全量 SDK
- 无"剩余配额"直查接口 → 套餐上限由用户在 extra.plan_quota 手填（单位 Tokens），
  剩余% = (配额 - 已用) / 配额
- 方舟日粒度用量无法精确还原 5 小时滚动窗，一期口径：
  「今日已用」「本周已用（周一起）」「本月已用」三个窗口对比同一 plan_quota
- 配置：extra.access_key / extra.secret_key（access_key 也可填在 api_key 字段）、
  extra.region 默认 cn-beijing、extra.object_names 可选过滤模型列表
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import httpx

from .base import WIN_WEEK, BaseAdapter
from ..models import PlanUsage, UsageWindow

HOST_DEFAULT = "ark.cn-beijing.volcengineapi.com"
REGION_DEFAULT = "cn-beijing"
SERVICE = "ark"
CONTENT_TYPE = "application/json"

WIN_TODAY = "近1天"


# ── 火山引擎 V4 签名（HMAC-SHA256，与官方算法一致）────────────────────────
def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def sign_v4(
    access_key: str,
    secret_key: str,
    region: str,
    host: str,
    action: str,
    version: str,
    body_json: str,
    now: datetime,
    session_token: str | None = None,
) -> dict[str, str]:
    """构造火山引擎 OpenAPI V4 签名请求头。

    步骤遵循官方《签名机制》：规范化 query → 规范化 header → canonical request
    → string to sign → 派生签名密钥 → Authorization。
    """
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    credential_scope = f"{date_stamp}/{region}/{SERVICE}/request"
    payload_hash = _sha256_hex(body_json.encode("utf-8"))

    # 规范化 query（Action/Version 已按字母序：Action 在前）
    query = f"Action={action}&Version={version}"

    headers = {
        "content-type": CONTENT_TYPE,
        "host": host,
        "x-content-sha256": payload_hash,
        "x-date": amz_date,
    }
    if session_token:
        headers["x-security-token"] = session_token
    signed_headers = ";".join(sorted(headers))
    canonical_headers = "".join(f"{k}:{headers[k]}\n" for k in sorted(headers))

    canonical_request = "\n".join([
        "POST",
        "/",
        query,
        canonical_headers,
        signed_headers,
        payload_hash,
    ])

    string_to_sign = "\n".join([
        "HMAC-SHA256",
        amz_date,
        credential_scope,
        _sha256_hex(canonical_request.encode("utf-8")),
    ])

    k_date = _hmac(secret_key.encode("utf-8"), date_stamp)
    k_region = _hmac(k_date, region)
    k_service = _hmac(k_region, SERVICE)
    k_signing = _hmac(k_service, "request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization = (
        f"HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    out_headers = {
        "Authorization": authorization,
        "Content-Type": CONTENT_TYPE,
        "X-Date": amz_date,
        "X-Content-Sha256": payload_hash,
    }
    if session_token:
        out_headers["X-Security-Token"] = session_token
    return out_headers


class ArkAdapter(BaseAdapter):
    provider_id = "ark"
    display_name = "火山方舟"

    def _fetch(self, api_key: str, extra: dict, usage: PlanUsage) -> PlanUsage:
        access_key = (extra.get("access_key") or api_key or "").strip()
        secret_key = (extra.get("secret_key") or "").strip()
        if not access_key or not secret_key:
            return self._fail(usage, "缺少访问凭证：请在配置中提供 AccessKey / SecretKey")

        quota = self._to_float(extra.get("plan_quota"))
        if not quota or quota <= 0:
            return self._fail(
                usage,
                "缺少套餐上限：请在 extra.plan_quota 填写套餐总配额（Tokens）",
            )

        region = str(extra.get("region") or REGION_DEFAULT)
        host = str(extra.get("host") or HOST_DEFAULT)
        url = f"https://{host}/?Action=GetUsageDetails&Version=2024-01-01"

        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(days=int(extra.get("lookback_days", 35)))

        body: dict = {
            "QueryInterval": "Day",
            "StartTime": start_dt.strftime("%Y-%m-%d"),
            "EndTime": end_dt.strftime("%Y-%m-%d"),
        }
        object_names = extra.get("object_names")
        if isinstance(object_names, list) and object_names:
            body["Filter"] = {"ObjectName": [str(o) for o in object_names]}

        body_json = json.dumps(body, separators=(",", ":"))
        headers = sign_v4(
            access_key=access_key,
            secret_key=secret_key,
            region=region,
            host=host,
            action="GetUsageDetails",
            version="2024-01-01",
            body_json=body_json,
            now=end_dt,
            session_token=extra.get("session_token"),
        )

        with httpx.Client(timeout=20.0) as client:
            resp = client.post(url, content=body_json, headers=headers)

        if resp.status_code in (401, 403):
            return self._fail(usage, f"认证失败 (HTTP {resp.status_code})：AK/SK 无效或无权限")
        if resp.status_code >= 400:
            detail = ""
            try:
                err_body = resp.json()
                detail = str(
                    err_body.get("ResponseMetadata", {}).get("Error", {}).get("Message", "")
                )[:120]
            except ValueError:
                pass
            return self._fail(usage, f"API 错误 (HTTP {resp.status_code}) {detail}".strip())

        try:
            body_data = resp.json()
        except ValueError:
            return self._fail(usage, "响应不是合法 JSON")

        result = body_data.get("Result") or {}
        details = result.get("Details")
        if not isinstance(details, list):
            return self._fail(usage, "响应缺少 Result.Details 字段")

        today = end_dt.date()
        week_start = today - timedelta(days=today.weekday())       # 本周一
        month_start = today.replace(day=1)
        used_today = used_week = used_month = 0.0
        for d in details:
            if not isinstance(d, dict):
                continue
            day_str = str(d.get("Time") or "")[:10]
            amount = self._to_float(d.get("Usage"), 0.0) or 0.0
            try:
                day = datetime.strptime(day_str, "%Y-%m-%d").date()
            except ValueError:
                continue
            if day == today:
                used_today += amount
            if day >= week_start:
                used_week += amount
            if day >= month_start:
                used_month += amount

        def pct(used: float) -> float:
            return self._clamp_pct(used / quota * 100.0)

        usage.windows.append(UsageWindow(WIN_TODAY, pct(used_today), None))
        usage.windows.append(UsageWindow(WIN_WEEK, pct(used_week), _iso(next_week_start(today))))
        usage.windows.append(UsageWindow("本月", pct(used_month), _iso(next_month_start(today))))
        usage.plan_name = f"配额 {int(quota):,} Tokens/月"
        # 附带聚合数值便于排查；raw 不含 AK/SK
        usage.raw = {
            "aggregated": {
                "plan_quota": quota,
                "used_today_approx": used_today,
                "used_week": used_week,
                "used_month": used_month,
            }
        }
        return usage


def next_week_start(today) -> datetime:
    monday = today - timedelta(days=today.weekday())
    return datetime.combine(monday + timedelta(days=7), datetime.min.time(), tzinfo=timezone.utc)


def next_month_start(today) -> datetime:
    if today.month == 12:
        return datetime(today.year + 1, 1, 1, tzinfo=timezone.utc)
    return datetime(today.year, today.month + 1, 1, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")
