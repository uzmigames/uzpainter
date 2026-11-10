"""The grunge goldens of `phase3.2_proc-grunge-families` (2026-11-10).

**Diagnostic** (never a calibration or held-out case of any batch): every inventoried grunge
(`docs/analysis/proc-grunge-families/01-asset-inventory.md`) at Painter's default parameters on
the authored plane, at seeds 1 and 2 at 1024 and at seed 1 at 2048. Every case sets its seed, so
each case's readback describes every `Property` of the source with its metadata (item 2.2). The
goldens record the separating evidence of item 2.4: what the seed changes, whether the
2048 output is the 1024 one at a finer sampling, and r1 against r2.
"""

from __future__ import annotations

from tools.parity.proc_grunges.requests import GRUNGE_URLS, Golden, GrungeCase

ASSETS = tuple(GRUNGE_URLS)
PER_GOLDEN_1024 = 4  # two cases per asset, eight User channels


def chunks(items: tuple[str, ...], size: int) -> list[tuple[str, ...]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def diagnostic_goldens() -> tuple[Golden, ...]:
    low = tuple(
        Golden(
            "diagnostic",
            f"seeds-{index + 1}",
            1024,
            tuple(
                GrungeCase(f"{asset}-seed-{seed}", asset, seed=seed)
                for asset in assets
                for seed in (1, 2)
            ),
        )
        for index, assets in enumerate(chunks(ASSETS, PER_GOLDEN_1024))
    )
    high = tuple(
        Golden(
            "diagnostic",
            f"seed-1-{index + 1}",
            2048,
            tuple(GrungeCase(f"{asset}-seed-1", asset, seed=1) for asset in assets),
        )
        for index, assets in enumerate(chunks(ASSETS, 8))
    )
    return (*low, *high)


def goldens() -> tuple[Golden, ...]:
    return diagnostic_goldens()
