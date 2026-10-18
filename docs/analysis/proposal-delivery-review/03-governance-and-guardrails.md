# 03. Governance and guardrails

## F-012 - The clean room is enforced in tooling, not only in text

**Evidence:**
- `docs/licensing-and-clean-room.md:19` lists the off-limits files: Painter's shader `.glsl` files, the `shader-doc/lib-*.html` pages and the shipped MDL. `:11` forbids describing their internals.
- `tools/sources/` implements the approved-source index and a citation check. `tests/sources/test_citation_check.py:43` tests that a citation of `shader-doc\lib-pbr.html` is rejected.
- The repository guard keeps every Painter output in the private store (`parity/GUARD.md`; `phase1.25_pilot-wand/tasks.md:30`).
- The UzEngine copy is attributed with its source commit (`NOTICE:7-19`), and the build refuses any UzEngine path (`build.zig:65`).
- Each fit records its public source and residual in `parity/semantics/*.json` (`licensing-and-clean-room.md:27`). Decision 256 §2, for example, cites *Physically Based Rendering* §9.1.5 and labels its 0.2 band as UzPainter's own constant.

A search of the tree (excluding `thirdparty/`, `zig-out/` and `.git`) for Painter's shader-library names and install paths found only the off-limits list itself, UI preset names (`pbr-metal-rough` as a shader *name*), and the guard's own tests.

**Impact:** Positive. This is the requirement most likely to be broken silently by speed pressure, and it has the strongest automatic protection. Two exposures are already recorded: the pre-sanitisation first commit (`docs/prd.md:232`, release item 8) and the restricted historical analyses (`licensing-and-clean-room.md:29`).

**Confidence:** High for the guardrails. This review did not audit every formula's provenance.

## F-013 - EXC-007 says "approved_by: owner", but the owner did not approve it

**Evidence:** `parity/exceptions.json:223-260` records EXC-007, the Wand padding exception, as `"approved_by": "owner"`. Its own note says "Approved on the owner's delegation to the model panel". Decision 223 (Context, line 16) quotes the owner's answer: "n sei oq quer dizer isso, fale com outros modelos disponiveis no 9 router" ("I don't know what this means; talk to the other models"). The parity contract accepts a divergence only through an *owner-approved* exception (`docs/prd.md:26`, ACC-01; `:207`, ARC-10). The memory note *decide with a model panel* (line 17) lists "signing gate/exception records as the owner" as **not** delegated.

**Impact:** High for the integrity of the acceptance premise ("divergence is a bug", `vision.md:17`). An exception register that the owner has not understood cannot be what makes UzPainter "the same as Painter". This is the first Tier 1 exception, and every later pilot will set this precedent. It also makes the G1 record unsafe: G1 would rely on EXC-007.

**Confidence:** High. The record is transparent in its note, so this is a field-accuracy and sign-off problem, not concealment.

## F-014 - Two of the previous review's four risks are fixed; the other two are still open

**Evidence:** `docs/analysis/plan-purpose-review/` (main `173fb65`, 2026-10-13) raised six findings:

| Earlier finding | Status now | Evidence |
|---|---|---|
| F-001 acceptance cycle (Vulkan → Tunic → MCP → Supervisor → Vulkan) | **Fixed** by a sequencing split. `tools.planning.acceptance_graph` now checks the waits | decision 221; `docs/task-index.md` header |
| F-003 procedural fit versus generalisation | **Fixed in the plan**: declared editable domain, held-out cases fixed before calibration | decision 222 |
| F-005 pilot inputs and owner decisions | **Open**; see F-006 | decisions 192, 194, 196 |
| F-006 duration and packaging assumptions | **Open.** No interim Wand schedule update has been recorded under roadmap rule 9, and no packaging smoke run exists | `docs/roadmap.md:29`, `:33`; `phase1.25_pilot-wand/tasks.md:34` |
| F-002, F-004 | Information only (purpose aligned; research disclosed) | — |

**Impact:** Medium. Plan-level defects are fixed quickly once found. Owner-dependent and schedule items are not, because no step forces them.

**Confidence:** High.

## F-015 - The schedule has not been re-forecast, although the first checkpoint is blocked

**Evidence:** The G0 record revised Phase 1 to "1-2 weeks of elapsed time" from 2026-10-10 (`parity/reports/phase0/gate-g0.md:156`). That window ends on 2026-10-24, and G1 is blocked on F-007. Roadmap rule 9 requires an interim schedule update at a blocked Wand checkpoint (`docs/roadmap.md:33`). Rule 6 requires a full re-forecast when the Wand passes or fails (`:29`). Neither exists: the roadmap's only later edit is the rule text itself (`0cf43b9`). The total is still the original 30-39-week hypothesis (`:20`).

**Impact:** Medium. Without a measured forecast, nobody can tell whether the proposal is on track. The task count (68 tasks and 1,143 items in Phases 3-5, F-004) is not a forecast either.

**Confidence:** High that no update exists. The forecast values themselves are not estimated here.
