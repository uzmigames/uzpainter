# Proposal: phase1.1_docmodel-types-manifest

## Why
The project model needs concrete, persistent types for projects, texture sets, stacks, channels, layers, effects, sources, resources, mesh-map bindings and versions, with 64-bit ids that survive save/reopen (Painter only promises in-session ids), and a canonical JSON manifest that is the public schema of the `.uzp` file. Requirements: PRJ-02, PRJ-03, PRJ-05, PRJ-06, RES-01…RES-04, BAK-06, LAY-06, LAY-13, NFR-08, ARC-11 (`docs/prd.md`). Implements the document part of D3 (decision 005) in `docs/architecture/03-project-model.md` and `docs/architecture/04-layer-stack-and-compositing.md` §1, the operation records of D1/ARC-02 (decision 003) in `docs/architecture/02-runtime-topology.md` §3 and `docs/architecture/09-project-file-format.md` §4, and the capability manifest of D2 (decision 004, amended by decision 019: brush strokes out of scope) in `docs/architecture/10-python-api.md` §3. Child of `phase1.3_document-model` (P1-DOCMODEL).

## What Changes
- `src/uzp_core/types/`: Project settings (normal map format, tangent space, workflow, default resolution, mesh unit scale, colour management, import cameras, auto-unwrap recorded), mesh reference, `TextureSet` (id, name, original name, description, material id, power-of-two resolution 128–8192, `uv_tiles[]` with the single tile 1001, mesh-map bindings with `imported`/`baked` provenance and an `invalid` flag, bake settings, stacks), `Stack` (at most one channel per `ChannelType`, each with one of the nine `ChannelFormat`s), the layer/effect/source model of `docs/architecture/04-layer-stack-and-compositing.md` §1 (every node, effect and source kind, paint planes as `plane_id` references), resources keyed by SHA-256 with `ResourceMeta`, resource URLs `resource://project/<name>?version=<sha256>` and `uzasset://<family>/<id>@<version>`, display state, export defaults, metadata, versions (`format_version`, `app_version`, `evaluator_profile`, `compat_profile = "painter-12.1-api-0.3.7"`, `painter_reference`).
- 64-bit persistent ids for every node, set, stack, tile and resource.
- Model validation: the insertion rules of the twelve documented `NodeType`s (compare mask, colour selection and smart masks only in mask stacks; groups, smart materials and instances only in the hierarchy), acyclic anchor references (`ValueError` on a cycle).
- `src/uzp_core/manifest/`: canonical JSON writer/reader (deterministic key order, number formatting, UTF-8), SHA-256 digest of the canonical form, unknown keys preserved verbatim; `src/uzp_core/schema/manifest.schema.json`.
- The result-record header `{revision, evaluator_profile, compat_profile, app_version, resource_hashes}` carried by every export, capture, bake and dump receipt (ARC-11).

## Dependencies
- DAG input of the parent: `phase0.2_parity-contract`.
- Parent: `phase1.3_document-model`. Siblings building on this child: `phase1.2_docmodel-transactions`, `phase1.2_docmodel-capability-manifest`.

## Acceptance
Part of the P1-DOCMODEL gate: manifest round-trip tests pass for fixtures covering every type, and the canonical digest is stable.

## Impact
- Affected specs: `document-model`
- Affected code: `src/uzp_core/types/`, `src/uzp_core/manifest/`, `src/uzp_core/schema/manifest.schema.json`, `tests/uzp_core/`
- Breaking change: NO
- User benefit: Persistent ids and a canonical, schema-checked manifest, so name collisions and save/reopen never change node identity.
