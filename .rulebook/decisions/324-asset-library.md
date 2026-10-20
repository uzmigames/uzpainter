# 324. The asset library: data files beside the executable, exact pins, provenance records that enforce the clean room, and an alias table that answers a Painter name only with a certified asset

**Status**: accepted
**Date**: 2026-10-20
**Related Tasks**: phase3.1_proc-backend-seam, phase3.3_procedural-families

## Context

Item 2.4 of `phase3.1_proc-backend-seam` asks for the asset library of `05-procedural-content.md` §3: assets pinned as `uzasset://<family>/<id>@<version>` in the project, a provenance record per family, and an internal alias table so `resource.search` resolves Painter names. Facts at the start:

- The seam (items 2.1 to 2.3) has the request, the certified-domain check and the HLSL host. No Painter family is certified, and none will be before the Tier 2a recordings.
- The document model already stores a pinned URL in `ProceduralRef.asset` and validates its form.
- `substance_painter.resource.search` is a release gap whose owner is item 2.4 (decision 113). The typed MCP tools `resource_search` and `assets_search` are registered gap families (decision 164).
- Painter's query grammar is documented only by an external page. The python-doc gives examples: `s:starterassets u:filter n:Blur=`, and `n:Paper\ Grainy=` with an escaped blank.
- The facade's `resource.Usage` holds five members: TEXTURE, ENVIRONMENT, COLOR_LUT, GENERATOR and SMART_MATERIAL.

The coordinator's brief fixed the rules: `resource.search` returns only what the library really holds, no Painter search result is invented, and the library holds UzPainter-certified families only (clean room, decision 006). No model panel ran. The forks below follow from those rules and from decisions 006, 113 and 222.

## Decision

Code: `src/procedural/asset_library.{h,cpp}`, `src/procedural/cli.{h,cpp}` and `src/procedural/admission.{h,cpp}`. Shipped library: `assets/procedural/`, installed as `bin/assets/procedural/`. Facade: `python/uzpainter_facade/resource.py` `search`. Tests: `tests/procedural/test_proc_asset_library.py` and the `library` case of `tests/procedural/procedural_test.cpp`, and `tests/python/test_pyapi_asset_library.py`.

1. **Files.**
   - A library is a directory. `library.json` (`uzpainter/asset-library/1`) lists one provenance record per pinned asset and names the alias table.
   - A record (`uzpainter/asset-provenance/1`) holds the URL, the UzPainter name, the usage, the author, the licence, the public sources, the effective defaults, the certified domain, the corpus ids and the parity status with the report that gives it.
   - The domain is the certification harness's JSON (`tools/parity/proc_cert/batch.py` `Domain`), plus an optional `presets` list. The seam and the harness therefore read the same declaration.
   - The alias table (`uzpainter/asset-aliases/1`) maps (shelf, usage, Painter name) to a URL.
   - The process loads the library once, from beside the executable. `UZP_ASSET_LIBRARY` names another directory, for tests.
2. **The load refuses the whole library on any broken rule.** The refusal names the file and the reason. The rules are:
   - every member is one the schema names, so a record cannot carry an `.sbsar`, a capture or a preset tree;
   - the licence is Apache-2.0 (decision 002);
   - every source is a paper, a book, a standard or an approved public source named by its `A-` id in `docs/approved-sources.md`, so a record cites no recorded Painter output;
   - the usage is a procedural `resource.Usage` member: BASE_MATERIAL, FILTER, GENERATOR, PROCEDURAL, SMART_MASK or SMART_MATERIAL;
   - every declared parameter has a default, and no default is undeclared;
   - an `exact` or `calibrated` status names both corpus ids and its report, and a calibrated status lists its residuals per harness unit (decision 305);
   - a record's name is not a Painter name of the alias table: shipped assets carry UzPainter names (CLR-06);
   - a URL is pinned by one record only, and record paths stay inside the library;
   - an alias names an asset the library holds, with the same usage, whose status is `exact`. An alias to a calibrated or unavailable asset would answer a Painter name with an asset that is not proven equal, which is a substitution (05 §2).
3. **Pins are exact.**
   - `Resolve(url)` returns the record of that exact version.
   - Otherwise it raises `UnsupportedProcedural{asset, reason: "pinned version not in the asset library", field: version, value, certified: the versions held}`.
   - There is no "latest", no nearest version, and no alias inside a pin.
   - `PinnedAssets(project)` lists every pin of a project: procedural sources, generator and filter effects, and smart-preset provenance. `CheckPins` refuses the first pin the library does not hold.
4. **`resource.search` answers from the library only.**
   - Terms: `s:<shelf>`, `u:<usage>` (lower case, no underscore) and the exact name `n:<name>=`. A backslash escapes the next character.
   - `s:uzpainter` is UzPainter's own shelf. It lists the library by UzPainter name, filtered by usage and exact name.
   - Any other shelf, or no shelf, is Painter's library. Only an exact name is answered there, through the alias table. A name with no alias raises `UnsupportedProcedural{asset: "<shelf>/<usage>/<name>", reason: "no certified family"}`. Nothing similar is offered in its place.
   - Every other form is `NotYetSupported` naming `phase3.3_procedural-families`, because Painter's grammar and listing order are unrecorded. That covers free text, a partial name, a repeated term, a usage the library has no record of (`u:substance`), and a listing of a Painter shelf without a name, whose Painter answer is Adobe content UzPainter does not hold (decision 006).
   - A shelf the script added with `Shelves.add` is the existing shelf gap.
   - A result is an `AssetResource`:
     - its identifier is `resource://uzasset/<family>/<id>?version=<version>`, the pin in Painter's ResourceID form;
     - `gui_name()` is the UzPainter name;
     - `usages()` is the `Usage` member, or `NotYetSupported` for a member the facade lacks (FILTER, ...);
     - `asset_url()`, `parity_status()` and `provenance()` are UzPainter additions on that class only.
   - The native helper is the private `uzpainter.resource._search_assets`.
5. **The capability status stays `release-gap`.** The shipped library certifies no family, so every Painter name is refused. The inventory note says so. The MCP gap tools are unchanged. The entry becomes `supported` only when the phase3.3 families are certified and a Tier 0 search replay exercises it. The R-095 P7 search exclusion keeps its known divergence, reworded.
6. **`UnsupportedProcedural` carries `asset` and `reason`** in Python (`uzpainter.exception`) when the refusal states them. Existing refusals that state neither keep `None`.
7. **`.sbsar` import (item 2.5).**
   - The shared resource reader (`python/edits.cpp` `ReadResourceFile`) refuses a `.sbsar` file of any usage, before the file is read. It raises `UnsupportedProcedural{asset: <file name>, reason: "no runtime"}`.
   - The reader is shared by `uzpainter.resource.import_project_resource`, the facade (which delegates a `.sbsar` before reading its bytes, so a missing archive gets the same refusal) and the typed MCP import tools. The revision never advances.
8. **`UzPainter.exe assets list [--parity] [--library <dir>]` (item 2.5, `src/procedural/cli.h`).**
   - It prints one line, `UZP_JSON:{status, library, assets: [{asset, name, usage}]}`, sorted by URL.
   - `--parity` adds each asset's status. A calibrated status comes with its residuals per unit (max, sum, count, mean, p99) and its corpus ids, and an unavailable one with its reason. Each asset also gets its report and its certified domain, as 05 §6 asks.
   - The alias table is never printed (CLR-06).
   - Exit status: 0 listed, 2 usage error, 3 host error (`AssetLibraryError`) when the library does not load.

9. **Certification reports and batches are committed (item 2.7; this closes decision 303's risk 4).**
   - `python -m tools.parity.proc_cert` writes its reports under `parity/reports/phase3/proc-cert/` by default (`tools/parity/proc_cert/report.py`), as `<family>__<id>@<version>/<pin16>.json`. `--reports` still names another directory.
   - Committed batches live under `parity/manifests/phase3/proc-cert/`.
   - The repository guard has a rule for each. A report or a reservation holds only its schema's members: hashes, integer statistics, outcomes from the harness's vocabulary and its fixed statement. `certified` must be true exactly when the outcome is exact, and no string may name a file path. A batch file is a `batch.json`, whose domain and §6 matrix parse and whose case lists are relative paths pinned by SHA-256, or a case list whose cases parse.
   - The records under `assets/procedural/` name the report that gives their status, so `assets list --parity` and the published report can be compared (phase3.3 item 3.3).

10. **Procedural edits go through the seam before any transaction (items 3.1, 3.4, 3.6; `src/procedural/admission.h`).**
    - A `ProceduralRef` stores only what the user chose: the pin, the parameters, the preset and the image inputs by hash. A `UseContext` supplies what its place in the document gives: the output spec, the mesh class, the input specs, the seed and the tile. Its callers resolve the context from the texture set, the channel and the mesh (item 2.6, phase3.3).
    - `RequestFor(ref, context, library)` lays the stored parameters over the record's defaults. Booleans become integers. A value of another JSON type, or an input whose spec the context lacks, is refused.
    - `Admit` tries the seam first. A snapshot with the exact signature serves the request, even for an asset the library does not hold (05 §4, migration). Otherwise a pin the library does not hold is refused as such, and any other refusal is the seam's.
    - `SetEffectProcedural` runs both before calling its `submit` (`ProjectStore::Submit`). A refusal therefore opens no transaction: the revision stays where it was, nothing is evaluated, clamped or substituted. An admitted reference is committed exactly as given.
    - The Python API still refuses `insert_generator_effect`, `insert_filter_effect` and procedural sources as release gaps. They will call this edit when item 2.6 and phase3.3 open them.

## Alternatives Considered

- **The library inside the project file, or compiled into the executable.** Rejected. A project pins versions, and the library is versioned with UzPainter. Data files beside the executable follow the export presets and environments (decisions 095, 132).
- **An alias to any library asset, with its status shown.** Rejected. A script that names a Painter asset expects that asset's output. Only an exact asset may stand for it.
- **An empty list for an unaliased Painter name.** Rejected. Painter would return the asset, so an empty list is a silent divergence. A loud refusal is the seam's rule.
- **Implementing Painter's partial and free-text matching.** Rejected. It is unrecorded, so any implementation would be a guess at Painter's results.
- **Marking `resource.search` `pending-evidence`.** Rejected. No Painter query is answered while no family is certified, and decision 164's gap tools would disagree with the inventory.

## Consequences

- phase3.2 families add their records and aliases to `assets/procedural/` as they are certified, and register the same declaration with the HLSL host.
- The facade's `Usage` enum lacks FILTER, PROCEDURAL, BASE_MATERIAL and SMART_MASK. An asset of those usages is found, but its `usages()` is a release gap until those members are added (phase3.3).
- The query grammar beyond the three terms stays a release gap until it is recorded.
