"""The material channel survey's diagnostic candidates on authored values (no Painter data)."""

from __future__ import annotations

import numpy as np

from tools.parity.fit.material_channel_survey import channel_report, tz, unorm8_of_16


def test_l8_candidate_truncates_to_12_bits_before_the_8_bit_store() -> None:
    codes = np.array([0, 15, 16, 32769, 32779, 50255, 50256, 65535])
    stored = unorm8_of_16(codes / 65535)
    assert stored.tolist() == [0, 0, 0, 127, 127, 195, 196, 255]


def test_reports_count_the_misses_of_each_candidate() -> None:
    x = (np.arange(16, dtype=np.float64) * 4096 / 65535).reshape(4, 4)
    stored = unorm8_of_16(x).astype(np.float64)
    exported = (stored / 255).astype(np.float32).astype(np.float64)
    (line,) = channel_report("SpecularRoughness", x, np.stack([x] * 3, -1), exported)
    assert "12-bit rule misses 0" in line and "export code/255 True" in line

    height = np.full((2, 2), 0.75)
    (line,) = channel_report("Height", height, np.stack([height] * 3, -1), tz(np.full((2, 2), 0.5)))
    assert line == "tz16(2x - 1) misses 0 of 4"

    rgb = np.array([[[0.25, 0.25, 1.0], [0.75, 0.5, 1.0]]])
    normal = np.stack([tz(rgb[..., 0]), tz(1 - rgb[..., 1]), tz(rgb[..., 2])], -1)
    (line,) = channel_report("Normal", rgb[..., 0], rgb, normal)
    assert line.startswith("(tz16 r, tz16(1 - g), tz16 b) misses [0, 0, 0]")
