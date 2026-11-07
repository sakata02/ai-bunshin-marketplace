#!/usr/bin/env python3
"""自動実行（claude -p）の囲い：守るパスの一覧（protected_paths.json）から、--settings に渡す JSON を作る。

使い方：
  python3 sandbox_settings.py --home <本人のフォルダの絶対パス> --plugin-root <プラグインの元の絶対パス>
        [--plugin-root <もう1つ>] [--config <config.json>] [--user-home <ホーム>] [--paths-file <一覧>]
        [--calendar-url-env <環境変数の名前>]
  → 標準出力に JSON を1行（そのまま claude -p --settings "$(…)" に渡せる）
  → 作れないときは、標準エラーに日本語1行・終了コード1（呼ぶ側は Python を許さず、今の許可に退く。T119 S05）

決まり（T119 S01〜S10。決定一覧.md）：
- 守る先は一覧から denyWrite（Bash に OS）と permissions.deny の Edit(...)（道具）の両方に作る（T097 §3-2）。
  日本語のパスは NFC と NFD の両方を入れる（Mac のファイル名の形。T097 X13）。実体のパス（realpath）も入れる
- tasks.json は書けるまま（S02）。一覧がそれを含むと作らずに止める（must_stay_writable）。本人の scripts/ は丸ごと守る
  （S04。囲いの中の update_dashboard.py は失敗のログを書けないが、write_error_log が例外を飲むので止まらない）
- マーケットプレイスは、利用者の known_marketplaces.json の source が directory のものの installLocation を
  丸ごと守る（S12）。読めない・無い・形が違うときは足さずに作る
- 通信は止め、カレンダーの取得先の host だけ通す（S02・S09）。URL は環境変数で受け取り、host だけを取り出す。
  URL そのものは出力・エラー・ログに出さない。config に calendar（ics）が無い人は全部止める
- 許可の一覧（permissions.allow）・読み取りの守り（denyRead）は作らない（S08・S10）
"""
import argparse
import ipaddress
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
DEFAULT_PATHS_FILE = HERE / "protected_paths.json"
DEFAULT_URL_ENV = "AI_BUNSHIN_CALENDAR_URL"
BASES = ("home", "user_home", "plugin_root")
BAD_PATH_CHARS = set("*?[]{}()\n\r\x00")   # 権限の規則・囲いのパスで別の意味になる文字
HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")


class Fail(Exception):
    """作れない理由（日本語1行。URL・秘密を入れない）"""


def forms(p):
    """パスの形：そのまま・realpath、それぞれの NFC・NFD。重複なし、順序は決まった形"""
    base = [str(p)]
    real = os.path.realpath(str(p))
    if real not in base:
        base.append(real)
    out = []
    for s in base:
        for f in ("NFC", "NFD"):
            v = unicodedata.normalize(f, s)
            if v not in out:
                out.append(v)
    return out


def canon(p):
    return unicodedata.normalize("NFC", os.path.realpath(str(p)))


def is_inside(child, parent):
    return child == parent or child.startswith(parent.rstrip("/") + "/")


def load_json(path, what):
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise Fail("%s が見つかりません" % what)
    except Exception:
        raise Fail("%s を読めません（JSON の形が違います）" % what)
    if not isinstance(data, dict):
        raise Fail("%s を読めません（形が違います）" % what)
    return data


def need_abs_dir(value, what):
    if not value or not os.path.isabs(value):
        raise Fail("%s は絶対パスで渡してください" % what)
    p = Path(os.path.normpath(value))
    if str(p) == "/":
        raise Fail("%s が / です" % what)
    if not p.is_dir():
        raise Fail("%s のフォルダが見つかりません" % what)
    for ch in str(p):
        if ch in BAD_PATH_CHARS:
            raise Fail("%s に使えない文字が含まれています" % what)
    return p


def calendar_host(cfg, url):
    """config に calendar（ics）があり、URL が https の普通のドメインのときだけ host を返す。それ以外は None（全部止める）"""
    cal = cfg.get("calendar")
    if not isinstance(cal, dict) or cal.get("type") != "ics" or not url:
        return None
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    if parts.scheme not in ("https", "http", "webcal") or not host or "." not in host or not HOST_RE.match(host):
        return None
    try:
        ipaddress.ip_address(host)
        return None   # IP アドレスは通さない
    except ValueError:
        return host


def add_dir_repos(cfg, home):
    """daily_cycle.sh の ADD_DIRS と同じ選び方：config の dev.projects で、本人のフォルダの外にある実在の絶対パス"""
    out = []
    dev = cfg.get("dev")
    projects = dev.get("projects") if isinstance(dev, dict) else None
    for p in projects if isinstance(projects, list) else []:
        if not isinstance(p, dict) or not isinstance(p.get("path"), str) or not p["path"]:
            continue
        d = Path(os.path.expanduser(p["path"]))
        if d.is_absolute() and d.exists() and not is_inside(canon(d), canon(home)):   # 本人のフォルダの中は対象外
            if d not in out:
                out.append(d)
    return out


def marketplace_roots(user_home, spec):
    """known_marketplaces.json の source が directory のものの installLocation（S12）。読めない・無い・形が違うものは足さない"""
    m = spec.get("marketplaces")
    if not isinstance(m, dict) or not isinstance(m.get("file"), str) or m.get("base") != "user_home" \
            or not isinstance(m.get("source_kind"), str):
        raise Fail("守るパスの一覧の marketplaces の書き方が違います")
    out = []
    try:
        with open(Path(user_home) / m["file"], encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception:
        return out
    if not isinstance(data, dict):
        return out
    for name, ent in data.items():
        if not isinstance(ent, dict) or not isinstance(ent.get("source"), dict) or ent["source"].get("source") != m["source_kind"]:
            continue
        loc = ent.get("installLocation")
        if not isinstance(loc, str) or not os.path.isabs(loc) or any(ch in BAD_PATH_CHARS for ch in loc):
            continue
        p = Path(os.path.normpath(loc))
        if str(p) != "/" and p.is_dir():
            out.append((str(name), p))
    return out


def build_settings(home, plugin_roots, config_path, user_home, calendar_url, paths_file):
    home = need_abs_dir(home, "本人のフォルダ")
    roots = [need_abs_dir(r, "プラグインの元") for r in plugin_roots]
    if not roots:
        raise Fail("プラグインの元が渡されていません")
    user_home = need_abs_dir(user_home, "ユーザーのホーム")
    cfg = load_json(config_path, "config.json")
    spec = load_json(paths_file, "守るパスの一覧（protected_paths.json）")

    entries = spec.get("entries")
    if not isinstance(entries, list) or not entries:
        raise Fail("守るパスの一覧が空です")
    # (id, 実際のパス, 種類)
    targets = []
    for e in entries:
        if not isinstance(e, dict) or e.get("base") not in BASES or not isinstance(e.get("path"), str) \
                or e.get("kind") not in ("dir", "file") or not isinstance(e.get("id"), str):
            raise Fail("守るパスの一覧の書き方が違います")
        rel = e["path"]
        if os.path.isabs(rel) or ".." in Path(rel).parts:
            raise Fail("守るパスの一覧の %s が相対パスではありません" % e["id"])
        bases = {"home": [home], "user_home": [user_home], "plugin_root": roots}[e["base"]]
        for b in bases:
            targets.append((e["id"], Path(os.path.normpath(str(b / rel))), e["kind"]))
    for i, (_mname, mpath) in enumerate(marketplace_roots(user_home, spec)):
        targets.append(("S12-marketplace-%d" % (i + 1), mpath, "dir"))
    git_rel = spec.get("add_dir_git")
    if not isinstance(git_rel, list):
        raise Fail("守るパスの一覧に add_dir_git がありません")
    for d in add_dir_repos(cfg, home):
        for r in git_rel:   # ファイルかフォルダかは、名前でなく一覧の kind で決める
            if not isinstance(r, dict) or not isinstance(r.get("path"), str) or r.get("kind") not in ("dir", "file") \
                    or os.path.isabs(r["path"]) or ".." in Path(r["path"]).parts:
                raise Fail("守るパスの一覧の add_dir_git の書き方が違います")
            targets.append(("X12-" + d.name, Path(os.path.normpath(str(d / r["path"]))), r["kind"]))

    # 書けるままにする先（tasks.json・logs）を含む守り方は作らない
    stay = spec.get("must_stay_writable")
    if not isinstance(stay, list):
        raise Fail("守るパスの一覧に must_stay_writable がありません")
    for s in stay:
        if not isinstance(s, dict) or s.get("base") not in BASES or not isinstance(s.get("path"), str):
            raise Fail("守るパスの一覧の must_stay_writable の書き方が違います")
        sb = {"home": [home], "user_home": [user_home], "plugin_root": roots}[s["base"]]
        for b in sb:
            w = canon(b / s["path"])
            for tid, tp, _k in targets:
                if is_inside(w, canon(tp)):
                    raise Fail("守る先 %s が、書けるままにする先（%s）を含んでいます" % (tid, s["path"]))

    deny_write, deny_edit = [], []
    for tid, tp, kind in targets:
        for v in forms(tp):
            for ch in v:
                if ch in BAD_PATH_CHARS:
                    raise Fail("守る先 %s のパスに使えない文字が含まれています" % tid)
            if v not in deny_write:
                deny_write.append(v)               # サンドボックスのパスは / で始まる絶対パス
            rule = "Edit(/%s%s)" % (v, "/**" if kind == "dir" else "")   # 権限の規則は // で始まる絶対パス
            if rule not in deny_edit:
                deny_edit.append(rule)

    host = calendar_host(cfg, calendar_url)
    return {
        "sandbox": {
            "enabled": True,
            "failIfUnavailable": True,
            "allowUnsandboxedCommands": False,
            "autoAllowBashIfSandboxed": False,
            "excludedCommands": [],
            "filesystem": {"denyWrite": deny_write},
            "network": {"allowedDomains": [host] if host else []},
        },
        "permissions": {"deny": deny_edit},
    }


class JaParser(argparse.ArgumentParser):
    def error(self, message):   # 既定は終了コード2・英語。呼ぶ側が見るのは「1」なので日本語1行に揃える
        raise Fail("引数が正しくありません（--home と --plugin-root が要ります）")


def main(argv=None):
    ap = JaParser(add_help=False)
    ap.add_argument("--home", required=True)
    ap.add_argument("--plugin-root", action="append", default=[])
    ap.add_argument("--config")
    ap.add_argument("--user-home", default=os.path.expanduser("~"))
    ap.add_argument("--paths-file", default=str(DEFAULT_PATHS_FILE))
    ap.add_argument("--calendar-url-env", default=DEFAULT_URL_ENV)
    try:
        a = ap.parse_args(argv)
        config = a.config or str(Path(a.home) / "設定" / "config.json")
        url = os.environ.get(a.calendar_url_env, "")
        out = build_settings(a.home, a.plugin_root, config, a.user_home, url, a.paths_file)
        sys.stdout.write(json.dumps(out, ensure_ascii=True, separators=(",", ":")) + "\n")
        return 0
    except Fail as e:
        msg = str(e)
    except Exception as e:   # str(e) は使わない（URL・パスが入ることがある）
        msg = "囲いの設定を作れませんでした（%s）" % type(e).__name__
    sys.stderr.buffer.write(("sandbox_settings: " + msg + "\n").encode("utf-8"))
    return 1


if __name__ == "__main__":
    sys.exit(main())
