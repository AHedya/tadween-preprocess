from dataclasses import dataclass

from opentelemetry.sdk.metrics._internal.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


@dataclass
class TelemetryHandles:
    """Holds the in-memory OpenTelemetry test handles."""

    span_exporter: InMemorySpanExporter
    metric_reader: InMemoryMetricReader
