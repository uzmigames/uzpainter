# Proposal: phase1.10_compositor-float32-residual

## Why
One Tier 0 difference remains after `phase1.9_compositor-quantisation-profile`: under the settled profile `painter-12.1-isolated-linear`, 6 of the 16 32-bit float values of `quantisation-thirds` differ from the same-session recording r1 by 2^-25 or 2^-24 (RGB32F User4: s0 G and B, s1 R, s3 R; L32F Scattering: s0 and s3), and decision 032 (owner, 2026-10-11) keeps any r1 mismatch a divergence that is never counted as a pass. No shipped template uses a 32-bit float format (`assets/templates/`), so the owner split it into this task (`parity/reports/phase1/compositor-quantisation-profile.md`, open items; `parity/semantics/quantisation-profile.json`, entry `quantisation-isolated-root`).

## What Changes
- Identify the float32 operation order of Painter's source-over within a partly covered root stack (candidates: the order of the colour and coverage products in the isolated intermediate, the form of the read-out composite `base + (C - base) a` against `base (1 - a) + C a`, where the coverage is stored and rounded) from public sources (W3C Compositing §5.1 and §6, IEEE 754 binary32) and the Tier 0 goldens `quantisation-thirds` and `blend-inputs` s2; record a new Tier 0 golden under `parity/manifests/tier0/semantics/` if the existing ones do not determine it.
- If the order is found: implement it for 32-bit float channels in the CPU reference and the kernel generator (`src/evaluator/arith.*`, `src/evaluator/kernelgen.*`; CPU = GPU bit for bit) under a new profile id (`painter-12.1-<profile-id>`, decision 017 pinning: `painter-12.1-isolated-linear` stays registered and unchanged), and re-derive `parity/semantics/quantisation-profile.json` through `tests/evaluator/quantisation_fits.py`.
- If it cannot be found: the residual stays published and visible as a divergence; an exception-register entry is the owner's decision (`rulebook_task ask`), never this task's.

## Dependencies
- `phase1.9_compositor-quantisation-profile` (the profile registry, the isolated root and its published fit).
- Not a prerequisite of `phase1.14_compositor-core` or of gate G1 (`phase1.26_gate-g1`): the pilot stacks and every shipped template use sRGB8, RGB8, RGB16, RGB16F, L8, L16 and L16F, all exact against r1. It becomes a prerequisite of any later gate whose content uses an RGB32F or L32F channel.

## Acceptance
Every RGB32F and L32F value of `quantisation-thirds` s0-s3 and `blend-inputs` s2 equals r1 on CPU and GPU in a local DX12 run (decision 028), with every other map of both goldens still exact against r1; or the residual stays published as a divergence with the owner's decision recorded.

## Impact
- Affected specs: `compositor`
- Affected code: `src/evaluator/arith.*`, `src/evaluator/kernelgen.*`, `src/evaluator/profile.*`, `tests/evaluator/`, `parity/semantics/quantisation-profile.json`
- Breaking change: NO (a new profile id; projects stamped with an earlier profile evaluate as before)
- User benefit: 32-bit float channels of partly covered stacks match Painter to the last bit.
