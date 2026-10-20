# 341. More bakers on the CPU core: Opacity as 1 on a hit and 0 elsewhere; every value Painter's labels leave open refused before any work; parity pending-evidence

**Status**: accepted
**Date**: 2026-10-20
**Related Tasks**: phase3.4_baker-opacity, phase3.5_embree-bakers

## Context

The coordinator asked for the offline items of the Thickness, Height and Opacity baker tasks on the Embree CPU core, in the pattern of decision 337: CPU only, each map in its own file, a parameter whose Painter semantics are unrecorded refused with `NotYetSupported` naming the owner task and this decision, and nothing claimed equal to Painter.

What is recorded (`assets/defaults/baking.json`, decision 323): Opacity has no keys of its own. No Tier 2b golden of Opacity exists, and no recorded output states its channel format.

The rule of decision 337 §1 applies unchanged: a value whose label names exactly one computation on data the bake mesh carries is implemented (`pending-evidence`); a value that needs a formula, a constant or an input nothing recorded fixes is refused before any work.

## Decision

### 1. Shared to the maps of this decision
Decision 337 §2 holds for each of them:
- they run on the shared primary hit of `embree_baker.cpp` and, combined with other usages, leave those maps' bytes alone;
- a non-hit texel holds zero and is told apart by the class map;
- `SubSampling` above 1 and `DilationWidth` above 0 are refused;
- each map present is appended to the canonical bytes as a tagged block; a result without it keeps its bytes;
- every value is written by one texel's own slot, so the bytes do not depend on the worker count.

### 2. Opacity (phase3.4_baker-opacity)
- **The value.** The opacity of the high surface the primary ray hit. A bake mesh carries no transparency input (no alpha, texture or material), so a hit surface is opaque: 1. Non-hit texels (misses, back-face hits, hidden, uncovered) are 0 with their class.
- **Stored unencoded.** `BakeResult::opacity`, float32 in [0, 1]. Painter's channel format (item 2.2) is established by the Tier 2b goldens, so no encoding is chosen. The block tag is `OPA1`.
- **Refused.** `SubSampling` above 1: a texel partly covered by the high mesh would need a coverage fraction or another resolve, and neither is recorded. `DilationWidth` above 0.
- **No parameters.** Opacity has no keys, so nothing is stored for it and `RequestFromParameters` maps nothing.
- **Assumption.** If Painter's Opacity reads a transparency of the high mesh (a texture's alpha, a material opacity), that input is outside the bake mesh and outside every analytic fixture, which have none: on them the computation above is the only one.
- **Settles it:** an Opacity golden on the plane, sphere and bevelled cube, for the encoding and the edge coverage.

## Alternatives Considered

- **Encoding Opacity as 8-bit or 16-bit grey.** Not taken: the channel format is item 2.2's, established by the goldens. A float in [0, 1] loses nothing.
- **Averaging sub-samples into a coverage fraction.** Rejected: the resolve rule is not recorded (decision 337's rule for every map).

## Consequences

- New: `src/bake/opacity_baker.{h,cpp}` (in the `bake-feasibility-tests` step) and `tests/bake/opacity_bake_cases.h` (six native cases, the `opacity` cross-process fixture).
- Changed: `bake_request.*` (the `opacity` map and its `OPA1` block), `embree_baker.*` (the usage, its validation and its texel write), `tests/bake/bake_feasibility_test.cpp`, `test_bake_feasibility.py`, `06-baking.md` §3.3.
- The bytes of every AO, Normal, WorldSpaceNormal, Position and ID result are unchanged.
- No Python or MCP symbol is added. Parity stays `pending-evidence`; every Tier 2b item stays open.
