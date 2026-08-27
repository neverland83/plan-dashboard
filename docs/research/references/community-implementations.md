# 外部参考资源归档

> 这些是开发一期适配器时的直接参考资料，全部来自社区已验证实现。

## 1. CC Switch（farion1231/cc-switch）

GitHub: https://github.com/farion1231/cc-switch

**这是最核心参考**——它已实现多家厂商的用量查询，且是用户点名参照的产品（显示格式、交互）。

关键材料：
- 智谱 GLM Coding Plan 用量脚本：GitHub discussion #1038
  - 端点：GET https://open.bigmodel.cn/api/monitor/usage/quota/limit
  - 认证：Authorization: {{apiKey}}（裸 key）
  - extractor 解析 data.limits[]（TIME_LIMIT/TOKENS_LIMIT）→ percentage
- MiniMax 适配（v3.16.2，#3518）：新余额接口返回剩余百分比；过滤非编程模型；兼容无周限额套餐
- Kimi 余额模式（issue #4455）：GET https://api.moonshot.cn/v1/users/me/balance
- 智谱配额请求按 base URL 主机路由（v3.16.2，#3702）→ 国内 open.bigmodel.cn / 国际 api.z.ai

**取源码方式**（开发时）：
```bash
git clone --depth 1 https://github.com/farion1231/cc-switch.git /tmp/cc-switch
# 重点看 src-tauri/src/services/balance.rs（余额适配器）
# 及前端 UsageScriptModal（extractor 脚本定义）
```

## 2. zai_rs（Rust，Coding Plan 用量查询）

- docs: https://docs.rs/zai-rs/latest/zai_rs/usage/index.html
- 同接口：GET /api/monitor/usage/quota/limit
- 提供类型化响应 CodingPlanUsageResponse，窗口：TIME_LIMIT（5h）/ TOKENS_LIMIT（周）
- 参考其字段语义（quota/used/remaining/percentage/next_reset_at）

## 3. CodexBar（z.ai / GLM provider 配额）

- GitHub: https://github.com/steipete/CodexBar → docs/zai.md
- 支持区域：global（api.z.ai）/ CN（open.bigmodel.cn）
- 团队版 header：Bigmodel-Organization / Bigmodel-Project（从控制台用量页 DevTools 获取）
- 也可覆盖配额 URL：Z_AI_QUOTA_URL

## 4. Zhipu Tools Coding Plan（OpenClaw skill）

- 来源：clawhub（skill 名 zhipu-tools / zhipu-tools-coding-plan）
- 命令：`python3 scripts/zhipu_tool.py balance` / `--raw`
- 返回：套餐等级 + MCP 月度配额 + 5小时/周窗口百分比
- 端点：GET open.bigmodel.cn/api/monitor/usage/quota/limit（裸 key 认证，无 Bearer）

## 5. coding-plan-monitor（社区 CLI）

- https://github.com/JinHanAI/coding-plan-monitor
- 智谱 Coding Plan 命令行监控

## 6. glm-plan-usage（智谱官方插件）

- https://docs.bigmodel.cn/cn/coding-plan/extension/usage-query-plugin
- 官方用量查询插件（zai_rs 文档中提及已验证）

---
归档日期：2026-08-27