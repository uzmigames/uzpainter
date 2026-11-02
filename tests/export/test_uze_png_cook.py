"""Tests of phase3.3_uze-png-cook-cli (decision 380; `src/export/cook_uzengine.cpp`,
`src/export/cli.h`, `src/export/EXPORT.md` §5): `cook-uzengine` turns a texture set exported as
PNG into the UzEngine delivery (`.uztexture` set + `.uzmat`) through the native preset's own cook.

Every case runs `uzp-export-tests.exe cook-uzengine` (the same `RunCookUzEngineCommand` that
`UzPainter.exe cook-uzengine` dispatches to) on the CPU. No case runs Painter, UzEngine or the GPU.

What these cases establish:
- Byte identity with the native preset: the canonical PNG 16 maps a native UzEngine export writes,
  fed back to the verb, give that export's `.uztexture` files and `.uzmat`, byte for byte.
- Equality on decoded inputs: an 8-bit PNG and the 16-bit PNG of its codes * 257, an OpenGL normal
  and the DirectX normal of its mirrored green, a packed ORM and its three grey maps, give equal
  bytes.
- Determinism across runs, the receipt's fields, and every refusal of the input contract, with
  nothing written on refusal.
"""

from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import zlib
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pytest

from tests.export.test_uze_preset import (
    authored_spec,
    publish,
    published,
    shipped_config,
    variant_presets,
)
from tools.parity.feasibility import png

UZTEXTURE_MAGIC = 0x5A585455
FORMAT_CODES = {"BC5": 3, "BC7": 4, "BC4": 5}
SIZE = 64
MAPS = ("albedo", "normal", "orm", "emissive", "height")


def cook(exe: Path, *args: str) -> tuple[int, dict[str, Any] | None, str]:
    proc = subprocess.run(
        [str(exe), "cook-uzengine", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
        check=False,
    )
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    receipt = json.loads(lines[0]) if proc.returncode == 0 and len(lines) == 1 else None
    return proc.returncode, receipt, proc.stderr


def cooked(
    exe: Path, out: Path, maps: dict[str, Path], convention: str, set_name: str = "s"
) -> dict[str, Any]:
    args = ["--set", set_name, "--out", str(out), "--normal-convention", convention]
    for flag, path in maps.items():
        args += [f"--{flag}", str(path)]
    code, receipt, err = cook(exe, *args)
    assert code == 0 and receipt is not None, (code, err)
    return receipt


def written(out: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(out.iterdir())}


def write_png(path: Path, samples: npt.NDArray[np.integer], depth: int) -> Path:
    png.write(path, samples, depth)
    return path


def chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def rng_codes(seed: int, shape: tuple[int, ...], high: int = 256) -> npt.NDArray[np.int64]:
    return np.random.default_rng(seed).integers(0, high, size=shape, dtype=np.int64)


def normal_codes(seed: int, size: int = SIZE) -> npt.NDArray[np.int64]:
    """An 8-bit OpenGL normal map with Z > 0 everywhere."""
    rng = np.random.default_rng(seed)
    xy = rng.uniform(-0.6, 0.6, size=(size, size, 2))
    z = np.sqrt(1.0 - (xy**2).sum(axis=2))
    v = np.concatenate([xy, z[..., None]], axis=2)
    return np.round((v * 0.5 + 0.5) * 255).astype(np.int64)


@pytest.fixture(scope="module")
def painter_set(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """The Assets3D case: three 8-bit PNGs (BaseColor RGB without alpha, OpenGL normal, packed
    ORM), plus the arrays they hold."""
    root = tmp_path_factory.mktemp("painter-set")
    albedo = rng_codes(1, (SIZE, SIZE, 3))
    normal = normal_codes(2)
    orm = rng_codes(3, (SIZE, SIZE, 3))
    return {
        "root": root,
        "albedo": albedo,
        "normal": normal,
        "orm": orm,
        "maps": {
            "albedo": write_png(root / "BaseColor.png", albedo, 8),
            "normal": write_png(root / "Normal.png", normal, 8),
            "orm": write_png(root / "ORM.png", orm, 8),
        },
    }


@pytest.fixture(scope="module")
def painter_cooked(
    export_tests: Path, painter_set: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, bytes]]:
    out = painter_set["root"] / "out"
    receipt = cooked(export_tests, out, painter_set["maps"], "opengl")
    return receipt, written(out)


# ── Byte identity with the native preset ─────────────────────────────────────


def test_canonical_maps_of_a_native_export_cook_to_its_bytes(
    export_tests: Path, tmp_path: Path
) -> None:
    """The native UzEngine export (the test-only variant whose ORM R reads ambientOcclusion,
    test_uze_preset.py; its `uzengine` targets are the shipped ones) of an authored set with a
    varying opacity: its canonical PNG 16 maps, fed to the verb with the DirectX convention its
    normal is stored in, give its five `.uztexture` files and its `.uzmat` byte for byte, and the
    receipt's hashes are the native receipt's."""
    presets = variant_presets(tmp_path / "presets")
    spec_path = authored_spec(tmp_path / "spec")
    native_out = tmp_path / "native"
    code, lines, err = publish(
        export_tests, spec_path, shipped_config(native_out.as_posix()), tmp_path, presets
    )
    assert code == 0 and len(lines) == 1 and "error" not in lines[0], (code, lines, err)
    generation, native_receipt = published(export_tests, native_out)
    files = generation / "files"
    out = tmp_path / "cooked"
    receipt = cooked(
        export_tests,
        out,
        {
            "albedo": files / "canonical" / "s0_albedo.png",
            "normal": files / "s0_normal.png",
            "orm": files / "canonical" / "s0_orm.png",
            "emissive": files / "canonical" / "s0_emissive.png",
            "height": files / "s0_height.png",
        },
        "directx",
        "s0",
    )
    expected = [f"s0_{m}.uztexture" for m in MAPS] + ["s0.uzmat"]
    assert [f["path"] for f in receipt["files"]] == expected
    native = {f["path"]: f for f in native_receipt["files"]}
    for name in expected:
        assert (out / name).read_bytes() == (files / name).read_bytes(), name
    for entry in receipt["files"]:
        assert entry["sha256"] == native[entry["path"]]["sha256"]
        if entry["format"] == "uztexture":
            mine, theirs = entry["uztexture"], native[entry["path"]]["uztexture"]
            assert (
                mine["binding"],
                mine["format"],
                mine["srgb"],
                mine["mips"],
                mine["encoder"],
            ) == (
                theirs["binding"],
                theirs["format"],
                theirs["srgb"],
                theirs["mips"],
                theirs["encoder"],
            )
    material = receipt["files"][-1]["uzmat"]
    assert material["blend"] == native["s0.uzmat"]["uzmat"]["blend"] == "Masked"
    assert material["opacity"] == "albedo alpha"
    assert material["inline_material"] == native["s0.uzmat"]["uzmat"]["inline_material"]


# ── The Assets3D three-PNG case and its receipt ──────────────────────────────


def test_three_png_set_cooks_with_its_receipt(
    painter_set: dict[str, Any], painter_cooked: tuple[dict[str, Any], dict[str, bytes]]
) -> None:
    """BaseColor (8-bit RGB, no alpha), an OpenGL normal and a packed ORM give the albedo, normal,
    ORM and a black emissive texture plus an Opaque `.uzmat`; the receipt names each input's
    hashes, depth, colour space and convention, and each file's format, mips, filter and encoder."""
    receipt, files = painter_cooked
    assert sorted(files) == sorted(
        [
            "s_albedo.uztexture",
            "s_normal.uztexture",
            "s_orm.uztexture",
            "s_emissive.uztexture",
            "s.uzmat",
        ]
    )
    for entry in receipt["files"]:
        data = files[entry["path"]]
        assert entry["bytes"] == len(data) and entry["sha256"] == hashlib.sha256(data).hexdigest()
    textures = {f["path"]: f for f in receipt["files"] if f["format"] == "uztexture"}
    table = {
        "s_albedo.uztexture": ("albedo", "BC7", True, "masked_colour"),
        "s_normal.uztexture": ("normal", "BC5", False, "normal"),
        "s_orm.uztexture": ("orm", "BC7", False, "linear"),
        "s_emissive.uztexture": ("emissive", "BC7", True, "colour"),
    }
    for name, (binding, fmt, srgb, mips) in table.items():
        meta = textures[name]["uztexture"]
        assert (meta["binding"], meta["format"], meta["srgb"], meta["mip_filter"]) == (
            binding,
            fmt,
            srgb,
            mips,
        )
        assert meta["mips"] == 7 and meta["size"] == [SIZE, SIZE]
        assert meta["encoder"] == "etcpak 2.1" and meta["encoder_settings"]
        assert textures[name]["colour_space"] == ("sRGB" if srgb else "linear")
        header = struct.unpack_from("<16I", files[name])
        assert header[0] == UZTEXTURE_MAGIC and header[2:4] == (SIZE, SIZE)
        assert header[4] == 7 and header[5] == FORMAT_CODES[fmt] and header[6] == (1 if srgb else 0)
    assert textures["s_albedo.uztexture"]["uztexture"]["alpha_coverage_threshold"] == 0.5
    assert textures["s_normal.uztexture"]["uztexture"]["negative_z"] == {
        "policy": "fail",
        "texels": 0,
    }
    assert textures["s_albedo.uztexture"]["consumer_gaps"] == []
    material = receipt["files"][-1]
    assert material["path"] == "s.uzmat" and material["uzmat"]["blend"] == "Opaque"
    assert material["uzmat"]["opacity"] == "1: the albedo PNG has no alpha"
    assert {g["channel"] for g in material["consumer_gaps"]} == {"blend"}
    graph = json.loads(files["s.uzmat"])
    assert graph["blendMode"] == "Opaque" and graph["twoSided"] is False
    inputs = {i["map"]: i for i in receipt["inputs"]}
    assert inputs["emissive"]["path"] is None and "black" in inputs["emissive"]["synthesized"]
    assert inputs["normal"]["convention"] == "opengl" and inputs["normal"]["green_mirrored"] is True
    for name in ("albedo", "normal", "orm"):
        source = painter_set["maps"][name]
        assert inputs[name]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
        assert (inputs[name]["bit_depth"], inputs[name]["channels"]) == (8, "RGB")
        decoded = png.read(source).astype("<u2") * 257
        rgba = np.concatenate([decoded, np.full((SIZE, SIZE, 1), 65535, "<u2")], axis=2)
        assert inputs[name]["decoded_rgba16_sha256"] == hashlib.sha256(rgba.tobytes()).hexdigest()
    assert inputs["albedo"]["colour_space"] == "sRGB" and inputs["orm"]["colour_space"] == "linear"


def test_runs_are_deterministic(
    export_tests: Path,
    painter_set: dict[str, Any],
    painter_cooked: tuple[dict[str, Any], dict[str, bytes]],
    tmp_path: Path,
) -> None:
    """A second run of the same inputs writes the same bytes and the same receipt."""
    receipt, files = painter_cooked
    again = cooked(export_tests, tmp_path / "again", painter_set["maps"], "opengl")
    assert written(tmp_path / "again") == files
    assert {**again, "out": None} == {**receipt, "out": None}


def test_equal_decoded_inputs_give_equal_bytes(
    export_tests: Path,
    painter_set: dict[str, Any],
    painter_cooked: tuple[dict[str, Any], dict[str, bytes]],
    tmp_path: Path,
) -> None:
    """16-bit PNGs of the codes * 257, a DirectX normal holding the mirrored green and a grey AO,
    roughness and metallic in place of the packed ORM decode to the same images and give the same
    bytes. An alpha channel of codes 65535 everywhere decodes to the same image too, so the
    textures are equal; the `.uzmat` follows the preset's layout rule (an alpha channel is the
    opacity, as in the native canonical file, whose all-1 alpha is dropped before writing) and
    blends Masked."""
    _, files = painter_cooked
    albedo, normal, orm = painter_set["albedo"], painter_set["normal"], painter_set["orm"]
    directx = normal.copy()
    directx[..., 1] = 255 - directx[..., 1]
    maps = {
        "albedo": write_png(tmp_path / "albedo16.png", albedo * 257, 16),
        "normal": write_png(tmp_path / "normal-dx.png", directx, 8),
        "ao": write_png(tmp_path / "ao.png", orm[..., 0], 8),
        "roughness": write_png(tmp_path / "roughness.png", orm[..., 1] * 257, 16),
        "metallic": write_png(tmp_path / "metallic.png", np.repeat(orm[..., 2:3], 3, axis=2), 8),
    }
    receipt = cooked(export_tests, tmp_path / "out", maps, "directx")
    assert written(tmp_path / "out") == files
    assert receipt["files"][-1]["uzmat"]["opacity"] == "1: the albedo PNG has no alpha"
    inputs = {i["map"]: i for i in receipt["inputs"]}
    assert inputs["normal"]["green_mirrored"] is False and inputs["albedo"]["bit_depth"] == 16
    opaque = np.concatenate([albedo, np.full((SIZE, SIZE, 1), 255, np.int64)], axis=2)
    alpha = {**painter_set["maps"], "albedo": write_png(tmp_path / "rgba1.png", opaque, 8)}
    masked = cooked(export_tests, tmp_path / "alpha", alpha, "opengl")
    textures = written(tmp_path / "alpha")
    assert {n: d for n, d in textures.items() if n != "s.uzmat"} == {
        n: d for n, d in files.items() if n != "s.uzmat"
    }
    assert masked["files"][-1]["uzmat"]["blend"] == "Masked"
    assert masked["files"][-1]["uzmat"]["opacity"] == "albedo alpha"


def test_albedo_alpha_masks_the_material_and_height_is_bc4(
    export_tests: Path, painter_set: dict[str, Any], tmp_path: Path
) -> None:
    """An albedo alpha below 1 somewhere blends Masked with the SM5 opacity gap; a grey 16-bit
    height is the BC4 heightmap texture with its gap; an emissive input replaces the black one."""
    alpha = rng_codes(4, (SIZE, SIZE, 1))
    maps = {
        **painter_set["maps"],
        "albedo": write_png(
            tmp_path / "rgba.png", np.concatenate([painter_set["albedo"], alpha], axis=2), 8
        ),
        "emissive": write_png(tmp_path / "emissive.png", rng_codes(5, (SIZE, SIZE, 3)), 8),
        "height": write_png(tmp_path / "height.png", rng_codes(6, (SIZE, SIZE), 65536), 16),
    }
    receipt = cooked(export_tests, tmp_path / "out", maps, "opengl")
    entries = {f["path"]: f for f in receipt["files"]}
    assert entries["s.uzmat"]["uzmat"]["blend"] == "Masked"
    assert entries["s.uzmat"]["uzmat"]["height"] == "s_height.uztexture"
    assert {g["channel"] for g in entries["s.uzmat"]["consumer_gaps"]} == {
        "opacity",
        "height",
        "blend",
    }
    assert [g["channel"] for g in entries["s_albedo.uztexture"]["consumer_gaps"]] == ["Opacity"]
    height = entries["s_height.uztexture"]
    assert (height["uztexture"]["binding"], height["uztexture"]["format"]) == ("heightmap", "BC4")
    assert [g["channel"] for g in height["consumer_gaps"]] == ["Height"]
    assert {i["map"]: i for i in receipt["inputs"]}["emissive"]["sha256"]


# ── Refusals ─────────────────────────────────────────────────────────────────


def grey4_png() -> bytes:
    """A 4x4 4-bit grey PNG."""
    raw = b"".join(b"\x00" + b"\x12\x34" for _ in range(4))
    header = struct.pack(">IIBBBBB", 4, 4, 4, 0, 0, 0, 0)
    return (
        png.SIGNATURE
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def with_trns(data: bytes) -> bytes:
    """`data` (an RGB PNG) with a tRNS chunk before its IDAT."""
    at = data.index(b"IDAT") - 4
    return data[:at] + chunk(b"tRNS", b"\x00\x00\x00\x00\x00\x00") + data[at:]


def refusal_case(
    name: str, root: Path, base: dict[str, Path], set_data: dict[str, Any]
) -> tuple[dict[str, Path], str]:
    """The maps of refusal `name` and the text its message holds."""
    maps = dict(base)
    if name == "size":
        maps["orm"] = write_png(root / "orm32.png", rng_codes(7, (32, 32, 3)), 8)
        return maps, "every map of a set has one size"
    if name == "power-of-two":
        for flag in ("albedo", "orm"):
            maps[flag] = write_png(root / f"{flag}48.png", rng_codes(8, (48, 48, 3)), 8)
        maps["normal"] = write_png(root / "normal48.png", normal_codes(9, 48), 8)
        return maps, "power of two"
    if name == "negative-z":
        normal = set_data["normal"].copy()
        normal[5, 7, 2] = 100
        maps["normal"] = write_png(root / "negz.png", normal, 8)
        return maps, "negative"
    if name == "orm-alpha":
        orm = np.concatenate([set_data["orm"], rng_codes(10, (SIZE, SIZE, 1))], axis=2)
        maps["orm"] = write_png(root / "orm-alpha.png", orm, 8)
        return maps, "only the albedo alpha carries opacity"
    if name == "height-not-grey":
        maps["height"] = write_png(root / "height-rgb.png", rng_codes(11, (SIZE, SIZE, 3)), 8)
        return maps, "not a grey map"
    if name == "grey-normal":
        maps["normal"] = write_png(root / "normal-grey.png", rng_codes(12, (SIZE, SIZE)), 8)
        return maps, "a normal map is RGB"
    if name == "4-bit":
        (root / "grey4.png").write_bytes(grey4_png())
        maps["height"] = root / "grey4.png"
        return maps, "4-bit samples"
    if name == "trns":
        (root / "trns.png").write_bytes(with_trns(base["albedo"].read_bytes()))
        maps["albedo"] = root / "trns.png"
        return maps, "tRNS"
    if name == "no-iend":
        data = base["orm"].read_bytes()
        (root / "no-iend.png").write_bytes(data[: data.rindex(b"IEND") - 4])
        maps["orm"] = root / "no-iend.png"
        return maps, "cannot read the chunks after the image"
    if name == "not-png":
        (root / "text.png").write_bytes(b"not a png")
        maps["orm"] = root / "text.png"
        return maps, "not a PNG file"
    assert name == "missing-file"
    maps["emissive"] = root / "absent.png"
    return maps, "cannot read the file"


@pytest.mark.parametrize(
    "name",
    [
        "size",
        "power-of-two",
        "negative-z",
        "orm-alpha",
        "height-not-grey",
        "grey-normal",
        "4-bit",
        "trns",
        "no-iend",
        "not-png",
        "missing-file",
    ],
)
def test_contract_violations_are_refused_and_write_nothing(
    export_tests: Path, painter_set: dict[str, Any], tmp_path: Path, name: str
) -> None:
    maps, reason = refusal_case(name, tmp_path, painter_set["maps"], painter_set)
    out = tmp_path / "out"
    args = ["--set", "s", "--out", str(out), "--normal-convention", "opengl"]
    for flag, path in maps.items():
        args += [f"--{flag}", str(path)]
    code, _, err = cook(export_tests, *args)
    assert code == 1 and "refused" in err and reason in err and "nothing was written" in err, err
    assert not out.exists()


@pytest.mark.parametrize("set_name", ["..", "../x", "a/b", "a\\b", "c:x", "CON"])
def test_unsafe_set_names_are_refused(
    export_tests: Path, painter_set: dict[str, Any], tmp_path: Path, set_name: str
) -> None:
    """The set name is the stem of every delivery path: one safe component (no separator, drive,
    `..` or device name), so the `.uzmat` only references relative paths under its root."""
    out = tmp_path / "out"
    args = ["--set", set_name, "--out", str(out), "--normal-convention", "opengl"]
    for flag, path in painter_set["maps"].items():
        args += [f"--{flag}", str(path)]
    code, _, err = cook(export_tests, *args)
    assert code == 1 and "refused" in err, err
    assert not out.exists()


@pytest.mark.parametrize(
    "drop, add",
    [
        ("--normal-convention", []),
        ("--albedo", []),
        ("--orm", []),
        (None, ["--ao", "x.png"]),
        ("--orm", ["--ao", "x.png", "--roughness", "y.png"]),
        (None, ["--albedo", "again.png"]),
        (None, ["--blend", "Masked"]),
    ],
)
def test_usage_errors_exit_2(
    export_tests: Path,
    painter_set: dict[str, Any],
    tmp_path: Path,
    drop: str | None,
    add: list[str],
) -> None:
    """A missing required argument or convention, a packed ORM with separate maps, an incomplete
    set of separate maps, a repeated or unknown option: the usage, exit status 2."""
    pairs = [("--set", "s"), ("--out", str(tmp_path / "out")), ("--normal-convention", "opengl")]
    pairs += [(f"--{k}", str(v)) for k, v in painter_set["maps"].items()]
    args = [x for k, v in pairs if k != drop for x in (k, v)] + add
    code, _, err = cook(export_tests, *args)
    assert code == 2 and "usage: UzPainter.exe cook-uzengine" in err, err
