"""The UzEngine preset on Wand v1 (phase3.2_uze-uzmat-preset items 3.1 and 3.3; decisions 414,
417, 418, 420).

One production rebuild of the Wand's glTF pilot job (`phase3/tier1/wand-v1-gltf`: the pinned
pipeline scripts, then Painter's glTF preset as the closing export), as
`tests/parity/tier1/test_gltf_pilots.py` runs it. That job's files are the proven PNG route: the
glTF pilots test compares the same rebuild's files with Painter's own export under EXC-013 and
EXC-014. Then, in further `UzPainter.exe run` processes over the same saved project:

- Item 3.1: the dry run of the shipped `uzengine` preset (`list_project_textures` and the typed
  plan) lists exactly the table's files for the Wand's channels: albedo (RGB, no Opacity channel),
  normal, ORM (AO_Mixed in decision 418's scope), height, the black emissive derivative of decision
  420 (no Emissive channel) and the `.uzmat`, each derivative with its format, colour space,
  binding and canonical map. Emissive and SpecularWeight maps are skipped as absent channels. The
  export then publishes exactly the listed files, and the `.uzmat` binds that generation's
  derivatives.
- Item 3.3: the canonical maps equal, in decoded values on every texel, the same channels of the
  proven PNG route of the same rebuild. Canonical albedo = glTF baseColor, canonical ORM = glTF
  occlusionRoughnessMetallic (its G and B also = the script's Roughness and Metallic), height = the
  script's Height. The DirectX normal's R and B equal the glTF (OpenGL) normal's, and its green is
  mirrored within one code.

It runs only when `UZP_TIER1_PRODUCTION=1` (a GPU rebuild, never part of the suite), on the
owner's machine with the Assets3D repository and the private oracle store, and prints a summary
line (`UZE_WAND:`).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.adapters.assets3d.wand import ASSETS3D, CLOSING_EXPORT_CODE
from tests.parity.tier1.test_mcp_round import fast_painter  # noqa: F401  (the fixture)
from tests.parity.tier1.wand_v1 import runner as wand_runner
from tests.parity.tier1.wand_v1.test_wand_production import PRODUCTION_ENV
from tools.parity.fit.decode import decode
from tools.parity.recorder.gltf_pilots import PILOT_GOLDENS
from tools.parity.store.store import locate
from tools.parity.verdict import resolve_golden

PRODUCTION_EXCEPTIONS = frozenset({"EXC-013", "EXC-014"})
# Delivered map stem -> (format, sRGB, binding, canonical relative path or None).
DERIVATIVES = {
    "albedo": ("BC7", True, "albedo", "canonical/{s}_albedo.png"),
    "normal": ("BC5", False, "normal", "{s}_normal.png"),
    "orm": ("BC7", False, "orm", "canonical/{s}_orm.png"),
    "height": ("BC4", False, "heightmap", "{s}_height.png"),
}

pytestmark = [
    pytest.mark.skipif(
        not (ASSETS3D / "AGENTS.md").is_file(),
        reason=f"the UzmiGames asset repository is not at {ASSETS3D} (local run, decision 028)",
    ),
    pytest.mark.skipif(locate() is None, reason="no private oracle store on this machine"),
    pytest.mark.skipif(
        os.environ.get(PRODUCTION_ENV) != "1",
        reason=f"opt-in GPU run: set {PRODUCTION_ENV}=1 (decision 417)",
    ),
]

PLAN_CODE = """import json

import substance_painter.export
import uzpainter

config = json.loads(__CONFIG__)
listed = substance_painter.export.list_project_textures(config)
result = {
    "listed": [[list(key), list(files)] for key, files in listed.items()],
    "plan": uzpainter.export.plan(config),
}
"""


def values(path: Path) -> np.ndarray:
    """The decoded samples of a PNG, (height, width, channels)."""
    array: np.ndarray = decode(path.read_bytes()).values
    return array.reshape(array.shape[0], array.shape[1], -1)


def test_wand_v1_uzengine_export_lists_the_table_and_equals_the_png_route(
    fast_painter: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    found = PILOT_GOLDENS["wand-v1"][1]
    resolved = resolve_golden(found)
    if resolved is None:
        pytest.skip(f"{found} is not admitted")
    wand, route = wand_runner.rebuild(fast_painter, tmp_path / "run-1", resolved.manifest_path)
    assert not route.refused, route.refusal
    assert wand.job.config_export is not None
    closing = wand.job.config_export.config
    [entry] = closing["exportList"]
    s = entry["rootPath"]
    by_suffix = {key[1].removeprefix(f"{s}_"): path for key, path in route.files.items()}
    out = tmp_path / "uzengine"
    parameters = {k: closing["exportParameters"][0]["parameters"][k] for k in ("sizeLog2",)}
    config = {
        "exportShaderParams": False,
        "exportPath": out.as_posix(),
        "defaultExportPreset": "uzengine",
        "exportList": [{"rootPath": s}],
        "exportParameters": [
            {"parameters": {**parameters, "paddingAlgorithm": "infinite", "dithering": False}}
        ],
    }
    spec = repr(json.dumps(config))

    # 3.1: the dry run.
    dry = wand.probe("uze-plan", PLAN_CODE.replace("__CONFIG__", spec))
    [[_, listed]] = dry["listed"]
    expected = [
        f"{s}_albedo.png",
        f"{s}_albedo.uztexture",
        f"canonical/{s}_albedo.png",
        f"{s}_normal.png",
        f"{s}_normal.uztexture",
        f"{s}_orm.png",
        f"{s}_orm.uztexture",
        f"canonical/{s}_orm.png",
        f"{s}_height.png",
        f"{s}_height.uztexture",
        f"{s}_emissive.uztexture",
        f"{s}.uzmat",
    ]
    assert [Path(p).relative_to(out).as_posix() for p in listed] == expected
    plan = dry["plan"]
    assert {k["fileName"]: k["kind"] for k in plan["skipped"]} == {
        "$textureSet_emissive": "absent",
        "canonical/$textureSet_emissive": "absent",
        "$textureSet_specularweight": "absent",
    }
    files = {f["relativePath"]: f for f in plan["files"]}
    for stem, (fmt, srgb, binding, canonical) in DERIVATIVES.items():
        derivative = files[f"{s}_{stem}.png"]["uztexture"]
        assert (derivative["format"], derivative["srgb"], derivative["binding"]) == (
            fmt,
            srgb,
            binding,
        )
        assert derivative["canonical"] == canonical.format(s=s)
    assert files[f"canonical/{s}_albedo.png"]["layout"] == "RGB"  # no Opacity channel
    [material] = plan["materials"]
    black = material["synthesizedEmissive"]
    assert (black["format"], black["srgb"], black["binding"]) == ("BC7", True, "emissive")
    assert material["emissive"] == f"{s}_emissive.uztexture"

    # The export publishes exactly the listed files.
    exported = wand.probe(
        "uze-export", CLOSING_EXPORT_CODE.replace("__SPEC__", repr(json.dumps({"config": config})))
    )
    assert str(exported["status"]).rsplit(".", 1)[-1] == "Success", exported
    current = json.loads((out / "current.json").read_text(encoding="utf-8"))
    receipt: dict[str, Any] = json.loads((out / current["receipt"]).read_text(encoding="utf-8"))
    generation = (out / current["receipt"]).parent / "files"
    assert [f["path"] for f in receipt["files"]] == expected
    assert "non_conformant" not in receipt
    entries = {f["path"]: f for f in receipt["files"]}
    for path, entry in entries.items():
        assert (generation / path).stat().st_size == entry["bytes"], path
    for stem, (fmt, srgb, binding, canonical) in DERIVATIVES.items():
        meta = entries[f"{s}_{stem}.uztexture"]["uztexture"]
        assert (meta["format"], meta["srgb"], meta["binding"], meta["source"]) == (
            fmt,
            srgb,
            binding,
            canonical.format(s=s),
        )
        assert entries[f"{s}_{stem}.uztexture"]["colour_space"] == ("sRGB" if srgb else "linear")
    assert entries[f"{s}_emissive.uztexture"]["uztexture"]["synthesized"]
    uzmat = entries[f"{s}.uzmat"]["uzmat"]
    assert (uzmat["albedo"], uzmat["normal"], uzmat["orm"], uzmat["emissive"], uzmat["height"]) == (
        f"{s}_albedo.uztexture",
        f"{s}_normal.uztexture",
        f"{s}_orm.uztexture",
        f"{s}_emissive.uztexture",
        f"{s}_height.uztexture",
    )
    assert uzmat["blend"] == "Opaque"  # no Opacity channel: the albedo has no alpha
    graph = json.loads((generation / f"{s}.uzmat").read_text(encoding="utf-8"))
    samples = {
        e["name"]: e["stringParams"]["texturePath"]
        for e in graph["expressions"]
        if e["type"] == "TextureSample"
    }
    assert samples == {
        "Albedo": uzmat["albedo"],
        "Normal": uzmat["normal"],
        "ORM": uzmat["orm"],
        "Emissive": uzmat["emissive"],
    }
    relied: dict[str, set[str]] = {}
    for item in receipt.get("exceptions_relied_on") or []:
        for path in item["paths"]:
            relied.setdefault(Path(str(path)).name, set()).add(str(item["exception_id"]))
    for name, ids in relied.items():
        assert ids <= PRODUCTION_EXCEPTIONS and ("EXC-014" in ids) <= ("normal" in name), (
            name,
            ids,
        )

    # 3.3: the canonical maps against the proven PNG route of the same rebuild.
    pairs = {
        f"canonical/{s}_albedo.png": by_suffix["baseColor"],
        f"canonical/{s}_orm.png": by_suffix["occlusionRoughnessMetallic"],
        f"{s}_height.png": next(p for k, p in by_suffix.items() if k.endswith("_Height")),
    }
    summary: dict[str, Any] = {}
    for canonical, proven in pairs.items():
        ours, theirs = values(generation / canonical), values(proven)
        assert ours.shape == theirs.shape, (canonical, ours.shape, theirs.shape)
        differing = int(np.count_nonzero(np.any(ours != theirs, axis=-1)))
        summary[canonical] = {"texels": int(np.prod(ours.shape[:2])), "differing": differing}
        assert differing == 0, (canonical, differing)
    orm = values(generation / f"canonical/{s}_orm.png")
    for c, suffix in ((1, "_Roughness"), (2, "_Metallic")):
        single = values(next(p for k, p in by_suffix.items() if k.endswith(suffix)))
        assert np.array_equal(orm[..., c], single[..., 0]), suffix
    directx = values(generation / f"{s}_normal.png").astype(np.int64)
    opengl = values(by_suffix["normal"]).astype(np.int64)
    assert directx.shape == opengl.shape
    assert np.array_equal(directx[..., 0], opengl[..., 0])
    assert np.array_equal(directx[..., 2], opengl[..., 2])
    mirrored = directx[..., 1] + opengl[..., 1] - 65535
    summary["normal_green_mirror"] = {"min": int(mirrored.min()), "max": int(mirrored.max())}
    assert int(mirrored.min()) >= -1 and int(mirrored.max()) <= 0
    print("UZE_WAND: " + json.dumps({"generation": current, "files": len(entries), **summary}))
