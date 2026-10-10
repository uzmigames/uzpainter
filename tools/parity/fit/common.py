"""Shared pieces of the Tier 0 fits: the fitting context, storage-level decoding and the public
entry builders of `parity/schema/semantics.json`.

A fit module exposes `FILE` (its file name under `parity/semantics/`) and
`fit(ctx) -> dict` (the public document). Fit modules read recorded values from the private
store through `Context` and publish only formulas, authored or fitted constants and residual
statistics; `publishable_problems` refuses a document that is not valid against the schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from tools.parity.fit.oracle import Golden, load
from tools.parity.fit.stats import Array, Difference
from tools.parity.schemas import Schema, validation_errors
from tools.parity.store.store import OracleStore

PAINTER_BUILD = "12.1.0+js-api.1.1.20"
MANIFESTS = "parity/manifests/tier0"
SEMANTICS_DIR = "parity/semantics"
RECORDINGS = ("r1", "r2")

# Residual units (native decoded units at storage precision, CONTRACT §3.1).
UNIT = {
    "RGB16": "16-bit code value",
    "L16": "16-bit code value",
    "RGB8": "8-bit code value",
    "L8": "8-bit code value",
    "sRGB8": "8-bit code value",
    "RGB16F": "half-float value",
    "L16F": "half-float value",
    "RGB32F": "float32 value",
    "L32F": "float32 value",
    "export16": "16-bit code value",
}


@dataclass
class Context:
    """Access to the private goldens of the Tier 0 corpus (owner's machine only)."""

    store: OracleStore | None
    repository: Path
    _goldens: dict[str, Golden] = field(default_factory=dict)
    _cache: dict[str, Any] = field(default_factory=dict)

    def golden(self, name: str) -> Golden:
        """`name` is `<folder>/<manifest stem>`, e.g. `semantics/blend-basic`."""
        if name not in self._goldens:
            path = self.repository / MANIFESTS / f"{name}.json"
            self._goldens[name] = load(self.store, path)
        return self._goldens[name]

    def cached(self, key: str) -> Any:
        return self._cache.get(key)

    def remember(self, key: str, value: Any) -> Any:
        self._cache[key] = value
        return value


def channel_format(golden: Golden, texture_set: str, channel: str, recording: str = "r1") -> str:
    """The channel's `ChannelFormat` from the golden's template capture (a readback, not a name)."""
    capture = golden.output(recording, "template/texture-sets")["values"]["texture_sets"]
    stack = capture[texture_set]["stacks"][""]
    by_lower = {name.lower(): spec for name, spec in stack.items()}
    return str(by_lower[channel.lower()]["format"])


def srgb8_export_table(ctx: Context) -> Array:
    """The 16-bit export value of each sRGB8 storage code 0..255 (in memory only, never published).

    Calibrated on `blend-inputs`: the sRGB8 channels (User2, User3) of the fields A and B hold
    every 16-bit code in their blue channel, so every one of the 256 storage codes is exported;
    the export is strictly increasing, so the k-th distinct export value is code k.
    """
    cached = ctx.cached("srgb8-export-table")
    if cached is not None:
        return np.asarray(cached)
    golden = ctx.golden("semantics/blend-inputs")
    values = [golden.map("r1", f"s{s}/user{u}").values.ravel() for s in (0, 1) for u in (2, 3)]
    table = np.unique(np.concatenate(values)).astype(np.int64)
    if table.size != 256:
        raise ValueError(f"sRGB8 export table has {table.size} values, not 256")
    return np.asarray(ctx.remember("srgb8-export-table", table))


def to_storage(ctx: Context, values: Array, fmt: str) -> Array:
    """Exported values -> the channel's storage values (codes for integer formats, floats else).

    RGB16/L16 export their codes unchanged; RGB8/L8 export code * 257; sRGB8 exports through the
    calibrated table (inverted here); float formats export their values as float32.
    """
    if fmt in ("RGB16", "L16"):
        return values.astype(np.int64)
    if fmt in ("RGB8", "L8"):
        codes = values.astype(np.int64)
        if (codes % 257).any():
            raise ValueError(f"{fmt} export not on the 8-bit lattice")
        return codes // 257
    if fmt == "sRGB8":
        table = srgb8_export_table(ctx)
        codes = np.searchsorted(table, values.astype(np.int64))
        if (codes > 255).any() or (table[np.minimum(codes, 255)] != values).any():
            raise ValueError("sRGB8 export value outside the calibrated table")
        return codes.astype(np.int64)
    return values.astype(np.float64)


# --- Public entries ---------------------------------------------------------------------------


def source(source_id: str, locator: str) -> dict[str, str]:
    return {"source_id": source_id, "locator": locator}


def parameter(name: str, value: Any, origin: str, unit: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"name": name, "value": value, "origin": origin}
    if unit is not None:
        result["unit"] = unit
    return result


def residual(
    golden_id: str, map_name: str, recording: str, unit: str, diff: Difference
) -> dict[str, Any]:
    return {
        "golden_id": golden_id,
        "map": map_name,
        "compared_against": recording,
        "unit": unit,
        "difference": diff.as_dict(),
    }


def entry(
    entry_id: str,
    subject: str,
    formula: str,
    sources: list[dict[str, str]],
    parameters: list[dict[str, Any]],
    residuals: list[dict[str, Any]],
    notes: str | None = None,
    gap: bool = False,
) -> dict[str, Any]:
    """`exact` only when every residual is zero; `gap` when the fit does not reproduce at all."""
    exact = bool(residuals) and all(r["difference"]["differing"] == 0 for r in residuals)
    result: dict[str, Any] = {
        "entry_id": entry_id,
        "subject": subject,
        "status": "gap" if gap else ("exact" if exact else "calibrated"),
        "formula": formula,
        "public_sources": sources,
        "parameters": parameters,
        "residuals": residuals,
    }
    if notes:
        result["notes"] = notes
    return result


def document(
    semantics_id: str, description: str, corpus: list[str], entries: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "schema": "uzpainter/parity/semantics/1",
        "record_class": "public_semantics",
        "semantics_id": semantics_id,
        "description": description,
        "painter_build_id": PAINTER_BUILD,
        "corpus": sorted(set(corpus)),
        "entries": entries,
    }


def publishable_problems(doc: dict[str, Any]) -> list[str]:
    return validation_errors(doc, Schema.SEMANTICS)
