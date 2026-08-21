#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy 每日自动签到（青龙面板版）

功能：
  - 调用官方签到接口，幂等（今日已签则跳过）
  - 支持多账号：用 "," 分隔多个 Token
  - Token 不写死在脚本里，全部从环境变量读取
  - 输出结构与青龙面板兼容（直接 print 即可被青龙捕获并通知）

环境变量：
  WB_ACCESS_TOKEN   单个账号的 Bearer Token（必填其一）
  WB_ACCESS_TOKENS  多个账号 Token，逗号分隔（必填其一）
  WB_USER_ID        可选，X-User-Id 头；不填则尝试从 JWT 解析 sub
  QINGLONG_NOTIFY   可选，1/true 时打印青龙通知标记（默认开启，青龙自动捕获 stdout）

本地调试（不依赖青龙）：
  WB_ACCESS_TOKEN=xxxx python3 workbuddy_checkin.py
"""

import os
import sys
import json
import time
import base64

# 优先用 requests（青龙自带），否则回退到标准库 urllib
try:
    import requests
    HAVE_REQUESTS = True
except ImportError:
    import urllib.request
    import urllib.error
    HAVE_REQUESTS = False

API_BASE = "https://copilot.tencent.com/v2/billing/meter"
STATUS_EP = API_BASE + "/checkin-activity-status"
CHECKIN_EP = API_BASE + "/daily-checkin"

NOTIFY = str(os.environ.get("QINGLONG_NOTIFY", "1")).lower() in ("1", "true", "yes")


def log(msg):
    """统一输出：青龙会捕获 stdout 作为任务日志 / 通知内容。"""
    print(msg)


def decode_jwt_sub(token):
    """无需密钥，仅 base64url 解码 payload 取 sub（Uid）。失败返回空串。"""
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        payload = json.loads(base64.urlsafe_b64decode(part).decode("utf-8", "ignore"))
        return payload.get("sub") or ""
    except Exception:
        return ""


def get_accounts():
    """从环境变量读取账号列表，返回 [(uid, token), ...]。"""
    tokens_raw = os.environ.get("WB_ACCESS_TOKENS", "").strip()
    single = os.environ.get("WB_ACCESS_TOKEN", "").strip()
    tokens = []
    if tokens_raw:
        # 支持 "uid:token" 或纯 "token"，逗号分隔
        for item in tokens_raw.split(","):
            item = item.strip()
            if not item:
                continue
            if ":" in item and len(item.split(":")) == 2 and not item.startswith("eyJ"):
                uid, tok = item.split(":", 1)
                tokens.append((uid.strip(), tok.strip()))
            else:
                tokens.append(("", item))
    if single:
        tokens.append(("", single.strip()))
    if not tokens:
        log("❌ 未检测到 Token：请设置环境变量 WB_ACCESS_TOKEN 或 WB_ACCESS_TOKENS")
        return []
    # 补全 uid
    fixed = []
    for uid, tok in tokens:
        if not uid:
            uid = decode_jwt_sub(tok)
        fixed.append((uid, tok))
    return fixed


def http_post(url, token, uid, body="{}"):
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": "Bearer " + token,
        "X-User-Id": uid or "",
    }
    if HAVE_REQUESTS:
        resp = requests.post(url, headers=headers, data=body, timeout=20)
        return resp.status_code, resp.text
    else:
        req = urllib.request.Request(url, data=body.encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, r.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "ignore")


def http_get(url, token, uid):
    headers = {
        "Accept": "application/json",
        "Authorization": "Bearer " + token,
        "X-User-Id": uid or "",
    }
    if HAVE_REQUESTS:
        resp = requests.get(url, headers=headers, timeout=20)
        return resp.status_code, resp.text
    else:
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, r.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "ignore")


def checkin_one(uid, token):
    """对单个账号执行签到，返回 (成功: bool, 消息: str)。"""
    # 1) 查状态（注意：官方接口只接受 POST，GET 会返回 404 page not found）
    st_code, st_text = http_post(STATUS_EP, token, uid)
    if st_code == 401:
        return False, "登录态失效(401)，请在 WorkBuddy 客户端重新登录后更新 Token"
    try:
        st = json.loads(st_text)
    except Exception:
        return False, f"状态接口返回异常({st_code}): {st_text[:120]}"
    if st.get("code") != 0:
        return False, f"状态查询失败 code={st.get('code')} msg={st.get('msg','')}"
    data = st.get("data") or {}
    if data.get("today_checked_in"):
        return True, f"今日已签到（连续 {data.get('streak_days', 0)} 天）"
    # 2) 执行签到
    ck_code, ck_text = http_post(CHECKIN_EP, token, uid)
    if ck_code == 401:
        return False, "登录态失效(401)，请在 WorkBuddy 客户端重新登录后更新 Token"
    try:
        ck = json.loads(ck_text)
    except Exception:
        return False, f"签到接口返回异常({ck_code}): {ck_text[:120]}"
    code = ck.get("code")
    if code == 0:
        d = ck.get("data") or {}
        credit = d.get("credit", 0)
        streak = d.get("streak_days", 0)
        return True, f"签到成功 +{credit} 积分（连续 {streak} 天）"
    if code == 10001 or "已签" in (ck.get("msg") or ""):
        return True, "今日已签到（接口确认）"
    return False, f"签到失败 code={code} msg={ck.get('msg','')}"


def main():
    accounts = get_accounts()
    if not accounts:
        sys.exit(2)
    log(f"🔰 WorkBuddy 自动签到开始，共 {len(accounts)} 个账号")
    ok, fail = 0, 0
    for idx, (uid, token) in enumerate(accounts, 1):
        tag = (uid[:8] + "…") if uid else f"账号{idx}"
        try:
            success, msg = checkin_one(uid, token)
        except Exception as e:
            success, msg = False, f"异常: {e}"
        if success:
            ok += 1
            log(f"✅ [{tag}] {msg}")
        else:
            fail += 1
            log(f"❌ [{tag}] {msg}")
        time.sleep(1)  # 多账号之间稍作间隔，避免触发风控
    log(f"🏁 完成：成功 {ok} / 失败 {fail} / 共 {len(accounts)}")
    if fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
