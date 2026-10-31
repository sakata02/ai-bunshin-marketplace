"""予定を「読めなかった」ときの扱い（calendar_today.py・update_dashboard.py）のテスト。
- 読み込みの失敗（ネットワーク・形式の誤り・キーチェーンに無い・ログイン画面）→「読めませんでした」。「予定なし」とは別
- 本当に0件のときだけ「予定なし」
- タイムゾーンを読めない予定は、時刻をずらさず「時刻不明」
- Windows の分かれ道（platform を差し替える）
キーチェーン・URL・ネットワークはすべて偽物（本物のキーチェーンや URL には触れない）。
実行：python3 tests/test_calendar_errors.py（失敗があれば終了コード1）"""
import contextlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
from datetime import date, datetime
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import calendar_today as c  # noqa: E402

fails = 0


def check(name, ok, detail=""):
    global fails
    if not ok:
        fails += 1
        print("NG  ", name, "←", detail)


@contextlib.contextmanager
def patch(obj, name, value):
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, old)


class FakeRes:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


SECRET = "https://example.invalid/secret-token-123/basic.ics"   # 偽物
TODAY = date.today()
CFG = {"calendar": {"type": "ics", "keychain": "fake-service-for-test"}}
EMPTY_ICS = "BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n"


def new_root():
    root = Path(tempfile.mkdtemp(prefix="calerr_"))
    (root / "00_タスク管理" / "data").mkdir(parents=True)
    return root


def must_not_call(*a, **k):
    raise AssertionError("呼んではいけない")


def is_unreadable(r, label, want_in_error=""):
    check(label + "：error が付く", bool(r and r["error"]), r)
    if not (r and r["error"]):
        return
    check(label + "：予定は空（古い予定も無い）", r["events"] == [] and r["stale"] is None, r)
    check(label + "：理由に URL が入らない", "secret-token" not in r["error"] and "example.invalid" not in r["error"], r["error"])
    if want_in_error:
        check(label + f"：理由に「{want_in_error}」", want_in_error in r["error"], r["error"])
    lines = c.format_events(r["events"], TODAY, r["error"], r["stale"])
    text = "\n".join(lines)
    check(label + "：「読めませんでした」と出る", "予定を読めませんでした" in text, text)
    check(label + "：「（予定なし）」とは出ない", "（予定なし）" not in text, text)


# --- 1. キーチェーン（Mac） -----------------------------------------------
class P:
    def __init__(self, rc, out):
        self.returncode, self.stdout = rc, out


with patch(c.subprocess, "run", lambda *a, **k: P(44, "")):
    try:
        c.keychain_secret("fake-service-for-test")
        check("キーチェーンに無い → CalendarError", False, "例外が出なかった")
    except c.CalendarError as e:
        check("キーチェーンに無い → 理由にサービス名", "fake-service-for-test" in str(e), str(e))
with patch(c.subprocess, "run", lambda *a, **k: P(0, SECRET + "\n")):
    check("キーチェーンの値を返す（偽物）", c.keychain_secret("x") == SECRET)
with patch(c.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("no security"))):
    try:
        c.keychain_secret("x")
        check("security が動かない → CalendarError", False, "例外が出なかった")
    except c.CalendarError:
        pass

with patch(c, "_platform", lambda: "darwin"):
    with patch(c.subprocess, "run", lambda *a, **k: P(44, "")):
        is_unreadable(c.load_calendar(new_root(), CFG, TODAY), "キーチェーンが無い", "キーチェーン")

    # --- 2. ネットワーク・形式 ---
    with patch(c.subprocess, "run", lambda *a, **k: P(0, SECRET)):
        def boom(*a, **k):
            raise urllib.error.URLError("failed to reach " + SECRET)
        with patch(c.urllib.request, "urlopen", boom):
            is_unreadable(c.load_calendar(new_root(), CFG, TODAY), "ネットワーク失敗", "ネットワーク")

        def e404(*a, **k):
            raise urllib.error.HTTPError(SECRET, 404, "Not Found", {}, None)
        with patch(c.urllib.request, "urlopen", e404):
            is_unreadable(c.load_calendar(new_root(), CFG, TODAY), "404", "404")

        def timeout(*a, **k):
            raise TimeoutError("timed out")
        with patch(c.urllib.request, "urlopen", timeout):
            is_unreadable(c.load_calendar(new_root(), CFG, TODAY), "タイムアウト", "ネットワーク")

        with patch(c.urllib.request, "urlopen", lambda *a, **k: FakeRes(b"<html>login</html>")):
            is_unreadable(c.load_calendar(new_root(), CFG, TODAY), "ログイン画面", "形式")

        bad = b"BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART:garbage\nEND:VEVENT\nEND:VCALENDAR\n"
        with patch(c.urllib.request, "urlopen", lambda *a, **k: FakeRes(bad)):
            is_unreadable(c.load_calendar(new_root(), CFG, TODAY), "形式の誤り", "形式の誤り")

        # 0件のときだけ「予定なし」
        with patch(c.urllib.request, "urlopen", lambda *a, **k: FakeRes(EMPTY_ICS.encode())):
            r = c.load_calendar(new_root(), CFG, TODAY)
            check("0件：error なし", r and r["error"] is None and r["events"] == [] and r["stale"] is None, r)
            check("0件：「予定なし」と出る", c.format_events(r["events"], TODAY) == ["  （予定なし）"], c.format_events(r["events"], TODAY))

        # URL でない値
    with patch(c.subprocess, "run", lambda *a, **k: P(0, "not-a-url")):
        is_unreadable(c.load_calendar(new_root(), CFG, TODAY), "URL でない値", "https://")

    # --- 3. キャッシュ：同じ日に取れたものだけ、古いと断って添える ---
    ics = ("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:a\nSUMMARY:会議\nDTSTART:%sT010000Z\nDTEND:%sT020000Z\nEND:VEVENT\nEND:VCALENDAR\n"
           % (TODAY.strftime("%Y%m%d"), TODAY.strftime("%Y%m%d")))
    root = new_root()
    with patch(c.subprocess, "run", lambda *a, **k: P(0, SECRET)):
        with patch(c.urllib.request, "urlopen", lambda *a, **k: FakeRes(ics.encode())):
            ok = c.load_calendar(root, CFG, TODAY)
        check("取れたとき：error なし・キャッシュを書く", ok and ok["error"] is None and (root / "00_タスク管理/data/calendar_cache.json").exists(), ok)
        with patch(c.urllib.request, "urlopen", boom):
            r = c.load_calendar(root, CFG, TODAY)
        check("同じ日のキャッシュ：error と stale と予定", r and r["error"] and r["stale"] and len(r["events"]) >= 1, r)
        text = "\n".join(c.format_events(r["events"], TODAY, r["error"], r["stale"]))
        check("同じ日のキャッシュ：「読めませんでした」＋最新ではない", "読めませんでした" in text and "最新ではありません" in text, text)
        cache = root / "00_タスク管理/data/calendar_cache.json"
        d = json.loads(cache.read_text(encoding="utf-8"))
        d["fetched"] = "2000-01-01 09:00"
        cache.write_text(json.dumps(d), encoding="utf-8")
        with patch(c.urllib.request, "urlopen", boom):
            r = c.load_calendar(root, CFG, TODAY)
        check("前の日のキャッシュは使わない（予定なしに見えるため）", r and r["error"] and r["stale"] is None and r["events"] == [], r)

# --- 4. 設定なし・コネクタ ---
check("calendar の設定なし → None", c.load_calendar(new_root(), {}, TODAY) is None)
check("connector → None", c.load_calendar(new_root(), {"calendar": {"type": "connector"}}, TODAY) is None)
check("load_events も None", c.load_events(new_root(), {}, TODAY) is None)

# --- 5. ICS ファイル ---
is_unreadable(c.load_calendar(new_root(), {"calendar": {"type": "ics", "ics_file": "/nonexistent/x.ics"}}, TODAY), "ICS ファイルが無い", "ICS")

# --- 6. Windows の分かれ道 ---
tmp = Path(tempfile.mkdtemp(prefix="calwin_"))
with patch(c, "_platform", lambda: "win32"), patch(c, "keychain_secret", must_not_call):
    with patch(c, "url_file_path", lambda: tmp / "missing.txt"):
        r = c.load_calendar(new_root(), CFG, TODAY)
        is_unreadable(r, "Windows でファイルが無い", "Windows のつなぎ方は setup を見てください")
        check("Windows：行の全文", "📅 予定を読めませんでした（Windows のつなぎ方は setup を見てください）" in c.format_events([], TODAY, r["error"])[0],
              c.format_events([], TODAY, r["error"]))
    f = tmp / "url.txt"
    # メモ帳の BOM・行末の改行・見えない空白が付いても、URL を取り出せる
    f.write_bytes(b"\xef\xbb\xbf" + SECRET.encode() + "​ \r\n".encode())
    seen = []

    def fake_open(url, timeout=0):
        seen.append(url)
        return FakeRes(EMPTY_ICS.encode())
    with patch(c, "url_file_path", lambda: f), patch(c.urllib.request, "urlopen", fake_open):
        r = c.load_calendar(new_root(), CFG, TODAY)
    check("Windows：ファイルの URL で取る（BOM・改行・見えない文字を除く）", r and r["error"] is None and seen == [SECRET], (r, seen))
    f.write_text("ftp://example.invalid/x", encoding="utf-8")
    with patch(c, "url_file_path", lambda: f):
        is_unreadable(c.load_calendar(new_root(), CFG, TODAY), "Windows で URL でない値", "https://")
    f.write_text("\n", encoding="utf-8")
    with patch(c, "url_file_path", lambda: f):
        is_unreadable(c.load_calendar(new_root(), CFG, TODAY), "Windows で空のファイル", "空")
with patch(c, "_platform", lambda: "linux"), patch(c, "keychain_secret", must_not_call), patch(c, "url_file_path", lambda: tmp / "none.txt"):
    is_unreadable(c.load_calendar(new_root(), CFG, TODAY), "Linux でファイルが無い", "setup")

# --- 7. タイムゾーンを読めない予定 ---
def ev(body):
    return "BEGIN:VCALENDAR\nBEGIN:VEVENT\n" + body.strip().replace("    ", "") + "\nEND:VEVENT\nEND:VCALENDAR\n"


unknown = ev("""
    UID:tz1
    SUMMARY:海外の会議
    DTSTART;TZID=Nowhere/Nothing:20261105T090000
    DTEND;TZID=Nowhere/Nothing:20261105T100000
""")
got = c.events_between(unknown, date(2026, 11, 5), date(2026, 11, 6))
check("TZID 不明：時刻を出さない・time_unknown", len(got) == 1 and got[0]["start"] == "" and got[0]["end"] == "" and got[0].get("time_unknown") is True
      and got[0]["date"] == "2026-11-05" and got[0]["allday"] is False, got)
text = "\n".join(c.format_events(got, date(2026, 11, 5)))
check("TZID 不明：「時刻不明」と警告", "時刻不明 海外の会議" in text and "⚠" in text and "9:00" not in text and "09:00" not in text, text)

# tzdata が無い・ZoneInfo が無い状態（Windows の tzdata 無し／Python 3.8）の Asia/Tokyo も、ずらさず時刻不明
def no_zone(name):
    raise KeyError(name)
tokyo = ev("""
    UID:tz2
    SUMMARY:東京の会議
    DTSTART;TZID=Asia/Tokyo:20261105T090000
    DTEND;TZID=Asia/Tokyo:20261105T100000
""")
with patch(c, "ZoneInfo", no_zone):
    got = c.events_between(tokyo, date(2026, 11, 5), date(2026, 11, 5))
check("tzdata 無し：ずらさず時刻不明", len(got) == 1 and got[0]["start"] == "" and got[0].get("time_unknown"), got)
with patch(c, "ZoneInfo", None):
    got = c.events_between(tokyo, date(2026, 11, 5), date(2026, 11, 5))
check("ZoneInfo 無し（Python 3.8）：ずらさず時刻不明", len(got) == 1 and got[0].get("time_unknown"), got)

# 繰り返しも時刻不明のまま（毎日、3日分）
rec = ev("""
    UID:tz3
    SUMMARY:毎朝
    DTSTART;TZID=Nowhere/Nothing:20261105T090000
    RRULE:FREQ=DAILY;COUNT=3
""")
got = c.events_between(rec, date(2026, 11, 1), date(2026, 11, 30))
check("TZID 不明の繰り返し：3日とも時刻不明", [(e["date"], e.get("time_unknown")) for e in got]
      == [("2026-11-05", True), ("2026-11-06", True), ("2026-11-07", True)], got)

# 影響を受けないもの：ローカル時刻（TZID なし）・UTC（Z）・TZID ありで読めるもの
if hasattr(__import__("time"), "tzset"):
    import time
    os.environ["TZ"] = "Asia/Tokyo"
    time.tzset()
    floating = ev("UID:f1\nSUMMARY:ローカル\nDTSTART:20261105T090000\nDTEND:20261105T100000")
    got = c.events_between(floating, date(2026, 11, 5), date(2026, 11, 5))
    check("TZID なし：ローカル時刻のまま", got and got[0]["start"] == "09:00" and not got[0].get("time_unknown"), got)
    utc = ev("UID:u1\nSUMMARY:UTC\nDTSTART:20261105T000000Z\nDTEND:20261105T010000Z")
    got = c.events_between(utc, date(2026, 11, 5), date(2026, 11, 5))
    check("UTC：日本時間に直る", got and got[0]["start"] == "09:00" and not got[0].get("time_unknown"), got)
    try:
        from zoneinfo import ZoneInfo as _Z
        _Z("Asia/Tokyo")
        got = c.events_between(tokyo, date(2026, 11, 5), date(2026, 11, 5))
        check("TZID が読めるとき：時刻が出る", got and got[0]["start"] == "09:00" and not got[0].get("time_unknown"), got)
    except Exception:
        pass   # tzdata の無い環境では、このテストは飛ばす

# --- 8. update_dashboard.py（起動時のまとめ・朝の計画の材料・Excel）---
SCRIPT = os.path.abspath(os.path.join(HERE, "..", "scripts", "update_dashboard.py"))


def make_owner(calendar_cfg):
    base = os.path.realpath(tempfile.mkdtemp(prefix="caldash_"))
    R = os.path.join(base, "owner")
    os.makedirs(os.path.join(R, "設定"))
    os.makedirs(os.path.join(R, "00_タスク管理", "data"))
    cfg = {"owner": "テスト", "owner_call": "テストさん", "ai_name": "テストAI", "departments": ["総務"], "calendar": calendar_cfg}
    json.dump(cfg, open(os.path.join(R, "設定", "config.json"), "w", encoding="utf-8"), ensure_ascii=False)
    tasks = {"project": {"name": "テストAI", "daily_capacity_default": 8.0, "holidays": []}, "daily_sprints": [], "sprints": [],
             "tasks": [{"id": "T001", "title": "テスト用タスク", "status": "ToDo", "assignee": "dev-a", "type": "開発",
                        "reviewer": "dev-b", "points": 2, "department": "総務", "priority": 1}]}
    json.dump(tasks, open(os.path.join(R, "00_タスク管理", "data", "tasks.json"), "w", encoding="utf-8"), ensure_ascii=False)
    home = os.path.join(base, "home")
    os.makedirs(home)
    return R, home


def run_dash(R, home, args):
    env = {k: v for k, v in os.environ.items() if k not in ("AI_BUNSHIN_HOME", "CLAUDE_PROJECT_DIR")}
    env["HOME"] = home
    env["USERPROFILE"] = home
    env["CLAUDE_PROJECT_DIR"] = R
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, cwd=R, env=env)


R, home = make_owner({"type": "ics", "ics_file": "/nonexistent/calendar.ics"})
r = run_dash(R, home, ["--plan-context"])
check("朝の計画の材料：読めなかった旨", r.returncode == 0 and "予定を読めなかったので、会議の多さは分からない" in r.stdout, r.stdout + r.stderr)
check("朝の計画の材料：「📅 予定を読めませんでした（理由）」", "📅 予定を読めませんでした（ICS ファイルを読めませんでした）" in r.stdout, r.stdout)
check("朝の計画の材料：「（予定なし）」とは出ない", "（予定なし）" not in r.stdout, r.stdout)
r = run_dash(R, home, [])
check("起動時のまとめ（手動実行）：読めなかった旨", r.returncode == 0 and "📅 予定を読めませんでした" in r.stdout and "（予定なし）" not in r.stdout, r.stdout + r.stderr)
r = run_dash(R, home, ["--session"])
ctx_text = ""
try:
    ctx_text = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
except (ValueError, KeyError):
    pass
check("起動時のまとめ（--session）：読めなかった旨", "📅 予定を読めませんでした" in ctx_text and "（予定なし）" not in ctx_text, r.stdout + r.stderr)
try:
    import openpyxl
    ws = openpyxl.load_workbook(os.path.join(R, "00_タスク管理", "タスク管理.xlsx"))
    vals = [str(cell.value) for sh in ws.worksheets for row in sh.iter_rows() for cell in row if cell.value]
    check("Excel：「予定を読めませんでした」が出て、「予定なし」は出ない",
          any("予定を読めませんでした" in v for v in vals) and not any(v.startswith("予定なし") for v in vals), [v for v in vals if "予定" in v])
except ImportError:
    pass

ok_ics = os.path.join(os.path.dirname(R), "empty.ics")
open(ok_ics, "w", encoding="utf-8").write(EMPTY_ICS)
R2, home2 = make_owner({"type": "ics", "ics_file": ok_ics})
r = run_dash(R2, home2, ["--plan-context"])
check("本当に0件：「予定なし」と出る", "（予定なし）" in r.stdout and "読めませんでした" not in r.stdout and "読めなかった" not in r.stdout, r.stdout + r.stderr)

print(f"失敗 {fails} 件")
sys.exit(1 if fails else 0)
