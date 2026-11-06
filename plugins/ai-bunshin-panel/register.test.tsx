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
}
const CFG = { owner: '山田', owner_call: '山田さん', calendar: { type: 'ics' } }
async function setup($: any, on: any, s: Src) {
  s.hasFile ??= true
  s.mtime ??= 1
  if (!('cfg' in s)) s.cfg = CFG
  const titles: string[] = []
  const descs: string[] = []
  const n = { command: 0, tool: 0, open: 0, every: 0, writes: 0, tasksReads: 0, calReads: 0 }
  const want = s.hasFile
  on('command.register', (_: any, e: any) => {
    n.command++
    descs.push(String(e.description ?? ''))
    return { value: { command: 'x' } }
  })
  on('tool.register', () => {
    n.tool++
    return { value: { name: 'x' } }
  })
  on('ui.open', (_: any, e: any) => {
    n.open++
    titles.push(e.title)
    return { value: { isPlaced: true } }
  })
  on('fs.stat', (_: any, e: any) => {
    const p = String(e.path)
    if (p === `${HOME}/設定/config.json`) return s.cfg === undefined ? { deny: 'none' } : { value: { mtimeMs: 1 } }
    if (p === `${HOME}/00_タスク管理/data/tasks.json`) return s.hasFile ? { value: { mtimeMs: s.mtime } } : { deny: 'none' }
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
  on('session.cwd', () => ({ value: s.cwd ?? HOME }))
  on('session.start', (_: any, e: any) => ({ cwd: e.cwd }))
  // 起動のときは tasks.json がある（本人のフォルダとして見つかる）。そのあと消す・壊す試しができる
  s.hasFile = s.startFile ?? true
  await $.session.start({ cwd: s.cwd ?? HOME, surface: 'terminal', isInteractive: true })
  s.hasFile = want
  return { titles, n, s, descs }
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

  // bodyRows 10 → 1 ページ 5 行 → 4 ページ
  ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /全部のタスク/ }))?.text).toContain('1/4')
  expect((await ui.find({ type: 'Text', text: /全部のタスク/ }))?.text).toContain('未完了 12')
  expect(await ui.find({ type: 'Text', text: /未完了1 / })).toBeTruthy()
  expect(await ui.find({ type: 'Text', text: /未完了6 / })).toBeFalsy()
  expect(await ui.find({ type: 'Button', text: /次/ })).toBeTruthy()
  expect(await ui.find({ type: 'Button', text: /前/ })).toBeFalsy()
  await ui.press({ key: 'next' })
  expect((await ui.find({ type: 'Text', text: /全部のタスク/ }))?.text).toContain('2/4')
  expect(await ui.find({ type: 'Text', text: /未完了6 / })).toBeTruthy()
  await ui.press({ key: 'next' })
  await ui.press({ key: 'next' })
  expect((await ui.find({ type: 'Text', text: /全部のタスク/ }))?.text).toContain('4/4')
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

test('端数のある最終ページ：21 件・5 ページ目は 1 行', async ($, on) => {
  await setup($, on, { data: open(21), hasFile: true, mtime: 1 })
  await $.tool.call({ tool: 'mcp__ai-bunshin-panel__show_all_tasks' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await heading(ui)).toContain('1/5')
  for (let i = 0; i < 4; i++) await ui.press({ key: 'next' })
  expect(await heading(ui)).toContain('5/5')
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
  expect(await heading(ui)).toContain('2/4')
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
  expect(n.tool).toBe(2)
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
