## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase1.3_document-model, phase1.4_store-container-operations

## 2. Implementation
- [x] 2.1 `plane` rows: allocate persistent `plane_id` with set, stack, channel, `tile_u`/`tile_v`, native format, width, height, chunk size and `created_revision`; no uniqueness on set/stack/channel/tile so several planes coexist on one channel and tile
- [x] 2.2 Chunk codec: split a plane into 1024×1024 chunks indexed by `(chunk_x, chunk_y)` inside the plane, store each non-empty chunk losslessly in its native format as a zstd blob keyed by SHA-256, deduplicated through `blob`
- [x] 2.3 `plane_version` creation: list every non-empty chunk, compute `chunk_root` = SHA-256 of the sorted `(chunk_x, chunk_y, sha256)` list, and refuse any write to a committed version
- [x] 2.4 Copy-on-write edit: a new version writes blobs only for changed chunks and copies the hash rows of unchanged chunks; an all-empty chunk is omitted and reads as the plane's empty value
- [x] 2.5 Manifest bindings: bind each raster plane referenced by a node, source or output to `{version_id, chunk_root}` in the revision's manifest, committed in the same transaction as the revision through the container commit path
- [x] 2.6 Read path: resolve `plane_id` → `version_id` through the manifest of the requested revision and assemble chunks, never querying the greatest chunk revision below it
- [x] 2.7 Plane integrity checker (on open and for `inspect --verify`): foreign keys on; binding → existing `plane_version` of that `plane_id`; chunk rows hash to `chunk_root`; every chunk hash present in `blob` with matching bytes; unreachable `plane`/`plane_version` rows listed as collectable; each failure reported with the affected plane and owning node
- [x] 2.8 Store-level plane write API for later bitmap/projection operations and frozen procedural snapshots, plus a test writer that fills planes with deterministic synthetic content

## 3. Tests
- [x] 3.1 Two paint layers with separate planes on the same channel and UV tile: save, reopen, edit one, revert, reopen; each layer's pixels equal their expected values and neither plane aliases nor flattens the other (09 §7)
- [x] 3.2 Copy-on-write test: on a 4×4-chunk plane, an edit touching one chunk writes exactly one new chunk blob, copies 15 hash rows and leaves the previous version byte-identical
- [x] 3.3 Binding-resolution test: after edits at revisions r1 < r2 < r3, reading the plane at r1, r2 and r3 returns exactly the bytes bound by each manifest
- [x] 3.4 Empty-chunk test: a version without a chunk row reads that chunk as the plane's empty value and its `chunk_root` matches the recomputed list
- [x] 3.5 Native-format round trip for every channel format the document model allows in `plane.format`: stored and read back bit-exact
- [x] 3.6 Interruption during a raster-plane commit (kill point between chunk inserts and the revision row): reopening yields the previous revision with identical manifest and pixels and no dangling version bound
- [x] 3.7 Corruption tests: a chunk blob with altered bytes and a `plane_chunk` row altered so it no longer hashes to `chunk_root` are each detected on open and by the integrity checker, naming the plane and owning node

## 4. Acceptance
- [ ] 4.1 Every §3 test green on the hosted CPU lane; results attached to `phase1.8_project-store` as part of its `09-…` §7 evidence

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass
