# Put transcript files here

This directory is **empty in git on purpose**. The repository does not redistribute
podcast transcripts. Official files belong to Lenny Rachitsky; inventing stand-in
"Lenny transcripts" would produce citations that look real but are not.

## Official source

Use Lenny's public starter pack (personal / non-commercial; do not commit the raw files):

https://github.com/LennysNewsletter/lennys-newsletterpodcastdata

```bash
git clone --depth 1 https://github.com/LennysNewsletter/lennys-newsletterpodcastdata.git
python backend/scripts/import_lennys_data.py --src ./lennys-newsletterpodcastdata
docker compose exec backend python -m scripts.ingest
```

Until you add files and run ingestion, the assistant will honestly decline every question.

You can also drop `.txt` / `.md` / `.vtt` / `.srt` / `.json` files here by hand with YAML
front matter (`title`, `episode`, `guest`, `source_url`). Files in this directory are
git-ignored.

Full guide: [`docs/transcripts.md`](../../docs/transcripts.md).
