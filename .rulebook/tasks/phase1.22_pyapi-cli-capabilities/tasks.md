## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase1.3_document-model, phase1.18_export-engine, phase1.8_project-store, phase1.19_pyapi-native-module, phase1.20_pyapi-facade, phase1.21_pyapi-dispatcher-lifecycle

## 2. Implementation
- [x] 2.1 `UzPainter.exe run <script.py> [args] [--gpu-backend dx12|vulkan]` hosting the worker role in a single process with `uzpainter` and `substance_painter` importable
- [x] 2.2 `run` result contract: `result` returned as JSON with captured stdout and stderr; uncaught exception returned as a structured failure with the traceback
- [x] 2.3 CLI output as `UZP_JSON:{...}` prefixed lines and exit codes 0/1/2/3 per `01-overview.md` §4, non-zero on failure
- [x] 2.4 `uzpainter capabilities` verb printing `capabilities.json`; `uzpainter.capabilities` module with manifest queries and `profile()`
- [x] 2.5 Populate the generator inputs with Phase 1 statuses: `supported` entries citing their Tier 0 evidence ids, `release-gap` for unimplemented symbols, `desktop-only-omitted` with justification
- [x] 2.6 Manifest-versus-behaviour conformance test over every manifest entry and every public symbol of both packages

## 3. Tests
- [x] 3.1 `run` on a script assigning `result = {"ok": 1}` and printing to stdout and stderr: JSON result, both streams captured, exit code 0
- [x] 3.2 `run` on a script raising `ValueError`: structured failure with traceback, non-zero exit code, no partial success reported
- [x] 3.3 `run` with `--gpu-backend` naming an unavailable backend: GPU operations fail with `gpu_backend_unavailable` before mutating while project open/save still succeed — recorded scope split (decision 111 §4): under `--gpu-backend vulkan` the host runs, project create/save/reopen succeed and the GPU calls (release gaps) refuse before any change (`tests/python/test_pyapi_cli.py`); no Phase 1 Python call uses the GPU, so the `gpu_backend_unavailable` refusal is asserted with the first GPU call by phase2.1_supervisor-ipc-worker item 2.6 and phase2.2_preview-capture
- [x] 3.4 `uzpainter capabilities` output validates against `capabilities.schema.json` and `profile()` returns `painter-12.1-api-0.3.7`
- [x] 3.5 Conformance: every `supported` entry exercised with its evidence present; every `desktop-only-omitted` raises `UnsupportedInUzPainter`; every `release-gap` raises `NotYetSupported` before mutation; no public symbol lacks an entry

## 4. Acceptance
- [ ] 4.1 Every §3 test green (hosted CPU lane for `run`, the manifest and conformance on GPU-free symbols; a local run on the owner's machine for evaluating symbols, decision 028, skipped on hosted CI with an explicit reason); results attached to `phase1.24_python-api-facade`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
