"""Plan Dashboard 后端入口 —— FastAPI 应用 + 路由。

- 仅监听 127.0.0.1（由 uvicorn 启动参数保证，见 README）
- GET  /api/plans     看板数据（各 provider 条目用量/余额/错误态）
- POST /api/refresh   手动触发全量刷新
- GET  /api/config    读取配置（脱敏，不回显 key）
- POST /api/config    保存配置
- GET  /api/providers 支持的厂商类型清单
- GET  /api/plans/{id}/info           卡片详情（首查→缓存→返回）
- POST /api/plans/{id}/refresh-info   卡片详情强制重查（忽略缓存）
- DELETE /api/plans/{id}/info         清空该条目详情缓存
- GET  /              前端 index.html

安全约定：API Key 只进 config.json 与厂商请求头，绝不写进响应或日志。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import config as config_mod
from .adapters import PROVIDER_META, get_adapter
from .adapters.base import utc_now_iso as _adapter_utc_now_iso
from .model_cache import ModelCacheService, build_cache_entry
from .scheduler import RefreshScheduler
from .store import UsageStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

store = UsageStore()
scheduler = RefreshScheduler(store)
model_cache = ModelCacheService()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="Plan Dashboard", version="1.0.0", lifespan=lifespan)


# ---- 静态前端 --------------------------------------------------------------
@app.get("/", include_in_schema=False)
def index():
    frontend = config_mod.PROJECT_ROOT / "src" / "frontend" / "index.html"
    if not frontend.exists():
        raise HTTPException(status_code=404, detail="frontend/index.html 未找到")
    return FileResponse(frontend, media_type="text/html; charset=utf-8")


# ---- 看板数据 --------------------------------------------------------------
@app.get("/api/plans")
def get_plans() -> dict:
    return {
        "ok": True,
        "plans": store.get_all(),
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(timespec="seconds"),
    }


@app.post("/api/refresh")
def refresh() -> dict:
    results = store.refresh_all()
    ok_count = sum(1 for r in results if not r.get("error"))
    return {
        "ok": True,
        "refreshed": len(results),
        "succeeded": ok_count,
        "failed": len(results) - ok_count,
        "plans": store.get_all(force_refresh_if_empty=False),
    }


# ---- 配置 ------------------------------------------------------------------
class ProviderEntryIn(BaseModel):
    id: str = Field(..., min_length=1)
    name: str = ""
    type: str = Field(..., min_length=1)
    api_key: str | None = None       # None/空 = 保留已有 key 不覆盖
    extra: dict = Field(default_factory=dict)
    enabled: bool = True


class ConfigIn(BaseModel):
    refresh_interval_minutes: float = Field(default=30, ge=1, le=1440)
    providers: list[ProviderEntryIn] = Field(default_factory=list)


@app.get("/api/config")
def read_config() -> dict:
    cfg = config_mod.load_config()
    return {"ok": True, "config": config_mod.sanitize_for_frontend(cfg)}


@app.post("/api/config")
def write_config(payload: ConfigIn) -> dict:
    """整体保存配置。

    注意：providers[].api_key 为空时**保留**该条目现有 key（防止前端脱敏回显把 key 冲掉）。
    """
    old_cfg = config_mod.load_config()

    new_providers: list[dict] = []
    for entry in payload.providers:
        item = entry.model_dump()
        # api_key=None 或 "" → 从旧配置带回来
        if not item.get("api_key"):
            for old in old_cfg.get("providers", []):
                if isinstance(old, dict) and old.get("id") == item["id"]:
                    item["api_key"] = old.get("api_key") or ""
                    break
            else:
                item["api_key"] = ""
        if not isinstance(item.get("extra"), dict):
            item["extra"] = {}
        new_providers.append(item)

    new_cfg = {
        "refresh_interval_minutes": payload.refresh_interval_minutes,
        "providers": new_providers,
    }
    config_mod.save_config(new_cfg)
    store.invalidate()      # 下次 /api/plans 会按新配置拉取
    return {"ok": True, "config": config_mod.sanitize_for_frontend(new_cfg)}


# ---- 厂商元数据 ------------------------------------------------------------
@app.get("/api/providers")
def list_providers() -> dict:
    return {"ok": True, "providers": PROVIDER_META}


# ---- 卡片详情（Model Info + Plan 档级，brief 2026-08-29） -------------------
def _find_entry(entry_id: str) -> dict:
    """按条目 id 查 config；找不到 → 404。"""
    for entry in config_mod.load_config().get("providers", []):
        if isinstance(entry, dict) and str(entry.get("id") or "") == entry_id:
            return entry
    raise HTTPException(status_code=404, detail=f"未知条目 id：{entry_id}")


def _resolve_plan_name(adapter, entry: dict, api_key: str, extra: dict,
                       cached: dict | None) -> tuple[str | None, str]:
    """plan_name 三层回退（D5'）：adapter 自报 → config.json 手填 → None（前端显示按量/未知）。

    返回 (plan_name, source)；source ∈ {"adapter", "config", "none"}。
    - adapter 层失败不抛异常（契约保证），返回 None 即落到下一层
    - 手动刷新成功时优先采信 adapter 新值；adapter 失败时回退
      config 手填，再回退旧缓存里的值
    """
    fetched = None
    try:
        fetched = adapter.fetch_plan_name(api_key, extra)
    except Exception as exc:  # noqa: BLE001 —— 双保险，理论上 adapter 不抛
        logger.warning("fetch_plan_name %s raised: %s", entry.get("type"), exc)
    if fetched:
        return str(fetched).strip() or None, "adapter"

    manual = entry.get("plan_name")
    if isinstance(manual, str) and manual.strip():
        return manual.strip(), "config"

    if cached:
        old = cached.get("plan_name")
        if isinstance(old, str) and old.strip():
            return old.strip(), str(cached.get("plan_name_source") or "config")
    return None, "none"


def _gather_info(entry: dict, cached: dict | None) -> dict:
    """调 adapter 拉 models + plan_name 并组装缓存条目（不写缓存）。

    models 查询失败返回 []（缓存保留 []）；plan_name 走三层回退；
    两项全失败且带错误信息时填 error 字段。
    """
    ptype = str(entry.get("type") or "manual")
    adapter = get_adapter(ptype)
    api_key = (entry.get("api_key") or "").strip()
    extra = entry.get("extra") or {}
    if not isinstance(extra, dict):
        extra = {}

    entry_id = str(entry.get("id") or ptype)
    fetched_at = (cached or {}).get("fetched_at") or _adapter_utc_now_iso()
    if adapter is None:
        return build_cache_entry(
            [], None, "none", owned_by=ptype,
            error=f"未知厂商类型：{ptype}",
            fetched_at=fetched_at,
        )

    config_error = adapter.config_error(api_key, extra)
    if config_error:
        # 无有效凭证：不请求；保留旧缓存的 models，plan_name 走 config 手填 → 旧缓存
        kept_ids = [
            str(m.get("id")) for m in ((cached or {}).get("models") or [])
            if isinstance(m, dict) and m.get("id")
        ]
        plan_name, source = _resolve_plan_name_plan_only(entry, cached)
        return build_cache_entry(
            kept_ids, plan_name, source, owned_by=ptype,
            error=config_error,
            fetched_at=fetched_at,
        )

    try:
        models = adapter.fetch_models(api_key, extra) or []
    except Exception as exc:  # noqa: BLE001 —— 双保险，理论上 adapter 不抛
        logger.warning("fetch_models %s raised: %s", ptype, exc)
        models = []

    plan_name, source = _resolve_plan_name(adapter, entry, api_key, extra, cached)

    # models 全空且 plan_name 没有 adapter 来源 → 视为整体查询失败，保留旧 fetched_at
    # （manual 等无查询能力的 adapter 除外：空列表是正常态）
    if not models and source != "adapter" and adapter.supports_models:
        return build_cache_entry(
            models, plan_name, source, owned_by=ptype,
            error=f"{adapter.display_name}: 模型列表查询失败（无数据返回）",
            fetched_at=fetched_at,
        )
    return build_cache_entry(models, plan_name, source, owned_by=ptype)


def _resolve_plan_name_plan_only(entry: dict, cached: dict | None) -> tuple[str | None, str]:
    """无 key 场景的 plan_name 解析：只走 config 手填 → 旧缓存两层。"""
    manual = entry.get("plan_name")
    if isinstance(manual, str) and manual.strip():
        return manual.strip(), "config"
    if cached:
        old = cached.get("plan_name")
        if isinstance(old, str) and old.strip():
            return old.strip(), str(cached.get("plan_name_source") or "config")
    return None, "none"


def _info_response(entry: dict, cache_entry: dict | None, entry_id: str) -> dict:
    """组装 /info 响应体（含三层回退后前端可直读的 plan_name）。"""
    display_name = str(entry.get("name") or entry.get("id") or entry_id)
    if cache_entry is None:
        return {
            "ok": True,
            "entry_id": entry_id,
            "display_name": display_name,
            "fetched_at": None,
            "plan_name": None,
            "plan_name_source": "none",
            "models": [],
            "error": None,
        }
    models = [
        {"id": str(m.get("id")), "owned_by": str(m.get("owned_by") or "")}
        for m in (cache_entry.get("models") or [])
        if isinstance(m, dict) and m.get("id")
    ]
    return {
        "ok": True,
        "entry_id": entry_id,
        "display_name": display_name,
        "fetched_at": cache_entry.get("fetched_at"),
        "plan_name": cache_entry.get("plan_name"),
        "plan_name_source": cache_entry.get("plan_name_source") or "none",
        "models": models,
        "error": cache_entry.get("error"),
    }


@app.get("/api/plans/{entry_id}/info")
def get_plan_info(entry_id: str) -> dict:
    """卡片详情：有缓存直接返回；无缓存首查一次并写缓存（D2）。"""
    entry = _find_entry(entry_id)
    cached = model_cache.get(entry_id)
    if cached is None:
        cache_entry = _gather_info(entry, None)
        if not cache_entry.get("error") or cache_entry.get("models"):
            model_cache.save_entry(entry_id, cache_entry)
        cached = model_cache.get(entry_id) or cache_entry
    return _info_response(entry, cached, entry_id)


@app.post("/api/plans/{entry_id}/refresh-info")
def refresh_plan_info(entry_id: str) -> dict:
    """强制重查：忽略缓存，调 adapter 重查 + 更新缓存 + 返回新结果。"""
    entry = _find_entry(entry_id)
    cached = model_cache.get(entry_id)
    cache_entry = _gather_info(entry, cached)
    # 失败也写缓存（带 error + 保留旧 models/plan_name），便于前端展示错误态
    model_cache.save_entry(entry_id, cache_entry)
    return _info_response(entry, cache_entry, entry_id)


@app.delete("/api/plans/{entry_id}/info")
def clear_plan_info(entry_id: str) -> dict:
    """清空该条目详情缓存（下次 GET /info 会重新首查）。"""
    _find_entry(entry_id)
    model_cache.clear(entry_id)
    return {"ok": True, "cleared": entry_id}
