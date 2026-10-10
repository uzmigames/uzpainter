"""Published outputs of the procedural feasibility study (2.7, 2.8, 3.1, 3.2, 4.1).

Hosted tests check the committed semantics file and report against each other and the guard
rules. The local test (owner's machine, store present) re-runs the comparison against the
private oracles with the published fits and requires the same numbers.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from tools.parity.feasibility.cases import ASSETS, cases
from tools.parity.feasibility.report import REPORT_PATH, SEMANTICS_PATH
from tools.parity.guard.guard import PATH_RULES
from tools.parity.schemas import REPO_ROOT, Schema, load_json, validation_errors
from tools.parity.store.store import locate

ROW = re.compile(r"^\| (?P<asset>[^|]+) \| (?P<fixture>[^|]+) \| (?P<set>[a-z0-9-]+) \(.*?\) \| ")


def semantics() -> dict:  # type: ignore[type-arg]
    document: dict = load_json(SEMANTICS_PATH)  # type: ignore[type-arg]
    return document


def test_semantics_file_is_valid_public_and_cites_sources() -> None:
    document = semantics()
    assert validation_errors(document, Schema.SEMANTICS) == []
    assert document["corpus"] == [case.golden_id for case in cases()]
    for entry in document["entries"]:
        assert entry["public_sources"], entry["entry_id"]
        assert all(s["source_id"] != "A-OBSERVE" for s in entry["public_sources"])
        assert entry["residuals"], entry["entry_id"]
        zero = all(r["difference"]["max"] == 0 for r in entry["residuals"])
        assert (entry["status"] == "exact") == zero


def test_every_case_and_map_has_residuals_against_both_recordings() -> None:
    residuals = {
        (r["golden_id"], r["map"], r["compared_against"])
        for entry in semantics()["entries"]
        for r in entry["residuals"]
    }
    for case in cases():
        maps = {m for g, m, _ in residuals if g == case.golden_id}
        assert maps, case.golden_id
        for name in maps:
            assert {(case.golden_id, name, "r1"), (case.golden_id, name, "r2")} <= residuals


def test_report_numbers_match_the_semantics_file() -> None:
    by_key = {
        (r["golden_id"], r["map"], r["compared_against"]): r["difference"]
        for entry in semantics()["entries"]
        for r in entry["residuals"]
    }
    names = {asset.painter_name: asset.asset_id for asset in ASSETS.values()}
    rows = 0
    for line in REPORT_PATH.read_text(encoding="utf-8").splitlines():
        match = ROW.match(line)
        if not match:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        golden = (
            f"phase0/procedural-feasibility/{names[match['asset']]}/{match['fixture']}/"
            f"{match['set']}"
        )
        map_name = cells[3]
        for offset, recording in ((4, "r1"), (9, "r2")):
            diff = by_key[(golden, map_name, recording)]
            affected, texels = (int(v) for v in cells[offset + 4].split(" / "))
            assert int(cells[offset]) == diff["max"]
            assert float(cells[offset + 1]) == pytest.approx(diff["mean"], abs=0.005)
            assert int(cells[offset + 2]) == diff["p99"]
            assert int(cells[offset + 3]) == diff["differing"]
            assert (affected, texels) == (diff["affected_texels"], diff["texels"])
        classification = cells[-1]
        zero = all(by_key[(golden, map_name, r)]["max"] == 0 for r in ("r1", "r2"))
        if not zero:
            assert classification != "equal"
        rows += 1
    assert rows == len(by_key) // 2


def test_report_states_a_verdict_per_evaluated_asset() -> None:
    text = REPORT_PATH.read_text(encoding="utf-8")
    for asset in ASSETS.values():
        assert re.search(rf"\| {re.escape(asset.painter_name)} \|.*\*\*(go|no-go)\*\* \|", text)


def test_guard_assigns_the_semantics_schema() -> None:
    rule = next(r for r in PATH_RULES if r[0].match("parity/semantics/procedural-feasibility.json"))
    assert rule[1] == "semantics.json"


def test_guard_rejects_a_readback_dressed_as_semantics() -> None:
    document = semantics()
    document["entries"][0]["parameters"].append(
        {"name": "readback", "value": {"substance_properties": {}}, "origin": "fitted"}
    )
    assert validation_errors(document, Schema.SEMANTICS)
    document = semantics()
    document["record_class"] = "private_oracle_record"
    assert validation_errors(document, Schema.SEMANTICS)


@pytest.mark.skipif(locate() is None, reason="no private oracle store on this machine")
def test_local_comparison_reproduces_the_published_numbers() -> None:
    """Task 3.1 on the owner's machine: every prototype against both recordings."""
    result = subprocess.run(
        [sys.executable, "-m", "tools.parity.feasibility", "check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(locate() is None, reason="no private oracle store on this machine")
def test_local_guard_finds_no_oracle_output_or_readback() -> None:
    """Task 3.2: no recorded map, readback or preset structure is in the repository."""
    paths = [
        "parity/manifests/phase0/procedural-feasibility",
        "parity/fixtures/feasibility",
        "parity/semantics",
        "parity/reports",
        "tools/parity/feasibility",
        "tests/parity/feasibility",
    ]
    result = subprocess.run(
        [sys.executable, "-m", "tools.parity.guard", *paths],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "store-hash rule against store" in result.stdout
    assert Path(REPO_ROOT / "parity" / "semantics").is_dir()
