import contextlib
import os
import tempfile
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

import aiofiles  # type: ignore
import aiofiles.os  # type: ignore
import httpx

CHUNK_SIZE = 65536


@asynccontextmanager
async def _client_scope(
    client: httpx.AsyncClient | None,
) -> AsyncGenerator[httpx.AsyncClient]:
    if client is not None:
        yield client
    else:
        async with httpx.AsyncClient() as c:
            yield c


async def download_file_stream(
    get_url: str,
    destination_path: str | Path,
    client: httpx.AsyncClient | None = None,
    timeout: int | float | httpx.Timeout = 30,
    max_bytes: int | None = None,
) -> int:
    """
    Download a file from a URL, streaming to a temporary file and atomically renaming.
    Returns total bytes written.
    """
    dest_path = Path(destination_path)
    dest_dir = dest_path.parent
    await aiofiles.os.makedirs(dest_dir, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=dest_dir, prefix=".dl-")
    os.close(fd)

    try:
        async with (
            _client_scope(client) as c,
            c.stream("GET", get_url, timeout=timeout) as resp,
        ):
            resp.raise_for_status()
            expected = _expected_total(resp, 0)
            written = await _stream_response_to_file(
                resp, tmp_path, max_bytes=max_bytes
            )

            if expected is not None and written != expected:
                raise httpx.StreamError(
                    f"Stream ended early: got {written} bytes, expected {expected}."
                )
        await aiofiles.os.replace(tmp_path, dest_path)
        return written
    finally:
        if await aiofiles.os.path.exists(tmp_path):
            with contextlib.suppress(OSError):
                await aiofiles.os.remove(tmp_path)


async def upload_file_stream(
    url: str,
    file_path: str | Path,
    method: Literal["POST", "PUT"] = "PUT",
    headers: dict[str, Any] | None = None,
    fields: dict[str, Any] | None = None,
    client: httpx.AsyncClient | None = None,
    timeout: int | float | httpx.Timeout = 30,
) -> None:
    path = Path(file_path)
    if not await aiofiles.os.path.exists(path):
        raise FileNotFoundError(f"Can't upload not found file: {path}")

    req_headers = dict(headers) if headers else {}
    async with _client_scope(client) as c:
        if method.upper() == "PUT":
            req_headers["Content-Length"] = str(await aiofiles.os.path.getsize(path))
            async with aiofiles.open(path, "rb") as fh:
                resp = await c.put(
                    url,
                    content=_file_chunk_reader(fh),
                    headers=req_headers,
                    timeout=timeout,
                )
        elif method.upper() == "POST":
            async with aiofiles.open(path, "rb") as fh:
                file_content = await fh.read()
                files = {"file": (path.name, file_content)}
                resp = await c.post(
                    url,
                    data=fields,
                    files=files,
                    headers=req_headers,
                    timeout=timeout,
                )
        else:
            raise ValueError("Unsupported method. Use 'PUT' or 'POST'.")

        resp.raise_for_status()


async def _stream_response_to_file(
    resp: httpx.Response,
    path: str | Path,
    max_bytes: int | None = None,
) -> int:
    downloaded_bytes = 0
    async with aiofiles.open(path, "wb") as fh:
        async for chunk in resp.aiter_bytes(chunk_size=CHUNK_SIZE):
            if chunk:
                await fh.write(chunk)
                downloaded_bytes += len(chunk)
                if max_bytes is not None and downloaded_bytes > max_bytes:
                    raise ValueError(
                        f"Download exceeded max allowed size ({max_bytes} bytes). "
                        f"Downloaded {downloaded_bytes} bytes so far. Aborting."
                    )
    return downloaded_bytes


async def _file_chunk_reader(
    file_handle: Any,
) -> AsyncIterator[bytes]:
    while True:
        chunk = await file_handle.read(CHUNK_SIZE)
        if not chunk:
            break
        yield chunk


def _expected_total(resp: httpx.Response, downloaded_bytes: int) -> int | None:
    content_length = resp.headers.get("Content-Length")
    if content_length is None:
        return None
    try:
        return downloaded_bytes + int(content_length)
    except ValueError:
        return None
