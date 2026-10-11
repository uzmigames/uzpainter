"""`parity/reports/phase0/tier0-stability.md`: oracle stability, published fits and the
settlement of `04-layer-stack-and-compositing.md` §9. Numbers and hashes only.

Settlement rule: an item is settled only when at least one published fit covers it, every
covering entry is `exact` (zero residual against every listed comparison), every golden of the
item is stable and no part of the item was moved to another task. Anything else is an open item
with its reasons.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tools.parity.fit.stability import STABLE, GoldenStability, channel_types

ITEM_BLEND = "Blend formulas and spaces"
ITEM_QUANTISATION = "quantisation points"
ITEM_BASE = "stack base values"
ITEM_MASK = "mask precision (8 vs 16 bit)"
ITEM_GROUP = "group `Normal`/`PassThrough` semantics with masks"
ITEM_EFFECT = "content-effect order"
ITEM_LEVELS = "levels clamp behaviour"
ITEM_RESAMPLE = "the `BilinearHQ` kernel"
ITEM_HEIGHT = "height→normal methods and strength scaling"
ITEM_AO = "the `AO_Mixed` operator"
ITEM_API = "API readback rules (set→get, mask `None`, insertion errors)"
UI_CASES = "phase0.7_tier0-semantics-ui-cases"
MASK_FIT = "phase1.11_compositor-mask-effects (`masks-levels.json`)"
TILE_DAG = "phase1.5_compositor-tile-dag"

EntryFilter = Callable[[str], bool]


@dataclass(frozen=True)
class Item:
    name: str
    golden_prefixes: tuple[str, ...]  # golden ids or domains this item is decided by
    fits: tuple[tuple[str, EntryFilter], ...]  # (semantics file, entry-id filter)
    moved: str | None = None  # the part of the item another task owns
    owner: str | None = None  # where the item is fitted or stated when this task has no fit


def _all(_: str) -> bool:
    return True


ITEMS: tuple[Item, ...] = (
    Item(
        ITEM_BLEND,
        (
            "tier0/blend/modes",
            "tier0/blend/normal-channel",
            "tier0/blend/inputs",
            "tier0/blend/order",
            "tier0/colour/uniform-ramps",
        ),
        (("blend-modes.json", lambda e: e != "blend-passthrough"), ("srgb-transfer.json", _all)),
        "`PassThrough` (group-only mode, not settable through the documented API on Painter "
        f"12.1.0): {UI_CASES}",
    ),
    Item(
        ITEM_QUANTISATION,
        ("tier0/quantisation/thirds", "tier0/colour/uniform-ramps"),
        (("evaluator-profile.json", lambda e: e == "evaluator-profile"),),
    ),
    Item(ITEM_BASE, ("tier0/stack/base-values",), (), owner=f"templates: {TILE_DAG}"),
    Item(ITEM_MASK, ("tier0/mask/precision",), (), owner=MASK_FIT),
    Item(
        ITEM_GROUP,
        ("tier0/group/masks",),
        (),
        f"`PassThrough` groups with masks: {UI_CASES}",
        MASK_FIT,
    ),
    Item(ITEM_EFFECT, ("tier0/effects/order",), (), owner=MASK_FIT),
    Item(ITEM_LEVELS, ("tier0/levels/clamp",), (), owner=MASK_FIT),
    Item(
        ITEM_RESAMPLE, ("tier0/resample/uv",), (("resampling.json", lambda e: "bilinearhq" in e),)
    ),
    Item(
        ITEM_HEIGHT,
        ("tier0/height-normal/default-method",),
        (("height-to-normal.json", lambda e: "default" in e),),
        f"the second height→normal method and the strength sweep: {UI_CASES}",
    ),
    Item(ITEM_AO, ("tier0/ao-mixed/operator",), (("ao-mixed.json", _all),)),
    Item(
        ITEM_API,
        ("tier0/api-probes/",),
        (),
        owner="readback rules, no formula: stated by phase0.6_tier0-api-probes "
        "(`parity/RECORDER.md` §9)",
    ),
)


def _fmt(value: float) -> str:
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.6g}"


def _goldens_of(
    item: Item, stability: list[GoldenStability], domains: dict[str, str]
) -> list[GoldenStability]:
    chosen = []
    for golden in stability:
        domain = domains.get(golden.golden_id, "")
        if any(
            domain == p or golden.golden_id.startswith(p) or golden.golden_id == p
            for p in item.golden_prefixes
        ):
            chosen.append(golden)
    return chosen


@dataclass
class Settlement:
    item: Item
    goldens: list[GoldenStability]
    entries: list[tuple[str, dict[str, Any]]]
    reasons: list[str]

    @property
    def settled(self) -> bool:
        return not self.reasons


def settle(
    stability: list[GoldenStability], domains: dict[str, str], documents: dict[str, dict[str, Any]]
) -> list[Settlement]:
    result = []
    for item in ITEMS:
        goldens = _goldens_of(item, stability, domains)
        entries = [
            (file, e)
            for file, keep in item.fits
            for e in documents.get(file, {}).get("entries", [])
            if keep(e["entry_id"])
        ]
        reasons = []
        if not item.fits:
            reasons.append(f"no fit in this task's scope; {item.owner}")
        elif not entries:
            reasons.append("fit file missing or without a covering entry")
        open_entries = [e["entry_id"] for _, e in entries if e["status"] != "exact"]
        if open_entries:
            reasons.append(
                f"{len(open_entries)} of {len(entries)} covering entries not exact: "
                + ", ".join(open_entries)
            )
        unstable = [g.golden_id.rsplit("/", 1)[-1] for g in goldens if g.classification != STABLE]
        if unstable:
            reasons.append("unstable goldens: " + ", ".join(unstable))
        if item.moved:
            reasons.append("moved: " + item.moved)
        result.append(Settlement(item, goldens, entries, reasons))
    return result


def _worst(entries: list[tuple[str, dict[str, Any]]]) -> str:
    worst: tuple[float, str, str, int] | None = None
    for _, e in entries:
        for r in e["residuals"]:
            d = r["difference"]
            if d["differing"] and (worst is None or d["differing"] / d["total"] > worst[0]):
                worst = (
                    d["differing"] / d["total"],
                    e["entry_id"],
                    f"{_fmt(d['max'])} {r['unit']}",
                    d["differing"],
                )
    if not entries:
        return "—"
    if worst is None:
        return "0 (every covering residual is zero)"
    return f"{worst[1]}: max \\|Δ\\| {worst[2]}, {worst[3]} differing values"


def render(
    stability: list[GoldenStability],
    domains: dict[str, str],
    documents: dict[str, dict[str, Any]],
    run: dict[str, str],
) -> str:
    lines: list[str] = []
    add = lines.append
    unstable_goldens = [g for g in stability if g.classification != STABLE]
    add("# Tier 0 oracle stability and fits (phase0.7_tier0-stability-fits)")
    add("")
    add(
        "Task `phase0.7_tier0-stability-fits` (child of `phase0.8_tier0-goldens`, D3/D5/D9/D13). "
        "Numbers and hashes only: every recorded output stays in the owner's private store; the "
        "fitted formulas are published under `parity/semantics/`. Generated by "
        "`python -m tools.parity.fit run` (`parity/FITS.md`); do not edit by hand."
    )
    add("")
    add(
        "Comparison run: "
        + ", ".join(f"{k} {v}" for k, v in run.items())
        + ". Rules: `parity/CONTRACT.md` §2, §3.1-§3.2 (native decoded values; classification by "
        "measured storage format) and `14-parity-testing.md` §1, §5."
    )
    add("")
    add("## 1. Summary")
    add("")
    maps = sum(len(g.maps) for g in stability)
    outputs = sum(len(g.outputs) for g in stability)
    add(
        f"- Goldens compared: {len(stability)} (every Tier 0 manifest of the `manifests` above); "
        f"stable {len(stability) - len(unstable_goldens)}, unstable {len(unstable_goldens)}."
    )
    add(
        f"- Exported maps compared: {maps} (unstable "
        f"{sum(len(g.unstable_maps()) for g in stability)}); readbacks and captures compared: "
        f"{outputs} (unstable {sum(len(g.unstable_outputs()) for g in stability)})."
    )
    for file in sorted(documents):
        statuses = [e["status"] for e in documents[file]["entries"]]
        counts = ", ".join(f"{s} {statuses.count(s)}" for s in ("exact", "calibrated", "gap"))
        add(f"- `parity/semantics/{file}`: {len(statuses)} entries ({counts}).")
    settled = settle(stability, domains, documents)
    add(
        f"- 04 §9 items settled: {sum(s.settled for s in settled)} of {len(settled)} "
        "(section 6); every other item is an open item."
    )
    add("")
    add("## 2. Stability per channel type (measured storage format)")
    add("")
    add(
        "Storage format = container/sample type and bits/channels/encoding of the export, as "
        "measured in the private record. |Δ| in native units (integer codes or float values); "
        "every recording compared with `r1` (same session)."
    )
    add("")
    add(
        "| Storage format | Maps compared | Unstable maps | Classification | max \\|Δ\\| | "
        "mean \\|Δ\\| | Differing values | Differing texels | Values compared |"
    )
    add("|---|---|---|---|---|---|---|---|---|")
    for t in channel_types(stability):
        add(
            f"| `{t.storage}` | {t.maps} | {t.unstable_maps} | {t.classification} | "
            f"{_fmt(t.max)} | {t.mean:.6g} | {t.differing} | {t.affected_texels} | {t.values} |"
        )
    readback_unstable = sum(len(g.unstable_outputs()) for g in stability)
    add(
        f"| readbacks and captures (JSON equality) | {outputs} | {readback_unstable} | "
        f"{'stable' if readback_unstable == 0 else 'unstable'} | — | — | — | — | — |"
    )
    add("")
    add(
        "Readback rule: the resource context counter Painter increments per opened project "
        "(`projectNN` in resource URLs) is replaced by `project#` before comparison; the raw "
        "differing count is given per golden in section 3. Outputs recorded in only one "
        "recording (API probes record their steps before the reopen and identity checks after "
        "it) are counted as unpaired, not compared."
    )
    add("")
    add("## 3. Per-golden recording comparison")
    add("")
    add(
        "| Golden | Private record SHA-256 | Recordings | Maps (unstable) | Readbacks and "
        "captures equal / compared (raw equal) | Unpaired | Classification | Admission |"
    )
    add("|---|---|---|---|---|---|---|---|")
    for g in stability:
        recs = ", ".join(f"{r} {c}" for r, c in g.recordings)
        equal = sum(o.equal for o in g.outputs)
        raw = sum(o.equal_raw for o in g.outputs)
        admission = "exact golden" if g.classification == STABLE else "not admitted (§4)"
        add(
            f"| `{g.golden_id}` | `{g.record_sha256}` | {recs} | {len(g.maps)} "
            f"({len(g.unstable_maps())}) | {equal} / {len(g.outputs)} ({raw}) | "
            f"{len(g.unpaired)} | {g.classification} | {admission} |"
        )
    add("")
    add("## 4. Exception evidence (unstable goldens)")
    add("")
    add(
        "An unstable golden is not admitted as an exact golden (`14-…` §5); its statistics "
        "below are the evidence an exception proposal cites. The entries in force are those of "
        "the register (`parity/exceptions.json`); under decision 032 the same-session recording "
        "r1 stays the exact target (`parity/CONTRACT.md` §5)."
    )
    add("")
    add(
        "| Golden | Map | Storage format | Recordings | Blob SHA-256 (first, other) | max "
        "\\|Δ\\| | mean \\|Δ\\| | p99 \\|Δ\\| | Differing values / compared | Differing texels / "
        "texels |"
    )
    add("|---|---|---|---|---|---|---|---|---|---|")
    for g in unstable_goldens:
        for m in g.unstable_maps():
            d = m.difference
            add(
                f"| `{g.golden_id}` | `{m.output_id}` | `{m.storage}` | {m.recordings[0]} vs "
                f"{m.recordings[1]} | `{m.sha256[0]}`, `{m.sha256[1]}` | {_fmt(d.max)} | "
                f"{d.mean:.6g} | {_fmt(d.p99)} | {d.differing} / {d.total} | "
                f"{d.affected_texels} / {d.texels} |"
            )
    add("")
    add("Unstable readbacks and captures (after the resource-context normalisation):")
    add("")
    add("| Golden | Output | Kind | Recordings |")
    add("|---|---|---|---|")
    for g in unstable_goldens:
        for o in g.unstable_outputs():
            add(
                f"| `{g.golden_id}` | `{o.output_id}` | {o.kind} | "
                f"{o.recordings[0]} vs {o.recordings[1]} |"
            )
    add("")
    add(
        "API-probe readbacks of the project's name, file path or node identity describe the "
        "state the save and reopen create, so they differ by construction of the second "
        "recording's condition; they are listed because the classification is binary."
    )
    add("")
    add("## 5. Published fits")
    add("")
    add("| File | Entry | Subject | Status | Residuals | Worst residual |")
    add("|---|---|---|---|---|---|")
    for file in sorted(documents):
        for e in documents[file]["entries"]:
            add(
                f"| `{file}` | `{e['entry_id']}` | {e['subject']} | {e['status']} | "
                f"{len(e['residuals'])} | {_worst([(file, e)])} |"
            )
    add("")
    add("## 6. Settlement of `04-layer-stack-and-compositing.md` §9")
    add("")
    add(
        "Settled only when a published fit covers the item, every covering entry is exact, "
        "every golden of the item is stable and no part of it moved to another task; otherwise "
        "the item is open (release gap until settled, or an exception proposal). Golden record "
        "hashes: first 16 hex digits here, full values in section 3."
    )
    add("")
    add("| §9 item | Status | Goldens (record SHA-256) | Fits | Worst residual | Open because |")
    add("|---|---|---|---|---|---|")
    for s in settled:
        goldens = "; ".join(
            f"`{g.golden_id.rsplit('/', 1)[-1]}` {g.record_sha256[:16]}" for g in s.goldens
        )
        fits = ", ".join(sorted({f"`{f}`" for f, _ in s.entries})) or "—"
        add(
            f"| {s.item.name} | {'**settled**' if s.settled else 'not settled'} | {goldens} | "
            f"{fits} | {_worst(s.entries)} | {'; '.join(s.reasons) or '—'} |"
        )
    add("")
    return "\n".join(lines)
