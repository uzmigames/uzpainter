## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.3_document-model, phase1.18_export-engine, phase1.8_project-store, phase1.19_pyapi-native-module, phase1.20_pyapi-facade, phase1.21_pyapi-dispatcher-lifecycle

## 2. Implementation
- [ ] 2.1 `UzPainter.exe run <script.py> [args] [--gpu-backend dx12|vulkan]` hosting the worker role in a single process with `uzpainter` and `substance_painter` importable
- [ ] 2.2 `run` result contract: `result` returned as JSON with captured stdout and stderr; uncaught exception returned as a structured failure with the traceback
- [ ] 2.3 CLI output as `UZP_JSON:{...}` prefixed lines and exit codes 0/1/2/3 per `01-overview.md` §4, non-zero on failure
- [ ] 2.4 `uzpainter capabilities` verb printing `capabilities.json`; `uzpainter.capabilities` module with manifest queries and `profile()`
- [ ] 2.5 Populate the generator inputs with Phase 1 statuses: `supported` entries citing their Tier 0 evidence ids, `release-gap` for unimplemented symbols, `desktop-only-omitted` with justification
- [ ] 2.6 Manifest-versus-behaviour conformance test over every manifest entry and every public symbol of both packages

## 3. Tests
- [ ] 3.1 `run` on a script assigning `result = {"ok": 1}` and printing to stdout and stderr: JSON result, both streams captured, exit code 0
- [ ] 3.2 `run` on a script raising `ValueError`: structured failure with traceback, non-zero exit code, no partial success reported
- [ ] 3.3 `run` with `--gpu-backend` naming an unavailable backend: GPU operations fail with `gpu_backend_unavailable` before mutating while project open/save still succeed
- [ ] 3.4 `uzpainter capabilities` output validates against `capabilities.schema.json` and `profile()` returns `painter-12.1-api-0.3.7`
- [ ] 3.5 Conformance: every `supported` entry exercised with its evidence present; every `desktop-only-omitted` raises `UnsupportedInUzPainter`; every `release-gap` raises `NotYetSupported` before mutation; no public symbol lacks an entry

## 4. Acceptance
- [ ] 4.1 Every §3 test green (hosted CPU lane for `run`, the manifest and conformance on GPU-free symbols; self-hosted GPU runner for evaluating symbols); results attached to `phase1.24_python-api-facade`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
