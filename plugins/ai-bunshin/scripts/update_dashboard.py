#!/usr/bin/env python3
"""tasks.json から タスク管理.xlsx と タスクボード.md を生成し、完了予定日を再計算する。

使い方:
  python3 scripts/update_dashboard.py            # 生成してサマリーを表示
  python3 scripts/update_dashboard.py --hook     # Claude Code の hook から呼ぶ（stdin の JSON を判定）
  python3 scripts/update_dashboard.py --session  # SessionStart hook 用
  python3 scripts/update_dashboard.py --today 2026-11-05  # 日付を指定して試算
  python3 scripts/update_dashboard.py --plan-context     # 9時のプランニングの材料（1行目 OPEN/SKIP）
  python3 scripts/update_dashboard.py --review-context   # 17時の振り返り会議の材料（1行目 OPEN/SKIP）
"""
import argparse
import json
import math
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

def find_root():
    """本人のフォルダ（00_タスク管理/data/tasks.json がある場所）。hook は CLAUDE_PROJECT_DIR、手動はカレントから上へ探す。"""
    if os.environ.get("AI_BUNSHIN_HOME"):
        # 自動実行で指定されたときは、そのフォルダだけを見る（別の人のフォルダを誤って更新しない）
        d = Path(os.environ["AI_BUNSHIN_HOME"]).resolve()
        return d if (d / "00_タスク管理" / "data" / "tasks.json").exists() else None
    cands = [os.environ.get("CLAUDE_PROJECT_DIR"), os.getcwd()]
    for c in cands:
        if not c:
            continue
        d = Path(c).resolve()
        for x in [d, *d.parents]:
            if (x / "00_タスク管理" / "data" / "tasks.json").exists():
                return x
    return None


ROOT = find_root() or Path(os.getcwd()).resolve()
CONFIG_JSON = ROOT / "設定" / "config.json"
_cfg = json.loads(CONFIG_JSON.read_text(encoding="utf-8")) if CONFIG_JSON.exists() else {}
OWNER = _cfg.get("owner", "本人")                 # tasks.json の assignee に入る本人の名前
OWNER_CALL = _cfg.get("owner_call", OWNER + "さん")  # 文章での呼び方
AI_NAME = _cfg.get("ai_name", "AI")
DEPARTMENTS = _cfg.get("departments", []) + ["共通"]
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
RULES_MD = PLUGIN_ROOT / "rules" / "commander.md"   # 指揮官ルール（Windows の展開で壊れないよう、プラグインの中のファイル名は英数字）
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import calendar_today  # 予定の読み取り（読むだけ）
except Exception:  # 予定が読めなくても、タスク管理は止めない
    calendar_today = None
RULES_COPY = ROOT / ".claude" / "rules" / "ai-bunshin-common.md"   # .claude/rules/ は自動で読み込まれる。起動のたびにプラグインから写す


def sync_rules():
    """共通の指揮官ルールを本人のフォルダの .claude/rules/ に写す（hook の出力は長いと切れるため）。
    中身が変わったら True。"""
    if not RULES_MD.exists():
        return False
    RULES_COPY.parent.mkdir(parents=True, exist_ok=True)
    head = (f"<!-- 自動コピー：{RULES_MD}（ai-bunshin プラグイン）。直接編集しない。"
            "起動のたびに上書きされる -->\n\n")
    text = head + RULES_MD.read_text(encoding="utf-8")
    if RULES_COPY.exists() and RULES_COPY.read_text(encoding="utf-8") == text:
        return False
    RULES_COPY.write_text(text, encoding="utf-8")
    return True
TASKS_JSON = ROOT / "00_タスク管理" / "data" / "tasks.json"
XLSX = ROOT / "00_タスク管理" / "タスク管理.xlsx"
BOARD_MD = ROOT / "00_タスク管理" / "タスクボード.md"
REQUEST_MD = ROOT / "00_タスク管理" / f"{OWNER_CALL}へのお願い.md"
SNAPSHOT_JSON = ROOT / "00_タスク管理" / "data" / ".snapshot.json"
HISTORY_JSONL = ROOT / "00_タスク管理" / "data" / "history.jsonl"
KAIZEN_MD = ROOT / "04_ナレッジ" / "改善ログ.md"
SPRINT_DIR = ROOT / "01_スプリント"
HISTORY_FIELDS = ["title", "status", "progress", "pdca", "due", "assignee", "done_date", "points", "reestimate"]
LOCK_FILE = ROOT / "scripts" / "auto" / ".lock"
EXTRA_FROM_DAY = 4   # 追加でタスクを取ってよいのは、計画のある日が4日目以降
EXTRA_POINTS = 4     # 追加で取ってよい量：約束＋4pt まで
EXTRA_CUTOFF = "16:30"  # この時刻を過ぎたら新しいタスクは取らない
VELOCITY_DAYS = 3  # ベロシティ＝直近3営業日の日次スプリントの完了ptの平均（昨日の天気）

STATUSES = ["Backlog", "ToDo", "作業中", "レビュー", "完了"]
KINDS = ["判断", "申請", "設定", "確認", "送付", "提供"]   # AI から本人へのお願いの種類
OWN_KIND = "自分"   # 本人が自分でやる仕事（お願いではない。期日・手順は任意）
KIND_ICON = {"判断": "🔴", "申請": "📝", "設定": "🔧", "確認": "✅", "送付": "📤", "提供": "🙋", "その他": "・"}

# 振り分け：仕事の種類（type）ごとの、作る人（assignee）と確かめる人（reviewer）の組み合わせ
MEMBER_LABEL = {"buka-a": "部下A", "buka-b": "部下B", "dev-a": "部下C", "dev-b": "部下D", "design": "部下E",
                "analyst": "部下F", "trainer": "部下G"}
TEAM_OFF = set((_cfg.get("team") or {}).get("off", []))
TEAM_MAX = int((_cfg.get("team") or {}).get("max", 7))
ASSIGNMENT = {
    "資料": ({"buka-a", "指揮官", "design"}, {"buka-b"}),
    "調査・分析・設計": ({"指揮官"}, {"buka-b", "dev-b"}),
    "開発": ({"dev-a", "指揮官", "design"}, {"dev-b"}),
    "分析": ({"analyst", "指揮官"}, {"buka-b"}),
    "研修": ({"trainer", "buka-a", "指揮官", "design"}, {"buka-b"}),
}

FLAG_DONE = "✅ 完了"
FLAG_OVERDUE = "🔴 期限超過"
FLAG_LATE = "⚠ 遅延見込み"
FLAG_OK = "🟢 順調"
FLAG_NO_DUE = "― 納期なし"

FONT = "Meiryo UI"
STATUS_FILL = {
    "Backlog": "EDEDED",
    "ToDo": "DDEBF7",
    "作業中": "FFF2CC",
    "レビュー": "E4DFEC",
    "完了": "E2EFDA",
}
FLAG_FILL = {FLAG_OVERDUE: "F8CBAD", FLAG_LATE: "FFE699", FLAG_OK: "E2EFDA", FLAG_DONE: "E2EFDA"}
HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(name=FONT, bold=True, color="FFFFFF")
BODY_FONT = Font(name=FONT, size=10)
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


# ---------- 日付ユーティリティ ----------

def parse_date(s):
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()


def fmt(d):
    return d.strftime("%Y-%m-%d") if d else ""


def fmt_jp(d):
    if not d:
        return "―"
    return f"{d.month}/{d.day}({'月火水木金土日'[d.weekday()]})"


class Calendar:
    def __init__(self, holidays):
        self.holidays = {parse_date(h) for h in holidays}

    def is_workday(self, d):
        return d.weekday() < 5 and d not in self.holidays

    def add_workdays(self, start, n):
        """start を含めて n 営業日目の日付（n<=0 なら start 以降の最初の営業日）。"""
        d = start
        while not self.is_workday(d):
            d += timedelta(days=1)
        remaining = max(n, 1) - 1
        while remaining > 0:
            d += timedelta(days=1)
            if self.is_workday(d):
                remaining -= 1
        return d

    def workdays_between(self, start, end):
        """start〜end（両端含む）の営業日数。"""
        if end < start:
            return 0
        return sum(1 for i in range((end - start).days + 1) if self.is_workday(start + timedelta(days=i)))


# ---------- 計算 ----------

def remaining_points(t):
    if t["status"] == "完了":
        return 0.0
    progress = t.get("progress") or 0
    return float(t.get("points") or 0) * (1 - progress / 100)


def days_left(t, today):
    due = parse_date(t.get("due"))
    if not due:
        return "期日未設定"
    n = (due - today).days
    return f"{-n}日超過" if n < 0 else ("今日まで" if n == 0 else f"あと{n}日")


def owner_requests(tasks, include_done=False):
    """AI から本人へのお願い（assignee=本人、kind が「自分」以外）を 種類→優先順位 で並べる。"""
    reqs = [t for t in tasks if t.get("assignee") == OWNER and t.get("kind") != OWN_KIND
            and (include_done or t["status"] != "完了")]
    order = {k: i for i, k in enumerate(KINDS)}
    return sorted(reqs, key=lambda t: (order.get(t.get("kind"), len(KINDS)), t.get("_rank") or 999))


def own_tasks(tasks, include_done=False):
    """本人が自分でやる仕事（kind: 自分）。期日の近い順（期日なしは後ろ）→ 優先順位。"""
    own = [t for t in tasks if t.get("assignee") == OWNER and t.get("kind") == OWN_KIND
           and (include_done or t["status"] != "完了")]
    return sorted(own, key=lambda t: (parse_date(t.get("due")) or date.max, t.get("_rank") or 999))


def today_own_picks(tasks, today, limit=3):
    """今日やるといい自分の仕事：期限切れ → 今日まで → 期日が近い → 作業中、の順に最大 limit 件。"""
    own = own_tasks(tasks)

    def key(t):
        due = parse_date(t.get("due"))
        return (0 if due and due < today else 1 if due == today else 2 if due else 3,
                due or date.max, 0 if t["status"] == "作業中" else 1, t.get("_rank") or 999)
    return sorted(own, key=key)[:limit]


def day_done_points(tasks, d):
    """その日に完了した AI のタスク（本人のタスクを除く）のポイント合計。"""
    return sum(float(t.get("points") or 0) for t in tasks
               if t["status"] == "完了" and t.get("assignee") != OWNER and parse_date(t.get("done_date")) == d)


def calc_velocity(data, tasks, today, cal):
    """直近3営業日分の日次スプリントの完了ptの平均。記録が3日分たまるまでは初期値。"""
    cfg = data.get("project", {})
    default = float(cfg.get("daily_capacity_default", cfg.get("default_velocity", 2.0)))
    past = sorted(parse_date(ds["date"]) for ds in data.get("daily_sprints", [])
                  if parse_date(ds["date"]) < today and cal.is_workday(parse_date(ds["date"])))
    if len(past) < VELOCITY_DAYS:
        return default, "初期値"
    recent = past[-VELOCITY_DAYS:]
    v = sum(day_done_points(tasks, d) for d in recent) / VELOCITY_DAYS
    return max(v, 0.5), f"直近{VELOCITY_DAYS}営業日の実績"


def daily_rows(data, tasks):
    """日次スプリントの実績（日付順）。約束・完了・達成率・3日平均。"""
    pts = {t["id"]: float(t.get("points") or 0) for t in tasks}
    rows = []
    for ds in sorted(data.get("daily_sprints", []), key=lambda x: x["date"]):
        d = parse_date(ds["date"])
        committed = sum(pts.get(i, 0) for i in ds.get("planned", []))
        done_planned = sum(pts.get(t["id"], 0) for t in tasks if t["id"] in ds.get("planned", [])
                           and t["status"] == "完了" and parse_date(t.get("done_date")) == d)
        extra_ids = ds.get("added", []) + ds.get("pulled", [])
        done_extra = sum(pts.get(t["id"], 0) for t in tasks if t["id"] in extra_ids
                         and t["status"] == "完了" and parse_date(t.get("done_date")) == d)
        done = day_done_points(tasks, d)
        rows.append(dict(ds=ds, date=d, capacity=ds.get("capacity"), committed=committed,
                         done_planned=done_planned, done_extra=done_extra, done=done,
                         rate=(done_planned / committed if committed else None)))
    for i, r in enumerate(rows):
        window = rows[max(0, i - VELOCITY_DAYS + 1):i + 1]
        r["avg"] = sum(w["done"] for w in window) / len(window)
    return rows


def today_sprint(data, today):
    return next((ds for ds in data.get("daily_sprints", []) if ds["date"] == fmt(today)), None)


def forecast(tasks, today, velocity, cal, today_planned=None):
    """優先度順に残ポイントを積み上げ、各タスクの完了予定日と状態フラグを付ける。

    today_planned: 今日の計画が作成済みなら、その計画のタスクIDの集合。計画のタスクは今日の完了予定、
    それ以外は翌営業日から積み上げる（計画の後に登録したものは翌日の計画に入るため）。"""
    open_tasks = sorted(
        [t for t in tasks if t["status"] != "完了"],
        key=lambda t: (t.get("priority") or 999, parse_date(t.get("due")) or date.max, t["id"]),
    )
    by_id = {t["id"]: t for t in tasks}
    for t in tasks:
        if t["status"] == "完了":
            t["_forecast"] = parse_date(t.get("done_date"))
    cum = 0.0
    start = today
    if today_planned is not None:
        start = cal.add_workdays(today + timedelta(days=1), 1)
    for rank, t in enumerate(open_tasks, start=1):
        t["_rank"] = rank
        if t.get("assignee") == OWNER:
            # 本人の作業は AI のベロシティに含めない。期日（AIが設定）を完了予定とする
            t["_forecast"] = parse_date(t.get("due")) or today
            continue
        if today_planned is not None and t["id"] in today_planned:
            t["_forecast"] = today
            continue
        cum += remaining_points(t)
        t["_forecast"] = cal.add_workdays(start, math.ceil(cum / velocity) if cum > 0 else 1)
        # depends_on のタスクが終わってから着手する（前提タスクの完了予定の翌営業日から数える）
        deps = [by_id[d]["_forecast"] for d in t.get("depends_on", []) if d in by_id and by_id[d].get("_forecast")]
        if deps:
            own = math.ceil(remaining_points(t) / velocity) or 1
            t["_forecast"] = max(t["_forecast"], cal.add_workdays(max(deps) + timedelta(days=1), own))
    for t in tasks:
        due = parse_date(t.get("due"))
        if t["status"] == "完了":
            t["_rank"] = None
            t["_forecast"] = parse_date(t.get("done_date"))
            t["_flag"] = FLAG_DONE
        elif due and due < today:
            t["_flag"] = FLAG_OVERDUE
        elif due and t["_forecast"] > due:
            t["_flag"] = FLAG_LATE
        elif due:
            t["_flag"] = FLAG_OK
        else:
            t["_flag"] = FLAG_NO_DUE
    project_end = max((t["_forecast"] for t in open_tasks), default=None)
    return open_tasks, project_end


def current_sprint(data, today):
    sprints = data.get("sprints", [])
    active = [s for s in sprints if s.get("status") == "進行中"]
    if active:
        return active[-1]
    for s in sprints:
        if parse_date(s["start"]) <= today <= parse_date(s["end"]):
            return s
    return sprints[-1] if sprints else None


def burndown(sprint, tasks, today, cal):
    """スプリント期間の日別 理想線 / 実績残ポイント。"""
    start, end = parse_date(sprint["start"]), parse_date(sprint["end"])
    st = [t for t in tasks if t.get("sprint") == sprint["id"]]
    total = sum(float(t.get("points") or 0) for t in st)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    workdays = [d for d in days if cal.is_workday(d)] or days
    n = len(workdays)
    rows = []
    for i, d in enumerate(workdays):
        ideal = total * (1 - i / (n - 1)) if n > 1 else 0
        if d <= today:
            done = sum(float(t.get("points") or 0) for t in st
                       if t["status"] == "完了" and parse_date(t.get("done_date")) and parse_date(t["done_date"]) <= d)
            actual = total - done
        else:
            actual = None
        rows.append((fmt_jp(d), round(ideal, 1), actual))
    return total, rows


# ---------- Excel ----------

def style_header(ws, row, ncols):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER


def style_body(ws, min_row, max_row, ncols):
    for r in range(min_row, max_row + 1):
        for c in range(1, ncols + 1):
            cell = ws.cell(row=r, column=c)
            cell.font = BODY_FONT
            cell.border = BORDER
            cell.alignment = Alignment(vertical="center", wrap_text=cell.alignment.wrap_text)


def set_widths(ws, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def section_title(ws, row, text):
    ws.cell(row=row, column=1, value=text).font = Font(name=FONT, size=12, bold=True, color="1F4E78")


def build_dashboard(wb, ctx):
    ws = wb.active
    ws.title = "ダッシュボード"
    ws.sheet_view.showGridLines = False
    set_widths(ws, [36, 14, 14, 14, 14, 14, 40, 14])
    today, sprint, tasks = ctx["today"], ctx["sprint"], ctx["tasks"]

    ws["A1"] = f"{AI_NAME} タスク管理ダッシュボード"
    ws["A1"].font = Font(name=FONT, size=18, bold=True, color="1F4E78")
    ws["A2"] = f"最終更新：{ctx['now']}　（このファイルは自動生成です。編集しないでください）"
    ws["A2"].font = Font(name=FONT, size=9, color="808080")

    # KPI
    open_n = sum(1 for t in tasks if t["status"] != "完了")
    overdue = sum(1 for t in tasks if t["_flag"] == FLAG_OVERDUE)
    late = sum(1 for t in tasks if t["_flag"] == FLAG_LATE)
    sp_tasks = [t for t in tasks if sprint and t.get("sprint") == sprint["id"]]
    sp_total = sum(float(t.get("points") or 0) for t in sp_tasks)
    sp_done = sum(float(t.get("points") or 0) for t in sp_tasks if t["status"] == "完了")
    sp_rate = sp_done / sp_total if sp_total else 0
    tds = today_sprint(ctx["data"], today)
    tdr = next((r for r in daily_rows(ctx["data"], tasks) if tds and r["ds"] is tds), None)
    kpis = [
        ("全体の完了予定日", fmt_jp(ctx["project_end"]) if ctx["project_end"] else "残タスクなし"),
        (f"📌 {OWNER_CALL}へのお願い", f"{len(owner_requests(tasks))} 件"),
        ("今日の計画（完了/約束）", f"{tdr['done_planned']:g} / {tdr['committed']:g} pt" if tdr else "未計画"),
        ("残タスク", f"{open_n} 件"),
        ("🔴 期限超過", f"{overdue} 件"),
        ("⚠ 遅延見込み", f"{late} 件"),
        ("スプリント進捗", f"{sp_rate:.0%}"),
        ("ベロシティ", f"{ctx['velocity']:.1f} pt/日"),
    ]
    for i, (label, value) in enumerate(kpis):
        col = i + 1
        lc = ws.cell(row=4, column=col, value=label)
        vc = ws.cell(row=5, column=col, value=value)
        lc.font = Font(name=FONT, size=9, color="595959")
        vc.font = Font(name=FONT, size=16, bold=True,
                       color="C00000" if ("超過" in label and overdue) or ("遅延" in label and late)
                       else ("C55A11" if "お願い" in label and owner_requests(tasks) else "1F4E78"))
        for c in (lc, vc):
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.fill = PatternFill("solid", fgColor="F2F2F2")
            c.border = BORDER
    ws.row_dimensions[5].height = 32
    ws.cell(row=6, column=8, value=f"（{ctx['velocity_src']}）").font = Font(name=FONT, size=8, color="808080")

    # スプリント
    row = 8
    section_title(ws, row, "現在のスプリント")
    if sprint:
        info = [
            ("スプリント", sprint["id"]),
            ("ゴール", sprint.get("goal", "")),
            ("期間", f"{fmt_jp(parse_date(sprint['start']))} 〜 {fmt_jp(parse_date(sprint['end']))}"),
            ("進捗", f"{sp_done:g} / {sp_total:g} pt（{sp_rate:.0%}）"),
            ("PDCAフェーズ", sprint.get("pdca", "")),
        ]
        for i, (k, v) in enumerate(info, start=row + 1):
            ws.cell(row=i, column=1, value=k).font = Font(name=FONT, bold=True, size=10)
            ws.cell(row=i, column=2, value=v).font = BODY_FONT
            ws.merge_cells(start_row=i, start_column=2, end_row=i, end_column=7)
        row += len(info) + 2
    else:
        ws.cell(row=row + 1, column=1, value="スプリントはまだありません").font = BODY_FONT
        row += 3

    # 要注意タスク
    section_title(ws, row, "要注意タスク（期限超過・遅延見込み）")
    row += 1
    headers = ["タスク", "部署", "担当", "納期", "完了予定", "状態", "メモ"]
    for c, h in enumerate(headers, start=1):
        ws.cell(row=row, column=c, value=h)
    style_header(ws, row, len(headers))
    alerts = [t for t in tasks if t["_flag"] in (FLAG_OVERDUE, FLAG_LATE)]
    alerts.sort(key=lambda t: (t["_flag"] != FLAG_OVERDUE, t.get("_rank") or 999))
    start = row + 1
    if not alerts:
        ws.cell(row=start, column=1, value="なし 🎉")
        ws.merge_cells(start_row=start, start_column=1, end_row=start, end_column=7)
        style_body(ws, start, start, 7)
        row = start + 2
    else:
        for i, t in enumerate(alerts):
            r = start + i
            vals = [f"{t['id']} {t['title']}", t.get("department"), t.get("assignee"),
                    fmt_jp(parse_date(t.get("due"))), fmt_jp(t["_forecast"]), t["_flag"], t.get("note", "")]
            for c, v in enumerate(vals, start=1):
                ws.cell(row=r, column=c, value=v)
            style_body(ws, r, r, 7)
            for c in (1, 7):
                ws.cell(row=r, column=c).alignment = Alignment(vertical="center", wrap_text=True)
            ws.cell(row=r, column=6).fill = PatternFill("solid", fgColor=FLAG_FILL[t["_flag"]])
        row = start + len(alerts) + 1

    # 部署別
    section_title(ws, row, "部署別")
    row += 1
    dep_headers = ["部署", "全件", "完了", "未完了", "遅延・超過", "残pt"]
    for c, h in enumerate(dep_headers, start=1):
        ws.cell(row=row, column=c, value=h)
    style_header(ws, row, len(dep_headers))
    dep_start = row + 1
    deps = [d for d in DEPARTMENTS if any(t.get("department") == d for t in tasks)] or DEPARTMENTS[:4]
    for i, d in enumerate(deps):
        r = dep_start + i
        dt = [t for t in tasks if t.get("department") == d]
        vals = [d, len(dt), sum(t["status"] == "完了" for t in dt), sum(t["status"] != "完了" for t in dt),
                sum(t["_flag"] in (FLAG_OVERDUE, FLAG_LATE) for t in dt), round(sum(remaining_points(t) for t in dt), 1)]
        for c, v in enumerate(vals, start=1):
            ws.cell(row=r, column=c, value=v)
        style_body(ws, r, r, len(dep_headers))
    dep_end = dep_start + len(deps) - 1

    chart = BarChart()
    chart.type = "bar"
    chart.grouping = "stacked"
    chart.overlap = 100
    chart.title = "部署別タスク"
    chart.add_data(Reference(ws, min_col=3, max_col=4, min_row=dep_start - 1, max_row=dep_end), titles_from_data=True)
    chart.set_categories(Reference(ws, min_col=1, min_row=dep_start, max_row=dep_end))
    chart.height, chart.width = 6, 12
    ws.add_chart(chart, f"I{dep_start - 1}")
    row = dep_end + 2

    # バーンダウン
    if sprint:
        section_title(ws, row, f"バーンダウン（{sprint['id']}）")
        row += 1
        for c, h in enumerate(["日付", "理想", "実績（残pt）"], start=1):
            ws.cell(row=row, column=c, value=h)
        style_header(ws, row, 3)
        total, rows = burndown(sprint, tasks, today, ctx["cal"])
        bd_start = row + 1
        for i, (d, ideal, actual) in enumerate(rows):
            r = bd_start + i
            ws.cell(row=r, column=1, value=d)
            ws.cell(row=r, column=2, value=ideal)
            ws.cell(row=r, column=3, value=actual)
            style_body(ws, r, r, 3)
        bd_end = bd_start + len(rows) - 1
        lc = LineChart()
        lc.title = f"バーンダウン（計画 {total:g} pt）"
        lc.y_axis.title = "残ポイント"
        lc.add_data(Reference(ws, min_col=2, max_col=3, min_row=bd_start - 1, max_row=bd_end), titles_from_data=True)
        lc.set_categories(Reference(ws, min_col=1, min_row=bd_start, max_row=bd_end))
        lc.series[0].graphicalProperties.line.dashStyle = "dash"
        lc.series[0].graphicalProperties.line.solidFill = "A6A6A6"
        lc.series[1].graphicalProperties.line.solidFill = "1F4E78"
        lc.series[1].graphicalProperties.line.width = 28000
        lc.height, lc.width = 7, 16
        ws.add_chart(lc, "I4")


def build_daily_sheet(wb, ctx):
    ws = wb.create_sheet("日次スプリント")
    ws.sheet_view.showGridLines = False
    set_widths(ws, [14, 10, 12, 12, 10, 14, 40, 30, 14])
    ws["A1"] = "日次スプリント（9時 計画 → すぐ実行 → 17時 振り返り）"
    ws["A1"].font = Font(name=FONT, size=14, bold=True, color="1F4E78")
    ws["A2"] = (f"ベロシティ＝直近{VELOCITY_DAYS}営業日の完了ptの平均。今日の容量の目安：{ctx['velocity']:.1f} pt"
                f"（{ctx['velocity_src']}）。{OWNER_CALL}のタスクはポイントに数えません")
    ws["A2"].font = Font(name=FONT, size=9, color="808080")
    headers = ["日付", "容量", "約束pt", "完了pt", "達成率", f"ベロシティ({VELOCITY_DAYS}日平均)", "計画したタスク", "持ち越し・止まった理由", "状態"]
    for c, h in enumerate(headers, start=1):
        ws.cell(row=4, column=c, value=h)
    style_header(ws, 4, len(headers))
    rows = daily_rows(ctx["data"], ctx["tasks"])
    for i, r in enumerate(rows):
        row = 5 + i
        ds = r["ds"]
        blockers = ds.get("blockers") or {}
        vals = [fmt_jp(r["date"]), ds.get("capacity"), r["committed"], r["done"],
                f"{r['rate']:.0%}" if r["rate"] is not None else "―", round(r["avg"], 1),
                "、".join(ds.get("planned", []))
                + (f"／割り込み：{'、'.join(ds['added'])}" if ds.get("added") else "")
                + (f"／追加：{'、'.join(ds['pulled'])}" if ds.get("pulled") else ""),
                "、".join(f"{k}：{v}" for k, v in blockers.items()) or "、".join(ds.get("carried_over", [])),
                ds.get("status", "")]
        for c, v in enumerate(vals, start=1):
            ws.cell(row=row, column=c, value=v)
        style_body(ws, row, row, len(headers))
        for c in (7, 8):
            ws.cell(row=row, column=c).alignment = Alignment(vertical="center", wrap_text=True)
    if not rows:
        ws.cell(row=5, column=1, value="まだ記録がありません（平日9時のプランニングで作られます）").font = BODY_FONT
        return
    end = 4 + len(rows)
    lc = LineChart()
    lc.title = "約束pt・完了pt・ベロシティ"
    lc.y_axis.title = "pt"
    lc.add_data(Reference(ws, min_col=3, max_col=4, min_row=4, max_row=end), titles_from_data=True)
    lc.add_data(Reference(ws, min_col=6, min_row=4, max_row=end), titles_from_data=True)
    lc.set_categories(Reference(ws, min_col=1, min_row=5, max_row=end))
    lc.series[0].graphicalProperties.line.dashStyle = "dash"
    lc.series[0].graphicalProperties.line.solidFill = "A6A6A6"
    lc.series[1].graphicalProperties.line.solidFill = "1F4E78"
    lc.series[2].graphicalProperties.line.solidFill = "C55A11"
    lc.height, lc.width = 8, 18
    ws.add_chart(lc, f"A{end + 2}")


def build_own_sheet(wb, ctx):
    ws = wb.create_sheet(f"{OWNER_CALL}の仕事")
    ws.sheet_view.showGridLines = False
    set_widths(ws, [8, 7, 48, 12, 12, 12, 10, 30, 40])
    ws["A1"] = f"🗂 {OWNER_CALL}の仕事（自分でやるタスク）"
    ws["A1"].font = Font(name=FONT, size=14, bold=True, color="1F4E78")
    ws["A2"] = "「タスク追加：◯◯（〆11/5）、△△」と話しかけると増えます。終わったら「T0XX 終わった」。AI が引き受けられる部分は、AI のタスクに切り出します"
    ws["A2"].font = Font(name=FONT, size=9, color="808080")
    headers = ["今日", "ID", "仕事", "部署", "期日", "残り", "状態", "AI に渡した部分", "メモ"]
    for c, h in enumerate(headers, start=1):
        ws.cell(row=4, column=c, value=h)
    style_header(ws, 4, len(headers))
    picks = {t["id"] for t in today_own_picks(ctx["tasks"], ctx["today"])}
    by_dep = {}
    for t in ctx["tasks"]:
        for dep in t.get("depends_on") or []:
            by_dep.setdefault(dep, []).append(t["id"])
        if t.get("related"):
            by_dep.setdefault(t["related"], []).append(t["id"])
    rows = own_tasks(ctx["tasks"]) + [t for t in own_tasks(ctx["tasks"], include_done=True) if t["status"] == "完了"][-10:]
    for i, t in enumerate(rows, start=5):
        due = parse_date(t.get("due"))
        ai_part = "、".join(x for x in by_dep.get(t["id"], []) if x != t["id"])
        vals = ["★" if t["id"] in picks else "", t["id"], t["title"], t.get("department", ""),
                fmt_jp(due) if due else "なし", days_left(t, ctx["today"]) if due and t["status"] != "完了" else "", t["status"], ai_part, t.get("note", "")]
        for c, v in enumerate(vals, start=1):
            ws.cell(row=i, column=c, value=v)
        style_body(ws, i, i, len(headers))
        ws.cell(row=i, column=7).fill = PatternFill("solid", fgColor=STATUS_FILL.get(t["status"], "FFFFFF"))
        if due and due < ctx["today"] and t["status"] != "完了":
            ws.cell(row=i, column=5).fill = PatternFill("solid", fgColor=FLAG_FILL[FLAG_OVERDUE])
    if not rows:
        ws.cell(row=5, column=1, value="まだありません。「タスク追加：…」と話しかけてください").font = BODY_FONT
    if ctx.get("events") is not None:
        ws.column_dimensions["K"].width = 12
        ws.column_dimensions["L"].width = 14
        ws.column_dimensions["M"].width = 36
        for c, h in enumerate(["日付", "時間", "予定（件名だけ）"], start=11):
            ws.cell(row=4, column=c, value=h)
            ws.cell(row=4, column=c).fill = HEADER_FILL
            ws.cell(row=4, column=c).font = HEADER_FONT
            ws.cell(row=4, column=c).border = BORDER
        for i, e in enumerate(ctx["events"] or [], start=5):
            vals = [fmt_jp(parse_date(e["date"])), "終日" if e["allday"] else f"{e['start']}〜{e['end']}", e["title"]]
            for c, v in enumerate(vals, start=11):
                cell = ws.cell(row=i, column=c, value=v)
                cell.font = BODY_FONT
                cell.border = BORDER
        if not ctx["events"]:
            ws.cell(row=5, column=11, value="予定なし（または取得できませんでした）").font = BODY_FONT


def build_requests_sheet(wb, ctx):
    ws = wb.create_sheet(f"{OWNER_CALL}へのお願い")
    ws.sheet_view.showGridLines = False
    ws["A1"] = f"📌 {OWNER_CALL}へのお願い（{AI_NAME}からの指示）"
    ws["A1"].font = Font(name=FONT, size=14, bold=True, color="1F4E78")
    ws["A2"] = f"AIでは実行できない判断・申請・確認・送付です。終わったら {AI_NAME}に「T0XX やった」と伝えてください。"
    ws["A2"].font = Font(name=FONT, size=9, color="595959")
    headers = ["順位", "ID", "種類", "内容", "期日", "残り", f"なぜ{OWNER_CALL}が", "手順", "完了の基準",
               "終わったら教えてほしいこと", "状態"]
    set_widths(ws, [6, 7, 8, 30, 11, 9, 26, 52, 24, 24, 12])
    for c, h in enumerate(headers, start=1):
        ws.cell(row=4, column=c, value=h)
    style_header(ws, 4, len(headers))
    reqs = sorted(owner_requests(ctx["tasks"]), key=lambda t: (parse_date(t.get("due")) or date.max, t.get("_rank") or 999))
    if not reqs:
        ws.cell(row=5, column=1, value="いまお願いはありません 🎉").font = BODY_FONT
        return
    for i, t in enumerate(reqs, start=5):
        kind = t.get("kind") or "その他"
        steps = "\n".join(f"{n}. {x}" for n, x in enumerate(t.get("steps") or [], start=1))
        due = parse_date(t.get("due"))
        vals = [t.get("_rank"), t["id"], f"{KIND_ICON.get(kind, '')} {kind}", t["title"],
                fmt_jp(due) if due else "未設定", days_left(t, ctx["today"]), t.get("why", ""), steps,
                t.get("done_when", ""), t.get("report_back", ""), t["_flag"]]
        for c, v in enumerate(vals, start=1):
            ws.cell(row=i, column=c, value=v)
        style_body(ws, i, i, len(headers))
        for c in range(1, len(headers) + 1):
            ws.cell(row=i, column=c).alignment = Alignment(vertical="top", wrap_text=True)
        if t["_flag"] in FLAG_FILL:
            ws.cell(row=i, column=11).fill = PatternFill("solid", fgColor=FLAG_FILL[t["_flag"]])
    ws.freeze_panes = "E5"


def build_requests_md(ctx):
    tasks = ctx["tasks"]
    reqs = owner_requests(tasks)
    lines = [f"# 📌 {OWNER_CALL}へのお願い", "",
             f"> {AI_NAME}からの指示です（自動生成：{ctx['now']}）。", "",
             "> **返事のしかた**：終わったら「T0XX やった」／できない・無いときは「T0XX は無い」（代わりの進め方を考えます）／"
             "変えてほしいときは「T0XX はこう変えて」。どれも一言で大丈夫です", "",
             f"**未完了：{len(reqs)} 件**"]
    if reqs:
        lines += ["", "## 期日順", "", "| 期日 | 残り | ID | 種類 | 内容 |", "|---|---|---|---|---|"]
        for t in sorted(reqs, key=lambda t: (parse_date(t.get("due")) or date.max, t.get("_rank") or 999)):
            due = parse_date(t.get("due"))
            lines.append(f"| {fmt_jp(due) if due else '未設定'} | {days_left(t, ctx['today'])} | {t['id']} | "
                         f"{KIND_ICON.get(t.get('kind') or 'その他', '')} {t.get('kind') or 'その他'} | {t['title']} |")
    if not reqs:
        lines += ["", "いまお願いはありません 🎉"]
    for kind in KINDS + ["その他"]:
        group = [t for t in reqs if (t.get("kind") or "その他") == kind]
        if not group:
            continue
        lines += ["", f"## {KIND_ICON[kind]} {kind}（{len(group)}）"]
        for t in group:
            due = parse_date(t.get("due"))
            lines += ["", f"### {t['id']} {t['title']}", "",
                      f"- **期日**：{fmt_jp(due) if due else '未設定'}（{days_left(t, ctx['today'])}）　{t['_flag']}"]
            if t.get("due_reason"):
                lines.append(f"- **期日の理由**：{t['due_reason']}")
            if t.get("why"):
                lines.append(f"- **なぜ{OWNER_CALL}が**：{t['why']}")
            if t.get("related"):
                lines.append(f"- **関連**：{t['related']}")
            if t.get("steps"):
                lines.append("- **手順**：")
                lines += [f"  {n}. {x}" for n, x in enumerate(t["steps"], start=1)]
            if t.get("done_when"):
                lines.append(f"- **完了の基準**：{t['done_when']}")
            if t.get("report_back"):
                lines.append(f"- **終わったら教えてほしいこと**：{t['report_back']}")
    done = sorted([t for t in tasks if t.get("assignee") == OWNER and t["status"] == "完了" and t.get("kind") != OWN_KIND],
                  key=lambda t: t.get("done_date") or "", reverse=True)[:5]
    if done:
        lines += ["", "## 最近完了したお願い", ""]
        lines += [f"- ✅ {t['id']} {t['title']}（{fmt_jp(parse_date(t.get('done_date')))}）" for t in done]
    return "\n".join(lines) + "\n"


def build_task_list(wb, ctx):
    ws = wb.create_sheet("タスク一覧")
    headers = ["優先順位", "ID", "タイトル", "部署", "種類", "デザイン", "作る人", "確かめる人", "ステータス", "状態", "pt", "進捗%",
               "開始日", "納期", "完了予定日", "完了日", "スプリント", "PDCA", "メモ"]
    set_widths(ws, [9, 7, 40, 12, 12, 8, 10, 10, 10, 13, 5, 7, 11, 11, 11, 11, 10, 8, 40])
    for c, h in enumerate(headers, start=1):
        ws.cell(row=1, column=c, value=h)
    style_header(ws, 1, len(headers))
    ws.freeze_panes = "D2"
    tasks = sorted(ctx["tasks"], key=lambda t: (t["status"] == "完了", t.get("_rank") or 999,
                                                 -(parse_date(t.get("done_date")) or date.min).toordinal()))
    for i, t in enumerate(tasks, start=2):
        due = t.get("due")
        vals = [t.get("_rank") or "", t["id"], t["title"], t.get("department"), t.get("type", ""),
                "部下E" if t.get("design") else "",
                MEMBER_LABEL.get(t.get("assignee"), t.get("assignee")), MEMBER_LABEL.get(t.get("reviewer"), t.get("reviewer") or ""),
                t["status"],
                t["_flag"], t.get("points"), t.get("progress") or (100 if t["status"] == "完了" else 0),
                parse_date(t.get("start")), parse_date(due) if due else "指定なし", t["_forecast"],
                parse_date(t.get("done_date")), t.get("sprint"), t.get("pdca"), t.get("note", "")]
        for c, v in enumerate(vals, start=1):
            cell = ws.cell(row=i, column=c, value=v)
            if isinstance(v, date):
                cell.number_format = "m/d(aaa)"
        style_body(ws, i, i, len(headers))
        ws.cell(row=i, column=9).fill = PatternFill("solid", fgColor=STATUS_FILL.get(t["status"], "FFFFFF"))
        if t["_flag"] in FLAG_FILL:
            ws.cell(row=i, column=10).fill = PatternFill("solid", fgColor=FLAG_FILL[t["_flag"]])
        if t["status"] == "完了":
            for c in (3,):
                ws.cell(row=i, column=c).font = Font(name=FONT, size=10, color="808080")
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(len(tasks) + 1, 2)}"


def build_gantt(wb, ctx):
    ws = wb.create_sheet("ガント")
    today, cal, tasks = ctx["today"], ctx["cal"], ctx["tasks"]
    items = sorted(tasks, key=lambda t: (t["status"] == "完了", t.get("_rank") or 999))
    starts = [parse_date(t.get("start")) or today for t in items]
    ends = [max(filter(None, [t["_forecast"], parse_date(t.get("due"))]), default=today) for t in items]
    begin = min(starts + [today - timedelta(days=7)])
    finish = max(ends + [today + timedelta(days=14)])
    finish = min(finish, begin + timedelta(days=120))
    days = [begin + timedelta(days=i) for i in range((finish - begin).days + 1)]

    fixed = ["ID", "タイトル", "担当", "ステータス", "納期"]
    nfix = len(fixed)
    set_widths(ws, [7, 34, 9, 9, 9])
    for c, h in enumerate(fixed, start=1):
        ws.cell(row=2, column=c, value=h)
    style_header(ws, 2, nfix)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=nfix)
    ws.cell(row=1, column=1, value="■ 計画（開始〜完了予定）　■ 完了　◆ 納期　│ 今日").font = Font(name=FONT, size=9)
    for j, d in enumerate(days):
        col = nfix + 1 + j
        ws.column_dimensions[get_column_letter(col)].width = 3.2
        top = ws.cell(row=1, column=col, value=f"{d.month}月" if d.day == 1 or j == 0 else None)
        top.font = Font(name=FONT, size=8, bold=True)
        c = ws.cell(row=2, column=col, value=d.day)
        c.font = Font(name=FONT, size=8, color="FFFFFF", bold=(d == today))
        c.alignment = Alignment(horizontal="center")
        c.fill = PatternFill("solid", fgColor="C00000" if d == today else ("7F7F7F" if not cal.is_workday(d) else "1F4E78"))
    ws.freeze_panes = ws.cell(row=3, column=nfix + 1)

    for i, t in enumerate(items):
        r = 3 + i
        due = parse_date(t.get("due"))
        vals = [t["id"], t["title"], t.get("assignee"), t["status"], fmt_jp(due) if due else "―"]
        for c, v in enumerate(vals, start=1):
            ws.cell(row=r, column=c, value=v)
        style_body(ws, r, r, nfix)
        ws.cell(row=r, column=4).fill = PatternFill("solid", fgColor=STATUS_FILL.get(t["status"], "FFFFFF"))
        s = starts[i]
        e = t["_forecast"] or s
        color = "70AD47" if t["status"] == "完了" else ("ED7D31" if t["_flag"] in (FLAG_OVERDUE, FLAG_LATE) else "5B9BD5")
        for j, d in enumerate(days):
            cell = ws.cell(row=r, column=nfix + 1 + j)
            cell.border = Border(left=Side(style="thin", color="C00000") if d == today else None,
                                 bottom=Side(style="hair", color="D9D9D9"))
            if not cal.is_workday(d):
                cell.fill = PatternFill("solid", fgColor="F2F2F2")
            if s <= d <= e:
                cell.fill = PatternFill("solid", fgColor=color)
            if due and d == due:
                cell.value = "◆"
                cell.font = Font(name=FONT, size=9, bold=True, color="C00000")
                cell.alignment = Alignment(horizontal="center")


def build_sprint_history(wb, ctx):
    ws = wb.create_sheet("スプリント履歴")
    headers = ["スプリント", "ゴール", "開始", "終了", "状態", "計画pt", "完了pt", "達成率", "振り返りメモ"]
    set_widths(ws, [10, 44, 11, 11, 9, 8, 8, 8, 44])
    for c, h in enumerate(headers, start=1):
        ws.cell(row=1, column=c, value=h)
    style_header(ws, 1, len(headers))
    for i, s in enumerate(ctx["data"].get("sprints", []), start=2):
        st = [t for t in ctx["tasks"] if t.get("sprint") == s["id"]]
        plan = sum(float(t.get("points") or 0) for t in st)
        done = sum(float(t.get("points") or 0) for t in st if t["status"] == "完了")
        vals = [s["id"], s.get("goal"), parse_date(s["start"]), parse_date(s["end"]), s.get("status"),
                plan, done, (done / plan) if plan else 0, s.get("retro", "")]
        for c, v in enumerate(vals, start=1):
            cell = ws.cell(row=i, column=c, value=v)
            if isinstance(v, date):
                cell.number_format = "m/d(aaa)"
        ws.cell(row=i, column=8).number_format = "0%"
        style_body(ws, i, i, len(headers))
    ws.freeze_panes = "B2"


# ---------- Markdown ----------

def build_board_md(ctx):
    tasks, sprint = ctx["tasks"], ctx["sprint"]
    lines = ["# タスクボード", "",
             f"> 自動生成：{ctx['now']}（編集しないでください。正本は `data/tasks.json`）", "",
             f"- **全体の完了予定日**：{fmt_jp(ctx['project_end']) if ctx['project_end'] else '残タスクなし'}",
             f"- **ベロシティ**：{ctx['velocity']:.1f} pt/日（{ctx['velocity_src']}）"]
    if sprint:
        lines.append(f"- **現在のスプリント**：{sprint['id']}「{sprint.get('goal', '')}」"
                     f"（{fmt_jp(parse_date(sprint['start']))}〜{fmt_jp(parse_date(sprint['end']))}／{sprint.get('pdca', '')}）")
    alerts = [t for t in tasks if t["_flag"] in (FLAG_OVERDUE, FLAG_LATE)]
    if alerts:
        lines += ["", "## 要注意", ""]
        for t in alerts:
            lines.append(f"- {t['_flag']} **{t['id']} {t['title']}**（納期 {fmt_jp(parse_date(t.get('due')))} → 完了予定 {fmt_jp(t['_forecast'])}）")
    for status in ["作業中", "レビュー", "ToDo", "Backlog", "完了"]:
        st = [t for t in tasks if t["status"] == status]
        if status == "完了":
            st = sorted(st, key=lambda t: t.get("done_date") or "", reverse=True)[:10]
        else:
            st = sorted(st, key=lambda t: t.get("_rank") or 999)
        lines += ["", f"## {status}（{sum(1 for t in tasks if t['status'] == status)}）", ""]
        if not st:
            lines.append("_なし_")
            continue
        lines += ["| 順位 | ID | タイトル | 部署 | 担当 | 納期 | 完了予定 | 状態 |", "|---|---|---|---|---|---|---|---|"]
        for t in st:
            lines.append(f"| {t.get('_rank') or ''} | {t['id']} | {t['title']} | {t.get('department', '')} | "
                         f"{t.get('assignee', '')} | {fmt_jp(parse_date(t.get('due')))} | {fmt_jp(t['_forecast'])} | {t['_flag']} |")
    return "\n".join(lines) + "\n"


def assignment_warnings(tasks):
    """種類と、作る人・確かめる人の組み合わせが「振り分け」の表に合わない未完了タスク。"""
    out = []
    for t in tasks:
        if t["status"] == "完了" or t.get("assignee") == OWNER:
            continue
        typ = t.get("type")
        for who in (t.get("assignee"), t.get("reviewer")):
            if who in TEAM_OFF:
                out.append(f"{t['id']}：{MEMBER_LABEL.get(who, who)} は本人設定で使わない（team.off）")
        if not typ:
            out.append(f"{t['id']}：種類（type）が未設定")
            continue
        makers, reviewers = ASSIGNMENT.get(typ, (None, None))
        if makers is None:
            continue
        if t.get("assignee") not in makers:
            out.append(f"{t['id']}：{typ} なのに作る人が {MEMBER_LABEL.get(t.get('assignee'), t.get('assignee'))}")
        if t.get("reviewer") and t["reviewer"] not in reviewers:
            out.append(f"{t['id']}：{typ} なのに確かめる人が {MEMBER_LABEL.get(t['reviewer'], t['reviewer'])}")
    return out


def summary_text(ctx, limit=10):
    lines = [f"[{AI_NAME} タスク状況 {fmt(ctx['today'])}] 全体完了予定 {fmt_jp(ctx['project_end'])}"
             f"／ベロシティ {ctx['velocity']:.1f}pt/日（{ctx['velocity_src']}）"]
    for t in ctx["open_tasks"][:limit]:
        due = parse_date(t.get("due"))
        lines.append(f"  {t['_rank']}. {t['id']} {t['title']} [{t['status']}/{t.get('assignee', '')}] "
                     f"納期 {fmt_jp(due) if due else '指定なし'} → 完了予定 {fmt_jp(t['_forecast'])} {t['_flag']}")
    if len(ctx["open_tasks"]) > limit:
        lines.append(f"  …ほか {len(ctx['open_tasks']) - limit} 件")
    reqs = owner_requests(ctx["tasks"])
    if ctx.get("events") is not None:
        lines.append(f"[📅 今日の予定 {fmt_jp(ctx['today'])}]（予定の中身は使わず、件名と時間だけ）")
        lines += calendar_today.format_events(ctx["events"], ctx["today"])
    own = own_tasks(ctx["tasks"])
    if own:
        picks = today_own_picks(ctx["tasks"], ctx["today"])
        lines.append(f"[🗂 {OWNER_CALL}の仕事 未完了 {len(own)} 件。今日やるといいもの]")
        for t in picks:
            due = parse_date(t.get("due"))
            lines.append(f"  - {t['id']} {t['title']} — 期日 {fmt_jp(due) if due else 'なし'}"
                         f"{'（' + days_left(t, ctx['today']) + '）' if due else ''}")
    lines.append(f"[📌 {OWNER_CALL}へのお願い 未完了 {len(reqs)} 件]（00_タスク管理/{OWNER_CALL}へのお願い.md）")
    for t in sorted(reqs, key=lambda t: parse_date(t.get("due")) or date.max):
        due = parse_date(t.get("due"))
        lines.append(f"  - {t['id']} [{t.get('kind') or 'その他'}] {t['title']} — 期日 {fmt_jp(due) if due else '未設定'}"
                     f"（{days_left(t, ctx['today'])}）{' 🔴' if t['_flag'] == FLAG_OVERDUE else ''}")
    warns = assignment_warnings(ctx["tasks"])
    if warns:
        lines.append(f"[⚠ 振り分けの確認 {len(warns)} 件] " + "／".join(warns[:6]) + ("／…" if len(warns) > 6 else ""))
    tds = today_sprint(ctx["data"], ctx["today"])
    if tds:
        r = next(r for r in daily_rows(ctx["data"], ctx["tasks"]) if r["ds"] is tds)
        lines.append(f"[📅 今日の計画] {'、'.join(tds.get('planned', []))} — 約束 {r['committed']:g}pt／完了 {r['done_planned']:g}pt"
                     f"（{tds.get('status', '')}）")
    if LOCK_FILE.exists():
        lines.append(f"[⏳ 自動実行中] {LOCK_FILE.read_text(encoding='utf-8').strip()}。tasks.json の同時編集に注意")
    tries = active_tries_text()
    if tries:
        lines.append("[🔁 実施中の Try（今日の作業で意識する。17時の振り返りで検証）]")
        lines.append(tries)
    review = latest_review(ctx["today"])
    if review:
        path, digest = review
        lines.append(f"[🗒 直近の振り返り]（{path.relative_to(ROOT)}）")
        lines.append(digest)
    return "\n".join(lines)


# ---------- 振り返り（変更履歴・Try・議事録） ----------

def record_history(data):
    """前回の tasks.json との差分を history.jsonl に追記する。初回はスナップショットだけ作る。"""
    current = {t["id"]: {k: t.get(k) for k in HISTORY_FIELDS} for t in data.get("tasks", [])}
    if SNAPSHOT_JSON.exists():
        prev = json.loads(SNAPSHOT_JSON.read_text(encoding="utf-8"))
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        entries = []
        for tid, cur in current.items():
            old = prev.get(tid)
            if old is None:
                entries.append({"at": now, "id": tid, "change": "新規", "title": cur["title"], "status": cur["status"]})
                continue
            diff = {k: [old.get(k), cur.get(k)] for k in HISTORY_FIELDS if old.get(k) != cur.get(k)}
            if diff:
                entries.append({"at": now, "id": tid, "change": "更新", "title": cur["title"], "diff": diff})
        if entries:
            with HISTORY_JSONL.open("a", encoding="utf-8") as f:
                for e in entries:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
    SNAPSHOT_JSON.write_text(json.dumps(current, ensure_ascii=False, indent=1), encoding="utf-8")


def history_on(day):
    if not HISTORY_JSONL.exists():
        return []
    key = fmt(day)
    out = []
    for line in HISTORY_JSONL.read_text(encoding="utf-8").splitlines():
        if line.strip():
            e = json.loads(line)
            if e["at"].startswith(key):
                out.append(e)
    return out


def md_section(text, heading):
    """'## heading' から次の '## ' までの本文。"""
    lines, inside = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            if inside:
                break
            inside = line[3:].strip().startswith(heading)
            continue
        if inside:
            lines.append(line)
    return "\n".join(l for l in lines if l.strip() and not l.startswith(">") and not l.startswith("<!--")).strip()


def active_tries_text():
    if not KAIZEN_MD.exists():
        return ""
    body = md_section(KAIZEN_MD.read_text(encoding="utf-8"), "実施中の Try")
    return "" if body in ("", "- （なし）") else body


def latest_review(today):
    files = sorted(SPRINT_DIR.glob("*/daily/*_振り返り.md"), key=lambda p: p.name)
    files = [p for p in files if p.name[:8] <= today.strftime("%Y%m%d")]
    if not files:
        return None
    path = files[-1]
    digest = md_section(path.read_text(encoding="utf-8"), "3行まとめ")
    return path, digest


def plan_context(today, cal, ctx):
    """9時のプランニング（と実行中の追加判断）の材料。1行目が OPEN か SKIP。"""
    data, tasks = ctx["data"], ctx["tasks"]
    by_id = {t["id"]: t for t in tasks}
    if not cal.is_workday(today):
        head = "SKIP: 営業日ではない"
    elif today_sprint(data, today):
        head = "SKIP: 今日の計画は作成済み"
    else:
        head = "OPEN"
    # 何日目か（今日より前で計画のあった日＋今日）と、実行中に追加でタスクを取れるか
    day_no = len([d for d in data.get("daily_sprints", []) if d.get("planned") and d["date"] < fmt(today)]) + 1
    tds = today_sprint(data, today)
    if day_no <= EXTRA_FROM_DAY - 1:
        extra = f"不可（{EXTRA_FROM_DAY - 1}日目までは計画した分だけ）"
    elif datetime.now().strftime("%H:%M") >= EXTRA_CUTOFF:
        extra = f"不可（{EXTRA_CUTOFF} を過ぎた）"
    elif tds:
        r = next(r for r in daily_rows(data, tasks) if r["ds"] is tds)
        room = r["committed"] + EXTRA_POINTS - (r["done_planned"] + r["done_extra"])
        extra = (f"可（あと {room:g}pt まで。上限＝約束 {r['committed']:g}pt＋{EXTRA_POINTS}pt、今日の完了は計画分＋追加分で数える）"
                 if room > 0 else f"不可（約束＋{EXTRA_POINTS}pt に達した）")
    else:
        extra = "―（今日の計画がまだない）"
    sprint = ctx["sprint"]
    sprint_dir = next(iter(sorted(SPRINT_DIR.glob(f"{sprint['id']}_*"))), None) if sprint else None
    lines = [head, f"日付: {fmt(today)}",
             f"計画の保存先: {(sprint_dir.relative_to(ROOT) if sprint_dir else '01_スプリント/<今のスプリント>')}/daily/{today.strftime('%Y%m%d')}_計画.md",
             f"今日の容量の目安: {ctx['velocity']:.1f} pt（{ctx['velocity_src']}）", "",
             f"今日は日次スプリント {day_no} 日目（計画ありの日を数える。3日目までは追加でタスクを取らない）",
             f"現在時刻: {datetime.now().strftime('%H:%M')}",
             f"追加でタスクを取れるか: {extra}", "",
             "## 候補タスク（AI の未完了タスク、優先順。🆕＝前回の計画以降に登録、🔁＝要再見積もり → この2つと 8pt 以上を見積もる）"]

    prev_dates = sorted(ds["date"] for ds in data.get("daily_sprints", []) if ds["date"] < fmt(today))
    since = prev_dates[-1] if prev_dates else "0000-00-00"
    new_ids = set()
    if HISTORY_JSONL.exists():
        for line in HISTORY_JSONL.read_text(encoding="utf-8").splitlines():
            if line.strip():
                e = json.loads(line)
                if e.get("change") == "新規" and e["at"][:10] >= since:
                    new_ids.add(e["id"])

    def blocked_by(t):
        return [d for d in t.get("depends_on") or [] if d in by_id and by_id[d]["status"] != "完了"]

    for t in [t for t in ctx["open_tasks"] if t.get("assignee") != OWNER]:
        b = blocked_by(t)
        waits = "、".join(f"{d}（{by_id[d].get('assignee')}）" for d in b)
        note = f" ⛔ 待ち：{waits}" if b else ""
        marks = ("🆕新規 " if t["id"] in new_ids else "") + ("🔁要再見積もり " if t.get("reestimate") else "")
        lines.append(f"- {t['_rank']}. {marks}{t['id']} {t['title']} [{t['status']}] {t.get('points') or '未見積もり'}pt"
                     f" 納期 {fmt_jp(parse_date(t.get('due')))}{note}")
    prev = [ds for ds in data.get("daily_sprints", []) if ds["date"] < fmt(today)]
    if prev:
        last = sorted(prev, key=lambda x: x["date"])[-1]
        lines += ["", f"## 前回（{last['date']}）の持ち越し・止まった理由"]
        lines += [f"- {k}：{v}" for k, v in (last.get("blockers") or {}).items()] or [f"- {i}" for i in last.get("carried_over", [])] or ["- なし"]
    if ctx.get("events") is not None:
        todays = [e for e in ctx["events"] if e["date"] == fmt(today) and not e["allday"]]
        lines += ["", f"## 今日の予定（{len(todays)} 件。会議の多い日は、本人の仕事とお願いを絞る。会議の準備が要りそうなら提案する）"]
        lines += calendar_today.format_events(ctx["events"], today)
    picks = today_own_picks(tasks, today)
    if picks:
        lines += ["", f"## {OWNER_CALL}の仕事（今日やるといいもの。ポイントには数えない）"]
        lines += [f"- {t['id']} {t['title']} 期日 {fmt_jp(parse_date(t.get('due')))}" for t in picks]
    lines += ["", f"## {OWNER_CALL}へのお願い（期日順。AI のタスクを止めているものに注意）"]
    for t in sorted(owner_requests(tasks), key=lambda t: parse_date(t.get("due")) or date.max):
        waiting = [x["id"] for x in tasks if t["id"] in (x.get("depends_on") or []) and x["status"] != "完了"]
        lines.append(f"- {t['id']} [{t.get('kind')}] {t['title']} 期日 {fmt_jp(parse_date(t.get('due')))}"
                     + (f" → 待っているタスク：{'、'.join(waiting)}" if waiting else ""))
    lines += ["", "## 実施中の Try", active_tries_text() or "- なし"]
    return "\n".join(lines)


MANUAL_WORDS = ["転記", "集計", "コピー", "貼り付け", "入力", "照合", "突き合わせ", "確認", "送付", "連絡", "更新",
                "毎週", "毎月", "毎日", "定例", "まとめ", "報告", "リマインド", "チェック", "ダウンロード", "アップロード"]


def normalize_title(title):
    """似た仕事をまとめるための見出し：日付・数字・括弧の中・回数を取り除く。"""
    t = re.sub(r"[（(【\[].*?[）)】\]]", "", title)
    t = re.sub(r"\d+[/月年日回週号]?\d*", "", t)
    t = re.sub(r"(第|今週分|今月分|今日分|分|の件|について|を作る|を作成|をする|する)$", "", t.strip())
    return re.sub(r"\s+", "", t)[:18]


def improvement_candidates(ctx, today, weeks=4):
    """直近 weeks 週の、繰り返している仕事と手作業らしい仕事。判断は指揮官（スクリプトは材料だけ）。"""
    since = today - timedelta(days=weeks * 7 - 1)
    # AI から本人へのお願い（判断・申請など一度きりのもの）は除き、本人の仕事と AI のタスクを見る
    recent = [t for t in ctx["tasks"] if not (t.get("assignee") == OWNER and t.get("kind") in KINDS)
              and (parse_date(t.get("start")) or parse_date(t.get("done_date")) or parse_date(t.get("due")) or today) >= since]
    groups = {}
    for t in recent:
        groups.setdefault(normalize_title(t["title"]), []).append(t)
    repeated = sorted(((k, v) for k, v in groups.items() if len(v) >= 2 and k), key=lambda kv: -len(kv[1]))
    manual = [t for t in recent if any(w in t["title"] for w in MANUAL_WORDS)]
    lines = [f"## 改善の材料（直近{weeks}週。金曜に指揮官が見て、システム化の提案を最大3件）"]
    lines.append("- 繰り返している仕事：" + ("／".join(f"{k}（{len(v)}回：{'・'.join(x['id'] for x in v[:5])}）" for k, v in repeated[:8])
                                       or "なし"))
    lines.append("- 手作業らしい仕事：" + ("／".join(f"{t['id']} {t['title'][:24]}" for t in manual[:10]) or "なし"))
    regular = (_cfg.get("regular") or [])
    if regular:
        lines.append("- 本人設定の定例業務：" + "、".join(regular))
    lines.append(f"- 提案の一覧（採用・見送りの記録）：02_成果物/共通/業務改善の提案.md")
    return "\n".join(lines)


def team_summary(ctx, today):
    """金曜の振り返り用：部下ごとの仕事の数（直近7日・14日）、役を渡した仕事、Opus に上げた回数、使う部下の数／上限。"""
    tasks = ctx["tasks"]
    last7, last14 = today - timedelta(days=6), today - timedelta(days=13)

    def touched(t, since):
        d = parse_date(t.get("done_date")) or parse_date(t.get("start"))
        return d is not None and since <= d <= today

    members = [m for m in MEMBER_LABEL if m not in TEAM_OFF]
    joined = (_cfg.get("team") or {}).get("joined", {})
    starts = [parse_date(ds["date"]) for ds in ctx["data"].get("daily_sprints", [])] + \
             [parse_date(t.get("start")) for t in tasks if t.get("start")]
    first_day = min([d for d in starts if d] or [today])
    agents_dir = ROOT / ".claude" / "agents"   # やめた部下は .claude/agents_off/ に移す（数えない）
    local_agents = sorted(p.stem for p in agents_dir.glob("*.md")
                          if p.read_text(encoding="utf-8").lstrip().startswith("---")
                          and "\nname:" in p.read_text(encoding="utf-8")) if agents_dir.exists() else []
    lines = ["## チームのまとめ（金曜）", f"- 使う部下の数／上限：{len(members) + len(local_agents)}／{TEAM_MAX}"
             f"（共通 {len(members)}、本人用 {len(local_agents)}{'：' + '・'.join(local_agents) if local_agents else ''}"
             f"{'、使わない：' + '・'.join(MEMBER_LABEL.get(m, m) for m in sorted(TEAM_OFF)) if TEAM_OFF else ''}）"]
    for m in members + local_agents:
        n7 = sum(1 for t in tasks if m in (t.get("assignee"), t.get("reviewer")) and touched(t, last7))
        n14 = sum(1 for t in tasks if m in (t.get("assignee"), t.get("reviewer")) and touched(t, last14))
        since = parse_date(joined.get(m)) or first_day
        days = (today - since).days
        flag = ("　← 2週間 呼ばれていない（やめる候補）" if n14 == 0 and days >= 14
                else (f"（参加から{days}日。1週間のお試し中）" if m in joined and days < 7 else ""))
        lines.append(f"- {MEMBER_LABEL.get(m, m)}（{m}）：直近7日 {n7} 件／14日 {n14} 件{flag}")
    roles = {}
    for t in tasks:
        note = t.get("note") or ""
        if "役：" in note and touched(t, last7):
            name = note.split("役：", 1)[1].split()[0].split("／")[0].strip("（）()")
            roles.setdefault(name, []).append(t["id"])
    lines.append("- 役を渡した仕事（直近7日）：" + ("、".join(f"{k}：{'・'.join(v)}" + ("（2回以上＝部下を足す候補）" if len(v) >= 2 else "")
                                                     for k, v in roles.items()) or "なし"))
    log = "\n".join(p.read_text(encoding="utf-8") for p in SPRINT_DIR.glob("*/do_log.md"))
    lines.append(f"- Opus に上げた記録（do_log 全体の「Opus に上げた理由」の行数）：{log.count('Opus に上げた理由')}")
    return "\n".join(lines)


def review_context(today, cal, ctx):
    """17時の振り返り会議の材料。1行目が OPEN か SKIP。"""
    hist = history_on(today)
    tries = active_tries_text()
    day = today.strftime("%Y%m%d")
    touched = []
    for base in (ROOT / "02_成果物", SPRINT_DIR):
        for p in base.rglob("*"):
            if p.is_file() and not p.name.startswith(".") and datetime.fromtimestamp(p.stat().st_mtime).date() == today and "/daily/" not in str(p):
                touched.append(str(p.relative_to(ROOT)))
    reviewed = (today_sprint(ctx["data"], today) or {}).get("status") == "振り返り済み" or any(
        SPRINT_DIR.glob(f"*/daily/{day}_振り返り.md"))
    if not cal.is_workday(today):
        head = "SKIP: 営業日ではない"
    elif reviewed:
        head = "SKIP: 振り返り済み"
    elif not hist and not touched and not tries and not any(t.get("done_date") == fmt(today) for t in ctx["tasks"]):
        head = "SKIP: 今日の動きなし・実施中の Try なし"
    else:
        head = "OPEN"
    sprint = ctx["sprint"]
    sprint_dir = next(iter(sorted(SPRINT_DIR.glob(f"{sprint['id']}_*"))), None) if sprint else None
    lines = [head, f"日付: {fmt(today)}",
             f"議事録の保存先: {(sprint_dir.relative_to(ROOT) if sprint_dir else '01_スプリント/<今のスプリント>')}/daily/{day}_振り返り.md",
             "", "## 今日のタスクの変更（history.jsonl）"]
    lines += [f"- {e['at'][11:]} {e['id']} {e['title']} {e['change']} "
              + (json.dumps(e.get('diff'), ensure_ascii=False) if e.get('diff') else e.get('status', '')) for e in hist] or ["- なし"]
    tds = today_sprint(ctx["data"], today)
    lines += ["", "## 今日の計画（日次スプリント）"]
    if tds:
        r = next(r for r in daily_rows(ctx["data"], ctx["tasks"]) if r["ds"] is tds)
        by_id = {t["id"]: t for t in ctx["tasks"]}
        lines.append(f"- 容量 {tds.get('capacity')}pt／約束 {r['committed']:g}pt／計画分の完了 {r['done_planned']:g}pt／"
                     f"今日の完了（計画外を含む） {r['done']:g}pt")
        lines += [f"- {i} {by_id[i]['title']}（{by_id[i].get('points')}pt）→ {by_id[i]['status']}" for i in tds.get("planned", [])]
        for key, label in (("added", "割り込み"), ("pulled", "追加で取った")):
            lines += [f"- [{label}] {i} {by_id[i]['title']}（{by_id[i].get('points')}pt）→ {by_id[i]['status']}"
                      for i in tds.get(key, []) if i in by_id]
    else:
        lines.append("- 今日の計画なし（プランニング未実施）")
    lines += ["", f"## ベロシティの推移（直近{VELOCITY_DAYS * 2}日）"]
    lines += [f"- {fmt(r['date'])} 約束 {r['committed']:g} → 完了 {r['done']:g}pt（3日平均 {r['avg']:.1f}）"
              for r in daily_rows(ctx["data"], ctx["tasks"])[-VELOCITY_DAYS * 2:]] or ["- 記録なし"]
    done_today = [t for t in ctx["tasks"] if t.get("done_date") == fmt(today)]
    lines += ["", "## 今日完了したタスク（done_date）"] + ([f"- {t['id']} {t['title']}" for t in done_today] or ["- なし"])
    if today.weekday() == 4:
        lines += ["", team_summary(ctx, today), "", improvement_candidates(ctx, today)]
    lines += ["", "## 今日更新されたファイル"] + ([f"- {p}" for p in sorted(touched)] or ["- なし"])
    lines += ["", "## 実施中の Try", tries or "- なし"]
    return "\n".join(lines)


# ---------- main ----------

def validate(data):
    errors = []
    ids = set()
    for t in data.get("tasks", []):
        for key in ("id", "title", "status"):
            if key not in t:
                errors.append(f"{t.get('id', '?')}: '{key}' がありません")
        if t.get("id") in ids:
            errors.append(f"ID が重複しています: {t.get('id')}")
        ids.add(t.get("id"))
        if t.get("status") not in STATUSES:
            errors.append(f"{t.get('id')}: ステータス '{t.get('status')}' は {STATUSES} のいずれかにしてください")
        if t.get("status") == "完了" and not t.get("done_date"):
            errors.append(f"{t.get('id')}: 完了タスクには done_date が必要です")
        if t.get("assignee") == OWNER and t.get("status") != "完了" and t.get("kind") != OWN_KIND:
            if t.get("kind") and t["kind"] not in KINDS:
                errors.append(f"{t.get('id')}: kind '{t['kind']}' は {KINDS} のいずれかにしてください")
            if not t.get("due"):
                errors.append(f"{t.get('id')}: {OWNER_CALL}へのお願いには期日（due）が必要です。{AI_NAME}が期日を決めて入れてください")
            if t.get("kind") in ("申請", "判断", "設定") and not (t.get("steps") or t.get("why")):
                errors.append(f"{t.get('id')}: {OWNER_CALL}への{t['kind']}には steps（手順）か why（理由）が必要です")
        if t.get("reestimate") and t.get("status") in ("作業中", "レビュー", "完了"):
            errors.append(f"{t.get('id')}: 始めたタスクは見積もり直さないでください（reestimate を外し、増えた分は差分タスクとして登録する）")
        for key in ("start", "due", "done_date"):
            try:
                parse_date(t.get(key))
            except ValueError:
                errors.append(f"{t.get('id')}: {key} は YYYY-MM-DD 形式にしてください")
    pts = {t.get("id"): float(t.get("points") or 0) for t in data.get("tasks", [])}
    dates = [ds.get("date") for ds in data.get("daily_sprints", [])]
    for d in sorted({d for d in dates if dates.count(d) > 1}):
        errors.append(f"日次スプリント {d}: 同じ日付の行が複数あります。1日1行にしてください")
    for ds in data.get("daily_sprints", []):
        d = ds.get("date", "?")
        for tid in ds.get("planned", []) + ds.get("added", []) + ds.get("pulled", []):
            if tid not in pts:
                errors.append(f"日次スプリント {d}: 計画のタスク {tid} が tasks にありません")
            elif tid in ids and next(t for t in data["tasks"] if t["id"] == tid).get("assignee") == OWNER:
                errors.append(f"日次スプリント {d}: {tid} は{OWNER_CALL}のタスクなので計画（ポイント）に入れないでください")
        if "committed" in ds and abs(ds["committed"] - sum(pts.get(i, 0) for i in ds.get("planned", []))) > 1e-9:
            errors.append(f"日次スプリント {d}: committed（{ds['committed']}）が計画タスクのポイント合計と一致しません。"
                          "見積もりは計画後に変えないでください（変えた理由があるなら振り返りに書き、committed は計画時のまま）")
    return errors


def run(today):
    data = json.loads(TASKS_JSON.read_text(encoding="utf-8"))
    errors = validate(data)
    if errors:
        raise ValueError("tasks.json の内容に問題があります:\n- " + "\n- ".join(errors))
    record_history(data)
    cal =Calendar(data.get("project", {}).get("holidays", []))
    tasks = data.get("tasks", [])
    velocity, velocity_src = calc_velocity(data, tasks, today, cal)
    tds = today_sprint(data, today)
    planned_today = set(tds.get("planned", []) + tds.get("added", []) + tds.get("pulled", [])) if tds else None
    open_tasks, project_end = forecast(tasks, today, velocity, cal, planned_today)
    events = None
    if calendar_today is not None:
        try:
            events = calendar_today.load_events(ROOT, _cfg, today)
        except Exception:
            events = []
    ctx = dict(data=data, tasks=tasks, today=today, cal=cal, velocity=velocity, velocity_src=velocity_src, events=events,
               open_tasks=open_tasks, project_end=project_end, sprint=current_sprint(data, today),
               now=datetime.now().strftime("%Y-%m-%d %H:%M"))

    wb = Workbook()
    build_dashboard(wb, ctx)
    build_own_sheet(wb, ctx)
    build_requests_sheet(wb, ctx)
    build_daily_sheet(wb, ctx)
    build_task_list(wb, ctx)
    build_gantt(wb, ctx)
    build_sprint_history(wb, ctx)
    try:
        wb.save(XLSX)
        saved_note = ""
    except PermissionError:
        saved_note = "（タスク管理.xlsx が Excel で開かれているため保存できませんでした。閉じてから /status を実行してください）"
    BOARD_MD.write_text(build_board_md(ctx), encoding="utf-8")
    REQUEST_MD.write_text(build_requests_md(ctx), encoding="utf-8")
    return ctx, saved_note


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hook", action="store_true", help="PostToolUse hook として実行")
    ap.add_argument("--session", action="store_true", help="SessionStart hook として実行")
    ap.add_argument("--today", help="基準日 YYYY-MM-DD（試算用）")
    ap.add_argument("--review-context", action="store_true", help="振り返り会議の材料を表示（1行目 OPEN/SKIP）")
    ap.add_argument("--plan-context", action="store_true", help="プランニングの材料を表示（1行目 OPEN/SKIP）")
    ap.add_argument("--today-status", action="store_true", help="今日の日次スプリントの status を表示（なければ空）")
    args = ap.parse_args()
    today = parse_date(args.today) if args.today else date.today()

    if args.hook:
        try:
            payload = json.load(sys.stdin)
        except json.JSONDecodeError:
            return 0
        path = (payload.get("tool_input") or {}).get("file_path", "")
        if not path.endswith("tasks.json") or find_root() is None:
            return 0

    if find_root() is None or not CONFIG_JSON.exists():
        # 本人のフォルダではない、または初回セットアップ前
        if args.session:
            text = (f"[初回セットアップ] このフォルダには本人設定（設定/config.json）がまだありません。"
                    f"共通の指揮官ルール（{RULES_MD}）を読み、最初の返事で初回セットアップを始めてください：本人に名前・呼び方・AI の名前・担当部署・勤務時間・定例業務を聞き、"
                    f"設定/config.json・CLAUDE.md（本人設定）・00_タスク管理/data/tasks.json を作る（/ai-bunshin:setup があればその手順で）。")
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}},
                             ensure_ascii=False))
            return 0
        print("本人のフォルダ（00_タスク管理/data/tasks.json と 設定/config.json）が見つかりません。"
              "本人のフォルダで実行するか、AI_BUNSHIN_HOME を指定してください", file=sys.stderr)
        return 1

    try:
        ctx, note = run(today)
    except (ValueError, json.JSONDecodeError) as e:
        msg = f"ダッシュボード更新に失敗: {e}"
        if args.hook:
            print(msg, file=sys.stderr)
            return 2  # Claude に修正を促す
        print(msg, file=sys.stderr)
        return 1

    if args.today_status:
        print((today_sprint(ctx["data"], today) or {}).get("status", ""))
        return 0
    if args.plan_context:
        print(plan_context(today, ctx["cal"], ctx))
        return 0
    if args.review_context:
        print(review_context(today, ctx["cal"], ctx))
        return 0

    text = summary_text(ctx) + (f"\n{note}" if note else "")
    if args.session:
        # 共通の指揮官ルールは .claude/rules/ai-bunshin-common.md に写す（自動で読み込まれる）
        if sync_rules():
            text = ("[共通ルールが更新されました] .claude/rules/ai-bunshin-common.md を読み直してから作業してください"
                    "（この起動では古い版が読み込まれている可能性があります）\n") + text
    if args.hook or args.session:
        event = "PostToolUse" if args.hook else "SessionStart"
        print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}, ensure_ascii=False))
    else:
        print(text)
        print(f"\n→ {XLSX.relative_to(ROOT)} / {BOARD_MD.relative_to(ROOT)} を更新しました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
