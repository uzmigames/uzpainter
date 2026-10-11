# 03 — Project model

Implements D3 (document part) and parts of D8/D9 (`05-resolution.md`). Requirements: PRJ-01…10, RES-01…04, BAK-01, BAK-06, LAY-06, LAY-07, LAY-13, SAV-01…04, NFR-08 (`docs/prd.md`). Painter facts come from the public API documentation (`PAINTER\resources\python-doc\**\*.html`) and black-box observation. `docs/analysis/substance-parity/02-layer-stack-model.md` and `05-project-and-spp.md` are quarantined in the approved-source index, `docs/approved-sources.md`, and are historical context only.

## 1. Containment

```
Project
├── settings: normal_map_format (OpenGL|DirectX), tangent_space (PerVertex|PerFragment), workflow (Default|UVTile),
│             default_resolution, mesh_unit_scale, color_management {mode, config_hash, working_space, io_rules},
│             import_cameras, auto_unwrap (release gap: recorded, rejected at import)
├── mesh: resource ref (original bytes), import report, texturing mesh derived data (not stored; re-derived)
├── texture_sets[]: TextureSet { id, name, original_name, description, material_id, resolution,
│     uv_tiles[] (Default workflow: the single tile 1001), mesh_maps{usage → MeshMapBinding},
│     bake_settings {common, detail, per_baker}, stacks[] }
│     └── Stack { id, name ("" for the ordinary stack), channels{type → {format, label}}, root_layers[] }   (04-…)
├── resources{sha256 → ResourceMeta {mime, size, name, usage, origin, imported_at, color_space}}
├── display: environment ref + rotation/exposure/opacity/blur, color LUT ref, tone_mapping (Linear|ACES),
│            shader {id, hash, parameters}, cameras[], background, shadows, post-effects (all off by default);
│            values limited to the fixed render pipeline (decisions 038, 042; see below)
├── export_defaults (Painter exporter settings equivalent)
├── metadata{context → {key → json}}            (project.Metadata)
└── versions: format_version, app_version, evaluator_profile, compat_profile ("painter-12.1-api-0.3.7"), painter_reference {build, recorded_from}
```

Display state covers only the fixed render pipeline: the Assets3D render comparison standard (approved source `U-A3D-RENDERSTD-2`: v2 common block, `ref_match` v3, `base_color` diagnostic; decision 038). The fields stay so the documented `substance_painter.display` symbols keep working (decision 042), but each field accepts only the pipeline's values, and any other value fails with an explicit unsupported-value error:
- display transform: OCIO with Painter's substance config and the view `Default - sRGB`; `tone_mapping` does not apply to a colour-managed project, and Legacy `Linear`/`ACES` are not supported;
- colour LUT: none; post-effects: off;
- shader: Painter's default `open-pbr` instance at its default parameters;
- environment: Linear, exposure 0, opacity 0, blur 0, infinite-sphere dome, no ground, the preset's clear colour and shadows; rotation 0, or the `ref_match` per-view rotation;
- cameras: free.

Identity: every node, set, stack, tile and resource has a 64-bit id persisted in the file (UzPainter guarantee; Painter promises only an in-session integer — `substance-parity-astra-review.md` V03, historical context; confirmed through the documented API by the Tier 0 probes, P0-TIER0). Names are not unique (Painter semantics); the API resolves by id, and name lookups return all matches. Name-addressed mutations (LAY-06) are idempotent within an explicit `{project, set, stack, parent}` scope: an ambiguous match fails before mutation and lists the candidate ids; repeating the same named operation does not create duplicate nodes. Tests cover ambiguity and repeats as well as save/reopen.

## 2. Texture sets, stacks, channels

- One texture set per mesh material, in file order; material identity is separate from object/group identity (`12-mesh-import.md`). Names must be unique and may be renamed; `original_name` keeps the import name.
- Resolution per set: power of two, 128–8192; the engine thread checks the VRAM budget at creation (`13-engine-integration.md` §6) and refuses with an explicit error rather than failing later.
- Workflow `Default` (one tile) in v1; the data model carries `uv_tiles[]` so `UVTile` can be enabled without a schema change (release gap, `roadmap.md` Phase 4).
- A stack holds at most one channel per `ChannelType` (OpenPBR names with the legacy aliases, as the public `textureset` API documentation lists them; `02-layer-stack-model.md` §6.1 is historical context); each channel has a `ChannelFormat` among the nine Painter formats (`sRGB8, L8, RGB8, L16, RGB16, L16F, RGB16F, L32F, RGB32F`). Default channel sets and formats per template are observed in Tier 0; the captures are private oracle records (`14-parity-testing.md` §6). The template JSON UzPainter ships is authored by UzmiGames from documented semantics, with a provenance record per entry (public source, or the hash of the private observation it must equal); it is never generated from a capture and is checked against the captures in a local run on the owner's machine (decision 028). A project records its channels explicitly.
- Material layering (several named stacks) is modelled but a release gap until its template is authored and verified.

## 3. Resources

- Imported bytes are stored unmodified and addressed by SHA-256; decoding happens into a RAM/VRAM cache keyed by (hash, requested format). Deduplication is by content; two imports of identical bytes share one blob but keep separate `ResourceMeta.name` entries.
- URL form for compatibility: `resource://project/<name>?version=<sha256>` (valid across sessions and machines); `ResourceID.from_url`, `from_project`, `from_session` resolve against the project; `session` resources are stored like project resources but flagged non-persistent.
- Procedural assets (`05-procedural-content.md`) are resources too: `uzasset://<family>/<id>@<version>`; the project pins the version.
- Environments (HDRIs) are stored as bytes + hash; a display preset that names a missing hash fails explicitly (RES-03).

## 4. Mesh maps

`MeshMapBinding { usage, resource sha256, format, color_space, provenance }` where provenance is one of:
- `imported {source_path, source_sha256, declared_role: geometry_only|combined, declared_convention: OpenGL|DirectX, units}`;
- `baked {baker_version, backend: embree|dx12_rt|vulkan_rt, settings_hash, high_meshes[] sha256, cage, mesh_hashes {positions, uvs, corner_normals, triangulation}, effective_normalization (e.g. curvature bounds actually used)}`.

A mesh reload compares the stored mesh hashes with the new mesh and marks bindings `invalid` (kept, flagged, never deleted) with the changed-region report (`12-mesh-import.md` §7). Generators read mesh maps by usage; an invalid binding makes dependent evaluation fail loudly until re-baked or re-imported.

## 5. Revisions and snapshots

- The document is a persistent (copy-on-write) structure; a revision snapshot is cheap and immutable. The evaluator, exporter and renderers work on snapshots only.
- `revision` increments per committed transaction; a named **checkpoint** points at a revision; `previous` always points at the checkpoint before the current one (SAV-02).
- Every result record (`ExportReceipt`, `CaptureReceipt`, `BakeReceipt`, recipe dump) carries `{revision, evaluator_profile, compat_profile, app_version, resource_hashes}`.

## 6. Transactions

- One API call = one transaction under the document lock. Composite operations (`sync_stack`, `insert_smart_material`, `insert_smart_mask`, `apply_smart`, recipe replay) build their subtree detached and attach it in one step; on failure nothing is attached and the result lists what would have changed.
- Each committed transaction persists its idempotency record atomically with its revision (`09-project-file-format.md` §4).
- `sync_stack` (LAY-07) rebuilds only the named root group; other root groups are hidden, never deleted, unless an explicit supported option preserves their visibility. Tests check that unrelated roots and resources survive and only the addressed group is rebuilt.
- A failed individual mutation leaves that mutation unapplied. A script exception may follow previously committed calls; its error receipt reports the last committed revision and the partial changes. Atomic multi-call execution is available only through an explicitly declared native `Transaction` (`10-python-api.md`).
- A transaction's result enumerates created/modified/removed/hidden node ids and resource hashes imported or skipped (QG-03).
- `ScopedModification` (facade) batches evaluation invalidation, exactly as Painter groups recomputation; it does not provide rollback (Painter does not either: the public API documentation describes `ScopedModification` as grouping computation and documents no undo; `substance-parity/08-review-response.md` F04 is historical context).

## 7. Recipe dump and inspect

`uzpainter.project.dump_recipe()` returns the manifest subset that fully determines output: per node type, name, visibility, channels, per-channel blend/opacity, sources with values and colour spaces, resource hashes and aliases, projections and symmetry, effects and parameters, mask background/enable, geometry masks, procedural parameters and asset versions, effective defaults, `evaluator_profile`, plus a deterministic digest (SHA-256 of the canonical JSON). The same JSON is `uzpainter inspect <file.uzp>` without opening the project and the MCP resource `uzpainter://project/recipe` (INT-20, SAV-03). Rebuilding a project from a dump plus the referenced resources must reproduce identical exports (SAV-04, tested in Tier 1 on tunic v10). Migration from Painter uses the same rebuild path (owner Q6, decision 020): the project's state is read through Painter's documented API while Painter is installed and replayed into a new project; output equality is the acceptance; there is no `.spp` reader (`09-project-file-format.md` §5).
