"""右のパネルのガントチャート用の元データ（forecast.json と着手見込み `_start`）のテスト（T118）。
- D1：update_dashboard.py が動くたびに 00_タスク管理/data/forecast.json を書く（作った時刻・今日・ベロシティ・タスク・見積もり待ちの件数）。一時ファイルを残さない
- D2：着手見込み `_start`（前のタスクまでの積み上げから出す。前提があれば前提の完了予定の翌営業日より前にしない。今日の計画は今日）。完了予定日 `_forecast` は変えない
- D5：今日から14日ぶんの日付と、休みの判定（土日・休日。update_dashboard.py の Calendar と同じ）
- D8（元データ側）：不正な tasks.json のときは forecast.json を書き換えない／書けなくても、ほかの生成物は更新される
実行：python3 tests/test_forecast_file.py（失敗があれば終了コード1）。本物の tasks.json は使わず、一時フォルダだけで動く"""
import json
import os
import subprocess
import sys
import tempfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.abspath(os.path.join(HERE, "..", "scripts"))
SCRIPT = os.path.join(SCRIPTS, "update_dashboard.py")

BASE = os.path.realpath(tempfile.mkdtemp(prefix="forecastfile_"))
FAKE_HOME = os.path.join(BASE, "home")
os.makedirs(FAKE_HOME)


def make_home(name):
    """本人のフォルダ（一時）を作って、そのパスを返す。本物のフォルダには触らない"""
    home = os.path.join(BASE, name)
    os.makedirs(os.path.join(home, "設定"))
    os.makedirs(os.path.join(home, "00_タスク管理", "data"))
    json.dump({"owner": "テスト", "owner_call": "テストさん", "ai_name": "テストAI", "departments": ["総務"]},
              open(os.path.join(home, "設定", "config.json"), "w", encoding="utf-8"), ensure_ascii=False)
    json.dump({"project": {"name": "テスト", "daily_capacity_default": 1.0, "holidays": []}, "daily_sprints": [], "sprints": [], "tasks": []},
              open(os.path.join(home, "00_タスク管理", "data", "tasks.json"), "w", encoding="utf-8"), ensure_ascii=False)   # 本人のフォルダの目印
    return home


HOME_DIR = make_home("owner")
os.environ["AI_BUNSHIN_HOME"] = HOME_DIR
os.environ["HOME"] = FAKE_HOME
sys.path.insert(0, SCRIPTS)
import update_dashboard as u  # noqa: E402

OWNER = "テスト"
MON = date(2026, 11, 2)   # 月曜
FRI = date(2026, 11, 6)   # 金曜
D = lambda d: date(2026, 11, d)  # noqa: E731


def data_dir(home=HOME_DIR):
    return os.path.join(home, "00_タスク管理", "data")


def T(id, prio, pts, deps=(), assignee="dev-a", status="ToDo", **kw):
    t = {"id": id, "title": f"タスク{id}", "status": status, "assignee": assignee, "priority": prio, "depends_on": list(deps),
         "department": "総務"}
    if pts is not None:
        t["points"] = pts
    t.update(kw)
    return t


def run_fc(tasks, velocity=1.0, today=MON, holidays=(), planned=None):
    cal = u.Calendar(list(holidays))
    u.forecast(tasks, today, velocity, cal, planned)
    return {t["id"]: t for t in tasks}


def write_tasks(tasks, capacity=1.0, holidays=(), home=HOME_DIR):
    json.dump({"project": {"name": "テスト", "daily_capacity_default": capacity, "holidays": list(holidays)},
               "daily_sprints": [], "sprints": [], "tasks": tasks},
              open(os.path.join(data_dir(home), "tasks.json"), "w", encoding="utf-8"), ensure_ascii=False)


def run_cli(*args, home=HOME_DIR):
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR",)}
    env["AI_BUNSHIN_HOME"] = home
    env["HOME"] = FAKE_HOME
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, cwd=home, env=env)


def fc_path(home=HOME_DIR):
    return os.path.join(data_dir(home), "forecast.json")


def load_fc(home=HOME_DIR):
    return json.load(open(fc_path(home), encoding="utf-8"))


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
        except Exception as e:  # noqa: BLE001
            fails += 1
            print(f"[{fn.__name__}] 例外で落ちた: {type(e).__name__}: {e}")


def eq(got, want, label=""):
    assert got == want, f"{label} が違う：期待 {want} ／ 実際 {got}"


# ---------- D2：着手見込み ----------

@case
def start_follows_the_previous_tasks():
    # ベロシティ1：A(1pt)→B(2pt)→C(1pt)。B は A が終わった翌日から、C は B が終わった翌日から
    by = run_fc([T("A", 1, 1), T("B", 2, 2), T("C", 3, 1)])
    eq([by[i]["_start"] for i in "ABC"], [D(2), D(3), D(5)], "着手見込み")
    eq([by[i]["_forecast"] for i in "ABC"], [D(2), D(4), D(5)], "完了予定（今までどおり）")


@case
def start_can_share_a_day_when_velocity_is_bigger():
    # ベロシティ2：A(1pt) は半日ぶん。B(3pt) は同じ日に続きから始め、2日目に終わる
    by = run_fc([T("A", 1, 1), T("B", 2, 3)], velocity=2.0)
    eq(by["B"]["_start"], D(2), "B の着手見込み（A と同じ日）")
    eq(by["B"]["_forecast"], D(3), "B の完了予定")


@case
def start_skips_weekend_and_holiday():
    by = run_fc([T("A", 1, 1), T("B", 2, 1)], today=FRI)
    eq((by["A"]["_start"], by["B"]["_start"]), (D(6), D(9)), "金曜から数えると B は月曜")
    by = run_fc([T("A", 1, 1), T("B", 2, 1)], today=MON, holidays=["2026-11-03"])
    eq((by["B"]["_start"], by["B"]["_forecast"]), (D(4), D(4)), "11/3 が休みなら B は 11/4")


@case
def start_not_before_the_day_after_the_prerequisite():
    # X は本人の作業 O（期日 11/10）に依存。積み上げでは 11/2 に着手できるが、O の翌営業日（11/11）より前にしない
    by = run_fc([T("X", 1, 1, deps=["O"]), T("O", 2, 1, assignee=OWNER, due="2026-11-10", kind="判断")])
    eq(by["X"]["_start"], D(11), "前提の翌営業日")
    eq(by["X"]["_forecast"], D(11), "完了予定（今までどおり）")
    # 前提が AI のタスクのとき：優先度の高い H が低い L に依存 → L が先、H は L の翌日
    by = run_fc([T("H", 1, 1, deps=["L"]), T("L", 2, 1)])
    eq((by["L"]["_start"], by["H"]["_start"]), (D(2), D(3)), "L→H")


@case
def start_is_today_for_todays_plan():
    by = run_fc([T("A", 1, 1), T("B", 2, 1), T("C", 3, 1)], planned={"B"})
    eq((by["B"]["_start"], by["B"]["_forecast"]), (MON, MON), "今日の計画のタスクは今日")
    eq(by["A"]["_start"], D(3), "計画に入っていないものは翌営業日から")


@case
def start_is_none_for_owner_and_unschedulable_and_never_after_end():
    tasks = [T("A", 1, 1), T("W", 2, None), T("L1", 3, 1, deps=["L2"]), T("L2", 4, 1, deps=["L1"]),
             T("O", 5, 1, assignee=OWNER, due="2026-11-05", kind="確認"),
             T("Z", 6, 0), T("B", 7, 3, deps=["A"])]
    by = run_fc(tasks)
    for i in ("W", "L1", "L2", "O"):
        eq(by[i]["_start"], None, f"{i} の着手見込み")
    eq(by["O"]["_forecast"], D(5), "本人のタスクは期日のまま")
    for i in ("A", "Z", "B"):
        ok = by[i]["_start"] is not None and MON <= by[i]["_start"] <= by[i]["_forecast"]
        assert ok, f"{i} の着手見込みが完了予定より後: {by[i]['_start']} {by[i]['_forecast']}"


@case
def forecast_values_unchanged_by_start():
    # 着手見込みを足しても、完了予定日は今までの計算のまま（手計算した値）
    by = run_fc([T("A", 1, 2), T("B", 2, 1, deps=["A"]), T("C", 3, 3), T("D", 4, 1)], velocity=2.0)
    eq([by[i]["_forecast"] for i in "ABCD"], [D(2), D(3), D(4), D(5)], "完了予定")


# ---------- D1・D5：forecast.json ----------

@case
def file_is_written_with_the_planned_shape():
    write_tasks([T("T001", 1, 1), T("T002", 2, None), T("T003", 3, 2, deps=["T001"]),
                 T("T004", 4, 1, assignee=OWNER, due="2026-11-09", kind="判断", why="本人だけが決められる"),
                 T("T005", 5, 1, status="完了", done_date="2026-11-02"),
                 T("T006", 6, 1, deps=["T007"]), T("T007", 7, 1, deps=["T006"])])
    r = run_cli("--today", "2026-11-06", "--now", "2026-11-06 09:30")
    assert r.returncode == 0, f"終了コード {r.returncode}: {r.stderr[:300]}"
    f = load_fc()
    eq(sorted(f), ["days", "made", "tasks", "today", "velocity", "waiting"], "最上位のキー")
    eq(f["today"], "2026-11-06", "今日")
    eq(f["made"], "2026-11-06 09:30", "作った時刻")
    assert isinstance(f["velocity"], (int, float)) and f["velocity"] > 0, f"ベロシティ: {f['velocity']}"
    eq(f["waiting"], 1, "見積もり待ちの件数")
    ids = [t["id"] for t in f["tasks"]]
    assert "T005" not in ids, "完了したタスクが入っている"
    eq(ids, ["T001", "T002", "T003", "T004", "T006", "T007"], "未完了のタスクが順位の順")
    by = {t["id"]: t for t in f["tasks"]}
    eq(sorted(by["T001"]), ["assignee", "end", "id", "start", "state", "title", "who"], "タスクのキー")
    eq((by["T001"]["who"], by["T001"]["assignee"], by["T001"]["title"]), ("AI", "dev-a", "タスクT001"), "T001")
    eq((by["T001"]["start"], by["T001"]["end"]), ("2026-11-06", "2026-11-06"), "T001 の着手・完了")
    eq((by["T003"]["start"], by["T003"]["end"]), ("2026-11-09", "2026-11-10"), "T003（前提あり・週末をまたぐ）")
    eq((by["T004"]["who"], by["T004"]["start"], by["T004"]["end"]), ("本人", None, "2026-11-09"), "本人のタスクは期日")
    eq((by["T002"]["state"], by["T002"]["start"], by["T002"]["end"]), ("見積もり待ち", None, None), "見積もり待ち")
    eq((by["T006"]["state"], by["T006"]["end"]), ("依存の輪", None), "依存の輪")
    assert by["T001"]["state"] in ("順調", "納期なし"), f"状態の言葉: {by['T001']['state']}"


@case
def state_words_match_the_dashboard():
    write_tasks([T("T001", 1, 1, due="2026-11-05"),                 # 期限超過
                 T("T002", 2, 1, due="2026-11-09"),                 # 順調
                 T("T003", 3, 3, due="2026-11-09"),                 # 遅延見込み
                 T("T004", 4, 1)])                                  # 納期なし
    run_cli("--today", "2026-11-06")
    by = {t["id"]: t["state"] for t in load_fc()["tasks"]}
    eq(by, {"T001": "期限超過", "T002": "順調", "T003": "遅延見込み", "T004": "納期なし"}, "状態の言葉（ダッシュボードの旗と同じ。絵文字なし）")


@case
def days_are_14_calendar_days_with_off_days():
    write_tasks([T("T001", 1, 1)], holidays=["2026-11-10"])
    run_cli("--today", "2026-11-06")
    days = load_fc()["days"]
    eq(len(days), 14, "日数")
    eq(days[0]["date"], "2026-11-06", "最初の日は今日")
    eq(days[-1]["date"], "2026-11-19", "最後の日")
    off = [d["date"] for d in days if d["off"]]
    eq(off, ["2026-11-07", "2026-11-08", "2026-11-10", "2026-11-14", "2026-11-15"], "休みの日（土日と、休日に入れた 11/10）")
    cal = u.Calendar(["2026-11-10"])
    for d in days:
        eq(d["off"], not cal.is_workday(u.parse_date(d["date"])), f"{d['date']} の判定が Calendar と同じ")


@case
def no_tmp_left_and_rewritten_each_run():
    write_tasks([T("T001", 1, 1)])
    run_cli("--today", "2026-11-06", "--now", "2026-11-06 09:00")
    run_cli("--today", "2026-11-06", "--now", "2026-11-06 09:05")
    eq(load_fc()["made"], "2026-11-06 09:05", "動くたびに作り直す")
    left = [n for n in os.listdir(data_dir()) if n.endswith(".tmp") or (n.startswith("forecast") and n != "forecast.json")]
    eq(left, [], "一時ファイルが残っていない")


# ---------- D8 の元データ側 ----------

@case
def invalid_tasks_json_keeps_the_old_file():
    write_tasks([T("T001", 1, 1)])
    run_cli("--today", "2026-11-06", "--now", "2026-11-06 09:00")
    before = open(fc_path(), encoding="utf-8").read()
    write_tasks([T("T001", 1, 1), T("T001", 2, 1)])   # ID の重複 → 検査で止まる
    r = run_cli("--today", "2026-11-06", "--now", "2026-11-06 09:30")
    assert r.returncode != 0, "壊れた tasks.json なのに成功した"
    eq(open(fc_path(), encoding="utf-8").read(), before, "検査で止まったら forecast.json は書き換えない")


@case
def write_failure_does_not_stop_the_other_outputs():
    home = make_home("blocked")
    write_tasks([T("T001", 1, 1)], home=home)
    os.mkdir(fc_path(home))   # forecast.json の場所をフォルダにして、置き換えられなくする（別の一時フォルダの中だけ）
    r = run_cli("--today", "2026-11-06", home=home)
    assert r.returncode == 0, f"書けないだけで止まった: {r.returncode} {r.stderr[:300]}"
    board = open(os.path.join(home, "00_タスク管理", "タスクボード.md"), encoding="utf-8").read()
    assert "T001" in board, "タスクボードが更新されていない"
    eq([n for n in os.listdir(data_dir(home)) if n.endswith(".tmp")], [], "一時ファイルが残っていない")


# ---------- D9：控えに入れない ----------

@case
def gitignore_template_ignores_forecast_json():
    tpl = os.path.join(HERE, "..", "templates", "gitignore.txt")
    lines = [l.strip() for l in open(tpl, encoding="utf-8").read().splitlines()]
    assert "00_タスク管理/data/forecast.json" in lines, "雛形の .gitignore に forecast.json が無い"
    # 実際に Git が無視するか（別の一時フォルダの中だけ）
    repo = os.path.join(BASE, "gitchk")
    os.makedirs(os.path.join(repo, "00_タスク管理", "data"))
    subprocess.run(["git", "init", "-q", repo], check=True, capture_output=True)
    open(os.path.join(repo, ".gitignore"), "w", encoding="utf-8").write(open(tpl, encoding="utf-8").read())
    r = subprocess.run(["git", "-C", repo, "check-ignore", "00_タスク管理/data/forecast.json"], capture_output=True, text=True)
    eq(r.returncode, 0, "git check-ignore の終了コード（0 なら無視される）")
    r = subprocess.run(["git", "-C", repo, "check-ignore", "00_タスク管理/data/tasks.json"], capture_output=True, text=True)
    eq(r.returncode, 1, "tasks.json は無視されない")

run_all()
print(f"失敗 {fails} 件（{len(names)} 項目）")
sys.exit(1 if fails else 0)
