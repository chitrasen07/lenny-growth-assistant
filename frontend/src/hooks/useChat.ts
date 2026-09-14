import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError, api } from '../services/api'
import type { Artifact, ArtifactType, Message, ProviderName } from '../types/api'

/** Staged progress shown while a turn runs, since generation is not streamed. */
export type ChatStage = 'idle' | 'retrieving' | 'generating'

interface UseChatOptions {
  sessionId: string | null
  provider?: ProviderName
  onActivity?: (sessionId: string, messageCount: number, title?: string) => void
}

/**
 * Owns the message list, artifact and in-flight state for the active session.
 *
 * Responses are not token-streamed, so a local model can take 30-60s. Rather than an
 * opaque spinner, the hook advances through named stages that mirror what the backend is
 * actually doing (retrieval, then generation) and tracks elapsed time.
 */
export function useChat({ sessionId, provider, onActivity }: UseChatOptions) {
  const [messages, setMessages] = useState<Message[]>([])
  const [artifact, setArtifact] = useState<Artifact | null>(null)
  const [stage, setStage] = useState<ChatStage>('idle')
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [error, setError] = useState<ApiError | null>(null)
  const [loadingHistory, setLoadingHistory] = useState(false)

  // Guards against a slow response for a previous session overwriting the current one.
  const requestSession = useRef<string | null>(null)

  useEffect(() => {
    setMessages([])
    setArtifact(null)
    setError(null)
    setStage('idle')
    if (!sessionId) return

    requestSession.current = sessionId
    setLoadingHistory(true)
    void (async () => {
      try {
        const [history, latest] = await Promise.all([
          api.listMessages(sessionId),
          api.latestArtifact(sessionId).catch(() => null),
        ])
        if (requestSession.current !== sessionId) return
        setMessages(history)
        setArtifact(latest)
      } catch (caught) {
        if (requestSession.current === sessionId) setError(caught as ApiError)
      } finally {
        if (requestSession.current === sessionId) setLoadingHistory(false)
      }
    })()
  }, [sessionId])

  useEffect(() => {
    if (stage === 'idle') {
      setElapsedSeconds(0)
      return
    }
    const startedAt = Date.now()
    const timer = window.setInterval(
      () => setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000)),
      1000,
    )
    // Retrieval is fast; anything past ~2s is the model generating.
    const advance = window.setTimeout(() => setStage('generating'), 2000)
    return () => {
      window.clearInterval(timer)
      window.clearTimeout(advance)
    }
  }, [stage])

  const run = useCallback(
    async (optimisticText: string, call: () => Promise<{ message: Message }>) => {
      if (!sessionId) return
      const target = sessionId
      requestSession.current = target
      setError(null)
      setStage('retrieving')

      // Show the user's own message immediately; it is already persisted server-side.
      const pending: Message = {
        id: `pending-${Date.now()}`,
        session_id: target,
        role: 'user',
        content: optimisticText,
        created_at: new Date().toISOString(),
        metadata: {},
        sources: [],
        artifact: null,
      }
      setMessages((current) => [...current, pending])

      try {
        const response = await call()
        if (requestSession.current !== target) return
        // The response carries only the assistant turn; the optimistic user message stays.
        setMessages((current) => [...current, response.message])
        if (response.message.artifact) setArtifact(response.message.artifact)
        onActivity?.(target, messages.length + 2, optimisticText)
      } catch (caught) {
        if (requestSession.current !== target) return
        setError(caught as ApiError)
        // Keep the user's message: it is persisted, and they should not retype it.
      } finally {
        if (requestSession.current === target) setStage('idle')
      }
    },
    [messages.length, onActivity, sessionId],
  )

  const sendMessage = useCallback(
    (text: string) => run(text, () => api.sendMessage(sessionId as string, text, provider)),
    [provider, run, sessionId],
  )

  const generateArtifact = useCallback(
    (artifactType: ArtifactType, instruction: string) =>
      run(`[${artifactType}] ${instruction}`, () =>
        api.generateArtifact(sessionId as string, artifactType, instruction, provider),
      ),
    [provider, run, sessionId],
  )

  return {
    messages,
    artifact,
    stage,
    elapsedSeconds,
    busy: stage !== 'idle',
    error,
    loadingHistory,
    sendMessage,
    generateArtifact,
    setArtifact,
    clearError: () => setError(null),
  }
}
