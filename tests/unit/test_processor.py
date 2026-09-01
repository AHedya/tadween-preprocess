import uuid
from pathlib import Path
from unittest.mock import patch

from tadween_preprocess.adapters.processor import MediaProcessor
from tadween_preprocess.core.models import (
    AudioStream,
    Envelope,
    HttpLocation,
    ItemContext,
    ItemInspection,
    ItemOptions,
    ItemState,
    MediaMetadata,
    SourceResult,
)


def _create_envelope(
    declared_duration: float = 10.0,
    declared_size: int = 1024,
    tolerance: float = 0.1,
) -> Envelope:
    file_id = uuid.uuid4()
    return Envelope(
        context=ItemContext(
            file_id=file_id,
            filename="test.mp3",
            og_uri="http://example.com/get",
        ),
        dist=HttpLocation(url="http://example.com/put", method="PUT"),
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
        payload=HttpLocation(url="http://example.com/get"),
    )


async def test_media_processor_when_media_invalid_flags_item(tmp_path: Path):
    env = _create_envelope()
    test_file = tmp_path / "corrupt.raw"
    test_file.write_bytes(b"bad media bytes" * 64)

    src_env = env.advance(
        SourceResult(
            raw_path=test_file,
            file_size_bytes=test_file.stat().st_size,
            is_temporary=True,
        )
    )

    processor = MediaProcessor()
    with patch(
        "tadween_preprocess.adapters.processor.get_media_metadata",
        side_effect=RuntimeError("FFprobe failed: Invalid data found"),
    ):
        proc_env = await processor.process(src_env, tmp_path)

    assert proc_env.state.status == "flagged"
    assert proc_env.state.error == "invalid_media_type"
    assert proc_env.state.failed_step == "metadata"


async def test_media_processor_when_no_audio_streams_flags_item(tmp_path: Path):
    test_bytes = b"dummy silent video" * 64
    env = _create_envelope(declared_size=len(test_bytes))
    test_file = tmp_path / "silent_video.raw"
    test_file.write_bytes(test_bytes)

    src_env = env.advance(
        SourceResult(
            raw_path=test_file,
            file_size_bytes=test_file.stat().st_size,
            is_temporary=True,
        )
    )

    processor = MediaProcessor()
    fake_meta = MediaMetadata(
        format_name="mp4",
        duration=10.0,
        bit_rate=128000,
        mime_type="video/mp4",
        audio_streams=[],  # No audio streams
    )

    with patch(
        "tadween_preprocess.adapters.processor.get_media_metadata",
        return_value=fake_meta,
    ):
        proc_env = await processor.process(src_env, tmp_path)

    assert proc_env.state.status == "flagged"
    assert proc_env.state.error == "no_audio_stream"
    assert proc_env.state.failed_step == "metadata"


async def test_media_processor_when_size_drift_exceeds_tolerance_flags_item(
    tmp_path: Path,
):
    env = _create_envelope(declared_size=1024, tolerance=0.1)
    test_file = tmp_path / "drift.raw"
    test_file.write_bytes(b"0" * 2000)  # 2000 vs 1024 is >10% drift

    src_env = env.advance(
        SourceResult(
            raw_path=test_file,
            file_size_bytes=test_file.stat().st_size,
            is_temporary=True,
        )
    )

    processor = MediaProcessor()
    proc_env = await processor.process(src_env, tmp_path)

    assert proc_env.state.status == "flagged"
    assert proc_env.state.error == "size_drift_exceeded"
    assert proc_env.state.failed_step == "validate_size"


async def test_media_processor_when_duration_drift_exceeds_tolerance_flags_item(
    tmp_path: Path,
):
    env = _create_envelope(declared_duration=10.0, tolerance=0.1)
    test_file = tmp_path / "drift_dur.raw"
    test_file.write_bytes(b"0" * 1024)

    src_env = env.advance(
        SourceResult(
            raw_path=test_file,
            file_size_bytes=test_file.stat().st_size,
            is_temporary=True,
        )
    )

    processor = MediaProcessor()
    fake_meta = MediaMetadata(
        format_name="mp3",
        duration=4.0,  # 4.0 vs 10.0 is 60% drift (exceeds 10%)
        bit_rate=128000,
        mime_type="audio/mpeg",
        audio_streams=[AudioStream(index=0, codec_name="mp3")],
    )

    with patch(
        "tadween_preprocess.adapters.processor.get_media_metadata",
        return_value=fake_meta,
    ):
        proc_env = await processor.process(src_env, tmp_path)

    assert proc_env.state.status == "flagged"
    assert proc_env.state.error == "duration_drift_exceeded"
    assert proc_env.state.failed_step == "validate_duration"
