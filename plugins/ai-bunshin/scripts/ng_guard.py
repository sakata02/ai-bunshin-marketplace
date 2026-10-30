#!/usr/bin/env python3
"""NG の見張り（PreToolUse hook）。権限の設定（deny）をすり抜ける書き方も含めて、やってはいけない操作を実行前に止める。

止めたら理由を Claude に返し（permissionDecision: deny）、00_タスク管理/data/ng_log.jsonl に記録する。
本人が許可した例外は 設定/config.json の "ng_allow"（正規表現のリスト。コマンドやパスに一致したら通す）に書く。

動くのは本人のフォルダの中だけ。本人のフォルダ＝印（設定/config.json・00_タスク管理/data/tasks.json・
.claude/rules/ai-bunshin-common.md）のどれか1つがある、または記録（~/.ai-bunshin/owners.json）にあるフォルダ。
今いる場所から上にたどって探す（リンクを解いた道と解かない道の両方）。印で見つけたフォルダは記録に足し、記録は消さない
（印を動かしても・消しても見張りは外れない）。
ほかのプロジェクトでは普段の作業を止めない。ただし、どこからでも次は止める：
- プラグインのコピー（~/.claude/plugins/ の下）・見張りの記録（~/.ai-bunshin/）への書き込み
- 本人のフォルダそのもの（やその親）を動かす・消す操作、印（設定/config.json・tasks.json・共通ルールの写し）を動かす・消す操作
- 外で始めたセッションでも、操作が本人のフォルダを指すなら（パス・cd の行き先・フォルダの名前）、その本人のフォルダを基準に判定する
- 見張りの入力を読めなかったときは、本人のフォルダの中なら止める、外なら通す

保護しているもの（本人のフォルダ・印・見張りの記録・03_インプット・.claude の設定・プラグインのコピー）と比べるときは、
文字の並びではなく実体（st_dev・st_ino）で比べる（方式 v2、T058）。すでにあるパスは、保護しているものと同じか、その下か。
まだ無いパスは、いちばん近い「ある」親の実体と、その先の名前（NFC・大文字小文字をそろえる）で比べる。
大文字小文字（macOS は区別しない）・NFD・リンク・//・/./・ハードリンクを、まとめて解く。
同じコマンドの中で作るリンク（ln -s・ln -sf・ln -sfn・os.symlink・Path.symlink_to）は、元か行き先が保護しているもの
（またはその下）なら、作る時点で止める（作ったあとのリンクは、見張りが動く時点ではまだ無く、たどれないため）。
確かめ方：python3 ng_guard.py --explain "<コマンド>"（今いる場所で判定し、deny／pass と理由を出す。記録も ng_log も書かない）
"""
import glob
import json
import os
import re
import shlex
import stat
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

DRY_RUN = False  # --explain のとき：見張りの記録（owners.json）にも ng_log にも書かない

# コマンドとして実行される位置：行頭・; & | ( ` $( { の後、then/do/else/eval/xargs/env/sudo などの後、
# bash -c "…"・bash -lc '…'・eval "…" の中身の先頭。/bin/rm のようなパス付きも同じに扱う。
# grep rm のように引数として出てくるだけのものは止めない
B = (r"(?:^|\n|[;&|(`{]|\$\(|"
     r"\b(?:bash|sh|zsh)\s+-\w*c\s+[\"']|\beval\s+[\"']?|"
     r"\b(?:then|do|else|xargs|env|nohup|time|exec|command|nice|sudo|eval)\s+(?:-\S+\s+)*)"
     r"\s*(?:(?:\.{0,2}/)?(?:[\w.-]+/)+)?")
E = r"(?=$|[\s;&|)`'\"])"


def cmd(words):
    return B + r"(?:" + words + r")" + E


def seq(*pats, line=True):
    """「pats[0] のあとに pats[1]、そのあとに pats[2] …」が（line=True なら同じ行の中に）あるか。
    `\\bpython\\b[\\s\\S]*(…)` のような書き方は、長いコマンドで長さの2乗の時間がかかる（R9）ので、前から1回ずつ探す。
    どの段も、いちばん早く見つかったものを使えば、あとの段が見つかる可能性は減らない（同じ結果になる）。"""
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
    return match


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
    # 03_インプット への書き込み・03_インプット からの移動は、文字の並びではなく行き先を実体で解いて止める（input_hit。R3）
    ("保護されたファイルの上書き", r">>?\s*[\"']?(?:\S*/)?\.claude/settings[^\s]*\.json"),
]
BASH_RULES = [(label, re.compile(m) if isinstance(m, str) else m) for label, m in BASH_RULES]

# 03_インプット を文字の並びで見ていたときの規則。ヒアドキュメント（<<）のあるコマンドは、区切りを解けない（中身が別の言語）
# ので、この形のときだけ前の規則も残す（前に止めていたものを通さないため。文書の中の語で止めないのは T092）
LEGACY_INPUT_RULES = [
    seq(r"\b(?:sed|perl)\b", r"\s-i\b", r"\s[\"']?(?:\S*/)?03_インプット[\"']?/"),
    seq(r"\b(?:mv|cp|tee)\b", r"\s[\"']?(?:\S*/)?03_インプット[\"']?/"),
    re.compile(r">>?\s*[\"']?(?:\S*/)?03_インプット[\"']?/").search,
]

# 書き込みではない向け先（R4）：2>/dev/null・>/dev/null・&>/dev/null・2>&1・>&2・2>&- など。規則を当てる前に除く
NULL_REDIR = re.compile(r"(?:\d+|&)?>>?\|?\s*/dev/(?:null|stdout|stderr|tty)(?![\w/.-])|\d*[<>]&\s*(?:\d+|-)(?![\w/.-])")


def quiet(text):
    return NULL_REDIR.sub(" ", text)


def rule_hit(matcher, text):
    """規則（正規表現、または seq などの関数）が text に当たるか。"""
    return bool(matcher.search(text)) if hasattr(matcher, "search") else bool(matcher(text))


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


# 同じものを実体（st_dev・st_ino）でも比べる：(理由, 本人のフォルダからの道)
PROTECTED_TARGETS = [
    ("元データ（読むだけ）", ("03_インプット",)),
    ("権限・設定", (".claude", "settings.json")),
    ("権限・設定", (".claude", "settings.local.json")),
    ("hook・権限（.claude の設定）", (".claude", "hooks")),
    ("共通ルールの自動コピー（プラグイン側を直す）", (".claude", "rules", "ai-bunshin-common.md")),
]


OWNER_MARKS = (("設定", "config.json"), ("00_タスク管理", "data", "tasks.json"), (".claude", "rules", "ai-bunshin-common.md"))


def nfc(text):
    return unicodedata.normalize("NFC", text)


_FORMS = {}


def path_forms(p, base=None):
    """p のリンクを解かない形（abspath）と解いた形（realpath）を、NFC にそろえた文字列で返す（~ は展開する）。"""
    key = (p if isinstance(p, str) else os.fspath(p) if isinstance(p, os.PathLike) else repr(p), base)
    if key in _FORMS:
        return _FORMS[key]
    try:
        t = os.path.expanduser(os.fspath(p))
        if base is not None and not os.path.isabs(t):
            t = os.path.join(base, t)
        a = os.path.abspath(t)
        out = {nfc(a)}
        out.add(nfc(os.path.realpath(t)))  # 「リンク/..」は、リンクを解いてから .. をたどる（OS と同じ）
        out.add(nfc(os.path.realpath(a)))  # 文字の上で .. をたどった形も見る（止める側）
        out = frozenset(out)
    except (OSError, ValueError, TypeError):
        out = frozenset()
    _FORMS[key] = out
    return out


def is_under(f, r):
    """f が r そのもの、または r の下か（文字列で比べる。どちらも path_forms の形）。"""
    return f == r or f.startswith(r.rstrip(os.sep) + os.sep)


# ---- 実体で比べる（st_dev・st_ino）。大文字小文字・NFD・リンク・//・/./・ハードリンクをまとめて解く ----

_IDENT = {}


def ident(p):
    """p（絶対パス）の実体 (st_dev, st_ino)。無い・読めないときは None。リンクはたどる。"""
    v = _IDENT.get(p, 0)
    if v == 0:
        try:
            st = os.stat(p)
            v = (st.st_dev, st.st_ino)
        except (OSError, ValueError, TypeError):
            v = None
        _IDENT[p] = v
    return v


_LOCATE = {}


def locate(p):
    """p（絶対パス）を (いちばん近い「ある」所, その実体, その先の名前のタプル) にする。
    その先の名前は NFC にそろえ、大文字小文字も区別しない（macOS の既定に合わせる。区別する所では止める側に寄る）。"""
    r = _LOCATE.get(p)
    if r is None:
        cur, rest = p, []
        while True:
            i = ident(cur)
            parent = os.path.dirname(cur)
            if i is not None or parent == cur:
                break
            rest.append(nfc(os.path.basename(cur)).casefold())
            cur = parent
        r = (cur, i, tuple(reversed(rest)))
        _LOCATE[p] = r
    return r


_CHAIN = {}


def chain(p):
    """ある所 p と、その親すべての実体の集合。リンクを解かない道（文字の上の親）と解いた道（realpath の親）の両方。"""
    r = _CHAIN.get(p)
    if r is None:
        r = set()
        try:
            starts = {p, os.path.realpath(p)}
        except (OSError, ValueError):
            starts = {p}
        for cur in starts:
            while True:
                i = ident(cur)
                if i is not None:
                    r.add(i)
                parent = os.path.dirname(cur)
                if parent == cur:
                    break
                cur = parent
        _CHAIN[p] = r
    return r


HARDLINK_SCAN_MAX = 20000  # フォルダの中のハードリンクを探すときに見るファイルの上限


class Target:
    """保護しているもの（ファイルかフォルダ）。まだ無くてもよい（いちばん近い「ある」親で比べる）。"""

    def __init__(self, path):
        self.path = os.fspath(path)
        try:
            rp = os.path.realpath(self.path)
        except (OSError, ValueError):
            rp = self.path
        self.anchor, self.id, self.rest = locate(nfc(rp))
        self._inodes = None

    @property
    def exists(self):
        return self.id is not None and not self.rest

    def covers(self, f):
        """f（絶対パス）が、これと同じか、その下か。f がハードリンクで、これ（フォルダ）の下のファイルと同じ実体のときも。"""
        anchor, i, rest = locate(f)
        if i is None or self.id is None:
            return False
        if not self.rest:
            if self.id in chain(anchor):
                return True
            return not rest and self._hardlink(anchor)
        return i == self.id and rest[:len(self.rest)] == self.rest

    def within(self, f):
        """これが、f（絶対パス。動かす・消すもの）と同じか、その下にあるか（f がこれを含むか）。"""
        anchor, i, rest = locate(f)
        if i is None or self.id is None:
            return False
        if rest:  # f がまだ無い：これもまだ無く、同じ所から f の先にあるときだけ（まだ無い印を動かす、など）
            return i == self.id and self.rest[:len(rest)] == rest
        return i in chain(self.anchor)

    def same(self, f):
        """f が、これ（すでにあるもの）と同じ実体か。"""
        if not self.exists:
            return False
        anchor, i, rest = locate(f)
        return not rest and i == self.id

    def _hardlink(self, f):
        try:
            st = os.stat(f)
        except (OSError, ValueError):
            return False
        if not stat.S_ISREG(st.st_mode) or st.st_nlink < 2:
            return False
        try:
            if not os.path.isdir(self.anchor):
                return False
        except (OSError, ValueError):
            return False
        if self._inodes is None:
            found, n = set(), 0
            try:
                for dp, _, files in os.walk(self.anchor):
                    for name in files:
                        n += 1
                        try:
                            s2 = os.stat(os.path.join(dp, name))
                        except (OSError, ValueError):
                            continue
                        if s2.st_nlink > 1:
                            found.add((s2.st_dev, s2.st_ino))
                    if n > HARDLINK_SCAN_MAX:
                        break
            except Exception:
                pass
            self._inodes = found
        return (st.st_dev, st.st_ino) in self._inodes


_TARGETS = {}


def target(path):
    key = os.fspath(path)
    t = _TARGETS.get(key)
    if t is None:
        t = _TARGETS[key] = Target(key)
    return t


def covers_any(t, forms):
    return any(t.covers(f) for f in forms)


# ---- 本人のフォルダの記録（~/.ai-bunshin/owners.json）。印で見つけたフォルダを足していき、消さない ----

def records_dir():
    return Path.home() / ".ai-bunshin"


def records_file():
    return records_dir() / "owners.json"


_RECORDS = None


def _read_records():
    """記録を読む。深い入れ子（RecursionError）・壊れた JSON・型の違いなど、読み込みの例外はすべて受けて [] を返す（R8）。
    記録が読めなくても、印で本人のフォルダを見つけて、中は今までどおり止める（記録が読めないことで保護が外れない）。"""
    try:
        data = json.loads(records_file().read_text(encoding="utf-8"))
        items = data.get("owners", []) if isinstance(data, dict) else data
        if not isinstance(items, list):
            return []
        return [nfc(x) for x in items if isinstance(x, str) and os.path.isabs(x)]
    except Exception:
        return []


def load_records():
    global _RECORDS
    if _RECORDS is None:
        _RECORDS = _read_records()
    return _RECORDS


def remember_owner(d):
    """本人のフォルダ d（abspath と realpath の両方）を記録に足す。重複させない。書けなくても見張りは止めない。"""
    if DRY_RUN:
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
    rids = record_ids()
    for f in sorted(path_forms(path)):
        q = Path(f)
        for d in (q, *q.parents):
            if is_owner_dir(d):
                remember_owner(d)
                return _resolved(d)
            if nfc(str(d)) in recs:
                return _resolved(d)
            i = ident(str(d)) if rids else None  # 記録と実体で比べる（大文字小文字・NFD・リンクの違い）
            if i is not None and i in rids:
                return rids[i]
    return None


_RECORD_IDS = None


def record_ids():
    """記録にある本人のフォルダの実体 → 解いたフォルダ。"""
    global _RECORD_IDS
    if _RECORD_IDS is None:
        _RECORD_IDS = {}
        for _, r in record_roots():
            i = ident(str(r))
            if i is not None:
                _RECORD_IDS.setdefault(i, r)
    return _RECORD_IDS


def owner_roots(root=None):
    """どこからでも守る本人のフォルダ（記録にあるもの・今の本人のフォルダ）。実体が同じものは1つにする。"""
    out, seen = [], set()
    for r in [r for _, r in record_roots()] + ([Path(root)] if root is not None else []):
        key = ident(str(r)) or str(r)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def marks_of(r):
    return [target(os.path.join(str(r), *m)) for m in OWNER_MARKS]


def plugins_dir():
    return Path.home() / ".claude" / "plugins"


def content_targets(owners):
    """中を書き換えてはいけないもの（リンクの元・行き先として止める）：見張りの記録・プラグインのコピー・印・03_インプット・.claude の設定。"""
    out = [target(records_dir()), target(plugins_dir())]
    for r in owners:
        out += marks_of(r)
        out += [target(os.path.join(str(r), *rel)) for _, rel in PROTECTED_TARGETS]
    return out


def holder_targets(owners):
    """含むものを動かす・消す・リンクの元にしてはいけないもの：本人のフォルダ・見張りの記録・印。"""
    out = [target(str(r)) for r in owners] + [target(records_dir())]
    for r in owners:
        out += marks_of(r)
    return out


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
    return seg_words_ok(text)[0]


def seg_words_ok(text):
    """語に分ける。(語のリスト, 引用符などを正しく解けたか)。解けなければ、空白などで切った語（向け先の > は落ちる）。"""
    s = re.sub(r"\$\(\s*pwd\s*\)|`\s*pwd\s*`|\$\{PWD\}", "$PWD", text)
    try:
        lex = shlex.shlex(s, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        lex.commenters = ""
        return list(lex), True
    except ValueError:
        return [w.strip("'\"") for w in re.findall(r"[^\s;&|()<>]+", s)], False


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


_TO_PATHS = {}


def to_paths(t, cwd):
    """文字列 t をパス（絶対、NFC の文字列の集合）にする。ワイルドカードは実際のファイルに広げる。"""
    key = (t, cwd)
    if key not in _TO_PATHS:
        _TO_PATHS[key] = frozenset(_to_paths(t, cwd))
    return _TO_PATHS[key]


def _to_paths(t, cwd):
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


REDIR_CHARS = set("<>&|")


def split_redirs(words):
    """語から向け先（> x・>> x・2> x・&> x・< x・<<EOF など）を除く。(残りの語, 書き込む向け先のリスト)。
    >&1・2>&- のような番号への向け先は書き込みではない（R4）。"""
    clean, redirs, k = [], [], 0
    while k < len(words):
        w = words[k]
        if w and set(w) <= REDIR_CHARS and ("<" in w or ">" in w):
            nxt = words[k + 1] if k + 1 < len(words) else None
            if ">" in w and nxt is not None and not (w.endswith("&") and re.fullmatch(r"\d+|-", nxt)):
                redirs.append(nxt)
            if len(clean) > 1 and re.fullmatch(r"\d{1,2}", clean[-1]):  # 2> の 2
                clean.pop()
            k += 2
            continue
        clean.append(w)
        k += 1
    return clean, redirs


RAW_REDIR = re.compile(r"(?:^|[^<>&\d\\])(?:\d*|&)>>?\|?\s*(?:\"([^\"\n]*)\"|'([^'\n]*)'|([^\s\"';&|()<>]+))")


class Part:
    """パイプでつながった1つのコマンド。"""

    def __init__(self, text, cwd, words, lex_ok=True):
        self.text, self.cwd, self.words = text, cwd, words
        clean, self.redirs = split_redirs(words)
        if not lex_ok or "<<" in text:  # 語に分けきれない（ヒアドキュメント・閉じない引用符）：文字の並びからも向け先を拾う
            for m in RAW_REDIR.finditer(quiet(text)):
                self.redirs.append(next(g for g in m.groups() if g is not None))
        i = 0
        while i < len(clean):
            w = clean[i]
            if w in WRAPPERS or re.match(r"^[A-Za-z_]\w*=", w) or (w.startswith("-") and i and clean[i - 1] in WRAPPERS):
                i += 1
                continue
            break
        self.cmd = os.path.basename(clean[i]) if i < len(clean) else ""
        self.args = [a for a in clean[i + 1:] if a not in (")", "}", ";;")]


class Analysis:
    def __init__(self):
        self.groups = []      # [(区切りごとのテキスト, [Part])]
        self.parts = []       # すべての Part（bash -c・eval の中身も）
        self.nwords = 0
        self.too_long = False


_ANALYZED = {}


def analyze(command, cwd, an=None, depth=0, top=None):
    """コマンドを区切り・パイプに分け、cd の行き先を順にたどって、各コマンドの今いる場所と語を出す。
    ヒアドキュメント（<<）があるときは区切らない（中身が別の言語のため）。同じコマンドと場所は1回だけ解く（R9）。"""
    if an is None and depth == 0 and top is None:
        key = (command, cwd)
        if key not in _ANALYZED:
            _ANALYZED[key] = analyze(command, cwd, Analysis(), 0, None)
        return _ANALYZED[key]
    groups = [command] if "<<" in command else split_top(command)
    for g in groups:
        parts = []
        for pt in ([g] if "<<" in g else split_top(g, pipes=True)):
            raw, ok = seg_words_ok(pt)
            words = [expand(w, cwd) for w in raw]
            an.nwords += len(words)
            an.too_long = an.nwords > MAX_WORDS
            p = Part(pt, cwd, words, ok)
            p.top = top if top is not None else g
            parts.append(p)
            an.parts.append(p)
            if p.cmd in ("cd", "pushd"):
                dest = next((a for a in p.args if not a.startswith("-")), None)
                if dest is None:
                    cwd = os.path.expanduser("~")
                else:
                    cwd = os.path.normpath(os.path.join(cwd, dest))
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


# find の -exec・-execdir・-ok・-okdir の直後がこれなら、起点を「動かす・消す」とみなす（R2）。
# grep・cat・wc などの読むだけは通す。シェル・言語・xargs などは中で何をするか読めないので、今までどおり止める側に入れる
FIND_EXEC_DESTROY = {"rm", "rmdir", "unlink", "mv", "rename", "shred", "srm", "trash",
                     "sh", "bash", "zsh", "dash", "ksh", "env", "xargs", "sudo", "command", "eval", "osascript",
                     "python", "python3", "perl", "ruby", "node"}


def find_destroys(args):
    """find の引数が、見つけたものを消す・動かすか（-delete、または -exec などの直後が FIND_EXEC_DESTROY）。"""
    for k, x in enumerate(args):
        if x == "-delete":
            return True
        if x in ("-exec", "-execdir", "-ok", "-okdir") and k + 1 < len(args):
            name = os.path.basename(args[k + 1])
            if name in FIND_EXEC_DESTROY or re.match(r"^python[\d.]*$", name):
                return True
    return False


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
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s*=\s*(?:pathlib\.)?Path\(\s*" + lit + r"\s*\)", code):
        if re.search(r"\b" + re.escape(m.group(1)) + PY_METHOD, code):
            out.append(m.group(2) if m.group(2) is not None else m.group(3))
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s*=\s*" + PY_CWD, code):
        if re.search(r"\b" + re.escape(m.group(1)) + PY_METHOD, code):
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
    elif c == "find" and find_destroys(a):
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


def destructive_hit(an, root=None):
    """本人のフォルダそのもの（やその親）・見張りの記録・印を動かす・消す操作か。(ラベル, 本人のフォルダ) を返す。
    文字の並びではなく実体で比べる（動かす・消すものが、保護しているものと同じか、それを含むか）。"""
    owners = owner_roots(root)
    rec = target(records_dir())
    marks = [(mk, r) for r in owners for mk in marks_of(r)]
    for p in an.parts:
        srcs, dest, base = move_sources(p)
        for s in srcs:
            for t in word_texts(s):
                for f in to_paths(t, base):
                    if rec.within(f):
                        return "見張りの記録（~/.ai-bunshin/）を動かす・消す", None
                    for r in owners:
                        if target(str(r)).within(f):
                            return "本人のフォルダそのものを動かす・消す", r
                    for mk, r in marks:
                        if mk.within(f):
                            return "本人の設定・タスクの正本の移動・削除", r
        if dest is not None and p.cmd in ("mv", "git"):
            for f in to_paths(dest, base):
                for mk, r in marks:
                    if mk.same(f):
                        return "本人の設定・タスクの正本の上書き", r
    return None


# ---- 書き込み先（R3）とリンク（R6）：コマンドごとに、どこへ書くか・どこにリンクを作るかを解く ----

PY_STR = r"(?:[rbuRBU]{1,2})?(?:'([^'\n]*)'|\"([^\"\n]*)\")"  # 引用符つき文字列（中身は2つの組のどちらか）


def _s(m, k):
    return m.group(k) if m.group(k) is not None else m.group(k + 1)


PY_OPEN_W = re.compile(r"\bopen\(\s*" + PY_STR + r"\s*,\s*(?:mode\s*=\s*)?" + PY_STR)
PY_PATH_W = re.compile(r"\bPath\(\s*" + PY_STR + r"\s*\)\s*\.\s*(write_text|write_bytes|touch|mkdir|open|hardlink_to)\(\s*(?:" + PY_STR + r")?")
PY_TWO_BOTH = re.compile(r"\b(?:shutil\.move|os\.(?:rename|replace|renames))\(\s*" + PY_STR + r"\s*,\s*" + PY_STR)
PY_TWO_DEST = re.compile(r"\b(?:shutil\.(?:copy|copy2|copyfile|copytree)|os\.link)\(\s*" + PY_STR + r"\s*,\s*" + PY_STR)
PY_ONE = re.compile(r"\bos\.(?:makedirs|mkdir|truncate|chmod|chown|utime)\(\s*" + PY_STR)


def python_writes(code):
    """python のコードの中で、書き込む・作る・動かす先になっている文字列（引用符つきで書いてあるものだけ。変数は読めない）。"""
    out = []
    for m in PY_OPEN_W.finditer(code):
        if re.search(r"[wax+]", _s(m, 3) or ""):
            out.append(_s(m, 1))
    for m in PY_PATH_W.finditer(code):
        if m.group(3) != "open" or re.search(r"[wax+]", _s(m, 4) or ""):
            out.append(_s(m, 1))
    for m in PY_TWO_BOTH.finditer(code):
        out += [_s(m, 1), _s(m, 3)]
    for m in PY_TWO_DEST.finditer(code):
        out.append(_s(m, 3))
    for m in PY_ONE.finditer(code):
        out.append(_s(m, 1))
    return [s for s in out if s]


def _opt_value(args, shorts, longs):
    """-t DIR・-tDIR・--target-directory=DIR・--target-directory DIR の値（最後のもの）。"""
    val = None
    for k, x in enumerate(args):
        if x in shorts or x in longs:
            if k + 1 < len(args):
                val = args[k + 1]
        elif any(x.startswith(lg + "=") for lg in longs):
            val = x.split("=", 1)[1]
        elif any(x.startswith(s) and len(x) > len(s) for s in shorts):
            val = x[2:]
    return val


WRITE_ALL_ARGS = {"mv", "rename", "tee", "touch", "mkdir", "truncate", "rm", "rmdir", "unlink", "shred", "srm", "trash",
                  "chmod", "chown", "chgrp", "chflags", "xattr", "setfacl", "patch"}
WRITE_LAST_ARG = {"cp", "install", "ditto", "rsync", "gcp", "ln", "scp"}


def write_targets(p):
    """Part が書き込む・作る・動かす・消す先：[(文字列, 基準の場所)]。読み出し側（cp の元など）は入れない。"""
    c, a, base = p.cmd, p.args, p.cwd
    out = list(p.redirs)
    na = _nonopt(a)
    if c in WRITE_ALL_ARGS:
        out += na
        tdir = _opt_value(a, ("-t",), ("--target-directory",)) if c == "mv" else None
        if tdir:
            out.append(tdir)
    elif c in WRITE_LAST_ARG:
        tdir = _opt_value(a, ("-t",), ("--target-directory",))
        if tdir:
            out.append(tdir)
        elif len(na) >= 2:
            out.append(na[-1])
        elif c == "ln" and na:
            out.append(os.path.basename(na[0].rstrip("/")) or na[0])
    elif c == "dd":
        out += [x[3:] for x in a if x.startswith("of=")]
    elif c in ("sed", "perl", "ruby") and any(re.match(r"^-[A-Za-z]*i", x) or x.startswith("--in-place") for x in a):
        out += na
    elif c == "unzip" and not any(x in ("-l", "-t", "-v", "-Z", "-p", "-z") for x in a):
        out.append(_opt_value(a, ("-d",), ()) or ".")
    elif c in ("tar", "bsdtar", "gtar"):
        flags = "".join(x.lstrip("-") for x in a if re.match(r"^-[A-Za-z]+$", x))
        if a and re.match(r"^[A-Za-z]+$", a[0]):
            flags += a[0]  # tar xzf のような、- のない書き方
        if "x" in flags or any(x in ("--extract", "--get") for x in a):
            out.append(_opt_value(a, ("-C",), ("--directory",)) or ".")
        if "--remove-files" in a:
            out += na
    srcs, dest, _ = move_sources(p)  # 動かす・消す元（mv・git mv・find -delete・zip -m・python の os.rename など）
    out += srcs
    if dest:
        out.append(dest)
    if re.search(r"\bpython[\d.]*\b", p.text):
        out += python_writes(p.text)
    return [(t, base) for t in out if t]


def input_hit(an, root):
    """03_インプット（元データ。読むだけ）へ書き込む・作る・そこから動かす・消す操作か（R3）。読み出し（cp の元など）は通す。"""
    t = target(os.path.join(str(root), "03_インプット"))
    for p in an.parts:
        for text, base in write_targets(p):
            for w in word_texts(text):
                for f in to_paths(w, base):
                    if t.covers(f):
                        return "元データの移動・上書き"
    return None


NO_DEREF = re.compile(r"^-[A-Za-z]*[nhT]")  # ln -n・-h・-T：行き先がリンクやフォルダでも、それ自体を置き換える


def link_pairs(p):
    """リンクを作る操作：[(元の文字列, [行き先の文字列], 基準の場所, シンボリックか, 置き換えるか)]。"""
    out = []
    if p.cmd == "ln":
        a, sym, tdir, plain, skip, repl = p.args, False, None, [], False, False
        for k, x in enumerate(a):
            if skip:
                skip = False
                continue
            if x in ("-t", "--target-directory"):
                tdir = a[k + 1] if k + 1 < len(a) else None
                skip = True
            elif x.startswith("--target-directory="):
                tdir = x.split("=", 1)[1]
            elif x == "--symbolic":
                sym = True
            elif x in ("--no-dereference", "--no-target-directory"):
                repl = True
            elif x.startswith("--"):
                continue
            elif x.startswith("-t") and len(x) > 2:
                tdir = x[2:]
            elif x.startswith("-") and len(x) > 1:
                sym = sym or "s" in x
                repl = repl or bool(NO_DEREF.match(x))
                if x.endswith("t"):
                    tdir = a[k + 1] if k + 1 < len(a) else None
                    skip = True
            else:
                plain.append(x)
        if tdir is not None:
            for s in plain:
                out.append((s, [os.path.join(tdir, os.path.basename(s.rstrip("/")))], sym, repl))
        elif len(plain) == 1:
            out.append((plain[0], [os.path.basename(plain[0].rstrip("/")) or plain[0]], sym, repl))
        elif len(plain) >= 2:
            d = plain[-1]
            for s in plain[:-1]:
                dests = [os.path.join(d, os.path.basename(s.rstrip("/")))]
                full = os.path.join(p.cwd, os.path.expanduser(d))
                if repl or not os.path.isdir(full) or os.path.islink(full):
                    # 行き先がフォルダでなければ、その名前でリンクを作る。リンクや -n・-h・-T なら、行き先そのものを置き換えうる
                    dests.append(d)
                out.append((s, dests, sym, len(dests) > 1))
    if re.search(r"\bpython[\d.]*\b", p.text):
        for m in re.finditer(r"\bos\.symlink\(\s*" + PY_STR + r"\s*,\s*" + PY_STR, p.text):
            out.append((_s(m, 1), [_s(m, 3)], True, False))
        for m in re.finditer(r"\bPath\(\s*" + PY_STR + r"\s*\)\s*\.\s*symlink_to\(\s*" + PY_STR, p.text):
            out.append((_s(m, 3), [_s(m, 1)], True, False))
    return [(s, [d for d in ds if d], sym, repl) for s, ds, sym, repl in out if s]


LINK_LABEL = "保護しているものへのリンク（リンクを通すと見張りが行き先を読めなくなる。作らない）"


def link_hit(an, root=None):
    """同じコマンドの中で作るリンク（R6）：元か行き先が、保護しているもの（またはその下）なら止める。
    元が保護しているものを含む（本人のフォルダ・その親・印のあるフォルダ）ときも止める。
    リンクの元は、リンクを置く場所から数える（ln -s ../03_インプット 02_成果物/lk）。今いる場所から数えた形も見る。"""
    pairs = [(p, x) for p in an.parts for x in link_pairs(p)]
    if not pairs:
        return None
    owners = owner_roots(root)
    content, holders = content_targets(owners), holder_targets(owners)

    def bad(f, as_dest=False, replace=False):
        if any(t.covers(f) for t in content):
            return True
        if as_dest:
            return replace and any(t.within(f) for t in holders)
        return any(t.within(f) for t in holders)

    for p, (s, dests, sym, repl) in pairs:
        dpaths = set()
        for d in dests:
            dpaths |= to_paths(d, p.cwd)
        for f in dpaths:
            if bad(f, as_dest=True, replace=repl):
                return LINK_LABEL
        if not sym:
            continue  # ハードリンクの元は、ここでは見ない（書き込みのときに実体で比べる）
        spaths = set(to_paths(s, p.cwd))
        for f in dpaths:
            spaths |= to_paths(s, os.path.dirname(f))
        for f in spaths:
            if bad(f):
                return LINK_LABEL
    return None


RECORD_WRITE = re.compile(r"(?:>>?(?!\s*(?:&|/dev/null\b))|\btee\b|\s-i\b|\b(?:cp|mv|ln|rsync|install|touch|mkdir|rm|rmdir|unlink|shred|trash|rename|"
                          r"truncate|dd|unzip|tar|zip|patch|chmod|chflags|chown|find|sed|perl|ruby|node|python[\d.]*)\b|"
                          r"open\(|\.write|write_text|writeFile|\bcd\b|\bpushd\b)")


def records_bash_hit(an):
    """見張りの記録（~/.ai-bunshin/）に書く Bash か。読むだけ（cat・ls など）は通す。
    記録の名前が出てくる、またはパス・cd の行き先が記録の置き場所の中の区切りに、書き込みの語があれば止める。"""
    rec = target(records_dir())
    for p in an.parts:
        top = quiet(p.top)
        if not RECORD_WRITE.search(top):
            continue
        if re.search(r"\.ai-bunshin(?=$|[/\s\"';&|)])", top, re.I) or any(
                rec.covers(f) for f in part_paths(p) | path_forms(p.cwd)):  # 実体で比べる（大文字小文字・リンク・ハードリンク）
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
    if p.cmd == "find" and (find_destroys(p.args) or any(x in ("-fprint", "-fprintf", "-fls") for x in p.args)):
        return False  # -exec grep などの読むだけは、読むだけのまま（R2）
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
    # 本人のフォルダの名前が語に含まれるだけでは当てない（R1）。パスとして解いたものが、記録の実体と同じか、その下か、その親のときだけ
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
            for f in cands_anc:  # 本人のフォルダの親を指す（chmod -R ~/workspace など）。実体で比べる
                for rf, r in recs:
                    if target(str(r)).within(f):
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
    command = quiet(command)  # 2>/dev/null・2>&1 は書き込みと見ない（R4）
    if not WRITE_WORDS.search(command):
        return None
    tokens = re.findall(r"[\"']?([^\s\"';&|()]+)[\"']?", command)
    copy_hit = re.search(r"\.claude/plugins(?:/|$|[\s\"'])", command)
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


# プラグイン・見張りの記録・本人のフォルダそのもの・保護しているものへのリンクは、本人の許可する例外（ng_allow）でも外さない
NO_EXCEPTION_LABELS = ("プラグインのコピーの書き換え", "共通部分（プラグインの元）の書き換え", "見張りの記録",
                       "本人のフォルダそのものを動かす・消す", "保護しているものへのリンク")
RECORDS_LABEL = "見張りの記録（~/.ai-bunshin/）の書き換え（本人のフォルダを覚えておく所。消すと見張りが外れる）"
PLUGIN_COPY_LABEL = "プラグインのコピーの書き換え（Claude Code が読み込む共通部分。元を直して更新する）"
WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")


def global_check(payload, root):
    """どこからでも効かせる保護：プラグインのコピー、見張りの記録、本人のフォルダそのもの・印を動かす・消す操作、
    保護しているものへのリンク。(ラベル, 対象, ログを書く本人のフォルダ) を返す。"""
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
        if link_hit(an, root):
            return LINK_LABEL, command, root
    elif tool in WRITE_TOOLS:
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        if path:
            forms = path_forms(path, base_cwd(payload, root))
            if plugin_area(path) == "copy" or covers_any(target(plugins_dir()), forms):
                return PLUGIN_COPY_LABEL, path, root
            if covers_any(target(records_dir()), forms):  # 実体で比べる（大文字小文字・リンク・ハードリンク）
                return RECORDS_LABEL, path, root
    return None


def rels_in_root(path, root, base):
    """path が root の中なら、root からの相対パス（NFC）のリスト。リンクを解かない道と解いた道の、すべての形で比べる（R7）。"""
    rforms = path_forms(root)
    out = []
    for f in sorted(path_forms(path, base)):
        for r in rforms:
            if is_under(f, r) and f != r:
                out.append(f[len(r.rstrip(os.sep)) + 1:].replace(os.sep, "/"))
    return out


def rel_in_root(path, root, base):
    rels = rels_in_root(path, root, base)
    return rels[0] if rels else None


def check(payload, root, command=None):
    """本人のフォルダ root の規則で判定する。command を渡したら、Bash はその部分だけを見る（外のセッション）。"""
    tool = payload.get("tool_name", "")
    inp = payload.get("tool_input") or {}
    if tool == "Bash":
        full = inp.get("command", "")
        flat = normalize(full if command is None else command)
        q = quiet(flat)  # 2>/dev/null・2>&1 などを除いてから規則を当てる（R4）
        for label, pat in BASH_RULES:
            if rule_hit(pat, q):
                if (label in DEV_ALLOWED and not GLOBAL_INSTALL.search(flat) and not pip_outside_venv(flat)
                        and in_dev_area(flat, payload, root)):
                    continue
                return label, full
        label = input_hit(analyze(flat, base_cwd(payload, root)), root)
        if label is None and "<<" in q and any(m(q) for m in LEGACY_INPUT_RULES):
            label = "元データの移動・上書き"
        if label:
            return label, full
    elif tool in WRITE_TOOLS:
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        if not path:
            return None
        if plugin_area(path) == "source" and not is_maintainer(root):
            return "共通部分（プラグインの元）の書き換え（メンテする人だけ。提案の下書きにする）", path
        base = base_cwd(payload, root)
        forms = path_forms(path, base)
        for label, rel in PROTECTED_TARGETS:  # 実体で比べる（リンク経由・大文字小文字・NFD・ハードリンク。R5・R7）
            if covers_any(target(os.path.join(str(root), *rel)), forms):
                return label, "/".join(rel)
        for rel in rels_in_root(path, root, base):  # 文字の並びでも、すべての形で見る（前の比べ方も残す）
            for label, pat in PROTECTED_PATHS:
                if re.search(pat, rel, re.I):
                    return label, rel
    return None


def deny(label, what, root, tool=None):
    reason = (f"NG（{label}）：この操作は AI 分身では行いません。必要なら止めて、本人へのお願い（手順付き。"
              f"コマンドは `! …` の形で示す）にしてください。対象：{what[:200]}")
    log = root / "00_タスク管理" / "data" / "ng_log.jsonl" if root is not None and not DRY_RUN else None
    try:
        if log is not None and log.parent.exists():
            with log.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "tool": tool,
                                    "label": label, "target": what[:500]}, ensure_ascii=False) + "\n")
    except OSError:
        pass
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}, ensure_ascii=False))


def judge(payload):
    """判定する。None（当たらない）か、(判定 "deny"／"allow"（本人の許可する例外で通す）, ラベル, 対象, ログを書く本人のフォルダ)。"""
    root = project_dir(payload)
    hit = global_check(payload, root)  # プラグイン・見張りの記録・本人のフォルダそのもの・リンク（どこからでも）
    label = what = None
    log_root = root
    if hit:
        label, what, log_root = hit
    elif root is not None:
        h = check(payload, root)
        if h:
            label, what = h
    else:  # 外で始めたセッション：操作が本人のフォルダを指すなら、その本人のフォルダを基準に、指している部分を判定
        for r, part in roots_from_input(payload):
            h = check(payload, r, part)
            if h:
                label, what = h
                log_root = r
                break
    if label is None:
        return None
    if log_root is not None and not label.startswith(NO_EXCEPTION_LABELS) and any(p.search(what) for p in allow_patterns(log_root)):
        return "allow", label, what, log_root
    return "deny", label, what, log_root


def run_guard():
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise ValueError("payload is not an object")
    res = judge(payload)
    if res and res[0] == "deny":
        deny(res[1], res[2], res[3], payload.get("tool_name"))
    return 0


def explain(command):
    """--explain "<コマンド>"：今いる場所で Bash のコマンドを判定し、判定（deny／pass）と理由の語を出す。
    見張りの記録（owners.json）にも ng_log にも書かない。"""
    global DRY_RUN
    DRY_RUN = True
    try:
        cwd = os.getcwd()
    except OSError:
        cwd = os.path.expanduser("~")
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd}
    try:
        res = judge(payload)
    except Exception as e:  # 本物の見張りと同じく、本人のフォルダの中なら止める側
        try:
            root = project_dir({})
        except Exception:
            root = None
        print("判定：" + ("deny" if root is not None else "pass"))
        print(f"理由：見張りの入力を読めませんでした（{type(e).__name__}）")
        return 0
    if res is None:
        print("判定：pass")
        print("理由：当たる規則なし")
        return 0
    decision, label, what, log_root = res
    if decision == "allow":
        print("判定：pass")
        print(f"理由：本人の許可する例外（ng_allow）に一致（当たった規則：{label}）")
    else:
        print("判定：deny")
        print(f"理由：{label}")
    print(f"本人のフォルダ：{log_root if log_root is not None else '（なし）'}")
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--explain":
        if len(sys.argv) < 3:
            print('使い方：python3 ng_guard.py --explain "<コマンド>"', file=sys.stderr)
            return 2
        return explain(" ".join(sys.argv[2:]))
    try:
        return run_guard()
    except Exception:
        # 入力が壊れていて読めなかった：本人のフォルダの中（起動場所から上にたどって見つかる）なら止める、外なら通す
        try:
            root = project_dir({})
        except Exception:
            root = None
        if root is not None:
            deny("見張りの入力を読めませんでした", "（入力不明）", root)
        return 0


if __name__ == "__main__":
    sys.exit(main())
