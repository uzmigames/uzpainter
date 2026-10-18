## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.25_pilot-wand, phase2.8_mcp-server

## 2. Implementation
- [ ] 2.1 Sash v5 fixture manifest in `parity/manifests/`: stack JSON, resources and external mesh maps by SHA-256, instruction sequence, export configuration
- [ ] 2.2 Sash v5 Tier 1 goldens recorded twice through the recorder on the owner's machine; oracle stability classified; blobs in the private store, hashes in the manifest
- [ ] 2.3 Sash v5 rebuilt in UzPainter from the same stack JSON and resources, including the `base_tex` swatch fills
- [ ] 2.4 Tier 1 comparison and report `parity/reports/phase2/tier1-sash-v5.json`
- [ ] 2.5 MCP-only round script driving typed tools against a supervisor started without `--allow-python`; call log and receipts in `parity/reports/phase2/sash-v5-mcp-round.json`
- [ ] 2.6 Before input-dependent rebuild or recording work, complete one bounded inventory of the round folder, swatches and identified recovery sources: name the sources checked, inputs present or missing, known historical hashes or resource versions, and unresolved identity checks; publish numbers, hashes and missing-path metadata only. Reuse the documented searches of decisions 192 and 260; do not repeat a sweep without a newly identified source
- [ ] 2.7 Preserve every available or recovered input, the fixture request and its oracle envelope in the private content-addressed store, and verify the stored hashes before use; public manifests contain hashes and provenance metadata, not private input bytes
- [ ] 2.8 At the inventory checkpoint, verify restored originals against known reference hashes/resource versions and provenance. Original restoration needs no new scope decision. If originals remain unavailable, prepare one owner decision package for recovery versus a new reference, replacement or exclusion; link any existing pending question instead of duplicating it. A changed baseline requires an explicit recorded owner scope decision before recording or claiming Sash v5 parity; unresolved inputs keep this task open while independent work continues

## 3. Tests
- [ ] 3.1 Tier 1: every exported Sash v5 map equals the private golden in native decoded values; save/reopen preserves equality
- [ ] 3.2 Repeatability: two UzPainter runs produce byte-identical exports
- [ ] 3.3 MCP-only round: `run_python` absent from the tool list, every call typed, round completed, maps equal to the Tier 1 run
- [ ] 3.4 Every divergence is listed with the owner-approved exception that covers it, or the test fails

## 4. Acceptance
- [ ] 4.1 DAG gate met: equal maps and the Python-disabled MCP integration round completed; reports written to `parity/reports/phase2/`; the input inventory and preservation records are complete, and the reports identify the original reference or an explicitly owner-authorized changed baseline (items 2.6-2.8)

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass

## 6. Notes (decision 260; 2026-10-18, branch `wt/pilot-skeleton-mage`)
- The pilot is Sash v5 (`25-Faixa-Cintura` v5), which the owner chose to replace Belt v5 with on 2026-10-18 ("outra peça do skeleton mage"). It was painted in the belt's waist-v5 round through the same pinned scripts, at 2048 px with one texture set and 61 UV islands, and its stack uses only the Wand's features. It is a named stand-in for the second pilot, not restored Belt parity. The directory keeps its name.
- Inventory (items 2.6-2.8, decision 260 table): no Skeletal Mage piece has complete inputs. Every round ran from `_tmp/claude/<round>/`, and all of those are gone. Choosing the sash does not unblock the pilot.
- Recordings needed: one, the Sash v5 Tier 1 golden `phase2/tier1/sash-v5` (r1, r1-repeat, r2) from `parity/envelopes/painter-12.1.5_js-api.1.1.20/requests/phase2/tier1/sash-v5.json`. That request does not exist yet; see the blockers.
- Blockers, each with its owner, tracked apart:
  - Lost inputs (owner): restore `_tmp/claude/cintura-v5/` or name a backup. Then run `python -m tools.parity.recorder.script_run manifest --pilot sash --assets-root E:\UzmiGames\Assets3D --out <request> --store` and commit the request. This blocks 2.1, and through it 2.2-2.4, 3.1-3.4 and 4.1.
  - Recording (owner's Painter session): blocks 2.2, 3.1 and 4.1.
  - `infinite` padding (phase1.25 item 2.7): independent of the inputs. Every pilot export is refused before writing until it lands.
  - 1.1: phase1.25 and phase2.8 are not accepted.
  - Owner options that are not chosen here: a re-run of the waist-v5 round as a new golden, which also needs the lost base assembly; or a migration golden from the stored `.spp` (decision 194's route), a separate acceptance route that is not the script-created golden.
- 2.1 (open): `sash_manifest`, sharing the Belt's builder (`waist_manifest`), is tested on a synthetic mirror (`tests/parity/recorder/test_script_run.py`). Arguments files that name another piece are refused, since the round folder holds one pair for both pieces.
  - On the real Assets3D it refuses, listing 22 missing paths: the two arguments files, the 19 masks and `T_sash`.
  - The mesh, MTL, normal and AO are unresolved bindings: only the lost arguments file names them. The `Textures/` normal bake copy is not bound in their place.
- 2.7 (open, partial): 20 files are in the private store by SHA-256, through the store's `input` command, and `python -m tools.parity.store verify` reports ok. They are the sash's git-ignored `.spp`, `.blend`, FBX, GLB, five maps, normal bake copy, two reference crops, report and piece manifests, plus the five committed pins.
- 2.3-2.5 (open): `tests/parity/tier1/sash_v5/runner.py` and `test_sash_v5.py` (moved from `belt_v5`) skip with the reason until the request exists. The reports are `parity/reports/phase2/tier1-sash-v5.json` and `parity/reports/phase2/sash-v5-mcp-round.json`. The MCP-only round with `--allow-python` off stays required, as a gate apart from Tier 1 equality.
- Tests run once (2026-10-18): `tests/parity/recorder/test_script_run.py` + `tests/parity/tier1/sash_v5`: 27 passed, 2 skipped (the sash tests, with the reason). ruff, `ruff format --check` and mypy on the touched files: clean.

## 7. Notes, Belt v5 history (decision 192; 2026-10-12, branch `wt/p2-belt`)
- Recordings needed: one, the Belt v5 Tier 1 golden `phase2/tier1/belt-v5` (r1, r1-repeat, r2) from `parity/envelopes/painter-12.1.5_js-api.1.1.20/requests/phase2/tier1/belt-v5.json`. That request does not exist yet; see the blockers.
- Blockers, each with its owner:
  - Lost inputs (owner). Assets3D `_tmp/claude/cintura-v5/` (the round folder) and `_tmp/astra/paint-swatches/23/` were removed on 2026-10-12. The documented searches reported no copy in the private store, recycle bin, drives checked or Assets3D git; this is not a claim that every possible recovery source was exhausted. Restored original inputs are verified and preserved (2.6-2.8), then the owner runs `python -m tools.parity.recorder.script_run manifest --pilot belt --assets-root E:\UzmiGames\Assets3D --out <request> --store` and commits the request. This blocks input-dependent manifest, recording, rebuild and parity work; items 2.6-2.8 proceed to the inventory checkpoint with the missing inputs recorded.
  - Recording (owner's Painter session): blocks 2.2, 3.1 and 4.1.
  - `infinite` padding (phase1.25 item 2.7): independent of the inputs. Pilot exports are currently refused before writing; phase1.25 must clear that capability under the existing equality/owner-exception contract before 2.3-2.5, 3.1-3.3 and 4.1 can pass. An exception route remains pending until measured evidence and an owner-approved, versioned register entry cover the affected domain; no tolerance is assumed.
  - 1.1: phase1.25 and phase2.8 are not accepted.
- 2.1 (open): the generator `belt_manifest` is written and tested on a synthetic mirror (`tests/parity/recorder/test_script_run.py`). On the real Assets3D it refuses, listing 21 missing paths: the two arguments files, the 18 masks and `T_belt`.
- 2.3, 2.4 (open; moved to `tests/parity/tier1/sash_v5` by decision 260): `tests/parity/tier1/belt_v5/runner.py` (the Wand's runner over `phase2/tier1/belt-v5`) and `test_belt_v5.py`. Both skip with the reason until the request exists. The report goes to `parity/reports/phase2/tier1-belt-v5.json`, the guard's `tier<tier>-*.json` name.
- 2.5 (open): `tests/parity/tier1/mcp_round.py` drives the round through typed tools with Python disabled. `tools/parity/tier1/mcp_round.py` holds the report schema, and a guard rule covers `parity/reports/<phase>/<pilot>-mcp-round.json`.
  - Proven for the tool only, on the Wand v1 inputs (`tests/parity/tier1/test_mcp_round.py`): `run_python` is not listed, and the six calls before the export succeed. The export is refused (`capability_gap`, infinite padding), and the Tier 1 run refuses it too.
  - The Belt's own report waits on the blockers.
- Fix the pilot exposed: a release gap that a worker tool's long job meets (`export`) came back as `call_failed {type: RuntimeError}`. It is now `capability_gap {tool, type: NotYetSupported, reason}` (`src/supervisor/worker.cpp`, test `test_an_export_release_gap_is_a_capability_gap`).
- Tests run once each (2026-10-12):
  - `tests/parity/recorder/test_script_run.py` + `tests/parity/tier1/belt_v5` + `tests/sources/test_index.py`: 38 passed, 2 skipped (the Belt tests, with the reason), exit 0.
  - `tests/parity/test_guard.py -k mcp_round`: 10 passed, exit 0.
  - `test_typed_tools.py::test_an_export_release_gap_is_a_capability_gap` + `tests/parity/tier1/test_mcp_round.py`: 2 passed, exit 0.
  - Earlier, before the worker fix: the stand-in round failed on the RuntimeError mapping, which is what led to the fix.
  - `python -m tools.sources.check`: ok. ruff, `ruff format --check` and mypy on the touched files: clean. `zig build painter` (-Werror on own sources): exit 0.
