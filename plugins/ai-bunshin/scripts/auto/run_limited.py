#!/usr/bin/env python3
"""時間の上限つきでコマンド（自動実行の claude）を動かす（T095）。daily_cycle.sh が使う。

  run_limited.py --minutes N --stdout FILE [--grace 秒] -- コマンド 引数…

- コマンドは新しいセッション（プロセスグループ）で起動する。上限を超えたら、そのグループだけに TERM を送り、
  grace 秒（既定 5）待って、まだ残っていれば KILL。孫のプロセスも同じグループなので一緒に止まる。
  止める対象は自分が起動したグループだけ（名前で探して止める pkill -f などは使わない）
- コマンドの標準出力は FILE に書く（標準エラーは呼び出し元のものをそのまま引き継ぐ）。標準入力は引き継ぐ
- TERM・HUP・INT を受けたときも同じ：起動したグループを止め（TERM → grace 秒後に KILL）、FILE を消して、128+シグナル番号で終わる
- 終了コード：上限で止めたら 124。ふつうに終わったらコマンドの終了コード（シグナルで終わったら 128+番号）
"""
import argparse
import os
import signal
import subprocess
import sys

TIMED_OUT = 124


def _killpg(pgid, sig):
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


STOP_SIGNALS = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)


class Stopped(Exception):
    """外側から TERM・HUP・INT を受けた。"""
    def __init__(self, signum):
        super().__init__(signum)
        self.signum = signum


def _stop_group(p, grace):
    """自分が起動したグループだけを止める：TERM → grace 秒待つ → KILL。"""
    pgid = p.pid   # start_new_session=True なので、グループ ID は子の PID
    _killpg(pgid, signal.SIGTERM)
    try:
        p.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass
    _killpg(pgid, signal.SIGKILL)   # 親が先に終わっていても、残った孫を止める（グループが空なら何も起きない）
    try:
        p.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass


def run(cmd, seconds, stdout_path, grace=5.0):
    state = {"p": None, "sig": None}

    def on_signal(signum, frame):
        state["sig"] = signum
        if state["p"] is not None:   # まだ起動していなければ、起動した直後に気づく
            raise Stopped(signum)

    old = {s: signal.signal(s, on_signal) for s in STOP_SIGNALS}
    got = None
    rc = None
    try:
        with open(stdout_path, "wb") as out:
            try:
                p = subprocess.Popen(cmd, stdout=out, start_new_session=True)
            except OSError as e:
                print(f"起動できませんでした：{e}", file=sys.stderr)
                return 127
            state["p"] = p
            try:
                if state["sig"] is not None:
                    raise Stopped(state["sig"])
                rc = p.wait(timeout=seconds)
            except subprocess.TimeoutExpired:
                for s in STOP_SIGNALS:        # 止めている間に重ねて届いても、途中でやめない
                    signal.signal(s, signal.SIG_IGN)
                _stop_group(p, grace)
                rc = TIMED_OUT
            except Stopped as e:
                got = e.signum
                for s in STOP_SIGNALS:
                    signal.signal(s, signal.SIG_IGN)
                _stop_group(p, grace)
    finally:
        for s, h in old.items():
            signal.signal(s, h)
    if got is not None:
        try:
            os.unlink(stdout_path)   # 止められた実行の一時ファイルは片付ける
        except OSError:
            pass
        return 128 + got
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
    sys.exit(main(sys.argv[1:]))
