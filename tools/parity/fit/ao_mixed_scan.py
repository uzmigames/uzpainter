"""`AO_Mixed` operator fit and scan (item 2.10 of `phase3.2_unreal-ue56-packed-preset`).

The operator, fitted on the admitted AO goldens (decisions 092, 131, 321 and the operand probe
`ao-mixed-operand-probe`), r1, in float32 with one rounding per operation:

1. the AO mesh map operand a (its UNORM operand, or its float32 value) enters as
   `a' = float32(float32(1 + a) - 1)`, i.e. rounded to the absolute 2^-23 grid;
2. the AO channel operand c is the channel's layer mixed over the white AO base:
   `c = float32(fma(S, al, 1) - al)` (`layer_operand`), where the source S is the fill's value
   (bitmap operand or uniform grey), written as an L16 code first on an L16 channel (the UNORM
   write rule, `write_unorm`), and al is the layer opacity: its L16 code with ties down on an L16
   channel (`l16_opacity`), its float32 value on an L32F channel. Fills of one source compose to
   one mix whose opacity is 1 - prod(1 - opacity) (a group multiplies its children's opacity).
   With no layer, c = 1;
3. `v = float32(a' * c)`, re-composited over the white base `w = float32(float32(v - 1) + 1)`;
4. the 8-bit code `write_unorm(w, 8)`; PNG 16 writes code * 257, OpenEXR float32(code / 255).

The stored channel is not the operand: an L16 channel stores its blend quantized, an L32F
channel stores fma(S - 1, al, 1), while AO_Mixed reads the unquantized mix above. After save and
reopen (r2) Painter's AO_Mixed differs from this operator on blended sets.

`python -m tools.parity.fit.ao_mixed_scan` interprets each golden's instruction sequence and
prints, per golden, recording and texture set, the differing samples of every AO_Mixed export
(exact export values): counts only, no recorded value leaves the private store.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

from tools.parity.fit.decode import decode
from tools.parity.fit.oracle import Golden, OracleUnavailable, load
from tools.parity.schemas import REPO_ROOT
from tools.parity.store.store import locate
from tools.parity.verdict import resolve_golden

Array = npt.NDArray[Any]
F32 = np.float32
GOLDENS = (
    "ao-mixed",
    "ao-mixed-opacity",
    "ao-mixed-opacity-float",
    "ao-mixed-isolation",
    "ao-mixed-isolation-float",
    "ao-mixed-isolation-8bit",
    "ao-mixed-grid",
    "ao-mixed-grid-l32f",
    "ao-mixed-grid-l16-reopen3",
    "ao-mixed-mesh-float-product",
    "ao-mixed-precomposed-half-l32f",
    "ao-mixed-precomposed-half-y-l32f",
    "ao-mixed-operand-probe",
)
SET_COUNTS = {"grid2x2": 4, "grid4x2": 8, "grid6x4": 24}


def fma32(x: npt.ArrayLike, y: npt.ArrayLike, z: npt.ArrayLike) -> Array:
    """float32 fma of float32 operands with one rounding (x * y is exact in float64; the sum's
    rounding error decides a float64 result that falls on a float32 midpoint)."""
    xd, yd, zd = (np.asarray(v, F32).astype(np.float64) for v in (x, y, z))
    s = xd * yd
    t = s + zd
    back = t - s
    error = (s - (t - back)) + (zd - back)
    r = t.astype(F32)
    rd = r.astype(np.float64)
    above = rd > t
    lo = np.where(above, np.nextafter(r, F32(-np.inf)), r).astype(np.float64)
    hi = np.where(above, r, np.nextafter(r, F32(np.inf))).astype(np.float64)
    tie = (t == (lo + hi) / 2) & (error != 0)
    result: Array = np.where(tie & (error > 0), hi, np.where(tie & (error < 0), lo, rd)).astype(F32)
    return result


def write_unorm(v: npt.ArrayLike, bits: int) -> Array:
    """The UNORM write rule: clamp to [0, 1], j = floor(v 2^(n+4)), code = (j (2^n - 1) +
    2^(n+3) - 1) >> (n + 4)."""
    clamped = np.clip(np.nan_to_num(np.asarray(v, F32).astype(np.float64)), 0.0, 1.0)
    j = np.floor(clamped * float(1 << (bits + 4))).astype(np.int64)
    result: Array = (j * ((1 << bits) - 1) + (1 << (bits + 3)) - 1) >> (bits + 4)
    return result


def unorm_operand(code: npt.ArrayLike, bits: int) -> Array:
    result: Array = (np.asarray(code, np.float64) / ((1 << bits) - 1)).astype(F32)
    return result


def l16_opacity(opacity: float) -> F32:
    """The layer opacity as Painter applies it to an L16 channel: its L16 code, ties down."""
    scaled = opacity * 65535
    code = np.floor(scaled) if scaled % 1 == 0.5 else np.rint(scaled)
    return F32(code / 65535)


def layer_operand(source: npt.ArrayLike, opacity: float, channel_format: str) -> Array:
    """The AO channel operand of one mix of `source` over the white base (step 2 above)."""
    s = np.asarray(source, F32)
    if channel_format == "L16":
        s = unorm_operand(write_unorm(s, 16), 16)
        alpha = l16_opacity(opacity)
    elif channel_format == "L32F":
        alpha = F32(opacity)
    else:
        raise ValueError(f"AO_Mixed is fitted on L16 and L32F channels only, not {channel_format}")
    ones = np.ones_like(s)
    result: Array = (fma32(s, np.full_like(s, alpha), ones) - alpha).astype(F32)
    return result


def ao_mixed_codes(mesh: npt.ArrayLike, channel: npt.ArrayLike) -> Array:
    """8-bit AO_Mixed codes of the mesh operand and the channel operand (steps 1, 3 and 4)."""
    a = np.asarray(mesh, F32)
    a2 = ((F32(1) + a).astype(F32) - F32(1)).astype(F32)
    v = (a2 * np.asarray(channel, F32)).astype(F32)
    w = ((v - F32(1)).astype(F32) + F32(1)).astype(F32)
    return write_unorm(w, 8)


def export_values(codes: Array, container: str, bits: int) -> Array:
    """The values a file of `container` and `bits` stores for 8-bit codes."""
    if container == "exr":
        result: Array = (codes.astype(np.float64) / 255).astype(F32)
    elif bits == 16:
        result = codes * 257
    else:
        result = codes
    return result


# --- Instruction-sequence interpretation ---------------------------------------------------------


@dataclass
class Fill:
    source: tuple[str, Any] | None = None  # ("bitmap", input id) or ("colour", grey value)
    opacity: float = 1.0
    group_opacity: float = 1.0
    children: list[Fill] = field(default_factory=list)
    group: bool = False


@dataclass
class SetState:
    channel_format: str | None = None
    mesh: str | None = None
    layers: list[Fill] = field(default_factory=list)


def interpret(manifest: dict[str, Any]) -> dict[str, SetState]:
    """Each texture set's AO channel format, AO mesh map input and AO fills."""
    steps = manifest["instruction_sequence"]["steps"]
    sets = {f"s{i}": SetState() for i in range(SET_COUNTS[steps[0]["args"]["mesh"]])}
    resources: dict[int, str] = {}
    nodes: dict[int, tuple[str, Fill]] = {}
    for step in steps:
        call, args = step["call"].rsplit(".", 1)[-1], step["args"]
        targets = [args["texture_set"]] if args.get("texture_set") else list(sets)
        if call in ("add_channel", "edit_channel") and args["channel"] == "AO":
            for t in targets:
                sets[t].channel_format = args["format"]
        elif call == "import_project_resource":
            resources[step["step"]] = args["input"]
        elif call == "set_mesh_map_resource" and args["usage"] == "AO":
            for t in targets:
                sets[t].mesh = resources[args["resource_step"]]
        elif call in ("insert_fill", "insert_group"):
            node = Fill(group=call == "insert_group")
            if "inside_step" in args:
                texture_set, parent = nodes[args["inside_step"]]
                parent.children.append(node)
            elif "above_step" in args:
                texture_set = nodes[args["above_step"]][0]
                sets[texture_set].layers.append(node)
            else:
                texture_set = args.get("texture_set", "s0")
                sets[texture_set].layers.append(node)
            nodes[step["step"]] = (texture_set, node)
        elif call == "set_source" and args.get("channel") == "AO":
            fill = nodes[args["node_step"]][1]
            if "resource_step" in args:
                fill.source = ("bitmap", resources[args["resource_step"]])
            else:
                rgb = args["color"]
                if len(set(rgb)) != 1:
                    raise ValueError("AO_Mixed is fitted on grey uniform colours only")
                fill.source = ("colour", rgb[0])
        elif call == "set_opacity" and args.get("channel") == "AO":
            nodes[args["node_step"]][1].opacity = args["opacity"]
        elif (
            call == "set_blending_mode"
            and args.get("channel") == "AO"
            and args["blending_mode"] != "Normal"
        ):
            raise ValueError("AO_Mixed is fitted on Normal blending only")
    return sets


def _fills(layers: list[Fill], scale: float = 1.0) -> list[tuple[tuple[str, Any], float]]:
    out: list[tuple[tuple[str, Any], float]] = []
    for layer in layers:
        if layer.group:
            out += _fills(layer.children, scale * layer.opacity)
        elif layer.source is not None:
            out.append((layer.source, scale * layer.opacity))
    return out


def input_values(input_id: str) -> Array:
    """An authored input's first channel as float32 operands (UNORM codes / M)."""
    from tools.parity.tier0_semantics import recording_requests as rr

    _, path, generate = rr.fixture(input_id)
    file = REPO_ROOT / path
    decoded = decode(file.read_bytes() if file.is_file() or generate is None else generate())
    values = decoded.values[..., 0]
    if decoded.integer:
        return unorm_operand(values, decoded.bits)
    result: Array = values.astype(F32)
    return result


def channel_operand(state: SetState, shape: tuple[int, int]) -> Array:
    """The AO channel operand of a set; one mix of all fills, which must share one source."""
    fills = _fills(state.layers)
    if not fills:
        return np.ones(shape, F32)
    sources = {source for source, _ in fills}
    if len(sources) != 1 or state.channel_format is None:
        raise ValueError("AO_Mixed is fitted on fills of one source only")
    kind, value = fills[0][0]
    source = input_values(value) if kind == "bitmap" else np.full(shape, F32(value))
    alpha = 1.0 - float(np.prod([1.0 - opacity for _, opacity in fills]))
    return layer_operand(source, alpha, state.channel_format)


def scan(golden: Golden, recording: str) -> dict[str, list[int]]:
    """Differing samples of every AO_Mixed export per texture set (export steps in order)."""
    sets = interpret(golden.manifest)
    found: dict[str, dict[int, int]] = {}
    for output_id, output in golden.recordings[recording].outputs.items():
        if output.get("map") != "AO_Mixed" or "export_settings" not in output:
            continue
        state = sets[output["texture_set"]]
        decoded = golden.map(recording, output_id)
        recorded = decoded.values[..., 0]
        mesh = input_values(state.mesh) if state.mesh else np.ones(recorded.shape, F32)
        codes = ao_mixed_codes(mesh, channel_operand(state, recorded.shape))
        storage = output["storage_format"]
        ours = export_values(codes, storage["container"], storage["bits_per_channel"])
        if storage["container"] == "exr":
            differing = ours.view(np.uint32) != recorded.astype(F32).view(np.uint32)
        else:
            differing = ours != recorded.astype(np.int64)
        step = output["export_settings"]["step"]
        found.setdefault(output["texture_set"], {})[step] = int(np.count_nonzero(differing))
    return {t: [s[k] for k in sorted(s)] for t, s in sorted(found.items())}


def main() -> int:
    store = locate()
    report: dict[str, Any] = {}
    for name in GOLDENS:
        resolved = resolve_golden(f"tier0/semantics/{name}")
        if resolved is None:
            report[name] = "oracle_unavailable"
            continue
        try:
            golden = load(store, resolved.manifest_path)
            report[name] = {r: scan(golden, r) for r in sorted(golden.recordings)}
        except OracleUnavailable:
            report[name] = "oracle_unavailable"
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
