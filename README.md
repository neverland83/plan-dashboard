# Plan Dashboard - MaaS 套餐用量看板

> 多模型服务商 Coding Plan / Token Plan 套餐余量统一看板。
> 支持在本地 Web 页面配置各家 MaaS 的 API Key，以卡片形式直观展示各套餐限时周期的剩余百分比（类似 CC Switch 的用量显示）。

## 当前状态

- **一期（进行中）**：6 家已确认接口的厂商接入（智谱 / Z.ai / MiniMax / DeepSeek / Kimi / 火山方舟）+ 手动录入兜底
- **二期（规划）**：阿里百炼 / 腾讯云 / 百度千帆 / StepFun 探索接入
- **三期+（规划）**：余量告警、历史趋势、多 Key 对比、与 OpenClaw 集成

详情见 [`docs/roadmap.md`](docs/roadmap.md)

## 快速开始

（一期开发完成后补全）

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