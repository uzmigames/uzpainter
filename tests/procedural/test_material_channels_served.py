"""Item 2.16 of `phase3.3_procedural-families`: the felt and leather grain material fills served
from the project-private snapshots of one Painter session, compared with that session's goldens
(decision 431).

The projects are the private derived artifacts of
`tests/python/capture_material_channels_session.py`: one UzPainter project per material on the
authored plane at 128 px, holding its `MATERIAL` captures at the defaults and at the first preset,
made in the Painter session that also records the Tier 0 goldens `material-channels-*`. They are
resolved from the private oracle store by hash and size, the receipts by their bytes; until that
session is recorded and pinned here (`PROJECT_BLOBS`, `RECEIPTS`), and without the goldens, the
tests skip as `oracle_unavailable`. They then also need the support check's same-session refusal
lifted for the recorded configuration (`src/evaluator/support.cpp`). Messages name counts, maps and
owners only; no Painter value is printed.

- Every snapshot of each project is `Stored` and `Evaluate`d byte-equal to its Painter export.
- Each golden's material fill, rebuilt through the facade (`set_material_source`, and
  `apply_preset` of the first preset for the `-preset` goldens), exports every map byte-equal to
  r1 and r2 on the CPU lane and on a DX12 engine, which are byte-equal to each other.
- A single changed field is refused before any change: another preset, another output mapped to a
  channel, another texture set resolution and a parameter edit.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.export.conftest import export_tests as export_tests
from tests.procedural.test_material_channel_rules import CHANNELS, export_config, exported, pixels
from tests.procedural.test_proc_snapshot_served_capture import (
    export_float32,
    recordings_dir,
    served_rows,
)
from tests.python.conftest import Run
from tests.python.conftest import facade as facade
from tests.python.conftest import pyapi_runner as pyapi_runner
from tests.python.test_pyapi_native import ok
from tools.parity.fit.material_channels import exports
from tools.parity.recorder.material_survey import MATERIAL_URLS
from tools.parity.store.store import OracleStore, Status, locate, resolve_oracle
from tools.parity.tier0_semantics.material_channels import MAPS, PREFIX_NAME, STATES

# The one-session capture of 2026-11-11 (`tests/python/capture_material_channels_session.py`):
# one destination project per material, and the capture receipts by capture (SHA-256, size).
PROJECT_BLOBS: dict[str, dict[str, Any]] = {
    family: {"record_id": f"material-channels-{family}-project", "sha256": "", "size_bytes": 0}
    for family in MATERIAL_URLS
}
RECEIPTS: dict[str, tuple[str, int]] = {}

BUILD = """
project.open(WORK + "/material-channels-{family}.uzp")
stack = ts.get_active_stack()
fill = ls.insert_fill(top(stack))
fill.set_material_source(resource.ResourceID.from_url({url!r}))
m = fill.get_material_source()
presets = m.get_preset_list()
if {preset!r}:
    m.apply_preset(presets[0])
r = {{}}
r["set"] = ts.all_texture_sets()[0].name()
r["active"] = sorted(c.name for c in fill.active_channels)
r["colours"] = sorted(
    (name, v.color_space.name)
    for name, v in m.get_parameters().items()
    if isinstance(v, cm.Color)
)
revision = uzpainter.project.revision()
r["other_preset"] = raises(m.apply_preset, presets[1]) if len(presets) > 1 else "no other preset"
outputs = m.image_outputs
mapped = m.output_mapping[CT.BaseColor]
other = [o for o in outputs if o != mapped][0]
r["other_output"] = raises(m.output_mapping.__setitem__, CT.BaseColor, other)
r["resolution"] = raises(ts.all_texture_sets()[0].set_resolution, ts.Resolution(256, 256))
name = sorted(m.get_parameters())[0]
r["parameter"] = raises(m.set_parameters, {{name: m.get_parameters()[name]}})
r["unchanged"] = uzpainter.project.revision() == revision
project.save_as(WORK + "/{state}.uzp")
project.close()
result = r
"""


def oracle_store() -> OracleStore:
    store = locate()
    if store is None:
        pytest.skip("oracle_unavailable: no private store on this machine")
    return store


def staged_project(store: OracleStore, tmp_path: Path, family: str) -> Path:
    blob = PROJECT_BLOBS[family]
    if not blob["sha256"]:
        pytest.skip("oracle_unavailable: the item-2.16 session is not recorded yet")
    resolved = resolve_oracle(store, blob)
    if resolved.status != Status.AVAILABLE or resolved.path is None:
        pytest.skip(f"oracle_unavailable: {resolved.reason}")
    target = tmp_path / f"material-channels-{family}.uzp"
    target.write_bytes(resolved.path.read_bytes())
    data = target.read_bytes()
    if (hashlib.sha256(data).hexdigest(), len(data)) != (blob["sha256"], blob["size_bytes"]):
        pytest.fail("the copied capture project differs from its store record", pytrace=False)
    return target


def receipts() -> dict[str, Path]:
    """The work directory of each receipt in `RECEIPTS`, found by its bytes."""
    wanted = {value: name for name, value in RECEIPTS.items()}
    found: dict[str, Path] = {}
    root = recordings_dir()
    if root.is_dir():
        for receipt in sorted(root.glob("*/capture.json")):
            data = receipt.read_bytes()
            name = wanted.get((hashlib.sha256(data).hexdigest(), len(data)))
            if name is not None:
                found[name] = receipt.parent
    return found


@pytest.mark.parametrize("family", list(MATERIAL_URLS))
def test_every_snapshot_is_its_painter_export(
    family: str,
    procedural_tests: Path,
    tmp_path: Path,
) -> None:
    """Every snapshot of the family's project is `Stored` and `Evaluate`d byte-equal to the float32
    export its receipt pairs with its signature, both exports equal (the `assets snapshot`
    verification after reopen, repeated here over the stored project)."""
    store = oracle_store()
    project = staged_project(store, tmp_path, family)
    found = receipts()
    names = [family, family + "-preset"]
    if any(name not in found for name in names):
        pytest.skip("oracle_unavailable: the capture receipts are not on this machine")
    rows = served_rows(procedural_tests, project)
    keys = {row["signature_sha256"] for row in rows}
    matched: set[str] = set()
    for name in names:
        work = found[name]
        receipt = json.loads((work / "capture.json").read_text(encoding="utf-8"))
        for capture in receipt["captures"]:
            signature = capture["signature"]
            channels = int(signature["output"]["channels"])
            first = export_float32(work / capture["file"], channels)
            assert first == export_float32(work / capture["repeat"], channels), capture["file"]
            served = [row for row in rows if row["signature"] == signature]
            assert len(served) == 1, f"{name}/{capture['file']}: {len(served)} entries"
            expected = hashlib.sha256(first).hexdigest()
            assert served[0]["stored_sha256"] == expected, served[0]["signature_sha256"]
            assert served[0]["evaluated"]["sha256"] == expected, served[0]["signature_sha256"]
            matched.add(served[0]["signature_sha256"])
    assert matched == keys, f"{len(keys - matched)} snapshots without a receipt export"


@pytest.mark.parametrize("state", list(STATES))
def test_served_material_fill_equals_its_session_golden(
    state: str,
    facade: Run,  # noqa: F811
    export_tests: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    family, preset = STATES[state]
    store = oracle_store()
    staged_project(store, tmp_path, family)
    try:
        golden = exports(store, PREFIX_NAME + state)
    except (KeyError, FileNotFoundError, ValueError) as error:
        pytest.skip(f"oracle_unavailable: {error}")
    r: dict[str, Any] = ok(
        facade(BUILD.format(url=MATERIAL_URLS[family], preset=preset, state=state, family=family))
    )
    assert r["unchanged"]
    for field in ("other_preset", "other_output", "resolution", "parameter"):
        if r[field] == "no other preset":
            continue
        assert r[field].startswith(("NotYetSupported", "UnsupportedProcedural")), field
    project = tmp_path / f"{state}.uzp"
    lanes = {}
    for backend in ("cpu", "dx12"):
        out = tmp_path / f"out-{backend}"
        out.mkdir()
        config = tmp_path / f"config-{backend}.json"
        config.write_text(json.dumps(export_config(out, r["set"])), encoding="utf-8")
        lanes[backend] = exported(export_tests, project, config, backend)
    for name in lanes["cpu"]:
        assert lanes["cpu"][name].read_bytes() == lanes["dx12"][name].read_bytes(), name
    by_map = {f"documentMap/{name}:{layout}": name for name, layout in CHANNELS.values()}
    assert set(by_map) == set(MAPS)
    misses: dict[str, int] = {}
    for map_name, file_name in by_map.items():
        ours = pixels(lanes["cpu"][file_name]).reshape(-1)
        for recording in ("r1", "r2"):
            theirs = golden[(recording, map_name)].astype(np.float32).reshape(-1)
            assert ours.shape == theirs.shape, (map_name, recording)
            misses[f"{map_name} {recording}"] = int(
                (ours.view(np.uint32) != theirs.view(np.uint32)).sum()
            )
    assert not any(misses.values()), f"{state}: components that differ {misses}"
