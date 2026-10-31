#!/usr/bin/env python3
"""前の版（4560a92）の見張りの判定（ng_guard.py から読む。単独では動かさない）。

T058 の決め（2026-10-31 坂田さん「範囲を絞って終える」）：見張りは「前の版より悪くしない」。前の版の文字の規則を、
すべてのコマンドに当てる。ng_guard.py は、この判定で止まったものを、R1〜R4 の通す側（構造で読み切れて、行き先が
守っているものの外だと確かめられた形）のときだけ通す。旗（R1_NO_NAMES・R2_FIND・SKIP_03・SKIP_PLUGIN_COPY）は、
その確かめのために、前の版の判定から R1〜R4 の当たり方だけを外して判定し直すためのもの。
前の版から変えたのは、旗と、長さの2乗になる探し方（結果は同じ）と、記録（owners.json）を書かないことだけ。
"""
import glob
import json
import os
import re
import shlex
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

# コマンドとして実行される位置：行頭・; & | ( ` $( { の後、then/do/else/eval/xargs/env/sudo などの後、
# bash -c "…"・bash -lc '…'・eval "…" の中身の先頭。/bin/rm のようなパス付きも同じに扱う。
# grep rm のように引数として出てくるだけのものは止めない
B = (r"(?:^|\n|[;&|(`{]|\$\(|"
     r"\b(?:bash|sh|zsh)\s+-\w*c\s+[\"']|\beval\s+[\"']?|"
     r"\b(?:then|do|else|xargs|env|nohup|time|exec|command|nice|sudo|eval)\s+(?:-\S+\s+)*)"
     r"\s*(?:(?:\.{0,2}/)?(?:[\w.-]+/)+)?")
E = r"(?=$|[\s;&|)`'\"])"


R1_NO_NAMES = False       # R1：外のセッションで、名前の部分一致で本人のフォルダを当てない
R2_FIND = False           # R2：find の -exec の後ろが読むだけのコマンドなら、起点を「動かす・消す」とみなさない
SKIP_03 = False           # R3：03_インプット を文字の並びで見る規則を外す（構造で確かめた後だけ）
SKIP_PLUGIN_COPY = False  # プラグインのコピーを文字の並びで見る規則を外す（構造で確かめた後だけ）


def seq(*pats, line=True):
    """「pats[0] のあとに pats[1] …」が（line=True なら同じ行に）あるか。前の版の `a[^\\n]*b` と同じ結果を、前から1回ずつ探して出す。"""
    rxs = [re.compile(p) for p in pats]

    def match(text):
        for seg in (text.split("\n") if line else (text,)):
            pos = 0
            for rx in rxs:
                m = rx.search(seg, pos)
                if not m:
                    break
                pos = m.end()
            else:
                return True
        return False
    match.pats = pats
    return match


def cmd(words):
    return B + r"(?:" + words + r")" + E


BASH_RULES = [
    ("削除", cmd(r"rm|rmdir|unlink|shred|trash|srm|truncate")),
    ("削除", seq(r"\bfind\b", r"\s-(?:delete\b|(?:exec|execdir|ok|okdir)\s+(?:\S*/)?rm\b)")),
    ("削除", seq(B + r"zip(?=\s)", r"\s(?:-[A-Za-z]*m[A-Za-z]*|--move)(?=$|[\s;&|)])", line=False)),  # 圧縮したあと元を消す
    ("削除・書き換え（git）",
     B + r"git\s+(?:-\S+(?:\s+[^-\s]\S*)?\s+)*(?:push|clean|rebase|restore|rm|reset\s+--hard|stash\s+(?:drop|clear)|"
         r"branch\s+-D|checkout\s+(?:--|\.))(?=\s|$)"),
    ("プロセスの停止", cmd(r"kill|pkill|killall")),
    ("システム", cmd(r"sudo|su|launchctl|crontab|shutdown|reboot|halt|pmset|diskutil|systemsetup|osascript|shortcuts")),
    ("システム", B + r"defaults\s+(?:write|delete)\b"),
    ("権限の変更", cmd(r"chmod|chown|chgrp|chflags")),
    ("インストール", B + r"(?:brew|pip3?|npm|pnpm|yarn|gem)\s+(?:install|i|ci|add|uninstall|remove|publish)(?=$|[\s;&|)`'\"])"),
    ("インストール", r"\bpython3?\s+-m\s+pip\s+(?:install|uninstall)\b"),
    ("外部送信", cmd(r"curl|wget|scp|sftp|rsync|ssh|nc|ncat|telnet|ftp|mail|sendmail|mutt|swaks")),
    ("外部送信・公開", B + r"gh\s+(?:pr|issue|release|gist|api|repo)\b"),
    ("外部送信", B + r"open\b[^\n;&|]*(?:mailto:|https?://|-a\s+[\"']?Mail\b)"),
    ("シェルへの受け渡し", r"\|\s*(?:(?:/[\w.-]+)+/)?(?:ba|z)?sh(?=$|[\s;&|)])"),
    ("シェルへの受け渡し", r"\$\(\s*(?:echo|printf)\s+[\"']?(?:rm|kill|curl|sudo)\b"),
    ("スクリプト経由の削除・送信",
     seq(r"\bpython3?\b", r"(?:os\.(?:remove|unlink|rmdir|removedirs|system)\b|shutil\.rmtree|\.unlink\(|\.rmdir\(|"
                          r"requests\.(?:post|put|delete|patch)|smtplib|urlopen\()", line=False)),
    ("スクリプト経由の削除", seq(r"\bperl\b", r"\s-\w*e\b", r"\b(?:unlink|rmdir|system)\b")),
    ("スクリプト経由の削除", seq(r"\bruby\b", r"\s-\w*e\b", r"(?:File\.delete|FileUtils\.rm|system)")),
    ("スクリプト経由の削除", seq(r"\bnode\b", r"\s-\w*e\b", r"(?:rmSync|unlinkSync|rmdirSync|\.rm\(|\.unlink\(|child_process)")),
    # 印（設定・タスクの正本）を動かす・消す操作は、記録があるので文字の並びではなく行き先を解いて止める（destructive_hit）
    ("空にする・上書き", seq(r"\bdd\b", r"\bof=")),
    ("空にする・上書き", r"\b(?:cp|cat)\s+/dev/null\b"),
    ("空にする・上書き", r"\bln\s+-\w*f\w*\s+/dev/null\b"),
    ("空にする・上書き", r"(?:^|\n|[;&|]\s*)\s*:\s*>"),
    ("空にする・上書き", r">\|"),
    ("ゴミ箱・破棄", seq(r"\bmv\b", r"\s(?:/dev/null|\S*/\.Trash\b)")),
    ("保護されたファイルの書き換え",
     seq(r"\b(?:sed|perl)\b", r"\s-i\b", r"\s[\"']?(?:\./)?(?:\.claude/|CLAUDE\.md(?=$|[\s\"'])|設定/)")),
    ("保護されたファイルの書き換え", seq(r"\b(?:sed|perl)\b", r"\s-i\b", r"\s[\"']?(?:\S*/)?03_インプット[\"']?/")),
    ("元データの移動・上書き", seq(r"\b(?:mv|cp|tee)\b", r"\s[\"']?(?:\S*/)?03_インプット[\"']?/")),
    ("保護されたファイルの上書き", r">>?\s*[\"']?(?:\S*/)?03_インプット[\"']?/"),
    ("保護されたファイルの上書き", r">>?\s*[\"']?(?:\S*/)?\.claude/settings[^\s]*\.json"),
]
# 03_インプット を文字の並びで見る規則の番号（SKIP_03 で外す）
RULES_03 = {k for k, (_, m) in enumerate(BASH_RULES) if "03_インプット" in (m if isinstance(m, str) else " ".join(getattr(m, "pats", ())))}


def _hit(m, text):
    return bool(re.search(m, text)) if isinstance(m, str) else bool(m(text))


def normalize(cmd_text):
    """\\rm・r\\m・行末の \\ による改行など、見た目をずらす書き方をならす。濁点を分けた表記（NFD）も NFC にそろえる。"""
    t = cmd_text.replace("\\\n", " ")
    return unicodedata.normalize("NFC", re.sub(r"\\(?=[A-Za-z])", "", t))


# Write / Edit で書いてはいけない場所（本人のフォルダからの相対パスで判定）
PROTECTED_PATHS = [
    ("元データ（読むだけ）", r"^03_インプット/"),
    ("権限・設定", r"^\.claude/settings(?:\.local)?\.json$"),
    ("hook・権限（.claude の設定）", r"^\.claude/hooks/"),
    ("共通ルールの自動コピー（プラグイン側を直す）", r"^\.claude/rules/ai-bunshin-common\.md$"),
]


OWNER_MARKS = (("設定", "config.json"), ("00_タスク管理", "data", "tasks.json"), (".claude", "rules", "ai-bunshin-common.md"))


def nfc(text):
    return unicodedata.normalize("NFC", text)


def path_forms(p, base=None):
    """p のリンクを解かない形（abspath）と解いた形（realpath）を、NFC にそろえた文字列で返す（~ は展開する）。"""
    try:
        t = os.path.expanduser(os.fspath(p))
        if base is not None and not os.path.isabs(t):
            t = os.path.join(base, t)
        a = os.path.abspath(t)
        out = {nfc(a)}
        out.add(nfc(os.path.realpath(a)))
        return out
    except (OSError, ValueError, TypeError):
        return set()


def is_under(f, r):
    """f が r そのもの、または r の下か（文字列で比べる。どちらも path_forms の形）。"""
    return f == r or f.startswith(r.rstrip(os.sep) + os.sep)


# ---- 本人のフォルダの記録（~/.ai-bunshin/owners.json）。印で見つけたフォルダを足していき、消さない ----

def records_dir():
    return Path.home() / ".ai-bunshin"


def records_file():
    return records_dir() / "owners.json"


_RECORDS = None


def _read_records():
    try:
        data = json.loads(records_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("owners", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    return [nfc(x) for x in items if isinstance(x, str) and os.path.isabs(x)]


def load_records():
    global _RECORDS
    if _RECORDS is None:
        _RECORDS = _read_records()
    return _RECORDS


def remember_owner(d):
    """前の版の判定では記録に足さない（ng_guard.py が足す）。"""
    return
    try:
        recs = load_records()
        new = [f for f in sorted(path_forms(d)) if f not in recs]
        if not new:
            return
        recs.extend(new)
        merged = _read_records()  # ほかの見張りが同時に足した分を消さないよう、読み直して足す
        for f in recs:
            if f not in merged:
                merged.append(f)
        records_dir().mkdir(parents=True, exist_ok=True)
        tmp = records_dir() / f".owners.{os.getpid()}.tmp"
        tmp.write_text(json.dumps({"owners": merged}, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, records_file())
    except Exception:
        pass


def record_roots():
    """記録にある本人のフォルダ：[(記録の文字列, 解いたフォルダ)]。"""
    out = []
    for f in load_records():
        try:
            out.append((f, Path(os.path.realpath(f))))
        except (OSError, ValueError):
            out.append((f, Path(f)))
    return out


_OWNER_DIR_CACHE = {}


def is_owner_dir(d):
    """印（設定/config.json・00_タスク管理/data/tasks.json・.claude/rules/ai-bunshin-common.md）のどれか1つがあるか。
    「両方」を条件にすると、片方を動かすだけで見張りが外れるので、1つでよい。"""
    key = str(d)
    if key not in _OWNER_DIR_CACHE:
        try:
            _OWNER_DIR_CACHE[key] = any(d.joinpath(*m).is_file() for m in OWNER_MARKS)
        except (OSError, ValueError):
            _OWNER_DIR_CACHE[key] = False
    return _OWNER_DIR_CACHE[key]


def _resolved(d):
    try:
        return d.resolve()
    except (OSError, RuntimeError):
        return d


def find_owner(path):
    """path（ファイルでもよい）から上にたどって本人のフォルダを探す（印がある、または記録にある）。
    リンクを解かない道（abspath）と解いた道（realpath）の両方を見て、どちらかで見つかれば返す（解いたフォルダ）。
    印で見つけたフォルダは記録に足す。"""
    recs = set(load_records())
    for f in sorted(path_forms(path)):
        q = Path(f)
        for d in (q, *q.parents):
            if is_owner_dir(d):
                remember_owner(d)
                return _resolved(d)
            if nfc(str(d)) in recs:
                return _resolved(d)
    return None


def project_dir(payload):
    """本人のフォルダを返す。今いる場所（CLAUDE_PROJECT_DIR・payload の cwd・os.getcwd）から上にたどって探す
    （05_開発/ などの下で動いていても本人のフォルダ）。見つからなければ None（＝ほかのプロジェクト）。"""
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    try:
        here = os.getcwd()
    except OSError:
        here = None
    for c in (os.environ.get("CLAUDE_PROJECT_DIR"), cwd, here):
        if not c or not isinstance(c, str):
            continue
        r = find_owner(c)
        if r is not None:
            return r
    return None


def base_cwd(payload, root=None):
    c = payload.get("cwd") if isinstance(payload, dict) else None
    if isinstance(c, str) and c:
        return c
    if root is not None:
        return str(root)
    try:
        return os.getcwd()
    except OSError:
        return os.path.expanduser("~")


# ---- コマンドの読み解き：区切り（; && || & 改行）・パイプ・cd の行き先・展開・ワイルドカード ----

MAX_WORDS = 3000  # 外のセッションでこれを超える長さは、指している本人のフォルダを探しきれないので、記録にあるすべてで全体を判定する


def split_top(text, pipes=False):
    """引用符・$( )・` ` の外にある ; && || & 改行（pipes=True なら | も）で分ける。"""
    out, cur, i, q, depth, n = [], [], 0, None, 0, len(text)

    def flush():
        s = "".join(cur).strip()
        if s:
            out.append(s)
        cur.clear()

    while i < n:
        c = text[i]
        if q:
            cur.append(c)
            if c == "\\" and q != "'" and i + 1 < n:
                cur.append(text[i + 1])
                i += 2
                continue
            if c == q:
                q = None
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            cur.append(text[i:i + 2])
            i += 2
            continue
        if c in "'\"`":
            q = c
        elif text.startswith("$(", i):
            depth += 1
            cur.append("$(")
            i += 2
            continue
        elif c == "(" and depth:
            depth += 1
        elif c == ")" and depth:
            depth -= 1
        elif depth == 0:
            if text.startswith("&&", i) or text.startswith("||", i):
                flush()
                i += 2
                continue
            if c in ";\n" or (c == "&" and (i == 0 or text[i - 1] not in "<>") and not text.startswith("&>", i)):
                flush()
                i += 1
                continue
            if pipes and c == "|":
                flush()
                i += 1
                continue
        cur.append(c)
        i += 1
    flush()
    return out


def seg_words(text):
    s = re.sub(r"\$\(\s*pwd\s*\)|`\s*pwd\s*`|\$\{PWD\}", "$PWD", text)
    try:
        lex = shlex.shlex(s, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        lex.commenters = ""
        return list(lex)
    except ValueError:
        return [w.strip("'\"") for w in re.findall(r"[^\s;&|()<>]+", s)]


def expand(w, cwd):
    home = os.path.expanduser("~")
    w = w.replace("${HOME}", home).replace("$HOME", home).replace("$PWD", cwd)
    if w.startswith("~"):
        w = os.path.expanduser(w)  # ~user も
    return w


GLOB_CHARS = re.compile(r"[*?\[]")
PY_LIT = r"""(?:[rbuRBU]{1,2})?(['"])(.*?)\1"""


def word_texts(w):
    """語からパスの候補を取り出す：語そのもの、-C/x・--opt=x・NAME=x の後ろ、語の中の引用符つき文字列（python のコードなど）。"""
    out = [w]
    for pat in (r"^--?[\w-]+=(.+)$", r"^-[A-Za-z]([/~.$].*)$", r"^[A-Za-z_]\w*=(.+)$"):
        m = re.match(pat, w)
        if m:
            out.append(m.group(1))
    out += [m.group(2) for m in re.finditer(PY_LIT, w) if m.group(2)]
    return out


def to_paths(t, cwd):
    """文字列 t をパス（絶対、NFC の文字列の集合）にする。ワイルドカードは実際のファイルに広げる。"""
    if not t or len(t) > 1024 or "\n" in t or "\x00" in t:
        return set()
    t = os.path.expanduser(t)
    full = t if os.path.isabs(t) else os.path.join(cwd, t)
    out = set()
    if GLOB_CHARS.search(t):
        try:
            hits = glob.glob(full)
        except (OSError, ValueError, re.error):
            hits = []
        for h in hits[:5000]:
            out |= path_forms(h)
        if len(hits) > 5000:
            out |= path_forms(os.path.dirname(full))
    out |= path_forms(full)
    return out


WRAPPERS = {"sudo", "env", "command", "builtin", "nohup", "time", "nice", "exec", "then", "do", "else", "elif",
            "if", "while", "until", "!", "{", "(", "xargs", "caffeinate", "timeout"}


class Part:
    """パイプでつながった1つのコマンド。"""

    def __init__(self, text, cwd, words):
        self.text, self.cwd, self.words = text, cwd, words
        i = 0
        while i < len(words):
            w = words[i]
            if w in WRAPPERS or re.match(r"^[A-Za-z_]\w*=", w) or (w.startswith("-") and i and words[i - 1] in WRAPPERS):
                i += 1
                continue
            break
        self.cmd = os.path.basename(words[i]) if i < len(words) else ""
        self.args = [a for a in words[i + 1:] if a not in (")", "}", ";;")]


class Analysis:
    def __init__(self):
        self.groups = []      # [(区切りごとのテキスト, [Part])]
        self.parts = []       # すべての Part（bash -c・eval の中身も）
        self.nwords = 0
        self.too_long = False


def os_path_join_norm(cwd, dest):
    """os.path.normpath(os.path.join(cwd, dest))（ng_guard.py が、同じ結果の速いものに差し替える）。"""
    return os.path.normpath(os.path.join(cwd, dest))


def analyze(command, cwd, an=None, depth=0, top=None):
    """コマンドを区切り・パイプに分け、cd の行き先を順にたどって、各コマンドの今いる場所と語を出す。
    ヒアドキュメント（<<）があるときは区切らない（中身が別の言語のため）。"""
    an = an or Analysis()
    groups = [command] if "<<" in command else split_top(command)
    for g in groups:
        parts = []
        for pt in ([g] if "<<" in g else split_top(g, pipes=True)):
            words = [expand(w, cwd) for w in seg_words(pt)]
            an.nwords += len(words)
            an.too_long = an.nwords > MAX_WORDS
            p = Part(pt, cwd, words)
            p.top = top if top is not None else g
            parts.append(p)
            an.parts.append(p)
            if p.cmd in ("cd", "pushd"):
                dest = next((a for a in p.args if not a.startswith("-")), None)
                if dest is None:
                    cwd = os.path.expanduser("~")
                else:
                    cwd = os_path_join_norm(cwd, dest)
            if depth < 3:
                if p.cmd in ("bash", "sh", "zsh"):
                    for k, a in enumerate(p.args[:-1]):
                        if re.match(r"^-\w*c\w*$", a):
                            analyze(p.args[k + 1], cwd, an, depth + 1, p.top)
                            break
                elif p.cmd == "eval":
                    analyze(" ".join(p.args), cwd, an, depth + 1, p.top)
        an.groups.append((g, parts))
    return an


def part_paths(p):
    out = set()
    for w in p.words:
        for t in word_texts(w):
            out |= to_paths(t, p.cwd)
    return out


# ---- 動かす・消す操作の「元」（行き先は除く）----

def _nonopt(args):
    out, after = [], False
    for a in args:
        if after or not a.startswith("-") or a == "-":
            out.append(a)
        elif a == "--":
            after = True
    return out


PY_CWD = r"(?:os\.getcwd\(\)|(?:pathlib\.)?Path\.cwd\(\)|(?:pathlib\.)?Path\(\s*\)|os\.curdir)"
PY_CALL = r"(?:os\.(?:rename|renames|replace|remove|unlink|rmdir|removedirs)|shutil\.(?:move|rmtree))\(\s*"
PY_METHOD = r"\s*\.(?:rename|replace|rmdir|unlink)\("


def python_sources(code):
    """python のコードの中で、動かす・消す対象になっている文字列（今いる場所は "."）。"""
    lit = r"(?:[rbuRBU]{1,2})?(?:'([^'\n]*)'|\"([^\"\n]*)\")"  # 引用符つき文字列（中身は2つの組のどちらか）
    out = []
    for m in re.finditer(PY_CALL + r"(?:" + lit + r"|(" + PY_CWD + r"))", code):
        out.append("." if m.group(3) else (m.group(1) if m.group(1) is not None else m.group(2)))
    for m in re.finditer(r"(?:pathlib\.)?Path\(\s*" + lit + r"\s*\)" + PY_METHOD, code):
        out.append(m.group(1) if m.group(1) is not None else m.group(2))
    for m in re.finditer(PY_CWD + PY_METHOD, code):
        out.append(".")
    called = {m.group(1) for m in re.finditer(r"\b([A-Za-z_]\w*)" + PY_METHOD, code)}
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s*=\s*(?:pathlib\.)?Path\(\s*" + lit + r"\s*\)", code):
        if m.group(1) in called:
            out.append(m.group(2) if m.group(2) is not None else m.group(3))
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s*=\s*" + PY_CWD, code):
        if m.group(1) in called:
            out.append(".")
    return [s.rstrip("\\") for s in out if s]


def move_sources(p):
    """Part が動かす・消すもの：(元の文字列のリスト, mv の行き先 or None, 基準の場所)。"""
    c, a, base = p.cmd, p.args, p.cwd
    if c == "git":
        i, sub = 0, ""
        while i < len(a):
            if a[i] == "-C" and i + 1 < len(a):
                base = os.path.join(base, a[i + 1])
                i += 2
            elif a[i].startswith("-C") and len(a[i]) > 2:
                base = os.path.join(base, a[i][2:])
                i += 1
            elif a[i] in ("-c", "--git-dir", "--work-tree") and i + 1 < len(a):
                i += 2
            elif a[i].startswith("-"):
                i += 1
            else:
                sub = a[i]
                break
        if sub in ("mv", "rm"):
            c, a = sub, a[i + 1:]
        else:
            return [], None, base
    srcs, dest = [], None
    if c in ("mv", "rename"):
        has_t, skip, plain = False, False, []
        for x in a:
            if skip:
                skip = False
                continue
            if x in ("-t", "--target-directory"):
                has_t, skip = True, True
                continue
            if x.startswith("--target-directory="):
                has_t = True
                continue
            plain.append(x)
        plain = _nonopt(plain)
        if c == "mv" and not has_t and plain:
            srcs, dest = plain[:-1], plain[-1]
        else:
            srcs = plain
    elif c in ("rm", "rmdir", "unlink", "trash", "srm", "shred"):
        srcs = _nonopt(a)
    elif c == "zip" and any(re.match(r"^-[A-Za-z]*m", x) or x == "--move" for x in a):
        srcs = _nonopt(a)[1:]
    elif c == "rsync" and "--remove-source-files" in a:
        srcs = _nonopt(a)[:-1]
    elif c == "tar" and "--remove-files" in a:
        srcs = _nonopt(a)
    elif c == "find" and (_find_destroys(a) if R2_FIND else any(x in ("-delete", "-exec", "-execdir", "-ok", "-okdir") for x in a)):
        for x in a:
            if x.startswith("-") or x in ("(", "!"):
                break
            srcs.append(x)
        srcs = srcs or ["."]
    if re.search(r"\bpython[\d.]*\b", p.text):
        srcs = srcs + python_sources(p.text)
        for w in p.words:
            srcs += python_sources(w)
    return srcs, dest, base


_FIND_EXEC_DESTROY = {"rm", "rmdir", "unlink", "mv", "rename", "shred", "srm", "trash",
                      "sh", "bash", "zsh", "dash", "ksh", "env", "xargs", "sudo", "command", "eval", "osascript",
                      "python", "python3", "perl", "ruby", "node"}


def _find_destroys(args):
    for k, x in enumerate(args):
        if x == "-delete":
            return True
        if x in ("-exec", "-execdir", "-ok", "-okdir") and k + 1 < len(args):
            name = os.path.basename(args[k + 1])
            if name in _FIND_EXEC_DESTROY or re.match(r"^python[\d.]*$", name):
                return True
    return False


def protected_roots(root=None):
    """どこからでも動かす・消すのを止めるフォルダ：[(フォルダの形の文字列, 本人のフォルダ or None)]。
    記録にある本人のフォルダ・今の本人のフォルダ・見張りの記録の置き場所。"""
    out = [(f, r) for f, r in record_roots()]
    if root is not None:
        out += [(f, root) for f in path_forms(root)]
    out += [(f, None) for f in path_forms(records_dir())]
    return out


def destructive_hit(an, root=None):
    """本人のフォルダそのもの（やその親）・見張りの記録・印を動かす・消す操作か。(ラベル, 本人のフォルダ) を返す。"""
    prot = protected_roots(root)
    owners = {}
    for f, r in prot:
        if r is not None:
            owners.setdefault(str(r), r)
    marks = []
    for r in owners.values():
        for f in path_forms(r):
            marks += [(nfc(os.path.join(f, *m)), r) for m in OWNER_MARKS]
    for p in an.parts:
        srcs, dest, base = move_sources(p)
        for s in srcs:
            for t in word_texts(s):
                for f in to_paths(t, base):
                    for pr, r in prot:
                        if is_under(pr, f):
                            if r is None:
                                return "見張りの記録（~/.ai-bunshin/）を動かす・消す", None
                            return "本人のフォルダそのものを動かす・消す", r
                    for mk, r in marks:
                        if is_under(mk, f):
                            return "本人の設定・タスクの正本の移動・削除", r
        if dest is not None and p.cmd in ("mv", "git"):
            for f in to_paths(dest, base):
                for mk, r in marks:
                    if f == mk:
                        return "本人の設定・タスクの正本の上書き", r
    return None


RECORD_WRITE = re.compile(r"(?:>>?(?!\s*(?:&|/dev/null\b))|\btee\b|\s-i\b|\b(?:cp|mv|ln|rsync|install|touch|mkdir|rm|rmdir|unlink|shred|trash|rename|"
                          r"truncate|dd|unzip|tar|zip|patch|chmod|chflags|chown|find|sed|perl|ruby|node|python[\d.]*)\b|"
                          r"open\(|\.write|write_text|writeFile|\bcd\b|\bpushd\b)")


def records_bash_hit(an):
    """見張りの記録（~/.ai-bunshin/）に書く Bash か。読むだけ（cat・ls など）は通す。
    記録の名前が出てくる、またはパス・cd の行き先が記録の置き場所の中の区切りに、書き込みの語があれば止める。"""
    rec = path_forms(records_dir())
    for p in an.parts:
        if not RECORD_WRITE.search(p.top):
            continue
        if re.search(r"\.ai-bunshin(?=$|[/\s\"';&|)])", p.top) or any(
                is_under(f, r) for f in part_paths(p) | path_forms(p.cwd) for r in rec):
            return True
    return False


# 外のセッションで、本人のフォルダを指していても、あとの区切りに影響しない読むだけのコマンド
READ_ONLY_CMDS = {"cat", "ls", "head", "tail", "wc", "grep", "egrep", "fgrep", "rg", "diff", "stat", "file", "less", "more",
                  "du", "df", "pwd", "test", "[", "realpath", "readlink", "echo", "printf", "find", "open", "md5", "shasum",
                  "cd", "pushd"}


def _read_only_group(g, parts):
    if re.search(r"[>`]|\$\(|<\(", g):
        return False
    if len(parts) != 1:
        return False
    p = parts[0]
    if p.cmd == "find" and ((_find_destroys(p.args) or any(x in ("-fprint", "-fprintf", "-fls") for x in p.args)) if R2_FIND else
                            any(x in ("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprintf", "-fls") for x in p.args)):
        return False
    return p.cmd in READ_ONLY_CMDS


def roots_from_input(payload):
    """起動場所が本人のフォルダの外のとき、操作が指している本人のフォルダと、その本人のフォルダで判定する範囲（Bash の
    コマンドの一部。None なら全部）のリスト。Write・Edit はパス、Bash はパス・cd の行き先・記録にあるフォルダの名前で見つける。
    外のコマンドの中で、本人のフォルダを指す区切りと、その後ろの区切り（変数や for で受け渡せるため。読むだけのコマンドは除く）を判定する。"""
    tool = payload.get("tool_name", "")
    inp = payload.get("tool_input")
    if not isinstance(inp, dict):
        return []
    base = base_cwd(payload)
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        p = inp.get("file_path") or inp.get("notebook_path")
        if isinstance(p, str) and p:
            for f in sorted(path_forms(p, base)):
                r = find_owner(f)
                if r is not None:
                    return [(r, None)]
        return []
    if tool != "Bash" or not isinstance(inp.get("command"), str):
        return []
    flat = normalize(inp["command"])
    an = analyze(flat, base)
    recs = record_roots()
    if an.too_long:  # 確かめきれない長さ：記録にあるすべての本人のフォルダで、全体を判定する（止める側）
        seen, out = set(), []
        for _, r in recs:
            if str(r) not in seen:
                seen.add(str(r))
                out.append((r, None))
        return out
    names = {}
    for f, r in recs:
        nm = nfc(os.path.basename(f.rstrip(os.sep)))
        if nm:
            names.setdefault(nm, []).append(r)
    # 区切りごとのコマンド（bash -c・eval の中身も、その区切りに含める）
    groups = [(g, [p for p in an.parts if p.top == g]) for g, _ in an.groups]
    refs = []  # 区切りごとの、指している本人のフォルダ（解いた形の文字列 → Path）
    for g, parts in groups:
        hit = {}
        for p in parts:
            cands = set()
            for w in p.words:
                for t in word_texts(w):
                    cands |= to_paths(t, p.cwd)
            cands_anc = set(cands) if p.cmd not in ("cd", "pushd") else set()  # 今いる場所は親とみなさない（cd ~ など）
            cands |= path_forms(p.cwd)
            for f in cands:
                r = find_owner(f)
                if r is not None:
                    hit[str(r)] = r
            for f in cands_anc:  # 本人のフォルダの親を指す（chmod -R ~/workspace など）
                for rf, r in recs:
                    if is_under(rf, f):
                        hit[str(r)] = r
            for w in ([] if R1_NO_NAMES else p.words):
                wn = nfc(w)
                for nm, rs in names.items():
                    if nm in wn:
                        for r in rs:
                            hit[str(r)] = r
        refs.append(hit)
    roots = {}
    for hit in refs:
        roots.update(hit)
    out = []
    for key, r in roots.items():
        chosen, tainted = [], False
        for (g, parts), hit in zip(groups, refs):
            cd_only = all(p.cmd in ("cd", "pushd") for p in parts)
            if key in hit or tainted or cd_only:
                chosen.append(g)
            if key in hit and not _read_only_group(g, parts):
                tainted = True
        out.append((r, "\n".join(chosen)))
    return out


def allow_patterns(root):
    try:
        cfg = json.loads((root / "設定" / "config.json").read_text(encoding="utf-8"))
        return [re.compile(p) for p in cfg.get("ng_allow", [])]
    except (OSError, ValueError, re.error):
        return []


def dev_paths(root):
    """本人設定（config の dev.projects）に登録した開発の置き場所（絶対パス）。"""
    try:
        cfg = json.loads((root / "設定" / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for prj in (cfg.get("dev") or {}).get("projects", []):
        if prj.get("path"):
            d = Path(os.path.expanduser(prj["path"]))
            out.append((d if d.is_absolute() else root / d).resolve())
    out.append((root / "05_開発").resolve())  # local モードの置き場所は登録がなくても対象
    return out


def in_dev_area(command, payload, root):
    """コマンドが開発の置き場所の中で動くか。cd の行き先は順にたどり（cd .. も含む）、すべて置き場所の中のときだけ True。
    -C／--prefix／--cwd の行き先も置き場所の中であること。cd が無ければ、今いる場所（cwd）で判断する。"""
    areas = dev_paths(root)

    def is_inside(q):
        return any(q == a or a in q.parents for a in areas)

    def resolve(base, text):
        t = os.path.expanduser(text.strip("'\""))
        try:
            return (Path(t) if os.path.isabs(t) else base / t).resolve()
        except (OSError, ValueError):
            return None

    cur = Path(payload.get("cwd") or root).resolve()
    cds = re.findall(r"(?:^|[;&|(]\s*)cd\s+(\"[^\"]+\"|'[^']+'|[^\s;&|)]+)", command)
    for t in cds:
        cur = resolve(cur, t)
        if cur is None or not is_inside(cur):
            return False
    for t in re.findall(r"(?:\s-C|--prefix|--cwd)(?:=|\s+)(\"[^\"]+\"|'[^']+'|[^\s;&|)]+)", command):
        q = resolve(cur, t)
        if q is None or not is_inside(q):
            return False
    return is_inside(cur)


def pip_outside_venv(command):
    """pip のインストールが仮想環境（venv）の外に向いているか。venv/bin/pip・venv/bin/python -m pip、
    または先に source <venv>/bin/activate していれば中とみなす。"""
    activated = re.search(r"(?:^|[;&|(]\s*)(?:source|\.)\s+\S*venv/bin/activate\b", command)
    for m in re.finditer(r"(\S*)\b(?:pip3?\s+install|python3?\s+-m\s+pip\s+install)\b", command):
        prefix = m.group(1)
        if re.search(r"(?:^|/)\.?venv/bin/$", prefix):
            continue
        if activated and activated.start() < m.start() and not prefix:
            continue
        return True
    return False


# 開発の置き場所の中なら通す操作（その案件の中へのインストール）。パソコン全体（-g・brew・sudo）は通さない
DEV_ALLOWED = {"インストール"}
GLOBAL_INSTALL = re.compile(r"(?:\s-g\b|--global\b|--location[= ]global\b|\bbrew\b|\bsudo\b|\bgem\b|--user\b|"
                            r"--target\b|-t\s|--root\b|--break-system-packages)")


def is_maintainer(root):
    if root is None:
        return False
    try:
        return bool(json.loads((root / "設定" / "config.json").read_text(encoding="utf-8")).get("maintainer"))
    except (OSError, ValueError):
        return False


def plugin_area(path_text):
    """プラグインのコピー（~/.claude/plugins/ の下）か、プラグインの元（.claude-plugin/ を持つフォルダの下）か。"""
    try:
        q = Path(os.path.expanduser(path_text)).resolve()
    except (OSError, ValueError):
        return None
    plugins = (Path.home() / ".claude" / "plugins").resolve()
    if q == plugins or plugins in q.parents:
        return "copy"
    for d in [q, *q.parents]:
        if (d / ".claude-plugin" / "plugin.json").exists() or (d / ".claude-plugin" / "marketplace.json").exists():
            return "source"
    return None


WRITE_WORDS = re.compile(r"(?:>|\btee\b|\s-i\b|\b(?:cp|mv|ln|rsync|install|touch|mkdir|rm|truncate|dd|unzip|tar|patch)\b|"
                         r"open\(|\.write|write_text|writeFile|\bcd\b|\bpushd\b)")
READ_ONLY_CP = re.compile(r"^\s*cp\s+(?:-(?!t\b)[A-Za-su-z]+\s+)*\S+\s+\S+\s*$")  # -t（コピー先の指定）付きは読み出しとみなさない


def plugin_bash_check(command, root):
    """Bash でのプラグインへの書き込み。コピー（~/.claude/plugins/）は誰でも、元（.claude-plugin/ を持つフォルダ）は
    メンテする人以外を止める。読むだけ（cat・ls・diff、cp のコピー元）は通す。
    パスを細かく追えない書き方（cd してから書く、python -c で書く）もあるので、書き込みの語があれば広めに止める。"""
    if not WRITE_WORDS.search(command):
        return None
    tokens = re.findall(r"[\"']?([^\s\"';&|()]+)[\"']?", command)
    copy_hit = None if SKIP_PLUGIN_COPY else re.search(r"\.claude/plugins(?:/|$|[\s\"'])", command)
    if copy_hit:
        # cp <プラグインのコピー> <外> だけは読み出しなので通す
        if READ_ONLY_CP.match(command):
            parts = command.split()
            if ".claude/plugins" in parts[-2] and ".claude/plugins" not in parts[-1]:
                return None
        return "プラグインのコピーの書き換え（Claude Code が読み込む共通部分。元を直して更新する）"
    if root is not None and not is_maintainer(root):  # 元の保護は本人のフォルダの中だけ（ほかのプロジェクトでは誰がメンテする人か分からない）
        for tk in tokens:
            if "/" in tk and plugin_area(tk.replace("$HOME", "~")) == "source":
                if READ_ONLY_CP.match(command) and tk == command.split()[-2]:
                    continue
                return "共通部分（プラグインの元）の書き換え（メンテする人だけ。提案の下書きにする）"
    return None


# プラグイン・見張りの記録・本人のフォルダそのものの保護は、本人の許可する例外（ng_allow）でも外さない
NO_EXCEPTION_LABELS = ("プラグインのコピーの書き換え", "共通部分（プラグインの元）の書き換え", "見張りの記録",
                       "本人のフォルダそのものを動かす・消す")
RECORDS_LABEL = "見張りの記録（~/.ai-bunshin/）の書き換え（本人のフォルダを覚えておく所。消すと見張りが外れる）"


def global_check(payload, root):
    """どこからでも効かせる保護：プラグインのコピー、見張りの記録、本人のフォルダそのもの・印を動かす・消す操作。
    (ラベル, 対象, ログを書く本人のフォルダ) を返す。"""
    tool = payload.get("tool_name", "")
    inp = payload.get("tool_input") or {}
    if tool == "Bash":
        command = inp.get("command", "")
        flat = normalize(command)
        plugin_label = plugin_bash_check(flat, root)
        if plugin_label:
            return plugin_label, command, root
        an = analyze(flat, base_cwd(payload, root))
        if records_bash_hit(an):
            return RECORDS_LABEL, command, root
        hit = destructive_hit(an, root)
        if hit:
            label, r = hit
            return label, command, (r if r is not None else root)
    elif tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        if path:
            if plugin_area(path) == "copy":
                return "プラグインのコピーの書き換え（Claude Code が読み込む共通部分。元を直して更新する）", path, root
            rec = path_forms(records_dir())
            if any(is_under(f, r) for f in path_forms(path, base_cwd(payload, root)) for r in rec):
                return RECORDS_LABEL, path, root
    return None


def rel_in_root(path, root, base):
    """path が root の中なら、root からの相対パス（NFC）。リンクを解かない道と解いた道の両方で比べる。"""
    rforms = path_forms(root)
    for f in sorted(path_forms(path, base)):
        for r in rforms:
            if is_under(f, r) and f != r:
                return f[len(r.rstrip(os.sep)) + 1:].replace(os.sep, "/")
    return None


def check(payload, root, command=None):
    """本人のフォルダ root の規則で判定する。command を渡したら、Bash はその部分だけを見る（外のセッション）。"""
    tool = payload.get("tool_name", "")
    inp = payload.get("tool_input") or {}
    if tool == "Bash":
        full = inp.get("command", "")
        flat = normalize(full if command is None else command)
        for k, (label, pat) in enumerate(BASH_RULES):
            if SKIP_03 and k in RULES_03:
                continue
            if _hit(pat, flat):
                if (label in DEV_ALLOWED and not GLOBAL_INSTALL.search(flat) and not pip_outside_venv(flat)
                        and in_dev_area(flat, payload, root)):
                    continue
                return label, full
    elif tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        if not path:
            return None
        if plugin_area(path) == "source" and not is_maintainer(root):
            return "共通部分（プラグインの元）の書き換え（メンテする人だけ。提案の下書きにする）", path
        rel = rel_in_root(path, root, base_cwd(payload, root))
        if rel is not None:
            for label, pat in PROTECTED_PATHS:
                if re.search(pat, rel, re.I):
                    return label, rel
    return None


def deny(label, target, root, tool=None):
    reason = (f"NG（{label}）：この操作は AI 分身では行いません。必要なら止めて、本人へのお願い（手順付き。"
              f"コマンドは `! …` の形で示す）にしてください。対象：{target[:200]}")
    log = root / "00_タスク管理" / "data" / "ng_log.jsonl" if root is not None else None
    try:
        if log is not None and log.parent.exists():
            with log.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "tool": tool,
                                    "label": label, "target": target[:500]}, ensure_ascii=False) + "\n")
    except OSError:
        pass
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}, ensure_ascii=False))


def verdict(payload):
    """前の版の run_guard と同じ判定。止めるなら (ラベル, 対象, ログを書く本人のフォルダ)、通すなら None（本人の許可する例外を含む）。"""
    root = project_dir(payload)
    hit = global_check(payload, root)
    log_root = root
    label = target = None
    if hit:
        label, target, log_root = hit
    elif root is not None:
        h = check(payload, root)
        if h:
            label, target = h
    else:
        for r, part in roots_from_input(payload):
            h = check(payload, r, part)
            if h:
                label, target = h
                log_root = r
                break
    if label is None:
        return None
    if log_root is not None and not label.startswith(NO_EXCEPTION_LABELS) and any(p.search(target) for p in allow_patterns(log_root)):
        return None
    return label, target, log_root
