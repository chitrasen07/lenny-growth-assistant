import type { SessionSummary } from '../types/api'

interface Props {
  sessions: SessionSummary[]
  activeId: string | null
  loading: boolean
  onSelect: (sessionId: string) => void
  onCreate: () => void
  onDelete: (sessionId: string) => void
}

function formatDate(iso: string): string {
  const date = new Date(iso)
  const today = new Date()
  const sameDay = date.toDateString() === today.toDateString()
  return sameDay
    ? date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : date.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

export function SessionSidebar({ sessions, activeId, loading, onSelect, onCreate, onDelete }: Props) {
  return (
    <nav className="sidebar" aria-label="Chat sessions">
      <button type="button" className="sidebar__new" onClick={onCreate}>
        + New chat
      </button>

      <h2 className="sidebar__heading" id="sessions-heading">
        Chats
      </h2>

      {loading && <p className="sidebar__state">Loading…</p>}
      {!loading && sessions.length === 0 && (
        <p className="sidebar__state">No chats yet. Start one above.</p>
      )}

      <ul className="sidebar__list" aria-labelledby="sessions-heading">
        {sessions.map((session) => {
          const isActive = session.id === activeId
          return (
            <li key={session.id} className={`sidebar__item${isActive ? ' is-active' : ''}`}>
              <button
                type="button"
                className="sidebar__link"
                aria-current={isActive ? 'true' : undefined}
                onClick={() => onSelect(session.id)}
              >
                <span className="sidebar__title">{session.title}</span>
                <span className="sidebar__meta">
                  {formatDate(session.updated_at)}
                  {session.message_count > 0 && ` · ${session.message_count} messages`}
                </span>
              </button>
              <button
                type="button"
                className="sidebar__delete"
                // Names the chat so screen-reader users know which delete this is.
                aria-label={`Delete chat: ${session.title}`}
                onClick={() => onDelete(session.id)}
              >
                ×
              </button>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
