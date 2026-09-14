"""Import official Lenny's Data starter-pack transcripts into data/transcripts/.

Source: https://github.com/LennysNewsletter/lennys-newsletterpodcastdata
(Lenny Rachitsky's public free starter pack). Spoken text is copied verbatim.
Speaker lines are rewritten from ``**Name** (00:00:00):`` to ``Name:`` so the
existing chunker can store speaker labels. Metadata is taken only from the
official front matter / index.json — never invented.

Usage:
    python scripts/import_lennys_data.py --src /path/to/lennys-newsletterpodcastdata
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

_SPEAKER_LINE = re.compile(
    r"^\*\*(?P<name>.+?)\*\*\s*(?:\([^)]*\))?\s*:\s*(?P<rest>.*)$"
)


def _parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    if not text.lstrip().startswith("---"):
        return {}, text
    parts = text.lstrip().split("---", 2)
    if len(parts) < 3:
        return {}, text
    metadata: dict[str, str] = {}
    for line in parts[1].strip().split("\n"):
        if ":" not in line or line.strip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        metadata[key.strip().lower()] = value.strip().strip("\"'").replace('\\"', '"')
    return metadata, parts[2].lstrip("\n")


def _convert_speakers(body: str) -> str:
    lines: list[str] = []
    for line in body.splitlines():
        match = _SPEAKER_LINE.match(line.strip())
        if match:
            name = match.group("name").strip()
            rest = match.group("rest").strip()
            lines.append(f"{name}: {rest}".rstrip() if rest else f"{name}:")
        else:
            lines.append(line)
    return "\n".join(lines).strip() + "\n"


def import_podcasts(src: Path, dest: Path) -> int:
    index_path = src / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    by_file = {
        Path(item["filename"]).name: item
        for item in index.get("podcasts", [])
        if isinstance(item, dict) and item.get("filename")
    }

    podcast_dir = src / "podcasts"
    files = sorted(podcast_dir.glob("*.md"))
    if not files:
        raise SystemExit(f"No podcast markdown files in {podcast_dir}")

    dest.mkdir(parents=True, exist_ok=True)
    written = 0
    for path in files:
        raw = path.read_text(encoding="utf-8")
        front, body = _parse_front_matter(raw)
        extra = by_file.get(path.name, {})
        title = front.get("title") or extra.get("title") or path.stem
        guest = front.get("guest") or extra.get("guest")
        episode = front.get("episode") or front.get("date") or extra.get("date")
        source_url = (
            front.get("source_url")
            or front.get("url")
            or front.get("post_url")
            or extra.get("post_url")
            or front.get("youtube_url")
            or extra.get("youtube_url")
        )
        converted = _convert_speakers(body)
        if not converted.strip():
            print(f"skip empty: {path.name}")
            continue

        lines = ["---", f"title: {json.dumps(title, ensure_ascii=False)}"]
        if episode:
            lines.append(f"episode: {json.dumps(str(episode), ensure_ascii=False)}")
        if guest:
            lines.append(f"guest: {json.dumps(guest, ensure_ascii=False)}")
        if source_url:
            lines.append(f"source_url: {json.dumps(source_url, ensure_ascii=False)}")
        lines.extend(["---", "", converted])
        (dest / path.name).write_text("\n".join(lines), encoding="utf-8")
        written += 1
        print(f"wrote {path.name}")
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Import official Lenny's Data podcast transcripts.")
    parser.add_argument("--src", required=True, help="Clone of LennysNewsletter/lennys-newsletterpodcastdata")
    parser.add_argument(
        "--dest",
        default=str(Path(__file__).resolve().parents[2] / "data" / "transcripts"),
        help="Destination directory (default: data/transcripts)",
    )
    args = parser.parse_args()
    count = import_podcasts(Path(args.src), Path(args.dest))
    print(f"\nImported {count} official podcast transcript(s) into {args.dest}")
    print("Raw files stay git-ignored. Then: docker compose exec backend python -m scripts.ingest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
