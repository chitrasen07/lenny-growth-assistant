# Synthetic verification fixture — NOT real podcast content

This directory contains **one synthetic file that I wrote**. It is not a Lenny's Podcast
transcript, it is not a transcript of anything, and it contains no real quotations. The
speakers are named "Host" and "Fixture Speaker" and its `source_url` is
`https://example.invalid/...` precisely so it can never be mistaken for a real citation.

## Why it exists

It lets you verify that the whole stack works — ingestion, chunking, embedding, vector
retrieval, grounded answering with citations, the Ship 30 essay skill and artifact
generation — **before** you have sourced a real transcript corpus. Without any indexed
content the assistant correctly refuses every question, which is right but makes it hard to
tell "working and honest" apart from "broken".

It is deliberately **not** in `data/transcripts/`, so it is never ingested by accident.

## Using it

```bash
# Index the fixture only
docker compose exec backend python -m scripts.ingest --dir /data/sample-transcripts
```

For that path to exist in the container, add the mount to the `backend` service in
`docker-compose.yml`:

```yaml
    volumes:
      - ./data/transcripts:/data/transcripts:ro
      - ./data/sample-transcripts:/data/sample-transcripts:ro   # already present
```

Then ask the assistant something the fixture covers, e.g. *"How should I think about
improving activation?"* — you should get a grounded answer citing
"SYNTHETIC VERIFICATION FIXTURE - Activation and onboarding".

Ask about something it does **not** cover, e.g. *"What is the best pricing model for
hardware?"* — you should get an honest refusal. Both behaviours are the point.

## Before a real demo

Remove it, so nothing in the demo cites synthetic content:

```bash
docker compose exec db psql -U lenny -d lenny \
  -c "DELETE FROM transcripts WHERE source_file LIKE '%synthetic%';"
```

Then ingest your real corpus per [`docs/transcripts.md`](../../docs/transcripts.md).
