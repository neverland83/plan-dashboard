# DeepSeek 账户余额查询

> 状态：🟢 实锤（官方公开 API）
> 归档日期：2026-08-27

## 接口

```
GET https://api.deepseek.com/user/balance
Headers:
  Authorization: Bearer <API_KEY>
  Accept: application/json
```

## 响应结构

```json
{
  "is_available": true,
  "balance_infos": [
    {
      "currency": "CNY",
      "total_balance": "110.00",
      "granted_balance": "10.00",
      "topped_up_balance": "100.00"
    }
  ]
}
```

## 说明

- DeepSeek 是**按量计费**（无周期套餐），所以没有"百分比窗口"
- 显示策略：显示余额金额 + 可用状态（is_available），或按用户偏好以"余额充足度"展示
- 余额 = granted（赠金，有有效期）+ topped_up（充值，永久）

## 来源

- 官方文档：https://api-docs.deepseek.com/api/get-user-balance（中英都有）