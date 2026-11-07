import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { AllRow, Board, Cal, CalEvent, Detail, ForecastDay, ForecastTask, Gantt, Row, Try, View } from '../types'

// 共通のパネル。本人のフォルダ（設定/config.json と 00_タスク管理/data/tasks.json がある所）でだけ出る。
// tasks.json と予定のキャッシュは読むだけ。名前・呼び方は config.json の owner・owner_call から
const PANE = 'ai-bunshin-panel'
const TITLE = '今日のやること'
const ALL_TITLE = '全部のタスク'
const GANTT_TITLE = 'これから2週間'

const EMPTY: Board = { today: '', mine: [], ai: [], aiNext: [], aiNextMore: 0, all: [], soon: [], openRequests: 0, error: '' }
// 形を変えたら shape の札も変える（前の版がしまった値を読まないように）
const board = atom({ plugin: 'ai-bunshin-panel', key: 'board' } as const, EMPTY, { shape: 'board-5' })
const HOME: View = { mode: 'home', page: 0 }
const view = atom({ plugin: 'ai-bunshin-panel', key: 'view' } as const, HOME, { shape: 'view-2' })
const mtime = atom({ plugin: 'ai-bunshin-panel', key: 'mtime' } as const, 0)
const NONE: Detail = { id: '', title: '', lines: [], steps: [], error: '' }
const detail = atom({ plugin: 'ai-bunshin-panel', key: 'detail' } as const, NONE, { shape: 'detail-1' })
const NO_CAL: Cal = { fetched: '', events: [], nowMin: 0, error: '' }
const cal = atom({ plugin: 'ai-bunshin-panel', key: 'cal' } as const, NO_CAL, { shape: 'cal-1' })
const NO_GANTT: Gantt = { ok: false, message: '', today: '', days: [], tasks: [], waiting: 0 }
const gantt = atom({ plugin: 'ai-bunshin-panel', key: 'gantt' } as const, NO_GANTT, { shape: 'gantt-1' })

type Task = {
  id: string
  title: string
  assignee?: string
  status?: string
  due?: string | null
  kind?: string
  [k: string]: any
}

// 本人のフォルダ（見つかったときだけ入る。session.start のたびに探し直す）
type Me = { home: string; owner: string; call: string; hasCal: boolean; file: string; calFile: string; forecastFile: string; logFile: string }
let me: Me | undefined
const NO_HOME = '本人のフォルダ（設定/config.json と 00_タスク管理/data/tasks.json がある所）の中ではないので、使えません。'

const MAX_UP = 6
// Windows の形のパス（C:\… ・ C:/… ・ \\server\share\…）かどうか。そうでなければ POSIX として今までどおり扱う
const isWin = (p: string) => /^[A-Za-z]:/.test(p) || p.startsWith('\\\\')
const lastSep = (p: string) => Math.max(p.lastIndexOf('/'), p.lastIndexOf('\\'))
// つなぐ区切りは、dir が使っているほう（\ があって / が無ければ \）。dir 末尾の区切りは削る
const at = (dir: string, rel: string) => {
  const sep = dir.includes('\\') && !dir.includes('/') ? '\\' : '/'
  return `${dir.replace(/[\\/]+$/, '')}${sep}${rel.replace(/\//g, sep)}`
}
// 1つ上のフォルダ。いちばん上（/、C:\、UNC の \\server\share）では dir と同じものを返す（呼ぶ側が止まる）
const parentOf = (dir: string) => {
  if (!isWin(dir)) {
    const i = dir.lastIndexOf('/')
    return i > 0 ? dir.slice(0, i) : '/'
  }
  const d = dir.replace(/[\\/]+$/, '')
  const unc = /^\\\\[^\\/]+(?:[\\/][^\\/]+)?$/.test(d) // \\server か \\server\share（これより上は無い）
  if (unc || /^[A-Za-z]:$/.test(d)) return dir
  const i = lastSep(d)
  if (i < 0) return dir
  const up = d.slice(0, i)
  return /^[A-Za-z]:$/.test(up) ? up + d[i] : up
}

// 作業中のフォルダから上へ最大6段たどり、本人のフォルダを探す。無ければ undefined（何も出さない）。
// config.json は先頭の BOM を除いて読む。読めない・壊れているときも undefined
async function findMe($: EngineInterface): Promise<Me | undefined> {
  let dir = await $.session.cwd().catch(() => '')
  if (!dir) return undefined
  for (let i = 0; i <= MAX_UP; i++) {
    const cfg = at(dir, '設定/config.json')
    const file = at(dir, '00_タスク管理/data/tasks.json')
    if ((await $.fs.stat(cfg).catch(() => undefined)) && (await $.fs.stat(file).catch(() => undefined))) {
      try {
        const c = JSON.parse((await $.fs.read(cfg)).replace(/^\uFEFF/, ''))
        const owner = typeof c.owner === 'string' && c.owner.trim() ? c.owner.trim() : '本人'
        const call = typeof c.owner_call === 'string' && c.owner_call.trim() ? c.owner_call.trim() : `${owner}さん`
        // 予定は update_dashboard.py が起動時・自動実行のときに書く（config に calendar があるときだけ）
        return { home: dir, owner, call, hasCal: !!c.calendar, file, calFile: at(dir, '00_タスク管理/data/calendar_cache.json'), forecastFile: at(dir, '00_タスク管理/data/forecast.json'), logFile: at(dir, '04_ナレッジ/改善ログ.md') }
      } catch {
        return undefined
      }
    }
    const up = parentOf(dir)
    if (up === dir) break
    dir = up
  }
  return undefined
}

// 日本時間の日付（YYYY-MM-DD）
const dayOf = (ms: number) => new Date(ms + 9 * 3600e3).toISOString().slice(0, 10)
const md = (d: string) => (d ? `${Number(d.slice(5, 7))}/${Number(d.slice(8, 10))}` : '')

// 案件のカテゴリ（tasks.json の category）。文字で、空でなければそのまま（前後の空白は除く）。無い・空・文字でないものは「未分類」
const UNCAT = '未分類'
const DONE_HEAD = '完了'
const catOf = (t: Task): string => (typeof t.category === 'string' && t.category.trim() ? t.category.trim() : UNCAT)

// 短い画面の区切りの中を、カテゴリごとに分ける。カテゴリの順は「その区切りで最初に出てくる順」。未分類は最後。
// カテゴリの中の行は、渡された並びのまま
function groupByCat(rows: Row[]): { cat: string; rows: Row[] }[] {
  const groups: { cat: string; rows: Row[] }[] = []
  for (const r of rows) {
    const g = groups.find(x => x.cat === r.category)
    if (g) g.rows.push(r)
    else groups.push({ cat: r.category, rows: [r] })
  }
  return [...groups.filter(g => g.cat !== UNCAT), ...groups.filter(g => g.cat === UNCAT)]
}

// 承認待ち：未完了で、担当が本人、題名が「ルール変更の承認」で始まるお願い（振り返りが出すお願いの目印）。印は [承認]
const APPROVAL = 'ルール変更の承認'
const APPROVAL_MARK = '承認'
const isApproval = (t: Task, OWNER: string) =>
  t.status !== '完了' && t.assignee === OWNER && typeof t.title === 'string' && t.title.startsWith(APPROVAL)

function build(data: any, today: string, OWNER: string): Board {
  const tasks: Task[] = data.tasks ?? []
  const open = tasks.filter(t => t.status !== '完了')
  const row = (t: Task, mark: string): Row => ({ id: t.id, title: t.title, due: md(t.due ?? ''), mark, category: catOf(t) })
  const byDue = (a: Task, b: Task) => (a.due ?? '').localeCompare(b.due ?? '')

  // 今日まで：期日の順。承認待ちは一番上（同じ仲間の中は期日の順のまま）
  const mineTasks = open.filter(t => t.assignee === OWNER && t.due && t.due <= today).sort(byDue)
  const mine = [...mineTasks.filter(t => isApproval(t, OWNER)), ...mineTasks.filter(t => !isApproval(t, OWNER))].map(t =>
    row(t, isApproval(t, OWNER) ? APPROVAL_MARK : t.due! < today ? '超過' : '今日'),
  )

  const limit = dayOf(Date.parse(today) + 4 * 86400e3)
  const soon = open
    .filter(t => t.assignee === OWNER && t.due && t.due > today && t.due <= limit)
    .sort(byDue)
    .slice(0, 6)
    .map(t => row(t, isApproval(t, OWNER) ? APPROVAL_MARK : ''))

  const sprint = (data.daily_sprints ?? []).find((s: any) => s.date === today)
  const planned: string[] = [...(sprint?.planned ?? []), ...(sprint?.added ?? []), ...(sprint?.pulled ?? [])]
  const byId = new Map(tasks.map(t => [t.id, t]))
  const ai = planned
    .map(id => byId.get(id))
    .filter((t): t is Task => !!t)
    .map(t => row(t, t.status === '完了' ? '済' : (t.status ?? '')))

  // AI のこれから：今日の計画に入っていない、未完了の AI のタスク（順位の順）
  const inPlan = new Set(planned)
  const next = open
    .filter(t => t.assignee && t.assignee !== OWNER && !inPlan.has(t.id))
    .sort((a, b) => (a.priority ?? 999) - (b.priority ?? 999))
  const aiNext = next.slice(0, 6).map(t => row(t, t.status ?? ''))

  // 全部のタスク：未完了をカテゴリごとにまとめる（順位の順に並べ、カテゴリは「いちばん順位が高いタスク」が早い順。「未分類」は最後）。
  // カテゴリの中は順位の順のまま。そのあとに完了を新しい順に（カテゴリでは分けない）
  const allRow = (t: Task): AllRow => ({
    ...row(t, t.status === '完了' ? '済' : isApproval(t, OWNER) ? APPROVAL_MARK : (t.status ?? '')),
    who: t.assignee ?? '',
    done: t.status === '完了',
  })
  const sortedOpen = [...open].sort((a, b) => (a.priority ?? 999) - (b.priority ?? 999) || a.id.localeCompare(b.id))
  const order: string[] = []
  for (const t of sortedOpen) if (catOf(t) !== UNCAT && !order.includes(catOf(t))) order.push(catOf(t))
  const rank = (t: Task) => (catOf(t) === UNCAT ? order.length : order.indexOf(catOf(t)))
  const all = [
    ...sortedOpen.map((t, i) => ({ t, i })).sort((a, b) => rank(a.t) - rank(b.t) || a.i - b.i).map(x => x.t),
    ...tasks.filter(t => t.status === '完了').sort((a, b) => b.id.localeCompare(a.id)),
  ].map(allRow)

  const openRequests = open.filter(t => t.assignee === OWNER && t.kind !== '自分').length
  return { today, mine, ai, aiNext, aiNextMore: next.length - aiNext.length, all, soon, openRequests, error: '' }
}

const fmt = (v: any): string =>
  Array.isArray(v) ? v.map(fmt).join('、') : v == null ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v)

// ---------- 試し中の Try（本人のフォルダの 04_ナレッジ/改善ログ.md の「## 実施中の Try」の表。読むだけ） ----------
const TRY_HEAD = /^##\s+実施中の\s*Try/
const TRY_COLS = ['ID', '良くするもの', '内容', '確かめ方', '開始日'] as const

// 表の1行を、| で区切った欄にする（\| は区切りにしない。前後の空白は除く）
const splitRow = (line: string): string[] => {
  const s = line.trim().replace(/^\|/, '').replace(/(?<!\\)\|$/, '')
  const cells: string[] = []
  let cur = ''
  for (let i = 0; i < s.length; i++) {
    if (s[i] === '\\' && s[i + 1] === '|') {
      cur += '|'
      i++
    } else if (s[i] === '|') {
      cells.push(cur.trim())
      cur = ''
    } else cur += s[i]
  }
  cells.push(cur.trim())
  return cells
}

// 内容の先頭の「（…）」の注記を飛ばして、そこから右をそのまま返す。閉じ括弧が無い・飛ばすと何も残らないときは飛ばさない
function skipNote(body: string): string {
  if (!body.startsWith('（')) return body
  let depth = 0
  for (let i = 0; i < body.length; i++) {
    if (body[i] === '（') depth++
    else if (body[i] === '）' && --depth === 0) {
      const rest = body.slice(i + 1).trimStart()
      return rest === '' ? body : rest
    }
  }
  return body
}

// 「実施中の Try」の見出しから次の「## 」までの表を読む。列は見出しの名前で探す。無い・形が違う・空のときは []（エラーにしない）
function parseTries(text: string): Try[] {
  const lines = text.split(/\r?\n/)
  const from = lines.findIndex(l => TRY_HEAD.test(l))
  if (from < 0) return []
  let to = lines.findIndex((l, i) => i > from && /^##\s/.test(l))
  if (to < 0) to = lines.length
  const rows = lines.slice(from + 1, to).map(l => l.trim())
  const t0 = rows.findIndex(l => l.startsWith('|'))
  if (t0 < 0 || !rows[t0 + 1]?.startsWith('|') || !/^[\s|:-]+$/.test(rows[t0 + 1]) || !rows[t0 + 1].includes('-')) return []
  const head = splitRow(rows[t0])
  const col = TRY_COLS.map(name => head.findIndex(h => h.startsWith(name)))
  if (col.some(i => i < 0)) return []
  const tries: Try[] = []
  for (let i = t0 + 2; i < rows.length && rows[i].startsWith('|'); i++) {
    const c = splitRow(rows[i])
    const cell = (k: number) => c[col[k]] ?? ''
    if (!cell(0).toUpperCase().startsWith('Y')) continue
    tries.push({ id: cell(0), area: cell(1), body: cell(2), check: cell(3), start: cell(4) })
  }
  return tries
}

// 改善ログを読んで Try の一覧にする。読めなければ []
async function loadTries($: EngineInterface): Promise<Try[]> {
  if (!me) return []
  try {
    return parseTries(await $.fs.read(me.logFile))
  } catch {
    return []
  }
}

// 開始日：YYYY-MM-DD なら M/D、ほかの書き方はそのまま
const startOf = (s: string) => (ISO.test(s) ? md(s) : s)

// 1件分の詳細。お願いなら手順・完了の基準・報告してほしいことも出す。Y で始まる ID なら Try の詳細
async function show($: EngineInterface, raw: string): Promise<Detail & { isPlaced: boolean }> {
  if (!me) return { ...NONE, error: NO_HOME, isPlaced: false }
  const FILE = me.file
  let id = (raw.trim().split(/\s+/)[0] ?? '').toUpperCase()
  if (/^\d+$/.test(id)) id = `T${id.padStart(3, '0')}`
  let d: Detail
  if (id.startsWith('Y')) {
    const t = (await loadTries($)).find(x => x.id.toUpperCase() === id)
    if (!t) {
      d = { ...NONE, id, error: `${id} は改善ログにありません` }
    } else {
      const pairs: [string, string][] = [
        ['良くするもの', t.area],
        ['内容', t.body],
        ['確かめ方', t.check],
        ['開始日', startOf(t.start)],
      ]
      d = { id: t.id, title: '試し中の Try', lines: pairs.map(([label, text]) => ({ label, text })).filter(l => l.text !== ''), steps: [], error: '' }
    }
    await update($, detail, () => d)
    const { isPlaced } = await $.ui.open({ id: PANE, title: d.error ? TITLE : `${d.id} の詳細` })
    return { ...d, isPlaced }
  }
  try {
    const data = JSON.parse(await $.fs.read(FILE))
    const t: Task | undefined = (data.tasks ?? []).find((x: Task) => x.id === id)
    if (!t) {
      d = { ...NONE, id, error: `${id} は tasks.json にありません` }
    } else {
      const pairs: [string, any][] = [
        ['状態', t.status],
        ['担当', t.assignee],
        ['カテゴリ', catOf(t) === UNCAT && t.status === '完了' ? '' : catOf(t)],
        ['種類', t.kind ? `${t.type ?? ''}／${t.kind}` : t.type],
        ['期日', t.due ? md(t.due) : ''],
        ['期日の理由', t.due_reason],
        ['なぜ', t.why],
        ['完了の基準', t.done_when],
        ['終わったら教えてほしいこと', t.report_back],
        ['関連', t.related],
        ['前提', t.depends_on],
        ['メモ', t.note],
      ]
      const lines = pairs.map(([label, v]) => ({ label, text: fmt(v) })).filter(l => l.text !== '')
      d = { id, title: t.title, lines, steps: Array.isArray(t.steps) ? t.steps.map(fmt) : [], error: '' }
    }
  } catch {
    d = { ...NONE, id, error: 'tasks.json を読めませんでした（少し待ってもう一度）' }
  }
  await update($, detail, () => d)
  const { isPlaced } = await $.ui.open({ id: PANE, title: d.error ? TITLE : `${d.id} の詳細` })
  return { ...d, isPlaced }
}

// 全部の一覧に出す行：カテゴリの見出し（■ カテゴリ（N））と、タスクの行。見出しも1行に数える
type AllLine = { kind: 'head'; text: string; done: boolean } | { kind: 'row'; r: AllRow }

// board.all（未完了はカテゴリごとにまとまり、完了は最後）から、見出しつきの行にする。N はその見出しの下の数
function allLines(all: AllRow[]): AllLine[] {
  const key = (r: AllRow) => (r.done ? '\u0000done' : `c:${r.category}`)
  const lines: AllLine[] = []
  for (let i = 0; i < all.length; ) {
    let j = i
    while (j < all.length && key(all[j]) === key(all[i])) j++
    const name = all[i].done ? DONE_HEAD : all[i].category
    lines.push({ kind: 'head', text: `■ ${name}（${j - i}）`, done: all[i].done })
    for (let k = i; k < j; k++) lines.push({ kind: 'row', r: all[k] })
    i = j
  }
  return lines
}

// 1ページ per 行に区切る。見出しも1行に数える。ページの頭がカテゴリの途中なら、その見出しに「（続き）」を付けてもう一度出す。
// 見出しだけがページの最後に残るときは、次のページの頭に送る
function paginate(lines: AllLine[], per: number): AllLine[][] {
  const pages: AllLine[][] = []
  let cur: (AllLine & { kind: 'head' }) | undefined
  let i = 0
  while (i < lines.length) {
    const page: AllLine[] = []
    if (lines[i].kind === 'row' && cur) page.push({ ...cur, text: `${cur.text}（続き）` })
    while (i < lines.length && page.length < per) {
      const l = lines[i]
      if (l.kind === 'head' && page.length === per - 1 && i + 1 < lines.length) break
      page.push(l)
      if (l.kind === 'head') cur = l
      i++
    }
    pages.push(page)
  }
  return pages.length ? pages : [[]]
}

// 詳細を閉じて、いま見ていた一覧（短い画面か全部の一覧）に戻る
async function back($: EngineInterface) {
  await update($, detail, () => NONE)
  await refresh($, true)
  const v = await read($, view)
  await $.ui.open({ id: PANE, title: v.mode === 'all' ? ALL_TITLE : v.mode === 'gantt' ? GANTT_TITLE : TITLE })
}

// 短い画面に戻す
async function home($: EngineInterface) {
  await update($, view, () => HOME)
  await back($)
}

// 全部のタスクの一覧に切り替える
async function showAll($: EngineInterface): Promise<{ isPlaced: boolean; count: number }> {
  await refresh($, true)
  await update($, detail, () => NONE)
  await update($, view, () => ({ mode: 'all', page: 0 }))
  const { isPlaced } = await $.ui.open({ id: PANE, title: ALL_TITLE })
  return { isPlaced, count: (await read($, board)).all.length }
}

// ---------- これから2週間のガントチャート（forecast.json を読むだけ。計算し直さない） ----------
const GANTT_COLS = 14
const ISO = /^\d{4}-\d{2}-\d{2}$/
const STATE_WAIT = '見積もり待ち'
const STATE_LOOP = '依存の輪'

// 画面で占める幅。全角（かな・漢字・全角記号・絵文字など）は 2、結合する印・異体字セレクタは 0、それ以外は 1
const cellWidth = (s: string) => {
  let w = 0
  for (const ch of s) {
    const c = ch.codePointAt(0)!
    if ((c >= 0x300 && c <= 0x36f) || c === 0x3099 || c === 0x309a || c === 0xfe0f || c === 0x200d) continue
    const wide =
      c > 0xffff ||
      (c >= 0x1100 && c <= 0x115f) ||
      (c >= 0x2e80 && c <= 0xa4cf) ||
      (c >= 0xac00 && c <= 0xd7a3) ||
      (c >= 0xf900 && c <= 0xfaff) ||
      (c >= 0xfe30 && c <= 0xfe6f) ||
      (c >= 0xff00 && c <= 0xff60) ||
      (c >= 0xffe0 && c <= 0xffe6)
    w += wide ? 2 : 1
  }
  return w
}

// 幅 w にちょうど収める（長ければ切って「~」（幅が1に決まっている文字。「…」は端末によって幅が違う）、短ければ空白で埋める）。列がずれないように
const fitCells = (s: string, w: number) => {
  let out = ''
  let used = 0
  if (cellWidth(s) <= w) {
    out = s
    used = cellWidth(s)
  } else {
    for (const ch of s) {
      const cw = cellWidth(ch)
      if (used + cw > w - 1) break
      out += ch
      used += cw
    }
    out += '~'
    used += 1
  }
  return out + ' '.repeat(Math.max(0, w - used))
}

const isoOrNull = (v: any): string | null => (typeof v === 'string' && ISO.test(v) ? v : null)

// forecast.json を読む。無い・壊れている・古い（今日の日付でない）ときは、ok=false と1行の案内にする
async function loadGantt($: EngineInterface, now: number): Promise<Gantt> {
  if (!me) return { ...NO_GANTT, message: NO_HOME }
  const today = dayOf(now)
  let raw: any
  try {
    raw = await $.fs.read(me.forecastFile)
  } catch {
    return { ...NO_GANTT, message: 'forecast.json がまだありません（読めませんでした）。update_dashboard.py を動かすと出ます' }
  }
  try {
    const f = JSON.parse(raw)
    const days: ForecastDay[] = (Array.isArray(f.days) ? f.days : [])
      .filter((d: any) => d && isoOrNull(d.date))
      .map((d: any) => ({ date: d.date as string, off: d.off === true }))
    const made = isoOrNull(f.today)
    if (!made || days.length === 0 || !Array.isArray(f.tasks)) throw new Error('shape')
    if (made !== today) {
      return { ...NO_GANTT, message: `forecast.json が古いです（${md(made)} 作成）。update_dashboard.py を動かすと出ます` }
    }
    const tasks: ForecastTask[] = f.tasks
      .filter((t: any) => t && typeof t.id === 'string')
      .map((t: any) => ({
        id: t.id,
        title: String(t.title ?? ''),
        who: String(t.who ?? ''),
        start: isoOrNull(t.start),
        end: isoOrNull(t.end),
        state: String(t.state ?? ''),
      }))
    const waiting = typeof f.waiting === 'number' && f.waiting >= 0 ? f.waiting : tasks.filter(t => t.state === STATE_WAIT).length
    return { ok: true, message: '', today: made, days, tasks, waiting }
  } catch {
    return { ...NO_GANTT, message: 'forecast.json を読めませんでした（壊れています）。update_dashboard.py を動かし直すと出ます' }
  }
}

async function refreshGantt($: EngineInterface) {
  const next = await loadGantt($, await $.clock.now())
  const cur = await read($, gantt)
  if (JSON.stringify(cur) !== JSON.stringify(next)) await update($, gantt, () => next)
}

// 1行ぶんの「列」。AI は 着手見込み〜完了予定を棒（= 、休みの日は .）、本人は期日の日に印（*）。
// 2週間より先に終わる（または先から始まる）ものは、右端に →。日付の前後は文字の並びで比べる（暦は計算しない）
function ganttCells(t: ForecastTask, days: ForecastDay[]): { cells: string; beyond: boolean } {
  const last = days.length - 1
  const own = t.who === '本人'
  const end = t.end ?? ''
  const beyond = end > days[last].date
  const mark: string[] = days.map(d => (d.off ? '.' : ' '))
  if (own) {
    if (!beyond) {
      const at = Math.max(0, days.findIndex(d => d.date >= end))
      mark[at] = '*'
    }
  } else {
    const s = days.findIndex(d => d.date >= (t.start ?? end))
    if (s >= 0) {
      let e = last
      if (!beyond) e = Math.max(s, days.map(d => d.date <= end).lastIndexOf(true))
      for (let i = s; i <= e; i++) if (!days[i].off) mark[i] = '='
    }
  }
  return { cells: mark.join(''), beyond }
}

// 棒の行は案件のカテゴリごとのまとまりに分ける（見出しの件数は、そのカテゴリの描ける件数）
type GanttGroup = { label: string; count: number; rows: string[] }
type GanttShow = { head: string; overdueLine: string; axis: string; groups: GanttGroup[]; waitLine: string; more: number; drawn: number }

// 棒（または印）の行にできるタスクと、期限を過ぎた本人のタスク（今日より前が期日。行にせず件数だけ出す）に分ける
function ganttSplit(g: Gantt) {
  const ok = g.tasks.filter(t => t.end && t.state !== STATE_WAIT && t.state !== STATE_LOOP && (t.who === '本人' || t.start))
  const today = g.days[0]?.date ?? ''
  const isOverdue = (t: ForecastTask) => t.who === '本人' && (t.end ?? '') < today
  return { draw: ok.filter(t => !isOverdue(t)), overdue: ok.filter(isOverdue).length }
}

// 画面に出す文字を作る（幅 cols・窓の高さ bodyRows）。タスク名の幅は残りの幅から、行の数は窓の高さから決める。
// 棒の行のほかに使う行：見出し・凡例・日付・「ほか」・件数のまとめ・ボタンで 6 行、期限超過の行（呼び方が長い人は折り返す分）。
// 棒の行はカテゴリごとにまとめる。カテゴリは board.all の並び（全部の一覧と同じ。「未分類」は最後）。
// forecast.json の tasks にはカテゴリが無いので、id で board.all から引く（引けないものは「未分類」）
function ganttLines(g: Gantt, cols: number, bodyRows: number, call: string, all: AllRow[]): GanttShow {
  const { draw, overdue } = ganttSplit(g)
  const overdueLine = overdue > 0 ? `期限超過 ${overdue} 件（${call}・今日より前）` : ''
  const overdueRows = overdueLine ? Math.ceil(cellWidth(overdueLine) / Math.max(1, cols)) : 0
  const catById = new Map<string, string>()
  const order: string[] = []
  for (const r of all) {
    if (r.done) continue
    catById.set(r.id, r.category)
    if (r.category !== UNCAT && !order.includes(r.category)) order.push(r.category)
  }
  order.push(UNCAT)
  const sets = order
    .map(name => ({ name, list: draw.filter(t => (catById.get(t.id) ?? UNCAT) === name) }))
    .filter(x => x.list.length > 0)
  // 窓の行：先頭から、見出し・間の空行・最低1行ずつが入るところまでのカテゴリを出す（k 個で 3k - 1 行）。入らないカテゴリは見出しごと出さない
  const avail = Math.max(0, bodyRows - 6 - overdueRows)
  const shownSets = Math.min(sets.length, Math.floor((avail + 1) / 3))
  // 棒の数：出すカテゴリに最低1行ずつ。余った行は前のカテゴリから詰める
  let spare = shownSets === 0 ? 0 : avail - (shownSets * 3 - 1)
  const picked = sets.slice(0, shownSets).map(x => {
    const take = Math.min(x.list.length, 1 + spare)
    spare -= take - 1
    return x.list.slice(0, take)
  })
  const shownAll = picked.flat()
  const idW = Math.max(4, ...shownAll.map(t => cellWidth(t.id)))
  const titleW = Math.max(6, Math.min(24, cols - idW - 1 - 1 - g.days.length - 2))
  const lead = ' '.repeat(idW + 1 + titleW + 1)
  const groups: GanttGroup[] = picked.map((rows, i) => ({
    label: `■ ${sets[i].name}（${sets[i].list.length}）`,
    count: sets[i].list.length,
    rows: rows.map(t => {
      const { cells, beyond } = ganttCells(t, g.days)
      return `${fitCells(t.id, idW)} ${fitCells(t.title, titleW)} ${cells}${beyond ? '→' : ''}`
    }),
  }))
  const loops = g.tasks.filter(t => t.state === STATE_LOOP).length
  const parts = [g.waiting > 0 ? `${STATE_WAIT} ${g.waiting}` : '', loops > 0 ? `${STATE_LOOP} ${loops}` : ''].filter(Boolean)
  return {
    head: `これから2週間（${md(g.days[0].date)}〜${md(g.days[g.days.length - 1].date)}）`,
    overdueLine,
    axis: lead + g.days.map(d => d.date.slice(-1)).join(''),
    groups,
    waitLine: parts.length ? `${parts.join('・')}（棒なし）` : '',
    more: draw.length - shownAll.length,
    drawn: draw.length,
  }
}

// これから2週間のガントチャートに切り替える
async function showGantt($: EngineInterface): Promise<{ isPlaced: boolean; g: Gantt }> {
  await refreshGantt($)
  await update($, detail, () => NONE)
  await update($, view, () => ({ mode: 'gantt', page: 0 }))
  const { isPlaced } = await $.ui.open({ id: PANE, title: GANTT_TITLE })
  return { isPlaced, g: await read($, gantt) }
}

// 日本時間の「何分目」（今の予定・終わった予定の色分けに使う）
const minOf = (ms: number) => Math.floor(((ms + 9 * 3600e3) % 86400e3) / 60000)
const toMin = (hhmm: string) => (hhmm ? Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5)) : -1)

async function refreshCal($: EngineInterface, now: number, CAL_FILE: string) {
  const today = dayOf(now)
  let next: Cal
  try {
    const c = JSON.parse(await $.fs.read(CAL_FILE))
    const events: CalEvent[] = (c.events ?? [])
      .filter((e: any) => e.date === today)
      .map((e: any) => ({ start: e.start ?? '', end: e.end ?? '', title: e.title ?? '', allday: !!e.allday, unknown: e.time_unknown === true }))
    const fetched = String(c.fetched ?? '')
    // 今日より前に取った予定しか無いときは、読めていないものとして扱う（「予定なし」と見せない）
    const stale = fetched.slice(0, 10) < today
    next = { fetched, events, nowMin: minOf(now), error: stale ? `予定を読めていません（最後の取得 ${md(fetched.slice(0, 10))} ${fetched.slice(11)}）` : '' }
  } catch {
    next = { ...NO_CAL, error: '予定を読めませんでした' }
  }
  const cur = await read($, cal)
  // 5分ごとに「今」の位置を進める。中身が変わらなければ描き直さない
  const same = JSON.stringify({ ...cur, nowMin: 0 }) === JSON.stringify({ ...next, nowMin: 0 })
  if (same && Math.floor(cur.nowMin / 5) === Math.floor(next.nowMin / 5)) return
  await update($, cal, () => next)
}

async function refresh($: EngineInterface, force = false) {
  // 本人のフォルダが見つかっていなければ、何もしない
  if (!me) return
  const { file: FILE, calFile, hasCal, owner } = me
  const now = await $.clock.now()
  const today = dayOf(now)
  if (hasCal) await refreshCal($, now, calFile).catch(() => undefined)
  // ガントチャートを開いているあいだは、forecast.json が作り直されたら読み直す
  if ((await read($, view)).mode === 'gantt') await refreshGantt($).catch(() => undefined)
  const stat = await $.fs.stat(FILE).catch(() => undefined)
  if (!stat) {
    await update($, board, () => ({ ...EMPTY, today, error: 'tasks.json が見つかりません' }))
    return
  }
  const last = await read($, mtime)
  const cur = await read($, board)
  if (!force && stat.mtimeMs === last && cur.today === today) return
  try {
    const data = JSON.parse(await $.fs.read(FILE))
    await update($, board, () => build(data, today, owner))
    await update($, mtime, () => stat.mtimeMs)
  } catch {
    // 書き込みの途中などで読めなかったときは、前の表示のまま次の確認を待つ。
    // ただし前の表示がまだ無いときは、「0件・なし」と誤って見せないよう、エラーを入れる
    if (cur.today === '') await update($, board, () => ({ ...EMPTY, today, error: 'tasks.json を読めませんでした' }))
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    // 本人のフォルダが見つからなければ、命令・道具・パネル・更新のどれも登録しない
    me = await findMe($)
    if (!me) return next(e)
    await $.command.register({ name: 'yarukoto', description: `今日のやること（${me.call}・AI）を右のパネルに出す` })
    await $.command.register({ name: 'task', description: '指定のタスク（例：/task T013）を右のパネルに開く' })
    await $.tool
      .register({
        name: 'open_task',
        description:
          'あなたの右のパネルに、指定したタスク（tasks.json の ID。例 T013）の詳細を開く。「T013 開いて」と言われたときに使う。試し中の Try の ID（Y で始まる。例 Y20261106-2）も渡せる（「Y20261106-2 開いて」）。id を空にすると一覧に戻る',
        inputSchema: {
          type: 'object',
          properties: { id: { type: 'string', description: 'タスクID（例 T013）か、試し中の Try の ID（例 Y20261106-2）。空なら一覧に戻る' } },
        },
        isDeferred: false,
      })
      .catch(() => undefined)
    await $.tool
      .register({
        name: 'show_all_tasks',
        description:
          'あなたの右のパネルを、全部のタスクの一覧（未完了→完了の順、ページ送りあり）に切り替える。「タスク全部見せて」と言われたときに使う。短い画面に戻すのは open_task（id を空にする）',
        inputSchema: { type: 'object', properties: {} },
        isDeferred: false,
      })
      .catch(() => undefined)
    await $.tool
      .register({
        name: 'show_gantt',
        description:
          '右のパネルを、これから2週間のガントチャートに切り替える。「ガント見せて」と言われたときに使う。短い画面に戻すのは open_task（id を空にする）',
        inputSchema: { type: 'object', properties: {} },
        isDeferred: false,
      })
      .catch(() => undefined)
    await refresh($, true).catch(() => undefined)
    await update($, detail, () => NONE)
    // 最初の画面：今日の forecast.json が読めればガント、読めなければ短い画面
    await refreshGantt($).catch(() => undefined)
    const first = (await read($, gantt)).ok
    await update($, view, () => (first ? { mode: 'gantt', page: 0 } : HOME))
    void $.ui.open({ id: PANE, title: first ? GANTT_TITLE : TITLE })
    $.clock.every(20000, () => refresh($))
    return next(e)
  })

  on('command.run', { command: 'yarukoto' }, async $ => {
    if (!me) return { text: NO_HOME }
    await home($)
    return { text: '今日のやることを右に出しました。' }
  })

  on('command.run', { command: 'task' }, async ($, e) => {
    if (!me) return { text: NO_HOME }
    if (!e.args.trim()) {
      await home($)
      return { text: '一覧に戻しました。' }
    }
    const d = await show($, e.args)
    return { text: d.error || `${d.id} を右に開きました。` }
  })

  on('tool.call', { tool: 'mcp__ai-bunshin-panel__open_task' }, async ($, e) => {
    if (!me) return { result: NO_HOME }
    const id = String((e as any).id ?? '').trim()
    if (!id) {
      await home($)
      return { result: '一覧に戻しました。' }
    }
    const d = await show($, id)
    if (d.error) return { result: d.error }
    return {
      result: d.isPlaced
        ? `${d.id}「${d.title}」を右のパネルに開きました。`
        : `${d.id} を開きましたが、画面が狭くて右のパネルが出ていません。/task ${d.id} と打つと、どの幅でも出ます。`,
    }
  })

  on('tool.call', { tool: 'mcp__ai-bunshin-panel__show_all_tasks' }, async $ => {
    if (!me) return { result: NO_HOME }
    const { isPlaced, count } = await showAll($)
    return {
      result: isPlaced
        ? `全部のタスク（${count}件）を右のパネルに出しました。ページ送りのボタンで見られます。`
        : '切り替えましたが、画面が狭くて右のパネルが出ていません。',
    }
  })

  on('tool.call', { tool: 'mcp__ai-bunshin-panel__show_gantt' }, async $ => {
    if (!me) return { result: NO_HOME }
    const { isPlaced, g } = await showGantt($)
    if (!g.ok) return { result: g.message }
    const n = ganttSplit(g).draw.length
    return {
      result: isPlaced
        ? `これから2週間のガントチャート（${n}件）を右のパネルに出しました。`
        : '切り替えましたが、画面が狭くて右のパネルが出ていません。',
    }
  })

  // tasks.json を書き換えたあとは、すぐ表示を更新する
  on('tool.call', async ($, e, next) => {
    const ran = await next(e)
    if (e.tool === 'Edit' || e.tool === 'Write' || e.tool === 'Bash') await refresh($).catch(() => undefined)
    return ran
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e, next) => {
    if (!me) return next(e)
    const { call, hasCal } = me
    const { Box, Text, Button } = $.ui.resolve(e)
    const d = await read($, detail)
    if (d.id && !d.error) {
      return (
        <Box flexDirection="column">
          <Text bold wrap="wrap">
            {d.id} {d.title}
          </Text>
          <Text> </Text>
          {d.lines.map(l => (
            <Text key={l.label} wrap="wrap">
              <Text bold>{l.label}：</Text>
              {l.text}
            </Text>
          ))}
          {d.steps.length > 0 && <Text> </Text>}
          {d.steps.length > 0 && <Text bold>手順</Text>}
          {d.steps.map((s, i) => (
            <Text key={`step${i}`} wrap="wrap">
              {i + 1}. {s}
            </Text>
          ))}
          <Text> </Text>
          <Button key="back" label={d.id.startsWith('Y') ? '← 一覧に戻る' : '← 戻る'} onPress={() => void back($)} />
        </Box>
      )
    }

    const b = await read($, board)
    const v = await read($, view)

    if (v.mode === 'gantt') {
      const g = await read($, gantt)
      const show = g.ok ? ganttLines(g, e.props.bodyColumns, e.props.scroll.bodyRows, call, b.all) : undefined
      return (
        <Box flexDirection="column">
          <Text bold>{show ? show.head : GANTT_TITLE}</Text>
          {!show && <Text color="red" wrap="wrap">{g.message}</Text>}
          {show && <Text dimColor wrap="truncate-end">= AI　* 期日　. 休み　→ 先</Text>}
          {show && show.overdueLine !== '' && <Text wrap="wrap">{show.overdueLine}</Text>}
          {show && <Text dimColor>{show.axis}</Text>}
          {show && show.drawn === 0 && <Text dimColor>棒にできるタスクなし</Text>}
          {show &&
            show.groups.map((grp, gi) => [
              gi > 0 ? <Text key={`gantt-gap-${gi}`}> </Text> : null,
              <Text key={`gantt-head-${gi}`} bold wrap="truncate-end">
                {grp.label}
              </Text>,
              ...grp.rows.map((r, i) => (
                <Text key={`gantt-${gi}-${i}`} wrap="truncate-end">
                  {r}
                </Text>
              )),
            ])}
          {show && show.more > 0 && <Text dimColor>ほか {show.more} 件</Text>}
          {show && show.waitLine !== '' && <Text dimColor wrap="truncate-end">{show.waitLine}</Text>}
          <Button key="home" label="短い画面へ" onPress={() => void home($)} />
        </Box>
      )
    }

    if (v.mode === 'all') {
      // ページ送り：1ページが窓（bodyRows）に収まる行数にする。見出し・ボタン・足元で 5行使う
      const rowsPerPage = Math.max(5, Math.min(40, e.props.scroll.bodyRows - 5))
      const paged = paginate(allLines(b.all), rowsPerPage)
      const pages = paged.length
      const page = Math.min(Math.max(0, v.page), pages - 1)
      const shown = paged[page]
      const openCount = b.all.filter(r => !r.done).length
      const go = (to: number) => void update($, view, () => ({ mode: 'all', page: Math.min(Math.max(0, to), pages - 1) }))
      return (
        <Box flexDirection="column">
          <Text bold>
            全部のタスク {b.all.length} 件（未完了 {openCount}）　{page + 1}/{pages} ページ
          </Text>
          <Box flexDirection="row">
            {page > 0 && <Button key="prev" label="← 前" onPress={() => go(page - 1)} />}
            {page < pages - 1 && <Button key="next" label="次 →" onPress={() => go(page + 1)} />}
            <Button key="home" label="短い画面へ" onPress={() => void home($)} />
            <Button key="gantt" label="ガントへ" onPress={() => void showGantt($)} />
          </Box>
          {b.error !== '' && <Text color="red">{b.error}</Text>}
          {b.all.length === 0 && b.error === '' && <Text dimColor>なし</Text>}
          {shown.map((l, i) =>
            l.kind === 'head' ? (
              <Text key={`all-head-${page}-${i}`} bold dimColor={l.done} wrap="truncate-end">
                {l.text}
              </Text>
            ) : (
              <Button key={`all-${l.r.id}`} plain dimColor={l.r.done} onPress={() => void show($, l.r.id)}>
                <Text wrap="truncate-end" dimColor={l.r.done}>
                  [{l.r.mark}] {l.r.id} {l.r.title}
                  {l.r.who ? ` ・${l.r.who}` : ''}
                  {l.r.due && !l.r.done ? `（${l.r.due}）` : ''}
                </Text>
              </Button>
            ),
          )}
          <Text dimColor>行を押すと詳細</Text>
        </Box>
      )
    }

    const tries = await loadTries($)
    const c = await read($, cal)
    // 予定 1件：「09:00〜09:30 件名」。終わったものは薄く、今のものは太字
    const ev = (e: CalEvent, i: number) => {
      const s = toMin(e.start)
      const t = toMin(e.end)
      const past = !e.allday && t >= 0 ? t <= c.nowMin : !e.allday && s >= 0 && s < c.nowMin
      const nowOn = !e.allday && s >= 0 && s <= c.nowMin && t > c.nowMin
      const when = e.unknown ? '時刻不明' : e.allday ? '終日' : e.end ? `${e.start}〜${e.end}` : e.start
      return (
        <Text key={`cal-${i}`} wrap="truncate-end" dimColor={past} bold={nowOn}>
          {when} {e.title}
        </Text>
      )
    }
    // 行を押すと、そのタスクの詳細を開く
    const line = (sec: string, r: Row, color?: string) => (
      <Button key={`${sec}-${r.id}`} plain onPress={() => void show($, r.id)}>
        <Text wrap="truncate-end" color={color}>
          {r.mark ? `[${r.mark}] ` : ''}
          {r.id} {r.title}
          {r.due && r.mark !== '今日' ? `（${r.due}）` : ''}
        </Text>
      </Button>
    )

    // 区切りの中を「 ◇ カテゴリ」の小見出しで分ける。カテゴリの間に空行 1 行（最初の小見出しの前には入れない）
    const grouped = (sec: string, rows: Row[], one: (r: Row) => any) =>
      groupByCat(rows).flatMap((g, gi) => [
        ...(gi > 0 ? [<Text key={`${sec}-gap-${gi}`}> </Text>] : []),
        <Text key={`${sec}-cat-${gi}`} bold wrap="truncate-end">
          {` ◇ ${g.cat}`}
        </Text>,
        ...g.rows.map(one),
      ])

    return (
      <Box flexDirection="column">
        <Text bold>{md(b.today)} の予定</Text>
        {b.error !== '' && <Text color="red">{b.error}</Text>}
        {d.error !== '' && <Text color="red">{d.error}</Text>}

        {hasCal && <Text bold> </Text>}
        {hasCal && <Text bold>■ 今日の予定{c.fetched && !c.error ? `（${c.fetched.slice(11)} 取得）` : ''}</Text>}
        {hasCal && c.error !== '' && <Text color="red">{c.error}</Text>}
        {hasCal && c.error === '' && c.events.length === 0 && <Text dimColor>予定なし</Text>}
        {hasCal && c.events.map(ev)}

        <Text bold> </Text>
        <Text bold>■ {call}（今日まで）</Text>
        {b.mine.length === 0 && <Text dimColor>なし</Text>}
        {grouped('mine', b.mine, r => line('mine', r, r.mark === '超過' || r.mark === APPROVAL_MARK ? 'red' : undefined))}

        <Text bold> </Text>
        <Text bold>■ AI（今日の計画）</Text>
        {b.ai.length === 0 && <Text dimColor>計画なし</Text>}
        {grouped('ai', b.ai, r =>
          r.mark === '済' ? (
            <Button key={`ai-${r.id}`} plain dimColor onPress={() => void show($, r.id)}>
              <Text dimColor wrap="truncate-end">
                [済] {r.id} {r.title}
              </Text>
            </Button>
          ) : (
            line('ai', r)
          ),
        )}

        <Text bold> </Text>
        <Text bold>■ AI（これから）</Text>
        {b.aiNext.length === 0 && <Text dimColor>なし</Text>}
        {grouped('aiNext', b.aiNext, r => line('aiNext', r))}
        {b.aiNextMore > 0 && <Text dimColor>ほか {b.aiNextMore} 件</Text>}

        {tries.length > 0 && <Text bold> </Text>}
        {tries.length > 0 && <Text bold>■ 試し中の Try（{tries.length}）</Text>}
        {tries.map(t => (
          <Button key={`try-${t.id}`} plain onPress={() => void show($, t.id)}>
            <Text wrap="truncate-end">{[startOf(t.start), t.id, skipNote(t.body)].filter(Boolean).join(' ')}</Text>
          </Button>
        ))}

        <Text bold> </Text>
        <Text bold>■ 近いうちに（{call}）</Text>
        {b.soon.length === 0 && <Text dimColor>なし</Text>}
        {grouped('soon', b.soon, r => line('soon', r, r.mark === APPROVAL_MARK ? 'red' : undefined))}

        <Text bold> </Text>
        <Box flexDirection="row">
          <Button key="gantt" label="ガントへ" onPress={() => void showGantt($)} />
          <Button key="open-all" label="全部のタスクを見る" onPress={() => void showAll($)} />
        </Box>
        <Text dimColor>お願い 残り {b.openRequests} 件 ／ 行を押すと詳細 ／ /task T013 でも開く</Text>
      </Box>
    )
  })
}
