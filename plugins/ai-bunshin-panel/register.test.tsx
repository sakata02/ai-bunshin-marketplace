import { expect, test } from 'claude-code/testing'

// 本人のフォルダ（設定/config.json と 00_タスク管理/data/tasks.json がある所）。名前は山田
const HOME = '/work/yamada-folder'

// 未完了 12 件（本人 2・AI 10）＋ 完了 8 件
const tasks = [
  ...Array.from({ length: 12 }, (_, i) => ({
    id: `T${String(i + 1).padStart(3, '0')}`,
    title: `未完了${i + 1}`,
    assignee: i < 2 ? '山田' : 'dev-a',
    status: 'ToDo',
    priority: i + 1,
  })),
  ...Array.from({ length: 8 }, (_, i) => ({
    id: `T${String(i + 20).padStart(3, '0')}`,
    title: `完了${i + 1}`,
    assignee: 'buka-a',
    status: '完了',
  })),
]

const PANE = {
  plugin: 'ai-bunshin-panel',
  component: 'Pane',
  requestId: 'ai-bunshin-panel',
  props: {
    title: '今日のやること',
    isFocused: false,
    bodyColumns: 40,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 10 },
    view: {},
  },
} as const

// 準備。状態は後から書き換えられる。cwd は本人のフォルダ（既定）か、その下・外のフォルダ。
// cfg が undefined なら config.json が無い。cfg が文字列ならそのまま返す（BOM 付きなどに使う）
type Src = {
  data: unknown
  hasFile?: boolean
  mtime?: number
  cal?: unknown
  cfg?: unknown
  cwd?: string
  startFile?: boolean
  forecast?: unknown // forecast.json の中身（文字ならそのまま。undefined なら読めない）
  home?: string // 本人のフォルダ（既定は HOME）。Windows の形（C:\\…）も渡せる
}
const CFG = { owner: '山田', owner_call: '山田さん', calendar: { type: 'ics' } }
async function setup($: any, on: any, s: Src) {
  s.hasFile ??= true
  s.mtime ??= 1
  if (!('cfg' in s)) s.cfg = CFG
  const titles: string[] = []
  const descs: string[] = []
  const tools: { name: string; description: string }[] = []
  const home = s.home ?? HOME
  // fs.stat が答えるパスは、home と同じ区切りで組む（Windows の形なら \\）
  const sep = home.includes('\\') && !home.includes('/') ? '\\' : '/'
  const join = (rel: string) => home + sep + rel.replace(/\//g, sep)
  const statPaths: string[] = []
  const n = { command: 0, tool: 0, open: 0, every: 0, writes: 0, tasksReads: 0, calReads: 0, forecastReads: 0 }
  const want = s.hasFile
  on('command.register', (_: any, e: any) => {
    n.command++
    descs.push(String(e.description ?? ''))
    return { value: { command: 'x' } }
  })
  on('tool.register', (_: any, e: any) => {
    n.tool++
    tools.push({ name: String(e.name ?? ''), description: String(e.description ?? '') })
    return { value: { name: 'x' } }
  })
  on('ui.open', (_: any, e: any) => {
    n.open++
    titles.push(e.title)
    return { value: { isPlaced: true } }
  })
  on('fs.stat', (_: any, e: any) => {
    // テストの土台は、/ で始まらないパス（C:\… など）の前に今のフォルダをつなげて渡す。その前の部分を除く
    const p = String(e.path).replace(/^.*?\/(?=[A-Za-z]:[\\/]|\\\\)/, '')
    statPaths.push(p)
    if (p === join('設定/config.json')) return s.cfg === undefined ? { deny: 'none' } : { value: { mtimeMs: 1 } }
    if (p === join('00_タスク管理/data/tasks.json')) return s.hasFile ? { value: { mtimeMs: s.mtime } } : { deny: 'none' }
    return { deny: 'none' }
  })
  on('fs.read', (_: any, e: any) => {
    const p = String(e.path)
    if (p.endsWith('config.json')) return { value: typeof s.cfg === 'string' ? s.cfg : JSON.stringify(s.cfg) }
    if (p.includes('calendar')) {
      n.calReads++
      if (s.cal === undefined) throw new Error('none')
      return { value: JSON.stringify(s.cal) }
    }
    if (p.endsWith('forecast.json')) {
      n.forecastReads++
      if (s.forecast === undefined) throw new Error('none')
      return { value: typeof s.forecast === 'string' ? s.forecast : JSON.stringify(s.forecast) }
    }
    n.tasksReads++
    return { value: typeof s.data === 'string' ? s.data : JSON.stringify(s.data) }
  })
  on('fs.write', () => {
    n.writes++
    return { value: undefined }
  })
  on('clock.now', () => ({ value: Date.parse('2026-11-02T01:00:00Z') }))
  on('clock.every', () => {
    n.every++
    return { value: undefined }
  })
  on('tool.call', () => ({ result: {} }))
  on('session.cwd', () => ({ value: s.cwd ?? home }))
  on('session.start', (_: any, e: any) => ({ cwd: e.cwd }))
  // 起動のときは tasks.json がある（本人のフォルダとして見つかる）。そのあと消す・壊す試しができる
  s.hasFile = s.startFile ?? true
  await $.session.start({ cwd: s.cwd ?? home, surface: 'terminal', isInteractive: true })
  s.hasFile = want
  return { titles, n, s, descs, statPaths, tools }
}

test('全部のタスクに切り替え、ページを送り、短い画面に戻る。tasks.json は書かない', async ($, on) => {
  const { n } = await setup($, on, { data: { tasks, daily_sprints: [] } })

  // ふだんの画面：全部は出ない（20 件ぶんの行が並ばない）
  let ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /今日の予定/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /\[済\]/ })).toBeFalsy()
  await ui.unmount()

  const r = await $.tool.call({ tool: 'mcp__ai-bunshin-panel__show_all_tasks' })
  expect(JSON.stringify(r)).toContain('20件')

  // bodyRows 10 → 1 ページ 5 行。見出し（■ 未分類（12）・■ 完了（8））も 1 行に数えるので、22 行 → 5 ページ（T134 で 4 → 5）
  ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /全部のタスク/ }))?.text).toContain('1/5')
  expect((await ui.find({ type: 'Text', text: /全部のタスク/ }))?.text).toContain('未完了 12')
  expect(await ui.find({ type: 'Text', text: /■ 未分類（12）/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /未完了1 / })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /未完了6 / })).toBeFalsy()
  expect(await ui.find({ type: 'Button', text: /次/ })).toBeTruthy()
  expect(await ui.find({ type: 'Button', text: /前/ })).toBeFalsy()
  await ui.press({ key: 'next' })
  expect((await ui.find({ type: 'Text', text: /全部のタスク/ }))?.text).toContain('2/5')
  expect(await ui.find({ type: 'Text', text: /未完了6 / })).toBeTruthy()
  await ui.press({ key: 'next' })
  await ui.press({ key: 'next' })
  await ui.press({ key: 'next' })
  expect((await ui.find({ type: 'Text', text: /全部のタスク/ }))?.text).toContain('5/5')
  expect(await ui.find({ type: 'Text', text: /\[済\].*完了3/ })).toBeTruthy()
  // 最終ページでは「次 →」が出ない
  expect(await ui.find({ type: 'Button', text: /次/ })).toBeFalsy()
  await ui.press({ key: 'home' })
  expect(await ui.find({ type: 'Text', text: /今日の予定/ })).toBeTruthy()
  await ui.unmount()

  // open_task の id を空にすると短い画面に戻る
  await $.tool.call({ tool: 'mcp__ai-bunshin-panel__show_all_tasks' })
  const back = await $.tool.call({ tool: 'mcp__ai-bunshin-panel__open_task', id: '' })
  expect(JSON.stringify(back)).toContain('一覧に戻しました')
  ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /今日の予定/ })).toBeTruthy()
  await ui.unmount()

  expect(n.writes).toBe(0)
})

const open = (n: number) => ({
  tasks: Array.from({ length: n }, (_, i) => ({
    id: `T${String(i + 1).padStart(3, '0')}`,
    title: `件${i + 1}`,
    assignee: 'dev-a',
    status: 'ToDo',
    priority: i + 1,
  })),
  daily_sprints: [],
})
const heading = async (ui: any) => (await ui.find({ type: 'Text', text: /全部のタスク/ }))?.text as string

test('全部のタスクが 0 件のとき：1/1 ページで「なし」。次・前は出ない', async ($, on) => {
  await setup($, on, { data: { tasks: [], daily_sprints: [] }, hasFile: true, mtime: 1 })
  await $.tool.call({ tool: 'mcp__ai-bunshin-panel__show_all_tasks' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await heading(ui)).toContain('1/1')
  expect(await ui.find({ type: 'Text', text: /^なし$/ })).toBeTruthy()
  expect(await ui.find({ type: 'Button', text: /次/ })).toBeFalsy()
  expect(await ui.find({ type: 'Button', text: /前/ })).toBeFalsy()
  await ui.unmount()
})

test('全部のタスクで tasks.json が無いとき：赤いエラー文を出し「なし」は出さない', async ($, on) => {
  await setup($, on, { data: {}, hasFile: false, mtime: 1 })
  await $.tool.call({ tool: 'mcp__ai-bunshin-panel__show_all_tasks' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /tasks\.json が見つかりません/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /^なし$/ })).toBeFalsy()
  await ui.unmount()
})

test('tasks.json はあるが JSON が壊れているとき：最初は赤いエラー文（「なし」は出ない）。前の表示があれば保持', async ($, on) => {
  const src: Src = { data: '{broken', hasFile: true, mtime: 1 }
  await setup($, on, src)
  await $.tool.call({ tool: 'mcp__ai-bunshin-panel__show_all_tasks' })
  let ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /tasks\.json を読めませんでした/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /^なし$/ })).toBeFalsy()
  await ui.unmount()

  // 読めるようになる → 表示が出てエラーが消える。そのあと壊れても前の表示のまま
  src.data = open(3)
  src.mtime = 2
  await $.tool.call({ tool: 'mcp__ai-bunshin-panel__show_all_tasks' })
  ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /件3/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /読めませんでした/ })).toBeFalsy()
  await ui.unmount()

  src.data = '{broken'
  src.mtime = 3
  await $.tool.call({ tool: 'mcp__ai-bunshin-panel__show_all_tasks' })
  ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /件3/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /読めませんでした/ })).toBeFalsy()
  await ui.unmount()
})

test('端数のある最終ページ：21 件・見出しも 1 行に数えて 6 ページ。最後は「（続き）」の見出しと 1 行（T134 で 5 → 6）', async ($, on) => {
  await setup($, on, { data: open(21), hasFile: true, mtime: 1 })
  await $.tool.call({ tool: 'mcp__ai-bunshin-panel__show_all_tasks' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await heading(ui)).toContain('1/6')
  for (let i = 0; i < 5; i++) await ui.press({ key: 'next' })
  expect(await heading(ui)).toContain('6/6')
  expect(await ui.find({ type: 'Text', text: /■ 未分類（21）（続き）/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /件21/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /件20/ })).toBeFalsy()
  expect(await ui.find({ type: 'Button', text: /次/ })).toBeFalsy()
  await ui.unmount()
})

test('件数が減ったとき：2 ページ目にいても最後のページに収まる', async ($, on) => {
  const src: Src = { data: open(20), hasFile: true, mtime: 1 }
  await setup($, on, src)
  await $.tool.call({ tool: 'mcp__ai-bunshin-panel__show_all_tasks' })
  let ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'next' })
  expect(await heading(ui)).toContain('2/5')
  await ui.unmount()

  src.data = open(3)
  src.mtime = 2
  await $.tool.call({ tool: 'Bash' }) // tasks.json を書き換えたあとの更新（ページは動かさない）
  ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await heading(ui)).toContain('1/1')
  expect(await ui.find({ type: 'Text', text: /件3/ })).toBeTruthy()
  await ui.unmount()
})

test('全部の一覧から詳細を開いて戻ると、タイトルは「全部のタスク」。短い画面からなら「今日のやること」', async ($, on) => {
  const { titles } = await setup($, on, { data: open(3), hasFile: true, mtime: 1 })
  await $.tool.call({ tool: 'mcp__ai-bunshin-panel__show_all_tasks' })
  await $.tool.call({ tool: 'mcp__ai-bunshin-panel__open_task', id: 'T001' })
  expect(titles.at(-1)).toBe('T001 の詳細')
  let ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'back' })
  expect(titles.at(-1)).toBe('全部のタスク')
  await ui.unmount()

  await $.tool.call({ tool: 'mcp__ai-bunshin-panel__open_task', id: '' }) // 短い画面へ
  await $.tool.call({ tool: 'mcp__ai-bunshin-panel__open_task', id: 'T001' })
  ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'back' })
  expect(titles.at(-1)).toBe('今日のやること')
  await ui.unmount()
})

test('今日の予定：time_unknown の予定は「時刻不明」。ふつうの予定・終日の出方は変わらない', async ($, on) => {
  // 今は 2026-11-02 10:00（日本時間）。calendar_today.py のキャッシュと同じ形
  const cal = {
    fetched: '2026-11-02 09:00',
    events: [
      { date: '2026-11-02', start: '', end: '', title: '時刻不明の会議', allday: false, time_unknown: true },
      { date: '2026-11-02', start: '13:00', end: '14:00', title: 'ふつうの会議', allday: false },
      { date: '2026-11-02', start: '', end: '', title: '終日の予定', allday: true },
      { date: '2026-11-03', start: '', end: '', title: '明日の不明', allday: false, time_unknown: true },
    ],
  }
  await setup($, on, { data: open(1), hasFile: true, mtime: 1, cal })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /時刻不明の会議/ }))?.text).toBe('時刻不明 時刻不明の会議')
  expect((await ui.find({ type: 'Text', text: /ふつうの会議/ }))?.text).toBe('13:00〜14:00 ふつうの会議')
  expect((await ui.find({ type: 'Text', text: /終日の予定/ }))?.text).toBe('終日 終日の予定')
  expect(await ui.find({ type: 'Text', text: /明日の不明/ })).toBeFalsy()
  await ui.unmount()
})

const today = '2026-11-02'
const mineData = (owner: string) => ({
  tasks: [
    { id: 'T001', title: '本人の今日のお願い', assignee: owner, status: 'ToDo', due: today, kind: '判断', priority: 1 },
    { id: 'T002', title: '別の人の今日の分', assignee: '山田', status: 'ToDo', due: today, priority: 2 },
    { id: 'T003', title: '本人の近いお願い', assignee: owner, status: 'ToDo', due: '2026-11-04', kind: '確認', priority: 3 },
  ],
  daily_sprints: [],
})

test('config の owner で絞り込む：別の名前（鈴木）でも、その人の分が「今日まで」に出る。呼び方は owner_call', async ($, on) => {
  await setup($, on, { data: mineData('鈴木'), cfg: { owner: '鈴木', owner_call: '鈴木さん' } })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /■ 鈴木さん（今日まで）/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /■ 近いうちに（鈴木さん）/ })).toBeTruthy()
  // 「今日まで」の印（[今日]）が付くのは鈴木の T001 だけ。山田の T002 は本人の分に入らない
  expect(await ui.find({ type: 'Text', text: /\[今日\] T001/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /\[今日\] T002/ })).toBeFalsy()
  expect(await ui.find({ type: 'Text', text: /お願い 残り 2 件/ })).toBeTruthy()
  await ui.unmount()
})

test('owner_call が無いとき：owner に「さん」を付けて呼ぶ（命令の説明にも）。あれば owner_call を使う', async ($, on) => {
  const a = await setup($, on, { data: mineData('鈴木'), cfg: { owner: '鈴木' } })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /■ 鈴木さん（今日まで）/ })).toBeTruthy()
  await ui.unmount()
  expect(a.descs.join('|')).toContain('鈴木さん')
})

test('owner_call があるとき：その呼び方を使う', async ($, on) => {
  await setup($, on, { data: mineData('鈴木'), cfg: { owner: '鈴木', owner_call: '鈴木先生' } })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /■ 鈴木先生（今日まで）/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /■ 鈴木さん/ })).toBeFalsy()
  await ui.unmount()
})

test('BOM 付きの config.json も読める', async ($, on) => {
  const { n } = await setup($, on, { data: mineData('山田'), cfg: '\uFEFF' + JSON.stringify(CFG) })
  expect(n.command).toBe(2)
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /■ 山田さん（今日まで）/ })).toBeTruthy()
  await ui.unmount()
})

// 本人のフォルダが見つからないとき：命令・道具・パネル・更新のどれも登録しない
async function expectNothing($: any, on: any, src: Src) {
  const { n } = await setup($, on, src)
  expect({ command: n.command, tool: n.tool, open: n.open, every: n.every }).toEqual({ command: 0, tool: 0, open: 0, every: 0 })
  // Bash などのあとの更新も、すぐ戻って tasks.json も予定も読まない
  await $.tool.call({ tool: 'Bash' })
  await $.tool.call({ tool: 'Write' })
  expect(n.tasksReads).toBe(0)
  expect(n.calReads).toBe(0)
  expect(n.writes).toBe(0)
  // 道具・命令が呼ばれても、パネルは開かない
  const r = await $.tool.call({ tool: 'mcp__ai-bunshin-panel__open_task', id: 'T001' })
  expect(JSON.stringify(r)).toContain('本人のフォルダ')
  expect(n.open).toBe(0)
}

test('config.json の無いフォルダでは、命令・道具・パネルを登録しない', async ($, on) => {
  await expectNothing($, on, { data: open(3), cfg: undefined })
})

test('tasks.json の無いフォルダ（config.json だけ）でも登録しない', async ($, on) => {
  await expectNothing($, on, { data: open(3), startFile: false })
})

test('config.json が壊れているときは何も出さない', async ($, on) => {
  await expectNothing($, on, { data: open(3), cfg: '{broken' })
})

test('本人のフォルダの外（どこにも config が無い）では何も出さない', async ($, on) => {
  await expectNothing($, on, { data: open(3), cwd: '/work/other' })
})

test('本人のフォルダの下（05_開発/x）で開いても、本人のフォルダを見つける', async ($, on) => {
  const { n } = await setup($, on, { data: open(3), cwd: `${HOME}/05_開発/x` })
  expect(n.command).toBe(2)
  expect(n.tool).toBe(3) // open_task・show_all_tasks・show_gantt
  expect(n.open).toBeGreaterThan(0)
  expect(n.every).toBe(1)
  await $.tool.call({ tool: 'mcp__ai-bunshin-panel__show_all_tasks' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await heading(ui)).toContain('1/1')
  await ui.unmount()
})

test('6段下までは見つける', async ($, on) => {
  const six = await setup($, on, { data: open(1), cwd: `${HOME}/a/b/c/d/e/f` })
  expect(six.n.command).toBe(2)
})

test('7段下では見つけない', async ($, on) => {
  const { n } = await setup($, on, { data: open(1), cwd: `${HOME}/a/b/c/d/e/f/g` })
  expect(n.command).toBe(0)
  expect(n.open).toBe(0)
  expect(n.every).toBe(0)
})

test('config に calendar が無いとき：予定の節を出さず、予定のキャッシュも読まない', async ($, on) => {
  const cal = { fetched: '2026-11-02 09:00', events: [{ date: today, start: '13:00', end: '14:00', title: 'ふつうの会議', allday: false }] }
  const { n } = await setup($, on, { data: open(1), cal, cfg: { owner: '山田', owner_call: '山田さん' } })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /■ 山田さん（今日まで）/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /今日の予定/ })).toBeFalsy()
  expect(await ui.find({ type: 'Text', text: /ふつうの会議/ })).toBeFalsy()
  expect(await ui.find({ type: 'Text', text: /予定なし|予定を読め/ })).toBeFalsy()
  await ui.unmount()
  await $.tool.call({ tool: 'Bash' })
  expect(n.calReads).toBe(0)
})

test('config に calendar があるとき：予定の節が出て、キャッシュを読む', async ($, on) => {
  const cal = { fetched: '2026-11-02 09:00', events: [{ date: today, start: '13:00', end: '14:00', title: 'ふつうの会議', allday: false }] }
  const { n } = await setup($, on, { data: open(1), cal })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /■ 今日の予定/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /ふつうの会議/ })).toBeTruthy()
  await ui.unmount()
  expect(n.calReads).toBeGreaterThan(0)
})

// Windows の形のパス（区切りは \）。$.session.cwd() が実際にどの区切りで返るかは確かめられないので、
// \ でも / でも動くことをテストで押さえる
const WHOME = 'C:\\work\\home'

test('Windows のパス：05_開発\\x から上へたどって本人のフォルダを見つける', async ($, on) => {
  const { n, statPaths } = await setup($, on, { data: mineData('山田'), home: WHOME, cwd: `${WHOME}\\05_開発\\x` })
  expect(n.command).toBe(2)
  expect(n.every).toBe(1)
  expect(statPaths).toContain(`${WHOME}\\05_開発\\x\\設定\\config.json`)
  expect(statPaths).toContain(`${WHOME}\\設定\\config.json`)
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /■ 山田さん（今日まで）/ })).toBeTruthy()
  await ui.unmount()
})

test('Windows のパス：/ 区切りの C:/work/home でも見つける', async ($, on) => {
  const { n } = await setup($, on, { data: open(1), home: 'C:/work/home', cwd: 'C:/work/home/05_開発/x' })
  expect(n.command).toBe(2)
})

test('Windows のパス：別のドライブ（D:\\other）では見つけない', async ($, on) => {
  const { n, statPaths } = await setup($, on, { data: open(1), home: WHOME, cwd: 'D:\\other' })
  expect(n.command).toBe(0)
  expect(n.open).toBe(0)
  // D: の中だけを調べて、C: のほうは見に行かない
  expect(statPaths.length).toBeGreaterThan(0)
  expect(statPaths.every(p => p.startsWith('D:\\'))).toBe(true)
})

test('Windows のパス：ドライブの根（C:\\）で止まる（上へ回り続けない）', async ($, on) => {
  const { n, statPaths } = await setup($, on, { data: open(1), home: 'C:\\work\\home', cwd: 'C:\\' })
  expect(n.command).toBe(0)
  // C:\ の config.json を1回調べて終わり（根より上は無い）
  expect(statPaths).toEqual(['C:\\設定\\config.json'])
})

test('Windows のパス：UNC（\\\\server\\share）は share より上へ行かない', async ($, on) => {
  const { n, statPaths } = await setup($, on, { data: open(1), home: 'C:\\work\\home', cwd: '\\\\server\\share\\a\\b' })
  expect(n.command).toBe(0)
  expect(statPaths).toEqual([
    '\\\\server\\share\\a\\b\\設定\\config.json',
    '\\\\server\\share\\a\\設定\\config.json',
    '\\\\server\\share\\設定\\config.json',
  ])
})

// 調べるパス（fs.stat）は、どれも 設定/config.json か 00_タスク管理/data/tasks.json で終わる（区切りはどちらでも）
const TARGET = /(設定[\\/]config\.json|00_タスク管理[\\/]data[\\/]tasks\.json)$/

test('調べるパス（POSIX）：stat は config.json と tasks.json 以外を調べない', async ($, on) => {
  const { statPaths } = await setup($, on, { data: open(1), cwd: `${HOME}/05_開発/x` })
  expect(statPaths.length).toBeGreaterThan(2)
  for (const p of statPaths) expect(p).toMatch(TARGET)
  expect(statPaths.some(p => /設定\/config\.json$/.test(p))).toBe(true)
  expect(statPaths.some(p => /tasks\.json$/.test(p))).toBe(true)
  expect(statPaths.some(p => p.includes('\\'))).toBe(false)
  // 見つからなかった場合も（フォルダの外）、調べるのは同じ2つだけ
  await $.tool.call({ tool: 'Bash' })
  for (const p of statPaths) expect(p).toMatch(TARGET)
})

test('調べるパス（Windows）：stat は config.json と tasks.json 以外を調べず、区切りは \\ にそろう', async ($, on) => {
  const { statPaths } = await setup($, on, { data: open(1), home: WHOME, cwd: `${WHOME}\\05_開発\\x` })
  expect(statPaths.length).toBeGreaterThan(2)
  for (const p of statPaths) expect(p).toMatch(TARGET)
  expect(statPaths.some(p => /設定\\config\.json$/.test(p))).toBe(true)
  expect(statPaths.some(p => /tasks\.json$/.test(p))).toBe(true)
  expect(statPaths.some(p => p.includes('/'))).toBe(false)
})

// ---------- これから2週間のガントチャート（T118）。forecast.json を読むだけ ----------

const GT = 'mcp__ai-bunshin-panel__show_gantt'
// 今日は 2026-11-02（月）。14 日ぶん。休みは土日（11/7・8・14・15）。テストの側でも暦は計算せず、日付の文字を並べるだけにする
const GDAYS = Array.from({ length: 14 }, (_, i) => {
  const d = new Date(Date.parse('2026-11-02T00:00:00Z') + i * 86400e3)
  const wd = d.getUTCDay()
  return { date: d.toISOString().slice(0, 10), off: wd === 0 || wd === 6 }
})
type FT = { id: string; title: string; who: string; start: string | null; end: string | null; state: string }
const ft = (id: string, title: string, who: string, start: string | null, end: string | null, state = '順調'): FT => ({
  id,
  title,
  who,
  start,
  end,
  state,
})
const fcFile = (tasks: FT[], over: Record<string, unknown> = {}) => ({
  made: '2026-11-02 09:00',
  today: '2026-11-02',
  velocity: 2,
  days: GDAYS,
  tasks,
  waiting: tasks.filter(t => t.state === '見積もり待ち').length,
  ...over,
})
// 画面での幅（テストの側の数え方。全角・絵文字は 2）
// 全角（かな・漢字・全角記号・絵文字）は 2、半角カナは 1（パネルも同じ）。切ったしるしの「~」は幅1に決まっている
const wcols = (s: string) =>
  [...s].reduce((w, ch) => {
    const c = ch.codePointAt(0)!
    return w + (c > 0xffff || (c >= 0x2e80 && c <= 0xa4cf) || (c >= 0xff01 && c <= 0xff60) || (c >= 0xffe0 && c <= 0xffe6) ? 2 : 1)
  }, 0)
const TALL = { ...PANE.props, scroll: { offset: 0, bodyRows: 30 } } // 行が多くても全部出る高さ
const ganttRows = async (ui: any) =>
  ((await ui.findAll({ type: 'Text', text: /^T\d+ / })) as { text: string }[]).map(r => r.text)

test('ガント：新しい道具 show_gantt が登録され、説明は決めたとおり。切り替えて短い画面に戻せる', async ($, on) => {
  const { tools, titles, n } = await setup($, on, { data: open(2), forecast: fcFile([ft('T001', '実装', 'AI', '2026-11-02', '2026-11-03')]) })
  const g = tools.find(t => t.name === 'show_gantt')
  expect(g?.description).toBe(
    '右のパネルを、これから2週間のガントチャートに切り替える。「ガント見せて」と言われたときに使う。短い画面に戻すのは open_task（id を空にする）',
  )
  const r = await $.tool.call({ tool: GT })
  expect(JSON.stringify(r)).toContain('ガントチャート')
  expect(titles.at(-1)).toBe('これから2週間')
  let ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /これから2週間/ }))?.text).toBe('これから2週間（11/2〜11/15）')
  expect((await ui.find({ type: 'Text', text: /^= AI/ }))?.text).toBe('= AI　* 期日　. 休み　→ 先')
  await ui.unmount()
  // 短い画面に戻す（open_task の id を空に）
  const back = await $.tool.call({ tool: 'mcp__ai-bunshin-panel__open_task', id: '' })
  expect(JSON.stringify(back)).toContain('一覧に戻しました')
  ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /今日の予定/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /これから2週間/ })).toBeFalsy()
  await ui.unmount()
  expect(n.writes).toBe(0)
})

test('ガント：AI は棒（休みの日は .）、本人は期日に印（*）、2週間の外は右端に →。見積もり待ち・依存の輪は棒にせず件数を出す', async ($, on) => {
  const tasks = [
    ft('T101', 'AI棒', 'AI', '2026-11-04', '2026-11-09'),
    ft('T102', '本人の期日', '本人', null, '2026-11-06'),
    ft('T103', '外へ続く', 'AI', '2026-11-13', '2026-11-20'),
    ft('T104', '外から始まる', 'AI', '2026-11-18', '2026-11-19'),
    ft('T105', '見積もりまだ', 'AI', null, null, '見積もり待ち'),
    ft('T106', '見積もりまだ2', 'AI', '2026-11-03', '2026-11-04', '見積もり待ち'), // 日付が入っていても、状態が見積もり待ちなら棒にしない
    ft('T107', '輪の中', 'AI', null, null, '依存の輪'),
    ft('T108', '本人の外', '本人', null, '2026-11-30'),
  ]
  const { n } = await setup($, on, { data: open(1), forecast: fcFile(tasks) })
  await $.tool.call({ tool: GT })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal', props: TALL })
  const rows = await ganttRows(ui)
  const by = (id: string) => rows.find(r => r.startsWith(id + ' '))!
  // 列は 14 日ぶん：11/2 から数えて、T101 は 11/4〜11/6 が =、土日（11/7・8）が .、11/9 が =、11/14・15 が .
  expect(by('T101')).toMatch(/ {2}===\.\.= {4}\.\.$/)
  expect(by('T102')).toMatch(/ {4}\*\.\. {5}\.\.$/)
  expect(by('T102')).not.toContain('=')
  expect(by('T101')).not.toContain('*')
  // 2週間の外に終わる：棒は右端（休みは .）まで、そのあとに →。外から始まるものは棒なしで →
  expect(by('T103')).toMatch(/ {5}\.\. {4}=\.\.→$/)
  expect(by('T104')).toMatch(/ {5}\.\. {5}\.\.→$/)
  expect(by('T104')).not.toContain('=')
  expect(by('T108')).toMatch(/→$/)
  expect(by('T108')).not.toContain('*')
  // 見積もり待ち・依存の輪は行にならず、件数を1行
  expect(rows.some(r => /T105|T106|T107/.test(r))).toBe(false)
  expect((await ui.find({ type: 'Text', text: /見積もり待ち 2/ }))?.text).toBe('見積もり待ち 2・依存の輪 1（棒なし）')
  expect(rows.length).toBe(5)
  await ui.unmount()
  expect(n.writes).toBe(0)
})

test('ガント：件数が 0 のときは、件数の行を出さない', async ($, on) => {
  await setup($, on, { data: open(1), forecast: fcFile([ft('T101', 'AI棒', 'AI', '2026-11-02', '2026-11-02')]) })
  await $.tool.call({ tool: GT })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /（棒なし）/ })).toBeFalsy()
  expect(await ui.find({ type: 'Text', text: /^T101 / })).toBeTruthy()
  await ui.unmount()
})

// forecast.json が「無い」「壊れている」「形が違う」「古い」：棒を出さず、1行。パネルは落ちず、何も書かない
for (const [label, forecast, msg] of [
  ['無い', undefined, /まだありません.*update_dashboard\.py を動かすと出ます/],
  ['壊れている（JSON でない）', '{broken', /読めませんでした.*update_dashboard\.py を動かし直すと出ます/],
  ['形が違う（days が無い）', { today: '2026-11-02', tasks: [] }, /読めませんでした.*update_dashboard\.py/],
  ['形が違う（配列でない）', '[1,2]', /読めませんでした.*update_dashboard\.py/],
  ['古い（前の日）', fcFile([ft('T101', 'x', 'AI', '2026-11-02', '2026-11-02')], { today: '2026-11-01' }), /古いです（11\/1 作成）.*update_dashboard\.py を動かすと出ます/],
] as [string, unknown, RegExp][]) {
  test(`ガント：forecast.json が${label}ときは、棒を出さず1行を出す（落ちない・書かない）`, async ($, on) => {
    const { n } = await setup($, on, { data: open(2), forecast })
    const r = await $.tool.call({ tool: GT })
    expect(JSON.stringify(r)).toMatch(msg)
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    expect(await ui.find({ type: 'Text', text: msg })).toBeTruthy()
    expect((await ganttRows(ui)).length).toBe(0)
    expect(await ui.find({ type: 'Text', text: /^= AI/ })).toBeFalsy()
    expect(await ui.find({ type: 'Button', text: /短い画面へ/ })).toBeTruthy()
    await ui.unmount()
    expect(n.writes).toBe(0)
  })
}

test('ガント：全角の長いタスク名・半角・絵文字でも、列（棒の始まり）がずれない', async ($, on) => {
  const tasks = [
    ft('T201', 'あ', 'AI', '2026-11-02', '2026-11-02'),
    ft('T202', 'とても長い全角のタスク名でも切って列をそろえる必要があります', 'AI', '2026-11-02', '2026-11-02'),
    ft('T203', 'abcdefghijklmnopqrstuvwxyz0123456789', 'AI', '2026-11-02', '2026-11-02'),
    ft('T204', '🔴絵文字とかなと漢字ｱｲｳ半角カナ混じりの名前', 'AI', '2026-11-02', '2026-11-02'),
    ft('T205', '全角ちょうど十二文字のなまえです。', 'AI', '2026-11-02', '2026-11-02'),
  ]
  await setup($, on, { data: open(1), forecast: fcFile(tasks) })
  await $.tool.call({ tool: GT })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal', props: TALL }) // bodyColumns 40
  const rows = await ganttRows(ui)
  expect(rows.length).toBe(5)
  // 各行：「ID 名前 14 列」。名前の部分まで（最後の 14 列を除く）の幅がどの行でも同じ
  const heads = rows.map(r => wcols(r.slice(0, -14)))
  expect(new Set(heads).size).toBe(1)
  // 全体も 40 列（bodyColumns）に収まる
  for (const r of rows) expect(wcols(r)).toBeLessThanOrEqual(40)
  // 短い名前はそのまま、長い名前は「…」で切れる
  expect(rows[0]).toContain('あ ')
  expect(rows[1]).toContain('~')
  expect(rows[2]).toContain('~')
  expect(rows.some(r => r.includes('…'))).toBe(false) // 幅が環境で違う「…」は使わない
  await ui.unmount()
  // 幅が広ければ名前を長く出す（切り方は幅で決まる）
  const wide = await $.ui.mount({ ...PANE, surface: 'terminal', props: { ...TALL, bodyColumns: 80 } })
  const wrows = await ganttRows(wide)
  expect(wrows[1].length).toBeGreaterThan(rows[1].length)
  expect(new Set(wrows.map(r => wcols(r.slice(0, -14)))).size).toBe(1)
  await wide.unmount()
})

test('ガント：行が多いときは優先順に上から出し、出せない分は「ほか N 件」', async ($, on) => {
  const tasks = Array.from({ length: 8 }, (_, i) => ft(`T3${String(i).padStart(2, '0')}`, `件${i}`, 'AI', '2026-11-02', '2026-11-03'))
  await setup($, on, { data: open(1), forecast: fcFile(tasks) })
  await $.tool.call({ tool: GT })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' }) // bodyRows 10 → 見出し・凡例・日付・ほか・ボタンの 5 行を引いて 4 行（件数のまとめが無いので 1 行余る）
  const rows = await ganttRows(ui)
  expect(rows.map(r => r.slice(0, 4))).toEqual(['T300', 'T301', 'T302', 'T303'])
  expect((await ui.find({ type: 'Text', text: /^ほか/ }))?.text).toBe('ほか 4 件')
  await ui.unmount()
  // 窓が高ければ全部出て、「ほか」は出ない
  const tall = await $.ui.mount({ ...PANE, surface: 'terminal', props: { ...PANE.props, scroll: { offset: 0, bodyRows: 30 } } })
  expect((await ganttRows(tall)).length).toBe(8)
  expect(await tall.find({ type: 'Text', text: /^ほか/ })).toBeFalsy()
  await tall.unmount()
})

test('ガント：forecast.json が作り直されたら、Bash のあとなどに読み直す（開いている間）。ふつうの画面では読まない', async ($, on) => {
  const src: Src = { data: open(1), forecast: fcFile([ft('T101', '前', 'AI', '2026-11-02', '2026-11-02')]) }
  const { n } = await setup($, on, src)
  await $.tool.call({ tool: 'Bash' }) // ふつうの画面：forecast.json は読まない
  expect(n.forecastReads).toBe(0)
  await $.tool.call({ tool: GT })
  let ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /^T101 / })).toBeTruthy()
  await ui.unmount()
  src.forecast = fcFile([ft('T102', '後', 'AI', '2026-11-02', '2026-11-02')])
  await $.tool.call({ tool: 'Bash' })
  ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /^T102 / })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /^T101 / })).toBeFalsy()
  await ui.unmount()
})

test('ガント：開いたあとも、ふつうの画面・全部の一覧・T013 開いて・戻る の動きは変わらない', async ($, on) => {
  const { titles } = await setup($, on, { data: open(3), forecast: fcFile([ft('T001', '実装', 'AI', '2026-11-02', '2026-11-03')]) })
  await $.tool.call({ tool: GT })
  // ガント → 詳細 → 戻る：ガントに戻る
  await $.tool.call({ tool: 'mcp__ai-bunshin-panel__open_task', id: 'T001' })
  expect(titles.at(-1)).toBe('T001 の詳細')
  let ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'back' })
  expect(titles.at(-1)).toBe('これから2週間')
  await ui.unmount()
  // ガント → 全部の一覧 → 短い画面
  await $.tool.call({ tool: 'mcp__ai-bunshin-panel__show_all_tasks' })
  ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /全部のタスク/ })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /これから2週間/ })).toBeFalsy()
  await ui.press({ key: 'home' })
  expect(await ui.find({ type: 'Text', text: /今日の予定/ })).toBeTruthy()
  await ui.unmount()
  // ガントの「短い画面へ」ボタン
  await $.tool.call({ tool: GT })
  ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'home' })
  expect(await ui.find({ type: 'Text', text: /今日の予定/ })).toBeTruthy()
  await ui.unmount()
})

test('ガント：本人のフォルダの外では道具を登録せず、呼ばれても何も読まない', async ($, on) => {
  const { n } = await setup($, on, { data: open(3), cwd: '/work/other', forecast: fcFile([]) })
  expect(n.tool).toBe(0)
  const r = await $.tool.call({ tool: GT })
  expect(JSON.stringify(r)).toContain('本人のフォルダ')
  expect(n.forecastReads).toBe(0)
  expect(n.open).toBe(0)
})

test('ガント（境目）：14日目ちょうどに終わる AI のタスクと、その日が期日の本人のタスクは、→ が付かず * が出る。翌日は → が付く', async ($, on) => {
  const last = GDAYS[13].date // 11/15（14 日目）
  const tasks = [
    ft('T401', '14日目に終わる', 'AI', '2026-11-13', last),
    ft('T402', '14日目が期日', '本人', null, last),
    ft('T403', '15日目に終わる', 'AI', '2026-11-13', '2026-11-16'),
    ft('T404', '15日目が期日', '本人', null, '2026-11-16'),
    ft('T405', '1日目が期日', '本人', null, '2026-11-02'),
  ]
  await setup($, on, { data: open(1), forecast: fcFile(tasks) })
  await $.tool.call({ tool: GT })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal', props: TALL })
  const by = async (id: string) => ((await ganttRows(ui)).find(r => r.startsWith(id + ' ')))!
  // 14 日目（右端の列）まではその列に出て、→ は付かない
  expect(await by('T401')).toMatch(/ {5}\.\. {4}=\.\.$/) // 13 日目（金）が =、14・15 日目（土日）が .
  expect(await by('T402')).toMatch(/ {5}\.\. {5}\.\*$/) // 14 日目（右端の列）に *
  expect(await by('T401')).not.toContain('→')
  expect(await by('T402')).not.toContain('→')
  // 15 日目以降は → （印は出ない）
  expect(await by('T403')).toMatch(/→$/)
  expect(await by('T404')).toMatch(/→$/)
  expect(await by('T404')).not.toContain('*')
  // 1 日目（今日）が期日なら左端に *（期限超過ではない）
  expect(await by('T405')).toMatch(/\* {4}\.\. {5}\.\.$/)
  expect(await ui.find({ type: 'Text', text: /期限超過/ })).toBeFalsy()
  await ui.unmount()
})

test('ガント：期限を過ぎた本人のタスクは行にせず、凡例の下に1行でまとめる。0 件なら出さない。今日が期日なら * の行', async ($, on) => {
  const tasks = [
    ft('T501', '期限切れ1', '本人', null, '2026-11-01'),
    ft('T502', '期限切れ2', '本人', null, '2026-10-20', '期限超過'),
    ft('T503', '今日が期日', '本人', null, '2026-11-02'),
    ft('T504', 'AI の作業', 'AI', '2026-11-02', '2026-11-03'),
  ]
  await setup($, on, { data: open(1), forecast: fcFile(tasks) })
  await $.tool.call({ tool: GT })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal', props: TALL })
  const rows = await ganttRows(ui)
  expect(rows.map(r => r.slice(0, 4))).toEqual(['T503', 'T504'])
  expect(rows[0]).toContain('*')
  // 凡例のすぐ下に、呼び方つきの 1 行
  const texts = ((await ui.findAll({ type: 'Text' })) as { text: string }[]).map(t => t.text)
  expect(texts[1]).toMatch(/^= AI/)
  expect(texts[2]).toBe('期限超過 2 件（山田さん・今日より前）')
  expect(wcols(texts[2])).toBeLessThanOrEqual(40) // 幅40で1行
  await ui.unmount()
  const r = await $.tool.call({ tool: GT })
  expect(JSON.stringify(r)).toContain('2件') // 行にできるのは T503・T504
})

test('ガント：期限を過ぎた本人のタスクが 0 件のときは、その行を出さない', async ($, on) => {
  const tasks = [ft('T503', '今日が期日', '本人', null, '2026-11-02'), ft('T504', 'AI の作業', 'AI', '2026-11-02', '2026-11-03')]
  await setup($, on, { data: open(1), forecast: fcFile(tasks) })
  await $.tool.call({ tool: GT })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal', props: TALL })
  expect(await ui.find({ type: 'Text', text: /期限超過/ })).toBeFalsy()
  expect((await ganttRows(ui)).length).toBe(2)
  await ui.unmount()
})

test('ガント：凡例とまとめの行は幅40で1行。いちばん行が多い形でも、窓の高さ（bodyRows）に収まる', async ($, on) => {
  const many = Array.from({ length: 9 }, (_, i) => ft(`T6${String(i).padStart(2, '0')}`, `件${i}`, 'AI', '2026-11-02', '2026-11-03'))
  const tasks = [
    ...many,
    ft('T690', '期限切れ', '本人', null, '2026-10-30'),
    ft('T691', '見積もり1', 'AI', null, null, '見積もり待ち'),
    ft('T692', '見積もり2', 'AI', null, null, '見積もり待ち'),
    ft('T693', '輪', 'AI', null, null, '依存の輪'),
  ]
  await setup($, on, { data: open(1), forecast: fcFile(tasks, { waiting: 12 }) })
  await $.tool.call({ tool: GT })
  for (const bodyRows of [10, 14, 24]) {
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal', props: { ...PANE.props, scroll: { offset: 0, bodyRows } } })
    const texts = ((await ui.findAll({ type: 'Text' })) as { text: string }[]).map(t => t.text)
    const buttons = ((await ui.findAll({ type: 'Button' })) as { text: string }[]).length
    const legend = texts.find(t => t.startsWith('= AI'))!
    const wait = texts.find(t => t.includes('（棒なし）'))!
    expect(wcols(legend)).toBeLessThanOrEqual(40)
    expect(wcols(wait)).toBeLessThanOrEqual(40)
    const over = texts.find(t => t.startsWith('期限超過'))!
    expect(wcols(over)).toBeLessThanOrEqual(40) // 期限超過の行も幅40で1行
    expect(wait).toBe('見積もり待ち 12・依存の輪 1（棒なし）')
    // 画面の行数：テキスト（40 列で折り返す分を数える）＋ボタン。窓の高さを超えない
    const lines = texts.reduce((n, t) => n + Math.max(1, Math.ceil(wcols(t) / 40)), 0) + buttons
    expect(lines).toBeLessThanOrEqual(bodyRows)
    // 窓が高いほど棒の行が増える（行の数は窓の高さで決まる）
    if (bodyRows === 10) expect((await ganttRows(ui)).length).toBe(3) // 期限超過の行は1行 → 10 - 6 - 1 = 3 行
    await ui.unmount()
  }
})

test('ガント：呼び方が長い人は期限超過の行が折り返す。その分を引いて、窓の高さに収まる', async ($, on) => {
  const tasks = [
    ...Array.from({ length: 6 }, (_, i) => ft(`T7${String(i).padStart(2, '0')}`, `件${i}`, 'AI', '2026-11-02', '2026-11-03')),
    ft('T790', '期限切れ', '本人', null, '2026-10-30'),
  ]
  const call = '山田太郎先生ご担当者様'
  await setup($, on, { data: open(1), forecast: fcFile(tasks), cfg: { owner: '山田', owner_call: call } })
  await $.tool.call({ tool: GT })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal', props: { ...PANE.props, scroll: { offset: 0, bodyRows: 12 } } })
  const texts = ((await ui.findAll({ type: 'Text' })) as { text: string }[]).map(t => t.text)
  const over = texts.find(t => t.startsWith('期限超過'))!
  expect(over).toBe(`期限超過 1 件（${call}・今日より前）`)
  expect(wcols(over)).toBeGreaterThan(40) // 折り返す長さ
  const buttons = ((await ui.findAll({ type: 'Button' })) as { text: string }[]).length
  const lines = texts.reduce((n, t) => n + Math.max(1, Math.ceil(wcols(t) / 40)), 0) + buttons
  expect(lines).toBeLessThanOrEqual(12)
  expect((await ganttRows(ui)).length).toBe(4) // 12 - 6 - 折り返して 2 行 = 4 行
  await ui.unmount()
})

// ---------- 案件のカテゴリ（T134）。tasks.json の category で、全部の一覧をまとめて出す ----------

const AT = 'mcp__ai-bunshin-panel__show_all_tasks'
type CT = { id: string; title: string; priority?: number; category?: unknown; status?: string; assignee?: string }
const ct = (id: string, title: string, priority: number | undefined, category?: unknown, status = 'ToDo'): CT => ({
  id,
  title,
  priority,
  ...(category === undefined ? {} : { category }),
  status,
  assignee: 'dev-a',
})
const catData = (tasks: CT[]) => ({ tasks, daily_sprints: [] })
// 画面に出ている文字を、上から順に（見出し・行・足元）。ボタンは含まない
const texts = async (ui: any) => ((await ui.findAll({ type: 'Text' })) as { text: string }[]).map(t => t.text)
const heads = (ts: string[]) => ts.filter(t => t.startsWith('■ '))
const taskIds = (ts: string[]) => ts.map(t => /^\[[^\]]*\] (T\d+) /.exec(t)?.[1]).filter((x): x is string => !!x)
const mountAll = async ($: any, rows = 30, cols = 40) =>
  $.ui.mount({ ...PANE, surface: 'terminal', props: { ...PANE.props, bodyColumns: cols, scroll: { offset: 0, bodyRows: rows } } })

const MIX = [
  ct('T001', '手前の仕事', 5, 'A案件'),
  ct('T002', '分類なし1', 1), // いちばん順位が高いが「未分類」は未完了の最後
  ct('T003', 'B の先頭', 2, 'B案件'),
  ct('T004', 'A の2つめ', 6, 'A案件'),
  ct('T005', 'C の先頭', 3, 'C案件'),
  ct('T006', 'B の2つめ', 9, 'B案件'),
  ct('T007', '完了A', undefined, 'A案件', '完了'),
  ct('T008', '完了なし', undefined, undefined, '完了'),
]

test('カテゴリ（C1・C2）：未完了はカテゴリごとにまとまる。カテゴリの順は「いちばん順位が高いタスク」の順。「未分類」は未完了の最後、完了はその後ろに1つだけ', async ($, on) => {
  const { n } = await setup($, on, { data: catData(MIX) })
  await $.tool.call({ tool: AT })
  const ui = await mountAll($)
  const ts = await texts(ui)
  // B（順位2）→ C（3）→ A（5）→ 未分類 → 完了
  expect(heads(ts)).toEqual(['■ B案件（2）', '■ C案件（1）', '■ A案件（2）', '■ 未分類（1）', '■ 完了（2）'])
  // カテゴリの中は今の並び（順位の順）のまま。完了は新しい順
  expect(taskIds(ts)).toEqual(['T003', 'T006', 'T005', 'T001', 'T004', 'T002', 'T008', 'T007'])
  // 行の形は今のまま
  expect(ts).toContain('[ToDo] T003 B の先頭 ・dev-a')
  expect(ts).toContain('[済] T008 完了なし ・dev-a')
  await ui.unmount()
  expect(n.writes).toBe(0)
})

test('カテゴリ（C2）：見出しの件数は実物の件数と合う。数え漏れ・二重がない', async ($, on) => {
  await setup($, on, { data: catData(MIX) })
  await $.tool.call({ tool: AT })
  const ui = await mountAll($)
  const ts = await texts(ui)
  const sum = heads(ts).reduce((n, h) => n + Number(/（(\d+)）$/.exec(h)![1]), 0)
  expect(sum).toBe(MIX.length)
  const ids = taskIds(ts)
  expect(new Set(ids).size).toBe(ids.length)
  expect(ids.length).toBe(MIX.length)
  // 未完了の見出しの合計は、上の「未完了 N」と同じ
  const top = (await heading(ui)) as string
  const openSum = heads(ts).filter(h => !h.startsWith('■ 完了')).reduce((n, h) => n + Number(/（(\d+)）$/.exec(h)![1]), 0)
  expect(top).toContain(`未完了 ${openSum}`)
  await ui.unmount()
})

test('カテゴリ（C1）：無い・空・空白だけ・数字・null・配列・オブジェクト・真偽値は「未分類」に入り、落ちない。前後の空白は除いて同じカテゴリに', async ($, on) => {
  const bad: unknown[] = [undefined, '', '   ', 123, null, ['A案件'], { a: 1 }, true]
  const rows = [
    ...bad.map((c, i) => ct(`T${String(i + 1).padStart(3, '0')}`, `おかしな${i + 1}`, i + 1, c)),
    ct('T020', '空白つき', 20, '  A案件  '),
    ct('T021', '空白なし', 21, 'A案件'),
  ]
  await setup($, on, { data: catData(rows) })
  await $.tool.call({ tool: AT })
  const ui = await mountAll($)
  const ts = await texts(ui)
  expect(heads(ts)).toEqual(['■ A案件（2）', '■ 未分類（8）'])
  expect(taskIds(ts).length).toBe(10)
  await ui.unmount()
})

test('カテゴリ（C2）：完了は、カテゴリがあっても全部まとめて最後の「■ 完了（N）」に入る（薄く）。未完了が 0 件でも落ちない', async ($, on) => {
  await setup($, on, { data: catData([ct('T001', '済A', undefined, 'A案件', '完了'), ct('T002', '済B', undefined, 'B案件', '完了')]) })
  await $.tool.call({ tool: AT })
  const ui = await mountAll($)
  const ts = await texts(ui)
  expect(heads(ts)).toEqual(['■ 完了（2）'])
  const h = ((await ui.findAll({ type: 'Text' })) as any[]).find(t => t.text === '■ 完了（2）')
  expect(h.props.dimColor).toBe(true)
  const o = ((await ui.findAll({ type: 'Text' })) as any[]).find(t => t.text.includes('T001'))
  expect(o.props.dimColor).toBe(true)
  await ui.unmount()
})

test('カテゴリ（C2）：順位が同じ・順位が無いタスクでも、カテゴリの順は安定（順位なしは最後・同順位は ID 順）', async ($, on) => {
  const rows = [ct('T003', 'z', 3, 'L案件'), ct('T002', 'y', 3, 'M案件'), ct('T001', 'x', undefined, 'N案件')] // わざと ID の逆順で入れる
  await setup($, on, { data: catData(rows) })
  await $.tool.call({ tool: AT })
  const ui = await mountAll($)
  expect(heads(await texts(ui))).toEqual(['■ M案件（1）', '■ L案件（1）', '■ N案件（1）'])
  await ui.unmount()
})

test('カテゴリ（C3）：ページの頭がカテゴリの途中なら「（続き）」付きの見出しをもう一度出す。見出しも 1 行に数える。ふつうの頭には付けない', async ($, on) => {
  // A案件 7 件・B案件 2 件。bodyRows 10 → 1 ページ 5 行
  const rows = [
    ...Array.from({ length: 7 }, (_, i) => ct(`T00${i + 1}`, `a${i + 1}`, i + 1, 'A案件')),
    ct('T008', 'b1', 8, 'B案件'),
    ct('T009', 'b2', 9, 'B案件'),
  ]
  await setup($, on, { data: catData(rows) })
  await $.tool.call({ tool: AT })
  const ui = await mountAll($, 10)
  const p1 = await texts(ui)
  expect(heads(p1)).toEqual(['■ A案件（7）']) // 1 ページ目：見出し＋4件（続きは付かない）
  expect(taskIds(p1)).toEqual(['T001', 'T002', 'T003', 'T004'])
  await ui.press({ key: 'next' })
  const p2 = await texts(ui)
  expect(heads(p2)).toEqual(['■ A案件（7）（続き）']) // 2 ページ目：頭は A の途中
  expect(taskIds(p2)).toEqual(['T005', 'T006', 'T007'])
  expect((await heading(ui)) as string).toContain('2/3')
  // B の見出しがページの最後の1行だけになるときは、次のページの頭に送る（見出しだけを残さない）
  await ui.press({ key: 'next' })
  const p3 = await texts(ui)
  expect(heads(p3)).toEqual(['■ B案件（2）'])
  expect(taskIds(p3)).toEqual(['T008', 'T009'])
  expect((await heading(ui)) as string).toContain('3/3')
  // 全ページを通して、行が1回ずつ出ている
  await ui.unmount()
})

test('カテゴリ（C3）：どのページも bodyRows - 5 行に収まり、全ページで行が 1 回ずつ。続きの見出しは名前と件数が元と同じ', async ($, on) => {
  const rows = [
    ...Array.from({ length: 13 }, (_, i) => ct(`T${String(i + 1).padStart(3, '0')}`, `a${i + 1}`, i + 1, 'A案件')),
    ...Array.from({ length: 6 }, (_, i) => ct(`T${String(i + 20).padStart(3, '0')}`, `m${i + 1}`, 20 + i)), // 未分類
    ...Array.from({ length: 4 }, (_, i) => ct(`T${String(i + 40).padStart(3, '0')}`, `d${i + 1}`, undefined, 'A案件', '完了')),
  ]
  await setup($, on, { data: catData(rows) })
  await $.tool.call({ tool: AT })
  const ui = await mountAll($, 10)
  const seen: string[] = []
  let pages = 1
  for (let p = 0; p < pages; p++) {
    const ts = await texts(ui)
    if (p === 0) pages = Number(/\/(\d+) ページ/.exec((await heading(ui)) as string)![1])
    // 見出し（全部のタスク …）と足元（行を押すと詳細）を除いた中身が 5 行以内
    const body = ts.filter(t => t !== '行を押すと詳細' && !t.startsWith('全部のタスク'))
    expect(body.length).toBeLessThanOrEqual(5)
    seen.push(...taskIds(ts))
    for (const h of heads(ts)) expect(h).toMatch(/^■ (A案件|未分類|完了)（(13|6|4)）(（続き）)?$/)
    if (p < pages - 1) await ui.press({ key: 'next' })
  }
  expect(seen.sort()).toEqual(rows.map(r => r.id).sort())
  await ui.unmount()
})

test('カテゴリ（C4）：ふつうの画面は区画も並びも変わらず、カテゴリの見出しは出ない', async ($, on) => {
  await setup($, on, { data: catData(MIX) })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  const ts = await texts(ui)
  expect(heads(ts)).toEqual(['■ 今日の予定', '■ 山田さん（今日まで）', '■ AI（今日の計画）', '■ AI（これから）', '■ 近いうちに（山田さん）'])
  expect(ts.some(t => /■ [ABC]案件/.test(t))).toBe(false)
  await ui.unmount()
})

test('カテゴリ（C4）：タスクの詳細に「カテゴリ：…」が出る。無いときは、未完了なら「未分類」、完了なら出さない', async ($, on) => {
  await setup($, on, { data: catData(MIX) })
  const detailText = async (id: string) => {
    await $.tool.call({ tool: 'mcp__ai-bunshin-panel__open_task', id })
    const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
    const ts = await texts(ui)
    await ui.unmount()
    return ts
  }
  expect(await detailText('T001')).toContain('カテゴリ：A案件')
  expect(await detailText('T002')).toContain('カテゴリ：未分類')
  expect((await detailText('T008')).some(t => t.startsWith('カテゴリ：'))).toBe(false)
  expect(await detailText('T007')).toContain('カテゴリ：A案件')
})

test('カテゴリ（C5・C6）：見出しは1行で切れる（truncate-end）。幅20でも崩れず、一覧→詳細→戻ると全部の一覧、ガントも動く', async ($, on) => {
  const long = 'とても長いカテゴリの名前がここに入ります（幅を超える）'
  const { titles } = await setup($, on, {
    data: catData([ct('T001', 'x', 1, long), ct('T002', 'y', 2, long)]),
    forecast: fcFile([ft('T001', '実装', 'AI', '2026-11-02', '2026-11-03')]),
  })
  await $.tool.call({ tool: AT })
  let ui = await mountAll($, 12, 20)
  const h = ((await ui.findAll({ type: 'Text' })) as any[]).find(t => t.text.startsWith('■ '))
  expect(h.text).toBe(`■ ${long}（2）`)
  expect(h.props.wrap).toBe('truncate-end')
  await ui.unmount()
  await $.tool.call({ tool: 'mcp__ai-bunshin-panel__open_task', id: 'T001' })
  expect(titles.at(-1)).toBe('T001 の詳細')
  ui = await mountAll($, 12, 20)
  await ui.press({ key: 'back' })
  expect(titles.at(-1)).toBe('全部のタスク')
  await ui.unmount()
  await $.tool.call({ tool: GT })
  expect(titles.at(-1)).toBe('これから2週間')
  await $.tool.call({ tool: 'mcp__ai-bunshin-panel__open_task', id: '' })
  expect(titles.at(-1)).toBe('今日のやること')
})
