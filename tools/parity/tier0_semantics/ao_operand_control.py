"""Authored controls separating AO mesh storage from multiplication and output conversion."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from tools.parity.recorder import vocabulary as ps
from tools.parity.tier0_semantics.corpus import Golden, start
from tools.parity.tier0_semantics.request_fixtures import exr_float_y

MESH_VALUES = "ao-mesh-code-y"
PRODUCT_VALUES = "ao-mesh-product-half-y"


def operands() -> tuple[npt.NDArray[np.float32], npt.NDArray[np.float32]]:
    """Every code pair, with the scalar opacity-half operand authored independently."""
    codes = (np.arange(256, dtype=np.float64) / 255).astype(np.float32)
    delta = codes - np.float32(1)
    channel = (delta.astype(np.float64) * 0.5 + 1).astype(np.float32)
    return np.broadcast_to(codes[None, :], (256, 256)), np.broadcast_to(
        channel[:, None], (256, 256)
    )


def mesh_values() -> bytes:
    """Exact float32 code/255 mesh values, without integer-image normalization."""
    mesh, _ = operands()
    return exr_float_y(mesh)


def product_values() -> bytes:
    """One correctly rounded float32 product, supplied as a mesh map rather than a layer."""
    mesh, channel = operands()
    return exr_float_y(mesh * channel)


def request() -> Golden:
    from tools.parity.tier0_semantics import recording_requests as rr

    s = start("grid2x2")
    s.channels((("AO", "L32F"),))
    inputs = ["grey-a", "ao-precomposed-half-y", MESH_VALUES, PRODUCT_VALUES]
    resources = s.imports(*inputs)
    for index, mesh in enumerate(("grey-a", MESH_VALUES, PRODUCT_VALUES, PRODUCT_VALUES)):
        s.add(
            ps.SET_MESH_MAP,
            texture_set=f"s{index}",
            usage="AO",
            resource_step=resources[mesh],
        )
    for index in (0, 1):
        node = s.fill(["AO"], texture_set=f"s{index}")
        s.bitmap(node, "AO", resources["ao-precomposed-half-y"])
        rr.projection(s, node, "Nearest", "RepeatNone")
        s.blend(node, "AO", "Normal", 1.0)
    # s2 keeps the empty AO base. s3 controls the same 1.0 value with an explicit fill.
    node = s.fill(["AO"], texture_set="s3")
    s.colour(node, "AO", [1.0, 1.0, 1.0], "Raw")
    s.blend(node, "AO", "Normal", 1.0)
    maps = [
        "virtualMap/AO_Mixed:L",
        "documentMap/ambientOcclusion:L",
        "meshMap/ambient_occlusion:L",
    ]
    rr.export(s, maps, rr.PNG8, "passthrough")
    rr.export(s, maps, rr.EXR32F, "passthrough")
    return Golden(
        "ao-mixed-mesh-float-product",
        "tier0/ao-mixed/operator",
        "Decision 131 mesh-storage and multiplication control, Legacy, AO L32F, 256 px. "
        "s0 binds grey-a PNG16 code x*257 as AO mesh; s1 binds authored Y/FLOAT "
        "f32(x/255). Both use the same scalar precomposed-half Y/FLOAT channel at opacity "
        "1, Nearest, identity UV, RepeatNone. s2/s3 bind an authored Y/FLOAT mesh holding "
        "f32(f32(x/255)*fma(f32(f32(y/255)-1),0.5,1)); s2 has no layer, s3 explicit "
        "Raw white fill at opacity 1. Product enters through the mesh, avoiding the "
        "subtraction/addition of a layer blend at values below 0.5. All inputs are "
        "authored formulas, never recorded pixels. Gate s0/s1 comparisons on bit-identical "
        "channel and mesh EXR exports; gate s2/s3 on mesh exports equal to the authored "
        "float32 product AND f32(mesh_s1_EXR * channel_s1_EXR), with channel exports exactly "
        "1. s0/s1 compares format/import/sampling paths, not normalization alone. "
        "Compare every texel, both immediate "
        "repeats and Full save/reopen. If an EXR mesh is quantized on import, report that "
        "failed precondition rather than inferring multiplication or output conversion. "
        "The product-plus-one controls predict equality only for an operator that consumes "
        "the exported operands with a float32 product and common quantizer. Agreement alone "
        "does not establish that operator. Export AO_Mixed/channel/mesh twice as PNG8 and "
        "twice as EXR32F, passthrough, no dithering. No production acceptance is implied.",
        "grid2x2",
        ["grid2x2", *inputs],
        s,
    )
