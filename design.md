# Design

UI and interaction design for The Lenny Growth Assistant. Technical structure is in
[`architecture.md`](architecture.md); product intent in [`PRD.md`](PRD.md).

---

## Design principles

**1. The receipts are the product.** Anyone can render a chat bubble. The reason to trust
this tool is that every claim traces to a specific transcript excerpt you can read. So
sources are part of the answer's own layout — not a modal, not a footnote, not a separate
tab.

**2. A refusal is a good answer.** "I couldn't find enough relevant information" is the
system working. It is styled as a normal message with a quiet explanatory note, never as an
error. Styling it red would train the user to read honesty as malfunction.

**3. Make the machine's state legible.** The active provider, the model name and the indexed
chunk count are always on screen. When something is misconfigured, the UI names the problem
*and the command that fixes it*. An evaluator should never have to read server logs to
understand what the app is doing.

**4. Restraint over decoration.** One accent colour, one type scale, one spinner. Every
visual element carries information. The product is a professional tool; it should look like
one, and it should be obvious within five seconds what it does.

**5. Honest waiting.** A local 8B model takes 30–60 seconds. Hiding that behind an
indeterminate spinner feels broken. Named stages plus elapsed seconds make a slow response
legibly slow rather than ambiguously stuck.

## Information architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│ HEADER   The Lenny Growth Assistant            ● Ollama (local)        │
│          grounded in podcast transcripts         llama3.1:8b           │
│                                                agent: router · 312 chunks│
├────────────────────────────────────────────────────────────────────────┤
│ STATUS   ⚠ No transcripts indexed  → docker compose exec backend …     │  (conditional)
├──────────────┬─────────────────────────────────────────────────────────┤
│  SIDEBAR     │  CHAT                    │  ARTIFACT VIEWER             │
│              │                          │                              │
│  + New chat  │  ┌────────────────────┐  │  Artifact Viewer             │
│              │  │ You                │  │  [HTML] Activation Landing…  │
│  CHATS       │  │ How do I improve…  │  │  ┌────────────────────────┐  │
│  ▸ Activation│  └────────────────────┘  │  │                        │  │
│    14:32 · 6 │  ┌────────────────────┐  │  │   sandboxed iframe     │  │
│  ▸ Pricing   │  │ Assistant          │  │  │   (no scripting)       │  │
│    Sep 12    │  │ Answer text [S1]…  │  │  │                        │  │
│              │  │ ── SOURCES ────    │  │  └────────────────────────┘  │
│              │  │ S1 Episode title   │  │                              │
│              │  │    Show excerpt    │  ├──────────────────────────────┤
│              │  └────────────────────┘  │  [HTML ▾] [instruction…] [Gen]│
│              ├──────────────────────────┤                              │
│              │  [textarea         ] [Send]                             │
└──────────────┴──────────────────────────┴──────────────────────────────┘
```

Three columns, one job each: **navigate** (sidebar), **converse** (chat), **inspect the
deliverable** (viewer). Nothing important is more than one click away, and there is no
navigation state to get lost in — no routes, no tabs, no modals.

## Layout

Desktop is a `flex` column (header, optional status banner, body) with a `flex` body
(sidebar + main) and a two-column CSS `grid` main area. The chat gets slightly more width
(`1.05fr` vs `1fr`) because prose needs it more than a preview does.

Only the message list and the viewer body scroll. The header, composer and generation form
stay fixed, so the two things you interact with most are always where you left them.

## Navigation

There is deliberately no router. The app has one screen; the only navigational state is
"which session is active", held in a hook and reflected by `aria-current` on the active
sidebar item. Adding routes would mean URL state, history handling and deep-link edge cases
in exchange for nothing a user of a single-screen tool would notice.

Sessions are ordered by most recent activity, so the chat you were just in is at the top.
Each row shows a title derived from the first message plus a relative timestamp (time today,
date otherwise) and a message count.

## Chat interaction

**Sending.** `Enter` sends, `Shift+Enter` inserts a newline — the convention every chat
interface uses. The send button is disabled until there is non-whitespace input, so it is
never ambiguous whether a click will do anything.

**Optimistic echo.** The user's message appears immediately; it is already persisted
server-side by the time the request returns. On failure it *stays* — nobody should have to
retype a paragraph because the model timed out.

**User vs assistant.** User messages are tinted and inset from the left; assistant messages
are on white, full width, with rendered Markdown. The asymmetry does the work that avatars
usually do, without the clutter.

**Citation markers.** `[S1]` in answer text is rendered as a small monospace chip in the
accent colour, tying it visually to the `S1` badge in the source list below. It is
deliberately *not* a link: a link implies navigation, and the target is already on screen a
few hundred pixels down.

**Metadata footer.** Provider, model and per-stage timings sit in a small monospace row
under each assistant message. Most users will ignore it; an evaluator checking that a claim
came from the local model will not have to guess.

## Session interaction

"+ New chat" is the only primary-coloured button in the sidebar, because it is the only
action there worth emphasising. Creating a session switches to it and clears the viewer.

Delete is a `×` that appears on row hover — and on keyboard focus, so it is reachable
without a pointer. Its accessible name is `Delete chat: {title}`, not "Delete", so a screen
reader user knows which chat they are about to remove.

Switching sessions loads that session's history and its latest artifact. Because a slow
response from a previous session could otherwise arrive after the switch, `useChat` records
the session each request was issued for and discards late replies — a correctness detail the
user should never perceive.

## Source display

This is the most carefully designed part of the UI, because it is where trust is earned.

```
── SOURCES ──────────────── 2 cited of 6 retrieved ──
┌──────────────────────────────────────────────────┐
│ S1  How to improve activation                     │  ← links to the episode when a
│     Episode 142 · Guest: A Guest · match 0.82     │    source_url was declared
│     Show excerpt                                  │
│     ┌──────────────────────────────────────────┐  │
│     │ "The single biggest activation lever…"    │  │  ← the EXACT text retrieved
│     │ episode-142.txt · chunk 3 · Guest         │  │
│     └──────────────────────────────────────────┘  │
└──────────────────────────────────────────────────┘
▸ 4 more retrieved but not cited
```

Four decisions here:

**Cited and merely-retrieved are separated.** Sources the answer actually referenced are
shown; the rest collapse behind "4 more retrieved but not cited". A reviewer can see
*everything the model was given*, not just what it quoted — which is what makes it possible
to judge whether an answer used its evidence well.

**Excerpts are collapsed by default.** Six open excerpts would bury the answer. One click
reveals the exact retrieved text, with file name, chunk index and speaker — enough to find
it in the source file.

**Absent metadata is omitted, never filled in.** No guest line if the transcript declared no
guest; plain text instead of a link if there was no URL. A plausible-looking wrong citation
is worse than a missing field, so the UI would rather show less.

**Relevance is shown as "match 0.82".** Cosine distance inverted, because "lower is better"
is a needless puzzle for a reader. The tooltip explains what it is.

## Artifact Viewer

Always present, so the panel's existence is discoverable before anything has been generated
— an empty viewer that explains itself teaches the feature better than a panel that appears
from nowhere.

Four states:

| State | What is shown |
| --- | --- |
| Empty | "Nothing generated yet", plus the two phrasings that produce an artifact |
| Loading | Spinner and "Generating artifact…" in a `role="status"` region |
| Rendered | Format badge (`HTML`/`MARKDOWN`), title, and the artifact itself |
| Sanitised | A collapsible note above the render listing exactly what was stripped |

HTML renders in a sandboxed iframe **without** `allow-scripts`; Markdown renders through
`marked` + DOMPurify. The frame's accessible title names the artifact
(`Rendered artifact: Activation Landing Page`) rather than being a generic "preview".

The generation form at the bottom (format select + instruction + Generate) exists because
discovering that a chat message can produce an artifact requires knowing the magic phrasing.
The form makes the capability visible and gives explicit control over format.

Showing the sanitiser report is a deliberate product decision, not a debug leftover:
silently altering someone's document is worse than telling them what changed, and it makes
the security model observable rather than a documentation claim.

## Loading states

| Where | Treatment |
| --- | --- |
| Config/health | No blocking spinner; the header fills in when data arrives |
| Session list | "Loading…" in the sidebar |
| History | "Loading conversation…" in the message area |
| Chat turn | Staged: "Searching the transcript knowledge base…" → "Generating a grounded answer…", plus elapsed seconds after 2s |
| Artifact | Spinner + "Generating artifact…" in the viewer |

The staged progress mirrors what the backend is actually doing — retrieval is fast, so
anything past ~2s is generation. This is honest signalling, not a fake progress bar: with a
30–60s local model, "it is on the second of two steps and has been 24 seconds" is the
difference between waiting and reloading.

All live regions use `role="status"` with `aria-live="polite"`, so progress is announced
without interrupting.

## Empty states

**No session / no messages.** A short explanation of what the product does and what makes it
different ("answers come only from indexed transcripts, with citations you can check"), then
three clickable example prompts covering the three capabilities — a question, an essay, an
artifact. This is the primary discovery surface for the Ship 30 and artifact features.

**Knowledge base empty.** The examples are replaced by a callout: transcripts are missing,
here is where they go, here is the command, here is the doc. Offering example prompts that
would all be declined would be a worse first experience than explaining the gap.

**No artifact yet.** Explained above.

**No sessions.** "No chats yet. Start one above."

## Error states

Errors are shown where the failure happened — session errors above the body, chat errors
inline in the conversation — so the failing thing and its explanation are adjacent.

Each `ErrorBanner` carries four things:

```
┌──────────────────────────────────────────────────────────┐
│ The local model is not reachable                Dismiss  │  ← what broke, in plain words
│ Ollama is not reachable at http://…:11434.               │  ← the specific detail
│ Start Ollama with `ollama serve`, then retry.            │  ← what to do about it
│ Error code: provider_unavailable                         │  ← the searchable handle
└──────────────────────────────────────────────────────────┘
```

The title is mapped from the backend's stable error code, so it is human, while the code
stays visible for searching docs or logs. The **remedy** comes from the backend rather than
being guessed by the frontend, because the server knows which URL it tried and which model
was missing.

The `StatusBanner` is the proactive counterpart: it surfaces database-down, Ollama-down,
provider-unconfigured and empty-index *before* the user hits them, each with its fix
command. Together they mean a misconfigured environment is diagnosable from the browser
alone.

A refusal is **not** an error state. It renders as a normal assistant message with a quiet
note explaining that the transcripts did not cover the question.

## Responsive behaviour

| Breakpoint | Layout |
| --- | --- |
| > 1024px | Sidebar + chat and viewer side by side |
| ≤ 1024px | Sidebar retained; chat and viewer stack vertically, each with a minimum height so neither collapses |
| ≤ 720px | Sidebar becomes a short scrollable strip above the content; delete buttons become permanently visible since hover does not exist on touch |

Everything is plain CSS grid/flex with three breakpoints. No component library, no JS-driven
layout. The `1024px` breakpoint stacks rather than hides the viewer: an artifact you cannot
see is the feature not working.

## Accessibility

Built in, not retrofitted, and kept proportionate — no accessibility framework:

- **Semantic landmarks:** `header`, `nav`, `main`, `section`, `article`, `form`, with
  `aria-label` where several regions share a role.
- **Skip link** to the conversation, visible on focus.
- **Visible focus everywhere:** one `:focus-visible` outline rule, never removed.
- **Keyboard reachable:** every action is a real `<button>`; the row-hover delete is also
  revealed by `:focus-visible`, so it is not pointer-only.
- **Labelled inputs:** the composer and artifact instruction have real `<label>`s
  (visually hidden where a visible label would be redundant); the composer uses
  `aria-describedby` for its hint and `aria-invalid` when over the limit.
- **Announcements:** loading and progress in `role="status"` / `aria-live="polite"`;
  errors in `role="alert"`.
- **Meaningful names:** `Delete chat: {title}`, `Rendered artifact: {title}` — never
  "Delete" or "Click here".
- **State conveyed non-visually:** `aria-current` on the active session, `aria-expanded` on
  excerpt toggles.
- **Contrast:** body text `#16191d` on `#fff`; the lightest muted text (`#7a838d`) is used
  only for secondary metadata and still clears 4.5:1.
- **Colour is never the only signal:** the provider dot pairs with text; the sanitiser note
  pairs with a heading.
- **`prefers-reduced-motion`** slows the one spinner and disables smooth scrolling.

## Key UI decisions

**Provider indicator in the header, permanently.** The assignment requires the active model
to be obvious. A badge with a health dot, provider name and model does that in one glance,
and turning red on failure makes the most common problem self-diagnosing.

**Fix commands in the UI.** Unusual for a product; correct for this one. The primary user is
an evaluator on a fresh clone, and their most likely failure is environmental. Printing
`docker compose exec backend python -m scripts.ingest` where the problem appears removes a
round trip through the README.

**Sanitiser report surfaced, not hidden.** Turns a documentation claim into an observable
behaviour.

**Elapsed seconds during generation.** Cheap, and it converts "is this broken?" into "this
is slow", which is the truth.

**No streaming.** Citation markers must be verified against retrieved chunks before display,
which needs the complete response. Staged progress was chosen over streaming plus a
correction pass.

**Cited/uncited split in sources.** The single most reviewer-facing decision in the UI: it
shows the whole evidence set, so the answer can be judged rather than trusted.

## Why the UI is intentionally simple

An evaluator has limited time and will judge whether the *hard* parts — grounding,
citations, artifact isolation, failure handling — are real. Every hour spent on a component
library, animations or a settings screen is an hour not spent on those, and it adds surface
that can be wrong.

So the interface is deliberately conventional: a familiar three-pane layout, one accent
colour, no novel interactions to learn. The only places it spends design effort are the ones
that carry the product's actual argument — the source list, the status/error banners, and
the artifact viewer's security-visible states.

Plain CSS with custom properties (~700 lines across four files, no Tailwind, no component
library) keeps the dependency list short and every style directly readable. At this size,
a utility framework would add a build concern and a mental translation step without
reducing the work.
