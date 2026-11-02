# Sash v5 current round: input contract

The input contract for the pinned current round `phase2/tier1/sash-v5-current` (decision 300 item 7). It is derived from the Sash v5 migration golden admitted on 2026-11-02. This page holds only counts, public file names, statuses and hashes. The full contract, with the readback values it was derived from, is private (`%LOCALAPPDATA%\UzPainter\sash-v5-current-contract.json`, SHA-256 `e441ced9bf5c…`, 45,477 bytes).

Revised on 2026-11-02 (Codex root REV418): the export route is decided, the sync and export scripts and the sync script's import closure are pinned by commit and SHA-256, and the wording of the literal SHA-1 comparison is corrected.

**Result.** The round still cannot be requested. Of its seven input kinds, one is available as a named substitute (the Normal), one is in progress (the low OBJ and MTL, front N), and five are missing: AO, the 19 masks, `T_sash`, the two swatches, and the generator intermediates. The export route is settled, and so are the script pins. The recorder cannot load the sync script's import closure yet (see the scripts below).

## Binding

| Item | Value |
|---|---|
| Migration golden | `phase2/tier1/sash-v5-migration`, admitted in `e53d15b1` |
| Private record | `e87c5701791ffe371bb951cbbf2fce0918ce03a4c11c09ee93c99bbaae4d6ca9` (63,960 bytes), hash checked in the store |
| Public manifest | `parity/envelopes/painter-12.2.0_js-api.1.1.20-env-a981b586eae7/manifests/phase2/tier1/sash-v5-migration.json`, SHA-256 `992fd5b35dc5…` |
| Request | `…/requests/phase2/tier1/sash-v5-migration.json`, SHA-256 `b37e099bb0ca…` |
| Record inputs | `sash-v5-project` `0691cc120714…`, `sash-v5-export-config` `983c4d30c889…` |
| Environment record | `4cd95449e169…` |
| Input inventory | `parity/reports/phase2/sash-v5-input-inventory.md`, SHA-256 `40de41b9c5ad…` |
| Painter | `12.2.0+js-api.1.1.20`, OCIO (Painter's substance configuration) |

## What the saved state shows

- **Stability.** The r1 and r2 state readbacks are equal. They differ only in the resource context (`project0`, then `project1`) and in the work-copy path. All 22 resource versions are stable.
- **Texture set.** One set, `25-Faixa-Cintura`, at 2048 × 2048, with five channels.
- **The stack.** It matches `stack-sash.json` (`567e918f97ab…`) with no structural difference. All of these are equal: the title, the 2 groups and the 20 layers in order, their names, their masks and the BaseColor opacities. Roughness, metallic and height are equal at float32. The BaseColor uniform colours were not compared: the readback gives working-space values and the stack gives sRGB 0-255.
- **Root.** The synced group is visible, plus one hidden default paint layer.
- **Bitmaps.** There are 21 bindings on 20 layer-stack resources:
  - 19 mask fill effects (18 layer masks and 1 group mask), colour space Data;
  - 2 `T_sash` BaseColor fills, colour space sRGB.
- **Mesh maps.** Normal and AO are each bound to one resource. The other eight mesh-map slots are empty.
- **The mesh.** The last-imported mesh has the base name of front N's `OBJ_NAME`, `25-Faixa-Cintura-v5-low.obj`. The readback states no file hash.

## Arguments

A *derived* value is read from the saved state. An *authored* value is chosen for the round and named as such. *Unknown* means the record does not state it.

| Step | Argument | Status |
|---|---|---|
| 1 `painter_create.py` (`f3e01482efaa…`) | `mesh` | front N's OBJ (decision 099 staged copy); historical file hash unknown |
| | `normal` | named substitute (see below) |
| | `ao` | **unknown, missing** |
| | `dst` | decision 099 work project; historical value unknown |
| | `name` | `25-Faixa-Cintura`, derived from the mesh-map resource names |
| | normal format OpenGL, `import_cameras` False, group `mesh_maps_v5` | fixed in the script; not stated by the record (resolution 2048 is confirmed) |
| 2 `painter_layer_stack.py sync` | script bytes | pinned to a commit, see the scripts below; the historical bytes stay unestablished |
| | `--stack` | `stack-sash.json`, derived (structure equal) |
| | `--masks` | staged folder with the 19 masks and `T_sash.png`: **missing** |
| | `--state` | a fresh file, so every bitmap is imported; the historical round tag is unknown |
| | `--resource-prefix` | `v5f_`, derived (all 20 names) |
| | `--resource-group` | `faixa25_v5`, from `round.sh` only; groups are not read back |
| | `--texture-set` | `25-Faixa-Cintura`, derived |
| | `--keep-visible`, `--stack-key` | none (`round.sh`), consistent with the hidden root layer |
| 3 `painter_export.py` | script bytes | pinned to a commit, see the scripts below |
| | `out` | decision 099 fresh directory |
| | `prefix` | `25-Faixa-Cintura`, **authored** (the export route); historical `25-Faixa-Cintura_v5<tag>`, tag unknown |

## Export route: Option A (decided)

The round has three steps and no fourth. Step 3 runs the unchanged committed `painter_export.py` with the authored prefix `25-Faixa-Cintura`. It writes exactly five maps of one texture set, with the migration's five map names, so `current_reference` pairs them one to one.

- **The migration configuration's role.** `parity/fixtures/tier1/sash-v5/export-config.json` (`983c4d30c889…`) stays an input of the migration golden only. It is not an input of `sash-v5-current`.
- **What this corrects.** `parity/RECORDER.md` §9b said the current round "exports with the same file". It is now corrected. The admitted migration manifest and its request say the same in their descriptions. They are bound by hash, so they stay unchanged, and this page supersedes that sentence.
- **Option B, rejected.** A fourth `export_project_textures` step with `export-config.json` would need another prefix, or the recorder refuses maps of the same name. `current_reference` would then see 10 maps against 5.

**The configurations are equivalent.** The comparison extracted `doc` and `cfg` from the pinned script bytes, evaluated them with the prefix `25-Faixa-Cintura` and one texture set, and compared the values with `export-config.json`, field by field:

| Field | `painter_export.py` against `export-config.json` |
|---|---|
| `exportShaderParams` | equal (false) |
| `exportPresets` | one preset each. The five maps are equal in order, file name and every channel's destination, source, map type and map name: BaseColor RGB, Roughness L, Metallic L and Height L from document maps, and Normal RGB from `Normal_OpenGL` |
| `defaultExportPreset` | the names differ (`v5` against `sash-v5-png16`), and each names its sole preset |
| `exportList` | equal when the project holds exactly one texture set, `25-Faixa-Cintura`. The script lists the texture sets at run time, and the texture-set check enforces this |
| `exportParameters` | equal: one unfiltered rule, PNG, `bitDepth` 16, `sizeLog2` 11, `infinite` padding, no dithering; neither has a dilation distance |
| Colour space | neither configuration states one; the JSON comparison does not verify Painter's colour handling at run time |
| `exportPath` | in the script only. Adaptation 1 points it at a fresh directory; §9b leaves it out of the migration configuration |

**Verdict.** They are equivalent as configurations: the two are equal once `exportPath` is dropped and the preset names are made the same. Outside the configuration, one behaviour differs. `painter_export.py` saves the project in full before every export, while the migration step only exports.

## Scripts

The current round runs a named set of committed scripts. It is an input choice for the current round, not a historical recovery: which script bytes ran in the historical round stays unestablished for every file below.

- **The sync and its support snapshot.** The sync script and the modules it imports are taken from one committed Assets3D snapshot, `1c9a312a47eea0b35aa0aa05777245ef61ac49e5` (2026-10-20). The current `run.py` (`c4c4989d`) is not used: it adds more local dependencies at import time (`resume_block`, `shared_equipment`, `reconstruction` and, through it, `reference_gate`).
- **The export script.** `painter_export.py` has one blob for its whole history.
- **The declared format.** Every pin below is the raw git blob, which is LF. Each blob is read straight from the Assets3D object database into the authorized private input store. There is no checkout, no worktree and no copy in the repository, and nothing is normalised after hashing. The request pins exactly these SHA-256 values.

| Script | Commit | Git blob | SHA-256 of the blob (bytes) |
|---|---|---|---|
| `Pipeline/retopology/waist-v5/painter_export.py` | `d974c81e` (2026-10-11), the only commit at this path. The same blob was first committed at `83e9f434` (2026-10-09 22:10) and is unchanged up to Assets3D HEAD `a8a06a1c`. | `cfa63b03272b…` | `48c294a43cbce1073e647f6299576fedd66f31f8fb4370f8175f3df2ac64d038` (1,822) |
| `Pipeline/painting/painter_layer_stack.py` (sync) | `1c9a312a`, the last commit that changed the path | `c83a2db598e5…` | `834c4bca3d32ebdeb9cd705e699782ee86fb86eb6dcff277345fae7bd63827aa` (22,407) |
| `Pipeline/production/run.py` | `1c9a312a` | `dc93f607f7ae…` | `7d8017d256a2359d5062fcc6e9e06881fee5d2bbb113e8000f8fba819a85b0a2` (119,859) |
| `Pipeline/production/decision_evidence.py` | `1c9a312a` | `3967c1c1113d…` | `a1f11c9a6938a8c77284e63c3e515b78a892424df480d8931a90f825a1967d60` (12,533) |
| `Pipeline/production/stage_review_evidence.py` | `1c9a312a` | `868ee2714914…` | `598c774ade15d7893bec154aead7065ddb515fd5799ab42fcf8f6e97735f502a` (7,780) |

- **The Windows checkout is the same blob.** Assets3D checks out with `core.autocrlf` true and no attributes, so the working copies are CRLF. The sync script's checkout `62702cb30030…` (22,785 bytes) equals its blob with every LF replaced by CRLF; that was checked by hashing the converted blob. The inventory's `run.py` working copy `79afd1ce47e4…`, recorded when HEAD was `1c9a312`, is that blob's CRLF form too. The CRLF forms are not pinned: this only shows they are the same blob materialized.
- **What the round does not use.** It does not use the stored decision 260 copy `d3eebe58b98b…`, which matches no committed version (inventory check 3). It does not use the live tree or whatever HEAD holds when the request is written. Assets3D HEAD already holds other bytes for `run.py` (`c4c4989d`) and `decision_evidence.py` (`bbac5b22`).

**Import-time behaviour.** This was traced by reading the committed sources, without running them.
- **The sync script.** At module scope it imports `locate` and `owner_preview_paint` from `run.py`. `1c9a312a` is the first `run.py` that defines `owner_preview_paint`.
- **`run.py`.** It is **not** standard-library-only at import time. A top-level `try` imports two local helpers: `decision_evidence` and `stage_review_evidence`, relative first, then absolute on `ImportError`. Each helper defines every name `run.py` takes from it.
- **The two helpers.** Each imports only the standard library at import time. `decision_evidence` imports PIL only inside a function.
- **The functions the sync script calls.** `locate`, `owner_preview_paint` and `owner_preview` import nothing. `run.py`'s function-level imports (`directives`, `reference_gate`, PIL, numpy) are not reached by those calls.
- **Guards.** The sync script's own route guard and the recorder's outside-production check stay unchanged.

**Readiness: the recorder cannot load this closure yet.**
- **Where it fails.** `script_run` accepts an `imports` entry only for a module the sync script imports by itself (`imported_modules`). It runs each pinned module from its bytes before the sync script puts `Pipeline/production` on `sys.path`. So `run.py`'s fallback `from decision_evidence import …` either fails, or it finds an unpinned live module through the host's `sys.path`.
- **The fix.** A recorder change must accept the transitive closure as pinned imports and load it in dependency order: `decision_evidence` and `stage_review_evidence` before `run`. That is a code task. It needs no stub and no guard bypass.
- **Until then.** The current round cannot run, even with every input present.

## Resource mapping and inventory

The pinned sources were checked by exact name only:
- the 29 Sash store input entries, by path;
- the piece's `Textures/` and `Textures/Swatches/` folders;
- the `round.sh` and `sashchain.sh` paths under `_tmp/claude/cintura-v5/`, which is now absent (it was present and empty on 2026-10-20).

| Input | Saved-state binding | Available | Status |
|---|---|---|---|
| Normal mesh map | `25-Faixa-Cintura_Normal_v5` | `Textures/25-Faixa-Cintura_Normal_OpenGL_bake_v5.png`, SHA-256 `ec05be82d5c5…`, SHA-1 `a32d7cb0b6f8…` | the literal text comparison is inconclusive about the bytes; identity unestablished; named substitute |
| AO mesh map | `25-Faixa-Cintura_AO_v5` | none (no store entry; `25-Faixa-Cintura_AO_v5*` absent) | missing |
| 19 masks `M_band`, `M_band_seam`, `M_band_stitch`, `M_band_top`, `M_beltgrime`, `M_cav`, `M_crest`, `M_dust`, `M_fibers`, `M_hem`, `M_hem_crack`, `M_hem_grain`, `M_hem_grime`, `M_hem_top`, `M_inner`, `M_seam`, `M_tab_edge`, `M_tab_var`, `M_weave` | `v5f_<name>_<6 hex>`; 19 bindings | none | missing; a substitute needs today's `waist_masks.py` (`959eca0bc3e2…`) and its intermediates |
| `T_sash` | `v5f_T_sash_<6 hex>`; 2 bindings | none | missing; needs both swatches |
| `sash-cloth-BaseColor-v1.png` | input of `T_sash` | absent; SHA-256 `5ab8cdf3edef…` (v5.json) | **open dependency** |
| `hem-leather-BaseColor-v1.png` | input of `T_sash` | absent; SHA-256 `546bba43d729…` (v5.json) | **open dependency** |
| `waist_masks.py` intermediates: `low.npz`, `highnormal.npy`, `ao.npy`, `construction.npz` | none (`sashchain.sh` products) | absent; `sashchain.sh` needs `bake/baked-v5.blend`, absent too | missing |
| Low OBJ and MTL | the project's mesh | front N's `tools/parity/tier1/sash_low_export.py` from the `.blend` `4c770d1dcf1f…` | in progress; a substitute |

**The Normal verdict.** The candidate's SHA-1 was compared with the recorded version string as text, with no suffix normalisation. The two strings are unequal, because the version carries a suffix. That proves only that the text differs, not that the bytes differ. So the original Normal is neither recovered nor excluded: its identity stays unestablished, and the candidate enters the round as a named substitute. No resource was extracted, no suffix was recovered and no baseline was accepted.

**The stored PNGs, by text.** As text, none of the 9 stored Sash PNGs' 40-hex SHA-1 strings equals any of the 22 recorded version strings. Every version carries the suffix, so no SHA-1 can equal one as text. The result shows that the strings differ. It neither establishes nor excludes any stored PNG as an imported original.

**Swatches.** No image generator is available, and the CLI or API authorization is still pending with the owner. No paid API was run and no key was read. `T_sash`, and through it the round, waits on the two swatches.

**Qualification.** It stays `RE_ENCODED` (decision 300), so no PROJECT resource is exported from the pilot project.

## Checks the recorded round must pass

- **Texture set.** `25-Faixa-Cintura` at 2048 px, with the five channel formats the record holds.
- **Root.** The same root shape: the synced group, plus the hidden default layer.
- **Resources.** 20 layer-stack resources and 21 bindings, with the same colour spaces.
- **Mesh maps.** Both are named `25-Faixa-Cintura_<usage>_v5`.
- **Recordings.** r1, r1-repeat and r2 are byte-identical.

## Open risks

- **Literal comparison.** Under it, no input can ever be shown identical to a recorded version, or shown different from one: every version carries the suffix. Historical input identity stays not established until a decision states a rule.
- **Not stated by the record.** The resource group, the normal-map format and `import_cameras`. The arguments above take them from the scripts or `round.sh`, whose round copies are unproven (inventory check 2). The scripts the round runs are committed substitutes: their historical bytes are unestablished.
- **The import closure.** The recorder must change before it can load the closure (see readiness above). The files at `1c9a312a` have already drifted in the live Assets3D tree, so the request takes them only as that commit's raw blobs in the private input store.
- **The changed baseline.** Using this round as the baseline still needs the owner's yes (decision 300 item 8, phase2.9 items 2.8 and 4.1).
