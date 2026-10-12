# 122. The recipe dump digests only output-determining state, keeps the rebuild state beside it, and a mesh stores the files it reads

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase2.1_recipe-dump-manifest-blocks, phase2.2_recipe-and-diagnostics, phase2.6_mcp-typed-tool-families, phase2.1_supervisor-ipc-worker, phase4.1_nodes-paint-layers, phase3.1_assets3d-cutover, phase1.17_export-publication-receipts, phase1.6_mesh-reload, phase5.6_gate-g5

## Context

phase2.1 delivers `uzpainter.project.dump_recipe()`, `uzpainter inspect`, the rebuild path and the manifest export block (SAV-03, SAV-04, INT-20, INT-21, ARC-11). Its spec: the digest is the same across runs, sessions and save/reopen, and changes **only** when output-determining state changes; inert state (selection, a group's collapse) leaves it alone; a project rebuilt from a dump and its resources exports byte-identical maps.

Measured facts:

- **Explicit values.** The manifest already stores every node parameter explicitly: inserts store Painter's effective defaults (decision 115). The one default the evaluator reads but the project does not store is each stack channel's base value, which comes from the shipped template the project records (decision 116).
- **Ids.** Every node, set, stack, tile and resource entry has a persistent id. `sync_stack` rebuilds its group with new ids for identical content.
- **What is read.** Evaluation, export and mesh derivation read:
  - the settings `normal_map_format`, `tangent_space`, `workflow`, `color_management` and `template`;
  - the mesh bytes and their import report (`$mesh` reads the file name there);
  - a set's name, `original_name` (`$sceneMaterial`), `material_id`, resolution, tiles and `height_to_normal_method`;
  - a mesh map's resource, format, colour space, `invalid` flag and `declared_convention`;
  - the stack channels and their formats, and the layer stack.
- **What is not read.** Nothing reads:
  - `display`, `export_defaults` and `metadata`;
  - the settings `default_resolution`, `mesh_unit_scale` (the import report keeps the scale used), `import_cameras` and `auto_unwrap`;
  - resource entry names, origins and times, and `mesh.source`;
  - a set's `description` and `bake_settings`;
  - a mesh map's `invalid_report` and the rest of its provenance;
  - a channel's `label` (decision 116) and a node's `collapsed` and `preset_ref`.

  Selection and the active stack are session state.
- **Paint.** Paint layers are a release gap. Their planes bind content hashes (`plane_versions.chunk_root`) whose bytes are not resources.
- **External glTF buffers.** A glTF's external buffers were read beside the import's origin and never stored. A recipe plus its resources could not rebuild such a mesh, and the project itself was not self-contained (SAV-01, 09 §2: portable mode embeds every dependency).
- **MCP.** Neither the MCP worker pipe (phase2.1_supervisor-ipc-worker, nothing committed) nor the tool registry exists on main. phase2.6 lists the `project_recipe` tool and, as its item 2.9, the `uzpainter://project/recipe` resource.
- **Export block.** Export receipts already carry the Assets3D v2 `$defs/export` block (phase1.17, decision 097). Writing the recipe into Assets3D manifests belongs to phase3.1 item 2.7.

### Model panel, one round (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5)

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C1. The recipe is the manifest without a listed set of keys, with references as pointers; keep `preset_ref`, bake settings, `description` and unknown keys when in doubt | DISAGREE: keeping unread state breaks "only output-determining" | PARTLY: drop those three and unknown keys | PARTLY: same |
| C2. Each channel carries its float32 base value; an unknown template is an error | PARTLY: share the resolver between dump and inspect | AGREE: pin the float form | AGREE |
| C3. The ARC-11 header sits outside the digest; `evaluator_profile` is also in the body | PARTLY: justify leaving out `compat_profile` | AGREE | PARTLY: the profile must flip the digest |
| C4. `inspect --recipe` with the host's resolver | PARTLY: test the real CLI under concurrent access | AGREE | PARTLY: wire the resolver explicitly |
| C5. Rebuild in one transaction from hash-named resource files, with fresh ids, the support check, and paint refused | PARTLY: keep the file name and `original_name`; preflight first | PARTLY: the `$mesh` name must survive | AGREE |
| C6. Item 2.4 is a scope split to phase2.6 | PARTLY: record it as transferred, not done | AGREE | AGREE |
| C7. Item 2.6 is delivered by phase1.17, plus a test pinned to Assets3D | PARTLY: never only skip | PARTLY: vendor the pin, fail on drift | AGREE |

### Codex source review (coordinator, while in progress)

- `ProjectFromRecipe` read only `schema`, `recipe` and `digest`. The header must be required and checked.
- `import_cameras` (and so every unread setting) was in the body. Two projects with the same maps had different digests. Rebuild data must be kept, but outside the digest.
- External glTF buffers: capture them as hashed resources rather than refuse. SAV-01 does not permit a refusal.
- Projects written before the capture must keep working: re-derive beside the origin, and let a reload replace a mesh it cannot re-derive.
- Receipts must name the captured buffers, so a reload that changes only the `.bin` invalidates them.

## Decision

1. **The dump.** `{schema: uzpainter/recipe/1, revision, evaluator_profile, compat_profile, app_version, resource_hashes, recipe, rebuild, digest}` (`src/uzp_core/manifest/recipe.h`, `MANIFEST.md` §8, `schema/recipe.schema.json`). The id-less document of the revision is split in two:
   - **`recipe`, the body.** Every key evaluation, export or mesh derivation reads, and nothing else. Ids and unknown keys are dropped. Anchor and instance references become JSON pointers inside the texture set. Paint planes become `{chunk_root}`. Each channel carries its float32 `base`. `settings.template` is always stated. `resources` lists the referenced hashes as `{mime, size}`. `digest` is the SHA-256 of the body's canonical JSON, the same in C++ and Python.
   - **`rebuild`, outside the digest.** `{pointer: value}` for the unread state listed above, plus `resource_catalog` (every stored entry without its id), `painter_reference` and `mesh.source`. A rebuild is therefore lossless but for ids.
   - **The header.** ARC-11, outside the digest. `revision` moves on inert commits. `app_version` is the running build. The compatibility profile names the API surface, not pixels. `evaluator_profile` is also in the body (C3).
2. **Rebuild.** `ProjectFromRecipe` checks the schema, the digest and the complete ARC-11 header (`HeaderFromJson`): `kCompatProfile`, and the body's evaluator profile and hashes. It then:
   - applies only rebuild-only pointers that name a place the body holds;
   - gives fresh ids and resolves the pointers;
   - refuses a channel base that differs from this build's (`ValueError`);
   - refuses paint plane content (`NotYetSupported`, phase4.1_nodes-paint-layers item 2.7, which owns "recipe-dump entries for planes and content versions");
   - requires the rebuilt body and rebuild values to equal the dump's.

   `uzpainter.project.rebuild_from_recipe(recipe, resources_dir)` commits it into a new untitled project in one transaction:
   - every stored resource must be in `resources_dir`, named `<sha256>` with any extension (the `export-bundle` `res/` layout), and must hash to its name;
   - the mesh must re-derive from those bytes alone, never from an origin;
   - `RequireSupported` runs on the whole project.

   A recipe without a rebuild block (a migration) takes a new project's defaults.
3. **Inspect.** `UzPainter.exe inspect <file> --recipe [--revision N]` prints the dump through a read-only connection, with no lock and no GPU. The report's `recipe_digest` is `{available: true, digest}`. The host passes its recipe resolver (`python::HostRecipe`, the installed templates, loaded on first use), the same one `dump_recipe` uses (C2, C4). The store's own test executable has no resolver and says so.
4. **External mesh files (SAV-01).**
   - The glTF importer reads external buffers itself. The project stores them as resources (usage `mesh-file`, named by URI) and lists them in the import report as `external_files [{uri, sha256, size}]`. `RederiveMesh` reads them from the store.
   - A report without `external_files` (a project written before this) re-derives beside the origin, as before, checked against the stored hashes. When the file is gone, or for a rebuild, it raises `MeshFileMissing`.
   - A reload then replaces the mesh without comparing (`ApplyReloadWithoutCurrent`):
     - each set keeps its material by name or `material_mapping`, otherwise `MaterialMappingError` before any change;
     - every mesh map and mesh geometry mask of a kept set is invalidated with the reason;
     - the new mesh's files are stored.
   - Receipts list the mesh's files (`core::MeshResourceHashes`). A reload invalidates the receipts of every mesh file the new mesh no longer reads, including a `.bin` whose UVs changed under an identical `.gltf`.
5. **Scope splits (decision-069 pattern).**
   - **Item 2.4.** The native operation behind `project_recipe` and `uzpainter://project/recipe` is `python::DumpCurrentRecipe`. Registering them is transferred to phase2.6_mcp-typed-tool-families: the Project tool family and item 2.9. It is not implemented here, because the worker pipe and the registry do not exist yet.
   - **Item 2.6 / 3.5.** These were delivered by phase1.17 as `manifest_export` (decision 097). This task adds a test that pins the SHA-256 of the copied `$defs` on every lane and recomputes it from Assets3D commit `b14511b` when the checkout is present (C7).
6. **Capabilities.** `uzpainter.project.dump_recipe` and `rebuild_from_recipe` are `pending-evidence` (decision 112): UzPainter-only, accepted or not on their contract tests at gate G5.

## Alternatives Considered

- **The whole manifest as the recipe.** Rejected. Ids, names and inert state would move the digest.
- **Uids in the body.** Rejected. `sync_stack` and every rebuild allocate new ids for identical output.
- **Refusing external glTF buffers.** Rejected: SAV-01 and 09 §2 require the dependency closure.
- **Writing the recipe into every export generation.** Not done. The Assets3D manifest blocks are phase3.1's (item 2.7), and the receipt already names its revision.

## Consequences

- The digest is identical for identical output, a rebuilt project included (`tests/uzp_core/test_recipe.py`, `tests/python/test_pyapi_recipe.py`).
- Migration from Painter (owner Q6, decision 020) produces a recipe body and replays it through `rebuild_from_recipe`.
- phase2.6 registers `project_recipe` and the resource on `DumpCurrentRecipe`.
- phase4.1 item 2.7 adds plane content to the dump and the rebuild.
