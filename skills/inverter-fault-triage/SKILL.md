---
name: inverter-fault-triage
description: Runbook for inverter alerts (kind "inverter_fault" with codes F-27, F-41 and others, and kind "dc_overvoltage"). Load it whenever an open alert concerns an inverter before deciding on a restart or a dispatch.
---

# Inverter fault triage runbook

## Always first

1. Call `get_site_profile` for the site. Read `remote_restart_policy` and `critical_load`.
2. Call `run_remote_diagnostic` for the faulted device. Read `classification`, `safe_to_restart` and `occurrences_7d`.
3. Check the memory file `site-notes.md` for standing notes about the site.

## Decision table

| Condition | Action | Resolution |
| --- | --- | --- |
| `critical_load` is set, or `remote_restart_policy` is `never` | Never restart remotely. `dispatch_technician` with priority `urgent`. | `dispatched` |
| `remote_restart_policy` is `dispatcher-sign-off` and a restart would be needed | Do not restart on your own authority. `dispatch_technician`, priority `next-business-day` unless the site is dark. | `dispatched` |
| F-27 (DC link soft fault), `safe_to_restart` true, first occurrence in 7 days | Request `restart_device` (this needs approval). After the restart, call `get_telemetry` and confirm `state` is `running`. | `restarted` |
| F-27 second or later occurrence in 7 days | Do not restart again. `dispatch_technician`, priority `next-business-day`. | `dispatched` |
| F-41 (DC bus capacitor degraded) or any `classification` of `hardware degradation` | Never restart. `dispatch_technician`, priority `next-business-day`. | `dispatched` |
| Restart approved but telemetry still shows `fault` afterwards | `dispatch_technician`, priority `next-business-day`. | `dispatched` |

## DC overvoltage events (kind `dc_overvoltage`)

| Condition | Action | Resolution |
| --- | --- | --- |
| Single event, diagnostic says `cleared` true and `repeat_count_shift` is 1 | No action. | `transient` |
| `repeat_count_shift` is 2 or more (second event on the same device in one shift) | `dispatch_technician`, priority `next-business-day`, for a string inspection. Close every overvoltage alert on that device under that dispatch. | `dispatched` |
| Event not cleared, or string voltages still above limit | `dispatch_technician`, priority `urgent`. | `dispatched` |

Never restart an inverter for an overvoltage event; a restart does not change string voltage.

## Rules

- A restart is a risky action. Only request it when the table says so, and give a one-line reason.
- If the operator denies a restart, fall back to a dispatch and say so in the report.
- Every alert ends with exactly one `resolve_alert` call.
