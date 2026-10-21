"""Fixture writers of the mesh-import tests (phase1.4_mesh-importers): OBJ text, glTF/GLB with an
embedded buffer, ASCII FBX 7.4 and 8-bit PNG, all written from closed-form data at test time
(UzmiGames-authored, Apache-2.0), plus an independent reference of the content hashes of
`src/mesh/texturing_mesh.h` computed from an OBJ's text.
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

IDENTITY = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]


# ---------------------------------------------------------------------------------------------
# Reference hashes from an OBJ's text (the byte streams of `ComputeHashes`)


def _f32(value: float) -> bytes:
    return struct.pack("<f", value)


def _resolve(token: str, count: int) -> int:
    value = int(token)
    return value - 1 if value > 0 else count + value


def obj_reference_hashes(text: str) -> dict[str, str]:
    """The five hashes of an OBJ that uses `v`, `vt`, `vn`, `f`, `o`, `g` and `usemtl` only, from
    the documented rules: positions in file order, one corner per face reference, triangles kept
    and polygons fanned from their last corner, objects by `o`/`g` (faces before them in
    `default`), materials by first `usemtl` (faces before it in `default`)."""
    positions: list[Vec3] = []
    uvs: list[Vec2] = []
    normals: list[Vec3] = []
    corners: list[tuple[int, Vec3, Vec2, str]] = []
    objects: list[tuple[str, list[tuple[int, int, int]]]] = []
    material = "default"
    material_order: list[str] = []
    for raw in text.splitlines():
        parts = raw.split("#", 1)[0].split()
        if not parts:
            continue
        key, args = parts[0], parts[1:]
        if key == "v":
            positions.append((float(args[0]), float(args[1]), float(args[2])))
        elif key == "vt":
            uvs.append((float(args[0]), float(args[1]) if len(args) > 1 else 0.0))
        elif key == "vn":
            normals.append((float(args[0]), float(args[1]), float(args[2])))
        elif key in ("o", "g"):
            name = " ".join(args) or "default"
            if not objects or objects[-1][0] != name:
                objects.append((name, []))
        elif key == "usemtl":
            material = " ".join(args)
        elif key == "f":
            if not objects:
                objects.append(("default", []))
            if material not in material_order:
                material_order.append(material)
            first = len(corners)
            for ref in args:
                fields = ref.split("/")
                position = _resolve(fields[0], len(positions))
                uv = (
                    uvs[_resolve(fields[1], len(uvs))]
                    if len(fields) > 1 and fields[1]
                    else (0.0, 0.0)
                )
                normal = (
                    normals[_resolve(fields[2], len(normals))]
                    if len(fields) > 2 and fields[2]
                    else (0.0, 0.0, 0.0)
                )
                corners.append((position, normal, uv, material))
            last = first + len(args) - 1
            for i in range(len(args) - 2):
                objects[-1][1].append((first + i, first + i + 1, last))
    objects = [o for o in objects if o[1]]
    index = {name: i for i, name in enumerate(material_order)}

    def digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    stream = b"".join(_f32(c) for p in positions for c in p)
    stream += b"".join(struct.pack("<d", e) for _ in objects for e in IDENTITY)
    tri = b"".join(
        struct.pack("<I", len(t)) + b"".join(struct.pack("<3I", *x) for x in t) for _, t in objects
    )
    tri += b"".join(struct.pack("<I", c[0]) for c in corners)
    mats = b"".join(struct.pack("<I", i) + n.encode() + b"\0" for i, n in enumerate(material_order))
    mats += b"".join(struct.pack("<I", index[c[3]]) for c in corners)
    return {
        "positions": digest(stream),
        "uvs": digest(b"".join(_f32(v) for c in corners for v in c[2])),
        "corner_normals": digest(b"".join(_f32(v) for c in corners for v in c[1])),
        "triangulation": digest(tri),
        "materials": digest(mats),
    }


def secondary_uvs_hash(sets: list[tuple[str, list[Vec2]]]) -> str:
    """`hashes.secondary_uvs`: per UV set after the first, its UTF-8 name and a 0 byte, then
    every corner's UV in it as 2 x float32."""
    stream = b"".join(
        name.encode() + b"\0" + b"".join(_f32(c) for uv in uvs for c in uv) for name, uvs in sets
    )
    return hashlib.sha256(stream).hexdigest()


# ---------------------------------------------------------------------------------------------
# glTF / GLB


@dataclass
class Primitive:
    positions: list[Vec3]
    indices: list[int]
    normals: list[Vec3] | None = None
    uvs: list[Vec2] | None = None  # glTF convention: v grows downwards
    material: int | None = None
    tangents: list[tuple[float, float, float, float]] | None = None
    texcoords: dict[int, list[Vec2]] = field(default_factory=dict)  # TEXCOORD_n by n >= 1


@dataclass
class GltfNode:
    name: str
    mesh: int | None = None
    translation: Vec3 | None = None
    scale: Vec3 | None = None
    children: list[int] = field(default_factory=list)


def gltf_document(
    meshes: list[list[Primitive]], nodes: list[GltfNode], materials: list[str], roots: list[int]
) -> tuple[dict[str, Any], bytes]:
    """A glTF document and its single binary buffer (float32 attributes, uint32 indices)."""
    blob = bytearray()
    accessors: list[dict[str, Any]] = []
    views: list[dict[str, Any]] = []

    def add(values: list[Any], kind: str, component: int, fmt: str) -> int:
        while len(blob) % 4:
            blob.append(0)
        start = len(blob)
        for value in values:
            blob.extend(struct.pack(fmt, *(value if isinstance(value, tuple) else (value,))))
        views.append({"buffer": 0, "byteOffset": start, "byteLength": len(blob) - start})
        accessor: dict[str, Any] = {
            "bufferView": len(views) - 1,
            "componentType": component,
            "count": len(values),
            "type": kind,
        }
        if kind == "VEC3" and fmt == "<3f":
            accessor["min"] = [min(v[i] for v in values) for i in range(3)]
            accessor["max"] = [max(v[i] for v in values) for i in range(3)]
        accessors.append(accessor)
        return len(accessors) - 1

    gltf_meshes = []
    for primitives in meshes:
        out = []
        for p in primitives:
            attributes = {"POSITION": add(p.positions, "VEC3", 5126, "<3f")}
            if p.normals is not None:
                attributes["NORMAL"] = add(p.normals, "VEC3", 5126, "<3f")
            if p.uvs is not None:
                attributes["TEXCOORD_0"] = add(p.uvs, "VEC2", 5126, "<2f")
            for n, values in p.texcoords.items():
                attributes[f"TEXCOORD_{n}"] = add(values, "VEC2", 5126, "<2f")
            if p.tangents is not None:
                attributes["TANGENT"] = add(p.tangents, "VEC4", 5126, "<4f")
            prim: dict[str, Any] = {
                "attributes": attributes,
                "indices": add(p.indices, "SCALAR", 5125, "<I"),
            }
            if p.material is not None:
                prim["material"] = p.material
            out.append(prim)
        gltf_meshes.append({"primitives": out})
    gltf_nodes = []
    for node in nodes:
        entry: dict[str, Any] = {"name": node.name}
        if node.mesh is not None:
            entry["mesh"] = node.mesh
        if node.translation is not None:
            entry["translation"] = list(node.translation)
        if node.scale is not None:
            entry["scale"] = list(node.scale)
        if node.children:
            entry["children"] = node.children
        gltf_nodes.append(entry)
    document: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "UzPainter mesh-import tests"},
        "scene": 0,
        "scenes": [{"nodes": roots}],
        "nodes": gltf_nodes,
        "meshes": gltf_meshes,
        "materials": [{"name": name} for name in materials],
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(blob)}],
    }
    return document, bytes(blob)


def write_gltf(path: Path, document: dict[str, Any], blob: bytes) -> Path:
    """`.gltf` with the buffer as a base64 data URI."""
    document = json.loads(json.dumps(document))
    document["buffers"][0]["uri"] = "data:application/octet-stream;base64," + base64.b64encode(
        blob
    ).decode("ascii")
    path.write_text(json.dumps(document, indent=1), encoding="utf-8")
    return path


def write_glb(path: Path, document: dict[str, Any], blob: bytes) -> Path:
    text = json.dumps(document).encode("utf-8")
    text += b" " * (-len(text) % 4)
    blob += b"\0" * (-len(blob) % 4)
    body = (
        struct.pack("<II", len(text), 0x4E4F534A)
        + text
        + struct.pack("<II", len(blob), 0x004E4942)
        + blob
    )
    path.write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body)
    return path


# ---------------------------------------------------------------------------------------------
# ASCII FBX 7.4


@dataclass
class FbxGeometry:
    id: int
    name: str
    positions: list[Vec3]
    polygons: list[list[int]]  # control-point indices per polygon
    normals: list[Vec3] | None = None  # one per polygon vertex
    uvs: list[Vec2] | None = None  # one per polygon vertex
    polygon_materials: list[int] | None = None  # material slot per polygon
    extra_uvs: list[tuple[str, list[Vec2]]] = field(default_factory=list)  # later UV layers


@dataclass
class FbxModel:
    id: int
    name: str
    geometry: int
    translation: Vec3 = (0.0, 0.0, 0.0)
    materials: list[int] = field(default_factory=list)  # material ids, slot order
    parent: int = 0


def _numbers(values: list[float] | list[int]) -> str:
    return ",".join(repr(v) if isinstance(v, float) else str(v) for v in values)


def fbx_ascii(
    geometries: list[FbxGeometry],
    models: list[FbxModel],
    materials: dict[int, str],
    unit_scale_factor: float = 1.0,
) -> str:
    """An ASCII FBX 7.4 scene: `UnitScaleFactor` is centimetres per unit (1 = cm, 100 = m)."""
    out = [
        "; FBX 7.4.0 project file",
        "FBXHeaderExtension:  {",
        "\tFBXHeaderVersion: 1003",
        "\tFBXVersion: 7400",
        "}",
        "GlobalSettings:  {",
        "\tVersion: 1000",
        "\tProperties70:  {",
        '\t\tP: "UpAxis", "int", "Integer", "",1',
        '\t\tP: "UpAxisSign", "int", "Integer", "",1',
        '\t\tP: "FrontAxis", "int", "Integer", "",2',
        '\t\tP: "FrontAxisSign", "int", "Integer", "",1',
        '\t\tP: "CoordAxis", "int", "Integer", "",0',
        '\t\tP: "CoordAxisSign", "int", "Integer", "",1',
        f'\t\tP: "UnitScaleFactor", "double", "Number", "",{unit_scale_factor!r}',
        "\t}",
        "}",
        "Objects:  {",
    ]
    for g in geometries:
        flat = [c for p in g.positions for c in p]
        index: list[int] = []
        for poly in g.polygons:
            index += [*poly[:-1], -poly[-1] - 1]
        out += [
            f'\tGeometry: {g.id}, "Geometry::{g.name}", "Mesh" {{',
            f"\t\tVertices: *{len(flat)} {{ a: {_numbers([float(v) for v in flat])} }}",
            f"\t\tPolygonVertexIndex: *{len(index)} {{ a: {_numbers(index)} }}",
        ]
        layer = []
        if g.normals is not None:
            normals = [float(c) for n in g.normals for c in n]
            out += [
                "\t\tLayerElementNormal: 0 {",
                "\t\t\tVersion: 101",
                '\t\t\tName: ""',
                '\t\t\tMappingInformationType: "ByPolygonVertex"',
                '\t\t\tReferenceInformationType: "Direct"',
                f"\t\t\tNormals: *{len(normals)} {{ a: {_numbers(normals)} }}",
                "\t\t}",
            ]
            layer.append("LayerElementNormal")
        if g.uvs is not None:
            uvs = [float(c) for uv in g.uvs for c in uv]
            out += [
                "\t\tLayerElementUV: 0 {",
                "\t\t\tVersion: 101",
                '\t\t\tName: "UVMap"',
                '\t\t\tMappingInformationType: "ByPolygonVertex"',
                '\t\t\tReferenceInformationType: "IndexToDirect"',
                f"\t\t\tUV: *{len(uvs)} {{ a: {_numbers(uvs)} }}",
                f"\t\t\tUVIndex: *{len(g.uvs)} {{ a: {_numbers(list(range(len(g.uvs))))} }}",
                "\t\t}",
            ]
            layer.append("LayerElementUV")
        for n, (uv_name, values) in enumerate(g.extra_uvs, start=1):
            flat_uvs = [float(c) for uv in values for c in uv]
            out += [
                f"\t\tLayerElementUV: {n} {{",
                "\t\t\tVersion: 101",
                f'\t\t\tName: "{uv_name}"',
                '\t\t\tMappingInformationType: "ByPolygonVertex"',
                '\t\t\tReferenceInformationType: "IndexToDirect"',
                f"\t\t\tUV: *{len(flat_uvs)} {{ a: {_numbers(flat_uvs)} }}",
                f"\t\t\tUVIndex: *{len(values)} {{ a: {_numbers(list(range(len(values))))} }}",
                "\t\t}",
            ]
        if g.polygon_materials is not None:
            slots = g.polygon_materials
            out += [
                "\t\tLayerElementMaterial: 0 {",
                "\t\t\tVersion: 101",
                '\t\t\tName: ""',
                '\t\t\tMappingInformationType: "ByPolygon"',
                '\t\t\tReferenceInformationType: "IndexToDirect"',
                f"\t\t\tMaterials: *{len(slots)} {{ a: {_numbers(slots)} }}",
                "\t\t}",
            ]
            layer.append("LayerElementMaterial")
        out += ["\t\tLayer: 0 {", "\t\t\tVersion: 100"]
        for element in layer:
            out += [
                "\t\t\tLayerElement:  {",
                f'\t\t\t\tType: "{element}"',
                "\t\t\t\tTypedIndex: 0",
                "\t\t\t}",
            ]
        out += ["\t\t}"]
        for n in range(1, len(g.extra_uvs) + 1):
            out += [
                f"\t\tLayer: {n} {{",
                "\t\t\tVersion: 100",
                "\t\t\tLayerElement:  {",
                '\t\t\t\tType: "LayerElementUV"',
                f"\t\t\t\tTypedIndex: {n}",
                "\t\t\t}",
                "\t\t}",
            ]
        out += ["\t}"]
    for m in models:
        t = m.translation
        out += [
            f'\tModel: {m.id}, "Model::{m.name}", "Mesh" {{',
            "\t\tVersion: 232",
            "\t\tProperties70:  {",
            f'\t\t\tP: "Lcl Translation", "Lcl Translation", "", "A",{t[0]!r},{t[1]!r},{t[2]!r}',
            "\t\t}",
            "\t}",
        ]
    for mid, name in materials.items():
        out += [
            f'\tMaterial: {mid}, "Material::{name}", "" {{',
            "\t\tVersion: 102",
            '\t\tShadingModel: "phong"',
            "\t}",
        ]
    out += ["}", "Connections:  {"]
    for m in models:
        out.append(f'\tC: "OO",{m.id},{m.parent}')
        out.append(f'\tC: "OO",{m.geometry},{m.id}')
        out += [f'\tC: "OO",{mid},{m.id}' for mid in m.materials]
    out.append("}")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------------------------
# PNG


def png_rgba8(width: int, height: int, pixels: list[list[tuple[int, int, int, int]]]) -> bytes:
    """An 8-bit RGBA PNG; `pixels[row][col]`, row 0 written first (the top of the image)."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    raw = b"".join(b"\0" + b"".join(bytes(p) for p in row) for row in pixels)
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
