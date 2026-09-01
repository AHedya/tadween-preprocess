import uuid
from collections.abc import Sequence
from pathlib import Path

from tadween_preprocess.adapters._mime_map import FFPROBE_MIME_MAP
from tadween_preprocess.core.models import ItemContext, ItemOptions, LocalLocation
from tadween_preprocess.models import PreprocessBatch, PreprocessItem

SUPPORTED_MEDIA_EXTENSIONS = {
    f".{ext.strip().lower()}"
    for k in FFPROBE_MIME_MAP
    for ext in k.split(",")
    if ext.strip()
}


def scan_directory_for_media(
    directory: str | Path,
    extensions: Sequence[str] | None = None,
    recursive: bool = False,
) -> list[Path]:
    """
    Scans a directory for audio and media files matching the given extensions.
    Defaults to all supported extensions from FFPROBE_MIME_MAP.
    """
    dir_path = Path(directory).resolve()
    if not dir_path.is_dir():
        raise NotADirectoryError(f"Directory not found or not a directory: {dir_path}")

    valid_exts = (
        {ext if ext.startswith(".") else f".{ext.lower()}" for ext in extensions}
        if extensions is not None
        else SUPPORTED_MEDIA_EXTENSIONS
    )

    pattern = "**/*" if recursive else "*"
    found_files: list[Path] = []
    for file_path in dir_path.glob(pattern):
        if file_path.is_file() and file_path.suffix.lower() in valid_exts:
            found_files.append(file_path)

    found_files.sort()
    return found_files


def create_batch_from_directory(
    directory: str | Path,
    output_dir: str | Path | None = None,
    extensions: Sequence[str] | None = None,
    recursive: bool = False,
    options: ItemOptions | None = None,
    batch_id: uuid.UUID | None = None,
) -> PreprocessBatch:
    """
    Constructs a PreprocessBatch from all media files found in a local directory.

    If `output_dir` is specified, each item's sink will be a LocalLocation pointing to
    `output_dir / f"{file_path.stem}.opus"`.
    If `output_dir` is not specified, sink defaults to `file_path.with_suffix(".opus")`.
    """
    media_files = scan_directory_for_media(
        directory=directory,
        extensions=extensions,
        recursive=recursive,
    )

    out_dir = Path(output_dir).resolve() if output_dir else None
    item_opts = options or ItemOptions()
    batch_uuid = batch_id or uuid.uuid4()

    files: dict[uuid.UUID, PreprocessItem] = {}
    for file_path in media_files:
        file_id = uuid.uuid4()
        if out_dir:
            sink_path = out_dir / f"{file_path.stem}.opus"
        else:
            sink_path = file_path.with_suffix(".opus")

        files[file_id] = PreprocessItem(
            context=ItemContext(file_id=file_id, filename=file_path.name),
            source=LocalLocation(file_path=file_path),
            sink=LocalLocation(file_path=sink_path),
            options=item_opts,
        )

    return PreprocessBatch(id=batch_uuid, files=files)
