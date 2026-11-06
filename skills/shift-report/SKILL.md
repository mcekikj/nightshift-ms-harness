---
name: shift-report
description: How to write the end-of-shift report and what to keep in the memory file site-notes.md. Load it when all alerts are resolved and the report is the remaining task.
---

# Shift report

Write the report with `file_access_write` to `reports/<shift-id>.md` (for example `reports/shift-01.md`). Use this structure:

```markdown
# Night shift report <shift-id> (<date>, <window>)

## Summary
One paragraph: how many alerts, how many resolved, anything the day shift must pick up first.

## Alerts
| Alert | Site | Device | Kind | Resolution | Action taken |
| --- | --- | --- | --- | --- | --- |

## Approvals requested
Bullet list of every restart or dispatch you asked approval for, with the decision.

## Follow-ups for the day shift
Numbered list (tickets to open, firmware upgrades, site visits to confirm).

## Notes for the next night shift
Durable facts learned tonight.
```

## Memory

Keep durable, site-specific facts in the memory file `site-notes.md` (one bullet per site, newest first). Examples: standing carrier tickets, nightly flaps, policy reminders, repeat offenders. Read it at the start of every shift and update it at the end. Do not store alert-by-alert detail there; that belongs in the report.
