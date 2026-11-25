import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  FileText, FolderInput, Pencil, Plus, Search, Sparkles, Trash2, X,
} from 'lucide-react'
import { API_BASE } from '../../api/base'
import {
  type ImgModel, type ProjSummary, type StyleItem, type ThemeItem, type TxtModel,
  card, ghostBtn, goBtn, inputStyle,
} from '../studio/StudioShell'
import CanvasCopilotPane from './CanvasCopilotPane'
import CanvasEditorPane, { type CanvasViewMode } from './CanvasEditorPane'
import { type CanvasProject, type CanvasSummary, type SelectionLock, formatShortTime } from './types'

export default function CanvasShell() {
  const [list, setList] = useState<CanvasSummary[]>([])
  const [search, setSearch] = useState('')
  const [proj, setProj] = useState<CanvasProject | null>(null)

  // 创建与导入状态
  const [showNew, setShowNew] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [importOpen, setImportOpen] = useState(false)
  const [oldStudioList, setOldStudioList] = useState<ProjSummary[]>([])
  const [busy, setBusy] = useState(false)
  const [deleting, setDeleting] = useState<string | null>(null)
  const [renaming, setRenaming] = useState<string | null>(null)
  const [renameText, setRenameText] = useState('')

  // 共享目录配置
  const [txtModels, setTxtModels] = useState<TxtModel[]>([])
  const [imgModels, setImgModels] = useState<ImgModel[]>([])
  const [styleList, setStyleList] = useState<StyleItem[]>([])
  const [themeList, setThemeList] = useState<ThemeItem[]>([])

  // 编辑器实时受控态
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [themePick, setThemePick] = useState('moyu_green')
  const [modelPick, setModelPick] = useState('')
  const [stylePick, setStylePick] = useState('')
  const [useMyStyle, setUseMyStyle] = useState(true)
  const [viewMode, setViewMode] = useState<CanvasViewMode>('split')
  const [saveStatus, setSaveStatus] = useState<'saved' | 'saving' | 'dirty'>('saved')
  const [renderedHtml, setRenderedHtml] = useState('')

  // Copilot 协同联动
  const [aiStreaming, setAiStreaming] = useState(false)
  const [selectionLock, setSelectionLock] = useState<SelectionLock | null>(null)
  const [quickSeedPrompt, setQuickSeedPrompt] = useState('')
  const [pushModalOpen, setPushModalOpen] = useState(false)

  // 可拖拽分栏比例
  const [leftRatio, setLeftRatio] = useState(58)
  const containerRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const saveTimerRef = useRef<number | null>(null)
  const renderTimerRef = useRef<number | null>(null)

  const loadList = useCallback(() => {
    fetch(`${API_BASE}/canvas/projects`)
      .then((r) => r.json())
      .then((d) => setList(d.projects || []))
      .catch(() => {})
  }, [])

  useEffect(() => {
    loadList()
    fetch(`${API_BASE}/studio/text-models`).then((r) => r.json()).then((d) => setTxtModels(d.models || [])).catch(() => {})
    fetch(`${API_BASE}/studio/image-models`).then((r) => r.json()).then((d) => setImgModels(d.models || [])).catch(() => {})
    fetch(`${API_BASE}/studio/styles`).then((r) => r.json()).then((d) => setStyleList(d.styles || [])).catch(() => {})
    fetch(`${API_BASE}/themes`).then((r) => r.json()).then((d) => setThemeList(d.themes || [])).catch(() => {})
  }, [loadList])

  const shownList = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return list
    return list.filter((x) => (x.title || '').toLowerCase().includes(q))
  }, [list, search])

  function hydrateProject(p: CanvasProject) {
    setProj(p)
    setTitle(p.title || '未命名文章')
    setContent(p.content || '')
    setThemePick(p.theme || 'moyu_green')
    setModelPick(p.model || '')
    setStylePick(p.style || '')
    setUseMyStyle(p.use_my_style !== false)
    setSaveStatus('saved')
    setSelectionLock(null)
  }

  async function openProject(pid: string) {
    try {
      const d = await (await fetch(`${API_BASE}/canvas/projects/${pid}`)).json()
      if (d.ok && d.project) hydrateProject(d.project)
    } catch {
      /* ignore */
    }
  }

  async function createProject() {
    if (busy) return
    setBusy(true)
    try {
      const d = await (await fetch(`${API_BASE}/canvas/projects`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: newTitle.trim() || '未命名文章' }),
      })).json()
      if (d.ok && d.project) {
        setShowNew(false)
        setNewTitle('')
        loadList()
        hydrateProject(d.project)
      }
    } finally {
      setBusy(false)
    }
  }

  async function openImportModal() {
    setImportOpen(true)
    try {
      const d = await (await fetch(`${API_BASE}/studio/projects`)).json()
      setOldStudioList(d.projects || [])
    } catch {
      setOldStudioList([])
    }
  }

  async function importFromStudio(studioPid: string) {
    if (busy) return
    setBusy(true)
    try {
      const d = await (await fetch(`${API_BASE}/canvas/projects/import-studio/${studioPid}`, { method: 'POST' })).json()
      if (d.ok && d.project) {
        setImportOpen(false)
        loadList()
        hydrateProject(d.project)
      }
    } finally {
      setBusy(false)
    }
  }

  async function submitRename(pid: string) {
    const nt = renameText.trim()
    setRenaming(null)
    if (!nt) return
    await fetch(`${API_BASE}/canvas/projects/${pid}/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: nt }),
    })
    loadList()
  }

  // 防抖自动保存（不产生冗余快照）
  const persistFields = useCallback(async (
    pid: string,
    patch: { title?: string; content?: string; theme?: string; style?: string; model?: string; use_my_style?: boolean; push_version?: boolean; version_label?: string },
  ) => {
    setSaveStatus('saving')
    try {
      const d = await (await fetch(`${API_BASE}/canvas/projects/${pid}/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      })).json()
      if (d.ok && d.project) {
        setProj(d.project)
        setSaveStatus('saved')
      }
    } catch {
      setSaveStatus('dirty')
    }
  }, [])

  function scheduleContentSave(nextContent: string) {
    if (!proj) return
    setContent(nextContent)
    setSaveStatus('dirty')
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current)
    const pid = proj.id
    saveTimerRef.current = window.setTimeout(() => {
      void persistFields(pid, { content: nextContent })
    }, 750)
  }

  // 微信预览防抖实时渲染
  useEffect(() => {
    if (!proj || viewMode === 'edit') return
    if (!content.trim()) {
      setRenderedHtml('')
      return
    }
    if (renderTimerRef.current) window.clearTimeout(renderTimerRef.current)
    renderTimerRef.current = window.setTimeout(() => {
      fetch(`${API_BASE}/canvas/render-wechat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ markdown: content, theme: themePick, include_footer: false }),
      })
        .then((r) => r.json())
        .then((d) => { if (d.ok) setRenderedHtml(d.html || '') })
        .catch(() => {})
    }, aiStreaming ? 450 : 220)
    return () => {
      if (renderTimerRef.current) window.clearTimeout(renderTimerRef.current)
    }
  }, [proj?.id, content, themePick, viewMode, aiStreaming])

  async function handleTitleSave(nextTitle: string): Promise<boolean> {
    if (!proj) return false
    setTitle(nextTitle)
    await persistFields(proj.id, { title: nextTitle })
    loadList()
    return true
  }

  async function handleRestoreVersion(vid: string) {
    if (!proj || aiStreaming) return
    const d = await (await fetch(`${API_BASE}/canvas/projects/${proj.id}/restore-version`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ version_id: vid }),
    })).json()
    if (d.ok && d.project) hydrateProject(d.project)
  }

  function insertImageAtCursor(url: string, alt: string) {
    const mdSnippet = `\n\n![${alt}](${url})\n\n`
    const el = textareaRef.current
    if (el) {
      const start = el.selectionStart ?? content.length
      const end = el.selectionEnd ?? content.length
      const next = content.slice(0, start) + mdSnippet + content.slice(end)
      scheduleContentSave(next)
    } else {
      scheduleContentSave(`${content}${mdSnippet}`)
    }
    if (viewMode === 'edit') setViewMode('split')
  }

  function startSplitDrag(e: React.MouseEvent) {
    e.preventDefault()
    const onMove = (ev: MouseEvent) => {
      const box = containerRef.current?.getBoundingClientRect()
      if (!box || box.width <= 0) return
      const pct = ((ev.clientX - box.left) / box.width) * 100
      setLeftRatio(Math.min(75, Math.max(35, pct)))
    }
    const onUp = () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  // 列表视图
  if (!proj) {
    return (
      <div style={{ flex: 1, overflow: 'auto', padding: '18px 24px', width: '100%' }}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 14, gap: 10, flexWrap: 'wrap' }}>
          <button
            type="button"
            style={{ ...goBtn, display: 'inline-flex', alignItems: 'center', gap: 6 }}
            onClick={() => setShowNew((v) => !v)}
          >
            <Plus size={14} />
            <span>新建文稿</span>
          </button>
          <button
            type="button"
            style={{ ...ghostBtn, display: 'inline-flex', alignItems: 'center', gap: 6 }}
            onClick={openImportModal}
          >
            <FolderInput size={14} />
            <span>从旧创作台导入</span>
          </button>
          <div style={{ position: 'relative', flex: 1, minWidth: 180 }}>
            <Search size={13} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', opacity: 0.5 }} />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索文稿标题"
              style={{ ...inputStyle, width: '100%', padding: '6px 10px 6px 30px', fontSize: 13 }}
            />
          </div>
        </div>

        {showNew && (
          <div style={{ ...card, display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <input
              autoFocus
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') void createProject() }}
              placeholder="输入文章标题或方向（也可留空直接进画布开聊）"
              style={{ ...inputStyle, flex: 1, minWidth: 240 }}
            />
            <button type="button" style={goBtn} disabled={busy} onClick={createProject}>
              进入画布
            </button>
          </div>
        )}

        {list.length === 0 && (
          <div style={{ ...card, padding: 28, textAlign: 'center', opacity: 0.72, fontSize: 13.5, lineHeight: 1.8 }}>
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontWeight: 600, marginBottom: 6 }}>
              <Sparkles size={15} color="#c4a77d" />
              <span>双栏协同创作台（Canvas）</span>
            </div>
            <div>左侧手写与实时预览微信排版，右侧直接投喂链接、截图、文档与 Copilot 对话改稿。</div>
            <div style={{ opacity: 0.7, fontSize: 12.5, marginTop: 4 }}>点上方「新建文稿」开始，或「从旧创作台导入」把已有文章无损拉过来试写。</div>
          </div>
        )}

        {shownList.map((p) => {
          const isEdit = renaming === p.id
          const isDel = deleting === p.id
          return (
            <div
              key={p.id}
              onClick={() => { if (!isEdit && !isDel) void openProject(p.id) }}
              style={{
                ...card,
                cursor: isEdit || isDel ? 'default' : 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 12,
              }}
            >
              <FileText size={17} style={{ opacity: 0.75, flexShrink: 0, color: '#c4a77d' }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                {isEdit ? (
                  <input
                    autoFocus
                    value={renameText}
                    onChange={(e) => setRenameText(e.target.value)}
                    onClick={(e) => e.stopPropagation()}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') void submitRename(p.id)
                      else if (e.key === 'Escape') setRenaming(null)
                    }}
                    onBlur={() => void submitRename(p.id)}
                    style={{ ...inputStyle, width: '100%', fontSize: 14, fontWeight: 600, padding: '4px 8px' }}
                  />
                ) : (
                  <div style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.title}</div>
                )}
                <div style={{ fontSize: 12, opacity: 0.6, marginTop: 2, fontVariantNumeric: 'tabular-nums' }}>
                  {p.word_count} 字 · {p.source_count} 份素材 · {p.version_count} 版快照 · {formatShortTime(p.updated)}
                  {p.draft_media_id ? ' · 已推草稿箱' : ''}
                </div>
              </div>
              {isDel ? (
                <>
                  <span style={{ fontSize: 12.5, color: '#e06c75' }}>确认删除？</span>
                  <button type="button" style={{ ...ghostBtn, padding: '4px 9px', fontSize: 12 }} onClick={(e) => { e.stopPropagation(); setDeleting(null) }}>取消</button>
                  <button
                    type="button"
                    style={{ ...ghostBtn, padding: '4px 9px', fontSize: 12, color: '#e06c75', borderColor: 'rgba(224,108,117,0.5)' }}
                    onClick={(e) => {
                      e.stopPropagation()
                      fetch(`${API_BASE}/canvas/projects/${p.id}`, { method: 'DELETE' }).then(() => { setDeleting(null); loadList() })
                    }}
                  >
                    删除
                  </button>
                </>
              ) : isEdit ? null : (
                <>
                  <button
                    type="button"
                    title="重命名"
                    style={{ ...ghostBtn, padding: '5px 8px', opacity: 0.65 }}
                    onClick={(e) => { e.stopPropagation(); setRenaming(p.id); setRenameText(p.title) }}
                  >
                    <Pencil size={13} />
                  </button>
                  <button
                    type="button"
                    title="删除"
                    style={{ ...ghostBtn, padding: '5px 8px', opacity: 0.65 }}
                    onClick={(e) => { e.stopPropagation(); setDeleting(p.id) }}
                  >
                    <Trash2 size={13} />
                  </button>
                </>
              )}
            </div>
          )
        })}

        {importOpen && (
          <div onClick={() => setImportOpen(false)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
            <div onClick={(e) => e.stopPropagation()} style={{ background: 'var(--bg-card, #1c2128)', border: '1px solid rgba(127,127,127,0.3)', borderRadius: 12, padding: 18, width: 'min(580px, 94vw)', maxHeight: '80vh', display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span style={{ fontSize: 15, fontWeight: 600 }}>从旧创作台复制导入（原项目保持不变）</span>
                <button type="button" onClick={() => setImportOpen(false)} style={{ ...ghostBtn, padding: 4 }}><X size={14} /></button>
              </div>
              <div style={{ overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column', gap: 6 }}>
                {oldStudioList.length === 0 ? (
                  <div style={{ padding: 20, textAlign: 'center', opacity: 0.6, fontSize: 13 }}>旧创作台暂无项目</div>
                ) : (
                  oldStudioList.map((op) => (
                    <button
                      key={op.id}
                      type="button"
                      disabled={busy}
                      onClick={() => void importFromStudio(op.id)}
                      style={{
                        ...ghostBtn,
                        textAlign: 'left',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 10,
                        padding: '9px 12px',
                      }}
                    >
                      <span style={{ fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{op.title || '未命名'}</span>
                      <span style={{ fontSize: 11.5, opacity: 0.6, flexShrink: 0 }}>{op.done_count}/{op.total} 步</span>
                    </button>
                  ))
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    )
  }

  // 双栏协同画布视图
  return (
    <div ref={containerRef} style={{ flex: 1, minWidth: 0, height: '100%', display: 'flex', overflow: 'hidden' }}>
      <div style={{ width: `${leftRatio}%`, minWidth: 320, height: '100%', display: 'flex', overflow: 'hidden' }}>
        <CanvasEditorPane
          proj={proj}
          title={title}
          content={content}
          themePick={themePick}
          themeList={themeList}
          viewMode={viewMode}
          setViewMode={setViewMode}
          saveStatus={saveStatus}
          aiStreaming={aiStreaming}
          textareaRef={textareaRef}
          onBack={() => { setProj(null); loadList() }}
          onTitleSave={handleTitleSave}
          onContentChange={scheduleContentSave}
          onThemeChange={(t) => {
            setThemePick(t)
            void persistFields(proj.id, { theme: t })
          }}
          onPushSnapshot={() => {
            void persistFields(proj.id, { title, content, push_version: true, version_label: '手动保存' })
          }}
          onRestoreVersion={(vid) => void handleRestoreVersion(vid)}
          onSelectForCopilot={(sel, quickPrompt) => {
            setSelectionLock(sel)
            if (quickPrompt) setQuickSeedPrompt(quickPrompt)
          }}
          onOpenPushModal={() => setPushModalOpen(true)}
          renderedHtml={renderedHtml}
        />
      </div>

      {/* 中间可拖拽分隔条 */}
      <div
        onMouseDown={startSplitDrag}
        title="拖动调整左右宽度"
        style={{
          width: 5,
          flexShrink: 0,
          cursor: 'col-resize',
          background: 'rgba(127,127,127,0.14)',
        }}
      />

      <div style={{ flex: 1, minWidth: 320, height: '100%', display: 'flex', overflow: 'hidden' }}>
        <CanvasCopilotPane
          proj={proj}
          title={title}
          content={content}
          themePick={themePick}
          txtModels={txtModels}
          imgModels={imgModels}
          styleList={styleList}
          modelPick={modelPick}
          stylePick={stylePick}
          useMyStyle={useMyStyle}
          aiStreaming={aiStreaming}
          selectionLock={selectionLock}
          quickSeedPrompt={quickSeedPrompt}
          pushModalOpen={pushModalOpen}
          setPushModalOpen={setPushModalOpen}
          onConsumeSeedPrompt={() => setQuickSeedPrompt('')}
          onClearSelectionLock={() => setSelectionLock(null)}
          onChangeModel={(m) => {
            setModelPick(m)
            void persistFields(proj.id, { model: m })
          }}
          onChangeStyle={(s) => {
            setStylePick(s)
            void persistFields(proj.id, { style: s })
          }}
          onToggleMyStyle={(v) => {
            setUseMyStyle(v)
            void persistFields(proj.id, { use_my_style: v })
          }}
          onInsertImageToEditor={insertImageAtCursor}
          onRestoreVersion={(vid) => void handleRestoreVersion(vid)}
          onStreamStart={() => setAiStreaming(true)}
          onStreamArticleDelta={(delta, isFirst) => {
            setContent((prev) => (isFirst ? delta : prev + delta))
          }}
          onStreamArticleFull={(full) => {
            setContent(full)
          }}
          onStreamFinish={(updatedProj) => {
            setAiStreaming(false)
            hydrateProject(updatedProj)
            loadList()
          }}
          onStreamError={() => {
            setAiStreaming(false)
          }}
          onProjectUpdated={(updatedProj) => {
            setProj(updatedProj)
            if (updatedProj.title) setTitle(updatedProj.title)
          }}
          renderedHtml={renderedHtml}
        />
      </div>
    </div>
  )
}
