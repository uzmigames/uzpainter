"""Tests of phase1.17_export-publication-receipts (P1-EXPORT, `docs/architecture/08-export.md` §5;
`src/export/publish.h`, `fixed_names.h`, `receipt.h`, `cli.h`; decision 097; EXP-06, EXP-09,
ARC-11, INT-21, QG-03).

Every case runs `uzp-export-tests.exe` on the CPU (every lane). The fault cases arm the test-only
hooks of `src/export/fault.h` (`--fault <point>:<n>`), which terminate the process (exit 77) or
fail a step between every publication step and around every fixed-name copy; a consumer then reads
the delivery at once, through the generation-pinning adapter (`consume-pinned`) or under the
publication lock (`consume-locked`).
"""

from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import time
from pathlib import Path
from typing import Any

import jsonschema
import numpy as np
import pytest

from tests.export.conftest import REPO_ROOT
from tests.export.test_export_encoders import (
    GRID,
    PNG16,
    TEMPLATES,
    chan,
    config,
    files_under,
    ramp_codes,
    spec,
)

SCHEMA = REPO_ROOT / "src" / "export" / "schema" / "receipt.schema.json"
KILLED = 77
STAGING = ".uzp-staging"


def call(exe: Path, *args: str) -> tuple[int, list[dict[str, Any]], str]:
    proc = subprocess.run(
        [str(exe), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=1800,
        check=False,
    )
    lines = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    return proc.returncode, lines, proc.stderr


def one(exe: Path, *args: str) -> dict[str, Any]:
    code, lines, err = call(exe, *args)
    assert code == 0 and len(lines) == 1, (code, lines, err)
    return lines[0]


def inverted_spec(tmp: Path) -> Path:
    """`spec`, filled from the ramp with every code inverted (65535 - code): every file differs."""
    from tools.parity.feasibility import png

    path = spec(tmp)
    document = json.loads(path.read_text(encoding="utf-8"))
    data = png.encode((65535 - ramp_codes()).astype(np.int64), 16)
    (tmp / "inverted.png").write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    document["resources"] = [{"sha256": sha, "png": "inverted.png"}]
    for source in document["layers"][0]["sources"].values():
        source["bitmap"] = sha
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def config_b(out: Path) -> dict[str, Any]:
    """`config` without the Height map, with a combined normal (Normal_OpenGL) instead."""
    cfg = config(out)
    maps = cfg["exportPresets"][0]["maps"]
    maps[2] = {
        "fileName": "$textureSet_Normal",
        "channels": [chan(c, "virtualMap", "Normal_OpenGL") for c in "RGB"],
    }
    return cfg


class Fixture:
    """Two exports A and B of different content and file sets into one exportPath, and the bytes
    of each, published alone elsewhere."""

    def __init__(self, exe: Path, tmp: Path) -> None:
        self.exe = exe
        self.tmp = tmp
        self.out = tmp / "out"
        self.spec_a = spec(tmp / "spec-a")
        self.spec_b = inverted_spec(tmp / "spec-b")
        self.expected = {
            "a": self.reference("a", self.spec_a, config),
            "b": self.reference("b", self.spec_b, config_b),
        }

    def config_path(self, name: str, out: Path) -> Path:
        cfg = config(out) if name == "a" else config_b(out)
        path = self.tmp / f"config-{name}-{abs(hash(str(out)))}.json"
        path.write_text(json.dumps(cfg), encoding="utf-8")
        return path

    def reference(self, name: str, spec_path: Path, make: Any) -> dict[str, str]:
        out = self.tmp / f"reference-{name}"
        result = one(
            self.exe, "publish", str(TEMPLATES), str(spec_path), str(self.config_path(name, out))
        )
        assert "error" not in result, result
        return {f["relativePath"]: f["sha256"] for f in result["files"]}

    def publish(self, name: str, *fault: str) -> tuple[int, list[dict[str, Any]], str]:
        spec_path = self.spec_a if name == "a" else self.spec_b
        args = ["--fault", fault[0]] if fault else []
        return call(
            self.exe,
            *args,
            "publish",
            str(TEMPLATES),
            str(spec_path),
            str(self.config_path(name, self.out)),
        )


def current(out: Path) -> dict[str, Any] | None:
    path = out / "current.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def selected(out: Path) -> str:
    pointer = current(out)
    assert pointer is not None
    generation: str = pointer["generation"]
    return generation


def no_staging_names(out: Path) -> None:
    """3.3: no staging name in the pointer, in any receipt or journal, or among the delivered
    files."""
    for path in out.rglob("*"):
        if path.name in ("current.json", "receipt.json", "fixed-names.journal.json"):
            assert STAGING not in path.read_text(encoding="utf-8"), path


def consumed(exe: Path, out: Path, fixed: Path | None = None) -> dict[str, Any]:
    if fixed is None:
        return one(exe, "consume-pinned", str(out))
    return one(exe, "consume-locked", str(out), str(fixed))


def assert_one_generation(result: dict[str, Any], fx: Fixture, allowed: dict[str, str]) -> None:
    """The consumer read one complete generation of `allowed` ({generation: "a" | "b"}), or failed
    before consumption."""
    if "error" in result:
        assert "files" not in result, result
        return
    assert result["generation"] in allowed, result
    assert result["files"] == fx.expected[allowed[result["generation"]]], result


# ── Publication ──────────────────────────────────────────────────────────────


def test_publication_writes_a_verified_generation(export_tests: Path, tmp_path: Path) -> None:
    """2.1, 2.2, 3.3: the files go to generations/000001/files under their planned names, with
    plan.json and receipt.json; current.json names the generation and its receipt's SHA-256; the
    bytes equal WriteExport's (the parity writer); a second publication is generation 000002 and
    leaves the first untouched; nothing else is written under exportPath."""
    fx = Fixture(export_tests, tmp_path)
    code, [first], err = fx.publish("a")
    assert code == 0 and "error" not in first, (first, err)
    assert first["generation"] == "000001"
    generation = fx.out / "generations" / "000001"
    files = files_under(generation / "files")
    assert {k: hashlib.sha256(v).hexdigest() for k, v in files.items()} == fx.expected["a"]
    pointer = current(fx.out)
    receipt_bytes = (generation / "receipt.json").read_bytes()
    assert pointer == {
        "schema": "uzpainter/export-current/1",
        "generation": "000001",
        "receipt": "generations/000001/receipt.json",
        "receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
    }
    assert first["receipt_sha256"] == pointer["receipt_sha256"]
    plan = json.loads((generation / "plan.json").read_text(encoding="utf-8"))
    assert json.loads(receipt_bytes)["plan_hash"] == plan["hash"]

    flat = tmp_path / "flat"
    (tmp_path / "flat.json").write_text(json.dumps(config(flat)), encoding="utf-8")
    written = one(
        export_tests, "export", str(TEMPLATES), str(fx.spec_a), str(tmp_path / "flat.json")
    )
    assert "error" not in written, written
    assert files_under(flat) == files

    code, [second], err = fx.publish("b")
    assert code == 0 and second["generation"] == "000002", (second, err)
    assert files_under(generation / "files") == files
    assert sorted(p.name for p in fx.out.iterdir()) == [
        "current.json",
        "generations",
        "publication.lock",
    ]
    assert selected(fx.out) == "000002"
    no_staging_names(fx.out)
    assert consumed(export_tests, fx.out) == {"generation": "000002", "files": fx.expected["b"]}


@pytest.mark.parametrize(
    ("fault", "selected_after_kill", "after_recovery", "removed"),
    [
        ("kill_after_file:0", "000001", "000001", True),
        ("kill_after_file:1", "000001", "000001", True),
        ("kill_after_file:2", "000001", "000001", True),
        ("kill_after_plan", "000001", "000001", True),
        ("kill_after_receipt", "000001", "000002", False),
        ("kill_before_pointer_rename", "000001", "000002", False),
        ("kill_after_pointer_rename", "000002", "000002", False),
    ],
)
def test_interrupted_publication(
    export_tests: Path,
    tmp_path: Path,
    fault: str,
    selected_after_kill: str,
    after_recovery: str,
    removed: bool,
) -> None:
    """3.1, 3.3: the process killed after each file, after the plan, after the receipt and on
    either side of the pointer's rename: a consumer reading current.json at once gets the old or
    the new complete generation; `export --recover` publishes the new one when it is complete and
    removes it otherwise; no staging name is ever advertised."""
    fx = Fixture(export_tests, tmp_path)
    code, _, err = fx.publish("a")
    assert code == 0, err
    code, lines, err = fx.publish("b", fault)
    assert code == KILLED and lines == [], (code, lines, err)
    allowed = {"000001": "a", "000002": "b"}
    seen = consumed(export_tests, fx.out)
    assert_one_generation(seen, fx, allowed)
    assert seen["generation"] == selected_after_kill
    no_staging_names(fx.out)

    report = one(export_tests, "recover", "--recover", str(fx.out))
    assert report["current_before"] == selected_after_kill
    assert report["current_after"] == after_recovery
    assert report["published"] == (
        after_recovery if after_recovery != selected_after_kill else None
    )
    assert [r["generation"] for r in report["removed"]] == (["000002"] if removed else [])
    assert report["damaged"] is None
    assert report["removed_staging_pointer"] == (fault == "kill_before_pointer_rename")
    expected_generations = ["000001"] if removed else ["000001", "000002"]
    assert sorted(p.name for p in (fx.out / "generations").iterdir()) == expected_generations
    assert consumed(export_tests, fx.out) == {
        "generation": after_recovery,
        "files": fx.expected[allowed[after_recovery]],
    }
    no_staging_names(fx.out)
    assert one(export_tests, "recover", "--recover", str(fx.out))["removed"] == []


def test_recovery_of_a_first_export_and_of_a_bad_pointer(
    export_tests: Path, tmp_path: Path
) -> None:
    """2.2: a first export killed before the pointer existed leaves nothing selected (the adapter
    fails before consumption) and recovery publishes it; a pointer that does not read fails the
    recovery before it changes anything."""
    fx = Fixture(export_tests, tmp_path)
    code, _, _ = fx.publish("a", "kill_before_pointer_rename")
    assert code == KILLED
    seen = consumed(export_tests, fx.out)
    assert seen["error"] == "Failure" and "nothing is published" in seen["message"], seen
    report = one(export_tests, "recover", "--recover", str(fx.out))
    assert report["current_before"] is None and report["published"] == "000001"
    assert consumed(export_tests, fx.out) == {"generation": "000001", "files": fx.expected["a"]}

    code, _, _ = fx.publish("b", "kill_after_file:1")
    assert code == KILLED
    (fx.out / "current.json").write_text("{not json", encoding="utf-8")
    code, lines, err = call(export_tests, "recover", "--recover", str(fx.out))
    assert code == 1 and lines == [] and "is not a delivery pointer" in err, (code, lines, err)
    assert sorted(p.name for p in (fx.out / "generations").iterdir()) == ["000001", "000002"]

    missing = tmp_path / "missing"
    code, lines, err = call(export_tests, "recover", "--recover", str(missing))
    assert code == 1 and "is not an export folder" in err and not missing.exists()


def test_damaged_selected_generation_is_reported_not_removed(
    export_tests: Path, tmp_path: Path
) -> None:
    """2.2: when a file of the selected generation no longer verifies, the adapter fails before
    consumption and recovery reports the generation (exit 1) without removing it."""
    fx = Fixture(export_tests, tmp_path)
    assert fx.publish("a")[0] == 0
    target = fx.out / "generations" / "000001" / "files" / "s0_User0.png"
    target.write_bytes(target.read_bytes()[:-1])
    seen = consumed(export_tests, fx.out)
    assert seen["error"] == "Failure" and "is not complete" in seen["message"], seen
    code, [report], _ = call(export_tests, "recover", "--recover", str(fx.out))
    assert code == 1 and report["damaged"]["generation"] == "000001", report
    assert (fx.out / "generations" / "000001").is_dir()


@pytest.mark.parametrize("fault", ["fail_encode:1", "fail_write:1"])
def test_failure_keeps_the_previous_generation(
    export_tests: Path, tmp_path: Path, fault: str
) -> None:
    """3.5: an encoder that throws and a write that fails return a failure from a process that
    stays alive (exit 0, a result printed); the previous generation stays selected and the
    failed one leaves no directory."""
    fx = Fixture(export_tests, tmp_path)
    assert fx.publish("a")[0] == 0
    before = current(fx.out)
    code, [result], err = fx.publish("b", fault)
    assert code == 0 and result["error"] == "Failure", (result, err)
    expected = "encoding" if fault.startswith("fail_encode") else "injected write failure"
    assert expected in result["message"], result
    assert current(fx.out) == before
    assert sorted(p.name for p in (fx.out / "generations").iterdir()) == ["000001"]
    assert consumed(export_tests, fx.out) == {"generation": "000001", "files": fx.expected["a"]}


def test_refusal_writes_nothing(export_tests: Path, tmp_path: Path) -> None:
    """3.5: a processing refused before evaluation (NotYetSupported) creates no generation and
    leaves the selected one."""
    fx = Fixture(export_tests, tmp_path)
    assert fx.publish("a")[0] == 0
    path = tmp_path / "refused.json"
    path.write_text(json.dumps(config(fx.out, dithering=True)), encoding="utf-8")
    result = one(export_tests, "publish", str(TEMPLATES), str(fx.spec_a), str(path))
    assert result["error"] == "NotYetSupported", result
    assert sorted(p.name for p in (fx.out / "generations").iterdir()) == ["000001"]


def test_publication_lock_excludes_writers(export_tests: Path, tmp_path: Path) -> None:
    """2.3: while another process holds the publication lock, a publication waits: the pointer
    does not change until the holder releases the lock, then the publication completes."""
    fx = Fixture(export_tests, tmp_path)
    assert fx.publish("a")[0] == 0
    holder = subprocess.Popen(
        [str(export_tests), "hold-lock", str(fx.out), "3000"],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert holder.stdout is not None and holder.stdout.readline().strip() == "held"
    writer = subprocess.Popen(
        [
            str(export_tests),
            "publish",
            str(TEMPLATES),
            str(fx.spec_b),
            str(fx.config_path("b", fx.out)),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    time.sleep(1.5)
    assert writer.poll() is None
    assert selected(fx.out) == "000001"
    assert not (fx.out / "generations" / "000002").exists()
    assert holder.wait(timeout=60) == 0
    out, _ = writer.communicate(timeout=600)
    assert writer.returncode == 0 and json.loads(out)["generation"] == "000002"


# ── Fixed names ──────────────────────────────────────────────────────────────


def fixed_fixture(export_tests: Path, tmp_path: Path) -> tuple[Fixture, Path]:
    """A published, fixed-name copy of A in `fixed/`, then B published."""
    fx = Fixture(export_tests, tmp_path)
    assert fx.publish("a")[0] == 0
    fixed = tmp_path / "fixed"
    copied = one(export_tests, "fixed-copy", str(fx.out), str(fixed))
    assert copied == {"generation": "000001", "files": list(fx.expected["a"])}, copied
    on_disk = files_under(fixed)
    on_disk.pop("fixed-names.journal.json")
    assert {k: hashlib.sha256(v).hexdigest() for k, v in on_disk.items()} == fx.expected["a"]
    assert fx.publish("b")[0] == 0
    return fx, fixed


def test_fixed_name_copy(export_tests: Path, tmp_path: Path) -> None:
    """2.3: the copy of the published generation under its fixed names, journalled; the names of
    the previous generation the new one lacks (s0_Height.exr) are removed; the locked reader
    consumes it."""
    fx, fixed = fixed_fixture(export_tests, tmp_path)
    copied = one(export_tests, "fixed-copy", str(fx.out), str(fixed))
    assert copied["generation"] == "000002"
    on_disk = files_under(fixed)
    journal = json.loads(on_disk.pop("fixed-names.journal.json"))
    assert journal == {
        "schema": "uzpainter/export-fixed-names/1",
        "generation": "000002",
        "files": list(fx.expected["b"]),
        "copied": list(fx.expected["b"]),
        "obsolete": [],
    }
    assert {k: hashlib.sha256(v).hexdigest() for k, v in on_disk.items()} == fx.expected["b"]
    assert consumed(export_tests, fx.out, fixed) == {
        "generation": "000002",
        "files": fx.expected["b"],
    }
    no_staging_names(tmp_path)


@pytest.mark.parametrize("point", ["kill_before_fixed_rename", "kill_after_fixed_rename"])
@pytest.mark.parametrize("index", [0, 1, 2])
def test_interrupted_fixed_name_copy(
    export_tests: Path, tmp_path: Path, point: str, index: int
) -> None:
    """3.2, 3.3: the fixed-name copy killed before and after the rename of each file; the
    fixed-name consumer invoked at once under the publication lock consumes one complete
    generation (the copy rolled forward from its journal), and through the pinning adapter the
    published one."""
    fx, fixed = fixed_fixture(export_tests, tmp_path)
    code, lines, err = call(
        export_tests, "--fault", f"{point}:{index}", "fixed-copy", str(fx.out), str(fixed)
    )
    assert code == KILLED and lines == [], (code, lines, err)
    journal = json.loads((fixed / "fixed-names.journal.json").read_text(encoding="utf-8"))
    assert journal["generation"] == "000002" and len(journal["copied"]) == index
    allowed = {"000001": "a", "000002": "b"}
    locked = consumed(export_tests, fx.out, fixed)
    assert_one_generation(locked, fx, allowed)
    assert locked["generation"] == "000002"
    on_disk = files_under(fixed)
    on_disk.pop("fixed-names.journal.json")
    assert {k: hashlib.sha256(v).hexdigest() for k, v in on_disk.items()} == fx.expected["b"]
    assert consumed(export_tests, fx.out) == {"generation": "000002", "files": fx.expected["b"]}
    no_staging_names(tmp_path)


def test_interrupted_fixed_name_copy_without_its_generation_fails_before_consumption(
    export_tests: Path, tmp_path: Path
) -> None:
    """3.2: when the generation an interrupted copy names no longer verifies, the locked reader
    cannot roll the copy forward and fails before consuming anything; `export --recover
    --fixed-names` fails the same way."""
    fx, fixed = fixed_fixture(export_tests, tmp_path)
    code, _, _ = call(
        export_tests, "--fault", "kill_after_fixed_rename:0", "fixed-copy", str(fx.out), str(fixed)
    )
    assert code == KILLED
    target = fx.out / "generations" / "000002" / "files" / "s0_Normal.png"
    target.write_bytes(b"damaged")
    locked = consumed(export_tests, fx.out, fixed)
    assert locked["error"] == "Failure" and "files" not in locked, locked
    assert "is not complete" in locked["message"]
    code, _, err = call(
        export_tests, "recover", "--recover", str(fx.out), "--fixed-names", str(fixed)
    )
    assert code == 1 and "is not complete" in err


def test_recover_rolls_fixed_names_forward(export_tests: Path, tmp_path: Path) -> None:
    """2.2, 2.3: `export --recover --fixed-names` completes an interrupted fixed-name copy."""
    fx, fixed = fixed_fixture(export_tests, tmp_path)
    code, _, _ = call(
        export_tests, "--fault", "kill_before_fixed_rename:1", "fixed-copy", str(fx.out), str(fixed)
    )
    assert code == KILLED
    report = one(export_tests, "recover", "--recover", str(fx.out), "--fixed-names", str(fixed))
    assert report["fixed_names"] == [{"directory": fixed.as_posix(), "rolled_forward": "000002"}]
    again = one(export_tests, "recover", "--recover", str(fx.out), "--fixed-names", str(fixed))
    assert again["fixed_names"] == [{"directory": fixed.as_posix(), "rolled_forward": None}]


def test_fixed_names_into_the_export_path_refuse_reserved_names(
    export_tests: Path, tmp_path: Path
) -> None:
    """2.3: a fixed-name copy into exportPath itself gives Painter's flat layout beside the
    publication; a fixed name equal to one of the publication's own names is refused before
    anything is copied."""
    fx = Fixture(export_tests, tmp_path)
    assert fx.publish("a")[0] == 0
    copied = one(export_tests, "fixed-copy", str(fx.out), str(fx.out))
    assert copied["generation"] == "000001"
    for rel, sha in fx.expected["a"].items():
        assert hashlib.sha256((fx.out / rel).read_bytes()).hexdigest() == sha

    clash = tmp_path / "clash"
    cfg = config(clash)
    cfg["exportPresets"][0]["maps"][1]["fileName"] = "generations/$textureSet_Roughness"
    path = tmp_path / "clash.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    assert "error" not in one(export_tests, "publish", str(TEMPLATES), str(fx.spec_a), str(path))
    refused = one(export_tests, "fixed-copy", str(clash), str(clash))
    assert refused["error"] == "Failure" and "publication's own generations" in refused["message"]
    assert not (clash / "fixed-names.journal.json").exists()


# ── Receipts ─────────────────────────────────────────────────────────────────


def receipt_of(out: Path, generation: str = "000001") -> dict[str, Any]:
    receipt: dict[str, Any] = json.loads(
        (out / "generations" / generation / "receipt.json").read_text(encoding="utf-8")
    )
    return receipt


def validate(receipt: dict[str, Any]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(receipt)


def test_receipt_schema_and_fields(export_tests: Path, tmp_path: Path) -> None:
    """2.4, 3.4: the receipt validates against receipt.schema.json and carries the ARC-11 header
    (revision, profiles, app version, build, the resources read: the fill bitmap and the mesh),
    the plan hash, and per file its path, bytes, SHA-256 of the delivered bytes, format, bit
    depth, colour space, size, preset, layout, channel mapping and normal tag; the Assets3D export
    block (manifest-schema-v2 `$defs/export`) names every output, map format and source."""
    fx = Fixture(export_tests, tmp_path)
    assert fx.publish("b")[0] == 0
    receipt = receipt_of(fx.out)
    validate(receipt)
    spec_doc = json.loads(fx.spec_b.read_text(encoding="utf-8"))
    mesh_sha = hashlib.sha256(Path(spec_doc["mesh"]).read_bytes()).hexdigest()
    assert receipt["revision"] == 1
    assert receipt["app_version"] == "0.0.0-test" and receipt["build"] == "uzp-export-tests"
    assert receipt["compat_profile"] and receipt["evaluator_profile"]
    assert receipt["resource_hashes"] == sorted([spec_doc["resources"][0]["sha256"], mesh_sha])
    assert receipt["generation"] == "000001" and receipt["plan"] == "plan.json"
    files = {f["path"]: f for f in receipt["files"]}
    assert set(files) == set(fx.expected["b"])
    for rel, f in files.items():
        data = (fx.out / "generations" / "000001" / "files" / rel).read_bytes()
        assert f["bytes"] == len(data) and f["sha256"] == hashlib.sha256(data).hexdigest()
        assert f["format"] == "png" and f["bit_depth"] == "16" and f["colour_space"] == "linear"
        assert f["size"] == [256, 256] and f["preset"] == "p" and f["root_path"] == "s0"
        assert f["consumer_gaps"] == []
    assert files["maps/s0_Roughness.png"]["layout"] == "L"
    assert files["maps/s0_Roughness.png"]["channels"] == [
        {
            "dest_channel": "L",
            "src_channel": "L",
            "src_map_type": "documentMap",
            "src_map_name": "roughness",
            # phase3.2_uze-uzmat-preset: each image channel states its transfer.
            "transfer": "linear",
        }
    ]
    assert files["maps/s0_Roughness.png"]["normal"] is None
    normal = files["s0_Normal.png"]["normal"]
    assert normal["role"] == "combined"
    assert normal["relief"]["revision"] == 1 and normal["relief"]["method"] == "Sharp"
    assert len(normal["relief"]["height_hash"]) == 64

    block = receipt["manifest_export"]
    keys = {f["path"]: f["key"] for f in receipt["files"]}
    assert keys == {
        "maps/s0_Roughness.png": "maps-s0_roughness-png",
        "s0_Normal.png": "s0_normal-png",
        "s0_User0.png": "s0_user0-png",
    }
    assert block["sources"] == ["project", "mesh"]
    assert sorted(block["outputs"]) == sorted(keys.values())
    assert block["moment"] == receipt["moment"]
    assert block["preset"] == {"file": "export-plan", "selector": "/files/0/preset"}
    assert block["maps"]["s0_normal-png"] == {
        "resolution": [256, 256],
        "bit_depth": 16,
        "color_space": "linear",
    }
    assert block["comparison"] == {
        "result": "pending",
        "report": None,
        "tolerance": None,
        "differences": [],
    }
    assert block["evidence"] == [{"file": "export-plan"}]
    manifest_files = receipt["manifest_files"]
    assert manifest_files["s0_normal-png"]["path"] == "files/s0_Normal.png"
    assert manifest_files["s0_normal-png"]["sha256"] == {
        "algorithm": "sha256",
        "value": files["s0_Normal.png"]["sha256"],
        "verification": "verified",
    }
    plan_bytes = (fx.out / "generations" / "000001" / "plan.json").read_bytes()
    assert (
        manifest_files["export-plan"]["sha256"]["value"] == hashlib.sha256(plan_bytes).hexdigest()
    )
    assert manifest_files["project"]["path"] == "fixture.uzp"
    assert manifest_files["project"]["revision"] == "1"
    assert manifest_files["mesh"]["path"] == Path(spec_doc["mesh"]).name
    assert manifest_files["mesh"]["sha256"]["value"] == mesh_sha

    broken = json.loads(json.dumps(receipt))
    del broken["files"][0]["normal"]
    with pytest.raises(jsonschema.ValidationError):
        validate(broken)
    broken = json.loads(json.dumps(receipt))
    broken["manifest_export"]["comparison"]["result"] = "bytes-iguais"
    with pytest.raises(jsonschema.ValidationError):
        validate(broken)
    broken = json.loads(json.dumps(receipt))
    broken["files"][0]["path"] = "s0_User0.png.uzp-staging"
    with pytest.raises(jsonschema.ValidationError):
        validate(broken)


def test_receipt_geometry_only_normal_and_skipped_maps(export_tests: Path, tmp_path: Path) -> None:
    """2.4, 3.4: the geometry-only normal (meshMap normal_base) is tagged `geometry_only` without a
    relief round and its mesh map is a resource read; a map the plan does not write is listed in
    `skipped` and in the open items (QG-03)."""
    from tools.parity.feasibility import png

    spec_path = spec(tmp_path / "spec")
    document = json.loads(spec_path.read_text(encoding="utf-8"))
    flat = np.full((256, 256, 3), 32768, np.int64)
    flat[:, :, 2] = 65535
    normal_png = png.encode(flat, 16)
    (tmp_path / "spec" / "normal.png").write_bytes(normal_png)
    normal_sha = hashlib.sha256(normal_png).hexdigest()
    document["resources"].append({"sha256": normal_sha, "png": "normal.png"})
    document["mesh_maps"] = {"Normal": normal_sha}
    spec_path.write_text(json.dumps(document), encoding="utf-8")
    out = tmp_path / "out"
    cfg = config(out)
    cfg["exportPresets"][0]["maps"] = [
        {
            "fileName": "$textureSet_GeoNormal",
            "channels": [chan(c, "meshMap", "normal_base") for c in "RGB"],
        },
        {"fileName": "$textureSet_Opacity", "channels": [chan("L", "documentMap", "opacity")]},
    ]
    cfg["exportParameters"] = cfg["exportParameters"][:1]
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    result = one(export_tests, "publish", str(TEMPLATES), str(spec_path), str(path))
    assert "error" not in result, result
    receipt = receipt_of(out)
    validate(receipt)
    [geo] = receipt["files"]
    assert geo["path"] == "s0_GeoNormal.png"
    assert geo["normal"] == {"role": "geometry_only", "relief": None}
    assert normal_sha in receipt["resource_hashes"]
    assert [s["file_name"] for s in receipt["skipped"]] == ["$textureSet_Opacity"]
    assert receipt["skipped"][0]["kind"] == "absent"
    items = receipt["manifest_export"]["open_items"]
    assert any("$textureSet_Opacity: not written (absent)" in i for i in items)


def test_receipt_consumer_gap_and_empty_export(export_tests: Path, tmp_path: Path) -> None:
    """2.4, 3.4: `BuildReceipt` on a plan (`receipt`, bytes stand-ins): a map of the SpecularWeight
    channel carries its consumer gap, also in the open items; a plan that writes no file has no
    Assets3D export block (it needs an output) and still validates."""
    project = {
        "texture_sets": [
            {
                "name": "s0",
                "stacks": [
                    {"name": "", "channels": {"SpecularWeight": "L16", "BaseColor": "sRGB8"}}
                ],
            }
        ]
    }
    (tmp_path / "project.json").write_text(json.dumps(project), encoding="utf-8")
    cfg = config(tmp_path / "out")
    cfg["exportPresets"][0]["maps"] = [
        {"fileName": "$textureSet_Spec", "channels": [chan("L", "documentMap", "specularweight")]},
    ]
    cfg["exportParameters"] = cfg["exportParameters"][:1]
    (tmp_path / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    receipt = one(
        export_tests, "receipt", str(tmp_path / "project.json"), str(tmp_path / "config.json")
    )
    validate(receipt)
    [spec_file] = receipt["files"]
    assert spec_file["consumer_gaps"][0]["channel"] == "SpecularWeight"
    assert "not applied by the export" in spec_file["consumer_gaps"][0]["gap"]
    assert receipt["manifest_export"]["open_items"] == [
        "s0_Spec.png: " + spec_file["consumer_gaps"][0]["gap"]
    ]

    cfg["exportList"] = [{"rootPath": "s0", "filter": {"outputMaps": []}}]
    (tmp_path / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    empty = one(
        export_tests, "receipt", str(tmp_path / "project.json"), str(tmp_path / "config.json")
    )
    validate(empty)
    assert empty["files"] == [] and empty["manifest_export"] is None


# SHA-256 of the canonical JSON of the Assets3D definitions the receipt schema copies, as Assets3D
# commit b14511b78ae627ceb5be5e69f0740a3804570311 writes them in
# `Pipeline/manifest/manifest-schema-v2.json` (decision 097).
A3D_COMMIT = "b14511b78ae627ceb5be5e69f0740a3804570311"
A3D_SCHEMA = "Pipeline/manifest/manifest-schema-v2.json"
A3D_DEFS = ("export", "map_format", "comparison", "source", "moment", "path", "sha256", "file")
A3D_DEFS_SHA256 = "899949754a3619e9a1eadc00e839c4168cad135c2f38262304210183960e7eac"


def test_receipt_schema_copies_the_pinned_assets3d_export_block() -> None:
    """phase2.1_recipe-dump-manifest-blocks 2.6, 3.5: the manifest export block every receipt
    carries (v2 `$defs/export`, replacing v1's `exportacao`) is validated by definitions equal to
    the pinned Assets3D schema's: their digest is pinned here, on every lane, and recomputed from
    the pinned commit when the Assets3D checkout is beside this repository."""
    from tools.parity.recorder.job import canonical_json

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    copied = {name: schema["$defs"][name] for name in A3D_DEFS}
    assert hashlib.sha256(canonical_json(copied)).hexdigest() == A3D_DEFS_SHA256
    assert schema["properties"]["manifest_export"] == {
        "anyOf": [{"$ref": "#/$defs/export"}, {"type": "null"}]
    }
    # The checkout beside this one, or beside the folder of a git worktree of it.
    for assets3d in (REPO_ROOT.parent / "Assets3D", REPO_ROOT.parent.parent / "Assets3D"):
        shown = subprocess.run(
            ["git", "-C", str(assets3d), "show", f"{A3D_COMMIT}:{A3D_SCHEMA}"],
            capture_output=True,
            check=False,
        )
        if shown.returncode == 0:
            break
    else:
        pytest.skip("the Assets3D checkout with the pinned commit is not beside this repository")
    pinned = json.loads(shown.stdout)
    original = {name: pinned["$defs"][name] for name in A3D_DEFS}
    assert hashlib.sha256(canonical_json(original)).hexdigest() == A3D_DEFS_SHA256


# ── The .uztexture normal derivative (phase3.1_uze-uztexture-writer 2.7, 3.5; decision 316) ──

NORMAL_SIZE = 128
NORMAL_MIPS = 8
NEGATIVE_TEXEL = (5, 3)  # (x, y)
UZ_BC5, UZ_RGBA8 = 3, 0  # uz::TextureFormat


def normal_spec(tmp: Path, negative: bool) -> Path:
    """A texture set s0 of the grid mesh whose Normal (RGB16F) is filled from an authored RGB 16-bit
    bitmap holding (0, 0, 1), with Z = -0.5 at `NEGATIVE_TEXEL` when `negative`."""
    from tools.parity.feasibility import png

    tmp.mkdir(parents=True, exist_ok=True)
    codes = np.empty((NORMAL_SIZE, NORMAL_SIZE, 3), np.int64)
    codes[..., 0:2] = 32768
    codes[..., 2] = 65535
    if negative:
        x, y = NEGATIVE_TEXEL
        codes[y, x, 2] = 16384
    data = png.encode(codes, 16)
    (tmp / "normal.png").write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    document = {
        "name": "s0",
        "resolution": [NORMAL_SIZE, NORMAL_SIZE],
        "channels": [{"type": "Normal", "format": "RGB16F"}],
        "resources": [{"sha256": sha, "png": "normal.png"}],
        "layers": [{"kind": "fill", "sources": {"Normal": {"bitmap": sha, "color_space": "Raw"}}}],
        "mesh": str(GRID),
    }
    (tmp / "spec.json").write_text(json.dumps(document), encoding="utf-8")
    return tmp / "spec.json"


def normal_config(out: Path, tmp: Path, luma_map: bool = False) -> Path:
    """`s0_n`: the Normal channel as an RGB PNG 16 (the canonical companion); with `luma_map`, also
    `s0_l`, its luma as an L file."""
    maps: list[dict[str, Any]] = [
        {"fileName": "$textureSet_n", "channels": [chan(c, "documentMap", "normal") for c in "RGB"]}
    ]
    if luma_map:
        maps.append({"fileName": "$textureSet_l", "channels": [chan("L", "documentMap", "normal")]})
    cfg = {
        "exportShaderParams": False,
        "exportPath": out.as_posix(),
        "defaultExportPreset": "p",
        "exportPresets": [{"name": "p", "maps": maps}],
        "exportList": [{"rootPath": "s0"}],
        "exportParameters": [{"parameters": PNG16}],
    }
    path = tmp / f"normal-config-{int(luma_map)}.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


def publish_normal(
    exe: Path, spec_path: Path, cfg: Path, request: str = "s0_n.png"
) -> dict[str, Any]:
    return one(exe, "publish", str(TEMPLATES), str(spec_path), str(cfg), "--uztexture", request)


def read_uztexture(data: bytes) -> tuple[tuple[int, ...], list[tuple[int, ...]]]:
    """The header (magic, version, width, height, mipCount, format, flags) and the mip
    descriptors (offset, size, width, height) of a `.uztexture`."""
    header = struct.unpack_from("<7I", data, 0)
    mips = [struct.unpack_from("<QQII", data, 64 + 24 * n) for n in range(header[4])]
    return header, mips


def derivative_entry(receipt: dict[str, Any]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = [f for f in receipt["files"] if f["format"] == "uztexture"]
    assert len(entries) == 1, entries
    return entries[0]


def test_uztexture_negative_z_fail_publishes_nothing(export_tests: Path, tmp_path: Path) -> None:
    """2.7, 3.5: under the default policy `fail`, a normal map without negative-Z texels is
    published as BC5 beside its canonical PNG 16, the receipt recording the policy; the authored
    map with one negative-Z texel then fails the export, naming the count and the first texel,
    before anything is published: no generation, and the pointer, the selected receipt and what a
    pinned consumer reads are unchanged."""
    out = tmp_path / "out"
    cfg = normal_config(out, tmp_path)
    clean = publish_normal(export_tests, normal_spec(tmp_path / "clean", False), cfg)
    assert "error" not in clean, clean
    assert [f["relativePath"] for f in clean["files"]] == ["s0_n.png", "s0_n.uztexture"]
    receipt = receipt_of(out)
    validate(receipt)
    entry = derivative_entry(receipt)
    assert entry["path"] == "s0_n.uztexture" and entry["bit_depth"] == "8"
    assert entry["uztexture"] == {
        "source": "s0_n.png",
        "delivery": "s0_n.png",
        "binding": "normal",
        "format": "BC5",
        "srgb": False,
        "mips": NORMAL_MIPS,
        "encoder": "etcpak 2.1",
        "negative_z": {"policy": "fail", "texels": 0, "first": None, "routed": False},
    }
    data = (out / "generations" / "000001" / "files" / "s0_n.uztexture").read_bytes()
    assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    header, _ = read_uztexture(data)
    assert header == (0x5A585455, 1, NORMAL_SIZE, NORMAL_SIZE, NORMAL_MIPS, UZ_BC5, 0)
    plan = json.loads((out / "generations" / "000001" / "plan.json").read_text(encoding="utf-8"))
    assert plan["files"][0]["uztexture"] == {
        "relativePath": "s0_n.uztexture",
        "path": (out / "s0_n.uztexture").as_posix(),
        "binding": "normal",
        # phase3.2_uze-uzmat-preset: the derivative's format, colour space, mips and canonical file.
        "format": "BC5",
        "srgb": False,
        "mips": "normal",
        "canonical": "s0_n.png",
        "negativeZ": "fail",
    }

    pointer = (out / "current.json").read_bytes()
    selected_receipt = (out / "generations" / "000001" / "receipt.json").read_bytes()
    pinned = consumed(export_tests, out)
    refused = publish_normal(
        export_tests, normal_spec(tmp_path / "negative", True), cfg, "s0_n.png:fail"
    )
    assert refused["error"] == "Failure", refused
    x, y = NEGATIVE_TEXEL
    message = refused["message"]
    assert f"normal map 's0_n.png': 1 texel(s) with negative Z (first at {x}, {y})" in message
    assert "the negative-Z policy is fail (decision 316): nothing is published" in message
    assert (out / "current.json").read_bytes() == pointer
    assert sorted(p.name for p in (out / "generations").iterdir()) == ["000001"]
    assert (out / "generations" / "000001" / "receipt.json").read_bytes() == selected_receipt
    assert consumed(export_tests, out) == pinned


def test_uztexture_negative_z_rgb_routes_and_records(export_tests: Path, tmp_path: Path) -> None:
    """2.7, 3.5: under the policy `rgb` the authored map with one negative-Z texel is published
    with its canonical PNG 16 and a derivative stored as RGBA8 whose decoded Z keeps its negative
    sign; the receipt (valid against the schema) records the policy, the count, the first texel,
    the routed format and the consumer gap."""
    from tools.parity.feasibility import png

    out = tmp_path / "out"
    result = publish_normal(
        export_tests,
        normal_spec(tmp_path / "negative", True),
        normal_config(out, tmp_path),
        "s0_n.png:rgb",
    )
    assert "error" not in result, result
    assert [f["relativePath"] for f in result["files"]] == ["s0_n.png", "s0_n.uztexture"]
    receipt = receipt_of(out)
    validate(receipt)
    x, y = NEGATIVE_TEXEL
    entry = derivative_entry(receipt)
    assert entry["uztexture"]["format"] == "RGBA8"
    assert entry["uztexture"]["negative_z"] == {
        "policy": "rgb",
        "texels": 1,
        "first": [x, y],
        "routed": True,
    }
    assert [gap["channel"] for gap in entry["consumer_gaps"]] == ["Normal"]
    assert entry["key"] in receipt["manifest_export"]["outputs"]
    files = out / "generations" / "000001" / "files"
    canonical = png.decode((files / "s0_n.png").read_bytes()).reshape(NORMAL_SIZE, NORMAL_SIZE, 3)
    assert canonical[y, x, 2] < 32768
    assert int((canonical[..., 2] < 32768).sum()) == 1
    data = (files / "s0_n.uztexture").read_bytes()
    assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    header, mips = read_uztexture(data)
    assert header == (0x5A585455, 1, NORMAL_SIZE, NORMAL_SIZE, NORMAL_MIPS, UZ_RGBA8, 0)
    offset, size, width, height = mips[0]
    assert (size, width, height) == (NORMAL_SIZE * NORMAL_SIZE * 4, NORMAL_SIZE, NORMAL_SIZE)
    level0 = np.frombuffer(data, np.uint8, size, offset).reshape(NORMAL_SIZE, NORMAL_SIZE, 4)
    z = level0[..., 2].astype(np.float64) / 255 * 2 - 1
    assert z[y, x] < 0
    assert int((z < 0).sum()) == 1


def test_uztexture_request_refusals(export_tests: Path, tmp_path: Path) -> None:
    """Decision 316: an unknown policy and an unknown file are ValueErrors, and a file outside the
    bound is NotYetSupported naming phase3.4_uzengine-preset; all before anything is written."""
    out = tmp_path / "out"
    spec_path = normal_spec(tmp_path / "spec", True)
    cfg = normal_config(out, tmp_path, luma_map=True)
    bogus = publish_normal(export_tests, spec_path, cfg, "s0_n.png:bogus")
    assert bogus == {
        "error": "ValueError",
        "message": 'export: the negative-Z policy "bogus": expected fail or rgb',
    }
    missing = publish_normal(export_tests, spec_path, cfg, "s0_x.png")
    assert missing["error"] == "ValueError", missing
    assert 'the .uztexture normal derivative of "s0_x.png"' in missing["message"]
    luma = publish_normal(export_tests, spec_path, cfg, "s0_l.png:rgb")
    assert luma["error"] == "NotYetSupported", luma
    assert "decision 316" in luma["message"] and "phase3.4_uzengine-preset" in luma["message"]
    assert not out.exists()
