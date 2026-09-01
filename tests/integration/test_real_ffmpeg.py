import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer  # type: ignore
from resource_semaphore import AsyncResourceSemaphore

from tadween_preprocess.core.models import (
    HttpLocation,
    ItemContext,
    ItemOptions,
    LocalLocation,
)
from tadween_preprocess.models import (
    PreprocessBatch,
    PreprocessItem,
    PreprocessJobRequest,
    WebhookConfig,
)
from tadween_preprocess.orchestrator import Orchestrator


@pytest.fixture(scope="session")
def real_audio_file(tmp_path_factory) -> Path:
    """Generates a real 1-second sine wave WAV file for testing ffmpeg without mocking."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg binary not found in PATH")
    path = tmp_path_factory.mktemp("audio") / "test.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:duration=1",
            "-c:a",
            "pcm_s16le",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


async def test_real_ffmpeg_end_to_end_conversion_over_http(
    httpserver: HTTPServer,
    real_audio_file: Path,
    tmp_path: Path,
):
    """
    Tests the full pipeline on a real WAV file, driving the actual subprocess.run
    calls for ffprobe (metadata) and ffmpeg (conversion).
    No mock_convert_to_opus or mock_get_media_metadata is used!
    """
    audio_data = real_audio_file.read_bytes()
    httpserver.expect_request("/test.wav", method="GET").respond_with_data(
        audio_data, mimetype="audio/wav"
    )
    httpserver.expect_request("/put", method="PUT").respond_with_data("OK", status=200)
    httpserver.expect_request("/webhook", method="POST").respond_with_json(
        {"status": "ok"}
    )

    base_url = httpserver.url_for("")

    file_id = uuid.uuid4()
    item = PreprocessItem(
        context=ItemContext(file_id=file_id, filename="test.wav"),
        source=HttpLocation(url=f"{base_url}/test.wav"),
        sink=HttpLocation(url=f"{base_url}/put", method="PUT"),
        options=ItemOptions(
            require_duration=True,
            require_size=True,
            require_compression=True,
            declared_duration_seconds=1.0,
            declared_size_bytes=len(audio_data),
            tolerance_rate=0.5,
        ),
    )

    batch_id = uuid.uuid4()
    req = PreprocessJobRequest(
        webhook=WebhookConfig(url=f"{base_url}/webhook", token="secret"),
        batch=PreprocessBatch(id=batch_id, files={file_id: item}),
    )

    rm = AsyncResourceSemaphore(
        {
            "download_slots": 2,
            "cpu_cores": 2,
            "upload_slots": 2,
            "disk_bytes": 100 * 1024 * 1024,
            "ram_bytes": 100 * 1024 * 1024,
        }
    )

    orchestrator = Orchestrator(rm=rm)
    results = await orchestrator.execute_async(req, temp_dir=tmp_path)

    assert len(results) == 1
    res = results[file_id]
    assert res.status == "completed"
    assert res.true_duration_seconds is not None
    assert 0.9 <= res.true_duration_seconds <= 1.1
    assert res.true_size_bytes == len(audio_data)


async def test_real_ffmpeg_end_to_end_conversion_on_local_filesystem(
    real_audio_file: Path,
    tmp_path: Path,
):
    """
    Tests pure local filesystem processing without any HTTP server:
    LocalLocation -> FFprobe -> FFmpeg Opus -> LocalLocation.
    """
    output_file = tmp_path / "output_processed.opus"
    file_id = uuid.uuid4()

    item = PreprocessItem(
        context=ItemContext(file_id=file_id, filename="test.wav"),
        source=LocalLocation(file_path=real_audio_file),
        sink=LocalLocation(file_path=output_file),
        options=ItemOptions(
            require_duration=True,
            require_size=True,
            require_compression=True,
            declared_duration_seconds=1.0,
            declared_size_bytes=real_audio_file.stat().st_size,
            tolerance_rate=0.5,
        ),
    )

    req = PreprocessJobRequest(
        batch=PreprocessBatch(id=uuid.uuid4(), files={file_id: item})
    )

    work_dir = tmp_path / "work"
    work_dir.mkdir()

    orchestrator = Orchestrator()
    results = await orchestrator.execute_async(req, temp_dir=work_dir)

    assert len(results) == 1
    res = results[file_id]
    assert res.status == "completed"
    assert output_file.exists()
    assert output_file.stat().st_size > 0
    assert res.true_size_bytes == real_audio_file.stat().st_size
    assert res.true_duration_seconds is not None
    assert 0.9 <= res.true_duration_seconds <= 1.1
    # Verify original source WAV file remains intact
    assert real_audio_file.exists()
