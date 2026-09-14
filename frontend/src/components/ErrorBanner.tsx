import type { ApiError } from '../services/api'

/** Titles per error code, so a failure reads as a diagnosis rather than a stack trace. */
const TITLES: Record<string, string> = {
  provider_unavailable: 'The local model is not reachable',
  provider_not_configured: 'Anthropic not configured',
  provider_timeout: 'The model took too long to respond',
  provider_error: 'The model provider returned an error',
  embedding_failed: 'Could not create embeddings',
  knowledge_base_empty: 'No transcripts are indexed',
  database_unavailable: 'The database is unavailable',
  artifact_generation_failed: 'The artifact could not be generated',
  payload_too_large: 'That message is too long',
  validation_failed: 'That request was not valid',
  network_error: 'Could not reach the API',
  not_found: 'Not found',
}

interface Props {
  error: ApiError
  onDismiss: () => void
  onRetry?: () => void
}

export function ErrorBanner({ error, onDismiss, onRetry }: Props) {
  return (
    <div className="error-banner" role="alert">
      <div className="error-banner__body">
        <strong>{TITLES[error.code] ?? 'Something went wrong'}</strong>
        <p>{error.message}</p>
        {error.remedy && <p className="error-banner__remedy">{error.remedy}</p>}
        <p className="error-banner__code">Error code: {error.code}</p>
      </div>
      <div className="error-banner__actions">
        {onRetry && (
          <button type="button" onClick={onRetry}>
            Retry
          </button>
        )}
        <button type="button" onClick={onDismiss} aria-label="Dismiss error">
          Dismiss
        </button>
      </div>
    </div>
  )
}
