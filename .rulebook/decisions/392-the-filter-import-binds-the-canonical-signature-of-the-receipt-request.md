# 392. The Filter import binds the canonical signature of the receipt's request

**Status**: accepted
**Date**: 2026-11-02
**Related Tasks**: phase3.1_proc-backend-seam

## Context

On 2026-11-02 the prepared import of the admitted Filter observation into the original private project H (`assets import-filter-observation`, request and preflight of 2026-10-26) refused with `TARGET_CONTEXT_UNREPRESENTABLE` / `DESTINATION_HOST_SNAPSHOT`. H was unchanged.

The cause is in the importer, not in H or the request:

- The snapshot bridge writes the receipt's `signature.params` as observed (`"params": source["parameters"]`), so a parameter Painter reports as a float keeps its type even when integral (`15.0`, `0.0`).
- `assets snapshot` parses that signature with `RequestFromSignature` and stores `SignatureJson(request)`. Its `ParamJson` writes an integral finite double as an integer. The entry key is `SignatureHash(request)`, the hash of that canonical form.
- Two importer guards compared the receipt's raw signature, typed, with the stored entry's signature: `ExpectedDestination` step 3 (`DESTINATION_HOST_SNAPSHOT`) and `VerifyHostCapture` (`HOST_SOURCE_STATE_MISMATCH`). Any real receipt with an integral-double parameter therefore failed. H's host receipt has three such parameters. Its raw signature hashes to another key than the one the store holds, while the canonical form of its request hashes to exactly the stored key.
- Every authored fixture wrote the receipt signature as `SignatureJson(request)`, and the destination fixture deliberately used only an integer and a non-integral double. So the bridge's real form was never tested.

## Decision

1. Both guards compare the stored entry's signature with `SignatureJson(host.Request())`: the canonical signature of the request the receipt names, which is exactly what `assets snapshot` stored. Lookup stays by `SignatureHash(host.Request())`. `ValidatedHostArtifacts::Signature()` still returns the receipt's raw signature as recorded.
2. Nothing else changes: the seed check against the observed `$randomseed`, typed `/3` metadata equality, the plane census, raster hash, project UUID, revision, starting shape and every J1-J4 binding. A stored signature that is not the canonical form of the receipt's request still refuses.
3. Regression tests reproduce H's shape with authored values: a receipt in the bridge's form (an integral double kept), checked to differ typed from the stored signature. `ExpectedDestination` and `VerifyHostCapture` accept it. A stored signature with the same key but a parameter changed back to a double still refuses: `DESTINATION_HOST_SNAPSHOT` in `ExpectedDestination`, `HOST_SOURCE_STATE_MISMATCH` in `VerifyHostCapture`.

## Consequences

The import of the admitted observation into H can proceed under the existing contract (`docs/filter-observations-v2.md`), and the strict 16-24 replay of item 2.6j follows it. Destination checks go from 66 to 69 and transaction checks from 97 to 99. Four 9router models reviewed the frozen diff; their verdicts are recorded in the task notes.
