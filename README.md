# Plan Dashboard - MaaS 套餐用量看板

> 多模型服务商 Coding Plan / Token Plan 套餐余量统一看板。
> 支持在本地 Web 页面配置各家 MaaS 的 API Key，以卡片形式直观展示各套餐限时周期的剩余百分比（类似 CC Switch 的用量显示）。

## 当前状态

- **一期（进行中）**：6 家已确认接口的厂商接入（智谱 / Z.ai / MiniMax / DeepSeek / Kimi / 火山方舟）+ 手动录入兜底
- **二期（规划）**：阿里百炼 / 腾讯云 / 百度千帆 / StepFun 探索接入
- **三期+（规划）**：余量告警、历史趋势、多 Key 对比、与 OpenClaw 集成

详情见 [`docs/roadmap.md`](docs/roadmap.md)

## 快速开始

### 1. 安装依赖

要求 Python 3.10+（本机 3.14 验证通过）：

```powershell
pip install -r src/requirements.txt
```

包含：`fastapi` / `uvicorn` / `httpx` / `pydantic`（火山 AK/SK 签名为纯标准库实现，无额外依赖）。

### 2. 准备配置

复制模板并填入自己的 API Key：

```powershell
copy config.example.json config.json
notepad config.json
```

- 把各条目的 `api_key` 换成真实 Key（`config.json` 已在 `.gitignore` 中排除，不会入库）
- 火山方舟需要在 `extra` 里填 `access_key` / `secret_key` / `plan_quota`（套餐总配额，Tokens）
- 手动型条目在 `extra.windows` 里直接填窗口名 + 已用百分比
- 不想启用的条目设 `"enabled": false`

也可以启动后在前端「⚙ 配置」面板里增删改条目（面板不回显已保存的 Key）。

### 3. 启动服务

```powershell
python -m uvicorn src.backend.main:app --host 127.0.0.1 --port 8712
```

> ⚠️ 仅监听 `127.0.0.1`，不要改成 `0.0.0.0` —— API Key 安全依赖这一点。

打开浏览器访问 <http://127.0.0.1:8712/> 即可看到看板。

### 4. 使用

- 卡片显示每个厂商的各窗口剩余百分比（环形图：绿 >50% / 黄 20–50% / 红 <20%）+ 重置倒计时
- 余额型厂商（DeepSeek/Kimi）显示余额金额与可用状态；手动型卡片带「手动」标记
- 右上角「↻ 刷新」立即重新拉取；后端每 `refresh_interval_minutes`（默认 30 分钟）自动拉取，前端每分钟轮询展示层

### API 一览

| 路由 | 说明 |
|---|---|
| `GET /api/plans` | 所有启用条目的用量数据（含错误态） |
| `POST /api/refresh` | 手动触发全量刷新 |
| `GET /api/config` | 读取配置（脱敏，不含 Key） |
| `POST /api/config` | 保存配置（Key 留空 = 保留原值） |
| `GET /api/providers` | 支持的厂商类型清单 |

### 运行测试

```powershell
python -m pytest src/tests
```

全部测试使用 mock 响应，**不会发起任何真实网络请求**。

## 项目文档索引

| 文档 | 说明 |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | 架构与适配器统一契约 |
| [`docs/roadmap.md`](docs/roadmap.md) | 一/二/三期路线图与待办 |
| [`docs/decisions/`](docs/decisions/) | ADR 决策记录（为什么这么做） |
| [`docs/research/`](docs/research/) | 各厂商接口调研资产（直接可复用） |
| [`docs/task-briefs/`](docs/task-briefs/) | 每次委派 Claude Code 的任务 brief 存档 |
| [`docs/review-reports/`](docs/review-reports/) | 每期 review 报告 |
| [`docs/changelog.md`](docs/changelog.md) | 变更记录 |

## 项目原则

1. **适配器插件架构**：每厂商一个 adapter 文件，统一接口契约，新增厂商不动核心
2. **Key 仅存本地**：密钥不进前端，服务只监听 127.0.0.1
3. **无法直连的用手动兜底**：保证所有厂商都能上板，能直连的逐步替换
4. **调研资产先归档再开发**：社区方案（CC Switch extractor 等）都记录在案

---
FrankMei (neverland_83@163.com) · 2026-08-27