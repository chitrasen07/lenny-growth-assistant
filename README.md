# The Lenny Growth Assistant

A conversational assistant that answers product-management and growth questions **only**
from an indexed corpus of Lenny's Podcast transcripts, shows the excerpts each claim came
from, and turns a conversation into a publishable Ship 30 for 30 essay or a rendered
HTML/Markdown artifact.

Runs entirely locally on Ollama. No cloud account is required.

---

## Overview

Most "chat with your docs" demos will answer anything you ask, because the model quietly
falls back on its own knowledge when retrieval comes up empty. That makes the citations
decorative: you cannot tell a grounded answer from a fluent guess.

This app is built the other way round. Retrieval decides whether an answer is possible
**before** the model is invoked. If nothing in the transcripts clears the relevance
threshold, the assistant says so and no LLM call is made. If weak neighbours still pass
the distance cap, the model is called with an evidence-only prompt and must refuse rather
than invent outside facts. When it does answer, every claim carries an `[S1]`-style
marker tied to a specific transcript chunk, and you can expand that chunk in the UI to
read the exact text the model was shown.

Three things follow from that design, and they are the things worth reviewing:

- **Grounding is enforced in code, not by prompt wording** — a relevance threshold before
  generation, and citation verification after it (§[RAG Architecture](#rag-architecture)).
- **Generated HTML is treated as hostile** — server-side allowlist sanitising plus a
  sandboxed iframe with scripting disabled (§[Artifact Security](#artifact-security)).
- **The local model is the primary target, not a fallback** — routing is deterministic so
  an 8B model on a laptop behaves predictably (§[Agent layer](#agent-layer)).

## Problem

A product team's useful context is buried in hours of podcast audio. Searching it is
impractical, and a general chatbot will confidently attribute plausible-sounding advice to
people who never said it. What a PM actually needs is: an answer, the receipts, and an
honest "that isn't in here" when it isn't.

## Features

| | |
| --- | --- |
| **Grounded Q&A** | Answers restricted to retrieved transcript evidence, with inline `[S1]` citations |
| **Verifiable sources** | Every citation expands to the exact excerpt, speaker, file and chunk index; links to the episode when the transcript declared a URL |
| **Honest refusal** | The assistant declines when the corpus does not support an answer and does not invent outside facts |
| **Independent sessions** | Separate chats with their own history, persisted in PostgreSQL |
| **Follow-up context** | "What about for B2B SaaS?" resolves against the prior turns, while grounding still comes only from retrieval |
| **Ship 30 for 30 essays** | A dedicated skill targeting ~1,250 words (1,062–1,437), max 3 generations, 4–6 H2s, citation-validated |
| **Artifacts** | Markdown documents and complete standalone HTML/CSS pages generated from the conversation |
| **Artifact Viewer** | Renders artifacts beside the chat; HTML runs in a sandboxed frame that cannot execute script or reach the app |
| **Provider switching** | Header toggle (and `LLM_PROVIDER`) selects Ollama or Anthropic; the selected provider, model, and actual agent runtime are visible |
| **Operable** | Structured JSON logs, a `/health` endpoint that distinguishes API / database / provider / knowledge-base state, and setup problems surfaced in the UI with the command that fixes them |

## Architecture

```
                        ┌──────────────────────────────────┐
   Browser ───────────► │  React + TypeScript (nginx)       │
                        │  chat · sources · artifact viewer │
                        └───────────────┬──────────────────┘
                                        │  /api/*  (same origin, proxied)
                        ┌───────────────▼──────────────────┐
                        │  FastAPI                          │
                        │  validation · errors · logging    │
                        └───┬───────────────────────┬──────┘
                            │                       │
                  ┌─────────▼────────┐    ┌─────────▼─────────┐
                  │  Chat / Session  │    │   Agent Service   │
                  │     Service      │    │  (runtime + skills)│
                  └─────────┬────────┘    └─────────┬─────────┘
                            │                       │
                            │            ┌──────────┴──────────┬─────────────┐
                            │            ▼                     ▼             ▼
                            │      RAG retrieval        Ship 30 skill   Artifact skill
                            │            │                     │             │
                            │            │                     │             ▼
                            │            │                     │      sanitiser (allowlist)
                            │            │                     │
                            ▼            ▼                     ▼
                  ┌──────────────────────────────────────────────────┐
                  │  PostgreSQL 16 + pgvector                         │
                  │  sessions · messages · message_sources           │
                  │  transcripts · transcript_chunks(vector) · artifacts│
                  └──────────────────────────────────────────────────┘

                        LLM Provider interface
                                 │
                   ┌─────────────┴─────────────┐
                   ▼                           ▼
            OllamaProvider              AnthropicProvider
            (local, default)            (cloud, optional)
```

Full detail, including the failure matrix and data flow, is in
[`architecture.md`](architecture.md).

## Requirements

| | Version | Notes |
| --- | --- | --- |
| Docker | 24+ with Compose v2 | The only requirement for the Docker path |
| Ollama | 0.1.30+ | Installed on the **host**, not in Compose — see [Ollama Setup](#ollama-setup) |
| Disk | ~6 GB | `llama3.1:8b` (4.7 GB) + `nomic-embed-text` (274 MB) + images |
| RAM | 8 GB+ | 16 GB is more comfortable for the 8B model |
| Python | 3.12 | Only for running the backend outside Docker |
| Node | 20+ | Only for running the frontend outside Docker |

Verified on Windows 11 with Docker Desktop. Nothing in the stack is OS-specific; the one
platform-dependent detail is documented in [`app/core/runtime.py`](backend/app/core/runtime.py).

## Prerequisites

You need **transcripts** and a **local model**. Neither ships with the repository.

1. **Transcripts.** This repo bundles no podcast content — see
   [Transcript Ingestion](#transcript-ingestion). Until you ingest some, the assistant
   correctly declines every question.
2. **Ollama.** See [Ollama Setup](#ollama-setup).

## Quick Start

```bash
git clone <repo-url>
cd lenny-growth-assistant
cp .env.example .env

# Host prerequisite: Ollama with both models
ollama pull llama3.1:8b
ollama pull nomic-embed-text

docker compose up --build
```

Then, in another terminal, index official Lenny's Podcast transcripts from
[Lenny's Data](https://github.com/LennysNewsletter/lennys-newsletterpodcastdata)
(personal / non-commercial; do not commit the raw files):

```bash
git clone --depth 1 https://github.com/LennysNewsletter/lennys-newsletterpodcastdata.git
python backend/scripts/import_lennys_data.py --src ./lennys-newsletterpodcastdata
docker compose exec backend python -m scripts.ingest
```

To confirm the stack without that corpus, the clearly-labelled synthetic fixture is still
available (**not** real podcast content):

```bash
docker compose exec backend python -m scripts.ingest --dir /data/sample-transcripts
```

Open **http://localhost:3000**. Do not demo citations of the synthetic fixture.

| | |
| --- | --- |
| UI | http://localhost:3000 |
| API docs | http://localhost:8000/docs |
| Health | http://localhost:8000/health |

The header shows the active provider, model and indexed chunk count. If anything is
missing — Ollama down, no transcripts indexed — a banner names the problem and gives the
command that fixes it.

For a real demo, replace the fixture with actual transcripts per
[`docs/transcripts.md`](docs/transcripts.md).

## Environment Variables

`cp .env.example .env` gives you working defaults for a fully local run. Nothing must be
edited to start. [`.env.example`](.env.example) documents every variable inline; the ones
that matter:

**Required** (defaults work as-is)

| Variable | Default | Purpose |
| --- | --- | --- |
| `POSTGRES_USER` / `_PASSWORD` / `_DB` | `lenny` | Database credentials |
| `POSTGRES_HOST_PORT` | `5433` | Host port for Postgres. Not 5432, so this stack coexists with an existing local Postgres |
| `DATABASE_URL` | `…@db:5432/lenny` | Use `db` under Compose, `localhost` outside it |
| `LLM_PROVIDER` | `ollama` | `ollama` or `anthropic` |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | `http://localhost:11434` outside Compose |
| `OLLAMA_MODEL` | `llama3.1:8b` | Chat model |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Embedding model |
| `EMBEDDING_DIMENSIONS` | `768` | **Must** match the embedding model |

**Optional**

| Variable | Default | Purpose |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | *(empty)* | Required when Anthropic is selected. Absent ⇒ reported unconfigured, never a crash |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-5` | Cloud model |
| `AGENT_RUNTIME` | `router` | Loaded for compatibility; **not** the dispatcher. Runtime follows the selected provider |
| `RETRIEVAL_TOP_K` | `6` | Chunks considered per question |
| `RETRIEVAL_MAX_DISTANCE` | `0.55` | Relevance ceiling. **This is the refusal dial** — lower refuses more |
| `ESSAY_TARGET_WORDS` | `1250` | Ship 30 target length |
| `LOG_LEVEL` / `LOG_FORMAT` | `INFO` / `json` | `console` for readable local logs |
| `CORS_ORIGINS` | `localhost:5173,localhost:3000` | Comma-separated |

`.env` is git-ignored. No secret is ever logged or returned by the API — `/api/config`
reports *whether* a key is configured, never its value, and there is a test asserting that.

## Transcript Ingestion

The repository ships **no transcript content**. Podcast transcripts belong to the podcast,
and inventing stand-in "Lenny transcripts" would produce citations that look real and are
not. So the corpus is yours to supply.

Full guide: **[`docs/transcripts.md`](docs/transcripts.md)**. Short version:

1. Drop one file per episode into `data/transcripts/` — `.txt`, `.md`, `.vtt`, `.srt` or `.json`.
2. Declare metadata so citations can link back:

   ```markdown
   ---
   title: How to improve activation
   episode: "142"
   guest: A Guest Name
   source_url: https://www.lennysnewsletter.com/p/some-episode
   ---

   Lenny: Welcome to the show…
   ```

3. Ingest:

   ```bash
   docker compose exec backend python -m scripts.ingest
   ```

`data/transcripts/` is mounted read-only into the container, so **adding a transcript needs
no rebuild**. It is also git-ignored, so your corpus is never committed.

### The ingestion command

```bash
docker compose exec backend python -m scripts.ingest              # index new + changed
docker compose exec backend python -m scripts.ingest --status     # report, change nothing
docker compose exec backend python -m scripts.ingest --force      # re-embed everything
docker compose exec backend python -m scripts.ingest --dir PATH   # a different directory
```

Ingestion is **idempotent**, keyed on a SHA-256 hash of each file's text: re-running with
nothing changed embeds nothing. Editing one file re-indexes only that file. A file that
fails to parse is reported without aborting the run, and the command exits non-zero so a
script notices. Files named `README`, `LICENSE` and similar are skipped so documentation
beside the corpus never becomes a citable "episode".

Deleting a file does **not** unindex it — absence is never treated as a delete instruction,
so a mistyped `--dir` cannot wipe your index. `docs/transcripts.md` §6 covers explicit
removal and re-indexing.

## Ollama Setup

Ollama runs **on the host, deliberately not in Compose**. Containerising it would lose
GPU/Metal access and fall back to CPU inference, and would re-download several GB of models
you likely already have. Containers reach the host daemon through
`host.docker.internal`, which `docker-compose.yml` maps on Linux too via
`extra_hosts: host-gateway`.

```bash
# 1. Install — https://ollama.com/download
#    macOS/Windows: the installer. Linux:
curl -fsSL https://ollama.com/install.sh | sh

# 2. Pull both models: one for chat, one for embeddings
ollama pull llama3.1:8b        # 4.7 GB
ollama pull nomic-embed-text   # 274 MB

# 3. Serve (the desktop app does this automatically)
ollama serve

# 4. Verify
curl http://localhost:11434/api/tags
```

`llama3.1:8b` is chosen as a model that fits a normal developer laptop while still handling
grounded synthesis and a 1,250-word essay. A smaller model works — set
`OLLAMA_MODEL=llama3.2:3b` — at some cost in citation discipline and essay coherence.

**Embeddings are also local.** `nomic-embed-text` (768-dim) means the RAG index needs no
cloud account either. If you change `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS` must match
and the corpus must be re-embedded — query and document vectors are only comparable when
produced by the same model.

If Ollama is unreachable the app does not hide it: `/health` reports the URL it tried and
the error class, the header badge turns red, and a chat attempt returns a structured
`provider_unavailable` error whose remedy text names the command to run.

## Cloud LLM Setup

Anthropic Claude is optional and additive.

```bash
# .env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-…
ANTHROPIC_MODEL=claude-sonnet-4-5
```

```bash
docker compose up -d backend    # picks up the new environment
```

The header updates to "Anthropic (cloud)" with the model name. No application code differs
between providers: both implement the same `LLMProvider` interface
([`providers/base.py`](backend/app/providers/base.py)), and the skills call that interface.

Selecting `anthropic` without a key is a **configuration error**, reported as
`provider_not_configured` with a remedy, not a crash. Leaving the key empty while running
on Ollama is perfectly normal — `/health` reports the cloud provider as unconfigured and
stays `200`. There is no silent fallback to Ollama.

## Agent layer

The runtime is chosen from the **selected provider**, not from `AGENT_RUNTIME`:

```
Anthropic selected
  → ClaudeAgentSDKRuntime
  → Claude Agent SDK (claude-agent-sdk in backend/requirements.txt)
  → MCP skill tools
  → skill calls Anthropic Messages via AnthropicProvider
  → Claude model

Ollama selected
  → RouterRuntime
  → one skill
  → OllamaProvider
  → local model
```

The header shows that runtime (`agent: router` or `agent: claude_agent_sdk`) for the
provider currently selected in the toggle. `/api/config` exposes `active_runtime` for the
default `LLM_PROVIDER` and a `runtime` field on each provider.

The SDK is **in the runtime Docker image** because it is a production dependency. It is
cloud-only and cannot drive Ollama, which is why the demo path is the router. Live
Anthropic generation has not been exercised here (no API key); the SDK contract is tested
against a stub.

The `AGENT_RUNTIME` environment variable is still loaded for compatibility. It does **not**
select the runtime.

## Running Locally

Docker Compose is the supported path. To run the services directly:

```bash
# Database only
docker compose up -d db

# Backend  (Python 3.12)
cd backend
python -m venv .venv && .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# point at the host-published port and localhost Ollama
export DATABASE_URL=postgresql+psycopg://lenny:lenny@localhost:5433/lenny
export OLLAMA_BASE_URL=http://localhost:11434
alembic upgrade head
python run_local.py            # http://localhost:8000

# Frontend  (Node 20+)
cd frontend
npm install
npm run dev                    # http://localhost:5173, proxies /api to :8000
```

Use `python run_local.py` rather than `uvicorn app.main:app` directly: on Windows,
`psycopg`'s async driver cannot run on the default `ProactorEventLoop`, so that script
installs the selector policy first. It is a no-op elsewhere.

## Docker Setup

Three services, plus a test service behind a profile:

| Service | Image | Port | Purpose |
| --- | --- | --- | --- |
| `db` | `pgvector/pgvector:pg16` | `5433→5432` | Postgres with pgvector preinstalled — no build step, no manual extension install |
| `backend` | built from `backend/` | `8000` | FastAPI; applies migrations on start |
| `frontend` | built from `frontend/` | `3000→80` | nginx serving the built SPA and proxying `/api` |
| `tests` | built from `backend/` (`test` stage) | – | Backend suite; `--profile test` only |

Notable choices:

- **No Ollama service** — explained in [Ollama Setup](#ollama-setup).
- **No separate vector store.** pgvector keeps chunks and their embeddings in the same
  database as sessions and messages, so one backup and one connection covers everything,
  and a citation is a plain foreign key rather than a cross-store lookup.
- **Host Postgres port is 5433**, since 5432 is usually taken. Inside the network it is
  always 5432.
- **Migrations run at container start** via `entrypoint.sh`, which retries while the
  database becomes ready, so `docker compose up` is enough on a clean machine.
- **The backend runs as a non-root user.** pytest and ruff live in a separate Docker
  **test** stage so they never ship in the runtime image. `claude-agent-sdk` **does** ship
  in the runtime image (it is in `requirements.txt`) because Anthropic chat uses
  `ClaudeAgentSDKRuntime`.

```bash
docker compose up --build          # start everything
docker compose logs -f backend     # structured logs
docker compose down                # stop
docker compose down -v             # stop and delete the database volume
```

## Tests

**Automated tests: 253 backend, 48 frontend.**

These numbers are the last full run after the pre-submission alignment; re-run the
commands below if you change code, and treat the command output as source of truth.

```bash
# Backend — needs the db service; no Ollama, no API key, no network
docker compose --profile test run --rm tests

# Frontend
cd frontend && npm test
```

Backend tests run against a **real PostgreSQL** (a `lenny_test` database they create and
drop), because pgvector similarity search is the behaviour under test and SQLite cannot
emulate it. When no database is reachable, tests skip with an explanatory message rather
than silently passing.

External models are replaced, not called: `EMBEDDING_PROVIDER=hash` selects a
deterministic offline embedder, and a scriptable `FakeProvider` stands in for the LLM. That
keeps the suite fast and reproducible while still exercising the real retrieval, routing,
persistence and sanitisation code. The fake provider records what it was sent, so tests can
assert **what the model was actually shown** — that retrieved evidence and prior turns
reached the prompt, and that nothing else did.

What is covered, beyond the endpoints returning 200:

| Area | Examples |
| --- | --- |
| Grounding | Answers cite only retrieved chunks; invalid `[Sn]` markers are stripped; refusal when evidence is missing or too weak |
| Retrieval | Ranking order, distance threshold, per-episode diversity cap, follow-up query construction, empty index |
| Sessions | Isolation between sessions, persistence, deterministic message ordering, cascade delete |
| Providers | Routing by config, Ollama unavailable, missing API key, timeout, invalid provider |
| Ship 30 | Word count within 1,062–1,437, max 3 generations, post-cleanup count, H2 cap, grounding |
| Artifacts | Markdown and HTML generation, persistence, validation, sanitiser integration |
| Security | Script/iframe/handler/CSS-vector removal, CSP injection, sandbox attributes, secret values never returned |
| Ingestion | Cleaning, chunking size and overlap, speaker turns, all loader formats, metadata precedence, idempotency, docs exclusion |
| Failures | Structured error envelope, validation errors, 404s, oversized payloads |

Frontend tests focus on the security-critical rendering paths: that HTML artifacts reach
the DOM only as an iframe `srcdoc` with no `allow-scripts`, that markdown sanitising
removes scripts, handlers and `javascript:` URLs, and that citation metadata is never
fabricated in the UI.

A **[manual UI test plan](docs/manual-test-plan.md)** covers what automation cannot:
keyboard navigation, responsive behaviour, and the live Ollama path.

## API

Interactive docs at http://localhost:8000/docs (OpenAPI, generated from the Pydantic
schemas).

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | API, database, provider and knowledge-base status |
| `GET` | `/api/config` | Non-secret runtime config for the UI (active provider, model, runtime, index stats) |
| `POST` | `/api/sessions` | Create a chat session |
| `GET` | `/api/sessions` | List sessions, most recently active first |
| `GET` | `/api/sessions/{id}` | One session's metadata |
| `DELETE` | `/api/sessions/{id}` | Delete a session and its messages |
| `GET` | `/api/sessions/{id}/messages` | Full history with sources and artifacts |
| `POST` | `/api/chat` | Send a turn; returns the assistant message, sources and any artifact |
| `POST` | `/api/artifacts` | Explicitly generate a Markdown or HTML artifact |
| `GET` | `/api/artifacts/session/{id}/latest` | Most recent artifact, to restore the viewer on reload |

Every failure uses one envelope, with a stable machine-readable code and a human remedy:

```json
{
  "error": {
    "code": "provider_unavailable",
    "message": "Ollama is not reachable at http://host.docker.internal:11434.",
    "remedy": "Start Ollama with `ollama serve`, then retry."
  }
}
```

That `remedy` is what lets the UI say "run `ollama serve`" instead of "something went
wrong". Codes include `validation_failed`, `not_found`, `database_unavailable`,
`provider_unavailable`, `provider_not_configured`, `provider_timeout`, `embedding_failed`,
`knowledge_base_empty`, `artifact_generation_failed` and `payload_too_large`.

## RAG Architecture

```
transcript file
   │  load, read declared metadata (never infer it)
   │  clean: strip subtitle cues, normalise whitespace, keep speaker labels
   │  split into speaker turns, keeping character offsets into the source
   │  pack into ~1200-char chunks with ~150-char overlap, preferring turn boundaries
   │  embed each chunk  (nomic-embed-text, 768-dim)
   ▼
transcript_chunks(content, embedding vector(768), speaker, char offsets, transcript_id)
   │
   ▼  question  →  embed  →  cosine KNN (pgvector HNSW)
   │              ├─ drop chunks beyond RETRIEVAL_MAX_DISTANCE
   │              ├─ cap chunks per episode (diversity)
   │              └─ cap total context characters
   ▼
   nothing left?  ──yes──►  refuse, no LLM call
   │ no
   ▼
   numbered EVIDENCE block  →  LLM  →  verify [Sn] markers against real chunk ids
   ▼
   answer + sources (cited flagged separately from merely retrieved)
```

**Chunking on speaker turns** rather than a blind character window keeps a guest's point
attached to its speaker; overlap means a claim spanning a boundary survives intact in at
least one chunk.

**Grounding is enforced at three layers**, because prompt instructions alone are not a
control:

1. **Before generation** — if no chunk clears `RETRIEVAL_MAX_DISTANCE`, the canonical
   refusal is returned and the model is never called.
2. **During generation** — if weak chunks still pass the distance cap, the model is called
   with an evidence-only prompt and must refuse rather than invent outside facts. On a
   large nomic index this is the usual out-of-corpus path.
3. **After generation** — `[Sn]` markers are parsed and matched against the chunks actually
   retrieved. Markers pointing at nothing are stripped, and sources the answer really used
   are flagged `cited` separately from those merely retrieved. The UI shows both, so you
   can see everything the model was given, not just what it quoted.

**Follow-ups** are handled by composing the retrieval query from the current question plus
bounded prior context, so "what about for B2B SaaS?" retrieves sensibly. History is capped
by both message count and characters. Prior turns inform *interpretation* only — they are
never treated as evidence.

## Model Switching

```
                  Skills call one interface
                            │
                  ┌─────────▼─────────┐
                  │    LLMProvider    │   chat() · chat_with_tools() · embed() · health()
                  └─────────┬─────────┘
              ┌─────────────┴─────────────┐
              ▼                           ▼
      OllamaProvider              AnthropicProvider
      HTTP → local daemon         Anthropic SDK
```

Switching is the header toggle (per-request `provider`) or `LLM_PROVIDER=ollama|anthropic`.
No application code changes. Anthropic selection uses `ClaudeAgentSDKRuntime`; Ollama uses
`RouterRuntime`. Providers are cached per process and closed on shutdown.

Failures are translated into the shared error taxonomy so the UI reacts identically
whichever provider is active:

| Situation | Code | Behaviour |
| --- | --- | --- |
| Ollama daemon down | `provider_unavailable` | Message names the URL tried; remedy names the command |
| Model not pulled | `provider_unavailable` | Remedy names `ollama pull <model>` |
| `LLM_PROVIDER=anthropic`, no key | `provider_not_configured` | Reported at request time and in `/health` |
| Generation exceeds timeout | `provider_timeout` | Remedy suggests a smaller model or a longer timeout |
| Provider returns an error | `provider_error` | SDK detail is logged; the response never carries a key |

**There is deliberately no automatic failover to the cloud.** Silently answering from
Anthropic when Ollama fails would make the model behind an answer unknowable, and could
send transcript content to a third party the operator did not choose for that request.
Provider selection stays explicit; a failure is surfaced, not papered over.

## Artifact Security

Generated HTML is treated as **untrusted input**, because that is what model output is.
Three layers, in increasing order of how much they are relied on:

**1. The prompt** forbids `<script>`, inline handlers, `javascript:` URLs and external
resources. Useful for output quality; **not** a security control, and not counted as one.

**2. Server-side allowlist sanitiser**
([`artifacts/sanitizer.py`](backend/app/artifacts/sanitizer.py)) — the layer that actually
removes things:

- **Allowed:** document structure, headings, text semantics, lists, tables, links,
  images, `<style>`, and a small set of attributes per tag.
- **Dropped with their entire subtree:** `script`, `iframe`, `object`, `embed`, `applet`,
  `form`, `input`, `select`, `textarea`, `link`, `base`, `svg`, `math`, `template`,
  `noscript`, `frame`, `frameset` — their *content* is itself the payload, so unwrapping
  them would not be safe.
- **Stripped:** every `on*` handler; `javascript:`, `vbscript:`, `file:`, `about:`,
  `blob:` and non-image `data:` URLs; CSS `@import`, `expression()`,
  `url(javascript:…)`, `-moz-binding` and `behavior` — as whole declarations, so no
  attacker-supplied URL survives as leftover text.
- **Injected:** a restrictive CSP `<meta>` — `default-src 'none'; script-src 'none'; …`.
- A **report** of what was removed is stored and shown in the viewer, so sanitising is
  visible rather than silent.

Why a hand-written allowlist instead of `bleach`: the assignment requires generating full
HTML **with CSS**, and general-purpose cleaners escape `<style>` contents, which breaks
every generated page. So `<style>` text is preserved and filtered for CSS-borne script
vectors instead.

**3. Sandboxed iframe** ([`ArtifactViewer.tsx`](frontend/src/components/ArtifactViewer.tsx))
— the primary containment boundary:

```tsx
<iframe sandbox="allow-same-origin" srcDoc={artifact.content} />
```

`sandbox` **without `allow-scripts`** means the browser refuses to execute any script in
that document — inline, handler or injected — so a sanitiser miss still cannot run.
`srcDoc` keeps the markup out of the parent document: it is never assigned to `innerHTML`
anywhere in the app, so it cannot touch the DOM, storage or cookies. `allow-same-origin` is
present only so the frame can apply its own inline `<style>`; with `allow-scripts` absent it
grants no script access to anything. `allow-forms`, `allow-popups` and
`allow-top-navigation` are all withheld.

Markdown artifacts and chat messages take a different path — parsed with `marked`, then
sanitised with **DOMPurify** under an explicit tag/attribute allowlist and a URI scheme
regex that permits only `http(s)`, `mailto:` and fragments.

**Limitations, stated honestly.** The server sanitiser is a syntactic filter, not a browser,
and does not attempt to defeat every mutation-XSS trick — which is exactly why the
script-disabled iframe, not the sanitiser, is the boundary the design leans on. The frame
can still make layout-based requests (e.g. a CSS background URL) unless the CSP blocks
them; the injected CSP restricts this, but a `<meta>` CSP is weaker than a real header,
which a production deployment should add. There is no authentication, so anyone who can
reach the app can generate artifacts — acceptable for a local evaluation, not for a
deployment.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Header badge red, "Ollama not reachable" | Daemon not running, or not reachable from the container | `ollama serve`; confirm `OLLAMA_BASE_URL=http://host.docker.internal:11434` under Compose |
| `llama runner process has terminated` / CUDA error | GPU runner stuck after a failed load (common on 6 GB laptops) | Quit and relaunch the host Ollama app, then retry. The backend unloads `nomic-embed-text` after each embed so `llama3.1:8b` can claim VRAM. |
| Every question is declined | Nothing indexed — check `/health` → `knowledge_base.ready` | `docker compose exec backend python -m scripts.ingest` |
| Relevant questions still declined | Threshold too strict for your corpus | Raise `RETRIEVAL_MAX_DISTANCE` toward `0.65`, restart backend |
| `embedding_failed` during ingestion | Embedding model not pulled | `ollama pull nomic-embed-text` |
| Backend exits: port 5432 in use | Another local Postgres | Change `POSTGRES_HOST_PORT` in `.env` (container port is unaffected) |
| `exec /entrypoint.sh: no such file or directory` | Shell script checked out with CRLF | Handled by `.gitattributes` and a `sed` in the Dockerfile; rebuild with `docker compose build --no-cache backend` |
| Chat times out on the first message | Model loading into memory on first inference | Wait, or `ollama run llama3.1:8b` once to warm it |
| Essay is short | Small model ignoring the length target | Use `llama3.1:8b` or larger; the skill allows up to 3 generations and continues after citation cleanup if the cleaned draft is still short |
| `psycopg` / `ProactorEventLoop` error on Windows | Running uvicorn directly | Use `python run_local.py` |
| Tests skip with a database message | `db` service not running | `docker compose up -d db` |

Logs are structured JSON — `docker compose logs backend | grep chat_completed` — and every
line for one request carries the same `request_id`. Set `LOG_FORMAT=console` for readable
local output.

## Project Structure

```
backend/
  app/
    api/          routes, middleware (request id, body size), error handlers, deps
    agent/        runtimes (router, claude_sdk), skills, routing, prompts, citations
    artifacts/    builder (fence stripping, title extraction) + sanitizer (allowlist)
    core/         config, structured logging, error taxonomy, event-loop policy
    db/           engine, session factory, health check
    models/       SQLAlchemy ORM: sessions, messages, transcripts, chunks, artifacts
    providers/    LLMProvider interface, Ollama, Anthropic, factory
    rag/          loader, chunking, embeddings, ingestion, retrieval
    schemas/      Pydantic request/response contracts
    services/     session and chat orchestration
  alembic/        migrations
  scripts/        ingest.py CLI
    tests/          backend pytest suite
frontend/
  src/
    components/   AppHeader, SessionSidebar, ChatPanel, Composer, MessageBubble,
                  SourceList, ArtifactViewer, ErrorBanner, StatusBanner
    hooks/        useConfig, useSessions, useChat
    services/     typed API client, markdown rendering + sanitising
    styles/       tokens, layout, chat, artifact
    test/         frontend vitest suite
data/
  transcripts/        your corpus (git-ignored, empty by default)
  sample-transcripts/ one clearly-labelled synthetic fixture
docs/               implementation plan, transcripts guide, test plan, demo script, audit
agent-transcripts/  development decision log
```

## Design Decisions

Decisions where a different choice was reasonable, and why this one:

**Refuse before generating, not after.** The relevance threshold runs before the LLM call,
so "not enough information" is a property of the system rather than a behaviour the model
might exhibit. Cost: a strict threshold occasionally declines a question a human would
consider covered. That failure is visible and tunable in one variable, which is the right
trade for a tool whose value depends on trusting its answers.

**Deterministic routing as the default agent runtime.** The demo must run on an 8B local
model, where tool-call JSON is unreliable and each extra round trip costs 10–20s. So one
turn deterministically selects one skill, and the model is called *inside* the skill, never
to decide control flow. Selecting Anthropic in the header uses `ClaudeAgentSDKRuntime`
instead: the Claude Agent SDK registers the same skills as MCP tools and the model chooses
among them. That path is cloud-only, so the Ollama demo stays on the router. This is the
project's central trade-off: predictability and local reproducibility over agent autonomy.

**pgvector rather than a separate vector store.** Chunks, embeddings, sessions and messages
in one database means one backup, one connection, one migration path, and citations that
are plain foreign keys. A dedicated vector database would scale further; at this corpus
size it would add a service and a consistency problem for no gain.

**A sandboxed iframe as the security boundary, with sanitising as depth.** Sanitisers can
be bypassed; `sandbox` without `allow-scripts` is enforced by the browser. Both are
implemented, but the design leans on the one that holds even when the other is wrong.

**Local embeddings.** `nomic-embed-text` via Ollama means the RAG index needs no cloud
account, so the whole app runs offline after model pull.

**No streaming.** Token streaming would improve perceived latency but complicates citation
verification, which needs the complete response before markers can be validated. Instead
the UI shows named stages (retrieving → generating) and elapsed time. Correctness of
citations over perceived speed.

**A `seq` column for message ordering.** Postgres `now()` is transaction-scoped, so two
messages written in one transaction share a timestamp and their order becomes
non-deterministic. A sequence-backed column makes ordering stable — found by a flaky test,
which is the note worth keeping.

## Known Limitations

Stated plainly rather than buried:

- **No transcript corpus ships with the repo.** Deliberate (§[Transcript Ingestion](#transcript-ingestion)), but it means a fresh clone declines everything until you ingest.
- **The Anthropic path is verified only by mocked tests.** No API key was used for a live Claude generation; provider selection, missing-key errors and the SDK runtime contract are tested against stubs, not the live API.
- **Retrieval is dense-only.** No BM25/hybrid search and no reranker, so an exact-phrase or acronym query can underperform. Simple and explainable was preferred at this corpus size.
- **Relevance is one global threshold.** A single `RETRIEVAL_MAX_DISTANCE` cannot be right for every question shape; a per-query calibration would be better. On a ~5k-chunk nomic index, out-of-corpus questions often still retrieve weak neighbours, so the model may be called and then refuse from evidence rather than being skipped.
- **Essay length is approximate.** Target 1,250 words (accepted 1,062–1,437), maximum 3 generations, word count taken after citation cleanup from the cleaned draft. A small local model can still land outside tolerance after three calls; metadata reports the actual cleaned count, not the target.
- **`<meta>` CSP is weaker than an HTTP header**, and the sanitiser is syntactic, not a browser (§[Artifact Security](#artifact-security)).
- **No authentication and no rate limiting.** Out of scope per the assignment; fine locally, not deployable as-is.
- **Sessions are anonymous and unscoped** — anyone reaching the API sees all sessions. Acceptable for a single-user local tool only.
- **No token-level cost/latency accounting** beyond per-stage timings in message metadata.

## Demo Flow

Full script with timings: **[`docs/demo-script.md`](docs/demo-script.md)**. Shape:

1. The problem — buried podcast knowledge, and citations you cannot trust.
2. Header: provider `Ollama (local)`, model, indexed chunk count.
3. New chat → a grounded question → answer with inline `[S1]` markers.
4. Expand a source → the exact excerpt, speaker and file the claim came from.
5. Follow-up ("what about for B2B SaaS?") → context resolves, grounding still from retrieval.
6. A question the corpus does not cover → honest refusal, no fabrication.
7. "Write a Ship 30 for 30 essay about activation" → ~1,250 grounded words (1,062–1,437; live-checked on Ollama: 3 generations, 1,413 cleaned words, 6 H2s). Pre-generate before recording — it takes ~2–3 minutes.
8. "Create a landing page for this" → HTML renders in the Artifact Viewer.
9. Show the sandbox attribute and the sanitiser report — why generated HTML cannot execute.
10. The trade-off: Ollama uses deterministic routing; selecting Anthropic uses the Claude Agent SDK.

## Future Improvements

Ordered by value per unit of work:

1. **Hybrid retrieval** — add BM25 alongside dense search and fuse; the biggest quality win for exact-phrase and acronym queries.
2. **A retrieval evaluation set** — a fixed question/expected-source list scored in CI, so `RETRIEVAL_MAX_DISTANCE` and chunking changes are measured rather than guessed. This is what would turn the target metrics in [`PRD.md`](PRD.md) into real ones.
3. **A reranker** over the top ~20 candidates, which usually beats threshold tuning.
4. **Streaming with post-hoc citation verification** — stream tokens, then reconcile markers and mark unverifiable ones, keeping today's guarantee while improving perceived latency.
5. **Timestamp-linked citations** — `.vtt`/`.srt` carry timings; retaining them would let a citation deep-link to the moment in the audio.
6. **Artifact history and export** — versions per session, download as `.md`/`.html`.
7. **A real CSP header** for artifacts served from a separate origin, upgrading the boundary from `<meta>`.
8. **Auth and rate limiting**, required before any shared deployment.
