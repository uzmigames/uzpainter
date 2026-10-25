"""Synthetic v2 evidence tests the preflight, never certifies an actual asset."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from adapters.assets3d import client, layer_stack, runner
from adapters.assets3d import gate_contract as gates


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


def test_native_policy_pins_every_consumed_file_and_exact_report(
    evidence: tuple[dict[str, Any], dict[str, Any], Path],
) -> None:
    request, _, root = evidence
    path = root / "request.json"
    save(path, request)
    policy = gates.production_policy(path)
    assert policy["import_report"] == json.loads((root / "import.json").read_bytes())
    assert policy["request_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    pins = policy["pins"]
    assert {Path(pin["path"]).name for pin in pins} == {
        "request.json",
        "manifest.json",
        "import.json",
        "proof.json",
        "low.obj",
    }
    for pin in pins:
        file = Path(pin["path"])
        assert file.is_absolute()
        assert pin["size"] == len(file.read_bytes())
        assert pin["sha256"] == hashlib.sha256(file.read_bytes()).hexdigest()


def test_selectorless_empty_evidence_refuses_production_policy(
    evidence: tuple[dict[str, Any], dict[str, Any], Path],
) -> None:
    request, manifest, root = evidence
    empty = root / "empty.bin"
    empty.write_bytes(b"")
    manifest["files"]["empty"] = {
        "path": "empty.bin",
        "bytes": 0,
        "sha256": {
            "algorithm": "sha256",
            "verification": "verified",
            "value": hashlib.sha256(b"").hexdigest(),
        },
    }
    # Keep fidelity's explicit selector intact: only an upstream inspection lacks material.
    manifest["gates"]["technical"]["geometry_fit-producer"]["evidence"] = [{"file": "empty"}]
    refresh(request, manifest, root)
    path = root / "request.json"
    save(path, request)
    with pytest.raises(gates.EvidenceError, match="evidence file is empty"):
        gates.production_policy(path)


def test_execution_requires_explicit_mode_before_script_or_host(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(client.PRODUCTION_ENV, raising=False)
    monkeypatch.delenv(client.IMPORT_DIAGNOSTIC_ENV, raising=False)
    assert layer_stack.main([str(tmp_path / "never-read.py")]) == client.FAILED
    assert json.loads(capsys.readouterr().out)["error"]["type"] == "ProductionContextRequired"
    with pytest.raises(client.ProductionContextRequired):
        client.execute_python("raise AssertionError('never executed')")


def test_failed_evidence_refuses_before_launch_or_session_write(
    evidence: tuple[dict[str, Any], dict[str, Any], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, manifest, root = evidence
    manifest["gates"]["technical"]["bake-producer"]["state"] = "fail"
    refresh(request, manifest, root)
    path = root / "request.json"
    save(path, request)
    session = root / "session.json"
    session.write_text("unchanged", encoding="utf-8")
    monkeypatch.setenv(client.PRODUCTION_ENV, str(path))
    monkeypatch.delenv(client.IMPORT_DIAGNOSTIC_ENV, raising=False)
    monkeypatch.delenv(client.DIAGNOSTIC_ENV, raising=False)
    monkeypatch.setenv(client.SESSION_ENV, str(session))

    def forbidden() -> Path:
        raise AssertionError("host discovery must not happen")

    monkeypatch.setattr(client, "painter_exe", forbidden)
    with pytest.raises(client.HostError, match="upstream gate"):
        client.execute_python("raise AssertionError('never executed')")
    assert session.read_text(encoding="utf-8") == "unchanged"
    assert not session.with_name(session.name + ".lock").exists()


@pytest.mark.parametrize("acknowledge", [True, False])
def test_runner_installs_policy_once_and_checks_native_hashes(
    evidence: tuple[dict[str, Any], dict[str, Any], Path],
    acknowledge: bool,
) -> None:
    from types import SimpleNamespace

    request, _, root = evidence
    path = root / "request.json"
    save(path, request)
    policy = gates.production_policy(path)
    policy_path = root / "policy.json"
    save(policy_path, policy)
    installed: list[dict[str, Any]] = []

    def status() -> dict[str, Any]:
        return {
            "schema": "uzpainter/assets3d-production-status/1",
            "mode": "armed" if installed else "required",
            "policy_installed": bool(installed),
            "request_sha256": policy["request_sha256"] if installed else None,
            "source_sha256": (policy["source_sha256"] if acknowledge else "0" * 64)
            if installed
            else None,
        }

    native = SimpleNamespace(
        _assets3d_production_status=status,
        _assets3d_install_production_policy=lambda raw: installed.append(json.loads(raw)),
    )
    if acknowledge:
        assert runner.install_production_policy(native, policy_path) == status()
    else:
        with pytest.raises(runner.AdapterSessionError, match="did not arm"):
            runner.install_production_policy(native, policy_path)
    assert installed == [policy]


def test_wrapper_restores_context_even_when_script_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(client.PRODUCTION_ENV, "previous-request")
    monkeypatch.delenv(client.IMPORT_DIAGNOSTIC_ENV, raising=False)
    monkeypatch.setenv(layer_stack.ROOT_ENV, "previous-root")
    script = tmp_path / "layer.py"
    script.write_text(
        "import os\n"
        "assert os.environ['UZP_ASSETS3D_DIAGNOSTIC_IMPORT'] == '1'\n"
        "assert not os.environ['UZP_ASSETS3D_PRODUCTION_REQUEST']\n"
        "CLIENT = MCP_PYTHON = None\n"
        "def execute(code): pass\n"
        "def main(): raise RuntimeError('script failed')\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="script failed"):
        layer_stack.run(["--diagnostic-import", str(script)])
    assert os.environ[client.PRODUCTION_ENV] == "previous-request"
    assert client.IMPORT_DIAGNOSTIC_ENV not in os.environ
    assert os.environ[layer_stack.ROOT_ENV] == "previous-root"


@pytest.mark.parametrize(
    "probe",
    [
        None,
        {},
        {"assets3d_production_guard": 1},
        {
            "schema": "uzpainter/runtime-capabilities/1",
            "assets3d_production_guard": True,
        },
    ],
)
def test_old_or_ambiguous_host_never_runs_production_script(
    evidence: tuple[dict[str, Any], dict[str, Any], Path],
    monkeypatch: pytest.MonkeyPatch,
    probe: Any,
) -> None:
    from types import SimpleNamespace

    request, _, root = evidence
    path = root / "request.json"
    save(path, request)
    monkeypatch.setenv(client.PRODUCTION_ENV, str(path))
    monkeypatch.delenv(client.IMPORT_DIAGNOSTIC_ENV, raising=False)
    monkeypatch.delenv(client.DIAGNOSTIC_ENV, raising=False)
    monkeypatch.setattr(client, "painter_exe", lambda: root / "UzPainter.exe")
    calls: list[list[str]] = []

    def run(argv: list[str]) -> Any:
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout=client.JSON_PREFIX + json.dumps(probe))

    monkeypatch.setattr(client, "run_painter", run)
    with pytest.raises(client.HostError, match="does not support"):
        client.execute_python("raise AssertionError('never executed')")
    assert calls == [[str(root / "UzPainter.exe"), "capabilities", "--runtime"]]


@pytest.mark.parametrize("mode", ["absent", "armed", "unknown"])
def test_runner_requires_host_latch_before_restore_or_script(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    import sys
    from types import SimpleNamespace

    code, session, report, policy = [
        tmp_path / name for name in ("code.py", "session.json", "report.json", "policy.json")
    ]
    code.write_text("raise AssertionError('script must not execute')", encoding="utf-8")
    session.write_text('{"untouched": true}', encoding="utf-8")
    policy.write_text('{"schema":"uzpainter/assets3d-native-policy/1"}', encoding="utf-8")
    native = SimpleNamespace(
        _assets3d_production_status=lambda: {
            "schema": "uzpainter/assets3d-production-status/1",
            "mode": mode,
            "policy_installed": False,
            "request_sha256": None,
            "source_sha256": None,
        }
    )
    monkeypatch.setitem(sys.modules, "uzpainter", native)
    with pytest.raises(runner.AdapterSessionError, match="not REQUIRED"):
        runner.main(["runner.py", str(code), str(session), str(report), str(policy)])
    assert session.read_text(encoding="utf-8") == '{"untouched": true}'
    assert "carried" not in json.loads(report.read_bytes())


def test_client_propagates_verified_policy_and_requires_native_ack(
    evidence: tuple[dict[str, Any], dict[str, Any], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    request, _, root = evidence
    request_path = root / "request.json"
    save(request_path, request)
    monkeypatch.setenv(client.PRODUCTION_ENV, str(request_path))
    monkeypatch.delenv(client.IMPORT_DIAGNOSTIC_ENV, raising=False)
    monkeypatch.delenv(client.DIAGNOSTIC_ENV, raising=False)
    monkeypatch.setenv(client.SCRATCH_ENV, str(root))
    monkeypatch.setenv(client.SESSION_ENV, str(root / "session.json"))
    monkeypatch.setattr(client, "painter_exe", lambda: root / "UzPainter.exe")
    acknowledge = True
    calls: list[list[str]] = []

    def run(argv: list[str]) -> Any:
        calls.append(argv)
        if argv[1] == "capabilities":
            host = {"schema": "uzpainter/runtime-capabilities/1", "assets3d_production_guard": 1}
        else:
            assert client.PRODUCTION_FLAG in argv[: argv.index("--")]
            policy = json.loads(Path(argv[-1]).read_bytes())
            assert policy == gates.production_policy(request_path)
            status = {
                "schema": "uzpainter/assets3d-production-status/1",
                "mode": "armed",
                "policy_installed": True,
                "request_sha256": policy["request_sha256"],
                "source_sha256": policy["source_sha256"],
            }
            Path(argv[-2]).write_text(
                json.dumps({"production_guard": status} if acknowledge else {}), encoding="utf-8"
            )
            host = {"status": "ok", "result": None, "stdout": "", "stderr": ""}
        return SimpleNamespace(returncode=0, stdout=client.JSON_PREFIX + json.dumps(host))

    monkeypatch.setattr(client, "run_painter", run)
    reply, status = client.execute_python("result = None")
    assert status == client.OK and reply["production_guard"]["mode"] == "armed"
    assert "diagnostic" not in reply
    assert not list(root.glob("uzp-a3d-*"))
    acknowledge = False
    with pytest.raises(client.HostError, match="did not acknowledge"):
        client.execute_python("result = None")
    assert len(calls) == 4


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
