## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase2.10_pilot-tunic-recovery`

## 2. Children (mandatory, in dependency order)
- [ ] 2.1 Child accepted: `phase3.1_uze-uztexture-writer`
- [ ] 2.2 Child accepted: `phase3.2_uze-uzmat-preset`
- [ ] 2.3 Child accepted: `phase3.3_uze-consumer-fixture`

## 3. Integration
- [ ] 3.1 Run the UzEngine preset end to end on wand v1, belt v5 and tunic v10 through the export plan compiler and generational publication (`08-export.md` §5)
- [ ] 3.2 Consolidate the per-asset consumer gaps (SpecularWeight, SM5 opacity route, any binding the fixture rejects) into one gap report in `parity/reports/phase3/`
- [ ] 3.3 Regenerate the capability manifest with the UzEngine preset and its outputs at their proven status

## 4. Tests
- [ ] 4.1 Consumer-matrix row 9 (`08-export.md` §5.1) passes on wand v1 through the fixture of `phase3.3_uze-consumer-fixture`
- [ ] 4.2 Same build, project and config yield byte-identical `.uzmat`, `.uztexture` and canonical maps across two runs (EXP-05)

## 5. Acceptance
- [ ] 5.1 DAG gate P3-UZE met: the preset loads and renders in the external UzEngine fixture; gaps listed

## 6. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 6.1 Update or create documentation covering the implementation
- [ ] 6.2 Write tests covering the new behavior
- [ ] 6.3 Run tests and confirm they pass
