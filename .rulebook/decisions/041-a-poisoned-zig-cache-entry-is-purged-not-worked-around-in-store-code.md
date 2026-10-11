# 41. A poisoned Zig cache entry is purged, not worked around in store code

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.7_store-inspect-census

## Context

In a full `python -m pytest` run, `tests/store/test_store_inspect.py` had 3 cases time out at 900 s and 11 more never ran. Run alone, the cases still hung, so machine load was not the cause. A cdb stack showed `ProjectStore::Close` blocked in `std::mutex::lock` on a store that had just been created, with one thread and no CPU use. The disassembly showed that `Close` (in `save.cpp`) reads `mutex_` at +0x70 and `container_` at +0x30. The PDB layout, from `project_store.cpp`, puts them at +0x78 and +0x38. The 8-byte difference is the `void* handle_` that commit `42316fb` added to `ProjectLock` in `lock.h`. So the word `Close` tried to lock was `portable_` plus heap padding. Its low bit was set, so the lock looked already held. The same mismatch caused the abort with libc++ "locale not supported".

The linked `save.obj` (`.zig-cache/o/073ca663…`) was written at 23:53:31. `lock.h` was last written at 23:53:33. The object's manifest (`h/95884618…`) was written at 23:53:35 and records the new mtime and hash of `lock.h`. Zig 0.15.2 hashes depfile headers after the compile (`Cache.addDepFilePost`). A header saved while a compile runs is therefore recorded with its new hash next to an object built from the old text, and every later build hits that entry. `compact.obj` was poisoned the same way. A build with a fresh `--cache-dir` passed.

## Decision

The fix is to purge the poisoned cache entries. `src/store` and `tests/store` do not change.

- **Object entries removed.** Using the manifest digest (SipHash128(1,3) over the prefix digest and the file digests) to find each output, 25 object manifests and their outputs were removed from the main checkout's `.zig-cache`. Each one recorded a dependency written after its output directory was created.
- **Top-level entries removed.** The 25 library and executable manifests that consumed those sources were removed too.
- **Not done.** No timeout was raised, no case was skipped, and the test does not build with a private cache, which would only hide a poisoned shared cache.

Panel (2026-10-11):

| Claim | cx/gpt-6-astra | kimi/kimi-k3 | xai/grok-4.5 |
|---|---|---|---|
| C1: the root cause is the cache race | AGREE | AGREE | AGREE |
| C2: purge with no code change | PARTLY | AGREE | AGREE |
| C3: prevent recurrence with a coordinator rule | PARTLY | AGREE | AGREE |

GPT's PARTLY votes add one point: derived outputs must be purged too, not the objects alone. The top-level purge does this.

## Alternatives Considered

- Raise the timeout or skip the cases (rejected: hides the defect)
- Build the test with a private cache dir (rejected: covers one test only; every other binary built from the shared cache keeps the poisoned objects)

## Consequences

- **Recurrence.** This will happen again whenever a source in a checkout changes while a `zig build` runs in that checkout. The coordinator's rule: edit in worktrees, or do not edit while a build runs. After a violation, purge the outputs built during the edit window.
- **Other binaries.** Binaries built from the purged entries before 2026-10-11 07:30 (the store test exes, `uzp_store.lib`, `UzPainter.exe`, and the evaluator objects that include `arith.h` from 05:40) were rebuilt or will be rebuilt on the next build. Test sessions that started earlier still run the stale binaries.
