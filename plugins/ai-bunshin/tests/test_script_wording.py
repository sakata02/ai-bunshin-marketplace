"""update_dashboard.py が本人に見せる文言のテスト（T074：エンジニアでない人が見ても迷わない）。
- フォルダが見つからないときの案内：AI_BUNSHIN_HOME の話を出さず、フォルダの開き直し方（アプリ）を一言入れる。AI_BUNSHIN_HOME の機能は残る
- 案内のコマンドは /ai-bunshin:status（裸の /status を残さない）
- ベロシティ・スプリント・PDCA・pt に短い言い換え（タスク状況・タスクボード・Excel の見出し／注釈）
- dev-a・buka-a などの記号を、本人に見せる出力では部下C などの役割名にする（tasks.json の値は変えない）
実行：python3 tests/test_script_wording.py（失敗があれば終了コード1）。一時フォルダだけで動く"""
import json, os, re, subprocess, sys, tempfile
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.abspath(os.path.join(HERE, "..", "scripts", "update_dashboard.py"))

BASE = os.path.realpath(tempfile.mkdtemp(prefix="wordingchk_"))
FAKE_HOME = os.path.join(BASE, "home")
os.makedirs(FAKE_HOME)
R = os.path.join(BASE, "owner")
os.makedirs(os.path.join(R, "設定"))
os.makedirs(os.path.join(R, "00_タスク管理", "data"))
TODAY = date(2026, 11, 4)   # 水曜
TASKS_PATH = os.path.join(R, "00_タスク管理", "data", "tasks.json")
json.dump({"owner": "テスト", "owner_call": "テストさん", "ai_name": "テストAI", "departments": ["総務"]},
          open(os.path.join(R, "設定", "config.json"), "w", encoding="utf-8"), ensure_ascii=False)
DATA = {"project": {"name": "テストAI", "daily_capacity_default": 8.0, "holidays": []},
        "daily_sprints": [],
        "sprints": [{"id": "S001", "start": "2026-11-02", "end": "2026-11-06", "goal": "テストの目標", "status": "進行中", "pdca": "Do"}],
        "tasks": [
            # 納期を過ぎている（要注意シートとガントに作る人が出る）。作る人 dev-a・確かめる人 dev-b
            {"id": "T001", "title": "遅れているタスク", "status": "作業中", "assignee": "dev-a", "type": "開発",
             "reviewer": "dev-b", "points": 2, "department": "総務", "priority": 1, "due": "2026-11-02", "sprint": "S001"},
            {"id": "T002", "title": "待っているタスク", "status": "ToDo", "assignee": "buka-a", "type": "資料",
             "reviewer": "buka-b", "points": 1, "department": "総務", "priority": 2, "depends_on": ["T001"], "sprint": "S001"}]}
json.dump(DATA, open(TASKS_PATH, "w", encoding="utf-8"), ensure_ascii=False)


def run(args, cwd=R, home=R, project=None):
    env = {k: v for k, v in os.environ.items() if k not in ("AI_BUNSHIN_HOME", "CLAUDE_PROJECT_DIR")}
    env["HOME"] = FAKE_HOME
    if home:
        env["AI_BUNSHIN_HOME"] = home
    if project:
        env["CLAUDE_PROJECT_DIR"] = project
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, cwd=cwd, env=env)


fails = 0


def check(name, ok, detail=""):
    global fails
    print(("OK   " if ok else "FAIL ") + name + ("" if ok else f"\n     {str(detail)[:500]}"))
    if not ok:
        fails += 1


# --- 1. フォルダが見つからないときの案内 ---
EMPTY = os.path.join(BASE, "empty")
os.makedirs(EMPTY)
r = run([], cwd=EMPTY, home=None, project=EMPTY)
check("見つからない：終了コード1で案内が出る", r.returncode == 1 and "00_タスク管理" in r.stderr, r.stderr)
check("見つからない：AI_BUNSHIN_HOME の話を出さない", "AI_BUNSHIN_HOME" not in r.stderr, r.stderr)
check("見つからない：「00_タスク管理 があるフォルダを開き直してください」", "00_タスク管理 があるフォルダを開き直してください" in r.stderr, r.stderr)
check("見つからない：アプリでのフォルダの開き方（Code タブ）を一言", "Code" in r.stderr and "タブ" in r.stderr, r.stderr)
r = run(["--today", TODAY.isoformat()])   # AI_BUNSHIN_HOME で指定したフォルダは今までどおり使える
check("AI_BUNSHIN_HOME の機能は残る（指定したフォルダで動く）", r.returncode == 0 and "T001" in r.stdout, r.stdout + r.stderr)
check("AI_BUNSHIN_HOME に別のフォルダを指定すると見つからない扱い（誤更新しない）", run([], cwd=R, home=EMPTY).returncode == 1)

# --- 2. 案内のコマンド ---
src = open(SCRIPT, encoding="utf-8").read()
bare = [m.group(0) for m in re.finditer(r"(?<![\w:/-])/status\b", src)]
check("スクリプトの中に裸の /status が無い（/ai-bunshin:status にする）", not bare, bare)
check("Excel を保存できなかったときの案内が /ai-bunshin:status", "もう一度 /ai-bunshin:status を実行してください" in src)

# --- 3・4. 出力（タスク状況・タスクボード・Excel） ---
r = run(["--today", TODAY.isoformat()])
out = r.stdout
check("タスク状況：ベロシティに言い換えが付く", re.search(r"ベロシティ（[^）]*終わった量|ベロシティ（[^）]*完了量", out) is not None, out[:400])
check("タスク状況：作る人が役割名（部下C・部下A）", "部下C" in out and "部下A" in out, out)
check("タスク状況：dev-a・buka-a の記号が出ない", not re.search(r"\b(dev-[ab]|buka-[ab]|design|analyst|trainer)\b", out), out)
board = open(os.path.join(R, "00_タスク管理", "タスクボード.md"), encoding="utf-8").read()
check("タスクボード：ベロシティに言い換え", re.search(r"ベロシティ[^\n]*（[^）]*(終わった量|完了量)", board) is not None, board[:500])
check("タスクボード：スプリントに言い換え", re.search(r"現在のスプリント[^\n]*1週間", board) is not None, board[:600])
check("タスクボード：記号が出ない・部下C", not re.search(r"\b(dev-[ab]|buka-[ab])\b", board) and "部下C" in board, board)

try:
    import openpyxl
except ImportError:   # openpyxl が無い環境では Excel の確かめだけ飛ばす
    openpyxl = None
if openpyxl is None:
    print("SKIP Excel の確かめ（openpyxl なし）")
else:
    wb = openpyxl.load_workbook(os.path.join(R, "00_タスク管理", "タスク管理.xlsx"))
    cells = [(ws.title, c) for ws in wb for row in ws.iter_rows() for c in row if c.value is not None]
    texts = [str(c.value) for _, c in cells]
    check("Excel：セルに dev-a・buka-a などの記号が出ない", not [t for t in texts if re.fullmatch(r"(dev-[ab]|buka-[ab]|design|analyst|trainer)", t)],
          [t for t in texts if re.fullmatch(r"(dev-[ab]|buka-[ab])", t)])
    dash = wb["ダッシュボード"]
    labels = [str(c.value) for row in dash.iter_rows(min_row=4, max_row=4) for c in row if c.value]
    check("Excel ダッシュボード：ベロシティの見出しに言い換え", any(l.startswith("ベロシティ（") for l in labels), labels)
    check("Excel ダッシュボード：スプリント進捗の見出しに言い換え", any(l.startswith("スプリント進捗（") for l in labels), labels)
    dtexts = [str(c.value) for row in dash.iter_rows() for c in row if c.value]
    check("Excel ダッシュボード：現在のスプリント・PDCAフェーズに言い換え",
          any(t.startswith("現在のスプリント（") for t in dtexts) and any(t.startswith("PDCAフェーズ（") for t in dtexts), dtexts)
    daily = wb["日次スプリント"]
    a1, a2 = str(daily["A1"].value), str(daily["A2"].value)
    check("Excel 日次スプリント：見出しに言い換え（1日ごとの計画）", "1日ごと" in a1, a1)
    check("Excel 日次スプリント：pt・約束pt・完了pt の説明", "pt＝" in a2 and "約束pt＝" in a2, a2)
    check("Excel 日次スプリント：表の見出し（約束pt・完了pt・ベロシティ）は変えない（グラフの凡例に使う）",
          [daily.cell(row=4, column=c).value for c in (3, 4, 6)] == ["約束pt", "完了pt", "ベロシティ(3日平均)"],
          [daily.cell(row=4, column=c).value for c in (3, 4, 6)])
    tl = wb["タスク一覧"]
    heads = {str(c.value): c for c in tl[1] if c.value}
    check("Excel タスク一覧：pt・スプリント・PDCA の見出しに注釈（コメント）",
          all(h in heads and heads[h].comment is not None for h in ("pt", "スプリント", "PDCA")), list(heads))
    check("Excel タスク一覧：見出しの文字は変えない", {"pt", "スプリント", "PDCA", "作る人", "確かめる人"} <= set(heads), list(heads))
    check("Excel タスク一覧：作る人・確かめる人は役割名",
          {str(tl.cell(row=2, column=c).value) for c in (7, 8)} <= {"部下A", "部下B", "部下C", "部下D"}, [tl.cell(row=2, column=c).value for c in (7, 8)])
    hist = wb["スプリント履歴"]
    hheads = {str(c.value): c for c in hist[1] if c.value}
    check("Excel スプリント履歴：スプリント・計画pt の見出しに注釈", all(h in hheads and hheads[h].comment is not None for h in ("スプリント", "計画pt")), list(hheads))
    check("Excel 要注意タスク・ガント：作る人が役割名（部下C）", "部下C" in texts, "")

# --- 5. ダッシュボードの見出しの折り返しと高さ（T074 の直し） ---
if openpyxl is not None:
    a_pdca = next((c for row in dash.iter_rows(min_row=9, max_row=14, max_col=1) for c in row
                   if c.value and str(c.value).startswith("PDCAフェーズ（")), None)
    check("Excel ダッシュボード：PDCAフェーズの見出し（A列）が折り返す", a_pdca is not None and a_pdca.alignment.wrap_text, a_pdca)
    h_pdca = dash.row_dimensions[a_pdca.row].height if a_pdca else None
    check("Excel ダッシュボード：PDCAフェーズの行が2行ぶん以上の高さ", h_pdca is not None and h_pdca >= 30, h_pdca)
    check("Excel ダッシュボード：4行目（C4・G4・H4の見出し）の高さが54以上", (dash.row_dimensions[4].height or 0) >= 54, dash.row_dimensions[4].height)
    check("Excel ダッシュボード：C4・G4・H4が折り返す", all(dash[c].alignment.wrap_text for c in ("C4", "G4", "H4")), "")

# --- 6. 本人に見せる文言の追加（T074 の直し） ---
dev_skill = open(os.path.join(HERE, "..", "skills", "dev", "SKILL.md"), encoding="utf-8").read()
check("dev スキル：git switch の案内に ! を付けない（ターミナルで打つ形）", "! cd <リポジトリ> && git switch" not in dev_skill and "git switch <ブランチ>" in dev_skill)
check("dev スキル：push の案内の ! は残す", "! git -C <リポジトリ> push -u origin <ブランチ>" in dev_skill)
check("タスクボード：現在のスプリントの PDCA に説明が付く", re.search(r"現在のスプリント[^\n]*Do[^\n]*計画・実行・確認・改善のどの段階か", board) is not None, board[:700])

# 今日の計画の行（起動時のまとめ）に pt の説明が付く。assignee が変わった値でも落ちず None と出ない
R2 = os.path.join(BASE, "owner2")
os.makedirs(os.path.join(R2, "設定"))
os.makedirs(os.path.join(R2, "00_タスク管理", "data"))
json.dump({"owner": "テスト", "owner_call": "テストさん", "ai_name": "テストAI", "departments": ["総務"]},
          open(os.path.join(R2, "設定", "config.json"), "w", encoding="utf-8"), ensure_ascii=False)
base_t = {"status": "ToDo", "points": 1, "department": "総務", "sprint": "S001"}
d2 = {"project": {"name": "テストAI", "daily_capacity_default": 8.0, "holidays": []},
      "daily_sprints": [{"date": TODAY.isoformat(), "capacity": 8, "planned": ["T001", "T002", "T003", "T005", "T006"],
                         "committed": 5, "status": "実行中"}],
      "sprints": DATA["sprints"],
      "tasks": [
          dict(base_t, id="T001", title="foo", assignee="foo", type="開発", reviewer="foo", priority=1),
          dict(base_t, id="T002", title="null", assignee=None, type="資料", reviewer=None, priority=2),
          dict(base_t, id="T003", title="無し", type="資料", priority=3),
          dict(base_t, id="T004", title="本人", assignee="テスト", type="本人の仕事", kind="自分", priority=4),
          dict(base_t, id="T005", title="指揮官", assignee="指揮官", type="開発", priority=5),
          dict(base_t, id="T006", title="種類なし", assignee="dev-a", priority=6),
      ]}
json.dump(d2, open(os.path.join(R2, "00_タスク管理", "data", "tasks.json"), "w", encoding="utf-8"), ensure_ascii=False)
for args in ([], ["--session"], ["--review-context"], ["--plan-context"]):
    r2 = run(["--today", TODAY.isoformat(), *args], cwd=R2, home=R2)
    check(f"assignee が foo・null・無し・本人・指揮官でも落ちない {args}", r2.returncode == 0 and "Traceback" not in r2.stderr, r2.stderr[-400:])
    check(f"assignee が欠けていても None と出ない {args}", not re.search(r"\bNone\b", r2.stdout), [l for l in r2.stdout.splitlines() if "None" in l][:3])
r2 = run(["--today", TODAY.isoformat()], cwd=R2, home=R2)
plan_line = next((l for l in r2.stdout.splitlines() if l.startswith("[📅 今日の計画]")), "")
check("起動時のまとめ：今日の計画の行に「pt＝しごとの大きさ」", "pt＝しごとの大きさ" in plan_line and "約束" in plan_line, plan_line or r2.stdout[:500])
warn_line = next((l for l in r2.stdout.splitlines() if "振り分けの確認" in l), "")
check("振り分けの確認：作る人が無いときは（未設定）と出る", "（未設定）" in warn_line, warn_line or r2.stdout[:500])
check("振り分けの確認：foo はそのまま出る", "foo" in warn_line, warn_line)
check("振り分けの確認：dev-a は部下C と出る（記号を出さない）", "dev-a" not in warn_line, warn_line)
if openpyxl is not None:
    wb2 = openpyxl.load_workbook(os.path.join(R2, "00_タスク管理", "タスク管理.xlsx"))
    t2 = [str(c.value) for ws in wb2 for row in ws.iter_rows() for c in row if c.value is not None]
    check("assignee が欠けていても Excel に None の文字が出ない", "None" not in t2, "")
# 週の振り返り（金曜）のチームのまとめも落ちない
rf = run(["--today", "2026-11-06", "--review-context"], cwd=R2, home=R2)
check("金曜の振り返りの材料も assignee が変わった値で落ちない", rf.returncode == 0 and "Traceback" not in rf.stderr, rf.stderr[-400:])

after = json.load(open(TASKS_PATH, encoding="utf-8"))["tasks"]
check("tasks.json の値（assignee・reviewer）は変わらない（dev-a のまま）",
      [(t["assignee"], t["reviewer"]) for t in after] == [(t["assignee"], t["reviewer"]) for t in DATA["tasks"]], after)

print(f"\n{'失敗 ' + str(fails) + ' 件' if fails else 'すべて通りました'}")
sys.exit(1 if fails else 0)
