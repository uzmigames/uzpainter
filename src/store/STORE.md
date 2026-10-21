# Project store: container, blobs, raster planes, the mutation commit and saving (`src/store/`)

Tasks `phase1.4_store-container-operations`, `phase1.5_store-planes`,
`phase1.6_store-save-retention` and `phase1.7_store-inspect-census` (children of P1-STORE,
`phase1.8_project-store`).
Implements the container of D8 (decision 010) in `docs/architecture/09-project-file-format.md`
§1, §2, §4 and §5, the durability contract of D1 (`02-runtime-topology.md` §3, §5: the operation
record is committed atomically with its revision; every commit is the autosave) and the
idempotency record of ARC-02. The document model it stores is `src/uzp_core/` (`MANIFEST.md`,
`TRANSACTIONS.md`). The raster planes of §8 implement 09 §1 "Authoritative raster planes" and the
paint planes of `04-layer-stack-and-compositing.md` §1. `save()`, named and protected
checkpoints, retention, revert, `compact`, `save_as`, `save_as_copy` and the lock sidecar (§9)
implement 09 §4 with owner answer Q11 (decision 024); `uzpainter inspect`, `export-bundle` with
the bundle import and the size census (§10, §11) implement 09 §3 and §6.

## 1. Layout

| Path | Content |
|---|---|
| `container.h` | `Container` (one SQLite connection), `Statement`, `WriteTransaction`, `StoreError`, zstd `Compress`/`Decompress` |
| `blobs.h` | Content-addressed blobs, `blob_meta` names, non-portable locators, `HashFile` |
| `commit.h` | `CommitMutation`, `WriteResources`, `WriteRevision`, stored operation rows, `DecideStored`, `CommitExtension` |
| `versioning.h` | `FormatVersion`, `VersionPolicy`, `CheckReadable`, `MigrateManifest` |
| `integrity.h` | `CheckIntegrity`, `IntegrityReport`, `CorruptionError`, `NodesBinding` (affected nodes), `ReadManifestText`, `QuickCheck` |
| `planes.h` | Raster planes: plane rows, immutable versions, chunk codec, `chunk_root`, manifest bindings, staging, the commit extension and the read path (§8) |
| `plane_integrity.h` | `CheckPlaneIntegrity`: the plane rules, run by `CheckIntegrity` (§8) |
| `snapshots.h` | Frozen procedural snapshots: the manifest's `procedural_snapshots` entries, `StageSnapshot`, `CheckSnapshots` (§8, decision 327) |
| `project_store.h` | `ProjectStore`: `Create`, `Open`, `Close`, `Attach`, `Submit`, `StageResource`, `StageLocator`, `ReadResource`, `CreatePlane`, `WritePlane`, `WriteBitmap`, `ReadPlane`, `ReadPlaneChunk`, `RecordSnapshot`, `Save`, `NeedsSaving`, `Compact`, `SaveAs`, `SaveAsCopy`, `Revert` |
| `save.h` | Checkpoint rows, `save()`'s rows (`WriteSaveCheckpoint`), the dirty flag, the revert project (§9) |
| `compact.h` | Retention (`ComputeRetention`), reachability, `CollapseAndCollect`, `VacuumInto`, `RenameFile` (§9) |
| `lock.h` | The lock sidecar `<file>.uzp.lock` (`ProjectLock`, §9) |
| `fault.h` | Test-only fault hooks (§6) |
| `inspect.h` | `Inspect` (the report of `uzpainter inspect`), `WriteIndented`, `ReadSnapshot` (§10) |
| `bundle.h` | `ExportBundle`, `ImportBundle`, `IsBundleDirectory` (§10) |
| `bundle_codec.h` | PNG and OpenEXR at a plane's native precision, inflate, CRC-32, the ZIP writer (§10) |
| `census.h` | The size census: inputs, the scripted sequence, the report (§11); the inputs of the Phase 1 run are `census_inputs.json` |
| `cli.h` | The verbs `inspect`, `export-bundle` and `store-census` of `UzPainter.exe` (§10, §11) |

`zig build uzp-store` builds `uzp_store.lib` from these sources, the SQLite amalgamation
(`thirdparty/sqlite/`, public domain, 3.54.0) and zstd (`thirdparty/zstd/`, BSD-3-Clause branch,
v1.5.7), both vendored with `tools/vendoring/thirdparty.py`; it links `uzp_core.lib` and nothing
else: no render layer, no GPU. `UzPainter.exe` links it for the verbs of `cli.h`.

## 2. Container

The tables are those of 09 §1: `meta`, `revision`, `blob`, `blob_meta`, `plane`,
`plane_version`, `plane_chunk`, `operation`, `cache` and `checkpoint`, plus `locator (sha256 TEXT
PRIMARY KEY, path TEXT NOT NULL)`, which holds the `{path, sha256}` locators of a non-portable
project (09 §2). The plane tables carry the indexes and immutability triggers of §8. Every
connection runs with `PRAGMA foreign_keys = ON` and `synchronous = FULL`; files use
`journal_mode = DELETE`, so no `-wal`/`-shm` companion exists and an interrupted commit leaves a
hot rollback journal that SQLite plays back on the next open. Every payload is an independent
zstd frame (level 3, content size and checksum in the frame): blob data, revision manifests and
operation outcomes.

`meta` holds `project_uuid`, `created`, `portable` (`1`/`0`), `operation_horizon_revision` and,
mirrored from the manifest of the last written revision, `format_version`, `app_version`,
`evaluator_profile`, `compat_profile` and `painter_reference` (canonical JSON). Keys this version
does not know are left untouched.

`Create(path, state, options)` takes the lock (§9) and writes, in one SQLite transaction, the
schema, `meta`, the resources the initial project references, its revision (`kind = checkpoint`)
and `checkpoint('current')`. A failed creation removes the file.

## 3. Resources

`blob` stores each distinct content once, keyed by its SHA-256: `size` is the original byte
count, `data` the zstd frame of the original bytes, which come back unmodified. Each resource
name of the manifest (`resources[<sha256>][]`) is one `blob_meta` row, so two imports of identical
bytes share one blob and keep two names. Bytes are staged with `StageResource` from inside a
transaction's call; the commit inserts the staged content of every hash the committed project
references and does not hold yet.

Portable mode (the default) embeds every dependency: a commit that references a hash with neither
stored nor staged bytes fails (`missing_resource`) and writes nothing, and `StageLocator` is
refused. A project created with `portable = false` may stage `{path, sha256}` locators instead;
`ReadResource` reads the file and checks its hash, and `Open` reports a locator whose file is
absent or no longer hashes to its SHA-256 as a missing dependency with the nodes that bind it.

## 4. The mutation commit

`Attach(document)` makes the store the document's commit sink. The sink runs `CommitMutation`
under the document lock, before the new revision becomes visible, as one SQLite transaction:

1. check that the snapshot's revision follows `checkpoint('current')` and that the record names
   this project and revision (`conflict` otherwise);
2. insert new blobs and `blob_meta` names (or locators);
3. write the plane rows of the transaction (`WritePlaneRows`, §8), then run the commit extensions
   (`AddCommitExtension`);
4. insert the `revision` row: `kind = mutation`, `parent` = the previous revision, the zstd
   canonical manifest and `manifest_sha256` (equal to `ManifestDigest`), and mirror the versions
   into `meta`;
5. insert the `operation` row `{idempotency_key, project_uuid, request_hash, outcome (zstd
   canonical JSON of the result), committed_revision, created_at}`;
6. move `checkpoint('current')`;
7. `COMMIT`.

Any failure rolls the transaction back and the sink throws, so the transaction's result is
`failed` and the document is unchanged: a failed mutation writes no row. A full disk surfaces as
`disk_full: … database or disk is full`.

`Submit(document, request, call)` decides the request with `DecideAdmission` against the stored
rows before executing it (`DecideStored`): the `operation` row of the key, the current revision
from `checkpoint('current')` and the horizon from `meta.operation_horizon_revision`. A known key
with the same request hash returns the stored outcome (even when the current revision is newer),
another hash is `idempotency_conflict`, an unknown key without a precondition or with one below
the horizon is `outcome_unknown`, a precondition other than the current revision is
`stale_revision`, and only an equal one executes. A row that cannot be read (undecodable outcome,
another project) makes the decision `outcome_unknown`, so the call is never executed twice.

## 5. Opening, versions and integrity

`Open(path, options)`:

0. takes the lock sidecar (§9) and removes the temporary files a killed `compact` left
   (`<file>.compact`, `<file>.vacuum`), then runs SQLite's structural check (`QuickCheck`:
   `PRAGMA quick_check`, every b-tree page, cell and overflow pointer and the free list, each page
   read once) and refuses a damaged file with `CorruptionError` (kind `sqlite`, key
   `quick_check`, the first problems found) before anything is read from it or written to it: a
   commit into a damaged b-tree could spread the damage to pages that were sound (B9 of
   `parity/reports/phase2/practical-e2e.md`);
1. reads `meta.format_version` and refuses another major with `StoreError(version)` before
   anything can write to the file (a newer major: "format_version 2.0.0 is newer than this reader
   supports (1.0.0)");
2. reads the current revision's manifest and refuses one that does not decompress or does not
   hash to its `manifest_sha256` (`CorruptionError`);
3. migrates an older minor in memory, step by step (`VersionPolicy::migrations`), and stamps the
   reader's version: the file is unchanged until the next commit, which writes the migrated
   manifest as a new revision and updates `meta.format_version` (older revisions keep theirs). A
   newer minor of the same major is read as it is; unknown manifest keys are kept verbatim
   (`MANIFEST.md` §4) and written back;
4. loads the readable operation rows into the `DocumentState` (unreadable ones are reported and
   left to `DecideStored`);
5. unless `OpenOptions::report` is false, runs `CheckIntegrity`: `PRAGMA foreign_key_check`, every retained manifest against its
   `manifest_sha256`, every operation row, every locator, the plane rules of §8 (with the bytes of
   the chunks the current manifest binds); with `VerifyLevel::full` also `PRAGMA quick_check`,
   the SHA-256 of every blob and the bytes of every chunk any retained manifest binds.

The session's open (`src/python/session.cpp`: the facade, `run`, the MCP worker) passes
`report = false`: it never read the report, whose scan of every retained manifest and locator
took 88-186 ms on a 168-revision project (decision 253); `inspect --verify`, `export` and the
census still build it.

Corrupt history, blobs and missing dependencies are reported in `Opened::report`, never thrown;
only a damaged SQLite structure (step 0) and a current manifest that does not verify (step 2) are.
`ReadResource` always verifies: a blob that does not decompress or does not hash to its key
raises `CorruptionError` naming the hash and the nodes of the current manifest that bind it (the
id of the nearest object with an `id`/`uid` and the JSON path, e.g.
`texture_sets[0].stacks[0].root_layers[0].fill.sources.BaseColor.resource.sha256`); its bytes are
never returned. The `DocumentState` carries the last named checkpoint and `previous` (§9).

## 6. Fault hooks (test builds only)

`fault.h` exists only when `UZP_STORE_FAULT_HOOKS` is defined, which `build.zig` does for
`uzp-store-tests.exe` alone; `uzp_store.lib` contains none of it (checked by
`tests/store/test_project_store.py`). The hooks work through a SQLite VFS that wraps the
platform VFS: `kill_during_commit` terminates the process right after the first page write to
the database file made by `COMMIT` (journal hot, file torn), `disk_full` fails every write that
would grow the database file with `SQLITE_FULL`, and `kill_after_commit` terminates the process
after `COMMIT` returned, before the commit sink returns. `kill_before_revision_row` terminates the
process inside the commit transaction right after the plane rows were inserted (`AfterPlaneRows`),
before the revision row. For `compact`, `save_as` and `save_as_copy` (§9): `fail_during_vacuum`
fails every page write to the output of `VACUUM INTO` (`SQLITE_IOERR_WRITE`),
`kill_during_vacuum` terminates the process after the first one, `kill_before_rename` terminates
the process between `VACUUM INTO` and the rename, and `fail_rename` fails that rename.

## 7. Tests

`python -m pytest tests/store` builds `uzp-store-tests.exe` (`zig build uzp-store-tests`; own
code compiled with `-Wall -Wextra -Werror`) and runs its native cases, each in its own folder under
the system temp directory:

| Case | Checks |
|---|---|
| `schema_and_pragmas` | the tables, `journal_mode = delete`, enforced foreign keys, `meta`, zstd frames, canonical manifest and digest, no `-wal`/`-journal` at rest, `Create` on an existing path |
| `commit_atomicity` | a child killed during `COMMIT` leaves a hot journal and a torn file; reopening rolls back to the previous revision with no operation row; the same request then commits with its row |
| `disk_full` | explicit `disk_full` error, document and file at the previous revision (integrity check ok), the retry commits |
| `corrupt_blob` | altered content and a damaged frame: reported by `VerifyLevel::full` and by `ReadResource` with the binding node |
| `corrupt_manifest` | an older manifest is reported, the current one refuses to open, both through `manifest_sha256` |
| `corrupt_structure` | a file with 64 KiB overwritten with 0xAB in its middle (B9 of `parity/reports/phase2/practical-e2e.md`; `quick_check` fails): `Open` refuses it at both verify levels with `CorruptionError` (`sqlite`, `quick_check`) naming the damaged pages; the file's bytes are unchanged and no lock sidecar is left |
| `commit_then_die` | a child killed after the durable commit: the retry returns the stored outcome with no second revision, also once the current revision is newer; a changed request with the key is `idempotency_conflict` |
| `unknown_key_rules` | missing precondition → `outcome_unknown`; ≠ current → `stale_revision`; = current → executes; below the stored horizon → `outcome_unknown`; an unreadable row → `outcome_unknown`, reported on reopen |
| `deduplication` | two imports of identical bytes: one blob, two `blob_meta` names, original bytes returned |
| `versioning_newer_major` | refused with an explicit error, file bytes unchanged |
| `versioning_older_minor` | migrated in memory, file bytes unchanged until the next commit, then `meta.format_version` and the new revision carry 1.1.0; unknown keys kept; a missing step is an explicit error |
| `non_portable_missing` | locator stored, absent and changed targets reported with the binding node; a portable project refuses locators and commits without bytes |
| `round_trip` | revisions, operation records and project survive reopen; no-op and failed calls write nothing; a commit extension runs inside the transaction and rolls it back when it throws |
| `planes_no_alias` | two paint layers with planes on one set/stack/channel/tile: saved, reopened, one edited, reverted (a mutation copying the old manifest), reopened; each reads its own bytes at every revision, the untouched plane is byte-identical, versions and chunks never shared |
| `planes_copy_on_write` | a 4096×4096 plane (16 chunks): an edit inside chunk (2,1) adds exactly one blob and copies 15 hash rows; the previous version and its pixels are unchanged; identical content is a no-op; the triggers refuse changes to committed rows; an unbound version is listed as collectable |
| `planes_binding_resolution` | a plane edited at three revisions with unrelated revisions between: each revision reads exactly the content its manifest binds; a revision before the plane binds none |
| `planes_empty_chunks` | a version with rows only for chunks (0,0) and (2,1): chunk (1,1) reads as zeros; `chunk_root` equals the SHA-256 of the canonical JSON list; a never-written plane has no rows and the root of `[]` |
| `planes_native_formats` | every `ChannelFormat` (and the channel-less plane of a mask-stack paint effect) round-trips bit-exact, with partial edge chunks |
| `planes_interrupted_commit` | a child killed between the plane rows and the revision row: reopening gives the previous revision with the same manifest, pixels, versions, chunk rows and blobs; the same request then commits |
| `planes_corruption` | an altered chunk blob and a `plane_chunk` row pointing at another blob: each reported on open and by `VerifyLevel::full` (`SHA-256 mismatch`, `chunk_root mismatch`) with the plane and the owning paint layer; reads of the damaged plane raise `CorruptionError`, the other plane reads intact |
| `planes_binding_rules` | the commit refuses a plane without a binding and a binding of a plane the node does not hold; size, channel, node-kind and UV-tile errors fail the call; three planes coexist on one channel and tile; deleting a node drops its binding; `Create` refuses planes |

`python -m pytest tests/store/test_store_save.py` builds `uzp-store-save-tests.exe` (`zig build
uzp-store-save-tests`, `tests/store/save_test.cpp`, the same hooked store sources) and runs:

| Case | Checks |
|---|---|
| `checkpoints` | `save()` names the current revision and moves `previous` (7 → 8: `previous` = 7); `needs_saving()` false after a save, true after a mutation, exact after a revert and after `save_as_copy`; named saves with a note; reserved names refused; checkpoints survive reopen; a revert copies the selected manifest (with the current `next_id`) as a new revision, history append-only |
| `retention_window` | 60 mutations with checkpoints a, approved (protected), b, c and a save at 60: retained exactly 4, 8, 11..60; a and b collapsed; operation rows of collapsed revisions deleted; horizon 10; `cache` emptied; a collapsed revision cannot be reverted to, a protected one can |
| `protected_checkpoint` | saving (and `save_as`) under a protected name is refused (`protected_checkpoint`); 55 mutations later and compacted, its manifest and pixels are unchanged |
| `revert_edit_reopen_compact` | paint (approved, protected) → two edits → 80 mutations → revert → edit → reopen → compact: manifests and pixels of every retained state equal byte for byte, including the protected checkpoint and a version first written by a collapsed revision; a version only collapsed revisions bound is collected with its chunk |
| `garbage_collection` | after compaction every `plane`, `plane_version`, `plane_chunk`, `blob` and `blob_meta` row is reachable from a retained manifest and every reachable one exists (computed from the manifests alone); a dropped resource and a deleted layer's plane are collected; later commits and new plane ids work |
| `pruned_key_replay` | a non-idempotent mutation (key `k1`, precondition 3) pruned by compaction: replays with precondition 3 and with none are `outcome_unknown` with no revision; `k2` inside the window returns its stored outcome at a newer revision; the same after reopen |
| `save_as_and_copy` | `save_as_copy` keeps path, lock and dirty state, the copy opens portable; `save_as` saves, relocates the project and its lock, leaves the original unchanged; existing and locked targets refused |
| `interrupted_rewrite` | I/O failure during `VACUUM INTO` and of the rename for `compact`, `save_as`, `save_as_copy`: error names the operation and the step, original bytes unchanged, no target or temporary file, the store keeps working; a child killed during `VACUUM INTO` / before the rename of `compact` and during `VACUUM INTO` of `save_as`: the original reopens at its previous state, temporaries removed, the rewrite then completes |
| `portability` | after `close`, `compact` and `save_as` no `-wal`/`-shm`/`-journal`; the header says rollback journal; a copied `.uzp` opens from another folder |
| `lock_sidecar` | the sidecar holds this pid; a second open in the same process and an open while a child worker holds it are refused naming the pid; `close` removes it; a worker killed while holding it leaves no sidecar (the OS deletes it with the handle, B14); a stale sidecar (a dead owner, a reused pid with another start time, this live pid, an unreadable one) is replaced; a held one is not stolen; a closed store refuses calls |

`python -m pytest tests/store/test_store_inspect.py` builds `uzp-store-inspect-tests.exe` (`zig
build uzp-store-inspect-tests`, `tests/store/inspect_test.cpp`) and runs:

| Case | Checks |
|---|---|
| `inspect_fields` | every field of 09 §6 on a fixture (versions, profiles, settings, texture sets and channels, the layer tree with resource and plane bindings, mesh maps with provenance, the resource table, checkpoints, sizes, the recipe digest reported unavailable); `--revision`; the CLI prints the same report, usage errors exit 2 |
| `inspect_while_locked` | a child process holds the project (lock sidecar, open connection): `inspect` and `inspect --verify` complete, the lock stays the child's, the file bytes are unchanged |
| `inspect_external_dependencies` | a non-portable project: project-file bytes and external dependency bytes listed separately; a removed target is counted missing and fails `--verify` |
| `verify_failures` | `inspect --verify` exits 1 on a broken plane binding (`chunk_root mismatch`, with the plane and its node), on a missing resource blob (`blob … missing`, with the binding node) and on a missing chunk blob |
| `bundle_round_trip` | `export-bundle` to a directory and to a ZIP; `ProjectStore::Open` of the bundle directory: equal manifest digest, plane pixels and resource bytes, `--verify` clean, further commits work; an older revision; a damaged plane file and a changed manifest are refused and leave no project |
| `codec_formats` | every `ChannelFormat` round-trips bit-exact through PNG or OpenEXR; mismatched formats and truncated files are refused |
| `census_sequence` | the census on a scripted sequence: bytes per edit (file growth and bytes written), reopen time, compaction time, retained-history size, ratio to the `.spp` size |

The driver also checks the ZIP bundle with Python's `zipfile` and the PNG reader against PNGs that
Python's zlib compressed (fixed and dynamic Huffman blocks, every scanline filter).

`python -m pytest tests/store/test_store_settle.py` builds `uzp-store-settle-tests.exe` (`zig build
uzp-store-settle-tests`, `tests/store/settle_test.cpp`, the same hooked store sources) and runs the
settling evidence of 09 §7 end to end (parent task `phase1.8_project-store`). Every case works on
the same content: a 300 KB resource bound to a fill layer and two paint layers whose 2048×2048
sRGB8 planes (2×2 chunks) share one set, stack, channel and UV tile. Recovery is checked as
whole-file equality: per revision the manifest bytes, the SHA-256 of the pixels of every bound
plane and of every named resource, plus the checkpoint and operation rows.

| Case | Checks |
|---|---|
| `interruptions` | one project (a protected checkpoint, 55 fills, a stroke per plane, a save) through, in turn: a child killed in `COMMIT` of a stroke (hot journal, torn file), one killed between the plane rows and the revision row, one killed during `VACUUM INTO` of `compact` and one before its rename, then I/O failures of `VACUUM INTO` and of the rename in process; after each, the file equals its state before the fault and its bytes are unchanged; the killed strokes then commit once each with exact pixels; `compact` keeps every retained state equal and collects the rest; on byte copies, a corrupt resource blob, a corrupt chunk blob, a corrupt older manifest and a corrupt current manifest are each detected and name the affected node, revision or plane while everything else reads exactly; the project itself is unchanged |
| `two_layers` | two paint layers on one channel and tile: reopened, A edited, a stroke on B killed in `COMMIT` and recovered, B edited, reverted to the saved checkpoint, compacted, reopened: each plane reads its own pixels at every checked revision, every retained revision binds two distinct versions whose chunk hashes never overlap |
| `commit_then_die` | a child commits a stroke durably and dies before the acknowledgement: the retry with the original key, arguments and precondition returns the stored outcome without executing, a changed stroke under the key is `idempotency_conflict`; neither creates a revision or a plane version; the same after the current revision advanced and after reopen |
| `pruned_key_replay` | a stroke `k1` pruned by `compact`: replays with its precondition and with none are `outcome_unknown`, not executed, no revision or version; `k2` inside the window returns its stored outcome at a newer revision; the plane holds `k1` exactly once; the same after reopen and after a second (empty) compaction |
| `revert_edit_reopen_compact` | approved (protected) → two strokes → 80 fills → revert → stroke → reopen → compact: every retained state equal byte for byte, the protected checkpoint's chunks written at revision 2 kept, a version only a collapsed revision bound collected; after reopen the protected checkpoint still reverts to its exact pixels |

No GPU is used; the cases run on the CPU lane.

## 8. Raster planes

Paint layers and paint effects hold one authoritative raster plane per channel
(`paint.planes{channel → plane_id}`; the one `paint.plane` of a mask-stack paint effect). Their
content is written by bitmap and projection operations (later phases) through the store-level API,
from inside a transaction's call:

- `CreatePlane(edit, PlaneSpec{node, channel, udim, format, width, height})` allocates the
  `plane_id` from the project counter, sets it on the node and binds it to a new empty version. It
  refuses a node that is not a paint layer or paint effect, a second plane on one channel, a
  channel on a mask-stack plane (or none on a content plane), a UV tile the texture set does not
  have, and a size outside 1..65536.
- `WritePlane(edit, plane_id, image)` stages a whole-plane image (`width × height` texels,
  row-major, `TexelBytes(format)` bytes each in the format's native little-endian components:
  1, 2, 3, 4, 6 or 12) as a new version and rebinds the node. Identical content changes nothing.
- `WriteBitmap(edit, node, channels, sha256)` is the whole-bitmap operation
  (phase4.1_nodes-paint-layers item 2.2, decision 348): the project resource `sha256` becomes the
  content of the plane of each addressed channel of a paint layer or content paint effect (a plane
  on UV tile 1001 is created where the node holds none), at the texture set's resolution and the
  channel's format, as new versions of the one transaction. The bitmap is stored as the plane's
  texels as they are: a PNG or OpenEXR whose size or layout differs from the plane's, a mask-stack
  paint effect and a project outside the Default workflow raise `NotYetSupported` before anything
  is staged (no resampling, conversion or mask plane format is recorded).
- `ReadPlane(project, plane_id)` (a working copy's staged content included), `ReadPlane(revision,
  plane_id)` and `ReadPlaneChunk(revision, plane_id, x, y)` read through the binding of that
  project or revision's manifest; no query ever selects chunks by revision number.

**Rows.** `plane` keeps `set_id`, `stack_id`, `channel` (NULL for a mask-stack plane),
`tile_u`/`tile_v` (UDIM − 1001 = u + 10 v), `format` (the `ChannelFormat` spelling), `width`,
`height`, `chunk_size` (1024) and `created_revision`; nothing is unique beyond `plane_id`, so any
number of planes share one set/stack/channel/tile. A version (`plane_version`) lists every
non-empty chunk in `plane_chunk (version_id, chunk_x, chunk_y, sha256)`: chunk (x, y) covers texels
`[1024 x, 1024 x + 1024) × [1024 y, 1024 y + 1024)` clipped to the plane, its texels are one zstd
blob in `blob` (`mime = application/vnd.uzpainter.plane-chunk`, keyed and deduplicated by the
SHA-256 of the raw texels), and a chunk without a row reads as the empty value, every byte 0.
`chunk_root` is the SHA-256 of the canonical JSON (MANIFEST.md §2) of
`[[chunk_x, chunk_y, "<sha256>"], ...]` sorted by `(chunk_x, chunk_y)`; an empty version's root is
the SHA-256 of `[]`. An edit creates a new version whose rows list every non-empty chunk; blobs are
written only for chunks whose bytes the file does not hold, so an edit of one chunk adds one blob
and copies the other hash rows. Triggers refuse any `UPDATE` of `plane`, `plane_version` and
`plane_chunk` and any chunk row added to a version created at or below `checkpoint('current')`:
a committed version is never modified. Rows may be deleted (compaction, `phase1.6`).

**Bindings.** The paint object of the owning node carries `plane_versions {"<plane_id>":
{"chunk_root": <hex>, "version_id": <n>}}` beside `planes`/`plane`. The document model keeps the
key verbatim (`extra`), so the binding is part of the canonical manifest and its digest: a pixel
edit is a manifest change (and a no-op is not), a revert that copies a manifest copies its
bindings unchanged, and deleting a node drops its bindings. `WritePlaneRows`, the first commit
extension, checks that every paint node binds exactly the planes it holds, each to a version staged
by the transaction for that plane or to a stored version of that plane with the same `chunk_root`
(`conflict` otherwise), then inserts the new plane rows, chunk blobs, versions and chunk rows with
`created_revision` = the committed revision, in the commit's SQLite transaction before the revision
row. Staged versions the committed manifest does not bind are dropped; `Submit` discards what an
earlier call staged. `Create` refuses an initial project that holds planes (no content can be
staged there). A revert must keep `next_id` (a plane id is never handed out twice; `CreatePlane`
reports a stored id as `conflict`).

**Integrity** (`CheckPlaneIntegrity`, on open and in `inspect --verify`): every binding of every
retained manifest is well-formed and names a stored `plane_version` of that `plane_id` with the
bound `chunk_root`; every plane a paint node holds is bound; the chunk rows of every bound version
hash to its `chunk_root` and lie inside the plane; every chunk hash is in `blob` with the chunk's
byte count; the bytes of the chunks the current manifest binds (`standard`) or every retained
manifest binds (`full`) are decompressed and hashed. Each failure is a `CorruptItem` of kind
`plane`, keyed by the `plane_id`, with the owning node and the binding's path, e.g. `plane 12:
plane_version 3 chunk (1,0): corrupt: SHA-256 mismatch: blob … holds bytes that hash to …; bound by
node 5 at texture_sets[0].stacks[0].root_layers[0].paint.plane_versions.12`. `plane` and
`plane_version` rows no retained manifest reaches are listed in `IntegrityReport::collectable` for
`compact`; they are not failures. Reads verify the same rules and raise `CorruptionError`; damaged
bytes are never returned.

**Procedural snapshots** (`snapshots.h`, `05-procedural-content.md` §4, decision 327). A frozen
procedural snapshot is a project-level raster plane. The manifest's top-level `procedural_snapshots`
holds one entry per snapshot, keyed by the SHA-256 of its signature's canonical JSON
(`procedural/seam.h` `SignatureJson`): `{signature, project_uuid, plane, plane_versions}`. The entry
holds its plane as a mask-stack paint object does, and the manifest walk reads the entries beside
the paint objects, so every rule above covers them: the binding and its digest, revert,
compaction, integrity, `inspect` and the bundle. The plane row has no set, stack, channel or UV tile
(0 and NULL). `ProjectStore::RecordSnapshot` stages one from a transaction's call. A second
snapshot of one signature is refused. The commit refuses a plane held by two objects, and an
entry whose key is not its signature's hash or whose `project_uuid` is another project's
(`CheckSnapshots`, `conflict`): a snapshot is never copied into another project. The bundle import
refuses such an entry, and `CheckIntegrity` reports it as a `snapshot` corrupt item. The document
model keeps the key verbatim (`Project::extra`).

## 9. Saving, retention, compaction, revert and the lock

Every commit is already the autosave (§4). The saving vocabulary of 09 §4 sits on top of it.

**Checkpoints** (`save.h`). The `checkpoint` table holds `current` (moved by every commit),
`previous` and named rows `{name, revision, created_at, note, protected}`. `save()`
(`ProjectStore::Save`, facade `ProjectSaveMode.Incremental`) writes a named row for the current
revision (`save-<revision>` unless a name is given) and, when the current revision is not the last
named checkpoint yet, moves `previous` to that checkpoint; then it marks the document
(`Document::MarkCheckpoint`). The last named checkpoint is the highest revision a named row names
(`save()` always names the current revision, which no earlier name exceeds), so `Open` restores
`named_checkpoint` and `previous_checkpoint` from the file. `needs_saving()` is `current ≠` that
revision, exactly (`Document::NeedsSaving`, `ProjectStore::NeedsSaving`). A row flagged
`protected` (an approved baseline, QG-05) is never overwritten: saving under its name, also through
`save_as`, fails with `protected_checkpoint` and changes nothing. `current` and `previous` cannot be
given as names (`conflict`). `SaveMode::full` (`save(Full)`) saves, then compacts.

**Retention** (`compact.h`, owner Q11). The retained revisions are `checkpoint('current')`, the last
named checkpoint (the "current checkpoint" of Q11: what `save()` marked last), `previous`, the last
50 revisions of kind `mutation` and the revision of every protected checkpoint. Until `compact`
runs, collapsed revisions still sit in the file, but a revert is refused for any revision outside
this set, so what can be reverted to does not depend on when compaction ran.

**Compaction** (`ProjectStore::Compact`, also `save(Full)`). The project file is copied to
`<file>.compact`; in one SQLite transaction on the copy (`CollapseAndCollect`): unprotected named
checkpoints other than those naming the last named checkpoint or `previous` are deleted, the
`operation` rows of revisions outside the retained set and those revisions are deleted,
`meta.operation_horizon_revision` rises to the highest collapsed revision (never lowered), `cache`
is emptied, and the rows no remaining manifest reaches are deleted: reachability walks every
retained manifest (plane bindings → `plane_version` → `plane_chunk` → `blob`, the `plane` rows of
bound versions, and every SHA-256 the manifest names, `resources` keys included, for `blob`,
`blob_meta` and `locator`). A chunk first written by a collapsed revision stays while a retained
manifest binds a version that lists it. A retained manifest or binding that does not verify stops
the compaction (`corrupt`): nothing could be collected safely. `VACUUM INTO <file>.vacuum` then
writes the compacted file, the connection closes, `MoveFileExW(…, MOVEFILE_REPLACE_EXISTING |
MOVEFILE_WRITE_THROUGH)` renames it over the project and the connection reopens; the document's
operation horizon is raised (`Document::SetOperationHorizon`). The project file is only read until
the rename, so an interruption at any point leaves it in its previous state: a failure removes the
temporary files and names the step (`compact <file>: VACUUM INTO … failed: …`, `… rename of … failed
…`); after a killed worker the next `Open` removes them. A pruned key is answered from the horizon
(§4): with its original precondition or none, `outcome_unknown`, never a second execution.

**save_as / save_as_copy.** `SaveAs(document, target)` refuses an existing `target` (`exists`), takes
the target's lock, `VACUUM INTO <target>.vacuum` from the open connection (a consistent, closed
copy with `journal_mode = DELETE`), writes `save()`'s checkpoint into that copy, renames it to
`target` (`MoveFileExW` without replace), reopens there and releases the original's lock: the open
project relocates and is saved, the original file is not changed. `SaveAsCopy(target)` does the
same without the checkpoint and without relocating: the project keeps its path, lock and dirty
state. A failure removes `<target>.vacuum` and leaves no `target`; a killed worker's leftover
`<target>.vacuum` is removed by the next `save_as` to that target.

**Revert** (`ProjectStore::Revert(document, request, revision | checkpoint)`, MCP `project_revert`).
A mutation submitted with the caller's request (idempotency key, precondition) whose call replaces
the working copy with the verified manifest of the selected retained revision (an older minor
migrated as `Open` does), keeping the project counter `next_id` at its current value so no node or
plane id is handed out twice. The raster-plane bindings are copied unchanged, so the commit binds
the stored versions (no new plane version); history stays append-only. A revision outside the
retained set or an unknown checkpoint fails the call with `not_retained` and writes nothing.

**Lock sidecar** (`lock.h`, SAV-05). `Create` and `Open` take `<file>.uzp.lock` (the project path
with `.lock` appended), holding `pid=<pid>` and `started=<process creation time>`. The owner keeps
the sidecar open for writing, sharing reads only, while it holds the lock, so the OS decides
ownership: another open is refused with `locked` (naming the recorded pid when it can be read) and
a held sidecar cannot be deleted. The handle is opened delete-on-close, so the OS removes the
sidecar whenever the owner lets go of it: a release, and also a crash, a kill or a console
Ctrl+Break of the owning process (B14 of `parity/reports/phase2/practical-e2e.md`). A sidecar no
process holds open (left by a machine that stopped) is stale whatever it records and is
overwritten; a reader of a held sidecar must share deletion (`ReadLockOwner`). `Close` (and the
store's destructor) closes the connection, which leaves no `-wal`/`-shm`/`-journal` companion
(`journal_mode = DELETE`, re-applied before closing), then closes the sidecar, which removes it; later calls on a closed store
fail with `io`. `save_as` moves the lock with the project. `inspect` reads through `Container` and takes no lock (§10).

## 10. Inspection and the export bundle

Every connection waits up to 10 s (`kBusyTimeoutMs`) for another connection's SQLite file lock,
so a worker committing and a reader inspecting never fail on each other.

**`uzpainter inspect <file.uzp> [--revision N] [--verify]`** (`Inspect`, `UzPainter.exe inspect`)
prints indented JSON: `project` (uuid, portable, created, horizon), `revision` (the described
revision, the current one, kind, name, parent, `manifest_sha256`) and `revisions`, `versions`
(manifest and file `format_version`, `app_version`, `painter_reference`), `profiles`
(`evaluator_profile`, `compat_profile`), `settings`, `mesh`, `texture_sets` (UV tiles, channels
per stack, the layer tree with each node's `bindings.resources` (JSON path and SHA-256) and
`bindings.planes` (plane id, channel, bound `version_id` and `chunk_root`, format, size, UDIM), and
`mesh_maps` with their provenance), `resources` (one row per name: SHA-256, bytes, stored bytes,
MIME, usage, colour space, origin and `storage` = `embedded`, `locator` or `missing`),
`procedural_snapshots` (one row per snapshot entry: signature hash, signature, project uuid,
plane id, bound `version_id` and `chunk_root`, format and size), `checkpoints`, `sizes`
(`file_bytes`, then the parts of the file — `manifests`, `resources`,
`plane_chunks`, `operations`, `cache` — and, listed separately, `external_dependencies`: the
locator targets of a non-portable project with their bytes and the missing count) and
`recipe_digest` (`{available: true, digest}` with the running application's recipe host,
`{available: false, reason}` without one, as in the store's own test executable, or when the dump
fails). `inspect <file.uzp> --recipe [--revision N]` prints the revision's recipe dump instead
(`InspectRecipe`, `src/uzp_core/MANIFEST.md` §8): the JSON `uzpainter.project.dump_recipe()`
returns for that revision. Both open the file read-only (`Container::OpenReadOnly`)
inside one read transaction: no lock sidecar, no GPU, nothing written; a file a killed worker left
with a hot journal is refused (`io`) rather than rolled back by a reader. `--verify` runs
`CheckIntegrity` at `VerifyLevel::full` — every rule of 09 §1: foreign keys, every manifest
against its `manifest_sha256`, operation rows, locators, every resource a stored manifest lists
present in `blob` (or located), the plane rules of §8 with the bytes of every bound chunk,
`quick_check` and the SHA-256 of every blob — on a consistent snapshot (`ReadSnapshot`: SQLite
online backup into a temporary file, the source's read lock held only while the pages are copied),
adds `verify {ok, corrupt, missing, collectable}` and exits 1 when it is not `ok`.

**`uzpainter export-bundle <file.uzp> <dir|file.zip> [--revision N]`** (`ExportBundle`) writes
one revision as files from a snapshot (no lock, no GPU): `manifest.json` (the canonical manifest
byte for byte), `res/<sha256>.<ext>` (resources, original bytes), `meshmaps/<set>_<usage>.<ext>`
(mesh-map resources; a name already taken, ignoring case, falls back to `meshmaps/<sha256>.<ext>`),
`planes/<plane_id>.png|.exr` (PNG for 8/16-bit formats, uncompressed
scanline OpenEXR for half/float formats, texels unmodified; `bundle_codec.h`) and `bundle.json`
(`uzpainter/bundle/1`: uuid, revision, `manifest_sha256`, the resource and plane index with each
plane's row and binding). Everything is verified on the way out. A name ending in `.zip` gives a
ZIP of the same paths (stored entries, ZIP64 when needed). The bundle is written to
`<target>.partial` and renamed when complete.

**Bundle import.** `ProjectStore::Open` of a directory holding `bundle.json` imports it into
`<dir>.uzp` beside it (`ImportBundle`; `exists` when that file exists) and opens that: the same
project uuid, one revision with the bundle's number (`kind = checkpoint`) whose manifest is
`manifest.json` byte for byte (checked against `manifest_sha256` and its canonical form), every
resource embedded (each file checked against its SHA-256), every plane rebuilt with the version id
its manifest binds (`InsertPlaneVersion`) and checked against the bound `chunk_root`, and
`meta.operation_horizon_revision` set to that revision: no operation row comes along, so a retried
key whose precondition is older is `outcome_unknown` (§4). A bundle that does not verify is
refused and leaves no file.

## 11. The size census (owner Q11)

`census.h` instruments the store on the dependency content of a project (09 §3, §7) and writes a
report of numbers and identifiers only (`uzpainter/store-census/1`; the repository guard checks
it, `parity/GUARD.md` §2). Per project, in a work folder: `Create` a portable project embedding
the mesh, the mesh maps bound per texture set and further resources (deduplicated by SHA-256) and
`save()` (**first save**); a fill layer, then N **one-parameter edits** (the layer's BaseColor
opacity; file growth and bytes written per edit as mean, max and total, with the stored manifest
size); a **raster plane** of the first set's resolution (sRGB8) and an **edit** inside chunk
(0, 0) (stored chunk bytes of each); `save()`, close and **reopen** (timed); **compact** (timed,
bytes before and after); the **retained history** (revisions besides the current one, their
manifests, the blobs only they reach and the operation rows); **project bytes** (the compacted
file) and **external dependency bytes** (0: portable). "Bytes written" is the process's write
transfer count (`GetProcessIoCounters`), so the rollback journal counts. The matched `.spp` is
measured by its file size only; the report gives `ratio_to_spp` and whether it is within the 10 %
candidate budget.

`UzPainter.exe store-census --inputs src/store/census_inputs.json --assets-root <Assets3D> --work
<dir> --out parity/reports/phase1/store-census.json` produced the Phase 1 report on tunic v10,
hat v8 and body v5/v6/v6b. The inputs list the dependency files that exist today; what is not
available as files (masks packed into a `.blend`, masks and high-poly meshes removed from `_tmp`,
maps Painter baked internally) is named under `not_measured`, so these ratios cover the measured
dependencies, not the full content; `phase4.1_coverage-body-v6b` completes the census.
