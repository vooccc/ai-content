import { useEffect, useState } from 'react'
import { API_BASE } from '../api/base'

interface MetricRow {
  id: string
  ref_date: string
  title: string
  target_user: number
  read_user: number
  read_count: number
  share_count: number
  fav_count: number
  like_count: number
  source: string
  notes: string
}

interface Summary {
  article_count: number
  metric_count: number
  total_read_user: number
  total_share: number
  total_fav: number
  total_like: number
  best_title: string
  best_read_user: number
}

interface ReviewResult {
  summary: string
  highlights: string[]
  suggested_title_formulas: string[]
  suggested_banned_words: string[]
}

export default function MetricsView() {
  const [metrics, setMetrics] = useState<MetricRow[]>([])
  const [summary, setSummary] = useState<Summary | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [reviewing, setReviewing] = useState(false)
  const [review, setReview] = useState<ReviewResult | null>(null)
  const [showAdd, setShowAdd] = useState(false)
  const [title, setTitle] = useState('')
  const [refDate, setRefDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [readUser, setReadUser] = useState('')
  const [shareCount, setShareCount] = useState('')
  const [favCount, setFavCount] = useState('')
  const [likeCount, setLikeCount] = useState('')
  const [msg, setMsg] = useState('')

  async function load() {
    try {
      const d = await (await fetch(`${API_BASE}/metrics`)).json()
      if (d.ok) {
        setMetrics(d.metrics || [])
        setSummary(d.summary || null)
      }
    } catch { /* ignore */ }
  }

  useEffect(() => { load() }, [])

  async function syncWechat() {
    setSyncing(true)
    setMsg('')
    try {
      const res = await fetch(`${API_BASE}/metrics/sync-wechat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ days: 7 }),
      })
      const d = await res.json()
      if (d.ok) {
        setMsg(`✓ 已同步 ${d.begin_date} ~ ${d.end_date} 共 ${d.synced} 条公众号数据`)
        await load()
      } else {
        setMsg(`✗ 同步失败：${d.error || '请确认公众号已认证且已配置凭证'}`)
      }
    } catch (e) {
      setMsg(`✗ 同步失败：${e}`)
    } finally {
      setSyncing(false)
    }
  }

  async function saveManual() {
    if (!title.trim()) return
    setMsg('')
    try {
      const res = await fetch(`${API_BASE}/metrics`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ref_date: refDate,
          title: title.trim(),
          read_user: Number(readUser) || 0,
          share_count: Number(shareCount) || 0,
          fav_count: Number(favCount) || 0,
          like_count: Number(likeCount) || 0,
        }),
      })
      const d = await res.json()
      if (d.ok) {
        setTitle(''); setReadUser(''); setShareCount(''); setFavCount(''); setLikeCount('')
        setShowAdd(false)
        setMsg('✓ 已记录文章数据')
        await load()
      } else {
        setMsg(`✗ ${d.error || '保存失败'}`)
      }
    } catch (e) {
      setMsg(`✗ 保存失败：${e}`)
    }
  }

  async function runReview() {
    setReviewing(true)
    setMsg('')
    try {
      const d = await (await fetch(`${API_BASE}/metrics/review`, { method: 'POST' })).json()
      if (d.ok) setReview(d)
    } catch (e) {
      setMsg(`✗ 复盘失败：${e}`)
    } finally {
      setReviewing(false)
    }
  }

  async function applySuggestions() {
    if (!review) return
    try {
      const cur = await (await fetch(`${API_BASE}/accounts/primary`)).json()
      if (!cur.ok) return
      const acc = cur.account
      const nextFormulas = Array.from(new Set([...(acc.title_formulas || []), ...(review.suggested_title_formulas || [])]))
      const nextBanned = Array.from(new Set([...(acc.banned_words || []), ...(review.suggested_banned_words || [])]))
      await fetch(`${API_BASE}/accounts/primary`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title_formulas: nextFormulas, banned_words: nextBanned }),
      })
      setMsg('✓ 已把复盘建议写入主号定位（后续选题与撰稿会自动应用）')
    } catch (e) {
      setMsg(`✗ 写入失败：${e}`)
    }
  }

  const card: React.CSSProperties = {
    background: 'rgba(127,127,127,0.08)',
    border: '1px solid rgba(127,127,127,0.18)',
    borderRadius: 12,
    padding: 14,
    marginBottom: 12,
  }
  const inputStyle: React.CSSProperties = {
    padding: '7px 10px',
    borderRadius: 8,
    border: '1px solid rgba(127,127,127,0.3)',
    background: 'transparent',
    color: 'inherit',
    fontSize: 13,
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

  return (
    <div style={{ flex: 1, overflow: 'auto', padding: '18px 24px', width: '100%' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 10, marginBottom: 14 }}>
        <div style={card}>
          <div style={{ fontSize: 12, opacity: 0.65 }}>已入库文章</div>
          <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>{summary?.article_count ?? 0} 篇</div>
        </div>
        <div style={card}>
          <div style={{ fontSize: 12, opacity: 0.65 }}>累计阅读人数</div>
          <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>{summary?.total_read_user ?? 0}</div>
        </div>
        <div style={card}>
          <div style={{ fontSize: 12, opacity: 0.65 }}>分享 / 收藏</div>
          <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>{summary?.total_share ?? 0} / {summary?.total_fav ?? 0}</div>
        </div>
        <div style={card}>
          <div style={{ fontSize: 12, opacity: 0.65 }}>最佳表现</div>
          <div style={{ fontSize: 13, fontWeight: 600, marginTop: 6, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={summary?.best_title || ''}>
            {summary?.best_title ? `${summary.best_title} (${summary.best_read_user})` : '暂无'}
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
        <button type="button" style={goBtn} disabled={syncing} onClick={syncWechat}>
          {syncing ? '同步中…' : '🔄 同步公众号数据（近7天）'}
        </button>
        <button type="button" style={ghostBtn} onClick={() => setShowAdd((v) => !v)}>+ 手动补录</button>
        <button type="button" style={ghostBtn} disabled={reviewing} onClick={runReview}>
          {reviewing ? '分析中…' : '✨ AI 复盘本周表现'}
        </button>
      </div>

      {msg && (
        <div style={{ ...card, padding: '10px 14px', fontSize: 13, borderColor: 'rgba(196,167,125,0.5)', background: 'rgba(196,167,125,0.1)' }}>
          {msg}
        </div>
      )}

      {showAdd && (
        <div style={{ ...card, borderColor: 'rgba(196,167,125,0.5)' }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <input type="date" value={refDate} onChange={(e) => setRefDate(e.target.value)} style={inputStyle} />
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="文章标题" style={{ ...inputStyle, flex: 2, minWidth: 200 }} />
            <input value={readUser} onChange={(e) => setReadUser(e.target.value)} placeholder="阅读人数" type="number" style={{ ...inputStyle, width: 92 }} />
            <input value={shareCount} onChange={(e) => setShareCount(e.target.value)} placeholder="分享" type="number" style={{ ...inputStyle, width: 76 }} />
            <input value={favCount} onChange={(e) => setFavCount(e.target.value)} placeholder="收藏" type="number" style={{ ...inputStyle, width: 76 }} />
            <input value={likeCount} onChange={(e) => setLikeCount(e.target.value)} placeholder="点赞" type="number" style={{ ...inputStyle, width: 76 }} />
            <button type="button" style={goBtn} onClick={saveManual}>保存</button>
          </div>
        </div>
      )}

      {review && (
        <div style={{ ...card, borderColor: 'rgba(58,157,93,0.45)', background: 'rgba(58,157,93,0.06)' }}>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>✨ 复盘结论</div>
          <div style={{ fontSize: 13.5, lineHeight: 1.7, marginBottom: 8 }}>{review.summary}</div>
          {review.highlights?.length > 0 && (
            <ul style={{ margin: '0 0 8px 18px', padding: 0, fontSize: 13, lineHeight: 1.7, opacity: 0.85 }}>
              {review.highlights.map((h, idx) => <li key={idx}>{h}</li>)}
            </ul>
          )}
          {(review.suggested_title_formulas?.length > 0 || review.suggested_banned_words?.length > 0) && (
            <button type="button" style={goBtn} onClick={applySuggestions}>
              一键采纳建议更新至主号定位
            </button>
          )}
        </div>
      )}

      <div style={card}>
        {metrics.length === 0 ? (
          <div style={{ fontSize: 13, opacity: 0.6, padding: 12 }}>
            还没有数据记录。推送群发后可点「同步公众号数据」（需公众号已认证并开通数据统计接口），或点「+ 手动补录」记下阅读与收藏表现。
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ textAlign: 'left', borderBottom: '1px solid rgba(127,127,127,0.2)', opacity: 0.7 }}>
                  <th style={{ padding: '8px 6px' }}>日期</th>
                  <th style={{ padding: '8px 6px' }}>标题</th>
                  <th style={{ padding: '8px 6px' }}>阅读</th>
                  <th style={{ padding: '8px 6px' }}>分享</th>
                  <th style={{ padding: '8px 6px' }}>收藏</th>
                  <th style={{ padding: '8px 6px' }}>点赞</th>
                  <th style={{ padding: '8px 6px' }}>来源</th>
                </tr>
              </thead>
              <tbody>
                {metrics.map((m) => (
                  <tr key={m.id} style={{ borderBottom: '1px solid rgba(127,127,127,0.1)' }}>
                    <td style={{ padding: '8px 6px', whiteSpace: 'nowrap', opacity: 0.7 }}>{m.ref_date}</td>
                    <td style={{ padding: '8px 6px', fontWeight: 500 }}>{m.title}</td>
                    <td style={{ padding: '8px 6px' }}>{m.read_user}</td>
                    <td style={{ padding: '8px 6px' }}>{m.share_count}</td>
                    <td style={{ padding: '8px 6px' }}>{m.fav_count}</td>
                    <td style={{ padding: '8px 6px' }}>{m.like_count}</td>
                    <td style={{ padding: '8px 6px', opacity: 0.65 }}>{m.source === 'datacube' ? '微信同步' : '手动'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
