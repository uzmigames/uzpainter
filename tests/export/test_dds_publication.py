"""Authored CPU DDS opt-in publication; canonical PNG remains the source of truth."""

from __future__ import annotations

import hashlib
import io
import json
import struct
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from tests.export.test_export_encoders import TEMPLATES, chan
from tests.export.test_export_plan import config, mapping, project, rgb, texture_set
from tests.export.test_export_publication import call, one, receipt_of, validate
from tools.parity.feasibility import png

SIZE = 256


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def request(path: str = "s0_n.png", fmt: int = 5, mips: int = 2) -> dict[str, Any]:
    return {"path": path, "format": fmt, "mips": mips}


def plan_case(
    tmp: Path,
    exe: Path,
    maps: list[dict[str, Any]],
    requests: list[dict[str, Any]],
    *,
    parameters: dict[str, Any] | None = None,
    uztexture: list[str] | None = None,
) -> dict[str, Any]:
    cfg = config(maps, ["s0"])
    if parameters:
        cfg["exportParameters"][0]["parameters"].update(parameters)
    path = tmp / "plan-cases.json"
    path.write_text(
        json.dumps(
            [
                {
                    "project": project(texture_set("s0")),
                    "config": cfg,
                    "dds": requests,
                    "uztexture": uztexture or [],
                }
            ]
        ),
        encoding="utf-8",
    )
    return one(exe, "plan", str(path))


def test_dds_plan_hash_and_dry_run(export_tests: Path, tmp_path: Path) -> None:
    maps = [mapping("$textureSet_n", rgb("virtualMap", "Normal_DirectX"))]
    baseline = plan_case(tmp_path, export_tests, maps, [])
    opted = plan_case(tmp_path, export_tests, maps, [request()])
    assert "error" not in opted, opted
    assert opted["canonical_sha256"] != baseline["canonical_sha256"]
    file = opted["plan"]["files"][0]
    assert file["dds"] == {
        "relativePath": "s0_n.dds",
        "path": "C:/export/s0_n.dds",
        "canonical": "s0_n.png",
        "format": "BC5",
        "srgb": False,
        "mips": "normal",
    }
    assert opted["list"][0][2] == ["C:/export/s0_n.png", "C:/export/s0_n.dds"]
    assert "dds" not in baseline["plan"]["files"][0]
    both = plan_case(tmp_path, export_tests, maps, [request()], uztexture=["s0_n.png"])
    assert "error" not in both, both
    assert both["list"][0][2] == [
        "C:/export/s0_n.png",
        "C:/export/s0_n.uztexture",
        "C:/export/s0_n.dds",
    ]


@pytest.mark.parametrize(
    "kind,name,fmt,mips,parameters",
    [
        ("virtualMap", "Normal_OpenGL", 5, 2, {}),
        ("documentMap", "normal", 5, 2, {}),
        ("virtualMap", "Normal_DirectX", 5, 0, {}),
        ("virtualMap", "Normal_DirectX", 6, 0, {}),
        ("virtualMap", "Normal_DirectX", 7, 2, {}),
        ("virtualMap", "Normal_DirectX", 255, 2, {}),
        ("virtualMap", "Normal_DirectX", 5, 255, {}),
        ("virtualMap", "Normal_DirectX", 5, 2, {"bitDepth": "8"}),
        ("virtualMap", "Normal_DirectX", 5, 2, {"fileFormat": "exr", "bitDepth": "32f"}),
        ("documentMap", "basecolor", 6, 0, {}),
        ("documentMap", "basecolor", 7, 0, {}),
    ],
)
def test_dds_plan_refusals(
    export_tests: Path,
    tmp_path: Path,
    kind: str,
    name: str,
    fmt: int,
    mips: int,
    parameters: dict[str, Any],
) -> None:
    suffix = "exr" if parameters.get("fileFormat") == "exr" else "png"
    result = plan_case(
        tmp_path,
        export_tests,
        [mapping("$textureSet_n", rgb(kind, name))],
        [request(f"s0_n.{suffix}", fmt, mips)],
        parameters=parameters,
    )
    assert result.get("error") in ("ValueError", "NotYetSupported"), result
    assert "DDS" in result["message"], result


def test_dds_plan_missing_reordered_and_path_collision(export_tests: Path, tmp_path: Path) -> None:
    channels = rgb("virtualMap", "Normal_DirectX")
    missing = plan_case(
        tmp_path, export_tests, [mapping("$textureSet_n", channels)], [request("missing.png")]
    )
    assert missing.get("error") == "ValueError" and "no such file" in missing["message"]
    channels[0]["srcChannel"], channels[1]["srcChannel"] = "G", "R"
    swapped = plan_case(tmp_path, export_tests, [mapping("$textureSet_n", channels)], [request()])
    assert swapped.get("error") == "NotYetSupported", swapped
    for directory, collision_expected in [
        ("s0_n.dds", True),
        ("S0_N.DDS", True),
        ("s0_n.dds-other", False),
    ]:
        collision = plan_case(
            tmp_path,
            export_tests,
            [
                mapping("$textureSet_n", rgb("virtualMap", "Normal_DirectX")),
                mapping(directory + "/child", rgb("documentMap", "basecolor")),
            ],
            [request()],
        )
        if collision_expected:
            assert collision.get("error") == "ValueError", collision
        else:
            assert "error" not in collision and "list_error" not in collision, collision
    inverse = plan_case(
        tmp_path,
        export_tests,
        [
            mapping("$textureSet_n", rgb("documentMap", "basecolor")),
            mapping("$textureSet_n.png/child", rgb("virtualMap", "Normal_DirectX")),
        ],
        [request("s0_n.png/child.png")],
    )
    assert inverse.get("error") == "ValueError", inverse


def fixture(tmp: Path, *, negative: bool = False) -> tuple[Path, Path, Path, Path]:
    tmp.mkdir(parents=True, exist_ok=True)
    mesh = tmp / "quad.obj"
    mesh.write_text(
        "o authored\nv 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\n"
        "vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\nvn 0 0 1\nusemtl s0\n"
        "f 1/1/1 2/2/1 3/3/1\nf 1/1/1 3/3/1 4/4/1\n",
        encoding="utf-8",
    )
    normal = np.empty((SIZE, SIZE, 3), dtype=np.int64)
    normal[...] = (32768, 24576, 16384 if negative else 62000)
    normal_bytes = png.encode(normal, 16)
    (tmp / "normal.png").write_bytes(normal_bytes)
    document = {
        "name": "s0",
        "resolution": [SIZE, SIZE],
        "mesh": str(mesh),
        "channels": [
            {"type": t, "format": f}
            for t, f in [
                ("Normal", "RGB16F"),
                ("Height", "L16F"),
                ("BaseColor", "sRGB8"),
                ("SpecularRoughness", "L8"),
            ]
        ],
        "resources": [{"sha256": digest(normal_bytes), "png": "normal.png"}],
        "layers": [
            {
                "kind": "fill",
                "sources": {"Normal": {"bitmap": digest(normal_bytes), "color_space": "Raw"}},
            }
        ],
    }
    spec = tmp / "spec.json"
    spec.write_text(json.dumps(document), encoding="utf-8")
    out = tmp / "out"
    cfg = config(
        [
            mapping("$textureSet_n", rgb("virtualMap", "Normal_DirectX")),
            mapping("$textureSet_c", rgb("documentMap", "basecolor")),
            mapping("$textureSet_r", [chan("L", "documentMap", "roughness")]),
        ],
        ["s0"],
    )
    cfg["exportPath"] = str(out)
    cfg["exportParameters"][0]["parameters"]["paddingAlgorithm"] = "passthrough"
    config_path = tmp / "config.json"
    config_path.write_text(json.dumps(cfg), encoding="utf-8")
    requests = tmp / "dds.json"
    requests.write_text(
        json.dumps([request(), request("s0_c.png", 7, 1), request("s0_r.png", 6, 0)]),
        encoding="utf-8",
    )
    return spec, config_path, requests, out


def publish(exe: Path, spec: Path, cfg: Path, requests: Path) -> dict[str, Any]:
    return one(exe, "publish", str(TEMPLATES), str(spec), str(cfg), "--dds", str(requests))


def check_dds(data: bytes, dxgi: int) -> Image.Image:
    assert data[:4] == b"DDS "
    assert struct.unpack_from("<II", data, 12) == (SIZE, SIZE)
    assert struct.unpack_from("<I", data, 28)[0] == 9
    assert struct.unpack_from("<5I", data, 128) == (dxgi, 3, 0, 1, 0)
    assert len(data) == 148 + sum(((max(1, SIZE >> n) + 3) // 4) ** 2 * 16 for n in range(9))
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def test_dds_real_write_publication_receipt_and_fixed_copy(
    export_tests: Path, tmp_path: Path
) -> None:
    spec, cfg, requests, out = fixture(tmp_path)
    baseline = one(export_tests, "publish", str(TEMPLATES), str(spec), str(cfg))
    assert "error" not in baseline, baseline
    first = out / "generations" / baseline["generation"] / "files"
    canonical = {p.name: p.read_bytes() for p in first.glob("*.png")}
    result = publish(export_tests, spec, cfg, requests)
    assert "error" not in result, result
    generation = out / "generations" / result["generation"]
    receipt = receipt_of(out, result["generation"])
    validate(receipt)
    assert digest((generation / "receipt.json").read_bytes()) == result["receipt_sha256"]
    entries = {f["path"]: f for f in receipt["files"]}
    assert set(entries) == {f"s0_{stem}.{ext}" for stem in "ncr" for ext in ("png", "dds")}
    for file in result["files"]:
        name = file["relativePath"]
        data = (generation / "files" / name).read_bytes()
        assert digest(data) == file["sha256"] == entries[name]["sha256"]
        assert len(data) == file["size"]
        if name.endswith("png"):
            assert data == canonical[name]
    for stem, dxgi, fmt, srgb in [
        ("n", 83, "BC5", False),
        ("c", 99, "BC7_SRGB", True),
        ("r", 98, "BC7", False),
    ]:
        entry = entries[f"s0_{stem}.dds"]
        assert entry["format"] == "dds" and entry["bit_depth"] == "8"
        meta = entry["dds"]
        assert meta["format"] == fmt and meta["srgb"] is srgb and meta["mips"] == 9
        assert meta["encoder"] == "etcpak 2.1"
        assert meta["source"] == f"s0_{stem}.png"
        assert meta["stored_channels"] == list("RG" if stem == "n" else "RGBA")
        assert meta["lossy"] is True and meta["settings"]
        decoded = check_dds((generation / "files" / f"s0_{stem}.dds").read_bytes(), dxgi)
        if stem == "n":
            png_codes = png.decode(canonical["s0_n.png"])
            actual = decoded.getpixel((0, 0))
            assert isinstance(actual, tuple)
            # BC5 stores RG in DirectX convention; a second flip would cross neutral.
            assert (actual[1] > 127) == (int(png_codes[0, 0, 1]) >= 32768)
    fixed = tmp_path / "fixed"
    copied = one(export_tests, "fixed-copy", str(out), str(fixed))
    assert "error" not in copied, copied
    for name, entry in entries.items():
        assert digest((fixed / name).read_bytes()) == entry["sha256"]
    # WriteExport's direct path must carry the same derivative bytes as publication.
    cfg_doc = json.loads(cfg.read_text())
    direct = tmp_path / "direct"
    cfg_doc["exportPath"] = str(direct)
    cfg.write_text(json.dumps(cfg_doc), encoding="utf-8")
    written = one(
        export_tests, "export", str(TEMPLATES), str(spec), str(cfg), "--dds", str(requests)
    )
    assert "error" not in written, written
    assert {f["relativePath"] for f in written["written"]} == set(entries)
    assert [f["relativePath"] for f in written["written"]] == [
        f"s0_{stem}.{ext}" for stem in "ncr" for ext in ("png", "dds")
    ]
    assert [Path(p) for p in written["list"][0][2]] == [Path(f["path"]) for f in written["written"]]
    for file in written["written"]:
        assert (
            digest((direct / file["relativePath"]).read_bytes())
            == entries[file["relativePath"]]["sha256"]
        )


def test_dds_interrupted_publish_preserves_previous_generation(
    export_tests: Path, tmp_path: Path
) -> None:
    spec, cfg, requests, out = fixture(tmp_path)
    prior = publish(export_tests, spec, cfg, requests)
    assert "error" not in prior, prior
    pointer = (out / "current.json").read_bytes()
    pinned = one(export_tests, "consume-pinned", str(out))
    code, _, _ = call(
        export_tests,
        "--fault",
        "kill_after_dds:1",
        "publish",
        str(TEMPLATES),
        str(spec),
        str(cfg),
        "--dds",
        str(requests),
    )
    assert code == 77
    assert (out / "current.json").read_bytes() == pointer
    assert one(export_tests, "consume-pinned", str(out)) == pinned
    recovered = one(export_tests, "recover", "--recover", str(out))
    assert "error" not in recovered, recovered
    assert (out / "current.json").read_bytes() == pointer


def test_dds_negative_z_bc5_refuses_preserving_publication(
    export_tests: Path, tmp_path: Path
) -> None:
    spec, cfg, requests, out = fixture(tmp_path / "positive")
    prior = publish(export_tests, spec, cfg, requests)
    assert "error" not in prior, prior
    pointer = (out / "current.json").read_bytes()
    negative, _, _, _ = fixture(tmp_path / "negative", negative=True)
    failed = publish(export_tests, negative, cfg, requests)
    assert failed.get("error") == "Failure" and "negative" in failed["message"].lower(), failed
    assert (out / "current.json").read_bytes() == pointer
