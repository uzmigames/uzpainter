"""Assemble and check a glTF fixture from one verified published generation.

This CPU fixture uses the pinned fastgltf loader and its structural validator.
It does not render, certify Painter parity or enable the pending glTF preset.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import subprocess
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

import numpy as np

from tools.parity.feasibility import png

SLOTS = ("baseColor", "metallicRoughness", "normal", "occlusion", "emissive")
CONSUMER = {"loader": "fastgltf", "version": "0.9.1", "validator": "fastgltf::validate"}
ARCHIVE_SHA256 = "d8705a496deb2831775baeef5009be36d24bf3d10f8d29ab016e977d0119c872"
MAX_FILE_BYTES = 256 * 1024 * 1024


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _json(data: bytes) -> dict[str, Any]:
    def invalid_constant(value: str) -> NoReturn:
        raise ValueError(f"invalid JSON number: {value}")

    result = json.loads(data, object_pairs_hook=_object, parse_constant=invalid_constant)
    if not isinstance(result, dict):
        raise ValueError("expected a JSON object")
    return result


def _read(path: Path) -> bytes:
    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"missing or oversized fixture input: {path}")
    return path.read_bytes()


def _local(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or any(c in name for c in "\\:%?#\0"):
        raise ValueError(f"invalid relative resource path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in name.split("/")):
        raise ValueError(f"invalid relative resource path: {name!r}")
    result = root.joinpath(*path.parts).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError(f"resource escapes its root: {name}")
    return result


@dataclass(frozen=True)
class Published:
    generation: str
    receipt_sha256: str
    files: dict[str, bytes]
    entries: dict[str, dict[str, Any]]


def _published(root: Path) -> Published:
    # Read the pointer once. Later publications do not change this pinned generation.
    pointer = _json(_read(root / "current.json"))
    generation = pointer.get("generation")
    if pointer.get("schema") != "uzpainter/export-current/1" or not isinstance(generation, str):
        raise ValueError("invalid publication pointer")
    if not re.fullmatch(r"[0-9]{6,}", generation):
        raise ValueError("invalid generation name")
    receipt_name = f"generations/{generation}/receipt.json"
    if pointer.get("receipt") != receipt_name:
        raise ValueError("receipt does not belong to the selected generation")
    receipt_bytes = _read(_local(root, receipt_name))
    digest = _sha(receipt_bytes)
    if digest != pointer.get("receipt_sha256"):
        raise ValueError("receipt SHA-256 mismatch")
    receipt = _json(receipt_bytes)
    if receipt.get("generation") != generation or not isinstance(receipt.get("files"), list):
        raise ValueError("receipt generation or files are invalid")
    files: dict[str, bytes] = {}
    entries: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    base = _local(root, f"generations/{generation}/files")
    for entry in receipt["files"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ValueError("invalid receipt file entry")
        name = entry["path"]
        if name.casefold() in seen:
            raise ValueError(f"duplicate published path: {name}")
        seen.add(name.casefold())
        data = _read(_local(base, name))
        if type(entry.get("bytes")) is not int or len(data) != entry["bytes"]:
            raise ValueError(f"published size mismatch: {name}")
        if _sha(data) != entry.get("sha256"):
            raise ValueError(f"published SHA-256 mismatch: {name}")
        files[name], entries[name] = data, entry
    if not files:
        raise ValueError("empty published generation")
    return Published(generation, digest, files, entries)


def _pixels(data: bytes) -> tuple[png.Samples, int]:
    try:
        chunks = png.chunks(data)
        if not chunks or chunks[0][0] != b"IHDR" or len(chunks[0][1]) != 13:
            raise ValueError("missing PNG header")
        width, height, depth, color, compression, filtering, interlace = struct.unpack(
            ">IIBBBBB", chunks[0][1]
        )
        if not 0 < width <= 16384 or not 0 < height <= 16384 or width * height > 64 * 1024**2:
            raise ValueError("PNG dimensions exceed the fixture limit")
        if (
            depth not in (8, 16)
            or color not in png.CHANNELS_OF_COLOR_TYPE
            or compression
            or filtering
            or interlace
        ):
            raise ValueError("unsupported PNG layout")
        expected = height * (1 + width * png.CHANNELS_OF_COLOR_TYPE[color] * (depth // 8))
        # Bound inflation before calling the shared native-depth sample decoder.
        inflater = zlib.decompressobj()
        raw = inflater.decompress(
            b"".join(body for kind, body in chunks if kind == b"IDAT"), expected + 1
        )
        if (
            len(raw) != expected
            or not inflater.eof
            or inflater.unused_data
            or inflater.unconsumed_tail
        ):
            raise ValueError("PNG IDAT size or stream does not match the header")
        del raw
        return png.decode(data), depth
    except (ValueError, struct.error, IndexError, zlib.error) as error:
        raise ValueError(f"invalid fixture PNG: {error}") from error


def _packing(packed: bytes, references: dict[str, dict[str, str]]) -> dict[str, Any]:
    if set(references) != {"roughness", "metallic"}:
        raise ValueError("packing requires independent roughness and metallic reference pins")
    pixels, depth = _pixels(packed)
    if pixels.shape[2] < 3:
        raise ValueError("metallic-roughness needs RGB channels")
    result: dict[str, Any] = {}
    for name, component in (("roughness", 1), ("metallic", 2)):
        reference = references[name]
        data = _read(Path(reference["path"]))
        if _sha(data) != reference.get("sha256"):
            raise ValueError(f"{name} reference SHA-256 mismatch")
        expected, expected_depth = _pixels(data)
        if expected_depth != depth or expected.shape != (*pixels.shape[:2], 1):
            raise ValueError(
                f"{name} reference must match the packed depth and size, with one channel"
            )
        mismatches = int(np.count_nonzero(pixels[:, :, component] != expected[:, :, 0]))
        if mismatches:
            raise ValueError(
                f"{name} packing mismatch: {mismatches} texels in channel {'GB'[component - 1]}"
            )
        result[name] = {
            "mismatches": 0,
            "reference_sha256": _sha(data),
            "texels": int(expected.size),
        }
    return result


def _geometry(path: Path, material: str | None) -> tuple[bytes, dict[str, Any]]:
    tables: dict[str, list[tuple[float, ...]]] = {"v": [], "vt": [], "vn": []}
    vertices: list[tuple[float, ...]] = []
    indices: list[int] = []
    unique: dict[tuple[int, int, int], int] = {}
    materials: set[str] = set()
    current = "default"
    source = _read(path)
    for number, raw in enumerate(source.decode("utf-8").splitlines(), 1):
        parts = raw.split("#", 1)[0].split()
        if not parts:
            continue
        kind, values = parts[0], parts[1:]
        if kind in tables:
            size = 2 if kind == "vt" else 3
            if len(values) != size:
                raise ValueError(f"OBJ line {number}: expected {size} {kind} components")
            vector = tuple(float(v) for v in values)
            if not all(math.isfinite(v) for v in vector):
                raise ValueError("OBJ contains non-finite coordinates")
            tables[kind].append(vector)
        elif kind == "usemtl":
            current = " ".join(values)
        elif kind == "f":
            if material is not None and current != material:
                continue
            materials.add(current)
            if len(values) != 3:
                raise ValueError("consumer fixture requires a triangulated OBJ")
            for token in values:
                fields = token.split("/")
                if len(fields) != 3 or not all(fields):
                    raise ValueError("every OBJ corner needs position, UV and normal")
                resolved = []
                for field, table in zip(fields, ("v", "vt", "vn"), strict=True):
                    index = int(field)
                    count = len(tables[table])
                    offset = index - 1 if index > 0 else count + index
                    if index == 0 or not 0 <= offset < count:
                        raise ValueError("OBJ corner index is out of range")
                    resolved.append(offset)
                key = (resolved[0], resolved[1], resolved[2])
                if key not in unique:
                    position, uv, normal = (
                        tables[t][i] for t, i in zip(("v", "vt", "vn"), key, strict=True)
                    )
                    length = math.sqrt(sum(v * v for v in normal))
                    if not math.isfinite(length) or length == 0:
                        raise ValueError("OBJ normal has zero or invalid length")
                    # OBJ V is bottom-up; glTF image coordinates have their origin at the top.
                    vertex = (*position, *(v / length for v in normal), uv[0], 1.0 - uv[1])
                    try:
                        rounded = struct.unpack("<8f", struct.pack("<8f", *vertex))
                    except (OverflowError, struct.error) as error:
                        raise ValueError("OBJ coordinates exceed float32") from error
                    if not all(math.isfinite(v) for v in rounded):
                        raise ValueError("OBJ coordinates exceed finite float32")
                    unique[key] = len(vertices)
                    vertices.append(rounded)
                indices.append(unique[key])
    if not indices or len(materials) != 1:
        raise ValueError(
            "fixture requires one non-empty OBJ material; select mesh_material explicitly"
        )
    vertex_bytes = b"".join(struct.pack("<8f", *vertex) for vertex in vertices)
    index_bytes = struct.pack(f"<{len(indices)}I", *indices)
    metadata = {
        "source_sha256": _sha(source),
        "vertices": len(vertices),
        "triangles": len(indices) // 3,
        "vertex_bytes": len(vertex_bytes),
        "index_bytes": len(index_bytes),
        "min": [min(v[i] for v in vertices) for i in range(3)],
        "max": [max(v[i] for v in vertices) for i in range(3)],
    }
    return vertex_bytes + index_bytes, metadata


def _asset(mesh: dict[str, Any]) -> dict[str, Any]:
    attributes = {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2}
    accessors: list[dict[str, Any]] = []
    for offset, kind in ((0, "VEC3"), (12, "VEC3"), (24, "VEC2")):
        accessors.append(
            {
                "bufferView": 0,
                "byteOffset": offset,
                "componentType": 5126,
                "count": mesh["vertices"],
                "type": kind,
            }
        )
    accessors[0].update({"min": mesh["min"], "max": mesh["max"]})
    accessors.append(
        {"bufferView": 1, "componentType": 5125, "count": mesh["triangles"] * 3, "type": "SCALAR"}
    )
    return {
        "asset": {"version": "2.0", "generator": "UzPainter consumer fixture"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "buffers": [{"uri": "mesh.bin", "byteLength": mesh["vertex_bytes"] + mesh["index_bytes"]}],
        "bufferViews": [
            {"buffer": 0, "byteLength": mesh["vertex_bytes"], "byteStride": 32, "target": 34962},
            {
                "buffer": 0,
                "byteOffset": mesh["vertex_bytes"],
                "byteLength": mesh["index_bytes"],
                "target": 34963,
            },
        ],
        "accessors": accessors,
        "meshes": [
            {"primitives": [{"attributes": attributes, "indices": 3, "material": 0, "mode": 4}]}
        ],
        "images": [{"uri": f"{slot}.png"} for slot in SLOTS],
        "textures": [{"source": i} for i in range(len(SLOTS))],
        "materials": [
            {
                "pbrMetallicRoughness": {
                    "baseColorTexture": {"index": 0},
                    "metallicRoughnessTexture": {"index": 1},
                    "baseColorFactor": [1, 1, 1, 1],
                    "metallicFactor": 1,
                    "roughnessFactor": 1,
                },
                "normalTexture": {"index": 2, "scale": 1},
                "occlusionTexture": {"index": 3, "strength": 1},
                "emissiveTexture": {"index": 4},
                "emissiveFactor": [1, 1, 1],
                "alphaMode": "BLEND",
            }
        ],
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n"
    )


def run_fixture(
    export_root: Path,
    mesh_obj: Path,
    bindings: dict[str, str],
    references: dict[str, dict[str, str]],
    output_dir: Path,
    consumer_exe: Path,
    manifest_path: Path,
    *,
    mesh_material: str | None = None,
) -> dict[str, Any]:
    """Verify, assemble and consume a fresh fixture; invalid input raises ValueError."""
    if set(bindings) != set(SLOTS):
        raise ValueError("fixture needs exactly the five glTF texture bindings")
    manifest_bytes = _read(manifest_path)
    manifest = _json(manifest_bytes)
    if (
        manifest.get("schema") != "uzpainter/gltf-consumer-fixture/1"
        or manifest.get("consumer") != CONSUMER
        or manifest.get("loader_archive_sha256") != ARCHIVE_SHA256
    ):
        raise ValueError("unsupported glTF consumer manifest identity")
    published = _published(export_root)
    selected: dict[str, bytes] = {}
    image_info: dict[str, dict[str, Any]] = {}
    for slot, name in bindings.items():
        if name not in published.files or published.entries[name].get("format") != "png":
            raise ValueError(f"missing published PNG binding: {slot}")
        data = published.files[name]
        pixels, depth = _pixels(data)
        height, width, channels = pixels.shape
        entry = published.entries[name]
        if entry.get("size") != [width, height] or str(entry.get("bit_depth")) != str(depth):
            raise ValueError(f"published PNG metadata mismatch: {slot}")
        if slot != "occlusion" and channels < 3:
            raise ValueError(f"glTF {slot} needs RGB or RGBA")
        selected[slot] = data
        image_info[slot] = {
            "image": f"{slot}.png",
            "sha256": _sha(data),
            "width": width,
            "height": height,
            "channels": channels,
            "bit_depth": depth,
            "texcoord": 0,
        }
    packing = _packing(selected["metallicRoughness"], references)
    mesh_bytes, mesh = _geometry(mesh_obj, mesh_material)
    try:
        output_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise ValueError("fixture output directory must be new") from error
    for slot, data in selected.items():
        (output_dir / f"{slot}.png").write_bytes(data)
    (output_dir / "mesh.bin").write_bytes(mesh_bytes)
    asset_path = output_dir / "asset.gltf"
    _write_json(asset_path, _asset(mesh))
    executable_hash = _sha(_read(consumer_exe))
    try:
        result = subprocess.run(
            [str(consumer_exe.resolve()), str(asset_path.resolve())],
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(f"glTF consumer could not complete: {error}") from error
    consumer = _json(result.stdout)
    if result.returncode != 0 or "error" in consumer:
        reason = consumer.get("error", result.stderr.decode(errors="replace"))
        raise ValueError(f"glTF consumer rejected asset: {reason}")
    if _sha(_read(consumer_exe)) != executable_hash or consumer.get("consumer") != CONSUMER:
        raise ValueError("glTF consumer identity changed or disagrees with the manifest")
    expected_mesh = {
        "vertices": mesh["vertices"],
        "triangles": mesh["triangles"],
        "normals": mesh["vertices"],
        "texcoords": mesh["vertices"],
        "boundsMin": mesh["min"],
        "boundsMax": mesh["max"],
    }
    if consumer.get("mesh") != expected_mesh:
        raise ValueError("glTF consumer loaded different geometry")
    if consumer.get("bindings") != image_info:
        raise ValueError("glTF consumer loaded different texture bindings or bytes")
    expected_material = {
        "baseColorFactor": [1, 1, 1, 1],
        "metallicFactor": 1,
        "roughnessFactor": 1,
        "emissiveFactor": [1, 1, 1],
        "alphaMode": "BLEND",
        "normalScale": 1,
        "occlusionStrength": 1,
    }
    if consumer.get("material") != expected_material:
        raise ValueError("glTF consumer material factors changed texture semantics")
    report = {
        "schema": "uzpainter/gltf-consumer-report/1",
        "status": "pass",
        "generation": published.generation,
        "receipt_sha256": published.receipt_sha256,
        "fixture": manifest.get("fixture"),
        "manifest_sha256": _sha(manifest_bytes),
        "mesh_sha256": mesh["source_sha256"],
        "asset_sha256": _sha(_read(asset_path)),
        "consumer_executable_sha256": executable_hash,
        "consumer": consumer,
        "packing": packing,
        "bindings": bindings,
        "consumer_gaps": [
            gap for entry in published.entries.values() for gap in entry.get("consumer_gaps", [])
        ],
        "scope": "CPU structure, geometry and bindings; no render or Painter parity",
    }
    _write_json(output_dir / "report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--request", type=Path, required=True, help="JSON paths, bindings and pinned references"
    )
    args = parser.parse_args()
    try:
        request = _json(_read(args.request))
        report = run_fixture(
            Path(request["export_root"]),
            Path(request["mesh_obj"]),
            request["bindings"],
            request["references"],
            Path(request["output_dir"]),
            Path(request["consumer_exe"]),
            Path(request["manifest_path"]),
            mesh_material=request.get("mesh_material"),
        )
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"error": str(error)}))
        return 1
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
