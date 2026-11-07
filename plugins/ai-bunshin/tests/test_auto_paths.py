"""自動実行で読める・書ける場所を絞る（T193。決定 K1・K3・K4・K5・K6）のテスト。
一時フォルダに本人のフォルダとプラグインのコピーを作り、daily_cycle.sh（本物のコピー）を作り物の claude（受け取った引数を記録するだけ）・
osascript で通して動かす。本物の launchd・claude・本物の本人のフォルダは使わない。

- T1：daily_cycle.sh が claude に渡す最終の --allowedTools に、かっこの続かない Read・Write・Edit・Glob・Grep が無い。
  Write(・Glob(・Grep( の後ろにパスが付いた規則も無い（3つの段とも。リンク経由で呼ばれたときも）
- T3：--print-add-dirs が /・ホーム・ホームの祖先・本人のフォルダの祖先を出さず、標準エラーに1行（パスなし）。ふつうの外のリポジトリは今までどおり。
  daily_cycle.sh は外したことをログに1行写す
- T4：--print-read-rules が、プラグインの元（と違うときはリンクの名前）の NFC・NFD・実体の形で Read(//…/**) を出す。末尾の / が無く、
  使えない文字を含むときは出さずに標準エラーに1行。daily_cycle.sh は --allowedTools に足し、足せないときはログに1行
- T5：--plan-context の道具の節に、ファイルを読む・書く・直すの範囲の1行が「書けない場所の見方」の行の直後に出る
実行：python3 tests/test_auto_paths.py（失敗があれば終了コード1）。CYCLE_UNDER_TEST・SANDBOX_UNDER_TEST・DASH_UNDER_TEST で別の版を指せる"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.abspath(os.path.join(HERE, "..", "scripts"))
CYCLE = os.environ.get("CYCLE_UNDER_TEST") or os.path.join(SCRIPTS, "auto", "daily_cycle.sh")
SANDBOX = os.environ.get("SANDBOX_UNDER_TEST") or os.path.join(SCRIPTS, "sandbox_settings.py")
DASH = os.environ.get("DASH_UNDER_TEST") or os.path.join(SCRIPTS, "update_dashboard.py")
SCRATCH = os.environ.get("AUTO_PATHS_SCRATCH") or tempfile.gettempdir()
BASE = os.path.realpath(tempfile.mkdtemp(prefix="autopaths_", dir=SCRATCH))
FAKE_HOME = os.path.join(BASE, "fakehome")
os.makedirs(FAKE_HOME)

BARE = ("Read", "Write", "Edit", "Glob", "Grep")
names, fails = [], 0


def case(fn):
    names.append(fn.__name__)
    return fn


# update_dashboard.py の代わり。計画：1回目だけ OPEN（計画のあと続けて実行に入る）。振り返りは OPEN
STUB = '''import os, sys, time
a = sys.argv[1:]
home = os.environ["AI_BUNSHIN_HOME"]
if "--session" in a:
    sys.exit(0)
if "--today-status" in a:
    print("計画済み"); sys.exit(0)
if "--plan-context" in a:
    if os.environ.get("STUB_PHASE") == "do":
        print("作成済み：テスト"); sys.exit(0)
    n = os.path.join(home, "plan_calls")
    c = int(open(n).read()) if os.path.exists(n) else 0
    open(n, "w").write(str(c + 1))
    print("OPEN" if c == 0 else "今日の計画は作成済み")
if "--review-context" in a:
    print("OPEN")
    print("議事録の保存先: 01_スプリント/S1/daily/" + time.strftime("%Y%m%d") + "_振り返り.md")
'''

# claude の代わり：受け取った引数を記録するだけ。囲いの点検の呼び出しは記録せず、何も書かずに終わる（点検は通らない＝Python なしの許可で動く）
FAKE_CLAUDE = '''#!__PY__
import json, os, sys
args = sys.argv[1:]
prompt = args[args.index("-p") + 1] if "-p" in args else ""
if "囲いの点検" not in prompt:
    with open(os.path.join(os.environ["FAKE_RECORD"], "calls.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"args": args, "auto_memory_off": os.environ.get("CLAUDE_CODE_DISABLE_AUTO_MEMORY")}, ensure_ascii=False) + "\\n")
else:
    with open(os.path.join(os.environ["FAKE_RECORD"], "canary_env.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"auto_memory_off": os.environ.get("CLAUDE_CODE_DISABLE_AUTO_MEMORY")}) + "\\n")
print("done")
'''


def make(name, cfg=None, repo=None, plugin_name="plugin", link=False, owner="owner"):
    """一時フォルダに、プラグインのコピー（link=True なら、実体と別の名前のリンク経由で呼ぶ）・本人のフォルダ・作り物の claude / osascript を作る"""
    d = os.path.join(BASE, name)
    real = os.path.join(d, "real_" + plugin_name if link else plugin_name)
    os.makedirs(os.path.join(real, "scripts", "auto"))
    shutil.copy(CYCLE, os.path.join(real, "scripts", "auto", "daily_cycle.sh"))
    shutil.copy(os.path.join(SCRIPTS, "auto", "run_limited.py"), os.path.join(real, "scripts", "auto", "run_limited.py"))
    for f in ("lock_check.py", "watch_check.py", "ng_guard.py", "ng_guard_legacy.py", "protected_paths.json", "calendar_today.py", "sandbox_canary.py"):
        shutil.copy(os.path.join(SCRIPTS, f), os.path.join(real, "scripts", f))
    shutil.copy(SANDBOX, os.path.join(real, "scripts", "sandbox_settings.py"))
    open(os.path.join(real, "scripts", "update_dashboard.py"), "w", encoding="utf-8").write(STUB)
    plugin = real
    if link:
        plugin = os.path.join(d, plugin_name)
        os.symlink(real, plugin)
    home = os.path.join(d, owner)
    for sub in ("設定", "scripts/auto", "00_タスク管理/data", "03_インプット"):
        os.makedirs(os.path.join(home, sub))
    c = {"ai_name": "テストAI"}
    c.update(cfg or {})
    if repo:
        c["dev"] = {"projects": [{"name": "外", "path": p} for p in (repo if isinstance(repo, list) else [repo])]}
    json.dump(c, open(os.path.join(home, "設定", "config.json"), "w", encoding="utf-8"), ensure_ascii=False)
    open(os.path.join(home, "00_タスク管理", "data", "tasks.json"), "w").write("{}")
    bindir, rec = os.path.join(d, "bin"), os.path.join(d, "rec")
    os.makedirs(bindir)
    os.makedirs(rec)
    open(os.path.join(bindir, "claude"), "w").write(FAKE_CLAUDE.replace("__PY__", sys.executable))
    open(os.path.join(bindir, "osascript"), "w").write('#!/bin/sh\necho "$*" >> "$FAKE_RECORD/notify.txt"\nexit 0\n')
    for f in ("claude", "osascript"):
        os.chmod(os.path.join(bindir, f), 0o755)
    return dict(d=d, plugin=plugin, real=real, home=home, bindir=bindir, rec=rec)


def run(c, phase, stub_phase="plan", timeout=120):
    env = {k: v for k, v in os.environ.items() if k not in ("AI_BUNSHIN_AUTO_RUN", "CLAUDE_PROJECT_DIR", "AI_BUNSHIN_CALENDAR_URL", "CLAUDE_CODE_DISABLE_AUTO_MEMORY")}
    env.update({"HOME": FAKE_HOME, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "AI_BUNSHIN_HOME": c["home"],
                "PATH": c["bindir"] + os.pathsep + env.get("PATH", ""), "FAKE_RECORD": c["rec"], "STUB_PHASE": stub_phase})
    return subprocess.run(["/bin/zsh", os.path.join(c["plugin"], "scripts", "auto", "daily_cycle.sh"), phase],
                          capture_output=True, text=True, env=env, timeout=timeout)


def calls(c):
    p = os.path.join(c["rec"], "calls.jsonl")
    return [json.loads(ln) for ln in open(p, encoding="utf-8").read().splitlines()] if os.path.exists(p) else []


def log_of(c):
    d = os.path.join(c["home"], "scripts", "auto", "logs")
    return "".join(open(os.path.join(d, f), encoding="utf-8").read() for f in sorted(os.listdir(d))) if os.path.isdir(d) else ""


def opt(call, flag):
    a = call["args"]
    return a[a.index(flag) + 1] if flag in a else None


def tool_items(call):
    """--allowedTools を、かっこの中の , で割らずに規則に分ける（Bash(…) の中に , は無い前提。Read(//…) の規則に , は入れない決まり）"""
    return (opt(call, "--allowedTools") or "").split(",")


def tool_problems(call):
    bad = []
    for it in tool_items(call):
        head = it.split("(", 1)[0]
        if it in BARE:
            bad.append("素の許可 " + it)
        if head in ("Write", "Glob", "Grep") and "(" in it:
            bad.append("パスつきの規則（一致しない形） " + it)
    return bad


def cli(*args, env_home=None):
    r = subprocess.run([sys.executable, "-I", SANDBOX, *args], capture_output=True, text=True, env={"PATH": os.environ.get("PATH", ""), "HOME": env_home or FAKE_HOME})
    return r.returncode, r.stdout, r.stderr


@case
def t1_no_bare_read_write_in_final_allowed_tools():
    """K1・K6・B1：3つの段（計画・計画から続けた実行・実行・振り返り）の最終の --allowedTools に素の許可もパスつきの規則も無い。ほかの許可は残る"""
    c = make("t1")
    r = run(c, "plan")
    assert r.returncode == 0, (r.returncode, r.stderr[-300:], log_of(c)[-500:])
    c2 = make("t1do")
    run(c2, "do", stub_phase="do")
    c3 = make("t1rev")
    run(c3, "review")
    got = calls(c) + calls(c2) + calls(c3)
    assert len(calls(c)) == 2 and len(calls(c2)) == 1 and len(calls(c3)) == 1, [len(calls(x)) for x in (c, c2, c3)]
    for call in got:
        assert not tool_problems(call), tool_problems(call)
        its = tool_items(call)
        for keep in ("Agent", "SendMessage", "Skill"):
            assert keep in its, (keep, its)
        root = os.path.realpath(c["plugin"])
        assert f"Bash(python3 {root}/scripts/update_dashboard.py:*)" in its or any("update_dashboard.py:*)" in i for i in its), its
    # リンク経由で呼ばれたときも（LINK_TOOLS・読み取りの規則を足した後の全体）
    cl = make("t1link", link=True)
    run(cl, "plan")
    assert calls(cl) and all(not tool_problems(x) for x in calls(cl)), [tool_problems(x) for x in calls(cl)]


@case
def t3_print_add_dirs_drops_too_wide_places():
    """K4・B8：/・ホーム・ホームの祖先・本人のフォルダの祖先は出さない。標準エラーは1行でパスなし。ふつうの外のリポジトリは今までどおり"""
    uh = os.path.join(BASE, "t3", "uh")
    home = os.path.join(uh, "work", "owner")
    repo = os.path.join(uh, "repos", "hp")
    for p in (home + "/設定", repo):
        os.makedirs(p)
    os.symlink(uh, os.path.join(BASE, "t3", "リンクのホーム"))
    wide = ["/", uh, os.path.dirname(uh), os.path.join(uh, "work"), os.path.join(BASE, "t3", "リンクのホーム")]

    def go(projects, cfg_body=None):
        body = json.dumps({"dev": {"projects": [{"path": p} for p in projects]}}) if cfg_body is None else cfg_body
        open(os.path.join(home, "設定", "config.json"), "w", encoding="utf-8").write(body)
        return cli("--home", home, "--user-home", uh, "--print-add-dirs")
    rc, out, err = go(wide + [repo])
    assert rc == 0 and out.splitlines() == [repo], (rc, out, err)
    assert err.count("\n") == 1 and err.startswith("sandbox_settings: ") and "広すぎ" in err, err
    assert uh not in err and home not in err and "t3" not in err, "標準エラーにパスが出ている"
    for w in wide:
        rc, out, err = go([w, repo])
        assert out.splitlines() == [repo] and err.count("\n") == 1, (w, out, err)
    # 大文字小文字だけ違う綴り（macOS の既定は区別しない）でも、すり抜けない（文字の比較だけでは一致しない。samefile でも照らす）
    case_variants = [os.path.join(BASE, "t3", "UH"), os.path.join(uh, "WORK"), os.path.join(BASE, "t3", "UH", "Work")]
    if all(os.path.isdir(v) for v in case_variants):   # 大文字小文字を区別するボリュームでは、実在しないので対象外
        for v in case_variants:
            rc, out, err = go([v, repo])
            assert out.splitlines() == [repo] and err.count("\n") == 1, (v, out, err)
    # ふつうの外のリポジトリだけ：今までどおり（標準エラーは空）
    rc, out, err = go([repo])
    assert rc == 0 and out.splitlines() == [repo] and err == "", (rc, out, err)
    # config が壊れている・無いときは今までどおり何も出さない（標準エラーも空）
    for body in ("{", "[]", "null"):
        rc, out, err = go([repo], cfg_body=body)
        assert rc == 0 and out == "" and err == "", (body, rc, out, err)
    # daily_cycle.sh：--add-dir に広い先が入らず、外したことをログに1行（パスなし）
    d_repo = os.path.join(BASE, "t3e", "repos", "hp")
    os.makedirs(d_repo)
    c = make("t3e", repo=[FAKE_HOME, os.path.dirname(FAKE_HOME), d_repo])
    run(c, "plan")
    cs = calls(c)
    assert cs, log_of(c)
    for call in cs:
        a = call["args"]
        assert [a[i + 1] for i, x in enumerate(a) if x == "--add-dir"] == [d_repo], a
    lg = log_of(c)
    assert lg.count("広すぎ") == 1 and FAKE_HOME not in lg, lg


def rules_of(out):
    return [x for x in out.splitlines() if x]


@case
def t4_print_read_rules_forms_and_bad_chars():
    """K3・B9：NFC・NFD・実体の形。末尾の / が無い。使えない文字を含むものは出さず、標準エラーに1行（パスなし）"""
    plug = os.path.join(BASE, "t4", "プラグイン ダウンロード")   # 日本語・空白・濁点
    os.makedirs(plug)
    link = os.path.join(BASE, "t4", "リンク名")
    os.symlink(plug, link)
    rc, out, err = cli("--home", FAKE_HOME, "--print-read-rules", "--plugin-root", plug + "/", "--plugin-root", link)
    assert rc == 0 and err == "", (rc, err)
    rules = rules_of(out)
    want = set()
    for p in (plug, link):
        for v in {unicodedata.normalize(f, s) for s in (p, os.path.realpath(p)) for f in ("NFC", "NFD")}:
            want.add("Read(/%s/**)" % v)
    assert set(rules) == want and len(rules) == len(want), (sorted(rules), sorted(want))
    assert any(unicodedata.normalize("NFD", plug) in r for r in rules) and any(unicodedata.normalize("NFC", plug) in r for r in rules)
    assert all(r.startswith("Read(//") and r.endswith("/**)") and "//**" not in r and "/**/" not in r for r in rules), rules
    # 同じ場所を2回渡しても重複しない
    rc, out, err = cli("--home", FAKE_HOME, "--print-read-rules", "--plugin-root", plug, "--plugin-root", plug)
    assert len(rules_of(out)) == len({unicodedata.normalize(f, s) for s in (plug, os.path.realpath(plug)) for f in ("NFC", "NFD")}), out
    # 使えない文字：規則を作らず、標準エラー1行・パスなし
    for tag, name in (("comma", "a,b"), ("star", "a*b"), ("paren", "a(b)"), ("bang", "a !b"), ("bang2", "a! b"), ("hash", "#x")):
        bad = os.path.join(BASE, "t4", name)
        os.makedirs(bad, exist_ok=True)
        rc, out, err = cli("--home", FAKE_HOME, "--print-read-rules", "--plugin-root", bad)
        assert rc == 0 and rules_of(out) == [] and err.count("\n") == 1 and "プラグインの置き場所に規則に使えない文字があります" in err, (tag, rc, out, err)
        assert "t4" not in err and name not in err, (tag, err)
    # 相対パス・/・無いフォルダも出さない
    for bad in ("relative/x", "/", os.path.join(BASE, "t4", "nowhere")):
        rc, out, err = cli("--home", FAKE_HOME, "--print-read-rules", "--plugin-root", bad)
        assert rules_of(out) == [] and err.count("\n") == 1, (bad, out, err)
    # 1つが使えなくても、ほかは出す
    rc, out, err = cli("--home", FAKE_HOME, "--print-read-rules", "--plugin-root", plug, "--plugin-root", os.path.join(BASE, "t4", "a,b"))
    assert rules_of(out) and all("a,b" not in r for r in rules_of(out)) and err.count("\n") == 1, (out, err)


@case
def t4b_daily_cycle_adds_read_rules_for_plugin_only():
    """K3・B7・B9：daily_cycle.sh の最終の --allowedTools に、プラグインの実体（とリンクの名前）の読み取りの規則が入る。作業フォルダ・add-dir の読み取りの規則は足さない。使えない文字のときはログに1行"""
    c = make("t4b", plugin_name="プラグイン ダウンロード", link=True)
    run(c, "review")
    cs = calls(c)
    assert len(cs) == 1, log_of(c)
    its = tool_items(cs[0])
    reads = [i for i in its if i.startswith("Read(")]
    for p in (c["real"], c["plugin"]):
        for f in ("NFC", "NFD"):
            r = "Read(/%s/**)" % unicodedata.normalize(f, os.path.realpath(p) if p == c["real"] else p)
            assert r in reads, (r, reads)
    assert all(r.startswith("Read(//") for r in reads) and not any(c["home"] in r for r in reads), reads
    assert not tool_problems(cs[0]), tool_problems(cs[0])
    assert "規則に使えない文字" not in log_of(c)
    # 実体と同じ名前で呼ばれたとき（リンクなし）は、その1つ（の NFC・NFD・実体）だけ
    c = make("t4c")
    run(c, "review")
    reads = [i for i in tool_items(calls(c)[0]) if i.startswith("Read(")]
    assert reads and all(os.path.realpath(c["plugin"]) in r or unicodedata.normalize("NFD", os.path.realpath(c["plugin"])) in r for r in reads), reads
    # 使えない文字を含む置き場所：規則は足さず（claude は動く）、ログに1行（パスなし）
    c = make("t4d", plugin_name="a !b")
    run(c, "review")
    cs = calls(c)
    assert len(cs) == 1 and not [i for i in tool_items(cs[0]) if i.startswith("Read(")], (log_of(c), cs)
    lg = log_of(c)
    assert lg.count("プラグインの置き場所に規則に使えない文字があります") == 1 and "a !b" not in lg, lg


@case
def t5_plan_context_has_read_write_range_line():
    """K5・B13：道具の節に1行。位置は「書けない場所の見方」の行の直後（節の途中に入れない）。節は読めないにならない"""
    home = os.path.join(BASE, "t5_home")
    for d in ("設定", "00_タスク管理/data"):
        os.makedirs(os.path.join(home, d), exist_ok=True)
    json.dump({"owner": "テスト", "owner_call": "テストさん", "ai_name": "テストAI", "departments": ["総務"]},
              open(os.path.join(home, "設定", "config.json"), "w", encoding="utf-8"), ensure_ascii=False)
    json.dump({"project": {"name": "テスト", "daily_capacity_default": 1.0, "holidays": []}, "daily_sprints": [], "sprints": [], "tasks": []},
              open(os.path.join(home, "00_タスク管理", "data", "tasks.json"), "w", encoding="utf-8"), ensure_ascii=False)
    code = "import sys; sys.path.insert(0, %r); import update_dashboard as u; print('\\n'.join(u.auto_tools_lines(%r)))" % (os.path.dirname(DASH), CYCLE)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={"PATH": os.environ.get("PATH", ""), "HOME": FAKE_HOME, "AI_BUNSHIN_HOME": home})
    assert r.returncode == 0, r.stderr[-400:]
    lines = r.stdout.splitlines()
    i = next(n for n, x in enumerate(lines) if x.startswith("- 書けない場所の見方"))
    j = lines[i + 1]
    assert j.startswith("- ファイルを読む・書く・直すは、本人のフォルダと開発の置き場所（add-dir）の中が基本"), j
    assert "プラグインの中は読むだけ" in j and lines[i + 2].startswith("- 次は定数では分からない"), lines[i:i + 4]
    assert not any("読めませんでした" in x for x in lines), [x for x in lines if "読めませんでした" in x]
    use = [x for x in lines if "使える道具" in x]
    assert use and not any(" Read," in x or " Write," in x or "Read," in x for x in use), use
    # 一覧に Glob・Grep が無いことと、1行が「Glob・Grep は使えない」と言うことは組（どちらかだけ変わったら落ちる）
    assert not any("Glob" in x or "Grep" in x for x in use) and "Glob・Grep は使えない" in j, (use, j)
    assert "自動記憶（~/.claude の下）は、自動実行では止めている" in j, j
    assert "ls・cat・find・grep など読むだけの命令は、下の範囲の中だけ動く" in lines[i], lines[i]


@case
def t6_log_does_not_copy_tool_output():
    """B：道具が壊れて、標準エラーにパス・URL を出しても、ログには写さない（ログに書くのは daily_cycle.sh が決めた文だけ）"""
    secret = "SECRETTOKEN-193"
    repo = os.path.join(BASE, "t6", "repos", "hp")
    os.makedirs(repo)
    c = make("t6", repo=repo)
    body = "import sys\nsys.stderr.write('sandbox_settings: 広すぎる開発の置き場所 /Users/x/%s https://h.example/%s\\n')\nsys.stderr.write('sandbox_settings: プラグインの置き場所に規則に使えない文字があります /Users/x/%s\\n')\nsys.exit(1)\n" % (secret, secret, secret)
    open(os.path.join(c["real"], "scripts", "sandbox_settings.py"), "w", encoding="utf-8").write(body)
    r = run(c, "plan")
    assert calls(c), (r.returncode, r.stderr[-300:], log_of(c)[-400:])   # 道具が壊れても claude は動く（規則を足さないだけ）
    text = r.stdout + r.stderr + log_of(c)
    assert secret not in text and "/Users/x" not in text and "h.example" not in text, text[-600:]
    assert "広すぎる開発の置き場所（/・ホーム" in log_of(c) and "規則に使えない文字があります（読み取りの規則を作れなかった先があります）" in log_of(c), log_of(c)
    assert not [i for i in tool_items(calls(c)[0]) if i.startswith("Read(")], tool_items(calls(c)[0])


@case
def t7_auto_memory_is_off_only_for_run_claude():
    """自動記憶を止める：計画・続けた実行・実行・振り返りの起動に CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 が付く。囲いの点検の claude には付かない"""
    c = make("t7")
    run(c, "plan")
    c2 = make("t7do")
    run(c2, "do", stub_phase="do")
    c3 = make("t7rev")
    run(c3, "review")
    got = calls(c) + calls(c2) + calls(c3)
    assert len(got) == 4 and all(x["auto_memory_off"] == "1" for x in got), [x["auto_memory_off"] for x in got]
    p = os.path.join(c2["rec"], "canary_env.jsonl")
    assert os.path.exists(p), "点検の claude が呼ばれていない"
    assert all(json.loads(ln)["auto_memory_off"] is None for ln in open(p, encoding="utf-8").read().splitlines()), "点検の claude に付いている"


def main():
    global fails
    g = globals()
    for n in names:
        try:
            g[n]()
            print(f"  ok   {n}")
        except AssertionError as e:
            fails += 1
            print(f"  FAIL {n}: {e}")
        except Exception as e:  # noqa: BLE001
            fails += 1
            print(f"  FAIL {n}: {e.__class__.__name__}: {e}")
    print(f"\n{len(names) - fails}/{len(names)} passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
