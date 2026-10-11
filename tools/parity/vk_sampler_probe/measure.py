"""The measurements behind decision 056 (task phase1.9_compositor-resample-gaps): Painter's
bilinear minification reproduced by the recording GPU's texture unit through Vulkan.

Runs `vkprobe.cpp` (built here with `zig c++`) on the owner's machine and compares its output
with the private Tier 0 goldens `resample-uv-minify`, `resample-uv-impulse` and the held-out
`resample-uv` user 6. Prints statistics only (exact fractions, maximum |delta| in 16-bit codes,
fitted weights); nothing recorded is written out.

    python -m tools.parity.vk_sampler_probe.measure <work-dir>

The model under test: a float32 RGBA texture of the bitmap stored bottom-up with a float32 box
mip chain, sampled with SampleGrad at Painter's UV (offset before scale and rotation) through an
anisotropic sampler with maxAnisotropy 4; BilinearSharp one sample at LOD bias -1.5; BilinearHQ
nine samples at +-1/3 output texel with the gradients divided by 3, the (+1/3, +1/3) one replaced
by the centre, weighed by the tent [1 2 1]^2 / 16 and blended with the centre sample by
alpha = min(footprint - 1, 1).
"""

from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np

from tools.parity.fit.common import Context
from tools.parity.fit.decode import decode
from tools.parity.store.store import locate
from tools.parity.tier0_semantics import fixtures

REPO = Path(__file__).resolve().parents[3]
SOURCE = Path(__file__).with_name("vkprobe.cpp")
DXC = REPO / "thirdparty" / "dxc" / "bin" / "x64" / "dxcompiler.dll"
SET = 256
SHARP_BIAS = -1.5
MAX_ANISOTROPY = 4
THIRD = 1.0 / 3.0
# Per set of the resample-uv-minify and -impulse goldens: filter and wrap (decision 048).
SETS = {
    "s0": ("HQ", "repeat"),
    "s1": ("Sharp", "repeat"),
    "s2": ("HQ", "none"),
    "s3": ("Sharp", "none"),
}
MINIFY = {
    0: ((5.13, 5.13), 0.0, (0.0, 0.0)),
    1: ((6.07, 6.07), 0.0, (0.0, 0.0)),
    2: ((7.77, 7.77), 0.0, (0.0, 0.0)),
    3: ((10.3, 10.3), 0.0, (0.0, 0.0)),
    4: ((13.2, 13.2), 0.0, (0.0, 0.0)),
    5: ((16.6, 16.6), 0.0, (0.0, 0.0)),
    6: ((13.2, 5.13), 0.0, (0.0, 0.0)),
    7: ((7.77, 7.77), 30.0, (0.123, 0.456)),
}
IMPULSE = {
    **{u: MINIFY[u] for u in range(6)},
    6: ((13.2, 13.2), 0.0, (0.001953125, 0.0009765625)),
    7: ((7.77, 7.77), 0.0, (0.0048828125, 0.0)),
}

HEAD = """
[[vk::binding(0, 0)]] Texture2D<float4> src;
[[vk::binding(1, 0)]] SamplerState s;
[[vk::binding(2, 0)]] RWTexture2D<float4> dst;
"""


class Probe:
    def __init__(self, work: Path) -> None:
        self.work = work
        self.exe = work / "vkprobe.exe"
        if not self.exe.exists():
            third = REPO / "thirdparty"
            subprocess.run(
                [
                    *("zig", "c++", "-std=c++20", "-O2", "-fms-extensions", "-w"),
                    *("-I", str(third / "volk"), "-I", str(third / "vulkan-headers" / "include")),
                    *("-I", str(third / "dxc" / "inc"), str(SOURCE)),
                    *("-o", str(self.exe), "-lole32"),
                ],
                check=True,
            )

    def run(
        self,
        levels: list[np.ndarray],
        body: str,
        *,
        anisotropy: int = MAX_ANISOTROPY,
        bias: float = 0.0,
        clamp: bool = False,
    ) -> np.ndarray:
        height, width = levels[0].shape[:2]
        header = struct.pack("<8I", width, height, len(levels), SET, SET, 2, anisotropy, int(clamp))
        data = bytearray(header + struct.pack("<3f", bias, 0.0, 1000.0))
        start = len(data)
        for level in levels:
            texels = level.astype("<f4")
            pitch = (texels.shape[1] * 16 + 255) & ~255
            for row in texels:
                data += row.tobytes().ljust(pitch, b"\0")
            data += b"\0" * (((len(data) - start + 511) & ~511) - (len(data) - start))
        folder = self.work / "run"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "probe.bin").write_bytes(bytes(data))
        (folder / "probe.hlsl").write_text(HEAD + body, encoding="utf-8")
        subprocess.run([str(self.exe), str(DXC), str(folder)], check=True, capture_output=True)
        out: np.ndarray = np.fromfile(folder / "out.bin", np.float32).reshape(SET, SET, 4)
        return out


def uv_body(
    scale: tuple[float, float],
    rotation: float,
    offset: tuple[float, float],
    shift: tuple[float, float] = (0.0, 0.0),
    gradient: float = 1.0,
    offset_last: bool = False,
) -> str:
    """Painter's UV of output texel (i, j) (+ `shift` texels), in double, and its gradients."""
    r = np.deg2rad(rotation)
    c, s = float(np.cos(r)), float(np.sin(r))
    if offset_last:
        ab = "const double a = (u - 0.5) * SU; const double b = (v - 0.5) * SV;"
        uv = "((C * a + S * b) + 0.5) - OU, ((-S * a + C * b) + 0.5) - OV"
    else:
        ab = "const double a = ((u - 0.5) - OU) * SU; const double b = ((v - 0.5) - OV) * SV;"
        uv = "(C * a + S * b) + 0.5, (-S * a + C * b) + 0.5"
    return f"""
static const double SU = {scale[0]!r}, SV = {scale[1]!r}, C = {c!r}, S = {s!r};
static const double OU = {offset[0]!r}, OV = {offset[1]!r}, PX = {shift[0]!r}, PY = {shift[1]!r};
static const float GM = {gradient!r};
[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID) {{
    const double u = ((double)id.x + 0.5 + PX) / {SET}.0;
    const double v = 1.0 - ((double)id.y + 0.5 + PY) / {SET}.0;
    {ab}
    const double2 p = double2({uv});
    const float2 gx = GM * float2((float)(C * SU / {SET}.0), (float)(-S * SU / {SET}.0));
    const float2 gy = GM * float2((float)(-S * SV / {SET}.0), (float)(-C * SV / {SET}.0));
    dst[id.xy] = src.SampleGrad(s, float2((float)p.x, (float)p.y), gx, gy);
}}
"""


def write16(values: np.ndarray) -> np.ndarray:
    v = np.clip(values.astype(np.float32).astype(np.float64), 0.0, 1.0)
    j = np.floor(v * (1 << 20)).astype(np.int64)
    result: np.ndarray = (j * 65535 + (1 << 19) - 1) >> 20
    return result


def texture(png: bytes) -> list[np.ndarray]:
    """The bitmap as float32 texels float32(c / 65535), stored bottom-up, and its box mips."""
    codes = np.asarray(decode(png).values, np.float64)
    codes = codes.reshape(codes.shape[0], codes.shape[1], -1)[..., :3]
    rgb = (codes / 65535.0).astype(np.float32)[::-1]
    level = np.concatenate([rgb, np.ones((*rgb.shape[:2], 1), np.float32)], axis=2)
    levels = [level]
    while levels[-1].shape[0] > 1:
        prev = levels[-1].astype(np.float64)
        h, w = prev.shape[:2]
        levels.append(prev.reshape(h // 2, 2, w // 2, 2, 4).mean(axis=(1, 3)).astype(np.float32))
    return levels


def covered(scale: tuple[float, float], rotation: float, offset: tuple[float, float]) -> np.ndarray:
    i = np.arange(SET)
    u = (i[None, :] + 0.5) / SET
    v = 1.0 - (i[:, None] + 0.5) / SET
    r = np.deg2rad(rotation)
    a = ((u - 0.5) - offset[0]) * scale[0]
    b = ((v - 0.5) - offset[1]) * scale[1]
    u2 = (np.cos(r) * a + np.sin(r) * b) + 0.5
    v2 = (-np.sin(r) * a + np.cos(r) * b) + 0.5
    mask: np.ndarray = (u2 >= 0) & (u2 < 1) & (v2 >= 0) & (v2 < 1)
    return mask


def hq(probe: Probe, levels: list[np.ndarray], geometry: Any, clamp: bool, width: int) -> Any:
    scale, rotation, offset = geometry
    samples = {}
    for dy in (-THIRD, 0.0, THIRD):
        for dx in (-THIRD, 0.0, THIRD):
            body = uv_body(scale, rotation, offset, (dx, dy), THIRD)
            samples[(dx, dy)] = probe.run(levels, body, clamp=clamp)[..., :3].astype(np.float32)
    tent = {k: (2 - round(abs(k[0]) * 3)) * (2 - round(abs(k[1]) * 3)) for k in samples}
    centre = samples[(0.0, 0.0)]
    acc = np.zeros_like(centre)
    for k, sample in samples.items():
        acc += np.float32(tent[k] / 16) * (centre if k == (THIRD, THIRD) else sample)
    footprint = min(scale) * width / SET
    alpha = np.float32(min(max(footprint - 1.0, 0.0), 1.0))
    model = centre * (np.float32(1) - alpha) + acc * alpha
    classes = np.stack(
        [
            (centre * np.float32(1)).ravel(),
            np.sum([samples[k] for k in samples if tent[k] == 2], axis=0).ravel(),
            np.sum(
                [v for k, v in samples.items() if tent[k] == 1 and k != (THIRD, THIRD)], axis=0
            ).ravel(),
        ],
        axis=1,
    ).astype(np.float64)
    return model, classes


def compare(ours: np.ndarray, theirs: np.ndarray, mask: np.ndarray | None = None) -> dict[str, Any]:
    delta = np.abs(write16(ours) - theirs.reshape(ours.shape))
    if mask is not None:
        delta = delta[mask]
    return {"exact": round(float((delta == 0).mean()), 6), "max": int(delta.max())}


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m tools.parity.vk_sampler_probe.measure <work-dir>")
        return 2
    probe = Probe(Path(argv[0]))
    ctx = Context(locate(), REPO)
    report: dict[str, Any] = {}

    # The trilinear band of the anisotropic path: mip k holds k / 8, t at LOD f = n / 16.
    levels = [np.full((64 >> k, 64 >> k, 4), k / 8, np.float32) for k in range(7)]
    band = {}
    for anisotropy in (1, 2, 4, 8, 16):
        body = """
[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID) {
    const float g = exp2((float)id.x / 16.0f) / 64.0f;
    dst[id.xy] = src.SampleGrad(s, float2(0.3f, 0.6f), float2(g, 0.0f), float2(0.0f, g)) * 8.0f;
}
"""
        out = probe.run(levels, body, anisotropy=anisotropy)
        band[str(anisotropy)] = [round(float(out[0, n, 0]) * 256) for n in range(17)]
    report["band_t256_at_lod_n16"] = band

    goldens = {
        "resample-uv-minify": (fixtures.pattern64(), MINIFY),
        "resample-uv-impulse": (fixtures.impulse64(), IMPULSE),
    }
    for stem, (png, geometries) in goldens.items():
        levels = texture(png)
        golden = ctx.golden(f"semantics/{stem}")
        for texture_set, (filter_, wrap) in SETS.items():
            for user, geometry in geometries.items():
                clamp = wrap == "none"
                mask = covered(*geometry) if clamp else None
                theirs = np.asarray(golden.map("r1", f"{texture_set}/user{user}").values)
                if filter_ == "Sharp":
                    body = uv_body(*geometry)
                    ours = probe.run(levels, body, bias=SHARP_BIAS, clamp=clamp)[..., :3]
                    report[f"{stem} {texture_set}/user{user}"] = compare(ours, theirs, mask)
                    continue
                model, classes = hq(probe, levels, geometry, clamp, 64)
                entry = compare(model, theirs, mask)
                rows = np.ones(theirs.size, bool) if mask is None else np.repeat(mask.ravel(), 3)
                target = theirs.ravel()[rows] / 65535.0
                w = np.linalg.lstsq(classes[rows], target, rcond=None)[0]
                entry["class_weights_x256"] = [round(float(x) * 256, 2) for x in w]
                report[f"{stem} {texture_set}/user{user}"] = entry

    # Held out: resample-uv user 6 (field A, 256 x 256, scale 3.3), s0 HQ and s1 Sharp.
    levels = texture(fixtures.field_a())
    golden = ctx.golden("semantics/resample-uv")
    geometry = ((3.3, 3.3), 0.0, (0.0, 0.0))
    sharp = probe.run(levels, uv_body(*geometry), bias=SHARP_BIAS)[..., :3]
    held = np.asarray(golden.map("r1", "s1/user6").values)
    report["held-out resample-uv s1/user6"] = compare(sharp, held)
    model, _ = hq(probe, levels, geometry, False, 256)
    held = np.asarray(golden.map("r1", "s0/user6").values)
    report["held-out resample-uv s0/user6"] = compare(model, held)

    # The offset order on resample-uv-minify s1 user 7 (scale 7.77, rotation 30, offset).
    levels = texture(fixtures.pattern64())
    theirs = np.asarray(ctx.golden("semantics/resample-uv-minify").map("r1", "s1/user7").values)
    for name, last in (("offset_before_scale", False), ("offset_after_rotation", True)):
        ours = probe.run(levels, uv_body(*MINIFY[7], offset_last=last), bias=SHARP_BIAS)[..., :3]
        delta = np.abs(write16(ours) - theirs.reshape(ours.shape))
        exact = round(float((delta == 0).mean()), 6)
        report[f"transform {name}"] = {"exact": exact, "mean": float(delta.mean())}

    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
