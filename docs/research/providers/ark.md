# 火山方舟（Volcengine Ark）套餐用量查询

> 状态：🟢 可行（官方 OpenAPI，需 AK/SK 签名）
> 归档日期：2026-08-27

## 接口（套餐用量详情）

```
POST https://ark.cn-beijing.volcengineapi.com/?Action=GetUsageDetails&Version=2024-01-01
```

请求体：
```json
{
  "QueryInterval": "Day",
  "Filter": {
    "ObjectName": ["doubao-seed-1.6", "GLM-4.7"],
    "PlanType": ["Large"],
    "StartTime": "2026-05-01",
    "EndTime": "2026-05-10"
  }
}
```

响应：`Result.Details[]`：`{ Time, ObjectName, Usage, Unit: "Tokens", BillingType: "WithinPlan" }`

## 相关接口

- `GetInferenceUsage`（查询推理用量；2026-08-12 后新 Key 仅支持 ApiKeyID 查询）
- `GetSeatUsageDetails`（企业版席位用量）
- 认证：火山引擎 OpenAPI 签名（AccessKey/SecretKey + V4 签名）

## 说明

- Coding Plan 套餐窗口：每 5 小时 / 周（周一重置）/ 月（自然月）
- 无公开的"剩余配额"直查接口，需要：已知套餐上限 → 用 GetUsageDetails 算出已用 → 剩余% = (上限-已用)/上限
- 套餐上限见控制台；**开发时需确认是否可通过 API 获取套餐定义（PlanType/限额）**，否则用户在配置里手填套餐总配额
- ⚠️ 套餐额度仅在 AI 编程工具中生效（Coding Plan 端点）
- 🔑 OpenClaw 中已有 `agent-plan` provider（方舟 Token Plan），其 apiKey 格式为 ark-xxx

## 来源

- 火山引擎文档：
  - GetUsageDetails: https://www.volcengine.com/docs/82379/2479849
  - GetInferenceUsage: https://www.volcengine.com/docs/82379/2116766
  - 套餐概览: https://www.volcengine.com/docs/82379/1925114