import { useMemo } from 'react'

import { highlightCitations, renderMarkdown } from '../services/markdown'
import type { Message } from '../types/api'
import { SourceList } from './SourceList'

const INTENT_LABELS: Record<string, string> = {
  question: 'Grounded answer',
  ship30_essay: 'Ship 30 for 30 essay',
  artifact: 'Artifact',
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user'
  const { metadata } = message

  const html = useMemo(
    () => (isUser ? '' : highlightCitations(renderMarkdown(message.content))),
    [isUser, message.content],
  )

  const wordCount = metadata.word_count
  const intentLabel = metadata.intent ? INTENT_LABELS[metadata.intent] : undefined

  return (
    <article className={`message message--${isUser ? 'user' : 'assistant'}`}>
      <header className="message__header">
        <span className="message__author">{isUser ? 'You' : 'Lenny Growth Assistant'}</span>
        <time dateTime={message.created_at}>{formatTime(message.created_at)}</time>
      </header>

      {isUser ? (
        <p className="message__text">{message.content}</p>
      ) : (
        <div
          className="message__text markdown-body"
          /* Sanitised with DOMPurify in renderMarkdown before reaching the DOM. */
          dangerouslySetInnerHTML={{ __html: html }}
        />
      )}

      {!isUser && metadata.refused === true && (
        <p className="message__flag message__flag--refused">
          No sufficiently relevant transcript evidence was found, so the assistant did not answer
          from general knowledge.
        </p>
      )}

      {!isUser && metadata.uncited_answer === true && (
        <p className="message__flag message__flag--warning">
          This answer did not cite specific excerpts. The retrieved sources are listed below for you
          to verify it.
        </p>
      )}

      {!isUser && <SourceList sources={message.sources} />}

      {!isUser && (metadata.provider || intentLabel) && (
        <footer className="message__footer">
          {intentLabel && <span>{intentLabel}</span>}
          {metadata.provider && (
            <span>
              {metadata.provider}
              {metadata.model ? ` · ${metadata.model}` : ''}
            </span>
          )}
          {typeof wordCount === 'number' && (
            <span
              className={metadata.within_tolerance === false ? 'is-warning' : undefined}
              title={
                metadata.target_words ? `Target ${metadata.target_words} words` : undefined
              }
            >
              {wordCount} words
            </span>
          )}
          {typeof metadata.timings_ms?.total_ms === 'number' && (
            <span>{(metadata.timings_ms.total_ms / 1000).toFixed(1)}s</span>
          )}
        </footer>
      )}
    </article>
  )
}
