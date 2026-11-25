export interface CanvasSource {
  id: string
  kind: 'url' | 'doc' | 'image' | 'text'
  title: string
  url?: string
  author?: string
  path?: string
  mime?: string
  purpose?: string
  content?: string
  added_at: number
}

export interface CanvasMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  selection?: string
  images?: string[]
  applied_version?: string
  model?: string
  ts: number
}

export interface CanvasVersion {
  id: string
  label: string
  title: string
  content: string
  ts: number
}

export interface CanvasProject {
  id: string
  title: string
  content: string
  initial_ai_draft?: string
  cover_url?: string
  model?: string
  style?: string
  use_my_style?: boolean
  theme?: string
  sources: CanvasSource[]
  messages: CanvasMessage[]
  versions: CanvasVersion[]
  draft_media_id?: string
  source_studio_id?: string
  created: number
  updated: number
}

export interface CanvasSummary {
  id: string
  title: string
  word_count: number
  version_count: number
  source_count: number
  theme: string
  style: string
  draft_media_id: string
  source_studio_id: string
  updated: number
}

export interface SelectionLock {
  text: string
  start: number
  end: number
}

export interface ComplianceFinding {
  severity: 'high' | 'warn' | 'style'
  category: string
  word: string
  count: number
  hits: { line: number; snippet: string }[]
}

export function countChars(text: string): number {
  return (text || '').replace(/\s+/g, '').length
}

export function formatShortTime(ts: number): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
