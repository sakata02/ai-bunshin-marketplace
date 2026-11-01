#!/usr/bin/env python3
"""時間の上限つきでコマンド（自動実行の claude）を動かす（T095）。daily_cycle.sh が使う。

  run_limited.py --minutes N --stdout FILE [--grace 秒] -- コマンド 引数…

- コマンドは新しいセッション（プロセスグループ）で起動する。上限を超えたら、そのグループだけに TERM を送り、
  grace 秒（既定 5）待って、まだ残っていれば KILL。孫のプロセスも同じグループなので一緒に止まる。
  止める対象は自分が起動したグループだけ（名前で探して止める pkill -f などは使わない）
- コマンドの標準出力は FILE に書く（標準エラーは呼び出し元のものをそのまま引き継ぐ）。標準入力は引き継ぐ
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


def run(cmd, seconds, stdout_path, grace=5.0):
    with open(stdout_path, "wb") as out:
        try:
            p = subprocess.Popen(cmd, stdout=out, start_new_session=True)
        except OSError as e:
            print(f"起動できませんでした：{e}", file=sys.stderr)
            return 127
        try:
            rc = p.wait(timeout=seconds)
            return rc if rc >= 0 else 128 - rc
        except subprocess.TimeoutExpired:
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
            return TIMED_OUT


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
