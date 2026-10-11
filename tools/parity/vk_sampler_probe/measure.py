"""The measurements behind decisions 056 and 060 (task phase1.9_compositor-resample-gaps): Painter's
bilinear minification reproduced exactly by the recording GPU's texture unit through Vulkan.

Runs `vkprobe.cpp` (built here with `zig c++`) on the owner's machine and compares its output
with the private Tier 0 goldens `resample-uv-minify`, `resample-uv-impulse` and the held-out
`resample-uv` user 6, both recordings. Prints statistics only (differing values, maximum |delta|
in 16-bit codes); nothing recorded is written out.

    python -m tools.parity.vk_sampler_probe.measure <work-dir>

The model under test (decision 060), with the GPU's own sampler as the texture unit:

- the bitmap as a float32 RGBA texture float32(c / 65535) stored bottom-up; each mip level the
  exact mean of four texels of the level above, rounded to the nearest float32, ties up;
- Painter's UV in float32: the affine matrix M of T(1/2) R S T(-1/2 - o), composed in double and
  rounded to float32, applied as u' = fma(m00, u, m01 v) + m02, v' = fma(m10, u, m11 v) + m12 to
  u = float32((i + 1/2) / W), v = float32(1 - (j + 1/2) / H);
- BilinearSharp: one SampleGrad (anisotropic sampler, maxAnisotropy 4) at LOD bias -1.5;
- BilinearHQ: the fine derivatives ddx, ddy of (u', v') in each 2 x 2 quad; nine samples at
  (u', v') + DX ddx + DY ddy (float32, DX and DY in {-1/3, 0, 1/3} as float32) with the gradients
  divided by 3; acc their float32 sum in the order centre, (+, 0), (-, 0), (0, -), (0, +), (+, -),
  (-, -), (-, +) and the centre again, weighed 4, 2, 2, 2, 2, 1, 1, 1, 1 / 16; C1 the level-0
  bilinear sample at (u', v'); alpha = clamp(min(|ddx|, |ddy|) w - 1, 0, 1) in float32 (w the
  bitmap width); the value fma(C1, 1 - alpha, acc alpha).
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
F32 = np.float32
THIRD = F32(1.0 / 3.0)
RECORDINGS = ("r1", "r2")
# Per set of the resample-uv-minify and -impulse goldens: filter and wrap (decision 048).
SETS = {
    "s0": ("HQ", "repeat"),
    "s1": ("Sharp", "repeat"),
    "s2": ("HQ", "none"),
    "s3": ("Sharp", "none"),
}
Geometry = tuple[tuple[float, float], float, tuple[float, float]]
MINIFY: dict[int, Geometry] = {
    0: ((5.13, 5.13), 0.0, (0.0, 0.0)),
    1: ((6.07, 6.07), 0.0, (0.0, 0.0)),
    2: ((7.77, 7.77), 0.0, (0.0, 0.0)),
    3: ((10.3, 10.3), 0.0, (0.0, 0.0)),
    4: ((13.2, 13.2), 0.0, (0.0, 0.0)),
    5: ((16.6, 16.6), 0.0, (0.0, 0.0)),
    6: ((13.2, 5.13), 0.0, (0.0, 0.0)),
    7: ((7.77, 7.77), 30.0, (0.123, 0.456)),
}
IMPULSE: dict[int, Geometry] = {
    **{u: MINIFY[u] for u in range(6)},
    6: ((13.2, 13.2), 0.0, (0.001953125, 0.0009765625)),
    7: ((7.77, 7.77), 0.0, (0.0048828125, 0.0)),
}
HELD_OUT: Geometry = ((3.3, 3.3), 0.0, (0.0, 0.0))
# HQ's accumulation order (DX, DY in thirds) and weights in sixteenths; (+1, +1) reads the centre.
HQ_ORDER = (
    ((0, 0), 4),
    ((1, 0), 2),
    ((-1, 0), 2),
    ((0, -1), 2),
    ((0, 1), 2),
    ((1, -1), 1),
    ((-1, -1), 1),
    ((-1, 1), 1),
    ((0, 0), 1),
)

KERNEL = """
[[vk::binding(0, 0)]] Texture2D<float4> src;
[[vk::binding(1, 0)]] SamplerState s;
[[vk::binding(2, 0)]] RWTexture2D<float4> dst;
[[vk::binding(3, 0)]] StructuredBuffer<float4> params;
[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID) {
    uint w, h;
    dst.GetDimensions(w, h);
    if (id.x >= w || id.y >= h) return;
    const float4 a = params[2 * (id.y * w + id.x)];
    const float4 b = params[2 * (id.y * w + id.x) + 1];
    dst[id.xy] = b.z != 0.0f ? src.SampleLevel(s, a.xy, 0.0f) : src.SampleGrad(s, a.xy, a.zw, b.xy);
}
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
        params: np.ndarray,
        *,
        width: int = SET,
        anisotropy: int = MAX_ANISOTROPY,
        bias: float = 0.0,
        clamp: bool = False,
    ) -> np.ndarray:
        """`params` holds two float4 per output texel: (u, v, ddx), (ddy, level-0 flag, 0)."""
        height, size = levels[0].shape[0], levels[0].shape[1]
        rows = params.shape[0] // (2 * width)
        header = struct.pack(
            "<8I", size, height, len(levels), width, rows, 2, anisotropy, int(clamp)
        )
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
        (folder / "probe.hlsl").write_text(KERNEL, encoding="utf-8")
        (folder / "params.bin").write_bytes(np.ascontiguousarray(params, "<f4").tobytes())
        subprocess.run([str(self.exe), str(DXC), str(folder)], check=True, capture_output=True)
        out: np.ndarray = np.fromfile(folder / "out.bin", np.float32).reshape(rows, width, 4)
        return out

    def sample(
        self,
        levels: list[np.ndarray],
        uv: tuple[np.ndarray, np.ndarray],
        ddx: tuple[Any, Any],
        ddy: tuple[Any, Any],
        *,
        level0: bool = False,
        bias: float = 0.0,
        clamp: bool = False,
    ) -> np.ndarray:
        """SampleGrad (or SampleLevel 0) at every texel of the set; the RGB result in float32."""
        params = np.zeros((SET, SET, 2, 4), np.float32)
        params[..., 0, 0], params[..., 0, 1] = uv
        params[..., 0, 2], params[..., 0, 3] = ddx
        params[..., 1, 0], params[..., 1, 1] = ddy
        params[..., 1, 2] = float(level0)
        out = self.run(levels, params.reshape(-1, 4), bias=bias, clamp=clamp)
        result: np.ndarray = out[..., :3].astype(np.float32)
        return result


def write16(values: np.ndarray) -> np.ndarray:
    v = np.clip(values.astype(np.float32).astype(np.float64), 0.0, 1.0)
    j = np.floor(v * (1 << 20)).astype(np.int64)
    result: np.ndarray = (j * 65535 + (1 << 19) - 1) >> 20
    return result


def nearest_ties_up(exact: np.ndarray) -> np.ndarray:
    """The float32 nearest to each double, ties toward +infinity."""
    first = exact.astype(np.float32)
    low = np.where(first.astype(np.float64) > exact, np.nextafter(first, F32(-np.inf)), first)
    high = np.where(low.astype(np.float64) < exact, np.nextafter(low, F32(np.inf)), low)
    middle = (low.astype(np.float64) + high.astype(np.float64)) / 2
    result: np.ndarray = np.where(exact >= middle, high, low)
    return result


def texture(png: bytes) -> list[np.ndarray]:
    """The bitmap as float32 texels float32(c / 65535), stored bottom-up, and its mip chain."""
    codes = np.asarray(decode(png).values, np.float64)
    codes = codes.reshape(codes.shape[0], codes.shape[1], -1)[..., :3]
    rgb = (codes / 65535.0).astype(np.float32)[::-1]
    levels = [np.concatenate([rgb, np.ones((*rgb.shape[:2], 1), np.float32)], axis=2)]
    while levels[-1].shape[0] > 1:
        p = levels[-1].astype(np.float64)
        mean = (p[0::2, 0::2] + p[0::2, 1::2] + p[1::2, 0::2] + p[1::2, 1::2]) / 4
        levels.append(nearest_ties_up(mean))
    return levels


def fma32(a: Any, b: Any, c: Any) -> np.ndarray:
    """float32(a b + c) with the exact product (a and b float32, c float32)."""
    exact = np.asarray(a, np.float64) * np.asarray(b, np.float64) + np.asarray(c, np.float64)
    result: np.ndarray = exact.astype(np.float32)
    return result


def painter_uv(geometry: Geometry) -> tuple[np.ndarray, np.ndarray]:
    """Painter's float32 UV of every texel of the set (decision 060)."""
    (su, sv), rotation, (ou, ov) = geometry
    r = np.deg2rad(rotation)
    c, s = np.cos(r), np.sin(r)
    m = np.array(
        [
            [c * su, s * sv, c * su * (-0.5 - ou) + s * sv * (-0.5 - ov) + 0.5],
            [-s * su, c * sv, -s * su * (-0.5 - ou) + c * sv * (-0.5 - ov) + 0.5],
        ]
    ).astype(np.float32)
    i = np.arange(SET, dtype=np.float64)
    u = np.broadcast_to(((i + 0.5) / SET).astype(np.float32)[None, :], (SET, SET))
    v = np.broadcast_to((1.0 - (i + 0.5) / SET).astype(np.float32)[:, None], (SET, SET))
    x = fma32(m[0, 0], u, m[0, 1] * v) + m[0, 2]
    y = fma32(m[1, 0], u, m[1, 1] * v) + m[1, 2]
    return x, y


def double_uv(geometry: Geometry, offset_last: bool) -> tuple[np.ndarray, np.ndarray]:
    """The double-precision UV with the offset first (decision 056) or last (the old order)."""
    (su, sv), rotation, (ou, ov) = geometry
    r = np.deg2rad(rotation)
    c, s = np.cos(r), np.sin(r)
    i = np.arange(SET, dtype=np.float64)
    u = np.broadcast_to(((i + 0.5) / SET)[None, :], (SET, SET))
    v = np.broadcast_to((1.0 - (i + 0.5) / SET)[:, None], (SET, SET))
    if offset_last:
        a, b = (u - 0.5) * su, (v - 0.5) * sv
        return (c * a + s * b) + 0.5 - ou, (-s * a + c * b) + 0.5 - ov
    a, b = ((u - 0.5) - ou) * su, ((v - 0.5) - ov) * sv
    return (c * a + s * b) + 0.5, (-s * a + c * b) + 0.5


def gradients(geometry: Geometry, scale: float = 1.0) -> tuple[tuple[Any, Any], tuple[Any, Any]]:
    (su, sv), rotation, _ = geometry
    r = np.deg2rad(rotation)
    c, s = float(np.cos(r)), float(np.sin(r))
    ddx = (F32(scale) * F32(c * su / SET), F32(scale) * F32(-s * su / SET))
    ddy = (F32(scale) * F32(-s * sv / SET), F32(scale) * F32(-c * sv / SET))
    return ddx, ddy


def fine(values: np.ndarray, axis: int) -> np.ndarray:
    """The fine derivative within each 2 x 2 quad along `axis` (1: x, 0: y), in float32."""
    q = values.reshape(SET // 2, 2, SET // 2, 2)
    if axis == 1:
        d = q[:, :, :, 1] - q[:, :, :, 0]
        result: np.ndarray = np.repeat(d[:, :, :, None], 2, axis=3).reshape(SET, SET)
    else:
        d = q[:, 1, :, :] - q[:, 0, :, :]
        result = np.repeat(d[:, None, :, :], 2, axis=1).reshape(SET, SET)
    return result


def sharp(probe: Probe, levels: list[np.ndarray], geometry: Geometry, clamp: bool) -> np.ndarray:
    ddx, ddy = gradients(geometry)
    return probe.sample(levels, painter_uv(geometry), ddx, ddy, bias=SHARP_BIAS, clamp=clamp)


def hq(probe: Probe, levels: list[np.ndarray], geometry: Geometry, clamp: bool) -> np.ndarray:
    u, v = painter_uv(geometry)
    dux, dvx, duy, dvy = fine(u, 1), fine(v, 1), fine(u, 0), fine(v, 0)
    ddx, ddy = gradients(geometry, 1.0 / 3.0)
    samples = {}
    for (dx, dy), _ in HQ_ORDER[:-1]:
        step_x, step_y = F32(dx) * THIRD, F32(dy) * THIRD
        point = ((u + step_x * dux) + step_y * duy, (v + step_x * dvx) + step_y * dvy)
        samples[(dx, dy)] = probe.sample(levels, point, ddx, ddy, clamp=clamp)
    acc = np.zeros_like(samples[(0, 0)])
    for key, weight in HQ_ORDER:
        acc = acc + F32(weight / 16) * samples[key]
    base = probe.sample(levels, (u, v), (0, 0), (0, 0), level0=True, clamp=clamp)
    length_x = np.sqrt(dux * dux + dvx * dvx).astype(np.float32)
    length_y = np.sqrt(duy * duy + dvy * dvy).astype(np.float32)
    width = F32(levels[0].shape[1])
    alpha = np.clip(np.minimum(length_x, length_y) * width - F32(1), F32(0), F32(1))[..., None]
    return fma32(base, F32(1) - alpha, acc * alpha)


def covered(geometry: Geometry) -> np.ndarray:
    u, v = painter_uv(geometry)
    mask: np.ndarray = (u >= 0) & (u < 1) & (v >= 0) & (v < 1)
    return mask


def compare(ours: np.ndarray, theirs: np.ndarray, mask: np.ndarray | None = None) -> dict[str, int]:
    delta = np.abs(write16(ours) - theirs.reshape(ours.shape))
    if mask is not None:
        delta = delta[mask]
    return {
        "values": int(delta.size),
        "differing": int((delta != 0).sum()),
        "max": int(delta.max()),
    }


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
        params = np.zeros((SET * SET, 2, 4), np.float32)
        g = (np.exp2(np.arange(SET) / 16.0) / 64.0).astype(np.float32)
        params[:, 0, 0], params[:, 0, 1] = 0.3, 0.6
        params[:, 0, 2] = np.tile(g, SET)
        params[:, 1, 1] = np.tile(g, SET)
        out = probe.run(levels, params.reshape(-1, 4), anisotropy=anisotropy)
        band[str(anisotropy)] = [round(float(out[0, n, 0]) * 8 * 256) for n in range(17)]
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
                ours = (sharp if filter_ == "Sharp" else hq)(probe, levels, geometry, clamp)
                mask = covered(geometry) if clamp else None
                for recording in RECORDINGS:
                    theirs = np.asarray(golden.map(recording, f"{texture_set}/user{user}").values)
                    report[f"{stem} {recording} {texture_set}/user{user}"] = compare(
                        ours, theirs, mask
                    )

    # Held out: resample-uv user 6 (field A, 256 x 256, scale 3.3), s0 HQ and s1 Sharp.
    levels = texture(fixtures.field_a())
    golden = ctx.golden("semantics/resample-uv")
    for texture_set, model in (("s0", hq), ("s1", sharp)):
        ours = model(probe, levels, HELD_OUT, False)
        for recording in RECORDINGS:
            theirs = np.asarray(golden.map(recording, f"{texture_set}/user6").values)
            report[f"held-out resample-uv {recording} {texture_set}/user6"] = compare(ours, theirs)

    # The UV arithmetic on resample-uv-minify s1 user 7 (scale 7.77, rotation 30, offset).
    levels = texture(fixtures.pattern64())
    theirs = np.asarray(ctx.golden("semantics/resample-uv-minify").map("r1", "s1/user7").values)
    ddx, ddy = gradients(MINIFY[7])
    variants = {
        "float32 affine (decision 060)": painter_uv(MINIFY[7]),
        "double, offset before scale (decision 056)": double_uv(MINIFY[7], False),
        "double, offset after rotation": double_uv(MINIFY[7], True),
    }
    for name, uv in variants.items():
        ours = probe.sample(levels, uv, ddx, ddy, bias=SHARP_BIAS)
        report[f"uv {name}"] = compare(ours, theirs)

    total = sum(
        entry["differing"] for key, entry in report.items() if key.startswith(("resample", "held"))
    )
    report["differing values over every golden map"] = total
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
