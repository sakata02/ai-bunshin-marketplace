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
- G4c：点検の結果を偽造・左右できない形（k14〜k18。印・設定の sha256・write の数・鍵が出ない・キーチェーンは囲いの外で先に確かめる・設定のファイルは囲いの外で置いて消す・計画と振り返りの DENY に Edit(CLAUDE.local.md)）。
  点検の claude は作り物なので、鍵・設定のファイルは実物の daily_cycle.sh と点検の道具（import）から読み、本物の claude の中で鍵が環境変数として届くことは確かめていない
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
    "marker_ready": os.path.isdir(os.path.join(os.environ["AI_BUNSHIN_HOME"], ".ai-bunshin-canary-dir", "guard")),
    "args": args,
    "main_has_key_var": "AI_BUNSHIN_CANARY_KEY" in env,
    "has_url_var": "AI_BUNSHIN_CALENDAR_URL" in env,
    "secret_in_env": any("__SECRET__" in v for v in env.values()),
    "secret_in_args": any("__SECRET__" in a for a in args),
}
CHECKS = ["write", "parent_mv", "case", "network", "keychain", "env_url"]
if "囲いの点検" in prompt:
    # 囲いの点検の呼び出し（calls.jsonl には入れない）。FAKE_CANARY で、点検の結果を作り物にする（印は、環境の鍵で付ける）
    mode = os.environ.get("FAKE_CANARY", "pass")
    import hashlib, importlib.util
    argv = shlex.split(prompt.splitlines()[1])   # python3 -I <点検の道具> --nonce <ID>（引数はこれだけ）
    canary_path = argv[2]
    nonce = argv[argv.index("--nonce") + 1]
    spec = importlib.util.spec_from_file_location("sc", canary_path)
    C = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(C)
    key = env.get("AI_BUNSHIN_CANARY_KEY", "")
    body = open(C.config_path(nonce), "rb").read()   # 囲いの外の daily_cycle.sh が置いた設定のファイル
    cfg = json.loads(body.decode("utf-8"))
    out = cfg["out"]
    minw = C.expected_write_count(cfg["settings"]["sandbox"]["filesystem"]["denyWrite"])
    with open(os.path.join(rec, "canary_calls.jsonl"), "a", encoding="utf-8") as f:
        info2 = dict(info, argv=argv, key=key, has_key_var=bool(key), key_in_args=bool(key) and any(key in a for a in args),
                     key_in_prompt=bool(key) and key in prompt, cfg_keychain=cfg["keychain_services"], cfg_home=cfg["home"],
                     cfg_net=cfg["net_targets"], cfg_has_settings=bool(cfg["settings"]), cfg_nonce=cfg["nonce"],
                     cfg_sha=hashlib.sha256(body).hexdigest(), minw=minw)
        f.write(json.dumps(info2, ensure_ascii=False) + "\\n")
    def put(checks, nonce=nonce, key=key, sha=None, writes=minw, sign_it=True, **kw):
        d = {"v": C.VERSION, "nonce": nonce, "date": "2026-11-07", "checks": checks, "counts": {"write": writes}, "litter": None,
             "restore_failed": False, "config_sha256": sha or hashlib.sha256(body).hexdigest()}
        d.update(kw)
        if sign_it:
            d["mac"] = C.sign(d, key)
        json.dump(d, open(out, "w"))
        return d
    ok_checks = {k: "blocked" for k in CHECKS}
    if not cfg["keychain_services"]:
        ok_checks["keychain"] = "error"   # 確かめる項目が1つも無い日は error（S22）
    if mode == "pass":
        put(ok_checks)
    elif mode.startswith(("leak:", "error:", "skipped:")):
        state, _, items = mode.partition(":")
        state = {"leak": "leaked"}.get(state, state)
        put({k: (state if k in items.split(",") else "blocked") for k in CHECKS})
    elif mode == "stale":
        put(ok_checks, nonce="OLD")   # 鍵で正しく印を付けた、前の実行の結果
    elif mode == "restore_failed":
        put(ok_checks, restore_failed=True)
    elif mode == "nomac":
        put(ok_checks, sign_it=False)
    elif mode == "wrongkey":
        put(ok_checks, key="ef" * 32)
    elif mode == "badsha":
        put(ok_checks, sha="0" * 64)
    elif mode == "lowcount":
        put(ok_checks, writes=minw - 1)
    elif mode.startswith("tamper:"):   # 印を付けたあとで書き換える（印は付け直さない）
        what = mode.split(":", 1)[1]
        d = put(dict(ok_checks, write="leaked", network="leaked"))
        if what == "checks":
            d["checks"] = dict(ok_checks)
        elif what == "sha":
            d["config_sha256"] = "1" * 64
        elif what == "count":
            d["counts"] = {"write": 999}
        elif what == "nonce":
            d["nonce"] = "OLD"
        json.dump(d, open(out, "w"))
    elif mode == "garbage":
        open(out, "w").write("not json")
    elif mode == "hang":
        time.sleep(60)
    elif mode == "fail":
        sys.exit(1)
    elif mode in ("fence", "nofence"):
        # 本物の点検の道具を import で動かす（コマンドの引数では security の場所を変えられないため、テストだけ import で security を差し替える）。fence は seatbelt の下で
        runner = os.path.join(rec, "runner.py")
        nl = chr(10)
        open(runner, "w").write("import importlib.util, os, sys" + nl + "spec = importlib.util.spec_from_file_location('sc', sys.argv[1])" + nl
                                + "m = importlib.util.module_from_spec(spec)" + nl + "spec.loader.exec_module(m)" + nl
                                + "key = os.environ.pop('AI_BUNSHIN_CANARY_KEY')" + nl + "m.execute(m.config_path(sys.argv[2]), sys.argv[2], key, sys.argv[3])" + nl)
        cmd = [sys.executable, "-I", runner, canary_path, nonce, os.environ["FAKE_CANARY_SEC"]]
        if mode == "fence":
            sj = json.loads(args[args.index("--settings") + 1])
            lines = ["(version 1)", "(allow default)", "(deny network*)"]
            lines += ['(deny file-write* (subpath "%s"))' % p for p in sj["sandbox"]["filesystem"]["denyWrite"]]
            top = os.path.dirname(rec)   # 守る先の親（このテストの一時フォルダの中）の名前の付け替えも止める（Claude Code の囲いが守る先の親を止める作りに合わせる）
            anc = set()
            for p in sj["sandbox"]["filesystem"]["denyWrite"]:
                q = os.path.dirname(p)
                while q.startswith(top) and q != top:
                    anc.add(q)
                    q = os.path.dirname(q)
            lines += ['(deny file-write-unlink (literal "%s"))' % a for a in sorted(anc)]
            prof = os.path.join(rec, "fence.sb")
            open(prof, "w").write(nl.join(lines) + nl)
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
echo "$*" >> "$FAKE_RECORD/__LOG__"
case " $* " in
  *" -w "*)
    # 中身を頼む呼び出し（カレンダーの URL を読む）
    echo x >> "$FAKE_RECORD/security_reads"
    if [ -s "$FAKE_RECORD/keychain_url" ]; then cat "$FAKE_RECORD/keychain_url"; exit 0; fi
    exit 44 ;;
  *)
    # 項目があるかだけ（点検の前に、囲いの外で確かめる）。no_items があれば、どの項目も無い
    if [ -e "$FAKE_RECORD/no_items" ]; then exit 44; fi
    if [ -s "$FAKE_RECORD/only_items" ] && ! grep -qx "$3" "$FAKE_RECORD/only_items"; then exit 44; fi
    exit 0 ;;
esac
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
    open(os.path.join(bindir, "security"), "w").write(FAKE_SECURITY.replace("__LOG__", "security_calls"))
    # 囲いの外の「項目があるか」の確かめは C.DEFAULT_SECURITY を使う（G4e 低1）。テストでは import で差し替える：プラグインのコピーの sandbox_canary.py の末尾で DEFAULT_SECURITY を sec_default にする
    open(os.path.join(bindir, "sec_default"), "w").write(FAKE_SECURITY.replace("__LOG__", "security_default_calls"))
    canary_copy = os.path.join(plugin, "scripts", "sandbox_canary.py")
    if os.path.exists(canary_copy):
        with open(canary_copy, "a", encoding="utf-8") as f:
            f.write("\n\nDEFAULT_SECURITY = %r   # テストだけ：import で security の代わりに差し替える\n" % os.path.join(bindir, "sec_default"))
    for f in ("claude", "osascript", "security", "sec_default"):
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
    assert os.path.exists(os.path.join(c["rec"], "security_reads")), "キーチェーンの代わり（security）で URL を読んでいない"
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
    assert not os.path.exists(os.path.join(c["rec"], "security_reads")), "カレンダーをつないでいないのにキーチェーンの中身を読んだ"
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
    # S20①：点検の claude は default。書く・調べる・人を呼ぶ道具を止める（本番の DENY に足して）
    dis = opt(k, "--disallowedTools").split(",")
    for t in ("Write", "Edit", "NotebookEdit", "Agent", "Task", "WebFetch", "WebSearch"):
        assert t in dis, (t, dis)
    assert all(x in dis for x in opt(cs[0], "--disallowedTools").split(",")), "本番の DENY が点検で外れている"
    # S20②：鍵は点検の claude の環境にだけある（本番の claude の環境には無い）。引数・プロンプトには出ない
    assert k["has_key_var"] is True and len(k["key"]) == 64 and cs[0]["main_has_key_var"] is False
    assert k["key_in_args"] is False and k["key_in_prompt"] is False
    # S20③：点検の道具の呼び方は nonce だけ（引数に --out・--home などが無い）。設定は囲いの外で置いた設定のファイルにある
    assert k["argv"][:3] == ["python3", "-I", canary_path] and k["argv"][3] == "--nonce" and len(k["argv"]) == 5, k["argv"]
    assert k["cfg_has_settings"] and k["cfg_nonce"] == k["argv"][4] and os.path.realpath(k["cfg_home"]) == os.path.realpath(c["home"])
    assert int(opt(k, "--max-turns")) <= 6 and opt(k, "--model") == "sonnet" and opt(k, "--permission-mode") == "default"
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
    extra = sec   # 点検の道具の中で呼ぶ security の代わり（import でだけ差し替える。コマンドの引数では変えられない）

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
    r = run(c, "do", stub_phase="do", extra_env={"FAKE_CANARY": "fence", "FAKE_CANARY_SEC": extra})
    assert r.returncode == 0, (r.returncode, log_of(c)[-600:])
    cs = calls(c)
    assert len(cs) == 1 and has_settings(cs[0]) and has_python(cs[0]), (cs, log_of(c)[-600:], r.stderr[-300:])
    assert "全部止まったのを確かめて" in log_of(c)
    after = tree(c)
    assert after == before, sorted(set(before) ^ set(after)) + [k for k in before if k in after and before[k] != after[k]]
    c = make("k7b")
    open(os.path.join(c["home"], "CLAUDE.md"), "w").write("# 本人設定\n")
    before = tree(c)
    r = run(c, "do", stub_phase="do", extra_env={"FAKE_CANARY": "nofence", "FAKE_CANARY_SEC": extra})
    lg = fell_back(c, r)
    assert "write=leaked" in lg and "network=" in lg, lg   # 通信は、つながれば leaked・届かなければ error（どちらも blocked ではない。S21）
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
    # A1：目印フォルダ（.ai-bunshin-canary-dir／guard）は daily_cycle.sh が囲いの外で前もって作る（無ければ作る）。点検の claude が動く時点で、もうある
    c = make("k13")
    r = run(c, "do", stub_phase="do")
    assert r.returncode == 0 and canary_calls(c) and canary_calls(c)[0]["marker_ready"] is True, (canary_calls(c), log_of(c)[-300:])
    assert os.path.isdir(os.path.join(c["home"], ".ai-bunshin-canary-dir", "guard"))
    # すでにあるときもそのまま（中の目印を壊さない）。2回目の実行でも通る
    r = run(c, "do", stub_phase="do")
    assert r.returncode == 0 and os.path.isdir(os.path.join(c["home"], ".ai-bunshin-canary-dir", "guard")) and len(canary_calls(c)) == 2
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


# ---------- G4c：点検の結果を偽造・左右できない形にする（決定 S20〜S24） ----------

@case
def k14_forged_or_tampered_results_do_not_pass():
    """S20②③：印の無い・違う鍵の・印のあとで書き換えた・設定の sha256 が違う・write の数が下限未満の結果は、どれも「通らなかった」"""
    for tag, mode, why in (("nomac", "nomac", "結果の印が正しくない"), ("wrongkey", "wrongkey", "結果の印が正しくない"),
                           ("t_checks", "tamper:checks", "結果の印が正しくない"), ("t_sha", "tamper:sha", "結果の印が正しくない"),
                           ("t_count", "tamper:count", "結果の印が正しくない"), ("t_nonce", "tamper:nonce", "結果の印が正しくない"),
                           ("badsha", "badsha", "設定の中身が違う"), ("lowcount", "lowcount", "write の確かめた数が足りない"),
                           ("stale", "stale", "結果が今回のものではない")):
        c = make("k14_" + tag)
        r = run(c, "do", stub_phase="do", extra_env={"FAKE_CANARY": mode})
        fell_back(c, r, why)
    c = make("k14_ok")   # 同じ作りで、正しく印を付けた結果は通る（上の確かめが「全部落とす」だけの壊れた判定でないこと）
    r = run(c, "do", stub_phase="do")
    cs = calls(c)
    assert r.returncode == 0 and len(cs) == 1 and has_settings(cs[0]) and has_python(cs[0]), (cs, log_of(c)[-400:])


@case
def k15_key_never_in_args_prompt_log_or_output():
    """S20②：鍵は引数・プロンプト・ログ・通知・標準出力・どのファイルにも出ない。毎回違う鍵。本番の claude の環境には無い"""
    keys = []
    for tag, mode in (("pass", "pass"), ("leak", "leak:write,network"), ("nomac", "nomac"), ("fail", "fail")):
        c = make("k15_" + tag)
        r = run(c, "do", stub_phase="do", extra_env={"FAKE_CANARY": mode})
        cc = canary_calls(c)
        assert len(cc) == 1, cc
        key = cc[0]["key"]
        assert len(key) == 64 and cc[0]["key_in_args"] is False and cc[0]["key_in_prompt"] is False, cc[0]
        keys.append(key)
        text = r.stdout + r.stderr + log_of(c) + "\n".join(notices(c)) + json.dumps(calls(c), ensure_ascii=False)
        assert key not in text, "%s: 鍵がログ・出力・通知・本体の呼び出しに出た" % tag
        assert all(x["main_has_key_var"] is False for x in calls(c)), "本番の claude の環境に鍵がある"
        for root in (c["home"], c["plugin"], FAKE_HOME):
            for dp, dn, fn in os.walk(root):
                for f in fn:
                    pth = os.path.join(dp, f)
                    try:
                        assert key.encode() not in open(pth, "rb").read(), "鍵がファイルに残った：" + pth
                    except OSError:
                        pass
    assert len(set(keys)) == len(keys), "鍵が毎回違わない"


@case
def k16_keychain_names_are_checked_outside_first():
    """S22：囲いの外で先に項目があるかを確かめ（-w なし）、ある名前だけを点検に渡す。1つも無い日は error（Python を許さない）"""
    c = make("k16a")
    open(os.path.join(c["rec"], "only_items"), "w").write("Claude Code-credentials\n")   # カレンダーの名前の項目は無い
    r = run(c, "do", stub_phase="do")
    cc = canary_calls(c)
    assert r.returncode == 0 and len(cc) == 1 and cc[0]["cfg_keychain"] == ["Claude Code-credentials"], (cc, log_of(c)[-300:])
    sec = open(os.path.join(c["rec"], "security_default_calls")).read().splitlines()
    exist = [x for x in sec if "-w" not in x.split()]
    assert exist and all(x.startswith("find-generic-password -s ") and " -w" not in x and " -g" not in x for x in exist), "確かめの呼び方が違う（-w・-g を付けない）：%s" % exist
    assert has_python(calls(c)[0])
    c = make("k16b")
    open(os.path.join(c["rec"], "no_items"), "w").write("x")
    r = run(c, "do", stub_phase="do")
    cc = canary_calls(c)
    assert len(cc) == 1 and cc[0]["cfg_keychain"] == [], cc
    fell_back(c, r, "keychain=error")


@case
def k17_config_file_is_placed_outside_and_removed():
    """S20③：設定のファイルは囲いの外で <ホーム>/.ai-bunshin/canary/<nonce>.json に置き、点検が終われば消す。写す中身の sha256・数の下限は呼び出しの前に決まる"""
    c = make("k17")
    r = run(c, "do", stub_phase="do")
    cc = canary_calls(c)
    assert r.returncode == 0 and len(cc) == 1, (r.returncode, log_of(c)[-300:])
    k = cc[0]
    assert len(k["cfg_sha"]) == 64 and k["minw"] >= 1 and k["cfg_net"] == [["1.1.1.1", 443]], k
    d = os.path.join(FAKE_HOME, ".ai-bunshin", "canary")
    left = [f for f in os.listdir(d) if f.startswith(k["cfg_nonce"])] if os.path.isdir(d) else []
    assert not left, left
    # 守る先が1つも無い（確かめられない）日は、点検の claude を起動しない
    zero = open(os.path.join(SCRIPTS, "sandbox_canary.py"), encoding="utf-8").read() + "\n\ndef expected_write_count(deny_write):\n    return 0\n"   # 確かめる守る先が0件の日
    c = make("k17b", plugin_files={"sandbox_canary.py": zero})
    r = run(c, "do", stub_phase="do")
    assert r.returncode == 0, (r.returncode, log_of(c)[-300:])
    assert canary_calls(c) == [], "守る先が無いのに点検の claude を起動した"


@case
def k18_plan_and_review_deny_editing_claude_local_md():
    """S24：計画・振り返りの段の DENY に Edit(CLAUDE.local.md) がある"""
    c = make("k18p")
    run(c, "plan", extra_env={"STUB_NO_PLAN": "1"})
    cs = calls(c)
    assert cs and "Edit(CLAUDE.local.md)" in opt(cs[0], "--disallowedTools").split(","), cs
    c = make("k18r")
    run(c, "review", stub_phase="review")
    cs = calls(c)
    assert cs and "Edit(CLAUDE.local.md)" in opt(cs[0], "--disallowedTools").split(","), cs

@case
def k19_settings_with_bash_allow_logs_one_line_and_does_not_stop():
    """G4e S25：本人のフォルダ・ユーザーのホームの設定の permissions.allow に Bash（や mcp）の許可があれば、点検の前にログへ1行。許可の中身は出さない。点検は止めない（通る日は通る）。無い・壊れていても止めない"""
    LINE = "設定に Bash の許可があるため、点検の結果の偽造は防げません（README の限界）"
    PATTERN = "secretcmd-9f3a"

    def settings(path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="utf-8").write(text)
    allow = json.dumps({"permissions": {"allow": ["Read", "Bash(%s:*)" % PATTERN]}})
    for tag, where, text in (("owner", "owner/.claude/settings.json", allow), ("local", "owner/.claude/settings.local.json", allow),
                             ("user", "uhome/.claude/settings.json", allow),
                             ("mcp", "owner/.claude/settings.json", json.dumps({"permissions": {"allow": ["mcp__%s__x" % PATTERN]}}))):
        c = make("k19_" + tag)
        uh = os.path.join(c["d"], "uhome")
        os.makedirs(uh, exist_ok=True)
        settings(os.path.join(c["d"], where), text)
        r = run(c, "do", stub_phase="do", extra_env={"HOME": uh})
        cs = calls(c)
        assert r.returncode == 0 and len(cs) == 1 and has_settings(cs[0]) and has_python(cs[0]), (tag, log_of(c)[-400:])   # 止めない（全部止まった日は Python を許す）
        assert log_of(c).count(LINE) == 1, (tag, log_of(c))
        assert PATTERN not in all_text(c, r) + "".join(notices(c)), "%s: 許可の中身がログ・出力に出た" % tag
        ln = [x for x in log_of(c).splitlines() if LINE in x][0]
        assert log_of(c).index(ln) < log_of(c).index("点検（カナリア）も全部止まった"), "点検の前に出していない"
    # 許可が無い・deny だけ・壊れた JSON・形が違う・計画と振り返りの段：1行も出さない。点検は動く
    for tag, text in (("none", None), ("deny", json.dumps({"permissions": {"deny": ["Bash(rm:*)"]}})), ("broken", "{broken"),
                      ("shape", json.dumps({"permissions": {"allow": "Bash"}})), ("readonly", json.dumps({"permissions": {"allow": ["Read"]}}))):
        c = make("k19n_" + tag)
        os.makedirs(os.path.join(c["d"], "uhome"), exist_ok=True)
        if text is not None:
            settings(os.path.join(c["home"], ".claude", "settings.json"), text)
            settings(os.path.join(c["d"], "uhome", ".claude", "settings.json"), text)
        r = run(c, "do", stub_phase="do", extra_env={"HOME": os.path.join(c["d"], "uhome")})
        cs = calls(c)
        assert r.returncode == 0 and len(cs) == 1 and has_python(cs[0]) and LINE not in log_of(c), (tag, log_of(c)[-400:])
    c = make("k19p")
    os.makedirs(os.path.join(c["d"], "uhome"), exist_ok=True)
    settings(os.path.join(c["home"], ".claude", "settings.json"), allow)
    run(c, "plan", extra_env={"STUB_NO_PLAN": "1", "HOME": os.path.join(c["d"], "uhome")})
    assert LINE not in log_of(c), "点検の無い段でも出した"
    # 点検が通らない日も出る（偽造できる日は通らない日のほうが安全、という読み方を妨げない）。出るのは1回だけ
    c = make("k19f")
    os.makedirs(os.path.join(c["d"], "uhome"), exist_ok=True)
    settings(os.path.join(c["home"], ".claude", "settings.json"), allow)
    r = run(c, "do", stub_phase="do", extra_env={"FAKE_CANARY": "leak:network", "HOME": os.path.join(c["d"], "uhome")})
    assert log_of(c).count(LINE) == 1 and "network=leaked" in log_of(c)


@case
def k20_keychain_error_has_a_guidance_line():
    """G4e 中2：keychain=error の日は、ログに案内を1行（write・parent_mv と同じ形）。ほかの項目だけが通らない日には出さない"""
    LINE = "キーチェーンに確かめる項目（ai-bunshin-calendar か Claude Code-credentials）が無いか、確かめられなかったため、点検が通りません。Python なしで動いています"
    c = make("k20a")
    open(os.path.join(c["rec"], "no_items"), "w").write("x")
    r = run(c, "do", stub_phase="do")
    lg = fell_back(c, r, "keychain=error")
    assert lg.count(LINE) == 1, lg
    c = make("k20b")
    r = run(c, "do", stub_phase="do", extra_env={"FAKE_CANARY": "error:keychain,network"})
    lg = fell_back(c, r, "keychain=error")
    assert lg.count(LINE) == 1, lg
    for tag, mode in (("net", "leak:network"), ("kcleak", "leak:keychain"), ("stale", "stale"), ("write", "leak:write")):
        c = make("k20_" + tag)
        r = run(c, "do", stub_phase="do", extra_env={"FAKE_CANARY": mode})
        assert LINE not in log_of(c), (tag, log_of(c))
    c = make("k20ok")
    run(c, "do", stub_phase="do")
    assert LINE not in log_of(c)


@case
def k21_timeout_has_a_guidance_line_about_leftover_marks():
    """G4e 低3：時間切れの日にも、点検用の名前（.ai-bunshin-canary- で始まるもの）が残っているかもしれない案内を1行。時間切れ以外の失敗には出さない"""
    LINE = "時間切れのため、点検用の名前（.ai-bunshin-canary- で始まるもの）が残っているかもしれません"
    c = make("k21a")
    r = run(c, "do", stub_phase="do", extra_env={"FAKE_CANARY": "hang", "AI_BUNSHIN_CANARY_SEC": "1"}, timeout=90)
    lg = fell_back(c, r, "時間切れ")
    assert lg.count(LINE) == 1, lg
    for tag, mode in (("fail", "fail"), ("none", "none"), ("stale", "stale"), ("net", "leak:network"), ("write", "leak:write")):
        c = make("k21_" + tag)
        r = run(c, "do", stub_phase="do", extra_env={"FAKE_CANARY": mode})
        assert LINE not in log_of(c), (tag, log_of(c))
    # 通知は今までどおり1行（案内は通知に出さない）
    c = make("k21n")
    run(c, "do", stub_phase="do", extra_env={"FAKE_CANARY": "hang", "AI_BUNSHIN_CANARY_SEC": "1"}, timeout=90)
    ns = [n for n in notices(c) if "囲いの点検" in n]
    assert len(ns) == 1 and "canary-" not in ns[0], notices(c)


@case
def k22_outside_keychain_check_uses_default_security():
    """G4e 低1：囲いの外の「項目があるか」の確かめも、囲いの中と同じ C.DEFAULT_SECURITY（テストでは import で差し替えた sec_default）。PATH の security は、カレンダーの URL を読むときだけ"""
    c = make("k22")
    r = run(c, "do", stub_phase="do")
    assert r.returncode == 0 and canary_calls(c), log_of(c)[-300:]
    dflt = open(os.path.join(c["rec"], "security_default_calls")).read().splitlines()
    assert dflt and all(x.startswith("find-generic-password -s ") and " -w" not in x for x in dflt), dflt
    path_calls = open(os.path.join(c["rec"], "security_calls")).read().splitlines() if os.path.exists(os.path.join(c["rec"], "security_calls")) else []
    assert all(x.split()[-1] == "-w" for x in path_calls), "PATH の security が、項目の確かめに使われた：%s" % path_calls

print(f"\n{len(names) - fails}/{len(names)} passed")
sys.exit(1 if fails else 0)
