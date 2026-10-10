# Proposal: phase1.10_compositor-blend-kernels

## Why
All 32 documented `BlendingMode` members must behave exactly as in Painter, per channel, with per-channel opacity (LAY-05). Their formulas come first from the Tier 0 black-box fit and then from public candidate definitions (W3C Compositing and Blending Level 1, PDF 1.7, Barré-Brisebois and Hill 2012 for the normal-map modes). Implements D3 (decision 005: Painter-semantic document with a tile/channel evaluator and a measured quantisation profile) with owner answer Q1 (decision 017: exact equality, a divergence passes only through an owner-approved exception) in `docs/architecture/04-layer-stack-and-compositing.md`; formulas are written from public literature and fitted to Tier 0 goldens recorded through Painter's documented API (`docs/architecture/14-parity-testing.md` §2, §3; CLR-01, CLR-02; `docs/licensing-and-clean-room.md`). Child of `phase1.14_compositor-core` (P1-COMPOSITOR), covering `docs/architecture/04-layer-stack-and-compositing.md` §3; named in the `docs/dag.md` decomposition rule.

## What Changes
- `src/evaluator/kernels/blend/`: one kernel per blend mode and channel format for `Normal, PassThrough, Disable, Replace, Multiply, Divide, InverseDivide, Darken, Lighten, LinearDodge, Subtract, InverseSubtract, Difference, Exclusion, SignedAddition, Overlay, Screen, LinearBurn, ColorBurn, ColorDodge, SoftLight, HardLight, VividLight, LinearLight, PinLight, Tint, Saturation, Color, Value, NormalMapCombine, NormalMapDetail, NormalMapInverseDetail`, per-channel `{mode, opacity}` blending, `precise` arithmetic.
- `parity/semantics/blend-modes.json`: per mode the fitted formula, clamping, colour space (encoded sRGB or linear), public source and residual — the kernel source of truth.
- A mode whose fit does not reproduce the goldens exactly stays `release-gap` in the capability manifest until it does, or passes only through an owner-approved exception in `parity/exceptions.json`.

## Dependencies
- DAG inputs of the parent: `phase0.8_tier0-goldens` (blend sweeps), `phase1.4_render-core-layer`.
- Sibling prerequisite: `phase1.9_compositor-quantisation-profile`.
- Parent: `phase1.14_compositor-core`. Consumers: `phase1.11_compositor-mask-effects`, `phase1.12_compositor-height-normal`.

## Acceptance
Tier 0 blend goldens exact for every mode: two uniform fills at a sweep of values and opacities, exported at 16 bit through the documented export API, equal at native decoded values. Only the fitted formula, its public source and its residual are published under `parity/semantics/`; the goldens stay in the private oracle store and are compared locally on the owner's machine (decision 028; `docs/architecture/14-parity-testing.md` §6); the local run report is the evidence and hosted CI skips these tests with an explicit reason.

## Impact
- Affected specs: `compositor`
- Affected code: `src/evaluator/kernels/blend/`, `parity/semantics/blend-modes.json`, `tests/evaluator/`
- Breaking change: NO
- User benefit: Every documented blend mode composes exactly as Painter does, with its formula and provenance on record.
