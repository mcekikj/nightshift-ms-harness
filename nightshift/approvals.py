"""Human-in-the-loop plumbing: approval decisions, the run loop that answers them, and auto-approval rules.

A harness run stops and returns pending approval requests instead of executing a risky tool. The
caller (this module) collects a decision and resumes the same session with the answer. Standing
decisions ("always approve this tool") are stored in the session by the harness middleware.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from agent_framework import (
    AgentResponse,
    AgentSession,
    Content,
    Message,
    create_always_approve_tool_response,
    create_always_approve_tool_with_arguments_response,
)

from .console import ainput


@dataclass
class Decision:
    approved: bool
    standing: str | None = None  # None | "tool" | "tool_with_arguments"
    reason: str | None = None


Approver = Callable[[Content], Awaitable[Decision]]


def describe_request(request: Content) -> str:
    call = request.function_call
    if call is None:
        return "<non-function approval request>"
    args = call.parse_arguments() or {}
    rendered = ", ".join(f"{k}={v!r}" for k, v in args.items())
    return f"{call.name}({rendered})"


async def interactive_approver(request: Content) -> Decision:
    """Ask the operator at the terminal. A closed input (Ctrl+D) counts as a denial."""
    print(f"\n  ⏸  Approval needed: {describe_request(request)}")
    prompt = "     [y] approve   [n] deny   [t] always approve this tool   [a] always approve these exact arguments > "
    while True:
        try:
            answer = (await ainput(prompt)).strip().lower()
        except EOFError:
            print("\n     no answer: denied")
            return Decision(False, reason="operator: no answer")
        if answer in ("y", "yes"):
            return Decision(True)
        if answer in ("n", "no"):
            return Decision(False)
        if answer == "t":
            return Decision(True, standing="tool", reason="operator: always approve this tool")
        if answer == "a":
            return Decision(True, standing="tool_with_arguments", reason="operator: always approve these arguments")
        print("     please answer y, n, t or a")


def policy_approver(policy: Callable[[str, dict[str, Any]], bool] | None = None, *, echo: bool = False) -> Approver:
    """Headless approver for evaluations and demos. The default policy approves everything, so what is
    measured is the agent's judgement (what it asks for), not the gate. Pass a policy to experiment,
    for example `lambda tool, args: tool != "dispatch_technician"`."""

    async def approve(request: Content) -> Decision:
        call = request.function_call
        args = (call.parse_arguments() or {}) if call else {}
        name = call.name if call else "?"
        ok = True if policy is None else bool(policy(name, args))
        if echo:
            print(f"\n  ⏸  Approval needed: {describe_request(request)} -> {'approved' if ok else 'DENIED'} (policy)")
        return Decision(ok, reason="policy")

    return approve


def response_for(request: Content, decision: Decision) -> Content:
    if decision.approved and decision.standing == "tool":
        return create_always_approve_tool_response(request, reason=decision.reason)
    if decision.approved and decision.standing == "tool_with_arguments":
        return create_always_approve_tool_with_arguments_response(request, reason=decision.reason)
    return request.to_function_approval_response(decision.approved)


async def run_turn(
    agent: Any,
    session: AgentSession,
    user_input: Any,
    approver: Approver,
    *,
    stream: bool = True,
    on_update: Callable[[Any], None] | None = None,
    metrics: Any | None = None,
) -> AgentResponse:
    """Run one operator turn to completion: keep answering approval requests until the agent returns a final answer."""
    current = user_input
    while True:
        pending: list[Content] = []
        if stream:
            response_stream = agent.run(current, stream=True, session=session)
            async for update in response_stream:
                if on_update is not None:
                    on_update(update)
                pending.extend(update.user_input_requests)
            response = await response_stream.get_final_response()
        else:
            response = await agent.run(current, session=session)

        requests = [r for r in (response.user_input_requests or pending) if r.function_call is not None]
        if not requests:
            return response

        replies: list[Message] = []
        for request in requests:
            decision = await approver(request)
            if metrics is not None:
                metrics.record_approval(request, decision)
            replies.append(Message("user", [response_for(request, decision)]))
        current = replies


# ---------------------------------------------------------------- recovery

INTERRUPTED_RESULT = (
    "No result was recorded for this call because the request was interrupted. It may or may not have "
    "completed. Check the current state with read-only tools before you repeat it or report it as done."
)


def _history_messages(agent: Any, session: AgentSession) -> list[Message] | None:
    """The transcript kept by the agent's history provider in session state (None if there is none)."""
    from agent_framework import HistoryProvider

    providers = getattr(agent, "context_providers", None) or []
    history = next((p for p in providers if isinstance(p, HistoryProvider)), None)
    bucket = session.state.get(history.source_id) if history is not None else None
    messages = bucket.get("messages") if isinstance(bucket, dict) else None
    return messages if isinstance(messages, list) else None


def history_length(agent: Any, session: AgentSession) -> int:
    """How many messages the history provider has saved for this session."""
    return len(_history_messages(agent, session) or [])


def _is_open_call(content: Content, answered: set[str]) -> bool:
    return (
        content.type == "function_call"
        and bool(content.call_id)
        and content.call_id not in answered
        and not getattr(content, "informational_only", False)  # hosted tools run service-side and need no result
    )


def _answered_call_ids(messages: list[Message]) -> set[str]:
    return {c.call_id for m in messages for c in (m.contents or ()) if c.type == "function_result" and c.call_id}


def find_dangling_tool_calls(agent: Any, session: AgentSession) -> list[Content]:
    """Function calls in the session history that have no recorded result."""
    messages = _history_messages(agent, session) or []
    answered = _answered_call_ids(messages)
    return [c for m in messages for c in (m.contents or ()) if _is_open_call(c, answered)]


def heal_dangling_tool_calls(agent: Any, session: AgentSession, note: str = INTERRUPTED_RESULT) -> int:
    """Give every function call that has no recorded result a placeholder result, so the session can continue.

    History is persisted after every model call, and a call's new input (such as the result of the tool
    that just ran) is saved together with that call's response. If the model call that follows a tool
    execution fails (rate limit, network), the history keeps the assistant's function call but not the
    tool's result, and the service rejects every later request ("No tool output found for function call").
    The placeholder goes right after the message that holds the call. Its text does not claim the tool
    ran: from here the healer cannot tell, so it tells the model to check before acting again.
    Call it only after a failed run, never while an approval request is still waiting for an answer.
    """
    messages = _history_messages(agent, session)
    if not messages:
        return 0
    answered = _answered_call_ids(messages)
    healed = 0
    i = 0
    while i < len(messages):
        dangling = [c for c in (messages[i].contents or ()) if _is_open_call(c, answered)]
        if dangling:
            messages.insert(i + 1, Message("tool", [Content.from_function_result(c.call_id, result=note) for c in dangling]))
            answered.update(c.call_id for c in dangling)
            healed += len(dangling)
            i += 1
        i += 1
    return healed


# ---------------------------------------------------------------- auto-approval rules (no human involved)


REPORT_WRITE_TOOLS = frozenset({"file_access_write", "file_access_replace", "file_access_replace_lines"})


def approve_report_writes(call: Content) -> bool:
    """Auto-approve writes and edits under reports/, the only place the agent is meant to write. Deletes still prompt."""
    if call.name not in REPORT_WRITE_TOOLS:
        return False
    args = call.parse_arguments() or {}
    target = str(args.get("file_name", "")).replace("\\", "/")
    return target.startswith("reports/") and ".." not in target
