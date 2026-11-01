"""openpyxl が入っていない環境でも update_dashboard.py が止まらないことのテスト。
openpyxl は消さず、import を失敗させた状態（sys.modules['openpyxl'] = None）でサブプロセスを動かす。
実行：python3 tests/test_dashboard_no_openpyxl.py（失敗があれば終了コード1）"""
import json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.abspath(os.path.join(HERE, "..", "scripts", "update_dashboard.py"))

R = tempfile.mkdtemp(prefix="dashtest_")
os.makedirs(os.path.join(R, "設定"))
os.makedirs(os.path.join(R, "00_タスク管理", "data"))
json.dump({"owner": "テスト", "owner_call": "テストさん", "ai_name": "テストAI", "departments": ["総務"]},
          open(os.path.join(R, "設定", "config.json"), "w", encoding="utf-8"), ensure_ascii=False)
json.dump({"project": {"name": "テストAI", "daily_capacity_default": 8.0, "holidays": []},
           "daily_sprints": [], "sprints": [],
           "tasks": [{"id": "T001", "title": "テスト用タスク", "status": "ToDo", "assignee": "dev-a", "type": "開発",
                      "reviewer": "dev-b", "points": 2, "department": "総務", "priority": 1}]},
          open(os.path.join(R, "00_タスク管理", "data", "tasks.json"), "w", encoding="utf-8"), ensure_ascii=False)

# サブプロセスで openpyxl の import を失敗させてから、本体を __main__ として動かす
LAUNCH = ("import sys, runpy; sys.modules['openpyxl'] = None; "
          "sys.argv = ['update_dashboard.py'] + sys.argv[1:]; "
          "runpy.run_path(%r, run_name='__main__')" % SCRIPT)


def run(args, stdin="", no_openpyxl=True):
    cmd = [sys.executable, "-c", LAUNCH, *args] if no_openpyxl else [sys.executable, SCRIPT, *args]
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True, cwd=R,
                          env={**os.environ, "AI_BUNSHIN_HOME": R, "CLAUDE_PROJECT_DIR": R})


fail = 0


def check(cond, msg):
    global fail
    if not cond:
        fail += 1
        print("NG", msg)


BOARD = os.path.join(R, "00_タスク管理", "タスクボード.md")
REQ = os.path.join(R, "00_タスク管理", "テストさんへのお願い.md")
XLSX = os.path.join(R, "00_タスク管理", "タスク管理.xlsx")
KEY = "openpyxl"

print("## openpyxl なし")
p = run([])
check(p.returncode == 0, f"引数なし：終了コード {p.returncode} / {p.stderr[-300:]}")
check("ModuleNotFoundError" not in p.stderr and "Traceback" not in p.stderr, "引数なし：エラーが出た")
check(KEY in p.stdout and "Excel" in p.stdout, "引数なし：日本語の案内が通常の出力に無い")
check(p.stdout.count("を飛ばしました") == 1, "引数なし：案内が1回だけではない")
check(os.path.exists(BOARD) and os.path.exists(REQ), "タスクボード.md / お願い.md ができていない")
check(not os.path.exists(XLSX), "openpyxl なしなのに xlsx ができた")

open(BOARD, "w").close()  # 空にして、--session で作り直されるかを見る
p = run(["--session"])
check(p.returncode == 0, f"--session：終了コード {p.returncode} / {p.stderr[-300:]}")
try:
    ctx = json.loads(p.stdout)["hookSpecificOutput"]
    check(ctx["hookEventName"] == "SessionStart", "--session：イベント名が違う")
    check(KEY in ctx["additionalContext"] and "T001" in ctx["additionalContext"], "--session：案内かタスク状況が additionalContext に無い")
    check(ctx["additionalContext"].count("を飛ばしました") == 1, "--session：案内が1回だけではない")
except Exception as e:
    check(False, f"--session：出力が JSON ではない {e} {p.stdout[:200]}")
check(os.path.getsize(BOARD) > 0, "--session：タスクボード.md が作り直されていない")

payload = json.dumps({"tool_input": {"file_path": os.path.join(R, "00_タスク管理", "data", "tasks.json")}})
p = run(["--hook"], stdin=payload)
check(p.returncode == 0, f"--hook：終了コード {p.returncode} / {p.stderr[-300:]}")
try:
    check(json.loads(p.stdout)["hookSpecificOutput"]["hookEventName"] == "PostToolUse", "--hook：イベント名が違う")
except Exception as e:
    check(False, f"--hook：出力が JSON ではない {e}")

for mode in ("--plan-context", "--review-context", "--today-status"):
    p = run([mode])
    check(p.returncode == 0 and "Traceback" not in p.stderr, f"{mode}：終了コード {p.returncode} / {p.stderr[-300:]}")

print("## openpyxl あり（入っている環境だけ）")
try:
    import openpyxl  # noqa: F401
    have = True
except ImportError:
    have = False
if have:
    p = run([], no_openpyxl=False)
    check(p.returncode == 0, f"通常：終了コード {p.returncode} / {p.stderr[-300:]}")
    check(os.path.exists(XLSX), "openpyxl ありなのに xlsx ができない")
    check("を飛ばしました" not in p.stdout, "openpyxl ありなのに案内が出た")
else:
    print("（openpyxl が無いのでスキップ）")

print(f"失敗 {fail} 件")
sys.exit(1 if fail else 0)
