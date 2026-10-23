"""Classify glTF export sidecars without interpreting them as texture maps."""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from tools.parity.recorder.session import RecorderError


def glb_document(path: Path) -> tuple[Any, int | None]:
    data = path.read_bytes()
    if len(data) < 20 or struct.unpack_from("<III", data) != (0x46546C67, 2, len(data)):
        raise RecorderError(f"{path.name}: invalid GLB header")
    chunks: list[tuple[int, bytes]] = []
    offset = 12
    while offset < len(data):
        if offset + 8 > len(data):
            raise RecorderError(f"{path.name}: truncated GLB chunk")
        length, kind = struct.unpack_from("<II", data, offset)
        offset += 8
        if length % 4 or offset + length > len(data):
            raise RecorderError(f"{path.name}: invalid GLB chunk length")
        chunks.append((kind, data[offset : offset + length]))
        offset += length
    if not chunks or chunks[0][0] != 0x4E4F534A or len(chunks) > 2:
        raise RecorderError(f"{path.name}: unsupported GLB chunk layout")
    if len(chunks) == 2 and chunks[1][0] != 0x004E4942:
        raise RecorderError(f"{path.name}: unsupported GLB binary chunk")
    try:
        document = json.loads(chunks[0][1])
    except (UnicodeError, ValueError) as error:
        raise RecorderError(f"{path.name}: invalid GLB JSON") from error
    return document, len(chunks[1][1]) if len(chunks) == 2 else None


def gltf_sidecars(present: list[Path], root: Path) -> dict[Path, str]:
    """Admit glTF 2.0 JSON and its local, size-checked binary buffers only."""
    media: dict[Path, str] = {}
    available = set(present)
    for path in present:
        suffix = path.suffix.lower()
        if suffix not in (".gltf", ".glb"):
            continue
        binary_length = None
        if suffix == ".glb":
            document, binary_length = glb_document(path)
        else:
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (UnicodeError, ValueError) as error:
                raise RecorderError(f"{path.name}: invalid glTF JSON") from error
        if not isinstance(document, dict) or not isinstance(document.get("asset"), dict):
            raise RecorderError(f"{path.name}: missing glTF asset")
        if document["asset"].get("version") != "2.0":
            raise RecorderError(f"{path.name}: unsupported glTF asset version")
        buffers = document.get("buffers", [])
        if not isinstance(buffers, list):
            raise RecorderError(f"{path.name}: glTF buffers must be an array")
        for index, buffer in enumerate(buffers):
            if not isinstance(buffer, dict):
                raise RecorderError(f"{path.name}: invalid glTF buffer")
            uri, length = buffer.get("uri"), buffer.get("byteLength")
            if uri is None and index == 0 and binary_length is not None:
                if type(length) is not int or not 0 <= binary_length - length <= 3 or length < 0:
                    raise RecorderError(f"{path.name}: GLB buffer byteLength mismatch")
                continue
            if not isinstance(uri, str) or type(length) is not int or length < 0:
                raise RecorderError(f"{path.name}: invalid glTF buffer URI or length")
            parsed = urlsplit(uri)
            decoded = unquote(parsed.path)
            if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or "\\" in decoded:
                raise RecorderError(f"{path.name}: glTF buffer must be a local relative URI")
            relative = Path(decoded)
            target = (path.parent / relative).resolve()
            if relative.is_absolute() or not target.is_relative_to(root) or target not in available:
                raise RecorderError(f"{path.name}: glTF buffer is outside or absent from capture")
            if target.suffix.lower() != ".bin" or target.stat().st_size != length:
                raise RecorderError(f"{path.name}: glTF buffer type or byteLength mismatch")
            media[target] = "application/octet-stream"
        media[path] = "model/gltf-binary" if suffix == ".glb" else "model/gltf+json"
    return media
