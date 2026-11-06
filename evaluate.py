#!/usr/bin/env python
"""Headless evaluation: run the scenarios with the harness agent and with a plain agent, score both.

Every count (model calls, tool calls, tokens) comes from the OpenTelemetry spans the agents emit.

    python evaluate.py                                  # harness + plain, shift-01 then shift-02, 1 run each
    python evaluate.py --agents harness --runs 3
    python evaluate.py --scenarios shift-01 --agents plain
    python evaluate.py --agents harness-no-memory harness-no-files --runs 3        # ablations: workspace only, memory only

Scenarios run in order with a fresh world each, but the harness agent keeps its memory folder across
them, which is how "what did last night's shift learn" is measured. A policy approver approves every
request and logs it, so the numbers reflect the agent's judgement, not the operator's.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from nightshift.agent import HarnessOptions, Paths, build_nightshift_agent, build_plain_agent
from nightshift.approvals import policy_approver, run_turn
from nightshift.clients import build_chat_client
from nightshift.config import Settings
from nightshift.console import ConsoleRenderer
from nightshift.metrics import RunMetrics, attach_span_counter
from nightshift.telemetry import configure_telemetry
from nightshift.tools import DOMAIN_TOOLS
from nightshift.world import World
from run_shift import opening_message

ROOT = Path(__file__).resolve().parent

# Headless runs start in execute mode. Two ablations separate the harness's two ways of carrying state from one
# shift to the next: the file memory (site-notes.md) and the file-access workspace (where the shift report lands).
HARNESS_VARIANTS = {
    "harness": HarnessOptions(start_mode="execute"),
    "harness-no-memory": HarnessOptions(start_mode="execute", memory=False),
    "harness-no-files": HarnessOptions(start_mode="execute", file_access=False),
}


async def run_one(kind: str, scenario_id: str, settings: Settings, state_root: Path, spans, *, verbose: bool) -> dict[str, Any]:
    world = World.load(ROOT / "scenarios" / f"{scenario_id}.json")
    client = build_chat_client(settings)
    paths = Paths(ROOT).with_state_root(state_root).ensure()
    approver = policy_approver(echo=verbose)
    metrics = RunMetrics(label=f"{kind}/{scenario_id}", spans=spans).start()
    renderer = ConsoleRenderer(show_results=False) if verbose else None

    if kind in HARNESS_VARIANTS:
        agent = build_nightshift_agent(client, world, paths, HARNESS_VARIANTS[kind]).agent
    elif kind == "plain":
        agent = build_plain_agent(client, world, paths)
    else:
        raise ValueError(kind)

    session = agent.create_session()
    error: str | None = None
    final_text = ""
    try:
        response = await run_turn(agent, session, opening_message(world), approver, stream=verbose, on_update=renderer, metrics=metrics)
        # The last assistant message: a looped run's response also carries earlier iterations and injected nudges.
        final_text = next((m.text for m in reversed(response.messages) if m.role == "assistant" and m.text), "")
    except Exception as e:  # noqa: BLE001 - keep going with the other runs, record the failure
        error = f"{type(e).__name__}: {e}"
        if verbose:
            print(f"\n!! {error}")
    metrics.stop()

    report = paths.workspace / "reports" / f"{scenario_id}.md"  # the workspace is shared by both scenarios
    report_text = report.read_text(encoding="utf-8") if report.exists() else None
    memory_files = sorted(p.name for p in paths.memory.rglob("*") if p.is_file() and not p.name.startswith("."))

    (state_root / f"{scenario_id}.final.md").write_text(final_text, encoding="utf-8")
    (state_root / f"{scenario_id}.audit.json").write_text(json.dumps(world.audit_log(), indent=2), encoding="utf-8")

    return {
        "agent": kind,
        "scenario": scenario_id,
        "model": settings.model_label,
        "error": error,
        "score": world.score(),
        "metrics": metrics.as_dict(),
        "report_written": report_text is not None,
        "report_chars": len(report_text) if report_text else 0,
        "memory_files": memory_files,
        "final_text_chars": len(final_text),
    }


def summary_table(results: list[dict[str, Any]]) -> str:
    cols = [
        "agent", "run", "scenario", "accuracy", "correct", "unsafe", "unexp.restart", "missed.restart", "repeat.restart",
        "unexp.dispatch", "missed.dispatch", "dup.dispatch", "wrong.priority", "approvals", "tool calls", "domain calls",
        "model calls", "tokens in", "cached in", "tokens out", "seconds", "report", "error",
    ]
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for r in results:
        s, m = r["score"], r["metrics"]
        tel = m.get("telemetry", {})
        lines.append(
            "| "
            + " | ".join(
                str(x)
                for x in [
                    r["agent"], r.get("run", 1), r["scenario"], s["accuracy"], f"{s['correct_resolutions']}/{s['alerts_total']}",
                    s["unsafe_restart_attempts"], s["unexpected_restarts"], len(s.get("missed_restarts", [])),
                    s.get("repeat_restart_attempts", "?"), s["unexpected_dispatches"], len(s["missed_dispatches"]),
                    s.get("duplicate_dispatches", "?"), len(s.get("wrong_priority", [])),
                    m["approvals_requested"], sum(tel.get("tool_executions", {}).values()),
                    sum(v for k, v in tel.get("tool_executions", {}).items() if k in DOMAIN_TOOLS),
                    tel.get("model_calls", "?"), tel.get("input_tokens", "?"), tel.get("cached_input_tokens", "?"),
                    tel.get("output_tokens", "?"),
                    m["wall_seconds"], "yes" if r["report_written"] else "no", (r["error"] or "")[:40],
                ]
            )
            + " |"
        )
    return "\n".join(lines)


async def main(args: argparse.Namespace) -> int:
    sys.stdout.reconfigure(line_buffering=True)  # progress lines show up even when redirected to a file
    settings = Settings.from_env(provider=args.provider, model=args.model, telemetry=args.telemetry)
    # One process-wide telemetry setup; the span counter attaches to whatever provider it installed.
    await configure_telemetry(settings.telemetry, build_chat_client(settings))
    spans = attach_span_counter()

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out) / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"model: {settings.model_label}   agents: {args.agents}   scenarios: {args.scenarios}   runs: {args.runs}")
    print(f"writing to {out_dir}")

    results: list[dict[str, Any]] = []
    for run in range(1, args.runs + 1):
        for kind in args.agents:
            state_root = out_dir / f"{kind}-run{run}"
            state_root.mkdir(parents=True, exist_ok=True)
            for scenario_id in args.scenarios:
                print(f"\n=== {kind} · run {run} · {scenario_id} ===")
                result = await run_one(kind, scenario_id, settings, state_root, spans, verbose=args.verbose)
                result["run"] = run
                results.append(result)
                s, m = result["score"], result["metrics"]
                tool_calls = sum(m.get("telemetry", {}).get("tool_executions", {}).values())
                print(
                    f"accuracy {s['accuracy']} ({s['correct_resolutions']}/{s['alerts_total']}), unsafe restarts {s['unsafe_restart_attempts']}, "
                    f"approvals {m['approvals_requested']}, tool calls {tool_calls}, {m['wall_seconds']}s"
                    + (f", ERROR {result['error']}" if result["error"] else "")
                )
                (out_dir / "results.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")

    table = summary_table(results)
    (out_dir / "summary.md").write_text(f"# Evaluation {stamp}\n\nmodel: {settings.model_label}\n\n{table}\n", encoding="utf-8")
    print("\n" + table)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scenarios", nargs="+", default=["shift-01", "shift-02"])
    p.add_argument("--agents", nargs="+", choices=[*HARNESS_VARIANTS, "plain"], default=["harness", "plain"])
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--provider", choices=["foundry", "azure-openai", "openai"], default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--telemetry", choices=["none", "console", "otlp", "azure-monitor", "foundry"], default=None,
                   help="defaults to NIGHTSHIFT_TELEMETRY; spans are counted in-process either way")
    p.add_argument("--out", default=str(ROOT / "results"))
    p.add_argument("--verbose", action="store_true", help="stream the agent's output while evaluating")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse_args())))
