import shutil
from collections.abc import Generator
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from opentelemetry import metrics, trace
from opentelemetry.util._once import Once

from tadween_preprocess.core import telemetry
from tadween_preprocess.core.models import AudioStream, MediaMetadata

from .utils import TelemetryHandles

tracer = trace.get_tracer(__name__)


@pytest.fixture
def mock_convert_to_opus() -> Generator[MagicMock]:
    def _mock_convert(
        input_file: str | Path,
        output_file: str | Path | None = None,
        bitrate: str = "16k",
        sr: str | int = 16000,
        use_voip: bool = True,
        timeout_sec: float = 600,
        capture_stderr: bool = True,
    ):
        input_path = Path(input_file)
        output_path = (
            Path(output_file) if output_file else input_path.with_suffix(".opus")
        )
        shutil.copy(src=input_path, dst=output_path)

    with (
        patch("tadween_preprocess.adapters._ffmpeg.convert_to_opus") as mock_core,
        patch("tadween_preprocess.adapters.processor.convert_to_opus") as mock_proc,
    ):
        mock_core.side_effect = _mock_convert
        mock_proc.side_effect = mock_core
        yield mock_core


@pytest.fixture
def mock_get_media_metadata() -> Generator[MagicMock]:
    """Assume all downloaded files are mp3 by default"""

    def _mock_meta(file_path: str | Path, timeout_sec: float = 15) -> MediaMetadata:
        if mock_core.return_value is not None and not isinstance(
            mock_core.return_value, MagicMock
        ):
            return mock_core.return_value
        return MediaMetadata(
            format_name="mp3",
            mime_type="audio/mpeg",
            duration=600.0,
            bit_rate=31759,
            audio_streams=[AudioStream(index=0, codec_name="mp3")],
        )

    with (
        patch("tadween_preprocess.adapters._ffmpeg.get_media_metadata") as mock_core,
        patch("tadween_preprocess.adapters.processor.get_media_metadata") as mock_proc,
    ):
        mock_core.side_effect = _mock_meta
        mock_proc.side_effect = mock_core
        mock_core.return_value = None
        mock_proc.return_value = None
        yield mock_core


def reset_telemetry_for_testing() -> None:
    trace._TRACER_PROVIDER = None
    metrics._internal._METER_PROVIDER = None

    trace._TRACER_PROVIDER_SET_ONCE = Once()
    metrics._internal._METER_PROVIDER_SET_ONCE = Once()

    telemetry._test_handles.span_exporter = None
    telemetry._test_handles.metric_reader = None


@pytest.fixture(autouse=True)
def _reset_otel_state():
    reset_telemetry_for_testing()
    telemetry.init_telemetry(service_name="test-service")
    yield
    reset_telemetry_for_testing()


@pytest.fixture
def telemetry_handles(_reset_otel_state) -> TelemetryHandles:
    return TelemetryHandles(
        span_exporter=cast(
            telemetry.InMemorySpanExporter,
            telemetry._test_handles.span_exporter,
        ),
        metric_reader=cast(
            telemetry.InMemoryMetricReader,
            telemetry._test_handles.metric_reader,
        ),
    )
