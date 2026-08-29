# 架构设计 - Plan Dashboard

## 总体架构

```
┌─────────────────────────────────────────┐
│  Web 看板（单页 HTML，卡片式 UI）          │
│  厂商 Logo + 多窗口剩余%环图 + 重置倒计时   │
└──────────────────┬──────────────────────┘
                   │ HTTP (仅 127.0.0.1)
┌──────────────────▼──────────────────────┐
│  后端服务（Python FastAPI + uvicorn）     │
│  ├─ GET  /api/plans       看板数据        │
│  ├─ POST /api/refresh     手动刷新        │
│  ├─ GET  /api/config      读取配置        │
│  ├─ POST /api/config      保存配置        │
│  ├─ GET  /api/providers   可用厂商列表    │
│  ├─ GET  /api/plans/{id}/info    卡片详情 │
│  ├─ POST /api/plans/{id}/refresh-info 详情强刷 │
│  └─ 定时轮询（30 分钟，可配）             │
└──────────────────┬──────────────────────┘
                   │ adapter 调用
┌──────────────────▼──────────────────────┐
│  适配器层（每厂商一个文件）                │
│  ├─ adapters/zhipu.py    智谱           │
│  ├─ adapters/zai.py      Z.ai 国际       │
│  ├─ adapters/minimax.py  MiniMax        │
│  ├─ adapters/deepseek.py DeepSeek       │
│  ├─ adapters/kimi.py     Kimi           │
│  ├─ adapters/ark.py      火山方舟(签名)  │
│  ├─ adapters/manual.py   手动录入兜底    │
│  └─ adapters/__init__.py 注册表          │
└─────────────────────────────────────────┘
```

## 适配器统一契约

每个 adapter 实现以下接口：

```python
@dataclass
class UsageWindow:
    name: str            # 窗口名："5小时" / "7天" / "周" / "月"
    percentage: float    # 已用百分比 0-100（或剩余百分比，统一约定）
    next_reset: str | None  # ISO 时间或 None

@dataclass
class PlanUsage:
    provider: str        # 厂商 id
    display_name: str    # 显示名
    plan_name: str       # 套餐名（可选）
    windows: list[UsageWindow]  # 多窗口
    raw: dict            # 原始响应（调试用）
    error: str | None    # 出错信息
    updated_at: str      # 更新时间

def fetch(api_key: str, config: dict) -> PlanUsage:
    """查询该厂商套餐用量。config 为该条目额外配置（如地域）。"""
```

**卡片详情扩展（2026-08-29，ADR-0004）** —— 基类提供 2 个可选方法，子类按需覆盖：

```python
def fetch_models(self, api_key: str, extra: dict) -> list[str]:
    """返回该 provider 支持的模型 id 列表。返回 [] 表示不支持查询（如手动/异常）。"""

def fetch_plan_name(self, api_key: str, extra: dict) -> str | None:
    """返回当前购买的 Plan 档级名（如 'GLM Coding Lite'），无法判定返回 None。"""
```

**约定**：
- `percentage` 统一为**已用百分比**（0-100），前端计算剩余 = 100 - percentage（与智谱接口返回一致）
- 纯余额型厂商（DeepSeek/Kimi）：windows 为空，用 `balance` 字段（见下）
- 适配器不得抛异常，必须返回带 error 的 PlanUsage（前端展示失败状态）
- `fetch_models` / `fetch_plan_name` 同样**不得抛异常**：失败分别返回 `[]` / `None`
- plan_name 由路由层三层回退：adapter → config.json `plan_name` 手填 → 前端「按量调用/未知档级」
- 详情数据缓存在 `data/model_cache.json`（`src/backend/model_cache.py`），首查→缓存→手动刷新

## 数据模型（config.json）

```json
{
  "refresh_interval_minutes": 30,
  "providers": [
    {
      "id": "zhipu",
      "name": "智谱 GLM Coding",
      "api_key": "xxx",          // 本地明文，仅本机
      "extra": {},               // 厂商特定配置（如 ark 的 AK/SK、地域）
      "enabled": true
    }
  ]
}
```

## 安全

- 服务只监听 `127.0.0.1`
- API Key 只存后端配置文件，前端只拿展示数据
- 不做任何外部暴露

## 前端

- 单页 `index.html`，无构建步骤
- 原生 JS + CSS（环形进度可用 SVG stroke-dasharray 实现，不引大库）
- 深色科技风（与用户偏好一致）
- 卡片：厂商名 + 套餐名 + 各窗口剩余% + 重置倒计时 + 颜色分级
- 手动刷新按钮 + 定时自动刷新（轮询 /api/plans）
- 配置页：增删改厂商条目（内嵌表单）

---
FrankMei (neverland_83@163.com)