# Proposal delivery review

Is UzPainter's original proposal being delivered, or has it been lost among the tasks? The proposal is in `docs/vision.md` and `docs/prd.md`: an AI-operated replacement for Substance Painter in the Assets3D pipeline, with the same output, clean room, DX12 and Vulkan, and MCP. This is a static review of main `c07e787` (last commit 2026-10-13), written on 2026-10-18. No build, test, Painter session, task or golden was run or changed. It follows up `../plan-purpose-review/` (main `173fb65`). Clean-room scope: only repository documents, reports and code were read; no Adobe implementation file was opened.

## Answer

**The proposal is not lost, but it is not being delivered yet.** The documents still state every owner requirement, and they report progress honestly (F-001). What exists is a working AI-operated foundation (F-003). What is missing is any delivered piece: no gate past G0, and the simplest pilot's export is refused (F-002). Native bake, the Iray path tracer, Vulkan, the engine presets and packaging have no implementation (F-004).

The cause is where the effort went, not the number of tasks:

- an open-ended exactness hunt on one Wand item, with no recorded budget (F-007);
- preview polish on a component the contract does not count (F-008);
- Phase 2 built ahead of G1, with its acceptance waiting on that one Wand item (F-009);
- colour fits wider than the pilots need (F-010);
- process records growing as fast as the product (F-011).

One governance fix is urgent. The first Tier 1 exception is recorded as owner-approved, but the owner had said he did not understand it (F-013).

| Requirement | State |
|---|---|
| AI-operated over MCP, headless | Delivered and exercised end to end (DX12) |
| Python API mirror | Delivered for the pilot scripts; about 35 % of Painter's capability entries are `supported` |
| Render core from UzEngine, zero dependency | Delivered (DX12) |
| Same textures as Painter | Exact on fitted primitives and on the Wand's island interiors; no complete piece |
| Same render as Iray | Research only; `painter_iray` unavailable |
| Native bake | Not started |
| PBR, Unreal ORM, UzEngine export, compressed | PNG/EXR only; engine presets not started |
| Compact save | Delivered; 10 % budget met for 1 of 5 projects on partial content |
| DX12 + Vulkan, standalone `.exe` | DX12 only; packaging not started |
| Clean room, Apache 2.0 | Enforced by tooling |
| Replaces Painter in Assets3D | 0 pieces |

## Reading order

1. [Requirement delivery](01-requirement-delivery.md): F-001..F-006. Requirement-by-requirement scorecard: what is delivered, partial or missing.
2. [Where the effort went](02-effort-allocation.md): F-007..F-011. Decision and commit themes against the critical path.
3. [Governance and guardrails](03-governance-and-guardrails.md): F-012..F-015. Clean room, exception sign-off, the previous review's follow-up, the re-forecast.
4. [Execution plan](04-execution-plan.md): six stages, from an owner yes/no package to G1 under a hard budget, a work-in-progress limit, the pilots, long-pole spikes and delivery reporting.

## Findings index

| ID | Title | Impact | Confidence |
|---|---|---|---|
| F-001 | The original proposal is intact and stated honestly | Positive | High |
| F-002 | Nothing usable for production has shipped; the Wand export is refused | High | High |
| F-003 | The foundation works end to end | Positive | High |
| F-004 | Bake, path tracer, Vulkan, engine presets and packaging have no implementation | High | High |
| F-005 | About a third of Painter's surface is supported, and the gaps are visible | Medium | Medium |
| F-006 | The production pilots depend on owner actions with no date | High | High |
| F-007 | The Wand's last mile is an open-ended hunt with no budget | High | High |
| F-008 | Preview polish took the latest work | Medium | High |
| F-009 | Phase 2 was built ahead of G1 and waits on one item | Medium | High |
| F-010 | Colour and export fits went wider than the pilots need | Low-Medium | Medium |
| F-011 | Process records grew as fast as the product | Medium | Medium |
| F-012 | The clean room is enforced in tooling | Positive | High |
| F-013 | EXC-007 says owner-approved, but the owner did not approve it | High | High |
| F-014 | Two of the previous review's four risks are fixed; two are open | Medium | High |
| F-015 | No re-forecast while the first checkpoint is blocked | Medium | High |

## Baseline numbers

- 538 commits, 2026-10-10 to 2026-10-13. 203 decision records.
- Tasks: 75 archived, 90 open. 1,259 open checklist items in all, 1,143 of them in Phases 3-5, where none is checked.
- Gates: G0 accepted. G1 to G5 open.
