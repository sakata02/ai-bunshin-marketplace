#!/usr/bin/env python3
"""設定/config.json の "display"（使い方の型：シンプル／フル）だけを書き換える（T182 組②。設計 T146 §5）。

本人が会話の中で「シンプルにして」「フルにして」「pt も見せて」と言ったときに、AI がこれで切り替える。
書くのは config.json の "display" のキーだけ。ほかのキー（ng_allow・maintainer など）と値・並び・BOM・改行・字下げは変えない。
自動実行の中では切り替えない（設計 P4。自動実行は Edit(設定/**) を止めていて、Bash も update_dashboard.py と lock_check.py だけ）。

使い方:
  python3 scripts/set_display.py show                         # 今の見せ方を表で出す（読むだけ）
  python3 scripts/set_display.py type simple|full             # 型を切り替える（個別の設定 overrides は残す）
  python3 scripts/set_display.py override <名前> <値>         # 1つだけ個別に変える（例：override terms full）
  python3 scripts/set_display.py reset-overrides              # 個別の設定を全部戻す（本人に確かめてから）
  名前：features terms requests_max stop_notice review_view team_view
  値：simple か full（requests_max だけは 1〜20 の整数）

最後の行は必ず「[見せ方：…]」（設計 U11・P12）。起動時のまとめ（update_dashboard.py）と同じ文面（K3）。
個別の設定があるときは、その「すぐ前の行」に「個別の設定（型より優先）：terms=full、…」を出す（K11）。
終了コード：0＝成功、1＝config が読めない・書けない・自動実行の中など、2＝使い方・値の間違い（何も書かない）。
"""
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

TYPES = ("simple", "full")
OVERRIDE_NAMES = ("features", "terms", "requests_max", "stop_notice", "review_view", "team_view")   # 設計 §3 の6つ。この順で並べる
REQUESTS_RANGE = (1, 20)                                                                                # U14
# 「[見せ方：…]」の文面。update_dashboard.py にも同じ文を持たせている（K3：import で共通にしない＝U02。同じことは ⑦ のテストで比べる）
TYPE_LINE = {"simple": "[見せ方：シンプル（言葉・件数の決まりを守る）]",
             "full": "[見せ方：フル（今までどおり）]"}
BROKEN_LINE = "[見せ方：設定の display.type を読めないので、フルで動いています（simple か full に直してください）]"

USAGE = __doc__.split("使い方:")[1].split("最後の行は必ず")[0].rstrip()
USAGE = "使い方:" + USAGE


class Fail(Exception):
    """本人に見せる日本語の理由つきで止める。code は終了コード。"""

    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


# ---- 見せ方の1行（U11・P12。update_dashboard.py と同じ文面） ----

def valid_override(name, value):
    """決まった名前と決まった値だけ true（U14）。bool は整数に数えない。"""
    if name == "requests_max":
        return type(value) is int and REQUESTS_RANGE[0] <= value <= REQUESTS_RANGE[1]
    if name in OVERRIDE_NAMES:
        return isinstance(value, str) and value in TYPES
    return False


def effective(display):
    """display の中身から (型, 効く個別の設定, 気づいたこと, 型が壊れているか, 値が範囲外の項目) を出す（K8）。
    読み方は update_dashboard.py の read_display と同じ：無い・空は静かにフル。壊れている（{ } でない・type が simple か full 以外）ときは
    フルにして、個別の設定は読まない。決まった名前で値が範囲外の項目は、その項目だけフル（invalid に入れる）。知らない名前は無視。"""
    notes = []
    if display is None or display == "" or display == {} or display == []:
        return "full", {}, notes, False, set()
    if not isinstance(display, dict):
        return "full", {}, ["display が { } の形ではないので、フルとして扱っています（個別の設定は使っていません）"], True, set()
    typ = "full"
    if "type" in display:
        t = display["type"]
        if not (isinstance(t, str) and t in TYPES):
            return "full", {}, ["display の type が simple か full ではないので、フルとして扱っています（個別の設定は使っていません）。"
                                "直すには「シンプルにして」か「フルにして」と言ってください"], True, set()
        typ = t
    else:
        notes.append("type 未設定（フル）として動いています。個別の設定だけが入っています。型を決めるには「シンプルにして」か「フルにして」と言ってください")
    raw_ov = display.get("overrides", {})
    ov, invalid, unknown = {}, set(), []
    if not isinstance(raw_ov, dict):
        notes.append("display の overrides が { } の形ではないので、個別の設定は使っていません")
    else:
        for k, v in raw_ov.items():
            if valid_override(k, v):
                ov[k] = v
            elif k in OVERRIDE_NAMES:
                invalid.add(k)
            else:
                unknown.append(f"{k}={json.dumps(v, ensure_ascii=False)}")
        if unknown:
            notes.append("決まりにない名前の個別の設定は無視しています：" + "、".join(unknown))
    return typ, {n: ov[n] for n in OVERRIDE_NAMES if n in ov}, notes, False, invalid


def display_line(typ, broken=False):
    """「[見せ方：…]」の1行（update_dashboard.py の起動時のまとめと同じ文）。"""
    return BROKEN_LINE if broken else TYPE_LINE[typ]


def overrides_line(ov):
    """個別の設定があるときの1行（「[見せ方：…]」のすぐ前に出す。K11）。無ければ空。update_dashboard.py の overrides_line と同じ文面・並び。"""
    return ("個別の設定（型より優先）：" + "、".join(f"{n}={ov[n]}" for n in OVERRIDE_NAMES if n in ov)) if ov else ""


# ---- 本人のフォルダと config の読み書き ----

def find_root():
    """本人のフォルダ（00_タスク管理/data/tasks.json がある場所）。update_dashboard.py の find_root と同じ探し方。
    AI_BUNSHIN_HOME があれば、そのフォルダだけを見る（無ければ None。ほかのフォルダに探しに行かない）。"""
    env = os.environ.get("AI_BUNSHIN_HOME")
    if env:
        d = Path(env).resolve()
        return d if (d / "00_タスク管理" / "data" / "tasks.json").exists() else None
    for c in (os.environ.get("CLAUDE_PROJECT_DIR"), os.getcwd()):
        if not c:
            continue
        d = Path(c).resolve()
        for x in (d, *d.parents):
            if (x / "00_タスク管理" / "data" / "tasks.json").exists():
                return x
    return None


def load_config(path):
    """(辞書, 元のバイト列, 形の情報)。読めない・形が違うときは Fail（書き換えない）。"""
    try:
        raw = Path(path).read_bytes()
    except FileNotFoundError:
        raise Fail("設定/config.json が見つかりません。初回セットアップ（/ai-bunshin:setup）が終わっているか確かめてください。何も書き換えていません")
    except OSError as e:
        raise Fail(f"設定/config.json を読めません（{e.__class__.__name__}）。何も書き換えていません")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise Fail("設定/config.json が UTF-8 の文字ではありません。壊れたファイルは書き換えていません。"
                   "メモ帳などで開いて、文字コードを UTF-8 にして保存し直してください")
    bom = text.startswith("﻿")
    if bom:
        text = text[1:]   # メモ帳の BOM。見張り（ng_guard）も1つだけ落とす
    if not text.strip():
        raise Fail("設定/config.json が空です。壊れたファイルは書き換えていません")
    try:
        cfg = json.loads(text)
    except (ValueError, RecursionError) as e:
        raise Fail(f"設定/config.json が JSON として読めません（{e}）。壊れたファイルは書き換えていません。"
                   "カンマや引用符の抜けを直してください")
    if not isinstance(cfg, dict):
        raise Fail("設定/config.json は { } で始まる形にしてください（今は別の形です）。壊れたファイルは書き換えていません")
    return cfg, raw, style_of(text, raw, bom)


def style_of(text, raw, bom):
    """元のファイルの書き方（BOM・改行・字下げ・末尾の改行・日本語の \\u 表記）。書き戻すときに同じにする。"""
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n") - crlf
    m = re.search(r"^([ \t]+)\S", text, re.M)
    if m is None:
        indent = None            # 1行に詰めた書き方
    elif m.group(1).startswith("\t"):
        indent = "\t"
    else:
        indent = len(m.group(1))
    ascii_only = all(ord(c) < 128 for c in text)
    return {"bom": bom, "crlf": crlf > lf, "indent": indent,
            "tail": text[len(text.rstrip()):],
            "ensure_ascii": ascii_only and bool(re.search(r"\\u[0-9a-fA-F]{4}", text))}


def render(cfg, style):
    body = json.dumps(cfg, ensure_ascii=style["ensure_ascii"], indent=style["indent"])
    if style["crlf"]:
        body = body.replace("\n", "\r\n")
    return (("﻿" if style["bom"] else "") + body + style["tail"]).encode("utf-8")


def with_display(cfg, display):
    """display だけを入れた新しい辞書。キーの位置は、すでにあればそのまま、無ければ maintainer の前（雛形と同じ）か末尾。"""
    if "display" in cfg:
        new = dict(cfg)
        new["display"] = display
        return new
    new = {}
    for k, v in cfg.items():
        if k == "maintainer":
            new["display"] = display
        new[k] = v
    new.setdefault("display", display)
    return new


def check_only_display_changed(old, new_bytes, style, display):
    """書く前の最後の確かめ：書く中身を読み直して、display 以外（キーの並びも）が元と同じで、display が狙いどおりか。"""
    text = new_bytes.decode("utf-8")
    chk = json.loads(text[1:] if style["bom"] else text)
    rest_old = [(k, v) for k, v in old.items() if k != "display"]
    rest_new = [(k, v) for k, v in chk.items() if k != "display"]
    if rest_old != rest_new or chk.get("display") != display:
        raise Fail("書く中身の確かめで、display 以外が変わってしまうことが分かりました。何も書き換えていません（作者に知らせてください）")


def replace_with_retry(tmp, path):
    """os.replace。相手が一瞬つかんでいる（Windows の PermissionError など）ときは、0.2秒おいて最大3回まで試す。"""
    for attempt in range(3):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 2:
                raise
            time.sleep(0.2)


def write_atomic(path, data, expect):
    """一時ファイルに書いてから置き換える（update_dashboard.py の atomic_write_text と同じ考え方）。
    置き換える直前に元のファイルを読み直し、expect と違えば（ほかで書き換えられた）置き換えない。"""
    target = Path(os.path.realpath(path))   # リンクのときは、リンク先を書く（リンクそのものを置き換えない）
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if target.read_bytes() != expect:
            raise Fail("書いている間に設定/config.json がほかで書き換えられました。何も書き換えていません。もう一度言ってください")
        try:
            shutil.copymode(target, tmp)
        except OSError:
            pass
        replace_with_retry(tmp, target)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


# ---- 操作 ----

def parse_args(argv):
    """(操作, 引数) か Fail(code=2)。知らない名前・値はここで止める（書かない）。"""
    if not argv:
        raise Fail("やることを指定してください。\n" + USAGE, 2)
    cmd, rest = argv[0], argv[1:]
    if cmd == "show" and not rest:
        return "show", ()
    if cmd == "reset-overrides" and not rest:
        return "reset-overrides", ()
    if cmd == "type":
        if len(rest) != 1 or rest[0] not in TYPES:
            raise Fail("type の値は simple か full のどちらかです（例：type simple）。何も書き換えていません", 2)
        return "type", (rest[0],)
    if cmd == "override":
        if len(rest) != 2:
            raise Fail("override は「名前」と「値」を1つずつ指定してください（例：override terms full）。何も書き換えていません", 2)
        name, value = rest
        if name not in OVERRIDE_NAMES:
            raise Fail(f"「{name}」は決まりにない名前です。使える名前：{' '.join(OVERRIDE_NAMES)}。何も書き換えていません", 2)
        if name == "requests_max":
            if not re.fullmatch(r"[0-9]{1,3}", value) or not REQUESTS_RANGE[0] <= int(value) <= REQUESTS_RANGE[1]:
                raise Fail(f"requests_max の値は {REQUESTS_RANGE[0]}〜{REQUESTS_RANGE[1]} の整数です（今は「{value}」）。何も書き換えていません", 2)
            return "override", (name, int(value))
        if value not in TYPES:
            raise Fail(f"{name} の値は simple か full のどちらかです（今は「{value}」）。何も書き換えていません", 2)
        return "override", (name, value)
    raise Fail("このやり方は使えません。\n" + USAGE, 2)


def next_display(cfg, op, args):
    """今の display に操作を当てた新しい display（辞書）。display の中のほかのキー・決まりにない個別の設定はそのまま残す。"""
    cur = cfg.get("display")
    d = dict(cur) if isinstance(cur, dict) else {}
    ov = d.get("overrides")
    ov = dict(ov) if isinstance(ov, dict) else {}
    if op == "type":
        d["type"] = args[0]
    elif op == "override":
        ov[args[0]] = args[1]
    elif op == "reset-overrides":
        ov = {}
    d.setdefault("type", "full")   # 無いときは、読む側が使っていた値（フル）を明示する
    d["overrides"] = ov
    ordered = {"type": d["type"], "overrides": d["overrides"]}
    ordered.update({k: v for k, v in d.items() if k not in ordered})
    return ordered


def show_table(typ, ov, has_display, invalid=()):
    rows = ["| 項目 | 今の値 |", "|---|---|", f"| 型（type） | {typ}{'' if has_display else '（display が未設定なのでフル）'} |"]
    for n in OVERRIDE_NAMES:
        rows.append(f"| {n} | {ov[n] if n in ov else '範囲外のためフル' if n in invalid else '型どおり'} |")
    return "\n".join(rows)


def check_link_inside(path, root):
    """設定/config.json がリンクのとき、リンクの先が本人のフォルダの中か（K9）。外なら書かない（見張りの印も、書き先も本人のフォルダの中だけ）。"""
    target = os.path.realpath(path)
    base = os.path.realpath(root)
    try:
        inside = os.path.commonpath([target, base]) == base
    except ValueError:   # Windows でドライブが違うとき
        inside = False
    if not inside:
        raise Fail(f"設定/config.json がリンクで、リンクの先（{target}）が本人のフォルダの外にあります。外のファイルは書き換えません。"
                   "何も書き換えていません。リンクの先を本人のフォルダの中にするか、リンクをやめてから、もう一度言ってください")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if argv and argv[0] in ("-h", "--help"):
            print(USAGE)
            return 0
        op, args = parse_args(argv)
        root = find_root()
        if root is None:
            raise Fail("本人のフォルダが見つかりません（00_タスク管理/data/tasks.json がある場所で実行してください）。何も書き換えていません")
        path = root / "設定" / "config.json"
        cfg, raw, style = load_config(path)

        if op == "show":
            typ, ov, notes, broken, invalid = effective(cfg.get("display"))
            print("今の見せ方（設定/config.json の display）")
            print(show_table(typ, ov, cfg.get("display") not in (None, "", {}, []), invalid))
            for n in notes:
                print("注意：" + n)
            if overrides_line(ov):
                print(overrides_line(ov))
            print(display_line(typ, broken))
            return 0

        if os.environ.get("AI_BUNSHIN_AUTO_RUN"):
            raise Fail("自動実行の中では、見せ方を切り替えません。会話の中で、本人が「シンプルにして」「フルにして」などと言ったときだけ切り替えます。"
                       "何も書き換えていません")

        display = next_display(cfg, op, args)
        typ, ov, notes, broken, invalid = effective(display)
        if cfg.get("display") == display:
            print("すでにその設定です（設定/config.json は書き換えていません）")
        else:
            check_link_inside(path, root)
            new_cfg = with_display(cfg, display)
            data = render(new_cfg, style)
            check_only_display_changed(cfg, data, style, display)
            write_atomic(path, data, raw)
            if op == "type":
                print(f"見せ方の型を {typ} にしました。個別の設定 {len(ov)} 件はそのまま残しています")
            elif op == "override":
                print(f"個別の設定 {args[0]} を {args[1]} にしました。型は {typ} のままです")
            else:
                print("個別の設定を全部戻しました。型は変えていません")
        for n in notes:
            print("注意：" + n)
        if overrides_line(ov):
            print(overrides_line(ov))   # 「[見せ方：…]」のすぐ前の行（K11。起動時のまとめと同じ並び）
        print(display_line(typ, broken))   # 最後の行は必ず「[見せ方：…]」（P12）
        return 0
    except Fail as e:
        print(str(e), file=sys.stderr)
        return e.code
    except OSError as e:
        print(f"設定/config.json を書き換えられませんでした（{e.__class__.__name__}）。元のファイルはそのままです。"
              "Excel やエディタで開いていれば閉じて、もう一度言ってください", file=sys.stderr)
        return 1


if __name__ == "__main__":
    # Windows は標準出力が cp932 のことがあり、日本語で落ちる。入口で UTF-8 にする（reconfigure が無い環境でも落ちない）
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    sys.exit(main())
