"""Tests of phase3.1_proc-backend-seam item 2.4 (`src/procedural/asset_library.h`, decision 324):
the asset library's exact pins, its provenance records, the internal alias table and the
`resource.search` query terms, and the checks that refuse a library at load.

Every case runs `uzp-procedural-tests.exe` on the CPU. The fixture library
(`tests/procedural/fixtures/library/`) holds synthetic test probes with authored names, never a
Painter asset; the shipped library (`assets/procedural/`) holds no asset yet.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests/procedural/fixtures/library"
SHIPPED = REPO_ROOT / "assets/procedural"
RIDGE2 = "records/test-generator.ridge@2.json"
SOFTEN = "records/test-filter.soften@1.json"


def run(exe: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(exe), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )


def test_pins_aliases_and_search(procedural_tests: Path, tmp_path: Path) -> None:
    """2.4: exact pins, aliases only to certified assets, the query terms, the project's pins."""
    proc = run(procedural_tests, "library", str(tmp_path), str(FIXTURE), str(SHIPPED))
    failed = [line for line in proc.stdout.splitlines() if line.startswith("FAIL ")]
    assert proc.returncode == 0 and not failed, proc.stdout + proc.stderr
    passed = {line[5:] for line in proc.stdout.splitlines() if line.startswith("PASS ")}
    assert len(passed) == 28, sorted(passed)
    for check in (
        "the shipped library loads and holds no asset and no alias (no family is certified yet)",
        "a pin of a version the library does not hold is refused, naming the versions it holds",
        "a Painter name resolves through the alias table to the UzPainter asset, with its "
        "UzPainter name",
        "a Painter name with no alias raises UnsupportedProcedural (no certified family), no "
        "similar asset",
        "the same Painter name under another usage is refused, not answered with the generator",
        "every pin of the project resolves at its exact version",
    ):
        assert check in passed


def edit_json(root: Path, name: str, change: Callable[[Any], None]) -> None:
    path = root / name
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document)
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")


def alias_to(asset: str, usage: str = "GENERATOR") -> Callable[[Any], None]:
    def change(document: Any) -> None:
        document["aliases"].append(
            {"shelf": "starterassets", "usage": usage, "painter_name": "Other", "asset": asset}
        )

    return change


def set_field(key: str, value: Any) -> Callable[[Any], None]:
    def change(document: Any) -> None:
        document[key] = value

    return change


def drop_report(document: Any) -> None:
    del document["parity"]["report"]


def drop_default(document: Any) -> None:
    del document["defaults"]["bias"]


def adobe_source(document: Any) -> None:
    document["sources"].append({"kind": "adobe-capture", "citation": "a recorded Painter output"})


def repeat_record(document: Any) -> None:
    document["records"].append(RIDGE2)


def escape_record(document: Any) -> None:
    document["records"].append("../outside.json")


def alias_shelf(document: Any) -> None:
    document["aliases"][0]["shelf"] = "uzpainter"


# (case id, file, change, expected text of the refusal)
REFUSALS: list[tuple[str, str, Callable[[Any], None], str]] = [
    (
        "alias-to-calibrated",
        "aliases.json",
        alias_to("uzasset://test-filter/soften@1", "FILTER"),
        "whose parity status is calibrated: only a certified (exact) asset may answer",
    ),
    (
        "alias-to-unavailable",
        "aliases.json",
        alias_to("uzasset://test-generator/ridge@1"),
        "whose parity status is unavailable",
    ),
    (
        "alias-to-missing",
        "aliases.json",
        alias_to("uzasset://test-generator/ridge@3"),
        "which the library does not hold",
    ),
    (
        "alias-usage",
        "aliases.json",
        alias_to("uzasset://test-generator/ridge@2", "FILTER"),
        "is a FILTER, uzasset://test-generator/ridge@2 a GENERATOR",
    ),
    ("alias-own-shelf", "aliases.json", alias_shelf, "names a Painter shelf, not uzpainter"),
    (
        "painter-name",
        RIDGE2,
        set_field("name", "synthetic edge probe"),
        "is a Painter asset name (an alias)",
    ),
    ("source-kind", RIDGE2, adobe_source, "is not paper, book, standard or approved-source"),
    ("license", RIDGE2, set_field("license", "Proprietary"), "license is not Apache-2.0"),
    ("sbsar-member", RIDGE2, set_field("sbsar", "ridge.sbsar"), "has an unknown member sbsar"),
    ("no-report", RIDGE2, drop_report, "names the report that gives it"),
    ("no-default", RIDGE2, drop_default, "parameter bias has no default"),
    ("usage", SOFTEN, set_field("usage", "TEXTURE"), "is not a procedural resource.Usage member"),
    ("repeated-record", "library.json", repeat_record, "is pinned by two records"),
    ("record-outside", "library.json", escape_record, "is not inside the library"),
]


def test_the_unchanged_fixture_loads(procedural_tests: Path) -> None:
    proc = run(procedural_tests, "library-load", ".", str(FIXTURE))
    assert proc.returncode == 0 and proc.stdout.strip() == "LOADED 3 1", proc.stdout + proc.stderr


@pytest.mark.parametrize(
    ("name", "change", "expected"),
    [pytest.param(name, change, expected, id=case) for case, name, change, expected in REFUSALS],
)
def test_a_library_that_breaks_a_rule_is_refused(
    procedural_tests: Path,
    tmp_path: Path,
    name: str,
    change: Callable[[Any], None],
    expected: str,
) -> None:
    """2.4: clean room (sources, licence, UzPainter names, no extra member) and the alias rule."""
    root = tmp_path / "library"
    shutil.copytree(FIXTURE, root)
    edit_json(root, name, change)
    proc = run(procedural_tests, "library-load", str(tmp_path), str(root))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert proc.stdout.startswith("REFUSED ") and expected in proc.stdout, proc.stdout


def test_assets_list_and_parity(procedural_tests: Path, tmp_path: Path) -> None:
    """2.5: `UzPainter.exe assets list [--parity]` (RunAssetsCommand) lists the library's assets,
    with each one's parity status and certified domain, and no Painter name."""
    proc = run(procedural_tests, "assets-cli", str(tmp_path), str(FIXTURE), str(SHIPPED))
    failed = [line for line in proc.stdout.splitlines() if line.startswith("FAIL ")]
    assert proc.returncode == 0 and not failed, proc.stdout + proc.stderr
    passed = {line[5:] for line in proc.stdout.splitlines() if line.startswith("PASS ")}
    assert len(passed) == 9, sorted(passed)
    assert "assets list shows no Painter name of the internal alias table" in passed
    assert "the shipped library lists no asset" in passed
