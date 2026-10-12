# 138. A script's key gets no operation row, and typed mutations are tested on a Debug-only `test_mutation` until phase2.6

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase2.2_supervisor-admission-ledger, phase2.6_mcp-typed-tool-families, phase2.4_supervisor-worker

## Context

phase2.2 binds idempotency to the project store's `operation` rows: a known key with the same request hash returns its stored outcome; the same key with other arguments is `idempotency_conflict`; an unknown key follows the precondition rule.

The worker has one mutating tool today, `run_python`. 11-mcp-server.md §6 says each API call inside a script is its own transaction, committed with its own fresh key, and that a script that raises keeps the calls it committed. A script is therefore not a transaction, and no single revision can carry an operation row for the script's own key. Typed single-transaction tools arrive with phase2.6.

The model panel (one round: GPT-6 Astra, Kimi K3, Grok 4.5) voted AGREE ×3 on C1 to C5. On C6 the vote was PARTLY ×2 (GPT, Kimi) and AGREE ×1 (Grok). This decision records C1, C2 and C4; decision 139 records C3, C5 and C6.

## Decision

1. **A script's key gets no row.**
   - The worker decides `run_python` against the stored rows before running it, like every mutating call (`ProjectStore::Decide`). A key already stored by a typed mutation has another request hash, so it is `idempotency_conflict`.
   - An unknown key then follows the precondition rule:
     - `outcome_unknown` when the precondition is missing or below `meta.operation_horizon_revision`;
     - `stale_revision` when it differs from the current revision;
     - execution otherwise.
   - A lost-acknowledgement retry of a script that committed is `stale_revision`, so it never runs twice. A script that committed nothing may run again on the unchanged revision.
   - Only a single-transaction mutation can return a stored outcome.
2. **Typed mutations: the same path for every tool.** A typed tool submits its client's request unchanged (key, original precondition, tool name and arguments) through `Session::Submit` → `ProjectStore::Submit`. The operation row is written in the transaction of its revision, and its outcome is `TransactionResult::ToJson`. A replay returns that object unchanged.
3. **`test_mutation` stands in until phase2.6.**
   - It is a Debug-only typed tool. It exists only under `--test-faults`, like the fault hooks of decision 120.
   - It inserts one fill layer on the active stack. With `fail`, it fails after its edit.
   - The acceptance tests run on it: lost acknowledgement, conflict, beyond retention, failed mutation and unreadable row. phase2.6's typed tools take the same worker path.
4. **The omission rule at the MCP boundary (11 §4):**

   | The client sends | The supervisor |
   |---|---|
   | neither key nor precondition | generates the key (`sup-<uuid>`) and resolves the precondition once from the reconciled revision (0 when no project is open) |
   | a precondition only | generates the key |
   | a key without a precondition | forwards it without one |

   - The supervisor records the key and precondition in the ledger and returns both in the receipt.
   - At the IPC a key without a precondition is admitted to the decision. A known key returns its stored outcome. An unknown key is `outcome_unknown` and never runs, even with no project open.

## Alternatives Considered

- **Wrap `run_python` in one transaction.** Rejected: it contradicts 11 §6 (each call is its own transaction, and a raising script keeps what it committed).
- **A synthetic row for the script's key, with its outcome written later.** Rejected: the row would no longer be atomic with one revision, and a crash between the two writes leaves a half-true outcome.
- **A real typed tool now.** Rejected: phase2.6 owns the families, their names and their schemas.

## Consequences

- phase2.6's typed tools need no further admission work in the worker. Their acceptance repeats §3.1-3.4 on real tools.
- The MCP schema of a mutating tool no longer requires the key and the precondition. Clients that retry keep the receipt's values.
- A retried script answers `stale_revision`, not a stored outcome. Clients that need replayable results use typed tools.
