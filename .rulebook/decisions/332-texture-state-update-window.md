# 332. TextureStateEvent UPDATE dispatches are compared as distinct (action, channel type) pairs within their causative window s7–s8; ADD and REMOVE stay exact per step

Date: 2026-10-20. Status: accepted (Claude and Codex, SUP-197; routine technical choice delegated by the owner). Amends decision 297 §3.3.
Related: phase1.24_python-api-facade item 4.1, decisions 297, 319 and 330, golden `tier0/api-probes/p22b-host-events`.

## Context

`p22b-host-events` records Painter's `TextureStateEvent` dispatches. Its two recordings deliver the UPDATE caused by the same edit in different steps: s8 in r1 and s7 in r2. Painter delivers it asynchronously from its event loop, so its step attribution is not stable in Painter itself. Decision 297 §3.3 asked for distinct (action, channel type) pairs per step. A per-step comparison would fail on Painter's own two recordings.

UzPainter is gaining a real texture observer (Codex, SUP-197):
- native: session.cpp, session.h and bind_misc.cpp;
- Python: `python/uzpainter_facade/texture_state.py`.
It emits real invalidation events. No harness code fakes them and no oracle data is replayed.

## Decision

1. **UPDATE.** The replay compares the set of distinct (action, channel type) pairs that the UPDATE dispatches carry within the causative window s7–s8, the steps between the edit and the next call that observes it. It does not attribute them to a single step.
2. **ADD and REMOVE** are compared exactly, in their step.
3. **Raw outputs are kept.** Every dispatch stays in the recorded output. The window rule is applied in the comparison, and nothing is excluded wholesale.
4. **Not claimed:** cache keys and texture ids carried by the events. Under decision 297 their parity is unrecorded, and no symbol is promoted on them.
5. **Item 4.1 closes on this point** only when UzPainter's observer emits the pairs Painter emits, within the window.

## Consequences

- The comparison tolerates Painter's own asynchronous attribution and nothing else.
- Any UPDATE outside s7–s8, or any missing pair, fails the replay.
