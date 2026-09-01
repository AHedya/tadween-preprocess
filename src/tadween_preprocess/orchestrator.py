"""
Reactor with Bounded Worker Offload: Core Orchestration Engine

===============================================================================
ARCHITECTURE & STATE MANAGEMENT OVERVIEW:
Pipes-and-Filters Pattern with Context Object (Message Envelope)
===============================================================================

1. Pipes-and-Filters Pipeline Flow:
    - The orchestration engine executes a Pipes-and-Filters architecture over an async event loop:
        Envelope[LocationConfig] -> [Source] -> Envelope[SourceResult] -> [Processor] -> Envelope[ProcessResult] -> [Sink] -> Completed
    - Filters are decoupled hexagonal adapters conforming to domain protocols (Source, Processor, Sink).
    - Each stage invokes `envelope.advance(payload)`, advancing the message payload type
        across filter boundaries while preserving immutable envelope context.

2. Controlled In-Place Mutations (OOP State & Inspection Tracking):
    While the payload advances, the metadata inside the envelope is
    mutated in-place. This allows the orchestration layer to track progress centrally:
    - `envelope.state`: Lifecycle status transitions (`pending` -> `flagged` / `failed` / `completed`).
    - `envelope.insp`: Measurement recordings populated dynamically (e.g., FFprobe data).
    - `envelope.artifacts`: Centralized registration of filesystem paths for guaranteed cleanup.
    All envelopes refer to the same instance but the payload, we are explicit about the payload as variable name and type-checker (Explicit is better than implicit)

3. Concurrency Gating & Resource Lifecycle:
    - Bounded Concurrency: `AsyncResourceSemaphore` strictly regulates I/O download/upload slots,
        physical CPU cores, RAM limits, and dynamic ephemeral disk budget tickets.
    - Self-Contained Cleanup: In `process_envelope`'s `finally` block, `cleanup(envelope)`
        unlinks temporary download files and symlinks (leaving original local sources intact)
        and releases dynamic disk budget tickets unconditionally.
    - Distributed Telemetry: Dynamic OpenTelemetry spans (`{SERVICE_NAME}.{adapter_name}`) and
        metrics counters (`items`, `batches`, `webhook_failures`).
===============================================================================
"""

import asyncio
import concurrent.futures
import logging
from collections.abc import Coroutine
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from opentelemetry import metrics
from resource_semaphore import AsyncResourceSemaphore

from tadween_preprocess.adapters.processor import MediaProcessor
from tadween_preprocess.adapters.runner import run_adapter
from tadween_preprocess.adapters.sink import CompositeSink
from tadween_preprocess.adapters.source import CompositeSource
from tadween_preprocess.config import (
    get_cpu_workers,
    get_disk_budget_bytes,
    get_disk_multiplier,
    get_download_workers,
    get_ram_budget_bytes,
    get_ram_per_cpu_bytes,
    get_service_name,
    get_upload_workers,
)
from tadween_preprocess.core.models import (
    Envelope,
    ItemInspection,
    ItemState,
    LocationConfig,
)
from tadween_preprocess.core.ports import PipelineRunner, Processor, Sink, Source
from tadween_preprocess.models import (
    PreprocessItem,
    PreprocessItemResult,
    PreprocessJobRequest,
)

from .adapters.utils import cleanup_envelope

logger = logging.getLogger(__name__)
meter = metrics.get_meter(__name__)

items_counter = meter.create_counter(
    name=f"{get_service_name()}.items",
    description="number of items processed",
)
batch_counter = meter.create_counter(
    name=f"{get_service_name()}.batches",
    description="number of batches processed",
)
webhook_failure_counter = meter.create_counter(
    name=f"{get_service_name()}.webhook_failures",
    description="number of failed webhook notifications",
)


def _run_coroutine_sync[T](coro: Coroutine[Any, Any, T]) -> T:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    if not loop.is_running():
        return loop.run_until_complete(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def _cleanup_and_release(
    envelope: Envelope[Any],
    disk_ticket: Any,
    rm: AsyncResourceSemaphore,
) -> None:
    try:
        await cleanup_envelope(envelope)
    finally:
        if disk_ticket is not None:
            await rm.release(disk_ticket)


async def process_envelope(
    envelope: Envelope[LocationConfig],
    source: Source,
    processor: Processor,
    sink: Sink,
    rm: AsyncResourceSemaphore,
    temp_dir: Path,
) -> Envelope:
    """
    Executes the linear pipeline lifecycle for a single item envelope.

    Side Effects:
    - In-place mutation of `envelope.state` (flags/fails on error).
    - In-place registration of filesystem paths on `envelope.artifacts`.
    - Dynamic disk reservation and concurrency slot claims via `rm`.
    - Guaranteed cleanup of materialized temporary files/symlinks in `finally`.
    """
    disk_ticket = None

    try:
        # 1. Acquire Source I/O slot (sets envelope.artifacts.raw_path)
        async with rm.claim({"download_slots": 1}):
            src_env = await run_adapter("source", source.get, envelope, temp_dir)
            if src_env.is_terminal:
                return src_env

        # 2. Claim Dynamic Disk Budget
        claimed_disk = int(src_env.payload.file_size_bytes * get_disk_multiplier())
        disk_ticket = await rm.acquire({"disk_bytes": claimed_disk})

        # 3. Acquire CPU / RAM & Process (FFprobe inspection & FFmpeg Opus transcode)
        async with rm.claim({"cpu_cores": 1, "ram_bytes": get_ram_per_cpu_bytes()}):
            proc_env = await run_adapter(
                "processor", processor.process, src_env, temp_dir
            )
            if proc_env.is_terminal:
                return proc_env

        # 4. Acquire Sink I/O slot & Publish
        async with rm.claim({"upload_slots": 1}):
            sink_env = await run_adapter("sink", sink.write, proc_env)
            if not sink_env.is_terminal:
                sink_env.state.status = "completed"
            return sink_env
    except ValueError as e:
        envelope.fail(f"resource_error:{e}", "resource_acquisition")
        return envelope
    finally:
        # Shielded cleanup and ticket release to guarantee zero leaks on task cancellation
        await asyncio.shield(_cleanup_and_release(envelope, disk_ticket, rm))


def create_envelope_from_item(
    item: PreprocessItem,
) -> Envelope[LocationConfig]:
    """
    Translates a public PreprocessItem DTO into an internal execution Envelope.
    Initializes clean ItemInspection, ItemState, and ItemArtifacts containers.
    """
    return Envelope(
        context=item.context,
        dist=item.sink,
        options=item.options,
        insp=ItemInspection(),
        state=ItemState(),
        payload=item.source,
    )


class Orchestrator(PipelineRunner):
    """
    Reactor with Bounded Worker Offload:
    Asynchronous event loop orchestrates concurrent per-item coroutines,
    while AsyncResourceSemaphore regulates I/O slots, disk capacity, and CPU/RAM offload.
    """

    def __init__(
        self,
        rm: AsyncResourceSemaphore | None = None,
        source: Source | None = None,
        processor: Processor | None = None,
        sink: Sink | None = None,
    ):
        self.rm = rm or AsyncResourceSemaphore(
            {
                "download_slots": get_download_workers(),
                "disk_bytes": get_disk_budget_bytes(),
                "cpu_cores": get_cpu_workers(),
                "ram_bytes": get_ram_budget_bytes(),
                "upload_slots": get_upload_workers(),
            }
        )
        self.source = source
        self.processor = processor
        self.sink = sink

    def execute(
        self, request: PreprocessJobRequest, temp_dir: Path
    ) -> dict[UUID, PreprocessItemResult]:
        """Synchronous entrypoint for non-async callers."""
        return _run_coroutine_sync(self.execute_async(request, temp_dir))

    async def execute_async(
        self, request: PreprocessJobRequest, temp_dir: Path
    ) -> dict[UUID, PreprocessItemResult]:
        """
        Asynchronously executes preprocessing for all items in a batch request.
        Translates DTOs -> Envelopes -> Pipeline Stages -> Results.
        """
        limits = httpx.Limits(
            max_connections=get_download_workers() + get_upload_workers(),
            max_keepalive_connections=20,
        )

        async with httpx.AsyncClient(limits=limits) as client:
            source = self.source or CompositeSource(client=client)
            processor = self.processor or MediaProcessor()
            sink = self.sink or CompositeSink(client=client)

            envelopes = [
                create_envelope_from_item(item) for item in request.batch.files.values()
            ]

            tasks = [
                process_envelope(env, source, processor, sink, self.rm, temp_dir)
                for env in envelopes
            ]

            finished_envelopes = await asyncio.gather(*tasks)

            results: dict[UUID, PreprocessItemResult] = {}
            for env in finished_envelopes:
                res = PreprocessItemResult(
                    status=env.state.status,  # type: ignore
                    true_duration_seconds=env.insp.true_duration_seconds,
                    true_size_bytes=env.insp.true_size_bytes,
                    error=env.state.error,
                    failed_step=env.state.failed_step,
                )
                results[env.context.file_id] = res
                items_counter.add(1, {"status": res.status})

            batch_counter.add(1, {"outcome": "success"})
            return results
