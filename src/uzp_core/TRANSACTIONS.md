# Transactions, operation records and name addressing (`src/uzp_core/`)

Task `phase1.2_docmodel-transactions` (P1-DOCMODEL). Implements the transaction part of D3 in
`docs/architecture/03-project-model.md` §1, §5 and §6, the operation records and the
idempotency/precondition decision of ARC-02 (`02-runtime-topology.md` §3,
`09-project-file-format.md` §4, `11-mcp-server.md` §4) and name addressing (LAY-06,
`10-python-api.md` §5). The project model and its manifest are described in `MANIFEST.md`.

## 1. Layout

| Path | Content |
|---|---|
| `document/document.h` | `Document`: current revision, `Snapshot`, `Checkpoints`, operation records, commit sink |
| `document/nodes.h` | Tree walking (`ForEachNode`) and lookups (`FindStack`, `FindLayer`, `FindEffect`) |
| `transaction/transaction.h` | `Transaction`, `Execute`, `Edit`, `TransactionResult`, `ChangeSet`, `Diff` |
| `operation/operation.h` | `OperationRecord`, `RequestHash`, `MutationRequest`, `DecideAdmission` |
| `naming/naming.h` | `NameScope`, `FindAllByName`, `FindByName`, `ResolveName`, `InsertNamed`, `AmbiguousNameError` |

## 2. Revisions and snapshots

A revision is an immutable `Project` behind a `shared_ptr<const Project>`. `Document::snapshot()`
returns `{revision, project}` at the cost of one pointer copy; it never changes, whatever is
committed later, and stays valid as long as it is held. Copy-on-write happens at revision
granularity: a transaction copies the current revision once, edits the copy and publishes it as a
new revision. The evaluator, exporter and renderers read snapshots only.

`revision` increments by one per committed transaction. `Checkpoints` holds `current` (the current
revision, the store's `checkpoint('current')`), `named` (the revision the last `save()` marked)
and `previous` (the named checkpoint before it). `NeedsSaving()` is `current ≠ named` (SAV-01).
The project store (P1-STORE) persists the checkpoints and opens a document from a
`DocumentState`.

## 3. Transactions

One API call is one transaction: `Execute(document, request, call)`.

1. `Transaction` takes the document lock (a transaction of another thread waits; the same thread
   opening a second one gets `std::logic_error`) and decides the request with `DecideAdmission`
   (§4). Only `execute` opens the transaction; every other decision releases the lock at once and
   is returned unchanged.
2. Each call (`Apply`) edits the private working copy through `Edit`. `Edit::Insert` applies the
   documented insertion rules (`InsertNode`). Composite operations build their subtree detached,
   with ids from `Edit::AllocateId`, and attach it in one step with `Edit::Attach`: the root is
   placed under the insertion rules of its type, the whole candidate is validated, and only then
   does the working copy change.
3. `Commit` validates the working copy. A call that threw, a validation failure or a commit sink
   that threw commits nothing: the document, its revision and its operation records are
   unchanged, no record is produced, and the result is `failed` with the error and the changes
   the call would have made (a failed `Attach` lists its subtree's ids as would-be created). An
   unchanged project is a `no_op`: no revision and no record. Otherwise the next revision and its
   operation record are handed to the commit sink (the store writes both in one SQLite
   transaction) and then published together.

The native `Transaction` (`uzpainter.Transaction`, `10-python-api.md` §7) is the same object
driven call by call: `Apply` per call, then `Commit`. A call that raises fails the transaction;
`Rollback`, or destroying it while open, discards every call. Readers keep reading the committed
revision while a transaction is open.

**Results (QG-03).** `TransactionResult` carries `status` (`committed`, `no_op`, `failed`),
`revision` (the revision after the call), the `ChangeSet` and `returned` (values the calls
return, e.g. the node a named insert resolved). `ChangeSet` lists, ascending: `created`,
`modified`, `removed` and `hidden` ids, and the `imported` and `skipped` resource hashes. A node is
modified when its own fields (not its sub-lists) change, when it moves to another list, or, for
the owner of a list (a stack or a layer), when the surviving members of that list change order.
Texture sets and stacks appear in `modified` when their own fields change. `hidden` is visible →
hidden. `imported` is a hash new in the project; `skipped` a hash an import found already stored
(`Edit::NoteSkippedResource`). `ToJson` gives
`{status, revision, returned, created, modified, removed, hidden, imported, skipped}` plus
`committed_revision` when committed; a failed result has `error {type, message}` and its changes
under `would_change`, so a failure never reads as a success. The error type is `ValueError` for a
`core::ValueError`, `NotYetSupported` for a `core::NotYetSupported` (a release gap refused before
any mutation, decision 082) and `RuntimeError` for any other exception.

## 4. Operation records and the admission decision

`OperationRecord` is `{project_uuid, idempotency_key, request_hash, outcome, committed_revision}`;
`outcome` is the committed result's JSON object, returned unchanged to a retry. The document keeps
the retained records in memory by key; the store persists each one with its revision.

`request_hash` = lower-case SHA-256 of the canonical JSON (`MANIFEST.md` §2) of
`{"arguments": <arguments>, "tool": <tool>}`. It does not depend on the order in which the
arguments were written, and Python computes the same bytes with
`hashlib.sha256(canonical_json({"tool": tool, "arguments": arguments}))`.

`DecideAdmission` is the one decision used by the document, the store and the worker, checked in
this order:

| Condition | Decision |
|---|---|
| The operation records cannot be read | `outcome_unknown` (current revision) |
| Known key, same `request_hash` | `stored_outcome` (the record), even when the current revision is newer |
| Known key, different `request_hash` | `idempotency_conflict` (the record: key, committed revision) |
| Unknown key, no precondition, or one below the pruning horizon | `outcome_unknown` (current revision); never executed |
| Unknown key, precondition ≠ current revision | `stale_revision` (expected, current) |
| Unknown key, precondition = current revision | `execute` |

The horizon is `meta.operation_horizon_revision`, the highest revision compaction has collapsed;
`Document::SetOperationHorizon` records it and drops the records of collapsed revisions. A
precondition equal to the horizon is not expired: a mutation based on it commits above the horizon,
where every record is kept. A failed or no-op call writes no record, so its retry is an unknown
key and follows the same rules. Every request needs a tool name and an idempotency key
(`ValueError` otherwise); a public wrapper that lets callers omit them generates the key and
resolves `expected_revision` once before submission (`11-mcp-server.md` §4).

## 5. Name addressing (LAY-06)

Names are not identity. `FindAllByName` returns every layer and effect of the project with a name,
in tree order. Name-addressed mutations resolve inside an explicit scope
`NameScope {texture_set, stack, parent, node_stack}` (the project is the document the call runs
in): the stack's root layers when `parent` is `kNoId`, otherwise the sub-layers, content effects
or mask effects of `parent`, which must be a layer of that stack. A scope that does not exist
raises `ValueError`. `ResolveName` returns the single match, nothing, or raises
`AmbiguousNameError` (a `ValueError`) whose message and `candidates()` list every matching id, top
first. `InsertNamed` resolves first and changes nothing when the name is ambiguous or names a node
of another type; when the scope already holds a node of that name and type it returns it
(`created` false) and the call is a `no_op`, so repeating a named operation never creates a
duplicate node. Otherwise it inserts at the top of the scope's list.

Ids are persistent (`MANIFEST.md` §3): after a save and reopen through the manifest the same names
resolve to the same ids in the same scopes, a repeated named insert is still a `no_op`, and new
ids continue from `next_id`. Painter's own uids are stable only within one session (PRD LAY-06);
UzPainter's survive save/reopen.

## 6. Tests

`zig build uzp-core-transaction-tests` builds `uzp-core-transaction-tests.exe`
(`tests/uzp_core/transaction_test.cpp`; own code compiled with `-Wall -Wextra -Werror`).
`python -m pytest tests/uzp_core/test_transactions.py` builds it, runs each native case and checks
the request hash against Python's `canonical_json` for several argument objects in two key orders.
Native cases: snapshot immutability; a failed mutation at revision 7 (unchanged document and
revision, no record; its retry executes); composite failure (invalid subtree, forbidden position:
nothing attached, would-be-created ids listed; a valid subtree attached in one revision); the
native `Transaction` (raising mid-way then rolled back, committed after a failure, destroyed while
open: nothing applied; all calls applied in one revision; a second thread waits for the lock and
gets `stale_revision`); change sets and no-ops; the commit sink and checkpoints; the decision table,
one assertion per branch, and the same branches through a document (stored outcome at revision 9
for a key committed at 5, `idempotency_conflict`, `outcome_unknown` without and with an expired
precondition, `stale_revision`, execute); request-hash key order; LAY-06 ambiguity, repeat and
save/reopen; and the integrated round trip of `phase1.3_document-model`: a document built only
through transactions (resource import, fill layer with sources, composite attach, content and
mask effects, a native multi-call `Transaction`, named inserts and their no-op repeat,
metadata) is serialised, reloaded and compared (equal project, bytes and digest), built a
second time to the same bytes, and reopened with its revision, checkpoints and operation
records (a retry returns the stored outcome, new ids continue from `next_id`).
`uzp-core-transaction-tests integrated-manifest` prints that manifest; the pytest runs it in two
processes and asserts the pinned digest, which the hosted CPU lane and the owner's machine
both check (decision 028). No GPU is used.
