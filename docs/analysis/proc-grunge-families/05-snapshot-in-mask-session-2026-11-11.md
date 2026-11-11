# Snapshots inside mask stacks in one Painter session, 2026-11-11 (phase3.3_procedural-families item 2.15)

Painter `12.2.0+js-api.1.1.20`, Legacy colour management, one Painter session under the Assets3D Painter lock (seq 2378 to 2379). The requests were committed before the session (`2d307575`). `tests/python/capture_snapshot_in_mask_session.py` built `UzPainter.exe`, created the destination project, captured the eight 2.13/2.14 snapshots with `assets snapshot`, then recorded two Tier 0 goldens before Painter stopped. Each golden was recorded twice (r1; r2 after save and reopen), admitted, verified, and its inbox run deleted. Numbers below come from `python -m tools.parity.fit.snapshot_in_mask` (sections 4 to 6). Every map is a private oracle in the owner's store; no Painter value is published.

**Outcome: the same session does not make seeded sources exact. Item 2.15 stays open.** The fixed grunges `grunge/rock` and `grunge/dirt-large` are served as a mask fill source. Seeded grunge snapshots and generator effects stay refused in a mask. The 16-bit read and the effect mix are settled.

## 1. Recordings

- Destination: as in `04-snapshot-in-mask-2026-11-10.md` §1, a new project (store record `snapshot-in-mask-session-project`) whose snapshots were captured in this session.
- `tier0/semantics/snapshot-in-mask-session`: the eight composites of `snapshot-in-mask`, the same steps, in the capturing session (decision 431).
- `tier0/semantics/snapshot-in-mask-read`: the bitmap `mask-codes` (every 16-bit code once) as the only effect of a black mask at Normal 1, on the same white-over-black L32F layout. The channel holds the read of every code k.

## 2. The 16-bit read G(k)

On all 65 536 codes, in r1 and r2, the channel holds G(k) = float32(1 + float32(F(k) - 1)), with F(k) the correctly rounded float32(k / 65535):

| Model | Texels that differ (of 65 536) |
|---|---|
| G(k) = 1 + (F(k) - 1) | 0 |
| float32(k / 65535) | 21 845 |

- G is not a property of the 16-bit fetch, which decision 424 measured correctly rounded. It is the read-out of a 32-bit float channel over its white base, `1 + (v - 1)` (arith.h `Float32Readout`, blend-modes.json), applied to the mask value F(k). It equals 1 - (1 - F(k)), the AO generator's I(I(F)) of decision 424.
- The evaluator already applies that read-out. No table of Painter values is needed, and none is shipped.
- `tests/export/test_snapshot_in_mask.py` evaluates the bitmap case natively: its read-out equals the golden on all 65 536 texels.

## 3. The effect mix

The code-level model of `04` §2 over this session's own captures, with G(k) as the read:

| Case | two roundings, a + fl((r - a) alpha) | one rounding, fma(r - a, alpha, a) |
|---|---|---|
| `rock` Normal 1 | 0 | 0 |
| `dirt-a` Normal 0.31 | 2 | 2 |
| `dirt-a`, `rock` Multiply | 1 | 1 |
| `dirt-a`, `dirt-large` LinearDodge 0.14 | 22 | 4 |
| Mask Builder Normal 0.91 | 10 | 10 |
| Metal Edge Wear, `rock` Multiply | 0 | 0 |
| Dirt, `grey-a` Subtract 0.9 | 20 | 8 |
| Dirt (seed 2) Normal 0.5 over White | 0 | 0 |

- In both sessions (2026-11-10 and this one), the two-rounding mix misses 18 and 12 more texels than the fused one, on the two cases where they differ. Those texels hold the same source codes in every capture.
- **Check against every earlier mask golden.** Of the 71 manifests of the current envelope with a mask stack, only `api-probes/mask-stack` (Screen 0.75 over a Black background, so a = 0 and both forms round fl(r alpha) once) and `mask-precision` (opacity 0.5 and 1, where (r - a) alpha is exact) set a mask effect's opacity. Both forms are therefore equal on every texel of every earlier golden. `tests/evaluator/test_compositor_mask_effects.py` passes with the fused mix.
- The evaluator's mask effect mix is now fma(r - a, alpha, a) on both lanes. A content filter effect keeps the two-rounding mix (`filterEffectMix`): no recording sets it apart.

## 4. Same session, seeded sources

The texels the fused model still misses are all on seeded sources (`dirt-a` both seeds, Dirt, Mask Builder - Legacy), by 1 to 21 codes:

- Each is a texel where the mask stack's instance of the source holds another code than this session's capture of it.
- Some recur in both sessions at texels where every capture agrees (`dirt-a` seed 1 at texel 50281, Mask Builder at 15226 and 47994). Others appear in one session only.
- The Dirt and Mask Builder texels repeat every 128 rows.

So each Painter instance of a seeded source can differ from another one, within one session too. The capture's instance does not predict the mask stack's instance. Under decision 431 these composites are not exact.

## 5. Across sessions (reported, not compared)

| Source | This session's capture vs the 2026-11-10 capture |
|---|---|
| `grunge/rock`, `grunge/dirt-large`, Dirt (seed 2), Metal Edge Wear | 0 texels |
| `grunge/dirt-a` seed 1, seed 2 | 2, 4 texels, 1 code |
| Dirt | 8 texels, up to 32 codes |
| Mask Builder - Legacy | 12 texels, up to 23 codes |

The composites differ from the 2026-11-10 golden on 0 to 12 texels per case, by up to 56 codes (Dirt, then `grey-a` Subtract 0.9). Dirt (seed 2) and Metal Edge Wear were exact in this session, but Dirt (seed 2) differed from its captures by 22 codes on 4 texels in the 2026-11-10 session. No seeded source is shown stable.

## 6. What is served

- **Served:** a snapshot of `grunge/rock` or `grunge/dirt-large` (Painter 12.2.0's versions) as a mask fill effect's source. It names its output with `mask_output` and takes no preset, image input or plugged source. Painter reads it as its 16-bit code, so the provider serves the UNORM16 write of each stored value, which gives back every captured code. Every recording of these grunges in a mask (three sessions) equals the evaluator on every texel: `rock` at Normal 1 in all three, `dirt-large` at Normal 1 in the fresh session of 2026-11-10.
- **Refused before mutation:** a seeded grunge snapshot as a mask source (naming decision 431), and a generator effect (the generator release gap). Capability entries: `SourceSubstance` `compositor:snapshot-in-mask` is `supported` for the fixed grunges; `compositor:snapshot-in-mask-seeded` is the release gap of item 2.15.
- **Open:** the recipes use seeded grunges and the three generators in masks. Exact parity for them needs a reference that predicts the mask stack's own Painter instance. A snapshot captured in another instance cannot. That rule is not this item's to set.
