# 256. The viewport fades its shading normal toward the interpolated normal as its mirror reflection nears the tangent plane

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase2.1_preview-viewport-window, phase2.3_realtime-preview, phase1.25_pilot-wand

## Context

The `painter_viewport` close-up of the Wand's tip gem (1920 × 1080, camera `03_tip_gem_closeup`) showed thin, jagged, near-black lines along the gem's lower edge and near its point. The texture inputs were clean there.

The cause was found pixel by pixel (scratch `fix4/gem-lines`):

- **Not the evaluated Normal.** Each of the 2,067 dark-line pixels was ray-cast to its UV. Under every one, the Height is 32767 (zero height) and Painter's recorded `Normal_OpenGL` (wand-v1 r1) equals the baked normal map to within one code. The texels lie on a baked facet ridge of the gem's island, a strong tilt (for example `t = (0.39, 0.83, 0.40)`), not on an island edge. The evaluator plays no part, and decision 245 is not involved.
- **The viewport's normal rule.** The pass switched to the interpolated normal only where the perturbed normal faced away from the viewer. An approximate CPU replay of the shading frame put 1,867 of the 2,067 dark pixels within 2 px of a region where the perturbed normal faces away. They form the rim of that region. Just inside the rim, `n · v` falls toward 0. The view's mirror reflection then dips below the geometric tangent plane, and the dark lower environment is reflected. Just past the rim, the rule switched to the interpolated normal, which is much brighter. The result was a thin dark contour along the boundary.
- **Measured on a fixture.** A plane under a uniform environment carries a normal map whose tilt sweeps from -80 to +80 degrees across u. With the old rule the centre row jumps by 0.224 (linear) between two neighbouring pixels, over a row range of 0.226.

The viewport is a preview, never parity or acceptance evidence (decision 018). Its normal rule is a design choice that no recording backs.

## Decision

1. **Fade toward the interpolated normal.** After the MikkTSpace perturbation, the pass computes `e = dot(reflect(-v, s), ng)`: the height of the view's mirror reflection about the shading normal `s` above the geometric tangent plane (`ng` faces the viewer).
   - `e >= 0.2` and `s` facing the viewer: `s` is kept, bit for bit.
   - `e <= 0`, or `s` facing away: the interpolated normal `normalize(n)`, the former fallback.
   - In between: `normalize(lerp(normalize(n), s, smoothstep(0, 0.2, e)))`.
   - The result is continuous in `s`. Facing-away normals and reflections below the surface get exactly the former fallback, so the rule only smooths the former switch.
2. **Sources.** *Physically Based Rendering*, 4th ed. (P-PBRT), §9.1.5: the shading and geometric normals define different hemispheres, and the mismatch causes artifacts unless it is handled. The criterion applies that to the mirror reflection: its height above the geometric surface, measured here as the cause of the lines. The remedy, a smoothstep blend toward the pass's own former fallback, is UzPainter's design. The band 0.2 is UzPainter's own preview constant. A reflection kept unchanged then lies at least about 11.5 degrees above the tangent plane. The fixture and the Wand show no band at its edge. Since the viewport makes no parity claim, nothing records it.
3. **The rule it replaces is removed.** `src/preview/viewport.h` and `src/preview/PREVIEW.md` state the new rule.
   - `parity/semantics/iray.json` `normal-and-bump` still states the old rule. That formula belongs to the phase0 prototype's calibration and its recorded residuals, not to the viewport, so it stays as recorded.
4. **Evidence.**
   - `tests/preview/test_preview_viewport.py::test_normal_tilted_past_the_horizon_shades_continuously` (DX12, native case `viewport-normal-fade`): on the swept-tilt plane, the centre row's colour varies with the tilt by 0.022, and no two neighbouring pixels differ by more than 0.02. The steepest step measured is 0.0068. Under the old kernel the same plane jumps by 0.224.
   - **Viewport goldens.** The sphere, plane and bevelled cube render byte-identically to the kernel before this decision: they have flat normal maps, so `s` is the interpolated normal and the blend returns it. Only the kernel key changes: `f8c9aa42d1df9cb3` for a CRLF checkout and `ff36ce4703f095c0` for an LF `viewport.hlsl`. The superseded keys of the first version (`8b9e7c46eeabf917`, `c3bb60d6949d2010`) were removed, as in decision 178.
   - **The Wand, rendered again** (scratch `fix5/renders`, the four planned views). A detector (luminance under 0.6 of the 9 × 9 median, pixels not beside the background) flags 1,891 interior pixels in the close-up before the fix and 272 after. The rest are texture detail and the grazing silhouette, which shows the same dark wedge as before. The thin lines along the gem's lower edge are gone. The other three views drop as well (224 → 203, 794 → 678, 267 → 219).

## Clean-room provenance

The first version of this decision (branch `wt/fix-gemlines`, commit `d77472b`, never merged) implemented a shading normal adaption from a source that is off-limits and never an implementation input: Keller et al. 2017, "The Iray Light Transport Simulation and Rendering System" (appendix A.3). That paper is NVIDIA's description of Iray's internals. Policy forbids it (`docs/licensing-and-clean-room.md` §2, "Iray: … description of its internals"), and the approved-source index quarantines it as Q-IRAY. The review rejected the change, and this version replaces it.

- **Exposure record.** On 2026-10-13 the implementing agent of the `gem-lines` fix (Claude Opus 5.5) read the paper's full text, extracted from the arXiv PDF into scratch (`fix4/gem-lines/iray_paper.txt`, 106,668 bytes, SHA-256 `78f15d43a41c0b31774a50a1c0ddbbf27c5ccb9b78a57632f67118b6fd17acd2`), and wrote `AdaptShadingNormal` from appendix A.3. The fixing agent of this version (Claude Opus 5.5, the same day) did not open the paper. It saw the appendix's rule only as restated in `d77472b`'s decision text and code. Both scratch copies (the paper text and `adapt.hlsl.txt`, SHA-256 `62866012330c10595deeb6defbc7998d88075a72d773474ab59882bb5fe2af95`) were deleted on 2026-10-13. Deleting them does not erase the exposure.
- **What was removed.** The lift of the reflection to a fixed elevation, the halfway-vector reconstruction, the 0.01 elevation, the function `AdaptShadingNormal`, the native case `viewport-normal-adaption`, and every citation of the paper and every "as Iray does" wording in code, docs and this record, except this provenance section.
- **What replaced it, and from where.** The rule above has a different construction, a blend between the perturbed normal and the pass's own former fallback. Its criterion comes from P-PBRT §9.1.5 and the measured cause. P-PBRT's cleared scope now names it (`docs/approved-sources.md`). Facing-away normals and reflections below the surface keep the former fallback exactly, which the adaption did not.
- **What clears the paper.** Only an owner decision that carves the paper out of Q-IRAY with an approved-source entry. Until then it is not an implementation input, and no change may cite it except in a sentence that forbids it.

## Panel

The dossier (root cause, the reviewer's blocker, options A-D, claims 1-5) went to `cx/gpt-6-astra`, `kimi/kimi-k3` and `xai/grok-4.5` in one round. The options: A, keep the adaption and carve it out of Q-IRAY (owner only). B, keep the same algorithm without the citation. C, the fade above. D, revert to the old rule until the owner rules.

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| 1 The blocker is real: the paper is within Q-IRAY, so A is not available to an agent | AGREE | AGREE | AGREE |
| 2 B is provenance laundering and is rejected | AGREE | AGREE | AGREE |
| 3 C is a different design (criterion from P-PBRT, remedy the smoothed former fallback), acceptable with the exposure recorded | PARTLY | PARTLY | AGREE |
| 4 C is preferable to D | PARTLY | AGREE | AGREE |
| 5 Amend the unmerged decision 256 instead of taking a new number | PARTLY | PARTLY | AGREE |

The PARTLY verdicts set conditions, and this version meets each one:

- C needs its own measurements. The adaption's numbers do not carry over: the fixture, the goldens and the Wand were measured again above.
- The provenance record must state facts: who, when, what was read, and what happened to the copies.
- Bit identity holds through explicit early returns, not through `lerp(·, s, 1)`. Facing-away `s` returns the fallback by its own test, so the rule does not depend on a hemisphere assumption.
- The blend is not claimed to guarantee a reflection above the surface.
- Decision 256 exists only on this unmerged branch, so amending it keeps one record. The first version's history stays in `d77472b` and in the section above.

## Alternatives Considered

- **Keep the reflection-lift adaption (options A, B).** Rejected. A needs the owner. B is laundering (provenance section).
- **Revert to the old rule (D).** Rejected. It keeps a visible defect in a preview that makes no parity claim, while a clean fix exists.
- **Blend on `s · v` instead of the reflection height.** Rejected. A normal that faces the viewer can still mirror the view below the surface. A CPU prototype of a swept tilt kept the old rule's darkest value there (0.084 at -85 degrees), where the reflection-height rule gives the fallback.
- **Clamp `n · v` to a floor by bending `s` toward the view.** Rejected. It turns the thin lines into wide dark bands, because every back-facing region would then shade at the floor.
- **Change the normal map or the evaluator.** Rejected. Under the lines, the evaluated Normal equals Painter's recorded export, so the texture is right.

## Consequences

- The viewport no longer draws dark contours where a baked or bumped normal turns past the viewer's horizon. Pixels whose reflection lies at least 0.2 above the tangent plane shade exactly as before. Pixels that faced away, or reflected below the surface, get the former fallback.
- The `wt/viewport-shadows` branch (decision 251) uses the same `shading` value for its visibility sums. It keeps unchanged the line this change replaces. The merge replaces that line with the `FadeShadingNormal` call, and it must re-bless the goldens' kernel keys.
