/** Types mirroring the FastAPI response schemas in backend/app/schemas. */

export type ProviderName = 'ollama' | 'anthropic'
export type MessageRole = 'user' | 'assistant'
export type ArtifactType = 'markdown' | 'html'

export interface SessionSummary {
  id: string
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

/**
 * A cited transcript excerpt. Optional fields are absent when the source transcript did
 * not declare them — the UI omits them rather than showing a placeholder.
 */
export interface Source {
  chunk_id: string
  transcript_id: string
  title: string
  episode: string | null
  guest: string | null
  source_url: string | null
  source_file: string
  chunk_index: number
  speaker: string | null
  excerpt: string
  /** Cosine distance; lower is a closer match. */
  distance: number
  /** The [S{marker}] reference used in the answer text. */
  marker: number
  /** True when the answer actually referenced this source. */
  cited: boolean
}

export interface SanitiserReport {
  removed_tags: Record<string, number>
  removed_attributes: Record<string, number>
  removed_urls: number
  css_rules_stripped: number
  comments_removed: number
  modified: boolean
}

export interface Artifact {
  id: string
  type: ArtifactType
  title: string
  content: string
  sanitised: boolean
  sanitiser_report: SanitiserReport | Record<string, never>
  created_at: string
}

export interface MessageMetadata {
  provider?: string
  model?: string
  intent?: string
  refused?: boolean
  word_count?: number
  target_words?: number
  within_tolerance?: boolean
  refusal_reason?: string
  uncited_answer?: boolean
  timings_ms?: Record<string, number>
  [key: string]: unknown
}

export interface Message {
  id: string
  session_id: string
  role: MessageRole
  content: string
  created_at: string
  metadata: MessageMetadata
  sources: Source[]
  artifact: Artifact | null
}

export interface ChatResponse {
  session_id: string
  message: Message
  provider: ProviderName
  model: string
  intent: string
  grounded: boolean
  timings_ms: Record<string, number>
}

export interface ComponentHealth {
  healthy: boolean
  detail: string | null
}

export interface KnowledgeBaseStatus {
  transcripts: number
  chunks: number
  embedding_model: string
  embedding_dimensions: number
  ready: boolean
}

export interface HealthResponse {
  status: 'ok' | 'degraded'
  version: string
  api: ComponentHealth
  database: ComponentHealth
  llm_provider: string
  llm_model: string
  agent_runtime: string
  active_runtime: string
  ollama: ComponentHealth
  cloud_provider: ComponentHealth
  knowledge_base: KnowledgeBaseStatus | null
}

export interface ProviderInfo {
  name: string
  model: string
  available: boolean
  detail: string | null
  /** Runtime AgentService constructs when this provider is selected. */
  runtime: string
}

export interface ConfigResponse {
  active_provider: string
  active_model: string
  agent_runtime: string
  active_runtime: string
  providers: ProviderInfo[]
  retrieval_top_k: number
  essay_target_words: number
  knowledge_base: KnowledgeBaseStatus
}

/** Normalised form of the backend's `{"error": {...}}` envelope. */
export interface ApiErrorPayload {
  code: string
  message: string
  remedy?: string
  details?: Record<string, unknown>
}
