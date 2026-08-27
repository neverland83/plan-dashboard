# Roadmap - Plan Dashboard

## 一期（当前）✅ 范围已定，开发中

**目标**：跑通框架 + 6 家实锤厂商 + 手动兜底

- [x] 项目骨架 + git + ADR 决策记录（0001/0002/0003）
- [x] 调研资产归档（docs/research/providers/）
- [ ] 后端骨架（FastAPI + 配置管理 + 看板 API）
- [ ] 适配器：智谱（monitor/usage/quota/limit）
- [ ] 适配器：Z.ai 国际（同智谱，host 切换）
- [ ] 适配器：MiniMax（剩余百分比接口）
- [ ] 适配器：DeepSeek（余额接口）
- [ ] 适配器：Kimi（余额接口）
- [ ] 适配器：火山方舟（GetUsageDetails，AK/SK 签名）
- [ ] 适配器：手动录入兜底
- [ ] 前端看板（卡片 + 多窗口环图 + 刷新）
- [ ] 真 key 验证（用户提供）、README 快速开始
- [ ] 一期 review + tag v0.1.0

## 二期（规划）

**目标**：补齐探索型厂商直连

- [ ] 阿里百炼（BSS 资源包 API / RAM 签名）
- [ ] 腾讯云（大模型套餐用量 API）
- [ ] 百度千帆（套餐用量 API）
- [ ] StepFun（Step Plan 用量 API）
- [ ] 按需：更多厂商（硅基流动/DeepInfra/OpenRouter 等）

## 三期+（规划）

- [ ] 余量告警（低于阈值飞书/系统通知）
- [ ] 历史趋势（用量变化曲线，sqlite 持久化）
- [ ] 多 Key 同厂商对比
- [ ] 与 OpenClaw 集成（skill / 命令触发查询）
- [ ] 一键切换厂商配置（类似 CC Switch 的 provider 切换）

## 决策记录

所有关键决策见 docs/decisions/（ADR-0001 技术栈 / 0002 显示口径 / 0003 一期范围）