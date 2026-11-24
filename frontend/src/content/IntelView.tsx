import { useEffect, useState } from 'react'

const API_BASE = ((import.meta as unknown as { env?: Record<string, string> }).env?.VITE_CONTENT_API_BASE || '').replace(/\/$/, '')

interface IntelSignal {
  source_type: string
  source_name: string
  title: string
  url: string
  popularity?: number
}

interface IntelItem {
  id: string
  title: string
  summary: string
  raw_title: string
  source_type: string
  source_name: string
  source_url: string
  signals: IntelSignal[]
  credibility: string
  metrics_badge: string
  engagement_badge?: string
  engagement?: { likes?: number; collects?: number; comments?: number }
  category: string
  tags: string[]
  popularity: number
  promoted_topic_id: string
  updated_at: number
}

interface IntelCounts {
  all: number
  一手官方: number
  多源印证: number
  社区热议: number
  快讯转述: number
}

interface IntelViewProps {
  onOpenProject: (projectId: string) => void
  onGoTopics?: () => void
}

type CredFilter = 'all' | '一手官方' | '多源印证' | '社区热议' | '快讯转述'

const CRED_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  一手官方: { bg: 'rgba(58,157,93,0.14)', border: 'rgba(58,157,93,0.45)', text: '#3a9d5d' },
  多源印证: { bg: 'rgba(90,169,230,0.14)', border: 'rgba(90,169,230,0.45)', text: '#5aa9e6' },
  社区热议: { bg: 'rgba(196,167,125,0.16)', border: 'rgba(196,167,125,0.5)', text: '#c4a77d' },
  快讯转述: { bg: 'rgba(127,127,127,0.12)', border: 'rgba(127,127,127,0.3)', text: 'inherit' },
}

const INTEL_SOURCE_OPTIONS: { key: string; label: string }[] = [
  { key: 'x', label: 'X (Twitter)' },
  { key: 'xiaohongshu', label: '小红书' },
  { key: 'github_trending', label: 'GitHub Trending' },
  { key: 'hackernews', label: 'Hacker News' },
  { key: 'hf_papers', label: 'Hugging Face 论文' },
  { key: 'reddit', label: 'Reddit' },
  { key: 'bluesky', label: 'Bluesky' },
  { key: 'bilibili', label: 'B站视频' },
  { key: 'wechat_search', label: '搜狗微信' },
  { key: 'weibo_hot', label: '微博热搜' },
  { key: 'rss', label: '科技 RSS' },
]

export default function IntelView({ onOpenProject, onGoTopics }: IntelViewProps) {
  const [items, setItems] = useState<IntelItem[]>([])
  const [counts, setCounts] = useState<IntelCounts>({ all: 0, 一手官方: 0, 多源印证: 0, 社区热议: 0, 快讯转述: 0 })
  const [sourceCounts, setSourceCounts] = useState<Record<string, number>>({})
  const [cred, setCred] = useState<CredFilter>('all')
  const [sourceType, setSourceType] = useState('')
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [translating, setTranslating] = useState(false)
  const [showRaw, setShowRaw] = useState<Record<string, boolean>>({})
  const [busyId, setBusyId] = useState<string | null>(null)
  const [msg, setMsg] = useState('')

  async function loadIntel(curCred = cred, curQ = query, curSrc = sourceType) {
    setLoading(true)
    try {
      const p = new URLSearchParams()
      if (curCred !== 'all') p.set('credibility', curCred)
      if (curSrc) p.set('source_type', curSrc)
      if (curQ.trim()) p.set('q', curQ.trim())
      const qs = p.toString() ? `?${p.toString()}` : ''
      const res = await fetch(`${API_BASE}/intel${qs}`)
      const d = await res.json()
      if (d.ok) {
        setItems(d.items || [])
        if (d.counts) setCounts(d.counts)
        if (d.source_counts) setSourceCounts(d.source_counts)
      }
    } catch (e) {
      setMsg(`加载快讯失败：${e}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadIntel(cred, query, sourceType)
  }, [cred, sourceType])

  async function refreshNow() {
    setRefreshing(true)
    setMsg('正在并发采集一手官方源、论文与社区动态并聚簇提炼…')
    try {
      const res = await fetch(`${API_BASE}/intel/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ limit: 48 }),
      })
      const d = await res.json()
      if (d.ok) {
        const errTip = d.errors?.length ? `（部分源告警：${d.errors[0]}）` : ''
        setMsg(`✓ 采集 ${d.fetched} 条，聚簇为 ${d.clustered} 起事件，新增 ${d.added} / 更新 ${d.updated}（${d.mode === 'llm' ? 'AI提炼' : '规则模式'}）${errTip}`)
        await loadIntel(cred, query, sourceType)
      } else {
        setMsg(`✗ 刷新失败：${d.error || '未知错误'}`)
      }
    } catch (e) {
      setMsg(`✗ 刷新失败：${e}`)
    } finally {
      setRefreshing(false)
    }
  }

  async function translatePending() {
    setTranslating(true)
    setMsg('正在把未翻译的英文快讯批量译成中文…')
    try {
      const res = await fetch(`${API_BASE}/intel/translate-pending`, { method: 'POST' })
      const d = await res.json()
      if (d.ok) {
        setMsg(`✓ 已翻译 ${d.translated} 条英文快讯${d.remaining > 0 ? `（剩余 ${d.remaining} 条可再点一次）` : '，已全部中文化'}`)
        await loadIntel(cred, query, sourceType)
      } else {
        setMsg(`✗ 翻译失败：${d.error || '未知错误'}`)
      }
    } catch (e) {
      setMsg(`✗ 翻译失败：${e}`)
    } finally {
      setTranslating(false)
    }
  }

  async function promote(id: string, startProject: boolean) {
    setBusyId(id)
    try {
      const res = await fetch(`${API_BASE}/intel/${id}/promote`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ start_project: startProject }),
      })
      const d = await res.json()
      if (d.ok) {
        setItems((prev) =>
          prev.map((x) => (x.id === id ? { ...x, promoted_topic_id: d.topic?.id || x.promoted_topic_id } : x))
        )
        if (startProject && d.project?.id) {
          onOpenProject(d.project.id)
          return
        }
        setMsg(d.already_existed ? '该快讯已在选题池中' : '✓ 已收入选题池，自动套好标题公式')
      } else {
        setMsg(`✗ 操作失败：${d.error || '未知错误'}`)
      }
    } catch (e) {
      setMsg(`✗ 操作失败：${e}`)
    } finally {
      setBusyId(null)
    }
  }

  const card: React.CSSProperties = {
    border: '1px solid rgba(127,127,127,0.2)',
    borderRadius: 12,
    padding: 15,
    background: 'rgba(127,127,127,0.03)',
    marginBottom: 12,
  }
  const pillBtn = (active: boolean): React.CSSProperties => ({
    padding: '5px 11px',
    borderRadius: 8,
    fontSize: 12.5,
    cursor: 'pointer',
    border: active ? '1px solid rgba(196,167,125,0.85)' : '1px solid rgba(127,127,127,0.22)',
    background: active ? 'rgba(196,167,125,0.18)' : 'transparent',
    color: 'inherit',
  })
  const ghostBtn: React.CSSProperties = {
    padding: '6px 11px',
    borderRadius: 8,
    fontSize: 12.5,
    cursor: 'pointer',
    border: '1px solid rgba(127,127,127,0.28)',
    background: 'transparent',
    color: 'inherit',
  }
  const goBtn: React.CSSProperties = {
    padding: '6px 13px',
    borderRadius: 8,
    fontSize: 12.5,
    fontWeight: 600,
    cursor: 'pointer',
    border: 'none',
    background: '#c4a77d',
    color: '#18181b',
  }

  const credTabs: [CredFilter, string, number][] = [
    ['all', '全部快讯', counts.all],
    ['一手官方', '一手官方', counts.一手官方],
    ['多源印证', '多源印证', counts.多源印证],
    ['社区热议', '社区热议', counts.社区热议],
    ['快讯转述', '快讯转述', counts.快讯转述],
  ]

  return (
    <div style={{ flex: 1, overflow: 'auto', padding: '18px 24px', width: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: 14 }}>
        {credTabs.map(([k, label, cnt]) => (
          <button key={k} type="button" style={pillBtn(cred === k)} onClick={() => setCred(k)}>
            {label} <span style={{ opacity: 0.65 }}>({cnt})</span>
          </button>
        ))}
        <select
          value={sourceType}
          onChange={(e) => setSourceType(e.target.value)}
          title="按信息源单独筛选快讯"
          style={{
            padding: '5px 9px',
            borderRadius: 8,
            fontSize: 12.5,
            border: sourceType ? '1px solid rgba(90,169,230,0.85)' : '1px solid rgba(127,127,127,0.25)',
            background: sourceType ? 'rgba(90,169,230,0.14)' : 'transparent',
            color: 'inherit',
            colorScheme: 'light dark',
          }}
        >
          <option value="">全部来源</option>
          {INTEL_SOURCE_OPTIONS.filter((opt) => (sourceCounts[opt.key] || 0) > 0 || opt.key === 'xiaohongshu' || opt.key === 'x').map((opt) => (
            <option key={opt.key} value={opt.key}>
              {opt.label} ({sourceCounts[opt.key] || 0})
            </option>
          ))}
        </select>

        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') loadIntel(cred, query, sourceType) }}
            placeholder="搜关键词（如 Claude / Agent）"
            style={{
              padding: '6px 10px',
              borderRadius: 8,
              border: '1px solid rgba(127,127,127,0.28)',
              background: 'transparent',
              color: 'inherit',
              fontSize: 12.5,
              width: 190,
            }}
          />
          <button type="button" style={ghostBtn} onClick={() => loadIntel(cred, query, sourceType)}>
            搜索
          </button>
          {items.some((x) => !/[\u4e00-\u9fff]/.test(x.title || '')) && (
            <button type="button" style={{ ...ghostBtn, borderColor: 'rgba(90,169,230,0.65)' }} disabled={translating} onClick={translatePending}>
              {translating ? '翻译中…' : `🌐 翻译英文 (${items.filter((x) => !/[\u4e00-\u9fff]/.test(x.title || '')).length})`}
            </button>
          )}
          <button type="button" style={goBtn} disabled={refreshing} onClick={refreshNow}>
            {refreshing ? '采集提炼中…' : '🔄 刷新快讯'}
          </button>
        </div>
      </div>

      {msg && (
        <div
          style={{
            marginBottom: 12,
            padding: '8px 12px',
            borderRadius: 8,
            fontSize: 13,
            background: 'rgba(196,167,125,0.12)',
            border: '1px solid rgba(196,167,125,0.35)',
          }}
        >
          {msg}
        </div>
      )}

      {loading && <div style={{ opacity: 0.65, padding: 24, textAlign: 'center' }}>加载实时快讯中…</div>}

      {!loading && items.length === 0 && (
        <div style={{ ...card, textAlign: 'center', padding: 36, opacity: 0.8 }}>
          <div style={{ fontSize: 15, marginBottom: 8 }}>
            {sourceType || cred !== 'all' || query.trim() ? '当前筛选条件下暂无快讯' : '还没有拉取实时快讯'}
          </div>
          <div style={{ fontSize: 13, opacity: 0.7, marginBottom: 14 }}>
            {sourceType || cred !== 'all' || query.trim()
              ? '可切换回「全部来源」或点右上角「🔄 刷新快讯」采集该信源最新动态。'
              : '点击右上角「🔄 刷新快讯」，会并发拉取 OpenAI / DeepMind / HuggingFace / GitHub / HN / B站 / X / 小红书 / RSS 等一手动态并自动聚簇翻成中文快讯。'}
          </div>
          <button type="button" style={goBtn} disabled={refreshing} onClick={refreshNow}>
            {sourceType ? '刷新全部快讯' : '立即采集第一批快讯'}
          </button>
        </div>
      )}

      {items.map((it) => {
        const badgeStyle = CRED_COLORS[it.credibility] || CRED_COLORS.快讯转述
        const sigs = it.signals || []
        const promoted = !!it.promoted_topic_id
        return (
          <div key={it.id} style={card}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 7, flexWrap: 'wrap', marginBottom: 7 }}>
              <span
                style={{
                  fontSize: 11.5,
                  fontWeight: 600,
                  padding: '2px 8px',
                  borderRadius: 6,
                  background: badgeStyle.bg,
                  border: `1px solid ${badgeStyle.border}`,
                  color: badgeStyle.text,
                }}
              >
                {it.credibility}
              </span>
              <span style={{ fontSize: 12, padding: '2px 8px', borderRadius: 6, background: 'rgba(196,167,125,0.16)' }}>
                {it.category}
              </span>
              {it.metrics_badge && (
                <span
                  style={{
                    fontSize: 11.5,
                    fontWeight: 600,
                    padding: '2px 8px',
                    borderRadius: 6,
                    background: 'rgba(226,75,74,0.14)',
                    color: '#e24b4a',
                  }}
                >
                  🚀 {it.metrics_badge}
                </span>
              )}
              {it.engagement_badge && (
                <span
                  title="小红书互动数据（点赞 · 收藏 · 评论）"
                  style={{
                    fontSize: 11.5,
                    fontWeight: 600,
                    padding: '2px 8px',
                    borderRadius: 6,
                    background: 'rgba(218,165,32,0.14)',
                    color: '#c48f16',
                  }}
                >
                  {it.engagement_badge}
                </span>
              )}
              {sigs.length > 1 && (
                <span style={{ fontSize: 11.5, opacity: 0.7 }}>
                  · 聚簇 {sigs.length} 条信源
                </span>
              )}
              <span style={{ fontSize: 11.5, opacity: 0.55, marginLeft: 'auto' }}>
                {new Date((it.updated_at || 0) * 1000).toLocaleString()}
              </span>
            </div>

            <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 6 }}>
              <div style={{ fontSize: 15.5, fontWeight: 600, lineHeight: 1.4, flex: 1 }}>
                {it.title}
              </div>
              {it.raw_title && it.raw_title !== it.title && (
                <button
                  type="button"
                  onClick={() => setShowRaw((p) => ({ ...p, [it.id]: !p[it.id] }))}
                  style={{ background: 'transparent', border: 'none', padding: 0, cursor: 'pointer', fontSize: 11.5, opacity: 0.55, color: 'inherit', flexShrink: 0 }}
                >
                  {showRaw[it.id] ? '收起原文' : '原文'}
                </button>
              )}
            </div>
            {showRaw[it.id] && it.raw_title && (
              <div style={{ fontSize: 12, opacity: 0.6, marginBottom: 6 }}>
                原文：{it.raw_title}
              </div>
            )}

            {it.summary && (
              <div style={{ fontSize: 13.5, opacity: 0.85, lineHeight: 1.55, marginBottom: 10 }}>
                {it.summary}
              </div>
            )}

            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                {(sigs.length > 0 ? sigs.slice(0, 5) : [{ source_name: it.source_name, title: it.raw_title, url: it.source_url }]).map((s, idx) =>
                  s.url ? (
                    <a
                      key={idx}
                      href={s.url}
                      target="_blank"
                      rel="noreferrer"
                      title={s.title}
                      style={{
                        fontSize: 12,
                        padding: '2px 8px',
                        borderRadius: 6,
                        background: 'rgba(127,127,127,0.1)',
                        color: 'inherit',
                        textDecoration: 'none',
                      }}
                    >
                      {s.source_name || '原文'} ↗
                    </a>
                  ) : null
                )}
              </div>

              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                {promoted ? (
                  <button
                    type="button"
                    style={{ ...ghostBtn, borderColor: 'rgba(58,157,93,0.45)', color: '#3a9d5d' }}
                    onClick={() => onGoTopics?.()}
                  >
                    ✓ 已入选题池
                  </button>
                ) : (
                  <button
                    type="button"
                    style={ghostBtn}
                    disabled={busyId === it.id}
                    onClick={() => promote(it.id, false)}
                  >
                    + 收进选题池
                  </button>
                )}
                <button
                  type="button"
                  style={goBtn}
                  disabled={busyId === it.id}
                  onClick={() => promote(it.id, true)}
                >
                  {busyId === it.id ? '建项中…' : '直接开写 →'}
                </button>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
