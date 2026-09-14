# Manual UI test plan

Covers what automated tests cannot: the live Ollama path, real browser rendering,
keyboard and responsive behaviour, and the honesty of the product's own claims.

**Start here.** §1 is the live local-model path (verified in this environment against
`llama3.1:8b` / `nomic-embed-text`). §2 (Anthropic generation) still needs a key.

**Setup**

```bash
cp .env.example .env
ollama pull llama3.1:8b && ollama pull nomic-embed-text && ollama serve
docker compose up --build
docker compose exec backend python -m scripts.ingest --dir /data/sample-transcripts
```

The synthetic fixture is enough for every test here. For §9 you also want a real corpus in
`data/transcripts/` per [`transcripts.md`](transcripts.md).

Record results as **PASS** / **FAIL** / **BLOCKED**. A test that cannot run is not a pass.

---

## 1. Ollama — the local model path

| # | Steps | Expected |
| --- | --- | --- |
| 1.1 | `curl http://localhost:11434/api/tags` | Both `llama3.1:8b` and `nomic-embed-text` listed |
| 1.2 | Open http://localhost:3000 | Header badge: green dot, **Ollama (local)**, `llama3.1:8b` |
| 1.3 | `curl http://localhost:8000/health` | `ollama.healthy: true`; `status: "ok"` (or `degraded` only because the cloud provider is unconfigured) |
| 1.4 | Re-run ingestion **without** `EMBEDDING_PROVIDER` overridden | Completes with real embeddings; `--status` shows the transcript and chunk count. *This is the real `nomic-embed-text` path* |
| 1.5 | Ask "How should I improve activation?" | Staged progress, then a grounded answer with `[S1]`-style markers, within ~60s |
| 1.6 | Check the message footer | Shows `ollama` and `llama3.1:8b` — the answer really came from the local model |
| 1.7 | Stop Ollama (`Ctrl+C` on `ollama serve`), reload the page | Badge turns red; status banner: "Ollama not reachable" with `ollama serve` as the fix |
| 1.8 | With Ollama stopped, send a message | Structured error banner: title, detail naming the URL tried, remedy, and `provider_unavailable`. No stack trace, no silent hang |
| 1.9 | Restart Ollama, dismiss the error, resend | Succeeds. No restart of the app required |
| 1.10 | `OLLAMA_MODEL=nonexistent:1b`, `docker compose up -d backend`, send a message | `provider_unavailable` whose remedy names `ollama pull`. Restore afterwards |

## 2. Cloud provider and provider switching *(unverified by the author)*

| # | Steps | Expected |
| --- | --- | --- |
| 2.1 | With `ANTHROPIC_API_KEY` empty, `curl /health` | `cloud_provider.healthy: false`, detail says optional. **`/health` still returns 200** |
| 2.2 | Set `LLM_PROVIDER=anthropic`, leave the key empty, restart backend, send a message | `provider_not_configured` with a remedy. Not a crash, not a fallback to Ollama |
| 2.3 | Add a real `ANTHROPIC_API_KEY`, restart backend | Header: **Anthropic (cloud)**, `claude-sonnet-4-5` |
| 2.4 | Ask the same question as 1.5 | Grounded answer with citations; footer shows `anthropic`. Identical UI behaviour |
| 2.5 | `curl /api/config` and search the response for your key | The key **value** appears nowhere. Availability is reported, the secret is not |
| 2.6 | Set `LLM_PROVIDER=ollama` again, restart | Header returns to Ollama. No other change needed anywhere |
| 2.7 | Select **Anthropic (cloud)** in the header with a key configured | Header shows `agent: claude_agent_sdk`; answer still grounded and cited. Live generation **not** claimed without a key |
| 2.8 | Select Anthropic **without** a key | Clear `provider_not_configured` naming the missing key — not an obscure import failure, and **not** a silent Ollama fallback |

## 3. Grounding and citations — the core claim

| # | Steps | Expected |
| --- | --- | --- |
| 3.1 | Ask an activation question (covered by the fixture) | Answer contains `[S1]`-style markers, rendered as accent chips |
| 3.2 | Read the SOURCES block | Header reads e.g. "2 cited of 6 retrieved" |
| 3.3 | Click "Show excerpt" on a cited source | The exact retrieved text appears, with file name, chunk index and speaker |
| 3.4 | Compare the excerpt against the claim it is cited for | The excerpt genuinely supports the claim. **If it does not, that is a FAIL worth reporting** |
| 3.5 | Expand "N more retrieved but not cited" | Additional sources listed — you can see everything the model was given |
| 3.6 | Check a source with no declared URL | Title is plain text, no link, no invented URL. No "Guest:" line if no guest was declared |
| 3.7 | Click a source that has a URL | Opens the episode in a new tab (`rel="noopener noreferrer"`) |
| 3.8 | Ask something the corpus does not cover ("What is the best pricing model for industrial hardware?") | The canonical refusal, styled as a normal message, not an error |
| 3.9 | While 3.8 runs, watch `docker compose logs -f backend` | Either `selected=0` and no provider call (pre-LLM threshold) **or** chunks still selected and the model refuses from evidence. On the 4984-chunk nomic index the second path is common. Do not require `model_ms: 0` |
| 3.10 | Ask a question the corpus covers only partly | Answers the covered part and says plainly what the transcripts do not cover |
| 3.11 | Look for any episode title or guest name in an answer | Every name matches a real indexed transcript. Nothing invented |

## 4. Sessions

| # | Steps | Expected |
| --- | --- | --- |
| 4.1 | Click "+ New chat" | New session appears and becomes active; viewer clears |
| 4.2 | Send a message; look at the sidebar | Title derives from your message; timestamp and message count update |
| 4.3 | Create a second chat, ask about a different topic | Independent history; nothing from chat 1 is visible |
| 4.4 | In chat 2, ask a follow-up that only makes sense in chat 1's context | It does **not** resolve using chat 1. No context leaks |
| 4.5 | Switch back to chat 1 | Full history restores in order, with sources intact |
| 4.6 | Reload the browser | Sessions and messages persist (PostgreSQL, not local state) |
| 4.7 | `docker compose restart backend`, reload | Still persisted |
| 4.8 | Delete a chat | Disappears; if it was active the view clears. Other chats unaffected |
| 4.9 | Order the sidebar by activity: post to an older chat | It moves to the top |

## 5. Follow-up context

| # | Steps | Expected |
| --- | --- | --- |
| 5.1 | "How should I improve activation?" | Grounded answer |
| 5.2 | "What about for B2B SaaS?" | Understood as about activation for B2B; retrieves accordingly |
| 5.3 | Check the sources on 5.2 | Sources are freshly retrieved for the follow-up, not carried over verbatim |
| 5.4 | "Summarise what you just told me" | Summarises the conversation without inventing new cited claims |

## 6. Ship 30 for 30 essay

| # | Steps | Expected |
| --- | --- | --- |
| 6.1 | "Write a Ship 30 for 30 essay about activation" | Progress indicator; essay may take 1–3 minutes on a local model |
| 6.2 | Paste the essay into a word counter | Within ±15% of 1,250 (1,063–1,438) |
| 6.3 | Read the opening | A hook naming a specific tension — not "In today's fast-paced world" |
| 6.4 | Scan the structure | H1 title, H2 sections written as claims, short paragraphs, bullets, sparing bold |
| 6.5 | Check the ending | One specific, actionable takeaway |
| 6.6 | Check citations | Substantive claims carry markers that resolve in the source list |
| 6.7 | Look for statistics or company outcomes | Every one traces to a cited excerpt. **Any invented number is a FAIL** |
| 6.8 | Request an essay on a topic the corpus does not cover | Says transcript evidence was insufficient; does not write a generic essay |
| 6.9 | Check the message metadata footer | Reports actual word count and whether it hit tolerance |

## 7. Artifacts and the viewer

| # | Steps | Expected |
| --- | --- | --- |
| 7.1 | Fresh session — look at the viewer | "Nothing generated yet", explaining how to produce one |
| 7.2 | "Create a landing page for an activation analytics tool" | Spinner, then a rendered page in the viewer. Badge `HTML`, title shown |
| 7.3 | Inspect the rendered page | Real layout and CSS — headings, sections, colours. Not raw markup in a chat bubble |
| 7.4 | Check the chat message | A short summary, **not** a wall of HTML |
| 7.5 | "Create a Markdown strategy document for this" | Badge `MARKDOWN`; rendered headings, lists, bold |
| 7.6 | Use the viewer's own form: select HTML, type an instruction, Generate | Produces an artifact the same way |
| 7.7 | Reload the page with the session active | The latest artifact restores in the viewer |
| 7.8 | Generate a second artifact | Viewer shows the newest |
| 7.9 | Look for a sanitiser note | If shown, it lists exactly what was removed |
| 7.10 | Check for invented specifics in the page | Placeholders like `[your product name]`, not fabricated customer names, logos or testimonials |

## 8. Artifact security — verify, do not take on trust

| # | Steps | Expected |
| --- | --- | --- |
| 8.1 | With an HTML artifact shown, DevTools → Elements, find the `<iframe>` | `sandbox="allow-same-origin"` — **`allow-scripts` absent**. Content is in `srcdoc` |
| 8.2 | Confirm no `allow-forms`, `allow-popups`, `allow-top-navigation` | Absent |
| 8.3 | Search the parent DOM for the artifact's markup outside the iframe | Not present — it is never `innerHTML`'d into the app |
| 8.4 | Ask: "Create an HTML page that includes a script tag alerting hello and a button with an onclick handler" | Page renders; **no alert fires**. DevTools shows no `<script>` and no `onclick` in the frame's document |
| 8.5 | Check the sanitiser note after 8.4 | Reports the removed `<script>` and handler |
| 8.6 | View the frame's document `<head>` | A CSP `<meta>` with `script-src 'none'` |
| 8.7 | Ask for a page with `@import url(https://example.com/x.css)` in its CSS | The `@import` is gone, and no leftover `example.com` text remains in the style block |
| 8.8 | DevTools → Console | No errors from the artifact reaching the parent app |
| 8.9 | Ask for a Markdown doc containing `<script>alert(1)</script>` | Rendered as text or removed; **no alert**, no `<script>` in the DOM |
| 8.10 | Check response headers on http://localhost:3000 | `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` |

## 9. Real transcripts *(needs your own corpus)*

| # | Steps | Expected |
| --- | --- | --- |
| 9.1 | Add 3+ real transcripts with front matter to `data/transcripts/`, ingest | Each indexed; `--status` lists titles, guests and `url: yes` |
| 9.2 | Ask a question you know one episode answers | Grounded answer citing that episode |
| 9.3 | Click through to the source URL | Opens the correct episode |
| 9.4 | Verify the excerpt against the actual transcript file | Text matches exactly; chunk index and speaker are right |
| 9.5 | Ask a question spanning two episodes | Sources from more than one episode (the per-episode cap encourages this) |
| 9.6 | Edit one transcript file, re-ingest | Reports 1 updated, others unchanged; no duplicate chunks |
| 9.7 | Re-ingest with nothing changed | Reports all unchanged; **0 chunks embedded** |
| 9.8 | Drop a deliberately malformed `.json` in and ingest | That file is reported as failed, the others still index, exit code non-zero |
| 9.9 | Confirm the directory's `README.md` was not indexed | It does not appear in `--status` |

## 10. Loading, error and empty states

| # | Steps | Expected |
| --- | --- | --- |
| 10.1 | Send a message and watch closely | "Searching the transcript knowledge base…" then "Generating a grounded answer…", with elapsed seconds after ~2s |
| 10.2 | Fresh app, empty knowledge base (`TRUNCATE transcripts CASCADE`) | Chat empty state shows the ingest command, not example prompts |
| 10.3 | With an empty index, `curl /health` and check the header | `knowledge_base.ready: false`; header shows "no transcripts indexed" |
| 10.4 | `docker compose stop db`, reload | Status banner: "Database unavailable" with `docker compose up -d db`. No white screen |
| 10.5 | With the database down, send a message | Structured `database_unavailable` error, not a crash |
| 10.6 | Restart the database, reload | Recovers without restarting the backend |
| 10.7 | Paste >8,000 characters into the composer | Counter turns red, Send disabled, hint explains why — rejected client-side before a request |
| 10.8 | Press Send with only whitespace | Nothing happens; the button was already disabled |
| 10.9 | Dismiss an error banner | It clears; the app stays usable |
| 10.10 | New chat with no session yet — click an example prompt | Creates a session and sends in one action |

## 11. Keyboard and accessibility

| # | Steps | Expected |
| --- | --- | --- |
| 11.1 | Load the page, press `Tab` once | "Skip to conversation" becomes visible |
| 11.2 | Activate the skip link | Focus moves to the main conversation area |
| 11.3 | `Tab` through the whole app | Every control reachable in a sensible order; focus always visibly outlined |
| 11.4 | Reach a session row's delete button by keyboard only | It becomes visible on focus — not pointer-only |
| 11.5 | In the composer, press `Enter` | Sends |
| 11.6 | Press `Shift+Enter` | Inserts a newline, does not send |
| 11.7 | `Tab` to a "Show excerpt" button and press `Enter`/`Space` | Toggles; `aria-expanded` flips |
| 11.8 | Run a screen reader over a session row | Announced as e.g. "Delete chat: Activation question", not "Delete" |
| 11.9 | Send a message with a screen reader active | Progress is announced politely; errors announced as alerts |
| 11.10 | Zoom the browser to 200% | Layout remains usable; nothing clipped or overlapping |
| 11.11 | OS "reduce motion" enabled, reload | Spinner slows; no smooth-scroll jumps |
| 11.12 | Run Lighthouse or axe on the page | No critical contrast or labelling violations |

## 12. Responsive layout

| # | Width | Expected |
| --- | --- | --- |
| 12.1 | 1440px | Sidebar, chat and viewer side by side |
| 12.2 | 1024px | Chat and viewer stack vertically; both keep a usable minimum height; sidebar remains |
| 12.3 | 768px | Same stacked layout, still comfortable |
| 12.4 | 700px | Sidebar becomes a short scrollable strip above the content; delete buttons permanently visible |
| 12.5 | 375px (iPhone SE) | Everything usable: composer, sources, artifact frame. No horizontal scroll |
| 12.6 | Rotate a tablet portrait ↔ landscape | Layout reflows without losing state |

## 13. Reproducible startup

| # | Steps | Expected |
| --- | --- | --- |
| 13.1 | `docker compose down -v` then `docker compose up --build` on a clean machine | All services healthy; migrations apply automatically |
| 13.2 | Read the backend logs at startup | `Applying database migrations…` → `Migrations applied.` → one JSON `startup` line with provider, model and database status |
| 13.3 | Confirm the startup log contains no secret | `anthropic_api_key` is reported as `missing`/`configured`, never a value |
| 13.4 | `docker compose --profile test run --rm tests` | All tests passed (use the command output; do not rely on an old count) |
| 13.5 | `cd frontend && npm test` | All tests passed (use the command output) |
| 13.6 | `git status` after a full run | No `.env`, no transcripts, no build output staged |
| 13.7 | `git log -p` / `git diff` scan for secrets | None. `.env.example` contains no real values |
| 13.8 | Add a transcript to `data/transcripts/` and ingest **without rebuilding** | Indexes successfully — the directory is a live mount |
| 13.9 | `docker compose down` then `up` (no `-v`) | Sessions and indexed transcripts survive |
| 13.10 | `docker compose down -v` then `up` | Clean slate; migrations re-apply without error |

---

## Result summary

| Section | Result | Notes |
| --- | --- | --- |
| 1. Ollama | PASS | Verified live (`llama3.1:8b` / `nomic-embed-text`); re-run before recording |
| 2. Cloud / switching | | Missing-key path verified (`provider_not_configured`). Live Anthropic generation unverified (no key) |
| 3. Grounding & citations | | |
| 4. Sessions | | |
| 5. Follow-up context | | |
| 6. Ship 30 essay | | |
| 7. Artifacts & viewer | | |
| 8. Artifact security | | |
| 9. Real transcripts | | *needs your own corpus* |
| 10. States | | |
| 11. Accessibility | | |
| 12. Responsive | | |
| 13. Startup | | |

Any **FAIL** in §3 (grounding), §6.7 (invented statistics) or §8 (isolation) is a defect in
the product's core claims and should block acceptance. Failures elsewhere are quality issues.
