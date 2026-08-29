/**
 * 拖拽排序端到端实测（Node 直接跑，无第三方依赖）。
 *
 * 原理：从 src/frontend/index.html 提取真实的 <script> 段，在一个迷你 DOM
 * stub（本文件实现）中执行，然后模拟用户操作：
 *   1. 首次加载 → 卡片按 config 顺序
 *   2. 指针拖拽（mouse）移动卡片 → DOM 重排 + localStorage 写入
 *   3. 再次 loadPlans（模拟刷新）→ 顺序保持
 *   4. 键盘拖拽（Space/方向键/Space、Esc 取消）
 *   5. 触摸拖拽（pointerType=touch）
 *   6. localStorage 损坏 / 隐私模式抛错 → 回退 config 顺序不报错
 *   7. 新增厂商 → 追加末尾；删除厂商 → 从顺序清理
 *   8. 拖拽进行中轮询让路（DOM 不被重建打断）
 *
 * 运行：node scripts/e2e-drag-sort.mjs
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const html = readFileSync(join(ROOT, "src", "frontend", "index.html"), "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

// ---------- 迷你 DOM ----------------------------------------------------------

let nextRectId = 1;

class Style {
  constructor() {
    this._p = {};
    const self = this;
    Object.defineProperty(this, "cssText", {
      get() { return ""; },
      set() { self._p = {}; },
      configurable: true,
    });
  }
}

class ClassList {
  constructor(el) { this._s = new Set(); this._el = el; }
  add(...c) { c.forEach(x => x && this._s.add(x)); this._sync(); }
  remove(...c) { c.forEach(x => this._s.delete(x)); this._sync(); }
  contains(c) { return this._s.has(c); }
  toggle(c) { this._s.has(c) ? this._s.delete(c) : this._s.add(c); this._sync(); }
  _sync() { this._el._attrs.class = [...this._s].join(" "); }
}

class Element {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this._attrs = {};
    this._children = [];
    this.parent = null;
    this._listeners = {};
    this.style = new Style();
    this.classList = new ClassList(this);
    this._rect = null;
  }
  get id() { return this._attrs.id || ""; }
  get dataset() {
    const ds = {};
    for (const [k, v] of Object.entries(this._attrs)) {
      if (k.startsWith("data-")) {
        ds[k.slice(5).replace(/-(\w)/g, (_, c) => c.toUpperCase())] = v;
      }
    }
    return ds;
  }
  get textContent() {
    return this._children.map(c => (typeof c === "string" ? c : c.textContent)).join("");
  }
  set textContent(v) { this._children = [v]; }
  get className() { return this._attrs.class || ""; }
  set className(v) { this.setAttribute("class", v); }

  addEventListener(type, fn) { (this._listeners[type] ||= []).push(fn); }
  removeEventListener(type, fn) {
    this._listeners[type] = (this._listeners[type] || []).filter(f => f !== fn);
  }

  matches(sel) {
    if (sel.startsWith(".")) return this.classList.contains(sel.slice(1));
    if (sel.startsWith("#")) return this.id === sel.slice(1);
    const attr = sel.match(/^\[([\w:-]+)="([^"]*)"\]$/);   // [attr="value"]
    if (attr) return (this._attrs[attr[1]] ?? null) === attr[2];
    return this.tagName === sel.toUpperCase();
  }
  closest(sel) {
    let el = this;
    while (el) { if (el.matches?.(sel)) return el; el = el.parent; }
    return null;
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  querySelectorAll(sel) {
    const out = [];
    // 支持后代组合："A B" → 在子树中先找到 A，再在其子树中找 B；单段 = 全子树匹配
    const parts = sel.trim().split(/\s+/);
    const walk = (n, i) => {
      for (const c of n._children) {
        if (typeof c === "string") continue;
        if (c.matches(parts[i])) {
          if (i === parts.length - 1) out.push(c);
          else walk(c, i + 1);
        }
        walk(c, i);            // 后代组合允许跨层穿透
      }
    };
    walk(this, 0);
    return out;
  }

  appendChild(n) { return this.insertBefore(n, null); }
  insertBefore(n, ref) {
    n.parent?.removeChild(n);
    n.parent = this;
    const i = ref ? this._children.indexOf(ref) : -1;
    if (i < 0) this._children.push(n); else this._children.splice(i, 0, n);
    return n;
  }
  removeChild(n) {
    const i = this._children.indexOf(n);
    if (i >= 0) this._children.splice(i, 1);
    n.parent = null;
    return n;
  }
  remove() { this.parent?.removeChild(this); }

  setAttribute(k, v) {
    this._attrs[k] = String(v);
    if (k === "class") this.classList._s = new Set(String(v).split(/\s+/).filter(Boolean));
  }
  getAttribute(k) { return this._attrs[k] ?? null; }
  get nextElementSibling() {
    if (!this.parent) return null;
    const sib = this.parent._children;
    const i = sib.indexOf(this);
    for (let j = i + 1; j < sib.length; j++) {
      if (typeof sib[j] !== "string") return sib[j];
    }
    return null;
  }
  get previousElementSibling() {
    if (!this.parent) return null;
    const sib = this.parent._children;
    const i = sib.indexOf(this);
    for (let j = i - 1; j >= 0; j--) {
      if (typeof sib[j] !== "string") return sib[j];
    }
    return null;
  }

  getBoundingClientRect() {
    if (this._rect) return this._rect;
    return { left: 0, top: 0, width: 300, height: 180, right: 300, bottom: 180, x: 0, y: 0 };
  }

  set innerHTML(html) { this._children = parseHTML(html, this); }
  get innerHTML() { return ""; }
}

/** 极简 HTML 解析（只处理本项目卡片模板产出的良构标签） */
function parseHTML(html, parent) {
  const rootChildren = [];
  const stack = [{ children: rootChildren }];
  const tagRe = /<\/?([a-zA-Z][\w-]*)((?:\s+[\w:-]+="[^"]*")*)\s*\/?>|([^<]+)/g;
  let m;
  while ((m = tagRe.exec(html))) {
    if (m[1]) {                                    // 标签
      const closing = html[m.index + 1] === "/";
      const selfClosed = /\/>$/.test(m[0]);
      if (closing) { stack.pop(); continue; }
      const el = new Element(m[1]);
      const attrRe = /([\w:-]+)="([^"]*)"/g;
      let a;
      while ((a = attrRe.exec(m[2] || ""))) el.setAttribute(a[1], a[2]);
      stack[stack.length - 1].children.push(el);
      if (!selfClosed) { el.parent = parent && stack.length === 1 ? parent : el.parent; stack.push({ children: el._children, el }); }
      if (stack.length === 1 || stack[stack.length - 1].el !== el) el.parent = stack[0].el || parent;
    } else {                                       // 文本
      stack[stack.length - 1].children.push(m[3]);
    }
  }
  // 修正 parent 链
  const fix = (nodes, p) => {
    for (const n of nodes) {
      if (typeof n === "string") continue;
      n.parent = p;
      fix(n._children, n);
    }
  };
  fix(rootChildren, parent);
  return rootChildren;
}

// ---------- 沙箱环境 ----------------------------------------------------------

function makeLocalStorage({ broken = false } = {}) {
  const map = new Map();
  if (broken) {
    // 隐私模式：访问即抛 SecurityError
    return {
      getItem() { throw new DOMException("denied"); },
      setItem() { throw new DOMException("denied"); },
    };
  }
  return {
    getItem: k => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: k => map.delete(k),
    _map: map,
  };
}

/** 网格布局参数（2 列 × 3 行，卡片 300×180，间距 18，原点 24,90） */
const GRID = { x: 24, y: 90, w: 300, h: 180, gap: 18, cols: 2 };
function layout(grid) {
  const cards = grid._children.filter(
    c => typeof c !== "string" && (c.classList.contains("card") || c.classList.contains("drop-placeholder")));
  cards.forEach((c, i) => {
    c._rect = {
      left: GRID.x + (i % GRID.cols) * (GRID.w + GRID.gap),
      top: GRID.y + Math.floor(i / GRID.cols) * (GRID.h + GRID.gap),
      width: GRID.w, height: GRID.h,
    };
    c._rect.right = c._rect.left + GRID.w;
    c._rect.bottom = c._rect.top + GRID.h;
    c._rect.x = c._rect.left; c._rect.y = c._rect.top;
  });
}

function makeEnv({ storage } = {}) {
  const winListeners = {};
  const document = {
    _ids: new Map(),
    getElementById(id) { return this._ids.get(id) || null; },
    createElement(tag) { return new Element(tag); },
    body: new Element("body"),
    addEventListener() {},
    elementFromPoint(x, y) {
      const grid = this._ids.get("grid");
      for (const c of grid._children) {
        if (typeof c === "string" || !c._rect) continue;
        // 模拟 CSS pointer-events:none（悬浮卡与占位不可命中）
        if (c.classList.contains("dragging") || c.classList.contains("drop-placeholder")) continue;
        const r = c._rect;
        if (x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) return c;
      }
      return null;
    },
  };
  for (const id of ["grid", "updated-at", "drag-live", "btn-refresh", "btn-config",
    "btn-add-entry", "btn-save-cfg", "btn-cancel-cfg", "cfg-dialog", "entries", "interval"]) {
    const el = new Element("div");
    el.setAttribute("id", id);
    document._ids.set(id, el);
  }

  const window = {
    addEventListener(type, fn) { (winListeners[type] ||= []).push(fn); },
    removeEventListener(type, fn) {
      winListeners[type] = (winListeners[type] || []).filter(f => f !== fn);
    },
  };

  /** 事件派发：从 target 冒泡到 grid → document → window */
  function dispatch(target, type, props = {}) {
    const ev = {
      target, type,
      clientX: 0, clientY: 0, button: 0, isPrimary: true,
      pointerType: "mouse", key: "",
      prevented: false,
      preventDefault() { this.prevented = true; },
      stopPropagation() {},
      ...props,
    };
    const path = [];
    let el = target;
    while (el) { path.push(el); el = el.parent; }
    path.push(window);
    for (const node of path) {
      const ls = node === window ? (winListeners[type] || []) : (node._listeners?.[type] || []);
      for (const fn of [...ls]) fn.call(node, ev);
    }
    return ev;
  }

  return { document, window, dispatch, winListeners };
}

// ---------- 断言工具 ----------------------------------------------------------

let passed = 0;
const failures = [];
function check(name, cond, detail = "") {
  if (cond) { passed++; console.log(`  ✓ ${name}`); }
  else { failures.push(name); console.error(`  ✗ ${name} ${detail}`); }
}
function domOrder(doc) {
  return doc.getElementById("grid").querySelectorAll(".card").map(el => el.dataset.entryId);
}
function storedOrder(storage) {
  const raw = storage.getItem("plan-dashboard.cardOrder");
  return raw ? JSON.parse(raw) : null;
}
const PLAN_IDS = ["zhipu", "deepseek", "minimax", "ark", "stepfun", "bailian"];
function makePlans(ids) {
  return ids.map(id => ({
    entry_id: id, provider: id, display_name: id.toUpperCase(),
    kind: "windows", windows: [{ name: "月", percentage: 10, remaining: 90, next_reset: null }],
    balance: null, error: null, updated_at: "2026-08-28T10:00:00+00:00",
  }));
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

// ---------- 场景执行 ----------------------------------------------------------

async function main() {
  const storage = makeLocalStorage();
  const { document, window, dispatch, winListeners } = makeEnv({ storage });

  const plansData = () => ({ ok: true, generated_at: "2026-08-28T10:00:00+00:00", plans: makePlans(PLAN_IDS) });
  const fetchStub = async () => ({ ok: true, json: async () => plansData() });

  // 暴露测试钩子后执行真实前端脚本
  const code = script + "\n;globalThis.__t = { loadPlans, dragSorter, OrderStore, renderPlans };";
  new Function("window", "document", "localStorage", "fetch", "setInterval", "alert", code)(
    window, document, storage, fetchStub, () => 0, msg => { throw new Error("alert: " + msg); });
  const t = globalThis.__t;
  const grid = document.getElementById("grid");

  await sleep(30);   // 等首次 loadPlans 完成

  console.log("\n[1] 首次加载：config 原顺序");
  check("初始顺序 = config 顺序", JSON.stringify(domOrder(document)) === JSON.stringify(PLAN_IDS),
    JSON.stringify(domOrder(document)));
  check("存储已初始化为当前顺序", JSON.stringify(storedOrder(storage)) === JSON.stringify(PLAN_IDS));
  check("每张卡有拖拽手柄且 aria-grabbed=false",
    grid.querySelectorAll(".drag-handle").length === 6 &&
    grid.querySelectorAll('.drag-handle').every(h => h.getAttribute("aria-grabbed") === "false"));
  check("手柄可聚焦 tabindex=0",
    grid.querySelectorAll('.drag-handle').every(h => h.getAttribute("tabindex") === "0"));

  console.log("\n[2] 指针拖拽（mouse）：把 zhipu 拖到 bailian 之后");
  layout(grid);
  const zhipu = grid.querySelector('[data-entry-id="zhipu"]');
  const zhHandle = zhipu.querySelector(".drag-handle");
  const r0 = zhipu.getBoundingClientRect();
  dispatch(zhHandle, "pointerdown", { clientX: r0.left + 10, clientY: r0.top + 10 });
  // 位移不足 5px → 尚未开始
  dispatch(window, "pointermove", { clientX: r0.left + 12, clientY: r0.top + 12 });
  check("5px 阈值内不启动拖拽", !zhipu.classList.contains("dragging"));
  // 拖到 bailian（此时 bailian 在 DOM 第 6 位）右半区
  layout(grid);
  const bailian = grid.querySelector('[data-entry-id="bailian"]');
  const rb = bailian.getBoundingClientRect();
  dispatch(window, "pointermove", { clientX: rb.left + rb.width * 0.75, clientY: rb.top + 10 });
  check("拖拽启动：卡片进入 dragging 态", zhipu.classList.contains("dragging"));
  check("拖拽启动：aria-grabbed=true", zhHandle.getAttribute("aria-grabbed") === "true");
  check("占位指示元素已插入", !!grid.querySelector(".drop-placeholder"));
  dispatch(window, "pointerup");
  const afterDrag = domOrder(document);
  check("放下后 zhipu 移到末尾", JSON.stringify(afterDrag) ===
    JSON.stringify(["deepseek", "minimax", "ark", "stepfun", "bailian", "zhipu"]),
    JSON.stringify(afterDrag));
  check("localStorage 已保存新顺序", JSON.stringify(storedOrder(storage)) === JSON.stringify(afterDrag));
  check("占位已清除", !grid.querySelector(".drop-placeholder"));
  check("拖拽态已清除", !grid.querySelector(".dragging"));
  check("aria-grabbed 复位",
    grid.querySelector('[data-entry-id="zhipu"] .drag-handle').getAttribute("aria-grabbed") === "false");
  check("live region 有播报", document.getElementById("drag-live").textContent.length > 0);

  console.log("\n[3] 刷新（重新 loadPlans）：顺序保持");
  await t.loadPlans();
  await sleep(10);
  check("刷新后顺序 = 拖拽后的顺序", JSON.stringify(domOrder(document)) === JSON.stringify(afterDrag),
    JSON.stringify(domOrder(document)));

  console.log("\n[4] 键盘拖拽：Space 抓取 → 方向键 → Space 放下");
  layout(grid);
  const deepseek = grid.querySelector('[data-entry-id="deepseek"]');
  const dsHandle = deepseek.querySelector(".drag-handle");
  dispatch(dsHandle, "keydown", { key: " " });
  check("Space 抓取：aria-grabbed=true", dsHandle.getAttribute("aria-grabbed") === "true");
  check("Space 抓取：kb-grab 高亮", deepseek.classList.contains("kb-grab"));
  dispatch(dsHandle, "keydown", { key: "ArrowRight" });
  dispatch(dsHandle, "keydown", { key: "ArrowDown" });
  const kbMid = domOrder(document);
  check("方向键移动了卡片", JSON.stringify(kbMid) !== JSON.stringify(afterDrag), JSON.stringify(kbMid));
  dispatch(dsHandle, "keydown", { key: " " });
  check("Space 放下：aria-grabbed=false", dsHandle.getAttribute("aria-grabbed") === "false");
  check("Space 放下：kb-grab 移除", !deepseek.classList.contains("kb-grab"));
  check("键盘顺序已持久化", JSON.stringify(storedOrder(storage)) === JSON.stringify(kbMid));

  console.log("\n[5] 键盘 Esc 取消：顺序不变");
  layout(grid);
  const ark = grid.querySelector('[data-entry-id="ark"]');
  const arkHandle = ark.querySelector(".drag-handle");
  const beforeEsc = domOrder(document);
  dispatch(arkHandle, "keydown", { key: " " });
  dispatch(arkHandle, "keydown", { key: "ArrowLeft" });
  dispatch(arkHandle, "keydown", { key: "Escape" });
  check("Esc 恢复原顺序", JSON.stringify(domOrder(document)) === JSON.stringify(beforeEsc));
  check("Esc 不写存储", JSON.stringify(storedOrder(storage)) === JSON.stringify(beforeEsc));

  console.log("\n[6] 触摸拖拽（pointerType=touch）");
  layout(grid);
  const minimax = grid.querySelector('[data-entry-id="minimax"]');
  const mmHandle = minimax.querySelector(".drag-handle");
  const rm = minimax.getBoundingClientRect();
  dispatch(mmHandle, "pointerdown", { clientX: rm.left + 8, clientY: rm.top + 8, pointerType: "touch" });
  layout(grid);
  const zhipu2 = grid.querySelector('[data-entry-id="zhipu"]');
  const rz = zhipu2.getBoundingClientRect();
  dispatch(window, "pointermove", { clientX: rz.left + 10, clientY: rz.top + 10, pointerType: "touch" });
  dispatch(window, "pointerup", { pointerType: "touch" });
  const afterTouch = domOrder(document);
  check("触摸拖拽生效（minimax 移到 zhipu 前）",
    afterTouch.indexOf("minimax") < afterTouch.indexOf("zhipu"), JSON.stringify(afterTouch));
  check("触摸拖拽后存储同步", JSON.stringify(storedOrder(storage)) === JSON.stringify(afterTouch));

  console.log("\n[7] localStorage 损坏 / 隐私模式 → 回退 config 顺序");
  storage.setItem("plan-dashboard.cardOrder", "{not valid json");
  await t.loadPlans(); await sleep(10);
  check("损坏数据不报错且回退 config 顺序", JSON.stringify(domOrder(document)) === JSON.stringify(PLAN_IDS),
    JSON.stringify(domOrder(document)));
  // 存储被修复写回
  check("损坏数据被解析结果覆盖", JSON.stringify(storedOrder(storage)) === JSON.stringify(PLAN_IDS));

  const storage2 = makeLocalStorage({ broken: true });
  const env2 = makeEnv({ storage: storage2 });
  new Function("window", "document", "localStorage", "fetch", "setInterval", "alert", code)(
    env2.window, env2.document, storage2, fetchStub, () => 0, () => {});
  await sleep(30);
  check("隐私模式（localStorage 抛错）仍能按 config 顺序渲染",
    JSON.stringify(domOrder(env2.document)) === JSON.stringify(PLAN_IDS),
    JSON.stringify(domOrder(env2.document)));

  console.log("\n[8] 新增厂商 → 追加末尾；删除厂商 → 清理");
  // 预置旧顺序（含已删除的 bailian）；config 新增 kimi、删除 bailian
  const ids8 = ["zhipu", "deepseek", "minimax", "ark", "stepfun", "kimi"];
  const storage8 = makeLocalStorage();
  storage8.setItem("plan-dashboard.cardOrder", JSON.stringify(PLAN_IDS));   // 旧顺序含 bailian
  const fetch8 = async () => ({ ok: true, json: async () => ({ ok: true, plans: makePlans(ids8) }) });
  const env3 = makeEnv({ storage: storage8 });
  new Function("window", "document", "localStorage", "fetch", "setInterval", "alert", code)(
    env3.window, env3.document, storage8, fetch8, () => 0, () => {});
  await sleep(30);
  check("bailian 被清理、kimi 追加末尾",
    JSON.stringify(domOrder(env3.document)) === JSON.stringify(ids8),
    JSON.stringify(domOrder(env3.document)));
  check("存储已同步（无 bailian、有 kimi）",
    JSON.stringify(storedOrder(storage8)) === JSON.stringify(ids8),
    JSON.stringify(storedOrder(storage8)));

  console.log("\n[9] 拖拽进行中：轮询渲染让路");
  layout(grid);
  const stepfun = grid.querySelector('[data-entry-id="stepfun"]');
  const sfHandle = stepfun.querySelector(".drag-handle");
  const rsf = stepfun.getBoundingClientRect();
  dispatch(sfHandle, "pointerdown", { clientX: rsf.left + 5, clientY: rsf.top + 5 });
  dispatch(window, "pointermove", { clientX: rsf.left + 40, clientY: rsf.top + 40 });
  check("拖拽中 isActive=true", t.dragSorter.isActive());
  const sentinel = stepfun;   // 引用比对：拖拽中 DOM 不应被重建
  await t.loadPlans(); await sleep(10);
  check("拖拽中 loadPlans 未重建 DOM", grid.querySelector('[data-entry-id="stepfun"]') === sentinel);
  dispatch(window, "pointerup");
  await sleep(10);
  check("松手后恢复渲染且顺序一致", JSON.stringify(domOrder(document)) === JSON.stringify(storedOrder(storage)));

  console.log("\n[10] 点击（未达阈值）不触发拖拽/写存储");
  layout(grid);
  const before = domOrder(document);
  const h = grid.querySelector('[data-entry-id="ark"] .drag-handle');
  const ra = grid.querySelector('[data-entry-id="ark"]').getBoundingClientRect();
  dispatch(h, "pointerdown", { clientX: ra.left + 5, clientY: ra.top + 5 });
  dispatch(window, "pointerup");
  check("顺序未变", JSON.stringify(domOrder(document)) === JSON.stringify(before));
  check("存储未变", JSON.stringify(storedOrder(storage)) === JSON.stringify(before));

  console.log(`\n===== 结果：${passed} 通过，${failures.length} 失败 =====`);
  if (failures.length) { console.error("失败项：", failures); process.exit(1); }
}

// ---------- 入口 ----------

main().catch(e => { console.error(e); process.exit(1); });
