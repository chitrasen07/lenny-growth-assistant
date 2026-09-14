/**
 * Header provider switcher: the selected provider is shown and is what chat requests use.
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { AppHeader } from '../components/AppHeader'
import { ErrorBanner } from '../components/ErrorBanner'
import { ApiError } from '../services/api'
import type { ConfigResponse, HealthResponse, ProviderName } from '../types/api'

const config: ConfigResponse = {
  active_provider: 'ollama',
  active_model: 'llama3.1:8b',
  agent_runtime: 'router',
  active_runtime: 'router',
  providers: [
    { name: 'ollama', model: 'llama3.1:8b', available: true, detail: null, runtime: 'router' },
    {
      name: 'anthropic',
      model: 'claude-sonnet-4-5',
      available: false,
      detail: 'ANTHROPIC_API_KEY missing (optional unless LLM_PROVIDER=anthropic)',
      runtime: 'claude_agent_sdk',
    },
  ],
  retrieval_top_k: 6,
  essay_target_words: 1250,
  knowledge_base: {
    transcripts: 50,
    chunks: 4984,
    embedding_model: 'nomic-embed-text',
    embedding_dimensions: 768,
    ready: true,
  },
}

const health: HealthResponse = {
  status: 'ok',
  version: '1.0.0',
  api: { healthy: true, detail: 'serving' },
  database: { healthy: true, detail: null },
  llm_provider: 'ollama',
  llm_model: 'llama3.1:8b',
  agent_runtime: 'router',
  active_runtime: 'router',
  ollama: { healthy: true, detail: null },
  cloud_provider: { healthy: false, detail: 'ANTHROPIC_API_KEY missing' },
  knowledge_base: config.knowledge_base,
}

function HeaderHarness({ initial = 'ollama' as ProviderName }) {
  const [provider, setProvider] = useState<ProviderName>(initial)
  return (
    <AppHeader config={config} health={health} provider={provider} onProviderChange={setProvider} />
  )
}

describe('AppHeader provider switcher', () => {
  it('lists Ollama and Anthropic with their configured models', () => {
    render(<HeaderHarness />)

    const select = screen.getByLabelText('LLM provider')
    expect(select).toHaveValue('ollama')
    expect(screen.getByRole('option', { name: /Ollama \(local\) — llama3.1:8b/ })).toBeInTheDocument()
    expect(
      screen.getByRole('option', { name: /Anthropic \(cloud\) — claude-sonnet-4-5/ }),
    ).toBeInTheDocument()
    expect(screen.getByText('llama3.1:8b')).toBeInTheDocument()
    expect(screen.getByText('agent: router')).toBeInTheDocument()
  })

  it('keeps the selected provider and its model visible after switching to Anthropic', async () => {
    const user = userEvent.setup()
    render(<HeaderHarness />)

    await user.selectOptions(screen.getByLabelText('LLM provider'), 'anthropic')

    expect(screen.getByLabelText('LLM provider')).toHaveValue('anthropic')
    expect(screen.getByText('claude-sonnet-4-5')).toBeInTheDocument()
    expect(screen.getByText('agent: claude_agent_sdk')).toBeInTheDocument()
  })

  it('shows Anthropic not configured when the cloud key is missing', async () => {
    const user = userEvent.setup()
    render(<HeaderHarness />)

    expect(screen.queryByText('Anthropic not configured')).not.toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('LLM provider'), 'anthropic')

    expect(screen.getByRole('status')).toHaveTextContent('Anthropic not configured')
  })

  it('notifies the parent so chat requests can send the selected provider', async () => {
    const user = userEvent.setup()
    const onProviderChange = vi.fn()
    render(
      <AppHeader
        config={config}
        health={health}
        provider="ollama"
        onProviderChange={onProviderChange}
      />,
    )

    await user.selectOptions(screen.getByLabelText('LLM provider'), 'anthropic')

    expect(onProviderChange).toHaveBeenCalledWith('anthropic')
  })
})

describe('ErrorBanner for a missing Anthropic key', () => {
  it('titles the failure Anthropic not configured', () => {
    render(
      <ErrorBanner
        error={
          new ApiError(
            'The Anthropic provider is selected but no API key is configured.',
            'provider_not_configured',
            503,
            'Set ANTHROPIC_API_KEY in .env, or switch back to Ollama (local) in the header.',
          )
        }
        onDismiss={() => undefined}
      />,
    )

    expect(screen.getByText('Anthropic not configured')).toBeInTheDocument()
    expect(screen.getByText(/no API key is configured/i)).toBeInTheDocument()
  })
})
