"""ModelCacheService 单元测试（data/model_cache.json 存取，brief 2026-08-29）。

覆盖：load/save/get/clear、原子写（临时文件替换）、文件不存在、JSON 损坏、
非对象顶层、并发写、以及缓存路径指向临时目录的隔离。
"""
from __future__ import annotations

import json
import threading

import pytest

from backend.model_cache import ModelCacheService, build_cache_entry, utc_now_iso


@pytest.fixture()
def cache_path(tmp_path):
    return tmp_path / "data" / "model_cache.json"


@pytest.fixture()
def svc(cache_path):
    return ModelCacheService(cache_path)


class TestLoad:
    def test_missing_file_returns_empty(self, svc, cache_path):
        assert not cache_path.exists()
        assert svc.load() == {}

    def test_corrupt_json_returns_empty_not_raise(self, svc, cache_path):
        cache_path.parent.mkdir(parents=True)
        cache_path.write_text("{not valid json!!", encoding="utf-8")
        assert svc.load() == {}

    def test_non_object_top_level_returns_empty(self, svc, cache_path):
        cache_path.parent.mkdir(parents=True)
        cache_path.write_text('["a", "list"]', encoding="utf-8")
        assert svc.load() == {}

    def test_valid_file_roundtrip(self, svc, cache_path):
        cache_path.parent.mkdir(parents=True)
        body = {"zhipu": {"fetched_at": "2026-08-29T00:00:00+00:00",
                          "plan_name": "GLM Coding Pro",
                          "plan_name_source": "adapter", "models": []}}
        cache_path.write_text(json.dumps(body), encoding="utf-8")
        assert svc.load() == body


class TestSaveEntry:
    def test_save_creates_parent_dirs_and_file(self, svc, cache_path):
        svc.save_entry("zhipu", build_cache_entry(
            ["glm-4-plus"], "GLM Coding Pro", "adapter", owned_by="zhipu"))
        assert cache_path.exists()
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        assert data["zhipu"]["models"] == [{"id": "glm-4-plus", "owned_by": "zhipu"}]
        assert data["zhipu"]["plan_name"] == "GLM Coding Pro"
        assert data["zhipu"]["plan_name_source"] == "adapter"

    def test_save_preserves_other_entries(self, svc):
        svc.save_entry("a", build_cache_entry([], None, "none"))
        svc.save_entry("b", build_cache_entry([], "X", "config"))
        loaded = svc.load()
        assert set(loaded) == {"a", "b"}
        assert loaded["b"]["plan_name"] == "X"

    def test_overwrite_replaces_entry(self, svc):
        svc.save_entry("z", build_cache_entry(["m1"], None, "none"))
        svc.save_entry("z", build_cache_entry(["m2"], "P", "adapter"))
        entry = svc.get("z")
        assert [m["id"] for m in entry["models"]] == ["m2"]
        assert entry["plan_name"] == "P"

    def test_get_returns_none_for_missing(self, svc):
        assert svc.get("nope") is None
        assert svc.has("nope") is False

    def test_get_ignores_non_dict_entry(self, svc, cache_path):
        cache_path.parent.mkdir(parents=True)
        cache_path.write_text(json.dumps({"bad": "just a string"}), encoding="utf-8")
        assert svc.get("bad") is None

    def test_no_tmp_files_left_behind(self, svc, cache_path):
        svc.save_entry("z", build_cache_entry([], None, "none"))
        svc.save_entry("z", build_cache_entry([], None, "none"))
        leftovers = [p for p in cache_path.parent.iterdir() if p.name != "model_cache.json"]
        assert leftovers == []


class TestSaveWhole:
    def test_save_whole_replaces_all(self, svc):
        svc.save_entry("old", build_cache_entry([], None, "none"))
        svc.save({"fresh": build_cache_entry(["m"], None, "none")})
        assert set(svc.load()) == {"fresh"}

    def test_save_rejects_non_dict(self, svc):
        svc.save(["not", "a", "dict"])   # 非法输入静默忽略，不写坏文件
        assert not svc.path.exists() or svc.load() == {}


class TestClear:
    def test_clear_single_entry(self, svc):
        svc.save_entry("a", build_cache_entry([], None, "none"))
        svc.save_entry("b", build_cache_entry([], None, "none"))
        svc.clear("a")
        assert svc.get("a") is None
        assert svc.get("b") is not None

    def test_clear_missing_entry_is_noop(self, svc):
        svc.clear("ghost")                       # 不抛异常
        assert svc.load() == {}

    def test_clear_all(self, svc):
        svc.save_entry("a", build_cache_entry([], None, "none"))
        svc.clear(None)
        assert svc.load() == {}
        # 清空后文件仍存在（内容为空对象）——下次首查逻辑照常
        assert svc.path.exists()

    def test_clear_idempotent_when_file_missing(self, svc, cache_path):
        assert not cache_path.exists()
        svc.clear("anything")                    # 幂等 no-op，不创建文件
        assert not cache_path.exists()


class TestBuildCacheEntry:
    def test_schema_shape(self):
        ts = "2026-08-29T12:00:00+00:00"
        entry = build_cache_entry(
            ["glm-4-flash", "glm-4-plus"], "GLM Coding Lite", "adapter",
            owned_by="zhipu", error=None, fetched_at=ts)
        assert entry == {
            "fetched_at": ts,
            "plan_name": "GLM Coding Lite",
            "plan_name_source": "adapter",
            "models": [{"id": "glm-4-flash", "owned_by": "zhipu"},
                       {"id": "glm-4-plus", "owned_by": "zhipu"}],
            "error": None,
        }

    def test_none_plan_name_stays_none(self):
        entry = build_cache_entry([], None, "config", owned_by="deepseek")
        assert entry["plan_name"] is None
        assert entry["plan_name_source"] == "config"

    def test_owned_by_defaults_empty(self):
        entry = build_cache_entry(["m"], None, "none")
        assert entry["models"] == [{"id": "m", "owned_by": ""}]

    def test_fetched_at_defaults_to_now(self):
        before = utc_now_iso()
        entry = build_cache_entry([], None, "none")
        assert entry["fetched_at"] >= before


class TestConcurrencyAndIsolation:
    def test_parallel_writes_keep_all_entries(self, svc):
        """并发写不同条目：读-合并-写全程持锁，任何条目都不丢。"""
        errors: list[Exception] = []

        def writer(i: int) -> None:
            try:
                for _ in range(10):
                    svc.save_entry(f"p{i}", build_cache_entry([f"m{i}"], None, "none"))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert set(svc.load()) == {f"p{i}" for i in range(8)}

    def test_custom_path_isolation(self, tmp_path):
        """两个实例指向不同文件互不干扰（测试隔离依赖这一点）。"""
        a = ModelCacheService(tmp_path / "a.json")
        b = ModelCacheService(tmp_path / "b.json")
        a.save_entry("x", build_cache_entry([], None, "none"))
        assert b.load() == {}
        assert a.get("x") is not None
