# 189. P22-B is a vocabulary task: the new host requests exercise 60 pending symbols, and the other 257 move to phase1.24

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.24_python-api-facade

## Context

Decision 112 named recording P22-B. It is one Tier 0 API probe on the plane that calls every Painter symbol the capability manifest marks `pending-evidence`, with set→get readbacks in both recordings, and passes every enum member where its owner call takes it.

The recording queue said P22-B needed "a generic per-symbol probe". The recorder's provenance check forbids dynamic attribute access (`getattr`, `vars`, rule 4), so it cannot be generic. Every Painter call is written out in the probe vocabulary, so each symbol needs its own entry, fake-Painter support and a test.

The manifest has 317 pending Painter symbols. Decision 188's new requests exercise 60 of them:

- the `display` module, `Camera` and its eight properties, both projection types, ACES, and the environment, LUT and tone-mapping getters and setters;
- `CameraPropertiesChanged`, `ShelfCrawlingStarted`/`Ended` and `TextureStateEvent`;
- `BlendingMode.Multiply`, `FilteringMode.Nearest`, `reset_source`, `set_symmetry_enabled`, `enable_mask`, `remove_mask` and `set_mask_background`;
- `LevelsEffectNode` with `affected_channel` and `set_parameters`;
- the `NodeType` members AnchorPointEffect, ColorSelectionEffect, CompareMaskEffect, LevelsEffect and PaintLayer;
- `Resource.gui_name`/`usages`, `Shelf` and five of its members, `Shelves` and `add`/`all`/`exists`, and `Usage.ENVIRONMENT`;
- `SourceBitmap.reset_color_space` and `SourceUniformColor.set_color`;
- the seven `MeshMapUsage` members BentNormals, Height, ID, Opacity, Position, Thickness and WorldSpaceNormal.

That leaves 257, by module: textureset 68, layerstack 59, event 16, levels 15, resource 15, ui 14, substance_painter_plugins 12, logging 11, project 11, properties 10, colormanagement 5, application 4, async_utils 4, exception 4, display 3, export 2, js 2, baking 1 and source 1. Reaching them needs about 80-120 new vocabulary entries. Some cannot be called safely or deterministically in a recording session:

- plugin start, close and reload;
- UI menus and logging;
- `ExportStatus.Cancelled` and `Warning`.

**Model panel (one round; cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5):**
- C1, P22-B is vocabulary building, not request authoring: AGREE x2, PARTLY x1. One fixed call can pass several enum members, and some symbols need another evidence route.
- C2, record the 60 and split the 257 to phase1.24 by module, judging the plugin, UI and logging symbols: AGREE x2, PARTLY x1. The follow-up must name its exact recordings and amend decision 112 wherever another evidence route replaces P22-B coverage.
- C3, a partial request named P22-B would claim coverage it lacks: AGREE x3.

## Decision

1. **P22-B is not authored as one request.** No partial request carries its name.
2. **Evidence already requested.** The 60 symbols above become evidence when decision 188's requests are admitted and their replays join the traced Tier 0 tests (decision 112 §1).
   - Until then they stay `pending-evidence`.
   - No manifest entry changes here.
3. **The remaining 257 are a scope split to `phase1.24_python-api-facade`** (decision 112 already makes it P22-B's owner), as task item 3.4. The work, module by module:
   - add the probe vocabulary each needs, with fake support and tests;
   - author the requests, each naming the symbols it exercises;
   - judge each plugin, UI, logging and export-status symbol: either a probe that can run safely, or another evidence route recorded as an amendment to decision 112.

## Alternatives Considered

- **Build the whole vocabulary now.** Rejected for this task. It is a separate body of recorder work and is not needed for the queued recordings to run.
- **A partial "P22-B" request.** Rejected by the panel (C3).

## Consequences

- The recording queue's P22-B entry points here and to phase1.24 item 3.4.
- No symbol's status changes until its recording is admitted and replayed.
