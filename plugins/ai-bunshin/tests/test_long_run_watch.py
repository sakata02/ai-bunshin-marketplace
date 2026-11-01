"""長引き・止まりに気づく仕組み（T095）のテスト。破られ方を先に書いたもの。
- run_limited.py：上限で止まる（孫も）／おとり（同じ名前の無関係なプロセス）は残る／終了コード 124／TERM を無視しても KILL／上限より早ければ何もしない
- watch_check.py：時間の上限の設定（上書き・0・文字・真偽・負・壊れた config は既定）／ng_log の数え方（3回で出る・2回で出ない・24時間の境目・
  壊れた行・ng_log が無い・ほかのラベル・BROKEN_LABEL を ng_guard.py から読む）／canary（正常・SyntaxError・全部 deny・全部 pass・無い・時間切れ）
- 起動時のまとめ（update_dashboard.py --session）：警告が出力の先頭 1,500 バイト以内／出ない場合／見張りが壊れたコピーで出る
- daily_cycle.sh（作り物の claude・osascript・update_dashboard で動かす）：上限で止まる（孫も・おとりは残る・ロックが消える・ログ・通知・印・exit 124）／
  計画で止まったら実行に入らない／上限より早く終われば前と同じ／設定で上書き／不正な値は既定／見張りが壊れていれば claude を起動しない／
  実行中に「読めませんでした」が3回で警告・2回で出ない／同じ段階の成功で印が消える
本物の claude・launchd・ロック・ログ・本人のフォルダには触らない（すべて一時フォルダ）。止める対象は自分が起動したグループだけ。
実行：python3 tests/test_long_run_watch.py（失敗があれば終了コード1）"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.path.join(HERE, ".."))
SCRIPTS = os.path.join(PLUGIN, "scripts")
sys.path.insert(0, SCRIPTS)
import watch_check as wc  # noqa: E402

REAL_GUARD = os.path.join(SCRIPTS, "ng_guard.py")

BASE = os.path.realpath(tempfile.mkdtemp(prefix="longrun_"))
FAKE_HOME = os.path.join(BASE, "home")
os.makedirs(FAKE_HOME)
fails = 0
CHILDREN = []   # テストが起動したプロセス（最後に必ず止める）


def case(fn):
    global fails
    try:
        fn()
        print(f"  ok   {fn.__name__}")
    except AssertionError as e:
        fails += 1
        print(f"  FAIL {fn.__name__}: {e}")
    except Exception as e:  # noqa: BLE001
        fails += 1
        print(f"  FAIL {fn.__name__}: {e.__class__.__name__}: {e}")
    return fn


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # ゾンビは「動いていない」とみなす
    r = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return bool(r.stdout.strip()) and not r.stdout.strip().startswith("Z")


def wait_dead(pid, sec=5):
    t0 = time.time()
    while time.time() - t0 < sec:
        if not alive(pid):
            return True
        time.sleep(0.1)
    return not alive(pid)


def start_decoy(name):
    """おとり：別のセッションで動く、同じ名前（claude）の無関係なプロセス。止められてはいけない。"""
    d = os.path.join(BASE, "decoy_" + name)
    os.makedirs(d, exist_ok=True)
    script = os.path.join(d, "claude")
    open(script, "w").write("#!/bin/sh\nsleep 300\n")
    os.chmod(script, 0o755)
    p = subprocess.Popen([script, "-p", "decoy"], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    CHILDREN.append(p)
    time.sleep(0.3)
    return p


def pid_from(path, sec=5):
    t0 = time.time()
    while time.time() - t0 < sec:
        try:
            t = open(path).read().strip()
            if t:
                return int(t)
        except (OSError, ValueError):
            pass
        time.sleep(0.05)
    raise AssertionError(f"{path} に PID が書かれない")


def copy_plugin(name):
    dst = os.path.join(BASE, name)
    shutil.copytree(PLUGIN, dst, ignore=shutil.ignore_patterns("__pycache__", "tests", ".git"))
    return dst


# ---------- 1. run_limited.py ----------
print("## 1. 時間の上限つきの起動（run_limited.py）")
LIMITED = os.path.join(SCRIPTS, "auto", "run_limited.py")


def run_limited(args, cmd, timeout=60):
    return subprocess.run([sys.executable, LIMITED, *args, "--", *cmd], capture_output=True, text=True, timeout=timeout)


def grandchild_script(name, ignore_term=False):
    """親（sh）が孫（sleep）を起動する作り物。孫の PID を ファイルに書く。"""
    d = os.path.join(BASE, name)
    os.makedirs(d, exist_ok=True)
    pidf = os.path.join(d, "grand.pid")
    trap = "trap '' TERM\n" if ignore_term else ""
    script = os.path.join(d, "run.sh")
    # 孫も TERM を無視する形（ignore_term）なら、KILL でしか止まらない
    inner = "sh -c \"trap '' TERM; sleep 120\" &" if ignore_term else "sleep 120 &"
    open(script, "w").write(f"#!/bin/sh\n{trap}{inner}\necho $! > '{pidf}'\necho partial-output\nwait\n")
    os.chmod(script, 0o755)
    return script, pidf


@case
def l1_limit_stops_child_and_grandchild_exit_124_decoy_survives():
    decoy = start_decoy("l1")
    script, pidf = grandchild_script("l1")
    out = os.path.join(BASE, "l1.out")
    t0 = time.time()
    r = run_limited(["--minutes", "0.04", "--stdout", out], [script])
    dt = time.time() - t0
    assert r.returncode == 124, (r.returncode, r.stderr[:200])
    assert dt < 15, f"止まるのが遅い：{dt:.1f}秒"
    gp = pid_from(pidf)
    assert wait_dead(gp), "孫のプロセスが残っている"
    assert decoy.poll() is None and alive(decoy.pid), "同じ名前の無関係なプロセス（おとり）まで止めた"
    assert "partial-output" in open(out).read(), "止める前までの出力が一時ファイルに残らない"


@case
def l2_term_ignored_is_killed_after_grace():
    script, pidf = grandchild_script("l2", ignore_term=True)
    out = os.path.join(BASE, "l2.out")
    t0 = time.time()
    r = run_limited(["--minutes", "0.03", "--grace", "1", "--stdout", out], [script])
    dt = time.time() - t0
    assert r.returncode == 124, r.returncode
    assert dt < 15, dt
    assert wait_dead(pid_from(pidf)), "TERM を無視する孫が KILL されない"


@case
def l3_finishing_early_does_nothing():
    out = os.path.join(BASE, "l3.out")
    r = run_limited(["--minutes", "5", "--stdout", out], ["sh", "-c", "echo hello; exit 0"])
    assert r.returncode == 0 and open(out).read().strip() == "hello", (r.returncode, r.stderr)
    r = run_limited(["--minutes", "5", "--stdout", out], ["sh", "-c", "echo bye; exit 3"])
    assert r.returncode == 3, r.returncode          # ふつうの失敗はそのまま返す（124 にしない）
    r = run_limited(["--minutes", "5", "--stdout", out], ["sh", "-c", "kill -9 $$"])
    assert r.returncode == 128 + 9, r.returncode


@case
def l4_bad_arguments_and_missing_command():
    out = os.path.join(BASE, "l4.out")
    assert run_limited(["--minutes", "0", "--stdout", out], ["true"]).returncode == 64
    assert run_limited(["--minutes", "-1", "--stdout", out], ["true"]).returncode == 64
    assert run_limited(["--minutes", "1", "--stdout", out], ["/no/such/command"]).returncode == 127


# ---------- 2. 時間の上限の設定 ----------
print("## 2. 時間の上限の設定（auto.max_minutes）")


def make_owner(name, cfg=None):
    root = os.path.join(BASE, name)
    os.makedirs(os.path.join(root, "設定"))
    os.makedirs(os.path.join(root, "scripts", "auto"))
    os.makedirs(os.path.join(root, "00_タスク管理", "data"))
    c = {"owner": "テスト", "owner_call": "テストさん", "ai_name": "テストAI", "departments": ["総務"]}
    c.update(cfg or {})
    json.dump(c, open(os.path.join(root, "設定", "config.json"), "w", encoding="utf-8"), ensure_ascii=False)
    json.dump({"project": {"name": "テストAI", "daily_capacity_default": 8.0, "holidays": []}, "daily_sprints": [], "sprints": [],
               "tasks": [{"id": "T001", "title": "テスト用", "status": "ToDo", "assignee": "dev-a", "type": "開発", "reviewer": "dev-b",
                          "points": 2, "department": "総務", "priority": 1}]},
              open(os.path.join(root, "00_タスク管理", "data", "tasks.json"), "w", encoding="utf-8"), ensure_ascii=False)
    return root


@case
def m1_defaults_60_180_60():
    root = make_owner("m1")
    assert [wc.minutes_for(root, p) for p in ("plan", "do", "review")] == [60, 180, 60]
    assert wc.wait_minutes(root, "plan") == 60 and wc.wait_minutes(root, "do") == 60 and wc.wait_minutes(root, "review") == 180


@case
def m2_config_overrides_per_phase_and_wait_follows():
    root = make_owner("m2", {"auto": {"max_minutes": {"plan": 30, "do": 90, "review": 45}}})
    assert [wc.minutes_for(root, p) for p in ("plan", "do", "review")] == [30, 90, 45]
    assert wc.wait_minutes(root, "review") == 90 and wc.wait_minutes(root, "plan") == 30   # MAX_WAIT は同じ設定から
    root = make_owner("m2b", {"auto": {"max_minutes": {"do": 0.05}}})
    assert wc.minutes_for(root, "do") == 0.05 and wc.minutes_for(root, "plan") == 60       # 書いた段階だけ変わる
    root = make_owner("m2c", {"auto": {"max_minutes": 45}})
    assert [wc.minutes_for(root, p) for p in ("plan", "do", "review")] == [45, 45, 45]    # 1つの数なら全段階


@case
def m3_invalid_values_fall_back_to_default():
    for i, bad in enumerate((0, -5, "abc", "90", True, False, None, [], {}, float("inf"), float("nan"), {"do": 0}, {"do": "x"}, {"do": True}, {"do": None})):
        root = make_owner(f"m3_{i}", {"auto": {"max_minutes": bad}})
        assert wc.minutes_for(root, "do") == 180, (bad, wc.minutes_for(root, "do"))
    # config が無い・壊れている
    root = make_owner("m3b")
    open(os.path.join(root, "設定", "config.json"), "w").write("{broken")
    assert wc.minutes_for(root, "plan") == 60
    os.remove(os.path.join(root, "設定", "config.json"))
    assert wc.minutes_for(root, "review") == 60
    root = make_owner("m3c", {"auto": "oops"})
    assert wc.minutes_for(root, "do") == 180


@case
def m4_cli_prints_minutes():
    root = make_owner("m4", {"auto": {"max_minutes": {"do": 0}}})
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "watch_check.py"), "minutes", root, "do"], capture_output=True, text=True)
    assert r.stdout.strip() == "180", r.stdout
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "watch_check.py"), "wait-minutes", root, "review"], capture_output=True, text=True)
    assert r.stdout.strip() == "180", r.stdout


# ---------- 3. ng_log の「読めませんでした」 ----------
print("## 3. ng_log の数え方")
LABEL = wc.broken_label()
NOW = datetime(2026, 11, 1, 12, 0, 0)


def write_log(root, lines):
    p = os.path.join(root, "00_タスク管理", "data", "ng_log.jsonl")
    with open(p, "wb") as f:
        for ln in lines:
            f.write((ln if isinstance(ln, bytes) else ln.encode("utf-8")) + b"\n")


def rec(at, label=None):
    return json.dumps({"at": at.strftime("%Y-%m-%d %H:%M:%S"), "tool": "Bash", "label": label or LABEL, "target": "（入力不明）"}, ensure_ascii=False)


def count(root, now=NOW):
    return wc.broken_count(root, now - timedelta(hours=24), now)


@case
def n0_label_comes_from_ng_guard():
    assert LABEL == "見張りの入力を読めませんでした", LABEL
    # 別の語に差し替えた見張りなら、その語を数える（写していない証拠）
    d = os.path.join(BASE, "n0")
    os.makedirs(d)
    open(os.path.join(d, "ng_guard.py"), "w").write('BROKEN_LABEL = "別の語です"\n')
    assert wc.broken_label(os.path.join(d, "ng_guard.py")) == "別の語です"
    root = make_owner("n0r")
    write_log(root, [rec(NOW - timedelta(minutes=i), "別の語です") for i in range(3)] + [rec(NOW - timedelta(minutes=9))] * 5)
    assert wc.broken_count(root, NOW - timedelta(hours=24), NOW, os.path.join(d, "ng_guard.py")) == 3
    assert wc.broken_label(os.path.join(d, "none.py")) is None
    assert wc.broken_count(root, NOW - timedelta(hours=24), NOW, os.path.join(d, "none.py")) == 0   # 語が読めなければ数えない（落ちない）


@case
def n1_three_or_more_counts_two_does_not_warn():
    root = make_owner("n1")
    write_log(root, [rec(NOW - timedelta(minutes=i)) for i in range(2)])
    assert count(root) == 2 and not [w for w in wc.session_warnings(root, os.path.join(root, "scripts", "auto"), NOW, guard=REAL_GUARD) if "読めない" in w]
    write_log(root, [rec(NOW - timedelta(minutes=i)) for i in range(3)])
    ws = [w for w in wc.session_warnings(root, os.path.join(root, "scripts", "auto"), NOW, guard=REAL_GUARD) if "読めない" in w]
    assert len(ws) == 1 and "3回" in ws[0], ws


@case
def n2_24_hour_boundary():
    root = make_owner("n2")
    write_log(root, [rec(NOW - timedelta(hours=24)),                        # ちょうど 24時間前＝含む
                     rec(NOW - timedelta(hours=24, seconds=1)),             # 1秒前に出る＝含まない
                     rec(NOW - timedelta(hours=23, minutes=59, seconds=59)),
                     rec(NOW),                                              # いま＝含む
                     rec(NOW + timedelta(seconds=1))])                      # 未来＝含まない
    assert count(root) == 3, count(root)


@case
def n3_broken_lines_do_not_crash():
    root = make_owner("n3")
    write_log(root, [b"", b"{not json", b"[1,2,3]", b"null", b"\"str\"", b"\xff\xfe\x80 binary",
                     json.dumps({"label": LABEL}).encode(),                         # at が無い
                     json.dumps({"label": LABEL, "at": "昨日"}).encode(),            # at が読めない
                     json.dumps({"label": LABEL, "at": 12345}).encode(),
                     json.dumps({"at": NOW.strftime("%Y-%m-%d %H:%M:%S"), "label": ["x"]}).encode(),
                     rec(NOW), rec(NOW), rec(NOW)])
    assert count(root) == 3, count(root)


@case
def n4_no_ng_log_and_other_labels():
    root = make_owner("n4")
    assert count(root) == 0                                           # ng_log が無い
    os.makedirs(os.path.join(root, "00_タスク管理", "data", "ng_log.jsonl"))   # フォルダ（読めない）
    assert count(root) == 0
    root = make_owner("n4b")
    write_log(root, [rec(NOW, "削除")] * 5)
    assert count(root) == 0
    assert wc.session_warnings(root, os.path.join(root, "scripts", "auto"), NOW, guard=REAL_GUARD) == []


@case
def n5_broken_since_cli():
    root = make_owner("n5")
    t = datetime.now()
    write_log(root, [rec(t - timedelta(hours=2)), rec(t), rec(t), rec(t)])
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "watch_check.py"), "broken-since", root,
                        (t - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")], capture_output=True, text=True)
    assert r.stdout.strip() == "3", r.stdout


# ---------- 4. 見張りの自己点検（canary） ----------
print("## 4. 見張りの自己点検（canary）")


def fake_guard(name, body):
    d = os.path.join(BASE, name)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "ng_guard.py")
    open(p, "w").write(body)
    return p


SYNTAX_ERROR_GUARD = "def broken(:\n    pass\n"
ALL_DENY_GUARD = 'import sys\nprint("判定：deny")\nprint("理由：全部止める")\n'
ALL_PASS_GUARD = 'import sys\nprint("判定：pass")\nprint("理由：全部通す")\n'
SLOW_GUARD = 'import time\ntime.sleep(60)\n'


@case
def k1_real_guard_is_ok():
    root = make_owner("k1")
    ok, why = wc.canary(root, REAL_GUARD)
    assert ok, why


@case
def k2_broken_guards_are_detected():
    root = make_owner("k2")
    for name, body in (("syn", SYNTAX_ERROR_GUARD), ("deny", ALL_DENY_GUARD), ("pass", ALL_PASS_GUARD)):
        ok, why = wc.canary(root, fake_guard("k2_" + name, body))
        assert not ok and why, (name, ok, why)
    ok, why = wc.canary(root, os.path.join(BASE, "k2_none", "ng_guard.py"))
    assert not ok and "見つかりません" in why, why
    t0 = time.time()
    ok, why = wc.canary(root, fake_guard("k2_slow", SLOW_GUARD), timeout=2)
    assert not ok and time.time() - t0 < 10, (ok, why)


@case
def k3_canary_does_not_write_ng_log_or_owner_records():
    root = make_owner("k3")
    home = os.path.join(BASE, "k3home")
    os.makedirs(home)
    env_home = os.environ.get("HOME")
    os.environ["HOME"] = home
    try:
        ok, _ = wc.canary(root, REAL_GUARD)
    finally:
        os.environ["HOME"] = env_home
    assert ok
    assert not os.path.exists(os.path.join(root, "00_タスク管理", "data", "ng_log.jsonl")), "点検が ng_log に書いた"
    assert not os.path.exists(os.path.join(home, ".ai-bunshin")), "点検が見張りの記録に書いた"


@case
def k4_canary_cli_exit_codes():
    root = make_owner("k4")
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "watch_check.py"), "canary", root], capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout, r.stderr)
    plug = copy_plugin("k4plug")
    open(os.path.join(plug, "scripts", "ng_guard.py"), "w").write(SYNTAX_ERROR_GUARD)
    r = subprocess.run([sys.executable, os.path.join(plug, "scripts", "watch_check.py"), "canary", root], capture_output=True, text=True)
    assert r.returncode == 1 and r.stdout.strip(), (r.returncode, r.stdout)


@case
def k5_canary_works_without_locale():
    # launchd のように文字コードを決めない環境でも、日本語の答えを読めて「正常」になる
    root = make_owner("k5")
    env = {"PATH": os.environ["PATH"], "LC_ALL": "C", "LANG": "C", "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0", "PYTHONIOENCODING": "utf-8", "HOME": FAKE_HOME}
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "watch_check.py"), "canary", root], capture_output=True, env=env)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr[-200:])


# ---------- 5. 起動時のまとめ（--session） ----------
print("## 5. 起動時のまとめ（update_dashboard.py --session）")


def run_session(plugin, root):
    env = {k: v for k, v in os.environ.items() if k not in ("AI_BUNSHIN_AUTO_RUN", "AI_BUNSHIN_HOME")}
    env["HOME"] = FAKE_HOME
    env["CLAUDE_PROJECT_DIR"] = root
    r = subprocess.run([sys.executable, os.path.join(plugin, "scripts", "update_dashboard.py"), "--session"],
                       capture_output=True, text=True, cwd=root, env=env)
    assert r.returncode == 0, (r.returncode, r.stderr[:300])
    return r.stdout


SESSION_PLUGIN = None


def session_plugin():
    global SESSION_PLUGIN
    if SESSION_PLUGIN is None:
        SESSION_PLUGIN = copy_plugin("sess_plugin")
    return SESSION_PLUGIN


@case
def s1_clean_session_has_no_warning():
    root = make_owner("s1")
    out = run_session(session_plugin(), root)
    assert "⚠ 見張り" not in out and "時間の上限" not in out, out[:400]


@case
def s2_all_three_warnings_inside_first_1500_bytes():
    plug = copy_plugin("s2plug")
    open(os.path.join(plug, "scripts", "ng_guard.py"), "w").write(ALL_PASS_GUARD.replace("import sys", "BROKEN_LABEL = \"%s\"" % LABEL))
    root = make_owner("s2")
    now = datetime.now()
    write_log(root, [rec(now - timedelta(minutes=i)) for i in range(5)])
    wc.mark_timeout(os.path.join(root, "scripts", "auto"), "do", 180, now - timedelta(hours=3))
    out = run_session(plug, root)
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "見張りが壊れている可能性" in ctx and "読めない状態が続きました（5回）" in ctx and "時間の上限で止まりました" in ctx, ctx[:600]
    # 出力の先頭 1,500 バイトに3行とも入る（バイトで数える）
    head = out.encode("utf-8")[:1500].decode("utf-8", errors="ignore")
    for key in ("見張りが壊れている可能性", "読めない状態が続きました", "時間の上限で止まりました"):
        assert key in head, f"先頭 1,500 バイトに「{key}」が入っていない"
    print(f"       3行の合計 {len(chr(10).join(ctx.splitlines()[:3]).encode('utf-8'))} バイト")


@case
def s3_two_in_log_does_not_warn_in_session():
    root = make_owner("s3")
    now = datetime.now()
    write_log(root, [rec(now), rec(now)])
    out = run_session(session_plugin(), root)
    assert "読めない状態" not in out, out[:300]
    write_log(root, [rec(now)] * 3)
    out = run_session(session_plugin(), root)
    assert "読めない状態が続きました（3回）" in json.loads(out)["hookSpecificOutput"]["additionalContext"]


@case
def s4_broken_guard_copy_warns_but_summary_still_works():
    plug = copy_plugin("s4plug")
    open(os.path.join(plug, "scripts", "ng_guard.py"), "w").write(SYNTAX_ERROR_GUARD)
    root = make_owner("s4")
    out = run_session(plug, root)
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert ctx.startswith("[⚠ 見張りが壊れている可能性"), ctx[:200]
    assert "タスク状況" in ctx, "警告のせいでふだんのまとめが消えた"
    assert "テストさん" in ctx.splitlines()[0], "本人の呼び方で案内していない"


@case
def s5_timeout_mark_shown_then_expires_and_clears_per_phase():
    root = make_owner("s5")
    auto = os.path.join(root, "scripts", "auto")
    now = datetime.now()
    wc.mark_timeout(auto, "plan", 60, now - timedelta(hours=1))
    ws = wc.session_warnings(root, auto, now, guard=REAL_GUARD)
    assert len(ws) == 1 and "時間の上限で止まりました" in ws[0] and "60分" in ws[0], ws
    assert wc.session_warnings(root, auto, now + timedelta(days=4), guard=REAL_GUARD) == []     # 古い印は出さない
    wc.clear_timeout(auto, "do")                                                                # 別の段階の成功では消えない
    assert wc.read_timeout(auto) is not None
    wc.clear_timeout(auto, "plan")
    assert wc.read_timeout(auto) is None and wc.session_warnings(root, auto, now, guard=REAL_GUARD) == []
    open(os.path.join(auto, wc.TIMEOUT_MARK), "wb").write(b"\xff\xfe broken")                  # 壊れた印でも落ちない
    assert wc.read_timeout(auto) is None and wc.session_warnings(root, auto, now, guard=REAL_GUARD) == []


# ---------- 6. daily_cycle.sh（作り物の claude で通して動かす） ----------
print("## 6. 自動実行（daily_cycle.sh）")
CYCLE = os.path.join(SCRIPTS, "auto", "daily_cycle.sh")

DASH_STUB = '''import os, sys, time
a = sys.argv[1:]
if "--session" in a:
    sys.exit(0)
mode = os.environ.get("STUB_MODE", "plan")
if "--plan-context" in a:
    if mode == "do":
        print("OPEN"); sys.exit(0)
    n = os.path.join(os.environ["AI_BUNSHIN_HOME"], "plan_calls")
    c = int(open(n).read()) if os.path.exists(n) else 0
    open(n, "w").write(str(c + 1))
    print("OPEN" if c == 0 else "今日の計画は作成済み")
if "--review-context" in a:
    print("OPEN")
    print("議事録の保存先: 01_スプリント/S1/daily/" + time.strftime("%Y%m%d") + "_振り返り.md")
'''


def make_cycle(name, claude_body, cfg=None, guard=None):
    d = os.path.join(BASE, name)
    plugin = os.path.join(d, "plugin")
    os.makedirs(os.path.join(plugin, "scripts", "auto"))
    shutil.copy(CYCLE, os.path.join(plugin, "scripts", "auto", "daily_cycle.sh"))
    shutil.copy(LIMITED, os.path.join(plugin, "scripts", "auto", "run_limited.py"))
    for f in ("lock_check.py", "watch_check.py", "ng_guard.py", "ng_guard_legacy.py"):
        shutil.copy(os.path.join(SCRIPTS, f), os.path.join(plugin, "scripts", f))
    if guard is not None:
        open(os.path.join(plugin, "scripts", "ng_guard.py"), "w").write(guard)
    open(os.path.join(plugin, "scripts", "update_dashboard.py"), "w", encoding="utf-8").write(DASH_STUB)
    home = os.path.join(d, "owner")
    os.makedirs(os.path.join(home, "設定"))
    os.makedirs(os.path.join(home, "scripts", "auto"))
    os.makedirs(os.path.join(home, "00_タスク管理", "data"))
    c = {"ai_name": "テストAI"}
    c.update(cfg or {})
    json.dump(c, open(os.path.join(home, "設定", "config.json"), "w", encoding="utf-8"), ensure_ascii=False)
    open(os.path.join(home, "00_タスク管理", "data", "tasks.json"), "w").write("{}")
    bindir = os.path.join(d, "bin")
    os.makedirs(bindir)
    calls = os.path.join(d, "claude_calls.txt")
    notes = os.path.join(d, "notify.txt")
    open(os.path.join(bindir, "claude"), "w").write(f'#!/bin/sh\necho "skill=$2" >> "{calls}"\n{claude_body}\n')
    open(os.path.join(bindir, "osascript"), "w").write(f'#!/bin/sh\necho "$*" >> "{notes}"\nexit 0\n')
    os.chmod(os.path.join(bindir, "claude"), 0o755)
    os.chmod(os.path.join(bindir, "osascript"), 0o755)
    return dict(d=d, plugin=plugin, home=home, bindir=bindir, calls=calls, notes=notes)


def run_cycle(c, phase, mode="plan", timeout=90):
    env = {k: v for k, v in os.environ.items() if k not in ("AI_BUNSHIN_AUTO_RUN", "CLAUDE_PROJECT_DIR")}
    env["AI_BUNSHIN_HOME"] = c["home"]
    env["PATH"] = c["bindir"] + os.pathsep + env.get("PATH", "")
    env["STUB_MODE"] = mode
    env["HOME"] = FAKE_HOME
    return subprocess.run(["/bin/zsh", os.path.join(c["plugin"], "scripts", "auto", "daily_cycle.sh"), phase],
                          capture_output=True, text=True, env=env, timeout=timeout)


def read(p):
    try:
        return open(p, encoding="utf-8").read()
    except OSError:
        return ""


def cycle_log(c):
    d = os.path.join(c["home"], "scripts", "auto", "logs")
    return "".join(read(os.path.join(d, f)) for f in sorted(os.listdir(d))) if os.path.isdir(d) else ""


def calls_of(c):
    return [ln.split("=", 1)[1] for ln in read(c["calls"]).splitlines() if ln.startswith("skill=")]


def hang_body(d, label):
    """上限を超えて居座る作り物の claude：孫（sleep）の PID を書いて、待ち続ける。"""
    return f"sleep 300 &\necho $! > '{d}/{label}.grand'\nwait"


@case
def d1_timeout_stops_group_unlocks_logs_notifies_marks_exit_124():
    decoy = start_decoy("d1")
    d = os.path.join(BASE, "d1")
    c = make_cycle("d1", hang_body(d, "g"), cfg={"auto": {"max_minutes": {"review": 0.05}}})
    t0 = time.time()
    r = run_cycle(c, "review", mode="review")
    dt = time.time() - t0
    assert r.returncode == 124, (r.returncode, r.stdout[:200], r.stderr[:300])
    assert dt < 40, dt
    assert wait_dead(pid_from(os.path.join(d, "g.grand"))), "孫のプロセスが残っている"
    assert decoy.poll() is None and alive(decoy.pid), "おとりを止めた"
    assert not os.path.exists(os.path.join(c["home"], "scripts", "auto", ".lock")), "ロックが残っている"
    log = cycle_log(c)
    assert "時間の上限（0.05分）で止めました" in log, log
    notes = read(c["notes"])
    assert "時間の上限（0.05分）で振り返りを止めました" in notes and "失敗" not in notes, notes
    m = wc.read_timeout(os.path.join(c["home"], "scripts", "auto"))
    assert m and m[1] == "review" and m[2] == "0.05", m
    assert not [f for f in os.listdir(os.path.join(c["home"], "scripts", "auto", "logs")) if f.startswith(".out.")], "一時ファイルが残っている"
    assert not os.path.exists(os.path.join(c["home"], "scripts", "auto", "last_success_review.txt")), "止めたのに成功の記録を書いた"


@case
def d2_stopped_plan_does_not_continue_to_do():
    d = os.path.join(BASE, "d2")
    c = make_cycle("d2", hang_body(d, "g"), cfg={"auto": {"max_minutes": {"plan": 0.05, "do": 5}}})
    r = run_cycle(c, "plan", mode="plan")
    assert r.returncode == 124, (r.returncode, r.stderr[:300])
    assert calls_of(c) == ["/ai-bunshin:daily-plan"], calls_of(c)      # 実行（daily-do）には入らない
    m = wc.read_timeout(os.path.join(c["home"], "scripts", "auto"))
    assert m and m[1] == "plan", m
    assert not os.path.exists(os.path.join(c["home"], "scripts", "auto", ".lock"))


@case
def d3_do_after_plan_uses_do_limit_and_marks_do():
    d = os.path.join(BASE, "d3")
    # 計画はすぐ終わり、実行が居座る。計画の上限は長く、実行の上限だけ短い（段階ごとに上限を決め直している証拠）
    body = f'''case "$2" in
  /ai-bunshin:daily-plan) echo planned ;;
  *) {hang_body(d, "g")} ;;
esac'''
    c = make_cycle("d3", body, cfg={"auto": {"max_minutes": {"plan": 5, "do": 0.05}}})
    t0 = time.time()
    r = run_cycle(c, "plan", mode="plan")
    assert r.returncode == 124 and time.time() - t0 < 40, (r.returncode, r.stderr[:300])
    assert calls_of(c) == ["/ai-bunshin:daily-plan", "/ai-bunshin:daily-do"], calls_of(c)
    m = wc.read_timeout(os.path.join(c["home"], "scripts", "auto"))
    assert m and m[1] == "do" and m[2] == "0.05", m
    assert os.path.exists(os.path.join(c["home"], "scripts", "auto", "last_success_plan.txt"))     # 計画は成功の記録が残る
    assert not os.path.exists(os.path.join(c["home"], "scripts", "auto", ".lock"))


@case
def d4_finishing_before_limit_behaves_as_before():
    c = make_cycle("d4", "echo done")
    r = run_cycle(c, "review", mode="review")
    assert r.returncode == 0, (r.returncode, r.stderr[:300])
    log = cycle_log(c)
    assert "時間の上限（" not in log.replace("時間の上限 ", "") and "止めました" not in log, log
    assert "claude を起動（時間の上限 60分）" in log
    assert wc.read_timeout(os.path.join(c["home"], "scripts", "auto")) is None
    assert os.path.exists(os.path.join(c["home"], "scripts", "auto", "last_success_review.txt"))
    assert not os.path.exists(os.path.join(c["home"], "scripts", "auto", ".lock"))
    assert "done" in read(c["notes"])
    # 失敗の終わり方（終了コード 1）は前と同じ
    c = make_cycle("d4b", "exit 1")
    r = run_cycle(c, "review", mode="review")
    assert r.returncode == 1 and "失敗" in read(c["notes"]), (r.returncode, read(c["notes"]))
    assert wc.read_timeout(os.path.join(c["home"], "scripts", "auto")) is None


@case
def d5_invalid_config_uses_default_in_the_real_run():
    for bad in (0, "abc", -3):
        c = make_cycle("d5_" + str(bad), "echo ok", cfg={"auto": {"max_minutes": {"review": bad}}})
        r = run_cycle(c, "review", mode="review")
        assert r.returncode == 0, (bad, r.returncode)
        assert "時間の上限 60分" in cycle_log(c), (bad, cycle_log(c))


@case
def d6_broken_guard_blocks_launch():
    for name, body in (("syn", SYNTAX_ERROR_GUARD), ("deny", ALL_DENY_GUARD)):
        c = make_cycle("d6_" + name, "echo should-not-run", guard=body)
        r = run_cycle(c, "review", mode="review")
        assert r.returncode == 1, (name, r.returncode)
        assert calls_of(c) == [], f"{name}：壊れた見張りなのに claude を起動した"
        assert "見張りが壊れている可能性があるため、振り返りを始めませんでした" in cycle_log(c), cycle_log(c)
        assert "見張りが壊れている可能性" in read(c["notes"]), read(c["notes"])
        assert not os.path.exists(os.path.join(c["home"], "scripts", "auto", ".lock"))
        assert not os.path.exists(os.path.join(c["home"], "scripts", "auto", "last_success_review.txt"))


def ng_append_body(home, n):
    line = json.dumps({"at": "__NOW__", "tool": "Bash", "label": LABEL, "target": "x"}, ensure_ascii=False)
    log = os.path.join(home, "00_タスク管理", "data", "ng_log.jsonl")
    return f'''for i in $(seq 1 {n}); do
  echo '{line}' | sed "s/__NOW__/$(date '+%Y-%m-%d %H:%M:%S')/" >> '{log}'
done
echo done'''


@case
def d7_three_broken_in_run_warns_two_does_not():
    c3 = make_cycle("d7c", ng_append_body(os.path.join(BASE, "d7c", "owner"), 3))
    r = run_cycle(c3, "review", mode="review")
    assert r.returncode == 0, r.stderr[:300]
    assert "警告：見張りが壊れている可能性（この実行の間に" in cycle_log(c3) and "3回" in cycle_log(c3), cycle_log(c3)
    assert "見張りが壊れている可能性があります（3回）" in read(c3["notes"]), read(c3["notes"])
    c2 = make_cycle("d7b", ng_append_body(os.path.join(BASE, "d7b", "owner"), 2))
    r = run_cycle(c2, "review", mode="review")
    assert r.returncode == 0
    assert "見張りが壊れている可能性" not in cycle_log(c2), cycle_log(c2)
    # この実行より前の古い行は数えない
    c0 = make_cycle("d7d", "echo done")
    old = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    write_log(c0["home"], [json.dumps({"at": old, "label": LABEL})] * 5)
    run_cycle(c0, "review", mode="review")
    assert "見張りが壊れている可能性" not in cycle_log(c0)


@case
def d8_success_of_same_phase_clears_the_mark():
    c = make_cycle("d8", "echo done")
    auto = os.path.join(c["home"], "scripts", "auto")
    wc.mark_timeout(auto, "plan", 60)
    r = run_cycle(c, "review", mode="review")
    assert r.returncode == 0
    assert wc.read_timeout(auto) is not None, "別の段階（振り返り）の成功で、計画の印が消えた"
    wc.mark_timeout(auto, "review", 60)
    r = run_cycle(c, "review", mode="review")
    assert r.returncode == 0 and wc.read_timeout(auto) is None, "同じ段階の成功で印が消えない"


@case
def d9_wait_for_previous_stage_follows_config():
    # 前の段階が動いている（ロックの持ち主が生きている）ときの待ち時間は、同じ設定から出る（review は do の上限）
    c = make_cycle("d9", "echo done", cfg={"auto": {"max_minutes": {"do": 1}}})
    holder = subprocess.Popen(["sleep", "120"])
    CHILDREN.append(holder)
    lock = os.path.join(c["home"], "scripts", "auto", ".lock")
    open(lock, "w").write(f"{holder.pid}\n実行（09:00開始）\nold.1\n")
    t0 = time.time()
    r = run_cycle(c, "review", mode="review", timeout=150)
    dt = time.time() - t0
    assert r.returncode == 1, (r.returncode, r.stderr[:200])
    assert "1分たっても終わらないため中止" in cycle_log(c), cycle_log(c)
    assert 55 < dt < 140, dt


# ---------- 7. ルール・スキル・部下の文（3章・10章5〜6が、どこにあるか） ----------
print("## 7. ルール・スキル・部下の文")


def text_of(*parts):
    return open(os.path.join(PLUGIN, *parts), encoding="utf-8").read()


COMMANDER = text_of("rules", "commander.md")
SPRINT = text_of("skills", "sprint", "SKILL.md")
DEV = text_of("skills", "dev", "SKILL.md")
DAILY_DO = text_of("skills", "daily-do", "SKILL.md")


@case
def t1_commander_has_the_three_short_rules_and_stays_small():
    for key in ("目安の時間を決める", "1pt 15分・2pt 25分・3pt 40分・5pt 60分", "1.5倍", "開始 HH:MM／目安 N分／見る時刻 HH:MM", "部下は部下を呼ばない",
                "長引いたら様子を見る", "15分止まったら終わる背景の Bash を1つだけ", "自動実行では出さない", "git の状態・作業のフォルダの更新時刻・ng_log の最後の行",
                "今どこ？止まってない？", "目安の1/4（最短5分）", "TaskStop", "同じ失敗が2回続いたら3周目に入らない",
                "見張りが壊れて Bash が全部止まったら", "Read しか使えない", "`! …` の1行を頼む"):
        assert key in COMMANDER, key
    assert len(COMMANDER.encode("utf-8")) < 32000, len(COMMANDER.encode("utf-8"))


@case
def t2_sprint_has_the_procedure_for_every_stop_pattern():
    sec = SPRINT[SPRINT.index("### 部下を出したら：長引いたら様子を見る"):SPRINT.index("## 3. Check")]
    for key in ("目安の時間", "開始 HH:MM／目安 N分／見る時刻 HH:MM", "Agent ID の書式は変えない", "run_in_background", "更新が15分止まったら終わる until ループ",
                "前景の sleep は使わない", "Monitor は30分まで", "TaskStop", "自動実行ではタイマーを出さない", "python -c \"import time; time.sleep(N)\"",
                "git の状態", "作業のフォルダの更新時刻", "ng_log.jsonl", "今どこ？止まってない？", "目安の1/4（最短5分）", "節目で指揮官に1行の進み",
                "同じ失敗を2回報告した", "3周目に入らない", "本人に1行のコマンド", "git restore", "使用量の上限で止まったとき", "同じ部下に SendMessage",
                "戻る時刻が分かるときだけ", "見張りが壊れて全員が止まったとき", "Read", "部下は部下を呼ばない", "「様子は？」", "推測で答えず"):
        assert key in sec, key


@case
def t3_dev_has_stop_rules_and_the_replace_procedure():
    for key in ("同じ失敗が2回続いたら3周目に入らず", "目安の時間を決めて指示書の頭に書き", "背景のタイマーを1つだけ", "部下は部下を呼ばない",
                "動いている仕組みを直すとき", "一度に置き換える", ".bak", "mv", "本人用の戻しのコマンド", "date", "マーケットプレイスの元か",
                "--explain \"date\"", "--explain \"rm x\""):
        assert key in DEV, key


@case
def t4_daily_do_and_review_and_plan_know_the_time_limit():
    for key in ("開始 HH:MM／目安 N分／見る時刻 HH:MM", "自動実行ではタイマーを出さない", "auto.max_minutes", "last_timeout.txt", "部下は部下を呼ばない",
                "同じ部下に SendMessage で続きを送る（新しい部下を立てない）", "戻る時刻が分かるときだけ"):
        assert key in DAILY_DO, key
    assert "last_timeout.txt" in text_of("skills", "daily-review", "SKILL.md") and "時間の上限で止まった" in text_of("skills", "daily-review", "SKILL.md")
    plan = text_of("skills", "daily-plan", "SKILL.md")
    assert "last_timeout.txt" in plan and "持ち越し" in plan


@case
def t5_every_agent_does_not_call_other_agents_and_dev_a_has_the_rest():
    for name in ("analyst", "buka-a", "buka-b", "design", "dev-a", "dev-b", "trainer"):
        t = text_of("agents", name + ".md")
        assert "他の部下を呼びません" in t and "同じ失敗が2回続いたとき" in t, name
    a = text_of("agents", "dev-a.md")
    assert "同じ失敗が2回続いたら3周目に入らず" in a and "`.bak` を残し" in a and "改名（`mv`）" in a and "戻しのコマンド" in a
    assert "最大3周" in a   # 今ある文は消えていない


@case
def t6_install_path_copy_is_what_daily_cycle_checks():
    src = text_of("scripts", "auto", "daily_cycle.sh")
    assert 'WATCH="$PLUGIN_ROOT/scripts/watch_check.py"' in src and 'LIMITED="$PLUGIN_ROOT/scripts/auto/run_limited.py"' in src
    assert "pkill" not in src and "killall" not in src
    assert src.index('"$WATCH" canary') < src.index('run_claude "$SKILL"'), "点検が claude の起動より後ろにある"


# ---------- 片づけ ----------
for p in CHILDREN:
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        p.wait(timeout=5)
    except Exception:  # noqa: BLE001
        pass

print(f"\n{'失敗 ' + str(fails) + ' 件' if fails else 'すべて通りました'}")
sys.exit(1 if fails else 0)
