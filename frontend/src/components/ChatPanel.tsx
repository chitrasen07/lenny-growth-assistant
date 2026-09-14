import { useEffect, useRef } from 'react'

import type { ChatStage } from '../hooks/useChat'
import type { ApiError } from '../services/api'
import type { KnowledgeBaseStatus, Message } from '../types/api'
import { Composer } from './Composer'
import { ErrorBanner } from './ErrorBanner'
import { MessageBubble } from './MessageBubble'

interface Props {
  messages: Message[]
  stage: ChatStage
  elapsedSeconds: number
  busy: boolean
  error: ApiError | null
  loadingHistory: boolean
  hasSession: boolean
  knowledgeBase: KnowledgeBaseStatus | null
  onSend: (text: string) => void
  onDismissError: () => void
}

const STAGE_LABELS: Record<Exclude<ChatStage, 'idle'>, string> = {
  retrieving: 'Searching the transcript knowledge base…',
  generating: 'Generating a grounded answer…',
}

const EXAMPLE_PROMPTS = [
  'How should I think about improving activation?',
  'Write a Ship 30 for 30 essay about activation',
  'Create a landing page for this idea',
]

function EmptyState({ knowledgeBase, onSend }: Pick<Props, 'knowledgeBase' | 'onSend'>) {
  const ready = knowledgeBase?.ready ?? false

  return (
    <div className="chat__empty">
      <h2>Ask about product &amp; growth</h2>
      <p>
        Answers come only from the indexed Lenny&apos;s Podcast transcripts, with citations you can
        check. When the transcripts don&apos;t cover something, the assistant says so instead of
        guessing.
      </p>

      {!ready ? (
        <div className="callout callout--warning">
          <strong>The knowledge base is empty.</strong>
          <p>
            Add transcripts to <code>data/transcripts/</code>, then run{' '}
            <code>docker compose exec backend python -m scripts.ingest</code>. See{' '}
            <code>docs/transcripts.md</code>.
          </p>
        </div>
      ) : (
        <>
          <p className="chat__empty-hint">
            {knowledgeBase?.transcripts} transcript(s) · {knowledgeBase?.chunks} indexed chunks
          </p>
          <ul className="chat__examples">
            {EXAMPLE_PROMPTS.map((prompt) => (
              <li key={prompt}>
                <button type="button" onClick={() => onSend(prompt)}>
                  {prompt}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

export function ChatPanel({
  messages,
  stage,
  elapsedSeconds,
  busy,
  error,
  loadingHistory,
  hasSession,
  knowledgeBase,
  onSend,
  onDismissError,
}: Props) {
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages.length, stage])

  return (
    <section className="chat" aria-label="Conversation">
      <div className="chat__messages">
        {loadingHistory && (
          <p className="chat__loading" role="status">
            Loading conversation…
          </p>
        )}

        {!loadingHistory && messages.length === 0 && (
          <EmptyState knowledgeBase={knowledgeBase} onSend={onSend} />
        )}

        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}

        {busy && stage !== 'idle' && (
          <div className="chat__pending" role="status" aria-live="polite">
            <span className="spinner" aria-hidden="true" />
            <span>{STAGE_LABELS[stage]}</span>
            {/* Local models can take 30-60s, so show progress rather than a bare spinner. */}
            {elapsedSeconds > 2 && <span className="chat__elapsed">{elapsedSeconds}s</span>}
          </div>
        )}

        {error && <ErrorBanner error={error} onDismiss={onDismissError} />}

        <div ref={endRef} />
      </div>

      <Composer disabled={!hasSession} busy={busy} onSend={onSend} />
    </section>
  )
}
