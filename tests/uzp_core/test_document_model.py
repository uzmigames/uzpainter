"""Document model and canonical manifest (phase1.1_docmodel-types-manifest, items 3.1-3.6).

`uzp-core-tests.exe` (`tests/uzp_core/uzp_core_test.cpp`, `zig build uzp-core-tests`) holds the
native cases and prints manifests; these tests run it, compare its canonical bytes with Python's
`canonical_json` (`tools/parity/recorder/job.py`) and validate its manifests against
`src/uzp_core/schema/manifest.schema.json`. No GPU is involved: everything runs on the hosted CPU
lane.
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
SCHEMA_PATH = REPO_ROOT / "src" / "uzp_core" / "schema" / "manifest.schema.json"
FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "every-kind.manifest.json"
# SHA-256 of the canonical form of FIXTURE_PATH: pinned so a change to the canonical writer, or to
# what the fixture holds, is a visible, reviewed change.
FIXTURE_DIGEST = "dc572509c528d6e520230df4d226099fd7711267cd9f53480594d954b21f1db3"

NATIVE_CASES = (
    "sha256_vectors",
    "json_canonical_form",
    "fixture_round_trip",
    "digest_independent_of_insertion_order",
    "ids_persist",
    "insertion_rules",
    "anchor_cycles",
    "model_constraints",
    "manifest_reader",
    "resource_urls",
    "result_header",
)


@pytest.fixture(scope="session")
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


def rejection(exe: Path, manifest_text: str, tmp_path: Path) -> str:
    """The error class the native loader reports for `manifest_text` (it must reject it)."""
    path = tmp_path / "manifest.json"
    path.write_text(manifest_text, encoding="utf-8")
    proc = run(exe, "canonical", str(path))
    assert proc.returncode == 3, proc.stdout
    return proc.stderr.decode("utf-8").split(":", 1)[0]


def strict_load(text: str) -> Any:
    """`json.loads` that rejects duplicate keys, as the native parser does."""

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        keys = [key for key, _ in items]
        if len(keys) != len(set(keys)):
            raise ValueError(f"duplicate key among {sorted(keys)}")
        return dict(items)

    return json.loads(text, object_pairs_hook=pairs)


@pytest.fixture(scope="session")
def validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@pytest.fixture(scope="session")
def fixture_manifest(core_tests: Path) -> dict[str, Any]:
    manifest: dict[str, Any] = json.loads(output(core_tests, "fixture"))
    return manifest


def roots(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    layers: list[dict[str, Any]] = manifest["texture_sets"][0]["stacks"][0]["root_layers"]
    return layers


def layer_named(manifest: dict[str, Any], name: str) -> dict[str, Any]:
    return next(layer for layer in roots(manifest) if layer["name"] == name)


# ── Native cases (3.1-3.6 on the C++ side) ─────────────────────────────────────────────────


@pytest.mark.parametrize("case", NATIVE_CASES)
def test_native_case(core_tests: Path, case: str) -> None:
    proc = run(core_tests, "run", case)
    assert proc.returncode == 0, proc.stdout.decode() + proc.stderr.decode()
    assert f"PASS {case}".encode() in proc.stdout


def test_native_case_list_is_complete(core_tests: Path) -> None:
    proc = run(core_tests, "run")
    assert proc.returncode == 0, proc.stdout.decode()
    ran = [line.split()[1] for line in proc.stdout.decode().splitlines() if line.startswith("PASS")]
    assert tuple(ran) == NATIVE_CASES


# ── 3.1 Round trip of fixture documents ────────────────────────────────────────────────────


def test_fixture_covers_every_kind(fixture_manifest: dict[str, Any]) -> None:
    layer_kinds: set[str] = set()
    content_kinds: set[str] = set()
    mask_kinds: set[str] = set()
    source_types: set[str] = set()

    def visit(layer: dict[str, Any]) -> None:
        layer_kinds.add(layer["kind"])
        if "fill" in layer:
            source_types.update(s["type"] for s in layer["fill"]["sources"].values())
        content_kinds.update(e["kind"] for e in layer["content_effects"])
        if layer["mask"] is not None:
            mask_kinds.update(e["kind"] for e in layer["mask"]["effects"])
        for child in layer.get("children", []):
            visit(child)

    for layer in roots(fixture_manifest):
        visit(layer)
    assert layer_kinds == {"fill", "paint", "group", "instance"}
    assert content_kinds | mask_kinds == {
        "fill",
        "paint",
        "generator",
        "filter",
        "levels",
        "compare_mask",
        "color_selection",
        "anchor",
    }
    assert source_types == {"uniform_color", "bitmap", "vector", "font", "procedural", "reference"}
    mesh_maps = fixture_manifest["texture_sets"][0]["mesh_maps"].values()
    provenances = {binding["provenance"]["kind"] for binding in mesh_maps}
    assert provenances == {"imported", "baked"}


def test_committed_fixture_matches_the_model(
    core_tests: Path, fixture_manifest: dict[str, Any]
) -> None:
    committed = strict_load(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert committed == fixture_manifest


def test_fixture_round_trip(
    core_tests: Path, fixture_manifest: dict[str, Any], tmp_path: Path
) -> None:
    text = output(core_tests, "fixture")
    path = tmp_path / "fixture.json"
    path.write_bytes(text)
    assert output(core_tests, "canonical", str(path)) == text
    reloaded = tmp_path / "reloaded.json"
    reloaded.write_bytes(output(core_tests, "canonical", str(path)))
    assert output(core_tests, "digest", str(reloaded)) == output(core_tests, "digest", str(path))
    # The committed, indented fixture loads to the same canonical bytes.
    assert output(core_tests, "canonical", str(FIXTURE_PATH)) == text


# ── 3.2 Digest independent of in-memory order, identical across processes ──────────────────


def test_digest_independent_of_insertion_order(core_tests: Path) -> None:
    assert output(core_tests, "fixture") == output(core_tests, "fixture", "reversed")


def test_digest_identical_across_processes_and_languages(core_tests: Path) -> None:
    first = output(core_tests, "digest", str(FIXTURE_PATH)).decode()
    second = output(core_tests, "digest", str(FIXTURE_PATH)).decode()
    assert first == second
    python = hashlib.sha256(canonical_json(json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))))
    assert first == python.hexdigest()
    assert first == FIXTURE_DIGEST


def test_canonical_json_matches_python(core_tests: Path, tmp_path: Path) -> None:
    value = {
        "z": [1.0, 0.1, -0.0, 123.456, 1e15, 1e16, 0.0001, 0.00001, 1.5e300, 5e-324, 2.5e-7],
        "a": 'é\n\t\u0001\u007f\u2028😀"\\/',
        "m": {"b": None, "B": True, "é": False, "a": -9223372036854775807},
        "i": [0, -1, 9223372036854775807],
    }
    path = tmp_path / "value.json"
    path.write_text(json.dumps(value, indent=3, ensure_ascii=True), encoding="utf-8")
    assert output(core_tests, "json", str(path)) == canonical_json(value)


# ── 3.3 Schema ─────────────────────────────────────────────────────────────────────────────


def test_serialised_manifests_validate(
    validator: Draft202012Validator, fixture_manifest: dict[str, Any]
) -> None:
    errors = [error.message for error in validator.iter_errors(fixture_manifest)]
    assert errors == []
    assert validator.is_valid(strict_load(FIXTURE_PATH.read_text(encoding="utf-8")))


def test_two_channels_of_one_type_rejected(
    core_tests: Path,
    validator: Draft202012Validator,
    fixture_manifest: dict[str, Any],
    tmp_path: Path,
) -> None:
    text = json.dumps(fixture_manifest)
    marker = '"channels": {'
    assert marker in text
    doubled = text.replace(marker, marker + '"BaseColor": {"format": "L8", "label": ""}, ', 1)
    with pytest.raises(ValueError, match="duplicate key"):
        strict_load(doubled)
    assert rejection(core_tests, doubled, tmp_path) == "ParseError"
    # The channel type is the key: a channel entry cannot name a second type.
    renamed = copy.deepcopy(fixture_manifest)
    channels = renamed["texture_sets"][0]["stacks"][0]["channels"]
    channels["BaseColour"] = channels["BaseColor"]
    assert not validator.is_valid(renamed)
    assert rejection(core_tests, json.dumps(renamed), tmp_path) == "ManifestError"


@pytest.mark.parametrize("width", [3000, 64, 16384])
def test_resolution_out_of_range_rejected(
    core_tests: Path,
    validator: Draft202012Validator,
    fixture_manifest: dict[str, Any],
    tmp_path: Path,
    width: int,
) -> None:
    manifest = copy.deepcopy(fixture_manifest)
    manifest["texture_sets"][0]["resolution"] = {"width": width, "height": width}
    assert not validator.is_valid(manifest)
    assert rejection(core_tests, json.dumps(manifest), tmp_path) == "ValueError"


def test_unknown_channel_format_rejected(
    core_tests: Path,
    validator: Draft202012Validator,
    fixture_manifest: dict[str, Any],
    tmp_path: Path,
) -> None:
    manifest = copy.deepcopy(fixture_manifest)
    manifest["texture_sets"][0]["stacks"][0]["channels"]["Roughness"]["format"] = "L12"
    assert not validator.is_valid(manifest)
    assert rejection(core_tests, json.dumps(manifest), tmp_path) == "ManifestError"


def test_mask_only_effect_in_content_stack_rejected(
    core_tests: Path,
    validator: Draft202012Validator,
    fixture_manifest: dict[str, Any],
    tmp_path: Path,
) -> None:
    manifest = copy.deepcopy(fixture_manifest)
    base = layer_named(manifest, "Base")
    compare = next(e for e in base["mask"]["effects"] if e["kind"] == "compare_mask")
    moved = dict(compare, uid=97, blending={}, active_channels=[])
    base["content_effects"].append(moved)
    assert not validator.is_valid(manifest)
    assert rejection(core_tests, json.dumps(manifest), tmp_path) == "ValueError"


def test_anchor_cycle_rejected(
    core_tests: Path, fixture_manifest: dict[str, Any], tmp_path: Path
) -> None:
    manifest = copy.deepcopy(fixture_manifest)
    base = layer_named(manifest, "Base")
    anchor_uid = next(e["uid"] for e in base["content_effects"] if e["kind"] == "anchor")
    base["fill"]["sources"]["BaseColor"] = {
        "type": "reference",
        "anchor": anchor_uid,
        "channel_mapping": {},
        "referenced_channel": None,
        "alpha_matte": False,
        "levels": None,
    }
    path = tmp_path / "cycle.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    proc = run(core_tests, "canonical", str(path))
    assert proc.returncode == 3
    assert proc.stderr.decode().startswith("ValueError: anchor reference cycle")


# ── 3.4 Unknown keys survive a load/save cycle verbatim ────────────────────────────────────


def test_unknown_keys_preserved(
    core_tests: Path,
    validator: Draft202012Validator,
    fixture_manifest: dict[str, Any],
    tmp_path: Path,
) -> None:
    manifest = copy.deepcopy(fixture_manifest)
    manifest["x_future"] = {"nested": [1, 2.5, "three", None, {"k": True}]}
    manifest["settings"]["x_setting"] = "kept"
    base = layer_named(manifest, "Base")
    base["x_layer"] = [3, 2, 1]
    base["content_effects"][0]["x_effect"] = {"z": 1, "a": 2}
    base["mask"]["effects"][0]["fill"]["source"]["x_source"] = 0.125
    manifest["texture_sets"][0]["mesh_maps"]["AO"]["provenance"]["x_provenance"] = "baked-v2"
    next(iter(manifest["resources"].values()))[0]["x_meta"] = {"origin_tool": "future"}
    assert validator.is_valid(manifest)
    path = tmp_path / "extended.json"
    path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    saved = output(core_tests, "canonical", str(path))
    assert saved == canonical_json(manifest)
    assert validator.is_valid(json.loads(saved))


# ── 3.6 Ids persist; same-named nodes keep distinct ids ────────────────────────────────────


def test_same_named_layers_keep_distinct_ids(core_tests: Path, tmp_path: Path) -> None:
    path = tmp_path / "fixture.json"
    path.write_bytes(output(core_tests, "fixture"))
    reloaded = json.loads(output(core_tests, "canonical", str(path)))
    piping = [layer["uid"] for layer in roots(reloaded) if layer["name"] == "M_piping"]
    assert len(piping) == 2
    assert piping[0] != piping[1]
    original = json.loads(path.read_bytes())
    assert piping == [layer["uid"] for layer in roots(original) if layer["name"] == "M_piping"]
