# Kimi / Moonshot 账户余额查询

> 状态：🟢 实锤（官方公开 API）
> 归档日期：2026-08-27

## 接口

```
GET https://api.moonshot.cn/v1/users/me/balance
Headers:
  Authorization: Bearer <API_KEY>
```

## 响应结构

```json
{
  "code": 0,
  "data": {
    "available_balance": 49.59,
    "voucher_balance": 46.59,
    "cash_balance": 3.00
  },
  "scode": "0x0",
  "status": true
}
```

## 说明

- 按量计费（无周期套餐窗口）
- 可用余额 = 现金 + 代金券；不可为负
- 代金券有效期 30 天（voucher）
- 速率限制（RPM/TPM/RPD）在控制台查看，不在余额接口

## 变体

| 地域 | 端点 |
|---|---|
| Kimi CN | https://api.moonshot.cn/v1/users/me/balance |
| Kimi EN | https://api.kimi.ai/v1/users/me/balance |

## 来源

- 官方文档：https://platform.kimi.com/docs/api/balance
- CC Switch issue #4455（社区确认）