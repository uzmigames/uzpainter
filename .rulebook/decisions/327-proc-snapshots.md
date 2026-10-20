# 327. Frozen procedural snapshots: a canonical JSON signature, one manifest entry per signature that holds its raster plane, exact-signature serving only, and project-private by uuid

**Status**: accepted
**Date**: 2026-10-20
**Related Tasks**: phase3.2_proc-snapshot-backend, phase3.3_procedural-families

## Context

`05-procedural-content.md` §4 defines `SnapshotBackend`: a raster the user's own Painter produced for the user's own project, served only for a request whose full signature matches exactly, stored in that project's `.uzp` and never shipped or copied into another project. `09-project-file-format.md` §1 and §2 store snapshots as authoritative raster planes with a `plane_id`, and their signatures in the manifest. Items 2.1 to 2.4 of `phase3.2_proc-snapshot-backend` implement this offline; item 2.5 (`uzpainter assets snapshot`, recording through Painter) and test 3.1 (byte-equal to a private Painter export) need Painter and stay open.

Facts at the start:

- The seam (decision 324 §10) already tries a snapshot backend first. Its signature (`procedural/seam.h`) was a hand-built string with no output id and no project settings, and nothing stored it yet.
- Raster planes (`store/planes.h`) belong to paint nodes. Every plane rule (integrity, compaction reachability, revert, `inspect`, `export-bundle`, the bundle import) walks the manifest's `plane_versions` bindings.
- Codex holds `tools/parity/` while it admits Painter recordings, so the repository guard cannot get a snapshot rule now.

The coordinator's brief fixed the rules: serve on an exact signature match only, otherwise `unavailable`; no resampling or extrapolation; a snapshot is migration data only. No model panel ran: the forks below follow from §4, decision 222 and the plane design of 09 §1.

## Decision

Code: `src/procedural/seam.{h,cpp}` (`SignatureJson`), `src/procedural/admission.{h,cpp}` (`EvaluationSettings`, `UseContext::outputId` and `settings`), `src/procedural/snapshot_backend.{h,cpp}`, `src/store/snapshots.{h,cpp}`, and the plane, integrity, inspection and bundle code of `src/store/`. Tests: the `snapshot` case of `tests/procedural/procedural_test.cpp`, driven by `tests/procedural/test_proc_snapshot_backend.py`.

1. **The signature (item 2.1).**
   - `SignatureJson(request)` is one JSON object with every field of §4:
     - `asset` (the asset id, `uzasset://<family>/<id>`) and `version`;
     - `params` (the effective parameters, defaults included) and `preset`;
     - `seed`;
     - `output` {`id`, `resolution`, `format`, `colour_space`, `channels`};
     - `inputs` {name: {`sha256`, `resolution`, `format`, `colour_space`, `channels`}};
     - `mesh` {`class`, `uv_tiles`};
     - `settings`: the project settings that affect evaluation.
   - `Signature` is its canonical JSON text (`MANIFEST.md` §2), and `SignatureHash` is the SHA-256 of that text. C++ and Python therefore compute the same hash.
   - Numbers compare by value: an integral double inside the int64 range is written as that integer, so 1 and 1.0 give one signature. A non-finite number is `{"non_finite": "nan" | "inf" | "-inf"}`, which no string parameter can equal.
   - The tile stays out of the signature: a tile is a part of the same texture.
   - `ProceduralRequest` gains `outputId` (`SourceSubstance.active_output`, empty for an asset with one output) and `settings`. `UseContext` gains the same two fields, and `RequestFor` copies them.
2. **The settings that affect evaluation.**
   - `EvaluationSettings(ProjectSettings)` names `normal_map_format`, `tangent_space`, `mesh_unit_scale`, `color_management.mode`, `color_management.config_hash`, `color_management.working_space` and `color_management.io_rules_sha256` (the SHA-256 of the rules' canonical JSON).
   - Assumption: Painter's documentation does not say which settings a generator reads. The list holds every setting that can change a procedural's texels. A longer list can only make a match rarer, never wrong.
3. **Storage (item 2.3).**
   - The manifest's top-level `procedural_snapshots` holds one entry per snapshot, keyed by its signature hash: {`signature`, `project_uuid`, `plane`, `plane_versions`}.
   - The entry holds its plane exactly as a mask-stack paint object does, and `ManifestPaintPlanes` reads the entries beside the paint objects. Every plane rule therefore covers snapshots unchanged: the digest, revert, compaction, integrity, `inspect`, `export-bundle` and the bundle import.
   - The plane row has no texture set, stack, channel or UV tile (0 and NULL). A snapshot belongs to the project, not to a node.
   - The plane format follows the output spec: `L8`/`RGB8`, `L16`/`RGB16`, `L16F`/`RGB16F` or `L32F`/`RGB32F` for 1 or 3 channels of u8, u16, f16 or f32. The recorded texels are stored unmodified. An output of 2 or 4 channels has no plane format and is refused when it is recorded.
   - `WritePlaneRows` also refuses a plane held by two objects, so a snapshot plane can never alias a paint plane.
   - The document model keeps the key verbatim in `Project::extra`, and the store owns it, as with `plane_versions`. The recipe dump drops unknown keys, so snapshots never enter a recipe: a rebuild is a new project.
   - `ProjectStore::RecordSnapshot` stages a snapshot from a transaction's call. A second snapshot of the same signature is refused, because a snapshot is immutable migration data.
   - `inspect` lists every entry under `procedural_snapshots` with its plane's version, format and size.
4. **Serving (item 2.2).**
   - `SnapshotBackend::Load(store, project)` reads every entry through its plane binding.
   - It refuses, naming the entry:
     - an entry that is malformed;
     - an entry stored under another key than its signature's hash;
     - an entry recorded for another project;
     - a plane whose format or size is not the output the signature names.
   - `CanEvaluate` is true only for a stored signature hash and a tile inside the output.
   - `Refusal` is `no snapshot with this signature`. It names the first field where the request differs from the closest stored signature of the same asset id.
   - `Stored` returns the recorded bytes. `Evaluate` returns them as float32: u8 and u16 codes are divided by 255 and 65535, and f16 is widened exactly. A tile is a copy of the stored texels. Nothing is resampled or extrapolated.
   - `Status` is `unavailable` for every asset: a snapshot certifies nothing, is never calibration or held-out evidence and never widens a certified domain (decision 222).
   - A changed parameter changes the signature. The edit is then served by another backend or refused before its transaction opens (decision 324 §10).
5. **Project-private (item 2.4).**
   - Each entry records the uuid of the project it was recorded for.
   - The commit refuses any entry whose uuid is another project's, or whose key is not its signature's hash (`CheckSnapshots`, `conflict`). So does the bundle import, and the integrity check reports such an entry as a `snapshot` corrupt item (`inspect --verify`). `SnapshotBackend::Load` refuses it.
   - A layer's `ProceduralRef` copied into another project carries no snapshot. There it is admitted only by that project's own snapshots or a certified family. Otherwise it raises `UnsupportedProcedural`.
   - `save_as`, `save_as_copy`, revert and the bundle import keep the project's uuid, so they are the same project and keep its snapshots.
6. **Never shipped (item 2.4).**
   - `test_no_snapshot_in_shipped_asset_folders` reads the folders build.zig installs beside the executables (`*_dir = "assets/..."`). It fails on any `.uzp`, any `bundle.json` and any file that holds `procedural_snapshots`.
   - The asset library's load already refuses any record member that is not in its schema (decision 324 §2).
   - The repository guard's rule that rejects a snapshot blob (test 3.4, second half) belongs to `tools/parity/guard`. It waits for Codex to release `tools/parity/`.

## Alternatives Considered

- **Keep the hand-built signature string.** Rejected. It escaped only `"` and `\`, so a parameter string with a control character gave invalid JSON. It also had no output id and no project settings. Canonical JSON already has one definition in C++ and Python.
- **A typed `Project::procedural_snapshots` member in the document model.** Rejected for now. The store owns the planes and their bindings, and the document model already keeps the store's `plane_versions` verbatim. A typed member would add a model, schema and migration surface for data that no edit touches, apart from recording it.
- **Snapshots as planes owned by the generator or filter effect that uses them.** Rejected. A snapshot belongs to a signature, not to a node. Two effects with the same signature share one snapshot, and deleting a node must not delete migration data that another node still uses.
- **Serving the nearest resolution or interpolating parameters.** Rejected by §4: that is resampling or extrapolation.

## Consequences

- Item 2.5 (`uzpainter assets snapshot`) records through Painter's documented export API with `RecordSnapshot`. The owner's Painter is needed, so the item and test 3.1 stay open.
- An RGBA (4-channel) or 2-channel output cannot be recorded until a plane format holds it. Item 2.5 raises `NotYetSupported` naming this task for such an output.
- The seam's callers (item 2.6 and phase3.3) resolve `UseContext::outputId` and `settings` from the document. `EvaluationSettings` gives the settings.
- The repository guard rule waits for `tools/parity/` to be released.
