## ADDED Requirements

### Requirement: Planes Never Alias
Each authoritative raster plane SHALL have its own persistent `plane_id` referenced by its owning node, source or output in the manifest, and the store MUST keep any number of planes on the same set, stack, channel and UV tile separate, never aliasing or flattening them into a composite.

#### Scenario: Two paint layers on one channel and tile
Given two paint layers whose base-colour planes share texture set, channel and UV tile 1001
When the project is saved, reopened, one layer's plane is edited and the project is reopened again
Then each layer reads back its own pixels, the unedited layer is byte-identical to its original content and no plane holds a composite of both

### Requirement: Immutable Copy-On-Write Versions
A committed `plane_version` MUST NOT be modified; an edit SHALL create a new version that writes blobs only for the chunks it changed, references the unchanged chunks by hash, and records `chunk_root` as the SHA-256 of its sorted `(chunk_x, chunk_y, sha256)` list.

#### Scenario: Edit one chunk of a 4K plane
Given a 4096×4096 plane stored as 16 non-empty 1024×1024 chunks
When an edit changes pixels inside one chunk only
Then the new version adds exactly one chunk blob, copies 15 hash rows, and the previous version still reads back its original bytes

### Requirement: Reads Resolve Manifest Bindings
Reading a plane at a revision SHALL resolve the version bound by that revision's manifest and MUST NOT select chunks by the greatest chunk revision below the requested one.

#### Scenario: Read an older revision after later edits
Given a plane edited at revisions 5, 9 and 12
When the caller reads the plane at revision 9
Then the returned pixels equal exactly the content bound by the revision-9 manifest

### Requirement: Missing Chunks Read As Empty
A version SHALL list every non-empty chunk of its plane, and a chunk without a row MUST read as the plane's empty value.

#### Scenario: Sparse plane
Given a plane version with chunk rows only for chunks (0,0) and (2,1)
When the caller reads chunk (1,1)
Then every texel of that chunk equals the plane's empty value

### Requirement: Plane Integrity Checked On Open
On open and in `inspect --verify` the store SHALL enforce foreign keys and MUST verify that every plane binding of a retained manifest names an existing `plane_version` of that `plane_id` whose chunk rows hash to its `chunk_root`, and that every chunk hash exists in `blob` with matching bytes, reporting each failure with the affected plane and owning node.

#### Scenario: Corrupted chunk blob
Given a saved project in which one chunk blob's bytes were altered on disk
When the project is opened
Then the open reports a SHA-256 mismatch naming the plane and the paint layer that owns it

#### Scenario: Chunk list no longer matches the root
Given a saved project in which a `plane_chunk` row was changed to reference another blob
When `uzpainter inspect --verify` runs on the file
Then it reports a `chunk_root` mismatch for that plane version

### Requirement: Plane Commits Are Atomic
Plane versions, chunk rows and their manifest binding SHALL be committed in the same transaction as the revision, so an interrupted raster-plane commit MUST leave the previous revision's manifest and pixels intact.

#### Scenario: Kill during a raster-plane commit
Given a raster-plane edit whose chunk rows are being inserted
When the worker is killed before the revision row commits
Then reopening the project yields the previous revision with identical manifest and pixels and no new version bound by any manifest
