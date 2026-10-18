r"""The Sash v5 Tier 1 runner (phase2.9 items 2.3, 2.4; decisions 124, 192 and 260).

    $env:UZP_TIER1_REPORT = "parity/reports/phase2/tier1-sash-v5.json"   # optional
    python -m pytest tests/parity/tier1/sash_v5

The wand's runner (`../wand_v1/runner.py`) over the Sash v5 golden, the piece of the Skeletal Mage
that replaced Belt v5 as the phase2.9 pilot (owner, 2026-10-18; decision 260): two rebuilds
through the Assets3D pipeline adapter, each script pinned by SHA-256 from the golden's manifest,
on the same staged inputs and external mesh maps the Painter recording used, then the comparison
(`tools.parity.tier1.compare`). The stack's `base_tex` fills (the colour bitmap `T_sash` in
final-UV space) are built by the pinned `painter_layer_stack.py sync`, as Painter's are. The
regions are the stack's group masks (the hem-leather group's `M_hem`; the cloth group has none and
counts in the whole-map numbers only); the normal map is the pinned export's `<prefix>_Normal`.

The golden is `phase2/tier1/sash-v5` resolved through the current envelope; until it is admitted
the runs execute its request. The request does not exist yet: the sash was painted in the belt's
waist-v5 round, whose folder (`_tmp/claude/cintura-v5/`) was removed from Assets3D (decision 192).
`python -m tools.parity.recorder.script_run manifest --pilot sash --store` writes it once the
owner restores the round's arguments files, low, AO and the sash's masks (decision 260).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.adapters.assets3d.wand import REPO_ROOT
from tests.parity.tier1.wand_v1 import runner as wand_runner

GOLDEN_ID = "phase2/tier1/sash-v5"
REQUEST = (
    REPO_ROOT / "parity/envelopes/painter-12.1.5_js-api.1.1.20/requests/phase2/tier1/sash-v5.json"
)


def run(painter: Path, work: Path) -> dict[str, Any]:
    """Two rebuilds and the comparison report."""
    return wand_runner.run(painter, work, GOLDEN_ID, REQUEST)
