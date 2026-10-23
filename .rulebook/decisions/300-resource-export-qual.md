# 300. Qualify the Assets window's Export resource on disposable project bitmaps before any pilot recovery; the pinned current round if it cannot be qualified

**Status**: accepted (design); the qualification run is pending
**Date**: 2026-10-19
**Related Tasks**: phase2.9_pilot-belt, phase2.10_pilot-tunic-recovery, phase2.11_gate-g2

## Context

The two G2 pilots lack original inputs (decisions 192, 194, 215 and 260). The lost bitmaps survive only inside the pilots' Painter projects, as PROJECT resources. A `.spp` reader is forbidden. The Codex supervisor's joint decision SUP-008 (`tmp/claude-supervision.json`, under the owner's delegation of 2026-10-19, "e pra vc tomar as desicoes junto com o claude, para de me perguntar") finds:

- Neither the Python API documentation nor the JavaScript API 1.1.20 documentation offers original-byte resource extraction. `alg.resources.getResourceInfo.filePath` is optional metadata.
- A texture (channel or composite) export, `mapexport.saveMeshMap` and `fileIO.urlToLocalFile` are not resource extraction.
- The Assets window's Export resource is documented for shelf resources ("in the Substance Painter shelf you can right click to export the resource", Adobe's *Layer instancing for VFX scenes*, A-HELP-GUIDE). What it does on a PROJECT resource is not documented.

Measured facts:

- **The version is the SHA-1 of the imported bytes.** A resource URL's `version` is the SHA-1 of the imported file's bytes. Decision 194 verified this on 15 recovered Tunic files.
- **The Tunic's missing inputs.** Its migration golden (decision 215) is admitted. Its private readback holds every layer's resource URL and version.
  - Nine masks are lost: `M_pores`, `M_fiber`, `M_dyeinv`, `M_stains`, `M_fray`, `M_hem`, `M_cav`, `M_ridgewear` and `M_lining`. They are 16-bit grey PNGs written by Pillow (`garment_material_masks.py`).
  - The mesh `_tmp/astra-tunica/normalized_low.obj` is the project's mesh, not a resource. It is lost too.
- **What the Sash project holds.** The stored `25-Faixa-Cintura-v5.spp` (`0691cc12…`) holds these PROJECT resources:
  - the 19 masks, 16-bit grey PNGs from `waist_masks.py` written by Pillow, plus `T_sash`, an 8-bit RGB PNG;
  - all of them imported by the unchanged `painter_layer_stack.py sync` as `v5f_<name>_<SHA-1[:6]>` in the group `faixa25_v5`, with usage TEXTURE;
  - the Normal and AO mesh maps, imported by `painter_create.py` as `<name>_Normal_v5` and `<name>_AO_v5`. The surviving copy of the Normal bake is a 16-bit RGB PNG with `sRGB` and `gAMA 45455` chunks, Blender's form.

  These are not resources and are lost: the low OBJ and its MTL, and both arguments files.
- **Documented calls the run uses.** `Resource.show_in_ui` highlights a resource in the Assets window. `Resource.location` reads SESSION, PROJECT or SHELF. `list_project_resources` and `Resource.retrieve` find a project's resources again after a reopen.

## Model panel (one round: cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5)

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C1 Twelve authored cases, imported as PROJECT resources with a name and group, each bound to a fill layer | AGREE (it qualifies the tested cases, not every file of a class; read back PROJECT location) | PARTLY (the Sash's Normal and AO are resources too; cover their form) | PARTLY (the pilots bind masks and mesh maps; qualify those uses) |
| C2 Conditions A (sources present) and B (sources deleted, project reopened) | PARTLY (restart Painter for B: process caches) | PARTLY (also reopen a moved copy) | AGREE |
| C3 Pass: one file after the fence; SHA-256, size; SHA-1 = version = original's; version stable | AGREE (reject links; pixels never rescue a byte mismatch) | PARTLY (a sidecar or zero-byte file must fail; record the file name) | AGREE |
| C4 Outcomes EXACT, PARTIAL, RE-ENCODED, SOURCE-DEPENDENT, UNAVAILABLE, INCONCLUSIVE | PARTLY (PARTIAL qualifies the tested forms, not whole classes) | PARTLY (cap re-runs, keep every failed run) | PARTLY (the pilots need every form their resources have) |
| C5 Each pilot file accepted only if its SHA-1 equals the readback's version | PARTLY (the 6-hex prefix only corroborates; opening pilot copies amends decision 029's protocol explicitly) | PARTLY (select by URL, not name) | AGREE |
| C6 One route for both outcomes: the pinned current round | PARTLY (it cannot discharge the historic obligations) | PARTLY (r1, r1-repeat, r2 byte-identical; pin the environment) | PARTLY (a substitute mesh can change the maps; the acceptance target must not silently move) |
| C7 The current round as G2 evidence is a joint scope choice under the delegation | PARTLY (the delegation alone does not authorise replacing mandatory G2 evidence) | AGREE (name every substitute and hash) | AGREE |

Every condition is adopted below:

- **Cases and binding.** A 13th case has Blender's Normal form. Each case is bound the way its pilot kind is bound: a layer mask's fill, the Normal or AO mesh map, or BaseColor.
- **Condition B.** It runs in a freshly started Painter process, on a moved copy of the project.
- **PROJECT location.** It is required for an exact result.
- **What PARTIAL qualifies.** It qualifies forms, not classes.
- **Re-runs.** They are capped.
- **The supervision protocol.** It is amended explicitly.
- **The baseline.** C7 is narrowed: the changed baseline still needs the owner's own yes. See item 6.

## Decision

1. **What is qualified.** The documented UI operation Export resource, through the Assets window's context menu, on resources whose location is PROJECT. Nothing else is a candidate for original-resource recovery:
   - not a texture export;
   - not `mapexport.saveMeshMap`;
   - not `fileIO.urlToLocalFile`;
   - not `getResourceInfo.filePath`;
   - not a `.spp` reader.

   The run never opens a production project. Assets3D stays read-only.
2. **The disposable bitmaps.** These are `tools/parity/recorder/resource_qualification.py` `CASES`, our own content: ramps plus integer-hash noise.
   - **Formats.** There are 13 cases:
     - PNG at 8 and 16 bits, grey, RGB and RGBA, with an `sRGB` chunk, a linear `gAMA`, Blender's `sRGB` + `gAMA 45455`, or no chunk;
     - the pilots' own forms, written by Pillow exactly as their generators call it: a 16-bit grey mask, and an 8-bit RGB base colour;
     - a 2048 px 16-bit grey mask;
     - TGA, raw and RLE;
     - OpenEXR, half with ZIP and float uncompressed;
     - a baseline JPEG.
   - **The files.** Twelve are committed in `parity/fixtures/resource-export/` (299,189 bytes). The 2048 px mask is generated at run time by a stored-deflate encoder, so its bytes are the same on every zlib.
   - **Pins.** Each case is pinned by SHA-256, SHA-1 and size. `python -m tools.parity.recorder.resource_qualification fixtures` checks the pins.
3. **The run.** The command is `resource-export-qual`, in `__main__.py`, `resource_qualification.py`, `painter_resources.py` and `painter_ui.py`. It follows the UI-oracle protocol of decisions 029 and 039: out-of-process UI Automation, real clicks guarded to land on Painter's own window, the Painter lock held, and every log, survey and image kept private.
   1. **Setup.** OCIO with Painter's substance configuration. The recorder:
      - creates a throwaway project on the authored plane;
      - imports each case as a project resource, with usage TEXTURE and the name `uzp_rq_<case>_<SHA-1[:6]>` in the group `uzp_rq300` (the sync's form);
      - binds each case as its pilot kind is bound;
      - saves the project (Full).
   2. **Condition `A_source_present`.** For each case, in turn:
      - `Resource.show_in_ui`, then an image of the Assets panel;
      - a fence, then the operator's Export resource into a fresh empty folder;
      - the files written are recorded.
   3. **Between the conditions.** The recorder:
      - closes the project;
      - deletes every staged source;
      - stops Painter and starts a fresh process (`--launch`; the session id must change);
      - copies the project to a new folder and opens that copy;
      - checks that `list_project_resources` lists every case again.
   4. **Condition `B_source_removed`.** The same exports, chosen by the reopened URL. This mirrors the pilots: their sources are gone, and their projects are reopened.

   **The UI operator.** It finds the one visible Assets item that shows the resource's GUI name. If none is visible, it types the name into the window's one search field. It then right-clicks the item and records the menu's items.
   - **The menu item.** It clicks the single enabled item matching `^export\b.*\bresources?$` (mnemonic and ellipsis stripped). It answers `absent` or `disabled` otherwise, without clicking anything.
   - **The dialog.** A native folder picker gets the target folder. A native save dialog gets the folder joined with the name it proposed, recorded together with its file types. A Qt dialog is cancelled and refused.

   Any step it cannot complete is recorded with a survey of the UI Automation tree (the Assets window, else the whole window once), and the run goes on to the next case. `--operator console` asks a person the same prompt.
4. **Pass criteria, per case and condition.** These are `case_status` and `analyse`.
   - **Exact.** All of these hold:
     - the highlighted resource's location is PROJECT;
     - exactly one regular file, not a link, is written after the fence;
     - its SHA-256 and size equal the original's;
     - its SHA-1 equals the original's and the version shown in that condition;
     - the version is the same in A and B;
     - B ran in another process.
   - **Recorded either way.** Its container by magic, width, height, channels and bit depth. Its colour metadata: the PNG chunks, the EXR channel types and compression, the JPEG markers, the TGA type and descriptor. Its file name. When the bytes differ, whether the decoded pixels are equal. A pixel match never makes a byte mismatch exact. These fields name exactly what differs.
   - **The other statuses.** `re-encoded`, `exact-bytes-version-differs`, `multiple-files`, `no-file`, `stale-or-link`, `not-project`, `menu-absent`, `menu-disabled` and `inconclusive`.
5. **Outcomes and what each means for the pilots.**

   | Verdict | Condition | Sash v5 | Tunic v10 |
   |---|---|---|---|
   | `EXACT` | every case exact in A and B | the 19 masks, `T_sash`, Normal and AO become recoverable (item 6). The low OBJ, the MTL and both arguments files stay lost: they are not resources | the nine masks become recoverable (item 6). `normalized_low.obj` stays lost |
   | `PARTIAL` | some cases exact in both conditions | recovery is allowed only for resources whose form equals a qualified case's (container, channels, depth, colour statement, writer, use; `qualified_forms`). The pilots' masks and `T_*` need `png16-grey-pillow`, `png16-grey-2048` and `png8-rgb-pillow`, and the Sash's Normal needs `png16-rgb-blender`. Each pilot file must still pass item 6. The rest goes to item 7 | the same |
   | `RE_ENCODED` | files written, no case exact | never an original. Item 7 | item 7 |
   | `SOURCE_DEPENDENT` | exact in A only | under the tested conditions, the export depends on the external file, not on the project. Item 7 | item 7 |
   | `UNAVAILABLE` | menu item absent or disabled, or nothing written, for every case | item 7 | item 7 |
   | `INCONCLUSIVE` | a step not completed, or B not in a fresh process | not an outcome: fix the locators from the private surveys and run again. At most two more runs; every run's evidence is kept. A third inconclusive run counts as `UNAVAILABLE` | as Sash |

6. **The pilot export, only after `EXACT`, or after `PARTIAL` with the pilot forms qualified.** This is a separate request, authored then. It amends decision 029's "throwaway projects from authored fixtures only" for this step alone, in the way decision 194 opens a migration golden.
   - **The project.** Painter opens a hash-checked private copy of the stored pilot project: Sash `0691cc12…`, Tunic `c43db46a…`. It never opens the original.
   - **The exports.** Each resource is chosen by its URL from the readback: decision 215's for the Tunic, a new Sash migration readback for the Sash.
   - **The gate.** An exported file is accepted as an original only if its SHA-1 equals that binding's recorded version. The `_<SHA-1[:6]>` in a sync-made name only corroborates.
   - **Storage.** An accepted file goes into the private store by SHA-256 (decision 144). The rebuild fixtures then resolve it from the store, never from Assets3D. A file that fails is not recovered.
   - **Reporting.** The recovered files and the historic missing inputs are reported by name and hash, separately.
7. **The fallback route, and the route for what item 6 cannot recover: the pinned current round.** Each pilot gets a separately identified Tier 1 script golden: `phase2/tier1/sash-v5-current` and `phase2/tier1/tunic-v10-current`.
   - **Scripts.** It is recorded through the piece's committed scripts, byte-unchanged:
     - the Sash: `painter_create.py`, `painter_layer_stack.py sync` with `stack-sash.json`, and `painter_export.py`, under decision 099's two adaptations;
     - the Tunic: the unchanged sync with the stack working copy and the F03 override (decision 194), on a project the recorder creates, with decision 194's export configuration.
   - **The mesh.** It is a file we hold: the piece's low, exported from the stored `.blend` by a committed deterministic script.
   - **Pins.** Every input is pinned and stored before Painter runs:
     - originals recovered by item 6, where qualified and SHA-1-verified;
     - otherwise, inputs generated now and named as substitutes. The Tunic's nine masks come from the unchanged `garment_material_masks.py`.
     - arguments files re-authored with the values the stored project shows.
   - **Recording and acceptance.** It records r1, r1-repeat and r2, which must be byte-identical, with the environment record. UzPainter must equal it exactly and rebuilds it from the same pins (Tier 1 items 3.1-3.4).
   - **The approved references.** These stay unchanged: the Tunic's admitted migration golden, and a Sash migration golden recorded from the stored `.spp` (decision 194's route). The current golden's maps are compared with them, and the result is reported.
   - **What may be claimed.** Approved-v5 or v10 parity is claimed only if they are byte-identical. Otherwise the report names it a current reference, and it lists every historic missing input by name and known hash (or `unknown`).
8. **Scope.** Recording and building the current round is a technical recovery step, taken jointly under the owner's delegation. It is reversible and records no parity exception. Using it as phase2.9 and phase2.10's changed baseline is a different matter: those tasks' item 2.8 and acceptance 4.1 require an explicitly owner-authorised changed baseline. So it is one plain-language yes/no question to the owner, asked once a run's verdict is known. It is never decided by the panel.

## Run (pending)

The `rec-batch` agent runs it in its next Painter window, with the Assets3D lock held. No Painter may be running: `--launch` starts it, restarts it for B, and stops it. Painter must stay visible on screen. In PowerShell, from the repository root:

```powershell
$env:OCIO = "C:\Program Files\Adobe\Adobe Substance 3D Painter\resources\ocio\substance\config.ocio"
python -m tools.parity.recorder resource-export-qual --launch --operator ui
python -m tools.parity.recorder resource-export-qual-analyse <run directory printed above> --report parity/reports/phase2/resource-export-qualification.md
```

- **What stays private.** The run directory is `UZP_ORACLE_WORK\resource-export-qual\<run>\`. It holds `evidence.json`, `analysis.json`, the exports, and the UI operator's images and surveys under `UZP_ORACLE_WORK\ui-operator\`. All of it stays private.
- **What is committed.** Only the report: identifiers, statuses, field names and hashes.
- **Afterwards.** The verdict is recorded in this decision and in phase2.9 and phase2.10. Item 6 or item 7 follows.

## Amendment (2026-10-19, SUP-018 and SUP-019)

The Codex supervisor's joint findings SUP-018 and SUP-019 (`tmp/claude-supervision.json`) found defects in the merged run (cc55850). The UI recording was held until they were fixed. These changes amend items 3, 4 and 5; the byte, SHA-256, SHA-1, PROJECT-location and version checks are unchanged.

- **The window of the started process (SUP-018).** The UI operator is made only after `--launch` has started Painter, inside the run's `try`/`finally`. Before, it was made first, so it failed when Painter was closed, or bound an unrelated window that already existed. `PainterUi(pid=...)` binds only the main window of the process the launcher started (`PainterLauncher.pid`), and refuses a window of any other process. After the restart between the conditions, it binds the new process's window.
- **The dialog's file name (SUP-018).** A native save dialog's proposed name is used only if it is a simple file name that resolves to a new file directly inside the private target (`painter_ui.contained_file`). These are refused: an empty name, `.` and `..`, absolute, rooted, drive-relative and UNC paths, separators, parent paths, wildcards, stream colons, device names, and trailing dots or spaces. A refused name cancels the dialog and refuses the step, and nothing is saved.
- **Source removal for B (SUP-019).** After the restart and before B opens the moved copy, the recorder records every staged path and whether it is absent (`sources_absent`). A source that is still present refuses the run. `analyse` qualifies B only when `sources_removed` is literally true and `sources_absent` names every case, each absent (`sources_removed_verified`). Otherwise the verdict is `INCONCLUSIVE`, with no qualified forms.
- **The verdicts (SUP-019).**
  - **PARTIAL.** It needs exact cases, not a whole exact format class. A sole exact `png16-grey-pillow` among failing PNGs is `PARTIAL`, and its form qualifies.
  - **Re-encoded.** A case is `re-encoded` only when its one fenced file has other bytes that decode as an image here. Other bytes that do not decode are `other-bytes-undecoded`.
  - **RE_ENCODED and SOURCE_DEPENDENT.** They need failures that establish them: `re-encoded`, `no-file`, `menu-absent` or `menu-disabled`.
  - **Failures that prove nothing.** These are `exact-bytes-version-differs`, `stale-or-link`, `not-project`, `multiple-files`, `other-bytes-undecoded`, and exact bytes with an unstable version. They are listed in `unresolved_cases`. With no exact case, they make the run `INCONCLUSIVE`, under item 5's re-run cap; they never make it `RE_ENCODED`.
- **SUP-025 (2026-10-19).** `sources_removal_verified` also needs each case's recorded `path` to be `sources/<file name>` (a missing or other path fails), and `RE_ENCODED` needs every status to be an established failure with at least one `re-encoded` export; any other unmatched combination, such as `no-file` in A and `exact` in B, is `INCONCLUSIVE`.

## Amendment (2026-10-23): preserve staged sources

Condition B now moves the thirteen staged sources into a separate private `preserved-sources/` directory instead of deleting them. Each file is checked against its pinned SHA-256 before and after the move, and private evidence records its preserved path, SHA-256 and size. The imported `sources/<file name>` paths must still all be absent immediately before B opens the moved project; any reappearance refuses the run. The fresh-process requirement and every export-byte/version check remain unchanged.

This tests the same source-path absence: committed authored fixtures already remained elsewhere even under the original deletion procedure. Preserved paths are never supplied to Painter. Physical destruction of the authored bytes is not required. The existing 35 qualification tests pass, including restored-source refusal, with added checks that preserved files retain their pinned bytes. No pilot project or baseline changes follow from this preparation.

## Alternatives Considered

- **Reading the resource bytes through `getResourceInfo.filePath` or `urlToLocalFile`.** Rejected (SUP-008): that is metadata or path conversion.
- **A texture export of a fill bound to the mask.** Rejected: it is Painter's rendered output, not the original bytes.
- **Qualifying directly on the pilot projects.** Rejected: the operation must first be shown exact on files whose bytes we hold.
- **Treating pixel equality as recovery.** Rejected: acceptance needs the original bytes, and the SHA-1 is the per-file proof.
- **Asking the owner to choose the route.** Rejected: the delegation and SUP-008 settle it, and only the baseline change needs his yes.

## Consequences

- One Painter window decides whether the lost pilot bitmaps can be recovered byte for byte. Even on success, the Sash's low mesh and arguments files, and the Tunic's `normalized_low.obj`, remain lost.
- Either way, the pinned current round gives each pilot a golden whose every input outlives Assets3D. The historic inputs are reported missing, never invented.
