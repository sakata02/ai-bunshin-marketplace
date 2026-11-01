#!/usr/bin/env python3
"""初回セットアップ専用：本人のフォルダの .claude/settings.json に NG の権限設定（deny）を足す。

- 既存の設定（プラグインの有効化 enabledPlugins など）は残し、deny だけを足す（上書きしない）
- 設定/config.json がすでにある（＝セットアップ済み）フォルダでは何もしない。権限の変更は本人の仕事（NG）なので、
  AI がこのスクリプトを使えるのは、本人の了承を得た初回セットアップの中だけ
使い方：python3 "<プラグイン>/scripts/setup_settings.py" "<本人のフォルダ>" [--add-dir <別フォルダのリポジトリ> ...]
（--add-dir：git / speckit モードで、本人のフォルダの外にあるリポジトリを編集できるようにする＝permissions.additionalDirectories）
"""
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = PLUGIN_ROOT / "templates" / ".claude" / "settings.json"


def main():
    args = sys.argv[1:]
    add_dirs = [args[i + 1] for i, a in enumerate(args) if a == "--add-dir" and i + 1 < len(args)]
    rest = [a for i, a in enumerate(args) if a != "--add-dir" and (i == 0 or args[i - 1] != "--add-dir")]
    home = Path(rest[0] if rest else ".").resolve()
    if (home / "設定" / "config.json").exists():
        print("セットアップ済みのフォルダなので何もしません（権限の変更は本人が行ってください）", file=sys.stderr)
        return 1
    tpl = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    path = home / ".claude" / "settings.json"
    cur = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    deny = cur.setdefault("permissions", {}).setdefault("deny", [])
    added = [r for r in tpl["permissions"]["deny"] if r not in deny]
    deny.extend(added)
    extra = cur["permissions"].setdefault("additionalDirectories", [])
    for d in add_dirs:
        d = str(Path(d).expanduser().resolve())
        if d not in extra:
            extra.append(d)
    if not extra:
        cur["permissions"].pop("additionalDirectories")
    for k, v in tpl.get("enabledPlugins", {}).items():
        cur.setdefault("enabledPlugins", {}).setdefault(k, v)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cur, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{path} に NG の権限設定を {len(added)} 件足しました（既存の設定は残しています）"
          + (f"。編集を許可したフォルダ：{', '.join(extra)}" if extra else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
