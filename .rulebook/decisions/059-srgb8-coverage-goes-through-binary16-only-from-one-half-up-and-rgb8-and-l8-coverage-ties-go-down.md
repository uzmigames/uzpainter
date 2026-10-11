# 59. sRGB8 coverage goes through binary16 only from 1/2 up, and RGB8 and L8 coverage ties go down

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.10_compositor-float32-residual

## Context

Decision 044 writes the coverage plane of an sRGB8 intermediate as `WriteUnorm(binary16_nearest_even(a), 8)`, measured on `group-masks` s2-s3, whose group coverages lie in [1/2, 1). It left the RGB8/L8 coverage at an 8-bit tie unobserved. The diagnostic golden `group-coverage-order` (decision 048) records both:

- **RGB8 and L8.** The even rows of the three opacity-0.5 sets put the group coverage (255 + y)/510 on an 8-bit tie. The RGB8 and L8 maps are exact on all four sets with the plain 8-bit write rule (truncate to 12 fractional bits, nearest, ties down), the rule every profile already uses.
- **sRGB8 below 1/2.** The opacity-0.3 set has coverages 0.3 + 0.7 m; on rows y = 0, 10, ..., 70 they lie within 3e-6 of an 8-bit tie in [0.3, 0.5). The sRGB8 map shows all eight stored down (the plain rule). Binary16 sends five of them up (rows 0, 20, 40, 50, 70: 1 863 sRGB8 values off). Without binary16 the rows from 100 up fail instead (2 261 values), as `group-masks` does.
- **Rule.** Binary16 only when the coverage is at least 1/2, the plain rule below, makes all 24 maps of the golden exact and keeps `group-masks` exact. Binary16 toward zero, fixed-point rounding to 2^-11, `1 - binary16(1 - a)`, binary16 of `255 a`, binary16 of `2a - 1` and half-precision code arithmetic each fail one side. The mechanism is not identified; below 1/2 the evidence is these eight rows of one golden.

## Decision

1. Under `painter-12.1-isolated-coverage-weights` (decision 058) the sRGB8 coverage plane passes through binary16 only when the coverage is at least 1/2 (`EvaluatorProfile::srgb8HalfCoverageFromHalf`, `TileFormat::halfCoverageFromHalf`, kernel define `UZP_HALF_COVERAGE=2`), on the CPU and GPU evaluators bit for bit. `painter-12.1-isolated-half-alpha` keeps decision 044's rule.
2. RGB8 and L8 coverage keeps the plain 8-bit rule; this is now measured, and no profile changes.

## Alternatives Considered

- Keep binary16 on every sRGB8 coverage and publish the 1 863 values as a divergence. Rejected: the rule is known wrong on them, and the split rule fits every observation.
- Search further for a mechanism before adopting. Deferred: the rule is stated as measured with its evidence; a recording with sRGB8 coverages on ties in [0.25, 0.5) at other opacities would test it.

## Consequences

`group-coverage-order` is exact on all 24 maps, CPU and GPU. Model panel 2026-10-11 (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5): C2 (adopt the split rule, mechanism unknown, evidence stated) agreed 3-0; C3 (RGB8/L8 settled, no profile change) agreed 3-0.
