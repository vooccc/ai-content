import { useEffect, useState } from 'react'
import { API_BASE } from '../api/base'

interface RawSignal {
  source_type: string
  source_name: string
  title: string
  url: string
  popularity?: number
  badge?: string
}

interface TopicItem {
  id: string
  source_type: string
  source_name: string
  source_url: string
  raw_title: string
  raw_summary: string
  suggested_titles: string[]
  raw_signals?: RawSignal[]
  metrics_badge?: string
  angle: string
  reason: string
  category: string
  score: number
  status: string
  project_id: string
  created_at: number
}

interface FunnelCounts {
  new: number
  today_new: number
  resonance: number
  drafted: number
  ignored: number
  all: number
}

interface InProgressProj {
  id: string
  title: string
  done_count: number
  total_count: number
  next_step: string
  updated: number
}

interface ImportPreview {
  total: number
  new_count: number
  dup_count: number
  low_fan_count: number
  preview: { title: string; source_name: string; metrics_badge?: string; summary: string }[]
}

interface RssFeedItem {
  name: string
  url: string
  enabled?: boolean
}

interface SourcesConfig {
  github_trending?: boolean
  github_languages?: string[]
  hackernews?: boolean
  hf_papers?: boolean
  reddit?: boolean
  reddit_subreddits?: string[]
  bluesky?: boolean
  bluesky_accounts?: string[]
  bilibili?: boolean
  bilibili_accounts?: string[]
  weibo_hot?: boolean
  wechat_search?: boolean
  wechat_keywords?: string[]
  rss_feeds?: RssFeedItem[]
  last_fetch_stats?: Record<string, number>
  last_rss_stats?: Record<string, number>
  last_fetch_errors?: string[]
  last_fetch_at?: number
}

interface TopicsViewProps {
  onOpenProject: (projectId: string) => void
}

type FilterMode = 'new' | 'today_new' | 'resonance' | 'drafted' | 'ignored' | 'all'

const SOURCE_META: { key: string; cfgKey?: keyof SourcesConfig; label: string; desc: string }[] = [
  { key: 'github_trending', cfgKey: 'github_trending', label: 'GitHub Trending', desc: '开源项目日榜' },
  { key: 'hackernews', cfgKey: 'hackernews', label: 'Hacker News', desc: '48h 高赞英文讨论' },
  { key: 'hf_papers', cfgKey: 'hf_papers', label: 'HF Daily Papers', desc: '每日高赞 AI 论文' },
  { key: 'reddit', cfgKey: 'reddit', label: 'Reddit AI 社区', desc: 'Arctic Shift 免 Key 热帖' },
  { key: 'bluesky', cfgKey: 'bluesky', label: 'Bluesky 大牛', desc: '免 Key 关注 AI 研究者动态' },
  { key: 'bilibili', cfgKey: 'bilibili', label: 'B站视频', desc: '关键词 + UP主 + 低粉爆款' },
  { key: 'wechat_search', cfgKey: 'wechat_search', label: '搜狗公众号', desc: '微信生态同题文章' },
  { key: 'weibo_hot', cfgKey: 'weibo_hot', label: '微博热搜', desc: 'AI/科技破圈话题' },
  { key: 'rss', label: 'RSS 订阅', desc: '独立博客与精选源' },
  { key: 'manual', label: '灵感投喂', desc: '手动输入想法或链接' },
  { key: 'import', label: '清单导入', desc: 'CSV / 表格批量导入' },
]

const SOURCE_LABEL_MAP: Record<string, string> = Object.fromEntries(SOURCE_META.map((s) => [s.key, s.label]))

export default function TopicsView({ onOpenProject }: TopicsViewProps) {
  const [topics, setTopics] = useState<TopicItem[]>([])
  const [counts, setCounts] = useState<FunnelCounts>({ new: 0, today_new: 0, resonance: 0, drafted: 0, ignored: 0, all: 0 })
  const [sourceCounts, setSourceCounts] = useState<Record<string, number>>({})
  const [sourceFilter, setSourceFilter] = useState<string>('')
  const [inProgress, setInProgress] = useState<InProgressProj[]>([])
  const [filter, setFilter] = useState<FilterMode>('new')
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [startingId, setStartingId] = useState<string | null>(null)
  const [pickedTitle, setPickedTitle] = useState<Record<string, string>>({})
  const [openSignals, setOpenSignals] = useState<Record<string, boolean>>({})
  const [showSources, setShowSources] = useState(false)
  const [srcCfg, setSrcCfg] = useState<SourcesConfig>({})
  const [srcBusy, setSrcBusy] = useState(false)
  const [newKw, setNewKw] = useState('')
  const [newBiliUp, setNewBiliUp] = useState('')
  const [newSubreddit, setNewSubreddit] = useState('')
  const [newBskyHandle, setNewBskyHandle] = useState('')
  const [newRssName, setNewRssName] = useState('')
  const [newRssUrl, setNewRssUrl] = useState('')
  const [rssTestRes, setRssTestRes] = useState<{ ok: boolean; text: string } | null>(null)
  const [showManual, setShowManual] = useState(false)
  const [idea, setIdea] = useState('')
  const [sourceUrl, setSourceUrl] = useState('')
  const [manualBusy, setManualBusy] = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [importText, setImportText] = useState('')
  const [importPreview, setImportPreview] = useState<ImportPreview | null>(null)
  const [importBusy, setImportBusy] = useState(false)
  const [msg, setMsg] = useState('')

  async function loadSources() {
    try {
      const res = await fetch(`${API_BASE}/topics/sources`)
      const d = await res.json()
      if (d.ok) {
        setSrcCfg(d.sources_config || {})
        if (d.pool_counts) setSourceCounts(d.pool_counts)
      }
    } catch { /* ignore */ }
  }

  async function saveSourcesConfig(nextCfg: SourcesConfig, tip?: string) {
    setSrcCfg(nextCfg)
    setSrcBusy(true)
    try {
      const res = await fetch(`${API_BASE}/accounts/primary`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sources_config: nextCfg }),
      })
      const d = await res.json()
      if (d.ok && d.account?.sources_config) {
        setSrcCfg(d.account.sources_config)
        if (tip) {
          setMsg(tip)
          setTimeout(() => setMsg((cur) => (cur === tip ? '' : cur)), 2200)
        }
      }
    } catch (e) {
      setMsg(`✗ 保存信息源配置失败：${e}`)
    } finally {
      setSrcBusy(false)
    }
  }

  async function loadTopics(curFilter = filter, curSrc = sourceFilter) {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (curFilter !== 'all') params.set('filter', curFilter)
      if (curSrc) params.set('source_type', curSrc)
      const qs = params.toString() ? `?${params.toString()}` : ''
      const res = await fetch(`${API_BASE}/topics${qs}`)
      const d = await res.json()
      const list: TopicItem[] = d.topics || []
      setTopics(list)
      if (d.counts) setCounts(d.counts)
      if (d.source_counts) setSourceCounts(d.source_counts)
      setInProgress(d.in_progress_projects || [])
      setPickedTitle((prev) => {
        const next = { ...prev }
        for (const t of list) {
          if (!next[t.id] && t.suggested_titles?.length) {
            next[t.id] = t.suggested_titles[0]
          }
        }
        return next
      })
    } catch (e) {
      setMsg(`加载选题失败：${e}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadTopics(filter, sourceFilter)
  }, [filter, sourceFilter])

  useEffect(() => {
    loadSources()
  }, [])

  async function refreshNow() {
    if (refreshing) return
    setRefreshing(true)
    setMsg('正在抓取 GitHub / HackerNews / B站 / 微博热搜 / RSS / 搜狗微信并聚类筛选高点击选题…')
    try {
      const res = await fetch(`${API_BASE}/topics/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ max_new: 8 }),
      })
      const d = await res.json().catch(() => ({}))
      if (res.ok && d.ok) {
        const errHint = d.errors?.length ? `（部分源提示：${d.errors[0]}）` : ''
        setMsg(`✓ 抓取 ${d.fetched} 条，聚类去重后新增 ${d.added} 条高契合选题（${d.mode === 'llm' ? 'AI精选' : '规则精选'}）${errHint}`)
        await Promise.all([loadTopics(filter, sourceFilter), loadSources()])
      } else {
        const detail = typeof d.detail === 'string' ? d.detail : (d.detail ? JSON.stringify(d.detail) : '')
        setMsg(`✗ 抓取失败：${d.error || detail || `HTTP ${res.status}（请确认已重启 ai-content 服务）`}`)
      }
    } catch (e) {
      setMsg(`✗ 抓取失败：${e}`)
    } finally {
      setRefreshing(false)
    }
  }

  async function submitManual() {
    if (!idea.trim() && !sourceUrl.trim()) return
    setManualBusy(true)
    setMsg('')
    try {
      const res = await fetch(`${API_BASE}/topics/manual`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ idea: idea.trim(), source_url: sourceUrl.trim() }),
      })
      const d = await res.json()
      if (d.ok) {
        setIdea('')
        setSourceUrl('')
        setShowManual(false)
        setMsg('✓ 已提炼标题并加入选题池')
        setFilter('new')
        await loadTopics('new')
      } else {
        setMsg(`✗ ${d.error || '添加失败'}`)
      }
    } catch (e) {
      setMsg(`✗ 添加失败：${e}`)
    } finally {
      setManualBusy(false)
    }
  }

  async function previewImport(textVal = importText) {
    if (!textVal.trim()) return
    setImportBusy(true)
    setMsg('')
    try {
      const res = await fetch(`${API_BASE}/topics/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: textVal, dry_run: true }),
      })
      const d = await res.json()
      if (res.ok && d.ok) {
        setImportPreview(d)
      } else {
        setImportPreview(null)
        setMsg(`✗ ${d.error || `HTTP ${res.status}`}`)
      }
    } catch (e) {
      setMsg(`✗ 解析失败：${e}`)
    } finally {
      setImportBusy(false)
    }
  }

  async function commitImport() {
    if (!importText.trim()) return
    setImportBusy(true)
    setMsg('')
    try {
      const res = await fetch(`${API_BASE}/topics/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: importText, dry_run: false }),
      })
      const d = await res.json()
      if (res.ok && d.ok) {
        setImportText('')
        setImportPreview(null)
        setShowImport(false)
        setMsg(`✓ 已导入 ${d.added} 条爆款选题（跳过重复 ${d.dup_count} 条${d.low_fan_count ? `，识别低粉爆款 ${d.low_fan_count} 条` : ''}）`)
        setFilter('new')
        await loadTopics('new')
      } else {
        setMsg(`✗ ${d.error || `HTTP ${res.status}`}`)
      }
    } catch (e) {
      setMsg(`✗ 导入失败：${e}`)
    } finally {
      setImportBusy(false)
    }
  }

  async function startWriting(t: TopicItem) {
    if (t.project_id && t.status === 'drafted') {
      onOpenProject(t.project_id)
      return
    }
    setStartingId(t.id)
    setMsg('')
    try {
      const selected_title = pickedTitle[t.id] || t.suggested_titles?.[0] || t.raw_title
      const res = await fetch(`${API_BASE}/topics/${t.id}/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ selected_title }),
      })
      const d = await res.json()
      if (d.ok && d.project?.id) {
        onOpenProject(d.project.id)
      } else {
        setMsg(`✗ 创建文章失败：${d.error || '未知错误'}`)
      }
    } catch (e) {
      setMsg(`✗ 创建文章失败：${e}`)
    } finally {
      setStartingId(null)
    }
  }

  async function setTopicStatus(t: TopicItem, nextStatus: 'ignored' | 'new') {
    try {
      await fetch(`${API_BASE}/topics/${t.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: nextStatus }),
      })
      await loadTopics(filter)
    } catch { /* ignore */ }
  }

  const card: React.CSSProperties = {
    background: 'rgba(127,127,127,0.08)',
    border: '1px solid rgba(127,127,127,0.18)',
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
  }
  const inputStyle: React.CSSProperties = {
    padding: '8px 10px',
    borderRadius: 8,
    border: '1px solid rgba(127,127,127,0.3)',
    background: 'transparent',
    color: 'inherit',
  }
  const goBtn: React.CSSProperties = {
    padding: '7px 14px',
    borderRadius: 8,
    border: 'none',
    cursor: 'pointer',
    fontWeight: 600,
    fontSize: 13,
    background: 'linear-gradient(135deg,#c4a77d,#8a6c49)',
    color: '#fff',
  }
  const ghostBtn: React.CSSProperties = {
    padding: '6px 12px',
    borderRadius: 8,
    border: '1px solid rgba(127,127,127,0.3)',
    cursor: 'pointer',
    fontSize: 13,
    background: 'transparent',
    color: 'inherit',
  }
  const pillBtn = (active: boolean): React.CSSProperties => ({
    ...ghostBtn,
    padding: '5px 11px',
    fontSize: 12.5,
    fontWeight: active ? 600 : 400,
    borderColor: active ? 'rgba(196,167,125,0.85)' : 'rgba(127,127,127,0.25)',
    background: active ? 'rgba(196,167,125,0.15)' : 'transparent',
  })

  async function testRssFeed() {
    const url = newRssUrl.trim()
    if (!url) return
    setSrcBusy(true)
    setRssTestRes(null)
    try {
      const res = await fetch(`${API_BASE}/topics/sources/test-rss`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, name: newRssName.trim() }),
      })
      const d = await res.json()
      if (res.ok && d.ok) {
        const titles = (d.samples || []).map((s: { title: string }) => s.title).join(' / ')
        setRssTestRes({ ok: true, text: `✓ 可用，抓到 ${d.count} 条（如：${titles.slice(0, 80)}）` })
      } else {
        setRssTestRes({ ok: false, text: `✗ ${d.error || '测试失败'}` })
      }
    } catch (e) {
      setRssTestRes({ ok: false, text: `✗ ${e}` })
    } finally {
      setSrcBusy(false)
    }
  }

  function addRssFeed() {
    const url = newRssUrl.trim()
    if (!url) return
    const name = newRssName.trim() || url.replace(/^https?:\/\//, '').split('/')[0]
    const curFeeds = srcCfg.rss_feeds || []
    if (curFeeds.some((f) => f.url === url)) {
      setMsg('该 RSS 地址已在列表中')
      return
    }
    const nextCfg: SourcesConfig = {
      ...srcCfg,
      rss_feeds: [...curFeeds, { name, url, enabled: true }],
    }
    setNewRssName('')
    setNewRssUrl('')
    setRssTestRes(null)
    saveSourcesConfig(nextCfg, `✓ 已添加订阅源：${name}`)
  }

  function addKeyword() {
    const kw = newKw.trim()
    if (!kw) return
    const cur = srcCfg.wechat_keywords || []
    if (cur.includes(kw)) {
      setNewKw('')
      return
    }
    setNewKw('')
    saveSourcesConfig({ ...srcCfg, wechat_keywords: [...cur, kw] }, `✓ 已添加关键词：${kw}`)
  }

  function addBiliUp() {
    const up = newBiliUp.trim()
    if (!up) return
    const cur = srcCfg.bilibili_accounts || []
    if (cur.includes(up)) {
      setNewBiliUp('')
      return
    }
    setNewBiliUp('')
    saveSourcesConfig({ ...srcCfg, bilibili_accounts: [...cur, up] }, `✓ 已关注 B站 UP 主：${up}`)
  }

  function addSubreddit() {
    const sub = newSubreddit.trim().replace(/^r\//i, '')
    if (!sub) return
    const cur = srcCfg.reddit_subreddits || ['LocalLLaMA', 'ClaudeAI', 'MachineLearning']
    if (cur.includes(sub)) {
      setNewSubreddit('')
      return
    }
    setNewSubreddit('')
    saveSourcesConfig({ ...srcCfg, reddit_subreddits: [...cur, sub] }, `✓ 已添加 Reddit 版块：r/${sub}`)
  }

  function addBskyHandle() {
    const h = newBskyHandle.trim().replace(/^@/, '')
    if (!h) return
    const cur = srcCfg.bluesky_accounts || ['karpathy.bsky.social', 'simonwillison.net', 'hardmaru.bsky.social', 'emollick.bsky.social', 'swyx.io']
    if (cur.includes(h)) {
      setNewBskyHandle('')
      return
    }
    setNewBskyHandle('')
    saveSourcesConfig({ ...srcCfg, bluesky_accounts: [...cur, h] }, `✓ 已关注 Bluesky 账号：${h}`)
  }

  const activePlatformCount =
    (srcCfg.github_trending !== false ? 1 : 0) +
    (srcCfg.hackernews !== false ? 1 : 0) +
    (srcCfg.hf_papers !== false ? 1 : 0) +
    (srcCfg.reddit !== false ? 1 : 0) +
    (srcCfg.bluesky !== false ? 1 : 0) +
    (srcCfg.bilibili !== false ? 1 : 0) +
    (srcCfg.wechat_search !== false ? 1 : 0) +
    (srcCfg.weibo_hot !== false ? 1 : 0) +
    (srcCfg.rss_feeds || []).filter((f) => f.enabled !== false).length

  const funnelTabs: [FilterMode, string, number][] = [
    ['new', '今日推荐', counts.new],
    ['today_new', '24h新增', counts.today_new],
    ['resonance', '多源/爆款', counts.resonance],
    ['drafted', '已开写', counts.drafted],
    ['ignored', '已忽略', counts.ignored],
    ['all', '全部', counts.all],
  ]

  return (
    <div style={{ flex: 1, overflow: 'auto', padding: '18px 24px', width: '100%' }}>
      {inProgress.length > 0 && (
        <div
          style={{
            ...card,
            padding: '10px 14px',
            marginBottom: 12,
            borderColor: 'rgba(196,167,125,0.5)',
            background: 'rgba(196,167,125,0.08)',
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            flexWrap: 'wrap',
            fontSize: 13,
          }}
        >
          <span style={{ fontWeight: 600 }}>⏳ 待收尾（{inProgress.length} 篇）</span>
          <span style={{ opacity: 0.85 }}>
            《{inProgress[0].title}》 · 进度 {inProgress[0].done_count}/{inProgress[0].total_count}（下一步：{inProgress[0].next_step}）
          </span>
          <button
            type="button"
            style={{ ...ghostBtn, marginLeft: 'auto', padding: '4px 10px', fontSize: 12.5, borderColor: 'rgba(196,167,125,0.75)' }}
            onClick={() => onOpenProject(inProgress[0].id)}
          >
            继续推进 →
          </button>
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: 14 }}>
        {funnelTabs.map(([k, label, cnt]) => (
          <button key={k} type="button" style={pillBtn(filter === k)} onClick={() => setFilter(k)}>
            {label} <span style={{ opacity: 0.65 }}>({cnt})</span>
          </button>
        ))}
        {sourceFilter && (
          <button
            type="button"
            style={{ ...pillBtn(true), borderColor: 'rgba(90,169,230,0.8)', background: 'rgba(90,169,230,0.14)' }}
            onClick={() => setSourceFilter('')}
            title="点击取消来源筛选"
          >
            来源：{SOURCE_LABEL_MAP[sourceFilter] || sourceFilter} ×
          </button>
        )}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button
            type="button"
            style={showSources ? pillBtn(true) : ghostBtn}
            onClick={() => { setShowSources((v) => !v); setShowImport(false); setShowManual(false) }}
          >
            📡 信息源 ({activePlatformCount})
          </button>
          <button type="button" style={ghostBtn} onClick={() => { setShowImport((v) => !v); setShowManual(false); setShowSources(false) }}>
            📥 导入清单
          </button>
          <button type="button" style={ghostBtn} onClick={() => { setShowManual((v) => !v); setShowImport(false); setShowSources(false) }}>
            + 投喂灵感
          </button>
          <button type="button" style={goBtn} disabled={refreshing} onClick={refreshNow}>
            {refreshing ? '抓取筛选中…' : '🔄 抓取新选题'}
          </button>
        </div>
      </div>

      {showSources && (
        <div style={{ ...card, borderColor: 'rgba(196,167,125,0.55)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10, flexWrap: 'wrap', gap: 8 }}>
            <div style={{ fontSize: 13.5, fontWeight: 600 }}>
              📡 信息源配置与分布（点击任意来源可筛选，开关改动自动保存）
            </div>
            <div style={{ fontSize: 12, opacity: 0.65 }}>
              {srcCfg.last_fetch_at
                ? `上次抓取：${new Date(srcCfg.last_fetch_at * 1000).toLocaleString()}`
                : '尚未记录抓取批次'}
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(210px, 1fr))', gap: 8, marginBottom: 12 }}>
            {SOURCE_META.map((sm) => {
              const poolCnt = sourceCounts[sm.key] || 0
              const lastCnt = sm.key === 'rss'
                ? (srcCfg.last_fetch_stats?.rss ?? null)
                : (srcCfg.last_fetch_stats?.[sm.key] ?? null)
              const hasToggle = !!sm.cfgKey
              const enabled = hasToggle ? srcCfg[sm.cfgKey!] !== false : true
              const isFiltered = sourceFilter === sm.key
              return (
                <div
                  key={sm.key}
                  style={{
                    padding: '9px 11px',
                    borderRadius: 9,
                    border: '1px solid ' + (isFiltered ? 'rgba(90,169,230,0.8)' : 'rgba(127,127,127,0.2)'),
                    background: isFiltered ? 'rgba(90,169,230,0.08)' : 'rgba(127,127,127,0.04)',
                    opacity: enabled ? 1 : 0.55,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 4,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 }}>
                    <button
                      type="button"
                      onClick={() => setSourceFilter(isFiltered ? '' : sm.key)}
                      style={{
                        background: 'transparent', border: 'none', padding: 0, cursor: 'pointer',
                        color: 'inherit', fontWeight: 600, fontSize: 13, textAlign: 'left',
                      }}
                      title="点击只看该来源选题"
                    >
                      {sm.label}
                    </button>
                    {hasToggle && (
                      <input
                        type="checkbox"
                        checked={enabled}
                        disabled={srcBusy}
                        onChange={(e) => saveSourcesConfig({ ...srcCfg, [sm.cfgKey!]: e.target.checked })}
                        title={enabled ? '点击停用此源' : '点击启用此源'}
                        style={{ cursor: 'pointer' }}
                      />
                    )}
                  </div>
                  <div style={{ fontSize: 11.5, opacity: 0.65 }}>{sm.desc}</div>
                  <div style={{ fontSize: 11.5, display: 'flex', gap: 8, marginTop: 2 }}>
                    <span
                      onClick={() => setSourceFilter(isFiltered ? '' : sm.key)}
                      style={{ cursor: 'pointer', color: poolCnt > 0 ? '#c4a77d' : 'inherit', opacity: poolCnt > 0 ? 1 : 0.5 }}
                    >
                      池内 {poolCnt} 条
                    </span>
                    {lastCnt !== null && (
                      <span style={{ opacity: 0.65 }}>· 上次抓 {lastCnt}</span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12, marginBottom: 12 }}>
            <div style={{ padding: '10px 12px', borderRadius: 9, background: 'rgba(127,127,127,0.05)' }}>
              <div style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 6 }}>
                检索关键词（驱动 HN / B站 / 公众号 / 微博过滤）
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
                {(srcCfg.wechat_keywords || []).map((kw) => (
                  <span
                    key={kw}
                    style={{
                      display: 'inline-flex', alignItems: 'center', gap: 5,
                      padding: '3px 8px', borderRadius: 6, fontSize: 12,
                      background: 'rgba(196,167,125,0.16)', border: '1px solid rgba(196,167,125,0.4)',
                    }}
                  >
                    {kw}
                    <button
                      type="button"
                      onClick={() => saveSourcesConfig({
                        ...srcCfg,
                        wechat_keywords: (srcCfg.wechat_keywords || []).filter((x) => x !== kw),
                      })}
                      style={{ background: 'transparent', border: 'none', color: 'inherit', cursor: 'pointer', padding: 0, opacity: 0.7 }}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                <input
                  value={newKw}
                  onChange={(e) => setNewKw(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') addKeyword() }}
                  placeholder="新增关键词（如 Cursor / MCP）"
                  style={{ ...inputStyle, flex: 1, padding: '5px 8px', fontSize: 12.5 }}
                />
                <button type="button" style={{ ...ghostBtn, padding: '5px 10px', fontSize: 12.5 }} onClick={addKeyword}>+ 添加</button>
              </div>
            </div>

            <div style={{ padding: '10px 12px', borderRadius: 9, background: 'rgba(127,127,127,0.05)' }}>
              <div style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 6 }}>
                B站定向关注 UP 主（名字或 UID，抓最新视频）
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
                {(srcCfg.bilibili_accounts || []).length === 0 && (
                  <span style={{ fontSize: 12, opacity: 0.55 }}>暂无定向 UP 主（当前按关键词全站搜）</span>
                )}
                {(srcCfg.bilibili_accounts || []).map((up) => (
                  <span
                    key={up}
                    style={{
                      display: 'inline-flex', alignItems: 'center', gap: 5,
                      padding: '3px 8px', borderRadius: 6, fontSize: 12,
                      background: 'rgba(90,169,230,0.14)', border: '1px solid rgba(90,169,230,0.35)',
                    }}
                  >
                    {up}
                    <button
                      type="button"
                      onClick={() => saveSourcesConfig({
                        ...srcCfg,
                        bilibili_accounts: (srcCfg.bilibili_accounts || []).filter((x) => x !== up),
                      })}
                      style={{ background: 'transparent', border: 'none', color: 'inherit', cursor: 'pointer', padding: 0, opacity: 0.7 }}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                <input
                  value={newBiliUp}
                  onChange={(e) => setNewBiliUp(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') addBiliUp() }}
                  placeholder="填 UP 主昵称或 UID"
                  style={{ ...inputStyle, flex: 1, padding: '5px 8px', fontSize: 12.5 }}
                />
                <button type="button" style={{ ...ghostBtn, padding: '5px 10px', fontSize: 12.5 }} onClick={addBiliUp}>+ 添加</button>
              </div>
            </div>

            <div style={{ padding: '10px 12px', borderRadius: 9, background: 'rgba(127,127,127,0.05)' }}>
              <div style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 6 }}>
                Reddit 关注版块（Arctic Shift 免 Key）
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
                {(srcCfg.reddit_subreddits || ['LocalLLaMA', 'ClaudeAI', 'MachineLearning']).map((sub) => (
                  <span
                    key={sub}
                    style={{
                      display: 'inline-flex', alignItems: 'center', gap: 5,
                      padding: '3px 8px', borderRadius: 6, fontSize: 12,
                      background: 'rgba(237,123,47,0.14)', border: '1px solid rgba(237,123,47,0.35)',
                    }}
                  >
                    r/{sub}
                    <button
                      type="button"
                      onClick={() => saveSourcesConfig({
                        ...srcCfg,
                        reddit_subreddits: (srcCfg.reddit_subreddits || ['LocalLLaMA', 'ClaudeAI', 'MachineLearning']).filter((x) => x !== sub),
                      })}
                      style={{ background: 'transparent', border: 'none', color: 'inherit', cursor: 'pointer', padding: 0, opacity: 0.7 }}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                <input
                  value={newSubreddit}
                  onChange={(e) => setNewSubreddit(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') addSubreddit() }}
                  placeholder="填版块名（如 singularity / OpenAI）"
                  style={{ ...inputStyle, flex: 1, padding: '5px 8px', fontSize: 12.5 }}
                />
                <button type="button" style={{ ...ghostBtn, padding: '5px 10px', fontSize: 12.5 }} onClick={addSubreddit}>+ 添加</button>
              </div>
            </div>

            <div style={{ padding: '10px 12px', borderRadius: 9, background: 'rgba(127,127,127,0.05)' }}>
              <div style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 6 }}>
                Bluesky 关注 AI 大牛（免 Key 公开流）
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
                {(srcCfg.bluesky_accounts || ['karpathy.bsky.social', 'simonwillison.net', 'hardmaru.bsky.social', 'emollick.bsky.social', 'swyx.io']).map((h) => (
                  <span
                    key={h}
                    style={{
                      display: 'inline-flex', alignItems: 'center', gap: 5,
                      padding: '3px 8px', borderRadius: 6, fontSize: 12,
                      background: 'rgba(58,157,93,0.14)', border: '1px solid rgba(58,157,93,0.35)',
                    }}
                  >
                    @{h}
                    <button
                      type="button"
                      onClick={() => saveSourcesConfig({
                        ...srcCfg,
                        bluesky_accounts: (srcCfg.bluesky_accounts || ['karpathy.bsky.social', 'simonwillison.net', 'hardmaru.bsky.social', 'emollick.bsky.social', 'swyx.io']).filter((x) => x !== h),
                      })}
                      style={{ background: 'transparent', border: 'none', color: 'inherit', cursor: 'pointer', padding: 0, opacity: 0.7 }}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                <input
                  value={newBskyHandle}
                  onChange={(e) => setNewBskyHandle(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') addBskyHandle() }}
                  placeholder="填 handle（如 karpathy.bsky.social）"
                  style={{ ...inputStyle, flex: 1, padding: '5px 8px', fontSize: 12.5 }}
                />
                <button type="button" style={{ ...ghostBtn, padding: '5px 10px', fontSize: 12.5 }} onClick={addBskyHandle}>+ 添加</button>
              </div>
            </div>
          </div>

          <div style={{ padding: '10px 12px', borderRadius: 9, background: 'rgba(127,127,127,0.05)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8, flexWrap: 'wrap', gap: 8 }}>
              <div style={{ fontSize: 12.5, fontWeight: 600 }}>
                RSS / Atom 订阅源（{(srcCfg.rss_feeds || []).filter((f) => f.enabled !== false).length}/{(srcCfg.rss_feeds || []).length} 启用）
              </div>
              <button
                type="button"
                disabled={srcBusy}
                style={{ ...ghostBtn, padding: '3px 9px', fontSize: 12, borderColor: 'rgba(196,167,125,0.6)' }}
                onClick={async () => {
                  setSrcBusy(true)
                  try {
                    const res = await fetch(`${API_BASE}/topics/sources/apply-presets`, { method: 'POST' })
                    const d = await res.json()
                    if (d.ok) {
                      if (d.sources_config) setSrcCfg(d.sources_config)
                      setMsg(d.added > 0 ? `✓ 已导入 ${d.added} 个一线 AI 官方博客 RSS（OpenAI / Anthropic / DeepMind / HF 等）` : '一线 AI 官方博客预设已全部在订阅列表中')
                    }
                  } catch (e) {
                    setMsg(`✗ 导入预设失败：${e}`)
                  } finally {
                    setSrcBusy(false)
                  }
                }}
              >
                ✨ 一键导入一线 AI 官方预设
              </button>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 8 }}>
              {(srcCfg.rss_feeds || []).map((f, idx) => {
                const enabled = f.enabled !== false
                const lastFeedCnt = srcCfg.last_rss_stats?.[f.name]
                return (
                  <div
                    key={`${f.url}-${idx}`}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
                      padding: '5px 8px', borderRadius: 7, background: 'rgba(127,127,127,0.06)',
                      opacity: enabled ? 1 : 0.55, fontSize: 12.5,
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={enabled}
                      onChange={(e) => {
                        const nextFeeds = (srcCfg.rss_feeds || []).map((item, i) =>
                          i === idx ? { ...item, enabled: e.target.checked } : item
                        )
                        saveSourcesConfig({ ...srcCfg, rss_feeds: nextFeeds })
                      }}
                      style={{ cursor: 'pointer' }}
                    />
                    <span style={{ fontWeight: 600 }}>{f.name}</span>
                    <span style={{ opacity: 0.65, flex: 1, minWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {f.url}
                    </span>
                    {lastFeedCnt !== undefined && (
                      <span style={{ fontSize: 11.5, opacity: 0.7 }}>上次 {lastFeedCnt} 条</span>
                    )}
                    <button
                      type="button"
                      onClick={() => saveSourcesConfig({
                        ...srcCfg,
                        rss_feeds: (srcCfg.rss_feeds || []).filter((_, i) => i !== idx),
                      }, `已移除订阅源：${f.name}`)}
                      style={{ ...ghostBtn, padding: '2px 8px', fontSize: 11.5, opacity: 0.75 }}
                    >
                      删除
                    </button>
                  </div>
                )
              })}
            </div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
              <input
                value={newRssName}
                onChange={(e) => setNewRssName(e.target.value)}
                placeholder="订阅源名称（如：Simon Willison）"
                style={{ ...inputStyle, width: 180, padding: '5px 8px', fontSize: 12.5 }}
              />
              <input
                value={newRssUrl}
                onChange={(e) => { setNewRssUrl(e.target.value); setRssTestRes(null) }}
                placeholder="RSS / Atom XML 地址（https://...）"
                style={{ ...inputStyle, flex: 1, minWidth: 220, padding: '5px 8px', fontSize: 12.5 }}
              />
              <button type="button" style={{ ...ghostBtn, padding: '5px 10px', fontSize: 12.5 }} disabled={srcBusy || !newRssUrl.trim()} onClick={testRssFeed}>
                测试
              </button>
              <button type="button" style={{ ...goBtn, padding: '5px 12px', fontSize: 12.5 }} disabled={srcBusy || !newRssUrl.trim()} onClick={addRssFeed}>
                + 添加订阅源
              </button>
            </div>
            {rssTestRes && (
              <div style={{ marginTop: 6, fontSize: 12, color: rssTestRes.ok ? '#3a9d5d' : '#e24b4a' }}>
                {rssTestRes.text}
              </div>
            )}
          </div>

          {(srcCfg.last_fetch_errors || []).length > 0 && (
            <div style={{ marginTop: 10, fontSize: 12, color: '#ed7b2f' }}>
              最近抓取告警：{(srcCfg.last_fetch_errors || []).join(' | ')}
            </div>
          )}
        </div>
      )}

      {showManual && (
        <div style={{ ...card, borderColor: 'rgba(196,167,125,0.55)' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <input
              value={idea}
              onChange={(e) => setIdea(e.target.value)}
              placeholder="一句话想法或主题（如：用 Claude Code 自动化写周报的实操踩坑）"
              style={inputStyle}
            />
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <input
                value={sourceUrl}
                onChange={(e) => setSourceUrl(e.target.value)}
                placeholder="可选：粘贴 GitHub / 公众号 / 文章链接自动抓摘要"
                style={{ ...inputStyle, flex: 1, minWidth: 240 }}
              />
              <button type="button" style={goBtn} disabled={manualBusy} onClick={submitManual}>
                {manualBusy ? '提炼中…' : '提炼入池'}
              </button>
              <button type="button" style={ghostBtn} onClick={() => setShowManual(false)}>取消</button>
            </div>
          </div>
        </div>
      )}

      {showImport && (
        <div style={{ ...card, borderColor: 'rgba(196,167,125,0.55)' }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
            导入外部爆款 / 信号清单（自动算「低粉爆款倍数」并去重）
          </div>
          <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 8 }}>
            支持直接粘贴 CSV / Excel 制表符表格 / JSON（表头支持：标题,作者,粉丝,播放,点赞,平台,链接；支持「5万」简写）
          </div>
          <textarea
            value={importText}
            onChange={(e) => { setImportText(e.target.value); setImportPreview(null) }}
            placeholder={'标题,作者,粉丝,播放,点赞,平台,链接\n用 Claude Code 10分钟搭完个人工作台,小王AI,4000,6万,1200,小红书,https://...'}
            style={{ ...inputStyle, width: '100%', minHeight: 88, resize: 'vertical', fontSize: 12.5, boxSizing: 'border-box' }}
          />
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginTop: 8 }}>
            <label style={{ ...ghostBtn, display: 'inline-flex', alignItems: 'center' }}>
              选择 CSV/JSON 文件
              <input
                type="file"
                accept=".csv,.json,.txt,text/csv,application/json"
                style={{ display: 'none' }}
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (!f) return
                  const reader = new FileReader()
                  reader.onload = () => {
                    const txt = String(reader.result || '')
                    setImportText(txt)
                    previewImport(txt)
                  }
                  reader.readAsText(f)
                  e.target.value = ''
                }}
              />
            </label>
            <button type="button" style={ghostBtn} disabled={importBusy || !importText.trim()} onClick={() => previewImport()}>
              {importBusy ? '解析中…' : '预览解析'}
            </button>
            {importPreview && importPreview.new_count > 0 && (
              <button type="button" style={goBtn} disabled={importBusy} onClick={commitImport}>
                确认导入 {importPreview.new_count} 条
              </button>
            )}
            <button type="button" style={{ ...ghostBtn, marginLeft: 'auto' }} onClick={() => setShowImport(false)}>关闭</button>
          </div>
          {importPreview && (
            <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid rgba(127,127,127,0.15)', fontSize: 12.5 }}>
              <div style={{ marginBottom: 6 }}>
                共解析 {importPreview.total} 条 · 新增 <strong>{importPreview.new_count}</strong> · 重复跳过 {importPreview.dup_count}
                {importPreview.low_fan_count > 0 && (
                  <span style={{ color: '#ed7b2f', fontWeight: 600 }}> · 识别低粉爆款 {importPreview.low_fan_count} 条</span>
                )}
              </div>
              {importPreview.preview.map((p, idx) => (
                <div key={idx} style={{ opacity: 0.8, padding: '3px 0' }}>
                  • {p.title} <span style={{ opacity: 0.65 }}>({p.source_name}{p.metrics_badge ? ` · ${p.metrics_badge}` : ''})</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {msg && (
        <div style={{ ...card, padding: '10px 14px', fontSize: 13, borderColor: 'rgba(196,167,125,0.5)', background: 'rgba(196,167,125,0.1)' }}>
          {msg}
        </div>
      )}

      {loading && topics.length === 0 && (
        <div style={{ opacity: 0.6, fontSize: 13, padding: 20 }}>加载选题中…</div>
      )}

      {!loading && topics.length === 0 && (
        <div style={{ ...card, textAlign: 'center', padding: 32 }}>
          <div style={{ fontSize: 14, opacity: 0.75, marginBottom: 12 }}>
            {filter === 'new' ? '选题池暂时空着 — 点右上角「🔄 抓取新选题」「+ 投喂灵感」或「📥 导入清单」立刻生成选题卡片。' : '该分类下暂无选题。'}
          </div>
          {filter === 'new' && (
            <button type="button" style={goBtn} disabled={refreshing} onClick={refreshNow}>
              {refreshing ? '抓取中…' : '立即抓取第一批选题'}
            </button>
          )}
        </div>
      )}

      {topics.map((t) => {
        const titles = t.suggested_titles?.length ? t.suggested_titles : [t.raw_title]
        const selected = pickedTitle[t.id] || titles[0]
        const scoreColor = t.score >= 85 ? '#3a9d5d' : t.score >= 70 ? '#c4a77d' : 'inherit'
        const sigs = t.raw_signals || []
        const sigsOpen = !!openSignals[t.id]
        return (
          <div key={t.id} style={card}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
              <span style={{ fontSize: 12, fontWeight: 700, padding: '2px 8px', borderRadius: 6, background: 'rgba(58,157,93,0.14)', color: scoreColor }}>
                {t.score} 分
              </span>
              <button
                type="button"
                onClick={() => setSourceFilter(sourceFilter === t.source_type ? '' : t.source_type)}
                title="点击按此信息源筛选"
                style={{
                  fontSize: 12,
                  padding: '2px 8px',
                  borderRadius: 6,
                  border: 'none',
                  cursor: 'pointer',
                  color: 'inherit',
                  background: sourceFilter === t.source_type ? 'rgba(90,169,230,0.22)' : 'rgba(127,127,127,0.14)',
                }}
              >
                {t.source_name || t.source_type}
              </button>
              {t.metrics_badge && (
                <span style={{ fontSize: 11.5, fontWeight: 600, padding: '2px 7px', borderRadius: 6, background: 'rgba(226,75,74,0.15)', color: '#e24b4a' }}>
                  🚀 {t.metrics_badge}
                </span>
              )}
              {t.reason?.includes('多源共振') && (
                <span style={{ fontSize: 11.5, fontWeight: 600, padding: '2px 7px', borderRadius: 6, background: 'rgba(237,123,47,0.16)', color: '#ed7b2f' }}>
                  🔥 多源共振
                </span>
              )}
              {t.category && (
                <span style={{ fontSize: 12, opacity: 0.7 }}>{t.category}</span>
              )}
              {sigs.length > 1 && (
                <button
                  type="button"
                  style={{ ...ghostBtn, padding: '2px 8px', fontSize: 11.5, opacity: 0.85 }}
                  onClick={() => setOpenSignals((prev) => ({ ...prev, [t.id]: !prev[t.id] }))}
                >
                  {sigs.length} 个关联信源 {sigsOpen ? '▴' : '▾'}
                </button>
              )}
              {t.source_url && (
                <a
                  href={t.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ fontSize: 12, color: '#5aa9e6', textDecoration: 'none', marginLeft: 4 }}
                >
                  原素材 ↗
                </a>
              )}
              <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
                {t.status === 'ignored' ? (
                  <button type="button" style={ghostBtn} onClick={() => setTopicStatus(t, 'new')}>↩️ 恢复</button>
                ) : t.status !== 'drafted' ? (
                  <button type="button" style={{ ...ghostBtn, opacity: 0.7 }} onClick={() => setTopicStatus(t, 'ignored')}>忽略</button>
                ) : null}
                <button
                  type="button"
                  style={goBtn}
                  disabled={startingId === t.id}
                  onClick={() => startWriting(t)}
                >
                  {startingId === t.id ? '建项中…' : (t.project_id && t.status === 'drafted' ? '继续写 →' : '直接开写 →')}
                </button>
              </div>
            </div>

            {sigsOpen && sigs.length > 0 && (
              <div style={{ marginBottom: 10, padding: '8px 10px', borderRadius: 8, background: 'rgba(127,127,127,0.06)', fontSize: 12, display: 'flex', flexDirection: 'column', gap: 4 }}>
                {sigs.map((s, i) => (
                  <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                    <span style={{ padding: '1px 6px', borderRadius: 4, background: 'rgba(127,127,127,0.14)' }}>{s.source_name}</span>
                    <span style={{ flex: 1, minWidth: 160 }}>{s.title}</span>
                    {s.url && (
                      <a href={s.url} target="_blank" rel="noopener noreferrer" style={{ color: '#5aa9e6', textDecoration: 'none' }}>打开 ↗</a>
                    )}
                  </div>
                ))}
              </div>
            )}

            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 10 }}>
              {titles.map((cand, idx) => {
                const isSel = selected === cand
                return (
                  <div
                    key={idx}
                    onClick={() => setPickedTitle((prev) => ({ ...prev, [t.id]: cand }))}
                    style={{
                      padding: '8px 10px',
                      borderRadius: 8,
                      cursor: 'pointer',
                      fontSize: 14,
                      fontWeight: isSel ? 600 : 400,
                      border: '1px solid ' + (isSel ? 'rgba(196,167,125,0.85)' : 'rgba(127,127,127,0.18)'),
                      background: isSel ? 'rgba(196,167,125,0.12)' : 'transparent',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                    }}
                  >
                    <span style={{ fontSize: 12, opacity: 0.7 }}>{isSel ? '●' : '○'}</span>
                    <span>{cand}</span>
                  </div>
                )
              })}
            </div>

            {(t.reason || t.angle) && (
              <div style={{ fontSize: 12.5, opacity: 0.75, lineHeight: 1.6 }}>
                {t.reason && <span>💡 {t.reason}</span>}
                {t.reason && t.angle && <span> · </span>}
                {t.angle && <span>切入：{t.angle}</span>}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
