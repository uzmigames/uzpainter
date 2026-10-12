# 86. Only the combined-normal virtual maps are supported; AO_Mixed and the converted maps stay release gaps until recording R-086

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.15_export-plan-compiler, phase1.18_export-engine

## Context

Painter documents thirteen `virtualMap` names (export.html):

- `Normal_OpenGL`, `Normal_DirectX`, `AO_Mixed`;
- `Diffuse`, `Specular`, `Glossiness`, `Unity4Diff`, `Unity4Gloss`, `reflection`, `1/ior`, `Glossiness2`, `f0`, `View_2D`.

Item 2.5 of phase1.15 asks for their resolution. A map whose golden does not pass stays a release gap and raises before writing.

Measured facts:

- **Combined normals.** Normal_OpenGL and Normal_DirectX were run through the plan: `CompilePlan`, then `EvaluateFileOn` on the CPU store, then the 16-bit UNORM write rule. They equal every r1 map, and every r2 map that equals r1, of `height-normal-plane-amplitudes` and the Sharp and Sobel `plane-strength` sweeps: 40 maps, 72 comparisons, 0 differing values.
- **AO_Mixed.** Its published operator (`parity/semantics/ao-mixed.json`, `calibrated`) is the float32 product of the AO mesh map and the AO channel, written at 8-bit precision with 12-bit truncation and the nearest code, ties down.
  - It is exact on `ao-mixed` s0, s2 and s3 against both recordings.
  - On s1, an AO fill at opacity 0.5, it misses 30 values against r1 and 17 against r2. Each miss is one 8-bit code, and each is within 0.03 of a 2^-12 step.
  - Painter's own r1 (same session) and r2 (after reopen) differ at 27 AO_Mixed values there, while their AO channel exports are byte-identical. 10 values miss both recordings.
  - Rejected operand models: the unquantised read-out, the lerp forms with and without fma, half-float operands or product, an 8-bit channel, and decoding by reciprocal multiplication.
- **No goldens for the other ten maps.**

The model panel was consulted under the owner's delegation (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5):

| Claim | Verdicts |
|---|---|
| C6 Normal_OpenGL and Normal_DirectX marked supported | AGREE x2, PARTLY x1 (the support keeps the evaluator's restrictions) |
| C7 AO_Mixed not supported: refused at plan time naming R-086, its evaluation code removed, ao-mixed.json kept as the calibrated operator; R-086 records an opacity sweep twice per session and after reopen | AGREE x2, PARTLY x1: say in the published file that calibrated is not parity; keep the rejected models; rerun the dry-run comparison |
| C8 Items 3.6 and 4.1 stay open until R-086 is fitted; item 2.5 is checked | AGREE x3 |
| C9 The ten converted maps published as `gap` with their documented meaning, refused before writing, requested in R-086 | AGREE x1, PARTLY x2: one plane with ramps is not enough coverage; record each map twice per session; list the AO and converted-map probes separately |

## Decision

1. **Support** (`src/export/virtual_maps.{h,cpp}`). `Support` marks Normal_OpenGL and Normal_DirectX supported. The evaluator's own limits of the combined normal still apply (decision 085).
2. **AO_Mixed is a release gap.**
   - It is refused when the plan resolves it, with `NotYetSupported` naming recording R-086 and owner phase1.18_export-engine. Its evaluation code is removed.
   - `parity/semantics/ao-mixed.json` stays the calibrated operator. `virtual-maps.json` notes the s1 residuals and that calibrated is not parity.
   - The dry-run comparison was re-run after the change: 165 steps are equal, and the refusals are the `meshMap position` step (phase1.16) and the `ao-mixed` step (R-086).
3. **The ten converted maps are `gap` entries** in `parity/semantics/virtual-maps.json`, with their documented meaning, components and public sources (A-PYDOC, A-HELP-EXPORT). They are refused before anything is written.
4. **Recording R-086** (`parity/reports/phase1/export-plan-compiler.md` §4) has two parts:
   - **R-086a:** an AO_Mixed opacity sweep, exported twice in one session and again after reopen, with an OpenEXR 32f twin.
   - **R-086b:** the converted maps over metal/roughness ramp sweeps and both metallic extremes, at PNG 16 and OpenEXR 32f, each exported twice per session. It needs a recorder change: the recorder's file names must not contain the `/` of `1/ior`.
5. **Items stay open until R-086 is recorded and fitted.** Item 3.6 names AO_Mixed, so 3.6 and acceptance 4.1 stay open. Item 2.5 (resolution, refusals, published file) is complete.

## Alternatives Considered

- Supporting AO_Mixed with an exception for s1. Rejected: the r1 target is missed, and no exception covers a missed r1 (decision 032).
- Keeping the AO_Mixed evaluation code behind the refusal. Rejected: dead code.

## Consequences

- Configurations using `AO_Mixed`, such as the future Unreal ORM and UzEngine ORM presets, fail before writing until R-086 is fitted. The Assets3D pipeline presets use only Normal_OpenGL and are unaffected.
- The R-086 recordings must be made by the agent that owns Painter.
