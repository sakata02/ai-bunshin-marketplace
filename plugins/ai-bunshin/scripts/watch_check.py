#!/usr/bin/env python3
"""長引き・止まりに気づくための小さな道具（T095）。update_dashboard.py（起動時のまとめ）と daily_cycle.sh（自動実行）が使う。

- 見張りの自己点検（canary）：ng_guard.py --explain で「date は pass・rm x は deny」を確かめる。壊れていれば「壊れている」とみなす
- ng_log の「見張りの入力を読めませんでした」を数える（補助。数える語は ng_guard.py の BROKEN_LABEL を1か所から読む）
- 自動実行の時間の上限（config の auto.max_minutes）と、「時間の上限で止めた」記録の印（scripts/auto/last_timeout.txt）

ng_guard.py の判定は変えない。ここは読むだけ（印のファイル以外は書かない）。

コマンド（daily_cycle.sh から）：
  watch_check.py canary <本人のフォルダ>             … 異常なし 0／壊れている 1（理由を1行出す）
  watch_check.py minutes <本人のフォルダ> <段階>      … 段階（plan／do／review）の時間の上限（分）を出す
  watch_check.py wait-minutes <本人のフォルダ> <段階>  … 前の段階を待つ分（整数）。review は do の上限、ほかは plan の上限
  watch_check.py broken-since <本人のフォルダ> "YYYY-MM-DD HH:MM:SS"  … その時刻以降の「読めませんでした」の数
  watch_check.py mark-timeout <scripts/auto> <段階> <分>
  watch_check.py clear-timeout <scripts/auto> <段階>  … 同じ段階の印だけ消す
"""
import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
GUARD = HERE / "ng_guard.py"

DEFAULT_MINUTES = {"plan": 60, "do": 180, "review": 60}   # 計画 60分・実行 180分・振り返り 60分
BROKEN_THRESHOLD = 3          # 「見張りの入力を読めませんでした」がこの回数以上で知らせる
BROKEN_WINDOW_HOURS = 24      # 起動時のまとめが数える期間
TIMEOUT_MARK = "last_timeout.txt"
TIMEOUT_MARK_DAYS = 3         # 印がこの日数より古ければ起動時のまとめには出さない
CANARY_SECONDS = 20


# ---------- 見張りの自己点検（canary） ----------

def canary(root, guard=None, timeout=CANARY_SECONDS):
    """今その場で動いている見張り（guard。既定はこのファイルと同じ場所の ng_guard.py）を点検する。
    本人のフォルダ（root）の中で、"date" が pass・"rm x" が deny でなければ壊れているとみなす。
    返り値：(正常か, 理由の1行)。"""
    guard = Path(guard) if guard else GUARD
    if not guard.is_file():
        return False, f"見張り（{guard.name}）が見つかりません"
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    env["PYTHONIOENCODING"] = "utf-8"   # 文字コードを決めない環境（launchd など）でも、日本語の答えを読めるように
    env["PYTHONUTF8"] = "1"
    for command, want in (("date", "pass"), ("rm x", "deny")):
        try:
            r = subprocess.run([sys.executable, str(guard), "--explain", command], capture_output=True,
                               cwd=str(root), env=env, timeout=timeout, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return False, f"見張りが{timeout}秒たっても答えません（点検：{command}）"
        except OSError as e:
            return False, f"見張りを動かせません（{e.__class__.__name__}）"
        out = (r.stdout or b"").decode("utf-8", errors="replace")
        err = (r.stderr or b"").decode("utf-8", errors="replace")
        first = out.splitlines()[0].strip() if out.strip() else ""
        if r.returncode != 0 or first != f"判定：{want}":
            tail = (err.strip().splitlines() or [""])[-1][:80]
            return False, f"点検「{command}」で {want} を返しませんでした（終了コード {r.returncode}）" + (f"：{tail}" if tail else "")
    return True, "正常"


# ---------- ng_log の「読めませんでした」 ----------

def broken_label(guard=None):
    """ng_guard.py の BROKEN_LABEL を、ソースから1か所で読む（語を写さない）。読めなければ None。"""
    guard = Path(guard) if guard else GUARD
    try:
        text = guard.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    m = re.search(r'^BROKEN_LABEL\s*=\s*"([^"\n]+)"', text, re.M)
    return m.group(1) if m else None


def _parse_at(s):
    try:
        return datetime.strptime(str(s).strip()[:19], "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def broken_count(root, since, until=None, guard=None):
    """ng_log.jsonl の、since 以上 until 以下（until 省略なら上限なし）の「見張りの入力を読めませんでした」の数。
    ファイルが無い・読めない・壊れた行・形の違う行は数えない（落ちない）。"""
    label = broken_label(guard)
    if not label:
        return 0
    log = Path(root) / "00_タスク管理" / "data" / "ng_log.jsonl"
    try:
        raw = log.read_bytes()
    except OSError:
        return 0
    n = 0
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or rec.get("label") != label:
            continue
        at = _parse_at(rec.get("at"))
        if at is None or at < since or (until is not None and at > until):
            continue
        n += 1
    return n


# ---------- 時間の上限（config の auto.max_minutes） ----------

def _valid_minutes(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if not math.isfinite(v) or v <= 0:
        return None
    return v


def minutes_for(root, phase):
    """段階（plan／do／review）の時間の上限（分）。config の auto.max_minutes が、段階ごとの辞書（{"plan": 60, "do": 180, "review": 60}）
    でも、全段階共通の数でもよい。0・負・文字・真偽・無限・config が読めないときは既定（60／180／60）。"""
    default = DEFAULT_MINUTES.get(phase, 60)
    try:
        cfg = json.loads((Path(root) / "設定" / "config.json").read_text(encoding="utf-8"))
        mm = (cfg.get("auto") or {}).get("max_minutes")
    except (OSError, ValueError, AttributeError, UnicodeDecodeError):
        return default
    if isinstance(mm, dict):
        mm = mm.get(phase)
    v = _valid_minutes(mm)
    if v is None:
        return default
    return int(v) if float(v).is_integer() else v


def wait_minutes(root, phase):
    """前の段階を待つ分（整数）。振り返りは実行の終わりを待つので実行の上限、ほかは計画の上限。同じ設定から出す。"""
    return max(1, math.ceil(minutes_for(root, "do" if phase == "review" else "plan")))


def _fmt_min(m):
    return str(int(m)) if float(m).is_integer() else f"{m:g}"


# ---------- 「時間の上限で止めた」の印 ----------

def mark_timeout(auto_dir, phase, minutes, now=None):
    """scripts/auto/last_timeout.txt に1行（YYYY-MM-DD HH:MM<TAB>段階<TAB>分）を書く。"""
    now = now or datetime.now()
    p = Path(auto_dir) / TIMEOUT_MARK
    tmp = p.with_name(TIMEOUT_MARK + f".tmp.{os.getpid()}")
    tmp.write_text(f"{now.strftime('%Y-%m-%d %H:%M')}\t{phase}\t{_fmt_min(minutes)}\n", encoding="utf-8")
    os.replace(tmp, p)


def read_timeout(auto_dir):
    """印を読む。(日時, 段階, 分) か、無い・形が違うときは None。"""
    try:
        parts = (Path(auto_dir) / TIMEOUT_MARK).read_text(encoding="utf-8").strip().split("\t")
        at = datetime.strptime(parts[0], "%Y-%m-%d %H:%M")
        return at, parts[1], parts[2]
    except (OSError, ValueError, IndexError, UnicodeDecodeError):
        return None


def clear_timeout(auto_dir, phase):
    """同じ段階の印だけ消す（その段階が後で成功したとき）。"""
    m = read_timeout(auto_dir)
    if m and m[1] == phase:
        try:
            (Path(auto_dir) / TIMEOUT_MARK).unlink()
        except OSError:
            pass


# ---------- 起動時のまとめの警告 ----------

def session_warnings(root, auto_dir, now=None, guard=None, call="本人"):
    """起動時のまとめの先頭に出す警告（短い1行ずつ。出力の先頭 1,500 バイトに収める）。"""
    now = now or datetime.now()
    out = []
    root = Path(root)
    if (root / "設定" / "config.json").exists() or (root / "00_タスク管理" / "data" / "tasks.json").exists():
        ok, why = canary(root, guard)
        if not ok:
            out.append(f"[⚠ 見張りが壊れている可能性]（{why[:60]}）直しが途中なら、元の版に戻してください。"
                       f"Bash が止まるときは{call}に `! …` の1行を頼みます")
    n = broken_count(root, now - timedelta(hours=BROKEN_WINDOW_HOURS), now, guard)
    if n >= BROKEN_THRESHOLD:
        out.append(f"[⚠ 見張りがコマンドを読めない状態が続きました（{n}回）]見張りの直しが途中なら、元の版に戻してください")
    m = read_timeout(auto_dir)
    if m and timedelta(0) <= now - m[0] <= timedelta(days=TIMEOUT_MARK_DAYS):
        out.append(f"[⚠ 自動実行が時間の上限で止まりました（{m[0].month}/{m[0].day} {m[0].strftime('%H:%M')}・{m[2]}分）]"
                   "作業中のタスクが残っています。続きは会話で")
    return out


def main(argv):
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 64
    cmd, args = argv[1], argv[2:]
    try:
        if cmd == "canary" and len(args) == 1:
            ok, why = canary(args[0])
            print(why)
            return 0 if ok else 1
        if cmd == "minutes" and len(args) == 2:
            print(_fmt_min(minutes_for(args[0], args[1])))
            return 0
        if cmd == "wait-minutes" and len(args) == 2:
            print(wait_minutes(args[0], args[1]))
            return 0
        if cmd == "broken-since" and len(args) == 2:
            since = _parse_at(args[1])
            print(broken_count(args[0], since) if since else 0)
            return 0
        if cmd == "mark-timeout" and len(args) == 3:
            mark_timeout(args[0], args[1], float(args[2]))
            return 0
        if cmd == "clear-timeout" and len(args) == 2:
            clear_timeout(args[0], args[1])
            return 0
    except (OSError, ValueError) as e:
        print(f"{e.__class__.__name__}: {e}", file=sys.stderr)
        return 1
    print(__doc__, file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv))
