"""The native OCIO sRGB decode table is generated from the facade's (decision 212)."""

from __future__ import annotations

from tools.parity import ocio_srgb_table


def test_the_native_table_is_the_facades() -> None:
    """`src/evaluator/ocio_srgb_table.inc` is what `tools/parity/ocio_srgb_table.py` renders from
    `python/uzpainter_facade/ocio_srgb.py`: the 256 codes and 193 other recorded components of
    decision 202, so no copy is kept by hand."""
    assert ocio_srgb_table.TARGET.read_text(encoding="utf-8") == ocio_srgb_table.render(), (
        "stale: run python tools/parity/ocio_srgb_table.py"
    )
    assert len(ocio_srgb_table.entries()) == 449
