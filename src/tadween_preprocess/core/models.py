import uuid
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator


class HttpLocation(BaseModel):
    provider: Literal["http"] = "http"
    url: str
    method: Literal["GET", "POST", "PUT"] = "GET"
    headers: dict[str, str] | None = None
    fields: dict[str, str] | None = None
    timeout: float = 30.0


class S3Location(BaseModel):
    provider: Literal["s3"] = "s3"
    bucket: str
    key: str
    endpoint_url: str | None = None


class LocalLocation(BaseModel):
    provider: Literal["local"] = "local"
    file_path: Path


LocationConfig = Annotated[
    HttpLocation | S3Location | LocalLocation, Field(discriminator="provider")
]


class ItemContext(BaseModel):
    file_id: uuid.UUID
    og_uri: str | None = None


class ItemInspection(BaseModel):
    true_duration_seconds: int | float | None = None
    true_size_bytes: int | float | None = None


class ItemOptions(BaseModel):
    """Strictly defines HOW the file should be validated/processed."""

    require_duration: bool = True
    require_size: bool = True
    require_compression: bool = True
    acceptable_codecs: list[str] | None = None
    acceptable_containers: list[str] | None = None
    declared_duration_seconds: int | float | None = None
    declared_size_bytes: int | None = None
    tolerance_rate: float | None = None
    keep_raw: bool = False
    keep_converted: bool = False


class ItemState(BaseModel):
    status: Literal["pending", "completed", "failed", "flagged"] = "pending"
    error: str | None = None
    failed_step: str | None = None


class ItemArtifacts(BaseModel):
    """Encapsulates materialized files and their cleanup logic across pipeline stages."""

    raw_path: Path | None = None
    opus_path: Path | None = None
    is_temporary: bool = True


class Envelope[T](BaseModel):
    context: ItemContext
    dist: LocationConfig
    options: ItemOptions
    insp: ItemInspection = Field(default_factory=ItemInspection)
    state: ItemState = Field(default_factory=ItemState)
    artifacts: ItemArtifacts = Field(default_factory=ItemArtifacts)
    payload: T

    @property
    def is_terminal(self) -> bool:
        return self.state.status in ("completed", "failed", "flagged")

    def advance[R](self, payload: R) -> Envelope[R]:
        """Create a new instance carrying forward context, state, and artifacts."""
        return Envelope.model_construct(
            payload=payload,
            context=self.context,
            options=self.options,
            insp=self.insp,
            dist=self.dist,
            state=self.state,
            artifacts=self.artifacts,
        )

    def flag(self, error: str, failed_step: str) -> None:
        self.state = ItemState(status="flagged", error=error, failed_step=failed_step)

    def fail(self, error: str, failed_step: str) -> None:
        self.state = ItemState(status="failed", error=error, failed_step=failed_step)


class SourceResult(BaseModel):
    raw_path: Path
    file_size_bytes: int
    is_temporary: bool = True


class ProcessResult(BaseModel):
    upload_target: Path
    is_compressed: bool


class AudioStream(BaseModel):
    index: int
    codec_name: str
    channels: int | None = None
    sample_rate: int | None = None


class MediaMetadata(BaseModel):
    format_name: str
    duration: float = 0.0
    bit_rate: int = 0
    mime_type: str = "application/octet-stream"
    audio_streams: list[AudioStream] = Field(default_factory=list)

    @field_validator("format_name", mode="before")
    @classmethod
    def clean_format_name(cls, v: str) -> str:
        return v.split(",")[0].strip() if v else "unknown"
