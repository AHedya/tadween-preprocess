import logging
import os
from dataclasses import dataclass
from typing import cast

from opentelemetry import metrics, propagate, trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    InMemoryMetricReader,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from tadween_preprocess.config import get_service_name

logger = logging.getLogger(__name__)

_TEST_ENVIRONMENTS = {"test", "testing"}


def init_telemetry(
    service_name: str | None = None, environment: str | None = None
) -> None:
    """
    Initializes the OpenTelemetry SDK to export spans and metrics to an OTLP endpoint.

    This should be called ONCE at the start of the worker.
    Calling it again after a provider is already installed is a no-op.

    `environment` sets the `deployment.environment` resource attribute. If not
    passed explicitly, it falls back to the ENVIRONMENT env var. When it
    resolves to "test" or "testing", spans and metrics are captured in-memory
    instead of exported over OTLP, and no OTLP endpoint is required. Use
    `get_test_span_exporter()` / `get_test_metric_reader()` in tests to
    inspect what was captured.
    """
    if isinstance(trace.get_tracer_provider(), TracerProvider):
        return

    environment = environment or os.environ.get("ENVIRONMENT")
    test_mode = _is_test_environment(environment)

    svc_name = service_name or get_service_name()
    attributes = {"service.name": svc_name}
    if environment and (env := environment.strip()):
        attributes["deployment.environment"] = env
    resource = Resource.create(attributes=attributes)

    trace_provider = TracerProvider(resource=resource)
    meter_provider = MeterProvider(resource=resource)

    if test_mode:
        metric_reader = _init_test_mode(trace_provider)
    else:
        metric_reader = _init_otlp_mode(trace_provider)

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[metric_reader] if metric_reader else [],
    )

    trace.set_tracer_provider(trace_provider)
    metrics.set_meter_provider(meter_provider)


def _init_test_mode(trace_provider: TracerProvider):
    _test_handles.span_exporter = InMemorySpanExporter()
    _test_handles.metric_reader = InMemoryMetricReader()

    trace_provider.add_span_processor(SimpleSpanProcessor(_test_handles.span_exporter))

    logger.info(
        "Telemetry initialized in TEST mode (in-memory exporters, no OTLP endpoint)."
    )
    return _test_handles.metric_reader


def _init_otlp_mode(trace_provider: TracerProvider):
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        logger.warning(
            "OTEL_EXPORTER_OTLP_ENDPOINT not found in env. Telemetry NOT initialized."
        )
        return None

    secure = endpoint.startswith("https")
    headers = _parse_otlp_headers(os.environ.get("OTEL_EXPORTER_OTLP_HEADERS"))
    redacted_auth = _redact_auth_header(headers.get("Authorization", ""))

    logger.info(
        f"Telemetry initialized. endpoint={endpoint} secure={secure} auth={redacted_auth}"
    )

    span_exporter = OTLPSpanExporter(
        endpoint=endpoint, insecure=not secure, headers=headers or None
    )
    trace_provider.add_span_processor(BatchSpanProcessor(span_exporter))

    metric_exporter = OTLPMetricExporter(
        endpoint=endpoint, insecure=not secure, headers=headers or None
    )
    return PeriodicExportingMetricReader(metric_exporter)


@dataclass
class _TestTelemetryHandles:
    """Holds the in-memory exporter/reader created when init_telemetry() runs in test mode."""

    span_exporter: InMemorySpanExporter | None = None
    metric_reader: InMemoryMetricReader | None = None


_test_handles = _TestTelemetryHandles()


def extract_telemetry_context(carrier: dict[str, str] | None) -> Context:
    """
    Extracts OpenTelemetry trace context from the given carrier dict (usually from request body).
    This allows the serverless handler to join the parent trace initiated by the backend.
    """
    if not carrier:
        return Context()

    return propagate.extract(carrier)


def _parse_otlp_headers(headers_str: str | None) -> dict[str, str]:
    """Parses the `key1=value1,key2=value2` format used by OTEL_EXPORTER_OTLP_HEADERS."""
    headers: dict[str, str] = {}
    if not headers_str:
        return headers

    for item in headers_str.split(","):
        if "=" in item:
            key, value = item.split("=", 1)
            headers[key.strip()] = value.strip()
    return headers


def _redact_auth_header(auth_val: str) -> str:
    """Returns a redacted version of an auth header value, safe to log."""
    if not auth_val:
        return "None"

    if auth_val.startswith("Bearer "):
        token = auth_val[len("Bearer ") :]
        return f"Bearer {token[:4]}...{token[-4:]}" if len(token) > 8 else "Bearer ***"

    return f"{auth_val[:4]}..." if len(auth_val) > 4 else "***"


def _is_test_environment(environment: str | None) -> bool:
    return bool(environment) and environment.strip().lower() in _TEST_ENVIRONMENTS


def force_flush(timeout_ms: int = 5000) -> None:
    """Flushes any pending spans/metrics. Safe to call even if telemetry was never initialized."""
    tracer_provider = trace.get_tracer_provider()
    if hasattr(tracer_provider, "force_flush"):
        trace_flushed = cast(TracerProvider, tracer_provider).force_flush(
            timeout_millis=timeout_ms
        )
        if not trace_flushed:
            logger.warning("Trace export did not complete within timeout")
    else:
        logger.warning("Trace is not initialized; nothing to flush.")

    meter_provider = metrics.get_meter_provider()
    if hasattr(meter_provider, "force_flush"):
        metrics_flushed = cast(MeterProvider, meter_provider).force_flush(
            timeout_millis=timeout_ms
        )
        if not metrics_flushed:
            logger.warning("Metrics export did not complete within timeout")
    else:
        logger.warning("Metrics is not initialized; nothing to flush.")
