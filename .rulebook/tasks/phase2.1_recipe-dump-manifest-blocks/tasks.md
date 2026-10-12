## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.25_pilot-wand — not accepted: phase1.25 still has implementation open (items 2.6 and 2.7) besides its recordings and CI; this task's work is host preparation, and the task stays open and unaccepted until phase1.25 and G1 are accepted

## 2. Implementation
- [x] 2.1 Recipe JSON schema covering every output-determining field of `03-…` §7 plus revision, profiles, app version and resource hashes — `src/uzp_core/schema/recipe.schema.json`, `src/uzp_core/manifest/recipe.h` (decision 122)
- [x] 2.2 `uzpainter.project.dump_recipe()` with canonical JSON and SHA-256 digest — the body holds only output-determining state, the `rebuild` block the rest, outside the digest
- [x] 2.3 `uzpainter inspect <file.uzp>` printing the recipe without opening the project (no GPU, no lock) — `inspect --recipe`; the report's `recipe_digest` is available
- [x] 2.4 Worker handler for the MCP `project_recipe` tool and `uzpainter://project/recipe` resource — scope split (decision 122 §5): the native operation `python::DumpCurrentRecipe` is delivered here; registering the tool and the resource is transferred to `phase2.6_mcp-typed-tool-families` (Project tool family, item 2.9), because neither the worker pipe (`phase2.1_supervisor-ipc-worker`) nor the registry exists on main; not implemented here
- [x] 2.5 Rebuild path replaying a dump and its referenced resources into a new project through the native API — `uzpainter.project.rebuild_from_recipe` over `core::ProjectFromRecipe`, one transaction; a glTF's external buffers are stored with the mesh so it rebuilds from the resources alone (SAV-01); paint plane content stays `NotYetSupported` (`phase4.1_nodes-paint-layers` item 2.7)
- [x] 2.6 `exportacao` block (`fontes`, `saidas`, `momento`, `preset`, `mapas`, `comparacao`, `evidencias`, `pendencias`) written with every export receipt — delivered by `phase1.17` as `manifest_export`, the Assets3D v2 `$defs/export` that replaced v1's `exportacao` (decision 097); this task pins the copied definitions to Assets3D `b14511b`

## 3. Tests
- [x] 3.1 Dump schema tests on synthetic projects covering every node, effect and source kind available in Phase 2 — `tests/uzp_core/test_recipe.py` (every-kind fixture), `tests/python/test_pyapi_recipe.py`
- [x] 3.2 Digest determinism: repeated dumps, a new session and save/reopen give the same digest; inert state (selection, collapsed) does not change it; an output-affecting edit does — native `recipe_digest_invariance`, `test_dump_recipe_is_deterministic_and_moves_only_with_the_output`
- [x] 3.3 `inspect` equals `dump_recipe()` for the same revision and runs without GPU or project lock — `test_inspect_prints_the_recipe_dump_of_a_project_open_elsewhere` (`UzPainter.exe`), native `inspect_while_locked`
- [x] 3.4 Rebuild from dump on a synthetic fixture: exports byte-identical to the original's — `test_rebuild_from_recipe_exports_byte_identical_files`, `test_a_gltf_with_an_external_buffer_is_stored_and_rebuilt_without_its_folder`
- [x] 3.5 `exportacao` schema test on export receipts — `test_receipt_schema_and_fields` (phase1.17) and `test_receipt_schema_copies_the_pinned_assets3d_export_block`

## 4. Acceptance
- [x] 4.1 Every §3 test green; results attached to `phase2.2_recipe-and-diagnostics` — `parity/reports/phase2/recipe-dump-manifest-blocks.md`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation — `src/uzp_core/MANIFEST.md` §8, `src/python/PYAPI.md`, `src/store/STORE.md`, `03-…` §7, `09-…` §6, `12-…`, `src/export/EXPORT.md`
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass — the affected CPU tests (report above); no GPU test is affected
