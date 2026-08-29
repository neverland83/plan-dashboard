"""卡片详情模型/档级缓存（data/model_cache.json）。

brief 2026-08-29 决策 D1/D2/D7'/D8'：
- 存储：`data/model_cache.json` 单文件，顶层 `{provider_id: {...}}`，与
  config.json 同风格的纯文件（运行时产物，不入库）
- 失效策略：首查 → 之后读缓存 → 手动按钮刷新（本模块只管存取，
  「首查 vs 强刷」的路由语义见 main.py）
- 幂等写：先写临时文件再原子替换，写坏也不破坏已有缓存
- 绝不抛异常到调用方：JSON 损坏 / 文件不存在均回退为「无缓存」

单条目 schema：
{
  "fetched_at": "2026-08-29T12:34:56+08:00",
  "plan_name": "GLM Coding · Lite 档" | null,
  "plan_name_source": "adapter" | "config",
  "models": [{"id": "glm-4-plus", "owned_by": "zhipu"}, ...],
  "error": "..." | null            # 上次刷新失败信息（可选）
}
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = PROJECT_ROOT / "data"
CACHE_PATH = CACHE_DIR / "model_cache.json"

_lock = threading.Lock()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty() -> dict:
    return {}


def _load_unlocked(path: Path) -> dict:
    """读缓存文件 → dict；不存在/损坏/非对象一律回退空（绝不抛异常）。"""
    if not path.exists():
        return _empty()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        logger.warning("model_cache 损坏，忽略并回退空缓存：%s", path)
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    return data


class ModelCacheService:
    """data/model_cache.json 的存取服务（线程安全 + 原子写）。"""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else CACHE_PATH

    # ---- 读 ---------------------------------------------------------------
    def load(self) -> dict:
        """整个缓存（顶层 {provider_id: entry}）。"""
        with _lock:
            return _load_unlocked(self.path)

    def get(self, provider_id: str) -> dict | None:
        """单个 provider 的缓存条目；无则 None。"""
        data = self.load()
        entry = data.get(provider_id)
        return entry if isinstance(entry, dict) else None

    def has(self, provider_id: str) -> bool:
        return self.get(provider_id) is not None

    # ---- 写 ---------------------------------------------------------------
    def save_entry(self, provider_id: str, entry: dict) -> None:
        """写入/覆盖单个 provider 条目（读-合并-原子写回）。"""
        with _lock:
            data = _load_unlocked(self.path)
            data[provider_id] = entry
            self._save_unlocked(data)

    def save(self, data: dict) -> None:
        """整体覆盖缓存（仅接受 dict 顶层结构）。"""
        if not isinstance(data, dict):
            return
        with _lock:
            self._save_unlocked(data)

    def _save_unlocked(self, data: dict) -> None:
        """原子写：临时文件 + os.replace（需持有 _lock）。失败只记日志。"""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_name, str(self.path))
            except BaseException:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
        except OSError as exc:
            logger.warning("model_cache 写入失败（不影响服务）：%s", exc)

    # ---- 删 ---------------------------------------------------------------
    def clear(self, provider_id: str | None = None) -> None:
        """清空单个 provider（传 id）或整个缓存（None）。

        文件不存在时为幂等 no-op（不创建文件）。
        """
        with _lock:
            if provider_id is None:
                self._save_unlocked({})
                return
            if not self.path.exists():
                return
            data = _load_unlocked(self.path)
            if provider_id in data:
                del data[provider_id]
                self._save_unlocked(data)


def build_cache_entry(
    models: list[str],
    plan_name: str | None,
    plan_name_source: str,
    owned_by: str | None = None,
    error: str | None = None,
    fetched_at: str | None = None,
) -> dict:
    """把 adapter 返回值规整为缓存 schema（D8'）。

    models 为 id 字符串列表 → [{id, owned_by}]；owned_by 缺省用 provider_id。
    """
    owner = owned_by or ""
    return {
        "fetched_at": fetched_at or utc_now_iso(),
        "plan_name": plan_name or None,
        "plan_name_source": plan_name_source,
        "models": [{"id": m, "owned_by": owner} for m in models],
        "error": error,
    }
