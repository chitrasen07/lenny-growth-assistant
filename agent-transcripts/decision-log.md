# Development decision log

The substantive record of the build: decisions with the alternatives considered, failed
attempts, real bugs found while testing, and corrections. Written from the actual session —
nothing here is reconstructed or invented.

Raw conversation log: see [`README.md`](README.md) and
[`capturing-transcripts.md`](capturing-transcripts.md).

---

## Phase 1 — Inspection and planning

The repository was effectively bare: a git repo with no code, no assignment document, and no
transcript data. Two consequences shaped everything after:

**No assignment document in the workspace.** The build prompt was the only specification, so
its "Required assignment areas" list became the requirements checklist verbatim rather than
being inferred from a document.

**No transcript data.** This forced an early decision, recorded in
`docs/implementation-plan.md`: **do not fabricate Lenny transcripts.** Inventing plausible
podcast content would have made every citation in the demo a lie, which is precisely what
the product exists to prevent. Instead: build a robust ingestion pipeline, document exactly
where the evaluator puts files, and design the UI so an empty knowledge base is a legible
state rather than a broken one.

Before writing code, three dependency questions were researched because getting them wrong
would have meant a rewrite:

- Does the **Claude Agent SDK** work with a non-Anthropic model? → No. It is cloud-only.
  This is what forced the two-runtime design below.
- Does **Ollama** support tool calling and embeddings in one daemon? → Yes: `/api/chat` with
  `tools`, and `/api/embed`. So one local dependency covers both roles.
- Is **pgvector** viable without a training pass on an index that starts empty? → Yes with
  HNSW; IVFFlat needs training data, which is wrong for an index that grows one transcript
  at a time.

### The central architectural tension

The assignment requires the Claude Agent SDK (or Pi) **and** requires the demo to work on
local Ollama. The SDK cannot drive a local model. Three options:

| Option | Rejected because |
| --- | --- |
| Claude SDK only | The demo would need an API key, contradicting the Ollama requirement |
| Custom router only | Would not satisfy the explicit SDK requirement |
| **Two runtimes behind one interface, sharing one skill registry** | **Chosen** |

Both runtimes implement one `AgentRuntime` protocol and invoke the *same* four skills, so
this is not two parallel implementations — a skill is defined once. `router` is the default
because it is provider-agnostic and therefore is the demo path; `claude_agent_sdk` is one
environment variable away. This is the project's headline trade-off, documented in
`architecture.md` §20.

---

## Bugs found while testing

The distinction that matters: two of these were **product bugs** that would have degraded
the evaluator's experience, not test scaffolding problems.

### Ship 30 essays refused whenever the corpus had few episodes *(real product bug)*

The essay skill refused with "insufficient evidence" on a topic the corpus clearly covered.

Cause: `retrieval_max_chunks_per_episode` defaults to 2 — a good rule for *answers*, since
it forces synthesis across sources instead of parroting one episode. But an essay needs far
more material, and with only a few relevant episodes the cap starved it below the minimum
chunk count before length could even be attempted. The diversity feature was fighting the
essay feature.

Fix: `RetrievalService.retrieve` takes a per-call `max_chunks_per_episode`, and the essay
skill passes `essay_max_chunks_per_episode` (6). An essay may legitimately lean on one
deep-dive episode; an answer should not. This is why two sets of retrieval parameters exist.

### `README.md` was indexed as a transcript *(real product bug)*

Caught during live verification, not by a test: the ingestion run reported
`title=Readme … chunks=2`. Both `data/transcripts/` and `data/sample-transcripts/` ship a
README explaining what to put there — and the loader dutifully indexed them.

The assistant could therefore have cited "Readme" as though it were an episode, in a product
whose entire claim is trustworthy citations. Fix: skip documentation stems (`readme`,
`license`, `contributing`, `changelog`, `notes`) in the loader, plus a regression test named
for the reason rather than the mechanism
(`test_documentation_alongside_the_corpus_is_not_indexed`).

Worth noting: no unit test would have caught this. It needed running the real pipeline over
the real directory.

### Message ordering was non-deterministic

A test asserting conversation order failed intermittently. Cause: PostgreSQL's `now()` is
**transaction-scoped**, so a user message and its assistant reply written in one transaction
share an identical `created_at`, leaving their relative order undefined.

Fix: a sequence-backed `seq BIGINT` column as the ordering key, with
`ix_messages_session_seq(session_id, seq)`, and all ordering switched to it. `created_at`
remains for display. A flaky test caught a real correctness bug — the note worth keeping.

### The CSS sanitiser left attacker-supplied URLs as text

A test asserting `evil.test` was absent from sanitised output failed. The original filter
removed the offending *keyword* (`@import`) but left the rest of the declaration, so the URL
survived as leftover text in the style block.

Fix: match and remove **whole at-rules and declarations** via regex, so nothing
attacker-supplied remains. Applies to `@import`, `expression()`, `url(javascript:…)`,
`-moz-binding` and `behavior`.

### CRLF line endings broke the container entrypoint

`docker compose up` produced `exec /entrypoint.sh: no such file or directory` — a misleading
message: the file existed, but the shebang read `#!/bin/sh\r`, so the kernel looked for an
interpreter literally named `/bin/sh\r`.

Fixed at both levels, deliberately: `.gitattributes` with `*.sh text eol=lf` so checkouts are
correct, **and** `sed -i 's/\r$//'` in the Dockerfile so the build works even from a working
tree that already has CRLF. Belt and braces, because an evaluator on Windows hitting this at
`docker compose up` would likely stop there.

### `CORS_ORIGINS` crashed startup

`SettingsError: error parsing value for field "cors_origins"`. pydantic-settings
JSON-decodes complex types from the environment *before* validators run, so the
comma-separated list in `docker-compose.yml` was not valid JSON — and the existing
`mode="before"` validator never got the chance to split it.

Fix: annotate the field `Annotated[list[str], NoDecode]` to opt out of JSON decoding, letting
the validator handle splitting. Keeps the operator-facing format natural
(`a,b`) rather than forcing `["a","b"]`.

### A security test was testing the wrong thing

`test_config_exposes_providers_without_leaking_secrets` failed because the string `api_key`
appeared in the response — inside the helpful diagnostic *"ANTHROPIC_API_KEY missing
(optional unless LLM_PROVIDER=anthropic)"*.

The test was wrong, not the code: it forbade the variable *name*, when the thing that must
never leak is the *value*. Rewritten as two tests — one asserting provider information is
exposed, one planting a recognisable key value and asserting it never appears in a
serialised response. The stronger assertion, and it no longer blocks a useful error message.

### A test encoded a wrong assumption about HTML

`test_dangerous_elements_are_dropped_entirely` failed for `link`, `base` and `embed`. These
are **void elements** — they have no children, so "dropped with their contents" is
meaningless for them. Split into two tests with accurate names: containers dropped with
their subtree, void elements dropped outright.

### Smaller corrections

| Issue | Fix |
| --- | --- |
| `beautifulsoup4==4.15.2` did not exist | Pinned `4.15.0` |
| Host port 5432 already taken by an unrelated container | `POSTGRES_HOST_PORT` (default 5433); container port unchanged at 5432 |
| `psycopg` async fails on Windows' default `ProactorEventLoop` | `core/runtime.py` sets the selector policy; called from `run_local.py`, the ingest CLI and `conftest.py`. No-op elsewhere |
| `HashEmbedder` gave poor relevance separation, so retrieval tests failed | Added stopword filtering and sub-linear term frequency; test threshold set to 0.90 with a comment explaining it is calibrated for the hash embedder, not production |
| Ship 30 word-count tests failed | The test *helper* miscounted — it ignored words contributed by the title and headings. Fixed the helper, not the assertion |
| `pytest` could not `import app` in the test image | `pythonpath = .` in `pytest.ini`, so both `pytest` and `python -m pytest` work on host and in container |
| CSS `@import` placed at the end of `index.css` | Moved to the top per spec, with a comment noting custom properties are order-independent |
| TypeScript: `import.meta.env` unknown; test error types too wide | Added `vite/client` to `tsconfig` types; added typed `captureError`/`firstRequest` test helpers |

---

## Dead code and inaccurate documentation removed

Found during final cleanup, and worth listing because each was a small honesty problem:

- **`python-frontmatter` was declared but never imported** — the loader implements its own
  flat front-matter parsing. Removed from `requirements.txt`.
- **`conftest.py` defined `FIXTURE_DIR` pointing at `tests/fixtures/transcripts`, which did
  not exist**, and its module docstring claimed a "bundled corpus" lived there. In fact tests
  seed content inline via `seed_transcript`. Both the constant and the false claim were
  removed. Documentation describing something that does not exist is worse than no
  documentation.
- An unused `json` import and a placeholder `_unused_json_guard` function in the Claude SDK
  runtime.

---

## Decisions worth recording

**Refuse before generating, not after.** The relevance threshold runs before the LLM call, so
"not enough information" is deterministic rather than a behaviour the model might exhibit.
Verified live: with an empty index, the response carried
`refusal_reason: knowledge_base_empty` and `model_ms: 0` — the model genuinely was not
called.

**Grounding enforced in three layers.** Prompt wording alone is not a control. So: threshold
before generation, evidence-only prompt during, and `[Sn]` marker verification against real
chunk ids after. The third layer is what makes citation validity a property of the code
rather than a hoped-for success rate.

**A hand-written HTML allowlist rather than `bleach`.** Generating HTML *with CSS* is a
requirement, and general-purpose cleaners escape `<style>` contents, breaking every generated
page. Accepting bespoke security code was only reasonable because it is not the primary
boundary — the script-disabled sandboxed iframe is, and the browser enforces that.

**`cited` persisted rather than derived.** The distinction between "the model was given this"
and "the model used this" is the product's honesty claim, so it is written at persist time
and survives a reload.

**No automatic cloud failover when Ollama fails.** Tempting for resilience, wrong here:
it would make the model behind an answer unknowable and could send transcript content to a
third party the operator did not choose for that request.

**No streaming.** Citation markers must be validated against retrieved chunks before display,
which needs the complete response. Chose staged progress plus elapsed seconds over streaming
with a later correction pass.

**A synthetic fixture, clearly labelled and kept out of the corpus directory.** With no real
transcripts, an evaluator could not tell "working and honest" from "broken" — both decline
every question. So `data/sample-transcripts/` holds one file I wrote, with speakers "Host"
and "Fixture Speaker" and a `example.invalid` URL so it can never be mistaken for a real
citation, plus a README saying exactly that and how to remove it before a demo.

---

## What was verified live, and what was not

Stated here because an untested path is a real risk, not a footnote.

**Verified live** against the running stack: Alembic migrations; session creation,
isolation and persistence; ingestion of the official Lenny's Data starter pack (50
transcripts, 4984 chunks); pgvector retrieval; grounded Ollama answers (`llama3.1:8b` +
`nomic-embed-text`); honest refusal of out-of-corpus questions (often after a weak-retrieval
LLM call, not only the pre-LLM threshold); structured errors; `/health` and `/api/config`;
nginx; Anthropic-without-key → `provider_not_configured` with no Ollama fallback.

**Not verified live:** Anthropic generation (no API key). Latest Ship 30 live quality after
the H2 cap has not been re-run for submission. Automated test counts belong in the latest
pytest / `npm test` output, not frozen here.
