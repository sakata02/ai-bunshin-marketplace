"""囲いのカナリア（scripts/sandbox_canary.py）のテスト。T119 G4a（決定 S05・S06・S15・S16）。
作り物の本人のフォルダ・ユーザーのホーム・プラグインの元を一時フォルダに作り、本物の sandbox_settings.py で denyWrite を作る。
そのうえで、macOS の sandbox-exec（Claude Code の囲いと同じ seatbelt）で、囲いの効き方を変えながらカナリアを動かす。
キーチェーンは作り物の security（終了コードを返すだけ）。本物の claude・キーチェーン・本物の本人のフォルダは使わない。

- ①〜⑥（write・parent_mv・case・network・keychain・env_url）のどれか1つが通ったとき、その項目名が結果と判定に出る
- 囲いが全部効いているときだけ、全部 blocked と判定される
- カナリア自身が実物を壊さない（守る先のファイルの中身は変わらず、名前も変わらず、消えず、増えるのは空の目印ファイル最大2つ）
- 結果が無い・形が違う・別の実行のもの・error・skipped は「全部止まった」にならない
実行：python3 tests/test_sandbox_canary.py（失敗があれば終了コード1）。CANARY_UNDER_TEST に別の版の sandbox_canary.py を指すと、その版で流せる"""
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
    return dict(d=d, home=home, user=user, plugin=plugin, settings=sj, deny=deny, out=os.path.join(home, "00_タスク管理", "data", "canary.json"))


def snapshot(e):
    """守る先を含む全体の中身（ファイルの中身・フォルダの名前）。目印ファイル（.ai-bunshin-canary-*）と結果は除く"""
    snap = {}
    for root in (e["home"], e["user"], e["plugin"]):
        for dp, dn, fn in os.walk(root):
            for x in dn:
                if C.PROBE_PREFIX in x:
                    continue
                snap[os.path.join(dp, x)] = "DIR"
            for x in fn:
                p = os.path.join(dp, x)
                if C.PROBE_PREFIX in x or p == e["out"] or p.endswith(".tmp"):
                    continue
                snap[p] = open(p, "rb").read()
    return snap


def litter(e):
    out = []
    for root in (e["home"], e["user"], e["plugin"]):
        for dp, dn, fn in os.walk(root):
            out += [os.path.join(dp, x) for x in dn + fn if C.PROBE_PREFIX in x]
    return out


def profile_for(e, mode="full", drop=None, network=True):
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
    if network:
        lines.append("(deny network*)")
    path = os.path.join(e["d"], "profile_%s_%s.sb" % (mode, "drop" if drop else "x"))
    open(path, "w").write("\n".join(lines) + "\n")
    return path


def run_canary(e, profile=None, env_extra=None, security=SEC_BLOCKED, nonce="N1", net=None):
    env = {k: v for k, v in os.environ.items() if k != C.URL_ENV and k not in C.PROXY_ENVS}
    env.update(env_extra or {})
    if os.path.exists(e["out"]):
        os.remove(e["out"])
    cmd = [sys.executable, "-I", CANARY, "--home", e["home"], "--settings-file", e["settings"], "--nonce", nonce, "--out", e["out"],
           "--net-target", net or "127.0.0.1:%d" % LISTEN_PORT, "--security-bin", security]
    if profile:
        cmd = ["sandbox-exec", "-f", profile] + cmd
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120, cwd=e["home"])
    res = json.load(open(e["out"], encoding="utf-8")) if os.path.exists(e["out"]) else None
    return r, res


def judge(e, nonce="N1"):
    r = subprocess.run([sys.executable, "-I", CANARY, "--judge", e["out"], "--nonce", nonce], capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


# ---------- 判定（judge） ----------

@case
def j1_judge_accepts_only_all_blocked_for_this_run():
    d = os.path.join(BASE, "j1")
    os.makedirs(d)
    f = os.path.join(d, "r.json")

    def put(checks=None, nonce="N", **kw):
        base = {k: "blocked" for k in C.CHECKS}
        base.update(checks or {})
        json.dump(dict({"v": 1, "nonce": nonce, "checks": base}, **kw), open(f, "w"))
        return C.judge(f, "N")
    assert put() == (True, "")
    for k in C.CHECKS:
        for bad in ("leaked", "error", "skipped", "ok", None, True):
            ok, why = put({k: bad})
            assert not ok and k + "=" in why, (k, bad, why)
    ok, why = put(nonce="OLD")
    assert not ok and "今回のものではない" in why, why
    ok, why = put(restore_failed=True)
    assert not ok and "restore_failed" in why, why
    # 項目が欠けている・余計な形
    json.dump({"v": 1, "nonce": "N", "checks": {"write": "blocked"}}, open(f, "w"))
    assert not C.judge(f, "N")[0]
    json.dump({"v": 2, "nonce": "N", "checks": {k: "blocked" for k in C.CHECKS}}, open(f, "w"))
    assert not C.judge(f, "N")[0]
    for text in ("not json", "[]", "null", ""):
        open(f, "w").write(text)
        ok, why = C.judge(f, "N")
        assert not ok and "形が違う" in why, (text, why)
    os.remove(f)
    ok, why = C.judge(f, "N")
    assert not ok and "動かなかった" in why, why
    # 理由にパス・URL が入らない（項目名と状態だけ）
    json.dump({"v": 1, "nonce": "N", "checks": {"write": "/Users/x/secret https://h.example/y", "network": "leaked"}}, open(f, "w"))
    ok, why = C.judge(f, "N")
    assert not ok and "/" not in why and "http" not in why, why


@case
def j2_cli_judge_exit_codes_and_output():
    e = {"out": os.path.join(BASE, "j2.json")}
    json.dump({"v": 1, "nonce": "N", "checks": {k: "blocked" for k in C.CHECKS}}, open(e["out"], "w"))
    assert judge(e, "N") == (0, "")
    assert judge(e, "M")[0] == 1
    json.dump({"v": 1, "nonce": "N", "checks": dict({k: "blocked" for k in C.CHECKS}, network="leaked", keychain="error")}, open(e["out"], "w"))
    assert judge(e, "N") == (1, "network=leaked,keychain=error")
    r = subprocess.run([sys.executable, "-I", CANARY], capture_output=True, text=True)
    assert r.returncode == 64, r.returncode
    r = subprocess.run([sys.executable, "-I", CANARY, "--bogus"], capture_output=True, text=True)
    assert r.returncode == 64, r.returncode


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
    ok, why = C.judge(e["out"], "N1")
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
    assert not [x for x in os.listdir(e["home"]) if C.PROBE_PREFIX in x], os.listdir(e["home"])
    # 戻せないとき（戻す先がふさがれた）は restore_failed を返して止まる
    real_rename = os.rename
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
    for x in os.listdir(e["home"]):   # 後始末：テストの一時フォルダの名前を戻す（実物ではない）
        if C.PROBE_PREFIX in x:
            real_rename(os.path.join(e["home"], x), os.path.join(e["home"], x.split(C.PROBE_PREFIX)[0]))


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
    assert C.judge(e["out"], "N1") == (True, ""), C.judge(e["out"], "N1")
    assert judge(e) == (0, "")
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
    ok, why = C.judge(e["out"], "N1")
    assert not ok and "write=leaked" in why, why
    assert any(C.PROBE_PREFIX in x for x in os.listdir(target)), "設定に目印が残っていない（記録して残す）"
    assert open(os.path.join(target, "config.json"), encoding="utf-8").read() == "{}"


@case
@need_sbx
def s3_parent_mv_leak_when_rename_is_not_blocked():
    e = make_env("s3")
    before = snapshot(e)
    r, res = run_canary(e, profile=profile_for(e, mode="no_rename"))
    assert res["checks"]["write"] == "blocked" and res["checks"]["parent_mv"] == "leaked", res
    ok, why = C.judge(e["out"], "N1")
    assert not ok and "parent_mv=leaked" in why, why
    assert snapshot(e) == before, "名前を戻せていない"


@case
@need_sbx
def s3b_parent_mv_that_cannot_be_restored_is_reported():
    e = make_env("s3b")
    r, res = run_canary(e, profile=profile_for(e, mode="no_restore"))
    assert res["checks"]["parent_mv"] == "leaked" and res["restore_failed"] is True, res
    ok, why = C.judge(e["out"], "N1")
    assert not ok and "parent_mv=leaked" in why and "parent_mv_restore_failed" in why, why
    assert os.path.isdir(os.path.join(e["home"], "scripts" + C.PROBE_PREFIX + "N1")), "名前が変わったまま残る（本人が戻す）"
    os.rename(os.path.join(e["home"], "scripts" + C.PROBE_PREFIX + "N1"), os.path.join(e["home"], "scripts"))   # 後始末（一時フォルダ）


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
    ok, why = C.judge(e["out"], "N1")
    assert not ok and "case=leaked" in why, why
    assert open(os.path.join(e["home"], "CLAUDE.md")).read() == "# 本人設定\n"


@case
@need_sbx
def s5_network_leak_when_not_blocked():
    e = make_env("s5")
    r, res = run_canary(e, profile=profile_for(e, network=False))
    only_leaks(res, "network")
    ok, why = C.judge(e["out"], "N1")
    assert not ok and why == "network=leaked", why


@case
@need_sbx
def s6_keychain_leak_when_found():
    e = make_env("s6")
    r, res = run_canary(e, profile=profile_for(e), security=SEC_FOUND)
    only_leaks(res, "keychain")
    assert C.judge(e["out"], "N1") == (False, "keychain=leaked")
    assert SECRET not in json.dumps(res) + r.stdout + r.stderr


@case
@need_sbx
def s7_env_url_leak_when_present():
    e = make_env("s7")
    r, res = run_canary(e, profile=profile_for(e), env_extra={C.URL_ENV: "https://h.example/" + SECRET})
    only_leaks(res, "env_url")
    assert C.judge(e["out"], "N1") == (False, "env_url=leaked")
    assert SECRET not in json.dumps(res) + r.stdout + r.stderr


# ---------- 個別の確かめ ----------

@case
def n1_network_via_proxy():
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
    dead = socket.socket()
    dead.bind(("127.0.0.1", 0))
    dead_port = dead.getsockname()[1]
    dead.close()   # つながらない先
    targets = [("127.0.0.1", dead_port)]
    saved = {k: os.environ.pop(k) for k in C.PROXY_ENVS if k in os.environ}
    try:
        assert C.check_network(targets) == "blocked"
        s, seen = serve(b"HTTP/1.1 200 Connection established\r\n\r\n")
        os.environ["HTTPS_PROXY"] = "http://127.0.0.1:%d" % s.getsockname()[1]
        assert C.check_network(targets) == "leaked", "プロキシが通した（200）のに blocked"
        assert seen and seen[0].startswith(b"CONNECT example.com:443"), seen
        assert C.check_network(targets, avoid_hosts=("example.com",)) == "leaked"
        assert seen[-1].startswith(b"CONNECT example.net:443"), "許可している host を避けていない: %s" % seen[-1]
        s.close()
        s2, _ = serve(b"HTTP/1.1 403 Forbidden\r\n\r\n")
        os.environ["HTTPS_PROXY"] = "http://127.0.0.1:%d" % s2.getsockname()[1]
        assert C.check_network(targets) == "blocked", "プロキシが断った（403）のに leaked"
        s2.close()
        os.environ["HTTPS_PROXY"] = "http://127.0.0.1:%d" % dead_port   # プロキシにつながらない＝通っていない
        assert C.check_network(targets) == "blocked"
        os.environ["HTTPS_PROXY"] = "not a url"
        assert C.check_network(targets) == "blocked"
        # 直接つながる先があれば leaked
        assert C.check_network([("127.0.0.1", dead_port), ("127.0.0.1", LISTEN_PORT)]) == "leaked"
    finally:
        for k in C.PROXY_ENVS:
            os.environ.pop(k, None)
        os.environ.update(saved)


@case
def n2_keychain_states():
    assert C.check_keychain(SEC_BLOCKED, ["a", "b"]) == "blocked"
    assert C.check_keychain(SEC_FOUND, ["a"]) == "leaked"
    # 2つ目の名前で見つかっても leaked
    p = os.path.join(BASE, "sec_second")
    open(p, "w").write('#!/bin/sh\n[ "$3" = second ] && exit 0\nexit 44\n')
    os.chmod(p, 0o755)
    assert C.check_keychain(p, ["first", "second"]) == "leaked"
    # 中身を頼む引数（-w・-g）を付けない
    log = os.path.join(BASE, "sec_args.txt")
    q = os.path.join(BASE, "sec_args")
    open(q, "w").write('#!/bin/sh\necho "$@" >> "%s"\nexit 44\n' % log)
    os.chmod(q, 0o755)
    C.check_keychain(q, ["svc"])
    args = open(log).read().split()
    assert args == ["find-generic-password", "-s", "svc"] and "-w" not in args and "-g" not in args, args
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
    assert C.check_keychain(os.path.join(BASE, "no_such_security"), ["svc"]) == ("error" if sys.platform == "darwin" else "blocked")


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
def n4_unreadable_settings_gives_errors_not_blocked():
    e = make_env("n4")
    open(e["settings"], "w").write("not json")
    r, res = run_canary(e)
    assert r.returncode == 0 and res, (r.returncode, r.stderr)
    for k in ("write", "parent_mv", "case"):
        assert res["checks"][k] == "error", res
    assert not C.judge(e["out"], "N1")[0]
    open(e["settings"], "w").write(json.dumps({"sandbox": {"filesystem": {"denyWrite": []}, "network": {}}}))
    r, res = run_canary(e)
    assert res["checks"]["write"] == "error", "守る先が空なのに blocked"
    assert litter(e) == []


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
def n6_out_is_written_atomically_and_has_no_paths_or_urls():
    e = make_env("n6")
    r, res = run_canary(e, env_extra={C.URL_ENV: "https://secret.example/" + SECRET})
    assert not os.path.exists(e["out"] + ".tmp")
    text = open(e["out"], encoding="utf-8").read()
    assert SECRET not in text and "secret.example" not in text and e["home"] not in text and e["user"] not in text, text
    assert set(res["checks"]) == set(C.CHECKS) and res["nonce"] == "N1" and res["v"] == 1


print(f"\n{len(names) - fails}/{len(names)} passed" + (f"（スキップの中身：{', '.join(skipped)}）" if skipped else ""))
sys.exit(1 if fails else 0)
