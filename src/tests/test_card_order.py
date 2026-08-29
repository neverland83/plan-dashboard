"""卡片拖拽排序测试。

三层覆盖：
1. config 默认顺序稳定（后端 config 解析顺序 == providers 数组顺序，是前端回退顺序的基准）
2. 顺序解析语义的纯 Python 镜像实现（resolve_order_reference）——语义文档化，
   无 Node 环境时测试仍然可跑
3. 前端真实 JS 逻辑（index.html 的 [order-pure] 段）经 Node 执行验证——保证
   测试覆盖的就是浏览器里跑的代码（无 Node 时 skip，不阻塞 CI）
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.conftest import write_config

FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "index.html"


# ---- 1. config 默认顺序稳定 --------------------------------------------------

class TestConfigDefaultOrder:
    def test_provider_order_matches_config_array(self, isolated_config):
        """config.json providers 数组顺序 == 加载后顺序（前端回退顺序的基准）。"""
        ids = ["zhipu", "deepseek", "minimax", "ark", "stepfun", "bailian"]
        write_config(isolated_config, [
            {"id": i, "name": i, "type": "manual", "api_key": "", "extra": {},
             "enabled": True}
            for i in ids
        ])
        import backend.config as cfg_mod
        loaded = cfg_mod.load_config()
        assert [e["id"] for e in loaded["providers"]] == ids

    def test_order_stable_across_save_roundtrip(self, isolated_config):
        """保存 → 加载往返不重排（前端拿到的 config 顺序跨会话稳定）。"""
        ids = ["b", "a", "c"]
        write_config(isolated_config, [
            {"id": i, "name": i, "type": "manual", "api_key": "", "extra": {},
             "enabled": True}
            for i in ids
        ])
        import backend.config as cfg_mod
        cfg = cfg_mod.load_config()
        cfg_mod.save_config(cfg)
        assert [e["id"] for e in cfg_mod.load_config()["providers"]] == ids

    def test_store_keeps_config_order(self, isolated_config):
        """UsageStore 按 config 顺序返回 plans，且带 entry_id（前端排序身份）。"""
        from tests.conftest import write_config as wc
        wc(isolated_config, [
            {"id": "m2", "name": "第二", "type": "manual", "api_key": "",
             "extra": {"windows": [{"name": "月", "percentage": 10}]}, "enabled": True},
            {"id": "m1", "name": "第一", "type": "manual", "api_key": "",
             "extra": {"windows": [{"name": "月", "percentage": 20}]}, "enabled": True},
        ])
        from backend.store import UsageStore
        plans = UsageStore().get_all()
        assert [p["entry_id"] for p in plans] == ["m2", "m1"]


# ---- 2. 顺序解析语义 · 纯 Python 镜像 ---------------------------------------

def resolve_order_reference(saved, config_ids):
    """resolveCardOrder 的参考实现（与 index.html 纯函数语义一致）。

    - saved 中已不存在的 id 剔除；重复 id 只留首个
    - config 新增 id 按 config 顺序追加末尾
    """
    valid = set(config_ids)
    kept, kept_set = [], set()
    for cid in saved or []:
        if cid in valid and cid not in kept_set:
            kept.append(cid)
            kept_set.add(cid)
    return kept + [c for c in config_ids if c not in kept_set]


class TestResolveOrderSemantics:
    def test_saved_order_wins(self):
        assert resolve_order_reference(["c", "a"], ["a", "b", "c"]) == ["c", "a", "b"]

    def test_no_saved_order_uses_config_order(self):
        ids = ["zhipu", "deepseek", "minimax"]
        assert resolve_order_reference(None, ids) == ids

    def test_removed_provider_dropped(self):
        # bailian 从 config 删除后，saved 里的 bailian 被清理
        assert resolve_order_reference(
            ["bailian", "zhipu", "ark"], ["zhipu", "ark", "stepfun"]) == ["zhipu", "ark", "stepfun"]

    def test_new_provider_appended_at_end(self):
        # config 新增 stepfun → 追加到已保存顺序末尾，而非插入开头/中间
        assert resolve_order_reference(
            ["ark", "zhipu"], ["zhipu", "ark", "stepfun"]) == ["ark", "zhipu", "stepfun"]

    def test_duplicate_ids_kept_once(self):
        assert resolve_order_reference(
            ["a", "a", "b"], ["a", "b"]) == ["a", "b"]

    def test_non_string_entries_ignored(self):
        # 损坏数据混入数字/null → 剔除不报错
        assert resolve_order_reference(
            ["a", 3, None, "b"], ["a", "b"]) == ["a", "b"]

    def test_corrupt_saved_ignored(self):
        # 非数组（模拟 JSON 损坏回退 null）→ 用 config 原顺序
        assert resolve_order_reference(None, ["x", "y"]) == ["x", "y"]


# ---- 3. 前端真实 JS 逻辑（Node 桥接） ---------------------------------------

ORDER_PURE_RE = re.compile(
    r"// ==== \[order-pure:begin\] ====(.*?)// ==== \[order-pure:end\] ====", re.S)


@pytest.fixture()
def run_js():
    """执行 index.html 中 [order-pure] 段的 JS 表达式，返回结果列表。"""
    if shutil.which("node") is None:
        pytest.skip("无 Node 环境：前端 JS 单测跳过（语义已由纯 Python 镜像覆盖）")
    html = FRONTEND.read_text(encoding="utf-8")
    m = ORDER_PURE_RE.search(html)
    assert m, "index.html 缺少 [order-pure] 标记段"
    js_src = m.group(1)

    def _run(exprs: list[str]) -> list:
        # 源码以 JSON 字符串内嵌，避免命令行转义问题；函数声明经 sloppy eval 提升到全局
        script = (
            "const src = " + json.dumps(js_src) + ";\n"
            "eval(src);\n"
            "const cases = " + json.dumps([{"expr": e} for e in exprs]) + ";\n"
            "console.log(JSON.stringify(cases.map(c => {"
            " try { return {ok: true, out: eval(c.expr)}; }"
            " catch (e) { return {ok: false, err: String(e)}; }"
            "})));\n"
        )
        proc = subprocess.run(
            ["node", "-e", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
        assert proc.returncode == 0, f"Node 执行失败：{proc.stderr}"
        results = json.loads(proc.stdout)
        for r in results:
            assert r["ok"], f"JS 表达式抛错：{r.get('err')}"
        return [r["out"] for r in results]

    return _run


@pytest.mark.skipif(shutil.which("node") is None, reason="无 Node 环境")
class TestFrontendJS:
    """直接测 index.html 里真实的前端纯函数。"""

    def test_resolve_order_full_scenario(self, run_js):
        """完整场景：用户拖过 3 张卡 + config 新增 1 张、删除 1 张。"""
        (kept,) = run_js([
            'resolveCardOrder(["d","b","x","gone"],["a","b","c","d"])'
        ])
        # x 被移到最前；gone（已删）被清理；a、c（新增）按 config 顺序追加
        assert kept == ["d", "b", "a", "c"]

    def test_card_id_prefers_entry_id(self, run_js):
        (ident,) = run_js(['cardIdOf({entry_id:"m1", provider:"manual"})'])
        assert ident == "m1"

    def test_card_id_falls_back_to_provider(self, run_js):
        (ident,) = run_js(['cardIdOf({provider:"zhipu"})'])
        assert ident == "zhipu"

    def test_sort_plans_by_saved_order(self, run_js):
        (names,) = run_js([
            'sortPlansByOrder(['
            '{entry_id:"a",v:1},{entry_id:"b",v:2},{entry_id:"c",v:3}],["c","a","b"])'
            '.map(p => p.v)'
        ])
        assert names == [3, 1, 2]

    def test_sort_plans_unordered_sink_to_end(self, run_js):
        (names,) = run_js([
            'sortPlansByOrder(['
            '{entry_id:"a",v:1},{entry_id:"b",v:2}],["b"]).map(p => p.v)'
        ])
        assert names == [2, 1]
