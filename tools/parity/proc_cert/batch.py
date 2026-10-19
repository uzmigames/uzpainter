"""Certification batches: the declared domain, the calibration set and the held-out set.

Layout of one batch (`docs/architecture/05-procedural-content.md` §6, decisions 222 and 303):

    <batch dir>/batch.json              asset, domain, §6 matrix, both sets pinned by SHA-256
    <batch dir>/<calibration root>/...  the calibration case list (fitted against)
    <batch dir>/<held-out root>/...     the held-out case list (never seen by a fitter)

`batch.json` is committed before calibration starts; it pins each case list by the SHA-256 of
its bytes, so a held-out list changed after the pin no longer loads. The two roots are separate
directories, neither inside the other, so the held-out root can be fenced on its own
(`fence.py`). Case lists name oracles and image inputs by hash only; the bytes live in the
private store (`parity/STORE.md`).

The calibration set must cover every cell of the §6 matrix the batch declares, with decision
222's counts: 3 meshes x 3 resolutions x {defaults, recipe sets, two boundary sets} x 2 seeds.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

BATCH_SCHEMA = "uzpainter/parity/proc-cert-batch/1"
CASES_SCHEMA = "uzpainter/parity/proc-cert-cases/1"
SETS = ("calibration", "held_out")
INTEGER_FORMATS = {"u8": 255, "u16": 65535}  # native integer code values and their maximum
FLOAT_FORMATS = frozenset({"f16", "f32"})  # IEEE half and single floats (decision 305)
FORMATS = frozenset(INTEGER_FORMATS) | FLOAT_FORMATS
# The formats each encoding can hold. raw: little-endian samples, rows top first, (h, w, c).
ENCODINGS = {"raw": FORMATS, "png": frozenset(INTEGER_FORMATS), "exr": FLOAT_FORMATS}
U32_MAX = (1 << 32) - 1
# The §6 matrix with decision 222's counts: meshes, resolutions, boundary sets, seeds.
MATRIX_MESHES = 3
MATRIX_RESOLUTIONS = 3
MATRIX_BOUNDARY_SETS = 2
MATRIX_SEEDS = 2
MATRIX_ROLES = ("defaults", "recipe", "boundary")

_ASSET = re.compile(r"^[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*$")
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class BatchError(Exception):
    """A batch that cannot be certified: malformed, changed after its pin, or not independent."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(document: Any) -> bytes:
    """The one serialisation hashed and written by the harness (sorted keys, no whitespace)."""
    return json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


@dataclass(frozen=True)
class RasterSpec:
    resolution: int
    format: str
    colour_space: str
    channels: int

    @property
    def shape(self) -> tuple[int, int, int]:
        return (self.resolution, self.resolution, self.channels)


@dataclass(frozen=True)
class BlobRef:
    record_id: str
    sha256: str
    size_bytes: int
    encoding: str


@dataclass(frozen=True)
class Case:
    """One evaluation of the asset and the oracle it must reproduce."""

    case_id: str
    set: str
    mesh_id: str
    mesh_class: str
    uv_tiles: int
    params: Mapping[str, Any]
    seed: int
    output: RasterSpec
    inputs: Mapping[str, tuple[RasterSpec, BlobRef]]
    oracle: BlobRef

    def signature(self) -> bytes:
        """Everything that defines the evaluation (not its id, set or oracle). Numbers are
        compared by value, so 1 and 1.0 are the same parameter value."""
        return canonical(
            {
                "mesh": [self.mesh_id, self.mesh_class, self.uv_tiles],
                "params": _normal(self.params),
                "seed": self.seed,
                "output": self.output.__dict__,
                "inputs": {
                    usage: {**spec.__dict__, "sha256": ref.sha256}
                    for usage, (spec, ref) in self.inputs.items()
                },
            }
        )


@dataclass(frozen=True)
class Refusal:
    """A case outside the certified domain: the field, its value and the certified range."""

    field: str
    value: Any
    certified: Any

    def __str__(self) -> str:
        return (
            f"outside certified domain: {self.field} = {self.value!r}, certified {self.certified!r}"
        )


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise BatchError(message)


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _normal(params: Mapping[str, Any]) -> dict[str, Any]:
    """Parameter values with numbers compared by value, so 1 and 1.0 are the same value."""
    return {
        name: str(Fraction(value)) if _number(value) else value for name, value in params.items()
    }


def _raster(document: Any, where: str) -> RasterSpec:
    _need(isinstance(document, dict), f"{where}: not an object")
    spec = RasterSpec(
        document.get("resolution"),
        document.get("format"),
        document.get("colour_space"),
        document.get("channels"),
    )
    _need(
        isinstance(spec.resolution, int)
        and not isinstance(spec.resolution, bool)
        and spec.resolution > 0,
        f"{where}: resolution must be a positive integer",
    )
    _need(spec.format in FORMATS, f"{where}: format must be one of {sorted(FORMATS)}")
    _need(isinstance(spec.colour_space, str) and bool(spec.colour_space), f"{where}: colour_space")
    _need(
        isinstance(spec.channels, int)
        and not isinstance(spec.channels, bool)
        and 1 <= spec.channels <= 4,
        f"{where}: channels must be 1 to 4",
    )
    return spec


def _blob(document: Any, where: str) -> BlobRef:
    _need(isinstance(document, dict), f"{where}: not an object")
    ref = BlobRef(
        document.get("record_id"),
        document.get("sha256"),
        document.get("size_bytes"),
        document.get("encoding"),
    )
    _need(isinstance(ref.record_id, str) and bool(_ID.match(ref.record_id)), f"{where}: record_id")
    _need(isinstance(ref.sha256, str) and bool(_SHA256.match(ref.sha256)), f"{where}: sha256")
    _need(
        isinstance(ref.size_bytes, int)
        and not isinstance(ref.size_bytes, bool)
        and ref.size_bytes > 0,
        f"{where}: size_bytes",
    )
    _need(ref.encoding in ENCODINGS, f"{where}: encoding must be one of {sorted(ENCODINGS)}")
    return ref


def _pinned(document: Any, spec: RasterSpec, where: str) -> BlobRef:
    ref = _blob(document, where)
    _need(
        spec.format in ENCODINGS[ref.encoding],
        f"{where}: a {ref.encoding} blob cannot hold {spec.format} samples",
    )
    return ref


def parse_case(document: Any, set_name: str) -> Case:
    _need(isinstance(document, dict), f"{set_name}: a case is not an object")
    case_id = document.get("case_id")
    _need(isinstance(case_id, str) and bool(_ID.match(case_id)), f"{set_name}: case_id {case_id!r}")
    where = f"{set_name} case {case_id}"
    mesh = document.get("mesh")
    _need(isinstance(mesh, dict), f"{where}: mesh")
    _need(isinstance(mesh.get("id"), str) and bool(_ID.match(mesh["id"])), f"{where}: mesh.id")
    _need(isinstance(mesh.get("class"), str) and bool(mesh["class"]), f"{where}: mesh.class")
    _need(isinstance(mesh.get("uv_tiles"), int), f"{where}: mesh.uv_tiles")
    params = document.get("params")
    _need(isinstance(params, dict), f"{where}: params")
    seed = document.get("seed")
    _need(isinstance(seed, int) and not isinstance(seed, bool), f"{where}: seed")
    inputs = document.get("inputs", {})
    _need(isinstance(inputs, dict), f"{where}: inputs")
    output = _raster(document.get("output"), f"{where}: output")
    input_specs = {
        usage: _raster(entry, f"{where}: input {usage}") for usage, entry in sorted(inputs.items())
    }
    return Case(
        case_id,
        set_name,
        mesh["id"],
        mesh["class"],
        mesh["uv_tiles"],
        dict(params),
        seed,
        output,
        {
            usage: (spec, _pinned(inputs[usage], spec, f"{where}: input {usage}"))
            for usage, spec in input_specs.items()
        },
        _pinned(document.get("oracle"), output, f"{where}: oracle"),
    )


class Domain:
    """The certified editable domain an asset declares before calibration (decision 222 §1)."""

    def __init__(self, document: Any) -> None:
        _need(isinstance(document, dict), "domain: not an object")
        self.document = document
        parameters = document.get("parameters")
        _need(isinstance(parameters, dict), "domain.parameters: not an object")
        self.ranges: dict[str, tuple[Fraction, Fraction]] = {}
        self.sets: dict[str, list[Any]] = {}
        for name, rule in parameters.items():
            _need(isinstance(rule, dict) and len(rule) == 1, f"domain.parameters.{name}")
            if "range" in rule:
                low, high = rule["range"]
                _need(_number(low) and _number(high) and low < high, f"domain {name}: range")
                self.ranges[name] = (Fraction(low), Fraction(high))
            else:
                _need(isinstance(rule.get("set"), list) and bool(rule["set"]), f"domain {name}")
                self.sets[name] = list(rule["set"])
        self.constraints = document.get("constraints", [])
        _need(isinstance(self.constraints, list), "domain.constraints: not a list")
        for constraint in self.constraints:
            _need(
                isinstance(constraint, dict)
                and isinstance(constraint.get("coefficients"), dict)
                and all(name in self.ranges for name in constraint["coefficients"])
                and all(_number(c) for c in constraint["coefficients"].values())
                and _number(constraint.get("max")),
                f"domain constraint {constraint!r}: coefficients over ranged parameters and a max",
            )
        seeds = document.get("seeds")
        _need(isinstance(seeds, dict), "domain.seeds")
        self.seed_policy = seeds.get("policy")
        _need(self.seed_policy in ("any_u32", "listed"), "domain.seeds.policy: any_u32 or listed")
        self.seeds = seeds.get("seeds", []) if self.seed_policy == "listed" else []
        geometry = document.get("geometry")
        _need(isinstance(geometry, dict), "domain.geometry")
        self.mesh_classes = geometry.get("mesh_classes")
        _need(isinstance(self.mesh_classes, list) and bool(self.mesh_classes), "mesh_classes")
        self.uv_tiles = geometry.get("uv_tiles")
        _need(self.uv_tiles == 1, "domain.geometry.uv_tiles: a single UV tile")
        self.inputs = geometry.get("inputs", {})
        _need(isinstance(self.inputs, dict), "domain.geometry.inputs")
        self.output = document.get("output")
        _need(isinstance(self.output, dict), "domain.output")
        for key in ("resolutions", "formats", "colour_spaces", "channels"):
            _need(isinstance(self.output.get(key), list), f"domain.output.{key}")
        for usage, rule in self.inputs.items():
            _need(isinstance(rule, dict), f"domain input {usage}")
            for key in ("resolutions", "formats", "colour_spaces", "channels"):
                _need(isinstance(rule.get(key), list), f"domain input {usage}.{key}")

    def sha256(self) -> str:
        return sha256_bytes(canonical(self.document))

    def params_refusal(self, params: Mapping[str, Any]) -> Refusal | None:
        """The first parameter outside the domain, or None inside it."""
        declared = set(self.ranges) | set(self.sets)
        if missing := sorted(declared - set(params)):
            return Refusal(f"params.{missing[0]}", "missing", "every declared parameter")
        if extra := sorted(set(params) - declared):
            return Refusal(f"params.{extra[0]}", params[extra[0]], "not a parameter")
        for name, (low, high) in sorted(self.ranges.items()):
            value = params[name]
            if not _number(value) or not low <= Fraction(value) <= high:
                return Refusal(f"params.{name}", value, [float(low), float(high)])
        for name, allowed in sorted(self.sets.items()):
            if params[name] not in allowed:
                return Refusal(f"params.{name}", params[name], allowed)
        for constraint in self.constraints:
            total = sum(
                Fraction(c) * Fraction(params[name])
                for name, c in constraint["coefficients"].items()
            )
            if total > Fraction(constraint["max"]):
                return Refusal("params", dict(params), constraint)
        return None

    def seed_refusal(self, seed: int) -> Refusal | None:
        if not 0 <= seed <= U32_MAX:
            return Refusal("seed", seed, [0, U32_MAX])
        if self.seed_policy == "listed" and seed not in self.seeds:
            return Refusal("seed", seed, self.seeds)
        return None

    @property
    def single_seed(self) -> bool:
        return self.seed_policy == "listed" and len(self.seeds) == 1

    def refusal(self, case: Case) -> Refusal | None:
        """The first field of `case` outside the domain, or None inside it. Nothing is clamped."""
        if (refusal := self.params_refusal(case.params)) is not None:
            return refusal
        if (refusal := self.seed_refusal(case.seed)) is not None:
            return refusal
        if case.mesh_class not in self.mesh_classes:
            return Refusal("mesh.class", case.mesh_class, self.mesh_classes)
        if case.uv_tiles != self.uv_tiles:
            return Refusal("mesh.uv_tiles", case.uv_tiles, self.uv_tiles)
        if absent := sorted(set(self.inputs) - set(case.inputs)):
            return Refusal(f"inputs.{absent[0]}", "missing", "a declared input")
        if undeclared := sorted(set(case.inputs) - set(self.inputs)):
            return Refusal(f"inputs.{undeclared[0]}", "present", "not an input of the domain")
        rasters = [("output", case.output, self.output)] + [
            (f"inputs.{usage}", case.inputs[usage][0], self.inputs[usage])
            for usage in sorted(case.inputs)
        ]
        for where, spec, rule in rasters:
            for name, key, value in (
                ("resolution", "resolutions", spec.resolution),
                ("format", "formats", spec.format),
                ("colour_space", "colour_spaces", spec.colour_space),
                ("channels", "channels", spec.channels),
            ):
                if value not in rule[key]:
                    return Refusal(f"{where}.{name}", value, rule[key])
        return None


@dataclass(frozen=True)
class ParameterSet:
    set_id: str
    role: str  # defaults, recipe or boundary
    params: Mapping[str, Any]


@dataclass(frozen=True)
class Matrix:
    """The §6 matrix the calibration set must cover (decision 222's counts)."""

    meshes: tuple[str, ...]
    resolutions: tuple[int, ...]
    parameter_sets: tuple[ParameterSet, ...]
    seeds: tuple[int, ...]

    def cells(self) -> Iterator[tuple[str, int, ParameterSet, int]]:
        for mesh in self.meshes:
            for resolution in self.resolutions:
                for parameter_set in self.parameter_sets:
                    for seed in self.seeds:
                        yield mesh, resolution, parameter_set, seed

    def summary(self) -> dict[str, Any]:
        sets = len(self.parameter_sets)
        return {
            "cells": len(self.meshes) * len(self.resolutions) * sets * len(self.seeds),
            "meshes": len(self.meshes),
            "resolutions": list(self.resolutions),
            "parameter_sets": {
                role: sum(s.role == role for s in self.parameter_sets) for role in MATRIX_ROLES
            },
            "seeds": len(self.seeds),
        }


def parse_matrix(document: Any) -> Matrix:
    _need(isinstance(document, dict), "batch.matrix: not an object (the §6 matrix)")
    meshes, resolutions = document.get("meshes"), document.get("resolutions")
    sets, seeds = document.get("parameter_sets"), document.get("seeds")
    _need(
        isinstance(meshes, list)
        and all(isinstance(mesh, str) and bool(_ID.match(mesh)) for mesh in meshes),
        "batch.matrix.meshes: a list of mesh ids",
    )
    _need(
        isinstance(resolutions, list) and all(_int(r) and r > 0 for r in resolutions),
        "batch.matrix.resolutions: a list of positive integers",
    )
    _need(
        isinstance(seeds, list) and all(_int(seed) for seed in seeds),
        "batch.matrix.seeds: a list of integers",
    )
    _need(isinstance(sets, list), "batch.matrix.parameter_sets: a list")
    parsed = []
    for entry in sets:
        _need(
            isinstance(entry, dict)
            and isinstance(entry.get("id"), str)
            and bool(_ID.match(entry["id"]))
            and entry.get("role") in MATRIX_ROLES
            and isinstance(entry.get("params"), dict),
            f"batch.matrix.parameter_sets: {entry!r} needs an id, a role in {MATRIX_ROLES} "
            "and params",
        )
        parsed.append(ParameterSet(entry["id"], entry["role"], dict(entry["params"])))
    return Matrix(tuple(meshes), tuple(resolutions), tuple(parsed), tuple(seeds))


def matrix_problems(matrix: Matrix, domain: Domain, calibration: Iterable[Case]) -> list[str]:
    """§6 with decision 222's counts, and a calibration case in every cell of the matrix."""
    problems: list[str] = []
    seeds = 1 if domain.single_seed else MATRIX_SEEDS
    counted: tuple[tuple[str, tuple[Any, ...], int], ...] = (
        ("meshes", matrix.meshes, MATRIX_MESHES),
        ("resolutions", matrix.resolutions, MATRIX_RESOLUTIONS),
        ("seeds", matrix.seeds, seeds),
    )
    for what, values, count in counted:
        if len(values) != count or len(set(values)) != count:
            problems.append(f"the §6 matrix needs {count} distinct {what}, it has {list(values)}")
    problems.extend(
        f"matrix resolution {resolution} is outside the domain's output resolutions"
        for resolution in matrix.resolutions
        if resolution not in domain.output["resolutions"]
    )
    for seed in matrix.seeds:
        if (refusal := domain.seed_refusal(seed)) is not None:
            problems.append(f"matrix seed: {refusal}")
    roles = [s.role for s in matrix.parameter_sets]
    if roles.count("defaults") != 1:
        problems.append("the §6 matrix needs exactly 1 defaults parameter set")
    if roles.count("boundary") != MATRIX_BOUNDARY_SETS:
        problems.append(f"the §6 matrix needs exactly {MATRIX_BOUNDARY_SETS} boundary sets")
    if "recipe" not in roles:
        problems.append("the §6 matrix needs at least one recipe parameter set")
    ids = [s.set_id for s in matrix.parameter_sets]
    problems.extend(
        f"matrix parameter set {i} is listed twice" for i in sorted(set(ids)) if ids.count(i) > 1
    )
    normals = [canonical(_normal(s.params)) for s in matrix.parameter_sets]
    if len(set(normals)) != len(normals):
        problems.append("two matrix parameter sets have the same values")
    for parameter_set in matrix.parameter_sets:
        if (refusal := domain.params_refusal(parameter_set.params)) is not None:
            problems.append(f"matrix parameter set {parameter_set.set_id}: {refusal}")
        elif (
            parameter_set.role == "boundary"
            and domain.ranges
            and not any(
                Fraction(parameter_set.params[name]) in (low, high)
                for name, (low, high) in domain.ranges.items()
            )
        ):
            problems.append(
                f"boundary set {parameter_set.set_id} puts no ranged parameter at an end of its "
                "range"
            )
    covered = {
        (case.mesh_id, case.output.resolution, canonical(_normal(case.params)), case.seed)
        for case in calibration
    }
    missing = [
        (mesh, resolution, parameter_set.set_id, seed)
        for mesh, resolution, parameter_set, seed in matrix.cells()
        if (mesh, resolution, canonical(_normal(parameter_set.params)), seed) not in covered
    ]
    if missing:
        mesh, resolution, set_id, seed = missing[0]
        problems.append(
            f"the calibration set leaves {len(missing)} cell(s) of the §6 matrix without a case, "
            f"first mesh {mesh}, resolution {resolution}, parameter set {set_id}, seed {seed}"
        )
    return problems


@dataclass(frozen=True)
class CaseSet:
    name: str
    corpus_id: str
    path: Path
    root: Path
    sha256: str


@dataclass(frozen=True)
class Batch:
    path: Path
    sha256: str
    asset: str
    asset_version: int
    domain: Domain
    matrix: Matrix
    calibration: CaseSet
    held_out: CaseSet

    def cases(self, which: CaseSet) -> tuple[Case, ...]:
        """The case list of `which`, refused when its bytes no longer match the pin."""
        data = which.path.read_bytes()
        found = sha256_bytes(data)
        _need(
            found == which.sha256,
            f"{which.name} list {which.path.name} hashes {found}, the batch pins {which.sha256}",
        )
        document = json.loads(data)
        _need(
            isinstance(document, dict) and document.get("schema") == CASES_SCHEMA,
            f"{which.path}: schema must be {CASES_SCHEMA}",
        )
        _need(document.get("set") == which.name, f"{which.path}: set must be {which.name}")
        _need(isinstance(document.get("cases"), list) and bool(document["cases"]), "no cases")
        return tuple(parse_case(entry, which.name) for entry in document["cases"])


def _case_set(document: Any, name: str, batch_dir: Path) -> CaseSet:
    _need(isinstance(document, dict), f"batch.{name}: not an object")
    corpus_id, relative, sha = (
        document.get("corpus_id"),
        document.get("path"),
        document.get("sha256"),
    )
    _need(isinstance(corpus_id, str) and bool(_ID.match(corpus_id)), f"batch.{name}.corpus_id")
    _need(isinstance(sha, str) and bool(_SHA256.match(sha)), f"batch.{name}.sha256")
    _need(isinstance(relative, str) and "/" in relative, f"batch.{name}.path: <root>/<file>")
    path = (batch_dir / relative).resolve()
    _need(path.is_relative_to(batch_dir), f"batch.{name}.path leaves the batch directory")
    return CaseSet(name, corpus_id, path, path.parent, sha)


def independence_problems(
    domain: Domain, calibration: Iterable[Case], held_out: Iterable[Case]
) -> list[str]:
    """Decision 222 §2: the held-out set is independent of the calibration set."""
    cal, held = list(calibration), list(held_out)
    problems: list[str] = []
    for case in cal + held:
        if (refusal := domain.refusal(case)) is not None:
            problems.append(f"{case.set} case {case.case_id}: {refusal}")
    ids = [case.case_id for case in cal + held]
    problems.extend(
        f"case id {i} is used twice" for i in sorted({i for i in ids if ids.count(i) > 1})
    )
    # Every blob a fitter is given: the calibration oracles and the calibration inputs.
    cal_blobs = {case.oracle.sha256 for case in cal} | {
        ref.sha256 for case in cal for _, ref in case.inputs.values()
    }
    problems.extend(
        f"held-out case {case.case_id} shares its oracle blob with the calibration set "
        "(a calibration oracle or input)"
        for case in held
        if case.oracle.sha256 in cal_blobs
    )
    cal_signatures = {case.signature() for case in cal}
    problems.extend(
        f"held-out case {case.case_id} repeats a calibration case"
        for case in held
        if case.signature() in cal_signatures
    )
    if not {case.mesh_id for case in held} - {case.mesh_id for case in cal}:
        problems.append("the held-out set has no mesh outside the calibration set")
    if not domain.single_seed and not {case.seed for case in held} - {case.seed for case in cal}:
        problems.append("the held-out set has no seed outside the calibration set")
    for name, (low, high) in sorted(domain.ranges.items()):
        seen = {Fraction(case.params[name]) for case in cal if _number(case.params.get(name))}
        interior = [
            case
            for case in held
            if _number(case.params.get(name))
            and low < Fraction(case.params[name]) < high
            and Fraction(case.params[name]) not in seen
        ]
        if not interior:
            problems.append(f"the held-out set has no new interior point of parameter {name}")
    return problems


def load_batch(path: Path) -> Batch:
    """Load and check a batch; every problem raises `BatchError` before anything is fitted."""
    path = path.resolve()
    data = path.read_bytes()
    document = json.loads(data)
    _need(isinstance(document, dict) and document.get("schema") == BATCH_SCHEMA, f"{BATCH_SCHEMA}")
    asset, version = document.get("asset"), document.get("asset_version")
    _need(isinstance(asset, str) and bool(_ASSET.match(asset)), "batch.asset: <family>/<id>")
    _need(isinstance(version, int) and not isinstance(version, bool) and version > 0, "version")
    batch_dir = path.parent
    calibration = _case_set(document.get("calibration"), "calibration", batch_dir)
    held_out = _case_set(document.get("held_out"), "held_out", batch_dir)
    for one, other in ((calibration, held_out), (held_out, calibration)):
        _need(
            one.root != batch_dir and not one.root.is_relative_to(other.root),
            f"the {one.name} root must be its own directory, outside the {other.name} root",
        )
    _need(not path.is_relative_to(held_out.root), "batch.json must be outside the held-out root")
    batch = Batch(
        path,
        sha256_bytes(data),
        asset,
        version,
        Domain(document.get("domain")),
        parse_matrix(document.get("matrix")),
        calibration,
        held_out,
    )
    cal = batch.cases(calibration)
    problems = independence_problems(batch.domain, cal, batch.cases(held_out))
    problems += matrix_problems(batch.matrix, batch.domain, cal)
    _need(not problems, "; ".join(problems))
    return batch
