#!/usr/bin/env python3
"""前の会話を、あとから探して呼び出せるようにする（会話の索引。読むだけで、元のファイルは触らない）。

元（読むだけ。消さない・動かさない・書き換えない）
  - Claude Code の会話：~/.claude/projects/<フォルダ>/*.jsonl（そのフォルダの直下だけ。下のフォルダの jsonl は部下の会話なので読まない）
    一時フォルダ（名前に -private-tmp-・-tmp-・scratchpad・-var-folders-・AppData-Local-Temp を含むもの）は、一覧にも出さない
  - claude.ai のチャットのエクスポート：本人のフォルダの 03_インプット/会話/ の *.zip、または展開したフォルダの conversations.json
    （03_インプット には書かない。形は【未確認】。知らない形の会話は飛ばして数を出す）

書き出し先（本人のフォルダの 06_会話履歴/。Git の控えには入れない）
  索引.jsonl・会話/<YYYYMMDD>_<IDの頭8字>.md・sources.json（選んだ元と、元ファイルごとの mtime・size）

コマンド
  sources                          取り込める元の一覧（番号付き）
  import <番号や名前…> | --all     選んだ元を sources.json に足して取り込む
  update [--quiet]                 選んだ元のうち、変わった・増えたファイルだけ作り直す（hook 用。無ければ何も出さない。20秒で打ち切る）
  search <言葉や T0XX…> [--limit N]  索引と本文を探す（言葉が全部入っている会話。日付の新しい順）
  show <IDの頭8字> [--grep 言葉] [--context N] [--summary]  まとめ（1500字まで）と本文。--grep はまとめなしで当たった発言とその前後だけ。--summary はまとめだけ（全体 4000字で切る）

本人のフォルダの見つけ方は update_dashboard.py の find_root() をそのまま使う。見つからなければ何もせず終わる（終了コード 0）。
Claude Code の保存場所は、環境変数 CLAUDE_CONFIG_DIR があればその下の projects、無ければ ~/.claude/projects。
Python 3 の標準ライブラリだけで動く。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

OUT_DIR = "06_会話履歴"
INDEX_NAME = "索引.jsonl"
SOURCES_NAME = "sources.json"
LOCK_NAME = ".lock"
CONV_DIR = "会話"
CHAT_DIR = ("03_インプット", "会話")
SKIP_FOLDER_WORDS = ("-private-tmp-", "-tmp-", "scratchpad", "-var-folders-", "AppData-Local-Temp")
SHOW_LIMIT = 4000
SUMMARY_LIMIT = 1500     # show で出すまとめの上限（超えたら --summary で全部）
UPDATE_BUDGET = 20.0      # update の打ち切り（秒）
LOCK_STALE_SEC = 60 * 60  # これより古いロックは無視する
MASK = "［伏せた］"
SELF_LABEL = "（このフォルダ）"

TASK_RE = re.compile(r"(?<![A-Za-z0-9])T\d{3,4}(?!\d)")
TASK_TERM_RE = re.compile(r"^T\d{3,4}$")

# ---- 伏せる（K8・K19）。数えて、取り込みの最後に出す ----
_masked = [0]


def _sub(rx, repl, text):
    new, n = rx.subn(repl, text)
    _masked[0] += n
    return new


def _keep_mask(prefix_groups):
    """値が既に伏せてあるものは数えず・変えない。"""
    def f(m):
        tail = m.group(len(m.groups()))
        if tail.startswith(MASK):
            return m.group(0)
        _masked[0] += 1
        return "".join(m.group(i) for i in range(1, prefix_groups + 1)) + MASK
    return f


_PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----(?:.*?-----END [A-Z ]*PRIVATE KEY-----|.*\Z)", re.S)
_AUTH_RE = re.compile(r"(Authorization:\s*)\S+(?:[ \t]+\S+)?", re.I)
_BEARER_RE = re.compile(r"(Bearer\s+)\S{8,}")
_WHOLE_RES = [  # 全体を伏せる形
    re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
    re.compile(r"(?<![A-Za-z0-9])(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{8,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"glpat-[A-Za-z0-9_-]{16,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"ya29\.[0-9A-Za-z_-]+"),
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[abpr]-[A-Za-z0-9-]{10,}"),
    re.compile(r"(?<![A-Za-z0-9])ntn_[A-Za-z0-9]{20,}"),
    re.compile(r"(?<![A-Za-z0-9])npm_[A-Za-z0-9]{20,}"),
    re.compile(r"(?<![A-Za-z0-9])shpat_[A-Za-z0-9]{20,}"),
    re.compile(r"ASIA[0-9A-Z]{16}"),
]
_URL_CRED_RE = re.compile(r"(://)[^/\s:@]+:[^/\s@]+(@)")
_QUERY_RE = re.compile(r"([?&](?:token|key|secret|sig|signature)=)[^&\s]+")
_PATH_SECRET_RES = [re.compile(r"(calendar/ical/)\S+"), re.compile(r"(hooks\.slack\.com/services/)\S+")]
# password 類：「password: X」「"password": "X"」「'passwd' : 'X'」「password is X」「パスワードは X」。引用符の中の値は閉じる引用符まで
_PASSWORD_RE = re.compile(r"((?:password|passwd|パスワード)[\"']?\s*[:=：]\s*)(\"[^\"\n]*\"?|'[^'\n]*'?|\S+)", re.I)
_PASSWORD_IS_RE = re.compile(r"((?:password|passwd|パスワード)(?:\s+is\s+|\s*は\s*))([!-~]+)", re.I)
_KEYVAL_RE = re.compile(
    r"((?:(?i:token|secret|api[_-]?key|client_secret))|[A-Z_]*(?:KEY|TOKEN|SECRET|PASSWORD))(\"?'?\s*[:=]\s*\"?'?)(\S{8,})")

# ---- Code の本人の文から取り除くもの（K6） ----
_STRIP_RES = [re.compile(r"<%s>.*?</%s>" % (t, t), re.S) for t in
              ("system-reminder", "bash-stdout", "bash-stderr", "local-command-stdout")]
_BASH_INPUT_RE = re.compile(r"<bash-input>(.*?)</bash-input>", re.S)


def redact(text):
    if not text:
        return text
    text = _sub(_PRIVATE_KEY_RE, MASK, text)
    text = _sub(_AUTH_RE, lambda m: m.group(1) + MASK, text)
    text = _sub(_BEARER_RE, lambda m: m.group(1) + MASK, text)
    for r in _WHOLE_RES:
        text = _sub(r, MASK, text)
    text = _sub(_URL_CRED_RE, lambda m: m.group(1) + MASK + m.group(2), text)
    text = _sub(_QUERY_RE, lambda m: m.group(1) + MASK, text)
    for r in _PATH_SECRET_RES:
        text = _sub(r, lambda m: m.group(1) + MASK, text)
    text = _PASSWORD_RE.sub(_keep_mask(1), text)
    text = _PASSWORD_IS_RE.sub(_keep_mask(1), text)
    return _KEYVAL_RE.sub(_keep_mask(2), text)


_CMD_TAG_RES = {t: re.compile(r"<command-%s>(.*?)</command-%s>" % (t, t), re.S) for t in ("message", "name", "args")}
_OTHER_WRAP_RES = [re.compile(r"<local-command-caveat>.*?</local-command-caveat>", re.S)]


def _fold_slash_command(text):
    """<command-message>…</command-message><command-name>/x</command-name><command-args>…</command-args> を「（コマンド）/x 引数」にする。"""
    found = {t: r.search(text) for t, r in _CMD_TAG_RES.items()}
    if not any(found.values()):
        return text
    name = found["name"].group(1).strip() if found["name"] else ""
    args = found["args"].group(1).strip() if found["args"] else ""
    msg = found["message"].group(1).strip() if found["message"] else ""
    for r in _CMD_TAG_RES.values():
        text = r.sub("", text)
    label = " ".join(x for x in ("（コマンド）" + (name or msg), args) if x)
    return (label + "\n" + text.strip()).strip()


def clean_user_text(text):
    for r in _STRIP_RES + _OTHER_WRAP_RES:
        text = r.sub("", text)
    text = _fold_slash_command(text)
    text = _BASH_INPUT_RE.sub(lambda m: "（コマンド）" + m.group(1).strip(), text)
    return text.strip()


def find_tasks(*texts):
    found = set()
    for t in texts:
        if t:
            found.update(TASK_RE.findall(t))
    return sorted(found)


# ---- 場所 ----
def find_root():
    """本人のフォルダ。update_dashboard.py の find_root() をそのまま使う（見つからなければ None）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        from update_dashboard import find_root as _find_root
    except ImportError:
        return None
    return _find_root()


def claude_projects_dir():
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    base = Path(base) if base else Path.home() / ".claude"
    return base / "projects"


def out_dir(root):
    return root / OUT_DIR


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


# ---- ロック（K21） ----
def acquire_lock(root):
    p = out_dir(root) / LOCK_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, ("%d %s" % (os.getpid(), datetime.now().isoformat())).encode())
            os.close(fd)
            return True
        except FileExistsError:
            try:
                if time.time() - p.stat().st_mtime < LOCK_STALE_SEC:
                    return False
                p.unlink()  # 60分より古いロックは無視する（自分が作ったロックファイルだけ）
            except OSError:
                return False
        except OSError:
            return False
    return False


def release_lock(root):
    try:
        (out_dir(root) / LOCK_NAME).unlink()
    except OSError:
        pass


# ---- 時刻 ----
def to_local_iso(s, utc19=False):
    """ISO 8601 の文字列を、このパソコンの時刻（オフセット付き）にそろえる。読めなければそのまま。
    utc19：先頭19字を UTC として読む（チャットのエクスポート用）。"""
    if not isinstance(s, str) or not s:
        return ""
    if utc19:
        t = s.strip()[:19] + "+00:00"
    else:
        t = s.strip().replace("Z", "+00:00")
        t = re.sub(r"(\.\d+)", lambda m: (m.group(1) + "000000")[:7], t, count=1)  # 小数は6桁にそろえる（Python 3.9 対策）
    try:
        d = datetime.fromisoformat(t)
        if d.tzinfo is None:
            return d.isoformat(timespec="seconds")
        return d.astimezone().isoformat(timespec="seconds")
    except ValueError:
        return s


def date_of(iso):
    return iso[:10] if iso else ""


def short_ts(iso):
    return iso[:19].replace("T", " ") if iso else ""


# ---- Code の jsonl を読む ----
def _text_of_content(content, images=False):
    """content から、文のかたまり（type: text）だけを取り出す。images=True なら image のかたまりは「（画像）」。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and isinstance(b.get("text"), str):
                parts.append(b["text"])
            elif images and b.get("type") == "image":
                parts.append("（画像）")
        return "\n".join(parts)
    return ""


def _is_human_queued(o):
    """type: attachment の queued_command のうち、本人が打った発言（K17）。"""
    a = o.get("attachment")
    if not isinstance(a, dict) or a.get("type") != "queued_command":
        return False
    origin = a.get("origin")
    return (a.get("commandMode") == "prompt" and isinstance(origin, dict) and origin.get("kind") == "human"
            and not a.get("isMeta") and not o.get("isMeta") and isinstance(a.get("prompt"), str))


def parse_code_jsonl(path):
    """1つの jsonl から会話を作る。入れる文が1つも無ければ None。"""
    turns = []          # [role, ts, text, queued]
    summaries = []
    title = custom = ""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            # 速さのための足切り：必要な種類の行だけ JSON として読む（空白の有無に左右されない言葉で見る）
            if ('"user"' not in line and '"assistant"' not in line and '"ai-title"' not in line
                    and "custom-title" not in line and "queued_command" not in line):
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if not isinstance(o, dict):
                continue
            t = o.get("type")
            if t == "ai-title":
                if isinstance(o.get("aiTitle"), str) and o["aiTitle"].strip():
                    title = o["aiTitle"].strip()
                continue
            if t == "custom-title":
                if isinstance(o.get("customTitle"), str) and o["customTitle"].strip():
                    custom = o["customTitle"].strip()
                continue
            if o.get("isSidechain"):
                continue
            if t == "attachment":
                if _is_human_queued(o):
                    a = o["attachment"]
                    text = redact(clean_user_text(a["prompt"]))
                    ts = to_local_iso(o.get("timestamp") or a.get("timestamp"))
                    if text and not text.startswith("<task-notification>"):
                        turns.append(["user", ts, text, True])
                continue
            if t not in ("user", "assistant"):
                continue
            msg = o.get("message")
            content = msg.get("content") if isinstance(msg, dict) else None
            ts = to_local_iso(o.get("timestamp"))
            if t == "user":
                if o.get("isCompactSummary"):                       # ① まとめ
                    s = redact(_STRIP_RES[0].sub("", _text_of_content(content)).strip())   # 先頭の <system-reminder>…</system-reminder> は取り除く
                    if s:
                        summaries.append(s)
                    continue
                if o.get("isMeta"):                                 # ② 入れない
                    continue
                raw = _text_of_content(content, images=True).strip()
                if raw.startswith("<task-notification>"):           # ③ 入れない
                    continue
                text = redact(clean_user_text(raw))                 # ④ 本人の発言
                if text:
                    turns.append(["user", ts, text, False])
            else:
                text = redact(_text_of_content(content).strip())
                if text:
                    turns.append(["ai", ts, text, False])
    # queued_command の発言が、近くの user 行にも同じ文であれば1つにする
    kept = []
    for i, tr in enumerate(turns):
        if tr[3]:
            near = turns[max(0, i - 5):i] + turns[i + 1:i + 6]
            if any((not x[3]) and x[0] == "user" and x[2] == tr[2] for x in near):
                continue
        kept.append((tr[0], tr[1], tr[2]))
    if not kept and not summaries:
        return None
    user_count = sum(1 for x in kept if x[0] == "user")
    return make_conv(Path(path).stem, "code", Path(path).parent.name, custom or title, kept, summaries, user_count)


def make_conv(cid, kind, source, title, turns, summaries, user_count, started=None, ended=None):
    # AI の返事は、道具を呼ぶたびに行が分かれるので、続いたら1つにまとめる（本人の発言はまとめない）
    merged = []
    for role, ts, text in turns:
        if role == "ai" and merged and merged[-1][0] == "ai":
            merged[-1] = (role, merged[-1][1], merged[-1][2] + "\n\n" + text)
        else:
            merged.append((role, ts, text))
    stamps = [ts for _, ts, _ in turns if ts]
    first_user = next((x[2] for x in turns if x[0] == "user"), "")
    first = re.sub(r"\s+", " ", first_user)[:80]
    title = redact(title).strip() if title else ""
    if not title:
        title = first[:30] or "（題なし）"
    all_text = [title] + [x[2] for x in turns] + summaries
    return {
        "id": cid, "kind": kind, "source": source,
        "started": started or (min(stamps) if stamps else ""),
        "ended": ended or (max(stamps) if stamps else ""),
        "title": title, "tasks": find_tasks(*all_text), "first": first,
        "has_summary": bool(summaries), "messages": user_count,
        "turns": merged, "summaries": summaries,
    }


# ---- チャットのエクスポートを読む ----
def _chat_text(m):
    t = m.get("text")
    if isinstance(t, str) and t.strip():
        return t
    return _text_of_content(m.get("content"))   # type: text だけ（attachments・files は読まない）


def load_chat_json(path, strict=False):
    """zip（名前の最後が conversations.json のもの全部）か conversations.json を読む。
    (会話のリスト, 読めなかった・配列でなかったものの数) を返す。strict なら、ファイルが開けない（OSError・壊れた zip）ときは例外を出す。"""
    p = Path(path)
    raws = []
    try:
        if p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as z:
                for n in sorted(z.namelist()):
                    if n.rsplit("/", 1)[-1] == "conversations.json":
                        raws.append(z.read(n))
        else:
            raws.append(p.read_bytes())
    except (OSError, zipfile.BadZipFile):
        if strict:
            raise
        return [], 1
    if not raws:
        return [], 1
    items, bad = [], 0
    for raw in raws:
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            bad += 1
            continue
        if isinstance(data, list):
            items.extend(data)
        else:
            bad += 1
    return items, bad


def parse_chat(path, source):
    """チャットのエクスポートから (会話のリスト, 飛ばした数) を返す。形が知らないものは飛ばす。同じ uuid は後のもので上書き。
    ファイルが開けないときは OSError（壊れた zip は BadZipFile）を出す。"""
    data, skipped = load_chat_json(path, strict=True)
    convs = {}
    for c in data:
        try:
            conv = _chat_conv(c, source)
        except Exception:
            conv = None
        if conv is None:
            skipped += 1
        else:
            convs[conv["id"]] = conv
    return list(convs.values()), skipped


def _chat_countable(c):
    """sources・import の一覧用：読める会話か（伏せる・発言の組み立てはしない）。"""
    if not isinstance(c, dict) or not isinstance(c.get("uuid"), str) or not c["uuid"]:
        return False
    msgs = c.get("chat_messages")
    if not isinstance(msgs, list):
        return False
    return any(isinstance(m, dict) and m.get("sender") in ("human", "assistant") and _chat_text(m).strip() for m in msgs)


def _chat_conv(c, source):
    if not isinstance(c, dict) or not isinstance(c.get("uuid"), str) or not c["uuid"]:
        return None
    msgs = c.get("chat_messages")
    if not isinstance(msgs, list):
        return None
    turns, user_count = [], 0
    for m in msgs:
        if not isinstance(m, dict):
            continue
        sender = m.get("sender")
        if sender not in ("human", "assistant"):
            continue
        text = redact(_chat_text(m).strip())
        if not text:
            continue
        role = "user" if sender == "human" else "ai"
        if role == "user":
            user_count += 1
        turns.append((role, to_local_iso(m.get("created_at"), utc19=True), text))
    if not turns:
        return None
    name = c.get("name") if isinstance(c.get("name"), str) else ""
    return make_conv(c["uuid"], "chat", source, name, turns, [], user_count,
                     started=to_local_iso(c.get("created_at"), utc19=True) or None,
                     ended=to_local_iso(c.get("updated_at"), utc19=True) or None)


# ---- 読みやすい形（md） ----
def _esc(text):
    return re.sub(r"(?m)^(#{2,3} )", r"\\\1", text)


def conv_filename(conv):
    d = date_of(conv["started"]).replace("-", "") or "00000000"
    return "%s_%s.md" % (d, re.sub(r"[^A-Za-z0-9-]", "_", conv["id"])[:8])


def render_md(conv):
    L = ["# " + conv["title"], "",
         "- ID: " + conv["id"],
         "- 種類: " + ("Code" if conv["kind"] == "code" else "チャット"),
         "- 元: " + conv["source"],
         "- 期間: %s 〜 %s" % (short_ts(conv["started"]), short_ts(conv["ended"])),
         "- タスク: " + (", ".join(conv["tasks"]) or "なし"),
         "- 本人の発言数: %d" % conv["messages"], ""]
    if conv["summaries"]:
        L += ["## まとめ", ""]
        L.append("\n\n---\n\n".join(_esc(s) for s in conv["summaries"]))
        L.append("")
    L += ["## 会話", ""]
    for i, (role, ts, text) in enumerate(conv["turns"], 1):
        L += ["### [%d] %s %s" % (i, "本人" if role == "user" else "AI", short_ts(ts)), "", _esc(text), ""]
    return "\n".join(L)


_TURN_RE = re.compile(r"(?m)^### \[(\d+)\] (本人|AI)([^\n]*)\n")


def parse_md(text):
    """読みやすい形を読み戻す。(見出し部分, まとめ, [(番号, 役, 本文, 時刻)])"""
    head, _, rest = text.partition("\n## 会話\n")
    summary = ""
    if "\n## まとめ\n" in head:
        head, _, summary = head.partition("\n## まとめ\n")
        summary = summary.strip()
    turns = []
    ms = list(_TURN_RE.finditer(rest))
    for k, m in enumerate(ms):
        end = ms[k + 1].start() if k + 1 < len(ms) else len(rest)
        turns.append((int(m.group(1)), m.group(2), rest[m.end():end].strip(), m.group(3).strip()))
    return head, summary, turns


def write_conv(root, conv, index):
    """会話の md を書き、索引（id → 行）を更新して、索引.jsonl の末尾にも足す。
    ファイル名が変わって古い md が残るときは、自分が書いたものだけ消す。"""
    rel = "%s/%s/%s" % (OUT_DIR, CONV_DIR, conv_filename(conv))
    target = root / rel
    old = index.get(conv["id"])
    atomic_write(target, render_md(conv))
    if old and old.get("file") and old["file"] != rel:
        stale = root / old["file"]
        conv_root = (out_dir(root) / CONV_DIR).resolve()
        try:
            if stale.resolve().parent == conv_root and stale.exists():
                stale.unlink()  # 自分が書いた md の置き換えだけ（元の jsonl・zip には触らない）
        except OSError:
            pass
    row = {
        "id": conv["id"], "kind": conv["kind"], "source": conv["source"],
        "started": conv["started"], "ended": conv["ended"], "title": conv["title"],
        "tasks": conv["tasks"], "first": conv["first"], "has_summary": conv["has_summary"],
        "messages": conv["messages"], "file": rel,
    }
    index[conv["id"]] = row
    append_index_row(root, row)


def load_index(root):
    """索引.jsonl を読む。壊れた行は飛ばす。同じ id は後の行が勝つ。"""
    p = out_dir(root) / INDEX_NAME
    rows = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and r.get("id"):
                rows[r["id"]] = r
    return rows


def append_index_row(root, row):
    p = out_dir(root) / INDEX_NAME
    with open(p, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def ensure_index_newline(root):
    """途中で切れた行が末尾に残っていても、次の行がつながらないようにする。"""
    p = out_dir(root) / INDEX_NAME
    try:
        if p.exists() and p.stat().st_size:
            with open(p, "rb") as f:
                f.seek(-1, os.SEEK_END)
                if f.read(1) != b"\n":
                    with open(p, "ab") as g:
                        g.write(b"\n")
    except OSError:
        pass


def save_index(root, index):
    """索引を並べ直して、一時ファイルに書いてから置き換える。"""
    rows = sorted(index.values(), key=lambda r: (r.get("started", ""), r["id"]))
    atomic_write(out_dir(root) / INDEX_NAME, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


# ---- 元の一覧 ----
def last_cwd(files):
    """新しい jsonl の終わりのほうから、最後の cwd を探す（見つからなければ空）。"""
    for p in sorted(files, key=lambda x: x.stat().st_mtime, reverse=True)[:3]:
        try:
            with open(p, "rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 262144))
                chunk = f.read().decode("utf-8", errors="replace")
        except OSError:
            continue
        found = re.findall(r'"cwd"\s*:\s*"((?:[^"\\]|\\.)*)"', chunk)
        if found:
            try:
                return json.loads('"%s"' % found[-1])
            except ValueError:
                return found[-1]
    return ""


def list_code_folders():
    """([(名前, パス, jsonl のリスト)] 名前順, 一時フォルダの数)。"""
    base = claude_projects_dir()
    out, skipped = [], 0
    if not base.is_dir():
        return out, 0
    for d in sorted(base.iterdir(), key=lambda x: x.name):
        if not d.is_dir():
            continue
        if any(w in d.name for w in SKIP_FOLDER_WORDS):
            skipped += 1
            continue
        files = sorted(p for p in d.glob("*.jsonl") if p.is_file())
        out.append((d.name, d, files))
    return out, skipped


def encode_folder(path):
    """Claude Code がフォルダ名にするときの形（英数字以外は -）。"""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def list_chat_exports(root):
    """[(名前, 相対パス, 絶対パス)] 03_インプット/会話/ の zip と conversations.json のあるフォルダ。"""
    base = root.joinpath(*CHAT_DIR)
    out = []
    if not base.is_dir():
        return out
    for p in sorted(base.iterdir(), key=lambda x: x.name):
        rel = "/".join(CHAT_DIR) + "/" + p.name
        if p.is_file() and p.suffix.lower() == ".zip":
            out.append((p.name, rel, p))
        elif p.is_dir() and (p / "conversations.json").is_file():
            out.append((p.name, rel + "/conversations.json", p / "conversations.json"))
        elif p.is_file() and p.name == "conversations.json":
            out.append((CHAT_DIR[-1], rel, p))
    return out


def stat_sig(p):
    st = os.stat(p)
    return {"mtime": st.st_mtime_ns, "size": st.st_size}


def load_sources(root):
    p = out_dir(root) / SOURCES_NAME
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    d.setdefault("sources", [])
    d.setdefault("files", {})
    return d


def save_sources(root, d):
    atomic_write(out_dir(root) / SOURCES_NAME, json.dumps(d, ensure_ascii=False, indent=1) + "\n")


def _fmt_date(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def build_catalog(root):
    """sources / import で使う番号付きの一覧。このフォルダ → ほかの Code（名前順）→ チャット（名前順）。"""
    cat = []
    folders, skipped = list_code_folders()
    mine = {encode_folder(root), encode_folder(str(root).rstrip("/\\"))}
    for name, d, files in folders:
        last = max((p.stat().st_mtime for p in files), default=None)
        cwd = last_cwd(files) if files else ""
        is_self = name in mine or bool(cwd and Path(cwd) == root)
        cat.append({"kind": "code", "name": name, "path": str(d), "count": len(files), "last": last,
                    "label": cwd or name, "self": is_self})
    cat.sort(key=lambda c: (not c["self"], c["name"]))
    for name, rel, ap in list_chat_exports(root):
        data, bad = load_chat_json(ap)
        stamps, n = [], 0
        for c in data:
            try:
                ok = _chat_countable(c)
            except Exception:
                ok = False
            if ok:
                n += 1
                for k in ("created_at", "updated_at"):
                    if isinstance(c.get(k), str):
                        stamps.append(c[k][:10])
        cat.append({"kind": "chat", "name": name, "path": rel, "count": n, "label": name, "self": False,
                    "period": (min(stamps), max(stamps)) if stamps else None, "bad": (not data and bad > 0)})
    for i, c in enumerate(cat, 1):
        c["no"] = i
    return cat, skipped


def selected_keys(src):
    return {(s["kind"], s["name"], s["path"]) for s in (src or {}).get("sources", [])}


# ---- 取り込み ----
def process_file(root, kind, name, path, index, srcfiles, key):
    """元ファイル1つから会話を作って書く。(足した数, 更新した数, 飛ばした数, 読めたか) を返す。"""
    added = updated = skipped = 0
    ids = []
    try:
        sig = stat_sig(path)     # 読む前の mtime・size を記録する（読んでいる間に変わっても、次の起動で拾える）
        if kind == "code":
            convs = []
            conv = parse_code_jsonl(path)
            if conv:
                convs.append(conv)
            else:
                skipped = 1
        else:
            convs, skipped = parse_chat(path, name)
    except (OSError, zipfile.BadZipFile):
        # 読めなかった元は、処理済みとして記録しない（次の起動でやり直す）
        return added, updated, skipped, False
    for conv in convs:
        if conv["id"] in index:
            updated += 1
        else:
            added += 1
        write_conv(root, conv, index)
        ids.append(conv["id"])
    srcfiles[key] = dict(sig, ids=ids)
    return added, updated, skipped, True


def scan_source(root, s):
    """選んだ元1つの、いま読めるファイル [(key, kind, name, path)]。無くなった元は何もしない（作った分は残す）。"""
    if s["kind"] == "code":
        d = Path(s["path"])
        if not d.is_dir():
            return []
        return [(str(p), "code", s["name"], p) for p in sorted(d.glob("*.jsonl")) if p.is_file()]
    ap = root / s["path"]
    return [(s["path"], "chat", s["name"], ap)] if ap.is_file() else []


def run_sync(root, src, budget=None):
    """変わった・増えたファイルだけ作り直す。元1本ごとに sources.json を更新（書き込みは1秒に1回までと、最後）。
    budget 秒を過ぎたら、残りは次の起動に回す。"""
    ensure_index_newline(root)
    index = load_index(root)
    totals = {"added": 0, "updated": 0, "skipped": 0, "files": 0, "masked": 0, "left": 0, "failed": 0}
    _masked[0] = 0
    t0 = time.monotonic()
    last_save = [t0]
    cut = False
    try:
        for s in src["sources"]:
            for key, kind, name, path in scan_source(root, s):
                try:
                    sig = stat_sig(path)
                except OSError:
                    continue
                old = src["files"].get(key)
                if old and old.get("mtime") == sig["mtime"] and old.get("size") == sig["size"]:
                    continue
                if cut or (budget is not None and time.monotonic() - t0 >= budget):
                    cut = True
                    totals["left"] += 1
                    continue
                a, u, k, ok = process_file(root, kind, name, path, index, src["files"], key)
                if not ok:
                    totals["failed"] += 1
                    continue
                totals["added"] += a
                totals["updated"] += u
                totals["skipped"] += k
                totals["files"] += 1
                if time.monotonic() - last_save[0] >= 1.0:
                    save_sources(root, src)
                    last_save[0] = time.monotonic()
    finally:
        totals["masked"] = _masked[0]
        save_index(root, index)
        save_sources(root, src)
    return totals


# ---- Git の控えに入らないことの確認（K16・K31） ----
def _git_dir_above(root):
    for x in [root, *root.parents]:
        if (x / ".git").exists():
            return True
    return False


def git_problem(root):
    """止めるべきなら理由（"not_ignored" か "unknown"）、進んでよければ None。
    Git の管理下（本人のフォルダかその上に .git がある）で、06_会話履歴/ が ignore されていなければ止める。
    確かめられないときも止める。Git が無い・.git が無いときだけ進む。"""
    has_git_dir = _git_dir_above(root)
    try:
        r = subprocess.run(["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
                           capture_output=True, text=True, timeout=15)
        inside = r.returncode == 0 and r.stdout.strip() == "true"
    except (OSError, subprocess.SubprocessError):
        return "unknown" if has_git_dir else None     # git が動かない：.git があるなら確かめられないので止める
    if not inside:
        return "unknown" if has_git_dir else None     # git が「リポジトリでない」と言っても、.git があれば（壊れている）止める
    try:
        r = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", OUT_DIR + "/"],
                           capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if r.returncode == 0:
        return None
    return "not_ignored" if r.returncode == 1 else "unknown"


# ---- コマンド ----
def cmd_sources(root, args):
    src = load_sources(root)
    sel = selected_keys(src)
    cat, skipped = build_catalog(root)
    print("取り込める元（番号で選ぶ：import <番号>）")
    print("■ Claude Code の会話（フォルダごと）")
    code = [c for c in cat if c["kind"] == "code"]
    for c in code:
        mark = "選択済" if ("code", c["name"], c["path"]) in sel else "未選択"
        label = (SELF_LABEL + " " if c["self"] else "") + c["label"]
        print("  %d. %s  会話 %d 件  最後 %s  [%s]" % (c["no"], label, c["count"], _fmt_date(c["last"]) if c["last"] else "-", mark))
    if not code:
        print("  （なし）")
    print("■ チャットのエクスポート（%s に zip か展開したフォルダを置く）" % "/".join(CHAT_DIR))
    chat = [c for c in cat if c["kind"] == "chat"]
    for c in chat:
        mark = "選択済" if ("chat", c["name"], c["path"]) in sel else "未選択"
        if c["bad"]:
            print("  %d. %s  読めない形です（conversations.json が見つからない）  [%s]" % (c["no"], c["name"], mark))
        else:
            per = "%s〜%s" % c["period"] if c["period"] else "-"
            print("  %d. %s  会話 %d 件  %s  [%s]" % (c["no"], c["name"], c["count"], per, mark))
    if not chat:
        print("  （なし）")
    if skipped:
        print("（一時フォルダ（tmp・scratchpad）の %d 件は出していません）" % skipped)
    return 0


def _pick(cat, token):
    if token.isdigit():
        return [c for c in cat if c["no"] == int(token)]
    exact = [c for c in cat if token in (c["name"], c["label"])]
    return exact or [c for c in cat if token in c["name"] or token in c["label"]]


def cmd_import(root, args):
    prob = git_problem(root)
    if prob:
        why = ("%s/ が控えから外れていません" % OUT_DIR) if prob == "not_ignored" else "%s/ が控えから外れているか確かめられません（Git が壊れているかもしれません）" % OUT_DIR
        print("取り込まずに止めました：この本人のフォルダは Git の管理下で、%s。"
              "会話の中身が Git に入らないよう、先に .gitignore に1行足してください：\n"
              "  ! cd \"%s\" && printf '\\n%s/\\n' >> .gitignore" % (why, root, OUT_DIR), file=sys.stderr)
        return 1
    cat, _ = build_catalog(root)
    chosen, bad = [], 0
    if args.all:
        chosen = list(cat)
    for tok in args.names:
        hit = _pick(cat, tok)
        if len(hit) != 1:
            print("「%s」は%s" % (tok, "見つかりません" if not hit else "%d 件に当たりました。番号で選んでください" % len(hit)), file=sys.stderr)
            bad += 1
            continue
        chosen.append(hit[0])
    if not chosen:
        print("取り込む元を選んでください（import <番号や名前> か import --all）", file=sys.stderr)
        return 1
    if not acquire_lock(root):
        print("ほかの取り込みが動いているようです。少し待ってからもう一度どうぞ", file=sys.stderr)
        return 0
    try:
        src = load_sources(root) or {"version": 1, "sources": [], "files": {}}
        have = selected_keys(src)
        for c in chosen:
            k = (c["kind"], c["name"], c["path"])
            if k not in have:
                src["sources"].append({"kind": c["kind"], "name": c["name"], "path": c["path"]})
                have.add(k)
        # いま見えているフォルダは「知っているもの」にする（update が選ばなかったフォルダを毎回知らせないため）
        src["seen_folders"] = sorted({c["name"] for c in cat if c["kind"] == "code"})
        t = run_sync(root, src)
    finally:
        release_lock(root)
    print("取り込み：元 %d 件を選び、会話を %d 件足し・%d 件更新 → %s/" % (len(chosen), t["added"], t["updated"], OUT_DIR))
    print("読んだ %d 件・飛ばした %d 件・伏せた %d 箇所" % (t["added"] + t["updated"], t["skipped"], t["masked"]))
    return 1 if bad else 0


def cmd_update(root, args):
    src = load_sources(root)
    if src is None:
        return 0
    if not acquire_lock(root):
        return 0
    try:
        t = run_sync(root, src, budget=UPDATE_BUDGET)
        line = ""
        if args.quiet:
            if t["added"] or t["updated"]:
                line = "会話の索引：新しく %d 件、更新 %d 件" % (t["added"], t["updated"])
        else:
            line = "更新：足した %d 件・更新 %d 件・読んだファイル %d・飛ばした %d 件・伏せた %d 箇所" % (
                t["added"], t["updated"], t["files"], t["skipped"], t["masked"])
            if t["left"]:
                line += "（時間切れ：残り %d 件は次回）" % t["left"]
        had_seen = "seen_folders" in src
        notice = _unselected_notice(src)
        if line:
            print(line)
        if notice:
            if not (args.quiet and line):       # 出力は最大1行：更新の行を出したときは、次の起動に回す
                print(notice[0])
                src["seen_folders"] = sorted(set(src.get("seen_folders", [])) | set(notice[1]))
                save_sources(root, src)
        elif not had_seen:
            save_sources(root, src)
    finally:
        release_lock(root)
    return 0


def _unselected_notice(src):
    """選んでいない新しい Code のフォルダが増えたときの1行（K27）。(文, 新しいフォルダ名) か None。"""
    folders, _ = list_code_folders()
    current = [name for name, _, files in folders if files]
    if "seen_folders" not in src:
        src["seen_folders"] = sorted(current)   # 初めて見たときは、いまあるものを「知っているもの」にする（知らせない）
        return None
    chosen = {s["name"] for s in src["sources"] if s["kind"] == "code"}
    seen = set(src["seen_folders"])
    new = [n for n in current if n not in chosen and n not in seen]
    if not new:
        return None
    return ("前の会話：選んでいないフォルダが %d 個あります（『前の会話を取り込んで』で選べます）" % len(new), new)


def _count_hits(text, term):
    if TASK_TERM_RE.match(term):
        return len(re.findall(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?!\d)", text))
    return text.lower().count(term.lower())


def _fingerprints(text):
    """本人の発言の（時刻, 文）の集まり。/resume のコピーは同じ発言を持つ。"""
    _, _, turns = parse_md(text)
    return {(t[3], t[2]) for t in turns if t[1] == "本人" and t[3]}


def cmd_search(root, args):
    terms = [t for t in args.terms if t.strip()]
    index = load_index(root)
    hits = []
    for r in index.values():
        p = root / r.get("file", "")
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        counts = [_count_hits(text, t) for t in terms]
        if all(counts):
            hits.append((r, sum(counts), _fingerprints(text)))
    hits.sort(key=lambda x: (x[0].get("started", ""), x[0]["id"]), reverse=True)
    if not hits:
        print("当たる会話はありません：" + " ".join(terms))
        return 0
    # 同じ発言をもつ会話が2つ以上あるとき、古いほうに「続きの会話あり」を付ける（K28）
    owners = {}
    for i, h in enumerate(hits):
        for fp in h[2]:
            owners.setdefault(fp, []).append(i)
    follow = {}
    for i, h in enumerate(hits):       # hits は新しい順。i が小さいほど新しい
        newer = {j for fp in h[2] for j in owners[fp] if j < i}
        if newer:
            follow[i] = min(newer)
    limit = max(1, args.limit)
    for i, (r, n, _) in enumerate(hits[:limit]):
        note = "  （続きの会話あり：%s）" % hits[follow[i]][0]["id"][:8] if i in follow else ""
        print("%s  %s  [%s]  当たり %d%s" % (date_of(r.get("started", "")) or "----------", r.get("title", ""), r["id"][:8], n, note))
    if len(hits) > limit:
        print("…ほか %d 件（--limit で増やせます）" % (len(hits) - limit))
    return 0


def cmd_show(root, args):
    index = load_index(root)
    pre = args.id.lower()
    cand = [r for r in index.values() if r["id"].lower().startswith(pre)]
    if not pre or not cand:
        print("その ID の会話はありません：" + args.id, file=sys.stderr)
        return 1
    if len(cand) > 1:
        print("複数に当たりました。ID をもう少し長く：", file=sys.stderr)
        for r in cand:
            print("  %s  %s" % (r["id"][:12], r.get("title", "")), file=sys.stderr)
        return 1
    r = cand[0]
    try:
        text = (root / r["file"]).read_text(encoding="utf-8", errors="replace")
    except OSError:
        print("読みやすい形のファイルが見つかりません：" + r.get("file", ""), file=sys.stderr)
        return 1
    _, summary, turns = parse_md(text)
    head = ["# %s" % r["title"],
            "ID %s ／ %s 〜 %s ／ %s" % (r["id"][:8], short_ts(r.get("started", "")), short_ts(r.get("ended", "")), r["file"]), ""]
    if args.summary:       # まとめだけを全部（4000字で切る）
        body = "\n".join(head + ["## まとめ", summary or "（まとめはありません）"])
        if len(body) > SHOW_LIMIT:
            body = body[:SHOW_LIMIT] + "\n…（%d字で切りました）" % SHOW_LIMIT
        print(body)
        return 0
    head_text = "\n".join(head)
    if summary and not args.grep:     # --grep のときは、まとめを出さず本文だけ
        sm = summary
        if len(sm) > SUMMARY_LIMIT:
            sm = sm[:SUMMARY_LIMIT] + "\n…（まとめの続きは --summary で）"
        head_text += "\n## まとめ\n" + sm + "\n"
    out = []
    n = len(turns)

    def fmt(t):
        return "### [%d] %s\n%s\n" % (t[0], t[1], t[2])

    if args.grep:
        idx = [i for i, t in enumerate(turns) if _count_hits(t[2], args.grep) > 0]
        if not idx:
            out.append("「%s」に当たる発言はありません。" % args.grep)
        else:
            keep = set()
            for i in idx:
                keep.update(range(max(0, i - args.context), min(n, i + args.context + 1)))
            out.append("## 「%s」に当たった発言 %d 件（前後 %d 件つき）" % (args.grep, len(idx), args.context))
            prev = None
            for i in sorted(keep):
                if prev is not None and i != prev + 1:
                    out.append("…")
                out.append(fmt(turns[i]))
                prev = i
    else:
        if n <= 10:
            out.append("## 会話（全 %d 件）" % n)
            out += [fmt(t) for t in turns]
        else:
            out.append("## 会話（最初の5件と最後の5件。全 %d 件）" % n)
            out += [fmt(t) for t in turns[:5]]
            out.append("…（途中 %d 件は省略。--grep で探せます）" % (n - 10))
            out += [fmt(t) for t in turns[-5:]]
    body = "\n".join(out)
    room = max(0, SHOW_LIMIT - len(head_text) - 1)      # 全体 4000字のうち、まとめの残りを本文に使う
    if len(body) > room:
        body = body[:room] + "\n…（%d字で切りました。続きは --grep <言葉> で絞ってください）" % SHOW_LIMIT
    print(head_text + "\n" + body)
    return 0


def build_parser():
    ap = argparse.ArgumentParser(prog="conversation_index.py", description="前の会話の索引（読むだけ）")
    sp = ap.add_subparsers(dest="cmd")
    sp.add_parser("sources", help="取り込める元の一覧")
    p = sp.add_parser("import", help="選んだ元を取り込む")
    p.add_argument("names", nargs="*", help="番号かフォルダ・ファイルの名前")
    p.add_argument("--all", action="store_true", help="一覧の全部")
    p = sp.add_parser("update", help="変わったファイルだけ作り直す")
    p.add_argument("--quiet", action="store_true")
    p = sp.add_parser("search", help="会話を探す")
    p.add_argument("terms", nargs="+")
    p.add_argument("--limit", type=int, default=20)
    p = sp.add_parser("show", help="会話を読む")
    p.add_argument("id")
    p.add_argument("--grep", default="")
    p.add_argument("--context", type=int, default=1)
    p.add_argument("--summary", action="store_true", help="まとめだけを全部出す")
    return ap


def main(argv=None):
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "import":
        # Code のフォルダ名は「-Users-…」のように - で始まる。オプションと間違えないよう、知っているオプション以外は名前として渡す
        flags = [a for a in argv[1:] if a in ("--all", "-h", "--help")]
        names = [a for a in argv[1:] if a not in ("--all", "-h", "--help", "--")]
        argv = ["import"] + flags + ["--"] + names
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return 0
    is_update = args.cmd == "update"
    quiet = is_update and args.quiet
    try:
        root = find_root()
        if root is None:
            if not is_update:
                print("本人のフォルダ（00_タスク管理/data/tasks.json がある場所）が見つかりません", file=sys.stderr)
            return 0
        return {"sources": cmd_sources, "import": cmd_import, "update": cmd_update,
                "search": cmd_search, "show": cmd_show}[args.cmd](root, args)
    except Exception as e:  # update --quiet は hook から呼ばれるので、何があっても起動を止めない
        if quiet:
            return 0
        print("エラー：%s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
