# `phase2.1_recipe-dump-manifest-blocks`: local run

This task is a child of `phase2.2_recipe-and-diagnostics` (P2-RECIPE; `docs/architecture/03-project-model.md` §5, §7; SAV-03, SAV-04, INT-20, INT-21, ARC-11). This report is its evidence, attached to `phase2.2_recipe-and-diagnostics`. Decision 122. Key reference: `src/uzp_core/MANIFEST.md` §8.

Run on 2026-10-12, branch `wt/phase2.1-recipe-dump`, on the owner's machine. CPU only: no test here uses a GPU, and no Painter recording is involved.

**Result.**

| Item | Test | What passed |
|---|---|---|
| 3.1 | `tests/uzp_core/test_recipe.py` (native `recipe_dump_fields`) | The every-kind fixture's dump validates against `recipe.schema.json`. It covers every node, effect and source kind and both mesh-map provenances. The schema refuses an id, an unknown key and a uid reference. In `tests/python/test_pyapi_recipe.py`, the dump of a stack built through the native API validates too. |
| 3.2 | native `recipe_digest_invariance`; `test_dump_recipe_is_deterministic_and_moves_only_with_the_output` | **Same digest:** repeated dumps, save and reopen, and a new process. **Unchanged by inert or unread state:** a group's collapse (a commit), the active stack, the facade's selection, `import_cameras` and the other unread settings, ids, entry names, metadata, display, unknown keys, and a plane's store version of the same content. **Moved by output edits:** opacity, visibility, name, colour, alias, template, evaluator profile, the invalid flag and root order. The digest equals Python's SHA-256 of the canonical body. |
| 3.3 | `test_inspect_prints_the_recipe_dump_of_a_project_open_elsewhere` (`UzPainter.exe`); native `inspect_while_locked` | While a script holds the project, `inspect --recipe` prints exactly `dump_recipe()`'s JSON, and the report's digest is the dump's. The holder's lock is untouched, it commits afterwards, and no GPU is used. |
| 3.4 | `test_rebuild_from_recipe_exports_byte_identical_files`; `test_a_gltf_with_an_external_buffer_is_stored_and_rebuilt_without_its_folder`; native `recipe_rebuild` | **Rebuild:** the rebuilt project has the dump's digest and rebuild block, and every exported file is byte-identical to the original's. A glTF whose `.bin` and folder are gone re-exports and rebuilds from the stored resources, and its receipt names the buffer. **Refused before anything exists:** an open project, a missing or wrong resource file, a tampered body, another build's base values, a bad pointer, an incomplete ARC-11 header and paint content. |
| 3.5 | `test_receipt_schema_and_fields` (phase1.17); `test_receipt_schema_copies_the_pinned_assets3d_export_block` | Receipts carry the Assets3D v2 export block. The copied definitions hash to the value pinned from Assets3D `b14511b`, recomputed here from that commit. |
| SAV-01 | native `gltf_external_buffer` (`tests/mesh/test_mesh_reload.py`) | **Current projects:** the buffer is stored and listed, and re-derivation uses the stored copy. **Projects written before the buffer was stored:** they re-derive beside their origin. Once the file is gone, the result is `MeshFileMissing`, and a reload replaces the mesh without comparing. **Receipts:** a reload that changes only the `.bin` invalidates the old buffer's receipts. |

**Counts.** First batch: 47 tests, 43 passing, 4 failing. All four were fixed and re-run by node id, and they pass:

- two script bugs in `test_pyapi_recipe.py`;
- `identical_reload` (decision 123, below).

Second batch: 36 of 36 pass. It covered `test_pyapi_native.py` and `test_capability_conformance.py` (later-phase calls, templates, reload, export, public symbols, pending evidence, release gaps), all of `test_export_publication.py`, and the rebuild test. The CLI test above passes. The `uzp-core-tests` native cases pass, 14 of 14.

**Found on main, settled by decision 123.** `tests/mesh/reload_test.cpp` `identical_reload` has failed since `2ace938`. phase1.6 called an identical reload a no-op, but decision 116 now records the folder a reload imports from as `mesh.source`. Reloading identical bytes from another folder therefore commits. Decision 123 (model panel, one round) keeps that behaviour. It is a metadata-only revision: the new `mesh.source` is recorded, because export provenance names it, and no pixel or derivation changes. A reload from the same path stays a `no_op`. The case tests both, and phase1.6's wording is amended.

**Open, by scope split (decision 122 §5).**

- The MCP `project_recipe` tool and the `uzpainter://project/recipe` resource are registered by `phase2.6_mcp-typed-tool-families`, on `python::DumpCurrentRecipe`.
- Paint plane content in the dump and the rebuild belongs to `phase4.1_nodes-paint-layers` item 2.7.
- The wand rebuild (the DAG gate) is `phase2.2_recipe-and-diagnostics` item 2.1.
