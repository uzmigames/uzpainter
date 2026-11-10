# 424. The recording GPU's 16-bit UNORM fetch is correctly rounded; the AO single invert inverts the 16-bit code; `generator/occlusion@2` is exact and aliased

**Status**: proposed (its exactness counts decision 423 §1's compared texels, which are still with the root reviewer)
**Date**: 2026-11-10
**Related Tasks**: phase3.2_proc-generator-families

## Context

Decision 423 left Ambient Occlusion `calibrated`. Defaults and both inverts were exact. A single invert differed by one ulp on about one AO code in six, and the decision attributed this to Painter's float32 of the 16-bit code. Its held-out set (knob cube at 2048) was spent. Decision 423 offered two routes: an exception, or a UzmiGames measurement of the recording GPU's 16-bit texture conversion. The coordinator ruled out an exception and asked for the measurement, then a refit of the single-invert sets and a new held-out golden. Evidence: `docs/analysis/proc-generator-families/03-occlusion-exact-2026-11-10.md`.

## Decision

1. **The measured fetch.** `tools/parity/vk_sampler_probe/unorm16.py` measures it through Vulkan on the recording GPU (RTX 4090, driver 617.14), in the same way as the reciprocal, root and texture-unit tables:
   - an R16G16B16A16_UNORM texture holds all 65 536 codes in each channel;
   - it is read with `Load`, nearest `SampleLevel` and linear `SampleLevel` at the texel centre;
   - every read returns float32(k / 65535) correctly rounded.

   The table is `src/evaluator/tables/hw-unorm16.zlib`, in hwmath.h's delta form, with every delta 0. The fetch is not the source of the residual.
2. **The model, refitted on the calibration set alone.**
   - c = k when `ao_invert` equals `global_invert`, else 65535 - k: one invert inverts the 16-bit code.
   - The value is I(I(F(c))), with I(v) = float32(1 - v) and F the measured fetch.
   - It equals Painter on all 65 534 codes present, and on every compared texel of the 36 calibration cases.
   - The candidate was committed (`ef7dafc7`) before any new held-out golden was recorded.
3. **A new held-out set:**
   - the Tunic v10 low mesh, the recipe set's mesh, outside the calibration set;
   - at 1024 and 4096, with the four sets: 8 cases;
   - recorded under Painter lock seq 2368 and pinned in `e59f9433`.

   The spent knob cube set leaves the batch. Its hash and its report stay in the ledger and in history. Certification is **exact**: calibration 36 of 36 and held-out 8 of 8 (report `parity/reports/phase3/proc-cert/generator__occlusion@2/2d91b5b1c67e5698.json`).
4. **`uzasset://generator/occlusion@2` ships as `exact`.**
   - Its record declares the batch's domain word for word: Painter's two invert parameters, float32 Raw AO and World Space Normals, one UV tile, 1024/2048/4096, seed 0.
   - The record names both corpus ids and the report.
   - The alias `starterassets / GENERATOR / Ambient Occlusion` names it (decision 324: only an exact asset).
   - The native family (`src/procedural/generators.h` `kOcclusion2Asset`) evaluates I(I(F(c))). It builds F from integer operations (`UnormQuotient16`, equal to the correctly rounded quotient on all codes), because kernels have no division.
   - An AO texel that is not float32(k / 65535) fails evaluation loudly on both lanes (`IHlslFamily::InputRefusal`). A 16-bit binding is outside the certified domain.
   - `@1` stays unavailable.

## Alternatives Considered

- **A decision-032 exception for the single-invert sets.** Rejected by the coordinator, and no longer needed.
- **A table of Painter's single-invert outputs.** Rejected, as in decision 423: it would ship Painter output values. The shipped table is UzmiGames' own measurement of the GPU.
- **Adding u16 AO bindings to the domain.** They decode to the same float32 values, but no u16 binding was certified, so they stay refused.

## Consequences

- Items 2.5, 2.6 and 3.1 are met for Ambient Occlusion. The other seven generators stay release gaps (decision 423 §4), so acceptance 4.1 holds only if they are listed as release gaps.
- If the root reviewer changes decision 423 §1, this certification and the alias are re-examined.
- Position and World Space Normals have the same per-texel structure, but no recipe set exists for them (decision 423).
