# 159. HTTP mode guards Origin, Host and bearer in front of the SDK, binds the lease to a named owner, and keeps handlers async

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase2.5_mcp-transport-registry, phase2.2_supervisor-admission-ledger, phase2.8_mcp-server

## Context

11-mcp-server.md §1 and §4 ask for these things in HTTP mode:

- Streamable HTTP on `127.0.0.1:<port>` with `--mcp-http`;
- Origin validation;
- a bearer token, generated at start or given by `--token`;
- no non-loopback bind without `--allow-remote`;
- an explicit lease (`lease_acquire {owner}`, `lease_release`, `lease_status`);
- "client reconnect keeps lease and job state";
- logs on stderr and in the ledger;
- handlers that "run in an executor so the event loop keeps serving progress and cancellation".

The facts these choices rest on:

- The pinned SDK (2.3.0) ships a DNS-rebinding check that lets an absent Origin through and takes host lists with `:*` port wildcards. It has no simple bearer check without its OAuth machinery.
- The lease table (decision 139) keys one lease per project UUID to a holder string and the holder's process id.
- The pipe client is asyncio overlapped I/O.

The model panel round is the one shared with decision 158.

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C3 The lease belongs to a named owner, bound to the MCP session by `lease_acquire`; a reconnecting client names it again | PARTLY | AGREE | AGREE |
| C6 The supervisor's own ASGI guard checks Origin, Host and the bearer token | PARTLY | AGREE | AGREE |
| C7 Async handlers; only filesystem canonicalisation runs in the executor | PARTLY | AGREE | AGREE |

Refinements adopted:

- C3: `lease_release` ends only the calling session's owner. It keeps the lease while that owner's job runs. The owner name is coordination, not authentication: every HTTP client already holds the bearer token. That is stated in SUPERVISOR.md (Kimi, GPT).
- C6: the Host list is fixed: `localhost`, `127.0.0.0/8` and `[::1]`, any port. Under `--allow-remote` the Host check is off, and a stderr warning says that the token is then the only guard and the traffic is plain HTTP. The bearer is checked on every method (Kimi, GPT).
- C7: the ledger's SQLite connection stays on the event loop's thread, so a log record from another thread reaches stderr only (Kimi raised the thread question).

Refinements not adopted:

- GPT's TLS and remote origin allowlist. A remote bind is an explicit, trusted-network opt-in, and the task asks for loopback by default.
- Moving ledger writes onto a thread (Kimi). Each write is a short local transaction that records admission state. Running it off the loop would reorder it against that state.

## Decision

1. **Transport.**
   - `--mcp-http <host>:<port>` serves the SDK's Streamable HTTP app at `/mcp` on uvicorn, inside the supervisor's event loop.
   - A host that is not loopback is a usage error without `--allow-remote`. `--token` and `--allow-remote` without `--mcp-http` are usage errors too.
   - The SDK's own DNS-rebinding check is switched off, and the guard below replaces it. The SDK still checks media types.
   - The address is logged once uvicorn listens.
   - Ctrl+C and Ctrl+Break stop the server cleanly; the supervisor's override keeps uvicorn from raising the signal again afterwards. Each worker starts in its own process group, so a console signal reaches the supervisor and never the worker.
2. **Guard (an ASGI app in front of the SDK).**
   - A present `Origin` must be an `http` origin on a loopback host: 403 otherwise.
   - With a loopback bind, `Host` must name a loopback host: 421 otherwise.
   - `Authorization: Bearer <token>` is required on every request and compared in constant time: 401 with `WWW-Authenticate: Bearer` otherwise.
   - A generated token (`secrets.token_urlsafe(32)`) is printed once on stderr and never logged, so it never reaches the ledger.
3. **Lease.**
   - HTTP sessions are told apart by `Mcp-Session-Id`.
   - `lease_acquire {owner}` binds the owner to the session and takes the open project's lease through the admission's `check_lease`, with `holder_pid` the supervisor's. Another live owner's lease is refused with `lease_held`.
   - A mutating call from a session with no owner fails `lease_required` before admission.
   - The lease belongs to the owner, so a reconnecting client names the same owner and gets it back. Jobs are read by id from the ledger, whatever the session.
   - Owner names match `[A-Za-z0-9._@-][A-Za-z0-9._:@-]{0,127}`. Names that start with `stdio:` are reserved.
   - The supervisor releases its owners' leases when it ends. The lease tools are listed only in HTTP mode; stdio keeps its implicit owner.
4. **Logs.** The ledger gains a `log` table (version 2) that holds every INFO-or-higher record logged on the loop's thread, with time, level, supervisor and message. It keeps the newest 10 000 rows. stdout stays protocol-only through the SDK's descriptor diversion.
5. **Executor.** Handlers stay coroutines over the overlapped pipe. The canonicalisation of root paths, the one blocking filesystem step, runs in `asyncio.to_thread`. A mutating or long call that would be `busy` skips the reference lookup, so it is refused at once rather than waiting behind a running long job.

## Alternatives Considered

- **The SDK's TransportSecuritySettings.** Rejected: it lets an absent Host through only when a list entry matches, and it cannot express "any loopback address".
- **The SDK's OAuth bearer middleware.** Rejected: it needs a token verifier and resource metadata that a static local token does not have.
- **A lease bound to the connection.** Rejected: it would be lost on every reconnect, against 11 §4.
- **The pipe protocol on executor threads.** Rejected: the overlapped asyncio client already never blocks the loop.

## Consequences

- phase2.8's acceptance attaches the HTTP tests (test_supervisor_transports.py, test_transport_http.py) to P2-MCP.
- A sessionless request (the 2026-07-28 single-exchange protocol) has no owner and cannot mutate in HTTP mode until the SDK offers a per-client identity.
