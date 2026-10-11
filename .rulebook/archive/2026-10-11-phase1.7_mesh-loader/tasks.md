## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase1.3_document-model, phase0.9_normal-convention-fixture

## 2. Children (each accepted before this parent closes)
- [x] 2.1 `phase1.4_mesh-importers` accepted
- [x] 2.2 `phase1.5_mesh-tangents-certificate` accepted
- [x] 2.3 `phase1.6_mesh-reload` accepted

## 3. Tests
- [x] 3.1 Run the complete `docs/architecture/12-mesh-import.md` §9 fixture set on one build: mirrored UVs, hard edges, negative OBJ indices, n-gons, duplicate material names, instances/transforms, units, multi-set body, coincident opposite faces
- [x] 3.2 Run the reload/rename/split fixtures (bindings preserved or deliberately rejected)
- [x] 3.3 Re-run the normal-convention fixture with the production loader and tangents: Painter hemisphere bake (private oracle) vs UzPainter in tangent space, and the same map shaded in UzEngine's own executable as an external consumer, in a local run on the owner's machine (decision 028)

## 4. Acceptance
- [x] 4.1 Acceptance (P1-MESH gate): `12-…` §9 fixtures pass; results recorded in `parity/reports/phase1/` for the G1 gate record (certificate and reload fixtures)

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

## Evidence

`parity/reports/phase1/mesh-loader.md` (owner's machine, 2026-10-11, commit `54db879` plus this
task's working tree). One build `zig build painter mesh-tests` (exit 0, no warnings):
`uzp-mesh-tests.exe run` 18 cases PASS, `uzp-mesh-reload-tests.exe run` 8 cases PASS,
`python -m pytest tests/mesh` 29 passed. Normal-convention re-run over the production importer and
production MikkTSpace frames: `python -m tools.parity.normal_convention check --prototype
uzp-normal-bake.exe` exit 0, every residual and verdict of `parity/semantics/tangent-frame.json`
reproduced against Painter's two recordings; the UzEngine leg (its own executables at commit
`f4dcfc4`, separate processes) gives 18 renders pixel-identical to the Phase 0 consumer run and the
same `directx` verdict. Full gate: `python -m mypy` (178 files, no issues), `ruff check .`,
`ruff format --check .`, `python -m pytest`, `python -m tools.parity.guard` (2314 files, 0 blocked).

## Hosted CPU lane

- Run `38100063195` on commit `8e5f3bc` (2026-10-11): `tests/mesh/test_mesh_import.py`,
  `test_mesh_certificate.py` and `test_mesh_reload.py` all passed. `src/mesh/` and every child test
  file are byte-identical between `8e5f3bc` and this tree, so that run is the hosted evidence for
  the §9 fixtures; the Painter comparison skips there with `oracle_unavailable` (decision 028).
- Open after the owner's next push: `tests/mesh/test_mesh_loader.py`, new in this task, first runs
  on the hosted lane then. It must show one `zig build mesh-tests` with exit 0 and no build-path
  violation.
