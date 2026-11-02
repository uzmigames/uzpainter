"""The Sash v5 current-round request (`sash_current.py`; decision 300 items 7-8), over a stand-in
asset repository that is a git repository (the scripts are read as raw blobs of one commit), a
temporary private store, complete stand-in PNGs and producer records in their producers' real
shapes (front N's export record, front P's extraction, AO and centre records, front T's masks
record); and, when they are here, the real asset repository's pins, the real import closure and
the real N and P records."""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import os
import struct
import subprocess
import sys
import zlib
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from tests.parity.recorder.test_script_run import (  # noqa: F401  (`painter` is a fixture)
    BELT,
    CLOSURE,
    CREATE,
    CURRENT_LAYER_STACK,
    EXPORT,
    LAYER_STACK_PATH,
    SASH_STACK,
    painter,
    write,
)
from tools.parity.recorder import sash_current, script_run
from tools.parity.recorder import session as session_module
from tools.parity.recorder.sash_current import (
    AO,
    BLOBS,
    INPUTS_SCHEMA,
    INTERMEDIATES_SCHEMA,
    MASKS,
    MASKS_SCHEMA,
    NORMAL,
    SWATCHES,
    WAIST_GEN,
    Blob,
    Found,
    Pins,
    current_request,
)
from tools.parity.recorder.script_run import (
    MissingInputs,
    PinnedInput,
    ScriptSession,
    record_script_golden,
    script_job_from_manifest,
)
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import Schema, record_problems, validation_errors
from tools.parity.store.store import OracleStore, Status

REAL_ASSETS = Path(r"E:\UzmiGames\Assets3D")
ORACLE_WORK = Path(os.environ.get("LOCALAPPDATA", "")) / "UzPainter" / "oracle-work"
REAL_RUNS = "phase2__tier1__sash-v5-current__"
BUILD = "12.2.0+js-api.1.1.20"
RES = 8  # the stand-in resolution (the real pin is 2048)
OBJ = "mtllib 25-Faixa-Cintura-v5-low.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nf 1 2 3\n"
MTL = "newmtl 25-Faixa-Cintura\n"
AO_PNG = PurePosixPath(AO).name
# The stand-in stack without its base_tex colour: masks only, as the round can be today.
MASK_STACK: dict[str, Any] = copy.deepcopy(SASH_STACK)
for layer in MASK_STACK["layers"]:
    if layer.pop("base_tex", None):
        layer["base"] = [40, 31, 26]
MASK_BITMAPS = ("M_hem", "M_weave")
Files = dict[str, dict[str, str]]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hexes(tag: str) -> str:
    return sha256(tag.encode("ascii"))


def png(size: int, depth: int, colour: int, seed: int) -> bytes:
    """A complete PNG (every chunk with its CRC, filter 0 rows), samples set by `seed`."""
    channels = {0: 1, 2: 3, 6: 4}[colour]
    row = bytes((seed + i) % 256 for i in range(size * channels * depth // 8))
    raw = b"".join(b"\x00" + row for _ in range(size))

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = struct.pack(">I", zlib.crc32(kind + body))
        return struct.pack(">I", len(body)) + kind + body + crc

    header = struct.pack(">IIBBBBB", size, size, depth, colour, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def git(root: Path, *args: str) -> bytes:
    command = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false"]
    return subprocess.run(
        [*command, "-C", str(root), *args], capture_output=True, check=True
    ).stdout


def blob(root: Path, commit: str, path: str) -> bytes:
    return git(root, "cat-file", "blob", f"{commit}:{path}")


def make_round_assets(root: Path, stack: dict[str, Any], bitmaps: tuple[str, ...]) -> Pins:
    """A stand-in Assets3D at the real layout, committed once: the waist-v5 create and export
    scripts, the 1c9a312a-shaped sync and its closure, the stack and the Normal. After the
    commit the sync's checkout drifts (as Assets3D's CRLF checkout does), so only the blob holds
    the pin."""
    write(root / "AGENTS.md", "stand-in asset repository\n")
    waist = root / sash_current.WAIST
    write(
        waist / "painter_create.py",
        CREATE.replace("__ARGS__", str(root / BELT / "painter_create_args.json")),
    )
    write(
        waist / "painter_export.py",
        EXPORT.replace("__ARGS__", str(root / BELT / "painter_export_args.json")),
    )
    write(waist / "stack-sash.json", json.dumps(stack))
    write(root / LAYER_STACK_PATH, CURRENT_LAYER_STACK)
    for _, path, text in CLOSURE:
        write(root / path, text)
    write(root / NORMAL.path, b"sash normal bake")
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "stand-in")
    commit = git(root, "rev-parse", "HEAD").decode("ascii").strip()
    write(root / LAYER_STACK_PATH, CURRENT_LAYER_STACK.replace("\n", "\r\n"))
    return Pins(
        snapshot=commit,
        blobs=tuple(
            Blob(b.input_id, b.kind, b.path, sha256(blob(root, commit, b.path))) for b in BLOBS
        ),
        normal=Blob(NORMAL.input_id, NORMAL.kind, NORMAL.path, sha256(b"sash normal bake")),
        low_obj=sha256(OBJ.encode("ascii")),
        low_mtl=sha256(MTL.encode("ascii")),
        bitmaps=bitmaps,
        resolution=RES,
    )


def out(data: bytes) -> dict[str, Any]:
    return {"sha256": sha256(data), "size_bytes": len(data)}


def masks_record(
    pins: Pins, data: dict[str, bytes], receipts: dict[str, str], arrays: dict[str, str]
) -> dict[str, Any]:
    """A masks record as front T's `sash_masks.produce` writes it for an agreeing repeat."""
    stack = [b for b in pins.bitmaps if b != sash_current.COLOUR]
    outputs = [
        {
            "name": name,
            "file": f"{name}.png",
            "role": "auxiliary" if name in pins.auxiliary else "stack-input",
            **(out(data[name]) if name in data else {"sha256": hexes(name), "size_bytes": 1}),
            "shape": [pins.resolution, pins.resolution],
            "depth": 16,
            "colour_type": 0,
            "coverage_mean": 0.5,
        }
        for name in (*pins.auxiliary, *reversed(stack))  # the donor's order, not sorted
    ]
    return {
        "schema": MASKS_SCHEMA,
        "kind": "masks",
        "status": "reproduced",
        "piece": "sash",
        "run_dir": "C:/oracle-work/masks-r1-repeat",
        "helper": {
            "path": "tools/parity/tier1/sash_masks.py",
            "sha256": hexes("t"),
            "checks_with": [],
        },
        "sources": [
            {
                "module": module,
                "assets3d_path": path,
                "commit": pins.snapshot,
                "git_blob": hexes(module)[:40],
                "sha256": digest,
                "size_bytes": 1,
                "read_from": "git object database (git cat-file), never the checkout",
                **(
                    {"checkout_sha256": pins.waist_gen_checkout, "checkout_form": "CRLF"}
                    if module == "waist_gen"
                    else {}
                ),
            }
            for module, path, digest in pins.mask_sources
        ],
        "runtime": {"python": "3.13.9"},
        "host": {"python_executable": "python", "platform": "stand-in"},
        "parameters": {
            "resolution": pins.resolution,
            "orientation": "rows top first",
            "padding": "nearest island texel",
            "quantisation": "uint16",
            "png": {"bit_depth": 16, "colour_type": 0},
        },
        "receipts": {
            "extraction": {
                "path": "x",
                "sha256": receipts["extraction"],
                "schema": INTERMEDIATES_SCHEMA,
                "kind": "extract",
            },
            "ao": {
                "path": "x",
                "sha256": receipts["ao"],
                "schema": INTERMEDIATES_SCHEMA,
                "kind": "ao",
                "extraction_record_sha256": receipts["extraction"],
            },
            "centre": {
                "path": "x",
                "sha256": receipts["centre"],
                "schema": INTERMEDIATES_SCHEMA,
                "kind": "centre",
                "status": "derived-from-preserved-geometry",
                "extraction_record_sha256": receipts["extraction"],
            },
        },
        "extraction_link": {
            "extraction_record_sha256": receipts["extraction"],
            "cited_by": ["ao", "centre"],
        },
        "arrays": {
            name: {"receipt": "extraction", "sha256": sha, "size_bytes": 1}
            for name, sha in arrays.items()
        },
        "split": {"masks_written": len(outputs), "boundary_reached": 'swatch("cloth")'},
        "texels": 1,
        "outputs": outputs,
        "stack_inputs": [o["name"] for o in outputs if o["role"] == "stack-input"],
        "auxiliary": list(pins.auxiliary),
        "substitute": {"classification": "current-round substitute"},
        "colour": {"status": "not-in-scope"},
        "repeat": {
            "of_record": "C:/oracle-work/masks-r1/masks-record.json",
            "of_record_sha256": hexes("masks r1"),
            "result": "byte-identical",
            "problems": [],
        },
    }


def private_inputs(folder: Path, pins: Pins) -> Files:
    """Every private input as a file: N's low and export record; P's extraction, AO and centre
    records; T's masks record; the AO map's record; all over complete PNGs at the pinned
    resolution, linked by hash."""
    stack = [b for b in pins.bitmaps if b != sash_current.COLOUR]
    data: dict[str, bytes] = {
        "low-obj": OBJ.encode("ascii"),
        "low-mtl": MTL.encode("ascii"),
        "ao": png(pins.resolution, 16, 0, 1),
        **{b: png(pins.resolution, 16, 0, i) for i, b in enumerate(stack, start=30)},
    }
    table = hexes("table")
    low = {
        "schema": "uzpainter/parity/sash-low-export-record/1",
        "exporter": "uzpainter/parity/sash-low-export/1",
        "source": {"sha256": pins.low_source},
        "outputs": {
            "obj": {"file": "25-Faixa-Cintura-v5-low.obj", "sha256": pins.low_obj, "size_bytes": 1},
            "mtl": {"file": "25-Faixa-Cintura-v5-low.mtl", "sha256": pins.low_mtl, "size_bytes": 1},
            "table": {"file": "export-table.json", "sha256": table, "size_bytes": 1},
        },
    }
    arrays = {
        "low.npz": hexes("low.npz"),
        "highnormal.npy": hexes("highnormal"),
        "ao.npy": hexes("ao.npy"),
        "construction-centre.npz": hexes("centre"),
    }
    extract = {
        "schema": INTERMEDIATES_SCHEMA,
        "kind": "extract",
        "source": {"sha256": pins.low_source},
        "low_game": {
            "obj_sha256": pins.low_obj,
            "mtl_sha256": pins.low_mtl,
            "table_sha256": table,
        },
        "normal": {"sha256": pins.normal.sha256},
        "outputs": {
            "low.npz": {"sha256": arrays["low.npz"], "size_bytes": 1},
            "highnormal.npy": {"sha256": arrays["highnormal.npy"], "size_bytes": 1},
        },
    }
    data["low-record"] = json.dumps(low).encode("utf-8")
    data["intermediates-record"] = json.dumps(extract).encode("utf-8")
    extract_sha256 = sha256(data["intermediates-record"])
    ao = {
        "schema": INTERMEDIATES_SCHEMA,
        "kind": "ao",
        "extraction": {"record_sha256": extract_sha256},
        "outputs": {"ao.npy": {"sha256": arrays["ao.npy"], "size_bytes": 1}},
    }
    centre = {
        "schema": INTERMEDIATES_SCHEMA,
        "kind": "centre",
        "status": "derived-from-preserved-geometry",
        "extraction": {"record_sha256": extract_sha256},
        "donors": {WAIST_GEN: pins.waist_gen_checkout},
        "outputs": {
            "construction-centre.npz": {
                "sha256": arrays["construction-centre.npz"],
                "size_bytes": 1,
            }
        },
    }
    data["ao-record"] = json.dumps(ao).encode("utf-8")
    data["centre-record"] = json.dumps(centre).encode("utf-8")
    receipts = {
        "extraction": extract_sha256,
        "ao": sha256(data["ao-record"]),
        "centre": sha256(data["centre-record"]),
    }
    data["masks-record"] = json.dumps(masks_record(pins, data, receipts, arrays)).encode("utf-8")
    ao_map = {  # as front V's `sash_ao_map` writes it for an agreeing repeat
        "schema": "uzpainter/parity/sash-ao-map-record/1",
        "kind": "ao-map",
        "status": "reproduced",
        "piece": "sash",
        "run_dir": "C:/oracle-work/ao-map-r1-repeat",
        "resolution": pins.resolution,
        "generator": {"path": "tools/parity/tier1/sash_ao_map.py", "sha256": hexes("v")},
        "donor": {
            "assets3d_path": "Pipeline/retopology/waist-v5/sashchain.sh",
            "commit": pins.snapshot,
            "git_blob": hexes("sashchain")[:40],
            "sha256": pins.ao_donor,
            "size_bytes": 2933,
            "read_from": "git object database (git cat-file), never the checkout",
            "line": "ao=np.load('paint/work-sash/ao.npy').astype(np.float32); "
            "Image.fromarray((np.clip(ao[::-1],0,1)*65535+0.5).astype(np.uint16))",
            "run": False,
        },
        "inputs": {"ao.npy": {"sha256": arrays["ao.npy"]}},
        "outputs": {
            AO_PNG: {
                **out(data["ao"]),
                "shape": [pins.resolution, pins.resolution],
                "depth": 16,
                "colour_type": 0,
                "sample_range": [0, 65535],
            }
        },
        "repeat": {
            "of_record": "C:/oracle-work/ao-map-r1/ao-map-record.json",
            "of_record_sha256": hexes("ao map r1"),
            "result": "byte-identical",
            "problems": [],
        },
    }
    data["ao-map-record"] = json.dumps(ao_map).encode("utf-8")
    files: Files = {}
    for role, value in data.items():
        file = folder / role
        write(file, value)
        files[role] = {"sha256": sha256(value), "file": str(file)}
    return files


@pytest.fixture
def mask_round(tmp_path: Path) -> tuple[Path, Pins]:
    """The stand-in round without its colour: masks only."""
    root = tmp_path / "assets3d"
    return root, make_round_assets(root, MASK_STACK, MASK_BITMAPS)


@pytest.fixture
def store(tmp_path: Path) -> OracleStore:
    return OracleStore.init(tmp_path / "store")


def test_a_complete_round_is_stored_and_its_request_records(
    mask_round: tuple[Path, Pins],
    store: OracleStore,
    tmp_path: Path,
    painter: tuple[Any, ScriptSession],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every input resolves (the scripts as raw blobs, never the drifted checkout), is stored, and
    the request's job loads from the store and records r1, r1-repeat and r2 with the options."""
    assets, pins = mask_round
    files = private_inputs(tmp_path / "private", pins)
    manifest = current_request(assets, store, files, pins)

    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    assert manifest["golden_id"] == "phase2/tier1/sash-v5-current"
    steps = manifest["instruction_sequence"]["steps"]
    assert [s["call"] for s in steps] == [script_run.RUN_SCRIPT] * 3  # no fourth export
    assert steps[1]["args"] == {
        "script": "painter-layer-stack-py",
        "command": "sync",
        "stack": "sash-stack",
        "mask_folder": MASKS,
        "imports": ["production-run-py"],
        "import_closure": ["decision-evidence-py", "stage-review-evidence-py"],
        "resource_prefix": "v5f_",
        "resource_group": "faixa25_v5",
        "texture_set": "25-Faixa-Cintura",
    }
    items = {i["input_id"]: i for i in manifest["inputs"]}
    assert "mask-m_cloth" not in items  # the auxiliary mask is no input
    for item in items.values():
        assert store.resolve(item["input_id"], item["sha256"]).status is Status.AVAILABLE
        assert "path" not in item
    sync = next(b for b in pins.blobs if b.input_id == "painter-layer-stack-py")
    assert items["painter-layer-stack-py"]["sha256"] == sync.sha256
    assert items["sash-mesh"]["sha256"] == pins.low_obj
    notes = {i: items[i]["provenance"]["note"] for i in items}
    for input_id in ("sash-mesh", "sash-mesh-mtl", "sash-ao", "mask-m_hem"):
        assert notes[input_id].startswith("Current-round substitute")
    assert files["low-record"]["sha256"] in notes["sash-mesh"]
    assert files["ao-map-record"]["sha256"] in notes["sash-ao"]
    for role in ("masks-record", "intermediates-record", "ao-record", "centre-record"):
        assert files[role]["sha256"] in notes["mask-m_hem"]
    assert hexes("centre") in notes["mask-m_hem"] and hexes("masks r1") in notes["mask-m_hem"]
    assert "Named substitute" in notes["sash-normal"]
    created = store.load(items["painter-create-args"]["sha256"])
    assert created is not None and json.loads(created)["name"] == "25-Faixa-Cintura"
    exported = store.load(items["painter-export-args"]["sha256"])
    assert exported is not None and json.loads(exported)["prefix"] == "25-Faixa-Cintura"
    for role in sash_current.RECEIPTS:
        assert store.resolve(role, files[role]["sha256"]).status is Status.AVAILABLE

    job = script_job_from_manifest(manifest, assets, store)
    assert job.sync.script.file.is_relative_to(store.root)  # the checkout drifted
    world, session = painter
    world.version, world.version_info = "12.2.0", (12, 2, 0)  # the request's Painter
    monkeypatch.setattr(session_module, "envelope_builds", lambda: frozenset({BUILD}))
    run = record_script_golden(session, job, tmp_path / "work", tmp_path / "inbox")
    data = json.loads((run / "record.json").read_text(encoding="utf-8"))
    assert record_problems(data) == []
    synced = next(
        o["value"]
        for r in data["recordings"]
        for o in r["outputs"]
        if o["output_id"] == "script/s2"
    )
    assert synced["options"]["texture_set"] == "25-Faixa-Cintura"
    assert synced["imported"] == list(MASK_BITMAPS)
    assert synced["run_mark"] == "decision-evidence-pinned+stage-review-pinned"


def test_t_sash_stays_missing_and_no_colour_record_can_vouch_for_it(
    tmp_path: Path, store: OracleStore
) -> None:
    """With T_sash in the stack: T_sash, its colour record and both swatches are named missing;
    given them, the request is refused, since the colour producer has no contract yet."""
    root = tmp_path / "assets3d"
    pins = make_round_assets(root, SASH_STACK, ("M_hem", "M_weave", "T_sash"))
    files = private_inputs(tmp_path / "private", pins)
    with pytest.raises(MissingInputs) as refused:
        current_request(root, store, files, pins)
    assert refused.value.missing == sorted(["T_sash", "colour-record", *SWATCHES])
    for role, data in (
        ("T_sash", png(RES, 8, 2, 7)),
        ("colour-record", json.dumps({"schema": "x/1"}).encode("utf-8")),
        *((s, png(4, 8, 2, i)) for i, s in enumerate(SWATCHES)),
    ):
        write(tmp_path / "private" / role, data)
        files[role] = {"sha256": sha256(data), "file": str(tmp_path / "private" / role)}
    with pytest.raises(RecorderError, match=r"`colour-record`: T_sash has no colour producer"):
        current_request(root, store, files, pins)
    assert store.index() == set()


def test_absent_inputs_refuse_naming_each_and_store_nothing(
    mask_round: tuple[Path, Pins],
    store: OracleStore,
    tmp_path: Path,
    capsys: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Today's state: front N's low and record and P's extraction and centre records alone. The
    AO and its two records, the masks record and the masks are named missing; nothing is stored
    and no request is written."""
    assets, pins = mask_round
    files = private_inputs(tmp_path / "private", pins)
    roles = ("low-obj", "low-mtl", "low-record", "intermediates-record", "centre-record")
    given = {r: files[r] for r in roles}
    with pytest.raises(MissingInputs) as refused:
        current_request(assets, store, given, pins)
    assert refused.value.missing == sorted(
        ["ao", "ao-record", "ao-map-record", "masks-record", *MASK_BITMAPS]
    )
    assert store.index() == set()

    inputs = tmp_path / "inputs.json"
    inputs.write_text(json.dumps({"schema": INPUTS_SCHEMA, "files": given}), encoding="utf-8")
    target = tmp_path / "out" / "sash-v5-current.json"
    command = ["request", "--assets-root", str(assets), "--out", str(target)]
    monkeypatch.setattr(sash_current, "PINS", pins)
    assert sash_current.main([*command, "--store", str(store.root), "--inputs", str(inputs)]) == 2
    assert not target.exists()
    printed = capsys.readouterr().err
    assert json.loads(printed[printed.index("{") :])["missing"] == refused.value.missing
    assert store.index() == set()


def test_without_an_inputs_file_every_private_input_is_missing(
    mask_round: tuple[Path, Pins], store: OracleStore
) -> None:
    assets, pins = mask_round
    with pytest.raises(MissingInputs) as refused:
        current_request(assets, store, None, pins)
    assert refused.value.missing == sorted(
        ["low-obj", "low-mtl", "ao", *sash_current.RECEIPTS, *MASK_BITMAPS]
    )


def replace_blob(pins: Pins, input_id: str, **changes: str) -> Pins:
    blobs = tuple(
        dataclasses.replace(b, **changes) if b.input_id == input_id else b for b in pins.blobs
    )
    return dataclasses.replace(pins, blobs=blobs)


def test_a_script_absent_at_the_snapshot_is_missing_and_other_bytes_refuse(
    mask_round: tuple[Path, Pins], store: OracleStore, tmp_path: Path
) -> None:
    assets, pins = mask_round
    files = private_inputs(tmp_path / "private", pins)
    absent = replace_blob(pins, "production-run-py", path="Pipeline/production/gone.py")
    with pytest.raises(MissingInputs) as refused:
        current_request(assets, store, files, absent)
    assert refused.value.missing == [f"Pipeline/production/gone.py@{pins.snapshot[:8]}"]
    other = replace_blob(pins, "production-run-py", sha256="0" * 64)
    with pytest.raises(RecorderError, match=r"run\.py at Assets3D .* not the pinned 0{64}"):
        current_request(assets, store, files, other)
    assert store.index() == set()


def edited(files: Files, role: str, data: bytes) -> Files:
    """`role`'s file replaced by `data`, its entry re-pinned."""
    path = Path(files[role]["file"])
    path.write_bytes(data)
    return {**files, role: {**files[role], "sha256": sha256(data)}}


def record_edited(files: Files, role: str, change: Callable[[dict[str, Any]], None]) -> Files:
    record = json.loads(Path(files[role]["file"]).read_bytes())
    change(record)
    return edited(files, role, json.dumps(record).encode("utf-8"))


def png_bytes(files: Files, role: str) -> bytes:
    return Path(files[role]["file"]).read_bytes()


def corrupt_idat(data: bytes) -> bytes:
    at = data.index(b"IDAT") + 6
    return data[:at] + bytes([data[at] ^ 0xFF]) + data[at + 1 :]


def setting(value: Any, *path: str | int) -> Callable[[dict[str, Any]], None]:
    def change(record: Any) -> None:
        for key in path[:-1]:
            record = record[key]
        record[path[-1]] = value

    return change


def drop_output(name: str) -> Callable[[dict[str, Any]], None]:
    def change(record: dict[str, Any]) -> None:
        record["outputs"] = [o for o in record["outputs"] if o["name"] != name]

    return change


def note_only(record: dict[str, Any]) -> None:
    """M_hem's output moved into a free-text note: a hash merely present does not count."""
    (output,) = [o for o in record["outputs"] if o["name"] == "M_hem"]
    record["outputs"].remove(output)
    record["note"] = f"M_hem {output['sha256']}"


def source_of(record: dict[str, Any], module: str) -> int:
    return next(i for i, s in enumerate(record["sources"]) if s["module"] == module)


def change_source(module: str, key: str, value: str) -> Callable[[dict[str, Any]], None]:
    def change(record: dict[str, Any]) -> None:
        record["sources"][source_of(record, module)][key] = value

    return change


CASES: list[tuple[Callable[[Files], Files], str]] = [
    # bitmaps: a complete PNG at its native depth, colour type and the pinned size
    (lambda f: edited(f, "M_hem", png(RES, 8, 2, 1)), r"`M_hem` is a 8x8 PNG of depth 8"),
    (lambda f: edited(f, "M_hem", png(4, 16, 0, 1)), r"`M_hem` is a 4x4 PNG"),
    (lambda f: edited(f, "ao", png(RES, 8, 0, 1)), r"`ao` is a 8x8 PNG of depth 8 and colour"),
    (lambda f: edited(f, "ao", b"not a png"), r"`ao` is not a complete PNG: no PNG signature"),
    (lambda f: edited(f, "ao", b"\x89PNG\r\n\x1a\n\x00\x00"), r"`ao` .*: truncated"),
    (lambda f: edited(f, "M_weave", png_bytes(f, "M_weave")[:-20]), r"`M_weave` .*: truncated"),
    (
        lambda f: edited(f, "M_weave", corrupt_idat(png_bytes(f, "M_weave"))),
        r"`M_weave` .*: the b'IDAT' chunk fails its CRC",
    ),
    # N's and P's records, by their typed fields
    (
        lambda f: record_edited(f, "low-record", setting("other/1", "exporter")),
        r"`low-record` `exporter` is 'other/1'",
    ),
    (
        lambda f: record_edited(f, "low-record", setting("0" * 64, "source", "sha256")),
        r"`low-record` `source.sha256`",
    ),
    (
        lambda f: record_edited(
            f, "intermediates-record", setting("1" * 64, "low_game", "table_sha256")
        ),
        r"`intermediates-record` `low_game.table_sha256`",
    ),
    (
        lambda f: record_edited(f, "intermediates-record", setting("1" * 64, "normal", "sha256")),
        r"`intermediates-record` `normal.sha256`",
    ),
    (
        lambda f: record_edited(f, "ao-record", setting("1" * 64, "extraction", "record_sha256")),
        r"`ao-record` `extraction.record_sha256`",
    ),
    (
        lambda f: record_edited(f, "centre-record", setting("missing", "status")),
        r"`centre-record` `status` is 'missing', not 'derived-from-preserved-geometry'",
    ),
    (
        lambda f: record_edited(f, "centre-record", setting("authored", "status")),
        r"`centre-record` `status` is 'authored'",
    ),
    (
        lambda f: record_edited(f, "centre-record", setting("2" * 64, "donors", WAIST_GEN)),
        r"`centre-record` `donors\.Pipeline/retopology/waist-v5/waist_gen\.py`",
    ),
    # T's masks record, in T's shape
    (
        lambda f: record_edited(f, "masks-record", setting("produced", "status")),
        r"`masks-record` `status` is 'produced', not 'reproduced'",
    ),
    (
        lambda f: record_edited(f, "masks-record", setting("differs", "repeat", "result")),
        r"`masks-record` `repeat.result`",
    ),
    (
        lambda f: record_edited(
            f, "masks-record", change_source("waist_masks", "sha256", "3" * 64)
        ),
        r"`masks-record` `sha256` is '3{64}'",
    ),
    (
        lambda f: record_edited(f, "masks-record", change_source("waist_gen", "sha256", "4" * 64)),
        r"`masks-record` `sha256` is '4{64}'",
    ),
    (
        lambda f: record_edited(
            f, "masks-record", change_source("waist_gen", "checkout_sha256", "5" * 64)
        ),
        r"`masks-record` `checkout_sha256` is '5{64}'",
    ),
    (
        lambda f: record_edited(f, "masks-record", change_source("waist_gen", "commit", "c" * 40)),
        r"`masks-record` `commit`",
    ),
    (
        lambda f: record_edited(f, "masks-record", setting(1024, "parameters", "resolution")),
        r"`masks-record` `parameters.resolution` is 1024",
    ),
    (
        lambda f: record_edited(
            f, "masks-record", setting("6" * 64, "receipts", "extraction", "sha256")
        ),
        r"`masks-record` `receipts.extraction.sha256`",
    ),
    (
        lambda f: record_edited(f, "masks-record", setting("7" * 64, "arrays", "ao.npy", "sha256")),
        r"`masks-record` `arrays.ao.npy.sha256`",
    ),
    (lambda f: record_edited(f, "masks-record", drop_output("M_cloth")), r"`outputs` must be"),
    (lambda f: record_edited(f, "masks-record", note_only), r"`outputs` must be"),
    (
        lambda f: record_edited(f, "masks-record", setting("auxiliary", "outputs", 1, "role")),
        r"`masks-record M_weave` `role` is 'auxiliary'",
    ),
    (
        lambda f: record_edited(f, "masks-record", setting(1, "outputs", 2, "size_bytes")),
        r"`masks-record M_hem` `size_bytes` is 1",
    ),
    (
        lambda f: record_edited(f, "masks-record", setting(["M_hem"], "stack_inputs")),
        r"`masks-record` `stack_inputs` must be",
    ),
    (lambda f: edited(f, "masks-record", b"not json"), r"`masks-record` is not a JSON record"),
    # the AO map's record
    (
        lambda f: record_edited(
            f, "ao-map-record", setting("8" * 64, "inputs", "ao.npy", "sha256")
        ),
        r"`ao-map-record` `inputs`",
    ),
    (
        lambda f: record_edited(f, "ao-map-record", setting("produced", "status")),
        r"`ao-map-record` `status` is 'produced', not 'reproduced'",
    ),
    (
        lambda f: record_edited(f, "ao-map-record", setting("9" * 64, "donor", "sha256")),
        r"`ao-map-record` `donor.sha256`",
    ),
    (
        lambda f: record_edited(f, "ao-map-record", setting("", "donor", "line")),
        r"`ao-map-record` `donor.line` is not the donor's conversion line",
    ),
    (
        lambda f: record_edited(f, "ao-map-record", setting(8, "outputs", AO_PNG, "depth")),
        r"`ao-map-record` `outputs.25-Faixa-Cintura_AO_v5.png.depth` is 8",
    ),
    # the inputs file itself
    (lambda f: {**f, "low-obj": {**f["low-obj"], "sha256": "1" * 64}}, "not front N's"),
    (lambda f: {**f, "M_cloth": f["M_hem"]}, r"unknown roles \['M_cloth'\]"),
]


@pytest.mark.parametrize(("change", "refusal"), CASES)
def test_a_wrong_png_record_or_link_refuses_before_storing(
    mask_round: tuple[Path, Pins],
    store: OracleStore,
    tmp_path: Path,
    change: Callable[[Files], Files],
    refusal: str,
) -> None:
    assets, pins = mask_round
    files = change(private_inputs(tmp_path / "private", pins))
    with pytest.raises(RecorderError, match=refusal):
        current_request(assets, store, files, pins)
    assert store.index() == set()


def test_a_private_file_with_other_bytes_refuses(
    mask_round: tuple[Path, Pins], store: OracleStore, tmp_path: Path
) -> None:
    assets, pins = mask_round
    files = private_inputs(tmp_path / "private", pins)
    Path(files["M_weave"]["file"]).write_bytes(png(RES, 16, 0, 99))
    with pytest.raises(RecorderError, match=r"`M_weave`: .* is not the bytes"):
        current_request(assets, store, files, pins)


def test_a_stack_of_other_bitmaps_refuses(
    mask_round: tuple[Path, Pins], store: OracleStore, tmp_path: Path
) -> None:
    assets, pins = mask_round
    files = private_inputs(tmp_path / "private", pins)
    files["M_extra"] = {**files["M_hem"]}
    other = dataclasses.replace(pins, bitmaps=(*MASK_BITMAPS, "M_extra"))
    with pytest.raises(RecorderError, match="the stack's bitmaps are"):
        current_request(assets, store, files, other)


def test_the_real_request_with_its_twenty_bitmaps_passes_the_public_schema(
    tmp_path: Path,
) -> None:
    """The contract's 19 masks and T_sash, by folder: with the masks' records the checks accept
    (and a placeholder colour record, which only names T_sash's note), the request is a valid
    public manifest (as parallel lists, 20 items exceed the schema's bound of 16)."""
    masks_only = tuple(b for b in sash_current.BITMAPS if b != sash_current.COLOUR)
    pins = dataclasses.replace(sash_current.PINS, bitmaps=masks_only, resolution=RES)
    files = private_inputs(tmp_path / "private", pins)
    found = {role: Found(e["sha256"], file=Path(e["file"])) for role, e in files.items()}
    records = sash_current.check_receipts(files, found, pins)
    records["colour-record"] = {"schema": "placeholder/1"}
    for role in ("colour-record", "T_sash", *SWATCHES):
        files[role] = {"sha256": hexes(role)}
        found[role] = Found(hexes(role), data=b"")
    for name in ("painter-create-args", "painter-export-args"):
        found[name] = Found("e" * 64, data=b"")
    manifest = sash_current.request_manifest(found, files, records, sash_current.PINS)
    assert validation_errors(manifest, Schema.GOLDEN_PUBLIC) == []
    masks = [i for i in manifest["inputs"] if i["assets3d_path"].startswith(MASKS + "/")]
    assert len(masks) == len(sash_current.BITMAPS) == 20


def test_the_inputs_file_must_have_its_shape(tmp_path: Path) -> None:
    path = tmp_path / "inputs.json"
    for document in (
        {"schema": "other", "files": {}},
        {"schema": INPUTS_SCHEMA, "files": {}, "extra": 1},
        {"schema": INPUTS_SCHEMA, "files": {"ao": {"sha256": "x", "receipt": "y"}}},
        {"schema": INPUTS_SCHEMA, "files": {"ao": {"file": "x"}}},
    ):
        path.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises(RecorderError):
            sash_current.load_inputs(path)


# --- the real pins, closure and producer records --------------------------------------------


def real_assets() -> Path:
    if not (REAL_ASSETS / ".git").exists():
        pytest.skip(f"the UzmiGames asset repository is not at {REAL_ASSETS}")
    return REAL_ASSETS


def test_the_real_pins_are_the_snapshot_blobs_and_the_round_still_misses_its_substitutes(
    tmp_path: Path,
) -> None:
    """Every script pin is the raw blob at 1c9a312a and the Normal is the file under Textures; with
    no private inputs file the request is refused, naming only the private roles, and nothing is
    stored."""
    assets = real_assets()
    store = OracleStore.init(tmp_path / "store")
    with pytest.raises(MissingInputs) as refused:
        current_request(assets, store, None)
    assert refused.value.missing == sorted(
        [
            "low-obj",
            "low-mtl",
            "ao",
            *sash_current.RECEIPTS,
            "colour-record",
            *sash_current.BITMAPS,
            *SWATCHES,
        ]
    )
    assert store.index() == set()


def test_the_real_waist_gen_blob_is_the_centre_donors_checkout_in_crlf() -> None:
    """The masks producer runs waist_gen.py's raw blob; P's centre donor cites the checkout: the
    pinned checkout hash is that blob with every LF replaced by CRLF."""
    assets = real_assets()
    data = blob(assets, sash_current.SNAPSHOT, WAIST_GEN)
    (_, _, executed) = next(s for s in sash_current.MASK_SOURCES if s[0] == "waist_gen")
    assert sha256(data) == executed
    assert sha256(data.replace(b"\n", b"\r\n")) == sash_current.WAIST_GEN_CHECKOUT_SHA256
    for module, path, digest in sash_current.MASK_SOURCES:
        assert sha256(blob(assets, sash_current.SNAPSHOT, path)) == digest, module


def real_record(run: str, name: str) -> tuple[Any, str]:
    path = ORACLE_WORK / f"{REAL_RUNS}{run}" / name
    if not path.is_file():
        pytest.skip(f"{path} is not here")
    data = path.read_bytes()
    return json.loads(data), sha256(data)


def test_the_real_n_and_p_records_pass_their_typed_checks() -> None:
    """Front N's export record and front P's extraction, centre and AO r2 records (and the AO's
    independent repeat), read where their runs wrote them, pass the checks the request applies; a
    changed link in each is refused."""
    low, _ = real_record("low-r1", "export-record.json")
    extract, extract_sha256 = real_record("intermediates-r1", "intermediates-record.json")
    centre, _ = real_record("centre-r1", "intermediates-record.json")
    pins = sash_current.PINS
    sash_current.check_low(low, pins)
    sash_current.check_extract(extract, low, pins)
    sash_current.check_centre(centre, extract_sha256)
    assert centre["donors"][WAIST_GEN] == sash_current.WAIST_GEN_CHECKOUT_SHA256
    for run in ("ao-r2", "ao-r2-repeat"):  # P's AO and its independent repeat
        ao, _ = real_record(run, "intermediates-record.json")
        sash_current.check_ao(ao, extract_sha256)
        assert ao["outputs"]["ao.npy"]["sha256"] == (
            "58440cda9c742ba3768d75965209e78f8df83c10f8ced3c29d66c0e98443413c"
        )
    changed = copy.deepcopy(extract)
    changed["low_game"]["obj_sha256"] = "0" * 64
    with pytest.raises(RecorderError, match=r"low_game\.obj_sha256"):
        sash_current.check_extract(changed, low, pins)
    with pytest.raises(RecorderError, match=r"extraction\.record_sha256"):
        sash_current.check_centre(centre, "0" * 64)


def test_the_real_sync_closure_loads_from_its_pinned_blobs(tmp_path: Path) -> None:
    """The pinned sync, run.py and its two helpers at 1c9a312a: the closure resolves, loads helpers
    first, run.py's `locate` and `owner_preview_paint` work from their pinned bytes, the sync
    defines its probes and the three option flags, and `sys.modules` and `sys.path` come back."""
    assets = real_assets()
    mirror = tmp_path / "mirror"
    write(mirror / "AGENTS.md", "staged\n")
    pinned: dict[str, PinnedInput] = {}
    for item in BLOBS:
        data = blob(assets, sash_current.SNAPSHOT, item.path)
        assert sha256(data) == item.sha256
        write(mirror / item.path, data)
        pinned[item.input_id] = PinnedInput(
            item.input_id, item.kind, item.path, item.sha256, mirror / item.path, data
        )
    script = pinned["painter-layer-stack-py"]
    order = script_run.import_closure(
        2, script, (pinned["production-run-py"],), list(sash_current.CLOSURE), pinned
    )
    assert [m.input_id for m in order] == [
        "decision-evidence-py",
        "stage-review-evidence-py",
        "production-run-py",
    ]
    assert script_run.sync_options(2, dict(sash_current.SYNC_OPTIONS), script) == (
        ("--resource-prefix", "v5f_"),
        ("--resource-group", "faixa25_v5"),
        ("--texture-set", "25-Faixa-Cintura"),
    )
    names = [m.module for m in order]
    saved = {name: sys.modules.get(name) for name in names}
    path = list(sys.path)
    try:
        for loaded in order:
            sys.modules[loaded.module] = script_run.pinned_module(loaded, loaded.file)
        run = sys.modules["run"]
        assert run.locate(str(tmp_path / "work")) == ("legacy", None)
        assert run.owner_preview_paint(str(tmp_path / "work")) is False
        namespace: dict[str, Any] = {"__name__": "uzp_check", "__file__": str(script.file)}
        assert script.data is not None
        exec(compile(script.data, str(script.file), "exec", dont_inherit=True), namespace)
        assert isinstance(namespace["PROJECT_PROBE_CODE"], str)
        assert "__TS__" in namespace["GUARD_CODE"]
        assert namespace["locate"] is run.locate
    finally:
        sys.path[:] = path
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    assert PurePosixPath(script.assets3d_path).name == "painter_layer_stack.py"
