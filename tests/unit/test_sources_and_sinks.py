import uuid
from pathlib import Path

from tadween_preprocess.adapters.sink import CompositeSink, HTTPSink, LocalSink
from tadween_preprocess.adapters.source import CompositeSource, HTTPSource, LocalSource
from tadween_preprocess.core.models import (
    Envelope,
    HttpLocation,
    ItemArtifacts,
    ItemContext,
    ItemInspection,
    ItemOptions,
    ItemState,
    LocalLocation,
    ProcessResult,
    S3Location,
)


def _make_dummy_envelope(payload, dist=None) -> Envelope:
    file_id = uuid.uuid4()
    return Envelope(
        context=ItemContext(file_id=file_id),
        dist=dist or HttpLocation(url="http://example.com/put", method="PUT"),
        options=ItemOptions(),
        insp=ItemInspection(),
        state=ItemState(),
        artifacts=ItemArtifacts(),
        payload=payload,
    )


async def test_http_source_when_given_invalid_location_type_fails_state(
    tmp_path: Path,
):
    env = _make_dummy_envelope(payload=LocalLocation(file_path=Path("/dummy")))
    src = HTTPSource()
    result = await src.get(env, tmp_path)
    assert result.state.status == "failed"
    assert "Expected HttpLocation" in str(result.state.error)


async def test_local_source_when_given_invalid_location_type_fails_state(
    tmp_path: Path,
):
    env = _make_dummy_envelope(payload=HttpLocation(url="http://example.com"))
    src = LocalSource()
    result = await src.get(env, tmp_path)
    assert result.state.status == "failed"
    assert "Expected LocalLocation" in str(result.state.error)


async def test_local_source_when_file_does_not_exist_fails_state(tmp_path: Path):
    env = _make_dummy_envelope(
        payload=LocalLocation(file_path=Path("/non_existent_file_98765.wav"))
    )
    src = LocalSource()
    result = await src.get(env, tmp_path)
    assert result.state.status == "failed"
    assert "Local file not found" in str(result.state.error)


async def test_composite_source_when_unsupported_provider_fails_state(tmp_path: Path):
    env = _make_dummy_envelope(payload=S3Location(bucket="b", key="k"))
    src = CompositeSource()
    result = await src.get(env, tmp_path)
    assert result.state.status == "failed"
    assert "Unsupported location provider" in str(result.state.error)


async def test_http_sink_when_given_invalid_location_type_fails_state(tmp_path: Path):
    test_file = tmp_path / "test.opus"
    test_file.write_bytes(b"data")
    env = _make_dummy_envelope(
        payload=ProcessResult(upload_target=test_file, is_compressed=False),
        dist=LocalLocation(file_path=Path("/dummy")),
    )
    sink = HTTPSink()
    result = await sink.write(env)
    assert result.state.status == "failed"
    assert "Expected HttpLocation" in str(result.state.error)


async def test_local_sink_when_given_invalid_location_type_fails_state(tmp_path: Path):
    test_file = tmp_path / "test.opus"
    test_file.write_bytes(b"data")
    env = _make_dummy_envelope(
        payload=ProcessResult(upload_target=test_file, is_compressed=False),
        dist=HttpLocation(url="http://example.com"),
    )
    sink = LocalSink()
    result = await sink.write(env)
    assert result.state.status == "failed"
    assert "Expected LocalLocation" in str(result.state.error)


async def test_local_sink_when_copy_fails_marks_sink_step_failed(tmp_path: Path):
    missing_file = tmp_path / "ghost.opus"
    env = _make_dummy_envelope(
        payload=ProcessResult(upload_target=missing_file, is_compressed=False),
        dist=LocalLocation(file_path=tmp_path / "dest.opus"),
    )
    sink = LocalSink()
    result = await sink.write(env)
    assert result.state.status == "failed"
    assert result.state.failed_step == "sink"


async def test_composite_sink_when_unsupported_provider_fails_state(tmp_path: Path):
    test_file = tmp_path / "test.opus"
    test_file.write_bytes(b"data")
    env = _make_dummy_envelope(
        payload=ProcessResult(upload_target=test_file, is_compressed=False),
        dist=S3Location(bucket="b", key="k"),
    )
    sink = CompositeSink()
    result = await sink.write(env)
    assert result.state.status == "failed"
    assert "Unsupported sink provider" in str(result.state.error)
