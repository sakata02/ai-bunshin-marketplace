#!/usr/bin/env python3
"""プラグインの場所：「Claude Code が実際に読み込んでいる場所」を決める（beta.10）。

自動実行の入口 run.sh（install.sh が作る）と daily_cycle.sh の両方が、この1か所の決め方を使う。
スキルは `"${CLAUDE_PLUGIN_ROOT}/scripts/…"`（＝Claude Code が実際に読む場所）でコマンドを打つので、
自動実行の許可（--allowedTools）もその場所の道で作らないと、許可に当たらず、`claude -p` は許可待ちで止まる。

決め方（上から。最初に決まったもの）：
  (a) installed_plugins.json に、本人のフォルダ（projectPath。user スコープで projectPath が無いものも）の
      <プラグイン名>@<マーケットプレイス> があり、known_marketplaces.json でそのマーケットプレイスの
      source が "directory" なら、元のフォルダの中：<path>/.claude-plugin/marketplace.json に、そのプラグインの
      source（"./plugins/…" のような文字列）があればそれ、無ければ <path>/plugins/<プラグイン名>
      （そこに scripts/auto/daily_cycle.sh があり、元のフォルダの中に収まるときだけ。"../" で外を指すものは使わない）
  (b) そうでなければ（github など）、installed_plugins.json の installPath（そこに daily_cycle.sh があるときだけ）
  (c) どちらも無ければ、空を返す（呼ぶ側が今まで通り止めて知らせる）

使い方：python3 -I plugin_location.py --home <本人のフォルダ> [--claude-dir <~/.claude>] [--plugin ai-bunshin]
  標準出力は2行：1行目＝決めた場所（決まらなければ空）、2行目＝何で決めたか（directory-marketplace／install-path／none）
  JSON が無い・壊れているときも落ちない（終了コード0で、決まらなければ1行目が空）。読むだけで、何も書かない
"""
import json
import os
import sys

CYCLE = os.path.join("scripts", "auto", "daily_cycle.sh")


def _load(path):
    """JSON を読む。無い・壊れている・形が違うときは None（落ちない）"""
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _real(p):
    try:
        return os.path.realpath(p)
    except (OSError, ValueError):
        return p


def _inside(path, base):
    """path（実体）が base（実体）の中に収まるか"""
    try:
        rp, rb = _real(path), _real(base)
        return os.path.commonpath([rp, rb]) == rb
    except ValueError:
        return False


def _has_cycle(root):
    try:
        return bool(root) and os.path.isfile(os.path.join(root, CYCLE))
    except (OSError, ValueError):
        return False


def _installed_entry(installed, plugin, home):
    """installed_plugins.json から、このプラグインで本人のフォルダのものの最後の1件を (マーケットプレイス名, 項目) で返す。
    今までの run.sh と同じ選び方（projectPath が本人のフォルダか、無いもの。最後の1件）。本人のフォルダは、そのままの道と実体の両方で比べる"""
    plugins = installed.get("plugins") if isinstance(installed, dict) else None
    if not isinstance(plugins, dict):
        return None
    homes = {home, _real(home)}
    found = None
    for key, entries in plugins.items():
        if not isinstance(key, str) or not key.startswith(plugin + "@") or not isinstance(entries, list):
            continue
        for e in entries:
            if not isinstance(e, dict):
                continue
            pp = e.get("projectPath")
            if pp is None or (isinstance(pp, str) and (pp in homes or _real(pp) in homes)):
                found = (key.split("@", 1)[1], e)
    return found


def _directory_marketplace_root(known, mkt, plugin):
    """(a)：マーケットプレイスが directory のときの、プラグインの元の場所（使えるときだけ。無ければ None）"""
    m = known.get(mkt) if isinstance(known, dict) else None
    src = m.get("source") if isinstance(m, dict) else None
    if not isinstance(src, dict) or src.get("source") != "directory":
        return None
    base = src.get("path")
    if not isinstance(base, str) or not os.path.isabs(base):
        return None
    candidate = os.path.join(base, "plugins", plugin)
    mj = _load(os.path.join(base, ".claude-plugin", "marketplace.json"))
    for p in (mj.get("plugins") if isinstance(mj, dict) else None) or []:
        if isinstance(p, dict) and p.get("name") == plugin:
            s = p.get("source")
            if isinstance(s, str) and s and "://" not in s and not os.path.isabs(s):
                candidate = os.path.normpath(os.path.join(base, s))
            elif s is not None:
                return None   # 元のフォルダの中の道ではない（github など）。(b) に任せる
            break
    if not _inside(candidate, base):
        return None   # "../" などで元のフォルダの外を指している。(b) に任せる
    return candidate if _has_cycle(candidate) else None


def resolve(home, claude_dir=None, plugin="ai-bunshin"):
    """(場所, 何で決めたか) を返す。決まらなければ ("", "none")。落ちない"""
    try:
        claude_dir = claude_dir or os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
        pdir = os.path.join(claude_dir, "plugins")
        got = _installed_entry(_load(os.path.join(pdir, "installed_plugins.json")), plugin, home)
        if got is None:
            return "", "none"
        mkt, entry = got
        root = _directory_marketplace_root(_load(os.path.join(pdir, "known_marketplaces.json")), mkt, plugin)
        if root:
            return root, "directory-marketplace"
        ip = entry.get("installPath")
        if isinstance(ip, str) and _has_cycle(ip):
            return ip.rstrip("/") or ip, "install-path"
    except Exception:  # noqa: BLE001  どんな形の JSON でも、自動実行の入口は落とさない
        pass
    return "", "none"


def main(argv):
    opts = {"--home": None, "--claude-dir": None, "--plugin": "ai-bunshin"}
    i = 0
    while i < len(argv):
        if argv[i] in opts and i + 1 < len(argv):
            opts[argv[i]] = argv[i + 1]
            i += 2
        else:
            print("usage: plugin_location.py --home <本人のフォルダ> [--claude-dir DIR] [--plugin NAME]", file=sys.stderr)
            return 64
    if not opts["--home"]:
        print("usage: plugin_location.py --home <本人のフォルダ> [--claude-dir DIR] [--plugin NAME]", file=sys.stderr)
        return 64
    path, kind = resolve(opts["--home"], opts["--claude-dir"], opts["--plugin"])
    print(path)
    print(kind)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
