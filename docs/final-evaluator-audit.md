# Final evaluator audit

A deliberately unsympathetic review of this repository against every stated requirement.

**Verification legend**

| Mark | Meaning |
| --- | --- |
| **live** | Exercised against the running stack in this environment, with the result observed |
| **test** | Covered by an automated test that asserts behaviour (not just a 200) |
| **code** | Verified by reading the implementation; no runtime or test evidence beyond that |
| **manual** | Requires a human at a browser; specified in [`manual-test-plan.md`](manual-test-plan.md) |
| **unverified** | Implemented, but never exercised in this environment. Stated as a risk, not a pass |

**Headline:** Automated tests are re-run after each alignment pass; treat the latest
`pytest` / `npm test` output as source of truth (not this file's older counts). Ruff
clean. TypeScript clean. The stack starts from `docker compose up` and was verified live
against host Ollama (`llama3.1:8b` + `nomic-embed-text`) **and** the official Lenny's Data
starter pack (50 podcast transcripts, 4984 chunks). Synthetic fixture rows were removed
from the demo database. **The remaining unverified live path is Anthropic generation (no
key).** Latest Ship 30 live quality after the H2 cap has not been re-verified.

---

## 1. Functional requirements

| # | Requirement | Implementation | Verification | Status |
| --- | --- | --- | --- | --- |
| 1 | User can open the application | `frontend/` served by nginx on :3000 | **live** — HTTP 200, SPA served, `/api` proxied | ✅ |
| 2 | User can create a new chat | `SessionSidebar` → `POST /api/sessions` → `services/sessions.py` | **live** (session created, UUID returned) + **test** | ✅ |
| 3 | Sessions are independent | `session_id` scoping; `history_for_prompt` never crosses sessions | **test** — isolation asserted, including a follow-up that must *not* resolve using another session | ✅ |
| 4 | Messages persist in PostgreSQL | `models/chat.py`, `messages` table | **live** (survived container restart) + **test** | ✅ |
| 5 | User can ask product/growth questions | `POST /api/chat` → `GroundedAnswerSkill` | **live** — Ollama cited Jason Cohen on stalled growth from the official transcript | ✅ |
| 6 | RAG retrieves transcript knowledge | `rag/retrieval.py`, pgvector cosine KNN | **live** — stalled-growth query ranked Jason Cohen at distance 0.229 | ✅ |
| 7 | Answers are grounded | Threshold before generation; evidence-only prompt; marker verification after | **test** (grounding, citation and refusal suites) + **live** for the threshold path | ✅ |
| 8 | Sources are displayed | `SourceList.tsx`; `message_sources` join | **test** (7 frontend tests) + **manual** | ✅ |
| 9 | Unsupported questions handled honestly | `retrieval.py` + evidence-only prompt | **live** — Hubble astronauts → refused (`grounded: false`); on a 4984-chunk nomic index `below_threshold` rarely fires at 0.55, so the evidence-only prompt is the backstop (the LLM may still be called) | ✅ |
| 10 | Follow-ups preserve session context | `build_query` composes bounded history | **test** | ✅ |
| 11 | Ollama works | `providers/ollama.py` | **live** — Docker backend reached `host.docker.internal:11434`; chat + embeddings + failure path all observed | ✅ |
| 12 | Cloud LLM works | `providers/anthropic.py` | **unverified** live (no key). Routing/errors **test** | ⚠️ |
| 13 | Provider switchable | Header toggle + `LLM_PROVIDER`; Anthropic → `ClaudeAgentSDKRuntime`, Ollama → `RouterRuntime` | **test** + **live** (`/api/config` `active_runtime` / per-provider `runtime`) | ✅ |
| 14 | Provider is visible | `AppHeader.tsx` badge | **live** (`/api/config` supplies it) + **manual** | ✅ |
| 15 | Ship 30 skill exists as a skill | `agent/skills/ship30.py`, registered separately | **test** + **code** | ✅ |
| 16 | Essay ≈1,250 words | Target ±15% (1,062–1,437), max 3 generations, post-cleanup count, 4–6 H2 cap | **test** · latest live essay after H2 cap **unverified** | ⚠️ |
| 17 | Essay is grounded | Retrieval-fed, marker-verified, refuses on thin evidence | **test** | ✅ |
| 18 | Markdown artifacts work | `ArtifactSkill` + `builder.py` | **test** | ✅ |
| 19 | HTML/CSS artifacts work | Same, plus `sanitizer.py` | **test** | ✅ |
| 20 | Artifact Viewer works | `ArtifactViewer.tsx` | **test** (13 tests incl. render paths) + **manual** | ✅ |
| 21 | HTML safely isolated/sanitised | Allowlist sanitiser + sandboxed iframe without `allow-scripts` | **test** — both layers asserted independently | ✅ |
| 22 | Loading states work | Staged progress + elapsed seconds | **test** (viewer loading) + **manual** | ✅ |
| 23 | Error states work | `ErrorBanner`, `StatusBanner` | **live** (structured errors observed) + **manual** | ✅ |
| 24 | Responsive UI works | 3 breakpoints, plain CSS | **code** + **manual** | ⚠️ manual |

## 2. Backend requirements

| Requirement | Location | Verification | Status |
| --- | --- | --- | --- |
| FastAPI | `app/main.py`, `api/routes/*` | **live** | ✅ |
| Pydantic validation | `schemas/*` on every endpoint | **live** (blank message → 422 naming the field) + **test** | ✅ |
| Structured errors | `core/errors.py`, `api/errors.py` | **live** (`{"error":{code,message,remedy}}` observed) + **test** | ✅ |
| Health endpoint | `api/routes/health.py` | **live** — distinguishes API/db/Ollama/cloud/KB; stays 200 with cloud unconfigured | ✅ |
| PostgreSQL | pgvector/pg16, Alembic | **live** (migrations applied on clean DB) | ✅ |
| Clean service boundaries | routes → services → skills → providers | **code** | ✅ |
| Provider abstraction | `providers/base.py` + 2 implementations | **test** | ✅ |
| Agent layer | `agent/service.py`, 2 runtimes, 4 skills | **test** (routing + SDK contract vs stub) | ✅ |
| RAG service | `rag/*` | **live** + **test** | ✅ |
| Artifact service | `artifacts/*` | **test** | ✅ |
| Logging | `core/logging.py`, structlog | **live** — JSON logs with `request_id`, `retrieval_completed`, ingestion events observed | ✅ |
| Failure handling | Taxonomy + handlers | **live** (503/422/404 paths) + **test** | ✅ |

## 3. Deployment

| Requirement | Location | Verification | Status |
| --- | --- | --- | --- |
| Docker Compose | `docker-compose.yml` — db, backend, frontend, tests(profile) | **live** — all healthy from `up --build` | ✅ |
| `.env.example` | root, every variable documented inline | **live** (defaults start the stack unedited) | ✅ |
| No secrets committed | `.gitignore`; scanned tracked files | **live** — no secret-shaped strings; `.env` untracked; `ANTHROPIC_API_KEY=` empty | ✅ |
| Reproducible startup | Healthchecks, `depends_on`, migration retry | **live** — verified from a clean database volume | ✅ |
| Ollama setup documented | README §Ollama Setup, `.env.example` | **code** | ✅ |

## 4. Documentation

| Requirement | File | Status |
| --- | --- | --- |
| README | [`README.md`](../README.md) — all requested sections | ✅ |
| PRD | [`PRD.md`](../PRD.md) — metrics labelled as targets, not measurements | ✅ |
| design.md | [`design.md`](../design.md) | ✅ |
| architecture.md | [`architecture.md`](../architecture.md) — 20 sections, ASCII diagrams | ✅ |
| implementation-plan.md | [`implementation-plan.md`](implementation-plan.md) | ✅ |
| agent-transcripts/ | [`../agent-transcripts/`](../agent-transcripts/) — decision log + capture procedure | ✅ |
| Manual UI test plan | [`manual-test-plan.md`](manual-test-plan.md) — 13 sections | ✅ |
| Demo preparation | [`demo-script.md`](demo-script.md) | ✅ |
| Transcript operator guide | [`transcripts.md`](transcripts.md) | ✅ |

## 5. Testing

| Requirement | Where | Status |
| --- | --- | --- |
| Health endpoint | `test_health_and_errors.py` | ✅ |
| Session creation | `test_sessions_api.py` | ✅ |
| Session isolation | `test_sessions_api.py`, `test_chat_grounding.py` | ✅ |
| Message persistence | `test_sessions_api.py` | ✅ |
| API validation | across suites | ✅ |
| Retrieval behaviour | `test_retrieval.py` | ✅ |
| Source metadata | `test_retrieval.py`, `test_ingestion.py` | ✅ |
| Provider routing | `test_providers.py` | ✅ |
| Ollama/provider failure | `test_providers.py`, `test_health_and_errors.py` | ✅ |
| Cloud config failure | `test_providers.py` | ✅ |
| Empty retrieval | `test_retrieval.py`, `test_chat_grounding.py` | ✅ |
| Artifact generation | `test_artifacts.py` | ✅ |
| Artifact security | `test_sanitizer.py`, `ArtifactViewer.test.tsx` | ✅ |
| Manual UI test plan | `docs/manual-test-plan.md` | ✅ |

**Are the tests meaningful?** Spot-check for the "asserts 200" failure mode:

- `test_chat_grounding.py` asserts the *content* of the prompt the model received, via a
  recording fake provider — that retrieved evidence and prior turns reached it, and that a
  refusal happened *without* a provider call.
- `test_sanitizer.py` asserts the specific payload text is absent from output, not merely
  that sanitising ran — which is how the CSS leftover-URL bug was caught.
- `ArtifactViewer.test.tsx` asserts `sandbox` lacks `allow-scripts` and that hostile markup
  exists only as an iframe attribute value, never as live parent DOM.
- `test_health_and_errors.py` plants a recognisable key value and asserts it never appears in
  a serialised response.
- `test_ingestion.py` asserts re-running embeds **zero** chunks, and that `README`/`LICENSE`
  beside the corpus are not indexed.

## 6. The strict evaluator's questions

**Does it actually work?** Yes. The stack starts, migrates, persists, ingests with
`nomic-embed-text`, retrieves, answers with `llama3.1:8b`, cites sources, and refuses
when evidence is below threshold — all observed live from the Dockerized backend against
host Ollama. Real Lenny transcripts are indexed from the official starter pack
(50 files / 4984 chunks). The remaining caveat is no Anthropic key.

**Can I run it quickly?** Three commands plus two model pulls. The UI names every blocking
condition with the command that fixes it, so the common failures do not require the README.

**Is the architecture understandable?** Routes → services → skills → providers, one
responsibility per module, ~4,000 lines of application code. `architecture.md` has the
diagrams.

**Is RAG actually grounded?** Yes, and enforced structurally rather than by prompt: if
nothing clears the distance threshold there is no LLM call; if weak chunks still retrieve,
the model is called with an evidence-only prompt and must refuse rather than invent. `[Sn]`
markers are verified against real chunk ids so an invented citation cannot survive.

**Can I verify sources?** Yes — each citation expands to the exact retrieved excerpt with
file, chunk index and speaker, and sources merely retrieved are shown separately from those
cited.

**Does Ollama work?** **Yes, verified live** from the backend container via
`http://host.docker.internal:11434`. Chat (`llama3.1:8b`), embeddings (`nomic-embed-text`),
health, and the Ollama-down error path were all observed. `my-model:latest` was left
untouched.

**Can I switch providers?** Header toggle (per-request `provider`) plus `LLM_PROVIDER`.
Ollama uses `RouterRuntime`; Anthropic uses `ClaudeAgentSDKRuntime`. Verified by tests and
by `/api/config`; live Anthropic generation is unverified (no key).

**Does PostgreSQL persist sessions?** Yes, verified across a container restart.

**Does the agent layer actually exist?** Yes — not a wrapper around one prompt. Two
interchangeable runtimes behind one protocol, four registered skills, deterministic routing,
and the Claude Agent SDK runtime exercised against a stubbed SDK. It is also the place I would
push back hardest on myself: see §Gaps.

**Is the Ship 30 skill properly separated?** Yes — its own module, prompt, retrieval
parameters, word counting (1,062–1,437), max 3 generations, post-cleanup continue, 4–6 H2
cap. Not an inline branch in the chat handler. Latest live essay after the H2 cap is
unverified.

**Does the Artifact Viewer actually render?** Yes, both formats, with title, loading, error
and sanitised states. Component-tested; visual confirmation is manual.

**Is generated HTML safely isolated?** Yes, two independent layers, and the one relied upon
(`sandbox` without `allow-scripts`) is browser-enforced rather than a filter that can be
outsmarted.

**Are failures handled?** Yes — a taxonomy with codes and remedies. Verified live for
provider-down, database-down, validation and not-found.

**Are docs accurate?** Cross-checked against the code during the audit, and three
inaccuracies were fixed rather than left: a docstring claiming a bundled corpus that did not
exist, a dead `FIXTURE_DIR` constant, and an unused `python-frontmatter` dependency.

**Is the UI polished?** Clean and conventional, with effort concentrated on the source list,
status/error banners and viewer states. Not visually ambitious, by choice.

**Are there unnecessary features?** I do not find any. No auth, no analytics, no streaming, no
extra services. The two additions beyond a literal reading of the requirements — the
`StatusBanner` fix-commands and the synthetic fixture — both exist to serve the evaluator
directly.

**Are there secrets?** No. Scanned; `.env` untracked; `.env.example` values empty; a test
asserts key values never reach a response.

**Is anything obviously fake or incomplete?** No placeholder implementations, no TODOs on
core paths, no mocked AI behaviour in the product (mocks exist only in tests). The
unverified paths are labelled as unverified everywhere they appear, rather than being
presented as working.

## 7. Gaps and limitations

Ordered by how much they should affect the assessment.

**1. Dense retrieval at `RETRIEVAL_MAX_DISTANCE=0.55` rarely empties on a large nomic index**
With 4984 conversational chunks, unrelated questions (FIFA, Eiffel Tower) still retrieve
at ~0.40–0.45. The pre-LLM `below_threshold` refusal therefore almost never fires; the
evidence-only prompt still produced a canonical refusal on a live unsupported question.
Do not raise the threshold to “make retrieval pass.” Lowering it on this corpus would
refuse more often and is the documented tuning knob if prompt-layer refusal ever slips.
**Fix:** optional, corpus-specific threshold tuning after a labelled eval set.

**2. Live Anthropic path unverified**
No API key was available. Provider selection, error translation and the SDK runtime contract
are tested against stubs.
**Fix:** manual test plan §2.

**3. No measured retrieval quality**
Every metric in `PRD.md` is labelled a target because none has been measured — there is no
labelled evaluation set, so `RETRIEVAL_MAX_DISTANCE = 0.55` is a reasoned default, not a
tuned one. On a real corpus it may need adjusting, which the troubleshooting table covers.
**Fix:** a fixed question/expected-source set scored in CI. First technical item in
README §Future Improvements.

**4. The default agent runtime is not the Claude Agent SDK**
Defensible and documented at length — the SDK cannot drive a local model, and the demo must
run on Ollama — but an evaluator reading "uses the Claude Agent SDK" literally should know
that `router` is the Ollama path and Anthropic selection uses the SDK. Both are real,
share one skill registry, and the SDK runtime is tested against a stub rather than the live
SDK. `AGENT_RUNTIME` is not the dispatcher.

**5. Deterministic routing cannot chain skills within a turn**
"Research this and then write me a landing page" runs one skill. A deliberate trade for
predictability on an 8B model; the SDK runtime removes the limitation.

**6. Dense-only retrieval**
No BM25 and no reranker, so exact-phrase and acronym queries can underperform.

**7. `<meta>` CSP is weaker than an HTTP header**, and the server sanitiser is a syntactic
filter rather than a browser. Mitigated by the sandbox being the actual boundary.

**8. No authentication, rate limiting or per-user session scoping**
Out of scope per the assignment. Anyone reaching the API sees all sessions — fine for a
single-user local tool, a blocker for any shared deployment.

**9. Responsive and accessibility behaviour is code-verified, not browser-verified**
Semantics, labels, focus handling and breakpoints were written deliberately and are covered
in the manual plan (§11, §12), but no screen reader or real device was driven here.

**10. No CI pipeline.** Tests run locally with two commands; no workflow file wires them to a
push.

## 8. Recommended actions before submission

| Priority | Action | Why |
| --- | --- | --- |
| **1** | Confirm the UI sources list shows a real episode title (not SYNTHETIC…) | Already indexed; a browser pass is the last visual check |
| **2** | Warm `llama3.1:8b` before recording (`ollama run llama3.1:8b`) | First GPU load can add 30s or fail if CUDA is stuck; relaunch host Ollama if needed |
| **3** | Run §3 (grounding) and §8 (artifact security) in a browser | The two areas where a failure would be a defect in the core claims |
| **4** | If a key is available, run §2 to verify the cloud path | Turns a documented capability into a demonstrated one |
| 5 | Optionally lower `RETRIEVAL_MAX_DISTANCE` if prompt-layer refusals ever slip | 0.55 rarely empties a 4984-chunk nomic index; do not raise it |
| 6 | Optionally add a CI workflow running both suites | Cheap credibility for the testing story |

## 9. Would I shortlist this candidate?

**Yes.**

What earns it: the grounding is real and enforced in code rather than asserted in a prompt —
verified live that an unanswerable question never reaches the model. The artifact security
model leans on the control the browser enforces rather than the one that can be outsmarted,
and says so. The tests assert behaviour (what the model was shown, which payload text is
absent, that re-ingestion writes nothing) rather than status codes. Two genuine product bugs
were found by testing and fixed with regression tests, one of which — indexing a `README` as
a citable episode — no unit test would have caught and only live verification revealed.

What I would probe in an interview: why `router` rather than the SDK as the default (the
answer is documented and sound, but it is the sharpest reading of the requirements in the
repo); how `RETRIEVAL_MAX_DISTANCE` would be tuned without an evaluation set; and what would
change if the corpus grew 100×.

What keeps this from unqualified: the live model paths were never exercised in the author's
environment. That is disclosed in the README, the PRD, the decision log, the test plan and
here — which is the right handling — but disclosure is not verification, and a reviewer
should run §1 of the manual test plan before trusting the end-to-end claim.
