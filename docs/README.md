# UzPainter documentation

UzPainter is an AI-operated texturing tool that replaces Adobe Substance 3D Painter in the Assets3D pipeline. It is a separate system from UzEngine: it vendors only the rendering code it needs and has no engine dependency (decision 021). These documents are the build contract: they tell engineers and AI agents what to build, in which order, and how acceptance is measured. Analyses and the architecture discussion that produced them live under `docs/analysis/`.

Historical analyses and discussion files are not implementation inputs until an itemised clean-room provenance audit approves their exact revision in the approved-source index (`docs/approved-sources.md`, work package `P0-SOURCES` in `dag.md`). Do not use descriptions derived from off-limits implementation files, including descriptions repeated by an intermediary. The implementation reading guide below links only to approved summaries, permitted public documentation and approved behavioural observations.

## Reading order

| Read | Before doing |
|---|---|
| `vision.md`, `prd.md`, `licensing-and-clean-room.md` | Anything. The PRD is the numbered requirement list; every architecture doc cites the requirements it satisfies. The clean-room rules bind every contributor and agent before a single file is opened. |
| `architecture/01-overview.md` | Any implementation work. Vocabulary, components, process roles, data flow. |
| `architecture/14-parity-testing.md` | Any implementation work. Acceptance is measured there; nothing is "done" without its tier passing. |
| `roadmap.md`, `dag.md` | Planning or creating rulebook tasks. The DAG ids are stable parent work packages; split a large parent into independently reviewable child tasks before creating implementation tasks. |
| `open-questions.md` | Anything touching an owner decision. Every question is answered (2026-10-10); each row names the rulebook decision that records the answer. |

## Documents

| File | Content |
|---|---|
| `vision.md` | Product definition, owner requirements, acceptance premise (decision 001), licence and clean-room decision (002), non-goals, success metrics |
| `licensing-and-clean-room.md` | Apache-2.0 release, clean-room rules (what may and may not be consulted), third-party dependency inventory with licence compatibility |
| `prd.md` | Product Requirements Document: numbered requirements with priority, source, acceptance criterion and satisfying architecture doc; personas; constraints; v1 release criteria |
| `architecture/01-overview.md` | System context: components, process roles, threads, data flow, shared vocabulary |
| `architecture/02-runtime-topology.md` | Supervisor/worker processes, IPC vocabulary, threads, GIL rules, failure and recovery model |
| `architecture/03-project-model.md` | Project, texture sets, stacks, channels, resources, mesh maps, revisions, identities |
| `architecture/04-layer-stack-and-compositing.md` | Layer/effect data model, per-channel blend and opacity, masks, anchors, smart presets, evaluator and quantisation rules |
| `architecture/05-procedural-content.md` | Independently implemented certified resource families and project-private frozen snapshots behind `IProceduralBackend`; no Adobe runtime adapter or redistributed Adobe content |
| `architecture/06-baking.md` | Ten bakers, Painter parameter names, Embree-first with an optional GPU baker later (DX12 DXR and Vulkan ray query), external mesh maps, evidence outputs, job model |
| `architecture/07-preview-and-render-parity.md` | Painter's Iray as the render-parity target: private Iray reference capture, clean-room path tracer on DXR and Vulkan ray tracing, stochastic comparison through the exception register; realtime viewport as preview and fast check; capture |
| `architecture/08-export.md` | Painter-compatible export configuration, presets (PBR, Blender, Unreal ORM for UE 5.6, glTF, UzEngine `.uztexture`/`.uzmat`), determinism, consumer fixtures and reported gaps |
| `architecture/09-project-file-format.md` | `.uzp`: self-contained SQLite + zstd blobs + JSON manifest, revisions and retention, autosave, versioning, size budget |
| `architecture/10-python-api.md` | `uzpainter` native API, `substance_painter` facade, capability manifest, events, errors |
| `architecture/11-mcp-server.md` | MCP topology, tools and typed operation families, jobs, lease, path roots, opt-in `run_python` |
| `architecture/12-mesh-import.md` | Mesh formats, texturing mesh, tangents, certification, reload |
| `architecture/13-engine-integration.md` | Render core vendored from UzEngine with zero engine dependency, own build, DX12 and Vulkan backends, Windows platform, packaging |
| `architecture/14-parity-testing.md` | Four-tier golden corpus, exact-equality gate, owner exception register, private oracle store, CI lanes |
| `roadmap.md` | Phases with acceptance gates, pilot order, durations as labelled Hypotheses |
| `dag.md` | Work-package dependency graph with stable parent ids (rulebook task ids), gate nodes, provisional dependency chain, parallelism |
| `open-questions.md` | Owner questions Q1–Q14 and the repository-history criterion, with the owner's answers of 2026-10-10 and the decisions recording them |
| `analysis/README.md` | Index of the analyses, the Astra reviews, the review responses, the clean-room redaction record and the architecture discussion (files 01–06) |
| `analysis/clean-room-redactions.md` | Record of the clean-room sanitisation pass over `docs/analysis/`: every redaction by file and category, and the borderline passages kept with the reason |
| `analysis/substance-parity/08-review-response.md`, `analysis/assets3d-pipeline/09-review-response.md`, `analysis/uzengine-renderer/10-review-response.md`, `analysis/technology-options/05-review-response.md` | Review responses: per-finding dispositions of Astra's four analysis reviews and the corrections applied to the analyses |
| `analysis/reviews/docs-set-astra-review.md` | Astra's final review of this documentation set: document verdicts, 23 findings (3 blockers), licence audit |
| `analysis/architecture-discussion/06-round4-changes.md` | Round-4 change record: how the owner's answers of 2026-10-10 and the docs-set review were applied to this set |

## How to use these docs when building a subsystem

1. Find the subsystem's work package in `dag.md`; its inputs tell you which other packages must be accepted first and which decision (`Dn`) it implements. Before creating implementation tasks, split a large parent into child tasks with their own artifact, acceptance fixture and prerequisite edges (ids `phase<N>_<kebab-name>`); the parent closes only when all mandatory children pass.
2. Read the architecture doc for that decision and the requirements it lists from `prd.md`.
3. Read `14-parity-testing.md` for the tier that gates the work, and `open-questions.md` and `.rulebook/decisions/` for the owner answers you depend on; if your work would change a recorded decision, stop and raise it (`rulebook_task {action:"ask"}`) instead of choosing silently.
4. Evidence conventions: a statement without a label is settled by the cited source or by a recorded decision under `.rulebook/decisions/`; historical analyses and discussion files are context, not implementation inputs, until cleared (see above). **Fact** marks a verified observation whose path is given; **Hypothesis** marks an unverified inference or estimate; **Recommendation** marks a design choice. Durations are always Hypotheses.
5. Path aliases used across the docs: `UZP` = `E:\UzmiGames\UzPainter`, `A3D` = `E:\UzmiGames\Assets3D`, `UZE` = `E:\UzmiGames\UzEngine`, `PAINTER` = `C:\Program Files\Adobe\Adobe Substance 3D Painter`.

## Status

Documentation only; no source code exists yet. Every owner question is answered (2026-10-10, `open-questions.md`). Rulebook decisions under `.rulebook/decisions/`: 001 output parity, 002 Apache-2.0 and clean room, 003–016 the D1–D14 outcomes, 017–027 the owner's answers of 2026-10-10. Decisions 004, 008 and 014 are superseded by 019 (D2), 018 (D6) and 021 (D12); every other decision is accepted.
