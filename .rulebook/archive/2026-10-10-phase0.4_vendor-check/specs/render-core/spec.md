## ADDED Requirements

### Requirement: Vendored hashes match the manifest and log
The vendoring check MUST recompute the SHA-256 of every vendored file and fail when it differs from `vendored_sha256`, when a `verbatim` file differs from upstream, or when a `modified` file names a modification id absent from `MODIFICATIONS.md`.

#### Scenario: Silent edit detected
Given a verbatim vendored file edited without a log entry
When the vendoring check runs
Then it fails with the hash-drift rule naming that file

### Requirement: Modified files carry their notice
The check MUST fail when a file marked `modified` lacks the Apache-2.0 §4(b) notice naming its modification id, original UzEngine path and commit.

#### Scenario: Missing notice detected
Given a modified file whose notice was removed
When the vendoring check runs
Then it fails with the notice rule naming that file

### Requirement: Folder contents equal the manifest and avoid the denylist
The check SHALL fail on any file under `thirdparty/uzengine-render-core/` other than its metadata files (`LICENSE`, `ORIGIN.md`, `MANIFEST.json`, `MODIFICATIONS.md`) without a manifest entry, on any manifest entry without its file, on any denylisted path (`asset/importers/**`, `asset/formats/uzmesh_format.*`, `asset/formats/uztexture_format.cpp`, `renderer/**`, `engine/config/**`) and on conflict markers.

#### Scenario: Defective mesh-cook file rejected
Given a commit that adds `asset/importers/mesh_importer.cpp` under the vendored folder
When the vendoring check runs
Then it fails with the denylist rule

#### Scenario: Unlisted file rejected
Given a new file under the vendored folder with no manifest entry
When the vendoring check runs
Then it fails with the coverage rule

### Requirement: No build path outside the repository
The check MUST fail when any include or library path used by the build points outside the UzPainter repository, other than the pinned Zig toolchain directories and the Windows SDK.

#### Scenario: Engine include path rejected
Given a build configuration that adds an include path into a UzEngine checkout
When the vendoring check runs
Then it fails with the build-path rule naming the UzEngine path

### Requirement: Runs on every commit
The vendoring check SHALL run in the hosted CPU CI lane on every commit and MUST exit non-zero with a per-rule message on failure.

#### Scenario: Clean tree passes in CI
Given the vendored folder as imported and modified
When CI runs the check on a commit
Then the check exits zero
