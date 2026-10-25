"""Read-only QG-02 preflight of pinned v2 evidence (decision 360).

This checks recorded prerequisites, not artistic quality or permission to cut over.
It is not a transferable admission ticket: the execution/import boundary must check
the same inputs again before mutating a project.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Never

SCHEMA = "uzpainter/assets3d-admission/1"
ROLES = {
    "geometry_fit": frozenset({"geometry", "fit"}),
    "low_uv": frozenset({"low_uv"}),
    "bake": frozenset({"bake"}),
    "low_high_fidelity": frozenset({"bake"}),
}
UPSTREAM = frozenset({"geometry", "fit", "coverage", "low_uv", "bake"})
STAGES = UPSTREAM | {"painting", "rig", "export"}


class EvidenceError(ValueError):
    """The current prerequisite has no unambiguous, verifiable evidence."""


def load_json(raw: bytes) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise EvidenceError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def nonstandard(value: str) -> Never:
        raise EvidenceError(f"non-standard JSON constant: {value}")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=nonstandard)


@dataclass(frozen=True)
class Assessment:
    eligible: bool
    diagnostic: bool
    problems: tuple[str, ...]
    manifest_sha256: str | None = None
    mesh_sha256: str | None = None
    certificate_status: str | None = None
    production_authorized: bool = False

    def json(self) -> dict[str, Any]:
        return asdict(self)


def object_of(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise EvidenceError(f"{context}: expected an object")
    return value


def text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceError(f"{context}: missing nonempty string")
    return value


def array(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise EvidenceError(f"{context}: expected an array")
    return value


def digest(value: Any, context: str) -> str:
    result = text(value, context)
    if re.fullmatch(r"[0-9a-f]{64}", result) is None:
        raise EvidenceError(f"{context}: expected lowercase SHA-256")
    return result


def pointer(document: Any, path: str) -> Any:
    if not path.startswith("/"):
        raise EvidenceError(f"{path}: expected a local JSON Pointer")
    value = document
    for part in path[1:].split("/"):
        if re.search(r"~(?![01])", part):
            raise EvidenceError(f"{path}: invalid JSON Pointer escape")
        key = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and key in value:
            value = value[key]
        elif isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", key):
            if int(key) >= len(value):
                raise EvidenceError(f"{path}: array index missing")
            value = value[int(key)]
        else:
            raise EvidenceError(f"{path}: target missing")
    return value


def moment(value: Any, context: str) -> datetime:
    raw = text(value, context)
    try:
        result = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise EvidenceError(f"{context}: invalid moment") from error
    if result.tzinfo is None:
        if len(raw) != 10:
            raise EvidenceError(f"{context}: timestamp needs an explicit timezone")
        result = result.replace(tzinfo=UTC)
    return result


class Evidence:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=True)
        self.pins: dict[Path, str] = {}
        self.manifest: dict[str, Any] = {}

    def read(self, relative: Any, expected: Any) -> bytes:
        name = text(relative, "file path")
        parts = PurePosixPath(name)
        if parts.is_absolute() or ".." in parts.parts or "\\" in name or ":" in name:
            raise EvidenceError(f"{name}: path must stay relative to the Assets3D root")
        path = (self.root / name).resolve(strict=True)
        if not path.is_relative_to(self.root) or not path.is_file():
            raise EvidenceError(f"{name}: file escapes the Assets3D root")
        wanted = digest(expected, name)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != wanted:
            raise EvidenceError(f"{name}: bytes differ from pinned SHA-256")
        if path in self.pins and self.pins[path] != wanted:
            raise EvidenceError(f"{name}: conflicting snapshots")
        self.pins[path] = wanted
        return raw

    def file(self, key: Any) -> bytes:
        name = text(key, "file key")
        entries = object_of(self.manifest.get("files"), "files")
        entry = object_of(entries.get(name), f"files.{name}")
        sha = object_of(entry.get("sha256"), f"files.{name}.sha256")
        if sha.get("algorithm") != "sha256" or sha.get("verification") != "verified":
            raise EvidenceError(f"files.{name}: digest has not been verified")
        raw = self.read(entry.get("path"), sha.get("value"))
        if type(entry.get("bytes")) is not int or entry["bytes"] != len(raw):
            raise EvidenceError(f"files.{name}: byte count differs")
        return raw

    def sources(self, sources: Any, context: str) -> None:
        refs = array(sources, context)
        if not refs:
            raise EvidenceError(f"{context}: evidence missing")
        for item in refs:
            ref = object_of(item, context)
            raw = self.file(ref.get("file"))
            if "selector" in ref:
                selector = text(ref["selector"], context)
                selected = pointer(load_json(raw), selector)
                if (
                    selected is None
                    or selected is False
                    or selected == {}
                    or selected == []
                    or (isinstance(selected, str) and not selected.strip())
                ):
                    raise EvidenceError(f"{context}: selected evidence is empty")

    def dependency(self, value: Any) -> str:
        dep = object_of(value, "dependency")
        target = text(dep.get("target"), "dependency.target")
        if not target.startswith(("/files/", "/meshes/")):
            raise EvidenceError(f"{target}: unsupported dependency target")
        if dep.get("verification") not in {"equal", "equivalent"}:
            raise EvidenceError(f"{target}: dependency is not currently verified")
        record = pointer(self.manifest, target)
        if target.startswith("/files/"):
            key = target.split("/")[2].replace("~1", "/").replace("~0", "~")
            self.file(key)
        else:
            mesh_path = "/".join(target.split("/")[:3])
            mesh = object_of(pointer(self.manifest, mesh_path), mesh_path)
            self.file(mesh.get("file"))
            if "/hashes/" in target:
                semantic = object_of(record, target)
                sha = object_of(semantic.get("sha256"), target)
                if sha.get("verification") != "verified":
                    raise EvidenceError(f"{target}: semantic hash unverified")
                digest(sha.get("value"), target)
                serialization = object_of(semantic.get("serialization"), target)
                for field in ("algorithm", "precision", "order", "space"):
                    text(serialization.get(field), f"{target}.{field}")
        self.sources(dep.get("evidence"), f"{target}.evidence")
        return target

    def unchanged(self) -> None:
        for path, expected in self.pins.items():
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise EvidenceError(f"{path.name}: input changed during preflight")


def assess(request: dict[str, Any], *, diagnostic: bool = False) -> Assessment:
    """Check a pinned request without modifying assets, projects, sessions or approvals."""
    manifest_hash = mesh_hash = status = None
    try:
        if request.get("schema") != SCHEMA:
            raise EvidenceError("unsupported admission request schema")
        evidence = Evidence(Path(text(request.get("root"), "root")))
        pin = object_of(request.get("manifest"), "manifest pin")
        manifest_hash = digest(pin.get("sha256"), "manifest.sha256")
        manifest = object_of(load_json(evidence.read(pin.get("path"), manifest_hash)), "manifest")
        evidence.manifest = manifest
        if (
            type(manifest.get("schema")) is not int
            or manifest.get("schema") != 1
            or manifest.get("type") != "piece-manifest"
        ):
            raise EvidenceError("expected Assets3D v2 piece-manifest (schema=1)")
        low = object_of(pointer(manifest, "/meshes/low"), "meshes.low")
        mesh_bytes = evidence.file(low.get("file"))
        mesh_hash = hashlib.sha256(mesh_bytes).hexdigest()
        report_pin = object_of(request.get("import_report"), "import_report pin")
        report = object_of(
            load_json(evidence.read(report_pin.get("path"), report_pin.get("sha256"))),
            "import_report",
        )
        source = object_of(report.get("source"), "import_report.source")
        if source.get("sha256") != mesh_hash or source.get("size") != len(mesh_bytes):
            raise EvidenceError("certificate import source differs from the current low mesh")
        if report.get("external_files"):
            raise EvidenceError("external mesh files need a verified import-boundary binding")
        certificate = object_of(report.get("certificate"), "certificate")
        hashes = object_of(report.get("hashes"), "import hashes")
        for name in ("positions", "uvs", "corner_normals", "triangulation", "materials"):
            digest(hashes.get(name), f"import hashes.{name}")
        if certificate.get("hashes") != hashes:
            raise EvidenceError("certificate and import report describe different mesh hashes")
        status = text(certificate.get("status"), "certificate.status")
        if status not in {"pass", "warn"}:
            raise EvidenceError(f"mesh certificate is {status}, not pass or warn")
        gates: dict[str, dict[str, Any]] = {}
        for family in ("technical", "visual", "user"):
            group = object_of(pointer(manifest, f"/gates/{family}"), f"gates.{family}")
            for key, value in group.items():
                gate = object_of(value, f"gate {key}")
                declared = [text(s, key) for s in array(gate.get("stages"), key)]
                stages = set(declared)
                if not stages or not stages <= STAGES or len(stages) != len(declared):
                    raise EvidenceError(
                        f"gate {key}: stages must be nonempty, unique v2 stage names"
                    )
                if stages & UPSTREAM:
                    escaped = key.replace("~", "~0").replace("/", "~1")
                    gates[f"/gates/{family}/{escaped}"] = gate
        for path, gate in gates.items():
            if gate.get("state") == "not_applicable":
                if gate.get("applicability") != "confirmed":
                    raise EvidenceError(f"{path}: applicability unverified")
                text(gate.get("justification"), path)
                continue
            if gate.get("state") != "pass" or gate.get("applicability") != "confirmed":
                raise EvidenceError(f"{path}: every applicable upstream gate needs pass/confirmed")
            text(gate.get("scope"), path)
            when = moment(gate.get("moment"), path)
            reviewer = object_of(gate.get("reviewer"), path)
            for field in ("agent", "session", "model"):
                text(reviewer.get(field), f"{path}.reviewer.{field}")
            evidence.sources(gate.get("evidence"), path)
            deps = array(gate.get("dependencies"), path)
            targets = [evidence.dependency(d) for d in deps]
            if not any(t == "/meshes/low" or t.startswith("/meshes/low/") for t in targets):
                raise EvidenceError(f"{path}: current low-mesh dependency missing")
            for invalidation in array(manifest.get("invalidations"), "invalidations"):
                invalid = object_of(invalidation, "invalidation")
                if path in array(invalid.get("gates"), "invalidation.gates") and when <= moment(
                    invalid.get("moment"), "invalidation.moment"
                ):
                    raise EvidenceError(f"{path}: unresolved invalidation")
        roles = object_of(request.get("requirements"), "requirements")
        if set(roles) != set(ROLES):
            raise EvidenceError(
                "requirements must name geometry_fit, low_uv, bake, low_high_fidelity"
            )
        for role, required_stages in ROLES.items():
            paths = array(roles[role], role)
            if len(paths) != len(set(text(p, role) for p in paths)):
                raise EvidenceError(f"{role}: duplicate gate binding")
            reviews: dict[str, list[dict[str, Any]]] = {"producer": [], "independent": []}
            for path in paths:
                bound_gate = gates.get(text(path, role))
                if bound_gate is None or bound_gate.get("state") != "pass":
                    raise EvidenceError(f"{role}: binding is not a passing upstream gate")
                gate = bound_gate
                reviewer = object_of(gate.get("reviewer"), role)
                kind = reviewer.get("role")
                if kind not in reviews:
                    raise EvidenceError(f"{role}: needs producer and independent inspection")
                if role == "low_high_fidelity" and not any(
                    ref.get("selector") == "/low_high_fidelity" for ref in gate["evidence"]
                ):
                    raise EvidenceError("low_high_fidelity: explicit fidelity evidence missing")
                reviews[kind].append(gate)
            for kind, selected in reviews.items():
                covered = {stage for gate in selected for stage in gate["stages"]}
                if not required_stages <= covered:
                    raise EvidenceError(f"{role}: {kind} inspection does not cover required stages")
            for producer in reviews["producer"]:
                for independent in reviews["independent"]:
                    first, second = producer["reviewer"], independent["reviewer"]
                    if first["agent"] == second["agent"] or first["session"] == second["session"]:
                        raise EvidenceError(f"{role}: independent reviewer is the producer")
        evidence.unchanged()
        return Assessment(True, diagnostic, (), manifest_hash, mesh_hash, status)
    except (EvidenceError, OSError, ValueError, KeyError, TypeError) as error:
        return Assessment(False, diagnostic, (str(error),), manifest_hash, mesh_hash, status)


def assess_file(path: Path, *, diagnostic: bool = False) -> Assessment:
    try:
        request = object_of(load_json(path.read_bytes()), "request")
    except (OSError, ValueError) as error:
        return Assessment(False, diagnostic, (str(error),))
    return assess(request, diagnostic=diagnostic)


def main(argv: list[str]) -> int:
    if len(argv) not in (1, 2) or (len(argv) == 2 and argv[1] != "--diagnostic"):
        sys.stderr.write(
            "usage: python -m adapters.assets3d check-production REQUEST [--diagnostic]\n"
        )
        return 2
    result = assess_file(Path(argv[0]), diagnostic=len(argv) == 2)
    sys.stdout.write(json.dumps(result.json()) + "\n")
    return 0 if result.eligible else 1
