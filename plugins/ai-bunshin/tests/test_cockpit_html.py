"""コックピットの HTML（scripts/cockpit_html.py。デスクトップ版のタスク表）のテスト（T196b）。
- B1'：全部の欄（tasks.json・forecast.json・config・予定・Try）に <script> などを入れても、出力に生のまま出ない（属性の中も）。使うタグ・属性も決まったものだけ
- B2'：パネルのテスト（plugins/ai-bunshin/register.test.tsx）の主な5つの入力と期待を、値のまま写して、同じ並び・同じ言葉になること
    T191 の grouped／カテゴリ（C1・C2）／T189 カテゴリ／今日の予定：time_unknown／ガント：期限を過ぎた本人
- B3：forecast.json が古い・無い・壊れている → パネルと同じ案内の1行。ガント以外は出る
- B4：本人のフォルダでないときは書かない／出力先は固定（引数で変えられない）／読むだけ（入力を書き換えない）／一時ファイルを残さない
- K3''：今日は日本時間（UTC の日付ではない）。K4：外の読み込みなし・JavaScript なし・CSP・色は変数だけ
パネルを変えたら、このテストも見る。本物の本人のフォルダは使わない（一時フォルダだけ）。
実行：python3 tests/test_cockpit_html.py（失敗があれば終了コード1）"""
import hashlib
import html
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.abspath(os.path.join(HERE, "..", "scripts", "cockpit_html.py"))
spec = importlib.util.spec_from_file_location("cockpit_html", SCRIPT)
CH = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CH)

BASE = os.path.realpath(tempfile.mkdtemp(prefix="cockpit_html_"))
fails = 0
counter = [0]
NOW = datetime(2026, 11, 2, 10, 0)      # 日本時間の「いま」。パネルのテストと同じ 2026-11-02 10:00
TODAY = "2026-11-02"
CFG = {"owner": "山田", "owner_call": "山田さん", "calendar": {"type": "ics"}}


def case(fn):
    global fails
    try:
        fn()
        print(f"  ok   {fn.__name__}")
    except AssertionError as e:
        fails += 1
        print(f"  FAIL {fn.__name__}: {e}")
    except Exception as e:  # noqa: BLE001
        fails += 1
        print(f"  FAIL {fn.__name__}: {e.__class__.__name__}: {e}")
    return fn


def eq(a, b, msg=""):
    assert a == b, f"{msg}: 期待 {b!r} ／ 実際 {a!r}"


# ---------- 土台：一時の本人のフォルダ ----------

def wjson(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False))


def make_home(tasks=None, cfg=CFG, cal=None, forecast="none", log=None, sprints=None, tasks_raw=None):
    """本人のフォルダ（一時）を作る。tasks_raw があれば tasks.json の中身を文字でそのまま入れる。None 以外の forecast・cal・log も書く。
    forecast="none" は「ファイルを作らない」"""
    counter[0] += 1
    home = os.path.join(BASE, f"home{counter[0]}")
    wjson(os.path.join(home, "設定", "config.json"), cfg)
    data = os.path.join(home, "00_タスク管理", "data")
    wjson(os.path.join(data, "tasks.json"),
          tasks_raw if tasks_raw is not None else {"tasks": tasks or [], "daily_sprints": sprints or []})
    if forecast != "none":
        wjson(os.path.join(data, "forecast.json"), forecast)
    if cal is not None:
        wjson(os.path.join(data, "calendar_cache.json"), cal)
    if log is not None:
        wjson(os.path.join(home, "04_ナレッジ", "改善ログ.md"), log)
    return home


def page(home, now=NOW):
    """HTML の文字を作る（ファイルには書かない）。"""
    from pathlib import Path
    h = Path(home)
    cfg = CH._read_config(h / "設定" / "config.json")
    return CH.render(CH.load_context(h, cfg, now))


def sec(out, sid):
    """<section id=sid> の中身。無ければ None。"""
    m = re.search(rf'<section class="sec" id="{sid}">(.*?)</section>', out, re.S)
    return m.group(1) if m else None


def un(s):
    return html.unescape(s)


def h2s(out):
    return [un(x) for x in re.findall(r"<h2>(.*?)</h2>", out)]


TOKEN = re.compile(r'<h3[^>]*>(.*?)</h3>|<span class="id">(.*?)</span>|<p class="more">(.*?)</p>|<p class="empty">(.*?)</p>')


def shape(s):
    """区切りの中を、小見出し（◇ …）・行の ID・「ほか N 件」・空の文の並びにする。"""
    return [un(next(g for g in m.groups() if g is not None)) for m in TOKEN.finditer(s)]


ROW = re.compile(r'<li class="row[^"]*"><span class="(?:mark[^"]*|nomark)">(.*?)</span><span class="id">(.*?)</span>'
                 r'<span class="title">(.*?)(?: <span class="who">・(.*?)</span>)?</span><span class="due">(.*?)</span></li>')


def rows(s):
    return [{"mark": un(m[0]), "id": un(m[1]), "title": un(m[2]), "who": un(m[3]), "due": un(m[4])} for m in ROW.findall(s)]


def line(r):
    """パネルの行と同じ形の文字：[印] ID 題名（期日）。期日は 今日・済 のときは出ない（行の作り側で決まっている）。"""
    return (f"[{r['mark']}] " if r["mark"] else "") + f"{r['id']} {r['title']}" + (f"・{r['who']}" if r["who"] else "") + r["due"]


# ---------- パネルのテストの入力（plugins/ai-bunshin/register.test.tsx から値のまま写す） ----------

def gx(id_, title, **over):
    d = {"id": id_, "title": title, "assignee": "山田", "status": "ToDo", "priority": int(id_[1:])}
    d.update(over)
    return d


GROUPED = {
    "tasks": [
        gx("T001", "期限切れ・分類なし", due="2026-11-01"),
        gx("T002", "期限切れ・A", due="2026-11-01", category="A案件"),
        gx("T003", "今日・B", due="2026-11-02", category="B案件"),
        gx("T004", "今日・A", due="2026-11-02", category="A案件"),
        gx("T005", "ルール変更の承認（1件）", due="2026-11-02", category="C案件"),
        gx("T011", "計画 1", assignee="dev-a", category="B案件", status="完了"),
        gx("T012", "計画 2", assignee="dev-a", category="A案件"),
        gx("T013", "計画 3", assignee="dev-a", category="B案件"),
        gx("T021", "次 1", assignee="dev-a"),
        gx("T022", "次 2", assignee="dev-a", category="A案件"),
        gx("T023", "次 3", assignee="dev-a", category="A案件"),
        gx("T024", "次 4", assignee="dev-a", category="B案件"),
        gx("T025", "次 5", assignee="dev-a", category="A案件"),
        gx("T026", "次 6", assignee="dev-a", category="B案件"),
        gx("T027", "次 7", assignee="dev-a", category="C案件"),
        gx("T028", "次 8", assignee="dev-a", category="C案件"),
        gx("T031", "近 1", due="2026-11-03", category="A案件"),
        gx("T032", "近 2", due="2026-11-04", category="B案件"),
        gx("T033", "近 3", due="2026-11-05", category="A案件"),
    ],
    "daily_sprints": [{"date": TODAY, "planned": ["T011", "T012", "T013"]}],
}
CAL_OK = {"fetched": "2026-11-02 09:00", "events": []}


def ct(id_, title, priority, category=None, status="ToDo"):
    d = {"id": id_, "title": title, "status": status, "assignee": "dev-a"}
    if priority is not None:
        d["priority"] = priority
    if category is not None:
        d["category"] = category
    return d


MIX = [
    ct("T001", "手前の仕事", 5, "A案件"),
    ct("T002", "分類なし1", 1),
    ct("T003", "B の先頭", 2, "B案件"),
    ct("T004", "A の2つめ", 6, "A案件"),
    ct("T005", "C の先頭", 3, "C案件"),
    ct("T006", "B の2つめ", 9, "B案件"),
    ct("T007", "完了A", None, "A案件", "完了"),
    ct("T008", "完了なし", None, None, "完了"),
]

GDAYS = [{"date": (datetime(2026, 11, 2) + timedelta(days=i)).strftime("%Y-%m-%d"),
          "off": (datetime(2026, 11, 2) + timedelta(days=i)).weekday() >= 5} for i in range(14)]


def ft(id_, title, who, start, end, state="順調"):
    return {"id": id_, "title": title, "who": who, "start": start, "end": end, "state": state}


def fc_file(tasks, **over):
    d = {"made": "2026-11-02 09:00", "today": TODAY, "velocity": 2, "days": GDAYS, "tasks": tasks,
         "waiting": len([t for t in tasks if t["state"] == "見積もり待ち"])}
    d.update(over)
    return d


def gt(id_, priority, category=None):
    d = {"id": id_, "title": f"題{id_}", "priority": priority, "status": "ToDo", "assignee": "dev-a"}
    if category is not None:
        d["category"] = category
    return d


# ---------- B2'：パネルのテストの写し ----------

@case
def b2_T191_grouped_4_sections():
    out = page(make_home(GROUPED["tasks"], cal=CAL_OK, sprints=GROUPED["daily_sprints"]))
    # 区切りの見出しと順（パネルの順から、本人の今日まで → 予定 → 近いうちに（左）・AI（右）に並べ替えている。言葉は同じ）
    eq([h for h in h2s(out) if not h.startswith(("これから2週間", "全部のタスク"))],
       ["山田さん（今日まで）", "今日の予定（09:00 取得）", "近いうちに（山田さん）", "AI（今日の計画）", "AI（これから）"], "見出し")
    # 今日まで：承認（C）が一番上 → C が最初のカテゴリ。ほかは A・B の順。未分類（T001 は期日が一番早いが）は最後
    eq(shape(sec(out, "mine")), ["◇ C案件", "T005", "◇ A案件", "T002", "T004", "◇ B案件", "T003", "◇ 未分類", "T001"], "今日まで")
    # 今日の計画：B → A（計画の並びで最初に出た順）。B の中は T011・T013 のまま
    eq(shape(sec(out, "plan")), ["◇ B案件", "T011", "T013", "◇ A案件", "T012"], "今日の計画")
    # これから：先に 6 件で切ってから分ける（T027・T028 は出ない）。未分類（T021 が先頭）は最後
    eq(shape(sec(out, "next")), ["◇ A案件", "T022", "T023", "T025", "◇ B案件", "T024", "T026", "◇ 未分類", "T021", "ほか 2 件"], "これから")
    eq(shape(sec(out, "soon")), ["◇ A案件", "T031", "T033", "◇ B案件", "T032"], "近いうちに")


@case
def b2_T191_row_shapes_and_marks():
    out = page(make_home(GROUPED["tasks"], cal=CAL_OK, sprints=GROUPED["daily_sprints"]))
    mine = [line(r) for r in rows(sec(out, "mine"))]
    assert "[承認] T005 ルール変更の承認（1件）（11/2）" in mine, mine
    assert "[超過] T002 期限切れ・A（11/1）" in mine, mine
    assert "[今日] T004 今日・A" in mine, mine           # 今日のときは期日を出さない
    assert "[済] T011 計画 1" in [line(r) for r in rows(sec(out, "plan"))]
    assert "[ToDo] T022 次 2" in [line(r) for r in rows(sec(out, "next"))]
    assert "T031 近 1（11/3）" in [line(r) for r in rows(sec(out, "soon"))]   # 近いうちは印なし → 期日付き
    assert 'class="row is-apv"' in sec(out, "mine") and "is-done" in sec(out, "plan")
    # お願い 残り：本人の未完了で kind が「自分」でない（T001〜T005・T031〜T033 の 8 件）
    assert '<span class="req">お願い 残り 8 件</span>' in out, "お願いの件数"


@case
def b2_T191_empty_and_single_category_and_plain():
    d = [gx("T001", "A のみ", assignee="dev-a", category="A案件")]
    out = page(make_home(d, cal=CAL_OK))
    eq(shape(sec(out, "mine")), ["なし"], "今日まで")
    eq(shape(sec(out, "plan")), ["計画なし"], "今日の計画")
    eq(shape(sec(out, "next")), ["◇ A案件", "T001"], "これから")
    eq(shape(sec(out, "soon")), ["なし"], "近いうちに")
    # 区切りの中が全部「未分類」なら小見出しなし。1つでもカテゴリがあればその区切りだけ小見出し付き（未分類も最後に付く）
    plain = [gx("T001", "本人 1", due="2026-11-02"), gx("T002", "本人 2", due="2026-11-01"),
             gx("T011", "計画 1", assignee="dev-a"), gx("T012", "計画 2", assignee="dev-a"),
             gx("T021", "次 1", assignee="dev-a"), gx("T022", "次 2", assignee="dev-a"),
             gx("T031", "近 1", due="2026-11-03"), gx("T032", "近 2", due="2026-11-04", category="  ")]
    sp = [{"date": TODAY, "planned": ["T011", "T012"]}]
    out = page(make_home(plain, cal=CAL_OK, sprints=sp))
    assert "◇" not in "".join(sec(out, s) for s in ("mine", "plan", "next", "soon")), "小見出しが出た"
    eq(shape(sec(out, "mine")), ["T002", "T001"], "今日まで")
    eq(shape(sec(out, "plan")), ["T011", "T012"], "今日の計画")
    eq(shape(sec(out, "next")), ["T021", "T022"], "これから")
    eq(shape(sec(out, "soon")), ["T031", "T032"], "近いうちに")
    plain[3] = gx("T012", "計画 2", assignee="dev-a", category="A案件")
    out = page(make_home(plain, cal=CAL_OK, sprints=sp))
    eq(shape(sec(out, "plan")), ["◇ A案件", "T012", "◇ 未分類", "T011"], "1つだけカテゴリあり")
    eq(shape(sec(out, "mine")), ["T002", "T001"], "ほかの区切りはそのまま")


@case
def b2_category_C1_C2_all_list():
    out = page(make_home(MIX))
    s = sec(out, "all")
    heads = [un(x) for x in re.findall(r"<h3>(.*?)</h3>", s)] + [un(x) for x in re.findall(r"<summary>(.*?)</summary>", s)]
    # B（順位2）→ C（3）→ A（5）→ 未分類 → 完了
    eq(heads, ["■ B案件（2）", "■ C案件（1）", "■ A案件（2）", "■ 未分類（1）", "■ 完了（2）"], "見出し")
    rs = rows(s)
    eq([r["id"] for r in rs], ["T003", "T006", "T005", "T001", "T004", "T002", "T008", "T007"], "ID の並び（完了は新しい順）")
    assert "[ToDo] T003 B の先頭・dev-a" in [line(r) for r in rs]
    assert "[済] T008 完了なし・dev-a" in [line(r) for r in rs]
    # C2：見出しの件数の合計は全件。二重・漏れなし。見出しの「全部のタスク N 件（未完了 M）」と合う
    eq(sum(int(x) for x in re.findall(r"（(\d+)）", "".join(heads))), len(MIX), "件数の合計")
    assert "全部のタスク 8 件（未完了 6）" in h2s(out)
    assert "<details class=\"done\">" in s and "<details class=\"done\" open" not in s, "完了は閉じた <details>"


@case
def b2_category_C1_weird_values_are_uncategorized():
    d = [ct("T001", "a", 1, ""), ct("T002", "b", 2, "  "), ct("T003", "c", 3, 7), ct("T004", "d", 4, None),
         ct("T005", "e", 5, [1]), ct("T006", "f", 6, {"a": 1}), ct("T007", "g", 7, True), ct("T008", "h", 8, " A案件 ")]
    d[3].pop("category", None)
    out = page(make_home(d))
    heads = [un(x) for x in re.findall(r"<h3>(.*?)</h3>", sec(out, "all"))]
    eq(heads, ["■ A案件（1）", "■ 未分類（7）"], "前後の空白は除く・文字でないものは未分類")
    # 完了は、カテゴリがあっても全部まとめて最後に1つ。未完了が 0 件でも落ちない
    d2 = [ct("T001", "x", None, "A案件", "完了"), ct("T002", "y", None, None, "完了")]
    s = sec(page(make_home(d2)), "all")
    eq(re.findall(r"<summary>(.*?)</summary>", s), ["■ 完了（2）"], "完了だけ")
    assert "<h3>" not in s


@case
def b2_category_C2_order_stable_for_equal_or_missing_priority():
    d = [ct("T010", "a", 1, "A案件"), ct("T009", "b", 1, "B案件"), ct("T020", "c", None, "C案件"), ct("T005", "d", None, "D案件")]
    out = page(make_home(d))
    # 順位が同じなら ID の順（T009 < T010）→ B が先。順位なしは最後（同じ順位なしは ID の順）
    eq([un(x) for x in re.findall(r"<h3>(.*?)</h3>", sec(out, "all"))], ["■ B案件（1）", "■ A案件（1）", "■ D案件（1）", "■ C案件（1）"])


def gantt_ids(out):
    return [un(x) for x in re.findall(r'<div class="glabel"><span class="id">(.*?)</span>', sec(out, "gantt"))]


@case
def b2_T189_gantt_categories():
    # 順位：T301=1(A)、T201=2(B)、T202=3(B)、T302=4(カテゴリなし)。T400=0(C・forecast に無い)。T303 は tasks.json に無い
    data = [gt("T400", 0, "C案件"), gt("T301", 1, "A案件"), gt("T201", 2, "B案件"), gt("T202", 3, "B案件"), gt("T302", 4)]
    own = lambda k: ft(f"T20{k}", f"題T20{k}", "本人", None, "2026-11-04")   # noqa: E731
    ai = lambda k: ft(f"T30{k}", f"題T30{k}", "AI", "2026-11-02", "2026-11-04")   # noqa: E731
    tasks = [ai(2), own(1), ai(1), ai(3), own(2)]       # forecast の順：T302・T201・T301・T303・T202
    out = page(make_home(data, forecast=fc_file(tasks)))
    g = sec(out, "gantt")
    # 全部の一覧と同じ順（C は順位 0 で先だが、描く棒が無いので出ない）
    eq([un(x) for x in re.findall(r'<h3 class="ghead">(.*?)</h3>', g)], ["■ A案件（1）", "■ B案件（2）", "■ 未分類（2）"], "見出し")
    eq(gantt_ids(out), ["T301", "T201", "T202", "T302", "T303"], "中は forecast の順。引けない T303 は未分類")
    # 全部の一覧は C が先（順位 0）
    eq([un(x) for x in re.findall(r"<h3>■ (.*?)（", sec(out, "all"))], ["C案件", "A案件", "B案件", "未分類"])
    # 印：AI は棒、本人は ◆
    assert re.search(r'T301.*?class="cells"[^>]*>(?:<span class="[^"]*"></span>)*<span class="[^"]*bar', g, re.S)
    assert "◆" in g


@case
def b2_T189_gantt_all_uncategorized_one_heading():
    data = [gt("T201", 1, ""), gt("T202", 2, "  "), gt("T203", 3, 7), gt("T301", 4, None)]
    tasks = [ft(f"T20{k}", "o", "本人", None, "2026-11-04") for k in (1, 2, 3)] + [ft("T301", "a", "AI", "2026-11-02", "2026-11-03"),
                                                                                   ft("T309", "a", "AI", "2026-11-02", "2026-11-03")]
    out = page(make_home(data, forecast=fc_file(tasks)))
    eq([un(x) for x in re.findall(r'<h3 class="ghead">(.*?)</h3>', sec(out, "gantt"))], ["■ 未分類（5）"])


@case
def b2_time_unknown_calendar_events():
    cal = {"fetched": "2026-11-02 09:00", "events": [
        {"date": "2026-11-02", "start": "", "end": "", "title": "時刻不明の会議", "allday": False, "time_unknown": True},
        {"date": "2026-11-02", "start": "13:00", "end": "14:00", "title": "ふつうの会議", "allday": False},
        {"date": "2026-11-02", "start": "", "end": "", "title": "終日の予定", "allday": True},
        {"date": "2026-11-03", "start": "", "end": "", "title": "明日の不明", "allday": False, "time_unknown": True}]}
    out = page(make_home(cal=cal))
    s = sec(out, "cal")
    got = [(un(a), un(b)) for a, b in re.findall(r"<li><time>(.*?)</time><span>(.*?)</span></li>", s)]
    eq(got, [("時刻不明", "時刻不明の会議"), ("13:00〜14:00", "ふつうの会議"), ("終日", "終日の予定")], "予定（ファイルの並びのまま。明日の分は出ない）")
    assert "明日の不明" not in out
    assert "<h2>今日の予定（09:00 取得）</h2>" in s


@case
def b2_gantt_overdue_owner_not_drawn_only_counted():
    tasks = [ft("T501", "期限切れ1", "本人", None, "2026-11-01"),
             ft("T502", "期限切れ2", "本人", None, "2026-10-20", "期限超過"),
             ft("T503", "今日が期日", "本人", None, "2026-11-02"),
             ft("T504", "AI の作業", "AI", "2026-11-02", "2026-11-03")]
    out = page(make_home(forecast=fc_file(tasks)))
    g = sec(out, "gantt")
    eq(gantt_ids(out), ["T503", "T504"], "行にできるのは T503・T504")
    assert '<p class="callout">期限超過 2 件（山田さん・今日より前）</p>' in g, "凡例の上に件数"
    assert g.index("期限超過 2 件") < g.index('class="legend"'), "見出しの下・凡例の前"
    # T503（今日が期日）は左端（今日の列）に ◆
    r503 = re.search(r'T503.*?<span class="cells" aria-hidden="true">(.*?)</span></div>', g, re.S).group(1)
    assert r503.startswith('<span class="today own">◆</span>'), r503[:80]
    # 0 件なら出さない
    out0 = page(make_home(forecast=fc_file([tasks[2], tasks[3]])))
    assert "期限超過" not in out0


@case
def gantt_cells_boundaries():
    # パネルのテスト「ガント（境目）」と同じ入力。今日は 11/2（月）。14 日目＝11/15
    last = GDAYS[13]["date"]
    mk = lambda t: CH.gantt_cells(t, GDAYS)    # noqa: E731
    m, b = mk(ft("T401", "x", "AI", "2026-11-13", last))
    eq(([i for i, x in enumerate(m) if x == "bar"], b), ([11], False), "14日目に終わる AI（13日・金だけ。土日は休み）")
    m, b = mk(ft("T402", "x", "本人", None, last))
    eq(([i for i, x in enumerate(m) if x == "own"], b), ([13], False), "14日目が期日")
    m, b = mk(ft("T403", "x", "AI", "2026-11-13", "2026-11-16"))
    eq(([i for i, x in enumerate(m) if x == "bar"], b), ([11], True), "15日目に終わる AI → 先")
    m, b = mk(ft("T404", "x", "本人", None, "2026-11-16"))
    eq(([x for x in m if x == "own"], b), ([], True), "15日目が期日：印なし・→")
    m, b = mk(ft("T405", "x", "本人", None, "2026-11-02"))
    eq(([i for i, x in enumerate(m) if x == "own"], b), ([0], False), "1日目（今日）が期日")
    m, b = mk(ft("T406", "x", "AI", "2026-11-03", "2026-11-06"))
    eq([i for i, x in enumerate(m) if x == "bar"], [1, 2, 3, 4], "月→金。休みの前で終わる")
    m, b = mk(ft("T407", "x", "AI", "2026-11-05", "2026-11-10"))
    eq([i for i, x in enumerate(m) if x == "bar"], [3, 4, 7, 8], "木・金・（土日は飛ばす）・月・火")


@case
def gantt_row_html_arrow_and_axis():
    last = GDAYS[13]["date"]
    tasks = [ft("T401", "x", "AI", "2026-11-13", last), ft("T403", "x", "AI", "2026-11-13", "2026-11-16"),
             ft("T404", "x", "本人", None, "2026-11-16"), ft("T402", "x", "本人", None, last)]
    out = page(make_home(forecast=fc_file(tasks)))
    g = sec(out, "gantt")
    cells = re.findall(r'<span class="cells" aria-hidden="true">(.*?)</span></div>', g, re.S)
    # 先頭は日付の行（今日・曜日つき）。続く4つが T401・T403・T404・T402
    assert "<span>今日</span>" in cells[0] and "<span>火</span>" in cells[0]
    arrows = [("→" in c.split('<span class="beyond">')[-1]) for c in cells[1:]]
    eq(arrows, [False, True, True, False], "→ は 15 日目以降だけ")
    assert cells[4].count("◆") == 1 and cells[3].count("◆") == 0
    assert "これから2週間（11/2〜11/15）" in h2s(out)
    assert g.count('class="today') >= 2


@case
def gantt_waiting_and_loop_and_empty():
    tasks = [ft("T1", "a", "AI", "2026-11-02", "2026-11-03"), ft("T2", "b", "AI", None, None, "見積もり待ち"),
             ft("T3", "c", "AI", None, None, "見積もり待ち"), ft("T4", "d", "AI", None, None, "依存の輪")]
    out = page(make_home(forecast=fc_file(tasks)))
    assert '<p class="more">見積もり待ち 2・依存の輪 1（棒なし）</p>' in sec(out, "gantt")
    out = page(make_home(forecast=fc_file([ft("T2", "b", "AI", None, None, "見積もり待ち")])))
    g = sec(out, "gantt")
    assert "棒にできるタスクなし" in g and '<p class="more">見積もり待ち 1（棒なし）</p>' in g
    out = page(make_home(forecast=fc_file([])))
    g = sec(out, "gantt")
    assert "棒にできるタスクなし" in g and 'class="more"' not in g


@case
def gantt_waiting_uses_file_count_and_loop_task_has_no_bar():
    # 見積もり待ちの件数は forecast.json の waiting のまま（tasks に待ちが2件あっても 5）
    tasks = [ft("T1", "a", "AI", "2026-11-02", "2026-11-03"), ft("T2", "b", "AI", None, None, "見積もり待ち"),
             ft("T3", "c", "AI", None, None, "見積もり待ち")]
    g = sec(page(make_home(forecast=fc_file(tasks, waiting=5))), "gantt")
    assert '<p class="more">見積もり待ち 5（棒なし）</p>' in g, g
    # 依存の輪のタスクは、開始・終了があっても棒に出さず、件数だけ
    out = page(make_home(forecast=fc_file([ft("T9", "x", "AI", "2026-11-02", "2026-11-04", "依存の輪")])))
    g = sec(out, "gantt")
    assert '<span class="id">T9</span>' not in g, "依存の輪の T9 が棒に出た"
    assert '<p class="more">依存の輪 1（棒なし）</p>' in g, g


# ---------- Try ----------

LOG_HEAD = "| ID | 良くするもの（プラグイン／チーム／人間側） | 内容 | 確かめ方 | 開始日 |\n|---|---|---|---|---|\n"
LOG_ROWS = [
    "| Y20261106-2 | チーム・プラグイン | （ベロシティ。畳んで作り方を変える）正の表を作る。行＝決定ごと | 次の仕事で手戻りが0回 | 2026-11-09 |",
    "| Y20261106-3 | チーム | （ベロシティ）5pt 以上は数えてから出す | 1回に出した量が上限の中 | 2026-11-09 |",
    "| Y20261106-1 | チーム・プラグイン | 外のリポジトリで作業するときは先に聞く | 聞いたことが do_log に1行ある | 2026-11-06 |",
]


def log_of(rows=LOG_ROWS, before="", after="## 定着したルール\n\n| ID | ルール |\n|---|---|\n| Y20261101-9 | 定着した分 |\n"):
    return f"# 改善ログ\n\n> 注記\n\n{before}## 実施中の Try\n\n{LOG_HEAD}" + "\n".join(rows) + f"\n\n{after}"


def try_lines(out):
    s = sec(out, "try")
    if s is None:
        return None
    return [(un(a), un(b), un(c)) for a, b, c in re.findall(r'<li class="row">(?:<span class="mark">(.*?)</span>|<span class="nomark"></span>)'
                                                         r'<span class="title" style="grid-column:2 / 4"><span class="id">(.*?)</span> (.*?)</span>', s)]


@case
def try_section_lines_and_notes():
    out = page(make_home(log=log_of()))
    s = sec(out, "try")
    assert "<h2>試し中の Try（3）</h2>" in s
    got = try_lines(out)
    eq(got, [("11/9", "Y20261106-2", "正の表を作る。行＝決定ごと"), ("11/9", "Y20261106-3", "5pt 以上は数えてから出す"),
             ("11/6", "Y20261106-1", "外のリポジトリで作業するときは先に聞く")], "表の並びのまま・注記は飛ばす")
    rows7 = ["| Y1 | a | （注記）本文1 | c | 2026-11-06 |", "| Y2 | a | 注記なしの本文2 | c | 2026-11-06 |",
             "| Y3 | a | （閉じ括弧が無い本文3 | c | 2026-11-06 |", "| Y4 | a | （入れ（子）の注記）本文4 | c | 2026-11-06 |",
             "| Y5 | a | （注記だけ） | c | 2026-11-06 |", "| Y6 | a | 本文6（途中の括弧）です | c | 2026-11-06 |",
             "| Y7 | a | （注記）　　空白を挟む本文7 | c | |"]
    got = try_lines(page(make_home(log=log_of(rows7))))
    eq([(a, b, c) for a, b, c in got], [("11/6", "Y1", "本文1"), ("11/6", "Y2", "注記なしの本文2"), ("11/6", "Y3", "（閉じ括弧が無い本文3"),
                                         ("11/6", "Y4", "本文4"), ("11/6", "Y5", "（注記だけ）"), ("11/6", "Y6", "本文6（途中の括弧）です"),
                                         ("", "Y7", "空白を挟む本文7")], "注記の飛ばし方・開始日が空なら日付なし")


@case
def try_section_absent_when_log_missing_or_malformed():
    bad = [None, "# 改善ログ\n\n## 定着したルール\n\n" + LOG_HEAD + "\n".join(LOG_ROWS) + "\n",
           "## 実施中の Try\n\n（なし）\n\n## 定着したルール\n",
           "## 実施中の Try\n\n| ID | 良くするもの | 確かめ方 | 開始日 |\n|---|---|---|---|\n| Y1 | a | b | 2026-11-06 |\n",
           log_of([]), "## 実施中の Try\n\n" + LOG_HEAD.split("\n")[0] + "\n" + "\n".join(LOG_ROWS) + "\n",
           "## 実施中の Try\n\nなし\n\n## 定着したルール\n\n" + LOG_HEAD + "\n".join(LOG_ROWS) + "\n",
           log_of(["| （なし） | | | | |", "| T001 | a | b | c | 2026-11-06 |"]), ""]
    for i, log in enumerate(bad):
        out = page(make_home(log=log))
        assert sec(out, "try") is None, f"{i} 番目の形で区切りが出た"
        assert 'class="err"' not in out, f"{i} 番目の形でエラーが出た"
    # 次の「## 」より後ろは読まない・列の順が違っても読める
    log = ("## 実施中の Try\n\n| 開始日 | 確かめ方（数字で） | 内容 | 良くするもの（チーム） | ID |\n|---|---|---|---|---|\n| 2026-11-08 | 確 | 本文A | 人 | Y9-1 |\n\n"
           "## 定着したルール\n\n| ID | 良くするもの | 内容 | 確かめ方 | 開始日 |\n|---|---|---|---|---|\n| Y9-2 | x | 本文B | y | 2026-11-01 |\n")
    eq(try_lines(page(make_home(log=log))), [("11/8", "Y9-1", "本文A")])


@case
def try_non_date_start_goes_first_like_the_panel():
    # パネルの並び [開始日, ID, 内容]：日付の形でない開始日は、そのまま ID の前に出る
    rows5 = ["| Y1 | a | 本文1 | c | 来週 |", "| Y2 | a | 本文2 | c | 2026-11-06 |", "| Y3 | a | 本文3 | c | |"]
    s = sec(page(make_home(log=log_of(rows5))), "try")
    items = re.findall(r'<li class="row">(.*?)</li>', s)
    texts = [un(re.sub(r"<[^>]+>", "", x)) for x in items]
    eq(texts, ["来週 Y1 本文1", "11/6Y2 本文2", "Y3 本文3"], "開始日・ID・内容の並び")
    assert '<span class="nomark"></span><span class="title" style="grid-column:2 / 4">来週 <span class="id">Y1</span> 本文1' in s, s


@case
def iso_dates_are_ascii_digits_only_and_no_trailing_newline():
    for bad in ("２０２６-１１-０６", "2026-11-06\n", "2026-11-06 "):
        assert not CH.ISO.match(bad), repr(bad)
    assert CH.ISO.match("2026-11-06")
    eq(CH.md("２０２６-１１-０６"), "２０２６-１１-０６", "全角の数字は日付にしない（そのまま）")
    # 全角の開始日の Try は、日付の印にせず、そのまま ID の前に出る
    s = sec(page(make_home(log=log_of(["| Y1 | a | 本文 | c | ２０２６-１１-０６ |"]))), "try")
    assert '<span class="nomark"></span>' in s and "２０２６-１１-０６ <span" in s, s


# ---------- B1'：エスケープ ----------

SEED = "<script>alert(1)</script>\"'&</style><img src=x onerror=1>"
ALLOWED_TAGS = {"html", "head", "meta", "title", "style", "body", "div", "header", "h1", "h2", "h3", "span", "p", "time", "ul", "li",
                "a", "main", "section", "details", "summary"}
ALLOWED_ATTRS = {"lang", "charset", "name", "content", "http-equiv", "class", "id", "href", "datetime", "title", "aria-hidden", "style"}
STATIC_STYLES = {"grid-column:2 / 4", "color:var(--bar);font-weight:700", "font-weight:700"}


class Audit(HTMLParser):
    """出力を HTML として読み、決まったタグ・属性だけが使われているかを調べる。"""

    def __init__(self):
        super().__init__()
        self.bad = []
        self.titles = []

    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWED_TAGS:
            self.bad.append(f"タグ {tag}")
        for k, v in attrs:
            if k not in ALLOWED_ATTRS:
                self.bad.append(f"属性 {k}")
            if k == "href" and not (v or "").startswith("#"):
                self.bad.append(f"href {v}")
            if k == "style" and v not in STATIC_STYLES:
                self.bad.append(f"style {v}")
            if k == "title":
                self.titles.append(v)


def audit(out):
    a = Audit()
    a.feed(out)
    a.close()
    return a


def seeded_inputs(name):
    """name の欄だけに SEED を入れた本人のフォルダ（と、それが出るはずか）。"""
    S = SEED + name
    tasks = [gx("T001", "本人の今日", due=TODAY, category="A案件", kind="判断"),
             gx("T002", "AI の作業", assignee="dev-a", category="B案件", status="作業中", due="2026-11-09"),
             gx("T003", "完了", assignee="buka-a", status="完了")]
    cfg = dict(CFG)
    cal = {"fetched": "2026-11-02 09:00", "events": [{"date": TODAY, "start": "09:00", "end": "09:30", "title": "朝会", "allday": False}]}
    fc = [ft("T002", "AI の作業", "AI", "2026-11-02", "2026-11-04"), ft("T001", "本人の今日", "本人", None, "2026-11-03")]
    fo = {}
    log = log_of()
    shown = True
    if name == "tasks.title":
        tasks[0]["title"] = S
        tasks[2]["title"] = S + "完了"
    elif name == "tasks.category":
        tasks[0]["category"] = S
        tasks[1]["category"] = S + "2"
    elif name == "tasks.status":
        tasks[1]["status"] = S
    elif name == "tasks.assignee":
        tasks[2]["assignee"] = S
    elif name == "tasks.id":
        tasks[1]["id"] = "T0" + S
        fc[0]["id"] = "T0" + S
    elif name == "tasks.due":
        tasks[1]["due"] = S
    elif name == "forecast.title":
        fc[0]["title"] = S
    elif name == "forecast.id":
        fc[0]["id"] = S
    elif name == "forecast.who":
        fc[0]["who"] = S
        shown = False
    elif name == "forecast.state":
        fc[0]["state"] = S
        shown = False
    elif name == "config.owner":
        cfg = {"owner": S, "calendar": {"type": "ics"}}
        tasks[0]["assignee"] = S
    elif name == "config.owner_call":
        cfg["owner_call"] = S
    elif name == "calendar.title":
        cal["events"][0]["title"] = S
    elif name == "calendar.fetched":
        cal["fetched"] = "2026-11-02 " + S
    elif name == "calendar.start_end":
        cal["events"][0]["start"] = S
        cal["events"][0]["end"] = S + "終"
    elif name == "try.id":
        log = log_of(["| Y1" + S + " | a | b | c | 2026-11-06 |"])
    elif name == "try.body":
        log = log_of(["| Y1 | a | " + S + " | c | 2026-11-06 |"])
    elif name == "try.start":
        log = log_of(["| Y1 | a | b | c | " + S + " |"])
    else:
        raise KeyError(name)
    return make_home(tasks, cfg=cfg, cal=cal, forecast=fc_file(fc, **fo), log=log), S, shown


FIELDS = ["tasks.title", "tasks.category", "tasks.status", "tasks.assignee", "tasks.id", "tasks.due", "forecast.title", "forecast.id",
          "forecast.who", "forecast.state", "config.owner", "config.owner_call", "calendar.title", "calendar.fetched",
          "calendar.start_end", "try.id", "try.body", "try.start"]


@case
def b1_escape_every_field():
    for name in FIELDS:
        home, S, shown = seeded_inputs(name)
        out = page(home)
        assert "<script" not in out, f"{name}: <script が生のまま"
        assert "<img" not in out, f"{name}: <img が生のまま"
        assert out.count("</style>") == 1, f"{name}: </style> が生のまま"
        assert "onerror=1>" not in out.replace("&lt;img src=x onerror=1&gt;", ""), f"{name}: 属性・タグを作れた"
        if shown:
            assert html.escape(S, quote=True) in out, f"{name}: 画面に出ていない（エスケープした形で）"
        bad = audit(out).bad
        assert not bad, f"{name}: 想定外のタグ・属性 {bad}"


@case
def b1_escape_attribute_title_in_gantt_roundtrips():
    home, S, _ = seeded_inputs("forecast.title")
    a = audit(page(home))
    assert S in a.titles, "title 属性の中でも、元の文字のまま読める（壊れて別の属性にならない）"


@case
def b1_escape_error_messages_and_calendar_error():
    # 壊れた入力でも、文言に外の文字は混ざらない（固定の文だけ）
    out = page(make_home(tasks_raw="{" + SEED, forecast="{" + SEED, cal="{" + SEED))
    assert "<script" not in out and SEED not in out


# ---------- B3：forecast.json が古い・無い・壊れている ----------

@case
def b3_forecast_old_missing_broken():
    cases = [
        ("古い", fc_file([], today="2026-11-01"), "forecast.json が古いです（11/1 作成）。update_dashboard.py を動かすと出ます"),
        ("無い", "none", "forecast.json がまだありません（読めませんでした）。update_dashboard.py を動かすと出ます"),
        ("壊れている", "{ここは壊れた JSON", "forecast.json を読めませんでした（壊れています）。update_dashboard.py を動かし直すと出ます"),
        ("形が違う", {"today": TODAY, "tasks": [], "days": []}, "forecast.json を読めませんでした（壊れています）。update_dashboard.py を動かし直すと出ます"),
        ("配列", "[]", "forecast.json を読めませんでした（壊れています）。update_dashboard.py を動かし直すと出ます"),
    ]
    for label, fc, msg in cases:
        out = page(make_home(GROUPED["tasks"], cal=CAL_OK, sprints=GROUPED["daily_sprints"], forecast=fc))
        g = sec(out, "gantt")
        assert f'<p class="callout">{html.escape(msg, quote=True)}</p>' in g, f"{label}: 案内の文が違う {g[:200]}"
        assert "<h2>これから2週間</h2>" in g, f"{label}: 見出しは日付なし"
        assert 'class="grow' not in g and "legend" not in g, f"{label}: 棒が出た"
        # ガント以外は普通に出る
        assert sec(out, "mine") and sec(out, "all") and sec(out, "cal"), f"{label}: ほかの区切りが消えた"


# ---------- tasks.json・予定・設定 ----------

@case
def tasks_json_missing_or_broken_shows_band_and_hides_lists():
    home = make_home(forecast=fc_file([ft("T1", "a", "AI", "2026-11-02", "2026-11-03")], ), cal=CAL_OK)
    os.remove(os.path.join(home, "00_タスク管理", "data", "tasks.json"))
    # tasks.json が無いと本人のフォルダとして見つからないので、中身を直接読む関数で試す
    from pathlib import Path
    ctx = CH.load_context(Path(home), CFG, NOW)
    out = CH.render(ctx)
    assert '<p class="err">tasks.json が見つかりません</p>' in out
    assert sec(out, "mine") is None and sec(out, "all") is None and "お願い 残り" not in out, "「0件・なし」と見せない"
    assert sec(out, "gantt") and sec(out, "cal"), "ガント・予定は出す"
    for raw in ("{壊れた", "[]", '{"tasks": 5}', '{"tasks": [], "daily_sprints": 3}'):
        out = page(make_home(tasks_raw=raw, forecast=fc_file([])))
        assert '<p class="err">tasks.json を読めませんでした</p>' in out, raw
        assert sec(out, "mine") is None and sec(out, "all") is None, raw


@case
def calendar_only_when_config_has_calendar_and_error_texts():
    cal = {"fetched": "2026-11-02 09:00", "events": [{"date": TODAY, "start": "13:00", "end": "14:00", "title": "ふつうの会議", "allday": False}]}
    out = page(make_home(cfg={"owner": "山田", "owner_call": "山田さん"}, cal=cal))
    assert sec(out, "cal") is None and "ふつうの会議" not in out and "予定なし" not in out, "calendar が無いと区切りごと出さない"
    out = page(make_home(cal={"fetched": "2026-11-02 09:00", "events": []}))
    eq(shape(sec(out, "cal")), ["予定なし"])
    out = page(make_home(cal={"fetched": "2026-11-01 17:30", "events": []}))
    assert '<p class="callout">予定を読めていません（最後の取得 11/1 17:30）</p>' in sec(out, "cal")
    assert "<h2>今日の予定</h2>" in sec(out, "cal") and "予定なし" not in sec(out, "cal"), "古いときは「予定なし」と見せない・取得の時刻も出さない"
    out = page(make_home(cal="{壊れた"))
    assert '<p class="callout">予定を読めませんでした</p>' in sec(out, "cal")
    out = page(make_home())   # キャッシュのファイルが無い
    assert '<p class="callout">予定を読めませんでした</p>' in sec(out, "cal")


@case
def owner_and_call_defaults():
    out = page(make_home([gx("T001", "x", due=TODAY)], cfg={"owner": "鈴木"}))
    assert "<h2>鈴木さん（今日まで）</h2>" in out, "owner_call が無ければ owner + さん"
    assert shape(sec(out, "mine")) == ["なし"], "assignee が山田のタスクは鈴木の分ではない"
    out = page(make_home([gx("T001", "x", due=TODAY, assignee="鈴木")], cfg={"owner": "鈴木", "owner_call": "鈴木先生"}))
    assert "<h2>鈴木先生（今日まで）</h2>" in out and shape(sec(out, "mine")) == ["T001"]
    out = page(make_home([gx("T001", "x", due=TODAY, assignee="本人")], cfg={}))
    assert "<h2>本人さん（今日まで）</h2>" in out and shape(sec(out, "mine")) == ["T001"], "config が空でも落ちない"


@case
def approval_goes_top_in_mine_but_not_in_soon():
    d = [gx("T001", "普通", due="2026-11-01"), gx("T002", "ルール変更の承認（x）", due="2026-11-02"),
         gx("T003", "ルール変更の承認（y）", due="2026-11-03"), gx("T004", "普通2", due="2026-11-04"),
         gx("T005", "ルール変更の承認（本人以外）", assignee="dev-a", due="2026-11-02")]
    out = page(make_home(d))
    eq([line(r) for r in rows(sec(out, "mine"))],
       ["[承認] T002 ルール変更の承認（x）（11/2）", "[超過] T001 普通（11/1）"], "承認が一番上")
    eq([r["mark"] for r in rows(sec(out, "soon"))], ["承認", ""], "近いうちは印だけ。並びは期日の順のまま")


@case
def soon_limit_6_and_4_day_range():
    d = [gx(f"T0{i}", f"s{i}", due=f"2026-11-0{3 if i < 8 else 6}") for i in range(10, 18)] + [gx("T099", "遠い", due="2026-11-07")]
    out = page(make_home(d))
    ids = [r["id"] for r in rows(sec(out, "soon"))]
    eq(len(ids), 6, "6件まで")
    assert "T099" not in ids
    out = page(make_home([gx("T1", "4日後", due="2026-11-06"), gx("T2", "5日後", due="2026-11-07")]))
    eq([r["id"] for r in rows(sec(out, "soon"))], ["T1"], "明日〜4日後")


# ---------- K3''・K4 ----------

@case
def k3_today_is_jst_not_utc():
    # UTC では 11/1 16:30。日本時間は 11/2 01:30
    utc = datetime(2026, 11, 1, 16, 30, tzinfo=timezone.utc)
    now = CH.jst_now(utc)
    eq(now, datetime(2026, 11, 2, 1, 30), "日本時間")
    home = make_home([gx("T001", "今日", due=TODAY)], forecast=fc_file([], today="2026-11-01"))
    from pathlib import Path
    out = CH.render(CH.load_context(Path(home), CFG, now))
    assert "<h1>11/2 の予定</h1>" in out
    assert "2026-11-02 01:30" in out
    assert "forecast.json が古いです（11/1 作成）" in sec(out, "gantt"), "forecast の today が UTC の日付（11/1）でも古い"
    assert shape(sec(out, "mine")) == ["T001"]


@case
def k4_single_file_no_external_no_js_csp_tokens():
    out = page(make_home(GROUPED["tasks"], cal=CAL_OK, sprints=GROUPED["daily_sprints"], log=log_of(),
                         forecast=fc_file([ft("T1", "a", "AI", "2026-11-02", "2026-11-03")])))
    assert not re.search(r"<script|<link|src=|href=\"http|@import|url\(|<iframe|<img|<form", out), "外の読み込み・JavaScript"
    assert not re.search(r"\son[a-z]+=", out), "イベントの属性"
    assert "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">" in out
    assert not audit(out).bad
    assert '<time datetime="2026-11-02T10:00+09:00">2026-11-02 10:00</time> に作成。新しくするには「コックピット見せて」' in out
    assert out.startswith("<!doctype html><html lang=\"ja\">")
    # 色は変数だけ：:root（明るい・暗い）の外に、色の直書きが無い
    css = re.search(r"<style>(.*?)</style>", out, re.S).group(1)
    rest = re.sub(r":root\{.*?\}", "", css, flags=re.S)
    rest = re.sub(r"@media \(prefers-color-scheme: dark\)\{\s*\}", "", rest)
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b|rgb\(|hsl\(", rest), "色の直書き"
    for v in ("--bg", "--surface", "--ink", "--ink-2", "--line", "--bar", "--today-bg", "--off-bg", "--hatch", "--apv-bg", "--apv-fg",
              "--over-fg", "--over-bg", "--now-fg", "--now-bg", "--done-fg", "--done-bg"):
        assert css.count(v + ":") == 2, f"{v} が明るい・暗いの両方に無い"
    assert "prefers-color-scheme: dark" in css and "color-scheme: light dark" in css


@case
def k4_nav_links_are_page_anchors_only():
    out = page(make_home())
    eq(re.findall(r'href="([^"]*)"', out), ["#today", "#gantt", "#all"])
    for i in ("today", "gantt", "all"):
        assert f'id="{i}"' in out


# ---------- B4：書く・書かない ----------

def tree(home):
    res = {}
    for d, _, fs in os.walk(home):
        for f in fs:
            p = os.path.join(d, f)
            res[os.path.relpath(p, home)] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    return res


def run(args=(), cwd=None, env_home=None, extra_env=None):
    env = {k: v for k, v in os.environ.items() if k not in ("AI_BUNSHIN_HOME", "CLAUDE_PROJECT_DIR")}
    if env_home:
        env["AI_BUNSHIN_HOME"] = env_home
    env.update(extra_env or {})
    return subprocess.run([sys.executable, SCRIPT, *args], cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8")


@case
def b4_writes_only_the_fixed_output_and_reads_only():
    home = make_home(GROUPED["tasks"], cal=CAL_OK, sprints=GROUPED["daily_sprints"], log=log_of(), forecast=fc_file([]))
    before = tree(home)
    r = run(cwd=home)
    eq(r.returncode, 0, f"終了コード {r.stdout} {r.stderr}")
    out_path = os.path.join(home, "00_タスク管理", "コックピット.html")
    eq(r.stdout.strip(), out_path, "標準出力は出力したパス1行")
    after = tree(home)
    new = sorted(set(after) - set(before))
    eq(new, ["00_タスク管理/コックピット.html"], "増えたファイルは1つだけ（一時ファイルは残らない）")
    eq({k: v for k, v in after.items() if k in before}, before, "入力のファイルは1つも書き換わっていない")
    assert open(out_path, encoding="utf-8").read().startswith("<!doctype html>")
    # 2回目は置き換え（古い中身は残らない）
    open(out_path, "w").write("古い中身")
    r = run(cwd=os.path.join(home, "00_タスク管理"))     # 下のフォルダから動かしても本人のフォルダを見つける
    eq(r.returncode, 0, r.stderr)
    assert "古い中身" not in open(out_path, encoding="utf-8").read()
    eq(sorted(os.listdir(os.path.join(home, "00_タスク管理"))), ["data", "コックピット.html"], "一時ファイルが残っていない")


@case
def b4_not_a_home_writes_nothing_and_one_line():
    for label, files in (("config が無い", ("00_タスク管理/data/tasks.json",)), ("tasks.json が無い", ("設定/config.json",)),
                         ("どちらも無い", ())):
        d = os.path.join(BASE, "nothome_" + str(abs(hash(label))))
        os.makedirs(d)
        for f in files:
            wjson(os.path.join(d, f), "{}")
        r = run(cwd=d)
        eq(r.returncode, 1, label)
        eq(len(r.stdout.strip().splitlines()), 1, f"{label}: 1行で終わる")
        assert "本人のフォルダ" in r.stdout and "Traceback" not in r.stderr, (label, r.stdout, r.stderr)
        eq(tree(d), {f: hashlib.sha256(b"{}").hexdigest() for f in files}, f"{label}: 何も書かない")
    # config が壊れているときも書かない（パネルと同じ）
    home = make_home()
    wjson(os.path.join(home, "設定", "config.json"), "{壊れた")
    before = tree(home)
    r = run(cwd=home)
    eq((r.returncode, tree(home)), (1, before), "config が壊れている")
    # AI_BUNSHIN_HOME が本人のフォルダでなければ、ほかへ探しに行かない（カレントが本人のフォルダでも書かない）
    home = make_home()
    before = tree(home)
    r = run(cwd=home, env_home=os.path.join(BASE, "nothome_x"))
    eq((r.returncode, tree(home)), (1, before), "AI_BUNSHIN_HOME が違う場所")
    # AI_BUNSHIN_HOME で指定すれば、どこから動かしても、そのフォルダに書く
    r = run(cwd=BASE, env_home=home)
    eq(r.returncode, 0, r.stderr)
    assert os.path.exists(os.path.join(home, "00_タスク管理", "コックピット.html"))


@case
def b4_no_arguments_output_path_cannot_be_changed():
    home = make_home()
    other = os.path.join(BASE, "elsewhere.html")
    before = tree(home)
    for args in (["--out", other], ["-o", other], [other], ["--output=" + other], ["--help"]):
        r = run(args, cwd=home)
        eq(r.returncode, 2, f"{args}: 引数は断る")
        eq(len(r.stdout.strip().splitlines()), 1, f"{args}: 1行")
        assert not os.path.exists(other), f"{args}: 指定した場所に書いた"
        eq(tree(home), before, f"{args}: 何も書かない")
    # 環境変数でも出力先は変えられない（出力の場所は本人のフォルダの中に固定）
    r = run(cwd=home, extra_env={"COCKPIT_OUT": other, "OUT": other})
    eq(r.returncode, 0, r.stderr)
    assert not os.path.exists(other)
    eq(os.path.realpath(r.stdout.strip()), os.path.realpath(os.path.join(home, "00_タスク管理", "コックピット.html")))


@case
def b4_symlink_tmp_is_not_followed_and_output_symlink_is_replaced():
    home = make_home()
    outdir = os.path.join(home, "00_タスク管理")
    victim = os.path.join(BASE, "victim.txt")
    open(victim, "w").write("守る")
    os.symlink(victim, os.path.join(outdir, ".コックピット.html.tmp"))
    r = run(cwd=home)
    eq(r.returncode, 1, "一時ファイルがリンクなら書かない")
    eq(open(victim).read(), "守る", "リンク先は書き換わらない")
    assert not os.path.exists(os.path.join(outdir, "コックピット.html"))
    os.unlink(os.path.join(outdir, ".コックピット.html.tmp"))
    # 出力先そのものがリンクでも、リンク先ではなく、リンクを置き換える
    os.symlink(victim, os.path.join(outdir, "コックピット.html"))
    r = run(cwd=home)
    eq(r.returncode, 0, r.stderr)
    eq(open(victim).read(), "守る", "出力先がリンクでも、リンク先は書き換わらない")
    assert not os.path.islink(os.path.join(outdir, "コックピット.html"))


@case
def b4_task_dir_symlink_pointing_outside_home_is_not_written():
    home = make_home()
    outside = os.path.join(BASE, "outside_dir")
    os.makedirs(outside)
    # 00_タスク管理 を、本人のフォルダの外にある実体へのリンクにする（data は外の実体の中に置く）
    real_dir = os.path.join(home, "00_タスク管理")
    moved = os.path.join(outside, "00_タスク管理")
    os.rename(real_dir, moved)
    os.symlink(moved, real_dir)
    before = tree(outside)
    r = run(cwd=home)
    eq(r.returncode, 1, f"外を指すリンクには書かない {r.stdout}")
    eq(len(r.stdout.strip().splitlines()), 1, "1行で終わる")
    assert "Traceback" not in r.stderr
    eq(tree(outside), before, "外の実体には何も増えない")
    # 本人のフォルダの中を指すリンクなら書ける
    home2 = make_home()
    inner = os.path.join(home2, "実体")
    os.rename(os.path.join(home2, "00_タスク管理"), inner)
    os.symlink(inner, os.path.join(home2, "00_タスク管理"))
    r = run(cwd=home2)
    eq(r.returncode, 0, r.stdout + r.stderr)
    assert os.path.exists(os.path.join(inner, "コックピット.html"))


@case
def b4_leftover_regular_tmp_is_reused_and_symlink_tmp_is_refused():
    # 前の実行が途中で止まって残った一時ファイル（普通のファイル）：上書きして使い、次の実行は成功する
    home = make_home()
    outdir = os.path.join(home, "00_タスク管理")
    tmp = os.path.join(outdir, ".コックピット.html.tmp")
    open(tmp, "w").write("残り物" * 1000)
    r = run(cwd=home)
    eq(r.returncode, 0, r.stdout + r.stderr)
    out = open(os.path.join(outdir, "コックピット.html"), encoding="utf-8").read()
    assert out.startswith("<!doctype html>") and "残り物" not in out, "出力が新しい中身になっている"
    eq(sorted(os.listdir(outdir)), ["data", "コックピット.html"], "一時ファイルは残らない")
    # 一時ファイルがリンクなら、書かずに終了コード1（リンク先も守る）
    home2 = make_home()
    outdir2 = os.path.join(home2, "00_タスク管理")
    victim = os.path.join(BASE, "victim2.txt")
    open(victim, "w").write("守る")
    os.symlink(victim, os.path.join(outdir2, ".コックピット.html.tmp"))
    r = run(cwd=home2)
    eq((r.returncode, len(r.stdout.strip().splitlines())), (1, 1), r.stdout + r.stderr)
    eq(open(victim).read(), "守る")
    assert not os.path.exists(os.path.join(outdir2, "コックピット.html"))


@case
def deeply_nested_json_is_unreadable_not_a_crash():
    deep = "[" * 100000 + "]" * 100000
    # tasks.json：帯に「読めませんでした」
    out = page(make_home(tasks_raw=deep))
    assert "tasks.json を読めませんでした" in out and "Traceback" not in out
    # 読み込みは通るが、題名の中の入れ子が深くて文字にするときに再帰が足りなくなる形（build の中）
    mid = "[" * 450 + "]" * 450
    out = page(make_home(tasks_raw='{"tasks": [{"id": "T1", "title": ' + mid + '}], "daily_sprints": []}'))
    assert "tasks.json を読めませんでした" in out and "Traceback" not in out
    # forecast.json・calendar_cache.json：それぞれの案内
    out = page(make_home(forecast=deep, cal=deep))
    assert "forecast.json を読めませんでした" in out and "予定を読めませんでした" in out
    # config.json：本人のフォルダとして扱わない（壊れた config と同じ）。標準出力は1行で、何も書かない
    home = make_home()
    wjson(os.path.join(home, "設定", "config.json"), deep)
    before = tree(home)
    r = run(cwd=home)
    eq((r.returncode, len(r.stdout.strip().splitlines()), tree(home)), (1, 1, before), "深い config")
    assert "Traceback" not in r.stderr, r.stderr
    # スクリプトの外側（main）でも、落ちずに1行で終わる
    home = make_home(tasks_raw=deep)
    r = run(cwd=home)
    eq(r.returncode, 0, r.stderr)
    assert "Traceback" not in r.stderr


@case
def b4_find_home_same_rule_as_panel():
    home = make_home()
    deep = os.path.join(home, "a", "b", "c", "d", "e", "f")
    os.makedirs(deep)
    r = run(cwd=deep)                  # 6段下までは見つける
    eq(r.returncode, 0, r.stderr)
    deep7 = os.path.join(deep, "g")
    os.makedirs(deep7)
    before = tree(home)
    r = run(cwd=deep7)                 # 7段下では見つけない
    eq(r.returncode, 1, "7段下")
    eq(tree(home), before)
    # BOM 付きの config.json も読める
    home = make_home(cfg="﻿" + json.dumps({"owner": "山田", "owner_call": "山田さん"}, ensure_ascii=False))
    eq(run(cwd=home).returncode, 0, "BOM")


if __name__ == "__main__":
    print(f"失敗 {fails} 件")
    sys.exit(1 if fails else 0)
