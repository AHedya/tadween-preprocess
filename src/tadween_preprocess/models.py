import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from .core.models import (
    HttpLocation,
    ItemContext,
    ItemOptions,
    LocalLocation,
    LocationConfig,
    S3Location,
)


class PreprocessItem(BaseModel):
    """
    Public API contract for a single file to be preprocessed.
    """

    context: ItemContext
    source: LocationConfig
    sink: LocationConfig
    options: ItemOptions = Field(default_factory=ItemOptions)


class WebhookConfig(BaseModel):
    url: str
    token: str
    max_retries: int = 3
    retry_delay_seconds: float = 1.5


class PreprocessBatch(BaseModel):
    id: Annotated[uuid.UUID, "job or batch id"]
    files: dict[uuid.UUID, PreprocessItem]


class PreprocessJobRequest(BaseModel):
    """
    The main request payload for the preprocessing pipeline.
    Represents a full 'job' containing multiple files.
    """

    batch: PreprocessBatch
    webhook: WebhookConfig | None = None
    telemetry_context: dict[str, str] | None = None


class PreprocessItemResult(BaseModel):
    """
    The result of preprocessing a single file.
    """

    status: Literal["completed", "failed", "flagged"]
    true_duration_seconds: int | float | None = None
    true_size_bytes: int | float | None = None
    error: str | None = None
    failed_step: str | None = None


class PreprocessWebhookPayload(BaseModel):
    """
    The payload sent back to the backend webhook upon job completion.
    """

    job_id: uuid.UUID
    files: dict[uuid.UUID, PreprocessItemResult]


__all__ = [
    "HttpLocation",
    "ItemContext",
    "ItemOptions",
    "LocalLocation",
    "LocationConfig",
    "PreprocessBatch",
    "PreprocessItem",
    "PreprocessItemResult",
    "PreprocessJobRequest",
    "PreprocessWebhookPayload",
    "S3Location",
    "WebhookConfig",
]
