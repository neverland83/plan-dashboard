"""配置加载/保存（config.json）。

- 配置文件位于项目根目录，含 API Key 明文（仅本机），已在 .gitignore 中排除
- 保存时先写临时文件再原子替换，避免写坏
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"

_lock = threading.Lock()

DEFAULT_CONFIG: dict = {
    "refresh_interval_minutes": 30,
    "providers": [],
}


def load_config(path: Path | None = None) -> dict:
    """读取 config.json；不存在或损坏时回退默认结构。"""
    p = path or CONFIG_PATH
    with _lock:
        return _load_unlocked(p)


def _load_unlocked(path: Path) -> dict:
    if not path.exists():
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return json.loads(json.dumps(DEFAULT_CONFIG))
    if not isinstance(data, dict):
        return json.loads(json.dumps(DEFAULT_CONFIG))
    # 补齐缺失字段
    data.setdefault("refresh_interval_minutes", DEFAULT_CONFIG["refresh_interval_minutes"])
    data.setdefault("providers", [])
    if not isinstance(data["providers"], list):
        data["providers"] = []
    return data


def save_config(config: dict, path: Path | None = None) -> None:
    """原子写入 config.json。"""
    p = path or CONFIG_PATH
    with _lock:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            os.replace(tmp_name, str(p))
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise


def sanitize_for_frontend(config: dict) -> dict:
    """脱敏：去掉 api_key / extra 中疑似密钥字段，供 GET /api/config 返回。

    注意：POST /api/config 收到的完整配置只在后端使用，不回显 key。
    """
    out = {
        "refresh_interval_minutes": config.get("refresh_interval_minutes", 30),
        "providers": [],
    }
    for i, entry in enumerate(config.get("providers", [])):
        if not isinstance(entry, dict):
            continue
        extra = entry.get("extra") or {}
        safe_extra = {
            k: v
            for k, v in extra.items()
            if k.lower()
            not in {"access_key", "accesskey", "secret_key", "secretkey", "api_key"}
        }
        has_key = bool(entry.get("api_key"))
        out["providers"].append(
            {
                "id": entry.get("id") or f"entry-{i}",
                "name": entry.get("name") or entry.get("id") or f"entry-{i}",
                "type": entry.get("type") or "manual",
                "has_key": has_key,
                "extra": safe_extra,
                "enabled": bool(entry.get("enabled", True)),
            }
        )
    return out


def merge_key_into_entry(config: dict, entry_id: str, api_key: str | None) -> None:
    """把前端提交的 api_key 合并进对应条目：None/空串 = 不修改已有 key。"""
    if api_key is None or api_key == "":
        return
    for entry in config.get("providers", []):
        if entry.get("id") == entry_id:
            entry["api_key"] = api_key
            return
