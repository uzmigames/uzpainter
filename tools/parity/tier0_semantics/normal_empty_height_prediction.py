"""Decision 245 section 2's native prediction: the authored `uzp-export-tests export-diagnostic`
inputs of `export-padding-normal-empty-height` and the check of what the runner prints.

The spec is closed and written out field by field, because `ParseSpec`
(`tests/export/export_test.cpp`) applies no facade default: the default template's five channels
with their formats, Legacy colour management, OpenGL, 256 px on the pinned sphere, normal-b bound
as the Normal mesh map, and one visible fill whose only source and only active channel is Normal
(normal-a, colour space `NormalXYZLeft`, which decisions 214 and 226 record as the Normal
channel's default and `sources.cpp` reads as linear), Normal blend at opacity 1, identity Nearest
Repeat UV. There is no Height layer and no Height source. `Sharp` is the native stand-in for the
height-to-normal method: with a flat Height of 0 at 256 px the method does not change the
prediction (H0), and nothing here says Painter's method was measured.

The prediction is `infinite` only. `export-diagnostic` records production's two island refusals
as `bypassed` instead of throwing them (decisions 286, 308), and still refuses a virtual normal
under `passthrough` (`src/export/guards.cpp`), so the third run is a negative control. The runner
prints `{"written": [...]}` or `{"error", "message"}` and exits 0 either way, so
`validate_result` reads the printed result, never the exit code, and returns a report that marks
itself nonconformant. This module never runs the native executable; the expected bits and the
predictions are in parity/reports/phase1/normal-empty-height-freeze.md.
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.feasibility import png
from tools.parity.preserve_diagnostic_evidence import file_fingerprint
from tools.parity.recorder.job import canonical_json
from tools.parity.recorder.resource_qualification import exr_fields
from tools.parity.schemas import REPO_ROOT
from tools.parity.tier0_semantics import normal_empty_height as request
from tools.parity.tier0_semantics import recording_requests as rr
from tools.parity.tier0_semantics.ocio16_raw_readout_control import UV

SIZE = 256
TEMPLATE_ID = "default"
TEMPLATE_PATH = "assets/templates/default.json"
EVALUATOR_PROFILE = "painter-12.1-isolated-coverage-weights"  # src/evaluator/profile.h
COLOR_MANAGEMENT = "legacy"
NORMAL_MAP_FORMAT = "OpenGL"
HEIGHT_TO_NORMAL_METHOD = "Sharp"  # a native stand-in for H0, not Painter's measured method
SOURCE_COLOR_SPACE = "NormalXYZLeft"
# The default template's channels, formats and bases (assets/templates/default.json), frozen.
TEMPLATE_CHANNELS = (
    ("BaseColor", "sRGB8", [0.800000011920929, 0.800000011920929, 0.800000011920929]),
    ("BaseMetalness", "L8", [0.0, 0.0, 0.0]),
    ("Height", "L16F", [0.0, 0.0, 0.0]),
    ("Normal", "RGB16F", [0.49803921580314636, 0.49803921580314636, 1.0]),
    ("SpecularRoughness", "L8", [0.2980392277240753, 0.2980392277240753, 0.2980392277240753]),
)
# The freeze note's input pins.
INPUT_SHA256 = {
    "sphere": "d263a715bce05810252aebbffec801645fb60a991d2311536935503c79640476",
    "normal-a": "4f8b9665b5c3d6ed7dff89b2b66c0ceeb138d67e453c871e9fb07e8fe0ac2c4d",
    "normal-b": "d6b52db099f6bd551a57632524cc66a9e8bda8c0867fbd31fdbcafa7a19aacea",
}
SPEC_KEYS = frozenset(
    {
        "name",
        "resolution",
        "template",
        "evaluator_profile",
        "color_management",
        "normal_map_format",
        "height_to_normal_method",
        "mesh",
        "channels",
        "resources",
        "mesh_maps",
        "layers",
    }
)


def channel(dest: str, kind: str, name: str) -> dict[str, str]:
    return {"destChannel": dest, "srcChannel": dest, "srcMapType": kind, "srcMapName": name}


# fileName -> channels of each planned file.
MAPS = {
    "n": [channel(c, "virtualMap", "Normal_OpenGL") for c in "RGB"],
    "h": [channel("L", "documentMap", "height")],
    "normal": [channel(c, "documentMap", "normal") for c in "RGB"],
    "normal_base": [channel(c, "meshMap", "normal_base") for c in "RGB"],
}
EXR32 = {"fileFormat": "exr", "bitDepth": "32f", "dithering": False}
PNG16 = {"fileFormat": "png", "bitDepth": "16", "dithering": False}
# Run -> (export parameters, padding, file names). The last run must be refused.
RUNS = {
    "exr32-infinite": (EXR32, "infinite", ("n", "h", "normal", "normal_base")),
    "png16-infinite": (PNG16, "infinite", ("n",)),
    "exr32-passthrough-refused": (EXR32, "passthrough", ("n",)),
}
REFUSED_RUN = "exr32-passthrough-refused"

# The causes `export-diagnostic` records (src/export/padding.cpp IslandNormalRefusal,
# src/export/guards.cpp PaddingRefusal), each with its decision.
ISLAND_NORMAL_CAUSE = (
    "reads the combined virtual normal on a texture set whose UV islands do not cover the whole "
    "tile",
    "decision 245",
)
INFINITE_CAUSE = (
    'the padding "infinite" on a texture set whose UV islands do not cover the whole tile is not '
    "exact",
    "decision 259",
)
PASSTHROUGH_CAUSE = (
    'the padding "passthrough" of a virtualMap source outside the UV islands is not recorded',
    "decision 245",
)
# fileName -> the causes its `bypassed` list must hold, in order, under `infinite`.
BYPASSED = {
    "n": (ISLAND_NORMAL_CAUSE, INFINITE_CAUSE),
    "h": (INFINITE_CAUSE,),
    "normal": (INFINITE_CAUSE,),
    "normal_base": (INFINITE_CAUSE,),
}


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def input_path(name: str, root: Path = REPO_ROOT) -> Path:
    path = root / rr.fixture(name)[1]
    data = path.read_bytes()
    require(
        hashlib.sha256(data).hexdigest() == INPUT_SHA256[name], f"{name} is not the pinned input"
    )
    return path


def check_template(root: Path = REPO_ROOT) -> None:
    """The shipped default template still has the frozen channels, formats and bases."""
    document = json.loads((root / TEMPLATE_PATH).read_text(encoding="utf-8"))
    require(document["id"] == TEMPLATE_ID, "template id")
    found = [(c["type"], c["format"], c["base"]) for c in document["channels"]]
    require(found == list(TEMPLATE_CHANNELS), "template channels, formats or bases")


def spec(root: Path = REPO_ROOT) -> dict[str, Any]:
    """The closed `ParseSpec` document; every path is absolute, so it may be written anywhere."""
    check_template(root)
    fill_sha, map_sha = INPUT_SHA256[request.FILL_INPUT], INPUT_SHA256[request.MESH_MAP_INPUT]
    layer = {
        "kind": "fill",
        "name": request.LAYER_NAME,
        "visible": True,
        "sources": {request.CHANNEL: {"bitmap": fill_sha, "color_space": SOURCE_COLOR_SPACE}},
        "active_channels": [request.CHANNEL],
        "blending": {request.CHANNEL: {"mode": "Normal", "opacity": 1.0}},
        "projection": {"mode": "UV", **UV},
    }
    return {
        "name": request.TEXTURE_SET,
        "resolution": [SIZE, SIZE],
        "template": TEMPLATE_ID,
        "evaluator_profile": EVALUATOR_PROFILE,
        "color_management": COLOR_MANAGEMENT,
        "normal_map_format": NORMAL_MAP_FORMAT,
        "height_to_normal_method": HEIGHT_TO_NORMAL_METHOD,
        "mesh": input_path(request.MESH, root).as_posix(),
        "channels": [{"type": t, "format": f} for t, f, _ in TEMPLATE_CHANNELS],
        "resources": [
            {"sha256": INPUT_SHA256[name], "png": input_path(name, root).as_posix()}
            for name in (request.FILL_INPUT, request.MESH_MAP_INPUT)
        ],
        "mesh_maps": {request.CHANNEL: map_sha},
        "layers": [layer],
    }


def config(run: str, out: Path) -> dict[str, Any]:
    """The export configuration of `run`, writing under `out`."""
    parameters, padding, names = RUNS[run]
    maps = [{"fileName": f"$textureSet_{name}", "channels": MAPS[name]} for name in names]
    return {
        "exportShaderParams": False,
        "exportPath": out.as_posix(),
        "defaultExportPreset": "p",
        "exportPresets": [{"name": "p", "maps": maps}],
        "exportList": [{"rootPath": request.TEXTURE_SET}],
        "exportParameters": [{"parameters": parameters | {"paddingAlgorithm": padding}}],
    }


def planned(run: str) -> dict[str, str]:
    """relativePath -> fileName of every file `run` writes."""
    parameters, _, names = RUNS[run]
    return {f"{request.TEXTURE_SET}_{name}.{parameters['fileFormat']}": name for name in names}


def holds(message: Any, relative: str, cause: tuple[str, str]) -> bool:
    """`message` is a refusal of this texture set's file `relative`, for `cause`."""
    return (
        type(message) is str
        and message.startswith(f'export: {request.TEXTURE_SET} map "')
        and f"({relative}): " in message
        and all(part in message for part in cause)
    )


def validate_result(run: str, result: Any, out: Path) -> dict[str, Any]:
    """The printed result of `run`, checked; returns the checker's own report.

    A positive run must print only `written`: exactly the planned files, each once, each entry
    with its four fields typed, at `out/relativePath`, each `bypassed` list exactly its causes
    bound to that file, and `undecided` a count that is kept, not required to be 0. The refused
    run must print only `error` NotYetSupported with the passthrough cause of its one file."""
    require(type(result) is dict, "result")
    expected = planned(run)
    if run == REFUSED_RUN:
        require(set(result) == {"error", "message"}, "refused run prints error and message only")
        require(result["error"] == "NotYetSupported", "refused run error kind")
        (relative,) = expected
        require(holds(result["message"], relative, PASSTHROUGH_CAUSE), "refused run cause")
        return {"run": run, "conformant": False, "refused": result["message"]}
    require(set(result) == {"written"}, "a positive run prints written only")
    written = result["written"]
    require(type(written) is list and len(written) == len(expected), "written count")
    for entry in written:
        require(
            type(entry) is dict
            and set(entry) == {"relativePath", "path", "bypassed", "undecided"}
            and type(entry["relativePath"]) is str
            and type(entry["path"]) is str,
            "written entry",
        )
    paths = [entry["relativePath"] for entry in written]
    require(len(set(paths)) == len(paths), "a planned file is written twice")
    require(set(paths) == set(expected), "written files")
    files: dict[str, Any] = {}
    for entry in written:
        relative = entry["relativePath"]
        require(entry["path"] == (out / relative).as_posix(), f"path of {relative}")
        bypassed = entry["bypassed"]
        causes = BYPASSED[expected[relative]]
        require(
            type(bypassed) is list
            and len(bypassed) == len(causes)
            and all(holds(m, relative, c) for m, c in zip(bypassed, causes, strict=True)),
            f"bypassed causes of {relative}",
        )
        undecided = entry["undecided"]
        require(type(undecided) is int and undecided >= 0, f"undecided of {relative}")
        files[relative] = {"bypassed": bypassed, "undecided": undecided}
    return {"run": run, "conformant": False, "files": files}


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
EXR_SIGNATURE = b"\x76\x2f\x31\x01"


def png16_rgb(path: Path) -> npt.NDArray[np.uint16]:
    """The codes of a 256 x 256 16-bit RGB PNG, refused unless its IHDR says exactly that (an
    8-bit file would also decode to uint16)."""
    data = path.read_bytes()
    require(data[:8] == PNG_SIGNATURE and data[12:16] == b"IHDR", f"{path.name}: PNG signature")
    width, height, depth, colour = struct.unpack(">IIBB", data[16:26])
    require((width, height, depth, colour) == (SIZE, SIZE, 16, 2), f"{path.name}: PNG header")
    codes = png.decode(data)
    require(codes.dtype == np.uint16 and codes.shape == (SIZE, SIZE, 3), f"{path.name}: codes")
    return codes


def exr_words(path: Path, channels: tuple[str, ...]) -> dict[str, npt.NDArray[np.uint32]]:
    """The float32 words of each channel of a single-part 256 x 256 FLOAT OpenEXR file, read
    from its own path (no copy), refused unless its channel set is exactly `channels`, every
    channel is FLOAT, unsampled and finite, and the file is unchanged by the read."""
    import OpenEXR

    data = path.read_bytes()
    require(data[:4] == EXR_SIGNATURE, f"{path.name}: EXR signature")
    header = exr_fields(data)
    require(
        (header["width"], header["height"]) == (SIZE, SIZE)
        and sorted(header["channel_names"]) == sorted(channels)
        and header["sample_types"] == ["float"] * len(channels),
        f"{path.name}: EXR header",
    )
    before = file_fingerprint(path)
    require(before == (hashlib.sha256(data).hexdigest(), len(data)), f"{path.name}: fingerprint")
    words: dict[str, npt.NDArray[np.uint32]] = {}
    with OpenEXR.File(str(path), separate_channels=True) as image:
        require(len(image.parts) == 1, f"{path.name}: one EXR part")
        found = image.channels()
        require(set(found) == set(channels), f"{path.name}: EXR channels")
        for name in channels:
            channel = found[name]
            require(channel.xSampling == channel.ySampling == 1, f"{path.name}: {name} sampling")
            plane = np.asarray(channel.pixels)
            require(
                plane.dtype == np.dtype(np.float32) and plane.shape == (SIZE, SIZE),
                f"{path.name}: {name} FLOAT32 plane",
            )
            require(bool(np.isfinite(plane).all()), f"{path.name}: {name} non-finite sample")
            words[name] = plane.view(np.uint32).copy()
    require(file_fingerprint(path) == before, f"{path.name}: changed while read")
    return words


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def partial_pins(
    executable: Path,
    templates: Path,
    spec_document: dict[str, Any],
    configs: dict[str, dict[str, Any]],
    outputs: dict[str, Path],
) -> dict[str, Any]:
    """Partial pins of one prediction run, raw and after the run only: the executable, every
    template file, the canonical spec and configurations, and each written file. Not a full
    receipt: the decoded digests and the native input closure are added by the run wrapper of
    the next slice."""
    return {
        "partial": True,
        "executable_sha256": sha256_file(executable),
        "templates": {
            p.relative_to(templates).as_posix(): sha256_file(p)
            for p in sorted(templates.rglob("*.json"))
        },
        "spec_sha256": hashlib.sha256(canonical_json(spec_document)).hexdigest(),
        "configs_sha256": {
            run: hashlib.sha256(canonical_json(c)).hexdigest() for run, c in sorted(configs.items())
        },
        "outputs_sha256": {name: sha256_file(p) for name, p in sorted(outputs.items())},
        "height_to_normal_method": f"{HEIGHT_TO_NORMAL_METHOD} (native stand-in, not measured)",
        "conformant": False,
    }
