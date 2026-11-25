import { useEffect, useState } from 'react'
import { Check, Pencil, X } from 'lucide-react'
import { ghostBtn, inputStyle } from './StudioShell'

export default function InlineTitleEditor({
  title,
  onSave,
}: {
  title: string
  onSave: (nextTitle: string) => Promise<boolean>
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(title)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!editing) setDraft(title)
  }, [title, editing])

  async function commit() {
    const nt = draft.trim()
    if (!nt || nt === title) {
      setEditing(false)
      setDraft(title)
      return
    }
    setSaving(true)
    const ok = await onSave(nt)
    setSaving(false)
    if (ok) setEditing(false)
  }

  if (editing) {
    return (
      <div style={{ display: 'flex', flex: 1, minWidth: 0, alignItems: 'center', gap: 6 }}>
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commit()
            if (e.key === 'Escape') {
              setEditing(false)
              setDraft(title)
            }
          }}
          style={{
            ...inputStyle,
            flex: 1,
            minWidth: 0,
            width: '100%',
            padding: '4px 10px',
            fontSize: 14,
            fontWeight: 600,
          }}
        />
        <button
          type="button"
          disabled={saving}
          onClick={commit}
          title="保存标题"
          style={{ ...ghostBtn, padding: '5px 8px', display: 'inline-flex', alignItems: 'center', flexShrink: 0 }}
        >
          <Check size={13} />
        </button>
        <button
          type="button"
          disabled={saving}
          onClick={() => {
            setEditing(false)
            setDraft(title)
          }}
          title="取消"
          style={{ ...ghostBtn, padding: '5px 8px', display: 'inline-flex', alignItems: 'center', flexShrink: 0 }}
        >
          <X size={13} />
        </button>
      </div>
    )
  }

  return (
    <button
      type="button"
      onClick={() => {
        setDraft(title)
        setEditing(true)
      }}
      title="点击修改标题"
      style={{
        display: 'flex',
        flex: 1,
        minWidth: 0,
        alignItems: 'center',
        gap: 6,
        background: 'transparent',
        border: 'none',
        color: 'inherit',
        fontWeight: 600,
        fontSize: 14,
        cursor: 'pointer',
        padding: '4px 6px',
        borderRadius: 6,
        textAlign: 'left',
      }}
    >
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{title}</span>
      <Pencil size={12} style={{ opacity: 0.55, flexShrink: 0 }} />
    </button>
  )
}
