# Coding-agent transcripts

This project was built with Cursor's coding agent. This directory holds the development
record the assignment asks for.

| File | What it is |
| --- | --- |
| [`decision-log.md`](decision-log.md) | The substantive record: decisions, failed attempts, real bugs found and how they were fixed, and trade-offs — written from the actual session |
| [`capturing-transcripts.md`](capturing-transcripts.md) | How to export the raw conversation log, and how to scrub it before sharing |

## Why the raw log is not committed

Cursor writes the full conversation to a machine-local path outside the repository:

```
%USERPROFILE%\.cursor\projects\<project-slug>\agent-transcripts\<session-id>\<session-id>.jsonl
```

It is not committed here for three reasons:

1. **It contains local absolute paths** and machine details that identify the development
   environment.
2. **It is large and low-signal** — many megabytes of tool calls, file reads and diffs. The
   decisions an engineer would actually want are in `decision-log.md`.
3. **It has not been mechanically scrubbed.** No API key was ever entered in this session
   (the Anthropic path was left unconfigured, which is itself recorded in the log), but
   committing an unscrubbed transcript on that assumption would be careless.

[`capturing-transcripts.md`](capturing-transcripts.md) documents the exact export and
scrub procedure, so the raw log can be produced on request.

## What is *not* in here

No invented history. `decision-log.md` records what actually happened in the build session,
including the mistakes and the two real product bugs found while testing. Live Ollama
generation against the official corpus **has** since been verified. The live Anthropic
path has not (no API key).
