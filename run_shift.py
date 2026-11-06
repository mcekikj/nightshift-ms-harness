#!/usr/bin/env python
"""Run one night shift interactively.

    python run_shift.py --scenario shift-01                 # plan mode, you approve risky actions
    python run_shift.py --scenario shift-02 --mode execute  # skip planning, start working
    python run_shift.py --scenario shift-01 --approve auto  # a policy approves everything (demo/eval)

Operator commands while the agent waits for you:
    /go        approve the plan and switch to execute mode
    /todos     show the todo list      /mode [plan|execute]   show or set the mode
    /alerts    open alerts             /audit                 every tool action so far
    /score     compare with ground truth     /metrics         tokens, calls, approvals
    /report    print this shift's report            /exit      quit (Ctrl+C also quits and saves)
Any other text is sent to the agent as a message.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys
from pathlib import Path

from agent_framework import get_agent_mode, set_agent_mode

from nightshift.agent import HarnessOptions, Paths, build_nightshift_agent
from nightshift.approvals import heal_dangling_tool_calls, history_length, interactive_approver, policy_approver, run_turn
from nightshift.clients import build_chat_client
from nightshift.config import Settings
from nightshift.console import BOLD, DIM, RESET, ConsoleRenderer, ainput, banner
from nightshift.metrics import RunMetrics, attach_span_counter
from nightshift.telemetry import configure_telemetry
from nightshift.world import World

ROOT = Path(__file__).resolve().parent
SCENARIOS = sorted(p.stem for p in (ROOT / "scenarios").glob("*.json"))
RESUME = "The previous request was interrupted. Continue where you left off."


def opening_message(world: World) -> str:
    shift = world.shift
    return (
        f"Shift {world.id} ({world.title}), {shift.get('date')} {shift.get('window')}, region {shift.get('region')}.\n\n"
        f"Handover brief: {world.handover_brief}\n\n"
        "Work the open alert queue for this shift."
    )


async def maybe_await(value):
    return await value if inspect.isawaitable(value) else value


async def main(args: argparse.Namespace) -> int:
    settings = Settings.from_env(provider=args.provider, model=args.model, telemetry=args.telemetry)
    world = World.load(ROOT / "scenarios" / f"{args.scenario}.json")
    client = build_chat_client(settings)
    await configure_telemetry(settings.telemetry, client)
    spans = attach_span_counter()

    options = HarnessOptions(
        start_mode=args.mode,
        loop=not args.no_loop,
        loop_max_iterations=args.max_iterations,
        memory=not args.no_memory,
        skills=not args.no_skills,
        file_access=not args.no_file_access,
        compaction=not args.no_compaction,
    )
    ns = build_nightshift_agent(client, world, Paths(ROOT), options)
    session = ns.agent.create_session()
    approver = interactive_approver if args.approve == "interactive" else policy_approver(echo=True)
    metrics = RunMetrics(label=f"{world.id}/{settings.model_label}", spans=spans).start()
    renderer = ConsoleRenderer(show_results=not args.quiet)

    banner(
        f"Night Shift · {world.title} ({world.id})",
        [
            f"model: {settings.model_label}   telemetry: {settings.telemetry}   mode: {args.mode}   approvals: {args.approve}",
            f"memory: {'on' if options.memory else 'off'}   skills: {'on' if options.skills else 'off'}   "
            f"file access: {'on' if options.file_access else 'off'}   loop: {'on, max ' + str(options.loop_max_iterations) if options.loop else 'off'}",
            f"open alerts: {len(world.list_open_alerts())}   session: {session.session_id}",
        ],
    )
    world.reset_audit()  # the banner's list call is not part of the run

    try:
        await console_loop(args, ns, session, world, approver, renderer, metrics)
    except (KeyboardInterrupt, asyncio.CancelledError):
        renderer.newline()
        print(f"{DIM}interrupted{RESET}")
    finally:
        save_summary(settings, options, world, metrics, session)
    return 0


async def console_loop(args, ns, session, world, approver, renderer, metrics) -> None:
    pending: str | None = opening_message(world)
    retries = 0
    while True:
        if pending is not None:
            renderer.reset()
            print(f"{BOLD}nightshift>{RESET} ", end="", flush=True)
            saved_before = history_length(ns.agent, session)
            try:
                await run_turn(ns.agent, session, pending, approver, stream=True, on_update=renderer, metrics=metrics)
                retries = 0
                pending = None
            except Exception as e:  # noqa: BLE001 - transport errors happen on long streams; the session survives them
                renderer.newline()
                retries += 1
                print(f"{DIM}!! {type(e).__name__}: {str(e)[:200]}{RESET}")
                nothing_saved = history_length(ns.agent, session) == saved_before
                healed = heal_dangling_tool_calls(ns.agent, session)
                if healed:
                    print(f"{DIM}   closed {healed} tool call(s) that had no recorded result{RESET}")
                # If the turn saved nothing, the operator's message was lost with it: send it again.
                retry_with = pending if nothing_saved else RESUME
                if args.approve == "auto" and retries <= 2:
                    print(f"{DIM}   history is persisted after every model call; resuming (attempt {retries}){RESET}")
                    pending = retry_with
                    continue
                pending = None
                hint = "nothing from this turn was saved; send your message again" if nothing_saved else "type 'continue' to resume the turn"
                print(f"{DIM}   {hint} (history is persisted after every model call){RESET}")
            renderer.newline()

        try:
            line = (await ainput(f"\n{BOLD}operator>{RESET} ")).strip()
        except EOFError:
            print()
            return
        if not line:
            continue
        if line in ("/exit", "/quit"):
            return
        if line == "/go":
            set_agent_mode(session, "execute", source_id=ns.mode_provider.source_id)
            pending = "Plan approved. Execute it."
        elif line == "/todos":
            items = await maybe_await(ns.todo_provider.store.load_items(session, source_id=ns.todo_provider.source_id))
            if not items:
                print(f"{DIM}(no todos){RESET}")
            for item in items:
                print(f"  [{'x' if item.is_complete else ' '}] {item.id}. {item.title}")
        elif line == "/mode":
            print(get_agent_mode(session, source_id=ns.mode_provider.source_id, default_mode=ns.mode_provider.default_mode))
        elif line.startswith("/mode "):
            new_mode = line.split(maxsplit=1)[1].strip()
            try:
                set_agent_mode(session, new_mode, source_id=ns.mode_provider.source_id)
            except ValueError as e:
                print(f"{DIM}{e}{RESET}")
                continue
            pending = f"Mode changed to {new_mode}. Continue."
        elif line == "/alerts":
            print(json.dumps(world.list_open_alerts(), indent=2))
        elif line == "/audit":
            for entry in world.audit_log():
                print(f"  {entry['seq']:>3}. {json.dumps({k: v for k, v in entry.items() if k != 'seq'}, ensure_ascii=False)}")
        elif line == "/score":
            print(json.dumps(world.score(), indent=2))
        elif line == "/metrics":
            print(json.dumps(metrics.stop().as_dict(), indent=2))
        elif line == "/report":
            report = ns.paths.workspace / "reports" / f"{world.id}.md"
            print(report.read_text(encoding="utf-8") if report.exists() else f"{DIM}(no report for {world.id} yet){RESET}")
        elif line.startswith("/"):
            print(__doc__)
        else:
            pending = line


def save_summary(settings, options, world, metrics, session) -> None:
    metrics.stop()
    summary = {"model": settings.model_label, "options": vars(options), "score": world.score(), "metrics": metrics.as_dict(), "audit": world.audit_log()}
    out = ROOT / "results" / f"{world.id}-interactive-{session.session_id[:8]}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"\n{DIM}saved {out.relative_to(ROOT)}{RESET}")


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return number


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scenario", choices=SCENARIOS, default="shift-01")
    p.add_argument("--provider", choices=["foundry", "azure-openai", "openai"], default=None)
    p.add_argument("--model", default=None, help="deployment/model name override")
    p.add_argument("--telemetry", choices=["none", "console", "otlp", "azure-monitor", "foundry"], default=None)
    p.add_argument("--mode", choices=["plan", "execute"], default="plan")
    p.add_argument("--approve", choices=["interactive", "auto"], default="interactive")
    p.add_argument("--max-iterations", type=positive_int, default=12, help="loop passes per run in execute mode")
    p.add_argument("--no-loop", action="store_true")
    p.add_argument("--no-memory", action="store_true")
    p.add_argument("--no-skills", action="store_true")
    p.add_argument("--no-file-access", action="store_true")
    p.add_argument("--no-compaction", action="store_true")
    p.add_argument("--quiet", action="store_true", help="hide tool results")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse_args())))
