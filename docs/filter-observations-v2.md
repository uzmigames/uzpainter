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

Only after independent fixture construction may old step17 identity and old16/18 values be read for strict comparison. Drift fails item2.6j; it never selects constructor values, another capture recipe or a fitted raster.

## 7. Closed frozen-host migration

H isolation and F target are two authenticated contexts related by the following enumerated mappings. Their context hashes are not expected to equal. No caller-supplied `compatible` flag or free-form allowed-differences list is accepted.

1. **Frozen source substitution.** H scalar B becomes the actual project-private snapshot plane. `SnapshotSourceProvider::Resolve` and `CpuTileStore::Upload` copy its Float32 bits. Destination keeps the genuine snapshot reference, signature, metadata, plane/version/root. Original ResourceID is provenance, never an executable archive alias.
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
