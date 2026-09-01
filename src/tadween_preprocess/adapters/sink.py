import shutil
from pathlib import Path

import aiofiles.os  # type: ignore
import httpx

from tadween_preprocess.adapters._http import upload_file_stream
from tadween_preprocess.core.models import (
    Envelope,
    HttpLocation,
    LocalLocation,
    ProcessResult,
)
from tadween_preprocess.core.ports import Sink


class HTTPSink(Sink):
    def __init__(self, client: httpx.AsyncClient | None = None):
        self.client = client

    async def write(self, item: Envelope[ProcessResult]) -> Envelope[ProcessResult]:
        if not isinstance(item.dist, HttpLocation):
            item.fail(
                error=f"Expected HttpLocation, got {type(item.dist)}",
                failed_step="sink",
            )
            return item

        loc: HttpLocation = item.dist
        upload_path = item.payload.upload_target

        try:
            await upload_file_stream(
                url=loc.url,
                file_path=upload_path,
                method=loc.method if loc.method in ("PUT", "POST") else "PUT",
                headers=loc.headers,
                fields=loc.fields,
                client=self.client,
                timeout=loc.timeout,
            )
            return item
        except Exception as e:
            item.fail(error=str(e), failed_step="sink")
            return item


class LocalSink(Sink):
    async def write(self, item: Envelope[ProcessResult]) -> Envelope[ProcessResult]:
        if not isinstance(item.dist, LocalLocation):
            item.fail(
                error=f"Expected LocalLocation, got {type(item.dist)}",
                failed_step="sink",
            )
            return item

        loc: LocalLocation = item.dist
        dest_path = Path(loc.file_path).resolve()
        upload_path = item.payload.upload_target

        try:
            await aiofiles.os.makedirs(dest_path.parent, exist_ok=True)
            shutil.copyfile(upload_path, dest_path)
            return item
        except Exception as e:
            item.fail(error=str(e), failed_step="sink")
            return item


class CompositeSink(Sink):
    def __init__(self, client: httpx.AsyncClient | None = None):
        self.http_sink = HTTPSink(client=client)
        self.local_sink = LocalSink()

    async def write(self, item: Envelope[ProcessResult]) -> Envelope[ProcessResult]:
        provider = getattr(item.dist, "provider", None)
        if provider == "http":
            return await self.http_sink.write(item)
        elif provider == "local":
            return await self.local_sink.write(item)
        else:
            item.fail(
                error=f"Unsupported sink provider: {provider}",
                failed_step="sink",
            )
            return item
