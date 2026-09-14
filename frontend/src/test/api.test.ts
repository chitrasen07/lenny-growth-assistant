/**
 * API client error normalisation.
 *
 * The UI can only give an actionable message if the backend's structured error envelope
 * survives transport intact, including the remedy. These tests pin that contract.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, api } from '../services/api'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** Runs a request expected to fail and returns the normalised error. */
async function captureError(call: () => Promise<unknown>): Promise<ApiError> {
  try {
    await call()
  } catch (caught) {
    return caught as ApiError
  }
  throw new Error('Expected the request to fail, but it resolved.')
}

/** The URL and parsed JSON body of the first fetch the client issued. */
function firstRequest(): { url: string; body: Record<string, unknown> } {
  const call = vi.mocked(fetch).mock.calls[0]
  if (!call) throw new Error('fetch was never called.')
  return { url: String(call[0]), body: JSON.parse(String(call[1]?.body)) }
}

describe('api client', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('returns the parsed body on success', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse([{ id: 's1', title: 'First chat' }]))

    const sessions = await api.listSessions()

    expect(sessions).toEqual([{ id: 's1', title: 'First chat' }])
  })

  it('preserves the backend error code, message and remedy', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse(
        {
          error: {
            code: 'provider_unavailable',
            message: 'Ollama is not reachable at http://localhost:11434.',
            remedy: 'Start Ollama with `ollama serve`.',
          },
        },
        503,
      ),
    )

    const error = await captureError(() => api.listSessions())

    expect(error).toBeInstanceOf(ApiError)
    expect(error.code).toBe('provider_unavailable')
    expect(error.status).toBe(503)
    expect(error.message).toContain('not reachable')
    expect(error.remedy).toBe('Start Ollama with `ollama serve`.')
  })

  it('falls back to a status-based message when the body is not an error envelope', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response('gateway timeout', { status: 504 }))

    const error = await captureError(() => api.listSessions())

    expect(error.code).toBe('http_error')
    expect(error.status).toBe(504)
    expect(error.message).toContain('504')
  })

  it('reports a transport failure as an actionable network error', async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError('Failed to fetch'))

    const error = await captureError(() => api.listSessions())

    expect(error.code).toBe('network_error')
    expect(error.status).toBe(0)
    expect(error.remedy).toContain('backend is running')
  })

  it('tolerates an empty 204 response on delete', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 204 }))

    await expect(api.deleteSession('s1')).resolves.toBeUndefined()
  })

  it('sends the session id and message when posting a chat turn', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ session_id: 's1' }))

    await api.sendMessage('s1', 'How do I improve activation?')

    expect(firstRequest().body).toEqual({
      session_id: 's1',
      message: 'How do I improve activation?',
    })
  })

  it('sends an explicit Ollama provider on a chat turn', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ session_id: 's1' }))

    await api.sendMessage('s1', 'How do I improve activation?', 'ollama')

    expect(firstRequest().body).toEqual({
      session_id: 's1',
      message: 'How do I improve activation?',
      provider: 'ollama',
    })
  })

  it('sends an explicit Anthropic provider on a chat turn', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ session_id: 's1' }))

    await api.sendMessage('s1', 'hello', 'anthropic')

    expect(firstRequest().body.provider).toBe('anthropic')
  })

  it('sends the selected provider when generating an artifact', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ session_id: 's1' }))

    await api.generateArtifact('s1', 'html', 'Landing page', 'anthropic')

    expect(firstRequest().url).toBe('/api/artifacts')
    expect(firstRequest().body.provider).toBe('anthropic')
  })

  it('posts the artifact type and instruction to the artifact endpoint', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ session_id: 's1' }))

    await api.generateArtifact('s1', 'html', 'Landing page')

    const { url, body } = firstRequest()
    expect(url).toBe('/api/artifacts')
    expect(body).toEqual({
      session_id: 's1',
      artifact_type: 'html',
      instruction: 'Landing page',
    })
  })
})
