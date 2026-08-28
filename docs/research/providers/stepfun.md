# StepFun 账户余额查询

> 状态：🟢 实锤（官方公开 API）+ 🟡 部分（Step Plan 月池/加油包无 API）
> 归档日期：2026-08-28

## 接口

```
GET https://api.stepfun.com/v1/accounts
Headers:
  Authorization: Bearer <API_KEY>
  Accept: application/json
```

> 注意：Step Plan 专用 Base URL 是 `https://api.stepfun.com/step_plan/v1`，
> 但账户余额接口在标准端点 `/v1/accounts`（step_plan 路径下实测 404）。

## 响应结构

```json
{
  "object": "account",
  "type": "prepaid",
  "balance": -0.07,
  "total_cash_balance": 0.00,
  "total_voucher_balance": 0.00
}
```

## 说明

- StepFun 无"周期套餐"；Step Plan 是订阅制（Credit 月池 + 加油包），
  但官方**没有公开查询 Step Plan 用量的 API**（探测 /usage /balance /billing 均 404）
- 此接口返回的是**按量账户余额**（type=prepaid/postpaid）
- Step Plan 月池 / 加油包余量只能在控制台查看 → 看板用 `extra.manual_credits`
  手动录入展示：`[{"name": "加油包", "remaining": 45}]`（remaining=剩余百分比）

## 来源

- 官方文档：https://platform.stepfun.com/docs/zh/api-reference/accounts/get.md
- Step Plan 概述（说明 Credit 与账户余额独立）：https://platform.stepfun.com/docs/zh/step-plan/overview