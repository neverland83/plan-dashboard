# MiniMax 套餐用量查询

> 状态：🟢 实锤（已从 CC Switch 源码确认全部细节，2026-08-27 一期开发时验证）
> 归档日期：2026-08-27（更新）

## 接口（已确认）

```
GET https://api.minimaxi.com/v1/api/openplatform/coding_plan/remains
# 国际版：https://api.minimax.io/v1/api/openplatform/coding_plan/remains
Headers:
  Authorization: Bearer <API_KEY>
```

## 响应结构（已确认）

```json
{
  "base_resp": { "status_code": 0, "status_msg": "success" },
  "model_remains": [
    {
      "model_name": "general",        // 取 general（过滤 video 等非编程模型）
      "current_interval_remaining_percent": 95,   // 剩余%！需反转为已用
      "current_weekly_status": 1,     // 1=有周窗口；3=无周限额不展示
      "end_time": 1787000000000       // 重置时间（毫秒时间戳）
    }
  ]
}
```

## 解析要点（CC Switch 源码确认）

- 业务错误判断：`base_resp.status_code != 0`
- **只取 `model_remains[]` 中 `model_name == "general"` 的条目**（过滤 video 等）
- `current_interval_remaining_percent` 是**剩余百分比**（需反转为已用：used = 100 - remaining）
- 5 小时窗口重置时间：`end_time`（毫秒时间戳）
- 周窗口：仅当 `current_weekly_status == 1` 时存在；`3` = 无周限额，不展示
- 兼容无周限额套餐（缺失周窗口时只显示 5h 窗口）

## 来源

- CC Switch 源码 `src-tauri/src/services/coding_plan.rs`（一期开发时克隆确认）
- CC Switch v3.16.2 Release Notes (#3518)