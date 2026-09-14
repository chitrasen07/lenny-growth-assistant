# Demo script — 2–3 minutes

**Camera on** (required by the assignment). Screen shared, one browser window.

The one thing to land: **this assistant answers only from the transcripts, shows you the
receipts, and refuses when it can't.** Everything else is supporting detail.

---

## Before recording

```bash
ollama serve                      # confirm: curl http://localhost:11434/api/tags
docker compose up -d
docker compose exec backend python -m scripts.ingest --status   # expect real transcripts
```

Checklist:

- [ ] Real transcripts indexed, not the synthetic fixture — a demo that cites
      "SYNTHETIC VERIFICATION FIXTURE" undercuts the whole point.
      (`DELETE FROM transcripts WHERE source_file LIKE '%synthetic%';` then ingest yours.)
- [ ] **Warm the model** — `ollama run llama3.1:8b` and ask it anything once. A cold model
      loading into memory can add 30s to your first answer on camera.
- [ ] Header shows a green dot, `Ollama (local)`, the model, `agent: router`, and a chunk count.
- [ ] Two chats already created and used, so the sidebar isn't empty.
- [ ] One rehearsal run so you know your corpus's actual answers and timings.
- [ ] Pick your questions from **your** corpus: one it covers well, one it clearly doesn't.
- [ ] Browser zoom ~110%, DevTools closed but ready (`F12`) for the security beat.
- [ ] Notifications off.

**Timing reality:** a local 8B model takes 30–60s per answer, and the essay 1–3 minutes.
That does not fit in three minutes of real time. **Pre-generate the essay and the artifact in
a session you switch to**, and say so plainly: "I generated this one earlier — it takes about
two minutes on a local model." Honest and fast beats waiting on camera.

---

## Script

### 0:00–0:20 — Problem and product

> "Lenny's Podcast has hundreds of hours of specific operating advice — how real teams fixed
> activation, priced a product, found a growth loop. It's unsearchable. And if you ask a
> general chatbot, it'll happily attribute advice to guests who never said it.
>
> This is the Lenny Growth Assistant. It answers **only** from indexed transcripts, shows the
> exact excerpt behind every claim, and tells you when it doesn't know."

*On screen: the app, header visible.*

### 0:20–0:35 — What's running

> "Everything's local — that's Ollama with llama3.1:8b in the header, and the embeddings are
> local too, so there's no cloud account anywhere. Postgres with pgvector holds the
> transcripts and the chat history. It's one `docker compose up`."

*Point at the provider badge and the chunk count.*

### 0:35–1:05 — Grounded answer with sources *(the core beat)*

*Click "+ New chat". Type your well-covered question. Send.*

> "Retrieval runs first, then generation — you can see which stage it's on."

*Answer appears.*

> "Note the markers in the text. Those aren't decoration."

*Scroll to SOURCES.*

> "Two cited of six retrieved. And I can open the actual excerpt —"

*Click "Show excerpt".*

> "— that's the exact transcript text the model was given, with the episode, the guest, the
> file and the chunk. I can check the claim myself. It also shows the four sources it
> retrieved but *didn't* cite, so you can see everything it had to work with."

### 1:05–1:20 — Follow-up

*Type: "What about for B2B SaaS?"*

> "It understands that's still about activation from the conversation — but the grounding is
> re-retrieved for the new question. Context shapes what it searches for; it never becomes
> the evidence."

### 1:20–1:40 — The refusal *(don't skip this)*

*Type a question your corpus clearly does not cover.*

> "And this is the part I'd actually point at. The assistant refuses when the retrieved
> Lenny corpus does not provide sufficient support, and it does not invent outside facts —
> no astronaut names, no Wikipedia. There are two refusal paths: if nothing clears the
> relevance threshold, generation is skipped; if weak neighbours still retrieve, the model
> is called with an evidence-only prompt and still has to decline. Do not say 'the model
> was never called' unless the logs show `selected=0` / `model_ms: 0`."

### 1:40–2:05 — Ship 30 essay

*Switch to your pre-generated essay session.*

> "There's a dedicated Ship 30 for 30 skill — separate from Q&A, with its own broader
> retrieval and its own style rules. I generated this earlier because it takes a couple of
> minutes locally."

*Scroll through it.*

> "About 1,250 words — the skill targets 1,062–1,437, counts after citation cleanup, and
> can continue up to three generations if the cleaned draft is short. Hook, 4–6 H2 sections,
> skimmable, and the substantive claims still carry citations. It won't write one if the
> transcripts don't support the topic. Generate this before recording and only show a draft
> that actually lands in range."

### 2:05–2:35 — Artifact and its isolation

*Switch to your pre-generated artifact session.*

> "Same conversation, different output: 'create a landing page for this idea' produces a
> complete HTML and CSS page, rendered right here."

*Then the security beat — open DevTools, select the iframe.*

> "This is generated HTML, so I treat it as untrusted. It's sanitised server-side against an
> allowlist, and then rendered in a sandboxed iframe **without** `allow-scripts` — so the
> browser refuses to execute any script in it, even if my sanitiser missed something. It's in
> `srcdoc`, never `innerHTML`, so it can't touch the app. When something gets stripped, the
> viewer tells you what."

### 2:35–3:00 — The trade-off, and close

> "One trade-off worth naming. On Ollama the agent uses deterministic routing — one turn
> picks one skill — rather than letting the model choose tools autonomously. On an 8B local
> model, tool-call JSON is unreliable and every round trip costs 10 to 20 seconds, so
> autonomy would have made the demo path slow and flaky. Selecting Anthropic in the header
> uses the Claude Agent SDK instead: same skills as MCP tools, Claude chooses among them.
> That path is cloud-only, so it cannot be the Ollama demo. Predictability and local
> reproducibility over agent autonomy. It's all documented."

---

## If you have 30 seconds more

- Stop Ollama and reload: the badge turns red and the banner names `ollama serve` as the fix.
  A strong beat — it shows failures are handled, not hidden.
- `docker compose logs backend | grep retrieval_completed`: `candidates` vs `selected` with
  the distances, which is how you'd debug a refusal.

## Cut first if you're over

1. §0:20–0:35 (what's running) — the header shows it anyway.
2. The follow-up beat.
3. Shorten the essay beat to one sentence and a scroll.

Never cut: the source excerpt (1:05), the refusal (1:20), the sandbox (2:05). Those are the
demo.

## Common on-camera problems

| Problem | Do this |
| --- | --- |
| First answer is very slow | You forgot to warm the model. Talk over it, or cut and rerun |
| Answer has no citations | Small model dropped them. Reroll, or note it honestly — metadata flags uncited answers |
| Your "uncovered" question gets answered | Your corpus covers more than you thought. Have a second, clearly-out-of-domain question ready |
| Artifact renders blank | Regenerate; mention the sanitiser report if one appears |
| Ollama drops mid-demo | Use it — reload and show the error handling, then restart |
