# 82. Excluded features raise NotYetSupported before any mutation, through one support check and one error-class mapping

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.14_compositor-core, phase1.19_pyapi-native-module, phase1.20_pyapi-facade

## Context

Item 3.3 of phase1.14: requesting an excluded feature (a triplanar projection, a compare mask and others) raises `NotYetSupported` before any mutation. The starting state:

- The evaluator refuses excluded features with `evaluator:unsupported_node`, `unsupported_blend_mode` or `unsupported_source`, mostly while it builds the evaluation DAG. A few refusals need decoded bitmaps (minification) or the virtual-normal stage.
- Four refusals in `diagnostics.cpp` used these kinds for malformed caller arguments: a region-statistics mask of the wrong shape, non-finite values, and an instance named as a material.
- The evaluator evaluates some features that no golden records: instance layers, Mesh geometry masks, one-axis wrap, content-stack fill effects, mask-stack levels, and SignedAddition and uniform colours on Height.
- Transactions reported only `ValueError` and `RuntimeError`.
- The mesh importer already maps its error kinds to class names (`not_yet_supported` → `NotYetSupported`).

The model panel was consulted: cx/gpt-6-astra and xai/grok-4.5. kimi/kimi-k3 answered HTTP 503 twice.

| Claim | gpt-6-astra | grok-4.5 |
|---|---|---|
| C4 Map by kind, `ErrorClassName(EvalErrorKind)`; move the malformed-argument refusals to a new kind `invalid_argument` → `ValueError` | PARTLY | AGREE |
| C5 The check is the evaluator's DAG build over the whole project, plus an instance rule | DISAGREE | PARTLY |

GPT's objections to C5, all accepted:

- A whole-project DAG check makes an unrelated edit fail when the project already holds a gap.
- It cannot see the refusals that need decoded bitmaps.
- An extra instance rule outside the DAG is already a second policy.
- Transaction rollback protects the document, not caches.

Grok asked that both sides share one code path, and named the cost of walking the whole project on every call.

## Decision

1. Each evaluator error kind maps to one API class (`ErrorClassName` in `evaluator/error.h`):

   | Kinds | API class |
   |---|---|
   | `unsupported_node`, `unsupported_blend_mode`, `unsupported_source` | `NotYetSupported` |
   | `not_found`, `unknown_template`, `invalid_argument` | `ValueError` |
   | `missing_resource` | `ResourceNotFoundError` |
   | every other kind | `RuntimeError` |

   The kinds are not renamed, so their strings stay stable for the open children and their tests.
2. A new kind, `invalid_argument`, takes the four malformed-argument refusals of `diagnostics.cpp`. `unsupported_*` now means only "a feature outside the implemented subset".
3. `core::NotYetSupported` joins the document model's errors. A transaction call that throws it fails with the error type `NotYetSupported`, and nothing is committed.
4. The check before mutation is `evaluator::RequireSupported(before, after)` in `src/evaluator/support.h`. It is the single statement of the Phase 1 boundary for requests: the same list as the `release-gap` entries of `compositor-capabilities.json` (decision 081).
   - It checks only what the request adds or changes: first a colour-management mode other than legacy, then each created or modified node in ascending id order. A project that already holds a gap stays editable elsewhere.
   - The first gap found is reported. The message names the node, the feature and the owner task.
   - An API call runs it on its transaction's working copy (`Edit::base()`, `Edit::project()`).
5. The evaluator keeps its own refusals as a second line of defence:
   - They catch documents opened from disk, and refusals that need decoded inputs: bilinear minification, height-to-normal at resolutions other than 256, a Normal mesh map.
   - These surface on the evaluation request with the same API class. The DAG and projection checks run before any tile is allocated or looked up.
   - Features the evaluator handles without a golden stay evaluable internally, for unit tests and diagnostics. Only requests are refused.
6. The native case `not-yet-supported` is the evidence:
   - 30 excluded features each fail their transaction with `NotYetSupported`, naming the owner task. The document, its revision, its records and its save state are unchanged.
   - The 22 features the evaluator refuses itself fail evaluation with a kind of class `NotYetSupported`. No tile is allocated or looked up.
   - A supported request commits.
   - An edit elsewhere in a project that holds an instance layer commits.

## Consequences

- phase1.19 and phase1.20 bind `core::NotYetSupported` and `ErrorClassName` to `uzpainter.NotYetSupported`. Every mutating API call ends with `RequireSupported`.
- Lifting a gap means editing `support.cpp`, the compositor capability entry and the native case together.
- The check before mutation does not cover refusals that need decoded inputs (point 5). Every export request evaluates before it writes, so no file is written before such a refusal.
