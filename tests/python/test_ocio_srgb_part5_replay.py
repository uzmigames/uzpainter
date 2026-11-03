"""Decision 202 part 5, replayed (decisions 202, 212 and 240): on a real OCIO project with Painter's
substance config, the facade setter and the native `sync_stack` store, for each of the 50 inputs of
the admitted `tier0/api-probes/phase1-srgb-uniform-decode-ocio-part5`, the working value Painter
read back (its r1 and r2 readbacks, equal), bit for bit, control included; an authored component
outside the table's 498 entries is refused with nothing committed.

The expected values come from the admitted private record (`ocio_srgb_part5.record_pairs`), not
from the table, after `qualify`'s identity, envelope and request guards on the same loaded record
and stack document (the Tier 1 supplement cross-check stays `qualify`'s own). They are private
(docs/licensing-and-clean-room.md, parity/CONTRACT.md §6.4): the replay script compares bits
itself and reports counts and booleans only; transport diagnostics go to the private store's
folder (`private_facade`), a failed script reports its error type only, and no assertion compares
containers of values. The test skips where the private store, the record or the pinned stack is
absent.
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
from pathlib import Path
from typing import Any

import pytest

from tests.python.conftest import REPO_ROOT, Run
from tools.parity import ocio_srgb_part5 as part5
from tools.parity import ocio_srgb_table
from tools.parity.envelope.ocio import named_ocio
from tools.parity.envelope.registry import current_envelope
from tools.parity.store.store import locate
from tools.parity.verdict import resolve_golden

SUBSTANCE = "15059d4b4e52893863f2063dfccb3902d182b522ad233564db32a5e30a43b7f4"
# The admitted part 5 (commit dfd21b7b) and `ocio_srgb_part5 qualify`'s digest of its 49 new pairs.
MANIFEST_SHA256 = "9d197ad77a2b727d693f6e8c88b2265fb7285e9209b7e87a50f0c7e09f0ceb45"
RECORD_SHA256 = "a131bfddfc59bfce6ce7426c348934e7c28bdcdac157ff943dde16e6a4ce093d"
QUALIFIED_SHA256 = "4104b941aabf8ef3adbb97ed14f7510c5f4d5c47a4e55abeca8003eec06e17f5"
# Authored, and asserted outside the 498 entries below.
UNRECORDED = 0.987654321

REPLAY = """
import base64, struct
PAYLOAD = json.loads(base64.b64decode("__PAYLOAD__").decode("utf-8"))
PAIRS, BAD, SUBSTANCE = PAYLOAD["pairs"], PAYLOAD["bad"], PAYLOAD["substance"]
nls, nct, nproject = uzpainter.layerstack, uzpainter.textureset.ChannelType, uzpainter.project


def bits(values):
    out = []
    for v in values:
        b = struct.unpack("<I", struct.pack("<f", v))[0]
        out.append(b if struct.unpack("<f", struct.pack("<I", b))[0] == v else None)
    return out


def matches(values, want):
    return len(values) == 3 and bits(values) == [want] * 3


def ocio_project():
    nproject.create(PLANE, nproject.Settings(default_texture_resolution=256,
                                             ocio_config_hash=SUBSTANCE))
    declared = uzpainter.colormanagement.get_color_management()
    return declared["mode"] == "ocio" and declared["config_hash"] == SUBSTANCE


def refused(error):
    return (error is not None and error.startswith("NotYetSupported")
            and ("sRGB component " + repr(BAD) + " is not recorded") in error)


# Facade route: the setter, then a fresh node and source each time.
facade_ocio = ocio_project()
fill = ls.insert_fill(top(ts.get_active_stack()))


def facade_working():
    return list(ls.get_node_by_uid(fill.uid()).get_source(CT.BaseColor).get_color().working)


facade_raised = facade_matches = 0
for x, want in PAIRS:
    if raises(fill.set_source, CT.BaseColor, cm.Color(x, x, x, cm.GenericColorSpace.sRGB)):
        facade_raised += 1
        continue
    facade_matches += matches(facade_working(), want)
before, revision = bits(facade_working()), nproject.revision()
first, second = PAIRS[0][0], PAIRS[1][0]
error = raises(fill.set_source, CT.BaseColor,
               cm.Color(first, second, BAD, cm.GenericColorSpace.sRGB))
facade_refusal = {"refused": refused(error), "revision": nproject.revision() == revision,
                  "source": bits(facade_working()) == before}
nproject.close()

# Native route: one sync of a grey per input, read from the sync report's uids.
native_ocio = ocio_project()
native_stack = uzpainter.textureset.get_active_stack()


def document(colours):
    layers = [{"id": "L%02d" % i, "group": "g", "name": "c%02d" % i, "base": rgb}
              for i, rgb in enumerate(colours)]
    return {"title": "T", "groups": [{"key": "g", "name": "G", "mask": None}], "layers": layers}


r = nls.sync_stack(document([[x, x, x] for x, _ in PAIRS]), WORK)
sync = r.returned["sync"]
uid_of = {layer["name"]: layer["uid"] for layer in sync["layers"]}
in_order = [uid_of.get("c%02d" % i) for i in range(len(PAIRS))]


def native_colour(uid):
    colour = nls.get_node_by_uid(uid).get_source(nct.BaseColor).get_color()
    return list(colour.value_raw), colour.color_space


native_matches = native_working = 0
for uid, (_, want) in zip(in_order, PAIRS):
    values, space = native_colour(uid)
    native_matches += matches(values, want)
    native_working += space == "Working"


def tree(nodes):
    return [[n.uid(), n.get_name(), type(n).__name__,
             tree(n.sub_layers()) if hasattr(n, "sub_layers") else []] for n in nodes]


def state():
    return tree(nls.get_root_layer_nodes(native_stack)), [
        [bits(native_colour(uid)[0]), native_colour(uid)[1]] for uid in in_order]


before, revision = state(), nproject.revision()
rotated = [[x, x, x] for x, _ in PAIRS[1:] + PAIRS[:1]]
rotated[-1][2] = BAD
error = raises(nls.sync_stack, document(rotated), WORK)
native_refusal = {"refused": refused(error), "revision": nproject.revision() == revision,
                  "state": state() == before}
nproject.close()

result = {
    "facade": {"ocio": facade_ocio, "raised": facade_raised, "matches": facade_matches,
               "refusal": facade_refusal},
    "native": {"ocio": native_ocio, "status": r.status, "layers": len(sync["layers"]),
               "resolved": sum(uid is not None for uid in in_order),
               "matches": native_matches, "working": native_working,
               "refusal": native_refusal},
}
"""


def f32(bits: int) -> float:
    return float(struct.unpack("<f", struct.pack("<I", bits))[0])


def admitted_pairs(assets_root: Path) -> dict[int, int]:
    """Input bits to working bits of the admitted part-5 readbacks (r1 = r2), after the guards of
    `ocio_srgb_part5.qualify` on one snapshot: the pinned manifest and record, each read once and
    verified by hash; the request regenerated from the same pinned stack document; the record's
    identity and the current envelope's OCIO identity; the domain, the control and the qualified
    digest. Skips where the private store, the record or the pinned stack is absent."""
    store = locate()
    if store is None:
        pytest.skip("no private store on this machine: the part-5 readbacks are private")
    for sha256 in (RECORD_SHA256, part5.STACK_SHA256):
        if not store.blob_path(sha256).is_file():
            pytest.skip(f"the private store holds no blob {sha256[:12]}")
    resolved = resolve_golden(part5.GOLDEN_ID, REPO_ROOT)
    assert resolved is not None and not resolved.stale, f"{part5.GOLDEN_ID} is not admitted"
    data = resolved.manifest_path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == MANIFEST_SHA256
    manifest: dict[str, Any] = json.loads(data)
    assert manifest == resolved.manifest
    records = [r for r in manifest["private_records"] if r["kind"] == "private_oracle_record"]
    assert len(records) == 1 and records[0]["sha256"] == RECORD_SHA256
    record = part5.loaded(store, RECORD_SHA256, records[0]["size_bytes"])
    item, document = part5.pinned_stack(assets_root)
    expected = part5.generated_request(item, document, REPO_ROOT)
    fields = ("golden_id", "tier", "domain", "inputs", "instruction_sequence", "applied_settings")
    assert [f for f in fields if manifest[f] != expected[f]] == []
    build = current_envelope(REPO_ROOT)["painter_build"]
    sequence, inputs = manifest["instruction_sequence"], manifest["inputs"]
    assert part5.identity_problems(record, part5.GOLDEN_ID, sequence, inputs, "0", build) == []
    settings = record["key"]["project_settings"]
    assert (settings.get("colour_management") or {}).get("mode") == "ocio"
    part5.check_ocio_identity([record["environment"]], named_ocio(manifest), REPO_ROOT, store)
    pairs = part5.record_pairs(manifest, record, document)
    new = part5.checked_mapping(pairs, ocio_srgb_table.entries())
    assert part5.pairs_digest(new) == QUALIFIED_SHA256
    return pairs


def replayed(private_facade: Run, pairs: dict[int, int]) -> Any:
    payload = {
        "pairs": [[f32(k), pairs[k]] for k in sorted(pairs)],
        "bad": UNRECORDED,
        "substance": SUBSTANCE,
    }
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    report = private_facade(REPLAY.replace("__PAYLOAD__", encoded))
    if report["status"] != "ok":
        kind = (report.get("error") or {}).get("type", "unknown")
        pytest.fail(f"the replay script failed ({kind}); details withheld", pytrace=False)
    return report["result"]


def test_part5_readbacks_replay_through_the_facade_and_native_routes(
    private_facade: Run, tmp_path: Path
) -> None:
    assert ocio_srgb_table._bits(UNRECORDED) not in ocio_srgb_table.entries()
    pairs = admitted_pairs(tmp_path)
    n = part5.DOMAIN_INPUTS
    assert len(pairs) == n
    result = replayed(private_facade, pairs)
    facade, native = result["facade"], result["native"]
    assert facade["ocio"] is True and native["ocio"] is True
    assert facade["raised"] == 0
    assert facade["matches"] == n
    assert facade["refusal"] == {"refused": True, "revision": True, "source": True}
    assert native["status"] == "committed"
    assert native["layers"] == native["resolved"] == n
    assert native["matches"] == n
    assert native["working"] == n
    assert native["refusal"] == {"refused": True, "revision": True, "state": True}
