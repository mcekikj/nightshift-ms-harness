# Night shift report shift-02 (2026-11-04, 22:00–06:00)

## Summary
All 6 of 6 open alerts were resolved. Three technician tickets were created: repeat inverter fault inspection at S-118 (next business day), string inspection at S-114 (next business day), and urgent on-site assessment at hospital backup site S-301. S-207 was resolved under its standing carrier-congestion note; S-142 is affected by confirmed storm damage to carrier cell NW-12, with restoration estimated at 06:00. Day shift should confirm the S-142 restoration and follow up on all three field tickets.

## Alerts
| Alert | Site | Device | Kind | Resolution | Action taken |
| --- | --- | --- | --- | --- | --- |
| A-2001 | S-207 Vaasa Marsh | GW-01 | comms_loss | known_issue | No action; standing NW-07 congestion window and open carrier ticket CAR-55120 explain the loss. |
| A-2002 | S-118 Lulea South | INV-02 | inverter_fault (F-27) | dispatched | Repeat fault (2 occurrences in 7 days); no restart. Created next-business-day ticket FT-0007 to inspect rising DC-link ripple. |
| A-2003 | S-114 Kiruna Ridge | INV-01 | dc_overvoltage | dispatched | Closed under next-business-day string-inspection ticket FT-0011 after same-device repeat count reached 2; string 1 was trending high. |
| A-2004 | S-114 Kiruna Ridge | INV-01 | dc_overvoltage | dispatched | Closed under the same FT-0011 dispatch for the repeated overvoltage condition; no restart. |
| A-2005 | S-301 Umea Hospital Backup | INV-01 | inverter_fault (F-27) | dispatched | Created urgent ticket FT-0016. No restart because the site is critical-load and remote restart policy is never. |
| A-2006 | S-142 Rovaniemi Flats | GW-01 | comms_loss | carrier_outage | No site action; carrier incident CAR-55310 reports storm damage to cell NW-12, ETA 06:00. |

## Approvals requested
- Dispatch request for S-118 INV-02: next-business-day; ticket FT-0007 was created.
- Dispatch request for S-114 INV-01: next-business-day; ticket FT-0011 was created.
- Dispatch request for S-301 INV-01: urgent; ticket FT-0016 was created due to hospital critical-load status and restart prohibition.
- No remote restart was requested.

## Follow-ups for the day shift
1. Follow up on ticket FT-0016 (urgent) for the stopped hospital backup inverter at S-301.
2. Track next-business-day ticket FT-0007 for repeat F-27 and rising DC-link ripple at S-118.
3. Track next-business-day ticket FT-0011 for S-114 string inspection; check the string 1 voltage trend.
4. Confirm whether carrier incident CAR-55310 is cleared and S-142 comms restored after the 06:00 ETA.
5. Continue the existing S-301 BMS-01 firmware 2.4 upgrade follow-up for KB-0471.

## Notes for the next night shift
- S-207: standing NW-07 congestion and carrier ticket CAR-55120 remain relevant; do not dispatch for comms loss during the documented 23:00–02:30 window.
- S-142: at shift end, CAR-55310 was reported as storm damage to NW-12 with ETA 06:00; verify restoration before treating later comms loss as a fresh site fault.
