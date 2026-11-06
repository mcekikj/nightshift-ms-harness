---
name: battery-anomaly-triage
description: Runbook for battery and BMS alerts (kind "battery_soc_anomaly" and other storage anomalies). Load it before acting on any battery alert.
---

# Battery anomaly triage runbook

## Always first

1. Call `get_site_profile`; storage sites with a `critical_load` are never restarted remotely.
2. Call `run_remote_diagnostic` for the BMS. Read `known_bug`, `safety_flags` and `soc_from_cell_voltages_pct`.

## Decision table

| Condition | Action | Resolution |
| --- | --- | --- |
| `safety_flags` is non-empty | `dispatch_technician`, priority `urgent`. | `dispatched` |
| `known_bug` names KB-0471 (BMS firmware 2.3 SoC reporting freeze) and `safety_flags` is empty | No restart. Resolve, and recommend a firmware 2.4 upgrade ticket in the report. | `known_issue` |
| SoC reading disagrees with cell voltages and no known bug applies | `dispatch_technician`, priority `next-business-day`. | `dispatched` |

## Rules

- A frozen reading on a healthy pack is a reporting problem, not a safety problem. Say so in the report.
- Every alert ends with exactly one `resolve_alert` call.
