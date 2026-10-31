#!/usr/bin/env python3
"""今日・明日の予定を読む（Google カレンダーなどの iCal 形式の非公開 URL。読むだけ）。

- 本人設定（設定/config.json）の calendar：
    {"type": "ics", "keychain": "ai-bunshin-calendar", "show": "title"}
  URL は合言葉と同じなので config には書かず、Mac のキーチェーン（サービス名 = keychain）に入れる。
  Windows など Mac 以外では、ユーザーのフォルダの直下の ai-bunshin-calendar-url.txt（URL を1行だけ書いたファイル。
  本人のフォルダの外なので、同期や Git に載らない）から読む。つなぎ方は skills/setup/SKILL.md
  試すとき・キーチェーンの無い環境では "ics_file": "<ICS ファイルのパス>" でもよい
- show："title"（件名と時間）／"time"（時間だけ。件名は「予定あり」）
- 取れないとき（オフライン・URL の誤り・キーチェーンに無い・ログイン画面などカレンダーでないもの）は、
  「予定なし」と取り違えないよう、理由つきの error を返す（load_calendar）。URL そのものは理由に入れない。
  直前に取れた予定は 00_タスク管理/data/calendar_cache.json（件名と時間だけ）に残し、同じ日に取れたものだけ
  「読めなかったが、○時点の予定」として添える（日をまたいだ古い予定は使わない）
- タイムゾーン（TZID）を読めない予定は、時刻をずらして出さない。時刻を空にして「時刻不明」の印（time_unknown）を付ける
- 繰り返しの予定（RRULE）：DAILY・WEEKLY・MONTHLY・YEARLY の INTERVAL・BYDAY（「第2火曜」「最終金曜」などの
  序数つきを含む）・BYMONTHDAY（-1＝月末を含む）・UNTIL・COUNT、EXDATE、1回だけ変更した予定（RECURRENCE-ID）。
  繰り返しは予定のタイムゾーンで数えてから自分のタイムゾーンに直す（夏時間も考える）。
  BYSETPOS・BYWEEKNO・BYYEARDAY など、ほかの規則が付いた繰り返しは、間違えないように表示しない
- 終日の何日かにわたる予定（出張・休暇）、日をまたぐ予定は、かかっている日すべてに出す
"""
import calendar as _calendar
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python 3.8 以前
    ZoneInfo = None

WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
UNSUPPORTED = ("BYSETPOS", "BYWEEKNO", "BYYEARDAY", "BYHOUR", "BYMINUTE", "BYSECOND")


class UnknownTZ(tzinfo):
    """タイムゾーン名（TZID）を読めなかった予定の印。時刻の計算には使わず、「時刻不明」として出す。"""
    def utcoffset(self, dt):
        return timedelta(0)

    def dst(self, dt):
        return timedelta(0)

    def tzname(self, dt):
        return "UNKNOWN"


class CalendarError(Exception):
    """予定を読めなかった理由（1行。URL は入れない）。"""


def local_tz():
    return datetime.now().astimezone().tzinfo


def unfold(text):
    return re.sub(r"\r?\n[ \t]", "", text).splitlines()


def unescape(v):
    return v.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def parse_dt(value, params):
    """値を、その予定のタイムゾーンの aware な datetime（終日は date）にする。"""
    value = value.strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        return datetime.strptime(value[:8], "%Y%m%d").date()
    dt = datetime.strptime(value.rstrip("Z")[:15], "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        return dt.replace(tzinfo=timezone.utc)
    tzid = params.get("TZID")
    if tzid:
        try:
            return dt.replace(tzinfo=ZoneInfo(tzid))
        except Exception:   # ZoneInfo が無い（Python 3.8 以前）・tzdata が無い（Windows）・知らない名前
            return dt.replace(tzinfo=UnknownTZ())   # ローカル時刻として扱うと、海外の予定が何時間もずれる
    return dt.replace(tzinfo=local_tz())


def to_local(x):
    return x.astimezone(local_tz()) if isinstance(x, datetime) else x


def parse_events(text):
    events, cur = [], None
    for line in unfold(text):
        if line == "BEGIN:VEVENT":
            cur = {"exdate": []}
        elif line == "END:VEVENT" and cur is not None:
            events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            head, value = line.split(":", 1)
            name, *ps = head.split(";")
            params = dict(p.split("=", 1) for p in ps if "=" in p)
            if name in ("DTSTART", "DTEND", "RECURRENCE-ID"):
                cur[name] = parse_dt(value, params)
            elif name == "EXDATE":
                cur["exdate"] += [parse_dt(v, params) for v in value.split(",")]
            elif name in ("SUMMARY", "RRULE", "UID", "STATUS", "DURATION"):
                cur[name] = unescape(value)
    return events


def duration_of(ev):
    start, end = ev.get("DTSTART"), ev.get("DTEND")
    if end is not None and start is not None and type(end) is type(start):
        return end - start
    m = re.fullmatch(r"P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?", ev.get("DURATION", ""))
    if m and any(m.groups()):
        w, d, h, mi = (int(x or 0) for x in m.groups())
        return timedelta(weeks=w, days=d, hours=h, minutes=mi)
    return timedelta(days=1) if not isinstance(start, datetime) else timedelta(0)


def as_date(x):
    return x.date() if isinstance(x, datetime) else x


def nth_weekdays(year, month, spec):
    """BYDAY の1つ（例 'TU'・'2TU'・'-1FR'）が、その月の何日に当たるか。"""
    m = re.fullmatch(r"([+-]?\d+)?([A-Z]{2})", spec)
    if not m or m.group(2) not in WEEKDAYS:
        return []
    wd = WEEKDAYS[m.group(2)]
    days = [d for d in range(1, _calendar.monthrange(year, month)[1] + 1) if date(year, month, d).weekday() == wd]
    if m.group(1):
        n = int(m.group(1))
        idx = n - 1 if n > 0 else n
        return [days[idx]] if -len(days) <= idx < len(days) else []
    return days


def month_days(year, month, rule, d0):
    """MONTHLY・YEARLY の、その月に当たる日（日付の数字の一覧）。"""
    last = _calendar.monthrange(year, month)[1]
    out = set()
    if "BYMONTHDAY" in rule:
        for x in rule["BYMONTHDAY"].split(","):
            n = int(x)
            day = n if n > 0 else last + n + 1
            if 1 <= day <= last:
                out.add(day)
    if "BYDAY" in rule:
        days = set()
        for spec in rule["BYDAY"].split(","):
            days |= set(nth_weekdays(year, month, spec))
        out = (out & days) if "BYMONTHDAY" in rule else days
    if "BYMONTHDAY" not in rule and "BYDAY" not in rule and d0.day <= last:
        out.add(d0.day)
    return sorted(out)


def occurrence_days(ev, first, last):
    """繰り返しの各回の「開始日（予定のタイムゾーンでの日付）」を、first〜last（少し広め）の範囲で返す。"""
    start = ev["DTSTART"]
    rule = dict(p.split("=", 1) for p in ev.get("RRULE", "").split(";") if "=" in p)
    d0 = as_date(start)
    if not rule:
        return [d0]
    if any(k in rule for k in UNSUPPORTED):
        return []   # 間違えて出すより、出さない
    freq = rule.get("FREQ")
    interval = int(rule.get("INTERVAL", "1"))
    count = int(rule["COUNT"]) if "COUNT" in rule else None
    until = parse_dt(rule["UNTIL"], {}) if "UNTIL" in rule else None
    bydays = [WEEKDAYS[d[-2:]] for d in rule.get("BYDAY", "").split(",") if d[-2:] in WEEKDAYS]
    bymonth = [int(x) for x in rule.get("BYMONTH", "").split(",") if x]
    week0 = d0 - timedelta(days=d0.weekday())   # 週の区切りは月曜（Google の既定 WKST=MO）
    out, n = [], 0
    day = d0
    hard_end = last + timedelta(days=1)
    while day <= hard_end:
        if freq == "DAILY":
            hit = (day - d0).days % interval == 0
        elif freq == "WEEKLY":
            weeks = ((day - timedelta(days=day.weekday())) - week0).days // 7
            hit = weeks % interval == 0 and day.weekday() in (bydays or [d0.weekday()])
        elif freq == "MONTHLY":
            months = (day.year - d0.year) * 12 + day.month - d0.month
            hit = months % interval == 0 and day.day in month_days(day.year, day.month, rule, d0)
        elif freq == "YEARLY":
            months_ok = day.month in (bymonth or [d0.month])
            hit = (day.year - d0.year) % interval == 0 and months_ok and day.day in month_days(day.year, day.month, rule, d0)
        else:
            return [d0]
        if bymonth and freq in ("DAILY", "WEEKLY", "MONTHLY") and day.month not in bymonth:
            hit = False
        if hit:
            occ = datetime.combine(day, start.time(), tzinfo=start.tzinfo) if isinstance(start, datetime) else day
            if until is not None:
                if isinstance(occ, datetime):
                    u = until if isinstance(until, datetime) else datetime.combine(until, datetime.max.time(), tzinfo=occ.tzinfo)
                    if occ > u:
                        break
                elif day > as_date(until):
                    break
            n += 1
            if count is not None and n > count:
                break
            out.append(day)
        day += timedelta(days=1)
    return out


def events_between(text, first, last):
    """first〜last（自分のタイムゾーンの日付）に「かかっている」予定。何日にもわたる予定は日ごとに出す。"""
    evs = parse_events(text)
    overridden = {(e.get("UID"), as_date(to_local(e["RECURRENCE-ID"])) if isinstance(e["RECURRENCE-ID"], datetime)
                   else e["RECURRENCE-ID"]) for e in evs if e.get("RECURRENCE-ID")}
    out = []
    for ev in evs:
        start = ev.get("DTSTART")
        if start is None or ev.get("STATUS") == "CANCELLED":
            continue
        dur = duration_of(ev)
        if ev.get("RECURRENCE-ID"):
            starts = [start]
        else:
            ex = set()
            for x in ev["exdate"]:
                ex.add(x.astimezone(start.tzinfo).replace(second=0, microsecond=0) if isinstance(x, datetime) and isinstance(start, datetime) else as_date(x))
            starts = []
            for day in occurrence_days(ev, first - timedelta(days=40), last):
                occ = datetime.combine(day, start.time(), tzinfo=start.tzinfo) if isinstance(start, datetime) else day
                key = occ.replace(second=0, microsecond=0) if isinstance(occ, datetime) else occ
                if key in ex or (not isinstance(occ, datetime) and occ in ex):
                    continue
                if (ev.get("UID"), as_date(to_local(occ))) in overridden:
                    continue
                starts.append(occ)
        for s in starts:
            if isinstance(s, datetime) and isinstance(s.tzinfo, UnknownTZ):
                # タイムゾーンを読めない：時刻は出さない。日付は書かれた日のまま
                d0 = s.date()
                for i in range(max(dur.days, 1)):
                    d = d0 + timedelta(days=i)
                    if first <= d <= last:
                        out.append({"date": d.isoformat(), "start": "", "end": "", "title": ev.get("SUMMARY", "(件名なし)"),
                                    "allday": False, "time_unknown": True})
            elif isinstance(s, datetime):
                ls, le = to_local(s), to_local(s + dur)
                d, dlast = ls.date(), (le - timedelta(microseconds=1)).date() if le > ls else ls.date()
                while d <= dlast:
                    if first <= d <= last:
                        out.append({"date": d.isoformat(),
                                    "start": ls.strftime("%H:%M") if d == ls.date() else "00:00",
                                    "end": le.strftime("%H:%M") if d == le.date() or le.date() <= d else "24:00",
                                    "title": ev.get("SUMMARY", "(件名なし)"), "allday": False})
                    d += timedelta(days=1)
            else:
                days = max(dur.days, 1)
                for i in range(days):
                    d = s + timedelta(days=i)
                    if first <= d <= last:
                        out.append({"date": d.isoformat(), "start": "", "end": "",
                                    "title": ev.get("SUMMARY", "(件名なし)"), "allday": True})
    return sorted(out, key=lambda e: (e["date"], not e["allday"], e["start"]))


def _platform():
    return sys.platform   # テストで差し替えるための入り口


def _is_windows():
    return _platform().startswith("win")


def url_file_path():
    """Mac 以外で URL を置く場所（ユーザーのフォルダの直下。本人のフォルダの外）。"""
    return Path.home() / "ai-bunshin-calendar-url.txt"


def keychain_secret(service):
    """キーチェーンの値。無い・読めないときは CalendarError（理由に値は入れない）。"""
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        raise CalendarError("キーチェーンを読めませんでした")
    value = r.stdout.strip()
    if r.returncode != 0 or not value:
        raise CalendarError(f"キーチェーン（{service}）に URL が入っていません")
    return value


def file_secret():
    p = url_file_path()
    try:
        # メモ帳が付ける BOM と、行末・見えない空白（URL の途中に空白は無い）を取り除く
        value = re.sub(r"[\s\u200b-\u200f\ufeff]+", "", p.read_text(encoding="utf-8-sig"))
    except OSError:
        if _is_windows():
            raise CalendarError("Windows のつなぎ方は setup を見てください")
        raise CalendarError("このパソコンのつなぎ方は setup を見てください")
    if not value:
        raise CalendarError("URL を書くファイルが空です")
    return value


def fetch_ics(cfg):
    """ICS の本文。読めなければ CalendarError（理由は1行）。"""
    if cfg.get("ics_file"):
        p = Path(cfg["ics_file"]).expanduser()
        try:
            return p.read_text(encoding="utf-8")
        except OSError:
            raise CalendarError("ICS ファイルを読めませんでした")
    url = keychain_secret(cfg.get("keychain", "ai-bunshin-calendar")) if _platform() == "darwin" else file_secret()
    if not url.startswith("https://"):
        raise CalendarError("保存されている値が https:// で始まる URL ではありません（入れ直してください）")
    try:
        with urllib.request.urlopen(url, timeout=10) as res:  # 読むだけ（GET）
            return res.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:   # URLError より先に。str(e) は使わない（URL が入ることがある）
        raise CalendarError(f"カレンダーのサーバーが {e.code} を返しました（URL が古い・違う可能性）")
    except Exception as e:
        if isinstance(e, (OSError, TimeoutError)):
            raise CalendarError("ネットワークにつながりませんでした")
        raise CalendarError(f"カレンダーを取得できませんでした（{type(e).__name__}）")


def load_calendar(root, cfg, today, days=2):
    """今日から days 日分の予定を読む。config に calendar（ics）が無ければ None。

    返すもの：{"events": [...], "error": 読めなかった理由（1行）か None, "stale": 古い予定を使うときの取得時刻か None}
    error があって stale が None なら、予定は不明（0件ではない）。"""
    cal = (cfg or {}).get("calendar") or {}
    if cal.get("type") != "ics":
        return None
    cache = root / "00_タスク管理" / "data" / "calendar_cache.json"
    last = today + timedelta(days=days - 1)
    try:
        text = fetch_ics(cal)
        if "BEGIN:VCALENDAR" not in text:   # ログイン画面などカレンダーでないものは使わない（キャッシュも上書きしない）
            raise CalendarError("カレンダーの形式ではありませんでした（ログイン画面などが返った可能性）")
        try:
            evs = events_between(text, today, last)
        except Exception:
            raise CalendarError("カレンダーの中身を読み取れませんでした（形式の誤り）")
    except CalendarError as e:
        error = str(e)
    else:
        if cal.get("show") == "time":
            for e in evs:
                e["title"] = "予定あり"
        if cache.parent.exists():
            cache.write_text(json.dumps({"fetched": datetime.now().strftime("%Y-%m-%d %H:%M"), "from": today.isoformat(),
                                         "events": evs}, ensure_ascii=False, indent=1), encoding="utf-8")
        return {"events": evs, "error": None, "stale": None}
    # 読めなかった：同じ日に取れた予定だけ、古いと断って添える（前の日のものは予定なしに見えてしまうので使わない）
    if cache.exists():
        try:
            c = json.loads(cache.read_text(encoding="utf-8"))
            if str(c.get("fetched", ""))[:10] == today.isoformat():
                return {"events": [e for e in c.get("events", []) if today.isoformat() <= e["date"] <= last.isoformat()],
                        "error": error, "stale": c["fetched"]}
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return {"events": [], "error": error, "stale": None}


def load_events(root, cfg, today, days=2):
    """予定の一覧だけ（読めなかったときの理由は load_calendar）。config に calendar が無ければ None。"""
    r = load_calendar(root, cfg, today, days)
    return None if r is None else r["events"]


def error_line(error, stale=None):
    return (f"📅 予定を読めませんでした（{error}）"
            + (f"。{stale} に取れた予定を出しています（最新ではありません）" if stale else "。「予定なし」ではありません"))


def format_events(evs, day, error=None, stale=None):
    if error and not stale:
        return [f"  {error_line(error)}"]
    todays = [e for e in evs if e["date"] == day.isoformat()]
    lines = [f"  {error_line(error, stale)}"] if error else []
    if not todays:
        return lines + ["  （予定なし）"]
    for e in todays:
        when = "時刻不明" if e.get("time_unknown") else "終日" if e["allday"] else e["start"] + "〜" + e["end"]
        lines.append(f"  - {when} {e['title']}")
    if any(e.get("time_unknown") for e in todays):
        lines.append("  ⚠ 時刻不明の予定があります（タイムゾーンを読めませんでした。時刻をずらして出さないよう、時間を空にしています）")
    return lines


if __name__ == "__main__":
    # 試し方：python3 calendar_today.py <ICS ファイル> [YYYY-MM-DD]
    text = Path(sys.argv[1]).read_text(encoding="utf-8")
    d = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date.today()
    for e in events_between(text, d, d + timedelta(days=1)):
        print(e)
