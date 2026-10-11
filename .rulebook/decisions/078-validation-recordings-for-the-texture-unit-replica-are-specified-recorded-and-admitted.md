# 78. Validation recordings for the texture-unit replica are specified, recorded and admitted

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.9_compositor-resample-gaps

## Context

Decision 061 stopped the closed-form search for the recording GPU's anisotropic texture unit and named a tabulated replica for axis-aligned footprints as the next step. Decisions 056 and 061 add that a Painter recording is needed only to validate such a replica beyond the existing captures: anisotropic HQ, LOD at or above 1, and rotations, for both filters, with irregular offsets (`parity/reports/phase1/compositor-resample-gaps.md` §5.4, §6.3). The existing `resample-uv-minify` and `-impulse` cover isotropic footprints of 1.28-4.15 texels at LOD below 1, one anisotropic footprint and one rotation.

The design (pattern64, footprint = scale / 4 texels at 256 px; effective LOD k at scale 4 * 2^(k + 1.5) for BilinearSharp and 12 * 2^k for BilinearHQ) went to the model panel under the owner's delegation on 2026-10-11 (cx/gpt-6-astra, kimi/kimi-k3; xai/grok-4.5 was unavailable in the first round and judged the revision):

| Claim | Verdicts |
|---|---|
| D1: three goldens on the existing four sets and pattern64; "every tap weight observable" | PARTLY x3: end-to-end validation, not tap identification (withdrawn); add an anisotropic impulse golden for attribution |
| D2: anisotropic ratios 2.1-4.2, one v-major case | PARTLY x2, DISAGREE x1: add clamp saturation (ratio about 7), a second v-major case, both axes past LOD 1 |
| D3: isotropic 4.4-15.9 texels cover LOD at or above 1 | DISAGREE x1, PARTLY x2: the effective LOD is 0.5-2.5; add samples at and beside the integer LODs of both biases |
| D4: 90/180/270 twins of non-cardinal rotations | PARTLY x2, DISAGREE x1: add rotation-0 controls (axes swapped, same offsets); the twins validate a replica that assumes axis alignment and do not probe Painter's trigonometry |
| D5: irregular offsets, no zero offset | PARTLY x2, DISAGREE x1: add a zero-offset twin in the new regimes |
| D6: validation data only, no refusal change, no exception | AGREE x2, PARTLY x1 |
| Revision R1-R5 (grok) | R2 AGREE; R1, R3, R4, R5 PARTLY: add LOD-0 boundaries, a zero-offset boundary sample and a same-scale rotation-0 control (adopted) |

## Decision

1. **Five goldens** (`current.py`, `validation_goldens`; domain `tier0/resample/uv`), each on grid2x2 with the sets of `resample-uv-minify` (s0 HQ Repeat, s1 Sharp Repeat, s2 HQ RepeatNone, s3 Sharp RepeatNone), one RGB16 user channel per case (up to User9), documented API only:
   - `resample-uv-anisotropic` (pattern64, 10 cases): (9.37, 4.41), (13.71, 4.93), (21.43, 6.17), (38.83, 9.07), (45.37, 6.11) clamp saturation, (30.13, 18.07) both footprints past 4.5 texels, (4.47, 17.29) and (6.11, 45.37) major axis on v, (21.43, 6.17) at offset 0, (4 * 2^2.5, 8) on the Sharp LOD-1 boundary; irregular offsets otherwise.
   - `resample-uv-anisotropic-impulse`: the same plan on impulse64 (kernel reads).
   - `resample-uv-lod` (8 cases): isotropic 17.47, 21.83, 26.29, 38.41, 45.13, 53.69, 63.77 at irregular offsets, and 26.29 at offset 0.
   - `resample-uv-lod-boundaries` (10 cases): Sharp boundaries 4 * 2^1.5, 4 * 2^2.5 (offset 0) with 22.40 and 22.86 beside it, 4 * 2^3.5; HQ boundaries 12, 24 with 23.76 and 24.24 beside it, 48.
   - `resample-uv-rotation` (10 cases): 7.3, 22.5, 45, 61.7 and 133.1 degrees (refusal checks); 90, 180 and 270 degrees (axis-aligned); rotation-0 controls of the 90 case with its axes swapped and of the 180 case, each with that case's offset.
   - `resample_minifying` takes the channels from the plan's length; the existing manifests are unchanged.
2. **Recorded and admitted.** r1 and r2 (after save and reopen), `store verify` ok; r1 = r2 on every map:

| Golden | Maps | Private record (SHA-256) |
|---|---|---|
| `resample-uv-anisotropic` | 40 | `f9421359740f97012e0b5d03fd9962d771f846c96b4e5668b94ac8c911bb5a7c` |
| `resample-uv-anisotropic-impulse` | 40 | `bc5a5096db6869391029498a61fa468ee43b4a427e9770ba1794ed878d6d0f37` |
| `resample-uv-lod` | 32 | `80bf855316ed90594aeed2931b239d51844bce3c52b99c83b9341ef09a8cced0` |
| `resample-uv-lod-boundaries` | 40 | `cbc19cbd976327597bf3b7fc17b796c652607aab4cdca316fa9e617ee7f68fa6` |
| `resample-uv-rotation` | 40 | `8a7ee1e00f74e07473e0cb4b2b1124719c6f7fb4d073fd3ca1e3baf2b29a08f7` |

3. **Validation data only.** No refusal changes; bilinear minification stays `evaluator:unsupported_source`. Non-cardinal rotations stay refused even if a replica matches them. The recordings are held out from table fitting: decision 061's gates (domain bound, key sufficiency, accumulation, sample-for-sample hardware validation) come first.

## Alternatives Considered

- New anisotropic or ramp fixtures (not needed: pattern64 and impulse64 already exist and are authored).
- Recording only P1-P3 as first proposed (amended by the panel for clamp saturation, integer-LOD boundaries, rotation-0 controls and zero-offset twins).

## Consequences

The follow-up texture-unit replica task can validate its axis-aligned subset end to end against Painter, at both biases, across anisotropy up to the clamp, LOD 0-2.5 and cardinal rotations, and keep the non-cardinal cases as refusal checks. The tier0 stability report lists the five goldens under the `BilinearHQ` kernel item.
