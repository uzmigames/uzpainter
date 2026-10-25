"""Private control fidelity only; never parity evidence for the old Filter steps 16-18."""

from __future__ import annotations

import hashlib
import inspect
import os
import shutil
import traceback
from contextlib import suppress
from pathlib import Path
from typing import Any

import pytest

from tests.python.capability_trace import SOURCE
from tests.python.conftest import FACADE_PRELUDE, PRELUDE, Run, runner
from tools.parity import filter_observation_import as observation
from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.recorder.job import canonical_json
from tools.parity.recorder.output import ensure_outside_repository
from tools.parity.store.store import locate
from tools.parity.tier0_semantics import filter_observation_control as control

GETTERS = ("get_parameters", "resource_id", "image_outputs")
CONDITIONS = ("same_session", "after_save_reopen")


def prepare(work: Path, configured: str) -> None:
    """Copy only the owner's closed imported fixture; derive expectations from admitted bytes."""
    source = ensure_outside_repository(Path(configured))
    observation.require(source.is_file() and source.suffix == ".uzp", "private project required")
    wal = Path(str(source) + "-wal")
    observation.require(not wal.exists() or wal.stat().st_size == 0, "project must be closed")
    manifest_path = (
        manifest_root(current_envelope()) / "tier0" / "api-probes" / (control.NAME + ".json")
    )
    manifest = observation.parse(manifest_path.read_bytes())
    authored = control.request()
    for name in ("golden_id", "instruction_sequence", "inputs", "applied_settings", "software"):
        observation.require(
            observation.typed_json(manifest[name]) == observation.typed_json(authored[name]),
            "official control differs",
        )
    store = locate()
    observation.require(store is not None, "oracle unavailable")
    if store is None:
        raise observation.ImportRefused("oracle unavailable")
    data, job = observation.admitted_record(store, manifest)
    record = observation.parse(data)
    observation.require(
        record["key"]["instruction_sequence_sha256"] == job.instruction_sequence_sha256
        and observation.typed_json(record["key"]["inputs"])
        == observation.typed_json(job.input_hashes())
        and observation.typed_json(record["key"]["painter_build"])
        == observation.typed_json(manifest["software"]["painter"]),
        "record recipe differs",
    )
    paired = observation.paired_readbacks(record, job)
    filter_steps = [s.step for s in job.state_steps if s.call.endswith(".insert_filter_effect")]
    observation.require(len(filter_steps) == 1, "unique Filter required")
    expected: dict[str, Any] = {"readbacks": {}, "outputs": {}}
    for condition in CONDITIONS:
        values = {}
        for getter in GETTERS:
            steps = [
                s
                for s in job.probe_steps
                if s.call == control.SOURCE + getter
                and s.args.get("node_step") == filter_steps[0]
                and s.args.get("effect") is True
            ]
            observation.require(len(steps) == 1, "unique Filter getter required")
            step = steps[0]
            value = paired[condition][step.step]
            if getter == "get_parameters":
                value = observation.parameters(value)
            elif getter == "resource_id":
                value = observation.resource_id(value)
            else:
                observation.require(
                    type(value) is list
                    and all(type(item) is str and item for item in value)
                    and len(set(value)) == len(value),
                    "invalid observed outputs",
                )
            values[getter] = value
            expected["outputs"][getter] = step.output_id
        expected["readbacks"][condition] = values
    expected["receipt_sha256"] = hashlib.sha256(data).hexdigest()
    observation.write_private(work / "expected.json", expected)
    target = work / "captured.uzp"
    before = hashlib.sha256(source.read_bytes()).digest()
    shutil.copyfile(source, target)
    observation.require(
        hashlib.sha256(target.read_bytes()).digest() == before
        and hashlib.sha256(source.read_bytes()).digest() == before,
        "project copy differs",
    )


SCRIPT = r"""
import math
import traceback
from pathlib import Path
from typing import Any

def replay():
    expected = json.loads(Path(WORK, "expected.json").read_text(encoding="utf-8"))
    diagnostics = {"comparisons": {}, "old_handles": {}}
    compared = 0
    equal = 0
    refused = 0
    marks = set()
    _TRACE["start"]()
    try:
        _TRACE["mark"]("bookkeeping")
        P = uzpainter.project
        P.open(WORK + "/captured.uzp")

        def fresh():
            hosts = ls.get_root_layer_nodes(ts.get_active_stack())
            if len(hosts) != 1 or len(hosts[0].content_effects()) != 1:
                raise RuntimeError("unexpected observation graph")
            return hosts[0].content_effects()[0].get_source()

        def read(handle, getter):
            if getter == "get_parameters":
                return handle.get_parameters()
            if getter == "image_outputs":
                # Explicitly call the same native getter so monitoring sees its C_RETURN.
                value = handle.image_outputs if FACADE else type(handle).image_outputs.fget(handle)
                return list(value)
            rid = handle.resource_id if FACADE else handle.resource_id()
            return {"url": rid.url(), "context": rid.context,
                    "name": rid.name, "version": rid.version}

        original = fresh()
        for round_, condition in enumerate(("same_session", "after_save_reopen"), 1):
            if round_ == 2:
                P.save()
                P.close()
                P.open(WORK + "/captured.uzp")
                for getter in GETTERS:
                    try:
                        read(original, getter)
                        diagnostics["old_handles"][getter] = "unexpected success"
                    except Exception as error:
                        diagnostics["old_handles"][getter] = {
                            "type": type(error).__name__, "message": str(error)}
                        refused += type(error).__name__ == "UnsupportedProcedural"
            handle = original if round_ == 1 else fresh()
            for getter in GETTERS:
                mark = "r" + str(round_) + "/" + expected["outputs"][getter]
                wanted = expected["readbacks"][condition][getter]
                _TRACE["mark"](mark)
                try:
                    actual = read(handle, getter)
                except Exception as error:
                    diagnostics["comparisons"][mark] = {
                        "error": type(error).__name__, "message": str(error)}
                else:
                    same = typed_json(actual) == typed_json(wanted)
                    compared += 1
                    equal += same
                    marks.add(mark)
                    if not same:
                        diagnostics["comparisons"][mark] = {"expected": wanted, "actual": actual}
                finally:
                    _TRACE["mark"]("bookkeeping")
        P.close()
    finally:
        trace = _TRACE["stop"]()
    selected = {mark: trace.get(mark, []) for mark in sorted(marks)}
    traced = all(mark in trace and bool(trace[mark]) for mark in marks)
    success = compared == equal == len(marks) == 6 and refused == 3 and traced
    private = {"receipt_sha256": expected["receipt_sha256"], "api": API,
               "status": "equal" if success else "different", "compared": compared,
               "equal": equal, "old_handles_refused": refused, "trace": selected}
    if not success:
        private["diagnostics"] = diagnostics
    Path(WORK, "private-replay-report.json").write_text(
        json.dumps(private, ensure_ascii=True), encoding="utf-8")
    return {"status": private["status"], "compared": compared, "equal": equal,
            "old_handles_refused": refused, "traced_outputs": len(selected)}

try:
    result = replay()
except BaseException:
    try:
        Path(WORK, "private-replay-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
    except OSError:
        pass
    result = {"status": "failed"}
"""


@pytest.mark.parametrize("api", ["run", "facade"])
def test_recorded_filter_control_replays_exactly(
    api: str, request: pytest.FixtureRequest, tmp_path: Path
) -> None:
    configured = os.environ.get("UZP_FILTER_OBSERVATION_PROJECT")
    if not configured:
        pytest.skip("oracle_unavailable: private Filter observation project not configured")
    problem = False
    work: Path | None = None
    try:
        work = ensure_outside_repository(tmp_path)
        prepare(work, configured)
        executable: Path = request.getfixturevalue("pyapi_runner")
        execute: Run = runner(
            executable,
            work,
            FACADE_PRELUDE if api == "facade" else PRELUDE,
            private_diagnostics=work,
        )
        codec = "\n".join(
            inspect.getsource(function)
            for function in (
                observation.ImportRefused,
                observation.require,
                canonical_json,
                observation.typed_json,
            )
        )
        body = (
            "import math\nfrom typing import Any\n"
            + codec
            + f"\nAPI = {api!r}\nFACADE = {api == 'facade'!r}\nGETTERS = {GETTERS!r}\n"
            + "_TRACE = {'__name__': 'uzp_capability_trace'}\n"
            + f"exec(compile({SOURCE!r}, 'capability_trace.py', 'exec'), _TRACE)\n"
            + SCRIPT
        )
        report = execute(body)
        observation.write_private(work / "private-runner-report.json", report)
        problem = report.get("status") != "ok" or report.get("result") != {
            "status": "equal",
            "compared": 6,
            "equal": 6,
            "old_handles_refused": 3,
            "traced_outputs": 6,
        }
    except Exception:
        problem = True
        if work is not None:
            with suppress(OSError):
                (work / "private-preparation-error.txt").write_text(
                    traceback.format_exc(), encoding="utf-8"
                )
    if problem:
        pytest.fail(
            "private Filter control replay failed; inspect private diagnostics", pytrace=False
        )
    print("Filter control fidelity: 6/6 outputs equal; 3/3 old handles refused")
