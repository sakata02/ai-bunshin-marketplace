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
- G4a：囲いのカナリア（k1〜k11。Python を許すのは、点検が6項目すべて止まったと返した日だけ）
- G4a の直し：目印フォルダ（.ai-bunshin-canary-dir）を囲いの外で前もって作る（k13）・点検が通らない日は通知を1行（k12）
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
if "--today-status" in a:
    print("計画済み"); sys.exit(0)
if "--plan-context" in a:
    if os.environ.get("STUB_SKIP_PLANNED"):   # 9時前に手動で計画した日：計画は作成済み・未実行
        print("SKIP: 今日の計画は作成済み"); sys.exit(0)
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
FAKE_CLAUDE = '''#!__PY__
import json, os, re, shlex, subprocess, sys, time
rec = os.environ["FAKE_RECORD"]
env = dict(os.environ)
args = sys.argv[1:]
prompt = args[args.index("-p") + 1] if "-p" in args else ""
info = {
    "marker_ready": os.path.isdir(os.path.join(os.environ["AI_BUNSHIN_HOME"], ".ai-bunshin-canary-dir", "inner")),
    "args": args,
    "has_url_var": "AI_BUNSHIN_CALENDAR_URL" in env,
    "secret_in_env": any("__SECRET__" in v for v in env.values()),
    "secret_in_args": any("__SECRET__" in a for a in args),
}
CHECKS = ["write", "parent_mv", "case", "network", "keychain", "env_url"]
if "囲いの点検" in prompt:
    # 囲いの点検の呼び出し（calls.jsonl には入れない）。FAKE_CANARY で、点検の結果を作り物にする
    with open(os.path.join(rec, "canary_calls.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(info, ensure_ascii=False) + "\\n")
    mode = os.environ.get("FAKE_CANARY", "pass")
    m = re.search(r'--nonce "([^"]+)" --out "([^"]+)"', prompt)
    nonce, out = m.group(1), m.group(2)
    def put(checks, nonce=nonce, **kw):
        d = {"v": 1, "nonce": nonce, "checks": checks}
        d.update(kw)
        json.dump(d, open(out, "w"))
    if mode == "pass":
        put({k: "blocked" for k in CHECKS})
    elif mode.startswith(("leak:", "error:", "skipped:")):
        state, _, items = mode.partition(":")
        state = {"leak": "leaked"}.get(state, state)
        put({k: (state if k in items.split(",") else "blocked") for k in CHECKS})
    elif mode == "stale":
        put({k: "blocked" for k in CHECKS}, nonce="OLD")
    elif mode == "restore_failed":
        put({k: "blocked" for k in CHECKS}, restore_failed=True)
    elif mode == "garbage":
        open(out, "w").write("not json")
    elif mode == "hang":
        time.sleep(60)
    elif mode == "fail":
        sys.exit(1)
    elif mode in ("fence", "nofence"):
        # 本物の点検の道具を、プロンプトのコマンドのまま動かす（テスト用に、キーチェーンの代わりと通信の確かめ先だけ足す）。fence は seatbelt の下で
        cmd = shlex.split(prompt.splitlines()[1]) + json.loads(os.environ["FAKE_CANARY_EXTRA"])
        if mode == "fence":
            sj = json.loads(args[args.index("--settings") + 1])
            lines = ["(version 1)", "(allow default)", "(deny network*)"]
            lines += ['(deny file-write* (subpath "%s"))' % p for p in sj["sandbox"]["filesystem"]["denyWrite"]]
            prof = os.path.join(rec, "fence.sb")
            open(prof, "w").write("\\n".join(lines) + "\\n")
            cmd = ["sandbox-exec", "-f", prof] + cmd
        subprocess.run(cmd, stdin=subprocess.DEVNULL, timeout=100)
    print("完了")
    sys.exit(0)
if os.environ.get("FAKE_MAIN_FAIL_WITH_SETTINGS") and "--settings" in args:
    with open(os.path.join(rec, "calls.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(info, ensure_ascii=False) + "\\n")
    sys.exit(1)
with open(os.path.join(rec, "calls.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps(info, ensure_ascii=False) + "\\n")
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
    for f in ("lock_check.py", "watch_check.py", "ng_guard.py", "ng_guard_legacy.py", "sandbox_settings.py", "protected_paths.json", "calendar_today.py", "sandbox_canary.py"):
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
    open(os.path.join(bindir, "claude"), "w").write(FAKE_CLAUDE.replace("__PY__", sys.executable).replace("__SECRET__", SECRET))
    open(os.path.join(bindir, "osascript"), "w").write('#!/bin/sh\necho "$*" >> "$FAKE_RECORD/notify.txt"\nexit 0\n')   # 通知の文面を記録する
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
    assert os.path.join(outside, ".git") in dw, "--add-dir の先の .git が丸ごと囲いで守られていない（T119 S17）"
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



# ---------- G4a：囲いのカナリア（Python を許す前に、囲いが効いているかを確かめる） ----------

CHECK_ITEMS = ["write", "parent_mv", "case", "network", "keychain", "env_url"]


def canary_calls(c):
    p = os.path.join(c["rec"], "canary_calls.jsonl")
    return [json.loads(ln) for ln in open(p, encoding="utf-8").read().splitlines()] if os.path.exists(p) else []


def fell_back(c, r, why=None):
    """Python も囲いも渡らず、今の許可（完全一致）のまま、実行の本体は動いている"""
    assert r.returncode == 0, (r.returncode, r.stderr[-300:], log_of(c)[-600:])
    cs = calls(c)
    assert len(cs) == 1, cs
    assert not has_settings(cs[0]) and not has_python(cs[0]), cs[0]["args"]
    assert not exact_tools(c, cs[0]) and no_wildcard(cs[0]), opt(cs[0], "--allowedTools")
    assert "WebFetch" in opt(cs[0], "--allowedTools")
    lg = log_of(c)
    assert "囲いの点検（カナリア）が通らなかったので、Python は許さず今の許可で動かす" in lg, lg
    if why:
        assert why in lg, (why, lg)
    return lg


@case
def k1_each_item_that_goes_through_stops_python():
    # ①〜⑥のどれか1つが通った（leaked）・確かめられなかった（error・skipped）とき、Python も囲いも許さない。項目名だけがログに出る
    for item in CHECK_ITEMS:
        for state, mode in (("leaked", "leak:" + item), ("error", "error:" + item), ("skipped", "skipped:" + item)):
            c = make("k1_%s_%s" % (item, state))
            r = run(c, "do", stub_phase="do", extra_env={"FAKE_CANARY": mode})
            lg = fell_back(c, r, "%s=%s" % (item, state))
            assert len(canary_calls(c)) == 1, canary_calls(c)
    # 複数
    c = make("k1_multi")
    r = run(c, "do", stub_phase="do", extra_env={"FAKE_CANARY": "leak:write,network,keychain"})
    fell_back(c, r, "write=leaked,network=leaked,keychain=leaked")


@case
def k2_all_blocked_is_the_only_way_python_is_allowed():
    c = make("k2")
    r = run(c, "do", stub_phase="do")   # 作り物の点検が全部 blocked を返す
    assert r.returncode == 0, (r.returncode, log_of(c)[-400:])
    cs = calls(c)
    assert len(cs) == 1 and has_settings(cs[0]) and has_python(cs[0]), cs
    assert "点検（カナリア）も全部止まったのを確かめて、Python を許して動かす" in log_of(c), log_of(c)
    cc = canary_calls(c)
    assert len(cc) == 1, cc
    # 点検の呼び出し：本番と同じ囲いの設定・同じ --add-dir。許す道具は点検の道具だけ（WebFetch・Python 全般・今の許可も付けない）。手数は小さく
    k = cc[0]
    assert opt(k, "--settings") == opt(cs[0], "--settings"), "点検と本番の囲いの設定が違う"
    tools = opt(k, "--allowedTools").split(",")
    canary_path = os.path.join(os.path.realpath(c["plugin"]), "scripts", "sandbox_canary.py")
    assert tools == ['Bash(python3 -I "%s":*)' % canary_path, "Bash(python3 -I %s:*)" % canary_path], tools
    assert "Bash(python3:*)" not in tools and not any("WebFetch" in t for t in tools)
    assert opt(k, "--disallowedTools") == opt(cs[0], "--disallowedTools")
    assert int(opt(k, "--max-turns")) <= 6 and opt(k, "--model") == "sonnet" and opt(k, "--permission-mode") == "acceptEdits"
    ka, ca_ = k["args"], cs[0]["args"]
    assert [ka[i + 1] for i, x in enumerate(ka) if x == "--add-dir"] == [ca_[i + 1] for i, x in enumerate(ca_) if x == "--add-dir"]
    # 点検は claude の中の環境にも URL を置かない
    assert k["has_url_var"] is False and k["secret_in_env"] is False and k["secret_in_args"] is False
    # 一時ファイルが残らない（設定の写し・結果）
    leftovers = [f for f in os.listdir(os.path.join(c["home"], "scripts", "auto", "logs")) if f.startswith(".out.")]
    leftovers += [f for f in os.listdir(os.path.join(c["home"], "00_タスク管理", "data")) if f.startswith(".sandbox_canary")]
    assert not leftovers, leftovers


@case
def k3_canary_not_run_or_not_trusted_falls_back():
    # 点検が動かなかった・結果が壊れている・前の実行のもの・時間切れ・claude の失敗・点検の道具が無い：どれも許さない
    for tag, mode, why in (("none", "none", "結果が無い（カナリアが動かなかった）"), ("garbage", "garbage", "結果の形が違う"),
                           ("stale", "stale", "結果が今回のものではない"), ("fail", "fail", "claude が失敗した（終了コード 1）"),
                           ("rf", "restore_failed", "parent_mv_restore_failed")):
        c = make("k3_" + tag)
        r = run(c, "do", stub_phase="do", extra_env={"FAKE_CANARY": mode})
        fell_back(c, r, why)
    c = make("k3_hang")
    r = run(c, "do", stub_phase="do", extra_env={"FAKE_CANARY": "hang", "AI_BUNSHIN_CANARY_SEC": "1"}, timeout=90)
    fell_back(c, r, "時間切れ")
    c = make("k3_nofile", plugin_files={"sandbox_canary.py": None})
    r = run(c, "do", stub_phase="do")
    fell_back(c, r, "点検の道具が無い")
    assert canary_calls(c) == [], "点検の道具が無いのに claude を起動した"


@case
def k4_canary_runs_only_when_settings_were_made_and_only_in_do():
    for tag, files in (("b", {"sandbox_settings.py": None}), ("c", {"sandbox_settings.py": "print('not json')\n"})):
        c = make("k4" + tag, plugin_files=files)
        r = run(c, "do", stub_phase="do")
        assert r.returncode == 0 and canary_calls(c) == [], (tag, canary_calls(c))
    c = make("k4p")
    r = run(c, "plan", extra_env={"STUB_NO_PLAN": "1"})
    assert r.returncode == 0 and canary_calls(c) == [], "計画の段で点検した"
    c = make("k4r")
    r = run(c, "review", stub_phase="review")
    assert r.returncode == 0 and canary_calls(c) == [], "振り返りの段で点検した"
    # 計画から続けて実行に入るとき：点検は実行の起動の前に1回だけ。計画には囲いも点検も無い
    c = make("k4d")
    r = run(c, "plan")
    cs, cc = calls(c), canary_calls(c)
    assert r.returncode == 0 and len(cs) == 2 and len(cc) == 1, (cs, cc)
    assert not has_settings(cs[0]) and has_settings(cs[1]) and has_python(cs[1])
    c = make("k4e")
    r = run(c, "plan", extra_env={"FAKE_CANARY": "leak:env_url"})
    cs = calls(c)
    assert r.returncode == 0 and len(cs) == 2 and not any(has_settings(x) or has_python(x) for x in cs), cs
    assert "env_url=leaked" in log_of(c)


@case
def k5_canary_log_has_no_paths_or_urls():
    for tag, mode in (("a", "leak:write,parent_mv,case,network,keychain,env_url"), ("b", "none"), ("c", "stale")):
        c = make("k5" + tag)
        r = run(c, "do", stub_phase="do", extra_env={"FAKE_CANARY": mode})
        text = all_text(c, r)
        assert SECRET not in text and "calendar.example.org/calendar" not in text, tag
        for ln in log_of(c).splitlines():
            if "点検" in ln or "囲い" in ln:
                assert c["home"] not in ln and "/Users/" not in ln and "http" not in ln, "%s: 点検の行にパス・URL: %s" % (tag, ln)


@case
def k6_leftover_hints_in_log():
    c = make("k6a")
    run(c, "do", stub_phase="do", extra_env={"FAKE_CANARY": "leak:write"})
    assert ".ai-bunshin-canary-" in log_of(c) and "空のファイルが残っているかもしれません" in log_of(c), log_of(c)
    c = make("k6b")
    run(c, "do", stub_phase="do", extra_env={"FAKE_CANARY": "leak:parent_mv"})
    assert "元の名前に戻してください" in log_of(c), log_of(c)
    c = make("k6c")
    run(c, "do", stub_phase="do", extra_env={"FAKE_CANARY": "leak:network"})
    assert "空のファイル" not in log_of(c) and "元の名前" not in log_of(c)


def sbx_ok():
    try:
        return subprocess.run(["sandbox-exec", "-p", "(version 1)(allow default)", "/usr/bin/true"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@case
def k7_end_to_end_with_real_canary_script():
    """daily_cycle.sh → 点検のプロンプト → 本物の点検の道具（seatbelt の下）→ 判定。囲いがあれば許し、無ければ許さない。実物（本人のフォルダの中身）は壊れない"""
    if not sbx_ok():
        print("(skip: sandbox-exec が使えない)", end=" ")
        return
    import socket
    ls = socket.socket()
    ls.bind(("127.0.0.1", 0))
    ls.listen(8)
    sec = os.path.join(BASE, "k7_sec")
    open(sec, "w").write("#!/bin/sh\nexit 44\n")
    os.chmod(sec, 0o755)
    extra = json.dumps(["--security-bin", sec, "--net-target", "127.0.0.1:%d" % ls.getsockname()[1]])

    def tree(c):
        out = {}
        for dp, dn, fn in os.walk(c["home"]):
            for x in fn:
                pth = os.path.join(dp, x)
                if ".ai-bunshin-canary-" in x or "/scripts/auto/" in pth or "/.git/" in pth:   # scripts/auto は囲いの外の daily_cycle.sh が書く（ログ・成功の印）
                    continue
                out[pth] = open(pth, "rb").read()
        return out
    c = make("k7a")
    open(os.path.join(c["home"], "CLAUDE.md"), "w").write("# 本人設定\n")
    before = tree(c)
    r = run(c, "do", stub_phase="do", extra_env={"FAKE_CANARY": "fence", "FAKE_CANARY_EXTRA": extra})
    assert r.returncode == 0, (r.returncode, log_of(c)[-600:])
    cs = calls(c)
    assert len(cs) == 1 and has_settings(cs[0]) and has_python(cs[0]), (cs, log_of(c)[-600:], r.stderr[-300:])
    assert "全部止まったのを確かめて" in log_of(c)
    after = tree(c)
    assert after == before, sorted(set(before) ^ set(after)) + [k for k in before if k in after and before[k] != after[k]]
    c = make("k7b")
    open(os.path.join(c["home"], "CLAUDE.md"), "w").write("# 本人設定\n")
    before = tree(c)
    r = run(c, "do", stub_phase="do", extra_env={"FAKE_CANARY": "nofence", "FAKE_CANARY_EXTRA": extra})
    lg = fell_back(c, r)
    assert "network=leaked" in lg and "write=leaked" in lg, lg
    after = tree(c)
    assert after == before, "囲いが無い日に、点検の道具が実物を変えた：%s" % (sorted(set(before) ^ set(after)) + [k for k in before if k in after and before[k] != after[k]])
    lit = [os.path.join(dp, x) for dp, dn, fn in os.walk(c["home"]) for x in dn + fn if ".ai-bunshin-canary-" in x and x != ".ai-bunshin-canary-dir"]
    assert 1 <= len(lit) <= 2, lit
    assert os.path.isdir(os.path.join(c["home"], "scripts")) and os.path.isdir(os.path.join(c["home"], "設定"))
    ls.close()


@case
def k8_plan_skip_with_existing_plan_enters_do_with_settings():
    # 9時前に手動で計画した日：plan:SKIP（計画は作成済み）→ 未実行なので実行に入る。実行の段として囲い・点検・Python が働く
    c = make("k8")
    r = run(c, "plan", extra_env={"STUB_SKIP_PLANNED": "1"})
    assert r.returncode == 0, (r.returncode, r.stderr[-300:], log_of(c)[-600:])
    cs = calls(c)
    assert len(cs) == 1 and "/ai-bunshin:daily-do" in cs[0]["args"] and "/ai-bunshin:daily-plan" not in cs[0]["args"], cs
    assert has_settings(cs[0]) and has_python(cs[0]) and "WebFetch" in opt(cs[0], "--allowedTools"), cs[0]["args"]
    assert len(canary_calls(c)) == 1
    assert "計画は作成済み・未実行のため、実行に入る" in log_of(c)
    good_settings(c, cs[0])
    # 点検が通らない日は、この道でも Python を許さない
    c = make("k8b")
    r = run(c, "plan", extra_env={"STUB_SKIP_PLANNED": "1", "FAKE_CANARY": "leak:keychain"})
    cs = calls(c)
    assert r.returncode == 0 and len(cs) == 1 and "/ai-bunshin:daily-do" in cs[0]["args"], cs
    assert not has_settings(cs[0]) and not has_python(cs[0]) and "keychain=leaked" in log_of(c)


@case
def k9_reason_cut_by_characters_not_bytes():
    # 作れなかった理由が長い日本語でも、C ロケールで文字の途中で切れない（cut -c はバイトで切る）
    long_reason = "あ" * 200
    files = {"sandbox_settings.py": "import sys\nsys.stderr.write('sandbox_settings: %s\\n')\nsys.exit(1)\n" % long_reason}
    c = make("k9", plugin_files=files)
    r = run(c, "do", stub_phase="do", extra_env={"LC_ALL": "C", "LANG": "C"})
    assert r.returncode == 0, (r.returncode, r.stderr[-200:])
    raw = b"".join(open(os.path.join(c["home"], "scripts", "auto", "logs", f), "rb").read() for f in os.listdir(os.path.join(c["home"], "scripts", "auto", "logs")) if f.endswith(".log"))
    text = raw.decode("utf-8")   # 文字の途中で切れていれば、ここで落ちる
    line = [ln for ln in text.splitlines() if "囲いの設定を作れなかったので" in ln][0]
    reason = line.split("（理由：", 1)[1].rsplit("）", 1)[0]
    assert reason == "あ" * 120, (len(reason), reason[:20])


@case
def k10_failed_main_run_is_not_retried_without_the_fence():
    # S19：囲いが動かない日（--settings 付きの claude が止まる）は、その日の実行は失敗で終わる。囲いなしでやり直さない
    c = make("k10")
    r = run(c, "do", stub_phase="do", extra_env={"FAKE_MAIN_FAIL_WITH_SETTINGS": "1"})
    assert r.returncode == 1, (r.returncode, log_of(c)[-400:])
    cs = calls(c)
    assert len(cs) == 1 and has_settings(cs[0]), cs
    assert "終了 (exit=1)" in log_of(c)


@case
def k11_signal_during_canary_leaves_no_temp_files():
    import signal
    import time
    c = make("k11")
    env = {k: v for k, v in os.environ.items() if k not in ("AI_BUNSHIN_AUTO_RUN", "CLAUDE_PROJECT_DIR", "AI_BUNSHIN_CALENDAR_URL")}
    env.update({"HOME": FAKE_HOME, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "AI_BUNSHIN_HOME": c["home"],
                "PATH": c["bindir"] + os.pathsep + env.get("PATH", ""), "FAKE_RECORD": c["rec"], "STUB_PHASE": "do",
                "FAKE_CANARY": "hang", "AI_BUNSHIN_CANARY_SEC": "60"})
    open(os.path.join(c["rec"], "keychain_url"), "w").write(CAL_URL + "\n")
    p = subprocess.Popen(["/bin/zsh", os.path.join(c["plugin"], "scripts", "auto", "daily_cycle.sh"), "do"], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        t0 = time.time()
        while time.time() - t0 < 40 and not canary_calls(c):
            time.sleep(0.05)
        assert canary_calls(c), "点検が始まらない"
        time.sleep(0.3)
        os.kill(p.pid, signal.SIGTERM)
        rc = p.wait(timeout=30)
        assert rc == 143, rc
    finally:
        if p.poll() is None:
            os.killpg(p.pid, signal.SIGKILL)
    logs = os.path.join(c["home"], "scripts", "auto", "logs")
    left = [f for f in os.listdir(logs) if f.startswith(".out.")] + [f for f in os.listdir(os.path.join(c["home"], "00_タスク管理", "data")) if f.startswith(".sandbox_canary")]
    assert not left, left
    assert not os.path.exists(os.path.join(c["home"], "scripts", "auto", ".lock"))
    assert calls(c) == [], "止められたのに本体を起動した"


def notices(c):
    p = os.path.join(c["rec"], "notify.txt")
    return open(p, encoding="utf-8").read().splitlines() if os.path.exists(p) else []


CANARY_NOTICE = "今日は囲いの点検が通らなかったので、Python を使わずに動かしました（ログを見てください）"


@case
def k12_notify_when_canary_fails_without_items_or_paths():
    # A2：点検が通らなかった日は、ログに加えて通知を1行。項目名・パスは通知に出さない
    for tag, mode, extra in (("leak", "leak:write,network,keychain", {}), ("none", "none", {}), ("fail", "fail", {}),
                             ("hang", "hang", {"AI_BUNSHIN_CANARY_SEC": "1"}), ("stale", "stale", {})):
        c = make("k12_" + tag)
        r = run(c, "do", stub_phase="do", extra_env=dict({"FAKE_CANARY": mode}, **extra), timeout=90)
        assert r.returncode == 0, (tag, r.returncode, log_of(c)[-300:])
        ns = [n for n in notices(c) if "囲いの点検" in n]
        assert len(ns) == 1 and CANARY_NOTICE in ns[0], (tag, notices(c))
        for bad in ("write", "network", "keychain", "leaked", "error", "=", c["home"], "/Users/", "http", SECRET):
            assert bad not in ns[0], (tag, bad, ns[0])
    # 全部止まった日・囲いの設定を作れない日（S05）・計画・振り返りの段は、点検の通知を出さない
    c = make("k12_pass")
    run(c, "do", stub_phase="do")
    assert not [n for n in notices(c) if "囲いの点検" in n], notices(c)
    c = make("k12_nosettings", plugin_files={"sandbox_settings.py": None})
    run(c, "do", stub_phase="do")
    assert not [n for n in notices(c) if "囲いの点検" in n], notices(c)
    c = make("k12_plan")
    run(c, "plan", extra_env={"STUB_NO_PLAN": "1", "FAKE_CANARY": "leak:write"})
    assert not [n for n in notices(c) if "囲いの点検" in n], notices(c)
    # 計画から続けて実行に入る日・plan:SKIP から実行に入る日も、点検が通らなければ1回だけ通知する
    c = make("k12_plando")
    run(c, "plan", extra_env={"FAKE_CANARY": "leak:env_url"})
    assert len([n for n in notices(c) if "囲いの点検" in n]) == 1, notices(c)
    c = make("k12_skip")
    run(c, "plan", extra_env={"STUB_SKIP_PLANNED": "1", "FAKE_CANARY": "leak:env_url"})
    assert len([n for n in notices(c) if "囲いの点検" in n]) == 1, notices(c)


@case
def k13_marker_dir_made_outside_the_fence_before_the_canary():
    # A1：目印フォルダ（.ai-bunshin-canary-dir／inner）は daily_cycle.sh が囲いの外で前もって作る（無ければ作る）。点検の claude が動く時点で、もうある
    c = make("k13")
    r = run(c, "do", stub_phase="do")
    assert r.returncode == 0 and canary_calls(c) and canary_calls(c)[0]["marker_ready"] is True, (canary_calls(c), log_of(c)[-300:])
    assert os.path.isdir(os.path.join(c["home"], ".ai-bunshin-canary-dir", "inner"))
    # すでにあるときもそのまま（中の目印を壊さない）。2回目の実行でも通る
    r = run(c, "do", stub_phase="do")
    assert r.returncode == 0 and os.path.isdir(os.path.join(c["home"], ".ai-bunshin-canary-dir", "inner")) and len(canary_calls(c)) == 2
    # 計画・振り返りの段、囲いの設定を作れない日、点検の道具が無い日は、作らない
    for tag, phase, kw in (("p", "plan", {"extra_env": {"STUB_NO_PLAN": "1"}}), ("r", "review", {"stub_phase": "review"})):
        c2 = make("k13" + tag)
        run(c2, phase, **kw)
        assert not os.path.exists(os.path.join(c2["home"], ".ai-bunshin-canary-dir")), phase
    c3 = make("k13s", plugin_files={"sandbox_settings.py": None})
    run(c3, "do", stub_phase="do")
    assert not os.path.exists(os.path.join(c3["home"], ".ai-bunshin-canary-dir"))
    c4 = make("k13c", plugin_files={"sandbox_canary.py": None})
    run(c4, "do", stub_phase="do")
    assert not os.path.exists(os.path.join(c4["home"], ".ai-bunshin-canary-dir"))
    # 同じ名前のファイルがあって作れないときは、点検できないので Python を許さない（claude も起動しない）
    c5 = make("k13f")
    open(os.path.join(c5["home"], ".ai-bunshin-canary-dir"), "w").write("x")
    r = run(c5, "do", stub_phase="do")
    fell_back(c5, r, "点検の目印フォルダを作れなかった")
    assert canary_calls(c5) == []

print(f"\n{len(names) - fails}/{len(names)} passed")
sys.exit(1 if fails else 0)
