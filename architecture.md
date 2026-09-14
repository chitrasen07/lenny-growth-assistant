# Architecture

Technical reference for The Lenny Growth Assistant. Product intent is in
[`PRD.md`](PRD.md), UI reasoning in [`design.md`](design.md), operator instructions in
[`README.md`](README.md).

---

## 1. System architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Browser                                                                     │
│  ┌───────────────────────────┬────────────────────────────────────────────┐  │
│  │  Chat pane                │  Artifact Viewer                            │  │
│  │  messages · sources       │  ┌──────────────────────────────────────┐  │  │
│  │  composer                 │  │ iframe sandbox (NO allow-scripts)     │  │  │
│  │                           │  │ generated HTML renders here           │  │  │
│  │                           │  └──────────────────────────────────────┘  │  │
│  └───────────────────────────┴────────────────────────────────────────────┘  │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ HTTP, same origin
┌──────────────────────────────────────▼──────────────────────────────────────┐
│  nginx (frontend container)                                                  │
│  serves built SPA · proxies /api/* and /health to backend:8000               │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
┌──────────────────────────────────────▼──────────────────────────────────────┐
│  FastAPI (backend container)                                                 │
│                                                                              │
│  middleware:  request-id  →  body-size limit  →  CORS                        │
│  exception handlers:  AppError / RequestValidationError / HTTPException       │
│                                                                              │
│  ┌────────────────────────┐          ┌──────────────────────────────────┐   │
│  │  ChatService           │  calls   │  AgentService                     │   │
│  │  ─────────────────────  │ ───────► │  ────────────────────────────────  │   │
│  │  validate input        │          │  pick runtime (config)            │   │
│  │  persist user turn     │          │  build SkillContext               │   │
│  │  persist assistant     │          │  ┌─────────────┬───────────────┐  │   │
│  │    turn + sources      │          │  │ RouterRuntime│ ClaudeSDK     │  │   │
│  │    + artifact          │          │  │ (default)    │ Runtime       │  │   │
│  └──────────┬─────────────┘          │  └──────┬──────┴───────┬───────┘  │   │
│             │                        │         │  SkillRegistry│          │   │
│  ┌──────────▼─────────────┐          │  ┌──────▼──────────────▼───────┐  │   │
│  │  SessionService        │          │  │ search_transcripts           │  │   │
│  │  create · list · get   │          │  │ answer_grounded_question     │  │   │
│  │  history_for_prompt    │          │  │ generate_ship30_essay        │  │   │
│  └──────────┬─────────────┘          │  │ generate_artifact            │  │   │
│             │                        │  └──────┬───────────────┬──────┘  │   │
│             │                        └─────────┼───────────────┼─────────┘   │
│             │                                  │               │             │
│             │                    ┌─────────────▼──┐   ┌────────▼─────────┐  │
│             │                    │ RetrievalService│   │ ArtifactBuilder  │  │
│             │                    │ embed · KNN     │   │ + Sanitiser      │  │
│             │                    │ threshold · cap │   └──────────────────┘  │
│             │                    └─────────────┬──┘                          │
│             │                                  │                             │
│             │                    ┌─────────────▼───────────────┐             │
│             │                    │  LLMProvider (interface)     │             │
│             │                    │  Ollama  │  Anthropic        │             │
│             │                    └──────────┬──────────────────┘             │
└─────────────┼───────────────────────────────┼────────────────────────────────┘
              │                               │
┌─────────────▼───────────────┐   ┌───────────▼──────────────┐
│  PostgreSQL 16 + pgvector    │   │  Ollama daemon (HOST)     │
│  (db container)              │   │  llama3.1:8b              │
│                              │   │  nomic-embed-text         │
│  sessions · messages         │   └───────────────────────────┘
│  message_sources · artifacts │   ┌───────────────────────────┐
│  transcripts                 │   │  Anthropic API (optional)  │
│  transcript_chunks(vector)   │   └───────────────────────────┘
└──────────────────────────────┘
```

Layering rule: routes never touch the database or a provider directly. Routes validate and
delegate to a service; services own transactions; skills own prompting; providers own
transport. Each layer's failures are translated into one error taxonomy at its boundary.

## 2. Frontend components

```
App.tsx
├── AppHeader          provider/model badge, agent runtime, indexed chunk count
├── StatusBanner       blocking setup problems + the exact command that fixes each
├── ErrorBanner        session-level failures (code, message, remedy)
└── app__body
    ├── SessionSidebar new chat, session list, delete
    └── app__main  (CSS grid: chat | artifact)
        ├── ChatPanel
        │   ├── EmptyState        what the product does; example prompts; KB warning
        │   ├── MessageBubble[]   author, timestamp, rendered content, metadata
        │   │   └── SourceList    cited sources first; retrieved-not-cited collapsed
        │   ├── pending indicator staged progress + elapsed seconds
        │   ├── ErrorBanner
        │   └── Composer          textarea, char limit, Enter to send
        └── ArtifactViewer
            ├── SanitiserNote     what was stripped, when anything was
            ├── iframe            HTML artifacts (sandboxed, no allow-scripts)
            ├── markdown-body     Markdown artifacts (marked + DOMPurify)
            └── generation form   format select + instruction
```

State lives in three hooks, each owning one concern:

| Hook | Owns |
| --- | --- |
| `useConfig` | `/api/config` + `/health`; drives the header and status banner; refreshable |
| `useSessions` | Session list, active id, create/delete, activity ordering |
| `useChat` | Messages, artifact, in-flight stage, elapsed time, errors for the active session |

`useChat` guards against a stale response from a previous session overwriting the current
one by recording the session a request was issued for and discarding late replies. The
user's own message is shown optimistically (it is already persisted server-side) and kept
on failure so nothing has to be retyped.

Services: `services/api.ts` (typed client, normalises the error envelope into `ApiError`)
and `services/markdown.ts` (marked → DOMPurify, plus `[Sn]` marker highlighting).

## 3. Backend components

| Module | Responsibility |
| --- | --- |
| `api/routes/*` | HTTP surface: validate, delegate, return typed responses |
| `api/middleware.py` | Request id for log correlation; body size limit |
| `api/errors.py` | Exception handlers producing one JSON error envelope |
| `api/deps.py` | DI for the database session and settings |
| `services/sessions.py` | Session CRUD, message listing, bounded `history_for_prompt` |
| `services/chat.py` | Orchestrates a turn: validate → persist user → agent → persist assistant + sources + artifact |
| `agent/service.py` | Chooses the runtime, assembles `SkillContext` |
| `agent/runtimes/router.py` | Deterministic one-skill-per-turn dispatch (default) |
| `agent/runtimes/claude_sdk.py` | Claude Agent SDK; skills exposed as in-process MCP tools |
| `agent/registry.py` | Single source of truth for available skills |
| `agent/routing.py` | Intent classification from the message text |
| `agent/prompts.py` | System prompts, Ship 30 principles, canonical refusal |
| `agent/citations.py` | Extract, strip-invalid and verify `[Sn]` markers |
| `agent/skills/*` | One file per skill; each owns its prompt and post-processing |
| `rag/loader.py` | Discover files, read declared metadata (never infer) |
| `rag/chunking.py` | Clean, split into speaker turns, pack overlapping chunks |
| `rag/embeddings.py` | `Embedder` interface; Ollama and deterministic hash implementations |
| `rag/ingestion.py` | Idempotent pipeline with per-file failure isolation |
| `rag/retrieval.py` | Query construction, KNN, threshold, diversity cap, context budget |
| `artifacts/builder.py` | Strip fences, extract title, dispatch sanitising |
| `artifacts/sanitizer.py` | HTML allowlist, CSS filtering, CSP injection, removal report |
| `providers/*` | `LLMProvider` interface, Ollama, Anthropic, caching factory |
| `core/config.py` | Settings from environment, with enums for provider/runtime/embedder |
| `core/errors.py` | `AppError` taxonomy: code, HTTP status, message, remedy |
| `core/logging.py` | structlog configuration; JSON or console; secret censoring |
| `core/runtime.py` | Windows selector event-loop policy for `psycopg` |
| `db/session.py` | Async engine, pooling, timeouts, health check |

## 4. Database schema

```
sessions
  id           uuid  PK
  title        varchar(200)      default 'New chat'
  created_at   timestamptz
  updated_at   timestamptz       ix_sessions_updated_at

messages
  id           uuid  PK
  seq          bigint            default nextval('messages_seq')
  session_id   uuid  FK sessions(id) ON DELETE CASCADE
  role         varchar(20)       'user' | 'assistant'
  content      text
  created_at   timestamptz
  metadata     jsonb             provider, model, intent, skill, timings, refusal_reason
                                 ix_messages_session_id, ix_messages_session_seq(session_id, seq)

message_sources                  ← the citation join; makes a claim traceable
  id           uuid  PK
  message_id   uuid  FK messages(id)          ON DELETE CASCADE
  chunk_id     uuid  FK transcript_chunks(id) ON DELETE CASCADE
  rank         integer           retrieval order → the [Sn] marker number
  distance     float             cosine distance at retrieval time
  cited        boolean           did the answer actually reference it

transcripts
  id           uuid  PK
  source_file  varchar(500) UNIQUE   idempotency key
  content_hash varchar(64)           sha256 of transcript text → change detection
  title        varchar(500)
  episode      varchar(300)  NULL    ─┐
  guest        varchar(300)  NULL     │ NULL when the file did not declare it.
  source_url   varchar(1000) NULL    ─┘ Never inferred.
  chunk_count  integer
  ingested_at  timestamptz

transcript_chunks
  id             uuid  PK
  transcript_id  uuid  FK transcripts(id) ON DELETE CASCADE
  chunk_index    integer            UNIQUE(transcript_id, chunk_index)
  content        text
  speaker        varchar(200) NULL  set only when the chunk has exactly one speaker
  char_start     integer   ─┐ offsets into the cleaned text: locate the excerpt
  char_end       integer   ─┘ in the original file
  token_estimate integer
  embedding      vector(768)        ix_chunk_embedding_hnsw (vector_cosine_ops)
  created_at     timestamptz

artifacts
  id               uuid  PK
  session_id       uuid  FK sessions(id)  ON DELETE CASCADE
  message_id       uuid  FK messages(id)  ON DELETE CASCADE
  type             varchar(20)   'markdown' | 'html'
  title            varchar(300)
  content          text          post-sanitisation content — what the viewer renders
  sanitised        boolean
  sanitiser_report jsonb         what was removed; surfaced in the UI
  created_at       timestamptz
```

Three notes on choices that were not obvious:

**`seq` rather than `created_at` for ordering.** PostgreSQL's `now()` is transaction-scoped,
so a user message and its assistant reply written in one transaction carry an identical
timestamp and their relative order becomes undefined. A sequence-backed column makes
ordering total and stable. This surfaced as a flaky test, not a design review.

**HNSW rather than IVFFlat.** IVFFlat needs a training pass over existing vectors to build
its lists, which is wrong for an index that starts empty and grows one transcript at a time.
HNSW needs no training and gives good cosine recall immediately.

**`cited` is stored, not derived.** The distinction between "the model was given this" and
"the model used this" is the product's honesty claim, so it is persisted at write time and
survives a page reload.

Migrations are Alembic, applied by `entrypoint.sh` at container start with a retry loop
while the database becomes ready. Every foreign key cascades, so deleting a session removes
its messages, citations and artifacts in one statement.

## 5. API endpoints

| Method | Path | Success | Notable failures |
| --- | --- | --- | --- |
| `GET` | `/health` | `200` always when the API is up | Reports component state in the body; a missing optional cloud provider never makes it fail |
| `GET` | `/api/config` | `200` | – |
| `POST` | `/api/sessions` | `201` | `422` invalid title |
| `GET` | `/api/sessions` | `200` | `503` database unavailable |
| `GET` | `/api/sessions/{id}` | `200` | `404` unknown session |
| `DELETE` | `/api/sessions/{id}` | `204` | `404` |
| `GET` | `/api/sessions/{id}/messages` | `200` | `404` |
| `POST` | `/api/chat` | `200` | `404` unknown session · `422` blank/oversized message · `503` provider unavailable · `504` timeout |
| `POST` | `/api/artifacts` | `200` | as above, plus `422` invalid artifact type |
| `GET` | `/api/artifacts/session/{id}/latest` | `200` | `404` none yet |

A refusal is **`200`, not an error**: the system worked correctly and produced an honest
answer. `grounded: false` and `metadata.refusal_reason` describe it, so the UI can present
it as an answer rather than a failure.

Error envelope:

```json
{ "error": { "code": "provider_unavailable",
             "message": "Ollama is not reachable at http://host.docker.internal:11434.",
             "remedy": "Start Ollama with `ollama serve`, then retry.",
             "details": { } } }
```

Codes are stable and machine-readable so the frontend can branch on them without parsing
prose: `validation_failed`, `not_found`, `database_unavailable`, `provider_unavailable`,
`provider_not_configured`, `provider_timeout`, `provider_error`, `embedding_failed`,
`knowledge_base_empty`, `artifact_generation_failed`, `payload_too_large`, `internal_error`.

## 6. Agent architecture

```
                       AgentService
                            │  provider name
              ┌─────────────┴─────────────┐
              ▼                           ▼
      RouterRuntime                ClaudeAgentSDKRuntime
      (Ollama)                     (Anthropic)
      deterministic dispatch       Claude Agent SDK picks tools
              │                           │
              └─────────────┬─────────────┘
                            ▼
                      SkillRegistry            ← one definition, both runtimes
              ┌──────────┬────────────┬──────────────────┐
              ▼          ▼            ▼                  ▼
    search_        answer_        generate_         generate_
    transcripts    grounded_      ship30_essay      artifact
                   question
```

Both runtimes implement one `AgentRuntime` protocol (`plan`, `run`) and share one
`SkillRegistry`, so a skill is defined once and behaves the same whichever runtime invokes
it. That is what makes the two runtimes genuinely interchangeable rather than parallel
implementations.

### Why each skill exists

| Skill | Why it is a separate skill |
| --- | --- |
| `search_transcripts` | Retrieval without generation. Lets the SDK runtime gather evidence as its own step, and makes retrieval independently inspectable and testable |
| `answer_grounded_question` | The default path. Owns the grounding contract: refuse below threshold, cite inline, verify markers afterwards |
| `generate_ship30_essay` | A different task, not a longer answer: broader retrieval (`essay_top_k`, higher per-episode cap), a distinct style prompt, word counting (target 1,250, range 1,062–1,437), at most 3 generations, post-cleanup continue, 4–6 H2 cap. The assignment explicitly requires it not be an inline prompt in the chat handler |
| `generate_artifact` | Produces a document, not a chat reply: format-specific prompts, fence stripping, title extraction, sanitising, and a separate persisted entity |

### Routing (default runtime)

```
user message
   │
   ├─ matches essay intent   ("ship 30", "write an essay about …")
   │     └─► retrieve (broad)  ─►  generate_ship30_essay
   │
   ├─ matches artifact intent ("create a landing page", "make HTML", "markdown doc")
   │     └─► conversation context (+ best-effort evidence) ─► generate_artifact
   │
   └─ otherwise
         └─► retrieve (top-k)  ─►  answer_grounded_question
```

Exactly one skill runs per turn. The model is called **inside** the chosen skill, never to
decide control flow — see §20 for why.

## 7. RAG pipeline

```
data/transcripts/*.{txt,md,vtt,srt,json}
   │
   │ loader.py     discover recursively; skip README/LICENSE-style docs and metadata.json
   │               read metadata from front matter | metadata.json sidecar | JSON fields
   │               precedence: front matter > sidecar > filename-derived title
   │               undeclared fields stay NULL — never inferred
   ▼
   │ chunking.py   clean_transcript: strip WEBVTT headers, cue numbers, timestamps;
   │                                normalise whitespace; keep "Speaker:" labels
   │               split_turns:      segment into speaker turns with char offsets
   │               chunk_turns:      pack turns to ~1200 chars with ~150 overlap,
   │                                 preferring turn boundaries; split over-long turns
   │                                 on sentence boundaries (budgeting for the speaker
   │                                 prefix so a chunk never exceeds the limit)
   ▼
   │ embeddings.py OllamaEmbedder → nomic-embed-text, 768-dim, batched
   ▼
   │ ingestion.py  per file: hash → unchanged? skip. changed? delete old chunks, re-index.
   │               new? index. Failures are isolated per file and reported at the end.
   ▼
transcripts + transcript_chunks(embedding vector(768))
```

Idempotency is a content hash per file, so re-running embeds nothing when nothing changed.
Absence is never a delete instruction — a mistyped `--dir` cannot wipe the index.

## 8. Retrieval strategy

```
question + bounded prior context
   │
   │  build query   follow-ups are composed with recent turns so "what about B2B SaaS?"
   │                retrieves sensibly; history informs interpretation, never evidence
   ▼
   │  embed with the SAME model used for documents
   ▼
   │  ORDER BY embedding <=> :query LIMIT top_k     (pgvector HNSW, cosine)
   ▼
   │  filter  distance > RETRIEVAL_MAX_DISTANCE          → drop
   │  cap     max chunks per episode                     → diversity
   │  cap     total context characters                   → prompt size
   ▼
   0 chunks left?  ──►  REFUSE. No LLM call. metadata.refusal_reason set.
   │
   ▼
   numbered EVIDENCE block  →  skill  →  LLM
```

Parameters and why they exist:

| Parameter | Default | Purpose |
| --- | --- | --- |
| `retrieval_top_k` | 6 | Enough evidence for a synthesised answer; small enough for an 8B context window |
| `retrieval_max_distance` | 0.55 | **The refusal dial.** Cosine distance ceiling for "relevant" |
| `retrieval_max_chunks_per_episode` | 2 | Stops one episode monopolising the evidence, so answers synthesise across sources |
| `retrieval_context_char_budget` | 9000 | Hard prompt-size ceiling |
| `essay_top_k` | 12 | Essays need more material than a single answer |
| `essay_max_chunks_per_episode` | 6 | An essay may legitimately lean on one deep-dive episode |
| `essay_context_char_budget` | 16000 | Correspondingly larger |

The per-episode cap was originally applied uniformly, which made essays refuse whenever
the corpus had few but highly relevant episodes — the cap starved the essay of evidence
before the length target could be met. Retrieval now accepts a per-call override and the
essay skill passes its own, which is why two sets of parameters exist.

## 9. Model abstraction

```python
class LLMProvider(ABC):
    name: str
    model: str
    async def chat(messages, *, system, temperature, max_tokens) -> LLMResponse
    async def chat_with_tools(messages, tools, *, system, ...) -> LLMResponse
    async def embed(texts) -> list[list[float]]
    async def health() -> ProviderHealth
    async def close() -> None
```

Shared value types (`ChatMessage`, `ToolSpec`, `ToolCall`, `LLMResponse`, `ProviderHealth`)
mean skills never see a provider-specific shape. Each provider translates its own
transport and SDK errors into the shared `AppError` taxonomy at its boundary, so callers
handle one set of failure modes.

A caching factory returns one instance per provider per process; `close_providers()` runs
at shutdown. `LLM_PROVIDER` selects the default, and `/api/chat` accepts a per-request
override for comparing providers within one session.

## 10. Ollama integration

Plain HTTP via `httpx` against `/api/chat`, `/api/embed` and `/api/tags` — no SDK, because
the surface used is small and this keeps the dependency list and failure translation
obvious.

Ollama runs **on the host**, reached at `host.docker.internal:11434`
(`extra_hosts: host-gateway` makes that resolve on Linux too). Rationale: a containerised
Ollama loses GPU/Metal access and falls back to CPU inference, and would re-download
several GB of models the evaluator probably already has.

It serves both roles: `llama3.1:8b` for chat, `nomic-embed-text` (768-dim) for embeddings —
so the entire RAG path is local with no cloud account.

Failure translation:

| Condition | Result |
| --- | --- |
| Connection refused | `provider_unavailable`, message names the URL tried |
| Model not pulled (404 from Ollama) | `provider_unavailable`, remedy names `ollama pull <model>` |
| Read timeout | `provider_timeout`, remedy suggests a smaller model or longer timeout |
| Malformed response | `provider_error`, raw detail logged not returned |

## 11. Cloud LLM integration

Anthropic via the official SDK. The provider maps the shared message shape onto Anthropic's
API: a top-level `system` parameter (not a system role), content blocks, and `tool_use` /
`tool_result` blocks for tool calling.

The API key is read from the environment only, is never logged (structlog censors it), and
is never returned by any endpoint — `/api/config` reports *whether* it is configured. A test
asserts a planted key value never appears in a serialised response.

Selecting `anthropic` with no key is a configuration error (`provider_not_configured`) with
a remedy, surfaced at request time and in `/health` — not a crash and not a silent fallback.

### Claude Agent SDK runtime

Selecting the Anthropic provider (header toggle or `LLM_PROVIDER=anthropic`) uses
`ClaudeAgentSDKRuntime`. It exposes the same four skills as in-process MCP tools and lets
Claude choose among them. It requires `ANTHROPIC_API_KEY` and `claude-agent-sdk` (in
production `requirements.txt`, so it ships in the runtime image). Missing key or package
raises a clear configuration error. Its integration contract is tested against a stubbed
SDK: skills are registered as tools, citation-validated skill text is not overwritten by
the SDK restatement, and misconfiguration is explicit.

Live Anthropic generation has not been run (no API key). Ollama is the demo path because
the SDK cannot drive a local model — see §20.

`AGENT_RUNTIME` is still loaded from the environment for compatibility. It is **not** the
dispatcher.

## 12. Artifact generation

```
conversation (+ best-effort retrieved evidence)
   │
   │  format-specific system prompt (Markdown | full HTML+CSS)
   ▼
   raw model output
   │
   │  builder.py   strip surrounding code fences (models add them despite instructions)
   │               extract the title from the H1 / <title>, else derive from the request
   │               HTML → sanitizer.py; Markdown → stored as text, sanitised at render
   ▼
   Artifact(type, title, content, sanitised, sanitiser_report)
   │
   │  persisted, linked to both the message and the session
   ▼
   returned inside the chat response → rendered in the Artifact Viewer
```

Artifacts are a **separate persisted entity**, not a chat message containing markup. That
is what lets the viewer restore the latest artifact on reload and keeps raw HTML out of the
conversation transcript.

Artifact generation is the one path with deliberately looser grounding: a landing page is a
design deliverable, not a factual claim. Transcript-derived claims must still carry markers,
and the prompt requires visible placeholders (`[your product name]`) rather than invented
specifics — no fake metrics, testimonials or customer names.

## 13. Artifact security

Three layers, in increasing order of how much is relied on:

```
1. PROMPT           "no script, no inline handlers, no external resources"
   │                → improves output quality. NOT a security control.
   ▼
2. SANITISER        allowlist parse (server-side, artifacts/sanitizer.py)
   │                • allow: structure, text semantics, lists, tables, links, img, <style>
   │                • drop with subtree: script, iframe, object, embed, applet, form,
   │                  input, select, textarea, link, base, svg, math, template,
   │                  noscript, frame, frameset
   │                • strip: every on* handler
   │                • strip: javascript:, vbscript:, file:, about:, blob:,
   │                         non-image data: URLs
   │                • CSS: remove whole declarations containing @import, expression(),
   │                       url(javascript:…), -moz-binding, behavior
   │                • inject: <meta CSP> default-src 'none'; script-src 'none'; …
   │                • report what was removed → shown in the UI
   ▼
3. SANDBOXED IFRAME <iframe sandbox="allow-same-origin" srcDoc={html}>
                    → no allow-scripts: the browser will not execute script at all
                    → srcDoc: never innerHTML in the parent document
                    → withheld: allow-forms, allow-popups, allow-top-navigation
                    THIS is the boundary the design relies on.
```

Why a hand-written allowlist rather than `bleach`: generating full HTML **with CSS** is a
requirement, and general-purpose cleaners escape `<style>` contents, breaking every
generated page. So `<style>` text is preserved and filtered for CSS-borne script vectors
instead.

Markdown takes a different path: `marked` → **DOMPurify** with an explicit tag/attribute
allowlist and a URI regex permitting only `http(s)`, `mailto:` and fragments.

Limitations are stated in [README §Artifact Security](README.md#artifact-security): the
server filter is syntactic rather than a browser; a `<meta>` CSP is weaker than a real
header; and there is no authentication.

## 14. Logging

structlog, JSON by default (`LOG_FORMAT=console` for local readability). Every log line for
one request carries the same `request_id`, injected by middleware, so a single chat turn can
be reconstructed from one grep.

Events emitted, and the fields that make them useful:

| Event | Fields |
| --- | --- |
| `request_started` / `request_completed` | method, path, status, duration_ms, request_id |
| `session_created` | session_id |
| `chat_request` / `chat_completed` | session_id, intent, provider, model, grounded, duration_ms |
| `agent_started` / `agent_routed` | runtime, provider, model, intent, reason, history_turns |
| `retrieval_completed` | candidates, selected, best_distance, max_distance, per_episode_cap, context_chars, latency_ms |
| `provider_call_completed` / `provider_call_failed` | provider, model, latency_ms, error_type |
| `ingestion_started` / `_file_indexed` / `_completed` | source_file, chunks, indexed, updated, skipped, failures, duration_ms |
| `transcript_metadata_incomplete` | source_file, warning — flags citations that will lack a URL |
| `artifact_generated` | type, title, sanitised, removal counts |
| `database_unavailable` | error_type |

`retrieval_completed` is the diagnostic that matters most: `candidates` vs `selected` with
`best_distance` against `max_distance` says immediately whether a refusal was correct or the
threshold is misconfigured.

Never logged: API keys, full prompts or full transcript text (chunk ids and counts instead).
structlog is configured to censor secret-shaped values.

## 15. Failure handling

| Failure | Detection | Behaviour |
| --- | --- | --- |
| Missing/invalid env var | Pydantic settings at startup | Fails fast with the offending field named |
| Database unavailable | `SQLAlchemyError` → `DatabaseUnavailableError` | `503` + remedy; `/health` reports it; UI banner |
| Database timeout | Connect/statement timeout | Same as above, distinct log event |
| Ollama down | `httpx.ConnectError` | `503 provider_unavailable` naming the URL |
| Model not pulled | Ollama `404` | `503` with `ollama pull` remedy |
| LLM timeout | `httpx.ReadTimeout` | `504 provider_timeout` |
| Cloud key missing | Config check | `503 provider_not_configured` |
| Embedding failure | Embedder error | `embedding_failed`; ingestion isolates it per file |
| Empty retrieval | 0 chunks past threshold | **`200` + honest refusal, no LLM call** |
| Empty knowledge base | Count check | Refusal with `refusal_reason: knowledge_base_empty` + UI banner |
| Ingestion failure | Per-file try/except | Logged, reported in the summary, run continues, exit code non-zero |
| Invalid generated artifact | Builder validation | `artifact_generation_failed` with a remedy |
| Unsafe artifact HTML | Sanitiser | Silently repaired, removals reported in the UI |
| Oversized request | Body-size middleware + field limits | `413` / `422` before any model call |
| Unexpected exception | Catch-all handler | `500 internal_error`, generic message out, full traceback logged |

Two rules hold throughout: an expected failure is an `AppError` with a code and a remedy,
never a bare 500; and no error message ever contains a secret.

## 16. Docker topology

```
┌─ host ────────────────────────────────────────────────────────────┐
│  Ollama daemon :11434   (GPU/Metal, models on host disk)          │
│                                ▲                                  │
│  ┌─ compose network ───────────┼───────────────────────────────┐  │
│  │                             │ host.docker.internal          │  │
│  │  frontend  :3000→80 ──────► backend :8000 ──────► db :5432  │  │
│  │  nginx: SPA + /api proxy    FastAPI            pgvector/pg16│  │
│  │                             ▲                       ▲       │  │
│  │                             │ ro mount              │ volume│  │
│  │  tests (profile: test) ─────┘                  postgres_data│  │
│  └─────────────────────────────────────────────────────────────┘  │
│     ./data/transcripts ──ro──► /data/transcripts                  │
│     ./data/sample-transcripts ──ro──► /data/sample-transcripts     │
└───────────────────────────────────────────────────────────────────┘

host ports:  3000 UI   ·   8000 API   ·   5433 Postgres
```

- `db` uses `pgvector/pgvector:pg16`, so the extension needs no build step or manual install.
- Startup order is enforced with `depends_on: condition: service_healthy`, and migrations
  retry while the database becomes ready, so `docker compose up` works on a clean machine.
- Transcripts are **mounted, not copied**, so adding one needs no image rebuild.
- Host Postgres port is 5433 to coexist with an existing local Postgres; inside the network
  it is always 5432.
- The backend image is multi-stage: `runtime` (non-root, production deps including
  `claude-agent-sdk`) and `test` (pytest, ruff). pytest/ruff do not ship in the served
  image; the SDK does, because Anthropic chat uses `ClaudeAgentSDKRuntime`.
- nginx proxies `/api` so the browser sees one origin and needs no CORS in the Docker path,
  and adds `X-Content-Type-Options`, `X-Frame-Options` and `Referrer-Policy` to the shell.

## 17. Configuration

One source: environment variables → `core/config.py` (`pydantic-settings`), read through a
cached `get_settings()`. Nothing reads `os.environ` directly, so every setting has one
declared type, default and validation point.

Enums (`LLMProviderName`, `AgentRuntimeName`, `EmbeddingProviderName`) mean an invalid value
fails at startup with the field named, rather than deep inside a request. `CORS_ORIGINS` is
annotated `NoDecode` so it can be the comma-separated list an operator would naturally
write rather than a JSON array.

`/api/config` exposes only non-secret values: active provider, model, `active_runtime`
(the runtime for that default provider), a `runtime` field on each provider, retrieval
parameters and index statistics — never a key. The header uses the selected provider's
`runtime` (`router` for Ollama, `claude_agent_sdk` for Anthropic).

## 18. Data flow

**A grounded question**

```
Composer
  → POST /api/chat {session_id, message}
    → middleware: request_id, body size
    → ChatService.handle
      ├─ validate; 404 if the session is unknown
      ├─ persist the user message (role=user)
      ├─ SessionService.history_for_prompt  (bounded by count and characters)
      ├─ AgentService.handle
      │   ├─ RouterRuntime.plan → Intent.QUESTION
      │   └─ GroundedAnswerSkill.run
      │       ├─ RetrievalService.retrieve(question, history)
      │       │   ├─ embed query
      │       │   ├─ pgvector cosine KNN, top_k
      │       │   ├─ drop beyond max_distance; cap per episode; cap context chars
      │       │   └─ 0 chunks → return refusal  ⟹ NO LLM CALL
      │       ├─ build numbered EVIDENCE block
      │       ├─ provider.chat(system=GROUNDED_ANSWER_SYSTEM, …)
      │       └─ citations: strip invalid [Sn]; flag chunks actually cited
      └─ persist assistant message + message_sources(rank, distance, cited)
    ← 200 {message, sources[], provider, model, intent, grounded, timings_ms}
  → MessageBubble renders content with highlighted markers
  → SourceList shows cited first, retrieved-not-cited collapsed
```

**An artifact**

```
POST /api/artifacts {session_id, artifact_type, instruction}
  → ChatService → AgentService → ArtifactSkill
      ├─ conversation context (+ best-effort evidence)
      ├─ provider.chat(system = Markdown | HTML prompt)
      ├─ builder: strip fences, extract title
      └─ HTML → sanitiser: allowlist, CSS filter, inject CSP, build report
  → persist Artifact + a short summary assistant message
  ← 200 {message: {…, artifact}}
  → ArtifactViewer: HTML → iframe sandbox srcDoc (no allow-scripts)
                    Markdown → marked + DOMPurify
```

## 19. Security considerations

| Concern | Control |
| --- | --- |
| Secrets in the repo | `.env` git-ignored; `.env.example` carries no real values; no key in any default |
| Secrets in logs/responses | structlog censoring; `/api/config` reports configured-or-not; test asserts a planted key value never appears in a response |
| SQL injection | SQLAlchemy Core/ORM with bound parameters throughout; no string-concatenated SQL, including the pgvector distance query |
| XSS via generated HTML | Server allowlist sanitiser + sandboxed iframe without `allow-scripts`; never `innerHTML` in the parent document |
| XSS via Markdown | DOMPurify with an explicit allowlist and URI-scheme regex |
| Oversized payloads | Body-size middleware plus per-field limits, rejected before any model call |
| Invalid input | Pydantic validation on every request; enums for closed sets |
| Resource exhaustion | Bounded `top_k`, context character budgets, capped history, provider timeouts, database pool limits |
| Container privilege | Backend runs as a non-root user; test tooling excluded from the runtime image |
| Transport of transcript content | No automatic cloud failover — provider choice is always explicit |
| Clickjacking of the app shell | `X-Frame-Options: DENY` from nginx |

Honest gaps: **no authentication, no rate limiting, no per-user scoping of sessions** —
out of scope for a local evaluation, and required before any shared deployment. HTTP is
plain in local Compose; TLS would terminate at a proxy in a real deployment.

## 20. Trade-offs

**Deterministic routing over autonomous tool selection** *(the central one)*

The demo must run on an 8B local model. There, tool-call JSON is unreliable and each extra
round trip costs 10–20 seconds — an autonomous loop would be slow and occasionally
incoherent, on exactly the path being demonstrated. So the default runtime deterministically
selects one skill per turn and calls the model only inside that skill.

The Claude Agent SDK runtime is fully implemented for autonomous selection, behind the same
protocol and sharing one skill registry. `AgentService` selects it when the provider is
Anthropic — not via `AGENT_RUNTIME`. It is cloud-only: the Ollama demo stays on the
router so the demonstrated path does not require an API key.

Cost: the Ollama path cannot chain skills within a turn (retrieve → essay → artifact in one
message). Given the assignment's explicit preference for explicit routing and clear skill
boundaries, predictability and local reproducibility were the better buy.

**Refuse before generating, over answer-then-hedge**

The threshold check precedes the LLM call when nothing clears `RETRIEVAL_MAX_DISTANCE`,
making that refusal deterministic. On a large nomic index, out-of-corpus questions often
still retrieve weak neighbours; then the model is called with an evidence-only prompt and
must refuse rather than invent outside facts. Cost: a strict threshold sometimes declines
a question a human would consider covered. That failure is visible in
`retrieval_completed` and tunable in one variable — the right trade for a tool whose value
is trustworthiness.

**pgvector over a dedicated vector database**

One database for chunks, embeddings, sessions and messages: one backup, one connection, one
migration path, and citations as plain foreign keys. A dedicated store scales further; at
this corpus size it would add a service and a cross-store consistency problem for no gain.

**Sandboxed iframe as the boundary, sanitising as depth**

Sanitisers get bypassed; `sandbox` without `allow-scripts` is enforced by the browser. Both
are implemented, but the design leans on the one that holds when the other is wrong. Cost:
generated pages genuinely cannot use JavaScript — accepted, since the deliverable is a
static page.

**No streaming**

Streaming would improve perceived latency but complicates citation verification, which needs
the whole response before markers can be validated against retrieved chunks. Instead the UI
shows named stages and elapsed time. Correct citations over perceived speed.

**Local embeddings over a hosted embedding API**

`nomic-embed-text` keeps the RAG index offline and account-free. Cost: hosted embeddings
would likely retrieve slightly better, and switching models requires re-embedding the whole
corpus.

**Hand-written HTML allowlist over an off-the-shelf cleaner**

Required, because standard cleaners escape `<style>` contents and the assignment requires
HTML *with CSS*. Cost: bespoke security code — mitigated by keeping it a strict allowlist,
testing it directly, and never treating it as the primary boundary.
