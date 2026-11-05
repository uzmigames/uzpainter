## 1. Prerequisites
- [x] 1.1 Inputs available: phase1.18_export-engine (archived 2026-10-12); the Wand v1 Tier 1 runner and goldens of phase1.25_pilot-wand (archived 2026-11-03; decision 396)

## 2. Implementation
- [ ] 2.1 (from phase1.25_pilot-wand item 2.7, decision 396) Fit and implement `infinite` padding on UV-islanded texture sets exactly on every texel, against `export-padding`, `export-padding-bevelled-cube`, `export-padding-sphere`, `export-padding-seam-*` and the admitted kernel probes (R-090 P5, P9), in decision 220 §5's order. History: the decisions listed in `proposal.md`
- [ ] 2.2 Implement the Height outside the islands as Painter's island-edge Normal reads it (decision 263: its own `infinite` ring in float32 before the L16F write), so the virtual Normal is exact on every covered texel; decision 245 §2's empty-Height case with its recording
- [ ] 2.3 Lift `CheckPadding` (decision 259) and `CheckIslandNormal` (decision 245) only for what 2.1 and 2.2 make exact; keep the rest refused, and rename the refusals' owner (`kIslandsOwner` and the messages naming `phase1.25_pilot-wand item 2.7`) to this task
- [ ] 2.4 Narrow EXC-010 by a new version as each part becomes exact (decision 395 §6), and withdraw it once the Wand v1 Tier 1 run passes with no exception

## 3. Tests
- [ ] 3.1 Every recorded islanded golden: exported `infinite` maps and the virtual Normal byte-identical to Painter's files, r1 and r2, on DX12 (decision 028)
- [ ] 3.2 The Wand v1 Tier 1 run on the production export (no `--diagnostic-measure-export`): `pass` with `exceptions_relied_on` empty

## 4. Acceptance
- [ ] 4.1 Acceptance: both cases exact on every texel of every recorded islanded golden; refusals lifted for that scope only; EXC-010 withdrawn

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass

## 6. Notes

- **Decision 401 (2026-11-05): this task owns the island-edge coverage near-tie and EXC-011 version 2's narrowing.** The Tunic's Tier 1 (`phase2/tier1/tunic-v10-current`, 4096 px) differs on 17 values of 3 covered island-edge texels (BaseColor 5, Height 9, Roughness 3): Painter counts each texel outside its island, UzPainter inside. Under decision 281's 1/256-texel vertex snap the three texel centres lie inside their triangles by 0.00004, 0.0016 and 0.0007 texel, each with an endpoint of the deciding edge within 1/64 texel of a rounding tie of that snap. A float32 clip-space edge test was tried and does not reproduce Painter's choice; no rule that does is identified. The owner widened EXC-011 to the island edge of every Tunic map (version 2) and sent the exact tie rule here. When 2.1 makes this coverage exact, narrow EXC-011 by a new version (back to the Normal's edge, as EXC-010's terms), and withdraw it once the Tunic passes with no exception (decision 398 §6).
