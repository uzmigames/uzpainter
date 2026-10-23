"""The local check of `assets/defaults/baking.json` against the private baking-defaults capture
(phase3.1_baker-request-model items 2.8, 2.9 and 3.2; decisions 028 and 323;
`docs/architecture/06-baking.md` §2).

UzmiGames authored the table from Painter's documented API. Each entry cites the private
observation it must equal: the Tier 0 record `tier0/defaults-templates/baking-defaults`, by its
SHA-256. This module resolves that record in this machine's private store, read only, and
compares every entry with what the record observed:
- the keys and their order;
- the name, label and widget type;
- the value type (from the type of Painter's `value()`);
- the enum values;
- the range (`min`/`max`, `minPow2`/`maxPow2`);
- the default (the fresh project's `value()`, or null where Painter states no `defaultValue`);
- the texture set's baking state.

Every recording must agree. `check_model` compares the native model's dump
(`uzp-baking-project-tests catalog <file>`) with the table. Problems name the key and the cited
hash, never a recorded value, so the report holds no Painter output.

`python -m tools.bake.bake_defaults check [--table FILE] [--model DUMP] [--report FILE]`.
Exit status:
- 0: the table equals the capture;
- 1: a problem was found;
- 2: the oracle is unavailable here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import OracleStore, locate

TABLE = REPO_ROOT / "assets" / "defaults" / "baking.json"
SCHEMA = "uzpainter/baking-defaults/1"
GOLDEN_ID = "tier0/defaults-templates/baking-defaults"


@dataclass(frozen=True)
class BakingCase:
    """One authored capture; each control keeps its own golden and exercised-symbol trace."""

    name: str

    @property
    def golden_id(self) -> str:
        return f"tier0/defaults-templates/{self.name}"

    @property
    def manifest_relative(self) -> Path:
        return Path(self.golden_id + ".json")

    @property
    def trace_id(self) -> str:
        return f"facade/{self.name}"


BASELINE = BakingCase("baking-defaults")
CONTROL_CASES = (
    BakingCase("baking-defaults-plane-256"),
    BakingCase("baking-defaults-plane-1024"),
    BakingCase("baking-defaults-bevelled-cube-256"),
    BakingCase("baking-defaults-plane-512"),
    BakingCase("baking-defaults-plane-2048"),
    BakingCase("baking-defaults-plane-256-resize-1024"),
    BakingCase("baking-defaults-plane-1024-resize-256"),
    BakingCase("baking-defaults-plane-256-resize-256x1024"),
)
CASES = (BASELINE, *CONTROL_CASES)
USAGES = (
    "Normal",
    "WorldSpaceNormal",
    "ID",
    "AO",
    "Curvature",
    "Position",
    "Thickness",
    "Height",
    "BentNormals",
    "Opacity",
)
STATE_OUTPUTS = {
    "curvature_method": "baking/get_curvature_method",
    "enabled_bakers": "baking/get_enabled_bakers",
    "textureset_enabled": "baking/is_textureset_enabled",
}
ENTRY_FIELDS = frozenset(
    {
        "short_name",
        "name",
        "label",
        "widget_type",
        "type",
        "enum_values",
        "range",
        "default",
        "default_note",
        "initial_value",
        "initial_by_resolution",
        "provenance",
    }
)
RANGE_KEYS = (("min", "min"), ("max", "max"), ("minPow2", "min"), ("maxPow2", "max"))


class OracleUnavailable(Exception):
    """The cited record cannot be read on this machine."""


def load_table(path: Path = TABLE) -> dict[str, Any]:
    table: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if table.get("schema") != SCHEMA:
        raise ValueError(f"{path}: schema is not {SCHEMA}")
    return table


def groups(table: Mapping[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    """`(output_id, entries)` of `common()` and of every baker, in the capture's order."""
    out = [("baking/common", list(table["common"]))]
    out += [(f"baking/baker/{usage}", list(table["bakers"][usage])) for usage in USAGES]
    return out


def cited_hashes(table: Mapping[str, Any]) -> set[str]:
    hashes = {
        entry["provenance"]["record_sha256"] for _, entries in groups(table) for entry in entries
    }
    hashes |= {
        state["provenance"]["record_sha256"] for state in table["texture_set_state"].values()
    }
    return hashes


def same(a: Any, b: Any) -> bool:
    """JSON equality that keeps bool, int and float apart (`True != 1`), with exact floats."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, float) or isinstance(b, float):
        return isinstance(a, (int, float)) and isinstance(b, (int, float)) and float(a) == float(b)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


def value_type(value: Any, enum_values: Mapping[str, int]) -> str:
    """The table's type of a captured `value()`."""
    if isinstance(value, bool):
        return "Bool"
    if isinstance(value, int):
        return "Enum" if enum_values else "Int"
    if isinstance(value, float):
        return "Float"
    if isinstance(value, str):
        return "String"
    if isinstance(value, list) and len(value) == 2:
        if all(isinstance(v, int) and not isinstance(v, bool) for v in value):
            return "IntPair"
        if all(isinstance(v, float) for v in value):
            return "FloatPair"
    return "unknown"


def texture_set_values(record: Mapping[str, Any], output_id: str) -> list[Any]:
    """The value of `output_id` on the record's one texture set, per recording."""
    found = []
    for recording in record["recordings"]:
        outputs = {output["output_id"]: output for output in recording["outputs"]}
        if output_id not in outputs:
            raise KeyError(output_id)
        sets = outputs[output_id]["values"]["texture_sets"]
        if len(sets) != 1:
            raise ValueError(f"{output_id}: the record has {len(sets)} texture sets, not one")
        found.append(next(iter(sets.values())))
    return found


def check_entry(entry: Mapping[str, Any], observed: Mapping[str, Any], where: str) -> list[str]:
    """The fields of one entry that differ from one observed property (names only)."""
    meta = observed["properties"]
    enum_values = observed["enum_values"]
    fields: list[str] = []
    for field in ("name", "label", "widget_type"):
        if not same(entry.get(field), observed[field]):
            fields.append(field)
    if entry.get("short_name") != observed["short_name"]:
        fields.append("short_name")
    if entry.get("type") != value_type(observed["value"], enum_values):
        fields.append("type")
    if not same(entry.get("enum_values", {}), enum_values):
        fields.append("enum_values")
    if enum_values and not same(observed.get("enum_value", enum_values), enum_values):
        fields.append("enum_value")
    observed_range = {
        bound: meta[key] for key, bound in RANGE_KEYS if key in meta and meta[key] is not None
    }
    if not same(entry.get("range", {}), observed_range):
        fields.append("range")
    stated_none = "defaultValue" in meta and meta["defaultValue"] is None
    if stated_none:
        if entry.get("default") is not None or not entry.get("default_note"):
            fields.append("default")
    elif not same(entry.get("default"), observed["value"]):
        fields.append("default")
    if "initial_value" in entry and not same(entry["initial_value"], observed["value"]):
        fields.append("initial_value")
    unknown = set(entry) - ENTRY_FIELDS
    if unknown:
        fields.append("unknown fields " + ", ".join(sorted(unknown)))
    return [f"{where}: {field} differs" for field in fields]


def check(table: Mapping[str, Any], record: Mapping[str, Any], sha256: str) -> list[str]:
    """Every difference between the table and the record `sha256` (problems name the key and
    the hash, never a value)."""
    problems: list[str] = []
    if record.get("golden_id") != GOLDEN_ID:
        problems.append(f"record {sha256[:12]}: not {GOLDEN_ID}")
        return problems
    if [r.get("recording_id") for r in record.get("recordings", [])] != ["r1", "r2", "r3"]:
        return [f"record {sha256[:12]}: expected recordings r1, r2, r3 in order"]
    for output_id, entries in groups(table):
        try:
            observations = texture_set_values(record, output_id)
        except (KeyError, ValueError) as error:
            problems.append(f"{output_id} (record {sha256[:12]}): {error}")
            continue
        for index, observed in enumerate(observations[1:], start=2):
            if not same(observed, observations[0]):
                problems.append(
                    f"{output_id} (record {sha256[:12]}): recording {index} differs from the first"
                )
        observed = observations[0]
        keys = [entry["short_name"] for entry in entries]
        if keys != observed["keys"]:
            problems.append(f"{output_id} (record {sha256[:12]}): the keys or their order differ")
        for entry in entries:
            key = entry["short_name"]
            where = f"{output_id} {key} (record {entry['provenance']['record_sha256'][:12]})"
            if (
                entry["provenance"]["record_sha256"] != sha256
                or entry["provenance"]["output_id"] != output_id
            ):
                problems.append(
                    f"{where}: provenance does not cite this output of record {sha256[:12]}"
                )
            if key not in observed["properties"]:
                problems.append(f"{where}: the record has no such key")
                continue
            problems += check_entry(entry, observed["properties"][key], where)
    for name, output_id in STATE_OUTPUTS.items():
        state = table["texture_set_state"][name]
        where = f"{output_id} (record {state['provenance']['record_sha256'][:12]})"
        try:
            observations = texture_set_values(record, output_id)
        except (KeyError, ValueError) as error:
            problems.append(f"{where}: {error}")
            continue
        if not all(same(state["default"], value) for value in observations):
            problems.append(f"{where}: default differs")
    return problems


def check_model(table: Mapping[str, Any], model: Mapping[str, Any]) -> list[str]:
    """Every difference between the native model's dump and the table."""
    problems: list[str] = []
    for output_id, entries in groups(table):
        name = output_id.rsplit("/", 1)[1]
        dumped = model["common"] if output_id == "baking/common" else model["bakers"].get(name, [])
        if [e["short_name"] for e in dumped] != [e["short_name"] for e in entries]:
            problems.append(f"model {output_id}: the keys or their order differ")
            continue
        for entry, got in zip(entries, dumped, strict=True):
            for field in (
                "name",
                "label",
                "widget_type",
                "type",
                "enum_values",
                "range",
                "default",
                "initial_value",
                "initial_by_resolution",
            ):
                if not same(
                    entry.get(field, {} if field in ("enum_values", "range") else None),
                    got.get(field, {} if field in ("enum_values", "range") else None),
                ):
                    problems.append(f"model {output_id} {entry['short_name']}: {field} differs")
    for name in STATE_OUTPUTS:
        if not same(
            table["texture_set_state"][name]["default"], model["texture_set_state"].get(name)
        ):
            problems.append(f"model texture_set_state {name}: differs")
    return problems


def check_initial_record(
    table: Mapping[str, Any], record: Mapping[str, Any], sha256: str
) -> list[str]:
    """Initial values require independent resolution/geometry controls, not declared defaults."""
    if [r.get("recording_id") for r in record.get("recordings", [])] != ["r1", "r2", "r3"]:
        return [f"record {sha256[:12]}: expected recordings r1, r2, r3 in order"]
    problems = []
    for output_id, entries in groups(table):
        initial = [
            entry
            for entry in entries
            if "initial_value" in entry or "initial_by_resolution" in entry
        ]
        if not initial:
            continue
        for index, values in enumerate(texture_set_values(record, output_id), 1):
            for entry in initial:
                key = entry["short_name"]
                observed = values["properties"].get(key, {})
                expected = entry.get("initial_value")
                if "initial_by_resolution" in entry:
                    size = record["key"]["project_settings"]["create"].get(
                        "default_texture_resolution"
                    )
                    if size is None:
                        sets = record["key"]["effective_defaults"]["project.create"]["texture_sets"]
                        [created] = sets.values()
                        width, height = created["resolution"]
                        size = width if width == height else None
                    expected = entry["initial_by_resolution"].get(str(size))
                if expected is None or not same(expected, observed.get("value")):
                    problems.append(
                        f"{output_id} {key} (record {sha256[:12]} r{index}): initial_value differs"
                    )
    return problems


def load_record(store: OracleStore | None, sha256: str) -> dict[str, Any]:
    if store is None:
        raise OracleUnavailable("no private store on this machine")
    data = store.load(sha256)
    if data is None:
        raise OracleUnavailable(f"record {sha256[:12]} is not available in the store")
    record: dict[str, Any] = json.loads(data.decode("utf-8"))
    return record


def run(
    table_path: Path = TABLE, model: Path | None = None, store: OracleStore | None = None
) -> dict[str, Any]:
    """The check's report: `{status, table_sha256, records, problems}` (no recorded value)."""
    table = load_table(table_path)
    problems: list[str] = []
    hashes = sorted(cited_hashes(table))
    if table["observation"]["record_sha256"] not in hashes or len(hashes) != 1:
        problems.append("every entry must cite the table's one observation")
    for sha256 in hashes:
        problems += check(table, load_record(store, sha256), sha256)
    observations = table.get("initial_observations", [])
    if {item["golden_id"] for item in observations} != {case.golden_id for case in CASES}:
        problems.append("initial values must cite the baseline and every authored control")
    for observation in observations:
        sha256 = observation["record_sha256"]
        record = load_record(store, sha256)
        if record.get("golden_id") != observation["golden_id"]:
            problems.append(f"record {sha256[:12]}: initialization golden differs")
        problems += check_initial_record(table, record, sha256)
    hashes = sorted(set(hashes) | {item["record_sha256"] for item in observations})
    if model is not None:
        problems += check_model(table, json.loads(model.read_text(encoding="utf-8")))
    return {
        "schema": "uzpainter/baking-defaults-check/1",
        "status": "pass" if not problems else "fail",
        "table_sha256": hashlib.sha256(table_path.read_bytes()).hexdigest(),
        "records": hashes,
        "entries": sum(len(entries) for _, entries in groups(table)),
        "model_compared": model is not None,
        "problems": problems,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.bake.bake_defaults")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("check", help="compare the table with the private capture")
    command.add_argument("--table", type=Path, default=TABLE)
    command.add_argument("--model", type=Path, help="a dump of uzp-baking-project-tests catalog")
    command.add_argument("--report", type=Path, help="write the JSON report here")
    args = parser.parse_args(argv)
    try:
        report = run(args.table, args.model, locate())
    except OracleUnavailable as error:
        print(f"oracle_unavailable: {error}", file=sys.stderr)
        return 2
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report is not None:
        args.report.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
