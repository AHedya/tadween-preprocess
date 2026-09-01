import re
import uuid
from pathlib import Path
from unittest.mock import MagicMock

from pytest_httpserver import HTTPServer

from tadween_preprocess.core.models import (
    AudioStream,
    HttpLocation,
    ItemContext,
    ItemOptions,
    MediaMetadata,
)
from tadween_preprocess.models import (
    PreprocessBatch,
    PreprocessItem,
    PreprocessJobRequest,
)
from tadween_preprocess.orchestrator import Orchestrator


def test_pipeline_skips_compression_when_input_already_opus(
    httpserver: HTTPServer,
    mock_convert_to_opus: MagicMock,
    mock_get_media_metadata: MagicMock,
    tmp_path: Path,
):
    httpserver.expect_request(re.compile(r"^/.*"), method="GET").respond_with_data(
        b"x" * 1024
    )
    httpserver.expect_request(re.compile(r"^/put.*"), method="PUT").respond_with_data(
        "OK", status=200
    )
    base_url = httpserver.url_for("").rstrip("/")

    file_id = uuid.uuid4()
    item = PreprocessItem(
        context=ItemContext(file_id=file_id, filename="test.opus"),
        source=HttpLocation(url=f"{base_url}/get"),
        sink=HttpLocation(url=f"{base_url}/put", method="PUT"),
        options=ItemOptions(
            require_compression=True,
            require_duration=True,
            require_size=True,
            declared_duration_seconds=10,
            declared_size_bytes=1024,
        ),
    )

    mock_get_media_metadata.return_value = MediaMetadata(
        format_name="opus",
        mime_type="audio/opus",
        duration=10.0,
        audio_streams=[AudioStream(index=0, codec_name="opus")],
    )

    req = PreprocessJobRequest(
        batch=PreprocessBatch(id=uuid.uuid4(), files={file_id: item})
    )
    orchestrator = Orchestrator()
    results = orchestrator.execute(req, tmp_path)

    assert results[file_id].status == "completed"
    mock_convert_to_opus.assert_not_called()

    put_reqs = [req for req, res in httpserver.log if req.method == "PUT"]
    assert len(put_reqs) == 1


def test_pipeline_compresses_media_when_input_is_not_opus(
    httpserver: HTTPServer,
    mock_convert_to_opus: MagicMock,
    mock_get_media_metadata: MagicMock,
    tmp_path: Path,
):
    httpserver.expect_request(re.compile(r"^/.*"), method="GET").respond_with_data(
        b"x" * 1024
    )
    httpserver.expect_request(re.compile(r"^/put.*"), method="PUT").respond_with_data(
        "OK", status=200
    )
    base_url = httpserver.url_for("").rstrip("/")

    file_id = uuid.uuid4()
    item = PreprocessItem(
        context=ItemContext(file_id=file_id, filename="test.mp3"),
        source=HttpLocation(url=f"{base_url}/get"),
        sink=HttpLocation(url=f"{base_url}/put", method="PUT"),
        options=ItemOptions(
            require_compression=True,
            require_duration=True,
            require_size=True,
            declared_duration_seconds=10,
            declared_size_bytes=1024,
        ),
    )

    mock_get_media_metadata.return_value = MediaMetadata(
        format_name="mp3",
        mime_type="audio/mpeg",
        duration=10.0,
        audio_streams=[AudioStream(index=0, codec_name="mp3")],
    )

    req = PreprocessJobRequest(
        batch=PreprocessBatch(id=uuid.uuid4(), files={file_id: item})
    )
    orchestrator = Orchestrator()
    results = orchestrator.execute(req, tmp_path)

    assert results[file_id].status == "completed"
    mock_convert_to_opus.assert_called_once()

    put_reqs = [req for req, res in httpserver.log if req.method == "PUT"]
    assert len(put_reqs) == 1


def test_pipeline_skips_compression_when_custom_codecs_allowed(
    httpserver: HTTPServer,
    mock_convert_to_opus: MagicMock,
    mock_get_media_metadata: MagicMock,
    tmp_path: Path,
):
    httpserver.expect_request(re.compile(r"^/.*"), method="GET").respond_with_data(
        b"x" * 1024
    )
    httpserver.expect_request(re.compile(r"^/put.*"), method="PUT").respond_with_data(
        "OK", status=200
    )
    base_url = httpserver.url_for("").rstrip("/")

    file_id = uuid.uuid4()
    item = PreprocessItem(
        context=ItemContext(file_id=file_id, filename="test.ogg"),
        source=HttpLocation(url=f"{base_url}/get"),
        sink=HttpLocation(url=f"{base_url}/put", method="PUT"),
        options=ItemOptions(
            require_compression=True,
            require_duration=True,
            require_size=True,
            acceptable_codecs=["vorbis"],
            acceptable_containers=["ogg"],
            declared_duration_seconds=10,
            declared_size_bytes=1024,
        ),
    )

    mock_get_media_metadata.return_value = MediaMetadata(
        format_name="ogg",
        mime_type="audio/ogg",
        duration=10.0,
        audio_streams=[AudioStream(index=0, codec_name="vorbis")],
    )

    req = PreprocessJobRequest(
        batch=PreprocessBatch(id=uuid.uuid4(), files={file_id: item})
    )
    orchestrator = Orchestrator()
    results = orchestrator.execute(req, tmp_path)

    assert results[file_id].status == "completed"
    mock_convert_to_opus.assert_not_called()

    put_reqs = [req for req, res in httpserver.log if req.method == "PUT"]
    assert len(put_reqs) == 1
