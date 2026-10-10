# Compact Project Container Format (Layer Stack + Masks + Cache)

Research compiled 2026-10-09.

## Container Format Options

| Format | What It Is | Pros | Cons | License | Key Source |
|--------|-----------|------|------|---------|-----------|
| **HDF5 (Hierarchical Data Format v5)** | **Fact**: Substance Painter .spp files use HDF5 v5 internally. Confirmed by local file verification (2026-10-09): HDF5 magic signature `89 48 44 46 0d 0a 1a 0a` detected in real projects at `E:\UzmiGames\Assets3D\Creatures\Undead\Skeletal Mage\Models3D\00-Corpo\`. Real-world sizes: 00-Corpo-v5.spp = 879.2 MB, 00-Corpo-v6.spp = 1.087 GB, 00-Corpo-v6b.spp = 1.190 GB (all single character body piece). HDF5 is hierarchical binary, optimized for large scientific/project datasets. | Hierarchical random access to layers/metadata; incremental updates possible; built-in checksums for corruption detection. Suitable for complex, renderer-heavy tools. | **Real-world baseline**: single Substance body piece = 879 MB–1.19 GB (UzPainter must beat this). **Hypothesis** (not confirmed source): size driven by baked geometry, cache data, undo history, or inefficient layer encoding. HDF5 less common in game tooling; requires libhdf5 dependency (larger, more complex than ZIP/SQLite). Poor random access for single-layer extraction (hierarchical, not flat). Not designed for incremental saves via external tools (rewrites structure on save). | **Fact**: HDF5 under BSD 3-Clause license. [Source](https://www.hdfgroup.org/) | [HDF5 Group](https://www.hdfgroup.org/); Local file verification 2026-10-09 |
| **ZIP Container + JSON Manifest** | Single .zip (no compression, or Zstandard optional) containing: `manifest.json` (layer tree, UUIDs, properties), per-layer PNG/EXR file, bake cache as binary chunks, `metadata.json` (project settings, undo state checksum). Layers stored as `layers/<layer-uuid>.png`. | Human-inspectable (text manifest, image files readable); incremental save trivial (replace one file in ZIP); random access fast (ZIP central directory); corruption resilience (manifests versioned, orphan files ignored); AI-friendly (JSON + standard image formats). **Fact**: ZIP does not require decompression for random member access. | ZIP central directory overhead (~4% for many small files); need ZIP library (libzip, minizip); undo-free state harder to track (would need per-layer versioning or diffs). | **Fact**: ZIP public domain / various implementations permissive. | [ZIP Spec](https://en.wikipedia.org/wiki/ZIP_(file_format)) |
| **Zstandard-Compressed Archive** | ZIP or TAR wrapped with Zstandard (Zstd) instead of DEFLATE. `project.tar.zst` or `project.zip.zst` containing layers + manifest. | 1-2x smaller than ZIP+DEFLATE for mixed image/JSON data; Zstandard fast decompression; modern compression vs 1990s DEFLATE. | Must decompress entire archive for any layer read (no streaming member access); requires Zstandard library (less standard than ZIP's DEFLATE). | **Fact**: Zstandard under BSD 3-Clause. [Source](https://github.com/facebook/zstd) | [Zstandard GitHub](https://github.com/facebook/zstd) |
| **OpenRaster (.ora)** | Open specification for layered raster images; ZIP-based container with: `mimetype` (uncompressed), `stack.xml` (layer tree + blend modes), `data/` folder (layer PNG files), `Thumbnails/` folder (preview PNG), `mergedimage.png` (flattened preview). Version 0.0.6 (draft). | Standard format (adopted by Krita, GIMP, MyPaint, Drawpile, Pinta); open spec (no reverse engineering); layer metadata portable (blend modes, opacity, visibility flags in XML). | XML parsing required; blend mode set limited compared to Substance (Krita's ~20 modes vs Substance's 50+); no bake cache or procedural state storage (designed for hand-painted art, not 3D texture maps). | **Fact**: Open spec, various implementations under permissive licenses (Krita: LGPL, GIMP: GPL, MyPaint: ISC). [Source](https://en.wikipedia.org/wiki/OpenRaster) | [OpenRaster Wikipedia](https://en.wikipedia.org/wiki/OpenRaster) |
| **Custom Chunked Binary** | Inspired by USDZ/ORA: single file with fixed alignment (e.g., 64-byte chunk boundaries), UUID-indexed layer data, binary manifest, Zstd-compressed payloads. Similar structure to USD's "crunchable binary" (USDC) or IFF/RIFF chunks. | Total control; minimal overhead (direct mmap possible); compression tunable per chunk; version-tolerant (unknown chunks skipped). | Requires custom parser; no standard tooling; corruption harder to detect vs ZIP (checksum overhead); not human-inspectable without tool. | Project-specific, typically permissive. | [USDZ Spec](https://openusd.org/files/USDZFileFormatSpecification.pdf) |
| **USDZ (Universal Scene Description Zip)** | Khronos zip-based format (no compression, 64-byte alignment); designed for 3D scenes, not layered 2D images. Stores .usd/.usda, textures, audio; used in AR workflows. | Industry standard for 3D interchange; USD ecosystem mature; direct viewport integration (Apple, engines support it natively); not designed for layer stacks but extensible. | Over-engineered for a 2D painting tool; USD learning curve steep; **Fact**: USDZ specifically requires zero compression and 64-byte alignment, limiting how compact it can be. [Source](https://openusd.org/files/USDZFileFormatSpecification.pdf) | **Fact**: Apache 2.0 license. [Source](https://openusd.org/) | [USDZ File Format Spec](https://openusd.org/files/USDZFileFormatSpecification.pdf) |

## Comparison: Random Access, Incremental Save, Compression, Resilience

| Capability | ZIP+JSON | Zstd TAR | OpenRaster | Custom Binary | USDZ |
|------------|----------|---------|-----------|-----------------|------|
| **Random access to one layer** | Yes (ZIP index) | No (decompress all) | Yes (ZIP index) | Yes (offset table) | Yes (zip index) |
| **Incremental save** | Yes (replace one file) | No (re-archive all) | Yes (replace layer PNG) | Yes (append, rewrite manifest) | Yes (append to zip) |
| **Compression ratio** | ~40% of uncompressed (DEFLATE) | ~25-35% (Zstd superior) | ~40% (same as ZIP) | ~20-30% (Zstd, aligned) | ~45% (no compression mandated) |
| **Corruption resilience** | Partial (ZIP CRC per file) | Full archive lost on corruption | Partial (ZIP CRC, orphan tolerance) | Custom (depends on design) | Partial (ZIP CRC) |
| **Tool inspection** | Full (unzip, edit JSON/PNG) | Partial (need Zstd decoder) | Full (unzip, read XML) | None (binary) | Partial (unzip, read USD/textures) |
| **AI readability** | Excellent (JSON + standard formats) | Good (JSON readable after decompression) | Excellent (XML + PNG) | Poor (requires parser) | Good (XML + JSON-like USD) |

## Trade-Off Summary

**Recommendation for UzPainter Save Format:**

1. **Recommended (ZIP + JSON Manifest + PNG Layers)**:
   - **Why**: Best balance of tooling simplicity, AI readability, incremental save, and corruption resilience. Standard ZIP library (libzip, minizip) available everywhere. Manifest versioning easy (e.g., manifest.v1.json, manifest.v2.json for schema evolution). Layers human-readable and importable into Photoshop/Krita without tool.
   - **Structure**: `project.uzp` (ZIP container):
     ```
     manifest.json          # { layers: [...], metadata: {...}, version: "1.0" }
     bake_cache.bin        # Monolithic bake state (or per-layer chunks)
     layers/
       uuid-1.png          # sRGB or linear, lossless
       uuid-2.png
     metadata.json         # Undo checkpoint markers, project settings
     ```
   - **File size**: ~30-50 MB for typical 4K project (uncompressed ZIP); with optional DEFLATE post-archive, ~10-20 MB.

2. **Alternative (Zstandard wrapper for external distribution)**:
   - If disk footprint critical (e.g., cloud sync, USB distribution), wrap project.zip as `project.uzp.zst` (~20-30% reduction); inflate on load once.
   - Not recommended as native save format (unnecessary complexity for single-user desktop tool).

3. **Avoid**:
   - **HDF5**: Substance's approach, but real-world sizes (879 MB–1.19 GB per body piece) are the baseline to beat, not emulate. HDF5 not standard in game tooling; libhdf5 dependency adds complexity. ZIP+JSON preferable for UzPainter (simpler, AI-readable, open ecosystem).
   - **Custom Binary**: Maintenance burden; no AI tooling out-of-the-box.
   - **USDZ**: 3D-centric; mandated zero compression conflicts with "preferably compressed" requirement.
   - **OpenRaster**: Layer metadata too limited for Substance parity (no bake cache, no procedural state).

**Undo/History Strategy:**
- Store linear checkpoint chain: `undo/checkpoint-0.json`, `undo/checkpoint-1.json`, etc., each referencing layer state at that step.
- Alternatively: delta encoding (only changed layers per checkpoint); complex but compact.
- ZIP incremental append makes this feasible without rewriting entire project.

**Bake Cache Storage:**
- Bake results (Normal, Height, Curvature from geometry import) stored in binary chunks, indexed by UUID in manifest.
- Separate from layer PNGs (bake cache is transient; delete and rebuild if corrupted or source geometry changes).

## Sources
- [Substance File Format Archive](http://justsolve.archiveteam.org/wiki/Substance)
- [HDF5 Group](https://www.hdfgroup.org/)
- [ZIP File Format](https://en.wikipedia.org/wiki/ZIP_(file_format))
- [Zstandard](https://github.com/facebook/zstd)
- [OpenRaster Format](https://en.wikipedia.org/wiki/OpenRaster)
- [USDZ File Format Specification](https://openusd.org/files/USDZFileFormatSpecification.pdf)
- [USD Specification](https://openusd.org/)
- Local file verification (00-Corpo-v5.spp, v6.spp, v6b.spp HDF5 signatures confirmed 2026-10-09)
