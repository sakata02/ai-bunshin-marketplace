"""自動実行のロック判断（scripts/lock_check.py と daily_cycle.sh）のテスト（T080）。
不具合：17時の自動の振り返りが、自分自身のロック（.lock）を「ほかの実行」と思って何もせずに終わった。
- 判断の4通り：自動の振り返り（自分のロック）→ 開く／自動の朝の計画が動いているときに会話から → 開かない／
  古いロック（PID が無い）→ 開く／自動同士が重なった → 後のほうは開かない
- ID の無い古い形式のロック・壊れたロック・ロックを読めないとき
- daily_cycle.sh が、ロックの3行目の ID と環境変数 AI_BUNSHIN_AUTO_RUN を同じ値にして claude に渡す
  （一時フォルダの作り物の claude・update_dashboard.py で、plan → do の続きまで通して動かす。本物の launchd・claude・通知は使わない）
実行：python3 tests/test_auto_lock.py（失敗があれば終了コード1）"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.abspath(os.path.join(HERE, "..", "scripts"))
LOCK_CHECK = os.path.join(SCRIPTS, "lock_check.py")
CYCLE = os.path.join(SCRIPTS, "auto", "daily_cycle.sh")
sys.path.insert(0, SCRIPTS)
import lock_check as lc  # noqa: E402

BASE = os.path.realpath(tempfile.mkdtemp(prefix="lockchk_"))

# 動いているプロセスと、もう終わったプロセスの PID
alive_proc = subprocess.Popen(["sleep", "60"])
dead_proc = subprocess.Popen(["true"])
dead_proc.wait()
ALIVE, DEAD = alive_proc.pid, dead_proc.pid

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


def lock_text(pid, label, run_id=None):
    t = f"{pid}\n{label}\n"
    return t + (run_id + "\n" if run_id else "")


# ---------- 判断（関数） ----------

@case
def j1_auto_review_own_lock_opens():
    # 17時の自動の振り返り：ロックは自分（daily_cycle.sh）が書いた。ID が一致する
    ok, kind, _ = lc.judge(lock_text(ALIVE, "振り返り（17:00開始）", "100.1700"), "100.1700")
    assert ok and kind == "own", (ok, kind)


@case
def j2_conversation_while_auto_plan_runs_does_not_open():
    # 朝の自動の計画が動いている。会話から振り返り（環境変数が無い）
    ok, kind, msg = lc.judge(lock_text(ALIVE, "プランニング（09:00開始）", "100.0900"), None)
    assert not ok and kind == "other", (ok, kind)
    assert "プランニング" in msg and str(ALIVE) in msg, msg


@case
def j3_stale_lock_opens():
    # ロックはあるが、その PID のプロセスはもう無い
    ok, kind, msg = lc.judge(lock_text(DEAD, "振り返り（17:00開始）", "100.1700"), None)
    assert ok and kind == "stale", (ok, kind)
    assert "古いロック" in msg
    # 環境変数が一致していても、PID が死んでいれば古いロック（自分扱いにしない）
    ok2, kind2, _ = lc.judge(lock_text(DEAD, "x", "100.1700"), "100.1700")
    assert ok2 and kind2 == "stale", (ok2, kind2)


@case
def j4_auto_overlap_later_one_does_not_open():
    # 自動同士が重なった：先の実行のロック（ID=A）が生きていて、後の実行（ID=B）が来た
    ok, kind, _ = lc.judge(lock_text(ALIVE, "プランニング（09:00開始）", "A.1"), "B.2")
    assert not ok and kind == "other", (ok, kind)
    # 先の実行のほうは開ける
    ok2, kind2, _ = lc.judge(lock_text(ALIVE, "プランニング（09:00開始）", "A.1"), "A.1")
    assert ok2 and kind2 == "own", (ok2, kind2)


@case
def j5_no_lock_opens():
    ok, kind, _ = lc.judge(None, None)
    assert ok and kind == "none", (ok, kind)


@case
def j6_old_format_lock_without_id():
    # ID の無い古い形式（2行）のロック：PID が生きていれば、自動実行の中でも「ほか」扱い（安全側）。死んでいれば古いロック
    ok, kind, _ = lc.judge(lock_text(ALIVE, "プランニング（09:00開始）"), "A.1")
    assert not ok and kind == "other", (ok, kind)
    ok2, kind2, _ = lc.judge(lock_text(DEAD, "プランニング（09:00開始）"), "A.1")
    assert ok2 and kind2 == "stale", (ok2, kind2)


@case
def j7_broken_lock_is_stale():
    # PID が読めない・空：daily_cycle.sh の kill -0 と同じく古いロック扱い
    for t in ("", "\n", "abc\nx\ny\n", "0\nx\n", "-5\nx\n"):
        ok, kind, _ = lc.judge(t, "A.1")
        assert ok and kind == "stale", (t, ok, kind)


@case
def j8_parse_lock():
    assert lc.parse_lock("12\n振り返り（17:00開始）\n12.99\n") == (12, "振り返り（17:00開始）", "12.99")
    assert lc.parse_lock("12\nラベル\n") == (12, "ラベル", None)
    assert lc.parse_lock("12\n")[1:] == (None, None)


# ---------- コマンド（本人のフォルダの .lock を読む） ----------

def make_owner(name):
    root = os.path.join(BASE, name)
    os.makedirs(os.path.join(root, "scripts", "auto"))
    os.makedirs(os.path.join(root, "00_タスク管理", "data"))
    open(os.path.join(root, "00_タスク管理", "data", "tasks.json"), "w").write("{}")
    return root


def run_cli(root, run_id=None, via="root"):
    env = {k: v for k, v in os.environ.items() if k not in (lc.ENV_NAME, "AI_BUNSHIN_HOME", "CLAUDE_PROJECT_DIR")}
    if run_id:
        env[lc.ENV_NAME] = run_id
    args = [sys.executable, LOCK_CHECK]
    cwd = BASE
    if via == "root":
        args += ["--root", root]
    elif via == "home":
        env["AI_BUNSHIN_HOME"] = root
    elif via == "cwd":
        cwd = os.path.join(root, "scripts")
    r = subprocess.run(args, capture_output=True, text=True, env=env, cwd=cwd)
    assert r.returncode == 0, (r.returncode, r.stderr[:200])
    return r.stdout.strip()


@case
def c1_cli_four_cases():
    root = make_owner("cli")
    lock = os.path.join(root, "scripts", "auto", ".lock")
    assert run_cli(root).startswith("OPEN: ロックなし")
    open(lock, "w", encoding="utf-8").write(lock_text(ALIVE, "振り返り（17:00開始）", "9.1"))
    assert run_cli(root, "9.1").startswith("OPEN: 自分の実行のロック"), run_cli(root, "9.1")       # 自動の振り返り
    assert run_cli(root, None).startswith("SKIP: ほかの実行が動いている"), run_cli(root, None)    # 会話から
    assert run_cli(root, "9.2").startswith("SKIP: ほかの実行が動いている"), run_cli(root, "9.2")  # 自動同士の重なり
    open(lock, "w", encoding="utf-8").write(lock_text(DEAD, "振り返り（17:00開始）", "9.1"))
    assert run_cli(root, None).startswith("OPEN: 古いロック"), run_cli(root, None)                # 古いロック
    # 読むだけ：ロックを消したり書き換えたりしない
    assert open(lock, encoding="utf-8").read() == lock_text(DEAD, "振り返り（17:00開始）", "9.1")


@case
def c2_cli_finds_root_by_env_and_cwd():
    root = make_owner("cli2")
    open(os.path.join(root, "scripts", "auto", ".lock"), "w", encoding="utf-8").write(lock_text(ALIVE, "プランニング（09:00開始）", "1.1"))
    assert run_cli(root, None, via="home").startswith("SKIP:")
    assert run_cli(root, "1.1", via="home").startswith("OPEN: 自分")
    assert run_cli(root, None, via="cwd").startswith("SKIP:")     # 会話：本人のフォルダの中から


@case
def c3_cli_unreadable_lock_is_safe_side():
    root = make_owner("cli3")
    lock = os.path.join(root, "scripts", "auto", ".lock")
    os.makedirs(lock)   # ファイルでなくフォルダ → 読めない
    assert run_cli(root).startswith("SKIP: ロックを読めない"), run_cli(root)


# ---------- daily_cycle.sh が ID を渡す（作り物の claude で通して動かす） ----------

def make_fake_plugin(name, phase_stub):
    """一時フォルダに、プラグインの scripts/ を作る：daily_cycle.sh（本物のコピー）・lock_check.py（本物のコピー）・
    update_dashboard.py（作り物）。本人のフォルダと、claude・osascript の作り物も作る。"""
    d = os.path.join(BASE, name)
    plugin = os.path.join(d, "plugin")
    os.makedirs(os.path.join(plugin, "scripts", "auto"))
    shutil.copy(CYCLE, os.path.join(plugin, "scripts", "auto", "daily_cycle.sh"))
    shutil.copy(LOCK_CHECK, os.path.join(plugin, "scripts", "lock_check.py"))
    # T095：時間の上限・見張りの点検の道具（daily_cycle.sh が使う）。見張りは本物のコピー（点検が通る）
    for f in ("watch_check.py", "ng_guard.py", "ng_guard_legacy.py"):
        shutil.copy(os.path.join(SCRIPTS, f), os.path.join(plugin, "scripts", f))
    shutil.copy(os.path.join(SCRIPTS, "auto", "run_limited.py"), os.path.join(plugin, "scripts", "auto", "run_limited.py"))
    open(os.path.join(plugin, "scripts", "update_dashboard.py"), "w", encoding="utf-8").write(phase_stub)
    home = os.path.join(d, "owner")
    os.makedirs(os.path.join(home, "設定"))
    os.makedirs(os.path.join(home, "scripts", "auto"))
    os.makedirs(os.path.join(home, "00_タスク管理", "data"))
    open(os.path.join(home, "設定", "config.json"), "w", encoding="utf-8").write('{"ai_name": "テストAI"}')
    open(os.path.join(home, "00_タスク管理", "data", "tasks.json"), "w").write("{}")
    bindir = os.path.join(d, "bin")
    os.makedirs(bindir)
    rec = os.path.join(d, "claude_calls.txt")
    # 作り物の claude：受け取った環境変数・ロックの中身・lock_check.py の答えを記録して、何か出力する
    fake = f'''#!/bin/sh
{{
  echo "skill=$2"
  echo "env=$AI_BUNSHIN_AUTO_RUN"
  echo "lock3=$(sed -n 3p "$AI_BUNSHIN_HOME/scripts/auto/.lock")"
  echo "lock2=$(sed -n 2p "$AI_BUNSHIN_HOME/scripts/auto/.lock")"
  echo "verdict=$({sys.executable} "{os.path.join(plugin, 'scripts', 'lock_check.py')}")"
  echo "--"
}} >> "{rec}"
# make_minutes という印があれば、議事録（今日の daily/YYYYMMDD_振り返り.md）を作る（本物の振り返りが書いたつもり）
if [ -f "$AI_BUNSHIN_HOME/make_minutes" ]; then
  mkdir -p "$AI_BUNSHIN_HOME/01_スプリント/S1/daily" && echo "# 議事録" > "$AI_BUNSHIN_HOME/01_スプリント/S1/daily/$(date +%Y%m%d)_振り返り.md"
fi
echo "done"
'''
    open(os.path.join(bindir, "claude"), "w").write(fake)
    open(os.path.join(bindir, "osascript"), "w").write("#!/bin/sh\nexit 0\n")   # 通知は出さない
    os.chmod(os.path.join(bindir, "claude"), 0o755)
    os.chmod(os.path.join(bindir, "osascript"), 0o755)
    return plugin, home, bindir, rec


def run_cycle(plugin, home, bindir, phase):
    env = {k: v for k, v in os.environ.items() if k not in (lc.ENV_NAME, "CLAUDE_PROJECT_DIR")}
    env["AI_BUNSHIN_HOME"] = home
    env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
    return subprocess.run(["/bin/zsh", os.path.join(plugin, "scripts", "auto", "daily_cycle.sh"), phase],
                          capture_output=True, text=True, env=env, timeout=60)


REVIEW_STUB = '''import sys, time
a = sys.argv[1:]
if "--session" in a:
    sys.exit(0)
print("OPEN")
print("議事録の保存先: 01_スプリント/S1/daily/" + time.strftime("%Y%m%d") + "_振り返り.md")
'''

PLAN_STUB = '''import os, sys
a = sys.argv[1:]
if "--session" in a:
    sys.exit(0)
if "--plan-context" in a:
    n = os.path.join(os.environ["AI_BUNSHIN_HOME"], "plan_calls")
    c = int(open(n).read()) if os.path.exists(n) else 0
    open(n, "w").write(str(c + 1))
    print("OPEN" if c == 0 else "今日の計画は作成済み")   # 1回目＝計画がまだ。2回目＝計画のあと
'''


def parse_rec(path):
    calls = []
    for blk in open(path, encoding="utf-8").read().split("--\n"):
        if blk.strip():
            calls.append(dict(line.split("=", 1) for line in blk.strip().splitlines()))
    return calls


@case
def s1_daily_cycle_review_passes_same_id_to_claude_and_lock():
    plugin, home, bindir, rec = make_fake_plugin("cycle_review", REVIEW_STUB)
    r = run_cycle(plugin, home, bindir, "review")
    assert r.returncode == 0, (r.returncode, r.stdout[:200], r.stderr[:300])
    calls = parse_rec(rec)
    assert len(calls) == 1, calls
    c = calls[0]
    assert c["skill"] == "/ai-bunshin:daily-review", c
    assert c["env"] and c["env"] == c["lock3"], f"環境変数とロックの ID が違う：{c}"
    assert c["lock2"].startswith("振り返り（"), c        # 2行目は段階の名前（ログの表示用）
    assert c["verdict"].startswith("OPEN: 自分の実行のロック"), c   # 自動の振り返りは自分のロックで止まらない
    # 終わったらロックは消える
    assert not os.path.exists(os.path.join(home, "scripts", "auto", ".lock"))


@case
def s2_daily_cycle_plan_then_do_keeps_one_id():
    plugin, home, bindir, rec = make_fake_plugin("cycle_plan", PLAN_STUB)
    r = run_cycle(plugin, home, bindir, "plan")
    assert r.returncode == 0, (r.returncode, r.stdout[:200], r.stderr[:300])
    calls = parse_rec(rec)
    assert [c["skill"] for c in calls] == ["/ai-bunshin:daily-plan", "/ai-bunshin:daily-do"], calls
    for c in calls:
        assert c["env"] and c["env"] == c["lock3"], f"環境変数とロックの ID が違う：{c}"
        assert c["verdict"].startswith("OPEN: 自分の実行のロック"), c
    assert calls[0]["env"] == calls[1]["env"], "計画と実行で ID が変わった"
    assert calls[0]["lock2"].startswith("プランニング（") and calls[1]["lock2"].startswith("実行（"), calls


@case
def s3_daily_cycle_stale_lock_is_ignored_and_replaced():
    plugin, home, bindir, rec = make_fake_plugin("cycle_stale", REVIEW_STUB)
    lock = os.path.join(home, "scripts", "auto", ".lock")
    open(lock, "w", encoding="utf-8").write(lock_text(DEAD, "実行（09:00開始）", "old.1"))   # 古い2行・3行ロック
    r = run_cycle(plugin, home, bindir, "review")
    assert r.returncode == 0, (r.returncode, r.stdout[:200], r.stderr[:300])
    c = parse_rec(rec)[0]
    assert c["env"] == c["lock3"] and c["env"] != "old.1", c
    log = [f for f in os.listdir(os.path.join(home, "scripts", "auto", "logs"))][0]
    text = open(os.path.join(home, "scripts", "auto", "logs", log), encoding="utf-8").read()
    assert "古いロック（実行（09:00開始）、PID" in text, text    # 2行目（段階の名前）がログに出る


@case
def s4_guard_in_allowed_tools():
    # 自動実行の中の Claude が lock_check.py を使える（許可リストに入っている）
    src = open(CYCLE, encoding="utf-8").read()
    assert "Bash(python3 *lock_check.py*)" in src


# ---------- 直し（部下D の確かめへの対応） ----------

# 1. 起動時のまとめの「⏳ 自動実行中」：ID を見せない・1行・lock_check.py へ案内
def run_session(root):
    env = {k: v for k, v in os.environ.items() if k not in (lc.ENV_NAME, "AI_BUNSHIN_HOME", "CLAUDE_PROJECT_DIR")}
    env["HOME"] = os.path.join(BASE, "fakehome")
    os.makedirs(env["HOME"], exist_ok=True)
    env["CLAUDE_PROJECT_DIR"] = root
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "update_dashboard.py"), "--session"],
                       capture_output=True, text=True, cwd=root, env=env)
    assert r.returncode == 0, (r.returncode, r.stderr[:300])
    import json
    return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]


def make_session_owner(name):
    import json
    root = make_owner(name)
    os.makedirs(os.path.join(root, "設定"), exist_ok=True)
    json.dump({"owner": "テスト", "owner_call": "テストさん", "ai_name": "テストAI", "departments": ["総務"]},
              open(os.path.join(root, "設定", "config.json"), "w", encoding="utf-8"), ensure_ascii=False)
    json.dump({"project": {"name": "テストAI", "daily_capacity_default": 8.0, "holidays": []}, "daily_sprints": [], "sprints": [],
               "tasks": [{"id": "T001", "title": "テスト用", "status": "ToDo", "assignee": "dev-a", "type": "開発", "reviewer": "dev-b",
                          "points": 2, "department": "総務", "priority": 1}]},
              open(os.path.join(root, "00_タスク管理", "data", "tasks.json"), "w", encoding="utf-8"), ensure_ascii=False)
    return root


def lock_lines(ctx):
    return [ln for ln in ctx.splitlines() if "自動実行中" in ln]


@case
def d1_session_banner_hides_run_id():
    root = make_session_owner("sess1")
    run_id = "98765.1793403910"
    open(os.path.join(root, "scripts", "auto", ".lock"), "w", encoding="utf-8").write(lock_text(ALIVE, "振り返り（17:00開始）", run_id))
    ctx = run_session(root)
    ls = lock_lines(ctx)
    assert len(ls) == 1, ls
    line = ls[0]
    assert run_id not in ctx, "実行の ID が AI に見えている"
    assert str(ALIVE) in line and "振り返り（17:00開始）" in line, line      # PID と段階名は同じ1行に出す（表示が崩れない）
    assert "tasks.json の同時編集に注意" in line, line                         # 今までの注意は残す
    assert "lock_check.py" in line and "1行目" in line, line                 # 自分かどうかは lock_check.py に任せる案内


@case
def d2_session_banner_old_two_line_lock_and_empty_lock():
    root = make_session_owner("sess2")
    lock = os.path.join(root, "scripts", "auto", ".lock")
    open(lock, "w", encoding="utf-8").write(lock_text(ALIVE, "プランニング（09:00開始）"))   # ID の無い古い形式
    ls = lock_lines(run_session(root))
    assert len(ls) == 1 and "プランニング（09:00開始）" in ls[0] and "lock_check.py" in ls[0], ls
    open(lock, "w", encoding="utf-8").write("")                                            # 空のロックでも落ちない
    assert len(lock_lines(run_session(root))) == 1


# 3. 壊れたロックへの強さ
@case
def b1_pid_alive_overflow_and_value_errors():
    for pid in (10 ** 30, 2 ** 63, 2 ** 31, -(10 ** 30)):
        assert lc.pid_alive(pid) is False, pid
    ok, kind, _ = lc.judge("99999999999999999999999999\nx\ny\n", "A.1")
    assert ok and kind == "stale", (ok, kind)


@case
def b2_cli_huge_pid_and_binary_lock():
    root = make_owner("broken")
    lock = os.path.join(root, "scripts", "auto", ".lock")
    open(lock, "w", encoding="utf-8").write("99999999999999999999999999\nx\ny\n")
    assert run_cli(root).startswith("OPEN: 古いロック"), run_cli(root)       # 落ちずに、古いロックとして開く
    open(lock, "wb").write(b"\xff\xfe\x80abc\n\x00\n")                       # UTF-8 として読めない
    out = run_cli(root)                                                      # 終了コード 0（run_cli が確かめる）
    assert out.startswith("SKIP: ロックを読めない"), out


# 4. 振り返りのあとに議事録が無ければ、ログに警告
def cycle_log(home):
    d = os.path.join(home, "scripts", "auto", "logs")
    return open(os.path.join(d, os.listdir(d)[0]), encoding="utf-8").read()


@case
def w1_review_without_minutes_logs_warning():
    plugin, home, bindir, rec = make_fake_plugin("cycle_nominutes", REVIEW_STUB)
    r = run_cycle(plugin, home, bindir, "review")
    assert r.returncode == 0, (r.returncode, r.stderr[:300])
    warn = [ln for ln in cycle_log(home).splitlines() if "警告" in ln and "議事録" in ln]
    assert len(warn) == 1, cycle_log(home)
    assert "_振り返り.md" in warn[0] and warn[0].startswith(tuple("[")), warn


@case
def w2_review_with_minutes_has_no_warning():
    plugin, home, bindir, rec = make_fake_plugin("cycle_minutes", REVIEW_STUB)
    open(os.path.join(home, "make_minutes"), "w").write("")
    r = run_cycle(plugin, home, bindir, "review")
    assert r.returncode == 0, (r.returncode, r.stderr[:300])
    assert "警告" not in cycle_log(home), cycle_log(home)


@case
def w3_plan_and_do_never_warn_about_minutes():
    plugin, home, bindir, rec = make_fake_plugin("cycle_plan_nowarn", PLAN_STUB)
    r = run_cycle(plugin, home, bindir, "plan")
    assert r.returncode == 0, (r.returncode, r.stderr[:300])
    assert "警告" not in cycle_log(home), cycle_log(home)


alive_proc.terminate()
alive_proc.wait()
print(f"失敗 {fails} 件（{len(names)} 項目）")
sys.exit(1 if fails else 0)
