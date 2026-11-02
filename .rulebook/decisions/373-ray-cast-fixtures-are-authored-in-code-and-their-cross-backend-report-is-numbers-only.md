# 373. Ray-cast fixtures are authored in code and their cross-backend report is numbers only

**Status**: accepted
**Date**: 2026-11-02
**Related Tasks**: phase3.2_vulkan-ray-tracing

## Context

Items 2.10 and 2.12 of `phase3.2_vulkan-ray-tracing` ask for ray-cast fixtures "under `parity/manifests/`" and a cross-backend report under `parity/reports/phase3/`. The repository guard (`parity/GUARD.md`) admits under `parity/manifests/**` only valid `golden-public.json` manifests, which describe Painter recordings (the envelope registry test reads each one's Painter build), and under `parity/fixtures/**` only inputs a golden manifest declares. A ray-cast fixture is no Painter golden: both sides of its comparison are UzPainter's (DXR and Vulkan) plus a CPU reference. Decision 372 already checks the qualification scene against hand-computed answers.

## Decision

1. **Fixtures in code.** The fixtures are authored procedurally in `src/render/ray_query.cpp` (`RayCastFixtures`): `plane` (a 4 x 4 grid, 16-byte stride), `sphere` (a 12 x 16 UV sphere, 32-byte stride, two instances), `bevelled-cube` (44 triangles over 24 shared vertices, 12-byte stride) and `opacity-pair` (a non-opaque quad over an opaque one, instanced plain, forced opaque, forced non-opaque and with mask 0). Nothing is placed under `parity/manifests/` or `parity/fixtures/`, so no Painter-golden rule is bent; the deviation from the task's wording is this decision.
2. **Ray kinds.** Every ray carries what it is aimed at, which sets how it is checked against the CPU reference: `interior` and `miss` field by field (|delta| <= 1e-5 for distance and barycentrics); `edge` and `vertex` inside a closed or shared region by hit and distance only (watertight hardware reports exactly one of the triangles there, not necessarily the reference's); `boundary` (an open mesh's border edge or corner, which DXR and Vulkan on the RTX 4090 both reported as misses) and `grazing` are reported, not asserted.
3. **Cross-backend comparison is exact.** DX12 and Vulkan records are compared with tolerance 0 on every field, and every differing ray is listed with its fields; a fixture passes only with none (a difference would need an owner-approved exception, `07-…` §3.5). Each backend also traces each fixture twice and must be byte-identical.
4. **Report.** `uzp-render-tests ray-cast-fixtures` writes a raw record; `python -m tools.parity.raycast` turns it into `parity/reports/phase3/ray-cast.json` (schema `uzpainter/parity/ray-cast-report/1`): counts, booleans, field names, non-negative numbers, and the adapter, driver and kernel source as SHA-256 digests. A new guard rule checks it with `tools.parity.raycast.report_problems`.
5. **Meshes.** `RaySceneFromMesh` builds a UzPainter `mesh::TexturingMesh` into a ray scene: one BLAS per object with triangles, one geometry per material (compacted positions at the 12-byte `Float3` stride, opacity from the caller's non-opaque materials), the glTF column-major transform as the instance transform, the object index as id.

## Consequences

On the owner's RTX 4090 every fixture builds and traces on both backends, repeats byte for byte, meets the CPU reference by kind, and DX12 equals Vulkan on every ray (`parity/reports/phase3/ray-cast.json`, outcome pass). The fixtures change only with this code and the report's kernel digest; a report from another machine or driver is a new run of the same tool.
