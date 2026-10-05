from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_instrumented = False


def setup_telemetry(app) -> None:
    global _instrumented
    if _instrumented:
        return

    resource = Resource.create({"service.name": "agent-backend"})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint="http://localhost:4317", insecure=True)
        )
    )
    trace.set_tracer_provider(provider)

    # Входящие HTTP-запросы к FastAPI
    FastAPIInstrumentor.instrument_app(app)

    # Исходящие HTTP-запросы (Ollama, любые API)
    HTTPXClientInstrumentor().instrument()

    _instrumented = True


def enrich_current_span(**attrs) -> None:
    span = trace.get_current_span()
    if span.is_recording():
        for k, v in attrs.items():
            if v is not None:
                span.set_attribute(
                    k, v if isinstance(v, (int, float, bool)) else str(v)
                )    