import { useEffect, useMemo, useState } from 'react'
import { API_BASE } from '../../api/base'
import WechatWorkbench from './WechatWorkbench'
import XhsWorkbench from './XhsWorkbench'

interface NodeMeta { id: string; type: string; role?: string; writes: string }
export interface ThemeItem { id: string; name: string; desc: string; primary: string }
export interface Project {
  id: string; title: string; workflow: string; name: string
  inputs: Record<string, string>; nodes: NodeMeta[]
  state: Record<string, unknown>; current: number; done: boolean[]; updated: number
  model?: string
  style?: string
  theme?: string
  topic_id?: string
  account_id?: string
  step_models?: Record<string, string>
}
export interface ProjSummary { id: string; title: string; workflow: string; name: string; current: number; total: number; done_count: number; updated: number }
export interface ImgModel { model: string; provider: string; provider_name: string }
export interface TxtModel { model: string; name: string; provider: string; provider_name: string }
export interface StyleItem { id: string; name: string; desc: string; overrides: string[] }
export interface MPAccount { id: string; name: string; url?: string; appid?: string; secret?: string; thumb_media_id?: string }
export interface MPlatform { key: string; name: string; emoji?: string; home: string; accounts: MPAccount[] }

export const STEP_LABEL: Record<string, string> = {
  collect: '资料收集', outline: '选题大纲', draft: '撰稿', fact: '事实核查',
  style: '风格润色', image_brief: '配图', review: '人工审核', finalize: '定稿',
  format: '排版',
  copy: '正文文案', image_batch: '图组成片',
}
export const stepLabel = (n: NodeMeta) => STEP_LABEL[n.id] || n.role || n.id

export const ROLE_LABEL: Record<string, string> = {
  planner: '选题策划', writer: '撰稿', fact_checker: '事实核查',
  style_editor: '风格润色', art_director: '配图', finalizer: '定稿',
  copywriter: '正文文案',
}

const PLATFORMS: { key: string; name: string; emoji: string; workflow: string }[] = [
  { key: 'wechat', name: '公众号', emoji: '📄', workflow: 'content_pipeline' },
  { key: 'xhs', name: '小红书', emoji: '📕', workflow: 'xhs_pipeline' },
]
const WORKFLOW_TO_PLATFORM: Record<string, { emoji: string; name: string }> = {
  content_pipeline: { emoji: '📄', name: '公众号' },
  xhs_pipeline: { emoji: '📕', name: '小红书' },
}
export const platformBadge = (workflow: string): { emoji: string; name: string } =>
  WORKFLOW_TO_PLATFORM[workflow] || { emoji: '📄', name: workflow }

export async function goExternal(url: string) {
  window.open(url, '_blank', 'noopener,noreferrer')
}

export function groupByProvider<T extends { provider: string; provider_name: string }>(models: T[]): [string, T[]][] {
  const groups: Record<string, T[]> = {}
  const order: string[] = []
  for (const m of models) {
    const key = m.provider_name || m.provider
    if (!groups[key]) { groups[key] = []; order.push(key) }
    groups[key].push(m)
  }
  return order.map((k) => [k, groups[k]] as [string, T[]])
}

export const COVER_MODEL_KEY = 'studio.coverModelPick'

export const card: React.CSSProperties = { background: 'rgba(127,127,127,0.08)', border: '1px solid rgba(127,127,127,0.18)', borderRadius: 10, padding: 14, marginBottom: 12 }
export const inputStyle: React.CSSProperties = { padding: '7px 10px', borderRadius: 8, border: '1px solid rgba(127,127,127,0.3)', background: 'transparent', color: 'inherit' }
export const goBtn: React.CSSProperties = { padding: '7px 16px', borderRadius: 8, border: 'none', cursor: 'pointer', fontWeight: 600, background: 'linear-gradient(135deg,#c4a77d,#8a6c49)', color: '#fff' }
export const ghostBtn: React.CSSProperties = { padding: '7px 12px', borderRadius: 8, border: '1px solid rgba(127,127,127,0.35)', cursor: 'pointer', background: 'transparent', color: 'inherit' }

interface StudioShellProps {
  openProjectId?: string
  onConsumedOpenProject?: () => void
}

export default function StudioShell({ openProjectId, onConsumedOpenProject }: StudioShellProps = {}) {
  const [list, setList] = useState<ProjSummary[]>([])
  const [search, setSearch] = useState('')
  const [sortBy, setSortBy] = useState('updated')
  const [renaming, setRenaming] = useState<string | null>(null)
  const [renameText, setRenameText] = useState('')
  const [deleting, setDeleting] = useState<string | null>(null)
  const [proj, setProj] = useState<Project | null>(null)
  const [sel, setSel] = useState(0)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [showNew, setShowNew] = useState(false)
  const [topic, setTopic] = useState('')
  const [newPlatform, setNewPlatform] = useState('wechat')
  const [imgModels, setImgModels] = useState<ImgModel[]>([])
  const [imgPick, setImgPick] = useState('')
  const [txtModels, setTxtModels] = useState<TxtModel[]>([])
  const [currentModelId, setCurrentModelId] = useState('')
  const [txtPick, setTxtPick] = useState('')
  const [styleList, setStyleList] = useState<StyleItem[]>([])
  const [stylePick, setStylePick] = useState('')
  const [themeList, setThemeList] = useState<ThemeItem[]>([])
  const [themePick, setThemePick] = useState('moyu_green')
  const [stepModels, setStepModels] = useState<Record<string, string>>({})
  const [editorOpen, setEditorOpen] = useState(false)
  const [edBase, setEdBase] = useState('')
  const [edRoles, setEdRoles] = useState<{ role: string; text: string; overridden: boolean }[]>([])
  const [edName, setEdName] = useState('')
  const [edBusy, setEdBusy] = useState(false)
  const [edMsg, setEdMsg] = useState('')

  function loadList() {
    fetch(`${API_BASE}/studio/projects`).then((r) => r.json()).then((d) => setList(d.projects || [])).catch(() => {})
  }
  useEffect(() => { loadList() }, [])

  const shownList = useMemo(() => {
    const q = search.trim().toLowerCase()
    const r = q ? list.filter((p) => (p.title || '').toLowerCase().includes(q) || (p.name || '').toLowerCase().includes(q)) : list
    const arr = [...r]
    if (sortBy === 'updated') arr.sort((a, b) => (b.updated || 0) - (a.updated || 0))
    else if (sortBy === 'oldest') arr.sort((a, b) => (a.updated || 0) - (b.updated || 0))
    else if (sortBy === 'title') arr.sort((a, b) => (a.title || '').localeCompare(b.title || '', 'zh'))
    else if (sortBy === 'progress') arr.sort((a, b) => (b.done_count / Math.max(1, b.total)) - (a.done_count / Math.max(1, a.total)))
    return arr
  }, [list, search, sortBy])

  useEffect(() => {
    fetch(`${API_BASE}/studio/image-models`).then((r) => r.json()).then((d) => setImgModels(d.models || [])).catch(() => {})
    fetch(`${API_BASE}/studio/text-models`).then((r) => r.json()).then((d) => { setTxtModels(d.models || []); setCurrentModelId(d.current || '') }).catch(() => {})
    fetch(`${API_BASE}/studio/styles`).then((r) => r.json()).then((d) => setStyleList(d.styles || [])).catch(() => {})
    fetch(`${API_BASE}/themes`).then((r) => r.json()).then((d) => setThemeList(d.themes || [])).catch(() => {})
  }, [])

  useEffect(() => {
    if (openProjectId) {
      loadList()
      openProject(openProjectId).finally(() => onConsumedOpenProject?.())
    }
  }, [openProjectId])

  const defaultModelName = useMemo(() => {
    const m = txtModels.find((x) => x.model === currentModelId)
    return m ? (m.name || m.model) : (currentModelId || '')
  }, [txtModels, currentModelId])

  useEffect(() => {
    if (!imgModels.length) return
    const inList = (v: string) => !!v && imgModels.some((m) => `${m.model}|${m.provider}` === v)
    const fallback = `${imgModels[0].model}|${imgModels[0].provider}`
    const state = (proj?.state || {}) as { _cover_model?: string; _cover_provider?: string }
    const saved = state._cover_model && state._cover_provider ? `${state._cover_model}|${state._cover_provider}` : ''
    let remembered = ''
    try { remembered = localStorage.getItem(COVER_MODEL_KEY) || '' } catch { /* ignore */ }
    setImgPick([remembered, saved].find(inList) || fallback)
  }, [imgModels, proj?.id])

  async function submitRename(id: string) {
    const nt = renameText.trim()
    setRenaming(null)
    if (!nt) return
    try {
      const d = await (await fetch(`${API_BASE}/studio/projects/${id}/rename`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: nt }),
      })).json()
      if (d.ok) loadList()
    } catch { /* ignore */ }
  }

  async function renameCurrent(newTitle: string): Promise<boolean> {
    if (!proj) return false
    const nt = newTitle.trim()
    if (!nt) return false
    try {
      const d = await (await fetch(`${API_BASE}/studio/projects/${proj.id}/rename`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: nt }),
      })).json()
      if (d.ok && d.title) {
        setProj((prev) => (prev ? {
          ...prev,
          title: d.title,
          inputs: { ...(prev.inputs || {}), topic: d.title },
          state: { ...(prev.state || {}), topic: d.title },
        } : prev))
        setMsg(`✓ 标题已更新：${d.title}`)
        loadList()
        return true
      }
      setMsg(`✗ 改标题失败：${d.error || '未知错误'}`)
    } catch (e) {
      setMsg(`✗ 改标题失败：${e}`)
    }
    return false
  }

  async function openProject(id: string, keepSel = false) {
    const d = await (await fetch(`${API_BASE}/studio/projects/${id}`)).json()
    if (d.ok) {
      setProj(d.project)
      if (!keepSel) setSel(d.project.current < d.project.nodes.length ? d.project.current : 0)
      setMsg('')
      setTxtPick(d.project.model || '')
      setStylePick(d.project.style || '')
      setThemePick(d.project.theme || 'moyu_green')
      setStepModels((d.project.step_models as Record<string, string>) || {})
    }
  }

  async function createProject() {
    if (!topic.trim()) { setMsg('请填主题'); return }
    const plat = PLATFORMS.find((p) => p.key === newPlatform) || PLATFORMS[0]
    setBusy(true); setMsg('')
    try {
      const d = await (await fetch(`${API_BASE}/studio/projects`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workflow: plat.workflow, inputs: { topic: topic.trim(), platform: plat.name }, title: topic.trim() }),
      })).json()
      if (d.ok) { setShowNew(false); setTopic(''); loadList(); setProj(d.project); setSel(0) }
      else setMsg(d.error || '创建失败')
    } catch (e) { setMsg(`创建失败：${e}`) } finally { setBusy(false) }
  }

  async function consumeStep(res: Response,
    onDelta: (t: string) => void, onReason: (t: string) => void,
    onImage?: (ev: { type: string; [k: string]: unknown }) => void) {
    if (!res.body) return { ok: false, error: '无响应流' } as { ok: boolean; error?: string; current?: number }
    const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = ''
    let result: { ok: boolean; error?: string; current?: number } = { ok: false, error: '未完成' }
    // eslint-disable-next-line no-constant-condition
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      const parts = buf.split('\n\n'); buf = parts.pop() || ''
      for (const p of parts) {
        const line = p.trim(); if (!line.startsWith('data:')) continue
        try {
          const ev = JSON.parse(line.slice(5).trim())
          if (ev.type === 'delta') onDelta(ev.text || '')
          else if (ev.type === 'reasoning') onReason(ev.text || '')
          else if (ev.type === 'step') result = { ok: true, current: ev.current }
          else if (ev.type === 'error') result = { ok: false, error: ev.msg || '出错' }
          else if (onImage && ['image_done', 'image_error', 'image_progress', 'batch_finish', 'begin'].includes(ev.type)) onImage(ev)
        } catch { /* 跳过 */ }
      }
    }
    return result
  }

  async function saveSettings(s: { model?: string; style?: string; theme?: string; step_models?: Record<string, string> }) {
    if (!proj) return
    try {
      await fetch(`${API_BASE}/studio/projects/${proj.id}/settings`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: s.model !== undefined ? s.model : txtPick,
          style: s.style !== undefined ? s.style : stylePick,
          theme: s.theme !== undefined ? s.theme : themePick,
          step_models: s.step_models !== undefined ? s.step_models : stepModels,
        }),
      })
    } catch { /* 静默 */ }
  }

  async function runStep(i: number, opts: { feedback?: string; nodeModel?: string; onDelta?: (t: string) => void; onReason?: (t: string) => void; onImage?: (ev: { type: string; [k: string]: unknown }) => void } = {}) {
    if (!proj || busy) return { ok: false as const, error: 'busy' }
    setBusy(true); setMsg('')
    try {
      const nodeModel = opts.nodeModel !== undefined ? opts.nodeModel : (stepModels[proj.nodes[i]?.id] || '')
      const res = await fetch(`${API_BASE}/studio/projects/${proj.id}/step`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ index: i, feedback: opts.feedback || '', model: txtPick, style: stylePick, node_model: nodeModel }),
      })
      const r = await consumeStep(res,
        opts.onDelta || (() => {}),
        opts.onReason || (() => {}),
        opts.onImage)
      if (r.ok) { await openProject(proj.id, true); setMsg('✓ 已生成') }
      else setMsg(`✗ ${r.error || '生成失败'}`)
      return { ok: r.ok as boolean, error: r.error }
    } catch (e) { setMsg(`✗ 生成失败：${e}`); return { ok: false, error: String(e) } } finally { setBusy(false) }
  }

  async function loadEditorPrompts(base: string) {
    setEdBase(base)
    try {
      const d = await (await fetch(`${API_BASE}/studio/prompts${base ? `?style=${encodeURIComponent(base)}` : ''}`)).json()
      setEdRoles((d.roles || []).map((r: { role: string; text?: string; overridden?: boolean }) => ({ role: r.role, text: r.text || '', overridden: !!r.overridden })))
    } catch { setEdRoles([]) }
  }
  function openEditor() { setEditorOpen(true); setEdName(''); setEdMsg(''); loadEditorPrompts(stylePick) }
  async function saveStyleEditor() {
    if (!edName.trim()) { setEdMsg('请填新风格名'); return }
    setEdBusy(true); setEdMsg('')
    try {
      const prompts: Record<string, string> = {}
      edRoles.forEach((r) => { prompts[r.role] = r.text })
      const d = await (await fetch(`${API_BASE}/studio/save-style`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: edName.trim(), prompts }),
      })).json()
      if (d.ok) {
        const sd = await (await fetch(`${API_BASE}/studio/styles`)).json()
        setStyleList(sd.styles || [])
        setStylePick(d.slug); saveSettings({ style: d.slug })
        setEditorOpen(false)
        setMsg(`✓ 已保存风格「${d.name}」并选用`)
      } else setEdMsg(`✗ ${d.error || '保存失败'}`)
    } catch (e) { setEdMsg(`✗ 保存失败：${e}`) } finally { setEdBusy(false) }
  }

  if (!proj) {
    return (
      <div style={{ flex: 1, overflow: 'auto', padding: '18px 24px', width: '100%' }}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 14, gap: 10, flexWrap: 'wrap' }}>
          <button type="button" style={goBtn} onClick={() => setShowNew((v) => !v)}>+ 新建创作</button>
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="🔍 搜索标题 / 主题"
            style={{ ...inputStyle, flex: 1, minWidth: 160, padding: '6px 10px', fontSize: 13 }} />
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value)} title="排序"
            style={{ ...inputStyle, padding: '6px 8px', fontSize: 12, background: 'var(--bg-card)' }}>
            <option value="updated">最近编辑</option>
            <option value="oldest">最早</option>
            <option value="title">标题</option>
            <option value="progress">完成度</option>
          </select>
        </div>
        {showNew && (
          <div style={card}>
            <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap', alignItems: 'center' }}>
              <span style={{ fontSize: 13, opacity: 0.7 }}>平台：</span>
              {PLATFORMS.map((p) => (
                <button key={p.key} type="button"
                  onClick={() => setNewPlatform(p.key)}
                  style={{ ...ghostBtn, fontSize: 13, ...(newPlatform === p.key ? { background: 'rgba(196,167,125,0.14)', borderColor: 'rgba(196,167,125,0.8)' } : {}) }}>
                  {p.emoji} {p.name}
                </button>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
              <input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="主题（如：用AI搭量化系统的踩坑）" style={{ ...inputStyle, flex: 1, minWidth: 240 }} />
              <button type="button" style={goBtn} disabled={busy} onClick={createProject}>开始创作</button>
            </div>
            {msg && <div style={{ marginTop: 8, fontSize: 13, opacity: 0.8 }}>{msg}</div>}
          </div>
        )}
        {list.length === 0 && <div style={{ opacity: 0.5, fontSize: 13, marginTop: 20 }}>还没有创作项目，点「+ 新建创作」开始。</div>}
        {list.length > 0 && shownList.length === 0 && <div style={{ opacity: 0.5, fontSize: 13, marginTop: 20 }}>没有匹配「{search}」的项目。</div>}
        {shownList.map((p) => {
          const editing = renaming === p.id
          const confirmDel = deleting === p.id
          const badge = platformBadge(p.workflow || '')
          return (
          <div key={p.id} style={{ ...card, cursor: editing || confirmDel ? 'default' : 'pointer', display: 'flex', alignItems: 'center', gap: 12 }} onClick={() => { if (!editing && !confirmDel) openProject(p.id) }}>
            <span style={{ fontSize: 18 }}>{badge.emoji}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              {editing ? (
                <input autoFocus value={renameText} onChange={(e) => setRenameText(e.target.value)}
                  onClick={(e) => e.stopPropagation()}
                  onKeyDown={(e) => { if (e.key === 'Enter') submitRename(p.id); else if (e.key === 'Escape') setRenaming(null) }}
                  onBlur={() => submitRename(p.id)}
                  style={{ ...inputStyle, width: '100%', fontSize: 14, fontWeight: 600, padding: '4px 8px' }} />
              ) : (
                <div style={{ fontWeight: 600 }}>{p.title || '未命名'}</div>
              )}
              <div style={{ fontSize: 12, opacity: 0.6, marginTop: 2 }}>{badge.name} · {p.name} · 进度 {p.done_count}/{p.total}</div>
            </div>
            {confirmDel ? (
              <>
                <span style={{ fontSize: 13, color: '#d9534f' }}>确认删除？</span>
                <button type="button" style={{ ...ghostBtn, opacity: 0.6 }} onClick={(e) => { e.stopPropagation(); setDeleting(null) }}>取消</button>
                <button type="button" style={{ ...ghostBtn, color: '#d9534f', borderColor: 'rgba(217,83,79,0.5)' }} onClick={(e) => { e.stopPropagation(); fetch(`${API_BASE}/studio/projects/${p.id}`, { method: 'DELETE' }).then(() => { setDeleting(null); loadList() }) }}>删除</button>
              </>
            ) : editing ? (
              <button type="button" style={{ ...ghostBtn, opacity: 0.85 }} onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); submitRename(p.id) }}>✓ 保存</button>
            ) : (
              <>
                <button type="button" style={{ ...ghostBtn, opacity: 0.6 }} onClick={(e) => { e.stopPropagation(); setRenaming(p.id); setRenameText(p.title || '') }}>重命名</button>
                <button type="button" style={{ ...ghostBtn, opacity: 0.6 }} onClick={(e) => { e.stopPropagation(); setDeleting(p.id) }}>删除</button>
              </>
            )}
          </div>
          )
        })}
      </div>
    )
  }

  const Workbench = proj.workflow === 'xhs_pipeline' ? XhsWorkbench : WechatWorkbench
  const shellProps = {
    proj, sel, setSel, busy, msg, setMsg,
    imgModels, imgPick, setImgPick, txtModels, txtPick, setTxtPick,
    defaultModelName,
    styleList, stylePick, setStylePick, themeList, themePick, setThemePick, stepModels, setStepModels,
    openProject, runStep, saveSettings, renameCurrent, openEditor, loadList,
  }
  return (
    <>
      {editorOpen && (
        <div onClick={() => setEditorOpen(false)}
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
          <div onClick={(e) => e.stopPropagation()}
            style={{ background: 'var(--bg-card, #1c2128)', border: '1px solid rgba(127,127,127,0.3)', borderRadius: 12, padding: 20, width: 'min(780px, 94vw)', maxHeight: '88vh', overflow: 'auto' }}>
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 4 }}>✏️ 风格编辑器</div>
            <div style={{ fontSize: 12, opacity: 0.6, marginBottom: 14 }}>选个基础风格做起点，改各步提示词，另存为你自己的新风格（不覆盖内置）。</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
              <span style={{ fontSize: 13 }}>基础风格</span>
              <select value={edBase} onChange={(e) => loadEditorPrompts(e.target.value)} style={{ ...inputStyle, padding: '5px 8px', fontSize: 13, background: 'var(--bg-card)' }}>
                <option value="">默认</option>
                {styleList.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </div>
            {edRoles.map((r, i) => (
              <div key={r.role} style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>{ROLE_LABEL[r.role] || r.role}</div>
                <textarea value={r.text}
                  onChange={(e) => setEdRoles((prev) => prev.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))}
                  style={{ ...inputStyle, width: '100%', minHeight: 90, resize: 'vertical', fontSize: 13, lineHeight: 1.6, background: 'var(--bg-card)' }} />
              </div>
            ))}
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginTop: 8, position: 'sticky', bottom: 0, background: 'var(--bg-card, #1c2128)', paddingTop: 8 }}>
              <input value={edName} onChange={(e) => setEdName(e.target.value)} placeholder="新风格名（如：我的卡兹克）" style={{ ...inputStyle, flex: 1, minWidth: 180 }} />
              <button type="button" style={goBtn} disabled={edBusy} onClick={saveStyleEditor}>{edBusy ? '保存中…' : '保存为新风格'}</button>
              <button type="button" style={ghostBtn} onClick={() => setEditorOpen(false)}>关闭</button>
            </div>
            {edMsg && <div style={{ marginTop: 8, fontSize: 13, opacity: 0.85 }}>{edMsg}</div>}
          </div>
        </div>
      )}
      <Workbench {...shellProps} onBack={() => { setProj(null); loadList() }} />
    </>
  )
}

export interface WorkbenchProps {
  proj: Project
  sel: number
  setSel: (i: number) => void
  busy: boolean
  msg: string
  setMsg: (s: string) => void
  imgModels: ImgModel[]
  imgPick: string
  setImgPick: (v: string) => void
  txtModels: TxtModel[]
  txtPick: string
  setTxtPick: (v: string) => void
  defaultModelName: string
  styleList: StyleItem[]
  stylePick: string
  setStylePick: (v: string) => void
  themeList: ThemeItem[]
  themePick: string
  setThemePick: (v: string) => void
  stepModels: Record<string, string>
  setStepModels: (m: Record<string, string>) => void
  openProject: (id: string, keepSel?: boolean) => Promise<void>
  runStep: (i: number, opts?: { feedback?: string; nodeModel?: string; onDelta?: (t: string) => void; onReason?: (t: string) => void; onImage?: (ev: { type: string; [k: string]: unknown }) => void }) => Promise<{ ok: boolean; error?: string }>
  saveSettings: (s: { model?: string; style?: string; theme?: string; step_models?: Record<string, string> }) => Promise<void>
  renameCurrent: (title: string) => Promise<boolean>
  openEditor: () => void
  loadList: () => void
  onBack: () => void
}
