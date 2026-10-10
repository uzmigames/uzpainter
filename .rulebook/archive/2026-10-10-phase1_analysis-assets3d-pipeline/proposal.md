# Proposal: phase1_analysis-assets3d-pipeline

## Why
UzPainter must fully replace Adobe Substance 3D Painter in the Tales of Shadowland asset
pipeline at E:\UzmiGames\Assets3D. Before any architecture work, we need a traceable,
source-cited record of how that pipeline works today, exactly how Painter is driven (project
settings, texture sets, bake, layer stacks, export, review render standard), which lessons and
gates constrain it, and therefore which concrete requirements UzPainter must satisfy. Without
this, the architecture phase (phase2_docs-architecture) would design against assumptions.

## What Changes
Adds eight analysis documents (English, Markdown) under
docs/analysis/assets3d-pipeline/ in the UzPainter repository:
01-pipeline-overview, 02-painter-usage, 03-bake-settings, 04-painting-recipes-and-materials,
05-export-and-consumers, 06-review-render-standard, 07-lessons-and-pitfalls,
08-requirements-for-uzpainter. Each claim cites a source path in Assets3D and is labelled
Fact / Hypothesis / Recommendation. No code, no changes to Assets3D.

## Impact
- Affected specs: none (analysis input for phase2_docs-architecture)
- Affected code: none
- Breaking change: NO
- User benefit: architects get a source-traced requirement set (MUST/SHOULD/COULD) and a clear
  Blender/UzPainter boundary for replacing Substance 3D Painter.
