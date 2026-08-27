# 新厂商接入检查清单

> 二期/三期新增厂商时按此流程执行，确保调研→接入→验证闭环。

## 前置调研（无接口则不阻塞）

1. [ ] 确认该厂商是否存在**用量/余额查询 API**（搜索：`<厂商> balance API`、`<厂商> 用量查询 接口`、CC Switch issue/源码）
2. [ ] 是否有**社区已验证实现**可参考（CC Switch extractor、SDK、skill）
3. [ ] 记录到 `docs/research/providers/<vendor>.md`（即使没找到接口，也记录"未找到"供后续复用）
4. [ ] 若只有控制台：**用手动兜底**，二期再找接口

## 开发接入

5. [ ] 在 `src/backend/adapters/<vendor>.py` 实现 `fetch(api_key, config) -> PlanUsage`
6. [ ] 在 `adapters/__init__.py` 注册
7. [ ] 编写单元测试（mock 响应，不发真实请求）
8. [ ] 跑通所有测试

## 真实验证

9. [ ] 用用户提供的真实 key 验证（先算成本：调用次数 × 单次价格，控制成本）
10. [ ] 确认返回的窗口/百分比语义正确（已用 vs 剩余）
11. [ ] 前端显示正常（含失败状态）
12. [ ] 更新 `docs/research/providers/<vendor>.md` 的"待确认"项
13. [ ] 更新 roadmap.md（勾选）、changelog.md、README 快速开始

## 收尾

14. [ ] git commit + tag（如 v0.2.0）
15. [ ] 同步通知用户验收

---
FrankMei (neverland_83@163.com) · 2026-08-27