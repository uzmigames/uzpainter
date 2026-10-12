## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.24_python-api-facade (accepted without the wand's exported maps: the 16-bit export of the sRGB8 material channels is this task's item 2.6, and the five-map export and its parity are items 3.1 and 4.1; decision 116)

## 2. Implementation
- [x] 2.1 Author `parity/manifests/phase1/wand-v1.json` with the independently authored inputs, instruction sequence, settings and software identities (decision 124: the decision-099 request `parity/envelopes/painter-12.1.5_js-api.1.1.20/requests/phase1/tier1/wand-v1.json` under the current 12.1.5 envelope, decision 037; admitted to that envelope's `manifests/` by recording R9, item 2.2; the UzPainter build hash is named per run in the report)
- [ ] 2.2 Record the Wand v1 Tier 1 goldens in Painter 12.1.0 through the oracle recorder (documented API rebuild from the same inputs), twice per golden (same session; after save/reopen), and store the blobs in `UZP_PARITY_STORE` with their hashes in the manifest
- [ ] 2.3 Classify oracle stability per map; record any content that cannot be migrated through the documented API as `not_migratable` with the reason
- [x] 2.4 Write the Tier 1 runner that rebuilds Wand v1 through the pipeline adapter (`painter_create`, `sync`, `painter_export` unchanged, pinned by SHA-256) on DX12 with the same external mesh maps (decision 124: `tests/parity/tier1/wand_v1/runner.py`)
- [x] 2.5 Write the comparison step: decode both sides at native depth, classify channels by measured storage format, compute the `docs/architecture/14-parity-testing.md` §4 diagnostics and write `parity/reports/phase1/tier1-wand-v1.json` (decision 124: `tools/parity/tier1/compare.py`, FLIP as a diagnostic through the pinned `flip-evaluator` 1.7; the report is written by the local run of 3.1, `UZP_TIER1_REPORT`)

- [ ] 2.6 (decision 103, from phase1.18_export-engine item 6.1) Fit and implement the export of sRGB8 material channels (BaseColor, Specular, Emissive) exactly: the PNG 16 encode (PNG 8 is fitted: the UNORM write of the IEC encoding of the linear value) and the evaluator's linear read-out of their export-valued template constants, against recording R-090 `export-bit-depth` (and R-090 P10); until then the export refuses them before writing
  - Progress (decision 126; open): the encode is exact (decision 091's GPU encode, exponent 0.41666: 258/258 values, 134/134 PNG files of four goldens, 120/120 end-to-end files of `export-bit-depth` s0-s3 and s6) and lifted; the default template's constants and the sRGB8 Specular/Emissive channel defaults are linear and observed. Open: the linear base of the other 25 templates is inferred from its PNG 16 code only and every export depending on it is refused; it needs an OpenEXR 32f export of the empty BaseColor on one 48107 template, one OpenPBR template and one sRGB8-Specular template (owner Painter session)
- [ ] 2.7 (decision 103, from phase1.18_export-engine item 6.1) Fit and implement `infinite` padding on UV-islanded texture sets exactly (the seam ring and the copy dilation of decision 090's partial fit) against recordings `export-padding`, `export-padding-bevelled-cube`, `export-padding-sphere` and `export-padding-seam-*` (R-090 P5, P9); until then the export refuses it before writing
  - Progress (decision 127; open, refusal kept): the seam ring takes the far island's value (B's ring is A's interior exactly); A's ring blends B's last row with B's ring by weights periodic in 3 A texels (0.4821, 0.5080, 0.3240, 0.3109), not an affine unfold with bilinear sampling, 2x2 supersampling or the mask at the across-seam UV. Unknown: the seam-coordinate rule, the pass order, the sphere pole wedges. Next: the recorded seam goldens at 1024, then a scale-ratio-1 and ratio-2 seam probe if needed

## 3. Tests
- [ ] 3.1 Tier 1 equality: every exported Wand v1 map per set equal to its private golden in a local DX12 run on the owner's machine (decision 028; the local run report is the evidence)
- [ ] 3.2 Repeatability: run the rebuild and export twice in separate processes; every file byte-identical
- [ ] 3.3 Save/reopen: save the rebuilt project, reopen it and export again; maps equal to the first export
- [x] 3.4 Oracle availability: a missing golden blob fails the comparison as `oracle_unavailable`, never as a pass (`tests/parity/tier1/test_tier1_compare.py`)
- [x] 3.5 Guard: the repository guard passes on the manifest and report and rejects a planted copy of a recorded golden (guard contract test on synthetic 4x4 fixtures, `tests/parity/tier1/test_tier1_compare.py`, with the committed Wand request and a report the runner writes for it; guard rule for `parity/reports/<phase>/tier<tier>-*.json`; the admitted manifest and the real Wand report stay open under 4.1)

## 4. Acceptance
- [ ] 4.1 Acceptance (P1-WAND gate): maps equal and byte-stable across two runs; report published for the G1 gate record, listing any exceptions relied on (none expected)
- [ ] 4.2 Schedule checkpoint (decision 035): when the pilot completes, pass or fail, record in `docs/roadmap.md` a re-forecast of every remaining phase from this slice's measured wall-clock, failure causes and exception counts, marking which estimates are measured and which stay extrapolated

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
