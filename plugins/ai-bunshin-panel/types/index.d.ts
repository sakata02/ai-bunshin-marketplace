// category は案件の名前（無い・空・文字でないときは「未分類」）。短い画面は区切りの中をこれで分ける
export type Row = { id: string; title: string; due: string; mark: string; category: string }
// 全部のタスクの一覧の1行（担当と状態つき）。完了の行では category は使わない
export type AllRow = Row & { who: string; done: boolean }
// 右のパネルの表示：ふだんの短い画面（home）か、全部のタスクの一覧（all）。page は 0 から
export type View = { mode: 'home' | 'all' | 'gantt'; page: number }
export type Board = {
  today: string
  mine: Row[]
  ai: Row[]
  aiNext: Row[]
  aiNextMore: number
  all: AllRow[]
  soon: Row[]
  openRequests: number
  error: string
}
// 右のパネルで開いているタスク（id が空なら一覧）
export type Detail = {
  id: string
  title: string
  lines: { label: string; text: string }[]
  steps: string[]
  error: string
}

// 試し中の Try（改善ログの「実施中の Try」の表の1行。列の中身はそのまま）
export type Try = { id: string; area: string; body: string; check: string; start: string }

// 今日の予定（calendar_cache.json から。件名と時間だけ）
export type CalEvent = { start: string; end: string; title: string; allday: boolean; unknown: boolean }
export type Cal = { fetched: string; events: CalEvent[]; nowMin: number; error: string }

// これから2週間のガントチャート（forecast.json から。update_dashboard.py が計算した結果を読むだけ）。ok が false のときは message を1行出す
export type ForecastDay = { date: string; off: boolean }
export type ForecastTask = { id: string; title: string; who: string; start: string | null; end: string | null; state: string }
export type Gantt = { ok: boolean; message: string; today: string; days: ForecastDay[]; tasks: ForecastTask[]; waiting: number }

declare module 'claude-code' {
  interface PluginState {
    'ai-bunshin-panel': { board: Shaped<Board>; view: Shaped<View>; mtime: number; detail: Shaped<Detail>; cal: Shaped<Cal>; gantt: Shaped<Gantt> }
  }
}
