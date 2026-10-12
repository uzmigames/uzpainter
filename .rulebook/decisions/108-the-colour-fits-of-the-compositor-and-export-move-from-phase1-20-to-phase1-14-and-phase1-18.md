# 108. The colour fits of the compositor and the export move from phase1.20 to phase1.14 and phase1.18

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.20_pyapi-facade, phase1.14_compositor-core, phase1.18_export-engine, phase1.24_python-api-facade

## Context

Decision 081 named `phase1.20_pyapi-facade` as the owner of OCIO colour management, and decision 100 gave it the fit of R5's Legacy twin (`export-ocio-encode-legacy`). These refusals name phase1.20 as their owner:

- in the evaluator (`support.cpp`, `dag.cpp`, `evaluate.cpp`): an sRGB bitmap as a mask source, on a channel that is not sRGB8, 8-bit, or resampled; an unrecorded bitmap colour space; OCIO colour management;
- in the export plan (`src/export/plan.cpp`): `$colorSpace` names.

phase1.20's checklist names the facade's colour rules: the implicit space, the profiles, and an unsupported configuration failing before evaluation. It does not name these compositor and export fits.

The refusals already fail before any change, as decision 082 requires. Lifting them is compositor and export work:
- the 8-bit, resampled and mask variants of the sRGB decode;
- the masked group of `export-ocio-encode-legacy` s5, which is unstable in the oracle (123 of 128 maps stable);
- `$colorSpace` naming;
- OCIO, which waits for the Session O goldens (decision 101).

The open owners of that work are `phase1.14_compositor-core` (Tier 0 semantics exact for the implemented subset) and `phase1.18_export-engine` (export naming and encoding).

The model panel could not be consulted: the 9router proxy refused every connection (decision 107).

## Decision

1. phase1.20 delivers the facade's colour rules and proves them through readbacks:
   - `export-ocio-encode-legacy` readbacks and colour-space captures, both recordings;
   - `fill-layer-readback` s5-s8, s30-s33 and s43.

   Every one is exact except the named residual of decision 107 §3.
2. The evaluator refusals that named phase1.20 now name `phase1.14_compositor-core`:
   - the sRGB bitmap variants and unrecorded bitmap colour spaces, fitted from `export-ocio-encode-legacy`, which is already recorded;
   - OCIO colour management, after Session O's `export-ocio-encode` and `export-presets-ocio`.

   The compositor capability entries `compositor:ocio` and `compositor:srgb-unrecorded` name it too.
3. The export plan's `$colorSpace` refusal belongs to `phase1.18_export-engine`. Its message is updated on that task's branch, which owns `src/export/` today.
4. The facade's own recorded gaps (decision 107, P20-A and P20-B) are fitted by phase1.14_compositor-core when recorded, together with the facade tables they settle.

## Alternatives Considered

- **Keep phase1.20 open until these fits land.** Rejected (brief speed rule 4): its checklist claims none of them, and every refusal stays explicit.
- **Move them to phase1.25_pilot-wand.** Rejected: the pilot consumes the compositor's subset and does not own its semantics.

## Consequences

phase1.14_compositor-core gains the R5 Legacy twin fit and, after Session O, the OCIO fit. phase1.18_export-engine renames the owner of the `$colorSpace` refusal. phase1.20 closes with these recorded as scope splits.
