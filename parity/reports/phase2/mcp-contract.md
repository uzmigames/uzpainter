# `phase2.8_mcp-server`: MCP contract fixtures (local run)

This task is the parent of P2-MCP (`docs/architecture/11-mcp-server.md` §7 Phase 2). It runs the Phase 2 contract fixtures through MCP clients on stdio and on Streamable HTTP. The numbers are in `mcp-contract.json` beside this file. Decision 186; the children's decisions are 158, 159, 164, 165 and 182.

The runs were on the owner's machine on 2026-10-12, worktree `wt/p2-mcp-server`, Debug `UzPainter.exe` SHA-256 `cad312379c5e4ad8fa939f66d1a52e2f2b1ff1d99a5dca56d4e869967a4915f9`. Both runs built the same bytes. No Painter recording is involved, and no GPU device is created: every supervisor runs a Vulkan worker with Python disabled.

## Synthetic fixtures (2.1)

- **Project.** UzmiGames' plane (`parity/fixtures/meshes/plane.obj`), created at 256 px and saved through the typed `project_create` and `project_save_as` tools. Each test opens its own copy.
- **Long job.** The Debug build's `test_job` under `--test-faults`: 30 steps of 100 ms, with one fill layer committed with its operation row at step 1.
- **Mutations.** The typed `layer_insert`.

## Runs

| Run | Command | Result |
|---|---|---|
| Contract suite (CPU lane) | `UZP_NO_GPU=1 UZP_MCP_CONTRACT_REPORT=… python -m pytest tests/supervisor -m mcp_contract` | 12 passed, 2 failed, exit 1, 132 s |
| Rerun of the failed and changed nodes | the lost-acknowledgement test (both transports) and `test_a_path_outside_the_roots_over_http` | 3 passed, exit 0, 19 s |
| Guard | `python -m pytest tests/parity/test_guard.py` (two invocations, disjoint) | 10 + 69 passed, exit 0 |

The two failures in the first run were mistakes in the new tests:

- The HTTP lost-acknowledgement test read the running jobs from `status`. That tool does not list them; `supervisor_status` does.
- The HTTP roots test did not create its export root, so the supervisor refused to start with a usage error.

The lost-acknowledgement test also gained a changed request with the same key (decision 186, C2). For that reason it was rerun on stdio as well.

## Fixtures (11 §7 Phase 2)

| Fixture | Item | stdio | HTTP |
|---|---|---|---|
| Two writers: the second owner's mutating call is `lease_held {holder, since, active_job}`, also during the holder's long job; its reads work | 3.1 | not applicable (one client) | pass, `test_a_second_writer_receives_lease_held` |
| Lost acknowledgement: the client loses the reply after the commit is reported, then retries. Stored outcome, no second revision, one operation row; a changed request with the same key is `idempotency_conflict` | 3.2 | pass, `test_a_lost_acknowledgement_is_retried_to_the_stored_outcome[stdio]` | pass, `[http]` |
| Worker killed after the durable commit and before the acknowledgement: the same request gives the stored outcome; a changed one gives `idempotency_conflict` | 3.2 | pass, `test_supervisor_admission.py::test_lost_acknowledgement_returns_the_stored_outcome` | pass, `test_commit_then_die_over_http` |
| Reconnect in HTTP mode with lease and job state intact | 3.3 | not applicable | pass, `test_supervisor_transports.py::test_http_transport_guards_and_reconnect` |
| Path outside the roots refused before admission | 3.4 | pass, `test_supervisor_transports.py::test_roots_confine_paths_and_never_echo_them` | pass, `test_a_path_outside_the_roots_over_http` |
| Stale revision: `stale_revision {expected, current}` | 3.4 | pass, `test_a_stale_revision_is_refused_with_both_revisions[stdio]` | pass, `[http]` |
| Known-key replay inside the window after the revision advanced | 3.5 | pass, `test_supervisor_admission.py::test_a_replay_beyond_retention_with_a_lost_ledger_never_mutates` | pass, `test_replays_inside_and_beyond_the_window_over_http` |
| Beyond retention, compacted, ledger lost: replay with the original precondition (`outcome_unknown`) and with none (refused before admission); no mutation | 3.5 | pass (same test) | pass (same test) |
| Capability gaps: every unavailable family is a release-gap tool and refused `capability_gap` before admission; native bake, procedural, paint layer, instances, anchors and `painter_iray` are `capability gap` rows; the `needs Python` rows are exactly the `run_python` rows (none today) | 3.6 | pass, `test_unavailable_families_and_python_needs_are_gaps[stdio]` | pass, `[http]` |

## Open

- **Acceptance of the prerequisites (1.1-1.4).** phase2.4_supervisor-worker is not accepted. It waits on G1, on the Vulkan device cases (decision 121) and on the hosted CPU lane. The three children each have their 1.1 open for that reason.
- **Hosted CPU lane.** It runs on the owner's push. These results are local.
