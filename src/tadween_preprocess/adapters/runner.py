import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from opentelemetry import trace

from tadween_preprocess.config import get_service_name
from tadween_preprocess.core.models import Envelope

tracer = trace.get_tracer(__name__)
logger = logging.getLogger(__name__)


async def run_adapter[T, R](
    adapter_name: str,
    adapter_fn: Callable[..., Awaitable[Envelope[R]]],
    envelope: Envelope[T],
    *args: Any,
    retries: int = 0,
    retry_delay: float = 2.0,
    retry_exceptions: tuple[type[Exception], ...] | None = None,
    **kwargs: Any,
) -> Envelope[R]:
    """
    Executes an adapter stage:
    1. Short-circuits immediately if envelope.is_terminal.
    2. Instruments OpenTelemetry span `{SERVICE_NAME}.{adapter_name}`.
    3. Handles retries with exponential backoff on transient errors.
    4. Automatically records errors on envelope.
    """
    if envelope.is_terminal:
        return envelope  # type: ignore

    with tracer.start_as_current_span(f"{get_service_name()}.{adapter_name}") as span:
        span.set_attribute("adapter.name", adapter_name)
        span.set_attribute("file_id", str(envelope.context.file_id))

        err: Exception | None = None
        for attempt in range(1, retries + 2):
            try:
                span.set_attribute("adapter.attempt", attempt)
                result_env = await adapter_fn(envelope, *args, **kwargs)
                return result_env
            except Exception as e:
                err = e
                span.add_event(
                    "adapter_failed_attempt",
                    {"attempt": attempt, "error": str(e)},
                )
                if retry_exceptions is not None and not isinstance(e, retry_exceptions):
                    break
                if attempt <= retries:
                    await asyncio.sleep(retry_delay)

        envelope.fail(error=str(err), failed_step=adapter_name)
        if err is not None:
            span.record_exception(err)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(err)))
        return envelope  # type: ignore
