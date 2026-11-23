import { useState } from 'react'
import { Moon, PanelLeftClose, PanelLeftOpen, Sun } from 'lucide-react'
import TopicsView from './TopicsView'
import IntelView from './IntelView'
import StudioShell from './studio/StudioShell'
import PublishView from './PublishView'
import MetricsView from './MetricsView'

interface ContentViewProps {
  theme?: 'dark' | 'light'
  onToggleTheme?: () => void
}

type NavTab = 'intel' | 'topics' | 'studio' | 'publish' | 'metrics'

const NAV_ITEMS: { key: NavTab; icon: string; label: string }[] = [
  { key: 'intel', icon: '⚡', label: '实时快讯' },
  { key: 'topics', icon: '💡', label: '选题池' },
  { key: 'studio', icon: '✍️', label: '创作台' },
  { key: 'publish', icon: '📤', label: '账号与设置' },
  { key: 'metrics', icon: '📊', label: '数据复盘' },
]

export default function ContentView({ theme = 'dark', onToggleTheme }: ContentViewProps) {
  const [tab, setTab] = useState<NavTab>('topics')
  const [openProjectId, setOpenProjectId] = useState<string | undefined>(undefined)
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem('aiContent.navCollapsed') === '1'
    } catch {
      return false
    }
  })

  function toggleCollapsed() {
    setCollapsed((prev) => {
      const next = !prev
      try {
        localStorage.setItem('aiContent.navCollapsed', next ? '1' : '0')
      } catch {
        // ignore storage errors
      }
      return next
    })
  }

  function handleOpenProject(pid: string) {
    setOpenProjectId(pid)
    setTab('studio')
  }

  return (
    <div style={{ flex: 1, display: 'flex', minWidth: 0, height: '100%' }}>
      <aside
        style={{
          width: collapsed ? 54 : 164,
          flexShrink: 0,
          borderRight: '1px solid rgba(127,127,127,0.18)',
          display: 'flex',
          flexDirection: 'column',
          padding: collapsed ? '12px 6px' : '12px 10px',
          gap: 6,
          transition: 'width 0.15s ease',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: collapsed ? 'center' : 'space-between',
            padding: collapsed ? '2px 0 8px' : '2px 6px 8px',
            borderBottom: '1px solid rgba(127,127,127,0.12)',
            marginBottom: 4,
          }}
        >
          {!collapsed && (
            <span style={{ fontSize: 13.5, fontWeight: 700, letterSpacing: 0.2, whiteSpace: 'nowrap' }}>
              AI Content
            </span>
          )}
          <button
            type="button"
            onClick={toggleCollapsed}
            title={collapsed ? '展开侧边栏' : '收起侧边栏'}
            style={{
              padding: 5,
              borderRadius: 6,
              border: 'none',
              background: 'transparent',
              color: 'inherit',
              opacity: 0.65,
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            {collapsed ? <PanelLeftOpen size={15} /> : <PanelLeftClose size={15} />}
          </button>
        </div>

        <nav style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1 }}>
          {NAV_ITEMS.map((item) => {
            const active = tab === item.key
            return (
              <button
                key={item.key}
                type="button"
                title={collapsed ? item.label : undefined}
                onClick={() => setTab(item.key)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: collapsed ? 'center' : 'flex-start',
                  gap: 9,
                  padding: collapsed ? '9px 0' : '8px 10px',
                  borderRadius: 8,
                  cursor: 'pointer',
                  fontSize: 13,
                  fontWeight: active ? 600 : 400,
                  border: active
                    ? '1px solid rgba(196,167,125,0.75)'
                    : '1px solid transparent',
                  background: active ? 'rgba(196,167,125,0.14)' : 'transparent',
                  color: 'inherit',
                  whiteSpace: 'nowrap',
                  textAlign: 'left',
                }}
              >
                <span style={{ fontSize: 15, lineHeight: 1 }}>{item.icon}</span>
                {!collapsed && <span>{item.label}</span>}
              </button>
            )
          })}
        </nav>

        {onToggleTheme && (
          <button
            type="button"
            onClick={onToggleTheme}
            title={theme === 'dark' ? '切换到浅色' : '切换到深色'}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: collapsed ? 'center' : 'flex-start',
              gap: 8,
              padding: collapsed ? '8px 0' : '7px 10px',
              borderRadius: 8,
              cursor: 'pointer',
              fontSize: 12.5,
              border: '1px solid rgba(127,127,127,0.2)',
              background: 'transparent',
              color: 'inherit',
              opacity: 0.8,
              whiteSpace: 'nowrap',
            }}
          >
            {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
            {!collapsed && <span>{theme === 'dark' ? '浅色模式' : '深色模式'}</span>}
          </button>
        )}
      </aside>

      <main style={{ flex: 1, minWidth: 0, minHeight: 0, display: 'flex' }}>
        {tab === 'intel' && <IntelView onOpenProject={handleOpenProject} onGoTopics={() => setTab('topics')} />}
        {tab === 'topics' && <TopicsView onOpenProject={handleOpenProject} />}
        {tab === 'studio' && (
          <StudioShell
            openProjectId={openProjectId}
            onConsumedOpenProject={() => setOpenProjectId(undefined)}
          />
        )}
        {tab === 'publish' && <PublishView />}
        {tab === 'metrics' && <MetricsView />}
      </main>
    </div>
  )
}
