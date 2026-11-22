export type PageType = 'cover' | 'content' | 'summary'
export interface PageLabels {
  title: string
  subtitle: string
  points: string[]
  header: string
}
export type Palette = 'warm' | 'fresh' | 'elegant' | 'vibrant'

const CW = 1080
const CH = 1440
const FONT_STACK = '"PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif'
const META_PREFIX_RE = /^\s*(?:[-*•·]|\d+[).、]|#+)?\s*(?:背景|画面|画面描述|主视觉|配图|插画|布局|留白|风格|色调|场景|元素|装饰|用户口吻|口吻)\s*[：:]/i
const LABEL_PREFIX_RE = /^\s*(?:[-*•·]|\d+[).、]|#+)?\s*(?:大标题|标题|主标题|副标题|小标题|正文|文案|页眉|页面标题|要点\s*\d*|重点\s*\d*|结论|总结|互动|互动引导|CTA|背景|画面|画面描述|主视觉|配图|插画|布局|留白|风格|色调|用户口吻|口吻|场景|元素|装饰)\s*[：:]\s*/i
const BULLET_RE = /^\s*(?:[-*•·]|\d+[).、]|#+)\s*/

type Theme = {
  bg: string
  title: string
  text: string
  muted: string
  soft: string
  accent: string
  accent2: string
  card: string
  cardStrong: string
  stroke: string
  dark: string
}

const PALETTE_THEME: Record<Palette, Theme> = {
  warm: {
    bg: '#f8efe5', title: '#22140d', text: '#35251b', muted: '#806758', soft: '#fff7ef',
    accent: '#d78343', accent2: '#f2c59f', card: 'rgba(255,250,245,0.82)', cardStrong: 'rgba(255,255,255,0.92)', stroke: 'rgba(214,147,86,0.28)', dark: 'rgba(50,31,18,0.76)',
  },
  fresh: {
    bg: '#edf8f7', title: '#0e3840', text: '#173f48', muted: '#5f7e85', soft: '#f2fffd',
    accent: '#25a8bf', accent2: '#9be1dc', card: 'rgba(248,255,254,0.82)', cardStrong: 'rgba(255,255,255,0.92)', stroke: 'rgba(37,168,191,0.24)', dark: 'rgba(15,56,64,0.74)',
  },
  elegant: {
    bg: '#f2eff5', title: '#2b2430', text: '#342c39', muted: '#756b7e', soft: '#fbf8ff',
    accent: '#9a7b5c', accent2: '#d9c6ad', card: 'rgba(252,250,255,0.84)', cardStrong: 'rgba(255,255,255,0.93)', stroke: 'rgba(154,123,92,0.25)', dark: 'rgba(42,35,48,0.76)',
  },
  vibrant: {
    bg: '#fff0f5', title: '#271019', text: '#351924', muted: '#835c6c', soft: '#fff8fb',
    accent: '#ff5d8f', accent2: '#ffc0d4', card: 'rgba(255,250,252,0.83)', cardStrong: 'rgba(255,255,255,0.92)', stroke: 'rgba(255,93,143,0.24)', dark: 'rgba(47,17,30,0.76)',
  },
}

export function isPalette(s: string | undefined | null): s is Palette {
  return !!s && ['warm', 'fresh', 'elegant', 'vibrant'].includes(s)
}

export function loadBg(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error('背景图加载失败'))
    img.src = src
  })
}

function theme(p: Palette): Theme {
  return PALETTE_THEME[p] || PALETTE_THEME.warm
}

function clean(s: string | undefined | null, fallback = ''): string {
  const raw = (s || '').trim()
  if (META_PREFIX_RE.test(raw)) return fallback
  const text = raw
    .replace(BULLET_RE, '')
    .replace(LABEL_PREFIX_RE, '')
    .replace(/[\t\r\n]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^[-—:：。\s]+|[-—:：。\s]+$/g, '')
  return text || fallback
}

function limitText(s: string, max = 34): string {
  const arr = Array.from(clean(s))
  return arr.length > max ? `${arr.slice(0, max - 1).join('')}…` : arr.join('')
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  const radius = Math.min(r, w / 2, h / 2)
  ctx.beginPath()
  ctx.moveTo(x + radius, y)
  ctx.arcTo(x + w, y, x + w, y + h, radius)
  ctx.arcTo(x + w, y + h, x, y + h, radius)
  ctx.arcTo(x, y + h, x, y, radius)
  ctx.arcTo(x, y, x + w, y, radius)
  ctx.closePath()
}

function drawCover(ctx: CanvasRenderingContext2D, img: HTMLImageElement, w: number, h: number) {
  const ir = img.width / img.height
  const cr = w / h
  let dw = w
  let dh = h
  let dx = 0
  let dy = 0
  if (ir > cr) {
    dh = h
    dw = h * ir
    dx = (w - dw) / 2
  } else {
    dw = w
    dh = w / ir
    dy = (h - dh) / 2
  }
  ctx.drawImage(img, dx, dy, dw, dh)
}

function panel(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number, fill: string | CanvasGradient, stroke?: string, shadow = true) {
  ctx.save()
  if (shadow) {
    ctx.shadowColor = 'rgba(36,22,12,0.16)'
    ctx.shadowBlur = 24
    ctx.shadowOffsetY = 10
  }
  ctx.fillStyle = fill
  roundRect(ctx, x, y, w, h, r)
  ctx.fill()
  ctx.shadowColor = 'transparent'
  if (stroke) {
    ctx.strokeStyle = stroke
    ctx.lineWidth = 2
    ctx.stroke()
  }
  ctx.restore()
}

function gradientPanel(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number, th: Theme) {
  const g = ctx.createLinearGradient(x, y, x + w, y + h)
  g.addColorStop(0, th.cardStrong)
  g.addColorStop(1, th.card)
  panel(ctx, x, y, w, h, r, g, th.stroke)
}

function fitLine(ctx: CanvasRenderingContext2D, text: string, base: number, maxWidth: number, weight = 800, min = 20): number {
  let size = base
  while (size > min) {
    ctx.font = `${weight} ${size}px ${FONT_STACK}`
    if (ctx.measureText(text).width <= maxWidth) break
    size -= 2
  }
  return size
}

function wrapText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number, maxLines = 4): string[] {
  const chars = Array.from(clean(text))
  const lines: string[] = []
  let cur = ''
  for (const ch of chars) {
    const next = cur + ch
    if (ctx.measureText(next).width > maxWidth && cur) {
      lines.push(cur)
      cur = ch
      if (lines.length >= maxLines) break
    } else {
      cur = next
    }
  }
  if (cur && lines.length < maxLines) lines.push(cur)
  if (lines.length === maxLines && chars.join('').length > lines.join('').length) {
    let last = lines[maxLines - 1]
    while (last.length > 1 && ctx.measureText(`${last}…`).width > maxWidth) last = last.slice(0, -1)
    lines[maxLines - 1] = `${last}…`
  }
  return lines
}

function drawWrapped(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  maxWidth: number,
  font: number,
  color: string,
  weight = 700,
  maxLines = 3,
  lineHeight = 1.25,
): number {
  ctx.save()
  ctx.font = `${weight} ${font}px ${FONT_STACK}`
  ctx.fillStyle = color
  ctx.textAlign = 'left'
  ctx.textBaseline = 'top'
  const lines = wrapText(ctx, text, maxWidth, maxLines)
  const lh = Math.round(font * lineHeight)
  lines.forEach((line, i) => ctx.fillText(line, x, y + i * lh))
  ctx.restore()
  return y + lines.length * lh
}

function drawTitle(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, maxWidth: number, base: number, color: string, maxLines = 3): number {
  const safeText = clean(text, '小红书图文')
  let size = base
  let lines: string[] = []
  while (size >= 34) {
    ctx.font = `900 ${size}px ${FONT_STACK}`
    lines = wrapText(ctx, safeText, maxWidth, maxLines)
    const overflow = lines.length === maxLines && !safeText.startsWith(lines.join('').replace(/…$/, ''))
    if (!overflow || size <= 42) break
    size -= 2
  }
  const lh = Math.round(size * 1.08)
  ctx.save()
  ctx.font = `900 ${size}px ${FONT_STACK}`
  ctx.fillStyle = color
  ctx.textAlign = 'left'
  ctx.textBaseline = 'top'
  ctx.shadowColor = 'rgba(255,255,255,0.95)'
  ctx.shadowBlur = 12
  lines.forEach((line, i) => ctx.fillText(line, x, y + i * lh))
  ctx.restore()
  return y + lines.length * lh
}

function pill(ctx: CanvasRenderingContext2D, x: number, y: number, text: string, th: Theme, opts?: { fill?: string; color?: string; font?: number; padX?: number; height?: number }) {
  const font = opts?.font || 24
  const height = opts?.height || 46
  const padX = opts?.padX || 22
  ctx.save()
  ctx.font = `800 ${font}px ${FONT_STACK}`
  const w = Math.max(128, Math.ceil(ctx.measureText(text).width + padX * 2))
  ctx.fillStyle = opts?.fill || 'rgba(255,255,255,0.86)'
  roundRect(ctx, x, y, w, height, height / 2)
  ctx.fill()
  ctx.strokeStyle = th.stroke
  ctx.lineWidth = 1.5
  ctx.stroke()
  ctx.fillStyle = opts?.color || th.accent
  ctx.textBaseline = 'middle'
  ctx.fillText(text, x + padX, y + height / 2 + 1)
  ctx.restore()
  return w
}

function drawDotPattern(ctx: CanvasRenderingContext2D, th: Theme) {
  ctx.save()
  ctx.globalAlpha = 0.42
  const points = [
    [94, 86, 26], [152, 126, 10], [962, 132, 32], [895, 215, 14],
    [116, 1240, 34], [185, 1305, 12], [940, 1216, 22], [988, 1284, 12],
  ]
  points.forEach(([x, y, r], i) => {
    ctx.fillStyle = i % 2 ? th.accent2 : th.accent
    ctx.beginPath()
    ctx.arc(x, y, r, 0, Math.PI * 2)
    ctx.fill()
  })
  ctx.restore()
}

function drawBase(ctx: CanvasRenderingContext2D, bg: HTMLImageElement, th: Theme) {
  ctx.fillStyle = th.bg
  ctx.fillRect(0, 0, CW, CH)

  ctx.save()
  ctx.globalAlpha = 0.5
  ctx.filter = 'blur(4px) saturate(0.82) contrast(0.9)'
  drawCover(ctx, bg, CW, CH)
  ctx.restore()

  const veil = ctx.createLinearGradient(0, 0, 0, CH)
  veil.addColorStop(0, 'rgba(255,255,255,0.62)')
  veil.addColorStop(0.36, 'rgba(255,255,255,0.70)')
  veil.addColorStop(0.72, 'rgba(255,255,255,0.80)')
  veil.addColorStop(1, 'rgba(255,255,255,0.88)')
  ctx.fillStyle = veil
  ctx.fillRect(0, 0, CW, CH)

  const glow = ctx.createRadialGradient(860, 190, 40, 860, 190, 520)
  glow.addColorStop(0, `${th.accent2}88`)
  glow.addColorStop(1, 'rgba(255,255,255,0)')
  ctx.fillStyle = glow
  ctx.fillRect(0, 0, CW, CH)

  drawDotPattern(ctx, th)
  ctx.save()
  ctx.strokeStyle = 'rgba(255,255,255,0.58)'
  ctx.lineWidth = 3
  roundRect(ctx, 38, 38, CW - 76, CH - 76, 38)
  ctx.stroke()
  ctx.restore()
}

function drawTagRow(ctx: CanvasRenderingContext2D, x: number, y: number, tags: string[], th: Theme) {
  let cur = x
  tags.filter(Boolean).slice(0, 3).forEach((tag) => {
    const w = pill(ctx, cur, y, tag, th, { fill: 'rgba(255,255,255,0.72)', color: th.muted, font: 21, height: 40, padX: 18 })
    cur += w + 12
  })
}

function splitPoint(point: string): { title: string; desc: string } {
  const text = clean(point)
  const parts = text.split(/[。.!！?？；;]/).map((s) => clean(s)).filter(Boolean)
  if (parts.length >= 2) return { title: limitText(parts[0], 16), desc: limitText(parts.slice(1).join('，'), 46) }
  const chars = Array.from(text)
  if (chars.length > 18) return { title: chars.slice(0, 14).join(''), desc: chars.slice(14, 58).join('') }
  return { title: limitText(text, 16), desc: '' }
}

function splitInlinePoints(text: string): string[] {
  const normalized = clean(text).replace(/\|/g, '｜')
  const marked = normalized.replace(/(?!^)(?=(?:要点|重点)\s*\d+\s*[：:])/g, '\n')
  return marked
    .split(/[｜\n]+/)
    .map((s) => clean(s))
    .filter(Boolean)
}

function ensurePoints(labels: PageLabels): string[] {
  const points = (labels.points || []).flatMap((p) => splitInlinePoints(p)).filter(Boolean)
  if (points.length) return points
  return [labels.title, labels.subtitle, labels.header].flatMap((p) => splitInlinePoints(p)).filter(Boolean)
}

function drawCoverPage(ctx: CanvasRenderingContext2D, labels: PageLabels, th: Theme) {
  const pad = 86
  pill(ctx, pad, 82, clean(labels.header, '小红书图文'), th, { font: 24, height: 48 })

  panel(ctx, pad, 192, 908, 612, 38, 'rgba(255,255,255,0.74)', th.stroke)
  const titleBottom = drawTitle(ctx, labels.title, pad + 48, 246, 798, 78, th.title, 3)
  ctx.fillStyle = th.accent
  roundRect(ctx, pad + 48, titleBottom + 28, 148, 10, 5)
  ctx.fill()

  if (clean(labels.subtitle)) {
    drawWrapped(ctx, labels.subtitle, pad + 48, titleBottom + 64, 784, 32, th.text, 700, 3, 1.35)
  }

  drawTagRow(ctx, pad + 48, 704, ['收藏备用', '一图读懂', '清晰排版'], th)

  panel(ctx, pad, 1110, 628, 126, 30, th.dark, undefined, true)
  drawWrapped(ctx, '先看结论，再看细节', pad + 34, 1144, 560, 34, '#fff', 800, 1)
  drawWrapped(ctx, '适合收藏后反复对照', pad + 34, 1192, 560, 22, 'rgba(255,255,255,0.78)', 600, 1)
}

function drawContentCard(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, idx: number, text: string, th: Theme) {
  const item = splitPoint(text || `要点 ${idx + 1}`)
  gradientPanel(ctx, x, y, w, h, 32, th)

  ctx.save()
  ctx.fillStyle = th.accent
  ctx.beginPath()
  ctx.arc(x + 58, y + 58, 30, 0, Math.PI * 2)
  ctx.fill()
  ctx.fillStyle = '#fff'
  ctx.font = `900 26px ${FONT_STACK}`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(String(idx + 1).padStart(2, '0'), x + 58, y + 59)
  ctx.restore()

  const title = item.title || `要点 ${idx + 1}`
  const titleSize = fitLine(ctx, title, 34, w - 126, 900, 24)
  ctx.save()
  ctx.font = `900 ${titleSize}px ${FONT_STACK}`
  ctx.fillStyle = th.title
  ctx.textBaseline = 'top'
  ctx.fillText(title, x + 104, y + 34)
  ctx.restore()

  const desc = item.desc || limitText(text, 50)
  drawWrapped(ctx, desc, x + 34, y + 126, w - 68, h > 280 ? 27 : 24, th.text, 650, h > 280 ? 4 : 3, 1.42)

  ctx.save()
  ctx.fillStyle = `${th.accent2}88`
  roundRect(ctx, x + 34, y + h - 42, w - 68, 8, 4)
  ctx.fill()
  ctx.restore()
}

function drawContentPage(ctx: CanvasRenderingContext2D, labels: PageLabels, th: Theme) {
  const pad = 72
  const headline = clean(labels.title || labels.header, '核心要点')
  pill(ctx, pad, 74, clean(labels.header || labels.title, '核心要点'), th, { font: 24, height: 48 })
  drawTitle(ctx, headline, pad, 150, 890, 52, th.title, 2)

  const points = ensurePoints(labels).filter((p) => clean(p) !== headline).slice(0, 4)
  if (points.length === 0) points.push(headline)

  const top = 332
  if (points.length <= 2) {
    const w = 936
    const h = points.length === 1 ? 520 : 368
    const gap = 38
    points.forEach((point, idx) => drawContentCard(ctx, pad, top + idx * (h + gap), w, h, idx, point, th))
  } else {
    const w = 438
    const h = 338
    const gap = 36
    points.forEach((point, idx) => {
      const col = idx % 2
      const row = Math.floor(idx / 2)
      drawContentCard(ctx, pad + col * (w + gap), top + row * (h + gap), w, h, idx, point, th)
    })
  }

  panel(ctx, pad, 1188, 936, 128, 30, th.dark, undefined, true)
  drawWrapped(ctx, clean(labels.subtitle, '这一页先抓结论，再看关键证据。'), pad + 34, 1226, 840, 30, '#fff', 800, 2, 1.28)
}

function drawSummaryPage(ctx: CanvasRenderingContext2D, labels: PageLabels, th: Theme) {
  const pad = 86
  pill(ctx, pad, 86, clean(labels.header, '最后总结'), th, { font: 24, height: 48 })

  panel(ctx, pad, 212, 908, 700, 42, 'rgba(255,255,255,0.76)', th.stroke)
  const titleBottom = drawTitle(ctx, clean(labels.title, '总结'), pad + 52, 282, 800, 70, th.title, 3)
  ctx.fillStyle = th.accent
  roundRect(ctx, pad + 52, titleBottom + 26, 170, 10, 5)
  ctx.fill()

  const subtitle = clean(labels.subtitle, '如果这张图对你有帮助，可以先收藏，后续照着一步步做。')
  panel(ctx, pad + 52, titleBottom + 66, 800, 178, 28, th.soft, th.stroke, false)
  drawWrapped(ctx, subtitle, pad + 84, titleBottom + 102, 736, 31, th.text, 700, 3, 1.36)

  const points = ensurePoints(labels).slice(0, 3)
  if (points.length) {
    let y = 782
    points.forEach((p) => {
      ctx.save()
      ctx.fillStyle = th.accent
      ctx.beginPath()
      ctx.arc(pad + 70, y + 14, 8, 0, Math.PI * 2)
      ctx.fill()
      ctx.restore()
      y = drawWrapped(ctx, limitText(p, 30), pad + 96, y, 740, 25, th.muted, 700, 1, 1.25) + 10
    })
  }

  panel(ctx, pad, 1122, 508, 122, 32, th.dark, undefined, true)
  drawWrapped(ctx, '觉得有用就收藏', pad + 34, 1158, 440, 34, '#fff', 900, 1)
  drawWrapped(ctx, '点关注看更多同类干货', pad + 34, 1206, 440, 22, 'rgba(255,255,255,0.78)', 650, 1)
}

export function composeCard(bg: HTMLImageElement, type: PageType, labels: PageLabels, palette: Palette): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = CW
  canvas.height = CH
  const ctx = canvas.getContext('2d')!
  const th = theme(palette)

  drawBase(ctx, bg, th)
  if (type === 'cover') drawCoverPage(ctx, labels, th)
  else if (type === 'summary') drawSummaryPage(ctx, labels, th)
  else drawContentPage(ctx, labels, th)

  return canvas
}

export function canvasToBlobPng(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob)
      else reject(new Error('PNG 导出失败'))
    }, 'image/png')
  })
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
