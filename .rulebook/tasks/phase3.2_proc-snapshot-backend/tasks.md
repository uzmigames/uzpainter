## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase3.1_proc-backend-seam

## 2. Implementation
- [ ] 2.1 Define the snapshot signature with every field of `05-procedural-content.md` §4 and its canonical hash
- [ ] 2.2 Implement `SnapshotBackend.status/canEvaluate/evaluate`: exact signature match only, else `unavailable`; no resampling or extrapolation; a snapshot is migration data only: it never counts as calibration or held-out evidence and never widens an asset's certified editable domain (decision 222)
- [ ] 2.3 Store snapshot rasters as `.uzp` raster planes with `plane_id` and their signatures in the manifest; include them in save/reopen, `inspect` and `export-bundle`
- [ ] 2.4 Refuse copying a snapshot into another project and keep snapshots out of every shipped asset folder
- [ ] 2.5 Implement `uzpainter assets snapshot` recording through Painter's documented export API on a licensed machine

## 3. Tests
- [ ] 3.1 Exact-match test: a recorded snapshot is served byte-equal to the private Painter export it came from
- [ ] 3.2 Signature mismatch tests: changing each signature field in turn (parameter, seed, resolution, colour space, image-input hash, project setting) yields `unavailable`
- [ ] 3.3 Save/reopen keeps snapshots bit-exact; `inspect --verify` passes
- [ ] 3.4 Cross-project copy is refused; the repository guard rejects a snapshot blob

## 4. Acceptance
- [ ] 4.1 Acceptance: exact-signature serving byte-equal; mismatches unavailable; snapshots project-private

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
