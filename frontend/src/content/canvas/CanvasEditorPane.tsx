import { useEffect, useRef, useState } from 'react'
import {
  ArrowLeft, BookmarkPlus, Check, Columns, Copy, History,
  PenLine, Smartphone, Sparkles, Undo2,
} from 'lucide-react'
import { API_BASE } from '../../api/base'
import InlineTitleEditor from '../studio/InlineTitleEditor'
import { type ThemeItem, ghostBtn } from '../studio/StudioShell'
import {
  type CanvasProject, type SelectionLock, countChars, formatShortTime,
} from './types'

export type CanvasViewMode = 'split' | 'edit' | 'preview'

interface CanvasEditorPaneProps {
  proj: CanvasProject
  title: string
  content: string
  themePick: string
  themeList: ThemeItem[]
  viewMode: CanvasViewMode
  setViewMode: (m: CanvasViewMode) => void
  saveStatus: 'saved' | 'saving' | 'dirty'
  aiStreaming: boolean
  textareaRef: React.RefObject<HTMLTextAreaElement>
  onBack: () => void
  onTitleSave: (nextTitle: string) => Promise<boolean>
  onContentChange: (nextContent: string) => void
  onThemeChange: (nextTheme: string) => void
  onPushSnapshot: () => void
  onRestoreVersion: (versionId: string) => void
  onSelectForCopilot: (sel: SelectionLock, quickPrompt?: string) => void
  onOpenPushModal: () => void
  renderedHtml: string
}

function normalizePreviewImgSrc(html: string): string {
  if (!html || !API_BASE) return html
  return html.replace(/src="(\/(?:canvas|studio)\/projects\/[^"]+)"/g, `src="${API_BASE}$1"`)
}

export default function CanvasEditorPane({
  proj,
  title,
  content,
  themePick,
  themeList,
  viewMode,
  setViewMode,
  saveStatus,
  aiStreaming,
  textareaRef,
  onBack,
  onTitleSave,
  onContentChange,
  onThemeChange,
  onPushSnapshot,
  onRestoreVersion,
  onSelectForCopilot,
  onOpenPushModal,
  renderedHtml,
}: CanvasEditorPaneProps) {
  const [selLock, setSelLock] = useState<SelectionLock | null>(null)
  const [histOpen, setHistOpen] = useState(false)
  const [copiedHtml, setCopiedHtml] = useState(false)
  const histRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleOutside(e: MouseEvent) {
      if (histRef.current && !histRef.current.contains(e.target as Node)) {
        setHistOpen(false)
      }
    }
    if (histOpen) document.addEventListener('mousedown', handleOutside)
    return () => document.removeEventListener('mousedown', handleOutside)
  }, [histOpen])

  function detectSelection() {
    const el = textareaRef.current
    if (!el) return
    const start = el.selectionStart ?? 0
    const end = el.selectionEnd ?? 0
    if (end - start >= 4) {
      const text = el.value.slice(start, end).trim()
      if (text.length >= 4) {
        setSelLock({ text, start, end })
        return
      }
    }
    setSelLock(null)
  }

  async function copyWechatHtml() {
    if (!renderedHtml) return
    try {
      await navigator.clipboard.writeText(renderedHtml)
      setCopiedHtml(true)
      setTimeout(() => setCopiedHtml(false), 1800)
    } catch {
      /* ignore */
    }
  }

  const versions = proj.versions || []
  const chars = countChars(content)
  const readMin = Math.max(1, Math.round(chars / 400))
  const prevVersion = versions.length >= 2 ? versions[versions.length - 2] : null

  return (
    <div style={{ flex: 1, minWidth: 0, height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* 顶部控制条 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '9px 14px',
          borderBottom: '1px solid rgba(127,127,127,0.16)',
          flexShrink: 0,
        }}
      >
        <button
          type="button"
          onClick={onBack}
          title="返回文稿列表"
          style={{ ...ghostBtn, padding: '5px 8px', display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12, flexShrink: 0 }}
        >
          <ArrowLeft size={14} />
          <span>列表</span>
        </button>

        <InlineTitleEditor title={title || '未命名文章'} onSave={onTitleSave} />

        {/* 三段视图切换 */}
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            padding: 2,
            borderRadius: 8,
            border: '1px solid rgba(127,127,127,0.25)',
            background: 'rgba(127,127,127,0.06)',
            flexShrink: 0,
          }}
        >
          {(
            [
              { key: 'edit', label: '编辑', icon: <PenLine size={12.5} /> },
              { key: 'split', label: '对照', icon: <Columns size={12.5} /> },
              { key: 'preview', label: '预览', icon: <Smartphone size={12.5} /> },
            ] as { key: CanvasViewMode; label: string; icon: React.ReactNode }[]
          ).map((m) => {
            const active = viewMode === m.key
            return (
              <button
                key={m.key}
                type="button"
                onClick={() => setViewMode(m.key)}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4,
                  padding: '4px 9px',
                  borderRadius: 6,
                  border: 'none',
                  cursor: 'pointer',
                  fontSize: 12,
                  fontWeight: active ? 600 : 400,
                  background: active ? 'rgba(196,167,125,0.22)' : 'transparent',
                  color: 'inherit',
                }}
              >
                {m.icon}
                <span>{m.label}</span>
              </button>
            )
          })}
        </div>

        {/* 快捷撤回 & 版本历史 */}
        {prevVersion && (
          <button
            type="button"
            disabled={aiStreaming}
            onClick={() => onRestoreVersion(prevVersion.id)}
            title={`撤回到上一版：${prevVersion.label}`}
            style={{ ...ghostBtn, padding: '5px 8px', fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 4, flexShrink: 0 }}
          >
            <Undo2 size={13} />
          </button>
        )}

        <div ref={histRef} style={{ position: 'relative', flexShrink: 0 }}>
          <button
            type="button"
            onClick={() => setHistOpen((v) => !v)}
            title="版本快照"
            style={{ ...ghostBtn, padding: '5px 8px', fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 4 }}
          >
            <History size={13} />
            <span style={{ fontVariantNumeric: 'tabular-nums' }}>{versions.length}</span>
          </button>
          {histOpen && (
            <div
              style={{
                position: 'absolute',
                right: 0,
                top: '110%',
                width: 260,
                maxHeight: 320,
                overflowY: 'auto',
                background: 'var(--bg-card, #1c2128)',
                border: '1px solid rgba(127,127,127,0.28)',
                borderRadius: 10,
                padding: 6,
                zIndex: 40,
                boxShadow: '0 12px 32px rgba(0,0,0,0.3)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '4px 6px 6px', borderBottom: '1px solid rgba(127,127,127,0.14)', marginBottom: 4 }}>
                <span style={{ fontSize: 12, fontWeight: 600 }}>版本历史</span>
                <button
                  type="button"
                  onClick={() => { onPushSnapshot(); setHistOpen(false) }}
                  style={{ ...ghostBtn, padding: '2px 7px', fontSize: 11, display: 'inline-flex', alignItems: 'center', gap: 3 }}
                >
                  <BookmarkPlus size={11} />
                  <span>存一版</span>
                </button>
              </div>
              {versions.length === 0 && (
                <div style={{ fontSize: 12, opacity: 0.55, padding: 10, textAlign: 'center' }}>暂无快照</div>
              )}
              {[...versions].reverse().map((v) => (
                <button
                  key={v.id}
                  type="button"
                  disabled={aiStreaming}
                  onClick={() => { onRestoreVersion(v.id); setHistOpen(false) }}
                  style={{
                    width: '100%',
                    textAlign: 'left',
                    padding: '7px 8px',
                    borderRadius: 6,
                    border: 'none',
                    background: 'transparent',
                    color: 'inherit',
                    cursor: 'pointer',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 2,
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, fontWeight: 500 }}>
                    <span>{v.label}</span>
                    <span style={{ opacity: 0.55, fontSize: 11, fontVariantNumeric: 'tabular-nums' }}>{formatShortTime(v.ts)}</span>
                  </div>
                  <div style={{ fontSize: 11, opacity: 0.55, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {countChars(v.content)} 字 · {(v.content || '').slice(0, 42).replace(/\n/g, ' ')}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* 主题切换与微信操作副栏（预览或对照时展示） */}
      {viewMode !== 'edit' && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '6px 14px',
            borderBottom: '1px solid rgba(127,127,127,0.12)',
            background: 'rgba(127,127,127,0.03)',
            flexShrink: 0,
            flexWrap: 'wrap',
          }}
        >
          <span style={{ fontSize: 11.5, opacity: 0.6 }}>公众号样式</span>
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
            {themeList.map((t) => {
              const active = themePick === t.id
              return (
                <button
                  key={t.id}
                  type="button"
                  title={t.desc}
                  onClick={() => onThemeChange(t.id)}
                  style={{
                    ...ghostBtn,
                    padding: '3px 8px',
                    fontSize: 11.5,
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 5,
                    borderColor: active ? t.primary : 'rgba(127,127,127,0.25)',
                    background: active ? 'rgba(196,167,125,0.14)' : 'transparent',
                    fontWeight: active ? 600 : 400,
                  }}
                >
                  <span style={{ width: 7, height: 7, borderRadius: '50%', background: t.primary }} />
                  <span>{t.name}</span>
                </button>
              )
            })}
          </div>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
            <button
              type="button"
              onClick={copyWechatHtml}
              disabled={!renderedHtml}
              style={{ ...ghostBtn, padding: '3px 9px', fontSize: 11.5, display: 'inline-flex', alignItems: 'center', gap: 4 }}
            >
              {copiedHtml ? <Check size={12} color="#3a9d5d" /> : <Copy size={12} />}
              <span>{copiedHtml ? '已复制 HTML' : '复制 HTML'}</span>
            </button>
            <button
              type="button"
              onClick={onOpenPushModal}
              disabled={!content.trim()}
              style={{
                padding: '3px 10px',
                borderRadius: 7,
                border: 'none',
                cursor: 'pointer',
                fontSize: 11.5,
                fontWeight: 600,
                background: 'linear-gradient(135deg,#07c160,#05974c)',
                color: '#fff',
                opacity: content.trim() ? 1 : 0.45,
              }}
            >
              推草稿箱
            </button>
          </div>
        </div>
      )}

      {/* 主体：编辑区 + 微信手机实时预览 */}
      <div style={{ flex: 1, minHeight: 0, display: 'flex', overflow: 'hidden', position: 'relative' }}>
        {viewMode !== 'preview' && (
          <div
            style={{
              flex: 1,
              minWidth: 0,
              display: 'flex',
              flexDirection: 'column',
              position: 'relative',
              borderRight: viewMode === 'split' ? '1px solid rgba(127,127,127,0.16)' : 'none',
            }}
          >
            {aiStreaming && (
              <div
                style={{
                  position: 'absolute',
                  top: 8,
                  right: 14,
                  zIndex: 5,
                  fontSize: 11.5,
                  fontWeight: 600,
                  color: '#c4a77d',
                  padding: '3px 9px',
                  borderRadius: 999,
                  background: 'rgba(196,167,125,0.14)',
                  border: '1px solid rgba(196,167,125,0.35)',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 5,
                }}
              >
                <span className="studio-pulse">●</span>
                <span>正在写入画布</span>
              </div>
            )}

            <textarea
              ref={textareaRef}
              value={content}
              readOnly={aiStreaming}
              onChange={(e) => {
                setSelLock(null)
                onContentChange(e.target.value)
              }}
              onMouseUp={detectSelection}
              onKeyUp={detectSelection}
              placeholder={'在这里直接写作或修改 Markdown……\n\n也可以直接把链接、截图、文档拖进右侧对话区，让 Copilot 整合后写到这里。'}
              style={{
                flex: 1,
                width: '100%',
                minHeight: 0,
                resize: 'none',
                border: 'none',
                outline: 'none',
                background: 'transparent',
                color: 'inherit',
                padding: '18px 20px 64px',
                fontSize: 14.5,
                lineHeight: 1.85,
                fontFamily: "ui-sans-serif, -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif",
              }}
            />

            {/* 划选文本悬浮快捷条 */}
            {selLock && !aiStreaming && (
              <div
                style={{
                  position: 'absolute',
                  left: 16,
                  right: 16,
                  bottom: 14,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '6px 10px',
                  borderRadius: 10,
                  background: 'var(--bg-card, #1c2128)',
                  border: '1px solid rgba(196,167,125,0.45)',
                  boxShadow: '0 8px 24px rgba(0,0,0,0.28)',
                  zIndex: 8,
                  flexWrap: 'wrap',
                }}
              >
                <Sparkles size={13} color="#c4a77d" />
                <span style={{ fontSize: 12, opacity: 0.75, maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  已选「{selLock.text}」
                </span>
                <button
                  type="button"
                  onClick={() => { onSelectForCopilot(selLock); setSelLock(null) }}
                  style={{ ...ghostBtn, padding: '3px 8px', fontSize: 11.5, borderColor: 'rgba(196,167,125,0.6)' }}
                >
                  交给 Copilot 改
                </button>
                <button
                  type="button"
                  onClick={() => { onSelectForCopilot(selLock, '把这段改得更精简有力，去掉多余修饰'); setSelLock(null) }}
                  style={{ ...ghostBtn, padding: '3px 8px', fontSize: 11.5 }}
                >
                  精简
                </button>
                <button
                  type="button"
                  onClick={() => { onSelectForCopilot(selLock, '把这段改得更有活人感、像真人在跟朋友聊天，去掉书面套话'); setSelLock(null) }}
                  style={{ ...ghostBtn, padding: '3px 8px', fontSize: 11.5 }}
                >
                  更口语
                </button>
              </div>
            )}
          </div>
        )}

        {viewMode !== 'edit' && (
          <div
            style={{
              flex: viewMode === 'preview' ? 1 : '0 0 388px',
              minWidth: 0,
              overflowY: 'auto',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              padding: '14px 16px',
              background: 'radial-gradient(600px 320px at 50% -110px, rgba(196,167,125,0.08), transparent 70%)',
            }}
          >
            {/* 微信手机阅读器外框（始终采用微信真实浅色底还原线上效果） */}
            <div
              style={{
                width: 356,
                maxWidth: '100%',
                background: 'var(--bg-card)',
                border: '1px solid rgba(127,127,127,0.2)',
                borderRadius: 28,
                padding: 6,
                boxShadow: '0 20px 50px -14px rgba(0,0,0,0.32)',
              }}
            >
              <div
                style={{
                  background: '#FFFFFF',
                  color: '#1F2937',
                  borderRadius: 22,
                  overflow: 'hidden',
                  border: '1px solid rgba(0,0,0,0.08)',
                }}
              >
                <div
                  style={{
                    height: 26,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '0 18px',
                    fontSize: 11,
                    fontWeight: 600,
                    color: '#374151',
                    borderBottom: '1px solid #F3F4F6',
                  }}
                >
                  <span>9:41</span>
                  <span style={{ opacity: 0.6, fontSize: 10 }}>公众号预览</span>
                  <span style={{ opacity: 0.65, fontSize: 10 }}>5G</span>
                </div>

                <div style={{ padding: '16px 18px 12px', borderBottom: '1px solid #F3F4F6' }}>
                  <div style={{ fontSize: 19, lineHeight: 1.4, fontWeight: 700, color: '#111827', marginBottom: 10 }}>
                    {title || '未命名文章'}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 12, color: '#6B7280' }}>
                    <span
                      style={{
                        width: 20,
                        height: 20,
                        borderRadius: '50%',
                        background: 'linear-gradient(135deg,#c4a77d,#8a6c49)',
                        flexShrink: 0,
                      }}
                    />
                    <span style={{ color: '#8a6c49', fontWeight: 600 }}>公众号效果</span>
                    <span>·</span>
                    <span style={{ fontVariantNumeric: 'tabular-nums' }}>{chars} 字</span>
                  </div>
                </div>

                <div
                  style={{ padding: '4px 6px 26px', minHeight: 380 }}
                  dangerouslySetInnerHTML={{
                    __html: content.trim()
                      ? normalizePreviewImgSrc(renderedHtml)
                      : '<p style="padding:28px 16px;text-align:center;color:#9CA3AF;font-size:13px;">左侧输入或让 Copilot 生成内容后，此处实时预览微信排版效果</p>',
                  }}
                />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 底部极简状态栏 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '5px 14px',
          borderTop: '1px solid rgba(127,127,127,0.14)',
          fontSize: 11.5,
          opacity: 0.65,
          flexShrink: 0,
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        <span>{chars} 字 · 约 {readMin} 分钟读完</span>
        <span>{saveStatus === 'saving' ? '保存中…' : saveStatus === 'dirty' ? '待保存' : '已自动保存'}</span>
      </div>
    </div>
  )
}
