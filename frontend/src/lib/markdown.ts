import { marked } from 'marked'
import hljs from 'highlight.js/lib/core'
import javascript from 'highlight.js/lib/languages/javascript'
import typescript from 'highlight.js/lib/languages/typescript'
import python from 'highlight.js/lib/languages/python'
import bash from 'highlight.js/lib/languages/bash'
import json from 'highlight.js/lib/languages/json'
import yaml from 'highlight.js/lib/languages/yaml'
import xml from 'highlight.js/lib/languages/xml'
import css from 'highlight.js/lib/languages/css'
import markdown from 'highlight.js/lib/languages/markdown'

hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('typescript', typescript)
hljs.registerLanguage('python', python)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('json', json)
hljs.registerLanguage('yaml', yaml)
hljs.registerLanguage('xml', xml)
hljs.registerLanguage('css', css)
hljs.registerLanguage('markdown', markdown)

const LANG_ALIASES: Record<string, string> = {
  js: 'javascript', jsx: 'javascript', ts: 'typescript', tsx: 'typescript',
  py: 'python', sh: 'bash', shell: 'bash', yml: 'yaml', html: 'xml', md: 'markdown',
}

const COPY_BTN_HTML =
  '<button type="button" class="code-copy-btn" aria-label="复制代码" title="复制">' +
  '<svg class="ic-copy" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>' +
  '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>' +
  '<svg class="ic-check" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">' +
  '<polyline points="20 6 9 17 4 12"></polyline></svg></button>'

const HL_CACHE = new Map<string, string>()

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function highlightBlock(code: string, langRaw: string): { html: string; lang: string } {
  const lang = LANG_ALIASES[langRaw] || langRaw
  const key = lang + '\u0001' + code
  const hit = HL_CACHE.get(key)
  if (hit !== undefined) return { html: hit, lang }
  let html: string
  if (lang && hljs.getLanguage(lang)) {
    try {
      html = hljs.highlight(code, { language: lang, ignoreIllegals: true }).value
    } catch {
      html = escapeHtml(code)
    }
  } else {
    html = escapeHtml(code)
  }
  if (HL_CACHE.size > 400) HL_CACHE.clear()
  HL_CACHE.set(key, html)
  return { html, lang }
}

marked.setOptions({ breaks: true, gfm: true })
marked.use({
  renderer: {
    code(token: { text: string; lang?: string }) {
      const raw = token.text ?? ''
      const langRaw = (token.lang || '').trim().split(/\s+/)[0].toLowerCase()
      const { html, lang } = highlightBlock(raw, langRaw)
      const headCls = lang ? 'code-block-head' : 'code-block-head no-lang'
      return (
        `<div class="code-block"><div class="${headCls}">` +
        `<span class="code-lang">${lang ? escapeHtml(lang) : ''}</span>` +
        COPY_BTN_HTML +
        `</div><pre><code class="hljs">${html}\n</code></pre></div>\n`
      )
    },
  },
})

let copyInstalled = false
if (!copyInstalled && typeof document !== 'undefined') {
  copyInstalled = true
  document.addEventListener('click', (e) => {
    const btn = (e.target as HTMLElement | null)?.closest?.('.code-copy-btn') as HTMLButtonElement | null
    if (!btn || btn.dataset.busy) return
    const text = btn.closest('.code-block')?.querySelector('pre code')?.textContent ?? ''
    btn.dataset.busy = '1'
    void (async () => {
      try { await navigator.clipboard.writeText(text) } catch { /* ignore */ }
      btn.classList.add('copied')
      window.setTimeout(() => {
        btn.classList.remove('copied')
        delete btn.dataset.busy
      }, 1400)
    })()
  })
}

function ensureLinksOpenInNewTab(html: string): string {
  return html.replace(/<a\b([^>]*?)>/gi, (_match, attrs: string) => {
    let next = attrs
    if (/\btarget\s*=/.test(next)) {
      next = next.replace(/\btarget\s*=\s*("[^"]*"|'[^']*'|\S+)/i, 'target="_blank"')
    } else {
      next += ' target="_blank"'
    }
    if (!/\brel\s*=/.test(next)) {
      next += ' rel="noopener noreferrer"'
    }
    return `<a${next}>`
  })
}

const MD_CACHE = new Map<string, string>()

export function renderChatMarkdown(text: string): string {
  if (!text) return ''
  const cached = MD_CACHE.get(text)
  if (cached !== undefined) return cached
  let cleaned = text
  if (cleaned.includes('<think')) {
    cleaned = cleaned
      .replace(/<think[^>]*>[\s\S]*?<\/think>/gi, '')
      .replace(/<think[^>]*>/gi, '')
      .replace(/<\/think[^>]*>/gi, '')
  }
  if (!cleaned.trim()) return ''
  const html = ensureLinksOpenInNewTab(marked.parse(cleaned) as string)
  if (MD_CACHE.size >= 500) {
    const oldest = MD_CACHE.keys().next().value
    if (oldest !== undefined) MD_CACHE.delete(oldest)
  }
  MD_CACHE.set(text, html)
  return html
}
