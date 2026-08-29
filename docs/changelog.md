# Changelog - Plan Dashboard

## [0.2.0] - 2026-08-29（卡片详情弹框）
- 新增卡片「☰ 详情」入口 + 原生 `<dialog>` 只读弹框：Plan 档级、模型列表（可搜索/滚动）、上次刷新时间 + 手动刷新
- 新增 `ModelCacheService`：`data/model_cache.json` 单文件缓存（per-provider），原子写、损坏回退、线程安全
- 新增路由：`GET /api/plans/{id}/info`（首查→缓存→返回）、`POST /api/plans/{id}/refresh-info`（强制重查）、`DELETE /api/plans/{id}/info`（清缓存）
- 适配器契约扩展：`BaseAdapter.fetch_models()` / `fetch_plan_name()`（默认 []/None，绝不抛异常）；zhipu/minimax/deepseek/kimi/ark/stepfun/bailian 各自实现
- plan_name 三层回退：adapter 自报 → config.json 手填（新增可选字段 `plan_name`）→ 「按量调用/未知档级」
- 模型列表端点：智谱 `{host}/api/paas/v4/models`、MiniMax `{host}/v1/models`、DeepSeek `/models`、Kimi `{host}/v1/models`、StepFun `/v1/models`、百炼 dashscope compatible-mode（有 key 才查）、火山管控面 `ListFoundationModels`（V4 签名复用）
- 测试：+82（ModelCacheService 22 / adapter 详情方法 44 / 详情路由与三层回退 16），全 mock 零真实请求
- 既有 `/api/plans` 等接口契约不变

## [0.1.0] - 2026-08-27（一期完成）
- Claude Code 开发完成（经 ACP 委派）：后端 6 适配器 + 前端看板 + 48 测试全过
- Reviewer 实测通过：uvicorn 启动 / API 结构 / 前端 200
- 调研勘误回填：zhipu nextResetTime 毫秒时间戳 + unit 字段；minimax 接口全确认
- 见 docs/review-reports/2026-08-27-phase1.md

## [0.1.0] - 一期（开发中）
- 立项：MaaS 套餐用量看板
- 决策：FastAPI + 单页 Web + 适配器架构（ADR-0001/0002/0003）
- 范围：6 家实锤厂商（智谱/Z.ai/MiniMax/DeepSeek/Kimi/火山方舟）+ 手动兜底
- 资产：调研归档、架构文档、路线图

---
FrankMei (neverland_83@163.com)

