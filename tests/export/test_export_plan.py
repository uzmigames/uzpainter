"""Tests of phase1.15_export-plan-compiler (P1-EXPORT, `docs/architecture/08-export.md` §1, §2,
§6; `src/export/`; decisions 085 and 086).

The plan cases run `uzp-export-tests.exe plan` on project skeletons and configurations (CPU only,
every lane). The Tier 0 cases read the private oracle store and skip, saying so, on a machine
without it (hosted CI, decision 028); the local run on the owner's machine
(`parity/reports/phase1/export-plan-compiler.md`) is their evidence:

- the dry run of every exporting golden of the current oracle envelope equals the files Painter
  wrote for that configuration (item 3.5, Painter's side);
- the virtual maps marked supported (`Normal_OpenGL`, `Normal_DirectX`), evaluated through the
  plan (`EvaluateFileOn`) and written with the 16-bit write rule, equal their goldens (item 3.6;
  `AO_Mixed` and the converted maps are release gaps, decision 092), and the published
  `parity/semantics/virtual-maps.json` is what that comparison derives. Painter 12.1.5's r1 is
  the exact target where its two recordings differ (decision 032).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from tests.export.conftest import REPO_ROOT

# ── Helpers ──────────────────────────────────────────────────────────────────

PARAMS: dict[str, Any] = {
    "fileFormat": "png",
    "bitDepth": "16",
    "dithering": False,
    "paddingAlgorithm": "infinite",
}
FULL_CHANNELS = {
    "BaseColor": "sRGB8",
    "SpecularRoughness": "L8",
    "BaseMetalness": "L8",
    "Height": "L16F",
    "Normal": "RGB16F",
    "AO": "L16",
    "SpecularWeight": "L8",
    "Opacity": "L8",
}


def chan(dest: str, src: str, kind: str, name: str) -> dict[str, str]:
    return {"destChannel": dest, "srcChannel": src, "srcMapType": kind, "srcMapName": name}


def rgb(kind: str, name: str) -> list[dict[str, str]]:
    return [chan(c, c, kind, name) for c in "RGB"]


def grey(kind: str, name: str) -> list[dict[str, str]]:
    return [chan("L", "L", kind, name)]


def mapping(file_name: str, channels: list[dict[str, str]], **parameters: Any) -> dict[str, Any]:
    m: dict[str, Any] = {"fileName": file_name, "channels": channels}
    if parameters:
        m["parameters"] = parameters
    return m


def config(
    maps: list[dict[str, Any]],
    roots: list[str],
    rules: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    c: dict[str, Any] = {
        "exportShaderParams": False,
        "exportPath": "C:/export",
        "defaultExportPreset": "p",
        "exportPresets": [{"name": "p", "maps": maps}],
        "exportList": [{"rootPath": r} for r in roots],
        "exportParameters": [{"parameters": dict(PARAMS)}] if rules is None else rules,
    }
    c.update(extra)
    return c


def texture_set(
    name: str,
    channels: dict[str, str] | None = None,
    mesh_maps: tuple[str, ...] = (),
    layers: tuple[int, ...] = (),
    resolution: tuple[int, int] = (256, 256),
    stacks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "resolution": list(resolution),
        "mesh_maps": list(mesh_maps),
        "stacks": stacks
        or [{"name": "", "channels": channels or FULL_CHANNELS, "layers": list(layers)}],
    }


def project(*sets: dict[str, Any], **settings: Any) -> dict[str, Any]:
    return {"texture_sets": list(sets), **settings}


TWO_SETS = project(
    texture_set("s0", mesh_maps=("AO",), layers=(500, 501)),
    texture_set("s1", {"BaseColor": "sRGB8", "Height": "L16F", "Normal": "RGB16F"}),
)


def plan_many(
    exe: Path,
    cases: list[tuple[dict[str, Any], Any]],
    tmp: Path,
    project_path: str | None = None,
) -> list[dict[str, Any]]:
    """`uzp-export-tests plan` on every (project skeleton, configuration) case; `project_path` is
    the saved project file's path of every case (absent: never saved)."""
    path = tmp / "cases.json"
    extra = {} if project_path is None else {"project_path": project_path}
    path.write_text(
        json.dumps([{"project": p, "config": c} | extra for p, c in cases]), encoding="utf-8"
    )
    proc = subprocess.run(
        [str(exe), "plan", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


def plan_one(exe: Path, prj: dict[str, Any], cfg: Any, tmp: Path) -> dict[str, Any]:
    return plan_many(exe, [(prj, cfg)], tmp)[0]


def ok(result: dict[str, Any]) -> dict[str, Any]:
    assert "error" not in result, result
    plan: dict[str, Any] = result["plan"]
    return plan


def paths(result: dict[str, Any]) -> list[str]:
    return [f["relativePath"] for f in ok(result)["files"]]


def refused(result: dict[str, Any], kind: str, *fragments: str) -> str:
    assert result.get("error") == kind, result
    message: str = result["message"]
    for fragment in fragments:
        assert fragment in message, message
    return message


# ── 3.1 Naming (EXP-03) ──────────────────────────────────────────────────────


def pipeline_inline_preset(prefix: str, specular: bool) -> dict[str, Any]:
    """The Assets3D inline preset (`staff-v10/painter_export.py`; the hat v8 variant adds
    SpecularWeight), its parameters as the scripts pass them."""

    def doc(name: str, src: str) -> dict[str, Any]:
        letters = "RGB" if name == "BaseColor" else "L"
        return mapping(f"{prefix}_{name}", [chan(c, c, "documentMap", src) for c in letters])

    maps = [
        doc("BaseColor", "basecolor"),
        doc("Roughness", "roughness"),
        doc("Metallic", "metallic"),
        doc("Height", "height"),
    ]
    if specular:
        maps.append(doc("SpecularWeight", "specularweight"))
    maps.append(mapping(f"{prefix}_Normal", rgb("virtualMap", "Normal_OpenGL")))
    return {
        "exportShaderParams": False,
        "exportPath": "E:/delivery/out",
        "defaultExportPreset": "v6",
        "exportPresets": [{"name": "v6", "maps": maps}],
        "exportList": [{"rootPath": "s0"}],
        "exportParameters": [
            {
                "parameters": {
                    "fileFormat": "png",
                    "bitDepth": "16",
                    "sizeLog2": 12,
                    "paddingAlgorithm": "infinite",
                    "dithering": False,
                }
            }
        ],
    }


def test_pipeline_presets_expand(export_tests: Path, tmp_path: Path) -> None:
    """3.1: the Assets3D inline five-map preset and its hat v8 variant expand to the delivered
    names, read the OpenPBR channels through the recorded aliases, and take sizeLog2 12 as 4096."""
    one = project(texture_set("s0"))
    five, six = plan_many(
        export_tests,
        [
            (one, pipeline_inline_preset("09-Cajado", False)),
            (one, pipeline_inline_preset("10-Chapeu", True)),
        ],
        tmp_path,
    )
    assert paths(five) == [
        "09-Cajado_BaseColor.png",
        "09-Cajado_Roughness.png",
        "09-Cajado_Metallic.png",
        "09-Cajado_Height.png",
        "09-Cajado_Normal.png",
    ]
    assert five["list"] == [["s0", "", [f"E:/delivery/out/{p}" for p in paths(five)]]]
    assert paths(six)[4] == "10-Chapeu_SpecularWeight.png"
    files = ok(five)["files"]
    assert files[1]["channels"][0]["source"]["channel"] == "SpecularRoughness"
    assert files[2]["channels"][0]["source"]["channel"] == "BaseMetalness"
    assert files[4]["channels"][0]["source"]["normal"] == "combined"
    assert {(f["width"], f["height"], f["layout"]) for f in files[:1]} == {(4096, 4096, "RGB")}
    assert files[1]["layout"] == "L"


def test_recorder_and_shipped_patterns_expand(export_tests: Path, tmp_path: Path) -> None:
    """3.1: `$textureSet_<name>` (the recorder's pattern), the optional groups of Adobe's preset
    patterns (empty `$colorSpace` under legacy colour management and empty `$udim` in the
    Default workflow drop their group) and `/` sub-folders, over two texture sets."""
    cfg = config(
        [
            mapping("$textureSet_BaseColor(_$colorSpace)(.$udim)", rgb("documentMap", "basecolor")),
            mapping("$textureSet_Height", grey("documentMap", "height")),
            mapping("maps/$textureSet/Normal", rgb("virtualMap", "Normal_DirectX")),
        ],
        ["s0", "s1"],
    )
    result = plan_one(export_tests, TWO_SETS, cfg, tmp_path)
    assert paths(result) == [
        "s0_BaseColor.png",
        "s0_Height.png",
        "maps/s0/Normal.png",
        "s1_BaseColor.png",
        "s1_Height.png",
        "maps/s1/Normal.png",
    ]
    assert result["list"][1][0] == "s1"
    assert ok(result)["files"][0]["path"] == "C:/export/s0_BaseColor.png"


def test_collisions_and_invalid_names_are_refused(export_tests: Path, tmp_path: Path) -> None:
    """3.1: two outputs of one exportList entry resolving to one path are written `name` and
    `name_1` (probe P9); two entries resolving to one path, a third equal path and paths equal
    only ignoring case are refused naming both; malformed and unrecorded names are refused before
    anything is written (decision 091)."""
    base = rgb("documentMap", "basecolor")
    h = grey("documentMap", "height")
    cases = [
        (TWO_SETS, config([mapping("Delivery_BaseColor", base)], ["s0", "s1"])),
        (TWO_SETS, config([mapping("$textureSet_A", base), mapping("$textureSet_a", h)], ["s0"])),
        (TWO_SETS, config([mapping("../$textureSet", base)], ["s0"])),
        (TWO_SETS, config([mapping("$textureSet:x", base)], ["s0"])),
        (TWO_SETS, config([mapping("$textureset_x", base)], ["s0"])),
        (TWO_SETS, config([mapping("$textureSet_c", base), mapping("$textureSet_c", h)], ["s0"])),
        (
            TWO_SETS,
            config([mapping("$textureSet_c", base), mapping("$textureSet_c", h)] * 2, ["s0"]),
        ),
        (TWO_SETS, config([mapping("$textureSet_c", base), mapping("$textureSet_c_1", h)], ["s0"])),
        (
            TWO_SETS,
            config([mapping("$textureSet_c", base)], ["s0"])
            | {"exportList": [{"rootPath": "s0"}, {"rootPath": "s0"}]},
        ),
        (TWO_SETS, config([mapping("con", base)], ["s0"])),
    ]
    r = plan_many(export_tests, cases, tmp_path)
    refused(r[0], "NotYetSupported", "s1", "s0", "Delivery_BaseColor.png", "collision")
    refused(r[1], "NotYetSupported", "s0_a.png", "collision")
    refused(r[2], "ValueError", "inside exportPath")
    refused(r[3], "ValueError", "Windows forbids")
    refused(r[4], "ValueError", 'unknown wildcard "$textureset"', "valid: $textureSet")
    assert paths(r[5]) == ["s0_c.png", "s0_c_1.png"]
    assert [f["map"] for f in ok(r[5])["files"]] == [0, 1]
    refused(r[6], "NotYetSupported", "third map", "R-091")
    assert paths(r[7]) == ["s0_c.png", "s0_c_1.png"]
    refused(r[8], "NotYetSupported", "s0_c.png", "collision")
    refused(r[9], "ValueError", "reserved")


def test_wildcards_and_groups(export_tests: Path, tmp_path: Path) -> None:
    """3.1: the wildcards and groups probes P1-P3 recorded (decision 091): `$mesh` is the mesh
    file's name without its extension, `$project` the project file's (`Untitled` while never
    saved), `$sceneMaterial` the set's material; an empty wildcard outside a group expands to
    nothing; parentheses without a wildcard, around a group or unclosed are literal. A file name
    with two dots, a renamed set's `$sceneMaterial`, a `)` after no literal `(` and a group with
    both empty and non-empty wildcards are not recorded."""
    base = rgb("documentMap", "basecolor")
    meshed = TWO_SETS | {"mesh": "grid2x2.obj"}
    renamed = project(texture_set("s0") | {"original_name": "mat0"}) | {"mesh": "grid2x2.obj"}

    def case(pattern: str, prj: dict[str, Any] = meshed) -> tuple[dict[str, Any], Any]:
        return prj, config([mapping(pattern, base)], ["s0"])

    cases = [
        case("$mesh_$textureSet_a"),
        case("$project_$textureSet_b"),
        case("$textureSet_$sceneMaterial_c"),
        case("$textureSet_$udim_d"),
        case("$textureSet_$colorSpace_e"),
        case("$textureSet(_v2)"),
        case("$textureSet((_$udim))"),
        case("$textureSet(_$udim"),
        case("($textureSet)x(_$textureSet)"),
        case("$mesh", meshed | {"mesh": "grid.v2.obj"}),
        case("$sceneMaterial", renamed),
        case("$mesh", TWO_SETS),
        case("$textureSet)x"),
        case("$textureSet(_$textureSet$udim)"),
    ]
    r = plan_many(export_tests, cases, tmp_path)
    assert [paths(x)[0] for x in r[:9]] == [
        "grid2x2_s0_a.png",
        "Untitled_s0_b.png",
        "s0_s0_c.png",
        "s0__d.png",
        "s0__e.png",
        "s0(_v2).png",
        "s0().png",
        "s0(_.png",
        "s0x_s0.png",
    ]
    refused(r[9], "NotYetSupported", "grid.v2.obj", "more than one dot")
    refused(r[10], "NotYetSupported", "$sceneMaterial", "mat0")
    refused(r[11], "ValueError", "$mesh", "has none")
    refused(r[12], "NotYetSupported", '")" after no literal "("')
    refused(r[13], "NotYetSupported", "both an empty and a non-empty wildcard")
    saved = plan_many(export_tests, [case("$project_x")], tmp_path, "D:/work/golden.spp")
    assert paths(saved[0]) == ["golden_x.png"]


# ── 3.2 Filters ──────────────────────────────────────────────────────────────


def test_filters(export_tests: Path, tmp_path: Path) -> None:
    """3.2: `{}` and an absent filter select all, `{"dataPaths": []}` selects nothing,
    `outputMaps` compares the unexpanded fileName, members combine with AND, `dataPaths`
    matches a texture set (all its stacks) or `set/stack`, and `uvTiles` selects a set of the
    Default workflow when it lists [0, 0] (probe P4, decision 091). A selection without any file
    is an export writing nothing (probe P8)."""
    maps = [
        mapping("$textureSet_BaseColor", rgb("documentMap", "basecolor")),
        mapping("$textureSet_Height", grey("documentMap", "height")),
    ]
    sixteen = {"parameters": dict(PARAMS)}
    eight = {"bitDepth": "8"}

    def per_stack(rules: list[dict[str, Any]]) -> dict[str, Any]:
        """One preset per stack of `body`, each naming its stack in its file names."""
        stacks = ("skin", "cloth")
        c = config(maps, [], rules)
        c["defaultExportPreset"] = stacks[0]
        c["exportPresets"] = [
            {
                "name": st,
                "maps": [
                    mapping(f"$textureSet_{st}_BaseColor", rgb("documentMap", "basecolor")),
                    mapping(f"$textureSet_{st}_Height", grey("documentMap", "height")),
                ],
            }
            for st in stacks
        ]
        c["exportList"] = [{"rootPath": f"body/{st}", "exportPreset": st} for st in stacks]
        return c

    layered = project(
        texture_set(
            "body",
            stacks=[
                {"name": "skin", "channels": FULL_CHANNELS},
                {"name": "cloth", "channels": FULL_CHANNELS},
            ],
        )
    )
    cases = [
        (TWO_SETS, config(maps, ["s0", "s1"], [{"filter": {}, "parameters": dict(PARAMS)}])),
        (
            TWO_SETS,
            config(maps, ["s0"], [{"filter": {"dataPaths": []}, "parameters": dict(PARAMS)}]),
        ),
        (
            TWO_SETS,
            config(
                maps,
                ["s0", "s1"],
                [
                    sixteen,
                    {
                        "filter": {"dataPaths": ["s1"], "outputMaps": ["$textureSet_Height"]},
                        "parameters": eight,
                    },
                ],
            ),
        ),
        (
            TWO_SETS,
            config(maps, ["s0"])
            | {
                "exportList": [{"rootPath": "s0", "filter": {"outputMaps": ["$textureSet_Height"]}}]
            },
        ),
        (
            TWO_SETS,
            config(maps, ["s0"])
            | {"exportList": [{"rootPath": "s0", "filter": {"outputMaps": []}}]},
        ),
        (
            layered,
            per_stack([sixteen, {"filter": {"dataPaths": ["body/cloth"]}, "parameters": eight}]),
        ),
        (
            layered,
            config(
                maps,
                ["body/skin"],
                [sixteen, {"filter": {"dataPaths": ["body"]}, "parameters": eight}],
            ),
        ),
        (
            TWO_SETS,
            config(maps, ["s0"])
            | {"exportList": [{"rootPath": "s0", "filter": {"uvTiles": [[0, 0]]}}]},
        ),
        (
            TWO_SETS,
            config(maps, ["s0"], [sixteen, {"filter": {"uvTiles": [[0, 0]]}, "parameters": eight}]),
        ),
        (
            TWO_SETS,
            config(
                maps,
                ["s0"],
                [
                    sixteen,
                    {"filter": {"dataPaths": ["s1"], "uvTiles": [[0, 0]]}, "parameters": eight},
                ],
            ),
        ),
        (layered, config(maps, ["body"])),
        (layered, config(maps, ["body/skin", "body/cloth"])),
        (
            TWO_SETS,
            config(maps, ["s0", "s1"])
            | {
                "exportList": [
                    {"rootPath": "s0", "filter": {"uvTiles": [[1, 0]]}},
                    {"rootPath": "s1"},
                ]
            },
        ),
    ]
    r = plan_many(export_tests, cases, tmp_path)
    assert len(paths(r[0])) == 4
    refused(r[1], "ValueError", "fileFormat is undefined")
    depths = {f["relativePath"]: f["parameters"]["bitDepth"] for f in ok(r[2])["files"]}
    assert depths == {
        "s0_BaseColor.png": "16",
        "s0_Height.png": "16",
        "s1_BaseColor.png": "16",
        "s1_Height.png": "8",
    }
    assert paths(r[3]) == ["s0_Height.png"]
    assert paths(r[4]) == [] and r[4]["list"] == []
    by_stack = {
        (f["stack"], f["relativePath"]): f["parameters"]["bitDepth"] for f in ok(r[5])["files"]
    }
    assert by_stack[("skin", "body_skin_BaseColor.png")] == "16"
    assert by_stack[("cloth", "body_cloth_BaseColor.png")] == "8"
    assert by_stack[("cloth", "body_cloth_Height.png")] == "8"
    assert {f["parameters"]["bitDepth"] for f in ok(r[6])["files"]} == {"8"}
    assert paths(r[7]) == ["s0_BaseColor.png", "s0_Height.png"]
    assert {f["parameters"]["bitDepth"] for f in ok(r[8])["files"]} == {"8"}
    assert {f["parameters"]["bitDepth"] for f in ok(r[9])["files"]} == {"16"}
    refused(r[10], "ValueError", 'no texture set or stack "body"', "body/skin")
    # $textureSet is the texture set's name in every stack (export.html): one preset over two
    # stacks of a set collides.
    refused(r[11], "NotYetSupported", "body/cloth", "body/skin", "body_BaseColor.png", "collision")
    assert paths(r[12]) == ["s1_BaseColor.png", "s1_Height.png"]
    assert [entry[0] for entry in r[12]["list"]] == ["s1"]


# ── 3.3 Resolution order ─────────────────────────────────────────────────────


def test_resolution_order(export_tests: Path, tmp_path: Path) -> None:
    """3.3: preset map parameters, then every matching exportParameters rule in list order; a
    parameter undefined after that makes the configuration invalid, naming the map and the
    parameter; dilationDistance is required only by the padding algorithms that need it."""
    base = rgb("documentMap", "basecolor")
    cases = [
        (
            TWO_SETS,
            config(
                [mapping("$textureSet_a", base, bitDepth="8", sizeLog2=10)],
                ["s0", "s1"],
                [
                    {
                        "parameters": {
                            "fileFormat": "png",
                            "dithering": True,
                            "paddingAlgorithm": "infinite",
                        }
                    },
                    {
                        "filter": {"dataPaths": ["s1"]},
                        "parameters": {"bitDepth": "16", "sizeLog2": [9, 11]},
                    },
                    {"filter": {"dataPaths": ["s1"]}, "parameters": {"dithering": False}},
                ],
            ),
        ),
        (TWO_SETS, config([mapping("$textureSet_a", base, **PARAMS)], ["s0"], [])),
        (
            TWO_SETS,
            config(
                [mapping("$textureSet_a", base)],
                ["s0"],
                [
                    {
                        "parameters": {
                            "fileFormat": "png",
                            "dithering": False,
                            "paddingAlgorithm": "infinite",
                        }
                    }
                ],
            ),
        ),
        (
            TWO_SETS,
            config(
                [mapping("$textureSet_a", base)],
                ["s0"],
                [{"parameters": PARAMS | {"paddingAlgorithm": "diffusion"}}],
            ),
        ),
        (
            TWO_SETS,
            config(
                [mapping("$textureSet_a", base)],
                ["s0"],
                [
                    {
                        "parameters": PARAMS
                        | {"paddingAlgorithm": "diffusion", "dilationDistance": 16}
                    }
                ],
            ),
        ),
        (
            TWO_SETS,
            config(
                [mapping("$textureSet_a", base)],
                ["s0"],
                [{"parameters": PARAMS | {"bitDepth": "16f"}}],
            ),
        ),
        (
            TWO_SETS,
            config(
                [mapping("$textureSet_a", base)],
                ["s0"],
                [{"parameters": PARAMS | {"fileFormat": "exr", "bitDepth": "32f"}}],
            ),
        ),
        (
            TWO_SETS,
            config(
                [mapping("$textureSet_a", base)],
                ["s0"],
                [{"parameters": PARAMS | {"bitDepth": 16}}],
            ),
        ),
        (
            TWO_SETS,
            config(
                [mapping("$textureSet_a", base)],
                ["s0"],
                [{"parameters": PARAMS | {"sizeLog2": 14}}],
            ),
        ),
    ]
    r = plan_many(export_tests, cases, tmp_path)
    files = {f["textureSet"]: f for f in ok(r[0])["files"]}
    assert files["s0"]["parameters"] == {
        "bitDepth": "8",
        "dithering": True,
        "fileFormat": "png",
        "paddingAlgorithm": "infinite",
        "sizeLog2": 10,
    }
    assert (files["s0"]["width"], files["s0"]["height"]) == (1024, 1024)
    assert files["s1"]["parameters"]["bitDepth"] == "16"
    assert files["s1"]["parameters"]["dithering"] is False
    assert (files["s1"]["width"], files["s1"]["height"]) == (512, 2048)
    assert paths(r[1]) == ["s0_a.png"]
    refused(r[2], "ValueError", 's0: preset "p" map 0 ("$textureSet_a")', "bitDepth is undefined")
    refused(r[3], "ValueError", "dilationDistance is undefined")
    assert ok(r[4])["files"][0]["parameters"]["dilationDistance"] == 16
    refused(r[5], "ValueError", "16f is not supported by the format png", "valid: 8, 16")
    assert paths(r[6]) == ["s0_a.exr"]
    refused(r[7], "ValueError", "bitDepth", "Expected a string value")
    refused(r[8], "NotYetSupported", "sizeLog2 14")


# ── 3.4 Unknown identifiers and refused formats ──────────────────────────────


def test_mixed_ao_is_rejected_with_ao_mixed(export_tests: Path, tmp_path: Path) -> None:
    """3.4: the pipeline's `Mixed_AO` (which crashed Painter) is rejected and the alternatives
    start with the documented `AO_Mixed`; nothing is written."""
    out = tmp_path / "out"
    cfg = config([mapping("$textureSet_AO", grey("virtualMap", "Mixed_AO"))], ["s0"])
    cfg["exportPath"] = out.as_posix()
    message = refused(
        plan_one(export_tests, TWO_SETS, cfg, tmp_path),
        "ValueError",
        'unknown virtualMap "Mixed_AO"',
    )
    assert message.split("valid: ")[1].startswith("AO_Mixed, ")
    assert not out.exists()


def test_refused_formats_raise_before_any_file(export_tests: Path, tmp_path: Path) -> None:
    """3.4: TIFF (not in v1) and TGA (a later package) raise NotYetSupported naming the owner,
    before any file exists; an unknown format is a ValueError with the alternatives."""
    out = tmp_path / "out"
    cases = []
    for fmt in ("tiff", "tif", "tga", "jpeg", "dds", "psd", "webp", "sbsar", "pngx"):
        cfg = config([mapping("$textureSet_a", rgb("documentMap", "basecolor"))], ["s0"])
        cfg["exportParameters"] = [{"parameters": PARAMS | {"fileFormat": fmt}}]
        cfg["exportPath"] = out.as_posix()
        cases.append((TWO_SETS, cfg))
    r = plan_many(export_tests, cases, tmp_path)
    refused(r[0], "NotYetSupported", '"tiff"', "not in v1")
    refused(r[1], "NotYetSupported", '"tif"', "not in v1")
    refused(r[2], "NotYetSupported", '"tga"', "phase3.2_unreal-ue56-packed-preset")
    refused(r[3], "NotYetSupported", '"jpeg"', "phase3.2")
    refused(r[4], "NotYetSupported", '"dds"', "phase3.2")
    for i in (5, 6, 7):
        refused(r[i], "NotYetSupported", "not in v1")
    refused(r[8], "ValueError", 'unknown file format "pngx"', "valid: png")
    assert not out.exists()


def test_identifiers_are_checked(export_tests: Path, tmp_path: Path) -> None:
    """3.4 (decisions 085, 091): srcMapType, channel letters, destination sets, presets and keys
    are checked with their alternatives; documentMap spellings follow the documented and recorded
    ones; shader parameters are a release gap, and a shelf preset UzPainter ships whose layout no
    recording confirms is refused (decision 095). Undocumented keys at the root and in a preset map
    are ignored as Painter ignores them (probe P10); elsewhere they are not recorded. A legacy name whose pairing the stack lacks makes the dry run raise (probe P13)."""
    base = rgb("documentMap", "basecolor")

    def with_map(channels: list[dict[str, str]]) -> dict[str, Any]:
        return config([mapping("$textureSet_x", channels)], ["s0"])

    bad_preset = config([mapping("x", base)], ["s0"])
    bad_preset["exportList"] = [{"rootPath": "s0", "exportPreset": "q"}]
    twice = config([mapping("x", base)], ["s0"])
    twice["exportPresets"].append({"name": "p", "maps": []})
    no_preset = config([mapping("x", base)], ["s0"])
    del no_preset["defaultExportPreset"]
    cases = [
        (TWO_SETS, with_map([chan("R", "R", "documentmap", "basecolor")])),
        (TWO_SETS, with_map([chan("X", "R", "documentMap", "basecolor")])),
        (TWO_SETS, with_map(base[:2])),
        (TWO_SETS, with_map([*base, chan("L", "L", "documentMap", "height")])),
        (TWO_SETS, with_map([*base, chan("R", "R", "documentMap", "height")])),
        (TWO_SETS, with_map([chan(c, c, "documentMap", "baseColor") for c in "RGB"])),
        (TWO_SETS, with_map([chan(c, c, "documentMap", "BaseColor") for c in "RGB"])),
        (TWO_SETS, with_map(grey("documentMap", "ao"))),
        (TWO_SETS, with_map(grey("documentMap", "ambientOcclusion"))),
        (TWO_SETS, with_map(grey("documentMap", "sheencolor"))),
        (TWO_SETS, with_map(grey("meshMap", "Normal_Base"))),
        (TWO_SETS, with_map(grey("defaultMap", "grey"))),
        (TWO_SETS, bad_preset),
        (TWO_SETS, twice),
        (TWO_SETS, no_preset),
        (
            TWO_SETS,
            with_map(base)
            | {"defaultExportPreset": "resource://starter_assets/PBR Metallic Roughness"},
        ),
        (TWO_SETS, with_map(base) | {"exportShaderParams": True}),
        (TWO_SETS, with_map(base) | {"exportPathh": "C:/x"}),
        (
            TWO_SETS,
            config([mapping("$textureSet_x", base) | {"comment": "x"}], ["s0"]),
        ),
        (
            TWO_SETS,
            with_map([chan(c, c, "documentMap", "basecolor") | {"note": ""} for c in "RGB"]),
        ),
        (
            TWO_SETS,
            with_map([chan(c, c, "documentMap", "basecolor") | {"srcPath": ""} for c in "RGB"]),
        ),
        (
            TWO_SETS,
            with_map([chan(c, c, "documentMap", "basecolor") | {"srcPath": "x"} for c in "RGB"]),
        ),
        (TWO_SETS, "{not json"),
        (TWO_SETS, with_map(base) | {"exportList": [{"rootPath": "s9"}]}),
    ]
    r = plan_many(export_tests, cases, tmp_path)
    refused(r[0], "ValueError", 'unknown srcMapType "documentmap"', "valid: documentMap")
    refused(r[1], "ValueError", 'unknown channel "X"')
    refused(r[2], "ValueError", "L, L+A, R+G+B or R+G+B+A")
    refused(r[3], "ValueError", "L, L+A, R+G+B or R+G+B+A")
    refused(r[4], "ValueError", "written twice")
    assert paths(r[5]) == ["s0_x.png"]
    refused(r[6], "NotYetSupported", '"BaseColor" is not recorded', "basecolor, baseColor")
    refused(r[7], "ValueError", 'unknown documentMap "ao"', "ambientOcclusion")
    assert ok(r[8])["files"][0]["channels"][0]["source"]["channel"] == "AO"
    assert ok(r[9])["skipped"][0]["kind"] == "export_error"
    assert "SheenColor" in r[9]["list_error"] and "FuzzColor" in r[9]["list_error"]
    refused(r[10], "ValueError", 'unknown meshMap "Normal_Base"', "valid: normal_base")
    refused(r[11], "ValueError", 'unknown defaultMap "grey"', "black, white")
    refused(r[12], "ValueError", 'unknown export preset "q"', "valid: p")
    refused(r[13], "ValueError", "defined twice")
    refused(r[14], "ValueError", "no exportPreset and no defaultExportPreset")
    refused(r[15], "NotYetSupported", '"pbr-metallic-roughness"', "R-095")
    refused(r[16], "NotYetSupported", "exportShaderParams")
    assert paths(r[17]) == ["s0_x.png"]
    assert paths(r[18]) == ["s0_x.png"]
    refused(r[19], "NotYetSupported", '"note" is not documented', "R-091")
    assert paths(r[20]) == ["s0_x.png"]
    refused(r[21], "ValueError", "srcPath")
    refused(r[22], "ValueError", "not JSON")
    refused(r[23], "ValueError", 'no texture set or stack "s9"', "valid: s0")


# ── Presence, sources and channels (decision 085) ────────────────────────────


def test_presence_and_sources(export_tests: Path, tmp_path: Path) -> None:
    """Maps whose documentMap is absent, and white-only maps, are skipped and listed (Painter
    writes neither); black-only maps are skipped as listed by Painter but not written (probe P8);
    an absent alpha drops to an RGB file (P7); an unbound mesh map is an export error the dry run
    raises (P12); srcChannel L of a colour is its luma (P5); unrecorded presence cases, release-gap
    virtual maps and mesh maps are refused; supported virtual and mesh maps resolve with their
    EXP-09 role (decisions 085, 091)."""
    base = rgb("documentMap", "basecolor")
    cases = [
        (
            TWO_SETS,
            config(
                [
                    mapping("$textureSet_r", grey("documentMap", "roughness")),
                    mapping("$textureSet_b", base),
                ],
                ["s0", "s1"],
            ),
        ),
        (
            TWO_SETS,
            config(
                [
                    mapping("$textureSet_w", grey("defaultMap", "white")),
                    mapping("$textureSet_b", base),
                ],
                ["s0"],
            ),
        ),
        (TWO_SETS, config([mapping("$textureSet_k", grey("defaultMap", "black"))], ["s0"])),
        (
            TWO_SETS,
            config(
                [mapping("$textureSet_m", [*base, chan("A", "L", "documentMap", "roughness")])],
                ["s1"],
            ),
        ),
        (
            TWO_SETS,
            config(
                [mapping("$textureSet_m", [*base, chan("A", "L", "defaultMap", "white")])], ["s1"]
            ),
        ),
        (TWO_SETS, config([mapping("$textureSet_ao", grey("virtualMap", "AO_Mixed"))], ["s0"])),
        (TWO_SETS, config([mapping("$textureSet_ao", grey("virtualMap", "AO_Mixed"))], ["s1"])),
        (TWO_SETS, config([mapping("$textureSet_d", rgb("virtualMap", "Diffuse"))], ["s0"])),
        (TWO_SETS, config([mapping("$textureSet_g", grey("virtualMap", "Glossiness"))], ["s0"])),
        (
            project(texture_set("s0", mesh_maps=("Normal",))),
            config([mapping("$textureSet_n", rgb("meshMap", "normal_base"))], ["s0"]),
        ),
        (TWO_SETS, config([mapping("$textureSet_n", rgb("meshMap", "normal_base"))], ["s0"])),
        (
            project(texture_set("s0", mesh_maps=("Curvature",))),
            config([mapping("$textureSet_c", grey("meshMap", "curvature"))], ["s0"]),
        ),
        (
            TWO_SETS,
            config(
                [mapping("$textureSet_l", [chan("L", "L", "documentMap", "basecolor")])], ["s0"]
            ),
        ),
        (
            TWO_SETS,
            config(
                [mapping("$textureSet_r", [chan("L", "R", "documentMap", "basecolor")])], ["s0"]
            ),
        ),
        (
            TWO_SETS,
            config(
                [mapping("$textureSet_a", [*base, chan("A", "A", "documentMap", "opacity")])],
                ["s0"],
            ),
        ),
        (
            TWO_SETS,
            config(
                [mapping("$textureSet_h", [chan(c, "L", "documentMap", "height") for c in "RGB"])],
                ["s0"],
            ),
        ),
        (
            project(texture_set("s0", resolution=(512, 512))),
            config([mapping("$textureSet_n", rgb("virtualMap", "Normal_OpenGL"))], ["s0"]),
        ),
        (
            project(texture_set("s0", {"BaseColor": "sRGB8", "Normal": "RGB16F"})),
            config([mapping("$textureSet_n", rgb("virtualMap", "Normal_OpenGL"))], ["s0"]),
        ),
        (
            project(texture_set("s0", mesh_maps=("Normal",))),
            config([mapping("$textureSet_n", rgb("virtualMap", "Normal_OpenGL"))], ["s0"]),
        ),
        (
            project(texture_set("s0"), color_management="ocio"),
            config([mapping("$textureSet_b", base)], ["s0"]),
        ),
        (
            project(texture_set("s0"), workflow="UVTile"),
            config([mapping("$textureSet_b", base)], ["s0"]),
        ),
        (TWO_SETS, config([mapping("$textureSet_r", grey("documentMap", "roughness"))], ["s1"])),
        (
            project(texture_set("s0", mesh_maps=("Normal",))),
            config(
                [
                    mapping("$textureSet_b", base),
                    mapping("$textureSet_c", grey("meshMap", "curvature")),
                ],
                ["s0"],
            ),
        ),
        (
            TWO_SETS,
            config(
                [
                    mapping(
                        "$textureSet_m",
                        [
                            chan("L", "L", "defaultMap", "black"),
                            chan("A", "L", "defaultMap", "white"),
                        ],
                    )
                ],
                ["s0"],
            ),
        ),
    ]
    r = plan_many(export_tests, cases, tmp_path)
    assert paths(r[0]) == ["s0_r.png", "s0_b.png", "s1_b.png"]
    assert ok(r[0])["skipped"] == [
        {
            "fileName": "$textureSet_r",
            "map": 0,
            "preset": "p",
            "reason": "the stack has no Roughness channel",
            "kind": "absent",
            "rootPath": "s1",
            "stack": "",
            "textureSet": "s1",
        }
    ]
    assert paths(r[1]) == ["s0_b.png"]
    assert ok(r[1])["skipped"][0]["reason"] == "every channel reads defaultMap white"
    assert paths(r[2]) == [] and r[2]["list"] == []
    assert ok(r[2])["skipped"][0]["kind"] == "not_written"
    rgb_only = ok(r[3])["files"][0]
    assert rgb_only["layout"] == "RGB" and len(rgb_only["channels"]) == 3
    files = ok(r[4])["files"]
    assert files[0]["layout"] == "RGBA"
    assert files[0]["channels"][3]["source"]["constant"] == 1.0
    refused(r[5], "NotYetSupported", '"AO_Mixed"', "not identified", "R-092")
    refused(r[6], "NotYetSupported", '"AO_Mixed"', "R-092")
    refused(r[7], "NotYetSupported", '"Diffuse"', "coverage", "R-092")
    refused(r[8], "NotYetSupported", '"Glossiness"', "coverage", "R-092")
    normal = ok(r[9])["files"][0]["channels"][0]["source"]
    assert normal["meshMap"] == "Normal" and normal["normal"] == "geometry_only"
    assert ok(r[10])["skipped"][0]["kind"] == "export_error"
    assert "not bound" in r[10]["list_error"] and "P12" in r[10]["list_error"]
    refused(r[11], "NotYetSupported", "R-090")
    assert ok(r[12])["files"][0]["channels"][0]["luma"] is True
    assert ok(r[13])["files"][0]["channels"][0]["component"] == 0
    refused(r[14], "NotYetSupported", "srcChannel A")
    assert ok(r[15])["files"][0]["layout"] == "RGB"
    # The combination's own limits (set size, a bound Normal mesh map) need decoded inputs: the
    # evaluator refuses what it does not reproduce when the export evaluates (decision 085).
    assert ok(r[16])["files"][0]["width"] == 512
    refused(r[17], "NotYetSupported", "without both a Height and a Normal channel")
    assert ok(r[18])["files"][0]["channels"][0]["source"]["normal"] == "combined"
    refused(r[19], "NotYetSupported", '"ocio"')
    refused(r[20], "NotYetSupported", "UVTile workflow")
    assert paths(r[21]) == [] and ok(r[21])["skipped"][0]["kind"] == "absent"
    refused(r[22], "NotYetSupported", "also writes other files")
    refused(r[23], "NotYetSupported", "black and white")


def test_diagnostic_sources(export_tests: Path, tmp_path: Path) -> None:
    """2.6 (EXP-04, decision 076): diagnosticMap sources resolve in the stacks holding their node
    and are absent (skipped) elsewhere; a node in no exported stack, a malformed name and a
    statistics source in an image slot are invalid; regionStats is a JSON statistics file."""
    cases = [
        (
            TWO_SETS,
            config(
                [
                    mapping("$textureSet_mask", grey("diagnosticMap", "materialMask/500")),
                    mapping("$textureSet_iso", rgb("diagnosticMap", "isolated/BaseColor/501")),
                    mapping("$textureSet_view", rgb("diagnosticMap", "materialView/Normal/500")),
                    mapping("$textureSet_stats", grey("diagnosticMap", "regionStats/Height/500")),
                ],
                ["s0", "s1"],
            ),
        ),
        (TWO_SETS, config([mapping("x", grey("diagnosticMap", "materialMask/999"))], ["s0"])),
        (TWO_SETS, config([mapping("x", grey("diagnosticMap", "materialMask/x"))], ["s0"])),
        (
            TWO_SETS,
            config([mapping("x", rgb("diagnosticMap", "regionStats/BaseColor/500"))], ["s0"]),
        ),
        (TWO_SETS, config([mapping("x", rgb("diagnosticMap", "isolated/Emissive/500"))], ["s0"])),
        (TWO_SETS, config([mapping("x", rgb("diagnosticMap", "materialView/ID/500"))], ["s0"])),
    ]
    r = plan_many(export_tests, cases, tmp_path)
    plan = ok(r[0])
    assert [f["relativePath"] for f in plan["files"]] == [
        "s0_mask.png",
        "s0_iso.png",
        "s0_view.png",
        "s0_stats.json",
    ]
    assert plan["files"][3]["layout"] == "statistics" and plan["files"][3]["parameters"] is None
    assert plan["files"][1]["channels"][0]["source"]["diagnostic"] == "isolated/BaseColor/501"
    assert {s["textureSet"] for s in plan["skipped"]} == {"s1"}
    assert {s["reason"] for s in plan["skipped"]} == {
        "node 500 is not in the stack",
        "node 501 is not in the stack",
    }
    refused(r[1], "ValueError", "materialMask/999", "none of the exported stacks")
    refused(r[2], "ValueError", "malformed diagnosticMap", "decision 076")
    refused(r[3], "ValueError", "statistics file")
    refused(r[4], "ValueError", "no Emissive channel")
    refused(r[5], "ValueError", "no ID mesh map")


def test_plan_hash_is_stable_and_sensitive(export_tests: Path, tmp_path: Path) -> None:
    """2.3: the plan hash is the SHA-256 of the canonical plan; the same project and configuration
    give the same plan and hash, and a parameter change changes the hash."""
    cfg = pipeline_inline_preset("09-Cajado", False)
    one = project(texture_set("s0"))
    other = json.loads(json.dumps(cfg))
    other["exportParameters"][0]["parameters"]["sizeLog2"] = 11
    a, b, c = plan_many(export_tests, [(one, cfg), (one, cfg), (one, other)], tmp_path)
    assert ok(a) == ok(b)
    assert len(ok(a)["hash"]) == 64
    assert ok(a)["hash"] != ok(c)["hash"]


# ── 3.5 Dry run = the files Painter wrote (Tier 0, owner's machine) ──────────


def tier0_export_goldens() -> list[Path]:
    from tools.parity.envelope.registry import current_envelope, manifest_root

    root = manifest_root(current_envelope())
    out = []
    for path in sorted(root.rglob("*.json")):
        steps = (
            json.loads(path.read_text(encoding="utf-8"))
            .get("instruction_sequence", {})
            .get("steps", [])
        )
        if any(s["call"].endswith("export_project_textures") for s in steps):
            out.append(path)
    return out


def skeleton_of(manifest: dict[str, Any], template: dict[str, Any]) -> dict[str, Any]:
    """The project skeleton of a recording: its texture sets, stacks and channels as Painter
    reported them, the mesh maps the sequence bound, and the project's normal convention."""
    steps = manifest["instruction_sequence"]["steps"]
    bound: dict[str, set[str]] = {}
    convention = "OpenGL"
    for step in steps:
        call, args = step["call"], step["args"]
        if call.endswith("project.create"):
            convention = str(args.get("normal_map_format", "OpenGL"))
        if call.endswith("set_mesh_map_resource"):
            targets = (
                [args["texture_set"]] if "texture_set" in args else list(template["texture_sets"])
            )
            for t in targets:
                bound.setdefault(t, set()).add(str(args["usage"]))
        if call.endswith("bake_async"):
            enabled = [
                s["args"].get("usages", [])
                for s in steps
                if s["call"].endswith("set_enabled_bakers")
            ]
            for t in template["texture_sets"]:
                for usages in enabled:
                    bound.setdefault(t, set()).update(str(u) for u in usages)
    sets = []
    for name, info in sorted(template["texture_sets"].items()):
        resolution = info.get("resolution", [256, 256])
        stacks = [
            {"name": stack, "channels": {c: v["format"] for c, v in channels.items()}}
            for stack, channels in sorted(info["stacks"].items())
        ]
        sets.append(
            {
                "name": name,
                "resolution": list(resolution),
                "mesh_maps": sorted(bound.get(name, set())),
                "stacks": stacks,
            }
        )
    return {"texture_sets": sets, "normal_map_format": convention}


def test_dry_run_equals_painter_export(export_tests: Path, tmp_path: Path) -> None:
    """3.5: for every exporting Tier 0 golden of the current envelope, the dry run of the
    recorder's documented configuration (tools/parity/recorder/job.py) on the recording's texture
    sets lists exactly the files Painter wrote, and the maps it skips are exactly the requested
    maps Painter did not write. A golden that uses a release gap of the plan (a baked mesh map
    other than normal_base, recording R-090) is refused with NotYetSupported, never planned
    differently."""
    from tests.export.tier0 import compare_dry_runs

    report = compare_dry_runs(
        export_tests, tmp_path, tier0_export_goldens(), skeleton_of, plan_many
    )
    assert report["compared"] > 0, report
    assert report["differing"] == [], report["differing"]
    assert report["unexpected_refusals"] == [], report["unexpected_refusals"]


def test_dry_run_equals_painter_probes(export_tests: Path, tmp_path: Path) -> None:
    """3.5 (decision 091): every export probe of recording R-085 (P0-P13, decision 087), compiled
    on its recording's texture sets, behaves as Painter did: the dry run lists exactly the files
    the export left on disk, with their bit depth and channel count; Painter's refusals are
    ValueErrors; an export Painter refused makes the dry run raise; each legacy name reads the
    channel whose direct export Painter wrote with the same bytes. Only the case-only collision
    and srcChannel A stay refused as unrecorded."""
    from tests.export.tier0 import compare_probes

    report = compare_probes(export_tests, tmp_path, skeleton_of, plan_many)
    assert report["compared"] == 2 * (14 + 7 + 4 + 3 * 14), report["compared"]
    assert report["differing"] == [], report["differing"]
    assert report["unexpected_refusals"] == [], report["unexpected_refusals"]
    assert len(report["refused"]) == 2 * 3, report["refused"]
    assert report["pairings"] == 2 * 2 * (1 + 3 + 2), report["pairings"]


def test_luma_probe_exact(export_tests: Path, tmp_path: Path) -> None:
    """Probe P5 (decision 091): `srcChannel L` of BaseColor through the plan is the Rec. 601 luma
    of the linear channel; written with Painter 12.1.5's 16-bit sRGB encode it equals r1 and r2
    on every texel of s0 (field A), and so does the RGB export of the channel. On s1 (no layer)
    the luma of BaseColor's base value is refused: the evaluator holds the base's export value,
    not its linear one."""
    from tests.export.tier0 import luma_probe

    report, refused = luma_probe(export_tests, tmp_path)
    assert len(report) == 4 and not any(report.values()), report
    assert list(refused) == ["s1_lum.png"], refused
    assert "base value" in refused["s1_lum.png"], refused


# ── 3.6 Virtual-map goldens through the plan (owner's machine) ───────────────


def test_virtual_map_goldens_exact(export_tests: Path, tmp_path: Path) -> None:
    """3.6: Normal_OpenGL and Normal_DirectX over the height-amplitude sweep and the Sharp and
    Sobel plane-strength sweeps, compiled as plan files, evaluated through `EvaluateFileOn` on
    the CPU store and written with the 16-bit write rule, equal r1 on every texel and r2 wherever
    r2 equals r1; the published virtual-maps.json is exactly the document this run derives."""
    from tests.export.tier0 import PUBLISHED, publish, virtual_map_goldens

    report = virtual_map_goldens(export_tests, tmp_path, REPO_ROOT)
    assert report["maps"] == 40, report["maps"]
    assert report["differing"] == [], report["differing"]
    assert json.loads(PUBLISHED.read_text(encoding="utf-8")) == publish(report)


def test_virtual_maps_semantics_published() -> None:
    """2.5: `parity/semantics/virtual-maps.json` is a valid public semantics file listing every
    documented virtual map with its documented meaning and public sources: the supported maps
    `exact` with their residuals, every other one a `gap` (refused before anything is
    written)."""
    from tools.parity.fit.common import publishable_problems

    doc = json.loads(
        (REPO_ROOT / "parity" / "semantics" / "virtual-maps.json").read_text(encoding="utf-8")
    )
    assert publishable_problems(doc) == []
    status = {e["subject"].split(":")[0]: e["status"] for e in doc["entries"]}
    gaps = ["AO_Mixed", "Diffuse", "Specular", "Glossiness", "Unity4Diff", "Unity4Gloss"]
    gaps += ["reflection", "1/ior", "Glossiness2", "f0", "View_2D"]
    assert status == {"Normal_OpenGL": "exact", "Normal_DirectX": "exact"} | dict.fromkeys(
        gaps, "gap"
    )
    for e in doc["entries"]:
        assert e["public_sources"], e["entry_id"]
        if e["status"] == "exact":
            assert e["residuals"] and all(r["difference"]["differing"] == 0 for r in e["residuals"])


def test_write16_rule() -> None:
    """The 16-bit write rule the golden comparisons apply (arith::WriteUnorm at 16 bits): an
    8-bit code's float32 value k/255 writes k * 257, and 0 and 1 write 0 and 65535."""
    from tests.export.tier0 import write16

    k = np.arange(256)
    assert np.array_equal(write16((k / 255.0).astype(np.float32)), k * 257)
