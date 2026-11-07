"""scripts/set_display.py のテスト（T182 組②。設計 T146 §1 の P1・P4・P6・P8・P11・P12 と §5）。
- display のキーだけを書く：ほかのキー（ng_allow・maintainer など）・値・並びは変えない。見張り（ng_guard）の目で見ても同じ
- 書き方を守る：BOM・CRLF・字下げ（2・4・タブ・1行）・末尾の改行・日本語の \\u 表記・ファイルの権限・リンク
- リンクの先が本人のフォルダの外なら書かない（K9）
- 型を切り替えても個別の設定（overrides）は残る。消すのは reset-overrides のときだけ
- 知らない名前・値は書かない（requests_max は 1〜20 の整数だけ）。使い方の間違いは終了コード2
- 壊れた config.json（JSON でない・空・{ } でない・UTF-8 でない・無い）は書き換えず、日本語で案内して終了コード1
- 新しい「[見せ方：…]」の1行を出す（P12）。個別の設定の行はその次の行（K11）。update_dashboard.py と同じ文面・並び（K3・K8）
- show・書いたあとの見え方は、update_dashboard.py の read_display と同じ（範囲外の値は「範囲外のためフル」。K8）
- 自動実行の中では切り替えない（P4）：環境変数で止める。daily_cycle.sh の DENY・道具の絞りでも届かない
- 書き込み：一時ファイル→置き換え。失敗しても・書いている間にほかで書き換えられても、元のファイルは壊れない・一時ファイルを残さない
- P1：display を読む所は set_display.py と update_dashboard.py だけ（scripts/・hooks・雛形の settings.json を機械で調べる）
本物の自分のフォルダは使わない（すべて一時フォルダ。AI_BUNSHIN_HOME で指定。CLAUDE_PROJECT_DIR は外す）。
実行：python3 tests/test_set_display.py（失敗があれば終了コード1）"""
import contextlib
import fnmatch
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.abspath(os.path.join(HERE, ".."))
SCRIPTS = os.path.join(PLUGIN, "scripts")
SET_DISPLAY = os.path.join(SCRIPTS, "set_display.py")
NG_GUARD = os.path.join(SCRIPTS, "ng_guard.py")
CYCLE = os.path.join(SCRIPTS, "auto", "daily_cycle.sh")

BASE = os.path.realpath(tempfile.mkdtemp(prefix="setdisp_"))
fails = 0

SIMPLE_LINE = "[見せ方：シンプル（言葉・件数の決まりを守る）]"
FULL_LINE = "[見せ方：フル（今までどおり）]"
BROKEN_LINE = "[見せ方：設定の display.type を読めないので、フルで動いています（simple か full に直してください）]"


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


_n = [0]


def new_dir(prefix="o"):
    _n[0] += 1
    d = os.path.join(BASE, f"{prefix}{_n[0]}")
    os.makedirs(d)
    return d


def make_owner(config_bytes, name=None):
    """本人のフォルダの作り物。config.json は渡したバイト列をそのまま置く。"""
    root = new_dir(name or "owner")
    os.makedirs(os.path.join(root, "設定"))
    os.makedirs(os.path.join(root, "00_タスク管理", "data"))
    with open(os.path.join(root, "00_タスク管理", "data", "tasks.json"), "w", encoding="utf-8") as f:
        f.write("{}")
    if config_bytes is not None:
        with open(cfg_path(root), "wb") as f:
            f.write(config_bytes)
    return root


def cfg_path(root):
    return os.path.join(root, "設定", "config.json")


def read_bytes(root):
    with open(cfg_path(root), "rb") as f:
        return f.read()


def read_cfg(root):
    t = read_bytes(root).decode("utf-8")
    return json.loads(t[1:] if t.startswith("﻿") else t)


def env_for(root, **extra):
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "AI_BUNSHIN_AUTO_RUN", "AI_BUNSHIN_HOME")}
    if root is not None:
        env["AI_BUNSHIN_HOME"] = root
    env.update(extra)
    return env


def run(root, *args, **extra):
    """(終了コード, 標準出力, 標準エラー)。カレントも一時フォルダにする（本物のフォルダを探しに行かせない）。"""
    cwd = root if root is not None and os.path.isdir(root) else BASE
    r = subprocess.run([sys.executable, SET_DISPLAY, *args], capture_output=True, text=True, encoding="utf-8",
                       env=env_for(root, **extra), cwd=cwd, timeout=60)
    return r.returncode, r.stdout, r.stderr


def kata_line(out):
    """出力の中の「[見せ方：…]」の行（1行だけであること）。"""
    found = [l for l in out.split("\n") if l.startswith("[見せ方：")]
    assert len(found) == 1, f"「[見せ方：…]」の行が{len(found)}行：{out!r}"
    return found[0]


def tmp_files(root):
    found = []
    for d, _, files in os.walk(root):
        found += [os.path.join(d, f) for f in files if f.endswith(".tmp")]
    return found


def standard_cfg():
    """雛形（templates/config/config.json）に近い、いろいろな値の入った config。maintainer は末尾。"""
    return {
        "owner": "坂田", "owner_call": "坂田さん", "ai_name": "デイビットはるか",
        "departments": ["HR事業部", "技術開発部"],
        "work_hours": {"start": "09:00", "end": "18:00"},
        "schedule": {"plan": "09:00", "review": "17:00"},
        "path": "/usr/local/bin:/usr/bin",
        "ng_allow": ["^git push origin (?!main)", "ひらがな\\\\d+"],
        "dev": {"default_mode": "local", "projects": [{"name": "X", "ratio": 0.5, "n": 10 ** 12}]},
        "design": {"systems": []},
        "team": {"max": 7, "off": [], "joined": {"a": None, "b": True}},
        "maintainer": True,
    }


def dump(cfg, indent=2, ensure_ascii=False, crlf=False, bom=False, tail="\n"):
    body = json.dumps(cfg, ensure_ascii=ensure_ascii, indent=indent)
    if crlf:
        body = body.replace("\n", "\r\n")
        tail = tail.replace("\n", "\r\n")
    return (("﻿" if bom else "") + body + tail).encode("utf-8")


def guard_view():
    spec = importlib.util.spec_from_file_location("ng_guard_for_set_display_test", NG_GUARD)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def import_set_display():
    spec = importlib.util.spec_from_file_location("set_display_inproc", SET_DISPLAY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def without_display(cfg):
    return [(k, v) for k, v in cfg.items() if k != "display"]


# ---------------------------------------------------------------- ほかのキーを変えない（P4）

@case
def t01_other_keys_unchanged_and_guard_view_same():
    ng = guard_view()
    for maint in (True, False):
        cfg = standard_cfg()
        cfg["maintainer"] = maint
        root = make_owner(dump(cfg))
        before_raw = read_bytes(root)
        before = read_cfg(root)
        for args in (("type", "simple"), ("override", "terms", "full"), ("override", "requests_max", "7"),
                     ("type", "full"), ("reset-overrides",)):
            rc, out, err = run(root, *args)
            assert rc == 0, (args, rc, err)
            after = read_cfg(root)
            assert without_display(after) == without_display(before), f"{args}：display 以外が変わった"
            raw = read_bytes(root)
            # 見張りの目（ng_allow と maintainer）でも同じ
            assert ng._limit_keys(ng._parse_config_bytes(raw)) == ng._limit_keys(ng._parse_config_bytes(before_raw)), \
                f"{args}：見張りの見え方（ng_allow・maintainer）が変わった"
        assert not tmp_files(root)


@case
def t02_only_display_lines_differ_in_standard_layout():
    cfg = standard_cfg()
    root = make_owner(dump(cfg))
    before = read_bytes(root).decode("utf-8").split("\n")
    rc, out, err = run(root, "type", "simple")
    assert rc == 0, err
    rc, out, err = run(root, "override", "terms", "full")
    assert rc == 0, err
    after = read_bytes(root).decode("utf-8").split("\n")
    i = after.index('  "display": {')
    j = i
    while after[j] != "  },":
        j += 1
    assert after[:i] + after[j + 1:] == before, "display の行を除くと、元と同じ行が並んでいない"
    assert after[j + 1] == '  "maintainer": true', "display は maintainer の前に入る（雛形と同じ）"


# ---------------------------------------------------------------- 書き方を守る

@case
def t03_formatting_preserved():
    ng = None  # noqa: F841
    variants = {
        "bom_crlf": dict(bom=True, crlf=True),
        "crlf": dict(crlf=True),
        "bom": dict(bom=True),
        "indent4": dict(indent=4),
        "tab": dict(indent="\t"),
        "no_trailing_newline": dict(tail=""),
        "two_trailing_newlines": dict(tail="\n\n"),
        "ascii_escapes": dict(ensure_ascii=True),
    }
    for label, kw in variants.items():
        cfg = standard_cfg()
        root = make_owner(dump(cfg, **kw))
        rc, out, err = run(root, "type", "simple")
        assert rc == 0, (label, err)
        expected = dict(cfg)
        new = {}
        for k, v in expected.items():
            if k == "maintainer":
                new["display"] = {"type": "simple", "overrides": {}}
            new[k] = v
        assert read_bytes(root) == dump(new, **kw), f"{label}：書き方が元と変わった\n{read_bytes(root)[:200]!r}"
        assert not tmp_files(root)


@case
def t04_compact_one_line_kept_one_line():
    cfg = {"owner": "坂田", "ng_allow": [], "maintainer": False}
    raw = json.dumps(cfg, ensure_ascii=False).encode("utf-8")
    root = make_owner(raw)
    rc, out, err = run(root, "type", "simple")
    assert rc == 0, err
    got = read_bytes(root)
    assert b"\n" not in got, got
    assert json.loads(got)["display"] == {"type": "simple", "overrides": {}}
    assert without_display(json.loads(got)) == list(cfg.items())


@case
def t05_key_order_and_display_position():
    # display が無く maintainer も無い → 末尾。すでに display が真ん中にある → その位置のまま
    cfg = {"z": 1, "a": 2, "m": {"k": [3, 2, 1]}}
    root = make_owner(dump(cfg))
    run(root, "type", "simple")
    assert list(read_cfg(root).keys()) == ["z", "a", "m", "display"]
    cfg2 = {"z": 1, "display": {"type": "full", "overrides": {}}, "a": 2, "maintainer": False}
    root = make_owner(dump(cfg2))
    run(root, "type", "simple")
    assert list(read_cfg(root).keys()) == ["z", "display", "a", "maintainer"]


@case
def t06_file_mode_kept():
    root = make_owner(dump(standard_cfg()))
    os.chmod(cfg_path(root), 0o600)
    rc, out, err = run(root, "type", "simple")
    assert rc == 0, err
    assert stat.S_IMODE(os.stat(cfg_path(root)).st_mode) == 0o600


@case
def t07_symlink_inside_folder_target_written_link_kept():
    root = make_owner(None)
    real = os.path.join(root, "設定", "real_config.json")
    with open(real, "wb") as f:
        f.write(dump(standard_cfg()))
    os.symlink(real, cfg_path(root))
    rc, out, err = run(root, "type", "simple")
    assert rc == 0, err
    assert os.path.islink(cfg_path(root)), "リンクが普通のファイルに置き換わった"
    assert json.loads(open(real, encoding="utf-8").read())["display"]["type"] == "simple"


@case
def t07b_symlink_pointing_outside_folder_not_written():
    # K9：リンクの先が本人のフォルダの外なら書かない。外のファイルも、リンクも、変えない
    root = make_owner(None)
    outside = os.path.join(new_dir("outside"), "real_config.json")
    raw = dump(standard_cfg())
    with open(outside, "wb") as f:
        f.write(raw)
    os.symlink(outside, cfg_path(root))
    for args in (("type", "simple"), ("override", "terms", "full")):
        rc, out, err = run(root, *args)
        assert rc == 1 and "リンク" in err and "外" in err and "Traceback" not in err, (args, rc, err)
        assert "[見せ方：" not in out, out
        assert open(outside, "rb").read() == raw, "リンクの先（本人のフォルダの外）を書き換えた"
        assert os.path.islink(cfg_path(root)) and os.path.realpath(cfg_path(root)) == os.path.realpath(outside)
    assert not tmp_files(os.path.dirname(outside)) and not tmp_files(root)
    rc, out, err = run(root, "show")   # 読むだけなら使える
    assert rc == 0, err


# ---------------------------------------------------------------- 型の切り替えと overrides（P6）

@case
def t08_overrides_survive_switch():
    root = make_owner(dump(standard_cfg()))
    for args in (("type", "simple"), ("override", "terms", "full"), ("override", "requests_max", "5")):
        assert run(root, *args)[0] == 0
    want = {"terms": "full", "requests_max": 5}
    assert read_cfg(root)["display"] == {"type": "simple", "overrides": want}
    assert run(root, "type", "full")[0] == 0
    assert read_cfg(root)["display"] == {"type": "full", "overrides": want}
    assert run(root, "type", "simple")[0] == 0
    assert read_cfg(root)["display"] == {"type": "simple", "overrides": want}
    assert isinstance(read_cfg(root)["display"]["overrides"]["requests_max"], int), "requests_max は数で書く"


@case
def t09_reset_overrides_only_on_request():
    root = make_owner(dump(standard_cfg()))
    run(root, "type", "simple")
    run(root, "override", "review_view", "full")
    run(root, "override", "team_view", "full")
    run(root, "type", "full")
    run(root, "override", "team_view", "simple")   # 値を上書きしても、ほかは残る
    assert read_cfg(root)["display"]["overrides"] == {"review_view": "full", "team_view": "simple"}
    rc, out, err = run(root, "reset-overrides")
    assert rc == 0, err
    assert read_cfg(root)["display"] == {"type": "full", "overrides": {}}, "型は変えず、個別の設定だけ空に"
    assert kata_line(out) == FULL_LINE


@case
def t10_noop_does_not_write():
    root = make_owner(dump(standard_cfg()))
    run(root, "type", "simple")
    before, m = read_bytes(root), os.stat(cfg_path(root)).st_mtime_ns
    for args in (("type", "simple"), ("reset-overrides",)):
        rc, out, err = run(root, *args)
        assert rc == 0 and "すでに" in out and kata_line(out) == SIMPLE_LINE, (args, out, err)
    assert read_bytes(root) == before and os.stat(cfg_path(root)).st_mtime_ns == m, "変更が無いのに書き換えた"


# ---------------------------------------------------------------- 知らない名前・値は書かない（P11・U14）

@case
def t11_unknown_names_and_values_not_written():
    root = make_owner(dump(standard_cfg()))
    before = read_bytes(root)
    bad = [("override", "ng_guard", "off"), ("override", "ng_allow", "full"), ("override", "maintainer", "full"),
           ("override", "Terms", "full"), ("override", "auto", "full"), ("override", "", "full"),
           ("override", "terms", "off"), ("override", "terms", "Full"), ("override", "terms", "FULL"),
           ("override", "terms", "5"), ("override", "terms", ""), ("override", "terms", " full"),
           ("override", "terms", "true"), ("override", "features", "none"),
           ("type", "simpel"), ("type", "Simple"), ("type", "シンプル"), ("type", ""), ("type", "off")]
    for args in bad:
        rc, out, err = run(root, *args)
        assert rc == 2, (args, rc, out, err)
        assert "何も書き換えていません" in err, (args, err)
        assert read_bytes(root) == before, f"{args}：書き換えてしまった"
    assert not tmp_files(root)


@case
def t12_requests_max_only_1_to_20_integers():
    root = make_owner(dump(standard_cfg()))
    for ok in ("1", "5", "20", "05"):
        assert run(root, "override", "requests_max", ok)[0] == 0, ok
        assert read_cfg(root)["display"]["overrides"]["requests_max"] == int(ok)
    keep = read_bytes(root)
    for bad in ("0", "21", "100", "999", "-1", "5.0", "1e1", "abc", "", " 5", "5 ", "０５", "１０", "0x5", "True", "true",
                "simple", "full", "1000", "+5", "5\n"):
        rc, out, err = run(root, "override", "requests_max", bad)
        assert rc == 2, (bad, rc, out)
        assert read_bytes(root) == keep, f"{bad!r}：書き換えてしまった"


@case
def t13_usage_errors_exit_2_no_change():
    root = make_owner(dump(standard_cfg()))
    before = read_bytes(root)
    for args in ((), ("hello",), ("type",), ("type", "simple", "extra"), ("show", "extra"), ("override",),
                 ("override", "terms"), ("override", "terms", "full", "x"), ("reset-overrides", "x"), ("--type", "simple"),
                 ("set", "simple")):
        rc, out, err = run(root, *args)
        assert rc == 2 and err.strip(), (args, rc, out, err)
        assert read_bytes(root) == before
    rc, out, err = run(root, "--help")
    assert rc == 0 and "使い方" in out, (rc, out, err)


# ---------------------------------------------------------------- 最後の1行（P12）

@case
def t14_last_line_is_new_state():
    root = make_owner(dump(standard_cfg()))
    cases = [(("type", "simple"), SIMPLE_LINE), (("override", "terms", "full"), SIMPLE_LINE),
             (("override", "requests_max", "5"), SIMPLE_LINE), (("type", "full"), FULL_LINE),
             (("reset-overrides",), FULL_LINE), (("type", "simple"), SIMPLE_LINE), (("type", "simple"), SIMPLE_LINE),
             (("show",), SIMPLE_LINE), (("type", "full"), FULL_LINE)]
    for args, want in cases:
        rc, out, err = run(root, *args)
        assert rc == 0, (args, err)
        assert kata_line(out) == want, (args, out)
    # 個別の設定があるときは、「[見せ方：…]」の次の行に出す（K11）。個別の設定が無いときは「[見せ方：…]」が最後の行
    run(root, "override", "terms", "full")
    rc, out, err = run(root, "override", "requests_max", "5")
    lines = out.rstrip("\n").split("\n")
    assert lines[-2] == FULL_LINE and lines[-1] == "個別の設定（型より優先）：terms=full、requests_max=5", out
    rc, out, err = run(root, "show")
    lines = out.rstrip("\n").split("\n")
    assert lines[-2] == FULL_LINE and lines[-1] == "個別の設定（型より優先）：terms=full、requests_max=5", out
    rc, out, err = run(root, "reset-overrides")
    assert out.rstrip("\n").split("\n")[-1] == FULL_LINE and "個別の設定（型より優先）" not in out, out


@case
def t15_line_text_matches_design_example():
    assert SIMPLE_LINE == "[見せ方：シンプル（言葉・件数の決まりを守る）]"   # 設計 U11 の例の文
    m = import_set_display()
    assert m.display_line("simple") == SIMPLE_LINE and m.display_line("full") == FULL_LINE
    assert m.display_line("full", broken=True) == BROKEN_LINE
    assert m.TYPE_LINE == {"simple": SIMPLE_LINE, "full": FULL_LINE} and m.BROKEN_LINE == BROKEN_LINE


# ---------------------------------------------------------------- display が無い・壊れている（P8）

@case
def t16_missing_display_created_before_maintainer():
    cfg = standard_cfg()
    assert "display" not in cfg
    root = make_owner(dump(cfg))
    rc, out, err = run(root, "show")
    assert rc == 0 and kata_line(out) == FULL_LINE and "未設定" in out, out
    assert read_bytes(root) == dump(cfg), "show は書かない"
    rc, out, err = run(root, "type", "full")
    assert rc == 0 and kata_line(out) == FULL_LINE, (out, err)
    got = read_cfg(root)
    assert got["display"] == {"type": "full", "overrides": {}}
    keys = list(got)
    assert keys.index("display") == keys.index("maintainer") - 1


@case
def t17_override_without_display_adds_explicit_full():
    root = make_owner(dump(standard_cfg()))
    rc, out, err = run(root, "override", "terms", "full")
    assert rc == 0, err
    assert read_cfg(root)["display"] == {"type": "full", "overrides": {"terms": "full"}}


@case
def t18_broken_display_values():
    # display が文字列・リスト → 辞書に直して書く（display は set_display が持つキー）
    for bad in ('"simple"', '["simple"]', '5', 'null'):
        raw = ('{\n  "owner": "x",\n  "display": ' + bad + ',\n  "maintainer": false\n}\n').encode()
        root = make_owner(raw)
        rc, out, err = run(root, "type", "simple")
        assert rc == 0, (bad, err)
        got = read_cfg(root)
        assert got["display"] == {"type": "simple", "overrides": {}} and got["owner"] == "x" and got["maintainer"] is False, (bad, got)
        assert kata_line(out) == SIMPLE_LINE
    # overrides がリスト → 空の辞書にして書く
    root = make_owner(b'{"display": {"type": "simple", "overrides": ["terms"]}}\n')
    assert run(root, "override", "terms", "full")[0] == 0
    assert read_cfg(root)["display"] == {"type": "simple", "overrides": {"terms": "full"}}


@case
def t19_broken_type_kept_with_notice_until_fixed():
    root = make_owner(b'{"display": {"type": "simpel", "overrides": {"terms": "full"}}}\n')
    rc, out, err = run(root, "show")
    assert rc == 0 and kata_line(out) == BROKEN_LINE and "simple か full ではない" in out, out
    rc, out, err = run(root, "override", "features", "simple")
    assert rc == 0 and kata_line(out) == BROKEN_LINE, out
    assert read_cfg(root)["display"]["type"] == "simpel", "type を黙って直さない"
    assert read_cfg(root)["display"]["overrides"] == {"terms": "full", "features": "simple"}
    rc, out, err = run(root, "type", "simple")
    assert rc == 0 and kata_line(out) == SIMPLE_LINE, out
    assert read_cfg(root)["display"]["overrides"] == {"terms": "full", "features": "simple"}, "直しても個別の設定は残る"


@case
def t20_unknown_entries_kept_but_not_used():
    raw = dump({"display": {"type": "simple", "overrides": {"ng_guard": "off", "terms": "maybe", "team_view": "full"},
                            "memo": "残す"}})
    root = make_owner(raw)
    rc, out, err = run(root, "show")
    assert rc == 0 and "ng_guard" in out and "無視" in out, out
    assert "team_view | full" in out and "terms | 範囲外のためフル" in out, out
    assert "ng_guard" not in out.split("| 項目")[1].split("注意")[0], "知らない名前は表に出さない（注意の行にだけ）"
    rc, out, err = run(root, "override", "requests_max", "4")
    assert rc == 0, err
    d = read_cfg(root)["display"]
    assert d["memo"] == "残す" and d["overrides"]["ng_guard"] == "off" and d["overrides"]["terms"] == "maybe", \
        "決まりにないものを黙って消さない"
    assert "個別の設定（型より優先）：requests_max=4、team_view=full" in out, out


# ---------------------------------------------------------------- 壊れた config は書き換えない

@case
def t21_broken_config_not_touched():
    broken = {
        "invalid_json": b'{"owner": "x",}\n',
        "truncated": b'{"owner": "x"',
        "empty": b"",
        "spaces_only": b"  \n",
        "list_top": b'["a"]\n',
        "string_top": b'"x"\n',
        "null_top": b"null\n",
        "not_utf8": b'{"owner": "\x83e\x83X\x83g"}\n',
        "double_bom": b'\xef\xbb\xbf\xef\xbb\xbf{"owner": "x"}\n',
    }
    for label, raw in broken.items():
        root = make_owner(raw)
        for args in (("type", "simple"), ("show",), ("override", "terms", "full"), ("reset-overrides",)):
            rc, out, err = run(root, *args)
            assert rc == 1, (label, args, rc, out, err)
            assert re.search(r"[ぁ-んァ-ン一-龥]", err) and "書き換えて" in err, (label, args, err)
            assert "Traceback" not in err, (label, err)
            assert read_bytes(root) == raw, f"{label}：壊れたファイルを書き換えた"
        assert not tmp_files(root)


@case
def t22_missing_config_not_created():
    root = make_owner(None)
    rc, out, err = run(root, "type", "simple")
    assert rc == 1 and "config.json" in err and "Traceback" not in err, (rc, err)
    assert not os.path.exists(cfg_path(root)), "config.json を新しく作った"


@case
def t23_no_fallback_to_other_folders():
    # AI_BUNSHIN_HOME が本人のフォルダでないとき、cwd や CLAUDE_PROJECT_DIR の本人のフォルダを探しに行かない
    other = make_owner(dump(standard_cfg()))
    before = read_bytes(other)
    empty = new_dir("empty")
    r = subprocess.run([sys.executable, SET_DISPLAY, "type", "simple"], capture_output=True, text=True, encoding="utf-8",
                       env=env_for(empty, CLAUDE_PROJECT_DIR=other), cwd=other, timeout=60)
    assert r.returncode == 1 and "見つかりません" in r.stderr, (r.returncode, r.stderr)
    assert read_bytes(other) == before and os.listdir(empty) == []
    # AI_BUNSHIN_HOME が無いときは、カレントから上へ探す（update_dashboard.py と同じ）
    sub = os.path.join(other, "02_成果物", "x")
    os.makedirs(sub)
    r = subprocess.run([sys.executable, SET_DISPLAY, "type", "simple"], capture_output=True, text=True, encoding="utf-8",
                       env=env_for(None), cwd=sub, timeout=60)
    assert r.returncode == 0, r.stderr
    assert read_cfg(other)["display"]["type"] == "simple"


# ---------------------------------------------------------------- 自動実行では切り替えない（P4）

@case
def t24_refuses_in_auto_run_but_show_works():
    root = make_owner(dump(standard_cfg()))
    before = read_bytes(root)
    for args in (("type", "simple"), ("override", "terms", "full"), ("reset-overrides",)):
        rc, out, err = run(root, *args, AI_BUNSHIN_AUTO_RUN="20261107-0900")
        assert rc == 1 and "自動実行" in err, (args, rc, err)
        assert read_bytes(root) == before
    rc, out, err = run(root, "show", AI_BUNSHIN_AUTO_RUN="20261107-0900")
    assert rc == 0 and kata_line(out) == FULL_LINE, (rc, out, err)


@case
def t25_auto_run_cannot_reach_script():
    # 自動実行（daily_cycle.sh）：設定/ への Edit は deny、Bash は update_dashboard.py・lock_check.py だけ
    text = open(CYCLE, encoding="utf-8").read()
    tools = re.search(r'^TOOLS="(.*)"$', text, re.M).group(1)
    deny = re.search(r'^DENY="(.*)"$', text, re.M).group(1)
    assert "Edit(設定/**)" in deny.split(","), deny
    assert "set_display" not in tools and "set_display" not in deny
    cmd = f"python3 {SET_DISPLAY} type simple"
    for pat in re.findall(r"Bash\((.*?)\)(?:,|$)", tools):
        glob = pat[:-2] if pat.endswith(":*") else pat
        glob = glob.replace('\\"', '"').replace("$DASH", "*update_dashboard.py")
        assert not fnmatch.fnmatchcase(cmd, glob), f"自動実行の道具 Bash({pat}) が set_display.py の呼び出しに当たる"


# ---------------------------------------------------------------- 書き込みの安全

@case
def t26_failed_replace_keeps_original():
    root = make_owner(dump(standard_cfg()))
    before = read_bytes(root)
    m = import_set_display()
    real_replace = os.replace

    def boom(*a, **k):
        raise OSError("置き換えられない（テスト）")

    old_env = os.environ.get("AI_BUNSHIN_HOME")
    os.environ["AI_BUNSHIN_HOME"] = root
    os.replace = boom
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = m.main(["type", "simple"])
    finally:
        os.replace = real_replace
        if old_env is None:
            os.environ.pop("AI_BUNSHIN_HOME", None)
        else:
            os.environ["AI_BUNSHIN_HOME"] = old_env
    assert rc == 1 and "元のファイルはそのまま" in err.getvalue(), (rc, err.getvalue())
    assert read_bytes(root) == before and not tmp_files(root), "途中で失敗したのに、元のファイルが変わった・一時ファイルが残った"
    assert "[見せ方：" not in out.getvalue(), "書けていないのに新しい型の行を出した"


@case
def t27_changed_by_others_while_writing_is_not_overwritten():
    root = make_owner(dump(standard_cfg()))
    m = import_set_display()
    real_fsync = os.fsync
    other_bytes = dump({**standard_cfg(), "owner": "ほかの人が書いた"})

    def fsync_and_interfere(fd):
        real_fsync(fd)
        with open(cfg_path(root), "wb") as f:   # 書いている間に、ほかが config を書き換える
            f.write(other_bytes)

    old_env = os.environ.get("AI_BUNSHIN_HOME")
    os.environ["AI_BUNSHIN_HOME"] = root
    os.fsync = fsync_and_interfere
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = m.main(["type", "simple"])
    finally:
        os.fsync = real_fsync
        if old_env is None:
            os.environ.pop("AI_BUNSHIN_HOME", None)
        else:
            os.environ["AI_BUNSHIN_HOME"] = old_env
    assert rc == 1 and "ほかで書き換えられました" in err.getvalue(), (rc, err.getvalue())
    assert read_bytes(root) == other_bytes and not tmp_files(root), "ほかの人の書き込みを上書きした・一時ファイルが残った"


@case
def t28_show_is_read_only():
    root = make_owner(dump(standard_cfg()))
    run(root, "type", "simple")
    run(root, "override", "terms", "full")
    before, m = read_bytes(root), os.stat(cfg_path(root)).st_mtime_ns
    rc, out, err = run(root, "show")
    assert rc == 0, err
    for name in ("features", "terms", "requests_max", "stop_notice", "review_view", "team_view"):
        assert f"| {name} |" in out, name
    assert "| terms | full |" in out and "| features | 型どおり |" in out, out
    assert read_bytes(root) == before and os.stat(cfg_path(root)).st_mtime_ns == m
    assert not tmp_files(root)


# ---------------------------------------------------------------- P1：display を読む所

@case
def t29_p1_only_two_scripts_read_display():
    key_read = re.compile(r"""["']display["']""")
    hits = []
    allowed = {"set_display.py", "update_dashboard.py"}
    targets = []
    for d, dirs, files in os.walk(SCRIPTS):
        dirs[:] = [x for x in dirs if x != "__pycache__"]
        for f in files:
            if ".bak" in f or f.endswith(".pyc") or f in allowed:
                continue
            targets.append(os.path.join(d, f))
    targets += [os.path.join(PLUGIN, "hooks", "hooks.json"), os.path.join(PLUGIN, "templates", ".claude", "settings.json")]
    assert len(targets) >= 8, f"調べる対象が少なすぎる：{len(targets)}"
    for p in targets:
        try:
            text = open(p, encoding="utf-8").read()
        except UnicodeDecodeError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if key_read.search(line):
                hits.append(f"{os.path.relpath(p, PLUGIN)}:{n}")
    assert not hits, "display を読む所がほかにある：" + "、".join(hits)


@case
def t30_set_display_imports_no_other_scripts():
    src = open(SET_DISPLAY, encoding="utf-8").read()
    bad = re.findall(r"^\s*(?:import|from)\s+(update_dashboard|ng_guard\w*|lock_check|watch_check|setup_settings|calendar_today)\b", src, re.M)
    assert not bad, f"ほかのスクリプトを読み込んでいる（U02・K3）：{bad}"


@case
def t31_writes_only_config_json():
    # 実行の前後で、config.json 以外のファイル（tasks.json など）が増えも変わりもしない
    root = make_owner(dump(standard_cfg()))
    snap = lambda: sorted((os.path.relpath(os.path.join(d, f), root), open(os.path.join(d, f), "rb").read())  # noqa: E731
                          for d, _, fs in os.walk(root) for f in fs if f != "config.json")
    before = snap()
    for args in (("type", "simple"), ("override", "terms", "full"), ("reset-overrides",), ("show",)):
        assert run(root, *args)[0] == 0
    assert snap() == before


# ---------------------------------------------------------------- K8・X4：読む側（update_dashboard.py）と同じ見え方

def import_dashboard():
    """update_dashboard.py を、一時の本人のフォルダを指して読み込む（読むだけ。本物のフォルダは見ない）。"""
    root = make_owner(dump({"owner": "テスト", "owner_call": "テストさん", "ai_name": "テストAI", "departments": ["総務"]}))
    old = {k: os.environ.get(k) for k in ("AI_BUNSHIN_HOME", "CLAUDE_PROJECT_DIR")}
    os.environ["AI_BUNSHIN_HOME"] = root
    os.environ.pop("CLAUDE_PROJECT_DIR", None)
    try:
        spec = importlib.util.spec_from_file_location("update_dashboard_for_set_display_test",
                                                      os.path.join(SCRIPTS, "update_dashboard.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return m


DISPLAY_SAMPLES = [
    ("display が無い", None),
    ("空の辞書", {}),
    ("空の文字列", ""),
    ("空のリスト", []),
    ("数（0）", 0),
    ("文字列", "simple"),
    ("type だけ（simple）", {"type": "simple"}),
    ("type full・overrides 空", {"type": "full", "overrides": {}}),
    ("壊れた type（綴り）", {"type": "simpel"}),
    ("壊れた type（数）", {"type": 7}),
    ("壊れた type と overrides（読まない）", {"type": "simpel", "overrides": {"terms": "full"}}),
    ("type が無く overrides だけ", {"overrides": {"terms": "full"}}),
    ("requests_max が範囲外（99）", {"type": "simple", "overrides": {"requests_max": 99}}),
    ("requests_max が 0", {"type": "simple", "overrides": {"requests_max": 0}}),
    ("requests_max が文字の数字", {"type": "simple", "overrides": {"requests_max": "5"}}),
    ("requests_max が True", {"type": "simple", "overrides": {"requests_max": True}}),
    ("requests_max が 5.0", {"type": "simple", "overrides": {"requests_max": 5.0}}),
    ("知らない名前", {"type": "simple", "overrides": {"ng_guard": "off", "terms": "full"}}),
    ("決まった名前で知らない値", {"type": "simple", "overrides": {"terms": "maybe", "features": 1, "team_view": "full"}}),
    ("overrides がリスト", {"type": "simple", "overrides": ["terms"]}),
    ("全部有効（順番ばらばら）", {"type": "full", "overrides": {"team_view": "simple", "requests_max": 20, "features": "full",
                                                      "review_view": "simple", "terms": "full", "stop_notice": "simple"}}),
]


@case
def t32_view_matches_update_dashboard_read_display():
    ud, sd = import_dashboard(), import_set_display()
    for label, v in DISPLAY_SAMPLES:
        r = ud.read_display({} if v is None else {"display": v})
        typ, ov, notes, broken, invalid = sd.effective(v)
        assert typ == r["type"], f"{label}：型が違う {typ} / {r['type']}"
        assert ov == r["overrides"], f"{label}：効く個別の設定が違う {ov} / {r['overrides']}"
        assert invalid == r["invalid"], f"{label}：範囲外の項目が違う {invalid} / {r['invalid']}"
        assert broken == (r["line"] == ud.DISPLAY_BROKEN_LINE), f"{label}：壊れ判定が違う"
        if broken or r["line"]:
            assert sd.display_line(typ, broken) == r["line"], f"{label}：「[見せ方：…]」の文面が違う"
        else:
            assert typ == "full", f"{label}：起動時は無言（フル）なのに型が full でない"
        # X4：個別の設定の行が1文字も違わない
        assert sd.overrides_line(ov) == ud.overrides_line(r), f"{label}：個別の設定の行が違う"


@case
def t33_same_text_constants_as_update_dashboard():
    ud, sd = import_dashboard(), import_set_display()
    assert sd.TYPE_LINE == ud.DISPLAY_LINE and sd.BROKEN_LINE == ud.DISPLAY_BROKEN_LINE
    assert tuple(sd.OVERRIDE_NAMES) == tuple(ud.DISPLAY_OVERRIDE_NAMES) and tuple(sd.TYPES) == tuple(ud.DISPLAY_TYPES)
    assert tuple(sd.REQUESTS_RANGE) == tuple(ud.REQUESTS_MAX_RANGE)


@case
def t34_show_table_says_out_of_range_means_full():
    # K8：読む側が「その項目はフル」と扱う値は、表でも「範囲外のためフル」
    for ov in ({"requests_max": 99}, {"requests_max": "5"}, {"requests_max": 0}, {"requests_max": True}, {"terms": "maybe"}):
        name = next(iter(ov))
        root = make_owner(dump({"display": {"type": "simple", "overrides": dict(ov, team_view="full")}}))
        rc, out, err = run(root, "show")
        assert rc == 0, err
        assert f"| {name} | 範囲外のためフル |" in out, (ov, out)
        assert "| team_view | full |" in out and "個別の設定（型より優先）：team_view=full" in out, out
        assert f"{name}=" not in out.split("[見せ方：")[1], f"{ov}：効かない値を、効く個別の設定の行に出している"
    # 有効な値と、値を書いていない項目は今までどおり
    root = make_owner(dump({"display": {"type": "simple", "overrides": {"requests_max": 20}}}))
    out = run(root, "show")[1]
    assert "| requests_max | 20 |" in out and "| terms | 型どおり |" in out and "範囲外" not in out, out


@case
def t35_show_notes_missing_type():
    # X2：type が無く overrides だけのとき、「[見せ方：…]」の前に「type 未設定（フル）」と注記する
    root = make_owner(dump({"display": {"overrides": {"terms": "full"}}}))
    rc, out, err = run(root, "show")
    assert rc == 0, err
    assert out.index("type 未設定（フル）") < out.index(FULL_LINE), out
    assert kata_line(out) == FULL_LINE and out.rstrip("\n").split("\n")[-1] == "個別の設定（型より優先）：terms=full", out
    # type が書いてあるとき・display が無いときは、この注記を出さない
    for v in ({"display": {"type": "simple"}}, {}, {"display": {}}):
        out = run(make_owner(dump(v)), "show")[1]
        assert "type 未設定" not in out, (v, out)


shutil.rmtree(BASE, ignore_errors=True)
print(f"\n失敗 {fails} 件")
sys.exit(1 if fails else 0)
