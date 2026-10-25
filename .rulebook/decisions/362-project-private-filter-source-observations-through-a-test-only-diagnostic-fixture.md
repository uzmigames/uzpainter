# 362. Project-private Filter source observations through a test-only diagnostic fixture

**Status**: proposed
**Date**: 2026-10-25
**Related Tasks**: phase3.1_proc-backend-seam

## Context

Coordinator-review proposal for phase3.1_proc-backend-seam items 2.6/3.2, specifically source-substance-booleans-filter steps 16-18. Decision 361 deliberately preserves prior effect behavior; snapshot metadata /3 belongs to an admitted raster signature. Current Filter get_parameters reads a synthetic reference, resource_id returns its pin, and image_outputs refuses. A filter's content input is the actual layer content at its position (admission.cpp), not an authored substitute raster. Existing expected probe readbacks must never become fixture construction inputs. The owner requested continued coordinated implementation; this is a technical scope proposal, not an owner licensing amendment, parity exception or gate waiver.

## Decision

PROPOSED; no implementation or capture is authorized by this entry until coordinator review accepts it.

1. Scope: FilterEffectNode observations only, initially through a test-only diagnostic fixture/importer. No generator scope, production insertion/binding API, execution backend, output raster, calibration, certification or editable-domain claim. Snapshot schemas /1-/3, signature codecs and stored entries remain byte-compatible and unchanged.

2. Separate closed schema and namespace: use project-private filter-source observations, not procedural_snapshots. Proposed entry body contains schema version, destination project UUID, role='filter', internal provenance pin, a complete observation context, capture provenance and observations. The context fixes the versioned requested resource, authored capture recipe and input hashes, owning stack/effect position and preceding authored content state, texture-set resolution/channel formats, mesh/import identity and evaluation settings. Pin an exact canonical context projection and document every field before implementation; never equate two contexts merely because resource and parameters match. Capture provenance records recorder/envelope identities and paired readback hashes. Observations contain complete typed effective parameters, complete observed ResourceID {url,context,name,version}, and image_outputs in observed order. Missing is not empty. Initially retain decision 361's finite int64/double/string parameter codec; bool/vector/color/object/array observations refuse rather than coerce. Empty output lists are represented if genuinely observed; do not invent an active output or raster mapping.

3. Identity and immutability: hash the canonical closed entry body (excluding its own key), preserving parameter JSON types and signed zero. The destination UUID prevents foreign reuse. An internal pin is an observation identity, not an executable asset-library alias; its precise URI namespace is a coordinator implementation choice documented with the schema. Complete observed URL and parts are captured, never reconstructed. Bind the diagnostic effect to the entry key plus complete procedural reference/context; getter lookup validates current state each time. Same context with conflicting observations is refused, never enriched in place. A new capture creates a new private fixture. Corrupt, missing, foreign, stale, or mismatched observations refuse explicitly; no borrowing or legacy fallback that fabricates an observed value.

4. Capture independence: a bounded own-Painter capture uses only documented public APIs, an explicitly versioned Filter resource and an authored recipe/content. Read actual parameters, identity and image_outputs in paired observations, including save/close/reopen. Capture and importer never read the existing replay expected values. Keep captures/receipts/identities/values private under the existing ownership/lock protocol. Publish only permitted hashes/counts. No source pixels or fake content hash are needed for observation storage; authored input identities describe the observed context and are not an evaluation result.

5. Diagnostic import: test tooling validates the complete receipt, authored inputs, pair equality, destination identity and context before creating a private diagnostic fixture in one transaction. It may create the Filter reference from the validated fresh capture as migration data, never from the old golden. Do not route through SetEffectProcedural with fake Admit/CanEvaluate, relax RequireSupported, or make this observation satisfy evaluator admission. The fixture remains explicitly non-executable; normal product operations and unsupported mutations retain their existing refusals. Save/reopen must preserve and revalidate entry/reference/context. Any later product importer or executable effect route requires a separate reviewed design.

6. Getter boundary: only the exact diagnostic observed Filter enables get_parameters, resource_id and image_outputs for this slice. Reuse decision 361's provenance-only observational ResourceID codec and pre-mutation rejection at import/resolve/search/bind consumers. Original effect behavior stays for legacy entries where explicitly documented; observations must not silently override different references. Resolution and other Filter restrictions (steps 19-24) remain unchanged; no additional getter/setter is inferred from these three observations.

7. Validation sequence: authored schema/store tests first (closed fields/types, signed zero, UUID/key/context mismatch, conflicting duplicate, missing/corrupt/stale, no mutation on refusal, save/reopen); diagnostic importer and observational-ID refusal tests; bounded new capture; strict typed replay of both recordings for steps 16-18 and regression of 19-24. Trace only outputs actually compared; no bookkeeping attribution. Do not promote capabilities or check task-wide 2.6/3.2 in this design/implementation slice. Any later promotion follows decision 112 after exact compared evidence and coordinator review.

## Alternatives Considered

- Reuse fill snapshot /3 without a raster: rejected; breaks admitted signature/output/raster meaning and invents executable support.
- Seed the existing synthetic filter from old replay expected values: rejected; oracle-derived fixture inputs invalidate independent comparison.
- Key only by asset pin and effective parameters: rejected; no evidence that observations are independent of effect/content/settings context.
- Implement full Filter evaluation first: valid later direction, but not required for a bounded non-executable observation diagnostic.

## Consequences

This creates only a proposed technical contract owned by phase3.1_proc-backend-seam, not phase3.2_proc-snapshot-backend. Coordinator must settle the exact canonical context projection and diagnostic schema/URI before acceptance. Implementation can then be split into store/provider/importer and independent public-API capture tooling, with native build/capture ownership serialized. No owner confirmation is needed merely for these reversible technical implementation choices under the standing implementation request. An owner decision would be required to change licensing/distribution policy, waive parity or a gate, or expand approved production cutover scope; this proposal does none. Pilots, G1/G2, amendment, procedural family certification and task-wide acceptance remain open.
