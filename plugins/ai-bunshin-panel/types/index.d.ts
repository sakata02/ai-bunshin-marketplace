export type Row = { id: string; title: string; due: string; mark: string }
// 全部のタスクの一覧の1行（担当と状態つき）
export type AllRow = Row & { who: string; done: boolean }
// 右のパネルの表示：ふだんの短い画面（home）か、全部のタスクの一覧（all）。page は 0 から
export type View = { mode: 'home' | 'all'; page: number }
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

// 今日の予定（calendar_cache.json から。件名と時間だけ）
export type CalEvent = { start: string; end: string; title: string; allday: boolean; unknown: boolean }
export type Cal = { fetched: string; events: CalEvent[]; nowMin: number; error: string }

declare module 'claude-code' {
  interface PluginState {
    'ai-bunshin-panel': { board: Shaped<Board>; view: Shaped<View>; mtime: number; detail: Shaped<Detail>; cal: Shaped<Cal> }
  }
}
