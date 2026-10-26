# Filter observations V2

This is the closed implementation contract accepted by [decision 363](../.rulebook/decisions/363-filter-observation-v2-explicit-frozen-host-migration-and-authoritative-current-context.md), extending [decision 362](../.rulebook/decisions/362-project-private-filter-source-observations-through-a-test-only-diagnostic-fixture.md) with the frozen snapshot migration defined by [decision 327](../.rulebook/decisions/327-proc-snapshots.md).

Initial implementation covers store/provider and authored tests. Real import and capture depend on the evidence and checks below. V1 serialized bytes, descriptor pins, dispatch and existing test-only import/2 payload remain unchanged. Snapshot schemas /1-/3 remain unchanged.

H denotes the independently captured, project-private paired scalar/RGB host snapshot. F denotes the independently captured Filter observations and complete target-context readbacks. B is H's verified native-precision scalar raster. The accepted relation is `paired-scalar-rgb-to-user0-frozen-host-v1`: B is frozen Painter-produced migration data, not a reconstruction of Painter's intrinsic procedural operand. V2 enables only `get_parameters`, `resource_id` and `image_outputs` on the observed Filter. It grants no Filter evaluation, output raster, family certification or editable procedural domain. Neither old expected values nor private differences supply constructor inputs.

## 1. Dispatch and hash graph

Keep the existing top-level project member `filter_source_observations`. Its exact `schema` selects V1 or V2. This is an explicit versioned namespace dispatch, not a new project key that existing plane walkers would accidentally traverse. A project holds one version, never a mixed namespace. No implicit upgrade, fallback or interpretation of a malformed /2 body as /1.

New literals:

- namespace: `uzpainter/filter-source-observations/2`
- entry: `uzpainter/filter-source-observation/2`
- context: `uzpainter/filter-observation-context/2`
- capture: `uzpainter/filter-observation-capture/2`
- native proof: `uzpainter/filter-frozen-host-native-proof/1`

Reuse `uzpainter/filter-observation-descriptor/1` and `uzasset://observation/<descriptor-hash>@1`. V2 descriptors allow only role `filter`; host remains a real snapshot reference. Reuse `uzpainter/observation-inventory/1` exactly as emitted today, without another resources census or alternate field names.

Hash all bodies with `ObservationKey` / typed canonical JSON (int/double and signed zero retained). Descriptor depends only on descriptor fields. Project projection includes the Filter descriptor pin but excludes the complete top-level observation namespace. Inventory excludes that namespace through the current walker. Context depends on projection and inventory. Native proof binds projection/inventory, never entry key. Entry depends on context, capture and descriptor. Namespace binding maps UID to entry key. There is no hash cycle.

Unknown schemas or fields refuse. UID keys remain canonical positive decimal strings; IDs are exact positive int64 within core ID range. Hashes are lowercase SHA-256, never arbitrary strings. An exact integer never accepts a boolean or double.

## 2. Exact namespace, descriptor and entry fields

Namespace /2 has exactly:

`schema, descriptors, entries, bindings`

No `host_bindings`. `descriptors` maps descriptor hash to existing descriptor/1 body with exactly `schema, role, resource_id, parameters`; role is `filter`. Existing ResourceID and finite int64/double/string parameter validators are reused unchanged. Each key hashes its complete body.

`entries` maps entry hash to a body with exactly:

`schema, project_uuid, role, host_snapshot, filter_descriptor, binding, context, context_sha256, capture, observations`

- `schema`: entry/2 literal.
- `project_uuid`: nonempty, equal authoritative store UUID when checking namespace.
- `role`: literal `filter`.
- `host_snapshot`: exactly `signature_sha256, plane_id`. The signature selects an entry in the HISTORICAL context project's `procedural_snapshots`; plane ID must equal that entry's plane. Require source_metadata /3 containing BOTH complete `typed_effective_parameters` and `observed_resource_id`. Existing /3 validator must pass. Do not duplicate or rewrite metadata in the observation entry.
- `filter_descriptor`: hash selecting role-filter descriptor in this namespace.
- `binding`: exact shape below.
- `context`: context/2 below; `context_sha256` equals its typed canonical hash.
- `capture`: capture/2 below.
- `observations`: reuse V1 optional-members object; only `parameters`, `resource_id`, `image_outputs` allowed. Missing remains missing. Present parameters/identity must typed-match the descriptor; image outputs retain distinct nonempty strings in observed order, including genuinely observed empty array. Real importer later requires all three for this slice; storage still represents partial observation faithfully.

Refuse a second entry with the same context hash, preserving V1 conflict policy. Historical entries may remain unbound/stale. `bindings` maps canonical Filter UID string to entry hash; entry binding's Filter UID must equal key. References to missing entries/descriptors refuse. No host descriptor fallback.

Binding has exactly the existing V1 fields plus one role ID:

`texture_set, stack, host_uid, filter_uid, initial_paint_uid, node_stack, effect_index, host_channel, host_reference, filter_reference`

IDs are positive/distinct as required by the historical graph; `node_stack="Content"`, `effect_index=0`, `host_channel="User0"`. Both references must round-trip through `ProceduralRefFromJson/ToJson` with identical typed canonical text. Filter reference asset equals selected descriptor pin. Host reference is the actual `snapshot` family pin from selected snapshot signature and retains every field/extra, output mapping and resolution override. It must not be an observation pin. Binding fields identify the actual historical host/Filter/initial Paint and owner set/stack, not merely valid numbers.

## 3. Exact context and inventory

Context /2 has exactly:

`schema, project, store_uuid, inventory`

`project` is full `ProjectToJson` with only top-level `filter_source_observations` erased. Reject that member if present; preserve every other extra and field. Parse into a historical Project, run `core::Validate`, and require exact typed canonical round-trip. `store_uuid` equals entry/store UUID. `inventory` is the current exact inventory/1 serialization:

- inventory root: `schema, project_uuid, planes, resources, snapshots`.
- plane: `plane_id, references, set_id, stack_id, channel, tile_u, tile_v, format, width, height, chunk_size, version_id, chunk_root, chunks, byte_count, sha256`.
- reference: `owner, path`; owner null or positive ID, path exact existing walker string.
- chunk: positional array `[x,y,sha256]`, exactly three elements.
- resource: `sha256, size, mime, records`; records is the complete canonical manifest resource metadata array for this hash.
- snapshots: sorted array of every retained snapshot key, not only the selected host.

No `created_revision`; no other row exclusions. Plane ID order, resource hash order, snapshot key order and chunk `(x,y)` order must match serializer; duplicates refuse. The current inventory has one reference per plane because the store prohibits sharing; validate against historical `ManifestPlaneReferences`, not an invented graph representation.

### Historical structural validation (store/commit/open)

This validation is PURE: no Container access, no current-byte lookup and no native rendering.

- Check exact fields/types/ranges, known enums, positive dimensions <=kMaxPlaneEdge and existing kChunkSize, safe byte-count arithmetic, nonnegative chunk coordinates inside grid, unique/sorted chunks, recomputed `ChunkRoot`, and `byte_count=width*height*TexelBytes(format)`.
- Derive holders, references and bindings from the historical Project. Require inventory coverage to equal that complete set, including every inactive retained snapshot. Every row owner/set/stack/channel/UDIM, reference owner/path, version ID and root must agree. Reuse foundation's pure holder/row checks where possible; do not expose unchecked row arithmetic.
- Validate every historical snapshot with `SnapshotProblem(uuid)`. Snapshot key list must be exact. For the selected host, validate signature key/hash, UUID, plane/version/root, canonical scalar raw F32 output dimensions/channels against the L32F128 census plane, and metadata /3 with both required observations. Verify the complete host reference's snapshot pin against signature asset/version, its explicit output mapping against signature output ID, and scalar parameters through the existing core/store ParamByValue codec. Generic inactive snapshot objects retain the generic store contract.
- Resource set and `records` must exactly equal historical `project.resources`; size/MIME must agree with every historical metadata record. Mesh and other resource references allowed by the closed V2 domain must resolve to census entries; no unenumerated dependency. Empty metadata records must not authenticate a referenced resource.
- SHA fields are syntactically validated and linked where recomputable. Historical texel/resource hashes cannot be authenticated without bytes and are NOT claimed to be. Integrity here proves internal structure and completeness, not live availability.
- Historical host/Filter/empty-Paint shape, binding and snapshot relationship must satisfy V2 domain using pure code. Never compare historical projection with current project during commit validation: legitimate later edits may make observations stale and must remain savable.

The store library does not link the procedural library. Historical structural validation therefore does not call `RequestFor`, `SnapshotUseContext` or a procedural provider, and does not accept an injected callback to bypass this boundary. It validates all JSON shapes, canonical forms and explicit links above. The complete procedural request/signature relation is an operational check performed by the procedural live lookup and the diagnostic importer before commit. A structurally valid historical entry with a failed operational relation remains unusable; structural validity is never permission to return a getter value.

### Live context validation (getter/prospective import)

Take an immutable or transaction-owned Project and exactly one `ReadObservationInventory(project)` call, which locks the store once and verifies actual stored/staged bytes, roots, resources and UUID. Build context from that same Project and returned inventory. Typed equality to recorded context plus recomputed hash is mandatory; no version-only cache.

All remaining host checks use that Project's parsed snapshot metadata and that returned inventory. The pure `SnapshotFillRequest` seam shares the provider's domain predicates, `SnapshotUseContext` and `RequestFor`; require its exact selected signature. Check signature output against the census plane. Do not call `SnapshotBackend::Load`, `ReadPlane`, `ReadResource` or `SnapshotSourceProvider::Metadata` after the inventory call, since separate store reads would mix views. No renderer runs in a getter.

The caller's retained OpenProject/session lease remains mandatory and unchanged. Submit callbacks run without store mutex and call the locked wrapper. Only commit extensions or store-owned locked code call unlocked inventory core. Never recursively lock.

## 4. Exact capture /2

Capture has exactly:

`schema, filter, host, migration`

### filter

Exactly `provenance, manifest, record, environment, rounds`.

`provenance` is the EXISTING V1 capture body, validated unchanged: exactly `recorder, envelope_id, painter_build_id, recipe_sha256, resource_query, authored_inputs, receipts`. Its inputs/receipts retain existing closed shapes. `manifest`, `record`, `environment` are artifact refs with respective literal kinds `filter_manifest`, `filter_record`, `filter_environment`.

`rounds` is exactly two objects in order, each exactly `condition, probe_sequence_sha256, context_readback_sha256, host_readback_sha256, filter_readback_sha256`; conditions are `same_session`, `after_save_reopen`. Store validates shapes/order/link consistency. Real importer validates these hashes against sections of the admitted record and exact setup-once/probes7-24-twice lifecycle. Hashes never substitute for checking actual operations and state.

### host

Exactly `protocol, receipt, request, environment, environment_binding, scalar_exports, rgb_exports`.

- `protocol`: literal `paired-scalar-rgb`.
- `receipt`, `request`: artifact refs kinds `snapshot_receipt`, `snapshot_request`.
- `environment`: null or artifact ref kind `snapshot_environment`.
- `environment_binding`: null or artifact ref kind `snapshot_environment_binding`; nullness must match environment. Historical absence is legal; never manufacture these from F or current machine.
- `scalar_exports`: exactly two refs kind `snapshot_scalar_export`, in original H round order.
- `rgb_exports`: exactly two refs kind `snapshot_rgb_export`, same order.

An artifact ref always has exactly `kind, sha256, size_bytes`. Size exact nonnegative int64. Kind fixed by its field. The same blob may validly occur twice when repeated exports are identical; do not require distinct artifact hashes. Store checks structure only. Real importer resolves bytes from private admitted artifact transport and verifies every claimed hash/size and admission where applicable.

### migration

Exactly `rule, raster_stage, raster_sha256, capture_context_sha256, destination_host_context_sha256, native_evidence`.

- rule: `paired-scalar-rgb-to-user0-frozen-host-v1`.
- raster_stage: `frozen_output`.
- raster_sha256: selected host census plane's texel SHA.
- capture_context_sha256: typed hash of validated complete H readback context under original protocol (real importer computes; store checks hash shape).
- destination_host_context_sha256: exactly `context_sha256` of this entry. It covers the full destination context, not a selectively normalized host subset. Real importer computes it after assembling context; historical validator checks equality.
- native_evidence: exact proof body below, embedded rather than an opaque artifact ref. This makes its binding to historical projection/inventory structurally checkable. Private external report may carry the same body; capture stores only this closed record, no path or pixel data.

Native proof body has exactly:

`schema, rule, validator_code_sha256, binary_sha256, domain_sha256, project_uuid, prospective_projection_sha256, inventory_sha256, signature_sha256, plane_id, version_id, chunk_root, raster_sha256, uploaded_sha256, final_output_sha256, sample_count, nonfinite_count, fixed_point_mismatches, upload_mismatches, final_output_mismatches`

Schema is native-proof/1 above; rule same fixed literal. SHA fields lowercase. UUID equals entry. Projection/inventory hashes equal hashes of context.project/context.inventory. Signature/plane/version/root and raster SHA equal selected host snapshot/census. Uploaded/final hashes equal raster SHA. Sample count equals selected scalar width*height. Counts exact integers, all four error counts zero. Domain hash equals the typed canonical hash of this exact public object (keep the object in code/tests, not an unexplained magic digest):

```json
{
  "schema": "uzpainter/filter-frozen-host-domain/1",
  "rule": "paired-scalar-rgb-to-user0-frozen-host-v1",
  "mesh_sha256": "7d3c5f616c2abf4b06050434fa943d19dcb15ec998245a211d1d4ca7e95197fe",
  "width": 128,
  "height": 128,
  "channel": "User0",
  "format": "L32F",
  "source_stage": "frozen_output",
  "source_transport": "snapshot-direct-upload",
  "proof_topology": "host-fill-over-empty-paint-with-observed-filter-removed",
  "readout": "float32(1+float32(v-1))",
  "finite_required": true,
  "fixed_point_required": true,
  "bitwise_upload_required": true,
  "bitwise_final_output_required": true
}
```

The mesh hash must be the existing provider constant verbatim; validate the literal length and equality when implementing. The rule ID binds the complete projection/provider predicates listed in this specification; the domain record does not replace those checks. Validator-code/binary hashes identify actual trusted native computation, not acceptance based on arbitrary strings.

These structural relations do not authenticate an arbitrary caller-created proof. Only the diagnostic importer may construct a real private entry, after running trusted actual native transport/fixed-point/full-chain computation on this prospective state and validating H/F evidence. Store/provider authored tests may construct synthetic entries explicitly; no public setter/importer is added in this slice. Runtime getters authenticate current bytes/context against recorded entry; they do not re-execute or re-admit capture evidence.

## 5. V2 software domain and live lookup

The closed target domain is:

- The authored full-UV plane with the mesh hash in the domain object, one non-UDIM set at128x128, one stack and UV tile1001; exact verified mesh bytes/import identity.
- Legacy, OpenGL, PerVertex, Default workflow and mesh unit scale1; no colour config, working-space or I/O overrides. Other required settings stay in the complete projection and match the admitted evidence.
- Root order exactly `[host Fill, original empty Paint]`. Verify `core::IsEmptyPaintLayer`, not a display name: no paint planes, content effects or other content. Preserve actual names and IDs; do not rename the initial Paint.
- Host Split source exactly User0, active channels exactly User0, channel format L32F, visible, Normal opacity1. No masks, children, instances, preset references, extra content effects beyond the observed Filter, symmetry or nonneutral geometry mask. Preserve all other template stack channels in the projection; no extra bound host source.
- Host projection UV or Fill, Factors identity scale/rotation/offset, BilinearHQ/Repeat, matching the existing `SnapshotSourceProvider` guards. These are acceptance predicates, not assertions about unobserved Painter defaults.
- Filter is the sole host Content effect at index0. Its active channels form a nonempty canonical subset of actual stack channels. Every name, visibility, channel, known blend value and finite opacity in[0,1] must be faithfully represented and context-hashed. Its procedural reference has no preset or image inputs, and parameters use the same finite int64/double/string codec. An image input pointing at an already inventoried resource is still outside this domain. No unsupported child/mask/reference or silently dropped state.
- Snapshot /3 finite scalar int64/double/string parameter domain remains closed. Bool/vector/colour/object/array observations refuse rather than coerce. Resource identities stay complete and provenance-only. No unresolved dependency, locator-only resource or invented raster/hash.

If fresh F defaults lie outside these predicates or existing codecs cannot retain them, refuse before import. Preserve complete unknown extras conservatively in the project context; do not infer that absent evidence means a neutral default.

Snapshot serving is real and host getters keep their existing /3 path; V2 adds no observational host alias. Filter descriptor is metadata only and never satisfies Admit/CanEvaluate. Original restrictions on setters/resolution remain unchanged. V1 ObservedFilter branch and Context function retain existing behavior. Add a separately named `CurrentFilterObservationContextV2`; existing V1 callers cannot accidentally select V2 by project shape.

`ObservedFilter` dispatches exact namespace schema, validates structural namespace, resolves entry/binding, validates current domain and complete host/Filter references, verifies Filter descriptor parameter values through existing ParamByValue boundary, obtains one live inventory/context, compares typed context/hash, then returns copied optional observations. Any missing/corrupt/stale mismatch refuses through existing error boundary. No cross-version fallback.

## 6. H/F evidence and exact lifecycle

### H validation and historical environment

Use the existing `capture_request`, `validate_readback`, `ReceiptSourceMetadata`, `RequestFromSignature`, `SnapshotExportTexels` and `SnapshotProblem` contracts. Verify original request's exact versioned ResourceID and overrides against recorded H readback, complete observed identity, typed effective parameters, seed, ordered output list/active output, resolution, no image inputs, immutable signature and source_metadata /3. Preserve numeric types and signed zero; ParamByValue is allowed only at its existing core conversion boundary.

Authenticate original paired bridge receipt/request/readbacks and four export references through private artifact transport/admission where applicable. Decode without precision conversion. Scalar B must equal every RGB component bitwise, both export rounds must match, and readback must remain stable. Verify lengths/hashes, plane format/dimensions and actual destination census, including inactive retained snapshots. Existing snapshot UUID must equal the owning store; never relabel a foreign snapshot.

The original bridge checks sole Fill, no effects/masks, full-UV128, Legacy, User0 L32F plus auxiliary User1 RGB32F, identity Nearest/RepeatNone and full-coverage Normal opacity1. Missing required original-protocol fields refuse. Do not relabel old bytes as a new protocol.

H's historical environment record may be absent. The existing bridge identity records build/project/colour/mesh data, not necessarily the later five-field envelope. Preserve known provenance and explicit null environment/binding. Do not borrow F's environment, require retrospective H/F GPU/driver equality, or regenerate B on a different machine. This serves already frozen bytes and metadata; reproducing H through a fresh renderer would be a separate claim requiring its own compatibility evidence.

Authenticate H under its original pinned bridge and control trace. That bridge explicitly requests OpenGL,128px, PerVertex and mesh scale1 and checks its Legacy environment; its signature settings also bind the native destination context. This original admission did not expose a complete Painter effective-settings getter. V2 does not retroactively require such a getter or relabel authored arguments as effective readbacks. H remains frozen migration data governed by its original protocol and the explicit relation below.

Existing H /3 is eligible for reuse only when all predicates pass. Missing evidence produces a precise refusal, not an automatic capture retry. Existing independently admitted contemporaneous evidence may supply required fields; neither missing data nor caller flags prove compatibility.

### F lifecycle

Recipe A setup steps1-6 execute once: create project, add channel, insert Fill, select active channel, bind versioned host source, insert Filter. Filter insertion at step6 precedes every toggle. Probe steps7-24 execute in `same_session`, including setters marked `probe=true`. Save/close/reopen follows, then the same probe sequence7-24 executes using fresh handles in `after_save_reopen`.

Do not repeat setup, move toggles before Filter insertion, or replace round2 with three getters alone. Preserve documented refusals at steps19-24; they are observations, not setters required to succeed. Context-dependent resolution readbacks follow existing documented handling, not blanket equality of unrelated getters.

Read-only context evidence is collected after setup6, immediately before step16 in both rounds, and after reopen before repeated probes. It must not change A's state operations. Each pre16 boundary binds:

- Complete root order, types, roles, UIDs and positions; host/Filter ownership and the initial Paint provenance defined below, with observable mask/effect structure.
- All set/stack channels and formats, resolutions, mesh/import/settings and colour selection.
- Host source mode/active channels, complete observed ResourceID, typed effective parameters, outputs/active mapping, resolution mode/value/offset and image-input slots.
- Host name/visibility, per-channel blending/opacity, projection/UV/transform, geometry mask, symmetry where applicable, masks and effects.
- Filter complete observed identity, parameters, image_outputs, name/visibility, active channels and documented per-channel blend/opacity state.

Initial Paint uses the explicit provenance basis `initial-empty-paint-under-decision348`, following [decision 348](../.rulebook/decisions/348-empty-paint-layer.md). Authenticate fresh `project.create` with the default template, the complete closed recorder trace with no painting or content-writing operation on the initial Paint, and observable root role/type/UID/position/mask/effect structure. Preserve this initial node through the original lifecycle. This is the already accepted creation-and-trace inference, not a direct readback of Painter paint pixels, strokes or plane presence; the documented Python API does not expose strokes. An arbitrary opened project, edited initial Paint or incomplete trace cannot use this basis. The destination still must pass actual `core::IsEmptyPaintLayer` and the authoritative inventory, and native proof retains the layer. The provenance basis belongs to authenticated F context evidence, not a new optional field in the closed stored schemas.

Use actual serializer shapes, including nested dataclass class-name omissions. Apart from explicitly named accepted provenance bases such as the initial Paint basis, missing fields cannot be filled from native defaults, H isolation defaults or old expected outputs. A genuinely unavailable documented field needs an explicit supported provenance/domain representation before acceptance; it is never silently labeled a getter result.

F requires an admitted record, exact authored recipe/input/receipt joins and a valid recorded current-or-approved-equivalent Legacy envelope. Never equate Legacy with OCIO. The source identity at A step5 must match H and F host complete identities. Host state at both pre16 boundaries must match H's recorded effective state under the existing explicit codec boundary. Filter identity/values come only from the fresh capture.

### Authored settings versus effective F settings

Keep three facts distinct: authored `project.create` arguments, documented meaning of those arguments, and actual effective configuration evidence. Recipe A authors OpenGL and128px but does not explicitly fix every setting required by the target domain. The [official project Settings API](https://experienceleague.adobe.com/en/docs/substance-3d-dev/painter-python/api/substancepainter-package/project) describes omitted/None values as defaults; `mesh_unit_scale=None` or0 uses the mesh file's internal scale. These values do not prove PerVertex, Default workflow or unit scale1. Copying create arguments into a recorder field named `project_settings` does not turn them into an effective getter.

Legacy selection is supported by the authenticated recorded environment under the existing bridge's documented OCIO/ACE checks. It does not prove unrelated tangent, workflow or mesh-scale settings. For each target setting, require either the actual authored value with its documented semantics and authenticated successful operation, or independently bound effective configuration evidence. Preserve omission explicitly. Do not change A's setters or template to manufacture agreement, and do not infer F settings from H's explicit isolation setup or native defaults.

The [official Project Configuration interface](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/project-configuration) exposes relevant configuration, including read-only post-creation UV-tile settings. A separately validated read-only evidence protocol may bind such observations to the owned Painter project/process and lifecycle boundaries. No UI collector or capture is established by this document, and viewing configuration must not become a settings change or reimport. This is an evidence transport option, not another stored schema version.

Until each required effective F setting is established and matches the target domain, real H/F acceptance refuses with `F_EFFECTIVE_SETTINGS_UNVERIFIED`, identifying the missing setting without fabricating its value. Software/schema authored tests can proceed; a synthetic fixture is not effective-setting evidence for a real F capture. This requirement applies to the F-to-target relation and does not invalidate historical H solely because its original protocol lacked an effective-settings getter.

#### Bound read-only configuration evidence (future protocol)

A future UI evidence protocol must bind observations to the same owned F process (PID and process start identity), project UUID and uninterrupted session at all five F lifecycle boundaries. Bracket each observation with typed context readbacks; require the same project/process identity, boundary context and `needs_saving` value before and after. Pin the exact imported mesh bytes and authenticated successful import trace, including input hashes before and after import; a current path or later file hash cannot prove historical imported bytes. The closed trace must exclude mesh replacement, reload/reimport and scale-setting edits between creation, observations and the relevant boundaries.

Resolve each configuration control uniquely within the owned dialog using validated selectors. Preserve raw labels, control identities, visibility/enabled state and selection/value states, with screenshots retained privately and bound to the same observation. Capture the tangent checkbox and UV workflow checkbox plus its selected workflow option where applicable. Read disabled controls without treating their inactive values as effective settings. Viewing or expanding a section must not edit settings; close through verified Cancel without Apply, OK or reimport, and verify the bracketed context remains unchanged. Ambiguous controls, missing states, failed identity checks or incomplete boundary coverage refuse evidence.

The supported proposed provenance basis `unitless-obj-internal-centimetres-v1` composes an observed internal-unit selection (with custom mode unselected), the exact authenticated unitless OBJ actually imported, and documented import semantics to derive `effective_cm_per_unit = 1`. The [official Physical size guide](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/features/physical-size) states that OBJ has no unit information and is measured in centimeters without conversion by default. The [official Project Creation guide](https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/getting-started/project-creation) distinguishes internal units from a custom override of a single unit's size; the [Settings API](https://experienceleague.adobe.com/en/docs/substance-3d-dev/painter-python/api/substancepainter-package/project) identifies centimeters as Painter's unit and the override required for OBJ units other than centimeters. This basis requires the complete binding and unchanged import/scale trace above. It is a documented derivation of physical scale, not a numeric getter of `mesh_unit_scale`; selection value `1` is a boolean state, not the scale. Neither `None`/0 alone, a disabled custom value, nor a bounding-box ratio establishes this basis.

Keep authored arguments, raw observations and derived conclusions separate, with explicit source and provenance references. Consumers must validate the complete evidence and derive the target-domain relation themselves; no caller-supplied `compatible` flag substitutes for these checks. This subsection specifies requirements, not an admitted collector or acceptance profile. A new schema/profile, admission path and independent review must validate the protocol before real acceptance. Historical F without this evidence still refuses; standalone surveys cannot retrofit F385 or any earlier capture.

Only after independent fixture construction may old step17 identity and old16/18 values be read for strict comparison. Drift fails item2.6j; it never selects constructor values, another capture recipe or a fitted raster.

## 7. Closed frozen-host migration

H isolation and F target are two authenticated contexts related by the following enumerated mappings. Their context hashes are not expected to equal. No caller-supplied `compatible` flag or free-form allowed-differences list is accepted.

1. **Frozen source substitution.** H scalar B becomes the actual project-private snapshot plane. `SnapshotSourceProvider::Resolve` and `CpuTileStore::Upload` copy its Float32 bits. Destination keeps the genuine snapshot reference, signature, metadata, plane/version/root. Original ResourceID is provenance, never an executable archive alias. The H store's host Fill may also hold the facade's known constructor defaults on inactive channels; mapping 1 removes exactly those, as section 11 defines ("Known constructor defaults on the host Fill"), and nothing else.
2. **Auxiliary RGB removal.** User1 is the paired bridge's isolation control. Its three components and both rounds must equal B before removal. Destination retains F's actual stack channels and exactly its User0 host source; do not invent or silently remove a channel from F's projection. This is the existing scalar snapshot migration, not an arbitrary channel-independence theorem.
3. **Projection boundary.** H Nearest/RepeatNone remains capture provenance. Destination obeys existing identity full-UV128 BilinearHQ/Repeat admission. The snapshot provider uploads B directly without sampling either UV mode. This relates frozen output to stored source; it does not claim that rerendering the original procedural under two Painter projections gives identical intrinsic pixels. Provider guards remain unchanged.
4. **Initial empty Paint.** H sole Fill maps to F's actual `[host Fill, initial empty Paint]`. Require the real empty-Paint predicate. Native proof retains the Paint and exercises its actual skip; name, UID and position remain context state.
5. **Observed Filter insertion.** Retain the sole index-zero Content Filter in destination projection and observation binding as non-executable. Only an in-memory native proof scene removes that identified Filter; all other state is preserved. The real destination is not altered by proof.
6. **Role identities.** Map session-local set/stack/node IDs and procedural-to-snapshot pin through the checked role map, full binding and provenance. Preserve F names/state. H isolation names remain H provenance and never overwrite F names.

All other required shared evaluation settings, mesh/import identity, effective source state and output/resolution identity must agree under existing typed codecs. Full F structural/source/default readbacks must satisfy the closed target domain and map faithfully to the complete destination projection. Unknown differences refuse.

`SnapshotUseContext` plus `RequestFor` from the actual destination must equal selected H signature. This is necessary signature validation, not proof of UV equivalence. The complete current plane/resource/snapshot inventory, real bytes and immutable entry must be checked atomically with the prospective state. Getter lookup must already succeed before commit; refusal leaves no mutation.

No intrinsic-source inverse is required. The accepted claim is frozen migration plus contextual metadata. Proof of actual Painter pre-Filter operand equivalence, Filter execution and family certification is outside this contract.

## 8. Native proof and test seams

Acceptance computes on actual prospective B using trusted native code. An arbitrary evidence JSON, matching hashes copied from a request, a range check, or a reusable suite result cannot substitute for execution. Verify every B sample is finite and bitwise `R(B)==B`, where `R(v)=float32(1+float32(v-1))`. Require this for all B, including values in[0,1]; idempotence `R(R(v))==R(v)` alone does not make arbitrary v a fixed point. Never normalize signed zero or source data.

Use real `SnapshotSourceProvider` and `evaluator::BuildDag` on the proof Project. Check the host `DagSource::Kind::Procedural` and its actual resolved image. Preserve the project's registered evaluator profile and template. Verify profile identity, isolated root and `readoutBase[0]==1.0f` for this rule; unknown or unsupported profile/base refuses. Do not silently replace a profile to make proof pass.

`CpuTileStore` is final. A test-only `ITileStore` delegator may forward every operation to a real `CpuTileStore` and intercept Upload after the actual call. Read the same tile with real `CpuTileStore::Read`; it returns tightly packed logical channels without coverage, so L32F compares directly with B. Hand-built image upload alone is insufficient: actual Resolve/DAG must supply that image.

Use fresh `TileCache` and `EvalEnvironment` with the real provider, then `EvaluateChannel`. Require actual procedural upload, no bitmap Project call, exact raw uploaded bits and exact final `ChannelResult` bytes. Cold proof must execute Upload; warm-cache verification is a separate case. The current isolated profile's readout runs through Blend; the older OverBase profile directly uses `Float32Readout`. Test the actual selected full chain, not only that helper or a Python formula.

The proof copy removes only the identified observed Filter. Verify the original Project is unchanged, every other projected field is retained, and the genuinely empty Paint remains in the proof Project. A nonempty Paint negative case must not be hidden by erasing it before evaluation.

The minimum authored stage-discriminating patterns are:

| Input | Input/raw-upload bits | Final R bits | Fixed point |
|---|---|---|---|
| +0 | `0x00000000` | `0x00000000` | Yes |
| -0 | `0x80000000` | `0x00000000` | No |
| 2^-26 | `0x32800000` | `0x00000000` | No |
| 2^-24 | `0x33800000` | `0x33800000` | Yes |
| 0.5 | `0x3f000000` | `0x3f000000` | Yes |
| 1 | `0x3f800000` | `0x3f800000` | Yes |

Construct samples from uint32 bit patterns. A mixed plane preserves all raw bits and fails frozen-output admission on -0 and2^-26. An all-fixed plane passes both raw and final equality. Use uint32/memcmp equality, not float equality or tolerances. Include corners, row ends and adjacent texels;128x128 is one evaluator tile because `kTileSize=1024`. Do not claim multi-tile coverage or enlarge the accepted domain to obtain it. Adjacent values near0.5/1 and finite subnormals can extend negative/rounding tests without changing admission.

Keep authored reopen/bundle/cache integration checks from `tests/export/snapshot_source_test.cpp` and `tests/python/test_snapshot_source_export.py`: exact source bits, final fixed output, retained-input corruption refusal, foreign UUID and missing snapshot refusal. A hot or persistent cache cannot hide unavailable authoritative bytes. The native proof operates on Float32 `ChannelResult`; EXR encoder transport belongs to existing export tests.

Native evidence is the embedded closed body specified in section4. Compute its UUID, projection/inventory/signature/plane/version/root, hashes and counts from the same run. Source/private bytes stay private. After computation, recheck owning revision, prospective projection and inventory before atomic insertion. A changed view refuses or restarts under the transaction contract. One earlier census does not keep arbitrary later native provider loads atomic.

Getters never run this proof. They perform pure checks and one locked inventory read. `SnapshotSourceProvider::Admitted` loads `SnapshotBackend`; Metadata calls Admitted. Neither may be used after inventory in live V2 lookup. Extract pure guard logic if needed and retain canonical typed comparisons, including signed zero.

## 9. Files and implementation split

- `src/store/filter_observations.h/.cpp`: V2 literals, explicit dispatcher, closed capture/entry/context validation. Preserve V1 helper behavior; separate `CheckV1/CheckV2` paths.
- `src/store/observation_inventory.h/.cpp`: pure historical inventory validation against supplied historical Project/UUID, sharing safe row/holder logic; existing live serialization unchanged.
- `src/procedural/filter_observation_source.h/.cpp`: distinct contextV2/domain/live lookup branch; pure host signature/metadata checks and one inventory read.
- `src/procedural/snapshot_request.cpp` and `src/procedural/snapshot_source.h/.cpp`: shared pure `SnapshotFillRequest`/`SnapshotUseContext` extraction, without guard weakening or new evaluator behavior. `build.zig` includes the pure source in procedural and export targets; the store library gains no procedural dependency.
- `tests/store/store_test.cpp`, `tests/store/test_project_store.py`: authored V2 schema/history cases alongside V1.
- `tests/procedural/procedural_test.cpp` and its existing Python driver: authored current lookup, stale/corrupt/inventory tests. No new runtime capture helper or actual private import yet.
- Existing facade `src/python/bind_layerstack.cpp` and lease behavior should need no semantic change: it already calls `ObservedFilter`. Verify V1 and V2 retained handles/identity refusal in appropriate authored Python tests when synthetic native fixture support is separately authorized.
- Later gated tools get distinct import payload/command version; current `uzpainter/filter-observation-import/2` is a V1 fixture payload and MUST NOT be reused as V2 observation import merely because its suffix is /2.

## 10. Required authored tests before real import

1. Preserve existing V1 canonical fixture hashes/bytes and all V1 passes/refusals. Unknown/mixed namespace schemas and V2 host_bindings/host_descriptor refuse.
2. Every closed shape rejects unknown/missing fields, wrong scalar types, bool-as-int, malformed hashes/UIDs and conflicting context. Signed zero and int/double differences remain visible.
3. Historical context validates against historical graph/inventory after current graph changes; stale observations save/reopen. Incomplete historical plane/resource/snapshot census, extra inventory rows, wrong holders/paths, roots, byte counts, metadata records or host signature refuse.
4. Live rehash detects missing/corrupt bytes, changed staged version with same version ID, changed inactive retained snapshot, plane format/size/root, resource metadata/bytes and foreign UUID. Sparse omitted chunks zero; listed missing chunks refuse.
5. Real snapshot host retained; /3 metadata missing either required field refuses. Wrong signature/output/resolution/complete reference or initial Paint role refuses. Filter observation pin cannot act as host or executable source.
6. Capture historical H environment null accepted structurally; F missing required environment ref refuses. Duplicate export hash allowed; wrong array cardinality/order rejected. Native proof self-consistency failures refuse; synthetic proof record never treated as actual runtime execution evidence.
7. Prospective Submit callback succeeds without deadlock via one locked inventory; rollback unchanged; committed/staged semantic census equal; namespace-only insertion causes no context cycle. Store structural commit never loads current bytes through historical validator.
8. Fresh getter success only for matching current context/lease. Stale handle after reopen refuses; fresh handle may succeed. Unsupported setters and legacy branches unchanged. Partial observations preserve absence versus empty.

Real H/F acceptance additionally requires the approved migration-rule native computation and independently admitted fresh F context. This specification authorizes no substitute stub, fabricated proof, capture retry or parity promotion.

## 11. Native F gate (contract addendum, before code)

The only real constructor of `VerifiedFilterContext` is a native gate over admitted F bytes for the golden `tier0/api-probes/filter-context-settings-a`. Python validators (`filter_context_settings_validation`, `filter_context_validation`, `filter_source_binding`) remain the executable specification and a test-only differential oracle; a Python result, report, object or flag is never accepted as authentication. The isolated embedded interpreter is not a trusted boundary: nothing pins its standard library, site-packages or `python/` folder, and its `._pth` runs `site`. Historical F385 and every capture without bound settings evidence still refuse.

### Entry point and destination

A distinct command and payload: `UzPainter.exe assets import-filter-observation <h-store.uzp> --oracle-store <root> --manifest <public-manifest.json> --request <import.json>`, payload schema `uzpainter/filter-observation-v2-import/1` (never the V1 fixture payload `uzpainter/filter-observation-import/2`). The payload has exactly `schema, manifest, host, expected_base_revision`:
- `manifest` is a `kind, sha256, size_bytes` ref of kind `filter_manifest` naming the public manifest bytes the command reads from `--manifest`;
- `host` is the capture/2 host section;
- `expected_base_revision` is an exact nonnegative integer.

No locator map, trust flag or computed value is accepted. Every private byte is read from the oracle store by the layout below.

The command is registered in `UzPainter.exe` (`src/main.cpp`) and in the export test executable's dispatcher. It reads the envelope registry at `<executable folder>/assets/filter-gate/registry.json`, which the build installs from `parity/envelopes/registry.json`; the bytes must still equal the compiled registry. In order, it:
1. parses the payload strictly (`ParseFilterImportRequest`);
2. opens the oracle store;
3. admits H (`AdmitHostCapture`) and F (`AdmitFilterCapture`, C2 and C3);
4. runs the store-free `ValidateFilterHostBinding`;
5. requires the original H file to be at rest, with no `-wal`, `-shm`, `-journal`, `.compact` or `.vacuum` companion;
6. opens it with a read-only preflight under the project lock. The preflight requires journal mode `delete`, checks that the store UUID is the H receipt's project UUID, looks up the replay row (`DecideStored`) and computes `ExpectedDestination` on the store's actual base;
7. calls `CommitAdmittedFilterObservation`, saves, reopens, and requires `ObservedFilter` to return the committed entry with the expected observations.

It prints one `UZP_JSON:` report: `ok` (with `replayed` and `verified_after_reopen`), `refused`, `host_error` or `committed_verification_failed`. A refusal inside the commit is reported with its reason and the fixed detail `NATIVE_COMMIT_REFUSED`; no store or proof detail text is printed.

The public manifest is NOT an admitted blob. `record_run` admits only its twelve private refs and writes the manifest outside the store, so no store entry or blob exists for it. The manifest bytes are untrusted input until all three of these pass:
- their SHA-256 and size equal the payload ref;
- the F1 invariants hold;
- every one of its twelve refs joins an admitted store entry (F2–F4).

Its ref in the capture/2 filter section is the hash of exactly those bytes.

The destination is the ORIGINAL H store at `<h-store.uzp>`: no copy, no `SaveAs`, no new store and no new UUID. Its `project_uuid` must equal the H receipt's. It must hold the H snapshot entry, with the receipt's signature and `/3` metadata, and the census plane equal to B. `CheckCaptureDomain` (mesh and settings) must pass. All mapping is computed in memory. The mapping, the Filter insertion, the native proof and the immutable entry happen in ONE `Submit`. Any refusal, including inside that callback, leaves the store byte-identical: no revision, operation record or stored change. Only a committed outcome is followed by `Save`, close, reopen and `ObservedFilter`, which must return the same entry and observations.

### H admission (shipped)

`AdmitHostCapture(host, store)` (`filter_gate_host.h/.cpp`) admits the capture/2 host section from the same oracle store:

- **Capture id.** Slot ids are assigned by protocol position (`receipt`, `request`, `r1-scalar`, `r2-scalar`, `r1-rgb`, `r2-rgb`) and never taken from a caller. The capture id is the typed hash of `{protocol, artifacts}`.
- **Admission before blobs.** Two files are read before any blob:
  - the admission record `snapshot-captures/<capture id>/<policy sha256>.json`: closed schema, the producer policy `{sha256, revision 1}`, artifacts equal to the slots, provenance `owner_local_submission` with no execution attestation, the validation hashes and the admission time;
  - the retained policy `snapshot-producer-policies/<sha256>.json`, which must be byte-equal to the compiled `parity/snapshot-producer-policy-v1.json`.
- **Approved producer.** The receipt's recorder pins must be one of the policy's approved producer rows.
- **Native validation.** Every artifact is read and rehashed, then validated natively (`ValidateHostCaptureArtifacts`). The admission's signature, capture context and raster hashes must equal the native validation's.
- **Re-read.** The admission and policy are read again afterwards and must be unchanged.

The reason is `HOST_CAPTURE_INVALID`, with a fixed detail: `H_ADMISSION_UNAVAILABLE`, `H_ADMISSION_INVALID`, `H_POLICY_UNAVAILABLE`, `H_POLICY_INVALID`, `H_PRODUCER_UNAPPROVED`, `H_ARTIFACT_UNAVAILABLE`, `H_VALIDATION_MISMATCH` or `H_ADMISSION_CHANGED`. A native validation refusal keeps its own reason, with the detail `H_ARTIFACT_INVALID`.

### Test seam of the command (limitation)

The public `RunFilterImportCommand` always uses the installed registry path and the compiled F pins (`AdmitFilterCapture`). The command body is a private static `FilterImportCommandDriver::Run`, whose only friends are that public wrapper and the test-only `FilterGateTestAccess` (defined once in `tests/export/filter_gate_test_support.h`).

The end-to-end test admits its authored F under authored pins (an authored registry and envelope) through `FilterGateTestAccess::RunCommand`. This is unavoidable: the compiled envelope's hash has no authored preimage, and its real preimage is private host data. Everything else in that test is the real command: the compiled H policy, the payload, the preflight, C4, C5 with the native proof, saving and the getters. The test therefore proves the command's behaviour on authored evidence, not the admission of the real F envelope.

### F1 manifest

Decode the manifest with core JSON, which keeps int64, double, bool, null and string distinct and rejects duplicate keys and non-finite numbers. Its typed invariants must equal those of the fixed request compiled into the binary (`#embed` of `parity/envelopes/painter-12.2.0_js-api.1.1.20-env-a981b586eae7/requests/tier0/api-probes/filter-context-settings-a.json`). The invariants are the document without `private_records` and without `software.painter`. The typed hash of `instruction_sequence` must equal A's.

`software.painter` must equal the reviewed approved build compiled into the gate: `build_id`, `version` (its prefix before `+js-api.`) and `product`.

`private_records` holds exactly twelve refs, each validated separately as exactly `record_id, kind, sha256, size_bytes`:
- `golden-record`, kind `private_oracle_record`;
- `oracle-environment`, kind `oracle_environment_record`;
- ten `settings_panel_evidence` refs, with ids `r1-settings-<b>-<image>` for the first three boundaries and `r2-settings-<b>-<image>` for the last two, where `<image>` is `configuration-image` or `physical-size-image`.

The twelve refs are matched by exact, UNORDERED membership of `(record_id, kind)` pairs, with no duplicate and no other ref; the manifest's ref order is not checked. The gate keeps them internally in the fixed order above. Order is checked only where the record defines it: the recording outputs.

### F2–F4 admission and record

Admission is authoritative only in the oracle store. The root must be outside the repository and hold `store.json` with schema `uzpainter/parity/store/1`. For each of the twelve refs, the entry `corpora/<build_id>/<golden_id>/<record_id>.json` must exist, be closed `uzpainter/parity/store-entry/1` (`painter_build_id, golden_id, record_id, kind, sha256, size_bytes, file_name`) and equal the ref. Admission is checked before any blob is read.

The blob `blobs/<first two hex>/<sha256>` is read once, then its SHA-256 and size are recomputed. The plane input is the blob named by the fixed request's input SHA-256, read and rehashed exactly as the Python validator's `store.resolve` and `store.load` do. No `inputs/<sha256>.json` entry is required, because the F recorder writes none. The blob must hash to `PLANE_SHA256`. A receipt, ref or hash supplied by a caller never proves admission.

The record and the environment blob must satisfy their closed schemas, and `record.environment` must be typed-equal to the environment blob. Three identities stay distinct:

- **Environment identity.** The environment record (`uzpainter/parity/oracle-environment/1`) carries `painter_build`, `gpu_model`, `driver_version`, `os_build`, `colour_configuration_sha256`, `recorder_version` and its provenance fields; it carries no `OCIO`, `PAINTER_ACE_CONFIG` or source revision. It joins the approved envelope `painter-12.2.0+js-api.1.1.20-env-a981b586eae7` by the existing Legacy rule (`recorded_request_environment_matches` when the manifest names no OCIO configuration):
- `basis` is `recorded`;
- the five envelope fields are non-empty strings and none is `unknown`;
- `painter_build` equals the registry entry's;
- the SHA-256 of canonical `{painter_build, gpu_model, driver_version, os_build, colour_configuration_sha256}` is the entry's `envelope_sha256` or one of its `equivalent_envelopes`.

The raw host fields are never compared to anything else. The gate reads the registry at its locator before admission: its raw bytes must equal the reviewed `parity/envelopes/registry.json` compiled into the gate, and the entry is parsed from that registry's `current` id. The gate reads the registry again after admission, on success and on refusal. Unreadable bytes, changed bytes or a changed typed entry give `F_SETTINGS_REGISTRY_DRIFT`, which supersedes any earlier code and keeps it only as `F_SETTINGS_REGISTRY_DRIFT:<earlier code>`. An unreadable registry before admission gives `F_SETTINGS_REGISTRY_UNAVAILABLE`. `colour_configuration_sha256` must equal the hash the recorder defines for the Legacy readback.
- **Legacy selection.** This comes from the record key, not the environment. `key.project_settings` must be exactly `{create, colour_management}`, with `create` the compiled request's create settings and `colour_management` exactly `{mode: legacy, OCIO: null, PAINTER_ACE_CONFIG: null}`. `key.effective_defaults.colour_management` must be the same Legacy object.
- **Producer.** `environment.recorder_version` must equal the single reviewed settings producer compiled into the gate (`uzp-recorder/1+src.89f3bbffae21361e`). The reviewed source revision `7c3f819c…` is compiled provenance of that pin and is never read from the record. Unknown or future producers refuse.

The record must also have:
- `golden_id` and tier `0`;
- `key` with the build, the input pins and the recipe hash;
- empty `resource_hashes`, a null `bake_backend` and a null `render_state`;
- recordings exactly `[r1 same_session, r2 after_save_reopen]`, with one shared `session_id`.

### F5–F7 trace, context, settings and images

- **Settings slots removed first.** Exactly five validated panel/image triples are removed (the `split_settings_outputs` contract). The trace (`_f_evidence_from_record` with the settings golden) and the context sequence (`validate_context_readback`, `validate_context_sequence`, `validate_census`) are then checked exactly as section 6 and the Python specification define them.
- **Cross-round comparison.** Full frames are never compared raw across rounds: their output ids and lifecycle state legitimately differ, and the round hashes (F9) keep them whole. A field consumed by the F8 projection must have a typed-equal value, with no `raised`, in the leaf with the same `leaf_key(call, selector, parameters)` in `pre16-r1` and in `pre16-r2`. A consumed leaf missing from either frame, or differing between them, refuses. Leaves that F8 does not consume are not compared across rounds. The existing invariants of `validate_context_sequence` remain exactly as defined: project UUID, role UIDs, root census and initial Paint name.
- **Settings contract.** The settings contract (`_panel` through `derive_effective_settings`) must derive `PerVertex`, `Default`, one centimetre per unit and the basis `unitless-obj-internal-centimetres-v1`, against the admitted plane bytes.
- **Images.** Each of the ten PNGs must equal its ref and record blob (sha256, size, `image/png`) and decode completely with the vendored libspng. The native check is deliberately STRICTER than the Python oracle (Pillow `verify()` then `load()`), not equivalent to it:
  - Every image the oracle refuses must also refuse natively; differential tests prove this on the authored cases.
  - A CRC error in any chunk, ancillary included, is a shared refusal. Pillow's default `verify()` rejects it, since `LOAD_TRUNCATED_IMAGES` is not enabled. The differential tests cover it as a case both sides refuse.
  - The native-only refusals are exactly these six. Each has an authored native test whose image the settings wrapper asserts Pillow's `verify()` and `load()` accept (`tests/export/test_filter_gate_settings.py`):
    - bytes after IEND (`trailing`);
    - an incompletely framed IEND, such as an IEND whose last four CRC bytes are missing (`truncated`); natively, IEND must be complete with a valid CRC;
    - stream data after the complete zlib stream inside IDAT, with every chunk CRC valid (`idat-trailing`);
    - decompressed data beyond the expected scanlines (`extra-scanline`);
    - decompressed data short of the expected scanlines (`missing-scanline`). The inflated size must be exactly the image's scanline bytes, neither more nor less;
    - an image above the fixed limits (`over-width`, `over-height`, and the chunk and ancillary limits).
  - The shared refusals, rejected by Pillow too, are:
    - a CRC error in any chunk (`ancillary-crc`);
    - a zlib stream missing its final Adler-32 bytes (`missing-adler`);
    - an invalid scanline filter type (`invalid-filter`).

  The native decode requires:
  - the PNG signature, then IHDR;
  - every chunk CRC, with errors fatal for critical and ancillary chunks;
  - a complete zlib stream with every scanline decoded;
  - IEND last, with no trailing bytes;
  - width and height in 1..8192;
  - a decoded RGBA8 size of at most 256 MiB;
  - no chunk larger than 64 MiB, and no more than 64 MiB of ancillary chunk data in total.

  Tests cover each limit at its edge and one above it. A truncated, corrupt or partially decodable image refuses.

### F9 per-round hashes

For recording `rk` of the stripped record (settings slots removed), each hash is the lowercase SHA-256 of `core::json::WriteCanonical` (typed canonical JSON) of one array:

- `probe_sequence_sha256`: an array of complete OUTPUT objects, exactly as recorded and in record order: the outputs whose `output_id` matches `s<step>/<name>` with 7 ≤ step ≤ 24.
- `context_readback_sha256`: an array of FRAME objects, one per context boundary of the round in order (r1: `after-create`, `after-setup6`, `pre16-r1`; r2: `after-reopen`, `pre16-r2`). Each frame is exactly `{schema, boundary, condition, outputs}` as the context contract rebuilds it, with `outputs` the boundary's complete output objects in record order.
- `host_readback_sha256`: an array of complete OUTPUT objects from the round's pre16 frame, in record order, whose `args.selector` is exactly `{"role": "host"}` or `{"role": "host", "source": true}`.
- `filter_readback_sha256`: the same, with `args.selector` exactly `{"role": "filter"}` or `{"role": "filter", "source": true}`. The context protocol has no `source: false`; a selector with any other `source` value is refused by the context contract before hashing.

An empty array is hashed as `[]` and is legal only where the trace contract allows it. The store keeps validating only shape, order and links; the gate computes these values itself.

### Starting shape of the H store

Every member of the base projection is classified before mapping. A member is RETAINED (kept typed-identical), MAPPED (its value is set from F evidence only) or REFUSED (any value other than the one stated refuses with `TARGET_CONTEXT_UNREPRESENTABLE`). The mapper never deletes or overwrites unknown content. `ExpectedDestination` copies from the base only RETAINED members and never copies an `extra` object or an unlisted member. Any member, enum value or `extra` key this table does not name refuses.

| Member | Class | Rule |
|---|---|---|
| `versions`, `display`, `export_defaults`, `mesh.import_report` | RETAINED | Unchanged; part of the projection hash. |
| `settings` | REFUSED unless equal | Satisfies `CheckCaptureDomain` and equals the settings derived from F (Legacy, OpenGL, PerVertex, Default, scale 1); empty `settings.extra` and `color_management.extra`. |
| `mesh` | REFUSED unless equal | The plane resource; empty `mesh.extra`. |
| project `extra` | REFUSED unless listed | Holds only the procedural snapshot member(s) holding the H entry, whose other retained snapshot entries are RETAINED; no `filter_source_observations`. |
| texture set | REFUSED unless equal, except `name` MAPPED | Exactly one; resolution 128; exactly one UV tile 1001 with empty `extra`; no mesh maps; `original_name`, `description`, `material_id`, `bake_settings` and `height_to_normal_method` RETAINED; empty `extra`. |
| stack | `id` RETAINED; `name` MAPPED; `channels` MAPPED | Exactly one stack. The channels and formats become F's exactly. A base channel that F lacks may be dropped only when no layer references it; each channel `extra` must be empty. Empty stack `extra`. |
| root layers | REFUSED unless listed | An order-preserving subsequence of `[host Fill, empty Paint]`; anything else, including groups, instances and extra layers, refuses. |
| host Fill (when present) | `uid` RETAINED; `name`, `visible`, `blending`, `active_channels`, `projection` MAPPED; known constructor defaults REMOVED | `fill.source_mode` Split; `active_channels` exactly `{User0}`; `sources` exactly `{User0: ProceduralSource}` equal to the bind of the H signature, plus any subset of the two known constructor defaults below; `mono_source` and `material_source` absent; no `content_effects`; no `mask`; `geometry_mask` the neutral default (type Mesh, `inclusion_list` false, no items, empty `extra`); `symmetry` the neutral default; no `children`; no `instance_source`; `collapsed` false; no `preset_ref`; empty layer and fill `extra`. |
| empty Paint (when present) | `uid` RETAINED; `name`, `visible`, `blending` MAPPED | `core::IsEmptyPaintLayer`; no `mask`; neutral `geometry_mask`; no `children`; no `instance_source`; no `preset_ref`; empty `extra`. |
| missing host Fill or Paint | allocated (ids below) | Every field from F evidence; a neutral default only where F observed that neutral state (geometry mask, symmetry, masks, effects). |

The neutral defaults, and the F leaves that prove each MAPPED field, are listed in code next to the F8 projection, with one authored refusal per row. The owner's classification of the real H store (counts and types only) must fall inside this table before a real run. The table is not widened to fit it.

#### Known constructor defaults on the host Fill (approved, REV401)

The owner's read-only classification of the real H store found three host Fill sources: two constant sources and the procedural `User0` one. After independent review, the following correction to mapping 1 is approved. It rests on these public facts:

- **Origin.** The facade's Fill creation (`InsertDefaults`, `src/python/edits.cpp`) runs `ApplyDefaultSources` (`src/python/stack_sync.cpp`). That function gives every new Fill a uniform `BaseColor` of `float32(0.8)` and a uniform `Height` of `float32(+0)`, both in the `Working` colour space, when the stack has those channels.
- **Bind and evaluation.** `assets bind-snapshot` keeps those other sources. The evaluator reads only active channels (`SourceOf`, `src/evaluator/dag.cpp`).
- **Domain.** The frozen-host domain (`FrozenHostDomainProblem`) stays unchanged: exactly one host source, `User0`.

The rule:

- **Allowed host sources.** `User0` = the procedural H source, plus any subset of these two, and nothing else:
  - `BaseColor` = `UniformColorSource` with components `[float32(0.8)] * 3`, `color_space` `Working`, empty `extra`;
  - `Height` = `UniformColorSource` with components `[float32(+0)] * 3`, `color_space` `Working`, empty `extra`.
- **Conditions.** `active_channels` is exactly `{User0}` and `source_mode` is `Split`.
- **Exact comparison.** Typed canonical comparison applies, so `float32(0.8)` differs from the double `0.8` and `+0` differs from `-0`.
- **Removal.** `ExpectedDestination` removes only these defaults, inside the same `Submit` as the rest of the import. F's stack channels, H's snapshots and census, and the empty Paint are kept.
- **Refusals.** Any other value, type, colour space, `extra`, source or active channel refuses before anything is staged. The removal makes no claim about Painter's own state for those channels.
- **Tests.**
  - All four subsets are accepted: none, `BaseColor`, `Height`, both.
  - Each single mutation refuses: value, double instead of float32, `-0`, colour space, `extra`, another source kind, another channel, an active default channel.
  - A refusal leaves the store byte-identical.

The owner's private checks only confirm that the real store falls inside this rule; they choose no value.

### Filter evidence of the expected destination (slice C4)

`ExpectedDestination` derives the Filter's evidence only from the validated slices, never from old expected values:

- **Descriptor:** `{schema: uzpainter/filter-observation-descriptor/1, role: filter, resource_id, parameters}`. Its parts come from the authenticated recipe steps 16 (`get_parameters`), 17 (`resource_id`) and 18 (`image_outputs`).
  - Each step must be unraised and typed-equal in both rounds.
  - Each must also equal the Filter's pre16 source leaves; `image_inputs` must be empty.
  - `resource_id` is the step-17 identity flattened to `{url, context, name, version}`.
  - The parameters stay in decision 361's scalar codec, typed (int, double and signed zero kept apart).
- **Observations:** exactly `{parameters, resource_id, image_outputs}` with those same values. The Filter reference is the descriptor's observation pin, carrying those parameters.
- **capture/2 `filter` section:**
  - `provenance` is the V1 body:
    - `recorder` = `environment.recorder_version`;
    - `envelope_id` = the admitted envelope;
    - `painter_build_id` = the manifest's `software.painter.build_id`;
    - `recipe_sha256` = recipe A;
    - `resource_query` = recipe step 6's `search`;
    - `authored_inputs` = `[{input_id: plane, sha256: PLANE_SHA256}]`;
    - `receipts` = one `{condition, sha256}` per original recording, where `sha256` is the typed canonical hash (`ObservationKey`) of that complete recording as admitted.
  - `manifest`, `record` and `environment` are the admitted references, with kinds `filter_manifest`, `filter_record` and `filter_environment`.
  - `rounds` is the trace's F9 rounds.
- **Hashes:**
  - the base and prospective projection hashes (without the observation namespace);
  - `ObservationKey(ValidatedHostArtifacts::Identity())`;
  - `ObservationKey({filter_capture, admission_identity})`.

  Together with the role map, these are the expected destination's identity that the seal (slice C5) binds.

### Destination rules the slice C4 code enforces

- **Store-free binding.** `ValidateFilterHostBinding(capture, panels, trace, settings, H)` checks the slices' admission identity, then J1–J4, with no base, store or mapping. The command runs it before any replay lookup. `ExpectedDestination` runs the same code, so the two cannot drift.
- **No silent drop.** Every member C4 replaces from F must hold no unknown data in the base: the host Fill's `projection.extra`, `projection.params`, `projection.uv.extra` and `projection.uv.uv_transformation.extra`, and every host and Paint `Blending.extra`. Otherwise `DESTINATION_STARTING_SHAPE`. `collapsed` must be false on the host and on the Paint. The host reference must be exactly the bind: no `extra`, preset, image input or mask output. Otherwise `DESTINATION_HOST_SOURCES`.
- **Dropped channels.** A base stack channel absent from F is dropped only when no base layer references it: no host or Paint blending entry, no Paint plane, and no host source other than the removed known defaults. Otherwise `DESTINATION_STARTING_SHAPE`.
- **Symmetry.** `is_symmetry_enabled` and `get_symmetry_parameters` are read from both pre16 frames, which must have equal outcomes (the same value, or the same raise type). Enabled must be `False` or raise `ValueError`. Parameters must raise `ValueError`: unraised parameters have no representation here and refuse with `DESTINATION_F_CONTEXT`, never dropped. The destination's neutral symmetry is then the observed state.
- **Blending.** Host and Paint blending come from F for every F stack channel; a raised leaf refuses. The Filter's blending covers every F stack channel:
  - active channels must be unraised;
  - on an inactive channel, the observed state is kept when both frames are unraised, and is absent when both frames raised;
  - any other combination refuses.

### Mapping, deterministic ids and target seal

`ExpectedDestination(F, H, base)` is a pure function that returns the complete prospective project:
- RETAINED members come from the base;
- MAPPED members come from F;
- the six section 7 mappings are applied: host bound to the snapshot like `bind-snapshot`, F projection inside the provider guards, F names and states, the Filter at host Content index 0.

The host Fill and the empty Paint are reused when the starting shape holds them, keeping their ids. Missing nodes are allocated from `base.next_id` in a fixed order: the host Fill (if missing), then the empty Paint (if missing), then the Filter. The Filter id is therefore `base.next_id + (number of nodes allocated before it)`, never assumed to be `base.next_id`. Texture set and stack ids are the base's. The role map holds the native id for the set, stack, host, Paint and Filter, each with the F UID it maps. Inside the transaction, `Edit::AllocateId` is called in the same order and must return exactly the expected ids; anything else refuses.

The only production route to a `VerifiedFilterContext` is the combined private factory and commit `CommitAdmittedFilterObservation(store, document, AdmittedHostCapture, ParsedFilterImportRequest, ValidatedFilterDestination, templates)` (`filter_observation_import_v2.h/.cpp`). No public `VerifyFilterContext` or other constructor exists; the context is built and committed inside this one call, and no token leaves it.

Before building the context, it requires:
- the document attached to this store, with the store's UUID;
- the request's host section to be the admitted H's;
- the destination's H identity to be the admitted H's;
- the request's `expected_base_revision` to equal the document and store revision;
- no observation namespace yet;
- the actual base projection hash to equal the destination's base hash.

It then runs, on the prospective project:
- `VerifyHostCapture`;
- `CurrentFilterObservationContextV2`, whose projection hash must equal the destination's prospective hash;
- `FrozenHostDomainProblem`.

The mapped native roles must equal the prospective nodes. The allocated ids must be consecutive from the base's `next_id` and end with the Filter.

The private seal records:
- the store binding: the transient in-process identity of the owning `ProjectStore` instance (compared in-process, never serialized, hashed or written to a record);
- the target `{project_uuid, revision, base projection hash, Filter id}`, computed from the store and the destination, never from a caller;
- the prospective projection and inventory hashes;
- the native roles and the F source roles;
- the verified H identity;
- the Filter identity: effect, descriptor, observations and capture section, plus a gate identity. The gate identity holds the destination identity, the H admission identity, the request arguments and the allocation ids.

The seal has no public constructor, setter, token or callback. A context sealed for one store instance refuses on any other instance, even one with the same UUID and revision. No persistent file identity is introduced.

Before `Submit`, the commit checks the store binding and the immutable seal.
Inside its one `Submit`, it:
1. checks the current revision, base projection and sealed evidence;
2. applies the expected destination with the same allocation order;
3. requires the projection hash (without the namespace) to equal the sealed one;
4. runs the existing domain, host request, context, native proof, recheck, namespace check and `ObservedFilter` steps.

The proof's projection hash must equal the seal's.

### Operation request and replay scope

`core::OperationRecord` stores only `project_uuid`, `idempotency_key`, `request_hash`, `outcome` and `committed_revision`; no tool, arguments or seal are stored. The operation request is therefore reconstructible from stable inputs alone:

- **tool:** `filter-observation-commit-v2`;
- **arguments:** exactly `{payload_sha256, project_uuid, expected_base_revision}`. `payload_sha256` is the SHA-256 of `core::json::WriteCanonical` of the strictly parsed payload (duplicate keys and unknown fields refuse), not of its raw file bytes;
- **idempotency key:** `filter-observation-commit-v2:` + `ObservationKey(arguments)`; `request_hash` is `RequestHash(tool, arguments)`;
- **outcome:** the store's standard outcome, whose `returned` object is exactly `{entry_key}` (lowercase SHA-256), as the existing commit already reads it.

The seal stays a private in-process recheck and never enters the request.

- **In-process replay (the C++ API, owned with the seal).** Submitting the exact same request object again returns the stored outcome through `DecideAdmission`, which admits a known key before any revision check. Nothing executes again.
- **Command replay (C6, separately specified, limited scope).** After the store-free validation (H artifacts, F1–F9, J1–J4) and before any mapping, the command reads the key with the existing `store::ReadOperation`:
  - A row that does not decode refuses.
  - A found row must have `request_hash == RequestHash(tool, arguments)` and an outcome whose `returned` is exactly `{entry_key}`. The command then reports that entry as the outcome recorded in THIS file: no mapping, proof or execution, and never the document's current binding.
  - With no row and `expected_base_revision` below the store's operation horizon (`store::ReadHorizon`), the outcome is unknown and the command refuses; it never re-executes.
  - With no row, `expected_base_revision` must otherwise equal the current revision; if not, `STALE_PROSPECTIVE_VIEW`. The full import then runs.

  Replay is promised only while the operation row is retained in the same project file. Compaction may rewrite the file and prune operation rows, so replay is never promised beyond the horizon. A moved revision without a retained row refuses rather than re-executing.
- **Saving.** After a committed import the command saves with the existing default (incremental) `Save`, then closes, reopens and runs `ObservedFilter`. It never compacts, saves as or replaces the file.

### Implementation slices (C++, disjoint files; one native window and one `zig build` at a time)

1. **C1, admission and envelope (F1–F4):** `src/procedural/filter_gate_admission.h/.cpp` and `src/procedural/filter_gate_pins.h/.cpp`, plus `tests/export/filter_gate_admission_test.cpp` and the shared `tests/export/filter_gate_test_support.h`. Shipped API (namespace `uzp::procedural`):
   - **Refusals.** `kFilterCaptureInvalid = "F_CAPTURE_INVALID"`; the detail is one fixed code of `filter_gate` (for example `F_SETTINGS_REFERENCES`), or `F_SETTINGS_REGISTRY_DRIFT:<earlier code>` after a refusal. It never carries a value or a path.
   - **`struct AdmittedRef`** `{record_id, kind, sha256, size_bytes}`.
   - **`class OracleStoreReader`**, read-only, with no write path:
     - `static std::expected<OracleStoreReader, ImportRefusal> Open(const std::filesystem::path& root, const std::filesystem::path& registry)`. The root is an existing plain folder: no reparse-point root or ancestor, and no UzPainter checkout ancestor. Its `store.json` is exactly `{schema, hash}`. `registry` is the locator of `parity/envelopes/registry.json`.
     - `std::optional<ImportRefusal> RequireAdmitted(std::string_view build_id, std::string_view golden_id, const AdmittedRef& ref) const`. The ids are validated before any path is built. The closed store entry must equal the ref. It reads the entry only, never the blob.
     - The blob and registry reads are private. Blobs are read only by admission, through handles fenced inside the store root, and are rehashed. The plane is read as the blob of its pinned SHA-256; no `inputs/<sha256>.json` entry is read.
     - Private test seams (a read observer and an action before the final registry read) are empty by default. Only the test-only `FilterGateTestAccess` sets them; it is defined once in the shared test header.
   - **`class AdmittedFilterCapture`**, private constructor. Accessors:
     - `Manifest()` and `ManifestRef()`;
     - `Record()` and `Environment()`;
     - `Refs()` (twelve, kept in the fixed order);
     - `Image(std::string_view record_id)` (bytes only, decoded in C2);
     - `PlaneBytes()`;
     - `Identity()` (manifest, record, environment and registry hashes, envelope id, producer, gate code hash).
   - **`AdmitFilterCapture`.** `std::expected<AdmittedFilterCapture, ImportRefusal> AdmitFilterCapture(std::string_view manifest_bytes, const core::json::Object& manifest_ref, const OracleStoreReader& store)`, under the compiled pins.
   - **Pins.** `filter_gate_pins.h/.cpp` `#embed` the fixed request file and `parity/envelopes/registry.json`. `CompiledFilterGatePins()` selects the approved current envelope `env-a981b586eae7` and refuses when it is absent, and carries the reviewed settings producer. `FilterGateCodeSha256()` hashes the gate sources and embedded pins, LF-normalized.
2. **C2, settings slots, settings contract and full PNG decode (F7):** `src/procedural/filter_gate_settings.h/.cpp`, plus tests. Runs in parallel with C3 once the C1 header is fixed.
3. **C3, trace, context, cross-round comparison and round hashes (F5, F6, F9):** `src/procedural/filter_gate_trace.h/.cpp`, plus tests.
4. **C4, J1–J4, F8 projection, starting-shape predicate and `ExpectedDestination` with deterministic allocation:** `src/procedural/filter_gate_destination.h/.cpp`, plus tests.
5. **C5, the combined private factory and sealed commit:** `CommitAdmittedFilterObservation` in `filter_observation_import_v2.h/.cpp`, with `tests/export/filter_import_v2_test.cpp`.
6. **H admission:** `src/procedural/filter_gate_host.h/.cpp`, with `tests/export/filter_gate_host_test.cpp`.
7. **C6, payload and command:**
   - `src/procedural/filter_gate_request.h/.cpp`: `ParseFilterImportRequest` and the stable operation request `MutationRequestFor`;
   - `src/procedural/filter_import_cli.h/.cpp`: `RunFilterImportCommand` and the private `FilterImportCommandDriver`;
   - the end-to-end authored test `RunFilterImportCommandCases` (in `tests/export/filter_gate_destination_test.cpp`).

Each slice carries authored refusals and test-only differential cases against the Python specification. No slice adds a diagnostic descriptor, UUID, store or proof, and no slice reads old expected 16–18.

The C4 test also covers five inactive-channel cases from four authored two-channel records (User0 and User1), which the wrapper produces through the authored recorder path. The native test derives the cross-round difference from one of those records:
- an observed inactive channel keeps its blending;
- a raised one stays absent;
- a mixed one refuses;
- one that differs between the pre16 frames refuses;
- a raised host blending leaf refuses, even on an inactive channel.

These are authored cases, not observations of Painter.

### Facade replay after a materialized import (shipped tooling, private)

`tools/parity/filter_context_replay.py`, driven by `tests/python/test_filter_context_capture_replay.py`, compares the native facade's Filter getters with independent recordings. It runs only after an import has actually been materialized. It is comparison tooling: it is not an import gate, and it grants no capability.

**Configuration.** The environment variable `UZP_FILTER_CONTEXT_REPLAY_CONFIG` names a private configuration: an absolute file outside the repository, with no symbolic-link or junction ancestor. It is exactly `uzpainter/filter-context-replay/1` with these fields:
- `project` and its `project_sha256`: the original H file after the import;
- `import_binary_sha256`: the SHA-256 of the executable that ran the import;
- `import_request` and `import_report`;
- `oracle_store`;
- `f_manifest` and `old_manifest`.

The project, import request/report and oracle store paths must be outside the repository, without symbolic-link or junction ancestors. The two manifests are public inputs and may reside in the repository. Without the variable, the test SKIPS as `oracle_unavailable`. A skip is never a pass.

**Order.**
1. **Prepare, structural only.** Read the project through SQLite read-only (immutable, `query_only`, journal `delete`). Confirm:
   - the operation row of the stable request key (`filter-observation-commit-v2:` + the typed hash of `{payload_sha256, project_uuid, expected_base_revision}`);
   - the current revision's manifest, decompressed and checked against its stored hash;
   - the entry and its native proof: the proof's binary hash equals `import_binary_sha256`, its projection and inventory hashes equal the context's, and its raster, upload and final hashes are equal.

   The project's file hash is checked before and after.
2. **Actual values first.** A worker opens the project through the real facade and reads the Filter's getters (`get_parameters`, `resource_id`, `image_outputs`) in both conditions, with a trace. It requires all three getters on the source handle retained before reopen to refuse. It never saves or copies the project.
3. **Only then the recordings.** The tool opens the admitted F record and the independent old recording, which must be a different record. It compares the six readbacks, typed. The project's file hash must be unchanged at the end.

Private reports (the runner envelope, the actual values, the comparison and any error trace) are written only to the test's private work folder. A failure prints only `F_REPLAY_FAILED`, and refusals carry fixed `F_REPLAY_*` codes. A passing comparison promotes no capability and does not by itself close item 2.6j.
