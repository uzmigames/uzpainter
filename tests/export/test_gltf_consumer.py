"""Authored CPU export consumed by fastgltf; not Painter/Wand parity evidence."""

from __future__ import annotations

import hashlib
import json
import shutil
import struct
import subprocess
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.export.test_export_encoders import TEMPLATES, chan
from tests.export.test_export_publication import one
from tools.consumers.gltf import _pixels, run_fixture
from tools.parity.feasibility import png

SIZE = 256
BINDINGS = {
    "baseColor": "s0_BaseColor.png",
    "metallicRoughness": "s0_MetallicRoughness.png",
    "normal": "s0_Normal.png",
    "occlusion": "s0_Occlusion.png",
    "emissive": "s0_Emissive.png",
}


@pytest.fixture(scope="session")
def gltf_consumer(tmp_path_factory: pytest.TempPathFactory) -> Path:
    zig = shutil.which("zig")
    assert zig is not None, "zig is required for the glTF consumer acceptance fixture"
    prefix = tmp_path_factory.mktemp("gltf-consumer")
    result = subprocess.run(
        [zig, "build", "gltf-consumer", "--prefix", str(prefix)],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3600,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return prefix / "bin" / "uzp-gltf-consumer.exe"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class Publication:
    root: Path
    mesh: Path
    references: dict[str, dict[str, str]]
    generation: Path

    def receipt(self) -> dict[str, Any]:
        result: dict[str, Any] = json.loads((self.generation / "receipt.json").read_bytes())
        return result

    def repin(self, receipt: dict[str, Any]) -> None:
        data = json.dumps(receipt).encode()
        (self.generation / "receipt.json").write_bytes(data)
        pointer = json.loads((self.root / "current.json").read_bytes())
        pointer["receipt_sha256"] = digest(data)
        (self.root / "current.json").write_text(json.dumps(pointer), encoding="utf-8")


@pytest.fixture
def publication(export_tests: Path, tmp_path: Path) -> Publication:
    source = tmp_path / "source"
    source.mkdir()
    mesh = source / "quad.obj"
    mesh.write_text(
        "o authored\nv 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\n"
        "vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\nvn 0 0 1\nusemtl s0\n"
        "f 1/1/1 2/2/1 3/3/1\nf 1/1/1 3/3/1 4/4/1\n",
        encoding="utf-8",
    )
    y, x = np.mgrid[:SIZE, :SIZE]
    planes = {"roughness": 32 + x % 64, "metallic": 160 + y % 64}
    references: dict[str, dict[str, str]] = {}
    resources = []
    sources: dict[str, Any] = {}
    for name, channel in (("roughness", "SpecularRoughness"), ("metallic", "BaseMetalness")):
        data = png.encode(planes[name], 8)
        path = source / f"{name}.png"
        path.write_bytes(data)
        references[name] = {"path": str(path), "sha256": digest(data)}
        resources.append({"sha256": digest(data), "png": path.name})
        sources[channel] = {"bitmap": digest(data), "color_space": "Raw"}
    document = {
        "name": "s0",
        "resolution": [SIZE, SIZE],
        "mesh": str(mesh),
        "channels": [
            {"type": name, "format": fmt}
            for name, fmt in (
                ("BaseColor", "sRGB8"),
                ("SpecularRoughness", "L8"),
                ("BaseMetalness", "L8"),
                ("Normal", "RGB16F"),
                ("Height", "L16F"),
                ("User0", "L8"),
                ("Emissive", "sRGB8"),
            )
        ],
        "resources": resources,
        "layers": [{"kind": "fill", "sources": sources}],
    }
    spec = source / "spec.json"
    spec.write_text(json.dumps(document), encoding="utf-8")
    maps = [
        {
            "fileName": "$textureSet_BaseColor",
            "channels": [chan(c, "documentMap", "basecolor") for c in "RGB"],
        },
        {
            "fileName": "$textureSet_MetallicRoughness",
            "channels": [
                {"destChannel": dest, "srcChannel": "L", "srcMapType": kind, "srcMapName": name}
                for dest, kind, name in (
                    ("R", "defaultMap", "white"),
                    ("G", "documentMap", "roughness"),
                    ("B", "documentMap", "metallic"),
                )
            ],
        },
        {
            "fileName": "$textureSet_Normal",
            "channels": [chan(c, "virtualMap", "Normal_OpenGL") for c in "RGB"],
        },
        {"fileName": "$textureSet_Occlusion", "channels": [chan("L", "documentMap", "user0")]},
        {
            "fileName": "$textureSet_Emissive",
            "channels": [chan(c, "documentMap", "emissive") for c in "RGB"],
        },
    ]
    out = tmp_path / "published"
    config = {
        "exportShaderParams": False,
        "exportPath": str(out),
        "defaultExportPreset": "authored-five-slots",
        "exportPresets": [{"name": "authored-five-slots", "maps": maps}],
        "exportList": [{"rootPath": "s0"}],
        "exportParameters": [
            {
                "parameters": {
                    "fileFormat": "png",
                    "bitDepth": "8",
                    "dithering": False,
                    "paddingAlgorithm": "passthrough",
                }
            }
        ],
    }
    config_path = source / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    result = one(export_tests, "publish", str(TEMPLATES), str(spec), str(config_path))
    assert "error" not in result, result
    pointer = json.loads((out / "current.json").read_bytes())
    return Publication(out, mesh, references, out / "generations" / pointer["generation"])


def consume(publication: Publication, exe: Path, output: Path) -> dict[str, Any]:
    manifest = Path(__file__).resolve().parents[2] / "parity/manifests/consumers/gltf/wand-v1.json"
    return run_fixture(
        publication.root,
        publication.mesh,
        BINDINGS,
        publication.references,
        output,
        exe,
        manifest,
        mesh_material="s0",
    )


def test_real_publication_consumed_by_fastgltf(
    publication: Publication, gltf_consumer: Path, tmp_path: Path
) -> None:
    output = tmp_path / "consumer"
    report = consume(publication, gltf_consumer, output)
    assert report["schema"] == "uzpainter/gltf-consumer-report/1"
    assert report["status"] == "pass"
    assert report["generation"] == publication.generation.name
    assert report["receipt_sha256"] == digest(
        (publication.generation / "receipt.json").read_bytes()
    )
    assert report["mesh_sha256"] == digest(publication.mesh.read_bytes())
    assert report["asset_sha256"] == digest((output / "asset.gltf").read_bytes())
    assert report["packing"]["roughness"]["mismatches"] == 0
    assert report["packing"]["metallic"]["mismatches"] == 0
    assert json.loads((output / "report.json").read_bytes()) == report
    asset = json.loads((output / "asset.gltf").read_bytes())
    assert len(asset["images"]) == 5
    copied = {(output / entry["uri"]).read_bytes() for entry in asset["images"]}
    original = {
        (publication.generation / "files" / name).read_bytes() for name in BINDINGS.values()
    }
    assert copied == original
    material = asset["materials"][0]
    pbr = material["pbrMetallicRoughness"]
    assert pbr["roughnessFactor"] == pbr["metallicFactor"] == 1
    assert pbr["baseColorFactor"] == [1, 1, 1, 1]
    assert material["emissiveFactor"] == [1, 1, 1]
    assert set(asset["meshes"][0]["primitives"][0]["attributes"]) >= {
        "POSITION",
        "NORMAL",
        "TEXCOORD_0",
    }


def test_swapped_packing_rejected_with_coherent_receipt(
    publication: Publication, gltf_consumer: Path, tmp_path: Path
) -> None:
    path = publication.generation / "files" / BINDINGS["metallicRoughness"]
    pixels = png.decode(path.read_bytes()).reshape(SIZE, SIZE, 3).copy()
    pixels[:, :, [1, 2]] = pixels[:, :, [2, 1]]
    data = png.encode(pixels, 8)
    path.write_bytes(data)
    receipt = publication.receipt()
    entry = next(f for f in receipt["files"] if f["path"] == path.name)
    entry.update(sha256=digest(data), bytes=len(data))
    publication.repin(receipt)
    with pytest.raises(ValueError, match=r"(?i)(packing|roughness|metallic)"):
        consume(publication, gltf_consumer, tmp_path / "consumer")


@pytest.mark.parametrize("mutation", ["receipt", "hash", "size", "path", "missing", "reference"])
def test_invalid_publication_rejected(
    publication: Publication, gltf_consumer: Path, tmp_path: Path, mutation: str
) -> None:
    receipt = publication.receipt()
    if mutation == "receipt":
        path = publication.generation / "receipt.json"
        path.write_bytes(path.read_bytes() + b" ")
    elif mutation == "reference":
        publication.references["roughness"]["sha256"] = "0" * 64
    else:
        entry = receipt["files"][0]
        if mutation == "hash":
            entry["sha256"] = "0" * 64
        elif mutation == "size":
            entry["bytes"] += 1
        elif mutation == "path":
            entry["path"] = "../../outside.png"
        else:
            entry["path"] = "missing.png"
        publication.repin(receipt)
    with pytest.raises(ValueError):
        consume(publication, gltf_consumer, tmp_path / "consumer")
    assert not (tmp_path / "consumer" / "report.json").exists()


def test_native_consumer_rejects_bad_asset_independently(
    publication: Publication, gltf_consumer: Path, tmp_path: Path
) -> None:
    output = tmp_path / "consumer"
    consume(publication, gltf_consumer, output)
    path = output / "asset.gltf"
    asset = json.loads(path.read_bytes())
    asset["meshes"][0]["primitives"][0]["attributes"].pop("TEXCOORD_0")
    path.write_text(json.dumps(asset), encoding="utf-8")
    proc = subprocess.run(
        [str(gltf_consumer), str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert json.loads(proc.stdout)["error"]


def png_with_idat(compressed: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    return (
        png.SIGNATURE
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


def forbid_unbounded_decode(data: bytes) -> png.Samples:
    raise AssertionError("invalid IDAT reached the unbounded PNG decoder")


def test_png_expansion_rejected_before_decode(monkeypatch: pytest.MonkeyPatch) -> None:
    data = png_with_idat(zlib.compress(b"\0" * 1024**2))
    monkeypatch.setattr(png, "decode", forbid_unbounded_decode)
    with pytest.raises(ValueError):
        _pixels(data)


def test_png_truncated_stream_rejected_before_decode(monkeypatch: pytest.MonkeyPatch) -> None:
    data = png_with_idat(zlib.compress(b"\0\x7f")[:-2])
    monkeypatch.setattr(png, "decode", forbid_unbounded_decode)
    with pytest.raises(ValueError):
        _pixels(data)


@pytest.mark.parametrize("request_text", ["{invalid JSON", '{"export_root": null}'])
def test_cli_rejects_invalid_request_without_traceback(tmp_path: Path, request_text: str) -> None:
    path = tmp_path / "request.json"
    path.write_text(request_text, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "tools.consumers.gltf", "--request", str(path)],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert json.loads(result.stdout)["error"]
    assert "Traceback" not in result.stderr
