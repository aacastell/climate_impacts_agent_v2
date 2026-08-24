"""Streams a file entry from ISIMIP directly into S3 — see ADR-006 Step 8.

The file's bytes exist only as a stream in flight: read from the HTTP
response, hashed, and handed to S3's multipart upload in the same pass,
never written whole to local disk. What DVC tracks as this stage's output
is the small manifest write_manifest() produces, not the payload itself.

Skip-if-already-fetched is checked directly against S3, not against DVC's
own dvc.lock: CodeBuild does a fresh git checkout on every run, so a
dvc.lock committed after a prior fetch wouldn't reliably be present to
compare against. S3 is the durable state that actually persists across
ephemeral runs, so that's what this checks — see conversation in this
project on why re-running the fetch stage unconditionally (the frontend
build's model, fine there because it's cheap) is the wrong default here.
"""

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime

import boto3
import httpx
from botocore.exceptions import ClientError

_CHUNK_SIZE = 1024 * 1024  # 1 MiB


class _HashingStream:
    """A file-like object (only .read() is needed by boto3's upload_fileobj)
    that wraps a byte-chunk iterator and hashes every chunk as it passes
    through — so the upload and the checksum are one pass over the data,
    not two."""

    def __init__(self, chunks: Iterator[bytes], checksum_type: str):
        self._chunks = chunks
        self._hasher = hashlib.new(checksum_type)
        self._buffer = b""
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        while size < 0 or len(self._buffer) < size:
            try:
                chunk = next(self._chunks)
            except StopIteration:
                break
            self._hasher.update(chunk)
            self.bytes_read += len(chunk)
            self._buffer += chunk
        if size < 0:
            result, self._buffer = self._buffer, b""
        else:
            result, self._buffer = self._buffer[:size], self._buffer[size:]
        return result

    def hexdigest(self) -> str:
        return self._hasher.hexdigest()


def _reusable_manifest(s3, bucket: str, key: str, file_entry: dict) -> dict | None:
    """Check whether s3://bucket/key already holds this exact ISIMIP file.

    Verified by comparing the checksum ISIMIP reports *right now* against
    what's recorded in the existing object's metadata — not just "a file
    exists at this key." If ISIMIP has since updated the file, the
    checksums won't match and this correctly reports a cache miss rather
    than reusing stale data.
    """
    try:
        head = s3.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return None
        raise

    metadata = head.get("Metadata", {})
    if metadata.get("isimip-checksum") != file_entry["checksum"]:
        return None

    return {
        "s3_key": key,
        "source_url": file_entry["file_url"],
        "checksum": file_entry["checksum"],
        "checksum_type": file_entry["checksum_type"],
        "size_bytes": file_entry["size"],
        "fetched_at": metadata.get("isimip-fetched-at", datetime.now(UTC).isoformat()),
        "skipped_fetch": True,
    }


def stream_file_to_s3(file_entry: dict, bucket: str, key: str) -> dict:
    """Stream file_entry's content from ISIMIP directly into s3://bucket/key,
    unless it's already there — see _reusable_manifest.

    Verifies the stream's hash against ISIMIP's reported checksum after
    upload completes — the only integrity check the payload ever receives
    (see ADR-006 Step 8 on why this isn't redundant with DVC's own
    hashing). Deletes the S3 object and raises on mismatch, rather than
    leaving an unverified object in place.

    Returns the manifest dict this stage's DVC output should contain.
    """
    s3 = boto3.client("s3")

    reusable = _reusable_manifest(s3, bucket, key, file_entry)
    if reusable is not None:
        return reusable

    fetched_at = datetime.now(UTC).isoformat()
    with httpx.stream("GET", file_entry["file_url"], timeout=None, follow_redirects=True) as response:
        response.raise_for_status()
        stream = _HashingStream(response.iter_bytes(chunk_size=_CHUNK_SIZE), file_entry["checksum_type"])
        s3.upload_fileobj(
            stream,
            bucket,
            key,
            ExtraArgs={
                "Metadata": {
                    "isimip-checksum": file_entry["checksum"],
                    "isimip-checksum-type": file_entry["checksum_type"],
                    "isimip-fetched-at": fetched_at,
                }
            },
        )

    if stream.hexdigest() != file_entry["checksum"]:
        s3.delete_object(Bucket=bucket, Key=key)
        raise ValueError(
            f"Checksum mismatch streaming {file_entry['name']} to s3://{bucket}/{key}: "
            f"expected {file_entry['checksum']}, got {stream.hexdigest()}"
        )

    return {
        "s3_key": key,
        "source_url": file_entry["file_url"],
        "checksum": file_entry["checksum"],
        "checksum_type": file_entry["checksum_type"],
        "size_bytes": file_entry["size"],
        "fetched_at": fetched_at,
        "skipped_fetch": False,
    }
