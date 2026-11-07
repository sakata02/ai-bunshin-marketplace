#!/usr/bin/env python3
"""自動実行の囲い（sandbox）のカナリア：囲いが本当に効いているかを、Python を許す前に確かめる（T119 G4a・G4c。決定 S05・S06・S15・S16・S19〜S23）。

囲いは Claude Code が claude の中の Bash に掛けるもので、外から同じ囲いを作って試すことはできない。
そこで daily_cycle.sh が、本番と同じ --settings と、このスクリプトだけを許す --allowedTools で短い claude -p を1回動かし、
その中のサンドボックスの下でこのスクリプトを動かす。囲いの外の daily_cycle.sh が `--judge` で結果を読んで、6つ全部が blocked のときだけ Python を許す。

点検の claude が結果を偽造・左右できないようにする作り（G4c）：
  - 呼び方は `python3 -I sandbox_canary.py --nonce <この実行の ID>` だけ。ほかの引数（--security-bin・--net-target・--settings-file・--home・--out など）は受け付けない（終了コード64）
  - 設定（--settings と同じ JSON）・本人のフォルダ・結果の書き先・確かめ先の一覧・キーチェーンの名前は、daily_cycle.sh が囲いの外で
    <ユーザーのホーム>/.ai-bunshin/canary/<nonce>.json に置く（ここは囲いの守る先。囲いの中から書けない）。点検の道具はそこから読む
  - 結果には HMAC-SHA256 の印を付ける。鍵は daily_cycle.sh が毎回作り、点検の claude を起動する1行の環境変数 AI_BUNSHIN_CANARY_KEY にだけ渡す。
    --judge は同じ鍵を環境変数で受けて確かめる。印の無い・違う・鍵が無い結果は通らない
  - 結果に「設定の中身の sha256」と「write で確かめた数」を入れ、--judge が囲いの外の値（daily_cycle.sh が計算）と比べる
  - テストの差し替え（確かめ先・security の場所）は import でだけ（prepare・execute の引数）。環境変数・コマンドの引数では差し替えられない

使い方：
  python3 -I sandbox_canary.py --nonce <この実行の ID>          （点検。鍵は環境変数 AI_BUNSHIN_CANARY_KEY）
  python3 -I sandbox_canary.py --judge <結果のファイル> --nonce <ID> --config-sha256 <囲いの外で計算した値> --min-writes <下限>   （囲いの外だけで使う。鍵は環境変数）
  → 判定。全部止まっていれば何も出さず終了コード0。そうでなければ、止まらなかった項目名を1行（write=leaked,network=error のように。パス・URL を出さない）出して終了コード1

確かめる6つ（どれも、実物を壊さない形。止まれば blocked、通ってしまえば leaked、確かめられなければ error、前の確かめで通ったためやらなければ skipped）：
  write      守る先（settings の denyWrite）への書き込み。フォルダには新しい空のファイルを作ろうとし、ファイルには書き込み用に開くだけ（1バイトも書かない）。
             通ってしまったら消さずに残して記録する（消すのは NG。残すのは最大2つ。名前は .ai-bunshin-canary-<nonce>-<番号>）
  parent_mv  目印フォルダ（<本人のフォルダ>/.ai-bunshin-canary-dir。守っていない親）の名前の付け替えと、守る先 guard（.ai-bunshin-canary-dir/guard）を外へ出す付け替え。
             どちらも daily_cycle.sh が囲いの外で前もって作る。本物の scripts/・.git は付け替えない。
             通ってしまったら、すぐ元の名前に戻す（戻せなければ restore_failed を記録）
  case       大文字・小文字を変えたパス（CLAUDE.md → claude.md）への書き込み。write と同じ形で確かめる。大文字・小文字を区別するディスクでは別のファイルなので blocked
  network    外への通信：直接つなぐ（1.1.1.1:443）が EPERM・EACCES で止まる（囲いが止めた）ことと、環境のプロキシに CONNECT を頼んで（許可していないドメイン宛て）通らないこと。
             拒否・時間切れ・届かないは、囲いが止めたとは言えないので error
  keychain   security find-generic-password でキーチェーンの項目を見つけられるか（中身は出さない。見つかったかどうかだけ）。
             確かめる名前は、daily_cycle.sh が囲いの外で「項目がある」と確かめたものだけ（0以外が「囲いに止められた」と言えるように）。1つも無い日は error
  env_url    環境に AI_BUNSHIN_CALENDAR_URL があるか
"""
import argparse
import errno
import hashlib
import hmac
import json
import os
import re
import socket
import subprocess
import sys
from datetime import date
from urllib.parse import urlsplit

sys.dont_write_bytecode = True

VERSION = 2
CHECKS = ("write", "parent_mv", "case", "network", "keychain", "env_url")
PROBE_PREFIX = ".ai-bunshin-canary-"
MAX_PROBES = 80            # write の確かめる先の上限
LITTER_BUDGET = 2          # 囲いが効いていないときに作ってしまう空のファイルの上限（write と case を合わせて）
MARKER_DIR = ".ai-bunshin-canary-dir"   # 点検用の目印フォルダ（守っていない親。守る先は中の guard だけ）
GUARD_DIR = "guard"                     # 守る先の一覧 protected_paths.json の S23-canary-guard（.ai-bunshin-canary-dir/guard）
NET_TIMEOUT = 3
KEYCHAIN_TIMEOUT = 10
DEFAULT_NET_TARGETS = [("1.1.1.1", 443)]
DEFAULT_SECURITY = "/usr/bin/security"
CLAUDE_CREDENTIAL_SERVICE = "Claude Code-credentials"   # Claude Code 自身の認証情報。どの Mac にもあるとは限らない（無ければ確かめられない）
URL_ENV = "AI_BUNSHIN_CALENDAR_URL"
KEY_ENV = "AI_BUNSHIN_CANARY_KEY"
MIN_KEY_LEN = 32
PROXY_ENVS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")
DENIED_ERRNOS = (errno.EPERM, errno.EACCES, errno.EROFS)   # 囲い（または読み取り専用）に止められた
NET_DENIED_ERRNOS = (errno.EPERM, errno.EACCES)            # 通信：囲いが止めたと言えるのはこの2つだけ（拒否・時間切れ・届かないは含めない）
NONCE_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
CONFIG_PARTS = (".ai-bunshin", "canary")   # <ユーザーのホーム>/.ai-bunshin/canary/<nonce>.json（囲いの守る先 .ai-bunshin の中）


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


def expected_write_count(deny_write):
    """write で確かめるはずの数＝今ある守る先（フォルダ・ファイル）の数（上限 MAX_PROBES）。囲いの外で数えて、--judge の下限にする"""
    n = sum(1 for p in unique_paths(deny_write) if os.path.isdir(p) or os.path.isfile(p))
    return min(n, MAX_PROBES)


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
    """守っていない親（<本人のフォルダ>/.ai-bunshin-canary-dir）の付け替えと、守る先 guard（その中）を外へ出す付け替えが止まるかを確かめる。
    親は守る先ではない（守る先の一覧に入っているのは中の guard だけ）。守る先の「親」を付け替えて guard ごと逃げられないか、が破られ方（S15①・S23）。
    どちらも daily_cycle.sh が囲いの外で前もって作る。本物の scripts/・.git などは付け替えない（囲いが効いていない日に、戻せない危険を作らないため）。
    通ってしまったら、すぐ元の名前に戻す（目印の空のフォルダなので、戻せなくても害は小さい。戻せなければ restore_failed）。
    返り値：(状態, 戻せなかったか)。目印フォルダ・guard が無い（確かめられない）ときは error"""
    home_c = os.path.realpath(home)
    marker = os.path.join(home_c, MARKER_DIR)
    guard = os.path.join(marker, GUARD_DIR)
    if not os.path.isdir(marker) or os.path.islink(marker) or not os.path.isdir(guard) or os.path.islink(guard):
        return "error", False
    results = []
    # (a) 守っていない親ごと
    moved = marker + ".moved-" + nonce
    r = _try_rename(marker, moved)
    if r == "moved":
        try:
            os.rename(moved, marker)
        except OSError:
            return "leaked", True
        return "leaked", False
    results.append(r)
    # (b) 守る先 guard を、目印フォルダの外（本人のフォルダの直下）へ
    out = os.path.join(home_c, GUARD_DIR + PROBE_PREFIX + nonce)
    r = _try_rename(guard, out)
    if r == "moved":
        try:
            os.rename(out, guard)
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


def check_network(targets, avoid_hosts=()):
    """直接の接続：通れば leaked。全部の確かめ先で EPERM・EACCES（囲いが止めた）のときだけ blocked。拒否・時間切れ・届かない（囲いが止めたとは言えない）は error。
    そのうえで、環境のプロキシに許可していないドメインへの CONNECT を頼む（2xx が返れば leaked）"""
    targets = list(targets)
    if not targets:
        return "error"
    denied = 0
    for host, port in targets:
        try:
            s = socket.create_connection((host, port), timeout=NET_TIMEOUT)
            s.close()
            return "leaked"
        except OSError as e:
            if e.errno in NET_DENIED_ERRNOS:
                denied += 1
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
    return "blocked" if denied == len(targets) else "error"


def check_keychain(security_bin, services):
    """項目が見つかったか（終了コード0）だけを見る。中身（-w・-g）は頼まず、出力は捨てる。
    services は、囲いの外で「項目がある」と確かめた名前だけ（だから、囲いの中で0以外なら囲いが止めたと言える）。1つも無い日は確かめられない（error）"""
    services = [s for s in services if isinstance(s, str) and s]
    if not services:
        return "error"
    env = {k: v for k, v in os.environ.items() if k != KEY_ENV}
    for svc in services:
        try:
            r = subprocess.run([security_bin, "find-generic-password", "-s", svc],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=KEYCHAIN_TIMEOUT, env=env)
        except (subprocess.TimeoutExpired, OSError):
            return "error"
        if r.returncode == 0:
            return "leaked"
    return "blocked"


def check_env():
    return "leaked" if URL_ENV in os.environ else "blocked"


def keychain_services(home):
    """確かめたい項目の名前：config のカレンダー（ics）のキーチェーンの名前と、Claude Code の認証情報"""
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


def existing_keychain_services(home, security_bin="security"):
    """囲いの外で使う：keychain_services のうち、キーチェーンに項目がある名前だけ（-w なし。出力は捨てる）。項目が無い・確かめられない名前は入れない"""
    out = []
    for svc in keychain_services(home):
        try:
            r = subprocess.run([security_bin, "find-generic-password", "-s", svc],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=KEYCHAIN_TIMEOUT)
        except (subprocess.TimeoutExpired, OSError):
            continue
        if r.returncode == 0:
            out.append(svc)
    return out


# ---------- 設定のファイル（囲いの外で置く）・結果の印 ----------

def config_path(nonce, user_home=None):
    return os.path.join(user_home or os.path.expanduser("~"), *CONFIG_PARTS, nonce + ".json")


def prepare(home, settings_text, nonce, out_path, keychain_names, net_targets=None, user_home=None):
    """囲いの外で使う（点検の claude を起動する前に daily_cycle.sh が呼ぶ。点検の claude の引数からは呼べない）。
    設定のファイル（<ユーザーのホーム>/.ai-bunshin/canary/<nonce>.json）を置き、(その中身の sha256, write で確かめる数の下限, 置いた場所) を返す"""
    if not NONCE_RE.match(nonce):
        raise ValueError("nonce")
    settings = json.loads(settings_text)
    deny = unique_paths(settings["sandbox"]["filesystem"]["denyWrite"])
    cfg = {"v": VERSION, "nonce": nonce, "home": home, "out": out_path, "settings": settings,
           "net_targets": [list(t) for t in (net_targets or DEFAULT_NET_TARGETS)],
           "keychain_services": [s for s in keychain_names if isinstance(s, str) and s]}
    body = (json.dumps(cfg, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    path = config_path(nonce, user_home)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(body)
    os.replace(tmp, path)
    return hashlib.sha256(body).hexdigest(), expected_write_count(deny), path


def _canonical(result):
    return json.dumps({k: v for k, v in result.items() if k != "mac"}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign(result, key):
    return hmac.new(key.encode("utf-8"), _canonical(result), hashlib.sha256).hexdigest()


def execute(cfg_file, nonce, key, security_bin=DEFAULT_SECURITY):
    """設定のファイル cfg_file を読んで6つを確かめ、印つきの結果を cfg の out に書く。返り値：結果。
    テストはここ（import）から、security の場所を差し替える。確かめ先・設定は prepare の引数で決める"""
    with open(cfg_file, "rb") as f:
        body = f.read()
    cfg = json.loads(body.decode("utf-8"))
    if not isinstance(cfg, dict) or cfg.get("v") != VERSION or cfg.get("nonce") != nonce:
        raise ValueError("config")
    home, out_path = cfg["home"], cfg["out"]
    checks = {k: "error" for k in CHECKS}
    counts = {}
    restore_failed = False
    deny, allowed_domains = [], []
    try:
        s = cfg["settings"]
        deny = unique_paths(s["sandbox"]["filesystem"]["denyWrite"])
        allowed_domains = [d for d in s["sandbox"]["network"].get("allowedDomains", []) if isinstance(d, str)]
    except Exception:  # noqa: BLE001（読めなければ write・parent_mv・case は error のまま）
        deny = []
    try:
        targets = [(str(h), int(p)) for h, p in cfg.get("net_targets", [])]
    except Exception:  # noqa: BLE001
        targets = []
    services = cfg.get("keychain_services", [])
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
    for k, fn in (("network", lambda: check_network(targets, allowed_domains)),
                  ("keychain", lambda: check_keychain(security_bin, services)),
                  ("env_url", check_env)):
        try:
            checks[k] = fn()
        except Exception:  # noqa: BLE001
            checks[k] = "error"
    result = {"v": VERSION, "nonce": nonce, "date": date.today().isoformat(), "checks": checks,
              "counts": counts, "litter": (PROBE_PREFIX + "*") if budget.left < LITTER_BUDGET else None,
              "restore_failed": restore_failed, "config_sha256": hashlib.sha256(body).hexdigest()}
    result["mac"] = sign(result, key)
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, out_path)
    return result


def judge(path, nonce, key, expected_sha, min_writes):
    """結果のファイルを読んで判定する。返り値 (全部止まったか, 理由の1行)。理由は項目名と状態だけ（パス・URL を入れない）。
    通る条件：形が正しい・鍵で付けた印が合う・今回の nonce・設定の中身の sha256 が囲いの外の値と同じ・write で確かめた数が下限以上・6項目すべて blocked"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return False, "結果が無い（カナリアが動かなかった）"
    except Exception:  # noqa: BLE001
        return False, "結果の形が違う"
    if not isinstance(data, dict) or data.get("v") != VERSION or not isinstance(data.get("checks"), dict):
        return False, "結果の形が違う"
    if not isinstance(key, str) or len(key) < MIN_KEY_LEN:
        return False, "鍵が無い"
    mac = data.get("mac")
    try:
        mac_ok = isinstance(mac, str) and hmac.compare_digest(mac, sign(data, key))
    except Exception:  # noqa: BLE001
        mac_ok = False
    if not mac_ok:
        return False, "結果の印が正しくない"
    if data.get("nonce") != nonce:
        return False, "結果が今回のものではない"
    if not isinstance(expected_sha, str) or not expected_sha or data.get("config_sha256") != expected_sha:
        return False, "設定の中身が違う"
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
    # 全部 blocked でも、write で確かめた数が囲いの外で数えた下限に届かなければ通さない（守る先を確かめずに blocked と書く偽造・手抜き）
    if isinstance(min_writes, bool) or not isinstance(min_writes, int) or min_writes < 1:
        return False, "確かめる守る先が1つも無い"
    counts = data.get("counts")
    n = counts.get("write") if isinstance(counts, dict) else None
    if isinstance(n, bool) or not isinstance(n, int) or n < min_writes:
        return False, "write の確かめた数が足りない"
    return True, ""


class _Parser(argparse.ArgumentParser):
    def error(self, message):   # 値（鍵・パスを含むかもしれない）を標準エラーに出さない
        raise SystemExit(64)


def main(argv=None):
    ap = _Parser(add_help=False, allow_abbrev=False)
    ap.add_argument("--nonce")
    ap.add_argument("--judge")
    ap.add_argument("--config-sha256")
    ap.add_argument("--min-writes")
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        sys.stderr.write("sandbox_canary: 引数が正しくありません\n")
        return 64
    key = os.environ.pop(KEY_ENV, None)
    if a.judge:
        if not (a.nonce and a.config_sha256 and a.min_writes and a.min_writes.isdigit()):
            sys.stderr.write("sandbox_canary: 引数が正しくありません\n")
            return 64
        ok, why = judge(a.judge, a.nonce, key, a.config_sha256, int(a.min_writes))
        if not ok:
            sys.stdout.write(why + "\n")
        return 0 if ok else 1
    # 点検：引数は --nonce だけ
    if a.config_sha256 is not None or a.min_writes is not None or not a.nonce or not NONCE_RE.match(a.nonce):
        sys.stderr.write("sandbox_canary: 引数が正しくありません\n")
        return 64
    if not isinstance(key, str) or len(key) < MIN_KEY_LEN:
        sys.stderr.write("sandbox_canary: 鍵が渡されていません\n")
        return 2
    try:
        execute(config_path(a.nonce), a.nonce, key)
    except Exception as e:  # noqa: BLE001（理由の文面にパスが入ることがあるので型の名前だけ）
        sys.stderr.write("sandbox_canary: 結果を書けませんでした（%s）\n" % type(e).__name__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
