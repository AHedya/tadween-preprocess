from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from pytest_httpserver import HTTPServer

from tadween_preprocess.adapters._http import (
    _client_scope,
    _expected_total,
    download_file_stream,
    upload_file_stream,
)


async def test_client_scope_creates_default_client():
    async with _client_scope(None) as client:
        assert isinstance(client, httpx.AsyncClient)
        assert not client.is_closed


async def test_upload_file_stream_when_file_missing_raises_file_not_found_error(
    tmp_path: Path,
):
    missing_file = tmp_path / "ghost.opus"
    with pytest.raises(FileNotFoundError, match="Can't upload not found file"):
        await upload_file_stream("http://example.com", missing_file)


async def test_upload_file_stream_when_method_unsupported_raises_value_error(
    tmp_path: Path,
):
    test_file = tmp_path / "test.opus"
    test_file.write_bytes(b"data")
    with pytest.raises(ValueError, match="Unsupported method"):
        await upload_file_stream(
            "http://example.com",
            test_file,
            method="PATCH",  # type: ignore
        )


async def test_upload_file_stream_supports_post_method_with_fields(
    tmp_path: Path, httpserver: HTTPServer
):
    test_file = tmp_path / "test.opus"
    test_file.write_bytes(b"sample opus data")

    httpserver.expect_request("/upload", method="POST").respond_with_json(
        {"status": "ok"}
    )
    url = httpserver.url_for("/upload")

    await upload_file_stream(
        url=url,
        file_path=test_file,
        method="POST",
        fields={"key": "custom_key"},
    )
    assert len(httpserver.log) == 1


async def test_download_file_stream_when_size_exceeds_limit_raises_value_error(
    tmp_path: Path, httpserver: HTTPServer
):
    httpserver.expect_request("/download").respond_with_data(b"x" * 1000)
    url = httpserver.url_for("/download")
    dest_path = tmp_path / "out.raw"

    with pytest.raises(ValueError, match="Download exceeded max allowed size"):
        await download_file_stream(
            get_url=url,
            destination_path=dest_path,
            max_bytes=500,
        )


async def test_download_file_stream_when_stream_ends_early_raises_stream_error(
    tmp_path: Path,
):
    dest_path = tmp_path / "out.raw"

    mock_resp = MagicMock()
    mock_resp.headers = {"Content-Length": "1000"}
    mock_resp.raise_for_status = MagicMock()

    async def _mock_aiter_bytes(chunk_size=65536):
        yield b"short bytes"

    mock_resp.aiter_bytes = _mock_aiter_bytes

    class MockStreamContext:
        async def __aenter__(self):
            return mock_resp

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_client.stream.return_value = MockStreamContext()

    with pytest.raises(httpx.StreamError, match="Stream ended early"):
        await download_file_stream(
            get_url="http://fake.com/file",
            destination_path=dest_path,
            client=mock_client,
        )


def test_expected_total_header_parsing_and_fallbacks():
    resp_no_cl = httpx.Response(200)
    assert _expected_total(resp_no_cl, 0) is None

    resp_bad_cl = httpx.Response(200, headers={"Content-Length": "invalid_number"})
    assert _expected_total(resp_bad_cl, 0) is None
