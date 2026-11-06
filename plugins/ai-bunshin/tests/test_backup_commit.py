"""自動の振り返りのあとの「控えのコミット」のテスト（scripts/auto/daily_cycle.sh の backup_commit。T077a）。
本人のフォルダをローカルの Git で控えている人について、review の段が終わったら、その日の控えを1回コミットする。
一時フォルダに本人のフォルダ（Git のリポジトリ）を作り、daily_cycle.sh（本物のコピー）を作り物の claude・osascript で通して動かす。
本物の launchd・claude・通知・本物の本人のフォルダは使わない（git の設定も一時の HOME に分ける）。

- ① 変更があれば、コミットが1つ増える。メッセージは「YYYY-MM-DD 振り返り」。ログにハッシュ
- ② 変更が無ければ、コミットは増えない。成功（終了コード 0）
- ③ 本人のフォルダが親のフォルダのリポジトリの中なら、何もしない（親のリポジトリにコミットしない）
- ④ git コマンドが無い（PATH に無い）なら、飛ばす
- ⑤ plan・do の段ではコミットしない
- ⑥ コミットが失敗しても、daily_cycle の終了コードは変わらない（失敗の文面・パスはログに書かない）
- 追加：claude が失敗（exit 1）・時間の上限（124）で終わっても、review ならコミットする（終了コードはそのまま）／git が固まっても上限で止まる
実行：python3 tests/test_backup_commit.py（失敗があれば終了コード1）。CYCLE_UNDER_TEST に別の版の daily_cycle.sh を指すと、その版で流せる"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.abspath(os.path.join(HERE, "..", "scripts"))
CYCLE = os.environ.get("CYCLE_UNDER_TEST") or os.path.join(SCRIPTS, "auto", "daily_cycle.sh")
BASE = os.path.realpath(tempfile.mkdtemp(prefix="backupcommit_"))
FAKE_HOME = os.path.join(BASE, "fakehome")
os.makedirs(FAKE_HOME)
TODAY = time.strftime("%Y-%m-%d")

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


STUB = '''import os, sys, time
a = sys.argv[1:]
if "--session" in a:
    sys.exit(0)
mode = os.environ.get("STUB_PHASE", "review")
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

# 作り物の claude：FAKE_CLAUDE が change なら本人のフォルダにファイルを足す／fail なら exit 1／sleep なら長く寝る
FAKE_CLAUDE = '''#!/bin/sh
case "$FAKE_CLAUDE" in
  change) mkdir -p "$AI_BUNSHIN_HOME/01_スプリント/S1/daily" && echo "議事録 $(date +%s)" > "$AI_BUNSHIN_HOME/01_スプリント/S1/daily/$(date +%Y%m%d)_振り返り.md" ;;
  fail) echo "error"; exit 1 ;;
  sleep) sleep 30 ;;
esac
echo "done"
'''


def git(cwd, *args, env=None):
    e = dict(os.environ)
    e.update(git_env())
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, env=e)


def git_env():
    return {"HOME": FAKE_HOME, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def commits(cwd):
    r = git(cwd, "rev-list", "--count", "HEAD")
    return int(r.stdout.strip()) if r.returncode == 0 else 0


def make(name, own_repo=True, parent_repo=False, cfg=None):
    """一時フォルダに、プラグイン（daily_cycle.sh と道具）・本人のフォルダ・作り物の claude と osascript を作る。
    own_repo：本人のフォルダを Git のリポジトリにして、最初のコミットを1つ作る（ログなどは .gitignore で外す）
    parent_repo：本人のフォルダの1つ上（プラグインと同じ階層の親）をリポジトリにする（本人のフォルダ自身はリポジトリにしない）"""
    d = os.path.join(BASE, name)
    plugin = os.path.join(d, "plugin")
    os.makedirs(os.path.join(plugin, "scripts", "auto"))
    shutil.copy(CYCLE, os.path.join(plugin, "scripts", "auto", "daily_cycle.sh"))
    shutil.copy(os.path.join(SCRIPTS, "auto", "run_limited.py"), os.path.join(plugin, "scripts", "auto", "run_limited.py"))
    for f in ("lock_check.py", "watch_check.py", "ng_guard.py", "ng_guard_legacy.py"):
        shutil.copy(os.path.join(SCRIPTS, f), os.path.join(plugin, "scripts", f))
    open(os.path.join(plugin, "scripts", "update_dashboard.py"), "w", encoding="utf-8").write(STUB)
    home = os.path.join(d, "owner")
    os.makedirs(os.path.join(home, "設定"))
    os.makedirs(os.path.join(home, "scripts", "auto"))
    os.makedirs(os.path.join(home, "00_タスク管理", "data"))
    c = {"ai_name": "テストAI"}
    c.update(cfg or {})
    json.dump(c, open(os.path.join(home, "設定", "config.json"), "w", encoding="utf-8"), ensure_ascii=False)
    open(os.path.join(home, "00_タスク管理", "data", "tasks.json"), "w").write("{}")
    open(os.path.join(home, ".gitignore"), "w").write("scripts/auto/\n")
    bindir = os.path.join(d, "bin")
    os.makedirs(bindir)
    open(os.path.join(bindir, "claude"), "w").write(FAKE_CLAUDE)
    open(os.path.join(bindir, "osascript"), "w").write("#!/bin/sh\nexit 0\n")
    os.chmod(os.path.join(bindir, "claude"), 0o755)
    os.chmod(os.path.join(bindir, "osascript"), 0o755)
    if own_repo:
        assert git(home, "init", "-q").returncode == 0
        git(home, "add", "-A")
        assert git(home, "commit", "-q", "-m", "最初").returncode == 0
    if parent_repo:
        assert git(d, "init", "-q").returncode == 0
        open(os.path.join(d, ".gitignore"), "w").write("plugin/\nbin/\nowner/scripts/auto/\n")
        git(d, "add", "-A")
        assert git(d, "commit", "-q", "-m", "親の最初").returncode == 0
    return dict(d=d, plugin=plugin, home=home, bindir=bindir)


def run(c, phase="review", claude="change", path=None, extra_env=None, timeout=90, stub_phase="review"):
    env = {k: v for k, v in os.environ.items() if k not in ("AI_BUNSHIN_AUTO_RUN", "CLAUDE_PROJECT_DIR")}
    env.update(git_env())
    env["AI_BUNSHIN_HOME"] = c["home"]
    env["PATH"] = path if path is not None else c["bindir"] + os.pathsep + env.get("PATH", "")
    env["FAKE_CLAUDE"] = claude
    env["STUB_PHASE"] = stub_phase
    env.update(extra_env or {})
    return subprocess.run(["/bin/zsh", os.path.join(c["plugin"], "scripts", "auto", "daily_cycle.sh"), phase],
                          capture_output=True, text=True, env=env, timeout=timeout)


def log_of(c):
    d = os.path.join(c["home"], "scripts", "auto", "logs")
    out = ""
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        out += open(os.path.join(d, f), encoding="utf-8").read()
    return out


def backup_lines(c):
    return [ln for ln in log_of(c).splitlines() if "控え：" in ln]


@case
def t1_review_with_changes_adds_one_commit_with_message():
    c = make("t1")
    before = commits(c["home"])
    r = run(c)
    assert r.returncode == 0, (r.returncode, r.stderr[-300:])
    assert commits(c["home"]) == before + 1, (before, commits(c["home"]), log_of(c)[-500:])
    msg = git(c["home"], "log", "-1", "--format=%s").stdout.strip()
    assert msg == f"{TODAY} 振り返り", msg
    body = git(c["home"], "log", "-1", "--format=%b").stdout
    assert "Co-Authored-By" not in body, body
    short = git(c["home"], "rev-parse", "--short", "HEAD").stdout.strip()
    lines = backup_lines(c)
    assert lines and f"コミットした（{short}）" in lines[-1], (short, lines)
    assert git(c["home"], "status", "--porcelain").stdout.strip() == "", "コミットしたのに未コミットが残っている"


@case
def t2_review_without_changes_adds_no_commit_and_succeeds():
    c = make("t2")
    before = commits(c["home"])
    r = run(c, claude="nochange")
    assert r.returncode == 0, (r.returncode, r.stderr[-300:])
    assert commits(c["home"]) == before, (before, commits(c["home"]))
    lines = backup_lines(c)
    assert lines and "何も無かった" in lines[-1], lines


@case
def t3_home_inside_parent_repo_does_nothing():
    c = make("t3", own_repo=False, parent_repo=True)
    before = commits(c["d"])
    r = run(c)
    assert r.returncode == 0, (r.returncode, r.stderr[-300:])
    assert commits(c["d"]) == before, "親のリポジトリにコミットした"
    assert not os.path.exists(os.path.join(c["home"], ".git")), "本人のフォルダに .git を作った"
    lines = backup_lines(c)
    assert lines and "飛ばした" in lines[-1], lines
    # 親のリポジトリには、変更（議事録）が未コミットのまま残る＝触っていない
    st = git(c["d"], "-c", "core.quotepath=off", "status", "--porcelain").stdout
    assert "owner/01_スプリント" in st, st


@case
def t3b_home_not_a_repo_at_all_is_skipped():
    c = make("t3b", own_repo=False)
    r = run(c)
    assert r.returncode == 0, (r.returncode, r.stderr[-300:])
    assert not os.path.exists(os.path.join(c["home"], ".git"))
    lines = backup_lines(c)
    assert lines and "飛ばした" in lines[-1], lines


@case
def t4_no_git_command_is_skipped():
    c = make("t4")
    before = commits(c["home"])
    # PATH から git を外す：必要な道具だけを置いた別のフォルダ（リンク）に、作り物の claude・osascript を加えたものだけを PATH にする
    tools = os.path.join(c["d"], "tools")
    os.makedirs(tools)
    for n in ("zsh", "sh", "python3", "date", "sed", "head", "tail", "tr", "mkdir", "mv", "cat", "grep", "kill", "sleep",
              "rm", "dirname", "ps", "pwd", "uname", "wc", "cut", "env", "true", "false", "echo", "sort", "ls", "cp", "touch"):
        p = shutil.which(n)
        if p:
            os.symlink(p, os.path.join(tools, n))
    path = c["bindir"] + os.pathsep + tools
    chk = subprocess.run(["/bin/sh", "-c", "command -v git"], capture_output=True, text=True, env={"PATH": path})
    assert chk.returncode != 0, f"テストの前提：PATH に git が残っている（{chk.stdout}）"
    r = run(c, path=path)
    assert r.returncode == 0, (r.returncode, r.stderr[-300:])
    assert commits(c["home"]) == before, "git が無いのにコミットが増えた"
    lines = backup_lines(c)
    assert lines and "飛ばした" in lines[-1], (lines, log_of(c)[-400:])


@case
def t5_plan_and_do_phases_do_not_commit():
    c = make("t5")
    before = commits(c["home"])
    r = run(c, phase="plan", stub_phase="plan")   # 計画 → 続けて実行。どちらも claude が本人のフォルダを変える
    assert r.returncode == 0, (r.returncode, r.stderr[-300:])
    assert commits(c["home"]) == before, "plan・do でコミットした"
    assert not backup_lines(c), backup_lines(c)
    c2 = make("t5b")
    before2 = commits(c2["home"])
    r2 = run(c2, phase="do", stub_phase="do")
    assert r2.returncode == 0, (r2.returncode, r2.stderr[-300:])
    assert commits(c2["home"]) == before2 and not backup_lines(c2), (before2, commits(c2["home"]), backup_lines(c2))


@case
def t6_commit_failure_does_not_change_exit_code():
    # 失敗のさせ方：index.lock があると git add が失敗する
    c = make("t6")
    open(os.path.join(c["home"], ".git", "index.lock"), "w").close()
    before = commits(c["home"])
    r = run(c)
    assert r.returncode == 0, (r.returncode, r.stderr[-300:])      # claude が成功＝終了コード 0 のまま
    assert commits(c["home"]) == before
    lines = backup_lines(c)
    assert lines and "失敗した" in lines[-1], lines
    # 失敗の文面・パスをログに書かない（T069）
    joined = "\n".join(lines)
    assert c["home"] not in joined and "index.lock" not in joined and "fatal" not in joined, joined
    # claude が失敗（exit 1）のときも、コミットの失敗で終了コードは変わらない（1 のまま）
    c2 = make("t6b")
    open(os.path.join(c2["home"], ".git", "index.lock"), "w").close()
    r2 = run(c2, claude="fail")
    assert r2.returncode == 1, r2.returncode


@case
def t7_claude_failure_still_commits_and_keeps_exit_code():
    c = make("t7")
    # claude が失敗する前に変更を残す形：fail の前に議事録を書く別の作り物
    open(os.path.join(c["bindir"], "claude"), "w").write(
        '#!/bin/sh\nmkdir -p "$AI_BUNSHIN_HOME/01_スプリント/S1/daily" && echo x > "$AI_BUNSHIN_HOME/01_スプリント/S1/daily/a.md"\necho error\nexit 1\n')
    before = commits(c["home"])
    r = run(c)
    assert r.returncode == 1, r.returncode
    assert commits(c["home"]) == before + 1, "claude が失敗した日の控えが残っていない"


@case
def t8_time_limit_stop_still_commits_and_keeps_exit_124():
    c = make("t8", cfg={"auto": {"max_minutes": 0.05}})   # 3秒で止める
    open(os.path.join(c["bindir"], "claude"), "w").write(
        '#!/bin/sh\nmkdir -p "$AI_BUNSHIN_HOME/01_スプリント/S1/daily" && echo x > "$AI_BUNSHIN_HOME/01_スプリント/S1/daily/a.md"\nsleep 30\n')
    before = commits(c["home"])
    r = run(c, timeout=60)
    assert r.returncode == 124, (r.returncode, r.stderr[-300:], log_of(c)[-500:])
    assert commits(c["home"]) == before + 1, "時間の上限で止めた日の控えが残っていない"


@case
def t9_hung_git_is_stopped_by_time_limit():
    c = make("t9")
    # git が固まる：作り物の git（寝るだけ）を PATH の先頭に置く。待つのは AI_BUNSHIN_BACKUP_SEC 秒まで
    open(os.path.join(c["bindir"], "git"), "w").write("#!/bin/sh\nsleep 120\n")
    os.chmod(os.path.join(c["bindir"], "git"), 0o755)
    t0 = time.time()
    r = run(c, extra_env={"AI_BUNSHIN_BACKUP_SEC": "2"}, timeout=60)
    took = time.time() - t0
    assert r.returncode == 0, (r.returncode, r.stderr[-300:])
    assert took < 30, f"git が固まったのに {took:.0f} 秒かかった"
    lines = backup_lines(c)
    assert lines and "失敗した" in lines[-1], lines


@case
def t10_no_other_git_operations_in_script():
    # push・reset・checkout・stash など、決めた以外の git 操作を入れていない（コードの中身）
    src = open(CYCLE, encoding="utf-8").read()
    import re
    ops = set(re.findall(r'git -C "\$r" ([a-z-]+)', src))
    assert ops <= {"rev-parse", "add", "diff", "commit"}, ops


print(f"\n{len(names) - fails}/{len(names)} passed")
sys.exit(1 if fails else 0)
