"""hook を Windows でも動かす土台（run_py.sh と UTF-8 の出力）のテスト。
- hooks.json の3か所が run_py.sh 経由になっている
- python3 が偽物（動かない）／Python 2／偽物でない python が無いとき：次の候補へ進む。Python が無ければ分かる言葉で 127 で終わる
- py だけの環境では -3 を付けて起動する
- 日本語・スペースの入った引数とパス、hook の標準入力（JSON）、終了コード 2 と標準出力がそのまま届く
- 標準出力が cp932 でも、絵文字の出力で落ちない（入口の .py が自分で UTF-8 にする）
- 標準出力が CRLF になる偽物の python3 でも Python 3 と確かめる／確かめる python が標準入力を読んでも hook の JSON が届く／選ぶ順番
- cp932 の指定で lock_check・setup_settings・watch_check・run_limited の日本語が UTF-8 で出る／ng_guard が絵文字入りの安全なコマンドを通す
- リポジトリ直下の .gitattributes に *.sh text eol=lf がある
- 直す前の hooks.json の形（`$(command -v python3 || …)`）では何が起きるかも並べて確かめる
作り物の python3・python・py は一時フォルダの PATH に作る（本物の PATH は使わない）。
実行：python3 tests/test_run_py.py（失敗があれば終了コード1）"""
import json, os, re, shutil, stat, subprocess, sys, tempfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.path.join(HERE, ".."))
SCRIPTS = os.path.join(PLUGIN, "scripts")
HOOKS = os.path.join(PLUGIN, "hooks", "hooks.json")
RUN_PY = os.path.join(SCRIPTS, "run_py.sh")
BASH = shutil.which("bash")

BASE = os.path.realpath(tempfile.mkdtemp(prefix="runpychk_"))
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("OK   " if ok else "FAIL ") + name + ("" if ok else f"\n     {str(detail)[:600]}"))
    if not ok:
        fails += 1


def note(text):
    print("     " + text)


def write_exe(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


REAL = sys.executable


CRLF_WRAP = os.path.join(BASE, "crlf_wrap.py")   # 渡されたコマンドを動かし、標準出力の LF を CRLF にして返す
with open(CRLF_WRAP, "w", encoding="utf-8") as _f:
    _f.write("import subprocess, sys\nr = subprocess.run(sys.argv[1:], stdin=sys.stdin, capture_output=True)\n"
             "sys.stdout.buffer.write(r.stdout.replace(b'\\n', b'\\r\\n'))\nsys.stderr.buffer.write(r.stderr)\nsys.exit(r.returncode)\n")


def make_bin(name, **fakes):
    """一時フォルダの PATH を作る。bash だけ本物。fakes: python3= / python= / py= に 'real'（本物へ中継）・'broken'（動かない）・'py2'（Python 2 のふり）・'pylauncher'（-3 を取って本物へ）"""
    d = os.path.join(BASE, name)
    os.makedirs(d)
    os.symlink(BASH, os.path.join(d, "bash"))
    for cmd, kind in fakes.items():
        p = os.path.join(d, cmd)
        if kind == "real":
            write_exe(p, f'#!/bin/sh\nPICKED={cmd} exec "{REAL}" "$@"\n')
        elif kind == "broken":   # Microsoft Store を開くだけの偽物。何も出さず 0 以外で終わる
            write_exe(p, "#!/bin/sh\nexit 9\n")
        elif kind == "broken0":  # 終了コード 0 だが何も出さない偽物
            write_exe(p, "#!/bin/sh\nexit 0\n")
        elif kind == "py2":      # Python 2 のふり（-c の中身は見ずに 2 と答える）
            write_exe(p, '#!/bin/sh\nif [ "$1" = "-c" ]; then echo 2; exit 0; fi\necho "Python 2 では動きません" >&2\nexit 1\n')
        elif kind == "crlf":     # Windows の Python 3 に近い偽物：-c のコードはそのまま動かし、標準出力の改行を CRLF にする（print は 3 の後ろに CR LF が付き、write は付かない）
            write_exe(p, f'#!/bin/sh\nif [ "$1" = "-c" ]; then PICKED={cmd} exec "{REAL}" "{CRLF_WRAP}" "{REAL}" "$@"; fi\n'
                         f'PICKED={cmd} exec "{REAL}" "$@"\n')
        elif kind == "eater":    # -c のとき標準入力を最後まで読んで捨てる偽物（</dev/null が無いと hook の JSON を食べる）
            write_exe(p, f'#!/bin/sh\nif [ "$1" = "-c" ]; then "{REAL}" -c "import sys; sys.stdin.buffer.read()"; fi\nPICKED={cmd} exec "{REAL}" "$@"\n')   # PATH に cat は無いので、本物の Python で読む
        elif kind == "pylauncher":   # Windows の py：-3 が付いたときだけ Python 3。付かないと Python 2 のふり
            write_exe(p, f'#!/bin/sh\nif [ "$1" = "-3" ]; then shift; PICKED=py3flag exec "{REAL}" "$@"; fi\n'
                         f'echo "py に -3 が付いていません" >&2\nif [ "$1" = "-c" ]; then echo 2; fi\nexit 1\n')
    return d


def sh(command, path_dir, stdin=b"", env_extra=None, cwd=None):
    """hooks.json の command の形（sh -c）で動かす"""
    env = {"PATH": path_dir, "HOME": BASE, "LANG": "C.UTF-8"}
    env.update(env_extra or {})
    return subprocess.run(["/bin/sh", "-c", command], input=stdin, capture_output=True, env=env, cwd=cwd)


# 試すスクリプト：選ばれた python の名前・Python のメジャー版・引数・標準入力・UTF8 の設定を JSON で出す
PROBE_DIR = os.path.join(BASE, "試す 場所")   # 日本語とスペースの入ったフォルダ
os.makedirs(PROBE_DIR)
PROBE = os.path.join(PROBE_DIR, "probe 試す.py")
with open(PROBE, "w", encoding="utf-8") as f:
    f.write('''import json, os, sys
data = sys.stdin.buffer.read()
sys.stdout.buffer.write(json.dumps({"picked": os.environ.get("PICKED"), "major": sys.version_info[0],
    "argv": sys.argv[1:], "stdin": data.decode("utf-8"), "utf8": os.environ.get("PYTHONUTF8"),
    "emoji": "😀"}, ensure_ascii=False).encode("utf-8"))
sys.exit(int(os.environ.get("PROBE_RC", "0")))
''')

NEW_CMD = f'bash "{RUN_PY}" "{PROBE}"'
OLD_CMD = f'"$(command -v python3 || command -v python || echo py)" "{PROBE}"'   # 直す前の hooks.json の形


def j(r):
    try:
        return json.loads(r.stdout.decode("utf-8"))
    except Exception:
        return {}


# --- 0. hooks.json の実物 ---
hooks = json.load(open(HOOKS, encoding="utf-8"))
cmds = [h["command"] for ev in hooks["hooks"].values() for g in ev for h in g["hooks"]]
check("hooks.json：command が3つ", len(cmds) == 3, cmds)
check("hooks.json：3つとも run_py.sh 経由（bash \"${CLAUDE_PLUGIN_ROOT}/scripts/run_py.sh\" …）",
      all(c.startswith('bash "${CLAUDE_PLUGIN_ROOT}/scripts/run_py.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/') for c in cmds), cmds)
check("hooks.json：名前だけで選ぶ形（command -v python3）が残っていない", not any("command -v" in c for c in cmds), cmds)
def _called(c):
    m = re.search(r'scripts/(\w+\.py)"(?: (.*))?$', c)
    return (m.group(1) + (" " + m.group(2) if m.group(2) else "")) if m else c


check("hooks.json：呼ぶスクリプトは update_dashboard.py ×2（--hook・--session）と ng_guard.py（引数なし）",
      sorted(_called(c) for c in cmds) == sorted(["update_dashboard.py --hook", "update_dashboard.py --session", "ng_guard.py"]), cmds)

# --- 1. python3 が偽物（動かない）→ 次の候補へ ---
for kind in ("broken", "broken0"):
    d = make_bin("t1_" + kind, python3=kind, python="real")
    new, old = sh(NEW_CMD, d), sh(OLD_CMD, d)
    check(f"1 python3 が偽物（{kind}）：新しい形は python に進んで動く", new.returncode == 0 and j(new).get("picked") == "python" and j(new).get("major") == 3, new.stderr)
    note(f"直す前の形：終了コード {old.returncode}／{'動いた' if j(old).get('major') == 3 else '動かなかった（偽物の python3 を掴んだ）'}")
    check(f"1 （対比）直す前の形は偽物の python3 で失敗する", j(old).get("major") != 3, old.stdout)

# --- 2. python3 が Python 2 → 使わない ---
d = make_bin("t2", python3="py2", python="real")
new, old = sh(NEW_CMD, d), sh(OLD_CMD, d)
check("2 python3 が Python 2：使わず python に進む", new.returncode == 0 and j(new).get("picked") == "python" and j(new).get("major") == 3, new.stderr)
check("2 （対比）直す前の形は Python 2 を掴んで失敗する", j(old).get("major") != 3, old.stdout)
d = make_bin("t2b", python3="py2", python="py2", py="pylauncher")
new = sh(NEW_CMD, d)
check("2 python3・python ともに Python 2：py -3 に進む", new.returncode == 0 and j(new).get("picked") == "py3flag", new.stderr)

# --- 3. 日本語・スペースの引数とパス ---
d = make_bin("t3", python3="real")
args = "日本語 の 引数" + " 'q' \"d\" $HOME ;x"
quoted = ["日本語 の 引数", "a b", "$HOME", "；", "'", "--flag=値 1"]
cmd = NEW_CMD + " " + " ".join("'" + a.replace("'", "'\\''") + "'" for a in quoted)
new = sh(cmd, d)
check("3 引数の日本語・スペース・記号がそのまま渡る", j(new).get("argv") == quoted, new.stdout + new.stderr)
# CLAUDE_PLUGIN_ROOT にスペース・日本語が入っているとき（run_py.sh を置いた場所が変でも動く）
weird_root = os.path.join(BASE, "プラグイン 置き場", "ai bunshin")
os.makedirs(os.path.join(weird_root, "scripts"))
shutil.copy(RUN_PY, os.path.join(weird_root, "scripts", "run_py.sh"))
shutil.copy(PROBE, os.path.join(weird_root, "scripts", "probe 試す.py"))
cmd = 'bash "${CLAUDE_PLUGIN_ROOT}/scripts/run_py.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/probe 試す.py" --hook'
new = sh(cmd, d, env_extra={"CLAUDE_PLUGIN_ROOT": weird_root})
check("3 CLAUDE_PLUGIN_ROOT にスペース・日本語があっても動く（hooks.json と同じ書き方）", new.returncode == 0 and j(new).get("argv") == ["--hook"], new.stdout + new.stderr)

# --- 4. 終了コード 2 と標準出力がそのまま返る ---
new = sh(NEW_CMD, d, env_extra={"PROBE_RC": "2"})
check("4 スクリプトが終了コード 2 で終わると、そのまま 2", new.returncode == 2 and j(new).get("emoji") == "😀", (new.returncode, new.stdout))
new = sh(NEW_CMD, d, env_extra={"PROBE_RC": "7"})
check("4 終了コード 7 もそのまま", new.returncode == 7, new.returncode)

# --- 5. hook の標準入力（JSON）が欠けずに、日本語が壊れずに届く ---
payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "echo 日本語 😀 'x' \"y\"\n" + "あ" * 200000}}, ensure_ascii=False)
new = sh(NEW_CMD, d, stdin=payload.encode("utf-8"))
check("5 標準入力の JSON（日本語・絵文字・改行・約600KB）が欠けずに届く", j(new).get("stdin") == payload, len(j(new).get("stdin", "")))
new = sh(NEW_CMD, d, stdin=b"")
check("5 標準入力が空でも落ちない", new.returncode == 0 and j(new).get("stdin") == "", new.stderr)
check("5 PYTHONUTF8=1 が付く", j(sh(NEW_CMD, d)).get("utf8") == "1")

# --- 6. Python が1つも無い ---
d6 = make_bin("t6", python3="broken", python="py2")
new, old = sh(NEW_CMD, d6), sh(OLD_CMD, d6)
msg = new.stderr.decode("utf-8", "replace")
check("6 Python が無い：分かる言葉で標準エラーに書く", "Python 3 が見つかりませんでした" in msg and "python.org" in msg, msg)
check("6 Python が無い：0 以外で終わる。2（hook では「止める」の意味）にはならない", new.returncode not in (0, 2) and new.returncode == 127, new.returncode)
check("6 Python が無い：標準出力には何も出さない", new.stdout == b"", new.stdout)
note(f"直す前の形：終了コード {old.returncode}／標準エラー {old.stderr.decode('utf-8','replace').strip()[:80]!r}")
check("6 （対比）直す前の形も 0 以外で終わる（今の動きより悪くならない）", old.returncode not in (0, 2))
d6b = make_bin("t6b")
new = sh(NEW_CMD, d6b)
check("6 名前が何も無い PATH でも同じ（127・案内）", new.returncode == 127 and "Python 3 が見つかりませんでした" in new.stderr.decode("utf-8", "replace"))

# --- 8. py だけの環境：-3 が付いて起動する ---
d8 = make_bin("t8", py="pylauncher")
new, old = sh(NEW_CMD, d8), sh(OLD_CMD, d8)
check("8 python3・python が無く py だけ：-3 を付けて起動する", new.returncode == 0 and j(new).get("picked") == "py3flag" and j(new).get("major") == 3, new.stderr)
note(f"直す前の形：終了コード {old.returncode}／{'動いた' if j(old).get('major') == 3 else '動かなかった（py に -3 が付かない）'}")
check("8 （対比）直す前の形は py に -3 が付かず失敗する", j(old).get("major") != 3, old.stdout)

# --- 4'. 本物の ng_guard.py を hooks.json の形で通す：判定と出力が直接呼んだときと同じ ---
GUARD = os.path.join(SCRIPTS, "ng_guard.py")
OWNER = os.path.join(BASE, "owner")
os.makedirs(os.path.join(OWNER, "00_タスク管理", "data"))
os.makedirs(os.path.join(OWNER, "設定"))
json.dump({"owner": "テスト", "owner_call": "テストさん", "ai_name": "テストAI"}, open(os.path.join(OWNER, "設定", "config.json"), "w", encoding="utf-8"), ensure_ascii=False)
json.dump({"project": {"name": "t"}, "tasks": [], "sprints": [], "daily_sprints": []}, open(os.path.join(OWNER, "00_タスク管理", "data", "tasks.json"), "w", encoding="utf-8"))
dr = make_bin("tg", python3="real")
for command, want_deny in (("rm x", True), ("date", False)):
    stdin = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": OWNER}).encode("utf-8")
    env = {"CLAUDE_PROJECT_DIR": OWNER, "CLAUDE_PLUGIN_ROOT": PLUGIN}
    via = sh('bash "${CLAUDE_PLUGIN_ROOT}/scripts/run_py.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/ng_guard.py"', dr, stdin=stdin, env_extra=env, cwd=OWNER)
    direct = subprocess.run([REAL, GUARD], input=stdin, capture_output=True, env={**os.environ, **env}, cwd=OWNER)
    denied = b'"deny"' in via.stdout
    check(f"4 ng_guard.py（{command}）：run_py.sh 経由でも {'止まる' if want_deny else '通る'}", denied == want_deny, via.stdout + via.stderr)
    check(f"4 ng_guard.py（{command}）：直接呼んだときと終了コード・標準出力が同じ", (via.returncode, via.stdout) == (direct.returncode, direct.stdout), (via.returncode, direct.returncode))

# --- 7. 標準出力・標準入力が cp932 でも、絵文字で落ちない ---
UPD = os.path.join(SCRIPTS, "update_dashboard.py")
R = os.path.join(BASE, "owner7")
os.makedirs(os.path.join(R, "設定"))
os.makedirs(os.path.join(R, "00_タスク管理", "data"))
json.dump({"owner": "テスト", "owner_call": "テストさん", "ai_name": "テストAI", "departments": ["総務"]},
          open(os.path.join(R, "設定", "config.json"), "w", encoding="utf-8"), ensure_ascii=False)
json.dump({"project": {"name": "テストAI", "daily_capacity_default": 8.0, "holidays": []}, "daily_sprints": [],
           "sprints": [{"id": "S001", "start": "2026-11-02", "end": "2026-11-06", "goal": "目標", "status": "進行中", "pdca": "Do"}],
           "tasks": [{"id": "T001", "title": "タスク", "status": "作業中", "assignee": "dev-a", "type": "開発", "reviewer": "dev-b",
                      "points": 2, "department": "総務", "priority": 1, "due": "2026-11-02", "sprint": "S001"}]},
          open(os.path.join(R, "00_タスク管理", "data", "tasks.json"), "w", encoding="utf-8"), ensure_ascii=False)


def run_cp932(script, args, stdin=b"", cwd=R, extra=None):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "AI_BUNSHIN_HOME", "CLAUDE_PROJECT_DIR")}
    env.update({"PYTHONIOENCODING": "cp932", "AI_BUNSHIN_HOME": R, "HOME": BASE, "CLAUDE_PROJECT_DIR": R})
    env.update(extra or {})
    return subprocess.run([REAL, script, *args], input=stdin, capture_output=True, env=env, cwd=cwd)


for args in (["--today", "2026-11-04"], ["--today", "2026-11-04", "--session"], ["--today", "2026-11-04", "--plan-context"]):
    r = run_cp932(UPD, args)
    out = r.stdout.decode("utf-8", "replace")
    check(f"7 update_dashboard.py {' '.join(args[2:]) or '（引数なし）'}：cp932 の指定でも落ちず、絵文字が UTF-8 で出る",
          r.returncode == 0 and "Traceback" not in r.stderr.decode("utf-8", "replace") and re.search(r"[\U0001F300-\U0001FAFF☀-➿]", out) is not None,
          (r.returncode, r.stderr[-300:]))
# ng_guard.py：UTF-8 の入力（日本語・絵文字）を cp932 指定で受けても、日本語を含む判定が読める
stdin = json.dumps({"tool_name": "Bash", "tool_input": {"command": "echo 😀 日本語; rm 資料😀.txt"}, "cwd": R}, ensure_ascii=False).encode("utf-8")
r = run_cp932(GUARD, [], stdin=stdin)
check("7 ng_guard.py：cp932 指定でも UTF-8 の JSON（絵文字入り）を読んで止める", b'"deny"' in r.stdout and r.returncode == 0, (r.returncode, r.stdout[:300], r.stderr[-200:]))
r = run_cp932(GUARD, ["--explain", "rm 😀"])
check("7 ng_guard.py --explain：cp932 指定でも日本語の出力で落ちない", r.returncode == 0 and "判定：deny".encode() in r.stdout, (r.stdout[:200], r.stderr[-200:]))
# ng_guard.py：安全なコマンド（絵文字・日本語入り）が cp932 指定でも通る（標準入力を UTF-8 で読めないと、読めない入力として止めてしまう）
stdin = json.dumps({"tool_name": "Bash", "tool_input": {"command": "echo 😀 日本語"}, "cwd": R}, ensure_ascii=False).encode("utf-8")
r = run_cp932(GUARD, [], stdin=stdin)
check("7 ng_guard.py：cp932 指定でも、絵文字・日本語入りの安全なコマンドは止まらずに通る",
      r.returncode == 0 and b'"deny"' not in r.stdout and b"Traceback" not in r.stderr, (r.returncode, r.stdout[:300], r.stderr[-200:]))
# ほかの入口：cp932 の指定で動かし、日本語が UTF-8 で出るかを見る（文面ではなく、動きで確かめる）
EMPTY = os.path.join(BASE, "空のフォルダ")
os.makedirs(EMPTY)
r = run_cp932(os.path.join(SCRIPTS, "lock_check.py"), ["--root", EMPTY])
check("7 lock_check.py：cp932 指定でも、日本語が UTF-8 で出る", r.returncode == 0 and r.stdout.decode("utf-8", "replace").strip() == "OPEN: ロックなし", (r.returncode, r.stdout, r.stderr[-200:]))
r = run_cp932(os.path.join(SCRIPTS, "setup_settings.py"), [R])   # R は設定/config.json がある＝セットアップ済み。何も書かずに日本語の案内を出す
check("7 setup_settings.py：cp932 指定でも、日本語の案内が UTF-8 で出る", r.returncode == 1 and "セットアップ済みのフォルダなので何もしません" in r.stderr.decode("utf-8", "replace"), (r.returncode, r.stderr[-300:]))
r = run_cp932(os.path.join(SCRIPTS, "watch_check.py"), [])
check("7 watch_check.py：cp932 指定でも、使い方の日本語が UTF-8 で出る", r.returncode == 64 and "長引き・止まりに気づくための小さな道具" in r.stderr.decode("utf-8", "replace"), (r.returncode, r.stderr[:200]))
r = run_cp932(os.path.join(SCRIPTS, "auto", "run_limited.py"), ["--minutes", "0", "--stdout", os.path.join(BASE, "rl.out"), "--", "x"])
check("7 run_limited.py：cp932 指定でも、使い方の日本語が UTF-8 で出る", r.returncode == 64 and "使い方：run_limited.py" in r.stderr.decode("utf-8", "replace"), (r.returncode, r.stderr[-300:]))
CAL = os.path.join(SCRIPTS, "calendar_today.py")
ics = os.path.join(BASE, "x.ics")
open(ics, "w", encoding="utf-8").write("BEGIN:VCALENDAR\nBEGIN:VEVENT\nDTSTART;VALUE=DATE:20261104\nSUMMARY:会議😀\nEND:VEVENT\nEND:VCALENDAR\n")
r = run_cp932(CAL, [ics, "2026-11-04"])
check("7 calendar_today.py：絵文字の件名を cp932 指定でも出せる", r.returncode == 0 and "😀".encode("utf-8") in r.stdout, (r.returncode, r.stderr[-300:]))

# --- 10. Windows の Python に近い偽物（改行が CRLF）でも Python 3 と確かめられる ---
d10 = make_bin("t10", python3="crlf")
new = sh(NEW_CMD, d10)
check("10 標準出力が CRLF になる python3 でも Python 3 と確かめて、起動する", new.returncode == 0 and j(new).get("picked") == "python3" and j(new).get("major") == 3, new.stderr)
d10b = make_bin("t10b", python3="broken", python="crlf")
new = sh(NEW_CMD, d10b)
check("10 python3 が偽物で、python が CRLF の Python 3 のとき：python に進んで起動する", new.returncode == 0 and j(new).get("picked") == "python" and j(new).get("major") == 3, new.stderr)
check("10 （確認）偽物の素の出力は CRLF になっている（改行を出す print で確かめると別物になる）",
      subprocess.run([os.path.join(d10, "python3"), "-c", "print(3)"], capture_output=True).stdout == b"3\r\n"
      and subprocess.run([os.path.join(d10, "python3"), "-c", "import sys; sys.stdout.write('3')"], capture_output=True).stdout == b"3")

# --- 11. 確かめる python が標準入力を読んでも、hook の JSON は後ろの Python に届く（</dev/null） ---
d11 = make_bin("t11", python3="eater")
payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "echo 日本語 😀"}}, ensure_ascii=False)
new = sh(NEW_CMD, d11, stdin=payload.encode("utf-8"))
check("11 確かめる python が標準入力を読む偽物でも、hook の JSON が欠けずに届く", new.returncode == 0 and j(new).get("stdin") == payload, new.stdout + new.stderr)

# --- 12. 選ぶ順番：python3 → python → py -3 ---
d12 = make_bin("t12", python3="real", python="real", py="pylauncher")
check("12 全部動くとき、python3 が選ばれる", j(sh(NEW_CMD, d12)).get("picked") == "python3", sh(NEW_CMD, d12).stdout)
d12b = make_bin("t12b", python3="broken", python="real", py="pylauncher")
check("12 python3 が動かず python と py -3 が動くとき、python が選ばれる（py -3 が先にならない）", j(sh(NEW_CMD, d12b)).get("picked") == "python", sh(NEW_CMD, d12b).stdout)
d12c = make_bin("t12c", python="real", py="pylauncher")
check("12 python3 が無く python と py -3 があるとき、python が選ばれる", j(sh(NEW_CMD, d12c)).get("picked") == "python", sh(NEW_CMD, d12c).stdout)

# --- 13. 改行コード：Windows で checkout しても *.sh が CRLF にならない ---
ROOT = os.path.abspath(os.path.join(PLUGIN, "..", ".."))
if os.path.isdir(os.path.join(ROOT, ".claude-plugin")):   # リポジトリの中で動かしているときだけ（インストールされたコピーには無い）
    ga = os.path.join(ROOT, ".gitattributes")
    lines = [l.split("#")[0].split() for l in open(ga, encoding="utf-8").read().splitlines()] if os.path.exists(ga) else []
    check("13 .gitattributes：*.sh は LF（text eol=lf）で取り出す", any(l[:1] == ["*.sh"] and "text" in l and "eol=lf" in l for l in lines), lines)
else:
    note("13 .gitattributes：リポジトリの外なので確かめない")

# --- 9. Mac の動きが変わらない：実物の python3 で、フックの形が今までと同じ結果 ---
real_bin = make_bin("t9", python3="real")
new, old = sh(NEW_CMD, real_bin), sh(OLD_CMD, real_bin)
check("9 本物の python3 があるとき、新旧で出力が同じ（選ばれる Python も同じ）",
      j(new).get("picked") == j(old).get("picked") == "python3" and new.returncode == old.returncode == 0)

shutil.rmtree(BASE, ignore_errors=True)
print(f"\n{'失敗 ' + str(fails) + ' 件' if fails else 'すべて通りました'}")
sys.exit(1 if fails else 0)
