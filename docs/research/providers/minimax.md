# MiniMax 套餐用量查询

> 状态：🟢 实锤（CC Switch v3.16.2 已适配，新余额接口返回剩余百分比）
> 归档日期：2026-08-27

## 接口

CC Switch v3.16.2 release notes：
> "适配 MiniMax Coding Plan 配额的新余额接口（新接口返回**剩余百分比**字段，而非旧解析器依赖的用量计数），过滤掉非编程模型（如视频），兼容无周限额的套餐"

- 端点：**开发时从 CC Switch 源码提取确认**（`src-tauri/src/services/balance.rs` 的 MiniMax 分支）
- 参考：MiniMax 开放平台 `https://api.minimaxi.com` 方向

## 已知信息

- 新接口直接返回**剩余百分比**
- 需要过滤非编程模型（如视频生成模型）
- 部分套餐可能没有周限额 → adapter 需处理缺失窗口

## 待确认（开发时）

- [ ] 精确端点路径
- [ ] 请求头/参数格式
- [ ] 响应字段名

## 来源

- CC Switch v3.16.2 Release Notes (#3518)
- 本地 mmx-cli skill（MiniMax 相关，可能有线索）