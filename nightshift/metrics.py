"""Measure a run with the harness's own OpenTelemetry signal: model calls, tool executions and tokens come from spans."""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor


class CountingSpanProcessor(SpanProcessor):
    """Counts model calls, tool executions and token usage from the GenAI spans Agent Framework emits."""

    def __init__(self) -> None:
        self.model_calls = 0
        self.agent_invocations = 0
        self.input_tokens = 0
        self.cached_input_tokens = 0
        self.output_tokens = 0
        self.reasoning_tokens = 0
        self.tool_executions: Counter[str] = Counter()
        self.chat_input_tokens: list[int] = []  # per model call, in order

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        return None

    def on_end(self, span: ReadableSpan) -> None:
        name = span.name or ""
        attrs = dict(span.attributes or {})
        op = str(attrs.get("gen_ai.operation.name") or name.split(" ", 1)[0])
        if op == "chat":
            self.model_calls += 1
            self.chat_input_tokens.append(int(attrs.get("gen_ai.usage.input_tokens") or 0))
            self.input_tokens += self.chat_input_tokens[-1]
            self.cached_input_tokens += int(attrs.get("gen_ai.usage.cache_read.input_tokens") or 0)
            self.output_tokens += int(attrs.get("gen_ai.usage.output_tokens") or 0)
            self.reasoning_tokens += int(attrs.get("gen_ai.usage.reasoning.output_tokens") or 0)
        elif op == "execute_tool":
            tool_name = str(attrs.get("gen_ai.tool.name") or name.split(" ", 1)[-1])
            self.tool_executions[tool_name] += 1
        elif op == "invoke_agent":
            self.agent_invocations += 1

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True

    def snapshot(self) -> dict[str, Any]:
        return {
            "model_calls": self.model_calls,
            "agent_invocations": self.agent_invocations,
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "tool_executions": dict(self.tool_executions),
        }


_counter: CountingSpanProcessor | None = None


def attach_span_counter() -> CountingSpanProcessor:
    """Attach (once) an in-process span counter to the global tracer provider. Call after telemetry is configured."""
    global _counter
    if _counter is None:
        provider = trace.get_tracer_provider()
        add = getattr(provider, "add_span_processor", None)
        if add is None:
            # No exporter was configured (telemetry mode "none"). Agent Framework's instrumentation is on by
            # default, so a bare SDK provider is all it takes for the spans to exist in-process.
            from agent_framework.observability import create_resource
            from opentelemetry.sdk.trace import TracerProvider

            provider = TracerProvider(resource=create_resource())
            trace.set_tracer_provider(provider)
            add = provider.add_span_processor
        _counter = CountingSpanProcessor()
        add(_counter)
    return _counter


def _diff(after: dict[str, Any], before: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in after.items():
        if isinstance(value, dict):
            out[key] = {k: v - before.get(key, {}).get(k, 0) for k, v in value.items() if v - before.get(key, {}).get(k, 0)}
        else:
            out[key] = value - before.get(key, 0)
    return out


@dataclass
class RunMetrics:
    """One run: wall time and approvals measured here, everything else read from the span counter."""

    label: str = ""
    spans: CountingSpanProcessor | None = None
    started: float = field(default_factory=time.perf_counter)
    wall_seconds: float = 0.0
    approvals: list[dict[str, Any]] = field(default_factory=list)
    _span_baseline: dict[str, Any] = field(default_factory=dict)

    def start(self) -> RunMetrics:
        self.started = time.perf_counter()
        if self.spans is not None:
            self._span_baseline = self.spans.snapshot()
        return self

    def stop(self) -> RunMetrics:
        self.wall_seconds = round(time.perf_counter() - self.started, 1)
        return self

    def record_approval(self, request: Any, decision: Any) -> None:
        call = request.function_call
        self.approvals.append(
            {
                "tool": call.name if call else "?",
                "arguments": (call.parse_arguments() or {}) if call else {},
                "approved": decision.approved,
                "standing": decision.standing,
            }
        )

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "label": self.label,
            "wall_seconds": self.wall_seconds,
            "approvals_requested": len(self.approvals),
            "approvals_granted": sum(1 for a in self.approvals if a["approved"]),
            "approvals": self.approvals,
        }
        if self.spans is not None:
            data["telemetry"] = _diff(self.spans.snapshot(), self._span_baseline)
            calls = self.spans.chat_input_tokens[self._span_baseline.get("model_calls", 0):]
            data["telemetry"]["first_call_input_tokens"] = calls[0] if calls else None
        return data
