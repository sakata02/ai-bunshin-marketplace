"""使い方の型（config の display）を update_dashboard.py が読むところのテスト（T182① A1・A2）。

- display が無い・空・壊れている・知らない値 → 今と同じ出力（フル）で止まらない。壊れているときだけ案内1行（U08）
- 起動時のまとめの「[見せ方：…]」1行（U11）。警告の行（先頭に足す並び）は動かさない（U12）
- シンプルのお願いの件数：3件か期限超過の全件のうち多いほう（U03）。個別の設定は型より強く、範囲外の値はその項目だけフル（U06・U14）
- お願いの一覧（build_requests_md）・計画の材料（plan_context）・Excel は型で変えない（K4）
一時のフォルダだけで動かす（本物の本人のフォルダには触らない）。`DASH_PATH` で update_dashboard.py を差し替えられる（壊して落ちることの確かめ用）。
使い方：python3 tests/test_display_dashboard.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.abspath(os.path.join(HERE, "..", "scripts"))
SCRIPT = os.environ.get("DASH_PATH") or os.path.join(SCRIPTS, "update_dashboard.py")

BASE = os.path.realpath(tempfile.mkdtemp(prefix="displaychk_"))
FAKE_HOME = os.path.join(BASE, "home")
os.makedirs(FAKE_HOME)
TODAY = "2026-11-06"
OWNER_CALL = "テストさん"
LIST_HINT = f"（一覧：00_タスク管理/{OWNER_CALL}へのお願い.md）"
SIMPLE_LINE = "[見せ方：シンプル（言葉・件数の決まりを守る）]"
FULL_LINE = "[見せ方：フル（今までどおり）]"
BROKEN_LINE = "[見せ方：設定の display.type を読めないので、フルで動いています（simple か full に直してください）]"

_n = [0]
fails = 0
names = []


def case(fn):
    names.append(fn)
    return fn


def request(i, due):
    return {"id": f"R{i}", "title": f"お願い{i}", "status": "ToDo", "assignee": "テスト", "priority": i, "kind": "判断",
            "due": due, "why": "本人しかできない", "steps": ["やる"], "done_when": "終わり", "depends_on": []}


def tasks_with(overdue, upcoming):
    """overdue 件の期限超過のお願い（11/1 より前）と upcoming 件のこれからのお願い（11/9 以降）。"""
    out = []
    for i in range(overdue):
        out.append(request(len(out) + 1, f"2026-10-{20 + i:02d}"))
    for i in range(upcoming):
        out.append(request(len(out) + 1, f"2026-11-{9 + i:02d}"))
    return out


def make_home(display="__absent__", tasks=None, extra=None):
    _n[0] += 1
    home = os.path.join(BASE, f"owner{_n[0]}")
    os.makedirs(os.path.join(home, "設定"))
    os.makedirs(os.path.join(home, "00_タスク管理", "data"))
    cfg = {"owner": "テスト", "owner_call": OWNER_CALL, "ai_name": "テストAI", "departments": ["総務"]}
    if display != "__absent__":
        cfg["display"] = display
    cfg.update(extra or {})
    json.dump(cfg, open(os.path.join(home, "設定", "config.json"), "w", encoding="utf-8"), ensure_ascii=False)
    json.dump({"project": {"name": "テスト", "daily_capacity_default": 1.0, "holidays": []}, "daily_sprints": [],
               "sprints": [], "tasks": tasks if tasks is not None else tasks_with(2, 4)},
              open(os.path.join(home, "00_タスク管理", "data", "tasks.json"), "w", encoding="utf-8"), ensure_ascii=False)
    return home


def run(home, *args):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    env["AI_BUNSHIN_HOME"] = home
    env["HOME"] = FAKE_HOME
    return subprocess.run([sys.executable, SCRIPT, *args, "--today", TODAY], capture_output=True, text=True, cwd=home, env=env)


def session_text(home):
    r = run(home, "--session")
    assert r.returncode == 0, f"終了コード {r.returncode}: {r.stderr[-300:]} {r.stdout[-300:]}"
    text = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "ダッシュボード更新に失敗" not in text, f"テストの材料（tasks.json）が不正: {text[:300]}"
    return text


def req_lines(text):
    """お願いの行（「  - R1 [判断] …」）。"""
    return [l for l in text.splitlines() if l.startswith("  - R")]


def drop(text, line):
    return "\n".join(l for l in text.splitlines() if l != line)


def eq(got, want, label=""):
    assert got == want, f"{label} が違う：期待 {want!r} ／ 実際 {got!r}"


# ---------- 無い・空・壊れている ----------

@case
def absent_display_is_silent_full():
    t = session_text(make_home())
    assert "見せ方" not in t, "display が無いのに「見せ方」の行が出ている"
    eq(len(req_lines(t)), 6, "お願いは全件")
    assert "ほかに" not in t, "全件のはずが「ほかに」が出ている"


@case
def empty_display_is_same_as_absent():
    base = session_text(make_home())
    for empty in ({}, "", None, [], {"overrides": {}}):
        eq(session_text(make_home(empty)), base, f"display={empty!r} の出力")


@case
def broken_display_falls_back_to_full_with_one_notice_line():
    base = session_text(make_home())
    for bad in ({"type": "simpel"}, {"type": "SIMPLE"}, {"type": None}, {"type": 3}, {"type": ["simple"]},
                {"type": ""}, "simple", 5, ["simple"], True,
                {"type": "simpel", "overrides": {"requests_max": 1}}):   # 型が壊れているときは個別の設定も読まず、全部フル
        t = session_text(make_home(bad))
        eq(t.count(BROKEN_LINE), 1, f"display={bad!r} の案内の行の数")
        eq(drop(t, BROKEN_LINE), base, f"display={bad!r}：案内の1行を除くと今と同じ出力")


@case
def broken_display_does_not_stop_hook_and_plain_run():
    home = make_home({"type": "simpel"})
    payload = json.dumps({"tool_input": {"file_path": os.path.join(home, "00_タスク管理", "data", "tasks.json")}})
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    env.update(AI_BUNSHIN_HOME=home, HOME=FAKE_HOME)
    r = subprocess.run([sys.executable, SCRIPT, "--hook", "--today", TODAY], input=payload, capture_output=True, text=True, cwd=home, env=env)
    eq(r.returncode, 0, "hook の終了コード")
    assert BROKEN_LINE in json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    r = run(home)
    eq(r.returncode, 0, "引数なしの実行の終了コード")
    assert "更新しました" in r.stdout, r.stdout[-200:]


# ---------- 型の行（U11）と並び（U12） ----------

@case
def explicit_types_put_one_line_right_after_the_first_line():
    base = session_text(make_home())
    for typ, line in (("simple", SIMPLE_LINE), ("full", FULL_LINE)):
        t = session_text(make_home({"type": typ, "overrides": {}}, tasks=tasks_with(0, 2)))
        lines = t.splitlines()
        i = next(k for k, l in enumerate(lines) if "タスク状況" in l)
        eq(lines[i + 1], line, f"{typ}：まとめの先頭行の次")
        eq(t.count("[見せ方："), 1, f"{typ}：型の行は1行だけ")
    # フルは、型の行を除くと設定が無いときと同じ（お願いが全件出る）
    t = session_text(make_home({"type": "full", "overrides": {}}))
    eq(drop(t, FULL_LINE), base, "フル：型の行を除くと今と同じ")


@case
def warning_lines_stay_in_front_in_the_same_order():
    # 初回の起動では「共通ルールが更新されました」が先頭に付く。型を変えても、この行が先頭のまま・同じ文
    absent = session_text(make_home()).splitlines()
    simple = session_text(make_home({"type": "simple"})).splitlines()
    k = next(i for i, l in enumerate(absent) if "タスク状況" in l)
    assert k >= 1 and "共通ルールが更新されました" in absent[0], f"土台：警告が先頭にない {absent[:2]}"
    eq(simple[:k + 1], absent[:k + 1], "警告の行とまとめの先頭行（同じ文・同じ順）")
    assert simple[k + 1] == SIMPLE_LINE


# ---------- シンプルのお願いの件数（U03） ----------

@case
def simple_shows_three_requests_when_none_overdue():
    t = session_text(make_home({"type": "simple"}, tasks=tasks_with(0, 6)))
    eq([l.split()[1] for l in req_lines(t)], ["R1", "R2", "R3"], "見せるお願い（期日順の先頭3件）")
    assert f"  …ほかに 3 件{LIST_HINT}" in t, "残りの案内が無い"
    assert "未完了 6 件" in t, "見出しの件数は全件のまま"


@case
def simple_shows_all_overdue_even_over_the_cap():
    t = session_text(make_home({"type": "simple"}, tasks=tasks_with(5, 3)))
    eq([l.split()[1] for l in req_lines(t)], ["R1", "R2", "R3", "R4", "R5"], "期限超過5件は上限3を超えても全部")
    assert all("🔴" in l for l in req_lines(t)), "出ているのは全部期限超過"
    assert f"  …ほかに 3 件{LIST_HINT}" in t


@case
def simple_fills_up_to_the_cap_after_overdue():
    t = session_text(make_home({"type": "simple"}, tasks=tasks_with(2, 4)))
    eq([l.split()[1] for l in req_lines(t)], ["R1", "R2", "R3"], "期限超過2件＋残り枠1件")
    assert f"  …ほかに 3 件{LIST_HINT}" in t


@case
def simple_with_few_requests_has_no_more_line():
    t = session_text(make_home({"type": "simple"}, tasks=tasks_with(1, 2)))
    eq(len(req_lines(t)), 3)
    assert "ほかに" not in t, "3件ちょうどなのに「ほかに」が出ている"


@case
def simple_is_shorter_than_full_and_keeps_overdue():
    ts = tasks_with(2, 6)
    full = session_text(make_home({"type": "full"}, tasks=ts))
    simple = session_text(make_home({"type": "simple"}, tasks=ts))
    assert len(simple.encode()) < len(full.encode()), "シンプルの起動時のまとめが、フルより短くない"
    for l in req_lines(full):
        if "🔴" in l:
            assert l in simple, f"期限超過の行が消えた: {l}"


# ---------- 個別の設定（U06・U14） ----------

@case
def requests_max_override_wins_over_type():
    ts = tasks_with(0, 8)
    eq(len(req_lines(session_text(make_home({"type": "simple", "overrides": {"requests_max": 5}}, tasks=ts)))), 5, "シンプル＋5")
    eq(len(req_lines(session_text(make_home({"type": "full", "overrides": {"requests_max": 2}}, tasks=ts)))), 2, "フル＋2")
    eq(len(req_lines(session_text(make_home({"type": "simple", "overrides": {"requests_max": 20}}, tasks=ts)))), 8, "20 は上限の端")
    eq(len(req_lines(session_text(make_home({"type": "simple", "overrides": {"requests_max": 1}}, tasks=ts)))), 1, "1 は下限の端")
    # 上限を超えて少なくしても、期限超過は全部
    t = session_text(make_home({"type": "simple", "overrides": {"requests_max": 1}}, tasks=tasks_with(3, 3)))
    eq(len(req_lines(t)), 3, "上限1でも期限超過3件は全部")


@case
def invalid_requests_max_makes_that_item_full():
    ts = tasks_with(0, 8)
    for bad in (0, 21, -1, "5", True, False, 3.5, None, [3], {"n": 3}):
        t = session_text(make_home({"type": "simple", "overrides": {"requests_max": bad}}, tasks=ts))
        eq(len(req_lines(t)), 8, f"requests_max={bad!r}：その項目はフル（全件）")
        eq(t.count(SIMPLE_LINE), 1, f"requests_max={bad!r}：型はシンプルのまま")


@case
def unknown_override_names_and_shapes_are_ignored():
    ts = tasks_with(0, 8)
    plain = session_text(make_home({"type": "simple", "overrides": {}}, tasks=ts))
    for ov in ({"ng_guard": "off"}, {"ng_guard": "full"}, {"ng_guard": "off", "auto": "full"}, {"terms": "bogus"}, {"terms": 1, "features": None},
               {"Requests_Max": 9}, "requests_max", ["requests_max"], None, 5):
        t = session_text(make_home({"type": "simple", "overrides": ov}, tasks=ts))
        eq(t, plain, f"overrides={ov!r}：何も変わらない")


@case
def overrides_survive_when_type_changes_in_config():
    # 設定の書き換えは set_display.py の仕事。ここでは、型だけが違う2つの設定で個別の設定が同じように効くことを見る
    ts = tasks_with(0, 8)
    a = session_text(make_home({"type": "simple", "overrides": {"requests_max": 4}}, tasks=ts))
    b = session_text(make_home({"type": "full", "overrides": {"requests_max": 4}}, tasks=ts))
    eq(len(req_lines(a)), 4)
    eq(len(req_lines(b)), 4)


# ---------- 件数を絞らないもの・Excel（K4） ----------

@case
def request_list_plan_context_and_excel_are_not_trimmed_by_type():
    ts = tasks_with(2, 6)
    homes = {k: make_home(d, tasks=ts) for k, d in (("absent", "__absent__"), ("simple", {"type": "simple"}),
                                                    ("cap1", {"type": "simple", "overrides": {"requests_max": 1}}))}
    out = {}
    for k, home in homes.items():
        run(home)   # 生成物を作る（お願いの一覧・Excel）
        md = open(os.path.join(home, "00_タスク管理", f"{OWNER_CALL}へのお願い.md"), encoding="utf-8").read()
        ctx = run(home, "--plan-context").stdout
        out[k] = (md, ctx)
        for i in range(1, 9):
            assert f"R{i} " in md or f"| R{i} |" in md, f"{k}：お願いの一覧に R{i} が無い"
            assert f"- R{i} [判断]" in ctx, f"{k}：計画の材料に R{i} が無い"
        assert "見せ方" not in md and "ほかに" not in md, f"{k}：お願いの一覧に型の行・件数の案内が混ざっている"
    # 一覧は、作った時刻の行を除いて同じ
    strip = lambda s: "\n".join(l for l in s.splitlines() if "自動生成" not in l)  # noqa: E731
    eq(strip(out["simple"][0]), strip(out["absent"][0]), "お願いの一覧（シンプル）")
    eq(strip(out["cap1"][0]), strip(out["absent"][0]), "お願いの一覧（上限1）")
    eq(out["simple"][1], out["absent"][1], "計画の材料（シンプル）")
    # Excel：シートの並び・中身は型で変えない
    try:
        import openpyxl
    except ImportError:
        return

    def dump(home):
        wb = openpyxl.load_workbook(os.path.join(home, "00_タスク管理", "タスク管理.xlsx"))
        return {ws.title: [[c.value for c in row] for row in ws.iter_rows()] for ws in wb.worksheets}
    a, s = dump(homes["absent"]), dump(homes["simple"])
    eq(list(s), list(a), "Excel のシートの並び")
    for title in a:
        stripped = lambda rows: [[v for v in r if not (isinstance(v, str) and "自動生成" in v)] for r in rows]  # noqa: E731
        eq(stripped(s[title]), stripped(a[title]), f"Excel「{title}」の中身")


# ---------- 個別の設定を AI に伝える行（U11 を広げた。set_display.py と同じ文面） ----------

OV_PREFIX = "個別の設定（型より優先）："
SET_DISPLAY = os.environ.get("SET_DISPLAY_PATH") or os.path.join(os.path.dirname(SCRIPT), "set_display.py")


def ov_lines(text):
    return [l for l in text.splitlines() if l.startswith(OV_PREFIX)]


@case
def overrides_line_comes_right_before_the_type_line_in_name_order():
    # 並びは決まった名前の順（features・terms・requests_max・stop_notice・review_view・team_view）。config に書いた順ではない
    ov = {"requests_max": 5, "terms": "full", "team_view": "simple"}
    t = session_text(make_home({"type": "simple", "overrides": ov}, tasks=tasks_with(0, 8)))
    lines = t.splitlines()
    i = next(k for k, l in enumerate(lines) if l == SIMPLE_LINE)
    eq(lines[i - 1], OV_PREFIX + "terms=full、requests_max=5、team_view=simple", "型の行のすぐ前の行")
    assert "タスク状況" in lines[i - 2], "その前はまとめの先頭行"
    eq(len(ov_lines(t)), 1, "個別の設定の行は1行だけ")
    t = session_text(make_home({"type": "full", "overrides": {"terms": "simple"}}))
    assert ov_lines(t) == [OV_PREFIX + "terms=simple"], "フルでも、個別の設定があれば出る"


@case
def overrides_line_is_absent_without_valid_overrides():
    for display in ("__absent__", {}, {"type": "simple"}, {"type": "simple", "overrides": {}},
                    {"type": "full", "overrides": {"ng_guard": "full", "auto": "full"}},   # 知らない名前だけ（値は simple／full でも、名前が決まりにない）
                    {"type": "simple", "overrides": {"terms": "bogus", "requests_max": 0}},   # 値が範囲外だけ
                    {"type": "simple", "overrides": "terms"}, {"type": "simpel", "overrides": {"terms": "full"}}):
        t = session_text(make_home(display))
        eq(ov_lines(t), [], f"display={display!r}：個別の設定の行は出ない")
    # 知らない名前が混ざっていても、効くものだけが出る
    t = session_text(make_home({"type": "simple", "overrides": {"ng_guard": "off", "terms": "full", "requests_max": 99}}))
    eq(ov_lines(t), [OV_PREFIX + "terms=full"], "効くものだけ")


@case
def startup_lines_are_identical_to_set_display_output():
    # set_display.py（組②）の実際の出力と、起動時のまとめの「[見せ方：…]」と個別の設定の行が、1文字も違わない（K3）
    home = make_home({"type": "simple", "overrides": {}}, tasks=tasks_with(0, 4))
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "AI_BUNSHIN_AUTO_RUN")}
    env.update(AI_BUNSHIN_HOME=home, HOME=FAKE_HOME)

    def sd(*a):
        r = subprocess.run([sys.executable, SET_DISPLAY, *a], capture_output=True, text=True, cwd=home, env=env)
        assert r.returncode == 0, f"set_display {a}: {r.stderr[-200:]}"
        return r.stdout
    sd("override", "requests_max", "5")
    out = sd("override", "terms", "full")
    startup = session_text(home)
    set_ov = [l for l in out.splitlines() if l.startswith(OV_PREFIX)]
    set_type = [l for l in out.splitlines() if l.startswith("[見せ方：")]
    eq(ov_lines(startup), set_ov, "個別の設定の行")
    eq([l for l in startup.splitlines() if l.startswith("[見せ方：")], set_type, "型の行（simple）")
    eq(set_ov, [OV_PREFIX + "terms=full、requests_max=5"])
    pair = lambda text: [l for l in text.splitlines() if l.startswith((OV_PREFIX, "[見せ方："))]  # noqa: E731
    eq(pair(startup), pair(out), "個別の設定の行 →「[見せ方：…]」の並び（set_display.py と同じ）")
    eq(pair(out)[-1], set_type[0], "「[見せ方：…]」が最後")
    for typ in ("full", "simple"):
        eq([l for l in session_text(make_home({"type": typ})).splitlines() if l.startswith("[見せ方：")],
           [l for l in sd("type", typ).splitlines() if l.startswith("[見せ方：")], f"型の行（{typ}）")
    # 壊れている型の案内も同じ文
    bad = make_home({"type": "simpel"})
    env["AI_BUNSHIN_HOME"] = bad
    shown = subprocess.run([sys.executable, SET_DISPLAY, "show"], capture_output=True, text=True, cwd=bad, env=env).stdout
    eq([l for l in session_text(bad).splitlines() if l.startswith("[見せ方：")],
       [l for l in shown.splitlines() if l.startswith("[見せ方：")], "壊れているときの案内の行")


# ---------- check_config に入れていない（U08） ----------

@case
def display_problems_do_not_enter_check_config():
    sys.path.insert(0, os.path.dirname(SCRIPT))
    home = make_home({"type": "simpel"})
    os.environ["AI_BUNSHIN_HOME"] = home
    os.environ["HOME"] = FAKE_HOME
    sys.modules.pop("update_dashboard", None)
    import update_dashboard as u
    assert u.CONFIG_ERROR is None, f"display の問題で config 全体が止まっている: {u.CONFIG_ERROR}"
    eq(u.check_config({"display": 5, "owner": "x"}), [], "check_config は display を見ない")
    d = u.read_display({"display": {"type": "simple", "overrides": {"requests_max": 7, "terms": "full", "bogus": 1}}})
    eq(d["type"], "simple")
    eq(d["overrides"], {"requests_max": 7, "terms": "full"}, "知らない名前は落とす")
    eq(u.requests_cap(d), 7)
    eq(u.requests_cap(u.read_display({})), None, "無い設定は全件")
    eq(u.requests_cap(u.read_display({"display": {"type": "simple"}})), 3, "シンプルの既定は3")


# ---------- 組⑦a：type が無く個別の設定だけのとき・雛形（K16・K18） ----------

@case
def overrides_only_without_type_ends_with_full_line_like_set_display_show():
    # type が無く、効く個別の設定だけがあるとき：個別の設定の行 →「[見せ方：フル（今までどおり）]」の2行がこの順（K16）。
    # set_display.py の show の出力の同じ2行と、1文字も違わない
    for ov, want in (({"terms": "simple"}, OV_PREFIX + "terms=simple"),
                     ({"requests_max": 5, "terms": "full"}, OV_PREFIX + "terms=full、requests_max=5")):
        home = make_home({"overrides": ov}, tasks=tasks_with(0, 4))
        t = session_text(home)
        lines = t.splitlines()
        i = lines.index(want)
        eq(lines[i + 1], FULL_LINE, "個別の設定の行のすぐ後ろ")
        eq(len(ov_lines(t)), 1, "個別の設定の行は1行だけ")
        eq(len([l for l in lines if l.startswith("[見せ方：")]), 1, "「[見せ方：…]」は1行だけ")
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "AI_BUNSHIN_AUTO_RUN")}
        env.update(AI_BUNSHIN_HOME=home, HOME=FAKE_HOME)
        r = subprocess.run([sys.executable, SET_DISPLAY, "show"], capture_output=True, text=True, cwd=home, env=env)
        assert r.returncode == 0, r.stderr[-200:]
        pair = lambda text: [l for l in text.splitlines() if l.startswith((OV_PREFIX, "[見せ方："))]  # noqa: E731
        eq(pair(t), pair(r.stdout), "set_display.py show と同じ2行・同じ並び")
        eq(pair(r.stdout)[-1], FULL_LINE, "show の最後の「[見せ方：…]」")
    # 個別の設定が無い（空・効かないものだけ）なら、今までどおり何も出さない
    for display in ({"overrides": {}}, {"overrides": {"ng_guard": "full"}}, {"overrides": {"terms": "bogus"}}, {"overrides": "terms"}):
        t = session_text(make_home(display))
        assert "見せ方" not in t, f"display={display!r}：type も効く個別の設定も無いのに「見せ方」の行が出ている"
    # type があるときは今までどおり（その型の行）
    t = session_text(make_home({"type": "simple", "overrides": {"terms": "full"}}))
    lines = t.splitlines()
    eq(lines[lines.index(OV_PREFIX + "terms=full") + 1], SIMPLE_LINE, "type があれば、その型の行")


@case
def template_config_has_no_display_and_startup_stays_silent():
    # 雛形の config.json に display が無い（K18）。その雛形で起動時のまとめに「見せ方」の行が出ない
    tpl_path = os.path.join(HERE, "..", "templates", "config", "config.json")
    tpl = json.load(open(tpl_path, encoding="utf-8"))
    assert "display" not in tpl, "雛形に display が残っている"
    home = make_home()
    cfg = dict(tpl)
    cfg.update(owner="テスト", owner_call=OWNER_CALL, ai_name="テストAI", departments=["総務"])
    json.dump(cfg, open(os.path.join(home, "設定", "config.json"), "w", encoding="utf-8"), ensure_ascii=False)
    t = session_text(home)
    assert "見せ方" not in t, "雛形のままなのに「見せ方」の行が出ている"
    eq(len(req_lines(t)), 6, "雛形のままはフル（お願いは全件）")


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


run_all()
shutil.rmtree(BASE, ignore_errors=True)
print(f"失敗 {fails} 件（{len(names)} 項目）")
sys.exit(1 if fails else 0)
