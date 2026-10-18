# 260. Sash v5 replaces Belt v5 as the phase2.9 pilot; no Skeletal Mage piece has complete inputs, and the sash's surviving files are stored

**Status**: accepted
**Date**: 2026-10-18
**Related Tasks**: phase2.9_pilot-belt, phase2.10_pilot-tunic-recovery, phase1.25_pilot-wand

## Context

The owner decided on 2026-10-18 that Belt v5 (decision 192, whose round folder was deleted) is replaced by "outra peça do skeleton mage": another piece of the Skeletal Mage. The task was to find the piece with complete inputs painted through the Wand's pinned pipeline, store its inputs by SHA-256, author its Tier 1 request, and point phase2.9 at it.

Measured facts (read-only survey of Assets3D at d13c4d4 and of the drives, 2026-10-18):

- **Every Skeletal Mage pipeline round ran from `_tmp/claude/<round>/`**, a copy of its committed folder in `Pipeline/retopology/`. All those round folders are gone; only an empty `_tmp/claude/cintura-v5/` remains.
  - The external archive `E:/UzmiGames/Assets3D-Arquivo` that `recuperacao-tmp-claude-39.json` names (the pauldron and chest-strap rounds) is gone too.
  - The private store held only Wand v1 and Tunic v10 inputs (61 entries).
  - A search of drives C to G found no copy. It looked for `*_low.obj`, `painter_create_args.json`, mask PNGs and the round folder names, with a 500 s limit per drive.
- **No candidate has a complete input set on disk.**

| Piece | Painted through | On disk now | Missing | Sets, resolution | UV islands | Features outside UzPainter's domain |
|---|---|---|---|---|---|---|
| 25-Faixa-Cintura v5 (sash) | the waist-v5 round, as the belt: `painter_create.py`, `painter_layer_stack.py sync`, `painter_export.py` (`round.sh`) | scripts, `stack-sash.json`; git-ignored but present and equal to the piece manifest: `.spp`, `.blend` (no packed images), FBX, GLB, five delivered maps, the 2K normal bake copy in `Textures/` | both arguments files, low OBJ and MTL, AO, 19 masks and `T_sash`, two swatches; the round's base `Assembly/Skeletal-Mage-TunicCoverage-v1.blend` and `waist-v5.blend` | 1, 2048 (sizeLog2 11) | 61 (4,038 tris) | none beyond the Wand's (uniform fills, bitmap masks, `base_tex`, a group mask) |
| 09-Cajado v10 round (delivered v12) | staff-v10, the same three scripts; v12 adds `painter_set_ao.py`, `painter_add_channel.py` and `painter_export_v8.py` | scripts, both arguments files (committed copies), `stack-staff.json`; only the v12 project, `.blend` and maps | mesh, normal, AO, 16 masks and `T_base`; the v10 `.spp`, `.blend` and maps | 1, 4096 (sizeLog2 12) | 286 (4,282 tris) | v12: the OpenPBR SpecularWeight channel (`spec`) and an AO override |
| 10-Chapeu v6 round (delivered v8) | hat-v6, as the staff | scripts, arguments, `stack-hat.json`; only the v8 project | mesh, normal, AO, 21 masks; the v6 `.spp` | 1, 4096 | 47 | v8: SpecularWeight |
| 13-Grimorio v4 | masks, `painter_layer_stack.py sync` and `base_tex`, but the project was created interactively (no pinned create or export) | `.spp` v4, `.blend` v6, maps | masks (`_tmp/claude/g`), colour sources (`_tmp/astra-grimorio`) | 1, 2048 | 59 | none, but not the pinned pipeline |
| 19 and 20 Ombreiras v9 | one-off scripts (`create19v9.py`, now lost with the archive) | `stack_v9.json`, rules, iron swatches, low and high `.blend`, normal, `.spp` | create and export scripts, masks | 1, 2048 | 102 | not the pinned pipeline |
| 24-Tiras-Peito-Gema v4 | one-off scripts (lost) | `stack24v4.json`, `masks24.py`, low `.blend`, `.spp` | masks, leather swatch | 1, 2048 (1024 delivered) | 150 | not the pinned pipeline |
| 21 and 22 Bracers | interactive Painter: smart materials (`.spsm`), curvature generators | `.spp`, maps | the round's working folder | 1, 2048 | 23 and 96 | smart materials and generators (refused) |
| 00-Corpo v6b | interactive Painter: grunges, Edges Uber and Occlusion generators | `.spp`, maps | not applicable | 3, 4096 | 219, 691, 343 | procedural resources and generators (refused) |
| 11-Varinha v3 | wand11-v1 | not applicable | not applicable | 1, 2048 | 4 | the Wand itself, pilot 1 |
| 12-Varinha-Osso, 14-Lanterna | never painted | not applicable | not applicable | not applicable | not applicable | not applicable |

## Model panel (one round: cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5)

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C1 Sash v5 is the replacement: the only piece painted through the pinned pipeline whose delivered project and maps survive; the belt's scripts; 2048, one set, 61 islands; the Wand's features only | AGREE (the best recovery prospect, not an executable pilot) | AGREE | AGREE (a named stand-in, not restored Belt parity) |
| C2 Say plainly that the choice does not unblock the pilot; the generator `--pilot sash` refuses on the real repository, listing the missing paths; no request JSON until the inputs exist; nothing regenerated, substituted or extracted | PARTLY (the normal copy needs provenance checks before it is bound; the mesh, MTL, normal and AO bindings are unresolved, not only missing) | AGREE | AGREE |
| C3 Store now every present at-risk file of the sash and the committed pins (20 files) | PARTLY (verify the stored copies; the `.spp` is the only known potential mask source, not a proven one) | AGREE (later, record the `.spp` resource inventory) | AGREE |
| C4 Keep the Belt generator; move the phase2.9 runner, test and task text to the sash; keep the MCP-only round; the task stays open with its blockers | PARTLY (keep the Belt history; the Tier 1 and MCP gates stay separate) | PARTLY (track the independent blockers apart) | AGREE |
| C5 Offer the owner the Tunic route (decision 194): a migration golden from the sash's pinned `.spp`, without choosing it | PARTLY (a separate, owner-approved route; it is not the script-created golden) | PARTLY (it tests less: the owner must know the trade-off) | AGREE |

Every condition is adopted below. Kimi's resource inventory needs a Painter session and is left to the next one.

## Decision

1. **Sash v5 (`25-Faixa-Cintura` v5) is the phase2.9 pilot.** It is a named stand-in for the second pilot, not restored Belt v5 parity. The task directory keeps its name `phase2.9_pilot-belt` so links and the DAG stay valid. Its text names the sash.
2. **The choice does not unblock the pilot.** No Skeletal Mage piece has complete inputs, so any replacement waits on the owner.
3. **Request generator: `python -m tools.parity.recorder.script_run manifest --pilot sash [--store]`** (`sash_manifest`). The golden id is `phase2/tier1/sash-v5`, and the request goes to `parity/envelopes/painter-12.1.5_js-api.1.1.20/requests/phase2/tier1/sash-v5.json`.
   - It shares the Belt's builder (`waist_manifest` over a `WaistPiece`). The pins are the committed waist-v5 scripts, `painter_layer_stack.py`, `Pipeline/production/run.py` and `stack-sash.json`; the round folder's two arguments files; the mesh, MTL, normal and AO those name; and the stack's 20 bitmaps from `paint/masks-sash/` (`round.sh`: `waist_masks.py sash --out paint/masks-sash`).
   - The round folder holds one pair of arguments files, which the round rewrites for each piece. A create `name` or export `prefix` that names another piece refuses the command, so a restored folder cannot pin the belt's low into the sash's request. The Belt's request has the same guard.
   - Today it refuses and lists 22 paths: the two arguments files, the 19 masks and `T_sash`. The mesh, MTL, normal and AO are unresolved bindings: only the lost arguments file names them.
   - The `Textures/` normal bake copy is not bound in their place; only the arguments file's own path counts. No request JSON is committed.
4. **Inputs stored now (decision 144).** The request refuses, so `--store` cannot run. Each file went in through the store's `input` command, under its Assets3D path, and the whole store verifies (`python -m tools.parity.store verify`: ok, 81 entries). That is 20 files:
   - the sash's git-ignored files: `25-Faixa-Cintura-v5.spp` (`0691cc12…`), `.blend` (`4c770d1d…`), FBX and GLB, the BaseColor, Normal, Roughness, Metallic and Height maps, the normal bake copy (`ec05be82…`), the two reference crops in `Textures/Swatches/`, `report.json`, and `manifests/v5.json` and `v5.input.json`;
   - the five committed pins: `painter_create.py`, `painter_export.py`, `stack-sash.json`, `painter_layer_stack.py`, `Pipeline/production/run.py`.

   The `.spp` is the only known remaining place that may hold the sash's masks, as Painter resources. That is not a proven recovery source, and nothing is extracted from it.
5. **Tests and runner.** `tests/parity/tier1/belt_v5` moves to `tests/parity/tier1/sash_v5`. It is the Wand's runner over `phase2/tier1/sash-v5`, with the report `parity/reports/phase2/tier1-sash-v5.json` and the round report `parity/reports/phase2/sash-v5-mcp-round.json`. Both skip with the reason until the request exists.
   - The regions are the hem group's `M_hem`. The cloth group has no mask and counts in the whole-map numbers only.
   - The Belt generator and its tests stay, since they still work if the folder returns.
   - The MCP-only round with `--allow-python` off stays required, as a gate apart from Tier 1 equality.
6. **The owner's options, none chosen here:**
   - restore `_tmp/claude/cintura-v5/` (both pieces' rounds) or name a backup of it;
   - accept a re-run of the waist-v5 round as a new golden. That also needs the lost base assembly and `waist-v5.blend`.
   - record a migration golden from the stored `.spp`, by decision 194's route. It is recordable without the round folder, but it is a separate acceptance route, not the script-created Tier 1 golden. It tests the delivered project's export rather than a fresh pipeline run, and the rebuild would still lack the arguments, mesh, AO and masks.

## Blockers, tracked apart (no item is checked on stand-in evidence)

- **Lost inputs (owner):** restore the round folder or name a backup. Then run `script_run manifest --pilot sash --store` and commit the request. This blocks 2.1, and through it 2.2-2.4, 3.1-3.4 and 4.1.
- **Recording (owner's Painter session):** record the sash request (r1, r1-repeat, r2) and admit it. This blocks 2.2, 3.1 and 4.1.
- **`infinite` padding (phase1.25 item 2.7):** independent of the inputs. Every pilot export is refused until it lands.
- **Prerequisites (1.1):** phase1.25 and phase2.8 are not accepted.

## Alternatives Considered

- **Cajado v10 or Chapeu v6.** Rejected. Their arguments files are committed, but their mesh, mesh maps and masks are as lost as the sash's. Their round's own project and maps are gone, and the delivered versions add SpecularWeight. They also run at 4096 px, and the cajado has 286 islands.
- **Grimorio v4, Ombreiras v9, Tiras v4.** Rejected. They were not painted through the pinned create and export scripts.
- **Bracers, Corpo.** Rejected. They were painted with smart materials, grunges and generators, which UzPainter refuses.
- **Bind the `Textures/` normal bake copy or re-export the low from the `.blend`.** Rejected. That would be a substitution: neither file's identity with the round's file can be proven.

## Consequences

- The owner's single action is the same as for the Belt: restore one folder. It now unblocks the sash (and the belt).
- Every git-ignored file of the sash outlives Assets3D.
