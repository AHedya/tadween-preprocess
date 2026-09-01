import asyncio
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from resource_semaphore import AsyncResourceSemaphore

from tadween_preprocess.adapters.processor import MediaProcessor
from tadween_preprocess.adapters.sink import LocalSink
from tadween_preprocess.adapters.source import LocalSource
from tadween_preprocess.core.models import (
    AudioStream,
    Envelope,
    HttpLocation,
    ItemContext,
    ItemInspection,
    ItemOptions,
    ItemState,
    LocalLocation,
    MediaMetadata,
    SourceResult,
)
from tadween_preprocess.models import (
    PreprocessBatch,
    PreprocessItem,
    PreprocessJobRequest,
)
from tadween_preprocess.orchestrator import _run_coroutine_sync, process_envelope
from tadween_preprocess.runner import run


def _create_envelope(
    source_loc=None,
    sink_loc=None,
    declared_duration=10.0,
    declared_size=1024,
    tolerance=0.1,
) -> Envelope:
    file_id = uuid.uuid4()
    return Envelope(
        context=ItemContext(
            file_id=file_id,
            filename="test.mp3",
            og_uri="http://example.com/get",
        ),
        dist=sink_loc or HttpLocation(url="http://example.com/put", method="PUT"),
        options=ItemOptions(
            require_duration=True,
            require_size=True,
            require_compression=True,
            declared_duration_seconds=declared_duration,
            declared_size_bytes=declared_size,
            tolerance_rate=tolerance,
        ),
        insp=ItemInspection(),
        state=ItemState(),
        payload=source_loc or HttpLocation(url="http://example.com/get"),
    )


async def test_process_envelope_when_source_fails_marks_envelope_failed(
    tmp_path: Path,
):
    env = _create_envelope()
    mock_source = MagicMock()
    mock_source.get = AsyncMock(
        side_effect=RuntimeError("Connection dropped during download")
    )
    mock_proc = MagicMock()
    mock_sink = MagicMock()
    rm = AsyncResourceSemaphore({"download_slots": 1, "disk_bytes": 100_000_000})

    res_env = await process_envelope(
        env, mock_source, mock_proc, mock_sink, rm, tmp_path
    )
    assert res_env.state.status == "failed"
    assert res_env.state.failed_step == "source"
    assert "Connection dropped" in str(res_env.state.error)


async def test_process_envelope_local_source_and_sink_preserves_original_file(
    tmp_path: Path,
):
    src_file = tmp_path / "original_voice.mp3"
    src_file.write_bytes(b"sample local audio bytes")
    dest_file = tmp_path / "output_dir" / "processed.opus"

    env = _create_envelope(
        source_loc=LocalLocation(file_path=src_file),
        sink_loc=LocalLocation(file_path=dest_file),
        declared_size=len(b"sample local audio bytes"),
    )

    source = LocalSource()
    sink = LocalSink()
    processor = MediaProcessor()
    rm = AsyncResourceSemaphore(
        {
            "download_slots": 1,
            "disk_bytes": 100_000_000,
            "cpu_cores": 1,
            "ram_bytes": 200 * 1024 * 1024,
            "upload_slots": 1,
        }
    )

    work_dir = tmp_path / "work"
    work_dir.mkdir()

    with patch(
        "tadween_preprocess.adapters.processor.get_media_metadata",
        return_value=MediaMetadata(
            format_name="opus",
            mime_type="audio/opus",
            duration=10.0,
            bit_rate=32000,
            audio_streams=[AudioStream(index=0, codec_name="opus")],
        ),
    ):
        result_env = await process_envelope(env, source, processor, sink, rm, work_dir)

    assert result_env.state.status == "completed"
    assert dest_file.exists()
    assert dest_file.read_bytes() == b"sample local audio bytes"
    # Verify original source file was NOT deleted!
    assert src_file.exists()


async def test_process_envelope_cancellation_shields_disk_release(tmp_path: Path):
    env = _create_envelope(declared_size=1024)
    test_file = tmp_path / "test.raw"
    test_file.write_bytes(b"x" * 1024)

    mock_source = MagicMock()
    mock_source.get = AsyncMock(
        return_value=env.advance(
            SourceResult(
                raw_path=test_file,
                file_size_bytes=1024,
                is_temporary=True,
            )
        )
    )

    async def hang_in_processor(*args, **kwargs):
        await asyncio.sleep(10)
        return env

    mock_proc = MagicMock()
    mock_proc.process = AsyncMock(side_effect=hang_in_processor)
    mock_sink = MagicMock()

    rm = AsyncResourceSemaphore(
        {
            "download_slots": 1,
            "disk_bytes": 100_000,
            "cpu_cores": 1,
            "ram_bytes": 200 * 1024 * 1024,
            "upload_slots": 1,
        }
    )

    initial_disk = rm.available["disk_bytes"]

    task = asyncio.create_task(
        process_envelope(env, mock_source, mock_proc, mock_sink, rm, tmp_path)
    )

    # Let task run to the point of acquiring disk and entering processor
    await asyncio.sleep(0.05)

    # Cancel the task
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Verify that shielded release ran and disk bytes returned to full capacity
    assert rm.available["disk_bytes"] == initial_disk


async def test_process_envelope_when_resource_demand_exceeds_capacity_fails_item(
    tmp_path: Path,
):
    env = _create_envelope(declared_size=10_000)
    test_file = tmp_path / "huge.raw"
    test_file.write_bytes(b"x" * 10_000)

    mock_source = MagicMock()
    mock_source.get = AsyncMock(
        return_value=env.advance(
            SourceResult(
                raw_path=test_file,
                file_size_bytes=10_000,
                is_temporary=True,
            )
        )
    )
    mock_proc = MagicMock()
    mock_sink = MagicMock()

    # Configure disk_bytes smaller than the file's demand (10_000 * 1.1 = 11_000)
    rm = AsyncResourceSemaphore(
        {
            "download_slots": 1,
            "disk_bytes": 5_000,
            "cpu_cores": 1,
            "ram_bytes": 200 * 1024 * 1024,
            "upload_slots": 1,
        }
    )

    res_env = await process_envelope(
        env, mock_source, mock_proc, mock_sink, rm, tmp_path
    )

    assert res_env.state.status == "failed"
    assert res_env.state.failed_step == "resource_acquisition"
    assert "resource_error" in str(res_env.state.error)


async def test_run_coroutine_sync_executes_correctly_inside_running_loop():
    async def sample_coro():
        return 42

    result = _run_coroutine_sync(sample_coro())
    assert result == 42


def test_runner_run_with_default_settings_and_no_webhook(tmp_path: Path):
    src_file = tmp_path / "sample.mp3"
    src_file.write_bytes(b"audio")
    file_id = uuid.uuid4()

    req = PreprocessJobRequest(
        batch=PreprocessBatch(
            id=uuid.uuid4(),
            files={
                file_id: PreprocessItem(
                    context=ItemContext(file_id=file_id),
                    source=LocalLocation(file_path=src_file),
                    sink=LocalLocation(file_path=tmp_path / "out.opus"),
                    options=ItemOptions(
                        require_compression=False,
                        require_duration=False,
                        require_size=False,
                    ),
                )
            },
        ),
        webhook=None,  # Tests no-webhook branch
    )

    valid_meta = MediaMetadata(
        duration=10.0,
        bit_rate=128000,
        format_name="mp3",
        mime_type="audio/mpeg",
        audio_streams=[AudioStream(index=0, codec_name="mp3")],
    )

    with patch(
        "tadween_preprocess.adapters.processor.get_media_metadata",
        return_value=valid_meta,
    ):
        results = run(req, cache_dir=tmp_path / "cache")
        assert file_id in results
        assert results[file_id].status == "completed"


def test_runner_run_when_orchestrator_raises_unhandled_exception(tmp_path: Path):
    file_id = uuid.uuid4()
    req = PreprocessJobRequest(
        batch=PreprocessBatch(
            id=uuid.uuid4(),
            files={
                file_id: PreprocessItem(
                    context=ItemContext(file_id=file_id),
                    source=LocalLocation(file_path=tmp_path / "dummy.mp3"),
                    sink=LocalLocation(file_path=tmp_path / "out.opus"),
                )
            },
        )
    )

    mock_orch = MagicMock()
    mock_orch.execute.side_effect = RuntimeError("Fatal hardware failure")

    with pytest.raises(RuntimeError, match="Fatal hardware failure"):
        run(req, cache_dir=tmp_path / "cache", orchestrator=mock_orch)


def test_runner_run_cleanup_handles_rmtree_oserror_gracefully(tmp_path: Path):
    src_file = tmp_path / "sample.mp3"
    src_file.write_bytes(b"audio")
    file_id = uuid.uuid4()

    req = PreprocessJobRequest(
        batch=PreprocessBatch(
            id=uuid.uuid4(),
            files={
                file_id: PreprocessItem(
                    context=ItemContext(file_id=file_id),
                    source=LocalLocation(file_path=src_file),
                    sink=LocalLocation(file_path=tmp_path / "out.opus"),
                    options=ItemOptions(
                        require_compression=False,
                        require_duration=False,
                        require_size=False,
                    ),
                )
            },
        )
    )

    with patch("shutil.rmtree", side_effect=OSError("Permission denied")):
        results = run(req, cache_dir=tmp_path / "cache")
        assert file_id in results
