# Who owns an agent's memory? The experiment

Night Shift, the Northwatch NOC agent from the first article, built on the Microsoft Agent Framework Harness, works two
consecutive nights. On night one it learns that site S-207's gateway drops every night because of a congested cell and
that carrier ticket CAR-55120 is open until 11 November. On night two, the storm night, the same gateway alert comes
back. An agent that remembers closes it as a known issue. An agent that does not restarts the gateway for nothing.

The only thing that differs between variants is who owns the long-term memory and how it reaches the agent:

| variant | who writes memory | how it reaches the agent | component |
|---|---|---|---|
| curated | the agent, deliberately, into site-notes.md | the agent reads the file as step one | `FileMemoryProvider` (harness) |
| extracted | the platform, from what the agent said | the platform searches with the opening message and injects a user message | `FoundryMemoryProvider` + Foundry Memory (preview) |
| none | nobody | nothing | control |
| recall-tool | the platform, from what the agent said | the agent calls a read-only tool with its own question (the fix) | `FoundryMemoryProvider` with delivery off + `recall_site_notes` |
| extracted-coherent | as extracted | as extracted, but the two memory steps of the workflow are rewritten to name the Memories block instead of being overridden by an appended note (the decisive check) | as extracted |

Two crossover variants swap the texts between the delivery paths, storm night only, with Foundry out of the loop:

| variant | text | delivered how |
|---|---|---|
| injected-note | the agent's own note (`crossover/curated-note.md`) | as an injected user message, the platform's way |
| file-platform | the memories text of the platform's injected block, without the heading (`crossover/platform-memory.md`) | pre-seeded into site-notes.md, the agent's way |

Everything else is identical: model, tools, runbook skills, workspace, todo list, loop, compaction, approvals. The world
is fresh for every shift. The Foundry variants get their own memory scope per variant and run, `update_delay=0`, and night
two starts only after the platform reports that extraction from night one completed.

What text each variant's agent sees is spelled out at the top of `agent_variants.py`. In short: the published
instructions are kept, and a memory note is appended that overrides the two workflow steps naming the file-memory tools;
`extracted-coherent` rewrites those two steps instead, and that difference decided the storm night.

The findings are in `FINDINGS.md`. Every number there and in the article comes from the `results.json` files the runner writes.

## Files

- `config.py` - where the Night Shift code is (see Layout) and the memory store name; imported first by every script.
- `run_experiment.py` - runs the variants; writes `results/<timestamp>/` with `results.json`, `summary.md` and one folder per
  variant and run (audit log, final answer, assistant messages, memory and workspace folders). For the Foundry variants each
  result also records the extraction outcomes, the memories in the scope, the memories injected on each shift, the recalls
  the agent made, the exact items sent for extraction, and two probe searches after night one. A run whose night one fails
  is stopped; a later night would be meaningless.
- `agent_variants.py` - the Night Shift agent with a memory backend switch, the instruction text per backend,
  `StaticMemoryProvider` for crossover A, and the `recall_site_notes` tool.
- `foundry_memory.py` - `ObservableFoundryMemoryProvider`: the stock provider with a record of what it injected, sent and
  was asked, a `wait()` for extraction, `list_memories()`, `search()`, `recall()` (the tool's fetch) and a `deliver` switch.
  On the delivered path a store that does not answer at the start of a run aborts the run instead of letting the stock
  hook inject nothing; on the fetched path a failed recall returns an explicit sentence to the agent and is recorded as a
  run error.
- `setup_memory_store.py` - creates the memory store, or deletes a scope.
- `crossover/` - the two texts used by the crossover variants and the notebook layout (`notebook/`) for crossover B.
- `results/` - not in the repository. The runs behind the article (six batches, about 1.7 MB of result files: a
  `results.json` and `summary.md` per batch, and per run the audit log, the agent's final answer, its assistant messages
  and its memory and workspace folders) are kept by the author; every number in the article and in `FINDINGS.md` was
  computed from them, and `FINDINGS.md` records the per-run figures. Running the commands below recreates the layout.

## Layout

The scripts import the `nightshift` package from the published Night Shift repository. `config.py` looks, in order, at
`NIGHTSHIFT_ROOT`, at the parent folder (this folder inside the repository), and at a sibling folder named
`nightshift-harness`. Clone https://github.com/mcekikj/nightshift-ms-harness accordingly and use its virtual environment.

## Azure prerequisites

- A Microsoft Foundry project in a region where Foundry Memory is available (Sweden Central was used), with a chat
  deployment (`gpt-6-luna` was used) and an embedding deployment (`text-embedding-3-small`).
- A memory store: `setup_memory_store.py` creates `nightshift-memory` with user profile, chat summary and procedural memory
  enabled, using the two deployments above.
- The project's system-assigned managed identity needs the **Foundry User** role on the Foundry account (the role was
  called Azure AI User before Microsoft renamed its built-in roles). Without it, on an account with local authentication
  disabled, every search and update fails with "Authentication to the Azure OpenAI resource failed", and the stock
  provider hides that as a warning. Propagation was uneven for about half an hour after the assignment.
- The Night Shift `.env` with `NIGHTSHIFT_PROVIDER=foundry`, `FOUNDRY_PROJECT_ENDPOINT` and `FOUNDRY_MODEL`, as for the
  first article.

## Run

With the Night Shift repository's virtual environment active (`../.venv` inside the repository, `../nightshift-harness/.venv`
in the sibling layout):

    cd memory-ownership
    python setup_memory_store.py
    python run_experiment.py --variants curated extracted none --runs 3
    python run_experiment.py --variants injected-note file-platform --runs 3
    python run_experiment.py --variants recall-tool --runs 3
    python run_experiment.py --variants extracted-coherent --runs 3

To clean up after a Foundry run: `setup_memory_store.py --delete-scope <scope>`.

## Notes

- Nothing in this folder identifies the subscription, the project or the account; the endpoint comes from the Night Shift
  `.env`, which is ignored by git.
- The provider sends only user and assistant text for extraction, as the stock one does. Tool calls and tool results never
  reach the memory store. That is a property of the stock design and is central to the findings.
