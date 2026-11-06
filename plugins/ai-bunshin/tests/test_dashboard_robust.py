"""手で編集した設定・Windows でも、タスク管理のスクリプトが落ちず、分かる言葉で知らせるかのテスト（レビュー③堅牢性）。
- Windows 形式のパスで daily の判定が正しい
- BOM 付きの config.json・tasks.json・settings.json が読める（BOM なしも今までどおり）
- 壊れた JSON・空のファイル・キーが足りない daily_sprints／sprints・容量の 0／文字／null でも、トレースバックを出さず日本語で知らせ、
  tasks.json を書き換えない。hook（--hook／--session）は壊れた設定でも止めない
- 初期ベロシティの既定値が1か所（雛形・コード・計画のスキルが同じ）
- --now で時刻を外から渡せる。--today と --now を固定すると、同じ入力で同じ出力になる
- ガントが 120 日で切れたら、切れたことが分かる
- pip の案内が hook の順番（python3 → python → py -3）で、status と setup と一致する
- 祝日の雛形が空なので、setup が祝日を入れる案内を持つ
本物の自分のフォルダは使わない（すべて一時フォルダ。AI_BUNSHIN_HOME で指定）。
実行：python3 tests/test_dashboard_robust.py（失敗があれば終了コード1）"""
import contextlib
import copy
import datetime
import importlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import PurePosixPath, PureWindowsPath

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.path.join(HERE, ".."))
SCRIPTS = os.path.join(PLUGIN, "scripts")
DASH = os.path.join(SCRIPTS, "update_dashboard.py")
SETUP_SETTINGS = os.path.join(SCRIPTS, "setup_settings.py")
TEMPLATE_TASKS = os.path.join(PLUGIN, "templates", "tasks", "tasks.json")

BASE = os.path.realpath(tempfile.mkdtemp(prefix="dashrobust_"))
BOM = "﻿"
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
TASKS = {"project": {"name": "テストAI", "daily_capacity_default": 8.0, "holidays": []},
         "daily_sprints": [], "sprints": [],
         "tasks": [{"id": "T001", "title": "テスト用タスク", "status": "ToDo", "assignee": "dev-a", "type": "開発",
                    "reviewer": "dev-b", "points": 2, "department": "総務", "priority": 1}]}


def make_home(config=CONFIG, tasks=TASKS, config_raw=None, tasks_raw=None, config_bom=False, tasks_bom=False):
    """一時の本人のフォルダを作る。*_raw を渡すと、そのバイト列・文字列をそのまま書く。"""
    counter[0] += 1
    root = os.path.join(BASE, f"home{counter[0]}")
    os.makedirs(os.path.join(root, "設定"))
    os.makedirs(os.path.join(root, "00_タスク管理", "data"))
    cfg = config_raw if config_raw is not None else json.dumps(config, ensure_ascii=False, indent=2)
    tsk = tasks_raw if tasks_raw is not None else json.dumps(tasks, ensure_ascii=False, indent=2) + "\n"
    for path, body, bom in ((os.path.join(root, "設定", "config.json"), cfg, config_bom),
                            (os.path.join(root, "00_タスク管理", "data", "tasks.json"), tsk, tasks_bom)):
        data = body if isinstance(body, bytes) else ((BOM if bom else "") + body).encode("utf-8")
        with open(path, "wb") as f:
            f.write(data)
    return root


def tasks_file(root):
    return os.path.join(root, "00_タスク管理", "data", "tasks.json")


def rd(path):
    with open(path, "rb") as f:
        return f.read()


def env_for(root):
    env = {k: v for k, v in os.environ.items() if k not in ("AI_BUNSHIN_HOME", "CLAUDE_PROJECT_DIR")}
    env["AI_BUNSHIN_HOME"] = root
    env["PYTHONUTF8"] = "1"
    return env


def run_dash(root, args, stdin=None):
    return subprocess.run([sys.executable, DASH, *args], capture_output=True, text=True, encoding="utf-8",
                          cwd=root, env=env_for(root), input=stdin)


def hook_payload(root):
    return json.dumps({"tool_input": {"file_path": tasks_file(root)}, "cwd": root})


def snap_dir(root):
    """生成物の有無と中身（書き換えていないことの確認用）。"""
    out = {}
    for sub in ("00_タスク管理",):
        for dp, _, fns in os.walk(os.path.join(root, sub)):
            for fn in fns:
                p = os.path.join(dp, fn)
                out[os.path.relpath(p, root)] = rd(p)
    return out


def japanese_no_trace(r, where):
    text = r.stdout + r.stderr
    assert "Traceback" not in text, f"{where}: トレースバックが出ています: {text[-300:]}"
    assert re.search(r"[ぁ-んァ-ン一-龥]", text), f"{where}: 日本語の案内がありません: {text!r}"


# ---------- 1. Windows のパス ----------

def load_module():
    """update_dashboard を一時の本人のフォルダで取り込む（import のとき ROOT が決まる）。"""
    home = make_home()
    os.environ["AI_BUNSHIN_HOME"] = home
    os.environ.pop("CLAUDE_PROJECT_DIR", None)
    sys.path.insert(0, SCRIPTS)
    if "update_dashboard" in sys.modules:
        del sys.modules["update_dashboard"]
    return importlib.import_module("update_dashboard"), home


MOD, MOD_HOME = load_module()


@case
def b1_windows_path_in_daily_is_detected():
    f = MOD.in_daily_dir
    assert f(PureWindowsPath(r"01_スプリント\S001_20261029\daily\20261030_計画.md")) is True
    assert f(PurePosixPath("01_スプリント/S001_20261029/daily/20261030_計画.md")) is True


@case
def b1_file_or_dir_name_that_only_contains_daily_is_not_daily():
    f = MOD.in_daily_dir
    for p in (PureWindowsPath(r"02_成果物\総務\daily_report.md"), PureWindowsPath(r"02_成果物\dailyplan\a.md"),
              PurePosixPath("02_成果物/総務/mydaily/a.md")):
        assert f(p) is False, p
    # 末尾が daily のファイルは「daily フォルダの中」ではない（フォルダの名前を数えるのは、ファイル名を除いた部分）
    assert f(PureWindowsPath(r"02_成果物\総務\daily")) is False


@case
def b1_review_context_excludes_daily_and_lists_others():
    home = make_home()
    d = os.path.join(home, "01_スプリント", "S001_x", "daily")
    os.makedirs(d)
    os.makedirs(os.path.join(home, "02_成果物", "総務"))
    for p in (os.path.join(d, "today_plan.md"), os.path.join(home, "02_成果物", "総務", "daily_report.md")):
        with open(p, "w", encoding="utf-8") as f:
            f.write("x")
    r = run_dash(home, ["--review-context"])
    assert r.returncode == 0, r.stderr
    assert "02_成果物/総務/daily_report.md" in r.stdout, r.stdout
    assert "today_plan.md" not in r.stdout, r.stdout


@case
def b1_no_other_slash_daily_string_check_left():
    src = open(DASH, encoding="utf-8").read()
    assert '"/daily/" not in str(' not in src and "'/daily/' not in str(" not in src


# ---------- 2. BOM ----------

NORM_TS = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")


def board_text(root):
    with open(os.path.join(root, "00_タスク管理", "タスクボード.md"), encoding="utf-8") as f:
        return NORM_TS.sub("<TS>", f.read())


@case
def b2_bom_config_and_tasks_are_read_same_as_without_bom():
    plain = make_home()
    bom = make_home(config_bom=True, tasks_bom=True)
    r1 = run_dash(plain, ["--today", "2026-11-02"])
    r2 = run_dash(bom, ["--today", "2026-11-02"])
    assert r1.returncode == 0, r1.stderr
    assert r2.returncode == 0, r2.stderr
    assert "Traceback" not in r2.stderr
    assert board_text(plain) == board_text(bom)
    assert r1.stdout.split("\n")[0] == r2.stdout.split("\n")[0]


@case
def b2_bom_only_config_and_only_tasks():
    for kw in ({"config_bom": True}, {"tasks_bom": True}):
        home = make_home(**kw)
        r = run_dash(home, ["--today", "2026-11-02"])
        assert r.returncode == 0 and "Traceback" not in r.stderr, (kw, r.stderr)
        assert "テストAI" in board_text(home) or "テスト" in r.stdout


@case
def b2_bom_old_schema_tasks_migrates_and_stays_readable():
    t = copy.deepcopy(TASKS)
    home = make_home(tasks=t, tasks_bom=True)
    r = run_dash(home, ["--today", "2026-11-02"])
    assert r.returncode == 0, r.stderr
    after = rd(tasks_file(home))
    json.loads(after.decode("utf-8-sig"))   # 読める形で残っている
    assert b'"schema_version"' in after


@case
def b2_bom_settings_json_in_setup_settings():
    home = os.path.join(BASE, "setup_bom")
    os.makedirs(os.path.join(home, ".claude"))
    with open(os.path.join(home, ".claude", "settings.json"), "wb") as f:
        f.write((BOM + json.dumps({"enabledPlugins": {"ai-bunshin@x": True}})).encode("utf-8"))
    r = subprocess.run([sys.executable, SETUP_SETTINGS, home], capture_output=True, text=True, encoding="utf-8",
                       env=dict(os.environ, PYTHONUTF8="1"))
    assert r.returncode == 0, r.stderr
    cur = json.loads(rd(os.path.join(home, ".claude", "settings.json")).decode("utf-8-sig"))
    assert cur["permissions"]["deny"], cur
    assert "ai-bunshin@x" in cur["enabledPlugins"]


@case
def b2_broken_settings_json_in_setup_settings_is_japanese_and_untouched():
    home = os.path.join(BASE, "setup_broken")
    os.makedirs(os.path.join(home, ".claude"))
    p = os.path.join(home, ".claude", "settings.json")
    with open(p, "w", encoding="utf-8") as f:
        f.write("{ broken")
    r = subprocess.run([sys.executable, SETUP_SETTINGS, home], capture_output=True, text=True, encoding="utf-8",
                       env=dict(os.environ, PYTHONUTF8="1"))
    assert r.returncode != 0
    japanese_no_trace(r, "setup_settings")
    assert rd(p) == b"{ broken"


@case
def b2_watch_check_reads_bom_config():
    import watch_check
    home = make_home(config_raw=json.dumps({"owner": "x", "auto": {"max_minutes": {"plan": 17}}}), config_bom=True)
    assert watch_check.minutes_for(home, "plan") == 17


# ---------- 3. 壊れた入力 ----------

def good_tasks(**project):
    t = copy.deepcopy(TASKS)
    t["project"].update(project)
    return t


def with_ds(ds):
    t = copy.deepcopy(TASKS)
    t["daily_sprints"] = ds
    return t


def with_sprints(sp):
    t = copy.deepcopy(TASKS)
    t["sprints"] = sp
    return t


BAD_TASKS = {
    "壊れた JSON": dict(tasks_raw="{ \"project\": "),
    "空のファイル": dict(tasks_raw=""),
    "空白だけ": dict(tasks_raw="  \n"),
    "配列で始まる": dict(tasks_raw="[]"),
    "null": dict(tasks_raw="null"),
    "daily_sprints に date が無い": dict(tasks=with_ds([{"planned": ["T001"]}])),
    "daily_sprints の date が日付でない": dict(tasks=with_ds([{"date": "11/2", "planned": []}])),
    "daily_sprints が一覧でない": dict(tasks=with_ds({"date": "2026-11-02"})),
    "daily_sprints の中身が辞書でない": dict(tasks=with_ds(["2026-11-02"])),
    "planned が文字": dict(tasks=with_ds([{"date": "2026-11-02", "planned": "T001"}])),
    "capacity が文字": dict(tasks=with_ds([{"date": "2026-11-02", "capacity": "たくさん", "planned": []}])),
    "committed が文字": dict(tasks=with_ds([{"date": "2026-11-02", "committed": "x", "planned": []}])),
    "sprints に start が無い": dict(tasks=with_sprints([{"id": "S001", "end": "2026-11-06"}])),
    "sprints に id が無い": dict(tasks=with_sprints([{"start": "2026-11-02", "end": "2026-11-06"}])),
    "sprints の end が日付でない": dict(tasks=with_sprints([{"id": "S001", "start": "2026-11-02", "end": "来週"}])),
    "sprints が一覧でない": dict(tasks=with_sprints("S001")),
    "daily_capacity_default が 0": dict(tasks=good_tasks(daily_capacity_default=0)),
    "daily_capacity_default が文字": dict(tasks=good_tasks(daily_capacity_default="たくさん")),
    "daily_capacity_default が null": dict(tasks=good_tasks(daily_capacity_default=None)),
    "daily_capacity_default が負": dict(tasks=good_tasks(daily_capacity_default=-3)),
    "holidays が日付でない": dict(tasks=good_tasks(holidays=["正月"])),
    "holidays が一覧でない": dict(tasks=good_tasks(holidays="2026-11-03")),
    "project が一覧": dict(tasks={**copy.deepcopy(TASKS), "project": []}),
    "tasks が辞書": dict(tasks={**copy.deepcopy(TASKS), "tasks": {}}),
    "progress が文字": dict(tasks={**copy.deepcopy(TASKS), "tasks": [{**TASKS["tasks"][0], "progress": "半分"}]}),
    "due が数": dict(tasks={**copy.deepcopy(TASKS), "tasks": [{**TASKS["tasks"][0], "due": 20261105}]}),
}


@case
def b3_bad_tasks_json_manual_run_is_japanese_and_untouched():
    bad = []
    for name, kw in BAD_TASKS.items():
        home = make_home(**kw)
        before = snap_dir(home)
        r = run_dash(home, ["--today", "2026-11-02"])
        try:
            assert r.returncode == 1, f"終了コード {r.returncode}（1 のはず）"
            japanese_no_trace(r, name)
            assert snap_dir(home) == before, "00_タスク管理 の中身が変わった"
        except AssertionError as e:
            bad.append(f"{name}: {e}")
    assert not bad, "\n      " + "\n      ".join(bad)


@case
def b3_bad_tasks_json_other_modes_do_not_show_traceback():
    bad = []
    for name, kw in BAD_TASKS.items():
        for mode in (["--plan-context"], ["--review-context"], ["--today-status"]):
            home = make_home(**kw)
            before = snap_dir(home)
            r = run_dash(home, mode + ["--today", "2026-11-02"])
            try:
                assert r.returncode == 1, f"終了コード {r.returncode}"
                japanese_no_trace(r, name + " " + mode[0])
                assert snap_dir(home) == before
            except AssertionError as e:
                bad.append(f"{name} {mode[0]}: {e}")
    assert not bad, "\n      " + "\n      ".join(bad)


@case
def b4_bad_tasks_json_session_gives_message_and_exit_0():
    """SessionStart：止めない（終了コード 0）で、本人に伝える案内を additionalContext に入れる。"""
    bad = []
    for name, kw in BAD_TASKS.items():
        home = make_home(**kw)
        before = snap_dir(home)
        r = run_dash(home, ["--session", "--today", "2026-11-02"])
        try:
            assert r.returncode == 0, f"終了コード {r.returncode}"
            assert "Traceback" not in r.stdout + r.stderr
            out = json.loads(r.stdout)
            ctx = out["hookSpecificOutput"]["additionalContext"]
            assert re.search(r"[ぁ-んァ-ン一-龥]", ctx) and "tasks.json" in ctx, ctx
            assert snap_dir(home) == before
        except (AssertionError, ValueError, KeyError) as e:
            bad.append(f"{name}: {e}")
    assert not bad, "\n      " + "\n      ".join(bad)


@case
def b4_bad_tasks_json_hook_keeps_asking_claude_to_fix_with_exit_2():
    """PostToolUse：tasks.json を書いた直後に壊れていたら、今までどおり終了コード 2（Claude に直させる）。トレースバックは出さない。"""
    bad = []
    for name, kw in BAD_TASKS.items():
        home = make_home(**kw)
        before = snap_dir(home)
        r = run_dash(home, ["--hook", "--today", "2026-11-02"], stdin=hook_payload(home))
        try:
            assert r.returncode == 2, f"終了コード {r.returncode}（2 のはず）"
            japanese_no_trace(r, name)
            assert snap_dir(home) == before
        except AssertionError as e:
            bad.append(f"{name}: {e}")
    assert not bad, "\n      " + "\n      ".join(bad)


BAD_CONFIG = {
    "壊れた JSON": "{ \"owner\": ",
    "空のファイル": "",
    "配列で始まる": "[]",
    "departments が文字": json.dumps({**CONFIG, "departments": "総務"}),
    "team.max が文字": json.dumps({**CONFIG, "team": {"max": "たくさん"}}),
    "team.off が数": json.dumps({**CONFIG, "team": {"off": 3}}),
    "owner が一覧": json.dumps({**CONFIG, "owner": ["a"]}),
}


@case
def b3_bad_config_manual_run_is_japanese_and_untouched():
    bad = []
    for name, raw in BAD_CONFIG.items():
        home = make_home(config_raw=raw)
        before = snap_dir(home)
        r = run_dash(home, ["--today", "2026-11-02"])
        try:
            assert r.returncode == 1, f"終了コード {r.returncode}"
            japanese_no_trace(r, name)
            assert "config.json" in r.stderr + r.stdout
            assert snap_dir(home) == before
        except AssertionError as e:
            bad.append(f"{name}: {e}")
    assert not bad, "\n      " + "\n      ".join(bad)


@case
def b4_bad_config_hook_and_session_do_not_stop_claude():
    bad = []
    for name, raw in BAD_CONFIG.items():
        for mode in ("--session", "--hook"):
            home = make_home(config_raw=raw)
            before = snap_dir(home)
            r = run_dash(home, [mode, "--today", "2026-11-02"], stdin=hook_payload(home) if mode == "--hook" else None)
            try:
                assert r.returncode == 0, f"終了コード {r.returncode}（0 のはず）"
                assert "Traceback" not in r.stdout + r.stderr
                ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
                assert "config.json" in ctx and re.search(r"[ぁ-んァ-ン一-龥]", ctx), ctx
                assert snap_dir(home) == before
            except (AssertionError, ValueError, KeyError) as e:
                bad.append(f"{name} {mode}: {e}")
    assert not bad, "\n      " + "\n      ".join(bad)


@case
def b3_capacity_null_zero_and_default_ok_do_not_break_real_shaped_data():
    """本物のデータにある形（計画なしの日は capacity が null）は、エラーにしない。0 も落とさない。"""
    for cap in (None, 0, 8, 7.5):
        t = with_ds([{"date": "2026-10-30", "capacity": cap, "committed": 0, "planned": [], "status": "計画なし"}])
        home = make_home(tasks=t)
        r = run_dash(home, ["--today", "2026-11-02"])
        assert r.returncode == 0, (cap, r.stderr)
        assert "Traceback" not in r.stderr


@case
def b3_unexpected_exception_is_japanese_not_traceback():
    """validate をすり抜けた想定外の例外でも、英語のトレースバックを見せない（手動＝1、hook＝1、session＝0）。"""
    home = MOD_HOME
    saved_argv = sys.argv
    saved_run = MOD.run

    def boom(today):
        raise KeyError("start")

    MOD.run = boom
    try:
        for argv, want in ((["x"], 1), (["x", "--session"], 0)):
            sys.argv = argv
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = MOD.main()
            text = out.getvalue() + err.getvalue()
            assert rc == want, (argv, rc, text)
            assert "Traceback" not in text, text
            assert re.search(r"[ぁ-んァ-ン一-龥]", text), text
    finally:
        MOD.run = saved_run
        sys.argv = saved_argv


# ---------- T069 の直し（部下D の確かめへの対応） ----------

def data_file(root, name):
    return os.path.join(root, "00_タスク管理", "data", name)


@case
def t69_1_snapshot_with_wrong_shape_or_broken_json_is_rebuilt():
    """.snapshot.json が JSON として正しくても形が違う・壊れているときは、前回なしとして扱う（ずっと落ち続けない）。"""
    bad = []
    for name, raw in (("値が文字", '{"T001": "x"}'), ("配列", '[1, 2]'), ("壊れた JSON", '{ "T001": '), ("空", ""),
                      ("値が配列", '{"T001": [1]}')):
        home = make_home()
        r0 = run_dash(home, ["--today", "2026-11-02"])   # 最初の記録（snapshot ができる）
        with open(data_file(home, ".snapshot.json"), "w", encoding="utf-8") as f:
            f.write(raw)
        hist_before = os.path.exists(data_file(home, "history.jsonl"))
        for n in (1, 2):   # 2回目も落ちない（直らないままにならない）
            r = run_dash(home, ["--today", "2026-11-02"])
            if r.returncode != 0 or "Traceback" in r.stderr:
                bad.append(f"{name} {n}回目: 終了コード {r.returncode} {r.stderr[-200:]}")
        snap = json.loads(rd(data_file(home, ".snapshot.json")).decode("utf-8"))
        if not (isinstance(snap, dict) and all(isinstance(v, dict) for v in snap.values())):
            bad.append(f"{name}: snapshot が作り直されていない")
        if not hist_before and os.path.exists(data_file(home, "history.jsonl")):
            bad.append(f"{name}: 前回なしのはずなのに history.jsonl に全部が「新規」で出た")
    assert not bad, "\n      " + "\n      ".join(bad)


@case
def t69_4_history_without_trailing_newline_gets_one_before_append():
    home = make_home()
    run_dash(home, ["--today", "2026-11-02", "--now", "2026-11-02 09:00"])
    first = json.dumps({"at": "2026-11-01 09:00", "id": "T001", "change": "新規", "title": "a", "status": "ToDo"}, ensure_ascii=False)
    with open(data_file(home, "history.jsonl"), "w", encoding="utf-8") as f:
        f.write(first)   # 改行で終わっていない
    t = copy.deepcopy(TASKS)
    t["tasks"].append({"id": "T002", "title": "追加", "status": "ToDo", "assignee": "dev-a", "points": 1, "priority": 2})
    with open(tasks_file(home), "w", encoding="utf-8") as f:
        json.dump(t, f, ensure_ascii=False)
    r = run_dash(home, ["--today", "2026-11-02", "--now", "2026-11-02 10:30"])
    assert r.returncode == 0, r.stderr
    lines = [x for x in open(data_file(home, "history.jsonl"), encoding="utf-8").read().split("\n") if x.strip()]
    assert len(lines) == 2, lines
    assert [json.loads(x)["id"] for x in lines] == ["T001", "T002"], lines


@case
def t69_2_starter_settings_json_with_bom_is_recognised_as_setup_pending():
    folder = os.path.join(BASE, "starter_bom")
    os.makedirs(os.path.join(folder, ".claude"))
    os.makedirs(os.path.join(BASE, "fakehome"), exist_ok=True)
    with open(os.path.join(folder, ".claude", "settings.json"), "wb") as f:
        f.write((BOM + json.dumps({"enabledPlugins": {"ai-bunshin@market": True}})).encode("utf-8"))
    env = {k: v for k, v in os.environ.items() if k not in ("AI_BUNSHIN_HOME", "CLAUDE_PROJECT_DIR")}
    env.update(HOME=os.path.join(BASE, "fakehome"), USERPROFILE=os.path.join(BASE, "fakehome"), PYTHONUTF8="1",
               CLAUDE_PROJECT_DIR=folder)
    r = subprocess.run([sys.executable, DASH, "--session"], capture_output=True, text=True, encoding="utf-8", cwd=folder, env=env)
    assert r.returncode == 0, r.stderr
    assert "初回セットアップ" in r.stdout, r.stdout


@case
def t69_3_list_note_fails_in_japanese_and_tasks_json_bytes_stay_same():
    """検査を通ったあと Excel で落ちる値（points が { }。note・title などの文字の項目は読むときに文字にするので落ちない：T159）でも、
    tasks.json は書き換えない（移しは最後）。英語の ValueError は出さない。"""
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        print("      （openpyxl が無いので飛ばす）")
        return
    t = copy.deepcopy(TASKS)
    t["tasks"][0]["points"] = {"一覧": "ではない"}
    home = make_home(tasks=t)   # schema_version が無い＝移しの対象
    before = rd(tasks_file(home))
    for mode in ([], ["--session"], ["--plan-context"]):
        r = run_dash(home, ["--today", "2026-11-02"] + mode)
        text = r.stdout + r.stderr
        assert "Cannot convert" not in text and "Traceback" not in text, text[-300:]
        assert re.search(r"[ぁ-んァ-ン一-龥]", text) and "Excel" in text, text
        assert rd(tasks_file(home)) == before, f"tasks.json が書き換わった {mode}"
        assert not [f for f in os.listdir(os.path.dirname(tasks_file(home))) if ".bak_" in f], "控えが作られた"
    # 直したら移しが行われる（移しは Excel・ボード・お願いを書き終えたあと）
    t["tasks"][0]["points"] = 2
    with open(tasks_file(home), "w", encoding="utf-8") as f:
        json.dump(t, f, ensure_ascii=False)
    r = run_dash(home, ["--today", "2026-11-02"])
    assert r.returncode == 0, r.stderr
    assert b'"schema_version"' in rd(tasks_file(home))
    assert "新しい形式" in r.stdout


@case
def t69_5_unexpected_exception_is_logged_to_auto_logs_and_message_names_it():
    saved_argv, saved_run, saved_auto, saved_root = sys.argv, MOD.run, MOD.AUTO_DIR, MOD.ROOT

    def boom(today):
        raise KeyError("start")

    # 他のテストのログ（固定日付が本物の今日と同じ日だと同じファイルになる）と混ぜないよう、このテストだけの置き場にする
    own_root = type(MOD.ROOT)(os.path.join(BASE, "t69_5_home"))
    MOD.ROOT = own_root
    MOD.AUTO_DIR = own_root / "scripts" / "auto"
    MOD.run = boom
    try:
        sys.argv = ["x", "--today", "2026-11-02", "--now", "2026-11-02 10:00"]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = MOD.main()
        text = out.getvalue() + err.getvalue()
        assert rc == 1, (rc, text)
        logdir = os.path.join(str(own_root), "scripts", "auto", "logs")
        files = [f for f in os.listdir(logdir) if f == "dashboard_error_20261102.log"]   # --now の日付で名前が決まる
        assert files, os.listdir(logdir) if os.path.isdir(logdir) else "logs が無い"
        body = open(os.path.join(logdir, files[0]), encoding="utf-8").read()
        assert "KeyError" in body and "boom" in body and "update_dashboard.py:" in body, body
        assert "scripts/auto/logs/" + files[0] in text, text
        assert "Traceback" not in text
        # 2回目は追記（上書きしない）。同じ日付を渡して、同じファイルに書かせる
        sys.argv = ["x", "--today", "2026-11-02", "--now", "2026-11-02 10:00"]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            MOD.main()
        body2 = open(os.path.join(logdir, files[0]), encoding="utf-8").read()
        assert body2.count("KeyError") >= 2 and body2.startswith(body[:50])
        assert "--today" in body and "--now" in body and "2026-11-02 10:00" in body.split("\n")[0]   # 日時は入る
        assert "--today 2026" not in body and "--now 2026" not in body, body   # 引数の値は入れない
        # ログが書けないとき（保存先が普通のファイル）も止まらない
        blocker = os.path.join(BASE, "not_a_dir")
        with open(blocker, "w") as f:
            f.write("x")
        MOD.AUTO_DIR = type(MOD.AUTO_DIR)(blocker)
        sys.argv = ["x"]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = MOD.main()
        text = out.getvalue() + err.getvalue()
        assert rc == 1 and "Traceback" not in text and re.search(r"[ぁ-んァ-ン一-龥]", text), (rc, text)
        assert "ログ" in text and "この文面を AI に見せてください" in text and "とログ" not in text, text
    finally:
        MOD.run, MOD.AUTO_DIR, MOD.ROOT, sys.argv = saved_run, saved_auto, saved_root, saved_argv


SECRET = "秘密のタスク名ZZ9"


@case
def t69b_log_has_no_exception_text_paths_or_arg_values():
    """ログに入れるのは、日時・オプション名・例外の型名・ファイル名:行番号 だけ。タスクの文字が例外の文面に入っても残らない。"""
    saved_argv, saved_run = sys.argv, MOD.run

    def boom2(today):
        raise KeyError(SECRET)   # 例外の文面にタスクの文字が入る

    MOD.run = boom2
    try:
        sys.argv = ["x", "--today", "2031-05-05", "--plan-context"]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            MOD.main()
        logdir = os.path.join(MOD_HOME, "scripts", "auto", "logs")
        body = ""
        for fn in os.listdir(logdir):
            body += open(os.path.join(logdir, fn), encoding="utf-8").read()
        assert "KeyError" in body, body
        assert SECRET not in body and "raise KeyError" not in body, body            # 文面・ソースの行は書かない
        assert "2031-05-05" not in body and "--today" in body and "--plan-context" in body, body   # 引数は名前だけ
        assert "/" not in body.replace("scripts/auto/logs", ""), body                 # パス（プラグイン・本人のフォルダ）は書かない
        assert SECRET not in out.getvalue() + err.getvalue()
    finally:
        MOD.run, sys.argv = saved_run, saved_argv


@case
def t69b_excel_failure_is_logged_without_task_text_and_message_names_log():
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        print("      （openpyxl が無いので飛ばす）")
        return
    t = copy.deepcopy(TASKS)
    t["tasks"][0]["points"] = {SECRET: 1}   # 文字の項目（note など）は読むときに文字にするので、Excel で落ちる別の値を使う（T159）
    home = make_home(tasks=t)
    r = run_dash(home, ["--today", "2026-11-02", "--now", "2026-11-02 10:00"])
    assert r.returncode == 1, r.stderr
    assert "scripts/auto/logs/dashboard_error_20261102.log" in r.stderr, r.stderr
    assert SECRET not in r.stdout + r.stderr or "Cannot convert" not in r.stderr
    body = open(os.path.join(home, "scripts", "auto", "logs", "dashboard_error_20261102.log"), encoding="utf-8").read()
    assert SECRET not in body and "ValueError" in body and "Cannot convert" not in body, body


@case
def t69b_history_with_broken_lines_does_not_stop_plan_context():
    home = make_home()
    run_dash(home, ["--today", "2026-11-02"])
    good = json.dumps({"at": "2026-11-01 09:00", "id": "T001", "change": "新規", "title": "a", "status": "ToDo"}, ensure_ascii=False)
    with open(data_file(home, "history.jsonl"), "w", encoding="utf-8") as f:
        f.write("{ 壊れた行\n" + good + "\n[1, 2]\n{\"at\": 5}\n\n{\"at\": \"2026-11-02 08:00\", \"change\": \"新規\"}\n")
    for mode in (["--plan-context"], ["--review-context"]):
        r = run_dash(home, ["--today", "2026-11-02"] + mode)
        assert r.returncode == 0, (mode, r.stderr[-300:])
        assert "Traceback" not in r.stderr


# ---------- 既定値 ----------

@case
def default_capacity_is_one_place_template_code_and_plan_skill_agree():
    tpl = json.load(open(TEMPLATE_TASKS, encoding="utf-8"))["project"]["daily_capacity_default"]
    assert MOD.DEFAULT_DAILY_CAPACITY == tpl, (MOD.DEFAULT_DAILY_CAPACITY, tpl)
    plan = open(os.path.join(PLUGIN, "skills", "daily-plan", "SKILL.md"), encoding="utf-8").read()
    assert f"初期値 {tpl:g}pt" in plan, "daily-plan の初期値の記述がコードと違う"


@case
def default_capacity_is_used_when_project_has_no_value():
    t = copy.deepcopy(TASKS)
    t["project"].pop("daily_capacity_default")
    home = make_home(tasks=t)
    r = run_dash(home, ["--today", "2026-11-02"])
    assert r.returncode == 0, r.stderr
    assert f"{MOD.DEFAULT_DAILY_CAPACITY:.1f}pt/日（初期値）" in r.stdout, r.stdout.split("\n")[0]
    assert "8.0pt/日（初期値）" in r.stdout


# ---------- 5. 時刻を外から渡す ----------

def plan_home():
    """4日分の計画のある日付つきデータ（追加でタスクを取れるかの判断が時刻で変わる）。"""
    t = copy.deepcopy(TASKS)
    t["sprints"] = [{"id": "S001", "goal": "g", "start": "2026-10-26", "end": "2026-11-06", "status": "進行中"}]
    t["daily_sprints"] = [{"date": d, "capacity": 8, "committed": 2, "planned": ["T001"], "status": "振り返り済み"}
                          for d in ("2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30")]
    t["daily_sprints"].append({"date": "2026-11-02", "capacity": 8, "committed": 2, "planned": ["T001"], "status": "実行中"})
    return make_home(tasks=t)


def board_raw(root):
    with open(os.path.join(root, "00_タスク管理", "タスクボード.md"), encoding="utf-8") as f:
        return f.read()


def requests_raw(root):
    d = os.path.join(root, "00_タスク管理")
    for fn in os.listdir(d):
        if fn.endswith("お願い.md"):
            return open(os.path.join(d, fn), encoding="utf-8").read()
    return ""


@case
def b5_now_option_sets_clock_in_plan_context():
    home = plan_home()
    morning = run_dash(home, ["--today", "2026-11-02", "--now", "2026-11-02 10:05", "--plan-context"])
    evening = run_dash(home, ["--today", "2026-11-02", "--now", "17:10", "--plan-context"])
    assert morning.returncode == 0, morning.stderr
    assert "現在時刻: 10:05" in morning.stdout, morning.stdout
    assert "現在時刻: 17:10" in evening.stdout
    assert "不可（16:30 を過ぎた）" in evening.stdout and "不可（16:30 を過ぎた）" not in morning.stdout


@case
def b5_fixed_today_and_now_give_same_output_twice():
    home = make_home()
    args = ["--today", "2026-11-02", "--now", "2026-11-02 10:00"]
    run_dash(home, args)   # 1回目は tasks.json の形式の移し（案内が1回だけ出る）があるので、比べるのは2回目と3回目
    outs = []
    for _ in range(2):
        r = run_dash(home, args)
        assert r.returncode == 0, r.stderr
        outs.append((r.stdout, board_raw(home), requests_raw(home)))
    assert outs[0] == outs[1]
    assert "2026-11-02 10:00" in outs[0][1]


@case
def b5_history_uses_the_given_time():
    home = make_home()
    run_dash(home, ["--today", "2026-11-02", "--now", "2026-11-02 09:00"])   # 最初の記録（snapshot）
    t = copy.deepcopy(TASKS)
    t["tasks"].append({"id": "T002", "title": "追加", "status": "ToDo", "assignee": "dev-a", "points": 1, "priority": 2})
    with open(tasks_file(home), "w", encoding="utf-8") as f:
        json.dump(t, f, ensure_ascii=False)
    r = run_dash(home, ["--today", "2026-11-02", "--now", "2026-11-02 10:30"])
    assert r.returncode == 0, r.stderr
    hist = open(os.path.join(home, "00_タスク管理", "data", "history.jsonl"), encoding="utf-8").read()
    assert '"at": "2026-11-02 10:30"' in hist, hist


@case
def b5_bad_today_or_now_is_japanese():
    home = make_home()
    for args in (["--today", "2026/11/02"], ["--now", "25:99"], ["--now", "あした"]):
        r = run_dash(home, args)
        assert r.returncode != 0
        assert "Traceback" not in r.stderr and re.search(r"[ぁ-んァ-ン一-龥]", r.stderr), (args, r.stderr)


# ---------- 6. ガント ----------

def read_gantt_header(root):
    from openpyxl import load_workbook
    wb = load_workbook(os.path.join(root, "00_タスク管理", "タスク管理.xlsx"))
    return wb["ガント"]["A1"].value or "", wb["ガント"].max_column


def gantt_data(due):
    t = copy.deepcopy(TASKS)
    t["tasks"][0]["due"] = due
    return t


@case
def b6_gantt_cut_is_announced_and_constant_exists():
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        print("      （openpyxl が無いので飛ばす）")
        return
    assert MOD.GANTT_MAX_DAYS == 120
    long_home = make_home(tasks=gantt_data("2027-09-30"))
    r = run_dash(long_home, ["--today", "2026-11-02", "--now", "2026-11-02 10:00"])
    assert r.returncode == 0, r.stderr
    head, ncol = read_gantt_header(long_home)
    assert "表示していません" in head, head
    short_home = make_home(tasks=gantt_data("2026-11-10"))
    run_dash(short_home, ["--today", "2026-11-02", "--now", "2026-11-02 10:00"])
    head2, _ = read_gantt_header(short_home)
    assert "表示していません" not in head2, head2


@case
def b6_gantt_range_helper():
    d = datetime.date
    begin, finish, true_finish = MOD.gantt_range([d(2026, 11, 2)], [d(2027, 9, 30)], d(2026, 11, 2))
    assert (finish - begin).days == MOD.GANTT_MAX_DAYS and true_finish == d(2027, 9, 30)
    begin, finish, true_finish = MOD.gantt_range([d(2026, 11, 2)], [d(2026, 11, 10)], d(2026, 11, 2))
    assert true_finish == finish


# ---------- 6. pip の案内 ----------

def order_ok(text):
    idx = [text.find(k) for k in ("python3 -m pip", "python -m pip", "py -3 -m pip")]
    return all(i >= 0 for i in idx) and idx == sorted(idx)


@case
def b6_pip_guidance_order_matches_hook_in_script_status_and_setup():
    assert order_ok(MOD.NO_OPENPYXL_NOTE), MOD.NO_OPENPYXL_NOTE
    status = open(os.path.join(PLUGIN, "skills", "status", "SKILL.md"), encoding="utf-8").read()
    line = next(x for x in status.splitlines() if "openpyxl" in x and "pip" in x)
    assert order_ok(line), line
    setup = open(os.path.join(PLUGIN, "skills", "setup", "SKILL.md"), encoding="utf-8").read()
    row = next(x for x in setup.splitlines() if x.startswith("| openpyxl "))
    assert order_ok(row), row
    # hook の順番（run_py.sh）と同じ：python3 → python → py -3
    sh = open(os.path.join(SCRIPTS, "run_py.sh"), encoding="utf-8").read()
    assert sh.find("is_py3 python3") < sh.find("is_py3 python;") < sh.find("is_py3 py -3")


# ---------- 祝日 ----------

@case
def holidays_guidance_in_setup():
    setup = open(os.path.join(PLUGIN, "skills", "setup", "SKILL.md"), encoding="utf-8").read()
    assert "雛形の holidays は空" in setup, "setup に、祝日を入れる案内がありません"
    tpl = json.load(open(TEMPLATE_TASKS, encoding="utf-8"))
    assert tpl["project"]["holidays"] == []


print(f"\n失敗 {fails} 件")
sys.exit(1 if fails else 0)
