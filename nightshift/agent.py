"""The agent factory. This is the part of the demo that is about the harness.

`build_nightshift_agent` composes one `create_harness_agent` call. `build_plain_agent` builds the
same model, tools and domain instructions without the harness, as a baseline for the evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_framework import (
    Agent,
    AgentModeProvider,
    FileAccessProvider,
    FileMemoryProvider,
    FileSystemAgentFileStore,
    SkillsProvider,
    TodoProvider,
    create_harness_agent,
    todos_remaining,
    todos_remaining_message,
)

from .approvals import approve_report_writes
from .instructions import MEMORY_INSTRUCTIONS, OPERATING_STANDARD, noc_instructions, plain_instructions
from .tools import build_tools
from .world import World


@dataclass
class Paths:
    root: Path
    memory: Path = field(init=False)
    workspace: Path = field(init=False)
    skills: Path = field(init=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.memory = self.root / ".nightshift" / "memory"
        self.workspace = self.root / "workspace"
        self.skills = self.root / "skills"

    def with_state_root(self, state_root: Path) -> Paths:
        """Keep the shared skills folder but move memory and workspace elsewhere (used by evaluations)."""
        p = Paths(self.root)
        p.memory = Path(state_root) / "memory"
        p.workspace = Path(state_root) / "workspace"
        return p

    def ensure(self) -> Paths:
        self.memory.mkdir(parents=True, exist_ok=True)
        (self.workspace / "reports").mkdir(parents=True, exist_ok=True)
        return self


@dataclass
class HarnessOptions:
    start_mode: str = "plan"            # "plan" for the interactive console, "execute" for headless runs
    loop: bool = True                   # keep re-running while todos remain in execute mode
    loop_max_iterations: int = 12
    memory: bool = True                 # durable file memory, shared across shifts through a stable scope
    memory_scope: str = "noc-nordic"
    skills: bool = True                 # runbooks as Agent Skills, loaded on demand
    file_access: bool = True            # shift reports written into workspace/reports
    compaction: bool = True
    max_context_window_tokens: int = 128_000
    max_output_tokens: int = 16_384
    web_search: bool = False            # not needed for a NOC; also avoids a warning on clients without hosted search
    client_side_history: bool = True    # store=False keeps the transcript in-process so persistence and compaction apply


@dataclass
class NightShiftAgent:
    agent: Agent
    todo_provider: TodoProvider
    mode_provider: AgentModeProvider
    paths: Paths


def build_nightshift_agent(client: Any, world: World, paths: Paths, options: HarnessOptions | None = None) -> NightShiftAgent:
    options = options or HarnessOptions()
    paths.ensure()

    todo_provider = TodoProvider()
    mode_provider = AgentModeProvider(default_mode=options.start_mode)

    context_providers = []
    if options.memory:
        # The harness default is session-scoped memory. A NOC wants one notebook shared by every
        # shift, so we build the provider ourselves with a stable scope and hand it in. The default
        # instructions describe session-scoped, isolated memory, so they are replaced too.
        memory_store = FileSystemAgentFileStore(paths.memory)
        context_providers.append(FileMemoryProvider(memory_store, scope=options.memory_scope, instructions=MEMORY_INSTRUCTIONS))

    skills_provider = None
    if options.skills:
        # The runbooks are ours, so loading them does not need a human in the loop.
        skills_provider = SkillsProvider.from_paths(
            paths.skills,
            disable_load_skill_approval=True,
            disable_read_skill_resource_approval=True,
        )

    extra: dict[str, Any] = {}
    if options.file_access:
        extra["file_access_store"] = FileSystemAgentFileStore(paths.workspace)
    if options.loop:
        extra["loop_should_continue"] = todos_remaining(looping_modes=["execute"])
        extra["loop_next_message"] = todos_remaining_message
        extra["loop_max_iterations"] = options.loop_max_iterations
    if options.compaction:
        extra["max_context_window_tokens"] = options.max_context_window_tokens
        extra["max_output_tokens"] = options.max_output_tokens
    else:
        extra["disable_compaction"] = True

    agent = create_harness_agent(
        client=client,
        name="nightshift",
        description="Northwatch Energy overnight NOC agent",
        harness_instructions=OPERATING_STANDARD,
        agent_instructions=noc_instructions(file_access=options.file_access, memory=options.memory),
        tools=build_tools(world),
        todo_provider=todo_provider,
        mode_provider=mode_provider,
        disable_file_memory=True,  # replaced by the scoped provider in context_providers
        context_providers=context_providers,
        skills_provider=skills_provider,
        auto_approval_rules=[
            FileAccessProvider.read_only_tools_auto_approval_rule,  # reading the workspace never needs a human
            approve_report_writes,                                   # writing under reports/ does not either
        ],
        disable_web_search=not options.web_search,
        default_options={"store": False} if options.client_side_history else None,
        **extra,
    )
    return NightShiftAgent(agent=agent, todo_provider=todo_provider, mode_provider=mode_provider, paths=paths)


def build_plain_agent(client: Any, world: World, paths: Paths) -> Agent:
    """Baseline for the evaluation: same model, same seven tools, same domain knowledge (runbooks inlined), no harness."""
    return Agent(
        client=client,
        name="nightshift-plain",
        instructions=plain_instructions(paths.skills),
        tools=build_tools(world),
        default_options={"store": False},
    )
