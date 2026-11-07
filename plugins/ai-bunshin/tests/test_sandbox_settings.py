"""自動実行の囲い（sandbox_settings.py・protected_paths.json）のテスト。T119 G2。
実行：python3 tests/test_sandbox_settings.py（失敗があれば終了コード1）
- 期待する守り先は、一覧（protected_paths.json）からでなく、このファイルに決定（S02・S04）どおりに書く。
  一覧から何かを外す・足りない形（NFD など）にする・書けるままの先を止める、と落ちる
- claude も security（キーチェーン）も動かさない。URL は作り物（SECRET を含む）。本物の本人のフォルダは読むだけ"""
import json
import os
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "sandbox_settings.py"
PATHS_JSON = HERE.parent / "scripts" / "protected_paths.json"
REAL_HOME = Path("/Users/rd/workspace/AI坂田")

SECRET = "SECRETTOKEN-9f3a1c"
CAL_URL = "https://calendar.example.org/calendar/ical/a%40b.c/private-" + SECRET + "/basic.ics"
URL_ENV = "TEST_CAL_URL"

fail = 0
count = 0


def check(cond, msg):
    global fail, count
    count += 1
    if not cond:
        fail += 1
        print("FAIL", msg)


def nfc(s):
    return unicodedata.normalize("NFC", s)


def nfd(s):
    return unicodedata.normalize("NFD", s)


def mkfixture():
    """本人のフォルダ・プラグインの元・ユーザーのホーム・外のリポジトリの作り物"""
    root = Path(os.path.realpath(tempfile.mkdtemp(prefix="sbxtest_")))
    home = root / "本人"
    for d in ["設定", "03_インプット", ".claude/rules", "scripts/auto/logs", "00_タスク管理/data", "04_ナレッジ", "05_開発/x"]:
        (home / d).mkdir(parents=True)
    (home / "00_タスク管理/data/tasks.json").write_text("{}", encoding="utf-8")
    (home / "CLAUDE.md").write_text("x", encoding="utf-8")
    (home / "scripts/auto/run.sh").write_text("#!/bin/zsh\n", encoding="utf-8")
    (home / "scripts/auto/daily_cycle.sh").write_text("#!/bin/zsh\n", encoding="utf-8")
    plug = root / "marketplace" / "plugins" / "ai-bunshin"
    (plug / "scripts").mkdir(parents=True)
    uh = root / "userhome"
    (uh / ".claude/plugins").mkdir(parents=True)
    repo = root / "repos" / "hp"
    (repo / ".git/hooks").mkdir(parents=True)
    (repo / ".git/config").write_text("", encoding="utf-8")
    cfg = {
        "owner": "テスト",
        "calendar": {"type": "ics", "keychain": "ai-bunshin-calendar", "show": "title"},
        "dev": {"projects": [
            {"name": "HP", "path": str(repo)},
            {"name": "中", "path": str(home / "05_開発/x")},
            {"name": "無い", "path": str(root / "repos/none")},
            {"name": "相対", "path": "relative/dir"},
        ]},
    }
    (home / "設定/config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return {"root": root, "home": home, "plug": plug, "uh": uh, "repo": repo, "cfg": cfg}


def write_cfg(fx, cfg):
    (fx["home"] / "設定/config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")


def run(fx, extra=None, url=CAL_URL, args=None, script=None):
    a = args if args is not None else ["--home", str(fx["home"]), "--plugin-root", str(fx["plug"]), "--user-home", str(fx["uh"])]
    env = {k: v for k, v in os.environ.items() if k != URL_ENV}
    if url is not None:
        env[URL_ENV] = url
    p = subprocess.run([sys.executable, str(script or SCRIPT), "--calendar-url-env", URL_ENV] + a + (extra or []),
                       capture_output=True, env=env)
    return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")


def ok_json(fx, **kw):
    rc, out, err = run(fx, **kw)
    check(rc == 0, "終了コード 0 のはず rc=%s err=%s" % (rc, err))
    return json.loads(out) if rc == 0 else None


def deny_write(s):
    return s["sandbox"]["filesystem"]["denyWrite"]


def deny_edit(s):
    return s["permissions"]["deny"]


# 守る先の期待（決定 S02・S04・T097 §2・X6・X12）。(基点, 相対パス, 種類, 根拠)
def expected(fx):
    h, uh, pl, repo = fx["home"], fx["uh"], fx["plug"], fx["repo"]
    return [
        (h / "設定", "dir", "S02 設定"),
        (h / "CLAUDE.md", "file", "S02 本人設定"),
        (uh / ".ai-bunshin", "dir", "T097 §2 A"),
        (h / "03_インプット", "dir", "S02 03_インプット"),
        (h / ".claude", "dir", "S02 .claude"),
        (uh / ".claude/plugins", "dir", "S02 プラグイン（コピー）"),
        (pl, "dir", "S02 プラグイン（元）"),
        (h / "scripts/auto/run.sh", "file", "S04 run.sh"),
        (h / "scripts/auto/daily_cycle.sh", "file", "S04 daily_cycle.sh"),
        (h / "scripts/hooks", "dir", "S04・X6 hook のフォルダ"),
        (h / "scripts/mods", "dir", "S04・X6 mod のフォルダ"),
        (repo / ".git/hooks", "dir", "X12 hooks"),
        (repo / ".git/config", "file", "X12 config"),
    ]


def rule(p, kind):
    return "Edit(/%s%s)" % (p, "/**" if kind == "dir" else "")


# --- 1. 試しで効いた形（S01・S10・T097 §4・X1・X2・X4・X11）---
def test_core_keys():
    fx = mkfixture()
    s = ok_json(fx)
    sb = s["sandbox"]
    check(sb["enabled"] is True, "S01 enabled")
    check(sb["failIfUnavailable"] is True, "X2 failIfUnavailable")
    check(sb["allowUnsandboxedCommands"] is False, "X1 allowUnsandboxedCommands")
    check(sb["autoAllowBashIfSandboxed"] is False, "X11 autoAllowBashIfSandboxed")
    check(sb["excludedCommands"] == [], "X4 excludedCommands は空")
    check(isinstance(sb["filesystem"]["denyWrite"], list), "denyWrite がある")
    check(set(s.keys()) == {"sandbox", "permissions"}, "最上位のキーは sandbox と permissions だけ %s" % list(s))


# --- 2. 守る先がすべて入る（S02・S04・X6・X12・X5・X3）---
def test_all_protected_in_both():
    fx = mkfixture()
    s = ok_json(fx)
    for p, kind, why in expected(fx):
        check(nfc(str(p)) in [nfc(x) for x in deny_write(s)], "denyWrite に無い：%s（%s）" % (p, why))
        check(rule(nfc(str(p)), kind) in [nfc(x) for x in deny_edit(s)], "Edit の deny に無い：%s（%s）" % (p, why))


def test_paths_are_absolute_forms():
    fx = mkfixture()
    s = ok_json(fx)
    check(all(x.startswith("/") and not x.startswith("//") for x in deny_write(s)), "X3 denyWrite は / で始まる絶対パス")
    check(all(x.startswith("Edit(//") and x.endswith(")") for x in deny_edit(s)), "X3 Edit の deny は // で始まる絶対パス")
    check(len(deny_write(s)) == len(set(deny_write(s))) and len(deny_edit(s)) == len(set(deny_edit(s))), "重複なし")


# --- 3. NFC と NFD の両方（X13）---
def test_nfc_and_nfd():
    fx = mkfixture()
    s = ok_json(fx)
    p = str(fx["home"] / "03_インプット")
    check(nfc(p) in deny_write(s), "X13 NFC の 03_インプット が denyWrite に無い")
    check(nfd(p) in deny_write(s), "X13 NFD の 03_インプット が denyWrite に無い")
    check(nfc(p) != nfd(p), "テスト自体：NFC と NFD は別の文字列のはず")
    check(rule(nfc(p), "dir") in deny_edit(s), "X13 NFC の Edit の deny が無い")
    check(rule(nfd(p), "dir") in deny_edit(s), "X13 NFD の Edit の deny が無い")
    # 本人のフォルダの名前に濁点・半濁点が付く形でも、両方が出る
    fx2 = mkfixture()
    odd = fx2["root"] / nfc("ブ本人プ")
    fx2["home"].rename(odd)
    fx2["home"] = odd
    s2 = ok_json(fx2)
    check(nfc(str(odd / "設定")) in deny_write(s2) and nfd(str(odd / "設定")) in deny_write(s2), "X13 本人のフォルダ名が NFC・NFD の両方")


# --- 4. 書けるままのもの（S02・S04）---
def test_tasks_json_and_logs_stay_writable():
    fx = mkfixture()
    s = ok_json(fx)
    for w in [fx["home"] / "00_タスク管理/data/tasks.json", fx["home"] / "scripts/auto/logs", fx["home"] / "scripts/auto/logs/20261107.log",
              fx["home"] / "00_タスク管理/data/calendar_cache.json", fx["home"] / "scripts/auto/.lock"]:
        for v in (nfc(str(w)), nfd(str(w))):
            hit = [x for x in deny_write(s) if v == x or v.startswith(x.rstrip("/") + "/")]
            check(not hit, "S02・S04 書けるままのはずが denyWrite に含まれる：%s ← %s" % (w.name, hit))
    check("tasks.json" not in json.dumps(s), "tasks.json の名前が出力に出ている")
    check("logs" not in json.dumps(s), "logs が出力に出ている")
    check(not any(x.rstrip("/").endswith("/scripts") for x in deny_write(s)), "S04 scripts ごと denyWrite にしない")
    check(not any(x.rstrip("/").endswith("/scripts/auto") for x in deny_write(s)), "S04 scripts/auto ごと denyWrite にしない")
    check(not any("/scripts/**" in x or "scripts/auto/**" in x for x in deny_edit(s)), "S04 scripts ごと Edit の deny にしない")
    check(not any(x.rstrip("/") == str(fx["home"]) for x in deny_write(s)), "本人のフォルダ全体を denyWrite にしない")


def test_stay_writable_guard():
    """一覧が書けるままの先を含むと、作らずに止める"""
    base = json.loads(PATHS_JSON.read_text(encoding="utf-8"))
    for bad_path, bad_base in [("scripts", "home"), ("scripts/auto", "home"), ("scripts/auto/logs", "home"),
                               ("00_タスク管理", "home"), ("00_タスク管理/data", "home"), ("00_タスク管理/data/tasks.json", "home"), (".", "home")]:
        fx = mkfixture()
        spec = json.loads(json.dumps(base))
        spec["entries"].append({"id": "BAD", "base": bad_base, "path": bad_path, "kind": "dir"})
        pf = fx["root"] / "bad_paths.json"
        pf.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        rc, out, err = run(fx, extra=["--paths-file", str(pf)])
        check(rc == 1 and out == "" and "書けるままにする先" in err, "must_stay_writable：%s を入れたのに止まらない rc=%s" % (bad_path, rc))
    # must_stay_writable の項目を消された一覧も、通さない（空の守りを作らない）
    fx = mkfixture()
    spec = json.loads(json.dumps(base))
    del spec["must_stay_writable"]
    pf = fx["root"] / "nostay.json"
    pf.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    rc, out, err = run(fx, extra=["--paths-file", str(pf)])
    check(rc == 1, "must_stay_writable が無い一覧は作らない")


def test_hooks_and_mods_protected_even_if_missing():
    """X6：hook と mod のフォルダは、無くても守る（囲いの中で作られたあとに hook・mod として動くのを防ぐ）"""
    fx = mkfixture()
    for d in ("hooks", "mods"):
        check(not (fx["home"] / "scripts" / d).exists(), "テスト自体：scripts/%s は無い状態から" % d)
    s = ok_json(fx)
    for d in ("hooks", "mods"):
        p = fx["home"] / "scripts" / d
        check(nfc(str(p)) in deny_write(s), "X6 無い scripts/%s も denyWrite にある" % d)
        check(rule(nfc(str(p)), "dir") in deny_edit(s), "X6 無い scripts/%s も Edit の deny にある" % d)
    # あっても同じ（実在する形）
    (fx["home"] / "scripts/hooks").mkdir(); (fx["home"] / "scripts/mods/sakata-tasks").mkdir(parents=True)
    s2 = ok_json(fx)
    check(s2 == s, "フォルダがあっても無くても同じ出力")
    # logs・tasks.json とは重ならない
    check(not any(x.rstrip("/").endswith("/scripts/auto/logs") for x in deny_write(s2)), "hooks・mods を入れても logs は書ける")


# --- 5. 作らないもの（S08・S10・X9）---
def test_no_allow_no_denyread_no_allowwrite():
    fx = mkfixture()
    s = ok_json(fx)
    sb = s["sandbox"]
    check("allowWrite" not in sb["filesystem"] and "allowRead" not in sb["filesystem"] and "denyRead" not in sb["filesystem"],
          "X9・S08 allowWrite・allowRead・denyRead は作らない")
    check(set(s["permissions"].keys()) == {"deny"}, "S10 permissions は deny だけ（allow・ask を作らない）%s" % list(s["permissions"]))
    check(all(r.startswith("Edit(") for r in deny_edit(s)), "deny は Edit(...) だけ（Read・Bash の deny を作らない）")
    check(set(sb.keys()) == {"enabled", "failIfUnavailable", "allowUnsandboxedCommands", "autoAllowBashIfSandboxed",
                             "excludedCommands", "filesystem", "network"}, "sandbox のキーが想定外 %s" % list(sb))


# --- 6. 通信（S02・S09）---
def test_network_calendar_host():
    fx = mkfixture()
    s = ok_json(fx)
    check(s["sandbox"]["network"]["allowedDomains"] == ["calendar.example.org"], "S09 host だけが入る %s" % s["sandbox"]["network"])
    for url, want in [("https://User:Pass@Cal.Example.ORG:8443/a/b.ics?x=1#f", ["cal.example.org"]),
                      ("webcal://cal.example.org/x.ics", ["cal.example.org"]),
                      ("https://calendar.google.com/calendar/ical/a/private-xyz/basic.ics", ["calendar.google.com"])]:
        s = ok_json(fx, url=url)
        check(s["sandbox"]["network"]["allowedDomains"] == want, "host の取り出し %s → %s" % ("<url>", s["sandbox"]["network"]))
    # 新しい設定のキーを足さなくてよい（config は calendar の type・keychain・show だけ）
    check(set(fx["cfg"]["calendar"].keys()) == {"type", "keychain", "show"}, "テスト自体：config に新しいキーを足していない")


def test_network_blocked_when_no_calendar():
    fx = mkfixture()
    cfg = json.loads(json.dumps(fx["cfg"]))
    # カレンダーが config に無い人は、URL が環境にあっても全部止める
    nocal = {k: v for k, v in cfg.items() if k != "calendar"}
    write_cfg(fx, nocal)
    check(ok_json(fx)["sandbox"]["network"]["allowedDomains"] == [], "S02 calendar が無い人は全部止める")
    for c in [{"type": "google"}, {"keychain": "x"}, "ics", None, []]:
        cfg2 = dict(cfg)
        cfg2["calendar"] = c
        write_cfg(fx, cfg2)
        check(ok_json(fx)["sandbox"]["network"]["allowedDomains"] == [], "calendar=%r は全部止める" % (c,))
    # calendar はあるが URL が無い・使えない形：全部止める（囲いの外で先に取るので困らない）
    write_cfg(fx, cfg)
    for url in [None, "", "   ", "not a url", "ftp://cal.example.org/x", "https://localhost/x", "https://192.168.0.5/x",
                "https://[::1]/x", "https://*.example.org/x", "https:///x", "file:///etc/passwd", "https://exa mple.org/x", "http://[bad/x"]:
        rc, out, err = run(fx, url=url)
        check(rc == 0 and json.loads(out)["sandbox"]["network"]["allowedDomains"] == [], "URL=%r は全部止める rc=%s" % (url, rc))
    # ics_file だけの人（URL なし）も全部止める
    cfg3 = dict(cfg)
    cfg3["calendar"] = {"type": "ics", "ics_file": "~/x.ics"}
    write_cfg(fx, cfg3)
    check(ok_json(fx, url=None)["sandbox"]["network"]["allowedDomains"] == [], "ics_file だけなら全部止める")


# --- 7. URL を出さない（S09）---
def test_url_never_printed():
    fx = mkfixture()
    rc, out, err = run(fx)
    check(SECRET not in out and SECRET not in err and "private-" not in out, "成功の出力に URL の一部が出ている")
    check("calendar.example.org/calendar" not in out and "ical" not in out, "成功の出力に URL の道筋が出ている")
    bad_cases = [
        ["--home", str(fx["root"] / "ない"), "--plugin-root", str(fx["plug"])],
        ["--home", str(fx["home"]), "--plugin-root", str(fx["root"] / "ない")],
        ["--home", "relative", "--plugin-root", str(fx["plug"])],
        ["--home", str(fx["home"]), "--plugin-root", str(fx["plug"]), "--config", str(fx["root"] / "ない.json")],
        ["--home", str(fx["home"])],
        [],
        ["--bogus", CAL_URL],
        ["--home", CAL_URL, "--plugin-root", str(fx["plug"])],
    ]
    for a in bad_cases:
        rc, out, err = run(fx, args=a)
        check(rc == 1 and SECRET not in out and SECRET not in err and "private-" not in err, "失敗の出力に URL が出る/終了コードが 1 でない：%s rc=%s err=%s" % (a[:2], rc, err[:80]))
    # config が壊れていて URL が環境にあるときも
    (fx["home"] / "設定/config.json").write_text("{" + CAL_URL, encoding="utf-8")
    rc, out, err = run(fx)
    check(rc == 1 and SECRET not in err and SECRET not in out, "config が壊れたときに URL が出る")
    # 例外の型名だけを出す経路（想定外の例外）：paths-file がディレクトリ
    fx2 = mkfixture()
    rc, out, err = run(fx2, extra=["--paths-file", str(fx2["root"])])
    check(rc == 1 and SECRET not in err and SECRET not in out, "想定外の失敗で URL が出る")


# --- 8. 作れないとき（S05）---
def test_exit1_cases():
    fx = mkfixture()
    plug = str(fx["plug"])
    cases = {
        "home が無い": ["--home", str(fx["root"] / "ない"), "--plugin-root", plug],
        "home が相対": ["--home", "本人", "--plugin-root", plug],
        "home が /": ["--home", "/", "--plugin-root", plug],
        "home がファイル": ["--home", str(fx["home"] / "CLAUDE.md"), "--plugin-root", plug],
        "plugin-root が無い": ["--home", str(fx["home"]), "--plugin-root", str(fx["root"] / "ない")],
        "plugin-root が相対": ["--home", str(fx["home"]), "--plugin-root", "plugins/ai-bunshin"],
        "plugin-root が渡されない": ["--home", str(fx["home"])],
        "引数なし": [],
        "知らない引数": ["--home", str(fx["home"]), "--plugin-root", plug, "--x", "y"],
        "config が無い": ["--home", str(fx["home"]), "--plugin-root", plug, "--config", str(fx["root"] / "ない.json")],
        "user-home が無い": ["--home", str(fx["home"]), "--plugin-root", plug, "--user-home", str(fx["root"] / "ない")],
    }
    for name, a in cases.items():
        rc, out, err = run(fx, args=a)
        check(rc == 1, "S05 %s：終了コード 1 のはず rc=%s" % (name, rc))
        check(out == "", "S05 %s：標準出力は空のはず" % name)
        check(err.startswith("sandbox_settings: ") and err.count("\n") == 1, "S05 %s：標準エラーは日本語1行のはず %r" % (name, err))
        check(any(ord(c) > 127 for c in err), "S05 %s：日本語の理由のはず" % name)
    # config の中身が読めない
    for body in ["", "{", "[]", "null", "\"x\"", "\x00\x01"]:
        (fx["home"] / "設定/config.json").write_text(body, encoding="utf-8")
        rc, out, err = run(fx)
        check(rc == 1 and out == "" and err.count("\n") == 1, "S05 config=%r は作れない rc=%s" % (body, rc))
    # 一覧が読めない・空・書き方が違う
    fx = mkfixture()
    for body in ["", "{", "[]", "{\"entries\": []}", "{\"entries\": [{}]}",
                 json.dumps({"entries": [{"id": "x", "base": "root", "path": "a", "kind": "dir"}], "add_dir_git": [], "must_stay_writable": []}),
                 json.dumps({"entries": [{"id": "x", "base": "home", "path": "/etc", "kind": "dir"}], "add_dir_git": [], "must_stay_writable": []}),
                 json.dumps({"entries": [{"id": "x", "base": "home", "path": "../a", "kind": "dir"}], "add_dir_git": [], "must_stay_writable": []}),
                 json.dumps({"entries": [{"id": "x", "base": "home", "path": "a", "kind": "dir"}], "must_stay_writable": []})]:
        pf = fx["root"] / "p.json"
        pf.write_text(body, encoding="utf-8")
        rc, out, err = run(fx, extra=["--paths-file", str(pf)])
        check(rc == 1 and out == "" and err.count("\n") == 1, "S05 一覧=%r は作れない rc=%s" % (body[:40], rc))
    rc, out, err = run(fx, extra=["--paths-file", str(fx["root"] / "ない.json")])
    check(rc == 1 and out == "", "S05 一覧のファイルが無い")


def test_special_chars_in_path():
    for ch in ["*", "?", "[", "(", "{", ")"]:
        fx = mkfixture()
        odd = fx["root"] / ("本人" + ch)
        fx["home"].rename(odd)
        fx["home"] = odd
        rc, out, err = run(fx)
        check(rc == 1 and out == "" and "使えない文字" in err, "パスに %r を含むと作らない rc=%s" % (ch, rc))


# --- 9. 出力の形 ---
def test_output_one_line_ascii_json():
    fx = mkfixture()
    rc, out, err = run(fx)
    check(rc == 0 and err == "", "成功のとき標準エラーは空 %r" % err)
    check(out.endswith("\n") and out.count("\n") == 1, "標準出力は1行")
    check(all(ord(c) < 128 for c in out), "標準出力は ASCII だけ（ロケールに左右されない）")
    check(isinstance(json.loads(out), dict), "JSON として読める")


# --- 10. 足すフォルダ（X12）・プラグインの元が複数 ---
def test_add_dir_repos():
    fx = mkfixture()
    s = ok_json(fx)
    ww = [nfc(x) for x in deny_write(s)]
    check(nfc(str(fx["repo"] / ".git/hooks")) in ww and nfc(str(fx["repo"] / ".git/config")) in ww, "X12 足すリポジトリの .git/hooks・.git/config")
    check(not any("05_開発" in x and ".git" in x for x in ww), "本人のフォルダの中の案件は対象外（daily_cycle.sh と同じ選び方）")
    check(not any("/none/" in x for x in ww), "実在しない案件は対象外")
    check(not any("relative" in x for x in ww), "相対パスの案件は対象外")
    # dev が無い config でも作れる
    cfg = {k: v for k, v in fx["cfg"].items() if k != "dev"}
    write_cfg(fx, cfg)
    s2 = ok_json(fx)
    check(s2 is not None and not any(".git" in x for x in deny_write(s2)), "dev が無ければ .git の項目は入らない")
    write_cfg(fx, dict(fx["cfg"], dev="x"))
    check(ok_json(fx) is not None, "dev が文字列でも作れる（読み飛ばす）")


def test_multiple_plugin_roots():
    fx = mkfixture()
    cache = fx["root"] / "cache" / "ai-bunshin" / "1.0.0"
    cache.mkdir(parents=True)
    rc, out, err = run(fx, extra=["--plugin-root", str(cache)])
    check(rc == 0, "プラグインの元を2つ渡せる")
    s = json.loads(out)
    check(str(fx["plug"]) in deny_write(s) and str(cache) in deny_write(s), "X6・X12 2つとも denyWrite")
    check(rule(str(cache), "dir") in deny_edit(s), "2つめも Edit の deny")


# --- 11. 書き込みをしない・本物は読むだけ ---
def snapshot(root):
    out = {}
    for dp, dn, fn in os.walk(root):
        for n in dn + fn:
            p = os.path.join(dp, n)
            st = os.lstat(p)
            out[p] = (st.st_size, st.st_mtime_ns)
    return out


def test_no_writes():
    fx = mkfixture()
    before = snapshot(fx["root"])
    ok_json(fx)
    check(snapshot(fx["root"]) == before, "スクリプトがファイルを作った・変えた")
    if REAL_HOME.is_dir() and (REAL_HOME / "設定/config.json").is_file():
        snap = {p: (REAL_HOME / p).stat().st_mtime_ns for p in ["設定/config.json", "00_タスク管理/data/tasks.json", "CLAUDE.md"] if (REAL_HOME / p).exists()}
        plug = HERE.parent
        rc, out, err = run(fx, args=["--home", str(REAL_HOME), "--plugin-root", str(plug)])
        check(rc == 0 and json.loads(out)["sandbox"]["enabled"] is True, "本物の本人のフォルダ（読むだけ）で JSON が作れる rc=%s err=%s" % (rc, err))
        check(snap == {p: (REAL_HOME / p).stat().st_mtime_ns for p in snap}, "本物の本人のフォルダのファイルが変わった")


# --- 12. 一覧の中身（外す・足りない形に壊されたら落ちる）---
def test_paths_json_shape():
    spec = json.loads(PATHS_JSON.read_text(encoding="utf-8"))
    ids = {e["id"] for e in spec["entries"]}
    want = {"A-settings", "A-claude-md", "A-ai-bunshin-dir", "B-input", "C-claude", "D-plugin-cache", "D-plugin-source", "S04-run-sh", "S04-daily-cycle", "S04-hooks", "S04-mods"}
    check(ids == want, "一覧の id が決定どおり：差 %s" % (ids ^ want))
    check(spec["add_dir_git"] == [".git/hooks", ".git/config"], "X12 add_dir_git")
    stay = {(m["base"], m["path"]) for m in spec["must_stay_writable"]}
    check(stay == {("home", "00_タスク管理/data/tasks.json"), ("home", "scripts/auto/logs")}, "must_stay_writable が tasks.json と logs")
    check(all(e["path"] not in ("scripts", "scripts/auto", "scripts/auto/logs", "00_タスク管理/data/tasks.json") for e in spec["entries"]), "S02・S04 一覧に scripts・tasks.json・logs が無い")


# --- 想定外の例外でも URL を出さない・シンボリックリンクの実体も守る ---
def test_unexpected_exception_hides_url():
    import importlib.util
    import io
    spec = importlib.util.spec_from_file_location("sandbox_settings_under_test", str(SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fx = mkfixture()

    def boom(*a, **k):
        raise RuntimeError("boom " + CAL_URL)
    mod.build_settings = boom
    os.environ[URL_ENV] = CAL_URL
    old_err, old_out = sys.stderr, sys.stdout
    sys.stderr = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    sys.stdout = io.StringIO()
    try:
        rc = mod.main(["--calendar-url-env", URL_ENV, "--home", str(fx["home"]), "--plugin-root", str(fx["plug"])])
        sys.stderr.flush()
        err = sys.stderr.buffer.getvalue().decode("utf-8")
        out = sys.stdout.getvalue()
    finally:
        sys.stderr, sys.stdout = old_err, old_out
        os.environ.pop(URL_ENV, None)
    check(rc == 1 and out == "", "想定外の例外でも終了コード 1・標準出力は空 rc=%s" % rc)
    check(SECRET not in err and "boom" not in err and "RuntimeError" in err, "想定外の例外の文に URL・例外の中身が出る %r" % err)


def test_symlink_realpath_also_denied():
    fx = mkfixture()
    link = fx["root"] / "リンク本人"
    os.symlink(str(fx["home"]), str(link))
    rc, out, err = run(fx, args=["--home", str(link), "--plugin-root", str(fx["plug"]), "--user-home", str(fx["uh"])])
    check(rc == 0, "リンク経由の本人のフォルダでも作れる err=%s" % err)
    s = json.loads(out)
    check(str(link / "03_インプット") in deny_write(s), "リンク経由のパスが denyWrite にある")
    check(nfc(str(fx["home"] / "03_インプット")) in [nfc(x) for x in deny_write(s)], "実体のパスも denyWrite にある（Seatbelt は実体で見る）")
    check(rule(nfc(str(fx["home"] / ".claude")), "dir") in [nfc(x) for x in deny_edit(s)], "実体のパスも Edit の deny にある")


for name, fn in list(globals().items()):
    if name.startswith("test_") and callable(fn):
        fn()

print("%d checks, %d failed" % (count, fail))
sys.exit(1 if fail else 0)
