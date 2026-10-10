## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: `phase3.7_fixtures-bracers-hat5`

## 2. Implementation
- [ ] 2.1 Classify every layer and effect of the three sets; import stroke-painted content as bitmaps where the documented export route preserves the output, otherwise record `not_migratable` with the reason and raise the owner scope question with `rulebook_task ask`
- [ ] 2.2 Record the body v6b Painter oracle through the documented API twice; hashes in `parity/manifests/tier1/body-v6b.json`
- [ ] 2.3 Rebuild body v6b in UzPainter: three 4096² sets in one project from the same stack JSON and resources with identical external mesh maps
- [ ] 2.4 Instrument memory admission on the body: VRAM tile budget, live tiles, evictions and peak RAM/VRAM per set and per project
- [ ] 2.5 Produce the size census: project bytes, external dependency bytes and retained history vs the matched `.spp` after Painter's documented compact-save, linked bytes counted on both sides
- [ ] 2.6 Record evaluation, export, save, reopen and compaction timings and peak memory for P5-PERF

## 3. Tests
- [ ] 3.1 Oracle stability of every body v6b golden classified before admission
- [ ] 3.2 Tier 1: every exported map of the three sets equal to the private goldens at native depth
- [ ] 3.3 UzPainter repeatability: two runs byte-identical
- [ ] 3.4 Save → close → reopen → export reproduces identical maps; compact keeps them identical; the file at rest has no `-wal`/`-shm` companion
- [ ] 3.5 Retention on body content: current and previous checkpoints plus the last 50 mutation revisions retained after compaction (Q11)
- [ ] 3.6 Admission test: a fourth 4096² set beyond the measured budget fails at creation with an explicit error; the three sets evaluate in sequence within budget
- [ ] 3.7 Reports in `parity/reports/phase4/`: Tier 1 numbers per map, census ratio against the 10 % candidate budget, timing and memory budgets, exceptions relied on

## 4. Acceptance
- [ ] 4.1 DAG gate P4-BODY met: equal maps; budgets measured; no `not_migratable` fixture without an owner scope decision

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
