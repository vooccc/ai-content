import { useEffect, useRef, useState } from 'react'
import { Loader2 } from 'lucide-react'
import {
  type PageType, type PageLabels, type Palette, isPalette,
  loadBg, composeCard, canvasToBlobPng, downloadBlob,
} from './composeCard'

interface Props {
  bgUrl: string
  type: PageType
  labels: PageLabels
  palette?: string
  onOpen?: (dataUrl: string) => void
  filename?: string
}

export default function CellCard({ bgUrl, type, labels, palette, onOpen, filename }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const [status, setStatus] = useState<'loading' | 'done' | 'error'>('loading')
  const [tries, setTries] = useState(0)
  const MAX_TRIES = 8
  const pal: Palette = isPalette(palette) ? palette : 'warm'

  useEffect(() => {
    let cancelled = false
    setStatus('loading'); setTries(0)
    async function run() {
      try {
        const bg = await loadBg(bgUrl)
        if (cancelled) return
        const canvas = composeCard(bg, type, labels, pal)
        canvasRef.current = canvas
        setStatus('done')
      } catch {
        if (!cancelled) setStatus('error')
      }
    }
    run()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bgUrl, type, palette, labels.title, labels.subtitle, labels.header, (labels.points || []).join('|')])

  useEffect(() => {
    if (status !== 'error' || tries >= MAX_TRIES) return
    const t = setTimeout(() => setTries((n) => n + 1), Math.min(300 * (tries + 1), 1500))
    return () => clearTimeout(t)
  }, [status, tries])

  useEffect(() => {
    if (status !== 'error' || tries >= MAX_TRIES || tries === 0) return
    let cancelled = false
    ;(async () => {
      try {
        const bg = await loadBg(bgUrl)
        if (cancelled) return
        canvasRef.current = composeCard(bg, type, labels, pal)
        setStatus('done')
      } catch { /* retry */ }
    })()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tries])

  async function download() {
    if (!canvasRef.current) return
    const blob = await canvasToBlobPng(canvasRef.current)
    downloadBlob(blob, filename || `xhs_${type}.png`)
  }

  function mountTo(display: HTMLCanvasElement | null) {
    if (!display || !canvasRef.current) return
    display.width = canvasRef.current.width
    display.height = canvasRef.current.height
    const dst = display.getContext('2d')
    if (dst) dst.drawImage(canvasRef.current, 0, 0)
  }

  async function previewOrDownload() {
    if (!canvasRef.current) return
    const dataUrl = canvasRef.current.toDataURL('image/png')
    if (onOpen) onOpen(dataUrl)
    else {
      const a = document.createElement('a')
      a.href = dataUrl
      a.download = filename || `xhs_${type}.png`
      a.click()
    }
  }

  return (
    <>
      {status === 'loading' && (
        <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(127,127,127,0.06)' }}>
          <Loader2 size={18} className="spin" />
        </div>
      )}
      {status === 'error' && tries >= MAX_TRIES && (
        <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 4, color: 'var(--text-color)', opacity: 0.6 }}>
          <span style={{ fontSize: 20 }}>✗</span>
          <span style={{ fontSize: 11 }}>加载失败</span>
        </div>
      )}
      {status === 'done' && (
        <canvas
          ref={mountTo}
          onClick={() => previewOrDownload()}
          style={{ width: '100%', height: '100%', objectFit: 'cover', cursor: 'zoom-in', display: 'block' }}
        />
      )}
      <button type="button" title="下载本页" onClick={(e) => { e.stopPropagation(); download() }}
        style={{ position: 'absolute', bottom: 6, left: 6, zIndex: 2, width: 26, height: 26, padding: 0, borderRadius: 6, border: 'none', cursor: 'pointer', background: 'rgba(0,0,0,0.6)', color: '#fff', fontSize: 12, display: status === 'done' ? 'flex' : 'none', alignItems: 'center', justifyContent: 'center' }}>⬇</button>
    </>
  )
}
