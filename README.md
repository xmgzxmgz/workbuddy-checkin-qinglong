# WorkBuddy 自动签到（青龙面板版）

适用于 [青龙面板](https://github.com/whyour/qinglong) 的 WorkBuddy / CodeBuddy 每日自动签到脚本。

- 纯 Python，依赖极少（`requests`，青龙一般已自带）
- **Token 不写死在脚本里**，全部从环境变量读取，多账号一行配置
- 幂等：今日已签到会自动跳过，可放心高频运行
- 输出结构与青龙兼容，自动被面板捕获并发送通知

> ⚠️ 本脚本仅向官方接口 `copilot.tencent.com` 发送**你自己的** Bearer Token，不会上传到任何第三方。**Token 属于敏感凭证，请勿提交到公开仓库、也不要在公开场合泄露。** 登录态通常约 90 天有效，过期后需重新获取并更新环境变量。

---

## 获取 Token

1. 登录 WorkBuddy / CodeBuddy 桌面客户端。
2. 找到本机登录态文件：
   - macOS：`~/Library/Application Support/CodeBuddyExtension/Data/Public/auth/workbuddy-desktop.info`
   - Windows：`%APPDATA%\CodeBuddyExtension\Data\Public\auth\workbuddy-desktop.info`
   - Linux：`~/.config/CodeBuddyExtension/Data/Public/auth/workbuddy-desktop.info`
3. 用任意编辑器打开，取 `auth.accessToken` 字段的整串值（通常以 `eyJ` 开头）作为 Token。

---

## 环境变量

| 变量名 | 必填 | 说明 |
| --- | --- | --- |
| `WB_ACCESS_TOKEN` | 二选一 | 单个账号的 Token |
| `WB_ACCESS_TOKENS` | 二选一 | 多账号，逗号分隔；支持 `uid:token` 或纯 `token` |
| `WB_USER_ID` | 否 | 手动指定 X-User-Id；不填时自动从 JWT 解析 `sub` |
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

## 青龙面板部署步骤

1. **订阅 / 拉取脚本**
   - 方式 A（依赖管理）：面板「依赖管理」→ 添加 `requests`（Python）。
   - 方式 B（直接新建脚本）：面板「脚本管理」→ 新建 → 文件名 `workbuddy_checkin.py` → 粘贴本仓库 `workbuddy_checkin.py` 内容 → 保存。

2. **配置环境变量**
   面板「环境变量」→ 新建：
   - 名称 `WB_ACCESS_TOKEN`，值填你的 Token（单账号）；
   - 或名称 `WB_ACCESS_TOKENS`，值填多个 Token（多账号）。

3. **添加定时任务**
   面板「定时任务」→ 新建：
   - 命令：`task workbuddy_checkin.py` （或你的实际脚本路径）
   - 定时规则（cron）：建议每天 9 点附近，例如
     ```
     0 9 * * *
     ```
   - 可加随机偏移避免整点拥堵，例如 `13 8 * * *`（每天 08:13）。

4. **运行并查看通知**
   手动点「运行」测试一次；成功 / 失败都会打印到任务日志，并被青龙通知渠道（已配置的 Server 酱 / 钉钉 / 企业微信 / Telegram 等）推送。

---

## 本地调试（不依赖青龙）

```bash
pip install requests
export WB_ACCESS_TOKEN="eyJxxxx..."
python3 workbuddy_checkin.py
```

---

## 接口说明

| 用途 | 方法 | 路径 |
| --- | --- | --- |
| 签到状态 | GET | `https://copilot.tencent.com/v2/billing/meter/checkin-activity-status` |
| 执行签到 | POST | `https://copilot.tencent.com/v2/billing/meter/daily-checkin` |

---

## 常见问题

- **401 登录态失效**：Token 过期或被踢下线，重新从客户端获取并更新环境变量即可。
- **多账号失败**：检查 `WB_ACCESS_TOKENS` 是否用英文逗号分隔，Token 是否完整（别漏掉末尾的 `.` 段）。
- **获取失败 / 风控**：脚本已内置账号间 1 秒间隔；若仍频繁失败，调低运行频率（如每天 1 次）。

---

## 许可

MIT
