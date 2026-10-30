#!/usr/bin/env python3
"""今日・明日の予定を読む（Google カレンダーなどの iCal 形式の非公開 URL。読むだけ）。

- 本人設定（設定/config.json）の calendar：
    {"type": "ics", "keychain": "ai-bunshin-calendar", "show": "title"}
  URL は合言葉と同じなので config には書かず、Mac のキーチェーン（サービス名 = keychain）に入れる。
  試すとき・キーチェーンの無い環境では "ics_file": "<ICS ファイルのパス>" でもよい
- show："title"（件名と時間）／"time"（時間だけ。件名は「予定あり」）
- 取れないとき（未設定・オフライン・URL の誤り・ログイン画面などカレンダーでないもの）は静かに空を返す。
  直前に取れた予定は 00_タスク管理/data/calendar_cache.json（件名と時間だけ）に残し、同じ日なら使う
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
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python 3.8 以前
    ZoneInfo = None

WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
UNSUPPORTED = ("BYSETPOS", "BYWEEKNO", "BYYEARDAY", "BYHOUR", "BYMINUTE", "BYSECOND")


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
    if tzid and ZoneInfo:
        try:
            return dt.replace(tzinfo=ZoneInfo(tzid))
        except Exception:
            pass
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
            if isinstance(s, datetime):
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


def keychain_secret(service):
    if sys.platform != "darwin":
        return None
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def fetch_ics(cfg):
    if cfg.get("ics_file"):
        p = Path(cfg["ics_file"]).expanduser()
        return p.read_text(encoding="utf-8") if p.exists() else None
    url = keychain_secret(cfg.get("keychain", "ai-bunshin-calendar"))
    if not url or not url.startswith("https://"):
        return None
    try:
        with urllib.request.urlopen(url, timeout=10) as res:  # 読むだけ（GET）
            return res.read().decode("utf-8", "replace")
    except Exception:
        return None


def load_events(root, cfg, today, days=2):
    """今日から days 日分の予定。config に calendar が無ければ None。"""
    cal = (cfg or {}).get("calendar") or {}
    if cal.get("type") != "ics":
        return None
    cache = root / "00_タスク管理" / "data" / "calendar_cache.json"
    last = today + timedelta(days=days - 1)
    text = fetch_ics(cal)
    if text and "BEGIN:VCALENDAR" in text:   # ログイン画面などカレンダーでないものは使わない（キャッシュも上書きしない）
        try:
            evs = events_between(text, today, last)
        except Exception:
            evs = None
        if evs is not None:
            if cal.get("show") == "time":
                for e in evs:
                    e["title"] = "予定あり"
            if cache.parent.exists():
                cache.write_text(json.dumps({"fetched": datetime.now().strftime("%Y-%m-%d %H:%M"), "from": today.isoformat(),
                                             "events": evs}, ensure_ascii=False, indent=1), encoding="utf-8")
            return evs
    if cache.exists():
        try:
            c = json.loads(cache.read_text(encoding="utf-8"))
            return [e for e in c.get("events", []) if today.isoformat() <= e["date"] <= last.isoformat()]
        except (OSError, ValueError):
            return []
    return []


def format_events(evs, day):
    todays = [e for e in evs if e["date"] == day.isoformat()]
    if not todays:
        return ["  （予定なし）"]
    return [f"  - {'終日' if e['allday'] else e['start'] + '〜' + e['end']} {e['title']}" for e in todays]


if __name__ == "__main__":
    # 試し方：python3 calendar_today.py <ICS ファイル> [YYYY-MM-DD]
    text = Path(sys.argv[1]).read_text(encoding="utf-8")
    d = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date.today()
    for e in events_between(text, d, d + timedelta(days=1)):
        print(e)
