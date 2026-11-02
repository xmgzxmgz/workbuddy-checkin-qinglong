#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy 每日自动签到（青龙面板版）

功能：
  - 调用官方签到接口，幂等（今日已签则跳过）
  - 输出完整签到状态面板：连续天数、下一奖励节点、本月打卡日历、积分
  - 支持多账号：用 "," 分隔多个 Token
  - Token 不写死在脚本里，全部从环境变量读取
  - 失败自动重试（网络抖动 / 5xx），输出结构与青龙面板兼容

环境变量：
  WB_ACCESS_TOKEN   单个账号的 Bearer Token（必填其一）
  WB_ACCESS_TOKENS  多个账号 Token，逗号分隔（必填其一）
  WB_USER_ID        可选，X-User-Id 头；不填则尝试从 JWT 解析 sub
  WB_PROXY          可选，代理地址，如 http://127.0.0.1:7897
  WB_RETRY          可选，单账号失败重试次数，默认 2（共最多 3 次）
  QINGLONG_NOTIFY   可选，1/true 时打印青龙通知标记（默认开启，青龙自动捕获 stdout）

命令行：
  python3 workbuddy_checkin.py            # 正常签到
  python3 workbuddy_checkin.py --status   # 只查状态，不签到（只读，安全）
  python3 workbuddy_checkin.py --json     # 机器可读输出

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
RETRY = int(os.environ.get("WB_RETRY", "2") or "2")
PROXY = os.environ.get("WB_PROXY", "").strip()
PROXIES = {"http": PROXY, "https": PROXY} if PROXY else {"http": None, "https": None}

ARGS = sys.argv[1:]
STATUS_ONLY = "--status" in ARGS or "-s" in ARGS
AS_JSON = "--json" in ARGS


def log(msg=""):
    """统一输出：青龙会捕获 stdout 作为任务日志 / 通知内容。"""
    if not AS_JSON:
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
        log("   不知道 Token 在哪？运行 python3 get_token.py 会自动查找并给出抓取指引")
        return []
    fixed = []
    for uid, tok in tokens:
        if not uid:
            uid = decode_jwt_sub(tok)
        fixed.append((uid, tok))
    return fixed


def _request(method, url, token, uid, body="{}"):
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": "Bearer " + token,
        "X-User-Id": uid or "",
        "User-Agent": "Mozilla/5.0",
    }
    if HAVE_REQUESTS:
        resp = requests.request(method, url, headers=headers, data=body, timeout=20, proxies=PROXIES)
        return resp.status_code, resp.text
    req = urllib.request.Request(url, data=body.encode("utf-8"), headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")


def http_post(url, token, uid, body="{}"):
    """带重试的 POST：网络异常与 5xx 会退避重试，4xx 直接返回（不重试）。"""
    last = None
    for attempt in range(RETRY + 1):
        try:
            code, text = _request("POST", url, token, uid, body)
            if code >= 500 and attempt < RETRY:
                last = (code, text)
                time.sleep(2 ** attempt)
                continue
            return code, text
        except Exception as e:
            last = (0, str(e))
            if attempt < RETRY:
                time.sleep(2 ** attempt)
                continue
            return last
    return last if last else (0, "unknown")


def fmt_ts(ts):
    try:
        ts = int(ts)
        if ts > 1e11:
            ts //= 1000
        return time.strftime("%Y-%m-%d", time.localtime(ts))
    except Exception:
        return ""


def parse_status(data):
    """把接口返回的 data 归一化成展示用的 dict。

    字段来源：客户端 checkin-activity-status 的解析实现
      active / today_checked_in / streak_days / daily_credit / today_credit
      is_streak_day / next_streak_day / streak_bonus_days / streak_bonus_credit
      checkin_dates / total_credits / start_time / end_time
      activity_name / claim_button_text / action_button
    """
    d = data or {}
    dates = d.get("checkin_dates") or []
    # 兼容 ["2026-11-01", ...] 与 [{"date": ...}, ...] 两种可能
    norm = []
    for x in dates:
        if isinstance(x, str):
            norm.append(x)
        elif isinstance(x, dict):
            v = x.get("date") or x.get("day") or x.get("ds")
            if v:
                norm.append(str(v))
    bonus = d.get("streak_bonus_days")
    if isinstance(bonus, list):
        bonus_days = [int(b) for b in bonus if str(b).isdigit()]
    elif isinstance(bonus, (int, float)):
        bonus_days = [int(bonus)]
    else:
        bonus_days = []
    return {
        "active": bool(d.get("active")),
        "today_checked_in": bool(d.get("today_checked_in")),
        "streak_days": int(d.get("streak_days") or 0),
        "next_streak_day": int(d.get("next_streak_day") or 0),
        "streak_bonus_days": bonus_days,
        "streak_bonus_credit": d.get("streak_bonus_credit"),
        "daily_credit": d.get("daily_credit"),
        "today_credit": d.get("today_credit"),
        "total_credits": d.get("total_credits"),
        "checkin_dates": sorted(norm),
        "start_time": fmt_ts(d.get("start_time")),
        "end_time": fmt_ts(d.get("end_time")),
        "activity_name": d.get("activity_name") or "",
        "claim_button_text": d.get("claim_button_text") or "",
        "action_button": d.get("action_button") or "",
    }


def render_panel(st):
    """把归一化状态渲染成可读面板。"""
    lines = []
    if st.get("activity_name"):
        lines.append("📅 活动：%s" % st["activity_name"])
    if st.get("start_time") or st.get("end_time"):
        lines.append("   周期：%s ~ %s" % (st.get("start_time") or "?", st.get("end_time") or "?"))

    # 连续天数与进度
    streak = st["streak_days"]
    if streak > 0:
        lines.append("🔥 当前连续签到：%d 天" % streak)
    else:
        lines.append("🔥 当前连续签到：0 天（今天签到即可开新一连）")

    bonus = st["streak_bonus_days"]
    if bonus:
        reached = [b for b in bonus if b <= streak]
        nxt = next((b for b in bonus if b > streak), None)
        nodes = " / ".join("%d天" % b for b in bonus)
        seg = "🎯 奖励节点：%s" % nodes
        if nxt:
            if reached:
                seg += "　已达 %s，距 %d 天还差 %d 天" % (
                    "、".join("%d天" % b for b in reached), nxt, nxt - streak)
            else:
                seg += "　距 %d 天还差 %d 天" % (nxt, nxt - streak)
        else:
            seg += "　已全部达成"
        lines.append(seg)
    elif st["next_streak_day"]:
        lines.append("🎯 下一奖励节点：%d 天（还差 %d 天）"
                     % (st["next_streak_day"], max(0, st["next_streak_day"] - streak)))

    # 今日状态
    if st["today_checked_in"]:
        today = "✅ 今日已打卡"
        if st.get("today_credit") not in (None, 0):
            today += "（今日 +%s）" % st["today_credit"]
    else:
        today = "⏳ 今日未打卡"
    daily = st.get("daily_credit")
    if daily not in (None, 0) and not (st["today_checked_in"] and st.get("today_credit") == daily):
        today += "　每日基础 +%s" % daily
    lines.append(today)

    # 日历
    dates = st["checkin_dates"]
    if dates:
        lines.append("🗓️ 本期已打卡 %d 天" % len(dates))
        # 太长则只展示最后 14 条，避免刷屏
        show = dates[-14:]
        prefix = "… " if len(dates) > len(show) else ""
        lines.append("   %s%s" % (prefix, " ".join(x[-5:] if len(x) > 5 else x for x in show)))

    if st.get("total_credits") is not None:
        lines.append("💰 累计积分：%s" % st["total_credits"])

    # 网页端专属入口提示（客户端不提供对应接口）
    web_actions = [x for x in (st.get("action_button"), st.get("claim_button_text")) if x]
    if web_actions:
        lines.append("🔗 网页端还有入口：%s（这类操作需在网页端完成）"
                     % "、".join(web_actions))
    return lines


def fetch_status(uid, token):
    """查询状态，返回 (ok, status_dict, msg)。"""
    code, text = http_post(STATUS_EP, token, uid)
    if code == 401:
        return False, None, "登录态失效(401)：请在 WorkBuddy 客户端重新登录后更新 Token（可用 get_token.py 辅助获取）"
    try:
        payload = json.loads(text)
    except Exception:
        return False, None, "状态接口返回异常(%s): %s" % (code, (text or "")[:120])
    if payload.get("code") != 0:
        return False, None, "状态查询失败 code=%s msg=%s" % (payload.get("code"), payload.get("msg", ""))
    return True, parse_status(payload.get("data")), ""


def do_checkin(uid, token, st):
    """执行签到，返回 (成功, 消息)。"""
    ck_code, ck_text = http_post(CHECKIN_EP, token, uid)
    if ck_code == 401:
        return False, "登录态失效(401)：请在 WorkBuddy 客户端重新登录后更新 Token"
    try:
        ck = json.loads(ck_text)
    except Exception:
        return False, "签到接口返回异常(%s): %s" % (ck_code, (ck_text or "")[:120])

    code = ck.get("code")
    if code == 0:
        # 注意：daily-checkin 的 credit / streak_days 在响应**顶层**，
        # 早期版本从 data 里取，导致积分恒显示 0。
        d = ck.get("data") if isinstance(ck.get("data"), dict) else {}
        credit = ck.get("credit", d.get("credit", 0))
        streak = ck.get("streak_days", d.get("streak_days", (st or {}).get("streak_days", 0)))
        is_streak = ck.get("is_streak_day", d.get("is_streak_day", False))
        msg = "签到成功 +%s 积分（连续 %s 天）" % (credit, streak)
        if is_streak:
            msg += " 🎉 命中连续奖励节点"
        return True, msg
    if code == 10001 or "已签" in (ck.get("msg") or ""):
        return True, "今日已签到（接口确认）"
    return False, "签到失败 code=%s msg=%s" % (code, ck.get("msg", ""))


def handle_one(uid, token):
    """处理单个账号，返回 (成功, [输出行])。"""
    lines = []
    ok, st, msg = fetch_status(uid, token)
    if not ok:
        return False, [msg]

    lines.extend(render_panel(st))

    if STATUS_ONLY:
        return True, lines

    if st["today_checked_in"]:
        lines.append("🎉 今日已签到，跳过（幂等，无副作用）")
        return True, lines
    if not st["active"]:
        lines.append("⚠️ 活动当前未开启（active=false），本次不执行签到")
        return True, lines

    done, cmsg = do_checkin(uid, token, st)
    lines.append(("✅ " if done else "❌ ") + cmsg)
    if done and not st["today_checked_in"]:
        lines.append("   提示：签到积分与连续天数以接口返回为准，稍后可在客户端查看")
    return done, lines


def main():
    accounts = get_accounts()
    if not accounts:
        sys.exit(2)

    mode = "状态查询" if STATUS_ONLY else "自动签到"
    log("🔰 WorkBuddy %s开始，共 %d 个账号" % (mode, len(accounts)))

    results = []
    ok, fail = 0, 0
    for idx, (uid, token) in enumerate(accounts, 1):
        tag = (uid[:8] + "…") if uid else "账号%d" % idx
        try:
            success, lines = handle_one(uid, token)
        except Exception as e:
            success, lines = False, ["异常: %s" % e]
        if success:
            ok += 1
        else:
            fail += 1
        results.append({"account": tag, "uid": uid, "ok": success,
                        "lines": lines})
        log("")
        log("%s [%s]" % ("✅" if success else "❌", tag))
        for ln in lines:
            log("   " + ln)
        if idx < len(accounts):
            time.sleep(1)  # 多账号之间稍作间隔，避免触发风控

    if AS_JSON:
        print(json.dumps({"ok": ok, "fail": fail, "total": len(accounts),
                          "accounts": results}, ensure_ascii=False, indent=2))
    log("")
    log("🏁 完成：成功 %d / 失败 %d / 共 %d" % (ok, fail, len(accounts)))
    if fail > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
