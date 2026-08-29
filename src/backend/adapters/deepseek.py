"""DeepSeek 账户余额查询（余额型，无窗口）。

接口档案：docs/research/providers/deepseek.md
- GET https://api.deepseek.com/user/balance
- Authorization: Bearer <key>
- balance_infos[]: currency / total_balance / granted_balance / topped_up_balance
- is_available: 账户是否可用

注意：balance_infos[] 可能同时含 CNY / USD 两条，且实测顺序不稳定
（连续调用顺序随机轮换）。不能盲取 infos[0]。本适配器把**全部币种**
解析进 balance.currencies（自带稳定排序，主币种在首位），同时回填
单币种兼容字段（= 主币种），老的前端/其他适配器逻辑不受影响。
主币种与排序规则见 _parse_currencies。
"""
from __future__ import annotations

import httpx

from .base import BaseAdapter
from ..models import PlanUsage

DEFAULT_HOST = "https://api.deepseek.com"
BALANCE_PATH = "/user/balance"
MODELS_PATH = "/models"          # OpenAI 兼容 List Models
# 国内用户主币种：金额并列时 CNY 排前；全为 0 时也兜底展示它
PREFERRED_CURRENCY = "CNY"


def _parse_currencies(infos: list) -> list[dict]:
    """把 balance_infos[] 规整为多币种列表（已排序，主币种在首位）。

    上游数组顺序不稳定（实测 CNY/USD 轮流在前），输出必须自带稳定排序，
    前端才能稳定展示"主币种在首行"。排序规则：
    1. total 大的在前（真实余额币种即主币种）；
    2. 并列（如全为 0）时 CNY 优先（国内主币种）；
    3. 再并列按币种代码字母序，保证任何输入顺序得到同一输出。

    混入的非 dict 元素直接跳过，绝不抛异常。
    """
    parsed = []
    for info in infos:
        if not isinstance(info, dict):
            continue
        parsed.append({
            "currency": str(info.get("currency") or PREFERRED_CURRENCY).upper(),
            "total": BaseAdapter._to_float(info.get("total_balance"), 0.0) or 0.0,
            "granted": BaseAdapter._to_float(info.get("granted_balance"), 0.0) or 0.0,
            "topped_up": BaseAdapter._to_float(info.get("topped_up_balance"), 0.0) or 0.0,
        })
    parsed.sort(key=lambda c: (-c["total"],
                               c["currency"] != PREFERRED_CURRENCY,
                               c["currency"]))
    return parsed


class DeepSeekAdapter(BaseAdapter):
    provider_id = "deepseek"
    display_name = "DeepSeek"
    kind = "balance"

    def _fetch(self, api_key: str, extra: dict, usage: PlanUsage) -> PlanUsage:
        host = (extra.get("host") or DEFAULT_HOST).rstrip("/")
        url = f"{host}{BALANCE_PATH}"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }

        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, headers=headers)

        if resp.status_code in (401, 403):
            return self._fail(usage, f"认证失败 (HTTP {resp.status_code})：Key 无效或已过期")
        if resp.status_code >= 400:
            return self._fail(usage, f"API 错误 (HTTP {resp.status_code})")

        try:
            body = resp.json()
        except ValueError:
            return self._fail(usage, "响应不是合法 JSON")

        usage.raw = body if isinstance(body, dict) else {}

        infos = body.get("balance_infos")
        if not isinstance(infos, list) or not infos:
            return self._fail(usage, "响应缺少 balance_infos 字段")

        # 顺序不稳定：全量解析 + 稳定排序，所有币种都上板（勿盲取 infos[0]）
        currencies = _parse_currencies(infos)
        main = currencies[0] if currencies else {
            "currency": PREFERRED_CURRENCY, "total": 0.0, "granted": 0.0, "topped_up": 0.0,
        }
        usage.balance = {
            # 单币种兼容字段 = 主币种（其他适配器同构，前端旧逻辑继续可用）
            "currency": main["currency"],
            "total": main["total"],
            "granted": main["granted"],
            "topped_up": main["topped_up"],
            # 多币种全量：主币种在首位，前端逐行渲染
            "currencies": currencies,
            # 数据有效即上板；is_available=False 由前端黄字提示"账户不可用"
            "is_available": bool(body.get("is_available", True)),
        }
        return usage

    # ---- 卡片详情扩展 -----------------------------------------------------
    def fetch_models(self, api_key: str, extra: dict) -> list[str]:
        """GET {host}/models（OpenAI 兼容 List Models）。失败返回 []。"""
        host = (extra.get("host") or DEFAULT_HOST).rstrip("/")
        return self._fetch_models_openai_compat(f"{host}{MODELS_PATH}", api_key)

    # fetch_plan_name：DeepSeek 按量计费无套餐 → 继承基类返回 None
