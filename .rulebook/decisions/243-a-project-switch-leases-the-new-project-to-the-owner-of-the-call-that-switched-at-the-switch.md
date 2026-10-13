# 243. A project switch leases the new project to the owner of the call that switched, at the switch

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase2.2_supervisor-admission-ledger, phase2.5_mcp-transport-registry, phase2.8_mcp-server

## Context

The practical end-to-end run (`parity/reports/phase2/practical-e2e.md`, B8) found this over `--mcp-http`:

1. Client A calls `lease_acquire {owner: A}` with no project open. It gets `lease: null`.
2. A calls `project_create` and it succeeds.
3. Client B calls `lease_acquire {owner: B}`, and that succeeds.
4. A's next `layer_insert` fails `lease_held {holder: B}`.

The creator is locked out by a client that did nothing.

The root cause is in the lease model of decisions 139 and 159, not in the HTTP transport. The lease is keyed by project UUID. It is taken in only two ways:

- by `lease_acquire` while the project is open;
- by a mutating call admitted while the project is open.

`project_create` and `project_open` run with no project open, because the worker refuses both while one is open. So nothing takes the lease of the project they make, and it stays free until the creator's next mutation.

The facts the fix rests on:

- The worker runs requests on one command thread, in the order they were sent. Only `worker/cancel` is answered out of order, at once, by the worker's reader thread.
- The worker sends its `revision` event (project, UUID, revision) before the reply of the call that caused it. Every reply of an earlier request reaches the pipe before the next request's events.
- Admission reads the project from `worker.project_uuid`, which the supervisor updates from that event.

### Panel

One round on six claims, with `cx/gpt-6-astra`, `kimi/kimi-k3` and `xai/grok-4.5`:

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C1 The root cause is the lease model: a call that switches project leaves the new project's lease free | AGREE | AGREE | AGREE |
| C2 The owner of the call that switched takes the new project's lease. A live holder is never overridden; a dead holder's lease is taken over | AGREE | AGREE | AGREE |
| C3 The lease is taken in the same event-loop step that makes the new UUID visible, not after the reply | AGREE | AGREE | AGREE |
| C4 The call that switched is the oldest pending request other than `worker/cancel` | PARTLY | PARTLY | AGREE |
| C5 Every owner binds, including the stdio session's. An HTTP session with no owner binds nothing | AGREE | AGREE | AGREE |
| C6 `active_job` is not set on the new lease for the rest of the job; `project_close` still needs no lease | AGREE | AGREE | PARTLY |

The two PARTLY verdicts on C4 had one condition: a request must stay pending until the worker answers it, never only until its caller stops waiting. Otherwise a switch would be attributed to the next request. The implementation meets that condition: a request's frame leaves the pending set only with its reply, or when its worker is replaced. A test cancels the caller's wait and checks that the switch is still attributed to the right request.

Two side remarks were checked:

- GPT on C3: another client's mutation, already admitted on the old project, could run on the new one. This cannot happen. A mutating call or long job of the same project scope is refused `busy`, so it cannot be queued behind the call that switches.
- GPT and Grok on C6: for the short rest of a create job, the lease shows no `active_job`. In that window, `lease_release` by the creator succeeds instead of failing `busy`. This was kept out of scope, by majority. `Session::Create` and `Session::Open` report the switch as their last step, so the window is the job's reply, and only the holder's own `lease_release` can use it.

## Decision

1. **Rule.** When the worker switches to another project during a call, the call's owner takes the new project's lease (`ledger.acquire`). A live holder's lease stays, and the opener then gets `lease_held` at its first mutation. A dead holder's lease is taken over, as before. The owner of the previous project's lease gets nothing from the switch: the lease goes to whoever switched. This covers `project_create`, `project_open` and a script that closes one project and opens or creates another. Each switch event binds on its own.
2. **Timing.** `worker.Supervisor._on_event` records the new project. Then, in the same synchronous step, it calls `on_project_switch` with the frame of the request that caused the switch. No other call can see the new project before its lease is bound. Binding after the reply was rejected, because between the event and the reply another client can take the lease.
3. **Attribution.**
   - Each worker generation keeps the frame of every pending request (`_Generation.sent`), in sending order. A frame leaves the set only with its reply, or when its generation is replaced.
   - `_Generation.running()` returns the oldest frame that is not `worker/cancel`. That is the request the command thread runs when an event arrives.
   - Admission finds its admitted call by that frame and binds the owner it recorded at admission. A later `lease_acquire` by the same session does not change it.
   - Two attributions were rejected:
     - "The call admitted with no project open" picks the wrong owner when a `run_python` script closes one project and opens another while another client's `project_open` is queued.
     - "The call that sees a new project at its reply" picks the wrong owner when an earlier call's coroutine resumes only after the next call's switch event.
4. **Who binds.**
   - HTTP owners and the stdio session's implicit owner bind. For stdio, the lease row now appears at open instead of at the first mutation.
   - A call from an HTTP session that has named no owner is admitted `anonymous` and binds nothing. It can still run `project_open`, which is a read. Before this decision such a call was attributed to the stdio owner. Binding it would have given the project's lease to `stdio:<pid>`, an owner no HTTP client can be.

## Alternatives Considered

- **Carry the lease taken with no project open to the next project.** Rejected. It hands the project to whoever acquired first, not to whoever created it.
- **Refuse lease takes on a project until the call that switched to it ends.** Rejected. It still needs the same attribution, and it adds a refusal state.
- **Put the request id in the worker's `revision` event.** Rejected. It changes the native worker and the IPC protocol for information the supervisor already has from the FIFO order.

## Consequences

- `lease_acquire` before `project_create` or `project_open` now holds the project those calls make. A second client's `lease_acquire` and mutations are refused `lease_held` while the lease is held.
- The tests are:
  - `tests/supervisor/test_supervisor_hold.py::test_a_project_switch_names_the_request_the_worker_runs`, for attribution;
  - `tests/supervisor/test_registry.py::test_a_lease_taken_before_project_create_holds_the_created_project`, for the rule, the anonymous session and stdio;
  - `tests/supervisor/test_mcp_contract.py::test_a_lease_taken_before_project_create_holds_the_created_project[http]`, which reproduces B8 with two HTTP clients through `UzPainter.exe`.
- `src/supervisor/SUPERVISOR.md` (Lease, admission step 3) and `docs/architecture/11-mcp-server.md` §4 state the rule.
