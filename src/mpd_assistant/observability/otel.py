"""OpenTelemetry setup with attribute scrubbing so traces never carry secrets or personal data."""

import os
from typing import Any, Dict

from mpd_assistant.core.logging import scrub
from mpd_assistant.privacy.detector import redact


def scrub_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact(scrub(value))
    if isinstance(value, list | tuple):
        return type(value)(scrub_value(v) for v in value)
    return value


def scrub_attributes(attributes: Dict[str, Any]) -> Dict[str, Any]:
    return {k: scrub_value(v) for k, v in attributes.items()}


def setup_tracing(service_name: str) -> bool:
    """Configure OTLP export if an endpoint is set. Returns whether tracing was enabled."""
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return False
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")))
    trace.set_tracer_provider(provider)
    return True


def traced_attributes(**attributes: Any) -> Dict[str, Any]:
    """Use when setting span attributes: scrubs first."""
    return scrub_attributes(attributes)
