## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase1.3_document-model, phase1.18_export-engine, phase1.8_project-store. All three are archived: `.rulebook/archive/2026-10-10-phase1.3_document-model`, `.rulebook/archive/2026-10-12-phase1.18_export-engine` and `.rulebook/archive/2026-10-13-phase1.8_project-store`

## 2. Children (each accepted before this parent closes)
- [x] 2.1 `phase1.19_pyapi-native-module` accepted (archived 2026-10-12)
- [x] 2.2 `phase1.20_pyapi-facade` accepted (archived 2026-10-12)
- [x] 2.3 `phase1.21_pyapi-dispatcher-lifecycle` accepted (archived 2026-10-12)
- [x] 2.4 `phase1.22_pyapi-cli-capabilities` accepted (archived 2026-10-12)
- [x] 2.5 `phase1.23_pyapi-pipeline-adapter` accepted (archived 2026-10-12)

## 3. Tests
- [x] 3.1 Full Tier 0 API-probe comparison on one build: all 36 current traced replays passed in the supported scope, with every excluded output and owner listed in report section 3. Local run 2026-10-19 (America/Sao_Paulo), commit `3b7c70afe9dc1ce39f4311a0888293896fee79f4`: 36 passed, 0 skipped, exit 0, 1173.02 s. Native 2, lifecycle/events 8, facade 26; exact trace-to-test coverage and build identity in report section 4.2. Dota 2 label policy remains decision 299; exclusions and their owners remain unchanged.
- [x] 3.2 Run the wand v1 adapter fixture on the same build: `painter_create.py`, `painter_layer_stack.py sync`, `painter_export.py` with pinned SHA-256; create and sync return their JSON results, export runs its pinned bytes and returns its result or the export engine's explicit refusal of the 16-bit sRGB8 BaseColor (release gap, owner phase1.25_pilot-wand item 2.6; decision 116) — `tests/adapters`: 44 passed (report §4.1)
- [x] 3.3 Regenerate `capabilities.json` from the same build and run the manifest-versus-behaviour conformance test — trace of 26 replays, decisions 112 and 116 §5; `test_pyapi_cli.py`, `test_capability_conformance.py`, `tests/capabilities` pass (report §4)
- [x] 3.4 (decision 189) P22-B authoring: decisions 295, 296 and 297 provide explicit probe vocabulary, fake support, tests and 18 requests for 220 symbols, plus amended evidence routes for 33. The current 253-symbol scope reconciles the original 257: add ExportStatus.Error, subtract three colormanagement symbols already supported and two display symbols requested by decision 188. Authoring only is complete; recordings, admission and compared replays remain required under 4.1 and decision 112, and every pending-evidence status is preserved. Evidence: python-api-facade.md section 5.

## 4. Acceptance
- [ ] 4.1 Acceptance (P1-PYAPI gate): the three pipeline scripts run unchanged through the adapter, as item 3.2 states them; API-probe goldens exact apart from the named exclusions with their owners; results recorded in `parity/reports/phase1/` for the G1 gate record. The wand's exported maps and their parity are not accepted here: they are `phase1.25_pilot-wand` items 2.6, 3.1 and 4.1 (decision 116) — item 3.1 is closed (report section 4.2); open for the outstanding P22-B recordings, admission and compared replays (decisions 112, 295-297); evidence in `parity/reports/phase1/python-api-facade.md`. Progress 2026-10-20 (report section 7, decision 319): the ten admitted observed API-probe goldens P21-A to P21-G, R-095 P7, R10 engine computations and P23-A have compared replays. All ten are exact apart from their named exclusions with owners, and tier0-trace.json holds 46 compared replays. The remaining open seams are the 18 P22-B recordings and the `get_default_export_path` release gap (P21-B s3, owner this item)

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation — decisions 115 and 116, `docs/architecture/03-project-model.md`, `10-python-api.md`, `src/python/PYAPI.md`, `python/FACADE.md`, the report
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass — the affected tests (report §4, §4.1); the full suite is the coordinator's batch
