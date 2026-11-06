"""tasks.json の文字の項目（related・note・title・department など）に一覧（[ ]）や { } が入っていても、
update_dashboard.py が止まらず、Excel・タスクボード・お願いを作るかのテスト（T159。11/04 に related が一覧になり、Excel の更新が半日止まった）。
- 読むときに文字にする：一覧 → 「・」でつなぐ、{ } → JSON の文字、None・数はそのまま
- 文字にするのはメモリの上だけ。tasks.json のファイルは書き換えない（移しのときも、中身の一覧は一覧のまま）
- steps・depends_on（もともと一覧の項目）は触らない
本物の自分のフォルダは使わない（すべて一時フォルダ。AI_BUNSHIN_HOME で指定）。
実行：python3 tests/test_text_fields.py（失敗があれば終了コード1）"""
import copy
import importlib
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.abspath(os.path.join(HERE, "..")), "scripts")
DASH = os.path.join(SCRIPTS, "update_dashboard.py")
BASE = os.path.realpath(tempfile.mkdtemp(prefix="textfields_"))
fails = 0
counter = [0]


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


CONFIG = {"owner": "テスト", "owner_call": "テストさん", "ai_name": "テストAI", "departments": ["総務"]}


def tasks_data(with_version):
    """11/04 の実物に近い形：お願い（本人のタスク）の related が一覧。note が { }、title・department が一覧のタスクも。"""
    data = {"project": {"name": "テストAI", "daily_capacity_default": 8.0, "holidays": []},
            "daily_sprints": [], "sprints": [],
            "tasks": [
                {"id": "T001", "title": "ふつうのタスク", "status": "ToDo", "assignee": "dev-a", "type": "開発",
                 "reviewer": "dev-b", "points": 2, "department": "総務", "priority": 1,
                 "note": {"役": "テスト", "メモ": ["a", "b"]}, "depends_on": ["T002"]},
                {"id": "T002", "title": ["一覧の", "題名"], "status": "ToDo", "assignee": "dev-a", "type": "開発",
                 "reviewer": "dev-b", "points": 1, "department": ["総務", "技術開発部"], "priority": 2},
                {"id": "T152", "title": "お願いその1", "status": "ToDo", "assignee": "テスト", "kind": "判断", "type": "本人",
                 "due": "2026-11-05", "due_reason": ["理由1", "理由2"], "why": ["なぜ"], "steps": ["やること1", "やること2"],
                 "done_when": {"基準": "できた"}, "report_back": ["教えて"], "related": ["T001", "T002"], "priority": 3},
                {"id": "T153", "title": "お願いその2", "status": "ToDo", "assignee": "テスト", "kind": "確認", "type": "本人",
                 "due": "2026-11-05", "related": ["T001", "T002"], "priority": 4},
                {"id": "T154", "title": "お願いその3", "status": "ToDo", "assignee": "テスト", "kind": "確認", "type": "本人",
                 "due": "2026-11-05", "related": {"元": "T001"}, "priority": 5},
            ]}
    if with_version:
        data = {"schema_version": 1, **data}
    return data


def make_home(tasks):
    counter[0] += 1
    root = os.path.join(BASE, f"home{counter[0]}")
    os.makedirs(os.path.join(root, "設定"))
    os.makedirs(os.path.join(root, "00_タスク管理", "data"))
    with open(os.path.join(root, "設定", "config.json"), "w", encoding="utf-8") as f:
        json.dump(CONFIG, f, ensure_ascii=False, indent=2)
    with open(tasks_file(root), "w", encoding="utf-8") as f:
        f.write(json.dumps(tasks, ensure_ascii=False, indent=2) + "\n")
    return root


def tasks_file(root):
    return os.path.join(root, "00_タスク管理", "data", "tasks.json")


def rd(path):
    with open(path, "rb") as f:
        return f.read()


def run_dash(root, args):
    env = {k: v for k, v in os.environ.items() if k not in ("AI_BUNSHIN_HOME", "CLAUDE_PROJECT_DIR")}
    env.update(AI_BUNSHIN_HOME=root, PYTHONUTF8="1")
    return subprocess.run([sys.executable, DASH, *args], capture_output=True, text=True, encoding="utf-8", cwd=root, env=env)


def read_outputs(root):
    d = os.path.join(root, "00_タスク管理")
    board = open(os.path.join(d, "タスクボード.md"), encoding="utf-8").read()
    reqs = open(os.path.join(d, "テストさんへのお願い.md"), encoding="utf-8").read()
    return board, reqs


def load_module():
    home = make_home(tasks_data(True))
    os.environ["AI_BUNSHIN_HOME"] = home
    os.environ.pop("CLAUDE_PROJECT_DIR", None)
    sys.path.insert(0, SCRIPTS)
    sys.modules.pop("update_dashboard", None)
    return importlib.import_module("update_dashboard")


MOD = load_module()


@case
def text_of_turns_lists_and_dicts_into_text_and_leaves_the_rest():
    t = MOD.text_of
    assert t(["T152", "T153"]) == "T152・T153"
    assert t([]) == "" and t(["T1", None, "T2"]) == "T1・T2", t(["T1", None, "T2"])
    assert t([["a", "b"], "c", 3]) == "a・b・c・3"
    assert t({"元": "T001"}) == '{"元": "T001"}'      # ensure_ascii=False
    assert t(None) is None and t("文字") == "文字" and t(5) == 5 and t(2.5) == 2.5 and t(True) is True and t("") == ""


@case
def normalize_touches_text_fields_only_not_steps_or_depends_on():
    data = copy.deepcopy(tasks_data(True))
    MOD.normalize_text_fields(data)
    by = {t["id"]: t for t in data["tasks"]}
    assert by["T152"]["related"] == "T001・T002", by["T152"]["related"]
    assert by["T152"]["steps"] == ["やること1", "やること2"]     # もともと一覧の項目は一覧のまま
    assert by["T001"]["depends_on"] == ["T002"]
    assert by["T002"]["title"] == "一覧の・題名" and by["T002"]["department"] == "総務・技術開発部"
    assert by["T001"]["note"].startswith("{") and "役" in by["T001"]["note"]
    assert by["T001"]["points"] == 2 and by["T001"]["priority"] == 1   # 数は触らない


@case
def related_list_note_dict_title_list_do_not_stop_excel_board_and_requests():
    home = make_home(tasks_data(True))
    r = run_dash(home, ["--today", "2026-11-06"])
    text = r.stdout + r.stderr
    assert r.returncode == 0 and "Traceback" not in text and "unhashable" not in text, text[-400:]
    board, reqs = read_outputs(home)
    assert "T001" in board and "T152" in reqs and "T153" in reqs and "T154" in reqs, reqs[:300]
    assert os.path.exists(os.path.join(home, "00_タスク管理", "タスク管理.xlsx")) or "openpyxl" in text, text[-300:]


@case
def related_list_is_shown_as_joined_text_in_requests_and_title_list_in_excel():
    home = make_home(tasks_data(True))
    r = run_dash(home, ["--today", "2026-11-06"])
    assert r.returncode == 0, r.stderr[-300:]
    _, reqs = read_outputs(home)
    assert "- **関連**：T001・T002" in reqs, reqs
    assert "['T001'" not in reqs and '["T001"' not in reqs, reqs
    assert "- **期日の理由**：理由1・理由2" in reqs, reqs
    try:
        import openpyxl
    except ImportError:
        print("      （openpyxl が無いので Excel の中身は飛ばす）")
        return
    wb = openpyxl.load_workbook(os.path.join(home, "00_タスク管理", "タスク管理.xlsx"))
    cells = [str(c.value) for ws in wb for row in ws.iter_rows() for c in row if c.value is not None]
    assert any("一覧の・題名" in c for c in cells), "title が一覧のタスクが Excel に文字で出ていない"
    assert not any(c.startswith("['") or c.startswith("[\"") for c in cells), "Excel に一覧の書き方が出ている"


@case
def tasks_json_bytes_stay_same_when_no_migration_needed():
    home = make_home(tasks_data(True))      # schema_version あり＝移しは行われない
    before = rd(tasks_file(home))
    for args in (["--today", "2026-11-06"], ["--today", "2026-11-06", "--task", "T152"], ["--today", "2026-11-06", "--session"],
                 ["--today", "2026-11-06", "--plan-context"]):
        r = run_dash(home, args)
        assert "Traceback" not in r.stdout + r.stderr, (args, (r.stdout + r.stderr)[-300:])
        assert rd(tasks_file(home)) == before, f"tasks.json が書き換わった {args}"
    assert not [f for f in os.listdir(os.path.dirname(tasks_file(home))) if ".bak_" in f], "控えが作られた"


@case
def migration_keeps_original_lists_and_dicts_in_tasks_json():
    """schema_version が無い tasks.json は移しで書き換わる。そのとき、文字にした値ではなく元の一覧・{ } のままであること。"""
    orig = tasks_data(False)
    home = make_home(orig)
    r = run_dash(home, ["--today", "2026-11-06"])
    assert r.returncode == 0, (r.stdout + r.stderr)[-300:]
    after = json.loads(rd(tasks_file(home)))
    assert after.pop("schema_version") == 1 and "新しい形式" in r.stdout, r.stdout
    assert after == orig, "移しのあとの tasks.json の中身が、元と違う（文字にした値が書き戻された）"


@case
def task_option_shows_the_original_list_not_the_text():
    """--task は tasks.json の実物を出す（読むときに文字にした値ではなく、一覧は一覧のまま）。"""
    home = make_home(tasks_data(True))
    r = run_dash(home, ["--today", "2026-11-06", "--task", "T152", "T154"])
    assert r.returncode == 0, r.stderr[-300:]
    found = {t["id"]: t for t in json.loads(r.stdout)}
    assert found["T152"]["related"] == ["T001", "T002"], found["T152"]
    assert found["T152"]["due_reason"] == ["理由1", "理由2"] and found["T152"]["done_when"] == {"基準": "できた"}, found["T152"]
    assert found["T154"]["related"] == {"元": "T001"}, found["T154"]


@case
def control_characters_in_text_fields_are_removed_so_excel_is_made_and_tasks_json_stays_same():
    """note に \u0001 などがあると openpyxl の IllegalCharacterError で Excel が止まる。文字の項目は読むときに取り除く（タブ・改行は残す）。"""
    assert MOD.text_of("a\u0001b\u000bc\u001fd\te\nf\rg") == "abcd\te\nf\rg"
    assert MOD.text_of(["x\u0002", "y"]) == "x・y"
    assert "\u0003" not in MOD.text_of({"k": "v\u0003"})   # { } の中の制御文字は json.dumps が \\u0003 の文字にするので、生の制御文字は残らない
    data = tasks_data(True)
    data["tasks"][0]["note"] = "メモ\u0001あり\n二行目"
    data["tasks"][1]["title"] = ["一覧\u0007の", "題名"]
    home = make_home(data)
    before = rd(tasks_file(home))
    r = run_dash(home, ["--today", "2026-11-06"])
    assert r.returncode == 0 and "Traceback" not in r.stdout + r.stderr, (r.stdout + r.stderr)[-400:]
    assert os.path.exists(os.path.join(home, "00_タスク管理", "タスク管理.xlsx")) or "openpyxl" in r.stdout + r.stderr
    assert rd(tasks_file(home)) == before, "tasks.json が書き換わった"


if __name__ == "__main__":
    print(f"失敗 {fails} 件")
    sys.exit(1 if fails else 0)
