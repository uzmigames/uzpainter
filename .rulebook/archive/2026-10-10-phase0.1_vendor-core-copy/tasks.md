## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0_owner-decisions

## 2. Implementation
- [x] 2.1 List candidate commits on UzEngine `main` (newest first) by full hash and export each candidate with `git archive <hash>` into a staging folder outside both repositories
- [x] 2.2 Check (a): scan every file of the §2.1 subset in the exported tree for conflict markers
- [x] 2.3 Check (b): compute the include closure from the exported tree through UzEngine's include directories to a fixed point and compare it with the manifest; record any unresolved include outside the listed third-party and Windows SDK headers
- [x] 2.4 Check (d): re-verify every behaviour cited in `13-engine-integration.md` §2.3 and §3.4 at the candidate commit and record the line numbers
- [x] 2.5 Select the newest candidate that passes (a), (b) and (d); record UzEngine's own build/test status at that commit as information only
- [x] 2.6 Copy the §2.1 subset from the exported tree into `thirdparty/uzengine-render-core/` with upstream relative paths, excluding every §2.4 path
- [x] 2.7 Write `LICENSE` (UzEngine's licence at the selected commit) and `ORIGIN.md` (repository, commit hash and date, selection evidence a–d with check (c) to be confirmed by phase0.3_vendor-modifications and phase0.6_toolchain-hardware-slice, import date, importer, re-verified line numbers)
- [x] 2.8 Write `MANIFEST.json` with `{upstream_path, vendored_path, upstream_commit, upstream_blob_sha1, upstream_sha256, vendored_sha256, status: verbatim, modifications: []}` per file
- [x] 2.9 Re-check for an upstream `NOTICE` and per-file licence headers at the selected commit; write the root `NOTICE` entry (vendored UzEngine code, copyright line, selected commit) and reproduce any upstream attribution notice found

## 3. Tests
- [x] 3.1 Byte-equality test: for every manifest entry, `vendored_sha256` equals `upstream_sha256` and `upstream_blob_sha1` equals the blob id in `git ls-tree` of the selected commit
- [x] 3.2 Closure test: rerunning the include-closure computation on the vendored folder yields exactly the manifest's file set
- [x] 3.3 Exclusion test: no file under `thirdparty/uzengine-render-core/` matches a §2.4 path (`asset/importers/**`, `asset/formats/uzmesh_format.*`, `asset/formats/uztexture_format.cpp`, `renderer/**`, `engine/config/**`, `engine/core/cvar.*`, `engine/rhi/dx11/**`, `engine/rhi/metal/**`, `engine/rhi/optimization/**`)
- [x] 3.4 Conflict-marker test over the vendored folder

## 4. Acceptance
- [x] 4.1 Child acceptance (contributes to P0-VENDOR): clean commit selected with recorded evidence; subset copied byte-equal with upstream paths; `LICENSE`, `ORIGIN.md`, `MANIFEST.json` and root `NOTICE` entry written; no denylisted path present

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass
