# 09 — Project file format (`.uzp`)

Implements D8 (`05-resolution.md`) and owner answer Q11 (decision 024): a self-contained portable file; 10 % of the matched `.spp` as the candidate size budget, measured by the census (§3); retention of the current and previous checkpoints plus the last 50 mutation revisions (§4). Owner answer Q6 (decision 020) governs Painter projects: no `.spp` reader (§5). Requirements: SAV-01…05, RES-01…04, NFR-04, NFR-08, QG-05, ARC-02 (`docs/prd.md`).

## 1. Container

A `.uzp` file is a SQLite database (`journal_mode = DELETE` for files at rest; a file is portable only when no `-wal`/`-shm` companion exists, which `close`, `save_as` and `compact` guarantee by checkpointing). SQLite is vendored as the public-domain amalgamation; zstd (BSD) compresses every payload independently. The container is an implementation detail: the **public schema is the JSON manifest** (`03-project-model.md` §1), which `uzpainter inspect` prints and `export-bundle` writes as ZIP + JSON + PNG for humans and tools that prefer files.

```sql
CREATE TABLE meta      (key TEXT PRIMARY KEY, value TEXT);             -- format_version, app_version, evaluator_profile, compat_profile, project_uuid, created, painter_reference
CREATE TABLE revision  (revision INTEGER PRIMARY KEY, parent INTEGER, created_at TEXT, kind TEXT /* mutation|checkpoint|autosave */, name TEXT, manifest BLOB /* zstd(canonical JSON) */, manifest_sha256 TEXT);
CREATE TABLE blob      (sha256 TEXT PRIMARY KEY, mime TEXT, size INTEGER, zstd_size INTEGER, data BLOB /* zstd */);
CREATE TABLE blob_meta (sha256 TEXT, name TEXT, usage TEXT, origin TEXT, color_space TEXT, imported_at TEXT, PRIMARY KEY (sha256, name));
CREATE TABLE plane     (plane_id INTEGER PRIMARY KEY, set_id INTEGER, stack_id INTEGER, channel TEXT, tile_u INTEGER, tile_v INTEGER,
                        format TEXT, width INTEGER, height INTEGER, chunk_size INTEGER, created_revision INTEGER);   -- owner node/source/output named in the manifest
CREATE TABLE plane_chunk(plane_id INTEGER REFERENCES plane, revision INTEGER, chunk_x INTEGER, chunk_y INTEGER, sha256 TEXT REFERENCES blob,
                        PRIMARY KEY (plane_id, revision, chunk_x, chunk_y));
CREATE TABLE operation (idempotency_key TEXT PRIMARY KEY, project_uuid TEXT, request_hash TEXT, outcome BLOB /* zstd(canonical JSON result) */,
                        committed_revision INTEGER REFERENCES revision, created_at TEXT);
CREATE TABLE cache     (key TEXT PRIMARY KEY, revision INTEGER, evaluator_profile TEXT, sha256 TEXT);   -- regenerable; dropped by `compact`
CREATE TABLE checkpoint(name TEXT PRIMARY KEY, revision INTEGER, created_at TEXT, note TEXT, protected INTEGER /* QG-05 */);   -- includes 'current' and 'previous'
```

Node ids live inside the manifest; bindings are part of the manifest (node → sha256 + alias), so `blob` is referenced only by hash.

**Authoritative raster planes** — paint-layer content written by bitmap and projection operations (brush strokes are out of scope, owner Q5) and frozen procedural snapshots embedded per project — each have a persistent `plane_id`, referenced explicitly by the owning node, source or output in the manifest. The `plane` row keeps the plane's UV-tile identity and native format; any number of planes may belong to the same set/stack/channel/tile, so two paint layers on one channel and tile never alias and are never flattened into a composite. Pixels are stored as chunks keyed by `(plane_id, revision, chunk_x, chunk_y)`: chunk coordinates index the evaluator's 1024×1024 tiles inside the plane (`04-layer-stack-and-compositing.md` §2) and are distinct from UV-tile coordinates. Chunks are copy-on-write: a revision writes only the chunks it changed; a plane at revision R reads, per chunk, the row with the greatest revision ≤ R, and a missing chunk reads as the plane's empty value. Integrity rules, checked on open and by `uzpainter inspect --verify`: foreign keys are enforced (`PRAGMA foreign_keys = ON`); every `plane_id` named by a retained manifest exists; every `plane` row is referenced by a retained manifest or removed by `compact`; every chunk hash exists in `blob`.

## 2. What is stored

| Stored | Not stored (re-derived) |
|---|---|
| Canonical manifest per revision (kilobytes to a few hundred KB) | Decoded rasters of imported resources |
| Original resource bytes once (PNG/EXR/HDR/OBJ/FBX/glTF as imported), deduplicated by SHA-256 | Texturing-mesh derived data (tangents, UV raster) |
| Baked mesh maps at native precision (R16/RGB16/R32F) with provenance | Evaluated channel tiles (optional `cache`, never required) |
| Authoritative planes | Mip chains, cooked `.uztexture` derivatives |
| Display state, shader parameters, cameras, export defaults, baking settings | Window/UI state |
| Procedural asset versions and frozen-snapshot signatures | — |

Portable mode (default) embeds every dependency, including high-poly meshes and HDRIs referenced by the project; an explicitly non-portable project may keep `{path, sha256}` locators and reports missing dependencies on open. The report of `inspect` lists project-file bytes and external dependency bytes separately.

## 3. Compactness

Compactness is measured from file sizes and dependency inventories obtained through permitted public APIs and filesystem metadata. No assumption about Painter's internal project representation is used. UzPainter stores original dependencies once, authoritative raster state and retained manifests, with regenerable caches optional. Compare matched content and retained-history policies after the reference application's documented compact-save operation; report project bytes plus external dependencies on both sides.

The only facts recorded about the `.spp` baseline are public or externally observable: the files carry the HDF5 file signature, and the three body project files measure 879,248,615, 1,087,438,533 and 1,190,431,812 bytes (`00-Corpo-v5/v6/v6b.spp`; `docs/analysis/technology-options/03-project-container-format.md`, HDF5 row). The **census** (Phase 1 instrumentation on tunic v10, hat v8 and the three body versions) measures lossless dependency bytes + manifests + the history retained under §4 against a compacted `.spp` of the same content, with linked bytes counted on both sides. **Budget (owner Q11):** 10 % of the matched `.spp` is the candidate budget the census is measured against; the census report states the ratio per project, and the budget becomes a release gate once the owner confirms it with the census in hand.

## 4. Saving semantics

| Operation | Behaviour |
|---|---|
| Every committed mutation | One SQLite transaction: insert new blobs and plane chunks, insert a `revision` row (`kind = mutation`), insert the request's `operation` row, update `checkpoint('current')`. Cost is proportional to the change, so the file at rest always holds the last committed revision (this replaces a separate autosave). |
| `save()` (facade `ProjectSaveMode.Incremental`) | Marks the current revision as a named checkpoint; moves `previous`. |
| `save(Full)` / `compact` | Checkpoint, drop `cache`, garbage-collect blobs, plane chunks, planes and `operation` rows unreferenced by retained revisions, `VACUUM INTO` a temporary file, atomic rename. Painter's "Save and compact" equivalent. |
| `save_as(path)` | `VACUUM INTO` the new path (closed, portable), then the project relocates. |
| `save_as_copy(path)` | `VACUUM INTO` the copy; the project stays where it was and keeps its dirty state (Painter semantics). |
| Retention (owner Q11) | The `current` and `previous` checkpoints, the last 50 mutation revisions and every checkpoint flagged `protected`. `compact` collapses older mutation revisions and older unprotected named checkpoints. An approved checkpoint flagged `protected` cannot be collapsed or overwritten (SAV-02, QG-05). |
| Revert | Open any retained revision as the new `current` (a new revision pointing to the old manifest; history is append-only). |
| Dirty flag | `needs_saving()` = `current` revision ≠ last named checkpoint (exact, SAV-01). |
| Lock | A `.uzp.lock` sidecar holds the owning worker pid; stale locks are detected by pid liveness; `close` removes it (SAV-05). |

**Idempotency record (ARC-02).** Each document transaction persists `{project_uuid, idempotency_key, request_hash, outcome, committed_revision}` in `operation`, atomically with its revision. Key scope: one project (`project_uuid`); `request_hash` is the SHA-256 of the canonical tool name and arguments. A retry with a known key and the same `request_hash` returns the stored outcome without mutating; the same key with a different `request_hash` is rejected (`idempotency_conflict`). After a worker restart the supervisor reconciles its ledger (`02-runtime-topology.md` §3) from the `operation` rows newer than the last revision it acknowledged, before admitting any retry; an unresolved outcome is never treated as a new mutation. A failed mutation commits nothing and writes no row, so its retry runs against unchanged state. Retention: rows are kept as long as the revisions they name (at least the Q11 window); `compact` records the pruning horizon in `meta.operation_horizon_revision`, and a retry whose key is unknown and whose `expected_revision` is older than that horizon is answered `outcome_unknown` with the current revision, never executed. The supervisor ledger stays a control-plane record, not a second editable document.

Interruption: SQLite's rollback journal guarantees the file is either the previous or the new state (`https://www.sqlite.org/atomiccommit.html`). Phase 1 fault injection (kill during commit, disk full, corrupt a blob vs the manifest) verifies the behaviour and the error messages; corruption of a blob is detected by `sha256` and reported with the affected nodes.

## 5. Versioning

`meta.format_version` is semver. A reader refuses a newer major with an explicit error, migrates older minors in memory and writes the migrated manifest only on the next commit (the original file is left intact until then). Unknown manifest keys are preserved verbatim. `evaluator_profile`, `compat_profile` and `app_version` travel with every revision so an old project can be re-evaluated with the evaluator it was authored with.

**Painter projects (owner Q6, decision 020).** UzPainter has no `.spp` reader and never opens one. A Painter project is migrated by rebuilding it: while Painter is installed, its state is read through Painter's documented Python API and replayed as UzPainter operations into a new `.uzp`; the migration is accepted when the exports are equal (`03-project-model.md` §7). The readback is private per-project migration data, never shipped or published.

## 6. Inspection

- `uzpainter inspect <file.uzp> [--revision N]` prints: format and app versions, profiles, project settings, texture sets/channels, layer tree with bindings, resource table (name, hash, bytes, usage), mesh maps with provenance, checkpoints, sizes (file, blobs, cache, external dependencies), recipe digest. No GPU, no project lock.
- `uzpainter export-bundle <file.uzp> <dir|zip>` writes `manifest.json`, `res/<sha256>.<ext>`, `meshmaps/`, `planes/` (PNG/EXR) for archive tools; the bundle is also importable (`project.open` accepts a bundle directory).
- MCP resources `uzpainter://project/manifest`, `uzpainter://project/recipe`, `uzpainter://project/resources` expose the same data (`11-mcp-server.md`).

## 7. Settling evidence (Phase 1, node P1-STORE)

Instrument on tunic, hat and body content: first save, repeated one-parameter edits, raster-plane edit, reopen time, bytes written per edit, compaction time, retained-history size; inject interruption during commit and `VACUUM INTO`; corrupt a blob and the manifest separately; verify identical manifests and pixels after recovery. Save, reopen, edit and recover two paint layers with separate planes on the same channel and tile, checking that neither aliases nor flattens the other. Kill the worker after the durable commit and before the supervisor's acknowledgement, then retry the same request (stored outcome, no second revision) and a changed request with the same key (`idempotency_conflict`). The census for Q11 is produced by the same instrumentation.
