# Transcript knowledge base

The assistant answers **only** from transcripts indexed in this repository's database. It
ships with **no transcript content**, so a fresh clone will decline every question until
you ingest a corpus. That is deliberate: podcast transcripts are the podcast's content,
not ours to redistribute, and fabricating stand-in "Lenny transcripts" would produce
citations that look real and are not.

This document is the complete operator guide: where files go, what formats work, how
metadata is preserved, how to run ingestion, and how re-ingestion handles changes.

---

## 1. Where transcript files go

```
data/transcripts/
├── how-to-improve-activation.txt
├── growth-loops-with-a-guest.md
├── episode-142.vtt
├── batch-export.json
└── metadata.json          # optional sidecar
```

`data/transcripts/` is mounted into the backend container read-only, so **adding a file
needs no image rebuild** — drop it in and re-run ingestion.

Subdirectories are searched recursively, so `data/transcripts/2024/episode-1.txt` works.

### Getting a corpus

The intended public source is **Lenny's Data**, released by Lenny Rachitsky:

- Repository: https://github.com/LennysNewsletter/lennys-newsletterpodcastdata
- License: personal, non-commercial use; **do not commit or redistribute the raw files**
- Contents: 50 official podcast transcripts (markdown) in `podcasts/`, plus `index.json` metadata

```bash
git clone --depth 1 https://github.com/LennysNewsletter/lennys-newsletterpodcastdata.git
python backend/scripts/import_lennys_data.py --src ./lennys-newsletterpodcastdata
docker compose exec backend python -m scripts.ingest
```

The importer copies spoken text verbatim, maps official title / guest / date / URL into
the front matter this pipeline reads, and rewrites ``**Speaker** (00:00:00):`` labels to
``Speaker:`` so existing chunking can store speaker names. It does not invent episodes,
guests, or URLs.

Paid subscribers can use the full archive from [lennysdata.com](https://www.lennysdata.com)
the same way. Episode pages on [lennysnewsletter.com](https://www.lennysnewsletter.com) also
publish transcripts if you prefer to save them by hand.

The directory is git-ignored (except `.gitkeep` and this repo's docs), so your corpus is
never committed.

---

## 2. Supported formats

| Extension | Handling |
| --- | --- |
| `.txt`, `.md` | Plain transcript text, optional YAML front matter (§3) |
| `.vtt`, `.srt` | Subtitle exports; cue numbers, timestamps and `WEBVTT` headers are stripped during cleaning |
| `.json` | One object, or an array of objects, with the transcript in `transcript`, `text` or `content` |

Anything else in the directory is ignored rather than treated as an error, so a stray
`.pdf` or `.mp3` will not fail the run.

### Speaker labels

Lines of the form `Speaker Name: text…` are recognised as speaker turns. Chunk boundaries
prefer turn boundaries, and the speaker is stored per chunk and shown with the excerpt in
the UI. Transcripts without speaker labels ingest fine — they are chunked on paragraph and
sentence boundaries instead, and the speaker field stays empty.

---

## 3. Metadata: read, never invented

Metadata is only ever read from what you supply. Any field you do not declare stays empty
and the UI omits it. **The pipeline never guesses an episode number, guest name or URL**,
because a plausible-looking wrong citation is worse than a missing one.

Recognised fields: `title`, `episode`, `guest`, `source_url` (or `url`).

### Option A — YAML front matter (recommended)

Put it at the top of a `.txt` or `.md` file:

```markdown
---
title: How to improve activation
episode: "142"
guest: A Guest Name
source_url: https://www.lennysnewsletter.com/p/some-episode
---

Lenny: Welcome to the show. Let's start with activation…

A Guest Name: The biggest lever we found was time to first value…
```

Flat `key: value` pairs only — no nested YAML. Quotes are optional and stripped.

### Option B — `metadata.json` sidecar

Better when you have dropped in a batch of plain text files and would rather not edit each
one. Keys are file paths relative to `data/transcripts/` (or bare filenames):

```json
{
  "how-to-improve-activation.txt": {
    "title": "How to improve activation",
    "episode": "142",
    "guest": "A Guest Name",
    "source_url": "https://www.lennysnewsletter.com/p/some-episode"
  },
  "2024/growth-loops.txt": {
    "title": "Growth loops that compound",
    "source_url": "https://example.com/growth-loops"
  }
}
```

### Option C — inline in JSON

```json
[
  {
    "title": "How to improve activation",
    "episode": "142",
    "guest": "A Guest Name",
    "source_url": "https://www.lennysnewsletter.com/p/some-episode",
    "transcript": "Lenny: Welcome to the show…"
  }
]
```

An array indexes several episodes from one file; each entry is tracked separately as
`batch.json#0`, `batch.json#1`, … so re-ingestion stays per-episode.

### Precedence

Front matter wins over the sidecar, which wins over the filename-derived title. So a file
named `how-to-improve-activation.txt` with no declared metadata still gets the readable
title "How To Improve Activation" rather than a raw filename.

Transcripts with no `source_url` are logged at ingestion
(`transcript_metadata_incomplete`) and cite by file name only. Everything works; the
citation is just less useful, because it cannot link back to the episode.

---

## 4. Running ingestion

Ollama must be running with the embedding model pulled, since embeddings are generated
locally:

```bash
ollama pull nomic-embed-text
```

**With Docker (normal path):**

```bash
docker compose exec backend python -m scripts.ingest
```

**Without Docker,** from `backend/` with the virtualenv active:

```bash
python -m scripts.ingest
```

Useful flags:

| Command | Effect |
| --- | --- |
| `python -m scripts.ingest` | Index new and changed transcripts |
| `python -m scripts.ingest --status` | Report what is currently indexed; changes nothing |
| `python -m scripts.ingest --force` | Re-chunk and re-embed everything, ignoring hashes |
| `python -m scripts.ingest --dir /some/path` | Ingest from a different directory |

The command logs one line per file and prints a summary of transcripts added, updated,
unchanged and failed. **A file that fails does not abort the run** — the rest still index,
and the failure is reported with its reason at the end. Exit code is non-zero if anything
failed, so it is usable in a script.

---

## 5. What ingestion actually does

```
data/transcripts/*
      |
      v
  load + read metadata          loader.py       (never infers missing fields)
      |
      v
  clean / normalise             chunking.py     (strip subtitle cues, collapse whitespace)
      |
      v
  split into speaker turns      chunking.py     (keeps character offsets into the source)
      |
      v
  pack into overlapping chunks  chunking.py     (~1200 chars, ~150 char overlap)
      |
      v
  embed each chunk              embeddings.py   (Ollama nomic-embed-text, 768-dim)
      |
      v
  store chunk + vector + source transcripts / transcript_chunks tables
```

Each stored chunk keeps its transcript title, episode, guest, source URL, source file,
chunk index, speaker, and start/end character offsets into the cleaned text. That is what
makes a citation traceable: the excerpt shown in the UI is the exact text that was
retrieved and put in front of the model, and the offsets locate it in the original file.

Chunks overlap so a claim spanning a boundary survives in at least one chunk intact.

---

## 6. Adding, updating and removing transcripts

Ingestion is **idempotent**, keyed on the SHA-256 hash of each file's transcript text.

| You do this | Ingestion does this |
| --- | --- |
| Add a new file | Chunks and embeds it; existing transcripts untouched |
| Re-run with nothing changed | Skips everything; reports "unchanged". No duplicate rows, no re-embedding |
| Edit an existing file | Hash differs → deletes that transcript's old chunks and re-indexes it. Other transcripts untouched |
| Rename a file | Treated as a new transcript. Delete the old one (§below) or use `--force` after clearing |
| Delete a file | **Its chunks stay indexed.** Ingestion never deletes on absence, so a mistyped `--dir` cannot silently wipe your index |

To remove a transcript that no longer exists on disk, drop it explicitly:

```bash
docker compose exec db psql -U lenny -d lenny \
  -c "DELETE FROM transcripts WHERE source_file = 'old-episode.txt';"
```

Chunks cascade-delete with the transcript.

To rebuild from scratch:

```bash
docker compose exec db psql -U lenny -d lenny -c "TRUNCATE transcripts CASCADE;"
docker compose exec backend python -m scripts.ingest
```

### Changing the embedding model

`EMBEDDING_MODEL` and `EMBEDDING_DIMENSIONS` must match the model's real output
dimensionality, and **every chunk must be re-embedded** with the same model that embeds
queries — vectors from different models are not comparable. After changing it, truncate
and re-ingest as above. Changing dimensions also requires a migration, since the vector
column is fixed-width.

---

## 7. Verifying the index

```bash
curl -s http://localhost:8000/health | python -m json.tool
```

The `knowledge_base` block reports transcript count, chunk count, embedding model and a
`ready` flag. The UI shows the same thing in the header, and displays a banner with the
ingestion command while the index is empty.

If retrieval finds nothing relevant, the assistant says so rather than answering from the
model's general knowledge. An empty index is therefore not a crash — it is an assistant
that honestly declines everything. `--status` and `/health` are how you tell the two
apart.
