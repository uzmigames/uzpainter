# 328. The filter families: Sharpen and grayscale conversion are HLSL families on the layer content, the Levels filter maps onto the native levels effect, the content is an implicit input with a joint rule, a filter's source has no resolution override, and the domains are declared uncertified

**Status**: accepted
**Date**: 2026-10-20
**Related Tasks**: phase3.2_proc-filter-families

## Context

`phase3.2_proc-filter-families` items 2.2, 2.3, 2.4 and 2.6 and tests 3.2, 3.3 and 3.5 can be built without Painter. Items 2.1 (parameter discovery through the `Property` API), 2.5 (calibration against private oracles), 3.1 (Tier 2a) and 3.4 (Tier 0 `effect-order`) need Painter recordings or goldens, and stay open. Facts at the start (main `bb2745dd`):

- The seam, the HLSL host and the asset library exist (decisions 222, 303, 324). No family is certified. The shipped library holds no record.
- The evaluator refuses filter effects (`unsupported_node`, owner this task). The procedural seam is not wired into the evaluator.
- The native levels effect is exact against Tier 0 (`parity/semantics/masks-levels.json` `levels`, `levels-clamp`). It uses the recording GPU's reciprocal, log2 and exp2 from measured tables (`src/evaluator/hwmath.h`), which the evaluator binds to its own kernels. The HLSL host has no table buffers.
- The certification harness reads the domain as JSON (`tools/parity/proc_cert/batch.py` `Domain`). It has no rule between an input and the output.
- Per the python-doc, `SourceSubstance.resolution` throws `ValueError` for a source that a `substance_painter.layerstack.FilterEffectNode` holds (A-PYDOC). In the document model the source of a filter effect is its `ProceduralRef`.

The coordinator's brief fixed the frame: the math comes from published sources only (decision 006), nothing is certified and no alias names a filter (decision 324). No model panel ran. The forks below follow from those rules.

## Decision

Code: `src/procedural/filters.{h,cpp}`, the `JointRefusal` hook of `IHlslFamily` (`src/procedural/hlsl_backend.h`), `UseContext::content` (`src/procedural/admission.h`) and one rule in `src/uzp_core/types/validation.cpp`. Records: `assets/procedural/records/filter.*@1.json`. Tests: `tests/procedural/filters_test.cpp` (`uzp-proc-filter-tests`) and `tests/procedural/test_proc_filter_families.py`.

1. **Two kinds of filter.**
   - Sharpen (`uzasset://filter/sharpen@1`) and grayscale conversion (`uzasset://filter/grayscale@1`) are `IHlslFamily` families. Each has one kernel pass over the content and a CPU reference that equals it bit for bit, built from the primitive library (`Add`, `Sub`, `Mul`, `Texel`, all flushed, no contraction).
     - Sharpen is the Laplacian sharpening of Gonzalez and Woods (4th ed., §3.6): `g = f - amount * (f(x-1,y) + f(x+1,y) + f(x,y-1) + f(x,y+1) - 4 f)`, summed left, right, up, down, with the content wrapping at the texture border.
     - Grayscale conversion is `Y = red * R + green * G + blue * B`, summed in that order, written to the three channels. The default weights are BT.709's luma coefficients rounded to float32.
   - The Levels filter (`uzasset://filter/levels@1`) is not an HLSL family. It maps onto the native levels effect (`LevelsFilterEffect` gives the `core::LevelsParams` of one component), so it keeps the effect's Tier 0 semantics, tables included, on every lane the evaluator has. Its CPU lane (`LevelsFilterReference`) is `evaluator::arith::Levels` on float32 parameters, as the evaluator converts them. An HLSL copy of the levels kernel would need the host to bind the hardware tables, and would be a second implementation of a settled operator.
2. **The content is an implicit input with a joint rule.**
   - Every filter reads one image input, `content`: the layer content at the filter's position in the effect list (04 §2 step 4). `UseContext::content` carries its spec and hash, and `RequestFor` adds it. A reference that also binds an input named `content` is refused.
   - The content has the output's resolution, channels and colour space. The domain's JSON cannot say so, so each filter checks it after the domain check (`FilterJointRefusal`, through `IHlslFamily::JointRefusal` on the HLSL host). A mismatch is refused as `outside certified domain`, naming the field, the value and the output's value. It is never resampled or converted.
3. **Filter-effect evaluation on the CPU lane** (`FilterEffectReference`). The filter's output blends over the same content with the effect's own mode and opacity, through the evaluator's effect mix (`arith::Composite` with `effectMix`, the mix that Tier 0 settled for content fill effects). The content raster must have the SHA-256 that the request names, so a filter computes only from the content it was admitted on. The evaluator still refuses filter effects (`unsupported_node`). Wiring them into the compositor waits on a certified family (phase3.3), because production may serve only `exact` assets.
4. **A filter's source has no resolution override.** Validation refuses a filter effect whose `ProceduralRef` has a `resolution_override`, with `ValueError`. Every write path validates (transactions, project load, recipes), so the edit commits nothing and the revision stays. A generator keeps its override. The getter half of the documented rule belongs to the `SourceSubstance` facade, which is a release gap (phase3.1 item 2.6).
5. **Domains declared before calibration, uncertified.**
   - The three records go in the shipped library with status `unavailable` and no corpus. The alias table stays empty, so `resource.search` refuses every Painter name as before. `s:uzpainter` lists the three assets, and `assets list --parity` prints their domains.
   - Parameter names and ranges are UzPainter's own (Sharpen `amount` [0, 4]; grayscale `red`, `green`, `blue` [0, 1]; Levels `input_min`, `input_max`, `output_min`, `output_max` [0, 1], `gamma` [0.125, 8], `clamp` {0, 1}, with the joint constraint `input_min - input_max <= -2^-8`). Item 2.1 has not discovered Painter's. When it does, the domains are revised before calibration starts.
   - Seeds: the single listed seed 0, because filters take content instead of seeds. Geometry: the classes of the certification meshes (`sphere`, `bevelled-cube`, `garment`) on one UV tile. Resolutions 1024, 2048 and 4096.
   - Content: Sharpen and Levels read a 16-bit linear mono content (the mask precision of `masks-levels.json`; LAY-04 sharpens masks). Grayscale reads an 8-bit sRGB RGB content. The output is float32 in the content's colour space. Every other channel layout and format is a release gap.
   - Item 2.6 stays open. Its held-out set and hash list come from the recording batch, and the parameter ranges come from item 2.1.

## Alternatives Considered

- **An HLSL Levels family with the hardware tables.** Rejected: the host would need table bindings, and the operator would be implemented twice.
- **Unsharp masking with a Gaussian for Sharpen.** Not taken: it needs a radius parameter that nothing documents yet. The Laplacian is one pass, and calibration may still replace it.
- **The content as a bound image input of the reference.** Rejected: the content changes with every edit below the filter, and a stored hash would be stale.
- **Records outside the shipped library until certification.** Rejected: 05 §6 records the domain in the provenance record and in `assets list --parity` before calibration.

## Consequences

- phase3.2 items 2.1, 2.5, 3.1 and 3.4 remain. 4.1 waits on them.
- Any later change of operator, parameter or domain happens before calibration starts, or it starts a new held-out set (decision 222).
- The Blur filter of `effect-order` (decision 069) is not built here.
