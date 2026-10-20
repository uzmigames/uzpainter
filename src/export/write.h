#pragma once

// Writing a plan's files (docs/architecture/08-export.md §3, §5; task
// phase1.16_export-processing-encoders, decisions 089 and 090): every planned file evaluated,
// padded, encoded and written under the plan's exportPath at its relativePath. Generations, the
// delivery pointer and receipts are phase1.17_export-publication-receipts, which builds on this.
//
// Order, so that a refusal or a failure leaves nothing written:
// 1. every file's processing is checked (CheckProcessing: NotYetSupported for an unrecorded one),
//    then a combined virtual normal on a UV-islanded set (CheckIslandNormal, statistics files
//    included) and the padding (CheckPadding);
// 2. every file is evaluated (EvaluateFileOn), padded over its texture set's coverage
//    (ApplyPadding) and encoded (EncodeFile) in memory, and its `.uztexture` derivative, when the
//    plan requests one, cooked from the encoded samples (`EncodedUzTexture`, decision 316);
// 3. only then are the files written, in plan order, each derivative right after its file,
//    sub-folders created as needed.
//
// The coverage comes from `inputs.geometry` (the texture set's material, every object); a
// configuration with an image file and no texturing mesh fails before anything is written. Same
// build, project and configuration give the same bytes (EXP-05).
//
// The diagnostic measure export (`DiagnosticMeasure`, decision 286) is NOT conformant and never
// the default: only `UzPainter.exe run --diagnostic-measure-export` reaches it (python/run.h). It
// writes what production refuses on a UV-islanded set so that the whole pipeline can be scored
// against Painter: step 1 records the refusals of CheckIslandNormal and of CheckPadding instead of
// throwing them (`EncodedFile::bypassed`; every other check still throws), and step 2 pads with
// `InexactPadding::measure` over the coverage and its triangles. A combined virtual normal
// (`Normal_OpenGL`, `Normal_DirectX`) is computed and padded by Painter's recorded rule
// (virtual_maps.h `VirtualMapRequest::islandNormal`, decision 308): its stencil reads the padded
// Height at the island edge (decisions 263, 288), its ring copies the nearest covered mesh-free
// normal (decision 287) and its gutter floods it, under the mesh map at each uncovered texel
// (decisions 276, 285). With a mesh map bound, that combination's form is not recorded: its texels
// are counted as undecided (`EncodedFile::undecided`). A diagnosticMap of a virtual normal keeps
// the whole-tile evaluation, padded as its stored values. The receipt marks such a generation
// `non_conformant` (receipt.h).

#include <array>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "export/padding.h"
#include "export/plan.h"

namespace uzp::mesh {
struct TexturingMesh;
}

namespace uzp::exporter {

/// The diagnostic measure export of decision 286 (above): not conformant. `mesh` is the texturing
/// mesh `inputs.geometry` rasterises, whose triangles the measured padding reads
/// (padding.h `IslandTriangles`).
struct DiagnosticMeasure {
    std::shared_ptr<const mesh::TexturingMesh> mesh;
};

/// The texel-centre UV coverage of every object of `set`'s material (`inputs.geometry`), or
/// nullopt without a texturing mesh. `uzpainter.diagnostics` reads it for CheckIslandNormal's
/// refusal of its in-memory views (padding.h, decision 245).
[[nodiscard]] std::optional<Coverage> CoverageOf(const core::TextureSet& set, const SourceInputs& inputs);

/// A planned file's `.uztexture` normal derivative, cooked in memory (plan.h `UzTextureOutput`,
/// decision 316): the file's PNG 16 samples, A = 65535, as the `Normal` class of
/// uztexture_writer.h `CookUzTexture`, binding `normal`, linear. Its negative-Z texels (B <= 32767)
/// are found first: with any of them, policy `fail` stops the export with an `export:` failure
/// naming their count and the first, before anything is published, and policy `rgb` stores the map
/// as RGBA8 (`routed`); otherwise it is stored as BC5.
struct EncodedUzTexture {
    std::string bytes;
    /// "BC5" or "RGBA8".
    std::string format;
    uint32_t mips = 0;
    NegativeZPolicy policy = NegativeZPolicy::fail;
    uint64_t negativeTexels = 0;
    /// The first negative-Z texel in row-major order, when there is one.
    std::optional<std::array<uint32_t, 2>> firstNegative;
    bool routed = false;
    /// The block encoder, for the receipt ("etcpak 2.1").
    std::string encoder;
};

/// A planned file's bytes, encoded in memory.
struct EncodedFile {
    std::string bytes;
    /// The EXP-09 tag of the file's normal source, when it has one.
    std::optional<evaluator::NormalTag> normalTag;
    /// The layout written: the plan's, or L / RGB when an all-opaque alpha was dropped (encode.h).
    FileLayout layout = FileLayout::L;
    /// Encoded by the diagnostic measure export (decision 286): not conformant.
    bool diagnostic = false;
    /// The production refusals that export bypassed for this file, their messages in check order.
    std::vector<std::string> bypassed{};
    /// The diagnostic measure export: the file's texels whose form is not recorded, written by the
    /// best-known rule (`FileRaster::undecided`, decision 308).
    uint64_t undecided = 0;
    /// The file's `.uztexture` derivative, when the plan requests one.
    std::optional<EncodedUzTexture> uztexture{};
};

/// Steps 1 and 2 above: every file of `plan` (compiled from revision `revision` of `project`)
/// checked, then evaluated, padded and encoded in memory, in plan order. Throws
/// `core::NotYetSupported` (or `core::ValueError`) before anything is evaluated for an unrecorded
/// processing or padding; returns the evaluator's failure, or an `export:` failure (no texturing
/// mesh, a padding or encoder that fails). Writes nothing. With `diagnostic`, the diagnostic
/// measure export (above, decision 286); it fails without its mesh.
[[nodiscard]] render::Result<std::vector<EncodedFile>> EncodeExport(const core::Project& project, std::int64_t revision,
                                                                    const ExportPlan& plan, const SourceInputs& inputs,
                                                                    const evaluator::TemplateLibrary& templates,
                                                                    evaluator::ITileStore& store,
                                                                    evaluator::TileCache& cache,
                                                                    const DiagnosticMeasure* diagnostic = nullptr);

struct WrittenFile {
    std::string rootPath;
    /// `/`-separated, relative to exportPath.
    std::string relativePath;
    std::string path;
    uint64_t size = 0;
    /// Lower-case hex SHA-256 of the bytes written.
    std::string sha256;
};

/// Writes every file of `plan` (compiled from revision `revision` of `project`), each `.uztexture`
/// derivative after its file. Throws
/// `core::NotYetSupported` before anything is evaluated for an unrecorded processing or padding;
/// returns the evaluator's failure, or an `export:` failure (no texturing mesh, a write that
/// fails), with nothing written except, for a write failure, the files before it.
[[nodiscard]] render::Result<std::vector<WrittenFile>> WriteExport(const core::Project& project, std::int64_t revision,
                                                                   const ExportPlan& plan, const SourceInputs& inputs,
                                                                   const evaluator::TemplateLibrary& templates,
                                                                   evaluator::ITileStore& store,
                                                                   evaluator::TileCache& cache);

}  // namespace uzp::exporter
