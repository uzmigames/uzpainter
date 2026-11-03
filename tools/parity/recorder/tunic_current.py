r"""The Tunic v10 current-round request, `phase2/tier1/tunic-v10-current` (decision 300 items 7-8).

    python -m tools.parity.recorder.tunic_current request --assets-root <Assets3D>
        [--inputs <private inputs.json>] --out <request.json> [--store DIR]

Once the request exists it is recorded as a native job (`script_run.NativeJob`):

    python -m tools.parity.recorder record-script <request.json> --assets-root <Assets3D>

This is a current-round technical preparation, not a baseline approval and not parity evidence:
the low, the 9 substitute masks and the AO behind them are made now, and using the round as
phase2.10's changed baseline stays the owner's yes (decision 300 item 8). The request promotes
and admits nothing. It binds what the input contract
(`docs/analysis/tunic-v10-current-round/01-input-contract.md`) fixes:

1. **Route.** Three steps, the native job's (`parity/RECORDER.md`, "Native jobs"): the recorder's
   own `substance_painter.project.create` (the low, every setting explicit, the preserved Normal
   imported as `Tunic_v6_HighNormal` in `tunica18_v10c_mesh_maps` and bound alone); the unchanged
   `painter_layer_stack.py sync` with `run.py` and its two helpers (the raw LF blobs of Assets3D
   `SNAPSHOT`, the Sash round's four pins), on the stack working copy with the F03 override
   (`recipe` the report, decision 194), the options `--resource-prefix v10c_ --resource-group
   tunica18_v10c --texture-set DefaultMaterial` and the 17 masks by folder; then the migration
   golden's export configuration (`export-config.json`), the only export.
2. **Pinned files.** The sync scripts and `report.json` are raw blobs of `SNAPSHOT` (`git cat-file`,
   never the checkout); the working copy is derived from the report (`tunic.working_copy`) and must
   hash to its pin; the export configuration is the repository file at its pin.
3. **Preserved inputs, from the private store by pin** (never regenerated): the 8 recovered masks
   (`tunic.RECOVERED`) and the Normal (`tunic.NORMAL`), each re-hashed, its SHA-1 equal to the
   version the report records (and its SHA-256 where the report gives one), the masks 16-bit grey
   and the Normal 16-bit RGB at the pinned resolution.
4. **Receipts, by role** (a private inputs file, `INPUTS_SCHEMA`: role -> `sha256` and an optional
   private `file`): each producer's first run and its independent repeat. A repeat is accepted only
   when it binds its first run and the producer's own record comparison, re-run here, finds nothing;
   a status alone is never taken:
   - front U3's low export (`tunic_low_export`): both records at the pins front U4 accepted
     (`tunic_ao.LowPins`; the repeat says it reproduced r1, which has no hash link of its own), the
     preserved `.blend`, the Blender side, `low.npz` and `highnormal.npy`;
   - front U4's AO (`tunic_ao`): baked on exactly U3's two records and digests; the repeat's
     `expect.of_record_sha256` is the r1 record's hash, `reproduced`, no problem;
   - front U4's masks (`tunic_masks`): r1 `produced`, the repeat `reproduced` with
     `repeat.of_record_sha256` the r1 record's hash and `byte-identical`; the donor, runtime and
     parameters; U3's records and arrays and the AO records and `ao.npy` it consumed; exactly the 9
     substitutes, the 7 donor outputs at preserved names as `discarded-never-bound` (never bound:
     no bound mask carries a discarded file or its bytes), the 8 preserved masks at their pins and
     the 17 stack masks.
   Every output the request binds or a receipt links (the OBJ, the MTL, `ao.npy`, the 9 masks) is
   re-hashed: from the store by its record's hash, else beside its records, and any copy beside a
   record with other bytes refuses the request.

Anything absent refuses the request with every missing role listed (`MissingInputs`), before the
store is written; a wrong hash, shape, receipt or link refuses it too. Only a complete set is
stored (decision 144), and the request is written only once its native job loads from those pins
(`pipeline_job_from_manifest`). Double-sided display is settled by SUP-030: the Painter round
neither sets nor checks it.
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

from tools.parity.recorder import tunic
from tools.parity.recorder.job import sha256_bytes, sha256_file
from tools.parity.recorder.output import ensure_outside_repository
from tools.parity.recorder.sash_current import (
    BLOBS as SASH_BLOBS,
)
from tools.parity.recorder.sash_current import (
    ENTRY_KEYS,
    GREY,
    RGB,
    SNAPSHOT,
    Blob,
    Found,
    NonFinite,
    assets3d_item,
    expect,
    find_blob,
    find_entry,
    finite_float,
    keys_at,
    no_constant,
    require_png,
    sha_at,
    store_input,
    stored,
    value_at,
)
from tools.parity.recorder.script_run import (
    CONFIG_EXPORT,
    INTERFACE,
    NATIVE_CREATE,
    RUN_SCRIPT,
    SYNC_COMMAND,
    MissingInputs,
    NativeJob,
    material_library,
    pipeline_job_from_manifest,
    stack_bitmaps,
)
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT, Schema, validation_errors
from tools.parity.store.store import OracleStore, StoreError, locate
from tools.parity.tier1 import tunic_ao, tunic_low_export, tunic_masks
from tools.parity.tier1 import tunic_ao_blender as ao_side
from tools.parity.tier1 import tunic_low_blender as low_side
from tools.parity.tier1.tunic_ao import LowPins
from tools.parity.tier1.tunic_intermediates import SOURCE

GOLDEN_ID = "phase2/tier1/tunic-v10-current"
PIECE = "18-Tunica"
TEXTURE_SET = low_side.TEXTURE_SET  # "DefaultMaterial": the record's one texture set
# Where the recorder stages the round's inputs (authored: the round has no Assets3D folder).
ROUND = "_tmp/claude/tunica18-v10c"
LOW_OBJ = f"{ROUND}/lows/{low_side.OBJ_NAME}"
LOW_MTL = f"{ROUND}/lows/{low_side.MTL_NAME}"
NORMAL_PATH = f"{ROUND}/mesh-maps/{tunic.NORMAL[0]}.png"
MASKS = f"{ROUND}/paint/masks"
STACK = f"{ROUND}/paint/stack-tunic-v10-working-copy.json"
# The native create (the input contract's Arguments): the derived values and the authored ones.
NORMAL_NAME = "Tunic_v6_HighNormal"  # derived: the recorded Normal resource's name
NORMAL_GROUP = "tunica18_v10c_mesh_maps"  # authored
SETTINGS: dict[str, Any] = {  # every project.Settings field the recorder passes, explicitly
    "normal_map_format": "OpenGL",  # authored: the preserved Normal's encoding
    "tangent_space_mode": "PerFragment",  # authored (Codex root, the current-round contract)
    "project_workflow": "Default",  # authored: one texture set, no UV tiles
    "default_texture_resolution": 4096,  # derived
    "import_cameras": False,  # authored
    "mesh_unit_scale": 1.0,  # authored
}
SYNC_OPTIONS = {"resource_prefix": "v10c_", "resource_group": "tunica18_v10c"}
CLOSURE = ("decision-evidence-py", "stage-review-evidence-py")
OVERRIDE_LAYER, OVERRIDE_MASK = "F03", "M_piping_lining_v9"  # decision 194: F03 only
# The sync and its import closure: the Sash round's four pins at `SNAPSHOT`; the report there.
SYNC_IDS = ("painter-layer-stack-py", "production-run-py", *CLOSURE)
REPORT = Blob(
    "tunic-report",
    "recipe_json",
    tunic.TUNIC_REPORT,
    "7829b2add3961e6916bfba32fdea470c3736c2f060636fd8a03b0272a982af5f",
)
BLOBS: tuple[Blob, ...] = (*(b for b in SASH_BLOBS if b.input_id in SYNC_IDS), REPORT)
STACK_SHA256 = "a5bc5613f9507c184e1b6df29c0d5e59b9c87dd812bd04db5695847f963a3650"
EXPORT_CONFIG_SHA256 = "7167a93ec10baf82f6d394efff7ea91d3f525b747ed1a71b47dc5bc75b846de8"

# The private inputs file: role -> {"sha256", "file"?}, one per producer run.
INPUTS_SCHEMA = "uzpainter/parity/tunic-v10-current-inputs/1"
LOW_RECORD, LOW_REPEAT = "low-record", "low-repeat"  # front U3: export-record.json, r1 and repeat
AO_RECORD, AO_REPEAT = "ao-record", "ao-repeat"  # front U4: ao-record.json, r1 and repeat
MASKS_RECORD, MASKS_REPEAT = "masks-record", "masks-repeat"  # front U4: masks-record.json
RECEIPTS = (LOW_RECORD, LOW_REPEAT, AO_RECORD, AO_REPEAT, MASKS_RECORD, MASKS_REPEAT)
LOW_SCHEMA = tunic_low_export.RECORD_SCHEMA  # "uzpainter/parity/tunic-low-export-record/1"
AO_SCHEMA = tunic_ao.RECORD_SCHEMA  # "uzpainter/parity/tunic-ao-record/1"
MASKS_SCHEMA = tunic_masks.RECORD_SCHEMA  # "uzpainter/parity/tunic-masks-record/1"
AO_OUTPUT = f"{ao_side.DONOR_OUT}/{ao_side.AO_NAME}"  # "donor/ao.npy", what the masks consume
NORMAL_ROLE = "tunic-normal"
LOW_OBJ_ROLE, LOW_MTL_ROLE, AO_ROLE = "low-obj", "low-mtl", "ao-npy"
SUBSTITUTES = tunic_masks.SUBSTITUTES
DISCARDED = tunic_masks.DISCARDED
SUBSTITUTE_ROLE = tunic_masks.SUBSTITUTE["classification"]  # "current-round substitute"
DISCARDED_ROLE = "discarded-never-bound"
PRESERVED_ROLE = "preserved: resolved from the private store by its pin, never regenerated"
SUBSTITUTE_KEYS = frozenset({"name", "file", "sha256", "size_bytes", "role", "shape"})
DISCARDED_KEYS = frozenset({"name", "file", "sha256", "size_bytes", "role"})
# The masks record's `receipts`: front U3's two records, the AO's two and both `ao.npy` copies.
MASKS_RECEIPTS = ("low_record", "low_repeat", "ao_record", "ao_repeat", "ao_npy", "ao_repeat_npy")
REPEAT_KEYS = frozenset({"of_record", "of_record_sha256", "result", "problems"})  # a masks repeat


@dataclass(frozen=True)
class Pins:
    """What the request pins; the defaults are the input contract's (tests pass stand-ins)."""

    snapshot: str = SNAPSHOT
    blobs: tuple[Blob, ...] = BLOBS
    stack: str = STACK_SHA256
    export_config: str = EXPORT_CONFIG_SHA256
    low: LowPins = tunic_ao.LOW_PINS
    blend: str = SOURCE.sha256
    # name -> packed image and SHA-256, as `tunic.RECOVERED`; the Normal as `tunic.NORMAL`.
    preserved: tuple[tuple[str, str, str], ...] = tuple(
        (name, image, sha256) for name, (image, sha256) in sorted(tunic.RECOVERED.items())
    )
    normal: tuple[str, str] = tunic.NORMAL
    resolution: int = 4096


PINS = Pins()


def load_inputs(path: Path) -> dict[str, dict[str, Any]]:
    """The private inputs file, refused unless it has the expected shape."""
    data = json.loads(path.read_bytes().decode("utf-8"))
    if not isinstance(data, dict) or data.get("schema") != INPUTS_SCHEMA:
        raise RecorderError(f"{path}: not a {INPUTS_SCHEMA} file")
    if set(data) != {"schema", "files"} or not isinstance(data["files"], dict):
        raise RecorderError(f"{path}: holds exactly `schema` and `files`")
    for role, entry in data["files"].items():
        if not isinstance(entry, dict) or not set(entry) <= ENTRY_KEYS or "sha256" not in entry:
            raise RecorderError(f"{path}: `{role}` must hold `sha256` and `file` only")
        if not all(isinstance(value, str) for value in entry.values()):
            raise RecorderError(f"{path}: `{role}` holds strings only")
    return dict(data["files"])


def read_record(role: str, item: Found) -> dict[str, Any]:
    try:
        record = json.loads(
            item.read().decode("utf-8"), parse_constant=no_constant, parse_float=finite_float
        )
    except (UnicodeDecodeError, json.JSONDecodeError, NonFinite) as error:
        raise RecorderError(f"`{role}` is not a JSON record ({error})") from error
    if not isinstance(record, dict):
        raise RecorderError(f"`{role}` is not a JSON object")
    return record


def run_folder(role: str, entry: Mapping[str, str]) -> Path | None:
    """The run directory of a receipt given as a private file (its outputs lie beside it)."""
    if "file" not in entry:
        return None
    file = ensure_outside_repository(Path(entry["file"]))
    if not file.is_file():
        return None
    if sha256_file(file) != entry["sha256"]:
        raise RecorderError(f"`{role}`: {file} is not the bytes {entry['sha256']}")
    return file.parent


def find_output(
    role: str,
    name: str,
    output: Mapping[str, Any],
    folders: Sequence[Path],
    store: OracleStore,
) -> Found | None:
    """A record's output by its hash and size: the store's blob, else the file `name` beside a
    record. Every copy beside a record is re-hashed, and one with other bytes refuses."""
    sha256, size = output["sha256"], output["size_bytes"]
    present = [folder / name for folder in folders if (folder / name).is_file()]
    for file in present:
        if sha256_file(file) != sha256:
            raise RecorderError(f"`{role}`: {file} has other bytes than its record's {sha256}")
    found = stored(store, role, sha256)
    if found is None and present:
        found = Found(sha256, file=present[0])
    if found is not None:
        assert found.file is not None
        if found.file.stat().st_size != size:
            raise RecorderError(f"`{role}` has {found.file.stat().st_size} bytes, not {size}")
    return found


def output_at(record: Any, role: str, path: Sequence[str]) -> dict[str, Any]:
    """`{"sha256", "size_bytes"}` of a record's output."""
    sha256 = sha_at(record, role, (*path, "sha256"))
    size = value_at(record, role, (*path, "size_bytes"))
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise RecorderError(f"`{role}` `{'.'.join((*path, 'size_bytes'))}` is {size!r}")
    return {"sha256": sha256, "size_bytes": size}


def reproduced(role: str, problems: Sequence[str]) -> None:
    """The producer's own record comparison, re-run here: the repeat must agree with its r1."""
    if problems:
        raise RecorderError(f"`{role}` does not reproduce its first run: " + "; ".join(problems))


def check_low(
    records: Mapping[str, dict[str, Any]], files: Mapping[str, Mapping[str, str]], pins: Pins
) -> None:
    """Front U3's export records: the r1 and repeat front U4 accepted (U3's repeat says it
    reproduced r1 but names no hash of it, so both records are bound by their pins), made from
    the preserved `.blend` by the pinned Blender side, `low.npz` and `highnormal.npy` the pins;
    the repeat reproduces r1 (U3's comparison, re-run)."""
    first, again = records[LOW_RECORD], records[LOW_REPEAT]
    for role, pinned in (
        (LOW_RECORD, pins.low.record_sha256),
        (LOW_REPEAT, pins.low.repeat_sha256),
    ):
        if files[role]["sha256"] != pinned:
            raise RecorderError(
                f"`{role}` is {files[role]['sha256']}, not front U3's accepted {pinned}"
            )
        record = records[role]
        expect(record, role, ("schema",), LOW_SCHEMA)
        expect(record, role, ("kind",), "export")
        expect(record, role, ("status",), "exported")
        expect(record, role, ("source", "sha256"), pins.blend)
        expect(record, role, ("script", "blender_side_sha256"), pins.low.blender_side_sha256)
        expect(record, role, ("remap",), low_side.REMAP)
    if "expect" in first:
        raise RecorderError(f"`{LOW_RECORD}` is itself a repeat")
    expect(again, LOW_REPEAT, ("expect",), {"reproduced": True, "problems": []})
    reproduced(LOW_REPEAT, tunic_low_export.compare_records(again, first))
    expect(
        first, LOW_RECORD, ("outputs", tunic_low_export.LOW_NPZ, "sha256"), pins.low.low_npz_sha256
    )
    expect(
        first, LOW_RECORD, ("outputs", low_side.HIGHNORMAL, "sha256"), pins.low.highnormal_sha256
    )
    for name in (low_side.OBJ_NAME, low_side.MTL_NAME):
        output_at(first, LOW_RECORD, ("outputs", name))


def low_outputs(first: Any) -> dict[str, str]:
    """The SHA-256 of each file of U3's r1 its consumers bind (`tunic_ao.LOW_FILES`)."""
    return {
        name: sha_at(first, LOW_RECORD, ("outputs", name, "sha256")) for name in tunic_ao.LOW_FILES
    }


def check_low_inputs(record: Any, role: str, low: Any, pins: Pins) -> None:
    """A consumer's `low_inputs` (`tunic_ao.LowInputs`): U3's two accepted records, and the
    digests and files r1 gives."""
    expect(record, role, ("low_inputs", "record_sha256"), pins.low.record_sha256)
    expect(record, role, ("low_inputs", "repeat_sha256"), pins.low.repeat_sha256)
    expect(record, role, ("low_inputs", "digests"), value_at(low, LOW_RECORD, ("mesh", "digests")))
    expect(record, role, ("low_inputs", "outputs"), low_outputs(low))


def check_ao(
    records: Mapping[str, dict[str, Any]], files: Mapping[str, Mapping[str, str]], pins: Pins
) -> None:
    """Front U4's AO records: both baked from the preserved `.blend` onto exactly U3's accepted
    low; the repeat's `expect` binds r1 by its hash, `reproduced` with no problem, and U4's
    comparison, re-run, finds nothing."""
    first, again = records[AO_RECORD], records[AO_REPEAT]
    for role in (AO_RECORD, AO_REPEAT):
        record = records[role]
        expect(record, role, ("schema",), AO_SCHEMA)
        expect(record, role, ("kind",), "ao")
        expect(record, role, ("status",), tunic_ao.STATUS["ao"])
        expect(record, role, ("source", "sha256"), pins.blend)
        check_low_inputs(record, role, records[LOW_RECORD], pins)
        output_at(record, role, ("outputs", AO_OUTPUT))
    if "expect" in first:
        raise RecorderError(f"`{AO_RECORD}` is itself a repeat")
    bound = {"of_record_sha256": files[AO_RECORD]["sha256"], "reproduced": True, "problems": []}
    expect(again, AO_REPEAT, ("expect",), bound)
    reproduced(AO_REPEAT, tunic_ao.compare_records(again, first))
    sha_at(first, AO_RECORD, ("ao", "bake", "digest"))


def preserved_json(pins: Pins) -> list[dict[str, Any]]:
    """The masks record's `preserved`, as `tunic_masks.preserved_json` writes it from the pins."""
    return [
        {"name": name, "packed_image": image, "sha256": sha256, "role": PRESERVED_ROLE}
        for name, image, sha256 in pins.preserved
    ]


def check_masks(
    records: Mapping[str, dict[str, Any]], files: Mapping[str, Mapping[str, str]], pins: Pins
) -> None:
    """Front U4's masks records: r1 `produced`, the repeat `reproduced` and `byte-identical` with
    `repeat.of_record_sha256` the r1 record's hash, and U4's comparison, re-run, finds nothing;
    the unchanged donor at its pins, the pinned runtime and parameters; U3's records and arrays
    and the AO records and `ao.npy` it consumed; exactly the 9 substitutes, the 7 discarded donor
    outputs, the 8 preserved masks at their pins and the 17 stack masks."""
    first, again = records[MASKS_RECORD], records[MASKS_REPEAT]
    ao = records[AO_RECORD]
    ao_sha256 = sha_at(ao, AO_RECORD, ("outputs", AO_OUTPUT, "sha256"))
    for role in (MASKS_RECORD, MASKS_REPEAT):
        record = records[role]
        expect(record, role, ("schema",), MASKS_SCHEMA)
        expect(record, role, ("kind",), "masks")
        expect(record, role, ("piece",), "tunic-v10")
        expect(record, role, ("donor",), tunic_masks.DONOR.as_json(tunic_masks.SNAPSHOT))
        expect(record, role, ("runtime",), dict(tunic_masks.RUNTIME))
        expect(record, role, ("parameters", "recipe"), None)
        expect(record, role, ("parameters", "resolution"), pins.resolution)
        expect(record, role, ("parameters", "png"), {"bit_depth": 16, "colour_type": GREY})
        check_low_inputs(record, role, records[LOW_RECORD], pins)
        expect(record, role, ("ao_inputs", "record_sha256"), files[AO_RECORD]["sha256"])
        expect(record, role, ("ao_inputs", "repeat_sha256"), files[AO_REPEAT]["sha256"])
        expect(record, role, ("ao_inputs", "ao_sha256"), ao_sha256)
        expect(
            record, role, ("ao_inputs", "digest"), value_at(ao, AO_RECORD, ("ao", "bake", "digest"))
        )
        receipts = {
            "low_record": pins.low.record_sha256,
            "low_repeat": pins.low.repeat_sha256,
            "ao_record": files[AO_RECORD]["sha256"],
            "ao_repeat": files[AO_REPEAT]["sha256"],
            "ao_npy": ao_sha256,
            "ao_repeat_npy": ao_sha256,
        }
        for key in MASKS_RECEIPTS:
            expect(record, role, ("receipts", key), receipts[key])
        check_mask_sets(record, role, pins)
    expect(first, MASKS_RECORD, ("status",), "produced")
    expect(first, MASKS_RECORD, ("repeat", "result"), "not-a-repeat")
    expect(again, MASKS_REPEAT, ("status",), "reproduced")
    keys_at(again, MASKS_REPEAT, ("repeat",), REPEAT_KEYS)
    expect(again, MASKS_REPEAT, ("repeat", "of_record_sha256"), files[MASKS_RECORD]["sha256"])
    expect(again, MASKS_REPEAT, ("repeat", "result"), "byte-identical")
    expect(again, MASKS_REPEAT, ("repeat", "problems"), [])
    reproduced(MASKS_REPEAT, tunic_masks.compare_records(again, first))


def entries(
    record: Any, role: str, key: str, names: Sequence[str], keys: frozenset[str]
) -> dict[str, dict[str, Any]]:
    """A list of mask entries, by name: exactly `names`, once each, each of exactly `keys`."""
    found = value_at(record, role, (key,))
    if not isinstance(found, list) or not all(isinstance(e, dict) for e in found):
        raise RecorderError(f"`{role}` `{key}` is no list of masks")
    by_name = {e.get("name"): e for e in found}
    if len(by_name) != len(found) or set(by_name) != set(names):
        raise RecorderError(f"`{role}` `{key}` must be {sorted(names)} once each")
    for name, entry in by_name.items():
        keys_at(entry, f"{role} {key} {name}", (), keys)
    return {str(name): entry for name, entry in by_name.items()}


def check_mask_sets(record: Any, role: str, pins: Pins) -> None:
    """Exactly the 9 substitutes (16-bit grey at the pinned resolution, each its own donor file),
    the 7 discarded outputs at preserved names, never bound, and the 8 preserved masks by pin."""
    preserved = [name for name, _, _ in pins.preserved]
    if set(SUBSTITUTES) & set(preserved) or len(set(SUBSTITUTES) | set(preserved)) != 17:
        raise RecorderError("the 9 substitutes and the 8 preserved masks are not the 17 masks")
    kept = entries(record, role, "substitutes", SUBSTITUTES, SUBSTITUTE_KEYS)
    dropped = entries(record, role, "discarded", DISCARDED, DISCARDED_KEYS)
    for name, entry in kept.items():
        where = f"{role} substitutes {name}"
        expect(entry, where, ("file",), f"{tunic_masks.MASKS_OUT}/{name}.png")
        expect(entry, where, ("role",), SUBSTITUTE_ROLE)
        expect(entry, where, ("shape",), [pins.resolution, pins.resolution])
        output_at(entry, where, ())
    for name, entry in dropped.items():
        where = f"{role} discarded {name}"
        expect(entry, where, ("file",), f"{tunic_masks.MASKS_OUT}/{name}.png")
        expect(entry, where, ("role",), DISCARDED_ROLE)
        output_at(entry, where, ())
    discarded = {entry["sha256"]: name for name, entry in dropped.items()}
    for name, entry in kept.items():
        if entry["sha256"] in discarded:
            raise RecorderError(
                f"`{role}` would bind the discarded {discarded[entry['sha256']]} as {name}: a "
                "discarded donor output is never bound"
            )
    expect(record, role, ("preserved",), preserved_json(pins))
    expect(record, role, ("stack_masks",), sorted([*SUBSTITUTES, *preserved]))
    expect(record, role, ("substitute", "classification"), SUBSTITUTE_ROLE)


def check_preserved(report: Any, found: Mapping[str, Found], pins: Pins) -> None:
    """Each preserved file as the report records it: its SHA-1 the recorded resource version
    (literally, no normalisation rule), and its SHA-256 the report's where it gives one."""
    try:
        recorded = tunic.report_versions(report)
    except (KeyError, TypeError, StopIteration, RecorderError) as error:
        raise RecorderError(f"`tunic-report` records no resource versions ({error!r})") from error
    for name, role in (*((n, n) for n, _, _ in pins.preserved), ("Normal", NORMAL_ROLE)):
        if name not in recorded:
            raise RecorderError(f"`tunic-report` records no version of {name}")
        sha256, version = recorded[name]
        item = found[role]
        sha1 = hashlib.sha1(item.read(), usedforsecurity=False).hexdigest()
        if (sha256 is not None and sha256 != item.sha256) or sha1 != version:
            raise RecorderError(
                f"`{role}`: sha256 {item.sha256} / version {sha1} disagree with the report's "
                f"{sha256} / {version}"
            )


def working_copy(report: Any) -> bytes:
    """The stack working copy: the report's recipe with its recorded override on F03 only."""
    try:
        override = tunic.at(report, tunic.OVERRIDE)
        stack = tunic.working_copy(report)
    except (KeyError, TypeError) as error:
        raise RecorderError(f"`tunic-report` holds no recipe and override ({error!r})") from error
    if (override.get("layer_id"), override.get("mask")) != (OVERRIDE_LAYER, OVERRIDE_MASK):
        raise RecorderError(f"the report's override is {override}, not F03 -> M_piping_lining_v9")
    return tunic.stack_bytes(stack)


def current_request(
    assets_root: Path,
    store: OracleStore,
    files: Mapping[str, Mapping[str, str]] | None,
    pins: Pins = PINS,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """The request: refused with `MissingInputs` naming every absent role before anything is
    stored; refused on a wrong hash, shape, receipt or link; else every input is stored and the
    request returned once its native job loads from the store."""
    files = dict(files or {})
    unknown = sorted(set(files) - set(RECEIPTS))
    if unknown:  # a discarded mask or a product among them: only receipts are named
        raise RecorderError(f"the inputs file names unknown roles {unknown}")
    missing: list[str] = []
    found: dict[str, Found] = {}
    for blob in pins.blobs:
        item = find_blob(blob, assets_root, store, pins.snapshot)
        if item is None:
            missing.append(f"{blob.path}@{pins.snapshot[:8]}")
        else:
            found[blob.input_id] = item
    for role in RECEIPTS:
        item = find_entry(role, files[role], store) if role in files else None
        if item is None:
            missing.append(role)
        else:
            found[role] = item
    for role, sha256 in (*((n, s) for n, _, s in pins.preserved), (NORMAL_ROLE, pins.normal[1])):
        item = stored(store, role, sha256)
        if item is None:
            missing.append(role)
        else:
            found[role] = item
    if missing:
        raise MissingInputs(GOLDEN_ID, missing)

    config = repo_root / tunic.EXPORT_CONFIG
    if not config.is_file() or sha256_file(config) != pins.export_config:
        raise RecorderError(f"{config} is missing or not the pinned {pins.export_config}")
    report = json.loads(found[REPORT.input_id].read().decode("utf-8"))
    stack = working_copy(report)
    if sha256_bytes(stack) != pins.stack:
        raise RecorderError(f"the stack working copy is {sha256_bytes(stack)}, not {pins.stack}")
    found["tunic-stack"] = Found(pins.stack, data=stack)
    names = sorted([*SUBSTITUTES, *(n for n, _, _ in pins.preserved)])
    if sorted(stack_bitmaps(json.loads(stack))) != names:
        raise RecorderError(f"the working copy binds {sorted(stack_bitmaps(json.loads(stack)))}")
    check_preserved(report, found, pins)

    records = {role: read_record(role, found[role]) for role in RECEIPTS}
    check_low(records, files, pins)
    check_ao(records, files, pins)
    check_masks(records, files, pins)
    folders = {role: run_folder(role, files[role]) for role in RECEIPTS}

    def beside(*roles: str) -> list[Path]:
        return [f for f in (folders[r] for r in roles) if f is not None]

    wanted: list[tuple[str, str, dict[str, Any], list[Path]]] = [
        (
            role,
            name,
            output_at(records[LOW_RECORD], LOW_RECORD, ("outputs", name)),
            beside(LOW_RECORD, LOW_REPEAT),
        )
        for role, name in ((LOW_OBJ_ROLE, low_side.OBJ_NAME), (LOW_MTL_ROLE, low_side.MTL_NAME))
    ]
    wanted.append(
        (
            AO_ROLE,
            AO_OUTPUT,
            output_at(records[AO_RECORD], AO_RECORD, ("outputs", AO_OUTPUT)),
            beside(AO_RECORD, AO_REPEAT),
        )
    )
    for entry in records[MASKS_REPEAT]["substitutes"]:
        wanted.append((entry["name"], entry["file"], entry, beside(MASKS_REPEAT, MASKS_RECORD)))
    for role, name, output, where in wanted:
        item = find_output(role, name, output, where, store)
        if item is None:
            missing.append(role)
        else:
            found[role] = item
    if missing:
        raise MissingInputs(GOLDEN_ID, missing)

    size = pins.resolution
    for name in names:
        require_png(name, found[name].read(), frozenset({16}), frozenset({GREY}), size)
    require_png(NORMAL_ROLE, found[NORMAL_ROLE].read(), frozenset({16}), frozenset({RGB}), size)
    obj = found[LOW_OBJ_ROLE].file
    assert obj is not None  # an output is a file, never a git blob
    if material_library(obj) != low_side.MTL_NAME:
        raise RecorderError(f"the low OBJ names the material library {material_library(obj)!r}")
    problems = tunic_low_export.mtl_problems(found[LOW_MTL_ROLE].read().decode("utf-8"))
    if problems:
        raise RecorderError("`low-mtl`: " + "; ".join(problems))

    paths = {blob.input_id: blob.path for blob in pins.blobs}
    paths.update(
        {
            "tunic-stack": STACK,
            LOW_OBJ_ROLE: LOW_OBJ,
            LOW_MTL_ROLE: LOW_MTL,
            NORMAL_ROLE: NORMAL_PATH,
            **{name: f"{MASKS}/{name}.png" for name in names},
        }
    )
    manifest = request_manifest(found, files, records, pins)
    problems = validation_errors(manifest, Schema.GOLDEN_PUBLIC)
    if problems:
        raise RecorderError(f"the {GOLDEN_ID} request is invalid: {problems}")
    for role, item in found.items():
        store_input(store, item, paths.get(role, f"private/{GOLDEN_ID}/{role}"))
    job = pipeline_job_from_manifest(manifest, assets_root, store, repo_root)
    if not isinstance(job, NativeJob):
        raise RecorderError(f"the {GOLDEN_ID} request does not load as a native job")
    return manifest


def note_of(role: str, records: Mapping[str, Any], files: Mapping[str, Mapping[str, str]]) -> str:
    """A receipt as a note cites it: its schema, its kind, and its hash."""
    return (
        f"{records[role]['schema']} {records[role]['kind']} record sha256 {files[role]['sha256']}"
    )


DESCRIPTION = (
    "Tier 1 current round of the UzmiGames tunic 18-Tunica v10 of the Skeletal Mage (decision 300 "
    "items 7-8): a current-round technical preparation, not the historical round, not parity "
    "evidence and not an approved baseline. Using it as phase2.10's changed baseline waits for "
    "the owner's yes (decision 300 item 8); this request promotes and admits nothing. The "
    "recorder creates the project itself (substance_painter.project.create, no template, under "
    "OCIO with Painter's substance config): the low OBJ, texture set DefaultMaterial, 4096 px, "
    "OpenGL normals, PerFragment tangents, the Default workflow, unit scale 1, no cameras; the "
    "preserved Normal imported as Tunic_v6_HighNormal in tunica18_v10c_mesh_maps and bound alone. "
    "Then painter_layer_stack.py sync, byte-unchanged (the raw git blob of Assets3D 1c9a312a, "
    "with run.py and its two import-time helpers), on the stack working copy (the report's recipe "
    "with F03 alone binding M_piping_lining_v9, decision 194) and its 17 masks by folder (8 "
    "preserved, 9 current-round substitutes), resource prefix v10c_, group tunica18_v10c. Then "
    "the migration golden's export configuration, the only export: the five DefaultMaterial maps "
    "as 16-bit PNG, sizeLog2 12, infinite padding, no dithering. The low, the 9 masks and the AO "
    "behind them are made now, each pinned by hash under the receipts its note names; the "
    "historical inputs stay missing. Double-sided display is neither set nor checked in Painter "
    "(SUP-030). Recordings: r1 (create, sync, export), r1-repeat (export again) and r2 (after "
    "save, close and reopen, export again), which must be byte-identical."
)
APPLIED_SETTINGS: tuple[tuple[str, Any, str], ...] = (
    ("OCIO", "resources/ocio/substance/config.ocio", "environment_variable"),
    *((f"project.{name}", value, "recorder_api") for name, value in SETTINGS.items()),
    ("project.save_mode", "Full", "recorder_api"),
    ("export.file_format", "png", "recorder_api"),
    ("export.png.bit_depth", 16, "recorder_api"),
    ("export.size_log2", 12, "recorder_api"),
    ("export.padding", "infinite", "recorder_api"),
    ("export.dithering", False, "recorder_api"),
    ("export.shader_params", False, "recorder_api"),
)


def request_manifest(
    found: Mapping[str, Found],
    files: Mapping[str, Mapping[str, str]],
    records: Mapping[str, Mapping[str, Any]],
    pins: Pins,
) -> dict[str, Any]:
    snapshot = pins.snapshot[:8]
    inputs = [
        assets3d_item(
            blob.input_id,
            blob.kind,
            blob.path,
            blob.sha256,
            f"Raw git blob of Assets3D {snapshot} {blob.path} (LF), read from Assets3D's object "
            "database into the private store: "
            + (
                "the committed recipe (painting_v10.painter_stack_recipe) the sync's F03 "
                "override applies to."
                if blob.input_id == REPORT.input_id
                else "the committed file the current round runs. Which bytes the historical "
                "round ran is unestablished."
            ),
        )
        for blob in pins.blobs
    ]
    inputs.append(
        assets3d_item(
            "tunic-stack",
            "recipe_json",
            STACK,
            pins.stack,
            "Derived for the current round from the pinned report.json (tunic.working_copy): its "
            f"recipe with the recorded override, {OVERRIDE_LAYER} alone binding {OVERRIDE_MASK} "
            "(decision 194), written as tunic.stack_bytes; the input contract's stack working "
            "copy.",
        )
    )
    low = (
        f"from the preserved .blend {pins.blend}, receipt {note_of(LOW_RECORD, records, files)}, "
        f"reproduced by {note_of(LOW_REPEAT, records, files)}"
    )
    for input_id, role, path in (
        ("tunic-mesh", LOW_OBJ_ROLE, LOW_OBJ),
        ("tunic-mesh-mtl", LOW_MTL_ROLE, LOW_MTL),
    ):
        inputs.append(
            assets3d_item(
                input_id,
                "mesh",
                path,
                found[role].sha256,
                "Current-round substitute, not the lost normalized_low.obj and not parity "
                f"evidence: front U3's deterministic export (tunic_low_export) {low}. Its "
                f"material {TEXTURE_SET} is an authored name remap of the copy, not a recovered "
                "material.",
            )
        )
    image, sha256 = pins.normal
    inputs.append(
        assets3d_item(
            NORMAL_ROLE,
            "image",
            NORMAL_PATH,
            sha256,
            f"Preserved, never regenerated: the packed {image} recovered from {tunic.TUNIC_BLEND} "
            "(tunic.NORMAL), resolved from the private store by its pin; its SHA-1 is the Normal "
            "resource version the report records.",
        )
    )
    masks = records[MASKS_REPEAT]
    ao = records[AO_RECORD]
    low_files = masks["low_inputs"]["outputs"]
    made = (
        f"written by {tunic_masks.DONOR.path} (raw blob of Assets3D {tunic_masks.SNAPSHOT[:8]}, "
        f"{tunic_masks.DONOR.sha256}) run unchanged through tunic_masks, receipt "
        f"{note_of(MASKS_REPEAT, records, files)} (an independent repeat of "
        f"{masks['repeat']['of_record_sha256']}, byte-identical), from front U3's low.npz "
        f"{low_files[tunic_low_export.LOW_NPZ]} and highnormal.npy "
        f"{low_files[low_side.HIGHNORMAL]} (receipt {note_of(LOW_RECORD, records, files)}) and the "
        f"NEW AO substitute ao.npy {ao['outputs'][AO_OUTPUT]['sha256']} (receipt "
        f"{note_of(AO_RECORD, records, files)}, reproduced by "
        f"{note_of(AO_REPEAT, records, files)})."
    )
    preserved = {name: (packed, sha) for name, packed, sha in pins.preserved}
    for name in sorted([*SUBSTITUTES, *preserved]):
        if name in preserved:
            note = (
                f"Preserved, never regenerated: the packed {preserved[name][0]} recovered from "
                f"{tunic.TUNIC_BLEND} (tunic.RECOVERED), resolved from the private store by its "
                "pin; its SHA-1 is the resource version the report records."
            )
        else:
            note = (
                f"Current-round substitute, not the historical {name} and not parity "
                f"evidence: {made}"
            )
        inputs.append(
            assets3d_item(
                f"mask-{name.lower()}", "mask", f"{MASKS}/{name}.png", found[name].sha256, note
            )
        )
    inputs.append(
        {
            "input_id": "tunic-v10-export-config",
            "kind": "recipe_json",
            "path": tunic.EXPORT_CONFIG,
            "sha256": pins.export_config,
            "provenance": {
                "origin": "uzmigames_authored",
                "licence": "Apache-2.0",
                "note": "The export configuration of the Tunic v10 migration golden (decision "
                "194), unchanged: the current round exports the same five map names.",
            },
        }
    )
    create = {
        "mesh": "tunic-mesh",
        "mesh_material_library": "tunic-mesh-mtl",
        "normal": NORMAL_ROLE,
        "texture_set": TEXTURE_SET,
        "normal_name": NORMAL_NAME,
        "normal_group": NORMAL_GROUP,
        **SETTINGS,
    }
    sync = {
        "script": "painter-layer-stack-py",
        "command": SYNC_COMMAND,
        "stack": "tunic-stack",
        "mask_folder": MASKS,
        "imports": ["production-run-py"],
        "import_closure": list(CLOSURE),
        **SYNC_OPTIONS,
        "texture_set": TEXTURE_SET,
        "recipe": REPORT.input_id,
        "recipe_keys": list(tunic.RECIPE),
        "override_layer": OVERRIDE_LAYER,
        "override_mask": OVERRIDE_MASK,
    }
    return {
        "schema": "uzpainter/parity/golden-public/1",
        "record_class": "public_manifest",
        "golden_id": GOLDEN_ID,
        "tier": "1",
        "domain": "tier1/pilot/tunic-v10-current",
        "description": DESCRIPTION,
        "inputs": inputs,
        "instruction_sequence": {
            "author": "UzmiGames",
            "interface": INTERFACE,
            "steps": [
                {"step": 1, "call": NATIVE_CREATE, "args": create},
                {"step": 2, "call": RUN_SCRIPT, "args": sync},
                {"step": 3, "call": CONFIG_EXPORT, "args": {"config": "tunic-v10-export-config"}},
            ],
        },
        "applied_settings": [
            {"name": name, "value": value, "applied_by": by} for name, value, by in APPLIED_SETTINGS
        ],
        "expectations": [],
        "software": {
            "painter": {
                "product": "Adobe Substance 3D Painter",
                "version": "12.2.0",
                "build_id": "12.2.0+js-api.1.1.20",
            },
            "uzpainter_build_hash": None,
        },
        "private_records": [],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.recorder.tunic_current")
    commands = parser.add_subparsers(dest="command", required=True)
    request = commands.add_parser("request", help="write the request once every input exists")
    request.add_argument("--assets-root", type=Path, required=True)
    request.add_argument("--inputs", type=Path, help="the private inputs file (INPUTS_SCHEMA)")
    request.add_argument("--out", type=Path, required=True)
    request.add_argument("--store", type=Path, help="the private store (default: this machine's)")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        store = OracleStore.open(args.store) if args.store else locate()
        if store is None:
            raise RecorderError("there is no private store on this machine")
        files = load_inputs(args.inputs) if args.inputs else None
        manifest = current_request(args.assets_root.resolve(), store, files, PINS)
    except MissingInputs as error:
        print(f"refused: {error}", file=sys.stderr)
        print(json.dumps({"missing": error.missing}, indent=2), file=sys.stderr)
        return 2
    except (RecorderError, StoreError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
