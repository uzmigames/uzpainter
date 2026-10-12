"""The recipe dump of the document model (phase2.1_recipe-dump-manifest-blocks items 2.1, 2.5,
3.1, 3.2; decision 122).

`uzp-core-tests.exe` (`tests/uzp_core/uzp_core_test.cpp`) holds the native cases (fields, digest
invariance under inert and identity edits, the rebuild and its refusals) and prints the dump of a
manifest with its test host (`recipe <manifest>`) and the manifest of the project a dump rebuilds
(`rebuild <dump>`). These tests validate dumps against `src/uzp_core/schema/recipe.schema.json`,
recompute the digest with Python's canonical JSON and rebuild through the command line. No GPU.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from tools.parity.recorder.job import canonical_json

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "src" / "uzp_core" / "schema" / "recipe.schema.json"
FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "every-kind.manifest.json"

NATIVE_CASES = ("recipe_dump_fields", "recipe_digest_invariance", "recipe_rebuild")


@pytest.fixture(scope="module")
def core_tests(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """`uzp-core-tests.exe` of a fresh `zig build uzp-core-tests`."""
    zig = shutil.which("zig")
    if zig is None:
        pytest.skip("zig is not on PATH; uzp-core-tests.exe cannot be built")
    prefix = tmp_path_factory.mktemp("uzp-core-tests")
    build = subprocess.run(
        [zig, "build", "uzp-core-tests", "--prefix", str(prefix)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    return prefix / "bin" / "uzp-core-tests.exe"


def run(exe: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([str(exe), *args], capture_output=True, timeout=120, check=False)


def output(exe: Path, *args: str) -> bytes:
    proc = run(exe, *args)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@pytest.fixture(scope="module")
def dump(core_tests: Path) -> dict[str, Any]:
    value: dict[str, Any] = json.loads(output(core_tests, "recipe", str(FIXTURE_PATH)))
    return value


def walk(value: Any) -> list[dict[str, Any]]:
    """Every object inside `value`."""
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        found.append(value)
        for member in value.values():
            found += walk(member)
    elif isinstance(value, list):
        for member in value:
            found += walk(member)
    return found


@pytest.mark.parametrize("case", NATIVE_CASES)
def test_native_case(core_tests: Path, case: str) -> None:
    proc = run(core_tests, "run", case)
    assert proc.returncode == 0, proc.stdout.decode() + proc.stderr.decode()
    assert f"PASS {case}".encode() in proc.stdout


def test_dump_validates_and_covers_every_kind(
    validator: Draft202012Validator, dump: dict[str, Any]
) -> None:
    """3.1: the dump of the fixture holding every node, effect and source kind (and both mesh-map
    provenances) validates; the schema refuses an id, an unknown key and a uid reference."""
    assert [e.message for e in validator.iter_errors(dump)] == []
    objects = walk(dump["recipe"])
    kinds = {o["kind"] for o in objects if "kind" in o and "visible" in o}
    assert kinds == {
        "fill",
        "paint",
        "group",
        "instance",
        "generator",
        "filter",
        "levels",
        "compare_mask",
        "color_selection",
        "anchor",
    }
    sources = {
        o["type"]
        for o in objects
        if o.get("type") in {"uniform_color", "bitmap", "vector", "font", "procedural", "reference"}
    }
    assert sources == {"uniform_color", "bitmap", "vector", "font", "procedural", "reference"}
    provenances = {
        o["kind"] for o in objects if "declared_convention" in o or o.get("kind") == "baked"
    }
    assert provenances == {"imported", "baked"}

    for path, value in (
        (("recipe", "texture_sets", 0, "id"), 1),
        (("recipe", "future_key"), True),
        (("recipe", "texture_sets", 0, "stacks", 0, "root_layers", 0, "instance_source"), 14),
    ):
        broken = copy.deepcopy(dump)
        target: Any = broken
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        assert not validator.is_valid(broken), path


def test_digest_is_python_canonical_json(core_tests: Path, dump: dict[str, Any]) -> None:
    """3.2: the digest is the SHA-256 of the body's canonical JSON in either language, the same in
    two processes; the header and the rebuild block are outside it."""
    assert dump["digest"] == hashlib.sha256(canonical_json(dump["recipe"])).hexdigest()
    again: dict[str, Any] = json.loads(output(core_tests, "recipe", str(FIXTURE_PATH)))
    assert again == dump
    assert set(dump) == {
        "schema",
        "revision",
        "evaluator_profile",
        "compat_profile",
        "app_version",
        "resource_hashes",
        "recipe",
        "rebuild",
        "digest",
    }
    assert dump["resource_hashes"] == sorted(dump["recipe"]["resources"])
    text = json.dumps(dump["recipe"])
    for key in ('"uid"', '"next_id"', '"collapsed"', '"display"', '"metadata"', '"import_cameras"'):
        assert key not in text


def test_rebuild_round_trip_through_the_command_line(
    core_tests: Path, dump: dict[str, Any], tmp_path: Path
) -> None:
    """2.5: a dump without paint content rebuilds to a manifest whose dump has the same body, digest
    and rebuild block; paint content and a tampered body are refused with their error classes."""
    paintless = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    stack = paintless["texture_sets"][0]["stacks"][0]
    stack["root_layers"] = [layer for layer in stack["root_layers"] if layer["kind"] != "paint"]
    base = stack["root_layers"][-1]
    base["content_effects"] = [e for e in base["content_effects"] if e["kind"] != "paint"]
    base["mask"]["effects"] = [e for e in base["mask"]["effects"] if e["kind"] != "paint"]
    (tmp_path / "paintless.json").write_text(json.dumps(paintless), encoding="utf-8")
    original = json.loads(output(core_tests, "recipe", str(tmp_path / "paintless.json")))
    (tmp_path / "dump.json").write_text(json.dumps(original), encoding="utf-8")
    (tmp_path / "rebuilt.json").write_bytes(
        output(core_tests, "rebuild", str(tmp_path / "dump.json"))
    )
    rebuilt = json.loads(output(core_tests, "recipe", str(tmp_path / "rebuilt.json")))
    assert rebuilt["digest"] == original["digest"]
    assert rebuilt["recipe"] == original["recipe"] and rebuilt["rebuild"] == original["rebuild"]

    (tmp_path / "painted.json").write_text(json.dumps(dump), encoding="utf-8")
    proc = run(core_tests, "rebuild", str(tmp_path / "painted.json"))
    assert proc.returncode == 3 and proc.stderr.startswith(b"NotYetSupported:")
    tampered = copy.deepcopy(original)
    tampered["recipe"]["texture_sets"][0]["name"] = "M_other"
    (tmp_path / "tampered.json").write_text(json.dumps(tampered), encoding="utf-8")
    proc = run(core_tests, "rebuild", str(tmp_path / "tampered.json"))
    assert (
        proc.returncode == 3
        and proc.stderr.startswith(b"ManifestError:")
        and b"digest" in proc.stderr
    )
