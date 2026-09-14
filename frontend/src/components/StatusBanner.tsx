import type { HealthResponse, ProviderName } from '../types/api'

/**
 * Surfaces blocking setup problems at the top of the app.
 *
 * Only shows conditions the evaluator must act on, each with the exact command to fix it,
 * so a misconfigured environment is diagnosable without reading the server logs.
 */
export function StatusBanner({
  health,
  provider,
}: {
  health: HealthResponse | null
  provider?: ProviderName
}) {
  if (!health) return null

  const problems: { title: string; detail: string; fix: string }[] = []

  if (!health.database.healthy) {
    problems.push({
      title: 'Database unavailable',
      detail: health.database.detail ?? 'The API cannot reach PostgreSQL.',
      fix: 'docker compose up -d db',
    })
  }

  const ollamaSelected = health.llm_provider === 'ollama' || provider === 'ollama'
  if (ollamaSelected && !health.ollama.healthy) {
    problems.push({
      title: 'Ollama not reachable',
      detail: health.ollama.detail ?? 'The configured local model is unavailable.',
      fix: `ollama serve  &&  ollama pull ${health.llm_model}`,
    })
  }

  const anthropicSelected = health.llm_provider === 'anthropic' || provider === 'anthropic'
  if (anthropicSelected && !health.cloud_provider.healthy) {
    problems.push({
      title: 'Anthropic not configured',
      detail: health.cloud_provider.detail ?? 'No API key is configured.',
      fix: 'Set ANTHROPIC_API_KEY in .env, or switch back to Ollama (local) in the header',
    })
  }

  if (health.knowledge_base && !health.knowledge_base.ready) {
    problems.push({
      title: 'No transcripts indexed',
      detail: 'Retrieval has nothing to search, so the assistant will decline every question.',
      fix: 'docker compose exec backend python -m scripts.ingest',
    })
  }

  if (problems.length === 0) return null

  return (
    <div className="status-banner" role="status">
      {problems.map((problem) => (
        <div key={problem.title} className="status-banner__item">
          <strong>{problem.title}</strong>
          <span>{problem.detail}</span>
          <code>{problem.fix}</code>
        </div>
      ))}
    </div>
  )
}
