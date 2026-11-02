r"""Export the Sash v5 low to OBJ/MTL from the preserved `.blend` (decision 300 item 7).

    python -m tools.parity.tier1.sash_low_export --blender <blender.exe> --assets-root <Assets3D>
        [--run NAME] [--expect <earlier run>\export-record.json] [--store DIR] [--dry-run]

Decision 300 item 7 gives `phase2/tier1/sash-v5-current` "the piece's low, exported from the
stored `.blend` by a committed deterministic script". This module is the host half of that
script; the Blender half, `sash_low_blender.py`, holds the object, material, modifier, UV,
transform and option pins and runs only inside Blender. The result is a current reference: it is
not the round's lost OBJ, and nothing here claims it equals that file or the donor's output.

1. **Pins.** The Blender executable by SHA-256 (`BLENDER_SHA256`: Blender 5.2, Steam build
   26125766), and the source `.blend` by SHA-256 and size (the inventory's `4c770d1d…`,
   9,748,913 bytes; `SOURCE`). The source resolves from Assets3D when the file there matches,
   else from the private store's blob of that hash (decision 144). Both scripts' SHA-256 are
   recorded.
2. **Run directory.** `<oracle work>/<run>` (`UZP_ORACLE_WORK`, default
   `%LOCALAPPDATA%\UzPainter\oracle-work`, always outside the repository), created fresh; an
   existing one is refused, so nothing is overwritten. Blender's TEMP, TMP and TMPDIR point at
   it, so its session folder lives and dies there, and any file left there that is not an
   expected output refuses the run. That is an environment setting, not a sandbox: nothing here
   can stop Blender writing elsewhere, so the run is confined by its pinned, offline options.
3. **Private copy.** The source is copied into the run directory under its own base name
   (Blender writes that name into the MTL), hash-checked and made read-only. Blender opens the
   copy, never the original, and never saves; the copy's hash is checked again after it exits.
4. **Blender.** The pinned command line (`blender_command`), once, with a timeout.
5. **Checks.** The report against every pin (`report_problems`); the table file against the
   report's counts and digests (`table_problems`). The OBJ against the table, value by value
   (`obj_problems`): the pinned `mtllib`, object and material, exactly `TRIANGLES` triangular
   faces in the table's order; every position equal to the table's under the pinned axes, and
   per face corner its vertex, its UV (no V flip) and its normal (the copy's custom normal, under
   the pinned axes), within the OBJ's printed precision. The MTL (`mtl_problems`): one material,
   the texture set, and no texture map. The change from the evaluated normals to the custom ones
   Blender stores is recorded (`max_normal_change`), not gated.
6. **Record.** `export-record.json` in the run directory, also printed. With `--expect`, the run
   must reproduce an earlier record's OBJ, MTL and digests byte for byte (r1 against r1-repeat).

`--dry-run` checks the pins and prints the plan with its command line; it writes nothing and does
not start Blender. The OBJ and MTL derive from a git-ignored Assets3D file, so they stay private:
they reach the store as inputs when the current round's request is written, not here.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.parity.recorder.job import pinned_assets3d_file, sha256_file
from tools.parity.recorder.output import ensure_outside_repository, work_root
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import OracleStore, StoreError, locate
from tools.parity.tier1 import sash_low_blender as side
from tools.parity.tier1.sash_low_blender import ExportError

RECORD_SCHEMA = "uzpainter/parity/sash-low-export-record/1"
RECORD_NAME = "export-record.json"
LOG_NAME = "blender.log"
DEFAULT_RUN = "phase2__tier1__sash-v5-current__low-r1"
RUN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}")

BLENDER_SHA256 = "e546b2a0d81ae19bd5b306b668733102d91d23db2e2be02d68b7ecbe548af0a1"
BLENDER_STEAM_BUILD = "26125766"  # provenance only; the SHA-256 is the pin
BLENDER_OPTIONS = (
    "--background",
    "--factory-startup",
    "--disable-autoexec",
    "--offline-mode",
    "-noaudio",
)
TIMEOUT_S = 600
TEMP_VARIABLES = ("TEMP", "TMP", "TMPDIR")
# The OBJ writes positions and UVs with six decimals and normals with four: half a unit in the
# last place, plus a margin for float32 arithmetic in the exporter, well under one unit.
COORDINATE_TOLERANCE = 5e-7 + 1e-7
NORMAL_TOLERANCE = 5e-5 + 1e-6
OUTPUTS = frozenset(
    {
        side.SOURCE_BLEND_NAME,
        side.OBJ_NAME,
        side.MTL_NAME,
        side.REPORT_NAME,
        side.TABLE_NAME,
        LOG_NAME,
    }
)
DIGESTS = ("corner_normals", "corner_uv", "positions", "triangulation")
SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class SourcePin:
    input_id: str
    assets3d_path: str
    sha256: str
    size_bytes: int

    def as_json(self) -> dict[str, Any]:
        return dict(self.__dict__)


SOURCE = SourcePin(
    input_id="sash-v5-blend",
    assets3d_path=(
        "Creatures/Undead/Skeletal Mage/Models3D/25-Faixa-Cintura/" + side.SOURCE_BLEND_NAME
    ),
    sha256="4c770d1dcf1fd4296386155e1ae12d60126a3d9de1fcfeaadf82636353624a3b",
    size_bytes=9_748_913,
)
SCRIPT = Path(side.__file__).resolve()


@dataclass(frozen=True)
class Plan:
    blender: Path
    blender_sha256: str
    script_sha256: str
    source_pin: SourcePin
    source: Path
    source_origin: str  # "assets3d" or "store"
    run_dir: Path
    command: tuple[str, ...]

    def as_json(self) -> dict[str, Any]:
        return {
            "blender": {"executable": str(self.blender), "sha256": self.blender_sha256},
            "script": _script_json(self.script_sha256),
            "source": {**self.source_pin.as_json(), "resolved_from": self.source_origin},
            "run_dir": str(self.run_dir),
            "command": list(self.command),
            "environment": {name: str(self.run_dir) for name in TEMP_VARIABLES},
            "options": side.OBJ_EXPORT_OPTIONS,
        }


Runner = Callable[[Sequence[str], Path, Mapping[str, str], Path], int]


def _script_json(script_sha256: str) -> dict[str, Any]:
    return {
        "blender_side": SCRIPT.relative_to(REPO_ROOT).as_posix(),
        "blender_side_sha256": script_sha256,
        "host": Path(__file__).resolve().relative_to(REPO_ROOT).as_posix(),
        "host_sha256": sha256_file(Path(__file__)),
        "donor": {"assets3d_path": side.DONOR_PATH, "sha256": side.DONOR_SHA256},
    }


def blender_command(blender: Path, script: Path, run_dir: Path) -> tuple[str, ...]:
    """Background, factory settings, no auto-run scripts, no network, no audio; the private copy
    is opened first and a Python error makes Blender exit 1."""
    return (
        str(blender),
        *BLENDER_OPTIONS,
        str(run_dir / side.SOURCE_BLEND_NAME),
        "--python-exit-code",
        "1",
        "--python",
        str(script),
        "--",
        str(run_dir),
    )


def plan_export(
    blender: Path,
    run: str,
    assets_root: Path,
    store: OracleStore | None,
    *,
    source_pin: SourcePin = SOURCE,
    blender_sha256: str = BLENDER_SHA256,
    work: Path | None = None,
) -> Plan:
    """Check every pin and fix the command; writes nothing."""
    if not RUN_NAME.fullmatch(run):
        raise ExportError(f"run name {run!r} must match {RUN_NAME.pattern}")
    # Resolved (symbolic links followed) and refused inside the repository, supplied or default.
    run_dir = ensure_outside_repository((work if work is not None else work_root()) / run)
    if run_dir.exists():
        raise ExportError(f"{run_dir} already exists; every run gets a fresh directory")
    if not blender.is_file():
        raise ExportError(f"no Blender executable at {blender}")
    blender = blender.resolve(strict=True)  # Blender runs from the run directory
    found = sha256_file(blender)
    if found != blender_sha256:
        raise ExportError(f"{blender} has SHA-256 {found}, pinned {blender_sha256}")
    item = {
        "input_id": source_pin.input_id,
        "assets3d_path": source_pin.assets3d_path,
        "sha256": source_pin.sha256,
    }
    source = pinned_assets3d_file(item, assets_root, store)
    if source.stat().st_size != source_pin.size_bytes:
        raise ExportError(f"{source} has {source.stat().st_size} bytes, pinned {source_pin}")
    origin = "assets3d" if source == assets_root / source_pin.assets3d_path else "store"
    return Plan(
        blender=blender,
        blender_sha256=found,
        script_sha256=sha256_file(SCRIPT),
        source_pin=source_pin,
        source=source,
        source_origin=origin,
        run_dir=run_dir,
        command=blender_command(blender, SCRIPT, run_dir),
    )


def run_blender(command: Sequence[str], cwd: Path, env: Mapping[str, str], log: Path) -> int:
    with log.open("xb") as stream:
        done = subprocess.run(
            list(command),
            cwd=cwd,
            env=dict(env),
            stdout=stream,
            stderr=subprocess.STDOUT,
            timeout=TIMEOUT_S,
            check=False,
        )
    return done.returncode


def run_export(plan: Plan, runner: Runner = run_blender) -> dict[str, Any]:
    """Copy, run Blender once, check everything it wrote and write the record."""
    ensure_outside_repository(plan.run_dir)  # again: a Plan can be built without plan_export
    pin = plan.source_pin
    plan.run_dir.mkdir(parents=True, exist_ok=False)
    copy = plan.run_dir / side.SOURCE_BLEND_NAME
    shutil.copyfile(plan.source, copy)
    if sha256_file(copy) != pin.sha256:
        raise ExportError(f"the private copy {copy} differs from its pin {pin.sha256}")
    os.chmod(copy, stat.S_IREAD)
    env = {**os.environ, **{name: str(plan.run_dir) for name in TEMP_VARIABLES}}
    log = plan.run_dir / LOG_NAME
    code = runner(plan.command, plan.run_dir, env, log)
    copy_after = sha256_file(copy)
    if copy_after != pin.sha256:
        raise ExportError(f"Blender changed the private copy {copy} (now {copy_after})")
    if code != 0:
        raise ExportError(f"Blender exited {code}; see {log}")
    present = {path.name for path in plan.run_dir.iterdir()}
    if present != OUTPUTS:
        raise ExportError(
            f"{plan.run_dir}: unexpected {sorted(present - OUTPUTS)}, "
            f"missing {sorted(OUTPUTS - present)}"
        )
    report = json.loads((plan.run_dir / side.REPORT_NAME).read_bytes())
    obj_path, mtl_path = plan.run_dir / side.OBJ_NAME, plan.run_dir / side.MTL_NAME
    table_path = plan.run_dir / side.TABLE_NAME
    problems = report_problems(report, copy)
    normal_change = None
    if not problems:
        try:
            table, exported = side.table_from_document(json.loads(table_path.read_bytes()))
        except (KeyError, TypeError, ValueError) as error:
            raise ExportError(f"{table_path} is malformed ({error!r})") from error
        problems += table_problems(table, report)
        if not problems:
            text = obj_path.read_text(encoding="utf-8")
            problems += obj_problems(text, table, exported)
            normal_change = max_normal_change(table, exported)
    problems += mtl_problems(mtl_path.read_text(encoding="utf-8"))
    if problems:
        raise ExportError("; ".join(problems))
    record = {
        "schema": RECORD_SCHEMA,
        "exporter": side.EXPORTER,
        "blender": {
            "executable": str(plan.blender),
            "sha256": plan.blender_sha256,
            "steam_build": BLENDER_STEAM_BUILD,
            "command": list(plan.command),
            "build": report["blender"],
        },
        "script": _script_json(plan.script_sha256),
        "source": {
            **pin.as_json(),
            "resolved_from": plan.source_origin,
            "copy_sha256_after": copy_after,
        },
        "options": side.OBJ_EXPORT_OPTIONS,
        "selection": report["source"],
        "mesh": {**report["mesh"], "max_custom_normal_change": normal_change},
        "outputs": {
            name: {
                "file": path.name,
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for name, path in (
                ("obj", obj_path),
                ("mtl", mtl_path),
                ("report", plan.run_dir / side.REPORT_NAME),
                ("table", table_path),
            )
        },
    }
    (plan.run_dir / RECORD_NAME).write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return record


def report_problems(report: Any, copy: Path) -> list[str]:
    """The Blender side's report against every pin."""
    try:
        source, export, mesh = report["source"], report["export"], report["mesh"]
        checks: list[tuple[str, Any, Any]] = [
            ("exporter", report["exporter"], side.EXPORTER),
            ("blender version", list(report["blender"]["version"][:2]), list(side.BLENDER_VERSION)),
            ("opened file", Path(source["blend"]).resolve(), copy.resolve()),
            ("object", source["object"], side.SOURCE_OBJECT),
            ("materials", source["materials"], list(side.SOURCE_MATERIALS)),
            ("modifiers", source["modifiers"], [list(m) for m in side.SOURCE_MODIFIERS]),
            ("uv map", source["uv_map"], side.UV_MAP),
            ("depsgraph mode", source["depsgraph_mode"], side.DEPSGRAPH_MODE),
            ("export object", export["object"], side.EXPORT_OBJECT),
            ("export material", export["material"], side.TEXTURE_SET),
            ("obj", export["obj"], side.OBJ_NAME),
            ("mtl", export["mtl"], side.MTL_NAME),
            ("options", export["options"], side.OBJ_EXPORT_OPTIONS),
            ("triangles", mesh["triangles"], side.TRIANGLES),
            ("digests", sorted(mesh["digests"]), list(DIGESTS)),
        ]
        problems = [
            f"report {what} is {found!r}, pinned {pinned!r}"
            for what, found, pinned in checks
            if found != pinned
        ]
        problems += [
            f"report digest {name} is not a SHA-256"
            for name in DIGESTS
            if not SHA256.fullmatch(str(mesh["digests"].get(name)))
        ]
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as error:
        return [f"the report is malformed ({type(error).__name__}: {error})"]
    return problems


def table_problems(table: side.TriangleTable, report: Mapping[str, Any]) -> list[str]:
    """The table file is the one the report describes: same counts and digests."""
    mesh = report["mesh"]
    problems = []
    if (len(table.positions), len(table.triangles)) != (mesh["vertices"], mesh["triangles"]):
        problems.append("the table's vertex or triangle count differs from the report's")
    if side.table_digests(table) != mesh["digests"]:
        problems.append("the table's digests differ from the report's")
    return problems


def _close(found: Sequence[float], expected: Sequence[float], tolerance: float) -> bool:
    return all(abs(a - b) <= tolerance for a, b in zip(found, expected, strict=True))


def max_normal_change(table: side.TriangleTable, exported: Sequence[side.Vec3]) -> float:
    """The largest component change from the evaluated corner normals to the copy's, which
    Blender re-encodes as custom normals; recorded, not gated."""
    corners = [loop for corner_loops in table.loops for loop in corner_loops]
    return max(
        (
            abs(a - b)
            for loop, normal in zip(corners, exported, strict=True)
            for a, b in zip(table.normals[loop], normal, strict=True)
        ),
        default=0.0,
    )


def obj_problems(text: str, table: side.TriangleTable, exported: Sequence[side.Vec3]) -> list[str]:
    """The OBJ against the table, value by value: every position (under the pinned axes), and per
    face corner its vertex, its UV and its normal (the copy's, under the pinned axes)."""
    lines = text.splitlines()
    major, minor = side.BLENDER_VERSION
    problems: list[str] = []
    if not lines or not lines[0].startswith(f"# Blender {major}.{minor}"):
        problems.append("the OBJ does not start with the pinned Blender's header")
    names: dict[str, list[str]] = {"o": [], "usemtl": [], "mtllib": []}
    positions: list[tuple[float, ...]] = []
    uvs: list[tuple[float, ...]] = []
    normals: list[tuple[float, ...]] = []
    faces: list[list[tuple[int, int, int]]] = []
    for number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, rest = line.partition(" ")
        try:
            if key == "v":
                positions.append(_floats(rest, 3))
            elif key == "vt":
                uvs.append(_floats(rest, 2))
            elif key == "vn":
                normals.append(_floats(rest, 3))
            elif key == "f":
                faces.append([_corner(corner) for corner in rest.split()])
            elif key in names:
                names[key].append(rest.strip())
            elif key != "s":
                problems.append(f"OBJ line {number}: unexpected {key!r}")
        except ValueError as error:
            problems.append(f"OBJ line {number}: {error}")
    for key, pinned in (
        ("mtllib", side.MTL_NAME),
        ("o", side.EXPORT_OBJECT),
        ("usemtl", side.TEXTURE_SET),
    ):
        if names[key] != [pinned]:
            problems.append(f"OBJ {key} is {names[key]}, pinned [{pinned!r}]")
    if len(positions) != len(table.positions):
        problems.append(f"OBJ has {len(positions)} vertices, the table {len(table.positions)}")
    if len(faces) != side.TRIANGLES or len(faces) != len(table.triangles):
        problems.append(f"OBJ has {len(faces)} faces, pinned {side.TRIANGLES}")
    counts = (len(positions), len(uvs), len(normals))
    for k, face in enumerate(faces):
        if len(face) != 3:
            problems.append(f"OBJ face {k + 1} has {len(face)} corners, not 3")
            break
        if any(not 1 <= c[i] <= counts[i] for c in face for i in range(3)):
            problems.append(f"OBJ face {k + 1} names an index out of range")
            break
    if problems:
        return problems
    moved = [
        i
        for i, (found, source) in enumerate(zip(positions, table.positions, strict=True))
        if not _close(found, side.to_obj_axes(source), COORDINATE_TOLERANCE)
    ]
    if moved:
        problems.append(f"{len(moved)} OBJ positions differ from the table's, first {moved[0]}")
    wrong: dict[str, list[int]] = {"vertex": [], "UV": [], "normal": []}
    for k, (face, vertices, loops) in enumerate(
        zip(faces, table.triangles, table.loops, strict=True)
    ):
        for c, ((v, t, n), vertex, loop) in enumerate(zip(face, vertices, loops, strict=True)):
            if v - 1 != vertex:
                wrong["vertex"].append(k)
            if not _close(uvs[t - 1], table.uv[loop], COORDINATE_TOLERANCE):
                wrong["UV"].append(k)
            expected = side.to_obj_axes(exported[3 * k + c])
            if not _close(normals[n - 1], expected, NORMAL_TOLERANCE):
                wrong["normal"].append(k)
    problems += [
        f"{len(faces_)} OBJ faces have a corner {what} that differs from the table's, "
        f"first face {faces_[0] + 1}"
        for what, faces_ in wrong.items()
        if faces_
    ]
    return problems


def _floats(text: str, size: int) -> tuple[float, ...]:
    values = tuple(float(part) for part in text.split())
    if len(values) != size or not all(math.isfinite(v) for v in values):
        raise ValueError(f"{text!r} is not {size} finite numbers")
    return values


def _corner(text: str) -> tuple[int, int, int]:
    parts = text.split("/")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError(f"face corner {text!r} is not v/vt/vn")
    return int(parts[0]), int(parts[1]), int(parts[2])


TEXTURE_KEYS = ("map_", "bump", "disp", "decal", "refl", "norm")


def mtl_problems(text: str) -> list[str]:
    """One material, named after the texture set, and no texture path."""
    lines = [line.strip() for line in text.splitlines()]
    problems: list[str] = []
    if not lines or not lines[0].startswith("# Blender"):
        problems.append("the MTL does not start with Blender's header")
    materials = [line.partition(" ")[2].strip() for line in lines if line.startswith("newmtl ")]
    if materials != [side.TEXTURE_SET]:
        problems.append(f"MTL materials are {materials}, pinned [{side.TEXTURE_SET!r}]")
    textures = [line for line in lines if line.lower().startswith(TEXTURE_KEYS)]
    if textures:
        problems.append(f"the MTL names textures: {textures}")
    return problems


def compare_records(record: Mapping[str, Any], expected: Mapping[str, Any]) -> list[str]:
    """What a repeat run must reproduce: the pins, the outputs' bytes and the mesh digests."""
    fields = (
        ("schema",),
        ("blender", "sha256"),
        ("script", "blender_side_sha256"),
        ("script", "host_sha256"),
        ("source", "sha256"),
        ("options",),
        ("mesh", "digests"),
        ("outputs", "obj", "sha256"),
        ("outputs", "obj", "size_bytes"),
        ("outputs", "mtl", "sha256"),
        ("outputs", "mtl", "size_bytes"),
    )
    problems = []
    for path in fields:
        found, wanted = _get(record, path), _get(expected, path)
        if found is None or found != wanted:
            problems.append(f"{'.'.join(path)} is {found!r}, the earlier run's {wanted!r}")
    return problems


def _get(document: Any, path: Sequence[str]) -> Any:
    for key in path:
        if not isinstance(document, Mapping):
            return None
        document = document.get(key)
    return document


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.parity.tier1.sash_low_export",
        description="Export the Sash v5 low to OBJ/MTL from the preserved .blend (decision 300).",
    )
    parser.add_argument("--blender", type=Path, required=True, help="the pinned blender.exe")
    parser.add_argument("--assets-root", type=Path, required=True, help="Assets3D (read only)")
    parser.add_argument("--run", default=DEFAULT_RUN, help="run directory name in oracle work")
    parser.add_argument("--expect", type=Path, help="an earlier run's export-record.json")
    parser.add_argument("--store", type=Path, help="private store root (default: located)")
    parser.add_argument("--dry-run", action="store_true", help="check pins, print the plan")
    args = parser.parse_args(argv)
    try:
        store = OracleStore.open(args.store) if args.store is not None else locate()
        expected = None
        if args.expect is not None:
            expected = json.loads(args.expect.read_text(encoding="utf-8"))
            if _get(expected, ("schema",)) != RECORD_SCHEMA:
                raise ExportError(f"{args.expect} is not a {RECORD_SCHEMA} record")
        plan = plan_export(args.blender, args.run, args.assets_root, store)
        if args.dry_run:
            print(json.dumps(plan.as_json(), indent=2))
            return 0
        record = run_export(plan)
    except (
        ExportError,
        RecorderError,
        StoreError,
        OSError,
        ValueError,
        subprocess.TimeoutExpired,
    ) as error:
        print(f"sash_low_export: {error}", file=sys.stderr)
        return 2
    print(json.dumps(record, indent=2, sort_keys=True))
    problems = compare_records(record, expected) if expected is not None else []
    for problem in problems:
        print(f"sash_low_export: not reproduced: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
