#!/usr/bin/env python3
"""長引き・止まりに気づくための小さな道具（T095）。update_dashboard.py（起動時のまとめ）と daily_cycle.sh（自動実行）が使う。

- 見張りの自己点検（canary）：ng_guard.py --explain で「date は pass・rm x は deny」を確かめる。壊れていれば「壊れている」とみなす
- ng_log の「見張りの入力を読めませんでした」を数える（補助。数える語は ng_guard.py の BROKEN_LABEL を1か所から読む）
- 自動実行の時間の上限（config の auto.max_minutes）・手数の上限（auto.max_turns。T066）と、「上限で止めた」記録の印（scripts/auto/last_timeout.txt）

ng_guard.py の判定は変えない。ここは読むだけ（印のファイル以外は書かない）。

コマンド（daily_cycle.sh から）：
  watch_check.py canary <本人のフォルダ>             … 異常なし 0／壊れている 1（理由を1行出す）
  watch_check.py minutes <本人のフォルダ> <段階>      … 段階（plan／do／review）の時間の上限（分）を出す
  watch_check.py turns <本人のフォルダ> <段階>        … 段階（plan／do／review）の手数の上限（回）を出す（既定 100／300／100）
  watch_check.py wait-minutes <本人のフォルダ> <段階>  … 前の段階を待つ分（整数）。review は do の上限、ほかは plan の上限
  watch_check.py broken-since <本人のフォルダ> "YYYY-MM-DD HH:MM:SS"  … その時刻以降の「読めませんでした」の数
  watch_check.py mark-timeout <scripts/auto> <段階> <分か回> [minutes|turns]  … 種類を省くと minutes
  watch_check.py clear-timeout <scripts/auto> <段階>  … 同じ段階の印だけ消す（Claude が実際に成功したときだけ呼ぶ）
  watch_check.py timeout-line <scripts/auto>          … 今日の印があれば、議事録に書く1行を出す（無ければ空）
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
DEFAULT_TURNS = {"plan": 100, "do": 300, "review": 100}   # 指揮官の手数（claude -p --max-turns）。計画 100・実行 300・振り返り 100（T066）
TIMEOUT_KINDS = ("minutes", "turns")                      # 印の4列目。無い・知らない値は minutes と読む
BROKEN_THRESHOLD = 3          # 「見張りの入力を読めませんでした」がこの回数以上で知らせる
BROKEN_WINDOW_HOURS = 24      # 起動時のまとめが数える期間
TIMEOUT_MARK = "last_timeout.txt"
TIMEOUT_MARK_DAYS = 4         # 印がこの日数より古ければ起動時のまとめには出さない（営業日は数えず暦で。金曜の印が月曜の夕方まで見える長さ）
CANARY_SECONDS = 20
ALLOW_REASON = "理由：本人の許可する例外（ng_allow）に一致"   # ng_guard.py --explain の2行目（例外で通ったとき）


# ---------- 見張りの自己点検（canary） ----------

def canary(root, guard=None, timeout=CANARY_SECONDS):
    """今その場で動いている見張り（guard。既定はこのファイルと同じ場所の ng_guard.py）を点検する。
    本人のフォルダ（root）の中で、"date" が pass・"rm x" が deny でなければ壊れているとみなす。
    ただし本人が rm を ng_allow で許可していて、rm x が「本人の許可する例外（ng_allow）に一致」で pass のときは正常。
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
        lines = [ln.strip() for ln in out.splitlines()]
        first = lines[0] if lines else ""
        second = lines[1] if len(lines) > 1 else ""
        # 本人が rm を ng_allow で許可しているときは、rm x が pass でも壊れていない（2行目が例外の一致を言っているときだけ）
        allowed = command == "rm x" and first == "判定：pass" and second.startswith(ALLOW_REASON)
        if r.returncode != 0 or (first != f"判定：{want}" and not allowed):
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
        cfg = json.loads((Path(root) / "設定" / "config.json").read_text(encoding="utf-8-sig"))   # BOM 付き（メモ帳）でも読む
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


def _valid_turns(v):
    """手数の上限として通すのは、1以上の整数だけ（真偽・小数・文字・辞書・配列は通さない）。"""
    if isinstance(v, bool) or not isinstance(v, int) or v < 1:
        return None
    return v


def turns_for(root, phase):
    """段階（plan／do／review）の手数の上限（回）。config の auto.max_turns が、段階ごとの辞書（{"plan": 100, "do": 300, "review": 100}）
    でも、全段階共通の数でもよい。通すのは1以上の整数だけ。悪い値・config が読めないときは、**その段階の既定**（100／300／100）に戻す。"""
    default = DEFAULT_TURNS.get(phase, DEFAULT_TURNS["plan"])
    try:
        cfg = json.loads((Path(root) / "設定" / "config.json").read_text(encoding="utf-8-sig"))
        mt = (cfg.get("auto") or {}).get("max_turns")
    except (OSError, ValueError, AttributeError, UnicodeDecodeError):
        return default
    if isinstance(mt, dict):
        mt = mt.get(phase)
    v = _valid_turns(mt)
    return default if v is None else v


def _fmt_min(m):
    return str(int(m)) if float(m).is_integer() else f"{m:g}"


# ---------- 「上限で止めた」の印（時間の上限・手数の上限） ----------

def mark_timeout(auto_dir, phase, amount, now=None, kind="minutes"):
    """scripts/auto/last_timeout.txt に1行（YYYY-MM-DD HH:MM<TAB>段階<TAB>分か回<TAB>種類）を書く。種類は minutes（時間の上限）か turns（手数の上限）。"""
    if kind not in TIMEOUT_KINDS:
        raise ValueError(f"印の種類は {'／'.join(TIMEOUT_KINDS)} のどちらかです: {kind}")
    now = now or datetime.now()
    p = Path(auto_dir) / TIMEOUT_MARK
    tmp = p.with_name(TIMEOUT_MARK + f".tmp.{os.getpid()}")
    tmp.write_text(f"{now.strftime('%Y-%m-%d %H:%M')}\t{phase}\t{_fmt_min(amount)}\t{kind}\n", encoding="utf-8")
    os.replace(tmp, p)


def read_timeout(auto_dir):
    """印を読む。(日時, 段階, 分か回, 種類) か、無い・形が違うときは None。4列目が無い（古い印）・知らない値のときは minutes と読む。"""
    try:
        parts = (Path(auto_dir) / TIMEOUT_MARK).read_text(encoding="utf-8").strip().split("\t")
        at = datetime.strptime(parts[0], "%Y-%m-%d %H:%M")
        kind = parts[3].strip() if len(parts) > 3 else ""
        return at, parts[1], parts[2], (kind if kind in TIMEOUT_KINDS else "minutes")
    except (OSError, ValueError, IndexError, UnicodeDecodeError):
        return None


PHASE_NAMES = {"plan": "計画", "do": "実行", "review": "振り返り"}


def _stop_kind_label(kind):
    """(上限の名前, 数の言い方) の組。minutes は「時間の上限」「N分」、turns は「手数の上限」「N回」。"""
    return ("手数の上限", "回") if kind == "turns" else ("時間の上限", "分")


def timeout_line_today(auto_dir, now=None):
    """今日の印があるときだけ、議事録に書く1行を返す（無い・昨日以前・壊れていれば空）。『今日の動きなし』の日でも止まった事実を残すため。"""
    now = now or datetime.now()
    m = read_timeout(auto_dir)
    if not m or m[0].date() != now.date():
        return ""
    name, unit = _stop_kind_label(m[3])
    return (f"{name}で止まった（{PHASE_NAMES.get(m[1], m[1])}・{m[2]}{unit}・{m[0].strftime('%H:%M')}）。"
            "作業中のタスクと実行中の daily_sprints が残っている")


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
            out.append(f"[⚠ 見張りが壊れている可能性]（{why[:60]}）直しが途中なら、元に戻してください。"
                       f"Bash が止まるときは{call}に `! …` の1行を頼みます")
    n = broken_count(root, now - timedelta(hours=BROKEN_WINDOW_HOURS), now, guard)
    if n >= BROKEN_THRESHOLD:
        out.append(f"[⚠ 見張りがコマンドを読めない状態が続きました（{n}回）]見張りの直しが途中なら、元に戻してください")
    m = read_timeout(auto_dir)
    if m and timedelta(0) <= now - m[0] <= timedelta(days=TIMEOUT_MARK_DAYS):
        name, unit = _stop_kind_label(m[3])
        out.append(f"[⚠ 自動実行が{name}で止まりました（{m[0].month}/{m[0].day} {m[0].strftime('%H:%M')}・{m[2]}{unit}）]"
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
        if cmd == "turns" and len(args) == 2:
            print(turns_for(args[0], args[1]))
            return 0
        if cmd == "wait-minutes" and len(args) == 2:
            print(wait_minutes(args[0], args[1]))
            return 0
        if cmd == "broken-since" and len(args) == 2:
            since = _parse_at(args[1])
            print(broken_count(args[0], since) if since else 0)
            return 0
        if cmd == "mark-timeout" and len(args) in (3, 4):
            mark_timeout(args[0], args[1], float(args[2]), kind=args[3] if len(args) == 4 else "minutes")
            return 0
        if cmd == "timeout-line" and len(args) == 1:
            print(timeout_line_today(args[0]))
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
    # Windows は標準出力が cp932 のことがあり、絵文字で落ちる。入口で UTF-8 にする（reconfigure が無い環境でも落ちない）
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    sys.exit(main(sys.argv))
