r"""Qualification of Painter's Export resource on disposable PROJECT bitmaps (decision 300).

    python -m tools.parity.recorder resource-export-qual --operator ui [--launch]
    python -m tools.parity.recorder resource-export-qual-analyse <run directory> [--report <md>]
    python -m tools.parity.recorder.resource_qualification fixtures [--write]

The documented Python and JavaScript APIs expose no way to read back the original bytes of a
resource held inside a Painter project (supervisor finding SUP-008). The Assets window's Export
resource menu operation is documented for shelf resources only. This module qualifies that UI
operation, under the UI-oracle protocol of decisions 029 and 039, on bitmaps UzmiGames authored for
it, before it may ever be used on a pilot project: it never opens a production project, never
reads a `.spp` file, and never treats a texture export, `mapexport.saveMeshMap` or
`fileIO.urlToLocalFile` as a resource export.

**Cases.** Thirteen disposable bitmaps (`CASES`): PNG 8 and 16 bit, grey, RGB and RGBA, with an
sRGB chunk, a linear `gAMA` or no colour chunk; two written by Pillow exactly as the pilots' mask
and base-colour generators write theirs; one 2048 px 16-bit grey mask generated at run time by a
deterministic stored-deflate encoder (too large to commit); TGA raw and RLE; OpenEXR half (ZIP)
and float (uncompressed); a baseline JPEG. The committed files are in
`parity/fixtures/resource-export/`; every case is pinned by SHA-256, SHA-1 and size here, and a
staged copy that differs refuses the run.

**Run.** In one Painter session under OCIO (Painter's substance configuration, as the pilots ran):

1. The recorder creates a throwaway project on the authored plane mesh and imports every case as a
   project resource (`import_project_resource` with the name `uzp_rq_<case>_<sha1[:6]>` and the
   group `uzp_rq300`: the naming form of the UzmiGames layer-stack sync), then binds each to the
   BaseColor of its own fill layer, so the project uses it, and saves the project (Full).
2. Condition `A_source_present`: for each case, `Resource.show_in_ui` highlights it and the operator
   uses the Assets window's Export resource on it, into a fresh empty folder written after a fence.
3. The project is closed, staged sources are moved to private hash-checked preservation, Painter
   is restarted, every staged
   path is recorded absent (`sources_absent`; otherwise the run is refused), and a moved copy of
   the project is reopened. `list_project_resources` must list every case again.
4. Condition `B_source_removed`: the exports of step 2 again, from the reopened project. This is
   the pilots' condition: their sources are gone and their project is reopened.

The operator is `painter_ui.UiOperator` (`--operator ui`) or a person at the console. Every answer,
the UI log, the Assets panel images and the UI Automation surveys are private evidence in
`UZP_ORACLE_WORK\resource-export-qual\<run>\` (`evidence.json`), with the exported files.

**Analysis.** `analyse` compares every export with its original: one file written after the fence,
SHA-256 and size, SHA-1 against the resource URL's `version` (decision 194: the SHA-1 of the
imported bytes), the version's stability between the conditions, and always the measured fields
(container, size, channels, bit depth, colour metadata, compression) and decoded-pixel equality.
`OUTCOMES` defines the verdicts; decision 300 says what each means for the Sash and the Tunic.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import io
import json
import shutil
import struct
import sys
import time
import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from tools.parity.recorder.capture import write_fence
from tools.parity.recorder.output import ensure_outside_repository, run_name
from tools.parity.recorder.session import PainterIdentity, PainterSession, RecorderError
from tools.parity.recorder.texture import Now, close_quietly, utc_now
from tools.parity.schemas import REPO_ROOT

DECISION = 300
SCHEMA = "uzpainter/resource-export-qualification/1"
FIXTURE_DIR = REPO_ROOT / "parity" / "fixtures" / "resource-export"
MESH = REPO_ROOT / "parity" / "fixtures" / "meshes" / "plane.obj"
PAINTER_RESOURCES = Path(__file__).with_name("painter_resources.py")
GROUP = "uzp_rq300"
OCIO_CONFIG = "resources/ocio/substance/config.ocio"
CREATE = "substance_painter.project.create"
INSERT_FILL = "substance_painter.layerstack.insert_fill"
SET_SOURCE = "substance_painter.layerstack.FillLayerNode.set_source"
SET_EFFECT_SOURCE = "substance_painter.layerstack.FillEffectNode.set_source"
ADD_MASK = "substance_painter.layerstack.LayerNode.add_mask"
SET_MESH_MAP = "substance_painter.textureset.TextureSet.set_mesh_map_resource"
CONDITION_A = "A_source_present"
CONDITION_B = "B_source_removed"
CONDITIONS = (CONDITION_A, CONDITION_B)
EXPORT_WAIT_S = 60.0
ASSETS_PANEL = "Assets"
ABSENT, DISABLED = "absent", "disabled"
# Asked once per export. `painter_ui.UiOperator` answers it by automation (RESOURCE_EXPORT_PROMPT).
EXPORT_PROMPT = (
    "Export resource: in the Assets window, export the highlighted project resource '{gui_name}' "
    "with its Export resource menu item into the folder {target}. Enter the menu item's label as "
    "shown, or 'absent' or 'disabled':"
)
IMAGE_PROMPT = f"Path of an image of the '{ASSETS_PANEL}' panel (PNG or JPEG):"

# --- the disposable bitmaps ------------------------------------------------------------------


@dataclass(frozen=True)
class Case:
    """One disposable bitmap: what it is, how it is written, how the project uses it, its pins."""

    case_id: str
    file_name: str
    format_class: str  # png | tga | exr | jpeg
    width: int
    height: int
    channels: int
    bits: int
    colour: str  # what the file states: srgb-chunk, gamma-1.0, blender, none, exr-linear, jfif
    writer: str
    binding: str  # basecolor | mask | normal-mesh-map | ao-mesh-map: the pilots' uses
    sha256: str
    sha1: str
    size: int
    committed: bool = True
    pilot_like: bool = False  # the form of a pilot's own resource

    @property
    def form(self) -> str:
        """What a qualified case qualifies: container, size class, channels, depth, colour
        statement, writer and use."""
        return f"{self.channels}ch-{self.bits}bit-{self.colour}-{self.writer}-{self.binding}"

    @property
    def resource_name(self) -> str:
        """The UzmiGames sync's form: `<prefix><name>_<SHA-1[:6]>`."""
        return f"uzp_rq_{self.case_id.replace('-', '_')}_{self.sha1[:6]}"


EXTENSION_CLASSES = {"png": "png", "tga": "tga", "exr": "exr", "jpg": "jpeg"}


def make_case(row: str, pins: str, committed: bool = True, pilot_like: bool = False) -> Case:
    """`row`: id ext width height channels bits colour writer binding; `pins`: SHA-256 SHA-1
    size."""
    case_id, ext, width, height, channels, bits, colour, writer, binding = row.split()
    sha256, sha1, size = pins.split()
    return Case(
        case_id,
        f"{case_id}.{ext}",
        EXTENSION_CLASSES[ext],
        int(width),
        int(height),
        int(channels),
        int(bits),
        colour,
        writer,
        binding,
        sha256,
        sha1,
        int(size),
        committed=committed,
        pilot_like=pilot_like,
    )


# 64 x 48 where the size is free: not square, so a transpose changes the size fields.
CASES: tuple[Case, ...] = (
    make_case(
        "png8-rgb-srgb png 64 48 3 8 srgb-chunk uzp-png basecolor",
        "bf38651e89044b20850a6b2e2427c2b27062bdc5db81ef041a12ce8dc99833fb "
        "3b35b82af41c274a5440be44d4f4a5dd046ff923 9345",
    ),
    make_case(
        "png8-grey-linear png 64 48 1 8 gamma-1.0 uzp-png ao-mesh-map",
        "8a0e81f502deb27148308a8e5f43d0e366de2fdedb1b3ab6e5f74085c72d07d2 "
        "9249ca69da54de7b38655863787a0d2235b19c4e 3204",
    ),
    make_case(
        "png8-rgba-plain png 64 48 4 8 none uzp-png basecolor",
        "2944dca9b5f03c3c53556aaa36b0d14f4473193e9460cd4f23ad41964604b0d3 "
        "bb8079465e0d644648fbf2126c831fc0e18f16af 12404",
    ),
    make_case(
        "png16-rgb-linear png 64 48 3 16 gamma-1.0 uzp-png basecolor",
        "21860f9eff6b970edb592a0e88816eb28451bfb55dd07389aa3f65b6bbc677fc "
        "89753064bf583653b65a28ab16ebc410d41c7211 18214",
    ),
    # The Sash's Normal bake (Blender's 16-bit RGB PNG: sRGB and gAMA 45455 chunks), bound as the
    # Normal mesh map as the Sash's create script binds it.
    make_case(
        "png16-rgb-blender png 64 48 3 16 blender uzp-png normal-mesh-map",
        "57ea96ac93acab5155719b913b1dd23f9d2b9043daeb2a3e658256599407b701 "
        "f52f48a4fd7820bd5058d43d9ec4d5b01bf58d50 18228",
        pilot_like=True,
    ),
    # The Sash and Tunic masks: 16-bit grey, Pillow (`Image.fromarray(uint16).save`), bound as a
    # layer mask's fill as the UzmiGames sync binds them.
    make_case(
        "png16-grey-pillow png 256 256 1 16 none pillow-png mask",
        "3ea0661a98fd77a4cd81d8a9ce33d7136da3fa6c1e68d4c6ec01c264cb61ef2e "
        "dc5df7d6663cf60ce2bd7892469a697577d801b8 94316",
        pilot_like=True,
    ),
    # A mask at the Sash's 2048 px, generated at run time (8 MB: not committed).
    make_case(
        "png16-grey-2048 png 2048 2048 1 16 none uzp-png-stored mask",
        "f710f70a51ba732e05ce6b0a87d9443b42935263027674da02bf19b837e0d7d5 "
        "2cb6e295c061d472e092d465a98874ec4b7b151c 8391364",
        committed=False,
        pilot_like=True,
    ),
    # T_sash and the Tunic's T_*: 8-bit RGB, Pillow, no colour chunk, sRGB content.
    make_case(
        "png8-rgb-pillow png 128 128 3 8 none pillow-png basecolor",
        "de4050c23a7ea3da17fe1ef729a96593493ab6d0412e6cf644350e99006eda6f "
        "778e64bfc6affbafb59b54465f97bb92c65718aa 49308",
        pilot_like=True,
    ),
    make_case(
        "tga8-rgb-raw tga 64 48 3 8 none uzp-tga basecolor",
        "61dc7f3d4a7b70456569788f2be324652079f35a7df6f77409a058239269a64b "
        "60018963239c1d952e4c54f784705df1cef30f38 9234",
    ),
    make_case(
        "tga8-rgba-rle tga 64 48 4 8 none uzp-tga-rle basecolor",
        "2be8cb5cb73f14d81ad320d0992a341c4ec9b755d03cd68e758dcc036a0c88af "
        "661369eef7a4446e84bb922047ada83ce4b9bee2 12354",
    ),
    make_case(
        "exr-half-rgb-zip exr 64 48 3 16 exr-linear openexr-half-zip basecolor",
        "77c751ebb61eae17ef98fe8e3866ad2e3eaff8e4c11ac850956b0527a5a20dd4 "
        "d54f1277dcdf6b79aa4faa18c04471fcbf20f892 15949",
    ),
    make_case(
        "exr-float-rgba-none exr 64 48 4 32 exr-linear openexr-float-no basecolor",
        "589df2cb27832626f7665e8ebd5444a0a96fb7d569f986c213007510a0f5eb19 "
        "a810179a0faeeed12cd78228a6dbb362d07eebb6 50280",
    ),
    make_case(
        "jpeg-rgb-srgb jpg 64 48 3 8 jfif pillow-jpeg basecolor",
        "ce5324eff6594c81aba1084da9cd2616209b4e2a9829fe8e2c68acbc0a9af968 "
        "6dcb04e07c6ad64f2fb65befc0c70f3f248bf869 6353",
    ),
)


def pattern(width: int, height: int, channels: int, maximum: int, seed: int) -> Any:
    """A deterministic image of our own: ramps in x and y plus integer-hash noise per channel, so
    that any resampling, flip, transpose or requantisation changes values."""
    import numpy as np

    y, x = np.mgrid[0:height, 0:width].astype(np.uint64)
    planes = []
    for c in range(channels):
        h = (x * np.uint64(73856093)) ^ (y * np.uint64(19349663)) ^ np.uint64(seed * 83492791 + c)
        h = (h * np.uint64(2654435761)) & np.uint64(0xFFFFFFFF)
        ramp = (x * np.uint64(maximum)) // np.uint64(max(width - 1, 1))
        ramp = ramp if c % 2 == 0 else (y * np.uint64(maximum)) // np.uint64(max(height - 1, 1))
        planes.append(((ramp + (h >> np.uint64(24))) % np.uint64(maximum + 1)).astype(np.uint64))
    return np.stack(planes, axis=-1)


def png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def stored_deflate(raw: bytes) -> bytes:
    """A zlib stream of stored (uncompressed) blocks: the same bytes on every zlib version."""
    out = bytearray(b"\x78\x01")
    blocks = [raw[i : i + 65535] for i in range(0, len(raw), 65535)] or [b""]
    for index, block in enumerate(blocks):
        out.append(1 if index == len(blocks) - 1 else 0)
        out += struct.pack("<HH", len(block), len(block) ^ 0xFFFF) + block
    out += struct.pack(">I", zlib.adler32(raw) & 0xFFFFFFFF)
    return bytes(out)


PNG_COLOUR_TYPES = {1: 0, 2: 4, 3: 2, 4: 6}


def png_bytes(array: Any, bits: int, colour: str, stored: bool = False) -> bytes:
    """Our PNG encoder: filter 0 on every row; an sRGB chunk, a linear gAMA, or none."""
    height, width, channels = array.shape
    dtype = ">u2" if bits == 16 else "u1"
    rows = array.astype(dtype).reshape(height, width * channels)
    raw = b"".join(b"\x00" + row.tobytes() for row in rows)
    header = struct.pack(">IIBBBBB", width, height, bits, PNG_COLOUR_TYPES[channels], 0, 0, 0)
    extra = b""
    if colour == "srgb-chunk":
        extra = png_chunk(b"sRGB", b"\x00")
    elif colour == "gamma-1.0":
        extra = png_chunk(b"gAMA", struct.pack(">I", 100000))
    elif colour == "blender":
        extra = png_chunk(b"sRGB", b"\x00") + png_chunk(b"gAMA", struct.pack(">I", 45455))
    data = stored_deflate(raw) if stored else zlib.compress(raw, 9)
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", header)
        + extra
        + png_chunk(b"IDAT", data)
        + png_chunk(b"IEND", b"")
    )


def tga_bytes(array: Any, rle: bool) -> bytes:
    """Our TGA encoder: true colour, top-left origin, BGR(A); RLE packets when `rle`."""
    import numpy as np

    height, width, channels = array.shape
    pixels = array[..., [2, 1, 0, 3][:channels]].astype(np.uint8)
    descriptor = 0x20 | (8 if channels == 4 else 0)
    header = struct.pack(
        "<BBBHHBHHHHBB",
        0,
        0,
        10 if rle else 2,
        0,
        0,
        0,
        0,
        0,
        width,
        height,
        8 * channels,
        descriptor,
    )
    if not rle:
        return header + bytes(pixels.tobytes())
    body = bytearray()
    for row in pixels:
        items = [bytes(p) for p in row]
        i = 0
        while i < len(items):
            run = 1
            while i + run < len(items) and run < 128 and items[i + run] == items[i]:
                run += 1
            if run > 1:
                body.append(0x80 | (run - 1))
                body += items[i]
                i += run
                continue
            start = i
            while i < len(items) and i - start < 128:
                if i + 1 < len(items) and items[i + 1] == items[i]:
                    break
                i += 1
            body.append(i - start - 1)
            body += b"".join(items[start:i])
    return header + bytes(body)


def pil_png_bytes(array: Any) -> bytes:
    """Pillow's PNG writer, as the pilots' generators call it (`Image.fromarray(...).save`)."""
    from PIL import Image

    buffer = io.BytesIO()
    image = array[..., 0] if array.shape[-1] == 1 else array
    Image.fromarray(image).save(buffer, format="PNG")
    return buffer.getvalue()


def jpeg_bytes(array: Any) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="JPEG", quality=90, subsampling=0)
    return buffer.getvalue()


def exr_bytes(array: Any, half: bool, compression: str) -> bytes:
    import numpy as np
    import OpenEXR

    names = "RGBA"[: array.shape[-1]]
    dtype = np.float16 if half else np.float32
    channels = {n: np.ascontiguousarray(array[..., i]).astype(dtype) for i, n in enumerate(names)}
    header = {
        "compression": getattr(OpenEXR, f"{compression}_COMPRESSION"),
        "type": OpenEXR.scanlineimage,
    }
    target = FIXTURE_DIR / ".exr-scratch.exr"
    try:
        OpenEXR.File(header, channels).write(str(target))
        return target.read_bytes()
    finally:
        target.unlink(missing_ok=True)


def case_bytes(case: Case) -> bytes:
    """Write one case from its recipe (the `fixtures --write` command, and the runtime case)."""
    import numpy as np

    w, h, c = case.width, case.height, case.channels
    seed = sum(case.case_id.encode("utf-8"))
    if case.writer == "uzp-png":
        image = pattern(w, h, c, (1 << case.bits) - 1, seed)
        return png_bytes(image, case.bits, case.colour)
    if case.writer == "uzp-png-stored":
        image = pattern(w, h, c, (1 << case.bits) - 1, seed)
        return png_bytes(image, case.bits, case.colour, stored=True)
    if case.writer == "pillow-png":
        image = pattern(w, h, c, (1 << case.bits) - 1, seed)
        return pil_png_bytes(image.astype(np.uint16 if case.bits == 16 else np.uint8))
    if case.writer in ("uzp-tga", "uzp-tga-rle"):
        return tga_bytes(pattern(w, h, c, 255, seed), rle=case.writer == "uzp-tga-rle")
    if case.writer == "pillow-jpeg":
        return jpeg_bytes(pattern(w, h, c, 255, seed).astype(np.uint8))
    if case.writer.startswith("openexr-"):
        _, kind, compression = case.writer.split("-")
        values = pattern(w, h, c, 1023, seed).astype(np.float64) / 1023.0 * 4.0 - 0.5
        return exr_bytes(values, half=kind == "half", compression=compression.upper())
    raise RecorderError(f"case {case.case_id}: unknown writer {case.writer!r}")


def pin(case: Case, data: bytes) -> list[str]:
    """What differs between `data` and the case's pins (empty when it is the pinned file)."""
    problems = []
    if hashlib.sha256(data).hexdigest() != case.sha256:
        problems.append(f"SHA-256 {hashlib.sha256(data).hexdigest()} is not {case.sha256}")
    if hashlib.sha1(data).hexdigest() != case.sha1:
        problems.append(f"SHA-1 {hashlib.sha1(data).hexdigest()} is not {case.sha1}")
    if len(data) != case.size:
        problems.append(f"{len(data)} bytes, not {case.size}")
    return problems


def original_bytes(case: Case) -> bytes:
    """The case's original: the committed file, or the runtime case generated again."""
    data = (FIXTURE_DIR / case.file_name).read_bytes() if case.committed else case_bytes(case)
    problems = pin(case, data)
    if problems:
        raise RecorderError(f"case {case.case_id}: the original differs from its pins: {problems}")
    return data


# --- measured fields ------------------------------------------------------------------------


def measure(data: bytes) -> dict[str, Any]:
    """The fields a file states about itself, read from its header bytes only."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return png_fields(data)
    if len(data) >= 4 and struct.unpack("<i", data[:4])[0] == 20000630:
        return exr_fields(data)
    if data.startswith(b"\xff\xd8"):
        return jpeg_fields(data)
    if len(data) >= 18 and data[2] in (2, 10) and data[16] in (24, 32):
        return tga_fields(data)
    return {"container": "unknown", "size": len(data), "head": data[:8].hex()}


def png_fields(data: bytes) -> dict[str, Any]:
    offset, chunks = 8, []
    while offset + 8 <= len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        chunks.append((data[offset + 4 : offset + 8], data[offset + 8 : offset + 8 + length]))
        offset += 12 + length
        if chunks[-1][0] == b"IEND":
            break
    width, height, bits, colour_type = struct.unpack(">IIBB", chunks[0][1][:10])
    kinds = [k.decode("latin-1") for k, _ in chunks]
    gama = next((struct.unpack(">I", v)[0] for k, v in chunks if k == b"gAMA"), None)
    return {
        "container": "png",
        "width": width,
        "height": height,
        "channels": {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour_type],
        "bits": bits,
        "colour_type": colour_type,
        "chunks": [k for k in kinds if k not in ("IDAT",)] + [f"IDAT x{kinds.count('IDAT')}"],
        "srgb": "sRGB" in kinds,
        "gama": gama,
        "iccp": "iCCP" in kinds,
    }


def exr_fields(data: bytes) -> dict[str, Any]:
    offset, attributes = 8, {}
    while data[offset] != 0:
        end = data.index(b"\0", offset)
        type_end = data.index(b"\0", end + 1)
        (size,) = struct.unpack("<i", data[type_end + 1 : type_end + 5])
        attributes[data[offset:end].decode("latin-1")] = data[type_end + 5 : type_end + 5 + size]
        offset = type_end + 5 + size
    xmin, ymin, xmax, ymax = struct.unpack("<iiii", attributes["dataWindow"])
    names, types, chlist, i = [], [], attributes["channels"], 0
    while chlist[i] != 0:
        end = chlist.index(b"\0", i)
        names.append(chlist[i:end].decode("latin-1"))
        (pixel_type,) = struct.unpack("<i", chlist[end + 1 : end + 5])
        types.append({0: "uint", 1: "half", 2: "float"}[pixel_type])
        i = end + 1 + 16
    return {
        "container": "exr",
        "width": xmax - xmin + 1,
        "height": ymax - ymin + 1,
        "channels": len(names),
        "channel_names": names,
        "sample_types": types,
        "bits": 16 if set(types) == {"half"} else 32,
        "compression": attributes["compression"][0],
        "attributes": sorted(attributes),
    }


def jpeg_fields(data: bytes) -> dict[str, Any]:
    offset, markers = 2, []
    fields: dict[str, Any] = {"container": "jpeg"}
    while offset + 4 <= len(data) and data[offset] == 0xFF:
        marker = data[offset + 1]
        (length,) = struct.unpack(">H", data[offset + 2 : offset + 4])
        markers.append(f"{marker:02X}")
        if marker in (0xC0, 0xC1, 0xC2):
            bits, height, width, channels = struct.unpack(">BHHB", data[offset + 4 : offset + 10])
            fields.update(width=width, height=height, channels=channels, bits=bits)
        if marker == 0xDA:
            break
        offset += 2 + length
    fields["markers"] = markers
    return fields


def tga_fields(data: bytes) -> dict[str, Any]:
    width, height = struct.unpack("<HH", data[12:16])
    return {
        "container": "tga",
        "image_type": data[2],
        "width": width,
        "height": height,
        "channels": data[16] // 8,
        "bits": 8,
        "descriptor": data[17],
    }


def decoded(data: bytes) -> Any:
    """The pixel values a file holds (numpy), or None when it cannot be decoded here."""
    import numpy as np

    try:
        container = measure(data)["container"]
        if container == "exr":
            return exr_pixels(data)
        if container == "png":  # Pillow truncates 16-bit RGB to 8 bits
            from tools.parity.feasibility.png import decode

            return decode(data)
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            return np.asarray(image)
    except Exception:  # an undecodable export is an observation, recorded as None
        return None


def exr_pixels(data: bytes) -> Any:
    """OpenEXR channels stacked in name order (the binding reads from a path, so a temporary
    copy outside the repository is decoded)."""
    import tempfile

    import numpy as np
    import OpenEXR

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "decode.exr"
        path.write_bytes(data)
        with OpenEXR.File(str(path), separate_channels=True) as exr:
            channels = exr.channels()
            return np.stack([channels[n].pixels for n in sorted(channels)], axis=-1)


# --- the run --------------------------------------------------------------------------------


class Operator(Protocol):
    """The person at the Painter window, or `painter_ui.UiOperator`."""

    def tell(self, message: str) -> None: ...

    def ask(self, question: str) -> str: ...


def extension_code(source: str) -> str:
    """Statements that execute `painter_resources.py` into a copy of the recorder's namespace
    (the pattern of `script_run.extension_code`)."""
    import base64

    encoded = base64.b64encode(source.encode("utf-8")).decode("ascii")
    return (
        "import base64\n"
        "uzp_resources = dict(uzp_recorder)\n"
        f"exec(base64.b64decode('{encoded}').decode('utf-8'), uzp_resources)\n"
    )


class ResourceSession(PainterSession):
    """A recorder session with the resource operations loaded next to `painter_side.py`."""

    def connect(self) -> PainterIdentity:
        identity = super().connect()
        self.transport.run(extension_code(PAINTER_RESOURCES.read_text(encoding="utf-8")))
        return identity


def require_substance_ocio(identity: PainterIdentity) -> None:
    found = str(identity.colour_management.get("OCIO") or "").replace("\\", "/")
    if identity.colour_management.get("mode") != "ocio" or not found.endswith(OCIO_CONFIG):
        raise RecorderError(
            "the qualification runs under OCIO with Painter's substance configuration, as the "
            f"pilots did: start Painter with OCIO naming its {OCIO_CONFIG} "
            f"(found {identity.colour_management!r})"
        )


def stage(directory: Path) -> dict[str, Path]:
    """Hash-checked private copies: the mesh, and every case in `sources/`."""
    (directory / "sources").mkdir(parents=True)
    staged = {"mesh": directory / "mesh" / MESH.name}
    staged["mesh"].parent.mkdir()
    shutil.copyfile(MESH, staged["mesh"])
    for case in CASES:
        target = directory / "sources" / case.file_name
        target.write_bytes(original_bytes(case))
        if pin(case, target.read_bytes()):
            raise RecorderError(f"case {case.case_id}: the staged copy differs from its pins")
        staged[case.case_id] = target
    return staged


def file_record(path: Path, root: Path, fence_ns: int) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "file": path.relative_to(root).as_posix(),
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "sha1": hashlib.sha1(data).hexdigest(),
        "after_fence": path.stat().st_mtime_ns >= fence_ns,
        "is_link": path.is_symlink(),
        "fields": measure(data),
    }


def wait_for_files(
    target: Path,
    timeout_s: float,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> list[Path]:
    """The files under `target` once at least one exists and no size changed for one poll."""
    deadline = monotonic() + timeout_s
    previous: dict[Path, int] | None = None
    while True:
        current = {p: p.stat().st_size for p in sorted(target.rglob("*")) if p.is_file()}
        if current and current == previous:
            return list(current)
        if monotonic() > deadline:
            return list(current)
        previous = current
        sleep(0.5)


def menu_answer(answer: str) -> str:
    """`absent` and `disabled` in any case; any other text is the menu label as shown."""
    text = answer.strip()
    return text.casefold() if text.casefold() in (ABSENT, DISABLED) else text


def export_once(
    session: PainterSession, operator: Operator, url: str, base: Path, timeout_s: float
) -> dict[str, Any]:
    """Highlight one resource, ask the operator to export it, record what was written."""
    entry: dict[str, Any] = {"url": url}
    try:
        entry["shown"] = session.call("rq_show", url=url)
        entry["assets_image"] = operator.ask(IMAGE_PROMPT)
        target = base / "out"
        target.mkdir(parents=True)
        fence_ns = write_fence(base / "fence")
        entry["answer"] = menu_answer(
            operator.ask(EXPORT_PROMPT.format(gui_name=entry["shown"]["gui_name"], target=target))
        )
        files = [] if entry["answer"] in (ABSENT, DISABLED) else wait_for_files(target, timeout_s)
        entry["files"] = [file_record(p, target, fence_ns) for p in files]
    except RecorderError as error:
        entry["error"] = {"type": "RecorderError", "message": str(error)}
    return entry


def bind(session: PainterSession, case: Case, step: int, url: str) -> None:
    """Use the resource the way a pilot uses its kind (UzmiGames create script and sync)."""
    if case.binding in ("normal-mesh-map", "ao-mesh-map"):
        usage = "Normal" if case.binding == "normal-mesh-map" else "AO"
        session.call(
            "apply_step",
            step=step + 1,
            call=SET_MESH_MAP,
            args={"usage": usage, "resource_step": step},
        )
        return
    session.call("apply_step", step=step + 1, call=INSERT_FILL, args={"position": "top"})
    if case.binding == "basecolor":
        session.call(
            "apply_step",
            step=step + 2,
            call=SET_SOURCE,
            args={"node_step": step + 1, "channel": "BaseColor", "resource": url},
        )
        return
    session.call(
        "apply_step",
        step=step + 2,
        call=ADD_MASK,
        args={"node_step": step + 1, "background": "Black"},
    )
    session.call(
        "apply_step",
        step=step + 3,
        call=INSERT_FILL,
        args={"inside_step": step + 1, "stack": "Mask"},
    )
    session.call(
        "apply_step",
        step=step + 4,
        call=SET_EFFECT_SOURCE,
        args={"node_step": step + 3, "channel": None, "resource": url},
    )


Restart = Callable[[PainterSession], PainterSession]


def record_qualification(
    session: PainterSession,
    operator: Operator,
    work: Path,
    restart: Restart,
    now: Now = utc_now,
    export_timeout_s: float = EXPORT_WAIT_S,
) -> Path:
    """Run decision 300's qualification; returns the run directory holding `evidence.json`.

    `restart` stops the Painter process of the session it is given and returns a connected
    session on a freshly started one: condition B runs in another process, so nothing Painter
    kept in memory from the import can serve the export."""
    identity = session.connect()
    require_substance_ocio(identity)
    directory = ensure_outside_repository(work) / "resource-export-qual"
    directory = directory / run_name(identity.session_id, now())
    staged = stage(directory)
    evidence: dict[str, Any] = {
        "schema": SCHEMA,
        "decision": DECISION,
        "painter_build": identity.painter_build(),
        "session_ids": {CONDITION_A: identity.session_id},
        "colour_management": identity.colour_management,
        "environment": identity.environment,
        "started_at": now().isoformat(),
        "cases": [dataclasses.asdict(case) for case in CASES],
        "imports": {},
        "conditions": {c: {} for c in CONDITIONS},
    }
    project = directory / "project" / "rq300.spp"
    moved = directory / "moved" / "rq300-moved.spp"
    project.parent.mkdir()
    try:
        mesh = staged["mesh"].as_posix()
        session.call("apply_step", step=1, call=CREATE, args={}, resolved={"mesh": mesh})
        session.wait_ready()
        for index, case in enumerate(CASES):
            step = 10 * (index + 1)
            imported = session.call(
                "rq_import",
                step=step,
                path=staged[case.case_id].as_posix(),
                name=case.resource_name,
                group=GROUP,
            )
            bind(session, case, step, imported["url"])
            evidence["imports"][case.case_id] = imported
        session.wait_ready()
        session.call("save_as", path=project.as_posix())
        session.wait_ready()
        for case in CASES:
            url = evidence["imports"][case.case_id]["url"]
            base = directory / "exports" / CONDITION_A / case.case_id
            evidence["conditions"][CONDITION_A][case.case_id] = export_once(
                session, operator, url, base, export_timeout_s
            )
        session.call("close_project")
        session.wait_closed()
        preserved = directory / "preserved-sources"
        preserved.mkdir()
        evidence["preserved_sources"] = {}
        for case in CASES:
            source = staged[case.case_id]
            data = source.read_bytes()
            if hashlib.sha256(data).hexdigest() != case.sha256:
                raise RecorderError(f"staged source changed before preservation: {case.case_id}")
            target = preserved / case.file_name
            source.rename(target)
            if hashlib.sha256(target.read_bytes()).hexdigest() != case.sha256:
                raise RecorderError(f"preserved source differs: {case.case_id}")
            evidence["preserved_sources"][case.case_id] = {
                "path": target.relative_to(directory).as_posix(),
                "sha256": case.sha256,
                "size_bytes": len(data),
            }
        session = restart(session)
        fresh = session.identity
        if fresh is None or fresh.session_id == identity.session_id:
            raise RecorderError("condition B needs a freshly started Painter process")
        evidence["session_ids"][CONDITION_B] = fresh.session_id
        require_substance_ocio(fresh)
        # Measured just before B opens the project: every staged path, and whether it is absent.
        evidence["sources_absent"] = {
            case.case_id: {
                "path": staged[case.case_id].relative_to(directory).as_posix(),
                "absent": not staged[case.case_id].exists(),
            }
            for case in CASES
        }
        evidence["sources_removed"] = all(
            v["absent"] for v in evidence["sources_absent"].values()
        ) and not any((directory / "sources").iterdir())
        if not evidence["sources_removed"]:
            raise RecorderError("condition B needs every staged source removed")
        moved.parent.mkdir()
        shutil.copyfile(project, moved)
        session.call("open_project", path=moved.as_posix())
        session.wait_ready()
        listed = session.call("rq_project_resources", names=[c.resource_name for c in CASES])
        evidence["reopened_resources"] = listed
        for case in CASES:
            base = directory / "exports" / CONDITION_B / case.case_id
            entries = listed.get(case.resource_name, [])
            if len(entries) != 1 or len(entries[0]["retrieved"]) != 1:
                evidence["conditions"][CONDITION_B][case.case_id] = {
                    "error": {
                        "type": "NotListed",
                        "message": f"the reopened project lists {len(entries)} resources named "
                        f"{case.resource_name}",
                    }
                }
                continue
            url = entries[0]["retrieved"][0]["url"]
            evidence["conditions"][CONDITION_B][case.case_id] = export_once(
                session, operator, url, base, export_timeout_s
            )
    finally:
        close_quietly(session)
        evidence["ui_log"] = list(getattr(operator, "log", []))
        evidence["finished_at"] = now().isoformat()
        (directory / "evidence.json").write_text(
            json.dumps(evidence, indent=1, sort_keys=True), encoding="utf-8"
        )
    analysis = analyse(directory)
    (directory / "analysis.json").write_text(json.dumps(analysis, indent=1), encoding="utf-8")
    return directory


# --- analysis -------------------------------------------------------------------------------

# Per case and condition.
EXACT = "exact"  # one file after the fence; SHA-256, size and SHA-1 equal; version is the SHA-1
EXACT_BYTES_VERSION_DIFFERS = "exact-bytes-version-differs"
RE_ENCODED = "re-encoded"  # one file, other bytes that decode as an image here
UNDECODED = "other-bytes-undecoded"  # one file, other bytes that do not decode: no proof
MULTIPLE_FILES = "multiple-files"
NO_FILE = "no-file"
MENU_ABSENT = "menu-absent"
MENU_DISABLED = "menu-disabled"
STALE = "stale-or-link"  # a file older than the fence, or a link: never an export of this run
NOT_PROJECT = "not-project"  # the highlighted resource is not a PROJECT resource
INCONCLUSIVE = "inconclusive"  # the operator or the automation could not complete the step

# What a case's failure establishes: the operation wrote other image bytes, or nothing. Every
# other non-exact status (version, fence, location, several files, undecodable bytes) and an
# unstable version prove nothing about the operation: the case stays unresolved (SUP-019).
ESTABLISHED_FAILURES = (RE_ENCODED, NO_FILE, MENU_ABSENT, MENU_DISABLED)

# Overall (decision 300 item 5).
OUTCOMES = {
    "EXACT": "every case is exact in both conditions",
    "PARTIAL": "some cases are exact in both conditions, others are not: only their forms qualify",
    "RE_ENCODED": "no case is exact: re-encoded files are written, and every other case wrote "
    "nothing or offered no enabled menu item",
    "SOURCE_DEPENDENT": "a case is exact with its source present but, after its removal, "
    "re-encoded, not written or not offered",
    "UNAVAILABLE": "the menu item is absent or disabled, or nothing is written, for every case",
    "INCONCLUSIVE": "a step could not be completed, condition B is not proven (a fresh process "
    "after every source was removed), or no case is exact and a failure proves nothing; fix the "
    "cause from the evidence and re-run",
}


def case_status(case: Case, entry: dict[str, Any]) -> dict[str, Any]:
    """The status of one export of one case (the constants above)."""
    result: dict[str, Any] = {"status": INCONCLUSIVE, "differs": []}
    if "error" in entry or "answer" not in entry:
        result["error"] = entry.get("error")
        return result
    shown = entry.get("shown") or {}
    version = shown.get("version")
    if shown.get("location") != "PROJECT":
        return {**result, "status": NOT_PROJECT, "location": shown.get("location")}
    answer = str(entry["answer"]).strip()
    result["menu_label"] = answer
    if answer == ABSENT:
        return {**result, "status": MENU_ABSENT}
    if answer == DISABLED:
        return {**result, "status": MENU_DISABLED}
    files = entry.get("files", [])
    if not files:
        return {**result, "status": NO_FILE}
    if any(not f["after_fence"] or f["is_link"] for f in files):
        return {**result, "status": STALE}
    if len(files) != 1:
        return {**result, "status": MULTIPLE_FILES, "files": [f["file"] for f in files]}
    exported = files[0]
    result["file"] = exported["file"]
    expected = {
        "container": case.format_class,
        "width": case.width,
        "height": case.height,
        "channels": case.channels,
        "bits": case.bits,
    }
    result["differs"] = sorted(k for k, v in expected.items() if exported["fields"].get(k) != v)
    same_bytes = exported["sha256"] == case.sha256 and exported["size"] == case.size
    if not same_bytes:
        result["differs"] = sorted({*result["differs"], "bytes"})
        return {**result, "status": RE_ENCODED}
    if exported["sha1"] != case.sha1 or version != case.sha1:
        return {**result, "status": EXACT_BYTES_VERSION_DIFFERS, "version": version}
    return {**result, "status": EXACT}


def pixel_comparison(case: Case, exported: Any) -> bool | None:
    """Whether a re-encoded export's decoded values are the original's (None: the original
    does not decode here)."""
    import numpy as np

    original = decoded(original_bytes(case))
    if original is None:
        return None
    return bool(exported.shape == original.shape and np.array_equal(exported, original))


def analyse(directory: Path) -> dict[str, Any]:
    """Verdicts of one run (no Painter needed); `analysis.json` holds the same."""
    evidence = json.loads((directory / "evidence.json").read_text(encoding="utf-8"))
    if evidence.get("schema") != SCHEMA:
        raise RecorderError(f"{directory}: not a decision {DECISION} run")
    rows: dict[str, Any] = {}
    for case in CASES:
        imported = evidence["imports"].get(case.case_id, {})
        row: dict[str, Any] = {
            "format_class": case.format_class,
            "form": case.form,
            "pilot_like": case.pilot_like,
            "import_version": imported.get("version"),
            "import_location": imported.get("location"),
            "version_is_sha1": imported.get("version") == case.sha1,
        }
        for condition in CONDITIONS:
            entry = evidence["conditions"].get(condition, {}).get(case.case_id, {})
            status = case_status(case, entry)
            status["version"] = (entry.get("shown") or {}).get("version")
            if status["status"] == RE_ENCODED:  # other bytes: re-encoded only if they decode
                path = directory / "exports" / condition / case.case_id / "out" / status["file"]
                exported = decoded(path.read_bytes())
                if exported is None:
                    status["status"] = UNDECODED
                else:
                    status["pixels_equal"] = pixel_comparison(case, exported)
            row[condition] = status
        versions = {row[condition]["version"] for condition in CONDITIONS}
        row["version_stable"] = len(versions) == 1 and None not in versions
        rows[case.case_id] = row
    sessions = evidence.get("session_ids", {})
    fresh = len({sessions.get(c) for c in CONDITIONS} - {None}) == len(CONDITIONS)
    removed = sources_removal_verified(evidence)
    return {
        "schema": SCHEMA + "/analysis",
        "outcome": outcome(rows, fresh, removed),
        "fresh_process_for_b": fresh,
        "sources_removed_verified": removed,
        "cases": rows,
    }


def sources_removal_verified(evidence: dict[str, Any]) -> bool:
    """Whether the evidence shows every case's staged source absent before condition B: the
    run's flag is literally true and the per-path record names every case, each at its staged
    path `sources/<file name>` and absent."""
    absent = evidence.get("sources_absent")
    return (
        evidence.get("sources_removed") is True
        and isinstance(absent, dict)
        and set(absent) == {case.case_id for case in CASES}
        and all(
            isinstance(v, dict)
            and v.get("path") == f"sources/{case.file_name}"
            and v.get("absent") is True
            for case in CASES
            for v in [absent[case.case_id]]
        )
    )


def outcome(
    rows: dict[str, Any], fresh_process_for_b: bool, sources_removed: bool
) -> dict[str, Any]:
    """The run's verdict (`OUTCOMES`). Condition B qualifies only when it ran in a freshly
    started Painter process after every staged source was verified absent; otherwise the run is
    inconclusive. PARTIAL needs exact cases (a whole format class need not be exact); RE_ENCODED
    and SOURCE_DEPENDENT need failures that establish them (`ESTABLISHED_FAILURES`), and
    RE_ENCODED at least one `re-encoded` export; any other combination is INCONCLUSIVE."""
    statuses = {c: [rows[c][k]["status"] for k in CONDITIONS] for c in rows}
    exact = {c for c, s in statuses.items() if s == [EXACT, EXACT] and rows[c]["version_stable"]}
    classes = sorted({rows[c]["format_class"] for c in rows})
    exact_classes = [
        k for k in classes if all(c in exact for c in rows if rows[c]["format_class"] == k)
    ]
    established = (EXACT, *ESTABLISHED_FAILURES)
    unresolved = sorted(
        c
        for c, s in statuses.items()
        if c not in exact and (s == [EXACT, EXACT] or any(x not in established for x in s))
    )
    pilot_cases = [c for c in rows if rows[c]["pilot_like"]]
    b_proven = fresh_process_for_b and sources_removed
    if not b_proven or any(INCONCLUSIVE in s for s in statuses.values()):
        verdict = "INCONCLUSIVE"
    elif len(exact) == len(rows):
        verdict = "EXACT"
    elif any(s[0] == EXACT and s[1] in ESTABLISHED_FAILURES for s in statuses.values()):
        verdict = "SOURCE_DEPENDENT"
    elif all(x in (MENU_ABSENT, MENU_DISABLED, NO_FILE) for s in statuses.values() for x in s):
        verdict = "UNAVAILABLE"
    elif exact:
        verdict = "PARTIAL"
    elif all(x in ESTABLISHED_FAILURES for s in statuses.values() for x in s) and any(
        RE_ENCODED in s for s in statuses.values()
    ):
        verdict = "RE_ENCODED"
    else:
        verdict = "INCONCLUSIVE"
    qualified = exact if verdict in ("EXACT", "PARTIAL") else set()
    forms = sorted({f"{r['format_class']}/{r['form']}" for c, r in rows.items() if c in qualified})
    return {
        "verdict": verdict,
        "meaning": OUTCOMES[verdict],
        "exact_cases": sorted(exact),
        "qualified_forms": forms,
        "exact_format_classes": exact_classes if qualified else [],
        "unresolved_cases": unresolved,
        "pilot_forms_exact": bool(pilot_cases) and all(c in qualified for c in pilot_cases),
    }


def report_markdown(analysis: dict[str, Any], evidence: dict[str, Any]) -> str:
    """The public report: identifiers, statuses, field names and hashes only."""
    lines = [
        f"# Export resource qualification (decision {DECISION})",
        "",
        f"Painter build `{evidence['painter_build']['build_id']}`, colour management "
        f"`{evidence['colour_management'].get('mode')}`, run `{evidence['started_at']}`.",
        "",
        f"**Verdict: {analysis['outcome']['verdict']}** ({analysis['outcome']['meaning']}). "
        f"Qualified forms: {', '.join(analysis['outcome']['qualified_forms']) or 'none'}. "
        f"Exact format classes: {', '.join(analysis['outcome']['exact_format_classes']) or 'none'}."
        f" Pilot forms exact: {'yes' if analysis['outcome']['pilot_forms_exact'] else 'no'}."
        f" Unresolved cases: {', '.join(analysis['outcome']['unresolved_cases']) or 'none'}."
        f" Fresh process for B: {'yes' if analysis['fresh_process_for_b'] else 'no'}; every "
        f"source verified absent: {'yes' if analysis['sources_removed_verified'] else 'no'}.",
        "",
        "| Case | Class | Version = SHA-1 at import | A (source present) | B (source removed) "
        "| Version stable | Fields that differ |",
        "|---|---|---|---|---|---|---|",
    ]
    for case in CASES:
        row = analysis["cases"][case.case_id]
        differs = sorted({*row[CONDITION_A]["differs"], *row[CONDITION_B]["differs"]})
        lines.append(
            f"| `{case.case_id}` | {case.format_class} | "
            f"{'yes' if row['version_is_sha1'] else 'no'} | "
            f"{row[CONDITION_A]['status']} | {row[CONDITION_B]['status']} | "
            f"{'yes' if row['version_stable'] else 'no'} | {', '.join(differs) or '-'} |"
        )
    lines += ["", "Originals (SHA-256) and exports (SHA-256) per condition:", ""]
    for case in CASES:
        hashes = []
        for condition in CONDITIONS:
            files = evidence["conditions"][condition].get(case.case_id, {}).get("files", [])
            hashes.append(", ".join(f"`{f['sha256']}`" for f in files) or "none")
        lines.append(f"- `{case.case_id}` `{case.sha256}`: A {hashes[0]}; B {hashes[1]}")
    return "\n".join(lines) + "\n"


# --- the fixtures command -------------------------------------------------------------------


def fixtures(write: bool) -> list[str]:
    """Check (or, with `write`, rewrite) the committed cases; the runtime case is regenerated and
    checked either way. Returns the problems found."""
    problems = []
    for case in CASES:
        if write and case.committed:
            FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
            (FIXTURE_DIR / case.file_name).write_bytes(case_bytes(case))
        data = (FIXTURE_DIR / case.file_name).read_bytes() if case.committed else case_bytes(case)
        problems += [f"{case.case_id}: {p}" for p in pin(case, data)]
    return problems


def describe(case: Case, data: bytes) -> str:
    return (
        f"{case.case_id}: sha256={hashlib.sha256(data).hexdigest()} "
        f"sha1={hashlib.sha1(data).hexdigest()} size={len(data)}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.parity.recorder.resource_qualification")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("fixtures", help="check (or --write) the disposable bitmaps")
    command.add_argument("--write", action="store_true")
    command.add_argument("--describe", action="store_true", help="print each case's hashes")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.describe:
        for case in CASES:
            path = FIXTURE_DIR / case.file_name
            data = path.read_bytes() if case.committed and path.exists() else case_bytes(case)
            print(describe(case, data))
        return 0
    problems = fixtures(args.write)
    print("\n".join(problems) or f"{len(CASES)} cases match their pins")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
