#!/usr/bin/env python3
"""NG の見張り（PreToolUse hook）。権限の設定（deny）をすり抜ける書き方も含めて、やってはいけない操作を実行前に止める。

止めたら理由を Claude に返し（permissionDecision: deny）、00_タスク管理/data/ng_log.jsonl に記録する。
本人が許可した例外は 設定/config.json の "ng_allow"（正規表現のリスト。コマンドやパスに一致したら通す）に書く。

動くのは本人のフォルダの中だけ。印（設定/config.json・00_タスク管理/data/tasks.json・.claude/rules/ai-bunshin-common.md）の
どれか1つがあれば本人のフォルダ。今いる場所から上にたどって探す（リンクを解いた道と解かない道の両方）。
ほかのプロジェクトでは何も止めない。ただし、
- プラグインのコピー（~/.claude/plugins/ の下）への書き込みは、どこでも止める
- 外で始めたセッションでも、Write・Edit のパスや Bash の中のパス（絶対パス・~/・$HOME/）が本人のフォルダの中を指すなら、その本人のフォルダを基準に判定する
- 見張りの入力を読めなかったときは、本人のフォルダの中なら止める、外なら通す
"""
import json
import os
import re
import shlex
import sys
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


def cmd(words):
    return B + r"(?:" + words + r")" + E


# 本人のフォルダの印・その入れ物（動かすと見張りが外れる）
PROTECTED_NAMES = (r"(?:設定(?:/config\.json)?|00_タスク管理(?:/data(?:/tasks\.json)?)?|"
                   r"\.claude(?:/rules(?:/ai-bunshin-common\.md)?)?)/?")

BASH_RULES = [
    ("削除", cmd(r"rm|rmdir|unlink|shred|trash|srm|truncate")),
    ("削除", r"\bfind\b[^\n]*\s-(?:delete\b|(?:exec|execdir|ok|okdir)\s+(?:\S*/)?rm\b)"),
    ("削除・書き換え（git）",
     B + r"git\s+(?:-\S+(?:\s+[^-\s]\S*)?\s+)*(?:push|clean|rebase|restore|reset\s+--hard|stash\s+(?:drop|clear)|"
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
     r"\bpython3?\b[\s\S]*(?:os\.(?:remove|unlink|rmdir|removedirs|system)\b|shutil\.rmtree|\.unlink\(|\.rmdir\(|"
     r"requests\.(?:post|put|delete|patch)|smtplib|urlopen\()"),
    ("スクリプト経由の削除", r"\bperl\b[^\n]*\s-\w*e\b[^\n]*\b(?:unlink|rmdir|system)\b"),
    ("スクリプト経由の削除", r"\bruby\b[^\n]*\s-\w*e\b[^\n]*(?:File\.delete|FileUtils\.rm|system)"),
    ("スクリプト経由の削除", r"\bnode\b[^\n]*\s-\w*e\b[^\n]*(?:rmSync|unlinkSync|rmdirSync|\.rm\(|\.unlink\(|child_process)"),
    # 印（設定・タスクの正本）を動かすと見張りが外れるので、移す・名前を変える操作を止める
    ("本人の設定・タスクの正本の移動",
     B + r"(?:git\s+mv|mv|rename)(?=\s)[^\n;&|]*[\s\"'/=]" + PROTECTED_NAMES + r"(?=$|[\s\"';&|)])"),
    ("本人の設定・タスクの正本の移動",
     r"\bpython3?\b(?=[\s\S]*(?:os\.(?:rename|renames|replace)\b|shutil\.move\b|\.rename\(|\.replace\(\s*[\"'\w/.~$]+[\"']?\s*\)))"
     r"(?=[\s\S]*(?:設定|00_タスク管理|config\.json|tasks\.json|ai-bunshin-common))"),
    ("空にする・上書き", r"\bdd\b[^\n]*\bof="),
    ("空にする・上書き", r"\b(?:cp|cat)\s+/dev/null\b"),
    ("空にする・上書き", r"\bln\s+-\w*f\w*\s+/dev/null\b"),
    ("空にする・上書き", r"(?:^|\n|[;&|]\s*)\s*:\s*>"),
    ("空にする・上書き", r">\|"),
    ("ゴミ箱・破棄", r"\bmv\b[^\n]*\s(?:/dev/null|\S*/\.Trash\b)"),
    ("保護されたファイルの書き換え",
     r"\b(?:sed|perl)\b[^\n]*\s-i\b[^\n]*\s[\"']?(?:\./)?(?:\.claude/|CLAUDE\.md(?=$|[\s\"'])|設定/|03_インプット/)"),
    ("元データの移動・上書き", r"\b(?:mv|cp|tee)\b[^\n]*\s[\"']?(?:\./)?03_インプット/"),
    ("保護されたファイルの上書き", r">>?\s*[\"']?(?:\S*/)?(?:03_インプット/|\.claude/settings[^\s]*\.json)"),
]


def normalize(cmd_text):
    """\\rm・r\\m・行末の \\ による改行など、見た目をずらす書き方をならす。"""
    t = cmd_text.replace("\\\n", " ")
    return re.sub(r"\\(?=[A-Za-z])", "", t)


# Write / Edit で書いてはいけない場所（本人のフォルダからの相対パスで判定）
PROTECTED_PATHS = [
    ("元データ（読むだけ）", r"^03_インプット/"),
    ("権限・設定", r"^\.claude/settings(?:\.local)?\.json$"),
    ("hook・権限（.claude の設定）", r"^\.claude/hooks/"),
    ("共通ルールの自動コピー（プラグイン側を直す）", r"^\.claude/rules/ai-bunshin-common\.md$"),
]


OWNER_MARKS = (("設定", "config.json"), ("00_タスク管理", "data", "tasks.json"), (".claude", "rules", "ai-bunshin-common.md"))


def is_owner_dir(d):
    """本人のフォルダか：印（設定/config.json・00_タスク管理/data/tasks.json・.claude/rules/ai-bunshin-common.md）の
    どれか1つがある。「両方」を条件にすると、片方を動かすだけで見張りが外れるので、1つでよい。"""
    try:
        return any(d.joinpath(*m).is_file() for m in OWNER_MARKS)
    except (OSError, ValueError):
        return False


def find_owner(path):
    """path（ファイルでもよい）から上にたどって本人のフォルダを探す。リンクを解かない道（abspath）と解いた道（resolve）の
    両方を見て、どちらかで見つかれば返す（解いたフォルダ）。"""
    try:
        text = os.path.expanduser(os.fspath(path))
        cands = [Path(os.path.abspath(text))]
    except (OSError, ValueError, TypeError):
        return None
    try:
        cands.append(Path(text).resolve())
    except (OSError, ValueError, RuntimeError):
        pass
    for q in cands:
        for d in (q, *q.parents):
            if is_owner_dir(d):
                try:
                    return d.resolve()
                except (OSError, RuntimeError):
                    return d
    return None


def project_dir(payload):
    """本人のフォルダを返す。今いる場所（CLAUDE_PROJECT_DIR・payload の cwd・os.getcwd）から上にたどって探す
    （05_開発/ などの下で動いていても本人のフォルダ）。見つからなければ None（＝ほかのプロジェクト。見張りは通す）。"""
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


PATH_WORD = re.compile(r"(?:^|[\s\"'=:(<>])((?:~|\$HOME|\$\{HOME\}|/)[^\s\"';&|()<>`]*)")


def roots_from_input(payload):
    """起動場所が本人のフォルダの外のとき、操作の中のパス（Write・Edit のパス、Bash の絶対パス・~/・$HOME/）から
    上にたどって見つかる本人のフォルダ（重複なし）。"""
    tool = payload.get("tool_name", "")
    inp = payload.get("tool_input")
    if not isinstance(inp, dict):
        return []
    paths = []
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        p = inp.get("file_path") or inp.get("notebook_path")
        if isinstance(p, str) and p:
            if not os.path.isabs(os.path.expanduser(p)):
                base = payload.get("cwd") if isinstance(payload.get("cwd"), str) else os.getcwd()
                p = os.path.join(base, p)
            paths.append(p)
    elif tool == "Bash" and isinstance(inp.get("command"), str):
        home = os.path.expanduser("~")
        for m in PATH_WORD.finditer(normalize(inp["command"])):
            t = m.group(1).replace("${HOME}", home).replace("$HOME", home)
            if t.startswith("~") and not t.startswith("~/") and t != "~":
                continue
            paths.append(t)
    roots = []
    for p in paths[:60]:
        r = find_owner(p)
        if r is not None and r not in roots:
            roots.append(r)
    return roots


def moves_owner_root(flat, payload, root):
    """mv・git mv・rename で、本人のフォルダそのもの（や、その親）を動かす操作か（最後の語は行き先なので見ない）。"""
    base = payload.get("cwd") if isinstance(payload.get("cwd"), str) and payload.get("cwd") else str(root)
    for seg in re.split(r"[;&|\n]+", flat):
        try:
            words = shlex.split(seg)
        except ValueError:
            words = seg.split()
        for i, w in enumerate(words):
            if os.path.basename(w) not in ("mv", "rename"):
                continue
            args = words[i + 1:]
            has_t = any(a in ("-t", "--target-directory") or a.startswith("--target-directory=") for a in args)
            srcs, skip = [], False
            for a in args:
                if skip:
                    skip = False
                    continue
                if a in ("-t", "--target-directory"):
                    skip = True
                    continue
                if a.startswith("-"):
                    continue
                srcs.append(a)
            if not has_t:
                srcs = srcs[:-1]
            for a in srcs:
                t = os.path.join(base, os.path.expanduser(a))
                try:
                    qs = (Path(os.path.abspath(t)), Path(t).resolve())
                except (OSError, ValueError, RuntimeError):
                    continue
                if any(q == root or q in root.parents for q in qs):
                    return True
    return False


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


# プラグインの保護は、本人の許可する例外（ng_allow）でも外さない
NO_EXCEPTION_LABELS = ("プラグインのコピーの書き換え", "共通部分（プラグインの元）の書き換え")


def check(payload, root):
    """root が None（本人のフォルダの外）のときは、プラグインのコピーの保護だけ効かせ、ほかは止めない。"""
    tool = payload.get("tool_name", "")
    inp = payload.get("tool_input") or {}
    if tool == "Bash":
        command = inp.get("command", "")
        flat = normalize(command)
        plugin_label = plugin_bash_check(flat, root)
        if plugin_label:
            return plugin_label, command
        if root is None:
            return None
        if moves_owner_root(flat, payload, root):
            return "本人の設定・タスクの正本の移動（本人のフォルダそのものを動かす）", command
        for label, pat in BASH_RULES:
            if re.search(pat, flat):
                if (label in DEV_ALLOWED and not GLOBAL_INSTALL.search(flat) and not pip_outside_venv(flat)
                        and in_dev_area(flat, payload, root)):
                    continue
                return label, command
    elif tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        area = plugin_area(path) if path else None
        if area == "copy":
            return "プラグインのコピーの書き換え（Claude Code が読み込む共通部分。元を直して更新する）", path
        if root is None:
            return None
        if area == "source" and not is_maintainer(root):
            return "共通部分（プラグインの元）の書き換え（メンテする人だけ。提案の下書きにする）", path
        for q in (Path(os.path.abspath(path)), Path(path).resolve()):  # リンクを解かない道と解いた道の両方
            try:
                rel = q.relative_to(root).as_posix()
            except ValueError:
                continue
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


def run_guard():
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise ValueError("payload is not an object")
    root = project_dir(payload)
    if root is not None:
        hit = check(payload, root)
    else:
        hit = check(payload, None)  # プラグインのコピーの保護
        if not hit:  # 外で始めたセッション：操作の中のパスが本人のフォルダを指すなら、その本人のフォルダを基準に判定
            for r in roots_from_input(payload):
                hit = check(payload, r)
                if hit:
                    root = r
                    break
    if not hit:
        return 0
    label, target = hit
    if root is not None and not label.startswith(NO_EXCEPTION_LABELS) and any(p.search(target) for p in allow_patterns(root)):
        return 0
    deny(label, target, root, payload.get("tool_name"))
    return 0


def main():
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
