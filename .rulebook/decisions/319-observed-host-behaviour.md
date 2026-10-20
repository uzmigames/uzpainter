# 319. The admitted P21, R10 and P23-A goldens settle host behaviours that decisions 105, 109 and 110 left open

Date: 2026-10-20. Status: accepted. Claude and Codex decided under the owner's delegation of 2026-10-19; the coordinator assigned the number.
Related: `phase1.24_python-api-facade` item 4.1; decisions 097, 105, 109, 110, 180, 198, 205.

## Context

Decisions 105, 109 and 110 refused, or implemented provisionally, the host behaviours that recordings P21-A to P21-F, R10 and P23-A would settle. Decisions 180, 198 and 205 admitted those recordings, plus P21-G. Item 4.1's compared replays (`tests/python/test_pyapi_observed_*_tier0.py`, helper `tests/python/observed_replay.py`) read them from the private store at run time.

## Decision

Each point below follows both recordings of its golden, and supersedes the clause it names.

1. **Queued `ProjectEditionEntered`** (P21-F, all four recordings; P21-G s10 and r2 `start/events`). Supersedes decision 109 §3.
   - In Painter, the busy pair and `ProjectCreated`/`ProjectOpened` carry the call's step marker. `ProjectEditionEntered` does not.
   - `create` and `open` now return in edition and queue `ProjectEditionEntered` (`host.enter_edition`).
   - The replays deliver the queued events at the recorder's remote-call boundary (`observed_replay.call`, and the lifecycle replay's `call`).
   - Before the edition state changes again (a `close` right after `create`), the host first delivers what is still queued, so `ProjectEditionEntered` reads the state in which it was sent.
2. **`create(mesh_map_file_paths=...)`** (P21-A, `phase1-create-mesh-maps`). Supersedes decision 110 §2.
   - Each `<texture set>_<suffix>` file is imported under its file name and bound to its usage, for seven suffixes (`project.MESH_MAP_SUFFIXES`):

     | Suffix | Usage |
     |---|---|
     | `ambient_occlusion` | AO |
     | `id` | ID |
     | `curvature` | Curvature |
     | `normal_base` | Normal |
     | `world_space_normals` | WorldSpaceNormal |
     | `position` | Position |
     | `thickness` | Thickness |

   - Any other name, a missing file, or a name that matches no texture set stays `NotYetSupported`.
   - A binding keeps the name of the resource it was given, in project metadata (`textureset.MESH_MAP_NAMES`). Resources with equal bytes therefore stay apart: s7 and s10, s3 and s11, s8 and s12.
3. **`Settings.default_save_path` and `export_path`** (P21-B, `phase1-create-default-paths`) are accepted, and no documented call reads them. Supersedes decision 110 §2.
4. **`TextureStateEvent.cache_key_invalidation_throttling_period()`** returns 2000 ms until a script sets a period (P21-C, `phase1-texture-throttling`). Supersedes decision 110 §5.
5. **Shelf crawls** (P21-D, `phase1-shelves` s3 and s9). Supersedes decision 110 §3's open timing.
   - `Shelves.add` crawls its folder.
   - `ShelfCrawlingStarted` is delivered during the call that starts a crawl.
   - `ShelfCrawlingEnded` is delivered once the walk ends.
6. **`LayerStacksModelDataChanged`** (P21-E, `phase1-layer-stack-events`). Supersedes decision 110 §4's "every other edit emits nothing" for the calls named here.
   - **Emitted during the call:**
     - `insert_levels_effect`;
     - `remove_mask`;
     - `set_blending_mode` and `set_opacity`, also when unchanged;
     - `set_visible`, only on a change.
   - **No event**, as recorded: `set_mask_background`, `enable_mask`, `set_projection_mode`, `set_projection_parameters`, `affected_channel`, `SourceUniformColor.set_color`, `reset_source` and the `SourceBitmap` colour-space setters.
   - `set_symmetry_enabled(True)` on a UV fill raises `ValueError("Symmetry is only available when using 3D projection modes")` (s28). The 3D modes stay refused (phase3.4_smart-projections).

7. **Engine computations** (R10, `phase1-engine-computations`). Supersedes decision 110 §1's provisional behaviour.
   - While computations are disabled, edits apply and `export_project_textures` completes with `Success` (s13). The facade does not wait for computations to be enabled again.
   - The export's events, all during the call, are `ExportTexturesAboutToStart` (not busy), then `BusyStatusChanged(1)`, then `ExportTexturesEnded` (busy), then `BusyStatusChanged(0)`.
8. **`save_as` onto an existing project** (P23-A, `phase1-save-as-existing`). Supersedes decision 105 for the facade's saving.
   - `substance_painter.project.save_as` replaces an existing closed target atomically, through the native private `_save_as_replace`. The replacement is opt-in in the facade only.
   - The native `uzpainter.project.save_as` stays create-only.
   - `save_as_copy` stays create-only.
   - The refusal of `-journal`, `-wal` and `-shm` companions stays.
   - The public native `save_as` gets no Tier 0 credit for this private path.
9. **Two file-output comparison rules** of the replays (`s<n>/files`). No other `files` output is excluded.
   - (a) **Lock files.** Only the suffix `.lock` of the project's lock is mapped to Painter's `.painter_lock`. The lock's presence, base name, path and phase stay compared. The owner is the store's lock sidecar (`docs/architecture/09`, SAV-05).
   - (b) **Export folders** (R10 s13; the owners are decisions 097 and 105). UzPainter publishes an export as a generation, so its folder holds more than Painter's.
     - The declared publication metadata must be present, each file with a SHA-256: `current.json`, `fixed-names.journal.json`, `publication.lock`, and the generation's `plan.json` and `receipt.json`. Their content is not compared with Painter's.
     - Each published copy in `generations/<id>/files/` must have Painter's file name and SHA-256.
     - Every other file is compared exactly with Painter's list, by name and SHA-256, so an unknown extra file fails.

## Consequences

- `tests/python/test_pyapi_dispatcher.py` and `test_capability_conformance.py` follow these behaviours. The throttling getter and the two settings are no longer release gaps.
- Each of these symbols becomes `supported` only once a compared replay proves it exact (decision 112).
- The outputs that are still refused, Painter-unstable, or Painter's installation values are listed by name in the replays and in `parity/reports/phase1/python-api-facade.md` §7.
