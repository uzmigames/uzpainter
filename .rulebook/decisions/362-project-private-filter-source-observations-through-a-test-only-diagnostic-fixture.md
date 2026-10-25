# 362. Project-private Filter source observations through a test-only diagnostic fixture

**Status**: accepted
**Date**: 2026-10-25
**Related Tasks**: phase3.1_proc-backend-seam

## Context

Coordinator-reviewed contract for phase3.1_proc-backend-seam items 2.6/3.2, specifically source-substance-booleans-filter steps 16-18. Decision 361 deliberately preserves prior effect behavior; snapshot metadata /3 belongs to an admitted raster signature. Current Filter get_parameters reads a synthetic reference, resource_id returns its pin, and image_outputs refuses. A filter's content input is the actual layer content at its position (admission.cpp), not an authored substitute raster. Existing expected probe readbacks must never become fixture construction inputs. The owner requested continued coordinated implementation; this is a technical scope decision, not an owner licensing amendment, parity exception or gate waiver.

## Decision

Accepted by the coordinator after control and Claude review. Item 2.6f is complete; design and implementation of 2.6g may proceed under the next scoped brief. Capture remains gated by passing authored store/importer tests and specific coordinator authorization.

1. Scope: FilterEffectNode observations only, initially through a test-only diagnostic fixture/importer. No generator scope, production insertion/binding API, execution backend, output raster, calibration, certification or editable-domain claim. Snapshot schemas /1-/3, signature codecs and stored entries remain byte-compatible and unchanged.

2. Separate closed schema and namespace: use project-private filter-source observations, not procedural_snapshots. The entry body contains schema version, destination project UUID, role='filter', internal provenance pin, a complete observation context, capture provenance and observations. The context fixes the current descriptor-backed references, owning stack/effect position and preceding authored content state, texture-set resolution/channel formats, mesh/import identity and evaluation settings through the projection below. Authored capture recipe and input hashes belong to capture provenance, not current-state context. Use the exact canonical context projection below; never equate two contexts merely because resource and parameters match. Capture provenance records recorder/envelope identities and paired readback hashes. Observations contain complete typed effective parameters, complete observed ResourceID {url,context,name,version}, and image_outputs in observed order. Missing is not empty. Initially retain decision 361's finite int64/double/string parameter codec; bool/vector/color/object/array observations refuse rather than coerce. Empty output lists are represented if genuinely observed; do not invent an active output or raster mapping.

3. Identity and immutability: hash the canonical closed entry body (excluding its own key), preserving parameter JSON types and signed zero. The destination UUID prevents foreign reuse. An internal pin is an observation identity, not an executable asset-library alias; its reserved URI namespace is specified below. Complete observed URL and parts are captured, never reconstructed. Bind the diagnostic effect to the entry key plus complete procedural reference/context; getter lookup validates current state each time. Same context with conflicting observations is refused, never enriched in place. A new capture creates a new private fixture. Corrupt, missing, foreign, stale, or mismatched observations refuse explicitly; no borrowing or legacy fallback that fabricates an observed value.

4. Capture independence: a bounded own-Painter capture uses only documented public APIs, an explicitly versioned Filter resource and an authored recipe/content. Read actual parameters, identity and image_outputs in paired observations, including save/close/reopen. Capture and importer never read the existing replay expected values. Keep captures/receipts/identities/values private under the existing ownership/lock protocol. Publish only permitted hashes/counts. No source pixels or fake content hash are needed for observation storage; authored input identities describe the observed context and are not an evaluation result.

5. Diagnostic import: test tooling validates the complete receipt, authored inputs, pair equality, destination identity and context before creating a private diagnostic fixture in one transaction. It may create the Filter reference from the validated fresh capture as migration data, never from the old golden. Do not route through SetEffectProcedural with fake Admit/CanEvaluate, relax RequireSupported, or make this observation satisfy evaluator admission. The fixture remains explicitly non-executable; normal product operations and unsupported mutations retain their existing refusals. Save/reopen preserves observations and validates structural integrity; getters revalidate current references and context, which may be stale. Any later product importer or executable effect route requires a separate reviewed design.

6. Getter boundary: only the exact diagnostic observed Filter enables get_parameters, resource_id and image_outputs for this slice. Reuse decision 361's provenance-only observational ResourceID codec and pre-mutation rejection at import/resolve/search/bind consumers. Original effect behavior stays for legacy entries where explicitly documented; observations must not silently override different references. Resolution and other Filter restrictions (steps 19-24) remain unchanged; no additional getter/setter is inferred from these three observations.

7. Validation sequence: authored schema/store tests first (closed fields/types, signed zero, UUID/key/context mismatch, conflicting duplicate, missing/corrupt/stale, no mutation on refusal, save/reopen); diagnostic importer and observational-ID refusal tests; bounded new capture; strict typed replay of both recordings for steps 16-18 and regression of 19-24. Trace only outputs actually compared; no bookkeeping attribution. Do not promote capabilities or check task-wide 2.6/3.2 in this design/implementation slice. Any later promotion follows decision 112 after exact compared evidence and coordinator review.

## Reviewed Constraints

These accepted constraints incorporate coordinator, control and Claude review.
The operational contract below fixes the context, schema and reserved URI.
Implementation remains scoped to the authorized 2.6g brief; capture requires the
separate prerequisites and coordinator authorization stated above.
Capture recipe and input provenance are separate from current-state context.

- Separate the current-state context from capture provenance. Every context field used
  for lookup must be recomputable from the current UzPainter project and its authoritative
  stores. Recorder/envelope/recipe/input/readback hashes belong to capture provenance;
  a stored capture claim is not evidence that the current project still matches it.
- Bind the complete procedural reference, not only its asset pin, together with the
  destination binding and entry key. Check the authoritative project's UUID from its
  store/open-project identity; a UUID copied into observation JSON cannot authenticate
  that identity. Entry-key canonicalization preserves typed parameters and signed zero.
- An observed facade handle retains a lease identifying the OpenProject instance,
  authoritative project UUID, node UID and observation entry key. Use a session
  generation or OpenProject identity captured at handle
  creation and preserved by the facade; UUID and node UID alone do not suffice.
  Resolve all getter inputs against one consistent snapshot, then validate the complete binding and
  current context before returning an observation. Do not combine checks from one
  revision with values from another. A pre-close handle refuses after reopen even
  when the UUID and node UID recur; fresh handles may revalidate persisted observations.
- Missing observations and explicitly empty observations remain distinct. A corrupt
  observation or binding refuses; it must not fall back to a synthetic or legacy
  reference. A legitimately legacy entry follows only its separately documented path.
- Observed setters first validate documented public argument types, then refuse before
  mutation, including no-op requests. Preserve the established errors and priorities
  for steps 19-24. Undo within the same OpenProject may restore access only when the
  retained lease, complete reference, entry key and recomputed context all match again.

### Operational Contract: Context

Hashing `ProjectToJson` after removing the observation namespace and its binding
pointers is not sufficient by itself: that projection does not establish all
authoritative raster-plane contents, versions or resource dependencies. Removing
volatile fields also requires an explicit reviewed list, not a general exclusion of
unknown extras. The selected subset and verified mesh census below close this gap within V1 only.

The coordinator selects the strict no-plane subset for V1. The broader
inventory alternative is deferred, not silently approximated:

1. **Strict no-plane schema subset.** Define a closed, validated subset of project
   state whose preceding content, sources and resources can all be reconstructed from
   the canonical project projection and independently verified authored inputs. Reject
   raster planes, snapshot-backed fills and any resource dependency outside that
   subset before import or lookup. This reduces implementation scope, but excludes
   the current snapshot-backed-fill fixture. It therefore cannot complete that fixture's
   steps 16-18; a different independently authored capture would be a separate control,
   not evidence for the excluded context.
2. **Full authoritative plane/resource inventory.** Extend the current-state context
   with an explicitly enumerated dependency inventory from the same consistent
   snapshot: plane IDs, versions, dimensions, formats, content hashes and verified
   available bytes, plus resource identities and verified content hashes for every
   dependency reachable by the admitted context. Specify which authoritative store
   supplies each field, how completeness is checked, and how save/reopen and undo
   preserve or invalidate it. Missing bytes or an unenumerated dependency refuse.
   This can retain the current snapshot-backed-fill context, but needs a reviewed
   snapshot/store interface and completeness checks before any importer or capture.

Neither alternative permits replacing preceding content with a uniform or fallback
source, inventing a raster/hash, or treating capture provenance as current-state proof.
For the selected subset, all `store::ManifestPlaneReferences` and plane bindings must be empty;
procedural snapshots must be absent or validly empty. Admit exactly one authored
host Fill and one Filter, without masks, instances, anchors, bitmaps,
external inputs or preset references. The host Fill has `source_mode=Split`, `sources` exactly
`{host_channel: ProceduralSource}` and `active_channels` exactly `{host_channel}`;
`mono_source` and `material_source` are absent. `host_channel` is a canonical core
channel name. The host's original procedural content and
parameters are represented by an immutable internal descriptor, not a replacement
uniform or evaluated raster. Host getters refuse; only the three Filter getters
are candidates for observation readback. V1 permits only the mesh resource;
environment, LUT, mesh-map and every other external graph-resource reference must
be absent. The resource table contains only that mesh resource, with bytes read
through `store.ReadResource` and exact metadata MIME, size and hash verification.
Additional resource records, unresolved locators or references outside the mesh
refuse. Check absence explicitly; omission from a census never means absence.
Mesh import report, settings and authored project content remain in the project
JSON context. V1 does not introduce a generic resource-census adapter framework.

The context is the canonical current `ProjectToJson` with only the top-level
`filter_source_observations` namespace removed, plus the authoritative store UUID
and verified resource census. Preserve all other fields and unknown extras;
conservative invalidation is preferable to an unreviewed volatile-field exclusion.
The complete current references retain their internal descriptor pins in this
projection. Descriptor hashes do not include this context or its fingerprint, so
the construction has no hash cycle. Import constructs the prospective context
from the same transaction state that will be committed; getters recompute it from
one consistent current snapshot and verify its resource dependencies.
The integral projection retains `app_version`, `painter_reference` and `next_id`.
An upgrade or otherwise irrelevant state change may therefore make observations
stale; this conservative invalidation is intentional.

Structural namespace integrity and operational context matching are separate.
Schema, hashes, authoritative UUID and internal descriptor/entry links are integrity requirements;
an otherwise permitted upstream edit may leave an intact immutable observation
stale. Internally intact bindings may survive node deletion or source changes;
current node existence and reference equality are operational checks, not grounds
to rewrite an immutable observation. Preserve that record and permit saving the stale state; do not block every
unrelated edit or repair observations to match. Import requires a current-context
match before commit. Reopen checks structural integrity, while each fresh getter
revalidates the current context and refuses until it matches again. Undo may
restore the match under the lease rules above.

The control must be a fresh, independently authored capture. It cannot replace
the old snapshot-backed fixture. Comparison claims for the old steps 16-18 require
demonstrated compatibility of authored/captured contexts and versions, followed
by strict comparison against those old outputs themselves. A new capture and its
own paired replay do not establish that compatibility or close the old steps;
Version drift remains an explicit difference. Acceptance closes design item 2.6f
only; implementation, capture and compared replay remain open.

### Operational Contract: Reserved References

`core::Validate` checks `ProceduralRef.asset` through `CheckAsset` and `ParseAssetUrl`,
which accepts only `uzasset://family/id@version`. An original Painter `resource://`
identity or a proposed `uzobs` URI cannot occupy that field under the current model.
A test-only builder accepting a syntactically valid UzPainter pin does not establish
that it represents the original observed identity. The selected representation uses
`uzasset://observation/<descriptor-sha256>@1`, a reserved family whose only meaning
is immutable provenance. Host and Filter descriptors have independent hashes;
neither is an executable alias or the original observed ResourceID. Original
ResourceID fields remain private inside each descriptor. An explicit observed-ref
model variant is deferred.

The family discriminant is recognized independently of a registry or successful
descriptor lookup. Execution rejects the entire `observation` family, for every ID
and version; observation getters accept only a matching 64-hex descriptor ID at
version 1. Reject the family at library registration, alias creation and Resolve;
seam Select and admission; SnapshotBackend Add, Load, Stored, Metadata and Evaluate;
and `HlslBackend::CandidateRefusal`, `Refusal` and `JointRefusal`, plus direct
EvaluateCandidate and EvaluateReference.
At the store boundary, `store/snapshots.cpp` SnapshotProblem and StageSnapshot
must also reject the family before AllocateId, StageVersion or any plane write.
This covers direct RecordSnapshot and CheckSnapshots/integrity paths, not merely
backend dispatch. Reject missing or corrupt observation bindings before
legacy getter dispatch, including after duplication or bundle import. Syntactic
asset validity never grants execution, legacy behavior or observation access.
Every preview, evaluation, export or bake path touching the reserved host_channel
must refuse. The fixture is non-executable; refusal tests must exercise these
boundaries rather than treating successful observation getters as render support.

### Closed Schema

This replaces the earlier `DECISION_362_SCHEMA_DRAFT` proposal's incompatible
`uzobs` pin and original-URL-in-`ProceduralRef.asset` assumptions. Names below are
the accepted closed fields; unknown members or wrong types refuse. All example
identities, hashes and values are placeholders, not Painter records.

- Top-level namespace `filter_source_observations` has exactly `schema`,
  `descriptors`, `entries`, `host_bindings`, `bindings`; schema is
  `uzpainter/filter-source-observations/1`. Maps use descriptor hashes, entry
  hashes, host UIDs and Filter UIDs respectively. `host_bindings` maps a host UID
  to exactly `{channel, descriptor}`, containing the canonical core channel name
  and host descriptor hash; `bindings` maps a Filter UID to its entry hash.
- A descriptor has exactly `schema`, `role`, `resource_id`, `parameters`;
  schema `uzpainter/filter-observation-descriptor/1`, role `host` or `filter`.
  `resource_id` has exactly `url`, `context`, `name`, `version`, each a nonempty
  string, using the decision361 codec without reconstructing any part. `parameters` uses the
  decision361 int64/finite-double/string codec. Its key is the typed canonical
  body hash. Its own pin/key, project context, context hash and entry key are
  excluded. Derive descriptor hashes first, then their pins, then the context
  containing final references, and finally the entry hash; no stage feeds itself.
- An entry has exactly `schema`, `project_uuid`, `role`, `host_descriptor`,
  `filter_descriptor`, `binding`, `context`, `context_sha256`, `capture`,
  `observations`; schema `uzpainter/filter-source-observation/1`, role `filter`.
  Descriptor fields contain hashes of the two closed descriptors. `project_uuid`
  must match the authoritative store UUID, never merely another JSON field.
- `binding` has exactly `texture_set`, `stack`, `host_uid`, `filter_uid`,
  `node_stack`, `effect_index`, `host_channel`, `host_reference`, `filter_reference`.
  `host_channel` is required and names the canonical core channel; it must agree
  with the host binding and the sole active Split source.
  `node_stack` is `Content`. References are complete canonical core ProceduralRef
  serializations, including every stored parameter, output mapping and override;
  the reviewed core serialization defines their fields. Pins must match their
  respective descriptors. Position, UIDs and both complete references must match
  the current snapshot. A partial asset/parameter comparison is insufficient.
- `context` has exactly `schema`, `project`, `store_uuid`, `resources`;
  schema `uzpainter/filter-observation-context/1`. `project` is the projection
  specified above. `resources` is a canonically ordered complete census of records
  with exactly `binding_path`, `kind`, `identity`, `mime`, `sha256`, `size_bytes`.
  Each record identifies an authoritative current dependency, not a capture claim;
  V1 has exactly one record, kind `mesh`, bound to the project's mesh resource.
  `binding_path` is `/mesh/resource`, `identity` is `project.mesh.resource`,
  `sha256` equals that identity, and `size_bytes` is the byte-array length.
  `store.ReadResource` supplies bytes; recompute SHA-256 and size, then compare
  them and `mime` with resource metadata from the same snapshot. ReadResource
  does not establish MIME by inspecting the bytes. Duplicate paths, additional table resources,
  unresolved locators, incomplete inventory or any external graph dependency
  other than this mesh refuse. Environment, LUT and mesh-map references must be
  absent, not ignored. No other resource kind or adapter is admitted in V1.
- `capture` has exactly `recorder`, `envelope_id`, `painter_build_id`,
  `recipe_sha256`, `resource_query`, `authored_inputs`, `receipts`.
  Authored-input records contain `input_id`, `sha256`; receipt records contain
  `condition`, `sha256`, with paired `same_session` and `after_save_reopen`.
  These are private provenance, never recomputed context substitutes.
- `observations` permits only `parameters`, `resource_id`, `image_outputs`.
  Absence means unobserved; empty maps/lists mean observed empty. Each getter
  requires its own complete observation. Parameters and ResourceID must agree
  with the Filter descriptor. `image_outputs` is an array of distinct nonempty
  strings in observed order; `[]` is permitted when observed empty. Unsupported
  observed types refuse, never coerce or omit silently.

Entry, descriptor and context hashes use sorted-key typed canonical bodies,
preserving int versus double and signed zero. Complete current core references
must match their stored core reference representations. Comparing core
`ProceduralRef.params` with raw observed parameters uses decision361's
`ParamByValue`: the core may convert an integral float to int, so numeric equality
here does not require the raw observation's numeric type or zero sign. This
comparison never rewrites observations or their hashes. Getters return the raw
typed observations; exact typed oracle comparison never normalizes expected
values. All other binding/reference fields retain their exact comparisons.
The entry key excludes only its own external map key.
Same context with conflicting observations refuses; identical immutable import
may be a no-op only after every binding, descriptor and provenance check passes.
No registry lookup or legacy fallback repairs a missing link. Save/reopen may
revalidate a fresh handle; old leases refuse as specified above.

This accepted operational contract closes 2.6f only. Implementation follows the
scoped 2.6g brief; no new capture is authorized by design acceptance alone.

## Alternatives Considered

- Reuse fill snapshot /3 without a raster: rejected; breaks admitted signature/output/raster meaning and invents executable support.
- Seed the existing synthetic filter from old replay expected values: rejected; oracle-derived fixture inputs invalidate independent comparison.
- Key only by asset pin and effective parameters: rejected; no evidence that observations are independent of effect/content/settings context.
- Implement full Filter evaluation first: valid later direction, but not required for a bounded non-executable observation diagnostic.

## Consequences

This accepted technical contract is owned by phase3.1_proc-backend-seam, not phase3.2_proc-snapshot-backend. Coordinator, control and Claude review settled the canonical context projection and diagnostic schema/URI for V1. Implementation can be split into store/provider/importer and independent public-API capture tooling, with native build/capture ownership serialized. No owner confirmation is needed merely for these reversible technical implementation choices under the standing implementation request. An owner decision would be required to change licensing/distribution policy, waive parity or a gate, or expand approved production cutover scope; this decision does none. Pilots, G1/G2, amendment, procedural family certification and task-wide acceptance remain open.
