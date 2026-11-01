#!/usr/bin/env bash
# Python 3 を探して、スクリプトを起動する（hook から呼ぶ入口。Mac・Linux・Windows の Git Bash 共通）
# 使い方：bash "${CLAUDE_PLUGIN_ROOT}/scripts/run_py.sh" <スクリプト> <引数…>
#
# なぜ：Windows の python3 は、Microsoft Store を開くだけの偽物のことがあり、名前があっても動かない。
#       py には -3 を付けないと Python 3 とは限らない。名前だけで選ばず、実際に動かして Python 3 と確かめてから使う。
# 順番：python3 → python → py -3
# 起動：PYTHONUTF8=1 を付けて exec で置き換える（標準入力・終了コードはそのまま。ng_guard.py の終了コード 2 も変わらない）
# 見つからないとき：標準エラーに案内を書いて 127 で終わる（hook では 2 は「止める」の意味なので、2 は返さない）

# Python 3 か確かめる（標準入力を読ませない：hook の JSON を食べないように /dev/null にする）
is_py3() {
    [ "$("$@" -c 'import sys; print(sys.version_info[0])' </dev/null 2>/dev/null)" = "3" ]
}

if is_py3 python3; then
    PY=(python3)
elif is_py3 python; then
    PY=(python)
elif is_py3 py -3; then
    PY=(py -3)
else
    echo "Python 3 が見つかりませんでした（python3・python・py -3 を試しました）。Python 3 を入れてから Claude を開き直してください（Windows は https://www.python.org/downloads/ 。入れるとき「Add python.exe to PATH」にチェック）。" >&2
    exit 127
fi

export PYTHONUTF8=1
exec "${PY[@]}" "$@"
