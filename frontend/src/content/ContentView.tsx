import { useState } from 'react'
import { Moon, Sun } from 'lucide-react'
import StudioShell from './studio/StudioShell'
import PublishView from './PublishView'

interface ContentViewProps {
  theme?: 'dark' | 'light'
  onToggleTheme?: () => void
}

export default function ContentView({ theme = 'dark', onToggleTheme }: ContentViewProps) {
  const [tab, setTab] = useState<'studio' | 'publish'>('studio')
  const tabBtn = (active: boolean): React.CSSProperties => ({
    padding: '6px 14px', borderRadius: 8, cursor: 'pointer', fontSize: 13, fontWeight: active ? 600 : 400,
    border: '1px solid ' + (active ? 'rgba(196,167,125,0.8)' : 'rgba(127,127,127,0.25)'),
    background: active ? 'rgba(196,167,125,0.14)' : 'transparent', color: 'inherit',
  })
  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, height: '100%' }}>
      <div style={{ padding: '10px 18px', borderBottom: '1px solid rgba(127,127,127,0.18)', display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{ fontSize: 15, fontWeight: 600, marginRight: 8 }}>AI Content Studio</div>
        <button type="button" style={tabBtn(tab === 'studio')} onClick={() => setTab('studio')}>✍️ 创作工作台</button>
        <button type="button" style={tabBtn(tab === 'publish')} onClick={() => setTab('publish')}>📤 多平台发布</button>
        {onToggleTheme && (
          <button
            type="button"
            onClick={onToggleTheme}
            title={theme === 'dark' ? '切换到浅色' : '切换到深色'}
            style={{
              marginLeft: 'auto', padding: '6px 10px', borderRadius: 8, cursor: 'pointer',
              border: '1px solid rgba(127,127,127,0.25)', background: 'transparent', color: 'inherit',
              display: 'inline-flex', alignItems: 'center',
            }}
          >
            {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
          </button>
        )}
      </div>
      <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
        {tab === 'studio' ? <StudioShell /> : <PublishView />}
      </div>
    </div>
  )
}
