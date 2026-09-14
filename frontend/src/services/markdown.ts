/**
 * Markdown rendering for chat messages and Markdown artifacts.
 *
 * Markdown can contain raw HTML, so model output is parsed and then sanitised with
 * DOMPurify before it is ever placed in the document. DOMPurify is a maintained,
 * widely-audited sanitiser — preferable to hand-rolling one for this path.
 *
 * The HTML *artifact* path does not use this function: those documents need their own
 * `<style>` and full page structure, so they are sanitised server-side and rendered in a
 * sandboxed iframe instead (see ArtifactViewer).
 */

import DOMPurify from 'dompurify'
import { marked } from 'marked'

marked.setOptions({ gfm: true, breaks: true })

/** Elements allowed in rendered Markdown. No script, iframe, form, style or embeds. */
const ALLOWED_TAGS = [
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'p', 'br', 'hr', 'blockquote', 'pre', 'code',
  'ul', 'ol', 'li', 'dl', 'dt', 'dd',
  'strong', 'em', 'b', 'i', 'u', 's', 'del', 'mark', 'sup', 'sub', 'span', 'div',
  'a', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
]

const ALLOWED_ATTR = ['href', 'title', 'colspan', 'rowspan', 'class', 'align']

export function renderMarkdown(markdown: string): string {
  const html = marked.parse(markdown, { async: false }) as string
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    // Only http(s) and mailto links; blocks javascript: and data: URLs.
    ALLOWED_URI_REGEXP: /^(?:https?:|mailto:|#)/i,
    FORBID_TAGS: ['style', 'script', 'iframe', 'object', 'embed', 'form', 'input'],
    FORBID_ATTR: ['style', 'onerror', 'onload', 'onclick'],
    ADD_ATTR: ['target', 'rel'],
  })
}

/**
 * Highlight `[S1]`-style citation markers so a reader can tie a claim to a source.
 * Runs on already-sanitised HTML and inserts only a fixed, non-interactive span.
 */
export function highlightCitations(html: string): string {
  return html.replace(
    /\[\s*S\s*(\d+(?:\s*,\s*S?\s*\d+)*)\s*\]/gi,
    (_match, group: string) =>
      `<span class="citation-marker" aria-label="Source ${group.replace(/\s+/g, ' ')}">[S${group
        .replace(/\s+/g, '')
        .replace(/S/gi, '')
        .split(',')
        .join(', S')}]</span>`,
  )
}
