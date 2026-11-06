#!/usr/bin/env python3
"""時間の上限つきでコマンド（自動実行の claude）を動かす（T095）。daily_cycle.sh が使う。

  run_limited.py --minutes N --stdout FILE [--grace 秒] -- コマンド 引数…

- コマンドは新しいセッション（プロセスグループ）で起動する。上限を超えたら、そのグループだけに TERM を送り、
  グループが空になるまで最大 grace 秒（既定 5）待って、まだ残っていれば KILL。孫のプロセスも同じグループなので一緒に止まる。
  止める対象は自分が起動したグループだけ（名前で探して止める pkill -f などは使わない）
- コマンドの標準出力は FILE に書く（標準エラーは呼び出し元のものをそのまま引き継ぐ）。標準入力は引き継ぐ
- TERM・HUP・INT を受けたときも同じ：起動したグループを止め（TERM → グループが空になるまで最大 grace 秒待つ → 残っていれば KILL）、FILE を消して、128+シグナル番号で終わる
- 親が死んだとき（親の PID が変わったのを待つ間に見つけたとき）は HUP を受けたのと同じ（129）
- 終了コード：上限で止めたら 124。ふつうに終わったらコマンドの終了コード（シグナルで終わったら 128+番号）
"""
import argparse
import os
import signal
import subprocess
import sys
import time

TIMED_OUT = 124


def _killpg(pgid, sig):
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


STOP_SIGNALS = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)


def _group_empty(pgid):
    """グループにプロセスが残っていないか（signal 0 は送らず、あるかどうかだけ見る）。"""
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):   # PermissionError：残りがゾンビだけのとき macOS で出る
        return True
    return False


def _stop_group(p, grace):
    """自分が起動したグループだけを止める：TERM → グループが空になるまで（最大 grace 秒）待つ → 残っていれば KILL。
    子が先に終わっても、孫が TERM の片づけをする間は待つ（子の終了だけを見て KILL しない）。"""
    pgid = p.pid   # start_new_session=True なので、グループ ID は子の PID
    _killpg(pgid, signal.SIGTERM)
    end = time.monotonic() + grace
    while time.monotonic() < end:
        p.poll()   # 子が終わっていれば回収する（ゾンビのままだとグループが空にならない）
        if _group_empty(pgid):
            break
        time.sleep(0.1)
    _killpg(pgid, signal.SIGKILL)   # 残った子・孫を止める（グループが空なら何も起きない）
    try:
        p.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass


POLL = 0.2   # 待つ間隔（秒）。信号の記録と上限を、このたびに見る


def _note_parent_gone(state, ppid0):
    """親が死んだ（親の PID が起動時と変わった：launchd などが親になった）なら、信号 HUP を受けたことにする。
    読む人がいないので、HUP を受けたときと同じ道で止める（129・一時ファイルを消す）。先に届いた信号があればそれを残す。"""
    if state["sig"] is None and os.getppid() != ppid0:
        state["sig"] = signal.SIGHUP


def run(cmd, seconds, stdout_path, grace=5.0):
    """ハンドラは信号の番号を記録するだけ（例外は出さない）。本体は短い間隔で待ちを繰り返し、そのたびに「記録」と「上限」を見る。
    これで、確認と待ちの間に届いた信号を取りこぼさない（届いても、次の見に行くまでの最大 POLL 秒で気づく）。
    最初に届いた信号の番号を終了コードに使い、止める処理の途中に届いたものは無視する。"""
    state = {"sig": None}
    ppid0 = os.getppid()   # 親が死ぬと、これが変わる（launchd などが親になる）

    def on_signal(signum, frame):
        if state["sig"] is None:
            state["sig"] = signum

    old = {s: signal.signal(s, on_signal) for s in STOP_SIGNALS}
    try:
        with open(stdout_path, "wb") as out:
            try:
                p = subprocess.Popen(cmd, stdout=out, start_new_session=True)
            except OSError as e:
                print(f"起動できませんでした：{e}", file=sys.stderr)
                return 127
            deadline = time.monotonic() + seconds
            rc = None
            stop = None   # "signal" か "timeout"
            while True:
                _note_parent_gone(state, ppid0)
                if state["sig"] is not None:   # 起動する前に届いたものも、ここで見つかる
                    stop = "signal"
                    break
                remain = deadline - time.monotonic()
                if remain <= 0:
                    stop = "timeout"
                    break
                try:
                    rc = p.wait(timeout=min(POLL, remain))
                    break
                except subprocess.TimeoutExpired:
                    continue
            if stop is None and state["sig"] is not None:
                stop = "signal"   # 待ちから戻る瞬間に信号を記録していた（子が先に終わった）。残った孫を止めるため、止める道に入れる
            if stop is not None:
                _stop_group(p, grace)
                _note_parent_gone(state, ppid0)   # 止める途中で親が死んだ場合も拾う
                if stop == "timeout" and state["sig"] is not None:
                    stop = "signal"   # 時間切れの止め途中に信号が届いた（親の死を含む）：記録だけで終わらせず、信号として扱う（128+番号・一時ファイルを消す）
                if stop == "signal":
                    try:
                        os.unlink(stdout_path)   # 止められた実行の一時ファイルは片付ける
                    except OSError:
                        pass
                    return 128 + state["sig"]
                return TIMED_OUT
    finally:
        for s, h in old.items():
            signal.signal(s, h)
    return rc if rc >= 0 else 128 - rc


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, required=True)
    ap.add_argument("--stdout", required=True)
    ap.add_argument("--grace", type=float, default=5.0)
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args(argv)
    cmd = a.cmd[1:] if a.cmd and a.cmd[0] == "--" else a.cmd
    if not cmd or not (a.minutes > 0):
        print("使い方：run_limited.py --minutes N --stdout FILE -- コマンド…（N は 0 より大きい数）", file=sys.stderr)
        return 64
    return run(cmd, a.minutes * 60, a.stdout, a.grace)


if __name__ == "__main__":
    # Windows は標準出力が cp932 のことがあり、絵文字で落ちる。入口で UTF-8 にする（reconfigure が無い環境でも落ちない）
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    sys.exit(main(sys.argv[1:]))
