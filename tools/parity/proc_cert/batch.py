"""Certification batches: the declared domain, the calibration set and the held-out set.

Layout of one batch (`docs/architecture/05-procedural-content.md` §6, decisions 222 and 303):

    <batch dir>/batch.json              asset, domain, and both sets pinned by SHA-256
    <batch dir>/<calibration root>/...  the calibration case list (fitted against)
    <batch dir>/<held-out root>/...     the held-out case list (never seen by a fitter)

`batch.json` is committed before calibration starts; it pins each case list by the SHA-256 of
its bytes, so a held-out list changed after the pin no longer loads. The two roots are separate
directories, neither inside the other, so the held-out root can be fenced on its own
(`fence.py`). Case lists name oracles and image inputs by hash only; the bytes live in the
private store (`parity/STORE.md`).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

BATCH_SCHEMA = "uzpainter/parity/proc-cert-batch/1"
CASES_SCHEMA = "uzpainter/parity/proc-cert-cases/1"
SETS = ("calibration", "held_out")
FORMATS = {"u8": 255, "u16": 65535}  # native integer code values and their maximum
ENCODINGS = frozenset({"raw", "png"})  # raw: little-endian samples, rows top first, (h, w, c)
U32_MAX = (1 << 32) - 1

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
                "params": {
                    name: str(Fraction(value)) if _number(value) else value
                    for name, value in self.params.items()
                },
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
    return Case(
        case_id,
        set_name,
        mesh["id"],
        mesh["class"],
        mesh["uv_tiles"],
        dict(params),
        seed,
        _raster(document.get("output"), f"{where}: output"),
        {
            usage: (
                _raster(entry, f"{where}: input {usage}"),
                _blob(entry, f"{where}: input {usage}"),
            )
            for usage, entry in sorted(inputs.items())
        },
        _blob(document.get("oracle"), f"{where}: oracle"),
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

    def refusal(self, case: Case) -> Refusal | None:
        """The first field of `case` outside the domain, or None inside it. Nothing is clamped."""
        declared = set(self.ranges) | set(self.sets)
        if missing := sorted(declared - set(case.params)):
            return Refusal(f"params.{missing[0]}", "missing", "every declared parameter")
        if extra := sorted(set(case.params) - declared):
            return Refusal(f"params.{extra[0]}", case.params[extra[0]], "not a parameter")
        for name, (low, high) in sorted(self.ranges.items()):
            value = case.params[name]
            if not _number(value) or not low <= Fraction(value) <= high:
                return Refusal(f"params.{name}", value, [float(low), float(high)])
        for name, allowed in sorted(self.sets.items()):
            if case.params[name] not in allowed:
                return Refusal(f"params.{name}", case.params[name], allowed)
        for constraint in self.constraints:
            total = sum(
                Fraction(c) * Fraction(case.params[name])
                for name, c in constraint["coefficients"].items()
            )
            if total > Fraction(constraint["max"]):
                return Refusal("params", dict(case.params), constraint)
        if not 0 <= case.seed <= U32_MAX:
            return Refusal("seed", case.seed, [0, U32_MAX])
        if self.seed_policy == "listed" and case.seed not in self.seeds:
            return Refusal("seed", case.seed, self.seeds)
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
    cal_oracles = {case.oracle.sha256 for case in cal}
    problems.extend(
        f"held-out case {case.case_id} shares its oracle blob with the calibration set"
        for case in held
        if case.oracle.sha256 in cal_oracles
    )
    cal_signatures = {case.signature() for case in cal}
    problems.extend(
        f"held-out case {case.case_id} repeats a calibration case"
        for case in held
        if case.signature() in cal_signatures
    )
    if not {case.mesh_id for case in held} - {case.mesh_id for case in cal}:
        problems.append("the held-out set has no mesh outside the calibration set")
    single_seed = domain.seed_policy == "listed" and len(domain.seeds) == 1
    if not single_seed and not {case.seed for case in held} - {case.seed for case in cal}:
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
        calibration,
        held_out,
    )
    problems = independence_problems(batch.domain, batch.cases(calibration), batch.cases(held_out))
    _need(not problems, "; ".join(problems))
    return batch
