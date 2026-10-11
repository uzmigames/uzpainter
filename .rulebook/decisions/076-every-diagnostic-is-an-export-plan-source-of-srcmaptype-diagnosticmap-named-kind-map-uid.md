# 76. Every diagnostic is an export-plan source of srcMapType diagnosticMap, named <kind>/<map>/<uid>

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.13_compositor-diagnostics, phase1.15_export-plan-compiler

## Context

EXP-04 requires that any channel, mesh map, mask, isolated layer, difference map or unlit BaseColor be exportable through the general export API (`08-export.md` §6, "with the appropriate `srcMapType`/diagnostic source"). Painter's export dictionary has `srcMapType ∈ {documentMap, meshMap, virtualMap, defaultMap}`, each with its documented `srcMapName`s. Item 2.5 of phase1.13 asks that every diagnostic be a source the export plan can name. The export-plan compiler (phase1.15) has not started.

The model panel was consulted (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5).

| Claim | Verdicts |
|---|---|
| C7 A new `srcMapType` value `diagnosticMap` (a UzPainter extension; Painter's values keep their meaning) with `srcMapName` `isolated/<map>/<uid>`, `contribution/<map>/<uid>`, `materialMask/<uid>`, `materialView/<view>/<uid>`, `materialLeaks/<view>/<uid>` and `regionStats/<map>/<uid>` as a statistics (JSON) source; one parser/formatter and one entry point on both stores | AGREE x2, PARTLY x2 |

The panel's points:

- The schema must name the ID mesh-map view: it is `materialView/ID/<uid>`.
- The statistics need a canonical JSON, or byte-identical runs fail on serialisation.
- The exporter must branch on a non-raster source and fail loudly if it expects an image.
- A 0/1 leak raster loses the leak values. Those are the `materialView` source and the API's `LeakTexel` list.

## Decision

1. `kDiagnosticMapType = "diagnosticMap"`. The `srcMapName` grammar is `<kind>/<map or view>/<uid>`, with uids in positive decimal:
   - `isolated/<map>/<node>`, `contribution/<map>/<node>`;
   - `materialMask/<material>` (two parts);
   - `materialView/<view>/<material>`, `materialLeaks/<view>/<material>`;
   - `regionStats/<map>/<material>` (the map's statistics inside the material's region).

   `<map>` is a `ChannelType` name, `Normal_OpenGL` or `Normal_DirectX`. `<view>` is `ID`, `BaseColor`, `Height`, `Normal`, `Roughness` or `Metallic`.
2. `SourceName` and `ParseSourceName` round-trip every source. A malformed name, an unknown kind, map or view, or a uid that is not a positive decimal id fails with `evaluator:not_found`.
3. `EvaluateDiagnosticOn` (and `Evaluator::Diagnose` / `CpuEvaluator::Diagnose`) evaluates any named source on either store. It returns a float32 raster, or `RegionStats` for `regionStats`. `RegionStatsJson` is its canonical JSON: fixed key order, every double in its shortest round-trip text. The export plan writes a raster with its file's write rule, and the statistics as a JSON file.
4. Phase1.15 consumes this grammar. A plan entry of `srcMapType` `diagnosticMap` whose name does not parse is an invalid config. A statistics source in an image channel slot is also an invalid config.

## Consequences

- Painter's own `srcMapType` values and names are unchanged. A config that uses only them exports the same files.
- Phase1.19 exposes the same names through `uzpainter.diagnostics`.
