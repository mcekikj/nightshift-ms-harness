---
name: comms-loss-triage
description: Runbook for site communication loss alerts (kind "comms_loss", gateway GW-xx not reporting). Load it before acting on any comms loss alert.
---

# Communication loss triage runbook

## Always first

1. Read the memory file `site-notes.md`. Standing notes about nightly flaps or open carrier tickets override everything below.
2. Call `get_site_profile` and `run_remote_diagnostic` for the gateway.

## Decision table

| Condition | Action | Resolution |
| --- | --- | --- |
| A standing note says the site drops in this window and a carrier ticket is open | No action. Mention the ticket in the report. | `known_issue` |
| `carrier_status` reports an incident or outage | No action. Note the incident id and ETA in the report. | `carrier_outage` |
| No carrier incident, `out_of_band_reachable` true, site policy allows restarts | Request `restart_device` for the gateway (needs approval). Then `get_telemetry` to confirm `state` is `online`. | `restarted` |
| No carrier incident and out-of-band restart is impossible or did not help | `dispatch_technician`, priority `next-business-day` (`urgent` if the site has a critical load). | `dispatched` |

## Rules

- Do not dispatch for a comms loss that a standing note already explains.
- Every alert ends with exactly one `resolve_alert` call.
