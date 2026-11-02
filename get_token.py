#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy Token 助手 —— 自动定位登录态文件并提取 Bearer Token

为什么需要它：
  WorkBuddy 客户端的登录态文件路径与结构都会随版本变化。
    - 旧版（≈5.8.2 及更早）：auth.accessToken 直接是 "eyJ..." 字符串，肉眼可复制
    - 新版（5.8.3+）：auth.accessToken 变成 {"$wbEncrypted": 1, "envelope": "..."}
      即由客户端用 AES-256-GCM 加密后落盘，字段里已经**不存在**明文 Token，
      所以「打开文件搜 auth.accessToken」的做法必然失效。

本脚本做三件事：
  1. 在 Windows / macOS / Linux 上自动找到登录态文件（含带时间戳的历史副本）
  2. 用**同一份文件里的** uid / 有效期等信息，把能用的情况直接提取出来
  3. 遇到加密格式时，明确告诉你「这是加密的、搜不到是正常的」，并给出可用的替代抓取方式

用法：
  python3 get_token.py                  # 自动查找并尝试提取
  python3 get_token.py --path FILE      # 指定文件
  python3 get_token.py --mask           # 提取时打码显示
  python3 get_token.py --check          # 校验环境变量里的 Token 是否仍有效
  python3 get_token.py --json           # 机器可读输出

退出码：
  0 成功拿到明文 Token
  2 未找到登录态文件
  3 文件存在但 Token 为加密格式（需要替代方案，见输出提示）
  4 --check 校验失败（Token 无效/过期）

注意：本脚本只读取本地文件、只用你自己的 Token 请求官方接口，不上传任何数据。
      它**不做解密**——客户端加密的密钥由客户端自行管理，绕过它既有风险也无必要，
      因为下面提示的替代方式更稳定。
"""

import base64
import json
import os
import sys

API_STATUS = "https://copilot.tencent.com/v2/billing/meter/checkin-activity-status"

# 各平台默认目录（相对用户主目录 / 环境变量）
CANDIDATES = {
    "win32": [r"%LOCALAPPDATA%\CodeBuddyExtension\Data\Public\auth"],
    "darwin": ["~/Library/Application Support/CodeBuddyExtension/Data/Public/auth"],
    "linux": ["~/.config/CodeBuddyExtension/Data/Public/auth"],
}

ENC_KEYS = ("$wbEncrypted", "envelope")


def log(msg=""):
    print(msg)


def expand(p):
    return os.path.expandvars(os.path.expanduser(p))


def auth_dirs():
    """返回所有可能存放登录态文件的目录（去重、保持顺序）。"""
    dirs = []
    env_dir = os.environ.get("WB_AUTH_DIR", "").strip()
    if env_dir:
        dirs.append(env_dir)
    for p in CANDIDATES.get(sys.platform, []) + CANDIDATES.get("linux", []):
        dirs.append(expand(p))
    out, seen = [], set()
    for d in dirs:
        d = os.path.abspath(d)
        if d not in seen and os.path.isdir(d):
            seen.add(d)
            out.append(d)
    return out


def auth_files():
    """列出候选文件，主文件优先，历史副本按修改时间倒序。"""
    found = []
    for d in auth_dirs():
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            if not n.endswith(".info"):
                continue
            if "corrupted" in n:
                continue
            found.append(os.path.join(d, n))
    main = [f for f in found if os.path.basename(f) == "workbuddy-desktop.info"]
    rest = [f for f in found if f not in main]
    rest.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    return main + rest


def is_encrypted(value):
    return isinstance(value, dict) and value.get("$wbEncrypted") == 1 and "envelope" in value


def find_plain_token(data):
    """在 JSON 里找明文 token：兼容各种字段名与层级。返回 (token, 路径) 或 (None, 命中说明)。"""
    # 常见位置，按优先级
    paths = [
        ("auth", "accessToken"),
        ("auth", "access_token"),
        ("auth", "token"),
        ("token", "accessToken"),
        ("accessToken",),
        ("access_token",),
    ]
    for path in paths:
        cur = data
        ok = True
        for k in path:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                ok = False
                break
        if not ok:
            continue
        if isinstance(cur, str) and cur.strip():
            return cur.strip(), ".".join(path)
        if is_encrypted(cur):
            return None, ".".join(path) + " (已加密)"
    return None, ""


def jwt_exp(token):
    """离线解析 JWT 的 exp，返回本地时间字符串；解析失败返回空串。"""
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        payload = json.loads(base64.urlsafe_b64decode(part).decode("utf-8", "ignore"))
        exp = payload.get("exp")
        if not exp:
            return "", None
        import datetime
        dt = datetime.datetime.fromtimestamp(int(exp))
        return dt.strftime("%Y-%m-%d %H:%M:%S"), int(exp)
    except Exception:
        return "", None


def is_backup(fp):
    base = os.path.basename(fp)
    return not (base == "workbuddy-desktop.info" or base.startswith("workbuddy-desktop.info."))


def describe_encrypted(value):
    """解析加密 envelope 的元信息（不解密），用于诊断输出。"""
    info = {"encrypted": True}
    env = value.get("envelope")
    if not isinstance(env, str):
        return info
    try:
        raw = env + "=" * (-len(env) % 4)
        meta = json.loads(base64.urlsafe_b64decode(raw).decode("utf-8", "ignore"))
        info["suite"] = meta.get("suite")
        info["keyId"] = meta.get("keyId")
        info["ciphertextLen"] = len(meta.get("ciphertext") or "")
    except Exception:
        info["envelopeLen"] = len(env)
    return info


def read_meta(data):
    """提取与 Token 无关但有用的元信息。"""
    meta = {}
    acct = data.get("account") or {}
    auth = data.get("auth") or {}
    meta["uid"] = acct.get("uid")
    meta["uin"] = acct.get("uin")
    exp = auth.get("expiresAt")
    if isinstance(exp, (int, float)) and exp > 0:
        # 客户端写的是毫秒时间戳
        ts = exp / 1000 if exp > 1e11 else exp
        import datetime
        meta["expiresAt"] = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    if auth.get("sessionState"):
        meta["sessionState"] = auth.get("sessionState")
    return meta


def load(fp):
    with open(fp, "rb") as f:
        raw = f.read()
    return json.loads(raw.decode("utf-8", "ignore")), len(raw)


def extract(fp, mask=False):
    data, size = load(fp)
    token, where = find_plain_token(data)
    meta = read_meta(data)
    return {
        "file": fp,
        "size": size,
        "token": token,
        "where": where,
        "encrypted": token is None and "已加密" in (where or ""),
        "meta": meta,
    }


def print_report(res):
    meta = res["meta"]
    kind = "历史副本" if is_backup(res["file"]) else "当前生效文件"
    log("📄 登录态文件：%s" % res["file"])
    log("   类型：%s | %d 字节" % (kind, res["size"]))
    if meta.get("uid"):
        log("   UID ：%s" % meta["uid"])
    if meta.get("uin"):
        log("   UIN ：%s" % meta["uin"])
    if meta.get("expiresAt"):
        log("   客户端记录的到期时间：%s" % meta["expiresAt"])
    log()

    if res["token"]:
        tok = res["token"]
        shown = tok[:12] + "…" + tok[-6:] if res["mask"] else tok
        exp_str, exp_ts = jwt_exp(tok)
        log("✅ 已找到明文 Token（字段：%s）" % res["where"])
        log("   %s" % shown)
        if exp_str:
            import time as _t
            left = int((exp_ts - _t.time()) / 86400)
            if exp_ts <= _t.time():
                log()
                log("⚠️ 该 Token 的 JWT 有效期已过（exp=%s），服务端会直接返回 401。" % exp_str)
                log("   请改用当前版本的抓取方式（见下方提示）。")
            else:
                log("   JWT 有效期至：%s（约剩 %d 天）" % (exp_str, left))
        if not res["mask"]:
            log()
            log("   青龙环境变量写法：")
            log('   export WB_ACCESS_TOKEN="%s"' % tok)
        log()
        log("   建议先验证再用：python3 get_token.py --check")
        return 0

    if res["encrypted"]:
        enc = describe_encrypted(get_path(res["file"], res["where"]))
        log("⚠️  字段 %s 是**加密对象**，不是字符串——所以你在文件里搜不到 auth.accessToken 的明文，这是正常的。" % res["where"])
        if enc.get("suite"):
            log("   suite=%s  keyId=%s  密文 %d 字节（客户端用 AES-256-GCM 加密后落盘）"
                % (enc.get("suite"), enc.get("keyId"), enc.get("ciphertextLen", 0)))
        log()
        log("   Token 本身仍然可用，只是不再能「打开文件复制」。请用下面任一方式取得：")
        log()
        log("   ① 浏览器抓取（最稳，推荐）")
        log("      1. 浏览器打开 https://www.workbuddy.cn 并登录")
        log("      2. F12 → Network → 过滤 Fetch/XHR → 点任意一个请求")
        log("      3. 在 Request Headers 里复制 Authorization 中 Bearer 后面那一串（eyJ 开头）")
        log()
        log("   ② 客户端内置页面抓取")
        log("      在 WorkBuddy 客户端里打开「成长空间/签到」页面，F12 → Network 同样取 Authorization")
        log()
        log("   ③ 尝试历史副本（成功率低，仅作兜底）")
        log("      ≤5.8.2 时期的 .info 备份里可能还是明文，本脚本已自动扫描同目录的历史副本。")
        log("      但注意：这类旧 Token 大多已被服务端吊销，取到后务必用 --check 验证。")
        log()
        log("   说明：本脚本不解密该字段。密钥由客户端管理，绕过它既有风险也没必要——")
        log("         上面两种抓取方式拿到的 Token 与加密文件里的完全等价。")
        return 3

    log("❌ 文件中没有找到可用 Token（可能尚未登录，或客户端改用了其它存储结构）")
    log("   请先在 WorkBuddy 客户端完成登录，再重新运行本脚本。")
    return 2


def get_path(fp, where):
    data, _ = load(fp)
    cur = data
    for k in (where or "").replace(" (已加密)", "").split("."):
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return {}
    return cur if isinstance(cur, dict) else {}


def do_check(token, uid=""):
    """用 Token 调一次状态接口，验证是否仍有效。"""
    import urllib.error
    import urllib.request

    body = b"{}"
    req = urllib.request.Request(API_STATUS, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    req.add_header("Authorization", "Bearer " + token)
    if uid:
        req.add_header("X-User-Id", uid)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            payload = json.loads(r.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            log("❌ Token 无效（HTTP 401）")
            log("   注意：JWT 里的 exp 没过期也不代表可用——服务端会主动吊销旧登录态快照。")
            log("   请重新获取 Token 后更新环境变量。")
            return 4
        log("⚠️  接口返回 HTTP %s，无法判定（不是 Token 的问题）" % e.code)
        return 4
    except Exception as e:
        log("⚠️  网络异常，无法完成校验：%s" % e)
        return 4

    if payload.get("code") != 0:
        log("❌ 校验失败：code=%s msg=%s" % (payload.get("code"), payload.get("msg", "")))
        return 4
    d = payload.get("data") or {}
    log("✅ Token 有效")
    log("   连续签到：%s 天" % d.get("streak_days", 0))
    log("   今日已签：%s" % ("是" if d.get("today_checked_in") else "否"))
    if d.get("total_credits") is not None:
        log("   累计积分：%s" % d.get("total_credits"))
    return 0


def main():
    args = sys.argv[1:]
    mask = "--mask" in args
    as_json = "--json" in args
    do_check_flag = "--check" in args

    path_arg = ""
    if "--path" in args:
        i = args.index("--path")
        if i + 1 < len(args):
            path_arg = args[i + 1]

    # --check：校验现有环境变量里的 Token
    if do_check_flag:
        tok = (os.environ.get("WB_ACCESS_TOKEN", "") or "").strip()
        uid = (os.environ.get("WB_USER_ID", "") or "").strip()
        if not tok:
            log("❌ 未设置 WB_ACCESS_TOKEN，无法校验")
            return 2
        return do_check(tok, uid)

    files = [path_arg] if path_arg else auth_files()
    if not files:
        if as_json:
            print(json.dumps({"error": "auth_file_not_found",
                              "searched": auth_dirs()}, ensure_ascii=False))
            return 2
        log("❌ 没有找到 WorkBuddy 登录态文件")
        log("   已搜索目录：")
        for d in auth_dirs() or ["(无可访问目录)"]:
            log("     - %s" % d)
        log()
        log("   如果装在自定义路径，请这样指定：")
        log("     python3 get_token.py --path /你的/路径/workbuddy-desktop.info")
        log("   （可用环境变量 WB_AUTH_DIR 指定目录）")
        return 2

    # 依次尝试：主文件 → 历史副本
    results = []
    for fp in files:
        try:
            res = extract(fp, mask)
        except Exception as e:
            results.append({"file": fp, "error": str(e)})
            continue
        res["mask"] = mask
        results.append(res)
        if res.get("token"):
            break  # 找到明文就不再往下试

    if as_json:
        out = []
        for r in results:
            r = dict(r)
            if r.get("token") and mask:
                r["token"] = r["token"][:10] + "***"
            out.append(r)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if any(r.get("token") for r in results) else 3

    # 优先展示成功的那一份；否则展示第一份有效解析
    chosen = next((r for r in results if r.get("token")), None) or \
             next((r for r in results if "error" not in r), None)
    if not chosen:
        log("❌ 无法解析任何登录态文件")
        for r in results:
            log("   %s -> %s" % (r["file"], r.get("error")))
        return 2

    code = print_report(chosen)

    if len(results) > 1 and not chosen.get("token"):
        log()
        log("ℹ️  共检查了 %d 个候选文件（含历史副本），结果如上。" % len(results))
    return code


if __name__ == "__main__":
    sys.exit(main())
