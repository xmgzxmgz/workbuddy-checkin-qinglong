# WorkBuddy 自动化工具箱（青龙面板版）

> 一套纯 Python 脚本，把 WorkBuddy / CodeBuddy 的「每日签到」和「宠物自动探险领积分」两个高频手动操作完全自动化，适合跑在 [青龙面板](https://github.com/whyour/qinglong) 上定时执行。

[![GitHub](https://img.shields.io/badge/GitHub-xmgzxmgz%2Fworkbuddy--checkin--qinglong-blue?logo=github)](https://github.com/xmgzxmgz/workbuddy-checkin-qinglong)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![青龙](https://img.shields.io/badge/Platform-青龙面板-orange)](https://github.com/whyour/qinglong)

---

## ✨ 功能

| 脚本 | 功能 | 状态 |
| --- | --- | --- |
| `workbuddy_checkin.py` | 每日自动签到，领取积分 | ✅ 稳定 |
| `workbuddy_buddy_travel.py` | 宠物自动探险（派出）+ 归来后自动领取积分 | ✅ 稳定 |

两个脚本共用同一套设计原则：

- **纯 Python，零重依赖**：仅需标准库，或 `requests`（青龙一般已自带），无需虚拟环境
- **Token 不写死**：全部从环境变量读取，支持多账号一行配置
- **幂等安全**：高频运行无副作用；今日已签到 / 宠物空闲时调用领取接口会被优雅跳过
- **青龙友好**：输出直接被面板捕获并推送通知（Server 酱 / 钉钉 / 企业微信 / Telegram 等）

> ⚠️ 本工具仅向官方接口 `copilot.tencent.com` 发送**你自己的** Bearer Token，不会上传到任何第三方。**Token 属于敏感凭证，请勿提交到公开仓库、也不要在公开场合泄露。** 登录态通常约 90 天有效，过期后需重新获取并更新环境变量。

---

## 🙏 致谢 & 功能缘起

本项目的「宠物自动探险并自动领取积分」能力，由社区用户 **[@jinyehyy](https://github.com/jinyehyy)（能猫期货哥）** 在 [Issue #1](https://github.com/xmgzxmgz/workbuddy-checkin-qinglong/issues/1) 中提出：

> 宠物派出后，需要手动操作领取积分。希望新增自动化能力：完成宠物派出之后，自动执行积分领取，无需人工介入，实现完整自动化流程。

感谢 @jinyehyy 的需求反馈，已在本仓库实现并随 `workbuddy_buddy_travel.py` 一起发布。欢迎更多朋友提 Issue / PR。

---

## 📦 获取 Token

1. 登录 WorkBuddy / CodeBuddy 桌面客户端。
2. 找到本机登录态文件：
   - macOS：`~/Library/Application Support/CodeBuddyExtension/Data/Public/auth/workbuddy-desktop.info`
   - Windows：`%APPDATA%\CodeBuddyExtension\Data\Public\auth\workbuddy-desktop.info`
   - Linux：`~/.config/CodeBuddyExtension/Data/Public/auth/workbuddy-desktop.info`
3. 用任意编辑器打开，取 `auth.accessToken` 字段的整串值（通常以 `eyJ` 开头）作为 Token。

---

## 🔧 环境变量

| 变量名 | 必填 | 说明 |
| --- | --- | --- |
| `WB_ACCESS_TOKEN` | 二选一 | 单个账号的 Token |
| `WB_ACCESS_TOKENS` | 二选一 | 多账号，逗号分隔；支持 `uid:token` 或纯 `token` |
| `WB_USER_ID` | 否 | 手动指定 X-User-Id；不填时自动从 JWT 解析 `sub` |
| `WB_TRAVEL_LOCATION` | 否 | 宠物探险地点（`workbuddy_buddy_travel.py`）：填数字 id 或 code，不填取配置第一个 |
| `WB_TRAVEL_AUTO_DEPART` | 否 | 默认 `1`；设为 `0` 则【只领取、不自动派出】 |
| `WB_PROXY` | 否 | 默认直连；如需代理填 `http://127.0.0.1:7897` 或 `socks5://127.0.0.1:7897` |
| `QINGLONG_NOTIFY` | 否 | 默认 `1`；设为 `0` 关闭青龙通知标记 |

多账号示例：

```
WB_ACCESS_TOKENS=eyJxxxx.aaaa.bbbb,eyJyyyy.cccc.dddd
```

或带 uid（避免解析）：

```
WB_ACCESS_TOKENS=uid1:eyJxxxx.aaaa.bbbb,uid2:eyJyyyy.cccc.dddd
```

---

## 🚀 青龙面板部署

### 1. 拉取脚本

面板「脚本管理」→ 新建 → 文件名分别填 `workbuddy_checkin.py` / `workbuddy_buddy_travel.py` → 粘贴本仓库对应文件内容 → 保存。
（如面板依赖管理缺失 `requests`，在「依赖管理」添加 Python 依赖 `requests`。）

### 2. 配置环境变量

面板「环境变量」→ 新建：
- 名称 `WB_ACCESS_TOKEN`，值填你的 Token（单账号）；
- 或名称 `WB_ACCESS_TOKENS`，值填多个 Token（多账号）。

### 3. 添加定时任务

面板「定时任务」→ 新建：
- 命令：`task workbuddy_checkin.py`（签到）
- 命令：`task workbuddy_buddy_travel.py`（宠物探险）
- 定时规则（cron）：建议每天 1~2 次，例如

  ```
  0 9 * * *
  ```

  宠物探险建议频率更高一点（如每 2~3 小时一次），以便归来后尽快自动领取：

  ```
  0 */3 * * *
  ```

### 4. 运行并查看通知

手动点「运行」测试一次；成功 / 失败都会打印到任务日志，并被青龙通知渠道推送。

---

## 💻 本地调试（不依赖青龙）

```bash
pip install requests

# 每日签到
export WB_ACCESS_TOKEN="eyJxxxx..."
python3 workbuddy_checkin.py

# 宠物自动探险 + 自动领取
export WB_ACCESS_TOKEN="eyJxxxx..."
python3 workbuddy_buddy_travel.py
```

---

## 🐱 宠物自动探险说明（`workbuddy_buddy_travel.py`）

把 WorkBuddy「成长空间 / 成长中心」网页里的宠物探险玩法自动化：

1. 查询宠物旅行状态 `travel/status`
   - `state == "arrived"` → 自动领取积分（`POST travel/claim`）
   - `state == "idle"` 且未达每日上限 → 自动派出（`POST travel/depart`）
   - `state == "traveling"` → 还在路上，下一轮定时再查（不重复派出）
   - `daily_limit_reached == true` → 今日已达派出上限，跳过
2. 幂等安全：高频运行无副作用；空闲时调用领取接口返回 400 已处理，不会报错

> 实测规律：每个账号**每天只能派出 1 次**，宠物归来（通常 1~4 小时后）需手动领取——本脚本正是把"派出 → 归来 → 领取"整条链路自动化，无需人工介入。

---

## 📡 接口说明

| 用途 | 方法 | 路径 |
| --- | --- | --- |
| 签到状态 | GET | `https://copilot.tencent.com/v2/billing/meter/checkin-activity-status` |
| 执行签到 | POST | `https://copilot.tencent.com/v2/billing/meter/daily-checkin` |
| 宠物旅行状态 | GET | `https://copilot.tencent.com/activity/growth/buddy/travel/status` |
| 宠物旅行配置 | GET | `https://copilot.tencent.com/activity/growth/buddy/travel/config` |
| 宠物派出 | POST | `https://copilot.tencent.com/activity/growth/buddy/travel/depart` |
| 宠物积分领取 | POST | `https://copilot.tencent.com/activity/growth/buddy/travel/claim` |

---

## ❓ 常见问题

- **401 登录态失效**：Token 过期或被踢下线，重新从客户端获取并更新环境变量即可。
- **多账号失败**：检查 `WB_ACCESS_TOKENS` 是否用英文逗号分隔，Token 是否完整（别漏掉末尾的 `.` 段）。
- **获取失败 / 风控**：脚本已内置账号间 1 秒间隔；若仍频繁失败，调低运行频率。
- **宠物一直"探险中"**：派出的宠物需要数小时才会归来，归来后脚本下一次运行会自动领取，属正常现象。

---

## 📄 许可

MIT
