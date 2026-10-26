"""Diagnostic source binding of an admitted fresh F capture to an admitted H capture (J1-J4).

Both sides come from real admissions in one oracle store: F through
`filter_context_validation.manifest_request` and `receipt` (admitted references by build, golden,
id, kind, hash and size; record and environment schema; current envelope; recorder pin; recipe
key) and `f_evidence_from_record` (closed trace and context frames); H through
`resolve_snapshot_capture` under the approved producer policy (complete admission, re-hashed
artifacts, the receipt the pinned native validator accepted). No caller-supplied value, report or
flag is trusted. The result is a value-free diagnostic: it is not a `VerifiedFilterContext` and
authorizes no import; effective settings stay unverified and acceptance blocked.

The F context leaves and the H receipt use different public serializers of the same documented
getters, related exactly as follows (anything else refuses):

- `SourceSubstance.resource_id`: F `{"resource_id": {"resource": {context, name, version}},
  "url": url()}` (painter_probes `substance_read` + `describe(ResourceID)`), H `{url: url(),
  context, name, version}` (uzpainter_snapshot `readback`): the same four attributes.
- `get_parameters`: F `describe(dict)` keeps int, float and str values unchanged; H is the raw map.
  Both are already in the /3 scalar domain (decision 361: int64, finite double, string): the F
  context contract refuses any other source parameter value and the native validator refused it in
  H at admission. They are compared typed (int vs double vs signed zero distinct).
- `image_outputs`, `image_inputs`, `active_output`: lists of strings and a string on both sides.
- `resolution`: F `{mode: describe(mode), value: describe(value), value_kind, log2_offset}`, H
  `{mode: mode.name, value: list(value), log2_offset}`. `describe` of an enum is its name and of a
  tuple or list of integers the same integer list, so `{mode, value, log2_offset}` must be equal
  when F's `value_kind` is `tuple` or `list` (the container H's `list()` erased); `value_kind` is
  kept in the diagnostic, and `other` refuses: no relation is demonstrated for it.
"""

from __future__ import annotations

import hashlib
from typing import Any

from tools.parity import filter_context_validation as validation
from tools.parity.filter_context_contract import MISSING_SETTINGS, SOURCE, typed
from tools.parity.recorder.filter_context_run import f_evidence_from_record
from tools.parity.store.snapshot_capture import resolve_snapshot_capture
from tools.parity.store.snapshot_contract import parse_document
from tools.parity.store.store import OracleStore, Status

SCHEMA = "uzpainter/parity/filter-source-binding/1"
HOST_SOURCE = {"role": "host", "source": True}
SOURCE_FRAMES = ("after-setup6", "pre16-r1", "after-reopen", "pre16-r2")
PRE16 = {"r1": "pre16-r1", "r2": "pre16-r2"}


class SourceBindingRefused(ValueError):
    """A value-free reason code; nothing about the observed values is disclosed. A registry drift
    refusal names the code of the refusal it superseded (`original`), if any."""

    def __init__(self, code: str, original: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.original = original


def require(condition: bool, code: str) -> None:
    if not condition:
        raise SourceBindingRefused(code)


def _same(a: Any, b: Any) -> bool:
    return typed(a) == typed(b)


def _host_leaves(frame: dict[str, Any]) -> dict[str, Any]:
    """The host source leaves of a frame by getter, each present once and not raised."""
    leaves: dict[str, Any] = {}
    for output in frame["outputs"]:
        if output["call"].startswith(SOURCE) and _same(
            output["args"], {"selector": HOST_SOURCE, "parameters": {}}
        ):
            getter = output["call"][len(SOURCE) :]
            require(getter not in leaves and "raised" not in output, "F_CONTEXT_INVALID")
            leaves[getter] = output["value"]
    return leaves


def _f_record(store: OracleStore, f_manifest: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        manifest = validation.decode(f_manifest)
        authored = validation.manifest_request(manifest)
        record = validation.receipt(manifest, authored, store)[0]
    except (ValueError, KeyError, TypeError, OSError):
        raise SourceBindingRefused("F_RECORD_UNBOUND") from None
    return manifest, record


def _h_receipt(
    store: OracleStore, capture: str, policy_sha256: str, policy_revision: int
) -> tuple[dict[str, Any], bytes]:
    resolution = resolve_snapshot_capture(
        store,
        capture,
        approved_policy_sha256=policy_sha256,
        approved_policy_revision=policy_revision,
    )
    require(
        resolution.status is Status.AVAILABLE and resolution.document is not None,
        "H_ADMISSION_UNAVAILABLE",
    )
    assert resolution.document is not None
    ref = resolution.document["artifacts"]["receipt"]
    data = store.load(ref["sha256"], ref["size_bytes"])
    require(data is not None, "H_ADMISSION_UNAVAILABLE")
    assert data is not None
    return resolution.document, data


def bind_filter_source(
    *,
    store: OracleStore,
    f_manifest: bytes,
    h_capture_id: str,
    approved_policy_sha256: str,
    approved_policy_revision: int,
) -> dict[str, Any]:
    """J1-J4 between the admitted F capture `f_manifest` names and the admitted H capture
    `h_capture_id`; returns the value-free diagnostic or raises `SourceBindingRefused`.

    The envelope registry is read before and after the whole binding: a drift (or an unreadable
    registry) refuses `REGISTRY_DRIFT` whether the binding succeeded or refused, superseding any
    result; the superseded refusal stays its cause and its code `original`. Failures other than a
    refusal (I/O included) refuse `BINDING_UNAVAILABLE` without their message or cause."""
    try:
        before = validation.registry_snapshot()
    except Exception:
        raise SourceBindingRefused("REGISTRY_DRIFT") from None
    superseded: BaseException | None = None
    try:
        return _bind(
            store, f_manifest, h_capture_id, approved_policy_sha256, approved_policy_revision
        )
    except SourceBindingRefused as error:
        superseded = error
        raise
    except Exception:
        # Any other failure (I/O included) refuses with a code only: no message or path escapes.
        superseded = SourceBindingRefused("BINDING_UNAVAILABLE")
        raise superseded from None
    finally:
        try:
            drifted = validation.registry_snapshot() != before
        except Exception:
            drifted = True
        if drifted:
            original = superseded.code if isinstance(superseded, SourceBindingRefused) else None
            raise SourceBindingRefused("REGISTRY_DRIFT", original) from superseded


def _bind(
    store: OracleStore,
    f_manifest: bytes,
    h_capture_id: str,
    approved_policy_sha256: str,
    approved_policy_revision: int,
) -> dict[str, Any]:
    manifest, record = _f_record(store, f_manifest)
    recipe = manifest["instruction_sequence"]
    try:
        evidence = f_evidence_from_record(record, recipe)
    except (ValueError, KeyError, TypeError, OSError):
        raise SourceBindingRefused("F_CONTEXT_INVALID") from None
    frames = {frame["boundary"]: _host_leaves(frame) for frame in evidence.contexts}
    require(
        all(set(frames[b]) >= {"get_parameters", "resource_id"} for b in SOURCE_FRAMES),
        "F_CONTEXT_INVALID",
    )

    document, receipt_bytes = _h_receipt(
        store, h_capture_id, approved_policy_sha256, approved_policy_revision
    )
    try:
        receipt = parse_document(receipt_bytes)
        sources = receipt["readback"]["sources"]
        require(len(sources) == 2 and _same(sources[0], sources[1]), "H_ADMISSION_UNAVAILABLE")
        source = sources[0]
        identity = source["resource_id"]
        require(
            type(identity) is dict and set(identity) == {"url", "context", "name", "version"},
            "H_ADMISSION_UNAVAILABLE",
        )
    except (ValueError, KeyError, TypeError, OSError):
        raise SourceBindingRefused("H_ADMISSION_UNAVAILABLE") from None

    # J1: recipe A step 5, the H receipt and every F frame name one complete source identity.
    steps = {step["step"]: step for step in recipe["steps"]}
    url = steps[5]["args"].get("resource_url")
    require(url == receipt["resource"] == identity["url"], "J1_SOURCE_IDENTITY")
    expected_f = {
        "resource_id": {"resource": {k: identity[k] for k in ("context", "name", "version")}},
        "url": identity["url"],
    }
    require(
        all(_same(frames[b]["resource_id"], expected_f) for b in SOURCE_FRAMES),
        "J1_SOURCE_IDENTITY",
    )

    # J2: the pre16 effective parameters of both rounds, typed (int, double and signed zero
    # distinct). Both maps are already in the /3 scalar domain: the F context contract refuses any
    # other source parameter value, and the native validator refused it in H at admission.
    for boundary in PRE16.values():
        require(
            _same(frames[boundary]["get_parameters"], source["parameters"]), "J2_PRE16_PARAMETERS"
        )

    # J3: the pre16 state is the one the probes left. Recipe A writes the first Togglebutton with
    # int 0 at step 12 and bool False at step 14, reading get_parameters at 13 and 15. The bool
    # write probes whether Painter accepts a bool (the contract keeps refusals from step 7 on as
    # observations), so it may succeed or refuse with TypeError; either way the state must not
    # change: the int write succeeded and steps 13, 15 and the pre16 boundary read one typed map.
    zero, zero_read, off, off_read = (steps.get(n, {}) for n in (12, 13, 14, 15))
    require(
        zero.get("call") == off.get("call") == SOURCE + "set_parameters"
        and type(zero.get("args", {}).get("toggle")) is int
        and zero["args"]["toggle"] == 0
        and off.get("args", {}).get("toggle") is False
        and zero_read.get("call") == off_read.get("call") == SOURCE + "get_parameters",
        "J3_PRE16_STATE",
    )
    bool_writes: list[dict[str, Any]] = []
    for recording in record["recordings"]:
        outputs = {o["output_id"]: o for o in recording["outputs"]}
        written = outputs.get("s12/set_parameters")
        require(written is not None and "raised" not in written, "J3_INT_WRITE")
        toggled = outputs.get("s14/set_parameters")
        require(toggled is not None, "J3_BOOL_WRITE")
        assert toggled is not None
        refusal = toggled.get("raised")
        require(refusal is None or refusal.get("type") == "TypeError", "J3_BOOL_WRITE")
        reads = [outputs.get("s13/get_parameters"), outputs.get("s15/get_parameters")]
        pre16 = frames[PRE16[recording["recording_id"]]]["get_parameters"]
        require(
            all(r is not None and "raised" not in r and _same(r["value"], pre16) for r in reads),
            "J3_PRE16_STATE",
        )
        bool_writes.append(
            {"outcome": "succeeded"}
            if refusal is None
            else {"outcome": "refused", "type": "TypeError"}
        )

    # J4: outputs, inputs, active output and resolution of both pre16 states.
    h_resolution = source["resolution"]
    containers = []
    for boundary in PRE16.values():
        leaves = frames[boundary]
        f_resolution = leaves.get("resolution")
        require(
            _same(leaves.get("image_outputs"), source["outputs"])
            and _same(leaves.get("image_inputs"), source["inputs"])
            and leaves.get("image_inputs") == []
            and _same(leaves.get("active_output"), source["active_output"])
            and type(f_resolution) is dict
            and set(f_resolution) == {"mode", "value", "value_kind", "log2_offset"}
            and f_resolution["value_kind"] in ("tuple", "list")
            and _same({k: f_resolution[k] for k in ("mode", "value", "log2_offset")}, h_resolution),
            "J4_OUTPUTS",
        )
        assert isinstance(f_resolution, dict)
        containers.append(f_resolution["value_kind"])

    record_ref = next(
        r for r in manifest["private_records"] if r["kind"] == "private_oracle_record"
    )
    validation_fields = document["validation"]
    return {
        "schema": SCHEMA,
        "status": "source_bound",
        "h": {
            "capture_id": document["capture_id"],
            "receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
            "signature_sha256": validation_fields["signature_sha256"],
            "capture_context_sha256": validation_fields["capture_context_sha256"],
            "validator_code_sha256": validation_fields["validator_code_sha256"],
            "validator_binary_sha256": validation_fields["validator_binary_sha256"],
        },
        "f": {
            "manifest_sha256": hashlib.sha256(f_manifest).hexdigest(),
            "record_sha256": record_ref["sha256"],
            "record_size": record_ref["size_bytes"],
            "resolution_value_kinds": containers,
            "toggle_bool_writes": bool_writes,
        },
        "joins": {"J1": True, "J2": True, "J3": True, "J4": True},
        "acceptance": {
            "importer": "not_authorized",
            "missing_effective_settings": list(MISSING_SETTINGS),
        },
    }
