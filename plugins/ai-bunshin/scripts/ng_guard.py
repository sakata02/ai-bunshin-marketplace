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

方式（T058 の決め。2026-10-31 坂田さん「凍結して小さく終える」）：見張りは「前の版（4560a92）より悪くしない」。
- 前の版の判定（ng_guard_legacy.py。4560a92 の写し）を、すべてのコマンドに当てる。前の版が止めたものは止める
- 新しい判定（構造で読む・実体で比べる）が止めたものも止める
- 前の版が止めて新しい判定が通すものは、前の版の当たり方が R1〜R4 だけで、構造で読み切れて、行き先が守っているものの外だと
  確かめられた形（R1〜R4 の通す側）のときだけ通す。確かめ方は、前の版から R1〜R4 の当たり方だけを外して判定し直し、それでも通ること
  （R1：名前の部分一致、R2：find -exec の後ろが読むだけ、R3：03_インプット を読むだけ（コマンドが構造で読めるときだけ）、
  R4：2>/dev/null・2>&1。プラグインのコピーを読むだけ（cat・ls・diff、コピーの中のスクリプトを動かすだけ）も同じ扱い）
読み方：ヒアドキュメントの本文は、TAG を語全体として読んで取り除いてから区切る（本文はデータ。python3 -・bash・sh に渡す本文だけ
コードとして読む）。コメント・$(( )) の中の << は見ない。読み切れない形（TAG が読めない・終わりの行が無い・本文をパイプで
シェルや言語に渡す）は取り除かずに、前の版と同じ全体の判定に任せる。外のセッションでは、本人のフォルダを探すときだけ、
すべての本文のパスも候補に入れ、見つかったら本文を含めた全体で判定する。
起動役（xargs・timeout・nice・env・time・nohup・caffeinate・parallel・sudo・find -exec・env -S）はほどいて中のコマンドを読む。
表に無いコマンドの引数に、書き込み・移動のコマンドの名前が出てきたら、そこから先も中のコマンドとして読む（表に名前を足していかない）。
cd の行き先は to_paths と同じ解き方にする。ワイルドカードの当たりが2つ以上で守っているものに関わるとき・今いる場所が 1024 文字を
超えたときは、読み切れない扱いにして、そのあとの読むだけでない操作を止める。
プラグインのコピー：書き込み先・移動の元・今いる場所を、実体で ~/.claude/plugins と比べる。claude plugin install|update|uninstall と
claude plugin marketplace add|update|remove は、メンテする人でも止める（本人へのお願い（`! claude plugin update …`）にする）。
締め切り：5 秒（hooks.json の timeout 10 秒より短い）。hook が時間切れになると Claude Code はコマンドを実行してしまうため。
超えたら、本人のフォルダの中は止める。外は、記録にある本人のフォルダが文面に出ていれば止め、出ていなければ通す。
本番では環境変数などで締め切りを変えられない（テストは decide(…, deadline=) の引数で短くする）。

既知の残り（止まらない・誤って止まるのが今の仕様。見張りは AI のうっかりと外からの指示を止める安全ベルトで、完全ではない。
凍結したので、ここから先は強くしない。強くするなら、別に OS の力で守る調べものをする）
- やらないと決めたもの（T092 にも回さない）：外での `ln -s <親> L && mv L/…`（リンクの元が本人のフォルダの親）、`cd ~+/…`、
  python の書き方違い（キーワード引数・Path() を挟む・変数や連結）、`Write <外>/<ループするリンク>/../../…` など、部下D の
  T092 行き・既知の残りの一覧のもの
- 変数・展開・ヒアドキュメントやパイプでシェルに渡す中身・書き込みのコマンドの列挙の抜け（sort -o・gzip・split・
  git checkout <版> -- <ファイル>・git clone・cp -R で外から 03_インプット ごと上書き など）は、前の版と同じだけしか止まらない
- プラグインのコピーのパスを変数で受け渡してから書く形（X=~/.claude/plugins; echo > $X/a）は止まらない（前の版も同じ）
- ~$(whoami) のような展開を含む ~user は解かない
- 外のセッションで、node・perl などに本文を渡して本人のフォルダを消す形（node <<EOF … rmSync …）は、前の版と同じく止まらない
- 外のセッションで、本文に本人のフォルダのパスが出てくるだけのデータ（tee /tmp/s.sh <<EOF … rm -rf <本人のフォルダ> …）も、
  前の版と同じく本文を含めた全体で判定するので止まる
- 大文字小文字を区別するディスク（APFS の区別する形式など）では、Write の文字の並びでの比べ方（re.I）が残っているため、
  別物の .CLAUDE/settings.json への Write も止まる。止める側に寄るので許す（指摘10）
- ハードリンクを探す上限（HARDLINK_SCAN_MAX）は、フォルダの区切りでしか数えていないので、実際には上限を超えて探す
  （20,500 個で 0.11 秒なので速さは問題なし）。上限を超えたところにあるハードリンクは見つからない（指摘12）
- 本人のフォルダから find . -exec sed -i … のように、起点が 03_インプット を含む形は、前の版と同じだけしか止まらない
- 解けないパス（リンクのループなど）は、動かす・消す元にあるときだけ止める。Write の行き先なら通す（OS も書けないため）
- Windows など setitimer の無い所では、締め切りを仕掛けられない
- 前の版の誤停止（文書の中の語・外で読み出しの後ろの区切りまで本人の規則を当てるなど）は、R1〜R4 の形のほかは残る（T061）。
  T061（T061b で狭めた）で減らしたもの：次の形の1文だけ。形が少しでも外れたら、何もせず前の版の判定に任せる（止める側）。
  ・cd <元> && 読むだけの1コマンド（sed -n・cat・head・tail・wc・ls・grep・git status|log|diff|show）
  ・cat > 先 <<'EOF'／cat <<'EOF' > 先／tee 先 <<'EOF'（先は .md .txt .csv .log。区切りは引用符付きだけ）
  ・python3 - <<'EOF'（区切りは引用符付きだけ。文字列と変数名はならし、os.remove( などの呼び出しは残す）
  ・git commit -m "…"／git tag -m "…"（前に git add … && が付くのは可。本文に $( ・` があればならさない）
  残るもの（止まるままの誤検知）：上の形から外れるもの（cd のあとに && ・パイプが続く、区切りが引用符なしのヒアドキュメント、
  git commit -m "$(cat <<'EOF' …)"、git -C 付きなど）・python の本文にプラグインのコピーの場所の文字と書き込みの語が同居する形・
  bash -c の中の git commit の本文・python -c の文字列・読み込み場所の判定（installed_plugins.json）は入れていない
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

# 締め切り（秒）。hook が時間切れになると Claude Code はコマンドを実行してしまう（10/30 指揮官の実験）ので、
# hooks.json の timeout（10 秒）より短く切り、切れたら fallback_decision で決める（中は止める）。
# 本番では環境変数などから変えられない。テストは decide(…, deadline=) の引数で短くする（長くはできない）。
DEADLINE_SEC = 5.0


class DeadlineExceeded(BaseException):
    """締め切りを超えた（except Exception で受けられないよう BaseException にする）。"""


def deadline_seconds(sec=None):
    """締め切りの秒。引数で短くできる（テスト用）。DEADLINE_SEC より長く・0 以下・数でない値は DEADLINE_SEC。"""
    try:
        v = float(DEADLINE_SEC if sec is None else sec)
    except (TypeError, ValueError):
        return DEADLINE_SEC
    return v if 0 < v < DEADLINE_SEC else DEADLINE_SEC


def start_deadline(sec):
    """締め切りを仕掛ける。Windows などで setitimer が無いときは仕掛けない（既知の残り）。"""
    import signal
    if not hasattr(signal, "setitimer"):
        return False

    def _fire(signum, frame):
        raise DeadlineExceeded()
    signal.signal(signal.SIGALRM, _fire)
    signal.setitimer(signal.ITIMER_REAL, sec)
    return True


def stop_deadline():
    import signal
    if hasattr(signal, "setitimer"):
        signal.setitimer(signal.ITIMER_REAL, 0)

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
         r"branch\s+-D|checkout\s+(?:--|\.))(?=[\s'\"]|$)"),
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


_QUIET = {}


def quiet(text):
    r = _QUIET.get(text)
    if r is None:
        r = _QUIET[text] = NULL_REDIR.sub(" ", text)
    return r


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
    ("共通ルールの詳細の自動コピー（プラグイン側を直す）", r"^\.claude/ai-bunshin-details(?:/|$)"),
]


# 同じものを実体（st_dev・st_ino）でも比べる：(理由, 本人のフォルダからの道)
PROTECTED_TARGETS = [
    ("元データ（読むだけ）", ("03_インプット",)),
    ("権限・設定", (".claude", "settings.json")),
    ("権限・設定", (".claude", "settings.local.json")),
    ("hook・権限（.claude の設定）", (".claude", "hooks")),
    ("共通ルールの自動コピー（プラグイン側を直す）", (".claude", "rules", "ai-bunshin-common.md")),
    ("共通ルールの詳細の自動コピー（プラグイン側を直す）", (".claude", "ai-bunshin-details")),
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
        a = fast_abspath(t)
        out = {nfc(a)}
        ra = fast_realpath(a)
        out.add(nfc(ra))  # 文字の上で .. をたどった形も見る（止める側）
        out.add(nfc(ra if t == a else os.path.realpath(t)))  # 「リンク/..」は、リンクを解いてから .. をたどる（OS と同じ）
        out = frozenset(out)
    except (OSError, ValueError, TypeError):
        out = frozenset()
    _FORMS[key] = out
    return out


def fast_abspath(t):
    """os.path.abspath と同じ結果。すでに整った絶対パス（// ・ /. ・ 末尾の / が無い）なら、そのまま返す（長いパスで遅くしない）。"""
    if t.startswith("/") and "//" not in t and "/." not in t and (len(t) == 1 or not t.endswith("/")):
        return t
    return os.path.abspath(t)


def join_norm(cwd, dest):
    """os.path.normpath(os.path.join(cwd, dest)) と同じ結果。cwd が整っていて dest が単純な名前の並びなら、つなぐだけ。"""
    if (cwd.startswith("/") and "//" not in cwd and "/." not in cwd and (len(cwd) == 1 or not cwd.endswith("/"))
            and dest and not dest.startswith("/") and "//" not in dest and not dest.endswith("/")
            and all(x not in (".", "..", "") for x in dest.split("/"))):
        return cwd.rstrip("/") + "/" + dest
    return os.path.normpath(os.path.join(cwd, dest))


_REAL = {}


def fast_realpath(a):
    """os.path.realpath と同じ結果（a は abspath の形）。まだ無いパスは、親の結果に名前をつなぐ（深い場所を何度も解くときに
    長さの2乗にしない。指摘3）。"""
    r = _REAL.get(a)
    if r is not None:
        return r
    cur, names = a, []
    while True:
        hit = _REAL.get(cur)
        if hit is not None:
            base = hit
            break
        parent = os.path.dirname(cur)
        if parent == cur or os.path.lexists(cur):
            base = _REAL[cur] = os.path.realpath(cur)
            break
        names.append(os.path.basename(cur))
        cur = parent
    for name in reversed(names):  # まだ無い名前は、そのままつなぐ（リンクではないので解かない）
        cur = os.path.join(cur, name)
        base = _REAL[cur] = os.path.join(base, name)
    return base


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
            hit = _LOCATE.get(cur) if cur is not p else None
            if hit is not None:  # 親の結果を使い回す（深い場所を何度も解くときに長さの2乗にしない。指摘3）
                r = (hit[0], hit[1], hit[2] + tuple(reversed(rest)))
                break
            i = ident(cur)
            parent = os.path.dirname(cur)
            if i is not None or parent == cur:
                r = (cur, i, tuple(reversed(rest)))
                break
            rest.append(nfc(os.path.basename(cur)).casefold())
            cur = parent
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
    if cwd == UNKNOWN_CWD and not os.path.isabs(os.path.expanduser(t)):
        return set()  # 今いる場所を読み切れない：相対パスは解かない（check で止める側に倒す）
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


# 前に付くだけの語（コマンドの頭に来ても、中のコマンドが本体）
KEYWORDS = {"then", "do", "else", "elif", "if", "while", "until", "!", "{", "("}

# 起動役（中のコマンドを動かすもの）と、値を1つ取るオプションの表（指摘2）。
# ここに無いオプションは、値を取らない（-0・-r・-t など）か、値をくっつけて書く形（-I{}・-n5・--max-args=1）として1語で読む
LAUNCHERS = {
    "xargs": {"-I", "-J", "-L", "-n", "-P", "-R", "-S", "-s", "-E", "-a", "-d", "--max-args", "--max-procs",
              "--arg-file", "--delimiter", "--max-chars", "--process-slot-var", "--max-lines", "--replace", "--eof"},
    "timeout": {"-s", "-k", "--signal", "--kill-after"},
    "nice": {"-n", "--adjustment"},
    "env": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string", "-P"},
    "time": {"-o", "-f", "--output", "--format"},
    "nohup": set(),
    "caffeinate": {"-t", "-w"},
    "parallel": {"-j", "-P", "-S", "-a", "-d", "-I", "-n", "-N", "-E", "-C", "--jobs", "--sshlogin", "--arg-file",
                 "--delimiter", "--colsep"},
    "sudo": {"-u", "-g", "-C", "-h", "-p", "-U", "-r", "-t", "-D"},
    "stdbuf": {"-i", "-o", "-e"},
    "command": set(), "builtin": set(), "exec": {"-a"},
}
LAUNCHER_POSITIONAL = {"timeout": 1}  # オプションのあとに、コマンドの前に来る語の数（timeout 5 cmd）
FIND_EXEC = ("-exec", "-execdir", "-ok", "-okdir")
# find -exec の中で、これなら起点に書き込まない（読むだけ）。これ以外は起点を書き込み先とみなす（指摘2）
FIND_READ_ONLY = {"grep", "egrep", "fgrep", "rg", "cat", "head", "tail", "wc", "ls", "stat", "file", "md5", "md5sum",
                  "shasum", "sha1sum", "sha256sum", "echo", "printf", "test", "[", "basename", "dirname", "realpath",
                  "readlink", "du", "diff", "cmp", "less", "more", "jq", "true", "false", "nl", "od", "xxd", "strings"}

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
ASSIGN = re.compile(r"^[A-Za-z_]\w*=")
BODY_RECEIVERS = re.compile(r"^(?:python[\d.]*|bash|sh|zsh|dash|ksh)$")  # 本文をコードとして読むコマンド


def unwrap(words, cwd):
    """頭に付く語と起動役（xargs・timeout・nice・env・time・nohup・caffeinate・parallel・sudo など）をほどく。
    (中のコマンドの位置, 今いる場所, 起動役があったか, env -S の文字列)。env -C／--chdir は今いる場所を変える。"""
    i, launched, split = 0, False, None
    while i < len(words):
        w = words[i]
        if w in KEYWORDS or ASSIGN.match(w):
            i += 1
            continue
        name = os.path.basename(w)
        if name not in LAUNCHERS:
            break
        launched = launched or name not in ("command", "builtin", "exec")
        vals, pos = LAUNCHERS[name], LAUNCHER_POSITIONAL.get(name, 0)
        i += 1
        while i < len(words):
            x = words[i]
            if x == "--":
                i += 1
                break
            if x.startswith("-") and len(x) > 1:
                if name == "env" and (x in ("-C", "--chdir") or x.startswith("--chdir=")):
                    d = x.split("=", 1)[1] if "=" in x else (words[i + 1] if i + 1 < len(words) else "")
                    cwd = os.path.normpath(os.path.join(cwd, d)) if d else cwd
                if name == "env" and (x in ("-S", "--split-string") or x.startswith("--split-string=") or
                                      (x.startswith("-S") and len(x) > 2)):
                    split = x.split("=", 1)[1] if x.startswith("--split-string=") else (
                        x[2:] if x.startswith("-S") and len(x) > 2 else (words[i + 1] if i + 1 < len(words) else ""))
                i += 2 if (x in vals and "=" not in x) else 1
                continue
            if name == "env" and ASSIGN.match(x):
                i += 1
                continue
            if pos:
                pos -= 1
                i += 1
                continue
            break
    return i, cwd, launched, split


# 起動役の表に無いコマンド（chrt・ionice・doas・script・unbuffer・arch・taskpolicy・sandbox-exec・watch・flock・gtimeout・npx など）の
# 引数に、書き込み・移動のコマンドの名前が出てきたら、そこから先を中のコマンドとしても読む（表に名前を足していかない。T058 の決め）。
# 引数を自分で解釈するだけのコマンド（echo・grep・git など）は除く
INNER_CMDS = {"mv", "cp", "gcp", "rm", "rmdir", "unlink", "ln", "link", "tee", "touch", "mkdir", "install", "ditto", "rsync",
              "truncate", "dd", "unzip", "tar", "sed", "gsed", "perl", "ruby", "node", "python", "python3", "bash", "sh",
              "zsh", "dash", "ksh", "fish", "find", "xargs", "chmod", "chown", "chgrp", "chflags", "shred", "srm", "trash",
              "env", "eval", "rename", "patch", "zip", "gzip", "split", "sort", "git", "curl", "wget", "scp"}
NON_LAUNCHERS = {"", "echo", "printf", "grep", "egrep", "fgrep", "rg", "git", "man", "which", "type", "help", "whatis",
                 "apropos", "cat", "less", "more", "head", "tail", "wc", "ls", "diff", "cmp", "comm", "sort", "uniq",
                 "cut", "tr", "awk", "sed", "gsed", "perl", "ruby", "node", "python", "python3", "bash", "sh", "zsh",
                 "dash", "ksh", "fish", "cd", "pushd", "popd", "test", "[", "true", "false", "jq", "open", "say",
                 "osascript", "claude", "gh", "npm", "yarn", "pnpm", "pip", "pip3", "brew", "make", "docker", "kubectl",
                 "ssh", "tmux", "find", "xargs", "env", "eval", "read", "export", "set", "unset", "source", ".",
                 "local", "declare", "alias", "history", "date", "sleep", "stat", "file", "du", "df", "pwd", "realpath",
                 "readlink", "basename", "dirname", "mkdir", "touch", "cp", "mv", "rm", "ln", "tee", "chmod", "tar",
                 "unzip", "zip", "curl", "wget", "security", "plutil", "launchctl", "defaults", "mdls", "md5", "shasum",
                 "base64", "od", "xxd", "strings", "nl", "column", "fold", "fmt", "expand", "paste", "join", "seq",
                 "yes", "for", "case", "function", "return", "exit", "break", "continue", "trap", "wait", "kill",
                 "time", "nice", "timeout", "nohup", "caffeinate", "parallel", "sudo", "stdbuf", "command", "builtin",
                 "exec", "printenv", "whoami", "id", "uname", "hostname", "sw_vers", "ps", "pgrep", "lsof", "top",
                 "code", "vim", "vi", "nano", "emacs", "pbcopy", "pbpaste", "afplay", "mdfind", "shellcheck", "bc"}


class Part:
    """パイプでつながった1つのコマンド。起動役はほどいて、中のコマンドを cmd・args にする。"""

    def __init__(self, text, cwd, words, lex_ok=True, body="", cwd_unknown=False):
        self.text, self.cwd, self.words = text, cwd, words
        self.cwd_unknown = cwd_unknown
        self.body = body
        self.guessed = False  # 表に無い起動役の引数から推し量って読んだ部分か
        clean, self.redirs = split_redirs(words)
        i, self.cwd, self.launched, self.env_split = unwrap(clean, cwd)
        self.cmd = os.path.basename(clean[i]) if i < len(clean) else ""
        args = [a for a in clean[i + 1:] if a not in (")", "}", ";;")]
        if self.cmd == "parallel" or (self.launched and ":::" in args):
            args = args[:args.index(":::")] if ":::" in args else args
        self.args = args
        self.extra_words = []
        if body and BODY_RECEIVERS.match(self.cmd):
            # python3 -・bash・sh に渡す本文は、前の版と同じくコードとして読む
            self.text = text + "\n" + body
            self.extra_words = seg_words(body)
        if not lex_ok or (body and BODY_RECEIVERS.match(self.cmd)):  # 語に分けきれない：文字の並びからも向け先を拾う
            for m in RAW_REDIR.finditer(quiet(self.text)):
                self.redirs.append(next(g for g in m.groups() if g is not None))
        self.find_execs = []  # find の -exec の中のコマンド（語のリスト）
        if self.cmd == "find":
            a, k = self.args, 0
            while k < len(a):
                if a[k] in FIND_EXEC:
                    j = k + 1
                    while j < len(a) and a[j] not in (";", "+", "\\;"):
                        j += 1
                    if j > k + 1:
                        self.find_execs.append(a[k + 1:j])
                    k = j
                k += 1

    @property
    def all_words(self):
        return self.words + self.extra_words

    def find_starts(self):
        """find の起点。前に付くオプション（-L・-H・-P・-x・-E・-s・-X・-O<n>・-D <値>・-f <起点>）を読み飛ばす（指摘5）。"""
        a, k, starts = self.args, 0, []
        while k < len(a):
            x = a[k]
            if x in ("-L", "-H", "-P", "-x", "-E", "-s", "-X") or re.match(r"^-O\d*$", x):
                k += 1
                continue
            if x == "-D" and k + 1 < len(a):
                k += 2
                continue
            if x == "-f" and k + 1 < len(a):
                starts.append(a[k + 1])
                k += 2
                continue
            break
        for x in a[k:]:
            if x.startswith("-") or x in ("(", "!", ")"):
                break
            starts.append(x)
        return starts or ["."]

    def find_outputs(self):
        """find の -fprint・-fprint0・-fprintf・-fls の書き込み先（指摘5）。"""
        a = self.args
        return [a[k + 1] for k, x in enumerate(a[:-1]) if x in ("-fprint", "-fprint0", "-fprintf", "-fls")]


class Analysis:
    def __init__(self):
        self.groups = []      # [(区切りごとのテキスト, [Part])]
        self.parts = []       # すべての Part（bash -c・eval の中身、find -exec の中身、推し量った中身も）
        self.nwords = 0
        self.too_long = False
        self.bodies = []      # ヒアドキュメントの本文
        self.unreadable = False  # ヒアドキュメントを読み切れない（前の版と同じ全体の判定に任せる）


HEREDOC_STOP = set(" \t\n;&|<>()")


def _heredoc_word(text, i):
    """<<（と -）の後ろの語を読む。(終わりの位置, 引用符を外した TAG)。語全体を1つの TAG として読む（<<E"OF" は EOF）。"""
    n, out = len(text), []
    while i < n and text[i] in " \t":
        i += 1
    while i < n and text[i] not in HEREDOC_STOP:
        c = text[i]
        if c in "'\"":
            j = text.find(c, i + 1)
            if j < 0:
                return i, ""
            out.append(text[i + 1:j])
            i = j + 1
            continue
        if c == "\\" and i + 1 < n:
            out.append(text[i + 1])
            i += 2
            continue
        if c == "$" or c == "`":
            return i, ""  # 展開を含む TAG は読み切れない
        out.append(c)
        i += 1
    return i, "".join(out)


def strip_heredocs(text):
    """ヒアドキュメントの本文（<<TAG の次の行から TAG の行まで）を取り除く。(本文を除いたコマンド, 本文のリスト, 読み切れたか)。
    TAG は語全体（<<E"OF"・<<'E'OF・<<\\EOF は EOF）。<<<・引用符の中・コメント（# の後ろ）・$(( )) と (( )) の中の << は見ない。
    TAG が読めない・終わりの行が無い・本文をシェルや python にパイプで渡すときは、読み切れない（取り除かない）。"""
    if "<<" not in text:
        return text, [], True
    out, bodies, pending = [], [], []
    i, n, q = 0, len(text), None
    while i < n:
        c = text[i]
        if q:
            out.append(c)
            if c == "\\" and q == '"' and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == q:
                q = None
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            out.append(text[i:i + 2])
            i += 2
            continue
        if c in "'\"":
            q = c
        elif c == "#" and (i == 0 or text[i - 1] in " \t\n;&|("):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(text[i:j])  # コメントは行の終わりまで、そのまま
            i = j
            continue
        elif text.startswith("$((", i) or (text.startswith("((", i) and (i == 0 or text[i - 1] in " \t\n;&|(")):
            k = i + (3 if text[i] == "$" else 2)
            depth = 2
            while k < n and depth > 0:
                if text[k] == "(":
                    depth += 1
                elif text[k] == ")":
                    depth -= 1
                k += 1
            if depth > 0:
                return text, [], False
            out.append(text[i:k])  # 計算の中の << は、ヒアドキュメントではない
            i = k
            continue
        elif text.startswith("<<", i) and not text.startswith("<<<", i):
            j = i + 2
            dash = j < n and text[j] == "-"
            j += 1 if dash else 0
            end, tag = _heredoc_word(text, j)
            if not tag:
                return text, [], False
            pending.append((tag, dash))
            out.append(text[i:end])
            i = end
            continue
        elif c == "\n" and pending:
            out.append("\n")
            i += 1
            for tag, dash in pending:
                lines, found = [], False
                while i < n:
                    j = text.find("\n", i)
                    line = text[i:j] if j >= 0 else text[i:]
                    i = j + 1 if j >= 0 else n
                    if (line.lstrip("\t") if dash else line) == tag:
                        found = True
                        break
                    lines.append(line)
                if not found:
                    return text, [], False
                bodies.append("\n".join(lines))
            pending = []
            continue
        out.append(c)
        i += 1
    if pending:
        return text, [], False
    stripped = "".join(out)
    if bodies and re.search(r"<<[^\n]*\|\s*(?:\S*/)?(?:(?:ba|z|da|k|fi)?sh|python[\d.]*|perl|ruby|node)\b", stripped):
        return text, [], False  # 本文をパイプでシェル・言語に渡す（前の版と同じ全体の判定に任せる）
    return stripped, bodies, True


MAX_CWD = 1024  # 今いる場所がこれより長くなったら、読み切れない扱い（指摘3）
UNKNOWN_CWD = "/\x00(今いる場所を読み切れない)"  # このパスの下は解かない（stat も glob も失敗する）


def _guarded_place(d):
    """d が、守っているもの（本人のフォルダの印・03_インプット・.claude の設定・記録・プラグインのコピー）か、それを含むか、その下か。"""
    owners = owner_roots(None)
    forms = path_forms(d)
    for t in content_targets(owners) + holder_targets(owners)[len(owners):]:
        if any(t.covers(f) or t.within(f) for f in forms):
            return True
    return False


def resolve_cd(dest, cwd):
    """cd の行き先を to_paths と同じ解き方で決める（~・$HOME・ワイルドカード）。(新しい場所, 読み切れないか)。
    ワイルドカードの当たりが1つならそれ。2つ以上なら、どれかが守っているものに関わるときだけ読み切れない（止める側）、
    関わらなければ1つ目。0個なら、その文字のまま（cd は失敗する）。長すぎるときは読み切れない。"""
    if cwd == UNKNOWN_CWD and not os.path.isabs(os.path.expanduser(dest)):
        return UNKNOWN_CWD, True
    t = os.path.expanduser(dest)
    full = t if os.path.isabs(t) else os.path.join(cwd, t)
    if GLOB_CHARS.search(t):
        try:
            hits = [h for h in glob.glob(full) if os.path.isdir(h)]
        except (OSError, ValueError, re.error):
            hits = []
        if len(hits) >= 2 and any(_guarded_place(h) for h in hits[:50]):
            return UNKNOWN_CWD, True
        if hits:
            full = sorted(hits)[0]
    new = join_norm(cwd, t) if (full == os.path.join(cwd, t) and not os.path.isabs(t)) else os.path.normpath(full)
    if len(new) > MAX_CWD:
        return UNKNOWN_CWD, True
    return new, False


_ANALYZED = {}


def _add_inner(an, words, cwd, depth, top):
    """語のリストを、中のコマンドとして読み足す。足した部分は「起動役あり」。"""
    before = len(an.parts)
    analyze(" ".join(shlex.quote(w) for w in words), cwd, an, depth + 1, top)
    for sp in an.parts[before:]:
        sp.launched = True
    return an.parts[before:]


def analyze(command, cwd, an=None, depth=0, top=None):
    """コマンドを区切り・パイプに分け、cd の行き先を順にたどって、各コマンドの今いる場所と語を出す。
    先にヒアドキュメントの本文を取り除き（本文はデータ。python3 -・bash・sh に渡すものだけコードとして読む。読み切れなければ
    前の版と同じく全体を1つにする）、起動役（xargs・timeout・find -exec・env -S など）をほどく。同じコマンドと場所は1回だけ解く（R9）。"""
    if an is None and depth == 0 and top is None:
        key = (command, cwd)
        if key not in _ANALYZED:
            _ANALYZED[key] = analyze(command, cwd, Analysis(), 0, None)
        return _ANALYZED[key]
    stripped, bodies, readable = strip_heredocs(command)
    if not readable:
        an.unreadable = True
        return an  # 前の版と同じ全体の判定（ng_guard_legacy）に任せる。構造の判定はしない
    an.bodies += bodies
    bodies = list(bodies)
    unknown = cwd == UNKNOWN_CWD
    prev_cwd = cwd
    for g in split_top(stripped):
        parts = []
        for pt in split_top(g, pipes=True):
            raw, ok = seg_words_ok(pt)
            words = [expand(w, cwd) for w in raw]
            an.nwords += len(words)
            an.too_long = an.nwords > MAX_WORDS
            nb = len(re.findall(r"(?<!<)<<(?!<)", pt)) if "<<" in pt else 0
            body = "\n".join(bodies.pop(0) for _ in range(min(nb, len(bodies))))
            p = Part(pt, cwd, words, ok, body, unknown)
            p.top = top if top is not None else g
            parts.append(p)
            an.parts.append(p)
            if depth < 4:
                for sub in p.find_execs:  # find -exec の中のコマンドを、別のコマンドとして読む（{} は起点に置き換える）
                    for s in p.find_starts()[:20]:
                        _add_inner(an, [x.replace("{}", s) for x in sub], p.cwd, depth, p.top)
                if p.env_split:  # env -S '<コマンド>'
                    _add_inner(an, seg_words(p.env_split) + p.args, p.cwd, depth, p.top)
                if p.cmd not in NON_LAUNCHERS and p.cmd not in INNER_CMDS and not p.launched:
                    k = next((k for k, a in enumerate(p.args) if os.path.basename(a) in INNER_CMDS), None)
                    if k is not None:
                        for sp in _add_inner(an, p.args[k:], p.cwd, depth, p.top):
                            sp.guessed = True
            if p.cmd in ("cd", "pushd"):
                dest = next((a for a in p.args if not a.startswith("-") or a == "-"), None)
                old = cwd
                if dest is None:
                    cwd, unknown = os.path.expanduser("~"), False
                elif dest == "-":
                    cwd, unknown = prev_cwd, prev_cwd == UNKNOWN_CWD  # cd -：ひとつ前の場所
                else:
                    cwd, unknown = resolve_cd(dest, cwd)
                prev_cwd = old
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
    for w in p.all_words:
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


_PY_LIT = r"(?:[rbuRBU]{1,2})?(?:'([^'\n]*)'|\"([^\"\n]*)\")"  # 引用符つき文字列（中身は2つの組のどちらか）
_PY_RX = [re.compile(PY_CALL + r"(?:" + _PY_LIT + r"|(" + PY_CWD + r"))"),
          re.compile(r"(?:pathlib\.)?Path\(\s*" + _PY_LIT + r"\s*\)" + PY_METHOD),
          re.compile(PY_CWD + PY_METHOD),
          re.compile(r"\b([A-Za-z_]\w*)" + PY_METHOD),
          re.compile(r"\b([A-Za-z_]\w*)\s*=\s*(?:pathlib\.)?Path\(\s*" + _PY_LIT + r"\s*\)"),
          re.compile(r"\b([A-Za-z_]\w*)\s*=\s*" + PY_CWD)]
_PY_SOURCES = {}


def python_sources(code):
    """python のコードの中で、動かす・消す対象になっている文字列（今いる場所は "."）。同じコードは1回だけ調べる。"""
    r = _PY_SOURCES.get(code)
    if r is not None:
        return list(r)
    out = []
    if "(" in code:
        for m in _PY_RX[0].finditer(code):
            out.append("." if m.group(3) else (m.group(1) if m.group(1) is not None else m.group(2)))
        for m in _PY_RX[1].finditer(code):
            out.append(m.group(1) if m.group(1) is not None else m.group(2))
        for m in _PY_RX[2].finditer(code):
            out.append(".")
        # 変数に入れてからメソッドを呼ぶ形。メソッドを呼んでいる変数を先に1回で集める（長さの2乗にしない。指摘3）
        called = {m.group(1) for m in _PY_RX[3].finditer(code)}
        if called:
            for m in _PY_RX[4].finditer(code):
                if m.group(1) in called:
                    out.append(m.group(2) if m.group(2) is not None else m.group(3))
            for m in _PY_RX[5].finditer(code):
                if m.group(1) in called:
                    out.append(".")
    r = _PY_SOURCES[code] = tuple(x.rstrip("\\") for x in out if x)
    return list(r)


def move_sources(p):
    """Part が動かす・消すもの：(元の文字列のリスト, mv の行き先 or None, 基準の場所)。1つの Part につき1回だけ解く。"""
    r = getattr(p, "_moves", None)
    if r is None:
        r = p._moves = _move_sources(p)
    return list(r[0]), r[1], r[2]


def _move_sources(p):
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
    if c == "find":
        out += p.find_outputs()  # -fprint などの書き込み先（指摘5）
    if c == "find" and any(os.path.basename(sub[0]) not in FIND_READ_ONLY for sub in p.find_execs):
        out += p.find_starts()  # find 03_インプット -exec <読むだけでないコマンド>：起点を書き込み先とみなす（指摘2）
    srcs, dest, _ = move_sources(p)  # 動かす・消す元（mv・git mv・find -delete・zip -m・python の os.rename など）
    out += srcs
    if dest:
        out.append(dest)
    if re.search(r"\bpython[\d.]*\b", p.text):
        out += python_writes(p.text)
    return [(t, base) for t in out if t]


def input_hit(an, root):
    """03_インプット（元データ。読むだけ）と .claude の設定（settings・hooks・共通ルールの写し）へ、Bash で書き込む・作る・
    そこから動かす・消す操作か（R3。.claude の設定は、ハードリンク・リンク経由も実体で比べる）。読み出し（cp の元など）は通す。"""
    targets = [("元データの移動・上書き" if rel == ("03_インプット",) else label, target(os.path.join(str(root), *rel)))
               for label, rel in PROTECTED_TARGETS]
    for p in an.parts:
        for text, base in write_targets(p):
            for w in word_texts(text):
                for f in to_paths(w, base):
                    for label, t in targets:
                        if t.covers(f):
                            return label
    return None


def unresolvable_source(an):
    """動かす・消す元のパスが、リンクのループなどで解けない（OS も解けない）か。中では止める側に倒す（st-1）。"""
    import errno
    for p in an.parts:
        srcs, _, base = move_sources(p)
        for s in srcs:
            t = os.path.expanduser(s)
            full = t if os.path.isabs(t) else os.path.join(base, t)
            try:
                os.stat(full)
            except OSError as e:
                if e.errno == errno.ELOOP:
                    return True
            except ValueError:
                continue
    return False


NO_DEREF = re.compile(r"^-[A-Za-z]*[nhT]")  # ln -n・-h・-T：行き先がリンクやフォルダでも、それ自体を置き換える


def _link_args(a, sym_flags="s"):
    """ln・cp のリンクの引数を読む。(元のリスト, 行き先のフォルダ（-t）, 置き場所の語, シンボリックか, 置き換えるか)。"""
    sym, tdir, plain, skip, repl = False, None, [], False, False
    for k, x in enumerate(a):
        if skip:
            skip = False
            continue
        if x in ("-t", "--target-directory"):
            tdir = a[k + 1] if k + 1 < len(a) else None
            skip = True
        elif x.startswith("--target-directory="):
            tdir = x.split("=", 1)[1]
        elif x in ("--symbolic", "--symbolic-link"):
            sym = True
        elif x in ("--no-dereference", "--no-target-directory"):
            repl = True
        elif x.startswith("--"):
            continue
        elif x.startswith("-t") and len(x) > 2:
            tdir = x[2:]
        elif x.startswith("-") and len(x) > 1:
            sym = sym or any(ch in x[1:] for ch in sym_flags)
            repl = repl or bool(NO_DEREF.match(x))
            if x.endswith("t"):
                tdir = a[k + 1] if k + 1 < len(a) else None
                skip = True
        else:
            plain.append(x)
    return plain, tdir, sym, repl


def _link_dests(p, plain, tdir, sym, repl):
    out = []
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
    return out


def link_pairs(p):
    """リンクを作る操作：[(元の文字列, [行き先の文字列], シンボリックか, 置き換えるか)]。
    ln（-s あり・なし）・link・cp -l／-s／-al・os.symlink・os.link・Path.symlink_to・Path.hardlink_to・Path.link_to。"""
    out = []
    if p.cmd == "ln":
        out += _link_dests(p, *_link_args(p.args))
    elif p.cmd == "link":
        plain = _nonopt(p.args)
        if len(plain) >= 2:
            out.append((plain[0], [plain[1]], False, False))
    elif p.cmd in ("cp", "gcp"):
        flags = "".join(x[1:] for x in p.args if re.match(r"^-[A-Za-z]+$", x))
        if "l" in flags or "s" in flags or "--link" in p.args or "--symbolic-link" in p.args:
            plain, tdir, sym, repl = _link_args([x for x in p.args if x != "--link"], sym_flags="s")
            out += _link_dests(p, plain, tdir, sym, repl)
    if re.search(r"\bpython[\d.]*\b", p.text):
        for m in re.finditer(r"\bos\.symlink\(\s*" + PY_STR + r"\s*,\s*" + PY_STR, p.text):
            out.append((_s(m, 1), [_s(m, 3)], True, False))
        for m in re.finditer(r"\bos\.link\(\s*" + PY_STR + r"\s*,\s*" + PY_STR, p.text):
            out.append((_s(m, 1), [_s(m, 3)], False, False))
        for m in re.finditer(r"\bPath\(\s*" + PY_STR + r"\s*\)\s*\.\s*symlink_to\(\s*" + PY_STR, p.text):
            out.append((_s(m, 3), [_s(m, 1)], True, False))
        for m in re.finditer(r"\bPath\(\s*" + PY_STR + r"\s*\)\s*\.\s*hardlink_to\(\s*" + PY_STR, p.text):
            out.append((_s(m, 3), [_s(m, 1)], False, False))
        for m in re.finditer(r"\bPath\(\s*" + PY_STR + r"\s*\)\s*\.\s*link_to\(\s*" + PY_STR, p.text):
            out.append((_s(m, 1), [_s(m, 3)], False, False))
    return [(s, [d for d in ds if d], sym, repl) for s, ds, sym, repl in out if s]


LINK_LABEL = "保護しているものへのリンク（リンクを通すと見張りが行き先を読めなくなる。作らない）"


def link_hit(an, root=None):
    """同じコマンドの中で作るリンク（R6）：
    - 行き先：保護しているもの（またはその下）なら止める。-n・-h・-T で置き換えるときは、本人のフォルダ・記録・印を含む所も止める
    - シンボリックリンクの元：保護しているもの（またはその下）、本人のフォルダそのもの、本人のフォルダの下で印を含むもの（設定・.claude など）。
      本人のフォルダの親（~・~/workspace）は止めない（指摘8。既知の残り）。元は、リンクを置く場所から数えた形も見る
    - ハードリンクの元（ln・link・cp -l・os.link・Path.hardlink_to）：03_インプット・.claude の設定・印・記録（またはその下・それを含む）なら止める（指摘4）"""
    pairs = [(p, x) for p in an.parts for x in link_pairs(p)]
    if not pairs:
        return None
    owners = owner_roots(root)
    content, holders = content_targets(owners), holder_targets(owners)
    roots_t = [target(str(r)) for r in owners]
    marks = [(mk, target(str(r))) for r in owners for mk in marks_of(r)]

    def bad_dest(f, replace):
        if any(t.covers(f) for t in content):
            return True
        return replace and any(t.within(f) for t in holders)

    def bad_sym_src(f, dest_inside):
        if any(t.covers(f) for t in content):
            return True
        if any(t.same(f) for t in roots_t):
            return True
        if dest_inside and any(t.within(f) for t in roots_t):
            return True  # 本人のフォルダの中に、本人のフォルダを含む所（親）へのリンクを作る（ln -s ../../ 02_成果物/up）
        return any(mk.within(f) and rt.covers(f) for mk, rt in marks)

    def bad_hard_src(f):
        return any(t.covers(f) or t.within(f) for t in content)

    for p, (s, dests, sym, repl) in pairs:
        dpaths = set()
        for d in dests:
            dpaths |= to_paths(d, p.cwd)
        for f in dpaths:
            if bad_dest(f, repl):
                return LINK_LABEL
        spaths = set(to_paths(s, p.cwd))
        if sym:
            for f in dpaths:
                spaths |= to_paths(s, os.path.dirname(f))
        dest_inside = any(t.covers(f) for f in dpaths for t in roots_t)
        for f in spaths:
            if (bad_sym_src(f, dest_inside) if sym else bad_hard_src(f)):
                return LINK_LABEL
    return None


RECORD_WRITE = re.compile(r"(?:>>?(?!\s*(?:&|/dev/null\b))|\btee\b|\s-i\b|\b(?:cp|mv|ln|rsync|install|touch|mkdir|rm|rmdir|unlink|shred|trash|rename|"
                          r"truncate|dd|unzip|tar|zip|patch|chmod|chflags|chown|find|sed|perl|ruby|node|python[\d.]*)\b|"
                          r"open\(|\.write|write_text|writeFile|\bcd\b|\bpushd\b)")


def records_bash_hit(an):
    """見張りの記録（~/.ai-bunshin/）に書く Bash か。読むだけ（cat・ls など）は通す。
    記録の名前が出てくる、またはパス・cd の行き先が記録の置き場所の中の区切りに、書き込みの語があれば止める。"""
    rec = target(records_dir())
    if an.bodies:  # ヒアドキュメントのあるコマンドは、前の版と同じく全体（本文を含む）でも見る（本文の中の書き込みを通さないため）
        whole = quiet("\n".join([g for g, _ in an.groups] + an.bodies))
        if RECORD_WRITE.search(whole) and re.search(r"\.ai-bunshin(?=$|[/\s\"';&|)])", whole, re.I):
            return True
    seen = {}
    for p in an.parts:
        top = quiet(p.top)
        if top not in seen:  # 同じ区切りの文字は1回だけ調べる（find -exec が多いときに長さの2乗にしない）
            seen[top] = (bool(RECORD_WRITE.search(top)), bool(re.search(r"\.ai-bunshin(?=$|[/\s\"';&|)])", top, re.I)))
        writes, named = seen[top]
        if not writes:
            continue
        if named or any(
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
    recs = record_roots()
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        p = inp.get("file_path") or inp.get("notebook_path")
        if isinstance(p, str) and p:
            for f in sorted(path_forms(p, base)):
                r = find_owner(f) or hardlink_owner(f, recs)
                if r is not None:
                    return [(r, None)]
        return []
    if tool != "Bash" or not isinstance(inp.get("command"), str):
        return []
    flat = normalize(inp["command"])
    an = analyze(flat, base)
    if an.bodies:  # 本人のフォルダを探すときだけ、すべての本文のパスも候補に入れる。見つかれば本文を含めた全体で判定する
        found = {}
        for body in an.bodies:
            for w in seg_words(body)[:MAX_WORDS]:
                for t in word_texts(w):
                    for f in to_paths(t, base):
                        r = find_owner(f) or hardlink_owner(f, recs)
                        if r is not None:
                            found[str(r)] = r
        if found:
            return [(r, None) for r in found.values()]
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
            for w in p.all_words:  # python3 -・bash・sh に渡す本文の語も見る（前の版と同じ）
                for t in word_texts(w):
                    cands |= to_paths(t, p.cwd)
            cands_anc = set(cands) if p.cmd not in ("cd", "pushd") else set()  # 今いる場所は親とみなさない（cd ~ など）
            cands |= path_forms(p.cwd)
            for f in cands:
                r = find_owner(f) or hardlink_owner(f, recs)
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
        # ヒアドキュメントのあるコマンドは、前の版と同じく全体（本文を含む）で判定する（本文を除いた区切りだけでは中のコードが見えない）
        out.append((r, None if an.bodies else "\n".join(chosen)))
    return out


def hardlink_owner(f, recs):
    """f が、記録にある本人のフォルダの守っているもの（03_インプット・.claude の設定など）のハードリンクなら、その本人のフォルダ。
    外の場所に作ったハードリンクへの書き込み（指摘4 の c3-15〜18）。ハードリンクでないファイルは調べない。"""
    try:
        st = os.stat(f)
    except (OSError, ValueError):
        return None
    if not stat.S_ISREG(st.st_mode) or st.st_nlink < 2:
        return None
    for _, r in recs:
        if any(t.covers(f) for t in content_targets([r])):
            return r
    return None


def _read_config(root):
    """設定/config.json を読む。読めない・形が違う（dict でない）ときは {}。例外はすべて受ける（指摘5）。"""
    try:
        cfg = json.loads((Path(root) / "設定" / "config.json").read_text(encoding="utf-8"))
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def allow_patterns(root):
    """本人の許可する例外（ng_allow）。リストの中の文字列だけを使う。形が違う・読めない・正規表現として壊れているものは使わない
    （例外が無い＝緩まない側。文字列そのものを1文字ずつ例外にしてしまう読み方もしない）。"""
    items = _read_config(root).get("ng_allow", [])
    if not isinstance(items, list):
        return []
    out = []
    for x in items:
        if isinstance(x, str):
            try:
                out.append(re.compile(x))
            except Exception:
                continue
    return out


def dev_paths(root):
    """本人設定（config の dev.projects）に登録した開発の置き場所（絶対パス）。形が違う・解けないものは使わない（指摘5）。"""
    cfg = _read_config(root)
    out = []
    dev = cfg.get("dev")
    projects = dev.get("projects", []) if isinstance(dev, dict) else []
    for prj in projects if isinstance(projects, list) else []:
        try:
            if isinstance(prj, dict) and isinstance(prj.get("path"), str) and prj["path"]:
                d = Path(os.path.expanduser(prj["path"]))
                out.append(Path(os.path.realpath(d if d.is_absolute() else Path(root) / d)))
        except Exception:
            continue
    try:
        out.append(Path(os.path.realpath(Path(root) / "05_開発")))  # local モードの置き場所は登録がなくても対象
    except Exception:
        pass
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
            return Path(os.path.realpath(Path(t) if os.path.isabs(t) else base / t))
        except Exception:
            return None

    try:
        cur = Path(os.path.realpath(payload.get("cwd") or root))
    except Exception:
        return False  # 解けないときは置き場所の外とみなす（緩まない側。指摘5）
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
    """メンテする人か。読めない・形が違うときは False（緩まない側。指摘5）。"""
    if root is None:
        return False
    try:
        return bool(_read_config(root).get("maintainer"))
    except Exception:
        return False


def plugin_area(path_text):
    """プラグインのコピー（~/.claude/plugins/ の下）か、プラグインの元（.claude-plugin/ を持つフォルダの下）か。
    リンクのループなどで解けないときも例外にしない（realpath を使う）。思わぬ例外のときは "unknown"（中では止める側。指摘5）。"""
    try:
        q = Path(os.path.realpath(os.path.expanduser(path_text)))
        plugins = Path(os.path.realpath(Path.home() / ".claude" / "plugins"))
        if q == plugins or plugins in q.parents:
            return "copy"
        for d in [q, *q.parents]:
            try:
                if (d / ".claude-plugin" / "plugin.json").exists() or (d / ".claude-plugin" / "marketplace.json").exists():
                    return "source"
            except (OSError, ValueError):
                continue
        return None
    except Exception:
        return "unknown"


WRITE_WORDS = re.compile(r"(?:>|\btee\b|\s-i\b|\b(?:cp|mv|ln|rsync|install|touch|mkdir|rm|truncate|dd|unzip|tar|patch)\b|"
                         r"open\(|\.write|write_text|writeFile|\bcd\b|\bpushd\b)")
READ_ONLY_CP = re.compile(r"^\s*cp\s+(?:-(?!t\b)[A-Za-su-z]+\s+)*\S+\s+\S+\s*$")  # -t（コピー先の指定）付きは読み出しとみなさない


PLUGIN_COPY_WORD = re.compile(r"\.claude/plugins(?:/|$|[\s\"'])")  # 前の版と同じ当て方（広げると新しく止まるものが出る）


# ---- T061：読むだけのコマンド・文字列・本文の中の語で止めない（通す形を狭い許可リストに絞る） ----
# 文字の並びの規則（BASH_RULES・plugin_bash_check・前の版の規則）に渡す前に、実行されない文字を「ならす」。
# 抜け道を一つずつ塞ぐのをやめ、ならす形を次の3つだけにした。どれも「コマンド全体がその1文だけ」のときに限り、
# 形が少しでも外れたら（先頭の NAME=値・語頭の #・閉じていない引用符・後ろに続く文など）何もせず、前の版の判定に任せる（止める側）。
#   1. ヒアドキュメント：cat > 先 <<'EOF'／cat <<'EOF' > 先／tee 先 <<'EOF'（区切りは引用符付きだけ。行き先は .md .txt .csv .log だけ）
#   2. python3 - <<'EOF'（区切りは引用符付きだけ）：文字列とコメントを消し、削除・送信の呼び出しの語だけ残す
#   3. git commit -m "…"／git tag -m "…"（前に git add … && が1つ付くのは可）。本文に $( ・` が入っていればならさない
# ならした文字は、規則に渡す分だけに使う。行き先の判定（analyze など）には元のコマンドを使うので、書き込み先は見落とさない。
PY_DANGER = re.compile(r"os\.(?:remove|unlink|rmdir|removedirs|system)\b|shutil\.rmtree|\.unlink\(|\.rmdir\(|"
                       r"requests\.(?:post|put|delete|patch)|smtplib|urlopen\(")
PY_RUNNERS = re.compile(r"\w*(?:exec|eval|compile|spawn|popen|system|fork)\w*|\b(?:__import__|getattr|setattr|importlib|subprocess|"
                        r"runpy|pty|ctypes|builtins|globals|locals)\b", re.I)
PY_FSTRING = re.compile(r"(?<![\w])(?:[fF][rR]?|[rR][fF])[\"']")  # f文字列の {} の中は実行される式（文字列として消すと見落とす）


def _py_code_only(body):
    """python の本文から、文字列とコメントを空白にした文字列。読めなければ None。"""
    import io
    import tokenize
    lines = body.split("\n")
    rows = [list(l) for l in lines]
    skip = {tokenize.STRING, tokenize.COMMENT}
    for n in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):
        if hasattr(tokenize, n):
            skip.add(getattr(tokenize, n))
    try:
        for tok in tokenize.generate_tokens(io.StringIO(body + "\n").readline):
            if tok.type in skip:
                (r1, c1), (r2, c2) = tok.start, tok.end
                for r in range(r1, r2 + 1):
                    if r - 1 >= len(rows):
                        break
                    a = c1 if r == r1 else 0
                    b = c2 if r == r2 else len(rows[r - 1])
                    for c in range(a, min(b, len(rows[r - 1]))):
                        rows[r - 1][c] = " "
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return None
    return "\n".join("".join(r) for r in rows)


def _py_body_summary(body):
    """python に渡す本文を、規則に渡す形にする：削除・送信の呼び出しの語だけ残す。ならせないときは None。"""
    if re.search(r"\$\(|`|<\(", body):
        return None  # シェルが展開して、中身が変わる
    code = _py_code_only(body)
    if code is None or PY_RUNNERS.search(code.replace("re.compile", "re_")) or PY_FSTRING.search(body):
        return None  # 読めない、または文字列を実行できる呼び出しがある
    if ".claude/plugins" in body and WRITE_WORDS.search(body):
        return None  # プラグインのコピーを指す文字と書き込みの語が同居：行き先を変数で隠せるので、ならさない
    return "\n".join(m.group(0) for m in PY_DANGER.finditer(code))


_DEST = r"(?P<dest>[\w./~+@%-]+)"
_DELIM = r"<<[ \t]*(?P<q>['\"])(?P<name>[A-Za-z_]\w*)(?P=q)"
HD_FIRST_DATA = [  # 1行目の形（この形だけ。cat >> や tee -a や前置きの変数は不可）
    re.compile(r"\A\s*cat[ \t]+>[ \t]*" + _DEST + r"[ \t]+" + _DELIM + r"[ \t]*\n"),
    re.compile(r"\A\s*cat[ \t]+" + _DELIM + r"[ \t]*>[ \t]*" + _DEST + r"[ \t]*\n"),
    re.compile(r"\A\s*tee[ \t]+" + _DEST + r"[ \t]+" + _DELIM + r"[ \t]*\n"),
]
HD_FIRST_PY = re.compile(r"\A\s*python[\d.]*[ \t]+-[ \t]+" + _DELIM + r"[ \t]*\n")
DATA_EXTS = (".md", ".txt", ".csv", ".log")


def _data_dest_ok(d):
    """書くだけのヒアドキュメントの行き先として、ならしてよいか。拡張子が .md .txt .csv .log で、ドット名・.. ・Library を通らない。"""
    if os.path.splitext(d)[1].lower() not in DATA_EXTS:
        return False
    if d.startswith("~") and not d.startswith("~/"):
        return False  # ~user
    parts = d.split("/")
    if d.startswith("~/") or d.startswith("./"):
        parts = parts[1:]
    if any(p.startswith(".") for p in parts):
        return False  # .zshenv・.ssh・.config・.claude・.git・..
    if parts and parts[0].lower() == "library":
        return False
    if d.startswith("/"):
        home = os.path.expanduser("~").rstrip("/").lower()
        low = os.path.normpath(d).lower()
        if home and (low == home + "/library" or low.startswith(home + "/library/")):
            return False
    return True


def _heredoc_whole(text, first_re):
    """text 全体が「first_re に合う1行目＋本文＋閉じの行」だけなら (一致, 本文の始め, 閉じの行の始め)。閉じの後に何か続けば None。"""
    m = first_re.match(text)
    if not m:
        return None
    name, pos = m.group("name"), m.end()
    while True:
        j = text.find("\n", pos)
        if text[pos:j if j >= 0 else len(text)] == name:
            if text[j + 1:].strip() if j >= 0 else False:
                return None  # 閉じの後に続きがある
            return m, m.end(), pos
        if j < 0:
            return None  # 閉じていない
        pos = j + 1


_GQ = r"(?:\"(?P<dq>(?:[^\"\\]|\\.)*)\"|'(?P<sq>[^']*)')"
GIT_MSG_WHOLE = re.compile(
    r"\A(?P<pre>\s*(?:git[ \t]+add(?:[ \t]+[\w./~*+@%-]+)*[ \t]*&&[ \t]*)?"
    r"git[ \t]+(?:commit(?:[ \t]+-a)?[ \t]+-m|commit[ \t]+-am|tag(?:[ \t]+-a)?[ \t]+[\w.-]+[ \t]+-m)[ \t]*)" + _GQ + r"\s*\Z", re.S)


def mask_inert(text):
    """規則に渡す前に、実行されない文字（上の1〜3）をならした文字列。コマンド全体が上の形の1文のときだけ。それ以外はそのまま返す。"""
    if "<<" in text:
        for first in HD_FIRST_DATA:
            r = _heredoc_whole(text, first)
            if r and _data_dest_ok(r[0].group("dest")):
                return text[:r[1]] + text[r[2]:]
        r = _heredoc_whole(text, HD_FIRST_PY)
        if r:
            summ = _py_body_summary(text[r[1]:r[2]])
            if summ is not None:
                return text[:r[1]] + ((summ + "\n") if summ else "") + text[r[2]:]
        return text
    if "git" in text:
        m = GIT_MSG_WHOLE.match(text)
        if m:
            inner = m.group("dq") if m.group("dq") is not None else m.group("sq")
            if not re.search(r"\$\(|`|\$\{|<\(", inner):
                q = '"' if m.group("dq") is not None else "'"
                return m.group("pre") + q + "x" * len(inner) + q
    return text


# 読むだけの $( )：中は ls か cat の1コマンドだけ（; & | 改行 > ` $ ( ) と引用符があれば当たらない）
READ_SUBST = re.compile(r"\$\([ \t]*(?:ls|cat)(?:[ \t]+[^\s;&|<>`$()\\'\"]+)*[ \t]*\)")
WRITE_WORDS_NO_CD = None  # WRITE_WORDS の定義のあとで作る
SED_SAFE_SCRIPT = re.compile(r"^(?:\d+|\$|/[^/]*/)(?:,(?:\d+|\$|/[^/]*/|\+\d+))?[pd=]$")
READ_CMDS_PLAIN = {"cat", "head", "tail", "wc", "ls", "grep"}
GIT_READ_SUBS = {"status", "log", "diff", "show"}
GIT_BAD_LONG = ("--textconv", "--ext-diff", "--no-index", "--output", "--open-files", "--exec")


def _read_cmd_ok(cmd):
    """cd のあとの1コマンドが、読むだけの許可リスト（sed -n・cat・head・tail・wc・ls・grep・git status|log|diff|show）か。"""
    if cmd.count('"') % 2 or cmd.count("'") % 2:
        return False
    try:
        words = shlex.split(cmd)
    except ValueError:
        return False
    if not words:
        return False
    name, args = words[0], words[1:]
    if name == "sed":
        return len(args) >= 2 and args[0] == "-n" and bool(SED_SAFE_SCRIPT.match(args[1])) and not any(a.startswith("-") for a in args[2:])
    if name == "git":
        if not args or args[0] not in GIT_READ_SUBS:
            return False
        for a in args[1:]:
            if a.startswith(GIT_BAD_LONG) or (a.startswith("-") and not a.startswith("--") and re.search(r"[OC]", a)):
                return False
        return True
    return name in READ_CMDS_PLAIN


CD_SHAPE = re.compile(
    r"\A\s*cd[ \t]+(?P<dir>[^\s\"'`$;&|()<>#\\]+|\"[^\"$`\\]*\"|\"" + READ_SUBST.pattern + r"\")[ \t]*&&[ \t]*(?P<cmd>[^\n;&|<>`$()\\#]+?)[ \t]*\Z")


def cd_read_shape(t):
    """t（ならして quiet を通した文字列）が「cd <元> && 読むだけの1コマンド」だけなら、読むだけの $( ) を外した文字列。そうでなければ None。
    読むだけの $( ) を外すのは、cd の行き先に置いたときだけ。"""
    m = CD_SHAPE.match(t)
    if not m:
        return None
    d = m.group("dir")
    t2 = t[:m.start("dir")] + ("READ_SUBST" if d.startswith('"$(') else d) + t[m.end("dir"):]
    if PLUGIN_COPY_WORD.search(t2) or WRITE_WORDS_NO_CD.search(t2) or not _read_cmd_ok(m.group("cmd")):
        return None
    return t2


def relax_text(command):
    """前の版の規則を当て直す文字列：実行されない文字をならし、cd と読むだけのコマンドだけなら cd を chdir に替える（cd は書き込みの語に数えない）。"""
    t = quiet(mask_inert(command))
    t2 = cd_read_shape(t)
    if t2 is not None:
        return re.sub(r"(?<![\w./-])cd(?=\s)", "chdir", t2)
    return t


WRITE_WORDS_NO_CD = re.compile(WRITE_WORDS.pattern.replace(r"|\bcd\b|\bpushd\b", ""))




def _plain_read(g):
    """区切り g が、読むだけの1つのコマンドか（cat・ls など。向け先・$( )・` ` なし）。"""
    if re.search(r"[>`]|\$\(|<\(", g):
        return False
    try:
        words = split_redirs(seg_words(g))[0]
    except Exception:
        return False
    i, _, _, _ = unwrap(words, "/")
    return i < len(words) and os.path.basename(words[i]) in READ_ONLY_CMDS - {"cd", "pushd"}


def plugin_bash_check(command, root):
    """Bash でのプラグインへの書き込み。コピー（~/.claude/plugins/）は誰でも、元（.claude-plugin/ を持つフォルダ）は
    メンテする人以外を止める。読むだけ（cat・ls・diff、cp のコピー元）は通す。
    パスを細かく追えない書き方（cd してから書く、python -c で書く）もあるので、書き込みの語があれば広めに止める。"""
    command = quiet(mask_inert(command))  # 2>/dev/null・2>&1 は書き込みと見ない（R4）。実行されない文字はならす（T061）
    if not WRITE_WORDS.search(command):
        return None
    if cd_read_shape(command) is not None:
        return None  # 書き込みの語が cd だけで、あとは読むだけ（cd <元> && sed -n …）。cd の先に書き込む形は、書き込みの語で止まる（T061）
    tokens = re.findall(r"[\"']?([^\s\"';&|()]+)[\"']?", command)
    if PLUGIN_COPY_WORD.search(command):
        # 区切り（; && || 改行）ごとに見る。読むだけの区切り（cat ~/.claude/plugins/x）のあとの、別の場所での cd や書き込みでは止めない。
        # プラグインのコピーを書く区切りと、それを読むだけでない形で受け渡した（変数・cd など）あとの、書き込みの語のある区切りは止める
        tainted = False
        for g in split_top(command):
            mentions = bool(PLUGIN_COPY_WORD.search(g))
            if (mentions or tainted) and WRITE_WORDS.search(g):
                if mentions and READ_ONLY_CP.match(g):  # cp <プラグインのコピー> <外> だけは読み出しなので通す
                    parts = g.split()
                    if ".claude/plugins" in parts[-2] and ".claude/plugins" not in parts[-1]:
                        continue
                return PLUGIN_COPY_LABEL
            if mentions and not _plain_read(g):
                tainted = True
    if root is not None and not is_maintainer(root):  # 元の保護は本人のフォルダの中だけ（ほかのプロジェクトでは誰がメンテする人か分からない）
        for tk in tokens:
            if "/" in tk and plugin_area(tk.replace("$HOME", "~")) in ("source", "unknown"):
                if READ_ONLY_CP.match(command) and tk == command.split()[-2]:
                    continue
                return "共通部分（プラグインの元）の書き換え（メンテする人だけ。提案の下書きにする）"
    return None


# プラグイン・見張りの記録・本人のフォルダそのもの・保護しているものへのリンクは、本人の許可する例外（ng_allow）でも外さない
NO_EXCEPTION_LABELS = ("プラグインのコピーの書き換え", "共通部分（プラグインの元）の書き換え", "見張りの記録",
                       "本人のフォルダそのものを動かす・消す", "保護しているものへのリンク", "AI 自身の制限を外す書き換え")
RECORDS_LABEL = "見張りの記録（~/.ai-bunshin/）の書き換え（本人のフォルダを覚えておく所。消すと見張りが外れる）"
PLUGIN_COPY_LABEL = "プラグインのコピーの書き換え（Claude Code が読み込む共通部分。元を直し、入れ替えは本人へのお願い（`! claude plugin update …`）にする）"
PLUGIN_UPDATE_LABEL = "プラグインのコピーの書き換え（claude plugin の入れる・更新・外す。本人へのお願い（`! claude plugin update …`）にする）"
WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")


GIT_WRITE_SUBS = {"pull", "fetch", "checkout", "switch", "reset", "merge", "rebase", "cherry-pick", "revert", "commit",
                  "add", "rm", "mv", "restore", "stash", "clean", "apply", "am", "init", "clone", "submodule", "worktree",
                  "gc", "prune", "update-index", "read-tree", "config"}
CLAUDE_PLUGIN_CHANGE = re.compile(r"^(?:install|i|update|uninstall|remove|rm)$")
CLAUDE_MARKET_CHANGE = re.compile(r"^(?:add|update|remove|rm)$")


def plugin_write_hit(an):
    """プラグインのコピー（~/.claude/plugins/）への書き込みを、書き込み先・移動の元・今いる場所を実体で比べて止める（指摘4）。
    cd してからの touch・~/.claude//plugins・大文字小文字・git -C … pull も止まる。
    claude plugin install|update|uninstall と claude plugin marketplace add|update|remove は、メンテする人でも止める
    （コピーを入れ替えるのは本人。本人へのお願い（`! claude plugin update …`）にする）。"""
    plug = target(plugins_dir())
    for p in an.parts:
        if p.cmd == "claude" and p.args[:1] == ["plugin"] and len(p.args) >= 2 and (
                CLAUDE_PLUGIN_CHANGE.match(p.args[1]) or
                (p.args[1] == "marketplace" and len(p.args) >= 3 and CLAUDE_MARKET_CHANGE.match(p.args[2]))):
            return PLUGIN_UPDATE_LABEL
        texts = list(write_targets(p))
        if p.cmd == "git":
            sub = next((a for k, a in enumerate(p.args) if not a.startswith("-") and
                        (k == 0 or p.args[k - 1] not in ("-C", "-c", "--git-dir", "--work-tree"))), "")
            if sub in GIT_WRITE_SUBS:
                cdir = _opt_value(p.args, ("-C",), ())
                texts.append((cdir or ".", p.cwd))
        for text, base in texts:
            for w in word_texts(text):
                for f in to_paths(w, base):
                    if plug.covers(f):
                        return PLUGIN_COPY_LABEL
        if p.cwd != UNKNOWN_CWD and p.cmd and p.cmd not in READ_ONLY_CMDS and covers_any(plug, path_forms(p.cwd)):
            return PLUGIN_COPY_LABEL  # コピーの中に入って、読むだけでないコマンドを動かす
    return None


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
        plug = plugin_write_hit(an)
        if plug:
            return plug, command, root
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


UNKNOWN_CWD_LABEL = "cd の行き先を読み切れない（ワイルドカードの当たりが0個か2個以上・長すぎる・cd -）あとの操作"


# ---- AI が自分の制限を外す書き換え（T059）：config の ng_allow・maintainer、CLAUDE.md の「許可する例外」 ----
SELF_LIMIT_LABEL = ("AI 自身の制限を外す書き換え（config.json の ng_allow・maintainer、CLAUDE.md の「許可する例外」は"
                    "本人が自分で直す。AI は提案の下書きまで）")
_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*)$")


def _text_after(tool, inp, text):
    """Write・Edit・MultiEdit を適用したあとの全文。適用の形が確かめられないときは None。"""
    if tool == "Write":
        c = inp.get("content")
        return c if isinstance(c, str) else None
    if tool == "MultiEdit":
        edits = inp.get("edits")
    elif tool == "Edit":
        edits = [inp]
    else:
        return None
    if not isinstance(edits, list) or not edits:
        return None
    for e in edits:
        if not isinstance(e, dict):
            return None
        old, new = e.get("old_string"), e.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str) or old == "" or old not in text:
            return None
        text = text.replace(old, new) if e.get("replace_all") is True else text.replace(old, new, 1)
    return text


def _limit_keys(text):
    """config.json の本文から、見張りが実際に使う値（ng_allow の文字列のリスト・maintainer の真偽）。読めない・形が違うときは見張りと同じく {} 扱い。"""
    try:
        cfg = json.loads(text)
    except Exception:
        cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}
    ng = cfg.get("ng_allow", [])
    ng = [x for x in ng if isinstance(x, str)] if isinstance(ng, list) else []
    return ng, bool(cfg.get("maintainer"))


def _exception_sections(text):
    """CLAUDE.md の本文から、見出しに「許可する例外」を含む節（次の同じか上の見出しの前まで）の本文のリスト。コードブロックの中の # は見出しにしない。"""
    out, cur, level, fence = [], None, 0, False
    for line in nfc(text).replace("\r\n", "\n").split("\n"):
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
        m = None if fence else _HEADING.match(line)
        if m:
            if cur is not None and len(m.group(1)) <= level:
                out.append("\n".join(cur))
                cur = None
            if cur is None and "許可する例外" in m.group(2):
                cur, level = [line], len(m.group(1))
                continue
        if cur is not None:
            cur.append(line)
    if cur is not None:
        out.append("\n".join(cur))
    return out


def self_limit_hit(tool, inp, root, path, forms, base):
    """Write・Edit で、既にある config.json の ng_allow・maintainer や CLAUDE.md の「許可する例外」が変わるなら True。
    まだ無いファイルの新規作成（setup）は通す。適用後の姿を確かめられない形（内容なし・見つからない old_string など）は止める。"""
    cfg_path, md_path = Path(root) / "設定" / "config.json", Path(root) / "CLAUDE.md"
    kind = None
    if covers_any(target(str(cfg_path)), forms):
        kind = "config"
    elif covers_any(target(str(md_path)), forms):
        kind = "md"
    else:
        for rel in rels_in_root(path, root, base):
            if rel.casefold() == "設定/config.json":
                kind = "config"
            elif rel.casefold() == "claude.md":
                kind = "md"
    if kind is None:
        return False
    f = cfg_path if kind == "config" else md_path
    try:
        old = f.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return False  # まだ無い：新規作成は通す
    except OSError:
        return True
    new = _text_after(tool, inp, old)
    if new is None:
        return True
    if kind == "config":
        return _limit_keys(old) != _limit_keys(new)
    return _exception_sections(old) != _exception_sections(new)


def check(payload, root, command=None):
    """本人のフォルダ root の規則で判定する。command を渡したら、Bash はその部分だけを見る（外のセッション）。"""
    tool = payload.get("tool_name", "")
    inp = payload.get("tool_input") or {}
    if tool == "Bash":
        full = inp.get("command", "")
        flat = normalize(full if command is None else command)
        qf = quiet(flat)  # 2>/dev/null・2>&1 などを除いてから規則を当てる（R4）
        q = quiet(mask_inert(flat))  # 実行されない文字（git commit の本文・書くだけの本文・python の文字列）をならす（T061）
        for label, pat in BASH_RULES:
            if rule_hit(pat, q):
                if (label in DEV_ALLOWED and not GLOBAL_INSTALL.search(flat) and not pip_outside_venv(flat)
                        and in_dev_area(flat, payload, root)):
                    continue
                return label, full
        an = analyze(flat, base_cwd(payload, root))
        label = input_hit(an, root)
        if label is None and "<<" in qf and any(m(qf) for m in LEGACY_INPUT_RULES):
            label = "元データの移動・上書き"
        if label is None and any(p.launched and any(m(quiet(p.text)) for m in LEGACY_INPUT_RULES) for p in an.parts):
            label = "元データの移動・上書き"  # 起動役（xargs・find -exec など）のあるコマンドには、前の文字の規則も残す（指摘2）
        if label is None and unresolvable_source(an):
            label = "動かす・消す元を読み切れない（リンクのループ）"
        if label is None and any(p.cwd_unknown and p.cmd and p.cmd not in READ_ONLY_CMDS for p in an.parts):
            label = UNKNOWN_CWD_LABEL  # cd の行き先を読み切れないあとで、読むだけでない操作をする（止める側。T092 で ask）
        if label:
            return label, full
    elif tool in WRITE_TOOLS:
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        if not path:
            return None
        if plugin_area(path) in ("source", "unknown") and not is_maintainer(root):
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
        if self_limit_hit(tool, inp, root, path, forms, base):  # AI が自分の制限を外す書き換え（T059）
            return SELF_LIMIT_LABEL, path
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


def judge_new(payload):
    """新しい判定（構造で読む）。None（当たらない）か、(判定 "deny"／"allow"（本人の許可する例外で通す）, ラベル, 対象, ログを書く本人のフォルダ)。"""
    root = project_dir(payload)
    _SEEN["root"] = root
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


# ---- 前の版（4560a92）の判定を重ねる（T058 の決め：前の版より悪くしない）----
# 前の版が止めたものは、原則として止める。通すのは、前の版の当たり方が R1〜R4 だけで、構造で読み切れて、
# 行き先が守っているものの外だと確かめられた形（R1〜R4 の通す側）だけ。

_LEGACY = None
_LEGACY_FORMS = {}
_LEGACY_TO_PATHS = {}
_LEGACY_OWNER_OF = {}


def _legacy_path_forms(p, base=None):
    """前の版と同じ形（abspath と realpath(abspath)）。深い場所を何度も解いても長さの2乗にしない。"""
    key = (p if isinstance(p, str) else os.fspath(p) if isinstance(p, os.PathLike) else repr(p), base)
    r = _LEGACY_FORMS.get(key)
    if r is None:
        try:
            t = os.path.expanduser(os.fspath(p))
            if base is not None and not os.path.isabs(t):
                t = os.path.join(base, t)
            a = fast_abspath(t)
            r = {nfc(a), nfc(fast_realpath(a))}
        except (OSError, ValueError, TypeError):
            r = set()
        _LEGACY_FORMS[key] = r
    return set(r)


def _legacy_owner_of(d, recs):
    """前の版の find_owner の1つの道の分（d から上にたどって、印か記録のあるフォルダ）。たどった結果を覚えておく。"""
    L = _LEGACY
    chain_, cur = [], d
    while True:
        key = str(cur)
        if key in _LEGACY_OWNER_OF:
            found = _LEGACY_OWNER_OF[key]
            break
        if L.is_owner_dir(cur):
            found = ("mark", cur)
            break
        if nfc(key) in recs:
            found = ("rec", cur)
            break
        chain_.append(key)
        parent = cur.parent
        if parent == cur:
            found = None
            break
        cur = parent
    for k in chain_:
        _LEGACY_OWNER_OF[k] = found
    return found


def _legacy_find_owner(path):
    L = _LEGACY
    recs = set(L.load_records())
    for f in sorted(L.path_forms(path)):
        found = _legacy_owner_of(Path(f), recs)
        if found is not None:
            kind, d = found
            if kind == "mark":
                remember_owner(d)
            return L._resolved(d)
    return None


def legacy():
    """前の版の判定（ng_guard_legacy.py）を読み込む。速さと例外への強さの部品だけ、こちらのものに差し替える（判定は同じ）。"""
    global _LEGACY
    if _LEGACY is None:
        sys.dont_write_bytecode = True  # プラグインのフォルダに __pycache__ を作らない
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
        import ng_guard_legacy as L
        _LEGACY = L
        L.path_forms = _legacy_path_forms
        L.os_path_join_norm = join_norm
        orig_to_paths = L.to_paths

        def memo_to_paths(t, cwd):
            key = (t, cwd)
            if key not in _LEGACY_TO_PATHS:
                _LEGACY_TO_PATHS[key] = orig_to_paths(t, cwd)
            return set(_LEGACY_TO_PATHS[key])
        L.to_paths = memo_to_paths
        L.find_owner = _legacy_find_owner
        L.allow_patterns = allow_patterns       # 例外への強さ（指摘5）：形の違う設定でも落ちない
        L.dev_paths = dev_paths
        L.in_dev_area = in_dev_area
        L.is_maintainer = is_maintainer
        L.plugin_area = plugin_area           # リンクのループでも落ちない
        L.python_sources = python_sources       # 同じ結果を長さの2乗にせずに出す
    return _LEGACY


def _set_flags(L, r1=False, r2=False, s03=False, splug=False):
    L.R1_NO_NAMES, L.R2_FIND, L.SKIP_03, L.SKIP_PLUGIN_COPY = r1, r2, s03, splug


R3_PARSED = {"cp", "gcp", "mv", "tee", "sed", "gsed", "perl", "install", "ditto", "ln", "cat", "head", "tail", "less",
             "more", "ls", "grep", "egrep", "fgrep", "rg", "wc", "diff", "cmp", "stat", "file", "md5", "shasum",
             "sha256sum", "du", "find", "touch", "mkdir", "unzip", "tar", "echo", "printf", "realpath", "readlink"}


def _risky_text(t):
    return bool(re.search(r"\$\(|`|<\(|>\(", t))


def r3_confirmed(an, flat):
    """R3 の通す側か：03_インプット が出てくる部分が、すべて構造で読めるコマンドで（起動役の推し量りでない）、
    今いる場所も読み切れている。構造の判定（input_hit）はすでに通っている。"""
    if "<<" in flat:
        return False
    for p in an.parts:
        if "03_インプット" not in nfc(p.text):
            continue
        if p.cmd not in R3_PARSED or p.cwd_unknown or p.guessed or _risky_text(p.text):
            return False
    return True


def plugin_confirmed(an, flat):
    """プラグインのコピーを読むだけか：.claude/plugins が出てくる部分が、すべて読むだけのコマンド（cat・ls・diff など）か、
    python3 でコピーの中のスクリプトを動かすだけ。今いる場所がコピーの中の部分も無い。構造の判定（書き込み先）はすでに通っている。"""
    plug = target(plugins_dir())
    for body in an.bodies:
        if ".claude/plugins" in body:
            return False
    for p in an.parts:
        if p.cwd != UNKNOWN_CWD and covers_any(plug, path_forms(p.cwd)):
            return False
        if ".claude/plugins" not in p.text:
            continue
        if p.cwd_unknown or p.guessed or _risky_text(p.text):
            return False
        if p.cmd in READ_ONLY_CMDS - {"cd", "pushd", "find", "open"}:
            continue
        if re.match(r"^python[\d.]*$", p.cmd) and p.args and ".claude/plugins" in p.args[0] and \
                not any(".claude/plugins" in a for a in p.args[1:]):
            continue  # コピーの中のスクリプトを動かすだけ（update_dashboard.py など）
        return False
    return True


def legacy_decision(payload, root_new):
    """前の版の判定。止めるなら (ラベル, 対象, ログを書く本人のフォルダ)。R1〜R4 の通す側だと確かめられたら None。"""
    L = legacy()
    try:
        _set_flags(L)
        v = L.verdict(payload)
        if v is None:
            return None
        relaxed, flat, an = dict(payload), None, None
        if payload.get("tool_name") == "Bash" and isinstance((payload.get("tool_input") or {}).get("command"), str):
            flat = normalize(payload["tool_input"]["command"])
            relaxed["tool_input"] = dict(payload["tool_input"], command=relax_text(flat))  # R4：2>/dev/null・2>&1 を除く。T061：実行されない文字・cd のあとの読むだけもならす
            an = analyze(flat, base_cwd(payload, root_new))
        s03 = an is not None and r3_confirmed(an, flat)
        splug = an is not None and plugin_confirmed(an, flat)
        _set_flags(L, r1=True, r2=True, s03=s03, splug=splug)
        v2 = L.verdict(relaxed)
        return v if v2 is not None else None
    except DeadlineExceeded:
        raise
    except Exception:  # 前の版も、読めないときは中を止めた
        return ("見張りの入力を読めませんでした（前の版の判定）", "（入力不明）", root_new) if root_new is not None else None
    finally:
        _set_flags(L)


def judge(payload):
    """新しい判定（構造で読む）と、前の版の判定を重ねる。どちらかが止めれば止める（前の版は R1〜R4 の通す側を除く）。"""
    res = judge_new(payload)
    if res is not None and res[0] == "deny":
        return res
    old = legacy_decision(payload, _SEEN["root"] if _SEEN["root"] != "unset" else None)
    if old is not None:
        label, what, log_root = old
        return "deny", label, what, log_root
    return res


_SEEN = {"root": "unset"}  # judge が見つけた本人のフォルダ（締め切りを超えたときに使う）
TIMEOUT_LABEL = "見張りが時間内に判定できませんでした（長すぎる・複雑すぎるコマンド）"
BROKEN_LABEL = "見張りの入力を読めませんでした"


def mentions_owner(payload):
    """入力の文面に、記録にある本人のフォルダ（絶対パス・~/ の形・$HOME の形）が出てくるか。出てくればその本人のフォルダ。
    締め切りを超えたとき・読み切れないときに、外のセッションで止めるかを決める（指摘3・5）。大文字小文字は区別しない。"""
    if not isinstance(payload, dict):
        return None
    try:
        text = nfc(json.dumps(payload.get("tool_input"), ensure_ascii=False)).casefold()
    except Exception:
        return None
    home = nfc(os.path.expanduser("~")).rstrip(os.sep)
    for f, r in record_roots():
        forms = {nfc(f), nfc(str(r))}
        for x in list(forms):
            if x.startswith(home + os.sep):
                rel = x[len(home) + 1:]
                forms |= {"~/" + rel, "$HOME/" + rel, "${HOME}/" + rel}
        if any(x.casefold() in text for x in forms if x):
            return r
    return None


def fallback_decision(payload, label):
    """判定しきれなかったとき（締め切り超え・思わぬ例外）：(deny するか, ラベル, ログを書く本人のフォルダ)。
    本人のフォルダの中なら止める。外は、記録にある本人のフォルダが文面に出ていれば止め、出ていなければ通す。"""
    root = _SEEN["root"]
    if root == "unset":
        try:
            root = project_dir(payload if isinstance(payload, dict) else {})
        except Exception:
            root = None
    if root is not None:
        return True, label, root
    hit = mentions_owner(payload)
    if hit is not None:
        return True, label, hit
    return False, label, None


def _arm(sec):
    try:
        return start_deadline(sec)
    except Exception:
        return False


def _disarm():
    try:
        stop_deadline()
    except Exception:
        pass


def decide(payload_text, deadline=None):
    """入力の文字列から判定する。締め切り（DEADLINE_SEC）と、思わぬ例外の受け皿つき。
    (deny するか, ラベル, 対象, ログを書く本人のフォルダ, ツール名, 例外の受け皿を通ったか)"""
    payload = None
    _arm(deadline_seconds(deadline))
    try:
        payload = json.loads(payload_text)
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
        res = judge(payload)
        _disarm()
        if res is None:
            return False, None, None, None, payload.get("tool_name"), False
        decision, label, what, log_root = res
        return decision == "deny", label, what, log_root, payload.get("tool_name"), False
    except DeadlineExceeded:
        label = TIMEOUT_LABEL
    except Exception:
        label = BROKEN_LABEL
    finally:
        _disarm()
    tool = payload.get("tool_name") if isinstance(payload, dict) else None
    _arm(1.0)  # 受け皿にも短い締め切り。超えたら止める側
    try:
        d, label, root = fallback_decision(payload, label)
    except DeadlineExceeded:
        d, root = True, None
    except Exception:
        d, root = True, None
    finally:
        _disarm()
    return d, label, "（入力不明）" if label == BROKEN_LABEL else "（時間切れ）", root, tool, True


def run_guard():
    deny_it, label, what, root, tool, _ = decide(sys.stdin.read())
    if deny_it:
        deny(label, what, root, tool)
    return 0


def explain(command):
    """--explain "<コマンド>"：今いる場所で Bash のコマンドを判定し、判定（deny／pass）と理由の語を出す。
    見張りの記録（owners.json）にも ng_log にも書かない。締め切りも本物と同じ。"""
    global DRY_RUN
    DRY_RUN = True
    try:
        cwd = os.getcwd()
    except OSError:
        cwd = os.path.expanduser("~")
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd}
    deny_it, label, what, root, tool, fell = decide(json.dumps(payload, ensure_ascii=False))
    if fell:
        print("判定：" + ("deny" if deny_it else "pass"))
        print(f"理由：{label}")
        return 0
    if label is None:
        print("判定：pass")
        print("理由：当たる規則なし")
        return 0
    if not deny_it:
        print("判定：pass")
        print(f"理由：本人の許可する例外（ng_allow）に一致（当たった規則：{label}）")
    else:
        print("判定：deny")
        print(f"理由：{label}")
    print(f"本人のフォルダ：{root if root is not None else '（なし）'}")
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--explain":
        if len(sys.argv) < 3:
            print('使い方：python3 ng_guard.py --explain "<コマンド>"', file=sys.stderr)
            return 2
        return explain(" ".join(sys.argv[2:]))
    try:
        return run_guard()
    except BaseException:
        # ここまで来るのは deny の書き出しなどの失敗だけ。中なら止める
        try:
            root = project_dir({})
        except BaseException:
            root = None
        if root is not None:
            try:
                deny(BROKEN_LABEL, "（入力不明）", root)
            except BaseException:
                pass
        return 0


if __name__ == "__main__":
    sys.exit(main())
