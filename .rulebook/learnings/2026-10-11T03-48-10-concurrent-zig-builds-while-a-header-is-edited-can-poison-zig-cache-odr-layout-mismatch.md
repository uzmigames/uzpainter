# Concurrent zig builds while a header is edited can poison .zig-cache (ODR layout mismatch)
**Source**: manual
**Date**: 2026-10-11
**Tags**: zig, build-cache, concurrency, debugging, store
What happened (2026-10-11): an agent edited src/store/lock.h (ProjectLock gained a `void* handle_`) while other agents/sessions were running `zig build` and pytest conftest builds against the same repo `.zig-cache`. The cache stored an object compiled against the OLD header under the NEW header's hash. Result: one binary with two sizes of ProjectLock, so ProjectStore::mutex_ was read at the wrong offset. Symptom: uzp-store-inspect-tests hung forever at 0% CPU; cdb stack showed ~ProjectStore -> Close -> lock_guard<std::mutex> on a mutex no thread held (RtlAcquireSRWLockExclusiveContended). Misdiagnosed at first as a lock-race bug in the new code.

How to detect: a deadlock/crash/garbage that appears right after a struct layout change, only in some test executables, with an uncontended mutex in the stack. Rebuild with an empty cache: `zig build <step> --cache-dir <empty dir>` (pytest conftest builds honour ZIG_LOCAL_CACHE_DIR). If it passes, the cache is poisoned, not the code.

Fix: clear `.zig-cache` when no session is building, or keep using a fresh --cache-dir / ZIG_LOCAL_CACHE_DIR. Prevention: when several sessions/agents share the tree, do not build while another one is mid-edit on a shared header; give parallel agents disjoint headers, or isolated cache dirs.