## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0.2_parity-contract, phase1.1_docmodel-types-manifest

## 2. Implementation
- [ ] 2.1 Author `painter-api-inventory.json` from the admitted public API documentation (documented symbols only, with the documentation anchor as evidence)
- [ ] 2.2 Author `uzpainter-additions.json` for UzPainter-only modules and operations
- [ ] 2.3 Write `capabilities.schema.json` for manifest entries
- [ ] 2.4 Implement `generate_capabilities.py` with the three statuses and the generation rules, and register it as a `build.zig` step emitting `capabilities.json`
- [ ] 2.5 Seed the release-gap entries listed in `docs/architecture/10-python-api.md` §3 and the desktop-only-omitted entries with their justifications

## 3. Tests
- [ ] 3.1 Determinism: two generations from the same inputs are byte-identical
- [ ] 3.2 Every entry validates against `capabilities.schema.json`
- [ ] 3.3 A `supported` entry without `tier_evidence` fails generation; a `desktop-only-omitted` entry without justification fails generation
- [ ] 3.4 The listed release gaps (paint layers and paint effects receiving bitmaps and projections, warp and UV-set-to-UV-set projections, UV-tile workflow, auto-unwrap, vector and font sources, material layering, USD export, TIFF/PSD/WebP/J2K export, arbitrary `.sbsar` evaluation) are present with status `release-gap`
- [ ] 3.5 Every `substance_painter` entry cites its public documentation anchor (an entry without one fails generation), and no brush-stroke symbol exists

## 4. Acceptance
- [ ] 4.1 All tests of this child green on the hosted CPU lane

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
