#!/bin/zsh
# 1日スプリントの自動実行（ai-bunshin プラグイン）
# 本人のフォルダの scripts/auto/run.sh（install.sh が作る）が、AI_BUNSHIN_HOME と PATH を決めてから呼ぶ
#   zsh daily_cycle.sh plan     # 9:00 プランニング（/ai-bunshin:daily-plan）→ 終わったら続けて実行（/ai-bunshin:daily-do）
#   zsh daily_cycle.sh do       # 実行だけ（手動で動かすとき）
#   zsh daily_cycle.sh review   # 17:00 振り返り（/ai-bunshin:daily-review）
# 止め方: launchctl unload ~/Library/LaunchAgents/com.ai-bunshin.daily-{plan,review}.plist

PHASE="$1"
case "$PHASE" in
  plan)   LABEL="プランニング"; SKILL="/ai-bunshin:daily-plan";   CTX="--plan-context" ;;
  do)     LABEL="実行";         SKILL="/ai-bunshin:daily-do";     CTX="--plan-context" ;;
  review) LABEL="振り返り";     SKILL="/ai-bunshin:daily-review"; CTX="--review-context" ;;
  *) echo "usage: daily_cycle.sh plan|do|review" >&2; exit 64 ;;
esac

ROOT="${AI_BUNSHIN_HOME:?本人のフォルダ（AI_BUNSHIN_HOME）が指定されていません。scripts/auto/run.sh から呼んでください}"
PLUGIN_ROOT="${0:A:h:h:h}"
DASH="$PLUGIN_ROOT/scripts/update_dashboard.py"
WATCH="$PLUGIN_ROOT/scripts/watch_check.py"          # 時間の上限・見張りの点検・「時間の上限で止めた」印（T095）
LIMITED="$PLUGIN_ROOT/scripts/auto/run_limited.py"   # claude を時間の上限つきで動かす（T095）
# 開発の置き場所のうち、本人のフォルダの外にあるリポジトリ（自動実行でも編集できるように --add-dir で渡す）
ADD_DIRS=(${(f)"$(python3 - "$ROOT" <<'PY'
import json, os, sys
from pathlib import Path
root = Path(sys.argv[1])
try:
    cfg = json.load(open(root / "設定" / "config.json", encoding="utf-8"))
except Exception:
    sys.exit(0)
for p in (cfg.get("dev") or {}).get("projects", []):
    d = Path(os.path.expanduser(p.get("path", "")))
    if p.get("path") and d.is_absolute() and root not in [d, *d.parents] and d.exists():
        print(d)
PY
)"})
ADD_DIR_ARGS=()
for d in ${(u)ADD_DIRS}; do ADD_DIR_ARGS+=(--add-dir "$d"); done
AI_NAME=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1], encoding="utf-8")).get("ai_name","AI"))' "$ROOT/設定/config.json" 2>/dev/null || echo AI)
LOG_DIR="$ROOT/scripts/auto/logs"
LOCK="$ROOT/scripts/auto/.lock"
TODAY=$(date +%Y%m%d)
LOG="$LOG_DIR/$TODAY.log"
mkdir -p "$LOG_DIR"
cd "$ROOT" || exit 1

# 段階ごとの「最後に成功した日時」（scripts/auto/last_success_<段階>.txt）。起動時のまとめが、2営業日以上なければ知らせる（update_dashboard.py。T073）
# 成功＝その段階が正常に終わったこと（営業日でない・計画や振り返りが済んでいて何もしなかった、も含む）。失敗・中止では書かない
mark_ok() {
  local f="$ROOT/scripts/auto/last_success_$1.txt"
  date '+%Y-%m-%d %H:%M' > "$f.tmp.$$" && mv -f "$f.tmp.$$" "$f"
}
# 「時間の上限で止めた」印を消すのは、Claude が実際に成功したときだけ（休日・済み・動きなしの SKIP では消さない。T095）
clear_mark() {
  python3 "$WATCH" clear-timeout "$ROOT/scripts/auto" "$1" 2>/dev/null
}
log() { echo "[$(date '+%H:%M:%S') $PHASE] $*" >> "$LOG"; }
notify() {
  local msg=${1//\"/\'}
  osascript -e "display notification \"$msg\" with title \"$AI_NAME\" subtitle \"$LABEL\""
}

# この実行の ID。ロックの3行目に書き、環境変数で claude にも渡す。
# 中の Claude（daily-plan/do/review）は、ロックの ID が自分の AI_BUNSHIN_AUTO_RUN と一致すれば「自分のロック」とみなし、
# 一致しなければ「ほかの実行が動いている」と判断して開かない（scripts/lock_check.py。T080）
RUN_ID="$$.$(date +%s)"
export AI_BUNSHIN_AUTO_RUN="$RUN_ID"
# ロックの形：1行目 PID／2行目 段階の名前と開始時刻／3行目 実行の ID
write_lock() { printf '%s\n%s\n%s\n' "$$" "${LABEL}（$(date '+%H:%M')開始）" "$RUN_ID" > "$LOCK"; }

log "開始"
# 共通ルールの写し（.claude/rules/ai-bunshin-common.md）を、Claude を起動する前に最新にする
# ふだんの出力は捨てる。写せなかった警告があるときだけ、その1行を $LOG に残す（朝に誰も見ていなくても後から分かるように）
SESSION_OUT=$(CLAUDE_PROJECT_DIR="$ROOT" python3 "$DASH" --session < /dev/null 2>> "$LOG")
COPY_WARN=$(printf '%s' "$SESSION_OUT" | grep -o '\[共通ルールの詳細ファイルを写せませんでした\][^\\]*' | head -1)
[ -n "$COPY_WARN" ] && log "警告 $COPY_WARN"

# 営業日でなければ何もしない（祝日は tasks.json の holidays を使う）
CONTEXT=$(python3 "$DASH" $CTX < /dev/null 2>> "$LOG")
HEAD=$(echo "$CONTEXT" | head -1)
log "$HEAD"
if [ "$HEAD" = "SKIP: 営業日ではない" ]; then
  mark_ok "$PHASE"
  exit 0
fi

# 前の段階が動いていれば待つ（計画・実行は計画の上限＝既定60分、振り返りは実行の終わりを待つため実行の上限＝既定180分。
# 時間の上限と同じ設定 auto.max_minutes から出す。T095）
# ロックの1行目は持ち主の PID。そのプロセスがもう無ければ（強制終了・停電など）古いロックとして無視する
MAX_WAIT=$(python3 "$WATCH" wait-minutes "$ROOT" "$PHASE" 2>/dev/null)
case "$MAX_WAIT" in (''|*[!0-9]*) MAX_WAIT=60; [ "$PHASE" = "review" ] && MAX_WAIT=180 ;; esac
WAITED=0
while [ -f "$LOCK" ]; do
  OWNER_PID=$(head -1 "$LOCK")
  if ! kill -0 "$OWNER_PID" 2>/dev/null; then
    log "古いロック（$(sed -n 2p "$LOCK")、PID $OWNER_PID は終了済み）を無視して続行"
    break
  fi
  if [ $WAITED -ge $MAX_WAIT ]; then
    log "前の段階（$(sed -n 2p "$LOCK")）が${MAX_WAIT}分たっても終わらないため中止"
    notify "前の段階が終わらないため、${LABEL}を中止しました（ログ参照）"
    exit 1
  fi
  [ $WAITED -eq 0 ] && log "前の段階（$(sed -n 2p "$LOCK")）の終了を待機"
  sleep 60
  WAITED=$((WAITED + 1))
done
# ここから先は、ロックを持つ。TERM・HUP・INT（launchd の停止・端末を閉じる・Ctrl-C）を受けたら、起動中の run_limited（claude とその孫）を止めて、
# ロックと一時ファイルを片づけ、ログに1行残して 128+シグナル番号で終わる（T095。mark_ok も印の書き込みもしない）。
# 先にトラップを置いてからロックを書くので、ロックを書いたあと・claude の起動前に届いても、ロックは残らない
LIMITED_PID=""   # 起動中の run_limited の PID（背景で動かして wait する）
LAUNCHING=0      # 1＝起動の直前から PID を控えるまで（この間に届いたときは $! を使う）
CUR_OUT=""       # 起動中の run_limited の出力の一時ファイル
on_stop() {
  local name=$1 num=$2 pid=$LIMITED_PID
  trap '' TERM HUP INT   # 片づけの最中に重ねて届いても、途中でやめない
  [ -z "$pid" ] && [ "$LAUNCHING" = 1 ] && pid=$!
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    kill -s TERM "$pid" 2>/dev/null   # run_limited は TERM・HUP・INT を同じに扱う（グループを止める → 猶予のあと KILL → 一時ファイルを消す）
    wait "$pid" 2>/dev/null           # 終わるまで待つ（最長でも猶予の2倍ほど）
  fi
  [ -n "$CUR_OUT" ] && rm -f "$CUR_OUT"
  log "シグナル（$name）を受けて止めました。claude を止め、ロックと一時ファイルを片づけました"
  exit $((128 + num))
}
trap 'rm -f "$LOCK"' EXIT
trap 'on_stop TERM 15' TERM
trap 'on_stop HUP 1' HUP
trap 'on_stop INT 2' INT
write_lock

# 待っている間に状況が変わることがあるので、もう一度確かめる
if [ $WAITED -gt 0 ]; then
  CONTEXT=$(python3 "$DASH" $CTX < /dev/null 2>> "$LOG")
  HEAD=$(echo "$CONTEXT" | head -1)
  log "待機後の判定：$HEAD"
fi

case "$PHASE:$HEAD" in
  "plan:SKIP: 今日の計画は作成済み")
    # 9時前に手動で計画した日は、まだ実行していなければ実行に入る
    mark_ok plan
    if [ "$(python3 "$DASH" --today-status < /dev/null 2>> "$LOG")" = "計画済み" ]; then
      log "計画は作成済み・未実行のため、実行に入る"
      PHASE="do"; LABEL="実行"; SKILL="/ai-bunshin:daily-do"
    else
      log "スキップ（計画・実行とも済み）"; exit 0
    fi ;;
  plan:SKIP:*)
    log "スキップ"; mark_ok plan; exit 0 ;;
  do:OPEN)
    # --plan-context が OPEN＝今日の計画がまだない
    log "今日の計画がないため実行しない"
    notify "今日の計画がないため、実行はしませんでした"
    mark_ok do
    exit 0 ;;
  "review:SKIP: 振り返り済み")
    log "今日の振り返りは済んでいる"; mark_ok review; exit 0 ;;
  review:SKIP:*)
    # 動きがない日は Claude を起動せず、1行だけ残す
    OUT=$(echo "$CONTEXT" | sed -n 's/^議事録の保存先: //p')
    mkdir -p "$(dirname "$OUT")"
    echo "# $(date +%Y-%m-%d) 振り返り — 開催なし（${HEAD#SKIP: }）" > "$OUT"
    # 今日、自動実行が時間の上限で止まっていたら、動きなしの日でもその事実を議事録に残す（印は消さない）
    STOPPED_LINE=$(python3 "$WATCH" timeout-line "$ROOT/scripts/auto" 2>/dev/null)
    [ -n "$STOPPED_LINE" ] && echo "$STOPPED_LINE" >> "$OUT"
    notify "今日は動きがなかったので、振り返りは開きませんでした"
    mark_ok review
    exit 0 ;;
  *:OPEN|do:*) ;;
  *)
    notify "${LABEL}の準備に失敗しました（scripts/auto/logs/$TODAY.log）"
    exit 1 ;;
esac

# 使える道具を絞る（送信・削除・設定やスクリプトの変更はできない）
TOOLS="Read,Write,Edit,Glob,Grep,Agent,SendMessage,Skill,Bash(python3 *update_dashboard.py*),Bash(python3 *lock_check.py*),Bash(python3 $DASH:*),Bash(python3 \"$DASH\":*)"
DENY="Bash(rm:*),Bash(curl:*),Edit(.claude/settings.json),Edit(scripts/**),Edit(/$PLUGIN_ROOT/**),Edit(設定/**),Edit(CLAUDE.md),Edit(.claude/**)"
if [ "$PHASE" = "do" ]; then
  TOOLS="$TOOLS,WebSearch,WebFetch"   # 実行では調査のためにネットを読むことだけ許可
else
  DENY="$DENY,WebFetch,WebSearch"
fi


# 見張りの自己点検（T095）：claude を起動する前に、今動いている見張り（このプラグインのコピー）が壊れていないかを確かめる。
# 壊れていれば起動しない（壊れた見張りの下では、中の Claude が何もできない／何でも通るため）
if ! GUARD_MSG=$(python3 "$WATCH" canary "$ROOT" 2>> "$LOG"); then
  log "見張りが壊れている可能性があるため、${LABEL}を始めませんでした（${GUARD_MSG}）"
  notify "見張りが壊れている可能性があるため、${LABEL}を始めませんでした（ログ参照）"
  exit 1
fi

# claude を時間の上限つきで動かす（T095）。結果は RESULT、終了コードは STATUS。
# 上限（auto.max_minutes。段階を決めたあとに決める）を超えたら、自分の起動した claude のグループだけを止めて exit 124
run_claude() {
  local skill="$1" out start broken
  LIMIT_MIN=$(python3 "$WATCH" minutes "$ROOT" "$PHASE" 2>/dev/null)
  case "$LIMIT_MIN" in (''|*[!0-9.]*) LIMIT_MIN=60 ;; esac
  out=$(mktemp "$LOG_DIR/.out.XXXXXX") || { log "一時ファイルを作れませんでした"; exit 1; }
  CUR_OUT="$out"
  start=$(date '+%Y-%m-%d %H:%M:%S')
  log "claude を起動（時間の上限 ${LIMIT_MIN}分）"
  # 背景で動かして wait する（前景だと、シグナルを受けても run_limited と claude が残るため）。
  # 受けたときは on_stop が run_limited を止めて終わるので、ここに戻るのは run_limited が自分で終わったときだけ（STATUS はその終了コード）
  LAUNCHING=1
  python3 "$LIMITED" --minutes "$LIMIT_MIN" --stdout "$out" -- claude -p "$skill" \
    --permission-mode acceptEdits \
    --model opus \
    --allowedTools "$TOOLS" \
    --disallowedTools "$DENY" \
    "${ADD_DIR_ARGS[@]}" \
    < /dev/null 2>> "$LOG" &
  LIMITED_PID=$!
  LAUNCHING=0
  wait "$LIMITED_PID"
  STATUS=$?
  LIMITED_PID=""
  RESULT=$(cat "$out" 2>/dev/null)
  rm -f "$out"
  CUR_OUT=""
  echo "$RESULT" >> "$LOG"
  log "終了 (exit=$STATUS)"
  # 補助：この実行の間に「見張りの入力を読めませんでした」が3回以上あれば、ログと通知に書く
  broken=$(python3 "$WATCH" broken-since "$ROOT" "$start" 2>/dev/null)
  if [ "${broken:-0}" -ge 3 ] 2>/dev/null; then
    log "警告：見張りが壊れている可能性（この実行の間に「見張りの入力を読めませんでした」が${broken}回）"
    notify "見張りが壊れている可能性があります（${broken}回）。ログを見てください"
  fi
  if [ $STATUS -eq 124 ]; then
    log "時間の上限（${LIMIT_MIN}分）で止めました。続きは会話で"
    python3 "$WATCH" mark-timeout "$ROOT/scripts/auto" "$PHASE" "$LIMIT_MIN" 2>> "$LOG"
    notify "時間の上限（${LIMIT_MIN}分）で${LABEL}を止めました。続きは会話で"
    exit 124
  fi
}

run_claude "$SKILL"

# 振り返りのあとに今日の議事録が無ければ、ログに警告を残す（スキルが SKIP などで何もせず終わったのが分かるように。T080）
if [ "$PHASE" = "review" ] && [ $STATUS -eq 0 ]; then
  MINUTES=$(echo "$CONTEXT" | sed -n 's/^議事録の保存先: //p')
  if [ -n "$MINUTES" ] && [ ! -f "$MINUTES" ]; then
    log "警告：振り返りの議事録（$MINUTES）が作られていない。スキルが何もせずに終わった可能性がある（出力：$(echo "$RESULT" | head -c 120 | tr '\n' ' ')）"
  fi
fi

if [ $STATUS -eq 0 ] && [ -n "$RESULT" ]; then
  mark_ok "$PHASE"
  clear_mark "$PHASE"
  notify "$(echo "$RESULT" | tail -3 | tr '\n' ' ')"
else
  notify "${LABEL}に失敗しました（scripts/auto/logs/$TODAY.log）"
  exit 1
fi

# プランニングが終わったら、そのまま実行に入る（ロックはこのプロセスが持ったまま）
if [ "$PHASE" = "plan" ]; then
  if ! python3 "$DASH" --plan-context < /dev/null 2>> "$LOG" | head -1 | grep -q "作成済み"; then
    log "今日の計画が作られていないため、実行には入らない"
    exit 0
  fi
  PHASE="do"; LABEL="実行"
  write_lock
  log "続けて実行を開始"
  notify "実行を始めました。その間、tasks.json の同時編集に注意してください"
  TOOLS="$TOOLS,WebSearch,WebFetch"
  DENY="${DENY/,WebFetch,WebSearch/}"
  run_claude "/ai-bunshin:daily-do"   # 上限（実行の分）はここで決め直す。計画で止まったら、ここには来ない
  if [ $STATUS -eq 0 ] && [ -n "$RESULT" ]; then
    mark_ok do
    clear_mark do
    notify "$(echo "$RESULT" | tail -3 | tr '\n' ' ')"
  else
    notify "実行に失敗しました（scripts/auto/logs/$TODAY.log）"
    exit 1
  fi
fi
