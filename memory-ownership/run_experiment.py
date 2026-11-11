#!/usr/bin/env python
"""Who owns an agent's memory? Night Shift on two consecutive nights, with a choice of memory owner.

    curated             the agent writes and reads its own notebook (FileMemoryProvider, shared scope)
    extracted           the platform extracts memories from what the agent said and delivers them (FoundryMemoryProvider)
    none                no long-term memory at all (control; storm night only)
    injected-note       crossover A: the agent's own note, delivered the platform's way (storm night only)
    file-platform       crossover B: the platform's extracted text, delivered the agent's way (storm night only)
    recall-tool         the platform's memory, fetched by the agent through a tool instead of delivered
    extracted-coherent  as extracted, with the workflow rewritten instead of overridden by an appended note

Two-night variants play shift-01 (the quiet night, where the S-207 carrier ticket is learned) and then shift-02 (the storm
night, where remembering it is the difference between a known issue and a needless gateway restart). The world is fresh
for every shift; only the memory backend carries anything across. Foundry variants get their own memory scope per
variant and run, and night two starts only after the platform reports the extraction from night one complete.

With the Night Shift repository's virtual environment (see README.md, Layout):

    python run_experiment.py --variants curated extracted none --runs 3
    python run_experiment.py --variants injected-note file-platform --runs 3
    python run_experiment.py --variants recall-tool --runs 3
    python run_experiment.py --variants extracted-coherent --runs 3

Results land in results/<timestamp>/: results.json (everything), summary.md (one table), and one folder per variant
and run with the audit log, the agent's final answer, its assistant messages, and its memory and workspace folders.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import time
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from config import CROSSOVER_DIR, MEMORY_STORE, NS_ROOT, RESULTS_DIR  # puts the Night Shift code on sys.path
from dotenv import load_dotenv

from agent_framework import ContextProvider
from agent_variants import BACKENDS, FOUNDRY_CONTEXT_PROMPT, MEMORY_SCOPE, StaticMemoryProvider, build_agent
from foundry_memory import ObservableFoundryMemoryProvider
from nightshift.agent import Paths
from nightshift.approvals import policy_approver, run_turn
from nightshift.clients import build_chat_client
from nightshift.config import Settings
from nightshift.metrics import CountingSpanProcessor, RunMetrics, attach_span_counter
from nightshift.telemetry import configure_telemetry
from nightshift.world import World
from run_shift import opening_message

SCENARIOS = {
    "curated": ["shift-01", "shift-02"],
    "extracted": ["shift-01", "shift-02"],
    "none": ["shift-02"],
    "injected-note": ["shift-02"],
    "file-platform": ["shift-02"],
    "recall-tool": ["shift-01", "shift-02"],
    "extracted-coherent": ["shift-01", "shift-02"],
}
FOUNDRY_VARIANTS = ("extracted", "extracted-coherent", "recall-tool")
KEY_ALERT = {"shift-02": "A-2001"}  # the alert whose resolution depends on remembering night one


# ---------------------------------------------------------------------------------------------------- memory backends

def make_foundry_provider(settings: Settings, scope: str, *, deliver: bool) -> ObservableFoundryMemoryProvider:
    from azure.identity.aio import AzureCliCredential

    return ObservableFoundryMemoryProvider(
        project_endpoint=settings.foundry_project_endpoint,
        credential=AzureCliCredential(),
        allow_preview=True,
        memory_store_name=MEMORY_STORE,
        scope=scope,
        context_prompt=FOUNDRY_CONTEXT_PROMPT,
        update_delay=0,
        deliver=deliver,
    )


def seed_platform_notebook(state_root: Path) -> None:
    """Crossover B: a notebook in the layout FileMemoryProvider expects (index and description files from
    crossover/notebook), with the platform's extracted text as site-notes.md."""
    target = state_root / "memory" / MEMORY_SCOPE
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(CROSSOVER_DIR / "notebook", target)
    (target / "site-notes.md").write_text((CROSSOVER_DIR / "platform-memory.md").read_text(encoding="utf-8"), encoding="utf-8")


# ---------------------------------------------------------------------------------------------------- one shift

async def play_shift(
    variant: str,
    scenario_id: str,
    settings: Settings,
    state_root: Path,
    spans: CountingSpanProcessor,
    memory_provider: ContextProvider | None,
    *,
    verbose: bool,
) -> dict[str, Any]:
    """Play one scenario with a fresh world and a fresh session; return the score, the metrics and what the agent kept."""
    world = World.load(NS_ROOT / "scenarios" / f"{scenario_id}.json")
    paths = Paths(NS_ROOT).with_state_root(state_root).ensure()
    if memory_provider is not None:
        memory_provider.label = scenario_id  # type: ignore[attr-defined] - both experiment providers record by label
    agent = build_agent(build_chat_client(settings), world, paths, variant, memory_provider=memory_provider).agent
    session = agent.create_session()
    approver = policy_approver(echo=verbose)
    metrics = RunMetrics(label=f"{variant}/{scenario_id}", spans=spans).start()

    error: str | None = None
    assistant_texts: list[str] = []
    try:
        response = await run_turn(agent, session, opening_message(world), approver, stream=False, metrics=metrics)
        assistant_texts = [m.text for m in response.messages if m.role == "assistant" and m.text]
    except Exception as e:  # noqa: BLE001 - record the failure and keep going with the other runs
        error = f"{type(e).__name__}: {e}"
        if verbose:
            print(f"\n!! {error}")
    metrics.stop()
    final_text = assistant_texts[-1] if assistant_texts else ""

    (state_root / f"{scenario_id}.final.md").write_text(final_text, encoding="utf-8")
    (state_root / f"{scenario_id}.assistant.json").write_text(json.dumps(assistant_texts, indent=2), encoding="utf-8")
    (state_root / f"{scenario_id}.audit.json").write_text(json.dumps(world.audit_log(), indent=2), encoding="utf-8")

    score = world.score()
    key_alert = next((p for p in score["per_alert"] if p["alert_id"] == KEY_ALERT.get(scenario_id)), None)
    memory_files = {
        str(p.relative_to(paths.memory)): p.read_text(encoding="utf-8") for p in sorted(paths.memory.rglob("*.md"))
    } if paths.memory.exists() else {}
    return {
        "variant": variant,
        "scenario": scenario_id,
        "model": settings.model_label,
        "error": error,
        "score": score,
        "key_alert": key_alert,
        "metrics": metrics.as_dict(),
        "memory_files": memory_files,
        "final_text_chars": len(final_text),
    }


async def platform_details(provider: ObservableFoundryMemoryProvider, scenario_id: str) -> dict[str, Any]:
    """After a shift on a Foundry variant: wait for extraction, then record what the store holds and what it served."""
    t0 = time.perf_counter()
    extraction = await provider.wait()
    recalls = [x for x in provider.recalls if x["label"] == scenario_id]
    details: dict[str, Any] = {
        "extraction": extraction,
        "extraction_wait_seconds": round(time.perf_counter() - t0, 1),
        "memories_after": await provider.list_memories(),
        "memories_injected": [x for x in provider.injected if x["label"] == scenario_id],
        "recalls": recalls,
        "items_sent_for_extraction": [x for x in provider.stored if x["label"] == scenario_id],
        "search_retries": [x for x in provider.search_retries if x["label"] == scenario_id],
    }
    failed = [x for x in recalls if "error" in x]
    if failed:
        details["error"] = f"{len(failed)} recall(s) failed: {failed[0]['error']}"
    if scenario_id == "shift-01":
        # What would the store return for night two's opening message, and for a direct question about the alert?
        storm = World.load(NS_ROOT / "scenarios" / "shift-02.json")
        details["probe_search"] = {
            "handover brief of shift-02": await provider.search(opening_message(storm)),
            "S-207 comms loss": await provider.search(
                "Alert A-2001: no telemetry from site gateway GW-01 at S-207 Vaasa Marsh for 38 minutes. Should I restart it?"
            ),
        }
    return details


# ---------------------------------------------------------------------------------------------------- reporting

def key_alert_cell(r: dict[str, Any]) -> str:
    key = r.get("key_alert")
    if not key:
        return ""
    return f"{key['actual'] or 'unresolved'} {'✓' if key['correct'] else '✗'}"


def memory_path_cell(r: dict[str, Any]) -> str:
    """How the memory reached the agent on this shift: delivered (injections), fetched (file, or tool calls with results)."""
    variant = r["variant"]
    if variant in ("extracted", "extracted-coherent", "injected-note"):
        return f"delivered x{len(r.get('memories_injected', []))}"
    if variant in ("curated", "file-platform"):
        return "file"
    if variant == "recall-tool":
        recalls = r.get("recalls", [])
        return f"tool {sum(1 for x in recalls if x.get('memories'))}/{len(recalls)}"
    return "-"


def progress_line(r: dict[str, Any]) -> str:
    s, m = r["score"], r["metrics"]
    telemetry = m.get("telemetry", {})
    line = (
        f"    accuracy {s['accuracy']} ({s['correct_resolutions']}/{s['alerts_total']}), restarts {s['restarts']}, "
        f"dispatches {s['dispatches']}, model calls {telemetry.get('model_calls')}, {m['wall_seconds']}s"
    )
    if r.get("key_alert"):
        line += f", {r['key_alert']['alert_id']} -> {key_alert_cell(r)}"
    if r.get("error"):
        line += f", ERROR {r['error']}"
    if "extraction" in r:
        statuses = [e.get("status") for e in r["extraction"]]
        line += (
            f"\n    extraction: {statuses} in {r['extraction_wait_seconds']}s; memories in scope: {len(r['memories_after'])}; "
            f"memory path: {memory_path_cell(r)}"
        )
    return line


def summary_table(results: list[dict[str, Any]]) -> str:
    cols = ["variant", "run", "scenario", "correct", "A-2001", "restarts", "dispatches", "memory path", "mem in scope",
            "model calls", "tokens in", "tokens out", "seconds", "error"]
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for r in results:
        s, telemetry = r["score"], r["metrics"].get("telemetry", {})
        cells = [
            r["variant"], r["run"], r["scenario"], f"{s['correct_resolutions']}/{s['alerts_total']}", key_alert_cell(r),
            s["restarts"], s["dispatches"], memory_path_cell(r),
            len(r["memories_after"]) if "memories_after" in r else "-",
            telemetry.get("model_calls", "?"), telemetry.get("input_tokens", "?"), telemetry.get("output_tokens", "?"),
            r["metrics"]["wall_seconds"], (r.get("error") or "")[:40],
        ]
        lines.append("| " + " | ".join(str(c) for c in cells) + " |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------------- main

async def main(args: argparse.Namespace) -> int:
    sys.stdout.reconfigure(line_buffering=True)  # progress lines show up even when redirected to a file
    load_dotenv(NS_ROOT / ".env")
    settings = Settings.from_env(provider=args.provider, model=args.model, telemetry=args.telemetry)
    await configure_telemetry(settings.telemetry, build_chat_client(settings))
    spans = attach_span_counter()

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = RESULTS_DIR / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"model: {settings.model_label}   variants: {args.variants}   runs: {args.runs}   -> {out_dir}")

    results: list[dict[str, Any]] = []
    for run in range(1, args.runs + 1):
        for variant in args.variants:
            state_root = out_dir / f"{variant}-run{run}"
            state_root.mkdir(parents=True, exist_ok=True)
            async with AsyncExitStack() as stack:
                provider: ContextProvider | None = None
                scope: str | None = None
                if variant in FOUNDRY_VARIANTS:
                    scope = f"nightshift-{stamp}-{variant}-run{run}"  # one scope per variant and run
                    provider = await stack.enter_async_context(
                        make_foundry_provider(settings, scope, deliver=(variant != "recall-tool"))
                    )
                elif variant == "injected-note":
                    provider = StaticMemoryProvider((CROSSOVER_DIR / "curated-note.md").read_text(encoding="utf-8"))
                elif variant == "file-platform":
                    seed_platform_notebook(state_root)

                for scenario_id in SCENARIOS[variant]:
                    print(f"\n=== {variant} · run {run} · {scenario_id}" + (f" · scope {scope}" if scope else "") + " ===")
                    r = await play_shift(variant, scenario_id, settings, state_root, spans, provider, verbose=args.verbose)
                    r["run"] = run
                    r["scope"] = scope
                    if isinstance(provider, StaticMemoryProvider):
                        r["memories_injected"] = [x for x in provider.injected if x["label"] == scenario_id]
                    elif isinstance(provider, ObservableFoundryMemoryProvider):
                        details = await platform_details(provider, scenario_id)
                        r["error"] = r["error"] or details.pop("error", None)
                        r.update(details)
                    results.append(r)
                    print(progress_line(r))
                    (out_dir / "results.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
                    if r["error"]:
                        print("    stopping this run: a later night would be meaningless after a failed one")
                        break

    table = summary_table(results)
    (out_dir / "summary.md").write_text(f"# Memory ownership experiment {stamp}\n\nmodel: {settings.model_label}\n\n{table}\n", encoding="utf-8")
    print("\n" + table)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--variants", nargs="+", choices=BACKENDS, default=["curated", "extracted", "none"])
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--provider", choices=["foundry", "azure-openai", "openai"], default=None,
                   help="defaults to NIGHTSHIFT_PROVIDER; the Foundry Memory variants need a Foundry project either way")
    p.add_argument("--model", default=None)
    p.add_argument("--telemetry", choices=["none", "console", "otlp", "azure-monitor", "foundry"], default=None,
                   help="defaults to NIGHTSHIFT_TELEMETRY; spans are counted in-process either way")
    p.add_argument("--verbose", action="store_true", help="echo approvals and errors while running")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse_args())))
