import { useEffect, useRef, useState } from 'react'

import { AppHeader } from './components/AppHeader'
import { ArtifactViewer } from './components/ArtifactViewer'
import { ChatPanel } from './components/ChatPanel'
import { ErrorBanner } from './components/ErrorBanner'
import { SessionSidebar } from './components/SessionSidebar'
import { StatusBanner } from './components/StatusBanner'
import { useChat } from './hooks/useChat'
import { useConfig } from './hooks/useConfig'
import { useSessions } from './hooks/useSessions'
import type { ProviderName } from './types/api'

export default function App() {
  const { config, health, refresh: refreshHealth } = useConfig()
  const [provider, setProvider] = useState<ProviderName>('ollama')
  const providerSynced = useRef(false)
  const {
    sessions,
    activeId,
    loading: sessionsLoading,
    error: sessionsError,
    setActiveId,
    createSession,
    deleteSession,
    registerActivity,
    clearError: clearSessionsError,
  } = useSessions()

  const chat = useChat({ sessionId: activeId, provider, onActivity: registerActivity })

  // Honour the server default once. Later header changes must not be overwritten by
  // a health refresh, which still reports the process-level LLM_PROVIDER.
  useEffect(() => {
    if (providerSynced.current || !config) return
    if (config.active_provider === 'ollama' || config.active_provider === 'anthropic') {
      setProvider(config.active_provider)
    }
    providerSynced.current = true
  }, [config])

  // Refresh health once the first turn completes: ingesting transcripts or starting
  // Ollama mid-session should clear the setup banner without a page reload.
  useEffect(() => {
    if (chat.stage === 'idle' && chat.messages.length > 0) void refreshHealth()
  }, [chat.messages.length, chat.stage, refreshHealth])

  async function handleCreate() {
    const session = await createSession()
    if (session) chat.setArtifact(null)
  }

  return (
    <div className="app">
      <a className="skip-link" href="#main-content">
        Skip to conversation
      </a>

      <AppHeader
        config={config}
        health={health}
        provider={provider}
        onProviderChange={setProvider}
      />
      <StatusBanner health={health} provider={provider} />

      {sessionsError && <ErrorBanner error={sessionsError} onDismiss={clearSessionsError} />}

      <div className="app__body">
        <SessionSidebar
          sessions={sessions}
          activeId={activeId}
          loading={sessionsLoading}
          onSelect={setActiveId}
          onCreate={handleCreate}
          onDelete={deleteSession}
        />

        <main id="main-content" className="app__main">
          <ChatPanel
            messages={chat.messages}
            stage={chat.stage}
            elapsedSeconds={chat.elapsedSeconds}
            busy={chat.busy}
            error={chat.error}
            loadingHistory={chat.loadingHistory}
            hasSession={Boolean(activeId)}
            knowledgeBase={health?.knowledge_base ?? config?.knowledge_base ?? null}
            onSend={async (text) => {
              // Sending from the empty state before a session exists should just work.
              if (!activeId) {
                const session = await createSession()
                if (!session) return
              }
              chat.sendMessage(text)
            }}
            onDismissError={chat.clearError}
          />

          <ArtifactViewer
            artifact={chat.artifact}
            busy={chat.busy}
            canGenerate={Boolean(activeId)}
            onGenerate={chat.generateArtifact}
          />
        </main>
      </div>
    </div>
  )
}
