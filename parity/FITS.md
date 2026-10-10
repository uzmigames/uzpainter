# Tier 0 oracle stability and clean-room fits

Task `phase0.7_tier0-stability-fits` (child of `phase0.8_tier0-goldens`, D3/D5/D9/D13). It answers two questions about the Tier 0 goldens before any compositor kernel is frozen (`docs/architecture/14-parity-testing.md` §1, `04-layer-stack-and-compositing.md` §9): does Painter reproduce itself (oracle stability), and which public formulas reproduce the recorded outputs (fits). Code: `tools/parity/fit/`. Tests: `tests/parity/fit/`. Outputs: `parity/semantics/*.json` (schema `parity/schema/semantics.json`) and `parity/reports/phase0/tier0-stability.md`.

## 1. Commands (owner's machine, private store present)

| Command | Does |
|---|---|
| `python -m tools.parity.fit run [--fit NAME ...]` | Runs the fits (all, or the named ones: `blend`, `profile`, `srgb`, `normal`, `resample`, `ao`), writes their files under `parity/semantics/`, compares the recordings of every manifest under `parity/manifests/tier0/` and writes the report |
| `python -m tools.parity.fit check [--fit NAME ...]` | Re-runs the fits and checks that every published entry, status and residual is reproduced exactly |

Both exit 1 with `oracle_unavailable` when the store or a blob is missing; nothing is compared then. A full `run` takes several minutes (it decodes every recorded map).

Decoding is at native depth (`parity/CONTRACT.md` §3.1): PNG with the repository's own decoder (`tools/parity/feasibility/png.py`), OpenEXR with the OpenEXR Python binding (BSD-3-Clause, approved source S-EXR). The binding is a tooling dependency of the owner's machine only; it is imported when a float map is decoded, so hosted CI (no store) never needs it.

## 2. Oracle stability (`stability.py`)

- Every recording of a golden is compared with its first one (`r1`, the session that built the state; `r2` is after save and reopen; some API probes and the baking defaults have more).
- Exported maps: decoded values compared value for value; integer maps compare codes, float maps compare numbers (a NaN matches only a NaN). Statistics: max, mean and p99 |Δ|, differing values, differing texels.
- Readbacks and captures: JSON equality, after one stated normalisation: the resource-context counter Painter increments per opened project (`projectNN` in resource URLs and contexts) becomes `project#`. The raw count is reported next to it. Outputs present in one recording only are listed as unpaired.
- Classification is binary and by measured storage format (container, sample type, bits per channel, channels, encoding), never by map name: `stable` when every compared value is equal, otherwise `unstable`. An unstable golden is not admitted as an exact golden; its statistics are listed as exception evidence in the report (no exception is proposed by this task).

## 3. Fits (`common.py` and one module per file)

Each fit module exposes `FILE` and `fit(ctx)`, reads recorded values from the store through `Context`, and returns a public document: formulas from public sources (approved source ids, never `A-OBSERVE`), authored or fitted constants, and residuals (|Δ| statistics at storage precision against both recordings). Nothing recorded is published: no value, table or crop derived texel for texel from a recording. The schema and the repository guard (`parity/GUARD.md`) enforce the shape.

Storage units (`common.to_storage`): RGB16/L16 export their 16-bit codes unchanged; RGB8/L8 export code × 257; sRGB8 storage codes are recovered from the 16-bit export through an export table calibrated in memory on `blend-inputs` (every code exported; never published); float formats export float32 values. Status per entry: `exact` only when every residual is zero, `calibrated` for a fitted formula with a non-zero residual (a candidate exception or release gap, never a pass), `gap` when not reproduced or moved to another task.

| File | Module | Subject |
|---|---|---|
| `blend-modes.json` | `blend.py`, `blend_component.py` | The `BlendingMode` members, the evaluation order (`blend-order`) and the normal-map modes |
| `evaluator-profile.json` | `profile.py` | End against per-layer quantisation and the sRGB8 blending space, from the three-1/3-opacity-fills golden; profile id `painter-12.1-<id>` |
| `srgb-transfer.json` | `srgb.py` | Uniform-colour storage on RGB16 and sRGB8 channels and the sRGB8 export, against IEC 61966-2-1 |
| `height-to-normal.json` | `normal.py` | The project's default height→normal method |
| `resampling.json` | `resample.py` | The UV-projection filters, `BilinearHQ` first |
| `ao-mixed.json` | `ao.py` | The `AO_Mixed` operator |

The second height→normal method, the strength sweep and the `PassThrough` group cases are recorded through Painter's UI by `phase0.7_tier0-semantics-ui-cases` (owner answer, 2026-10-10); here they are `gap` entries or open items.

## 4. Settlement of 04 §9 (`report.py`)

The report lists every §9 item as settled or not settled with the goldens (and their private record SHA-256) and the worst residual that decide it. An item is settled only when a published fit covers it, every covering entry is `exact`, every golden of the item is stable and no part of the item moved to another task; anything else is an open item with its reasons (a release gap until settled, or an exception proposal with the report's statistics as evidence).

## 5. Tests

`tests/parity/fit/test_stability_and_publication.py`: classification of identical and one-texel-different synthetic pairs, float and NaN comparison, readback normalisation (3.4); every published file valid against the schema, citing approved sources and residuals against both recordings (3.1); the guard accepts the published files and rejects a fits file with a pasted readback (3.2); the settlement covers every §9 item; on the owner's machine each fit is re-run and must reproduce its published file exactly, and the guard runs with the store index (3.3). The fit modules have unit tests of their formulas on synthetic arrays (`tests/parity/fit/test_*.py`).
