## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: `phase2.10_pilot-tunic-recovery` (parent input), `phase3.2_uze-uzmat-preset`; private oracle store from `phase0.5_private-oracle-store` available on the owner's machine for local runs (decision 028) — all archived: `.rulebook/archive/2026-11-05-phase2.10_pilot-tunic-recovery/`, `2026-11-09-phase3.2_uze-uzmat-preset/`, `2026-10-10-phase0.5_private-oracle-store/`; also `2026-10-10-phase0.9_normal-convention-fixture/` (item 2.4's convention); the store is present under `%LOCALAPPDATA%\UzPainter`

## 2. Implementation
- [ ] 2.1 Fixture manifest `parity/manifests/consumers/uzengine/wand-v1.json`: executable identity and hash, test scene, qualified mesh route, pinned generation, expected bindings
- [ ] 2.2 Runner, run locally on the owner's machine (decision 028), invoking UzEngine's own executable as an external process through the generation-pinning delivery adapter
- [ ] 2.3 Load-and-render check reading the engine's load report and verifying each slot binding of the UzEngine preset table
- [ ] 2.4 Normal convention check against the convention settled by `phase0.9_normal-convention-fixture`
- [ ] 2.5 Lossy-derivative comparison of decoded `.uztexture` levels against canonical maps (`14-parity-testing.md` §4)
- [ ] 2.6 Gap report in `parity/reports/phase3/` (SpecularWeight, SM5 opacity route, rejected bindings, mesh route used)
- [ ] 2.7 Explicit failure when the UzEngine executable or its scene is unavailable; never reported as a pass

## 3. Tests
- [ ] 3.1 Consumer-matrix row 9 (`08-export.md` §5.1) on wand v1: loads, renders, bindings as expected
- [ ] 3.2 Defect detection: a `.uzmat` with the ORM texture on the albedo pin is rejected by the binding check
- [ ] 3.3 Defect detection: an albedo `.uztexture` written with linear instead of sRGB metadata is flagged
- [ ] 3.4 Missing-executable case fails the fixture with an explicit unavailable status
- [ ] 3.5 Build check: no include path, library path or build step of UzPainter refers to a UzEngine checkout

## 4. Acceptance
- [ ] 4.1 Child acceptance met and reported to `phase3.4_uzengine-preset`: row 9 passes on wand v1; lossy-derivative numbers and gap report published

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass

## 6. Blocked on owner inputs (2026-11-10)

Survey of the consumer, read only; nothing in `E:\UzmiGames\UzEngine` was built, run or written.

- **How the fixture runs (planned, after `tools/consumers/gltf.py`).** An opt-in GPU test rebuilds
  wand v1 with the shipped `uzengine` preset, as `tests/parity/tier1/test_uze_wand.py` does, under
  pytest's `tmp_path`. It writes a UzEngine project (`contentRoot`, `defaultScene`) there. The
  generation's `files/`, the `.uzmat` and the wand OBJ cooked by `uzmesh` (the route phase0.9 §8
  qualified, not the glTF cook) go under that content root. It then runs `uzengine.exe` as a separate
  process with `--screenshot`, `--frames`, `--run-manifest` and `--view-mode`. The engine is invoked;
  UzPainter's build never names it. The exact flags are not settled, because no run was made.
- **Owner input 1: the executable identity (items 2.1, 2.2, 3.1).** No UzEngine build has a commit
  identity. `E:\UzmiGames\UzEngine\runtime\build\bin\uzengine.exe` (2026-10-23 02:05) predates
  HEAD `bb5b5565` (02:13). It was built from a working tree with 126 uncommitted entries that another
  session is changing. The many `runtime/build/readiness-*` builds are that session's experiments.
  Phase0.9 built `f4dcfc46` from `git archive` outside both repositories, which `AGENTS.override.md`
  (2026-10-24) now forbids. The owner names the commit and where its clean build lives. The manifest
  then records that commit and the executable's SHA-256.
- **Owner input 2: where the engine may write (item 2.2).** Each run writes its log to
  `%LOCALAPPDATA%\UzEngine\logs\` (`engine/logging/log.cpp`, no override flag). It writes its shader
  cache beside the executable (`<exe dir>/cache/shaders`, `shader_manager.cpp`). Neither place is an
  exception of `AGENTS.override.md`. The project, scene, cooked mesh and screenshots can stay under
  pytest's `tmp_path`.
- **Open design point: the "engine's own load report" (items 2.3, 3.2).** At `bb5b5565` the engine
  reports no binding per slot. `--run-manifest` (`uzengine.run-manifest/1`) records the executable,
  scene, CVars and captures, but no materials. `uz.scene.get_material` exposes only the albedo id and
  scalar material fields such as `use_orm` and `blend_mode`. `GetOrParseUzmat`
  (`engine/ecs/loaders/scene_loader.cpp`) resolves the pins, but logs nothing. Two routes exist:
  - binding evidence from the engine's debug views (`--view-mode albedo|roughness|metallic|ao|worldnormal`),
    which have no emissive view;
  - a binding report added on the UzEngine side. That is UzEngine work, to be reported, never
    compensated here.

  This is decided with Codex once input 1 is settled.
- **Offline work deferred on purpose.** Item 3.5 already has its check: the vendoring check's
  `build-path` rule names any include or library path into a UzEngine checkout
  (`tools/vendoring/vendor_check.py`, `tests/vendoring/test_vendor_check.py`). It is ticked once it runs
  on the fixture run's build. Item 2.5 needs a file-level decode of a published `.uztexture` against
  its canonical PNG 16. Today the test-only decoder (`tests/export/bc_decoder_test.cpp`) only runs on
  authored data inside `uzp-texture-tests` (case `lossy_derivative`). That native addition waits for
  the fixture design, so it is written once, not twice.
