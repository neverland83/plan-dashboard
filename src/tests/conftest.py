"""pytest 共享 fixture：临时 config.json 隔离 + httpx 全局 mock。

⚠️ 约束：所有测试禁止真实网络请求 —— 通过 monkeypatch 替换 adapters 内的
httpx.Client，并对 store 的配置路径重定向到 tmp_path。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# 保证可导入 src.backend.*
SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC))


@pytest.fixture()
def isolated_config(tmp_path, monkeypatch):
    """把 config.py 的 CONFIG_PATH 指到临时目录。"""
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr("backend.config.CONFIG_PATH", cfg_path)
    yield cfg_path


@pytest.fixture()
def mock_http(monkeypatch):
    """替换 backend.adapters.* 里的 httpx.Client 为可编程 fake。

    用法：
        responses = {url_substring: (status, json_body)} 或 (status, raw_text)
        mock_http(responses)
    未匹配的 URL 一律抛 AssertionError（防止真实请求漏网）。
    """
    from tests.helpers import FakeClient

    def _install(routes: dict):
        monkeypatch.setattr(
            "httpx.Client",
            lambda *a, **kw: FakeClient(routes),
        )
        return routes

    return _install


@pytest.fixture()
def zhipu_ok_body() -> dict:
    """智谱成功响应样本（与 docs/research/providers/zhipu.md 结构一致）。"""
    return {
        "success": True,
        "msg": "",
        "data": {
            "level": "pro",
            "limits": [
                {"type": "TIME_LIMIT", "percentage": 1, "nextResetTime": 1790000000000},
                {"type": "TOKENS_LIMIT", "percentage": 20, "nextResetTime": 1790500000000},
            ],
        },
    }


def write_config(path: Path, providers: list[dict], interval: int = 30) -> None:
    path.write_text(
        json.dumps({"refresh_interval_minutes": interval, "providers": providers}, ensure_ascii=False),
        encoding="utf-8",
    )
