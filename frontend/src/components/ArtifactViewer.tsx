/**
 * Artifact Viewer — renders generated Markdown and HTML/CSS beside the chat.
 *
 * Security model for HTML artifacts (layer 3 of 3; see backend sanitizer.py for 1-2):
 *
 *   <iframe sandbox="allow-same-origin" srcdoc={html}>
 *
 * `sandbox` **without `allow-scripts`** means the browser refuses to execute any script in
 * the document — inline, event-handler or injected. So even if the server-side sanitiser
 * missed something, it cannot run. `srcdoc` keeps the content out of the parent document
 * entirely: it is never assigned to `innerHTML` anywhere in this app, so it cannot touch
 * our DOM, storage or cookies. `allow-same-origin` is present only so the frame can apply
 * its own inline `<style>`; combined with the absence of `allow-scripts` it grants no
 * script access to anything.
 *
 * Markdown artifacts take the other path: parsed then DOMPurify-sanitised (services/markdown.ts).
 */

import { useMemo, useState } from 'react'

import { highlightCitations, renderMarkdown } from '../services/markdown'
import type { Artifact, SanitiserReport } from '../types/api'

interface Props {
  artifact: Artifact | null
  busy: boolean
  onGenerate: (type: 'markdown' | 'html', instruction: string) => void
  canGenerate: boolean
}

function SanitiserNote({ report }: { report: SanitiserReport }) {
  const removals: string[] = []
  const tags = Object.entries(report.removed_tags ?? {})
  const attributes = Object.entries(report.removed_attributes ?? {})
  if (tags.length) removals.push(tags.map(([tag, count]) => `<${tag}> ×${count}`).join(', '))
  if (attributes.length) removals.push(attributes.map(([attr, count]) => `${attr} ×${count}`).join(', '))
  if (report.removed_urls) removals.push(`${report.removed_urls} unsafe URL(s)`)
  if (report.css_rules_stripped) removals.push(`${report.css_rules_stripped} unsafe CSS rule(s)`)

  return (
    <details className="sanitiser-note">
      <summary>Unsafe markup was removed before rendering</summary>
      <p>
        Generated HTML is treated as untrusted. These constructs were stripped server-side, and the
        preview runs in a sandboxed frame with scripting disabled.
      </p>
      <ul>
        {removals.map((entry) => (
          <li key={entry}>{entry}</li>
        ))}
      </ul>
    </details>
  )
}

export function ArtifactViewer({ artifact, busy, onGenerate, canGenerate }: Props) {
  const [instruction, setInstruction] = useState('')
  const [type, setType] = useState<'markdown' | 'html'>('html')

  const markdownHtml = useMemo(
    () =>
      artifact && artifact.type === 'markdown'
        ? highlightCitations(renderMarkdown(artifact.content))
        : '',
    [artifact],
  )

  const report = artifact?.sanitiser_report as SanitiserReport | undefined
  const showReport = Boolean(artifact?.type === 'html' && report?.modified)

  function submit(event: React.FormEvent) {
    event.preventDefault()
    const trimmed = instruction.trim()
    if (!trimmed || busy || !canGenerate) return
    onGenerate(type, trimmed)
    setInstruction('')
  }

  return (
    <section className="artifact-viewer" aria-labelledby="artifact-heading">
      <header className="artifact-viewer__header">
        <div>
          <h2 id="artifact-heading">Artifact Viewer</h2>
          {artifact ? (
            <p className="artifact-viewer__title" title={artifact.title}>
              <span className={`badge badge--${artifact.type}`}>{artifact.type.toUpperCase()}</span>
              {artifact.title}
            </p>
          ) : (
            <p className="artifact-viewer__subtitle">Generated documents and pages appear here.</p>
          )}
        </div>
      </header>

      <div className="artifact-viewer__body">
        {busy && !artifact && (
          <div className="artifact-viewer__state" role="status">
            <span className="spinner" aria-hidden="true" />
            <p>Generating artifact…</p>
          </div>
        )}

        {!busy && !artifact && (
          <div className="artifact-viewer__state artifact-viewer__empty">
            <h3>Nothing generated yet</h3>
            <p>
              Ask the assistant for a deliverable in chat — for example{' '}
              <em>“Create a landing page for this idea”</em> or{' '}
              <em>“Create a Markdown strategy document”</em> — or use the form below.
            </p>
          </div>
        )}

        {artifact && artifact.type === 'html' && (
          <>
            {showReport && report && <SanitiserNote report={report} />}
            <iframe
              className="artifact-frame"
              title={`Rendered artifact: ${artifact.title}`}
              /* No allow-scripts: the browser will not execute script in this document. */
              sandbox="allow-same-origin"
              srcDoc={artifact.content}
            />
          </>
        )}

        {artifact && artifact.type === 'markdown' && (
          <article
            className="artifact-markdown markdown-body"
            /* Sanitised by DOMPurify in renderMarkdown before it reaches the DOM. */
            dangerouslySetInnerHTML={{ __html: markdownHtml }}
          />
        )}
      </div>

      <form className="artifact-viewer__form" onSubmit={submit}>
        <label className="visually-hidden" htmlFor="artifact-instruction">
          Describe the artifact to generate
        </label>
        <div className="artifact-viewer__controls">
          <select
            aria-label="Artifact format"
            value={type}
            onChange={(event) => setType(event.target.value as 'markdown' | 'html')}
            disabled={busy || !canGenerate}
          >
            <option value="html">HTML page</option>
            <option value="markdown">Markdown doc</option>
          </select>
          <input
            id="artifact-instruction"
            type="text"
            placeholder={canGenerate ? 'e.g. Landing page for our activation tool' : 'Start a chat first'}
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            disabled={busy || !canGenerate}
          />
          <button type="submit" disabled={busy || !canGenerate || !instruction.trim()}>
            Generate
          </button>
        </div>
      </form>
    </section>
  )
}
