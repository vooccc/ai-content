import { useEffect, useRef, useState } from 'react'
import { API_BASE } from '../api/base'

interface Account {
  id: string
  name: string
  url?: string
  appid?: string
  secret?: string
  thumb_media_id?: string
}

interface Platform {
  key: string
  name: string
  emoji?: string
  icon?: string
  home: string
  accounts: Account[]
}

const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6)

function openExternal(url: string) {
  window.open(url, '_blank', 'noopener,noreferrer')
}

export default function PublishView() {
  const [platforms, setPlatforms] = useState<Platform[]>([])
  const [loaded, setLoaded] = useState(false)
  const [msg, setMsg] = useState('')
  const [addingTo, setAddingTo] = useState<string | null>(null)
  const [accName, setAccName] = useState('')
  const [accUrl, setAccUrl] = useState('')
  const [accAppid, setAccAppid] = useState('')
  const [accSecret, setAccSecret] = useState('')
  const [accThumb, setAccThumb] = useState('')
  const [uploadingFor, setUploadingFor] = useState<string | null>(null)
  const [editing, setEditing] = useState<{ pKey: string; accId: string } | null>(null)
  const [showAddPlat, setShowAddPlat] = useState(false)
  const [platName, setPlatName] = useState('')
  const [platHome, setPlatHome] = useState('')
  const [confirmDel, setConfirmDel] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const uploadTarget = useRef<{ pKey: string; accId: string; appid: string; secret: string } | null>(null)

  useEffect(() => {
    fetch(`${API_BASE}/content/config`)
      .then((r) => r.json())
      .then((d) => { setPlatforms(d.platforms || []); setLoaded(true) })
      .catch(() => setLoaded(true))
  }, [])

  async function save(next: Platform[], tip?: string) {
    setPlatforms(next)
    try {
      await fetch(`${API_BASE}/content/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platforms: next }),
      })
      if (tip) {
        setMsg(tip)
        setTimeout(() => setMsg(''), 2200)
      }
    } catch (e) {
      setMsg(`保存失败：${e}`)
    }
  }

  function startAddAccount(pKey: string) {
    setEditing(null)
    setAddingTo(pKey)
    setAccName('')
    setAccUrl('')
    setAccAppid('')
    setAccSecret('')
    setAccThumb('')
  }

  function startEditAccount(pKey: string, a: Account) {
    setAddingTo(null)
    setEditing({ pKey, accId: a.id })
    setAccName(a.name)
    setAccUrl(a.url || '')
    setAccAppid(a.appid || '')
    setAccSecret(a.secret || '')
    setAccThumb(a.thumb_media_id || '')
  }

  function submitAccount(pKey: string) {
    const name = accName.trim()
    if (!name) return
    const acc: Account = {
      id: editing ? editing.accId : uid(),
      name,
      ...(accUrl.trim() ? { url: accUrl.trim() } : {}),
      ...(accAppid.trim() ? { appid: accAppid.trim() } : {}),
      ...(accSecret.trim() ? { secret: accSecret.trim() } : {}),
      ...(accThumb.trim() ? { thumb_media_id: accThumb.trim() } : {}),
    }
    const next = platforms.map((p) => {
      if (p.key !== pKey) return p
      const accounts = editing
        ? p.accounts.map((x) => (x.id === editing.accId ? acc : x))
        : [...p.accounts, acc]
      return { ...p, accounts }
    })
    setAddingTo(null)
    setEditing(null)
    save(next, editing ? '✓ 已更新账号' : '✓ 已添加账号')
  }

  function removeAccount(pKey: string, accId: string) {
    const next = platforms.map((p) =>
      p.key !== pKey ? p : { ...p, accounts: p.accounts.filter((a) => a.id !== accId) },
    )
    setConfirmDel(null)
    save(next, '已删除账号')
  }

  function triggerUploadThumb(pKey: string, a: Account) {
    if (!a.appid || !a.secret) {
      setMsg('请先点「编辑」填好 AppID 和 AppSecret，再上传默认封面')
      return
    }
    uploadTarget.current = { pKey, accId: a.id, appid: a.appid, secret: a.secret }
    fileRef.current?.click()
  }

  async function onThumbPicked(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = ''
    const tgt = uploadTarget.current
    if (!file || !tgt) return
    setUploadingFor(tgt.accId)
    setMsg('')
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('appid', tgt.appid)
      fd.append('secret', tgt.secret)
      const res = await fetch(`${API_BASE}/content/upload-thumb`, { method: 'POST', body: fd })
      const d = await res.json()
      if (!d.ok) {
        setMsg(`上传封面失败：${d.error || '未知错误'}`)
        return
      }
      const next = platforms.map((p) =>
        p.key !== tgt.pKey
          ? p
          : { ...p, accounts: p.accounts.map((a) => (a.id === tgt.accId ? { ...a, thumb_media_id: d.media_id } : a)) },
      )
      await save(next, '✓ 默认封面已上传并绑定到该公众号')
    } catch (err) {
      setMsg(`上传封面失败：${err}`)
    } finally {
      setUploadingFor(null)
    }
  }

  function addPlatform() {
    const name = platName.trim()
    const home = platHome.trim()
    if (!name || !home) return
    const next: Platform[] = [...platforms, { key: uid(), name, emoji: '🌐', home, accounts: [] }]
    setShowAddPlat(false)
    setPlatName('')
    setPlatHome('')
    save(next, '✓ 已添加平台')
  }

  const card: React.CSSProperties = {
    background: 'rgba(127,127,127,0.08)',
    border: '1px solid rgba(127,127,127,0.18)',
    borderRadius: 10,
    padding: '12px 14px',
    marginBottom: 12,
  }
  const inputStyle: React.CSSProperties = {
    padding: '7px 10px',
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
    background: 'linear-gradient(135deg,#c4a77d,#8a6c49)',
    color: '#fff',
  }
  const ghostBtn: React.CSSProperties = {
    padding: '6px 12px',
    borderRadius: 8,
    border: '1px solid rgba(127,127,127,0.35)',
    cursor: 'pointer',
    background: 'transparent',
    color: 'inherit',
  }

  const renderAccountForm = (p: Platform) => (
    <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px dashed rgba(127,127,127,0.25)', display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        <input value={accName} onChange={(e) => setAccName(e.target.value)} placeholder="账号名（如：科技观察）"
          style={{ ...inputStyle, flex: 1, minWidth: 160 }} autoFocus />
        <input value={accUrl} onChange={(e) => setAccUrl(e.target.value)} placeholder={`直达链接（留空则打开 ${p.home}）`}
          style={{ ...inputStyle, flex: 2, minWidth: 220 }} />
      </div>
      {p.key === 'wechat_mp' && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          <input value={accAppid} onChange={(e) => setAccAppid(e.target.value)} placeholder="AppID（填后可直推草稿箱）"
            style={{ ...inputStyle, flex: 1, minWidth: 180 }} />
          <input value={accSecret} onChange={(e) => setAccSecret(e.target.value)} placeholder="AppSecret" type="password"
            style={{ ...inputStyle, flex: 1, minWidth: 180 }} />
          <input value={accThumb} onChange={(e) => setAccThumb(e.target.value)} placeholder="默认封面 media_id（也可保存后点上传封面）"
            style={{ ...inputStyle, flex: 1, minWidth: 200 }} />
        </div>
      )}
      <div style={{ display: 'flex', gap: 8 }}>
        <button type="button" style={goBtn} onClick={() => submitAccount(p.key)}>{editing ? '保存修改' : '添加'}</button>
        <button type="button" style={ghostBtn} onClick={() => { setAddingTo(null); setEditing(null) }}>取消</button>
      </div>
    </div>
  )

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, height: '100%' }}>
      <input ref={fileRef} type="file" accept="image/*" style={{ display: 'none' }} onChange={onThumbPicked} />

      <div style={{ flex: 1, overflow: 'auto', padding: 18, maxWidth: 920, width: '100%', margin: '0 auto' }}>
        {msg && (
          <div style={{ ...card, borderColor: 'rgba(196,167,125,0.6)', background: 'rgba(196,167,125,0.12)', fontSize: 13 }}>
            {msg}
          </div>
        )}

        {platforms.map((p) => (
          <div key={p.key} style={card}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              {p.icon
                ? <img src={p.icon} alt={p.name} width={22} height={22} style={{ borderRadius: 5, flexShrink: 0 }} />
                : <span style={{ fontSize: 20 }}>{p.emoji || '🌐'}</span>}
              <span style={{ fontWeight: 600, fontSize: 15 }}>{p.name}</span>
              <span style={{ fontSize: 12, opacity: 0.5 }}>{p.accounts.length} 个账号</span>
              <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
                <button type="button" style={ghostBtn} onClick={() => startAddAccount(p.key)}>+ 添加账号</button>
                <button type="button" style={goBtn} onClick={() => openExternal(p.home)}>打开创作后台 ↗</button>
              </div>
            </div>

            {p.accounts.length > 0 && (
              <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid rgba(127,127,127,0.15)', display: 'flex', flexDirection: 'column', gap: 6 }}>
                {p.accounts.map((a) => {
                  const isEditingThis = editing?.pKey === p.key && editing.accId === a.id
                  const isWechat = p.key === 'wechat_mp'
                  const hasCreds = !!(a.appid && a.secret)
                  return (
                    <div key={a.id}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0', flexWrap: 'wrap' }}>
                        <span style={{ fontWeight: 500 }}>{a.name}</span>
                        {isWechat && (
                          <span style={{ fontSize: 11, padding: '2px 7px', borderRadius: 4, background: hasCreds ? 'rgba(58,157,93,0.15)' : 'rgba(127,127,127,0.15)', color: hasCreds ? '#3a9d5d' : 'inherit', opacity: hasCreds ? 1 : 0.6 }}>
                            {hasCreds ? (a.thumb_media_id ? '✓ 可直推草稿箱' : '已配凭证 · 缺默认封面') : '未配凭证'}
                          </span>
                        )}
                        {a.url && <span style={{ fontSize: 12, opacity: 0.45, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 260 }}>{a.url}</span>}
                        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
                          {isWechat && (
                            <button type="button" style={{ ...ghostBtn, padding: '4px 10px', fontSize: 12 }}
                              disabled={uploadingFor === a.id} onClick={() => triggerUploadThumb(p.key, a)}>
                              {uploadingFor === a.id ? '上传中…' : (a.thumb_media_id ? '换封面' : '上传封面')}
                            </button>
                          )}
                          <button type="button" style={{ ...ghostBtn, padding: '4px 10px', fontSize: 12 }}
                            onClick={() => openExternal(a.url || p.home)}>打开 ↗</button>
                          <button type="button" style={{ ...ghostBtn, padding: '4px 10px', fontSize: 12 }}
                            onClick={() => startEditAccount(p.key, a)}>编辑</button>
                          {confirmDel === a.id ? (
                            <>
                              <button type="button" style={{ ...ghostBtn, padding: '4px 10px', fontSize: 12, color: '#d66', borderColor: '#d66' }}
                                onClick={() => removeAccount(p.key, a.id)}>确定删除</button>
                              <button type="button" style={{ ...ghostBtn, padding: '4px 8px', fontSize: 12 }}
                                onClick={() => setConfirmDel(null)}>取消</button>
                            </>
                          ) : (
                            <button type="button" style={{ ...ghostBtn, padding: '4px 10px', fontSize: 12, opacity: 0.65 }}
                              onClick={() => setConfirmDel(a.id)}>删除</button>
                          )}
                        </div>
                      </div>
                      {isEditingThis && renderAccountForm(p)}
                    </div>
                  )
                })}
              </div>
            )}

            {addingTo === p.key && renderAccountForm(p)}
          </div>
        ))}

        <div style={{ ...card, marginTop: 4 }}>
          {!showAddPlat ? (
            <button type="button" style={ghostBtn} onClick={() => setShowAddPlat(true)}>+ 添加平台</button>
          ) : (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
              <input value={platName} onChange={(e) => setPlatName(e.target.value)} placeholder="平台名（如：头条号）"
                style={{ ...inputStyle, minWidth: 160 }} autoFocus />
              <input value={platHome} onChange={(e) => setPlatHome(e.target.value)} placeholder="创作后台链接 https://..."
                style={{ ...inputStyle, flex: 1, minWidth: 220 }} />
              <button type="button" style={goBtn} onClick={addPlatform}>添加平台</button>
              <button type="button" style={ghostBtn} onClick={() => setShowAddPlat(false)}>取消</button>
            </div>
          )}
        </div>

        {loaded && platforms.length === 0 && (
          <div style={{ opacity: 0.5, fontSize: 13 }}>暂无平台，点「+ 添加平台」开始。</div>
        )}
      </div>
    </div>
  )
}
