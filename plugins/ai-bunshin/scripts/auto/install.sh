#!/bin/zsh
# 自動実行（launchd）を登録する。本人が自分のフォルダで実行する：
#   zsh "<プラグインの場所>/scripts/auto/install.sh" ~/workspace/<本人のフォルダ>
# やること：
#   1. 本人のフォルダに scripts/auto/run.sh（launchd が呼ぶ入口）を作る
#   2. 設定/config.json の時刻で ~/Library/LaunchAgents/com.ai-bunshin.daily-{plan,review}.plist を作り、登録し直す
# Mac 専用。Windows・Linux では何もしない
set -e
if [ "$(uname)" != "Darwin" ]; then
  echo "自動実行は Mac 専用です。手動で /ai-bunshin:daily-plan などを使ってください"; exit 0
fi
HOME_DIR="${1:A}"
[ -f "$HOME_DIR/設定/config.json" ] || { echo "本人のフォルダ（設定/config.json がある場所）を指定してください: $1"; exit 1; }
PLUGIN_ROOT="${0:A:h:h:h}"
read PLAN_H PLAN_M REVIEW_H REVIEW_M <<< "$(python3 - "$HOME_DIR/設定/config.json" <<'PY'
import json, sys
c = json.load(open(sys.argv[1])).get("schedule", {})
p = c.get("plan", "09:00").split(":"); r = c.get("review", "17:00").split(":")
print(int(p[0]), int(p[1]), int(r[0]), int(r[1]))
PY
)"
CONF_PATH=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("path",""))' "$HOME_DIR/設定/config.json")
RUN_PATH="${CONF_PATH:-$PATH}"

mkdir -p "$HOME_DIR/scripts/auto/logs"
cat > "$HOME_DIR/scripts/auto/run.sh" <<RUN
#!/bin/zsh
# launchd から呼ばれる入口（install.sh が作成。手で直さず install.sh を実行し直す）
export PATH="$RUN_PATH"
export AI_BUNSHIN_HOME="$HOME_DIR"
# プラグインの場所：Claude Code が実際に読み込んでいる場所（installed_plugins.json の installPath）。更新で変わるので毎回調べる
PR=\$(python3 -c 'import json,os,sys
d=json.load(open(os.path.expanduser("~/.claude/plugins/installed_plugins.json"))).get("plugins",{})
c=[e for k,v in d.items() if k.startswith("ai-bunshin@") for e in v if e.get("projectPath") in (sys.argv[1],None)]
print(c[-1]["installPath"] if c else "")' "\$AI_BUNSHIN_HOME" 2>/dev/null)
[ -f "\$PR/scripts/auto/daily_cycle.sh" ] || PR="$PLUGIN_ROOT"
exec /bin/zsh "\${PR%/}/scripts/auto/daily_cycle.sh" "\$1"
RUN

for spec in "plan $PLAN_H $PLAN_M" "review $REVIEW_H $REVIEW_M"; do
  set -- ${=spec}
  PL="$HOME/Library/LaunchAgents/com.ai-bunshin.daily-$1.plist"
  cat > "$PL" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.ai-bunshin.daily-$1</string>
  <key>ProgramArguments</key>
  <array><string>/bin/zsh</string><string>$HOME_DIR/scripts/auto/run.sh</string><string>$1</string></array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>$2</integer><key>Minute</key><integer>$3</integer></dict>
  <key>StandardOutPath</key><string>$HOME_DIR/scripts/auto/logs/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$HOME_DIR/scripts/auto/logs/launchd.err.log</string>
</dict>
</plist>
PL
  launchctl unload "$PL" 2>/dev/null || true
  launchctl load "$PL"
done
# プラグイン化する前の旧い登録名が残っていれば外す（ファイルは消さずに .old にする）
for old in ~/Library/LaunchAgents/com.davidharuka.daily-*.plist(N); do
  launchctl unload "$old" 2>/dev/null || true
  mv "$old" "$old.old"
done
echo "登録しました：計画 ${PLAN_H}:$(printf %02d $PLAN_M)（続けて実行）／振り返り ${REVIEW_H}:$(printf %02d $REVIEW_M)"
launchctl list | grep ai-bunshin || true
