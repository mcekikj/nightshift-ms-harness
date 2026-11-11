"""Shared settings: where the Night Shift code lives, and the name of the memory store.

The experiment imports the `nightshift` package from the published Night Shift repository. It is found, in order:

1. `NIGHTSHIFT_ROOT`, if set;
2. the parent folder, when this folder lives inside the repository (the published layout);
3. a sibling folder named `nightshift-harness` (the layout used during the experiment).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CROSSOVER_DIR = HERE / "crossover"
RESULTS_DIR = HERE / "results"
MEMORY_STORE = "nightshift-memory"


def _find_nightshift_root() -> Path:
    candidates = [Path(os.environ["NIGHTSHIFT_ROOT"])] if os.environ.get("NIGHTSHIFT_ROOT") else []
    candidates += [HERE.parent, HERE.parent / "nightshift-harness"]
    for root in candidates:
        if (root / "nightshift" / "agent.py").is_file():
            return root.resolve()
    raise ImportError(
        "The Night Shift code was not found. Clone https://github.com/mcekikj/nightshift-ms-harness next to this folder "
        "as `nightshift-harness`, put this folder inside it, or set NIGHTSHIFT_ROOT."
    )


NS_ROOT = _find_nightshift_root()
if str(NS_ROOT) not in sys.path:
    sys.path.append(str(NS_ROOT))  # after this folder, so nothing here is shadowed by a Night Shift script of the same name
