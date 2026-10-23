# 358. Single-triangle own padding weights use box-normalised float32 distances

**Status**: accepted
**Date**: 2026-10-23
**Related Tasks**: phase1.25_pilot-wand

## Context

Wand item 2.7 remains open under production refusals 245/259. The 27 recorded kernel probes leave 2,951 differing ring coordinates under decision 356. The current Painter 12.2.0 envelope refresh preserves every export-padding and Wand golden exactly. A synthetic quantization-boundary probe and recorded own-tap chains distinguish geometric distances from the existing box-normalised float32 comparator distances.

## Decision

For a selected ring chain containing more than one tap, if every tap is own (not across-seam) and belongs to tau, calculate weight fractions from the existing compare_distance float32 distances over box-normalised positions. Preserve geometric distances for candidate selection and ordering, tap count, and uncertainty flags. If any measured distance is nonfinite or nonpositive, preserve the previous geometric fractions. Quantization remains decision 268's rule. Implement identically in src/export/padding.cpp and tests/export/padding_reference.py. No tolerance, exception, per-coordinate table, far-tap extension, or refusal lift.

## Consequences

### Subsequent corpus check (2026-10-23)

The tau-cumulative hypothesis is rejected for production after all 27 older kernel probes, using the current own-tau float32 fractions: 2,941 -> 2,959 differing ring coordinates, zero fixed and 18 new. Hinge-far changes 395 -> 401 and hinge-single 677 -> 689; the other 25 probes are unchanged. Tau-prism's 15 improvements do not generalise. No frame policy changes are accepted. This completes the wider check described as pending in the original evidence below.

Across all 24 components and every recorded infinite export of 27 probes: 2,951 -> 2,941 differing ring coordinates, 10 fixed and zero new, with 80,930 eligible chains. tie-sweep-seams-box320: 36 -> 35; tie-sweep-strips-box320: 4 -> 0; tie-sweep-strips-centred: 3 -> 0; tie-sweep-strips-offcentre: 2 -> 0; other 23 unchanged. Wand holdout retains identical residual coordinate sets: EXR 85 / PNG 49. Twelve focused CPU/native tests pass, including translation, quantization boundaries, and positive-extent float32 collapse fallback. Native export tests build in Debug, ReleaseSafe, ReleaseFast, and ReleaseSmall; six native precision cases pass in each release mode. Float32 generalization to far taps is rejected: tested variants fix seven coordinates but introduce one. Item 2.7 and production refusals 245/259 remain open; 2,941 kernel residuals remain. Separate tau-prism validity evidence: all eight exports exactly preserve authored data on 1,824 covered texels; four infinite exports are globally bit-identical. Passthrough repeats are internally stable in each session, but sessions differ on all 260,320 uncovered texels: first-session passthrough equals source throughout; second-session passthrough equals infinite output throughout. Cache mechanism unproven; uncovered passthrough is not a cross-session exact contract. Infinite-ring policy scoring is valid. Across 2,640 ring texels, per-hinge misses 227, tau-always 287 (34 fixed/94 new), tau-rigid 269 (0 fixed/42 new), tau-cumulative 212 (15 fixed/0 new). All four policies miss all 96 mixed-tau controls and pass all 80 single-far controls. The wider corpus check above rejects cumulative for production; these probe scores alone do not justify a policy change.
