r"""The Sash v5 Tier 1 runner (phase2.9 items 2.3, 2.4; decisions 124, 192, 260 and 399).

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

The golden is the re-run waist-v5 round, `phase2/tier1/sash-v5-current` (decision 399: the
owner's changed baseline; the original round's inputs are lost, decisions 192 and 260). It was
recorded under OCIO with Painter's substance configuration, so every rebuild runs with `OCIO`
naming that configuration (`painter_ocio`). The Sash is UV-islanded, so production UzPainter
refuses its five-map export (decisions 245, 259); every export here is the diagnostic measure
export (decision 286), whose receipt must be `non_conformant` and name only those two refusals,
and a pass is a pass under EXC-012 (decision 399), never an exact one.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from python.uzpainter_facade.bitmap_defaults import PAINTER_OCIO_CONFIG_SHA256
from tests.adapters.assets3d.wand import PAINTER_OCIO, REPO_ROOT
from tests.parity.tier1.wand_v1 import runner as wand_runner
from tools.parity.recorder.launcher import default_painter_exe
from tools.parity.tier1.compare import CandidateRun

GOLDEN_ID = "phase2/tier1/sash-v5-current"
REQUEST = (
    REPO_ROOT
    / "parity/envelopes/painter-12.2.0_js-api.1.1.20-env-a981b586eae7/requests/phase2/tier1"
    / "sash-v5-current.json"
)

Evidence = tuple[
    dict[str, object],
    tuple[CandidateRun, CandidateRun],
    wand_runner.Reopen | None,
]


def painter_ocio() -> Path:
    """Painter's substance configuration, which the manifest applies as `OCIO`: skipped where it
    is absent or is not the pinned configuration."""
    config = default_painter_exe().parent / PAINTER_OCIO
    if not config.is_file():
        pytest.skip(f"Painter's OCIO configuration is not at {config}")
    if hashlib.sha256(config.read_bytes()).hexdigest() != PAINTER_OCIO_CONFIG_SHA256:
        pytest.skip(f"{config} is not the pinned substance configuration")
    return config


def production(
    painter: Path, work: Path
) -> tuple[dict[str, Any], tuple[CandidateRun, CandidateRun]]:
    """The report and the two rebuilds, every export the production export (decisions 414, 417:
    conformant under EXC-013 and EXC-014, each map judged with the exceptions its receipt names),
    under the manifest's `OCIO`."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("OCIO", str(painter_ocio()))
        return wand_runner.compared(painter, work, GOLDEN_ID, REQUEST)


def run(painter: Path, work: Path) -> Evidence:
    """The report, the two rebuilds and the first rebuild's save/reopen record, every export the
    diagnostic measure export (decisions 286, 399), under the manifest's `OCIO`."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("OCIO", str(painter_ocio()))
        return wand_runner.reopened_compared(painter, work, GOLDEN_ID, REQUEST, diagnostic=True)
