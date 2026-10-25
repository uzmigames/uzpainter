"""Replay of admitted SourceSubstance probes over the captured snapshot project (2.6e step 4).

The project is a private derived artifact: UzPainter's own plane project holding the explicit
toggle 0 and toggle 1 snapshots captured by `UzPainter.exe assets snapshot`, with the initial
signature bound by `assets bind-snapshot` (fill uid 6, User0). It is resolved from the private
oracle store by hash and size and copied before it is opened; without it the tests skip as
`oracle_unavailable`. The recorder's own source functions (`painter_probes.py`,
`painter_side.py`) run unchanged through the facade; the only adaptation is the node: the
recorded node step 3 is the bound fill layer. Two real differences are reported, never
normalized: `resource_id` (UzPainter exposes its own pin) and the typed-parameter loss of
`TYPED_PARAMETER_LOSS`. Every other replayed step must equal its recording, types included.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from tests.python.conftest import Run
from tests.python.recorded_probe import ENVELOPE, recorded_readbacks
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import Status, locate, resolve_oracle

# Public references of the private /2 capture, hashes only (2026-10-25, Painter lock seq
# 1267/1268, UzPainter's own Legacy Painter; UzPainter.exe built at d72fa634). Receipts and
# requests stay private.
# `request_sha256` hashes the request file given to `assets snapshot` (the command keeps a
# canonical copy beside its receipt, whose bytes differ).
CAPTURE: dict[str, Any] = {
    "exe_sha256": "096f751cd6ff896d4e7f47e45db8c1814734bf4f8e7798dce9dbf6fce539c156",
    "bridge_sha256": "c941fe3a46b49bd1a0a691d9395e6750a71963a38868c4378d6b2023ca1612c3",
    "painter_side_sha256": "14cb8e44b284363c10a1d6affbbf9388d3993e8f4938f0e0b27342fa3204fecc",
    "toggle_0": {
        "signature_sha256": "fe9a975644a85ede1e1f5f3a127b08f040f795ad6b3cd6f7a52c5b350185bf4b",
        "request_sha256": "cf647c2c69d210039036bdf65e124bb7edf73f89ee02f7b66a2b0e9262c09a78",
        "receipt_sha256": "4cccf05525d9dcfd2b792d54eb898b8b9554f956b187723f952121e54ccb617b",
    },
    "toggle_1": {
        "signature_sha256": "190f21cad9c59752e66165ceeb64dcac63a64dc49783135da0aecc59138f9501",
        "request_sha256": "4cb69ff87970a007753e7b2de216952d7f056c64bb15b83adf3a8b37222aff53",
        "receipt_sha256": "346353fbf4ab8ac725be9b6d15bae4524c118ad3fc6dff57c56df9cce97a3a1a",
    },
    # The bound initial state: toggle 0, fill uid 6, User0, the receipt's nominal override.
    "bind_request_sha256": "f0c3126bd180db8ec09a009a0ec089ea0a95474498ea02bb21768d567cb927d8",
}
PROJECT_BLOB = {
    "record_id": "source-substance-0-1-project",
    "sha256": "bab09b8b950dadfb4c719bf9030029b0a4f22a33abe818802250a257677d59e5",
    "size_bytes": 225280,
}
FILL_UID = 6
NODE_STEP = 3

# Every probe step after the setup steps, except the booleans probe's filter steps 16-24 (the
# captured project has no filter; tests/python/test_pyapi_effect_sources.py replays those).
PROBES = {
    "source-substance-single-output": range(6, 59),
    "source-substance-booleans-filter": range(7, 16),
    "source-substance-held-property": range(6, 13),
}
# The known difference (2026-10-25 baseline): the bound reference carries the signature's
# parameters, whose codec writes integral doubles as integers, so get_parameters returns an int
# where Painter returned an integral float. Both recordings, these steps only, and nothing but
# that type changes; a step joining or leaving this set fails the test (nothing is coerced).
TYPED_PARAMETER_LOSS = {
    "source-substance-single-output": {"s6", "s15", "s24", "s33", "s42", "s51"},
    "source-substance-booleans-filter": {"s7", "s9", "s11", "s13", "s15"},
    "source-substance-held-property": set(),
}
RECORDER = ("painter_side", "painter_probes")  # a later module's definition wins
REPLAYED = ("describe", "substance_read", "substance_edit", "HELD_PROPERTIES")
ADAPTED = ("fresh", "channel_arg")  # the node resolution: replaced, never extracted


@pytest.fixture
def captured_project(tmp_path: Path) -> Path:
    resolved = resolve_oracle(locate(), PROJECT_BLOB)
    if resolved.status != Status.AVAILABLE or resolved.path is None:
        pytest.skip(f"oracle_unavailable: {resolved.reason}")
    target = tmp_path / "captured.uzp"
    shutil.copyfile(resolved.path, target)
    size = target.stat().st_size
    sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
    if (sha256, size) != (PROJECT_BLOB["sha256"], PROJECT_BLOB["size_bytes"]):
        pytest.fail(f"copied project differs: sha256 {sha256}, size {size}", pytrace=False)
    return target


def recorder_code(names: tuple[str, ...]) -> str:
    """The recorder's own top-level definitions `names` and every definition they reference,
    verbatim, in module order (painter_side.py, then painter_probes.py)."""
    table: dict[str, tuple[int, int, str, ast.AST]] = {}
    for rank, module in enumerate(RECORDER):
        source = (REPO_ROOT / "tools/parity/recorder" / f"{module}.py").read_text(encoding="utf-8")
        for position, node in enumerate(ast.parse(source).body):
            name = None
            if isinstance(node, ast.FunctionDef):
                name = node.name
            elif isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                name = target.id if isinstance(target, ast.Name) else None
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                name = node.target.id
            if name is not None:
                table[name] = (rank, position, str(ast.get_source_segment(source, node)), node)
    wanted: set[str] = set()
    queue = list(names)
    while queue:
        name = queue.pop()
        if name in wanted or name in ADAPTED or name not in table:
            continue
        wanted.add(name)
        queue.extend(n.id for n in ast.walk(table[name][3]) if isinstance(n, ast.Name))
    assert set(names) <= wanted, sorted(set(names) - wanted)
    return "\n\n".join(table[name][2] for name in sorted(wanted, key=lambda n: table[n][:2]))


def probe_steps(name: str) -> list[dict[str, Any]]:
    manifest = json.loads(
        (ENVELOPE / "manifests/tier0/api-probes" / f"{name}.json").read_text(encoding="utf-8")
    )
    steps = [s for s in manifest["instruction_sequence"]["steps"] if s["step"] in PROBES[name]]
    assert [s["step"] for s in steps] == list(PROBES[name])
    assert all(s["args"].get("node_step", NODE_STEP) == NODE_STEP for s in steps)
    assert all(s["args"].get("channel", "User0") == "User0" for s in steps)
    return steps


def expected(name: str, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per recording, `s<step>` -> the admitted readback of that step."""
    return [
        {
            f"s{s['step']}": readbacks[f"s{s['step']}/{str(s['call']).rsplit('.', 1)[1]}"]
            for s in steps
        }
        for readbacks in recorded_readbacks(name)
    ]


def typed(value: Any) -> Any:
    """`value` with every scalar tagged by its JSON type: 15 and 15.0 differ, as do 1 and True."""
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, int):
        return ["int", value]
    if isinstance(value, float):
        return ["float", repr(value)]
    if isinstance(value, list):
        return ["list", [typed(v) for v in value]]
    if isinstance(value, dict):
        return ["dict", {str(k): typed(v) for k, v in value.items()}]
    return [type(value).__name__, value]


def float_to_int_only(recorded: Any, replayed: Any) -> bool:
    """True when two typed values have the same shape and differ only where an integral float
    was recorded and the same integer was replayed."""
    if recorded == replayed:
        return True
    if recorded[0] == "float" and replayed[0] == "int":
        # Exact integers: comparing as floats would accept 9007199254740993 for 2.0**53.
        number = float(recorded[1])
        return number.is_integer() and int(number) == replayed[1]
    if recorded[0] != replayed[0] or recorded[0] not in ("list", "dict"):
        return False
    a, b = recorded[1], replayed[1]
    if recorded[0] == "list":
        return len(a) == len(b) and all(float_to_int_only(x, y) for x, y in zip(a, b, strict=True))
    return a.keys() == b.keys() and all(float_to_int_only(a[k], b[k]) for k in a)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(typed(value), sort_keys=True).encode()).hexdigest()[:12]


PRELUDE = """
import dataclasses
import datetime
import enum
import json
import os
from collections.abc import Callable
from typing import Any
import substance_painter
"""

ADAPTATION = """
def fresh(step):
    # The only adaptation: the recorded fill step is the bound fill layer.
    assert int(step) == NODE_STEP
    node = ls.get_root_layer_nodes(ts.get_active_stack())[0]
    assert node.uid() == FILL_UID
    return node

def channel_arg(args):
    return getattr(ts.ChannelType, args["channel"])
"""

REPLAY = """
def replay():
    observed = {}
    for step in steps:
        call, args = step["call"], dict(step["args"])
        read = "roundtrip" not in args
        try:
            value = substance_read(call, args) if read else substance_edit(call, args)
            observed["s" + str(step["step"])] = {"value": describe(value)}
        except Exception as error:
            observed["s" + str(step["step"])] = {
                "raised": {"type": type(error).__name__, "message": str(error)}
            }
    return observed

uzpainter.project.open(WORK + "/captured.uzp")
first = replay()
uzpainter.project.save()
uzpainter.project.close()
uzpainter.project.open(WORK + "/captured.uzp")
second = replay()
uzpainter.project.close()
result = [first, second]
"""


def replay(facade: Run, name: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    steps = probe_steps(name)
    script = (
        PRELUDE
        + recorder_code(REPLAYED)
        + ADAPTATION
        + f"\nNODE_STEP = {NODE_STEP}\nFILL_UID = {FILL_UID}\nsteps = {steps!r}\n"
        + REPLAY
    )
    report = facade(script)
    if report["status"] != "ok":
        # The report may carry private values (messages, tracebacks): kept privately.
        text = json.dumps(report, indent=1)
        (private_dir() / f"replay-failure-{name}.json").write_text(text, encoding="utf-8")
        error = report.get("error") or {}
        pytest.fail(f"replay script failed: {error.get('type')} (details kept privately)", False)
    observed: list[dict[str, Any]] = report["result"]
    keys = {f"s{s['step']}" for s in steps}
    if not (
        isinstance(observed, list)
        and len(observed) == 2
        and all(isinstance(r, dict) and set(r) == keys for r in observed)
    ):
        pytest.fail("replay result is not two recordings of the probe's steps", pytrace=False)
    return observed, steps


def private_dir() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "UzPainter"


def resource_id_steps(steps: list[dict[str, Any]]) -> set[str]:
    return {f"s{s['step']}" for s in steps if str(s["call"]).endswith(".resource_id")}


def internal_pin_readback(name: str) -> dict[str, Any]:
    """The readback UzPainter's resource_id gives today: the snapshot pin of the probe's own
    versioned resource URL (`uzasset://snapshot/<sha256(url)>@1`), as the recorder describes it."""
    manifest = json.loads(
        (ENVELOPE / "manifests/tier0/api-probes" / f"{name}.json").read_text(encoding="utf-8")
    )
    urls = {
        s["args"]["resource_url"]
        for s in manifest["instruction_sequence"]["steps"]
        if str(s["call"]).endswith(".set_source")
    }
    assert len(urls) == 1
    pin = hashlib.sha256(urls.pop().encode("utf-8")).hexdigest()
    parts = {"context": "uzasset", "name": f"snapshot/{pin}", "version": "1"}
    url = f"resource://uzasset/snapshot/{pin}?version=1"
    return {"value": {"resource_id": {"resource": parts}, "url": url}}


@pytest.mark.parametrize("name", sorted(PROBES))
def test_recorded_source_steps_replay_exactly_except_known_differences(
    private_facade: Run, captured_project: Path, name: str
) -> None:
    """Recording 1 is replayed on the captured project, which is then saved, closed and reopened
    before recording 2 is replayed, as the recorder did. Values compare with their JSON types.
    Messages name only the condition, step, call and digests; the full differences go to a
    private file beside the oracle store."""
    observed, steps = replay(private_facade, name)
    calls = {f"s{s['step']}": str(s["call"]).rsplit(".", 2)[-2:] for s in steps}
    excluded = resource_id_steps(steps)
    pin = typed(internal_pin_readback(name)) if excluded else None
    mismatches: list[str] = []
    different: list[str] = []  # known differences; the full comparison is `different` with any
    details: dict[str, Any] = {}
    pairs = zip(expected(name, steps), observed, strict=True)
    for condition, (recorded, actual) in enumerate(pairs):
        for key in calls:
            want, got = typed(recorded[key]), typed(actual[key])
            label = f"r{condition + 1} {key} {'.'.join(calls[key])}"
            hashes = f"recorded {digest(recorded[key])} != replayed {digest(actual[key])}"
            if want != got:
                details[f"r{condition + 1}/{key}"] = {"recorded": want, "replayed": got}
            if key in excluded:
                # A real representational difference: UzPainter reports its own snapshot pin, and
                # exactly that pin; any other value or a raised error is unexpected.
                if want == got:
                    mismatches.append(f"{label}: resource_id unexpectedly equal")
                elif got != pin:
                    mismatches.append(f"{label}: resource_id is not the internal snapshot pin")
                else:
                    different.append(f"{label}: {hashes} (internal pin)")
            elif key in TYPED_PARAMETER_LOSS[name]:
                if want == got:
                    mismatches.append(f"{label}: the known typed-parameter loss is gone")
                elif not float_to_int_only(want, got):
                    mismatches.append(f"{label}: differs beyond the known float->int loss")
                else:
                    different.append(f"{label}: {hashes} (float->int)")
            elif want != got:
                mismatches.append(f"{label}: {hashes}")
    if details:
        text = json.dumps(details, indent=1)
        (private_dir() / f"replay-differences-{name}.json").write_text(text, encoding="utf-8")
    # Not part of the exact subset; reported, never normalized.
    unexpected = len(mismatches)
    status = "equal" if not different and not unexpected else "different"
    print(
        f"full comparison: {status} ({len(different)} known, {unexpected} unexpected)",
        *different,
        sep="\n",
    )
    if mismatches:
        summary = [f"{len(mismatches)} replay differences:", *mismatches]
        pytest.fail("\n".join(summary), pytrace=False)


def test_float_to_int_only_keeps_exact_integers() -> None:
    assert float_to_int_only(typed({"a": 15.0}), typed({"a": 15}))
    assert float_to_int_only(typed(2.0**53), typed(2**53))
    assert not float_to_int_only(typed(2.0**53), typed(2**53 + 1))
    assert not float_to_int_only(typed(1.5), typed(1))
    assert not float_to_int_only(typed(1), typed(1.0))
    assert not float_to_int_only(typed(True), typed(1))
