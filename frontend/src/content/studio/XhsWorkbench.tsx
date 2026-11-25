import { useEffect, useState } from 'react'
import { API_BASE } from '../../api/base'
import { renderChatMarkdown } from '../../lib/markdown'
import { Loader2, Brain, ChevronDown, ChevronRight } from 'lucide-react'
import {
  type WorkbenchProps, stepLabel, goExternal, groupByProvider,
  card, inputStyle, goBtn, ghostBtn, COVER_MODEL_KEY,
} from './StudioShell'
import InlineTitleEditor from './InlineTitleEditor'
import CellCard from './xhs/CellCard'
import { type PageLabels } from './xhs/composeCard'

interface MPlatform { key: string; name: string; emoji?: string; home: string; accounts: MPAccount[] }
interface MPAccount { id: string; name: string; url?: string }

type PageStatus = 'pending' | 'done' | 'error' | 'generating'
interface PageCell {
  index: number
  type: 'cover' | 'content' | 'summary'
  status: PageStatus
  image_url?: string
  path?: string
  message?: string
  labels?: PageLabels
  palette?: string
}
const TYPE_CN: Record<string, string> = { cover: '封面', content: '内容', summary: '总结' }

function normalizeLabels(labels?: PageLabels): PageLabels {
  return {
    title: labels?.title || '',
    subtitle: labels?.subtitle || '',
    points: Array.isArray(labels?.points) ? labels!.points : [],
    header: labels?.header || '',
  }
}

export default function XhsWorkbench(p: WorkbenchProps) {
  const { proj, sel, setSel, busy, msg, setMsg } = p
  const [localBusy, setLocalBusy] = useState(false)
  const [draft, setDraft] = useState('')
  const [feedback, setFeedback] = useState('')
  const [preview, setPreview] = useState(false)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [streaming, setStreaming] = useState(false)
  const [streamText, setStreamText] = useState('')
  const [reasonText, setReasonText] = useState('')
  const [reasonOpen, setReasonOpen] = useState(true)
  const [cells, setCells] = useState<PageCell[]>([])
  const [batchMsg, setBatchMsg] = useState('')
  const [batchBusy, setBatchBusy] = useState(false)
  const [regenIndex, setRegenIndex] = useState<number | null>(null)
  const [editingPage, setEditingPage] = useState<number | null>(null)
  const [savingLabels, setSavingLabels] = useState(false)
  const [platforms, setPlatforms] = useState<MPlatform[]>([])
  const [dispatchRes, setDispatchRes] = useState<Record<string, { status: string; msg: string }>>({})

  useEffect(() => {
    fetch(`${API_BASE}/content/config`).then((r) => r.json()).then((d) => setPlatforms(d.platforms || [])).catch(() => {})
  }, [])

  function syncDraft() {
    const nd = proj.nodes[sel]
    if (!nd) return
    if (nd.type === 'data') {
      const dataObj = proj.state.data as Record<string, unknown> | undefined
      setDraft(typeof dataObj?.material === 'string' ? (dataObj.material as string) : '')
      return
    }
    const w = nd.writes
    const v = w ? proj.state[w] : ''
    setDraft(typeof v === 'string' ? v : '')
  }
  useEffect(() => { syncDraft() }, [proj, sel])  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const summary = (proj.state.images_summary as PageCell[] | undefined) || []
    if (summary.length) {
      const outlineLabels = parseOutlineToCells((proj.state.outline as string) || '')
      setCells(summary.map((c) => ({
        ...c,
        labels: c.labels || outlineLabels.find((x) => x.index === c.index)?.labels,
        palette: c.palette || outlineLabels.find((x) => x.index === c.index)?.palette,
        image_url: c.image_url || (c.path ? `${API_BASE}/studio/projects/${proj.id}/image?path=${encodeURIComponent(c.path)}` : undefined),
      })))
    } else {
      setCells([])
    }
  }, [proj.state.images_summary, proj.state.outline, proj.id])

  const writingStarted = streaming && streamText.length > 0
  useEffect(() => { if (writingStarted) setReasonOpen(false) }, [writingStarted])

  async function saveEdit(i: number) {
    if (!proj || busy || localBusy) return
    setLocalBusy(true); setMsg('')
    try {
      const d = await (await fetch(`${API_BASE}/studio/projects/${proj.id}/edit`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ index: i, content: draft }),
      })).json()
      if (d.ok) { await p.openProject(proj.id); setSel(i); setMsg('✓ 已保存修改') }
      else setMsg(d.error || '保存失败')
    } catch (e) { setMsg(`保存失败：${e}`) } finally { setLocalBusy(false) }
  }

  async function runTextStep(i: number, fb = '') {
    setStreaming(true); setStreamText(''); setReasonText(''); setReasonOpen(true)
    await p.runStep(i, {
      feedback: fb || undefined,
      onDelta: (t) => setStreamText((s) => s + t),
      onReason: (t) => setReasonText((s) => s + t),
    })
    setStreaming(false)
  }

  async function runImageBatch(i: number) {
    const outline = (proj.state.outline as string) || ''
    const parsed = parseOutlineToCells(outline)
    setCells(parsed.map((c) => ({ ...c, status: 'pending' })))
    setBatchMsg('正在生成封面…'); setBatchBusy(true); setStreaming(true)
    await p.runStep(i, {
      nodeModel: p.imgPick,
      onImage: (ev) => {
        if (ev.type === 'image_progress') {
          if (typeof ev.index === 'number' && ev.index >= 0) {
            setCells((cs) => cs.map((c) => (c.index === ev.index ? { ...c, status: 'generating', message: (ev.message as string) || '' } : c)))
          }
          if (ev.message) setBatchMsg(ev.message as string)
        } else if (ev.type === 'image_done') {
          const path = ev.path as string
          const fullUrl = path ? `${API_BASE}/studio/projects/${proj.id}/image?path=${encodeURIComponent(path)}` : ''
          setCells((cs) => cs.map((c) => (c.index === ev.index ? {
            ...c, status: 'done', image_url: fullUrl, path,
            labels: (ev.labels as PageLabels) || c.labels,
            palette: (ev.palette as string) || c.palette,
          } : c)))
          const phase = ev.phase as string
          setBatchMsg(phase === 'cover' ? '封面已生成，正在生成内容页…' : '正在生成内容页…')
        } else if (ev.type === 'image_error') {
          setCells((cs) => cs.map((c) => (c.index === ev.index ? { ...c, status: 'error', message: ev.message as string } : c)))
          setBatchMsg(`第 ${(ev.index as number) + 1} 页失败：${(ev.message as string || '').slice(0, 40)}`)
        } else if (ev.type === 'batch_finish') {
          setBatchMsg(`图组完成 ${ev.completed}/${ev.total}（失败 ${ev.failed}）`)
        }
      },
    })
    setBatchBusy(false); setStreaming(false)
    await p.openProject(proj.id, true)
  }

  function updatePageLabels(pageIndex: number, labels: PageLabels) {
    setCells((cs) => cs.map((c) => (c.index === pageIndex ? { ...c, labels } : c)))
  }

  async function savePageLabels(pageIndex: number) {
    const cell = cells.find((c) => c.index === pageIndex)
    if (!cell) return
    const labels = normalizeLabels(cell.labels)
    setSavingLabels(true); setMsg('')
    try {
      const d = await (await fetch(`${API_BASE}/studio/projects/${proj.id}/xhs-labels`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ page_index: pageIndex, labels, palette: cell.palette || '' }),
      })).json()
      if (d.ok) {
        setCells((cs) => cs.map((c) => (c.index === pageIndex ? { ...c, labels: (d.labels as PageLabels) || labels, palette: (d.palette as string) || c.palette } : c)))
        setMsg('✓ 图中文字已保存')
      } else setMsg(d.error || '保存图中文字失败')
    } catch (e) { setMsg(`保存图中文字失败：${e}`) } finally { setSavingLabels(false) }
  }

  async function regenPage(pageIndex: number) {
    setRegenIndex(pageIndex)
    setCells((cs) => cs.map((c) => (c.index === pageIndex ? { ...c, status: 'generating', message: '重新生成中…' } : c)))
    try {
      const d = await (await fetch(`${API_BASE}/studio/projects/${proj.id}/xhs-regen`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ page_index: pageIndex, model: p.imgPick.split('|')[0] || '', provider: p.imgPick.split('|')[1] || '' }),
      })).json()
      if (d.ok) { setCells((cs) => cs.map((c) => (c.index === pageIndex ? { ...c, status: 'done', image_url: `${API_BASE}/studio/projects/${proj.id}/image?path=${encodeURIComponent(d.path)}&_t=${Date.now()}`, path: d.path, labels: (d.labels as PageLabels) || c.labels, palette: (d.palette as string) || c.palette } : c))) }
      else { setCells((cs) => cs.map((c) => (c.index === pageIndex ? { ...c, status: 'error', message: d.error || '失败' } : c))) }
    } catch (e) {
      setCells((cs) => cs.map((c) => (c.index === pageIndex ? { ...c, status: 'error', message: String(e) } : c)))
    } finally { setRegenIndex(null) }
  }

  async function dispatchCopy(acc: MPAccount) {
    const finalText = ((proj.state.final as string) || draft || '').trim()
    const topic = (proj.inputs.topic || proj.title || '').trim()
    try { await navigator.clipboard.writeText(`${topic}\n\n${finalText}`) } catch { /* ignore */ }
    await goExternal(acc.url || 'https://creator.xiaohongshu.com')
    setDispatchRes((m) => ({ ...m, [acc.id]: { status: 'ok', msg: '已复制文案+打开后台' } }))
  }

  const node = proj.nodes[sel]
  const isData = node && node.type === 'data'
  const isImageBatch = node && node.type === 'image_batch'
  const isTextStep = node && (node.type === 'agent' || node.type === 'judge')
  const isDone = proj.done[sel]
  const isFinal = sel === proj.nodes.length - 1
  const curStyle = p.styleList.find((s) => s.id === p.stylePick)
  const doneCount = cells.filter((c) => c.status === 'done').length
  const editingCell = editingPage == null ? null : cells.find((c) => c.index === editingPage) || null
  const editingLabels = normalizeLabels(editingCell?.labels)

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, height: '100%' }}>
      {previewUrl && (
        <div onClick={() => setPreviewUrl(null)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.82)', zIndex: 1200, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
          <img src={previewUrl} alt="预览" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '92vw', maxHeight: '92vh', borderRadius: 12, boxShadow: '0 18px 60px rgba(0,0,0,0.55)' }} />
        </div>
      )}
      <div style={{ padding: '10px 18px', borderBottom: '1px solid rgba(127,127,127,0.18)', display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
          <button type="button" style={{ ...ghostBtn, flexShrink: 0 }} onClick={p.onBack}>返回</button>
          <InlineTitleEditor title={proj.title} onSave={p.renameCurrent} />
          <span style={{ fontSize: 12, opacity: 0.6, flexShrink: 0 }}>📕 {proj.name}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <select value={p.txtPick} onChange={(e) => { const v = e.target.value; p.setTxtPick(v); p.saveSettings({ model: v }) }} title="本篇写作模型" style={{ ...inputStyle, padding: '5px 8px', fontSize: 12, maxWidth: 260, background: 'var(--bg-card)' }}>
            <option value="">写作模型：默认{p.defaultModelName ? `（${p.defaultModelName}）` : ''}</option>
            {groupByProvider(p.txtModels).map(([prov, ms]) => (<optgroup key={prov} label={prov}>{ms.map((m) => <option key={`${m.model}|${m.provider}`} value={m.model}>{m.name}</option>)}</optgroup>))}
          </select>
          <select value={p.stylePick} onChange={(e) => { const v = e.target.value; p.setStylePick(v); p.saveSettings({ style: v }) }} title="写作风格" style={{ ...inputStyle, padding: '5px 8px', fontSize: 12, maxWidth: 200, background: 'var(--bg-card)' }}>
            <option value="">写作风格：默认</option>
            {p.styleList.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <button type="button" onClick={p.openEditor} title="编辑 / 新建写作风格" style={{ ...ghostBtn, padding: '5px 10px', fontSize: 12 }}>✏️ 风格</button>
        </div>
      </div>

      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        <div style={{ width: 180, borderRight: '1px solid rgba(127,127,127,0.18)', padding: 12, overflow: 'auto' }}>
          {proj.nodes.map((n, i) => {
            const mark = proj.done[i] ? '✓' : (i === proj.current ? '●' : '○')
            return (
              <button key={n.id} type="button" onClick={() => { setSel(i); setMsg('') }}
                style={{ display: 'block', width: '100%', textAlign: 'left', padding: '8px 10px', marginBottom: 4, borderRadius: 8, cursor: 'pointer', fontSize: 13,
                  border: '1px solid ' + (i === sel ? 'rgba(196,167,125,0.8)' : 'transparent'),
                  background: i === sel ? 'rgba(196,167,125,0.12)' : 'transparent', color: 'inherit', fontWeight: i === sel ? 600 : 400 }}>
                <span style={{ opacity: 0.7, marginRight: 6 }}>{mark}</span>{stepLabel(n)}
                {curStyle && n.role && curStyle.overrides?.includes(n.role) && (<span title={`此步应用「${curStyle.name}」风格`} style={{ marginLeft: 4, fontSize: 11 }}>✨</span>)}
              </button>
            )
          })}
        </div>

        <div style={{ flex: 1, minWidth: 0, overflow: 'auto', padding: 18 }}>
          {isImageBatch ? (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
                <div style={{ fontSize: 15, fontWeight: 600 }}>📕 图组预览</div>
                {cells.length > 0 && <span style={{ fontSize: 12, opacity: 0.6 }}>进度 {doneCount}/{cells.length}</span>}
                {batchMsg && <span style={{ fontSize: 12, opacity: 0.7, marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 4 }}>{batchBusy && <Loader2 size={12} className="spin" />}{batchMsg}</span>}
              </div>
              {cells.length === 0 ? (
                <div style={{ ...card, opacity: 0.6 }}>还没有图组。先完成「选题大纲」，再在右侧点「🎨 生成图组」。</div>
              ) : (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 14 }}>
                  {cells.map((c) => (
                    <div key={c.index} style={{ position: 'relative', aspectRatio: '3/4', borderRadius: 10, overflow: 'hidden', border: '1px solid rgba(127,127,127,0.22)', background: 'rgba(127,127,127,0.06)' }}>
                      <div style={{ position: 'absolute', top: 6, left: 6, zIndex: 2, padding: '2px 7px', borderRadius: 5, fontSize: 11, fontWeight: 600, background: 'rgba(0,0,0,0.55)', color: '#fff' }}>{TYPE_CN[c.type]}</div>
                      {c.status === 'done' && c.image_url ? (
                        <CellCard bgUrl={c.image_url} type={c.type} labels={normalizeLabels(c.labels)} palette={c.palette} onOpen={(dataUrl) => setPreviewUrl(dataUrl)} filename={`xhs_${proj.id}_${c.index}.png`} />
                      ) : (
                        <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 6, color: 'var(--text-color)', opacity: 0.6 }}>
                          {c.status === 'generating' ? <><Loader2 size={20} className="spin" /><span style={{ fontSize: 12 }}>生成中…</span></> : c.status === 'error' ? <><span style={{ fontSize: 22 }}>✗</span><span style={{ fontSize: 11, padding: '0 6px', textAlign: 'center' }}>{(c.message || '失败').slice(0, 40)}</span></> : <><span style={{ fontSize: 22, opacity: 0.4 }}>○</span><span style={{ fontSize: 11 }}>待生成</span></>}
                        </div>
                      )}
                      {c.status === 'done' && (
                        <>
                          <button type="button" title="编辑本页文字" onClick={(e) => { e.stopPropagation(); setEditingPage(c.index) }}
                            style={{ position: 'absolute', top: 6, right: 6, zIndex: 2, width: 26, height: 26, padding: 0, borderRadius: 6, border: 'none', cursor: 'pointer', background: editingPage === c.index ? 'rgba(196,167,125,0.92)' : 'rgba(0,0,0,0.6)', color: '#fff', fontSize: 13, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                            ✎
                          </button>
                          <button type="button" title="重新生成这页背景" disabled={regenIndex === c.index} onClick={(e) => { e.stopPropagation(); regenPage(c.index) }}
                            style={{ position: 'absolute', bottom: 6, right: 6, zIndex: 2, width: 26, height: 26, padding: 0, borderRadius: 6, border: 'none', cursor: 'pointer', background: 'rgba(0,0,0,0.6)', color: '#fff', fontSize: 13, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                            {regenIndex === c.index ? <Loader2 size={13} className="spin" /> : '↻'}
                          </button>
                        </>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : isData ? (
            <div className="studio-md-preview" style={{ padding: 4, fontSize: 14, lineHeight: 1.85, whiteSpace: 'pre-wrap', opacity: 0.85 }} dangerouslySetInnerHTML={{ __html: renderChatMarkdown(draft || '_资料收集步 — 在右侧点「🔍 联网搜资料」_') }} />
          ) : (
            <div style={{ maxWidth: 420, margin: '0 auto' }}>
              {streaming && reasonText && (
                <div style={{ marginBottom: 12, background: 'linear-gradient(180deg, rgba(196,167,125,0.08), rgba(127,127,127,0.035))', border: '1px solid rgba(196,167,125,0.2)', borderRadius: 10, overflow: 'hidden' }}>
                  <div onClick={() => setReasonOpen((o) => !o)} style={{ cursor: 'pointer', userSelect: 'none', display: 'flex', alignItems: 'center', gap: 6, padding: '8px 12px', fontSize: 12.5, fontWeight: 600, color: '#c4a77d' }}>
                    {writingStarted ? (reasonOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />) : <Brain size={13} />}
                    <span>{writingStarted ? '思考过程' : '模型思考中'}</span>
                    {!writingStarted && <span className="studio-pulse" style={{ marginLeft: 'auto' }}>●</span>}
                  </div>
                  {reasonOpen && <div style={{ padding: '0 12px 10px', fontSize: 12, lineHeight: 1.7, opacity: 0.72, whiteSpace: 'pre-wrap' }}>{reasonText}</div>}
                </div>
              )}
              <div className="studio-md-preview" style={{ padding: 4, fontSize: 15, lineHeight: 1.85 }}
                dangerouslySetInnerHTML={{ __html: renderChatMarkdown(streaming ? (streamText || '_正在生成…_') : (draft || '_这一步还没有内容 — 在右侧点「生成本步」_')) }} />
            </div>
          )}
        </div>

        <div style={{ width: 340, flexShrink: 0, padding: 16, overflow: 'auto', borderLeft: '1px solid rgba(127,127,127,0.18)' }}>
          <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 10 }}>{stepLabel(node)} {isDone && <span style={{ fontSize: 12, color: '#3a9d5d' }}>✓ 已完成</span>}</div>

          {isData && (
            <>
              <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 8 }}>资料可多来源：🔍 联网搜 · 直接粘贴素材 · 留空基于主题发挥</div>
              <textarea value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="联网搜的资料会填到这里，也可直接粘贴素材……" style={{ ...inputStyle, width: '100%', minHeight: 160, resize: 'vertical', lineHeight: 1.7, fontSize: 13, background: 'var(--bg-card)' }} />
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
                <button type="button" style={goBtn} disabled={busy} onClick={() => runTextStep(sel)}>{busy ? '搜索中…' : '🔍 联网搜资料'}</button>
                <button type="button" style={ghostBtn} disabled={busy} onClick={() => saveEdit(sel)}>💾 保存</button>
                {!isFinal && <button type="button" style={ghostBtn} onClick={() => { setSel(Math.min(sel + 1, proj.nodes.length - 1)); setMsg('') }}>下一步 →</button>}
              </div>
            </>
          )}

          {isTextStep && !streaming && (
            <>
              {!isDone && (
                <div style={{ ...card, opacity: 0.7, fontSize: 13, marginBottom: 10 }}>这一步还没生成。{sel > 0 && proj.done.slice(0, sel).some((d) => !d) ? '（建议先完成前面的步骤）' : ''}</div>
              )}
              {isDone && (
                <>
                  <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
                    <button type="button" onClick={() => setPreview(false)} style={{ ...ghostBtn, fontSize: 12, ...(preview ? {} : { background: 'rgba(196,167,125,0.14)', borderColor: 'rgba(196,167,125,0.8)' }) }}>✏️ 编辑</button>
                    <button type="button" onClick={() => setPreview(true)} style={{ ...ghostBtn, fontSize: 12, ...(preview ? { background: 'rgba(196,167,125,0.14)', borderColor: 'rgba(196,167,125,0.8)' } : {}) }}>👁 预览</button>
                  </div>
                  {preview ? (
                    <div className="studio-md-preview" style={{ ...inputStyle, width: '100%', minHeight: 200, maxHeight: 360, overflow: 'auto', lineHeight: 1.7, fontSize: 13, background: 'var(--bg-card)' }} dangerouslySetInnerHTML={{ __html: renderChatMarkdown(draft) }} />
                  ) : (
                    <textarea value={draft} onChange={(e) => setDraft(e.target.value)} style={{ ...inputStyle, width: '100%', minHeight: 200, resize: 'vertical', lineHeight: 1.7, fontSize: 13, background: 'var(--bg-card)' }} />
                  )}
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}>
                    <button type="button" style={ghostBtn} disabled={busy} onClick={() => saveEdit(sel)}>💾 保存</button>
                    <button type="button" style={ghostBtn} disabled={busy} onClick={() => runTextStep(sel)}>↻ 换一版</button>
                  </div>
                  <div style={{ ...card, marginTop: 10 }}>
                    <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 6 }}>给一句意见让它按你的改：</div>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                      <input value={feedback} onChange={(e) => setFeedback(e.target.value)} placeholder="如：标签再多几个、开头更口语" style={{ ...inputStyle, flex: 1, minWidth: 120 }} />
                      <button type="button" style={goBtn} disabled={busy || !feedback.trim()} onClick={() => runTextStep(sel, feedback.trim())}>重写</button>
                    </div>
                  </div>
                </>
              )}
              {!isDone && <button type="button" style={goBtn} disabled={busy} onClick={() => runTextStep(sel)}>{busy ? '生成中…' : '✨ 生成本步'}</button>}
              {isDone && !isFinal && <button type="button" style={{ ...goBtn, marginTop: 10 }} onClick={() => { setSel(Math.min(sel + 1, proj.nodes.length - 1)); setMsg('') }}>下一步 →</button>}
            </>
          )}

          {isImageBatch && (
            <>
              {editingCell && (
                <div style={{ ...card, marginBottom: 12, borderColor: 'rgba(196,167,125,0.55)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                    <div style={{ fontWeight: 600 }}>✎ 编辑第 {editingCell.index + 1} 页文字</div>
                    <span style={{ fontSize: 12, opacity: 0.6 }}>{TYPE_CN[editingCell.type]}</span>
                    <button type="button" onClick={() => setEditingPage(null)} style={{ ...ghostBtn, marginLeft: 'auto', padding: '3px 8px', fontSize: 12 }}>关闭</button>
                  </div>
                  <div style={{ fontSize: 12, opacity: 0.65, marginBottom: 8 }}>修改后左侧实时刷新；保存后刷新项目也不会丢。</div>
                  <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 4 }}>标题</div>
                  <input value={editingLabels.title} onChange={(e) => updatePageLabels(editingCell.index, { ...editingLabels, title: e.target.value })} placeholder="本页主标题" style={{ ...inputStyle, width: '100%', marginBottom: 8, background: 'var(--bg-card)' }} />
                  <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 4 }}>副标题 / 引导语</div>
                  <input value={editingLabels.subtitle} onChange={(e) => updatePageLabels(editingCell.index, { ...editingLabels, subtitle: e.target.value })} placeholder="可留空" style={{ ...inputStyle, width: '100%', marginBottom: 8, background: 'var(--bg-card)' }} />
                  <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 4 }}>页眉 / 标签</div>
                  <input value={editingLabels.header} onChange={(e) => updatePageLabels(editingCell.index, { ...editingLabels, header: e.target.value })} placeholder="如：核心要点 / 总结" style={{ ...inputStyle, width: '100%', marginBottom: 8, background: 'var(--bg-card)' }} />
                  <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 4 }}>要点（每行一个）</div>
                  <textarea value={editingLabels.points.join('\n')} onChange={(e) => updatePageLabels(editingCell.index, { ...editingLabels, points: e.target.value.split('\n').map((s) => s.trim()).filter(Boolean) })} placeholder="每行一个要点，内容页建议 1-4 行" style={{ ...inputStyle, width: '100%', minHeight: 112, resize: 'vertical', lineHeight: 1.55, fontSize: 13, background: 'var(--bg-card)' }} />
                  <button type="button" style={{ ...goBtn, width: '100%', marginTop: 10 }} disabled={savingLabels} onClick={() => savePageLabels(editingCell.index)}>
                    {savingLabels ? '保存中…' : '💾 保存本页文字'}
                  </button>
                </div>
              )}
              <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 8 }}>封面先行，内容页用封面作参考图保持风格统一。选一个生图模型：</div>
              <select value={p.imgPick} onChange={(e) => { p.setImgPick(e.target.value); try { localStorage.setItem(COVER_MODEL_KEY, e.target.value) } catch { /* ignore */ } }} style={{ ...inputStyle, width: '100%', marginBottom: 10, background: 'var(--bg-card)' }}>
                {p.imgModels.length === 0 && <option value="">（未配生图模型）</option>}
                {p.imgModels.map((m) => <option key={`${m.model}|${m.provider}`} value={`${m.model}|${m.provider}`}>{m.model} · {m.provider_name}</option>)}
              </select>
              <button type="button" style={{ ...goBtn, width: '100%' }} disabled={batchBusy} onClick={() => runImageBatch(sel)}>
                {batchBusy ? '生成中…' : isDone ? '↻ 重新生成图组' : '🎨 生成图组'}
              </button>
              {batchMsg && <div style={{ marginTop: 8, fontSize: 12, opacity: 0.8 }}>{batchMsg}</div>}
              {isDone && !isFinal && <button type="button" style={{ ...ghostBtn, width: '100%', marginTop: 10 }} onClick={() => { setSel(Math.min(sel + 1, proj.nodes.length - 1)); setMsg('') }}>下一步 →</button>}
              <div style={{ ...card, marginTop: 12, fontSize: 12, opacity: 0.65, lineHeight: 1.7 }}>
                💡 提示：点图片右上角 ✎ 可改叠字；右下角 ↻ 只重生成背景，已保存的文字会保留。
              </div>
            </>
          )}

          {isFinal && isDone && (
            <div style={{ ...card, borderColor: 'rgba(196,167,125,0.6)' }}>
              <div style={{ fontWeight: 600, marginBottom: 8 }}>📤 分发到小红书</div>
              {platforms.filter((pl) => pl.key === 'xhs' || pl.name.includes('小红书')).flatMap((pl) => pl.accounts).length === 0 && (
                <>
                  <div style={{ fontSize: 13, opacity: 0.6, marginBottom: 8 }}>未配小红书账号，直接复制文案 + 打开创作后台：</div>
                  <button type="button" style={{ ...goBtn, width: '100%' }} onClick={() => dispatchCopy({ id: 'adhoc', name: '小红书创作后台', url: 'https://creator.xiaohongshu.com' })}>复制文案 + 打开后台</button>
                </>
              )}
              {platforms.filter((pl) => pl.key === 'xhs' || pl.name.includes('小红书')).map((pl) => pl.accounts.map((a) => {
                const r = dispatchRes[a.id]
                return (
                  <div key={a.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0', borderTop: '1px solid rgba(127,127,127,0.1)' }}>
                    <span>{pl.emoji || '📕'}</span><span style={{ fontWeight: 500 }}>{a.name}</span>
                    <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
                      {r && <span style={{ fontSize: 12, color: r.status === 'ok' ? '#3a9d5d' : '#d66' }}>{r.status === 'ok' ? '✓ ' : '✗ '}{r.msg}</span>}
                      <button type="button" style={{ ...ghostBtn, padding: '5px 12px', fontSize: 13 }} onClick={() => dispatchCopy(a)}>复制+打开</button>
                    </div>
                  </div>
                )
              }))}
            </div>
          )}
          {msg && <div style={{ marginTop: 10, fontSize: 13, opacity: 0.8 }}>{msg}</div>}
        </div>
      </div>
    </div>
  )
}

function splitOutlineFragments(content: string): string[] {
  const normalized = (content || '').replace(/\|/g, '｜')
    .replace(/(?!^)\s*(?=(?:要点|重点)\s*\d+\s*[：:])/g, '\n')
    .replace(/(?!^)\s*(?=(?:副标题|小标题|互动引导|互动|结论|总结)\s*[：:])/g, '\n')
  return normalized.split(/[｜\n]+/).map((s) => s.trim()).filter(Boolean)
}

function cleanOutlineLabel(s: string, max: number): string {
  const text = (s || '')
    .replace(/^\s*(?:[-*•·]|\d+[).、]|#+)?\s*/, '')
    .replace(/^\s*(?:大标题|标题|主标题|副标题|小标题|正文|文案|页眉|页面标题|要点\s*\d*|重点\s*\d*|结论|总结|互动|互动引导|CTA|背景|画面|画面描述|主视觉|配图|插画|布局|留白|风格|色调|用户口吻|口吻|场景|元素|装饰)\s*[：:]\s*/i, '')
    .replace(/\s+/g, ' ')
    .trim()
  return Array.from(text).slice(0, max).join('')
}

function extractOutlineLabels(type: PageCell['type'], content: string): PageLabels {
  const fragments = splitOutlineFragments(content).map((s) => cleanOutlineLabel(s, 60)).filter(Boolean)
  if (type === 'cover') {
    return { title: cleanOutlineLabel(fragments[0] || '', 18), subtitle: cleanOutlineLabel(fragments[1] || '', 24), points: [], header: '' }
  }
  if (type === 'summary') {
    const sentenceParts = (fragments[0] || '').split(/[。.!！?？]/).map((s) => s.trim()).filter(Boolean)
    return {
      title: cleanOutlineLabel(sentenceParts[0] || fragments[0] || '总结', 20),
      subtitle: cleanOutlineLabel(sentenceParts[1] || fragments[1] || '点关注看更多', 24),
      points: fragments.slice(2, 5).map((s) => cleanOutlineLabel(s, 24)),
      header: '总结',
    }
  }
  const title = cleanOutlineLabel(fragments[0] || '核心要点', 18)
  return {
    title,
    subtitle: '',
    points: fragments.slice(0, 4).map((s) => cleanOutlineLabel(s, 46)),
    header: cleanOutlineLabel(title, 12),
  }
}

function parseOutlineToCells(outline: string): PageCell[] {
  const cells: (PageCell & { _content?: string })[] = []
  let cur: (PageCell & { _content?: string }) | null = null
  for (const raw of outline.split('\n')) {
    const line = raw.trim()
    if (!line) continue
    const m = line.match(/^\s*\[(封面|cover|内容|content|总结|summary)\]\s*(.*)$/i)
    if (m) {
      const t = m[1].toLowerCase()
      const type: PageCell['type'] = (t === '封面' || t === 'cover') ? 'cover' : (t === '总结' || t === 'summary') ? 'summary' : 'content'
      cur = { index: cells.length, type, status: 'pending', _content: m[2].trim(), palette: 'warm' }
      cells.push(cur)
    } else if (cur) {
      cur._content = `${cur._content || ''}\n${line}`.trim()
    }
  }
  if (cells.length === 0 && outline.trim()) cells.push({ index: 0, type: 'cover', status: 'pending', _content: outline.trim(), palette: 'warm' })
  if (cells.length > 0 && !cells.some((c) => c.type === 'cover')) cells[0].type = 'cover'
  if (cells.length > 1 && !cells.some((c) => c.type === 'summary')) cells[cells.length - 1].type = 'summary'
  return cells.map(({ _content, ...c }) => ({ ...c, labels: extractOutlineLabels(c.type, _content || '') }))
}
