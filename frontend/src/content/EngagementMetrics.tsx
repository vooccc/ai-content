import { Heart, MessageCircle, Star } from 'lucide-react'

export interface EngagementCounts {
  likes?: number
  collects?: number
  comments?: number
}

function formatCount(n: number): string {
  const val = Math.max(0, Math.round(n || 0))
  if (val >= 10000) {
    const w = val / 10000
    return Math.abs(w - Math.round(w)) < 0.05 ? `${Math.round(w)}万` : `${w.toFixed(1)}万`
  }
  return String(val)
}

function parseCountToken(raw: string): number {
  const s = (raw || '').trim()
  if (!s) return 0
  if (s.endsWith('万')) {
    const num = parseFloat(s.slice(0, -1))
    return Number.isFinite(num) ? Math.round(num * 10000) : 0
  }
  const num = parseFloat(s)
  return Number.isFinite(num) ? Math.round(num) : 0
}

function resolveCounts(engagement?: EngagementCounts, badge?: string): Required<EngagementCounts> {
  let likes = Number(engagement?.likes || 0)
  let collects = Number(engagement?.collects || 0)
  let comments = Number(engagement?.comments || 0)
  if (!likes && !collects && !comments && badge) {
    const mLike = badge.match(/👍\s*([0-9.]+万?)/)
    const mCol = badge.match(/⭐\s*([0-9.]+万?)/)
    const mCom = badge.match(/💬\s*([0-9.]+万?)/)
    if (mLike) likes = parseCountToken(mLike[1])
    if (mCol) collects = parseCountToken(mCol[1])
    if (mCom) comments = parseCountToken(mCom[1])
  }
  return { likes, collects, comments }
}

export default function EngagementMetrics({
  engagement,
  badge,
}: {
  engagement?: EngagementCounts
  badge?: string
}) {
  const { likes, collects, comments } = resolveCounts(engagement, badge)
  if (!likes && !collects && !comments) return null

  return (
    <span
      title="互动数据（点赞 · 收藏 · 评论）"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 11,
        fontSize: 12,
        fontWeight: 500,
        fontVariantNumeric: 'tabular-nums',
        lineHeight: 1,
        padding: '2px 4px',
      }}
    >
      {likes > 0 && (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <Heart size={13} fill="#ff2442" color="#ff2442" strokeWidth={2} />
          <span style={{ opacity: 0.88 }}>{formatCount(likes)}</span>
        </span>
      )}
      {collects > 0 && (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <Star size={13} fill="#f5b841" color="#f5b841" strokeWidth={2} />
          <span style={{ opacity: 0.88 }}>{formatCount(collects)}</span>
        </span>
      )}
      {comments > 0 && (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <MessageCircle size={13} strokeWidth={1.9} style={{ opacity: 0.78 }} />
          <span style={{ opacity: 0.88 }}>{formatCount(comments)}</span>
        </span>
      )}
    </span>
  )
}
