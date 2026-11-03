"""The native OCIO sRGB decode table is generated from the facade's (decision 212)."""

from __future__ import annotations

from tools.parity import ocio_srgb_part5 as part5
from tools.parity import ocio_srgb_table

# `python -m tools.parity.ocio_srgb_part5 qualify` on the admitted part 5 (decision 202).
PART5_NEW_PAIRS_SHA256 = "4104b941aabf8ef3adbb97ed14f7510c5f4d5c47a4e55abeca8003eec06e17f5"


def test_the_native_table_is_the_facades() -> None:
    """`src/evaluator/ocio_srgb_table.inc` is what `tools/parity/ocio_srgb_table.py` renders from
    `python/uzpainter_facade/ocio_srgb.py`: the 256 codes and 242 other recorded components of
    decision 202, so no copy is kept by hand."""
    assert ocio_srgb_table.TARGET.read_text(encoding="utf-8") == ocio_srgb_table.render(), (
        "stale: run python tools/parity/ocio_srgb_table.py"
    )
    assert len(ocio_srgb_table.entries()) == 498


def test_the_frozen_449_stay_and_part_5_adds_the_qualified_49() -> None:
    """Decision 202's part-5 amendment: without the 49 appended components the table is the frozen
    449-entry baseline, pair for pair, and the 49 are the qualified pairs, by digest only."""
    table = ocio_srgb_table.entries()
    appended = ocio_srgb_table.load_source().RECORDED[193:]
    new = {ocio_srgb_table._bits(x) for x, _ in appended}
    assert len(appended) == len(new) == part5.NEW
    assert part5.keys_digest(new) == part5.NEW_SHA256
    assert part5.pairs_digest({k: table[k] for k in new}) == PART5_NEW_PAIRS_SHA256
    baseline = {k: v for k, v in table.items() if k not in new}
    assert len(baseline) == part5.BASELINE_ENTRIES
    assert part5.pairs_digest(baseline) == part5.BASELINE_SHA256
