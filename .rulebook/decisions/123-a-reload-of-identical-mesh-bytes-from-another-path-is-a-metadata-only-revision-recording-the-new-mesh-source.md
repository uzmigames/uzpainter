# 123. A reload of identical mesh bytes from another path is a metadata-only revision that records the new mesh source

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.6_mesh-reload, phase1.24_python-api-facade, phase1.23_pyapi-pipeline-adapter, phase2.1_recipe-dump-manifest-blocks

## Context

- **What phase1.6 promised.** An identical reload means "no set changes, all texels unchanged, nothing invalidated". Its native case `identical_reload` expects the transaction to be a `no_op`. A transaction is a no-op only when the whole project equals its base.
- **What phase1.24 added.** Decisions 115 and 116 added `MeshReference.source`, the absolute path the last create or reload imported the mesh from.
  - Export jobs report it as `mesh_path`, and the Assets3D adapter rebases each receipt's mesh entry on it. Decision 118 carries the project path the same way.
  - A resource entry with the same bytes and file name is deduplicated, so its `origin` keeps the first import's path. That is why `mesh.source` exists separately.
- **The conflict.** Reloading byte-identical bytes from another folder changes only `mesh.source`, so the reload commits. `identical_reload` reloads from another folder, and it has failed on main since `2ace938`.
- **No effect on the recipe digest.** The digest of decision 122 excludes `mesh.source`, which is rebuild-only state.

Options:

- **(a) Metadata-only commit.** The revision advances, the new source is recorded, and nothing else changes. A reload from the same path stays a `no_op`.
- **(b) No commit when the bytes are equal.** The old source stays.

### Model panel, one round (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5)

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| D1. (a) is correct. Under (b), later exports name a path the user no longer imports from, a silent provenance error. | AGREE | AGREE | AGREE |
| D2. (a) keeps phase1.6's substance, so only the "no-op" wording is amended. | PARTLY: the transaction semantics change too, so amend explicitly and test the source-only commit and the same-path `no_op` | AGREE: test both cases | AGREE |
| D3. A metadata-only revision is an acceptable cost, and `needs_saving()` turning true is correct. | PARTLY: the existing metadata-only commits should be verified | AGREE: document the extra revision | AGREE |

On D3, `Metadata.set` and `GroupLayerNode.set_collapsed` already commit through `Mutate` (`src/python/bind_project.cpp`, `bind_layerstack.cpp`).

## Decision

1. **(a).** A reload of byte-identical mesh bytes from another path commits one revision. The revision is metadata-only: `mesh.source` becomes the new absolute path.
   - No set, texel, binding, geometry mask, procedural node or receipt changes.
   - The report's `changed` and invalidation lists are empty.
   - A reload of the same bytes from the same path is a `no_op`.
   - The code already behaves this way. Nothing in `src/mesh` changes behaviour.
2. **phase1.6's wording** is amended to "no pixel or derivation change": the archived item 3.1, `docs/architecture/12-mesh-import.md` §7 and `src/mesh/reload.h`.
3. **`identical_reload`** checks both cases:
   - from another folder: committed, revision + 1, and the project equals its base except `mesh.source`;
   - from the same file again: `no_op` with nothing changed.

## Alternatives Considered

- **(b), skip the commit for equal bytes.** Rejected (D1): exports after a reload from a moved folder would name the old path.
- **Change the test to reload from the same folder.** Rejected: it hides the conflict instead of settling it.

## Consequences

- `needs_saving()` becomes true after a cross-path identical reload. Saving writes the new source.
