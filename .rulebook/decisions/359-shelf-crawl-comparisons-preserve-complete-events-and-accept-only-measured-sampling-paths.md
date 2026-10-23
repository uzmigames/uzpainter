# 359. Shelf crawl comparisons preserve complete events and accept only measured sampling paths

**Status**: accepted
**Date**: 2026-10-23
**Related Tasks**: phase1.24_python-api-facade

## Context

The admitted 12.2.0 p22b-host-resources golden records the same ShelfCrawlingStarted (during_step 16) then ShelfCrawlingEnded events in both recordings. Its first recording samples shelves_crawling as true then false; after save/reopen it samples only false. The facade crawl worker starts after the public call returns. Its first in-process observer read races with completion, while the recorder polls through HTTP. Current replay failed solely on the extra true sample. The original observations remain retained.

## Decision

Only p22b-host-resources s16/states and s17/states, for the authored uzp_probe_host_shelf, compare the completed crawl episode rather than the presence of an intermediate poll. On each side require exactly one Started followed by one Ended for that shelf in the corresponding event output; Started bears the current during_step and Ended bears none. Keep complete events, payloads, order and every other state field exact. Accept only boolean trajectories [false] or [true,false], with exactly that shelf in shelves_crawling and identical non-crawl fields across samples. Reduce an optional initial true sample to the final false sample. Any other trajectory, missing event, extra episode, wrong shelf, changed other field or unfinished crawl fails. The comparison contract names raw polling trajectory as unclaimed and describes causal equality; it must not claim raw exactness. This does not alter the shelf implementation or change oracle data.

## Alternatives Considered

- Force synchronous crawling: changes the asynchronous API and event timing.
- Add a delay or rerun until green: hides a scheduler race without a contract.
- Ignore shelves_crawling or event fields: loses causal and completion checks.

## Consequences

Add positive tests for both directions and negative tests for event, state, shelf and trajectory mutations. Preserve raw replay outside the repository. Re-run fresh-build replays repeatedly without trace update; refresh evidence only after comparison passes. Reload-mesh's distinct unstable episode is outside this decision.
