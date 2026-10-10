# Astra — focused verification after round 4

Date: 2026-10-10.

## Verdict and scope

**Reject for archival.** Of the original 23 findings, **21 are closed, 2 are partially closed, and none is wholly open**. All three original blockers are closed at the documentation level.
There are **2 residual major issues**, plus **3 new major issues and 1 new minor issue**; no new blocker was identified.
The owner's main direction changes are reflected consistently. The remaining issues concern retry safety, delivery atomicity, raster revision identity, and acceptance conditions.
“Closed” means the documentation now supplies the required correction; it does not certify an implementation or an unperformed experiment.
This was a focused, read-only verification of the round-4 changes, not a repeat of the complete architecture or dependency-license audit. No git command, build, application, or MCP bridge was run; no confidential Adobe source was consulted.

Binding input, read first: `C:\Users\Bolado\AppData\Local\Temp\claude\e--UzmiGames-UzPainter\cccef20b-d07a-4705-9871-0e62a15cc979\scratchpad\round4-context.md`. The owner's answers supersede the earlier discussion wherever they change it. Finding IDs below refer to [the previous review](docs-set-astra-review.md).

## Status of the 23 original findings

Architecture references `A01`–`A14` mean the corresponding numbered document under `docs/architecture/`. `PRD`, `ROAD`, `DAG`, `QUEST`, and `LIC` mean `docs/prd.md`, `docs/roadmap.md`, `docs/dag.md`, `docs/open-questions.md`, and `docs/licensing-and-clean-room.md` respectively.

| ID | Original severity | Status | Current document and section; evidence |
|---|---|---|---|
| F01 | Blocker | Closed | A05 §3, A08 §4, LIC §§1.7/6: independently authored public presets are distinguished from private observations, with provenance records; observed structures cannot simply be serialized into shipped assets. |
| F02 | Blocker | Closed | A09 §3: the prohibited implementation description has been removed. The remaining external file observations are expressly permitted by the binding round-4 context. |
| F03 | Blocker | Closed | A03 §2, A06 §2, A14 §6, LIC §1.6: recorded readbacks, defaults, templates and images stay private; public authored inputs and expectations require permitted provenance. |
| F04 | Major | Closed | `docs/README.md` use instructions, `docs/analysis/README.md` introduction, LIC §2, DAG P0-SOURCES/G0: historical inputs are quarantined until exact-revision clearance. `docs/approved-sources.md` is a required Phase 0 artifact, not an existing clearance claimed by this review. |
| F05 | Major | Closed | LIC §3 and A13 §2.4: the selected dependency inventory now addresses D3D12MA, fmt, SPIRV-Reflect and the selected FLIP implementation; EnTT is excluded from the copied slice. Wheel/transitive closure remains explicitly subject to verification, not asserted complete. |
| F06 | Major | Closed | A10 §§0/2/4, A07 §2.2, A14 §2: the documented facade, private pipeline adapter and qualified oracle capture procedure are separate contracts. |
| F07 | Major | Closed | ROAD G0, DAG P0-TOOLCHAIN, A13 §§4.2/7: WARP must be investigated and reported; successful WARP qualification is not a G0 requirement. |
| F08 | Major | Partially closed | A02 §§2/3/5, A09 §4, A11 §4: operation records now commit atomically with revisions, fixing the central defect. Retention and replay rules still contradict each other; see **R01**. |
| F09 | Major | Closed | A02 §5, A10 §5, A11 §6: earlier successful calls survive a subsequent script error; multi-call atomicity requires an explicit native transaction. |
| F10 | Major | Closed | A09 §§1/7: persistent `plane_id`, independent chunk keys, manifest ownership and multi-plane tests address the original same-channel/tile collision. A separate revision-selection defect is **N02**. |
| F11 | Major | Partially closed | A08 §§5/5.1 and PRD EXP-06: generation directories and an atomic pointer fix publication for pointer-aware consumers. Fixed-name consumers remain exposed to incomplete delivery; see **R02**. |
| F12 | Major | Closed | A10 §4, Colour row, and A07 §3.4: declared color configuration is preserved, and unsupported configurations fail before evaluation. |
| F13 | Major | Closed | A07 §§1/5, A13 §2.4: UzPainter capture is windowless; the UzEngine consumer is external. The owner's removal of engine linkage supersedes the conflicting integration route. |
| F14 | Major | Closed | DAG Graph/Gate rule/Nodes and ROAD G0–G5: the missing structural prerequisites and explicit gate joins are supplied; stroke authoring is removed by the owner. New acceptance-level problems are **N01/N03**, not missing graph edges from the original finding. |
| F15 | Major | Closed | PRD LAY-06/07, BAK-07, INT-02/11, ARC-14; A03 identity rules, A06 §4, A08 §5.1, A10 name addressing, A11 §§2/6/7: omitted normative clauses and release conformance obligations are restored. |
| F16 | Major | Closed | PRD VIS-06, ARC-06, §§16–18; QUEST Q2; A07/A14: Iray is explicitly the required render reference. Realtime preview cannot count as render parity. |
| F17 | Major | Closed | QUEST introduction and DAG P0-OWNER: answered decisions are recorded without blanket reapproval; only changes to those decisions need a new decision. |
| F18 | Major | Closed | DAG Task decomposition rule and Critical path; README task guidance: large nodes are parent packages with mandatory child acceptance, and the provisional dependency chain includes the procedural/smart-material leg. |
| F19 | Minor | Closed | ROAD Pilot order and Phases 1–2; DAG P1-WAND/P2-BELT/P2-TUNIC: Wand is Phase 1, then Belt and Tunic in Phase 2. |
| F20 | Minor | Closed | README procedural-content row and A01 component table: the rejected Adobe runtime route is no longer an implementation option. |
| F21 | Minor | Closed | A07 §2.3: the analytic fixture is explicitly proposed, not ratified; production-project reference profiles remain distinct. |
| F22 | Minor | Closed | A06 §1, PRD §17, QUEST Q9: CPU baking is qualified by Windows/CPU/ISA configuration; cross-machine repeatability is measured separately. |
| F23 | Minor | Closed | PRD NFR-03: the recorded capacity workloads are separate, and the combined worst case is labeled a proposed stress fixture. |

## Owner-answer consistency and DAG verification

| Check | Result and evidence |
|---|---|
| Iray, not viewport, is the render target | Consistent in PRD, ROAD Phases 0/2/3/5, DAG P0-FEAS-RENDER/P3-PATHTRACER/P5-REPORT, QUEST Q2 and A07/A14. Converged private references and owner-approved exceptions govern Tier 3. The premature Phase 2 “all modes” promise is N04. |
| Independent copied render code; zero UzEngine dependency | Consistent in PRD §17, QUEST Q8, ROAD, DAG P0-VENDOR/P1-CORE and A01/A13. Source provenance is distinct from a live engine dependency. External UzEngine export validation is a consumer test, not linkage. No positive requirement for an engine pin, patch queue or upstream-PR dependency remains in the targeted documents. |
| No brush authoring; required output coverage remains explicit | Stroke authoring is consistently excluded. Paint content supplied by bitmaps/projections remains supported. The automatic fixture exclusion introduced alongside this change exceeds the recorded scope decision: N01. |
| Windows 10/11; DX12 and Vulkan; local CI | Consistent in PRD §17, QUEST Q9/Q9b, ROAD, DAG P3-VULKAN/P3-PATHTRACER and A02/A06/A07/A13/A14. Linux/macOS references do not establish a supported target. CPU qualification is distinct from GPU requirements. |
| Exact acceptance and exceptions | PRD §18, QUEST Q1, A14 §§1/5 and release gates do not grant preset numerical tolerances. Diagnostic metrics and proposed bounds do not authorize a pass. |
| Other recorded owner answers | QUEST records all 14 answers; documented-API migration, pilot order, UE 5.6/export targets, project retention, opt-in Python, scoped cutover and hypothetical schedules are reflected in the corresponding documents. Retry retention has the implementation-contract inconsistency R01. |
| Clean publication history | PRD §18, ROAD G5 and DAG P5-HISTORY require the clean-history check before publication. This verification checks the requirement only; it neither inspects nor changes git history. |

Static DAG inspection found **49 nodes and 98 edges**, with the Mermaid edges matching the `Inputs` table. The graph is acyclic; task IDs are unique and phase-correct. Every node reaches G5 except the explicitly optional GPU-baker package P4-DXR. Roadmap phases and gate allocations match, and the explicit gate chain includes the mandatory Vulkan, path-tracing and publication-history packages.

The structural graph therefore passes this check. Acceptance semantics do not yet pass: N01 permits bypassing required corpus evidence, while N03 requires later evidence before its prerequisites can close. A connected DAG alone does not resolve either problem.

## Residual major issues

### R01 — Major — F08: pruning makes an unknown idempotency key ambiguous

**Documents/sections:** `docs/architecture/02-runtime-topology.md` §§2/3/5; `09-project-file-format.md` §4; `11-mcp-server.md` §4.

**Evidence:** A09 retains operation rows with retained revisions and uses an operation horizon to reject expired retries. A02 permits `expected_revision: null` and only checks it when supplied. A11 says a key absent from both records and the supervisor ledger was never committed and runs once. After compaction and ledger loss, the absence of a record cannot distinguish a new call from an already committed call. A02 also compares a key's age to a horizon without defining how an opaque key establishes that age.

The durable-commit/lost-acknowledgement case is fixed inside the retained window. The pruning case can still apply a mutation twice.

**Proposed exact replacement contract, shared by all three documents:**

> Each mutation carries an original base revision captured before its first admission and preserved with its idempotency key on every retry. The native IPC requires that precondition; a public wrapper that permits omission resolves it once before submission and preserves it for retries. Check a known key and its request hash before checking the current revision. An unknown key with a missing or expired original precondition returns `outcome_unknown` and is never executed. An unknown key with an unexpired precondition may execute only if that precondition still equals the current revision; otherwise it returns `stale_revision`. The pruning horizon identifies the range for which operation-history completeness is guaranteed. Absence from the supervisor ledger never proves that a mutation did not commit.

**Required settling check:** commit a non-idempotent mutation, advance beyond retention and compact, lose the supervisor ledger, then replay the original key with its original precondition and with no precondition. Neither replay may create another mutation. Known-key replay inside the window must still return the stored result despite a newer current revision.

### R02 — Major — F11: fixed-name consumers can still observe mixed deliveries

**Documents/sections:** `docs/architecture/08-export.md` §§5/5.1; `docs/prd.md` EXP-06 and INT-11.

**Evidence:** A08 §5 atomically publishes a complete generation, but then updates fixed filenames by journalled per-file copying. Recovery runs on the next export or `--recover`. Section 5.1 requires the current consumer scripts to run unchanged. If copying is interrupted, a consumer can read some new files and some old files before recovery. Fault tests currently guarantee coherence for pointer readers, which does not establish EXP-06 for those fixed-name consumers.

**Proposed exact addition/replacement for the fixed-name delivery rule:**

> Every supported consumer reads one complete published generation. A fixed-name consumer runs through a delivery adapter that pins that generation, or under a coordinated publication lock that completes recovery before consumption and excludes writers for the entire read. Staging filenames are not advertised as a committed delivery. A raw fixed-name directory updated by separate copies is not an atomic delivery and cannot satisfy EXP-06. Consumer script code may remain unchanged, but its host adapter and invocation requirements are part of the consumer fixture.

**Required settling check:** interrupt each fixed-name copy and immediately invoke the supported consumer through its prescribed adapter. It must consume one complete generation or fail before consumption; deferred recovery on a later export is insufficient.

## New problems

### N01 — Major — automatic migration exclusions bypass required fixture gates

**Documents/sections:** `docs/roadmap.md`, Dependency policy item 7; `docs/dag.md`, Corpus migration assumption and P3-BRACERS acceptance; `docs/architecture/14-parity-testing.md` §2 and Tier 1 row in §3.

**Evidence:** these sections exclude a required fixture from Tier 1 when documented-API bitmap migration cannot preserve its stroke-authored content. P3-BRACERS explicitly accepts equality, an owner exception, **or** `not_migratable`. The statement that an exclusion does not count as a pass does not prevent the remaining gate from closing without that fixture.

Owner Q5 excludes stroke authoring; it does not automatically remove required migrated assets. Q6 requires proven output equality through documented APIs. PRD §18 items 1–2 requires the certified corpus and an explicit owner decision for a scope reduction. ROAD G3/G4 still require the affected asset comparisons.

**Proposed exact common replacement:**

> If a required fixture cannot be migrated through documented APIs, record `not_migratable` with the reason and keep its affected gate blocked. Excluding or replacing that fixture requires an explicit owner scope decision recorded in the capability manifest and gate report; reporting the limitation alone never closes the gate. Existing paint content may be imported as bitmaps when the documented export route preserves the required output.

Replace P3-BRACERS' acceptance cell with:

> Required fixtures pass their applicable tiers through equality or approved output exceptions. An unavailable fixture blocks acceptance unless an explicit owner scope decision authorizes its exclusion or replacement.

Remove the unconditional exclusion from the Tier 1 corpus row as well. **Settling check:** a gate fixture marked `not_migratable` with no owner scope decision must fail the gate, even if every remaining fixture passes.

### N02 — Major — reverting a manifest can select newer raster pixels

**Document/sections:** `docs/architecture/09-project-file-format.md` §§1/4/7.

**Evidence:** §1 selects, for each plane chunk, the greatest chunk revision less than or equal to the current revision. Section 4 implements revert as a new revision pointing to the old manifest. The manifest identifies `plane_id` but does not bind an immutable plane-content version.

**Counterexample derived from the stated rules, not an executed test:** plane P is red at R1 and blue at R2. R3 reverts to R1's manifest. P still has the same ID; the greatest eligible chunk revision at R3 is R2, so the reverted project reads blue. Persistent plane identity solves F10, but is insufficient to identify the pixels of a retained state.

**Proposed exact replacement:**

> Each retained manifest binds every raster plane to an immutable content version or chunk-root hash. Reads resolve that binding, never the greatest global chunk revision below the current project revision. Revert copies the selected manifest's content bindings unchanged into the new revision. Compaction preserves every chunk reachable from every retained manifest, including chunks first written in revisions no longer retained separately.

Update the schema accordingly and add to §7:

> Verify edit → revert → edit → reopen → compact against the exact raster contents of every retained state, including a protected checkpoint whose chunks were first written outside the retained mutation window.

### N03 — Major — MCP package acceptance requires its own downstream work

**Documents/sections:** `docs/dag.md`, P2-MCP acceptance and dependency chain; `docs/architecture/11-mcp-server.md` §§6/7.

**Evidence:** P2-MCP requires §7 tests and conformance for every required operation family. A11 reserves full conformance for G5, including native bake, later nodes/sources and every capture mode. Their implementations occur after P2-MCP → P2-BELT → P2-TUNIC. Section 7 also places the completed Belt round and cancellation during bake under the P2-MCP settling-evidence heading, although the Belt package depends on P2-MCP and native baking is a Phase 3 package.

The graph has no literal cycle, but interpreting these acceptance statements literally prevents P2-MCP from closing before its downstream packages. Merely moving the full matrix to G5 while retaining the Belt round as a prerequisite of P2-MCP would leave part of the problem intact.

**Proposed exact P2-MCP acceptance cell:**

> Phase 2 typed-tool, transport, lease, error and retry contract fixtures pass on synthetic project/job fixtures; unavailable later families are reported as capability gaps. P2-BELT/G2 accepts the Python-disabled Belt integration round. P3-BAKER accepts native-bake cancellation. P5-REPORT/G5 accepts full Python-disabled conformance for every required operation family after its implementation is available.

Rename A11 §7 to `Settling evidence by milestone` and divide its checks under those same milestones. Maintain the complete requirement-to-typed-operation matrix from Phase 2; require all rows to pass at release. **Settling check:** every package acceptance check must be runnable using that package and its predecessors, with later integration evidence attached to the later gate instead.

### N04 — Minor — Phase 2 still promises capture in all modes

**Documents/sections:** `docs/architecture/07-preview-and-render-parity.md` §8; `docs/dag.md`, P2-PREVIEW outputs.

**Evidence:** both promise capture in all modes in Phase 2, while `painter_iray` is one of the defined modes and is implemented by P3-PATHTRACER in Phase 3. ROAD correctly treats Phase 2 as preview only.

**Proposed exact replacement:**

> Phase 2 provides capture for preview and diagnostic modes; `painter_iray` remains an explicit unavailable capability until P3-PATHTRACER passes.

## Clean-room findings

No new prohibited Adobe implementation description was found in the final documents during this focused verification. The corrections to F01–F04/F06 preserve the separation between permitted public documentation, independently authored implementation inputs and private recorded outputs. MDL references distinguish permitted public specification/SDK inputs from forbidden Painter-shipped implementation material.

Historical analyses are not automatically cleared by their presence in the repository or by a link. The approved-source index and exact-revision audit remain P0-SOURCES/G0 deliverables. Likewise, the publication-history cleanup and dependency closure remain gates, not completed actions asserted by this review. Nothing here authorizes confidential sources or private oracle data to become public.

## Final disposition

**Reject for archival until R01, R02 and N01–N03 are corrected.** N04 is a minor wording correction. The owner's architecture direction does not need to be reopened; the required changes make recovery and acceptance contracts consistent with that direction.
