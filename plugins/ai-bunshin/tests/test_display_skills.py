"""使い方の型（display。T182）が、スキル・詳しい手順・スクリプトの間で守られているかのテスト（組⑦b）。
返事は AI が書く文なのでテストで固定できない（K5）。確かめるのは、スキルの「出力の印」の中の文と、2つのスクリプトの文面まで。
- (1) skills/*/SKILL.md の `<!-- 出力 -->` と `<!-- /出力 -->` が、開いて閉じる対になっている（入れ子・閉じ忘れ・閉じ過ぎがない）
- (2) 印の中の「シンプルのとき」の文に、シンプルで出さない言葉（部下・pt・Try・ベロシティ・スプリント・PDCA・KPT）が0件。
      言葉の一覧は rules/details/display.md の terms の行から読む（ここに別の一覧を持たない。読めなければ落とす）
- (3) 印の中に、手順の言葉（登録する・完了にする・do_log・追記してよいか）が無い（出す文だけを印で囲む。手順は印の外に置く）
- (4) skills と rules/details に、設計の決定の番号（K1〜K19・U01〜U16）が出ない（本人にも AI にも意味のない番号を本文に残さない）
- (5) K3：set_display.py と update_dashboard.py の「[見せ方：…]」の文（シンプル・フル・壊れたとき）と、
      個別の設定の行の形（文字列・並び）が1文字も違わない（2つのファイルから取り出して比べる）
本物の自分のフォルダは使わない（読むだけ。(5) の読み込みは一時フォルダを指す）。
壊したコピーで確かめるときは、環境変数 DISPLAY_SKILLS_PLUGIN にコピーのパス（plugins/ai-bunshin の写し）を入れる。
実行：python3 tests/test_display_skills.py（失敗があれば終了コード1）"""
import ast
import glob
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.environ.get("DISPLAY_SKILLS_PLUGIN") or os.path.join(HERE, ".."))
SKILLS = sorted(glob.glob(os.path.join(PLUGIN, "skills", "*", "SKILL.md")))
DETAILS = sorted(glob.glob(os.path.join(PLUGIN, "rules", "details", "*.md")))
DISPLAY_MD = os.path.join(PLUGIN, "rules", "details", "display.md")
SET_DISPLAY = os.path.join(PLUGIN, "scripts", "set_display.py")
DASHBOARD = os.path.join(PLUGIN, "scripts", "update_dashboard.py")

OPEN, CLOSE = "<!-- 出力 -->", "<!-- /出力 -->"
# (3) 手順の言葉。出力の印の中に置かない
PROCEDURE_WORDS = ("登録する", "完了にする", "do_log", "追記してよいか")
# (3) 例外（名指し）。ファイル名・その文にある言葉・理由。ここに無いものは落とす
PROCEDURE_EXCEPTIONS = [
    ("daily-do", "do_log・tasks.json の中身は型で変えずに同じに書く",
     "「型で変えない」と言う文で、do_log に書く手順そのものではない（指揮官が確かめた文）"),
]
# (4) 決定の番号
DECISION_NO = re.compile(r"(?<![A-Za-z0-9])(?:K(?:1[0-9]|[1-9])|U(?:0[1-9]|1[0-6]))(?![0-9])")

fails = 0


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


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def rel(path):
    return os.path.relpath(path, PLUGIN)


def skill_name(path):
    return os.path.basename(os.path.dirname(path))


def blocks_of(path):
    """印の中の行を、(開始行番号, [(行番号, 行), …]) の一覧で返す。対になっていなければ AssertionError。"""
    out, cur, start = [], None, 0
    for n, line in enumerate(read(path).split("\n"), 1):
        s = line.strip()
        if s == OPEN:
            assert cur is None, f"{rel(path)}:{n} 印が入れ子（{start} 行目の印が閉じていない）"
            cur, start = [], n
        elif s == CLOSE:
            assert cur is not None, f"{rel(path)}:{n} 開いていない印を閉じている"
            out.append((start, cur))
            cur = None
        elif cur is not None:
            cur.append((n, line))
    assert cur is None, f"{rel(path)}:{start} 印が閉じていない"
    return out


def simple_sentences(block_lines):
    """印の中の「シンプルのとき」の文（行番号つきの行の一覧）。
    「シンプルのとき」を含む行から。その行が「：」で終わるときは、続く行（箇条書き）も、空行か「フル、」の行まで。"""
    out = []
    i = 0
    while i < len(block_lines):
        n, line = block_lines[i]
        if "シンプルのとき" in line:
            out.append((n, line))
            if line.rstrip().endswith("：") or line.rstrip().endswith(":"):
                j = i + 1
                while j < len(block_lines) and block_lines[j][1].strip() and not block_lines[j][1].lstrip().startswith("フル、"):
                    out.append(block_lines[j])
                    j += 1
                i = j
                continue
        i += 1
    return out


def forbidden_words():
    """display.md の terms の行（「部下・pt・… を出さず言い換える」）から、シンプルで出さない言葉を読む。"""
    text = read(DISPLAY_MD)
    m = re.search(r"\| `terms` \|[^\n]*?([^|\s]+) を出さず言い換える", text)
    assert m, "display.md の terms の行から「シンプルで出さない言葉」の一覧を読めない"
    words = m.group(1).split("・")
    assert len(words) >= 7 and {"部下", "pt", "Try"} <= set(words), f"読んだ一覧がおかしい：{words}"
    return words


def word_regex(w):
    # 英字の言葉（pt・Try・PDCA・KPT）は、ほかの英単語の一部（script・Trying など）に当てない
    if re.fullmatch(r"[A-Za-z]+", w):
        return re.compile(rf"(?<![A-Za-z]){re.escape(w)}(?![a-z])" if w[0].isupper() else rf"(?<![A-Za-z]){re.escape(w)}(?![A-Za-z])")
    return re.compile(re.escape(w))


# ---------------------------------------------------------------- (1) 印の対

@case
def t1_marks_are_paired():
    assert SKILLS, "skills/*/SKILL.md が見つからない"
    total = 0
    for p in SKILLS:
        text = read(p)
        assert text.count(OPEN) == text.count(CLOSE), f"{rel(p)}：開く印 {text.count(OPEN)} 個・閉じる印 {text.count(CLOSE)} 個"
        total += len(blocks_of(p))
    assert total >= 10, f"印が {total} 個しかない（出力の節が消えている？）"


# ---------------------------------------------------------------- (2) シンプルの文に出さない言葉が無い

@case
def t2_simple_sentences_have_no_forbidden_words():
    words = forbidden_words()
    regs = [(w, word_regex(w)) for w in words]
    seen = 0
    bad = []
    for p in SKILLS:
        for start, lines in blocks_of(p):
            sent = simple_sentences(lines)
            seen += len(sent)
            for n, line in sent:
                for w, rg in regs:
                    if rg.search(line):
                        bad.append(f"{rel(p)}:{n} 「{w}」 {line.strip()[:50]}")
    assert seen >= 10, f"「シンプルのとき」の文が {seen} 行しか見つからない（読み方が壊れた？）"
    assert not bad, "シンプルの文に出さない言葉がある：\n    " + "\n    ".join(bad)


# ---------------------------------------------------------------- (3) 印の中に手順の言葉が無い

@case
def t3_no_procedure_words_inside_marks():
    bad = []
    for p in SKILLS:
        name = skill_name(p)
        for start, lines in blocks_of(p):
            for n, line in lines:
                shown = line
                for sk, phrase, _why in PROCEDURE_EXCEPTIONS:
                    if sk == name and phrase in shown:
                        shown = shown.replace(phrase, "")
                for w in PROCEDURE_WORDS:
                    if w in shown:
                        bad.append(f"{rel(p)}:{n} 「{w}」 {line.strip()[:50]}")
    assert not bad, "印の中に手順の言葉がある（手順は印の外へ）：\n    " + "\n    ".join(bad)


@case
def t3b_exceptions_are_still_needed():
    # 例外の文が無くなっていたら、例外の行も消す（使っていない例外を残さない）
    for sk, phrase, _why in PROCEDURE_EXCEPTIONS:
        path = os.path.join(PLUGIN, "skills", sk, "SKILL.md")
        inside = [line for _s, ls in blocks_of(path) for _n, line in ls]
        assert any(phrase in l for l in inside), f"例外の文が {sk} の印の中に無い：{phrase}"


# ---------------------------------------------------------------- (4) 決定の番号が本文に出ない

@case
def t4_no_decision_numbers_in_skills_and_details():
    bad = []
    files = SKILLS + DETAILS
    assert len(files) >= 10, "確かめるファイルが少ない"
    for p in files:
        for n, line in enumerate(read(p).split("\n"), 1):
            m = DECISION_NO.search(line)
            if m:
                bad.append(f"{rel(p)}:{n} {m.group(0)} {line.strip()[:50]}")
    assert not bad, "決定の番号が本文に出ている：\n    " + "\n    ".join(bad)


# ---------------------------------------------------------------- (5) K3：2つのスクリプトの文面が同じ

def module_literal(path, name):
    tree = ast.parse(read(path))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{rel(path)} に {name} が無い")


def function_node(path, name):
    for node in ast.parse(read(path)).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{rel(path)} に関数 {name} が無い")


def function_strings(path, name):
    """関数の return の式の中の文字列（f 文字列の文字の部分を含む）を、書かれた順に。引数の取り出し方の違いは見ない。"""
    out = []
    for node in ast.walk(function_node(path, name)):
        if isinstance(node, ast.Return) and node.value is not None:
            for sub in ast.walk(node.value):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    out.append(sub.value)
    return out


@case
def t5_display_lines_are_identical_in_both_scripts():
    a = module_literal(SET_DISPLAY, "TYPE_LINE")
    b = module_literal(DASHBOARD, "DISPLAY_LINE")
    assert a == b and set(a) == {"simple", "full"}, f"型の行が違う：\n  set_display：{a}\n  update_dashboard：{b}"
    for typ in ("simple", "full"):
        assert a[typ].startswith("[見せ方：") and a[typ].endswith("]"), f"{typ} の行の形がおかしい：{a[typ]}"
    x = module_literal(SET_DISPLAY, "BROKEN_LINE")
    y = module_literal(DASHBOARD, "DISPLAY_BROKEN_LINE")
    assert x == y, f"壊れたときの行が違う：\n  set_display：{x}\n  update_dashboard：{y}"
    assert x.startswith("[見せ方：") and x.endswith("]")


@case
def t5b_override_line_has_the_same_shape_in_both_scripts():
    # 個別の設定の行：文字列（見出し・区切り・=）と並び（名前の一覧）が同じ
    sa = function_strings(SET_DISPLAY, "overrides_line")
    sb = function_strings(DASHBOARD, "overrides_line")
    assert sa == sb and any(s.startswith("個別の設定（型より優先）：") for s in sa), f"個別の設定の行の文字列が違う：\n  set_display：{sa}\n  update_dashboard：{sb}"
    na = module_literal(SET_DISPLAY, "OVERRIDE_NAMES")
    nb = module_literal(DASHBOARD, "DISPLAY_OVERRIDE_NAMES")
    assert na == nb and len(na) == 6, f"個別の設定の名前・並びが違う：\n  set_display：{na}\n  update_dashboard：{nb}"
    ra, rb = module_literal(SET_DISPLAY, "REQUESTS_RANGE"), module_literal(DASHBOARD, "REQUESTS_MAX_RANGE")
    assert tuple(ra) == tuple(rb), f"requests_max の範囲が違う：{ra} と {rb}"


def load_module(path, tag, home):
    old = {k: os.environ.get(k) for k in ("AI_BUNSHIN_HOME", "CLAUDE_PROJECT_DIR")}
    os.environ["AI_BUNSHIN_HOME"] = home
    os.environ.pop("CLAUDE_PROJECT_DIR", None)
    try:
        spec = importlib.util.spec_from_file_location(tag, path)
        m = importlib.util.module_from_spec(spec)
        sys.modules[tag] = m
        spec.loader.exec_module(m)
        return m
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@case
def t5c_override_line_text_is_the_same_when_called():
    home = tempfile.mkdtemp(prefix="displayskills_")
    try:
        os.makedirs(os.path.join(home, "設定"))
        os.makedirs(os.path.join(home, "00_タスク管理", "data"))
        with open(os.path.join(home, "設定", "config.json"), "w", encoding="utf-8") as f:
            json.dump({"owner": "テスト", "owner_call": "テストさん", "ai_name": "テストAI", "departments": ["総務"]}, f, ensure_ascii=False)
        with open(os.path.join(home, "00_タスク管理", "data", "tasks.json"), "w", encoding="utf-8") as f:
            json.dump({"project": {"name": "テスト", "daily_capacity_default": 8.0, "holidays": []},
                       "daily_sprints": [], "sprints": [], "tasks": []}, f)
        sd = load_module(SET_DISPLAY, "set_display_for_skills_test", home)
        ud = load_module(DASHBOARD, "update_dashboard_for_skills_test", home)
    finally:
        shutil.rmtree(home, ignore_errors=True)
    samples = [{}, {"terms": "full"}, {"requests_max": 7, "terms": "full"},
               {"team_view": "simple", "features": "full", "requests_max": 20, "stop_notice": "full", "review_view": "simple", "terms": "simple"}]
    for ov in samples:
        mine = sd.overrides_line(dict(ov))
        theirs = ud.overrides_line({"overrides": dict(ov)})
        assert mine == theirs, f"{ov}：個別の設定の行が違う\n  set_display：{mine!r}\n  update_dashboard：{theirs!r}"
    for typ in ("simple", "full"):
        assert sd.display_line(typ) == ud.DISPLAY_LINE[typ], f"{typ} の行が違う"
    assert sd.display_line("full", broken=True) == ud.DISPLAY_BROKEN_LINE


print(f"\n失敗 {fails} 件")
sys.exit(1 if fails else 0)
