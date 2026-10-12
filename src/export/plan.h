#pragma once

// The typed export plan (docs/architecture/08-export.md §1, §2, §6; task
// phase1.15_export-plan-compiler, decisions 085, 086 and 091). `CompilePlan` turns a parsed
// configuration (config.h) and a project into every output file with its resolved sources,
// parameters, size, name and target format, before any evaluation or write. The plan is also the
// dry run: `ListProjectTextures` returns, in Painter's `list_project_textures` shape, exactly the
// files the export writes (decision 091). Painter's own `list_project_textures` also names maps
// its export then does not write or refuses; the plan keeps those in `skipped` with their kind.
//
// Semantics (Painter's public export documentation, the Tier 0 recordings, decision 085, and the
// export probes of recording R-085, decision 091):
//
// - rootPath is "<texture set>" for a set whose only stack is unnamed, "<texture set>/<stack>"
//   otherwise. The preset is the entry's `exportPreset`, else `defaultExportPreset`.
// - Filters: an absent member selects everything, a present empty list nothing. `dataPaths`
//   entries match a rootPath or its texture set; `outputMaps` entries match the map's
//   unexpanded `fileName` exactly; `uvTiles` selects a texture set of the Default workflow (the
//   single tile [0, 0], UDIM 1001) when it lists [0, 0]; members combine with AND.
// - Parameters per file: the preset map's `parameters`, then every matching `exportParameters`
//   rule in list order, each overriding the parameters it defines. fileFormat, bitDepth,
//   dithering and paddingAlgorithm must then be defined, and dilationDistance when the padding
//   needs it; sizeLog2 absent is the texture set's resolution. bitDepth must suit the format
//   (png: 8, 16; exr: 16f, 32f).
// - Presence: a documentMap whose channel the stack lacks (directly or through a recorded alias
//   pairing) makes its map absent, and a map whose channels are all `defaultMap white` is absent:
//   absent maps are skipped (`SkipKind::absent`, Painter writes neither). A map whose channels
//   are all `defaultMap black` is listed by Painter but not written (`not_written`). An unbound
//   mesh map, and a legacy name whose channel and pairing the stack lacks (`RaisesWhenAbsent`),
//   are listed by Painter but their export raises ValueError (`export_error`; the dry run raises
//   too, `CheckExportable`). An absent documentMap as the alpha of an R+G+B+A map whose R, G and B
//   are present drops the alpha: the file is R+G+B. Any other mix of present and absent sources,
//   a mix of black and white default maps and a virtual map whose inputs the stack lacks are not
//   recorded and are refused. A diagnosticMap whose node is not in a stack is absent there; one
//   whose node is in no exported stack is an invalid configuration. A plan may write no file.
// - Names: `$textureSet` is the set's name, `$sceneMaterial` its mesh material (`original_name`),
//   `$mesh` the imported mesh file's name without its extension, `$project` the project file's
//   name without its extension, `Untitled` while it was never saved (`PlanContext`); under legacy
//   colour management `$colorSpace` is empty, and in the Default workflow `$udim` and
//   `$uvTileName` are empty, also outside a group. A `( … )` holding no parenthesis and at least
//   one wildcard is a group: dropped when one of its wildcards is empty, written without its
//   parentheses otherwise; every other parenthesis is a literal character. A mesh or project file
//   name with more than one dot is not recorded and is refused. `/` separates sub-folders. Within
//   one exportList entry, a later map whose path equals an earlier one's gets `_1` before its
//   extension; a third equal path, equal paths of two entries and paths equal only ignoring case
//   are not recorded and are refused naming both.
// - Channels: destChannels L, L+A, R+G+B or R+G+B+A. srcChannel L, R, G or B of a one-component
//   source reads its value; R, G or B of a three-component source reads that component; L of a
//   three-component source reads the Rec. 601 luma of its linear components, fma(0.114, b,
//   fma(0.299, r, 0.587 g)) in float32 (probe P5, decision 091); any letter of a defaultMap reads
//   its constant. A of any other source is not recorded beyond full and no coverage and is
//   refused.
// - A `diagnosticMap` `regionStats/...` source is a statistics file: the map's only channel
//   (destChannel L), written as canonical JSON (`<name>.json`, decision 076); anywhere else it
//   is an invalid configuration.
//
// Failures throw before anything is written: `core::ValueError` (an invalid configuration in the
// context of the project) or `core::NotYetSupported` (a release gap or an unrecorded behaviour,
// naming its owner or the recording it needs).

#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "evaluator/diagnostics.h"
#include "export/config.h"
#include "export/virtual_maps.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/types/enums.h"
#include "uzp_core/types/ids.h"
#include "uzp_core/types/project.h"

namespace uzp::exporter {

/// The plan's JSON schema id.
inline constexpr std::string_view kPlanSchema = "uzpainter/export-plan/1";

/// A channel's source resolved against one stack.
struct PlannedSource {
    SourceType type = SourceType::documentMap;
    /// `srcMapName` as given.
    std::string name;
    /// documentMap: the stack's member read (after an alias pairing).
    std::optional<core::ChannelType> channel;
    /// meshMap: the bound mesh map.
    std::optional<core::MeshMapUsage> meshMap;
    std::optional<VirtualMap> virtualMap;
    /// defaultMap: its constant.
    std::optional<float> constant;
    std::optional<evaluator::DiagnosticSource> diagnostic;
    /// Components of the source's values (1 or 3).
    uint32_t components = 1;
    /// Normal sources: `combined` (Normal_OpenGL, Normal_DirectX) or `geometry_only` (normal_base).
    std::optional<core::MeshMapRole> normalRole;
};

struct PlannedChannel {
    ChannelLetter dest = ChannelLetter::L;
    ChannelLetter src = ChannelLetter::L;
    /// The component of the source's values this channel reads.
    uint32_t component = 0;
    /// srcChannel L of a three-component source: the Rec. 601 luma of its components (probe P5,
    /// decision 091) instead of `component`.
    bool luma = false;
    PlannedSource source;
};

enum class FileLayout : uint8_t { L, LA, RGB, RGBA, Statistics };
[[nodiscard]] std::string_view FileLayoutName(FileLayout layout);

struct ResolvedParameters {
    FileFormat fileFormat = FileFormat::png;
    BitDepth bitDepth = BitDepth::u8;
    bool dithering = false;
    std::optional<SizeLog2> sizeLog2;
    Padding paddingAlgorithm = Padding::infinite;
    std::optional<int> dilationDistance;
};

struct PlannedFile {
    std::string textureSet;
    /// "" for the unnamed stack.
    std::string stack;
    core::Id textureSetId = core::kNoId;
    core::Id stackId = core::kNoId;
    std::string rootPath;
    std::string preset;
    /// The map's index in its preset.
    size_t mapIndex = 0;
    /// The unexpanded `fileName`.
    std::string fileName;
    /// The expanded name with its extension, `/`-separated, relative to exportPath.
    std::string relativePath;
    /// exportPath / relativePath.
    std::string path;
    FileLayout layout = FileLayout::RGB;
    /// In destination order (L, R, G, B, A).
    std::vector<PlannedChannel> channels;
    /// Absent for a statistics file.
    std::optional<ResolvedParameters> parameters;
    /// The written size (sizeLog2 applied); for a statistics file the set's resolution.
    uint32_t width = 0;
    uint32_t height = 0;
};

/// Why the export writes no file for a preset map of a stack (decision 091).
enum class SkipKind : uint8_t {
    /// Its sources are absent in the stack: Painter writes no file.
    absent,
    /// Painter's `list_project_textures` lists it, its export writes nothing (black only).
    not_written,
    /// Painter's `list_project_textures` lists it, its export raises ValueError.
    export_error,
};
[[nodiscard]] std::string_view SkipKindName(SkipKind kind);

/// A preset map the export does not write for a stack.
struct SkippedMap {
    std::string textureSet;
    std::string stack;
    std::string rootPath;
    std::string preset;
    size_t mapIndex = 0;
    std::string fileName;
    std::string reason;
    SkipKind kind = SkipKind::absent;
};

struct ExportPlan {
    std::string exportPath;
    /// In exportList order, then preset map order.
    std::vector<PlannedFile> files;
    std::vector<SkippedMap> skipped;
    /// Lower-case hex SHA-256 of the canonical JSON of `PlanJson` without its `hash` member.
    std::string hash;
};

/// What a plan reads besides the project and its configuration.
struct PlanContext {
    /// The project file's path; empty while the project was never saved (`$project` is then
    /// `Untitled`, probe P1).
    std::string projectPath;
};

/// Compiles `config` against `project` (see above).
[[nodiscard]] ExportPlan CompilePlan(const core::Project& project, const ExportConfig& config,
                                     const PlanContext& context = {});
/// Parses and compiles the JSON text of a configuration.
[[nodiscard]] ExportPlan CompilePlan(const core::Project& project, std::string_view configJson,
                                     const PlanContext& context = {});

/// Throws `core::ValueError` naming the first `export_error` map of `plan` when the plan writes no
/// file: Painter's export of that configuration raises ValueError, and so do the dry run and the
/// export, before anything is written (probes P12, P13, decision 091). With files to write it
/// throws `core::NotYetSupported`: whether Painter writes them before it raises is not recorded.
void CheckExportable(const ExportPlan& plan);

/// The plan as JSON (`kPlanSchema`): exportPath, files (every field of PlannedFile), skipped and
/// hash. Its canonical form (core::json::WriteCanonical) is byte-stable.
[[nodiscard]] core::json::Value PlanJson(const ExportPlan& plan);

/// One stack's files, as `list_project_textures` groups them.
struct StackFiles {
    std::string textureSet;
    std::string stack;
    std::vector<std::string> files;

    friend bool operator==(const StackFiles&, const StackFiles&) = default;
};

/// The plan's files grouped by (texture set, stack) in first-appearance order: Painter's
/// `list_project_textures` result.
[[nodiscard]] std::vector<StackFiles> FilesByStack(const ExportPlan& plan);

/// The dry run: the files `export_project_textures(json_config)` writes on `project`, grouped as
/// `list_project_textures` groups them (CompilePlan, CheckExportable, FilesByStack).
[[nodiscard]] std::vector<StackFiles> ListProjectTextures(const core::Project& project, std::string_view configJson,
                                                          const PlanContext& context = {});

/// The inputs every source of a planned file reads.
struct SourceInputs {
    std::string templateId{evaluator::kDefaultTemplateId};
    std::shared_ptr<const evaluator::IResourceProvider> resources;
    std::shared_ptr<const evaluator::IGeometryMaskProvider> geometry;
};

/// A planned file's content before processing: its channels in destination order, float32
/// values at the texture set's resolution (padding and encoding: padding.h, encode.h), or the
/// canonical statistics JSON of a statistics file.
struct FileRaster {
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t channels = 0;
    /// Rows top first, `channels` values per texel.
    std::vector<float> values;
    /// The EXP-09 tag of the file's normal source, when it has one.
    std::optional<evaluator::NormalTag> normalTag;
    /// Statistics files: RegionStatsJson.
    std::optional<std::string> statistics;
};

/// Evaluates every source of `file` (compiled from revision `revision` of `project`) on `store`
/// with `cache` and assembles its channels: documentMap the channel read-out, meshMap and
/// virtualMap through virtual_maps.h, defaultMap its constant, diagnosticMap through
/// `evaluator::EvaluateDiagnosticOn` (decision 076). Each source is evaluated once per file.
[[nodiscard]] render::Result<FileRaster> EvaluateFileOn(const core::Project& project, std::int64_t revision,
                                                        const PlannedFile& file, const SourceInputs& inputs,
                                                        const evaluator::TemplateLibrary& templates,
                                                        evaluator::ITileStore& store, evaluator::TileCache& cache);

}  // namespace uzp::exporter
