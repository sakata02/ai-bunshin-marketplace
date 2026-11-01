---
name: setup
description: AI 分身の初回セットアップ。新しく使い始める人に質問して、本人設定（CLAUDE.md）・設定/config.json・タスク表・ナレッジの最初のバージョンを作り、業務の棚卸しから最初に任せる仕事を提案する。起動時に「初回セットアップ」の案内が出たとき、「/ai-bunshin:setup」「セットアップして」と言われたときに使う。
---

# 初回セットアップ

> 部下の呼び出しは `subagent_type: ai-bunshin:<名前>`。資料は `buka-a`（作成）→ `buka-b`（検証）、開発は `dev-a`（部下C・実装）→ `dev-b`（部下D・検証）、分析は `analyst`（部下F）→ `buka-b`、研修は `trainer`（部下G）→ `buka-b`、デザインが入るタスク（`design: true`）は作る人の前に `design`（部下E）。本人設定の `team.off` の部下は使わない。スクリプトは `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/update_dashboard.py"`。雛形は `${CLAUDE_PLUGIN_ROOT}/templates/`。

相手は初めて使う人。**専門用語を避け、1回に2〜3問ずつ、選択肢を付けて聞く**（AskUserQuestion を使う）。答えにくい質問は「あとで」でよいと伝える。すでに `設定/config.json` がある場合は、上書きせずに「作り直しますか？」と確認する。

## 1. 環境の確認（足りなければ、ここで止めて入れ方を示す）

次を確かめ、結果を表で見せる。足りないものは **その場で止め**、本人がコピーして打てるコマンド（`! …` の形）を示す。入れ終わったら「/ai-bunshin:setup」で再開してもらう。

**コマンドの打ち方（最初に1回、この3行をそのまま本人に伝える）**
- `!` を頭に付けて、Claude の入力欄で打つと、そのコマンドがその場で実行され、結果が会話に出ます（例：`! python3 --version`）。`!` を付けないと、ふつうの文章として AI に送られます
- Claude を開く前に打つもの（フォルダを作る・プラグインを入れる）や、`!` が効かない画面のときは、`!` を付けずに、Mac は「ターミナル」、Windows は「PowerShell」（Git Bash でもよい）に打つ
- 例外：カレンダーの URL など **秘密の値を扱うコマンド** は、`!` を使わず、必ずターミナルで打つ（チャットに残さないため）

| 確認 | 方法 | 足りないとき |
|---|---|---|
| OS | `uname`（見つからないと出たら Windows とみなす） | Mac 以外は自動実行が使えない（手動で `/ai-bunshin:daily-plan` などを使う）と伝えて続ける。Windows では hook が `python3` を呼べるか（`python3 --version`）も確かめ、無ければ止めて Python の入れ方を案内する。Windows の朝・夕方の自動実行は、手順5の「Windows の人」を案内する |
| Python 3 | `python3 --version`（Windows で `python3` が無いときは `python --version`、`py -3 --version`） | `! brew install python`（Mac）など。**Windows** は https://www.python.org/downloads/ からインストーラを入れる（入れるとき「Add python.exe to PATH」にチェック）。入れたら Claude を開き直す |
| openpyxl | `python3 -c "import openpyxl"`（Windows は `py -3 -c "import openpyxl"`） | `! python3 -m pip install --user openpyxl`（Windows は `! py -3 -m pip install --user openpyxl`。`py` が無ければ `python -m pip …`）。「externally-managed-environment」と出たら、`! python3 -m venv ~/.ai-bunshin-venv && ~/.ai-bunshin-venv/bin/pip install openpyxl` を案内し、config.json の `path` の先頭に `~/.ai-bunshin-venv/bin`（絶対パス）を入れる（この venv の手順は Mac 向け。Windows で同じ表示が出たら、`bin` を `Scripts` に読み替えるのが基本だが【未確認】なので、本人と確かめながら進める） |
| 置き場所 | 今のフォルダが空か、仕事用のフォルダか | 新しいフォルダを作り（`mkdir -p ~/workspace/<名前>-ai`）、そこでプラグインを入れて（`cd ~/workspace/<名前>-ai && claude plugin install ai-bunshin@ai-bunshin-marketplace --scope project`）、そのフォルダで claude を起動し直すよう案内する。**Claude を開き直す前の作業なので、`!` を付けずにターミナル（Windows は PowerShell か Git Bash）で打ってもらう**。古い PowerShell は `&&` が使えないので、1行ずつに分ける。デスクトップアプリの人は、README の「A. デスクトップアプリ」（starter フォルダを開くだけ）の方が簡単 |

※ インストールのコマンドは AI が実行しない（NG）。本人に打ってもらう。

## 2. 質問（4回に分ける）

**1回目：基本**
1. お名前（タスク表に入る名前）と、呼ばれ方（例：「山田さん」）
2. AI の名前（例：「やまだ二号」。本人と紛らわしくない名前をすすめる）
3. 担当している部署・役割（複数可）

**2回目：働き方**
4. 勤務時間 → 計画と振り返りの時刻の案を出す（例：勤務 9〜18時なら、計画 9:00 → すぐ実行、振り返り 17:00）
5. 毎週・毎月の決まった仕事（定例業務）。思いつくだけでよい
6. 報告の好み（「結論＋理由を短く」「詳しく」など）と、一番大事にすること（品質・速さ・コストなど）

**3回目：開発（ツール・スクリプト・Web アプリ）**
7. 開発を AI に頼むことはありますか？（ない → 開発の質問は飛ばす。既定は local にしておく）
8. Git を使っていますか？
   - 使っていない → 既定のモードは `local`（自分のフォルダの `05_開発/` で完結。Git は AI が裏で記録だけ取る）
   - 使っている → 既定のモードを聞き、すでにあるシステムを登録する：名前、リポジトリの場所（このフォルダの中／別のフォルダ。複数可）、Spec Kit を使っているか（そのフォルダに `.specify/` があれば speckit）、テストのコマンド、ブランチ名の決まり。push は既定で本人が行う（AI に任せたい場合は、許可する例外として本人が設定する）
   - 別のフォルダのリポジトリは、編集の許可（`.claude/settings.json` の `permissions.additionalDirectories`）が要る。手順4の権限設定のときに一緒に入れる（`setup_settings.py` に `--add-dir <パス>` を付ける）

**（3回目の続き）データ分析・研修**
- データの集計・分析（売上・人事・アンケート・アクセス数など）を AI に頼むことはありますか？ 研修の教材作りはありますか？ → 無いものは config の `team.off` に入れる（`analyst`・`trainer`）。使う部下の数が上限（`team.max`、既定7）に入っているかも伝える

**（3回目の続き）デザイン**
- 会社や部署で決まったデザイン（Claude Design のデザインシステム、ロゴ・色・フォント）はありますか？どこにありますか（このアカウントで見えるか、別のアカウントか）？ → config の `design.systems` に「名前・場所・使う対象」で登録。別のアカウントにあって今は読めないなら、空のままにして「デザインの作業を始めるときにお願いを出す」と伝える
- デザインを入れたくない仕事（例：社内資料は自分で見るので不要）があれば聞いて、本人設定に書く

**（3回目の続き）Google カレンダー**
- 先に `.claude/ai-bunshin-details/calendar.md` を読む（セットアップの途中でまだ写されていないときは `${CLAUDE_PLUGIN_ROOT}/rules/details/calendar.md`)（一度読んだら、この会話では読み直さない）
- 「今日の予定を、タスクと一緒に見られるようにしますか？（Google カレンダー）」→ いいえなら飛ばす
- はいなら、使い方に合わせて案内する（どちらも読むだけ）：
  - **チャットだけで使う人**：claude.ai の設定 → コネクタ（Connectors）→ Google Calendar をオンにして、Google アカウントでログインする。オンにしたら「今日の予定を見せて」で確かめる。config の `calendar` は `{"type": "connector"}`
  - **CLI の人・Mac で朝の自動実行にも予定を入れたい人**：
    1. Google カレンダーの設定 → 対象のカレンダー →「カレンダーの統合」→「iCal 形式の非公開 URL」をコピー（会社の管理者が止めている場合は表示されない。その場合はコネクタの方法にする）
    2. 先に 1. の URL をコピーしておき、**Claude の入力欄ではなく（`!` も付けず）、Mac の「ターミナル」アプリ** で、コピーした直後に次を打って Enter（URL は合言葉と同じなので、チャットに貼らない。この打ち方なら URL は画面にも履歴にも残らず、末尾に見えない文字が付かない）：`security add-generic-password -a "$USER" -s ai-bunshin-calendar -w "$(pbpaste | tr -d '[:space:]')"`。`-U`（上書き）は付けない（2026-10-30 に `-U` では上書きされなかった。入れ直すときは下の「入れ直すとき」のとおり、消してから入れる）
       - 入れたあとは、URL がクリップボードに残らないよう、続けて `pbcopy < /dev/null` を打って空にする
    3. config に `"calendar": {"type": "ics", "keychain": "ai-bunshin-calendar", "show": "title"}` を書く（件名を出したくなければ `"show": "time"`）
    4. `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/update_dashboard.py"` を実行し、起動時のまとめに「今日の予定」が出るか確かめる
    - **入れ直すとき（消してから入れる。消すのは本人が打つ）**：すでに入っていて予定を読めないとき（以前の手順は `-w` の入力欄に URL を貼っていて、URL の末尾に見えない文字が付いて読めなくなった。2026-10-30 に起きた）。次の2つを、Mac の「ターミナル」で（`!` なしで）**本人が** 打つ（AI は打たない。消すコマンドは本人だけが打つ）：
      1. 消す：`security delete-generic-password -s ai-bunshin-calendar`
      2. 入れる：上の 2. と同じ（先に URL をコピーしておき、コピーした直後に打って Enter）：`security add-generic-password -a "$USER" -s ai-bunshin-calendar -w "$(pbpaste | tr -d '[:space:]')"`。そのあと `pbcopy < /dev/null` でクリップボードを空にする
  - **Windows の人**（キーチェーンが無いので、置き場所が違う）：URL を、ユーザーのフォルダ（`C:\Users\<ユーザー名>\`）の直下の `ai-bunshin-calendar-url.txt` に書く。本人のフォルダの外なので、同期や Git に載らない。URL は合言葉と同じなので、チャットには貼らない：
    1. 上の 1. と同じ手順で URL をコピーする
    2. 「メモ帳」を開いて URL を貼り付ける（1行だけ。2つ貼らない。改行は付けなくてよい。保存するときの「文字コード」は UTF-8 のまま）→「名前を付けて保存」→ 保存先は自分のユーザーフォルダ、ファイル名は `ai-bunshin-calendar-url.txt`、「ファイルの種類」は「すべてのファイル」（`.txt.txt` になるのを防ぐ）。OneDrive で同期されるフォルダ（ドキュメント・デスクトップ）には置かない
    3. config の `calendar` は Mac と同じ（`keychain` の項目は Windows では使われない）
    4. 時刻がずれないよう、tzdata（タイムゾーンの辞書）が入っているか確かめる。`scripts/requirements.txt` に入っている。入れるのは本人（AI は入れない）。PowerShell で `py -m pip install tzdata`（`py` が無ければ `python -m pip install tzdata`）。入っているかの確かめ：`py -c "import zoneinfo; zoneinfo.ZoneInfo('Asia/Tokyo')"` がエラーなく終われば入っている。入っていないと、タイムゾーンを読めない予定は「時刻不明」と出る
    5. `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/update_dashboard.py"`（無ければ `python` か `py -3`）を実行する。「📅 予定を読めませんでした（Windows のつなぎ方は setup を見てください）」と出たら、ファイルの名前と場所を確かめる
  - 予定を読めなかったときは、起動時のまとめ・朝の計画に「📅 予定を読めませんでした（理由）」と出る（「予定なし」とは別。会議の多さは分からないので、予定のない日として計画を組まない）

**4回目：守ってほしいこと**
9. 共通の「必ず確認すること」（社外への送信・お金・人事・他の人を巻き込む判断・ファイルの削除）以外に、確認してほしいこと
10. ほかに「やってはいけないこと」（追加の NG）
11. 会社の休みの日（祝日以外。分かる範囲で）

## 3. ファイルを作る

**最初に権限の設定（NG）を入れる**（設定/config.json を作る前に行う。作ったあとはスクリプトが動かない）：
1. 本人に「AI が削除・送信・設定の変更などをできないようにする設定を入れます」と説明し、了承を得る
2. `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/setup_settings.py" "<本人のフォルダの絶対パス>"` を実行する（既存の `.claude/settings.json` のプラグイン有効化は残し、deny だけを足す。Write で上書きしない＝NG の見張りが止める）

次に、雛形 `${CLAUDE_PLUGIN_ROOT}/templates/` を読み（雛形のファイル名は英数字。作る先の日本語の名前は下の表）、`{{…}}` を **すべて** 答えで置き換えて、本人のフォルダに書く。置き換えの対応：

| 雛形の項目 | 入れるもの |
|---|---|
| `{{名前}}`・`{{呼び方}}`・`{{AIの名前}}` | 質問1・2 |
| `{{部署1}}`・`{{部署2}}`・`{{部署と役割}}` | 質問3。部署の数に合わせて、config.json の `departments` の要素と、部署一覧.md の表の行を増減する |
| `{{勤務時間}}`、config.json の `work_hours` | 質問4 |
| `{{計画の時刻}}`・`{{振り返りの時刻}}`、config.json の `schedule` | 質問4で決めた時刻（`"09:00"` の形） |
| `{{自動実行の有無}}` | 手順5の答え（あとで書き換える） |
| `{{定例の名前}}`・`{{頻度}}`・`{{AI がやること → …}}` | 質問5（定例の数だけ行を作る。なければ「（まだなし）」） |
| `{{大事にすること}}`・`{{報告の好み}}` | 質問6 |
| 追加の確認事項・追加の NG | 質問9・10 |
| config.json の `dev`、CLAUDE.md の「開発の置き場所」 | 質問7・8（既定のモードと、登録したシステムの一覧） |
| config.json の `path` | 手順1で調べた PATH（`command -v claude` と openpyxl の入った python3 のフォルダを含める） |

書き終えたら、本人のフォルダで `grep -rn "{{" CLAUDE.md 設定 04_ナレッジ 00_タスク管理` が何も出さないことを確かめる。

| 作るもの | 雛形 |
|---|---|
| `CLAUDE.md`（本人設定） | `templates/CLAUDE.md` |
| `設定/config.json` | `templates/config/config.json`。`path` には、`command -v claude` と openpyxl の入った `python3` のフォルダを含む PATH を入れる |
| `00_タスク管理/data/tasks.json` | `templates/tasks/tasks.json`。holidays に質問11の休みと、その年の祝日を入れる |
| `04_ナレッジ/プロフィール.md`・`判断基準.md`・`部署一覧.md`・`改善ログ.md`・`役の書き方.md`・`ルール履歴/README.md` | `templates/knowledge/` の `profile.md`・`judgement.md`・`departments.md`・`improvement_log.md`・`roles.md`・`rule_history/README.md` |
| `04_ナレッジ/プロダクトゴール.md`・`完成の定義.md`・`スクラムマスターの観察.md` | `templates/knowledge/` の `product_goal.md`・`definition_of_done.md`・`sm_observation.md` |
| `04_ナレッジ/研修/研修の決まり.md` | `templates/knowledge/training/training_rules.md`（研修を担当する人だけ） |
| `02_成果物/共通/業務改善の提案.md` | `templates/deliverables/improvement_proposals.md` |
| `04_ナレッジ/業務の流れ.md` | `templates/knowledge/business_flow.md` |
| `04_ナレッジ/記事スタイル/書き方.md`・`言い回し.md`・`手直し記録.md`・`お手本/README.md` | `templates/knowledge/article_style/` の `style_guide.md`・`phrases.md`・`revisions.md`・`examples/README.md`（本人名義の記事・コラムを書く人だけ。お手本はまだ空でよい） |
| 空のフォルダ | `01_スプリント/`、`02_成果物/<部署>/`、`03_インプット/<部署>/`、開発を頼む人は `05_開発/` |

作ったら自己診断をする（どれかが失敗したら、原因と直し方を本人に伝える）：
1. `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/update_dashboard.py"` → `00_タスク管理/タスク管理.xlsx` ができる
2. `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/update_dashboard.py" --session` → `.claude/rules/ai-bunshin-common.md` と `.claude/ai-bunshin-details/`（必要なときだけ読む詳しい手順）ができる（次の起動から共通ルールが読み込まれる）
3. `python3 "${CLAUDE_PLUGIN_ROOT}/tests/test_ng_guard.py"` → 「失敗 0 件」（NG の見張りが効く）

## 4. 業務の棚卸し（何を任せるか）

1. 「1週間の仕事を、思いつくだけ箇条書きで教えてください（細かくなくて大丈夫です）」と聞く
2. 各仕事を3つに分ける：
   - **任せられる**（資料作成・集計・調査・下書き・整理など）
   - **一部任せられる**（下書きは AI、送信・判断は本人）
   - **本人にしかできない**（会議への出席、決裁、対面の対応など）
3. 浮く時間が大きい順に **任せる候補リスト** を表で出す（仕事／分類／AI がやること／本人がやること／頼み方の例文）
4. 上位3つを最初のタスクとして登録してよいか聞く。よければ `/ai-bunshin:intake` の手順で登録する
5. 判断基準を育てるために、最初のお願い「インタビュー（判断基準・口調・資料の好み）」を本人のタスクとして登録する（期日は1週間後）
6. 業務の流れの最初のバージョンも作る：棚卸しの答えから、業務ごとに「どこから来るか・誰が何をするか・どこへ渡すか・頻度と時間・困っていること」を `04_ナレッジ/業務の流れ.md` に書く（雛形は `templates/knowledge/business_flow.md`）。分からないところは「ヒアリングしたいこと」の部分に残し、インタビューで聞く

## 5. 自動実行（Mac のみ）

「平日の計画と振り返りを自動で動かしますか？」と聞く。はいなら、本人に次を打ってもらう（AI は launchctl を実行しない。下の `${CLAUDE_PLUGIN_ROOT}` はこのスキルを読み込んだ時点で実際のパスになっているので、そのまま見せる。本人のフォルダの部分は絶対パスに置き換えて見せる）：

```
! zsh "${CLAUDE_PLUGIN_ROOT}/scripts/auto/install.sh" "<本人のフォルダの絶対パス>"
```

打ったあと `! launchctl list | grep ai-bunshin` で2行（daily-plan と daily-review）出れば完了。いいえなら、手動で `/ai-bunshin:daily-plan` などを使うと伝える。

### Windows の人（上の Mac の方法は Windows では動かない。次の A か B を案内する）

上の `install.sh` は zsh と launchd と osascript を使うので、Windows では動かない（zsh・osascript は Windows に標準では無い）。「自動で回したいですか？」と聞き、はいなら A、いいえ・うまくいかないなら B を案内する。**登録は本人が画面で行う**（AI は予定の登録・設定の変更をしない）。公式の説明の確認日：2026-10-31（出典：`code.claude.com/docs/en/desktop-scheduled-tasks`）。

**A. Claude デスクトップアプリの「定期実行」（公式の機能。Windows 版にもある）**

前提：Claude デスクトップアプリ（Windows 版。定期実行は 1.1.5368 以降）を入れていて、仕事用フォルダを **Code** タブで開いたことがあり（フォルダを信頼済み）、セットアップが終わっている。次の2つを作る（朝の計画→実行が1つ、夕方の振り返りが1つ）。

1. **Code** タブの左のメニュー **Scheduled**（「Routines」と出るバージョンは **Routines** → **New routine**）→ **New task**
2. 「Create with Claude」と「Set up manually」が出たら **Set up manually**
3. **Only on this computer** をオンにする（画面の上、または「Advanced settings」の中にある。クラウドの方は選ばない。仕事用フォルダはこの PC にあるため）
4. **Name**：朝は `ai-bunshin-plan-do`、夕方は `ai-bunshin-review`（英小文字とハイフン。ほかの定期実行と重ならない名前）
5. **Instructions**（指示）に、朝は次を貼る：
   `/ai-bunshin:daily-plan を実行してください。計画が作られたら、続けて /ai-bunshin:daily-do を実行してください。営業日でない日は何もしないでください。`
   夕方は次を貼る：
   `/ai-bunshin:daily-review を実行してください。営業日でない日、または今日の振り返りが済んでいる日は何もしないでください。`
6. **Local folder**（作業フォルダ）：仕事用フォルダ。モデル：Opus（Mac の自動実行と同じ）。権限モードは、はじめは手動のまま
7. 頻度：**Weekdays**（平日）、時刻は朝 9:00／夕方 17:00（自分の勤務時間に合わせる）→ **Create**
8. **Run now** で1回動かす。権限の確認が出たら中身を読み、計画・実行・振り返りに必要なもの（仕事用フォルダの中のファイルの読み書き、`update_dashboard.py` の実行）だけ「always allow」を選ぶ。削除・送信・設定の変更に当たるものは許可しない。朝の分は動かしたあと、`00_タスク管理/` と `01_スプリント/…/daily/` に今日の計画ができたかを見る

守る・伝えること：
- 【公式】動くのは、**アプリが開いていて、PC が起きているあいだだけ**。スリープしていた時刻の分は飛ぶ。PC が起きたときやアプリを開いたとき、直近7日の取りこぼしを **1回だけ**（一番新しい分）追いかけて動かす。朝9時の計画が夜に動くことがあるので、「Keep computer awake」（設定 → Desktop app）をオンにするか、朝はアプリを開いておく
- 【公式】決めた時刻から数分遅れて始まる（毎回同じだけ遅れる）。前の実行がまだ続いているときは、次の実行は飛ぶ（朝の実行が夕方まで続くと、振り返りが飛ぶ）。飛んだ理由は詳細ページの **History** にある
- 【公式】権限の確認で手動モードの実行が止まったら、History から実行のセッションを開いて答える。AI の質問で止まったときも同じ
- Mac の「自動実行が N日 動いていません」の警告は Windows では出ない（`scripts/auto/run.sh` を作らないため）。ときどき **Scheduled** の History を見て、動いているかを確かめる
- Mac の自動実行がかけている道具の絞り込み（削除・送信・設定の変更を使えなくする）は、この方法ではかからない。権限モードと、設定（`.claude/settings.json` の deny・NG の見張り）に頼る。【要確認】NG の見張りが定期実行のセッションでも動くか（Run now のあと、`00_タスク管理/data/ng_log.jsonl` が増えるかで見る）
- 【要確認】指示の中の `/ai-bunshin:…` がスキルとして呼ばれるか。ふつうの文として読まれて動かないときは、朝は「今日の計画を立てて。終わったら続けて今日の分を実行して」、夕方は「今日の振り返りをして」に書き換える（Edit から）。Run now で必ず確かめる
- 【要確認】このバージョンの画面の名前・並び（バージョンによって違う）。定期実行が使える契約（プラン）の条件は、公式の説明に書かれていない
- 使わない方法：**クラウドの定期実行**（claude.ai の Routines）は、GitHub のリポジトリを複製して動くので、この PC の仕事用フォルダ（タスク表・入力データ）には触れない。このプラグインが複製だけで動くかは確かめていないので、案内しない。**タスク スケジューラ＋`claude -p`** は、このプラグインの入口（`daily_cycle.sh`）が zsh 前提で Windows 用の入口が無いため、いまは案内しない

**B. 手で回す（A が使えない・うまくいかないときの予備。Mac 以外はこれが基本）**

自動実行は Mac だけと伝え、次のように言うと同じことができる、と案内する（Claude を仕事用フォルダで開いておく）：
- 朝：「**今日の計画を立てて**」（`/ai-bunshin:daily-plan`）→ 計画ができたら「**続けて今日の分を実行して**」（`/ai-bunshin:daily-do`）
- 夕方：「**今日の振り返り**」（`/ai-bunshin:daily-review`）
- 言い忘れた日があっても大丈夫。翌朝にまた言えばよい（営業日でない日や、すでに済んでいる日は、スキルが何もせずに終わることがある）

## 6. 使い方の案内（最後に短く）

- 頼み方：雑でよい。「今すぐ」→ その場で、「今日中」→ 今日の計画に割り込み、何も言わない → 翌日の計画へ
- 「何を頼めばいい？」と聞けば、任せられる仕事を提案する（`/ai-bunshin:consult`）
- お願いへの返事：「T0XX やった」「T0XX は無い」「T0XX はこう変えて」
- 見る場所：`00_タスク管理/タスク管理.xlsx` と `<呼び方>へのお願い.md`
- 最初の3日は使用量を測る期間。ときどき `/usage` で残りを見てほしい
- 分からない言葉（スプリント・ベロシティ・約束pt など）が出たら、「言葉の意味を教えて」と聞けば説明する（`/ai-bunshin:status` の最後の「ことばの説明」）
