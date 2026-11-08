# 411. AO_Mixed is fitted exactly on every r1 texel, and the plan computes it for an empty AO stack or one root fill

**Status**: accepted
**Date**: 2026-11-08
**Related Tasks**: phase3.2_unreal-ue56-packed-preset, phase3.1_unreal-gltf-pbr-preset, phase3.2_uze-uzmat-preset

## Context

Decisions 092 and 131 left `AO_Mixed` refused: the best model of decision 092 missed r1 at 31
values, and the R-131 controls (decision 321, decision 131's amendments) still left two residual
texels per set with bit-exact exported operands. Item 2.10 of `phase3.2_unreal-ue56-packed-preset`
owns the fit.

A new authored request, `ao-mixed-operand-probe` (`tools/parity/tier0_semantics/ao_operand_probe.py`),
was recorded and admitted in the current Legacy envelope on 2026-11-08: eight sets of authored
float32 operands placed at the quantizer's 12-bit steps (a constant 1.0 mesh times an L32F channel
at every step +-6 ulps, the mirror with a white channel, lattice and off-lattice products at step +
t ulp, and L16/L32F blend sources for the reopen question), PNG 8 and OpenEXR 32f with immediate
repeats, r1 and r2. All inputs are authored formulas; no recorded value is published here.

## Decision

1. **The operator** (CPU fit, `tools/parity/fit/ao_mixed_scan.py`), each step one float32 rounding:
   - the AO mesh map operand a enters as `a' = (1 + a) - 1` (rounded to the absolute 2^-23 grid);
   - the AO channel operand is the fill mixed over the white base, `c = fma(S, al, 1) - al`. On an
     L16 channel S is first written as an L16 code (the UNORM write rule) and al is the opacity's L16
     code with ties down; on an L32F channel S and al are float32. With no AO layer c = 1. Fills of
     one source compose to one mix of opacity `1 - prod(1 - opacity)`, a group multiplying its
     children's opacity;
   - `v = a' c`, re-composited over the white base as `(v - 1) + 1`, written with the 8-bit write
     rule; PNG 16 stores code x 257, OpenEXR float32(code / 255).

   It is exact on every r1 AO_Mixed export of the 13 admitted AO goldens: `ao-mixed`,
   `ao-mixed-opacity` and its OpenEXR 32f twin (group and two-fill sets included),
   `ao-mixed-isolation`, `-float`, `-8bit`, `ao-mixed-grid`, `ao-mixed-grid-l32f`,
   `ao-mixed-grid-l16-reopen3`, `ao-mixed-mesh-float-product`, `ao-mixed-precomposed-half-l32f`,
   `ao-mixed-precomposed-half-y-l32f` and `ao-mixed-operand-probe`, at PNG 8, PNG 16 and OpenEXR
   32f (0 differing samples). The stored channel is not the operand: an L16 channel stores the mix
   quantized and an L32F channel stores `fma(S - 1, al, 1)`. That is why every earlier model of
   exported operands missed.
2. **The plan computes AO_Mixed natively** (`src/export/virtual_maps.cpp` `AoMixedOn`; refusal
   `AoMixedRefusal` at plan time, `src/export/plan.cpp` `ResolveVirtual`) only in this scope:
   legacy colour management; the default template; an L16 or L32F AO channel; a valid AO mesh map
   bound, an 8- or 16-bit grey image at the set's resolution; UV islands covering the tile; and
   either no visible layer that changes AO, or exactly one root fill layer on AO, without mask,
   content effects or geometry mask, in Normal at an opacity in [0, 1], whose own AO source is a
   grey linear uniform colour or an 8- or 16-bit grey linear bitmap at the set's resolution under
   the identity UV projection (Nearest or BilinearHQ, Repeat or RepeatNone), with values in [0, 1].
   Through `EvaluateFileOn` it equals every r1 AO_Mixed export of the in-scope sets of the nine
   AO goldens with PNG inputs at PNG 8, PNG 16 and OpenEXR 32f
   (`tests/export/tier0.py ao_mixed_goldens`, `test_virtual_map_goldens_exact`).
3. **Everything else stays refused before writing**, naming item 2.10 and this decision: other
   colour management, templates or channel formats, a missing or invalid mesh map, partial
   coverage, OpenEXR images (the evaluator does not decode them), groups, several AO layers,
   masks, effects, other blend modes, sources or projections. The composition rule of item 1 for
   groups and several fills is recorded but not lifted: it is seen on one group set and one
   same-source two-fill set only.
4. **r1 is the target** (decision 032). After save and reopen Painter's AO_Mixed differs from r1 on
   blended sets, deterministically (r2 = r3 = r4 on `ao-mixed-grid-l16-reopen3`); opacity-1 L32F
   sets and the mesh path are unchanged. Neither the stored channel nor another opacity coding
   explains r2. This answers decision 131's open question for acceptance: r1 alone is compared, as
   for every other golden whose recordings differ.

## Alternatives Considered

- **Lifting the group and multi-fill rule too.** Rejected: one set each, same source only.
- **Computing from the stored channel.** Rejected: it is not Painter's operand (item 1).

## Consequences

- `Support(AO_Mixed)` is supported; configurations reading it in scope plan and export. The shipped
  Unreal and UzEngine presets stay refused on their own provenance and island rules where those
  apply; their ORM no longer blocks on an unfitted map inside the scope.
- `parity/semantics/virtual-maps.json` marks AO_Mixed exact with its residuals through the plan.
- `phase3.1_unreal-gltf-pbr-preset`'s AO_Mixed blocker is lifted for this scope.
