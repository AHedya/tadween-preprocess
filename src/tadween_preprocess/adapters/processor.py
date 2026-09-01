import asyncio
import logging
from pathlib import Path

from tadween_preprocess.core.models import (
    Envelope,
    MediaMetadata,
    ProcessResult,
    SourceResult,
)
from tadween_preprocess.core.ports import Processor

from ._ffmpeg import (
    convert_to_opus,
    get_media_metadata,
    is_compression_skippable,
)

logger = logging.getLogger(__name__)


class MediaProcessor(Processor):
    async def process(
        self, item: Envelope[SourceResult], temp_dir: Path
    ) -> Envelope[ProcessResult]:
        raw_path = item.payload.raw_path
        raw_size = item.payload.file_size_bytes
        opts = item.options
        insp = item.insp

        # 1. Record Downloaded Raw Size & Validate Drift (Anti-Spoofing Triangle)
        if opts.require_size:
            insp.true_size_bytes = raw_size

        if opts.declared_size_bytes is not None and opts.tolerance_rate is not None:
            drift = abs(raw_size - opts.declared_size_bytes) / opts.declared_size_bytes
            if drift > opts.tolerance_rate:
                item.flag("size_drift_exceeded", "validate_size")
                return item  # type: ignore

        # 2. Metadata Inspection via FFprobe (offloaded to thread)
        meta: MediaMetadata | None = None
        try:
            meta = await asyncio.to_thread(get_media_metadata, raw_path)
        except Exception as e:
            err_str = str(e)
            if (
                "FFprobe failed" in err_str
                or "invalid_media_type" in err_str
                or "Invalid data found" in err_str
            ):
                item.flag("invalid_media_type", "metadata")
                return item  # type: ignore
            else:
                item.fail(error=err_str, failed_step="metadata")
                return item  # type: ignore

        if opts.require_duration and meta:
            insp.true_duration_seconds = meta.duration

        # 3. Duration Validation (Declared Drift)
        if (
            opts.declared_duration_seconds is not None
            and opts.tolerance_rate is not None
            and meta is not None
        ):
            duration_drift = (
                abs(meta.duration - opts.declared_duration_seconds)
                / opts.declared_duration_seconds
            )
            if duration_drift > opts.tolerance_rate:
                item.flag("duration_drift_exceeded", "validate_duration")
                return item  # type: ignore

        # 4. Compression (or Zero-Copy Skip)
        upload_target: Path = raw_path
        is_compressed = False

        if opts.require_compression:
            if meta and not meta.audio_streams:
                item.flag("no_audio_stream", "metadata")
                return item  # type: ignore

            if meta and is_compression_skippable(
                meta,
                acceptable_codecs=opts.acceptable_codecs,
                acceptable_containers=opts.acceptable_containers,
            ):
                logger.info(
                    "File %s already encoded with acceptable codec/container (%s). Skipping FFmpeg compression.",
                    item.context.file_id,
                    meta.format_name,
                )
                upload_target = raw_path
                is_compressed = False
            else:
                opus_dir = temp_dir / "opus"
                opus_dir.mkdir(parents=True, exist_ok=True)
                opus_path = opus_dir / f"{item.context.file_id}.opus"
                try:
                    await asyncio.to_thread(
                        convert_to_opus,
                        input_file=raw_path,
                        output_file=opus_path,
                    )
                    upload_target = opus_path
                    is_compressed = True
                    item.artifacts.opus_path = opus_path
                except Exception as e:
                    item.fail(error=str(e), failed_step="compress")
                    return item  # type: ignore

        return item.advance(
            ProcessResult(upload_target=upload_target, is_compressed=is_compressed)
        )
