# 423. Generator goldens compare Painter's covered texels; the AO generator is calibrated, not exact; the other generators stay release gaps

**Status**: accepted (root review by the model panel, 2026-11-10; see Review). §3 is superseded by decision 424: `generator/occlusion@2` is exact.
**Date**: 2026-11-09
**Related Tasks**: phase3.2_proc-generator-families, phase3.3_procedural-families

## Context

Item 2.5 of `phase3.2_proc-generator-families` calibrates the eight mesh-map generators against private Painter oracles, after item 2.7 has declared each domain and pinned a held-out set (decision 222, harness of decision 303). The parameters were discovered on 2026-11-09 (item 2.1, `docs/analysis/proc-generator-families/01-parameter-discovery.md`). One Painter session (12.2.0, Legacy, lock seq 2354 to 2359) recorded a diagnostic golden and the Ambient Occlusion batch. Evidence and numbers: `docs/analysis/proc-generator-families/02-calibration-2026-11-09.md`.

Measured facts:

- Under `passthrough` padding the two recordings of a generator golden differ outside Painter's UV coverage, and on one island-edge texel of the hat at 4096; on every texel the World Space Normals bake covers with a covered 3 x 3 neighbourhood they are equal (ten AO goldens, the diagnostic golden).
- Ambient Occlusion: defaults and both inverts give float32(1 - float32(1 - ao)) on every compared texel of 18 calibration and 2 held-out cases. A single invert gives 1 - x(k), x(k) a float32 of the 16-bit AO code k / 65535 that is not the correctly rounded one on about one code in six; no tried conversion reproduces it. Report: outcome fail, `calibrated`, max 256 ULP f32 (absolute at most 4.5e-8), mean 0.039 ULP.
- Dirt, Metal Edge Wear and Mask Builder - Legacy change with the seed at their defaults (Painter's own grunge); Curvature and Mask Editor apply a multi-scale curvature filter at their defaults (equal inputs, outputs up to 0.0189 apart).
- No Assets3D recipe uses Position or World Space Normals, and the harness requires a recipe parameter set in the §6 matrix.
- Hat v6 low is lost (decision 260); the delivered hat v8 low mesh survives.

## Decision

1. **Compared texels.** A generator case compares the texels the World Space Normals map, baked with no dilation, covers with a covered 3 x 3 neighbourhood. The mask comes from that baked input map, not from the World Space Normals generator (a release gap, §4). Each oracle is stored with every other texel set to 0, and the candidate reproduces that mask from its World Space Normals input. The harness compares the whole stored raster, so a candidate with another or a smaller mask fails: no compared texel can be dropped silently. This is the feasibility study's rule (UV-covered texels eroded by one, phase0.6), with Painter's own bake as the coverage. Every compared texel is compared exactly; no tolerance is introduced.
2. **Garment mesh.** The hat v8 low mesh stands in for the lost hat v6 low in the generators' §6 matrix, pinned by SHA-256 and kept in the private store.
3. **Ambient Occlusion stays a release gap.** `generator/occlusion@2` is `calibrated`, not exact; its held-out set is spent. No exception is created: a decision-032 exception for the two single-invert sets, or a UzmiGames measurement of the recording GPU's 16-bit texture conversion, is the owner's choice. No asset record, alias or native kernel of `@2` is added while it is not exact.
4. **The other seven stay release gaps** with the evidence above. Observed facts first, the hypothesis each suggests second:
   - Dirt, Metal Edge Wear and Mask Builder - Legacy: the seed alone changes their output at the defaults. Hypothesis: Painter's own seeded grunge.
   - Curvature and Mask Editor: equal curvature inputs give unequal outputs, so they are not a per-texel function of that input. Hypothesis: a multi-scale curvature filter.
   - Position and World Space Normals: a procedural gap, not a technical one. The harness needs a recipe parameter set in the §6 matrix and no recipe uses them, so they are not batched.

## Alternatives Considered

- **Comparing every texel.** Rejected: Painter's two recordings of the same golden disagree outside the coverage, so no implementation could be exact there.
- **A 65 536-entry table of Painter's single-invert outputs.** Rejected: it would ship Painter output values.
- **Dropping the single invert from the AO domain.** Rejected: the Tunic v10 recipe set, which the §6 matrix requires, is a single invert.

## Consequences

- `phase3.2_proc-generator-families` items 2.1 and 2.7 (AO) are met; 2.5, 2.6, 3.1 and 4.1 stay open with every generator a release gap.
- A new AO candidate needs a new held-out set (decision 222); the requests and batch builder re-run in minutes (`python -m tools.parity.proc_generators write`, `python -m tools.parity.proc_generators.batch occlusion`).

## Review

Root review, 2026-11-10, by the model panel (`python -m tools.model_panel --deadline 180`; Codex root not active). The dossier held only the rules, precedent phase0.6 and counts, no Painter values. Every reply completed with finish reason `stop`.

| Model (returned id) | Round 1 | Round 2 |
|---|---|---|
| `cx/gpt-6-astra` (`gpt-6-astra`) | ACCEPT-WITH-CHANGES | ACCEPT |
| `xai/grok-4.5` (`grok-4.5`) | ACCEPT | ACCEPT |
| `kimi/kimi-k3` (`kimi-k3`) | ACCEPT | ACCEPT |

All three agreed that §1 is an exact domain with no hidden tolerance, matching phase0.6. GPT and Kimi asked for wording changes, taken in §1 and §4:

- GPT: the §4 mechanisms claimed more than the evidence showed, so §4 now separates fact from hypothesis.
- Kimi: Position and World Space Normals are a procedural gap, not an impossibility, and the mask comes from the input map, not from the generator.

No dissent remains.
