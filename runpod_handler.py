import os

from tadween_preprocess.core.telemetry import force_flush, init_telemetry

if (os.environ.get("TELEMETRY_ENABLED") or "").strip().lower() in (
    "1",
    "true",
    "yes",
):
    init_telemetry(
        service_name=os.environ.get("SERVICE_NAME"),
        environment=os.environ.get("ENVIRONMENT"),
    )

import logging

import runpod

from tadween_preprocess.models import PreprocessJobRequest
from tadween_preprocess.runner import run

logger = logging.getLogger(__name__)


def handler(event: dict):
    try:
        runpod_req = PreprocessJobRequest.model_validate(event.get("input", {}))
    except Exception as e:
        logger.warning(f"Invalid payload: {e}")
        return {"status": "error", "message": f"Invalid payload: {e}"}

    try:
        results = run(runpod_req)
        return {
            "status": "ok",
            "job_id": str(runpod_req.batch.id),
            "files": {
                str(file_id): res.model_dump(mode="json")
                for file_id, res in results.items()
            },
        }
    except Exception:
        logger.exception("Pipeline execution failed unexpectedly")
        raise
    finally:
        force_flush()


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
