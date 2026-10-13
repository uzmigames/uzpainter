## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.3_document-model, phase1.18_export-engine, phase1.8_project-store. Open: phase1.3 is archived; phase1.18_export-engine waits on phase1.14_compositor-core and phase1.15_export-plan-compiler, and phase1.8_project-store waits on phase1.6_store-save-retention and phase1.7_store-inspect-census (their children's code, which this API uses, is on main)

## 2. Children (each accepted before this parent closes)
- [x] 2.1 `phase1.19_pyapi-native-module` accepted (archived 2026-10-12)
- [x] 2.2 `phase1.20_pyapi-facade` accepted (archived 2026-10-12)
- [x] 2.3 `phase1.21_pyapi-dispatcher-lifecycle` accepted (archived 2026-10-12)
- [x] 2.4 `phase1.22_pyapi-cli-capabilities` accepted (archived 2026-10-12)
- [x] 2.5 `phase1.23_pyapi-pipeline-adapter` accepted (archived 2026-10-12)

## 3. Tests
- [ ] 3.1 Run the full Tier 0 API-probe comparison against `phase0.6_tier0-api-probes` goldens on one build in a local run on the owner's machine (decision 028; the local run report is the evidence): set→get readback, mask `None` rules, insertion rules, active-channel reset, event order; every output in the supported scope exact, every other one listed with its kind and owner in the report §3 — run on 2026-10-12: 26 traced replays exact in the supported scope (`parity/reports/phase1/python-api-facade.md` §4). Owners assigned by decision 117: P20-A and P20-B, with `phase1-reload-resources` recording 1 s9/s12, to phase1.14_compositor-core item 2.9, moved by decision 130 to phase1.15_compositor-colour-fits item 2.1; `phase1-reload-resources` recording 2 s9/s12 to phase5.2_parity-report-tiers item 2.10. Open: Dota 2's user-channel labels wait for the owner's clean-room ruling (`.metadata.json` question q1)
- [x] 3.2 Run the wand v1 adapter fixture on the same build: `painter_create.py`, `painter_layer_stack.py sync`, `painter_export.py` with pinned SHA-256; create and sync return their JSON results, export runs its pinned bytes and returns its result or the export engine's explicit refusal of the 16-bit sRGB8 BaseColor (release gap, owner phase1.25_pilot-wand item 2.6; decision 116) — `tests/adapters`: 44 passed (report §4.1)
- [x] 3.3 Regenerate `capabilities.json` from the same build and run the manifest-versus-behaviour conformance test — trace of 26 replays, decisions 112 and 116 §5; `test_pyapi_cli.py`, `test_capability_conformance.py`, `tests/capabilities` pass (report §4)
- [ ] 3.4 (decision 189) P22-B, the 257 pending-evidence Painter symbols the requests of decision 188 do not exercise: by module, add the probe vocabulary each needs (explicit calls only, fake support and tests), author requests that name the symbols they exercise, and judge each plugin, UI, logging and export-status symbol as a safe probe or another evidence route recorded as an amendment to decision 112

## 4. Acceptance
- [ ] 4.1 Acceptance (P1-PYAPI gate): the three pipeline scripts run unchanged through the adapter, as item 3.2 states them; API-probe goldens exact apart from the named exclusions with their owners; results recorded in `parity/reports/phase1/` for the G1 gate record. The wand's exported maps and their parity are not accepted here: they are `phase1.25_pilot-wand` items 2.6, 3.1 and 4.1 (decision 116) — open with item 3.1 (owner question q1); evidence in `parity/reports/phase1/python-api-facade.md`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation — decisions 115 and 116, `docs/architecture/03-project-model.md`, `10-python-api.md`, `src/python/PYAPI.md`, `python/FACADE.md`, the report
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass — the affected tests (report §4, §4.1); the full suite is the coordinator's batch
