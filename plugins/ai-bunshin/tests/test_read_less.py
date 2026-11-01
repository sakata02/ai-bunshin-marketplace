"""読む量を絞る（T102）のテスト。
- update_dashboard.py --task T0XX [T0YY ...]：指定のタスクだけを JSON で出す。何も書かない（更新時刻・ファイルの一覧が実行の前後で同じ。
  schema_version の書き戻しも起こさない）。無い ID は知らせて終了コード 1。自動実行で許可されているコマンドの形に合う
- スキルが指す節の名前が、雛形（改善ログの雛形・振り返りの議事録の雛形）に実在する
- 改善ログの月ごとの保管の手順がある／Agent ID を do_log から探す手順が壊れていない
本物の自分のフォルダは使わない（一時フォルダ。AI_BUNSHIN_HOME で指定）。
実行：python3 tests/test_read_less.py（失敗があれば終了コード1）"""
import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.path.join(HERE, ".."))
DASH = os.path.join(PLUGIN, "scripts", "update_dashboard.py")
CYCLE = os.path.join(PLUGIN, "scripts", "auto", "daily_cycle.sh")
SKILLS = os.path.join(PLUGIN, "skills")
BASE = os.path.realpath(tempfile.mkdtemp(prefix="readless_"))
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


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


TASKS = {"project": {"name": "テストAI", "daily_capacity_default": 8.0, "holidays": []},
         "daily_sprints": [], "sprints": [],
         "tasks": [{"id": "T001", "title": "一つ目", "status": "ToDo", "assignee": "dev-a", "type": "開発",
                    "reviewer": "dev-b", "points": 2, "department": "総務", "priority": 1},
                   {"id": "T002", "title": "二つ目", "status": "完了", "assignee": "buka-a", "type": "資料",
                    "reviewer": "buka-b", "points": 1, "department": "総務", "priority": 2, "done_date": "2026-11-01"},
                   {"id": "T003", "title": "三つ目", "status": "Backlog", "assignee": "指揮官", "type": "調査・分析・設計",
                    "reviewer": "buka-b", "points": 3, "department": "総務", "priority": 3}]}


def make_owner(name):
    root = os.path.join(BASE, name)
    for d in ("設定", os.path.join("00_タスク管理", "data"), "04_ナレッジ", os.path.join("01_スプリント", "S001_20261101", "daily")):
        os.makedirs(os.path.join(root, d))
    with open(os.path.join(root, "設定", "config.json"), "w", encoding="utf-8") as f:
        json.dump({"owner": "テスト", "owner_call": "テストさん", "ai_name": "テストAI", "departments": ["総務"]}, f, ensure_ascii=False)
    with open(os.path.join(root, "00_タスク管理", "data", "tasks.json"), "w", encoding="utf-8") as f:
        json.dump(TASKS, f, ensure_ascii=False, indent=2)   # schema_version なし＝通常の起動なら書き戻しが起きる形
    for name_, body in (("04_ナレッジ/改善ログ.md", "# 改善ログ\n\n## 実施中の Try\n\n- （なし）\n"),
                        ("01_スプリント/S001_20261101/do_log.md", "# S001 Do ログ\n"),
                        ("00_タスク管理/data/history.jsonl", "")):
        with open(os.path.join(root, *name_.split("/")), "w", encoding="utf-8") as f:
            f.write(body)
    return root


def listing(root):
    """全ファイル・フォルダの (相対パス, 更新時刻ns, サイズ)。"""
    out = []
    for d, dirs, files in os.walk(root):
        for n in dirs + files:
            p = os.path.join(d, n)
            st = os.stat(p)
            out.append((os.path.relpath(p, root), st.st_mtime_ns, st.st_size))
    return sorted(out)


def run_task(root, *ids, extra_env=None):
    env = dict(os.environ, AI_BUNSHIN_HOME=root, HOME=os.path.join(BASE, "home"))
    env.pop("CLAUDE_PROJECT_DIR", None)
    env.update(extra_env or {})
    return subprocess.run([sys.executable, DASH, "--task", *ids], cwd=root, env=env, capture_output=True, text=True, timeout=60)


@case
def task_prints_only_requested_in_order():
    root = make_owner("a")
    r = run_task(root, "T003", "T001")
    assert r.returncode == 0, (r.returncode, r.stderr)
    data = json.loads(r.stdout)
    assert [t["id"] for t in data] == ["T003", "T001"], [t.get("id") for t in data]
    assert data[1]["title"] == "一つ目" and data[1]["points"] == 2, data[1]


@case
def task_writes_nothing():
    root = make_owner("b")
    before = listing(root)
    r = run_task(root, "T001", "T002")
    assert r.returncode == 0, r.stderr
    after = listing(root)
    assert before == after, f"変わったもの：{sorted(set(after) ^ set(before))}"
    tj = json.load(open(os.path.join(root, "00_タスク管理", "data", "tasks.json"), encoding="utf-8"))
    assert "schema_version" not in tj, "schema_version が書き戻された"


@case
def task_writes_nothing_even_when_missing_id():
    root = make_owner("c")
    before = listing(root)
    run_task(root, "T001", "T999")
    assert before == listing(root)


@case
def task_missing_id_exit_1_and_says_which():
    root = make_owner("d")
    r = run_task(root, "T001", "T999")
    assert r.returncode == 1, r.returncode
    assert "T999" in r.stderr and "ありません" in r.stderr, r.stderr
    assert [t["id"] for t in json.loads(r.stdout)] == ["T001"], r.stdout   # あるぶんは出す
    r2 = run_task(root, "T998", "T999")
    assert r2.returncode == 1 and "T998" in r2.stderr and "T999" in r2.stderr, (r2.returncode, r2.stderr)
    assert json.loads(r2.stdout) == [], r2.stdout


@case
def task_without_ids_is_an_error_and_writes_nothing():
    root = make_owner("e")
    before = listing(root)
    r = run_task(root)
    assert r.returncode != 0, "ID なしで成功した"
    assert before == listing(root)


@case
def task_outside_owner_folder_fails():
    empty = os.path.join(BASE, "nowhere")
    os.makedirs(empty)
    env = dict(os.environ, HOME=os.path.join(BASE, "home"))
    env.pop("AI_BUNSHIN_HOME", None)
    env.pop("CLAUDE_PROJECT_DIR", None)
    r = subprocess.run([sys.executable, DASH, "--task", "T001"], cwd=empty, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 1, r.returncode
    assert os.listdir(empty) == [], os.listdir(empty)


@case
def task_command_matches_auto_run_allowlist():
    """自動実行（daily_cycle.sh の --allowedTools）で許可されている形で、--task が動くこと。"""
    sh = read(CYCLE)
    pats = re.findall(r"Bash\((python3 [^)]*?update_dashboard\.py[^)]*)\)", sh)
    assert pats, "daily_cycle.sh に update_dashboard.py の許可が見つからない"
    cmd = f'python3 "{DASH}" --task T001 T002'
    star = [p for p in pats if p.startswith("python3 *update_dashboard.py*")]
    assert star and fnmatch.fnmatchcase(cmd, star[0]), (pats, cmd)
    # 許可のコマンドそのままの形でも動く
    root = make_owner("f")
    env = dict(os.environ, AI_BUNSHIN_HOME=root, HOME=os.path.join(BASE, "home"))
    r = subprocess.run(cmd, shell=True, cwd=root, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and [t["id"] for t in json.loads(r.stdout)] == ["T001", "T002"], (r.returncode, r.stderr)


def headings(text):
    return [l[3:].strip() for l in text.splitlines() if l.startswith("## ")]


def review_template_headings():
    """daily-review の議事録の雛形（```で囲んだ部分）の見出し。"""
    body = read(SKILLS, "daily-review", "SKILL.md")
    m = re.search(r"## 8\. 議事録.*?```\n(.*?)\n```", body, re.S)
    assert m, "議事録の雛形が見つからない"
    return headings(m.group(1))


def has_heading(hs, name):
    return any(h.startswith(name) for h in hs)


@case
def sections_named_in_skills_exist_in_templates():
    review_hs = review_template_headings()
    log_hs = headings(read(PLUGIN, "templates", "knowledge", "improvement_log.md"))
    plan = read(SKILLS, "daily-plan", "SKILL.md")
    sprint = read(SKILLS, "sprint", "SKILL.md")
    for name in ("明日の Try", "明日の要件確認"):
        assert has_heading(review_hs, name), f"振り返りの雛形に「## {name}」が無い：{review_hs}"
        assert f"## {name}" in plan, f"daily-plan が「## {name}」を指していない"
    for name in ("実施中の Try", "定着したルール", "やめた Try"):
        assert has_heading(log_hs, name), f"改善ログの雛形に「## {name}」が無い：{log_hs}"
    assert "## 実施中の Try" in sprint and "## 実施中の Try" in plan
    # 計画が頼る「3行まとめ」「本人へのお願い」も雛形にある（plan-context の要約の元）
    assert has_heading(review_hs, "3行まとめ")


@case
def sprint_and_review_keep_whole_log_where_needed():
    """やめた Try・定着したルールを見る場面（sprint の Try を決める所・daily-review の材料）は、全体を読めるままにする。"""
    sprint = read(SKILLS, "sprint", "SKILL.md")
    review = read(SKILLS, "daily-review", "SKILL.md")
    line16 = [l for l in sprint.splitlines() if "判断基準.md" in l and "部署一覧.md" in l][0]
    assert "改善ログ.md" in line16 and "`## 実施中の Try`" in line16 and "部分だけ" in line16, line16
    line61 = [l for l in sprint.splitlines() if "過去の改善ログに照らして" in l][0]
    assert "改善ログ" in line61 and "全体" in line61, line61
    line39 = [l for l in review.splitlines() if l.startswith("- `04_ナレッジ/改善ログ.md`")][0]
    assert "全体" in line39 and "やめた Try" in line39, line39


@case
def do_log_readers_say_today_only_and_agent_id_search_stays():
    review = read(SKILLS, "daily-review", "SKILL.md")
    assert "do_log.md` の今日の記録" in review
    for skill in ("daily-do", "sprint", "daily-review"):
        body = read(SKILLS, skill, "SKILL.md")
        assert "Agent ID" in body, f"{skill} から Agent ID の手順が消えた"
        assert "Grep" in body and "全体" in body, f"{skill} に do_log を全体で開かず Grep で探す案内が無い"


@case
def task_option_is_announced_in_skills():
    n = sum("update_dashboard.py\" --task" in read(SKILLS, s, "SKILL.md") for s in os.listdir(SKILLS))
    assert n >= 1, "スキルに --task の案内が無い"


@case
def archive_step_in_daily_review():
    review = read(SKILLS, "daily-review", "SKILL.md")
    for word in ("改善ログ_保管/YYYYMM.md", "「実施中の Try」は移さない", "消さない", "コミット"):
        assert word in review, f"保管の手順に「{word}」が無い"
    sec = review.split("改善ログの月ごとの保管（")[1].split("## 8. 議事録")[0]
    for word in ("自動実行", "Git", "ルール履歴", "移さない", "前の月より前", "1行書く"):
        assert word in sec, f"保管の手順に「{word}」が無い"


# --- 本物の do_log に近い形（T102 の直し）：日付の箇条書き・字下げの続き・前日の見出しの節 ---
REAL_LOG = """# S001 Do ログ

## 2026-10-31 夕方（会話）

### T074 文書の分
- 受け取り：OK。2026-10-31 の記録は見出しの節にある
- 部下C の報告は20行以内

## 運用メモ（日付の見出しではない節）

- 2026-10-31 14:53 一旦やめた
  - 再開するときの状態：T058 は作業中

- 2026-11-01 T101 部下C 56e9c0d → 部下D 1回目 合格
  - 続き：PO 判断で直す点は3つ
  - 続きの続き：テスト9本
- 2026-11-01 Agent ID: a1b2c3（T102・部下C）
- 2026-11-01 Agent ID: d4e5f6（T102・部下D）
- 2026-11-01 山田さん：T102 を beta.5 に入れる
"""


def grep_today(text, date):
    """スキルの指定を機械で再現：日付を含む行（Grep -n）＋続きの字下げの行。日付の見出しの節があればその節も。
    見つからないときは全体を返す。"""
    lines = text.splitlines()
    picked = set()
    for i, l in enumerate(lines):
        if date in l:
            picked.add(i)
            if l.startswith("#"):                         # 見出しなら、次の同じ階層以上の見出しまでが節
                lv = len(l) - len(l.lstrip("#"))
                for j in range(i + 1, len(lines)):
                    m = re.match(r"(#+) ", lines[j])
                    if m and len(m.group(1)) <= lv:
                        break
                    picked.add(j)
            else:                                          # 続きの字下げの行
                for j in range(i + 1, len(lines)):
                    if lines[j].startswith((" ", "\t")):
                        picked.add(j)
                    else:
                        break
    if not picked:
        return text
    return "\n".join(lines[i] for i in sorted(picked))


def agent_id_for(text, task, who):
    """「Agent ID:」を含む行を Grep して、T 番号と担当で選ぶ。無ければ None（＝新しく呼ぶ）。"""
    hits = [l for l in text.splitlines() if "Agent ID:" in l]
    ids = [re.search(r"Agent ID: (\S+)（", l).group(1) for l in hits if task in l and who in l]
    return ids[-1] if ids else None


@case
def todays_grep_takes_today_lines_and_continuations_not_yesterdays_section():
    out = grep_today(REAL_LOG, "2026-11-01")
    assert "T101 部下C 56e9c0d" in out and "続きの続き：テスト9本" in out, out
    assert "山田さん：T102 を beta.5" in out
    assert "2026-10-31" not in out and "再開するときの状態" not in out and "T074 文書の分" not in out, out
    # 日付の見出しの節がある日は、その節も読む
    sec = grep_today(REAL_LOG, "2026-10-31 夕方")
    assert "T074 文書の分" in sec and "受け取り：OK" in sec and "T101 部下C" not in sec, sec
    # 見つからないときは全体（読めないままにしない）
    assert grep_today(REAL_LOG, "2026-12-25") == REAL_LOG


@case
def agent_id_found_by_format_and_task_and_who():
    assert agent_id_for(REAL_LOG, "T102", "部下C") == "a1b2c3"
    assert agent_id_for(REAL_LOG, "T102", "部下D") == "d4e5f6"
    assert agent_id_for(REAL_LOG, "T999", "部下C") is None          # 見つからなければ新しく呼ぶ
    # 実物の書き方（Agent ID の文字列が無い）では見つからず、新しく呼ぶ側に倒れる
    assert agent_id_for("- 2026-11-01 T101 部下C 56e9c0d → 部下D 合格\n", "T101", "部下C") is None


@case
def skills_spell_out_the_grep_and_the_line_format():
    review = read(SKILLS, "daily-review", "SKILL.md")
    l37 = [l for l in review.splitlines() if "do_log.md` の今日の記録" in l][0]
    for w in ("YYYY-MM-DD", "Grep -n", "字下げ", "見出しの部分", "見つからないとき", "全体を読む"):
        assert w in l37, f"daily-review の今日の分の読み方に「{w}」が無い"
    for skill in ("daily-do", "sprint"):
        body = read(SKILLS, skill, "SKILL.md")
        assert "`- YYYY-MM-DD …`" in body, f"{skill} に記録の行の書き出しが無い"
        assert "古い記録は直さない" in body, f"{skill} に「古い記録は直さない」が無い"
    for skill in ("daily-do", "sprint", "daily-review"):
        body = read(SKILLS, skill, "SKILL.md")
        assert "Agent ID: <id>（T0XX・部下C）" in body, f"{skill} に Agent ID の書式が無い"
        assert "`Agent ID:` を含む行" in body and "新しく呼ぶ" in body, f"{skill} に Agent ID を探す手順が無い"


@case
def archive_step_is_safe_to_redo_and_checks_git_toplevel():
    review = read(SKILLS, "daily-review", "SKILL.md")
    sec = review.split("改善ログの月ごとの保管（")[1].split("## 8. 議事録")[0]
    for w in ("同じ ID の行", "足さない", "git rev-parse --show-toplevel", "一致しない",
              "Git で記録していない環境", "コミットするものが無い", "成功として扱う",
              "金曜", "改善ログの保管（次の会話で「改善ログを保管して」と言う）", "毎日は出さない",
              "「改善ログを保管して」と言われたら"):
        assert w in sec, f"保管の手順に「{w}」が無い"


print(f"{'FAILED: ' + str(fails) if fails else 'ALL OK'}")
sys.exit(1 if fails else 0)
