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
    assert "ファイルを書く道具（Write など）に効く" in text and "Bash でファイルに書くことには効かない" in text, "Edit の決まりの注記が無い"
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
    assert checked >= 8, f"行番号の確認が少なすぎる: {checked}"
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
    assert "- 実行（計画から続けて入るとき）　実行と同じ（daily_cycle.sh:" in text and "を通っても変わらない）" in text, f"続けて実行に入るときの「実行と同じ」の行が無い: {text}"


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
    import importlib
    sys.path.insert(0, SCRIPTS)
    os.environ["AI_BUNSHIN_HOME"] = HOME_DIR
    os.environ["HOME"] = FAKE_HOME
    u = importlib.import_module("update_dashboard")
    P = u._parse_assign
    assert P('TOOLS="Read,Bash(python3 $DASH:*),${PLUGIN_ROOT}/x"') == ("TOOLS", [("text", "Read,Bash(python3 "), ("ref", "DASH"), ("text", ":*),"), ("ref", "PLUGIN_ROOT"), ("text", "/x")])
    assert P('  TOOLS="$TOOLS,W"   # 注釈') == ("TOOLS", [("ref", "TOOLS"), ("text", ",W")])
    assert P('DENY="${DENY/,y/}"') == ("DENY", [("remove", ",y")])
    assert P('TOOLS="a \\"$DASH\\""') == ("TOOLS", [("text", 'a "'), ("ref", "DASH"), ("text", '"')])
    for bad in ('TOOLS=$(x)', 'TOOLS="$(x)"', 'TOOLS=abc', "TOOLS='abc'", 'DENY="${DENY/*/}"', 'TOOLS="a" b', 'TOOLS="${FOO:-a}"',
                'TOOLS="a"; x', 'TOOLS="a"#c', 'TOOLS="$DASH:t"', 'TOOLS="$HOME"', 'TOOLS="\\$DASH"', 'DENY="x${DENY/a/}"', 'DENY="${TOOLS/a/}"',
                'export TOOLS="a"', 'TOOLS+="a"', 'TOOLS="a'):
        assert P(bad) is None, f"読めてしまった: {bad}"


# ---- 白リスト：読めない書き方は「なし」や値を出さず「読めませんでした」と出す（Y7①） ----
BASE_TOOLS = 'TOOLS="a,b"'
BASE_DENY = 'DENY="Bash(rm:*),Edit(CLAUDE.md)"'
ALL3 = {"plan", "do", "cont"}


def body(base_extra="", do="", plan="", after=""):
    parts = [BASE_TOOLS, BASE_DENY, base_extra, 'if [ "$PHASE" = "do" ]; then', do or "  :", "else", plan or "  :", "fi", after]
    return "\n".join(parts) + "\n"


def write_cycle(text):
    d = tempfile.mkdtemp(prefix="t141_adv_", dir=BASE)
    path = os.path.join(d, "daily_cycle.sh")
    open(path, "w", encoding="utf-8").write(text)
    return path


def phase_lines(out_lines, phase):
    label = {"plan": "- 計画　", "do": "- 実行　", "cont": "- 実行（計画から続けて入るとき）　"}[phase]
    i = next((n for n, l in enumerate(out_lines) if l.startswith(label)), None)
    if i is None:
        return None
    return out_lines[i:i + 3]


# 名前：(中身, {変数: 読めなくなる段})。after に何も無い形では「続けて」の段は出ない
ADVERSARIAL = {
    "semicolon_two": (body('TOOLS="x"; DENY="y"'), {"TOOLS": {"plan", "do"}, "DENY": {"plan", "do"}}),
    "plus_equals": (body('TOOLS+=",PE"'), {"TOOLS": {"plan", "do"}}),
    "one_line_if": (body('if true; then TOOLS="z"; fi'), {"TOOLS": {"plan", "do"}}),
    "and_and": (body('[ -n "$ROOT" ] && TOOLS="$TOOLS,COND"'), {"TOOLS": {"plan", "do"}}),
    "or_or": (body('[ -z "$ROOT" ] || DENY="$DENY,X"'), {"DENY": {"plan", "do"}}),
    "elif_in_block": (body(do='  TOOLS="$TOOLS,DO"\nelif [ "$PHASE" = "x" ]; then\n  TOOLS="$TOOLS,X"'), {"TOOLS": {"plan", "do"}}),
    "case_in_plan_side": (body(plan='  case "$X" in\n    a) TOOLS="$TOOLS,C" ;;\n  esac'), {"TOOLS": {"plan"}}),
    "other_if_in_do_side": (body(do='  if [ -n "$X" ]; then\n    DENY="$DENY,Y"\n  fi'), {"DENY": {"do"}}),
    "unknown_var": (body('TOOLS="a,Bash($HOME/x:*)"'), {"TOOLS": {"plan", "do"}}),
    "escaped_dollar": (body('TOOLS="a,Bash(echo \\$DASH)"'), {"TOOLS": {"plan", "do"}}),
    "dollar_modifier": (body('TOOLS="a,Bash(python3 $DASH:t)"'), {"TOOLS": {"plan", "do"}}),
    "brace_other_name": (body('TOOLS="a,${HOME}"'), {"TOOLS": {"plan", "do"}}),
    "special_pattern_paren": (body(do='  DENY="${DENY/Edit(CLAUDE.md),/}"'), {"DENY": {"do"}}),
    "special_pattern_hash": (body(do='  DENY="${DENY/#Bash/}"'), {"DENY": {"do"}}),
    "special_pattern_star": (body(plan='  DENY="${DENY/*/}"'), {"DENY": {"plan"}}),
    "remove_other_var": (body(plan='  DENY="${TOOLS/a/}"'), {"DENY": {"plan"}}),
    "local_in_function": (body('f() {\n  local TOOLS="inner"\n}'), {"TOOLS": {"plan", "do"}}),
    "export_form": (body('export TOOLS="q"'), {"TOOLS": {"plan", "do"}}),
    "trailing_semicolon": (body('TOOLS="$TOOLS,x";'), {"TOOLS": {"plan", "do"}}),
    "command_substitution": (body('TOOLS="a,$(echo x)"'), {"TOOLS": {"plan", "do"}}),
    "backtick": (body('TOOLS="a,`echo x`"'), {"TOOLS": {"plan", "do"}}),
    "backslash_other": (body('TOOLS="a,Bash(printf \\n)"'), {"TOOLS": {"plan", "do"}}),
    "unclosed_string": (body('TOOLS="a,\nb"'), {"TOOLS": {"plan", "do"}}),
    "colon_default_form": (body(': ${TOOLS:="x"}'), {"TOOLS": {"plan", "do"}}),
    "unreadable_then_append_stays_unreadable": (body('TOOLS=$(x)\nTOOLS="$TOOLS,more"'), {"TOOLS": {"plan", "do"}}),
    # Q1：分かれ目の fi のあとで、続けて実行の if（plan）の外にある代入は、計画・実行の両方に効くかもしれないので読めない
    "other_if_after": (body(after='if [ "$PHASE" = "review" ]; then\n  TOOLS="$TOOLS,REV"\nfi'), {"TOOLS": {"plan", "do"}}),
    "plain_assign_after_fi": (body(after='TOOLS="$TOOLS,LATE"'), {"TOOLS": {"plan", "do"}}),
    "plain_assign_after_fi_deny": (body(after='DENY="$DENY,LATE"'), {"DENY": {"plan", "do"}}),
    "after_plan_if_then_plain": (body(after='if [ "$PHASE" = "plan" ]; then\n  TOOLS="$TOOLS,P"\nfi\nDENY="$DENY,LATE"'), {"DENY": {"plan", "do"}}),
    # Q2：続けて実行の if（plan）に else・elif・入れ子の if があれば、続けて実行の分だけ読めない（計画・実行は読めたまま）
    "plan_if_with_else": (body(after='if [ "$PHASE" = "plan" ]; then\n  TOOLS="$TOOLS,P"\nelse\n  TOOLS="$TOOLS,E"\nfi'), {"TOOLS": {"cont"}}),
    "plan_if_with_elif": (body(after='if [ "$PHASE" = "plan" ]; then\n  TOOLS="$TOOLS,P"\nelif [ -n "$X" ]; then\n  TOOLS="$TOOLS,E"\nfi'), {"TOOLS": {"cont"}}),
    "plan_if_with_nested_if": (body(after='if [ "$PHASE" = "plan" ]; then\n  if [ -n "$X" ]; then\n    DENY="$DENY,N"\n  fi\n  TOOLS="$TOOLS,P"\nfi'), {"DENY": {"cont"}}),
    # Q3：関数の中の代入は、どの段も読めない。あとの普通の代入でも読めた扱いに戻さない
    "function_assign_then_plain_assign": (body('f() {\n  TOOLS="$TOOLS,F"\n}', do='  TOOLS="z"', plan='  TOOLS="y"'), {"TOOLS": {"plan", "do"}}),
    "function_one_line": (body('f() { TOOLS="x"; }'), {"TOOLS": {"plan", "do"}}),
    "function_keyword": (body('function g {\n  DENY="x"\n}', do='  DENY="z"'), {"DENY": {"plan", "do"}}),
}


@case
def adversarial_forms_say_unreadable_never_none():
    for name, (text, expect) in ADVERSARIAL.items():
        out = open_lines(text)
        sec = "\n".join(out)
        assert "読めませんでした" in sec, f"[{name}] 読めませんでした が出ていない: {sec[:300]}"
        for var, phases in expect.items():
            for ph in phases:
                lines = phase_lines(out, ph)
                assert lines, f"[{name}] {ph} の行が無い"
                targets = [lines[0]] if var == "TOOLS" else [lines[1], lines[2]]
                for l in targets:
                    assert "（読めませんでした：daily_cycle.sh:" in l, f"[{name}] {ph}の{var}が読めませんでしたになっていない: {l}"
                    assert "：なし" not in l, f"[{name}] 読めない変数が「なし」になった: {l}"
        for var in ("TOOLS", "DENY"):
            for ph in ("plan", "do"):
                if ph in expect.get(var, set()):
                    continue
                lines = phase_lines(out, ph)
                l = lines[0] if var == "TOOLS" else lines[1]
                assert "（読めませんでした：" not in l, f"[{name}] 読める {ph} の{var}まで読めない扱いになった: {l}"


def open_lines(text):
    import importlib
    sys.path.insert(0, SCRIPTS)
    os.environ["AI_BUNSHIN_HOME"] = HOME_DIR
    os.environ["HOME"] = FAKE_HOME
    u = importlib.import_module("update_dashboard")
    return u.auto_tools_lines(write_cycle(text))


@case
def plan_if_unreadable_forms_keep_other_variable_readable_in_cont():
    out = open_lines(body(after='if [ "$PHASE" = "plan" ]; then\n  if [ -n "$X" ]; then\n    DENY="$DENY,N"\n  fi\n  TOOLS="$TOOLS,P"\nfi'))
    cont = phase_lines(out, "cont")
    assert cont and "（読めませんでした：" not in cont[0] and "a, b, P" in cont[0], f"読める TOOLS まで読めない扱い、または値が違う: {cont}"
    assert "（読めませんでした：" in cont[1] and "（読めませんでした：" in cont[2], f"入れ子の if の中の DENY が読めませんでしたになっていない: {cont}"
    for ph in ("plan", "do"):
        l = phase_lines(out, ph)
        assert all("（読めませんでした：" not in x for x in l), f"{ph} まで読めない扱いになった: {l}"


@case
def real_cycle_layout_is_still_readable_after_fi():
    """今の実物の形（分かれ目の fi のあとの、plan の if の中の代入）は、読めたままで「実行と同じ」と出る"""
    out = open_lines(body(after='if [ "$PHASE" = "plan" ]; then\n  TOOLS="$TOOLS,WebSearch,WebFetch"\n  DENY="${DENY/,x/}"\nfi'))
    cont = phase_lines(out, "cont")
    assert cont and "（読めませんでした：" not in "\n".join(cont), cont


@case
def heredoc_text_and_reads_are_not_assignments():
    text = body(base_extra='cat <<EOF\nTOOLS="fake"\nif x; then\nEOF\necho "$TOOLS" "${DENY}" # TOOLS="c"')
    sec = "\n".join(open_lines(text))
    assert "読めませんでした" not in sec, f"読むだけの行・heredoc の中が読めない扱いになった: {sec}"
    assert "使える道具（daily_cycle.sh:1）：a, b" in sec, sec


@case
def broken_structure_does_not_trust_values():
    sec = "\n".join(open_lines(body() + 'if true; then\n'))   # fi が足りない
    assert "組み合わせが読めませんでした" in sec and "（読めませんでした：" in sec, sec
    sec2 = "\n".join(open_lines(body() + 'fi\n'))   # fi が多い
    assert "組み合わせが読めませんでした" in sec2, sec2


@case
def real_values_match_zsh_evaluation():
    """今の daily_cycle.sh の代入の行を、zsh に評価させた値と、読んだ値が一致する（zsh が無ければ飛ばす）"""
    zsh = shutil.which("zsh")
    if not zsh:
        print("  （zsh が無いので、zsh との一致の確かめは飛ばした）")
        return
    import importlib
    sys.path.insert(0, SCRIPTS)
    os.environ["AI_BUNSHIN_HOME"] = HOME_DIR
    os.environ["HOME"] = FAKE_HOME
    u = importlib.import_module("update_dashboard")
    cyc = real_cycle_lines()
    # 実物の if（do）と fi の位置を、読み方とは別に探す
    l1 = next(n for n, l in enumerate(cyc) if l.strip() == 'if [ "$PHASE" = "do" ]; then')
    l2 = next(n for n in range(l1, len(cyc)) if cyc[n].strip() == "fi")
    assign = re.compile(r"^\s*(TOOLS|DENY)=")
    before = [l for l in cyc[:l1] if assign.match(l)]
    block = cyc[l1:l2 + 1]
    after = [l for l in cyc[l2 + 1:] if assign.match(l)]
    plugin_root = os.path.dirname(SCRIPTS)
    res = u.read_auto_tools(os.path.join(SCRIPTS, "auto", "daily_cycle.sh"))
    for mode in ("plan", "do", "cont"):
        phase = "do" if mode == "do" else "plan"
        script = "\n".join([f'PLUGIN_ROOT="{plugin_root}"', f'DASH="$PLUGIN_ROOT/scripts/update_dashboard.py"', f'PHASE={phase}'] + before + block
                            + (after if mode == "cont" else []) + ['printf "%s\\n" "$TOOLS"', 'printf "%s\\n" "$DENY"'])
        r = subprocess.run([zsh, "-c", script], capture_output=True, text=True)
        assert r.returncode == 0, f"zsh が失敗: {r.stderr[-300:]}"
        z_tools, z_deny = r.stdout.split("\n")[:2]
        ph = res["phases"].get("cont" if mode == "cont" else mode)
        assert ph, f"{mode} の値が無い"
        assert ph["TOOLS"]["val"] == z_tools, f"{mode} の TOOLS が zsh と違う:\n  読んだ {ph['TOOLS']['val']}\n  zsh   {z_tools}"
        assert ph["DENY"]["val"] == z_deny, f"{mode} の DENY が zsh と違う:\n  読んだ {ph['DENY']['val']}\n  zsh   {z_deny}"


@case
def sandbox_python_line_is_in_the_section_with_real_line_number():
    """T119 G5b（S18）：実行の段の Python の1行が出る。行番号は実物の SANDBOX_TOOLS=",Bash(python3:*)" の行。上の使える道具の一覧は変わらない"""
    sec = section(plan_context())
    l = find(sec, "- 実行の段は、囲いの設定が作れて点検（カナリア）が全部止まった日だけ `Bash(python3:*)` も使える")
    for want in ("囲いの守る先（sandbox_settings.py の denyWrite）には書けず、カレンダーの取得先以外へは通信もできない", "囲いが作れない日や点検が通らない日は上の道具のまま", "計画・振り返りの段では使えない"):
        assert want in l, f"{want} が無い: {l}"
    cyc = real_cycle_lines()
    want_no = [n for n, x in enumerate(cyc, 1) if x.strip() == 'SANDBOX_TOOLS=",Bash(python3:*)"']
    assert len(want_no) == 1, f"実物に python3 の行が {len(want_no)} 本: {want_no}"
    assert f"（daily_cycle.sh:{want_no[0]}）" in l, f"行番号が実物の行（{want_no[0]}）と合わない: {l}"
    # 上の一覧（定数から読んだもの）に python3 を混ぜない
    for key in ("- 計画　使える道具", "- 実行　使える道具"):
        assert "python3:*" not in find(sec, key), f"使える道具の一覧に Bash(python3:*) が混ざった: {find(sec, key)}"


@case
def sandbox_python_line_without_cycle_line_does_not_crash():
    """daily_cycle.sh に python3 の行が無い・読めない形でも、--plan-context は落ちず、行は行番号なしで出る"""
    def gone(lines):
        return [("# (なくした)" if l.strip() == 'SANDBOX_TOOLS=",Bash(python3:*)"' else l) for l in lines]

    def odd(lines):
        return [('SANDBOX_TOOLS=$(printf ",Bash(%s)" "python3:*")' if l.strip() == 'SANDBOX_TOOLS=",Bash(python3:*)"' else l) for l in lines]
    for name, edit in (("t119g5b_gone", gone), ("t119g5b_odd", odd)):
        root = make_plugin(name, edit)
        out = plan_context(root)
        assert out.splitlines()[0].startswith(("OPEN", "SKIP")), f"[{name}] 1行目: {out.splitlines()[0]}"
        l = find(section(out), "- 実行の段は、囲いの設定が作れて点検（カナリア）が全部止まった日だけ `Bash(python3:*)` も使える")
        assert "daily_cycle.sh" not in l, f"[{name}] 行番号が出ている: {l}"
        assert "使える。その日も、囲いの守る先" in l, f"[{name}] 行番号なしの文になっていない: {l}"


run_all()
print(f"失敗 {fails} 件（{len(names)} 項目）")
sys.exit(1 if fails else 0)
