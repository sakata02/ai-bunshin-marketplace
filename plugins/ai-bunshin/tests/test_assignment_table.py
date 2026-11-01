"""仕事の種類と担当の一覧（T111）のテスト。ルール（rules/commander.md）とスクリプト（scripts/update_dashboard.py）が食い違わない。
- A. 部下の名前：役割分担の表の部下（部下A〜G と subagent_type）が、スクリプトの MEMBER_LABEL と agents/ のファイルに一致する
- B. 振り分けの表：種類ごとの作る人・確かめる人が、スクリプトの ASSIGNMENT と一致する（どちらかを変えると落ちる）
     スクリプトだけが許している作る人（指揮官・部下E・部下A など）は、下の SCRIPT_ONLY_MAKERS に書いたものだけ。増減したら落ちる
- C. 表の崩れ：commander.md のすべての表が Markdown の表として読める（見出し行・区切り行・列の数・前の空行）
- D. 文面：振り分けの回答例は役割名、`! …` に説明がある、確かめる部下（B・D）に作る側向けの「対応表で返す」の行が無い
本物の自分のフォルダは使わない。スクリプトは読み込まず、ast で表だけ取り出す（副作用なし）。
別の場所のファイルで試すときは、環境変数 COMMANDER_PATH・DASH_PATH・AGENTS_DIR で差し替える。
実行：python3 tests/test_assignment_table.py（失敗があれば終了コード1）"""
import ast
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.path.join(HERE, ".."))
COMMANDER_PATH = os.environ.get("COMMANDER_PATH") or os.path.join(PLUGIN, "rules", "commander.md")
DASH_PATH = os.environ.get("DASH_PATH") or os.path.join(PLUGIN, "scripts", "update_dashboard.py")
AGENTS_DIR = os.environ.get("AGENTS_DIR") or os.path.join(PLUGIN, "agents")

# スクリプトだけが許している作る人（ルールの表に無い）。ルールの表に合わせて直すか、表に足すかは、本人が決める（T111 の報告を参照）。
# ここに書いたものと違いが出たら落ちる＝どちらかを変えたときに気づける
SCRIPT_ONLY_MAKERS = {
    "資料": {"指揮官", "design"},
    "調査・分析・設計": set(),
    "開発": {"指揮官", "design"},
    "分析": {"指揮官"},
    "研修": {"buka-a", "指揮官", "design"},
}
NOT_IN_SCRIPT = {"本人"}   # 本人の仕事は assignee が本人のとき、スクリプトが検査しない（表には書く）

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


def read_lines(path):
    with open(path, encoding="utf-8") as f:
        return f.read().split("\n")


def script_value(name):
    """update_dashboard.py の最上位の代入 name = {...} を、実行せずに取り出す。"""
    with open(DASH_PATH, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} がスクリプトに見つからない")


LINES = read_lines(COMMANDER_PATH)


def table_blocks(lines):
    """表の行（先頭が | の行）の連続したまとまり。[(開始行番号(1始まり), [行, ...])]"""
    blocks, cur = [], []
    for i, l in enumerate(lines, 1):
        if l.strip().startswith("|"):
            if not cur:
                cur_start = i
            cur.append(l.strip())
        elif cur:
            blocks.append((cur_start, cur))
            cur = []
    if cur:
        blocks.append((cur_start, cur))
    return blocks


def cells(row):
    return [c.strip() for c in row.strip().strip("|").split("|")]


def is_delimiter(row):
    cs = cells(row)
    return bool(cs) and all(re.fullmatch(r":?-{3,}:?", c) for c in cs)


def table_after(heading_part):
    """見出しの文字列を含む行より後ろで最初の表（行のリスト）。"""
    start = next(i for i, l in enumerate(LINES) if heading_part in l)
    for at, rows in table_blocks(LINES):
        if at > start + 1:
            return rows
    raise AssertionError(f"{heading_part} の後ろに表が無い")


def role_table():
    return table_after("## 役割分担")


def assignment_table():
    return table_after("### 振り分け（誰がやるか）")


def ids(cell):
    return set(re.findall(r"`([^`]+)`", cell))


# ---------- A. 部下の名前 ----------
print("## A. 部下の名前")


@case
def a1_roles_table_members_match_member_label():
    label = script_value("MEMBER_LABEL")   # {"buka-a": "部下A", ...}
    rows = {}
    for r in role_table()[2:]:
        c = cells(r)
        m = re.match(r"(部下[A-Z])（subagent_type `ai-bunshin:([^`]+)`）", c[0])
        if m:
            rows[m.group(2)] = m.group(1)
    assert rows == label, f"役割分担の表 {rows} ／ スクリプト {label}"


@case
def a2_every_member_has_an_agent_file():
    label = script_value("MEMBER_LABEL")
    files = {n[:-3] for n in os.listdir(AGENTS_DIR) if n.endswith(".md")}
    assert set(label) == files, f"スクリプト {sorted(label)} ／ agents/ {sorted(files)}"


@case
def a3_assignment_table_labels_match_member_label():
    label = script_value("MEMBER_LABEL")
    seen = 0
    for r in assignment_table()[2:]:
        for cell in cells(r)[2:]:
            for m in re.finditer(r"`([a-z-]+)`（(部下[A-Z])）", cell):
                seen += 1
                assert label.get(m.group(1)) == m.group(2), f"{m.group(1)} は {label.get(m.group(1))} のはずが {m.group(2)}"
    assert seen >= 6, f"部下の呼び名の付いた箇所が少ない（{seen}）"


# ---------- B. 振り分けの表 ----------
print("## B. 振り分けの表とスクリプト")


def commander_assignment():
    out = {}
    for r in assignment_table()[2:]:
        c = cells(r)
        typ = next(iter(ids(c[0])))
        out[typ] = (ids(c[2]), ids(c[3]))
    return out


@case
def b1_same_types():
    types = set(commander_assignment())
    script = set(script_value("ASSIGNMENT"))
    assert types - NOT_IN_SCRIPT == script, f"ルールの表 {sorted(types)} ／ スクリプト {sorted(script)}"
    assert NOT_IN_SCRIPT <= types, "本人の行が表に無い"


@case
def b2_makers_in_table_are_allowed_by_script():
    table, script = commander_assignment(), script_value("ASSIGNMENT")
    for typ, (mk, _rv) in table.items():
        if typ in NOT_IN_SCRIPT:
            continue
        assert mk <= script[typ][0], f"{typ}：表の作る人 {sorted(mk)} がスクリプトの {sorted(script[typ][0])} に無い"


@case
def b3_reviewers_are_equal():
    table, script = commander_assignment(), script_value("ASSIGNMENT")
    for typ, (_mk, rv) in table.items():
        if typ in NOT_IN_SCRIPT:
            continue
        assert rv == script[typ][1], f"{typ}：表の確かめる人 {sorted(rv)} ／ スクリプト {sorted(script[typ][1])}"


@case
def b4_script_only_makers_are_exactly_the_known_ones():
    table, script = commander_assignment(), script_value("ASSIGNMENT")
    for typ, known in SCRIPT_ONLY_MAKERS.items():
        extra = script[typ][0] - table[typ][0]
        assert extra == known, f"{typ}：スクリプトだけの作る人 {sorted(extra)} ／ 控え {sorted(known)}"
    assert set(SCRIPT_ONLY_MAKERS) == set(script), "控えの種類がスクリプトと違う"


@case
def b5_owner_row_exists_and_has_no_reviewer():
    row = next(cells(r) for r in assignment_table()[2:] if "`本人`" in cells(r)[0])
    assert row[2] == "本人" and row[3] in ("—", "-"), row


# ---------- C. 表の崩れ ----------
print("## C. commander.md の表")


@case
def c1_every_table_has_header_delimiter_and_same_columns():
    blocks = table_blocks(LINES)
    assert len(blocks) >= 6, f"表が少ない（{len(blocks)}）"
    for at, rows in blocks:
        assert len(rows) >= 3, f"{at} 行目：表が見出しと区切りだけ、または行が1つだけ切れている（{len(rows)} 行）"
        assert is_delimiter(rows[1]), f"{at} 行目：2行目が区切り行（|---|）でない（見出しの無い表の続きかもしれない）"
        n = len(cells(rows[0]))
        for k, r in enumerate(rows):
            assert len(cells(r)) == n, f"{at + k} 行目：列の数が {len(cells(r))}（見出しは {n}）"


@case
def c2_a_blank_line_comes_before_every_table():
    """直前が文章の行だと、表として読まれない書き方がある。表の前は空行にする。"""
    for at, rows in table_blocks(LINES):
        before = LINES[at - 2] if at >= 2 else ""
        assert not before.strip(), f"{at} 行目の表の前が空行でない：{before[:30]}"


@case
def c3_no_stray_row_after_a_blank_line_in_the_roles_table():
    """役割分担の表に、本人の行が入っている（空行で切れて表の外に出ていない）。"""
    assert any(r.startswith("| **本人**") for r in role_table()), "本人の行が役割分担の表の外にある"


# ---------- D. 文面 ----------
print("## D. 文面")


def commander_text():
    return "\n".join(LINES)


@case
def d1_assignment_example_uses_role_names():
    t = commander_text()
    assert "開発なので部下C" not in t, "振り分けの回答例が「開発なので部下C」のまま"
    assert "開発の担当（部下C）" in t, "振り分けの回答例に「開発の担当（部下C）」が無い"


@case
def d2_bang_commands_are_explained():
    t = commander_text()
    for m in re.finditer(r"`! …`", t):
        near = t[m.start():m.start() + 120]
        assert "入力欄" in near, f"`! …` の近くに説明が無い：{near[:50]}"
    assert t.count("`! …`") >= 2


@case
def d3_reviewer_agents_do_not_have_the_makers_reply_table_line():
    for name in ("buka-b", "dev-b"):
        t = open(os.path.join(AGENTS_DIR, name + ".md"), encoding="utf-8").read()
        assert "確かめる人の指摘には" not in t, f"{name}.md に作る側向けの「確かめる人の指摘には…対応表で返す」が残っている"
        assert "修正の対応表が指摘と1対1か" in t, f"{name}.md から確かめる側の行が消えている"


@case
def d4_makers_keep_the_reply_table_line():
    for name in ("buka-a", "dev-a"):
        t = open(os.path.join(AGENTS_DIR, name + ".md"), encoding="utf-8").read()
        assert "確かめる人の指摘には" in t, f"{name}.md から「対応表で返す」が消えている"


print(f"\n失敗 {fails} 件")
sys.exit(1 if fails else 0)
