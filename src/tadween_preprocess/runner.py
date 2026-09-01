import logging
import shutil
import time
from pathlib import Path
from uuid import UUID

import requests
from opentelemetry import trace
from platformdirs import user_cache_dir

from tadween_preprocess.config import get_service_name
from tadween_preprocess.core.telemetry import extract_telemetry_context
from tadween_preprocess.models import (
    PreprocessItemResult,
    PreprocessJobRequest,
    PreprocessWebhookPayload,
    WebhookConfig,
)
from tadween_preprocess.orchestrator import (
    Orchestrator,
    batch_counter,
    webhook_failure_counter,
)

tracer = trace.get_tracer(__name__)
logger = logging.getLogger(__name__)


def notify_webhook(webhook: WebhookConfig, payload: dict) -> None:
    with tracer.start_as_current_span(f"{get_service_name()}.webhook_notify") as span:
        span.set_attribute("webhook.max_retries", webhook.max_retries)

        for attempt in range(1, webhook.max_retries + 1):
            try:
                resp = requests.post(
                    webhook.url,
                    json=payload,
                    headers={"Authorization": f"Bearer {webhook.token}"},
                    timeout=10,
                )
                resp.raise_for_status()
                return
            except Exception as e:
                span.add_event("webhook_retry", {"attempt": attempt, "error": str(e)})
                if attempt == webhook.max_retries:
                    webhook_failure_counter.add(1)
                    span.record_exception(e)
                    logger.error(
                        "Webhook notification failed after %d retries: %s",
                        webhook.max_retries,
                        e,
                    )
                else:
                    time.sleep(webhook.retry_delay_seconds * (2 ** (attempt - 1)))


def run(
    request: PreprocessJobRequest,
    cache_dir: str | Path | None = None,
    cleanup: bool = True,
    orchestrator: Orchestrator | None = None,
) -> dict[UUID, PreprocessItemResult]:
    """
    Main entrypoint for external handlers.
    Handles pre-flight (temp dir, telemetry, orchestrator default),
    dispatches to the orchestrator, posts the webhook, and cleans up.
    Returns the dictionary of per-file PreprocessItemResult objects.
    """
    if not request.webhook:
        logger.warning(
            "No webhook configuration provided. Task will complete silently."
        )

    batch_id = request.batch.id
    if cache_dir is None:
        base_dir = Path(
            user_cache_dir(appname="tadween_preprocess", ensure_exists=True)
        )
        cache_dir = base_dir
    else:
        cache_dir = Path(cache_dir)

    temp_dir = cache_dir / str(batch_id)
    temp_dir.mkdir(parents=True, exist_ok=True)

    if orchestrator is None:
        orchestrator = Orchestrator()

    ctx = extract_telemetry_context(request.telemetry_context)
    with tracer.start_as_current_span(
        f"{get_service_name()}.pipeline", context=ctx
    ) as span:
        span.set_attribute(f"{get_service_name()}.batch.id", str(batch_id))

        results: dict[UUID, PreprocessItemResult] = {}
        try:
            results = orchestrator.execute(request, temp_dir)
            webhook_payload = PreprocessWebhookPayload(job_id=batch_id, files=results)

            if request.webhook:
                notify_webhook(request.webhook, webhook_payload.model_dump(mode="json"))
        except Exception:
            batch_counter.add(1, {"outcome": "unhandled_error"})
            raise
        else:
            batch_counter.add(1, {"outcome": "success"})
        finally:
            if cleanup:
                try:
                    shutil.rmtree(temp_dir)
                    logger.info("Cleaned up temp directory: %s", temp_dir)
                except OSError as e:
                    span.add_event("cleanup_failed", {"error": str(e)})
                    logger.warning(
                        "Failed to clean up temp directory %s: %s",
                        temp_dir,
                        e,
                        exc_info=True,
                    )

    return results
