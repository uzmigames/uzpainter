"""The published fits of phase1.8_compositor-sources-projection:
`parity/semantics/colour-transfer.json` and `parity/semantics/uv-sampling.json`.

Each entry states the rule the evaluator implements (`src/evaluator/sources.h`, `projection_uv.h`,
`arith.h`), its public sources and its residuals: the evaluator's output (CPU store, built by
`zig build evaluator-tests`) against both recordings of the private Tier 0 goldens, as |delta|
statistics only (CONTRACT §6.4; nothing recorded is published). Run on the owner's machine:

    python tests/evaluator/sources_fits.py <uzp-evaluator-tests.exe> <work-dir>

writes both files; `test_compositor_sources_projection.py::test_published_fits_reproduce`
re-derives them and requires the published files to match.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import numpy as np

if __name__ == "__main__":
    # Run as a script: the repository root is the import root, and its `tests` folder is the
    # `tests` package even when another distribution installs one.
    _root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(_root))
    _tests = types.ModuleType("tests")
    _tests.__path__ = [str(_root / "tests")]
    sys.modules["tests"] = _tests

from tests.evaluator.test_compositor_tile_dag import (
    MANIFESTS,
    REPO_ROOT,
    evaluate,
    raster,
    run_case,
    spec_from_manifest,
)
from tools.parity.fit.common import (
    Context,
    document,
    entry,
    parameter,
    residual,
    source,
)
from tools.parity.fit.stats import difference
from tools.parity.schemas import load_json
from tools.parity.store.store import locate

SEMANTICS = REPO_ROOT / "parity" / "semantics"
COLOUR_FILE = "colour-transfer.json"
UV_FILE = "uv-sampling.json"
EXPORT_UNIT = "16-bit code value"
FLOAT_UNIT = "float32 value"
RAMP_SETS = 24
MESHES = REPO_ROOT / "parity" / "fixtures" / "tier0-semantics" / "meshes"
RESAMPLE_USERS = (0, 1, 2, 3, 4, 5, 7)  # user 6 minifies (field A at scale 3.3)
MINIFYING_USER = 6

SRGB = source("S-SRGB", "IEC 61966-2-1:1999 §5.2-5.3 (transfer functions)")
D3D_SRGB = source("X-D3D12", "Data conversion rules: FLOAT to SRGB, SRGB to FLOAT (UNORM_SRGB)")
D3D_UNORM = source("X-D3D12", "Data conversion rules: FLOAT to UNORM, UNORM to FLOAT")
D3D_FILTER = source(
    "X-D3D12", "Texture sampling: texel coordinate fixed-point precision, filtering"
)
PYDOC_COLOUR = source("A-PYDOC", "layerstack: ColorSpace of uniform colour and bitmap sources")
PYDOC_UV = source(
    "A-PYDOC", "layerstack: UVProjectionParams (scale, rotation, offset), FilteringMode"
)
PYDOC_WRAP = source("A-PYDOC", "layerstack: UVWrappingMode (Repeat, RepeatNone, ...)")
PYDOC_RESOURCE = source("A-PYDOC", "resource: import_project_resource; layerstack: set_source")
PBRT = source("P-PBRT", "Image texture: bilinear and point (nearest) filtering, wrap modes")
EXPORT = source("A-HELP-EXPORT", "Export settings: bit depth, padding")

BILINEAR_HARDWARE = (
    "the linear filter of a float32 texture on the GPU the goldens were recorded on (NVIDIA "
    "GeForce RTX 4090), measured by `uzp-evaluator-tests bilinear-hardware` at every 8-bit weight "
    "pair (16 777 216 samples, equal to the rule); the GPU rounds w11 ties up, which Painter's "
    "bottom-up bitmap turns into the ties down above"
)
HARDWARE = (
    "the D3D12 RGBA8_UNORM_SRGB conversions of the GPU the goldens were recorded on (NVIDIA "
    "GeForce RTX 4090), measured by `uzp-evaluator-tests srgb8-hardware` (store: the smallest "
    "float32 of each code, by bisection over clears of an sRGB render target; decode: a shader "
    "load of each code) and embedded in src/evaluator/arith.cpp"
)


# ── Comparison helpers ───────────────────────────────────────────────────────


def write16(values: np.ndarray) -> np.ndarray:
    v = np.clip(values.astype(np.float32).astype(np.float64), 0.0, 1.0)
    j = np.floor(v * (1 << 20)).astype(np.int64)
    result: np.ndarray = (j * 65535 + (1 << 19) - 1) >> 20
    return result


def srgb8_decode(exe: Path, work: Path) -> np.ndarray:
    run_case(exe, "tables", str(work / "tables"))
    document_ = json.loads((work / "tables" / "tables.json").read_text(encoding="utf-8"))
    bits = np.asarray(document_["srgb8_decode_bits"], np.uint32)
    return bits.view(np.float32).astype(np.float64)


def export16(stored: np.ndarray, fmt: str, decode: np.ndarray) -> np.ndarray:
    if fmt in ("RGB16", "L16"):
        return stored
    if fmt in ("RGB8", "L8"):
        result: np.ndarray = stored * 257
        return result
    if fmt == "sRGB8":
        return write16(decode[stored])
    raise ValueError(f"no 16-bit export rule for {fmt}")


def channel_formats(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        s["args"]["channel"]: s["args"]["format"]
        for s in manifest["instruction_sequence"]["steps"]
        if s["call"].endswith("Stack.add_channel")
    }


def pooled(
    pairs: list[tuple[np.ndarray, np.ndarray]], domains: list[np.ndarray] | None = None
) -> Any:
    """|delta| statistics over several maps of equal channel count, stacked along the rows."""
    ours = np.concatenate([p[0].reshape(-1, 1, p[0].shape[-1]) for p in pairs])
    theirs = np.concatenate([p[1].reshape(-1, 1, p[1].shape[-1]) for p in pairs])
    domain = None
    if domains is not None:
        domain = np.concatenate([d.reshape(-1, 1) for d in domains])
    return difference(ours, theirs, domain)


class Evaluations:
    """Evaluator results of Tier 0 instruction sequences (CPU store), cached per texture set."""

    def __init__(self, exe: Path, work: Path) -> None:
        self.exe = exe
        self.work = work
        self.ctx = Context(locate(), REPO_ROOT)
        self._results: dict[tuple[str, str], dict[str, Any]] = {}

    def result(
        self, golden_stem: str, texture_set: str, outputs: list[str], height: bool = False
    ) -> dict[str, Any]:
        key = (golden_stem, texture_set)
        if key not in self._results:
            manifest = load_json(MANIFESTS / "semantics" / f"{golden_stem}.json")
            workdir = self.work / golden_stem / texture_set
            spec = spec_from_manifest(manifest, texture_set, workdir, outputs)
            if height:
                spec["channels"] = [{"type": "Height", "format": "L16F"}]
                for layer in spec["layers"]:
                    layer["uid"] += 1000
            self._results[key] = evaluate(self.exe, spec, workdir, "cpu")
        return self._results[key]

    def recorded(self, golden_stem: str, recording: str, map_name: str) -> np.ndarray:
        values: np.ndarray = (
            self.ctx.golden(f"semantics/{golden_stem}").map(recording, map_name).values
        )
        return values


# ── colour-transfer.json ─────────────────────────────────────────────────────


def colour_transfer(ev: Evaluations, decode: np.ndarray) -> dict[str, Any]:
    ramps: dict[str, dict[str, list[tuple[np.ndarray, np.ndarray]]]] = {}
    for space in ("srgb", "working", "raw"):
        stem = f"colour-ramps-{space}"
        formats = channel_formats(load_json(MANIFESTS / "semantics" / f"{stem}.json"))
        users = [f"User{i}" for i in range(8)]
        for recording in ("r1", "r2"):
            for group in ("rgb16", "srgb8"):
                ramps.setdefault(group, {}).setdefault(f"{stem}|{recording}", [])
        for index in range(RAMP_SETS):
            result = ev.result(stem, f"s{index}", users)
            for user in users:
                ours = export16(raster(result, user), formats[user], decode)
                group = "rgb16" if formats[user] == "RGB16" else "srgb8"
                for recording in ("r1", "r2"):
                    theirs = ev.recorded(stem, recording, f"s{index}/{user.lower()}").astype(
                        np.int64
                    )
                    ramps[group][f"{stem}|{recording}"].append((ours, theirs.reshape(ours.shape)))

    def ramp_residuals(group: str, maps: str) -> list[dict[str, Any]]:
        out = []
        for key, pairs in ramps[group].items():
            stem, recording = key.split("|")
            out.append(
                residual(f"tier0/semantics/{stem}", maps, recording, EXPORT_UNIT, pooled(pairs))
            )
        return out

    inputs = load_json(MANIFESTS / "semantics" / "blend-inputs.json")
    input_formats = channel_formats(inputs)
    import_users = ["User0", "User1", "User2", "User3", "User4", "User6"]
    imports: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {}
    srgb_export: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {}
    for texture_set in ("s0", "s1"):
        result = ev.result("blend-inputs", texture_set, import_users)
        for user in import_users:
            fmt = input_formats[user]
            ours = export16(raster(result, user), fmt, decode)
            for recording in ("r1", "r2"):
                theirs = ev.recorded("blend-inputs", recording, f"{texture_set}/{user.lower()}")
                pair = (ours, theirs.astype(np.int64).reshape(ours.shape))
                if user != "User6":  # pool the colour maps; the grey L16 map has one channel
                    imports.setdefault(recording, []).append(pair)
                else:
                    imports.setdefault(recording + "-grey", []).append(pair)
                if fmt == "sRGB8":
                    srgb_export.setdefault(recording, []).append(pair)

    chains: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {}
    for stem, sets in (("blend-order", ("s0", "s1", "s2", "s3")), ("group-masks", ("s0", "s1"))):
        for texture_set in sets:
            result = ev.result(stem, texture_set, ["User1"])
            ours = export16(raster(result, "User1"), "sRGB8", decode)
            for recording in ("r1", "r2"):
                theirs = ev.recorded(stem, recording, f"{texture_set}/user1").astype(np.int64)
                chains.setdefault(f"{stem}|{recording}", []).append(
                    (ours, theirs.reshape(ours.shape))
                )

    heights: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {}
    for texture_set in ("s0", "s1", "s2", "s3"):
        result = ev.result("height-normal-plane-amplitudes", texture_set, ["Height"], height=True)
        ours = raster(result, "Height")
        for recording in ("r1", "r2"):
            height = ev.recorded(
                "height-normal-plane-amplitudes", recording, f"{texture_set}/height"
            ).astype(np.float64)
            height = height.reshape(ours.shape[0], ours.shape[1], -1)[..., :1]
            heights.setdefault(recording, []).append((ours, height))

    entries = [
        entry(
            "uniform-colour-rgb16",
            "Uniform colour stored on an RGB16 channel (legacy colour management)",
            "Each component v taken as linear and stored with the 16-bit UNORM write rule: v "
            "clamped to [0, 1], truncated to 20 fractional bits, nearest code with ties down "
            "(round(v 65535) on the ramp values). The colour spaces sRGB, Working and Raw give the "
            "same codes. Exported to PNG 16 unchanged.",
            [D3D_UNORM, PYDOC_COLOUR],
            [parameter("fractional_bits", 20, "fitted", "bits")],
            ramp_residuals("rgb16", "s0-s23/user0-user3"),
            notes="Evaluator output (src/evaluator/dag.cpp UniformOperand) against the 16-bit "
            "export; "
            "the 288 ramp values of each colour space pooled over 24 texture sets and four "
            "channels.",
        ),
        entry(
            "uniform-colour-srgb8-store",
            "Uniform colour stored on an sRGB8 channel (legacy colour management)",
            "Each component v taken as linear and stored as the code k with the largest float32 "
            "threshold t_k <= v (t_0 = 0): the GPU's float-to-sRGB8 conversion, which differs from "
            "round(255 encode_IEC(v)) on 2936 of the 65536 16-bit operands. The thresholds are "
            + HARDWARE
            + "; each lies within 0.15 code of decode_IEC((k - 0.5) / 255). sRGB, Working and Raw "
            "give the same codes.",
            [SRGB, D3D_SRGB, PYDOC_COLOUR],
            [
                parameter("threshold_count", 255, "fitted"),
                parameter("threshold_mantissa_bits_max", 11, "fitted", "bits"),
            ],
            ramp_residuals("srgb8", "s0-s23/user4-user7"),
            notes="Compared as the 16-bit export (entry srgb8-export), so the store and export "
            "rules "
            "are checked together; replaces the calibrated IEC rounding of srgb-transfer.json "
            "(one code off on 12 ramp values).",
        ),
        entry(
            "srgb8-export",
            "Export of an sRGB8 channel to a 16-bit PNG",
            "export = UNORM16 write rule of d_c, d_c the linear value the GPU decodes from the "
            "sRGB8 "
            "code c (" + HARDWARE + "); d_c lies within one unit in the 8th significant bit of "
            "decode_IEC(c / 255) rounded to 8 significant bits, and differs from it on 29 codes. "
            "The same d_c is the operand sRGB8 channels blend on.",
            [SRGB, D3D_SRGB, EXPORT],
            [parameter("decode_entries", 256, "fitted")],
            [
                residual(
                    "tier0/semantics/blend-inputs",
                    "s0-s1/user2-user3",
                    rec,
                    EXPORT_UNIT,
                    pooled(pairs),
                )
                for rec, pairs in sorted(srgb_export.items())
            ],
            notes="Every 16-bit code of the authored fields reaches the sRGB8 channels, so all 256 "
            "storage codes are exported; replaces the calibrated 8-significant-bit IEC decode of "
            "srgb-transfer.json (max 256 export codes off).",
        ),
        entry(
            "bitmap-import-linear",
            "16-bit bitmap source on RGB16, sRGB8, RGB8 and L16 channels",
            "A bitmap code c of an n-bit image is taken as the linear value float32(c / (2^n - 1)) "
            "whatever the colour-space tag (untagged PNG 16 here) and stored with the channel's "
            "write rule: RGB16/L16 the code itself, RGB8 the 8-bit write rule, sRGB8 the GPU "
            "float-to-sRGB8 conversion (entry uniform-colour-srgb8-store). A grey bitmap feeds the "
            "grey channel. Bound by the SHA-256 of the file bytes, decoded once per resource.",
            [D3D_UNORM, D3D_SRGB, PYDOC_RESOURCE],
            [parameter("bitmap_bits", 16, "authored", "bits")],
            [
                residual(
                    "tier0/semantics/blend-inputs",
                    "s0-s1/user0-user4" if not rec.endswith("grey") else "s0-s1/user6",
                    rec.removesuffix("-grey"),
                    EXPORT_UNIT,
                    pooled(pairs),
                )
                for rec, pairs in sorted(imports.items())
            ],
            notes="Fields A and B (s0, s1) hold every 16-bit code in their blue channel. s2 "
            "(opacity 0.5) is an unstable golden (tier0-stability.md section 4) and not compared. "
            "8-bit and sRGB-tagged bitmaps follow the same rule without a golden yet.",
        ),
        entry(
            "srgb8-stack",
            "Stacks on an sRGB8 channel: bitmaps, uniform colours, blends and groups",
            "Every layer reads the sRGB8 channel through the GPU decode d_c (entry srgb8-export), "
            "blends in float32 with the kernels of blend-modes.json and stores through the GPU "
            "conversion (entry uniform-colour-srgb8-store), after each layer and each group child.",
            [
                SRGB,
                D3D_SRGB,
                source("S-W3C-BLEND", "Section 5.1 (simple alpha compositing), 6 (blending)"),
            ],
            [],
            [
                residual(
                    f"tier0/semantics/{key.split('|')[0]}",
                    "s0-s3/user1" if key.startswith("blend") else "s0-s1/user1",
                    key.split("|")[1],
                    EXPORT_UNIT,
                    pooled(pairs),
                )
                for key, pairs in sorted(chains.items())
            ],
            notes="blend-order: fields A Normal, B Subtract 0.8 and uniform C Divide 0.6 in four "
            "orders; group-masks s0 and s1: a group without masks in its default mode and in "
            "Normal.",
        ),
        entry(
            "bitmap-height-signed",
            "Bitmap source on the Height channel",
            "On the Height channel a bitmap value t = float32(c / 65535) is stored as "
            "float32(float32(2 t) - 1), written to the channel's L16F storage toward zero; the "
            "OpenEXR export holds it unchanged. The Height channel is signed with base 0 (every "
            "template), so a fill at opacity a stores a (2 t - 1); its 16-bit PNG export is the "
            "write rule of (h + 1) / 2 (the empty channel's code 32767). A second fill in "
            "LinearDodge doubles it.",
            [D3D_UNORM, PYDOC_RESOURCE, source("S-EXR", "Half and float pixel types")],
            [parameter("scale", 2, "fitted"), parameter("offset", -1, "fitted")],
            [
                residual(
                    "tier0/semantics/height-normal-plane-amplitudes",
                    "s0-s3/height",
                    rec,
                    FLOAT_UNIT,
                    pooled(pairs),
                )
                for rec, pairs in sorted(heights.items())
            ],
            notes="s0-s2: opacity 1, 0.5, 0.25; s3: a second fill in LinearDodge. The PNG export "
            "of a non-zero Height and the EXR export of the empty channel are not recorded.",
        ),
        entry(
            "uniform-colour-height-and-8-bit-bitmaps",
            "Uniform colours on Height, 8-bit and sRGB-tagged bitmaps, OCIO colour management",
            "Not observed. Uniform colours on Height are stored like any channel value (no "
            "remap); 8-bit and sRGB-tagged bitmaps follow bitmap-import-linear; an OCIO project "
            "fails with evaluator:unsupported_source.",
            [PYDOC_COLOUR, source("S-OCIO", "Colour transforms")],
            [],
            [],
            gap=True,
        ),
    ]
    corpus = [
        "tier0/semantics/colour-ramps-srgb",
        "tier0/semantics/colour-ramps-working",
        "tier0/semantics/colour-ramps-raw",
        "tier0/semantics/blend-inputs",
        "tier0/semantics/blend-order",
        "tier0/semantics/group-masks",
        "tier0/semantics/height-normal-plane-amplitudes",
    ]
    return document(
        "colour-transfer",
        "Colour transfer of fill sources (04 section 1, 4; task phase1.8_compositor-sources-"
        "projection): uniform colours and bitmaps on every channel format under legacy colour "
        "management, as the evaluator implements them, with residuals of the evaluator's output "
        "against both recordings (r1 same session, r2 after save and reopen). Supersedes the "
        "calibrated sRGB8 entries of srgb-transfer.json.",
        corpus,
        entries,
    )


# ── uv-sampling.json ─────────────────────────────────────────────────────────

TRANSFORM = (
    "Output texel (i, j) of the W x H set at u = (i + 0.5)/W, v = 1 - (j + 0.5)/H; "
    "(a, b) = ((u - 0.5 - o_u) s_u, (v - 0.5 - o_v) s_v) (the offset precedes the scale and the "
    "rotation, decision 056); u' = (cos r a + sin r b) + 0.5, v' = (-sin r a + cos r b) + 0.5, "
    "in double; bitmap texel coordinates "
    "x = u' w - 0.5, y = (1 - v') h - 0.5 (row 0 on top, centres at integers). "
)


def uv_sampling(ev: Evaluations, exe: Path) -> dict[str, Any]:
    stem = "resample-uv"
    users = [f"User{u}" for u in range(8)]
    per_set: dict[tuple[str, str], list[tuple[np.ndarray, np.ndarray]]] = {}
    for texture_set in ("s0", "s1", "s2", "s3"):
        wanted = users if texture_set == "s2" else [f"User{u}" for u in RESAMPLE_USERS]
        result = ev.result(stem, texture_set, wanted)
        for user in wanted:
            ours = raster(result, user)
            for recording in ("r1", "r2"):
                theirs = ev.recorded(stem, recording, f"{texture_set}/{user.lower()}").astype(
                    np.int64
                )
                per_set.setdefault((texture_set, recording), []).append(
                    (ours, theirs.reshape(ours.shape))
                )

    def set_residuals(texture_set: str, maps: str) -> list[dict[str, Any]]:
        return [
            residual(
                f"tier0/semantics/{stem}",
                maps,
                rec,
                "16-bit code value",
                pooled(per_set[(texture_set, rec)]),
            )
            for rec in ("r1", "r2")
        ]

    islands: list[dict[str, Any]] = []
    for golden_stem, texture_set, mesh in (
        ("height-normal-sphere", "uzp_sphere", "sphere"),
        ("height-normal-bevelled-cube", "uzp_bevelled_cube", "bevelled-cube"),
    ):
        coverage_dir = ev.work / "coverage" / mesh
        run_case(
            exe,
            "uv-coverage",
            str(coverage_dir),
            str(MESHES / f"{mesh}.obj"),
            "256",
            needs_gpu=True,
        )
        covered = np.fromfile(coverage_dir / "coverage.bin", np.uint8).reshape(256, 256) == 1
        result = ev.result(golden_stem, texture_set, ["Height"], height=True)
        ours = raster(result, "Height")
        for recording in ("r1", "r2"):
            theirs = ev.recorded(golden_stem, recording, f"{texture_set}/height").astype(np.float64)
            theirs = theirs.reshape(ours.shape[0], ours.shape[1], -1)[..., :1]
            islands.append(
                residual(
                    f"tier0/semantics/{golden_stem}",
                    f"{texture_set}/height covered",
                    recording,
                    FLOAT_UNIT,
                    pooled([(ours, theirs)], [covered]),
                )
            )

    bilinear = (
        TRANSFORM
        + "Fixed point: X = floor(256 x + 0.5), x0 = X >> 8, fx = X & 255 (same for y); weights "
        "w11 = (fx fy + 127) >> 8, w10 = fx - w11, w01 = fy - w11, w00 = 256 - fx - fy + w11 on "
        "the taps (x0, y0), (x0 + 1, y0), (x0, y0 + 1), (x0 + 1, y0 + 1); texels t = "
        "float32(c / 65535); with E the binary exponent of the largest texel of non-zero weight "
        "(in [2^(E-1), 2^E)), operands floor(t 2^(28 - E)); value = their weighted sum times "
        "2^(E - 36), rounded to the nearest float32 with ties up (a texel weighed 256 is "
        "unchanged), stored with the channel's write rule. This is " + BILINEAR_HARDWARE + ". "
    )
    entries = [
        entry(
            "uv-nearest",
            "UV projection with the Nearest filter (Repeat), any scale",
            TRANSFORM + "The texel (floor(x + 0.5) mod w, floor(y + 0.5) mod h); its value "
            "float32(c / M) stored with the channel's write rule (the code itself at equal depth).",
            [PYDOC_UV, PYDOC_WRAP, PBRT],
            [parameter("uv_pivot", [0.5, 0.5], "fitted")],
            set_residuals("s2", "s2/user0-user7"),
        ),
        entry(
            "uv-bilinear-repeat",
            "UV projection with BilinearHQ and BilinearSharp (Repeat), magnification and 1:1",
            bilinear + "Repeat: tap indices modulo the bitmap size. BilinearHQ and BilinearSharp "
            "are identical here.",
            [PYDOC_UV, PYDOC_WRAP, D3D_FILTER, PBRT],
            [
                parameter("subtexel_bits", 8, "fitted", "bits"),
                parameter("weight_bits", 8, "fitted", "bits"),
                parameter("operand_bits", 28, "fitted", "bits"),
                parameter("uv_pivot", [0.5, 0.5], "fitted"),
            ],
            set_residuals("s0", "s0/user0-5,7") + set_residuals("s1", "s1/user0-5,7"),
            notes="The filter's 28-bit operands are what Painter's values need: with the float32 "
            "texels summed exactly one value of s0 and s1 user2 (scale 1.37 x 2.11, texel "
            "(175, 18), green) is one code high, its sum lying 2^-9.7 ulp above a float32 "
            "midpoint where Painter rounds it down; operands of 27 bits break 16 values of "
            "s0, s1 and s3 (3 867 033 values), 29 to 33 bits keep the miss; truncating the "
            "sum or each product, round-toward-zero and float32 orders of the sum (at least "
            "1630) do not fit. The GPU measurement fixes the rest of the rule (the exponent "
            "of the largest weighed texel, ties up), which the corpus cannot separate (task "
            "phase1.9_compositor-resample-gaps). Replaces the 20-bit integer value rule of "
            "resampling.json (about 280 values per map one code off).",
        ),
        entry(
            "uv-bilinear-repeatnone",
            "UV projection with BilinearHQ and RepeatNone, magnification and 1:1",
            bilinear + "RepeatNone: tap indices clamped to the bitmap; texels with u' or v' "
            "outside [0, 1) are not covered and keep the value below the fill (a coverage plane in "
            "the projected tile). RepeatHorizontally / RepeatVertically repeat one axis and treat "
            "the other as RepeatNone (not observed).",
            [PYDOC_UV, PYDOC_WRAP, D3D_FILTER, PBRT],
            [
                parameter("subtexel_bits", 8, "fitted", "bits"),
                parameter("operand_bits", 28, "fitted", "bits"),
            ],
            set_residuals("s3", "s3/user0-5,7"),
        ),
        entry(
            "uv-bilinear-minification",
            "BilinearHQ and BilinearSharp under minification",
            "Not reproduced. Painter samples a minified bitmap with the recording GPU's "
            "texture unit through Vulkan: a float32 texture with a box mip chain and an "
            "anisotropic sampler whose trilinear band is that of maxAnisotropy 4 to 7 "
            "(t = 1.75 f); BilinearSharp is one sample at LOD bias -1.5, BilinearHQ a 3 x 3 "
            "supersample at 1/3 output-texel steps with the gradients divided by 3, tent weights "
            "(the (+1/3, +1/3) sample replaced by the centre) blended in by "
            "min(footprint - 1, 1). Measured on that GPU this reproduces resample-uv-minify, "
            "resample-uv-impulse and the held-out resample-uv user 6 to one code, not exactly "
            "(the hardware's float coordinates, anisotropic probes and blend arithmetic are not "
            "modelled bit for bit; decision 056). The evaluator refuses a bilinear projection "
            "whose footprint exceeds one texel with evaluator:unsupported_source.",
            [PYDOC_UV, D3D_FILTER],
            [],
            [],
            gap=True,
        ),
        entry(
            "uv-island-edges",
            "UV projections on meshes: island edges",
            "The Fill and UV projections evaluate every texel of the UV tile, inside and outside "
            "the islands. On every texel whose centre a triangle of the texture set covers (the UV "
            "raster of src/render/uv_raster.h on the imported texturing mesh) the channel equals "
            "the export; the texels outside the islands are export padding (padding infinite), "
            "not the stack's value.",
            [PYDOC_UV, EXPORT, D3D_FILTER],
            [],
            islands,
            notes="Height ramps (bitmap-height-signed of colour-transfer.json) on the 32 x 16 UV "
            "sphere (61440 covered texels of 65536) and the bevelled cube atlas (53336).",
        ),
    ]
    corpus = [
        "tier0/semantics/resample-uv",
        "tier0/semantics/resample-uv-minify",
        "tier0/semantics/resample-uv-impulse",
        "tier0/semantics/height-normal-sphere",
        "tier0/semantics/height-normal-bevelled-cube",
    ]
    return document(
        "uv-sampling",
        "Fill and UV projections of bitmap sources (04 section 4, 5; task phase1.8_compositor-"
        "sources-projection): UV transform, Nearest and bilinear filters in the evaluator's "
        "arithmetic, wrap modes and island edges, with residuals of the evaluator's output "
        "against both recordings. Supersedes resampling.json for the evaluator.",
        corpus,
        entries,
    )


def build(exe: Path, work: Path) -> dict[str, dict[str, Any]]:
    ev = Evaluations(exe, work)
    decode = srgb8_decode(exe, work)
    return {COLOUR_FILE: colour_transfer(ev, decode), UV_FILE: uv_sampling(ev, exe)}


def serialise(doc: dict[str, Any]) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python tests/evaluator/sources_fits.py <uzp-evaluator-tests.exe> <work-dir>")
        return 2
    documents = build(Path(argv[0]), Path(argv[1]))
    for name, doc in documents.items():
        (SEMANTICS / name).write_text(serialise(doc), encoding="utf-8", newline="\n")
        print(f"wrote parity/semantics/{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
