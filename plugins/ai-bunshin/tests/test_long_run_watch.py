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
    only = os.environ.get("TEST_ONLY")   # 例：TEST_ONLY=e で名前が e で始まるケースだけ流す（調べるとき用。既定は全部）
    if only and not fn.__name__.startswith(only):
        return fn
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
# 新旧の比べ：環境変数 RUN_LIMITED_UNDER_TEST に別の版の run_limited.py を指すと、その版で流せる（既定は今の版）
LIMITED = os.environ.get("RUN_LIMITED_UNDER_TEST") or os.path.join(SCRIPTS, "auto", "run_limited.py")


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
    open(script, "w").write(f"#!/bin/sh\n{trap}{inner}\necho $! > '{pidf}'\necho $$ > '{d}/child.pid'\necho partial-output\nwait\n")
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


def _signal_case(name, sig, ignore_term=False):
    """外側（run_limited.py）にシグナルを送ると、偽 claude と孫が残らず、一時ファイル（.out.*）も残らない。おとりは残る。"""
    decoy = start_decoy(name)
    script, pidf = grandchild_script(name, ignore_term=ignore_term)
    logs = os.path.join(BASE, name, "logs")
    os.makedirs(logs, exist_ok=True)
    out = os.path.join(logs, ".out.abc123")
    p = subprocess.Popen([sys.executable, LIMITED, "--minutes", "5", "--grace", "1", "--stdout", out, "--", script],
                         start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    CHILDREN.append(p)
    gp = pid_from(pidf)
    child = pid_from(os.path.join(BASE, name, "child.pid"))   # 偽 claude（run.sh）
    t0 = time.time()
    os.kill(p.pid, sig)
    try:
        rc = p.wait(timeout=15)
    except subprocess.TimeoutExpired:
        raise AssertionError("シグナルを受けても終わらない")
    assert time.time() - t0 < 12, "終わるのが遅い"
    assert rc == 128 + sig, rc
    assert wait_dead(gp), "孫のプロセスが残っている"
    assert wait_dead(child), "偽 claude が残っている"
    assert not [f for f in os.listdir(logs) if f.startswith(".out.")], "一時ファイル（.out.*）が残っている"
    assert decoy.poll() is None and alive(decoy.pid), "おとりまで止めた"


@case
def l5_term_stops_the_group_and_cleans_up():
    _signal_case("l5", signal.SIGTERM)


@case
def l6_hup_and_int_do_the_same():
    _signal_case("l6a", signal.SIGHUP)
    _signal_case("l6b", signal.SIGINT)


@case
def l7_term_with_child_ignoring_term_is_killed_after_grace():
    _signal_case("l7", signal.SIGTERM, ignore_term=True)


@case
def l8_signals_in_a_row_still_stop_the_group_and_clean_up():
    # TERM・HUP・INT が続けて届いても（daily_cycle.sh が転送した TERM と、グループ全体に届いた TERM が重なるときなど）、
    # 例外で落ちず、起動したグループを止め、一時ファイルを消し、128+番号で終わる。
    # 続けて届く信号は同じ番号だと1つにまとまってしまうので、別の番号を3つ、同じプロセスに続けて送る（このテスト自身のプロセスだけ）
    import importlib.util
    import threading
    spec = importlib.util.spec_from_file_location("run_limited_under_test", LIMITED)
    rl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rl)
    sigs = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)
    saved = {s: signal.signal(s, signal.SIG_IGN) for s in sigs}   # run() の前後で、届き遅れたものでこのテストが落ちないように
    d = os.path.join(BASE, "l8")
    os.makedirs(d, exist_ok=True)
    try:
        for i in range(5):
            out = os.path.join(d, f"out{i}")
            pidf = os.path.join(d, f"pid{i}")

            def fire():
                t0 = time.time()
                while time.time() - t0 < 10 and not (os.path.exists(out) and os.path.exists(pidf) and os.path.getsize(pidf) > 0):
                    time.sleep(0.002)
                time.sleep(0.05)
                for s in sigs:
                    os.kill(os.getpid(), s)

            th = threading.Thread(target=fire)
            th.start()
            try:
                rc = rl.run(["sh", "-c", f"echo $$ > '{pidf}'; exec sleep 60"], 60, out, grace=1.0)
            finally:
                th.join()
            assert rc in (128 + int(s) for s in sigs), (i, rc)
            assert wait_dead(int(open(pidf).read().strip()), 5), (i, "起動した子が残っている")
            assert not os.path.exists(out), (i, "一時ファイルが残っている")
    finally:
        time.sleep(0.2)
        for s, h in saved.items():
            signal.signal(s, h)


@case
def l9_signal_at_every_line_of_run_is_not_lost():
    # run() の中の「どの行」に信号が届いても（起動の直前・直後・待ちに入る直前を含む）、取りこぼさず、すぐ止める。
    # sys.settrace で、run() の各行に入る直前に、自分自身に信号を送る（決定的。送る相手はこのテストのプロセスだけ。子は自分が起動した sleep だけ）。
    # 期待：戻り値は 128+番号、上限（3秒）を待たずに止まる、一時ファイルが無い、起動した子が残らない
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_limited_under_test2", LIMITED)
    rl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rl)
    sigs = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)
    saved = {s: signal.signal(s, signal.SIG_IGN) for s in sigs}   # run() の前後で、届き遅れたものでこのテストが落ちないように
    d = os.path.join(BASE, "l9")
    os.makedirs(d, exist_ok=True)

    def one(tag, fire_line, sig):
        out = os.path.join(d, f"out_{tag}")
        pidf = os.path.join(d, f"pid_{tag}")
        hit = []
        lines = {}   # 行番号 → 最初に通った時刻

        def tracer(frame, event, arg):
            if frame.f_code.co_name != "run" or frame.f_code.co_filename != rl.__file__:
                return None

            def local(frame, event, arg):
                if event == "line":
                    lines.setdefault(frame.f_lineno, time.time())
                    # 信号の受け手（run() の記録用のハンドラ）を入れたあとの行だけ。入れる前は、このテストの SIG_IGN で捨てられてしまう
                    if (fire_line is not None and frame.f_lineno == fire_line and not hit
                            and signal.getsignal(sig) not in (signal.SIG_IGN, signal.SIG_DFL)):
                        hit.append(1)
                        os.kill(os.getpid(), sig)
                return local
            return local

        t0 = time.time()
        sys.settrace(tracer)
        try:
            rc = rl.run(["sh", "-c", f"echo $$ > '{pidf}'; exec sleep 60"], 3, out, grace=1.0)
        finally:
            sys.settrace(None)
        return rc, time.time() - t0, hit, lines, out, pidf

    try:
        # まず信号なしで、上限で止まる道（124）と、ふつうに終わる道を流して、run() が通る行を集める
        rc, dt, hit, lines, out, pidf = one("dry", None, None)
        assert rc == 124, rc
        # 上限（3秒）が来たあとに初めて通る行（上限で止める道）は除く：そこに届いた信号は、止める判断のあとなので無視でよい
        t_end = max(lines.values())
        late = {ln for ln, t in lines.items() if t_end - t <= 0.3}
        all_lines = set(lines) - late
        # 早く終わる道の行も集める（信号は送らない）
        saved_run = rl.run
        out2 = os.path.join(d, "out_fast")
        lines2 = set()

        def tracer2(frame, event, arg):
            if frame.f_code.co_name != "run" or frame.f_code.co_filename != rl.__file__:
                return None

            def local(frame, event, arg):
                if event == "line":
                    lines2.add(frame.f_lineno)
                return local
            return local
        sys.settrace(tracer2)
        try:
            assert saved_run(["true"], 3, out2, grace=1.0) == 0
        finally:
            sys.settrace(None)
        all_lines |= (lines2 - late)
        assert len(all_lines) >= 8, all_lines   # run() の行を拾えている
        tried = 0
        for n, ln in enumerate(sorted(all_lines)):
            sig = sigs[n % 3]
            rc, dt, hit, lines, out, pidf = one(f"l{ln}", ln, sig)
            if not hit:
                continue   # この行は、信号を送った道では通らない（例：上限で止める道の行）
            tried += 1
            assert rc == 128 + int(sig), (f"{ln}行目で信号 {int(sig)}", "戻り値", rc)
            assert dt < 2.5, (f"{ln}行目で信号 {int(sig)}", "止まるのが遅い（上限まで待った）", round(dt, 1))
            assert not os.path.exists(out), (f"{ln}行目で信号 {int(sig)}", "一時ファイルが残っている")
            if os.path.exists(pidf) and open(pidf).read().strip():
                assert wait_dead(int(open(pidf).read().strip()), 5), (f"{ln}行目で信号 {int(sig)}", "起動した子が残っている")
        assert tried >= 5, tried
    finally:
        time.sleep(0.2)
        for s, h in saved.items():
            signal.signal(s, h)


@case
def l10_signal_recorded_then_child_finishes_first_still_stops_the_grandchild():
    # 信号を記録したあとに、子が先に終わっても（待ちから戻る瞬間に届く）、残った孫を止めて 128+番号 で返し、一時ファイルを消す。
    # 子（sh）は孫（sleep）を残して終わる。待ちの戻り際に自分へ信号を送る（Popen の戻りを包んで決める。送る相手はこのテストのプロセスだけ）
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_limited_under_test3", LIMITED)
    rl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rl)
    sigs = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)
    saved = {s: signal.signal(s, signal.SIG_IGN) for s in sigs}   # run() の前後で、届き遅れたものでこのテストが落ちないように
    d = os.path.join(BASE, "l10")
    os.makedirs(d, exist_ok=True)
    real_popen = rl.subprocess.Popen

    class Wrapped:
        def __init__(self, *a, **k):
            self._p = real_popen(*a, **k)
            self.sig = None

        def __getattr__(self, name):
            return getattr(self._p, name)

        def wait(self, timeout=None):
            rc = self._p.wait(timeout=timeout)   # 子が終わるまでは、そのまま待つ
            if self.sig is not None and not self.sent:
                self.sent = True
                os.kill(os.getpid(), self.sig)   # 子が終わった「その戻り際」に届く
                time.sleep(0.05)
            return rc
        sent = False

    try:
        for i, sig in enumerate(sigs):
            out = os.path.join(d, f"out{i}")
            pidf = os.path.join(d, f"pid{i}")

            def popen(*a, _sig=sig, **k):
                w = Wrapped(*a, **k)
                w.sig = _sig
                return w
            rl.subprocess.Popen = popen
            try:
                t0 = time.time()
                rc = rl.run(["sh", "-c", f"sleep 60 & echo $! > '{pidf}'; exit 0"], 30, out, grace=1.0)
            finally:
                rl.subprocess.Popen = real_popen
            assert rc == 128 + int(sig), (int(sig), "戻り値", rc)
            assert time.time() - t0 < 10, "遅い"
            assert wait_dead(int(open(pidf).read().strip()), 5), (int(sig), "子が先に終わったあと、孫が残っている")
            assert not os.path.exists(out), (int(sig), "一時ファイルが残っている")
    finally:
        time.sleep(0.2)
        for s, h in saved.items():
            signal.signal(s, h)


@case
def l11_child_finishing_normally_without_a_signal_is_unchanged():
    out = os.path.join(BASE, "l11_out")
    r = run_limited(["--minutes", "1", "--stdout", out], ["sh", "-c", "echo hi; exit 3"])
    assert r.returncode == 3 and open(out).read().strip() == "hi", (r.returncode, r.stderr)


def _kill_quiet(pid, sig=signal.SIGKILL):
    try:
        os.kill(pid, sig)
    except OSError:
        pass


def _killpg_quiet(pgid, sig=signal.SIGKILL):
    try:
        os.killpg(pgid, sig)
    except OSError:
        pass


@case
def l12_parent_killed_with_9_stops_child_and_grandchild_and_cleans_up():
    """A：親（daily_cycle.sh 役）が KILL されても trap は効かない。run_limited が親の死に気づいて、自分の claude 役と孫を止める。"""
    name = "l12"
    d = os.path.join(BASE, name)
    logs = os.path.join(d, "logs")
    os.makedirs(logs, exist_ok=True)
    script, pidf = grandchild_script(name)
    out = os.path.join(logs, ".out.abc123")
    runpid = os.path.join(d, "run.pid")
    # 親役：run_limited を背景で起動して、その PID を書き、wait する（上限は5分。親が死ななければ5分残る）
    parent = os.path.join(d, "parent.sh")
    open(parent, "w").write(f"#!/bin/sh\n'{sys.executable}' '{LIMITED}' --minutes 5 --grace 1 --stdout '{out}' -- '{script}' &\necho $! > '{runpid}'\nwait\n")
    os.chmod(parent, 0o755)
    par = subprocess.Popen([parent], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    CHILDREN.append(par)
    rl = pid_from(runpid)
    gp = pid_from(pidf)
    child = pid_from(os.path.join(d, "child.pid"))
    try:
        os.kill(par.pid, signal.SIGKILL)   # trap が効かない殺し方
        par.wait(timeout=5)
        assert wait_dead(gp, 8), "親が死んだのに、孫が残っている"
        assert wait_dead(child, 8), "親が死んだのに、claude 役が残っている"
        assert wait_dead(rl, 8), "親が死んだのに、run_limited が残っている"
        assert not [f for f in os.listdir(logs) if f.startswith(".out.")], "一時ファイル（.out.*）が残っている"
    finally:
        _kill_quiet(rl)
        _killpg_quiet(child)
        _kill_quiet(gp)


def _slow_cleanup_script(name):
    """子は TERM で即終了。孫は TERM を受けると seen を作り、1秒かけて片づけて cleaned を作る（K の再現の形）。"""
    d = os.path.join(BASE, name)
    os.makedirs(d, exist_ok=True)
    grand = os.path.join(d, "grand.sh")
    open(grand, "w").write(f"#!/bin/sh\ntrap \"touch '{d}/seen'; sleep 1; touch '{d}/cleaned'; exit 0\" TERM\ntouch '{d}/ready'\nsleep 120 &\nwait\n")
    os.chmod(grand, 0o755)
    script = os.path.join(d, "run.sh")
    open(script, "w").write(f"#!/bin/sh\n'{grand}' &\necho $! > '{d}/grand.pid'\necho $$ > '{d}/child.pid'\nwait\n")
    os.chmod(script, 0o755)
    return d, script


@case
def l13_grandchild_gets_grace_even_when_child_exits_at_once_on_term():
    """K：子が TERM で先に終わっても、孫の片づけ（1秒）が終わるまで待ってから KILL する。"""
    d, script = _slow_cleanup_script("l13")
    out = os.path.join(d, "l13.out")
    # 孫は起動後すぐ（0.1 秒ほど）trap を入れて ready を作る。上限は 6 秒（0.1 分）で、その後に時間切れの TERM を受ける
    r = run_limited(["--minutes", "0.1", "--grace", "3", "--stdout", out], [script])
    assert r.returncode == 124, (r.returncode, r.stderr[:200])
    assert os.path.exists(os.path.join(d, "ready")), "孫の準備ができる前に止まった（テストの前提が崩れた）"
    assert os.path.exists(os.path.join(d, "seen")), "孫が TERM を受けていない"
    assert os.path.exists(os.path.join(d, "cleaned")), "孫の片づけが終わる前に KILL された（猶予が 0 秒）"
    assert wait_dead(pid_from(os.path.join(d, "grand.pid"))), "孫が残っている"


@case
def l14_signal_during_timeout_stop_is_read_as_a_signal():
    """J：時間切れの止め途中に信号が来たら、128+番号で戻り、一時ファイルも残らない（124 にしない）。"""
    name = "l14"
    d = os.path.join(BASE, name)
    logs = os.path.join(d, "logs")
    os.makedirs(logs, exist_ok=True)
    termed = os.path.join(d, "termed")
    script = os.path.join(d, "run.sh")
    # TERM を受けたら印を作るが、終わらない（KILL まで止め途中が続く）
    open(script, "w").write(f"#!/bin/sh\ntrap \"echo t > '{termed}'\" TERM\necho $$ > '{d}/child.pid'\necho partial\nwhile :; do sleep 1; done\n")
    os.chmod(script, 0o755)
    out = os.path.join(logs, ".out.abc123")
    p = subprocess.Popen([sys.executable, LIMITED, "--minutes", "0.03", "--grace", "3", "--stdout", out, "--", script],
                         start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    CHILDREN.append(p)
    child = pid_from(os.path.join(d, "child.pid"))
    try:
        t0 = time.time()
        while not os.path.exists(termed) and time.time() - t0 < 10:   # 時間切れの TERM が届いた＝止め途中
            time.sleep(0.05)
        assert os.path.exists(termed), "時間切れの TERM が子に届かない（テストの前提が崩れた）"
        os.kill(p.pid, signal.SIGINT)
        try:
            rc = p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            raise AssertionError("止め途中に信号を受けて、終わらない")
        assert rc == 128 + signal.SIGINT, rc
        assert not [f for f in os.listdir(logs) if f.startswith(".out.")], "一時ファイル（.out.*）が残っている"
        assert wait_dead(child), "子が残っている"
    finally:
        _killpg_quiet(child)


@case
def l15_parent_killed_during_timeout_stop_leaves_no_temp_file():
    """M：時間切れの止め途中に親が KILL されても、一時ファイルを残さず、子孫が止まる（J・A と同じ種類の取りこぼし）。"""
    name = "l15"
    d = os.path.join(BASE, name)
    logs = os.path.join(d, "logs")
    os.makedirs(logs, exist_ok=True)
    termed = os.path.join(d, "termed")
    script = os.path.join(d, "run.sh")
    # TERM を受けたら印を作るが、終わらない（grace の間、止め途中が続く）
    open(script, "w").write(f"#!/bin/sh\ntrap \"echo t > '{termed}'\" TERM\necho $$ > '{d}/child.pid'\necho partial\nwhile :; do sleep 1; done\n")
    os.chmod(script, 0o755)
    out = os.path.join(logs, ".out.abc123")
    runpid = os.path.join(d, "run.pid")
    parent = os.path.join(d, "parent.sh")
    open(parent, "w").write(f"#!/bin/sh\n'{sys.executable}' '{LIMITED}' --minutes 0.03 --grace 3 --stdout '{out}' -- '{script}' &\necho $! > '{runpid}'\nwait\n")
    os.chmod(parent, 0o755)
    par = subprocess.Popen([parent], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    CHILDREN.append(par)
    rl = pid_from(runpid)
    child = pid_from(os.path.join(d, "child.pid"))
    try:
        t0 = time.time()
        while not os.path.exists(termed) and time.time() - t0 < 10:   # 時間切れの TERM が届いた＝止め途中
            time.sleep(0.05)
        assert os.path.exists(termed), "時間切れの TERM が子に届かない（テストの前提が崩れた）"
        os.kill(par.pid, signal.SIGKILL)   # 止め途中（grace 3 秒のうち）に親を殺す
        par.wait(timeout=5)
        assert wait_dead(rl, 10), "親が死んだのに、run_limited が残っている"
        assert wait_dead(child, 5), "子が残っている"
        assert not [f for f in os.listdir(logs) if f.startswith(".out.")], "一時ファイル（.out.*）が残っている"
    finally:
        _kill_quiet(rl)
        _killpg_quiet(child)


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


# ---------- 2b. 手数の上限の設定（T066：auto.max_turns） ----------
print("## 2b. 手数の上限の設定（auto.max_turns）")
PHASES = ("plan", "do", "review")
TURN_DEFAULT = {"plan": 100, "do": 300, "review": 100}


@case
def u1_turns_default_100_300_100_when_not_set():
    root = make_owner("u1")
    assert {p: wc.turns_for(root, p) for p in PHASES} == TURN_DEFAULT
    root = make_owner("u1b", {"auto": {"max_minutes": 30}})   # 時間の上限だけ書いてあっても、手数は既定
    assert {p: wc.turns_for(root, p) for p in PHASES} == TURN_DEFAULT


@case
def u2_invalid_turns_fall_back_to_that_phases_default():
    bads = ("abc", 0, -1, 1.5, True, False, {}, [], None, "5", "", float("inf"), float("nan"), [3], 1e30, 0.0, -0.5)
    for i, bad in enumerate(bads):
        for form in ("single", "dict"):
            val = bad if form == "single" else {p: bad for p in PHASES}
            root = make_owner(f"u2_{i}_{form}", {"auto": {"max_turns": val}})
            got = {p: wc.turns_for(root, p) for p in PHASES}
            assert got == TURN_DEFAULT, (bad, form, got)   # どの段階でも同じ値に戻さず、その段階の既定に戻る


@case
def u3_partial_config_changes_only_the_written_phase():
    root = make_owner("u3", {"auto": {"max_turns": {"do": 7}}})
    assert {p: wc.turns_for(root, p) for p in PHASES} == {"plan": 100, "do": 7, "review": 100}
    root = make_owner("u3b", {"auto": {"max_turns": {"plan": 5, "do": "x", "review": 0}}})
    assert {p: wc.turns_for(root, p) for p in PHASES} == {"plan": 5, "do": 300, "review": 100}   # 悪い値の段階だけ既定
    root = make_owner("u3c", {"auto": {"max_turns": {"review": 1}}})
    assert wc.turns_for(root, "review") == 1   # 1 は通す（下限）


@case
def u4_broken_or_missing_config_uses_defaults():
    root = make_owner("u4")
    open(os.path.join(root, "設定", "config.json"), "w").write("{broken")
    assert {p: wc.turns_for(root, p) for p in PHASES} == TURN_DEFAULT
    os.remove(os.path.join(root, "設定", "config.json"))
    assert {p: wc.turns_for(root, p) for p in PHASES} == TURN_DEFAULT
    for bad_auto in ("oops", [], 5, None):
        root = make_owner("u4_" + str(type(bad_auto).__name__), {"auto": bad_auto})
        assert {p: wc.turns_for(root, p) for p in PHASES} == TURN_DEFAULT, bad_auto
    open(os.path.join(root, "設定", "config.json"), "wb").write(b"\xef\xbb\xbf" + json.dumps({"auto": {"max_turns": {"do": 9}}}).encode())
    assert wc.turns_for(root, "do") == 9   # BOM 付きでも読む
    assert wc.turns_for(root, "nonsense") == 100   # 知らない段階は計画と同じ既定


@case
def u5_cli_prints_turns_and_a_single_number_applies_to_all():
    root = make_owner("u5", {"auto": {"max_turns": {"do": 0, "review": 12}}})
    run = lambda *a: subprocess.run([sys.executable, os.path.join(SCRIPTS, "watch_check.py"), *a], capture_output=True, text=True)
    assert run("turns", root, "do").stdout.strip() == "300"
    assert run("turns", root, "review").stdout.strip() == "12"
    assert run("turns", root, "plan").stdout.strip() == "100"
    root = make_owner("u5b", {"auto": {"max_turns": 40}})
    assert [wc.turns_for(root, p) for p in PHASES] == [40, 40, 40]


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
def k6_rm_allowed_by_ng_allow_is_still_normal():
    # 本人が rm を ng_allow で許可していても、見張りは壊れていない（--explain の2行目が「本人の許可する例外（ng_allow）に一致」）
    for i, pat in enumerate(("^rm ", "rm", ".*", "x", "^rm x$")):
        root = make_owner(f"k6_{i}", cfg={"ng_allow": [pat]})
        ok, why = wc.canary(root, REAL_GUARD)
        assert ok, (pat, why)
    # 例外の一致以外で rm x が pass なら、今までどおり壊れている判定
    root = make_owner("k6_none", cfg={"ng_allow": ["^rm "]})
    for name, body in (("pass", ALL_PASS_GUARD),
                       ("norule", 'print("判定：pass")\nprint("理由：当たる規則なし")\n'),
                       ("other", 'print("判定：pass")\nprint("理由：別の理由で通した")\n')):
        ok, why = wc.canary(root, fake_guard("k6_" + name, body))
        assert not ok and why, (name, ok, why)
    # 例外に一致したと答える見張りなら、rm x が pass でも正常（date は pass）
    allow_guard = ('import sys\nif "rm" in sys.argv[-1]:\n    print("判定：pass")\n'
                   '    print("理由：本人の許可する例外（ng_allow）に一致（当たった規則：x）")\n'
                   'else:\n    print("判定：pass")\n    print("理由：当たる規則なし")\n')
    ok, why = wc.canary(root, fake_guard("k6_allow", allow_guard))
    assert ok, why


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


@case
def s6_friday_mark_is_visible_monday_morning_to_afternoon():
    # 金曜の朝（計画＋実行で約4時間後）に止まった印が、月曜の朝〜夕方でも見える。5日たてば消える（営業日は数えず暦で4日）
    root = make_owner("s6")
    auto = os.path.join(root, "scripts", "auto")
    fri = datetime(2026, 10, 30, 9, 0)
    wc.mark_timeout(auto, "do", 180, fri)
    for mon in (datetime(2026, 11, 2, 9, 0), datetime(2026, 11, 2, 12, 0), datetime(2026, 11, 2, 16, 59)):
        ws = wc.session_warnings(root, auto, mon, guard=REAL_GUARD)
        assert len(ws) == 1 and "時間の上限で止まりました" in ws[0], (mon, ws)
    assert wc.session_warnings(root, auto, datetime(2026, 11, 3, 10, 0), guard=REAL_GUARD) == []


@case
def w1_old_three_column_mark_reads_as_minutes():
    root = make_owner("w1")
    auto = os.path.join(root, "scripts", "auto")
    now = datetime.now()
    at = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    open(os.path.join(auto, wc.TIMEOUT_MARK), "w", encoding="utf-8").write(f"{at}\tdo\t180\n")   # 古い3列の印
    m = wc.read_timeout(auto)
    assert m and m[1] == "do" and m[2] == "180" and m[3] == "minutes", m
    ws = wc.session_warnings(root, auto, now, guard=REAL_GUARD)
    assert len(ws) == 1 and "時間の上限で止まりました" in ws[0] and "180分" in ws[0] and "手数" not in ws[0], ws
    line = wc.timeout_line_today(auto, now)
    assert "時間の上限で止まった" in line and "180分" in line and "回" not in line, line
    # 4列目が知らない値・空のときも minutes と読む（安全な側）
    for tail in ("\tfoo", "\t", "\tTURNS"):
        open(os.path.join(auto, wc.TIMEOUT_MARK), "w", encoding="utf-8").write(f"{at}\tdo\t180{tail}\n")
        assert wc.read_timeout(auto)[3] == "minutes", tail


@case
def w2_turns_mark_is_written_with_a_fourth_column_and_read_back():
    root = make_owner("w2")
    auto = os.path.join(root, "scripts", "auto")
    now = datetime.now()
    wc.mark_timeout(auto, "do", 300, now - timedelta(hours=1), kind="turns")
    raw = open(os.path.join(auto, wc.TIMEOUT_MARK), encoding="utf-8").read().rstrip("\n").split("\t")
    assert len(raw) == 4 and raw[1:] == ["do", "300", "turns"], raw
    m = wc.read_timeout(auto)
    assert m[1] == "do" and m[2] == "300" and m[3] == "turns", m
    # 時間の上限の印も4列目（minutes）を書く。既存の呼び方（kind を渡さない）は minutes
    wc.mark_timeout(auto, "plan", 60, now)
    raw = open(os.path.join(auto, wc.TIMEOUT_MARK), encoding="utf-8").read().rstrip("\n").split("\t")
    assert raw[1:] == ["plan", "60", "minutes"], raw
    assert wc.read_timeout(auto)[3] == "minutes"
    try:
        wc.mark_timeout(auto, "plan", 60, now, kind="bogus")
        raise AssertionError("知らない種類を通した")
    except ValueError:
        pass


@case
def w3_turns_mark_says_count_not_minutes_everywhere():
    root = make_owner("w3")
    auto = os.path.join(root, "scripts", "auto")
    now = datetime.now()
    wc.mark_timeout(auto, "do", 300, now - timedelta(hours=1), kind="turns")
    ws = wc.session_warnings(root, auto, now, guard=REAL_GUARD)
    assert len(ws) == 1 and "手数の上限で止まりました" in ws[0] and "300回" in ws[0], ws
    assert "分" not in ws[0].replace("時分", "") and "時間の上限" not in ws[0], ws
    line = wc.timeout_line_today(auto, now)
    assert "手数の上限で止まった" in line and "実行" in line and "300回" in line, line
    assert "分" not in line.replace("時分", "").split("。")[0] and "時間の上限" not in line, line
    assert "作業中のタスクと実行中の daily_sprints が残っている" in line
    # 古くなれば出ない・同じ段階の成功で消える（時間の上限と同じ）
    assert wc.session_warnings(root, auto, now + timedelta(days=5), guard=REAL_GUARD) == []
    wc.clear_timeout(auto, "plan")
    assert wc.read_timeout(auto) is not None
    wc.clear_timeout(auto, "do")
    assert wc.read_timeout(auto) is None


@case
def w4_cli_mark_timeout_takes_an_optional_kind():
    root = make_owner("w4")
    auto = os.path.join(root, "scripts", "auto")
    run = lambda *a: subprocess.run([sys.executable, os.path.join(SCRIPTS, "watch_check.py"), *a], capture_output=True, text=True)
    assert run("mark-timeout", auto, "review", "100", "turns").returncode == 0
    m = wc.read_timeout(auto)
    assert m[1] == "review" and m[2] == "100" and m[3] == "turns", m
    assert run("mark-timeout", auto, "do", "0.05").returncode == 0     # 種類を省くと minutes（daily_cycle.sh の今の呼び方）
    m = wc.read_timeout(auto)
    assert m[2] == "0.05" and m[3] == "minutes", m
    r = run("mark-timeout", auto, "do", "5", "bogus")
    assert r.returncode != 0 and wc.read_timeout(auto)[3] == "minutes", (r.returncode, r.stderr)   # 知らない種類は書かない


# ---------- 6. daily_cycle.sh（作り物の claude で通して動かす） ----------
print("## 6. 自動実行（daily_cycle.sh）")
# 新旧の比べ：環境変数 CYCLE_UNDER_TEST に別の版の daily_cycle.sh を指すと、その版でこの節を流せる（既定は今の版）
CYCLE = os.environ.get("CYCLE_UNDER_TEST") or os.path.join(SCRIPTS, "auto", "daily_cycle.sh")

DASH_STUB = '''import os, sys, time
a = sys.argv[1:]
if "--session" in a:
    sys.exit(0)
mode = os.environ.get("STUB_MODE", "plan")
if "--plan-context" in a:
    if mode == "holiday":
        print("SKIP: 営業日ではない"); sys.exit(0)
    if mode == "do":
        print("OPEN"); sys.exit(0)
    n = os.path.join(os.environ["AI_BUNSHIN_HOME"], "plan_calls")
    c = int(open(n).read()) if os.path.exists(n) else 0
    open(n, "w").write(str(c + 1))
    print("OPEN" if c == 0 else "今日の計画は作成済み")
if "--review-context" in a:
    print({"skip": "SKIP: 今日の動きなし", "holiday": "SKIP: 営業日ではない"}.get(mode, "OPEN"))
    print("議事録の保存先: 01_スプリント/S1/daily/" + time.strftime("%Y%m%d") + "_振り返り.md")
'''


def make_cycle(name, claude_body, cfg=None, guard=None):
    d = os.path.join(BASE, name)
    plugin = os.path.join(d, "plugin")
    os.makedirs(os.path.join(plugin, "scripts", "auto"))
    shutil.copy(CYCLE, os.path.join(plugin, "scripts", "auto", "daily_cycle.sh"))
    shutil.copy(LIMITED, os.path.join(plugin, "scripts", "auto", "run_limited.py"))
    for f in ("lock_check.py", "watch_check.py", "ng_guard.py", "ng_guard_legacy.py", "sandbox_settings.py", "protected_paths.json"):
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


def cycle_env(c, mode):
    env = {k: v for k, v in os.environ.items() if k not in ("AI_BUNSHIN_AUTO_RUN", "CLAUDE_PROJECT_DIR")}
    env["AI_BUNSHIN_HOME"] = c["home"]
    env["PATH"] = c["bindir"] + os.pathsep + env.get("PATH", "")
    env["STUB_MODE"] = mode
    env["HOME"] = FAKE_HOME
    return env


def run_cycle(c, phase, mode="plan", timeout=90):
    return subprocess.run(["/bin/zsh", os.path.join(c["plugin"], "scripts", "auto", "daily_cycle.sh"), phase],
                          capture_output=True, text=True, env=cycle_env(c, mode), timeout=timeout)


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
    assert "claude を起動（時間の上限 60分・手数の上限 100回）" in log, log   # T066：起動の行に手数の上限も出す
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
def d10_holiday_skip_does_not_clear_the_mark():
    # 印を消すのは、Claude が実際に成功したときだけ。休日の SKIP（営業日ではない）では、成功の記録は書いても印は消さない
    for phase, mode in (("review", "holiday"), ("plan", "holiday")):
        c = make_cycle("d10_" + phase, "echo should-not-run")
        auto = os.path.join(c["home"], "scripts", "auto")
        wc.mark_timeout(auto, phase, 60)
        r = run_cycle(c, phase, mode=mode)
        assert r.returncode == 0, (phase, r.returncode, r.stderr[:200])
        assert calls_of(c) == [], f"{phase}：休日なのに claude を起動した"
        assert wc.read_timeout(auto) is not None, f"{phase}：休日の SKIP で印が消えた"
        assert os.path.exists(os.path.join(auto, f"last_success_{phase}.txt")), "休日の SKIP の成功の記録は今までどおり書く"


@case
def d11_no_activity_skip_keeps_the_mark_and_writes_the_line():
    # 「今日の動きなし」の分岐でも、今日の時間の上限の印があれば議事録に「時間の上限で止まった」を書く
    c = make_cycle("d11", "echo should-not-run")
    auto = os.path.join(c["home"], "scripts", "auto")
    wc.mark_timeout(auto, "do", 180)
    r = run_cycle(c, "review", mode="skip")
    assert r.returncode == 0, (r.returncode, r.stderr[:200])
    minutes = read(os.path.join(c["home"], "01_スプリント", "S1", "daily", datetime.now().strftime("%Y%m%d") + "_振り返り.md"))
    assert "開催なし" in minutes and "時間の上限で止まった" in minutes and "180分" in minutes, minutes
    assert len([ln for ln in minutes.splitlines() if "時間の上限で止まった" in ln]) == 1, minutes
    assert wc.read_timeout(auto) is not None, "動きなしの SKIP で印が消えた"
    # 印が無い・昨日以前の印なら、書かない
    c = make_cycle("d11b", "echo should-not-run")
    r = run_cycle(c, "review", mode="skip")
    minutes = read(os.path.join(c["home"], "01_スプリント", "S1", "daily", datetime.now().strftime("%Y%m%d") + "_振り返り.md"))
    assert "開催なし" in minutes and "時間の上限" not in minutes, minutes
    c = make_cycle("d11c", "echo should-not-run")
    wc.mark_timeout(os.path.join(c["home"], "scripts", "auto"), "do", 180, datetime.now() - timedelta(days=1, hours=1))
    r = run_cycle(c, "review", mode="skip")
    minutes = read(os.path.join(c["home"], "01_スプリント", "S1", "daily", datetime.now().strftime("%Y%m%d") + "_振り返り.md"))
    assert "開催なし" in minutes and "時間の上限" not in minutes, minutes


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


# ---------- 6a. 手数の上限（T066）：claude に --max-turns を付ける・上限の文面を見分ける ----------
print("## 6a. 手数の上限（daily_cycle.sh）")
TURNS_MSG = "Error: Reached max turns ({n})"


def args_body(d, tail="echo done"):
    """claude に渡された引数を、1回ごとに1行で残す作り物。"""
    return f"echo \"$*\" >> '{d}/args.txt'\n{tail}"


def args_of(d):
    return [ln for ln in read(os.path.join(d, "args.txt")).splitlines() if ln.strip()]


def turns_in(arg_line):
    parts = arg_line.split()
    return parts[parts.index("--max-turns") + 1] if "--max-turns" in parts else None


@case
def g1_default_max_turns_are_100_300_100_per_phase():
    d = os.path.join(BASE, "g1_review")
    c = make_cycle("g1_review", args_body(d))
    r = run_cycle(c, "review", mode="review")
    assert args_of(d) and turns_in(args_of(d)[-1]) == "100", (args_of(d), r.stderr[:200])
    # 実行だけ（手動）：作り物の plan-context は 1 回目が「計画なし」・2 回目から「作成済み」を返すので、2 回動かす
    d = os.path.join(BASE, "g1_do")
    c = make_cycle("g1_do", args_body(d))
    run_cycle(c, "do", mode="plan")
    r = run_cycle(c, "do", mode="plan")
    assert args_of(d) and turns_in(args_of(d)[-1]) == "300", (args_of(d), r.stderr[:200])
    # 計画→続けて実行：計画100、実行300
    d = os.path.join(BASE, "g1_plan")
    c = make_cycle("g1_plan", args_body(d))
    r = run_cycle(c, "plan", mode="plan")
    a = args_of(d)
    assert r.returncode == 0 and [turns_in(x) for x in a] == ["100", "300"], (a, r.stderr[:200])


@case
def g2_config_changes_only_the_written_phase_and_the_second_launch_uses_do_limit():
    d = os.path.join(BASE, "g2")
    c = make_cycle("g2", args_body(d), cfg={"auto": {"max_turns": {"plan": 5, "do": 7}}})
    r = run_cycle(c, "plan", mode="plan")
    a = args_of(d)
    assert r.returncode == 0 and [turns_in(x) for x in a] == ["5", "7"], (a, r.stderr[:200])     # 破られ方 10：実行は実行の上限に決め直す
    assert calls_of(c) == ["/ai-bunshin:daily-plan", "/ai-bunshin:daily-do"]
    d = os.path.join(BASE, "g2b")
    c = make_cycle("g2b", args_body(d), cfg={"auto": {"max_turns": {"do": 7}}})
    run_cycle(c, "review", mode="review")
    assert turns_in(args_of(d)[-1]) == "100"   # 書いていない段階は既定


@case
def g3_invalid_or_broken_config_uses_each_phases_default_in_the_real_run():
    for i, bad in enumerate(("abc", 0, -1, 1.5, True, {}, [])):
        d = os.path.join(BASE, f"g3_{i}")
        c = make_cycle(f"g3_{i}", args_body(d), cfg={"auto": {"max_turns": {"review": bad, "plan": bad, "do": bad}}})
        r = run_cycle(c, "plan", mode="plan")
        assert [turns_in(x) for x in args_of(d)] == ["100", "300"], (bad, args_of(d), r.stderr[:200])
    d = os.path.join(BASE, "g3_broken")
    c = make_cycle("g3_broken", args_body(d))
    open(os.path.join(c["home"], "設定", "config.json"), "w").write("{broken")
    r = run_cycle(c, "review", mode="review")
    assert r.returncode == 0 and turns_in(args_of(d)[-1]) == "100", (args_of(d), r.stderr[:200])


@case
def g4_exit_1_with_the_limit_message_on_the_last_line_is_a_turns_stop():
    d = os.path.join(BASE, "g4")
    body = f"echo 'working...'\necho '{TURNS_MSG.format(n=7)}'\nexit 1"
    c = make_cycle("g4", body, cfg={"auto": {"max_turns": {"review": 7}}})
    r = run_cycle(c, "review", mode="review")
    assert r.returncode == 124, (r.returncode, r.stdout[:200], r.stderr[:300])
    log = cycle_log(c)
    assert "手数の上限（7回）で振り返りを止めました。続きは会話で" in log, log
    notes = read(c["notes"])
    assert "手数の上限（7回）で振り返りを止めました。続きは会話で" in notes, notes
    assert "失敗" not in notes and "時間の上限" not in notes and "分" not in notes.replace("分間", ""), notes   # 失敗の通知は出さない・「N分」と出さない
    m = wc.read_timeout(os.path.join(c["home"], "scripts", "auto"))
    assert m and m[1] == "review" and m[2] == "7" and m[3] == "turns", m
    assert not os.path.exists(os.path.join(c["home"], "scripts", "auto", ".lock")), "ロックが残っている"
    assert not os.path.exists(os.path.join(c["home"], "scripts", "auto", "last_success_review.txt")), "止めたのに成功の記録を書いた"
    assert not [f for f in os.listdir(os.path.join(c["home"], "scripts", "auto", "logs")) if f.startswith(".out.")]


@case
def g5_the_message_in_the_middle_or_with_other_exit_code_is_an_ordinary_result():
    # 6：途中の行に同じ文面（最後は別）→ ふつうの失敗
    body = f"echo '{TURNS_MSG.format(n=3)}'\necho 'something else'\nexit 1"
    c = make_cycle("g5a", body)
    r = run_cycle(c, "review", mode="review")
    assert r.returncode == 1 and "失敗" in read(c["notes"]) and "手数の上限（" not in read(c["notes"]) + cycle_log(c), (r.returncode, read(c["notes"]))
    assert wc.read_timeout(os.path.join(c["home"], "scripts", "auto")) is None
    # 7：終了コード 0 で本文に同じ文面 → ふつうの成功
    body = f"echo 'こう出ることがあります'\necho '{TURNS_MSG.format(n=3)}'\nexit 0"
    c = make_cycle("g5b", body)
    r = run_cycle(c, "review", mode="review")
    assert r.returncode == 0 and wc.read_timeout(os.path.join(c["home"], "scripts", "auto")) is None, (r.returncode, read(c["notes"]))
    assert os.path.exists(os.path.join(c["home"], "scripts", "auto", "last_success_review.txt"))
    assert "手数の上限（" not in read(c["notes"]) + cycle_log(c)
    # 終了コードが 1 でないとき（2・124 以外）は、文面があってもふつうの失敗
    c = make_cycle("g5c", f"echo '{TURNS_MSG.format(n=3)}'\nexit 2")
    r = run_cycle(c, "review", mode="review")
    assert r.returncode == 1 and "失敗" in read(c["notes"]) and wc.read_timeout(os.path.join(c["home"], "scripts", "auto")) is None


@case
def g6_near_miss_messages_are_ordinary_failures():
    # 文面が少しでも違えば（安全な側）ふつうの失敗：末尾の空白・数が無い・数が数字でない・前に文字がある・大文字小文字
    for i, last in enumerate(("Error: Reached max turns (7) ", "Error: Reached max turns ()", "Error: Reached max turns (x)",
                              "error: reached max turns (7)", "[Error: Reached max turns (7)]", "Error: Reached max turns (7) extra",
                              "Error: Reached max turns 7", "Error: Reached max turns (-7)")):
        c = make_cycle(f"g6_{i}", f"printf '%s\\n' '{last}'\nexit 1")
        r = run_cycle(c, "review", mode="review")
        assert r.returncode == 1 and "失敗" in read(c["notes"]), (last, r.returncode, read(c["notes"]))
        assert wc.read_timeout(os.path.join(c["home"], "scripts", "auto")) is None, last


@case
def g7_trailing_blank_lines_are_ignored_and_the_number_in_the_message_is_used():
    body = f"printf 'a\\n%s\\n\\n\\n' '{TURNS_MSG.format(n=42)}'\nexit 1"
    c = make_cycle("g7", body)    # 設定は既定（100）だが、出力の数（42）を使う
    r = run_cycle(c, "review", mode="review")
    assert r.returncode == 124, (r.returncode, r.stderr[:200])
    assert "手数の上限（42回）" in read(c["notes"]) and wc.read_timeout(os.path.join(c["home"], "scripts", "auto"))[2] == "42"


@case
def g8_stopped_plan_by_turns_does_not_continue_to_do_and_do_stop_marks_do():
    d = os.path.join(BASE, "g8")
    body = f"echo \"$*\" >> '{d}/args.txt'\necho '{TURNS_MSG.format(n=5)}'\nexit 1"
    c = make_cycle("g8", body, cfg={"auto": {"max_turns": {"plan": 5}}})
    r = run_cycle(c, "plan", mode="plan")
    assert r.returncode == 124 and calls_of(c) == ["/ai-bunshin:daily-plan"], (r.returncode, calls_of(c))
    m = wc.read_timeout(os.path.join(c["home"], "scripts", "auto"))
    assert m and m[1] == "plan" and m[3] == "turns", m
    assert not os.path.exists(os.path.join(c["home"], "scripts", "auto", ".lock"))
    # 計画は終わり、続けて入った実行が手数の上限に届く
    d = os.path.join(BASE, "g8b")
    body = f'''case "$2" in
  /ai-bunshin:daily-plan) echo planned ;;
  *) echo '{TURNS_MSG.format(n=9)}'; exit 1 ;;
esac'''
    c = make_cycle("g8b", body, cfg={"auto": {"max_turns": {"do": 9}}})
    r = run_cycle(c, "plan", mode="plan")
    assert r.returncode == 124 and calls_of(c) == ["/ai-bunshin:daily-plan", "/ai-bunshin:daily-do"], (r.returncode, calls_of(c))
    m = wc.read_timeout(os.path.join(c["home"], "scripts", "auto"))
    assert m and m[1] == "do" and m[2] == "9" and m[3] == "turns", m
    assert "手数の上限（9回）で実行を止めました" in read(c["notes"]) and "失敗" not in read(c["notes"]), read(c["notes"])
    assert os.path.exists(os.path.join(c["home"], "scripts", "auto", "last_success_plan.txt"))


@case
def g9_same_phase_success_clears_a_turns_mark():
    c = make_cycle("g9", "echo done")
    auto = os.path.join(c["home"], "scripts", "auto")
    wc.mark_timeout(auto, "review", 100, kind="turns")
    r = run_cycle(c, "review", mode="review")
    assert r.returncode == 0 and wc.read_timeout(auto) is None, (r.returncode, wc.read_timeout(auto))


@case
def g10_time_limit_path_is_unchanged_and_writes_minutes_kind():
    d = os.path.join(BASE, "g10")
    c = make_cycle("g10", hang_body(d, "g"), cfg={"auto": {"max_minutes": {"review": 0.05}}})
    r = run_cycle(c, "review", mode="review")
    assert r.returncode == 124, (r.returncode, r.stderr[:200])
    assert "時間の上限（0.05分）で振り返りを止めました" in read(c["notes"]) and "手数" not in read(c["notes"])
    m = wc.read_timeout(os.path.join(c["home"], "scripts", "auto"))
    assert m and m[2] == "0.05" and m[3] == "minutes", m


# ---------- 6b. daily_cycle.sh が TERM・HUP・INT を受けたとき（T095 の直し） ----------
print("## 6b. 自動実行へのシグナル（TERM・HUP・INT）")
SIGNALS = (("TERM", signal.SIGTERM), ("HUP", signal.SIGHUP), ("INT", signal.SIGINT))


def start_cycle(c, phase, mode):
    """daily_cycle.sh を別のセッションで起動する（シグナルを送る相手は、このテストが起動したこのプロセスだけ）。"""
    p = subprocess.Popen(["/bin/zsh", os.path.join(c["plugin"], "scripts", "auto", "daily_cycle.sh"), phase],
                         env=cycle_env(c, mode), start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    CHILDREN.append(p)
    return p


def stop_leftovers(pids):
    """（新旧の比べで旧版が残したものも含め）このテストが起動した作り物を、最後に片づける。"""
    for pid in pids:
        for fn in (os.killpg, os.kill):
            try:
                fn(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass


def long_claude_body(d):
    """居座る作り物の claude：自分の PID と孫（sleep）の PID を書いて待つ。"""
    return f"echo $$ > '{d}/claude.pid'\nsleep 300 &\necho $! > '{d}/grand.pid'\nwait"


def out_files(c):
    d = os.path.join(c["home"], "scripts", "auto", "logs")
    return [f for f in os.listdir(d) if f.startswith(".out.")] if os.path.isdir(d) else []


def wait_out_file(c, sec=10):
    t0 = time.time()
    while time.time() - t0 < sec and not out_files(c):
        time.sleep(0.05)


def _cycle_signal_case(name, signame, sig, ignore_term=False):
    decoy = start_decoy(name)
    d = os.path.join(BASE, name)
    body = ("trap '' TERM\n" if ignore_term else "") + long_claude_body(d)
    c = make_cycle(name, body, cfg={"auto": {"max_minutes": {"review": 5}}})
    auto = os.path.join(c["home"], "scripts", "auto")
    p = start_cycle(c, "review", "review")
    pids = []
    problems = []   # 1つ見つけても止まらず、全部集めて最後にまとめて知らせる（新旧の比べで、どこが違うかを見るため）
    try:
        claude_pid = pid_from(os.path.join(d, "claude.pid"), 30)
        grand = pid_from(os.path.join(d, "grand.pid"), 30)
        pids = [claude_pid, grand]
        wait_out_file(c)   # run_limited が claude を起動したあとに送る
        os.kill(p.pid, sig)
        try:
            rc = p.wait(timeout=30)
            if rc != 128 + sig:
                problems.append(f"終了コードが {rc}（期待 {128 + sig}）")
        except subprocess.TimeoutExpired:
            problems.append("daily_cycle.sh が終わらない")
        if not wait_dead(claude_pid, 12):
            problems.append("偽 claude が残っている")
        if not wait_dead(grand, 12):
            problems.append("孫のプロセスが残っている")
        if not (decoy.poll() is None and alive(decoy.pid)):
            problems.append("おとりまで止めた")
        if os.path.exists(os.path.join(auto, ".lock")):
            problems.append("ロックが残っている")
        if out_files(c):
            problems.append("一時ファイル（.out.*）が残っている")
        if os.path.exists(os.path.join(auto, "last_success_review.txt")):
            problems.append("止められたのに成功の記録を書いた")
        if wc.read_timeout(auto) is not None:
            problems.append("シグナルで止まったのに「時間の上限」の印を書いた")
        stops = [ln for ln in cycle_log(c).splitlines() if "シグナル" in ln]
        if not (len(stops) == 1 and signame in stops[0]):
            problems.append(f"止まったことのログが1行でない：{stops}")
        elif "claude を止め" not in stops[0] or "ありませんでした" in stops[0]:
            problems.append(f"claude を止めたのに、ログがそう書いていない：{stops[0]}")
        if "終了 (exit=" in cycle_log(c):
            problems.append("止められたのに、ふつうの終わり方のログを書いた")
        if "失敗" in read(c["notes"]):
            problems.append("止められたのに「失敗」と通知した")
    finally:
        stop_leftovers(pids)
    assert not problems, f"{signame}：" + "／".join(problems) + (f"\nログ：{cycle_log(c)[-800:]}" if problems else "")


@case
def e1_term_stops_claude_and_grandchild_and_cleans_up():
    _cycle_signal_case("e1", *SIGNALS[0])


@case
def e2_hup_stops_claude_and_grandchild_and_cleans_up():
    _cycle_signal_case("e2", *SIGNALS[1])


@case
def e3_int_stops_claude_and_grandchild_and_cleans_up():
    _cycle_signal_case("e3", *SIGNALS[2])


@case
def e4_term_with_claude_ignoring_term_is_killed_after_grace():
    # TERM を無視する偽 claude でも、run_limited の猶予（5秒）のあと KILL で止まり、ロックと一時ファイルは残らない
    _cycle_signal_case("e4", "TERM", signal.SIGTERM, ignore_term=True)


@case
def e9_term_to_the_whole_group_like_launchd_leaves_nothing():
    # launchd が停止のときにするような、daily_cycle.sh のグループ全体への TERM。claude は別のセッションなので、グループへの TERM は届かない。
    # それでも、孫まで止まり、ロックと一時ファイルが残らない（新旧の比べ：run_limited の導入前の版では、claude が同じグループなので届いた）
    decoy = start_decoy("e9")
    d = os.path.join(BASE, "e9")
    c = make_cycle("e9", long_claude_body(d), cfg={"auto": {"max_minutes": {"review": 5}}})
    auto = os.path.join(c["home"], "scripts", "auto")
    p = start_cycle(c, "review", "review")
    pids = []
    problems = []
    try:
        pids = [pid_from(os.path.join(d, "claude.pid"), 30), pid_from(os.path.join(d, "grand.pid"), 30)]
        wait_out_file(c)
        os.killpg(p.pid, signal.SIGTERM)   # p はこのテストが新しいセッションで起動した daily_cycle.sh（そのグループだけに送る）
        try:
            rc = p.wait(timeout=30)
            if rc != 143:
                problems.append(f"終了コードが {rc}（期待 143）")
        except subprocess.TimeoutExpired:
            problems.append("daily_cycle.sh が終わらない")
        if not all(wait_dead(x, 12) for x in pids):
            problems.append("偽 claude か孫が残っている")
        if not (decoy.poll() is None and alive(decoy.pid)):
            problems.append("おとりまで止めた")
        if os.path.exists(os.path.join(auto, ".lock")):
            problems.append("ロックが残っている")
        if out_files(c):
            problems.append("一時ファイル（.out.*）が残っている")
    finally:
        stop_leftovers(pids)
    assert not problems, "／".join(problems) + f"\nログ：{cycle_log(c)[-800:]}"


def patched_cycle(name, claude_body, anchor, replacement, cfg=None):
    """作り物の daily_cycle.sh の写しの、決まった1行（anchor）のあとに、時機をずらすための行を足す（本物のスクリプトは変えない）。"""
    c = make_cycle(name, claude_body, cfg=cfg)
    path = os.path.join(c["plugin"], "scripts", "auto", "daily_cycle.sh")
    text = read(path)
    assert text.count(anchor) == 1, f"目印の行が見つからない（または2つ以上）：{anchor!r}"
    open(path, "w", encoding="utf-8").write(text.replace(anchor, anchor + replacement, 1))
    return c


def hold_with_bystander(d, phases_not="plan"):
    """claude を起動する直前（LAUNCHING=1 のあと）で3秒止まる。止まる前に、同じグループに「関係ない居座りプロセス」を1つ置く
    （$! を変えないよう、コマンド置換の中で背景に出す）。シグナルの転送先を取り違えて自分のグループ全体に送ると、これが止まってしまう。"""
    return (f'  if [ "$PHASE" != {phases_not} ]; then\n'
            f"    : $(sh -c 'echo $$ > \"{d}/bystander.pid\"; exec sleep 120' >/dev/null 2>&1 &)\n"
            f"    /bin/sleep 3\n  fi\n")


@case
def e10_signal_just_before_the_first_launch_does_not_hit_its_own_group():
    # 最初の起動の直前：$! がまだ 0（または空）のとき、kill に 0 を渡すと自分のグループ全体に届く。届かないこと。
    decoy = start_decoy("e10")
    d = os.path.join(BASE, "e10")
    os.makedirs(d, exist_ok=True)
    c = patched_cycle("e10", "echo should-not-run", '  LAUNCHING=1\n', hold_with_bystander(d, "none"))
    auto = os.path.join(c["home"], "scripts", "auto")
    p = start_cycle(c, "review", "review")
    pids = []
    try:
        pids = [pid_from(os.path.join(d, "bystander.pid"), 30)]
        time.sleep(0.5)
        os.kill(p.pid, signal.SIGTERM)
        rc = p.wait(timeout=30)
        assert rc == 143, rc
        assert alive(pids[0]), "起動の直前に受けて、自分のグループ全体に信号を送った（関係ないプロセスまで止めた）"
        assert decoy.poll() is None and alive(decoy.pid)
        assert calls_of(c) == [], "止められたのに claude を起動した"
        assert not os.path.exists(os.path.join(auto, ".lock")) and not out_files(c)
        assert len([ln for ln in cycle_log(c).splitlines() if "シグナル" in ln]) == 1
    finally:
        stop_leftovers(pids)


@case
def e11_signal_just_before_the_second_launch_ignores_the_old_pid():
    # 計画のあと実行に入る直前：$! は計画のときの run_limited の PID（もう終わっている）。それに信号を送らず、実行の claude を起動せずに 143 で終わる
    d = os.path.join(BASE, "e11")
    os.makedirs(d, exist_ok=True)
    body = """case "$2" in
  /ai-bunshin:daily-plan) echo planned ;;
  *) echo should-not-run ;;
esac"""
    c = patched_cycle("e11", body, '  LAUNCHING=1\n', hold_with_bystander(d, "plan"))
    # 「前の $!」を生きた PID にする：実行の起動で BG_BEFORE=$! を控える直前に、居座るプロセスを背景に出す（$! がその PID になる）。
    # 前の PID が死んでいると、kill -0 で弾かれて、BG_BEFORE との比べが無くても通ってしまう。生きていれば、比べが効いていないと TERM が届いて落ちる
    path = os.path.join(c["plugin"], "scripts", "auto", "daily_cycle.sh")
    text = read(path)
    anchor2 = "  BG_BEFORE=$!\n"
    assert text.count(anchor2) == 1, "BG_BEFORE の行が見つからない（または2つ以上）"
    live = (f'  if [ "$PHASE" != plan ]; then\n    sleep 120 &\n    echo $! > "{d}/oldpid.pid"\n  fi\n')
    open(path, "w", encoding="utf-8").write(text.replace(anchor2, live + anchor2, 1))
    auto = os.path.join(c["home"], "scripts", "auto")
    p = start_cycle(c, "plan", "plan")
    pids = []
    try:
        pids = [pid_from(os.path.join(d, "bystander.pid"), 40), pid_from(os.path.join(d, "oldpid.pid"), 40)]   # 実行の起動の直前に着いた
        time.sleep(0.5)
        assert alive(pids[1]), "前の PID に見立てたプロセスが、信号の前に死んでいる（テストの前提が崩れた）"
        os.kill(p.pid, signal.SIGTERM)
        rc = p.wait(timeout=30)
        assert rc == 143, rc
        assert alive(pids[0]), "関係ないプロセスまで止めた"
        time.sleep(0.5)
        assert alive(pids[1]), "前の $!（生きていた）に信号を送った"
        assert calls_of(c) == ["/ai-bunshin:daily-plan"], calls_of(c)
        assert not os.path.exists(os.path.join(auto, ".lock")) and not out_files(c)
        assert os.path.exists(os.path.join(auto, "last_success_plan.txt")) and not os.path.exists(os.path.join(auto, "last_success_do.txt"))
    finally:
        stop_leftovers(pids)


@case
def e12_signal_between_plan_and_do_during_the_notification():
    # 計画が終わった通知（osascript）の最中に受ける：実行（daily-do）には入らない。ロック・一時ファイルは残らず、143 で終わる
    c = make_cycle("e12", "echo planned")
    stub = os.path.join(c["bindir"], "osascript")
    open(stub, "w").write(f'#!/bin/sh\necho "$*" >> "{c["notes"]}"\nsleep 2\n')
    auto = os.path.join(c["home"], "scripts", "auto")
    p = start_cycle(c, "plan", "plan")
    try:
        t0 = time.time()
        while time.time() - t0 < 30 and "planned" not in read(c["notes"]):
            time.sleep(0.01)
        time.sleep(0.3)
        os.kill(p.pid, signal.SIGTERM)
        rc = p.wait(timeout=30)
        assert rc == 143, rc
        assert calls_of(c) == ["/ai-bunshin:daily-plan"], calls_of(c)
        assert not os.path.exists(os.path.join(auto, ".lock")) and not out_files(c)
        assert os.path.exists(os.path.join(auto, "last_success_plan.txt")) and not os.path.exists(os.path.join(auto, "last_success_do.txt"))
        assert len([ln for ln in cycle_log(c).splitlines() if "シグナル" in ln]) == 1
    finally:
        stop_leftovers([p.pid])


@case
def e13_signal_right_after_the_temp_file_is_made_leaves_no_temp_file():
    # 一時ファイル（.out.*）を作った直後・run_limited を起動する前に受ける：残らない
    c = patched_cycle("e13", "echo should-not-run", '  : > "$out" || { log "一時ファイルを作れませんでした"; exit 1; }\n', "  /bin/sleep 3\n")
    auto = os.path.join(c["home"], "scripts", "auto")
    p = start_cycle(c, "review", "review")
    try:
        wait_out_file(c, 30)
        assert out_files(c), "一時ファイルが作られない（テストの前提）"
        time.sleep(0.3)
        os.kill(p.pid, signal.SIGTERM)
        rc = p.wait(timeout=30)
        assert rc == 143, rc
        assert not out_files(c), "一時ファイル（.out.*）が残っている"
        assert not os.path.exists(os.path.join(auto, ".lock")) and calls_of(c) == []
    finally:
        stop_leftovers([p.pid])


# ロックを書いたあと・claude を起動する前（見張りの自己点検の最中）にシグナルが届く。点検を数秒かかるものにして、その間に送る
SLOW_THEN_REAL_GUARD = ('import os, sys, time\ntime.sleep(4)\n'
                        'os.execv(sys.executable, [sys.executable, %r] + sys.argv[1:])\n' % REAL_GUARD)


def _signal_before_launch(name, signame, sig):
    c = make_cycle(name, "echo should-not-run", guard=SLOW_THEN_REAL_GUARD)
    auto = os.path.join(c["home"], "scripts", "auto")
    p = start_cycle(c, "review", "review")
    try:
        t0 = time.time()
        while time.time() - t0 < 30 and not os.path.exists(os.path.join(auto, ".lock")):
            time.sleep(0.02)
        assert os.path.exists(os.path.join(auto, ".lock")), "ロックが書かれない"
        time.sleep(0.5)   # 自己点検の最中
        assert "claude を起動" not in cycle_log(c), "もう claude を起動している（テストの前提が崩れた）"
        os.kill(p.pid, sig)
        try:
            rc = p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            raise AssertionError(f"{signame}：終わらない")
        assert rc == 128 + sig, (signame, rc)
        assert not os.path.exists(os.path.join(auto, ".lock")), f"{signame}：起動前に受けたのにロックが残っている"
        assert calls_of(c) == [], f"{signame}：止められたのに claude を起動した"
        assert not os.path.exists(os.path.join(auto, "last_success_review.txt"))
        assert wc.read_timeout(auto) is None
        assert not out_files(c)
        # ログの文は実際の動きと合わせる：起動していない claude を「止めた」と書かない
        stops = [ln for ln in cycle_log(c).splitlines() if "シグナル" in ln]
        assert len(stops) == 1 and "claude を止め" not in stops[0] and "起動中の claude はありませんでした" in stops[0], stops
    finally:
        stop_leftovers([p.pid])


@case
def e5_signal_after_lock_before_claude_leaves_no_lock():
    for signame, sig in SIGNALS:
        _signal_before_launch("e5_" + signame, signame, sig)


@case
def e6_exit_codes_pass_through_unchanged():
    # ふつうの終了（0）・失敗（0以外）・自分で KILL された（137）・子が 124 を返した。wait の戻りと子の終了コードを取り違えない
    c = make_cycle("e6a", "echo done")
    r = run_cycle(c, "review", mode="review")
    assert r.returncode == 0 and "終了 (exit=0)" in cycle_log(c), (r.returncode, cycle_log(c))
    for code in (1, 3, 42):
        c = make_cycle(f"e6_{code}", f"echo partial\nexit {code}")
        r = run_cycle(c, "review", mode="review")
        assert r.returncode == 1, (code, r.returncode)
        assert f"終了 (exit={code})" in cycle_log(c), (code, cycle_log(c))
        assert "失敗" in read(c["notes"]) and not os.path.exists(os.path.join(c["home"], "scripts", "auto", "last_success_review.txt"))
    c = make_cycle("e6_kill", "kill -9 $$")
    r = run_cycle(c, "review", mode="review")
    assert r.returncode == 1 and "終了 (exit=137)" in cycle_log(c), (r.returncode, cycle_log(c))
    c = make_cycle("e6_124", "exit 124")   # 子が自分で 124 を返したときも、上限と同じ扱い（今までと同じ）
    r = run_cycle(c, "review", mode="review")
    assert r.returncode == 124 and "終了 (exit=124)" in cycle_log(c), (r.returncode, cycle_log(c))
    c = make_cycle("e6_empty", "exit 0")   # 出力が空のまま 0 で終わったときは、今までどおり失敗扱い
    r = run_cycle(c, "review", mode="review")
    assert r.returncode == 1 and "終了 (exit=0)" in cycle_log(c), (r.returncode, cycle_log(c))


@case
def e7_plan_then_do_status_is_per_run():
    # 計画の終了コードが、続けて動く実行の終了コードに混ざらない（計画は成功・実行は失敗 3）
    body = """case "$2" in
  /ai-bunshin:daily-plan) echo planned ;;
  *) echo partial; exit 3 ;;
esac"""
    c = make_cycle("e7", body)
    r = run_cycle(c, "plan", mode="plan")
    log = cycle_log(c)
    assert r.returncode == 1 and "終了 (exit=0)" in log and "終了 (exit=3)" in log, (r.returncode, log)
    assert os.path.exists(os.path.join(c["home"], "scripts", "auto", "last_success_plan.txt"))
    assert not os.path.exists(os.path.join(c["home"], "scripts", "auto", "last_success_do.txt"))


@case
def e8_signal_during_plan_does_not_continue_to_do():
    # 計画の最中に TERM → 実行（daily-do）には入らない。続けて動く実行の最中に TERM → 実行の claude も止まる
    d = os.path.join(BASE, "e8")
    c = make_cycle("e8", f"""case "$2" in
  /ai-bunshin:daily-plan) echo planned ;;
  *) {long_claude_body(d)} ;;
esac""", cfg={"auto": {"max_minutes": {"plan": 5, "do": 5}}})
    auto = os.path.join(c["home"], "scripts", "auto")
    p = start_cycle(c, "plan", "plan")
    pids = []
    try:
        pids = [pid_from(os.path.join(d, "claude.pid"), 40), pid_from(os.path.join(d, "grand.pid"), 40)]   # 実行の claude
        wait_out_file(c)
        os.kill(p.pid, signal.SIGTERM)
        rc = p.wait(timeout=30)
        assert rc == 128 + signal.SIGTERM, rc
        assert all(wait_dead(x, 12) for x in pids), "実行の claude か孫が残っている"
        assert not os.path.exists(os.path.join(auto, ".lock")) and not out_files(c)
        assert os.path.exists(os.path.join(auto, "last_success_plan.txt")), "止める前に済んだ計画の成功の記録は残る"
        assert not os.path.exists(os.path.join(auto, "last_success_do.txt")) and wc.read_timeout(auto) is None
    finally:
        stop_leftovers(pids)


# ---------- 6c. BOM 付きの config.json（T110）／watch_check.py が動かないときの手数の既定 ----------
print("## 6c. BOM 付きの config.json・watch_check.py が動かないとき")
INSTALL = os.environ.get("INSTALL_UNDER_TEST") or os.path.join(SCRIPTS, "auto", "install.sh")


def write_bom_config(home, cfg):
    """メモ帳で保存したように、先頭に BOM（EF BB BF）を付けて config.json を書く。"""
    with open(os.path.join(home, "設定", "config.json"), "wb") as f:
        f.write(b"\xef\xbb\xbf" + json.dumps(cfg, ensure_ascii=False).encode("utf-8"))


@case
def h1_daily_cycle_reads_a_bom_config_for_the_name_and_the_dev_dirs():
    repo = os.path.join(BASE, "h1_repo")
    os.makedirs(repo)
    d = os.path.join(BASE, "h1")
    c = make_cycle("h1", args_body(d))
    write_bom_config(c["home"], {"ai_name": "BOMのAI", "dev": {"projects": [{"path": repo}]}})
    r = run_cycle(c, "review", mode="review")
    assert r.returncode == 0, (r.returncode, r.stderr[:200])
    assert "BOMのAI" in read(c["notes"]), f"通知の名前が config から読めていない（BOM で落ちて既定の AI になった）：{read(c['notes'])[:200]}"
    assert "--add-dir " + repo in (args_of(d) or [""])[-1], f"開発の置き場所（--add-dir）が config から読めていない：{args_of(d)}"


@case
def h2_install_sh_reads_a_bom_config_for_the_schedule_and_the_path():
    d = os.path.join(BASE, "h2")
    home = os.path.join(d, "owner")
    os.makedirs(os.path.join(home, "設定"))
    fake_home = os.path.join(d, "home")
    os.makedirs(os.path.join(fake_home, "Library", "LaunchAgents"))
    bindir = os.path.join(d, "bin")
    os.makedirs(bindir)
    for name in ("launchctl", "osascript"):   # 本物の launchd には触らない（作り物に差し替える）
        open(os.path.join(bindir, name), "w").write("#!/bin/sh\nexit 0\n")
        os.chmod(os.path.join(bindir, name), 0o755)
    write_bom_config(home, {"schedule": {"plan": "08:15", "review": "16:45"}, "path": "/opt/bom-test/bin:/usr/bin"})
    env = {k: v for k, v in os.environ.items() if k not in ("AI_BUNSHIN_AUTO_RUN", "CLAUDE_PROJECT_DIR")}
    env["HOME"] = fake_home
    env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
    r = subprocess.run(["/bin/zsh", INSTALL, home], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, (r.returncode, r.stdout[-300:], r.stderr[-300:])
    assert "計画 8:15" in r.stdout and "振り返り 16:45" in r.stdout, r.stdout
    run_sh = read(os.path.join(home, "scripts", "auto", "run.sh"))
    assert 'export PATH="/opt/bom-test/bin:/usr/bin"' in run_sh, run_sh[:300]
    plist = read(os.path.join(fake_home, "Library", "LaunchAgents", "com.ai-bunshin.daily-plan.plist"))
    assert "<key>Hour</key><integer>8</integer>" in plist and "<key>Minute</key><integer>15</integer>" in plist, plist


FAKE_WATCH_KINDS = {
    "exits_1": "exit 1",
    "empty": "exit 0",
    "garbage": "echo 'abc'; exit 0",
    "dead_python": "exec python3 -c 'import nonexistent_module_xyz'",
}


def install_fake_watch(c, turns_body):
    """作り物の watch_check.py に差し替える：turns だけ壊し（turns_body をシェルで動かす）、ほかの呼び出し（canary など）は本物に渡す。"""
    scripts = os.path.join(c["plugin"], "scripts")
    os.rename(os.path.join(scripts, "watch_check.py"), os.path.join(scripts, "watch_real.py"))
    open(os.path.join(scripts, "watch_check.py"), "w", encoding="utf-8").write(
        "import os, subprocess, sys\n"
        "if sys.argv[1:2] == ['turns']:\n"
        f"    sys.exit(subprocess.run(['/bin/sh', '-c', {turns_body!r}]).returncode)\n"
        "here = os.path.dirname(os.path.abspath(__file__))\n"
        "sys.exit(subprocess.run([sys.executable, os.path.join(here, 'watch_real.py'), *sys.argv[1:]]).returncode)\n")


@case
def h3_dead_or_empty_watch_check_uses_the_shell_defaults_100_300_100():
    # watch_check.py の turns が動かない・空・数でない値を返すとき、シェル側の既定（計画 100・実行 300・振り返り 100）になる。
    # config に別の数を書いても、watch_check が答えない以上は既定（シェルは config を自分では読まない）
    cfg = {"auto": {"max_turns": {"plan": 5, "do": 7, "review": 9}}}
    for kind, body in FAKE_WATCH_KINDS.items():
        d = os.path.join(BASE, f"h3_{kind}")
        c = make_cycle(f"h3_{kind}", args_body(d), cfg=cfg)
        install_fake_watch(c, body)
        r = run_cycle(c, "plan", mode="plan")   # 計画 → 続けて実行
        assert r.returncode == 0 and [turns_in(x) for x in args_of(d)] == ["100", "300"], (kind, [turns_in(x) for x in args_of(d)], r.stderr[:200])
        d2 = os.path.join(BASE, f"h3r_{kind}")
        c2 = make_cycle(f"h3r_{kind}", args_body(d2), cfg=cfg)
        install_fake_watch(c2, body)
        r = run_cycle(c2, "review", mode="review")
        assert r.returncode == 0 and [turns_in(x) for x in args_of(d2)] == ["100"], (kind, [turns_in(x) for x in args_of(d2)], r.stderr[:200])
        d3 = os.path.join(BASE, f"h3d_{kind}")   # 実行だけ（手動）。作り物の plan-context は 2 回目から「作成済み」を返すので 2 回動かす
        c3 = make_cycle(f"h3d_{kind}", args_body(d3), cfg=cfg)
        install_fake_watch(c3, body)
        run_cycle(c3, "do", mode="plan")
        r = run_cycle(c3, "do", mode="plan")
        assert [turns_in(x) for x in args_of(d3)][-1:] == ["300"], (kind, [turns_in(x) for x in args_of(d3)], r.stderr[:200])


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
def x1_daily_do_sprint_dev_have_the_eight_calls_per_task_per_day_rule_and_keep_the_old_stops():
    # T066 B：1タスクで部下を呼ぶのは、その日の合計8回まで。今の「最大3周」「同じ失敗が2回続いたら3周目に入らない」は消えていない
    for name, t in (("daily-do", DAILY_DO), ("sprint", SPRINT), ("dev", DEV)):
        for key in ("1タスクで部下を呼ぶのは、その日の合計8回まで", "作る・確かめる・デザインの呼び出し", "SendMessage での続き", "Check 会議", "今どこ？",
                    "翌朝0から", "do_log の開始の行", "最大3周", "目標ではない"):
            assert key in t, (name, key)
        assert "3周目に入らない" in t or "3周目に入らず" in t, name
        assert "どれかに先に届いたら止める" in t, name
        assert "止めずに" in t and "本人に1行伝える" in t, (name, "会話の中の扱い")
    for key in ("手戻りの上限", "blockers", "次のタスクへ", "デザインの呼び出しと続きでも開始の行を書く", "同じ失敗が2回続いたら3周目に入らず報告する",
                "手戻り3周："):
        assert key in DAILY_DO, key
    assert "手戻りの上限" in DEV and "blockers" in DEV
    assert "ここでは決めない" not in SPRINT and "S10" in SPRINT      # 「決めない」を、この決まりへの参照に直した
    assert "`/ai-bunshin:daily-do` の「部下を出すとき」" in SPRINT and "`/ai-bunshin:daily-do` の「部下を出すとき」" in DEV


@case
def x2_skills_know_both_kinds_of_stop_mark():
    assert "--max-turns" in DAILY_DO and "auto.max_turns" in DAILY_DO and "計画 100・実行 300・振り返り 100" in DAILY_DO
    assert "部下の中の手数は数えられない" in DAILY_DO and "`turns`" in DAILY_DO and "`minutes`" in DAILY_DO
    assert "auto.max_minutes" in DAILY_DO and "計画 60分・実行 180分・振り返り 60分" in DAILY_DO      # 時間の上限は変えていない
    plan = text_of("skills", "daily-plan", "SKILL.md")
    review = text_of("skills", "daily-review", "SKILL.md")
    line = [ln for ln in plan.splitlines() if "last_timeout.txt" in ln][0]
    assert "手数の上限" in line and "`turns`" in line and "4列目が無ければ `minutes`" in line, line
    rline = [ln for ln in review.splitlines() if "last_timeout.txt" in ln][0]
    assert "手数の上限で止まった" in rline and "時間の上限で止まった" in rline and "N回" in rline and "4列目が無ければ `minutes`" in rline, rline


@case
def t5_every_agent_does_not_call_other_agents_and_dev_a_has_the_rest():
    for name in ("analyst", "buka-a", "buka-b", "design", "dev-a", "dev-b", "trainer"):
        t = text_of("agents", name + ".md")
        assert "他の部下を呼びません" in t and "同じ失敗が2回続いたとき" in t, name
    a = text_of("agents", "dev-a.md")
    assert "同じ失敗が2回続いたら3周目に入らず" in a and "`.bak` を残し" in a and "改名（`mv`）" in a and "戻しのコマンド" in a
    assert "最大3周" in a   # 今ある文は消えていない


@case
def t7_broken_watch_asks_the_owner_from_the_start():
    # 部下も同じ壊れた見張りの下にいて戻せない。最初から本人に1行のコマンドを頼む（「部下に戻させ、戻せなければ」ではない）
    step8 = [ln for ln in SPRINT.splitlines() if ln.startswith("8. ")][0]
    rule = [ln for ln in COMMANDER.splitlines() if ln.startswith("- **見張りが壊れて Bash が全部止まったら**")][0]
    for name, t in (("commander", rule), ("sprint 手順8", step8)):
        assert "部下も同じ壊れた見張りの下にいて戻せない" in t, name
        assert "最初から本人に" in t and "`! …`" in t, name
        assert "戻させ" not in t and "戻せなければ" not in t, name
        assert "戻しのコマンドは直す前に用意" in t, name
    assert "／簡単なコマンドも止まる" not in step8     # 「A／B」のあいまいな並べ方をやめた
    assert "または簡単なコマンドも止まる" in step8


@case
def t8_daily_plan_only_carries_over_after_a_time_limit_stop():
    plan = text_of("skills", "daily-plan", "SKILL.md")
    line = [ln for ln in plan.splitlines() if "last_timeout.txt" in ln][0]
    assert "持ち越し" in line and "始めからやり直さず" in line, line
    assert "見積もり直す" not in line and "2回続けて" not in line and "範囲を分けてから" not in line, line


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
