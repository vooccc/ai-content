import { useEffect, useRef, useState } from 'react'
import { API_BASE } from '../../api/base'
import { renderChatMarkdown } from '../../lib/markdown'
import { Loader2, Brain, PenLine, ChevronDown, ChevronRight } from 'lucide-react'
import {
  type WorkbenchProps, stepLabel, goExternal, groupByProvider,
  card, inputStyle, goBtn, ghostBtn, COVER_MODEL_KEY,
} from './StudioShell'

interface MPlatform { key: string; name: string; emoji?: string; home: string; accounts: MPAccount[] }
interface MPAccount { id: string; name: string; url?: string; appid?: string; secret?: string; thumb_media_id?: string }

export default function WechatWorkbench(p: WorkbenchProps) {
  const { proj, sel, setSel, busy, msg, setMsg } = p
  const [localBusy, setLocalBusy] = useState(false)
  const draft_busy = busy || localBusy
  const [draft, setDraft] = useState('')
  const [feedback, setFeedback] = useState('')
  const [preview, setPreview] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const [streamText, setStreamText] = useState('')
  const [reasonText, setReasonText] = useState('')
  const [reasonOpen, setReasonOpen] = useState(true)
  const streamRef = useRef<HTMLDivElement>(null)
  const stickBottom = useRef(true)
  const [cbOpen, setCbOpen] = useState(false)
  const [cbQuery, setCbQuery] = useState('')
  const [cbBusy, setCbBusy] = useState(false)
  const [cbList, setCbList] = useState<{ title: string; url: string; summary: string; source: string; date: string }[]>([])
  const [cbMsg, setCbMsg] = useState('')
  const [coverUrl, setCoverUrl] = useState('')
  const [coverBusy, setCoverBusy] = useState(false)
  const [coverMsg, setCoverMsg] = useState('')
  const [imgLib, setImgLib] = useState<{ name: string; path: string }[]>([])
  const [localDir, setLocalDir] = useState('')
  const [dirPickerOpen, setDirPickerOpen] = useState(false)
  const [dirCurrent, setDirCurrent] = useState('')
  const [dirParent, setDirParent] = useState('')
  const [dirItems, setDirItems] = useState<{ name: string; path: string }[]>([])
  const [dirErr, setDirErr] = useState('')
  const [urlsText, setUrlsText] = useState('')
  const [previewImg, setPreviewImg] = useState<{ name: string; path: string } | null>(null)
  const [hoverImg, setHoverImg] = useState<string | null>(null)
  const [imgScale, setImgScale] = useState(1)
  const [imgPos, setImgPos] = useState({ x: 0, y: 0 })
  const dragRef = useRef<{ x: number; y: number } | null>(null)
  const [platforms, setPlatforms] = useState<MPlatform[]>([])
  const [dispatchRes, setDispatchRes] = useState<Record<string, { status: string; msg: string }>>({})

  useEffect(() => {
    fetch(`${API_BASE}/content/config`).then((r) => r.json()).then((d) => setPlatforms(d.platforms || [])).catch(() => {})
  }, [])

  function syncDraft() {
    const nd = proj.nodes[sel]
    if (!nd) return
    if (nd.id === 'collect' || (nd.type === 'data' && nd.writes === 'data')) {
      const dataObj = proj.state.data as Record<string, unknown> | undefined
      setDraft(typeof dataObj?.material === 'string' ? (dataObj.material as string) : '')
      return
    }
    const w = nd.writes
    const v = w ? proj.state[w] : ''
    if (v && typeof v === 'object') {
      const obj = v as Record<string, unknown>
      if (typeof obj.markdown === 'string') { setDraft(obj.markdown); return }
      if (typeof obj.html === 'string') { setDraft(obj.html); return }
      if (typeof obj.material === 'string') { setDraft(obj.material); return }
      setDraft('')
      return
    }
    setDraft(typeof v === 'string' ? v : '')
  }
  useEffect(() => { syncDraft() }, [proj, sel])  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setCoverUrl((proj.state._cover as string) || '') }, [proj.state._cover])
  useEffect(() => {
    const imgs = (proj.state.images as { name: string; path: string }[] | undefined) || []
    setImgLib(imgs)
  }, [proj.state.images])

  function onStreamScroll() {
    const el = streamRef.current
    if (!el) return
    stickBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48
  }
  useEffect(() => { const el = streamRef.current; if (el && stickBottom.current) el.scrollTop = el.scrollHeight }, [streamText, reasonText])
  useEffect(() => { if (streaming) stickBottom.current = true }, [streaming])
  const writingStarted = streaming && streamText.length > 0
  useEffect(() => { if (writingStarted) setReasonOpen(false) }, [writingStarted])

  async function loadBrowseDirs(path = '') {
    setDirErr('')
    try {
      const d = await (await fetch(`${API_BASE}/studio/browse-dirs${path ? `?path=${encodeURIComponent(path)}` : ''}`)).json()
      setDirCurrent(d.current || '')
      setDirParent(d.parent || '')
      setDirItems(d.dirs || [])
      if (!d.ok && d.error) setDirErr(d.error)
    } catch (e) {
      setDirErr(String(e))
    }
  }
  function browseDir() {
    setDirPickerOpen(true)
    void loadBrowseDirs(localDir.trim())
  }
  async function importLocalDir() {
    if (!proj || draft_busy || !localDir.trim()) return
    setLocalBusy(true); setMsg('正在读取本地素材…')
    try {
      const d = await (await fetch(`${API_BASE}/studio/projects/${proj.id}/import-local`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ dir: localDir.trim() }),
      })).json()
      if (d.ok) { await p.openProject(proj.id); setSel(0); setMsg(`✓ 已导入 ${d.count} 篇文章、${d.image_count || 0} 张图片`) }
      else setMsg(`✗ ${d.error || '导入失败'}`)
    } catch (e) { setMsg(`✗ 导入失败：${e}`) } finally { setLocalBusy(false) }
  }
  async function importUrls() {
    if (!proj || draft_busy || !urlsText.trim()) return
    setLocalBusy(true); setMsg('正在抓取网络素材…')
    try {
      const d = await (await fetch(`${API_BASE}/studio/projects/${proj.id}/import-urls`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ urls: urlsText }),
      })).json()
      if (d.ok) { await p.openProject(proj.id); setSel(0); setUrlsText(''); setMsg(`✓ 已抓取 ${d.count} 篇${d.failed ? `（${d.failed} 篇失败）` : ''}`) }
      else setMsg(`✗ ${d.error || '抓取失败'}`)
    } catch (e) { setMsg(`✗ 抓取失败：${e}`) } finally { setLocalBusy(false) }
  }
  function studioImgUrl(path: string) { return `${API_BASE}/studio/projects/${proj.id}/image?path=${encodeURIComponent(path)}` }
  function insertImage(img: { name: string; path: string }) {
    setDraft((dft) => `${dft}\n\n![${img.name}](${studioImgUrl(img.path)})\n\n`)
    setPreview(true); setPreviewImg(null); setMsg(`已插入图片「${img.name}」，记得点保存修改`)
  }
  async function removeImage(img: { name: string; path: string }) {
    try {
      const d = await (await fetch(`${API_BASE}/studio/projects/${proj.id}/remove-image`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: img.path }),
      })).json()
      if (d.ok) { setImgLib(d.images || []); setPreviewImg(null) }
    } catch { /* ignore */ }
  }
  async function saveEdit(i: number) {
    if (!proj || draft_busy) return
    setLocalBusy(true); setMsg('')
    try {
      const d = await (await fetch(`${API_BASE}/studio/projects/${proj.id}/edit`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ index: i, content: draft }),
      })).json()
      if (d.ok) { await p.openProject(proj.id); setSel(i); setMsg('✓ 已保存修改') }
      else setMsg(d.error || '保存失败')
    } catch (e) { setMsg(`保存失败：${e}`) } finally { setLocalBusy(false) }
  }
  async function runStep(i: number, fb = '') {
    setStreaming(true); setStreamText(''); setReasonText(''); setReasonOpen(true)
    await p.runStep(i, {
      feedback: fb || undefined,
      onDelta: (t) => setStreamText((s) => s + t),
      onReason: (t) => setReasonText((s) => s + t),
    })
    setStreaming(false)
  }
  async function runAll(fromStart = false) {
    if (!proj || draft_busy) return
    setLocalBusy(true); setStreaming(true)
    const total = proj.nodes.length
    let i = fromStart ? 0 : proj.current
    try {
      while (i < total) {
        setMsg(`一键成稿：第 ${i + 1}/${total} 步…`); setStreamText(''); setReasonText(''); setReasonOpen(true)
        const res = await fetch(`${API_BASE}/studio/projects/${proj.id}/step`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ index: i, feedback: '', model: p.txtPick, style: p.stylePick, node_model: p.stepModels[proj.nodes[i]?.id] || '' }),
        })
        const r = await consumeLocal(res, (t) => setStreamText((s) => s + t), (t) => setReasonText((s) => s + t))
        if (!r.ok) { setMsg(`✗ 第 ${i + 1} 步失败：${r.error || '出错'}`); break }
        i = fromStart ? i + 1 : (typeof r.current === 'number' ? r.current : i + 1)
      }
      await p.openProject(proj.id, true)
      setSel(total - 1)
      if (i >= total) setMsg('✓ 已一键成稿，停在排版；可预览 HTML、复制或推草稿箱；封面可在配图步生成')
    } catch (e) { setMsg(`✗ 一键成稿失败：${e}`) } finally { setLocalBusy(false); setStreaming(false) }
  }
  async function consumeLocal(res: Response, onDelta: (t: string) => void, onReason: (t: string) => void) {
    if (!res.body) return { ok: false, error: '无响应流' }
    const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = ''
    let result: { ok: boolean; error?: string; current?: number } = { ok: false, error: '未完成' }
    // eslint-disable-next-line no-constant-condition
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      const parts = buf.split('\n\n'); buf = parts.pop() || ''
      for (const part of parts) {
        const line = part.trim(); if (!line.startsWith('data:')) continue
        try {
          const ev = JSON.parse(line.slice(5).trim())
          if (ev.type === 'delta') onDelta(ev.text || '')
          else if (ev.type === 'reasoning') onReason(ev.text || '')
          else if (ev.type === 'step') result = { ok: true, current: ev.current }
          else if (ev.type === 'error') result = { ok: false, error: ev.msg || '出错' }
        } catch { /* 跳过 */ }
      }
    }
    return result
  }
  function openCompare() {
    setCbOpen(true); setCbQuery((proj.inputs as { topic?: string })?.topic || ''); setCbList([]); setCbMsg('')
  }
  async function searchCompare() {
    const q = cbQuery.trim()
    if (!q) { setCbMsg('请输入搜索词'); return }
    setCbBusy(true); setCbMsg(''); setCbList([])
    try {
      const d = await (await fetch(`${API_BASE}/studio/search-wechat?q=${encodeURIComponent(q)}&n=10`)).json()
      const arts = d.articles || []
      setCbList(arts)
      if (arts.length === 0) setCbMsg('没搜到（可能搜狗反爬，换个词或稍后再试）')
    } catch (e) { setCbMsg(`搜索失败：${e}`) } finally { setCbBusy(false) }
  }
  async function genCover() {
    if (!proj || coverBusy) return
    const prompt = draft.trim()
    if (!prompt) { setCoverMsg('配图提示词为空，先生成本步'); return }
    setCoverBusy(true); setCoverMsg('生成封面图中…（首次较慢）')
    try {
      const d = await (await fetch(`${API_BASE}/studio/projects/${proj.id}/cover`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, model: p.imgPick.split('|')[0] || '', provider: p.imgPick.split('|')[1] || '' }),
      })).json()
      if (d.ok) { setCoverUrl(d.image); setCoverMsg('✓ 封面已生成') }
      else setCoverMsg(`✗ ${d.error || '生成失败'}`)
    } catch (e) { setCoverMsg(`✗ 生成失败：${e}`) } finally { setCoverBusy(false) }
  }
  function dispatchContent(): string {
    const layout = proj.state.layout as Record<string, unknown> | undefined
    if (layout && typeof layout.html === 'string' && layout.html.trim()) return layout.html
    const final = proj.state.final
    if (typeof final === 'string' && final.trim()) return final
    return draft
  }
  async function dispatchWechat(acc: MPAccount, title: string) {
    if (!acc.appid || !acc.secret) { setDispatchRes((m) => ({ ...m, [acc.id]: { status: 'err', msg: '未配凭证，去「多平台发布」填' } })); return }
    const content = dispatchContent()
    if (!content.trim()) { setDispatchRes((m) => ({ ...m, [acc.id]: { status: 'err', msg: '没有可推送内容，请先完成定稿/排版' } })); return }
    setDispatchRes((m) => ({ ...m, [acc.id]: { status: 'loading', msg: '' } }))
    try {
      const d = await (await fetch(`${API_BASE}/content/dispatch/wechat`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, content, appid: acc.appid, secret: acc.secret, thumb_media_id: acc.thumb_media_id || '', cover_url: coverUrl || '' }),
      })).json()
      setDispatchRes((m) => ({ ...m, [acc.id]: d.ok ? { status: 'ok', msg: coverUrl ? '已进草稿箱（用本篇封面）' : '已进草稿箱' } : { status: 'err', msg: d.error || '失败' } }))
    } catch (e) { setDispatchRes((m) => ({ ...m, [acc.id]: { status: 'err', msg: `${e}` } })) }
  }
  async function dispatchCopy(plat: MPlatform, acc: MPAccount, title: string) {
    const content = dispatchContent()
    try { await navigator.clipboard.writeText(content.startsWith('<') ? content : `${title}\n\n${content}`) } catch { /* ignore */ }
    await goExternal(acc.url || plat.home)
    setDispatchRes((m) => ({ ...m, [acc.id]: { status: 'ok', msg: content.startsWith('<') ? '已复制 HTML+打开后台' : '已复制+打开后台' } }))
  }

  const node = proj.nodes[sel]
  const isEditable = node && (node.type === 'agent' || node.type === 'judge')
  const isHuman = node && node.type === 'human'
  const isLayoutStep = node && (node.id === 'format' || node.writes === 'layout')
  const isCollectStep = node && (node.id === 'collect' || (node.type === 'data' && node.writes === 'data'))
  const isImageStep = node && (node.id === 'image_brief' || node.role === 'art_director')
  const isDone = proj.done[sel]
  const isFinal = sel === proj.nodes.length - 1
  const title = (proj.inputs.topic || proj.title || '').slice(0, 64)
  const curStyle = p.styleList.find((s) => s.id === p.stylePick)
  const layoutObj = (proj.state.layout as Record<string, unknown> | undefined) || undefined
  const layoutHtml = (isLayoutStep && layoutObj && typeof layoutObj.html === 'string') ? (layoutObj.html as string) : ''
  const layoutMeta = (layoutObj && typeof layoutObj.metadata === 'object' && layoutObj.metadata) ? (layoutObj.metadata as Record<string, unknown>) : null

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, height: '100%' }}>
      {dirPickerOpen && (
        <div onClick={() => setDirPickerOpen(false)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', zIndex: 1050, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
          <div onClick={(e) => e.stopPropagation()} style={{ background: 'var(--bg-card, #1c2128)', border: '1px solid rgba(127,127,127,0.3)', borderRadius: 12, padding: 18, width: 'min(560px, 94vw)', maxHeight: '80vh', display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ fontSize: 15, fontWeight: 600 }}>📁 选择本地素材目录</div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <button type="button" style={ghostBtn} disabled={!dirParent} onClick={() => loadBrowseDirs(dirParent)}>↑ 上级</button>
              <input value={dirCurrent} onChange={(e) => setDirCurrent(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') loadBrowseDirs(dirCurrent) }} style={{ ...inputStyle, flex: 1, fontSize: 13 }} />
              <button type="button" style={ghostBtn} onClick={() => loadBrowseDirs(dirCurrent)}>跳转</button>
            </div>
            {dirErr && <div style={{ fontSize: 12, color: '#d66' }}>{dirErr}</div>}
            <div style={{ flex: 1, minHeight: 200, maxHeight: 360, overflow: 'auto', border: '1px solid rgba(127,127,127,0.2)', borderRadius: 8, padding: 6 }}>
              {dirItems.length === 0 && <div style={{ padding: 12, fontSize: 13, opacity: 0.6 }}>此目录下没有子文件夹</div>}
              {dirItems.map((it) => (
                <div key={it.path} onClick={() => loadBrowseDirs(it.path)} style={{ padding: '7px 10px', borderRadius: 6, cursor: 'pointer', fontSize: 13, display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span>📁</span><span>{it.name}</span>
                </div>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button type="button" style={ghostBtn} onClick={() => setDirPickerOpen(false)}>取消</button>
              <button type="button" style={goBtn} disabled={!dirCurrent} onClick={() => { setLocalDir(dirCurrent); setDirPickerOpen(false) }}>选择此目录</button>
            </div>
          </div>
        </div>
      )}
      {cbOpen && (
        <div onClick={() => setCbOpen(false)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
          <div onClick={(e) => e.stopPropagation()} style={{ background: 'var(--bg-card, #1c2128)', border: '1px solid rgba(127,127,127,0.3)', borderRadius: 12, padding: 20, width: 'min(820px, 94vw)', maxHeight: '88vh', overflow: 'auto' }}>
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 4 }}>🔍 公众号对标搜索</div>
            <div style={{ fontSize: 12, opacity: 0.6, marginBottom: 14 }}>搜同主题的公众号文章，看人家的标题/角度做选题参考（来自搜狗微信搜索，无阅读量数据）。</div>
            <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
              <input value={cbQuery} onChange={(e) => setCbQuery(e.target.value)} placeholder="搜索词（默认=本篇主题）" onKeyDown={(e) => { if (e.key === 'Enter') searchCompare() }} style={{ ...inputStyle, flex: 1 }} />
              <button type="button" style={goBtn} disabled={cbBusy} onClick={searchCompare}>{cbBusy ? '搜索中…' : '搜索'}</button>
              <button type="button" style={ghostBtn} onClick={() => setCbOpen(false)}>关闭</button>
            </div>
            {cbMsg && <div style={{ fontSize: 13, opacity: 0.8, marginBottom: 10 }}>{cbMsg}</div>}
            {cbList.map((a, i) => (
              <div key={i} style={{ ...card, marginBottom: 8 }}>
                <div onClick={() => { if (a.url) goExternal(a.url) }} title={a.url ? '点击打开原文（搜狗跳转）' : ''} style={{ fontWeight: 600, fontSize: 14, color: a.url ? '#5aa9e6' : 'inherit', cursor: a.url ? 'pointer' : 'default' }}>{a.title}{a.url ? ' ↗' : ''}</div>
                <div style={{ fontSize: 12, opacity: 0.6, margin: '3px 0' }}>{a.source}{a.date ? ` · ${a.date}` : ''}</div>
                {a.summary && <div style={{ fontSize: 13, opacity: 0.85, lineHeight: 1.6 }}>{a.summary}</div>}
              </div>
            ))}
          </div>
        </div>
      )}
      {previewImg && (
        <div onClick={() => setPreviewImg(null)}
          onMouseMove={(e) => { if (dragRef.current) setImgPos({ x: e.clientX - dragRef.current.x, y: e.clientY - dragRef.current.y }) }}
          onMouseUp={() => { dragRef.current = null }}
          onMouseLeave={() => { dragRef.current = null }}
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.72)', zIndex: 1100, display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }}>
          <img src={studioImgUrl(previewImg.path)} alt={previewImg.name} draggable={false}
            onClick={(e) => e.stopPropagation()}
            onDoubleClick={() => { setImgScale(1); setImgPos({ x: 0, y: 0 }) }}
            onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); dragRef.current = { x: e.clientX - imgPos.x, y: e.clientY - imgPos.y } }}
            onWheel={(e) => { e.stopPropagation(); setImgScale((s) => Math.min(8, Math.max(0.3, +(s + (e.deltaY < 0 ? 0.25 : -0.25)).toFixed(2)))) }}
            style={{ maxWidth: '92vw', maxHeight: '88vh', objectFit: 'contain', borderRadius: 8, transform: `translate(${imgPos.x}px, ${imgPos.y}px) scale(${imgScale})`, transformOrigin: 'center', boxShadow: '0 8px 40px rgba(0,0,0,0.5)', cursor: imgScale > 1 ? 'grab' : 'zoom-in' }} />
          <div onClick={(e) => e.stopPropagation()} style={{ position: 'fixed', bottom: 24, left: '50%', transform: 'translateX(-50%)', display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'center', background: 'rgba(0,0,0,0.6)', padding: '8px 14px', borderRadius: 10, zIndex: 1101 }}>
            <span style={{ fontSize: 13, color: '#fff', opacity: 0.85, maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{previewImg.name}</span>
            <span style={{ fontSize: 12, color: '#fff', opacity: 0.7 }}>{Math.round(imgScale * 100)}% · 滚轮缩放·拖动·双击复位</span>
          </div>
        </div>
      )}
      <div style={{ padding: '12px 18px', borderBottom: '1px solid rgba(127,127,127,0.18)', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <button type="button" style={ghostBtn} onClick={p.onBack}>返回</button>
        <div style={{ fontWeight: 600 }}>{proj.title}</div>
        <span style={{ fontSize: 12, opacity: 0.6 }}>📄 {proj.name}</span>
        <select value={p.txtPick} onChange={(e) => { const v = e.target.value; p.setTxtPick(v); p.saveSettings({ model: v }) }} title="本篇写作模型" style={{ ...inputStyle, padding: '5px 8px', fontSize: 12, maxWidth: 240, background: 'var(--bg-card)' }}>
          <option value="">写作模型：默认{p.defaultModelName ? `（${p.defaultModelName}）` : ''}</option>
          {groupByProvider(p.txtModels).map(([prov, ms]) => (<optgroup key={prov} label={prov}>{ms.map((m) => <option key={`${m.model}|${m.provider}`} value={m.model}>{m.name}</option>)}</optgroup>))}
        </select>
        <select value={p.stylePick} onChange={(e) => { const v = e.target.value; p.setStylePick(v); p.saveSettings({ style: v }) }} title={p.styleList.find((s) => s.id === p.stylePick)?.desc || '写作风格（默认=通用）'} style={{ ...inputStyle, padding: '5px 8px', fontSize: 12, maxWidth: 200, background: 'var(--bg-card)' }}>
          <option value="">写作风格：默认</option>
          {p.styleList.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <button type="button" onClick={p.openEditor} title="编辑 / 新建写作风格" style={{ ...ghostBtn, padding: '5px 10px', fontSize: 12 }}>✏️ 风格</button>
        <button type="button" onClick={openCompare} title="搜公众号对标文章（选题参考）" style={{ ...ghostBtn, padding: '5px 10px', fontSize: 12 }}>🔍 对标</button>
        <button type="button" style={{ ...goBtn, marginLeft: 'auto' }} disabled={busy}
          onClick={() => { if (proj.current < proj.nodes.length) { runAll() } else if (window.confirm('重新成稿会从第一步开始覆盖现有全部内容，确定吗？')) { runAll(true) } }}>
          {busy ? '运行中…' : (proj.current < proj.nodes.length ? '⚡ 一键成稿' : '↻ 重新成稿')}
        </button>
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

        <div style={{ flexShrink: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '12px 24px', background: 'radial-gradient(700px 360px at 50% -130px, rgba(196,167,125,0.08), transparent 70%)' }}>
          <div style={{ width: 348, flex: '1 1 auto', minHeight: 0, maxHeight: 1600, background: 'var(--bg-card)', border: '1px solid rgba(127,127,127,0.18)', borderRadius: 30, boxShadow: '0 24px 60px -14px rgba(0,0,0,0.32), 0 8px 22px rgba(0,0,0,0.14)', padding: 6, display: 'flex', flexDirection: 'column', position: 'relative' }}>
            <div style={{ flex: 1, minHeight: 0, background: 'var(--bg-color)', borderRadius: 24, overflow: 'hidden', border: '1px solid rgba(127,127,127,0.14)', display: 'flex', flexDirection: 'column' }}>
              <div style={{ height: 28, flexShrink: 0, position: 'relative', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 20px', fontSize: 11.5, fontWeight: 600, opacity: 0.85 }}>
                <span>9:41</span>
                <span style={{ position: 'absolute', left: '50%', top: 10, transform: 'translateX(-50%)', width: 7, height: 7, borderRadius: '50%', background: 'rgba(0,0,0,0.55)' }} />
                <span style={{ fontSize: 10.5, opacity: 0.7 }}>5G ▮▮ 🔋</span>
              </div>
              <div ref={streamRef} onScroll={onStreamScroll} style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
                <div style={{ padding: '14px 22px', borderBottom: '1px solid rgba(127,127,127,0.12)' }}>
                  <div style={{ fontSize: 20, lineHeight: 1.45, fontWeight: 700, letterSpacing: -0.2, marginBottom: 12 }}>{title || '未命名文章'}</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, opacity: 0.78 }}>
                    <span style={{ width: 22, height: 22, borderRadius: '50%', background: 'linear-gradient(135deg,#c4a77d,#8a6c49)', flexShrink: 0, boxShadow: '0 1px 3px rgba(138,108,73,0.4)' }} />
                    <span style={{ color: '#b08d57', fontWeight: 600 }}>{proj.name || 'AI Content'}</span>
                    <span style={{ opacity: 0.55 }}>·</span>
                    <span style={{ opacity: 0.6 }}>{stepLabel(node)}</span>
                    {streaming && <span style={{ marginLeft: 'auto', fontSize: 11, fontWeight: 600, color: '#c4a77d', display: 'inline-flex', alignItems: 'center', gap: 4 }}><span className="studio-pulse">●</span>生成中</span>}
                  </div>
                </div>
                {streaming && reasonText && (
                  <div style={{ margin: '12px 18px 0', background: 'linear-gradient(180deg, rgba(196,167,125,0.08), rgba(127,127,127,0.035))', border: '1px solid rgba(196,167,125,0.2)', borderRadius: 10, overflow: 'hidden' }}>
                    <div onClick={() => setReasonOpen((o) => !o)} style={{ cursor: 'pointer', userSelect: 'none', display: 'flex', alignItems: 'center', gap: 6, padding: '8px 12px', fontSize: 12.5, fontWeight: 600, color: '#c4a77d' }}>
                      {writingStarted ? (reasonOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />) : <Brain size={13} />}
                      <span>{writingStarted ? '思考过程' : '模型思考中'}</span>
                      {writingStarted ? <span style={{ fontSize: 11, opacity: 0.6, fontWeight: 400 }}>· 点按{reasonOpen ? '收起' : '展开'}</span> : <span className="studio-pulse" style={{ marginLeft: 'auto' }}>●</span>}
                    </div>
                    {reasonOpen && (<div style={{ padding: '0 12px 10px', fontSize: 12, lineHeight: 1.7, color: 'var(--text-color)', opacity: 0.72, whiteSpace: 'pre-wrap' }}>{reasonText}</div>)}
                  </div>
                )}
                <div className="studio-md-preview" style={{ padding: layoutHtml ? '8px 4px 24px' : '16px 20px 32px', fontSize: 15, lineHeight: 1.85 }}
                  dangerouslySetInnerHTML={{
                    __html: streaming
                      ? renderChatMarkdown(streamText || (reasonText ? '_思考完成后将在此处开始撰写…_' : '_正在连接模型…_'))
                      : (layoutHtml
                        ? layoutHtml
                        : renderChatMarkdown(draft || '_这一步还没有内容 — 在右侧点「生成本步」开始_'))
                  }} />
              </div>
            </div>
          </div>
        </div>

        <div style={{ flex: 1, minWidth: 360, padding: 16, overflow: 'auto', borderLeft: '1px solid rgba(127,127,127,0.18)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, position: 'sticky', top: 0, zIndex: 6, background: 'var(--bg-color)', paddingBottom: 10 }}>
            <div style={{ fontSize: 15, fontWeight: 600 }}>{stepLabel(node)} {isDone && <span style={{ fontSize: 12, color: '#3a9d5d' }}>✓ 已完成</span>}</div>
            {isEditable && (
              <select value={p.stepModels[node.id] || ''} onChange={(e) => { const ns = { ...p.stepModels, [node.id]: e.target.value }; p.setStepModels(ns); p.saveSettings({ step_models: ns }) }} title="本步模型（默认=跟随整篇写作模型）" style={{ ...inputStyle, marginLeft: 'auto', padding: '4px 8px', fontSize: 12, maxWidth: 200, background: 'var(--bg-card)' }}>
                <option value="">{`本步模型：跟随整篇（${(() => { const t = p.txtModels.find((x) => x.model === p.txtPick); return t ? (t.name || t.model) : (p.txtPick || p.defaultModelName || '默认') })()}）`}</option>
                {groupByProvider(p.txtModels).map(([prov, ms]) => (<optgroup key={prov} label={prov}>{ms.map((m) => <option key={`${m.model}|${m.provider}`} value={m.model}>{m.name}</option>)}</optgroup>))}
              </select>
            )}
          </div>

          {streaming && (
            <div style={{ ...card, display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, fontWeight: 600, letterSpacing: 0.3, color: '#c4a77d', background: 'linear-gradient(180deg, rgba(196,167,125,0.08), rgba(127,127,127,0.04))', border: '1px solid rgba(196,167,125,0.22)' }}>
              {streamText ? <PenLine size={14} /> : reasonText ? <Brain size={14} /> : <Loader2 size={14} className="spin" />}
              <span>{streamText ? '正在撰写正文' : reasonText ? '模型思考中' : '正在连接模型'}</span>
              <span style={{ marginLeft: 'auto', fontSize: 11, fontWeight: 400, opacity: 0.65 }}>详见手机画布</span>
              <span className="studio-pulse">●</span>
            </div>
          )}

          {!streaming && !isDone && !isHuman && !isCollectStep && !isLayoutStep && (
            <div style={card}>
              <div style={{ opacity: 0.7, fontSize: 13, marginBottom: 10 }}>这一步还没生成。{sel > 0 && proj.done.slice(0, sel).some((d) => !d) ? '（建议先完成前面的步骤）' : ''}</div>
              <button type="button" style={goBtn} disabled={busy} onClick={() => runStep(sel)}>{busy ? '生成中…' : '✨ 生成本步'}</button>
            </div>
          )}

          {!streaming && isLayoutStep && (
            <>
              <div style={card}>
                <div style={{ fontSize: 13, opacity: 0.8, marginBottom: 10, lineHeight: 1.65 }}>
                  把<strong>定稿</strong>转成公众号可粘贴的内联 HTML（按当前写作风格套视觉模板）。
                  不改写内容；若改过终稿，回到定稿步保存后再点「重新排版」。
                </div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                  <button type="button" style={goBtn} disabled={busy} onClick={() => runStep(sel)}>
                    {busy ? '排版中…' : (isDone ? '↻ 重新排版' : '✨ 生成排版')}
                  </button>
                  {layoutHtml && (
                    <button type="button" style={ghostBtn} onClick={async () => {
                      try { await navigator.clipboard.writeText(layoutHtml); setMsg('✓ 已复制排版 HTML，可粘贴到公众号编辑器') }
                      catch { setMsg('✗ 复制失败，请在手机画布中全选复制') }
                    }}>📋 复制 HTML</button>
                  )}
                </div>
                {layoutMeta && (
                  <div style={{ marginTop: 10, fontSize: 12, opacity: 0.7, lineHeight: 1.6 }}>
                    {typeof layoutMeta.title === 'string' && layoutMeta.title ? `标题：${layoutMeta.title} · ` : ''}
                    {typeof layoutMeta.word_count === 'number' ? `${layoutMeta.word_count} 字` : ''}
                    {typeof layoutMeta.read_time === 'string' ? ` · 约 ${layoutMeta.read_time}` : ''}
                  </div>
                )}
              </div>
              {msg && <div style={{ marginTop: 8, fontSize: 13, opacity: 0.8 }}>{msg}</div>}
            </>
          )}

          {!streaming && isCollectStep && (
            <>
              <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 8 }}>资料可多来源：🔍 联网搜 · 📁 导入本地目录（txt/md/pdf/docx/pptx）· 🌐 抓取网址 · 直接粘贴素材 · 留空让撰稿基于主题发挥</div>
              <textarea value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="联网搜的资料会填到这里，你也可以直接粘贴自己的素材/笔记/链接……" style={{ ...inputStyle, width: '100%', minHeight: 220, resize: 'vertical', lineHeight: 1.7, fontSize: 14, background: 'var(--bg-card)' }} />
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10, alignItems: 'center' }}>
                <input value={localDir} onChange={(e) => setLocalDir(e.target.value)} placeholder="本地素材目录（放文章 txt/md/pdf/docx）" style={{ ...inputStyle, flex: 1, minWidth: 180, fontSize: 13 }} />
                <button type="button" style={ghostBtn} onClick={browseDir}>📁 浏览</button>
                <button type="button" style={ghostBtn} disabled={busy || !localDir.trim()} onClick={importLocalDir}>导入素材</button>
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10, alignItems: 'center' }}>
                <textarea value={urlsText} onChange={(e) => setUrlsText(e.target.value)} placeholder="粘贴网址，每行一个（支持微信公众号、GitHub 仓库等）" style={{ ...inputStyle, flex: 1, minWidth: 180, minHeight: 56, resize: 'vertical', fontSize: 13, lineHeight: 1.5 }} />
                <button type="button" style={ghostBtn} disabled={busy || !urlsText.trim()} onClick={importUrls}>{busy ? '抓取中…' : '🌐 抓取'}</button>
              </div>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 10, alignItems: 'center' }}>
                <button type="button" style={goBtn} disabled={busy} onClick={() => runStep(sel)}>{busy ? '搜索中…' : '🔍 联网搜资料'}</button>
                <button type="button" style={ghostBtn} disabled={busy} onClick={() => saveEdit(sel)}>💾 保存资料</button>
                {!isFinal && <button type="button" style={ghostBtn} onClick={() => { setSel(Math.min(sel + 1, proj.nodes.length - 1)); setMsg('') }}>下一步 →</button>}
              </div>
              {msg && <div style={{ marginTop: 8, fontSize: 13, opacity: 0.8 }}>{msg}</div>}
            </>
          )}

          {!streaming && isHuman && (
            <div style={card}>
              <div style={{ opacity: 0.7, fontSize: 13, marginBottom: 10 }}>这是审核占位步——本工作台每步都可审，直接跳过即可。</div>
              <button type="button" style={ghostBtn} disabled={busy} onClick={() => runStep(sel)}>跳过这步 →</button>
            </div>
          )}

          {!streaming && isDone && isEditable && (
            <>
              <div style={{ display: 'flex', gap: 6, position: 'sticky', top: 40, zIndex: 4, background: 'var(--bg-color)', paddingBottom: 8, marginBottom: 8 }}>
                <button type="button" onClick={() => setPreview(false)} style={{ ...ghostBtn, fontSize: 12, ...(preview ? {} : { background: 'rgba(196,167,125,0.14)', borderColor: 'rgba(196,167,125,0.8)' }) }}>✏️ 编辑</button>
                <button type="button" onClick={() => setPreview(true)} style={{ ...ghostBtn, fontSize: 12, ...(preview ? { background: 'rgba(196,167,125,0.14)', borderColor: 'rgba(196,167,125,0.8)' } : {}) }}>👁 预览</button>
              </div>
              {preview ? (
                <div className="studio-md-preview" style={{ ...inputStyle, width: '100%', minHeight: 280, maxHeight: 520, overflow: 'auto', lineHeight: 1.7, fontSize: 14, background: 'var(--bg-card)' }} dangerouslySetInnerHTML={{ __html: renderChatMarkdown(draft) }} />
              ) : (
                <textarea value={draft} onChange={(e) => setDraft(e.target.value)} style={{ ...inputStyle, width: '100%', minHeight: 280, resize: 'vertical', lineHeight: 1.7, fontSize: 14, background: 'var(--bg-card)' }} />
              )}
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 10, alignItems: 'center' }}>
                <button type="button" style={ghostBtn} disabled={busy} onClick={() => saveEdit(sel)}>💾 保存修改</button>
                <button type="button" style={ghostBtn} disabled={busy} onClick={() => runStep(sel)}>↻ 换一版</button>
                {!isFinal && <button type="button" style={goBtn} onClick={() => { setSel(Math.min(sel + 1, proj.nodes.length - 1)); setMsg('') }}>下一步 →</button>}
              </div>
              {imgLib.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 6 }}>本地图片素材（鼠标移上去：点「插入」入正文 · 点图放大 · 右上角 × 删除）：</div>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    {imgLib.map((img) => (
                      <div key={img.path} onMouseEnter={() => setHoverImg(img.path)} onMouseLeave={() => setHoverImg((h) => (h === img.path ? null : h))} style={{ position: 'relative', width: 64, height: 64 }}>
                        <img src={studioImgUrl(img.path)} title={img.name} onClick={() => { setPreviewImg(img); setImgScale(1); setImgPos({ x: 0, y: 0 }) }} style={{ width: 64, height: 64, objectFit: 'cover', borderRadius: 6, cursor: 'pointer', border: '1px solid rgba(127,127,127,0.3)', display: 'block' }} />
                        <div onClick={(e) => { e.stopPropagation(); insertImage(img) }} title="插入到正文" style={{ position: 'absolute', left: 0, right: 0, bottom: 0, height: 19, background: 'rgba(196,167,125,0.3)', color: '#fff', fontSize: 11, fontWeight: 600, lineHeight: '19px', textAlign: 'center', cursor: 'pointer', borderBottomLeftRadius: 6, borderBottomRightRadius: 6, textShadow: '0 1px 2px rgba(0,0,0,0.8)', opacity: hoverImg === img.path ? 1 : 0, pointerEvents: hoverImg === img.path ? 'auto' : 'none', transition: 'opacity 0.15s' }}>插入</div>
                        <button type="button" title={`删除「${img.name}」`} onClick={(e) => { e.stopPropagation(); removeImage(img) }} style={{ position: 'absolute', top: -6, right: -6, width: 18, height: 18, padding: 0, borderRadius: '50%', border: '1px solid rgba(255,255,255,0.9)', background: 'rgba(217,83,79,0.95)', color: '#fff', fontSize: 12, lineHeight: '15px', textAlign: 'center', cursor: 'pointer', boxShadow: '0 1px 4px rgba(0,0,0,0.45)', opacity: hoverImg === img.path ? 1 : 0, pointerEvents: hoverImg === img.path ? 'auto' : 'none', transition: 'opacity 0.15s' }}>×</button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              <div style={{ ...card, marginTop: 12 }}>
                <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 6 }}>不满意？给一句意见让它按你的改：</div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <input value={feedback} onChange={(e) => setFeedback(e.target.value)} placeholder="如：开头钩子再强一点、多举一个例子" style={{ ...inputStyle, flex: 1, minWidth: 220 }} />
                  <button type="button" style={goBtn} disabled={busy || !feedback.trim()} onClick={() => runStep(sel, feedback.trim())}>按意见重写</button>
                </div>
              </div>
              {isImageStep && (
                <div style={{ ...card, marginTop: 12 }}>
                  <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 8 }}>用上面的提示词生成封面图（选一个生图模型；若报 key 失效就换一个）：</div>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                    <select value={p.imgPick} onChange={(e) => { p.setImgPick(e.target.value); try { localStorage.setItem(COVER_MODEL_KEY, e.target.value) } catch { /* ignore */ } }} style={{ ...inputStyle, background: 'var(--bg-card)' }}>
                      {p.imgModels.length === 0 && <option value="">（未配生图模型）</option>}
                      {p.imgModels.map((m) => <option key={`${m.model}|${m.provider}`} value={`${m.model}|${m.provider}`}>{m.model} · {m.provider_name}</option>)}
                    </select>
                    <button type="button" style={goBtn} disabled={coverBusy} onClick={genCover}>{coverBusy ? '生成中…' : '🎨 生成封面图'}</button>
                  </div>
                  {coverMsg && <div style={{ marginTop: 8, fontSize: 13, opacity: 0.8 }}>{coverMsg}</div>}
                  {coverUrl && <div style={{ marginTop: 10 }}><img src={coverUrl} alt="封面" style={{ maxWidth: 360, borderRadius: 8, border: '1px solid rgba(127,127,127,0.2)' }} /></div>}
                </div>
              )}
            </>
          )}

          {!streaming && isDone && !isEditable && !isHuman && !isCollectStep && !isLayoutStep && (
            <>
              <div style={{ ...card, whiteSpace: 'pre-wrap', fontSize: 13, lineHeight: 1.6, opacity: 0.85 }}>
                {(() => {
                  const v = proj.state[node.writes]
                  if (v && typeof v === 'object' && 'material' in (v as Record<string, unknown>)) { return String((v as Record<string, unknown>).material || '') }
                  return typeof v === 'string' ? v : JSON.stringify(v, null, 2)
                })()}
              </div>
              <button type="button" style={ghostBtn} disabled={busy} onClick={() => runStep(sel)}>{busy ? '处理中…' : '↻ 重新生成这步'}</button>
            </>
          )}

          {!streaming && !isCollectStep && !isLayoutStep && msg && <div style={{ marginTop: 10, fontSize: 13, opacity: 0.8 }}>{msg}</div>}

          {isFinal && isDone && (
            <div style={{ ...card, marginTop: 14, borderColor: 'rgba(196,167,125,0.6)' }}>
              <div style={{ fontWeight: 600, marginBottom: 8 }}>📤 分发到平台账号</div>
              <div style={{ fontSize: 12, opacity: 0.65, marginBottom: 8, lineHeight: 1.5 }}>
                {layoutHtml ? '将使用本步排版 HTML 推送（不再二次转 MD）' : '尚未生成排版 HTML，将回退为定稿 Markdown 由后端转换'}
              </div>
              {platforms.every((pl) => pl.accounts.length === 0) && <div style={{ fontSize: 13, opacity: 0.5 }}>还没配账号 — 去「多平台发布」tab 添加</div>}
              {platforms.map((pl) => pl.accounts.map((a) => {
                const r = dispatchRes[a.id]; const isWx = pl.key === 'wechat_mp'
                return (
                  <div key={a.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0', borderTop: '1px solid rgba(127,127,127,0.1)' }}>
                    <span>{pl.emoji || '🌐'}</span><span style={{ fontWeight: 500 }}>{a.name}</span><span style={{ fontSize: 11, opacity: 0.5 }}>{pl.name}</span>
                    <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
                      {r && <span style={{ fontSize: 12, display: 'inline-flex', alignItems: 'center', color: r.status === 'ok' ? '#3a9d5d' : r.status === 'err' ? '#d66' : 'inherit' }}>{r.status === 'loading' ? <Loader2 size={13} className="spin" /> : (r.status === 'ok' ? '✓ ' : '✗ ') + r.msg}</span>}
                      {isWx ? <button type="button" style={{ ...goBtn, padding: '5px 12px', fontSize: 13, background: 'linear-gradient(135deg,#07c160,#05974c)' }} onClick={() => dispatchWechat(a, title)}>推草稿箱</button> : <button type="button" style={{ ...ghostBtn, padding: '5px 12px', fontSize: 13 }} onClick={() => dispatchCopy(pl, a, title)}>复制+打开后台</button>}
                    </div>
                  </div>
                )
              }))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
