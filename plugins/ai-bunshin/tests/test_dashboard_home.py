"""update_dashboard.py の hook が「本人のフォルダでだけ」動くことのテスト。
- --session：本人のフォルダ（とその下）→ いつもの出力／準備前（enabledPlugins だけ）→ 初回セットアップの案内／無関係のフォルダ → セットアップを促さない
- --hook：本人の tasks.json → 動く／ほかの tasks.json → 何もしない
実行：python3 tests/test_dashboard_home.py（失敗があれば終了コード1）"""
import json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.abspath(os.path.join(HERE, "..", "scripts", "update_dashboard.py"))

BASE = os.path.realpath(tempfile.mkdtemp(prefix="homechk_"))
FAKE_HOME = os.path.join(BASE, "home")            # ユーザー全体の設定（ホームの .claude）を拾わないよう、ホームも一時フォルダにする
os.makedirs(FAKE_HOME)
R = os.path.join(BASE, "owner")                    # 本人のフォルダ
os.makedirs(os.path.join(R, "設定"))
os.makedirs(os.path.join(R, "00_タスク管理", "data"))
os.makedirs(os.path.join(R, "05_開発", "x"))
TASKS = {"project": {"name": "テストAI", "daily_capacity_default": 8.0, "holidays": []},
         "daily_sprints": [], "sprints": [],
         "tasks": [{"id": "T001", "title": "テスト用タスク", "status": "ToDo", "assignee": "dev-a", "type": "開発",
                    "reviewer": "dev-b", "points": 2, "department": "総務", "priority": 1}]}
json.dump({"owner": "テスト", "owner_call": "テストさん", "ai_name": "テストAI", "departments": ["総務"]},
          open(os.path.join(R, "設定", "config.json"), "w", encoding="utf-8"), ensure_ascii=False)
json.dump(TASKS, open(os.path.join(R, "00_タスク管理", "data", "tasks.json"), "w", encoding="utf-8"), ensure_ascii=False)
# 開発案件の中の別の tasks.json
OTHER = os.path.join(R, "05_開発", "x", "tasks.json")
json.dump({"tasks": []}, open(OTHER, "w", encoding="utf-8"))

PREP = os.path.join(BASE, "prep")                  # 準備前：enabledPlugins だけがある starter のフォルダ
os.makedirs(os.path.join(PREP, ".claude"))
os.makedirs(os.path.join(PREP, "sub"))
json.dump({"enabledPlugins": {"ai-bunshin@ai-bunshin-marketplace": True}},
          open(os.path.join(PREP, ".claude", "settings.json"), "w", encoding="utf-8"))
OTHERDIR = os.path.join(BASE, "other")             # 無関係のフォルダ
os.makedirs(OTHERDIR)
# 別の人の tasks.json（本人のフォルダとは別のところにある）
STRANGER = os.path.join(BASE, "stranger")
os.makedirs(os.path.join(STRANGER, "00_タスク管理", "data"))
os.makedirs(os.path.join(STRANGER, "設定"))
json.dump({"owner": "他人"}, open(os.path.join(STRANGER, "設定", "config.json"), "w", encoding="utf-8"))
json.dump(TASKS, open(os.path.join(STRANGER, "00_タスク管理", "data", "tasks.json"), "w", encoding="utf-8"))


def run(args, cwd, stdin="", project_dir=None):
    env = {k: v for k, v in os.environ.items() if k not in ("AI_BUNSHIN_HOME", "CLAUDE_PROJECT_DIR")}
    env["HOME"] = FAKE_HOME
    env["CLAUDE_PROJECT_DIR"] = project_dir if project_dir is not None else cwd
    return subprocess.run([sys.executable, SCRIPT, *args], input=stdin, capture_output=True, text=True, cwd=cwd, env=env)


fails = 0


def check(name, ok, detail=""):
    global fails
    print(("OK   " if ok else "NG   ") + name + ("" if ok else f"  ← {detail}"))
    if not ok:
        fails += 1


def ctx_of(r):
    try:
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    except (ValueError, KeyError):
        return ""


# --session ---------------------------------------------------------------
for label, cwd in (("本人のフォルダ", R), ("本人のフォルダの下（05_開発/x）", os.path.join(R, "05_開発", "x"))):
    r = run(["--session"], cwd)
    c = ctx_of(r)
    check(f"session：{label} → いつもの出力", r.returncode == 0 and "タスク" in c and "セットアップ" not in c,
          r.stdout + r.stderr)
    check(f"session：{label} → セットアップを促さない", "セットアップ" not in c and "仕事用フォルダではない" not in c, c)
check("session：本人のフォルダで Excel が作られる", os.path.exists(os.path.join(R, "00_タスク管理", "タスクボード.md")))

for label, cwd in (("準備前のフォルダ", PREP), ("準備前のフォルダの下", os.path.join(PREP, "sub"))):
    r = run(["--session"], cwd)
    c = ctx_of(r)
    check(f"session：{label} → 初回セットアップの案内", r.returncode == 0 and "初回セットアップ" in c, r.stdout + r.stderr)

r = run(["--session"], OTHERDIR)
c = ctx_of(r)
check("session：無関係のフォルダ → セットアップを始めてと言わない", r.returncode == 0 and "セットアップ" not in c.replace("仕事用フォルダではない", "") and "初回" not in c, r.stdout + r.stderr)
check("session：無関係のフォルダ → フォルダ違いの1行が出る", "仕事用フォルダではない" in c, c)
check("session：無関係のフォルダに何も作らない", os.listdir(OTHERDIR) == [], str(os.listdir(OTHERDIR)))

# ホーム全体の設定に ai-bunshin が入っていても、ホームの下のただのフォルダは「準備前」扱いにしない
os.makedirs(os.path.join(FAKE_HOME, ".claude"))
json.dump({"enabledPlugins": {"ai-bunshin@x": True}}, open(os.path.join(FAKE_HOME, ".claude", "settings.json"), "w"))
HOMESUB = os.path.join(FAKE_HOME, "proj")
os.makedirs(HOMESUB)
r = run(["--session"], HOMESUB)
check("session：ホーム全体の設定だけでは準備前にしない", "初回セットアップ" not in ctx_of(r), r.stdout)

# --hook -----------------------------------------------------------------
def hook(path, cwd, project_dir=None):
    return run(["--hook"], cwd, stdin=json.dumps({"tool_input": {"file_path": path}, "cwd": cwd}), project_dir=project_dir)


own = os.path.join(R, "00_タスク管理", "data", "tasks.json")
board = os.path.join(R, "00_タスク管理", "タスクボード.md")
if os.path.exists(board):
    os.remove(board)
r = hook(own, R)
check("hook：本人の tasks.json → 動く", r.returncode == 0 and "PostToolUse" in r.stdout and os.path.exists(board), r.stdout + r.stderr)

os.remove(board)
r = hook("00_タスク管理/data/tasks.json", R)
check("hook：相対パスの本人の tasks.json → 動く", r.returncode == 0 and "PostToolUse" in r.stdout and os.path.exists(board), r.stdout + r.stderr)

os.remove(board)
r = hook(OTHER, os.path.join(R, "05_開発", "x"), project_dir=R)
check("hook：開発案件の tasks.json → 何もしない", r.returncode == 0 and r.stdout == "" and not os.path.exists(board), r.stdout + r.stderr)

stranger_tasks = os.path.join(STRANGER, "00_タスク管理", "data", "tasks.json")
r = hook(stranger_tasks, R)
check("hook：別のフォルダの tasks.json → 何もしない", r.returncode == 0 and r.stdout == "" and not os.path.exists(board), r.stdout + r.stderr)
check("hook：別のフォルダに何も作らない", not os.path.exists(os.path.join(STRANGER, "00_タスク管理", "タスクボード.md")))

r = hook(OTHER, OTHERDIR)
check("hook：無関係のフォルダ → 何もしない", r.returncode == 0 and r.stdout == "" and r.stderr == "", r.stdout + r.stderr)

# 手動実行（本人のフォルダが見つからない）
r = run([], OTHERDIR)
check("手動：見つからないときの案内文", r.returncode == 1 and "00_タスク管理 があるフォルダで Claude を開き直してください" in r.stderr, r.stderr)

print()
print(f"失敗 {fails} 件")
sys.exit(1 if fails else 0)
