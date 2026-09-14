import { useCallback, useEffect, useState } from 'react'

import { ApiError, api } from '../services/api'
import type { SessionSummary } from '../types/api'

/** Owns the session list and which session is active. */
export function useSessions() {
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiError | null>(null)

  const load = useCallback(async () => {
    try {
      const list = await api.listSessions()
      setSessions(list)
      setError(null)
      return list
    } catch (caught) {
      setError(caught as ApiError)
      return []
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void (async () => {
      const list = await load()
      // Open the most recent conversation so a returning evaluator sees prior state.
      if (list.length > 0 && list[0]) setActiveId(list[0].id)
    })()
  }, [load])

  const createSession = useCallback(async () => {
    try {
      const session = await api.createSession()
      setSessions((current) => [session, ...current])
      setActiveId(session.id)
      setError(null)
      return session
    } catch (caught) {
      setError(caught as ApiError)
      return null
    }
  }, [])

  const deleteSession = useCallback(
    async (sessionId: string) => {
      try {
        await api.deleteSession(sessionId)
        const remaining = sessions.filter((session) => session.id !== sessionId)
        setSessions(remaining)
        if (activeId === sessionId) setActiveId(remaining[0]?.id ?? null)
      } catch (caught) {
        setError(caught as ApiError)
      }
    },
    [activeId, sessions],
  )

  /** Reflect a new message count and re-sort without a full refetch. */
  const registerActivity = useCallback((sessionId: string, messageCount: number, title?: string) => {
    setSessions((current) => {
      const updated = current.map((session) =>
        session.id === sessionId
          ? {
              ...session,
              message_count: messageCount,
              title: title ?? session.title,
              updated_at: new Date().toISOString(),
            }
          : session,
      )
      return [...updated].sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    })
  }, [])

  return {
    sessions,
    activeId,
    loading,
    error,
    setActiveId,
    createSession,
    deleteSession,
    registerActivity,
    reload: load,
    clearError: () => setError(null),
  }
}
