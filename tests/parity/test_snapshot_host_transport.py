"""Offline H transport of authored snapshot recordings; no Painter, private data or pixels."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from python.uzpainter_snapshot import bridge
from tools.parity import snapshot_host_transport as transport

RESOURCE = "resource://authored/host?version=1"
UUID = "6f1c2a3e-0000-4000-8000-0000000a3633"
PINS = {
    "bridge_sha256": hashlib.sha256(b"authored bridge").hexdigest(),
    "painter_side_sha256": hashlib.sha256(b"authored painter side").hexdigest(),
}
SCALAR = b"authored scalar export"
RGB = b"authored rgb export"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def readback() -> dict[str, Any]:
    source = {
        "resource": RESOURCE,
        "parameters": {"amount": 0.5, "$randomseed": 0},
        "inputs": [],
        "outputs": ["scalar"],
        "active_output": "scalar",
        "resolution": {"mode": "Auto", "log2_offset": 0},
        "opacity": 1,
        "blending": "Normal",
    }
    return {
        "channel_formats": {"User0": "L32F", "User1": "RGB32F"},
        "source_mode": "Split",
        "projection_mode": "UV",
        "active_channels": ["User0", "User1"],
        "projection": {
            "filtering": "Nearest",
            "wrapping": "RepeatNone",
            "scale_mode": "Factors",
            "scale": [1, 1],
            "rotation": 0,
            "offset": [0, 0],
        },
        "isolated_tree": {
            "roots": [7],
            "fill": 7,
            "visible": True,
            "mask": False,
            "content_effects": [],
            "mask_effects": [],
        },
        "sets": [{"name": "uzp_plane", "resolution": [128, 128], "has_uv_tiles": False}],
        "sources": [deepcopy(source), deepcopy(source)],
    }


Mutation = Callable[[Path, dict[str, Any], dict[str, Any], dict[str, Any]], None]


def record(tmp_path: Path, mutate: Mutation | None = None) -> Path:
    """An authored recording laid out as `RunSnapshotCommand` and `bridge.main` write it."""
    work = tmp_path / "4242-1000"
    work.mkdir(parents=True)
    settings = {"resolution": 128}
    context = {
        "project_uuid": UUID,
        "revision": 3,
        "settings": settings,
        "mesh_path": (work / "mesh.obj").as_posix(),
        **PINS,
    }
    request = {"resource": RESOURCE, "parameters": {"amount": 0.5}}
    (work / "mesh.obj").write_bytes(b"authored plane")
    exports = []
    for index in (1, 2):
        directory = work.resolve() / f"export{index}"
        directory.mkdir()
        (directory / "user0.exr").write_bytes(SCALAR)
        (directory / "user1.exr").write_bytes(RGB)
        exports.append(
            {
                "config": bridge.export_config(directory),
                "result": {
                    "status": "Success",
                    "message": "",
                    "files": [str(directory / "user0.exr"), str(directory / "user1.exr")],
                },
            }
        )
    receipt: dict[str, Any] = {
        "schema": "uzpainter/procedural-capture/1",
        "recorder": dict(PINS),
        "identity": {
            "pid": 4242,
            "version": "12.2.0",
            "OCIO": None,
            "PAINTER_ACE_CONFIG": None,
            "project_open": False,
            "mesh": None,
        },
        "resource": RESOURCE,
        "readback": readback(),
        "exports": exports,
        "project_uuid": UUID,
        "revision": 3,
        "signature": {
            "asset": "uzasset://snapshot/" + sha(RESOURCE.encode("utf-8")),
            "version": "1",
            "params": {"amount": 0.5, "$randomseed": 0},
            "preset": None,
            "seed": 0,
            "output": {
                "id": "scalar",
                "resolution": 128,
                "format": "f32",
                "colour_space": "raw",
                "channels": 1,
            },
            "inputs": {},
            "mesh": {"class": "quad", "uv_tiles": 1},
            "settings": settings,
        },
        "files": {
            f"export{i}/{name}.exr": sha(data)
            for i in (1, 2)
            for name, data in (("user0", SCALAR), ("user1", RGB))
        },
    }
    if mutate is not None:
        mutate(work, context, request, receipt)
    (work / "context.json").write_text(json.dumps(context, sort_keys=True), encoding="utf-8")
    (work / "request.json").write_text(json.dumps(request, sort_keys=True), encoding="utf-8")
    # As `bridge.main` writes it: indented text, so the receipt bytes are not canonical JSON.
    (work / "capture.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return work


def test_recording_maps_to_the_host_section(tmp_path: Path) -> None:
    work = record(tmp_path)
    result = transport.host_transport(work)
    receipt = (work / "capture.json").read_bytes()
    request = (work / "request.json").read_bytes()
    assert result.section == {
        "protocol": "paired-scalar-rgb",
        "receipt": {"kind": "snapshot_receipt", "sha256": sha(receipt), "size_bytes": len(receipt)},
        "request": {"kind": "snapshot_request", "sha256": sha(request), "size_bytes": len(request)},
        "environment": None,
        "environment_binding": None,
        "scalar_exports": [
            {"kind": "snapshot_scalar_export", "sha256": sha(SCALAR), "size_bytes": len(SCALAR)}
        ]
        * 2,
        "rgb_exports": [{"kind": "snapshot_rgb_export", "sha256": sha(RGB), "size_bytes": len(RGB)}]
        * 2,
    }
    assert result.paths == {
        sha(receipt): work / "capture.json",
        sha(request): work / "request.json",
        sha(SCALAR): work / "export2/user0.exr",
        sha(RGB): work / "export2/user1.exr",
    }
    assert all(
        path.read_bytes() and sha(path.read_bytes()) == key for key, path in result.paths.items()
    )
    assert result.recorder == PINS
    source_paths = [
        work / name for name in ("capture.json", "request.json", "context.json", "mesh.obj")
    ] + [work / f"export{i}" / name for i in (1, 2) for name in transport.EXPORT_NAMES]
    assert result.source_fingerprints == {
        path: (sha(path.read_bytes()), len(path.read_bytes())) for path in source_paths
    }
    assert str(work) not in repr(result)


@pytest.mark.parametrize("name", ["context.json", "mesh.obj"])
def test_fingerprints_describe_bytes_read_not_later_disk_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    work = record(tmp_path)
    path = work / name
    baseline = path.read_bytes()
    original = Path.read_bytes

    def transient_read(self: Path) -> bytes:
        data = original(self)
        return data + b" " if self == path else data

    monkeypatch.setattr(Path, "read_bytes", transient_read)
    result = transport.host_transport(work)
    assert result.source_fingerprints[path] == (sha(baseline + b" "), len(baseline) + 1)
    assert original(path) == baseline


def test_a_relocated_recording_keeps_its_recorded_root(tmp_path: Path) -> None:
    recorded = record(tmp_path / "recorded")
    expected = transport.host_transport(recorded).section
    moved = tmp_path / "retained" / recorded.name
    moved.parent.mkdir()
    recorded.rename(moved)
    assert transport.host_transport(moved).section == expected
    renamed = moved.with_name("4242-1001")
    moved.rename(renamed)
    with pytest.raises(transport.TransportRefused, match="mesh is not this recording's"):
        transport.host_transport(renamed)


def test_the_receipt_reference_is_its_original_bytes(tmp_path: Path) -> None:
    work = record(tmp_path)
    original = (work / "capture.json").read_bytes()
    canonical = json.dumps(json.loads(original), sort_keys=True, separators=(",", ":")).encode()
    assert canonical != original
    assert transport.host_transport(work).section["receipt"]["sha256"] == sha(original)
    (work / "capture.json").write_bytes(canonical)
    assert transport.host_transport(work).section["receipt"]["sha256"] == sha(canonical)


def _set(target: str, key: str, value: Any) -> Mutation:
    def mutate(
        work: Path, context: dict[str, Any], request: dict[str, Any], receipt: dict[str, Any]
    ) -> None:
        {"context": context, "request": request, "receipt": receipt}[target][key] = value

    return mutate


def _extra_root_file(work: Path, *_: Any) -> None:
    (work / "bridge.log").write_text("authored", encoding="utf-8")


def _extra_export_file(work: Path, *_: Any) -> None:
    (work / "export1" / "user2.exr").write_bytes(b"x")


def _missing_mesh(work: Path, *_: Any) -> None:
    (work / "mesh.obj").unlink()


def _changed_export(work: Path, *_: Any) -> None:
    (work / "export2" / "user1.exr").write_bytes(b"changed")


def _other_override(work: Path, context: Any, request: dict[str, Any], receipt: Any) -> None:
    request["parameters"] = {"amount": 0.25}


def _other_recording_export(work: Path, context: Any, request: Any, receipt: Any) -> None:
    receipt["exports"][1]["config"] = bridge.export_config(work.parent / "other" / "export2")


def _failed_export(work: Path, context: Any, request: Any, receipt: Any) -> None:
    receipt["exports"][0]["result"]["status"] = "Error"


def _extra_export_result(work: Path, context: Any, request: Any, receipt: Any) -> None:
    receipt["exports"][0]["result"]["files"].append(str(work / "export1" / "user2.exr"))


def _other_signature_params(work: Path, context: Any, request: Any, receipt: Any) -> None:
    receipt["signature"]["params"] = {"amount": 0.5, "$randomseed": 1}


def _open_project(work: Path, context: Any, request: Any, receipt: Any) -> None:
    receipt["identity"]["project_open"] = True


def _same_name_other_root(work: Path) -> Path:
    return work.parent / "elsewhere" / work.name


def _export_under_other_root(work: Path, context: Any, request: Any, receipt: Any) -> None:
    directory = _same_name_other_root(work) / "export2"
    receipt["exports"][1]["config"] = bridge.export_config(directory)
    receipt["exports"][1]["result"]["files"] = [
        str(directory / n) for n in ("user0.exr", "user1.exr")
    ]


def _mesh_under_other_root(work: Path, context: dict[str, Any], request: Any, receipt: Any) -> None:
    context["mesh_path"] = (_same_name_other_root(work) / "mesh.obj").as_posix()


def _other_mesh(work: Path, context: dict[str, Any], request: Any, receipt: Any) -> None:
    context["mesh_path"] = (work.parent / "other" / "mesh.obj").as_posix()


def _unpaired_readback(work: Path, context: Any, request: Any, receipt: Any) -> None:
    receipt["readback"]["sources"][1]["opacity"] = 0.5


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (_extra_root_file, "recording entries differ"),
        (_extra_export_file, "export1 entries differ"),
        (_missing_mesh, "recording entries differ"),
        (_changed_export, "receipt files differ from the exports"),
        (_set("context", "bridge_sha256", "0" * 64), "recorder pins differ"),
        (_set("context", "project_uuid", "6f1c2a3e-0000-4000-8000-000000000000"), "project_uuid"),
        (_set("context", "revision", 4), "receipt revision differs"),
        (_set("context", "revision", 3.0), "receipt revision differs"),
        (_set("receipt", "resource", "resource://authored/other?version=1"), "resource differs"),
        (_set("request", "resource", "resource://authored/other?version=1"), "capture domain"),
        (_set("request", "resource", "resource://authored/host"), "capture domain"),
        (_other_override, "capture domain"),
        (_unpaired_readback, "capture domain"),
        (_set("receipt", "schema", "uzpainter/procedural-capture/2"), "schema differs"),
        (_set("receipt", "environment", None), "receipt members differ"),
        (_other_recording_export, "not this recording's directory"),
        (_export_under_other_root, "not this recording's directory"),
        (_mesh_under_other_root, "not this recording's directory"),
        (_failed_export, "export round failed"),
        (_extra_export_result, "names other files"),
        (_other_signature_params, "signature is not the one the bridge derived"),
        (_open_project, "Legacy capture identity"),
        (_other_mesh, "mesh is not this recording's"),
    ],
)
def test_recording_refusals(tmp_path: Path, mutate: Mutation, reason: str) -> None:
    work = record(tmp_path, mutate)
    with pytest.raises(transport.TransportRefused, match=reason):
        transport.host_transport(work)


def test_receipt_json_is_strict(tmp_path: Path) -> None:
    work = record(tmp_path)
    text = (work / "capture.json").read_text(encoding="utf-8")
    (work / "capture.json").write_text(text.replace('"revision": 3', '"revision": NaN'), "utf-8")
    with pytest.raises(transport.TransportRefused, match="non-finite"):
        transport.host_transport(work)
    (work / "capture.json").write_text("{" + '"schema": 1, ' + text[1:], encoding="utf-8")
    with pytest.raises(transport.TransportRefused, match="duplicate JSON key"):
        transport.host_transport(work)


@pytest.mark.parametrize(
    ("token", "reason"),
    [
        ("1e309", "non-finite"),
        ("-1e309", "non-finite"),
        ("1e-999", "underflow"),
        ("NaN", "non-finite"),
    ],
)
def test_the_parser_refuses_numbers_it_cannot_keep(token: str, reason: str) -> None:
    with pytest.raises(transport.TransportRefused, match=reason):
        transport.parse_object(('{"x": ' + token + "}").encode(), "authored")


def test_the_parser_keeps_typed_zeros_and_values() -> None:
    parsed = transport.parse_object(b'{"a": -0.0, "b": 0e-999, "c": 0, "d": 1e-300}', "authored")
    assert parsed == {"a": 0.0, "b": 0.0, "c": 0, "d": 1e-300}
    assert math.copysign(1.0, parsed["a"]) == -1.0 and type(parsed["c"]) is int


@pytest.mark.parametrize(
    ("file", "old", "new", "reason"),
    [
        ("request.json", '"amount": 0.5', '"amount": 1e-999', "underflow"),
        ("capture.json", '"pid": 4242', '"pid": 1e309', "non-finite"),
    ],
)
def test_a_recording_with_an_unkept_number_is_refused(
    tmp_path: Path, file: str, old: str, new: str, reason: str
) -> None:
    work = record(tmp_path)
    text = (work / file).read_text(encoding="utf-8")
    assert text.count(old) == 1
    (work / file).write_text(text.replace(old, new), encoding="utf-8")
    with pytest.raises(transport.TransportRefused, match=reason):
        transport.host_transport(work)


def test_a_signed_zero_override_is_kept(tmp_path: Path) -> None:
    def zero(work: Path, context: Any, request: dict[str, Any], receipt: dict[str, Any]) -> None:
        request["parameters"] = {"amount": -0.0}
        for source in receipt["readback"]["sources"]:
            source["parameters"]["amount"] = -0.0
        receipt["signature"]["params"]["amount"] = -0.0

    work = record(tmp_path, zero)
    assert transport.host_transport(work).section["request"]["sha256"] == sha(
        (work / "request.json").read_bytes()
    )


@pytest.mark.parametrize("link", ["is_symlink", "is_junction"])
@pytest.mark.parametrize("entry", ["export1", "export1/user0.exr", "capture.json"])
def test_a_linked_entry_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, link: str, entry: str
) -> None:
    work = record(tmp_path)
    linked = work / entry
    original = getattr(Path, link)

    def guard(self: Path) -> bool:
        return self == linked or bool(original(self))

    monkeypatch.setattr(Path, link, guard)
    with pytest.raises(transport.TransportRefused, match="is a link"):
        transport.host_transport(work)


# --- recorder pin provenance (public Git only) -------------------------------------------------


def git(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=transport.REPO, capture_output=True, check=True
    ).stdout


@pytest.fixture(scope="module")
def head() -> str:
    return git("rev-parse", "HEAD").decode().strip()


def blob(revision: str, key: str) -> bytes:
    return git("show", f"{revision}:{transport.RECORDER_SOURCES[key]}")


def test_pins_name_the_approved_revision_with_explicit_line_endings(head: str) -> None:
    lf = {key: sha(blob(head, key)) for key in transport.RECORDER_SOURCES}
    assert transport.recorder_pin_provenance(lf, head) == transport.RecorderProvenance(
        head, {"bridge_sha256": "lf", "painter_side_sha256": "lf"}
    )
    mixed = dict(lf, bridge_sha256=sha(blob(head, "bridge_sha256").replace(b"\n", b"\r\n")))
    assert transport.recorder_pin_provenance(mixed, head).variants == {
        "bridge_sha256": "crlf",
        "painter_side_sha256": "lf",
    }


@pytest.mark.parametrize(
    "case", ["swapped", "edited source", "unrelated hash", "extra member", "uppercase"]
)
def test_pins_outside_the_approved_revision_are_refused(head: str, case: str) -> None:
    source = blob(head, "bridge_sha256")
    bridge_pin = sha(source)
    side_pin = sha(blob(head, "painter_side_sha256"))
    recorder = {
        "swapped": {"bridge_sha256": side_pin, "painter_side_sha256": bridge_pin},
        "edited source": {"bridge_sha256": sha(source + b"#"), "painter_side_sha256": side_pin},
        "unrelated hash": {"bridge_sha256": PINS["bridge_sha256"], "painter_side_sha256": side_pin},
        "extra member": {
            "bridge_sha256": bridge_pin,
            "painter_side_sha256": side_pin,
            "x": side_pin,
        },
        "uppercase": {"bridge_sha256": bridge_pin.upper(), "painter_side_sha256": side_pin},
    }[case]
    with pytest.raises(transport.TransportRefused):
        transport.recorder_pin_provenance(recorder, head)


@pytest.mark.parametrize("revision", ["HEAD", "main", "0" * 40])
def test_only_an_existing_full_commit_id_is_an_approved_revision(head: str, revision: str) -> None:
    lf = {key: sha(blob(head, key)) for key in transport.RECORDER_SOURCES}
    with pytest.raises(transport.TransportRefused, match="approved revision"):
        transport.recorder_pin_provenance(lf, revision)
    with pytest.raises(transport.TransportRefused, match="approved revision"):
        transport.recorder_pin_provenance(lf, head[:12])
