"""glTF exports preserve non-image outputs and reject unsafe or unknown files."""

from __future__ import annotations

import hashlib
import json
import os
import struct
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator

from tools.parity.recorder.capture import StaleCaptureError
from tools.parity.recorder.job import ExportProbe
from tools.parity.recorder.output import write_run
from tools.parity.recorder.session import PainterSession, RecorderError
from tools.parity.recorder.sidecars import gltf_sidecars
from tools.parity.recorder.texture import probe_outputs
from tools.parity.schemas import REPO_ROOT, Schema, load_schema


class SidecarSession:
    def __init__(
        self, uri: str = "mesh.bin", length: int = 4, extra: bool = False, stale: bool = False
    ):
        self.uri, self.length, self.extra, self.stale = uri, length, extra, stale

    def wait_ready(self) -> None:
        pass

    def call(self, operation: str, **args: Any) -> dict[str, Any]:
        root = Path(args["config"]["exportPath"])
        if operation == "export_textures":
            (root / "mesh.bin").write_bytes(b"mesh")
            (root / "scene.gltf").write_text(
                json.dumps(
                    {
                        "asset": {"version": "2.0"},
                        "buffers": [{"uri": self.uri, "byteLength": self.length}],
                    }
                ),
                encoding="utf-8",
            )
            if self.extra:
                (root / "unknown.txt").write_text("unknown", encoding="utf-8")
            if self.stale:
                os.utime(root / "mesh.bin", ns=(1, 1))
        return {"textures": [], "status": "Success", "message": ""}


def capture(tmp_path: Path, **options: Any) -> tuple[list[dict[str, Any]], list[Path]]:
    session = cast(PainterSession, SidecarSession(**options))
    return probe_outputs(session, ExportProbe(1, "gltf", {}), tmp_path)


def test_gltf_sidecars_are_hashed_and_schema_valid_without_pixel_claims(tmp_path: Path) -> None:
    outputs, blobs = capture(tmp_path)
    assert len(blobs) == 2
    assert outputs[1]["value"]["directory"] == {
        "missing": [],
        "unlisted": ["mesh.bin", "scene.gltf"],
    }
    schema = load_schema(Schema.GOLDEN_PRIVATE)
    validator = Draft202012Validator({"$defs": schema["$defs"], "$ref": "#/$defs/output"})
    for output, path in zip(outputs[2:], blobs, strict=True):
        assert output["kind"] == "exported_sidecar"
        assert "storage_format" not in output
        assert output["blob"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert not list(validator.iter_errors(output))
    assert [o["blob"]["media_type"] for o in outputs[2:]] == [
        "application/octet-stream",
        "model/gltf+json",
    ]


@pytest.mark.parametrize(
    "uri",
    [
        "../mesh.bin",
        "%2e%2e/mesh.bin",
        "https://example.com/mesh.bin",
        "missing.bin",
        "C:/mesh.bin",
        "mesh.bin?q=1",
    ],
)
def test_gltf_sidecars_refuse_external_or_missing_buffers(tmp_path: Path, uri: str) -> None:
    with pytest.raises(RecorderError, match="glTF buffer"):
        capture(tmp_path, uri=uri)


def test_gltf_sidecars_refuse_wrong_buffer_length(tmp_path: Path) -> None:
    with pytest.raises(RecorderError, match="byteLength mismatch"):
        capture(tmp_path, length=5)


def test_gltf_sidecars_do_not_admit_unknown_files(tmp_path: Path) -> None:
    with pytest.raises(RecorderError, match="container not supported"):
        capture(tmp_path, extra=True)


def test_gltf_sidecars_keep_the_export_fence(tmp_path: Path) -> None:
    with pytest.raises(StaleCaptureError, match="before export"):
        capture(tmp_path, stale=True)


def glb_bytes() -> bytes:
    document = json.dumps({"asset": {"version": "2.0"}, "buffers": [{"byteLength": 3}]}).encode()
    document += b" " * (-len(document) % 4)
    chunks = struct.pack("<II", len(document), 0x4E4F534A) + document
    chunks += struct.pack("<II", 4, 0x004E4942) + b"abc\0"
    return struct.pack("<III", 0x46546C67, 2, 12 + len(chunks)) + chunks


def test_glb_sidecar_validates_container_and_embedded_buffer(tmp_path: Path) -> None:
    path = tmp_path / "scene.glb"
    path.write_bytes(glb_bytes())
    assert gltf_sidecars([path], tmp_path) == {path: "model/gltf-binary"}


@pytest.mark.parametrize("damage", ["truncate", "version", "chunk", "buffer"])
def test_glb_sidecar_refuses_malformed_container(tmp_path: Path, damage: str) -> None:
    data = bytearray(glb_bytes())
    if damage == "truncate":
        data.pop()
    elif damage == "version":
        struct.pack_into("<I", data, 4, 1)
    elif damage == "chunk":
        struct.pack_into("<I", data, 12, 1)
    else:
        data = data.replace(b'"byteLength": 3', b'"byteLength": 9')
    path = tmp_path / "scene.glb"
    path.write_bytes(data)
    with pytest.raises(RecorderError, match="GLB"):
        gltf_sidecars([path], tmp_path)


def test_sidecars_publish_normal_inbox_records_and_public_hashes(tmp_path: Path) -> None:
    outputs, blobs = capture(tmp_path / "capture")
    samples = REPO_ROOT / "parity/schema/samples"
    record = json.loads((samples / "private/exported-map-record.json").read_text(encoding="utf-8"))
    manifest = json.loads(
        (samples / "public/tier0-blend-multiply.json").read_text(encoding="utf-8")
    )
    manifest["golden_id"] = record["golden_id"]
    manifest["software"]["painter"] = record["key"]["painter_build"]
    for recording in record["recordings"]:
        recording["outputs"] = outputs
    run = write_run(tmp_path / "inbox", record, blobs, manifest, "sidecar-test")
    published = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    sidecars = [ref for ref in published["private_records"] if ref["kind"] == "exported_sidecar"]
    assert len(sidecars) == 4
    assert {ref["sha256"] for ref in sidecars} == {
        hashlib.sha256(p.read_bytes()).hexdigest() for p in blobs
    }
    assert (run / "READY").is_file()
