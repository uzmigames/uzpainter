# 11. D9 Python API: native uzpainter plus a substance_painter facade with Painter's observable behaviour

**Status**: accepted
**Date**: 2026-10-10
**Related Tasks**: phase2_docs-architecture

## Context

The pipeline scripts must run unchanged; Painter's lifecycle is asynchronous and event-driven; some quirks change output (05-resolution.md D9).

## Decision

uzpainter is the typed native API (synchronous conveniences over jobs and revisions); substance_painter is a facade written from the public python-doc that reproduces the documented asynchronous lifecycle, event order on a dedicated dispatcher thread, readiness barriers, an explicit computation-enable state model and output-affecting quirks (active-channel reset); __slots__ handles, readback-verified mutations, explicit (set, stack) addressing, atomic composite operations, persisted node ids, typed errors, a named compatibility profile. See docs/architecture/10-python-api.md.

## Alternatives Considered

- Only a substance_painter-compatible package - rejected: no room for safer native behaviour
- Only a new uzpainter package - rejected: scripts would change
- Synchronous facade with immediate events (Claude round 1) - rejected after Astra showed the readiness/reentrancy contract

## Consequences

Tier 0 callback-trace and quirk goldens; two documented behaviours where the native API differs from the facade.
