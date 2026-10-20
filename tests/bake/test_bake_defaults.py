"""The authored baking table `assets/defaults/baking.json` and its local check against the
private baking-defaults capture (phase3.1_baker-request-model items 2.8, 2.9 and 3.2; decisions
028 and 323).

The drift tests build their record from the table itself (UzmiGames data, no Painter output), so
they run everywhere. The private comparison runs on the owner's machine only, where the store
holds the cited record (decision 028).
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from tools.bake import bake_defaults as bd
from tools.parity.store.store import locate


def synthetic_record(table: dict[str, Any]) -> dict[str, Any]:
    """A record whose observations equal the table: three equal recordings."""
    outputs = []
    for output_id, entries in bd.groups(table):
        properties = {}
        for entry in entries:
            enum_values = entry.get("enum_values", {})
            meta: dict[str, Any] = {"defaultValue": entry["default"]}
            for bound, value in entry.get("range", {}).items():
                key = bound + "Pow2" if entry["type"] == "IntPair" else bound
                meta[key] = value
            observed = entry["default"]
            if observed is None:
                observed = [1, 1] if entry["type"] == "IntPair" else [0.0, 1.0]
            properties[entry["short_name"]] = {
                "short_name": entry["short_name"],
                "name": entry["name"],
                "label": entry["label"],
                "widget_type": entry["widget_type"],
                "value": observed,
                "enum_values": enum_values,
                "enum_value": enum_values,
                "properties": meta,
            }
        value = {"keys": [e["short_name"] for e in entries], "properties": properties}
        outputs.append({"output_id": output_id, "values": {"texture_sets": {"plane": value}}})
    for name, output_id in bd.STATE_OUTPUTS.items():
        default = table["texture_set_state"][name]["default"]
        outputs.append({"output_id": output_id, "values": {"texture_sets": {"plane": default}}})
    recordings = [{"recording_id": f"r{i}", "outputs": copy.deepcopy(outputs)} for i in (1, 2, 3)]
    return {"golden_id": bd.GOLDEN_ID, "recordings": recordings}


def observed(
    record: dict[str, Any], output_id: str, key: str, recording: int = 0
) -> dict[str, Any]:
    for output in record["recordings"][recording]["outputs"]:
        if output["output_id"] == output_id:
            value: dict[str, Any] = output["values"]["texture_sets"]["plane"]["properties"][key]
            return value
    raise KeyError(output_id)


def test_every_entry_cites_the_observation_and_carries_no_prose() -> None:
    table = bd.load_table()
    sha = table["observation"]["record_sha256"]
    assert bd.cited_hashes(table) == {sha}
    assert table["observation"]["golden_id"] == bd.GOLDEN_ID
    for output_id, entries in bd.groups(table):
        names = [entry["short_name"] for entry in entries]
        assert names == sorted(names), output_id
        for entry in entries:
            assert set(entry) <= bd.ENTRY_FIELDS, entry["short_name"]
            assert entry["provenance"] == {"record_sha256": sha, "output_id": output_id}
            assert (entry["default"] is None) == ("default_note" in entry), entry["short_name"]


def test_a_table_equal_to_its_record_passes() -> None:
    table = bd.load_table()
    sha = table["observation"]["record_sha256"]
    assert bd.check(table, synthetic_record(table), sha) == []


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda r: observed(r, "baking/baker/AO", "NbSecondary").update(value=32), "default"),
        (lambda r: observed(r, "baking/common", "CageMode").update(label="Cage"), "label"),
        (lambda r: observed(r, "baking/common", "MaxHeight").update(value=1), "type"),
        (
            lambda r: observed(r, "baking/common", "FilterMethod")["enum_values"].update(Never=2),
            "enum_values",
        ),
        (
            lambda r: observed(r, "baking/common", "DilationWidth")["properties"].update(max=64),
            "range",
        ),
        (
            lambda r: observed(r, "baking/baker/ID", "ColorSource", 2).update(widget_type="List"),
            "recording 3",
        ),
    ],
)
def test_drift_fails_naming_the_key_and_the_cited_hash(change: Any, expected: str) -> None:
    """Spec scenario "Default drift": the check fails and names the key and the cited hash."""
    table = bd.load_table()
    sha = table["observation"]["record_sha256"]
    record = synthetic_record(table)
    change(record)
    problems = bd.check(table, record, sha)
    assert problems and all(sha[:12] in problem for problem in problems), problems
    assert any(expected in problem for problem in problems), problems


def test_an_unestablished_default_must_stay_null() -> None:
    table = bd.load_table()
    sha = table["observation"]["record_sha256"]
    [entry] = [e for e in table["common"] if e["short_name"] == "OutputSize"]
    entry["default"] = [10, 10]
    problems = bd.check(table, synthetic_record(bd.load_table()), sha)
    assert problems == [f"baking/common OutputSize (record {sha[:12]}): default differs"]


def test_the_model_check_names_each_difference() -> None:
    table = bd.load_table()
    model: dict[str, Any] = {
        "common": [dict(e) for e in table["common"]],
        "bakers": {usage: [dict(e) for e in entries] for usage, entries in table["bakers"].items()},
        "texture_set_state": {k: v["default"] for k, v in table["texture_set_state"].items()},
    }
    assert bd.check_model(table, model) == []
    model["bakers"]["AO"][0]["label"] = "Something else"
    model["texture_set_state"]["textureset_enabled"] = False
    assert bd.check_model(table, model) == [
        "model baking/baker/AO Attenuation: label differs",
        "model texture_set_state textureset_enabled: differs",
    ]


def test_the_private_capture_equals_the_table() -> None:
    """3.2 on the owner's machine (decision 028): the cited record, read from the private store."""
    store = locate()
    sha = bd.load_table()["observation"]["record_sha256"]
    if store is None or store.load(sha) is None:
        # Decision 028: the oracle comparison runs only where the private store holds the record.
        pytest.skip(f"oracle_unavailable: record {sha[:12]} is not in this machine's store")
    report = bd.run(bd.TABLE, None, store)
    assert report["status"] == "pass", report["problems"]
    assert report["records"] == [sha] and report["entries"] == 60
