"""Build a private V1 diagnostic fixture from an admitted capture and an owned closed base.

No capture or build: callers supply both native test binaries explicitly. Outputs are new files
in an existing private directory. Partial outputs remain on failure and must never be reused.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import traceback
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from tools.parity import filter_observation_import as observation
from tools.parity.preserve_diagnostic_evidence import file_fingerprint, private_path
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import OracleStore, locate


@dataclass(frozen=True)
class Request:
    project: Path
    project_sha256: str
    manifest: Path
    export_binary: Path
    export_sha256: str
    pyapi_binary: Path
    pyapi_sha256: str
    output_prefix: Path


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def closed_project(path: Path) -> None:
    require(path.is_file() and path.suffix == ".uzp", "closed project required")
    lock = private_path(Path(str(path) + ".lock"), REPO_ROOT)
    wal = private_path(Path(str(path) + "-wal"), REPO_ROOT)
    private_path(Path(str(path) + "-shm"), REPO_ROOT)
    require(not lock.exists(), "project lock present")
    require(not wal.exists() or wal.stat().st_size == 0, "project WAL is not empty")


def verified_binary(path: Path, expected: str) -> Path:
    require(bool(re.fullmatch(r"[0-9a-f]{64}", expected)), "binary hash required")
    require(path.is_file() and not path.is_symlink(), "binary unavailable")
    require(file_fingerprint(path)[0] == expected, "binary hash differs")
    return path.resolve()


def outputs(prefix: Path) -> dict[str, Path]:
    suffixes = {
        "report": ".report.json",
        "project": ".uzp",
        "base": ".base.json",
        "payload": ".payload.json",
        "script": ".verify.py",
    }
    for stage in ("base", "import", "lifecycle"):
        for stream in ("stdout", "stderr"):
            suffixes[f"{stage}_{stream}"] = f".{stage}.{stream}.txt"
    return {key: prefix.with_name(prefix.name + suffix) for key, suffix in suffixes.items()}


def lifecycle_script(project: Path) -> bytes:
    return (
        "import uzpainter\n"
        "P = uzpainter.project\n"
        f"fixture = {str(project)!r}\n"
        "P.open(fixture)\nP.save()\nP.close()\nP.open(fixture)\nP.close()\n"
        "result = True\n"
    ).encode()


def create_fixture(request: Request, store: OracleStore) -> dict[str, object]:
    source = private_path(request.project, REPO_ROOT)
    prefix = private_path(request.output_prefix, REPO_ROOT)
    require(prefix.parent.is_dir(), "output parent must already exist")
    require(bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", prefix.name)), "invalid output prefix")
    require(bool(re.fullmatch(r"[0-9a-f]{64}", request.project_sha256)), "project hash required")
    closed_project(source)
    require(file_fingerprint(source)[0] == request.project_sha256, "project hash differs")
    export_binary = verified_binary(request.export_binary, request.export_sha256)
    pyapi_binary = verified_binary(request.pyapi_binary, request.pyapi_sha256)
    manifest_bytes = request.manifest.read_bytes()
    manifest = observation.parse(manifest_bytes)
    paths = outputs(prefix)
    protected = {source, request.manifest.resolve(), export_binary, pyapi_binary}
    for path in paths.values():
        require(private_path(path, REPO_ROOT) not in protected, "output overlaps input")
        require(not path.exists(), "output already exists")
    for suffix in (".lock", "-wal", "-shm"):
        sidecar = private_path(Path(str(paths["project"]) + suffix), REPO_ROOT)
        require(not sidecar.exists(), "output project sidecar already exists")

    report: dict[str, object] = {
        "schema": "uzpainter/filter-observation-fixture/1",
        "status": "refused",
        "stage": "reserve",
        "source_sha256": request.project_sha256,
        "export_binary_sha256": request.export_sha256,
        "pyapi_binary_sha256": request.pyapi_sha256,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "reserved_outputs": [],
        "observations": 0,
    }
    owned: list[str] = []
    with ExitStack() as cleanup:
        handles: dict[str, BinaryIO] = {}
        try:
            # Only files created by this invocation may be filled/replaced by native commands.
            for key, path in paths.items():
                handles[key] = cleanup.enter_context(path.open("xb"))
                owned.append(key)
            report["reserved_outputs"] = {key: str(paths[key]) for key in owned}
            report["stage"] = "copy"
            with source.open("rb") as original:
                while data := original.read(1024 * 1024):
                    require(handles["project"].write(data) == len(data), "short project copy")
            handles["project"].close()
            closed_project(source)
            require(
                file_fingerprint(source)[0] == request.project_sha256, "source changed during copy"
            )
            require(
                file_fingerprint(paths["project"])[0] == request.project_sha256,
                "project copy differs",
            )
            handles["base"].close()

            def native(stage: str, binary: Path, expected: str, arguments: list[str]) -> None:
                report["stage"] = stage
                verified_binary(binary, expected)
                closed_project(paths["project"])
                process = subprocess.run(
                    [str(binary), *arguments],
                    cwd=prefix.parent,
                    stdout=handles[f"{stage}_stdout"],
                    stderr=handles[f"{stage}_stderr"],
                    timeout=600,
                    check=False,
                )
                handles[f"{stage}_stdout"].flush()
                handles[f"{stage}_stderr"].flush()
                require(process.returncode == 0, "native operation refused")
                closed_project(paths["project"])

            native(
                "base",
                export_binary,
                request.export_sha256,
                ["filter-observation-base", str(paths["project"]), str(paths["base"])],
            )
            base = observation.parse(paths["base"].read_bytes())
            sets = base["projection"]["texture_sets"]
            require(type(sets) is list and len(sets) == 1, "one texture set required")
            stacks = sets[0]["stacks"]
            require(type(stacks) is list and len(stacks) == 1, "one stack required")
            report["stage"] = "admitted_payload"
            payload = observation.admitted_payload(
                store, manifest, base, texture_set=sets[0]["id"], stack=stacks[0]["id"]
            )
            encoded = observation.typed_json(payload) + b"\n"
            require(handles["payload"].write(encoded) == len(encoded), "short payload write")
            handles["payload"].close()
            native(
                "import",
                export_binary,
                request.export_sha256,
                ["filter-observation-import", str(paths["project"]), str(paths["payload"])],
            )
            script = lifecycle_script(paths["project"])
            require(handles["script"].write(script) == len(script), "short script write")
            handles["script"].close()
            native(
                "lifecycle",
                pyapi_binary,
                request.pyapi_sha256,
                [str(paths["script"]), "--test-gpu-unavailable"],
            )
            lines = paths["lifecycle_stdout"].read_text(encoding="utf-8").splitlines()
            reports = [line[len("UZP_JSON:") :] for line in lines if line.startswith("UZP_JSON:")]
            require(len(reports) == 1, "one lifecycle report required")
            lifecycle = observation.parse(reports[0].encode("utf-8"))
            require(
                lifecycle.get("status") == "ok" and lifecycle.get("result") is True,
                "lifecycle verification refused",
            )
            report.update(
                status="complete",
                observations=2,
                project_sha256=file_fingerprint(paths["project"])[0],
            )
        except Exception:
            report["error"] = traceback.format_exc()
        finally:
            report["reserved_outputs"] = {key: str(paths[key]) for key in owned}
            try:
                closed_project(source)
                require(
                    file_fingerprint(source)[0] == request.project_sha256,
                    "original project changed",
                )
                report["source_unchanged"] = True
            except Exception:
                report["source_unchanged"] = False
                report["status"] = "refused"
                report["source_error"] = traceback.format_exc()
            if "report" in handles:
                encoded_report = (
                    json.dumps(report, sort_keys=True, ensure_ascii=True) + "\n"
                ).encode()
                require(
                    handles["report"].write(encoded_report) == len(encoded_report),
                    "short report write",
                )
                handles["report"].flush()
    summary = {
        "status": report["status"],
        "observations": report["observations"],
        "report_sha256": file_fingerprint(paths["report"])[0],
    }
    if report["status"] == "complete":
        summary["project_sha256"] = report["project_sha256"]
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project", "manifest", "export-binary", "pyapi-binary", "output-prefix"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("project-sha256", "export-sha256", "pyapi-sha256"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    try:
        store = locate()
        require(store is not None, "oracle unavailable")
        assert store is not None
        result = create_fixture(Request(**vars(args)), store)
    except Exception:
        result = {"status": "refused", "observations": 0}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
