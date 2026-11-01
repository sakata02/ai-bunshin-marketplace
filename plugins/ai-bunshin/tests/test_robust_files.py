"""tasks.json・生成物の書き込みの安全、自動実行の見落とし、tasks.json の版、文字コードのテスト（T073）。
- 書き込み：一時ファイル→置き換え。途中で止まっても（例外・強制終了）tasks.json などが壊れない
- Excel が書けないとき：落ちずに「Excel を閉じてから、もう一度」と1行出し、ほかの生成物（ボード・お願い）は書く
- 自動実行の見落とし：平日に2営業日以上成功がなければ、起動時のまとめの先頭に「⚠ 自動実行が N日 動いていません」（土日・祝日は数えない）
- daily_cycle.sh が段階ごとに最後の成功を記録する（失敗では書かない）／run.sh が、本体が見つからないとき通知する
- tasks.json の版：版が無い・古いと移し（schema_version を足すだけ）、控え .bak_<日付> を残す
- 文字コード：日本語を含む設定を、文字コードを決めない環境（LC_ALL=C・UTF-8 モード無効）でも読める
本物の自分のフォルダは使わない（すべて一時フォルダ。AI_BUNSHIN_HOME で指定。launchd・claude・通知は作り物）。
実行：python3 tests/test_robust_files.py（失敗があれば終了コード1）"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.path.join(HERE, ".."))
SCRIPTS = os.path.join(PLUGIN, "scripts")
DASH = os.path.join(SCRIPTS, "update_dashboard.py")
CYCLE = os.path.join(SCRIPTS, "auto", "daily_cycle.sh")
INSTALL = os.path.join(SCRIPTS, "auto", "install.sh")
LOCK_CHECK = os.path.join(SCRIPTS, "lock_check.py")
TEMPLATE_TASKS = os.path.join(PLUGIN, "templates", "tasks", "tasks.json")

BASE = os.path.realpath(tempfile.mkdtemp(prefix="robust_"))
FAKE_HOME = os.path.join(BASE, "home")
os.makedirs(FAKE_HOME)

fails = 0


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


TASKS = {"project": {"name": "テストAI", "daily_capacity_default": 8.0, "holidays": []},
         "daily_sprints": [], "sprints": [],
         "tasks": [{"id": "T001", "title": "テスト用タスク", "status": "ToDo", "assignee": "dev-a", "type": "開発",
                    "reviewer": "dev-b", "points": 2, "department": "総務", "priority": 1}]}


def make_owner(name, tasks=None, holidays=(), run_sh=False, raw_tasks=None):
    root = os.path.join(BASE, name)
    os.makedirs(os.path.join(root, "設定"))
    os.makedirs(os.path.join(root, "00_タスク管理", "data"))
    os.makedirs(os.path.join(root, "scripts", "auto"))
    with open(os.path.join(root, "設定", "config.json"), "w", encoding="utf-8") as f:
        json.dump({"owner": "テスト", "owner_call": "テストさん", "ai_name": "テストAI", "departments": ["総務"]}, f, ensure_ascii=False)
    t = json.loads(json.dumps(tasks if tasks is not None else TASKS))
    t["project"]["holidays"] = list(holidays)
    with open(os.path.join(root, "00_タスク管理", "data", "tasks.json"), "w", encoding="utf-8") as f:
        f.write(raw_tasks if raw_tasks is not None else json.dumps(t, ensure_ascii=False, indent=2) + "\n")
    if run_sh:
        open(os.path.join(root, "scripts", "auto", "run.sh"), "w").write("#!/bin/zsh\n")
    return root


def tasks_path(root):
    return os.path.join(root, "00_タスク管理", "data", "tasks.json")


def read(path):
    with open(path, "rb") as f:
        return f.read()


# 作り物の launchctl（本物の launchd には触らない）。list <ラベル> は、環境変数 FAKE_LAUNCHCTL_REGISTERED（既定 plan,review）に
# その段階が入っていれば 0（登録あり）、無ければ 113（本物の launchctl list が、登録のないラベルに返す値）
FAKE_BIN = os.path.join(BASE, "fakebin")
os.makedirs(FAKE_BIN)
with open(os.path.join(FAKE_BIN, "launchctl"), "w") as _f:
    _f.write('''#!/bin/sh
if [ "$1" = "list" ] && [ -n "$2" ]; then
  case "$2" in
    *daily-plan)   case ",${FAKE_LAUNCHCTL_REGISTERED-plan,review}," in *,plan,*) exit 0;; esac; exit 113 ;;
    *daily-review) case ",${FAKE_LAUNCHCTL_REGISTERED-plan,review}," in *,review,*) exit 0;; esac; exit 113 ;;
  esac
fi
exit 0
''')
os.chmod(os.path.join(FAKE_BIN, "launchctl"), 0o755)


def env_for(root):
    env = {k: v for k, v in os.environ.items() if k not in ("AI_BUNSHIN_HOME", "CLAUDE_PROJECT_DIR", "FAKE_LAUNCHCTL_REGISTERED")}
    env["HOME"] = FAKE_HOME
    env["AI_BUNSHIN_HOME"] = root
    env["PATH"] = FAKE_BIN + os.pathsep + env.get("PATH", "")
    return env


def run_dash(root, args, env_extra=None):
    env = env_for(root)
    env.update(env_extra or {})
    return subprocess.run([sys.executable, DASH, *args], capture_output=True, text=True, cwd=root, env=env)


def run_driver(root, code, args=None):
    """update_dashboard を取り込んで、関数を差し替えてから動かす（差し替えは子プロセスの中だけ）。"""
    drv = os.path.join(BASE, f"driver_{abs(hash(code))}.py")
    with open(drv, "w", encoding="utf-8") as f:
        f.write(f"import os, sys\nsys.path.insert(0, {SCRIPTS!r})\nimport update_dashboard as ud\n" + code)
    return subprocess.run([sys.executable, drv, *(args or [])], capture_output=True, text=True, cwd=root, env=env_for(root))


def leftovers(folder):
    return [n for n in os.listdir(folder) if n.endswith(".tmp")]


# ---------- 1. 書き込み ----------

@case
def w1_exception_midway_keeps_original():
    root = make_owner("w1")
    before = read(tasks_path(root))
    r = run_driver(root, '''
def boom(fd):
    raise OSError("disk full")
os.fsync = boom
try:
    ud.atomic_write_text(ud.TASKS_JSON, "{ broken")
except OSError:
    print("raised")
''')
    assert "raised" in r.stdout, r.stdout + r.stderr
    assert read(tasks_path(root)) == before, "tasks.json が書き換わった"
    assert not leftovers(os.path.dirname(tasks_path(root))), leftovers(os.path.dirname(tasks_path(root)))


@case
def w2_kill_before_replace_keeps_original():
    root = make_owner("w2")
    before = read(tasks_path(root))
    r = run_driver(root, '''
import signal
real = os.replace
def die(src, dst, *a, **k):
    os.kill(os.getpid(), signal.SIGKILL)   # 置き換える直前に強制終了
os.replace = die
ud.atomic_write_text(ud.TASKS_JSON, "x" * 1000000)
''')
    assert r.returncode != 0, "止まっていない"
    assert read(tasks_path(root)) == before, "強制終了で tasks.json が壊れた"
    json.loads(read(tasks_path(root)).decode("utf-8"))


@case
def w3_generated_files_are_written_via_replace():
    root = make_owner("w3")
    r = run_driver(root, '''
calls = []
real = os.replace
def spy(src, dst, *a, **k):
    calls.append(os.path.basename(str(dst)))
    return real(src, dst, *a, **k)
os.replace = spy
sys.argv = ["x", "--today", "2026-11-02"]
rc = ud.main()
print("CALLS=" + "|".join(calls))
sys.exit(rc)
''')
    assert r.returncode == 0, r.stderr
    calls = re.search(r"CALLS=(.*)", r.stdout).group(1).split("|")
    for want in ("タスク管理.xlsx", "タスクボード.md", "テストさんへのお願い.md", ".snapshot.json"):
        assert want in calls, (want, calls)
    assert not leftovers(os.path.join(root, "00_タスク管理")), "一時ファイルが残った"


@case
def w4_excel_locked_does_not_crash_and_other_files_written():
    root = make_owner("w4")
    r = run_driver(root, '''
real = os.replace
def locked(src, dst, *a, **k):
    if str(dst).endswith("タスク管理.xlsx"):
        raise PermissionError(13, "Permission denied (Excel で開かれている)")
    return real(src, dst, *a, **k)
os.replace = locked
sys.argv = ["x", "--today", "2026-11-02"]
sys.exit(ud.main())
''')
    assert r.returncode == 0, f"落ちた: {r.stderr}"
    assert "Excel を閉じてから、もう一度" in r.stdout, r.stdout
    note_lines = [ln for ln in r.stdout.splitlines() if "Excel を閉じてから" in ln]
    assert len(note_lines) == 1, note_lines
    d = os.path.join(root, "00_タスク管理")
    assert os.path.exists(os.path.join(d, "タスクボード.md")) and os.path.exists(os.path.join(d, "テストさんへのお願い.md")), os.listdir(d)
    assert not os.path.exists(os.path.join(d, "タスク管理.xlsx")), "Excel が作られている"
    assert not leftovers(d), "Excel の一時ファイルが残った"


@case
def w5_excel_locked_keeps_existing_xlsx():
    root = make_owner("w5")
    assert run_dash(root, ["--today", "2026-11-02"]).returncode == 0
    x = os.path.join(root, "00_タスク管理", "タスク管理.xlsx")
    before = read(x)
    r = run_driver(root, '''
real = os.replace
def locked(src, dst, *a, **k):
    if str(dst).endswith("タスク管理.xlsx"):
        raise PermissionError(13, "locked")
    return real(src, dst, *a, **k)
os.replace = locked
sys.argv = ["x", "--today", "2026-11-02"]
sys.exit(ud.main())
''')
    assert r.returncode == 0 and "Excel を閉じてから" in r.stdout, r.stdout + r.stderr
    assert read(x) == before, "開かれている Excel が壊れた"


# ---------- 2. 自動実行の見落とし（2営業日の判定） ----------

def stale_line(root, today):
    r = run_dash(root, ["--session", "--today", today])
    assert r.returncode == 0, r.stderr
    text = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    hit = [ln for ln in text.splitlines() if "自動実行が" in ln and "動いていません" in ln]
    return text, hit


def set_run_sh_mtime(root, day):
    t = datetime.datetime.strptime(day + " 12:00", "%Y-%m-%d %H:%M").timestamp()
    os.utime(os.path.join(root, "scripts", "auto", "run.sh"), (t, t))


def put_success(root, plan, review):
    for ph, d in (("plan", plan), ("review", review)):
        if d:
            with open(os.path.join(root, "scripts", "auto", f"last_success_{ph}.txt"), "w", encoding="utf-8") as f:
                f.write(d + " 09:30\n")


@case
def a1_weekend_is_not_counted():
    # 2026-10-30 は金曜。月曜（11/2）は、土日をはさんでも「動いていない日」は0
    root = make_owner("a1", run_sh=True)
    put_success(root, "2026-10-30", "2026-10-30")
    _, hit = stale_line(root, "2026-11-02")
    assert not hit, hit
    root = make_owner("a1b", run_sh=True)
    put_success(root, "2026-10-30", "2026-10-30")
    _, hit = stale_line(root, "2026-11-03")   # 火曜：月曜の1日だけ
    assert not hit, hit


@case
def a2_two_business_days_warns():
    root = make_owner("a2", run_sh=True)
    put_success(root, "2026-10-30", "2026-10-30")
    text, hit = stale_line(root, "2026-11-04")   # 水曜：月・火の2日
    assert len(hit) == 1 and "2日" in hit[0], hit
    # 4日（金曜から次の金曜）なら 4日
    root = make_owner("a2b", run_sh=True)
    put_success(root, "2026-10-30", "2026-10-30")
    _, hit = stale_line(root, "2026-11-06")      # 金曜：月〜木の4日
    assert len(hit) == 1 and "4日" in hit[0], hit


@case
def a3_holidays_are_not_counted():
    root = make_owner("a3", holidays=["2026-11-02"], run_sh=True)
    put_success(root, "2026-10-30", "2026-10-30")
    _, hit = stale_line(root, "2026-11-04")   # 月曜は祝日 → 火の1日だけ
    assert not hit, hit


@case
def a4_one_stale_phase_is_enough():
    root = make_owner("a4", run_sh=True)
    put_success(root, "2026-11-03", "2026-10-30")   # 計画は動いているが、振り返りだけ止まっている
    _, hit = stale_line(root, "2026-11-05")
    assert len(hit) == 1 and "振り返り" in hit[0], hit


@case
def a5_not_registered_or_no_record_is_silent():
    root = make_owner("a5", run_sh=False)   # 自動実行を登録していない（run.sh が無い）
    put_success(root, "2026-10-01", "2026-10-01")
    _, hit = stale_line(root, "2026-11-04")
    assert not hit, hit
    root = make_owner("a5b", run_sh=True)   # 登録はあるが記録がまだ無い：run.sh の更新時刻（登録した日）を代わりに使う。登録が最近なら静か
    set_run_sh_mtime(root, "2026-11-03")
    _, hit = stale_line(root, "2026-11-04")
    assert not hit, hit
    root = make_owner("a5c", run_sh=True)   # 壊れた記録も「記録なし」と同じ扱い
    set_run_sh_mtime(root, "2026-11-03")
    put_success(root, "ばらばら", "ばらばら")
    _, hit = stale_line(root, "2026-11-04")
    assert not hit, hit


@case
def a6_warning_is_in_first_2kb_even_when_rules_updated_and_many_tasks():
    many = json.loads(json.dumps(TASKS))
    many["tasks"] = [dict(TASKS["tasks"][0], id=f"T{i:03d}", title="長めのタイトル" * 6, priority=i) for i in range(1, 40)]
    root = make_owner("a6", tasks=many, run_sh=True)   # 共通ルールの写しが無い → 「更新されました」の行も先頭に付く
    put_success(root, "2026-10-28", "2026-10-28")
    text, hit = stale_line(root, "2026-11-04")
    assert hit, "警告が出ていない"
    assert "共通ルールが更新されました" in text, "（前提）ルール更新の行が付いていない"
    pos = len(text[:text.index(hit[0])].encode("utf-8"))
    assert pos < 2048 and len(text.encode("utf-8")) > 2048, (pos, len(text.encode("utf-8")))


# ---------- 3. daily_cycle.sh の記録・run.sh の通知（作り物の claude・osascript・update_dashboard で動かす） ----------

STUB_REVIEW = '''import sys, time
a = sys.argv[1:]
if "--session" in a:
    sys.exit(0)
if "--review-context" in a:
    print("SKIP: 動きがない" if __import__("os").path.exists(__import__("os").path.join(__import__("os").environ["AI_BUNSHIN_HOME"], "quiet")) else "OPEN")
    print("議事録の保存先: 01_スプリント/S1/daily/" + time.strftime("%Y%m%d") + "_振り返り.md")
'''
STUB_PLAN = '''import os, sys
a = sys.argv[1:]
if "--session" in a:
    sys.exit(0)
if "--plan-context" in a:
    if os.path.exists(os.path.join(os.environ["AI_BUNSHIN_HOME"], "holiday")):
        print("SKIP: 営業日ではない")
        sys.exit(0)
    n = os.path.join(os.environ["AI_BUNSHIN_HOME"], "plan_calls")
    c = int(open(n).read()) if os.path.exists(n) else 0
    open(n, "w").write(str(c + 1))
    print("OPEN" if c == 0 else "今日の計画は作成済み")
'''


def make_cycle(name, stub, claude_exit=0, ai_name="テストAI", config_extra=None):
    d = os.path.join(BASE, name)
    plugin = os.path.join(d, "plugin")
    os.makedirs(os.path.join(plugin, "scripts", "auto"))
    shutil.copy(CYCLE, os.path.join(plugin, "scripts", "auto", "daily_cycle.sh"))
    shutil.copy(LOCK_CHECK, os.path.join(plugin, "scripts", "lock_check.py"))
    # T095：時間の上限・見張りの点検の道具（daily_cycle.sh が使う）。見張りは本物のコピー（点検が通る）
    for f in ("watch_check.py", "ng_guard.py", "ng_guard_legacy.py"):
        shutil.copy(os.path.join(SCRIPTS, f), os.path.join(plugin, "scripts", f))
    shutil.copy(os.path.join(SCRIPTS, "auto", "run_limited.py"), os.path.join(plugin, "scripts", "auto", "run_limited.py"))
    with open(os.path.join(plugin, "scripts", "update_dashboard.py"), "w", encoding="utf-8") as f:
        f.write(stub)
    home = os.path.join(d, "owner")
    os.makedirs(os.path.join(home, "設定"))
    os.makedirs(os.path.join(home, "scripts", "auto"))
    cfg = {"ai_name": ai_name}
    cfg.update(config_extra or {})
    with open(os.path.join(home, "設定", "config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False)
    bindir = os.path.join(d, "bin")
    os.makedirs(bindir)
    notes = os.path.join(d, "notifications.txt")
    with open(os.path.join(bindir, "claude"), "w") as f:
        f.write(f'#!/bin/sh\necho called >> "$AI_BUNSHIN_HOME/claude_calls"\necho done\nexit {claude_exit}\n')
    with open(os.path.join(bindir, "osascript"), "w") as f:
        f.write(f'#!/bin/sh\necho "$@" >> "{notes}"\nexit 0\n')
    os.chmod(os.path.join(bindir, "claude"), 0o755)
    os.chmod(os.path.join(bindir, "osascript"), 0o755)
    return plugin, home, bindir, notes


def run_cycle(plugin, home, bindir, phase, env_extra=None):
    env = {k: v for k, v in os.environ.items() if k not in ("AI_BUNSHIN_AUTO_RUN", "CLAUDE_PROJECT_DIR")}
    env["AI_BUNSHIN_HOME"] = home
    env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
    env.update(env_extra or {})
    return subprocess.run(["/bin/zsh", os.path.join(plugin, "scripts", "auto", "daily_cycle.sh"), phase],
                          capture_output=True, text=True, env=env, timeout=60)


def stamp(home, phase):
    p = os.path.join(home, "scripts", "auto", f"last_success_{phase}.txt")
    return open(p, encoding="utf-8").read().strip() if os.path.exists(p) else None


TODAY_ISO = subprocess.run(["date", "+%Y-%m-%d"], capture_output=True, text=True).stdout.strip()


@case
def c1_review_success_records_time():
    plugin, home, bindir, _ = make_cycle("c1", STUB_REVIEW)
    r = run_cycle(plugin, home, bindir, "review")
    assert r.returncode == 0, r.stderr
    s = stamp(home, "review")
    assert s and s.startswith(TODAY_ISO), s
    assert stamp(home, "plan") is None
    assert not [n for n in os.listdir(os.path.join(home, "scripts", "auto")) if ".tmp" in n]


@case
def c2_failure_does_not_record():
    plugin, home, bindir, notes = make_cycle("c2", STUB_REVIEW, claude_exit=1)
    r = run_cycle(plugin, home, bindir, "review")
    assert r.returncode == 1, r.returncode
    assert stamp(home, "review") is None, "失敗なのに成功を記録した"
    assert "失敗" in open(notes, encoding="utf-8").read()


@case
def c3_plan_then_do_records_both():
    plugin, home, bindir, _ = make_cycle("c3", STUB_PLAN)
    r = run_cycle(plugin, home, bindir, "plan")
    assert r.returncode == 0, r.stderr
    assert (stamp(home, "plan") or "").startswith(TODAY_ISO) and (stamp(home, "do") or "").startswith(TODAY_ISO), \
        (stamp(home, "plan"), stamp(home, "do"))


@case
def c4_skips_that_are_not_failures_record():
    plugin, home, bindir, _ = make_cycle("c4", STUB_PLAN)
    open(os.path.join(home, "holiday"), "w").write("")
    r = run_cycle(plugin, home, bindir, "plan")
    assert r.returncode == 0 and (stamp(home, "plan") or "").startswith(TODAY_ISO), (r.returncode, stamp(home, "plan"))
    plugin, home, bindir, _ = make_cycle("c4b", STUB_REVIEW)
    open(os.path.join(home, "quiet"), "w").write("")
    r = run_cycle(plugin, home, bindir, "review")
    assert r.returncode == 0 and (stamp(home, "review") or "").startswith(TODAY_ISO), (r.returncode, stamp(home, "review"))


def render_run_sh(root, plugin_root, path_env):
    """install.sh が作る run.sh を、install.sh の中身から取り出して作る（launchd には登録しない）。"""
    text = open(INSTALL, encoding="utf-8").read()
    m = re.search(r'<<RUN\n(.*?)\nRUN\n', text, re.S)
    assert m, "install.sh に run.sh の雛形が見つからない"
    path = os.path.join(root, "scripts", "auto", "run.sh")
    script = f'RUN_PATH="{path_env}"; HOME_DIR="{root}"; PLUGIN_ROOT="{plugin_root}"\ncat <<RUN > "{path}"\n{m.group(1)}\nRUN\n'
    subprocess.run(["/bin/zsh", "-c", script], check=True)
    return path


@case
def c5_run_sh_notifies_when_cycle_script_missing():
    plugin, home, bindir, notes = make_cycle("c5", STUB_REVIEW)
    run_sh = render_run_sh(home, os.path.join(BASE, "c5", "なくなったプラグインの場所"), bindir + os.pathsep + os.environ["PATH"])
    env = env_for(home)
    env["PATH"] = bindir + os.pathsep + env["PATH"]
    r = subprocess.run(["/bin/zsh", run_sh, "plan"], capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 1, (r.returncode, r.stderr)
    assert "始められませんでした" in open(notes, encoding="utf-8").read(), "通知が出ていない"
    logs = os.listdir(os.path.join(home, "scripts", "auto", "logs"))
    assert logs and "見つかりません" in open(os.path.join(home, "scripts", "auto", "logs", logs[0]), encoding="utf-8").read()


@case
def c6_run_sh_runs_cycle_script_when_found():
    plugin, home, bindir, notes = make_cycle("c6", STUB_REVIEW)
    run_sh = render_run_sh(home, plugin, bindir + os.pathsep + os.environ["PATH"])
    env = env_for(home)
    env["PATH"] = bindir + os.pathsep + env["PATH"]
    r = subprocess.run(["/bin/zsh", run_sh, "review"], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, (r.returncode, r.stderr)
    assert (stamp(home, "review") or "").startswith(TODAY_ISO)


# ---------- 4. tasks.json の版（移しと控え） ----------

def bak_files(root):
    d = os.path.dirname(tasks_path(root))
    return sorted(n for n in os.listdir(d) if n.startswith("tasks.json.bak_"))


@case
def m1_template_has_version_and_migrates_nothing():
    t = json.loads(read(TEMPLATE_TASKS).decode("utf-8"))
    assert t.get("schema_version") == 1, t.get("schema_version")
    assert next(iter(t)) == "schema_version"


@case
def m2_missing_version_is_migrated_with_backup():
    root = make_owner("m2")
    before = read(tasks_path(root))
    assert b"schema_version" not in before
    r = run_dash(root, ["--today", "2026-11-02"])
    assert r.returncode == 0, r.stderr
    assert r.stdout.count("に移しました") == 1, r.stdout
    after = json.loads(read(tasks_path(root)).decode("utf-8"))
    assert next(iter(after)) == "schema_version" and after["schema_version"] == 1
    expected = json.loads(before.decode("utf-8"))
    expected = {"schema_version": 1, **expected}
    assert after == expected, "移しで中身が変わった"
    assert bak_files(root) == ["tasks.json.bak_20261102"], bak_files(root)
    assert read(os.path.join(os.path.dirname(tasks_path(root)), "tasks.json.bak_20261102")) == before, "控えが元と違う"
    # 日本語がそのまま（\u エスケープになっていない）
    assert "テスト用タスク".encode("utf-8") in read(tasks_path(root))
    # 2回目は何もしない
    r2 = run_dash(root, ["--today", "2026-11-02"])
    assert "に移しました" not in r2.stdout and bak_files(root) == ["tasks.json.bak_20261102"], (r2.stdout, bak_files(root))


@case
def m3_old_version_zero_is_migrated_and_current_untouched():
    t = json.loads(json.dumps(TASKS))
    t = {"schema_version": 0, **t}
    root = make_owner("m3", tasks=t)
    r = run_dash(root, ["--today", "2026-11-03"])
    assert "に移しました" in r.stdout, r.stdout
    assert json.loads(read(tasks_path(root)).decode("utf-8"))["schema_version"] == 1
    # すでに最新の版：バイト単位で変えない（控えも作らない）
    t = {"schema_version": 1, **json.loads(json.dumps(TASKS))}
    root = make_owner("m3b", tasks=t, raw_tasks=json.dumps(t, ensure_ascii=False) + "\n")   # 1行の形でも崩さない
    before = read(tasks_path(root))
    r = run_dash(root, ["--today", "2026-11-03"])
    assert r.returncode == 0 and read(tasks_path(root)) == before and not bak_files(root), bak_files(root)


@case
def m4_backup_is_not_overwritten_on_same_day():
    root = make_owner("m4")
    d = os.path.dirname(tasks_path(root))
    with open(os.path.join(d, "tasks.json.bak_20261102"), "w") as f:
        f.write("前の控え")
    r = run_dash(root, ["--today", "2026-11-02"])
    assert "に移しました" in r.stdout
    assert open(os.path.join(d, "tasks.json.bak_20261102"), encoding="utf-8").read() == "前の控え"
    assert bak_files(root) == ["tasks.json.bak_20261102", "tasks.json.bak_20261102_2"], bak_files(root)


@case
def m5_context_modes_keep_first_line_and_put_note_on_stderr():
    root = make_owner("m5")
    r = run_dash(root, ["--plan-context", "--today", "2026-11-02"])
    assert r.returncode == 0, r.stderr
    first = r.stdout.splitlines()[0]
    assert first.startswith(("OPEN", "SKIP")), first
    assert "に移しました" in r.stderr and "に移しました" not in r.stdout


@case
def m6_kill_during_migration_keeps_original_then_retries():
    root = make_owner("m6")
    before = read(tasks_path(root))
    r = run_driver(root, '''
import signal
real = os.replace
def die(src, dst, *a, **k):
    if str(dst).endswith("tasks.json"):
        os.kill(os.getpid(), signal.SIGKILL)
    return real(src, dst, *a, **k)
os.replace = die
sys.argv = ["x", "--today", "2026-11-02"]
sys.exit(ud.main())
''')
    assert r.returncode != 0
    assert read(tasks_path(root)) == before, "移しの途中で止まって tasks.json が壊れた"
    r2 = run_dash(root, ["--today", "2026-11-02"])
    assert r2.returncode == 0 and "に移しました" in r2.stdout, r2.stdout + r2.stderr
    assert json.loads(read(tasks_path(root)).decode("utf-8"))["schema_version"] == 1


@case
def m7_concurrent_edit_during_migration_is_not_overwritten():
    root = make_owner("m7")
    r = run_driver(root, '''
real = ud._make_backup
def backup_then_other_writer_edits(*a, **k):
    out = real(*a, **k)
    with open(ud.TASKS_JSON, "a", encoding="utf-8") as f:   # 控えを取った直後に、ほかの人が tasks.json に書き足した
        f.write("\\n")
    return out
ud._make_backup = backup_then_other_writer_edits
print("RESULT=" + repr(ud.migrate_tasks_json(ud.TASKS_JSON, ud.date(2026, 11, 2))))
''')
    assert "RESULT=None" in r.stdout, r.stdout + r.stderr
    assert b"schema_version" not in read(tasks_path(root)), "ほかの人の書き込みを上書きした"
    assert not bak_files(root), bak_files(root)


@case
def m8_future_version_is_left_alone():
    t = {"schema_version": 99, **json.loads(json.dumps(TASKS))}
    root = make_owner("m8", tasks=t)
    before = read(tasks_path(root))
    r = run_dash(root, ["--today", "2026-11-02"])
    assert read(tasks_path(root)) == before and not bak_files(root)


# ---------- 5. 文字コード ----------

C_LOCALE = {"LC_ALL": "C", "LANG": "C", "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0",
            "PYTHONIOENCODING": "utf-8"}   # 文字コードを決めない環境（open() は ASCII で読む）。画面への出力だけは UTF-8（この修正の対象は「ファイルを開くとき」）


def sh_python_blocks(path):
    """シェルスクリプトの中の python のコード（python3 -c '…'・python3 - <<'PY' … PY・run.sh の雛形の中）から open( を拾う。"""
    text = open(path, encoding="utf-8").read()
    return re.findall(r"open\([^()]*(?:\([^()]*\)[^()]*)*\)", text)


@case
def e1_every_open_in_shell_scripts_has_encoding():
    seen = 0
    for p in (CYCLE, INSTALL):
        for call in sh_python_blocks(p):
            if "JSON" in call or "json" in call.lower() or "argv" in call or "expanduser" in call or "config" in call:
                seen += 1
                assert "encoding=" in call, f"{os.path.basename(p)}: 文字コードの指定がない: {call}"
    assert seen >= 5, f"対象の open( を {seen} 個しか見つけていない（検査が空振り）"


@case
def e2_daily_cycle_reads_japanese_config_without_locale():
    # 設定に日本語（AI の名前・開発の置き場所）がある。文字コードを決めない環境でも、AI の名前を通知に使えて、置き場所を読める
    outside = os.path.join(BASE, "e2_dev_日本語")
    os.makedirs(outside)
    plugin, home, bindir, notes = make_cycle("e2", STUB_REVIEW, ai_name="ガイドはるか",
                                             config_extra={"dev": {"projects": [{"path": outside}]}})
    r = run_cycle(plugin, home, bindir, "review", env_extra=C_LOCALE)
    assert r.returncode == 0, r.stderr
    n = open(notes, encoding="utf-8").read()
    assert "ガイドはるか" in n, f"AI の名前が読めていない: {n!r}"


@case
def e3_dashboard_reads_japanese_files_without_locale():
    root = make_owner("e3")
    r = run_dash(root, ["--today", "2026-11-02"], env_extra=C_LOCALE)
    assert r.returncode == 0, r.stderr
    assert "に移しました" in r.stdout
    assert "テスト用タスク".encode("utf-8") in read(tasks_path(root))
    assert "テスト用タスク" in open(os.path.join(root, "00_タスク管理", "タスクボード.md"), encoding="utf-8").read()


# ====================================================================================================
# 部下D の確かめへの直し（移しの lock・偽の警告・記録の初期値・tmp の掃除・権限・分岐のテスト）
# ====================================================================================================

def migrate_lock(root):
    return os.path.join(os.path.dirname(tasks_path(root)), ".tasks.json.migrate.lock")


def age_file(path, days):
    t = datetime.datetime.now().timestamp() - days * 86400
    os.utime(path, (t, t))


# ---------- 移しの lock・再確認・OSError ----------

@case
def l1_fresh_lock_skips_migration_and_keeps_others_lock():
    root = make_owner("l1")
    before = read(tasks_path(root))
    open(migrate_lock(root), "w").write("")           # ほかの実行が移している最中
    r = run_dash(root, ["--today", "2026-11-02"])
    assert r.returncode == 0, r.stderr
    assert read(tasks_path(root)) == before and not bak_files(root), "lock が取れないのに移した"
    assert os.path.exists(migrate_lock(root)), "他人の lock を消した"
    assert os.path.exists(os.path.join(root, "00_タスク管理", "タスクボード.md")), "移さなくても、ほかの生成物は書く"


@case
def l2_stale_lock_is_taken_over_and_released():
    root = make_owner("l2")
    open(migrate_lock(root), "w").write("")
    age_file(migrate_lock(root), 1 / 24)               # 1時間前の lock（持ち主が止まったまま）
    r = run_dash(root, ["--today", "2026-11-02"])
    assert "に移しました" in r.stdout, r.stdout + r.stderr
    assert not os.path.exists(migrate_lock(root)), "移したあとも lock が残っている"


@case
def l3_concurrent_runs_migrate_exactly_once():
    root = make_owner("l3")
    before = read(tasks_path(root))
    procs = [subprocess.Popen([sys.executable, DASH, "--today", "2026-11-02"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, cwd=root, env=env_for(root)) for _ in range(6)]
    outs = [p.communicate(timeout=120) for p in procs]
    assert all(p.returncode == 0 for p in procs), [o[1][-200:] for o in outs]
    assert sum(o[0].count("に移しました") for o in outs) == 1, [o[0].count("に移しました") for o in outs]
    assert len(bak_files(root)) == 1, bak_files(root)
    d = os.path.dirname(tasks_path(root))
    assert read(os.path.join(d, bak_files(root)[0])) == before, "控えが元と違う"
    assert json.loads(read(tasks_path(root)).decode("utf-8"))["schema_version"] == 1
    assert not os.path.exists(migrate_lock(root)) and not leftovers(d)


@case
def m9_oserror_during_migration_skips_with_one_line_and_cleans_up():
    root = make_owner("m9")
    before = read(tasks_path(root))
    r = run_driver(root, '''
real = os.replace
def full(src, dst, *a, **k):
    if str(dst).endswith("tasks.json"):
        raise OSError(28, "No space left on device")
    return real(src, dst, *a, **k)
os.replace = full
sys.argv = ["x", "--today", "2026-11-02"]
sys.exit(ud.main())
''')
    assert r.returncode == 0, f"落ちた: {r.stderr[-300:]}"
    assert r.stdout.count("移せませんでした（今回は見送り）") == 1, r.stdout
    assert read(tasks_path(root)) == before
    assert not bak_files(root), "作った控えが残っている"
    assert not os.path.exists(migrate_lock(root)), "lock が残っている"
    assert os.path.exists(os.path.join(root, "00_タスク管理", "タスクボード.md"))


@case
def m10_change_just_before_replace_is_detected():
    root = make_owner("m10")
    r = run_driver(root, '''
state = {"done": False}
real = os.fsync
def other_writer_then_fsync(fd):
    if not state["done"]:                 # 一時ファイルを書き終えて、置き換える直前に、ほかの人が tasks.json に書いた
        state["done"] = True
        with open(ud.TASKS_JSON, "a", encoding="utf-8") as f:
            f.write("\\n")
    return real(fd)
os.fsync = other_writer_then_fsync
print("RESULT=" + repr(ud.migrate_tasks_json(ud.TASKS_JSON, ud.date(2026, 11, 2))))
''')
    assert "RESULT=None" in r.stdout, r.stdout + r.stderr
    assert b"schema_version" not in read(tasks_path(root)), "置き換える直前の書き込みを上書きした"
    d = os.path.dirname(tasks_path(root))
    assert not bak_files(root) and not leftovers(d) and not os.path.exists(migrate_lock(root))


@case
def m11_only_own_backup_is_removed():
    root = make_owner("m11")
    d = os.path.dirname(tasks_path(root))
    open(os.path.join(d, "tasks.json.bak_20261102"), "w").write("ほかの控え")
    r = run_driver(root, '''
real = ud._make_backup
def wrapped(*a, **k):
    out = real(*a, **k)
    with open(ud.TASKS_JSON, "a", encoding="utf-8") as f:
        f.write("\\n")
    return out
ud._make_backup = wrapped
print("RESULT=" + repr(ud.migrate_tasks_json(ud.TASKS_JSON, ud.date(2026, 11, 2))))
''')
    assert "RESULT=None" in r.stdout, r.stdout + r.stderr
    assert bak_files(root) == ["tasks.json.bak_20261102"], bak_files(root)     # 自分の控え（_2）だけ消えて、ほかの控えは残る
    assert open(os.path.join(d, "tasks.json.bak_20261102"), encoding="utf-8").read() == "ほかの控え"


@case
def r1_permission_error_on_replace_is_retried_3_times():
    root = make_owner("r1")
    r = run_driver(root, '''
real = os.replace
n = [0]
sleeps = []
def flaky(src, dst, *a, **k):
    if str(dst).endswith("tasks.json") and n[0] < 2:
        n[0] += 1
        raise PermissionError(13, "busy")
    return real(src, dst, *a, **k)
os.replace = flaky
ud.time.sleep = lambda s: sleeps.append(s)
ud.atomic_write_text(ud.TASKS_JSON, '{"ok": 1}')
print("RESULT=%d %r %s" % (n[0], sleeps, open(ud.TASKS_JSON, encoding="utf-8").read()))
''')
    assert "RESULT=2 [0.2, 0.2] {\"ok\": 1}" in r.stdout, r.stdout + r.stderr
    root = make_owner("r1b")
    before = read(tasks_path(root))
    r = run_driver(root, '''
n = [0]
def always(src, dst, *a, **k):
    n[0] += 1
    raise PermissionError(13, "busy")
os.replace = always
ud.time.sleep = lambda s: None
try:
    ud.atomic_write_text(ud.TASKS_JSON, '{"ok": 1}')
except PermissionError:
    print("RAISED attempts=%d" % n[0])
''')
    assert "RAISED attempts=3" in r.stdout, r.stdout + r.stderr
    assert read(tasks_path(root)) == before and not leftovers(os.path.dirname(tasks_path(root)))


@case
def w6_excel_non_permission_oserror_does_not_crash():
    root = make_owner("w6")
    r = run_driver(root, '''
real = os.replace
def full(src, dst, *a, **k):
    if str(dst).endswith("タスク管理.xlsx"):
        raise OSError(28, "No space left on device")
    return real(src, dst, *a, **k)
os.replace = full
sys.argv = ["x", "--today", "2026-11-02"]
sys.exit(ud.main())
''')
    assert r.returncode == 0 and r.stdout.count("Excel を閉じてから、もう一度") == 1, r.stdout + r.stderr[-300:]
    d = os.path.join(root, "00_タスク管理")
    assert os.path.exists(os.path.join(d, "タスクボード.md")) and not leftovers(d)


# ---------- 偽の警告（登録なし・Mac 以外・記録なし） ----------

@case
def u1_no_warning_when_launchd_not_registered():
    root = make_owner("u1", run_sh=True)
    put_success(root, "2026-10-28", "2026-10-28")
    r = run_dash(root, ["--session", "--today", "2026-11-04"], env_extra={"FAKE_LAUNCHCTL_REGISTERED": ""})
    text = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "動いていません" not in text, "自動実行を止めた人に警告を出した"


@case
def u2_only_registered_phases_are_judged():
    root = make_owner("u2", run_sh=True)
    put_success(root, "2026-10-28", "2026-10-28")
    r = run_dash(root, ["--session", "--today", "2026-11-04"], env_extra={"FAKE_LAUNCHCTL_REGISTERED": "review"})
    text = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    hit = [ln for ln in text.splitlines() if "動いていません" in ln]
    assert len(hit) == 1 and "振り返り" in hit[0] and "計画" not in hit[0], hit


@case
def u3_no_warning_off_mac_or_when_launchctl_unknown():
    root = make_owner("u3", run_sh=True)
    put_success(root, "2026-10-28", "2026-10-28")
    r = run_driver(root, '''
ud.sys.platform = "linux"
print("LINUX=" + repr(ud.auto_run_warning(ud.date(2026, 11, 4), ud.Calendar([]))))
''')
    assert "LINUX=''" in r.stdout, r.stdout + r.stderr
    r = run_driver(root, '''
os.environ["PATH"] = "/nonexistent"      # launchctl が見つからない（登録を確かめられない）
ud.sys.platform = "darwin"
print("UNKNOWN=" + repr(ud.auto_run_warning(ud.date(2026, 11, 4), ud.Calendar([]))))
''')
    assert "UNKNOWN=''" in r.stdout, r.stdout + r.stderr


@case
def f1_missing_record_falls_back_to_run_sh_mtime():
    root = make_owner("f1", run_sh=True)           # 記録なし。run.sh は 10/28（登録してから動いた記録が無い）
    set_run_sh_mtime(root, "2026-10-28")
    _, hit = stale_line(root, "2026-11-04")
    assert len(hit) == 1 and "4日" in hit[0], hit
    root = make_owner("f1b", run_sh=True)          # 記録あり：記録を優先（run.sh が古くても）
    set_run_sh_mtime(root, "2026-10-01")
    put_success(root, "2026-11-03", "2026-11-03")
    _, hit = stale_line(root, "2026-11-04")
    assert not hit, hit


@case
def i1_install_rewrites_records_to_now():
    if sys.platform != "darwin":
        return
    root = make_owner("i1")
    put_success(root, "2026-10-01", "2026-10-01")   # 前の記録が古く残っている
    home2 = os.path.join(BASE, "i1home")
    os.makedirs(os.path.join(home2, "Library", "LaunchAgents"))
    env = env_for(root)
    env["HOME"] = home2
    r = subprocess.run(["/bin/zsh", INSTALL, root], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    for ph in ("plan", "review"):
        s = open(os.path.join(root, "scripts", "auto", f"last_success_{ph}.txt"), encoding="utf-8").read()
        assert s.startswith(TODAY_ISO), (ph, s)
    assert os.path.exists(os.path.join(root, "scripts", "auto", "run.sh"))


# ---------- tmp の掃除・権限 ----------

@case
def t1_old_tmp_files_are_cleaned_on_session_only_in_two_folders():
    root = make_owner("t1")
    data = os.path.join(root, "00_タスク管理", "data")
    os.makedirs(os.path.join(root, "04_ナレッジ"))
    old = [os.path.join(data, ".tasks.json.123.tmp"), os.path.join(root, "00_タスク管理", ".タスク管理.xlsx.9.tmp"),
           os.path.join(root, "scripts", "auto", ".last_success_plan.txt.5.tmp")]
    keep_old = [os.path.join(data, "keep.tmp"), os.path.join(root, "04_ナレッジ", ".a.tmp"), os.path.join(data, ".notes.txt")]
    fresh = os.path.join(root, "scripts", "auto", ".x.1.tmp")
    for p in old + keep_old + [fresh]:
        open(p, "w").write("x")
    for p in old + keep_old:
        age_file(p, 2)
    r = run_dash(root, ["--today", "2026-11-02"])          # 起動時でない実行では片付けない
    assert all(os.path.exists(p) for p in old + keep_old + [fresh]), r.stderr
    r = run_dash(root, ["--session", "--today", "2026-11-02"])
    assert r.returncode == 0, r.stderr
    assert not any(os.path.exists(p) for p in old), [p for p in old if os.path.exists(p)]
    assert all(os.path.exists(p) for p in keep_old + [fresh]), "対象外のファイルまで片付けた"


@case
def p1_permissions_are_kept_on_replace():
    root = make_owner("p1")
    os.chmod(tasks_path(root), 0o640)
    assert run_dash(root, ["--today", "2026-11-02"]).returncode == 0
    assert os.stat(tasks_path(root)).st_mode & 0o777 == 0o640, oct(os.stat(tasks_path(root)).st_mode & 0o777)
    d = os.path.join(root, "00_タスク管理")
    x, b = os.path.join(d, "タスク管理.xlsx"), os.path.join(d, "タスクボード.md")
    os.chmod(x, 0o600)
    os.chmod(b, 0o600)
    assert run_dash(root, ["--today", "2026-11-02"]).returncode == 0
    assert os.stat(x).st_mode & 0o777 == 0o600 and os.stat(b).st_mode & 0o777 == 0o600, \
        (oct(os.stat(x).st_mode & 0o777), oct(os.stat(b).st_mode & 0o777))


# ---------- daily_cycle.sh の分岐ごとの記録（段階を細かく） ----------

STUB_MODE = '''import os, sys
a = sys.argv[1:]
home = os.environ["AI_BUNSHIN_HOME"]
m = os.path.join(home, "mode")
mode = open(m).read().strip() if os.path.exists(m) else "normal"
if "--session" in a:
    sys.exit(0)
if "--today-status" in a:
    print("計画済み" if mode == "doneplanned" else "完了")
    sys.exit(0)
if "--plan-context" in a:
    if mode in ("noplan", "doopen"):
        print("OPEN")
    elif mode == "skipother":
        print("SKIP: 動きがない")
    elif mode in ("doneplanned", "doneall"):
        print("SKIP: 今日の計画は作成済み")
'''


def cycle_with_mode(name, mode, phase):
    plugin, home, bindir, notes = make_cycle(name, STUB_MODE)
    open(os.path.join(home, "mode"), "w").write(mode)
    r = run_cycle(plugin, home, bindir, phase)
    calls = os.path.join(home, "claude_calls")
    n = len(open(calls).read().split()) if os.path.exists(calls) else 0
    return r, home, n


@case
def b1_plan_ok_but_no_plan_created_records_plan_only():
    r, home, n = cycle_with_mode("b1", "noplan", "plan")
    assert r.returncode == 0, r.stderr
    assert (stamp(home, "plan") or "").startswith(TODAY_ISO) and stamp(home, "do") is None, (stamp(home, "plan"), stamp(home, "do"))
    assert n == 1, n          # 計画の claude だけ。実行には入らない


@case
def b2_plan_skip_other_records_plan_without_claude():
    r, home, n = cycle_with_mode("b2", "skipother", "plan")
    assert r.returncode == 0 and (stamp(home, "plan") or "").startswith(TODAY_ISO) and stamp(home, "do") is None and n == 0, \
        (r.returncode, stamp(home, "plan"), stamp(home, "do"), n)


@case
def b3_do_open_records_do_without_claude():
    r, home, n = cycle_with_mode("b3", "doopen", "do")
    assert r.returncode == 0 and (stamp(home, "do") or "").startswith(TODAY_ISO) and stamp(home, "plan") is None and n == 0, \
        (r.returncode, stamp(home, "plan"), stamp(home, "do"), n)


@case
def b4_plan_already_made_then_do_runs_records_both():
    r, home, n = cycle_with_mode("b4", "doneplanned", "plan")
    assert r.returncode == 0, r.stderr
    assert (stamp(home, "plan") or "").startswith(TODAY_ISO) and (stamp(home, "do") or "").startswith(TODAY_ISO) and n == 1, \
        (stamp(home, "plan"), stamp(home, "do"), n)


@case
def b5_plan_and_do_both_done_records_plan_only():
    r, home, n = cycle_with_mode("b5", "doneall", "plan")
    assert r.returncode == 0 and (stamp(home, "plan") or "").startswith(TODAY_ISO) and stamp(home, "do") is None and n == 0, \
        (r.returncode, stamp(home, "plan"), stamp(home, "do"), n)


shutil.rmtree(BASE, ignore_errors=True)
print(f"\n失敗 {fails} 件")
sys.exit(1 if fails else 0)
