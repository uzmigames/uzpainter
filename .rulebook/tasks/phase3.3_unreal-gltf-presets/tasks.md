## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase2.10_pilot-tunic-recovery`

## 2. Children (mandatory)
- [ ] 2.1 Child accepted: `phase3.2_unreal-ue56-packed-preset`
- [ ] 2.2 Child accepted: `phase3.1_unreal-gltf-pbr-preset`

## 3. Integration
- [ ] 3.1 Run both presets on wand v1, belt v5 and tunic v10 through the plan compiler and generational publication
- [ ] 3.2 Output parity: each preset's files compared with Painter's export of the same preset on the same projects (private oracle, decoded values at native depth)
- [ ] 3.3 Consolidated consumer-gap report for both presets in `parity/reports/phase3/`
- [ ] 3.4 Regenerate the capability manifest with both presets at their proven status

## 4. Tests
- [ ] 4.1 Consumer-matrix row 8 (`08-export.md` §5.1) passes on wand v1 for the PNG/TGA and the DDS variants
- [ ] 4.2 The glTF consumer fixture passes on wand v1
- [ ] 4.3 Byte determinism: two exports of each preset from the same build, project and config are identical (EXP-05)

## 5. Acceptance
- [ ] 5.1 DAG gate P3-UNREAL met: fixtures load; packing confirmed

## 6. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 6.1 Update or create documentation covering the implementation
- [ ] 6.2 Write tests covering the new behavior
- [ ] 6.3 Run tests and confirm they pass
