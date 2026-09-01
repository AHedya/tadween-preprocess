from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from resource_semaphore import AsyncResourceSemaphore

from .models import Envelope, LocationConfig, ProcessResult, SourceResult

if TYPE_CHECKING:
    from tadween_preprocess.models import (
        PreprocessItemResult,
        PreprocessJobRequest,
    )


class Source(Protocol):
    async def get(
        self, item: Envelope[LocationConfig], temp_dir: Path
    ) -> Envelope[SourceResult]: ...


class Processor(Protocol):
    async def process(
        self, item: Envelope[SourceResult], temp_dir: Path
    ) -> Envelope[ProcessResult]: ...


class Sink(Protocol):
    async def write(self, item: Envelope[ProcessResult]) -> Envelope[ProcessResult]: ...


class PipelineRunner(Protocol):
    rm: AsyncResourceSemaphore

    def execute(
        self, request: PreprocessJobRequest, temp_dir: Path
    ) -> dict[UUID, PreprocessItemResult]: ...

    async def execute_async(
        self, request: PreprocessJobRequest, temp_dir: Path
    ) -> dict[UUID, PreprocessItemResult]: ...
