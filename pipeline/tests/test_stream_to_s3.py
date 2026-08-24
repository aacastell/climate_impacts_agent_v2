import hashlib
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from climate_pipeline.fetch.stream_to_s3 import stream_file_to_s3

_CONTENT = b"pretend-netcdf-bytes"
_CHECKSUM = hashlib.new("sha512", _CONTENT).hexdigest()

_FILE_ENTRY = {
    "name": "example_2011_2014.nc",
    "file_url": "https://files.isimip.org/example_2011_2014.nc",
    "checksum": _CHECKSUM,
    "checksum_type": "sha512",
    "size": len(_CONTENT),
}


def _not_found_error() -> ClientError:
    return ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")


@contextmanager
def _fake_httpx_stream(*args, **kwargs):
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.iter_bytes = MagicMock(return_value=iter([_CONTENT]))
    yield response


def _draining_upload_fileobj(fileobj, bucket, key, ExtraArgs=None):
    """Real boto3 reads the fileobj to actually perform the upload — a bare
    MagicMock wouldn't, which would silently skip the hashing _HashingStream
    is supposed to do as a side effect of being read. Simulate that."""
    while fileobj.read(8192):
        pass


def test_skips_fetch_when_s3_already_has_matching_checksum():
    s3 = MagicMock()
    s3.head_object.return_value = {"Metadata": {"isimip-checksum": _CHECKSUM, "isimip-fetched-at": "then"}}

    with patch("climate_pipeline.fetch.stream_to_s3.boto3.client", return_value=s3):
        manifest = stream_file_to_s3(_FILE_ENTRY, "bucket", "raw/example.nc")

    assert manifest["skipped_fetch"] is True
    assert manifest["fetched_at"] == "then"
    s3.upload_fileobj.assert_not_called()


def test_refetches_when_s3_object_missing():
    s3 = MagicMock()
    s3.head_object.side_effect = _not_found_error()
    s3.upload_fileobj.side_effect = _draining_upload_fileobj

    with (
        patch("climate_pipeline.fetch.stream_to_s3.boto3.client", return_value=s3),
        patch("climate_pipeline.fetch.stream_to_s3.httpx.stream", _fake_httpx_stream),
    ):
        manifest = stream_file_to_s3(_FILE_ENTRY, "bucket", "raw/example.nc")

    assert manifest["skipped_fetch"] is False
    s3.upload_fileobj.assert_called_once()


def test_refetches_when_isimip_checksum_no_longer_matches():
    """ISIMIP updated the file since our last fetch — a stale cached checksum
    must not be treated as a cache hit."""
    s3 = MagicMock()
    s3.head_object.return_value = {"Metadata": {"isimip-checksum": "some-old-checksum"}}
    s3.upload_fileobj.side_effect = _draining_upload_fileobj

    with (
        patch("climate_pipeline.fetch.stream_to_s3.boto3.client", return_value=s3),
        patch("climate_pipeline.fetch.stream_to_s3.httpx.stream", _fake_httpx_stream),
    ):
        manifest = stream_file_to_s3(_FILE_ENTRY, "bucket", "raw/example.nc")

    assert manifest["skipped_fetch"] is False
    s3.upload_fileobj.assert_called_once()


def test_deletes_and_raises_on_checksum_mismatch():
    s3 = MagicMock()
    s3.head_object.side_effect = _not_found_error()
    s3.upload_fileobj.side_effect = _draining_upload_fileobj
    bad_entry = {**_FILE_ENTRY, "checksum": "not-the-real-checksum"}

    with (
        patch("climate_pipeline.fetch.stream_to_s3.boto3.client", return_value=s3),
        patch("climate_pipeline.fetch.stream_to_s3.httpx.stream", _fake_httpx_stream),
    ):
        try:
            stream_file_to_s3(bad_entry, "bucket", "raw/example.nc")
            raise AssertionError("expected ValueError on checksum mismatch")
        except ValueError:
            pass

    s3.delete_object.assert_called_once_with(Bucket="bucket", Key="raw/example.nc")
