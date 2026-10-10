## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.25_pilot-wand
- [ ] 1.2 Child accepted: phase2.1_recipe-dump-manifest-blocks
- [ ] 1.3 Child accepted: phase2.1_recipe-diagnostic-views

## 2. Implementation
- [ ] 2.1 Wand v1 rebuild-from-dump scenario: dump, rebuild into a new project from the dump and its resources, export both with the wand's export configuration
- [ ] 2.2 Report writer for `parity/reports/phase2/recipe-rebuild-wand.json`

## 3. Tests
- [ ] 3.1 Wand v1 rebuild: every exported file byte-identical and recipe digests equal
- [ ] 3.2 Diagnostics on wand v1: `isolate` on each root group restores state; `material_views` on the wand's material masks matches the exported maps

## 4. Acceptance
- [ ] 4.1 DAG gate met: rebuild-from-dump equality on wand; report written to `parity/reports/phase2/recipe-rebuild-wand.json`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
