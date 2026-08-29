# 卡片详情弹框任务 Brief：Model Info + Plan 档级缓存

- 任务 ID：2026-08-29-model-info-and-plan-cache
- 日期：2026-08-29
- 委派：Claude Code（通过 OpenClaw ACP）
- 验收人：FrankMei（猫哥）
- 上游背景：决策纪要见对话历史与 docs/decisions/（追加 0004）

## 任务背景与目标

现状：Plan Dashboard 卡片只显示每个 provider 的用量百分比，但用户**不知道自己买的是哪档 Plan**（如智谱 Lite / Pro / Max、火山方舟 Coding Plan 哪一个），也无法看到该 Plan 覆盖了哪些模型。

目标：为每张卡片新增"详情"入口，单击后弹出**只读 modal**，展示 ① 当前 Plan 档级（plan_name）；② 支持的模型列表（可搜索/滚动）；③ 上次刷新时间 + 手动刷新按钮。**首查 → 缓存 → 手动刷新**：避免每次打开弹框都请求第三方 API。

## 项目位置

`C:\Users\never\.openclaw\workspace\tools\plan-dashboard\`

**必读文档**：
- `README.md`
- `docs/architecture.md` — 适配器契约（本期扩展 `fetch_models()` 与 `fetch_plan_name()`）
- `docs/decisions/0001~0003.md`
- `docs/new-provider-checklist.md` — 接入规范
- `docs/research/providers/*.md` — 各厂商接口档案
- 上期 task-brief 与 review report（参考节奏）

> 文档是设计权威。若与本 brief 冲突，以文档为准并标注；若发现文档错误，在 result.json 中指出而不是擅自改。

## 已达成共识的设计决策（11 项不要重提）

| # | 决策 | 值 |
|---|------|----|
| D1 | 缓存存储 | `data/model_cache.json`（与 config.json 同风格的纯文件） |
| D2 | 失效策略 | 首查 → 之后读缓存 → 手动按钮刷新 |
| D3 | 弹框 UI | 原生 HTML `<dialog>` 覆盖层，深色科技风 |
| D4 | 模型数据来源 | 调各家 `/v1/models` 或控制面 API |
| **D5'** | **plan_name 三层回退**：adapter 自报 → config.json 手填 → "按量/未知" | 同 |
| D6' | 刷新按钮位置 | 卡片右下角"详情"图标 → 弹框内有"刷新"按钮 |
| D7' | 缓存 key | 单文件 `data/model_cache.json` 顶层 `{provider_id: {...}}` |
| D8' | 缓存 schema | 见下 |

## 交付物清单（在现有项目内增量修改/新增）

```
src/
├── backend/
│   ├── main.py                  # 新增路由：GET /api/plans/{id}/info / POST /api/plans/{id}/refresh-info
│   ├── model_cache.py           # 新增：ModelCacheService（load/save/get/clear + 幂等写）
│   └── adapters/
│       ├── base.py              # 基类新增 2 个可选方法：fetch_models / fetch_plan_name
│       ├── zhipu.py             # 新增 fetch_models + fetch_plan_name（智谱接口有 plan_name）
│       ├── minimax.py           # 新增 fetch_models
│       ├── deepseek.py          # 新增 fetch_models（按量）
│       ├── kimi.py              # 新增 fetch_models（按量）
│       ├── ark.py               # 新增 fetch_models + fetch_plan_name（火山 AFPUsage 有 plan_name）
│       ├── stepfun.py           # 新增 fetch_models（按量）；fetch_plan_name 返回 None
│       └── bailian.py           # 新增 fetch_models（按量）；fetch_plan_name 尝试拉 Token Plan 主额度
└── frontend/
    └── index.html               # 新增：卡片右下角"详情"图标 + modal 弹框 + 搜索/滚动 + 刷新按钮
tests/
└── test_model_cache.py          # 新增：ModelCacheService 单元测试
└── test_adapters.py            # 追加：每个 adapter 的 fetch_models / fetch_plan_name 测试
data/                            # 自动创建目录
└── .gitignore                   # 加入 *.local.json / cache 排除（运行时产物）
```

## 数据 Schema

### data/model_cache.json

```json
{
  "zhipu": {
    "fetched_at": "2026-08-29T12:34:56+08:00",
    "plan_name": "GLM Coding · Lite 档",
    "plan_name_source": "adapter",
    "models": [
      { "id": "glm-4-plus",     "owned_by": "zhipu" },
      { "id": "glm-4-flash",    "owned_by": "zhipu" }
    ]
  },
  "deepseek": {
    "fetched_at": "2026-08-29T12:34:56+08:00",
    "plan_name": null,
    "plan_name_source": "config",
    "models": [
      { "id": "deepseek-chat",  "owned_by": "deepseek" }
    ]
  }
}
```

### config.json provider entry 增量

```jsonc
{
  "id": "zhipu",
  // 既有字段略
  "plan_name": "GLM Coding · Lite 档"   // 新增可选字段，手填回退值
}
```

### Adapter 方法扩展（BaseAdapter）

```python
def fetch_models(self, api_key: str, extra: dict) -> list[str]:
    """返回该 provider 支持的模型 id 列表。返回 [] 表示不支持查询（如手动/异常）。
    适配器不应抛异常；失败请 return []。"""
    return []  # 默认实现

def fetch_plan_name(self, api_key: str, extra: dict) -> str | None:
    """返回当前购买的 Plan 档级名（如 'GLM Coding · Lite'），无法判定返回 None。
    适配器不应抛异常；失败请 return None。"""
    return None  # 默认实现
```

## API 设计

| 路由 | 方法 | 行为 |
|---|---|---|
| `/api/plans/{id}/info` | GET | 返回 `{fetched_at, plan_name, plan_name_source, models}`。无缓存 → 后端首次查 + 写缓存 + 返回；已有缓存 → 直接返回 |
| `/api/plans/{id}/refresh-info` | POST | 忽略缓存，调 adapter 重查 + 更新缓存 + 返回新结果 |
| `/api/plans/{id}/info` | DELETE（可选） | 清空某 provider 缓存 |

错误态：API Key 缺失 / 第三方报错 → 返回 `{error: "...", fetched_at: 上次成功时间}`，前端弹框显示错误但仍展示**已有缓存**（如有）。

## 前端 UI 设计

```
┌─ 卡片（既有 UI，新增右上角"详情"图标）────────────────┐
│ 智谱 GLM Coding         [⌘]                              │
│ 5h: 89%  Week: 60%   ↻ 重置 3h 后                      │
└──────────────────────────────────────────────────────────┘
       │ 单击"详情"图标
       ▼
┌─ Modal（深色科技风，全屏 70%）────────────────────────┐
│ 智谱 GLM Coding                                    [×] │
│ ──────────────────────────────────────────────────────│
│ 当前套餐:  GLM Coding · Lite 档    [来自 adapter]      │
│ 上次刷新:  3 分钟前                  [刷新 ↻]           │
│ 共支持 27 个模型                                        │
│ ┌───────────────────────────────────────────────────┐ │
│ │ 🔍 输入模型名/ID 过滤...                          │ │
│ │ ─────────────────────────────────────────────────│ │
│ │ glm-4-plus       智谱                             │ │
│ │ glm-4-flash      智谱                             │ │
│ │ ... 滚动列表 ...                                  │ │
│ └───────────────────────────────────────────────────┘ │
│                                              [关闭]    │
└────────────────────────────────────────────────────────────┘
```

## plan_name 三层回退实现细节

```
adapter.fetch_plan_name() → 返回值 | None
                    ↓ (None/空字符串)
config.json entry.plan_name → 手填字符串 | None
                    ↓ (None/空字符串)
前端显示"按量调用"或"未知档级"
```

适配器 `fetch_plan_name` 推荐实现（按 vendor）：
- **智谱 / Z.ai**：现有 `/api/monitor/usage/quota/limit` 响应通常含 plan_name 字段（如有）
- **火山方舟**：现有 GetUsageDetails/AFPUsage 响应内含 PlanNameToPurchaseQuotaMap，可以选最大配额档名
- **MiniMax**：Coding Plan 只有 1 档，返回 `"Coding Plan"` 或 None
- **DeepSeek / Kimi**：按量，无 Plan → 返回 None
- **StepFun**：无 Plan → None
- **Bailian**：尝试拉 Token Plan 套餐名（如果有），否则 None

**任何 vendor 的 fetch_plan_name 实现都不应抛异常**。失败一律返回 None，前端回退到手填值。

## 测试要求

1. `python -m pytest src/tests` 全绿（含新增 + 既有）
2. 新增 ModelCacheService 测试：load/save/clear/原子写/文件不存在/JSON 损坏
3. 每个 adapter 的 fetch_models / fetch_plan_name 测试：
   - 正常路径返回正确
   - HTTP 错误 / 401 / 503 → 返回空值而不是抛异常
4. 前端：modal HTML 在 snapshot 里出现"详情"、"刷新"按钮
5. 三层回退测试：构造 config.json 手填 + adapter 返回 None → 前端获取到手填值

> 所有测试 mock 网络，**禁止**发起真实 API 请求（成本控制硬约束）。

## 验收标准（必须全部满足）

1. `python -m pytest src/tests` 全绿
2. 后端启动后 `GET /api/plans/{id}/info` 返回结构（带或不带缓存）
3. 首次 GET → 实际查一次（mock）→ 第二次 GET 直接返回缓存 → `POST .../refresh-info` 强制重查
4. 配置变更（config.json 里 plan_name）后，前端刷新按钮触发能看到 plan_name 来源切回 config
5. 前端 modal 可打开、列表可滚动可搜索、刷新按钮工作、关闭按钮工作
6. 不改动既有 `/api/plans` 接口契约
7. 不引入新依赖
8. config.example.json 加入新字段 `plan_name`（注释说明可选）
9. README.md 增量更新"卡片详情"章节
10. docs/changelog.md 追加本次变更

## 约束

- 不动现有 `/api/plans`、`/api/refresh` 等接口契约
- 不修改既有 adapter 的 `_fetch`（除新增方法外不破坏）
- 不引入第三方 HTTP 库（沿用 httpx）
- 不在弹框加 eval/动态执行能力
- API Key 仍然只走后端，弹框内不展示 key 完整内容

## 结果回传要求

完成后在项目根创建 `result.json`：
```json
{
  "status": "success",
  "files_created": ["..."],
  "files_modified": ["..."],
  "validation": {
    "tests_passed": true,
    "tests_total": <int>,
    "tests_broken": 0,
    "existing_api_intact": true
  },
  "notes": "实现说明 + plan_name 三层回退实测样例 + 任何与 brief 的偏离说明 + 下一步建议"
}
```

## 预估

预计 1.5-3 小时。复杂点在：modal UI 的样式代码 + 搜索过滤 + 三层回退逻辑的测试矩阵。如超 3 小时请暂停并在 result.json 说明分阶段情况。
