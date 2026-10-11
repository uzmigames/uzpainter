"""P0-FEAS-RENDER acceptance, the entry gate of P3-PATHTRACER (task
`phase0.9_render-reference-capture`, `docs/dag.md`, decisions 033 and 063).

The record `parity/reports/phase0/gate-p3-pathtracer-entry.md` names its prerequisites and its
three children, which must be archived, and every evidence path it cites must exist. On the
owner's machine (private store) every admitted Iray reference must name the qualified procedure,
its settings sheet hash and its `uncontrolled` settings (item 3.1), every stability capture of
decision 052's capture request must resolve in the store (item 3.4), and so must the read-back of
the qualification sphere's template-default material (item 3.2, decision 068).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from tools.parity.recorder.iray import settings_sheet
from tools.parity.recorder.job import load_job
from tools.parity.render_procedure.noise import private_record
from tools.parity.render_procedure.references import (
    TEMPLATE_DEFAULT_MANIFEST,
    reference_manifests,
    stability_manifests,
)
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.manifest import verify
from tools.parity.store.store import Status, locate

RECORD = REPO_ROOT / "parity" / "reports" / "phase0" / "gate-p3-pathtracer-entry.md"
ARCHIVE = REPO_ROOT / ".rulebook" / "archive"
PREREQUISITES = ("phase0.3_painter-oracle-recorder", "phase0.5_private-oracle-store")
CHILDREN = (
    "phase0.6_render-reference-procedure",
    "phase0.7_render-reference-captures",
    "phase0.8_render-reference-fits",
)
PROCEDURE = "iray-capture/1"


def archived() -> set[str]:
    return {re.sub(r"^\d{4}-\d{2}-\d{2}-", "", p.name) for p in ARCHIVE.iterdir() if p.is_dir()}


def needs_store() -> Any:
    store = locate()
    if store is None:
        pytest.skip("no private oracle store on this machine (hosted CI, decision 028)")
    return store


def test_prerequisites_and_children_are_archived_and_named() -> None:
    text = RECORD.read_text(encoding="utf-8")
    done = archived()
    for task in PREREQUISITES + CHILDREN:
        assert task in done, f"{task} is not archived"
        assert f"`{task}`" in text, f"{task} is not named in the gate record"


def test_cited_evidence_paths_exist() -> None:
    text = RECORD.read_text(encoding="utf-8")
    cited = set(re.findall(r"\| `([\w.-]+/[\w./-]+\.(?:md|json|py))`", text))
    assert len(cited) >= 8
    for path in sorted(cited):
        assert (REPO_ROOT / Path(path)).is_file(), f"cited evidence {path} does not exist"


@pytest.mark.parametrize("path", reference_manifests(), ids=lambda p: p.stem)
def test_admitted_reference_names_procedure_sheet_and_uncontrolled(path: Path) -> None:
    """Item 3.1, on the private record of each admitted reference golden."""
    store = needs_store()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    settings = {s["name"]: s["value"] for s in manifest["applied_settings"]}
    assert settings["capture.procedure"] == PROCEDURE
    assert manifest["uncontrolled_settings"] == ["random_seed"]
    sheet = settings_sheet(load_job(path))
    record = private_record(store, manifest)
    outputs = [
        o for r in record["recordings"] for o in r["outputs"] if o["kind"] == "iray_reference"
    ]
    assert len(outputs) == 3
    for output in outputs:
        assert output["settings_sheet_sha256"] == sheet.sha256
        assert output["uncontrolled_settings"] == manifest["uncontrolled_settings"]
        assert output["current_frame_verified"] is True


@pytest.mark.parametrize("path", stability_manifests(), ids=lambda p: p.stem)
def test_stability_captures_resolve_in_the_store(path: Path) -> None:
    """Item 3.4: two renders per stability golden, every blob available."""
    store = needs_store()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    renders = [r for r in manifest["private_records"] if r["kind"] == "iray_reference"]
    assert len(renders) == 2
    assert all(r.status is Status.AVAILABLE for r in verify(store, manifest))


def test_template_default_material_resolves_in_the_store() -> None:
    """Item 3.2 (decisions 063, 068): the read-back of the qualification sphere's material, every
    blob available, the five maps identical in both recordings."""
    store = needs_store()
    manifest = json.loads(TEMPLATE_DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    assert all(r.status is Status.AVAILABLE for r in verify(store, manifest))
    maps = {r["record_id"]: r["sha256"] for r in manifest["private_records"]}
    first = {k[3:]: v for k, v in maps.items() if k.startswith("r1-")}
    assert len(first) == 5
    assert first == {k[3:]: v for k, v in maps.items() if k.startswith("r2-")}
