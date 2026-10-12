# 151. A Debug UzPainter compiles the store fault hooks, so the worker can be killed inside a save

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase2.4_supervisor-worker, phase2.1_supervisor-ipc-worker, phase1.8_project-store

## Context

`docs/architecture/02-runtime-topology.md` §7 asks to kill the worker during a save. A save names a checkpoint in one store transaction. A full save then compacts the file through `VACUUM INTO` and a rename.

The worker's fault hooks (decision 120) can kill it before or after a call, but not inside the store. The store has its own test-only hooks (`src/store/fault.h`): a kill at the first page write of a `COMMIT`, a kill while `VACUUM INTO` writes, and others. These were compiled only into the store's test executables, and they work through a forwarding SQLite VFS that every connection uses once they are compiled in.

A kill from outside on a timer, or from a Python thread watching for the journal file, would race the save.

Panel round (one round, shared with decision 150), claim C3:

- Grok: AGREE.
- Kimi: PARTLY. Agrees with the mechanism. Asks that the compaction case check that no partial copy is left. Its timing concern belongs to decision 150.
- GPT: PARTLY. Asks that the fault be scoped to the save's own transaction, not to "the next COMMIT", and that the integration be validated.

## Decision

1. **Build.**
   - A Debug `UzPainter.exe` compiles the store sources with `UZP_STORE_FAULT_HOOKS`, and `src/store/fault.cpp` with them. It does not link `uzp_store.lib`.
   - The worker sources get the same define in Debug.
   - Release builds (ReleaseFast, ReleaseSafe, ReleaseSmall) still link the hook-free library, which has no hook code and no forwarding VFS.
2. **Faults.** The worker's `test_fault` (Debug, `--test-faults`) gains two faults. Each only records a pending store fault.
   - `kill_during_save` maps to the store's `kill_during_commit`.
   - `kill_during_compaction` maps to the store's `kill_during_vacuum`.
3. **Scope.**
   - `project_save` holds a `SaveFaultScope`. The scope arms the pending fault on entry and disarms the store's fault when the save returns or throws.
   - A save fault therefore acts only inside the next `project_save`'s own commit or compaction, never on another call's commit.
4. **Assertions** (`tests/supervisor/test_settling.py`, both cases):
   - The save is answered `interrupted` (`terminated`, exit 77), and the session stays alive.
   - The relaunched worker holds the last committed revision.
   - The key's operation row is still there, and no `.compact` or `.vacuum` leftover remains.
   - A later save shows which checkpoint survived: none after the torn commit (rolled back from the hot journal), or the killed save's own checkpoint once its commit was durable and the compaction died.

## Alternatives Considered

- **Kill the worker from outside during a slow save.** Rejected: racy, and a pass would not prove the kill landed inside the save.
- **A worker-level kill just before or after the save.** Rejected: it is not "during", and it never reaches the store's commit or its compaction.

## Consequences

- Every connection of a Debug `UzPainter.exe` goes through the forwarding VFS, which is inert unless armed. The store's test suites already run on it.
- The store's DELETE journal is unchanged. The VFS has no shared memory, which this journal mode does not need.
- Debug builds compile the store sources a second time.
