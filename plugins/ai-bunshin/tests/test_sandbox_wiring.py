"""自動実行の入口（scripts/auto/daily_cycle.sh）と囲いの設定（sandbox_settings.py）のつなぎのテスト。T119 G3（決定 S01・S03・S05・S14・W1〜W7）。
一時フォルダに本人のフォルダとプラグインのコピーを作り、daily_cycle.sh（本物のコピー）を、作り物の claude（受け取った引数と環境を記録するだけ）・
osascript・security（キーチェーンの代わり）で通して動かす。本物の launchd・claude・キーチェーン・本物の本人のフォルダは使わない。

- ① 実行（do）の段に --settings（囲い）と Bash(python3:*) が渡る
- ② 計画・振り返りの段には渡らない
- ③ 囲いの設定を作れない（終了コード1・道具が無い・形が違う）ときは、どちらも渡らず、今の許可（update_dashboard.py・lock_check.py の完全一致）だけで動く
- ④ 計画から続けて実行に入るときも、実行の段にだけ ① と同じものが渡る
- ⑤ claude の環境に AI_BUNSHIN_CALENDAR_URL が無い（親の環境に置かれていても消す）。URL は囲いの設定を作る道具にだけ渡り、通信の許可の host だけになる
- ⑥ ログ・出力に URL・パスが出ない（作れなかった理由の文面にパスや URL が入っていても出さない）
- W3：許可はワイルドカードなし（完全なパス。リンク経由で呼ばれたときは両方の名前）
- W5：TOOLS・DENY は T141 の白リストが読める形のまま（update_dashboard.py --plan-context の節が「読めませんでした」にならない）
- W7：--add-dir は囲いの守る先と同じ判定（sandbox_settings.py --print-add-dirs）
実行：python3 tests/test_sandbox_wiring.py（失敗があれば終了コード1）。CYCLE_UNDER_TEST に別の版の daily_cycle.sh を指すと、その版で流せる"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.abspath(os.path.join(HERE, "..", "scripts"))
CYCLE = os.environ.get("CYCLE_UNDER_TEST") or os.path.join(SCRIPTS, "auto", "daily_cycle.sh")
BASE = os.path.realpath(tempfile.mkdtemp(prefix="sbxwiring_"))
FAKE_HOME = os.path.join(BASE, "fakehome")
os.makedirs(FAKE_HOME)

SECRET = "SECRETTOKEN-7c1e5d"
CAL_URL = "https://calendar.example.org/calendar/ical/a%40b.c/private-" + SECRET + "/basic.ics"

names, fails = [], 0


def case(fn):
    names.append(fn.__name__)
    try:
        fn()
        print(f"  ok   {fn.__name__}")
    except AssertionError as e:
        global fails
        fails += 1
        print(f"  FAIL {fn.__name__}: {e}")
    except Exception as e:  # noqa: BLE001
        fails += 1
        print(f"  FAIL {fn.__name__}: {e.__class__.__name__}: {e}")
    return fn


# update_dashboard.py の代わり。段階ごとの最初の1行だけ本物らしく返す
STUB = '''import os, sys, time
a = sys.argv[1:]
if "--session" in a:
    sys.exit(0)
home = os.environ["AI_BUNSHIN_HOME"]
if "--plan-context" in a:
    if os.environ.get("STUB_PHASE") == "do":
        print("作成済み：テスト"); sys.exit(0)
    n = os.path.join(home, "plan_calls")
    c = int(open(n).read()) if os.path.exists(n) else 0
    open(n, "w").write(str(c + 1))
    if c == 0:
        print("OPEN")
    else:
        print("OPEN" if os.environ.get("STUB_NO_PLAN") else "今日の計画は作成済み")
if "--review-context" in a:
    print("OPEN")
    print("議事録の保存先: 01_スプリント/S1/daily/" + time.strftime("%Y%m%d") + "_振り返り.md")
'''

# claude の代わり：受け取った引数と、環境（URL らしきものがあるか）を記録するだけ
FAKE_CLAUDE = '''#!{py}
import json, os, sys
rec = os.environ["FAKE_RECORD"]
env = dict(os.environ)
with open(os.path.join(rec, "calls.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps({{
        "args": sys.argv[1:],
        "has_url_var": "AI_BUNSHIN_CALENDAR_URL" in env,
        "secret_in_env": any("{secret}" in v for v in env.values()),
        "secret_in_args": any("{secret}" in a for a in sys.argv[1:]),
    }}, ensure_ascii=False) + "\\n")
print("done")
'''

# security（キーチェーン）の代わり：rec/keychain_url ファイルに URL があればそれを出す（環境変数には置かない。claude の環境を汚さないため）。呼ばれた回数を記録する
FAKE_SECURITY = '''#!/bin/sh
echo x >> "$FAKE_RECORD/security_calls"
if [ -s "$FAKE_RECORD/keychain_url" ]; then cat "$FAKE_RECORD/keychain_url"; exit 0; fi
exit 44
'''

CAL_CFG = {"calendar": {"type": "ics", "keychain": "ai-bunshin-calendar", "show": "title"}}


def make(name, cfg=None, plugin_files=None, repo=None):
    """一時フォルダに、プラグインのコピー・本人のフォルダ・作り物の claude / osascript / security を作る"""
    d = os.path.join(BASE, name)
    plugin = os.path.join(d, "plugin")
    os.makedirs(os.path.join(plugin, "scripts", "auto"))
    shutil.copy(CYCLE, os.path.join(plugin, "scripts", "auto", "daily_cycle.sh"))
    shutil.copy(os.path.join(SCRIPTS, "auto", "run_limited.py"), os.path.join(plugin, "scripts", "auto", "run_limited.py"))
    for f in ("lock_check.py", "watch_check.py", "ng_guard.py", "ng_guard_legacy.py", "sandbox_settings.py", "protected_paths.json", "calendar_today.py"):
        shutil.copy(os.path.join(SCRIPTS, f), os.path.join(plugin, "scripts", f))
    open(os.path.join(plugin, "scripts", "update_dashboard.py"), "w", encoding="utf-8").write(STUB)
    for rel, body in (plugin_files or {}).items():   # プラグインのコピーの一部を差し替える（None なら消す）
        p = os.path.join(plugin, "scripts", rel)
        if body is None:
            os.remove(p)
        else:
            open(p, "w", encoding="utf-8").write(body)
    home = os.path.join(d, "owner")
    for sub in ("設定", "scripts/auto", "00_タスク管理/data", "03_インプット"):
        os.makedirs(os.path.join(home, sub))
    c = {"ai_name": "テストAI"}
    c.update(cfg if cfg is not None else CAL_CFG)
    if repo:
        c["dev"] = {"projects": [{"name": "外", "path": repo}, {"name": "中", "path": os.path.join(home, "03_インプット")}]}
    json.dump(c, open(os.path.join(home, "設定", "config.json"), "w", encoding="utf-8"), ensure_ascii=False)
    open(os.path.join(home, "00_タスク管理", "data", "tasks.json"), "w").write("{}")
    bindir = os.path.join(d, "bin")
    rec = os.path.join(d, "rec")
    os.makedirs(bindir)
    os.makedirs(rec)
    open(os.path.join(bindir, "claude"), "w").write(FAKE_CLAUDE.format(py=sys.executable, secret=SECRET))
    open(os.path.join(bindir, "osascript"), "w").write("#!/bin/sh\nexit 0\n")
    open(os.path.join(bindir, "security"), "w").write(FAKE_SECURITY)
    for f in ("claude", "osascript", "security"):
        os.chmod(os.path.join(bindir, f), 0o755)
    return dict(d=d, plugin=plugin, home=home, bindir=bindir, rec=rec)


def run(c, phase, keychain_url=CAL_URL, extra_env=None, stub_phase="plan", cycle=None, timeout=120):
    env = {k: v for k, v in os.environ.items() if k not in ("AI_BUNSHIN_AUTO_RUN", "CLAUDE_PROJECT_DIR", "AI_BUNSHIN_CALENDAR_URL")}
    env.update({"HOME": FAKE_HOME, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull})
    env["AI_BUNSHIN_HOME"] = c["home"]
    env["PATH"] = c["bindir"] + os.pathsep + env.get("PATH", "")
    env["FAKE_RECORD"] = c["rec"]
    env["STUB_PHASE"] = stub_phase
    if keychain_url:
        open(os.path.join(c["rec"], "keychain_url"), "w").write(keychain_url + "\n")
    env.update(extra_env or {})
    return subprocess.run(["/bin/zsh", cycle or os.path.join(c["plugin"], "scripts", "auto", "daily_cycle.sh"), phase],
                          capture_output=True, text=True, env=env, timeout=timeout)


def calls(c):
    p = os.path.join(c["rec"], "calls.jsonl")
    return [json.loads(ln) for ln in open(p, encoding="utf-8").read().splitlines()] if os.path.exists(p) else []


def log_of(c):
    d = os.path.join(c["home"], "scripts", "auto", "logs")
    return "".join(open(os.path.join(d, f), encoding="utf-8").read() for f in sorted(os.listdir(d))) if os.path.isdir(d) else ""


def opt(call, flag):
    a = call["args"]
    return a[a.index(flag) + 1] if flag in a else None


def has_python(call):
    return "Bash(python3:*)" in (opt(call, "--allowedTools") or "").split(",")


def has_settings(call):
    return "--settings" in call["args"]


def no_wildcard(call):
    t = opt(call, "--allowedTools") or ""
    return "*update_dashboard.py*" not in t and "*lock_check.py*" not in t


def exact_tools(c, call):
    """今の許可（完全なパス。引用符なし・ありの両方）が入っている"""
    t = (opt(call, "--allowedTools") or "").split(",")
    root = os.path.realpath(c["plugin"])
    want = []
    for s in ("update_dashboard.py", "lock_check.py"):
        want += [f"Bash(python3 {root}/scripts/{s}:*)", f'Bash(python3 "{root}/scripts/{s}":*)']
    return [w for w in want if w not in t]


def good_settings(c, call):
    s = json.loads(opt(call, "--settings"))
    sb = s["sandbox"]
    assert sb["enabled"] is True and sb["failIfUnavailable"] is True and sb["allowUnsandboxedCommands"] is False, sb
    dw = sb["filesystem"]["denyWrite"]
    assert os.path.join(c["home"], "設定") in dw or any(x.endswith("/設定") for x in dw), "設定が守られていない"
    assert any(x.endswith("/scripts") and "owner" in x for x in dw), "本人の scripts/ が守られていない"
    return s


def all_text(c, r):
    return r.stdout + r.stderr + log_of(c) + json.dumps(calls(c), ensure_ascii=False).replace("calendar.example.org", "")


@case
def t1_do_gets_settings_and_python():
    c = make("t1")
    r = run(c, "do", stub_phase="do")
    assert r.returncode == 0, (r.returncode, r.stderr[-300:], log_of(c)[-500:])
    cs = calls(c)
    assert len(cs) == 1, cs
    assert has_settings(cs[0]) and has_python(cs[0]), cs[0]["args"]
    s = good_settings(c, cs[0])
    assert s["sandbox"]["network"]["allowedDomains"] == ["calendar.example.org"], s["sandbox"]["network"]
    assert "囲いの設定を作れたので" in log_of(c), log_of(c)
    assert not exact_tools(c, cs[0]), "完全一致の許可が欠けている: %s" % exact_tools(c, cs[0])
    assert no_wildcard(cs[0]), opt(cs[0], "--allowedTools")


@case
def t2_plan_and_review_get_neither():
    c = make("t2a")
    r = run(c, "plan", extra_env={"STUB_NO_PLAN": "1"})   # 計画が作られなかった日＝実行には入らない
    assert r.returncode == 0, (r.returncode, r.stderr[-300:], log_of(c)[-400:])
    cs = calls(c)
    assert len(cs) == 1 and "/ai-bunshin:daily-plan" in cs[0]["args"], cs
    assert not has_settings(cs[0]) and not has_python(cs[0]), cs[0]["args"]
    assert "WebFetch" not in opt(cs[0], "--allowedTools") and not exact_tools(c, cs[0]) and no_wildcard(cs[0])
    assert "囲い" not in log_of(c), "計画の段で囲いを作ろうとした: " + log_of(c)
    assert not os.path.exists(os.path.join(c["rec"], "security_calls")), "計画の段でキーチェーンを読んだ"
    c = make("t2b")
    r = run(c, "review", stub_phase="review")
    assert r.returncode == 0, (r.returncode, r.stderr[-300:], log_of(c)[-400:])
    cs = calls(c)
    assert len(cs) == 1 and "/ai-bunshin:daily-review" in cs[0]["args"], cs
    assert not has_settings(cs[0]) and not has_python(cs[0]) and "囲い" not in log_of(c)
    assert not os.path.exists(os.path.join(c["rec"], "security_calls")), "振り返りの段でキーチェーンを読んだ"


@case
def t3_sandbox_failure_falls_back_to_exact_permissions():
    # (a) 本物の sandbox_settings.py が終了コード1：利用者の known_marketplaces.json の場所が相対パス（使えない形）
    c = make("t3a")
    os.makedirs(os.path.join(FAKE_HOME, ".claude", "plugins"), exist_ok=True)
    km = os.path.join(FAKE_HOME, ".claude", "plugins", "known_marketplaces.json")
    open(km, "w", encoding="utf-8").write(json.dumps({"m": {"source": {"source": "directory", "path": "rel/dir"}, "installLocation": "rel/dir"}}))
    try:
        r = run(c, "do", stub_phase="do")
    finally:
        os.remove(km)
    assert r.returncode == 0, (r.returncode, r.stderr[-300:], log_of(c)[-400:])
    cs = calls(c)
    assert len(cs) == 1, cs
    assert not has_settings(cs[0]) and not has_python(cs[0]), cs[0]["args"]
    assert not exact_tools(c, cs[0]) and no_wildcard(cs[0]), opt(cs[0], "--allowedTools")
    lg = log_of(c)
    assert "囲いの設定を作れなかったので、Python は許さず今の許可で動かす（理由：" in lg and "マーケットプレイス" in lg, lg
    assert "WebFetch" in opt(cs[0], "--allowedTools"), "実行の段の今の許可（WebFetch など）まで消えた"
    # (b) 道具が無い／(c) 終了コード0でも形が違う
    for tag, files in (("b", {"sandbox_settings.py": None}),
                       ("c", {"sandbox_settings.py": "print('not json')\n"}),
                       ("d", {"sandbox_settings.py": "print('{\"sandbox\": {\"enabled\": false}}')\n"}),
                       ("e", {"sandbox_settings.py": "import sys\nprint('{\"sandbox\": {\"enabled\": true}}')\nsys.exit(3)\n"})):
        c = make("t3" + tag, plugin_files=files)
        r = run(c, "do", stub_phase="do")
        assert r.returncode == 0, (tag, r.returncode, r.stderr[-300:], log_of(c)[-400:])
        cs = calls(c)
        assert len(cs) == 1 and not has_settings(cs[0]) and not has_python(cs[0]), (tag, cs)
        assert not exact_tools(c, cs[0]) and no_wildcard(cs[0]), tag
        assert "囲いの設定を作れなかったので" in log_of(c), (tag, log_of(c))


@case
def t4_plan_then_do_only_do_gets_it():
    c = make("t4")
    r = run(c, "plan")
    assert r.returncode == 0, (r.returncode, r.stderr[-300:], log_of(c)[-500:])
    cs = calls(c)
    assert len(cs) == 2, cs
    plan, do = cs
    assert "/ai-bunshin:daily-plan" in plan["args"] and "/ai-bunshin:daily-do" in do["args"], (plan["args"][:1], do["args"][:1])
    assert not has_settings(plan) and not has_python(plan), "計画の段に囲い・Python が渡った"
    assert has_settings(do) and has_python(do), do["args"]
    good_settings(c, do)
    assert "WebFetch" in opt(do, "--allowedTools") and "WebFetch" not in opt(plan, "--allowedTools")
    assert not exact_tools(c, do) and not exact_tools(c, plan) and no_wildcard(do) and no_wildcard(plan)
    # 続けて実行に入るときも、囲いを作れなければ、実行の段にも渡らない（計画は今のまま）
    c = make("t4b", plugin_files={"sandbox_settings.py": "import sys\nsys.stderr.write('sandbox_settings: 作れません\\n')\nsys.exit(1)\n"})
    r = run(c, "plan")
    cs = calls(c)
    assert r.returncode == 0 and len(cs) == 2 and not any(has_settings(x) or has_python(x) for x in cs), cs


@case
def t5_calendar_url_not_in_claude_env():
    # 親の環境に URL が置かれていても、claude には渡らない。URL は囲いの設定を作る道具にだけ渡り、host だけになる
    c = make("t5")
    r = run(c, "do", stub_phase="do", extra_env={"AI_BUNSHIN_CALENDAR_URL": "https://parent.example.net/" + SECRET})
    cs = calls(c)
    assert r.returncode == 0 and len(cs) == 1, (r.returncode, cs, log_of(c)[-300:])
    assert cs[0]["has_url_var"] is False, "claude の環境に AI_BUNSHIN_CALENDAR_URL がある"
    assert cs[0]["secret_in_env"] is False and cs[0]["secret_in_args"] is False, "claude の環境・引数に URL が入っている"
    s = good_settings(c, cs[0])
    assert s["sandbox"]["network"]["allowedDomains"] == ["calendar.example.org"], "キーチェーンの URL の host が渡っていない（親の環境の値は使わない）: %s" % s["sandbox"]["network"]
    assert os.path.exists(os.path.join(c["rec"], "security_calls")), "キーチェーンの代わり（security）を呼んでいない"
    # キーチェーンから取れないときは、URL を付けずに作る（通信は全部止まる）
    c = make("t5b")
    r = run(c, "do", stub_phase="do", keychain_url="")
    cs = calls(c)
    assert r.returncode == 0 and len(cs) == 1 and has_settings(cs[0]) and has_python(cs[0]), (r.returncode, cs)
    assert json.loads(opt(cs[0], "--settings"))["sandbox"]["network"]["allowedDomains"] == [], "URL が取れないのに通信を許している"
    assert cs[0]["has_url_var"] is False
    # カレンダーをつないでいない人は、キーチェーンを読まない
    c = make("t5c", cfg={"owner": "x"})
    r = run(c, "do", stub_phase="do")
    cs = calls(c)
    assert r.returncode == 0 and len(cs) == 1 and has_settings(cs[0]), (r.returncode, cs)
    assert not os.path.exists(os.path.join(c["rec"], "security_calls")), "カレンダーをつないでいないのにキーチェーンを読んだ"
    assert json.loads(opt(cs[0], "--settings"))["sandbox"]["network"]["allowedDomains"] == []


@case
def t6_log_has_no_url_or_path():
    for tag, files in (("ok", None),
                       ("ng1", {"sandbox_settings.py": "import sys\nsys.stderr.write('sandbox_settings: 失敗 /Users/x/secret https://h.example/%s\\n')\nsys.exit(1)\n" % SECRET}),
                       ("ng2", {"sandbox_settings.py": "import sys\nsys.stderr.write('sandbox_settings: 場所 %s\\n')\nsys.exit(1)\n" % "ROOTPLACEHOLDER"}),
                       ("ng3", {"sandbox_settings.py": "import os,sys\nsys.stderr.write('sandbox_settings: 値 ' + os.environ.get('AI_BUNSHIN_CALENDAR_URL','') + '\\n')\nsys.exit(1)\n"})):
        c = make("t6" + tag, plugin_files=files)
        if tag == "ng2":   # 本人のフォルダのパスが理由の文に入っている
            p = os.path.join(c["plugin"], "scripts", "sandbox_settings.py")
            open(p, "w", encoding="utf-8").write(open(p, encoding="utf-8").read().replace("ROOTPLACEHOLDER", c["home"]))
        r = run(c, "do", stub_phase="do")
        assert r.returncode == 0, (tag, r.returncode, r.stderr[-300:])
        text = r.stdout + r.stderr + log_of(c)
        assert SECRET not in text and "calendar.example.org/calendar" not in text, "%s: ログ・出力に URL が出ている" % tag
        for ln in log_of(c).splitlines():
            if "囲い" in ln:
                assert c["home"] not in ln and "/Users/" not in ln and "http" not in ln, "%s: 囲いの行にパス・URL: %s" % (tag, ln)
        assert not any(c["secret_in_env"] for c in calls(c)), tag
    # 本物の道具が止めたときの理由の文面（パスを含まない）は、そのままログに残る
    c = make("t6real")
    os.makedirs(os.path.join(FAKE_HOME, ".claude", "plugins"), exist_ok=True)
    km = os.path.join(FAKE_HOME, ".claude", "plugins", "known_marketplaces.json")
    open(km, "w", encoding="utf-8").write(json.dumps({"m": {"source": {"source": "directory", "path": "rel"}}}))
    try:
        r = run(c, "do", stub_phase="do")
    finally:
        os.remove(km)
    assert "理由：マーケットプレイス（m）の場所が使えない形です" in log_of(c), log_of(c)


@case
def t7_permissions_exact_and_via_link():
    c = make("t7")
    link = os.path.join(c["d"], "plugin_link")
    os.symlink(c["plugin"], link)   # installPath がリンクのとき：PLUGIN_ROOT（実体）と呼ばれた名前が違う
    r = run(c, "do", stub_phase="do", cycle=os.path.join(link, "scripts", "auto", "daily_cycle.sh"))
    cs = calls(c)
    assert r.returncode == 0 and len(cs) == 1, (r.returncode, cs, log_of(c)[-300:])
    t = (opt(cs[0], "--allowedTools") or "").split(",")
    for root in (os.path.realpath(c["plugin"]), link):
        for s in ("update_dashboard.py", "lock_check.py"):
            for form in (f"Bash(python3 {root}/scripts/{s}:*)", f'Bash(python3 "{root}/scripts/{s}":*)'):
                assert form in t, "許可が無い: " + form
    assert no_wildcard(cs[0]) and has_python(cs[0]) and has_settings(cs[0])
    s = json.loads(opt(cs[0], "--settings"))
    dw = s["sandbox"]["filesystem"]["denyWrite"]
    assert os.path.realpath(c["plugin"]) in dw and link in dw, "プラグインの元（リンクの名前と実体の両方）が守られていない"


@case
def t8_add_dirs_same_rule_as_sandbox():
    outside = os.path.join(BASE, "t8_repos", "hp")
    os.makedirs(os.path.join(outside, ".git", "hooks"))
    open(os.path.join(outside, ".git", "config"), "w").write("")
    c = make("t8", repo=outside)
    # 本人のフォルダの中へのリンクで入る先は「中」。囲いも --add-dir も対象外にそろう
    inside_link = os.path.join(BASE, "t8_repos", "inside_link")
    os.symlink(os.path.join(c["home"], "03_インプット"), inside_link)
    cfg = json.load(open(os.path.join(c["home"], "設定", "config.json"), encoding="utf-8"))
    cfg["dev"]["projects"].append({"name": "リンク", "path": inside_link})
    json.dump(cfg, open(os.path.join(c["home"], "設定", "config.json"), "w", encoding="utf-8"), ensure_ascii=False)
    r = run(c, "do", stub_phase="do")
    cs = calls(c)
    assert r.returncode == 0 and len(cs) == 1, (r.returncode, cs)
    a = cs[0]["args"]
    adds = [a[i + 1] for i, x in enumerate(a) if x == "--add-dir"]
    assert adds == [outside], adds
    s = json.loads(opt(cs[0], "--settings"))
    dw = s["sandbox"]["filesystem"]["denyWrite"]
    assert os.path.join(outside, ".git", "hooks") in dw and os.path.join(outside, ".git", "config") in dw, "--add-dir の先の .git が囲いで守られていない"
    assert not any("inside_link" in x for x in dw)
    # 計画の段でも --add-dir は同じ（今までどおり）
    c2 = make("t8b", repo=outside)
    r = run(c2, "plan", extra_env={"STUB_NO_PLAN": "1"})
    cs = calls(c2)
    a = cs[0]["args"]
    assert [a[i + 1] for i, x in enumerate(a) if x == "--add-dir"] == [outside], a


@case
def t9_plan_tools_section_still_readable():
    """W5：TOOLS・DENY の代入が T141 の白リストで読める形のまま。節が「読めませんでした」にならず、完全一致の許可が出る"""
    home = os.path.join(BASE, "t9_home")
    for d in ("設定", "00_タスク管理/data"):
        os.makedirs(os.path.join(home, d), exist_ok=True)
    json.dump({"owner": "テスト", "owner_call": "テストさん", "ai_name": "テストAI", "departments": ["総務"]},
              open(os.path.join(home, "設定", "config.json"), "w", encoding="utf-8"), ensure_ascii=False)
    json.dump({"project": {"name": "テスト", "daily_capacity_default": 1.0, "holidays": []}, "daily_sprints": [], "sprints": [], "tasks": []},
              open(os.path.join(home, "00_タスク管理", "data", "tasks.json"), "w", encoding="utf-8"), ensure_ascii=False)
    root = os.path.join(BASE, "t9_plugin")
    shutil.copytree(SCRIPTS, os.path.join(root, "scripts"), ignore=shutil.ignore_patterns("__pycache__", "*.bak*"))
    shutil.copy(CYCLE, os.path.join(root, "scripts", "auto", "daily_cycle.sh"))
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    env.update({"AI_BUNSHIN_HOME": home, "HOME": FAKE_HOME})
    r = subprocess.run([sys.executable, os.path.join(root, "scripts", "update_dashboard.py"), "--plan-context", "--today", "2026-11-02"],
                       capture_output=True, text=True, cwd=home, env=env)
    assert r.returncode == 0, r.stderr[-300:]
    out = r.stdout
    assert "## 自動実行で使える道具・書けない場所" in out
    sec = out[out.index("## 自動実行で使える道具・書けない場所"):]
    assert "読めませんでした" not in sec, sec
    do_line = [ln for ln in sec.splitlines() if ln.startswith("- 実行　使える道具")][0]
    assert "lock_check.py" in do_line and "*update_dashboard.py*" not in do_line and "*lock_check.py*" not in do_line, do_line


print(f"\n{len(names) - fails}/{len(names)} passed")
sys.exit(1 if fails else 0)
