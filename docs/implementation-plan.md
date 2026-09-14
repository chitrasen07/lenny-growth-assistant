# Implementation Plan — The Lenny Growth Assistant

> Written before implementation, after inspecting the repository and verifying dependency
> facts. Kept up to date as decisions changed during the build. Assumptions are labelled
> **[Assumption]** and trade-offs **[Trade-off]**.

**Status: delivered.** All 16 phases are complete. Re-run pytest and `npm test` for current
counts. Ruff and TypeScript are clean, and the stack starts from
`docker compose up --build`. Live Ollama generation **has** been exercised against the
official corpus. The live Anthropic API has not (no key). Latest Ship 30 live quality after
the H2 cap is unverified.
>
> Where the build diverged from this plan, the divergence and its reason are recorded in
> [`../agent-transcripts/decision-log.md`](../agent-transcripts/decision-log.md). The two
> substantive changes were a per-call retrieval override (the per-episode diversity cap was
> starving Ship 30 essays of evidence) and skipping documentation files during ingestion
> (`README.md` beside the corpus was being indexed as a citable episode).

## 0. Repository inspection (starting state)

| Item | Finding |
| --- | --- |
| Tracked files | `.gitattributes` only; single commit `88293da Initial commit` |
| Backend / frontend / Docker / DB | None present — greenfield |
| Transcript data | **None present in the repo** |
| Assignment document | **Not present in the workspace** — the task brief in the chat prompt is the source of truth |
| Python (host) | 3.14.4 |
| Node / npm (host) | v22.19.0 / 10.9.3 |
| Docker / Compose | 29.5.3 / v5.1.4 |
| Ollama | CLI 0.20.2 installed, daemon not running at inspection time |

Verified dependency facts before committing to the design:

- `claude-agent-sdk` 0.2.152 exists on PyPI, **bundles the Claude Code CLI binary**, and supports
  in-process custom tools via `@tool` + `create_sdk_mcp_server`. It requires Anthropic credentials,
  so it *cannot* execute against a local Ollama model.
- `anthropic` 1.5.0 provides the Messages API with native tool use.
- Ollama exposes native tool calling on `POST /api/chat` (`tools` array) and embeddings on
  `POST /api/embed`; `nomic-embed-text` returns 768 dimensions.
- `pgvector` 0.5.0 provides the SQLAlchemy `Vector` column type.

Consequence: the assignment requires the Claude Agent SDK **and** requires the demo to run on
local Ollama. These are mutually exclusive in a single runtime, so the agent layer is designed
with one skill registry and two interchangeable runtimes (see §G).

---

## A. Requirements checklist

Traceability lives in `docs/final-evaluator-audit.md` (requirement → file → verification).
This is the extracted list the build works against.

### Backend / platform
1. FastAPI backend with Pydantic request validation and typed responses.
2. PostgreSQL persistence; reproducible schema via Alembic migrations.
3. Independent chat sessions; no context leakage between sessions.
4. Message persistence with `session_id`, `role`, `content`, timestamp, metadata.
5. REST endpoints: `/health`, session CRUD-lite, messages, chat, artifacts.
6. Structured error responses with stable error codes.
7. Structured JSON logging with request correlation IDs.
8. Resilience for DB, Ollama, cloud provider, timeout, empty-retrieval, oversized-input failures.

### AI / knowledge
9. Lenny's Podcast transcript knowledge base with a real ingestion pipeline.
10. Clean → chunk → embed → index → retrieve, preserving source metadata.
11. Grounded RAG answers with citations traceable to stored chunks.
12. Honest "not enough information" behaviour when retrieval is weak.
13. Conversational follow-up context, bounded in size.
14. Explicit agent layer with discrete skills/tools.
15. Dedicated Ship 30 for 30 essay skill (~1,250 words, grounded).
16. Markdown artifact generation.
17. HTML/CSS artifact generation.
18. Local Ollama provider (mandatory for the demo).
19. At least one cloud provider (Anthropic Claude).
20. Configuration-driven provider switching; selected provider visible in the UI.

### Frontend
21. Header, new chat, session history, conversation, composer.
22. Loading states, error states, empty states.
23. Source/citation display.
24. In-app Artifact Viewer rendering Markdown and HTML/CSS.
25. Sandboxed/sanitised HTML rendering — never `innerHTML` into the app DOM.
26. Provider/model indicator.
27. Responsive, keyboard-accessible, semantic markup.

### Delivery
28. Docker Compose one-command startup; `.env.example`; no committed secrets.
29. README, PRD, `design.md`, `architecture.md`, this plan, agent transcripts.
30. Automated backend tests + frontend tests + manual UI test plan.
31. Demo script for a 2–3 minute video.

---

## B. Architecture plan

```
┌──────────────────────────────────────────────────────────────────────┐
│ React + TypeScript + Vite (nginx in Docker)                          │
│  SessionSidebar │ ChatPanel │ ArtifactViewer │ ProviderBadge         │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ JSON over HTTP (/api/*)
┌───────────────────────────────▼──────────────────────────────────────┐
│ FastAPI                                                              │
│  middleware: request-id → structured logging → error envelope         │
│  routers: health │ sessions │ chat │ artifacts │ knowledge            │
├──────────────────────────────────────────────────────────────────────┤
│ Services                                                             │
│  SessionService ── ChatService ── AgentService                        │
│                                      │                               │
│                        AgentRuntime (interface)                      │
│                         ├── RouterRuntime         (Ollama)            │
│                         └── ClaudeAgentSDKRuntime (Anthropic / SDK)   │
│                                      │                               │
│                        SkillRegistry (shared by both runtimes)        │
│           ┌──────────────┬──────────────────┬────────────────────┐    │
│           ▼              ▼                  ▼                    ▼    │
│   search_transcripts  answer_grounded  generate_ship30   generate_    │
│                        _question        _essay            artifact    │
│           │                                                          │
│           ▼                                                          │
│  RetrievalService → Embedder → pgvector similarity search            │
├──────────────────────────────────────────────────────────────────────┤
│ LLMProvider (interface): OllamaProvider │ AnthropicProvider           │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
                 ┌──────────────▼───────────────┐      ┌──────────────┐
                 │ PostgreSQL 16 + pgvector     │      │ Ollama       │
                 │ sessions, messages,          │      │ (host)       │
                 │ transcripts, chunks,         │      │ chat + embed │
                 │ artifacts                    │      └──────────────┘
                 └──────────────────────────────┘
```

---

## C. Technology choices

| Layer | Choice | Why |
| --- | --- | --- |
| Backend | FastAPI + Pydantic v2 | Required; first-class validation and OpenAPI |
| ORM | SQLAlchemy 2.0 (async, `postgresql+psycopg`) | Typed 2.0 style; psycopg3 serves both async app and sync Alembic with one driver |
| Migrations | Alembic | Reproducible schema, no "create_all" drift |
| Vector store | **PostgreSQL + pgvector** | Required DB already present — one datastore instead of adding ChromaDB |
| Embeddings | Ollama `nomic-embed-text` (768d) | Ollama is already mandatory; avoids pulling ~2 GB of torch for sentence-transformers |
| Cloud LLM | Anthropic Claude (`anthropic` SDK) | Assignment names Anthropic explicitly |
| Agent | Own skill registry + two runtimes (tool loop, `claude-agent-sdk`) | Satisfies the SDK requirement *and* the local-Ollama demo requirement |
| HTML safety | Server allowlist sanitiser (BeautifulSoup) + sandboxed iframe + CSP | Defence in depth; keeps `<style>` working, which the HTML/CSS requirement needs |
| Frontend | React 19 + TS + Vite, hand-written CSS | Small surface; no Tailwind toolchain needed for ~10 components |
| Markdown | `marked` + `DOMPurify` | Reputable sanitiser for the markdown path |
| Tests | pytest + pytest-asyncio; Vitest | Standard |
| Logging | structlog (JSON) | Structured events without a heavy framework |

Rejected: ChromaDB (second datastore), Redis (nothing needs it), Kubernetes, auth, streaming
token transport (see §L).

---

## D. Data flow (chat request)

```
POST /api/chat {session_id, message, provider?}
  1. validate (Pydantic; length ceiling)
  2. load session + last N turns  ── scoped strictly by session_id
  3. persist user message
  4. AgentService.handle()
       a. route intent: question | ship30 | artifact
       b. build retrieval query (current question + recent user turns)
       c. embed query → pgvector cosine search → top-k, threshold, per-episode cap
       d. if no chunk within threshold → deterministic honest refusal (no LLM call)
       e. else run skill with evidence block [S1..Sn]
       f. parse which [Sn] markers the answer actually cited
  5. persist assistant message + sources + artifact metadata
  6. respond {message, sources[], artifact?, provider, model, timings}
```

## E. Database design

```
sessions            id uuid pk, title text, created_at, updated_at, message_count(view/derived)
messages            id uuid pk, session_id fk→sessions cascade, role enum(user|assistant|system),
                    content text, created_at, metadata jsonb  (provider, model, latency, intent,
                    retrieved_chunk_ids, refusal flag)
message_sources     id pk, message_id fk→messages cascade, chunk_id fk→transcript_chunks,
                    rank int, distance float, cited bool     ← citation traceability
transcripts         id uuid pk, source_file text unique, content_hash text, title, episode,
                    guest, source_url, ingested_at, chunk_count
transcript_chunks   id uuid pk, transcript_id fk cascade, chunk_index int, content text,
                    speaker text null, char_start int, char_end int, token_estimate int,
                    embedding vector(768), created_at
artifacts           id uuid pk, session_id fk, message_id fk, type enum(markdown|html),
                    title, content text, sanitised bool, sanitiser_report jsonb, created_at
```

Indexes: `messages(session_id, created_at)`, `transcript_chunks(transcript_id, chunk_index)`,
ivfflat/HNSW cosine index on `transcript_chunks.embedding`.

No user accounts or personal data — sessions are anonymous and server-generated.
**[Assumption]** Single-user local evaluation tool, so no auth (§42 forbids adding it).

## F. RAG design

- **Loading**: `.txt`, `.md`, `.vtt`, `.srt`, `.json` from `data/transcripts/`. Front-matter or a
  sidecar `metadata.json` supplies title/episode/guest/URL. Metadata is **never invented** — absent
  fields stay null and the UI shows only what exists.
- **Cleaning**: strip VTT/SRT cues and timestamps, collapse whitespace, normalise speaker labels.
- **Chunking**: speaker-turn aware sliding window, ~1,200 characters with ~200 overlap, so a chunk
  is big enough to carry an argument but small enough to keep prompts lean.
- **Embedding**: batched Ollama `/api/embed`; dimension asserted against configuration to prevent
  silent mismatch after a model change.
- **Idempotency**: SHA-256 of normalised file content stored on `transcripts`. Unchanged file →
  skipped; changed file → chunks replaced transactionally. Re-running ingestion is safe.
- **Retrieval**: cosine distance, `top_k=6`, `max_distance` threshold, at most 2 chunks per
  episode for diversity, total evidence capped by character budget.

## G. Agent design

One `SkillRegistry`, four skills, two runtimes:

| Skill | Why it exists |
| --- | --- |
| `search_transcripts` | Only path to knowledge; keeps retrieval auditable and reusable |
| `answer_grounded_question` | Grounded Q&A with citation discipline and honest refusal |
| `generate_ship30_essay` | Long-form writing has different prompt, evidence budget and validation than Q&A — deserves its own service, not a branch in the chat handler |
| `generate_artifact` | Structured Markdown/HTML output with its own validation + sanitisation |

Routing is an explicit deterministic classifier (keyword/pattern rules) with the LLM used only
inside skills. Rationale: an evaluator can read the routing table in one screen, and routing
cannot fail because a 7B local model produced malformed JSON. **[Trade-off]** less "agentic"
flexibility, far higher reliability on a small local model.

- `RouterRuntime` — deterministic intent router for **Ollama**. One turn selects one skill.
- `ClaudeAgentSDKRuntime` — real `claude-agent-sdk` integration, same skills as in-process
  MCP tools. Selected when the provider is **Anthropic** (header toggle or `LLM_PROVIDER`),
  not via `AGENT_RUNTIME`. Requires `ANTHROPIC_API_KEY`.

## H. Model provider strategy

`LLMProvider` interface: `complete()`, `chat_with_tools()`, `embed()`, `health()`.
`LLM_PROVIDER=ollama|anthropic` selects the default; a request may override per call so the UI
toggle works without a restart. Failure handling: missing key → typed configuration error;
Ollama down → typed unavailable error naming the URL and the `ollama serve` fix; timeout → typed
timeout error. **No silent fallback to the other provider** — a silent swap would hide the fact
that the demo stopped being local. Documented in README.

## I. Artifact security strategy

1. Model output is treated as untrusted.
2. Server-side allowlist sanitiser: drops `script`/`iframe`/`object`/`embed`/`form`/`link`,
   all `on*` handlers, and `javascript:`/`data:` URLs; keeps structural tags and `<style>` CSS.
3. A restrictive `<meta>` CSP is injected into the sanitised document.
4. Frontend renders HTML **only** inside `<iframe sandbox srcdoc>` **without** `allow-scripts`,
   so unsanitised script would still not execute (defence in depth).
5. Markdown path: `marked` → `DOMPurify` before display.
6. Sanitiser removals are recorded and surfaced in the viewer.

## J. Testing strategy

pytest with a real PostgreSQL when available and an automatic skip/`sqlite`-free guard otherwise;
external LLM/embedding calls replaced by a deterministic fake provider so routing and business
logic are tested without network. Coverage targets the 13 areas the brief lists (health, session
creation, session isolation, persistence, validation, retrieval, source metadata, provider
routing, Ollama failure, cloud config failure, empty retrieval, artifact generation, artifact
security). Vitest covers artifact rendering and sanitisation on the frontend. Tests assert
behaviour and payload shape, not just status codes.

## K. Deployment strategy

`docker compose up` starts `db` (pgvector/pgvector:pg16), `backend` (migrations run on start),
`frontend` (nginx). **Ollama runs on the host, not in Compose** — it needs GPU/Metal access, the
evaluator likely already has models pulled, and a containerised copy would re-download several GB.
Containers reach it via `host.docker.internal`.

## L. Risks / trade-offs

| Risk / decision | Mitigation / rationale |
| --- | --- |
| **No transcript data in the repo** | Real ingestion pipeline + documented drop-in location ([`transcripts.md`](transcripts.md)) + a UI banner carrying the ingest command. Transcripts are **not fabricated**. Two synthetic sources exist, both clearly labelled: short passages written inline for the test suite, and one fixture in `data/sample-transcripts/` — kept out of `data/transcripts/` so it is never ingested by accident — that lets an evaluator verify the stack before sourcing a real corpus. |
| Claude Agent SDK cannot run on Ollama | Two runtimes, one skill registry (§G) |
| Small local models drift from citation format | Deterministic routing, strict evidence block, citation parsing, threshold refusal before any LLM call |
| No token streaming | Local generation can take 30–60 s, so the UI shows staged progress ("retrieving → generating") instead. **[Trade-off]** simpler correct request/response over SSE plumbing through a tool loop |
| pgvector recall vs. hybrid search | Corpus is small; exact cosine search is accurate and explainable |
| Python 3.14 on host | Docker pins 3.12 for wheel availability; documented |

## M. Definition of done

- `docker compose up` from a clean clone serves a working UI.
- Ingestion command indexes transcripts idempotently and logs progress.
- Grounded answer returns citations resolvable to stored chunks.
- Weak retrieval produces the honest refusal instead of a model-knowledge answer.
- Follow-up question uses prior turns of that session only.
- Ship 30 essay lands within ~15% of 1,250 words and is grounded.
- Markdown and HTML artifacts render in the Artifact Viewer; HTML is sanitised and sandboxed.
- Provider switching works and the active provider is visible.
- Backend + frontend test suites pass; results reported honestly.
- All documents in §29 exist and match the implementation.

### Outcome against the above

| Item | Result |
| --- | --- |
| `docker compose up` serves a working UI | ✅ verified live from a clean database volume |
| Ingestion idempotent, logs progress | ✅ verified live — re-run embedded 0 chunks |
| Citations resolvable to stored chunks | ✅ enforced structurally (markers verified against chunk ids); test-covered |
| Weak retrieval → honest refusal, not model knowledge | ✅ two paths: pre-LLM when `selected=0`; evidence-only model refusal when weak chunks still retrieve |
| Follow-up uses that session's turns only | ✅ test-covered, including a cross-session negative case |
| Essay within ~15% of 1,250 words, grounded | ✅ test-covered · latest live essay after H2 cap unverified |
| Artifacts render; HTML sanitised and sandboxed | ✅ test-covered in both layers |
| Provider switching works, provider visible | ✅ header toggle; Anthropic → SDK runtime · live cloud generation unverified |
| Test suites pass, reported honestly | ✅ re-run pytest + `npm test`; ruff and `tsc` clean |
| Documents exist and match the implementation | ✅ cross-checked in the audit; three inaccuracies found and fixed |
