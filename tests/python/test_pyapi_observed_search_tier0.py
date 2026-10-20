"""R-095 P7 observed resource-search replay (phase1.24 item 4.1).

Compare both recordings against verified private records, retaining the named search gap.
"""

from __future__ import annotations

from pathlib import Path

from tests.python.conftest import Run
from tests.python.observed_replay import (
    check_observed_trace,
    compare_observed,
    observed_symbols,
    replay_observed,
    save_trace,
)

PROBE = "phase1-export-preset-search"
SEARCH_GAP = (
    "known divergence: resource.search is absent from the facade; owner "
    "phase3.1_proc-backend-seam item 2.4, decisions 113 and 164"
)
EXCLUDED: dict[str, dict[str, str]] = {
    PROBE: {"s3/search": SEARCH_GAP, "s4/search": SEARCH_GAP},
}


def test_export_preset_search_observed_replay(facade: Run, tmp_path: Path) -> None:
    replayed, golden, job = replay_observed(facade, PROBE, tmp_path)
    differences = compare_observed(replayed, golden, job, tmp_path, EXCLUDED[PROBE])
    save_trace(f"facade-observed/{PROBE}", golden, replayed, EXCLUDED[PROBE], differences)
    assert replayed["cleanup_failures"] == []
    assert not differences, "\n".join(differences)
    check_observed_trace(
        f"facade-observed/{PROBE}",
        golden["golden_id"],
        observed_symbols(replayed, golden, EXCLUDED[PROBE]),
    )
