# Findings: who owns an agent's memory? (runs of 10 and 11 Nov 2026)

One-line result: the platform remembered the fact in every run and the agent ignored it in four of five; the cause was not
delivery but the agent's workflow, whose step one still named a notebook that no longer existed; every arm whose workflow
named the real memory source (the file, the Memories block, or a recall tool) scored three storm nights out of three.

Model gpt-6-luna in a Foundry project in Sweden Central, agent-framework-core 1.24.0, agent-framework-foundry 1.16.0,
azure-ai-projects 2.7.0. Same agent, tools, skills, workspace, loop, compaction and approvals in every run. The world is
fresh for every shift; only the memory backend carries anything from night one to night two.

## The headline table

Night two is the storm night. A-2001 is the S-207 gateway alert whose correct resolution (known_issue, no action)
depends on remembering night one's carrier ticket CAR-55120.

| arm | memory | what step one of the workflow named | A-2001 right | night two scores | gateway restarted |
|---|---|---|---|---|---|
| curated | the agent's notebook, FileMemoryProvider, scope noc-nordic | the notebook | 3 of 3 | 6/6, 6/6, 6/6 | never |
| extracted | Foundry Memory delivered by FoundryMemoryProvider; published workflow kept, memory note appended | the notebook (missing); the note underneath named the Memories block | 1 of 4 clean runs (1 of 5 overall) | 5/6, 6/6, 5/6, 5/6, 5/6 | 4 of 5 runs |
| none | nothing | the notebook (missing); the published no-memory note appended | 0 of 3 | 5/6, 5/6, 5/6 | always |
| extracted-coherent | as extracted, workflow steps 1 and 4 rewritten, a three-line non-contradicting note appended | the Memories block | 3 of 3 | 6/6, 6/6, 6/6 | never |
| recall-tool | Foundry Memory with delivery off, plus a read-only recall tool | the recall tool (named in the appended note as step one) | 3 of 3 | 6/6, 6/6, 6/6 | never |

Night one was 5/5 in every run that played it; memory is not needed on night one.

Result folders (kept by the author, not in the repository): `results/20261110-233133` (curated and none), `results/20261110-235524` (extracted runs 1 to 3; run 1 is
tainted, see below), `results/20261111-000619` (extracted runs 4 and 5, stored there as run1 and run2),
`results/20261111-152525` (crossover), `results/20261111-202505` (recall-tool), `results/20261111-210239`
(extracted-coherent).

## What the platform did, run by run (extracted)

| extracted run | night one extraction | S-207 rule stored? | stored as | injected on night two? | A-2001 |
|---|---|---|---|---|---|
| 1 (tainted) | 2 of 4 updates failed with 401 (role still propagating) | yes, inside one chat summary | chat_summary | yes, in the middle of a night-one narrative | restarted |
| 2 | 4 of 4 ok, 7 memories | yes | user_profile + chat_summary | yes, first line of the block | known_issue |
| 3 | 3 of 3 ok, 6 memories | yes | user_profile + chat_summary | yes, first line of the block | restarted |
| 4 | 4 of 4 ok, 10 memories | yes | chat_summary only (no user_profile) | yes, inside a two-paragraph chat summary at the top of the block | restarted |
| 5 | 4 of 4 ok, 6 memories | yes | user_profile + chat_summary | yes, first line of the block | restarted |

So in every run the platform extracted the fact, kept it, found it (as a profile memory loaded at the start or by semantic
search on the handover brief), and put it in front of the agent at the start of night two. Recall was never the problem.
Four times out of five the agent restarted the gateway anyway. The restart reasons were built from the same facts every
time: no carrier incident reported and the gateway reachable out of band, with site policy cited as well in three of the
four. In run 4 the agent's own note on the alert says: "no prior-shift note was available in this session", written in the
same run in which the platform had injected the S-207 note at the top of the conversation.

## What the platform remembered

The memory store is readable (list_memories per scope). Observations that hold across runs:

- The S-207 rule became a **user_profile** memory in three of five runs ("the user's standing instruction"), a sentence
  inside a **chat_summary** in the other two. The platform's three kinds (user profile, chat summary, procedural) are built
  around a user; a site fact entered through the handover brief, which the provider sends as a user message, so it was filed
  under what the user wants.
- The chat summaries carry the platform's doubts, e.g. run 4: "The transcript does not show whether a restart was requested
  or approved, any telemetry verification, work on the other four alerts, or completion of the shift report and handover."
  All of that happened, in tool calls the platform never sees: FoundryMemoryProvider.after_run sends only user and assistant
  text.
- Every clean run produced **procedural** memories that are critiques of the agent (e.g. run 3: "the agent provides progress
  narration or claims a requested action without executing it or verifying the outcome"). None was retrieved on night two.
- Extraction: each night's updates were complete about 31 s (31.0 to 32.2 s) after the last one was submitted; 41 completed
  updates, 2,249 to 4,165 tokens each, median 2,927; 3 to 6 updates per storm night; 8,986 to 16,288 tokens per storm night
  against 120,468 to 291,736 input tokens for the agent's own calls across the five runs (120,468 to 273,031 in the four
  clean ones).
- The provider's default update_delay is 300 s; the experiment used 0 and waited for completion before night two.

## The crossover: same words, swapped transport (results/20261111-152525)

| variant | text | delivered how | A-2001 |
|---|---|---|---|
| injected-note | the agent's own note from curated run 2 (276 chars) | as a user message under "## Memories" at the start of the run; instructions as for `extracted` (published workflow + appended note) | restarted 3 of 3 |
| file-platform | the memories text of the block injected in extracted run 5, without the heading (4,711 chars) | pre-seeded site-notes.md read with file_memory_read; published instructions | known_issue 3 of 3 |

Read on its own this looked like proof that a fetched memory beats a delivered one. It is confounded: the two arms also
differ in what the workflow's step one names (the missing notebook with a note underneath vs the notebook). The next
section separates the two.

## The decisive check: the workflow pointer (results/20261111-210239)

`extracted-coherent`: identical to `extracted` (same provider, delivery on, same store, fresh scope per run, update_delay=0)
except that the two memory steps of the published workflow are rewritten and the appended note (three lines) only says
that the platform manages memory and where the memories appear, so nothing contradicts the steps:

- step 1: "Read the standing notes shown under the "## Memories" heading at the start of this conversation, if there are
  any. They were extracted by the platform from earlier shifts and they override runbook defaults."
- step 4: "... and end your final answer with a "Notes for the next night shift" section so the next shift inherits what
  you learned. Anything in the handover brief or in tonight's work that applies to future shifts belongs there, because
  only what you say in this conversation is remembered, not tool results."

| run | night one | night two | A-2001 | injected block (chars) | storm-night input tokens |
|---|---|---|---|---|---|
| 1 | 5/5 | 6/6 | known_issue | 3,636 | 113,007 |
| 2 | 5/5 | 6/6 | known_issue | 3,951 | 315,622 |
| 3 | 5/5 | 6/6 | known_issue | 3,893 | 360,812 |

Every night-one final answer contained the "Notes for the next night shift" section; every night-two injected block
contained S-207 and CAR-55120. Resolution note, run 1: "S-207's overnight GW-01 drops are covered by standing note for
NW-07 congestion; carrier ticket CAR-55120 remains open through 11 Nov. No dispatch or restart."

Interpretation: with the same delivered memory, rewriting what step one names turns 1 of 4 into 3 of 3. Note that the
recall-tool arm also kept the published step one; its appended note explicitly redefined step one ("Instead, step one of
every shift is to call recall_site_notes ..."), whereas FOUNDRY_MEMORY_NOTE only described the Memories block ("are shown
to you ... treat those memories like standing notes") without making reading it a step. The operative variable is whether
the instructions make reading the memory the agent has a step. The run-4 sentence
"no prior-shift note was available in this session" is the agent reporting the outcome of its step one (read the notebook
if it exists) in a deployment with no notebook. Transport did not decide the storm night; the workflow pointer did. The
earlier "provenance / schema / selection / timing" interpretation is withdrawn as the explanation of the main result;
schema and selection are accurate descriptions of the platform's memories but did not change between the failing and the
succeeding delivered arms.

## The other fix: the platform's memory, fetched by the agent (results/20261111-202505)

`recall-tool`: ObservableFoundryMemoryProvider with `deliver=False` (extraction after every run, nothing injected), plus one
read-only tool `recall_site_notes(question)` that searches the store with the agent's question and returns the memories as
text. The appended note names the tool as step one.

| run | night one | night two | A-2001 | recalls (night one / night two) | storm-night input tokens |
|---|---|---|---|---|---|
| 1 | 5/5 | 6/6 | known_issue | 6 / 6 | 293,905 |
| 2 | 5/5 | 6/6 | known_issue | 1 / 1 | 130,318 |
| 3 | 5/5 | 6/6 | known_issue | 2 / 6 | 462,276 |

Every night-two first recall returned five memories with the S-207 rule among them, still filed as a user-profile memory in
the platform's user-centred wording. Run 2 asked once: "Standing notes, open carrier tickets, storm-related comms guidance
and site policies that apply to shift-02 in the Nordic region." Resolution note, run 2: "Recurring S-207 gateway loss during
the 23:00–02:30 NW-07 congestion window per standing note; CAR-55120 remains open through Nov 11. No dispatch."

Side observation: because the provider runs after every loop iteration, run 1's fourth recall on night one (mid-shift)
returned memories extracted from that same night's conversation. With update_delay=0 the store is a running summary of the
shift in progress.

Cost: recalls return up to five memories and tool results stay in context, so storm-night input tokens ran 130,318 to
462,276; the rewritten-workflow arm ran 113,007 to 360,812; the original delivered arm 120,468 to 291,736 across its five
runs.

## What this does not show

- Three runs per arm (four clean in the original delivered arm), one model. Directions are unambiguous, rates are not.
- The crossover cannot separate transport from workflow; the extracted-coherent runs show the workflow effect is sufficient.
  The mirror image (the agent's note injected under a workflow that names the Memories block) was not run, so nothing is
  claimed about transport beyond "with the pointer right, both transports worked".
- Foundry Memory is in preview and documented for conversational, planning and research agents; the schema observations
  are descriptions, not defects.
- The hosted-session row of the article's ownership map rests on documentation and the first article's deployment.

## Setup facts that cost time

- The memory store calls the chat and embedding deployments with the project's system-assigned identity. On an account with
  local auth disabled that identity needs the role "Foundry User" (the renamed "Azure AI User") on the account, otherwise
  every search and update fails with "Authentication to the Azure OpenAI resource failed". Propagation was uneven for about
  half an hour: some calls succeeded while others on the same scope failed. An earlier attempt (`results/20261110-235210`)
  aborted on that error before the storm night and is not counted.
- The stock FoundryMemoryProvider swallows those failures with a warning and injects nothing, which would have looked exactly
  like "the platform recalled nothing". The provider in this folder probes the store at the start of every delivered run and
  aborts the run if it does not answer; on the fetched path a failed recall returns an explicit sentence to the agent and is
  recorded as a run error.
- The curated and control arms were also 3/3 and 0/3 on 6 Nov with the same agent (evaluate.py from the first article).
