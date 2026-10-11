# 79. The mesh normal map, the Normal channel at any coverage and the UV-space height scale close phase1.12 on the decision 077 recordings

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.12_compositor-height-normal

## Context

Decision 064 left three inputs refused with `unsupported_source` until recorded: set resolutions other than 256, a bound Normal mesh map, and a non-empty Normal channel or a Normal bitmap in a DirectX project. Decision 077 recorded ten goldens for them (r1 same session, r2 after save and reopen). Fitting them against r1 (counts of differing exported values; CPU and GPU evaluator identical bit for bit, a Python reimplementation gives the same counts):

- **F1 Mesh map** (`height-normal-mesh-map`, OpenGL, Sharp and Sobel; `-directx`): F = decode(code / 65535) of the bound map is the first base, A = normalise(reoriented(F, H)), its y negated when the map is in the DirectX convention (a map given to a DirectX project). Exact on all 60 maps, r1 and r2. Rejected: reoriented(H, F) (about 138 000 off), F after the Normal channel (about 92 000), the codes passed through (3 072 off by one). `meshMap/normal_base` exports the codes unchanged.
- **F2 DirectX Normal channel** (`normal-channel-import-directx`, `-mesh-map-directx` s2-s3): the export's green is htz(1 - htz(1 - g)) (htz: binary16 toward zero), 8 and 16 bits; the virtual maps are exact only on the OpenGL-convention storage htz(1 - g) (the DirectX export with y negated leaves 41 800 values up to 20 codes off). An empty channel exports 127/255 in both projects. Recorded in DirectX: one bitmap fill in Normal mode at opacity 1.
- **F3 Coverage** (`height-normal-channel-coverage`): (a) the channel's layers composite over (0.5, 0.5, 1) at read-out (127/255 leaves 131 072 values off), a = htz(opacity x mask); (b) the virtual maps read the root list from a transparent start, colour X and coverage a: C = flat at a = 0, decode(X) at a = 1, else u = decode(X rcp(a)) turned toward (0, 0, 1) by a, (u.x k, u.y k, cos t), t = a acos(z), k = sin(t) rsqrt(fma(-z, z, 1)); the read-out instead leaves up to 8 610 codes off; (c) acos is the GPU's Vulkan arccosine, 2 P(sqrt(fma(-1/2, z, 1/2))) above 0.57, else float32(pi/2) - P(z), P the arcsine polynomial: 0 mismatches on 33 554 432 Vulkan inputs over [-1, 1]; pi/2 - asin (the blend modes' rotation) leaves 82 values one code off; (d) X rcp(a): IEEE X / a leaves 78 values off on the mask-coded set. Exact on every r1 map; r2 of s2 differs (decision 080).
- **F4 Resolution** (`height-normal-resolution-512`, `-1024`, `-1024-sobel`, `-2048`): z = 100 / W (Sharp) and 800 / W (Sobel); a fixed z leaves 428 000 to 6.7 M values off. Exact on every r1 map; r2 of 2048 s2 differs (decision 080).
- **F6 Magnified Height**: Painter filters the signed texels 2t - 1, not t: filtering t and taking 2v - 1 leaves 16 (512) to 462 (2048) Height values one half-step off near 0. The integer bilinear filter of `projection_uv.h` extends to signed texels (sign-magnitude truncation toward zero, ties away from zero), equal to the measured rule for t >= 0.
- **F5 SignedAddition on Height** (`height-signed-addition`): the existing kernel (a + 2b) - 1 is exact on all 24 maps, r1 and r2, with no code change.

The model panel ruled on 2026-10-11 under the owner's delegation (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5):

| Claim | Verdicts |
|---|---|
| C1 Mesh map as F; lift for 16-bit maps at the set size, declared convention else the project's | PARTLY x3: an imported map declared in the other convention is unrecorded; lift only for the project's convention |
| C2 Convention-independent Normal storage, DirectX export inverts green; lift DirectX Normal bitmaps for every mode and coverage | DISAGREE x2, PARTLY x1: lift only the recorded stack (one bitmap fill, Normal mode, opacity 1, no mask or effects) |
| C3 Coverage model with the Vulkan acos; r1 the target for s2 | AGREE x2, PARTLY x1: list several-layer root lists at partial coverage as unrecorded |
| C4 z = 100 / W for every square power-of-two set | PARTLY x3: lift only 256, 512, 1024, 2048 |
| C5b Signed conversion before the filter in the shared projection code | PARTLY x3: implement; scope the claim to the recorded dyadic magnifications; the negative-texel hardware filter stays unmeasured |
| C5 3.1 closes on F5 | AGREE x3 |
| C7 3.1, 3.3, 4.1 met and the task archived | DISAGREE x2, PARTLY x1: only with the lifts scoped to the evidence, the gaps listed and a local DX12 run as the 4.1 evidence |

## Decision

1. The bound Normal mesh map is F, the first base of the combination: decode of its 16-bit codes, y negated in the DirectX convention. Evaluated only for a 16-bit RGB map at the set resolution in the project's convention; an 8-bit map, another size or the other convention stays refused (`unsupported_source`).
2. The Normal channel's storage is the same in OpenGL and DirectX projects (imports invert green, 8 and 16 bits); a DirectX project's export of a non-empty channel inverts green again (the export plan's concern, phase1.15); the evaluator returns the storage. In a DirectX project the Normal channel is evaluated only as one bitmap fill in Normal mode at opacity 1 without mask or effects; any other stack is refused.
3. The Normal channel's read-out composites its layers over (0.5, 0.5, 1) (`ChannelDag::readoutBase`); an empty channel keeps the template base 127/255. The virtual maps read the root list (colour, coverage) and turn the channel normal by its coverage with the GPU's Vulkan acos (`hw::Acos`), the reciprocal, sine, cosine and rsqrt tables; flat at coverage 0.
4. z = 100 / W (Sharp) and 800 / W (Sobel), lifted for square sets of 256, 512, 1024 and 2048 px; other sizes and shapes stay refused.
5. On the Height channel each bitmap texel is converted to 2t - 1 before the bilinear filter; the integer filter accepts signed texels (sign-magnitude truncation, ties away from zero), unchanged for t >= 0. The claim covers the recorded dyadic magnifications; the hardware filter on negative texels with other weights is a listed gap.
6. Items 3.1, 3.3 and 4.1 are met for the recorded combinations, with every r1 map exact on CPU and GPU in a local DX12 run; the unrecorded inputs above are published as the gap `height-normal-unrecorded-inputs`.

## Alternatives Considered

- Lifting every DirectX Normal stack and every power-of-two size on the convention-independence and the UV-space law (rejected by the panel: beyond the evidence).
- Leaving magnified Height bitmaps to phase1.9 (rejected: the resolution goldens need the Height end to end; the change is limited to the signed channel).
- Reading the Normal channel's read-out over the flat colour in the virtual maps at partial coverage (decision 064's hypothesis; rejected: thousands of values off).

## Consequences

`height_to_normal.{h,cpp}`, `hwmath` (`Acos`), `dag` (`readoutBase`, the DirectX Normal scope), `evaluate` (`EvaluateIsolatedRoot`), `projection_uv` (signed Height texels), the CPU store and the `UZP_VNORMAL` and projection kernels implement it, GPU = CPU bit for bit. `parity/semantics/height-to-normal.json` publishes the entries `height-normal-mesh-normal-map`, `height-normal-channel-coverage`, `height-normal-channel-import`, `height-normal-resolution-scaling`, `height-signed-addition` (exact) and the two divergences of decision 080.
