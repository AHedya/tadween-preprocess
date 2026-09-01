import json
import subprocess
from pathlib import Path
from typing import Any

import ffmpeg

from tadween_preprocess.adapters._mime_map import FFPROBE_MIME_MAP
from tadween_preprocess.core.models import AudioStream, MediaMetadata

DEFAULT_ACCEPTABLE_CODECS = {"opus"}
DEFAULT_ACCEPTABLE_CONTAINERS = {"opus", "ogg"}


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except ValueError, TypeError:
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    if val is None:
        return default
    try:
        return int(val)
    except ValueError, TypeError:
        return default


def _safe_int_or_none(val: Any) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except ValueError, TypeError:
        return None


def get_mimetype_mapping(file_format: str) -> str:
    if not file_format:
        return "application/octet-stream"
    if file_format in FFPROBE_MIME_MAP:
        return FFPROBE_MIME_MAP[file_format]
    for part in file_format.split(","):
        part = part.strip()
        if part in FFPROBE_MIME_MAP:
            return FFPROBE_MIME_MAP[part]
    return "application/octet-stream"


def is_compression_skippable(
    meta: MediaMetadata,
    acceptable_codecs: set[str] | list[str] | None = None,
    acceptable_containers: set[str] | list[str] | None = None,
) -> bool:
    """
    Check if the media file already uses an acceptable codec and container
    so that FFmpeg re-compression can be safely skipped.
    """
    codecs = (
        {c.lower() for c in acceptable_codecs}
        if acceptable_codecs is not None
        else DEFAULT_ACCEPTABLE_CODECS
    )
    containers = (
        {c.lower() for c in acceptable_containers}
        if acceptable_containers is not None
        else DEFAULT_ACCEPTABLE_CONTAINERS
    )

    format_parts = {p.strip().lower() for p in meta.format_name.split(",")}
    container_matches = (
        bool(format_parts & containers)
        or ("opus" in containers and meta.mime_type == "audio/opus")
        or ("ogg" in containers and meta.mime_type == "audio/ogg")
    )

    if not container_matches and containers:
        return False

    if "opus" in codecs and (meta.mime_type == "audio/opus" or "opus" in format_parts):
        return True

    return any(
        s.codec_name is not None and s.codec_name.lower() in codecs
        for s in meta.audio_streams
    )


def get_media_metadata(file_path: str | Path, timeout_sec: float = 15) -> MediaMetadata:
    args = [
        "ffprobe",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(file_path),
    ]
    try:
        process = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=True,
        )

    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"FFprobe failed for file: {file_path}. Stderr: {e.stderr}"
        ) from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"FFprobe timed out after {timeout_sec}s for file: {file_path}"
        ) from e

    data = json.loads(process.stdout)
    format_info = data.get("format", {}) or {}
    duration = _safe_float(format_info.get("duration"), 0.0)
    bit_rate = _safe_int(format_info.get("bit_rate"), 0)
    file_format = format_info.get("format_name", "") or ""

    streams_info = data.get("streams", []) or []
    audio_streams = [
        AudioStream(
            index=_safe_int(s.get("index"), 0),
            codec_name=str(s.get("codec_name") or ""),
            channels=_safe_int_or_none(s.get("channels")),
            sample_rate=_safe_int_or_none(s.get("sample_rate")),
        )
        for s in streams_info
        if s.get("codec_type") == "audio"
    ]

    # Fallback to stream duration if format duration is missing / 0
    if duration <= 0.0:
        for s in streams_info:
            stream_dur = _safe_float(s.get("duration"), 0.0)
            if stream_dur > 0.0:
                duration = stream_dur
                break

    return MediaMetadata(
        duration=duration,
        bit_rate=bit_rate,
        format_name=file_format,
        mime_type=get_mimetype_mapping(file_format),
        audio_streams=audio_streams,
    )


def convert_to_opus(
    input_file: str | Path,
    output_file: str | Path | None = None,
    bitrate: str = "16k",
    sr: str | int = 16000,
    use_voip: bool = True,
    timeout_sec: float = 600,
    capture_stderr: bool = True,
) -> None:
    input_path = Path(input_file)
    output_path = Path(output_file) if output_file else input_path.with_suffix(".opus")
    sr = str(sr)

    extra_options: dict[str, str] = {
        "b:a": bitrate,
    }
    if use_voip:
        extra_options["application"] = "voip"

    process = (
        ffmpeg.input(str(input_path))
        .output(
            filename=str(output_path),
            acodec="libopus",
            ac=1,
            ar=sr,
            f="opus",
            extra_options=extra_options,
        )
        .overwrite_output()
        .run_async(
            pipe_stdout=True,
            pipe_stderr=capture_stderr,
            quiet=not capture_stderr,
        )
    )

    try:
        out, err = process.communicate(timeout=timeout_sec)
    except subprocess.TimeoutExpired as e:
        process.kill()
        process.communicate()
        raise RuntimeError(f"FFmpeg conversion timed out after {timeout_sec}s") from e
    except BaseException:
        process.kill()
        process.communicate()
        raise

    if process.returncode != 0:
        err_msg = err.decode("utf-8") if err else "Unknown FFmpeg error"
        raise RuntimeError(f"FFmpeg failed with error:\n{err_msg}")
