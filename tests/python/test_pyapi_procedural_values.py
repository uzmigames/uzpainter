"""Public source value types: recorded Tier 0 parity without procedural evaluation."""

from __future__ import annotations

import ast
import json

import pytest

from tests.python.capability_trace import check_trace, exercised, traced
from tests.python.conftest import Run
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import Status, locate, resolve_oracle

MANIFEST = (
    REPO_ROOT
    / "parity/envelopes/painter-12.2.0_js-api.1.1.20-env-a981b586eae7"
    / "manifests/tier0/api-probes/source-resolution-values.json"
)


def test_resolution_types_match_both_recorded_readbacks(facade: Run) -> None:
    manifest = json.loads(MANIFEST.read_text())
    reference = next(r for r in manifest["private_records"] if r["record_id"] == "golden-record")
    resolved = resolve_oracle(locate(), reference)
    if resolved.status != Status.AVAILABLE or resolved.path is None:
        pytest.skip(f"oracle_unavailable: {resolved.reason}")
    record = json.loads(resolved.path.read_text())
    protocol = (REPO_ROOT / "tools/parity/recorder/painter_probes.py").read_text(encoding="utf-8")
    function = next(
        node
        for node in ast.parse(protocol).body
        if isinstance(node, ast.FunctionDef) and node.name == "resolution_contract"
    )
    body = ast.get_source_segment(protocol, function)
    assert body is not None
    script = """
import enum
from typing import Any
import substance_painter

def describe(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, enum.Enum):
        return value.name
    if isinstance(value, (tuple, list)):
        return [describe(v) for v in value]
    if isinstance(value, dict):
        return {key: describe(v) for key, v in value.items()}
    return value.name
"""
    steps = manifest["instruction_sequence"]["steps"][1:]
    script += (
        body
        + "\nsteps = "
        + repr(steps)
        + """
create()
before = uzpainter.project.revision()
result = {}
for step in steps:
    key = 's' + str(step['step']) + '/' + step['call'].rsplit('.', 1)[1]
    try:
        result[key] = {'value': describe(resolution_contract(step['call'], step['args']))}
    except Exception as error:
        result[key] = {'raised': {'type': type(error).__name__, 'message': str(error)}}
assert uzpainter.project.revision() == before
"""
    )
    observed = facade(traced(script))
    assert observed["status"] == "ok", observed
    results, trace = observed["result"]
    for recording in record["recordings"]:
        expected = {
            entry["output_id"]: {"raised": entry["raised"]}
            if "raised" in entry
            else {"value": entry["value"]}
            for entry in recording["outputs"]
            if entry["kind"] == "api_readback" and entry["output_id"].startswith("s")
        }
        assert results == expected, {
            key: {"expected": value, "actual": results.get(key)}
            for key, value in expected.items()
            if results.get(key) != value
        }
    check_trace("facade/source-resolution-values", manifest["golden_id"], exercised(trace))


def test_invalid_resolution_assignment_preserves_value_and_project(facade: Run) -> None:
    report = facade("""
import dataclasses
create()
before = uzpainter.project.revision()
value = source.ResolutionOverride(source.ResolutionMode.Custom, (128, 4096), 0)
error = raises(setattr, value, 'value', (257, 512))
result = {
    'error': error,
    'value': list(value.value),
    'dataclass': dataclasses.is_dataclass(value),
    'aliases': source.ResolutionMode.Document is source.ResolutionMode.Asset
        and source.ResolutionMode.Manual is source.ResolutionMode.Custom,
    'revision_unchanged': uzpainter.project.revision() == before,
}
""")
    assert report["status"] == "ok", report
    assert report["result"] == {
        "error": "ValueError: Attribut 'value': resolution values should be a power of 2",
        "value": [128, 4096],
        "dataclass": True,
        "aliases": True,
        "revision_unchanged": True,
    }


def test_resolution_dataclass_contract_and_individual_field_trace(facade: Run) -> None:
    report = facade(
        traced("""
import dataclasses
import inspect
value = source.ResolutionOverride(source.ResolutionMode.Auto, (128, 256), 0)
fields = dataclasses.fields(value)
assert [field.name for field in fields] == ['mode', 'value', 'log2_offset']
assert all(field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING
           for field in fields)
assert all(parameter.default is inspect.Parameter.empty
           for parameter in inspect.signature(source.ResolutionOverride).parameters.values())
assert vars(value) == {'mode': source.ResolutionMode.Auto, 'value': (128, 256), 'log2_offset': 0}
assert dataclasses.asdict(value) == vars(value)
assert repr(value) == ('ResolutionOverride(mode=' + repr(source.ResolutionMode.Auto)
                       + ', value=(128, 256), log2_offset=0)')
for name, replacement in [('mode', 'unvalidated'), ('value', [256, 512]), ('log2_offset', 1.5)]:
    _TRACE['mark']('write/' + name)
    setattr(value, name, replacement)
    _TRACE['mark']('read/' + name)
    assert getattr(value, name) == replacement
_TRACE['mark']('contract')
before = vars(value).copy()
error = raises(setattr, value, 'value', [257, 512])
assert vars(value) == before
assert error.startswith('ValueError:')
for name in ('mode', 'value', 'log2_offset'):
    delattr(value, name)
assert vars(value) == {}
result = True
""")
    )
    assert report["status"] == "ok", report
    result, trace = report["result"]
    assert result is True
    prefix = "substance_painter.source.ResolutionOverride."
    for name in ("mode", "value", "log2_offset"):
        for action in ("read", "write"):
            assert {
                symbol for symbol in trace[action + "/" + name] if symbol.startswith(prefix)
            } == {prefix + name}
