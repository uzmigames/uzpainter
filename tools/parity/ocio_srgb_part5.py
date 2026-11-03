r"""Decision 202 part 5: Painter's OCIO decode of the pinned Tunic v10 stack's BaseColor components.

    python -m tools.parity.ocio_srgb_part5 request --assets-root <Assets3D> [--check]
    python -m tools.parity.ocio_srgb_part5 qualify --assets-root <Assets3D> [--pairs-out <file>]

The UzmiGames Tunic v10 stack (`tunic-stack` of `phase2/tier1/tunic-v10-current`, SHA-256
`STACK_SHA256`) sets 66 sRGB BaseColor components, 50 distinct float32 values. Decision 202's
table (`python/uzpainter_facade/ocio_srgb.py`, 449 entries) holds one of them;
`python::SyncStack` refuses the other 49 under OCIO. This module requests and qualifies the
readback that settles them, in the decision-202 family
(`tier0/api-probes/phase1-srgb-uniform-decode-ocio-part1..4`).

**The frozen domain.** The 449-entry baseline (`BASELINE_SHA256`, every pair), the 50 inputs
(`DOMAIN_SHA256`), the control among them (`CONTROL_SHA256`) and the 49 others (`NEW_SHA256`)
are pinned by digest, so the request and the qualification stay checkable once the 49 pairs
join the table: the baseline is the table without the 49 new inputs, and it must be those 449
pairs exactly. Digests are of float32 bits; no value is printed.

- **`request`** writes `phase1-srgb-uniform-decode-ocio-part5`, a Tier 0 API probe of part 4's
  recipe (Session O; `set_source(BaseColor, Color(x, x, x, sRGB))` on one fill, each read back
  through `get_source`, in the first session and after save/reopen, with the BaseColor export).
  It sets one grey per distinct float32 component of the stack, in stack order (layer, then
  component), each at its first occurrence. The stack is a hash-pinned Assets3D input; each
  colour is a `color_from` reference `[input, layer, component]` the recorder resolves from the
  pinned bytes (`probes.check_color_from`), so the request holds no colour value.
- **`qualify`** checks the admitted golden and derives the pairs, on one verified byte snapshot
  of each file (`OracleStore.load` with the size the manifest names; the stack by its pin):
  - the golden resolves in the current envelope and its manifest equals the regenerated request;
  - its private record passes `record_problems` (the full private schema), is a Tier 0 record of
    that golden whose key pins the same instruction sequence, inputs and the current Painter
    build, and whose environment is the current envelope's OCIO identity
    (`envelope.ocio.ocio_reference_state`);
  - it holds `r1` (same session) and `r2` (after save/reopen) with unique output ids; each set
    and readback output is the requested call with the requested arguments, without a raise;
    every readback is a grey of finite float32 components, bit-identical in `r1` and `r2`;
  - the mapping has one working value per input, the domain is `DOMAIN_SHA256`, the control
    equals the baseline, and a new input the table already holds equals it.
  The Tier 1 supplement `SUPPLEMENT_SHA256` (the Tunic current round's state capture, kept
  private and never admitted) is a cross-check only: under the same OCIO identity, its
  `get_color().working` of every fill, joined to the stack through the sync report's uids,
  must give the same value for all 50 inputs in `r1` and `r2`. Only then are the 49 pairs
  derived; `--pairs-out` writes them to a private file outside the repository. Nothing here
  changes the table.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.parity import ocio_srgb_table
from tools.parity.envelope.ocio import (
    OCIO_REFERENCE,
    named_ocio,
    ocio_identities,
    ocio_reference_state,
)
from tools.parity.envelope.registry import current_envelope, manifest_root
from tools.parity.recorder.job import canonical_json, pinned_assets3d_file, sha256_bytes
from tools.parity.recorder.output import ensure_outside_repository
from tools.parity.recorder.probes import (
    COLOR_FROM,
    PROBE_FLAG,
    RECIPE_JSON,
    color_from_component,
    pinned_document,
)
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT, load_json, record_problems
from tools.parity.store.store import OracleStore, locate
from tools.parity.verdict import resolve_golden

FAMILY = "tier0/api-probes/phase1-srgb-uniform-decode-ocio"
GOLDEN_ID = f"{FAMILY}-part5"
TEMPLATE_ID = f"{FAMILY}-part4"
TUNIC_REQUEST = "phase2/tier1/tunic-v10-current.json"
STACK_INPUT = "tunic-stack"
STACK_SHA256 = "a5bc5613f9507c184e1b6df29c0d5e59b9c87dd812bd04db5695847f963a3650"
SUPPLEMENT_GOLDEN = "phase2/tier1/tunic-v10-current"
SUPPLEMENT_SHA256 = "7663d8ac374637d40a88c7b694a5b6055103f0a354f51a74b254ab5e01aca1df"
SUPPLEMENT_SIZE = 78168
BASELINE_ENTRIES = 449
BASELINE_SHA256 = "c21d979c756e19da64ee0c27effd5666bf540e00abdcf565fd35c81dccf4c34d"
DOMAIN_INPUTS, NEW, CONTROLS = 50, 49, 1
DOMAIN_SHA256 = "230362586d25182885ef1118e2e2e2fbd669cf4153d0642229775c44ee63cf06"
CONTROL_SHA256 = "d99e58435243d9fef9c88273b8d553b4fba4d0baf8009d29eae74fa99e0d9f57"
NEW_SHA256 = "09773c62c99d1169ec5460924c97d3cb7430e2d0225584e3915614336319365c"
SET_SOURCE = "substance_painter.layerstack.FillLayerNode.set_source"
GET_SOURCE = "substance_painter.layerstack.FillLayerNode.get_source"
API_READBACK = "api_readback"


def f32_bits(value: float) -> int:
    """The bits of `value` rounded to float32 (the native table's key, decision 212)."""
    return int(struct.unpack("<I", struct.pack("<f", value))[0])


def exact_f32_bits(value: Any, where: str) -> int:
    """The bits of a finite value that must already be a float32 (a Painter readback)."""
    if type(value) is not float or not math.isfinite(value):
        raise RecorderError(f"{where}: not a finite number")
    bits = f32_bits(value)
    if struct.unpack("<f", struct.pack("<I", bits))[0] != value:
        raise RecorderError(f"{where}: not a float32 value")
    return bits


def keys_digest(keys: Iterable[int]) -> str:
    return hashlib.sha256(b"".join(struct.pack("<I", k) for k in sorted(keys))).hexdigest()


def pairs_digest(pairs: dict[int, int]) -> str:
    rows = (struct.pack("<II", k, pairs[k]) for k in sorted(pairs))
    return hashlib.sha256(b"".join(rows)).hexdigest()


@dataclass(frozen=True)
class Reference:
    """One distinct float32 component of the stack, at its first occurrence."""

    layer: int
    component: int
    key: int


@dataclass(frozen=True)
class Domain:
    """The frozen split of the 50 inputs against the 449-entry baseline."""

    keys: frozenset[int]
    control: frozenset[int]
    new: frozenset[int]
    baseline: dict[int, int]


def references(document: Any) -> list[Reference]:
    """Every distinct float32 component of the stack's uniform `base` colours, in stack order,
    resolved as the recorder resolves a `color_from` reference."""
    layers = document.get("layers") if isinstance(document, dict) else None
    if not isinstance(layers, list):
        raise RecorderError("the stack has no layer list")
    kinds, documents = {STACK_INPUT: RECIPE_JSON}, {STACK_INPUT: document}
    found: dict[int, Reference] = {}
    for index, layer in enumerate(layers):
        if isinstance(layer, dict) and "base_tex" in layer:
            continue
        for component in range(3):
            value = color_from_component([STACK_INPUT, index, component], kinds, documents)
            key = f32_bits(value)
            found.setdefault(key, Reference(index, component, key))
    return list(found.values())


def domain(keys: Iterable[int], table: dict[int, int]) -> Domain:
    """The inputs split by the frozen digests; the table without the new inputs must be the
    449-entry baseline exactly (before or after the 49 pairs join it)."""
    inputs = frozenset(keys)
    if len(inputs) != DOMAIN_INPUTS or keys_digest(inputs) != DOMAIN_SHA256:
        raise RecorderError(f"the {len(inputs)} inputs are not the frozen domain")
    control = frozenset(k for k in inputs if keys_digest([k]) == CONTROL_SHA256)
    new = inputs - control
    if len(control) != CONTROLS or len(new) != NEW or keys_digest(new) != NEW_SHA256:
        raise RecorderError("the inputs do not split into the frozen control and new inputs")
    baseline = {k: v for k, v in table.items() if k not in new}
    if len(baseline) != BASELINE_ENTRIES or pairs_digest(baseline) != BASELINE_SHA256:
        raise RecorderError("the table without the new inputs is not the 449-entry baseline")
    if not control <= baseline.keys():
        raise RecorderError("the control is not in the baseline")
    return Domain(inputs, control, new, baseline)


def envelope_dir(repo_root: Path = REPO_ROOT) -> Path:
    return manifest_root(current_envelope(repo_root), repo_root).parent


def request_path(repo_root: Path = REPO_ROOT) -> Path:
    return envelope_dir(repo_root) / "requests" / f"{GOLDEN_ID}.json"


def tunic_request(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    request: dict[str, Any] = load_json(envelope_dir(repo_root) / "requests" / TUNIC_REQUEST)
    return request


def stack_item(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """The Tunic current round's pinned stack input, as its request names it."""
    items = [i for i in tunic_request(repo_root)["inputs"] if i["input_id"] == STACK_INPUT]
    if len(items) != 1 or items[0]["sha256"] != STACK_SHA256 or items[0]["kind"] != RECIPE_JSON:
        raise RecorderError(f"{TUNIC_REQUEST}: {STACK_INPUT} is not the pinned stack")
    return dict(items[0])


def build_request(
    refs: Sequence[Reference], item: dict[str, Any], template: dict[str, Any]
) -> dict[str, Any]:
    """Part 5 on part 4's manifest: the same create, fill, settings and export; one grey per
    reference."""
    steps = template["instruction_sequence"]["steps"]
    head = [s for s in steps if s["call"] not in (SET_SOURCE, GET_SOURCE)][:-1]
    export = steps[-1]
    fill = next(s["step"] for s in head if s["call"].endswith("insert_fill"))
    body: list[dict[str, Any]] = []
    for ref in refs:
        colour = [item["input_id"], ref.layer, ref.component]
        set_args = {"node_step": fill, "channel": "BaseColor", COLOR_FROM: colour}
        body.append({"call": SET_SOURCE, "args": set_args | {"color_space": "sRGB", "probe": True}})
        body.append({"call": GET_SOURCE, "args": {"node_step": fill, "channel": "BaseColor"}})
    numbered = [dict(s) for s in head] + body + [dict(export)]
    sequence = [
        {"step": number, "call": s["call"], "args": s["args"]}
        for number, s in enumerate(numbered, start=1)
    ]
    return {
        "schema": template["schema"],
        "record_class": "public_manifest",
        "golden_id": GOLDEN_ID,
        "tier": "0",
        "domain": FAMILY,
        "description": (
            "Part 5 of the OCIO twin of API probe P20-B (decisions 107, 190 and 202), recorded "
            "in a Session O project (Painter started with OCIO naming its substance config): "
            "set_source(BaseColor, Color(x, x, x, sRGB)) on one fill, each read back through "
            "get_source (its working-space colour), in the first session and after save/reopen, "
            f"with the BaseColor export, as parts 1-4. The {len(refs)} greys are the distinct "
            "float32 BaseColor components of the pinned UzmiGames Tunic v10 stack "
            f"(`{item['input_id']}`), in stack order: {NEW} that decision 202's table lacks and "
            f"{CONTROLS} it holds, as a control. Each colour is a `color_from` reference (layer "
            "index and component) the recorder resolves from the hash-pinned stack, so this "
            "manifest holds no colour value (tools/parity/ocio_srgb_part5.py)."
        ),
        "inputs": [*template["inputs"], item],
        "instruction_sequence": {
            "author": template["instruction_sequence"]["author"],
            "interface": template["instruction_sequence"]["interface"],
            "steps": sequence,
        },
        "applied_settings": template["applied_settings"],
        "expectations": [],
        "software": template["software"],
        "private_records": [],
    }


def request_text(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"


def current_template(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Part 4's admitted manifest in the current envelope."""
    resolved = resolve_golden(TEMPLATE_ID, repo_root)
    if resolved is None or resolved.stale:
        raise RecorderError(f"{TEMPLATE_ID} is not admitted in the current envelope")
    build = current_envelope(repo_root)["painter_build"]
    if resolved.manifest["software"]["painter"]["build_id"] != build:
        raise RecorderError(f"{TEMPLATE_ID} is not of the current build {build}")
    return dict(resolved.manifest)


def pinned_stack(assets_root: Path, repo_root: Path = REPO_ROOT) -> tuple[dict[str, Any], Any]:
    """The stack input and its document, parsed from one read of bytes checked against the pin."""
    item = stack_item(repo_root)
    path = pinned_assets3d_file(item, assets_root, locate())
    return item, pinned_document(path, item["sha256"])


def generated_request(item: dict[str, Any], document: Any, repo_root: Path) -> dict[str, Any]:
    refs = references(document)
    domain([r.key for r in refs], ocio_srgb_table.entries())
    return build_request(refs, item, current_template(repo_root))


def generate(assets_root: Path, repo_root: Path = REPO_ROOT) -> str:
    item, document = pinned_stack(assets_root, repo_root)
    return request_text(generated_request(item, document, repo_root))


# --- qualification -----------------------------------------------------------------------


def outputs(record: dict[str, Any], recording_id: str) -> dict[str, dict[str, Any]]:
    """One recording's outputs by id; a repeated id is refused."""
    found = [r for r in record["recordings"] if r["recording_id"] == recording_id]
    if len(found) != 1:
        raise RecorderError(f"the record has no single recording {recording_id}")
    by_id: dict[str, dict[str, Any]] = {}
    for output in found[0]["outputs"]:
        if output["output_id"] in by_id:
            raise RecorderError(f"{recording_id}: the output id {output['output_id']} repeats")
        by_id[output["output_id"]] = output
    return by_id


def expected_output(step: dict[str, Any], name: str) -> dict[str, Any]:
    """The readback fields the probe recorder writes for a manifest step (`probes.readback`)."""
    args = {k: v for k, v in step["args"].items() if k != PROBE_FLAG}
    return {
        "output_id": f"s{step['step']}/{name}",
        "kind": API_READBACK,
        "call": step["call"],
        "args": args,
    }


def record_pairs(manifest: dict[str, Any], record: dict[str, Any], document: Any) -> dict[int, int]:
    """Input bits to working bits of a part-5 record: every grey read back, r1 = r2."""
    conditions = {r["recording_id"]: r["condition"] for r in record["recordings"]}
    if len(record["recordings"]) != 2 or conditions != {
        "r1": "same_session",
        "r2": "after_save_reopen",
    }:
        raise RecorderError(f"the record's recordings are {conditions}, not r1 and r2")
    kinds = {i["input_id"]: i["kind"] for i in manifest["inputs"]}
    documents = {STACK_INPUT: document}
    steps = manifest["instruction_sequence"]["steps"]
    by_recording: dict[str, dict[int, int]] = {}
    for recording_id in ("r1", "r2"):
        found = outputs(record, recording_id)
        pairs: dict[int, int] = {}
        for index, step in enumerate(steps):
            if COLOR_FROM not in step["args"]:
                continue
            following = steps[index + 1] if index + 1 < len(steps) else None
            if step["call"] != SET_SOURCE or following is None or following["call"] != GET_SOURCE:
                raise RecorderError(f"step {step['step']} is not a set followed by its readback")
            for manifest_step, name in ((step, "set_source"), (following, "get_source")):
                want = expected_output(manifest_step, name)
                got = found.get(want["output_id"])
                if got is None or "raised" in got or {k: got.get(k) for k in want} != want:
                    raise RecorderError(f"{recording_id}: {want['output_id']} is not the request's")
            value = found[f"s{following['step']}/get_source"].get("value")
            working = value.get("uniform_color_working") if isinstance(value, dict) else None
            if not isinstance(working, list) or len(working) != 3:
                raise RecorderError(f"{recording_id}: step {following['step']} read no colour")
            where = f"{recording_id} step {following['step']}"
            bits = {exact_f32_bits(w, where) for w in working}
            if len(bits) != 1:
                raise RecorderError(f"{where}: the readback is no grey")
            key = f32_bits(color_from_component(step["args"][COLOR_FROM], kinds, documents))
            if key in pairs:
                raise RecorderError(f"{recording_id}: step {step['step']} sets an input twice")
            pairs[key] = bits.pop()
        by_recording[recording_id] = pairs
    if by_recording["r1"] != by_recording["r2"]:
        raise RecorderError("r1 and r2 differ")
    return by_recording["r1"]


def checked_mapping(pairs: dict[int, int], table: dict[int, int]) -> dict[int, int]:
    """The new pairs, when the inputs are the frozen domain, the control reproduces the
    baseline, and a new input the table already holds agrees with it."""
    split = domain(pairs, table)
    if any(split.baseline[k] != pairs[k] for k in split.control):
        raise RecorderError("the control does not reproduce the baseline")
    new = {k: pairs[k] for k in split.new}
    if any(k in table and table[k] != v for k, v in new.items()):
        raise RecorderError("the table already holds another value for a new input")
    return new


def fill_nodes(node: dict[str, Any], found: dict[int, dict[str, Any]]) -> None:
    if node.get("type") == "FillLayer" and "active_channels" in node:
        uid = int(node["uid"])
        if uid in found:
            raise RecorderError(f"the state lists the fill {uid} twice")
        found[uid] = node
    for field in ("sub_layers", "content_effects", "mask_effects"):
        children = node.get(field)
        for child in children if isinstance(children, list) else []:
            if isinstance(child, dict):
                fill_nodes(child, found)


def supplement_pairs(supplement: dict[str, Any], document: Any) -> dict[int, int]:
    """Input bits to working bits from the Tier 1 supplement: each stack layer's fill, found by
    the uid the sync reported, read through `get_source(BaseColor).get_color().working`."""
    report = outputs(supplement, "r1").get("script/s2")
    if report is None:
        raise RecorderError("the supplement has no sync report")
    uid_of: dict[str, int] = {}
    for layer in report["value"]["layers"]:
        if layer["id"] in uid_of:
            raise RecorderError("the sync report names a layer twice")
        uid_of[layer["id"]] = int(layer["uid"])
    kinds, documents = {STACK_INPUT: RECIPE_JSON}, {STACK_INPUT: document}
    by_recording: dict[str, dict[int, int]] = {}
    for recording_id in ("r1", "r2"):
        state = outputs(supplement, recording_id).get("create/state")
        if state is None:
            raise RecorderError(f"the supplement's {recording_id} has no state capture")
        fills: dict[int, dict[str, Any]] = {}
        for texture_set in state["value"]["texture_sets"].values():
            for stack_state in texture_set["stacks"].values():
                for node in stack_state["layers"]:
                    fill_nodes(node, fills)
        pairs: dict[int, int] = {}
        for index, layer in enumerate(document["layers"]):
            node = fills.get(uid_of.get(layer["id"], -1))
            if node is None or node["name"] != layer["name"]:
                raise RecorderError(f"the supplement's {recording_id} lacks a stack fill")
            source = (node["sources"].get("BaseColor") or {}).get("source") or {}
            working = source.get("uniform_color_working")
            if not isinstance(working, list) or len(working) != 3:
                raise RecorderError(f"the supplement's {recording_id} read no uniform colour")
            for c in range(3):
                key = f32_bits(color_from_component([STACK_INPUT, index, c], kinds, documents))
                value = exact_f32_bits(working[c], f"supplement {recording_id}")
                if pairs.setdefault(key, value) != value:
                    raise RecorderError("the supplement maps one input to two working values")
        by_recording[recording_id] = pairs
    if by_recording["r1"] != by_recording["r2"]:
        raise RecorderError("the supplement's r1 and r2 differ")
    return by_recording["r1"]


def loaded(store: OracleStore, sha256: str, size_bytes: int) -> dict[str, Any]:
    """A private record parsed from one read of bytes verified by hash and size."""
    data = store.load(sha256, size_bytes)
    if data is None:
        raise RecorderError(f"{sha256[:12]}: unavailable, or not of the pinned hash and size")
    record: dict[str, Any] = json.loads(data)
    return record


def golden_record(repo_root: Path, store: OracleStore) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved = resolve_golden(GOLDEN_ID, repo_root)
    if resolved is None or resolved.stale:
        raise RecorderError(f"{GOLDEN_ID} is not admitted in the current envelope")
    private = resolved.manifest["private_records"]
    refs = [r for r in private if r["kind"] == "private_oracle_record"]
    if len(refs) != 1:
        raise RecorderError(f"{GOLDEN_ID} names no single private record")
    return resolved.manifest, loaded(store, refs[0]["sha256"], refs[0]["size_bytes"])


def identity_problems(
    record: dict[str, Any],
    golden_id: str,
    sequence: dict[str, Any],
    inputs: list[dict[str, Any]],
    tier: str,
    build: str,
) -> list[str]:
    """What a record fails of its identity: the full private schema and its cross-field rules,
    the golden, tier, instruction sequence, inputs and the current Painter build."""
    problems = record_problems(record)
    if problems:
        return problems
    key = record["key"]
    pins = [{"input_id": i["input_id"], "sha256": i["sha256"]} for i in inputs]
    checks = (
        ("golden id", record["golden_id"] == golden_id),
        ("tier", record["tier"] == tier),
        (
            "instruction sequence",
            key["instruction_sequence_sha256"] == sha256_bytes(canonical_json(sequence)),
        ),
        ("inputs", key["inputs"] == pins),
        ("key build", key["painter_build"]["build_id"] == build),
        ("environment build", record["environment"]["painter_build"] == build),
    )
    return [what for what, ok in checks if not ok]


def check_ocio_identity(
    environments: Sequence[dict[str, Any]],
    configuration: str | None,
    repo_root: Path,
    store: OracleStore,
) -> None:
    """Every environment is the current envelope's OCIO identity for `configuration`."""
    if configuration is None:
        raise RecorderError("the golden names no OCIO configuration")
    anchors, refs = ocio_identities(current_envelope(repo_root), store, configuration, repo_root)
    for environment in environments:
        state, reason = ocio_reference_state(environment, anchors, refs, configuration)
        if state != OCIO_REFERENCE:
            raise RecorderError(f"not the current envelope's OCIO identity: {reason}")


def qualify(
    assets_root: Path, repo_root: Path = REPO_ROOT
) -> tuple[dict[int, int], dict[str, Any]]:
    """The 49 pairs of the admitted part 5, and a report of counts and hashes."""
    store = locate()
    if store is None:
        raise RecorderError("no private store on this machine")
    item, document = pinned_stack(assets_root, repo_root)
    manifest, record = golden_record(repo_root, store)
    expected = generated_request(item, document, repo_root)
    fields = ("golden_id", "tier", "domain", "inputs", "instruction_sequence", "applied_settings")
    if any(manifest[f] != expected[f] for f in fields):
        raise RecorderError(f"{GOLDEN_ID}: the admitted manifest is not the generated request")
    build = current_envelope(repo_root)["painter_build"]
    sequence, inputs = manifest["instruction_sequence"], manifest["inputs"]
    problems = identity_problems(record, GOLDEN_ID, sequence, inputs, "0", build)
    if problems:
        raise RecorderError(f"{GOLDEN_ID}: the record fails {', '.join(problems)}")
    if (record["key"]["project_settings"].get("colour_management") or {}).get("mode") != "ocio":
        raise RecorderError(f"{GOLDEN_ID}: the record is not of a Session O project")
    tunic = tunic_request(repo_root)
    supplement = loaded(store, SUPPLEMENT_SHA256, SUPPLEMENT_SIZE)
    problems = identity_problems(
        supplement, SUPPLEMENT_GOLDEN, tunic["instruction_sequence"], tunic["inputs"], "1", build
    )
    if problems:
        raise RecorderError(f"the supplement fails {', '.join(problems)}")
    configuration = named_ocio(manifest)
    if named_ocio(tunic) != configuration:
        raise RecorderError("the supplement's request names another OCIO configuration")
    check_ocio_identity(
        [record["environment"], supplement["environment"]], configuration, repo_root, store
    )
    pairs = record_pairs(manifest, record, document)
    new = checked_mapping(pairs, ocio_srgb_table.entries())
    if supplement_pairs(supplement, document) != pairs:
        raise RecorderError("the Tier 1 supplement disagrees with part 5")
    report = {
        "golden_id": GOLDEN_ID,
        "inputs": len(pairs),
        "new": len(new),
        "controls": len(pairs) - len(new),
        "supplement_agrees": len(pairs),
        "new_pairs_sha256": pairs_digest(new),
    }
    return new, report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.ocio_srgb_part5")
    commands = parser.add_subparsers(dest="command", required=True)
    request = commands.add_parser("request")
    request.add_argument("--assets-root", type=Path, required=True)
    request.add_argument("--check", action="store_true", help="exit 1 when the request differs")
    qualify_cmd = commands.add_parser("qualify")
    qualify_cmd.add_argument("--assets-root", type=Path, required=True)
    qualify_cmd.add_argument("--pairs-out", type=Path, help="a private file outside the repository")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.command == "request":
            text = generate(args.assets_root)
            path = request_path()
            if args.check:
                current = path.read_text(encoding="utf-8") if path.is_file() else None
                if current != text:
                    print(f"{path} differs from the generated request", file=sys.stderr)
                    return 1
                return 0
            path.write_text(text, encoding="utf-8", newline="\n")
            print(f"wrote {path.relative_to(REPO_ROOT).as_posix()}")
            return 0
        new, report = qualify(args.assets_root)
        if args.pairs_out is not None:
            out = ensure_outside_repository(args.pairs_out)
            rows = [[k, new[k]] for k in sorted(new)]
            text = json.dumps({"golden_id": GOLDEN_ID, "pairs_bits": rows}) + "\n"
            out.write_text(text, encoding="utf-8")
        print(json.dumps(report, sort_keys=True))
        return 0
    except RecorderError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
