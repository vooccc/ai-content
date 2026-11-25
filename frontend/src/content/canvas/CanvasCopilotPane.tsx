import { useEffect, useRef, useState } from 'react'
import {
  AlertTriangle, ArrowUp, BookMarked, Brain, Check, ChevronDown, ChevronRight,
  FileText, Globe, ImagePlus, Loader2, Paperclip, Plus, Send,
  ShieldCheck, Sparkles, Square, StickyNote, Trash2, Undo2, Wand2, X,
} from 'lucide-react'
import { API_BASE } from '../../api/base'
import { renderChatMarkdown } from '../../lib/markdown'
import {
  type ImgModel, type MPlatform, type MPAccount, type StyleItem, type TxtModel,
  COVER_MODEL_KEY, ghostBtn, goBtn, groupByProvider, inputStyle,
} from '../studio/StudioShell'
import {
  type CanvasMessage, type CanvasProject, type CanvasSource,
  type ComplianceFinding, type SelectionLock,
} from './types'

interface CanvasCopilotPaneProps {
  proj: CanvasProject
  title: string
  content: string
  themePick: string
  txtModels: TxtModel[]
  imgModels: ImgModel[]
  styleList: StyleItem[]
  modelPick: string
  stylePick: string
  useMyStyle: boolean
  aiStreaming: boolean
  selectionLock: SelectionLock | null
  quickSeedPrompt: string
  pushModalOpen: boolean
  setPushModalOpen: (v: boolean) => void
  onConsumeSeedPrompt: () => void
  onClearSelectionLock: () => void
  onChangeModel: (m: string) => void
  onChangeStyle: (s: string) => void
  onToggleMyStyle: (v: boolean) => void
  onInsertImageToEditor: (url: string, alt: string) => void
  onRestoreVersion: (vid: string) => void
  onStreamStart: () => void
  onStreamArticleDelta: (delta: string, isFirst: boolean) => void
  onStreamArticleFull: (full: string) => void
  onStreamFinish: (updatedProj: CanvasProject) => void
  onStreamError: () => void
  onProjectUpdated: (updatedProj: CanvasProject) => void
  renderedHtml: string
}

interface ImageSuggestion {
  cover?: { title?: string; prompt?: string }
  inlines?: { anchor?: string; caption?: string; prompt?: string }[]
}

export default function CanvasCopilotPane({
  proj,
  title,
  content,
  themePick,
  txtModels,
  imgModels,
  styleList,
  modelPick,
  stylePick,
  useMyStyle,
  aiStreaming,
  selectionLock,
  quickSeedPrompt,
  pushModalOpen,
  setPushModalOpen,
  onConsumeSeedPrompt,
  onClearSelectionLock,
  onChangeModel,
  onChangeStyle,
  onToggleMyStyle,
  onInsertImageToEditor,
  onRestoreVersion,
  onStreamStart,
  onStreamArticleDelta,
  onStreamArticleFull,
  onStreamFinish,
  onStreamError,
  onProjectUpdated,
  renderedHtml,
}: CanvasCopilotPaneProps) {
  const [input, setInput] = useState('')
  const [pendingImgs, setPendingImgs] = useState<CanvasSource[]>([])
  const [chatStream, setChatStream] = useState('')
  const [reasonStream, setReasonStream] = useState('')
  const [reasonOpen, setReasonOpen] = useState(true)
  const [draggingOver, setDraggingOver] = useState(false)
  const [statusMsg, setStatusMsg] = useState('')
  const [inputFocused, setInputFocused] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  // 素材输入面板
  const [urlBoxOpen, setUrlBoxOpen] = useState(false)
  const [urlInput, setUrlInput] = useState('')
  const [noteBoxOpen, setNoteBoxOpen] = useState(false)
  const [noteTitle, setNoteTitle] = useState('')
  const [noteBody, setNoteBody] = useState('')
  const [sourceBusy, setSourceBusy] = useState(false)
  const [inspectSource, setInspectSource] = useState<CanvasSource | null>(null)

  // 工具抽屉状态
  const [checkOpen, setCheckOpen] = useState(false)
  const [checkScore, setCheckScore] = useState<number | null>(null)
  const [checkFindings, setCheckFindings] = useState<ComplianceFinding[]>([])

  const [imgModalOpen, setImgModalOpen] = useState(false)
  const [imgPick, setImgPick] = useState('')
  const [imgBusy, setImgBusy] = useState(false)
  const [suggestBusy, setSuggestBusy] = useState(false)
  const [suggestions, setSuggestions] = useState<ImageSuggestion | null>(null)
  const [customImgPrompt, setCustomImgPrompt] = useState('')
  const [generatedImgs, setGeneratedImgs] = useState<{ url: string; kind: string }[]>([])

  const [myStyleOpen, setMyStyleOpen] = useState(false)
  const [myStyleText, setMyStyleText] = useState('')
  const [myStyleBusy, setMyStyleBusy] = useState(false)

  const [platforms, setPlatforms] = useState<MPlatform[]>([])
  const [dispatchRes, setDispatchRes] = useState<Record<string, { status: string; msg: string }>>({})

  const fileInputRef = useRef<HTMLInputElement>(null)
  const msgEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetch(`${API_BASE}/content/config`).then((r) => r.json()).then((d) => setPlatforms(d.platforms || [])).catch(() => {})
    fetch(`${API_BASE}/canvas/my-style`).then((r) => r.json()).then((d) => { if (d.ok) setMyStyleText(d.content || '') }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!imgModels.length) return
    let remembered = ''
    try { remembered = localStorage.getItem(COVER_MODEL_KEY) || '' } catch { /* ignore */ }
    const valid = imgModels.some((m) => `${m.model}|${m.provider}` === remembered)
    setImgPick(valid ? remembered : `${imgModels[0].model}|${imgModels[0].provider}`)
  }, [imgModels])

  useEffect(() => {
    if (quickSeedPrompt) {
      setInput(quickSeedPrompt)
      onConsumeSeedPrompt()
    }
  }, [quickSeedPrompt, onConsumeSeedPrompt])

  useEffect(() => {
    msgEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [proj.messages?.length, chatStream, reasonStream])

  function imgProxyUrl(localPath?: string): string {
    if (!localPath) return ''
    return `${API_BASE}/canvas/projects/${proj.id}/image?path=${encodeURIComponent(localPath)}`
  }

  async function uploadFiles(files: FileList | File[], attachToMessage = false) {
    const arr = Array.from(files)
    if (!arr.length) return
    setSourceBusy(true)
    setStatusMsg(`正在解析上传（${arr.length} 个文件）…`)
    const addedImages: CanvasSource[] = []
    let lastSources: CanvasSource[] | null = null
    try {
      for (const f of arr) {
        const fd = new FormData()
        fd.append('file', f)
        fd.append('purpose', attachToMessage ? 'chat' : 'source')
        const r = await fetch(`${API_BASE}/canvas/projects/${proj.id}/sources/upload`, { method: 'POST', body: fd })
        const d = await r.json()
        if (d.ok) {
          lastSources = d.sources
          if (d.source?.kind === 'image') addedImages.push(d.source)
        } else {
          setStatusMsg(d.error || `上传 ${f.name} 失败`)
        }
      }
      if (lastSources) {
        onProjectUpdated({ ...proj, sources: lastSources })
        if (attachToMessage && addedImages.length > 0) {
          setPendingImgs((prev) => [...prev, ...addedImages])
        }
        setStatusMsg('素材已加载')
      }
    } catch (e) {
      setStatusMsg(`上传失败：${e}`)
    } finally {
      setSourceBusy(false)
    }
  }

  async function handleAddUrl() {
    const u = urlInput.trim()
    if (!u || sourceBusy) return
    setSourceBusy(true)
    setStatusMsg('正在抓取网页正文…')
    try {
      const r = await fetch(`${API_BASE}/canvas/projects/${proj.id}/sources/url`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: u }),
      })
      const d = await r.json()
      if (d.ok) {
        onProjectUpdated({ ...proj, sources: d.sources })
        setUrlInput('')
        setUrlBoxOpen(false)
        setStatusMsg(`已抓取：${d.source?.title || u}`)
      } else {
        setStatusMsg(d.error || '抓取失败')
      }
    } catch (e) {
      setStatusMsg(`抓取失败：${e}`)
    } finally {
      setSourceBusy(false)
    }
  }

  async function handleAddNote() {
    if (!noteBody.trim() || sourceBusy) return
    setSourceBusy(true)
    try {
      const r = await fetch(`${API_BASE}/canvas/projects/${proj.id}/sources/text`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: noteTitle.trim() || '一手背景/笔记', content: noteBody.trim() }),
      })
      const d = await r.json()
      if (d.ok) {
        onProjectUpdated({ ...proj, sources: d.sources })
        setNoteTitle('')
        setNoteBody('')
        setNoteBoxOpen(false)
        setStatusMsg('已加入素材库')
      } else {
        setStatusMsg(d.error || '添加失败')
      }
    } catch (e) {
      setStatusMsg(`添加失败：${e}`)
    } finally {
      setSourceBusy(false)
    }
  }

  async function handleRemoveSource(sid: string) {
    try {
      const r = await fetch(`${API_BASE}/canvas/projects/${proj.id}/sources/${sid}`, { method: 'DELETE' })
      const d = await r.json()
      if (d.ok) {
        onProjectUpdated({ ...proj, sources: d.sources })
        setPendingImgs((prev) => prev.filter((x) => x.id !== sid))
      }
    } catch {
      /* ignore */
    }
  }

  function stopChat() {
    abortRef.current?.abort()
  }

  async function sendChat(overrideMsg?: string, forceNoSelection = false) {
    const rawText = (overrideMsg !== undefined ? overrideMsg : input).trim()
    if ((!rawText && pendingImgs.length === 0) || aiStreaming) return
    const text = rawText || '请结合我发给你的图片继续处理。'
    const locked = forceNoSelection ? null : selectionLock
    const imgsToSend = pendingImgs.map((x) => x.path || '').filter(Boolean)

    if (overrideMsg === undefined) setInput('')
    setPendingImgs([])
    if (locked) onClearSelectionLock()
    setStatusMsg('')
    setChatStream('')
    setReasonStream('')
    setReasonOpen(true)
    onStreamStart()

    const ac = new AbortController()
    abortRef.current = ac

    const optimisticUser: CanvasMessage = {
      id: `tmp_${Date.now()}`,
      role: 'user',
      text,
      selection: locked?.text,
      images: pendingImgs.map((x) => x.title),
      ts: Date.now() / 1000,
    }
    onProjectUpdated({ ...proj, messages: [...(proj.messages || []), optimisticUser] })

    let articleStarted = false
    let accChat = ''
    try {
      const res = await fetch(`${API_BASE}/canvas/projects/${proj.id}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: ac.signal,
        body: JSON.stringify({
          message: text,
          model: modelPick,
          style: stylePick,
          use_my_style: useMyStyle,
          selection: locked?.text || '',
          selection_start: locked?.start ?? -1,
          selection_end: locked?.end ?? -1,
          image_paths: imgsToSend,
          current_title: title,
          current_content: content,
        }),
      })
      if (!res.body) throw new Error('无响应流')
      const reader = res.body.getReader()
      const dec = new TextDecoder()
      let buf = ''
      let doneProj: CanvasProject | null = null

      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        const parts = buf.split('\n\n')
        buf = parts.pop() || ''
        for (const p of parts) {
          const line = p.trim()
          if (!line.startsWith('data:')) continue
          try {
            const ev = JSON.parse(line.slice(5).trim())
            if (ev.type === 'reasoning') {
              setReasonStream((s) => s + (ev.text || ''))
            } else if (ev.type === 'chat_delta') {
              setReasonOpen(false)
              accChat += (ev.text || '')
              setChatStream(accChat)
            } else if (ev.type === 'article_start') {
              articleStarted = true
              onStreamArticleDelta('', true)
            } else if (ev.type === 'article_delta') {
              const first = !articleStarted
              articleStarted = true
              onStreamArticleDelta(ev.text || '', first)
            } else if (ev.type === 'article_full') {
              onStreamArticleFull(ev.content || '')
            } else if (ev.type === 'error') {
              setStatusMsg(ev.msg || '调用出错')
            } else if (ev.type === 'done' && ev.project) {
              doneProj = ev.project
            }
          } catch {
            /* ignore malformed line */
          }
        }
      }

      abortRef.current = null
      setChatStream('')
      setReasonStream('')
      if (doneProj) {
        onStreamFinish(doneProj)
      } else {
        onStreamError()
      }
    } catch (e) {
      abortRef.current = null
      setChatStream('')
      setReasonStream('')
      const isAbort = e instanceof Error && e.name === 'AbortError'
      if (isAbort) {
        if (accChat.trim()) {
          const stoppedMsg: CanvasMessage = {
            id: `stop_${Date.now()}`,
            role: 'assistant',
            text: `${accChat}\n\n（已手动停止生成）`,
            ts: Date.now() / 1000,
          }
          onProjectUpdated({
            ...proj,
            messages: [...(proj.messages || []), optimisticUser, stoppedMsg],
          })
        }
        setStatusMsg('已停止生成')
      } else {
        setStatusMsg(`发送失败：${e}`)
      }
      onStreamError()
    }
  }

  async function runComplianceCheck() {
    if (!content.trim()) { setStatusMsg('画布正文为空'); return }
    try {
      const d = await (await fetch(`${API_BASE}/canvas/projects/${proj.id}/check`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      })).json()
      if (d.ok) {
        setCheckScore(d.score)
        setCheckFindings(d.findings || [])
        setCheckOpen(true)
      }
    } catch (e) {
      setStatusMsg(`检查失败：${e}`)
    }
  }

  async function runSuggestImages() {
    if (!content.trim() || suggestBusy) return
    setSuggestBusy(true)
    try {
      const d = await (await fetch(`${API_BASE}/canvas/projects/${proj.id}/suggest-images`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: modelPick, content }),
      })).json()
      if (d.ok) setSuggestions(d.suggestions || {})
      else setStatusMsg(d.error || '分析配图失败')
    } catch (e) {
      setStatusMsg(`分析失败：${e}`)
    } finally {
      setSuggestBusy(false)
    }
  }

  async function runGenImage(prompt: string, kind: 'cover' | 'inline') {
    if (!prompt.trim() || imgBusy) return
    setImgBusy(true)
    const [model, provider] = (imgPick || '').split('|')
    try {
      const d = await (await fetch(`${API_BASE}/canvas/projects/${proj.id}/gen-image`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: prompt.trim(), kind, model: model || '', provider: provider || '' }),
      })).json()
      if (d.ok && d.url) {
        setGeneratedImgs((prev) => [{ url: d.url, kind }, ...prev])
        const nextProj = { ...proj }
        if (kind === 'cover') nextProj.cover_url = d.url
        onProjectUpdated(nextProj)
        setStatusMsg(kind === 'cover' ? '封面已生成并关联' : '配图已生成，点击可插入正文')
      } else {
        setStatusMsg(d.error || '生图失败')
      }
    } catch (e) {
      setStatusMsg(`生图失败：${e}`)
    } finally {
      setImgBusy(false)
    }
  }

  async function runLearnStyle() {
    if (!content.trim() || myStyleBusy) return
    setMyStyleBusy(true)
    setStatusMsg('正在从改稿差异中提纯你的写作习惯…')
    try {
      const d = await (await fetch(`${API_BASE}/canvas/projects/${proj.id}/learn-style`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: modelPick, content }),
      })).json()
      if (d.ok) {
        setMyStyleText(d.content || '')
        setMyStyleOpen(true)
        setStatusMsg('已更新个人写作习惯档案')
      } else {
        setStatusMsg(d.error || '提炼失败')
      }
    } catch (e) {
      setStatusMsg(`提炼失败：${e}`)
    } finally {
      setMyStyleBusy(false)
    }
  }

  async function saveMyStyleManual() {
    setMyStyleBusy(true)
    try {
      const d = await (await fetch(`${API_BASE}/canvas/my-style`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: myStyleText }),
      })).json()
      if (d.ok) {
        setMyStyleOpen(false)
        setStatusMsg('个人写作习惯已保存')
      }
    } catch (e) {
      setStatusMsg(`保存失败：${e}`)
    } finally {
      setMyStyleBusy(false)
    }
  }

  async function dispatchWechat(acc: MPAccount) {
    if (!acc.appid || !acc.secret) {
      setDispatchRes((m) => ({ ...m, [acc.id]: { status: 'err', msg: '未配凭证，去「账号与设置」补全' } }))
      return
    }
    if (!content.trim()) {
      setDispatchRes((m) => ({ ...m, [acc.id]: { status: 'err', msg: '画布正文为空' } }))
      return
    }
    setDispatchRes((m) => ({ ...m, [acc.id]: { status: 'loading', msg: '' } }))
    try {
      let htmlBody = renderedHtml
      if (!htmlBody) {
        const rd = await (await fetch(`${API_BASE}/canvas/render-wechat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ markdown: content, theme: themePick, include_footer: true }),
        })).json()
        htmlBody = rd.html || content
      }
      const d = await (await fetch(`${API_BASE}/content/dispatch/wechat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: title || '未命名文章',
          content: htmlBody,
          appid: acc.appid,
          secret: acc.secret,
          thumb_media_id: acc.thumb_media_id || '',
          cover_url: proj.cover_url || '',
          project_id: proj.id,
          style: stylePick,
          theme: themePick,
        }),
      })).json()
      const imgHint = d.uploaded_images > 0 ? `，自动传图 ${d.uploaded_images} 张` : ''
      setDispatchRes((m) => ({
        ...m,
        [acc.id]: d.ok
          ? { status: 'ok', msg: `已进草稿箱${imgHint}` }
          : { status: 'err', msg: d.error || '推送失败' },
      }))
      if (d.ok && d.media_id) {
        onProjectUpdated({ ...proj, draft_media_id: d.media_id })
      }
    } catch (e) {
      setDispatchRes((m) => ({ ...m, [acc.id]: { status: 'err', msg: String(e) } }))
    }
  }

  function handlePaste(e: React.ClipboardEvent<HTMLTextAreaElement>) {
    const items = e.clipboardData?.items
    if (!items) return
    const imgFiles: File[] = []
    for (let i = 0; i < items.length; i += 1) {
      const it = items[i]
      if (it.kind === 'file' && it.type.startsWith('image/')) {
        const f = it.getAsFile()
        if (f) imgFiles.push(f)
      }
    }
    if (imgFiles.length > 0) {
      e.preventDefault()
      void uploadFiles(imgFiles, true)
    }
  }

  const sources = proj.sources || []
  const messages = proj.messages || []

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDraggingOver(true) }}
      onDragLeave={() => setDraggingOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDraggingOver(false)
        if (e.dataTransfer?.files?.length) {
          void uploadFiles(e.dataTransfer.files, true)
        }
      }}
      style={{
        width: '100%',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {draggingOver && (
        <div
          style={{
            position: 'absolute',
            inset: 8,
            zIndex: 50,
            borderRadius: 12,
            border: '2px dashed rgba(196,167,125,0.85)',
            background: 'rgba(196,167,125,0.12)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 14,
            fontWeight: 600,
            pointerEvents: 'none',
          }}
        >
          松开即可投喂图片或文档（PDF / DOCX / MD / TXT）
        </div>
      )}

      {/* 顶部配置条：模型 + 风格 + 个人习惯开关 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '8px 12px',
          borderBottom: '1px solid rgba(127,127,127,0.16)',
          flexShrink: 0,
          flexWrap: 'wrap',
        }}
      >
        <select
          value={modelPick}
          onChange={(e) => onChangeModel(e.target.value)}
          title="对话与创作模型"
          style={{ ...inputStyle, padding: '4px 8px', fontSize: 12, maxWidth: 185, background: 'var(--bg-card)' }}
        >
          <option value="">默认模型</option>
          {groupByProvider(txtModels).map(([prov, ms]) => (
            <optgroup key={prov} label={prov}>
              {ms.map((m) => (
                <option key={`${m.model}|${m.provider}`} value={m.model}>{m.name}</option>
              ))}
            </optgroup>
          ))}
        </select>

        <select
          value={stylePick}
          onChange={(e) => onChangeStyle(e.target.value)}
          title="参考写作风格"
          style={{ ...inputStyle, padding: '4px 8px', fontSize: 12, maxWidth: 135, background: 'var(--bg-card)' }}
        >
          <option value="">通用风格</option>
          {styleList.map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>

        <div style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <button
            type="button"
            onClick={() => onToggleMyStyle(!useMyStyle)}
            title="是否在对话中自动注入你沉淀的个人写作习惯"
            style={{
              ...ghostBtn,
              padding: '4px 8px',
              fontSize: 11.5,
              borderColor: useMyStyle ? 'rgba(196,167,125,0.7)' : 'rgba(127,127,127,0.28)',
              background: useMyStyle ? 'rgba(196,167,125,0.14)' : 'transparent',
            }}
          >
            我的习惯{useMyStyle ? '：开' : '：关'}
          </button>
          <button
            type="button"
            onClick={() => setMyStyleOpen(true)}
            title="查看或编辑个人写作习惯档案"
            style={{ ...ghostBtn, padding: '4px 7px', fontSize: 11.5 }}
          >
            查看
          </button>
        </div>
      </div>

      {/* 多模态素材投喂栏 */}
      <div
        style={{
          padding: '8px 12px',
          borderBottom: '1px solid rgba(127,127,127,0.12)',
          background: 'rgba(127,127,127,0.025)',
          flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept="image/*,.txt,.md,.markdown,.pdf,.docx,.pptx"
            style={{ display: 'none' }}
            onChange={(e) => {
              if (e.target.files?.length) void uploadFiles(e.target.files, false)
              e.target.value = ''
            }}
          />
          <button
            type="button"
            disabled={sourceBusy}
            onClick={() => fileInputRef.current?.click()}
            style={{ ...ghostBtn, padding: '3px 9px', fontSize: 11.5, display: 'inline-flex', alignItems: 'center', gap: 4 }}
          >
            <Paperclip size={12} />
            <span>传图/文档</span>
          </button>
          <button
            type="button"
            onClick={() => { setUrlBoxOpen((v) => !v); setNoteBoxOpen(false) }}
            style={{ ...ghostBtn, padding: '3px 9px', fontSize: 11.5, display: 'inline-flex', alignItems: 'center', gap: 4 }}
          >
            <Globe size={12} />
            <span>抓网址</span>
          </button>
          <button
            type="button"
            onClick={() => { setNoteBoxOpen((v) => !v); setUrlBoxOpen(false) }}
            style={{ ...ghostBtn, padding: '3px 9px', fontSize: 11.5, display: 'inline-flex', alignItems: 'center', gap: 4 }}
          >
            <StickyNote size={12} />
            <span>加笔记</span>
          </button>
          {sourceBusy && <Loader2 size={13} className="spin" style={{ opacity: 0.7 }} />}
          {sources.length > 0 && (
            <span style={{ marginLeft: 'auto', fontSize: 11, opacity: 0.55, fontVariantNumeric: 'tabular-nums' }}>
              已挂载 {sources.length} 份素材
            </span>
          )}
        </div>

        {urlBoxOpen && (
          <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
            <input
              autoFocus
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') void handleAddUrl() }}
              placeholder="粘贴微信公众号或网页链接，回车抓取正文"
              style={{ ...inputStyle, flex: 1, fontSize: 12, padding: '5px 9px' }}
            />
            <button type="button" disabled={sourceBusy || !urlInput.trim()} onClick={handleAddUrl} style={{ ...goBtn, padding: '5px 11px', fontSize: 12 }}>
              抓取
            </button>
          </div>
        )}

        {noteBoxOpen && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
            <input
              value={noteTitle}
              onChange={(e) => setNoteTitle(e.target.value)}
              placeholder="标题（如：我的实测结论 / 柳如烟近期改动）"
              style={{ ...inputStyle, fontSize: 12, padding: '5px 9px' }}
            />
            <textarea
              value={noteBody}
              onChange={(e) => setNoteBody(e.target.value)}
              placeholder="写下你的真实经历、观点、数据或背景事实…"
              style={{ ...inputStyle, fontSize: 12, minHeight: 68, resize: 'vertical', padding: '6px 9px', lineHeight: 1.5 }}
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 6 }}>
              <button type="button" onClick={() => setNoteBoxOpen(false)} style={{ ...ghostBtn, padding: '3px 9px', fontSize: 11.5 }}>取消</button>
              <button type="button" disabled={sourceBusy || !noteBody.trim()} onClick={handleAddNote} style={{ ...goBtn, padding: '3px 11px', fontSize: 11.5 }}>保存素材</button>
            </div>
          </div>
        )}

        {sources.length > 0 && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8, maxHeight: 92, overflowY: 'auto' }}>
            {sources.map((s) => (
              <div
                key={s.id}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 5,
                  padding: '3px 7px',
                  borderRadius: 7,
                  fontSize: 11.5,
                  border: '1px solid rgba(127,127,127,0.22)',
                  background: 'rgba(127,127,127,0.06)',
                  maxWidth: 210,
                }}
              >
                {s.kind === 'image' && s.path ? (
                  <img
                    src={imgProxyUrl(s.path)}
                    alt={s.title}
                    style={{ width: 18, height: 18, borderRadius: 3, objectFit: 'cover', flexShrink: 0 }}
                  />
                ) : s.kind === 'url' ? (
                  <Globe size={12} style={{ opacity: 0.7, flexShrink: 0 }} />
                ) : (
                  <FileText size={12} style={{ opacity: 0.7, flexShrink: 0 }} />
                )}
                <span
                  onClick={() => setInspectSource(s)}
                  title={s.title}
                  style={{ cursor: 'pointer', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                >
                  {s.title}
                </span>
                {s.kind === 'image' && s.path && (
                  <button
                    type="button"
                    title="插入到左侧正文"
                    onClick={() => onInsertImageToEditor(imgProxyUrl(s.path), s.title)}
                    style={{ border: 'none', background: 'transparent', color: '#c4a77d', cursor: 'pointer', padding: '0 2px', fontSize: 11, fontWeight: 600 }}
                  >
                    插图
                  </button>
                )}
                <button
                  type="button"
                  title="移除素材"
                  onClick={() => handleRemoveSource(s.id)}
                  style={{ border: 'none', background: 'transparent', color: 'inherit', opacity: 0.55, cursor: 'pointer', padding: 0, display: 'inline-flex' }}
                >
                  <X size={11} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 对话消息流 */}
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 12 }}>
        {messages.length === 0 && !aiStreaming && (
          <div style={{ margin: 'auto 0', padding: '16px 8px', display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ fontSize: 13, fontWeight: 600, opacity: 0.85, display: 'flex', alignItems: 'center', gap: 6 }}>
              <Sparkles size={14} color="#c4a77d" />
              <span>直接告诉我你想怎么写</span>
            </div>
            <div style={{ fontSize: 12, opacity: 0.62, lineHeight: 1.65 }}>
              拖进截图/文档或抓个链接后，像聊天一样交代你的角度和事实。我写完会直接同步到左侧画布，不合适随时一句指令微调。
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 6 }}>
              {[
                '结合我给的素材和想法，先起草一版完整公众号文章放到左侧',
                '帮我起 5 个更有点击欲的标题，先讨论再动正文',
                '检查左侧稿子哪里像 AI 写的，直接帮我改出活人感',
              ].map((hint) => (
                <button
                  key={hint}
                  type="button"
                  onClick={() => void sendChat(hint, true)}
                  style={{
                    ...ghostBtn,
                    textAlign: 'left',
                    fontSize: 12,
                    padding: '7px 10px',
                    borderColor: 'rgba(127,127,127,0.2)',
                    opacity: 0.85,
                  }}
                >
                  {hint}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m) => {
          const isUser = m.role === 'user'
          return (
            <div
              key={m.id}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: isUser ? 'flex-end' : 'flex-start',
                gap: 4,
              }}
            >
              <div
                style={{
                  maxWidth: '92%',
                  padding: '9px 12px',
                  borderRadius: 10,
                  fontSize: 13,
                  lineHeight: 1.65,
                  background: isUser ? 'rgba(196,167,125,0.16)' : 'rgba(127,127,127,0.08)',
                  border: isUser ? '1px solid rgba(196,167,125,0.35)' : '1px solid rgba(127,127,127,0.16)',
                }}
              >
                {m.selection && (
                  <div style={{ fontSize: 11.5, opacity: 0.7, borderLeft: '2px solid #c4a77d', paddingLeft: 7, marginBottom: 6 }}>
                    选区：{m.selection}
                  </div>
                )}
                {m.images && m.images.length > 0 && (
                  <div style={{ fontSize: 11, opacity: 0.7, marginBottom: 4 }}>
                    附带图片：{m.images.join('、')}
                  </div>
                )}
                {isUser ? (
                  <div style={{ whiteSpace: 'pre-wrap' }}>{m.text}</div>
                ) : (
                  <div className="studio-md-preview" dangerouslySetInnerHTML={{ __html: renderChatMarkdown(m.text) }} />
                )}
                {m.applied_version && (
                  <div
                    style={{
                      marginTop: 8,
                      paddingTop: 6,
                      borderTop: '1px solid rgba(127,127,127,0.14)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: 8,
                      fontSize: 11.5,
                      color: '#c4a77d',
                    }}
                  >
                    <span>已同步到左侧画布（{m.applied_version.split('_')[0]}）</span>
                    <button
                      type="button"
                      disabled={aiStreaming}
                      onClick={() => onRestoreVersion(m.applied_version!)}
                      style={{
                        border: 'none',
                        background: 'transparent',
                        color: 'inherit',
                        cursor: 'pointer',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 3,
                        fontSize: 11.5,
                        opacity: 0.85,
                      }}
                    >
                      <Undo2 size={11} />
                      <span>还原至此版</span>
                    </button>
                  </div>
                )}
              </div>
            </div>
          )
        })}

        {aiStreaming && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'flex-start' }}>
            {reasonStream && (
              <div
                style={{
                  maxWidth: '92%',
                  borderRadius: 9,
                  border: '1px solid rgba(196,167,125,0.22)',
                  background: 'rgba(196,167,125,0.06)',
                  overflow: 'hidden',
                }}
              >
                <button
                  type="button"
                  onClick={() => setReasonOpen((v) => !v)}
                  style={{
                    width: '100%',
                    border: 'none',
                    background: 'transparent',
                    color: '#c4a77d',
                    padding: '6px 10px',
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 5,
                  }}
                >
                  {reasonOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                  <Brain size={13} />
                  <span>思考中</span>
                </button>
                {reasonOpen && (
                  <div style={{ padding: '0 10px 8px', fontSize: 11.5, lineHeight: 1.6, opacity: 0.72, whiteSpace: 'pre-wrap' }}>
                    {reasonStream}
                  </div>
                )}
              </div>
            )}
            <div
              style={{
                maxWidth: '92%',
                padding: '9px 12px',
                borderRadius: 10,
                fontSize: 13,
                lineHeight: 1.65,
                background: 'rgba(127,127,127,0.08)',
                border: '1px solid rgba(127,127,127,0.16)',
              }}
            >
              {chatStream ? (
                <div className="studio-md-preview" dangerouslySetInnerHTML={{ __html: renderChatMarkdown(chatStream) }} />
              ) : (
                <span style={{ opacity: 0.65, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  <Loader2 size={13} className="spin" />
                  <span>正在组织思路与撰写…</span>
                </span>
              )}
            </div>
          </div>
        )}
        <div ref={msgEndRef} />
      </div>

      {/* 快捷技能操作条（替代旧8步流水线） */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 5,
          padding: '7px 12px',
          borderTop: '1px solid rgba(127,127,127,0.14)',
          background: 'rgba(127,127,127,0.025)',
          flexShrink: 0,
          flexWrap: 'wrap',
        }}
      >
        <button
          type="button"
          disabled={aiStreaming}
          onClick={runComplianceCheck}
          style={{ ...ghostBtn, padding: '4px 8px', fontSize: 11.5, display: 'inline-flex', alignItems: 'center', gap: 4 }}
        >
          <ShieldCheck size={12.5} />
          <span>违禁词</span>
        </button>
        <button
          type="button"
          disabled={aiStreaming || !content.trim()}
          onClick={() => void sendChat('请在不改变任何事实与细节的前提下，按当前选定的风格与我的个人写作习惯，全面润色左侧画布（去 AI 味、优化句子节奏与口语转场），并将润色后的完整正文同步到左侧画布。', true)}
          style={{ ...ghostBtn, padding: '4px 8px', fontSize: 11.5, display: 'inline-flex', alignItems: 'center', gap: 4 }}
        >
          <Wand2 size={12.5} />
          <span>风格润色</span>
        </button>
        <button
          type="button"
          onClick={() => setImgModalOpen(true)}
          style={{ ...ghostBtn, padding: '4px 8px', fontSize: 11.5, display: 'inline-flex', alignItems: 'center', gap: 4 }}
        >
          <ImagePlus size={12.5} />
          <span>配图</span>
        </button>
        <button
          type="button"
          disabled={myStyleBusy || !content.trim()}
          onClick={runLearnStyle}
          title="对比初稿与当前定稿，沉淀你的写作习惯"
          style={{ ...ghostBtn, padding: '4px 8px', fontSize: 11.5, display: 'inline-flex', alignItems: 'center', gap: 4 }}
        >
          <BookMarked size={12.5} />
          <span>{myStyleBusy ? '提纯中…' : '沉淀习惯'}</span>
        </button>
        <button
          type="button"
          disabled={!content.trim()}
          onClick={() => setPushModalOpen(true)}
          style={{
            marginLeft: 'auto',
            padding: '4px 10px',
            borderRadius: 7,
            border: 'none',
            cursor: 'pointer',
            fontSize: 11.5,
            fontWeight: 600,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            background: 'linear-gradient(135deg,#07c160,#05974c)',
            color: '#fff',
            opacity: content.trim() ? 1 : 0.45,
          }}
        >
          <Send size={12} />
          <span>推草稿箱</span>
        </button>
      </div>

      {/* 输入区域（内嵌圆形发送 / 停止按钮，贴合现代对话胶囊风格） */}
      <div style={{ padding: '6px 12px 12px', flexShrink: 0 }}>
        {statusMsg && (
          <div style={{ fontSize: 11.5, opacity: 0.78, marginBottom: 6, paddingLeft: 4, color: '#c4a77d' }}>{statusMsg}</div>
        )}

        <div
          style={{
            borderRadius: 20,
            border: `1px solid ${inputFocused ? 'rgba(196,167,125,0.65)' : 'rgba(127,127,127,0.22)'}`,
            background: 'var(--bg-card)',
            boxShadow: inputFocused ? '0 6px 22px rgba(0,0,0,0.14)' : '0 2px 12px rgba(0,0,0,0.06)',
            transition: 'border-color 0.15s ease, box-shadow 0.15s ease',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
          }}
        >
          {selectionLock && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                margin: '10px 12px 0',
                padding: '4px 9px',
                borderRadius: 8,
                background: 'rgba(196,167,125,0.12)',
                border: '1px solid rgba(196,167,125,0.32)',
                fontSize: 11.5,
              }}
            >
              <span style={{ opacity: 0.7, flexShrink: 0 }}>锁定选区：</span>
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {selectionLock.text}
              </span>
              <button
                type="button"
                onClick={onClearSelectionLock}
                style={{ border: 'none', background: 'transparent', color: 'inherit', cursor: 'pointer', padding: 0, display: 'inline-flex' }}
              >
                <X size={12} />
              </button>
            </div>
          )}

          {pendingImgs.length > 0 && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', padding: '10px 14px 0' }}>
              {pendingImgs.map((im) => (
                <div key={im.id} style={{ position: 'relative', width: 46, height: 46 }}>
                  <img
                    src={imgProxyUrl(im.path)}
                    alt={im.title}
                    style={{ width: 46, height: 46, objectFit: 'cover', borderRadius: 8, border: '1px solid rgba(127,127,127,0.28)' }}
                  />
                  <button
                    type="button"
                    onClick={() => setPendingImgs((prev) => prev.filter((x) => x.id !== im.id))}
                    style={{
                      position: 'absolute',
                      top: -5,
                      right: -5,
                      width: 16,
                      height: 16,
                      borderRadius: '50%',
                      border: 'none',
                      background: '#d9534f',
                      color: '#fff',
                      fontSize: 10,
                      cursor: 'pointer',
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      padding: 0,
                    }}
                  >
                    <X size={10} />
                  </button>
                </div>
              ))}
            </div>
          )}

          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onFocus={() => setInputFocused(true)}
            onBlur={() => setInputFocused(false)}
            onPaste={handlePaste}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                if (!aiStreaming) void sendChat()
              }
            }}
            placeholder="给 Copilot 提意见、投喂需求，或直接 Ctrl+V 粘贴截图…"
            style={{
              width: '100%',
              boxSizing: 'border-box',
              border: 'none',
              outline: 'none',
              background: 'transparent',
              color: 'inherit',
              fontFamily: 'inherit',
              padding: '12px 16px 4px',
              minHeight: 46,
              maxHeight: 150,
              resize: 'none',
              fontSize: 13.5,
              lineHeight: 1.55,
            }}
          />

          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '4px 10px 9px 12px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <button
                type="button"
                disabled={sourceBusy}
                onClick={() => fileInputRef.current?.click()}
                title="上传图片或文档"
                style={{
                  width: 30,
                  height: 30,
                  borderRadius: '50%',
                  border: 'none',
                  background: 'transparent',
                  color: 'inherit',
                  opacity: 0.72,
                  cursor: 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  padding: 0,
                }}
              >
                <Plus size={17} strokeWidth={1.9} />
              </button>
              <span style={{ fontSize: 11, opacity: 0.42, userSelect: 'none' }}>
                Enter 发送 · Shift+Enter 换行
              </span>
            </div>

            {(() => {
              const canSend = !!(input.trim() || pendingImgs.length > 0)
              if (aiStreaming) {
                return (
                  <button
                    type="button"
                    onClick={stopChat}
                    title="停止生成"
                    aria-label="停止生成"
                    style={{
                      width: 34,
                      height: 34,
                      borderRadius: '50%',
                      border: 'none',
                      background: 'rgba(127,127,127,0.18)',
                      color: 'inherit',
                      cursor: 'pointer',
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      padding: 0,
                      flexShrink: 0,
                      transition: 'background 0.15s ease',
                    }}
                  >
                    <Square size={12} fill="currentColor" strokeWidth={0} />
                  </button>
                )
              }
              return (
                <button
                  type="button"
                  disabled={!canSend}
                  onClick={() => void sendChat()}
                  title="发送"
                  aria-label="发送"
                  style={{
                    width: 34,
                    height: 34,
                    borderRadius: '50%',
                    border: 'none',
                    background: canSend ? 'rgba(155, 194, 249, 0.35)' : 'rgba(127,127,127,0.12)',
                    color: 'inherit',
                    opacity: canSend ? 1 : 0.4,
                    cursor: canSend ? 'pointer' : 'default',
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    padding: 0,
                    flexShrink: 0,
                    transition: 'background 0.15s ease, opacity 0.15s ease',
                  }}
                >
                  <ArrowUp size={16} strokeWidth={2.1} />
                </button>
              )
            })()}
          </div>
        </div>
      </div>

      {/* 弹窗 1：违禁词与 AI 味检查 */}
      {checkOpen && (
        <div onClick={() => setCheckOpen(false)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
          <div onClick={(e) => e.stopPropagation()} style={{ background: 'var(--bg-card, #1c2128)', border: '1px solid rgba(127,127,127,0.3)', borderRadius: 12, padding: 18, width: 'min(580px, 94vw)', maxHeight: '82vh', display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ fontSize: 15, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 7 }}>
                <ShieldCheck size={16} color="#c4a77d" />
                <span>违禁词与 AI 味检测</span>
                {checkScore !== null && (
                  <span style={{ fontSize: 12, padding: '2px 8px', borderRadius: 999, background: checkScore >= 85 ? 'rgba(58,157,93,0.18)' : 'rgba(217,83,79,0.18)', color: checkScore >= 85 ? '#3a9d5d' : '#e06c75', fontVariantNumeric: 'tabular-nums' }}>
                    纯净度 {checkScore} 分
                  </span>
                )}
              </div>
              <button type="button" onClick={() => setCheckOpen(false)} style={{ ...ghostBtn, padding: 4 }}><X size={14} /></button>
            </div>
            <div style={{ overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
              {checkFindings.length === 0 ? (
                <div style={{ padding: 24, textAlign: 'center', opacity: 0.75, fontSize: 13 }}>未命中高危违禁词与常见 AI 套话，表现很好。</div>
              ) : (
                checkFindings.map((f, idx) => (
                  <div key={`${f.word}_${idx}`} style={{ padding: '9px 11px', borderRadius: 8, border: '1px solid rgba(127,127,127,0.2)', background: 'rgba(127,127,127,0.05)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, fontWeight: 600 }}>
                      <AlertTriangle size={13} color={f.severity === 'high' ? '#e06c75' : f.severity === 'warn' ? '#e5c07b' : '#c4a77d'} />
                      <span>「{f.word}」</span>
                      <span style={{ fontSize: 11.5, opacity: 0.6, fontWeight: 400 }}>{f.category} · 命中 {f.count} 处</span>
                    </div>
                    {f.hits.slice(0, 2).map((h, hi) => (
                      <div key={hi} style={{ fontSize: 12, opacity: 0.75, marginTop: 4, paddingLeft: 18 }}>
                        第 {h.line} 行：{h.snippet}
                      </div>
                    ))}
                  </div>
                ))
              )}
            </div>
            {checkFindings.length > 0 && (
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                <button type="button" onClick={() => setCheckOpen(false)} style={ghostBtn}>关闭</button>
                <button
                  type="button"
                  onClick={() => {
                    const words = checkFindings.map((f) => f.word).join('、')
                    setCheckOpen(false)
                    void sendChat(`请帮我把左侧文章里命中的这些违禁词/AI套话（${words}）自然替换或删改掉，保持原意不变，把干净后的完整正文同步到左侧画布。`, true)
                  }}
                  style={goBtn}
                >
                  交给 Copilot 一键清理
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 弹窗 2：智能配图 */}
      {imgModalOpen && (
        <div onClick={() => setImgModalOpen(false)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
          <div onClick={(e) => e.stopPropagation()} style={{ background: 'var(--bg-card, #1c2128)', border: '1px solid rgba(127,127,127,0.3)', borderRadius: 12, padding: 18, width: 'min(660px, 95vw)', maxHeight: '86vh', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ fontSize: 15, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 7 }}>
                <ImagePlus size={16} color="#c4a77d" />
                <span>文章封面与智能配图</span>
              </div>
              <button type="button" onClick={() => setImgModalOpen(false)} style={{ ...ghostBtn, padding: 4 }}><X size={14} /></button>
            </div>

            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <select
                value={imgPick}
                onChange={(e) => { setImgPick(e.target.value); try { localStorage.setItem(COVER_MODEL_KEY, e.target.value) } catch { /* ignore */ } }}
                style={{ ...inputStyle, fontSize: 12.5, background: 'var(--bg-card)', flex: 1, minWidth: 180 }}
              >
                {imgModels.length === 0 && <option value="">未配置生图模型</option>}
                {imgModels.map((m) => (
                  <option key={`${m.model}|${m.provider}`} value={`${m.model}|${m.provider}`}>{m.model} · {m.provider_name}</option>
                ))}
              </select>
              <button type="button" disabled={suggestBusy || !content.trim()} onClick={runSuggestImages} style={goBtn}>
                {suggestBusy ? '分析正文中…' : 'AI 推荐封面与插图位置'}
              </button>
            </div>

            {proj.cover_url && (
              <div style={{ padding: 10, borderRadius: 8, border: '1px solid rgba(196,167,125,0.35)', background: 'rgba(196,167,125,0.06)' }}>
                <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>当前文章封面</div>
                <img
                  src={proj.cover_url.startsWith('/') ? `${API_BASE}${proj.cover_url}` : proj.cover_url}
                  alt="封面"
                  style={{ maxHeight: 160, borderRadius: 6, display: 'block' }}
                />
              </div>
            )}

            {suggestions?.cover?.prompt && (
              <div style={{ padding: 10, borderRadius: 8, border: '1px solid rgba(127,127,127,0.2)' }}>
                <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>推荐封面提示词</div>
                <div style={{ fontSize: 12, opacity: 0.8, marginBottom: 8 }}>{suggestions.cover.prompt}</div>
                <button type="button" disabled={imgBusy} onClick={() => void runGenImage(suggestions.cover!.prompt!, 'cover')} style={{ ...goBtn, padding: '4px 10px', fontSize: 12 }}>
                  {imgBusy ? '生图中…' : '生成封面图'}
                </button>
              </div>
            )}

            {(suggestions?.inlines || []).map((inl, idx) => (
              <div key={idx} style={{ padding: 10, borderRadius: 8, border: '1px solid rgba(127,127,127,0.2)' }}>
                <div style={{ fontSize: 12, fontWeight: 600 }}>插图 {idx + 1} · {inl.caption || '正文插图'}</div>
                {inl.anchor && <div style={{ fontSize: 11.5, opacity: 0.65, margin: '2px 0 4px' }}>建议位置：{inl.anchor}</div>}
                <div style={{ fontSize: 12, opacity: 0.8, marginBottom: 8 }}>{inl.prompt}</div>
                <button type="button" disabled={imgBusy || !inl.prompt} onClick={() => void runGenImage(inl.prompt!, 'inline')} style={{ ...ghostBtn, padding: '4px 10px', fontSize: 12 }}>
                  {imgBusy ? '生图中…' : '生成此插图'}
                </button>
              </div>
            ))}

            <div style={{ padding: 10, borderRadius: 8, border: '1px solid rgba(127,127,127,0.2)' }}>
              <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>自定义提示词生图</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                <input
                  value={customImgPrompt}
                  onChange={(e) => setCustomImgPrompt(e.target.value)}
                  placeholder="输入画面描述（如：minimalist tech desk at night, warm lamp light）"
                  style={{ ...inputStyle, flex: 1, minWidth: 200, fontSize: 12 }}
                />
                <button type="button" disabled={imgBusy || !customImgPrompt.trim()} onClick={() => void runGenImage(customImgPrompt, 'cover')} style={{ ...ghostBtn, fontSize: 12 }}>
                  生成封面
                </button>
                <button type="button" disabled={imgBusy || !customImgPrompt.trim()} onClick={() => void runGenImage(customImgPrompt, 'inline')} style={{ ...goBtn, fontSize: 12 }}>
                  生成插图
                </button>
              </div>
            </div>

            {generatedImgs.length > 0 && (
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                {generatedImgs.map((g, i) => {
                  const full = g.url.startsWith('/') ? `${API_BASE}${g.url}` : g.url
                  return (
                    <div key={i} style={{ width: 170, border: '1px solid rgba(127,127,127,0.24)', borderRadius: 8, padding: 6, display: 'flex', flexDirection: 'column', gap: 6 }}>
                      <img src={full} alt={g.kind} style={{ width: '100%', height: 105, objectFit: 'cover', borderRadius: 5 }} />
                      <div style={{ display: 'flex', gap: 4 }}>
                        <button
                          type="button"
                          onClick={() => { onInsertImageToEditor(g.url, '配图'); setImgModalOpen(false) }}
                          style={{ ...goBtn, flex: 1, padding: '4px 6px', fontSize: 11 }}
                        >
                          <Plus size={11} style={{ verticalAlign: 'middle' }} /> 插入正文
                        </button>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* 弹窗 3：个人写作习惯（my_style.md） */}
      {myStyleOpen && (
        <div onClick={() => setMyStyleOpen(false)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
          <div onClick={(e) => e.stopPropagation()} style={{ background: 'var(--bg-card, #1c2128)', border: '1px solid rgba(127,127,127,0.3)', borderRadius: 12, padding: 18, width: 'min(620px, 94vw)', display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ fontSize: 15, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 7 }}>
                <BookMarked size={16} color="#c4a77d" />
                <span>我的个人写作习惯档案</span>
              </div>
              <button type="button" onClick={() => setMyStyleOpen(false)} style={{ ...ghostBtn, padding: 4 }}><X size={14} /></button>
            </div>
            <div style={{ fontSize: 12, opacity: 0.68, lineHeight: 1.5 }}>
              开启「我的习惯」后，这段规则会以最高优先级自动注入每一次 Copilot 对话。你可以点「沉淀习惯」让 AI 从你的改稿里自动提纯，也可以直接在这里手改。
            </div>
            <textarea
              value={myStyleText}
              onChange={(e) => setMyStyleText(e.target.value)}
              placeholder="还没有沉淀个人习惯。你写完几篇并手动修改后，点右侧工具栏「沉淀习惯」，这里就会长出真正属于你的风格清单……"
              style={{ ...inputStyle, minHeight: 240, fontSize: 13, lineHeight: 1.7, resize: 'vertical', background: 'var(--bg-color)' }}
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button type="button" onClick={() => setMyStyleOpen(false)} style={ghostBtn}>关闭</button>
              <button type="button" disabled={myStyleBusy} onClick={saveMyStyleManual} style={goBtn}>
                {myStyleBusy ? '保存中…' : '保存习惯'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 弹窗 4：查看素材详情 */}
      {inspectSource && (
        <div onClick={() => setInspectSource(null)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
          <div onClick={(e) => e.stopPropagation()} style={{ background: 'var(--bg-card, #1c2128)', border: '1px solid rgba(127,127,127,0.3)', borderRadius: 12, padding: 18, width: 'min(620px, 94vw)', maxHeight: '82vh', display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
              <span style={{ fontSize: 14, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{inspectSource.title}</span>
              <div style={{ display: 'flex', gap: 6 }}>
                <button type="button" onClick={() => { void handleRemoveSource(inspectSource.id); setInspectSource(null) }} style={{ ...ghostBtn, color: '#e06c75', padding: '4px 8px', fontSize: 12 }}>
                  <Trash2 size={12} />
                </button>
                <button type="button" onClick={() => setInspectSource(null)} style={{ ...ghostBtn, padding: '4px 8px' }}><X size={13} /></button>
              </div>
            </div>
            {inspectSource.url && (
              <div style={{ fontSize: 11.5, opacity: 0.65, wordBreak: 'break-all' }}>{inspectSource.url}</div>
            )}
            <div style={{ overflowY: 'auto', flex: 1 }}>
              {inspectSource.kind === 'image' && inspectSource.path ? (
                <img src={imgProxyUrl(inspectSource.path)} alt={inspectSource.title} style={{ maxWidth: '100%', borderRadius: 8 }} />
              ) : (
                <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12.5, lineHeight: 1.65, fontFamily: 'inherit', margin: 0, opacity: 0.85 }}>
                  {inspectSource.content || '（无正文摘要）'}
                </pre>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 弹窗 5：推送公众号草稿箱 */}
      {pushModalOpen && (
        <div onClick={() => setPushModalOpen(false)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
          <div onClick={(e) => e.stopPropagation()} style={{ background: 'var(--bg-card, #1c2128)', border: '1px solid rgba(127,127,127,0.3)', borderRadius: 12, padding: 18, width: 'min(520px, 94vw)', display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ fontSize: 15, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 7 }}>
                <Send size={15} color="#07c160" />
                <span>推送至微信公众号草稿箱</span>
              </div>
              <button type="button" onClick={() => setPushModalOpen(false)} style={{ ...ghostBtn, padding: 4 }}><X size={14} /></button>
            </div>
            <div style={{ fontSize: 12, opacity: 0.72, lineHeight: 1.6 }}>
              将使用当前主题排版为内联 HTML，自动上传文中本地配图至微信图床，并附带{proj.cover_url ? '本篇已生成封面图' : '账号默认封面'}。
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {(platforms.find((pl) => pl.key === 'wechat_mp')?.accounts || []).length === 0 ? (
                <div style={{ fontSize: 13, opacity: 0.6, padding: 12 }}>还没有配置公众号账号，请先到左侧「账号与设置」添加。</div>
              ) : (
                (platforms.find((pl) => pl.key === 'wechat_mp')?.accounts || []).map((acc) => {
                  const r = dispatchRes[acc.id]
                  return (
                    <div key={acc.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', borderRadius: 8, border: '1px solid rgba(127,127,127,0.2)' }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 13.5, fontWeight: 600 }}>{acc.name}</div>
                        {r && (
                          <div style={{ fontSize: 11.5, marginTop: 2, color: r.status === 'ok' ? '#3a9d5d' : r.status === 'err' ? '#e06c75' : 'inherit' }}>
                            {r.status === 'loading' ? '推送中…' : r.msg}
                          </div>
                        )}
                      </div>
                      <button
                        type="button"
                        disabled={r?.status === 'loading'}
                        onClick={() => void dispatchWechat(acc)}
                        style={{
                          padding: '5px 12px',
                          borderRadius: 7,
                          border: 'none',
                          cursor: 'pointer',
                          fontSize: 12.5,
                          fontWeight: 600,
                          background: 'linear-gradient(135deg,#07c160,#05974c)',
                          color: '#fff',
                        }}
                      >
                        {r?.status === 'ok' ? (
                          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}><Check size={12} /> 再次推送</span>
                        ) : '立即推送'}
                      </button>
                    </div>
                  )
                })
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
