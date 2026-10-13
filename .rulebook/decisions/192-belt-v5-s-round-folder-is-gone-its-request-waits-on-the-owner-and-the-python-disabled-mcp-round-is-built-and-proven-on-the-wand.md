# 192. Belt v5's round folder is gone: its request waits on the owner, and the Python-disabled MCP round is built and proven on the Wand

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase2.9_pilot-belt, phase1.25_pilot-wand, phase2.8_mcp-server, phase2.6_mcp-typed-tool-families

## Context

phase2.9 is the Belt v5 pilot (Skeletal Mage `23-Cinto` v5). It follows the Wand's pattern: a request manifest pins every input by SHA-256 (decisions 099 and 144), the owner records the Tier 1 golden in Painter, UzPainter rebuilds through the same pipeline scripts, and the maps are compared. Its second half is the Belt round through typed MCP tools with `--allow-python` off.

Measured facts:

- **The round folder is gone.** Belt v5 was painted from Assets3D `_tmp/claude/cintura-v5/`, which is git-ignored. That folder held:
  - `painter_create_args.json` and `painter_export_args.json`;
  - the low OBJ and MTL;
  - the 2K Normal and the AO;
  - `paint/masks-belt/`: 18 masks `M_*.png` and the `base_tex` colour bitmap `T_belt.png`.

  `T_belt` was projected by `waist_masks.py` from two AI-generated swatches in `_tmp/astra/paint-swatches/23/`.
- **Nothing holds a copy.** Another session cleaned `_tmp` on 2026-10-12. Both folders are gone. No copy exists in any of these places:
  - the private store (25 entries, all Wand);
  - the recycle bin;
  - drives C, D, E, F and G;
  - Assets3D git history.

  The mask hashes were never recorded. The swatches are recorded by path only.
- **Still committed:** the waist-v5 scripts, `stack-belt.json` (2 groups and 19 fills, two of them `base_tex: T_belt`), the normal bake, the `.blend` and `.spp`, and the delivered maps.
- **The pipeline moved.** Assets3D c6b74c2 committed the `locate` move. The layer-stack route guard now imports `Pipeline/production/run.py`, and `Pipeline/qa/route_check.py` is gone.
- **No other way to recover the resources.** Painter's documented API has no export of an embedded resource, and the project forbids an `.spp` reader.
- **The MCP export mislabels a release gap.** Over MCP, an export UzPainter refuses before writing came back as `call_failed {type: RuntimeError}`. `Worker::Execute` has no handler for `core::NotYetSupported`, so the long job's rethrown error fell into the generic one. A typed tool reports the same gap as `capability_gap` (typed_tools.cpp `Translated`).
- **No pilot export can complete yet.** UzPainter refuses `infinite` padding on UV-islanded sets before writing (phase1.25 item 2.7), and both the Wand and the Belt export with it.

## Model panel (one round: cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5)

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C1 Keep Belt v5; UzPainter does not fabricate, regenerate or substitute its inputs; restoring them is an owner action | AGREE (restoration must recover the original bytes) | AGREE (name the exact scope: both folders) | AGREE |
| C2 Write the request generator now: committed pins plus the files the arguments file names, every missing file listed; tested on a synthetic mirror; no request committed until the inputs exist | PARTLY (pin the export args, the MTL and `T_belt`; emit nothing on failure) | AGREE (the refusal must be machine-readable) | PARTLY |
| C3 Store every pinned input in the private store when the request is written | AGREE (verify the bytes first) | AGREE (never from the synthetic mirror) | AGREE |
| C4 Build item 2.5 now, pilot-generic, exercised on the Wand as a stand-in; 2.5 stays unchecked | PARTLY (a refusal is not an end-to-end export) | PARTLY (label the Wand run a stand-in) | AGREE |
| C5 The Belt items stay open with the blocker chain; no archive | PARTLY (track the lost inputs and the padding fit apart; they are independent) | AGREE | AGREE |
| C6 Replacing Belt v5 with another piece is the owner's call; the agent must not pick one | AGREE | AGREE (do not even name a candidate) | AGREE |

Every condition is adopted below.

## Decision

1. **Belt v5 stays the pilot, and nothing replaces its inputs.**
   - UzPainter does not regenerate, substitute or extract the lost files.
   - The owner restores `_tmp/claude/cintura-v5/` (the full round folder) and the swatches `_tmp/astra/paint-swatches/23/`, or provides a backup of the original bytes.
   - Re-running the waist-v5 round with new swatches would be a different `T_belt`. The owner may accept it; it would then be a new pinned golden, not the delivered v5.
   - Choosing another production piece instead is also the owner's call. This decision names none.
2. **Request generator: `python -m tools.parity.recorder.script_run manifest --pilot belt [--store]`** (`belt_manifest`). The golden id is `phase2/tier1/belt-v5`, and the request goes to `requests/phase2/tier1/belt-v5.json`. It pins:
   - from the committed pipeline (Assets3D HEAD): `waist-v5/painter_create.py`, `painter_export.py` and `stack-belt.json`, the layer-stack script and `Pipeline/production/run.py`, which the sync step names in `imports`;
   - from the round folder: both arguments files;
   - the mesh, normal and AO the create arguments name, plus the MTL the OBJ's `mtllib` names;
   - every bitmap the stack names, taken from `paint/masks-belt/`.

   Any missing file refuses the command. The refusal lists every missing path, and the command line prints them as JSON (`MissingInputs.missing`). Nothing is written. Today it lists 21 paths: the two arguments files, the 18 masks and `T_belt`. The mesh, normal and AO are named by the lost arguments file, so they cannot be listed until it returns.

   The manifest builder is shared with the Wand's (`script_manifest`). The Wand's output is byte-identical (`test_committed_manifest_matches_the_real_assets`).
3. **`--store`.** It re-hashes every pinned input, stores it (`add_input`) and re-resolves it by hash before the request is written (decision 144). The tests use a temporary store only.
4. **Tier 1 runner.** `tests/parity/tier1/belt_v5/runner.py` reuses the Wand's runner. That runner now takes the golden id and request. The adapter fixture reads the stack input the sync step names, not `wand-stack`.
   - The report path is `parity/reports/phase2/tier1-belt-v5.json`. It follows the guard's `tier<tier>-*.json` rule and the Wand's name; the task text says `belt-v5-tier1.json`.
   - Regions are the stack's group masks: brass `M_metal`. Leather has no mask and counts in the whole-map numbers only.
5. **MCP-only round (item 2.5): `tests/parity/tier1/mcp_round.py`.** The pipeline round is sent as typed calls to `UzPainter.exe --mcp` without `--allow-python`:
   - `project_create` with the manifest's project settings;
   - `set_list`, then `set_mesh_maps` (Normal and AO on the first set, as the create script does);
   - `project_save_as` full;
   - `sync_stack` with the stack and its bitmaps' folder;
   - `project_save` full;
   - `export` with the export script's configuration (`pipeline_export_config`; waist-v5 and wand11-v1 differ only in the preset's name).

   It runs on Vulkan workers. Both paths export on the CPU evaluator, so no device is needed.

   **Report:** `parity/reports/<phase>/<pilot>-mcp-round.json`, schema `uzpainter/pilot-mcp-round/1` (`tools/parity/tier1/mcp_round.py`), checked by a new guard rule. It holds:
   - the Python block (`allow_python` and `run_python_listed`, both false);
   - per call: the tool, `typed: true`, the outcome, the admission, the committed revision and the receipt's SHA-256;
   - the round's outcome;
   - per map, its SHA-256 next to the Tier 1 run's.

   `equal_to_tier1` is derived from the maps. A refused round is never a pass.
6. **Fix the pilot exposed.** `Worker::Execute` maps `core::NotYetSupported` to `capability_gap {tool, type: "NotYetSupported", reason}`, the typed tools' convention (`SUPERVISOR.md`).
7. **Stand-in evidence, for the tool only.** `tests/parity/tier1/test_mcp_round.py` runs the round on the admitted Wand v1 golden's inputs. Results:
   - `run_python` is not listed;
   - the six calls before the export succeed;
   - the export is refused as `capability_gap` (infinite padding), and the Tier 1 adapter run refuses it too.

   This is not Belt evidence. Item 2.5 stays open until the Belt's own report exists and its round completes.
8. **Approved sources.** New rows U-A3D-STACK-4, U-A3D-PRODRUN, U-A3D-WAIST-CREATE, U-A3D-WAIST-EXPORT and U-A3D-WAIST-STACK, each audited. None contains Adobe content.

## Blockers, tracked apart (no item is checked on stand-in evidence)

- **Lost inputs (owner):** restore both folders, then run `script_run manifest --pilot belt --store` and commit the request. This blocks 2.1, and through it 2.2-2.4, 3.1-3.4 and 4.1.
- **Recording (owner's Painter session):** record the Belt request (r1, r1-repeat, r2) and admit it. This blocks 2.2, 3.1 and 4.1.
- **`infinite` padding (phase1.25 item 2.7):** independent of the inputs. Until it lands, every pilot export is refused, so 2.3-2.5, 3.1-3.3 and 4.1 cannot pass even with the inputs restored.
- **Prerequisites (1.1):** phase1.25 and phase2.8 are not accepted.

## Alternatives Considered

- **Regenerate the inputs from the committed waist-v5 chain in Blender.** Rejected (C1). The swatches are gone, and the result would not be Belt v5.
- **Extract the resources from the `.spp` or from the delivered maps.** Rejected. Painter's API cannot do it, an `.spp` reader is forbidden, and the delivered maps are Painter outputs.
- **Check 2.5 on the Wand stand-in.** Rejected (C4). The task names the Belt's report.

## Consequences

- When the owner restores the folder, one command writes and stores the request. The Tier 1 test and the MCP round then run on the next local run, `python -m pytest tests/parity/tier1/belt_v5`.
- `phase2.10_pilot-tunic-recovery` should check its own `_tmp` inputs now, before they are needed.
