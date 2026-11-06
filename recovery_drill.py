#!/usr/bin/env python
"""Recovery drill: reproduce, against a live model, the throttling failure described in the article, then repair it.

The failure: a tool runs, and the model call that should carry its result fails (a throttled deployment
returns 429). History is persisted per model call, so the session keeps the assistant's function call but
not the tool's result, and the service then rejects every request in that session with
"No tool output found for function call".

The drill makes that happen on purpose. Once the first run_remote_diagnostic has executed, every request to
the model's /responses endpoint gets an HTTP 429, the response a throttled deployment sends, until the
run gives up. Only the chat client's HTTP send is wrapped: the OpenAI SDK and its retries, the chat client,
the function loop, per-call persistence and the harness all run unmodified against the real model.

    python recovery_drill.py                    # shift-01 on the provider configured in .env
    python recovery_drill.py --verbose          # also stream the agent's output

Exit code 0 means every step behaved as expected.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from nightshift.agent import HarnessOptions, Paths, build_nightshift_agent
from nightshift.approvals import find_dangling_tool_calls, heal_dangling_tool_calls, policy_approver, run_turn
from nightshift.clients import build_chat_client
from nightshift.config import Settings
from nightshift.console import ConsoleRenderer
from nightshift.world import World
from run_shift import opening_message

ROOT = Path(__file__).resolve().parent
RESUME = "The previous request was interrupted. Continue where you left off."


class Throttle:
    """Answers model requests with HTTP 429 while armed, the way a throttled deployment does.

    It wraps the `send` method of the chat client's own HTTP client (the OpenAI SDK's), so nothing else changes.
    """

    def __init__(self, chat_client: Any) -> None:
        self.armed = False
        self.injected = 0
        self._http = chat_client.client._client  # the AsyncOpenAI client's HTTP client

    def install(self) -> None:
        throttle, original = self, self._http.send

        async def send(request: Any, **kwargs: Any) -> Any:
            if throttle.armed and request.method == "POST" and request.url.path.endswith("/responses"):
                throttle.injected += 1
                http = importlib.import_module(type(request).__module__.split(".")[0])  # httpx or httpx2
                body = {"error": {"code": "429", "message": "Rate limit exceeded (injected by recovery_drill.py)."}}
                return http.Response(429, json=body, headers={"retry-after-ms": "100"}, request=request)
            return await original(request, **kwargs)

        self._http.send = send


def step(n: int, text: str) -> None:
    print(f"\n[{n}] {text}")


async def main(args: argparse.Namespace) -> int:
    settings = Settings.from_env(provider=args.provider, model=args.model)
    world = World.load(ROOT / "scenarios" / f"{args.scenario}.json")
    state = Path(tempfile.mkdtemp(prefix="nightshift-drill-"))
    paths = Paths(ROOT).with_state_root(state).ensure()
    chat_client = build_chat_client(settings)
    ns = build_nightshift_agent(chat_client, world, paths, HarnessOptions(start_mode="execute"))
    session = ns.agent.create_session()
    approver = policy_approver()
    renderer = ConsoleRenderer(show_results=False) if args.verbose else None

    throttle = Throttle(chat_client)
    throttle.install()
    diagnostic = world.diagnostic

    def diagnostic_then_throttle(*a):
        result = diagnostic(*a)
        if throttle.injected == 0:
            throttle.armed = True  # the tool has run; the model call that should carry its result will fail
        return result

    world.diagnostic = diagnostic_then_throttle  # type: ignore[method-assign]
    checks: dict[str, bool] = {}
    print(f"model: {settings.model_label}   scenario: {world.id}")

    step(1, "Run the shift; the deployment starts throttling right after the first remote diagnostic.")
    try:
        await run_turn(ns.agent, session, opening_message(world), approver, on_update=renderer)
        print("    the run finished without an error (the drill did not trigger)")
        checks["run failed after a tool"] = False
    except Exception as e:  # noqa: BLE001
        print(f"    {type(e).__name__}: {str(e)[:220]}")
        checks["run failed after a tool"] = True
    finally:
        throttle.armed = False
    print(f"    429 responses injected: {throttle.injected}")
    executed = [x["tool"] for x in world.audit_log()]
    print(f"    tools executed before the failure: {', '.join(executed) or 'none'}")

    dangling = find_dangling_tool_calls(ns.agent, session)
    step(2, "Inspect the session history.")
    for c in dangling:
        print(f"    function call without a recorded result: {c.name}({c.arguments}) call_id={c.call_id}")
    checks["history has a dangling call"] = bool(dangling)

    step(3, "Resume without repairing the session (what the console did before the fix).")
    try:
        await run_turn(ns.agent, session, RESUME, approver, on_update=renderer)
        print("    the service accepted the request")
        checks["unrepaired resume is rejected"] = False
    except Exception as e:  # noqa: BLE001
        message = str(e)
        print(f"    {type(e).__name__}: {message[:220]}")
        checks["unrepaired resume is rejected"] = "No tool output found for function call" in message

    step(4, "Repair the session and resume.")
    healed = heal_dangling_tool_calls(ns.agent, session)
    print(f"    placeholder results added: {healed}")
    checks["repair closed the calls"] = healed == len(dangling) > 0
    diagnostics_before = sum(1 for x in world.audit_log() if x["tool"] == "run_remote_diagnostic")
    try:
        await run_turn(ns.agent, session, RESUME, approver, on_update=renderer)
        checks["repaired session completes"] = True
    except Exception as e:  # noqa: BLE001
        print(f"    {type(e).__name__}: {str(e)[:220]}")
        checks["repaired session completes"] = False
    score = world.score()
    diagnostics_after = sum(1 for x in world.audit_log() if x["tool"] == "run_remote_diagnostic")
    restarts = [x for x in world.audit_log() if x["tool"] == "restart_device"]
    print(
        f"    score {score['correct_resolutions']}/{score['alerts_total']}, open alerts {score['alerts_open']}, "
        f"unsafe restart attempts {score['unsafe_restart_attempts']}, restarts {len(restarts)}, "
        f"remote diagnostics after the repair {diagnostics_after - diagnostics_before}"
    )
    checks["shift finished correctly"] = score["alerts_open"] == 0 and score["correct_resolutions"] == score["alerts_total"]
    checks["no restart repeated"] = len({(x["site"], x["device"]) for x in restarts}) == len(restarts)

    shutil.rmtree(state, ignore_errors=True)
    print("\nResult")
    for name, ok in checks.items():
        print(f"    {'PASS' if ok else 'FAIL'}  {name}")
    return 0 if all(checks.values()) else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scenario", default="shift-01")
    p.add_argument("--provider", choices=["foundry", "azure-openai", "openai"], default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--verbose", action="store_true", help="stream the agent's output")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse_args())))
