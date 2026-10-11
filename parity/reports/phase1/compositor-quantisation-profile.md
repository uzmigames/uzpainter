# `phase1.9_compositor-quantisation-profile` — acceptance run on the owner's machine

Child of `phase1.14_compositor-core` (P1-COMPOSITOR; `docs/architecture/04-layer-stack-and-compositing.md` §4). Decision 028: the Tier 0 comparisons against the private oracle store and the GPU checks run locally on the owner's machine, and this report is their evidence. Numbers and hashes only; every recorded Painter output stays in the private store. Run on 2026-10-11 on the tree of commit `defca40` with this task's working-tree changes (`src/evaluator/`, `tests/evaluator/`, `build.zig`, `parity/semantics/quantisation-profile.json`).

**Result: the settled profile is `painter-12.1-isolated-linear`. It reproduces the same-session recording (r1) of the quantisation experiment exactly on every UNORM, sRGB8 and 16-bit float map and on every map of the one-layer partial-coverage stack; 6 of the 16 32-bit float values differ by 2^-25 or 2^-24, a divergence tracked by `phase1.10_compositor-float32-residual`. Both goldens are unstable (the after-reopen recording r2 differs from r1); under decision 032 r1 is their exact target and the register entries `EXC-001` (`quantisation-thirds`) and `EXC-002` (`blend-inputs`) in `parity/exceptions.json` cover their r2 comparisons with the published r2 residuals.** Unit tests green; the GPU equals the CPU bit for bit.

## Run record

| Item | Value |
|---|---|
| Hardware | NVIDIA GeForce RTX 4090, Windows 11 Pro 10.0.26200 |
| Backend | DX12; kernels `cs_6_6` through the render layer's kernel cache |
| Build | Zig 0.15.2, Debug; `zig build painter` and `zig build evaluator-tests` exit 0 with `-Wall -Wextra -Werror -ffp-contract=off` on `src/evaluator/` and `tests/evaluator/` |
| Oracle | `C:\Users\Bolado\AppData\Local\UzPainter\parity-store` (735 hashes), Painter build `12.1.0+js-api.1.1.20`; comparisons through `tools.parity.fit` (`Golden.map`), recordings `r1` (same session) and `r2` (after save and reopen) |

## The experiment and the selected model

`tier0/semantics/quantisation-thirds`: three uniform fills at opacity 1/3 in `Normal` on one channel per `ChannelFormat` member (sRGB8, RGB8, RGB16, RGB16F, RGB32F, L8, L16, L16F, L32F), four colour triplets (s0-s3), exported as 16-bit PNG (UNORM) and OpenEXR 32f (float). Cross-check: `tier0/semantics/blend-inputs` s2, the 16-bit fields A at opacity 0.5 over the white base (every texel a different value, so every rounding direction is exercised).

Models compared (all with the per-format write rules of phase1.8):

| Model | Root stack | Result against r1 |
|---|---|---|
| End-only quantisation (phase0.7 fit) | exact accumulation, one quantisation at the end | not reproduced (evaluator-profile.json: every format off by one code or one half step) |
| Per-layer over the base, `painter-12.1-layerq-linear` (provisional) | accumulator starts at the base, stored after every layer | every format except L16 differs (8-bit maps by one code, 16-bit by one code or one half step), and a 0.5-opacity layer over the base rounds its exact ties down where Painter rounds them up (94 888 of 196 608 RGB16 values) |
| sRGB8 blended on encoded values | — | rejected in phase0.7 (max 29 codes) |
| **Isolated root, `painter-12.1-isolated-linear` (selected)** | composited from a transparent start like a group (colour and coverage stored in the channel format after every layer), then over the base once: `v = base + (C - base) a` | exact on every UNORM, sRGB8 and 16-bit float map; 32-bit floats within 2^-24 |

Root cause of the provisional profile's divergence: Painter does not blend the root layers onto the base. The root stack behaves as an isolated group whose coverage is stored in the channel format (1/3, 5/9, 19/27 rounded to the format), and the base is composited under it once at read-out with the lerp form; with full coverage that is the `1 + (v - 1)` read-out the blend fits had already measured on 32-bit float channels. The stored coverage of a single 0.5 layer is 32767/65535 on 16 bits, just below 1/2, which is why every exact tie of `blend-inputs` s2 goes up. The read-out uses the `Replace` mix of `arith::Composite` (`a + (r - a) alpha`), whose kernel the GPU store already had, so no new kernel was needed; the mix form `a (1 - alpha) + r alpha` differs on 10 922 RGB32F values of `blend-inputs` s2.

## Tier 0 comparisons (selected profile)

Every row was compared on the CPU store and on the GPU store; |Δ| statistics are in `parity/semantics/quantisation-profile.json` (`tests/evaluator/quantisation_fits.py`; `test_published_fit_reproduces` requires the file byte for byte).

| Golden | Maps | vs r1 | vs r2 |
|---|---|---|---|
| `quantisation-thirds` s0-s3 | sRGB8 (User0, linear blending), RGB8, RGB16, RGB16F, L8, L16, L16F | exact (0 differing values) | within `EXC-001` (decision 032): r2 differs from r1 on 16 of 36 maps; the evaluator differs from r2 on sRGB8 (1 code, s2), RGB8 (1 code, s1), RGB16 (1 code, s3), L8 (1 code, s0), RGB16F and L16F (one half step, toward zero against nearest) |
| `quantisation-thirds` s0-s3 | RGB32F (User4), L32F (Scattering) | divergence, 6 of 16 values off: s0 G and B, s1 R, s3 R, L32F s0 and s3 (|Δ| 2^-25 or 2^-24; `phase1.10_compositor-float32-residual`) | within `EXC-001` bounds (r1 and r2 differ on 9 of the 16 values); the r1 divergence stands |
| `blend-inputs` s2 | RGB16 ×2, sRGB8 ×2, RGB8, RGB16F, L16, RGB32F | exact (0 of 1 245 184 values) | RGB16, RGB16F, L16, RGB32F exact; sRGB8 and RGB8 within `EXC-002` (decision 032; r2 differs from r1 on 22 912 and 11 520 values) |

The shipped templates use sRGB8, RGB8, RGB16, RGB16F, L8, L16 and L16F (`assets/templates/`), all exact against r1; no template uses a 32-bit float format.

### Treatment under decisions 017 and 032

`quantisation-thirds` and `blend-inputs` are classified unstable in `parity/reports/phase0/tier0-stability.md` (not admitted as exact goldens). Two recordings of the same instructions that differ cannot both be equalled by a deterministic evaluator. Decision 032 (owner, 2026-10-11, the exception under decision 017; `parity/CONTRACT.md` §5) makes the same-session recording r1 the exact target: (a) r1 equality, value for value, is required and holds on every map the templates use; (b) every r2 residual and the 32-bit float residual are published in the fit; (c) the register entries `EXC-001` (`tier0/quantisation/thirds`) and `EXC-002` (`tier0/blend/inputs`) name decision 032 and bound the r2 comparisons by those residuals (defect test `tests/parity/test_verdict.py::test_decision_032_entries_catch_injected_defects`). Any r1 mismatch stays a divergence: the 32-bit float residual is not covered and is tracked by `phase1.10_compositor-float32-residual`: the float32 operation order of Painter's source-over within a partly covered stack is not identified, and the oracle itself varies at that level between recordings.

## Profile registry and pinning

| Check | Evidence |
|---|---|
| 2.3 registry | `src/evaluator/profile.h`: `painter-12.1-layerq-linear` (root over the base) and `painter-12.1-isolated-linear` (current) registered; `FindProfile` fails with `evaluator:unknown_profile`, `RegisterProfile` refuses a malformed or taken id (`invalid_profile`) |
| 2.3 dispatch | `BuildDag` evaluates with the profile in `versions.evaluator_profile`; subtree hashes are seeded with that id, so tiles of two profiles never serve each other |
| 3.3 pinning | `uzp-evaluator-tests profile`: a project stamped A (`layerq-linear`) evaluates per its model; after a synthetic `painter-12.1-synthetic-b` is registered it still evaluates with A, bit for bit, on the same evaluator (served from its cache) and on a fresh one; a project stamped B evaluates with B's rules and shares no tile |

## Unit tests and kernels

| Case | Result |
|---|---|
| `arith`, `templates`, `order`, `cache`, `admission`, `sources`, `profile` (CPU) | every check passed (the `order` and `cache` cases count the read-out blend: one more blend and one cached read-out tile per tile) |
| `gpu-vs-cpu`, `kernel-sweep`, `projection-gpu-vs-cpu` (DX12) | GPU equals CPU bit for bit, with the isolated root on every random stack |
| `python -m pytest tests/evaluator` | 166 passed |
| Every Tier 0 golden of phase1.5 and phase1.8 under the new profile | unchanged (base values, ramps, bitmap import, `blend-order`, `group-masks`, `resample-uv`, Height, island edges; the published fits of phase1.8 reproduce byte for byte) |

## Quality gate

| Step | Command | Result |
|---|---|---|
| Type-check | `python -m mypy` | no issues (182 files) |
| Lint | `python -m ruff check .`, `python -m ruff format --check .` | clean |
| Build | `zig build painter`, `zig build evaluator-tests` | exit 0, no warnings |
| Tests | `python -m pytest tests/evaluator`, `python -m pytest tests/parity` | 166 passed (evaluator, with the store and the DX12 adapter: nothing skipped); 622 passed (parity) |
| Guard | `python -m tools.parity.guard` | 0 blocked |

## Open items

- 32-bit float channels of partly covered stacks: 6 of 16 values of the experiment within 2^-24 of r1 (above), a divergence; task `phase1.10_compositor-float32-residual` (no shipped template uses a 32-bit float format). Update 2026-10-11: under the new current profile `painter-12.1-isolated-half-alpha` (decision 044) 5 of the 16 values remain; the order was not identified (`parity/reports/phase1/compositor-float32-residual.md`).
- Resolved after the archive: `src/store/census.cpp` and the store and mesh test fixtures stamp `painter-12.1-isolated-linear` (the id of `evaluator::kCurrentProfile`, spelled out because the store does not depend on the evaluator; `tests/evaluator/test_compositor_quantisation_profile.py` checks they agree). The document-model fixtures of phase1.1 keep `painter-12.1-layerq-linear` (still registered), because their manifest digests are pinned evidence.
- Resolved after the archive: `parity/semantics/evaluator-profile.json` and `tools/parity/fit/profile.py` state that `quantisation-profile.json` supersedes them for the evaluator; the phase0.7 fit and its numbers are unchanged (`python -m tools.parity.fit check --fit profile` reproduces it).
