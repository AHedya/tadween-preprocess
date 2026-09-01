import logging

from _pytest.logging import LogCaptureFixture
from _pytest.monkeypatch import MonkeyPatch
from opentelemetry import metrics, propagate, trace

from tadween_preprocess.config import get_service_name
from tadween_preprocess.core import telemetry
from tests.conftest import reset_telemetry_for_testing
from tests.utils import TelemetryHandles


def test_init_telemetry_in_test_mode_starts_with_empty_spans_and_metrics(
    telemetry_handles: TelemetryHandles,
):
    assert telemetry_handles.span_exporter.get_finished_spans() == ()


def test_spans_are_captured_in_memory(telemetry_handles: TelemetryHandles):
    tracer = trace.get_tracer(__name__)

    with tracer.start_as_current_span("do-work") as span:
        span.set_attribute("worker.id", "abc123")

    finished = telemetry_handles.span_exporter.get_finished_spans()
    assert len(finished) == 1
    assert finished[0].name == "do-work"
    assert finished[0].attributes is not None
    assert finished[0].attributes["worker.id"] == "abc123"


def test_metrics_are_captured_in_memory(telemetry_handles: TelemetryHandles):
    meter = metrics.get_meter(__name__)
    counter = meter.create_counter("jobs.processed")

    counter.add(1, {"status": "ok"})

    data = telemetry_handles.metric_reader.get_metrics_data()
    assert data is not None

    metric_names = {
        metric.name
        for resource_metrics in data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
    }
    assert "jobs.processed" in metric_names


def test_force_flush_is_noop_in_test_mode(telemetry_handles: TelemetryHandles):
    # SimpleSpanProcessor exports synchronously, so flushing after init
    # should just succeed without raising.
    telemetry.force_flush(timeout_ms=1000)


def test_init_telemetry_is_idempotent_when_called_multiple_times(
    monkeypatch: MonkeyPatch,
):
    monkeypatch.setenv("ENVIRONMENT", "test")

    telemetry.init_telemetry(service_name="svc-a")
    provider_after_first = trace.get_tracer_provider()

    telemetry.init_telemetry(service_name="svc-b")
    provider_after_second = trace.get_tracer_provider()

    assert provider_after_first is provider_after_second


def test_extract_telemetry_context_with_empty_carrier_returns_empty_context():
    assert telemetry.extract_telemetry_context(None) == telemetry.Context()
    assert telemetry.extract_telemetry_context({}) == telemetry.Context()


def test_extract_telemetry_context_roundtrip_restores_valid_span_context():
    tracer = trace.get_tracer(__name__)
    carrier: dict[str, str] = {}

    with tracer.start_as_current_span("producer"):
        propagate.inject(carrier)

    assert "traceparent" in carrier

    ctx = telemetry.extract_telemetry_context(carrier)
    span_context = trace.get_current_span(ctx).get_span_context()
    assert span_context.is_valid


def test_init_telemetry_in_prod_without_otlp_endpoint_skips_initialization(
    monkeypatch: MonkeyPatch, caplog: LogCaptureFixture
):
    reset_telemetry_for_testing()
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

    with caplog.at_level(logging.WARNING, logger="tadween_preprocess.core.telemetry"):
        telemetry.init_telemetry(service_name="svc")

    assert "NOT initialized" in caplog.text
    assert telemetry._test_handles.span_exporter is None


def test_force_flush_without_initialization_logs_warning(caplog: LogCaptureFixture):
    reset_telemetry_for_testing()

    with caplog.at_level(logging.WARNING, logger="tadween_preprocess.core.telemetry"):
        telemetry.force_flush()

    assert (
        "not initialized" in caplog.text.lower() or "no provider" in caplog.text.lower()
    )


def test_init_telemetry_in_production_configures_providers(monkeypatch: MonkeyPatch):
    reset_telemetry_for_testing()
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")

    telemetry.init_telemetry(service_name="prod-svc")

    assert trace.get_tracer_provider() is not None


def test_service_name_fallback_and_environment_override(monkeypatch: MonkeyPatch):
    monkeypatch.delenv("SERVICE_NAME", raising=False)
    assert get_service_name() == "tadween_preprocess"

    monkeypatch.setenv("SERVICE_NAME", "custom_preprocess_svc")
    assert get_service_name() == "custom_preprocess_svc"
