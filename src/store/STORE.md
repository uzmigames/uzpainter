# Project store: container, blobs, raster planes and the mutation commit (`src/store/`)

Tasks `phase1.4_store-container-operations` and `phase1.5_store-planes` (children of P1-STORE,
`phase1.8_project-store`).
Implements the container of D8 (decision 010) in `docs/architecture/09-project-file-format.md`
§1, §2, §4 and §5, the durability contract of D1 (`02-runtime-topology.md` §3, §5: the operation
record is committed atomically with its revision; every commit is the autosave) and the
idempotency record of ARC-02. The document model it stores is `src/uzp_core/` (`MANIFEST.md`,
`TRANSACTIONS.md`). The raster planes of §8 implement 09 §1 "Authoritative raster planes" and the
paint planes of `04-layer-stack-and-compositing.md` §1. `save()`, named and protected
checkpoints, retention, revert and `compact` are `phase1.6_store-save-retention`; `uzpainter
inspect` and the census are `phase1.7_store-inspect-census`.

## 1. Layout

| Path | Content |
|---|---|
| `container.h` | `Container` (one SQLite connection), `Statement`, `WriteTransaction`, `StoreError`, zstd `Compress`/`Decompress` |
| `blobs.h` | Content-addressed blobs, `blob_meta` names, non-portable locators, `HashFile` |
| `commit.h` | `CommitMutation`, `WriteResources`, `WriteRevision`, stored operation rows, `DecideStored`, `CommitExtension` |
| `versioning.h` | `FormatVersion`, `VersionPolicy`, `CheckReadable`, `MigrateManifest` |
| `integrity.h` | `CheckIntegrity`, `IntegrityReport`, `CorruptionError`, `NodesBinding` (affected nodes), `ReadManifestText` |
| `planes.h` | Raster planes: plane rows, immutable versions, chunk codec, `chunk_root`, manifest bindings, staging, the commit extension and the read path (§8) |
| `plane_integrity.h` | `CheckPlaneIntegrity`: the plane rules, run by `CheckIntegrity` (§8) |
| `project_store.h` | `ProjectStore`: `Create`, `Open`, `Attach`, `Submit`, `StageResource`, `StageLocator`, `ReadResource`, `CreatePlane`, `WritePlane`, `ReadPlane`, `ReadPlaneChunk` |
| `fault.h` | Test-only fault hooks (§6) |

`zig build uzp-store` builds `uzp_store.lib` from these sources, the SQLite amalgamation
(`thirdparty/sqlite/`, public domain, 3.54.0) and zstd (`thirdparty/zstd/`, BSD-3-Clause branch,
v1.5.7), both vendored with `tools/vendoring/thirdparty.py`; it links `uzp_core.lib` and nothing
else: no render layer, no GPU.

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

`Create(path, state, options)` writes, in one SQLite transaction, the schema, `meta`, the
resources the initial project references, its revision (`kind = checkpoint`) and
`checkpoint('current')`. A failed creation removes the file.

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
5. runs `CheckIntegrity`: `PRAGMA foreign_key_check`, every retained manifest against its
   `manifest_sha256`, every operation row, every locator, the plane rules of §8 (with the bytes of
   the chunks the current manifest binds); with `VerifyLevel::full` also `PRAGMA quick_check`,
   the SHA-256 of every blob and the bytes of every chunk any retained manifest binds.

Corrupt history, blobs and missing dependencies are reported in `Opened::report`, never thrown.
`ReadResource` always verifies: a blob that does not decompress or does not hash to its key
raises `CorruptionError` naming the hash and the nodes of the current manifest that bind it (the
id of the nearest object with an `id`/`uid` and the JSON path, e.g.
`texture_sets[0].stacks[0].root_layers[0].fill.sources.BaseColor.resource.sha256`); its bytes are
never returned. The `DocumentState` leaves `named_checkpoint` and `previous_checkpoint` empty
(phase1.6).

## 6. Fault hooks (test builds only)

`fault.h` exists only when `UZP_STORE_FAULT_HOOKS` is defined, which `build.zig` does for
`uzp-store-tests.exe` alone; `uzp_store.lib` contains none of it (checked by
`tests/store/test_project_store.py`). The hooks work through a SQLite VFS that wraps the
platform VFS: `kill_during_commit` terminates the process right after the first page write to
the database file made by `COMMIT` (journal hot, file torn), `disk_full` fails every write that
would grow the database file with `SQLITE_FULL`, and `kill_after_commit` terminates the process
after `COMMIT` returned, before the commit sink returns. `kill_before_revision_row` terminates the
process inside the commit transaction right after the plane rows were inserted (`AfterPlaneRows`),
before the revision row.

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

No GPU is used; the cases run on the hosted CPU lane.

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
