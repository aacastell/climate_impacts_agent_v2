"""Fetches raw candidate RAG source documents — the same fetch/process separation ADR-006 already
established for ISIMIP data, applied to a new data type. This is a raw fetch only: it streams
whatever the public URL serves into S3 under raw/corpus/, real, unmodified. It does not curate,
excerpt, embed, or decide what belongs in services/narration/corpus.py — that stays a human
review/curation step (see services/narration/CORPUS_SOURCES_CANDIDATES.md), same as this project's
standing rule against fabricating corpus content.

Honest limitation, not hidden: some of these sources are paywalled (Nature, some ScienceDirect/
Springer pages). This fetches whatever the public URL actually returns — full text for open-access
sources (PMC, Frontiers, NASA, PNAS open content), likely only an abstract/paywall notice for
restricted ones. No workaround attempted; that's a real constraint on what's fetchable, not a bug.

Sources list lives in CORPUS_SOURCES.json, one entry per candidate found via real web search (see
docs/overnight-2026-08-25.md) — not fabricated, not yet curated into the actual retrievable corpus.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import boto3
import httpx

from climate_pipeline.fetch.manifest import upload_manifest, write_manifest

SOURCES_FILE = Path(__file__).parent / "CORPUS_SOURCES.json"


def _load_sources() -> list[dict]:
    return json.loads(SOURCES_FILE.read_text())


def fetch_corpus_source(source: dict, bucket: str, manifest_dir: Path) -> Path:
    """Streams one source URL's raw content to S3. Real HTTP fetch, real content, no curation."""
    s3 = boto3.client("s3")
    key = f"raw/corpus/{source['id']}.html"

    fetched_at = datetime.now(UTC).isoformat()
    with httpx.stream("GET", source["url"], timeout=30.0, follow_redirects=True) as response:
        response.raise_for_status()
        content = b"".join(response.iter_bytes())

    s3.put_object(Bucket=bucket, Key=key, Body=content, ContentType="text/html")

    manifest = {
        "id": source["id"],
        "title": source["title"],
        "url": source["url"],
        "s3_key": key,
        "size_bytes": len(content),
        "fetched_at": fetched_at,
    }
    upload_manifest(s3, bucket, manifest, f"manifests/corpus_{source['id']}.json")
    return write_manifest(manifest, manifest_dir / f"corpus_{source['id']}.json")


def fetch_all_corpus_sources(bucket: str, manifest_dir: Path) -> list[Path]:
    return [fetch_corpus_source(source, bucket, manifest_dir) for source in _load_sources()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--manifest-dir", required=True, type=Path)
    parser.add_argument("--source-id", help="Fetch one source only, by id — matches a --field-style per-source CodeBuild step, not one build fetching all sources.")
    args = parser.parse_args()

    if args.source_id:
        sources = [s for s in _load_sources() if s["id"] == args.source_id]
        if not sources:
            raise ValueError(f"No corpus source with id {args.source_id!r} in {SOURCES_FILE}")
        path = fetch_corpus_source(sources[0], args.bucket, args.manifest_dir)
        print(f"Wrote {path}")
    else:
        paths = fetch_all_corpus_sources(args.bucket, args.manifest_dir)
        print(f"Wrote {len(paths)} corpus source manifests")


if __name__ == "__main__":
    main()
