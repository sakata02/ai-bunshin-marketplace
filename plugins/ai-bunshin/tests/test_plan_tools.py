"""朝の計画の材料（update_dashboard.py --plan-context）の最後の節
「自動実行で使える道具・書けない場所（daily_cycle.sh:行番号 から）」のテスト。
- 今の daily_cycle.sh（実物）から読む：計画は WebFetch・WebSearch が止める側、実行は使える側
- Edit(CLAUDE.md)・Edit(設定/**) が書けない場所に出る
- 出る行番号が daily_cycle.sh の実際の行と合う
- 読めない形の行をまぜたコピーでも落ちず、1行目（OPEN/SKIP）とほかの節は変わらない／daily_cycle.sh が無くても落ちない
- 計画から続けて実行に入るときの値が実行と違えば、違いを出す
実行：python3 tests/test_plan_tools.py（失敗があれば終了コード1）。本物のフォルダ・本物の daily_cycle.sh は書き換えず、一時フォルダのコピーだけで動く。
別のコピーを確かめるとき：PLAN_TOOLS_SCRIPTS=<scripts フォルダ> python3 tests/test_plan_tools.py"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.abspath(os.environ.get("PLAN_TOOLS_SCRIPTS") or os.path.join(HERE, "..", "scripts"))

BASE = os.path.realpath(tempfile.mkdtemp(prefix="t141_plantools_"))
HOME_DIR = os.path.join(BASE, "owner")
FAKE_HOME = os.path.join(BASE, "home")
for d in (os.path.join(HOME_DIR, "設定"), os.path.join(HOME_DIR, "00_タスク管理", "data"), FAKE_HOME):
    os.makedirs(d)
json.dump({"owner": "テスト", "owner_call": "テストさん", "ai_name": "テストAI", "departments": ["総務"]},
          open(os.path.join(HOME_DIR, "設定", "config.json"), "w", encoding="utf-8"), ensure_ascii=False)
json.dump({"project": {"name": "テスト", "daily_capacity_default": 1.0, "holidays": []}, "daily_sprints": [], "sprints": [], "tasks": []},
          open(os.path.join(HOME_DIR, "00_タスク管理", "data", "tasks.json"), "w", encoding="utf-8"), ensure_ascii=False)

SECTION = "## 自動実行で使える道具・書けない場所"
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
            print(f"[{fn.__name__}] 例外: {type(e).__name__}: {e}")


def make_plugin(name, cycle_edit=None, with_cycle=True):
    """scripts のコピーを一時フォルダに作る（<name>/scripts/…）。cycle_edit(行のリスト) -> 行のリスト でコピー側の daily_cycle.sh を直せる"""
    root = os.path.join(BASE, name)
    shutil.copytree(SCRIPTS, os.path.join(root, "scripts"), ignore=shutil.ignore_patterns("__pycache__", "*.bak*"))
    cycle = os.path.join(root, "scripts", "auto", "daily_cycle.sh")
    if not with_cycle:
        os.rename(cycle, cycle + ".moved")
    elif cycle_edit:
        lines = open(cycle, encoding="utf-8").read().split("\n")
        open(cycle, "w", encoding="utf-8").write("\n".join(cycle_edit(lines)))
    return root


def plan_context(plugin_root=None):
    script = os.path.join(plugin_root, "scripts", "update_dashboard.py") if plugin_root else os.path.join(SCRIPTS, "update_dashboard.py")
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR",)}
    env["AI_BUNSHIN_HOME"] = HOME_DIR
    env["HOME"] = FAKE_HOME
    r = subprocess.run([sys.executable, script, "--plan-context", "--today", "2026-11-02"], capture_output=True, text=True, cwd=HOME_DIR, env=env)
    assert r.returncode == 0, f"終了コード {r.returncode}: {r.stderr[-500:]}"
    return r.stdout


def section(out):
    assert SECTION in out, f"節が出ていない: {out[-600:]}"
    return out[out.index(SECTION):].splitlines()


def find(sec, prefix):
    hits = [l for l in sec if l.startswith(prefix)]
    assert len(hits) == 1, f"{prefix!r} の行が {len(hits)} 本: {sec}"
    return hits[0]


def real_cycle_lines():
    return open(os.path.join(SCRIPTS, "auto", "daily_cycle.sh"), encoding="utf-8").read().split("\n")


@case
def web_tools_blocked_in_plan_and_allowed_in_do():
    sec = section(plan_context())
    plan_ok = find(sec, "- 計画　使える道具")
    i = sec.index(plan_ok)
    plan_stop = sec[i + 1]
    assert "止める道具" in plan_stop and "WebFetch" in plan_stop and "WebSearch" in plan_stop, f"計画の止める側に WebFetch・WebSearch が無い: {plan_stop}"
    assert "WebFetch" not in plan_ok and "WebSearch" not in plan_ok, f"計画の使える側に WebFetch・WebSearch がある: {plan_ok}"
    do_ok = find(sec, "- 実行　使える道具")
    do_stop = sec[sec.index(do_ok) + 1]
    assert "WebFetch" in do_ok and "WebSearch" in do_ok, f"実行の使える側に WebFetch・WebSearch が無い: {do_ok}"
    assert "WebFetch" not in do_stop and "WebSearch" not in do_stop, f"実行の止める側に WebFetch・WebSearch がある: {do_stop}"
    assert "Bash(rm:*)" in do_stop and "Bash(curl:*)" in do_stop, f"rm・curl が止める側に無い: {do_stop}"


@case
def unwritable_places_are_listed():
    sec = section(plan_context())
    i = sec.index(find(sec, "- 計画　使える道具"))
    places = sec[i + 2]
    assert "書けない場所" in places, places
    for want in ("Edit(CLAUDE.md)", "Edit(設定/**)", "Edit(scripts/**)", "Edit(.claude/**)"):
        assert want in places, f"{want} が書けない場所に無い: {places}"
    assert "Bash(rm" not in places, f"書けない場所に Bash の止めが混ざっている: {places}"
    text = "\n".join(sec)
    assert "Write など、ファイルを書く道具すべてに効く" in text, "Edit の決まりが Write にも効くという1行が無い"
    assert "ng_guard.py --explain" in text and "自動モード" in text, "定数では分からないものの1行が無い"


@case
def line_numbers_match_real_lines():
    sec = section(plan_context())
    cyc = real_cycle_lines()

    def nums(line):
        m = re.search(r"daily_cycle\.sh((?::\d+・?)+)", line)
        assert m, f"行番号が無い: {line}"
        return [int(n) for n in re.findall(r":(\d+)", m.group(1))]
    checked = 0
    for l in sec:
        if l.startswith("##") or "（daily_cycle.sh:" not in l or not re.search(r"(使える道具|止める道具|書けない場所)", l):
            continue
        kind = "TOOLS" if "使える道具" in l else "DENY"
        for n in nums(l):
            assert cyc[n - 1].lstrip().startswith(kind + "="), f"{n} 行目が {kind}= の行でない: {cyc[n - 1]!r}（{l[:40]}）"
            checked += 1
    assert checked >= 10, f"行番号の確認が少なすぎる: {checked}"
    # 実行に WebFetch を足している行（:行）は、実物でも WebFetch を含む
    do_ok = find(sec, "- 実行　使える道具")
    assert any("WebFetch" in cyc[n - 1] for n in nums(do_ok)), f"実行の行番号の中に WebFetch の行が無い: {do_ok[:60]}"
    plan_stop = sec[sec.index(find(sec, "- 計画　使える道具")) + 1]
    assert any("WebFetch" in cyc[n - 1] for n in nums(plan_stop)), f"計画の止める側の行番号の中に WebFetch の行が無い: {plan_stop[:60]}"
    assert "$DASH" not in "\n".join(sec) and "$PLUGIN_ROOT" not in "\n".join(sec), "$DASH・$PLUGIN_ROOT が実際のパスになっていない"


@case
def real_continuation_matches_do_and_no_warning():
    text = "\n".join(section(plan_context()))
    assert "注意：" not in text, f"今の daily_cycle.sh で違いの注意が出ている: {text}"
    assert "読めませんでした" not in text, f"今の daily_cycle.sh で読めなかった行がある: {text}"
    assert "- 実行（計画から続けて入るとき）　使える道具" in text, "続けて実行に入るときの行が無い"


@case
def unreadable_line_is_reported_and_nothing_else_changes():
    def edit(lines):
        i = next(n for n, l in enumerate(lines) if l.startswith("DENY="))
        return lines[:i + 1] + ['TOOLS=$(echo Read)'] + lines[i + 1:]
    broken_root = make_plugin("t141_broken", edit)
    broken_no = next(n for n, l in enumerate(open(os.path.join(broken_root, "scripts", "auto", "daily_cycle.sh"), encoding="utf-8").read().split("\n"), 1) if l == "TOOLS=$(echo Read)")
    good, bad = plan_context(), plan_context(broken_root)
    assert good.splitlines()[0] == bad.splitlines()[0] and bad.splitlines()[0].startswith(("OPEN", "SKIP")), f"1行目が変わった: {bad.splitlines()[0]}"
    assert f"daily_cycle.sh:{broken_no} の行は読めませんでした。使う前に1回ためしてください" in bad, f"読めない行の報告が無い: {bad[-700:]}"
    assert "読めませんでした" not in good
    head = lambda o: o[:o.index(SECTION)]  # noqa: E731
    assert head(good) == head(bad), "ほかの節が変わった"
    assert "- 計画　使える道具" in bad, "読めない行があるほかの行も出る"


@case
def missing_or_unreadable_cycle_file_does_not_crash():
    root = make_plugin("t141_nocycle", with_cycle=False)
    out = plan_context(root)
    assert out.splitlines()[0].startswith(("OPEN", "SKIP")), out.splitlines()[0]
    assert SECTION in out and "読めませんでした" in out[out.index(SECTION):], f"読めない報告が無い: {out[-400:]}"
    assert out.splitlines()[0] == plan_context().splitlines()[0], "1行目が変わった"
    # 中身が読めないデータ（文字コードが違う）でも落ちない
    root2 = make_plugin("t141_badbytes")
    open(os.path.join(root2, "scripts", "auto", "daily_cycle.sh"), "wb").write(b"\xff\xfe\x00TOOLS=\x80\n")
    out2 = plan_context(root2)
    assert "読めませんでした" in out2[out2.index(SECTION):], f"文字コードが違うときの報告が無い: {out2[-400:]}"


@case
def difference_between_do_and_continuation_is_reported():
    def edit(lines):  # 続けて実行に入る所の取り除きを、足すだけに変える（今は空振りしていない。差が出る形を作って確かめる）
        return [('  DENY="$DENY,Bash(x:*)"' if l.strip() == 'DENY="${DENY/,WebFetch,WebSearch/}"' else l) for l in lines]
    root = make_plugin("t141_diff", edit)
    sec = "\n".join(section(plan_context(root)))
    assert "注意：" in sec and "Bash(x:*)" in sec, f"違いの注意が出ない: {sec[-900:]}"


@case
def parser_handles_the_three_forms():
    sys.path.insert(0, SCRIPTS)
    os.environ["AI_BUNSHIN_HOME"] = HOME_DIR
    os.environ["HOME"] = FAKE_HOME
    import importlib
    u = importlib.import_module("update_dashboard")
    env = {"DASH": "/d/u.py", "PLUGIN_ROOT": "/p"}
    cur = {"TOOLS": "A,B", "DENY": "x,y,z"}
    eq = lambda got, want: (got == want) or (_ for _ in ()).throw(AssertionError(f"{got!r} != {want!r}"))  # noqa: E731
    eq(u._apply_assign('TOOLS="Read,Bash(python3 $DASH:*),$UNKNOWN"', cur, env), ("TOOLS", "Read,Bash(python3 /d/u.py:*),$UNKNOWN"))
    eq(u._apply_assign('  TOOLS="$TOOLS,W"   # 注釈', cur, env), ("TOOLS", "A,B,W"))
    eq(u._apply_assign('DENY="${DENY/,y/}"', cur, env), ("DENY", "x,z"))
    eq(u._apply_assign('DENY="Edit(/$PLUGIN_ROOT/**)"', cur, env), ("DENY", "Edit(//p/**)"))
    eq(u._apply_assign('TOOLS="a \\"$DASH\\""', cur, env), ("TOOLS", 'a "/d/u.py"'))
    for bad in ('TOOLS=$(x)', 'TOOLS="$(x)"', 'TOOLS=abc', "TOOLS='abc'", 'DENY="${DENY/*/}"', 'TOOLS="a" b', 'TOOLS="${FOO:-a}"'):
        eq(u._apply_assign(bad, cur, env), None)


run_all()
print(f"失敗 {fails} 件（{len(names)} 項目）")
sys.exit(1 if fails else 0)
