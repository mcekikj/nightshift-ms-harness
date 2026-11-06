# Evaluation, 6 November 2026

Model: `gpt-6-luna` (Global Standard) on a Microsoft Foundry project, Sweden Central. Code: this repository as
published, installed from `requirements.txt`. Every count (tool calls, Northwatch "domain" calls, model calls,
tokens) comes from Agent Framework's OpenTelemetry spans; scores come from `World.score()` against the ground
truth in `scenarios/`. The four jobs below overlapped in time on the same deployment, so `seconds` is
wall-clock time under shared load.

Notes:
- Every wrong resolution in every run is alert A-2001 (the Vaasa Marsh gateway on the storm night).
- The first model call's prompt is recorded per run (`first_call_input_tokens` in `results.json`). It was 6,592
  tokens for the harness on shift 1, 6,604 to 6,612 on shift 2, and 2,621 / 2,564 for the plain agent, except the
  very first harness run of the main job, which recorded 9,046. A separate probe measured 6,592 three times out
  of three, so the article uses that figure.

## Harness and plain baseline

`python evaluate.py --runs 3` (run 20261106-010921)

| agent | run | scenario | accuracy | correct | unsafe | unexp.restart | missed.restart | repeat.restart | unexp.dispatch | missed.dispatch | dup.dispatch | wrong.priority | approvals | tool calls | domain calls | model calls | tokens in | cached in | tokens out | seconds | report | error |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| harness | 1 | shift-01 | 1.0 | 5/5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 30 | 16 | 26 | 317866 | 292498 | 3480 | 97.9 | yes |  |
| harness | 1 | shift-02 | 1.0 | 6/6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 38 | 21 | 33 | 405007 | 354293 | 6233 | 124.9 | yes |  |
| plain | 1 | shift-01 | 1.0 | 5/5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 19 | 19 | 6 | 26295 | 20480 | 1914 | 24.5 | no |  |
| plain | 1 | shift-02 | 0.833 | 5/6 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 22 | 22 | 6 | 27146 | 23524 | 2181 | 23.1 | no |  |
| harness | 2 | shift-01 | 1.0 | 5/5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 37 | 19 | 31 | 343978 | 318330 | 4466 | 88.7 | yes |  |
| harness | 2 | shift-02 | 1.0 | 6/6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 39 | 20 | 33 | 390838 | 338665 | 5766 | 111.2 | yes |  |
| plain | 2 | shift-01 | 1.0 | 5/5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 19 | 19 | 6 | 26434 | 23179 | 2051 | 23.2 | no |  |
| plain | 2 | shift-02 | 0.833 | 5/6 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 22 | 22 | 6 | 27141 | 23594 | 2146 | 22.3 | no |  |
| harness | 3 | shift-01 | 1.0 | 5/5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 32 | 19 | 15 | 168670 | 136055 | 4426 | 57.9 | yes |  |
| harness | 3 | shift-02 | 1.0 | 6/6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 42 | 20 | 32 | 408802 | 352716 | 5953 | 100.7 | yes |  |
| plain | 3 | shift-01 | 1.0 | 5/5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 19 | 19 | 6 | 26070 | 23412 | 1849 | 21.5 | no |  |
| plain | 3 | shift-02 | 0.833 | 5/6 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 22 | 22 | 6 | 27472 | 23814 | 2375 | 23.2 | no |  |

## Ablation: memory only (file access off)

`python evaluate.py --agents harness-no-files --runs 3` (run 20261106-010921)

| agent | run | scenario | accuracy | correct | unsafe | unexp.restart | missed.restart | repeat.restart | unexp.dispatch | missed.dispatch | dup.dispatch | wrong.priority | approvals | tool calls | domain calls | model calls | tokens in | cached in | tokens out | seconds | report | error |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| harness-no-files | 1 | shift-01 | 1.0 | 5/5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 26 | 16 | 22 | 207365 | 194623 | 2785 | 78.4 | no |  |
| harness-no-files | 1 | shift-02 | 1.0 | 6/6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 35 | 20 | 22 | 210616 | 190111 | 4554 | 72.3 | no |  |
| harness-no-files | 2 | shift-01 | 1.0 | 5/5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 40 | 20 | 30 | 281872 | 263653 | 4298 | 84.7 | no |  |
| harness-no-files | 2 | shift-02 | 1.0 | 6/6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 35 | 20 | 31 | 276196 | 253832 | 4144 | 82.5 | no |  |
| harness-no-files | 3 | shift-01 | 1.0 | 5/5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 31 | 20 | 13 | 108389 | 96146 | 3535 | 55.0 | no |  |
| harness-no-files | 3 | shift-02 | 1.0 | 6/6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 35 | 20 | 29 | 267095 | 242069 | 4821 | 95.2 | no |  |

## Ablation: workspace only (file memory off)

`python evaluate.py --agents harness-no-memory --runs 3` (run 20261106-010921)

| agent | run | scenario | accuracy | correct | unsafe | unexp.restart | missed.restart | repeat.restart | unexp.dispatch | missed.dispatch | dup.dispatch | wrong.priority | approvals | tool calls | domain calls | model calls | tokens in | cached in | tokens out | seconds | report | error |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| harness-no-memory | 1 | shift-01 | 1.0 | 5/5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 40 | 20 | 28 | 284305 | 256152 | 4157 | 83.0 | yes |  |
| harness-no-memory | 1 | shift-02 | 1.0 | 6/6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 38 | 21 | 31 | 313215 | 276085 | 5617 | 98.4 | yes |  |
| harness-no-memory | 2 | shift-01 | 1.0 | 5/5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 38 | 20 | 31 | 328584 | 296434 | 4435 | 87.5 | yes |  |
| harness-no-memory | 2 | shift-02 | 1.0 | 6/6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 5 | 40 | 20 | 26 | 285373 | 239918 | 6245 | 245.9 | yes |  |
| harness-no-memory | 3 | shift-01 | 1.0 | 5/5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 35 | 19 | 30 | 297216 | 268826 | 3904 | 70.7 | yes |  |
| harness-no-memory | 3 | shift-02 | 0.833 | 5/6 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 5 | 40 | 22 | 25 | 267997 | 225984 | 6195 | 93.3 | yes |  |

## Ablation: no state carried over (storm night only)

`python evaluate.py --agents harness-no-memory --scenarios shift-02 --runs 3` (run 20261106-011720)

| agent | run | scenario | accuracy | correct | unsafe | unexp.restart | missed.restart | repeat.restart | unexp.dispatch | missed.dispatch | dup.dispatch | wrong.priority | approvals | tool calls | domain calls | model calls | tokens in | cached in | tokens out | seconds | report | error |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| harness-no-memory | 1 | shift-02 | 0.833 | 5/6 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 38 | 22 | 32 | 325384 | 287211 | 4536 | 94.6 | yes |  |
| harness-no-memory | 2 | shift-02 | 0.833 | 5/6 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 5 | 38 | 22 | 32 | 327792 | 288129 | 5571 | 98.1 | yes |  |
| harness-no-memory | 3 | shift-02 | 0.833 | 5/6 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 36 | 23 | 28 | 271888 | 236195 | 4846 | 80.8 | yes |  |
