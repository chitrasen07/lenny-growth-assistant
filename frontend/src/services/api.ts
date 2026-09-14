/**
 * Typed API client.
 *
 * Every backend failure arrives as `{"error": {code, message, remedy?}}`, so this module
 * normalises it into a single `ApiError` that carries the remedy through to the UI. That
 * is what lets the interface say "start Ollama with `ollama serve`" instead of
 * "something went wrong".
 */

import type {
  Artifact,
  ArtifactType,
  ChatResponse,
  ConfigResponse,
  HealthResponse,
  Message,
  ProviderName,
  SessionSummary,
} from '../types/api'

// Empty in Docker (same-origin, proxied by nginx) and in dev (proxied by Vite).
const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export class ApiError extends Error {
  readonly code: string
  readonly remedy?: string
  readonly status: number

  constructor(message: string, code: string, status: number, remedy?: string) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.remedy = remedy
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    })
  } catch {
    // fetch only rejects on a transport failure, which the user cannot act on inside the app.
    throw new ApiError(
      'Could not reach the API.',
      'network_error',
      0,
      'Check that the backend is running, then retry.',
    )
  }

  if (response.status === 204) return undefined as T

  const body = await response.json().catch(() => null)

  if (!response.ok) {
    const error = (body as { error?: { code?: string; message?: string; remedy?: string } } | null)?.error
    throw new ApiError(
      error?.message ?? `Request failed with status ${response.status}.`,
      error?.code ?? 'http_error',
      response.status,
      error?.remedy,
    )
  }

  return body as T
}

export const api = {
  health: () => request<HealthResponse>('/health'),

  config: () => request<ConfigResponse>('/api/config'),

  listSessions: () => request<SessionSummary[]>('/api/sessions'),

  createSession: (title?: string) =>
    request<SessionSummary>('/api/sessions', {
      method: 'POST',
      body: JSON.stringify(title ? { title } : {}),
    }),

  deleteSession: (sessionId: string) =>
    request<void>(`/api/sessions/${sessionId}`, { method: 'DELETE' }),

  listMessages: (sessionId: string) => request<Message[]>(`/api/sessions/${sessionId}/messages`),

  sendMessage: (sessionId: string, message: string, provider?: ProviderName) =>
    request<ChatResponse>('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, message, ...(provider ? { provider } : {}) }),
    }),

  generateArtifact: (
    sessionId: string,
    artifactType: ArtifactType,
    instruction: string,
    provider?: ProviderName,
  ) =>
    request<ChatResponse>('/api/artifacts', {
      method: 'POST',
      body: JSON.stringify({
        session_id: sessionId,
        artifact_type: artifactType,
        instruction,
        ...(provider ? { provider } : {}),
      }),
    }),

  latestArtifact: (sessionId: string) =>
    request<Artifact>(`/api/artifacts/session/${sessionId}/latest`),
}
