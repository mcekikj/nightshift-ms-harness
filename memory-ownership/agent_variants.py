"""Night Shift with a choice of long-term memory owner.

Everything else is the published Night Shift harness agent: the same model, tools, runbook skills, workspace, todo
list, mode, loop, compaction and approval rules. What changes per backend is the memory provider and the memory text
in the agent's instructions, exactly as listed here:

    curated             the agent's own notebook: FileMemoryProvider with a shared scope, instructions as published
    extracted           Foundry Memory delivered by the provider; the published workflow kept as is, with
                        FOUNDRY_MEMORY_NOTE appended (it overrides the two workflow steps that name the file tools)
    none                no long-term memory; the published NO_MEMORY note appended (the control)
    injected-note       crossover A: a fixed text delivered the platform's way by StaticMemoryProvider; instructions as
                        for `extracted`
    file-platform       crossover B: a pre-seeded notebook delivered the agent's way; instructions as for `curated`
    recall-tool         Foundry Memory with delivery off, plus a read-only tool the agent calls; the published workflow
                        kept as is, with FOUNDRY_RECALL_NOTE appended
    extracted-coherent  as `extracted`, but the two memory steps of the workflow are rewritten instead of overridden,
                        so the agent sees one coherent set of instructions (a fairness check)
"""

from __future__ import annotations

from typing import Annotated, Any

from config import NS_ROOT  # noqa: F401 - importing config puts the Night Shift code on sys.path

from agent_framework import (
    AgentModeProvider,
    ContextProvider,
    FileAccessProvider,
    FileMemoryProvider,
    FileSystemAgentFileStore,
    Message,
    SkillsProvider,
    TodoProvider,
    create_harness_agent,
    todos_remaining,
    todos_remaining_message,
    tool,
)

from foundry_memory import ObservableFoundryMemoryProvider
from nightshift.agent import HarnessOptions, NightShiftAgent, Paths
from nightshift.approvals import approve_report_writes
from nightshift.instructions import (
    HARNESS_WORKFLOW,
    MEMORY_INSTRUCTIONS,
    NO_MEMORY,
    NOC_INSTRUCTIONS,
    OPERATING_STANDARD,
)
from nightshift.tools import build_tools
from nightshift.world import World

BACKENDS = ("curated", "extracted", "none", "injected-note", "file-platform", "recall-tool", "extracted-coherent")

# Headless runs start in execute mode; everything else is the published default. The notebook scope is shared with the
# crossover seeding in run_experiment.py.
OPTIONS = HarnessOptions(start_mode="execute")
MEMORY_SCOPE = OPTIONS.memory_scope

# The heading under which memories are injected; replaces the provider's default "Consider the following memories ...".
FOUNDRY_CONTEXT_PROMPT = "## Memories\nStanding notes extracted from earlier shifts. They override runbook defaults:"

# Appended to the published instructions when the platform delivers long-term memory. It tells the agent the two things
# that are true in that deployment: memories arrive at the start of a shift, and only what it says out loud is remembered.
FOUNDRY_MEMORY_NOTE = """
### Memory in this deployment
Long-term memory is managed by the platform (Foundry Memory), not by you. There are no file_memory_* tools and no site-notes.md.
What you and the operator say in this conversation is extracted into memories automatically after the shift, and memories judged
relevant are shown to you at the start of a shift under a "## Memories" heading. Treat those memories like standing notes from
earlier shifts: they override runbook defaults. Anything a future shift must know (open carrier tickets, recurring behaviour,
policy reminders) must appear in your own messages, for example in a "Notes for the next night shift" section at the end of your
final answer, because only your messages are remembered, not tool results.
"""

# Appended when the agent fetches platform memory itself, in the slot where the published agent reads its notebook.
FOUNDRY_RECALL_NOTE = """
### Memory in this deployment
Long-term memory is managed by the platform (Foundry Memory), not by you. There are no file_memory_* tools and no site-notes.md.
Instead, step one of every shift is to call recall_site_notes with a question about standing notes from earlier shifts (for
example "standing notes, open carrier tickets and site policies that apply tonight"), and to call it again for a specific site
when an alert needs it. What it returns are standing notes from earlier shifts: they override runbook defaults.
What you and the operator say in this conversation is extracted into memories automatically after the shift. Anything a future
shift must know (open carrier tickets, recurring behaviour, policy reminders) must appear in your own messages, for example in
a "Notes for the next night shift" section at the end of your final answer, because only your messages are remembered, not
tool results.
"""

# extracted-coherent: the two memory steps of the published workflow, and their replacements.
_WORKFLOW_STEP_1 = "1. Read the memory file `site-notes.md` with file_memory_read if it exists. It holds standing notes from earlier shifts and they override runbook defaults."
_WORKFLOW_STEP_4_MEMORY = "and update `site-notes.md` with file_memory_write so the next shift inherits what you learned. Anything in the handover brief that applies to future shifts belongs in `site-notes.md`."
COHERENT_STEP_1 = '1. Read the standing notes shown under the "## Memories" heading at the start of this conversation, if there are any. They were extracted by the platform from earlier shifts and they override runbook defaults.'
COHERENT_STEP_4_MEMORY = 'and end your final answer with a "Notes for the next night shift" section so the next shift inherits what you learned. Anything in the handover brief or in tonight\'s work that applies to future shifts belongs there, because only what you say in this conversation is remembered, not tool results.'
COHERENT_MEMORY_NOTE = """
### Memory in this deployment
Long-term memory is managed by the platform (Foundry Memory), not by you. What you and the operator say in this conversation is
extracted into memories automatically after the shift, and memories judged relevant are shown to you at the start of a shift
under a "## Memories" heading.
"""


def coherent_instructions() -> str:
    """NOC instructions with the two memory steps rewritten for delivered platform memory, and no contradicting note."""
    if _WORKFLOW_STEP_1 not in HARNESS_WORKFLOW or _WORKFLOW_STEP_4_MEMORY not in HARNESS_WORKFLOW:
        raise RuntimeError("the published workflow text changed; update the memory steps in agent_variants.py")
    return NOC_INSTRUCTIONS.replace(_WORKFLOW_STEP_1, COHERENT_STEP_1).replace(_WORKFLOW_STEP_4_MEMORY, COHERENT_STEP_4_MEMORY) + COHERENT_MEMORY_NOTE


class StaticMemoryProvider(ContextProvider):
    """Delivers a fixed text exactly the way FoundryMemoryProvider delivers memories: as a user message, under the same
    heading, before every run that has input text. Used for the crossover, with Foundry out of the loop."""

    def __init__(self, text: str, source_id: str = "static_memory") -> None:
        super().__init__(source_id)
        self.text = text
        self.label = ""
        self.injected: list[dict[str, Any]] = []

    async def before_run(self, *, agent: Any, session: Any, context: Any, state: dict[str, Any]) -> None:
        if not any(m and m.text and m.text.strip() for m in context.input_messages):
            return
        block = f"{FOUNDRY_CONTEXT_PROMPT}\n{self.text}"
        context.extend_messages(self.source_id, [Message(role="user", contents=[block])])
        # Same record shape as ObservableFoundryMemoryProvider.injected, so the runner treats both alike.
        self.injected.append({
            "label": self.label,
            "query": [m.text for m in context.input_messages if m and m.text],
            "static_memories": 0,
            "text": block,
        })


def make_recall_tool(provider: ObservableFoundryMemoryProvider):
    """A read-only tool that lets the agent fetch platform memories itself, with its own question as the query."""

    @tool(name="recall_site_notes", approval_mode="never_require")
    async def recall_site_notes(
        question: Annotated[str, "What you need to know, for example 'standing notes and open carrier tickets for S-207'."],
    ) -> str:
        """Search the shared NOC memory for standing notes from earlier shifts and return them. Read-only."""
        return await provider.recall(question)

    return recall_site_notes


def build_agent(
    client: Any,
    world: World,
    paths: Paths,
    backend: str,
    memory_provider: ContextProvider | None = None,
) -> NightShiftAgent:
    """Compose the Night Shift harness agent with the chosen owner of long-term memory.

    `paths` must already exist (the runner calls `Paths.ensure()`)."""
    if backend not in BACKENDS:
        raise ValueError(f"unknown backend {backend!r}; expected one of {BACKENDS}")

    context_providers: list[ContextProvider] = []
    tools = build_tools(world)
    if backend in ("curated", "file-platform"):
        context_providers.append(_shared_notebook(paths))
        agent_instructions = NOC_INSTRUCTIONS
    elif backend in ("extracted", "injected-note", "extracted-coherent"):
        if memory_provider is None:
            raise ValueError(f"the {backend} backend needs a memory provider")
        if isinstance(memory_provider, ObservableFoundryMemoryProvider) and not memory_provider.deliver:
            raise ValueError(f"the {backend} backend needs a provider with deliver=True")
        context_providers.append(memory_provider)
        agent_instructions = coherent_instructions() if backend == "extracted-coherent" else NOC_INSTRUCTIONS + FOUNDRY_MEMORY_NOTE
    elif backend == "recall-tool":
        if not isinstance(memory_provider, ObservableFoundryMemoryProvider) or memory_provider.deliver:
            raise ValueError("the recall-tool backend needs an ObservableFoundryMemoryProvider with deliver=False")
        context_providers.append(memory_provider)
        tools.append(make_recall_tool(memory_provider))
        agent_instructions = NOC_INSTRUCTIONS + FOUNDRY_RECALL_NOTE
    else:  # none
        agent_instructions = NOC_INSTRUCTIONS + NO_MEMORY

    todo_provider = TodoProvider()
    mode_provider = AgentModeProvider(default_mode=OPTIONS.start_mode)
    agent = create_harness_agent(
        client=client,
        name="nightshift",
        description="Northwatch Energy overnight NOC agent",
        harness_instructions=OPERATING_STANDARD,
        agent_instructions=agent_instructions,
        tools=tools,
        todo_provider=todo_provider,
        mode_provider=mode_provider,
        disable_file_memory=True,  # the memory backend is chosen above
        context_providers=context_providers,
        skills_provider=SkillsProvider.from_paths(
            paths.skills, disable_load_skill_approval=True, disable_read_skill_resource_approval=True
        ),
        file_access_store=FileSystemAgentFileStore(paths.workspace),
        auto_approval_rules=[FileAccessProvider.read_only_tools_auto_approval_rule, approve_report_writes],
        loop_should_continue=todos_remaining(looping_modes=["execute"]),
        loop_next_message=todos_remaining_message,
        loop_max_iterations=OPTIONS.loop_max_iterations,
        max_context_window_tokens=OPTIONS.max_context_window_tokens,
        max_output_tokens=OPTIONS.max_output_tokens,
        disable_web_search=True,
        default_options={"store": False},
    )
    return NightShiftAgent(agent=agent, todo_provider=todo_provider, mode_provider=mode_provider, paths=paths)


def _shared_notebook(paths: Paths) -> FileMemoryProvider:
    """The first article's notebook: one scope shared by every shift, with instructions that say so."""
    return FileMemoryProvider(FileSystemAgentFileStore(paths.memory), scope=MEMORY_SCOPE, instructions=MEMORY_INSTRUCTIONS)
