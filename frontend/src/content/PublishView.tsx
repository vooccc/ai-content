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

interface PrimaryAccount {
  id: string
  name: string
  niche: string
  audience: string
  cadence: string
  title_formulas: string[]
  banned_words: string[]
  default_style: string
  default_theme: string
  wechat_account_id: string
  footer_template: string
  sources_config: {
    github_trending?: boolean
    hackernews?: boolean
    bilibili?: boolean
    bilibili_accounts?: string[]
    weibo_hot?: boolean
    wechat_keywords?: string[]
    rss_feeds?: { name: string; url: string }[]
    daily_fetch_enabled?: boolean
    daily_fetch_time?: string
    daily_metrics_sync_enabled?: boolean
    daily_metrics_sync_time?: string
  }
}

export default function PublishView() {
  const [platforms, setPlatforms] = useState<Platform[]>([])
  const [loaded, setLoaded] = useState(false)
  const [msg, setMsg] = useState('')
  const [primaryAcc, setPrimaryAcc] = useState<PrimaryAccount | null>(null)
  const [accOpen, setAccOpen] = useState(false)
  const [niche, setNiche] = useState('')
  const [audience, setAudience] = useState('')
  const [bannedText, setBannedText] = useState('')
  const [footerTpl, setFooterTpl] = useState('')
  const [wxKeywords, setWxKeywords] = useState('')
  const [rssText, setRssText] = useState('')
  const [ghEnabled, setGhEnabled] = useState(true)
  const [hnEnabled, setHnEnabled] = useState(true)
  const [biliEnabled, setBiliEnabled] = useState(true)
  const [weiboEnabled, setWeiboEnabled] = useState(true)
  const [biliAccounts, setBiliAccounts] = useState('')
  const [dailyFetch, setDailyFetch] = useState(true)
  const [fetchTime, setFetchTime] = useState('08:00')
  const [boundWxId, setBoundWxId] = useState('')
  const [modelOpen, setModelOpen] = useState(false)
  const [cfgMode, setCfgMode] = useState<'auto' | 'gateway' | 'custom'>('auto')
  const [activeSource, setActiveSource] = useState('')
  const [currentModel, setCurrentModel] = useState('')
  const [currentFastModel, setCurrentFastModel] = useState('')
  const [textModelOpts, setTextModelOpts] = useState<{ model: string; name: string; provider_name: string }[]>([])
  const [imageModelOpts, setImageModelOpts] = useState<{ model: string; provider_name: string }[]>([])
  const [gwUrl, setGwUrl] = useState('http://127.0.0.1:8000/gateway/v1')
  const [gwToken, setGwToken] = useState('')
  const [gwTokenHint, setGwTokenHint] = useState('')
  const [llmBaseUrl, setLlmBaseUrl] = useState('')
  const [llmApiKey, setLlmApiKey] = useState('')
  const [llmKeyHint, setLlmKeyHint] = useState('')
  const [defTextModel, setDefTextModel] = useState('')
  const [fastTextModel, setFastTextModel] = useState('')
  const [imgBaseUrl, setImgBaseUrl] = useState('')
  const [imgApiKey, setImgApiKey] = useState('')
  const [imgKeyHint, setImgKeyHint] = useState('')
  const [defImgModel, setDefImgModel] = useState('')
  const [tavilyKey, setTavilyKey] = useState('')
  const [tavilyHint, setTavilyHint] = useState('')
  const [testingModel, setTestingModel] = useState(false)
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
    fetch(`${API_BASE}/accounts/primary`)
      .then((r) => r.json())
      .then((d) => {
        if (d.ok && d.account) {
          const a: PrimaryAccount = d.account
          setPrimaryAcc(a)
          setNiche(a.niche || '')
          setAudience(a.audience || '')
          setBannedText((a.banned_words || []).join('、'))
          setFooterTpl(a.footer_template || '')
          setBoundWxId(a.wechat_account_id || '')
          const sc = a.sources_config || {}
          setGhEnabled(sc.github_trending !== false)
          setHnEnabled(sc.hackernews !== false)
          setBiliEnabled(sc.bilibili !== false)
          setWeiboEnabled(sc.weibo_hot !== false)
          setBiliAccounts((sc.bilibili_accounts || []).join(', '))
          setWxKeywords((sc.wechat_keywords || []).join(', '))
          setRssText((sc.rss_feeds || []).map((f) => `${f.name} | ${f.url}`).join('\n'))
          setDailyFetch(sc.daily_fetch_enabled !== false)
          setFetchTime(sc.daily_fetch_time || '08:00')
        }
      })
      .catch(() => {})
    loadModelSettings()
  }, [])

  function applyModelPayload(d: {
    settings?: Record<string, unknown>
    active_source?: string
    current_model?: string
    current_fast_model?: string
    text_models?: { model: string; name: string; provider_name: string }[]
    image_models?: { model: string; provider_name: string }[]
  }) {
    const s = d.settings || {}
    setCfgMode(((s.mode as string) || 'auto') as 'auto' | 'gateway' | 'custom')
    setGwUrl(String(s.gateway_url || 'http://127.0.0.1:8000/gateway/v1'))
    setGwTokenHint(String(s.gateway_token_masked || ''))
    setLlmBaseUrl(String(s.llm_base_url || ''))
    setLlmKeyHint(String(s.llm_api_key_masked || ''))
    setDefTextModel(String(s.default_text_model || ''))
    setFastTextModel(String(s.fast_text_model || ''))
    setImgBaseUrl(String(s.image_base_url || ''))
    setImgKeyHint(String(s.image_api_key_masked || ''))
    setDefImgModel(String(s.default_image_model || ''))
    setTavilyHint(String(s.tavily_api_key_masked || ''))
    setActiveSource(d.active_source || '')
    setCurrentModel(d.current_model || '')
    setCurrentFastModel(d.current_fast_model || '')
    setTextModelOpts(d.text_models || [])
    setImageModelOpts(d.image_models || [])
  }

  async function loadModelSettings() {
    try {
      const res = await fetch(`${API_BASE}/settings/models`)
      const d = await res.json()
      if (d.ok) applyModelPayload(d)
    } catch { /* 静默 */ }
  }

  async function saveModelSettings() {
    try {
      const body: Record<string, unknown> = {
        mode: cfgMode,
        gateway_url: gwUrl.trim(),
        llm_base_url: llmBaseUrl.trim(),
        default_text_model: defTextModel.trim(),
        fast_text_model: fastTextModel.trim(),
        image_base_url: imgBaseUrl.trim(),
        default_image_model: defImgModel.trim(),
      }
      if (gwToken.trim()) body.gateway_token = gwToken.trim()
      if (llmApiKey.trim()) body.llm_api_key = llmApiKey.trim()
      if (imgApiKey.trim()) body.image_api_key = imgApiKey.trim()
      if (tavilyKey.trim()) body.tavily_api_key = tavilyKey.trim()
      const res = await fetch(`${API_BASE}/settings/models`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const d = await res.json()
      if (d.ok) {
        applyModelPayload(d)
        setGwToken(''); setLlmApiKey(''); setImgApiKey(''); setTavilyKey('')
        setMsg('✓ 已保存模型与连接配置')
        setTimeout(() => setMsg(''), 2200)
      }
    } catch (e) {
      setMsg(`✗ 保存模型配置失败：${e}`)
    }
  }

  async function testModelConn() {
    if (testingModel) return
    setTestingModel(true)
    setMsg('正在测试模型连通性…')
    try {
      const res = await fetch(`${API_BASE}/settings/models/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: defTextModel.trim(), prefer_fast: !defTextModel.trim() }),
      })
      const d = await res.json()
      if (res.ok && d.ok) {
        setMsg(`✓ 连通成功：${d.model}（${d.latency_ms}ms，回复：${d.reply}）`)
      } else {
        setMsg(`✗ ${d.error || `HTTP ${res.status}`}`)
      }
    } catch (e) {
      setMsg(`✗ 测试失败：${e}`)
    } finally {
      setTestingModel(false)
    }
  }

  async function savePrimaryAccount() {
    if (!primaryAcc) return
    const banned_words = bannedText.split(/[,，、\n]/).map((s) => s.trim()).filter(Boolean)
    const wechat_keywords = wxKeywords.split(/[,，、\n]/).map((s) => s.trim()).filter(Boolean)
    const bilibili_accounts = biliAccounts.split(/[,，、\n]/).map((s) => s.trim()).filter(Boolean)
    const rss_feeds = rssText.split('\n').map((ln) => ln.trim()).filter(Boolean).map((ln) => {
      const parts = ln.split('|').map((s) => s.trim())
      return parts.length >= 2 ? { name: parts[0], url: parts[1] } : { name: parts[0], url: parts[0] }
    })
    try {
      const res = await fetch(`${API_BASE}/accounts/primary`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          niche: niche.trim(),
          audience: audience.trim(),
          banned_words,
          footer_template: footerTpl.trim(),
          wechat_account_id: boundWxId,
          sources_config: {
            ...(primaryAcc.sources_config || {}),
            github_trending: ghEnabled,
            hackernews: hnEnabled,
            bilibili: biliEnabled,
            weibo_hot: weiboEnabled,
            bilibili_accounts,
            wechat_keywords,
            rss_feeds,
            daily_fetch_enabled: dailyFetch,
            daily_fetch_time: fetchTime || '08:00',
          },
        }),
      })
      const d = await res.json()
      if (d.ok) {
        setPrimaryAcc(d.account)
        setAccOpen(false)
        setMsg('✓ 已保存主号定位与抓取配置')
        setTimeout(() => setMsg(''), 2200)
      }
    } catch (e) {
      setMsg(`保存失败：${e}`)
    }
  }

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

      <div style={{ flex: 1, overflow: 'auto', padding: '18px 24px', width: '100%' }}>
        {msg && (
          <div style={{ ...card, borderColor: 'rgba(196,167,125,0.6)', background: 'rgba(196,167,125,0.12)', fontSize: 13 }}>
            {msg}
          </div>
        )}

        <div style={{ ...card, borderColor: 'rgba(196,167,125,0.4)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <span style={{ fontWeight: 600, fontSize: 15 }}>🤖 模型与连接配置</span>
            <span style={{ fontSize: 12, opacity: 0.7 }}>
              {activeSource === 'gateway' ? '柳如烟 Gateway'
                : activeSource === 'custom' ? '独立自定义 API'
                : activeSource === 'liuruyan_models' ? '自动复用柳如烟模型'
                : activeSource === 'env' ? '环境变量'
                : '未配置'}
            </span>
            {currentModel && (
              <span style={{ fontSize: 12, opacity: 0.7 }}>
                · 写作：{currentModel}{(() => { const p = textModelOpts.find((m) => m.model === currentModel)?.provider_name; return p ? `（${p}）` : '' })()}
                {currentFastModel ? ` · 翻译/快讯：${currentFastModel}${(() => { const p = textModelOpts.find((m) => m.model === currentFastModel)?.provider_name; return p ? `（${p}）` : '' })()}` : ''}
              </span>
            )}
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
              <button type="button" style={ghostBtn} disabled={testingModel} onClick={testModelConn}>
                {testingModel ? '测试中…' : '⚡ 测试连通'}
              </button>
              <button type="button" style={ghostBtn} onClick={() => setModelOpen((v) => !v)}>
                {modelOpen ? '收起' : '配置模型'}
              </button>
            </div>
          </div>
          {modelOpen && (
            <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid rgba(127,127,127,0.15)', display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', fontSize: 13 }}>
                <span style={{ opacity: 0.7 }}>接入模式：</span>
                {([
                  ['auto', '自动（优先自定义，回退柳如烟）'],
                  ['gateway', '柳如烟 Gateway'],
                  ['custom', '独立自定义 API'],
                ] as const).map(([m, label]) => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => setCfgMode(m)}
                    style={{
                      ...ghostBtn,
                      padding: '4px 10px',
                      fontSize: 12.5,
                      borderColor: cfgMode === m ? 'rgba(196,167,125,0.9)' : 'rgba(127,127,127,0.3)',
                      background: cfgMode === m ? 'rgba(196,167,125,0.16)' : 'transparent',
                    }}
                  >
                    {label}
                  </button>
                ))}
              </div>

              {cfgMode === 'gateway' && (
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <input value={gwUrl} onChange={(e) => setGwUrl(e.target.value)} placeholder="Gateway URL（如 http://127.0.0.1:8000/gateway/v1）" style={{ ...inputStyle, flex: 2, minWidth: 220 }} />
                  <input value={gwToken} onChange={(e) => setGwToken(e.target.value)} type="password" placeholder={gwTokenHint ? `Gateway Token（已配：${gwTokenHint}）` : 'Gateway Token'} style={{ ...inputStyle, flex: 1, minWidth: 180 }} />
                </div>
              )}

              {cfgMode !== 'gateway' && (
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <input value={llmBaseUrl} onChange={(e) => setLlmBaseUrl(e.target.value)} placeholder="自定义 LLM Base URL（如 https://api.deepseek.com/v1，留空则复用柳如烟）" style={{ ...inputStyle, flex: 2, minWidth: 240 }} />
                  <input value={llmApiKey} onChange={(e) => setLlmApiKey(e.target.value)} type="password" placeholder={llmKeyHint ? `API Key（已配：${llmKeyHint}）` : 'API Key（留空则复用柳如烟）'} style={{ ...inputStyle, flex: 1, minWidth: 180 }} />
                </div>
              )}

              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {(() => {
                  const effWrite = defTextModel || currentModel
                  const effWriteProv = textModelOpts.find((m) => m.model === effWrite)?.provider_name || ''
                  const effFast = fastTextModel || currentFastModel
                  const effFastProv = textModelOpts.find((m) => m.model === effFast)?.provider_name || ''
                  return (
                    <>
                      <div style={{ flex: 1, minWidth: 220, display: 'flex', flexDirection: 'column', gap: 4 }}>
                        <span style={{ fontSize: 12, opacity: 0.7 }}>默认写作模型（大纲 / 撰稿 / 润色）</span>
                        <select
                          value={defTextModel}
                          onChange={(e) => setDefTextModel(e.target.value)}
                          style={{ ...inputStyle, colorScheme: 'light dark' }}
                        >
                          <option value="">
                            自动（✓ 当前：{currentModel || '跟随柳如烟'}{effWriteProv && !defTextModel ? ` · ${effWriteProv}` : ''}）
                          </option>
                          {defTextModel && !textModelOpts.some((m) => m.model === defTextModel) && (
                            <option value={defTextModel}>✓ [当前] {defTextModel}（自定义）</option>
                          )}
                          {textModelOpts.map((m) => {
                            const isCur = m.model === effWrite
                            return (
                              <option key={m.model} value={m.model}>
                                {isCur ? '✓ [当前] ' : ''}{m.model}（{m.provider_name}）
                              </option>
                            )
                          })}
                        </select>
                        {effWrite && (
                          <span style={{ fontSize: 11.5, opacity: 0.6 }}>
                            当前生效：{effWriteProv ? `${effWriteProv} · ` : ''}{effWrite}
                          </span>
                        )}
                      </div>
                      <div style={{ flex: 1, minWidth: 220, display: 'flex', flexDirection: 'column', gap: 4 }}>
                        <span style={{ fontSize: 12, opacity: 0.7 }}>翻译 / 快讯 / 选题筛选模型</span>
                        <select
                          value={fastTextModel}
                          onChange={(e) => setFastTextModel(e.target.value)}
                          style={{ ...inputStyle, colorScheme: 'light dark' }}
                        >
                          <option value="">
                            自动（✓ 当前：{currentFastModel || '自动挑快模型'}{effFastProv && !fastTextModel ? ` · ${effFastProv}` : ''}）
                          </option>
                          {fastTextModel && !textModelOpts.some((m) => m.model === fastTextModel) && (
                            <option value={fastTextModel}>✓ [当前] {fastTextModel}（自定义）</option>
                          )}
                          {textModelOpts.map((m) => {
                            const isCur = m.model === effFast
                            return (
                              <option key={m.model} value={m.model}>
                                {isCur ? '✓ [当前] ' : ''}{m.model}（{m.provider_name}）
                              </option>
                            )
                          })}
                        </select>
                        {effFast && (
                          <span style={{ fontSize: 11.5, opacity: 0.6 }}>
                            当前生效：{effFastProv ? `${effFastProv} · ` : ''}{effFast}
                          </span>
                        )}
                      </div>
                    </>
                  )
                })()}
                <div style={{ flex: 1, minWidth: 200, display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span style={{ fontSize: 12, opacity: 0.7 }}>默认生图模型</span>
                  <select
                    value={defImgModel}
                    onChange={(e) => setDefImgModel(e.target.value)}
                    style={{ ...inputStyle, colorScheme: 'light dark' }}
                  >
                    <option value="">自动（按工作台所选）</option>
                    {defImgModel && !imageModelOpts.some((m) => m.model === defImgModel) && (
                      <option value={defImgModel}>✓ [当前] {defImgModel}（自定义）</option>
                    )}
                    {imageModelOpts.map((m) => (
                      <option key={m.model} value={m.model}>
                        {m.model === defImgModel ? '✓ [当前] ' : ''}{m.model}（{m.provider_name}）
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <input value={imgBaseUrl} onChange={(e) => setImgBaseUrl(e.target.value)} placeholder="独立生图 Base URL（可选，不填则复用上方/柳如烟）" style={{ ...inputStyle, flex: 2, minWidth: 220 }} />
                <input value={imgApiKey} onChange={(e) => setImgApiKey(e.target.value)} type="password" placeholder={imgKeyHint ? `生图 Key（已配：${imgKeyHint}）` : '生图 API Key（可选）'} style={{ ...inputStyle, flex: 1, minWidth: 160 }} />
                <input value={tavilyKey} onChange={(e) => setTavilyKey(e.target.value)} type="password" placeholder={tavilyHint ? `Tavily Key（已配：${tavilyHint}）` : 'Tavily 搜索 Key（可选）'} style={{ ...inputStyle, flex: 1, minWidth: 160 }} />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                <button type="button" style={goBtn} onClick={saveModelSettings}>保存模型配置</button>
              </div>
            </div>
          )}
        </div>

        {primaryAcc && (
          <div style={{ ...card, borderColor: 'rgba(196,167,125,0.4)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <span style={{ fontWeight: 600, fontSize: 15 }}>🎯 主号定位与抓取设置</span>
              <span style={{ fontSize: 12, opacity: 0.7 }}>{primaryAcc.niche}</span>
              <span style={{ fontSize: 12, opacity: 0.55 }}>
                · {dailyFetch ? `每日 ${fetchTime} 自动抓选题` : '手动抓取'}
              </span>
              <button type="button" style={{ ...ghostBtn, marginLeft: 'auto' }} onClick={() => setAccOpen((v) => !v)}>
                {accOpen ? '收起' : '编辑定位与抓取源'}
              </button>
            </div>
            {accOpen && (
              <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid rgba(127,127,127,0.15)', display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <input value={niche} onChange={(e) => setNiche(e.target.value)} placeholder="赛道定位" style={{ ...inputStyle, flex: 1, minWidth: 220 }} />
                  <select value={boundWxId} onChange={(e) => setBoundWxId(e.target.value)} style={{ ...inputStyle, minWidth: 180, background: 'var(--bg-card)' }}>
                    <option value="">默认使用首个公众号凭证</option>
                    {(platforms.find((p) => p.key === 'wechat_mp')?.accounts || []).map((a) => (
                      <option key={a.id} value={a.id}>主号：{a.name}</option>
                    ))}
                  </select>
                </div>
                <input value={audience} onChange={(e) => setAudience(e.target.value)} placeholder="目标读者" style={inputStyle} />
                <input value={bannedText} onChange={(e) => setBannedText(e.target.value)} placeholder="去 AI 味禁用词（顿号或逗号分隔）" style={inputStyle} />
                <input value={footerTpl} onChange={(e) => setFooterTpl(e.target.value)} placeholder="文末低门槛互动引导" style={inputStyle} />
                <input value={wxKeywords} onChange={(e) => setWxKeywords(e.target.value)} placeholder="抓取关键词（逗号分隔，自动扩展中英文变体）" style={inputStyle} />
                <input value={biliAccounts} onChange={(e) => setBiliAccounts(e.target.value)} placeholder="对标 B站 UP 主（可选，逗号分隔昵称或 UID）" style={inputStyle} />
                <textarea value={rssText} onChange={(e) => setRssText(e.target.value)} placeholder="RSS 源（每行：名称 | URL）" style={{ ...inputStyle, minHeight: 72, resize: 'vertical', fontSize: 12.5 }} />
                <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'center', fontSize: 13 }}>
                  <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                    <input type="checkbox" checked={ghEnabled} onChange={(e) => setGhEnabled(e.target.checked)} />
                    GitHub Trending
                  </label>
                  <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                    <input type="checkbox" checked={hnEnabled} onChange={(e) => setHnEnabled(e.target.checked)} />
                    Hacker News
                  </label>
                  <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                    <input type="checkbox" checked={biliEnabled} onChange={(e) => setBiliEnabled(e.target.checked)} />
                    B站视频
                  </label>
                  <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                    <input type="checkbox" checked={weiboEnabled} onChange={(e) => setWeiboEnabled(e.target.checked)} />
                    微博热搜
                  </label>
                  <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                    <input type="checkbox" checked={dailyFetch} onChange={(e) => setDailyFetch(e.target.checked)} />
                    每日自动抓选题
                  </label>
                  <input type="time" value={fetchTime} onChange={(e) => setFetchTime(e.target.value)} style={{ ...inputStyle, padding: '4px 8px' }} />
                  <button type="button" style={{ ...goBtn, marginLeft: 'auto' }} onClick={savePrimaryAccount}>保存设置</button>
                </div>
              </div>
            )}
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
