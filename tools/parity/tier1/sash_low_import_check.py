"""Check how Painter imports front N's Sash v5 low OBJ (decision 300 item 7, preparation only).

    python -m tools.parity.tier1.sash_low_import_check --check-only
    python -m tools.parity.tier1.sash_low_import_check

This is a private diagnostic, not a golden and not a baseline approval. It reuses the documented
BaseMesh export route of `parity/reports/phase2/base-mesh-export-control.md` and the native mesh
inspector that control qualified (pinned by SHA-256).

1. **Pins.** The OBJ and MTL that `sash_low_export.py` (commit 3afbbfbf) wrote in its private run
   `phase2__tier1__sash-v5-current__low-r1`, and that run's `export-report.json`, by SHA-256.
   The originals are only read: they are hashed before and after, and Painter opens a
   hash-checked copy made under their own base names (the OBJ's `mtllib` names the MTL).
2. **Source binding.** The source OBJ's bounds, as the inspector reads them, must equal the
   export report's Blender bounds under the exporter's pinned axes (forward -Z, up Y: OBJ
   `(x, z, -y)`) within `SOURCE_BOUNDS_TOLERANCE`, with `global_scale` 1 and transforms applied.
3. **Controls.** The comparator first reproduces the control run's own measurements on its
   hash-checked inspections: the reindexed OBJ bevelled cube is equal in every corner attribute,
   and the OBJ sphere has equal positions and UVs and normals that differ by at most
   1.0132789611816406e-06. Either control failing refuses the Painter run.
4. **Painter.** It attaches to the Painter the operator started (OCIO, remote scripting, under
   the Assets3D Painter lock) and refuses unless that build is the current envelope's, its
   colour mode is OCIO with Painter's substance configuration, and no project is open. It
   creates a project from the copy with `CREATE_SETTINGS`, reads back the texture sets, the scene
   bounding box and the migration readback, exports the BaseMesh as OBJ twice, saves (Full),
   closes, reopens, reads back again and exports a third time. Each export goes to a fresh path.
   The project is this run's own: the UUID its create recorded (and, after the save, its path)
   is checked at create, before the save, after it, at the reopen, before each export and at
   cleanup, which closes only that project and leaves any other one open (and refuses).
   Every directory and file it writes is checked to stay under the private root, with no link
   or junction below it, and outside the repository. The final hashes of the originals and of
   the staged copy must equal the pins and the first reads, or the run is refused.
5. **Comparison.** Each export against the source, as a multiset of the 4038 oriented triangles,
   each corner its position, UV and material name. Face order, index order and a cyclic
   rotation of a triangle's corners are allowed; reversed winding, welding, fitting and scale
   normalisation are not. Positions, UVs and materials must be exactly equal (float32 as the
   inspector parses them); normals are then paired by triangle and must be within
   `NORMAL_COMPONENT_BOUND`, a bound for this comparison only, never a parity tolerance.
6. **Verdict.** `status: complete` says only that the capture completed. `verdict` evaluates
   each observation: texture sets exactly `[25-Faixa-Cintura]` and its resolution, the scene
   bounds against the source, each export against the source, the repeat and the reopen
   against `r1`, and the exported UV tiles. Any failed check is listed as a difference and the
   mesh is not called consistent.

Nothing here observes Painter's internal UV or axis representation: an import conversion that
the BaseMesh export undoes is not observable through this route, and neither are per-object
transforms (an OBJ has none) nor UV tiles beyond the exported UVs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.parity.envelope.colour_sessions import matches
from tools.parity.envelope.registry import current_envelope, load_registry
from tools.parity.recorder.environment import capture_host_environment
from tools.parity.recorder.output import ensure_outside_repository, work_root
from tools.parity.recorder.probes import ProbeSession
from tools.parity.recorder.session import HttpTransport, PainterSession, RecorderError

REPO_ROOT = Path(__file__).resolve().parents[3]

SOURCE_RUN = "phase2__tier1__sash-v5-current__low-r1"
OBJ_NAME = "25-Faixa-Cintura-v5-low.obj"
OBJ_SHA256 = "646bba8546ad9dcd6475eb366fced896f35f592b088e1286d1a30ec957249944"
MTL_NAME = "25-Faixa-Cintura-v5-low.mtl"
MTL_SHA256 = "2e9174ad995c854491ac0c4e02ccc58144fe62128ee64097c5268216a575c061"
EXPORT_REPORT_NAME = "export-report.json"
EXPORT_REPORT_SHA256 = "448e46cf921bb09c1579ef68e9d38103d4192bc53c062db7d9d033ac15bdb24f"
TEXTURE_SET = "25-Faixa-Cintura"
TRIANGLES = 4038

INSPECTOR = REPO_ROOT / "scripts/tmp/commits/mesh-export-qualification-build/bin/uzp-mesh-tests.exe"
INSPECTOR_SHA256 = "957834bff2e80f63732cb5c8fa82c216b56ecb5c86079612e9a9aad1367b743b"

CONTROL_RUN = "mesh-export-qualification/run-_ddmbxhw"
CONTROL_REPORT_SHA256 = "d668b57d93f024b28442b8cf1e0d16653e6d63b93cdc5d4b0d4944eb0b14029e"
# (source inspection, r1 OBJ export inspection), as the control's report.json lists them.
CONTROLS = {
    "bevelled-cube": (
        "bevelled-cube/source-inspection/mesh-report.json",
        "bevelled-cube/r1/obj-inspection/mesh-report.json",
    ),
    "sphere": (
        "sphere/source-inspection/mesh-report.json",
        "sphere/r1/obj-inspection/mesh-report.json",
    ),
}
SPHERE_NORMAL_MAX = 1.0132789611816406e-06

CREATE_SETTINGS: dict[str, Any] = {
    "normal_map_format": "OpenGL",
    "import_cameras": False,
    "default_texture_resolution": 2048,
    "mesh_unit_scale": 1.0,
}
PHASES = ("r1", "repeat", "reopen")
OCIO_CONFIG = "resources/ocio/substance/config.ocio"

# Declared before the run. The source writes normals with 4 decimals, so they are not unit
# length; renormalising them moves a component by at most 6.1725e-05 on this source (measured
# from the inspector's reading of it). Painter's OBJ writer prints 6 decimals (half step 5e-07),
# and float32 parsing adds less than 1e-06. Sum below 6.5e-05. This bound applies to this
# comparison only.
NORMAL_COMPONENT_BOUND = 6.5e-05
# The export report's float32 Blender bounds against the OBJ's 6-decimal positions.
SOURCE_BOUNDS_TOLERANCE = 1.0e-06
# Painter's scene bounding box against the source's float32 bounds: the source values are
# about 1.25 at most (float32 step 1.2e-07), and a centre or a size adds one rounding.
SCENE_CENTER_TOLERANCE = 1.0e-06
SCENE_DIMENSION_TOLERANCE = 1.0e-06
# Read through the probe extension's owned-project form (decision 295): the UUID this run's
# own create recorded and the open project's.
GET_UUID = "substance_painter.project.get_uuid"

Vector = tuple[float, ...]
CornerKey = tuple[Vector, Vector, str]
TriangleKey = tuple[CornerKey, CornerKey, CornerKey]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def oriented_triangles(document: dict[str, Any]) -> list[tuple[TriangleKey, tuple[Vector, ...]]]:
    """Each triangle as (corner keys, corner normals), cyclically rotated to its smallest key.

    A rotation keeps the winding; the reversed order is never tried, so a flipped triangle keeps
    a different key."""
    mesh = document["mesh"]
    names = {m["index"]: m["name"] for m in document["report"]["materials"]}
    positions = mesh["positions"]
    result = []
    for obj in mesh["objects"]:
        for triangle in obj["triangles"]:
            corners = [mesh["corners"][index] for index in triangle]
            keys = [
                (tuple(positions[c["position"]]), tuple(c["uv0"]), names[c["material"]])
                for c in corners
            ]
            normals = [tuple(c["normal"]) for c in corners]
            turn = min(range(3), key=lambda i: keys[i:] + keys[:i])
            key = keys[turn:] + keys[:turn]
            normal = normals[turn:] + normals[:turn]
            result.append(((key[0], key[1], key[2]), tuple(normal)))
    return result


def bounds(points: list[Vector]) -> dict[str, list[float]]:
    return {
        "min": [min(p[i] for p in points) for i in range(len(points[0]))],
        "max": [max(p[i] for p in points) for i in range(len(points[0]))],
    }


def corner_values(document: dict[str, Any]) -> tuple[list[Vector], list[Vector]]:
    mesh = document["mesh"]
    positions = [tuple(mesh["positions"][c["position"]]) for c in mesh["corners"]]
    return positions, [tuple(c["uv0"]) for c in mesh["corners"]]


def uv_tiles(document: dict[str, Any]) -> list[int]:
    """The UDIM tiles (1001 + u + 10 v) the corners' UVs fall in."""
    _, uvs = corner_values(document)
    return sorted({1001 + math.floor(u) + 10 * math.floor(v) for u, v in uvs})


def diagnostic_counts(source: list[TriangleKey], other: list[TriangleKey]) -> dict[str, int]:
    """How many triangles match under the identity, a reversed winding, or V mirrored (V values
    rounded to 6 decimals here only): diagnostics of a failed comparison, never a pass."""

    def rotated(keys: list[CornerKey]) -> TriangleKey:
        turn = min(range(3), key=lambda i: keys[i:] + keys[:i])
        k = keys[turn:] + keys[:turn]
        return (k[0], k[1], k[2])

    def flip_v(corner: CornerKey) -> CornerKey:
        position, uv, material = corner
        return position, (uv[0], round(1.0 - uv[1], 6)), material

    def round_v(corner: CornerKey) -> CornerKey:
        position, uv, material = corner
        return position, (uv[0], round(uv[1], 6)), material

    base = Counter(source)
    rounded = Counter(rotated([round_v(c) for c in t]) for t in source)
    reversed_ = Counter(rotated([t[0], t[2], t[1]]) for t in other)
    flipped = Counter(rotated([flip_v(c) for c in t]) for t in other)
    return {
        "identity_matches": sum((base & Counter(other)).values()),
        "reversed_winding_matches": sum((base & reversed_).values()),
        "v_mirrored_matches": sum((rounded & flipped).values()),
    }


def compare(source: dict[str, Any], other: dict[str, Any], normal_bound: float) -> dict[str, Any]:
    """Oriented-triangle multiset comparison of two inspections (module docstring, step 5)."""
    a, b = oriented_triangles(source), oriented_triangles(other)
    keys_a, keys_b = [k for k, _ in a], [k for k, _ in b]
    result: dict[str, Any] = {
        "triangles": [len(a), len(b)],
        "unique_positions": [len(source["mesh"]["positions"]), len(other["mesh"]["positions"])],
        "corners": [len(source["mesh"]["corners"]), len(other["mesh"]["corners"])],
        "materials": [
            [m["name"] for m in source["report"]["materials"]],
            [m["name"] for m in other["report"]["materials"]],
        ],
        "position_uv_material_multiset_equal": Counter(keys_a) == Counter(keys_b),
        "full_multiset_equal": Counter(a) == Counter(b),
        "normal_component_bound": normal_bound,
        "normals": None,
        "within_bounds": False,
    }
    if not result["position_uv_material_multiset_equal"]:
        result["diagnostics"] = diagnostic_counts(keys_a, keys_b)
        return result
    groups: dict[TriangleKey, list[list[tuple[Vector, ...]]]] = defaultdict(lambda: [[], []])
    for key, normal in a:
        groups[key][0].append(normal)
    for key, normal in b:
        groups[key][1].append(normal)
    deltas: list[float] = []
    for left, right in groups.values():
        for na, nb in zip(sorted(left), sorted(right), strict=True):
            for ca, cb in zip(na, nb, strict=True):
                deltas.extend(abs(x - y) for x, y in zip(ca, cb, strict=True))
    worst = max(deltas, default=0.0)
    result["normals"] = {
        "components": len(deltas),
        "differing_components": sum(d != 0.0 for d in deltas),
        "max_abs": worst,
    }
    result["within_bounds"] = worst <= normal_bound
    return result


def inspect(path: Path, directory: Path) -> dict[str, Any]:
    command = [str(INSPECTOR), "import", str(path), "--mesh-unit-scale", "1"]
    proc = subprocess.run(command, capture_output=True, timeout=300, check=False)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "stdout.bin").write_bytes(proc.stdout)
    (directory / "stderr.bin").write_bytes(proc.stderr)
    if proc.returncode != 0:
        raise RecorderError(f"inspector exited {proc.returncode} on {path.name}")
    document: dict[str, Any] = json.loads(proc.stdout.decode("utf-8"))
    oriented_triangles(document)
    return document


def check_controls(control_root: Path) -> dict[str, Any]:
    """Reproduce the base-mesh control's own measurements with this comparator (step 3)."""
    report_path = control_root / "report.json"
    if digest(report_path) != CONTROL_REPORT_SHA256:
        raise RecorderError("the base-mesh control report differs from its pin")
    listed = {
        Path(f["path"]).as_posix(): f["sha256"]
        for f in json.loads(report_path.read_text(encoding="utf-8"))["files"]
    }
    results: dict[str, Any] = {}
    for name, (left, right) in CONTROLS.items():
        documents = []
        for relative in (left, right):
            if digest(control_root / relative) != listed.get(relative):
                raise RecorderError(f"control file {relative} differs from the control report")
            documents.append(json.loads((control_root / relative).read_text(encoding="utf-8")))
        results[name] = compare(documents[0], documents[1], 0.0)
    cube, sphere = results["bevelled-cube"], results["sphere"]
    if not (cube["full_multiset_equal"] and cube["within_bounds"]):
        raise RecorderError(f"control bevelled-cube not reproduced: {cube}")
    if not (
        sphere["position_uv_material_multiset_equal"]
        and not sphere["full_multiset_equal"]
        and sphere["normals"]["max_abs"] == SPHERE_NORMAL_MAX
    ):
        raise RecorderError(f"control sphere not reproduced: {sphere}")
    return results


def source_binding(document: dict[str, Any], export_report: dict[str, Any]) -> dict[str, Any]:
    """The source OBJ against the exporter's report under its pinned axes (step 2)."""
    options = export_report["export"]["options"]
    pinned = {
        "forward_axis": "NEGATIVE_Z",
        "up_axis": "Y",
        "global_scale": 1.0,
        "apply_transform": True,
    }
    problems = [f"{k} is {options.get(k)!r}" for k, v in pinned.items() if options.get(k) != v]
    (bx0, by0, bz0), (bx1, by1, bz1) = export_report["mesh"]["bounds"]
    expected = {"min": [bx0, bz0, -by1], "max": [bx1, bz1, -by0]}
    positions, _ = corner_values(document)
    measured = bounds(positions)
    delta = max(
        abs(x - y)
        for side in ("min", "max")
        for x, y in zip(expected[side], measured[side], strict=True)
    )
    if delta > SOURCE_BOUNDS_TOLERANCE:
        problems.append(f"bounds differ from the mapped Blender bounds by {delta}")
    counts = document["report"]["counts"]
    if counts["triangles"] != TRIANGLES or export_report["mesh"]["triangles"] != TRIANGLES:
        problems.append(f"triangle count {counts['triangles']}, expected {TRIANGLES}")
    if problems:
        raise RecorderError("source binding failed: " + "; ".join(problems))
    return {
        "axis_mapping": "obj = (x, z, -y) of Blender",
        "bounds": measured,
        "max_bounds_delta": delta,
        "uv_tiles": uv_tiles(document),
        "inspector_flags": document["report"]["flags"],
        "units": document["report"]["units"],
    }


def source_hashes(source_dir: Path) -> dict[str, str]:
    return {name: digest(source_dir / name) for name in (OBJ_NAME, MTL_NAME, EXPORT_REPORT_NAME)}


def check_sources(source_dir: Path) -> dict[str, str]:
    found = source_hashes(source_dir)
    pins = {OBJ_NAME: OBJ_SHA256, MTL_NAME: MTL_SHA256, EXPORT_REPORT_NAME: EXPORT_REPORT_SHA256}
    if found != pins:
        raise RecorderError(f"source hashes differ from the pins: {found}")
    return found


def scene_versus_source(box: dict[str, Any], source: dict[str, list[float]]) -> dict[str, Any]:
    """Painter's scene bounding box against the source OBJ's bounds, axis by axis."""
    centre = [(lo + hi) / 2 for lo, hi in zip(source["min"], source["max"], strict=True)]
    size = [hi - lo for lo, hi in zip(source["min"], source["max"], strict=True)]
    return {
        "painter": box,
        "source_center": centre,
        "source_dimensions": size,
        "center_delta": [p - s for p, s in zip(box["center"], centre, strict=True)],
        "dimension_ratio": [p / s for p, s in zip(box["dimensions"], size, strict=True)],
    }


def envelope_entry() -> dict[str, Any]:
    if load_registry(REPO_ROOT)["candidate"] is not None:
        raise RecorderError("an envelope refresh is active")
    entry: dict[str, Any] = current_envelope(REPO_ROOT)
    return entry


def verify(session: PainterSession, entry: dict[str, Any], colour: str) -> None:
    if current_envelope(REPO_ROOT)["envelope_id"] != entry["envelope_id"]:
        raise RecorderError("the current envelope changed during the check")
    session.verify_identity(host=capture_host_environment)
    identity = session.identity
    if identity is None or identity.build_id != entry["painter_build"]:
        raise RecorderError("the Painter build is not the current envelope's")
    if not matches(identity, colour):
        raise RecorderError(f"the Painter session is not under {colour}")


def guarded(path: Path, root: Path) -> Path:
    """`path` itself, refused unless it stays under the private root and outside the
    repository: no existing component below the root may be a link or a junction, and the
    resolved path must lie under the resolved root."""
    base = root.resolve()
    if base.is_relative_to(REPO_ROOT.resolve()):
        raise RecorderError(f"the private root {base} is inside the repository")
    relative = path.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink() or current.is_junction():
            raise RecorderError(f"{current} is a link or a junction")
    resolved = path.resolve()
    if not resolved.is_relative_to(base) or resolved.is_relative_to(REPO_ROOT.resolve()):
        raise RecorderError(f"{resolved} leaves the private root {base}")
    return path


def same_path(left: str | None, right: str | None) -> bool:
    if left is None or right is None:
        return left == right
    return Path(left).resolve() == Path(right).resolve()


def own_project(session: PainterSession, expected: dict[str, Any]) -> dict[str, Any]:
    """This run's project, by the UUID its own create recorded and the path it should have;
    refused when the open project is any other one."""
    state = session.state()
    if not state.is_open:
        raise RecorderError("no project is open")
    outcome = session.call("probe_step", step=0, call=GET_UUID, args={"owned_project": True})
    if "raised" in outcome or not isinstance(outcome.get("value"), dict):
        raise RecorderError(f"the project UUID cannot be read: {outcome}")
    value = outcome["value"]
    found = {
        "created_uuid": value["created_project_uuid"],
        "uuid": value["current_project_uuid"],
        "file_path": state.file_path,
    }
    if expected.get("uuid") is None:
        if found["created_uuid"] != found["uuid"]:
            raise RecorderError("the open project is not the one this run created")
        expected.update(uuid=found["uuid"], file_path=found["file_path"])
    if found["created_uuid"] != expected["uuid"] or found["uuid"] != expected["uuid"]:
        raise RecorderError(f"the open project UUID differs from this run's: {found}")
    if not same_path(found["file_path"], expected["file_path"]):
        raise RecorderError(f"the open project path differs from this run's: {found}")
    return found


def readbacks(session: PainterSession) -> dict[str, Any]:
    return {
        "state": asdict(session.wait_ready()),
        "texture_sets": session.call("texture_set_names"),
        "scene_bounding_box": session.call("scene_bounding_box"),
        "migration_readback": session.call("migration_readback"),
    }


def run_painter(
    session: PainterSession,
    run_dir: Path,
    root: Path,
    staged: Path,
    source_doc: dict[str, Any],
    report: dict[str, Any],
) -> None:
    entry = envelope_entry()
    colour = "ocio:" + OCIO_CONFIG
    report["identity"] = asdict(session.connect())
    verify(session, entry, colour)
    if session.state().is_open:
        raise RecorderError("a project is open in Painter; this check only creates its own")
    source_bounds = report["source"]["bounds"]
    documents: dict[str, dict[str, Any]] = {}
    expected: dict[str, Any] = {"uuid": None}
    project = guarded(run_dir / "project" / "sash-low-import.spp", root)
    checks: list[dict[str, Any]] = []
    report["project_checks"] = checks
    created = False
    try:
        report["create"] = session.call(
            "apply_step",
            step=1,
            call="substance_painter.project.create",
            args=CREATE_SETTINGS,
            resolved={"mesh": staged.as_posix()},
        )
        created = True
        session.wait_ready()
        checks.append({"at": "create", **own_project(session, expected)})
        for phase in PHASES:
            if phase == "reopen":
                checks.append({"at": "save", **own_project(session, expected)})
                project.parent.mkdir()
                report["save"] = session.call("save_as", path=project.as_posix())
                saved = session.wait_ready()
                if saved.file_path is None or Path(saved.file_path).resolve() != project.resolve():
                    raise RecorderError("the saved project path differs")
                expected["file_path"] = saved.file_path
                checks.append({"at": "saved", **own_project(session, expected)})
                session.call("close_project")
                session.wait_closed()
                session.call("open_project", path=project.as_posix())
                session.wait_ready()
                checks.append({"at": "reopen", **own_project(session, expected)})
            if phase != "repeat":
                read = readbacks(session)
                read["scene_versus_source"] = scene_versus_source(
                    read["scene_bounding_box"], source_bounds
                )
                report["readbacks"][phase] = read
            verify(session, entry, colour)
            destination = guarded(run_dir / phase / "base-mesh.obj", root)
            destination.parent.mkdir()
            exported: dict[str, Any] = {"state_before": asdict(session.wait_ready())}
            checks.append({"at": f"export {phase}", **own_project(session, expected)})
            exported["result"] = session.call("export_base_mesh", path=destination.as_posix())
            exported["state_after"] = asdict(session.wait_ready())
            report["exports"][phase] = exported
            if exported["result"]["status"] != "Success" or not destination.is_file():
                raise RecorderError(f"{phase}: BaseMesh export did not succeed: {exported}")
            exported["sha256"] = digest(destination)
            exported["size_bytes"] = destination.stat().st_size
            document = inspect(destination, guarded(run_dir / phase / "inspection", root))
            documents[phase] = document
            exported["uv_tiles"] = uv_tiles(document)
            exported["inspector_flags"] = document["report"]["flags"]
            exported["versus_source"] = compare(source_doc, document, NORMAL_COMPONENT_BOUND)
            if phase != "r1":
                exported["bytes_equal_r1"] = exported["sha256"] == report["exports"]["r1"]["sha256"]
                exported["versus_r1"] = compare(documents["r1"], document, 0.0)
            save(run_dir / "report.json", report)
    finally:
        report["cleanup"] = cleanup(session, expected, created)


def cleanup(session: PainterSession, expected: dict[str, Any], created: bool) -> dict[str, Any]:
    """Close the project only when it is provably this run's; an unrelated one stays open."""
    try:
        if not session.state().is_open:
            return {"closed": False, "open_project": None}
        if not created or expected.get("uuid") is None:
            return {"closed": False, "open_project": "not this run's (no identity recorded)"}
        try:
            found = own_project(session, expected)
        except RecorderError as error:
            return {"closed": False, "open_project": f"not this run's: {error}"}
        session.call("close_project")
        session.wait_closed()
        return {"closed": True, "open_project": found}
    except (RecorderError, OSError, ValueError, KeyError) as error:
        return {"closed": False, "error": f"{type(error).__name__}: {error}"}


def final_hash_problems(report: dict[str, Any]) -> list[str]:
    """The final hashes against the pins and the first reads; any difference refuses the run."""
    pins = {OBJ_NAME: OBJ_SHA256, MTL_NAME: MTL_SHA256, EXPORT_REPORT_NAME: EXPORT_REPORT_SHA256}
    problems = []
    before = report.get("source_hashes_before")
    after = report.get("source_hashes_after")
    if after != pins or before != pins:
        problems.append(f"source hashes {after} differ from the pins or the first read {before}")
    staged = report.get("staged_hashes_after")
    if staged != {OBJ_NAME: OBJ_SHA256, MTL_NAME: MTL_SHA256}:
        problems.append(f"staged hashes {staged} differ from the pins")
    return problems


def max_abs(values: list[float]) -> float:
    return max((abs(v) for v in values), default=math.inf)


def verdict(report: dict[str, Any]) -> dict[str, Any]:
    """What the observations support, check by check. A failed check is a recorded difference;
    the mesh is called consistent only when every check holds."""
    reads, exports = report.get("readbacks", {}), report.get("exports", {})
    checks: dict[str, bool] = {}
    for phase in ("r1", "reopen"):
        read = reads.get(phase)
        if read is None:
            checks[f"{phase}: readbacks captured"] = False
            continue
        names = [s["name"] for s in read["texture_sets"]]
        checks[f"{phase}: texture sets == [{TEXTURE_SET}]"] = names == [TEXTURE_SET]
        sets = read["migration_readback"]["texture_sets"]
        resolution = CREATE_SETTINGS["default_texture_resolution"]
        checks[f"{phase}: resolution == {resolution}"] = sets.get(TEXTURE_SET, {}).get(
            "resolution"
        ) == [resolution, resolution]
        scene = read["scene_versus_source"]
        checks[f"{phase}: scene centre within {SCENE_CENTER_TOLERANCE}"] = (
            max_abs(scene["center_delta"]) <= SCENE_CENTER_TOLERANCE
        )
        dimension_delta = [
            p - s
            for p, s in zip(scene["painter"]["dimensions"], scene["source_dimensions"], strict=True)
        ]
        checks[f"{phase}: scene dimensions within {SCENE_DIMENSION_TOLERANCE}"] = (
            max_abs(dimension_delta) <= SCENE_DIMENSION_TOLERANCE
        )
    for phase in PHASES:
        exported = exports.get(phase)
        if exported is None or "versus_source" not in exported:
            checks[f"{phase}: export compared"] = False
            continue
        checks[f"{phase}: export versus source within bounds"] = exported["versus_source"][
            "within_bounds"
        ]
        checks[f"{phase}: export UV tiles == [1001]"] = exported["uv_tiles"] == [1001]
        if phase != "r1":
            checks[f"{phase}: export equal to r1"] = exported["versus_r1"]["full_multiset_equal"]
    differences = sorted(name for name, held in checks.items() if not held)
    return {
        "checks": checks,
        "differences": differences,
        "import_consistent": report.get("status") == "complete" and not differences,
        "settings_passed": CREATE_SETTINGS,
        "settings_read_back": "texture-set resolution only; no documented getter reads the "
        "normal format, import_cameras or mesh_unit_scale (scene bounds are their only trace)",
        "not_observed": [
            "an import conversion that the BaseMesh export undoes",
            "per-object transforms (an OBJ has none)",
            "UV tiles other than through the exported UVs (TextureSet.has_uv_tiles is not read)",
            "the historical round's OBJ and any baseline",
        ],
    }


def prepare(root: Path, check_only: bool) -> tuple[Path, dict[str, Any]]:
    """Every check that needs no Painter; returns the fresh run directory and its report."""
    if digest(INSPECTOR) != INSPECTOR_SHA256:
        raise RecorderError("the mesh inspector differs from its pin")
    source_dir = guarded(root / SOURCE_RUN, root)
    report: dict[str, Any] = {
        "status": "running",
        "golden": False,
        "check_only": check_only,
        "script_sha256": digest(Path(__file__)),
        "inspector_sha256": INSPECTOR_SHA256,
        "create_settings": CREATE_SETTINGS,
        "normal_component_bound": NORMAL_COMPONENT_BOUND,
        "source_hashes_before": check_sources(source_dir),
        "controls": check_controls(guarded(root / CONTROL_RUN, root)),
        "readbacks": {},
        "exports": {},
        "started_at": time.time(),
    }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = guarded(
        root / "sash-low-import-check" / f"{'check' if check_only else 'run'}-{stamp}", root
    )
    staged_dir = guarded(run_dir / "source", root)
    staged_dir.mkdir(parents=True)
    guarded(staged_dir, root)
    for name in (OBJ_NAME, MTL_NAME):
        shutil.copyfile(source_dir / name, guarded(staged_dir / name, root))
    if digest(staged_dir / OBJ_NAME) != OBJ_SHA256 or digest(staged_dir / MTL_NAME) != MTL_SHA256:
        raise RecorderError("the staged copy differs from the pins")
    return run_dir, report


def execute(
    root: Path, check_only: bool, session_factory: Callable[[], PainterSession]
) -> tuple[Path | None, dict[str, Any] | None]:
    """The whole check; the report is written even when a step or the final reads fail."""
    try:
        run_dir, report = prepare(root, check_only)
    except (RecorderError, OSError, ValueError, KeyError) as error:
        print(f"refused before the run: {type(error).__name__}: {error}", file=sys.stderr)
        return None, None
    staged = run_dir / "source" / OBJ_NAME
    try:
        source_doc = inspect(staged, guarded(run_dir / "source-inspection", root))
        export_report = json.loads(
            (root / SOURCE_RUN / EXPORT_REPORT_NAME).read_text(encoding="utf-8")
        )
        report["source"] = source_binding(source_doc, export_report)
        save(run_dir / "report.json", report)
        if not check_only:
            run_painter(session_factory(), run_dir, root, staged, source_doc, report)
            if not report["cleanup"].get("closed"):
                raise RecorderError(f"the project was not closed: {report['cleanup']}")
        report["status"] = "complete"
    except (RecorderError, OSError, ValueError, KeyError) as error:
        report["status"] = "refused"
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        try:
            report["staged_hashes_after"] = {
                name: digest(run_dir / "source" / name) for name in (OBJ_NAME, MTL_NAME)
            }
            report["source_hashes_after"] = source_hashes(root / SOURCE_RUN)
        except OSError as error:
            report["final_hash_error"] = f"{type(error).__name__}: {error}"
        problems = final_hash_problems(report)
        if problems:
            report["status"] = "refused"
            report["final_hash_problems"] = problems
        if not check_only:
            report["verdict"] = verdict(report)
        report["finished_at"] = time.time()
        save(run_dir / "report.json", report)
    return run_dir, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check-only", action="store_true", help="no Painter call")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    root = ensure_outside_repository(work_root(REPO_ROOT))
    run_dir, report = execute(
        root, args.check_only, lambda: ProbeSession(HttpTransport(), verify_calls=True)
    )
    if run_dir is None or report is None:
        return 2
    print(f"{report['status']}: {run_dir / 'report.json'}")
    if "verdict" in report:
        print(f"import consistent: {report['verdict']['import_consistent']}")
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
