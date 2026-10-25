"""Synthetic v2 evidence tests the preflight, never certifies an actual asset."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from adapters.assets3d import gate_contract as gates
from adapters.assets3d import layer_stack


def save(path: Path, value: Any) -> str:
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def evidence(tmp_path: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
    mesh = b"synthetic fixture mesh bytes"
    (tmp_path / "low.obj").write_bytes(mesh)
    mesh_hash = hashlib.sha256(mesh).hexdigest()
    proof_hash = save(
        tmp_path / "proof.json", {"inspection": True, "low_high_fidelity": {"pass": True}}
    )
    manifest: dict[str, Any] = {
        "schema": 1,
        "type": "piece-manifest",
        "files": {
            "mesh": {
                "path": "low.obj",
                "bytes": len(mesh),
                "sha256": {"algorithm": "sha256", "value": mesh_hash, "verification": "verified"},
            },
            "proof": {
                "path": "proof.json",
                "bytes": (tmp_path / "proof.json").stat().st_size,
                "sha256": {"algorithm": "sha256", "value": proof_hash, "verification": "verified"},
            },
        },
        "meshes": {"low": {"file": "mesh"}},
        "gates": {"technical": {}, "visual": {}, "user": {}},
        "invalidations": [],
    }
    requirements: dict[str, list[str]] = {}
    for role, stages in gates.ROLES.items():
        requirements[role] = []
        for reviewer in ("producer", "independent"):
            key = role + "-" + reviewer
            refs = [{"file": "proof", "selector": "/inspection"}]
            if role == "low_high_fidelity":
                refs.append({"file": "proof", "selector": "/low_high_fidelity"})
            manifest["gates"]["technical"][key] = {
                "stages": sorted(stages),
                "scope": role,
                "state": "pass",
                "applicability": "confirmed",
                "origin": "inspection",
                "reviewer": {
                    "agent": reviewer,
                    "session": reviewer + "-session",
                    "model": "model",
                    "role": reviewer,
                },
                "moment": "2026-10-24T12:00:00Z",
                "dependencies": [
                    {"target": "/meshes/low", "verification": "equal", "evidence": refs}
                ],
                "evidence": refs,
                "differences": [],
                "open_items": [],
            }
            requirements[role].append("/gates/technical/" + key)
    hashes = {
        key: "a" * 64
        for key in ("positions", "uvs", "corner_normals", "triangulation", "materials")
    }
    report = {
        "source": {"name": "low.obj", "sha256": mesh_hash, "size": len(mesh)},
        "hashes": hashes,
        "certificate": {"status": "pass", "hashes": hashes},
    }
    report_hash = save(tmp_path / "import.json", report)
    request = {
        "schema": gates.SCHEMA,
        "root": str(tmp_path),
        "manifest": {"path": "manifest.json", "sha256": save(tmp_path / "manifest.json", manifest)},
        "import_report": {"path": "import.json", "sha256": report_hash},
        "requirements": requirements,
    }
    return request, manifest, tmp_path


def refresh(request: dict[str, Any], manifest: dict[str, Any], root: Path) -> None:
    request["manifest"]["sha256"] = save(root / "manifest.json", manifest)


def test_verified_current_evidence_is_eligible_without_granting_production(
    evidence: tuple[dict[str, Any], dict[str, Any], Path],
) -> None:
    request, _, _ = evidence
    result = gates.assess(request)
    assert result.eligible and result.problems == ()
    assert result.production_authorized is False and result.diagnostic is False


@pytest.mark.parametrize(
    "status,eligible", [("pass", True), ("warn", True), ("fail", False), ("unknown", False)]
)
def test_certificate_status_and_diagnostic_marking(
    evidence: tuple[dict[str, Any], dict[str, Any], Path], status: str, eligible: bool
) -> None:
    request, _, root = evidence
    report = json.loads((root / "import.json").read_bytes())
    report["certificate"]["status"] = status
    request["import_report"]["sha256"] = save(root / "import.json", report)
    result = gates.assess(request, diagnostic=True)
    assert result.eligible is eligible and result.diagnostic is True
    assert result.production_authorized is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("state", "pending"),
        ("state", "fail"),
        ("applicability", "reopened"),
        ("applicability", "not-verified"),
    ],
)
def test_parallel_failed_or_unverified_gate_cannot_be_hidden_by_pass(
    evidence: tuple[dict[str, Any], dict[str, Any], Path], field: str, value: str
) -> None:
    request, manifest, root = evidence
    extra = dict(manifest["gates"]["technical"]["bake-producer"])
    extra[field] = value
    manifest["gates"]["technical"]["another-upstream"] = extra
    refresh(request, manifest, root)
    result = gates.assess(request)
    assert not result.eligible and "another-upstream" in result.problems[0]


@pytest.mark.parametrize(
    "problem",
    [
        "wrong-stage",
        "no-fidelity",
        "same-agent",
        "same-session",
        "no-dependency",
        "changed-dependency",
        "missing-selector",
        "stale-invalidation",
    ],
)
def test_incomplete_or_mismatched_proof_refuses(
    evidence: tuple[dict[str, Any], dict[str, Any], Path], problem: str
) -> None:
    request, manifest, root = evidence
    gate = manifest["gates"]["technical"]["low_high_fidelity-independent"]
    if problem == "wrong-stage":
        gate["stages"] = ["low_uv"]
    elif problem == "no-fidelity":
        gate["evidence"] = [{"file": "proof", "selector": "/inspection"}]
    elif problem == "same-agent":
        gate["reviewer"]["agent"] = "producer"
    elif problem == "same-session":
        gate["reviewer"]["session"] = "producer-session"
    elif problem == "no-dependency":
        gate["dependencies"] = []
    elif problem == "changed-dependency":
        gate["dependencies"][0]["verification"] = "changed"
    elif problem == "missing-selector":
        gate["evidence"] = [{"file": "proof", "selector": "/missing"}]
    else:
        manifest["invalidations"] = [
            {"moment": gate["moment"], "gates": ["/gates/technical/low_high_fidelity-independent"]}
        ]
    refresh(request, manifest, root)
    result = gates.assess(request)
    assert not result.eligible and result.problems


@pytest.mark.parametrize(
    "problem",
    ["mesh", "proof", "certificate-source", "certificate-hashes", "path-escape", "unverified-file"],
)
def test_pins_prevent_mixed_snapshots(
    evidence: tuple[dict[str, Any], dict[str, Any], Path], problem: str
) -> None:
    request, manifest, root = evidence
    if problem in {"mesh", "proof"}:
        (root / ("low.obj" if problem == "mesh" else "proof.json")).write_bytes(b"changed")
    elif problem.startswith("certificate"):
        report = json.loads((root / "import.json").read_bytes())
        if problem == "certificate-source":
            report["source"]["sha256"] = "b" * 64
        else:
            report["certificate"]["hashes"]["positions"] = "b" * 64
        request["import_report"]["sha256"] = save(root / "import.json", report)
    elif problem == "path-escape":
        manifest["files"]["proof"]["path"] = "../proof.json"
    else:
        manifest["files"]["proof"]["sha256"]["verification"] = "not-verified"
    refresh(request, manifest, root)
    assert not gates.assess(request).eligible


def test_input_change_during_check_is_refused(
    evidence: tuple[dict[str, Any], dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    request, _, root = evidence
    original = gates.Evidence.unchanged

    def changed(self: gates.Evidence) -> None:
        (root / "low.obj").write_bytes(b"changed during check")
        original(self)

    monkeypatch.setattr(gates.Evidence, "unchanged", changed)
    assert "changed during preflight" in gates.assess(request).problems[0]


def test_duplicate_keys_cannot_replace_a_failed_gate(
    evidence: tuple[dict[str, Any], dict[str, Any], Path],
) -> None:
    request, _, root = evidence
    original = (root / "manifest.json").read_bytes()
    raw = original.replace(b'"state": "pass"', b'"state": "fail", "state": "pass"', 1)
    (root / "manifest.json").write_bytes(raw)
    request["manifest"]["sha256"] = hashlib.sha256(raw).hexdigest()
    assert "duplicate JSON key" in gates.assess(request).problems[0]


def test_preflight_cli_only_reports_and_never_executes_pipeline(
    evidence: tuple[dict[str, Any], dict[str, Any], Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _, root = evidence
    path = root / "request.json"
    save(path, request)

    def forbidden(argv: list[str]) -> int:
        raise AssertionError("preflight must not enter the executable pipeline")

    monkeypatch.setattr(layer_stack, "run", forbidden)
    assert layer_stack.main(["check-production", str(path)]) == 0
    reply = json.loads(capsys.readouterr().out)
    assert reply["eligible"] is True and reply["production_authorized"] is False
    (root / "low.obj").write_bytes(b"changed")
    assert layer_stack.main(["check-production", str(path), "--diagnostic"]) == 1
    reply = json.loads(capsys.readouterr().out)
    assert reply["eligible"] is False and reply["diagnostic"] is True


@pytest.mark.parametrize("stages", [[], ["low_uv_typo"], ["painting", "painting"]])
def test_invalid_stage_declarations_cannot_hide_pending_gates(
    evidence: tuple[dict[str, Any], dict[str, Any], Path], stages: list[str]
) -> None:
    request, manifest, root = evidence
    gate = dict(manifest["gates"]["technical"]["bake-producer"])
    gate.update(state="pending", stages=stages)
    manifest["gates"]["technical"]["malformed-stage"] = gate
    refresh(request, manifest, root)
    result = gates.assess(request)
    assert not result.eligible and "stage names" in result.problems[0]


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_nonstandard_json_constants_refuse(
    evidence: tuple[dict[str, Any], dict[str, Any], Path], constant: str
) -> None:
    request, _, root = evidence
    original = (root / "manifest.json").read_bytes()
    raw = original[:-1] + b', "unexpected": ' + constant.encode() + b"}"
    (root / "manifest.json").write_bytes(raw)
    request["manifest"]["sha256"] = hashlib.sha256(raw).hexdigest()
    assert "non-standard JSON constant" in gates.assess(request).problems[0]


@pytest.mark.parametrize("selected", ["", " "])
def test_empty_selected_text_is_not_evidence(
    evidence: tuple[dict[str, Any], dict[str, Any], Path], selected: str
) -> None:
    request, manifest, root = evidence
    raw = json.loads((root / "proof.json").read_bytes())
    raw["inspection"] = selected
    proof = manifest["files"]["proof"]
    proof["sha256"]["value"] = save(root / "proof.json", raw)
    proof["bytes"] = (root / "proof.json").stat().st_size
    refresh(request, manifest, root)
    assert "selected evidence is empty" in gates.assess(request).problems[0]
