"""`tools/parity/fit/ao_mixed_scan.py` on synthetic operands (no store)."""

from __future__ import annotations

import numpy as np

from tools.parity.fit.ao_mixed_scan import (
    Fill,
    SetState,
    _fills,
    ao_mixed_codes,
    export_values,
    fma32,
    interpret,
    l16_opacity,
    layer_operand,
    write_unorm,
)

F32 = np.float32


def step(n: int) -> F32:
    return F32(n / 4096)


def below(x: F32, k: int) -> F32:
    return F32(np.asarray(x, F32).view(np.int32).__sub__(k).astype(np.int32).view(F32))


def test_write_rule_truncates_to_n_plus_4_bits_with_ties_down() -> None:
    assert write_unorm([0.0, 1.0, 2.0, -1.0], 8).tolist() == [0, 255, 255, 0]
    assert write_unorm([0.5], 8).tolist() == [127]  # j = 2048 -> 127.5, a tie, down
    assert write_unorm([step(1551)], 8).tolist() == [97]
    assert write_unorm([below(step(1551), 1)], 8).tolist() == [96]


def test_mesh_operand_rounds_to_the_2_pow_minus_23_grid() -> None:
    # Below 0.5 a step of 2^-24 is a tie on the 2^-23 grid: to even, here the 12-bit step.
    one = np.ones(1, F32)
    assert ao_mixed_codes([below(step(1551), 2)], one).tolist() == [97]
    assert ao_mixed_codes([below(step(1551), 3)], one).tolist() == [96]
    # The channel operand is not rounded there: a channel value 2^-24 below the step stays below.
    assert ao_mixed_codes(one, [below(step(1551), 2)]).tolist() == [96]


def test_product_is_recomposited_over_white_at_2_pow_minus_24() -> None:
    # 0.75 * x below 0.5: float32(v - 1) + 1 rounds v to the 2^-24 grid.
    a, c = np.array([F32(0.75)]), np.array([F32(1551 / 4096 / 0.75)])
    v = F32(a[0] * c[0])
    expected = write_unorm([F32(F32(v - F32(1)) + F32(1))], 8)
    assert ao_mixed_codes(a, c).tolist() == expected.tolist()


def test_layer_operand_mixes_over_white_with_the_channel_opacity() -> None:
    s = np.array([F32(0.25)])
    assert l16_opacity(0.5) == F32(32767 / 65535)
    assert l16_opacity(0.75) == F32(49151 / 65535)
    alpha = l16_opacity(0.5)
    s16 = np.array([F32(write_unorm(s, 16)[0] / 65535)])
    assert layer_operand(s, 0.5, "L16")[0] == F32(fma32(s16, [alpha], [1.0])[0] - alpha)
    assert layer_operand(s, 0.75, "L32F")[0] == F32(fma32(s, [0.75], [1.0])[0] - F32(0.75))
    # Opacity 1 rounds the source to the 2^-23 grid; an L16 channel writes it as a code first.
    tiny = np.array([F32(2.0**-30)])
    assert layer_operand(tiny, 1.0, "L32F")[0] == 0
    assert layer_operand(np.array([F32(0.3)]), 1.0, "L16")[0] == F32(
        F32(1 + F32(write_unorm([0.3], 16)[0] / 65535)) - 1
    )


def test_fma32_rounds_once() -> None:
    x, y, z = F32(1 + 2.0**-23), F32(1 - 2.0**-24), F32(-1)
    exact = float(x) * float(y) + float(z)
    assert fma32([x], [y], [z])[0] == F32(exact)


def test_export_values_per_container() -> None:
    codes = np.array([0, 128, 255])
    assert export_values(codes, "png", 8).tolist() == [0, 128, 255]
    assert export_values(codes, "png", 16).tolist() == [0, 128 * 257, 65535]
    assert export_values(codes, "exr", 32).tolist() == [0.0, F32(128 / 255), 1.0]


def test_interpreter_reads_sets_meshes_fills_and_groups() -> None:
    steps = [
        {"step": 1, "call": "x.project.create", "args": {"mesh": "grid2x2"}},
        {"step": 2, "call": "x.Stack.add_channel", "args": {"channel": "AO", "format": "L16"}},
        {"step": 3, "call": "x.import_project_resource", "args": {"input": "grey-a"}},
        {"step": 4, "call": "x.set_mesh_map_resource", "args": {"usage": "AO", "resource_step": 3}},
        {"step": 5, "call": "x.insert_group", "args": {"position": "top", "texture_set": "s1"}},
        {
            "step": 6,
            "call": "x.set_opacity",
            "args": {"node_step": 5, "opacity": 0.5, "channel": "AO"},
        },
        {"step": 7, "call": "x.insert_fill", "args": {"inside_step": 5, "stack": "Substack"}},
        {
            "step": 8,
            "call": "x.set_source",
            "args": {"node_step": 7, "channel": "AO", "color": [0.3, 0.3, 0.3]},
        },
        {
            "step": 9,
            "call": "x.set_opacity",
            "args": {"node_step": 7, "opacity": 0.5, "channel": "AO"},
        },
    ]
    sets = interpret({"instruction_sequence": {"steps": steps}})
    assert set(sets) == {"s0", "s1", "s2", "s3"}
    assert all(s.mesh == "grey-a" and s.channel_format == "L16" for s in sets.values())
    assert _fills(sets["s0"].layers) == []
    assert _fills(sets["s1"].layers) == [(("colour", 0.3), 0.25)]
    assert _fills(SetState(layers=[Fill(("colour", 1.0), 0.5)]).layers) == [(("colour", 1.0), 0.5)]
