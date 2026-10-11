# 37. Rolling Painter oracle: acceptance follows the installed Painter build through transactional envelope refreshes

**Status**: accepted
**Date**: 2026-10-11

## Context

Owner statement, 2026-10-11, binding: Creative Cloud auto-update stays on and the project must adapt ("eu não vou desabilitar atualização automática, você que precisa se adaptar"). Painter moved 12.1.0 -> 12.1.5 after the 82-golden corpus was recorded; with auto-update on and no freezing, 12.1.0 can no longer serve as a live oracle, so decision 036 (12.1.0 acceptance, 12.1.5 research) no longer holds. Design settled by the model panel (cx/gpt-6-astra REJECT pending transactional fixes, cx/gpt-5.6-sol and xai/grok-4.5 and kimi/kimi-k3 ACCEPT-WITH-CHANGE); all four named a mixed-build corpus during a multi-hour re-record as the main failure mode. On whether the owner's statement replaces decision 001's 12.1.0 pin the panel split 2-2; it is recorded here as the owner's decision derived from that statement, reversible by the owner. Historical context: docs/analysis/multi-model-review/.

## Decision

1. The acceptance oracle is the current envelope: the Painter build of the newest promoted envelope. Decision 001's pin to 12.1.0 is replaced by it; decision 036 is superseded. 2. Detection: every recorder run and the local parity gate read the running Painter build first; an unseen build starts the refresh procedure automatically, with no human step. 3. Refresh is a transaction: the 10-golden canary, then a full unattended re-record of the texture corpus (tiers 0-2) under a candidate envelope, always in full because goldens are immutable per build and a canary cannot prove the rest unchanged. The running build and environment are verified on every capture and at the end; any change or unverifiable identity aborts the candidate, quarantines its partial outputs and restarts against the new build. The candidate is promoted atomically only when complete, internally consistent, schema-valid and its drift report (unchanged / changed per golden) is published; until then the previous envelope stays current. 4. Gates and parity verdicts use the current envelope only. A golden whose Painter output changed becomes a tracked divergence task for UzPainter; an old-envelope pass never carries over. Semantics fits are re-checked against each new envelope and re-opened when they no longer hold. 5. Evaluator profiles: a new profile id is minted when any Tier 0 semantics golden changes between envelopes (objective rule); existing UzPainter projects keep the profile they were created with and are verified against that profile's envelope history; current-envelope parity claims cover current-profile projects. 6. Tier 3: Iray references from an older envelope are stale; Tier 3 results against them are reported stale, never pass, and no whole-product parity is claimed while required references are stale; they are refreshed at the next operator session. 7. Previous envelopes, their goldens, fits and verdicts are kept as history.

## Alternatives Considered

- Keep 12.1.0 as acceptance (decision 036; rejected: owner keeps auto-update on, so 12.1.0 can never be re-recorded)
- Conditional re-record when the canary shows no drift, aliasing goldens to the new build (rejected: a 10-golden canary cannot prove the other goldens unchanged)
- Human acknowledgement before promoting an envelope (rejected: owner forbids being asked; replaced by objective promotion criteria)
- Check the build only at run start (rejected: an update mid-run would mix builds under one envelope)

## Consequences

phase0.9_oracle-envelope implements detection, the transactional refresh and promotion. The first refresh promotes 12.1.5 once its full texture corpus is recorded; until then 12.1.0 stays the current envelope. Each Painter update costs one unattended corpus re-record and may open divergence tasks. Owner may reverse the acceptance reading of this decision at any time.
