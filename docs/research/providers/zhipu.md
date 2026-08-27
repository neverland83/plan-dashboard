# 智谱 GLM Coding Plan 用量查询

> 状态：🟢 实锤（社区验证，CC Switch 采用）
> 归档日期：2026-08-27

## 接口

```
GET https://open.bigmodel.cn/api/monitor/usage/quota/limit
Headers:
  Authorization: {{apiKey}}     ← 裸 key，不加 Bearer 前缀
  Accept-Language: en-US,en
  Content-Type: application/json
```

## 响应结构（社区 extractor 已验证）

```json
{
  "success": true,
  "msg": "",
  "data": {
    "level": "pro",              // 套餐等级 lite/pro/max
    "limits": [
      {
        "type": "TIME_LIMIT",     // 5 小时窗口
        "percentage": 1,          // 已用百分比 0-100
        "nextResetTime": "2026-08-27T..."
      },
      {
        "type": "TOKENS_LIMIT",   // 7 天/周窗口
        "percentage": 20,
        "nextResetTime": "2026-08-28T..."
      }
    ]
  }
}
```

## 解析要点

- `percentage` 是**已用百分比**，剩余 = 100 - percentage
- `level` → 套餐名：lite / pro / max
- CC Switch 显示格式：`5小时: X% 4h37m` / `7天: Y% 1d16h`（重置倒计时由 nextResetTime 计算）

## 来源

- CC Switch 用量脚本示例（GitHub discussion #1038）
- docs.rs zai_rs usage 模块（同接口，验证过）
- Zhipu Tools Coding Plan skill（clawhub，`zhipu_tool.py balance`）
- CodexBar（支持团队版 header：Bigmodel-Organization / Bigmodel-Project）

## 补充说明

- 智谱套餐窗口：每 5 小时（动态刷新）+ 每 7 天（周）
- ⚠️ **勘误（2026-08-27 一期开发确认）**：`nextResetTime` 是**毫秒时间戳**（非 ISO 字符串），前端需转 Date；CC Switch 实际还依赖 `limits[].unit` 字段归类（3=5小时 / 6=周），纯看 type 会把周口窗口排错序 → 适配器做双轨兼容（TIME_LIMIT→5h，TOKENS_LIMIT 按 unit 归类，兜底分配）
- 团队套餐 key 与个人 key 独立
- 其他官方文档：https://docs.bigmodel.cn/cn/coding-plan/