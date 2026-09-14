# PRD — The Lenny Growth Assistant

Product requirements for a transcript-grounded product and growth assistant.
Technical design in [`architecture.md`](architecture.md), UI reasoning in
[`design.md`](design.md), build sequence in
[`docs/implementation-plan.md`](docs/implementation-plan.md).

---

## 1. User

**Primary: an operator at a startup** — a product manager, growth lead or founder who needs
a specific answer to a specific problem ("our activation is flat, what do people who have
solved this actually do?") and has neither hours of podcast listening nor tolerance for
advice that might be invented.

They are experienced enough to be sceptical. They will not act on a recommendation they
cannot check, and a single confidently fabricated claim costs them all trust in the tool.

**Secondary: a content operator** who has already reached a conclusion in conversation and
needs to publish it — a Ship 30 for 30-style essay, a strategy document, or a landing page —
without leaving the tool and without hand-writing the connective tissue.

**Third, and the one shaping near-term decisions: a technical evaluator.** Someone who
clones the repository, has ~30 minutes, and is deciding whether the engineering is sound.
They need it to run on one command, be obviously not faked, and be honest about its own
limits. Where the interests of the operator and the evaluator diverge, this document says so.

## 2. Problem

Lenny's Podcast contains a large amount of specific, hard-won operating knowledge — how
particular teams fixed activation, priced a product, or found a growth loop. That knowledge
is locked in hours of audio.

The two available options both fail:

- **Search the transcripts yourself.** Accurate, but slow, and it only surfaces passages,
  not a synthesised answer to your situation.
- **Ask a general chatbot.** Fast and fluent, and it will attribute plausible advice to
  guests who never gave it. Because it answers everything, you cannot tell which parts are
  real.

The specific failure this product exists to fix: **a RAG system that falls back on the
model's general knowledge when retrieval finds nothing makes its own citations
meaningless.** If every question gets an answer, "here are the sources" is decoration —
the user has no way to distinguish grounded from guessed, so they must either verify
everything or trust everything.

## 3. Jobs to be done

| When… | I want to… | So that… |
| --- | --- | --- |
| I hit a growth problem | ask it in my own words and get a synthesised answer from people who solved it | I start from operating experience, not first principles |
| I get an answer | see the exact excerpt behind each claim | I can act on it, or cite it to my team, without re-listening |
| The corpus does not cover my question | be told that plainly | I go elsewhere instead of acting on a fabrication |
| I am mid-conversation | ask a follow-up in context ("what about for B2B SaaS?") | I refine without restating everything |
| I reach a useful conclusion | turn it into a publishable essay | I share the thinking beyond a chat log |
| I am pitching an idea | generate a landing page or strategy doc | I can show it rather than describe it |
| I am working on several problems | keep separate conversations | contexts do not bleed together |
| I am evaluating or demoing this | run it locally with no cloud account | there is no signup, cost or data-egress question |

## 4. Product goal

**Make transcript knowledge usable without making it untrustworthy.**

Concretely: an assistant whose answers are either traceable to a specific transcript excerpt
or explicitly absent. The product's differentiator is not answer quality — it is that you
can tell, per claim, whether an answer is grounded, and that the system declines rather than
improvises.

Secondary goal: close the loop from question to deliverable, so a conclusion can leave the
tool as an essay or a page.

**Explicit non-goal:** being able to answer everything. Coverage is bounded by the corpus,
by design.

## 5. Success metrics

**All figures below are targets, not measurements.** No metric here has been measured on a
real corpus — the repository ships with no transcripts, and building the labelled evaluation
set required to measure retrieval quality is listed as future work
([README §Future Improvements](README.md#future-improvements)). Stating them as achieved
would be exactly the kind of fabrication this product exists to avoid.

### Grounding quality — the metrics that matter

| Metric | Target | How it would be measured |
| --- | --- | --- |
| Citation validity | 100% | Every `[Sn]` in an answer resolves to a retrieved chunk. **Structurally enforced today**: markers are verified against real chunk ids and invalid ones stripped, so this is a property of the code, not a hoped-for rate |
| Claim support rate | ≥ 90% | Human review of a sample: does the cited excerpt actually support the claim? Requires the evaluation set |
| Correct refusal rate | ≥ 95% | On a set of out-of-corpus questions, how often the assistant declines instead of answering |
| False refusal rate | ≤ 10% | On in-corpus questions, how often it declines something the corpus covers. Directly traded against the metric above via `RETRIEVAL_MAX_DISTANCE` |
| Retrieval precision@6 | ≥ 0.7 | Fraction of retrieved chunks a reviewer judges relevant |

Correct-refusal and false-refusal are the pair worth watching: they move in opposite
directions, and the threshold that balances them depends on the corpus. This product
deliberately biases toward refusing.

### Reliability

| Metric | Target |
| --- | --- |
| Session persistence | 100% — no message acknowledged to the UI is ever lost |
| Session isolation | 100% — no context crosses sessions (asserted by tests today) |
| Artifact render success | ≥ 98% of generated artifacts render without a viewer error |
| Unhandled 5xx rate | < 0.5% — expected failures carry a code and a remedy |
| Ingestion idempotency | 100% — re-running with no changes writes nothing (asserted by tests today) |

### Task success

| Metric | Target |
| --- | --- |
| Essay within tolerance | ≥ 80% of essays land within ±15% of 1,250 words |
| Artifact usable as-is | ≥ 70% need no manual editing before use |
| Follow-up resolution | ≥ 90% of follow-ups retrieve appropriately for the implied subject |

### Evaluator experience

| Metric | Target |
| --- | --- |
| Time to first grounded answer, from clone | ≤ 15 min (excluding model download) |
| Commands to a running app | 3 — `cp .env.example .env`, `docker compose up`, one ingest |
| Setup failures needing the README | 0 — every blocking condition is surfaced in the UI with its fix command |

### Performance (local, `llama3.1:8b`, mid-range laptop)

| Stage | Target |
| --- | --- |
| Retrieval | < 300 ms |
| Grounded answer, end to end | < 60 s |
| Ship 30 essay | < 180 s (two passes when revision triggers) |
| Ingestion | < 30 s per hour-long transcript |

## 6. Assumptions

Assumptions that shaped the build, with what falls over if each is wrong:

1. **The evaluator supplies the corpus.** Transcripts are the podcast's content, so none are
   bundled. *If wrong* (data was expected in-repo): the ingestion path, docs and a
   clearly-labelled synthetic fixture make this a 5-minute step rather than a blocker.
2. **The demo must run on Ollama, so the local model is the primary target.** This drives
   deterministic routing over an autonomous agent loop. *If wrong* (cloud-first was
   acceptable): selecting Anthropic already uses `ClaudeAgentSDKRuntime` behind the same
   skill registry.
3. **Refusing is better than hedging.** A wrong-but-cited answer damages trust more than an
   unnecessary refusal. *If wrong* for a given corpus: one variable
   (`RETRIEVAL_MAX_DISTANCE`) moves the balance.
4. **Single-user, local, trusted network.** No auth, no rate limiting, no per-user session
   scoping. *If wrong*: all three are prerequisites before any shared deployment, and are
   listed as such.
5. **Dense retrieval suffices at this corpus size.** Tens to low hundreds of episodes.
   *If wrong* (exact-phrase and acronym queries underperform): hybrid BM25 is the first
   listed improvement.
6. **Transcripts carry speaker labels.** `Speaker: text` is common in published transcripts
   and improves chunking. *If wrong*: chunking falls back to paragraph and sentence
   boundaries, and the speaker field stays empty. Handled, not assumed away.
7. **Generated HTML needs no JavaScript.** The deliverable is a static page. *If wrong*:
   the security model would need rethinking, since scripting is disabled by design.
8. **Approximately 1,250 words means ±15%.** The assignment says "approximately"; the
   tolerance is our interpretation, and it is reported in the response metadata rather than
   hidden.

## 7. Scope

**Conversation**
- Independent sessions with persistent history and timestamps
- Grounded Q&A restricted to retrieved evidence
- Inline `[Sn]` citations, verified against retrieved chunks
- Source display: title, episode, guest, URL, excerpt, speaker, file, chunk index
- Cited sources distinguished from merely retrieved
- Honest refusal below the relevance threshold, with no model call
- Follow-up context, bounded by message count and characters

**Knowledge base**
- Ingestion of `.txt`, `.md`, `.vtt`, `.srt`, `.json`
- Cleaning, speaker-turn chunking with overlap, local embeddings, pgvector indexing
- Metadata read from front matter, a `metadata.json` sidecar, or JSON fields — never inferred
- Idempotent re-ingestion by content hash; per-file failure isolation
- A CLI with `--status`, `--force`, `--dir`

**Generation**
- Ship 30 for 30 essay skill: ~1,250 words, grounded, with a bounded revision pass
- Markdown artifacts
- Complete standalone HTML/CSS artifacts
- In-app Artifact Viewer with sandboxed HTML rendering and a visible sanitiser report

**Providers**
- Local Ollama (default) and Anthropic Claude behind one interface
- Configurable by environment variable; per-request override
- Active provider and model always visible in the UI
- Distinct, actionable errors for down / unconfigured / timeout / failure

**Platform**
- FastAPI, PostgreSQL + pgvector, Alembic migrations
- React + TypeScript + Vite frontend
- Docker Compose one-command startup
- Structured JSON logging with request correlation
- `/health` distinguishing API, database, provider and knowledge-base state
- Automated tests (backend pytest + frontend vitest); a manual UI test plan

## 8. Out of scope

| Not building | Why |
| --- | --- |
| Authentication, accounts, roles | Single-user local tool; the assignment excludes it. Required before any shared deployment |
| Multi-tenancy | Follows from the above |
| Audio ingestion / transcription | The input is transcripts. `whisper` output already works as `.vtt` |
| Automatic transcript scraping | Rights and robustness belong to whoever supplies the corpus |
| Answers from outside the corpus | This is the entire point |
| Automatic cloud failover when Ollama fails | Would make the model behind an answer unknowable and could send transcript content to an unchosen third party |
| Streaming responses | Complicates citation verification, which needs the whole response. Staged progress instead |
| Fine-tuning or a custom model | Retrieval, not model weights, is the problem |
| Analytics dashboards, payments, social features | Unrelated to the jobs to be done |
| Redis, queues, Kubernetes, microservices | No requirement at this scale |
| Artifact editing / version history | Nice, not required. Listed as a future improvement |
| Hybrid retrieval and reranking | Real quality wins, but dense-only is sufficient at this corpus size and much simpler to explain. First two future improvements |

## 9. User flows

**A. First run (evaluator)**

```
clone → cp .env.example .env → ollama pull ×2 → docker compose up
  → open :3000
  → header: "Ollama (local) · llama3.1:8b"; banner: "No transcripts indexed" + command
  → run ingest
  → banner clears; header shows chunk count
```
The banner is the flow: a fresh clone cannot answer anything, and the UI says so with the
fix rather than failing silently or pretending.

**B. A grounded question**

```
"+ New chat" → type a question → Enter
  → "Searching the transcript knowledge base…"  (~0.3s)
  → "Generating a grounded answer…"  + elapsed seconds
  → answer with [S1]/[S2] markers
  → SOURCES: "2 cited of 6 retrieved"
  → "Show excerpt" → the exact retrieved text, file, chunk, speaker
```

**C. A question the corpus does not cover**

```
ask something off-corpus
  → retrieval finds nothing past threshold
  → NO model call
  → "I couldn't find enough relevant information in the Lenny transcript
     knowledge base to answer that confidently."
  → styled as a normal message, not an error
```

**D. Follow-up**

```
"How should I improve activation?"        → grounded answer
"What about for B2B SaaS?"                → query composed with prior turns
                                          → retrieves B2B-relevant chunks
                                          → grounding still only from retrieval
```

**E. Ship 30 essay**

```
"Write a Ship 30 for 30 essay about activation"
  → essay intent → broader retrieval (top_k 12, higher per-episode cap)
  → thin evidence?  → "not enough transcript evidence", no essay
  → otherwise: draft → word count after citation cleanup → if short, continue (max 3 generations)
  → target ~1,250 words (1,062–1,437): H1, 4–6 H2 sections, bullets, selective bold, inline citations
  → metadata reports actual word count and whether it hit tolerance. Live quality after the H2 cap is not claimed verified.
```

**F. Artifact**

```
"Create a landing page for this idea"   (or the viewer's form)
  → artifact intent, format html
  → generate → strip fences → extract title → sanitise → report
  → persist, return in the chat response
  → viewer: sandboxed iframe (no scripting); note listing anything stripped
```

**G. Switching provider**

```
.env: LLM_PROVIDER=anthropic + ANTHROPIC_API_KEY
  → docker compose up -d backend
  → header: "Anthropic (cloud) · claude-sonnet-4-5"
  → identical behaviour; no application code differs
  (key missing → "provider not configured" + remedy, not a crash)
```

## 10. Acceptance criteria

**Grounding** *(the criteria that define the product)*
- [x] An answer's `[Sn]` markers all resolve to chunks actually retrieved for that turn; invalid markers are stripped
- [x] Below the relevance threshold, the canonical refusal is returned **and no LLM call is made**
- [x] An empty knowledge base declines every question, with `refusal_reason` recorded
- [x] Sources the answer used are distinguishable from those merely retrieved, in both API and UI
- [x] Metadata absent from a transcript is never invented — no fabricated episode, guest or URL
- [x] Prior conversation turns inform interpretation but are never supplied as evidence

**Conversation**
- [x] Create, list, switch and delete sessions; history persists in PostgreSQL
- [x] No context crosses sessions
- [x] Message order is deterministic (sequence-backed, not timestamp-dependent)
- [x] Follow-ups retrieve for the implied subject
- [x] History is bounded by message count and characters

**Knowledge base**
- [x] All five formats ingest; metadata read with documented precedence
- [x] Chunks preserve title, episode, guest, URL, file, chunk index, speaker and character offsets
- [x] Re-running with no changes writes nothing; editing one file re-indexes only that file
- [x] A malformed file is reported without aborting the run; exit code is non-zero
- [x] Documentation beside the corpus (`README`, `LICENSE`) is not indexed

**Generation**
- [x] Ship 30 essay is a separate skill, not an inline prompt in the chat handler
- [x] Essay targets 1,250 words within ±15%, with a bounded revision pass; actual count reported
- [x] Essay refuses on insufficient evidence
- [x] Markdown and complete HTML/CSS artifacts generate and persist as their own entity
- [x] The viewer renders both, with title, loading, error and sanitised states

**Security**
- [x] HTML artifacts reach the DOM only as an iframe `srcdoc` with no `allow-scripts`
- [x] `script`, `iframe`, `form`, `on*` handlers, `javascript:` URLs and CSS script vectors are removed server-side
- [x] A CSP meta is injected; what was removed is reported in the UI
- [x] Markdown is DOMPurify-sanitised under an explicit allowlist
- [x] No secret is logged or returned; a test asserts a planted key value never appears in a response
- [x] All database access is parameterised

**Providers**
- [x] Ollama and Anthropic behind one interface; switching is one variable, no code change
- [x] Active provider and model visible in the UI
- [x] Down / unconfigured / timeout / failure each produce a distinct code with a remedy
- [x] `/health` stays `200` when an optional cloud provider is unconfigured

**Operability**
- [x] `docker compose up` starts the stack; migrations apply automatically with retry
- [x] `/health` distinguishes API, database, provider and knowledge-base state
- [x] Structured logs correlate one request by `request_id`
- [x] Blocking setup problems are surfaced in the UI with the command that fixes them
- [x] Keyboard navigable, labelled, responsive to 720px

**Verified live** — migrations, session persistence, ingestion (including idempotency and
docs exclusion), pgvector retrieval ranking and threshold behaviour, honest refusal,
structured errors, nginx proxying, and the automated test suites.
**Verified live** — Ollama chat (`llama3.1:8b`) and `nomic-embed-text` embeddings against
the official 50-transcript / 4984-chunk corpus.
**Not verified live** — Anthropic generation (no key). Latest Ship 30 live quality after
the H2 cap has not been re-run for submission.

## 11. Risks

| Risk | Impact | Likelihood | Mitigation |
| --- | --- | --- | --- |
| Threshold mistuned for the evaluator's corpus → refuses good questions | High — looks broken | Medium | One documented variable; `retrieval_completed` logs `candidates` vs `selected` and `best_distance`, so mistuning is diagnosable in one line. Troubleshooting table names it |
| Small local model produces uncited or thin answers | High — undermines the demo | Medium | Markers verified structurally; `uncited_answer` flagged in metadata and surfaced; `llama3.1:8b` recommended over 3B |
| Live Ollama path unverified by the author | High | — | Stated openly in README, PRD and audit; manual test plan leads with it; failure modes are explicitly handled and tested against a fake provider |
| Evaluator has no transcripts and stops | High | Medium | Synthetic fixture ingests in one command; UI banner carries the command; `docs/transcripts.md` covers sourcing |
| Sanitiser bypassed by a mutation-XSS trick | High if it were the only control | Low | It is not the only control — the script-disabled sandboxed iframe is the boundary, and the browser enforces it |
| Model invents an episode or guest despite the prompt | High — the core trust claim | Low | Metadata comes from the database, not the model; the UI renders stored metadata, never model-asserted names |
| First response times out while the model loads | Medium — looks broken on message one | Medium | Generous provider timeout, staged progress with elapsed seconds, troubleshooting entry recommending a warm-up run |
| Essay misses the word target on a small model | Medium | Medium | One bounded revision pass; actual count reported honestly rather than hidden |
| Chunk boundary splits a claim from its context | Medium — subtly wrong citation | Low | Speaker-turn chunking with overlap so a boundary-spanning claim survives intact somewhere |
| CRLF checkout breaks the container entrypoint on Windows | Medium — fails at startup | Was actual | Fixed twice over: `.gitattributes` `eol=lf` and a `sed` in the Dockerfile |
| Corpus grows past comfortable dense-only retrieval | Medium | Low near-term | HNSW scales well; hybrid retrieval is the first future improvement |

## 12. Trade-offs

Fuller technical discussion in [`architecture.md`](architecture.md#20-trade-offs). The
product-level shape:

**Trustworthiness over coverage.** Refusing before generating means the assistant answers
less. That is the product.

**Predictability over autonomy** *(the central trade-off).* Deterministic routing rather
than an autonomous tool loop, because the demo must work on an 8B local model where
tool-call JSON is unreliable and each round trip costs 10–20s. The Claude Agent SDK runtime
is implemented behind the same interface, so the capability exists and is swappable — it is
simply not the default, because it cannot drive a local model and making it default would
mean the documented agent layer and the demo path were different code. Cost: no chaining of
skills within one turn.

**Simplicity over retrieval sophistication.** Dense-only, no reranker. A reviewer can read
`retrieval.py` in a few minutes and know exactly why a chunk was or was not used. Cost:
weaker on exact-phrase and acronym queries.

**Local over hosted.** Ollama for both chat and embeddings: no account, no cost, no egress.
Cost: slower, and hosted embeddings would likely retrieve slightly better.

**Correctness over perceived speed.** No streaming, because citations must be verified
against retrieved chunks before display.

**Explicit failure over graceful degradation.** No automatic cloud failover; a provider
failure is surfaced with its remedy. Cost: a hard stop instead of a degraded answer — the
right choice when the answer's provenance is the product.

**Fewer dependencies over faster styling.** Plain CSS, no component library. Cost: more
hand-written CSS.

## 13. Implementation plan

Delivered in the order below; each phase was tested before the next.
Detail: [`docs/implementation-plan.md`](docs/implementation-plan.md).

| Phase | Delivered | Verification |
| --- | --- | --- |
| 1 | Repository inspection, dependency research, plan | — |
| 2 | FastAPI skeleton, config, structured logging, error taxonomy, ORM, migrations | Migrations apply on a clean database |
| 3 | Session and chat REST APIs with validation and structured errors | Session isolation and persistence tests |
| 4 | Ingestion pipeline and pgvector retrieval | Chunking, loader, idempotency, ranking and threshold tests; live ingest + retrieval probe |
| 5 | `LLMProvider` interface, Ollama provider, failure translation | Provider routing and failure tests |
| 6 | Anthropic provider and configuration errors | Missing-key and error-translation tests |
| 7 | Agent layer: registry, deterministic router, Claude SDK runtime | Routing tests; SDK contract against a stub |
| 8 | Grounded answering with citation verification and refusal | End-to-end grounding, citation and refusal tests |
| 9 | Ship 30 essay skill with revision pass | Word count, grounding and refusal tests |
| 10 | Artifact generation, builder, sanitiser, Artifact Viewer | Generation, persistence and sanitiser tests |
| 11 | Security hardening: sandbox, CSP, body limits, secret hygiene | Security tests, including no-secret-in-response |
| 12 | Frontend: hooks, components, styles, accessibility, responsive | Frontend tests; manual test plan |
| 13 | Test suites: backend pytest + frontend vitest | Full run in a container / `npm test` |
| 14 | Docker Compose, multi-stage images, nginx proxy, test profile | Live stack verified end to end |
| 15 | README, PRD, design, architecture, transcripts, test plan, demo script | Cross-checked against the code |
| 16 | Evaluator audit and cleanup | [`docs/final-evaluator-audit.md`](docs/final-evaluator-audit.md) |

Two phases produced real corrections worth recording, because they changed the product and
not just the code:

- **Phase 9** exposed a genuine bug: the per-episode diversity cap that keeps *answers*
  varied was starving *essays* of evidence, so an essay would refuse whenever the corpus had
  few but highly relevant episodes. Retrieval now takes a per-call override and the essay
  skill passes its own.
- **Phase 14** exposed that the loader indexed `README.md` from the transcript directories,
  which would let the assistant cite a "Readme" as an episode. Documentation stems are now
  skipped, with a regression test.
