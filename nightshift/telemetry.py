"""Observability setup. Instrumentation is on by default in Agent Framework; this only chooses where the signal goes."""

from __future__ import annotations

import os
from typing import Any


async def configure_telemetry(mode: str, client: Any | None = None) -> None:
    """Configure OpenTelemetry exporters for one of: none, console, otlp, azure-monitor, foundry.

    'none' exports nothing. Measurement still works in every mode: `metrics.attach_span_counter` installs an
    in-process tracer provider when no exporter did.
    """
    mode = (mode or "none").lower()
    if mode == "none":
        return

    if mode == "azure-monitor":
        from agent_framework.observability import create_resource, enable_instrumentation
        from azure.monitor.opentelemetry import configure_azure_monitor

        connection_string = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
        if not connection_string:
            raise ValueError("NIGHTSHIFT_TELEMETRY=azure-monitor needs APPLICATIONINSIGHTS_CONNECTION_STRING.")
        configure_azure_monitor(connection_string=connection_string, resource=create_resource(), enable_live_metrics=False)
        enable_instrumentation()
        return

    if mode == "foundry":
        configure = getattr(client, "configure_azure_monitor", None)
        if configure is None:
            raise ValueError("NIGHTSHIFT_TELEMETRY=foundry requires the 'foundry' provider (FoundryChatClient).")
        # Reads the Application Insights connection string from the Foundry project. The client defaults
        # enable_sensitive_data to False and overrides the environment, so pass the setting through.
        sensitive = os.environ.get("ENABLE_SENSITIVE_DATA", "false").strip().lower() in ("1", "true", "yes")
        await configure(enable_sensitive_data=sensitive, enable_live_metrics=False)
        return

    from agent_framework.observability import configure_otel_providers

    if mode == "console":
        os.environ["ENABLE_CONSOLE_EXPORTERS"] = "true"
    else:  # mode == "otlp"
        if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
            raise ValueError("NIGHTSHIFT_TELEMETRY=otlp needs OTEL_EXPORTER_OTLP_ENDPOINT (see .env.example).")
        os.environ.setdefault("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")  # the HTTP exporter is the one installed
    configure_otel_providers()  # reads the standard OTEL_* variables
