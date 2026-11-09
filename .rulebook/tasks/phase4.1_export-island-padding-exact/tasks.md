## 1. Prerequisites
- [x] 1.1 Inputs available: `phase3.1_export-island-padding` archived 2026-11-09 (decision 414 scope split); `phase1.18_export-engine`; the Wand v1, Sash v5 and Tunic v10 Tier 1 runners and goldens

## 2. Implementation
- [ ] 2.1 (from `phase3.1_export-island-padding` item 2.1, decision 414) Fit and implement `infinite` padding on UV-islanded sets exactly on every texel, against `export-padding`, `export-padding-bevelled-cube`, `export-padding-sphere`, `export-padding-seam-*` and the admitted kernel probes (`padding_corpus.py`, 36 probes), r1 and r2: the exact-tie sides at seam ends on Pythagorean folds, multi-facet chains, window-side ties and poles; the cube, sphere and kernel-probe residuals. Separating evidence named in the moved notes: an end-overhang sweep on an oblique seam (the pair turned in the mesh about y by a Pythagorean angle, positions still dyadic); the float32 tangent-frame and GPU-rsqrt turn models; the 30 ring texels past A's bottom end at shift +7/64 (a tap-order or weight class)
- [ ] 2.2 (from `phase3.1_export-island-padding` item 2.2) Implement the Height outside the islands as Painter's island-edge Normal reads it (decision 263: its own `infinite` ring in float32 before the L16F write), so the virtual Normal is exact on every covered texel; decision 245 §2's empty-Height case with its recording (`export-padding-normal-empty-height`)
- [x] 2.3 Lift `CheckIslandNormal` (decision 245) only for what 2.1 and 2.2 make exact, or as the owner decides the Normal's edge; keep the rest refused, naming this task (`kIslandsOwner`) — done 2026-11-09 under the owner's decision (decision 417, EXC-014; see §6). What stays refused (the empty Height, diagnosticMap and statistics sources of the normal, mixed files, `passthrough`) lifts with 2.2 as it becomes exact
- [ ] 2.4 Narrow EXC-010, EXC-011 v3, EXC-012, EXC-013 and EXC-014 by new versions as each part becomes exact, and withdraw each once its golden (or, for EXC-013 and EXC-014, production) passes with no exception (decisions 395 §6, 398 §6, 410 §4, 414, 417)

## 3. Tests
- [ ] 3.1 Every recorded islanded golden: exported `infinite` maps and the virtual Normal byte-identical to Painter's files, r1 and r2, on DX12 (decision 028)
- [ ] 3.2 The Wand v1, Sash v5 and Tunic v10 Tier 1 runs on the production export (no `--diagnostic-measure-export`): `pass` with `exceptions_relied_on` empty

## 4. Acceptance
- [ ] 4.1 Acceptance: both cases exact on every texel of every recorded islanded golden; `CheckIslandNormal` lifted for that scope only; EXC-010, EXC-011, EXC-012, EXC-013 and EXC-014 withdrawn

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass

## 6. Notes

- **Created 2026-11-09 by decision 414's scope split.** At the move, production writes `infinite` padding on islanded sets under EXC-013 (every covered texel exact, the padding free; each such file listed in the receipt's `exceptions_relied_on`) and refuses a combined virtual Normal on them (`CheckIslandNormal`). The last state of the fit is in the archived `phase3.1_export-island-padding` notes (2026-11-08, seam-end overhang sweep, cf4c215e): `padding_goldens.py` 80 of 104 files exact r1 and r2, ring 2,956 and gutter 9,812 values differing, covered 0; kernel probes 2,415 ring texels; recorded coverage 0 wrong on the three coverage probes (decision 408).
- **2026-11-09, decision 417 (the owner's "Incluir a borda").** Item 2.3 is done under EXC-014 v1 (`production_export`, selector `export/islanded-virtual-normal-edge`, bound `max_abs_diff` 0 over `covered_interior`): `IslandNormalLifted` (padding.h) admits a production file whose every channel reads `Normal_OpenGL` or `Normal_DirectX`, padded `infinite` over incomplete coverage, computed by decision 308's rule; `IslandNormalHeightRefusal` (guards.h) keeps decision 245 §2's empty Height refused in the export and the preflight. The receipt lists EXC-014 per file beside EXC-013. Still refused: the empty Height, diagnosticMap and statistics sources of the normal, a file mixing it with another source, `passthrough`, and `uzpainter.diagnostics`' views. Production Tier 1 (commit 435dc9c3, `UZP_TIER1_PRODUCTION=1`): Wand v1 `pass`, every covered value equal on BaseColor, Height, Metallic and Roughness, the Normal differing on 42 covered values, all on the island edge (6,301 edge texels); Sash v5 `pass`, the Normal differing on 880 covered values, all on the island edge (43,634 edge texels), every other covered value equal; both rebuilds byte-identical; Tunic v10 not run (over 20 minutes, the coordinator's batch). Items 2.1, 2.2 and 2.4 (EXC-014 narrowed as 2.2 makes the Height outside the islands exact) remain; 3.2 still needs `exceptions_relied_on` empty.
