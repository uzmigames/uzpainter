# Sash v5 current round: input contract

The input contract for the pinned current round `phase2/tier1/sash-v5-current` (decision 300 item 7). It is derived from the Sash v5 migration golden admitted on 2026-11-02. This page holds only counts, public file names, statuses and hashes. The full contract, with the readback values it was derived from, is private (`%LOCALAPPDATA%\UzPainter\sash-v5-current-contract.json`, SHA-256 `b5901254b821…`, 37,953 bytes).

**Result.** The round still cannot be requested. Of its seven input kinds, one is available as a named substitute (the Normal), one is in progress (the low OBJ and MTL, front N), and five are missing: AO, the 19 masks, `T_sash`, the two swatches, and the generator intermediates.

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
| 2 `painter_layer_stack.py sync` | script bytes | **unknown**: the stored decision 260 copy `d3eebe58b98b…` or the Assets3D HEAD copy `62702cb30030…`; the round's copy matches no commit |
| | `--stack` | `stack-sash.json`, derived (structure equal) |
| | `--masks` | staged folder with the 19 masks and `T_sash.png`: **missing** |
| | `--state` | a fresh file, so every bitmap is imported; the historical round tag is unknown |
| | `--resource-prefix` | `v5f_`, derived (all 20 names) |
| | `--resource-group` | `faixa25_v5`, from `round.sh` only; groups are not read back |
| | `--texture-set` | `25-Faixa-Cintura`, derived |
| | `--keep-visible`, `--stack-key` | none (`round.sh`), consistent with the hidden root layer |
| 3 `painter_export.py` (`48c294a43cbc…`) | `out` | decision 099 fresh directory |
| | `prefix` | authored, see the export route; historical `25-Faixa-Cintura_v5<tag>`, tag unknown |

**The export route has an open conflict.**
- **The two sources disagree.** Decision 300 item 7 exports through `painter_export.py`. The migration manifest and `parity/RECORDER.md` §9b say the current round exports with `parity/fixtures/tier1/sash-v5/export-config.json`.
- **The inline configuration is nearly the same.** `painter_export.py` builds the same five maps, channels, sources and parameters as `export-config.json`. Only the preset name and `exportPath` differ.
- **Option A.** No fourth step, and the prefix is `25-Faixa-Cintura`. The script then writes the migration's five map names. `current_reference` pairs them one to one.
- **Option B.** A fourth `export_project_textures` step with `export-config.json` (the Wand float precedent). Two problems follow:
  - The prefix must then differ from `25-Faixa-Cintura`, or the recorder refuses maps of the same name.
  - `current_reference` then sees 10 maps against 5. It reports a structural difference unless it is changed to compare only the configuration export.
- **Recommendation.** Option A, named in the request as an authored argument. The coordinator decides.

## Resource mapping and inventory

The pinned sources were checked by exact name only:
- the 29 Sash store input entries, by path;
- the piece's `Textures/` and `Textures/Swatches/` folders;
- the `round.sh` and `sashchain.sh` paths under `_tmp/claude/cintura-v5/`, which is now absent (it was present and empty on 2026-10-20).

| Input | Saved-state binding | Available | Status |
|---|---|---|---|
| Normal mesh map | `25-Faixa-Cintura_Normal_v5` | `Textures/25-Faixa-Cintura_Normal_OpenGL_bake_v5.png`, SHA-256 `ec05be82d5c5…`, SHA-1 `a32d7cb0b6f8…` | literal comparison **unequal**: not recovered; named substitute |
| AO mesh map | `25-Faixa-Cintura_AO_v5` | none (no store entry; `25-Faixa-Cintura_AO_v5*` absent) | missing |
| 19 masks `M_band`, `M_band_seam`, `M_band_stitch`, `M_band_top`, `M_beltgrime`, `M_cav`, `M_crest`, `M_dust`, `M_fibers`, `M_hem`, `M_hem_crack`, `M_hem_grain`, `M_hem_grime`, `M_hem_top`, `M_inner`, `M_seam`, `M_tab_edge`, `M_tab_var`, `M_weave` | `v5f_<name>_<6 hex>`; 19 bindings | none | missing; a substitute needs today's `waist_masks.py` (`959eca0bc3e2…`) and its intermediates |
| `T_sash` | `v5f_T_sash_<6 hex>`; 2 bindings | none | missing; needs both swatches |
| `sash-cloth-BaseColor-v1.png` | input of `T_sash` | absent; SHA-256 `5ab8cdf3edef…` (v5.json) | **open dependency** |
| `hem-leather-BaseColor-v1.png` | input of `T_sash` | absent; SHA-256 `546bba43d729…` (v5.json) | **open dependency** |
| `waist_masks.py` intermediates: `low.npz`, `highnormal.npy`, `ao.npy`, `construction.npz` | none (`sashchain.sh` products) | absent; `sashchain.sh` needs `bake/baked-v5.blend`, absent too | missing |
| Low OBJ and MTL | the project's mesh | front N's `tools/parity/tier1/sash_low_export.py` from the `.blend` `4c770d1dcf1f…` | in progress; a substitute |

**The Normal verdict.** The candidate's SHA-1 was compared with the recorded version string as text, with no suffix normalisation. The two strings are unequal, because the version carries a suffix. So the original Normal is not claimed recovered.

**No stored PNG matches.** None of the 9 stored Sash PNGs has a SHA-1 equal to any of the 22 recorded versions.

**Swatches.** No image generator is available, and the CLI or API authorization is still pending with the owner. No paid API was run and no key was read. `T_sash`, and through it the round, waits on the two swatches.

**Qualification.** It stays `RE_ENCODED` (decision 300), so no PROJECT resource is exported from the pilot project.

## Checks the recorded round must pass

- **Texture set.** `25-Faixa-Cintura` at 2048 px, with the five channel formats the record holds.
- **Root.** The same root shape: the synced group, plus the hidden default layer.
- **Resources.** 20 layer-stack resources and 21 bindings, with the same colour spaces.
- **Mesh maps.** Both are named `25-Faixa-Cintura_<usage>_v5`.
- **Recordings.** r1, r1-repeat and r2 are byte-identical.

## Open risks

- **Literal comparison.** Under it, no input can ever be shown identical to a recorded version: every version carries the suffix. Historical input identity stays not established until a decision states a rule.
- **Not stated by the record.** The sync script's bytes, the resource group, the normal-map format and `import_cameras`. The arguments above take them from the scripts or `round.sh`, whose round copies are unproven (inventory check 2).
- **The changed baseline.** Using this round as the baseline still needs the owner's yes (decision 300 item 8, phase2.9 items 2.8 and 4.1).
