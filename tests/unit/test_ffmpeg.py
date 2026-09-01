import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tadween_preprocess.adapters._ffmpeg import (
    DEFAULT_ACCEPTABLE_CODECS,
    DEFAULT_ACCEPTABLE_CONTAINERS,
    _safe_float,
    _safe_int,
    _safe_int_or_none,
    convert_to_opus,
    get_media_metadata,
    get_mimetype_mapping,
    is_compression_skippable,
)
from tadween_preprocess.core.models import AudioStream, MediaMetadata


def test_mock_convert_to_opus_creates_destination_file(
    mock_convert_to_opus: MagicMock, tmp_path: Path
):
    dl_path = tmp_path / "data.wav"
    dl_path.write_bytes(b"dummy content")

    mock_convert_to_opus(input_file=dl_path)
    out_path = dl_path.with_suffix(".opus")
    assert out_path.exists()


def test_mock_get_media_metadata_returns_metadata(
    mock_get_media_metadata: MagicMock, tmp_path: Path
):
    dl_path = tmp_path / "data.wav"
    dl_path.write_bytes(b"dummy content")

    res = mock_get_media_metadata(file_path=dl_path)
    assert isinstance(res, MediaMetadata)


def test_is_compression_skippable_when_already_opus_by_mime_type():
    meta = MediaMetadata(
        format_name="opus",
        mime_type="audio/opus",
        duration=10.0,
    )
    assert is_compression_skippable(
        meta,
        acceptable_codecs=DEFAULT_ACCEPTABLE_CODECS,
        acceptable_containers=DEFAULT_ACCEPTABLE_CONTAINERS,
    )


def test_is_compression_skippable_when_already_opus_by_codec_name():
    meta = MediaMetadata(
        format_name="ogg",
        mime_type="audio/ogg",
        duration=10.0,
        audio_streams=[AudioStream(index=0, codec_name="opus")],
    )
    assert is_compression_skippable(
        meta,
        acceptable_codecs=DEFAULT_ACCEPTABLE_CODECS,
        acceptable_containers=DEFAULT_ACCEPTABLE_CONTAINERS,
    )


def test_is_compression_skippable_returns_false_for_mp3():
    meta = MediaMetadata(
        format_name="mp3",
        mime_type="audio/mpeg",
        duration=10.0,
        audio_streams=[AudioStream(index=0, codec_name="mp3")],
    )
    assert not is_compression_skippable(
        meta,
        acceptable_codecs=DEFAULT_ACCEPTABLE_CODECS,
        acceptable_containers=DEFAULT_ACCEPTABLE_CONTAINERS,
    )


def test_is_compression_skippable_returns_false_for_ogg_vorbis_by_default():
    meta = MediaMetadata(
        format_name="ogg",
        mime_type="audio/ogg",
        duration=10.0,
        audio_streams=[AudioStream(index=0, codec_name="vorbis")],
    )
    assert not is_compression_skippable(
        meta,
        acceptable_codecs=DEFAULT_ACCEPTABLE_CODECS,
        acceptable_containers=DEFAULT_ACCEPTABLE_CONTAINERS,
    )


def test_is_compression_skippable_with_custom_acceptable_codecs_and_containers():
    # Vorbis in OGG is accepted when acceptable_codecs includes vorbis
    ogg_vorbis_meta = MediaMetadata(
        format_name="ogg",
        mime_type="audio/ogg",
        duration=10.0,
        audio_streams=[AudioStream(index=0, codec_name="vorbis")],
    )
    assert (
        is_compression_skippable(ogg_vorbis_meta, acceptable_codecs=["opus", "vorbis"])
        is True
    )
    assert (
        is_compression_skippable(ogg_vorbis_meta, acceptable_codecs=["opus"]) is False
    )

    # AAC in M4A container
    m4a_aac_meta = MediaMetadata(
        format_name="mov,mp4,m4a",
        mime_type="video/mp4",
        duration=10.0,
        audio_streams=[AudioStream(index=0, codec_name="aac")],
    )
    assert (
        is_compression_skippable(
            m4a_aac_meta,
            acceptable_codecs=["aac"],
            acceptable_containers=["m4a", "mov", "mp4"],
        )
        is True
    )
    # Disallowed container
    assert (
        is_compression_skippable(
            m4a_aac_meta,
            acceptable_codecs=["aac"],
            acceptable_containers=["ogg"],
        )
        is False
    )

    # MP3 file
    mp3_meta = MediaMetadata(
        format_name="mp3",
        mime_type="audio/mpeg",
        duration=10.0,
        audio_streams=[AudioStream(index=0, codec_name="mp3")],
    )
    assert (
        is_compression_skippable(
            mp3_meta,
            acceptable_codecs=["mp3"],
            acceptable_containers=["mp3"],
        )
        is True
    )
    assert is_compression_skippable(mp3_meta) is False


def test_get_mimetype_mapping_known_and_fallback_formats():
    assert get_mimetype_mapping("mp3") == "audio/mpeg"
    assert get_mimetype_mapping("matroska,webm") == "video/webm"
    assert get_mimetype_mapping("mov,mp4,m4a") == "video/mp4"
    assert get_mimetype_mapping("unknown_ext") == "application/octet-stream"
    assert get_mimetype_mapping("") == "application/octet-stream"


def test_safe_numeric_helpers_parsing_and_fallbacks():
    assert _safe_float(None) == 0.0
    assert _safe_float("N/A") == 0.0
    assert _safe_float("") == 0.0
    assert _safe_float("12.34") == 12.34
    assert _safe_float(5) == 5.0

    assert _safe_int(None) == 0
    assert _safe_int("N/A") == 0
    assert _safe_int("") == 0
    assert _safe_int("128000") == 128000
    assert _safe_int(44100) == 44100

    assert _safe_int_or_none(None) is None
    assert _safe_int_or_none("N/A") is None
    assert _safe_int_or_none("") is None
    assert _safe_int_or_none("48000") == 48000
    assert _safe_int_or_none(2) == 2


def test_get_media_metadata_with_null_and_missing_fields(tmp_path: Path):
    dummy_file = tmp_path / "dummy.raw"
    dummy_file.write_bytes(b"dummy")

    fake_ffprobe_json = {
        "format": {
            "format_name": "mp3",
            "duration": None,  # format duration is None
            "bit_rate": "N/A",  # bitrate is non-integer string
        },
        "streams": [
            {
                "codec_type": "audio",
                "codec_name": "mp3",
                "index": None,
                "channels": "N/A",
                "sample_rate": "44100",
                "duration": "15.5",  # stream duration fallback
            }
        ],
    }

    mock_process = subprocess.CompletedProcess(
        args=["ffprobe"],
        returncode=0,
        stdout=json.dumps(fake_ffprobe_json),
        stderr="",
    )

    with patch("subprocess.run", return_value=mock_process):
        meta = get_media_metadata(dummy_file)

    assert meta.format_name == "mp3"
    assert meta.duration == 15.5
    assert meta.bit_rate == 0
    assert len(meta.audio_streams) == 1
    assert meta.audio_streams[0].codec_name == "mp3"
    assert meta.audio_streams[0].index == 0
    assert meta.audio_streams[0].channels is None
    assert meta.audio_streams[0].sample_rate == 44100


def test_get_media_metadata_called_process_error_raises_runtime_error(tmp_path: Path):
    test_file = tmp_path / "corrupt.mp3"
    test_file.write_bytes(b"corrupt data")

    with (
        patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(
                returncode=1, cmd=["ffprobe"], stderr="Invalid data"
            ),
        ),
        pytest.raises(RuntimeError, match="FFprobe failed for file"),
    ):
        get_media_metadata(test_file)


def test_get_media_metadata_timeout_raises_runtime_error(tmp_path: Path):
    test_file = tmp_path / "hang.mp3"
    test_file.write_bytes(b"data")

    with (
        patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["ffprobe"], timeout=5),
        ),
        pytest.raises(RuntimeError, match="FFprobe timed out after"),
    ):
        get_media_metadata(test_file, timeout_sec=5)


def test_convert_to_opus_timeout_raises_runtime_error(tmp_path: Path):
    in_file = tmp_path / "in.wav"
    in_file.write_bytes(b"data")
    out_file = tmp_path / "out.opus"

    mock_process = MagicMock()
    mock_process.communicate.side_effect = [
        subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=5),
        (b"", b""),
    ]

    mock_node = MagicMock()
    mock_node.output.return_value = mock_node
    mock_node.overwrite_output.return_value = mock_node
    mock_node.run_async.return_value = mock_process

    with (
        patch("ffmpeg.input", return_value=mock_node),
        pytest.raises(RuntimeError, match="FFmpeg conversion timed out after"),
    ):
        convert_to_opus(in_file, out_file, timeout_sec=5)


def test_convert_to_opus_non_zero_returncode_raises_runtime_error(tmp_path: Path):
    in_file = tmp_path / "in.wav"
    in_file.write_bytes(b"data")
    out_file = tmp_path / "out.opus"

    mock_process = MagicMock()
    mock_process.communicate.return_value = (b"", b"FFmpeg internal error")
    mock_process.returncode = 1

    mock_node = MagicMock()
    mock_node.output.return_value = mock_node
    mock_node.overwrite_output.return_value = mock_node
    mock_node.run_async.return_value = mock_process

    with (
        patch("ffmpeg.input", return_value=mock_node),
        pytest.raises(RuntimeError, match="FFmpeg failed with error"),
    ):
        convert_to_opus(in_file, out_file)
