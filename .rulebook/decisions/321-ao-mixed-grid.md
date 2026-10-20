# 321. Recording R-131 is one Tier 0 request, `ao-mixed-grid`, that pins what R-086a left implicit: the fill's Nearest filtering and identity UV at three opacities and one BilinearHQ control, with PNG 8 and OpenEXR 32f exported twice each from one project; designed, recording pending

Date: 2026-10-20. Status: accepted (Claude and Codex, SUP-173 to 176; routine technical choice delegated by the owner).
Related: `phase3.2_unreal-ue56-packed-preset` item 2.10, `phase3.2_uze-uzmat-preset` (`<set>_orm`), decisions 086, 087, 092, 093 and 131.

## Context

Decision 131 §2 names R-131 as the settling recording for AO_Mixed if the R-092 isolation goldens do not identify the operator, and they do not. The best model in `parity/semantics/virtual-maps.json` misses r1 at 31 values, every one of them within 3 ulps of a 2^-12 boundary. r2 misses more, and no model explains that. The misses come from these R-086a sets:

| Set | Content | Misses |
|---|---|---|
| `ao-mixed-opacity` s1 | one fill at 0.5 | 9 |
| `ao-mixed-opacity` s2 | one fill at 0.75 | 2 |
| `ao-mixed-opacity` s5 | a fill at 0.5 inside a group | 9 |
| `ao-mixed-opacity` s6 | two fills at 0.5 | 2 |
| `ao-mixed` s1 | at 0.5 | 9 |

**R-086a already covers the whole code grid.** Its fixtures grey A and grey B are 256 × 256 (`tools/parity/tier0_semantics/fixtures.py`), laid on a 4 × 2 plane grid where every set has UV 0..1 at resolution 256. So all 65 536 pairs of mesh-map code and channel code were recorded. Decision 131's literal "full grid" would repeat a recording, which the no-repeat rule forbids. What R-086a did not pin is how the fill's source bitmap was read. Its filtering and UV projection stayed at the defaults, and read arithmetic there could produce boundary-adjacent misses like these. The mesh-map binding has no filtering setting. Its PNG and OpenEXR results also came from separate goldens and projects (`ao-mixed-opacity` and its `-float` twin), not from one project and fill.

## Decision

1. **One request, `tier0/semantics/ao-mixed-grid`.** It uses the existing 2 × 2 plane grid: four texture sets, each with UV 0..1 at resolution 256, in Legacy colour. Grey A, mesh-map code x, is bound as the AO mesh map. Grey B, channel code y, is the AO fill's source bitmap. Both are authored PNG 16 on the `code8 × 257` lattice, so every pair 0..255 occurs once. The fill uses identity UV (scale 1, rotation 0, offset 0, RepeatNone); across the four sets only its filtering and the fill's opacity vary, as listed. No new fixture, probe vocabulary or recorder change is needed.
   - **s0:** fill filtering Nearest, opacity 0.5.
   - **s1:** fill filtering Nearest, opacity 0.75.
   - **s2:** fill filtering Nearest, opacity 1.
   - **s3:** fill filtering BilinearHQ, opacity 0.5. This is the filtering control.
2. **Order.** The recorder's job model allows no state change after the first capture. So all four fills and every mutation come first. Then four export steps run from the same project and inputs: PNG 8, PNG 8 repeat, OpenEXR 32f and OpenEXR 32f repeat, all with passthrough padding and no dithering. Each step exports three maps per set: AO_Mixed, the AO channel, and the AO mesh map directly as the mesh-map control. That gives 48 maps per recording, with r1 and r2. The channel exports are observations, not assumed to be AO_Mixed's exact pre-write operands.
   - Each set's fill persists across its format and repeat pairs.
   - s0 and s3 are different sets with different fills. The filtering control compares filter settings, not the same fill.
3. **Hypothesis.** If the misses come from read filtering, they should disappear on s0 to s2 and remain on s3. If they come from the operator, they should remain on the Nearest sets too. A difference between s0 and s3 supports the filtering hypothesis but does not prove it, because s0 and s3 are different sets with different fills. The format and repeat pairs show whether PNG 8 and OpenEXR 32f agree within one project, and whether r2's extra misses repeat within one session.
4. **Limits.**
   - The group and two-fill cases of R-086a (s5 and s6) are not repeated. They stay validation sets for any operator found.
   - A new golden alone accepts nothing. Any future operator must still match every admitted AO_Mixed golden (R-086a and the R-092 isolation goldens) under item 2.10's every-texel rule at PNG 8, PNG 16 and OpenEXR 32f.
   - No recording, admission, exception or change to the refusal in `src/export/virtual_maps.cpp` is made now.
5. **This decision amends decision 131 §2.** R-131 is this controlled-variable request, not a repeat of the code grid.

## Consequences

- One recording gives evidence on two hypotheses for AO_Mixed, read filtering versus the operator itself. It does not settle the cause alone.
- The request becomes a separately versioned recording operation for the owner, after operation-v2 and P22-B.
- File authorship:
  - Codex: `tools/parity/tier0_semantics/recording_requests.py`, the request `parity/envelopes/painter-12.1.5_js-api.1.1.20/requests/tier0/semantics/ao-mixed-grid.json` and `tests/parity/recorder/test_ao_mixed_request.py`.
  - Codex's independent validation: `tests/parity/test_ao_mixed_grid_contract.py`. It is a structural contract check of the request (the request JSON equals the generator's output, and the referenced inputs' bytes match their SHA-256). It is neither a fake replay nor observed Painter evidence.
  - Claude: this decision.
