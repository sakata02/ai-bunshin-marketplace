"""自動実行の囲い（sandbox_settings.py・protected_paths.json）のテスト。T119 G2。
実行：python3 tests/test_sandbox_settings.py（失敗があれば終了コード1）
- 期待する守り先は、一覧（protected_paths.json）からでなく、このファイルに決定（S02・S04）どおりに書く。
  一覧から何かを外す・足りない形（NFD など）にする・書けるままの先を止める、と落ちる
- claude も security（キーチェーン）も動かさない。URL は作り物（SECRET を含む）。本物の本人のフォルダは読むだけ"""
import json
import os
import shutil
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
TMP_DIRS = []   # このテストが作った一時フォルダ（終わりに片付ける。D5）


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
    TMP_DIRS.append(root)
    home = root / "本人"
    for d in ["設定", "03_インプット", ".claude/rules", "scripts/auto/logs", "00_タスク管理/data", "04_ナレッジ", "05_開発/x"]:
        (home / d).mkdir(parents=True)
    (home / "00_タスク管理/data/tasks.json").write_text("{}", encoding="utf-8")
    (home / "CLAUDE.md").write_text("x", encoding="utf-8")
    (home / "scripts/auto/run.sh").write_text("#!/bin/zsh\n", encoding="utf-8")
    (home / "scripts/auto/daily_cycle.sh").write_text("#!/bin/zsh\n", encoding="utf-8")
    (home / ".git/hooks").mkdir(parents=True)
    (home / ".git/config").write_text("", encoding="utf-8")
    mkt = root / "marketplace"
    plug = mkt / "plugins" / "ai-bunshin"
    (plug / "scripts").mkdir(parents=True)
    uh = root / "userhome"
    (uh / ".claude/plugins").mkdir(parents=True)
    other_mkt = root / "other_marketplace"
    other_mkt.mkdir()
    (root / "gh_clone").mkdir()   # github 由来のもの（実在する。directory でないので足さない）
    (uh / ".claude/plugins/known_marketplaces.json").write_text(json.dumps({
        "official": {"source": {"source": "github", "repo": "x/y"}, "installLocation": str(root / "gh_clone")},
        "mine": {"source": {"source": "directory", "path": str(mkt)}, "installLocation": str(mkt)},
        "second": {"source": {"source": "directory", "path": str(other_mkt)}, "installLocation": str(other_mkt)},
        "gone": {"source": {"source": "directory", "path": str(root / "nowhere_src")}, "installLocation": str(root / "nowhere")},
        "gh_bad": {"source": {"source": "github", "repo": "x/z"}, "installLocation": "relative/(1)"},   # directory でなければ見ない
        "broken1": "x", "broken2": {"source": "directory"}, "broken3": {"source": {"source": "directory"}, "installLocation": 5},
    }), encoding="utf-8")
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
    return {"root": root, "home": home, "plug": plug, "uh": uh, "repo": repo, "cfg": cfg, "mkt": mkt, "mkt2": other_mkt}


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
        (h / "scripts", "dir", "S04 scripts/ を丸ごと"),
        (h / ".ai-bunshin-canary-dir/guard", "dir", "S23 囲いの点検の目印（guard だけ。親は守らない）"),
        (fx["mkt"], "dir", "S12 マーケットプレイスのルート"),
        (fx["mkt2"], "dir", "S12 directory の2つ目"),
        (h / "CLAUDE.local.md", "file", "S13 CLAUDE.local.md"),
        (h / ".git", "dir", "S17 本人のフォルダの .git を丸ごと"),
        (uh / "Library/LaunchAgents", "dir", "S13 LaunchAgents"),
        (uh / ".claude/settings.json", "file", "S13 利用者の settings.json"),
        (uh / ".claude/CLAUDE.md", "file", "S13 利用者の CLAUDE.md"),
        (uh / ".claude/skills", "dir", "S13 skills"),
        (uh / ".claude/agents", "dir", "S13 agents"),
        (uh / ".claude/commands", "dir", "S13 commands"),
        (repo / ".git", "dir", "S17 足すリポジトリの .git を丸ごと"),
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


# --- 4. 書けるままのもの（S02。S04 改で logs は書けなくなった）---
def test_tasks_json_stays_writable_scripts_all_protected():
    fx = mkfixture()
    s = ok_json(fx)
    for w in [fx["home"] / "00_タスク管理/data/tasks.json", fx["home"] / "00_タスク管理/data/calendar_cache.json",
              fx["home"] / "00_タスク管理/タスクボード.md", fx["home"] / "02_成果物/x.xlsx", fx["home"] / "04_ナレッジ/a.md"]:
        for v in (nfc(str(w)), nfd(str(w))):
            hit = [x for x in deny_write(s) if v == x or v.startswith(x.rstrip("/") + "/")]
            check(not hit, "S02 書けるままのはずが denyWrite に含まれる：%s ← %s" % (w.name, hit))
    check("tasks.json" not in json.dumps(s), "tasks.json の名前が出力に出ている")
    check(not any(x.rstrip("/") == str(fx["home"]) for x in deny_write(s)), "本人のフォルダ全体を denyWrite にしない")
    # S04 改：scripts/ は丸ごと。run.sh だけ・hooks と mods だけ、では親を mv してリンクに替えられる
    for sub in ("scripts", ):
        for v in (nfc(str(fx["home"] / sub)), nfd(str(fx["home"] / sub))):
            check(v in deny_write(s), "S04 %s が丸ごと denyWrite にある" % sub)
            check(rule(v, "dir") in deny_edit(s), "S04 %s が丸ごと Edit の deny にある" % sub)
    for w in [fx["home"] / "scripts/auto/logs/20261107.log", fx["home"] / "scripts/auto/.lock", fx["home"] / "scripts/hooks/x.sh",
              fx["home"] / "scripts/mods/m/a.ts", fx["home"] / "scripts/new_dir/x"]:
        hit = [x for x in deny_write(s) if nfc(str(w)).startswith(x.rstrip("/") + "/")]
        check(hit, "S04 scripts/ の中は書けない：%s" % w.name)
    # 個別に分けて守る形に戻っていない（scripts/ の中だけの項目は冗長なので無いはず）
    check(not any(x.endswith("/scripts/auto/run.sh") or x.endswith("/scripts/hooks") or x.endswith("/scripts/mods") for x in deny_write(s)),
          "S04 scripts/ の中の個別の項目は作らない（丸ごとだけ）")


def test_stay_writable_guard():
    """一覧が tasks.json を含むと、作らずに止める"""
    base = json.loads(PATHS_JSON.read_text(encoding="utf-8"))
    for bad_path, bad_base in [("00_タスク管理", "home"), ("00_タスク管理/data", "home"), ("00_タスク管理/data/tasks.json", "home"), (".", "home")]:
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
    # マーケットプレイスのルートが tasks.json を含む（本人のフォルダの親を登録した）ときも作らない
    fx = mkfixture()
    (fx["uh"] / ".claude/plugins/known_marketplaces.json").write_text(json.dumps(
        {"p": {"source": {"source": "directory", "path": str(fx["root"])}, "installLocation": str(fx["root"])}}), encoding="utf-8")
    rc, out, err = run(fx)
    check(rc == 1 and out == "" and "S12-marketplace" in err, "S12 マーケットプレイスのルートが tasks.json を含むときは作らない rc=%s err=%s" % (rc, err))


def test_scripts_missing_still_protected():
    """X6：scripts/ が無くても守る（囲いの中で作られて、あとで hook・mod・launchd の入口になるのを防ぐ）"""
    fx = mkfixture()
    shutil.rmtree(str(fx["home"] / "scripts"))
    s = ok_json(fx)
    check(nfc(str(fx["home"] / "scripts")) in deny_write(s) and rule(nfc(str(fx["home"] / "scripts")), "dir") in deny_edit(s), "無い scripts/ も守る")
    # CLAUDE.local.md・~/Library/LaunchAgents・~/.claude の項目も、無くても入る
    for p in [fx["home"] / "CLAUDE.local.md", fx["uh"] / "Library/LaunchAgents", fx["uh"] / ".claude/skills"]:
        check(not p.exists() and nfc(str(p)) in deny_write(s), "S13 無い %s も denyWrite にある" % p.name)


def test_marketplace_roots():
    fx = mkfixture()
    s = ok_json(fx)
    for r in (fx["mkt"], fx["mkt2"]):
        check(nfc(str(r)) in deny_write(s) and rule(nfc(str(r)), "dir") in deny_edit(s), "S12 directory のマーケットプレイスのルートを丸ごと守る：%s" % r.name)
    check(not any("gh_clone" in x or "nowhere" in x or "relative" in x for x in deny_write(s)), "S12 github・無い installLocation は足さない")
    # --plugin-root を渡さない形でなく、渡した plugin-root が別の場所でも、マーケットプレイスは足される
    other = fx["root"] / "cache" / "p"
    other.mkdir(parents=True)
    rc, out, err = run(fx, args=["--home", str(fx["home"]), "--plugin-root", str(other), "--user-home", str(fx["uh"])])
    s2 = json.loads(out)
    check(rc == 0 and str(fx["mkt"]) in deny_write(s2) and str(other) in deny_write(s2), "S12 plugin-root が別でもマーケットプレイスを守る（両方）")
    # 読めない・無いときは、足さずに作る（止めない）
    f = fx["uh"] / ".claude/plugins/known_marketplaces.json"
    for body in ["", "{", "[]", "null", "\"x\"", "\x00", None]:
        if body is None:
            f.rename(fx["uh"] / ".claude/plugins/moved.json")
        else:
            f.write_text(body, encoding="utf-8")
        rc, out, err = run(fx)
        sj = json.loads(out) if rc == 0 else {}
        check(rc == 0 and err == "" and str(fx["mkt2"]) not in deny_write(sj) and str(fx["plug"]) in deny_write(sj),
              "S12 known_marketplaces.json=%r でも作る（マーケットプレイスは足さない）rc=%s err=%s" % (body, rc, err))
    # ファイルがフォルダ
    (fx["uh"] / ".claude/plugins/moved.json").rename(f)
    f.rename(fx["uh"] / ".claude/plugins/moved2.json")
    f.mkdir()
    rc, out, err = run(fx)
    check(rc == 0, "S12 known_marketplaces.json がフォルダでも作る rc=%s" % rc)
    # R1：directory の場所が使えない形（相対パス・使えない文字）なら作らない。黙って飛ばして Python を許さない
    kf = fx["uh"] / ".claude/plugins/known_marketplaces.json"
    if kf.is_dir():   # 直前の「ファイルがフォルダ」の形を脇へ移す（作った一時フォルダの中だけ。終わりにまとめて片付く）
        kf.rename(fx["uh"] / ".claude/plugins/was_dir")
    ok_ent = {"source": {"source": "directory", "path": str(fx["mkt"])}, "installLocation": str(fx["mkt"])}
    for loc in ["relative/dir", "mk", "./x", "~/mk", str(fx["root"] / "mk (1)"), str(fx["root"] / "mk*"), str(fx["root"] / "mk[1]"),
                str(fx["root"] / "mk{a}"), str(fx["root"] / "mk?"), str(fx["root"] / "mk\nx")]:
        kf.write_text(json.dumps({"p": {"source": {"source": "directory", "path": "x"}, "installLocation": loc}, "ok": ok_ent}), encoding="utf-8")
        rc, out, err = run(fx)
        check(rc == 1 and out == "" and err.count("\n") == 1 and "マーケットプレイス" in err, "R1 使えない形 %r は作らない rc=%s" % (loc, rc))
        check(SECRET not in err, "R1 エラーに URL が出ない")
    # directory でない項目が使えない形でも、作る（見ない）。場所が書かれていない directory も作る（守る相手が無い）
    kf.write_text(json.dumps({"g": {"source": {"source": "github", "repo": "x"}, "installLocation": "relative/(1)"},
                              "n": {"source": {"source": "directory"}}, "ok": ok_ent}), encoding="utf-8")
    rc, out, err = run(fx)
    check(rc == 0 and str(fx["mkt"]) in deny_write(json.loads(out)), "R1 github の使えない形・場所なしの directory は読み飛ばして作る rc=%s err=%s" % (rc, err))
    kf.write_text(json.dumps({"ok": ok_ent}), encoding="utf-8")
    # 一覧の marketplaces の書き方が違うときは作らない
    base = json.loads(PATHS_JSON.read_text(encoding="utf-8"))
    for mod in (lambda d: d.pop("marketplaces"), lambda d: d["marketplaces"].pop("file"), lambda d: d["marketplaces"].update(base="home")):
        spec = json.loads(json.dumps(base))
        mod(spec)
        pf = fx["root"] / "m.json"
        pf.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        rc, out, err = run(fx, extra=["--paths-file", str(pf)])
        check(rc == 1 and out == "", "S12 一覧の marketplaces が壊れていたら作らない")


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
    check(nfc(str(fx["repo"] / ".git")) in ww, "S17 足すリポジトリの .git が丸ごと denyWrite にある")
    check(nfc(str(fx["repo"] / ".git/hooks")) not in ww and nfc(str(fx["repo"] / ".git/config")) not in ww, "S17 .git/hooks・.git/config の個別の項目は、丸ごとに含まれるので無い")
    # D4：ファイルかフォルダかは名前でなく一覧の kind で決まる（.git はフォルダ＝ /** が付く）
    ee = [nfc(x) for x in deny_edit(s)]
    check("Edit(/%s/**)" % nfc(str(fx["repo"] / ".git")) in ee, "S17・D4 足すリポジトリの .git の Edit の deny（フォルダ丸ごと）")
    base = json.loads(PATHS_JSON.read_text(encoding="utf-8"))
    spec = json.loads(json.dumps(base))
    spec["add_dir_git"] = [{"path": ".git/info/exclude_x", "kind": "file"}, {"path": ".git/hooks_config", "kind": "dir"}]
    pf = fx["root"] / "g.json"
    pf.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    sg = ok_json(fx, extra=["--paths-file", str(pf)])
    eg = [nfc(x) for x in deny_edit(sg)]
    check("Edit(/%s)" % nfc(str(fx["repo"] / ".git/info/exclude_x")) in eg, "D4 名前が config でなくても kind=file ならファイル")
    check("Edit(/%s/**)" % nfc(str(fx["repo"] / ".git/hooks_config")) in eg, "D4 名前が config で終わっても kind=dir ならフォルダ")
    for bad in ([".git/hooks"], [{"path": ".git/x"}], [{"path": ".git", "kind": "gitt"}], [{"path": ".git/x", "kind": "pipe"}], [{"path": "/etc", "kind": "dir"}], [{"path": "../a", "kind": "dir"}]):
        spec["add_dir_git"] = bad
        pf.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        rc, out, err = run(fx, extra=["--paths-file", str(pf)])
        check(rc == 1 and out == "", "D4 add_dir_git の書き方が違えば作らない：%r" % (bad,))
    check(not any("05_開発" in x and ".git" in x for x in ww), "本人のフォルダの中の案件は対象外（daily_cycle.sh と同じ選び方）")
    check(not any("/none/" in x for x in ww), "実在しない案件は対象外")
    check(not any("relative" in x for x in ww), "相対パスの案件は対象外")
    # dev が無い config でも作れる
    cfg = {k: v for k, v in fx["cfg"].items() if k != "dev"}
    write_cfg(fx, cfg)
    s2 = ok_json(fx)
    check(s2 is not None and not any(str(fx["repo"]) in x for x in deny_write(s2)), "dev が無ければ足すリポジトリの .git の項目は入らない")
    write_cfg(fx, dict(fx["cfg"], dev="x"))
    check(ok_json(fx) is not None, "dev が文字列でも作れる（読み飛ばす）")


def test_marketplace_source_path():
    """W6（G2 の低1・低2）：installLocation が無く source.path だけでも守る。両方あって違えば両方。使えない形・/ は作らない"""
    fx = mkfixture()
    kf = fx["uh"] / ".claude/plugins/known_marketplaces.json"
    only_src = fx["root"] / "only_src"
    only_src.mkdir()
    other_loc = fx["root"] / "other_loc"
    other_loc.mkdir()

    def ent(path=None, loc=None):
        e = {"source": {"source": "directory"}}
        if path is not None:
            e["source"]["path"] = path
        if loc is not None:
            e["installLocation"] = loc
        kf.write_text(json.dumps({"a": e}), encoding="utf-8")

    # source.path だけ（installLocation なし）
    ent(path=str(only_src))
    s = ok_json(fx)
    check(s is not None and nfc(str(only_src)) in deny_write(s) and rule(nfc(str(only_src)), "dir") in deny_edit(s),
          "W6 installLocation が無く source.path だけでも守る")
    # 両方あって違えば両方
    ent(path=str(only_src), loc=str(other_loc))
    s = ok_json(fx)
    ww = deny_write(s) if s else []
    check(nfc(str(only_src)) in ww and nfc(str(other_loc)) in ww, "W6 両方あって違えば両方守る")
    # installLocation が文字列でなくても、source.path は守る
    ent(path=str(only_src), loc=5)
    s = ok_json(fx)
    check(s is not None and nfc(str(only_src)) in deny_write(s), "W6 installLocation が文字列でなくても source.path を守る")
    # 同じ場所が2回書かれても二重にならない
    ent(path=str(only_src), loc=str(only_src))
    s = ok_json(fx)
    check(s is not None and deny_write(s).count(nfc(str(only_src))) == 1, "W6 同じ場所が2回書かれても1つ")
    # どちらかが使えない形なら、もう片方が良くても作らない。/ も作らない
    for bad in ["relative/dir", "x", "~/mk", str(fx["root"] / "mk (1)"), str(fx["root"] / "mk*"), "/", "//", "/.", "/../"]:
        ent(path=bad, loc=str(other_loc))
        rc, out, err = run(fx)
        check(rc == 1 and out == "" and err.count("\n") == 1 and "マーケットプレイス" in err, "W6 source.path が使えない形 %r は作らない rc=%s" % (bad, rc))
        check(SECRET not in err and str(fx["root"]) not in err, "W6 エラーに URL・パスが出ない")
        ent(path=str(other_loc), loc=bad)
        rc, out, err = run(fx)
        check(rc == 1 and out == "", "W6 installLocation が使えない形 %r は作らない（/ を含む）rc=%s" % (bad, rc))
        ent(path=bad)
        rc, out, err = run(fx)
        check(rc == 1 and out == "", "W6 source.path だけが使えない形 %r は作らない rc=%s" % (bad, rc))
    # path が実在しなければ足さない（作れる）
    ent(path=str(fx["root"] / "nope"))
    rc, out, err = run(fx)
    check(rc == 0 and "nope" not in out, "W6 実在しない source.path は足さない rc=%s" % rc)
    # source.path が文字列でない（installLocation だけ）なら今までどおり
    ent(path=7, loc=str(other_loc))
    s = ok_json(fx)
    check(s is not None and nfc(str(other_loc)) in deny_write(s), "W6 source.path が数でも installLocation は守る")


def test_print_add_dirs():
    """W7（G2 の低5）：daily_cycle.sh の --add-dir と囲いの守る先は、同じ判定（--print-add-dirs）"""
    fx = mkfixture()
    pa = ["--home", str(fx["home"]), "--print-add-dirs"]
    rc, out, err = run(fx, args=pa)
    check(rc == 0 and out.splitlines() == [str(fx["repo"])], "W7 本人のフォルダの外の実在の絶対パスだけ rc=%s out=%r" % (rc, out))
    s = ok_json(fx)
    check(s is not None and nfc(str(fx["repo"] / ".git")) in deny_write(s), "W7 同じ先が囲いの守る先にも入る")
    # 本人のフォルダにリンクで入る先は「中」＝対象外（realpath で判定）
    link = fx["root"] / "リンク先"
    os.symlink(str(fx["home"] / "05_開発/x"), str(link))
    write_cfg(fx, dict(fx["cfg"], dev={"projects": [{"path": str(link)}, {"path": str(fx["repo"])}, {"path": str(fx["repo"])}]}))
    rc, out, err = run(fx, args=pa)
    check(rc == 0 and str(link) not in out and str(fx["repo"]) in out, "W7 リンクで本人のフォルダの中に入る先は出さない（realpath）out=%r" % out)
    s = ok_json(fx)
    check(s is not None and not any("リンク先" in x for x in deny_write(s)), "W7 リンクで中に入る先は囲いの守る先にも入らない")
    write_cfg(fx, dict(fx["cfg"], dev={"projects": [{"path": "~/sbx_nowhere_dir_zz"}]}))
    rc, out, err = run(fx, args=pa)
    check(rc == 0 and out == "", "W7 実在しない先は出さない")
    # 読めない・無いときは何も出さず終了コード0（前の daily_cycle.sh と同じ）
    for body in ["{", "[]", "null"]:
        (fx["home"] / "設定/config.json").write_text(body, encoding="utf-8")
        rc, out, err = run(fx, args=pa)
        check(rc == 0 and out == "" and err == "", "W7 config が %r でも何も出さず終了コード0 rc=%s err=%s" % (body, rc, err))
    (fx["home"] / "設定/config.json").unlink()
    rc, out, err = run(fx, args=pa)
    check(rc == 0 and out == "", "W7 config が無くても何も出さず終了コード0")
    (fx["home"] / "設定/config.json").write_bytes(b"\xef\xbb\xbf" + json.dumps(fx["cfg"], ensure_ascii=False).encode("utf-8"))
    rc, out, err = run(fx, args=pa)
    check(rc == 0 and out.splitlines() == [str(fx["repo"])], "W7 BOM 付き config も読める")


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
    want = {"A-settings", "A-claude-md", "A-claude-local-md", "A-ai-bunshin-dir", "B-input", "C-claude", "C-git",
            "D-plugin-cache", "D-plugin-source", "S04-scripts", "S23-canary-guard", "S13-launchagents", "S13-user-settings", "S13-user-claude-md",
            "S13-user-skills", "S13-user-agents", "S13-user-commands"}
    check(ids == want, "一覧の id が決定どおり：差 %s" % (ids ^ want))
    check(spec["add_dir_git"] == [{"path": ".git", "kind": "git"}], "S17 add_dir_git は .git を丸ごと（kind=git）")
    cg = [e for e in spec["entries"] if e["id"] == "C-git"]
    check(len(cg) == 1 and cg[0]["base"] == "home" and cg[0]["path"] == ".git" and cg[0]["kind"] == "git", "S17 本人のフォルダの .git は丸ごと（kind=git）")
    stay = {(m["base"], m["path"]) for m in spec["must_stay_writable"]}
    check(stay == {("home", "00_タスク管理"), ("home", "00_タスク管理/data/tasks.json")}, "must_stay_writable は 00_タスク管理 と tasks.json だけ（R2）")
    check(spec["marketplaces"]["source_kind"] == "directory", "S12 directory のものだけ")
    check(all(e["path"] not in ("scripts/auto", "scripts/auto/logs", "scripts/auto/run.sh", "scripts/hooks", "scripts/mods", "00_タスク管理/data/tasks.json")
              for e in spec["entries"]), "S04 一覧に scripts の中の個別の項目・tasks.json が無い（scripts/ を丸ごと）")


# --- 13. .git は丸ごと（S17）・.git がファイルの形（worktree・submodule）---
def test_git_whole_dir():
    fx = mkfixture()
    s = ok_json(fx)
    ww = [nfc(x) for x in deny_write(s)]
    ee = [nfc(x) for x in deny_edit(s)]
    for g in (fx["home"] / ".git", fx["repo"] / ".git"):
        check(nfc(str(g)) in ww, "S17 .git が denyWrite にある：%s" % g)
        check("Edit(/%s/**)" % nfc(str(g)) in ee, "S17 .git が Edit の deny（フォルダ丸ごと）にある：%s" % g)
        for sub in (".git/hooks", ".git/config"):   # 丸ごとに含まれるので、個別の項目は無い
            check(nfc(str(g.parent / sub)) not in ww, "S17 個別の項目が無い：%s" % (g.parent / sub))
    # .git がまだ無い本人のフォルダでも、守る先に入る（あとで囲いの中で作られても守る）
    fx2 = mkfixture()
    (fx2["home"] / ".git").rename(fx2["home"] / "git_moved_away")
    s2 = ok_json(fx2)
    check(nfc(str(fx2["home"] / ".git")) in [nfc(x) for x in deny_write(s2)], "S17 .git が無くても守る先に入る")


def _gitfile_fixture(abs_form, content=None):
    """本人のフォルダの .git をファイル（gitdir: …）にする。指す先は本人のフォルダの外の作り物"""
    fx = mkfixture()
    (fx["home"] / ".git").rename(fx["home"] / "git_moved_away")
    target = fx["root"] / "elsewhere" / "wt" / "gitdir_x"
    target.mkdir(parents=True)
    ref = str(target) if abs_form else os.path.relpath(str(target), str(fx["home"]))
    data = content if content is not None else ("gitdir: %s\n" % ref).encode("utf-8")
    (fx["home"] / ".git").write_bytes(data)
    return fx, target


def test_git_file_form():
    for abs_form in (True, False):
        fx, target = _gitfile_fixture(abs_form)
        s = ok_json(fx)
        ww = [nfc(x) for x in deny_write(s)]
        ee = [nfc(x) for x in deny_edit(s)]
        gf = fx["home"] / ".git"
        tag = "絶対" if abs_form else "相対"
        check(nfc(str(gf)) in ww and "Edit(/%s)" % nfc(str(gf)) in ee, "S17 .git ファイル（%s）そのものが denyWrite と Edit の deny（ファイル）にある" % tag)
        check("Edit(/%s/**)" % nfc(str(gf)) not in ee, "S17 .git ファイルに /** は付けない（%s）" % tag)
        check(nfc(str(target)) in ww and "Edit(/%s/**)" % nfc(str(target)) in ee, "S17 .git ファイルの指す先のフォルダ（%s）が denyWrite と Edit の deny にある" % tag)
    # 足すリポジトリの .git がファイルのとき（相対の ../ で指す）
    fx, target = _gitfile_fixture(True)
    (fx["repo"] / ".git").rename(fx["repo"] / "git_moved_away")
    t2 = fx["root"] / "elsewhere" / "repo_gitdir"
    t2.mkdir(parents=True)
    (fx["repo"] / ".git").write_text("gitdir: ../../elsewhere/repo_gitdir\n", encoding="utf-8")
    s = ok_json(fx)
    ww = [nfc(x) for x in deny_write(s)]
    ee = [nfc(x) for x in deny_edit(s)]
    check(nfc(str(fx["repo"] / ".git")) in ww and "Edit(/%s)" % nfc(str(fx["repo"] / ".git")) in ee, "S17 足すリポジトリの .git ファイルが両方にある")
    check(nfc(os.path.realpath(str(t2))) in ww and "Edit(/%s/**)" % nfc(os.path.realpath(str(t2))) in ee, "S17 足すリポジトリの .git ファイルの指す先（相対の ../）が両方にある")
    # 使えない形は終了コード 1・出力なし（S05）
    notdir = str(fx["home"] / "CLAUDE.md")
    cases = (
        (b"", "空"), (b"not a gitdir line\n", "形が違う"), (b"gitdir: \n", "先が空"), (b"gitdir: nowhere/none\n", "先が無い"),
        (b"gitdir: /\n", "先が /"), (("gitdir: %s\n" % notdir).encode("utf-8"), "先がフォルダでない"), (b"\xff\xfe\n", "読めない文字"),
    )
    for data, why in cases:
        fy, _t = _gitfile_fixture(True, content=data)
        rc, out, err = run(fy)
        check(rc == 1 and out == "" and err.startswith("sandbox_settings:"), "S17・S05 使えない .git ファイル（%s）は作らない rc=%s" % (why, rc))
        check(SECRET not in err, "エラーに URL が出ない")
    # 足すリポジトリ側の使えない .git ファイル
    fz = mkfixture()
    (fz["repo"] / ".git").rename(fz["repo"] / "git_moved_away")
    (fz["repo"] / ".git").write_text("garbage\n", encoding="utf-8")
    rc, out, err = run(fz)
    check(rc == 1 and out == "", "S17・S05 足すリポジトリの使えない .git ファイルも作らない rc=%s" % rc)


# --- 14. S23：目印は guard だけ守る（親は守らない）---
def test_canary_guard_only():
    fx = mkfixture()
    s = ok_json(fx)
    ww = [nfc(x) for x in deny_write(s)]
    ee = [nfc(x) for x in deny_edit(s)]
    g = nfc(str(fx["home"] / ".ai-bunshin-canary-dir/guard"))
    par = nfc(str(fx["home"] / ".ai-bunshin-canary-dir"))
    check(g in ww and "Edit(/%s/**)" % g in ee, "S23 guard が denyWrite と Edit の deny にある")
    check(par not in ww and "Edit(/%s/**)" % par not in ee and "Edit(/%s)" % par not in ee, "S23 親の .ai-bunshin-canary-dir は守らない")
    spec = json.loads(PATHS_JSON.read_text(encoding="utf-8"))
    cg = [e for e in spec["entries"] if e["id"] == "S23-canary-guard"]
    check(len(cg) == 1 and cg[0]["path"] == ".ai-bunshin-canary-dir/guard" and cg[0]["kind"] == "dir", "S23 一覧の項目（id・path・kind）")
    check(all(e["path"] != ".ai-bunshin-canary-dir" for e in spec["entries"]), "S23 一覧に親そのものが無い")


# --- 15. S24：worktree の commondir も守る ---
def _commondir_fixture(content, make_target=True, as_dir=False):
    """本人の .git をファイル（gitdir:）にし、指す先に commondir を置く。本体の .git は本人のフォルダの外の作り物"""
    fx, target = _gitfile_fixture(True)
    common = fx["root"] / "elsewhere" / "main_repo" / ".git"
    if make_target:
        common.mkdir(parents=True)
    cdfile = target / "commondir"
    if as_dir:
        cdfile.mkdir()
    elif content is not None:
        cdfile.write_bytes(content.replace("{ABS}", str(common)).encode("utf-8") if isinstance(content, str) else content)
    return fx, target, common


def test_commondir():
    # 絶対・相対（gitdir からの ../..）・改行なし
    rel = "../../main_repo/.git"
    for content, tag in (("{ABS}\n", "絶対"), (rel + "\n", "相対"), ("{ABS}", "改行なし"), (rel + "\r\n", "CRLF")):
        fx, target, common = _commondir_fixture(content)
        s = ok_json(fx)
        ww = [nfc(x) for x in deny_write(s)]
        ee = [nfc(x) for x in deny_edit(s)]
        c = nfc(os.path.realpath(str(common)))
        check(c in ww and "Edit(/%s/**)" % c in ee, "S24 commondir（%s）の指す先が denyWrite と Edit の deny にある" % tag)
        check(nfc(str(target)) in ww, "S24 gitdir の指す先も今までどおりある（%s）" % tag)
    # 足すリポジトリ（X12）の worktree にも commondir
    fx, target, common = _commondir_fixture("{ABS}\n")
    (fx["repo"] / ".git").rename(fx["repo"] / "git_moved_away")
    t2 = fx["root"] / "elsewhere" / "repo_gitdir"
    t2.mkdir(parents=True)
    c2 = fx["root"] / "elsewhere" / "main_hp" / ".git"
    c2.mkdir(parents=True)
    (t2 / "commondir").write_text(str(c2) + "\n", encoding="utf-8")
    (fx["repo"] / ".git").write_text("gitdir: ../../elsewhere/repo_gitdir\n", encoding="utf-8")
    s = ok_json(fx)
    check(nfc(os.path.realpath(str(c2))) in [nfc(x) for x in deny_write(s)], "S24 足すリポジトリの commondir の指す先も守る")
    # 無いときは今のまま（余計な項目が増えない）
    fx0, t0 = _gitfile_fixture(True)
    s0 = ok_json(fx0)
    check(not any("main_repo" in x for x in deny_write(s0)), "S24 commondir が無ければ増えない")
    # 作らない（終了コード 1・出力なし。S05 と同じ側）
    cases = (
        (b"", "空", True, False), (b"\n", "改行だけ", True, False), (b"\xff\xfe\n", "読めない文字", True, False),
        ("{ABS}\n", "指す先が無い", False, False), (b"/\n", "指す先が /", True, False),
        (None, "commondir がフォルダ（読めない）", True, True), (b"nowhere/none\n", "指す先が無い（相対）", True, False),
    )
    for data, why, mk, as_dir in cases:
        fy, _t, _c = _commondir_fixture(data, make_target=mk, as_dir=as_dir)
        rc, out, err = run(fy)
        check(rc == 1 and out == "" and err.startswith("sandbox_settings:"), "S24・S05 commondir が使えない（%s）は作らない rc=%s" % (why, rc))
        check(SECRET not in err, "エラーに URL が出ない（commondir）")
    # 指す先がファイル
    fz, tz, cz = _commondir_fixture("{ABS}\n", make_target=False)
    cz.parent.mkdir(parents=True)
    cz.write_text("x", encoding="utf-8")
    rc, out, err = run(fz)
    check(rc == 1 and out == "", "S24・S05 commondir の指す先がフォルダでない rc=%s" % rc)


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

tmproot = os.path.realpath(tempfile.gettempdir())
for d in TMP_DIRS:   # 自分が作った sbxtest_* だけ片付ける（本物の本人のフォルダ・~/.claude には触れない）
    if str(d).startswith(tmproot + os.sep) and d.name.startswith("sbxtest_"):
        shutil.rmtree(str(d), ignore_errors=True)
leftover = [d for d in TMP_DIRS if d.exists()]
if leftover:
    fail += 1
    print("FAIL 一時フォルダが残っている", leftover[:3])
print("%d checks, %d failed" % (count, fail))
sys.exit(1 if fail else 0)
