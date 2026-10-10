# Licensing and clean-room policy

Owner decision of 2026-10-10 (rulebook decision 002, accepted): UzPainter is released under the **Apache License 2.0** (root `LICENSE`, copyright UzmiGames), and nothing in the project may exceed what Substance Painter's licence permits. UzPainter reproduces Painter's *behaviour*; it copies nothing from Adobe. This closes the legal questions of the architecture discussion (`docs/analysis/architecture-discussion/05-resolution.md` D4, D6) in favour of the clean-room route. Later owner answers of the same day that touch this policy: Q2 (decision 018, superseding 008: Painter's Iray output is the render target; NVIDIA's MDL specification and the open-source MDL SDK are allowed sources), Q8 (decision 021: UzEngine code is vendored, not linked) and the repository-history release criterion (decision 027). Requirements: LIC-01…03, CLR-01…06 (`docs/prd.md`).

## 1. Policy

1. **No copying.** No code, shader text, MDL material files, constants, data tables, asset bytes, preset files or documentation text from Adobe Substance 3D Painter or Substance 3D Assets enters the repository, the build, the distributable or the documentation.
2. **Behaviour only.** UzPainter implements compositing, baking, procedural generators, viewport shading, path tracing and export from public literature and specifications, plus black-box numerical calibration against Painter's observable outputs (textures, captures and renders produced through its documented Python API and its documented user interface).
3. **No redistribution of Adobe content.** HDRIs, grunges, materials, smart masks, smart materials, procedural captures, `.spexp`/`.spt`/`.spsm`/`.spmsk` files and shelf content are never shipped. UzPainter ships its own assets (CC0 HDRIs such as Poly Haven, UzmiGames-authored presets) under compatible licences, each with a provenance record (§6).
4. **API shape only.** The `substance_painter` compatibility facade mirrors the documented API shape — module and symbol names, signatures, enum members, documented semantics and errors — written from Painter's public API documentation (`PAINTER\resources\python-doc\**\*.html` and the same pages on Adobe's website), never from Adobe's shipped `.py` sources. Painter's shipped `PAINTER\resources\javascript-doc\` has the same status as `python-doc`: public API documentation that may be consulted for documented behaviour, never used as an implementation source.
5. **No internals in the docs.** Documentation may state that Adobe's shipped shader library, shader sources, MDL files and `.py` sources exist and are off-limits; it must not describe their algorithms, constants, sampling schemes or formulas. Facts derived from observing Painter's outputs, from its public documentation and from the documented API shape are allowed.
6. **Private oracles.** Public manifests contain independently authored test inputs, public-documentation-derived expectations, schemas, software identities and hashes of private oracle records. Every recorded Painter output, including API readbacks, default/template captures, Iray reference renders and asset recipes, stays in the private store (`docs/architecture/14-parity-testing.md` §6), which lives on the owner's machine (Q9b). Public templates and default tables are independently authored from permitted documented semantics with provenance; raw captured records are never shipped. Hosted CI compares independently authored public expectations; comparisons against Painter's recorded values require private-store access. Learning compatibility facts through permitted observation, and publishing independently derived implementations and fitted formulas, remain allowed; serialising a recorded value as JSON does not make it public data.
7. **Independent presets.** Public smart presets are independently designed UzmiGames recipes expressed in the documented layer/effect model. Adobe preset trees, parameter collections and serialized readbacks obtained during observation remain private oracle or per-project migration data; changing their format or names does not qualify them for publication. Each shipped recipe records independently authored provenance and passes output-parity tests. Export presets follow the same rule (§6).

## 2. Rules for contributors and agents

| Allowed to consult | Not allowed to consult or reproduce |
|---|---|
| `PAINTER\resources\python-doc\**\*.html` and `PAINTER\resources\javascript-doc\**` (public API documentation) and Adobe's public help pages (settings, workflows, output templates, mesh-map descriptions, blend-mode names) | `PAINTER\resources\starter_assets\shaders\*.glsl`, `PAINTER\resources\shader-doc\lib-*.html` (shader library text and documentation that embeds it) and `PAINTER\resources\mdl\**` (Painter's shipped MDL material files) |
| Painter's observable behaviour: outputs exported through `substance_painter.export`, captures of its viewport, its Iray renders saved through the application, values read back through the documented API, settings shown in its user interface, property names/labels discovered through `Property` introspection | `PAINTER\resources\python\modules\**\*.py` (shipped Python sources, including Adobe's test suites) as an implementation source |
| Public specifications and papers: OpenPBR Surface specification (Academy Software Foundation), glTF 2.0 specification and its PBR appendix, Karis 2013 (split-sum IBL), Walter et al. 2007 (GGX), Heitz 2014 (Smith masking) and 2018 (VNDF sampling), Schlick 1994, Burley 2012, Ramamoorthi and Hanrahan 2001 (SH irradiance), Barré-Brisebois and Hill 2012 (normal blending), W3C Compositing and Blending Level 1 and the PDF reference blend modes, IEC 61966-2-1 (sRGB), MikkTSpace (Mikkelsen 2008), the OCIO and OpenEXR specifications | Decoding or parsing Adobe's binary files (`.spp`, `.spexp`, `.spt`, `.spsm`, `.spmsk`, `.sbsar`) for implementation purposes; redistributing or embedding their contents |
| Path-tracing literature: Kajiya 1986 (rendering equation), Veach 1997 (MIS, path-space methods), Pharr, Jakob and Humphreys, *Physically Based Rendering*, 4th ed. (read as literature; code copied from pbrt-v4, which is Apache-2.0, would be vendored with its notice), Burley 2020 (hash-based Owen scrambling) | Iray: any Iray binary, library, plug-in or description of its internals; Iray output is used only as a private oracle (§1.6) |
| NVIDIA's Material Definition Language specification and the open-source MDL SDK sources (BSD-3-Clause), allowed by the owner under Q2; the Academy's ACES documents and reference transforms (§3) | Any Adobe binary (DLLs, engines) as a dependency |
| UzEngine sources (`E:\UzmiGames\UzEngine`, Apache-2.0) for reading; code enters UzPainter only through the vendoring procedure (`docs/architecture/13-engine-integration.md` §3), and third-party code under its own licence | — |
| Historical analyses under `docs/analysis/` only after the provenance audit below approves the exact revision | Descriptions derived from off-limits implementation files, including descriptions repeated by an intermediary |

Procedure: an implementer who needs a formula writes it from the literature above, then calibrates parameters by fitting to Tier 0 goldens (`14-parity-testing.md`); the fit, its residual and the public source are recorded in `parity/semantics/*.json`. A reviewer rejects a change whose provenance names an off-limits file.

**Historical material.** The sanitisation pass over `docs/analysis/` is recorded in `docs/analysis/clean-room-redactions.md` (102 redactions). That record is not a clearance. Historical analyses and discussion files are not implementation inputs until an itemised clean-room provenance audit approves their exact revision in the approved-source index (`docs/approved-sources.md`, work package `P0-SOURCES` in `dag.md`), with revision hash, provenance and cleared scope. Until then they are restricted historical context. Do not use descriptions derived from off-limits implementation files, including descriptions repeated by an intermediary. The implementation reading guide links only to approved summaries, permitted public documentation and approved behavioural observations. Where a contributor's independent-provenance claim depends on it, prior exposure to off-limits material is recorded; avoiding a second direct read does not erase it.

Agents operating on this repository follow the same rules: they do not open the off-limits files, and they treat any content from them that appears in older documents as unusable for implementation.

## 3. Third-party dependency inventory

Compatibility means distribution alongside Apache-2.0 UzPainter code while retaining each component's own license and notices; it does not relicense third-party code as Apache-2.0. Record license, notices, source/package hash, selected features and distribution role for every direct and transitive dependency in the qualified build. Unverified entries are release blockers. Excluded vendor folders are not release dependencies unless they enter the selected closure. "Not confirmed" below means the exact licence text or redistribution terms of the package to be shipped were not verified in this project yet.

| Dependency | Use | Licence | Apache-2.0 compatible | Notes |
|---|---|---|---|---|
| UzEngine render core (vendored copy, `thirdparty/uzengine-render-core/`) | RHI with DX12 and Vulkan backends, shader compiler/reflection/cache, `.uztexture` format definition (header only), math, logging, paths, crash handler, preview window (`13-engine-integration.md` §2) | Apache-2.0 (UzEngine `LICENSE`, "Copyright 2026 Uzmi Games") | yes | Copied from a clean commit (13 §3.1); upstream files carry no per-file headers. UzEngine has **no `NOTICE` file** (checked 2026-10-10 at the repository root, `runtime/`, `runtime/engine`, `runtime/platform`), so Apache-2.0 §4(d) adds no text today; re-checked at the selected commit. Obligations kept: licence copy (§4(a)), prominent notices in modified files (§4(b)), retained notices (§4(c)), manifest and modification log, attribution in UzPainter's `NOTICE` (13 §3.3) |
| D3D12MA | DX12 memory allocator (used by the vendored backend) | MIT; upstream `NOTICES.txt` adds AMD and Microsoft MIT notices | yes | Ship `NOTICES.txt` content |
| DirectX-Headers | D3D12 headers and helpers | MIT | yes | Headers only |
| DirectXMath | Math (vendored `engine/math`) | MIT | yes | Headers only |
| volk | Vulkan function loader | MIT | yes | |
| Vulkan Memory Allocator | Vulkan memory | MIT | yes | |
| Vulkan-Headers | Vulkan API headers | Apache-2.0 for the headers used; repository files are Apache-2.0 or "Apache-2.0 OR MIT" (`LICENSE.md`) | yes | Headers only |
| Vulkan loader (`vulkan-1.dll`) | Vulkan runtime entry point | Apache-2.0 (Khronos Vulkan-Loader) | yes | **Not shipped**: installed with the GPU driver and loaded by volk; outside the release closure |
| LunarG Vulkan SDK (validation layers, tools) | Development and CI only | Validation layers Apache-2.0; SDK installer under LunarG's terms | — | Never in the distributable |
| SPIRV-Reflect | SPIR-V reflection | Apache-2.0 | yes | |
| spdlog with bundled fmt | Logging | MIT (spdlog), MIT (fmt) | yes | |
| Tracy (public headers only) | Profiling macros of the vendored code, compiled to stubs | BSD-3-Clause | yes | No Tracy client linked in release |
| xxHash | Hashing, shader-cache keys | BSD-2-Clause | yes | |
| DirectX Shader Compiler (`dxcompiler.dll`, `dxil.dll`, `dxcapi.h`) | Run-time HLSL → DXIL and SPIR-V | Per the release notes of 1.9.2602 (in UzEngine's tree): LLVM Release License (University of Illinois/NCSA) for all files except `d3d12shader.h` (MIT). The package also contains `LICENSE-MS.txt` (Microsoft Software License Terms, "Microsoft DirectX Shader Compiler") whose scope the notes do not state | yes for the NCSA/MIT parts; `dxil.dll` redistribution **not confirmed** | Confirm against the exact release package before shipping |
| Direct3D 12 Agility SDK (`D3D12Core.dll`) | DX12 runtime | Licence terms of the `Microsoft.Direct3D.D3D12` NuGet package; UzEngine's third-party README lists "MIT", which is not a verification of the package text | **not confirmed** | Verify the package's licence text before shipping |
| Microsoft Visual C++ runtime DLLs | Imported by prebuilt MSVC binaries (CPython ships its own `vcruntime140*.dll`) | Microsoft Visual C++ redistributable terms | redistributable — exact files **not confirmed** | App-local only as the measured import closure requires; not Apache-2.0 |
| CPython 3.13 embeddable | Embedded interpreter | PSF License with its historical and incorporated notices | yes | Preserve the complete pinned distribution's notices; pip unsupported in the embeddable package |
| pybind11 | Python bindings/embedding | BSD-3-Clause | yes | |
| Official MCP Python SDK (`mcp`) and its wheel closure (pydantic, anyio, httpx, …) | MCP server | SDK MIT; each dependency recorded at pin time | SDK yes; closure **not confirmed** until the wheels are pinned | Record licence, notices and hash per wheel |
| Embree 4.x | CPU ray tracing for bakers | Apache-2.0 | yes | Upstream build with notices; optional TBB (Apache-2.0) |
| SQLite | Project container | Public domain | yes | Amalgamation |
| zstd | Payload compression | BSD-3-Clause / GPLv2 dual | yes (BSD branch) | Choose the BSD licence explicitly |
| lz4 | Not used by the vendored subset; only if UzPainter selects it | BSD-2-Clause (library) | yes | Outside the closure unless selected |
| etcpak (with bundled bc7enc) | BC1/3/4/5/7 encoding | BSD-3-Clause (etcpak); bc7enc MIT/Unlicense | yes | Component licences recorded; `bc7e.ispc` (Apache-2.0) not used |
| libpng, zlib | PNG 8/16 | libpng/zlib licences | yes | |
| spng | PNG decode | BSD-2-Clause | yes | |
| libjpeg-turbo | JPEG | IJG / BSD-3 / zlib | yes | |
| stb (image, image_write, image_resize2) | TGA/BMP/HDR, resampling | MIT or public domain (dual) | yes | |
| tinyexr (+ miniz) | EXR | BSD-3-Clause (tinyexr); MIT (miniz) | yes | |
| ufbx | FBX parsing | MIT or public domain (dual) | yes | |
| fastgltf | glTF parsing | MIT | yes | |
| mikktspace (Mikkelsen) | Tangent basis | zlib-style licence in its header | yes | |
| meshoptimizer | Vertex dedup | MIT | yes | |
| nlohmann/json | JSON | MIT | yes | |
| OpenColorIO 2.x | Colour management, if linked | BSD-3-Clause | yes | Only UzmiGames- or user-supplied configs; Adobe's OCIO configs are never shipped |
| ACES transforms, if used for display | ACES view/tone mapping | `ampas/aces-core` (named `aces-dev` before 2.0) states Apache-2.0 for ACES 2.x (checked 2026-10-10); 1.x releases carried the Academy's own licence; OCIO's built-in ACES transforms fall under OCIO's BSD-3-Clause | yes for 2.x and OCIO — confirm at pin | Only if selected; 1.x terms not used without review |
| NVIDIA MDL specification and MDL SDK | Material semantics for the path tracer (consulted); SDK code only if a component is later selected | MDL SDK: BSD-3-Clause ("Copyright (c) 2018-2026, NVIDIA CORPORATION", upstream `LICENSE.md`, checked 2026-10-10); specification: NVIDIA public document, consulted, not copied | yes | Outside the release closure unless a component is linked; then its transitive notices are inventoried. No Iray component |
| NVIDIA FLIP (`NVlabs/flip`) | Diagnostic image metric in parity reports | BSD-3-Clause ("Copyright (c) 2020-2025, NVIDIA CORPORATION & AFFILIATES") | yes | Pinned release; diagnostic only, never acceptance evidence; UzEngine's `flip_pass` is not vendored; in the distributable only if a shipped tool reports FLIP |
| pbrt-v4 | Literature (§2) | Apache-2.0 (source); book text is the authors' copyright | yes | Consulted; any copied code is vendored with its notice |
| HDRIs for UzPainter's own display presets | Reference lighting | Poly Haven CC0 or UzmiGames-authored | yes | Adobe's environments are never shipped; users may point to their own files by hash |
| GoogleTest | Tests | BSD-3-Clause | yes | Not shipped |
| Zig toolchain | Build | MIT | yes (tool, not shipped) | |
| EnTT, astcenc, basis_universal, FFmpeg, DLSS, LuaJIT, Slang, FXC, FidelityFX/Brixelizer (present in UzEngine's tree) | — | MIT / Apache-2.0 / Apache-2.0 / LGPL-2.1 / NVIDIA proprietary / MIT / MIT or Apache-2.0 / Microsoft / MIT | — | **Not vendored** (13 §2.4); outside the closure |

The distribution's `NOTICE` file and `LICENSES\` folder carry every notice of the release closure, including UzEngine's attribution (`13-engine-integration.md` §3.3, §5).

## 4. What the policy means for parity

Equality with Painter is still the acceptance criterion (`vision.md`). The clean-room route reaches it by calibration: candidate formulas from public sources are fitted to Painter's outputs recorded through its documented API, the residuals are measured, and anything that cannot be made equal is a release gap or an owner-approved exception (`14-parity-testing.md` §5). The same holds for the Iray target: the path tracer is written from the literature of §2 and calibrated against converged Iray references held in the private store; nothing is taken from Iray or Adobe internals (`07-preview-and-render-parity.md`). The owner accepted this route and its calibration cost on 2026-10-10.

## 5. Publication release criteria

The repository is made public, and a release is published, only when all of the following hold (gate G5 in `dag.md`):

1. **Clean history (decision 027).** The private repository `uzmigames/uzpainter` (first commit `6d7c297`) contains pre-sanitisation analysis text. Before it is made public, its history is recreated clean: a new history built from the sanitised tree, so that no pre-sanitisation blob is reachable from any published branch or tag, published by a force push at that moment under the owner's explicit authorisation. Nobody rewrites history before that moment. Verification scans every blob reachable from the refs to be published, not only the latest tree: redaction markers, Adobe file signatures, oracle-blob hashes from the private store index, and off-limits content.
2. **Inventory and attribution complete.** Every §3 entry of the release closure is confirmed (no "not confirmed" entry left); `LICENSE`, `NOTICE` and `LICENSES\` are complete; the UzEngine vendoring records (`ORIGIN.md`, `MANIFEST.json`, `MODIFICATIONS.md`) are complete and the vendoring check passes; the Python wheel closure is recorded.
3. **No Adobe-derived content.** The repository and the release pass the LIC-03 scan; every shipped preset and asset has its provenance record (§6); no document describes Adobe internals (§1.5).
4. **Private oracle store excluded.** No oracle blob is in the repository, its published history, the release or any artifact published by hosted CI; manifests hold hashes only; store credentials never enter the repository.

These checks run on the same immutable build and dependency lock as the final parity report and the package verification.

## 6. Preset and asset provenance

Shipped presets and assets follow §1.7. For **export presets** (`docs/architecture/08-export.md` §4):

- **May be published:** UzmiGames-authored preset files under UzPainter names whose content is functional — output maps, which channel feeds which file and channel, bit depth, file format, colour space, padding — where each decision cites a public source (Adobe's public output-template help pages, the consumer's public specification such as glTF 2.0, Unreal Engine documentation or UzEngine's formats, or a UzmiGames pipeline script) or is a behavioural compatibility fact confirmed on UzmiGames fixture projects and written independently.
- **Never published:** Adobe preset files or their content; serialised readbacks of Adobe presets (for example `list_output_maps()` results) and anything generated from them by renaming, reformatting or re-serialising; Adobe's descriptive preset text; Adobe preset names as shipped identifiers (they are internal compatibility aliases only, CLR-06).
- **Observation confirms; it is not a source to copy.** A preset is written by hand from documented semantics and cited sources. The private readbacks and exported files are the oracle its output-parity test compares against.

For **smart materials, smart masks and other recipes** (`05-procedural-content.md`): independently designed; observed Adobe trees and parameter collections stay private migration or test data.

**Provenance record.** Every shipped preset or asset has `<name>.provenance.json` beside it (export presets: `assets/export-presets/<preset>.provenance.json`, fields in `08-export.md` §4) with at least `{asset, version, author, date, design notes or public sources (page and section), transitive resources and their own records, private oracle records used for verification (SHA-256 only), parity tests and status, reviewer}`. A reviewer rejects a shipped asset without a record, with a record that names an off-limits source, or whose content traces to a readback. Hosted CI checks that records exist and match the schema; it cannot prove independent authorship, which is the reviewer's decision.
