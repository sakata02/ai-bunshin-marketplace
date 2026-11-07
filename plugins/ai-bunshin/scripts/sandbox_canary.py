#!/usr/bin/env python3
"""自動実行の囲い（sandbox）のカナリア：囲いが本当に効いているかを、Python を許す前に確かめる（T119 G4a。決定 S05・S06・S15・S16・S19）。

囲いは Claude Code が claude の中の Bash に掛けるもので、外から同じ囲いを作って試すことはできない。
そこで daily_cycle.sh が、本番と同じ --settings と、このスクリプトだけを許す --allowedTools で短い claude -p を1回動かし、
その中のサンドボックスの下でこのスクリプトを動かす。結果は JSON を1つのファイル（--out）に残す。
囲いの外の daily_cycle.sh が `--judge` で読んで、6つ全部が blocked のときだけ Python を許す。

使い方：
  python3 -I sandbox_canary.py --home <本人のフォルダ> --settings-file <--settings に渡す JSON のファイル> --nonce <この実行の ID> --out <結果の置き場>
        [--net-target host:port ...] [--security-bin <security の場所>]
  python3 -I sandbox_canary.py --judge <結果のファイル> --nonce <この実行の ID>
  → 判定。全部止まっていれば何も出さず終了コード0。そうでなければ、止まらなかった項目名を1行（write=leaked,network=error のように。パス・URL を出さない）出して終了コード1

確かめる6つ（どれも、実物を壊さない形。止まれば blocked、通ってしまえば leaked、確かめられなければ error、前の確かめで通ったためやらなければ skipped）：
  write      守る先（settings の denyWrite）への書き込み。フォルダには新しい空のファイルを作ろうとし、ファイルには書き込み用に開くだけ（1バイトも書かない）。
             通ってしまったら消さずに残して記録する（消すのは NG。残すのは最大2つ。名前は .ai-bunshin-canary-<nonce>-<番号>）
  parent_mv  目印フォルダ（<本人のフォルダ>/.ai-bunshin-canary-dir。中に空のフォルダ inner を1つ。daily_cycle.sh が囲いの外で前もって作る）の
             名前の付け替えと、中の inner を外へ出す付け替え。本物の scripts/・.git は付け替えない。
             通ってしまったら、すぐ元の名前に戻す（戻せなければ restore_failed を記録）
  case       大文字・小文字を変えたパス（CLAUDE.md → claude.md）への書き込み。write と同じ形で確かめる。大文字・小文字を区別するディスクでは別のファイルなので blocked
  network    外への通信：直接つなぐ（1.1.1.1:443）と、環境のプロキシに CONNECT を頼む（許可していないドメイン宛て）。どちらも通らなければ blocked
  keychain   security find-generic-password でキーチェーンの項目を見つけられるか（中身は出さない。見つかったかどうかだけ）
  env_url    環境に AI_BUNSHIN_CALENDAR_URL があるか
"""
import argparse
import errno
import json
import os
import socket
import subprocess
import sys
from datetime import date
from urllib.parse import urlsplit

VERSION = 1
CHECKS = ("write", "parent_mv", "case", "network", "keychain", "env_url")
PROBE_PREFIX = ".ai-bunshin-canary-"
MAX_PROBES = 80            # write の確かめる先の上限
LITTER_BUDGET = 2          # 囲いが効いていないときに作ってしまう空のファイルの上限（write と case を合わせて）
MARKER_DIR = ".ai-bunshin-canary-dir"   # 点検用の目印フォルダ（守る先の一覧 protected_paths.json の S15-canary-dir と同じ名前）
MARKER_INNER = "inner"
NET_TIMEOUT = 3
KEYCHAIN_TIMEOUT = 10
DEFAULT_NET_TARGETS = [("1.1.1.1", 443)]
DEFAULT_SECURITY = "/usr/bin/security"
CLAUDE_CREDENTIAL_SERVICE = "Claude Code-credentials"   # Claude Code 自身の認証情報。どの Mac にもあるとは限らない（無ければ何も分からない）
URL_ENV = "AI_BUNSHIN_CALENDAR_URL"
PROXY_ENVS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")
DENIED_ERRNOS = (errno.EPERM, errno.EACCES, errno.EROFS)   # 囲い（または読み取り専用）に止められた


class Budget:
    def __init__(self, n):
        self.left = n
        self.seq = 0


def _is_denied(e):
    return isinstance(e, OSError) and e.errno in DENIED_ERRNOS


def probe_write(path, nonce, budget):
    """守る先 path に「書けるか」を壊さずに確かめる。返り値：blocked / leaked / error / skip（確かめられない先）"""
    try:
        if os.path.isdir(path):
            if budget.left <= 0:
                return "skip"
            budget.seq += 1
            f = os.path.join(path, "%s%s-%d" % (PROBE_PREFIX, nonce, budget.seq))
            fd = os.open(f, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            budget.left -= 1       # 作れてしまった＝残す（消さない）
            return "leaked"
        if os.path.isfile(path):
            fd = os.open(path, os.O_WRONLY | os.O_APPEND)   # 開くだけ。書かない
            os.close(fd)
            return "leaked"
        return "skip"              # 無い先は確かめない（作ると、無かったものが増えるため）
    except OSError as e:
        return "blocked" if _is_denied(e) else "error"


def _summarize(results, need_any=True):
    """probe の結果の一覧から状態を決める。leaked が1つでもあれば leaked／error があれば error／確かめた先が1つも無ければ error"""
    if "leaked" in results:
        return "leaked"
    if "error" in results:
        return "error"
    if need_any and "blocked" not in results:
        return "error"
    return "blocked"


def unique_paths(deny_write):
    out = []
    for p in deny_write:
        if isinstance(p, str) and p.startswith("/") and p not in out:
            out.append(p)
    return out[:MAX_PROBES * 2]


def check_write(deny, nonce, budget):
    results = []
    for p in deny:
        if len(results) >= MAX_PROBES:
            break
        r = probe_write(p, nonce, budget)
        if r != "skip":
            results.append(r)
    return _summarize(results), len(results)


def _try_rename(old, new):
    """名前を付け替えてみる。返り値：blocked（止まった）／error／moved（通った）"""
    if os.path.lexists(new):
        return "error"
    try:
        os.rename(old, new)
    except OSError as e:
        return "blocked" if _is_denied(e) else "error"
    return "moved"


def check_parent_mv(home, deny, nonce):
    """目印フォルダ（<本人のフォルダ>/.ai-bunshin-canary-dir。中に空のフォルダ inner が1つ。daily_cycle.sh が囲いの外で前もって作る）の
    (a) 名前の付け替え（フォルダごと別名に）と (b) 中のフォルダ（inner）を目印フォルダの外へ出す付け替えが止まるかを確かめる。
    本物の scripts/・.git などは付け替えない（囲いが効いていない日に、戻せない危険を作らないため）。
    通ってしまったら、すぐ元の名前に戻す（目印の空のフォルダなので、戻せなくても害は小さい。戻せなければ restore_failed）。
    返り値：(状態, 戻せなかったか)。目印フォルダが無い・守る先の一覧に入っていない（一覧に無ければ付け替えが通る＝leaked）"""
    home_c = os.path.realpath(home)
    marker = os.path.join(home_c, MARKER_DIR)
    inner = os.path.join(marker, MARKER_INNER)
    if not os.path.isdir(marker) or os.path.islink(marker) or not os.path.isdir(inner) or os.path.islink(inner):
        return "error", False
    results = []
    # (a) 目印フォルダごと
    moved = marker + ".moved-" + nonce
    r = _try_rename(marker, moved)
    if r == "moved":
        try:
            os.rename(moved, marker)
        except OSError:
            return "leaked", True
        return "leaked", False
    results.append(r)
    # (b) 中の inner を目印フォルダの外（本人のフォルダの直下）へ
    out = os.path.join(home_c, MARKER_INNER + PROBE_PREFIX + nonce)
    r = _try_rename(inner, out)
    if r == "moved":
        try:
            os.rename(out, inner)
        except OSError:
            return "leaked", True
        return "leaked", False
    results.append(r)
    return _summarize(results), False


def check_case(deny, nonce, budget):
    results = []
    cased_existing = 0
    for p in deny:
        if len(results) >= 3:
            break
        parent, name = os.path.split(p)
        alt_name = name.swapcase()
        if alt_name == name or not os.path.lexists(p):
            continue
        alt = os.path.join(parent, alt_name)
        if not os.path.lexists(alt):
            cased_existing += 1        # 大文字・小文字を区別するディスク：別の名前は別のファイルなので、通っても守る先ではない
            continue
        try:
            if not os.path.samefile(alt, p):
                continue
        except OSError:
            continue
        r = probe_write(alt, nonce, budget)
        if r != "skip":
            results.append(r)
    if results:
        return _summarize(results)
    return "blocked" if cased_existing else "error"


def _parse_target(s):
    host, _, port = s.rpartition(":")
    return host, int(port)


def check_network(targets, avoid_hosts=()):
    for host, port in targets:
        try:
            s = socket.create_connection((host, port), timeout=NET_TIMEOUT)
            s.close()
            return "leaked"
        except OSError:
            pass
    # 環境のプロキシに、許可していないドメインへの CONNECT を頼む（囲いのプロキシなら、許可の一覧に無いので断る）
    probe_host = next((h for h in ("example.com", "example.net") if h not in avoid_hosts), "example.org")
    for name in PROXY_ENVS:
        v = os.environ.get(name)
        if not v:
            continue
        try:
            u = urlsplit(v if "://" in v else "http://" + v)
            if not u.hostname or not u.port:
                continue
            s = socket.create_connection((u.hostname, u.port), timeout=NET_TIMEOUT)
        except (OSError, ValueError):
            continue
        try:
            s.settimeout(NET_TIMEOUT)
            s.sendall(("CONNECT %s:443 HTTP/1.1\r\nHost: %s:443\r\n\r\n" % (probe_host, probe_host)).encode("ascii"))
            line = s.recv(256).split(b"\r\n", 1)[0]
        except OSError:
            line = b""
        finally:
            s.close()
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith(b"HTTP/1.") and parts[1].startswith(b"2"):
            return "leaked"
    return "blocked"


def check_keychain(security_bin, services):
    """項目が見つかったか（終了コード0）だけを見る。中身（-w・-g）は頼まず、出力は捨てる"""
    for svc in services:
        try:
            r = subprocess.run([security_bin, "find-generic-password", "-s", svc],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=KEYCHAIN_TIMEOUT)
        except FileNotFoundError:
            return "error" if sys.platform == "darwin" else "blocked"
        except (subprocess.TimeoutExpired, OSError):
            return "error"
        if r.returncode == 0:
            return "leaked"
    return "blocked"


def check_env():
    return "leaked" if URL_ENV in os.environ else "blocked"


def keychain_services(home):
    """確かめる項目の名前：config のカレンダー（ics）のキーチェーンの名前と、Claude Code の認証情報"""
    out = []
    try:
        with open(os.path.join(home, "設定", "config.json"), encoding="utf-8-sig") as f:
            cal = json.load(f).get("calendar")
        if isinstance(cal, dict) and cal.get("type") == "ics" and not cal.get("ics_file"):
            name = cal.get("keychain", "ai-bunshin-calendar")
            if isinstance(name, str) and name:
                out.append(name)
    except Exception:  # noqa: BLE001（読めなくても点検は続ける）
        pass
    out.append(CLAUDE_CREDENTIAL_SERVICE)
    return out


def run(home, settings_file, nonce, out_path, net_targets=None, security_bin=DEFAULT_SECURITY):
    checks = {k: "error" for k in CHECKS}
    counts = {}
    restore_failed = False
    deny, allowed_domains = [], []
    try:
        with open(settings_file, encoding="utf-8") as f:
            s = json.load(f)
        deny = unique_paths(s["sandbox"]["filesystem"]["denyWrite"])
        allowed_domains = [d for d in s["sandbox"]["network"].get("allowedDomains", []) if isinstance(d, str)]
    except Exception:  # noqa: BLE001（読めなければ write・parent_mv・case は error のまま）
        deny = []
    budget = Budget(LITTER_BUDGET)
    try:
        if deny:
            # 順番に意味がある：write が通ってしまった（囲いが効いていない）日は、名前を変えて戻す parent_mv と case をやらない（skipped）
            checks["write"], counts["write"] = check_write(deny, nonce, budget)
            if checks["write"] == "blocked":
                checks["parent_mv"], restore_failed = check_parent_mv(home, deny, nonce)
                checks["case"] = check_case(deny, nonce, budget)
            else:
                checks["parent_mv"] = checks["case"] = "skipped"
    except Exception:  # noqa: BLE001
        pass
    for key, fn in (("network", lambda: check_network(net_targets or DEFAULT_NET_TARGETS, allowed_domains)),
                    ("keychain", lambda: check_keychain(security_bin, keychain_services(home))),
                    ("env_url", check_env)):
        try:
            checks[key] = fn()
        except Exception:  # noqa: BLE001
            checks[key] = "error"
    result = {"v": VERSION, "nonce": nonce, "date": date.today().isoformat(), "checks": checks,
              "counts": counts, "litter": (PROBE_PREFIX + "*") if budget.left < LITTER_BUDGET else None,
              "restore_failed": restore_failed}
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, out_path)
    return result


def judge(path, nonce):
    """結果のファイルを読んで判定する。返り値 (全部止まったか, 理由の1行)。理由は項目名と状態だけ（パス・URL を入れない）"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return False, "結果が無い（カナリアが動かなかった）"
    except Exception:  # noqa: BLE001
        return False, "結果の形が違う"
    if not isinstance(data, dict) or data.get("v") != VERSION or not isinstance(data.get("checks"), dict):
        return False, "結果の形が違う"
    if data.get("nonce") != nonce:
        return False, "結果が今回のものではない"
    checks = data["checks"]
    bad = []
    for k in CHECKS:
        v = checks.get(k)
        if v != "blocked":
            bad.append("%s=%s" % (k, v if v in ("leaked", "error", "skipped") else "none"))
    if data.get("restore_failed") is True:
        bad.append("parent_mv_restore_failed")
    if bad:
        return False, ",".join(bad)
    return True, ""


def main(argv=None):
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--home")
    ap.add_argument("--settings-file")
    ap.add_argument("--nonce")
    ap.add_argument("--out")
    ap.add_argument("--net-target", action="append", default=[])
    ap.add_argument("--security-bin", default=DEFAULT_SECURITY)
    ap.add_argument("--judge")
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        sys.stderr.write("sandbox_canary: 引数が正しくありません\n")
        return 64
    if a.judge:
        ok, why = judge(a.judge, a.nonce or "")
        if not ok:
            sys.stdout.write(why + "\n")
        return 0 if ok else 1
    if not (a.home and a.settings_file and a.nonce and a.out):
        sys.stderr.write("sandbox_canary: --home --settings-file --nonce --out が要ります\n")
        return 64
    try:
        targets = [_parse_target(t) for t in a.net_target] or None
        run(a.home, a.settings_file, a.nonce, a.out, targets, a.security_bin)
    except Exception as e:  # noqa: BLE001（理由の文面にパスが入ることがあるので型の名前だけ）
        sys.stderr.write("sandbox_canary: 結果を書けませんでした（%s）\n" % type(e).__name__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
