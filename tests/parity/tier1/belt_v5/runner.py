r"""The Belt v5 Tier 1 runner (phase2.9 items 2.3, 2.4; decisions 124 and 192).

    $env:UZP_TIER1_REPORT = "parity/reports/phase2/tier1-belt-v5.json"   # optional
    python -m pytest tests/parity/tier1/belt_v5

The wand's runner (`../wand_v1/runner.py`) over the Belt v5 golden: two rebuilds through the
Assets3D pipeline adapter, each script pinned by SHA-256 from the golden's manifest, on the same
staged inputs and external mesh maps the Painter recording used, then the comparison
(`tools.parity.tier1.compare`). The stack's `base_tex` fills (the colour bitmap `T_belt` in
final-UV space) are built by the pinned `painter_layer_stack.py sync`, as Painter's are. The regions
are the stack's group masks (the brass group's `M_metal`; the leather group has none and counts in
the whole-map numbers only); the normal map is the pinned export's `<prefix>_Normal`.

The golden is `phase2/tier1/belt-v5` resolved through the current envelope; until it is admitted
the runs execute its request. The request does not exist yet: the round folder the pinned scripts
read (`_tmp/claude/cintura-v5/`) was removed from Assets3D, and its files are not in the private
store (decision 192). `python -m tools.parity.recorder.script_run manifest --pilot belt --store`
writes it once the owner restores them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.adapters.assets3d.wand import REPO_ROOT
from tests.parity.tier1.wand_v1 import runner as wand_runner

GOLDEN_ID = "phase2/tier1/belt-v5"
REQUEST = (
    REPO_ROOT / "parity/envelopes/painter-12.1.5_js-api.1.1.20/requests/phase2/tier1/belt-v5.json"
)


def run(painter: Path, work: Path) -> dict[str, Any]:
    """Two rebuilds and the comparison report."""
    return wand_runner.run(painter, work, GOLDEN_ID, REQUEST)
