"""囲いのカナリア（scripts/sandbox_canary.py）のテスト。T119 G4a・G4c（決定 S05・S06・S15・S16・S20〜S23）。
作り物の本人のフォルダ・ユーザーのホーム・プラグインの元を一時フォルダに作り、本物の sandbox_settings.py で denyWrite を作る。
そのうえで、macOS の sandbox-exec（Claude Code の囲いと同じ seatbelt）で、囲いの効き方を変えながらカナリアを動かす。
キーチェーンは作り物の security（終了コードを返すだけ）。本物の claude・キーチェーン・本物の本人のフォルダは使わない。
カナリアは import で動かす（設定のファイルは prepare で置く。security の場所・確かめ先の差し替えも import でだけ）。
コマンドから動かすのは、引数を受け付けないことと、鍵が出ないことの確かめだけ。

- ①〜⑥（write・parent_mv・case・network・keychain・env_url）のどれか1つが通ったとき、その項目名が結果と判定に出る
- 囲いが全部効いているときだけ、全部 blocked と判定される
- カナリア自身が実物を壊さない（守る先のファイルの中身は変わらず、名前も変わらず、消えず、増えるのは空の目印ファイル最大2つ）
- 結果が無い・形が違う・別の実行のもの・error・skipped は「全部止まった」にならない
- G4c：偽造（印なし・違う鍵・設定の sha256 違い・write の数が下限未満・印のあとの書き換え）は通らない／コマンドの引数（--security-bin など）は受け付けない／鍵が出力・結果・security の環境に出ない
- G4c：network は EPERM・EACCES のときだけ blocked／keychain は名前が無い日は error／parent_mv は守っていない親の付け替えを試す
実行：python3 tests/test_sandbox_canary.py（失敗があれば終了コード1）。CANARY_UNDER_TEST に別の版の sandbox_canary.py を指すと、その版で流せる"""
import errno
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.abspath(os.path.join(HERE, "..", "scripts"))
CANARY = os.environ.get("CANARY_UNDER_TEST") or os.path.join(SCRIPTS, "sandbox_canary.py")
SETTINGS_PY = os.path.join(SCRIPTS, "sandbox_settings.py")
BASE = os.path.realpath(tempfile.mkdtemp(prefix="sbxcanary_"))
SECRET = "KEYCHAINSECRET-5d2f"
KEY = "ab" * 32              # 点検の鍵（64文字の16進）
OTHER_KEY = "cd" * 32

names, fails, skipped = [], 0, []


def case(fn):
    names.append(fn.__name__)
    try:
        fn()
        print(f"  ok   {fn.__name__}")
    except AssertionError as e:
        global fails
        fails += 1
        print(f"  FAIL {fn.__name__}: {e}")
    except Exception as e:  # noqa: BLE001
        fails += 1
        print(f"  FAIL {fn.__name__}: {e.__class__.__name__}: {e}")
    return fn


def load_canary():
    spec = importlib.util.spec_from_file_location("sandbox_canary_under_test", CANARY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


C = load_canary()


def sandbox_exec_works():
    try:
        r = subprocess.run(["sandbox-exec", "-p", "(version 1)(allow default)", "/usr/bin/true"], capture_output=True, timeout=20)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


HAVE_SBX = sandbox_exec_works()

# 受け付けて閉じるだけの待ち受け（囲いが無ければ、ここへの直接の接続は通る）
LISTENER = socket.socket()
LISTENER.bind(("127.0.0.1", 0))
LISTENER.listen(16)
LISTEN_PORT = LISTENER.getsockname()[1]


def _accept_loop():
    while True:
        try:
            c, _ = LISTENER.accept()
            c.close()
        except OSError:
            return


threading.Thread(target=_accept_loop, daemon=True).start()


def fake_security(name, code, out_text=""):
    p = os.path.join(BASE, name)
    open(p, "w").write("#!/bin/sh\n" + ('echo "%s"\n' % out_text if out_text else "") + "exit %d\n" % code)
    os.chmod(p, 0o755)
    return p


SEC_BLOCKED = fake_security("sec_blocked", 44, SECRET)   # 見つからない（出力に秘密らしきものを出しても、結果に出ないことを見る）
SEC_FOUND = fake_security("sec_found", 0, SECRET)


def make_env(name, git_dir=True):
    d = os.path.join(BASE, name)
    home, user, plugin = (os.path.join(d, x) for x in ("owner", "user", "plugin"))
    for sub in (os.path.join(home, "設定"), os.path.join(home, "scripts", "auto"), os.path.join(home, "03_インプット"),
                os.path.join(home, ".claude"), os.path.join(home, "00_タスク管理", "data"),
                os.path.join(user, ".claude", "plugins"), os.path.join(user, "Library", "LaunchAgents"),
                os.path.join(plugin, "scripts")):
        os.makedirs(sub)
    if git_dir:
        os.makedirs(os.path.join(home, ".git", "hooks"))
        open(os.path.join(home, ".git", "config"), "w").write("[core]\n")
    os.makedirs(os.path.join(home, C.MARKER_DIR, C.GUARD_DIR))   # daily_cycle.sh が囲いの外で前もって作る目印フォルダ（親は守らない。守る先は中の guard）
    open(os.path.join(home, "CLAUDE.md"), "w").write("# 本人設定\n")
    open(os.path.join(home, "設定", "config.json"), "w", encoding="utf-8").write("{}")
    open(os.path.join(home, "scripts", "auto", "run.sh"), "w").write("#!/bin/sh\n")
    open(os.path.join(home, "03_インプット", "in.txt"), "w").write("in\n")
    open(os.path.join(user, ".claude", "settings.json"), "w").write("{}")
    open(os.path.join(plugin, "scripts", "x.py"), "w").write("x\n")
    sj = os.path.join(d, "settings.json")
    r = subprocess.run([sys.executable, "-I", SETTINGS_PY, "--home", home, "--plugin-root", plugin, "--user-home", user],
                       capture_output=True, text=True, env={"PATH": os.environ.get("PATH", "")})
    assert r.returncode == 0, r.stderr
    open(sj, "w").write(r.stdout)
    deny = json.loads(r.stdout)["sandbox"]["filesystem"]["denyWrite"]
    return dict(d=d, home=home, user=user, plugin=plugin, settings=sj, deny=deny, out=os.path.join(home, "00_タスク管理", "data", "canary.json"),
                key=KEY, sha=None, minw=None)


def snapshot(e):
    """守る先を含む全体の中身（ファイルの中身・フォルダの名前）。目印ファイル（.ai-bunshin-canary-*）と結果は除く"""
    snap = {}
    cfg_dir = os.path.join(e["user"], ".ai-bunshin")   # 囲いの外で prepare が置く設定のファイル（点検の前に作られる）。比べない
    for root in (e["home"], e["user"], e["plugin"]):
        for dp, dn, fn in os.walk(root):
            for x in dn:
                if C.PROBE_PREFIX in x or os.path.join(dp, x) == cfg_dir or dp.startswith(cfg_dir):
                    continue
                snap[os.path.join(dp, x)] = "DIR"
            for x in fn:
                p = os.path.join(dp, x)
                if C.PROBE_PREFIX in x or p == e["out"] or p.endswith(".tmp") or p.startswith(cfg_dir + os.sep):
                    continue
                snap[p] = open(p, "rb").read()
    return snap


def litter(e):
    out = []
    for root in (e["home"], e["user"], e["plugin"]):
        for dp, dn, fn in os.walk(root):
            out += [os.path.join(dp, x) for x in dn + fn if C.PROBE_PREFIX in x and x != C.MARKER_DIR]
    return out


def profile_for(e, mode="full", drop=None, network=True, extra=()):
    """seatbelt の設定を作る。mode：full＝守る先への書き込み・名前の変更を止める／no_rename＝書き込みは止めるが、名前の変更は止めない／case_sensitive＝大文字・小文字を区別する書き方（正規表現）。
    drop＝この守る先だけ止めない"""
    lines = ["(version 1)", "(allow default)"]
    ancestors = set()
    for p in e["deny"]:
        if drop and p == drop:
            continue
        if mode == "no_rename":   # 中への書き込み・作成は止める。守る先そのものの名前の変更（と、戻すこと）は止めない
            import re
            lines.append('(deny file-write-data (subpath "%s"))' % p)
            lines.append('(deny file-write-create (regex #"^%s/"))' % re.escape(p))
        elif mode == "no_restore":   # 名前を変えるのは通すが、同じ名前に戻すのは止める（守る先の名前への作成を止める）
            lines.append('(deny file-write-data (subpath "%s"))' % p)
            lines.append('(deny file-write-create (subpath "%s"))' % p)
        elif mode == "case_sensitive":
            import re
            lines.append('(deny file-write* (regex #"^%s(/|$)"))' % re.escape(p))
        else:
            lines.append('(deny file-write* (subpath "%s"))' % p)
        if mode not in ("no_rename", "no_restore"):
            q = os.path.dirname(p)
            while q.startswith(e["d"]) and q != e["d"]:
                ancestors.add(q)
                q = os.path.dirname(q)
    for a in sorted(ancestors):
        lines.append('(deny file-write-unlink (literal "%s"))' % a)
    lines += list(extra)
    if network:
        lines.append("(deny network*)")
    path = os.path.join(e["d"], "profile_%s_%s.sb" % (mode, "drop" if drop else "x"))
    open(path, "w").write("\n".join(lines) + "\n")
    return path


# 点検を import で動かす小さな実行ファイル（テスト用。本物の daily_cycle.sh が呼ぶ点検の道具とは別。security の場所の差し替えは import でだけできる）
RUNNER = os.path.join(BASE, "runner.py")
open(RUNNER, "w").write('''import importlib.util, os, sys
spec = importlib.util.spec_from_file_location("sc", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
key = os.environ.pop("AI_BUNSHIN_CANARY_KEY")
m.execute(sys.argv[2], sys.argv[3], key, sys.argv[4])
''')


def prepare_env(e, nonce="N1", net=None, services=("svc",)):
    """囲いの外の作業（設定のファイルを置く・設定の sha256 と write の下限を決める）。e に sha・minw・nonce を覚えておく"""
    host, _, port = (net or "127.0.0.1:%d" % LISTEN_PORT).rpartition(":")
    sha, minw, cfg = C.prepare(e["home"], open(e["settings"], encoding="utf-8").read(), nonce, e["out"], list(services), [(host, int(port))], user_home=e["user"])
    e.update(sha=sha, minw=minw, nonce=nonce, cfg=cfg)
    return cfg


def run_canary(e, profile=None, env_extra=None, security=SEC_BLOCKED, nonce="N1", net=None, services=("svc",), key=None):
    env = {k: v for k, v in os.environ.items() if k != C.URL_ENV and k not in C.PROXY_ENVS and k != C.KEY_ENV}
    env.update(env_extra or {})
    env[C.KEY_ENV] = key or e["key"]
    if os.path.exists(e["out"]):
        os.remove(e["out"])
    cfg = prepare_env(e, nonce, net, services)
    cmd = [sys.executable, "-B", "-I", RUNNER, CANARY, cfg, nonce, security]
    if profile:
        cmd = ["sandbox-exec", "-f", profile] + cmd
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120, cwd=e["home"])
    res = json.load(open(e["out"], encoding="utf-8")) if os.path.exists(e["out"]) else None
    return r, res


def J(e, nonce="N1", key=None):
    """囲いの外の判定（run_canary のあと）"""
    return C.judge(e["out"], nonce, key or e["key"], e["sha"], e["minw"])


def judge_cli(e, nonce="N1", key=None, sha=None, minw=None):
    env = {k: v for k, v in os.environ.items() if k != C.KEY_ENV}
    if key is not False:
        env[C.KEY_ENV] = key or e["key"]
    r = subprocess.run([sys.executable, "-I", CANARY, "--judge", e["out"], "--nonce", nonce, "--config-sha256", sha or e["sha"],
                        "--min-writes", str(minw if minw is not None else e["minw"])], capture_output=True, text=True, env=env)
    return r.returncode, r.stdout.strip()


def signed(data, key=KEY):
    d = dict(data)
    d.pop("mac", None)
    d["mac"] = C.sign(d, key)
    return d


# ---------- 判定（judge） ----------

SHA, MINW = "a" * 64, 5


def base_result(nonce="N", **kw):
    d = {"v": C.VERSION, "nonce": nonce, "date": "2026-11-07", "checks": {k: "blocked" for k in C.CHECKS}, "counts": {"write": MINW},
         "litter": None, "restore_failed": False, "config_sha256": SHA}
    d.update(kw)
    return d


@case
def j1_judge_accepts_only_all_blocked_for_this_run():
    d = os.path.join(BASE, "j1")
    os.makedirs(d)
    f = os.path.join(d, "r.json")

    def put(checks=None, nonce="N", key=KEY, **kw):
        data = base_result(nonce=nonce, **kw)
        data["checks"] = dict(data["checks"], **(checks or {}))
        json.dump(signed(data, key), open(f, "w"))
        return C.judge(f, "N", KEY, SHA, MINW)
    assert put() == (True, "")
    for k in C.CHECKS:
        for bad in ("leaked", "error", "skipped", "ok", None, True):
            ok, why = put({k: bad})
            assert not ok and k + "=" in why, (k, bad, why)
    ok, why = put(nonce="OLD")
    assert not ok and "今回のものではない" in why, why
    ok, why = put(restore_failed=True)
    assert not ok and "restore_failed" in why, why
    # 項目が欠けている・版が違う
    json.dump(signed(base_result(checks={"write": "blocked"})), open(f, "w"))
    assert not C.judge(f, "N", KEY, SHA, MINW)[0]
    json.dump(signed(base_result(v=1)), open(f, "w"))
    ok, why = C.judge(f, "N", KEY, SHA, MINW)
    assert not ok and "形が違う" in why, why
    for text in ("not json", "[]", "null", ""):
        open(f, "w").write(text)
        ok, why = C.judge(f, "N", KEY, SHA, MINW)
        assert not ok and "形が違う" in why, (text, why)
    os.remove(f)
    ok, why = C.judge(f, "N", KEY, SHA, MINW)
    assert not ok and "動かなかった" in why, why
    # 理由にパス・URL が入らない（項目名と状態だけ）
    ok, why = put({"write": "/Users/x/secret https://h.example/y", "network": "leaked"})
    assert not ok and "/" not in why and "http" not in why, why


@case
def j3_judge_rejects_forged_or_tampered_results():
    """S20②③：印の無い・違う鍵・印のあとの書き換え・設定の sha256 違い・write の数が下限未満は、全部 blocked でも通さない"""
    d = os.path.join(BASE, "j3")
    os.makedirs(d)
    f = os.path.join(d, "r.json")

    def judge_data(data, key=KEY, sha=SHA, minw=MINW):
        json.dump(data, open(f, "w"))
        return C.judge(f, "N", key, sha, minw)

    def expect_fail(label, res, word):
        ok, why = res
        assert not ok and word in why, (label, ok, why)
    assert judge_data(signed(base_result())) == (True, "")
    # 印を外す・違う鍵で付ける・印が文字でない
    d0 = signed(base_result())
    d0.pop("mac")
    expect_fail("nomac", judge_data(d0), "印")
    expect_fail("otherkey", judge_data(signed(base_result(), OTHER_KEY)), "印")
    for bad in (None, 123, ["x"], "", "0" * 64):
        expect_fail("badmac %r" % (bad,), judge_data(dict(signed(base_result()), mac=bad)), "印")
    # 印を付けたあとの書き換え（leaked → blocked・設定の sha256・数・nonce・日付・余計な項目）
    leaked = signed(base_result(checks={k: ("leaked" if k == "write" else "blocked") for k in C.CHECKS}))
    t = json.loads(json.dumps(leaked))
    t["checks"]["write"] = "blocked"
    expect_fail("flip", judge_data(t), "印")
    t = json.loads(json.dumps(signed(base_result())))
    t["config_sha256"] = "b" * 64
    expect_fail("sha", judge_data(t, sha="b" * 64), "印")
    t = json.loads(json.dumps(signed(base_result(counts={"write": 0}))))
    t["counts"]["write"] = 99
    expect_fail("count", judge_data(t), "印")
    t = json.loads(json.dumps(signed(base_result())))
    t["restore_failed"] = True
    expect_fail("restore", judge_data(t), "印")
    t = json.loads(json.dumps(signed(base_result())))
    t["extra"] = 1
    expect_fail("extra", judge_data(t), "印")
    # 鍵が無い・短い（判定側）
    for k in (None, "", "short", 123):
        expect_fail("key %r" % (k,), judge_data(signed(base_result()), key=k), "鍵")
    # 設定の中身の sha256 が、囲いの外の値と違う（印は正しい）
    expect_fail("sha-mismatch", judge_data(signed(base_result(config_sha256="c" * 64))), "設定の中身")
    for bad_sha in (None, "", 5):
        expect_fail("expected-sha %r" % (bad_sha,), judge_data(signed(base_result()), sha=bad_sha), "設定の中身")
    d1 = base_result()
    d1.pop("config_sha256")
    expect_fail("no-sha", judge_data(signed(d1)), "設定の中身")
    # write で確かめた数が、囲いの外で数えた下限より少ない・数でない・無い（印は正しい）
    expect_fail("low", judge_data(signed(base_result(counts={"write": MINW - 1}))), "足りない")
    for bad in ({}, {"write": True}, {"write": "9"}, {"write": None}, {"write": 5.0}):
        expect_fail("count %r" % (bad,), judge_data(signed(base_result(counts=bad))), "足りない")
    expect_fail("nocounts", judge_data(signed(base_result(counts=None))), "足りない")
    assert judge_data(signed(base_result(counts={"write": MINW + 3}))) == (True, "")
    # 下限が0・数でない：確かめる守る先が1つも無い
    for m in (0, -1, None, True, "5"):
        expect_fail("minw %r" % (m,), judge_data(signed(base_result()), minw=m), "守る先")
    # 項目が通らなかったときは、数が足りなくても項目名が出る（ログの案内に使う）
    ok, why = judge_data(signed(base_result(counts={"write": 0}, checks={k: ("leaked" if k == "write" else "blocked") for k in C.CHECKS})))
    assert not ok and why == "write=leaked", why


@case
def j2_cli_judge_exit_codes_and_output():
    e = {"out": os.path.join(BASE, "j2.json"), "key": KEY, "sha": SHA, "minw": MINW}
    json.dump(signed(base_result()), open(e["out"], "w"))
    assert judge_cli(e, "N") == (0, "")
    assert judge_cli(e, "M")[0] == 1
    assert judge_cli(e, "N", key=OTHER_KEY) == (1, "結果の印が正しくない")
    assert judge_cli(e, "N", key=False) == (1, "鍵が無い")   # 環境に鍵が無い
    assert judge_cli(e, "N", sha="d" * 64) == (1, "設定の中身が違う")
    assert judge_cli(e, "N", minw=MINW + 1) == (1, "write の確かめた数が足りない")
    json.dump(signed(base_result(checks=dict({k: "blocked" for k in C.CHECKS}, network="leaked", keychain="error"))), open(e["out"], "w"))
    assert judge_cli(e, "N") == (1, "network=leaked,keychain=error")
    # 引数が足りない・形が違う：64（値は出さない）
    base = [sys.executable, "-I", CANARY]
    env = dict(os.environ, **{C.KEY_ENV: KEY})
    for argv in ([], ["--bogus"], ["--judge", e["out"]], ["--judge", e["out"], "--nonce", "N"], ["--judge", e["out"], "--nonce", "N", "--config-sha256", SHA],
                 ["--judge", e["out"], "--nonce", "N", "--config-sha256", SHA, "--min-writes", "x"],
                 ["--judge", e["out"], "--nonce", "N", "--config-sha256", SHA, "--min-writes", "5", "--out", "/tmp/x"]):
        r = subprocess.run(base + argv, capture_output=True, text=True, env=env)
        assert r.returncode == 64 and r.stdout == "" and KEY not in r.stderr, (argv, r.returncode, r.stdout, r.stderr)


# ---------- 囲いが無い日：全部通る。でも実物は壊さない ----------

@case
def c1_no_fence_everything_leaks_but_nothing_is_damaged():
    e = make_env("c1")
    before = snapshot(e)
    r, res = run_canary(e, env_extra={C.URL_ENV: "https://h.example/x-" + SECRET}, security=SEC_FOUND)
    assert r.returncode == 0, (r.returncode, r.stderr)
    assert res is not None
    assert res["checks"]["write"] == "leaked" and res["checks"]["network"] == "leaked", res
    assert res["checks"]["keychain"] == "leaked" and res["checks"]["env_url"] == "leaked", res
    assert res["checks"]["parent_mv"] == "skipped" and res["checks"]["case"] == "skipped", "write が通った日に名前を変えようとした: %s" % res
    ok, why = J(e)
    assert not ok and "write=leaked" in why and "network=leaked" in why and "keychain=leaked" in why and "env_url=leaked" in why, why
    after = snapshot(e)
    assert before == after, "実物が変わった：%s" % sorted(set(before) ^ set(after))
    lit = litter(e)
    assert 1 <= len(lit) <= C.LITTER_BUDGET, lit
    assert all(os.path.getsize(p) == 0 for p in lit), "目印のファイルが空でない"
    assert res["litter"] == C.PROBE_PREFIX + "*"
    text = json.dumps(res, ensure_ascii=False) + r.stdout + r.stderr
    assert SECRET not in text, "結果・出力にキーチェーンの中身・URL が出た"
    assert e["home"] not in json.dumps(res, ensure_ascii=False), "結果にパスが入っている"


@case
def c2_parent_mv_renames_back_when_it_goes_through():
    e = make_env("c2")
    before = snapshot(e)
    state, restore_failed = C.check_parent_mv(e["home"], e["deny"], "X")
    assert (state, restore_failed) == ("leaked", False), (state, restore_failed)
    assert snapshot(e) == before, "名前が元に戻っていない"
    assert not [x for x in os.listdir(e["home"]) if ".moved-" in x or x.startswith(C.GUARD_DIR)], os.listdir(e["home"])
    assert os.path.isdir(os.path.join(e["home"], C.MARKER_DIR, C.GUARD_DIR))
    # 本物の scripts/・.git は付け替えない：囲いが無くて通る日でも、名前は一度も変わらない
    real_rename = os.rename
    renamed = []

    def spy(a, b):
        renamed.append(a)
        return real_rename(a, b)
    os.rename = spy
    try:
        C.check_parent_mv(e["home"], e["deny"], "W")
    finally:
        os.rename = real_rename
    assert renamed and all(C.MARKER_DIR in x for x in renamed), "目印フォルダ以外の名前を変えた：%s" % renamed
    # 戻せないとき（戻す先がふさがれた）は restore_failed を返して止まる
    calls = []

    def flaky(a, b):
        calls.append((a, b))
        if len(calls) == 2:
            raise PermissionError(1, "no")
        return real_rename(a, b)
    os.rename = flaky
    try:
        state, restore_failed = C.check_parent_mv(e["home"], e["deny"], "Y")
    finally:
        os.rename = real_rename
    assert (state, restore_failed) == ("leaked", True), (state, restore_failed)
    real_rename(os.path.join(e["home"], C.MARKER_DIR + ".moved-Y"), os.path.join(e["home"], C.MARKER_DIR))   # 後始末（一時フォルダ）
    # 目印フォルダが無い・中の inner が無いとき：確かめられない（error）
    e2 = make_env("c2b")
    real_rename(os.path.join(e2["home"], C.MARKER_DIR, C.GUARD_DIR), os.path.join(e2["home"], "elsewhere"))
    assert C.check_parent_mv(e2["home"], e2["deny"], "Z") == ("error", False)
    e3 = make_env("c2c")
    real_rename(os.path.join(e3["home"], C.MARKER_DIR), os.path.join(e3["home"], "elsewhere"))
    assert C.check_parent_mv(e3["home"], e3["deny"], "Z") == ("error", False)
    r, res = run_canary(e3)
    assert res["checks"]["parent_mv"] in ("error", "skipped"), res
    assert not J(e3)[0]


@case
def c3_probe_writes_nothing_to_existing_files():
    e = make_env("c3")
    f = os.path.join(e["home"], "CLAUDE.md")
    st = os.stat(f)
    b = C.Budget(2)
    assert C.probe_write(f, "Z", b) == "leaked"   # 囲いが無いので開ける
    st2 = os.stat(f)
    assert open(f).read() == "# 本人設定\n" and st2.st_size == st.st_size and st2.st_mtime_ns == st.st_mtime_ns, "ファイルの中身・更新時刻が変わった"
    assert b.left == 2, "ファイルの確かめで目印の枠を使った"
    assert C.probe_write(os.path.join(e["home"], "CLAUDE.local.md"), "Z", b) == "skip"
    assert not os.path.exists(os.path.join(e["home"], "CLAUDE.local.md")), "無いファイルを作った"
    d = os.path.join(e["home"], "設定")
    assert C.probe_write(d, "Z", b) == "leaked" and b.left == 1
    assert C.probe_write(d, "Z", b) == "leaked" and b.left == 0
    assert C.probe_write(d, "Z", b) == "skip", "枠を使い切ったのに作った"
    assert len(litter(e)) == 2


# ---------- 囲いがある日（sandbox-exec） ----------

def need_sbx(fn):
    def wrapper():
        if not HAVE_SBX:
            skipped.append(fn.__name__)
            print("  (skip: sandbox-exec が使えない)", end=" ")
            return
        return fn()
    wrapper.__name__ = fn.__name__
    return wrapper


@case
@need_sbx
def s1_full_fence_all_blocked():
    e = make_env("s1")
    before = snapshot(e)
    r, res = run_canary(e, profile=profile_for(e))
    assert r.returncode == 0, (r.returncode, r.stderr[-300:])
    assert res and res["checks"] == {k: "blocked" for k in C.CHECKS}, res
    assert J(e) == (True, ""), J(e)
    assert judge_cli(e) == (0, "")
    assert snapshot(e) == before and litter(e) == [], "囲いの中で何かが変わった／目印が残った"
    assert res["counts"]["write"] >= 8, res["counts"]   # 守る先を数か所以上確かめている（NFC・NFD・realpath の形も数える）


def only_leaks(res, *items):
    leaked = sorted(k for k, v in res["checks"].items() if v == "leaked")
    assert leaked == sorted(items), (leaked, res["checks"])


@case
@need_sbx
def s2_write_leak_when_a_protected_path_is_not_fenced():
    e = make_env("s2")
    target = os.path.join(e["home"], "設定")
    r, res = run_canary(e, profile=profile_for(e, drop=target))
    assert res["checks"]["write"] == "leaked", res
    ok, why = J(e)
    assert not ok and "write=leaked" in why, why
    assert any(C.PROBE_PREFIX in x for x in os.listdir(target)), "設定に目印が残っていない（記録して残す）"
    assert open(os.path.join(target, "config.json"), encoding="utf-8").read() == "{}"


def marker_path(e):
    return os.path.join(e["home"], C.MARKER_DIR)


@case
@need_sbx
def s3_parent_mv_leak_when_rename_is_not_blocked():
    e = make_env("s3")
    before = snapshot(e)
    r, res = run_canary(e, profile=profile_for(e, mode="no_rename"))
    assert res["checks"]["write"] == "blocked" and res["checks"]["parent_mv"] == "leaked", res
    ok, why = J(e)
    assert not ok and "parent_mv=leaked" in why, why
    assert snapshot(e) == before, "名前を戻せていない"
    assert not res["restore_failed"]


@case
@need_sbx
def s3a_marker_dir_rename_alone_is_detected():
    # 目印フォルダごとの付け替えだけが通る囲い（中の inner の付け替えは止まる）：(a) の確かめが無いと見逃す
    e = make_env("s3a")
    m = marker_path(e)
    r, res = run_canary(e, profile=profile_for(e, mode="no_rename", extra=['(deny file-write-unlink (literal "%s/%s"))' % (m, C.GUARD_DIR)]))
    assert res["checks"]["write"] == "blocked" and res["checks"]["parent_mv"] == "leaked", res
    assert os.path.isdir(os.path.join(m, C.GUARD_DIR)), "名前が戻っていない"


@case
@need_sbx
def s3i_inner_rename_alone_is_detected():
    # 中の inner を外へ出す付け替えだけが通る囲い（目印フォルダごとの付け替えは止まる）：(b) の確かめが無いと見逃す
    e = make_env("s3i")
    m = marker_path(e)
    r, res = run_canary(e, profile=profile_for(e, mode="no_rename", extra=['(deny file-write-unlink (literal "%s"))' % m, '(allow file-write-create (literal "%s/%s"))' % (m, C.GUARD_DIR)]))   # 戻す先（inner）への作成は通す（戻せる囲い）
    assert res["checks"]["write"] == "blocked" and res["checks"]["parent_mv"] == "leaked", res
    assert os.path.isdir(os.path.join(m, C.GUARD_DIR)) and not os.path.exists(os.path.join(e["home"], C.GUARD_DIR + C.PROBE_PREFIX + "N1")), "名前が戻っていない"


@case
@need_sbx
def s3b_parent_mv_that_cannot_be_restored_is_reported():
    e = make_env("s3b")
    # 守っていない親の付け替えは通り、元の名前に戻す（その名前への作成）が止まる囲い
    r, res = run_canary(e, profile=profile_for(e, mode="no_restore", extra=['(deny file-write-create (literal "%s"))' % marker_path(e)]))
    assert res["checks"]["parent_mv"] == "leaked" and res["restore_failed"] is True, res
    ok, why = J(e)
    assert not ok and "parent_mv=leaked" in why and "parent_mv_restore_failed" in why, why
    moved = marker_path(e) + ".moved-N1"
    assert os.path.isdir(moved), "名前が変わったまま残る（目印のフォルダ。次の日に daily_cycle.sh が作り直す）"
    os.rename(moved, marker_path(e))   # 後始末（一時フォルダ）


@case
@need_sbx
def s3c_real_scripts_and_git_are_never_renamed():
    # 名前の付け替えが通る囲いでも、本物の scripts/・.git の名前は変わらない
    e = make_env("s3c")
    before = snapshot(e)
    r, res = run_canary(e, profile=profile_for(e, mode="no_rename"))
    assert res["checks"]["parent_mv"] == "leaked", res
    assert os.path.isdir(os.path.join(e["home"], "scripts")) and os.path.isdir(os.path.join(e["home"], ".git")), "本物のフォルダの名前が変わった"
    assert snapshot(e) == before


@case
@need_sbx
def s4_case_leak_when_fence_is_case_sensitive():
    e = make_env("s4")
    probe = os.path.join(e["home"], "claude.md")
    if not os.path.exists(probe):
        skipped.append("s4（大文字・小文字を区別するディスク）")
        print("(skip: このディスクは大文字・小文字を区別する)", end=" ")
        return
    r, res = run_canary(e, profile=profile_for(e, mode="case_sensitive"))
    if res["checks"]["case"] != "leaked":
        skipped.append("s4（この seatbelt の正規表現は大文字・小文字を区別しない）")
        print("(skip: 正規表現が大文字・小文字を区別しない)", end=" ")
        return
    only_leaks(res, "case")
    ok, why = J(e)
    assert not ok and "case=leaked" in why, why
    assert open(os.path.join(e["home"], "CLAUDE.md")).read() == "# 本人設定\n"


@case
@need_sbx
def s5_network_leak_when_not_blocked():
    e = make_env("s5")
    r, res = run_canary(e, profile=profile_for(e, network=False))
    only_leaks(res, "network")
    ok, why = J(e)
    assert not ok and why == "network=leaked", why


@case
@need_sbx
def s6_keychain_leak_when_found():
    e = make_env("s6")
    r, res = run_canary(e, profile=profile_for(e), security=SEC_FOUND)
    only_leaks(res, "keychain")
    assert J(e) == (False, "keychain=leaked")
    assert SECRET not in json.dumps(res) + r.stdout + r.stderr


@case
@need_sbx
def s7_env_url_leak_when_present():
    e = make_env("s7")
    r, res = run_canary(e, profile=profile_for(e), env_extra={C.URL_ENV: "https://h.example/" + SECRET})
    only_leaks(res, "env_url")
    assert J(e) == (False, "env_url=leaked")
    assert SECRET not in json.dumps(res) + r.stdout + r.stderr


# ---------- 個別の確かめ ----------

@case
def n3_keychain_services_from_config():
    e = make_env("n3")
    assert C.keychain_services(e["home"]) == [C.CLAUDE_CREDENTIAL_SERVICE]
    json.dump({"calendar": {"type": "ics", "keychain": "my-cal"}}, open(os.path.join(e["home"], "設定", "config.json"), "w", encoding="utf-8"))
    assert C.keychain_services(e["home"]) == ["my-cal", C.CLAUDE_CREDENTIAL_SERVICE]
    json.dump({"calendar": {"type": "ics"}}, open(os.path.join(e["home"], "設定", "config.json"), "w", encoding="utf-8"))
    assert C.keychain_services(e["home"])[0] == "ai-bunshin-calendar"
    open(os.path.join(e["home"], "設定", "config.json"), "w").write("broken")
    assert C.keychain_services(e["home"]) == [C.CLAUDE_CREDENTIAL_SERVICE]   # 読めなくても点検は続く


@case
def n1_network_states():
    """S21：直接の接続が EPERM・EACCES（囲いが止めた）のときだけ blocked。拒否・時間切れ・届かないは error（囲いが止めたとは言えない）"""
    real_cc = socket.create_connection
    saved = {k: os.environ.pop(k) for k in C.PROXY_ENVS if k in os.environ}

    def raising(exc):
        def f(*a, **k):
            raise exc
        return f
    T = [("127.0.0.1", 1)]
    try:
        for exc, want in ((OSError(errno.EPERM, "x"), "blocked"), (OSError(errno.EACCES, "x"), "blocked"),
                          (ConnectionRefusedError(errno.ECONNREFUSED, "x"), "error"), (socket.timeout("t"), "error"),
                          (OSError(errno.ENETUNREACH, "x"), "error"), (OSError(errno.EHOSTUNREACH, "x"), "error"),
                          (OSError(errno.EROFS, "x"), "error"), (OSError("no errno"), "error")):
            socket.create_connection = raising(exc)
            assert C.check_network(T) == want, (repr(exc), want)
        # 確かめ先が複数：全部が止めた（EPERM・EACCES）ときだけ blocked。1つでも拒否・届かないなら error
        calls_ = iter([OSError(errno.EPERM, "x"), OSError(errno.ECONNREFUSED, "x")])

        def mixed(*a, **k):
            raise next(calls_)
        socket.create_connection = mixed
        assert C.check_network([("127.0.0.1", 1), ("127.0.0.1", 2)]) == "error"
        socket.create_connection = raising(OSError(errno.EPERM, "x"))
        assert C.check_network([("127.0.0.1", 1), ("127.0.0.1", 2)]) == "blocked"
        assert C.check_network([]) == "error", "確かめ先が無いのに blocked"
        # プロキシ：許可していないドメインへの CONNECT が通れば leaked（直接が止まっていても）。断られても、直接が EPERM でなければ error
        socket.create_connection = real_cc

        def serve(reply):
            s = socket.socket()
            s.bind(("127.0.0.1", 0))
            s.listen(4)
            seen = []

            def loop():
                while True:
                    try:
                        c, _ = s.accept()
                    except OSError:
                        return
                    seen.append(c.recv(512))
                    c.sendall(reply)
                    c.close()
            threading.Thread(target=loop, daemon=True).start()
            return s, seen

        def eperm_for_target(host, port, *a, **k):   # 確かめ先だけ「囲いが止めた」形にし、プロキシへの接続は本物
            if host == "203.0.113.9":
                raise OSError(errno.EPERM, "x")
            return real_cc((host, port), *a, **k)
        socket.create_connection = lambda addr, *a, **k: eperm_for_target(addr[0], addr[1], *a, **k)
        TD = [("203.0.113.9", 443)]
        dead = socket.socket()
        dead.bind(("127.0.0.1", 0))
        dead_port = dead.getsockname()[1]
        dead.close()
        s, seen = serve(b"HTTP/1.1 200 Connection established\r\n\r\n")
        os.environ["HTTPS_PROXY"] = "http://127.0.0.1:%d" % s.getsockname()[1]
        assert C.check_network(TD) == "leaked", "プロキシが通した（200）のに blocked"
        assert seen and seen[0].startswith(b"CONNECT example.com:443"), seen
        assert C.check_network(TD, avoid_hosts=("example.com",)) == "leaked"
        assert seen[-1].startswith(b"CONNECT example.net:443"), "許可している host を避けていない: %s" % seen[-1]
        s.close()
        s2, _ = serve(b"HTTP/1.1 403 Forbidden\r\n\r\n")
        os.environ["HTTPS_PROXY"] = "http://127.0.0.1:%d" % s2.getsockname()[1]
        assert C.check_network(TD) == "blocked", "プロキシが断った（403）・直接は EPERM なのに blocked でない"
        assert C.check_network([("127.0.0.1", dead_port)]) == "error", "直接の接続が拒否（EPERM でない）なのに blocked"
        s2.close()
        os.environ["HTTPS_PROXY"] = "http://127.0.0.1:%d" % dead_port   # プロキシにつながらない＝通っていない
        assert C.check_network(TD) == "blocked"
        os.environ["HTTPS_PROXY"] = "not a url"
        assert C.check_network(TD) == "blocked"
        # 直接つながる先があれば leaked
        os.environ.pop("HTTPS_PROXY")
        socket.create_connection = real_cc
        assert C.check_network([("127.0.0.1", dead_port), ("127.0.0.1", LISTEN_PORT)]) == "leaked"
    finally:
        socket.create_connection = real_cc
        for k in C.PROXY_ENVS:
            os.environ.pop(k, None)
        os.environ.update(saved)


@case
@need_sbx
def n1b_network_in_fence_is_blocked_and_refused_is_error():
    """本物の seatbelt の下：囲いが通信を止めれば EPERM で blocked。囲いが無くて、つながらない先は error（blocked にしない）"""
    e = make_env("n1b")
    r, res = run_canary(e, profile=profile_for(e), net="127.0.0.1:%d" % LISTEN_PORT)
    assert res["checks"]["network"] == "blocked", res
    dead = socket.socket()
    dead.bind(("127.0.0.1", 0))
    dead_port = dead.getsockname()[1]
    dead.close()
    e2 = make_env("n1c")
    r, res = run_canary(e2, profile=profile_for(e2, network=False), net="127.0.0.1:%d" % dead_port)
    assert res["checks"]["network"] == "error", res
    assert not J(e2)[0]


@case
def n2_keychain_states():
    assert C.check_keychain(SEC_BLOCKED, ["a", "b"]) == "blocked"
    assert C.check_keychain(SEC_FOUND, ["a"]) == "leaked"
    # 確かめる項目が1つも無い日は error（0以外が「囲いに止められた」と言えない。S22）
    assert C.check_keychain(SEC_BLOCKED, []) == "error"
    assert C.check_keychain(SEC_BLOCKED, ["", None, 5]) == "error"
    # 2つ目の名前で見つかっても leaked
    p = os.path.join(BASE, "sec_second")
    open(p, "w").write('#!/bin/sh\n[ "$3" = second ] && exit 0\nexit 44\n')
    os.chmod(p, 0o755)
    assert C.check_keychain(p, ["first", "second"]) == "leaked"
    # 中身を頼む引数（-w・-g）を付けない。鍵（環境変数）を security に渡さない
    log = os.path.join(BASE, "sec_args.txt")
    q = os.path.join(BASE, "sec_args")
    open(q, "w").write('#!/bin/sh\necho "$@" >> "%s"\nenv >> "%s"\nexit 44\n' % (log, log))
    os.chmod(q, 0o755)
    os.environ[C.KEY_ENV] = KEY
    try:
        C.check_keychain(q, ["svc"])
    finally:
        os.environ.pop(C.KEY_ENV, None)
    text = open(log).read()
    args = text.splitlines()[0].split()
    assert args == ["find-generic-password", "-s", "svc"] and "-w" not in args and "-g" not in args, args
    assert KEY not in text and C.KEY_ENV not in text, "鍵が security の環境に渡った"
    # 固まったら error（blocked にしない）
    h = os.path.join(BASE, "sec_hang")
    open(h, "w").write("#!/bin/sh\nsleep 30\n")
    os.chmod(h, 0o755)
    saved = C.KEYCHAIN_TIMEOUT
    C.KEYCHAIN_TIMEOUT = 0.5
    try:
        assert C.check_keychain(h, ["svc"]) == "error"
    finally:
        C.KEYCHAIN_TIMEOUT = saved
    assert C.check_keychain(os.path.join(BASE, "no_such_security"), ["svc"]) == "error"   # security が無い・動かせない日は、blocked にしない


@case
def n2b_existing_keychain_services_outside():
    """S22：囲いの外で先に項目があるかを確かめる。ある名前だけ（-w なし）"""
    e = make_env("n2b")
    json.dump({"calendar": {"type": "ics", "keychain": "my-cal"}}, open(os.path.join(e["home"], "設定", "config.json"), "w", encoding="utf-8"))
    log = os.path.join(BASE, "sec_exist.txt")
    p = os.path.join(BASE, "sec_exist")
    open(p, "w").write('#!/bin/sh\necho "$@" >> "%s"\n[ "$3" = my-cal ] && exit 0\nexit 44\n' % log)
    os.chmod(p, 0o755)
    assert C.existing_keychain_services(e["home"], p) == ["my-cal"]
    calls_ = open(log).read().splitlines()
    assert calls_ == ["find-generic-password -s my-cal", "find-generic-password -s " + C.CLAUDE_CREDENTIAL_SERVICE], calls_
    assert C.existing_keychain_services(e["home"], SEC_BLOCKED) == []
    # 引数を渡さなければ、囲いの中と同じ DEFAULT_SECURITY を使う（呼ぶときに決める。G4e 低1）
    saved = C.DEFAULT_SECURITY
    C.DEFAULT_SECURITY = p
    try:
        assert C.existing_keychain_services(e["home"]) == ["my-cal"]
        C.DEFAULT_SECURITY = SEC_BLOCKED
        assert C.existing_keychain_services(e["home"]) == []
    finally:
        C.DEFAULT_SECURITY = saved
    assert C.existing_keychain_services(e["home"], os.path.join(BASE, "no_such_security")) == []


@case
def a1_cli_accepts_only_nonce():
    """S20③：点検の道具は nonce 以外の引数を受け付けない（0以外で終わる）。受け付けないときは何も書かず・何も確かめない。環境変数で確かめ先は変えられない"""
    e = make_env("a1")
    cfg = prepare_env(e, "A1")
    env = {k: v for k, v in os.environ.items() if k not in C.PROXY_ENVS}
    env.update({C.KEY_ENV: KEY, "HOME": e["user"]})
    base = [sys.executable, "-I", CANARY]
    extras = (["--out", os.path.join(BASE, "evil_out.json")], ["--home", e["home"]], ["--settings-file", e["settings"]],
              ["--security-bin", SEC_BLOCKED], ["--net-target", "127.0.0.1:%d" % LISTEN_PORT], ["--net-target=127.0.0.1:1"],
              ["--config-sha256", "a" * 64], ["--min-writes", "1"], ["--judge", e["out"]], ["--nonc", "A1"], ["extra"], ["-x"])
    before = snapshot(e)
    for ex in extras:
        for order in (ex + ["--nonce", "A1"], ["--nonce", "A1"] + ex):
            r = subprocess.run(base + order, capture_output=True, text=True, env=env, cwd=e["home"])
            assert r.returncode == 64, (order, r.returncode)
            assert KEY not in r.stdout + r.stderr, "引数エラーに鍵が出た"
            assert not os.path.exists(e["out"]) and not os.path.exists(os.path.join(BASE, "evil_out.json")), "引数が拒否されたのに結果を書いた：%s" % order
    assert snapshot(e) == before and litter(e) == [], "引数が拒否されたのに、確かめて実物を触った"
    # nonce が無い・形が違う（パスの区切りなど）
    for order in ([], ["--nonce"], ["--nonce", ""], ["--nonce", "../x"], ["--nonce", "a/b"], ["--nonce", "x" * 81], ["--nonce", "a b"]):
        r = subprocess.run(base + order, capture_output=True, text=True, env=env, cwd=e["home"])
        assert r.returncode == 64, (order, r.returncode)
    # 鍵が渡されていない：2。設定のファイルが無い nonce：2（結果も書かない）
    env2 = dict(env)
    env2.pop(C.KEY_ENV)
    r = subprocess.run(base + ["--nonce", "A1"], capture_output=True, text=True, env=env2, cwd=e["home"])
    assert r.returncode == 2 and not os.path.exists(e["out"]), (r.returncode, r.stderr)
    r = subprocess.run(base + ["--nonce", "NOCONFIG"], capture_output=True, text=True, env=env, cwd=e["home"])
    assert r.returncode == 2 and not os.path.exists(e["out"]), r.returncode
    # 短い鍵・16進でない短い値は受け付けない
    env3 = dict(env, **{C.KEY_ENV: "short"})
    r = subprocess.run(base + ["--nonce", "A1"], capture_output=True, text=True, env=env3, cwd=e["home"])
    assert r.returncode == 2 and not os.path.exists(e["out"]), r.returncode
    assert os.path.exists(cfg)


@case
@need_sbx
def a2_cli_end_to_end_signed_result_and_no_key_leak():
    """本番と同じ呼び方（--nonce だけ・鍵は環境変数）を seatbelt の下で：印つきの結果が書かれ、囲いの外の判定が同じ鍵・設定の sha256・下限で通る／違えば通らない。鍵は結果・出力に出ない。
    キーチェーンは、無いはずの名前（本物の security に頼む。項目が無いので0以外）を使う"""
    if sys.platform != "darwin" or not os.path.exists(C.DEFAULT_SECURITY):
        skipped.append("a2（macOS の security が無い）")
        print("(skip: macOS の security が無い)", end=" ")
        return
    e = make_env("a2")
    cfg = prepare_env(e, "A2", services=["ai-bunshin-canary-test-no-such-item-7c1d9e"])
    prof = profile_for(e)
    env = {k: v for k, v in os.environ.items() if k not in C.PROXY_ENVS and k != C.URL_ENV}
    env.update({C.KEY_ENV: KEY, "HOME": e["user"]})
    for name in ("AI_BUNSHIN_SECURITY_BIN", "AI_BUNSHIN_SECURITY", "SECURITY_BIN", "CANARY_SECURITY_BIN", "AI_BUNSHIN_CANARY_SECURITY"):
        env[name] = SEC_FOUND   # 環境変数で security を差し替えようとしても、点検は使わない（全部 blocked のまま）
    for name in ("AI_BUNSHIN_NET_TARGET", "AI_BUNSHIN_CANARY_NET", "AI_BUNSHIN_CANARY_OUT", "AI_BUNSHIN_CANARY_HOME"):
        env[name] = "127.0.0.1:%d" % LISTEN_PORT
    cmd = ["sandbox-exec", "-f", prof, sys.executable, "-B", "-I", CANARY, "--nonce", "A2"]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=e["home"], timeout=120)
    assert r.returncode == 0, (r.returncode, r.stderr[-300:])
    raw = open(e["out"], encoding="utf-8").read()
    res = json.loads(raw)
    assert KEY not in raw + r.stdout + r.stderr, "鍵が結果・出力に出た"
    assert res["mac"] == C.sign(res, KEY) and res["nonce"] == "A2" and res["v"] == C.VERSION
    assert res["config_sha256"] == e["sha"] and res["counts"]["write"] >= e["minw"], (res["counts"], e["minw"])
    assert res["checks"] == {k: "blocked" for k in C.CHECKS}, res
    assert judge_cli(e, "A2") == (0, "")
    assert judge_cli(e, "A2", key=OTHER_KEY) == (1, "結果の印が正しくない")
    assert judge_cli(e, "A2", sha="e" * 64) == (1, "設定の中身が違う")
    assert judge_cli(e, "A2", minw=e["minw"] + 50) == (1, "write の確かめた数が足りない")
    # 結果を書き換える（印はそのまま）・印を外す
    res2 = dict(res, checks=dict(res["checks"], write="leaked"))
    res2b = dict(res2, checks={k: "blocked" for k in C.CHECKS}, counts={"write": 1})
    json.dump(res2b, open(e["out"], "w"))
    assert judge_cli(e, "A2") == (1, "結果の印が正しくない")
    res3 = {k: v for k, v in res.items() if k != "mac"}
    json.dump(res3, open(e["out"], "w"))
    assert judge_cli(e, "A2") == (1, "結果の印が正しくない")
    # 設定のファイルの中身を差し替える（点検の claude が書けたとして）→ 結果の sha256 が、囲いの外の値と合わない
    evil = json.loads(open(cfg, "rb").read().decode("utf-8"))
    evil["net_targets"] = []
    open(cfg, "wb").write((json.dumps(evil, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=e["home"], timeout=120)
    assert r.returncode == 0, (r.returncode, r.stderr[-300:])
    res4 = json.load(open(e["out"], encoding="utf-8"))
    assert res4["mac"] == C.sign(res4, KEY) and res4["config_sha256"] != e["sha"]
    assert judge_cli(e, "A2") == (1, "設定の中身が違う"), judge_cli(e, "A2")
    # 項目0件の日は、同じ呼び方でも error（blocked にならない）
    e2 = make_env("a2b")
    prepare_env(e2, "A2", services=[])
    e2.update(key=KEY)
    r = subprocess.run(["sandbox-exec", "-f", profile_for(e2), sys.executable, "-B", "-I", CANARY, "--nonce", "A2"], capture_output=True, text=True, env=dict(env, HOME=e2["user"]), cwd=e2["home"], timeout=120)
    res5 = json.load(open(e2["out"], encoding="utf-8"))
    assert res5["checks"]["keychain"] == "error" and not C.judge(e2["out"], "A2", KEY, e2["sha"], e2["minw"])[0], res5


@case
def a3_source_reads_only_known_environment_names():
    """S20③：環境変数で確かめ先・security・書き先を変えられない（読む名前は、鍵・カレンダーの URL・プロキシだけ）"""
    src = open(CANARY, encoding="utf-8").read()
    import re
    names_ = set(re.findall(r'os\.environ(?:\.get|\.pop)?\(\s*([A-Za-z_"\']+)', src)) | set(re.findall(r'os\.environ\[\s*([A-Za-z_"\']+)', src))
    allowed = {"KEY_ENV", "name", "URL_ENV"}   # name は PROXY_ENVS の繰り返しの変数
    assert names_ <= allowed, "知らない環境変数を読んでいる：%s" % sorted(names_ - allowed)
    assert "os.environ.items()" in src   # 鍵を外した環境を security に渡す
    assert "add_argument" in src and src.count("add_argument(") == 4, "引数の数が増えた（--nonce・--judge・--config-sha256・--min-writes だけ）"


@case
def a4_prepare_places_config_outside_and_returns_outside_values():
    """S20③：設定のファイルを <ホーム>/.ai-bunshin/canary/<nonce>.json に置く（0600）。中身の sha256・write の下限を返す。nonce の形が悪ければ置かない"""
    e = make_env("a4")
    settings_text = open(e["settings"], encoding="utf-8").read()
    sha, minw, path = C.prepare(e["home"], settings_text, "P1", e["out"], ["svc", "", None], [("127.0.0.1", 9)], user_home=e["user"])
    assert path == os.path.join(e["user"], ".ai-bunshin", "canary", "P1.json") == C.config_path("P1", e["user"]), path
    body = open(path, "rb").read()
    import hashlib
    assert hashlib.sha256(body).hexdigest() == sha
    assert (os.stat(path).st_mode & 0o777) == 0o600
    cfg = json.loads(body.decode("utf-8"))
    assert cfg["keychain_services"] == ["svc"] and cfg["net_targets"] == [["127.0.0.1", 9]] and cfg["home"] == e["home"] and cfg["out"] == e["out"]
    expect = sum(1 for p in C.unique_paths(e["deny"]) if os.path.isdir(p) or os.path.isfile(p))
    assert minw == min(expect, C.MAX_PROBES) and minw >= 8, (minw, expect)
    for bad in ("../x", "a/b", "", "x" * 81, "a b", "a\nb"):
        try:
            C.prepare(e["home"], settings_text, bad, e["out"], [], user_home=e["user"])
        except ValueError:
            pass
        else:
            raise AssertionError("nonce %r を受け付けた" % bad)
    # 守る先が1つも無い日は、下限が0（呼ぶ側が点検に進まない）
    empty = json.dumps({"sandbox": {"filesystem": {"denyWrite": [os.path.join(e["d"], "nowhere")]}, "network": {}}})
    assert C.prepare(e["home"], empty, "P2", e["out"], [], user_home=e["user"])[1] == 0
    # execute は nonce が合わない・版が違う設定を使わない
    try:
        C.execute(path, "OTHER", KEY, SEC_BLOCKED)
    except ValueError:
        pass
    else:
        raise AssertionError("別の nonce の設定を使った")


@case
def n4_unreadable_settings_gives_errors_not_blocked():
    e = make_env("n4")
    cfg = prepare_env(e, "N4")
    body = json.load(open(cfg, encoding="utf-8"))
    body["settings"] = "not a dict"
    open(cfg, "w", encoding="utf-8").write(json.dumps(body, ensure_ascii=False))
    res = C.execute(cfg, "N4", KEY, SEC_BLOCKED)
    for k in ("write", "parent_mv", "case"):
        assert res["checks"][k] == "error", res
    assert res["mac"] == C.sign(res, KEY)
    assert not C.judge(e["out"], "N4", KEY, e["sha"], e["minw"])[0]
    body["settings"] = {"sandbox": {"filesystem": {"denyWrite": []}, "network": {}}}
    open(cfg, "w", encoding="utf-8").write(json.dumps(body, ensure_ascii=False))
    res = C.execute(cfg, "N4", KEY, SEC_BLOCKED)
    assert res["checks"]["write"] == "error", "守る先が空なのに blocked"
    assert litter(e) == []


@case
def g1_default_security_is_fixed_to_usr_bin_security():
    """G4e 低2：囲いの外と中で同じ security を使うので、その値を、スキップしない確かめで固定する"""
    assert C.DEFAULT_SECURITY == "/usr/bin/security", C.DEFAULT_SECURITY
    import inspect
    assert inspect.signature(C.execute).parameters["security_bin"].default == "/usr/bin/security"


@case
def g2_settings_allow_bash_reads_three_settings_without_stopping():
    """G4e S25：設定の permissions.allow に Bash（や mcp）の許可があれば True。許可の中身は返さない。読めない・壊れた JSON・形が違うときは飛ばす（例外にしない）"""
    d = os.path.join(BASE, "g2")
    os.makedirs(d)

    def put(name, data, raw=None):
        p = os.path.join(d, name)
        open(p, "w", encoding="utf-8").write(raw if raw is not None else json.dumps(data))
        return p
    assert C.settings_allow_bash([put("a.json", {"permissions": {"allow": ["Read", "Bash(python3:*)"]}})]) is True
    assert C.settings_allow_bash([put("b.json", {"permissions": {"allow": ["Bash"]}})]) is True
    assert C.settings_allow_bash([put("c.json", {"permissions": {"allow": ["mcp__oplan__create"]}})]) is True
    assert C.settings_allow_bash([put("d.json", {"permissions": {"allow": [" Bash(ls:*)"]}})]) is True
    assert C.settings_allow_bash([put("e.json", {"permissions": {"allow": ["Read", "Edit(x)"]}})]) is False
    assert C.settings_allow_bash([put("f.json", {"permissions": {"deny": ["Bash(rm:*)"], "ask": ["Bash(git:*)"]}})]) is False, "deny・ask は許可ではない"
    for bad in ({"permissions": []}, {"permissions": {"allow": "Bash"}}, {"permissions": {"allow": [1, None, ["Bash"]]}}, [], "x", None, {}):
        assert C.settings_allow_bash([put("g.json", bad)]) is False, bad
    assert C.settings_allow_bash([put("h.json", None, raw="{broken")]) is False
    assert C.settings_allow_bash([put("i.json", None, raw="")]) is False
    assert C.settings_allow_bash([os.path.join(d, "no_such.json")]) is False
    assert C.settings_allow_bash([]) is False
    # 3つのうち1つにあれば True（壊れたもの・無いものがあっても、ほかを読む）
    assert C.settings_allow_bash([os.path.join(d, "no_such.json"), os.path.join(d, "h.json"), os.path.join(d, "a.json")]) is True
    # BOM 付きでも読む
    assert C.settings_allow_bash([put("j.json", None, raw="\ufeff" + json.dumps({"permissions": {"allow": ["Bash(x:*)"]}}))]) is True


@case
def g3_gitignore_template_ignores_canary_marks():
    """G4e 低6：雛形の .gitignore に .ai-bunshin-canary-*（囲いが効いていない日に残る空の目印）。実際に Git が無視する（一時フォルダの中だけ）"""
    tpl = os.path.join(HERE, "..", "templates", "gitignore.txt")
    text = open(tpl, encoding="utf-8").read()
    lines = [x.strip() for x in text.splitlines()]
    assert ".ai-bunshin-canary-*" in lines, "雛形の .gitignore に .ai-bunshin-canary-* が無い"
    assert "00_タスク管理/data/forecast.json" in lines, "T118 の forecast.json の行が消えた"
    repo = os.path.join(BASE, "gitchk")
    os.makedirs(os.path.join(repo, "設定"))
    subprocess.run(["git", "init", "-q", repo], check=True, capture_output=True)
    open(os.path.join(repo, ".gitignore"), "w", encoding="utf-8").write(text)

    def ignored(rel):
        return subprocess.run(["git", "-C", repo, "check-ignore", rel], capture_output=True, text=True).returncode == 0
    for rel in (".ai-bunshin-canary-N1-1", "設定/.ai-bunshin-canary-N1-2", ".ai-bunshin-canary-dir", ".ai-bunshin-canary-dir.moved-N1"):
        assert ignored(rel), rel
    for rel in ("CLAUDE.md", "設定/config.json", "ai-bunshin-canary.txt"):
        assert not ignored(rel), rel

@case
def n5_case_probe_on_case_sensitive_names_is_not_a_leak():
    # 大文字・小文字を変えた名前が存在しない（区別するディスク）なら、別のファイルなので blocked。対象になる名前が1つも無ければ error
    e = make_env("n5")
    real_lexists = os.path.lexists
    os.path.lexists = lambda p: real_lexists(p) and p in e["deny"]   # 変えた名前は無いことにする
    try:
        st = C.check_case(e["deny"], "Q", C.Budget(2))
    finally:
        os.path.lexists = real_lexists
    assert st == "blocked", st
    assert C.check_case([os.path.join(e["home"], "設定")], "Q", C.Budget(2)) == "error"   # 大文字・小文字の無い名前だけ
    assert litter(e) == []


@case
def n7_case_probe_leaks_without_a_fence_and_leaves_at_most_the_budget():
    # seatbelt は大文字・小文字を区別しない（s4 で確かめられなかった）ので、囲い無しで case の確かめが通ること（leaked）を直接見る
    e = make_env("n7")
    if not os.path.exists(os.path.join(e["home"], "claude.md")):
        skipped.append("n7（大文字・小文字を区別するディスク）")
        return
    before = snapshot(e)
    assert C.check_case(e["deny"], "Q", C.Budget(C.LITTER_BUDGET)) == "leaked"
    assert snapshot(e) == before and 1 <= len(litter(e)) <= C.LITTER_BUDGET, litter(e)


@case
def n8_guard_is_protected_and_marker_parent_is_not():
    """S23：守る先は .ai-bunshin-canary-dir/guard だけ。守っていない親 .ai-bunshin-canary-dir は守る先の一覧に入れない。設定のファイルの置き場（ユーザーのホームの .ai-bunshin）は守る"""
    spec = json.load(open(os.path.join(SCRIPTS, "protected_paths.json"), encoding="utf-8"))
    ent = [x for x in spec["entries"] if x["path"] == C.MARKER_DIR + "/" + C.GUARD_DIR]
    assert len(ent) == 1 and ent[0]["base"] == "home" and ent[0]["kind"] == "dir", "guard が一覧にない（または名前が違う）: %s" % ent
    assert not [x for x in spec["entries"] if x["path"] == C.MARKER_DIR], "守っていないはずの親が一覧に入っている"
    e = make_env("n8")
    assert os.path.join(e["home"], C.MARKER_DIR, C.GUARD_DIR) in e["deny"], "本物の sandbox_settings.py の denyWrite に guard が入っていない"
    assert os.path.join(e["home"], C.MARKER_DIR) not in e["deny"], "守っていないはずの親が denyWrite に入っている"
    assert os.path.join(e["user"], C.CONFIG_PARTS[0]) in e["deny"], "設定のファイルを置く場所が守られていない（点検の claude が設定を書き換えられる）"


@case
def n6_out_is_written_atomically_and_has_no_paths_or_urls():
    e = make_env("n6")
    r, res = run_canary(e, env_extra={C.URL_ENV: "https://secret.example/" + SECRET})
    assert not os.path.exists(e["out"] + ".tmp")
    text = open(e["out"], encoding="utf-8").read()
    assert SECRET not in text and "secret.example" not in text and e["home"] not in text and e["user"] not in text, text
    assert set(res["checks"]) == set(C.CHECKS) and res["nonce"] == "N1" and res["v"] == C.VERSION and len(res["mac"]) == 64


print(f"\n{len(names) - fails}/{len(names)} passed" + (f"（スキップの中身：{', '.join(skipped)}）" if skipped else ""))
sys.exit(1 if fails else 0)
