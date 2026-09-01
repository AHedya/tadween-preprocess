import uuid
from pathlib import Path

import pytest

from tadween_preprocess.adapters.discovery import (
    create_batch_from_directory,
    scan_directory_for_media,
)
from tadween_preprocess.core.models import ItemOptions, LocalLocation


def test_scan_directory_for_media_flat_and_recursive(tmp_path: Path):
    (tmp_path / "song.mp3").write_bytes(b"mp3")
    (tmp_path / "voice.wav").write_bytes(b"wav")
    (tmp_path / "audio.opus").write_bytes(b"opus")
    (tmp_path / "document.pdf").write_bytes(b"pdf")
    (tmp_path / "notes.txt").write_bytes(b"txt")

    sub_dir = tmp_path / "sub"
    sub_dir.mkdir()
    (sub_dir / "nested.flac").write_bytes(b"flac")
    (sub_dir / "ignored.json").write_bytes(b"json")

    # Non-recursive scan
    flat_results = scan_directory_for_media(tmp_path, recursive=False)
    flat_names = [p.name for p in flat_results]
    assert "song.mp3" in flat_names
    assert "voice.wav" in flat_names
    assert "audio.opus" in flat_names
    assert "document.pdf" not in flat_names
    assert "notes.txt" not in flat_names
    assert "nested.flac" not in flat_names

    # Recursive scan
    rec_results = scan_directory_for_media(tmp_path, recursive=True)
    rec_names = [p.name for p in rec_results]
    assert "song.mp3" in rec_names
    assert "voice.wav" in rec_names
    assert "audio.opus" in rec_names
    assert "nested.flac" in rec_names
    assert "document.pdf" not in rec_names
    assert "ignored.json" not in rec_names


def test_scan_directory_with_custom_extensions_filters_matching_files(tmp_path: Path):
    (tmp_path / "a.mp3").write_bytes(b"mp3")
    (tmp_path / "b.wav").write_bytes(b"wav")
    (tmp_path / "c.opus").write_bytes(b"opus")

    res = scan_directory_for_media(tmp_path, extensions=["mp3", ".opus"])
    names = [p.name for p in res]
    assert names == ["a.mp3", "c.opus"]


def test_scan_non_existent_directory_raises_not_a_directory_error():
    with pytest.raises(NotADirectoryError):
        scan_directory_for_media("/path/that/definitely/does/not/exist/98765")


def test_create_batch_from_directory_generates_valid_batch_payload(tmp_path: Path):
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    (input_dir / "track1.mp3").write_bytes(b"1")
    (input_dir / "track2.wav").write_bytes(b"2")

    output_dir = tmp_path / "outputs"

    custom_options = ItemOptions(require_compression=True, require_duration=True)
    custom_batch_id = uuid.uuid4()

    batch = create_batch_from_directory(
        directory=input_dir,
        output_dir=output_dir,
        options=custom_options,
        batch_id=custom_batch_id,
    )

    assert batch.id == custom_batch_id
    assert len(batch.files) == 2

    for item in batch.files.values():
        assert isinstance(item.source, LocalLocation)
        assert isinstance(item.sink, LocalLocation)
        assert item.source.file_path.parent == input_dir
        assert item.sink.file_path.parent == output_dir.resolve()
        assert item.sink.file_path.suffix == ".opus"
        assert item.options.require_compression is True


def test_create_batch_from_directory_defaults_sink_to_same_folder_opus(tmp_path: Path):
    input_dir = tmp_path / "inputs"
    input_dir.mkdir()
    f1 = input_dir / "recording.m4a"
    f1.write_bytes(b"m4a")

    batch = create_batch_from_directory(directory=input_dir)
    assert len(batch.files) == 1

    item = list(batch.files.values())[0]
    assert isinstance(item.sink, LocalLocation)
    assert item.sink.file_path == f1.resolve().with_suffix(".opus")
