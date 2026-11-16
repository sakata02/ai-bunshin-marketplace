"""会話の索引（conversation_index.py）のテスト。実行：python3 tests/test_conversation_index.py（失敗があれば終了コード1）
仮の jsonl・仮の zip は一時フォルダに作る（本物の会話は使わない）。"""
import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import conversation_index as ci  # noqa: E402

fail = 0


def check(name, cond, detail=""):
    global fail
    if not cond:
        fail += 1
        print("NG:", name, detail)


def run(argv, home=None, claude=None, project=None, cwd=None):
    """main() を、環境を差し替えて動かす。(終了コード, 標準出力, 標準エラー)"""
    keep_env = {k: os.environ.get(k) for k in ("AI_BUNSHIN_HOME", "CLAUDE_CONFIG_DIR", "CLAUDE_PROJECT_DIR")}
    keep_cwd = os.getcwd()
    for k in keep_env:
        os.environ.pop(k, None)
    if home:
        os.environ["AI_BUNSHIN_HOME"] = str(home)
    if claude:
        os.environ["CLAUDE_CONFIG_DIR"] = str(claude)
    if project:
        os.environ["CLAUDE_PROJECT_DIR"] = str(project)
    if cwd:
        os.chdir(cwd)
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = ci.main(argv)
            except SystemExit as e:  # argparse の usage エラー
                code = e.code
    finally:
        os.chdir(keep_cwd)
        for k, v in keep_env.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
    return code, out.getvalue(), err.getvalue()


def tree_hash(d):
    h = hashlib.sha256()
    for p in sorted(Path(d).rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(d)).encode())
            h.update(p.read_bytes())
            h.update(str(p.stat().st_mtime_ns).encode())
    return h.hexdigest()


def jl(*objs):
    return "".join(json.dumps(o, ensure_ascii=False) + "\n" for o in objs)


def user(text, ts="2026-11-10T03:00:00.000Z", **kw):
    o = {"type": "user", "isSidechain": False, "timestamp": ts, "message": {"role": "user", "content": text}}
    o.update(kw)
    return o


def asst(blocks, ts="2026-11-10T03:00:10.000Z", **kw):
    o = {"type": "assistant", "isSidechain": False, "timestamp": ts, "message": {"role": "assistant", "content": blocks}}
    o.update(kw)
    return o


SECRET = "sk-" + "A1b2C3d4E5f6G7h8I9j0"
GHP = "ghp_" + "a" * 24
AKIA = "AKIA" + "ABCDEFGHIJKLMNOP"
XOX = "xoxb-" + "1234567890abc"
PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy\n-----END RSA PRIVATE KEY-----"

main_lines = jl(
    {"type": "mode", "mode": "x", "sessionId": "s1"},
    {"type": "file-history-snapshot", "snapshot": {}},
    user("T257 の経緯を教えて。<system-reminder>これは消える</system-reminder>キーは %s です" % SECRET),
    asst([{"type": "thinking", "thinking": "秘密の考え"}, {"type": "text", "text": "T257 は先週の件です。鍵 %s と %s と %s と %s" % (GHP, AKIA, XOX, SECRET)}]),
    asst([{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls TOOLUSE_INPUT"}}]),
    user([{"type": "tool_result", "tool_use_id": "t1", "content": "TOOL_RESULT_BODY"}], ts="2026-11-10T03:00:20.000Z"),
    asst([{"type": "text", "text": "続けます。T300 と T1234 も関係。password: hunter2 と パスワード：abc123"}], ts="2026-11-10T03:00:30.000Z"),
    user("サイドの発言", isSidechain=True),
    user("メタの発言", isMeta=True),
    user("<bash-input>cd ~/work && ls</bash-input>"),
    user("<bash-stdout>STDOUT_BODY</bash-stdout><bash-stderr>STDERR_BODY</bash-stderr>"),
    user("<local-command-stdout>LOCAL_OUT</local-command-stdout>続きの質問です\n" + PEM + "\n後ろの文"),
    user("This session is being continued from a previous conversation... SUMMARY_BODY", isCompactSummary=True),
    asst([{"type": "text", "text": "サイドの返事"}], isSidechain=True),
    {"type": "ai-title", "aiTitle": "古い題", "sessionId": "s1"},
    {"type": "ai-title", "aiTitle": "T257 の経緯：確認/メモ?", "sessionId": "s1"},
    {"type": "api-request-blob", "message": "user assistant ai-title"},
)
# 壊れた行も混ぜる（落ちないこと）
main_lines += "{これは壊れた行 \"user\"\n"


def make_home(tmp, name="home"):
    h = Path(tmp) / name
    (h / "設定").mkdir(parents=True)
    (h / "設定" / "config.json").write_text("{}", encoding="utf-8")
    (h / "00_タスク管理" / "data").mkdir(parents=True)  # 本人のフォルダの目印（update_dashboard.find_root と同じ）
    (h / "00_タスク管理" / "data" / "tasks.json").write_text("{}", encoding="utf-8")
    return h


def make_claude(tmp, name="claude"):
    c = Path(tmp) / name
    p = c / "projects"
    (p / "-Users-x-proj").mkdir(parents=True)
    (p / "-Users-x-proj" / "aaaaaaaa-1111-2222-3333-444444444444.jsonl").write_text(main_lines, encoding="utf-8")
    (p / "-Users-x-proj" / "bbbbbbbb-1111-2222-3333-444444444444.jsonl").write_text(
        jl(user("別の会話。キーワードは banana", ts="2026-11-12T03:00:00.000Z"),
           asst([{"type": "text", "text": "banana の話ですね"}], ts="2026-11-12T03:00:05.000Z")), encoding="utf-8")
    # 部下の会話（下のフォルダ）は読まない
    (p / "-Users-x-proj" / "sub").mkdir()
    (p / "-Users-x-proj" / "sub" / "cccccccc-0000-0000-0000-000000000000.jsonl").write_text(
        jl(user("部下の会話 SUBDIR_ONLY")), encoding="utf-8")
    # 一時フォルダ
    for n in ("-private-tmp-claude-501-x", "-Users-x-proj-scratchpad-y", "-var-folders-ab-T-z"):
        (p / n).mkdir()
        (p / n / "dddddddd-0000-0000-0000-000000000000.jsonl").write_text(jl(user("一時 TMP_ONLY")), encoding="utf-8")
    # 空（入れる文が無い）jsonl
    (p / "-Users-x-proj" / "eeeeeeee-0000-0000-0000-000000000000.jsonl").write_text(
        jl({"type": "mode", "mode": "x"}), encoding="utf-8")
    return c


def chat_export_data():
    return [
        {"uuid": "11111111-aaaa-bbbb-cccc-000000000001", "name": "請求書の相談", "created_at": "2026-10-01T01:00:00.000000Z",
         "updated_at": "2026-10-01T02:00:00.000000Z",
         "chat_messages": [
             {"sender": "human", "created_at": "2026-10-01T01:00:00Z", "text": "T410 の請求書について。token %s" % SECRET},
             {"sender": "assistant", "created_at": "2026-10-01T01:01:00Z", "text": "", "content": [{"type": "text", "text": "請求書の件ですね（contentから）"}, {"type": "tool_use", "name": "x"}]},
             {"sender": "system", "text": "無視される"},
         ]},
        {"uuid": "22222222-aaaa-bbbb-cccc-000000000002", "name": "", "created_at": "2026-10-05T01:00:00Z", "updated_at": "2026-10-05T01:05:00Z",
         "chat_messages": [{"sender": "human", "text": "題の無い会話です"}, {"sender": "assistant", "text": "はい"}]},
        {"title": "知らない形", "messages": [{"role": "user"}]},      # 知らない形
        "文字列が混ざっている",                                          # 知らない形
        {"uuid": "33333333-aaaa-bbbb-cccc-000000000003", "name": "空", "chat_messages": []},  # 空
    ]


def make_chat_zip(path, data=None, inner="conversations.json"):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("users.json", "[]")
        z.writestr(inner, json.dumps(data if data is not None else chat_export_data(), ensure_ascii=False))


def read_index(home):
    p = Path(home) / "06_会話履歴" / "索引.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


# ---------------- 単体：伏せる・取り除く ----------------
check("伏せる sk", ci.redact("a %s b" % SECRET) == "a %s b" % ci.MASK)
check("伏せる ghp", ci.redact(GHP) == ci.MASK)
check("伏せる ghs（別の種類）", ci.redact("ghs_" + "Z" * 22) == ci.MASK)
check("伏せる AKIA", ci.redact(AKIA) == ci.MASK)
check("伏せる xox", ci.redact(XOX) == ci.MASK)
check("伏せる 短い sk は残る", ci.redact("sk-short") == "sk-short")
check("伏せる 秘密鍵（BEGIN〜END）", ci.redact("前\n" + PEM + "\n後") == "前\n%s\n後" % ci.MASK)
check("伏せる 秘密鍵（ENDが無ければ最後まで）", ci.redact("前 -----BEGIN PRIVATE KEY-----\nAAAA\nBBBB") == "前 " + ci.MASK)
check("伏せる password: 値だけ", ci.redact("password: hunter2 です") == "password: %s です" % ci.MASK)
check("伏せる PASSWD=", ci.redact("PASSWD=abc") == "PASSWD=" + ci.MASK)
check("伏せる パスワード：（全角）", ci.redact("パスワード：abc123 だよ") == "パスワード：%s だよ" % ci.MASK)
check("伏せる 普通の文は変わらない", ci.redact("パスワードの変更方法を教えて") == "パスワードの変更方法を教えて")
check("取り除く 4種", ci.clean_user_text("a<system-reminder>x</system-reminder>b<bash-stdout>y</bash-stdout>c<bash-stderr>z</bash-stderr>d<local-command-stdout>w</local-command-stdout>e") == "abcde")
check("bash-input は（コマンド）で残す", ci.clean_user_text("<bash-input> ls -la </bash-input>") == "（コマンド）ls -la")
check("タスク番号：重ならず・数字つづきは別", ci.find_tasks("T257の経緯 T257 T300 xT111 T12345 T99") == ["T257", "T300"], ci.find_tasks("T257の経緯 T257 T300 xT111 T12345 T99"))
check("タスク番号：4桁", ci.find_tasks("T1234,T0001") == ["T0001", "T1234"])

with tempfile.TemporaryDirectory() as tmp:
    home = make_home(tmp)
    claude = make_claude(tmp)
    zdir = home / "03_インプット" / "会話"
    zdir.mkdir(parents=True)
    make_chat_zip(zdir / "data-2026-11-01.zip")
    # 展開したフォルダ
    (zdir / "export-folder").mkdir()
    (zdir / "export-folder" / "conversations.json").write_text(json.dumps(chat_export_data(), ensure_ascii=False), encoding="utf-8")
    # conversations.json の無い zip（読めない形）
    with zipfile.ZipFile(zdir / "broken.zip", "w") as z:
        z.writestr("other.json", "[]")
    src_hash_before = (tree_hash(claude), tree_hash(home / "03_インプット"))

    # ---------------- sources ----------------
    code, out, err = run(["sources"], home=home, claude=claude)
    check("sources 終了コード", code == 0, err)
    check("sources Code のフォルダが出る（会話2件）", "-Users-x-proj  会話 3 件" in out or "会話 3 件" in out, out)
    check("sources 一時フォルダは出ない", "scratchpad" not in out.replace("tmp・scratchpad", "") and "private-tmp" not in out and "var-folders" not in out, out)
    check("sources 一時フォルダの数を出す（3件）", "3 件は出していません" in out, out)
    check("sources 部下のフォルダ（sub）は数えない", "会話 3 件" in out and "SUBDIR_ONLY" not in out, out)
    check("sources チャットが出る（zip・フォルダ・読めない形）", "data-2026-11-01.zip  会話 2 件" in out and "export-folder  会話 2 件" in out and "読めない形" in out, out)
    check("sources 期間が出る", "2026-10-01〜2026-10-05" in out, out)
    check("sources まだ全部未選択", out.count("[未選択]") == 4 and "[選択済]" not in out, out)
    check("sources は何も書かない（06_会話履歴 が無い）", not (home / "06_会話履歴").exists())
    nums = {}
    for line in out.splitlines():
        s = line.strip()
        if s[:1].isdigit() and ". " in s:
            nums[s.split(". ", 1)[1].split("  ")[0]] = int(s.split(". ", 1)[0])
    check("sources 番号付き（Code→チャット）", nums.get("-Users-x-proj") == 1 and "data-2026-11-01.zip" in nums, str(nums))

    # ---------------- import（Code のフォルダ1つ） ----------------
    code, out, err = run(["import", "-Users-x-proj"], home=home, claude=claude)
    check("import 終了コード", code == 0, err)
    check("import の最後の1行：読んだ・飛ばした・伏せた", "読んだ 2 件・飛ばした 1 件・伏せた " in out and out.strip().splitlines()[-1].endswith("箇所"), out)
    idx = read_index(home)
    by = {r["id"][:8]: r for r in idx}
    check("import 会話は2件（空の jsonl・一時・部下は入らない）", len(idx) == 2, str([r["id"] for r in idx]))
    a = by.get("aaaaaaaa", {})
    check("索引の項目", set(a) == {"id", "kind", "source", "started", "ended", "title", "tasks", "first", "has_summary", "messages", "file"}, str(sorted(a)))
    check("kind/source", a.get("kind") == "code" and a.get("source") == "-Users-x-proj")
    check("題は最後の ai-title", a.get("title") == "T257 の経緯：確認/メモ?", a.get("title"))
    check("tasks（重なりなし・T12345 は入らない）", a.get("tasks") == ["T0257"[0] + "257", "T1234", "T300"] or a.get("tasks") == ["T1234", "T257", "T300"], str(a.get("tasks")))
    check("first は本人の最初の発言の頭80字（system-reminder を除いた形）", a.get("first", "").startswith("T257 の経緯を教えて。キーは") and len(a["first"]) <= 80, a.get("first"))
    check("has_summary", a.get("has_summary") is True)
    check("messages は本人の発言の数（サイド・メタ・まとめ・空を除く）", a.get("messages") == 3, str(a.get("messages")))
    check("started/ended は ISO 8601 で started<=ended", a.get("started", "") and a["started"] <= a["ended"], str((a.get("started"), a.get("ended"))))
    d0 = datetime.fromisoformat("2026-11-10T03:00:00+00:00").astimezone().date().isoformat()
    check("started の日付", a.get("started", "")[:10] == d0, a.get("started"))
    check("file は本人のフォルダからの相対", a.get("file", "").startswith("06_会話履歴/会話/") and (home / a["file"]).is_file(), a.get("file"))
    check("ファイル名：日付_ID8（題を入れない）", a["file"] == "06_会話履歴/会話/%s_aaaaaaaa.md" % d0.replace("-", ""), a["file"])
    md = (home / a["file"]).read_text(encoding="utf-8")
    check("md 本人の発言と AI の返事が入る", "T257 の経緯を教えて" in md and "T257 は先週の件です" in md and "続けます" in md)
    check("md まとめが入る", "## まとめ" in md and "SUMMARY_BODY" in md)
    for bad in ("TOOL_RESULT_BODY", "TOOLUSE_INPUT", "秘密の考え", "サイドの発言", "メタの発言", "サイドの返事", "STDOUT_BODY", "STDERR_BODY",
                "LOCAL_OUT", "これは消える", "古い題"):
        check("md に入らない：" + bad, bad not in md)
    check("md bash-input は（コマンド）", "（コマンド）cd ~/work && ls" in md)
    check("md 本人の文の残りは残る", "続きの質問です" in md and "後ろの文" in md)
    for bad in (SECRET, GHP, AKIA, XOX, "hunter2", "abc123", "MIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy"):
        check("md に鍵が残らない：" + bad[:8], bad not in md)
    check("md 伏せた印", md.count(ci.MASK) >= 7, str(md.count(ci.MASK)))
    check("md AI の連続はまとめる（道具の前後が1つ）・本人の発言はまとめない", md.count("] AI ") == 1 and md.count("] 本人 ") == 3, "%d/%d" % (md.count("] AI "), md.count("] 本人 ")))
    check("索引・md の全体に鍵が残らない", all(s not in (home / "06_会話履歴" / "索引.jsonl").read_text(encoding="utf-8") for s in (SECRET, "hunter2")))
    check("sources.json の中身", (lambda d: d["sources"][0]["kind"] == "code" and len(d["files"]) == 3 and all("mtime" in v and "size" in v for v in d["files"].values()))(
        json.loads((home / "06_会話履歴" / "sources.json").read_text(encoding="utf-8"))))
    check("元（Code の jsonl）が変わらない", tree_hash(claude) == src_hash_before[0])
    check("03_インプット に書かない", tree_hash(home / "03_インプット") == src_hash_before[1])

    # ---------------- search ----------------
    code, out, err = run(["search", "T257"], home=home, claude=claude)
    check("search T257：a だけ", code == 0 and "[aaaaaaaa]" in out and "[bbbbbbbb]" not in out, out)
    check("search 1件1行（日付・題・ID・当たり）", out.strip().splitlines()[0].startswith(d0) and "当たり" in out.splitlines()[0], out)
    code, out, _ = run(["search", "banana"], home=home, claude=claude)
    check("search 本文", "[bbbbbbbb]" in out and "[aaaaaaaa]" not in out, out)
    code, out, _ = run(["search", "の"], home=home, claude=claude)
    lines = [x for x in out.splitlines() if "[" in x]
    check("search 並び：日付の新しい順（bbbbbbbb が先）", len(lines) == 2 and "[bbbbbbbb]" in lines[0] and "[aaaaaaaa]" in lines[1], out)
    code, out, _ = run(["search", "の", "--limit", "1"], home=home, claude=claude)
    check("search --limit", len([x for x in out.splitlines() if "[" in x]) == 1 and "ほか 1 件" in out, out)
    code, out, _ = run(["search", "T123"], home=home, claude=claude)
    check("search T123 は T1234 に当たらない（T 番号は桁の境目で見る）", "当たる会話はありません" in out, out)
    code, out, _ = run(["search", "T1234"], home=home, claude=claude)
    check("search T1234 は当たる", "[aaaaaaaa]" in out, out)
    code, out, _ = run(["search", "T2570"], home=home, claude=claude)
    check("search 当たらない", "当たる会話はありません" in out, out)
    code, out, _ = run(["search", "banana", "T257"], home=home, claude=claude)
    check("search 複数の言葉は全部入っている会話だけ", "当たる会話はありません" in out, out)
    code, out, _ = run(["search", "T257", "経緯"], home=home, claude=claude)
    check("search 複数の言葉で当たる", "[aaaaaaaa]" in out, out)

    # ---------------- show ----------------
    code, out, err = run(["show", "aaaaaaaa"], home=home, claude=claude)
    check("show まとめと会話", code == 0 and "## まとめ" in out and "SUMMARY_BODY" in out and "T257 の経緯を教えて" in out, out + err)
    code, out, err = run(["show", "aaa"], home=home, claude=claude)
    check("show 頭の数文字でもよい", code == 0 and "ID aaaaaaaa" in out, out + err)
    code, out, err = run(["show", "zzzz"], home=home, claude=claude)
    check("show 無い ID は失敗", code == 1 and err)
    code, out, err = run(["show", "aaaaaaaa", "--grep", "banana"], home=home, claude=claude)
    check("show --grep 当たりなし", "当たる発言はありません" in out and "## まとめ" in out, out)
    # 長い会話：grep と context と 4000字の切り
    big = [user("最初の質問 FIRSTQ", ts="2026-11-13T01:00:00Z")]
    for i in range(1, 31):
        big.append(asst([{"type": "text", "text": "返事%d " % i + "あ" * (1500 if i in (1, 2, 29, 30) else 50)}], ts="2026-11-13T01:%02d:00Z" % i))
        big.append(user("質問%d%s" % (i, " NEEDLE" if i in (10, 11, 25) else ""), ts="2026-11-13T01:%02d:30Z" % i))
    (claude / "projects" / "-Users-x-proj" / "ffffffff-1111-2222-3333-444444444444.jsonl").write_text(jl(*big), encoding="utf-8")
    code, out, _ = run(["update"], home=home, claude=claude)
    check("update 増えたファイルを足す", "足した 1 件" in out, out)
    code, out, err = run(["show", "ffffffff"], home=home, claude=claude)
    check("show grep なし：最初と最後の5件・省略の注記", "[1]" in out and "FIRSTQ" in out and "省略" in out, out[:300])
    check("show 4000字で切る", len(out.rstrip("\n")) <= 4000 + 120 and "4000字で切りました" in out and "--grep" in out.splitlines()[-1], str(len(out)))
    code, out, err = run(["show", "ffffffff", "--grep", "NEEDLE", "--context", "1"], home=home, claude=claude)
    nums_shown = [int(x.split("]")[0][5:]) for x in out.splitlines() if x.startswith("### [")]
    # 1=最初の質問、以降 返事i=2i・質問i=2i+1。当たりは 質問10=21・質問11=23・質問25=51。前後1件 → 20〜24 と 50〜52
    check("show --grep 当たった発言と前後1件", nums_shown == [20, 21, 22, 23, 24, 50, 51, 52], str(nums_shown))
    check("show --grep 離れた所は … でつなぐ", "\n…\n" in out, out[:200])
    code, out, err = run(["show", "ffffffff", "--grep", "NEEDLE", "--context", "0"], home=home, claude=claude)
    check("show --context 0 は当たった発言だけ", [x for x in out.splitlines() if x.startswith("### [")] == ["### [21] 本人", "### [23] 本人", "### [51] 本人"], out)

    # ---------------- チャット ----------------
    code, out, err = run(["import", "data-2026-11-01.zip"], home=home, claude=claude)
    check("import チャット zip", code == 0 and "読んだ 2 件・飛ばした 3 件" in out, out + err)
    idx = read_index(home)
    chats = [r for r in idx if r["kind"] == "chat"]
    check("チャット：読める2件だけ（知らない形・文字列・空は飛ばす）", len(chats) == 2, str(len(chats)))
    c1 = next((r for r in chats if r["id"].startswith("11111111")), {})
    c2 = next((r for r in chats if r["id"].startswith("22222222")), {})
    check("チャットの題", c1.get("title") == "請求書の相談" and c1.get("source") == "data-2026-11-01.zip")
    check("チャットの題が空なら最初の発言", c2.get("title") == "題の無い会話です", c2.get("title"))
    check("チャットの tasks", c1.get("tasks") == ["T410"])
    check("チャットの messages（human だけ数える）", c1.get("messages") == 1 and c2.get("messages") == 1)
    check("チャットの期間", c1.get("started", "").startswith(datetime.fromisoformat("2026-10-01T01:00:00+00:00").astimezone().date().isoformat()))
    cmd = (home / c1["file"]).read_text(encoding="utf-8")
    check("チャット content からの文・鍵を伏せる", "contentから" in cmd and SECRET not in cmd and ci.MASK in cmd and "無視される" not in cmd)
    check("チャット has_summary は False", c1.get("has_summary") is False)
    code, out, _ = run(["search", "請求書"], home=home, claude=claude)
    check("search チャット", "[11111111]" in out, out)
    # 展開したフォルダ・読めない zip
    code, out, err = run(["import", "export-folder", "broken.zip"], home=home, claude=claude)
    check("import フォルダ・読めない zip でも落ちない", code == 0 and "飛ばした" in out, out + err)
    check("import 同じ uuid の会話は更新扱い（増えない）", len([r for r in read_index(home) if r["kind"] == "chat"]) == 2)
    check("import 番号でも選べる", run(["import", "1"], home=home, claude=claude)[0] == 0)
    code, out, err = run(["import", "nonexistent-xyz"], home=home, claude=claude)
    check("import 見つからない名前は失敗を返す", code == 1 and "見つかりません" in err, out + err)
    code, out, err = run(["import"], home=home, claude=claude)
    check("import 何も選ばなければ失敗を返す", code == 1)
    check("元（zip・チャット）が変わらない", tree_hash(home / "03_インプット") == src_hash_before[1])

    # ---------------- update：変わったファイルだけ ----------------
    before_md = {p.name: p.stat().st_mtime_ns for p in (home / "06_会話履歴" / "会話").glob("*.md")}
    time.sleep(0.05)
    code, out, _ = run(["update", "--quiet"], home=home, claude=claude)
    check("update 変更なしなら何も出さない（--quiet）", code == 0 and out == "", repr(out))
    after_md = {p.name: p.stat().st_mtime_ns for p in (home / "06_会話履歴" / "会話").glob("*.md")}
    check("update 変更なしなら md を作り直さない", before_md == after_md)
    # b だけ変える
    bp = claude / "projects" / "-Users-x-proj" / "bbbbbbbb-1111-2222-3333-444444444444.jsonl"
    time.sleep(0.05)
    bp.write_text(bp.read_text(encoding="utf-8") + jl(user("追加の発言 apple", ts="2026-11-12T05:00:00Z")), encoding="utf-8")
    # 新しい jsonl も1つ
    (claude / "projects" / "-Users-x-proj" / "99999999-1111-2222-3333-444444444444.jsonl").write_text(
        jl(user("新しい会話 cherry", ts="2026-11-14T05:00:00Z")), encoding="utf-8")
    # 選んでいない新しい Code のフォルダは足さない
    (claude / "projects" / "-Users-x-other").mkdir()
    (claude / "projects" / "-Users-x-other" / "77777777-0000-0000-0000-000000000000.jsonl").write_text(jl(user("別フォルダ NOTSELECTED")), encoding="utf-8")
    code, out, _ = run(["update", "--quiet"], home=home, claude=claude)
    check("update --quiet は1行だけ（足した数）", code == 0 and len(out.strip().splitlines()) == 1 and "新しく 1 件" in out and "更新 1 件" in out, repr(out))
    after2 = {p.name: p.stat().st_mtime_ns for p in (home / "06_会話履歴" / "会話").glob("*.md")}
    changed = [n for n in after2 if after_md.get(n) != after2[n]]
    check("update 変わった b と新しい 9 だけ作り直す", sorted(n.rsplit("_", 1)[1] for n in changed) == ["99999999.md", "bbbbbbbb.md"], str(changed))
    check("update で b の中身が増える", "[bbbbbbbb]" in run(["search", "apple"], home=home, claude=claude)[1])
    check("update 新しい Code のフォルダは勝手に足さない", "当たる会話はありません" in run(["search", "NOTSELECTED"], home=home, claude=claude)[1])
    check("update 新しい jsonl が足される", "[99999999]" in run(["search", "cherry"], home=home, claude=claude)[1])
    # 題が変わったら古い md が残らない
    n_before = len(list((home / "06_会話履歴" / "会話").glob("*.md")))
    ap_ = claude / "projects" / "-Users-x-proj" / "aaaaaaaa-1111-2222-3333-444444444444.jsonl"
    time.sleep(0.05)
    ap_.write_text(ap_.read_text(encoding="utf-8") + jl({"type": "ai-title", "aiTitle": "新しい題"}), encoding="utf-8")
    run(["update", "--quiet"], home=home, claude=claude)
    n_after = len(list((home / "06_会話履歴" / "会話").glob("*.md")))
    check("update 題が変わっても md が増えない・索引の題が変わる", n_before == n_after and next(r for r in read_index(home) if r["id"].startswith("aaaaaaaa"))["title"] == "新しい題", "%d/%d" % (n_before, n_after))
    code, out, _ = run(["update"], home=home, claude=claude)
    check("update（--quiet なし）は結果を出す", "足した 0 件" in out, out)
    # 元の変化を、自分の変更として分けて確かめる：読むだけのコマンド（sources・search・show・update）の前後で元の hash が同じ
    h1 = (tree_hash(claude), tree_hash(home / "03_インプット"))
    for argv in (["sources"], ["search", "T257"], ["show", "aaaaaaaa"], ["update"], ["import", "--all"]):
        run(argv, home=home, claude=claude)
    check("コマンドの前後で元の jsonl・zip が変わらない（import --all を含む）", h1 == (tree_hash(claude), tree_hash(home / "03_インプット")))
    # 再 import（変わっていない）は読み直さない
    code, out, _ = run(["import", "--all"], home=home, claude=claude)
    check("import --all の再実行は、変わっていないファイルを読まない", "読んだ 0 件" in out, out)

# ---------------- sources.json が無いときの update ----------------
with tempfile.TemporaryDirectory() as tmp:
    home = make_home(tmp)
    claude = make_claude(tmp)
    code, out, err = run(["update", "--quiet"], home=home, claude=claude)
    check("sources.json が無い update --quiet は何も出さない・何も作らない", code == 0 and out == "" and err == "" and not (home / "06_会話履歴").exists(), out + err)
    code, out, err = run(["update"], home=home, claude=claude)
    check("sources.json が無い update も何も出さない", code == 0 and out == "" and err == "" and not (home / "06_会話履歴").exists(), out + err)
    # sources.json が壊れていても落ちない
    (home / "06_会話履歴").mkdir()
    (home / "06_会話履歴" / "sources.json").write_text("{壊れた", encoding="utf-8")
    code, out, err = run(["update", "--quiet"], home=home, claude=claude)
    check("sources.json が壊れていても update --quiet は静かに終わる", code == 0 and out == "")

# ---------------- 本人のフォルダが見つからないとき ----------------
with tempfile.TemporaryDirectory() as tmp:
    nohome = Path(tmp) / "nohome"
    nohome.mkdir()
    claude = make_claude(tmp)
    h0 = tree_hash(tmp)
    code, out, err = run(["update", "--quiet"], claude=claude, project=nohome, cwd=nohome)
    check("本人のフォルダが無いとき update は何もしない（出力なし・終了コード 0）", code == 0 and out == "" and err == "", out + err)
    code, out, err = run(["import", "--all"], claude=claude, project=nohome, cwd=nohome)
    check("本人のフォルダが無いとき import は何も書かず終了コード 0", code == 0 and out == "" and not (nohome / "06_会話履歴").exists())
    check("本人のフォルダが無いとき何も作らない", tree_hash(tmp) == h0)
    # CLAUDE_PROJECT_DIR → cwd の順、上のフォルダまで探す
    home = make_home(tmp, "home2")
    sub = home / "05_開発" / "x"
    sub.mkdir(parents=True)
    check("find_root：下のフォルダから上へ", (lambda r: r == home.resolve())(
        (lambda: (os.environ.pop("AI_BUNSHIN_HOME", None), os.environ.__setitem__("CLAUDE_PROJECT_DIR", str(sub)), ci.find_root())[2])()))
    os.environ.pop("CLAUDE_PROJECT_DIR", None)

# ---------------- 保存場所が無い・空のとき ----------------
with tempfile.TemporaryDirectory() as tmp:
    home = make_home(tmp)
    code, out, err = run(["sources"], home=home, claude=Path(tmp) / "nowhere")
    check("Code の保存場所が無くても sources は落ちない", code == 0 and "（なし）" in out, out + err)
    code, out, err = run(["search", "x"], home=home, claude=Path(tmp) / "nowhere")
    check("索引が無くても search は落ちない", code == 0 and "当たる会話はありません" in out, out + err)


# ================= 追加の決定 K16〜K29 =================
import shutil  # noqa: E402
import subprocess  # noqa: E402


def parse_lines(tmp, *objs, name="a1111111-0000-0000-0000-000000000000.jsonl"):
    p = Path(tmp) / name
    p.write_text(jl(*objs), encoding="utf-8")
    return ci.parse_code_jsonl(p)


def queued(prompt, kind="human", mode="prompt", meta=None, ts="2026-11-10T04:00:00.000Z"):
    a = {"type": "queued_command", "prompt": prompt, "commandMode": mode, "origin": {"kind": kind}, "timestamp": ts}
    if meta is not None:
        a["isMeta"] = meta
    return {"type": "attachment", "isSidechain": False, "timestamp": ts, "attachment": a}


# ---- K17：判定の順番・queued_command・画像 ----
with tempfile.TemporaryDirectory() as tmp:
    conv = parse_lines(
        tmp,
        user("<task-notification>\n<task-id>x</task-id>TN_STRING_BODY</task-notification>"),
        user([{"type": "text", "text": "<task-notification>TN_LIST_BODY</task-notification>"}]),
        queued("<task-notification>TN_QUEUED</task-notification>", kind="task-notification", mode="task-notification"),
        queued("QUEUED_PEER_BODY", kind="peer", meta=True),
        queued("QUEUED_META_BODY", meta=True),
        queued("QUEUED_PEER_NOHUMAN", kind="peer"),
        queued("QUEUED_BADMODE", mode="bash"),
        queued("QUEUED_HUMAN_ONLY 本人が打った文", ts="2026-11-10T04:00:01.000Z"),
        user("同じ文です"),
        queued("同じ文です", ts="2026-11-10T03:00:00.000Z"),   # 近くの user 行と同じ文 → 1つ
        user([{"type": "image", "source": {"type": "base64", "data": "AAAA"}}, {"type": "text", "text": "この画像を見て"}]),
        user([{"type": "tool_result", "tool_use_id": "x", "content": [{"type": "image", "source": {}}]}]),
        user("要約です", isCompactSummary=True),
        asst([{"type": "text", "text": "返事"}]),
    )
    texts = [t[2] for t in conv["turns"]]
    alltext = "\n".join(texts) + "\n".join(conv["summaries"])
    for bad in ("TN_STRING_BODY", "TN_LIST_BODY", "TN_QUEUED", "QUEUED_PEER_BODY", "QUEUED_META_BODY", "QUEUED_PEER_NOHUMAN", "QUEUED_BADMODE"):
        check("K17 入れない：" + bad, bad not in alltext)
    check("K17 task-notification の文字が残らない", "task-notification" not in alltext and "queued_command" not in alltext)
    check("K17 本人の queued_command は発言に足す", any("QUEUED_HUMAN_ONLY" in t for t in texts))
    check("K17 近くの user 行と同じ文は1つ", texts.count("同じ文です") == 1, str(texts))
    check("K17 image は（画像）", any(t.startswith("（画像）") and "この画像を見て" in t for t in texts), str(texts))
    check("K17 tool_result の中の画像は入れない", sum("（画像）" in t for t in texts) == 1)
    check("K17 まとめは①で拾う", conv["summaries"] == ["要約です"] and conv["has_summary"])
    check("K17 messages は発言の数（queued を含み、重なりを除く）", conv["messages"] == 3, str(conv["messages"]))

# ---- K18：題の決め方 ----
with tempfile.TemporaryDirectory() as tmp:
    c1 = parse_lines(tmp, user("最初の発言"), {"type": "ai-title", "aiTitle": "AI の題"}, {"type": "custom-title", "customTitle": "古い手の題"},
                     {"type": "custom-title", "customTitle": "最後の手の題"}, {"type": "ai-title", "aiTitle": "AI の最後の題"})
    check("K18 custom-title の最後が先", c1["title"] == "最後の手の題", c1["title"])
    c2 = parse_lines(tmp, user("最初の発言"), {"type": "ai-title", "aiTitle": "AI の題"}, {"type": "ai-title", "aiTitle": "AI の最後の題"})
    check("K18 次は ai-title の最後", c2["title"] == "AI の最後の題", c2["title"])
    c3 = parse_lines(tmp, user("あ" * 50))
    check("K18 次は first の頭30字", c3["title"] == "あ" * 30, c3["title"])
    c4 = parse_lines(tmp, user("まとめだけ", isCompactSummary=True))
    check("K18 何も無ければ（題なし）", c4 is not None and c4["title"] == "（題なし）", str(c4 and c4["title"]))

# ---- K19：伏せる形と数・掛ける先 ----
cases = {
    "sk_live": "sk_live_" + "abcdEFGH1234", "rk_test": "rk_test_" + "abcdEFGH1234",
    "github_pat": "github_pat_" + "A" * 22 + "_b", "glpat": "glpat-" + "x" * 18, "AIza": "AIza" + "B" * 32,
    "ya29": "ya29." + "a1b2c3_d4-e5", "jwt": "eyJhbGciOi.eyJzdWIiOiIx.SflKxwRJSMeKKF2QT4",
}
for nm, secret in cases.items():
    out_ = ci.redact("前 %s 後" % secret)
    check("K19 伏せる：" + nm, secret not in out_ and ci.MASK in out_, out_)
check("K19 Bearer", ci.redact("Bearer abcdefgh12345") == "Bearer " + ci.MASK)
check("K19 Bearer 短いのは残る", ci.redact("Bearer abc") == "Bearer abc")
check("K19 Authorization（2語）", ci.redact("Authorization: Basic dXNlcjpwYXNz 以上") == "Authorization: %s 以上" % ci.MASK, ci.redact("Authorization: Basic dXNlcjpwYXNz 以上"))
check("K19 URL の user:pass@", ci.redact("https://admin:p4ssw0rd@example.com/x") == "https://%s@example.com/x" % ci.MASK, ci.redact("https://admin:p4ssw0rd@example.com/x"))
check("K19 クエリの token=", ci.redact("https://a.example/x?id=1&token=abc123def&z=2") == "https://a.example/x?id=1&token=%s&z=2" % ci.MASK)
check("K19 クエリ signature=", ci.redact("?signature=xyz789") == "?signature=" + ci.MASK)
check("K19 api_key: 値（8字以上）", ci.redact("api_key: abcdefgh1234") == "api_key: " + ci.MASK)
check("K19 api-key=（引用つき）", ci.redact('"api_key": "abcdefgh1234"') == '"api_key": "%s' % ci.MASK)
check("K19 STRIPE_SECRET_KEY=", ci.redact("STRIPE_SECRET_KEY=abcdefgh1234") == "STRIPE_SECRET_KEY=" + ci.MASK)
check("K19 DB_PASSWORD=", ci.redact("DB_PASSWORD=abcdefgh1234") == "DB_PASSWORD=" + ci.MASK)
check("K19 短い値・ふつうの文は残る", ci.redact("token: abc と key: x") == "token: abc と key: x")
check("K19 calendar/ical/", ci.redact("https://calendar.google.com/calendar/ical/abc%40x/private-0123/basic.ics 以上") == "https://calendar.google.com/calendar/ical/%s 以上" % ci.MASK)
check("K19 hooks.slack.com/services/", "T000" not in ci.redact("https://hooks.slack.com/services/T000/B000/XXXX") and ci.MASK in ci.redact("https://hooks.slack.com/services/T000/B000/XXXX"))
sha40 = "a1b2c3d4e5" * 4
check("K19 40字の英数字（git の版）は伏せない", ci.redact("commit %s です" % sha40) == "commit %s です" % sha40)
check("K19 task-foo のような sk- は伏せない", ci.redact("disk-usage-report-weekly-run") == "disk-usage-report-weekly-run")
ci._masked[0] = 0
ci.redact("sk-" + "A1b2C3d4E5f6G7h8I9j0 と Bearer abcdefgh12345 と password: zzz")
check("K19 伏せた数を数える（3箇所）", ci._masked[0] == 3, str(ci._masked[0]))
ci._masked[0] = 0
ci.redact("password: " + ci.MASK)
check("K19 伏せ済みは数えない", ci._masked[0] == 0)
with tempfile.TemporaryDirectory() as tmp:
    cv = parse_lines(tmp, user("<bash-input>curl -H 'Authorization: Bearer abcdefgh12345' x</bash-input> first にも sk-A1b2C3d4E5f6G7h8I9j0"),
                     user("まとめ ghp_" + "b" * 24, isCompactSummary=True),
                     {"type": "ai-title", "aiTitle": "題に sk-A1b2C3d4E5f6G7h8I9j0"})
    blob = json.dumps(cv, ensure_ascii=False)
    check("K19 コマンド・first・まとめ・題にも掛かる", "abcdefgh12345" not in blob and "A1b2C3d4E5f6G7h8I9j0" not in blob and "b" * 24 not in blob and ci.MASK in cv["title"] and ci.MASK in cv["first"] and ci.MASK in cv["summaries"][0], blob[:300])

# ---- K16：Git の控えに入らないことの確認 ----
if shutil.which("git"):
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp)
        claude = make_claude(tmp)
        r = subprocess.run(["git", "init", "-q", str(home)], capture_output=True)
        code, out, err = run(["import", "-Users-x-proj"], home=home, claude=claude)
        check("K16 Git の管理下で ignore が無ければ取り込まずに止める", code == 1 and ".gitignore" in err and "06_会話履歴/" in err and not (home / "06_会話履歴").exists(), out + err)
        check("K16 .gitignore を書き換えない", not (home / ".gitignore").exists())
        (home / ".gitignore").write_text("06_会話履歴/\n", encoding="utf-8")
        code, out, err = run(["import", "-Users-x-proj"], home=home, claude=claude)
        check("K16 ignore してあれば取り込む", code == 0 and len(read_index(home)) == 2, out + err)
        r2 = subprocess.run(["git", "-C", str(home), "check-ignore", "-q", "06_会話履歴/索引.jsonl"])
        check("K16 取り込んだ中身は Git に出ない", r2.returncode == 0)
else:
    print("git が無いので K16 のテストを飛ばしました")

# ---- K21：ロック・途中で切れる・20秒の打ち切り ----
with tempfile.TemporaryDirectory() as tmp:
    home = make_home(tmp)
    claude = make_claude(tmp)
    run(["import", "-Users-x-proj"], home=home, claude=claude)
    check("K21 import が終わるとロックが消える", not (home / "06_会話履歴" / ".lock").exists())
    newj = claude / "projects" / "-Users-x-proj" / "12121212-0000-0000-0000-000000000000.jsonl"
    newj.write_text(jl(user("ロックの試し LOCKTEST")), encoding="utf-8")
    lock = home / "06_会話履歴" / ".lock"
    lock.write_text("other", encoding="utf-8")
    code, out, err = run(["update", "--quiet"], home=home, claude=claude)
    check("K21 新しいロックがあれば何もせず終わる", code == 0 and out == "" and "当たる会話はありません" in run(["search", "LOCKTEST"], home=home, claude=claude)[1] and lock.exists())
    code, out, err = run(["import", "-Users-x-proj"], home=home, claude=claude)
    check("K21 import もロックが取れなければ何もしない", code == 0 and "動いている" in err and lock.exists())
    old = time.time() - 61 * 60
    os.utime(lock, (old, old))
    code, out, err = run(["update", "--quiet"], home=home, claude=claude)
    check("K21 60分より古いロックは無視して動き、終わったら消える", "新しく 1 件" in out and not lock.exists(), out + err)
    # 壊れた行・途中で切れた末尾
    ipath = home / "06_会話履歴" / "索引.jsonl"
    with open(ipath, "ab") as f:
        f.write(b'{"id": "zzzz", "title": "\xe5\x88\x87')   # 末尾が途中で切れている（改行なし）
    newj2 = claude / "projects" / "-Users-x-proj" / "13131313-0000-0000-0000-000000000000.jsonl"
    newj2.write_text(jl(user("切れた後の追加 AFTERCUT")), encoding="utf-8")
    code, out, err = run(["update", "--quiet"], home=home, claude=claude)
    ids = [r["id"][:8] for r in read_index(home)]
    check("K21 索引の末尾が切れていても、次の会話が正しく入る", code == 0 and "13131313" in ids and "zzzz" not in ids, str(ids))
    check("K21 索引は全部の行が JSON として読める（最後に置き換える）", all(json.loads(x) for x in ipath.read_text(encoding="utf-8").splitlines()))
    # 途中で止まっても、終わった元は sources.json に残る
    pa = claude / "projects" / "-Users-x-proj"
    for nm in ("14141414", "15151515"):
        (pa / (nm + "-0000-0000-0000-000000000000.jsonl")).write_text(jl(user("途中で止まる " + nm)), encoding="utf-8")
    real_process = ci.process_file
    calls = []

    def boom(root, kind, name, path, index, srcfiles, key):
        calls.append(path.name)
        if len(calls) == 2:
            raise RuntimeError("途中で落ちた")
        return real_process(root, kind, name, path, index, srcfiles, key)
    ci.process_file = boom
    try:
        code, out, err = run(["update"], home=home, claude=claude)
    finally:
        ci.process_file = real_process
    sj = json.loads((home / "06_会話履歴" / "sources.json").read_text(encoding="utf-8"))
    check("K21 途中で落ちても、終わった元は sources.json に残り、ロックは消える",
          any(k.endswith(calls[0]) for k in sj["files"]) and not any(k.endswith(calls[1]) for k in sj["files"]) and not lock.exists(), str(calls) + err)
    code, out, err = run(["update"], home=home, claude=claude)
    check("K21 次の update で残りを拾う", "足した 1 件" in out and "[1515" not in out, out + err)
    # 打ち切り
    for nm in ("16161616", "17171717"):
        (pa / (nm + "-0000-0000-0000-000000000000.jsonl")).write_text(jl(user("時間切れ " + nm)), encoding="utf-8")
    ci.UPDATE_BUDGET = 0.0
    try:
        code, out, err = run(["update"], home=home, claude=claude)
    finally:
        ci.UPDATE_BUDGET = 20.0
    check("K21 打ち切り：時間が過ぎたら残りは次回に回す", "足した 0 件" in out and "残り 2 件は次回" in out, out)
    code, out, err = run(["update"], home=home, claude=claude)
    check("K21 打ち切りの残りは次の update で入る", "足した 2 件" in out, out)
    check("K21 UPDATE_BUDGET は20秒", ci.UPDATE_BUDGET == 20.0)

# ---- K21：途中で切れた末尾・K25：日付が変わったら古い md を置き換える（単体） ----
with tempfile.TemporaryDirectory() as tmp:
    home = make_home(tmp)
    (home / "06_会話履歴").mkdir()
    ip = home / "06_会話履歴" / "索引.jsonl"
    ip.write_bytes(b'{"id": "keep1", "title": "x"}\n{"id": "cut", "tit')
    ci.ensure_index_newline(home)
    ci.append_index_row(home, {"id": "next1", "title": "y"})
    check("K21 切れた末尾のあとに足した行が、つながらず読める", sorted(ci.load_index(home)) == ["keep1", "next1"], str(sorted(ci.load_index(home))))
    index = {}
    mk = lambda started: ci.make_conv("dddd4444-0000-0000-0000-000000000000", "chat", "x.zip", "題", [("user", started, "発言")], [], 1, started=started, ended=started)
    ci.write_conv(home, mk("2026-10-01T09:00:00+09:00"), index)
    first_md = home / index["dddd4444-0000-0000-0000-000000000000"]["file"]
    ci.write_conv(home, mk("2026-10-03T09:00:00+09:00"), index)
    names = sorted(p.name for p in (home / "06_会話履歴" / "会話").glob("*.md"))
    check("K25 日付が変わっても md は1つ（自分が書いた古い md を置き換える）", names == ["20261003_dddd4444.md"] and not first_md.exists(), str(names))

# ---- K22：一覧（一時の目印・cwd の名前・このフォルダ）／K23：元が無くなっても残す ----
with tempfile.TemporaryDirectory() as tmp:
    home = make_home(tmp)
    cdir = Path(tmp) / "claude2"
    pj = cdir / "projects"
    selfname = "-Users-x-selfhome"   # 一時の置き場（/var/folders）の名前は「一時フォルダ」の目印に当たるので、cwd で本人のフォルダと分かるようにする
    (pj / selfname).mkdir(parents=True)
    (pj / selfname / "aaaa0001-0000-0000-0000-000000000000.jsonl").write_text(jl(user("このフォルダの会話 SELFCONV", cwd=str(home.resolve()))), encoding="utf-8")
    (pj / "-Users-x-zeta").mkdir(parents=True)
    (pj / "-Users-x-zeta" / "bbbb0001-0000-0000-0000-000000000000.jsonl").write_text(jl(user("ほかの会話 OTHERCONV", cwd="/Users/x/zeta/sub")), encoding="utf-8")
    (pj / "-Users-x-alpha").mkdir(parents=True)
    (pj / "-Users-x-alpha" / "cccc0001-0000-0000-0000-000000000000.jsonl").write_text(
        jl(user("古い cwd", cwd="/old/place")) + jl(user("新しい cwd", cwd="/Users/x/alpha-real")), encoding="utf-8")
    for n in ("-home-x-tmp-job", "C--Users-x-AppData-Local-Temp-abc"):
        (pj / n).mkdir()
        (pj / n / "dddd0001-0000-0000-0000-000000000000.jsonl").write_text(jl(user("一時 TMPONLY")), encoding="utf-8")
    code, out, err = run(["sources"], home=home, claude=cdir)
    lines = [x.strip() for x in out.splitlines() if x.strip()[:1].isdigit()]
    check("K22 このフォルダが先頭・付箋つき・自動では選ばない", lines[0].startswith("1. （このフォルダ） ") and "[未選択]" in lines[0], out)
    check("K22 名前のかわりに cwd（最後のもの）を見せる", any("/Users/x/alpha-real" in x for x in lines) and any("/Users/x/zeta/sub" in x for x in lines) and not any("/old/place" in x for x in lines), out)
    check("K22 -tmp-・AppData-Local-Temp は一覧に出ない（2件を数える）", "TMPONLY" not in out and "-home-x-tmp-job" not in out and "AppData" not in out and "2 件は出していません" in out, out)
    check("K22 フォルダ名から本人のフォルダを見分ける形（英数字以外は -）", ci.encode_folder("/Users/rd/workspace/AI坂田") == "-Users-rd-workspace-AI--")
    code, out, err = run(["import", "/Users/x/zeta/sub"], home=home, claude=cdir)
    check("K22 cwd の名前でも選べる（番号でも、フォルダ名でも）", code == 0 and [r["id"][:8] for r in read_index(home)] == ["bbbb0001"], out + err)
    code, out, err = run(["import", "2"], home=home, claude=cdir)
    check("K22 番号で選ぶ", code == 0 and len(read_index(home)) == 2, out + err)
    # K23：元が無くなっても残す
    sd = pj / "-Users-x-zeta"
    shutil.move(str(sd), str(Path(tmp) / "gone"))
    h_before = {p.name: p.read_bytes() for p in (home / "06_会話履歴" / "会話").glob("*.md")}
    idx_before = read_index(home)
    code, out, err = run(["update"], home=home, claude=cdir)
    check("K23 元の jsonl が無くなっても、索引と読みやすい形は消さない", code == 0 and read_index(home) == idx_before
          and {p.name: p.read_bytes() for p in (home / "06_会話履歴" / "会話").glob("*.md")} == h_before and "[bbbb0001]" in run(["search", "OTHERCONV"], home=home, claude=cdir)[1], out + err)

# ---- K24：チャットの形 ----
with tempfile.TemporaryDirectory() as tmp:
    home = make_home(tmp)
    zdir = home / "03_インプット" / "会話"
    zdir.mkdir(parents=True)
    conv_a = {"uuid": "aaaa1111-0000-0000-0000-000000000001", "name": "一つ目", "created_at": "2026-10-01T01:00:00.123456+09:00",
              "updated_at": "2026-10-01T02:30:00+09:00",
              "chat_messages": [
                  {"sender": "human", "created_at": "2026-10-01T01:00:00.000000Z", "text": "", "content": [{"type": "text", "text": "質問"}, {"type": "tool_use", "text": "TOOLTEXT"}],
                   "attachments": [{"extracted_content": "ATTACH_BODY"}], "files": [{"file_name": "FILES_BODY"}]},
                  {"sender": "assistant", "created_at": "2026-10-01T01:01:00Z", "text": "答え"}]}
    conv_b = {"uuid": "bbbb2222-0000-0000-0000-000000000002", "name": "二つ目", "created_at": "2026-10-02T03:00:00Z", "updated_at": "2026-10-02T03:00:00Z",
              "chat_messages": [{"sender": "human", "text": "古い版"}]}
    conv_b2 = dict(conv_b, name="二つ目（新しい版）", chat_messages=[{"sender": "human", "text": "新しい版"}])
    with zipfile.ZipFile(zdir / "multi.zip", "w") as z:
        z.writestr("part1/conversations.json", json.dumps([conv_a, conv_b], ensure_ascii=False))
        z.writestr("part2/conversations.json", json.dumps([conv_b2], ensure_ascii=False))
        z.writestr("part3/conversations.json", json.dumps({"not": "array"}))
        z.writestr("part4/old_conversations.json.bak", "[]")
    code, out, err = run(["import", "multi.zip"], home=home, claude=Path(tmp) / "none")
    rows = {r["id"][:8]: r for r in read_index(home)}
    check("K24 zip の中の conversations.json を全部読む・同じ uuid は上書き", sorted(rows) == ["aaaa1111", "bbbb2222"] and rows["bbbb2222"]["title"] == "二つ目（新しい版）", str(rows.keys()) + out + err)
    check("K24 配列でない最上位は飛ばして数を出す", "読んだ 2 件・飛ばした 1 件" in out, out)
    mda = (home / rows["aaaa1111"]["file"]).read_text(encoding="utf-8")
    check("K24 content は type: text だけ・attachments と files は読まない", "質問" in mda and "TOOLTEXT" not in mda and "ATTACH_BODY" not in mda and "FILES_BODY" not in mda, mda)
    want = datetime.fromisoformat("2026-10-01T01:00:00+00:00").astimezone().isoformat(timespec="seconds")
    check("K24 時刻は先頭19字を UTC として読む（+09:00 は無視）", rows["aaaa1111"]["started"] == want, rows["aaaa1111"]["started"] + " / " + want)
    check("K24 ファイル名は日付_ID8", rows["aaaa1111"]["file"] == "06_会話履歴/会話/%s_aaaa1111.md" % want[:10].replace("-", ""), rows["aaaa1111"]["file"])
    # 最上位が配列でない conversations.json だけ
    (zdir / "dictonly").mkdir()
    (zdir / "dictonly" / "conversations.json").write_text(json.dumps({"conversations": []}), encoding="utf-8")
    code, out, err = run(["sources"], home=home, claude=Path(tmp) / "none")
    check("K24 配列でないエクスポートは「読めない形」と出す", "dictonly  読めない形" in out, out)

# ---- K27：選んでいない新しい Code のフォルダ ----
with tempfile.TemporaryDirectory() as tmp:
    home = make_home(tmp)
    claude = make_claude(tmp)
    pj = claude / "projects"
    run(["import", "-Users-x-proj"], home=home, claude=claude)
    code, out, err = run(["update", "--quiet"], home=home, claude=claude)
    check("K27 import のあと、いまあるフォルダでは知らせない", code == 0 and out == "", out)
    (pj / "-Users-x-new1").mkdir()
    (pj / "-Users-x-new1" / "e1e1e1e1-0000-0000-0000-000000000000.jsonl").write_text(jl(user("new1")), encoding="utf-8")
    (pj / "-Users-x-new2").mkdir()
    (pj / "-Users-x-new2" / "e2e2e2e2-0000-0000-0000-000000000000.jsonl").write_text(jl(user("new2")), encoding="utf-8")
    code, out, err = run(["update", "--quiet"], home=home, claude=claude)
    check("K27 新しいフォルダが増えたら1行：個数つき", out.strip() == "前の会話：選んでいないフォルダが 2 個あります（『前の会話を取り込んで』で選べます）", out)
    code, out, err = run(["update", "--quiet"], home=home, claude=claude)
    check("K27 同じフォルダでは2回目は知らせない", out == "", out)
    check("K27 新しいフォルダは勝手に足さない", "新しい" not in " ".join(r["title"] for r in read_index(home)) and len(read_index(home)) == 2)
    (pj / "-Users-x-new3").mkdir()
    (pj / "-Users-x-new3" / "e3e3e3e3-0000-0000-0000-000000000000.jsonl").write_text(jl(user("new3")), encoding="utf-8")
    (pj / "-Users-x-proj" / "e4e4e4e4-0000-0000-0000-000000000000.jsonl").write_text(jl(user("増えた会話")), encoding="utf-8")
    code, out, err = run(["update", "--quiet"], home=home, claude=claude)
    check("K27 出力は最大1行（更新の行が先。知らせは次の起動へ）", out.strip().splitlines() == ["会話の索引：新しく 1 件、更新 0 件"], out)
    code, out, err = run(["update", "--quiet"], home=home, claude=claude)
    check("K27 次の起動で知らせる（1個）", "選んでいないフォルダが 1 個" in out and len(out.strip().splitlines()) == 1, out)
    # sources.json に seen_folders が無い古い形：初回は静か
    sj_path = home / "06_会話履歴" / "sources.json"
    sj = json.loads(sj_path.read_text(encoding="utf-8"))
    sj.pop("seen_folders")
    sj_path.write_text(json.dumps(sj), encoding="utf-8")
    code, out, err = run(["update", "--quiet"], home=home, claude=claude)
    check("K27 seen_folders が無いときは、いまあるものを記録して静かに終わる", out == "" and "seen_folders" in json.loads(sj_path.read_text(encoding="utf-8")), out)

# ---- K28：/resume のコピー ----
with tempfile.TemporaryDirectory() as tmp:
    home = make_home(tmp)
    claude = make_claude(tmp)
    pa = claude / "projects" / "-Users-x-proj"
    base = [user("共有の質問 COPYWORD", ts="2026-11-20T01:00:00Z"), asst([{"type": "text", "text": "共有の返事"}], ts="2026-11-20T01:00:05Z")]
    (pa / "c0c0c0c0-0000-0000-0000-000000000000.jsonl").write_text(jl(*base), encoding="utf-8")
    (pa / "c1c1c1c1-0000-0000-0000-000000000000.jsonl").write_text(
        jl(*(base + [user("続きの質問 COPYWORD2", ts="2026-11-21T01:00:00Z")])), encoding="utf-8")
    (pa / "c2c2c2c2-0000-0000-0000-000000000000.jsonl").write_text(jl(user("無関係 COPYWORD", ts="2026-11-22T01:00:00Z")), encoding="utf-8")
    run(["import", "-Users-x-proj"], home=home, claude=claude)
    code, out, err = run(["search", "COPYWORD"], home=home, claude=claude)
    ls = {x.split("[")[1][:8]: x for x in out.splitlines() if "[" in x}
    check("K28 古いほうに（続きの会話あり：新しい ID）", "（続きの会話あり：c1c1c1c1）" in ls.get("c0c0c0c0", ""), out)
    check("K28 新しいほう・無関係な会話には付けない", "続きの会話" not in ls.get("c1c1c1c1", "") and "続きの会話" not in ls.get("c2c2c2c2", ""), out)

# ---- K29：標準出力は UTF-8 ----
with tempfile.TemporaryDirectory() as tmp:
    home = make_home(tmp)
    claude = make_claude(tmp)
    env = dict(os.environ, AI_BUNSHIN_HOME=str(home), CLAUDE_CONFIG_DIR=str(claude), PYTHONIOENCODING="ascii")
    env.pop("CLAUDE_PROJECT_DIR", None)
    r = subprocess.run([sys.executable, os.path.join(HERE, "..", "scripts", "conversation_index.py"), "sources"], env=env, capture_output=True)
    check("K29 出力の文字コードが ascii でも落ちず、UTF-8 で出す", r.returncode == 0 and "取り込める元".encode("utf-8") in r.stdout, str(r.stderr[:200]))
    r = subprocess.run([sys.executable, os.path.join(HERE, "..", "scripts", "conversation_index.py"), "import", "-Users-x-proj"], env=env, capture_output=True)
    md_ = next((home / "06_会話履歴" / "会話").glob("*_aaaaaaaa.md"))
    check("K29 ファイルは UTF-8 で書く", r.returncode == 0 and "T257" in md_.read_bytes().decode("utf-8"))

if fail:
    print("失敗 %d 件" % fail)
    sys.exit(1)
print("会話の索引のテスト：すべて通りました（失敗 0 件）")
