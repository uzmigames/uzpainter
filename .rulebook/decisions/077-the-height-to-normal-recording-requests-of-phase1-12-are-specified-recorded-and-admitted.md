# 77. The height-to-normal recording requests of phase1.12 are specified, recorded and admitted

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.12_compositor-height-normal

## Context

`phase1.12_compositor-height-normal` left items 3.1, 3.3 and 4.1 open on five recordings that only the agent holding the Assets3D Painter lock may make (`parity/reports/phase1/compositor-height-normal.md` §5): (i) a Normal mesh map in the combination, (ii) SignedAddition on Height, (iii) Normal-channel partial coverage with Height, (iv) 8- and 16-bit Normal imports in OpenGL and DirectX projects, (v) the amplitude golden at 512, 1024 and 2048 px. The request leaves some points open. One project has one normal-map format and one document resolution, so (iv) and (v) need several goldens. Blending modes, the source of (ii) s3, the use of unnamed sets, the 8-bit copy and the domains are not stated.

The model panel was consulted under the owner's delegation on 2026-10-11 (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5):

| Claim | Verdicts |
|---|---|
| C1: every fill states its mode; Height fills Normal at 1; Normal-channel fills in Normal at the stated opacity; uniform colours in Working; (i) s3 two fills, Height below | PARTLY x3: pin every layer's mode, opacity and source in the manifest (done: the instruction sequence holds each) |
| C2: `height-normal-mesh-map-directx` on grid2x2, s0-s3 as (i), Sharp, same exports | AGREE x2, PARTLY x1 (the mesh map's orientation in a DirectX project is a measurement, not an assumption) |
| C3: (ii) s3 is grey A at 1; s4-s7 empty; Height PNG16 as L16 | PARTLY x3: document the s3 source |
| C4: (iii) s4-s7 repeat s0-s3 in NormalMapCombine | DISAGREE x2, PARTLY x1: not requested; leave them empty |
| C5: two import goldens on grid2x2, with s2-s3 the imports alone; 8-bit copy round(c16 / 257) | PARTLY x3: the split is forced; the "alone" sets contradict "each with the Height ramps" (two of three); the quantiser is sound, with no colour chunks in the PNG |
| C6: four resolution goldens; the Sobel one with every set in Sobel | PARTLY x3: only s0 in Sobel as requested; s1-s3 Sharp are a cross-project repeat of the 1024 golden |
| C7: new domains outside EXC-003's `tier0/height-normal/method` | AGREE x1, PARTLY x2 (split the imports into their own domain) |
| C8: one session, Legacy colour management, r1 = r2 per map, an unstable golden admitted with r1 the target (decision 032) and reported | AGREE x1, PARTLY x2 |

## Decision

1. **Ten goldens** under the current envelope (`tools/parity/tier0_semantics/current.py`, `request_goldens`), documented API except the Sobel sets (UI operator, decision 047), Legacy colour management, every fill in Normal at opacity 1 unless stated, uniform colours in Working:
   - `height-normal-mesh-map` (grid4x2, OpenGL, domain `tier0/height-normal/combination`): `normal-b` bound as the Normal mesh map of every set; s0 the mesh map alone, s1 + height ramps, s2 + `normal-a` on Normal, s3 both (Height fill below, Normal fill above); s4-s7 the same with Smooth (Sobel). Exports Normal_OpenGL, Normal_DirectX, `meshMap/normal_base` (PNG16), Height and Normal (EXR 32f).
   - `height-normal-mesh-map-directx`: grid2x2, DirectX, s0-s3 as above, Sharp.
   - `height-signed-addition` (grid4x2, `tier0/height-normal/height-blend`): s0 grey A in SignedAddition at 1 over the ramps, s1 at 0.5, s2 a uniform 0.25 at 1, s3 grey A at 1 onto the empty Height; s4-s7 empty. Height only as EXR 32f: the recorder keys outputs by texture set and map, so one map is exported once per golden; the EXR holds the stored signed value, and Height's PNG16 encoding is the export encoder's concern.
   - `height-normal-channel-coverage` (grid4x2, `combination`): the ramps in every set; above them `normal-a` on Normal at 0.5 (s0), 0.25 (s1), at 1 under a Black mask with a `mask-codes` fill (s2), a uniform (0.6, 0.4, 1) at 0.5 (s3); s4-s7 empty. Height exports with the Normal channel and the virtual maps, as every height-normal golden.
   - `normal-channel-import`, `normal-channel-import-directx` (grid2x2, `tier0/height-normal/import`): s0 `normal-a` over the ramps, s1 the 8-bit copy over the ramps; s2-s3 empty. New fixture `bitmaps/normal-a-8bit.png`: 8-bit RGB, no ancillary chunks, each code round(c16 / 257) of `normal-a` (never a tie).
   - `height-normal-resolution-512`, `-1024`, `-2048` (`tier0/height-normal/resolution`): the instruction sequence of `height-normal-plane-amplitudes` with only `default_texture_resolution` changed (the 256 px ramps magnified by the default projection); `height-normal-resolution-1024-sobel`: the 1024 golden with s0 in Smooth (Sobel).
   - The corpus's `start` and `applied_settings` now take the format and resolution from the `project.create` step; every earlier manifest is unchanged (`tier0_semantics check`).
2. **Recorded and admitted.** r1 (same session) and r2 (after save and reopen), `uzpainter parity record`, `store verify` ok:

| Golden | Maps | r1 = r2 | Private record (SHA-256) |
|---|---|---|---|
| `height-normal-mesh-map` | 40 | 40/40 | `245069a4495272c2fb68ca910182a6255a1df088c5ef47b8d2f909877f1c9642` |
| `height-normal-mesh-map-directx` | 20 | 20/20 | `0571d1d45aba0b765c551f5b2e0ef571570fc7104efe9bc4897f4c3a2c94127c` |
| `height-signed-addition` | 24 | 24/24 | `731b1e97ca020aaa21284d300e321a91ff71d564d1729d2d294391eafd327560` |
| `height-normal-channel-coverage` | 32 | 29/32 | `58fa28f33cdfefdb939ea05b34d0abe0ea05644f6328e21087428c79edba3ba3` |
| `normal-channel-import` | 16 | 16/16 | `eebb4246d50ec6d5d0d94cf4945bbefe9e2ef39dff343983def7ab7bc197a031` |
| `normal-channel-import-directx` | 16 | 16/16 | `835b59789f3325456ec740b130d64e2b636bb1829915585db8c753d779293e46` |
| `height-normal-resolution-512` | 16 | 16/16 | `e52b103f64176ebffec6a6a5972d27fe89c4a073640ea039a0bcb38166030162` |
| `height-normal-resolution-1024` | 16 | 16/16 | `5a63f7eca7893785e00aafd0f7ddf08950ed239910b6da053bb1ca9f1eab9592` |
| `height-normal-resolution-2048` | 16 | 14/16 | `0f02c91260dac1035dc0805eaada5a38c177261b1629939844023eb66d33fea2` |
| `height-normal-resolution-1024-sobel` | 16 | 16/16 | `6e51f5eccb47721bc14153c971559c61f42aef095345166afcb1a8397a9b9c26` |

   In `height-normal-resolution-1024-sobel`, s0's virtual maps differ from the Sharp golden's and every other map (s1-s3, and s0's Height and Normal) is byte-identical to `height-normal-resolution-1024` in both recordings: the UI value reached only s0, and the Sharp sets repeat exactly across projects.
3. **Two save-and-reopen divergences, r1 the target (decision 032).** `height-normal-channel-coverage` s2 (the masked Normal fill): the Normal channel differs by up to 2^-10 on 114 266 values, the virtual maps by up to 61 codes. `height-normal-resolution-2048` s2 (opacity 0.25): 4 and 5 values of the virtual maps, 1 code each. A second recording in a freshly started Painter process reproduced both r1 and both r2 map for map, so each divergence is deterministic. Neither golden joins an exception: EXC-003 selects only `tier0/height-normal/method`, and any bound for these r2 comparisons is phase1.12's to propose.

## Alternatives Considered

- One golden per request with sets in mixed formats or resolutions (impossible: both are per project).
- NormalMapCombine variants of (iii) and import-only sets in (iv) (rejected by the panel as unrequested).
- The Sobel resolution golden with every set in Sobel (rejected: the request names s0; the Sharp sets repeat the 1024 golden across projects).
- Exporting Height as PNG16 beside EXR in (ii) (not possible without a recorder change to output ids; the EXR carries the value).

## Consequences

phase1.12 can close 3.1 (SignedAddition) and 3.3 (mesh normal map, Normal coverage, imports, both conventions) against these goldens, and test whether z is per texel or per UV width at 512-2048 px, with its own task files unchanged here. The tier0 stability report counts 87 goldens.
