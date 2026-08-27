# Z.ai 国际版 Coding Plan 用量查询

> 状态：🟢 实锤（与智谱同接口，仅 host 不同）
> 归档日期：2026-08-27

## 接口

```
GET https://api.z.ai/api/monitor/usage/quota/limit
Headers:
  Authorization: {{apiKey}}     ← 裸 key，不加 Bearer
```

## 响应结构

同智谱国内版（见 `zhipu.md`）：`data.limits[]` 含 TIME_LIMIT / TOKENS_LIMIT。

## 与智谱国内版差异

| 项 | 国内 | 国际 |
|---|---|---|
| host | open.bigmodel.cn | api.z.ai |
| 路径 | /api/monitor/usage/quota/limit | 同左 |
| 认证 | 裸 key | 同左 |

> ✅ 适配器可以共用一个实现，仅 host 配置不同。

## 来源

- CC Switch 提取器（说明 "If you are using Z.ai, just replace https://open.bigmodel.cn to https://api.z.ai"）
- CodexBar z.ai provider 文档