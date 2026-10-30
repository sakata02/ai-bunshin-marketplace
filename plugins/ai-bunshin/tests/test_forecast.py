"""完了予定日の計算（update_dashboard.py の forecast と営業日の計算）のテスト。
- 前提タスク（depends_on）：優先度の高いタスクが低いタスクに依存していても、前提より先に終わる予定にならない
- 依存の輪（循環）：落ちずに「依存の輪」と出す
- 見積もりの無いタスク：「見積もり待ち」。完了予定日は出さず、全体の完了予定日にも入れない
- 本人のタスク：ポイントを数えない
- 営業日（土日・休日）と --today の指定
実行：python3 tests/test_forecast.py（失敗があれば終了コード1）。本物の tasks.json は使わず、一時フォルダだけで動く"""
import json
import os
import subprocess
import sys
import tempfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.abspath(os.path.join(HERE, "..", "scripts"))
SCRIPT = os.path.join(SCRIPTS, "update_dashboard.py")

# 本人のフォルダ（一時）。本物のフォルダには触らない
BASE = os.path.realpath(tempfile.mkdtemp(prefix="forecastchk_"))
HOME_DIR = os.path.join(BASE, "owner")
os.makedirs(os.path.join(HOME_DIR, "設定"))
os.makedirs(os.path.join(HOME_DIR, "00_タスク管理", "data"))
FAKE_HOME = os.path.join(BASE, "home")
os.makedirs(FAKE_HOME)
json.dump({"owner": "テスト", "owner_call": "テストさん", "ai_name": "テストAI", "departments": ["総務"]},
          open(os.path.join(HOME_DIR, "設定", "config.json"), "w", encoding="utf-8"), ensure_ascii=False)
json.dump({"project": {"name": "テスト", "daily_capacity_default": 1.0, "holidays": []}, "daily_sprints": [], "sprints": [], "tasks": []},
          open(os.path.join(HOME_DIR, "00_タスク管理", "data", "tasks.json"), "w", encoding="utf-8"), ensure_ascii=False)
os.environ["AI_BUNSHIN_HOME"] = HOME_DIR
os.environ["HOME"] = FAKE_HOME
sys.path.insert(0, SCRIPTS)
import update_dashboard as u  # noqa: E402

OWNER = "テスト"
MON = date(2026, 11, 2)   # 月曜
D = lambda d: date(2026, 11, d)  # noqa: E731


def T(id, prio, pts, deps=(), assignee="dev-a", status="ToDo", **kw):
    t = {"id": id, "title": f"タスク{id}", "status": status, "assignee": assignee, "priority": prio, "depends_on": list(deps)}
    if pts is not None:
        t["points"] = pts
    t.update(kw)
    return t


def run_fc(tasks, velocity=1.0, today=MON, holidays=(), planned=None):
    cal = u.Calendar([h for h in holidays])
    open_tasks, end = u.forecast(tasks, today, velocity, cal, planned)
    return {t["id"]: t for t in tasks}, end


fails = 0
names = []


def case(fn):
    names.append(fn)
    return fn


def run_all():
    global fails
    for fn in names:
        try:
            fn()
        except AssertionError as e:
            fails += 1
            print(f"[{fn.__name__}] {e}")
        except Exception as e:  # noqa: BLE001  落ちたことも失敗として数える
            fails += 1
            print(f"[{fn.__name__}] 例外で落ちた: {type(e).__name__}: {e}")


def eq(got, want, label=""):
    assert got == want, f"{label} が違う：期待 {want} ／ 実際 {got}"


# ---------- 土台 ----------

@case
def base_priority_order():
    by, end = run_fc([T("A", 1, 1), T("B", 2, 1), T("C", 3, 1)])
    eq([by[i]["_forecast"] for i in "ABC"], [D(2), D(3), D(4)], "優先順に積む")
    eq(end, D(4), "全体の完了予定日")


@case
def done_dependency_does_not_block():
    by, _ = run_fc([T("A", 1, 1, deps=["Z"]), T("Z", 9, 1, status="完了", done_date="2026-10-20")])
    eq(by["A"]["_forecast"], D(2), "完了済みの前提は待たない")


# ---------- 依存 ----------

@case
def dep_high_priority_depends_on_low():
    # 優先度1の H が、優先度2の L に依存。L が先に終わり、H はその後。関係ない Q（優先度3）は、H と L の後
    by, end = run_fc([T("H", 1, 1, deps=["L"]), T("L", 2, 1), T("Q", 3, 1)])
    eq(by["L"]["_forecast"], D(2), "前提 L")
    eq(by["H"]["_forecast"], D(3), "依存する H は前提の翌営業日")
    eq(by["Q"]["_forecast"], D(4), "関係ない Q はあと")
    eq(end, D(4), "全体")


@case
def dep_bigger_task_waits_for_prerequisite():
    # H は 2pt（2日分）。L（1pt）が月曜に終わるので、H は火曜から2日 → 水曜
    by, _ = run_fc([T("H", 1, 2, deps=["L"]), T("L", 2, 1)])
    eq(by["L"]["_forecast"], D(2), "前提 L")
    eq(by["H"]["_forecast"], D(4), "2日分の H")


@case
def dep_three_levels_reverse_priority():
    # A(優先1)→B(優先2)→C(優先3) の順に依存。実際に終わる順は C → B → A
    by, end = run_fc([T("A", 1, 1, deps=["B"]), T("B", 2, 1, deps=["C"]), T("C", 3, 1)])
    eq([by[i]["_forecast"] for i in "CBA"], [D(2), D(3), D(4)], "C→B→A")
    assert by["A"]["_forecast"] > by["B"]["_forecast"] > by["C"]["_forecast"], "前提より先に終わる予定になっている"
    eq(end, D(4), "全体")


@case
def dep_three_levels_with_gap_unrelated_in_between():
    # 関係ない X（優先2）が間にあっても、依存の列（A→B→C）は崩れない
    by, _ = run_fc([T("A", 1, 1, deps=["B"]), T("X", 2, 1), T("B", 3, 1, deps=["C"]), T("C", 4, 1)])
    assert by["C"]["_forecast"] < by["B"]["_forecast"] < by["A"]["_forecast"], \
        f"C→B→A の順になっていない {[by[i]['_forecast'] for i in 'CBA']}"
    # 優先度の高い A の列（C,B,A）が先、X はあと
    eq(by["X"]["_forecast"], D(5), "X は依存の列のあと")


@case
def dep_on_owner_task_waits_for_its_due():
    # 本人のタスク（期日 11/6 金）に依存する AI のタスクは、その翌営業日（11/9 月）以降
    by, _ = run_fc([T("A", 1, 1, deps=["O"]), T("O", 2, 1, assignee=OWNER, due="2026-11-06", kind="確認")])
    eq(by["O"]["_forecast"], D(6), "本人のタスクは期日")
    eq(by["A"]["_forecast"], D(9), "本人の作業の後")


@case
def dep_on_unknown_id_is_ignored():
    by, _ = run_fc([T("A", 1, 1, deps=["T999"])])
    eq(by["A"]["_forecast"], D(2), "存在しない前提は無視")


# ---------- 依存の輪 ----------

@case
def cycle_does_not_crash_and_is_labeled():
    by, end = run_fc([T("A", 1, 1, deps=["B"]), T("B", 2, 1, deps=["A"]), T("C", 3, 1)])
    for i in "AB":
        assert "依存の輪" in by[i]["_flag"], f"{i} の表示が「依存の輪」でない: {by[i]['_flag']}"
        assert by[i]["_forecast"] is None, f"{i} に完了予定日が出ている"
    eq(by["C"]["_forecast"], D(2), "輪の外の C は普通に積む")
    eq(end, D(2), "全体の完了予定日に輪の中を入れない")


@case
def cycle_of_three_and_self_dependency():
    by, _ = run_fc([T("A", 1, 1, deps=["C"]), T("B", 2, 1, deps=["A"]), T("C", 3, 1, deps=["B"]), T("S", 4, 1, deps=["S"]), T("Z", 5, 1)])
    for i in "ABCS":
        assert "依存の輪" in by[i]["_flag"], f"{i}: {by[i]['_flag']}"
    eq(by["Z"]["_forecast"], D(2), "Z")


@case
def downstream_of_cycle_is_not_scheduled():
    by, _ = run_fc([T("A", 1, 1, deps=["B"]), T("B", 2, 1, deps=["A"]), T("D", 3, 1, deps=["A"])])
    assert by["D"]["_forecast"] is None, "輪に依存する D に完了予定日が出ている"
    assert "依存の輪" in by["D"]["_flag"], by["D"]["_flag"]


# ---------- 見積もり待ち ----------

@case
def no_estimate_is_waiting():
    by, end = run_fc([T("W", 1, None), T("X", 2, 1)])
    assert by["W"]["_forecast"] is None, f"見積もりの無い W に完了予定日が出ている: {by['W']['_forecast']}"
    assert "見積もり待ち" in by["W"]["_flag"], by["W"]["_flag"]
    assert "順調" not in by["W"]["_flag"], by["W"]["_flag"]
    eq(by["X"]["_forecast"], D(2), "見積もりの無いタスクは場所を取らない")
    eq(end, D(2), "全体の完了予定日に入れない")


@case
def no_estimate_null_and_missing_key_are_both_waiting():
    by, _ = run_fc([T("N", 1, None, points=None), T("M", 2, None), T("Z", 3, 0)])
    for i in "NM":
        assert "見積もり待ち" in by[i]["_flag"], f"{i}: {by[i]['_flag']}"
    assert "見積もり待ち" not in by["Z"]["_flag"], "0pt は見積もり済み（見積もり待ちにしない）"


@case
def only_waiting_tasks_means_no_overall_date():
    by, end = run_fc([T("W", 1, None)])
    eq(end, None, "全体の完了予定日")


@case
def waiting_with_due_date_keeps_overdue_alert():
    by, _ = run_fc([T("W", 1, None, due="2026-10-30")])
    assert "期限超過" in by["W"]["_flag"], by["W"]["_flag"]
    assert by["W"]["_forecast"] is None, "見積もりの無い W に完了予定日が出ている"


@case
def dependent_of_waiting_task_is_also_waiting():
    by, end = run_fc([T("D", 1, 1, deps=["W"]), T("W", 2, None), T("X", 3, 1)])
    assert by["D"]["_forecast"] is None, "見積もり待ちに依存する D に完了予定日が出ている"
    assert "見積もり待ち" in by["D"]["_flag"], by["D"]["_flag"]
    eq(by["X"]["_forecast"], D(2), "X")
    eq(end, D(2), "全体")


@case
def done_task_without_points_is_not_waiting():
    by, _ = run_fc([T("A", 1, None, status="完了", done_date="2026-10-30"), T("B", 2, 1)])
    eq(by["A"]["_forecast"], date(2026, 10, 30), "完了済みは完了日")
    assert "見積もり待ち" not in by["A"]["_flag"]


# ---------- 本人のタスク ----------

@case
def owner_tasks_are_not_counted():
    by, end = run_fc([T("O", 1, 5, assignee=OWNER, due="2026-11-03", kind="確認"), T("A", 2, 1)])
    eq(by["A"]["_forecast"], D(2), "本人の 5pt は AI の積み上げに入らない")
    eq(by["O"]["_forecast"], D(3), "本人のタスクは期日が完了予定")


@case
def owner_task_without_points_is_not_waiting():
    by, _ = run_fc([T("O", 1, None, assignee=OWNER, due="2026-11-03", kind="確認")])
    assert "見積もり待ち" not in by["O"]["_flag"], by["O"]["_flag"]
    eq(by["O"]["_forecast"], D(3), "本人のタスクは期日")


# ---------- 営業日 ----------

@case
def workdays_skip_weekend():
    cal = u.Calendar([])
    eq(cal.add_workdays(date(2026, 10, 30), 2), D(2), "金曜から2営業日目（金・月）")
    eq(cal.add_workdays(date(2026, 10, 31), 1), D(2), "土曜から1営業日目は月曜")
    eq(cal.add_workdays(date(2026, 11, 1), 1), D(2), "日曜から1営業日目は月曜")
    eq(cal.add_workdays(MON, 0), MON, "n が 0 以下は開始日以降の最初の営業日")
    eq(cal.add_workdays(date(2026, 10, 31), 0), D(2), "土曜で n=0 は月曜")


@case
def workdays_skip_holidays():
    cal = u.Calendar(["2026-11-03", "2026-11-04"])   # 火・水が休み
    eq(cal.add_workdays(MON, 2), D(5), "月・（休・休）・木 で2営業日目は木曜")
    eq(cal.is_workday(D(3)), False, "休日は営業日でない")
    eq(cal.workdays_between(MON, D(8)), 3, "月〜日の営業日数（月・木・金）")
    eq(cal.workdays_between(D(5), MON), 0, "終わりが始めより前なら 0")


@case
def forecast_crosses_weekend_and_holiday():
    tasks = [T("A", 1, 1), T("B", 2, 1), T("C", 3, 1)]
    by, _ = run_fc(tasks, today=D(5), holidays=["2026-11-09"])  # 木曜から。金曜のあと土日、月曜（休）、火曜
    eq([by[i]["_forecast"] for i in "ABC"], [D(5), D(6), D(10)], "木・金・（土日休）火")


@case
def velocity_two_points_per_day():
    by, _ = run_fc([T("A", 1, 1), T("B", 2, 1), T("C", 3, 1)], velocity=2.0)
    eq([by[i]["_forecast"] for i in "ABC"], [D(2), D(2), D(3)], "1日 2pt")


# ---------- 基準日と今日の計画 ----------

@case
def today_parameter_moves_the_start():
    by_mon, _ = run_fc([T("A", 1, 1)], today=MON)
    by_sat, _ = run_fc([T("A", 1, 1)], today=date(2026, 11, 7))   # 土曜が基準日 → 月曜
    eq(by_mon["A"]["_forecast"], D(2), "月曜")
    eq(by_sat["A"]["_forecast"], D(9), "土曜が基準日なら次の月曜")


@case
def planned_today_tasks_finish_today_others_next_workday():
    by, _ = run_fc([T("A", 1, 1), T("B", 2, 1)], today=D(6), planned={"A"})   # 金曜、A だけ今日の計画
    eq(by["A"]["_forecast"], D(6), "今日の計画は今日")
    eq(by["B"]["_forecast"], D(9), "計画の外は翌営業日（月曜）から")


# ---------- 画面の文言（全体の完了予定日・見積もり待ち）と --today の指定 ----------

def write_tasks(tasks, capacity=1.0):
    json.dump({"project": {"name": "テスト", "daily_capacity_default": capacity, "holidays": []}, "daily_sprints": [], "sprints": [], "tasks": tasks},
              open(os.path.join(HOME_DIR, "00_タスク管理", "data", "tasks.json"), "w", encoding="utf-8"), ensure_ascii=False)


def run_cli(*args):
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR",)}
    env["AI_BUNSHIN_HOME"] = HOME_DIR
    env["HOME"] = FAKE_HOME
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, cwd=HOME_DIR, env=env)


@case
def cli_today_option_and_waiting_message():
    write_tasks([T("T001", 1, 1, department="総務"), T("T002", 2, None, department="総務"), T("T003", 3, 1, department="総務")])
    r = run_cli("--today", "2026-11-06")   # 金曜
    assert r.returncode == 0, f"終了コード {r.returncode}: {r.stderr[:300]}"
    out = r.stdout
    assert "タスク状況 2026-11-06" in out, "--today の日付が出ていない"
    assert "T001" in out and "完了予定 11/6(金)" in out, "金曜が基準日で T001 は 11/6(金)"
    assert "T003" in out and "完了予定 11/9(月)" in out, "T003 は翌営業日の 11/9(月)"
    line2 = next(l for l in out.splitlines() if "T002" in l)
    assert "見積もり待ち" in line2, f"T002 の行に「見積もり待ち」が無い: {line2}"
    assert "順調" not in line2 and "11/" not in line2.split("→")[-1], f"T002 に完了予定日が出ている: {line2}"
    head = out.splitlines()[0]
    assert "全体完了予定 11/9(月)" in head, f"全体の完了予定日（見積もり待ちを入れない）が違う: {head}"
    assert "見積もり待ちが1件あります" in head, f"「見積もり待ちが1件あります」が添えられていない: {head}"
    board = open(os.path.join(HOME_DIR, "00_タスク管理", "タスクボード.md"), encoding="utf-8").read()
    assert "見積もり待ちが1件あります" in board, "タスクボードに見積もり待ちの添え書きが無い"


@case
def cli_cycle_prints_warning_and_does_not_crash():
    write_tasks([T("T001", 1, 1, deps=["T002"], department="総務"), T("T002", 2, 1, deps=["T001"], department="総務"),
                 T("T003", 3, 1, department="総務")])
    r = run_cli("--today", "2026-11-02")
    assert r.returncode == 0, f"輪があると終了コード {r.returncode}: {r.stderr[:300]}"
    assert "依存の輪" in r.stdout, f"依存の輪の表示が無い: {r.stdout[:400]}"
    assert "T001" in r.stdout.split("依存の輪")[1] or "T001" in r.stdout, "輪の中の ID が出ていない"


@case
def cli_all_estimated_has_no_waiting_message():
    write_tasks([T("T001", 1, 1, department="総務")])
    r = run_cli("--today", "2026-11-02")
    assert r.returncode == 0, r.stderr[:300]
    assert "見積もり待ち" not in r.stdout and "依存の輪" not in r.stdout, "見積もり待ち・依存の輪が無いのに添え書きが出ている"
    assert "全体完了予定 11/2(月)" in r.stdout.splitlines()[0], r.stdout.splitlines()[0]


# ---------- 追加（部下D の確かめへの直し） ----------

def line_of(out, tid):
    return next(l for l in out.splitlines() if f" {tid} " in l)


@case
def cli_session_summary_has_no_id_lines_but_plain_and_board_do():
    write_tasks([T("T001", 1, 1, department="総務"), T("T002", 2, None, department="総務"),
                 T("T003", 3, 1, deps=["T004"], department="総務"), T("T004", 4, 1, deps=["T003"], department="総務")])
    r = run_cli("--today", "2026-11-02", "--session")
    assert r.returncode == 0, r.stderr[:300]
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "⚠ 見積もり待ち" not in ctx and "輪になっています" not in ctx, "起動時のまとめに ID 付きの ⚠ 行が出ている"
    head = next(l for l in ctx.splitlines() if "タスク状況" in l)   # 共通ルール更新の案内が先に付くことがあるので、まとめの先頭の行を探す
    assert "見積もり待ちが1件あります" in head and "依存の輪が2件あります" in head, f"先頭の行に件数が無い: {head}"
    plain = run_cli("--today", "2026-11-02").stdout
    assert "⚠ 見積もり待ち 1件：T002" in plain, "引数なしの状態表示に ID 付きの行が無い"
    assert "⚠ 前提のタスクが輪になっています（T003→T004→T003）" in plain, "引数なしの状態表示に依存の輪の行が無い"
    board = open(os.path.join(HOME_DIR, "00_タスク管理", "タスクボード.md"), encoding="utf-8").read()
    assert "⚠ 見積もり待ち 1件：T002" in board and "T003→T004→T003" in board, "タスクボードに ID 付きの行が無い"


@case
def hook_summary_has_no_id_lines():
    write_tasks([T("T001", 1, 1, department="総務"), T("T002", 2, None, department="総務")])
    payload = json.dumps({"tool_input": {"file_path": os.path.join(HOME_DIR, "00_タスク管理", "data", "tasks.json")}})
    env = dict(os.environ, AI_BUNSHIN_HOME=HOME_DIR, HOME=FAKE_HOME)
    r = subprocess.run([sys.executable, SCRIPT, "--hook", "--today", "2026-11-02"], input=payload, capture_output=True, text=True,
                       cwd=HOME_DIR, env=env)
    assert r.returncode == 0, r.stderr[:300]
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "⚠ 見積もり待ち" not in ctx and "見積もり待ちが1件あります" in ctx, "hook の出力：ID 付きの行は出さず、件数だけ"


@case
def planned_today_but_no_estimate_is_waiting():
    by, end = run_fc([T("A", 1, None), T("B", 2, 1, deps=["A"]), T("C", 3, 1)], today=D(6), planned={"A", "C"})
    assert by["A"]["_forecast"] is None and "見積もり待ち" in by["A"]["_flag"], f"今日の計画にある見積もり無しの A: {by['A']['_flag']} {by['A']['_forecast']}"
    assert by["B"]["_forecast"] is None and "見積もり待ち" in by["B"]["_flag"], "A に依存する B"
    eq(by["C"]["_forecast"], D(6), "計画にあって見積もりのある C は今日")
    eq(end, D(6), "全体")


@case
def depends_on_null_and_wrong_types_do_not_crash():
    by, end = run_fc([T("TA", 1, 1, depends_on=None), T("TB", 2, 1, depends_on="TA"), T("TC", 3, 1, depends_on=5),
                      T("TD", 4, 1, depends_on={"x": 1}), T("TE", 5, 1)])
    eq(by["TA"]["_forecast"], D(2), "null は前提なし")
    for i in ("TB", "TC", "TD"):
        assert by[i]["_forecast"] is None and "見積もり待ち" in by[i]["_flag"], f"{i}: 書き方が違うタスクは見積もり待ち {by[i]['_flag']}"
    eq(by["TE"]["_forecast"], D(3), "ほかのタスクは普通に積む")
    lines = "\n".join(u.unscheduled_lines([by[i] for i in ("TA", "TB", "TC", "TD", "TE")]))
    for i in ("TB", "TC", "TD"):
        assert i in lines, f"{i} の警告が出ていない: {lines}"
    assert "TA" not in lines and "TE" not in lines, f"問題の無いタスクが警告に出ている: {lines}"


@case
def points_text_empty_and_list_are_handled():
    by, end = run_fc([T("TA", 1, "abc"), T("TB", 2, ""), T("TC", 3, "3"), T("TD", 4, [1]), T("TE", 5, 1)], velocity=1.0)
    for i in ("TA", "TB", "TD"):
        assert by[i]["_forecast"] is None and "見積もり待ち" in by[i]["_flag"], f"{i}: {by[i]['_flag']}"
    eq(by["TC"]["_forecast"], D(4), "数字の文字 '3' は 3pt")
    eq(by["TE"]["_forecast"], D(5), "TE は TC の後")
    lines = "\n".join(u.unscheduled_lines([by[i] for i in ("TA", "TB", "TC", "TD", "TE")]))
    assert "TA" in lines and "TD" in lines, f"数でない points の警告が出ていない: {lines}"
    assert "TC" not in lines and "TE" not in lines, f"問題の無いタスクが警告に出ている: {lines}"


@case
def cli_points_text_does_not_crash():
    write_tasks([T("T001", 1, "abc", department="総務"), T("T002", 2, "", department="総務"), T("T003", 3, 1, department="総務")])
    r = run_cli("--today", "2026-11-02")
    assert r.returncode == 0, f"points が文字で終了コード {r.returncode}: {r.stderr[:400]}"
    assert "T001" in r.stdout and "見積もり待ち" in line_of(r.stdout, "T001") and "見積もり待ち" in line_of(r.stdout, "T002")
    assert "全体完了予定 11/2(月)（見積もり待ちが2件あります）" in r.stdout.splitlines()[0], r.stdout.splitlines()[0]


@case
def long_chain_does_not_hit_recursion_limit():
    n = 1100
    tasks = [T(f"T{i:04d}", i, 1, deps=[f"T{i + 1:04d}"] if i < n else []) for i in range(1, n + 1)]
    by, end = run_fc(tasks, velocity=1000.0)
    assert by["T1100"]["_forecast"] < by["T0001"]["_forecast"], "1100段の鎖：いちばん奥の前提が先に終わる予定になっていない"
    assert all(by[f"T{i:04d}"]["_forecast"] is not None for i in range(1, n + 1)), "鎖の途中に予定が出ないものがある"


@case
def prerequisite_is_lifted_to_the_priority_of_its_dependent():
    # H（優先1）は L（優先3）に依存。X（優先2）は無関係。L は H と同じ優先度まで繰り上がるので、L → H → X の順
    by, _ = run_fc([T("H", 1, 1, deps=["L"]), T("X", 2, 1), T("L", 3, 1)])
    eq([by[i]["_forecast"] for i in "LHX"], [D(2), D(3), D(4)], "L→H→X")


@case
def wording_no_duplicate_no_english_and_loop_shows_path():
    write_tasks([T("T001", 1, None, department="総務"), T("T002", 2, 1, deps=["T003"], department="総務"),
                 T("T003", 3, 1, deps=["T002"], department="総務"), T("T004", 4, 1, deps=["T002"], department="総務")])
    out = run_cli("--today", "2026-11-02").stdout
    l1 = line_of(out, "T001")
    assert l1.count("見積もり待ち") == 1, f"一覧で「見積もり待ち」が重なっている: {l1}"
    l2 = line_of(out, "T002")
    assert l2.count("依存の輪") == 1, f"一覧で「依存の輪」が重なっている: {l2}"
    assert "前提のタスクが輪になっています（T002→T003→T002）。前提を見直してください" in out, f"輪の中身の行が違う: {out}"
    for bad in ("points", "depends_on"):
        assert bad not in "\n".join(l for l in out.splitlines() if l.startswith("[⚠ 見積もり") or l.startswith("[⚠ 前提")
                                    or l.startswith("[⚠ 依存") or "輪" in l), f"括弧の英語 {bad} が文言に残っている"
    board = open(os.path.join(HOME_DIR, "00_タスク管理", "タスクボード.md"), encoding="utf-8").read()
    assert "T002→T003→T002" in board, "タスクボードに輪の中身が無い"
    assert board.count("| ⏳ 見積もり待ち |") == 1 and "| 見積もり待ち | ⏳" not in board, "ボードの表で「見積もり待ち」が重なっている"

run_all()
print(f"失敗 {fails} 件（{len(names)} 項目）")
sys.exit(1 if fails else 0)
