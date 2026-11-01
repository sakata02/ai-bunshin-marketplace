"""共通ルール（rules/commander.md）の分割（T101）のテスト。破られ方の6つ＋文面の突き合わせ。
- A. 突き合わせ：古い commander.md（コミット 8101a02 の版）の空行以外の全行が、本体か rules/details/ のどちらかに完全一致で残っている
     （破られ方4：節を移すときに文が欠ける）。新しく書いた行は案内・表だけ。安全に関わる節は本体に残る
- B. 写し：古い本人フォルダ（details なし）から更新すると本体と details が同時に写る（破られ方1）。
     .claude/rules/ の外に写す。写せないときは起動時に知らせる。元に無くなった写しは消さない
- C. 自動実行：daily_cycle.sh の起動前の写しでも details が写る（破られ方2）
- D. 見張り：写し（.claude/ai-bunshin-details/）への書き込みを止める。読むだけは通す（破られ方3）
- E. 参照：スキル・部下・雛形・スクリプトの中の「指揮官ルールの「○○」」が消えた節を指したままになっていない。
     スキルの該当手順に「先に .claude/ai-bunshin-details/x.md を読む」がある（破られ方5）
- F. 読まずに tasks.json を手で直したとき、スクリプトの検証で止まる項目と止まらない項目の一覧（破られ方6）
本物の自分のフォルダは使わない（すべて一時フォルダ・HOME も一時）。
実行：python3 tests/test_rules_split.py（失敗があれば終了コード1）"""
import copy
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.path.join(HERE, ".."))
SCRIPTS = os.path.join(PLUGIN, "scripts")
DASH = os.path.join(SCRIPTS, "update_dashboard.py")
GUARD = os.path.join(SCRIPTS, "ng_guard.py")
CYCLE = os.path.join(SCRIPTS, "auto", "daily_cycle.sh")
BODY_PATH = os.path.join(PLUGIN, "rules", "commander.md")
DETAILS_SRC = os.path.join(PLUGIN, "rules", "details")
OLD_COMMIT = "8101a02"   # 分割前の commander.md（beta.4）
DETAIL_NAMES = ["tasks-json", "retro-try", "kaizen", "daily-sprint", "models", "team-growth", "calendar", "writing-style", "dev"]
DETAILS_REL = os.path.join(".claude", "ai-bunshin-details")
# 本体の「本体に残すもの」のうち、古い版に無い短い案内（指示書で認められた新しい文。ほかに新しい文は書かない）
NEW_STUB_SENTENCES = {
    "- Opus に上げる・部下を呼ぶモデルを決めるときは、先に読む",
    "- iCal の非公開 URL はチャットに貼らせない（キーチェーンなどに入れる）",
    "- 本人名義の文章（記事・コラムなど）を書く前に読む",
    "- tasks.json を手で書き換える前に読む（項目のルールとポイントの基準）",
    "| `.claude/ai-bunshin-details/` | 共通ルールの詳しい手順の自動コピー（直接編集しない） |",
    # T095：長引いたら様子を見る（会話の中で必ず守る短い手順。長い説明はスキルの sprint・dev・daily-do）
    "- **部下を出したら目安の時間を決める**：作る＝1pt 15分・2pt 25分・3pt 40分・5pt 60分、確かめる＝その半分、Opus に上げたら1.5倍（暫定）。指示書の頭と do_log（`- YYYY-MM-DD T0XX 開始 HH:MM／目安 N分／見る時刻 HH:MM`）に書く。部下は部下を呼ばない（指示書の「守ること」に書く）",
    "- **長引いたら様子を見る**（会話の中）：部下を出した応答で、作業のフォルダの更新が15分止まったら終わる背景の Bash を1つだけ出す（自動実行では出さない）。起こされたら git の状態・作業のフォルダの更新時刻・ng_log の最後の行を見て、進みがあれば本人に1行伝えて出し直す。無ければ部下に「今どこ？止まってない？」と聞き、目安の1/4（最短5分）待って進みが無ければ止めて（TaskStop）範囲を切り直す。同じ失敗が2回続いたら3周目に入らない。手順は `/ai-bunshin:sprint` の「部下を出したら」",
    "- **見張りが壊れて Bash が全部止まったら**：指揮官は Read しか使えない。直している部下に元の版へ戻させ、戻せなければ本人に `! …` の1行を頼む（戻しのコマンドは直す前に用意する）。止めた部下の変更を戻すときも、本人に1行で頼む",
}
TAIL_HEADING = "## 詳しい手順のファイル（必要なときに読む）"

BASE = os.path.realpath(tempfile.mkdtemp(prefix="rulessplit_"))
FAKE_HOME = os.path.join(BASE, "home")
os.makedirs(FAKE_HOME)
fails = 0
SKIPS = 0


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


def old_text():
    """分割前の commander.md。git から読む（.git が無い環境では None）。"""
    r = subprocess.run(["git", "show", f"{OLD_COMMIT}:./rules/commander.md"], capture_output=True, text=True, cwd=PLUGIN)
    return r.stdout if r.returncode == 0 and r.stdout else None


OLD = old_text()
OLD_LINES = OLD.split("\n") if OLD else []
BODY = read(BODY_PATH)
BODY_LINES = BODY.split("\n")


def details_files():
    return sorted(n for n in os.listdir(DETAILS_SRC)) if os.path.isdir(DETAILS_SRC) else []


def details_text(name):
    return read(os.path.join(DETAILS_SRC, name + ".md"))


def need_old():
    global SKIPS
    if not OLD:
        SKIPS += 1
        print(f"  SKIP （git で {OLD_COMMIT} の版が読めない）")
        return False
    return True


# ---------- A. 突き合わせ ----------
print("## A. 文面の突き合わせ")


@case
def a1_nine_detail_files_with_the_given_names():
    assert details_files() == sorted(n + ".md" for n in DETAIL_NAMES), details_files()


@case
def a2_every_old_nonblank_line_is_kept_exactly():
    if not need_old():
        return
    kept = set(BODY_LINES)
    for n in DETAIL_NAMES:
        kept |= set(details_text(n).split("\n"))
    lost = [l for l in OLD_LINES if l.strip() and l not in kept]
    print(f"       差分 {len(lost)} 行（古い版の空行以外 {sum(1 for l in OLD_LINES if l.strip())} 行中）")
    assert not lost, "欠けた行：" + " / ".join(l[:50] for l in lost[:5])


@case
def a3_each_details_file_is_a_contiguous_block_of_the_old_text():
    if not need_old():
        return
    for n in DETAIL_NAMES:
        block = details_text(n).rstrip("\n").split("\n")
        found = any(OLD_LINES[i:i + len(block)] == block for i in range(len(OLD_LINES) - len(block) + 1))
        assert found, f"{n}.md が古い版の連続した範囲と一致しない"


@case
def a4_details_files_have_no_new_lines():
    if not need_old():
        return
    old = set(OLD_LINES)
    for n in DETAIL_NAMES:
        new = [l for l in details_text(n).split("\n") if l.strip() and l not in old]
        assert not new, f"{n}.md に新しい行：{new[:2]}"


@case
def a5_new_lines_in_body_are_only_pointers_and_the_tail_table():
    """本体に新しく書いた行は、(1) 本体に残すもの＋details への案内（パスを含む）、(2) 末尾の表と3つの説明、だけ。"""
    if not need_old():
        return
    old = set(OLD_LINES)
    tail_at = BODY_LINES.index(TAIL_HEADING) if TAIL_HEADING in BODY_LINES else None
    assert tail_at is not None, "末尾の「読むファイル」の節が無い"
    new = [(i, l) for i, l in enumerate(BODY_LINES) if l.strip() and l not in old]
    bad = [l for i, l in new if i < tail_at and "ai-bunshin-details/" not in l and l not in NEW_STUB_SENTENCES]
    print(f"       本体の新しい行：{len(new)} 行（うち末尾の節 {sum(1 for i, _ in new if i >= tail_at)} 行）")
    assert not bad, f"案内でも末尾の節でもない新しい行：{bad[:3]}"
    # 末尾の節の説明は、指示書にある3つ（1回・迷ったら読む・部下は読まない）だけ
    tail = [l for l in BODY_LINES[tail_at + 1:] if l.strip() and not l.startswith("|")]
    bullets = [l for l in tail if l.startswith("- ")]
    assert len(bullets) == 3, bullets
    for key in ("1つの会話で1回", "迷ったら読む", "部下は読まない"):
        assert any(key in b for b in bullets), key


@case
def a6_safety_lines_stay_in_the_body():
    if not need_old():
        return

    def old_line(prefix):
        hits = [l for l in OLD_LINES if l.lstrip().startswith(prefix)]
        assert hits, f"古い版に無い：{prefix}"
        return hits[0]
    for prefix in ("- セッション開始時に hook が出す「実施中の Try」", "- **ルールやプロンプトの変更は本人の承認制**",
                   "- Claude Code が読み込んでいるプラグインのコピー", "- NG の見張りは Edit・Write と Bash の書き込み",
                   "- **増やすのは本人の承認があったときだけ**", "- **必ず本人に確認すること**"):
        assert old_line(prefix) in BODY_LINES, f"本体に無い：{prefix}"
    # NG の節と判断のルール・本人へのお願いは丸ごと本体
    start = OLD_LINES.index("## やってはいけないこと（NG）")
    end = OLD_LINES.index("## 開発（スクリプト・ツール・Web アプリ・既存システムの改修）")
    missing = [l for l in OLD_LINES[start:end] if l.strip() and l not in BODY_LINES]
    assert not missing, missing[:2]


@case
def a7_body_is_smaller():
    size = len(BODY.encode("utf-8"))
    total = sum(len(details_text(n).encode("utf-8")) for n in DETAIL_NAMES)
    print(f"       本体 {size} バイト／details 合計 {total} バイト／分割前 {len(OLD.encode('utf-8')) if OLD else '?'} バイト")
    assert size < 32000, size


@case
def a8_tail_table_lists_every_file():
    tail = "\n".join(BODY_LINES[BODY_LINES.index(TAIL_HEADING):]) if TAIL_HEADING in BODY_LINES else ""
    for n in DETAIL_NAMES:
        assert f".claude/ai-bunshin-details/{n}.md" in tail, f"{n}.md が末尾の表に無い"
    assert "${CLAUDE_PLUGIN_ROOT}" not in tail, "写しの中では展開されない"


# ---------- B. 写し（破られ方1） ----------
print("## B. 本人のフォルダへの写し")
TASKS = {"project": {"name": "テストAI", "daily_capacity_default": 8.0, "holidays": []}, "daily_sprints": [], "sprints": [],
         "tasks": [{"id": "T001", "title": "テスト用タスク", "status": "ToDo", "assignee": "dev-a", "type": "開発",
                    "reviewer": "dev-b", "points": 2, "department": "総務", "priority": 1}]}
_n = [0]


def make_owner(holidays=(), tasks=None):
    _n[0] += 1
    root = os.path.join(BASE, f"owner{_n[0]}")
    os.makedirs(os.path.join(root, "設定"))
    os.makedirs(os.path.join(root, "00_タスク管理", "data"))
    json.dump({"owner": "テスト", "owner_call": "テストさん", "ai_name": "テストAI", "departments": ["総務"]},
              open(os.path.join(root, "設定", "config.json"), "w", encoding="utf-8"), ensure_ascii=False)
    t = copy.deepcopy(tasks if tasks is not None else TASKS)
    t["project"]["holidays"] = list(holidays)
    json.dump(t, open(os.path.join(root, "00_タスク管理", "data", "tasks.json"), "w", encoding="utf-8"), ensure_ascii=False)
    return root


def env_for(root, extra=None):
    env = {k: v for k, v in os.environ.items() if k not in ("AI_BUNSHIN_HOME", "CLAUDE_PROJECT_DIR")}
    env["HOME"] = FAKE_HOME
    env["CLAUDE_PROJECT_DIR"] = root
    env.update(extra or {})
    return env


def session(root):
    r = subprocess.run([sys.executable, DASH, "--session"], capture_output=True, text=True, cwd=root, env=env_for(root))
    try:
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    except (ValueError, KeyError):
        ctx = ""
    return r, ctx


def rules_copy(root):
    return os.path.join(root, ".claude", "rules", "ai-bunshin-common.md")


def details_dir(root):
    return os.path.join(root, DETAILS_REL)


def old_style_owner():
    """更新前の本人フォルダ：古い（全部入りの）写しだけがあり、details が無い。"""
    root = make_owner()
    os.makedirs(os.path.dirname(rules_copy(root)))
    open(rules_copy(root), "w", encoding="utf-8").write("<!-- 自動コピー：古い版 -->\n\n" + (OLD or "古い版の本文\n"))
    return root


@case
def b1_update_from_old_folder_writes_body_and_details_together():
    root = old_style_owner()
    assert not os.path.exists(details_dir(root))
    r, ctx = session(root)
    assert r.returncode == 0, r.stderr
    assert "共通ルールが更新されました" in ctx, ctx[:200]
    copy_text = read(rules_copy(root))
    assert copy_text.endswith(BODY) and copy_text.startswith("<!-- 自動コピー："), "本体が新しくなっていない"
    assert sorted(os.listdir(details_dir(root))) == sorted(n + ".md" for n in DETAIL_NAMES), os.listdir(details_dir(root))
    for n in DETAIL_NAMES:
        t = read(os.path.join(details_dir(root), n + ".md"))
        assert t.startswith("<!-- 自動コピー：") and t.endswith(details_text(n)), f"{n}.md の中身が元と違う"


@case
def b2_details_are_outside_dot_claude_rules():
    root = old_style_owner()
    session(root)
    rules_dir = os.path.dirname(rules_copy(root))
    assert os.listdir(rules_dir) == ["ai-bunshin-common.md"], os.listdir(rules_dir)   # .claude/rules/ の下に置くと自動で読み込まれてしまう
    assert details_dir(root).startswith(os.path.join(root, ".claude")) and not details_dir(root).startswith(rules_dir)


@case
def b3_second_start_does_not_announce_an_update():
    root = old_style_owner()
    session(root)
    r, ctx = session(root)
    assert "共通ルールが更新されました" not in ctx and "詳細ファイル" not in ctx, ctx[:200]


@case
def b4_a_changed_details_copy_is_restored_and_announced():
    root = old_style_owner()
    session(root)
    p = os.path.join(details_dir(root), "models.md")
    open(p, "a", encoding="utf-8").write("\n勝手な追記\n")
    r, ctx = session(root)
    assert read(p).endswith(details_text("models")), "写しが元に戻っていない"
    assert "共通ルールが更新されました" in ctx, "details だけが変わったときも知らせる"


@case
def b5_missing_one_details_file_is_written_again():
    root = old_style_owner()
    session(root)
    os.remove(os.path.join(details_dir(root), "kaizen.md"))
    session(root)
    assert os.path.exists(os.path.join(details_dir(root), "kaizen.md"))


@case
def b6_files_that_no_longer_exist_in_the_source_are_left_alone():
    """元に無くなったファイルは消さない（削除は本人。本体の「読むファイル」の表にないので、読まれない）。"""
    root = old_style_owner()
    session(root)
    stale = os.path.join(details_dir(root), "removed-in-later-version.md")
    open(stale, "w", encoding="utf-8").write("古い手順\n")
    r, ctx = session(root)
    assert os.path.exists(stale) and read(stale) == "古い手順\n", "消えた・書き換わった"
    assert "共通ルールが更新されました" not in ctx and "詳細ファイル" not in ctx, ctx[:200]


@case
def b7_failure_to_write_details_is_announced_and_old_body_is_kept():
    root = old_style_owner()
    open(details_dir(root), "w").write("ディレクトリではない（写せない状態を作る）")
    before = read(rules_copy(root))
    r, ctx = session(root)
    assert r.returncode == 0, r.stderr
    assert ctx.startswith("[共通ルールの詳細ファイルを写せませんでした]"), ctx[:200]   # 先頭（hook の出力は約2KBで切れる）
    assert ".claude/ai-bunshin-details/" in ctx.splitlines()[0]
    assert read(rules_copy(root)) == before, "詳細が無いのに、詳細を指す新しい本体だけが写った"


@case
def b8_failure_with_no_previous_copy_still_writes_body_and_announces():
    root = make_owner()
    os.makedirs(os.path.join(root, ".claude"))
    open(details_dir(root), "w").write("x")
    r, ctx = session(root)
    assert os.path.exists(rules_copy(root)) and read(rules_copy(root)).endswith(BODY), "本体まで無くなってはいけない"
    assert ctx.startswith("[共通ルールの詳細ファイルを写せませんでした]"), ctx[:200]


@case
def b9_details_source_missing_is_announced():
    """プラグインの元に details が無い（壊れた配布）。本体だけ写して終わらず、知らせる。"""
    root = make_owner()
    plugin2 = os.path.join(BASE, "plugin_nodetails")
    shutil.copytree(PLUGIN, plugin2, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    shutil.rmtree(os.path.join(plugin2, "rules", "details"))
    r = subprocess.run([sys.executable, os.path.join(plugin2, "scripts", "update_dashboard.py"), "--session"],
                       capture_output=True, text=True, cwd=root, env=env_for(root))
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert ctx.startswith("[共通ルールの詳細ファイルを写せませんでした]"), ctx[:200]


# ---------- C. 自動実行（破られ方2） ----------
print("## C. 自動実行の起動前の写し")


@case
def c1_daily_cycle_syncs_through_the_same_function_before_claude():
    sh = read(CYCLE)
    i_sync = sh.index('"$DASH" --session')
    claude_calls = [m.start() for m in re.finditer(r"^\s*(?:\S+=\S+\s+)*claude\b|\bclaude\s+-p\b|\bclaude\s+--", sh, re.M)]
    assert claude_calls and i_sync < min(claude_calls), "起動前の写しが claude より後"
    assert "sync_rules" not in sh, "別の関数で写してはいけない（--session が sync_rules を通る）"


@case
def c2_daily_cycle_run_writes_details_even_when_it_skips():
    if not shutil.which("zsh"):
        print("       SKIP（zsh なし）")
        return
    today = datetime.date.today().isoformat()
    root = old_style_owner()
    # 今日を祝日にして、claude を呼ばずに「営業日ではない」で終わらせる（写しは claude を起動する前に済んでいる）
    t = json.load(open(os.path.join(root, "00_タスク管理", "data", "tasks.json"), encoding="utf-8"))
    t["project"]["holidays"] = [today]
    json.dump(t, open(os.path.join(root, "00_タスク管理", "data", "tasks.json"), "w", encoding="utf-8"), ensure_ascii=False)
    fakebin = os.path.join(BASE, "fakebin_claude")
    os.makedirs(fakebin, exist_ok=True)
    with open(os.path.join(fakebin, "claude"), "w") as f:
        f.write("#!/bin/sh\necho CLAUDE_WAS_CALLED >> \"$AI_BUNSHIN_HOME/claude_called.txt\"\nexit 1\n")
    os.chmod(os.path.join(fakebin, "claude"), 0o755)
    env = env_for(root, {"AI_BUNSHIN_HOME": root, "PATH": fakebin + os.pathsep + os.environ.get("PATH", "")})
    r = subprocess.run(["zsh", CYCLE, "plan"], capture_output=True, text=True, cwd=root, env=env, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not os.path.exists(os.path.join(root, "claude_called.txt")), "claude が呼ばれた（前提が崩れている）"
    assert sorted(os.listdir(details_dir(root))) == sorted(n + ".md" for n in DETAIL_NAMES), "自動実行の起動前の写しで details が写っていない"
    assert read(rules_copy(root)).endswith(BODY)


# ---------- D. 見張り（破られ方3） ----------
print("## D. 写しへの書き込みを止める")
GUARD_HOME = os.path.join(BASE, "guardhome")
os.makedirs(GUARD_HOME)
GROOT = make_owner()
os.makedirs(details_dir(GROOT))
open(os.path.join(details_dir(GROOT), "models.md"), "w").write("x")
os.makedirs(os.path.join(GROOT, ".claude", "ai-bunshin-details-notes"))   # 名前が似ているだけの別のフォルダ（止めない）


def guard(tool, inp):
    env = env_for(GROOT)
    env["HOME"] = GUARD_HOME
    p = subprocess.run([sys.executable, GUARD], input=json.dumps({"tool_name": tool, "tool_input": inp}),
                       capture_output=True, text=True, cwd=GROOT, env=env)
    return "STOP" if "deny" in p.stdout else "pass"


@case
def d1_write_tools_to_the_copy_are_stopped():
    d = details_dir(GROOT)
    for tool, key in (("Write", "file_path"), ("Edit", "file_path"), ("MultiEdit", "file_path"), ("NotebookEdit", "notebook_path")):
        for path in (os.path.join(d, "models.md"), os.path.join(d, "new-file.md"), os.path.join(GROOT, "02_成果物", "..", DETAILS_REL, "models.md"),
                     os.path.join(GROOT, DETAILS_REL, "sub", "x.md"), os.path.join(GROOT, DETAILS_REL.upper(), "models.md")):
            got = guard(tool, {key: path})
            assert got == "STOP", f"{tool} {path} → {got}"


@case
def d2_bash_writes_to_the_copy_are_stopped():
    for c in ("echo x > .claude/ai-bunshin-details/models.md", "echo x >> .claude/ai-bunshin-details/models.md",
              "sed -i '' s/a/b/ .claude/ai-bunshin-details/models.md", "cp 02_成果物/a.md .claude/ai-bunshin-details/models.md",
              "tee .claude/ai-bunshin-details/models.md < 02_成果物/a.md", "mv 02_成果物/a.md .claude/ai-bunshin-details/",
              "mv .claude/ai-bunshin-details/models.md 02_成果物/", "touch .claude/ai-bunshin-details/new.md",
              "python3 -c \"open('.claude/ai-bunshin-details/models.md','w').write('x')\"",
              f"echo x > {details_dir(GROOT)}/models.md", "truncate -s 0 .claude/ai-bunshin-details/models.md"):
        assert guard("Bash", {"command": c}) == "STOP", c


@case
def d3_reading_and_other_folders_still_pass():
    for c in ("cat .claude/ai-bunshin-details/models.md", "grep -n Opus .claude/ai-bunshin-details/models.md", "ls .claude/ai-bunshin-details",
              "head -5 .claude/ai-bunshin-details/dev.md", "cp .claude/ai-bunshin-details/models.md 02_成果物/m.md",
              "echo x > .claude/ai-bunshin-details-notes/a.md", "echo x > 02_成果物/a.md"):
        assert guard("Bash", {"command": c}) == "pass", c
    assert guard("Write", {"file_path": os.path.join(GROOT, "02_成果物", "a.md")}) == "pass"
    assert guard("Write", {"file_path": os.path.join(GROOT, ".claude", "ai-bunshin-details-notes", "a.md")}) == "pass"


@case
def d4_symlink_into_the_copy_is_stopped():
    link = os.path.join(GROOT, "02_成果物")
    os.makedirs(link, exist_ok=True)
    ln = os.path.join(link, "to-details")
    if not os.path.lexists(ln):
        os.symlink(details_dir(GROOT), ln)
    assert guard("Write", {"file_path": os.path.join(ln, "models.md")}) == "STOP"


# ---------- E. 参照（破られ方5） ----------
print("## E. 参照の確認")
SEARCH_DIRS = ["skills", "agents", "templates", "scripts", "hooks"]
SEARCH_FILES = [os.path.join(PLUGIN, "README.md"), os.path.join(PLUGIN, "..", "..", "README.md")]


def plugin_files():
    out = []
    for d in SEARCH_DIRS:
        for dp, dn, fn in os.walk(os.path.join(PLUGIN, d)):
            dn[:] = [x for x in dn if x != "__pycache__"]
            out += [os.path.join(dp, f) for f in fn if f.endswith((".md", ".py", ".sh", ".json", ".txt"))]
    return out + [p for p in SEARCH_FILES if os.path.exists(p)]


def headings_of(text):
    return [re.sub(r"^#+\s*", "", l) for l in text.split("\n") if l.startswith("#")]


@case
def e1_commander_references_point_to_existing_text():
    body_h = headings_of(BODY)
    det = {n: details_text(n) for n in DETAIL_NAMES}
    dangling, moved = [], []
    for p in plugin_files():
        if p.endswith("ng_guard_legacy.py"):
            continue
        text = read(p)
        for m in re.finditer(r"指揮官ルールの「([^」]+)」", text):
            name = m.group(1)
            if any(name in h for h in body_h):
                continue
            home = [n for n, t in det.items() if any(name in h for h in headings_of(t))]
            if home:
                moved.append((os.path.relpath(p, PLUGIN), name, home[0]))
                assert f"ai-bunshin-details/{home[0]}.md" in text, f"{os.path.relpath(p, PLUGIN)}: 「{name}」は details/{home[0]}.md に移ったのに、そのファイルの道が書かれていない"
                continue
            if name in BODY or any(name in t for t in det.values()):
                continue   # 見出しではない言い回し（「デザインシステム」など）が本文にある
            dangling.append((os.path.relpath(p, PLUGIN), name))
    print(f"       参照 {len(moved)} 件が details へ移った節を指す。切れている参照 {len(dangling)} 件")
    assert not dangling, dangling


@case
def e2_every_details_path_mentioned_exists():
    bad = []
    for p in plugin_files() + [BODY_PATH]:
        for m in re.finditer(r"ai-bunshin-details/([A-Za-z0-9_-]+)\.md", read(p)):
            if m.group(1) not in DETAIL_NAMES:
                bad.append((os.path.relpath(p, PLUGIN), m.group(0)))
    assert not bad, bad


# 指示書「スキルの手順で読む」の列
SKILL_READS = {
    "intake": ["tasks-json"],
    "daily-plan": ["tasks-json", "daily-sprint", "models", "calendar"],
    "daily-do": ["daily-sprint", "writing-style"],
    "daily-review": ["retro-try", "daily-sprint", "kaizen", "team-growth"],
    "sprint": ["tasks-json", "models", "team-growth", "writing-style"],
    "dev": ["dev", "models"],
    "setup": ["calendar"],
}


@case
def e3_skills_tell_to_read_the_file_first():
    missing = []
    for skill, names in SKILL_READS.items():
        text = read(os.path.join(PLUGIN, "skills", skill, "SKILL.md"))
        for n in names:
            lines = [l for l in text.split("\n") if f"ai-bunshin-details/{n}.md" in l]
            if not any("先に" in l and "読む" in l for l in lines):
                missing.append((skill, n))
    assert not missing, missing


@case
def e4_skill_steps_sit_in_the_right_step():
    """「先に読む」の行が、該当する手順の見出しの下にある（スキルの最初にまとめて書いただけにしない）。"""
    want = {("intake", "tasks-json"): "依頼を整理する", ("daily-plan", "tasks-json"): "見積もり", ("daily-plan", "models"): "モデルと考える深さ",
            ("daily-plan", "calendar"): "今日の予定", ("daily-review", "kaizen"): "改善の提案", ("daily-review", "team-growth"): "金曜",
            ("sprint", "team-growth"): "詰まっ", ("dev", "models"): "実装", ("setup", "calendar"): "質問"}
    wrong = []
    for (skill, n), key in want.items():
        text = read(os.path.join(PLUGIN, "skills", skill, "SKILL.md"))
        cur, ok = "", False
        for l in text.split("\n"):
            if l.startswith("#"):
                cur = l
            if f"ai-bunshin-details/{n}.md" in l and "先に" in l and (key in cur or key in l):
                ok = True
        if not ok:
            wrong.append((skill, n, key))
    assert not wrong, wrong


@case
def e5_agents_do_not_read_details():
    """部下は読まない（指揮官が指示書の「守ること」に抜き出す）。"""
    bad = [f for f in os.listdir(os.path.join(PLUGIN, "agents")) if "ai-bunshin-details" in read(os.path.join(PLUGIN, "agents", f))]
    assert not bad, bad


# ---------- F. 読まずに tasks.json を手で直す（破られ方6） ----------
print("## F. tasks.json の手直しで、スクリプトの検証が止めるもの・止めないもの")
BASE_TASKS = {"project": {"name": "x", "daily_capacity_default": 8.0, "holidays": []}, "daily_sprints": [],
              "sprints": [{"id": "S001", "start": "2026-10-26", "end": "2026-11-01", "goal": "g", "status": "進行中"}],
              "tasks": [{"id": "T001", "title": "a", "status": "ToDo", "assignee": "dev-a", "type": "開発", "reviewer": "dev-b", "points": 2,
                         "department": "総務", "priority": 1, "sprint": "S001"},
                        {"id": "T002", "title": "b", "status": "ToDo", "assignee": "buka-a", "type": "資料", "reviewer": "buka-b", "points": 2,
                         "department": "総務", "priority": 2, "sprint": "S001", "depends_on": ["T001"]}]}


def run_with(edit):
    t = copy.deepcopy(BASE_TASKS)
    edit(t)
    root = make_owner(tasks=t)
    r = subprocess.run([sys.executable, DASH], capture_output=True, text=True, cwd=root, env=env_for(root))
    return r.returncode


T0 = lambda t: t["tasks"][0]   # noqa: E731
T1 = lambda t: t["tasks"][1]   # noqa: E731
# (項目, 手直し, 止まるか) — 止まる＝スクリプトが異常終了して Excel などを更新しない。止まらない＝そのまま通る（読まないと守れない）
F_CASES = [
    ("ID の重複", lambda t: t["tasks"].append(dict(T0(t))), True),
    ("status が決まった5つ以外", lambda t: T0(t).update(status="x"), True),
    ("完了なのに done_date が無い", lambda t: T0(t).update(status="完了"), True),
    ("due が YYYY-MM-DD でない", lambda t: T0(t).update(due="10/30"), True),
    ("本人のタスク（お願い）に due が無い", lambda t: t["tasks"].append({"id": "T003", "title": "c", "status": "ToDo", "assignee": "テスト", "kind": "判断", "why": "w", "priority": 3}), True),
    ("始めたタスクに reestimate", lambda t: T0(t).update(status="作業中", reestimate=True), True),
    ("sprints の id が無い", lambda t: t["sprints"][0].pop("id"), True),
    ("sprints の start が無い", lambda t: t["sprints"][0].pop("start"), True),
    ("sprints の日付が YYYY-MM-DD でない", lambda t: t["sprints"][0].update(start="2026/10/26"), True),
    ("daily_sprints の date が無い", lambda t: t["daily_sprints"].append({"planned": []}), True),
    ("daily_sprints の date が YYYY-MM-DD でない", lambda t: t["daily_sprints"].append({"date": "1030", "planned": []}), True),
    ("daily_sprints の日付が重複", lambda t: t["daily_sprints"].extend([{"date": "2026-10-30", "planned": []}] * 2), True),
    ("daily_sprints の planned に無いタスク", lambda t: t["daily_sprints"].append({"date": "2026-10-30", "planned": ["T999"]}), True),
    ("daily_sprints の committed が計画の合計と違う", lambda t: t["daily_sprints"].append({"date": "2026-10-30", "planned": ["T001"], "committed": 5}), True),
    ("progress が数でない文字", lambda t: T0(t).update(progress="abc"), True),
    ("ID の形が T+3桁でない", lambda t: T0(t).update(id="T1"), False),
    ("priority の重複", lambda t: T1(t).update(priority=1), False),
    ("priority の欠け", lambda t: T1(t).pop("priority"), False),
    ("type が決まった種類以外", lambda t: T0(t).update(type="zzz"), False),
    ("assignee が決まった担当以外", lambda t: T0(t).update(assignee="zzz"), False),
    ("reviewer が無い", lambda t: T0(t).pop("reviewer"), False),
    ("department が担当部署以外", lambda t: T0(t).update(department="zzz"), False),
    ("depends_on が無いタスクを指す", lambda t: T1(t).update(depends_on=["T999"]), False),
    ("depends_on が自分自身", lambda t: T1(t).update(depends_on=["T002"]), False),
    ("points が基準（1/2/3/5）以外", lambda t: T0(t).update(points=4), False),
    ("points が数でない文字", lambda t: T0(t).update(points="abc"), False),
    ("sprint が無いスプリントの id", lambda t: T0(t).update(sprint="S999"), False),
    ("daily_sprints の committed が無い", lambda t: t["daily_sprints"].append({"date": "2026-10-30", "planned": ["T001"]}), False),
    ("開発なのに dev_project・dev_scope が無い", lambda t: None, False),
]


@case
def f1_the_validation_table_matches_what_the_script_does():
    rows, wrong = [], []
    for name, edit, should_stop in F_CASES:
        code = run_with(edit)
        stopped = code != 0
        rows.append((name, stopped))
        if stopped != should_stop:
            wrong.append(f"{name}: 想定 {'止まる' if should_stop else '止まらない'}／実際 {'止まる' if stopped else '止まらない'}")
    print("       止まる（スクリプトの検証）：" + "、".join(n for n, s in rows if s))
    print("       止まらない（読まないと守れない）：" + "、".join(n for n, s in rows if not s))
    assert not wrong, wrong


@case
def f2_the_untouched_base_passes():
    assert run_with(lambda t: None) == 0


# ---------- G. T101 の小さな直し ----------
print("## G. 本体の小さな直しと警告の出し方")
HAIKU_LINE = "- Haiku は使わない（品質を優先）。別の会社の AI（Codex など）でのレビューは、外部へ渡すことになるので使わない（使うなら本人の判断）"


@case
def g1_haiku_line_is_in_the_body_right_after_the_models_pointer_and_stays_in_details():
    assert HAIKU_LINE in details_text("models").split("\n"), "models.md から消えた"
    assert BODY_LINES.count(HAIKU_LINE) == 1, "本体に原文のまま1行ある"
    i = BODY_LINES.index(HAIKU_LINE)
    assert BODY_LINES[i - 1].startswith("- 詳細：`.claude/ai-bunshin-details/models.md`"), BODY_LINES[i - 1]


@case
def g2_tasks_json_row_says_done_date_is_needed_when_completing():
    rows = [l for l in BODY_LINES if l.startswith("| `.claude/ai-bunshin-details/tasks-json.md`")]
    assert len(rows) == 1, rows
    assert rows[0].endswith("状態を変えるだけなら読まない。ただし完了にするときは `done_date` を入れる |"), rows[0]


@case
def g3_folder_table_lists_the_details_copy_after_the_rules_copy():
    i = next(i for i, l in enumerate(BODY_LINES) if l.startswith("| `.claude/rules/ai-bunshin-common.md` |"))
    row = BODY_LINES[i + 1]
    assert row.startswith("| `.claude/ai-bunshin-details/` |"), row
    assert "自動コピー" in row and "直接編集しない" in row, row


@case
def g4_warning_text_matches_what_happened():
    # 前の本体が残った場合だけ「前の版の共通ルールで動きます」
    root = old_style_owner()
    open(details_dir(root), "w").write("x")
    _, ctx = session(root)
    first = ctx.splitlines()[0]
    assert "前の版の共通ルールで動きます" in first and "無いまま" not in first, first
    # 前の本体が無く、新しい本体を写した場合は事実どおり
    root = make_owner()
    os.makedirs(os.path.join(root, ".claude"))
    open(details_dir(root), "w").write("x")
    _, ctx = session(root)
    first = ctx.splitlines()[0]
    assert "詳しい手順のファイルが無いまま動きます" in first and "前の版" not in first, first


def run_cycle(root):
    today = datetime.date.today().isoformat()
    t = json.load(open(os.path.join(root, "00_タスク管理", "data", "tasks.json"), encoding="utf-8"))
    t["project"]["holidays"] = [today]
    json.dump(t, open(os.path.join(root, "00_タスク管理", "data", "tasks.json"), "w", encoding="utf-8"), ensure_ascii=False)
    fakebin = os.path.join(BASE, "fakebin_claude")
    os.makedirs(fakebin, exist_ok=True)
    with open(os.path.join(fakebin, "claude"), "w") as f:
        f.write("#!/bin/sh\nexit 1\n")
    os.chmod(os.path.join(fakebin, "claude"), 0o755)
    env = env_for(root, {"AI_BUNSHIN_HOME": root, "PATH": fakebin + os.pathsep + os.environ.get("PATH", "")})
    r = subprocess.run(["zsh", CYCLE, "plan"], capture_output=True, text=True, cwd=root, env=env, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    logs = os.path.join(root, "scripts", "auto", "logs")
    return "\n".join(read(os.path.join(logs, f)) for f in sorted(os.listdir(logs))) if os.path.isdir(logs) else ""


@case
def g5_daily_cycle_logs_the_copy_warning_only_when_there_is_one():
    if not shutil.which("zsh"):
        print("       SKIP（zsh なし）")
        return
    root = old_style_owner()
    open(details_dir(root), "w").write("x")   # 写せない状態
    log = run_cycle(root)
    lines = [l for l in log.splitlines() if "写せませんでした" in l]
    assert len(lines) == 1, log
    assert "ai-bunshin-details" in lines[0] and "{" not in lines[0] and "hookSpecificOutput" not in lines[0], lines[0]
    root = old_style_owner()   # 写せる状態：警告の行は無く、ふだんの出力もログに混ざらない
    log = run_cycle(root)
    assert "写せませんでした" not in log and "hookSpecificOutput" not in log, log


print(f"\n失敗 {fails} 件" + (f"（SKIP {SKIPS} 件）" if SKIPS else ""))
sys.exit(1 if fails else 0)
