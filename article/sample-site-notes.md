# Standing site notes

- S-142 (Rovaniemi Flats): Carrier incident CAR-55310 reported storm damage to cell NW-12 on 2026-11-05, with restoration ETA 06:00. Verify carrier restoration before troubleshooting any continuing comms loss.
- S-301 (Umea Hospital Backup): INV-01 had F-27 and is subject to urgent field ticket FT-0016; critical hospital backup load and remote_restart_policy is never, so never remotely restart. Separately, BMS-01 firmware 2.3 is affected by KB-0471 (frozen SoC reporting); 2026-11-04 diagnostic found no safety flags and cell-voltage-derived SoC 61% despite reported 100%, pack assessed healthy. Firmware 2.4 fixes reporting; follow up on upgrade.
- S-114 (Kiruna Ridge): INV-01 had two DC overvoltage events on 2026-11-05; next-business-day string inspection ticket FT-0011 opened. Diagnostic reported string 1 trending high; verify inspection and trend.
- S-118 (Lulea South): INV-02 repeat F-27 (2 occurrences in 7 days) with DC-link ripple trending up; next-business-day inspection ticket FT-0007 opened on 2026-11-05. Do not restart repeat F-27 faults; follow up on ticket.
- S-207 (Vaasa Marsh): Gateway comms loss commonly occurs most nights from 23:00 to 02:30 because cell tower NW-07 is congested. Carrier ticket CAR-55120 remains open until 2026-11-11. Do not dispatch for S-207 comms loss during this window; note the condition in the shift report.
