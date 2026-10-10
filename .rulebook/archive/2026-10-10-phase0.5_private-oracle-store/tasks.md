## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.2_parity-contract

## 2. Children
- [x] 2.1 Child accepted: phase0.3_oracle-store-cli (store, `parity fetch/verify/record`, local oracle run procedure)
- [x] 2.2 Child accepted: phase0.4_oracle-store-guard (pre-commit and CI content guard)

## 3. Integration tests
- [x] 3.1 On the owner's machine: record an authored sample with `parity record`, delete the local copy, `parity fetch` it by manifest and `parity verify` the hash
- [x] 3.2 On the same commit: the guard blocks a recorded PNG and a recorded JSON readback and passes an authored fixture image and an authored expectation JSON

## 3a. Local oracle run (moved from phase0.3_oracle-store-cli 2.5, owner answer q1 2026-10-10; decision 028)
- [x] 3a.1 Local oracle run procedure documented (`parity/STORE.md` §5.1) and executed once on the owner's machine (GPU, licensed Painter 12.1.0, `UZP_PARITY_STORE`), decision 028; its local run report (commands, machine, GPU, driver, build hash, results) recorded as the evidence

## 4. Acceptance
- [x] 4.1 Acceptance gate (P0-STORE): fetch/verify round trip on the owner's machine; guard blocks a recorded PNG and a recorded JSON readback and passes an authored fixture image and an authored expectation JSON

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

## Evidence (2026-10-10, owner's machine BOLADO: Windows 11 Pro 10.0.26200, NVIDIA GeForce RTX 4090 driver 32.0.16.1714, Adobe Substance 3D Painter 12.1.0 installed (uninstall registry entry), Python 3.13.9, jsonschema 4.25.1; build hash: working tree on `main` at 6a2f26cc66bb52552454726f594dca0a4eec20ba plus this task's uncommitted files)
- 1.1, 2.1, 2.2: `phase0.2_parity-contract`, `phase0.3_oracle-store-cli` and `phase0.4_oracle-store-guard` are archived (`.rulebook/archive/2026-10-10-*`) with every checklist item checked.
- 3a.1 local oracle run (`parity/STORE.md` §5.1), `UZP_PARITY_STORE` unset, store at the default `C:\Users\Bolado\AppData\Local\UzPainter\parity-store` (outside the repository). Inputs authored by the run (a 4x4 RGB PNG and a JSON readback `{"call": "substance_painter.layerstack.Node.get_opacity", "value": 0.75}`), manifest copied from `tests/parity/guard_data/authored-expectation.json` with golden `local-run/store-gate` and Painter build id `local-run-authored`, all in the session scratch folder; the recorder's run waiting in the oracle inbox was not imported (owned by `phase0.3_painter-oracle-recorder`). Commands and exit status:
  - `python -m tools.parity.store init` → 0 (`store ready at ...\parity-store`)
  - `python -m tools.parity.store record <manifest> --record-id authored-gradient --kind exported_map --file authored-gradient.png` → 0; local copy SHA-256 `505d27a19e39058afe37424c2c2bc8c6264aa75ec8c44c506ba190d982086b87`; local copy deleted
  - `python -m tools.parity.store fetch <manifest> --out <scratch>/fetched` → 0 (`authored-gradient 505d27a19e39 available`); fetched file SHA-256 `505d27a1...6b87` = manifest `private_records[0].sha256`
  - `python -m tools.parity.store verify <manifest>` → 0 (available)
  - `python -m tools.parity.store record <manifest> --record-id opacity-readback --kind api_readback --file opacity-readback.json` → 0 (SHA-256 `5691126e048723c3d0c2b69f6c49eaabf33f78f0440e633719be8ce61eb3ba32`)
  - §5.1 step 2: `python -m tools.parity.store verify` → 0 (`store ...\parity-store: ok`); `verify <manifest>` → 0 (both records available); `verify parity/manifests` → 0 (the folder is the recorder task's uncommitted work; its one manifest names no private record yet)
  - hosted lane: `env -u UZP_PARITY_STORE LOCALAPPDATA=<empty> python -m tools.parity.store verify <manifest>` → 1, both records `oracle_unavailable (no private store here)`
- 3.2 / 4.1 guard against the real store, through the committed `.githooks/pre-commit` (`git -c core.hooksPath=<repo>/.githooks`, `PYTHONPATH=<repo>`) in a throwaway git repository in the scratch folder:
  - commit of `parity/fixtures/images/authored-checker.png` + `parity/manifests/guard/srgb8-checker-decode.json` (from `tests/parity/guard_data/`) → 0 (`2 files checked, 0 blocked`)
  - commit of the fetched PNG at `parity/fixtures/images/basecolor.png` → 1 (`BLOCKED ...: [store-hash] SHA-256 505d27a1...6b87 is in the private store index`)
  - commit of the readback at `notes/opacity-readback.json` → 1 (`BLOCKED ...: [store-hash] SHA-256 5691126e...ba32 is in the private store index`); the throwaway repository ends with 1 commit
  - `python -m tools.parity.guard` on the UzPainter working tree with the real store → 0 (`1275 files checked, 0 blocked`)
- Store contents after the run: 2 blobs, corpus `corpora/local-run-authored/local-run/store-gate/` (authored stand-ins only; no Painter output).
- 3.1 / 3.2 / 4.1 as a test: `tests/parity/test_store_integration.py::test_p0_store_gate` (temporary store and throwaway repository: round trip, `oracle_unavailable` without the store, recorded PNG and JSON readback stand-ins recorded with `record` and rejected by `git commit` through the hook with `[store-hash]`, authored fixture image and expectation JSON committed).
- Quality gate: `python -m mypy` clean (65 files), `python -m ruff check .` clean, `python -m pytest` 367 passed.
- Docs: `parity/STORE.md` §5.1 (first run) and §6 (gate test), `CHANGELOG.md`.
