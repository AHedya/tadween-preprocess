import os
import uuid
from pathlib import Path
from unittest.mock import patch

from tadween_preprocess.adapters.utils import cleanup_envelope
from tadween_preprocess.core.models import (
    Envelope,
    HttpLocation,
    ItemArtifacts,
    ItemContext,
    ItemInspection,
    ItemOptions,
    ItemState,
    LocalLocation,
)


def _make_envelope(
    raw_path: Path | None = None,
    opus_path: Path | None = None,
    is_temporary: bool = True,
    keep_raw: bool = False,
    keep_converted: bool = False,
) -> Envelope:
    return Envelope(
        context=ItemContext(file_id=uuid.uuid4(), filename="test.mp3"),
        dist=HttpLocation(url="http://example.com/put", method="PUT"),
        options=ItemOptions(keep_raw=keep_raw, keep_converted=keep_converted),
        insp=ItemInspection(),
        state=ItemState(),
        artifacts=ItemArtifacts(
            raw_path=raw_path,
            opus_path=opus_path,
            is_temporary=is_temporary,
        ),
        payload=LocalLocation(file_path=Path("/dummy")),
    )


async def test_cleanup_deletes_raw_and_opus(tmp_path: Path):
    raw = tmp_path / "input.raw"
    raw.write_bytes(b"sample raw bytes")
    opus = tmp_path / "output.opus"
    opus.write_bytes(b"sample opus bytes")

    env = _make_envelope(raw_path=raw, opus_path=opus, is_temporary=True)
    await cleanup_envelope(env)

    assert not raw.exists()
    assert not opus.exists()


async def test_cleanup_preserves_non_temporary_raw(tmp_path: Path):
    raw = tmp_path / "original_user_file.mp3"
    raw.write_bytes(b"original contents")
    opus = tmp_path / "output.opus"
    opus.write_bytes(b"converted contents")

    env = _make_envelope(raw_path=raw, opus_path=opus, is_temporary=False)
    await cleanup_envelope(env)

    # Raw file must NOT be deleted
    assert raw.exists()
    # Opus file must be deleted
    assert not opus.exists()


async def test_cleanup_removes_symlink_without_touching_target(tmp_path: Path):
    target = tmp_path / "real_file.wav"
    target.write_bytes(b"real audio")
    link = tmp_path / "symlink.wav"
    os.symlink(target, link)

    env = _make_envelope(raw_path=link, is_temporary=False)
    await cleanup_envelope(env)

    # Symlink must be removed
    assert not link.exists()
    # Target file must be intact
    assert target.exists()


async def test_cleanup_removes_broken_symlink(tmp_path: Path):
    non_existent = tmp_path / "ghost.wav"
    broken_link = tmp_path / "broken_link.wav"
    os.symlink(non_existent, broken_link)

    assert os.path.islink(broken_link)
    assert not broken_link.exists()

    env = _make_envelope(raw_path=broken_link, is_temporary=True)
    await cleanup_envelope(env)

    assert not os.path.islink(broken_link)


async def test_cleanup_respects_keep_raw_and_keep_converted(tmp_path: Path):
    raw = tmp_path / "downloaded.raw"
    raw.write_bytes(b"raw bytes")
    opus = tmp_path / "converted.opus"
    opus.write_bytes(b"opus bytes")

    env = _make_envelope(
        raw_path=raw,
        opus_path=opus,
        is_temporary=True,
        keep_raw=True,
        keep_converted=True,
    )
    await cleanup_envelope(env)

    assert raw.exists()
    assert opus.exists()


async def test_cleanup_handles_missing_and_none_paths():
    env = _make_envelope(raw_path=None, opus_path=None)
    # Should run cleanly without error
    await cleanup_envelope(env)

    ghost_raw = Path("/tmp/definitely_does_not_exist_12345.raw")
    ghost_opus = Path("/tmp/definitely_does_not_exist_12345.opus")
    env2 = _make_envelope(raw_path=ghost_raw, opus_path=ghost_opus)
    await cleanup_envelope(env2)


async def test_cleanup_handles_oserror_gracefully(tmp_path: Path):
    raw = tmp_path / "raw.raw"
    opus = tmp_path / "opus.opus"
    raw.write_bytes(b"raw")
    opus.write_bytes(b"opus")

    env = _make_envelope(raw_path=raw, opus_path=opus, is_temporary=True)

    with patch("aiofiles.os.unlink", side_effect=OSError("Disk busy")):
        await cleanup_envelope(env)
