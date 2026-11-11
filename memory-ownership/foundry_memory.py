"""A FoundryMemoryProvider that can be observed, waited for, and used without delivery.

The stock provider fires memory updates and forgets them, and it swallows search errors with a warning. For an
experiment we need to

1. know exactly which memories were injected into the agent's context on each run,
2. wait until the platform has finished extracting memories from night one before night two starts,
3. list what the platform decided to remember,
4. make a failed memory call visible: on the delivered path a store that does not answer at the start of a run aborts the
   run instead of letting the stock hook inject nothing; on the fetched path the tool returns an explicit error sentence
   and the failure is recorded,
5. switch delivery off while keeping extraction, so the agent can fetch memories itself through a tool.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from agent_framework import AgentSession, Message, SessionContext
from agent_framework.foundry import FoundryMemoryProvider

logger = logging.getLogger(__name__)

T = TypeVar("T")

RECALL_UNAVAILABLE = "The memory store could not be reached. Do not assume there are no notes from earlier shifts."


class ObservableFoundryMemoryProvider(FoundryMemoryProvider):
    """FoundryMemoryProvider with a record of what went in and out, a way to wait for extraction, and a `deliver` switch.

    `label` is set by the runner before each shift so that every recorded event can be attributed to a scenario.
    With `deliver=False` the stock `before_run` is skipped (nothing is searched or injected) while `after_run` still
    sends the conversation for extraction; the agent then fetches memories through a tool that calls `recall()`.
    The provider closes the credential it was given when it is used as an async context manager.
    """

    def __init__(self, *args: Any, deliver: bool = True, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.deliver = deliver
        self.label = ""
        self.injected: list[dict[str, Any]] = []        # one entry per before_run that injected memories
        self.recalls: list[dict[str, Any]] = []         # one entry per recall() made by the agent's tool
        self.stored: list[dict[str, Any]] = []          # one entry per after_run that sent items for extraction
        self.search_retries: list[dict[str, Any]] = []  # probes that needed more than one attempt
        self._credential = kwargs.get("credential")
        self._pollers: list[Any] = []

    async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any) -> None:
        await super().__aexit__(exc_type, exc_val, exc_tb)
        close = getattr(self._credential, "close", None)
        if close is not None:
            await close()

    # ------------------------------------------------------------------ hooks

    async def before_run(self, *, agent: Any, session: AgentSession, context: SessionContext, state: dict[str, Any]) -> None:
        if not self.deliver:
            return
        # One extra search per run with text input, on top of the stock provider's own (static + contextual) searches.
        # It costs a call; a store that does not answer here aborts the run instead of producing an empty injection.
        # (A failure between this probe and the stock searches would still be swallowed by the stock hook.)
        await self._probe(context)
        await super().before_run(agent=agent, session=session, context=context, state=state)
        messages = context.get_messages(sources={self.source_id})
        if messages:
            self.injected.append({
                "label": self.label,
                "query": [m.text for m in context.input_messages if m and m.text],
                "static_memories": len(state.get("static_memories", [])),
                "text": "\n".join(m.text or "" for m in messages),
            })

    async def after_run(self, *, agent: Any, session: AgentSession, context: SessionContext, state: dict[str, Any]) -> None:
        # The same filter as the stock provider: user and assistant text only, no tool calls and no tool results.
        messages: list[Message] = list(context.input_messages)
        if context.response and context.response.messages:
            messages.extend(context.response.messages)
        items = [
            {"role": m.role, "type": "message", "content": m.text}
            for m in messages
            if m.role in {"user", "assistant"} and m.text and m.text.strip()
        ]
        if not items:
            return
        try:
            poller = await self.project_client.beta.memory_stores.begin_update_memories(
                name=self.memory_store_name,
                scope=self.scope,
                items=items,
                previous_update_id=state.get("previous_update_id"),
                update_delay=self.update_delay,
            )
        except Exception as e:  # noqa: BLE001 - recorded, and visible in the results, instead of swallowed
            logger.warning("Failed to update memories: %s", e)
            self.stored.append({"label": self.label, "error": f"{type(e).__name__}: {e}", "items": items})
            return
        state["previous_update_id"] = poller.update_id
        self._pollers.append(poller)
        self.stored.append({"label": self.label, "update_id": poller.update_id, "items": items})

    # ------------------------------------------------------------------ the agent's own fetch

    async def recall(self, question: str, attempts: int = 4, delay: float = 10.0) -> str:
        """Search the store with the agent's question and return the memories as text.

        Never raises: a tool exception would reach the model as a generic "Error: Function failed." and read like an empty
        result. A failure is recorded in `recalls` and returned as an explicit sentence instead."""
        try:
            memories = await self._retry(lambda: self._search(question), attempts, delay, what="recall")
        except Exception as e:  # noqa: BLE001
            self.recalls.append({"label": self.label, "question": question, "attempts": attempts, "error": f"{type(e).__name__}: {str(e)[:300]}"})
            return RECALL_UNAVAILABLE
        self.recalls.append({"label": self.label, "question": question, "memories": memories})
        return "\n\n".join(m["content"] for m in memories) or "No notes from earlier shifts were found."

    # ------------------------------------------------------------------ experiment helpers

    async def wait(self) -> list[dict[str, Any]]:
        """Wait for every pending extraction and report how each one ended."""
        outcomes = []
        for poller in self._pollers:
            try:
                result = await poller.result()
                outcomes.append({"update_id": poller.update_id, "status": poller.status(), "result": _as_dict(result)})
            except Exception as e:  # noqa: BLE001 - a failed extraction is a result, not a crash
                outcomes.append({"update_id": poller.update_id, "status": f"{type(e).__name__}: {e}", "superseded_by": poller.superseded_by})
        self._pollers.clear()
        return outcomes

    async def list_memories(self) -> list[dict[str, Any]]:
        """Everything the store holds for this scope (`limit` is the page size; the pager follows continuation cursors)."""
        out = []
        async for m in self.project_client.beta.memory_stores.list_memories(name=self.memory_store_name, scope=self.scope, limit=100):
            out.append({"kind": str(m.kind), "memory_id": m.memory_id, "updated_at": str(m.updated_at), "content": m.content})
        return out

    async def search(self, query: str) -> list[dict[str, Any]] | dict[str, str]:
        """What the store would return for a query; errors are returned, not raised, so a probe never ends a run."""
        try:
            return await self._search(query)
        except Exception as e:  # noqa: BLE001
            return {"error": f"{type(e).__name__}: {str(e)[:300]}"}

    # ------------------------------------------------------------------ internals

    async def _search(self, query: str) -> list[dict[str, Any]]:
        result = await self.project_client.beta.memory_stores.search_memories(
            name=self.memory_store_name,
            scope=self.scope,
            items=[{"type": "message", "role": "user", "content": query}],
        )
        return [{"kind": str(m.memory_item.kind), "content": m.memory_item.content} for m in result.memories]

    async def _probe(self, context: SessionContext, attempts: int = 8, delay: float = 15.0) -> None:
        """Fail loudly if the store does not answer, before the stock hook could hide the failure as an empty result."""
        text = next((m.text for m in context.input_messages if m and m.text and m.text.strip()), None)
        if text is None:
            return
        used = {"attempts": 0}

        async def probe() -> list[dict[str, Any]]:
            used["attempts"] += 1
            return await self._search(text)

        try:
            await self._retry(probe, attempts, delay, what="memory search probe")
        except Exception as e:
            raise RuntimeError(f"Foundry Memory search unavailable after {attempts} attempts: {e}") from e
        if used["attempts"] > 1:
            self.search_retries.append({"label": self.label, "attempts_needed": used["attempts"]})

    @staticmethod
    async def _retry(fn: Callable[[], Awaitable[T]], attempts: int, delay: float, *, what: str) -> T:
        """Call `fn` up to `attempts` times, sleeping `delay` seconds between attempts, never after the last one."""
        if attempts < 1:
            raise ValueError("attempts must be at least 1")
        for attempt in range(1, attempts + 1):
            try:
                return await fn()
            except Exception as e:  # noqa: BLE001
                logger.warning("%s failed (attempt %d/%d): %s", what, attempt, attempts, str(e)[:120])
                if attempt == attempts:
                    raise
                await asyncio.sleep(delay)
        raise AssertionError("unreachable")


def _as_dict(obj: Any) -> Any:
    if obj is None:
        return None
    if hasattr(obj, "as_dict"):
        try:
            return obj.as_dict()
        except Exception:  # noqa: BLE001
            pass
    return str(obj)
