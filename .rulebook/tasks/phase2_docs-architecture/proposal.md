# Proposal: phase2_docs-architecture

## Why
The owner asked for UzPainter, a 100% AI-operated replacement for Adobe Substance 3D Painter built on UzEngine, with output parity (same instruction sequence → same textures and renders) as the acceptance criterion (`.rulebook/decisions/001-acceptance-criterion-output-parity-with-substance-painter.md`). Phase 1 produced ~700 KB of analyses (`docs/analysis/substance-parity`, `assets3d-pipeline`, `uzengine-renderer`, `technology-options`) and three Astra reviews that raise blockers (no parity contract, unpinned UzEngine baseline with merge-conflict markers, a 32/48-byte stride defect). No architecture exists yet that answers the 14 open decisions (runtime topology, API scope, layer model, procedural strategy, baking, render parity, export, project format, Python API shape, MCP, mesh import, engine integration, parity testing, roadmap).

## What Changes
Three rounds, all documentation under `docs/`:
1. Round 1: an independent architecture proposal by Claude (`docs/analysis/architecture-discussion/01-claude-proposal.md`) answering D1–D14 with options, position, rationale, risks and reversal cost, a parity strategy, a roadmap and owner questions.
2. Round 2: reconciliation with Astra's independent position paper (`02-astra-position.md`, written by the other architect) into `03-reconciliation.md` (agreements, disagreements, decisions, open owner questions).
3. Round 3: the final `docs/` set (architecture, decisions, parity contract, API, MCP, project format, roadmap) plus `docs/README.md` index.

## Impact
- Affected specs: none yet (specs will be derived from the final docs in later phases)
- Affected code: none (documentation only; no build, no engine changes)
- Breaking change: NO
- User benefit: a decided, evidence-backed architecture the owner can approve before implementation starts, with the parity risks stated honestly
