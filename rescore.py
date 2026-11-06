#!/usr/bin/env python
"""Re-score an evaluation folder from its audit logs after a scenario's ground truth changed.

    python rescore.py results/20261105-140331
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from evaluate import summary_table
from nightshift.world import World

ROOT = Path(__file__).resolve().parent


def replay(scenario_id: str, audit_path: Path) -> dict:
    world = World.load(ROOT / "scenarios" / f"{scenario_id}.json")
    for x in json.loads(audit_path.read_text(encoding="utf-8")):
        if x["tool"] == "resolve_alert":
            world.resolve(x["alert"], x["resolution"], x["note"])
        elif x["tool"] == "dispatch_technician":
            world.dispatch(x["site"], x["priority"], x["reason"])
        elif x["tool"] == "restart_device":
            world.restart(x["site"], x["device"], x["reason"])
    return world.score()


def main(folder: str) -> int:
    out_dir = Path(folder)
    results = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))
    for r in results:
        audit = out_dir / f"{r['agent']}-run{r.get('run', 1)}" / f"{r['scenario']}.audit.json"
        if audit.exists():
            r["score"] = replay(r["scenario"], audit)
    (out_dir / "results.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    table = summary_table(results)
    (out_dir / "summary.md").write_text(f"# Evaluation {out_dir.name} (rescored)\n\nmodel: {results[0]['model']}\n\n{table}\n", encoding="utf-8")
    print(table)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
