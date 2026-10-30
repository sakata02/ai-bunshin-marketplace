#!/usr/bin/env python3
"""自動実行のロック（scripts/auto/.lock）を見て、「いま開いてよいか」を決める（T080）。

ロックの中身（daily_cycle.sh が書く）：
  1行目 持ち主の PID
  2行目 段階の名前と開始時刻（例：振り返り（17:00開始））
  3行目 その実行の ID（環境変数 AI_BUNSHIN_AUTO_RUN と同じ値）。古い版のロックには無い

判定（1行目に出す）：
  OPEN: ロックなし／古いロック（その PID はもう動いていない）／自分の実行のロック
  SKIP: ほかの実行が動いている（会話から開いたとき・別の自動実行・ID の無い古い形式のロックで PID が生きているとき）

「自分」の目印は ID だけ。自動実行の中の Claude は daily_cycle.sh から AI_BUNSHIN_AUTO_RUN を受け取るので、
ロックの ID と一致すれば自分のロック。会話から開いたときは環境変数が無いので、ロックが生きていれば必ず「ほか」になる。

使い方：python3 lock_check.py [--root 本人のフォルダ]　（読むだけ。何も書かない・消さない。終了コードは常に 0）
"""
import os
import sys
from pathlib import Path

ENV_NAME = "AI_BUNSHIN_AUTO_RUN"


def parse_lock(text):
    """ロックの中身 → (pid, label, run_id)。読めない部分は None（pid が読めないときは古いロック扱い）。"""
    lines = [ln.strip() for ln in (text or "").splitlines()]
    try:
        pid = int(lines[0]) if lines and lines[0] else None
    except ValueError:
        pid = None
    label = lines[1] if len(lines) > 1 and lines[1] else None
    run_id = lines[2] if len(lines) > 2 and lines[2] else None
    return pid, label, run_id


def pid_alive(pid):
    """その PID のプロセスが動いているか（kill -0 と同じ）。"""
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True   # 他のユーザーのプロセス＝動いている
    except OSError:
        return False
    return True


def judge(lock_text, own_run_id, alive=pid_alive):
    """(open か, 種類, 説明)。種類は none / stale / own / other。
    lock_text が None ならロックなし。alive はテストで差し替えられる（PID → bool）。"""
    if lock_text is None:
        return True, "none", "ロックなし"
    pid, label, run_id = parse_lock(lock_text)
    if not alive(pid):
        return True, "stale", f"古いロック（{label or '段階不明'}、PID {pid} は終了済み）。無視して続ける"
    if own_run_id and run_id and own_run_id == run_id:
        return True, "own", f"自分の実行のロック（{label or '段階不明'}、PID {pid}）"
    return False, "other", (f"ほかの実行が動いている（{label or '段階不明'}、PID {pid}）。"
                            "同じ tasks.json と議事録を書き合わないよう、ここでは開かない")


def find_lock(root_arg=None):
    """ロックのパス。--root → AI_BUNSHIN_HOME → CLAUDE_PROJECT_DIR / カレントから上へ（00_タスク管理/data/tasks.json のある所）。"""
    if root_arg:
        return Path(root_arg).resolve() / "scripts" / "auto" / ".lock"
    if os.environ.get("AI_BUNSHIN_HOME"):
        return Path(os.environ["AI_BUNSHIN_HOME"]).resolve() / "scripts" / "auto" / ".lock"
    for c in (os.environ.get("CLAUDE_PROJECT_DIR"), os.getcwd()):
        if not c:
            continue
        d = Path(c).resolve()
        for x in [d, *d.parents]:
            if (x / "00_タスク管理" / "data" / "tasks.json").exists():
                return x / "scripts" / "auto" / ".lock"
    return Path(os.getcwd()).resolve() / "scripts" / "auto" / ".lock"


def main(argv):
    root_arg = None
    if "--root" in argv:
        i = argv.index("--root")
        root_arg = argv[i + 1] if i + 1 < len(argv) else None
    lock = find_lock(root_arg)
    try:
        text = lock.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = None
    except OSError as e:
        # 読めないときは安全側（開かない）。古いロックと決めつけない
        print(f"SKIP: ロックを読めない（{e.__class__.__name__}）。ほかの実行が動いているかもしれないので開かない")
        return 0
    ok, _kind, msg = judge(text, os.environ.get(ENV_NAME))
    print(("OPEN: " if ok else "SKIP: ") + msg)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
