# 43. Iray reference captures cover the fixed pipeline: v2 for every fixture, ref_match for both views

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase0.7_render-reference-captures

## Context

Task phase0.7_render-reference-captures was written before decision 038. It proposed an "analytic fixture profile" of `docs/architecture/07-preview-and-render-parity.md` §2.3: Legacy colour management with `Linear` tone mapping, three environments (a constant colour, a single bright patch, a Poly Haven HDRI), a white-furnace fixture, and one aggregate public manifest `parity/manifests/phase0/iray-references.json`. Decision 038 fixes the render pipeline to the Assets3D standard (`U-A3D-RENDERSTD-2`: the v2 common block, the `ref_match` v3 preset, the `base_color` diagnostic). Decision 039 makes Save Render (16-bit display-referred PNG) the pixel route, verified per reference by a fresh Painter session, a selector image and the background canary. Decision 042 pins the material model to Painter 12.1.5's default `open-pbr` instance at its defaults.

Measured for this task on Painter 12.1.5 under OCIO:
- One reference takes about 2.4 minutes with a fresh Painter process: 14 s launch, 125 s record, 5 s stop.
- The default shader instance reads back as follows (UI Automation read of the Shader settings dock, record `shader-defaults.json` `0cd1b76de6e5cbc97112e01783873ca4bfe08dceadce84855f82e17bf87c0da6`): displacement enabled with source Height, scale unit Normalized, amount 0; tessellation Uniform with count 1; emission luminance 0; alpha test, alpha blending and double sided all off. So an emission colour or an opacity map has no effect under the pinned shader.
- The template of a new project is the OpenPBR channel set: BaseColor, BaseMetalness, SpecularRoughness, Normal and Height.
- The repository guard accepts only one golden-public manifest per JSON file under the manifest roots.

The model panel was consulted under the owner's delegation on 2026-10-11 (cx/gpt-6-astra, xai/grok-4.5, kimi/kimi-k3). Verdicts per claim:

| Claim | Verdicts |
|---|---|
| OCIO with Default - sRGB replaces Legacy `Linear` | AGREE x3 |
| Only the pipeline's environments are used | PARTLY x3: the `ref_match` HDRI is still imported, as a session resource; state the glossy-fit risk of losing the bright patch |
| `ref_match` for a neutral pair at rotation 0 only | PARTLY x3: also capture rotation 180 and an asymmetric, mid-roughness, non-neutral fixture |
| The white furnace is replaced by the standard's `neutral_control` pair | AGREE x2, PARTLY x1: label them controls under the default shader, not analytic standards; keep the furnace as UzPainter's own analytic test |
| Content fixtures stay | PARTLY x3: perturbations must vary in space; label the channels the default shader ignores as negative controls; list the non-goals |
| `base_color` is not captured here | AGREE x2, PARTLY x1: name the work that captures it |
| One manifest per golden under the envelope root, plus an aggregate table in the report | AGREE x1, PARTLY x2: map golden to records explicitly; the hashes stay in each manifest and the report only mirrors them |
| A fresh Painter per reference (`--launch` series) | AGREE x1, PARTLY x2: a fresh process per capture is required; make the series resumable; batching would need a measurement first |
| k = 4; regions; statistics | AGREE x2, PARTLY x1: keep the edge band as its own region; the pixel filter correlates noise in space, so take the standard error over blocks; say whether deltas are per channel |
| Only the fixture content is proposed for ratification | AGREE x3 |
| Reword the task in place | AGREE x2, PARTLY x1 |

Overall: GPT "revise before approval", Grok "reject as-is on coverage holes", Kimi "approve with required changes". Their required changes are adopted below.

## Decision

1. **Pipeline.** References are captured only under the fixed pipeline: OCIO with Painter's substance config and Default - sRGB, Save Render 16-bit PNG at 1200x1200, Min = Max = 256 samples, Max Time 3600 s, k = 4, all through procedure `iray-capture/1`. The Legacy colour management and `Linear` tone mapping of the old proposal are dropped. The recorder refuses a fixed-pipeline sheet when Painter is not OCIO managed, because a Legacy project shows the same 89,89,89 background canary.
2. **Environments.**
   - `v2` fixtures use Studio White Soft, named by resource URL.
   - `ref_match` fixtures import the standard's HDRI as a session resource. The instruction sequence names the HDRI by SHA-256 (`77eeed8d…`) and file name, and the recorder is given the file with `--session-file`. The file stays in Assets3D and is not copied into the repository.
   - The constant-colour, bright-patch and Poly Haven environments are dropped.
3. **Fixtures** (22 goldens plus the qualification sphere, 69 references). All are UzmiGames-authored. The camera sits on +Z at 60 units, field of view 40, with no rotation. Each material is one fill layer of uniform sources on the OpenPBR channels.
   - `v2`:
     - the standard's `neutral_control` pair: linear 18% grey with metalness 0 and roughness 1; a reflective sphere with sRGB 0.9, metalness 1 and roughness 0;
     - base colour 0.8 grey and a saturated sRGB (0.8, 0.2, 0.1);
     - a metalness {0, 1} x roughness {0.1, 0.5, 0.9} grid;
     - perturbations that vary in space: normal ridges and height stripes;
     - negative controls: an emission colour (luminance 0 by default) and opacity stripes (alpha test and blending off by default);
     - a tilted plane and a bevelled cube.
   - `ref_match`, at environment rotations 0 and 180: the neutral pair and a saturated bevelled cube (asymmetric, not neutral).
   - The qualification sphere completes as the default-material fixture.
4. **Non-goals of the reference set**, which no Iray reference measures:
   - open-pbr features off by default: transmission, subsurface, coat, fuzz, thin-film, specular colour, anisotropy, diffuse roughness;
   - textured base colour and multi-material sets;
   - non-default shader parameters, which decision 042 rejects anyway;
   - the realtime `base_color` diagnostic. It is a viewport capture, never an Iray reference (decision 039), and it belongs to the preview work of P2-PREVIEW.
   - The white furnace and energy checks become analytic tests of UzPainter's own path tracer. They need no Iray reference.
5. **Session separation.** Every reference gets its own Painter process. `python -m tools.parity.recorder iray <manifests…> --launch` starts and stops Painter once per reference. It skips a golden that already holds the condition, so the series is resumable, and it carries on after a refusal. Batching fixtures in one session is not adopted, because the qualified procedure requires a fresh session per reference.
6. **Manifests.** There is one golden-public manifest per fixture under `parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests/phase0/iray-references/`, generated by `tools/parity/render_procedure/references.py`. The aggregate view lives in `parity/reports/phase0/iray-references.md`: golden, manifest, preset and every private record's hash.
7. **Noise terms.** They are computed in the reference's encoding per region: interior, the 2-pixel edge band, background.
   - (a) is s versus s; (b) is s versus k·S.
   - Statistics: max, mean, p99 and rms of |Δ|, the differing-pixel count, and the mean signed Δ with a standard error over 16x16 blocks. Each is also given after 2x, 4x and 8x box averaging.
   - The S-render σ is estimated from (b) only, as a range: rms(b)/√(1+1/k) if the k·S render is independent of the S render, and rms(b)/√(1−1/k) if it continues the same sample sequence. The first admitted goldens showed (a) orders of magnitude below (b): about 2% of object pixels differ between sessions. So Iray's sequence repeats across sessions, and (a) is not an independent-seed repeat. It is reported as the oracle-stability result, and no σ is derived from it.
   - These are noisy estimates from three renders, not tolerances.
8. **Ratification.** Only the fixture content (meshes, material values, camera, which fixtures get `ref_match`) is proposed to the owner. The render settings were fixed by the owner in decision 038.

## Alternatives Considered

- Keep the old analytic profile in Legacy colour management. Rejected: it is outside the fixed pipeline, and decision 042 rejects Legacy for `painter_iray`.
- Commit the `ref_match` HDRI as a repository fixture. Rejected: it would publish an Assets3D asset under the repository licence, and licence terms are owner-only.
- Record several fixtures per Painter session to save about a third of the wall time. Rejected: it departs from the qualified procedure's fresh session per reference, and nothing has measured that it keeps the display-transform evidence.
- One aggregate `iray-references.json`. Rejected: the guard requires one golden-public manifest per file.

## Consequences

Items 2.1–2.7, 3.2 and 4.1 of `phase0.7_render-reference-captures` are reworded to this scope. A change of the Assets3D standard, of the HDRI hash or of Painter's default shader re-opens the reference set. The emission and opacity references document that the pinned shader ignores those channels; if the owner later enables them in decision 038's scope, they need new references.
