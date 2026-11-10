"""The recording GPU's 16-bit UNORM texture fetch: the float32 it returns for every code.

Measures, through Vulkan (`vkprobe.cpp`, the API Painter 12 renders with) on the recording GPU
(RTX 4090, driver 617.14), what an R16G16B16A16_UNORM texture returns for each of the 65 536
codes k, by three fetches:

- `load`: `Texture2D.Load` (no sampler);
- `nearest`: `SampleLevel` at the texel centre through a nearest sampler;
- `linear`: `SampleLevel` at the texel centre through a linear sampler (weight 1 on one texel).

Every code sits in each of the four channels (R holds k, G 65535 - k, B k ^ 0x5555, A the
code's image under k -> 40503 k mod 65536, a bijection), so a channel-dependent conversion would
show. Synthetic textures only; no Painter data is read.

    python -m tools.parity.vk_sampler_probe.unorm16 measure <work-dir> [<out-dir>]

`measure` writes `hw-unorm16.zlib` (by default into `src/evaluator/tables`): entry k is the
measured float32 minus float32(k / 65535) correctly rounded, in ulp, stored as the delta tables of
`src/evaluator/hwmath.h` are (2 bits per entry, delta + 2, 16 entries per little-endian word,
zlib). It refuses to write when the fetches or channels disagree, or a delta leaves [-2, 1].
`<work-dir>` receives the probe's files flat (`vkprobe.exe`, `probe.bin`, `probe.hlsl`,
`params.bin`, `out.bin`). `fetch(k)` reads the stored table back.
"""

from __future__ import annotations

import json
import struct
import subprocess
import sys
import zlib
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

REPO = Path(__file__).resolve().parents[3]
SOURCE = Path(__file__).with_name("vkprobe.cpp")
DXC = REPO / "thirdparty" / "dxc" / "bin" / "x64" / "dxcompiler.dll"
TABLES = REPO / "src" / "evaluator" / "tables"
TABLE = "hw-unorm16.zlib"
SIDE = 256  # 256 x 256 texels hold every code once per channel
CODES = 1 << 16
FILTERS = {"load": 0, "nearest": 0, "linear": 1}

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
    const float4 a = params[id.y * w + id.x];
    dst[id.xy] = a.z != 0.0f ? src.Load(int3(id.xy, 0)) : src.SampleLevel(s, a.xy, 0.0f);
}
"""


def channel_codes() -> npt.NDArray[np.uint16]:
    """The probe texture (SIDE x SIDE x 4 codes): texel (x, y) holds k = 256 y + x as above."""
    k = np.arange(CODES, dtype=np.uint32)
    codes = np.stack([k, 65535 - k, k ^ 0x5555, (k * 40503) & 0xFFFF], axis=1)
    return codes.astype(np.uint16).reshape(SIDE, SIDE, 4)


def correct(k: npt.ArrayLike) -> npt.NDArray[np.float32]:
    """float32(k / 65535) correctly rounded (the double quotient is never near a float32 tie)."""
    out: npt.NDArray[np.float32] = (np.asarray(k, np.float64) / 65535.0).astype(np.float32)
    return out


def _build(work: Path) -> Path:
    exe = work / "vkprobe.exe"
    if not exe.exists():
        third = REPO / "thirdparty"
        subprocess.run(
            [
                *("zig", "c++", "-std=c++20", "-O2", "-fms-extensions", "-w"),
                *("-I", str(third / "volk"), "-I", str(third / "vulkan-headers" / "include")),
                *("-I", str(third / "dxc" / "inc"), str(SOURCE)),
                *("-o", str(exe), "-lole32"),
            ],
            check=True,
        )
    return exe


def _run(exe: Path, work: Path, mode: str) -> npt.NDArray[np.float32]:
    """One dispatch over the probe texture; returns SIDE x SIDE x 4 float32."""
    flags = 2 | 1  # UNORM16, clamp to edge
    header = struct.pack("<8I", SIDE, SIDE, 1, SIDE, SIDE, FILTERS[mode], 1, flags)
    data = bytearray(header + struct.pack("<3f", 0.0, 0.0, 0.0))
    for row in channel_codes():
        data += row.astype("<u2").tobytes()  # 2048 bytes a row: already a multiple of 256
    ys, xs = np.mgrid[0:SIDE, 0:SIDE].astype(np.float64)
    params = np.zeros((SIDE, SIDE, 4), np.float32)
    params[..., 0] = ((xs + 0.5) / SIDE).astype(np.float32)  # exact in float32
    params[..., 1] = ((ys + 0.5) / SIDE).astype(np.float32)
    params[..., 2] = 1.0 if mode == "load" else 0.0
    (work / "probe.bin").write_bytes(bytes(data))
    (work / "probe.hlsl").write_text(KERNEL, encoding="utf-8")
    (work / "params.bin").write_bytes(np.ascontiguousarray(params, "<f4").tobytes())
    subprocess.run([str(exe), str(DXC), str(work)], check=True, capture_output=True)
    out: npt.NDArray[np.float32] = np.fromfile(work / "out.bin", "<f4").reshape(SIDE, SIDE, 4)
    return out


def _per_code(sampled: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
    """CODES x 4: the value each channel returned for code k."""
    codes = channel_codes().reshape(-1, 4).astype(np.int64)
    flat = sampled.reshape(-1, 4)
    out = np.empty((CODES, 4), np.float32)
    for c in range(4):
        out[codes[:, c], c] = flat[:, c]
    return out


def pack(deltas: npt.NDArray[np.int64]) -> bytes:
    """hwmath.h's stored delta form: delta + 2 in 2 bits, 16 per little-endian word, zlib 9."""
    entries = (deltas + 2).astype(np.uint32).reshape(-1, 16)
    shifts = np.arange(16, dtype=np.uint32) * 2
    words = np.bitwise_or.reduce(entries << shifts, axis=1).astype("<u4")
    return zlib.compress(words.tobytes(), 9)


def unpack(blob: bytes) -> npt.NDArray[np.int8]:
    words = np.frombuffer(zlib.decompress(blob), "<u4")
    shifts = np.arange(16, dtype=np.uint32) * 2
    deltas: npt.NDArray[np.int8] = (((words[:, None] >> shifts) & 3).reshape(-1)).astype(
        np.int8
    ) - 2
    return deltas


@cache
def _table() -> npt.NDArray[np.float32]:
    deltas = unpack((TABLES / TABLE).read_bytes()).astype(np.int64)
    bits = correct(np.arange(CODES)).view(np.uint32).astype(np.int64) + deltas
    out: npt.NDArray[np.float32] = bits.astype(np.uint32).view(np.float32)
    return out


def fetch(k: npt.ArrayLike) -> npt.NDArray[np.float32]:
    """The recording GPU's float32 of the 16-bit UNORM code(s) k (the measured table)."""
    out: npt.NDArray[np.float32] = _table()[np.asarray(k, np.int64)]
    return out


def measure(work: Path, out_dir: Path) -> dict[str, Any]:
    work.mkdir(parents=True, exist_ok=True)
    exe = _build(work)
    per_mode = {mode: _per_code(_run(exe, work, mode)) for mode in FILTERS}
    reference = per_mode["load"][:, 0]
    k = np.arange(CODES)
    ref_bits = correct(k).view(np.uint32).astype(np.int64)
    report: dict[str, Any] = {"codes": CODES}
    agree = True
    for mode, values in per_mode.items():
        for c in range(4):
            same = int((values[:, c].view(np.uint32) == reference.view(np.uint32)).sum())
            report[f"{mode} channel {'RGBA'[c]} equals load R"] = same
            agree &= same == CODES
    deltas = reference.view(np.uint32).astype(np.int64) - ref_bits
    values, counts = np.unique(deltas, return_counts=True)
    report["ulp from correctly rounded"] = {
        int(v): int(n) for v, n in zip(values, counts, strict=True)
    }
    report["toward zero"] = int((reference == _toward_zero(k)).sum())
    report["k * float32(1/65535)"] = int(
        (reference == (k.astype(np.float32) * np.float32(1.0 / 65535.0)).astype(np.float32)).sum()
    )
    report["monotonic"] = bool(np.all(np.diff(reference.astype(np.float64)) > 0))
    if not agree:
        report["written"] = None
        report["refused"] = "the fetches or channels disagree"
        return report
    if deltas.min() < -2 or deltas.max() > 1:
        report["written"] = None
        report["refused"] = "a delta leaves [-2, 1]"
        return report
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / TABLE).write_bytes(pack(deltas))
    report["written"] = str(out_dir / TABLE)
    return report


def _toward_zero(k: npt.NDArray[np.int64]) -> npt.NDArray[np.float32]:
    c = correct(k)
    over = c.astype(np.float64) * 65535.0 > k.astype(np.float64)
    bits = c.view(np.uint32).astype(np.int64) - over.astype(np.int64)
    out: npt.NDArray[np.float32] = bits.astype(np.uint32).view(np.float32)
    return out


def main(argv: list[str]) -> int:
    if len(argv) in (2, 3) and argv[0] == "measure":
        out = Path(argv[2]) if len(argv) == 3 else TABLES
        print(json.dumps(measure(Path(argv[1]), out), indent=1))
        return 0
    print("usage: python -m tools.parity.vk_sampler_probe.unorm16 measure <work-dir> [<out-dir>]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
