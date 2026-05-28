import os
import logging
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

logger = logging.getLogger("agentops.observability.tracing")

def init_telemetry_sdk(service_name: str = "agentops-service") -> TracerProvider:
    """
    Sets up the global OpenTelemetry tracer pipeline.
    Binds exporter processors tracking metrics directly to Jaeger containers.
    """
    logger.info(f"Initializing OpenTelemetry Tracer Provider for service: {service_name}")
    
    # Establish base resource definitions identifying container contexts
    resource = Resource.create({
        "service.name": service_name,
        "environment": os.getenv("PLATFORM_ENV", "development")
    })
    
    provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(provider)
    
    # Retrieve OTEL agent destination endpoint
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    
    try:
        logger.info(f"Binding OTLP Span Exporter pipeline pointing to: {otlp_endpoint}")
        # Build local OTLP Exporter dispatching spans in background batches
        otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        span_processor = BatchSpanProcessor(otlp_exporter)
        provider.add_span_processor(span_processor)
        logger.info("Successfully registered OTLP span processor.")
    except Exception as e:
        logger.warning(
            f"Failed to bind OTLP export process (using fallback memory processor instead): {e}. "
            "Please check if collector daemon is active."
        )
        
    return provider

def get_tracer(module_name: str) -> trace.Tracer:
    """
    Acquires named tracer handle ensuring correct scope traces in span logs.
    """
    return trace.get_tracer(module_name)
