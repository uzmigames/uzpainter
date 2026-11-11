# 432. The four materials are Adobe Substance graphs, served only from project-private snapshots; their serving gaps move to phase3.3

**Status**: accepted (coordinator decision, 2026-11-11). It applies the owner's snapshot-only route of decision 429 ("Só snapshot") to the materials by its precedent, and splits the scope under the owner's throughput rule. No exception is created or proposed: there is no candidate.
**Date**: 2026-11-11
**Related Tasks**: phase3.2_proc-material-families, phase3.3_procedural-families

## Context

`phase3.2_proc-material-families` certifies the materials the recipes use: felt, leather grain, burlap and leather pattern (`05-procedural-content.md` §3, decision 334). Each must be exact, or covered by an owner-approved exception; otherwise it is a release gap. Decision 334 built four UzPainter kernels from public literature, declared their domains and left them `unavailable`.

The survey `python -m tools.parity.recorder.material_survey` ran on 2026-11-11 (Painter 12.2.0, Legacy, Painter lock seq 2380 to 2381). It uses documented symbols only and reads no pixel. The private survey's SHA-256 is `c14b57a2…`. The published semantics are in `docs/analysis/proc-material-families/01-parameter-discovery.md` (`python -m tools.parity.proc_materials.discovery`). It found:

- **Felt and leather grain** are the starter materials the hat recipe names by versioned URL: `fabric_felt` and `leather_grain` (`.sbsar`). They have 13 and 10 outputs, 3 presets and no image input. Their parameters include a `$randomseed` and colour parameters (`fabric_color`; `color`, `hand_tipped_color`).
  - A default material fill of felt activates BaseColor, BaseMetalness, Height and SpecularRoughness.
  - A default material fill of leather grain activates BaseColor, BaseMetalness, Normal and SpecularRoughness. It does not activate Height.
- **Burlap and leather pattern** are not materials of their own. The recipes reach them through the starter smart materials Fabric Burlap and Leather Damaged (Assets3D `25-Faixa-Cintura`, `22-Bracal-Direito`).
  - The single source under burlap's pattern layer is the procedural `weave_2` (one output, `$randomseed`, `Disorder`, `Tiling`). The smart material embeds it in its own resource context.
  - The single source under the Leather Pattern layer is the procedural `grunge_leather_damaged` (one output, `$randomseed` and six parameters), also in an embedded context. It is a split source of BaseColor and Height.
  - The smart materials' structures stay private (§3 publication rule). Only those two sources are named.

## Decision

1. **No clean-room route to exact.** Each of the four outputs comes from an Adobe Substance graph run by Adobe's engine, and each takes a seed.
   - No public source describes these graphs or the engine's random sequence. Reproducing them bit for bit from recordings would reverse-engineer Adobe content (`docs/licensing-and-clean-room.md` §1). That is decision 427 §1 and §2, here for materials.
   - The seed's effect was not recorded. Seeded or fixed, the output is Adobe content, so the route is the same (decision 427 §1 for fixed, §2 for seeded).
   - No fitting was run. The ~2 h time box cannot turn decision 334's kernels into these graphs. With no candidate, there is no residual to offer as a candidate exception.
2. **Snapshot-only, by decision 429's precedent.** The four families are served only from project-private snapshots that `UzPainter.exe assets snapshot` captures from the user's own Painter into the user's own `.uzp`, and are refused without one.
   - Felt and leather grain use the multi-output capture (decision 413) and `set_material_source` (decision 416).
   - Burlap's `weave_2` and leather pattern's `grunge_leather_damaged` are grunge-like procedurals. They follow decision 429's `PROCEDURAL` capture, inside the smart materials of `phase3.6_smart-presets-projections`.
   - The `material.*@1` records stay `unavailable`, with no alias, and their reason names this decision. UzPainter's kernels never serve these families, and a snapshot certifies nothing (decision 222).
3. **What the route cannot serve yet** (release gaps, measured by the survey):
   - **Colour parameters.** The capture's typed codec holds scalars only. Both materials have colour parameters, and the recipes set them (the hat's `fabric_color`, `color`), so neither can be captured today. `set_material_source` then refuses with no recorded default state.
   - **Channels other than Height.** Only Height's composition of a material fill is recorded (P413-A, on a fill activating Height alone). Felt also activates three other channels, and leather grain activates no Height at all.
   - **The 128 px plane.** The multi-output capture runs on UzPainter's plane at 128 px only. The recipes texture their own meshes at their own resolution, and decision 429 §3 extended only the `PROCEDURAL` and `GENERATOR` captures to the destination.
   - **Masks and split template channels.** Burlap's procedural is a mask source, which a seeded procedural cannot be yet (`phase3.3_procedural-families` item 2.15). Leather pattern's procedural is a split BaseColor and Height source, whose split template-channel stores are not derivable (P413-D, item 2.7). Both sit inside smart materials (`phase3.6_smart-presets-projections`).
   - **Physical size.** Painter's own `MaterialPhysicalSize` and `CustomPhysicalSize` rules are not recorded (the oracle half of test 3.2), so both modes stay refused. The recipes project these sources triplanar (`phase3.4_smart-projections`).
4. **Refusal instead of silent loss.** A material fill with any active channel other than Height is now refused by the support check, before any change, naming `phase3.3_procedural-families item 2.16`. Before this, the evaluator left such a channel as the layers below gave it. That is not what Painter does, because a material writes its output into every active channel (§3).
5. **Moved item.** The gaps of §3 move to the new `phase3.3_procedural-families` item 2.16, in this order: the typed codec for colour parameters, the recording and fit of each other channel's composition, the capture on the destination's mesh and resolution, then Painter's physical-size rule. The masked and split uses follow items 2.7 and 2.15.
6. **Narrowed acceptance.** `phase3.2_proc-material-families` is accepted when:
   - items 2.2, 2.3, 2.4, 3.3 and 3.4 stay met;
   - item 2.1's discovery is published;
   - each domain is declared (the first half of item 2.6);
   - the four families are listed as release gaps with the evidence above and their new item.

   Nothing is relaxed. The Tier 2a batches, held-out sets and calibration of items 2.5, 3.1 and the second half of 2.6 do not apply to a snapshot-only family (decision 429 §6). No family becomes `exact` or `calibrated`.

## Alternatives Considered

- **Fitting decision 334's kernels for 2 h anyway.** Rejected. No parameter of a Worley, fibre or weave kernel turns it into an Adobe graph or Adobe's random sequence.
- **Recording each material at two seeds first.** Not done. Seeded or fixed, the output is Adobe content (§1), so the recording could not change the route. Recording it would have cost a Painter session.
- **Extending the capture to colour parameters here.** Deferred to item 2.16. It changes the snapshot signature and metadata codec shared with every capture, and even with it the recipes' fills would still be refused for their other channels (§3).
- **Asking the owner for a new route.** Not needed. Decision 429 already chose snapshot-only for Painter procedurals with no clean-room route. These families are the same case.

## Consequences

- `phase3.2_proc-material-families` is archived on 2026-11-11, and parent item 2.6 is met.
- The four families stay release gaps until item 2.16 closes. The capability entries for `SourceMode.Material` and `ScaleMode.MaterialPhysicalSize` keep their status.
- Evaluator and facade refusals that name `phase3.2_proc-material-families` are unchanged. Archived siblings keep their owner strings the same way, and item 2.16 holds the work.
- Evidence: `tests/parity/test_proc_material_discovery.py` (the publisher) and `tests/export/snapshot_source_test.cpp` `snapshot-material` (another active channel of a material fill is refused atomically, naming item 2.16).
