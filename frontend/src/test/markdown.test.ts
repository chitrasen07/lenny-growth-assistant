/**
 * Markdown rendering safety.
 *
 * Markdown may embed raw HTML, and the text being rendered is model output, so these
 * tests assert DOMPurify actually removes the dangerous constructs before anything
 * reaches the DOM.
 */

import { describe, expect, it } from 'vitest'

import { highlightCitations, renderMarkdown } from '../services/markdown'

describe('renderMarkdown', () => {
  it('renders standard markdown structures', () => {
    const html = renderMarkdown('# Title\n\nSome **bold** text.\n\n- one\n- two\n')

    expect(html).toContain('<h1>Title</h1>')
    expect(html).toContain('<strong>bold</strong>')
    expect(html).toContain('<li>one</li>')
  })

  it('renders tables and blockquotes', () => {
    const html = renderMarkdown('| A | B |\n| --- | --- |\n| 1 | 2 |\n\n> quoted\n')

    expect(html).toContain('<table>')
    expect(html).toContain('<blockquote>')
  })

  it('strips embedded script tags', () => {
    const html = renderMarkdown('Hello\n\n<script>alert("xss")</script>\n')

    expect(html).not.toContain('<script')
    expect(html).not.toContain('alert')
  })

  it('strips inline event handlers', () => {
    const html = renderMarkdown('<div onclick="alert(1)">Click</div>')

    expect(html).not.toContain('onclick')
    expect(html).toContain('Click')
  })

  it('removes javascript: links but keeps the text', () => {
    const html = renderMarkdown('[click me](javascript:alert(1))')

    expect(html).not.toContain('javascript:')
    expect(html).toContain('click me')
  })

  it('removes img onerror payloads', () => {
    const html = renderMarkdown('<img src="x" onerror="alert(1)">')

    expect(html).not.toContain('onerror')
    expect(html).not.toContain('alert')
  })

  it('strips style elements and iframes', () => {
    const html = renderMarkdown('<style>body{display:none}</style><iframe src="https://evil.test"></iframe>')

    expect(html).not.toContain('<style')
    expect(html).not.toContain('<iframe')
    expect(html).not.toContain('evil.test')
  })

  it('keeps safe https links', () => {
    const html = renderMarkdown('[Lenny](https://example.com/episode)')

    expect(html).toContain('href="https://example.com/episode"')
  })

  it('handles empty input', () => {
    expect(renderMarkdown('')).toBe('')
  })
})

describe('highlightCitations', () => {
  it('wraps a single marker', () => {
    const html = highlightCitations('Activation matters [S1].')

    expect(html).toContain('citation-marker')
    expect(html).toContain('[S1]')
  })

  it('wraps grouped markers', () => {
    expect(highlightCitations('Claim [S1, S3].')).toContain('citation-marker')
  })

  it('leaves text without markers untouched', () => {
    expect(highlightCitations('No citations here.')).toBe('No citations here.')
  })

  it('does not treat ordinary brackets as citations', () => {
    expect(highlightCitations('An array like [1, 2].')).not.toContain('citation-marker')
  })
})
