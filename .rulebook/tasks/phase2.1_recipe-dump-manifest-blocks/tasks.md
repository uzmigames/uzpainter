## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.25_pilot-wand

## 2. Implementation
- [ ] 2.1 Recipe JSON schema covering every output-determining field of `03-…` §7 plus revision, profiles, app version and resource hashes
- [ ] 2.2 `uzpainter.project.dump_recipe()` with canonical JSON and SHA-256 digest
- [ ] 2.3 `uzpainter inspect <file.uzp>` printing the recipe without opening the project (no GPU, no lock)
- [ ] 2.4 Worker handler for the MCP `project_recipe` tool and `uzpainter://project/recipe` resource
- [ ] 2.5 Rebuild path replaying a dump and its referenced resources into a new project through the native API
- [ ] 2.6 `exportacao` block (`fontes`, `saidas`, `momento`, `preset`, `mapas`, `comparacao`, `evidencias`, `pendencias`) written with every export receipt

## 3. Tests
- [ ] 3.1 Dump schema tests on synthetic projects covering every node, effect and source kind available in Phase 2
- [ ] 3.2 Digest determinism: repeated dumps, a new session and save/reopen give the same digest; inert state (selection, collapsed) does not change it; an output-affecting edit does
- [ ] 3.3 `inspect` equals `dump_recipe()` for the same revision and runs without GPU or project lock
- [ ] 3.4 Rebuild from dump on a synthetic fixture: exports byte-identical to the original's
- [ ] 3.5 `exportacao` schema test on export receipts

## 4. Acceptance
- [ ] 4.1 Every §3 test green; results attached to `phase2.2_recipe-and-diagnostics`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
