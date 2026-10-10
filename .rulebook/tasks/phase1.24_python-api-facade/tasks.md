## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.3_document-model, phase1.18_export-engine, phase1.8_project-store

## 2. Children (each accepted before this parent closes)
- [ ] 2.1 `phase1.19_pyapi-native-module` accepted
- [ ] 2.2 `phase1.20_pyapi-facade` accepted
- [ ] 2.3 `phase1.21_pyapi-dispatcher-lifecycle` accepted
- [ ] 2.4 `phase1.22_pyapi-cli-capabilities` accepted
- [ ] 2.5 `phase1.23_pyapi-pipeline-adapter` accepted

## 3. Tests
- [ ] 3.1 Run the full Tier 0 API-probe comparison against `phase0.6_tier0-api-probes` goldens on one build on the self-hosted GPU runner: set→get readback, mask `None` rules, insertion rules, active-channel reset, event order; every probe exact
- [ ] 3.2 Run the wand v1 adapter fixture end to end on the same build: `painter_create.py`, `painter_layer_stack.py sync`, `painter_export.py` with pinned SHA-256, results returned as JSON
- [ ] 3.3 Regenerate `capabilities.json` from the same build and run the manifest-versus-behaviour conformance test

## 4. Acceptance
- [ ] 4.1 Acceptance (P1-PYAPI gate): the three pipeline scripts run unchanged through the adapter; API-probe goldens exact; results recorded in `parity/reports/phase1/` for the G1 gate record

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
