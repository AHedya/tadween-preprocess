import os
from pathlib import Path

import aiofiles.os  # type: ignore
import httpx

from tadween_preprocess.config import get_max_file_bytes
from tadween_preprocess.core.models import (
    Envelope,
    HttpLocation,
    LocalLocation,
    LocationConfig,
    SourceResult,
)
from tadween_preprocess.core.ports import Source

from ._http import download_file_stream


class HTTPSource(Source):
    def __init__(self, client: httpx.AsyncClient | None = None):
        self.client = client

    async def get(
        self, item: Envelope[LocationConfig], temp_dir: Path
    ) -> Envelope[SourceResult]:
        if not isinstance(item.payload, HttpLocation):
            item.fail(
                error=f"Expected HttpLocation, got {type(item.payload)}",
                failed_step="source",
            )
            return item  # type: ignore

        loc = item.payload
        http_dir = temp_dir / "http"
        dest_path = http_dir / f"{item.context.file_id}.raw"

        try:
            await aiofiles.os.makedirs(http_dir, exist_ok=True)
            written = await download_file_stream(
                get_url=loc.url,
                destination_path=dest_path,
                client=self.client,
                timeout=loc.timeout,
                max_bytes=get_max_file_bytes(),
            )
            item.artifacts.raw_path = dest_path
            item.artifacts.is_temporary = not getattr(item.options, "keep_raw", False)
            return item.advance(
                SourceResult(
                    raw_path=dest_path,
                    file_size_bytes=written,
                    is_temporary=item.artifacts.is_temporary,
                )
            )
        except Exception as e:
            item.fail(error=str(e), failed_step="source")
            return item  # type: ignore


class LocalSource(Source):
    async def get(
        self, item: Envelope[LocationConfig], temp_dir: Path
    ) -> Envelope[SourceResult]:
        if not isinstance(item.payload, LocalLocation):
            item.fail(
                error=f"Expected LocalLocation, got {type(item.payload)}",
                failed_step="source",
            )
            return item  # type: ignore

        loc: LocalLocation = item.payload
        src_path = Path(loc.file_path).resolve()

        if not await aiofiles.os.path.exists(src_path):
            item.fail(error=f"Local file not found: {src_path}", failed_step="source")
            return item  # type: ignore

        # Symlink into temp_dir/local to align with pipeline directory conventions without copying
        local_dir = temp_dir / "local"
        await aiofiles.os.makedirs(local_dir, exist_ok=True)
        symlink_dest = local_dir / f"{item.context.file_id}{src_path.suffix}"
        try:
            if await aiofiles.os.path.exists(
                symlink_dest
            ) or await aiofiles.os.path.islink(symlink_dest):
                await aiofiles.os.remove(symlink_dest)
            os.symlink(src_path, symlink_dest)
            actual_path = symlink_dest
        except OSError:
            actual_path = src_path

        stat = await aiofiles.os.stat(src_path)
        item.artifacts.raw_path = actual_path
        item.artifacts.is_temporary = False  # DO NOT delete original local file!
        return item.advance(
            SourceResult(
                raw_path=actual_path,
                file_size_bytes=stat.st_size,
                is_temporary=False,
            )
        )


class CompositeSource(Source):
    def __init__(self, client: httpx.AsyncClient | None = None):
        self.http_source = HTTPSource(client=client)
        self.local_source = LocalSource()

    async def get(
        self, item: Envelope[LocationConfig], temp_dir: Path
    ) -> Envelope[SourceResult]:
        if isinstance(item.payload, HttpLocation):
            return await self.http_source.get(item, temp_dir)
        elif isinstance(item.payload, LocalLocation):
            return await self.local_source.get(item, temp_dir)
        else:
            item.fail(
                error=f"Unsupported location provider: {item.payload.provider}",
                failed_step="source",
            )
            return item  # type: ignore
