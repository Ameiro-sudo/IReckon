import {marked} from 'marked'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/common'
import 'highlight.js/styles/github.css'
import dockerfile from 'highlight.js/lib/languages/dockerfile'
import dos from 'highlight.js/lib/languages/dos'
import pythonRepl from 'highlight.js/lib/languages/python-repl'

hljs.registerLanguage('dockerfile', dockerfile)
hljs.registerLanguage('batchfile', dos)
hljs.registerLanguage('python-repl', pythonRepl)

marked.setOptions({
  gfm: true,
  breaks: true
})

const escapeAttr = (s) =>
  String(s ?? '').replace(/&/g, '&amp;').replace(/"/g, '&quot;')
    .replace(/</g, '&lt;').replace(/>/g, '&gt;')

const safeUrl = (u) => {
  const s = String(u ?? '').trim()
  if (/^(https?:|mailto:)/i.test(s)) return s
  if (/^[./#]/.test(s) && !/^\/\//.test(s)) return s
  return '#'
}

marked.use({
  renderer: {
    link({ href, title, tokens }) {
      const text = this.parser.parseInline(tokens)
      const url = escapeAttr(safeUrl(href))
      const titleAttr = title ? ` title="${escapeAttr(title)}"` : ''
      return `<a href="${url}"${titleAttr} target="_blank" rel="noopener noreferrer">${text}</a>`
    }
  }
})

export function renderMarkdown(text) {
  if (!text) return ''
  const raw = marked.parse(String(text))
  return DOMPurify.sanitize(raw)
}

export function highlightDom(root) {
  if (!root) return
  root.querySelectorAll('pre code').forEach((el) => {
    if (el.dataset.highlighted) return
    try {
      hljs.highlightElement(el)
    } catch {
      /* 忽略无法高亮的代码块 */
    }
    el.dataset.highlighted = '1'
  })
}

const EXT_LANG = {
  py: 'python', js: 'javascript', mjs: 'javascript', cjs: 'javascript',
  ts: 'typescript', jsx: 'javascript', tsx: 'typescript', vue: 'xml',
  json: 'json', jsonc: 'json', yaml: 'yaml', yml: 'yaml', toml: 'ini',
  md: 'markdown', markdown: 'markdown', txt: 'plaintext',
  sh: 'bash', bash: 'bash', bat: 'batchfile', cmd: 'batchfile',
  sql: 'sql', html: 'xml', htm: 'xml', css: 'css', scss: 'scss',
  xml: 'xml', java: 'java', kt: 'kotlin', c: 'c', h: 'c',
  cpp: 'cpp', hpp: 'cpp', go: 'go', rs: 'rust', rb: 'ruby',
  php: 'php', swift: 'swift', lua: 'lua', ini: 'ini', conf: 'ini',
  cfg: 'ini', env: 'ini', properties: 'ini',
  dockerfile: 'dockerfile', makefile: 'makefile',
  gitignore: 'plaintext', dockerignore: 'plaintext'
}

export function highlightCode(code, filename = '') {
  if (!code) return ''
  let lang = ''
  const base = (filename || '').split('/').pop() || ''
  const ext = base.split('.').pop()?.toLowerCase()
  if (base.toLowerCase() === 'dockerfile') lang = 'dockerfile'
  if (base.toLowerCase() === 'makefile') lang = 'makefile'
  lang = lang || EXT_LANG[ext] || ''
  let html
  if (lang && hljs.getLanguage(lang)) {
    try {
      html = hljs.highlight(code, { language: lang }).value
    } catch {
      html = hljs.highlightAuto(code).value
    }
  } else {
    try {
      html = hljs.highlightAuto(code).value
    } catch {
      html = code.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    }
  }
  return DOMPurify.sanitize(html)
}

export const roleMeta = {
  user: { label: '用户', color: '#3b82f6' },
  scheduler: { label: '调度器', color: '#a855f7' },
  executor: { label: '执行者', color: '#f59e0b' },
  reviewer: { label: '审查者', color: '#10b981' },
  reviewer_correctness: { label: '正确性审查', color: '#10b981' },
  reviewer_efficiency: { label: '架构审查', color: '#0ea5e9' },
  deliverer: { label: '交付者', color: '#ec4899' },
  creative: { label: '创意官', color: '#8b5cf6' },
  learner: { label: '学习者', color: '#64748b' },
  tool_manager: { label: '工具管理', color: '#14b8a6' },
  security_scanner: { label: '安全扫描', color: '#ef4444' },
  system: { label: '系统', color: '#94a3b8' }
}

export function roleLabel(role) {
  return roleMeta[role]?.label || role
}

export function roleColor(role) {
  return roleMeta[role]?.color || '#94a3b8'
}
