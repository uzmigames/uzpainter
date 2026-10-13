# 249. On the Normal channel only recorded bitmap uses evaluate: colour maps at 1:1 and under Nearest, and 8-bit colour maps magnified as P20-A records them

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase1.15_compositor-colour-fits

## Context

Decision 226 fitted P20-A's Normal map. A bitmap on the Normal channel became a 16-bit UNORM texture: an 8-bit blue code below 127 is raised to 127, a grey image feeds its value to the three components, and the filter's result is written as a 16-bit code. Its only evidence is P20-A: on an RGB16F Normal channel in an OpenGL project, a 16 x 16 8-bit colour checker (blue codes 26 and 204) and a 16 x 16 8-bit grey image (codes 0 and 255) magnified 16 times on a 256 set by the default BilinearHQ, Repeat, scale 1, rotation 0, offset 0, both in NormalMapDetail mode.

Decision 226 also changed the output of inputs no recording holds, which decision 001 does not allow:

- a magnified or minified 16-bit normal map now passes through the 16-bit code;
- an 8-bit normal map with a blue code below 127 at 1:1 (or under Nearest) now stores 127;
- an 8-bit normal map minified, magnified another way, or magnified on another channel format or in a DirectX project, now passes through the new texture and the 16-bit code;
- an 8-bit grey bitmap became admitted at every sampling. P20-A sees it only through NormalMapDetail: decision 226 notes that its transitions are exact both ways, with and without the 16-bit code.

**Every recorded bitmap on the Normal channel.** This was read from the instruction sequences of the current envelope and the fixtures' codes:

| Bitmap | Kind | Sampling | Goldens |
|---|---|---|---|
| normal-a, normal-b | 16-bit RGB, 256 px, blue codes 57 680 and above | 1:1 (the default BilinearHQ; Nearest and BilinearHQ in `export-resize` s0 and s3) | `normal-channel-import` and its DirectX twin, `blend-normal-channel` s0-s3, `height-normal-mesh-map` and its DirectX twin, `height-normal-channel-coverage`, `export-bit-depth`, `export-dither`, `export-padding`, `export-presets-*` |
| normal-a | 16-bit RGB | magnified 2 and 4 times (an export upscale is the evaluation at 512 and 1024, decision 103), seen only through `Normal_OpenGL` and `Normal_DirectX` | `export-resize` s0 (Nearest), s3 (BilinearHQ) |
| normal-a | 16-bit RGB | minified 2 times vertically on a 256 x 128 set | `export-resize` s1. The evaluator refuses minification on a non-square set on every channel. |
| normal-a-8bit | 8-bit RGB, 256 px, blue codes 237 and above | 1:1 | `normal-channel-import` and its DirectX twin, `export-bit-depth` |
| checker-16 | 8-bit RGB, 16 px, blue codes 26 and 204 | magnified 16 times, BilinearHQ, RGB16F, OpenGL | P20-A |
| mask-left-half | 8-bit grey, 16 px, codes 0 and 255 | magnified 16 times, BilinearHQ, RGB16F, OpenGL, under NormalMapDetail with a mask | P20-A |

The phase-0 Iray reference `normal-ridges` (8-bit, blue codes 238 and above) is a render reference, not a channel golden.

**`export-resize` under decision 226's rule.** The virtual normal maps were evaluated at the upscaled size through the export engine (`uzp-export-tests files` from `export_spec`, the CPU store). They were compared with Painter's OpenEXR 32f and PNG 16 files, r1 and r2:

- s0, Nearest: exact at 512 and 1024. Decision 226 does not change Nearest, because a 16-bit code written as a 16-bit code is itself.
- s3, BilinearHQ: 2 048 of 262 144 texels differ at 512, and 6 880 of 1 048 576 at 1024, by up to 32 PNG 16 codes. Under the earlier float32 rule, 21 888 texels differed at 512 (decision 103).
- The Height channel alone is exact at those sizes (decision 103), and the height-to-normal combination is exact at 512 and 1024 on its own goldens. So the residual lies in the Normal channel's 16-bit bilinear magnification: decision 226's rule is disproved for a 16-bit normal map.

**The grey bitmap (found in review).** A first version of this decision kept an 8-bit grey image with the codes 0 and 255 at P20-A's sampling, on the claim that those codes cannot expose the 16-bit code. That claim is false:

- A plain grey fill (Normal mode, opacity 1, no mask) at P20-A's sampling filters to 184 / 256 at texel (124, 32). The channel stores 0.71875 without the 16-bit code and 0.71826171875 with it. Every texel where the filter mixes 0 and 255 depends on the choice.
- The normal-map modes do not hide the choice either. They decode (g, g, g) as normalise(2g - 1) with the GPU's rsqrt, and at 33 of the 257 filter weights the two candidates decode to normals one float32 step apart (measured with `arith::NormalDecode`). The current profile composites the root isolated, so a bottom layer passes its source raw (v = s) whatever its mode.
- P20-A also does not record the grey's value itself. NormalMapDetail normalises the decoded grey, so P20-A's cell interiors show only its direction: not inverted, blue not raised. Any value along (1, 1, 1), or along (-1, -1, 0) below one half, decodes alike.

So no grey use on the Normal channel is recorded. A rule that admitted only P20-A's composite would be a fingerprint of that one stack, not a rule.

**Channel format and convention (found in review).** P20-A records the magnification only on an RGB16F channel in an OpenGL project. The facade lets the Normal channel take another format (RGB32F, RGB16, RGB8, ...). On RGB32F the 16-bit code is stored as it is, with no half store after it, where the float32 filter result was stored before decision 226. A DirectX project's Normal channel is recorded only at 1:1 (decision 079), yet a single bitmap fill there passed the P20-A sampling check. At 1:1 and under Nearest decision 226 changes no value in any format or convention: an 8-bit code c becomes 257 c, the same value c / 255, and a code written as a 16-bit code is itself.

**Model panel**, round 1 (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5):

- C1. Refuse a 16-bit map resampled by a bilinear filter, and keep it at 1:1 and under Nearest: AGREE, AGREE, PARTLY.
- C2. Refuse bilinear minification on Normal: AGREE ×3.
- C3. Refuse an 8-bit map with a blue code below 127 at 1:1 or under Nearest, and keep one whose blue codes are all 127 or above: AGREE, PARTLY, PARTLY. The partial verdicts point out that an 8-bit map under Nearest away from 1:1 is not recorded on Normal either.
- C4. Admit an 8-bit grey bitmap only magnified: AGREE, AGREE, PARTLY. This rested on the false claim above, and round 2 replaces it.
- C5. Keep 8-bit magnification admitted at every factor and transform on P20-A's evidence: DISAGREE ×3. The same UNORM16-texture rule misses the 16-bit map at 2 and 4 times, so P20-A's 16-times upright sampling cannot stand for other factors or transforms.
- C6. Raise the refusals in the evaluator when the source is prepared, because the pre-mutation check (`support.cpp`) has no image data: AGREE ×3.

**Model panel**, round 2, on the review findings:

- G1. Codes 0 and 255 protect nothing, and the grey's 16-bit write is unproven for every code: PARTLY, AGREE, AGREE.
- G2. Admitting the grey only in P20-A's composite form (NormalMapDetail, masked) cannot be made a proof, and any safe structural rule would be a fingerprint: PARTLY, AGREE, AGREE.
- G3. Refuse every grey bitmap on Normal and exclude P20-A's Normal map until the recording: DISAGREE, PARTLY, AGREE.
  - GPT and Kimi object only that at 1:1 and under Nearest the 16-bit code cannot matter.
  - That is true of the code, but not of the grey's value, which P20-A does not record (above). Kimi and Grok agree on refusing every filtered grey, P20-A's included.
  - So every grey use is refused.
- G4. Admit P20-A's sampling only on an RGB16F channel in an OpenGL project, and keep 1:1 and Nearest colour maps in every format and convention: PARTLY, AGREE, AGREE. GPT asks that 1:1 and Nearest in other formats rest on their own evidence. They do: the import rule recorded at 1:1 (`blend-inputs`, `normal-channel-import` and its DirectX twin), unchanged by decision 226.

## Decision

1. **Admitted on the Normal channel** (`evaluate.cpp` `CheckNormalTexture`, after `NormalTexture`):
   - **A colour image (8- or 16-bit) at 1:1 or under Nearest whose import raises no blue code, in any channel format and convention.** Decision 226 changes none of these samples. normal-a, normal-b and normal-a-8bit at 1:1 are recorded, and so is normal-a under Nearest at 2 and 4 times (`export-resize` s0, exact).
     - The C3 objection is weighed and kept. Under Nearest, an 8-bit map with no raised blue gives the same values before and after decision 226. Those values are the 1:1 import rule (recorded) at the texel that the generic Nearest addressing picks (`resample-nearest`, exact at every scale). This is the earlier, documented "8-bit bitmaps by analogy" admission, and this decision does not widen it.
   - **An 8-bit colour image magnified exactly as P20-A records it.** That means an RGB16F Normal channel in an OpenGL project (`DagSource::p20aNormal`), a bilinear filter, Repeat, scale 1, rotation 0, offset 0, and an image 16 times smaller than the set on each axis.
     - The project's convention enters the source's content hash, so a tile made under one convention never serves the other.
2. **Refused** with `evaluator:unsupported_source` before the source's tile is projected (C6, as decisions 218 and 226 do for refusals that need the decoded image). The message names phase1.15_compositor-colour-fits item 2.9, decision 226 and this decision. Refused:
   - a grey image at any sampling;
   - a 16-bit image resampled by a bilinear filter (magnified, or rotated or shifted at scale 1);
   - any bilinear minification;
   - an 8-bit magnification other than P20-A's: another factor, transform or wrap mode, another channel format, or a DirectX project;
   - an 8-bit colour image with a blue code below 127, at 1:1 or under Nearest (`DecodedImage::blueRaised`).

   The 16-bit grey refusal of decision 226 stays.
3. **P20-A's Normal map is refused**, because its grey bitmap is refused. It is excluded again from `test_facade_fill_channel_defaults_equal_painter`, naming this decision and the recording below.
   - The checker's 16-bit-code rule stays admitted at P20-A's sampling. Its own 768 transition texels prove it.
   - The rule of decision 226 itself (the texture, the clamp, the 16-bit code) is not changed. Every recorded 1:1 import is unchanged.
4. **Native tests.**
   - `sources` checks the checker's P20-A codes on Normal (decision 226).
   - `sources` checks that 16-bit and 8-bit colour maps whose blue codes are 127 or above keep their codes at 1:1 and under Nearest. This includes 16-bit Nearest at 2 times, RGB16 and a DirectX project.
   - `sources` also checks that 19 unrecorded uses fail with the item and decision named. Among them are P20-A's binary grey at P20-A's sampling in a plain fill, and the checker at P20-A's sampling on RGB32F, on RGB16 and in a DirectX project. Against the code before each revision they evaluated: 15 before round 1, and the 4 review cases before round 2.
   - `projection-gpu-vs-cpu` compares the checker's sampling on DX12 and CPU under both bilinear filters. It also checks that a rotated map and a binary grey image are refused on both.
5. **Capability manifest.** `compositor:minification` is supported only outside the Height and Normal channels. A release gap `compositor:normal-unrecorded` names the refused uses and the recording that settles them.

## Alternatives Considered

- **Keeping decision 226's admissions** (any 8-bit magnification, 16-bit resampling, 8-bit grey everywhere). Rejected: `export-resize` s3 disproves the rule for 16-bit maps, and nothing records the rest (decision 001).
- **Keeping 8-bit magnification at every factor and transform**, the scope decision 218 took for one-channel textures. Rejected by the panel (C5): the same texture rule fails at 2 and 4 times on 16-bit codes.
- **Admitting the grey in P20-A's composite form only** (NormalMapDetail under a mask, over a covering layer). Rejected (G2): the decode does not hide the 16-bit code at 33 of 257 weights, a bottom layer passes its source raw, and P20-A records only the grey's direction. A rule narrow enough to be safe would be a fingerprint of P20-A's stack.
- **Admitting the grey at 1:1 and under Nearest** (GPT and Kimi in G3). Rejected: there the 16-bit code is moot, but the grey's value is not recorded, only its direction.
- **Fitting `export-resize` s3** (2 048 texels). This is new fitting work, not a fix of decision 226's scope, and it is seen only through the virtual normal maps. It is left to the recording below.
- **Refusing in `support.cpp` before mutation.** Not possible: the refusals depend on the bit depth, the channel count and the blue codes of the decoded image.

## Consequences

- A normal map on the Normal channel evaluates only at the set's size, under Nearest, or as P20-A's 16-times magnification of an 8-bit colour image on an RGB16F channel in an OpenGL project. Other resampled normal maps and every grey bitmap now fail explicitly. Before, they evaluated by analogy, and since decision 226 by its rule.
- P20-A's Normal map is refused and excluded until the recording below exists. Its four other maps stay exact.
- `export-resize` s3's virtual normals stay refused (resize is refused, decision 103). They are now documented as missing decision 226's rule by 2 048 and 6 880 texels.
- **Recording that settles the gap (owner: phase1.15_compositor-colour-fits).** Random-content 8- and 16-bit normal maps, with blue codes over 0-255, and 8-bit grey images with every code, on the Normal channel, in a plain Normal-mode fill as well as under NormalMapDetail:
  - at 1:1;
  - magnified 2, 3 and 16 times;
  - rotated by 30 degrees and shifted by 0.1;
  - minified 2 and 4 times;
  - under BilinearHQ, BilinearSharp and Nearest;
  - on RGB16F and RGB32F channels, in an OpenGL and a DirectX project.

  Each export is `documentMap/normal` at PNG 16 and OpenEXR 32f, two recordings.
