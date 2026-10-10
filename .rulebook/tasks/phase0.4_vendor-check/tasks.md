## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase0_owner-decisions, phase0.1_vendor-core-copy, phase0.3_vendor-modifications

## 2. Implementation
- [ ] 2.1 Manifest reader: load `MANIFEST.json` and the ids of `MODIFICATIONS.md`; report malformed entries
- [ ] 2.2 Hash rule: recompute SHA-256 per file; fail on drift from `vendored_sha256`, on a `verbatim` entry whose vendored and upstream hashes differ, and on a `modified` entry whose ids are absent from the log
- [ ] 2.3 Notice rule: fail on a `modified` file whose header lacks the §4(b) notice with its id, original path and commit
- [ ] 2.4 Coverage rule: fail on a file under `thirdparty/uzengine-render-core/` without a manifest entry (metadata files `LICENSE`, `ORIGIN.md`, `MANIFEST.json`, `MODIFICATIONS.md` excepted) and on a manifest entry without its file
- [ ] 2.5 Denylist rule: fail on any path matching `asset/importers/**`, `asset/formats/uzmesh_format.*`, `asset/formats/uztexture_format.cpp`, `renderer/**`, `engine/config/**`
- [ ] 2.6 Conflict-marker rule over every vendored file
- [ ] 2.7 Build-path rule: collect include and library paths from the build's verbose compiler/linker invocations; fail on any path outside the repository other than the pinned Zig toolchain directories and the Windows SDK, naming any UzEngine path
- [ ] 2.8 Wire the check into the hosted CPU CI lane on every commit with a per-rule failure message and non-zero exit

## 3. Tests
- [ ] 3.1 Positive test: the check passes on the imported and modified folder
- [ ] 3.2 Negative fixtures, one per rule, each failing with that rule's message: an edited verbatim file, a modified file without its notice, a modified entry with an unknown id, an extra unlisted file, a missing listed file, a file under `asset/importers/`, a file under `renderer/`, `engine/config/config.h`, a conflict marker, and an include path pointing into a UzEngine checkout

## 4. Acceptance
- [ ] 4.1 Child acceptance (contributes to P0-VENDOR): the vendoring check is green on the vendored folder, red on every negative fixture with the right rule, and runs in CI on every commit

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
