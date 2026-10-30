"""予定の読み取り（calendar_today.py）のテスト。実行：python3 tests/test_calendar.py（失敗があれば終了コード1）"""
import os
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
os.environ["TZ"] = "Asia/Tokyo"
import time  # noqa: E402
time.tzset()
import calendar_today as c  # noqa: E402

text = open(os.path.join(HERE, "sample_calendar.ics"), encoding="utf-8").read()
evs = c.events_between(text, date(2026, 10, 30), date(2026, 10, 31))
got = [(e["date"], e["start"], e["title"]) for e in evs]
want = [("2026-10-30", "", "テックブログ公開日"), ("2026-10-30", "09:30", "朝会（時間変更）"), ("2026-10-30", "10:00", "部長会"),
        ("2026-10-30", "14:00", "1on1（UTCで登録）"), ("2026-10-30", "17:00", "週次ふりかえり"), ("2026-10-31", "09:00", "朝会")]
fail = 0
if got != want:
    fail += 1
    print("10/30〜31 が違う:", got)
if c.events_between(text, date(2026, 10, 23), date(2026, 10, 23)):
    fail += 1
    print("EXDATE の日（10/23）に予定が出た")
if any(e["title"] == "朝会" for e in c.events_between(text, date(2026, 11, 5), date(2026, 11, 5))):
    fail += 1
    print("COUNT=10 を超えて朝会が出た")
if c.load_events(__import__("pathlib").Path("/nonexistent"), {}, date.today()) is not None:
    fail += 1
    print("calendar の設定が無いのに予定を返した")
def ev(body):
    return "BEGIN:VCALENDAR\nBEGIN:VEVENT\n" + body.strip().replace("    ", "") + "\nEND:VEVENT\nEND:VCALENDAR\n"


def check(name, text, first, last, want):
    global fail
    got = [(e["date"], e["start"], e["end"]) for e in c.events_between(text, first, last)]
    if got != want:
        fail += 1
        print(name, "が違う:", got)


# 毎月 第2火曜（2026-11-10、12-08）
check("第2火曜", ev("""
    UID:m1
    SUMMARY:月例
    DTSTART;TZID=Asia/Tokyo:20261013T100000
    DTEND;TZID=Asia/Tokyo:20261013T110000
    RRULE:FREQ=MONTHLY;BYDAY=2TU
"""), date(2026, 11, 1), date(2026, 12, 31), [("2026-11-10", "10:00", "11:00"), ("2026-12-08", "10:00", "11:00")])
# 毎月 最終金曜
check("最終金曜", ev("""
    UID:m2
    DTSTART;TZID=Asia/Tokyo:20261030T160000
    DTEND;TZID=Asia/Tokyo:20261030T170000
    RRULE:FREQ=MONTHLY;BYDAY=-1FR
"""), date(2026, 11, 1), date(2026, 11, 30), [("2026-11-27", "16:00", "17:00")])
# 毎月 月末（BYMONTHDAY=-1）
check("月末", ev("""
    UID:m3
    DTSTART;VALUE=DATE:20261031
    RRULE:FREQ=MONTHLY;BYMONTHDAY=-1
"""), date(2026, 11, 1), date(2026, 12, 31), [("2026-11-30", "", ""), ("2026-12-31", "", "")])
# 隔週 月・水（10/26 の週から。11/2 の週は休み、11/9 の週）
check("隔週", ev("""
    UID:w1
    DTSTART;TZID=Asia/Tokyo:20261028T090000
    DTEND;TZID=Asia/Tokyo:20261028T093000
    RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE
"""), date(2026, 10, 28), date(2026, 11, 13), [("2026-10-28", "09:00", "09:30"), ("2026-11-09", "09:00", "09:30"), ("2026-11-11", "09:00", "09:30")])
# 何日かにわたる終日（出張 11/4〜11/6）
check("出張", ev("""
    UID:a1
    DTSTART;VALUE=DATE:20261104
    DTEND;VALUE=DATE:20261107
"""), date(2026, 11, 5), date(2026, 11, 7), [("2026-11-05", "", ""), ("2026-11-06", "", "")])
# 日をまたぐ予定（22:00〜翌 2:00）
check("夜間", ev("""
    UID:n1
    DTSTART;TZID=Asia/Tokyo:20261105T220000
    DTEND;TZID=Asia/Tokyo:20261106T020000
"""), date(2026, 11, 5), date(2026, 11, 6), [("2026-11-05", "22:00", "24:00"), ("2026-11-06", "00:00", "02:00")])
# 夏時間：ニューヨークの毎週月曜 9:00（11/1 に夏時間が終わる → 日本では 22:00 → 23:00）
check("夏時間", ev("""
    UID:d1
    DTSTART;TZID=America/New_York:20261026T090000
    DTEND;TZID=America/New_York:20261026T100000
    RRULE:FREQ=WEEKLY
"""), date(2026, 10, 26), date(2026, 11, 2), [("2026-10-26", "22:00", "23:00"), ("2026-11-02", "23:00", "24:00")])
# UNTIL に時刻（10/29 08:59 まで → 10/29 9:00 は出ない）
check("UNTIL", ev("""
    UID:u1
    DTSTART;TZID=Asia/Tokyo:20261027T090000
    DTEND;TZID=Asia/Tokyo:20261027T100000
    RRULE:FREQ=DAILY;UNTIL=20261028T235900Z
"""), date(2026, 10, 27), date(2026, 10, 31), [("2026-10-27", "09:00", "10:00"), ("2026-10-28", "09:00", "10:00")])
# 対応していない規則（BYSETPOS）は出さない
check("BYSETPOS", ev("""
    UID:x1
    DTSTART;TZID=Asia/Tokyo:20261030T090000
    RRULE:FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1
"""), date(2026, 11, 1), date(2026, 11, 30), [])
# 件名の \; を戻す
t = c.events_between(ev("""
    UID:s1
    SUMMARY:A\\;B
    DTSTART;TZID=Asia/Tokyo:20261105T090000
"""), date(2026, 11, 5), date(2026, 11, 5))
if not t or t[0]["title"] != "A;B":
    fail += 1
    print("\\; が戻らない:", t)

print(f"失敗 {fail} 件")
sys.exit(1 if fail else 0)
