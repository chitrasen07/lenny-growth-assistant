import type { ConfigResponse, HealthResponse, ProviderInfo, ProviderName } from '../types/api'

interface Props {
  config: ConfigResponse | null
  health: HealthResponse | null
  provider: ProviderName
  onProviderChange: (provider: ProviderName) => void
}

const FALLBACK_PROVIDERS: ProviderInfo[] = [
  { name: 'ollama', model: 'llama3.1:8b', available: true, detail: null, runtime: 'router' },
  {
    name: 'anthropic',
    model: 'claude-sonnet-4-5',
    available: false,
    detail: 'ANTHROPIC_API_KEY missing',
    runtime: 'claude_agent_sdk',
  },
]

function providerLabel(name: string): string {
  return name === 'ollama' ? 'Ollama (local)' : 'Anthropic (cloud)'
}

/**
 * Header with the provider/model switcher.
 *
 * The selected provider is sent on every chat request. Only names and models are shown —
 * never keys. Anthropic can be selected without a key; the request then fails loudly
 * instead of falling back to Ollama.
 */
export function AppHeader({ config, health, provider, onProviderChange }: Props) {
  const providers = config?.providers?.length ? config.providers : FALLBACK_PROVIDERS
  const selected = providers.find((item) => item.name === provider)
  const model = selected?.model ?? (provider === 'ollama' ? 'llama3.1:8b' : 'claude-sonnet-4-5')
  const runtime =
    selected?.runtime ?? (provider === 'anthropic' ? 'claude_agent_sdk' : 'router')

  const providerHealth = provider === 'ollama' ? health?.ollama : health?.cloud_provider
  const providerOk = selected?.available ?? providerHealth?.healthy ?? true
  const anthropic = providers.find((item) => item.name === 'anthropic')
  const anthropicUnconfigured = provider === 'anthropic' && anthropic?.available === false

  return (
    <header className="app-header">
      <div className="app-header__brand">
        <h1>The Lenny Growth Assistant</h1>
        <p>Product &amp; growth answers grounded in podcast transcripts</p>
      </div>

      <div className="app-header__status">
        <div
          className={`provider-switcher${providerOk ? '' : ' provider-switcher--error'}`}
          title={selected?.detail ?? providerHealth?.detail ?? undefined}
        >
          <span className={`provider-badge__dot${providerOk ? '' : ' is-error'}`} aria-hidden="true" />
          <span className="provider-badge__text">
            <label className="provider-switcher__label">
              <span className="visually-hidden">LLM provider</span>
              <select
                aria-label="LLM provider"
                value={provider}
                onChange={(event) => onProviderChange(event.target.value as ProviderName)}
              >
                {providers.map((item) => (
                  <option key={item.name} value={item.name}>
                    {providerLabel(item.name)}
                    {item.model ? ` — ${item.model}` : ''}
                  </option>
                ))}
              </select>
            </label>
            <span>{model}</span>
          </span>
        </div>

        {anthropicUnconfigured && (
          <span className="provider-switcher__warning" role="status">
            Anthropic not configured
          </span>
        )}

        {runtime && (
          <span className="app-header__runtime" title="Agent runtime handling each turn for the selected provider">
            agent: {runtime}
          </span>
        )}

        {health?.knowledge_base && (
          <span
            className={`app-header__kb${health.knowledge_base.ready ? '' : ' is-warning'}`}
            title={`Embedding model: ${health.knowledge_base.embedding_model}`}
          >
            {health.knowledge_base.ready
              ? `${health.knowledge_base.chunks} chunks indexed`
              : 'no transcripts indexed'}
          </span>
        )}
      </div>
    </header>
  )
}
