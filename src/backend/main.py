"""Plan Dashboard 后端入口 —— FastAPI 应用 + 路由。

- 仅监听 127.0.0.1（由 uvicorn 启动参数保证，见 README）
- GET  /api/plans     看板数据（各 provider 条目用量/余额/错误态）
- POST /api/refresh   手动触发全量刷新
- GET  /api/config    读取配置（脱敏，不回显 key）
- POST /api/config    保存配置
- GET  /api/providers 支持的厂商类型清单
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
from .adapters import PROVIDER_META
from .scheduler import RefreshScheduler
from .store import UsageStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

store = UsageStore()
scheduler = RefreshScheduler(store)


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
