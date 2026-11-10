# 429. Grunges and the three grunge-reading generators are served only from project-private snapshots of the user's own Painter, and refused without one

**Status**: accepted (owner decision, 2026-11-10, choice "Só snapshot"). This is the route decision 427 §5 left to the owner.
**Date**: 2026-11-10
**Related Tasks**: phase3.3_procedural-families, phase3.2_proc-grunge-families, phase3.2_proc-snapshot-backend

## Context

Decision 427 found no clean-room route to exact for the seventeen inventoried grunges:

- `grunge/rock`, `stone-details`, `scratches` and `dirt-large` are fixed Adobe textures.
- The other thirteen follow the Substance engine's seeded sequence, which no public source describes.

Dirt, Metal Edge Wear and Mask Builder - Legacy read that seeded grunge at their defaults (decision 423 §4), so they inherit the blocker. Items 2.13 and 2.14 of `phase3.3_procedural-families` waited on the owner's route. The options were:

- snapshot-only;
- an art change to independently designed UzPainter grunges;
- another route.

The snapshot backend (decision 327, `phase3.2_proc-snapshot-backend`) already serves a raster captured from the user's own licensed Painter for the user's own project, at an exact signature. Its capture was limited to the authored plane at 128 px, as a fill source, without image inputs. A generator cannot be a fill source, and it reads the texture set's mesh maps.

## Decision

1. **Snapshot-only.** The seventeen grunges and the three generators are served only from project-private snapshots that `UzPainter.exe assets snapshot` captures from the user's own Painter into the user's own `.uzp`.
   - A snapshot is never stored in the repository, never shipped and never carried by a recipe. The guard rule `procedural-snapshot` and decision 327 §4 still apply.
   - Private Painter data stays in the project and the private recording directory.
2. **No substitution.** Without a snapshot of the exact signature, the source is refused as `unavailable` (`no snapshot with this signature`). The refusal names the first field where the closest stored signature of the same asset differs.
   - For a `uzasset://snapshot/` pin, `ProceduralSeam::Select` and `Admit` return the snapshot backend's own refusal. They used to return the asset library's `pinned version not in the asset library`, which named no signature field.
   - UzPainter's kernels for these assets (decisions 329, 331) are not exact. They never serve them, and they are not certified.
   - Every `grunge.*@1` record and the `generator.dirt@1`, `generator.edge-wear@1` and `generator.mask-builder@1` records stay `unavailable`, with no alias. Their reason names this decision.
   - A snapshot certifies nothing (decision 222). It counts as no calibration or held-out evidence, and capturing it makes no parameter editable.
3. **The capture route.** A request of exactly `resource`, `parameters` and `usage` (`PROCEDURAL` or `GENERATOR`) captures on the destination's own mesh and texture set resolution.
   - The destination holds one texture set of one UV tile 1001, square, at a power of two from 128 to 4096 px, on an imported self-contained OBJ mesh, with the settings of the existing capture domain.
   - `PROCEDURAL` (a grunge) is captured as the existing paired User0 L32F / User1 RGB32F fill source.
   - `GENERATOR` is captured as the only effect in the black mask of a white Raw fill above a black Raw base fill. This is the layout of the generator goldens (decision 423). Every mesh map bound to the destination is imported into Painter from its stored bytes and bound to its usage with the documented `set_mesh_map_resource`, and every other usage must read back unbound.
   - Both exports of both channels must be equal at the float32 bit level.
4. **The signature.** The signature is decision 327's, filled by the capture:
   - every effective parameter, the seed (`$randomseed`) and the output id;
   - the resolution, which is the destination set's;
   - the destination's settings, including the mesh SHA-256 and import report hash;
   - for a generator, each bound mesh map as an image input, with its SHA-256 and spec (`SnapshotMeshMapInputs`).

   Before its one transaction, the command rebuilds the request the destination's own set asks for (`SnapshotSetRequest`, `SnapshotGeneratorRequest`). That request must equal the receipt's signature. Decision 413's per-output rule holds: each output is one snapshot of its own signature. Grunges and these generators list one output.
5. **Serving.**
   - The fill provider now admits a User L32F snapshot fill at its texture set's resolution, on any mesh of that domain. The mesh's identity is a signature field, so another mesh is a mismatch.
   - `SnapshotBackend` serves a generator snapshot for `SnapshotGeneratorRequest`.
   - The compositor does not yet evaluate a generator effect, nor a snapshot source inside a mask stack, which is how the recipes use both. That compositing is a separate release gap: `phase3.3_procedural-families` item 2.15.
6. **Scope of items 2.13 and 2.14.**
   - They close on the route: the capture, the signature, exact serving and refusal, records, capability entries and docs. They are proven on a real private capture (Consequences).
   - The Tier 2a batches, held-out sets and calibration they listed do not apply to a snapshot-only asset. Nothing is relaxed: no asset becomes `exact` or `calibrated`.

## Alternatives Considered

- **An art change to UzPainter-designed grunges.** Not chosen by the owner. It would be certified as UzPainter assets, not as Painter parity.
- **Keeping the 128 px plane capture only.** Rejected. Painter evaluates the graph at the output resolution (decision 427 §3), and the recipes texture the user's own meshes, so both are signature fields captured as they are.
- **Baking mesh maps inside Painter for a generator capture.** Rejected. Painter's bake is not the destination's mesh maps, so the signature could never match the project's own request. Importing the destination's stored mesh maps makes the signature name exactly what the project binds.

## Consequences

- Real private capture, 2026-11-10 (Painter 12.2.0, Legacy; Painter lock seq 2374 to 2375). UzPainter's own project on the authored plane at 256 px, with four authored 16-bit fixture bitmaps as its AO, Curvature, Position and World Space Normal maps, holds:
  - the grunges `rock` and `dirt-large` at their defaults, and `dirt-a` at seeds 1 and 2;
  - Dirt at its default seed and at seed 2, and Metal Edge Wear and Mask Builder - Legacy at their defaults.
  - The project is in the private oracle store by hash. Its receipts stay under `%LOCALAPPDATA%/UzPainter/snapshot-recordings/`.
- `tests/procedural/test_proc_grunge_snapshot_served.py` checks over that capture:
  - every snapshot is `Stored` and `Evaluate`d byte-equal to its Painter export;
  - the project's own request gives each stored signature;
  - each single change of seed, parameter, resolution, mesh or mesh map is `unavailable`, naming its field;
  - each grunge binds to a fill and is served after reopen.
- Items 2.13 and 2.14 are met on this route; item 2.15 holds the mask-stack and generator-effect compositing.
