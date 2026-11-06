"""A small streaming renderer for the terminal. Intentionally plain: the point is the harness, not the UI."""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

DIM = "\033[2m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def _short(value: Any, limit: int = 160) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        try:
            value = json.dumps(value, ensure_ascii=False, default=str)
        except TypeError:
            value = str(value)
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


async def ainput(prompt: str) -> str:
    """input() that does not block the event loop and does not keep the process alive after Ctrl+C."""
    loop = asyncio.get_running_loop()
    future: asyncio.Future[str] = loop.create_future()

    def read() -> None:
        try:
            line = input(prompt)
        except BaseException as error:  # noqa: BLE001 - EOFError and friends are handed to the awaiting task
            loop.call_soon_threadsafe(lambda err=error: future.done() or future.set_exception(err))
        else:
            loop.call_soon_threadsafe(lambda text=line: future.done() or future.set_result(text))

    threading.Thread(target=read, daemon=True).start()
    return await future


class ConsoleRenderer:
    """Prints streamed text as it arrives and one line per tool call once its result is in."""

    def __init__(self, *, show_results: bool = True) -> None:
        self.show_results = show_results
        self._calls: dict[str, dict[str, Any]] = {}
        self._at_line_start = True
        self._text_since_last_call = ""  # the stream replays each text run once more as one chunk; we skip that

    def reset(self) -> None:
        """Call at the start of every operator turn."""
        self._text_since_last_call = ""
        self._at_line_start = True

    def newline(self) -> None:
        if not self._at_line_start:
            print()
            self._at_line_start = True

    def __call__(self, update: Any) -> None:
        if str(getattr(update, "role", "") or "") == "user":
            # Messages the harness injects between loop iterations ("You still have N open todo items...").
            text = " ".join(c.text for c in update.contents or () if c.type == "text" and c.text)
            if text:
                self.newline()
                print(f"  {DIM}↻ {_short(text)}{RESET}")
                self._text_since_last_call = ""
            return
        for c in update.contents or ():
            kind = c.type
            if kind == "text" and c.text:
                if len(c.text) > 1 and c.text == self._text_since_last_call:
                    continue  # consolidated replay of what was already streamed
                self._text_since_last_call += c.text
                print(c.text, end="", flush=True)
                self._at_line_start = c.text.endswith("\n")
            elif kind == "function_call":
                self._text_since_last_call = ""
                key = c.call_id or f"{c.name}:{len(self._calls)}"
                entry = self._calls.setdefault(key, {"name": c.name, "args": "", "full": None})
                if c.name:
                    entry["name"] = c.name
                if isinstance(c.arguments, str):
                    try:
                        json.loads(c.arguments)
                        entry["full"] = c.arguments  # a chunk that parses on its own is the consolidated call
                    except ValueError:
                        entry["args"] += c.arguments
                elif c.arguments:
                    entry["full"] = json.dumps(c.arguments, ensure_ascii=False)
            elif kind == "function_result":
                self._text_since_last_call = ""
                entry = self._calls.get(c.call_id or "", {"name": "?", "args": "", "full": None})
                entry["args"] = entry.get("full") or entry["args"]
                self.newline()
                print(f"  {CYAN}▶ {entry['name']}{RESET}{DIM}({_short(entry['args'], 120)}){RESET}")
                if self.show_results:
                    print(f"  {GREEN}◀{RESET} {DIM}{_short(c.result)}{RESET}")
            elif kind == "usage":
                self._text_since_last_call = ""  # model-call boundary
            elif kind == "function_approval_request":
                self.newline()
            elif kind == "error":
                self.newline()
                print(f"  {YELLOW}! {c.message or c.error_code}{RESET}")


def banner(title: str, lines: list[str]) -> None:
    print(f"\n{BOLD}{title}{RESET}")
    for line in lines:
        print(f"  {DIM}{line}{RESET}")
    print()
