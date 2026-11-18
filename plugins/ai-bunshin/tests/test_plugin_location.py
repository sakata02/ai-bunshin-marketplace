"""プラグインの場所の決め方（beta.10。scripts/plugin_location.py）と、install.sh が作る run.sh のテスト。
一時フォルダに偽の ~/.claude（installed_plugins.json・known_marketplaces.json）を作って確かめる。本物の ~/.claude・launchd・claude は使わない。

- L1：マーケットプレイスが directory のとき、元のフォルダ（<path>/plugins/<名前>）が選ばれる（installPath が別でも）
- L2：marketplace.json に source の道があればそれ。github などの source のものと、directory でも元に daily_cycle.sh が無いときは installPath
- L3：JSON が無い・壊れている・形が違うときに落ちない（終了コード0・空）
- L4：本人のフォルダの projectPath で選ぶ（別のフォルダのものは選ばない・projectPath が無い user スコープは選ぶ・実体の道でも一致）
- L5：引数の間違いは終了コード64
- R1：install.sh が作った run.sh が、directory のマーケットプレイスの元のフォルダの daily_cycle.sh を動かす（今までの installPath は使わない）
- R2：JSON が無いときは、install.sh を打った場所（今までどおり）で動く
実行：python3 tests/test_plugin_location.py（失敗があれば終了コード1）"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.abspath(os.path.join(HERE, "..", "scripts"))
LOC = os.environ.get("LOC_UNDER_TEST") or os.path.join(SCRIPTS, "plugin_location.py")
INSTALL = os.environ.get("INSTALL_UNDER_TEST") or os.path.join(SCRIPTS, "auto", "install.sh")
SCRATCH = os.environ.get("AUTO_PATHS_SCRATCH") or tempfile.gettempdir()
BASE = os.path.realpath(tempfile.mkdtemp(prefix="pluginloc_", dir=SCRATCH))
names = []
fails = 0


def case(fn):
    names.append(fn.__name__)
    return fn


def mkplugin(root):
    """daily_cycle.sh のある、プラグインの形のフォルダ"""
    os.makedirs(os.path.join(root, "scripts", "auto"), exist_ok=True)
    open(os.path.join(root, "scripts", "auto", "daily_cycle.sh"), "w").write("#!/bin/zsh\n")
    return root


def fixture(name, installed=None, known=None, marketplace_json=None, raw=None):
    """偽の ~/.claude を作る。raw は {ファイル名: 中身の文字列}（壊れた JSON を置く）"""
    d = os.path.join(BASE, name)
    cdir = os.path.join(d, "claude")
    os.makedirs(os.path.join(cdir, "plugins"))
    if installed is not None:
        json.dump(installed, open(os.path.join(cdir, "plugins", "installed_plugins.json"), "w"))
    if known is not None:
        json.dump(known, open(os.path.join(cdir, "plugins", "known_marketplaces.json"), "w"))
    for fn, body in (raw or {}).items():
        open(os.path.join(cdir, "plugins", fn), "w").write(body)
    return d, cdir


def locate(cdir, home, *extra):
    r = subprocess.run([sys.executable, "-I", LOC, "--home", home, "--claude-dir", cdir, *extra], capture_output=True, text=True)
    lines = r.stdout.split("\n")
    return r.returncode, lines[0], (lines[1] if len(lines) > 1 else ""), r.stderr


def inst(path, project="/home/x", key="ai-bunshin@mk"):
    e = {"scope": "project", "installPath": path, "version": "1"}
    if project is not None:
        e["projectPath"] = project
    return {"version": 2, "plugins": {key: [e]}}


@case
def l1_directory_marketplace_picks_the_source_folder():
    d = os.path.join(BASE, "l1")
    src = mkplugin(os.path.join(d, "mkt", "plugins", "ai-bunshin"))
    cache = mkplugin(os.path.join(d, "cache", "1.0.0-beta.8"))
    _, cdir = fixture("l1c", inst(cache, "/home/x"), {"mk": {"source": {"source": "directory", "path": os.path.join(d, "mkt")}}})
    rc, path, kind, err = locate(cdir, "/home/x")
    assert (rc, path, kind) == (0, src, "directory-marketplace"), (rc, path, kind, err)


@case
def l2_marketplace_json_source_and_fallbacks_to_install_path():
    d = os.path.join(BASE, "l2")
    cache = mkplugin(os.path.join(d, "cache"))
    known = {"mk": {"source": {"source": "directory", "path": os.path.join(d, "mkt")}}}
    # marketplace.json に source の道がある（plugins/ の下ではない名前）
    other = mkplugin(os.path.join(d, "mkt", "src", "bunshin"))
    os.makedirs(os.path.join(d, "mkt", ".claude-plugin"))
    json.dump({"plugins": [{"name": "ai-bunshin", "source": "./src/bunshin"}]}, open(os.path.join(d, "mkt", ".claude-plugin", "marketplace.json"), "w"))
    _, cdir = fixture("l2a", inst(cache), known)
    assert locate(cdir, "/home/x")[1:3] == (other, "directory-marketplace"), locate(cdir, "/home/x")
    # source が github などの辞書（元のフォルダの中ではない）→ installPath
    json.dump({"plugins": [{"name": "ai-bunshin", "source": {"source": "github", "repo": "a/b"}}]}, open(os.path.join(d, "mkt", ".claude-plugin", "marketplace.json"), "w"))
    assert locate(cdir, "/home/x")[1:3] == (cache, "install-path"), locate(cdir, "/home/x")
    # マーケットプレイスが github → installPath
    _, cdir2 = fixture("l2b", inst(cache), {"mk": {"source": {"source": "github", "repo": "a/b"}}})
    assert locate(cdir2, "/home/x")[1:3] == (cache, "install-path"), locate(cdir2, "/home/x")
    # directory だが元に daily_cycle.sh が無い → installPath
    os.makedirs(os.path.join(d, "empty", "plugins", "ai-bunshin"))
    _, cdir3 = fixture("l2c", inst(cache), {"mk": {"source": {"source": "directory", "path": os.path.join(d, "empty")}}})
    assert locate(cdir3, "/home/x")[1:3] == (cache, "install-path"), locate(cdir3, "/home/x")
    # known_marketplaces.json に無い → installPath
    _, cdir4 = fixture("l2d", inst(cache), {})
    assert locate(cdir4, "/home/x")[1:3] == (cache, "install-path"), locate(cdir4, "/home/x")
    # installPath にも daily_cycle.sh が無い → 決まらない（空）
    _, cdir5 = fixture("l2e", inst(os.path.join(d, "ない")), {})
    assert locate(cdir5, "/home/x")[1:3] == ("", "none"), locate(cdir5, "/home/x")
    # 壊れた marketplace.json は無いものとして、既定の plugins/<名前> に
    src = mkplugin(os.path.join(d, "mkt2", "plugins", "ai-bunshin"))
    os.makedirs(os.path.join(d, "mkt2", ".claude-plugin"))
    open(os.path.join(d, "mkt2", ".claude-plugin", "marketplace.json"), "w").write("{壊れ")
    _, cdir6 = fixture("l2f", inst(cache), {"mk": {"source": {"source": "directory", "path": os.path.join(d, "mkt2")}}})
    assert locate(cdir6, "/home/x")[1:3] == (src, "directory-marketplace"), locate(cdir6, "/home/x")


@case
def l6_source_outside_the_marketplace_folder_is_not_used():
    """部下D：marketplace.json の source が "../" で元のフォルダの外を指しても、絶対パスでも、外へのリンクでも、使わず installPath に落とす。中に収まる "../" 入りの道は使う"""
    d = os.path.join(BASE, "l6")
    cache = mkplugin(os.path.join(d, "cache"))
    outside = mkplugin(os.path.join(d, "outside", "ai-bunshin"))   # 元のフォルダの外にある、daily_cycle.sh のあるフォルダ
    base = os.path.join(d, "mkt")
    os.makedirs(os.path.join(base, ".claude-plugin"))
    known = {"mk": {"source": {"source": "directory", "path": base}}}

    def write_src(s):
        json.dump({"plugins": [{"name": "ai-bunshin", "source": s}]}, open(os.path.join(base, ".claude-plugin", "marketplace.json"), "w"))
    for i, s in enumerate(("../outside/ai-bunshin", "./../outside/ai-bunshin", "./a/../../outside/ai-bunshin", outside)):
        write_src(s)
        _, cdir = fixture("l6a%d" % i, inst(cache), known)
        assert locate(cdir, "/home/x")[1:3] == (cache, "install-path"), (s, locate(cdir, "/home/x"))
    # 外を指すリンク（plugins/ai-bunshin → 外）
    os.makedirs(os.path.join(base, "plugins"))
    os.symlink(outside, os.path.join(base, "plugins", "ai-bunshin"))
    os.rename(os.path.join(base, ".claude-plugin", "marketplace.json"), os.path.join(base, ".claude-plugin", "marketplace.json.off"))
    _, cdir = fixture("l6b", inst(cache), known)
    assert locate(cdir, "/home/x")[1:3] == (cache, "install-path"), locate(cdir, "/home/x")
    # 中に収まる（"../" を含んでも）ものは使う
    inner = mkplugin(os.path.join(base, "src", "bunshin"))
    os.rename(os.path.join(base, ".claude-plugin", "marketplace.json.off"), os.path.join(base, ".claude-plugin", "marketplace.json"))
    write_src("./src/x/../bunshin")
    _, cdir = fixture("l6c", inst(cache), known)
    assert locate(cdir, "/home/x")[1:3] == (os.path.normpath(inner), "directory-marketplace"), locate(cdir, "/home/x")


@case
def l3_missing_or_broken_json_never_crashes():
    d = os.path.join(BASE, "l3")
    cache = mkplugin(os.path.join(d, "cache"))
    os.makedirs(os.path.join(d, "none", "plugins"))   # 何も無い
    rc, path, kind, err = locate(os.path.join(d, "none"), "/home/x")
    assert (rc, path, kind) == (0, "", "none"), (rc, path, kind, err)
    rc, path, kind, err = locate(os.path.join(d, "no_such_dir"), "/home/x")
    assert (rc, path, kind) == (0, "", "none"), (rc, path, kind, err)
    for body in ("{壊れた", "", "[]", "null", '{"plugins": 3}', '{"plugins": {"ai-bunshin@mk": "x"}}', '{"plugins": {"ai-bunshin@mk": [3, null]}}'):
        _, cdir = fixture("l3_" + str(abs(hash(body))), raw={"installed_plugins.json": body})
        rc, path, kind, err = locate(cdir, "/home/x")
        assert (rc, path, kind) == (0, "", "none"), (body, rc, path, kind, err)
    # known_marketplaces.json だけ壊れている → installPath
    for body in ("{壊れ", "[]", '{"mk": 3}', '{"mk": {"source": 3}}', '{"mk": {"source": {"source": "directory"}}}', '{"mk": {"source": {"source": "directory", "path": "相対"}}}'):
        _, cdir = fixture("l3k_" + str(abs(hash(body))), inst(cache), raw={"known_marketplaces.json": body})
        assert locate(cdir, "/home/x")[:3] == (0, cache, "install-path"), (body, locate(cdir, "/home/x"))
    # BOM 付きの JSON も読める
    _, cdir = fixture("l3bom")
    open(os.path.join(cdir, "plugins", "installed_plugins.json"), "wb").write(b"\xef\xbb\xbf" + json.dumps(inst(cache)).encode())
    assert locate(cdir, "/home/x")[1:3] == (cache, "install-path")


@case
def l4_picks_by_the_owner_folder_project_path():
    d = os.path.join(BASE, "l4")
    a = mkplugin(os.path.join(d, "a"))
    b = mkplugin(os.path.join(d, "b"))
    u = mkplugin(os.path.join(d, "u"))
    home = os.path.join(d, "owner")
    os.makedirs(home)
    link = os.path.join(d, "owner_link")
    os.symlink(home, link)
    installed = {"version": 2, "plugins": {"ai-bunshin@mk": [
        {"scope": "project", "projectPath": "/somewhere/else", "installPath": a},
        {"scope": "project", "projectPath": home, "installPath": b}]}}
    _, cdir = fixture("l4a", installed, {})
    assert locate(cdir, home)[1:3] == (b, "install-path"), locate(cdir, home)
    assert locate(cdir, link)[1:3] == (b, "install-path"), "リンク経由の本人のフォルダでも一致する"
    assert locate(cdir, "/another/folder")[1:3] == ("", "none"), "別のフォルダのものは選ばない"
    # projectPath が無い（user スコープ）ものは、どの本人のフォルダでも選ぶ
    installed["plugins"]["ai-bunshin@mk"].append({"scope": "user", "installPath": u})
    _, cdir2 = fixture("l4b", installed, {})
    assert locate(cdir2, "/another/folder")[1:3] == (u, "install-path"), locate(cdir2, "/another/folder")
    # 別のプラグイン（ai-bunshin-panel）の項目は選ばない
    _, cdir3 = fixture("l4c", {"version": 2, "plugins": {"ai-bunshin-panel@mk": [{"scope": "project", "projectPath": home, "installPath": a}]}}, {})
    assert locate(cdir3, home)[1:3] == ("", "none"), locate(cdir3, home)


@case
def l5_bad_arguments_exit_64():
    for args in ([], ["--home"], ["--x", "y"]):
        r = subprocess.run([sys.executable, "-I", LOC, *args], capture_output=True, text=True)
        assert r.returncode == 64, (args, r.returncode, r.stderr)


# ---------- install.sh が作る run.sh ----------

STUB_CYCLE = '#!/bin/zsh\necho "ran:${0:A:h:h:h}:$1" >> "$AI_BUNSHIN_HOME/ran.txt"\n'


def install_in(name, cache_json=True):
    """偽のプラグイン2つ（install.sh を打つ場所＝cache、directory のマーケットプレイスの元＝mkt）と偽の HOME を作り、install.sh を動かす。
    launchctl・osascript は作り物（本物の launchd には触らない）。戻り値：(本人のフォルダ, 偽の HOME, 環境変数, cache, mkt)"""
    d = os.path.join(BASE, name)
    cache = os.path.join(d, "cache", "1.0.0-beta.8")
    mkt_plugin = os.path.join(d, "mkt", "plugins", "ai-bunshin")
    for p in (cache, mkt_plugin):
        os.makedirs(os.path.join(p, "scripts", "auto"))
        open(os.path.join(p, "scripts", "auto", "daily_cycle.sh"), "w").write(STUB_CYCLE)
        shutil.copy(LOC, os.path.join(p, "scripts", "plugin_location.py"))
    shutil.copy(INSTALL, os.path.join(cache, "scripts", "auto", "install.sh"))
    home = os.path.join(d, "owner")
    os.makedirs(os.path.join(home, "設定"))
    json.dump({}, open(os.path.join(home, "設定", "config.json"), "w"))
    fake_home = os.path.join(d, "home")
    os.makedirs(os.path.join(fake_home, "Library", "LaunchAgents"))
    os.makedirs(os.path.join(fake_home, ".claude", "plugins"))
    bindir = os.path.join(d, "bin")
    os.makedirs(bindir)
    for n in ("launchctl", "osascript"):
        open(os.path.join(bindir, n), "w").write("#!/bin/sh\nexit 0\n")
        os.chmod(os.path.join(bindir, n), 0o755)
    if cache_json:
        json.dump(inst(cache, home), open(os.path.join(fake_home, ".claude", "plugins", "installed_plugins.json"), "w"))
        json.dump({"mk": {"source": {"source": "directory", "path": os.path.join(d, "mkt")}}}, open(os.path.join(fake_home, ".claude", "plugins", "known_marketplaces.json"), "w"))
    env = {k: v for k, v in os.environ.items() if k not in ("AI_BUNSHIN_AUTO_RUN", "CLAUDE_PROJECT_DIR", "CLAUDE_CONFIG_DIR")}
    env["HOME"] = fake_home
    env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
    r = subprocess.run(["/bin/zsh", os.path.join(cache, "scripts", "auto", "install.sh"), home], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, (r.returncode, r.stdout[-300:], r.stderr[-300:])
    return home, fake_home, env, cache, mkt_plugin


@case
def r1_run_sh_runs_the_cycle_from_the_directory_marketplace():
    home, fake_home, env, cache, mkt_plugin = install_in("r1")
    run_sh = os.path.join(home, "scripts", "auto", "run.sh")
    text = open(run_sh, encoding="utf-8").read()
    assert "plugin_location.py" in text and "json.load" not in text, text[:600]
    r = subprocess.run(["/bin/zsh", run_sh, "plan"], capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, (r.returncode, r.stderr)
    assert open(os.path.join(home, "ran.txt"), encoding="utf-8").read().strip() == f"ran:{mkt_plugin}:plan", open(os.path.join(home, "ran.txt")).read()


@case
def r2_run_sh_falls_back_to_the_install_location_without_json():
    home, fake_home, env, cache, mkt_plugin = install_in("r2", cache_json=False)
    r = subprocess.run(["/bin/zsh", os.path.join(home, "scripts", "auto", "run.sh"), "review"], capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, (r.returncode, r.stderr)
    assert open(os.path.join(home, "ran.txt"), encoding="utf-8").read().strip() == f"ran:{cache}:review"
    # 場所が1つも使えないときは、今までどおり止めて知らせる
    os.rename(os.path.join(cache, "scripts", "auto", "daily_cycle.sh"), os.path.join(cache, "scripts", "auto", "x.sh"))
    r = subprocess.run(["/bin/zsh", os.path.join(home, "scripts", "auto", "run.sh"), "review"], capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 1, r.returncode
    logs = os.path.join(home, "scripts", "auto", "logs")
    assert any("見つかりません" in open(os.path.join(logs, f), encoding="utf-8").read() for f in os.listdir(logs) if f.endswith(".log")), os.listdir(logs)


def main():
    global fails
    g = globals()
    for n in names:
        try:
            g[n]()
            print(f"  ok   {n}")
        except AssertionError as e:
            fails += 1
            print(f"  FAIL {n}: {e}")
        except Exception as e:  # noqa: BLE001
            fails += 1
            print(f"  FAIL {n}: {e.__class__.__name__}: {e}")
    print(f"\n{len(names) - fails}/{len(names)} passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
