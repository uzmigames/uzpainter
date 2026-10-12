# 124. The Wand Tier 1 runner rebuilds through the adapter, and the comparison reports structural differences as failures

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.25_pilot-wand, phase1.23_pyapi-pipeline-adapter, phase0.2_parity-contract, phase0.4_oracle-store-guard

## Context

phase1.25 items 2.1, 2.4, 2.5, 3.4 and 3.5 call for five things: the Wand v1 manifest, a Tier 1 runner, the comparison step, the `oracle_unavailable` case and the guard. Measured facts:

- **The manifest exists.** Decision 099 committed the R9 request `parity/envelopes/painter-12.1.5_js-api.1.1.20/requests/phase1/tier1/wand-v1.json`. It holds the inputs by SHA-256, the instruction sequence, the applied settings and the Painter 12.1.5 identity.
  - The task text names `parity/manifests/phase1/wand-v1.json` and Painter 12.1.0. Since decision 037 that path is the superseded envelope's root.
  - `store record` admits the request to the current envelope's `manifests/` when R9 is recorded.
- **Nothing is recorded yet.** R9 waits for the owner's session O.
- **UzPainter's wand export refuses before writing.** Two parts are not fitted yet: the PNG 16 export of the sRGB8 channels (item 2.6) and infinite padding (item 2.7).
- **The schema had two gaps.**
  - `comparison-report.json` had no field for a map on one side only or for a refused export.
  - Its encoding enum lacked `undetermined`, which the private record has (decision 087). Painter's 16-bit PNG exports state no encoding.
- **The guard had no rule** for a golden's comparison report under `parity/reports/`, so it rejected any such report.
- **The verdict was slow.** `verdict.diagnose` sorted Python lists, and a 2048 px RGB map is 12.6 million values.
- **Region masks.** The stack's four group masks (`M_wood`, `M_leather`, `M_iron`, `M_gem`) are 16-bit grey 2048 px PNGs, the export's resolution.

## Model panel (one round: cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5)

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C1 2.1 is the decision-099 request; `uzpainter_build_hash` stays null; each report names the exe's SHA-256 | PARTLY: covers the request only; admission is 2.2 | AGREE | AGREE |
| C2 each map judged against r1; outcome order unavailable, stale, fail, blocked, pass | PARTLY: preflight every blob first; unavailable and stale outrank structural | PARTLY: check the register before a fail | PARTLY |
| C3 a `structural` list of failures that a pass needs empty; `undetermined` added | PARTLY: list every missing map | AGREE | AGREE |
| C4 regions are the group masks' non-zero texels | AGREE: state overlaps and uncovered texels | PARTLY: needs an overlap rule | PARTLY |
| C5 normal diagnostics; unnormalised beyond sqrt(3)/max | PARTLY: clamp or avoid acos; exclude invalid vectors | AGREE | AGREE |
| C6 difference maps only in the private store; FLIP omitted | PARTLY: widen before subtracting | AGREE | AGREE |
| C7 a guard path rule for `tier<N>-*.json` reports | PARTLY: the hash rule must still apply | AGREE | AGREE |
| C8 vectorise `diagnose` with the same semantics | PARTLY: keep the exact fsum | PARTLY | PARTLY |
| C9 two rebuilds on DX12; a refusal fails structurally; repeatability `not_measured` | PARTLY: with no recording the outcome is oracle_unavailable | AGREE | AGREE |

Every condition the panel raised is adopted; see the Decision. The Codex audit then added four more:

- a structural difference rejects a pass even with exceptions;
- integer differences cannot overflow;
- the runner fails when the rebuilds are not repeatable;
- a map only in another recording makes the golden unstable.

## Decision

1. **Item 2.1 is the decision-099 request.** Its path and the 12.1.5 oracle follow decisions 037 and 099.
   - The manifest keeps `uzpainter_build_hash: null`; the schema allows null before any comparison.
   - Each report's `run` block names the SHA-256 of the `UzPainter.exe` that ran.
   - The admitted manifest comes with recording R9 (item 2.2).
2. **Runner (item 2.4): `tests/parity/tier1/wand_v1/runner.py`.**
   - It makes two rebuilds through the phase1.23 fixture `Wand`, which now accepts the admitted manifest.
   - Each rebuild has its own work directory. Create, sync and export each run as a separate `UzPainter.exe run` process.
   - The backend is DX12, the `run` verb's default; the adapter passes no backend.
   - An export that fails with `NotYetSupported` and writes nothing is a refusal. Any other failure stops the run.
   - The local test `test_wand_v1.py` writes the report to `UZP_TIER1_REPORT`. A `python -m` command cannot be used here: on this machine an installed editable package named `tests` (synap_sdk) shadows the repository's `tests` folder.
   - The test passes only on a `pass` with no structural difference and `repeatable` rebuilds.
3. **Comparison (item 2.5): `tools/parity/tier1/compare.py`.**
   - **Pairing.** Maps pair by texture set and map name. They are decoded at native depth and classified by measured storage format.
   - **Structural differences.** Each of these adds a `structural` entry and fails the comparison:
     - a refused export;
     - a map on one side only;
     - a differing storage format;
     - a differing shape.
   - **Oracle stability.** Each map of r1 is compared with r1-repeat and r2.
     - The comparison covers the union of every recording's maps. If another recording holds a map that r1 lacks, the golden is unstable and the comparison is never a pass (`blocked`).
     - Each map's verdict comes from `verdict.evaluate`. An unstable map is judged against r1 as the exact target (decision 032), and the register is consulted before a fail.
   - **Outcome order.** The first that applies wins:
     1. `oracle_unavailable`: the golden is not admitted, or its record or any of its blobs is missing. This is checked before anything is compared.
     2. `stale`.
     3. `fail`.
     4. `blocked`.
     5. `pass`.
   - **Diagnostics per map.**
     - Max, mean and p99 |Δ|, the differing count and the differing percentage.
     - The same per region. A region is a stack group mask's texels with a non-zero grey code, taken only at the mask's own resolution. Regions may overlap, and texels outside every mask count only in the whole-map numbers.
     - For the normal map: `<prefix>_Normal`, exported by the pinned `painter_export.py` from `Normal_OpenGL`.
       - The angle is atan2(|a×b|, a·b), taken over texels where both vectors are finite and non-zero.
       - Non-finite texels are counted.
       - Unnormalised texels are counted: beyond sqrt(3)/max for codes, sqrt(3)·eps for floats.
     - For a differing integer map, its |Δ| PNG goes only into the private store, and the report names its SHA-256.
     - FLIP is not computed, because no pinned NVlabs/flip exists in this repository.
4. **Schema: `comparison-report.json` gains three things.**
   - `equality_to_painter.structural`: a list of `{output_id, reason}` with an enumerated reason.
   - A rule that no `pass` lists a structural difference, with or without exception entries.
   - `undetermined` in the storage-format encoding enum.
5. **Guard (item 3.5).** `parity/reports/<phase>/tier<tier>-*.json` must validate against `comparison-report.json`. The store-hash and private-record rules run first, unchanged.
6. **Verdict.** `diagnose` accepts arrays and is vectorised with numpy. Its semantics are unchanged:
   - two NaNs are equal; a NaN against a number is an infinite difference;
   - p99 is nearest-rank; the mean is an exactly rounded `math.fsum`;
   - integers subtract in int64 only when both lie strictly within ±2^62, otherwise as Python integers;
   - a shape mismatch is structural.

## Alternatives Considered

- **Author a second manifest under `parity/manifests/phase1/`.** Rejected: that is the superseded envelope's root, and decision 099 already defines the wand golden.
- **Report a refused export as `not_measured`.** Rejected: the contract allows only a failure for missing content. Without a recording the outcome stays `oracle_unavailable`, and the refusal is still listed.

## Consequences

- Items 3.1 (equality) and 3.2 (repeatability) run with `python -m pytest tests/parity/tier1/wand_v1` on the owner's machine. They need two things first: R9 admitted, and the export's refusals lifted by items 2.6 and 2.7.
- Belt v5 and Tunic v10 reuse `tools/parity/tier1/compare.py` with their own regions and normal maps.
