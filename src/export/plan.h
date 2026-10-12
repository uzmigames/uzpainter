#pragma once

// The typed export plan (docs/architecture/08-export.md §1, §2, §6; task
// phase1.15_export-plan-compiler, decisions 085 and 086). `CompilePlan` turns a parsed
// configuration (config.h) and a project into every output file with its resolved sources,
// parameters, size, name and target format, before any evaluation or write. The plan is also the
// dry run: `ListProjectTextures` returns Painter's `list_project_textures` shape from it.
//
// Semantics (Painter's public export documentation and the Tier 0 recordings, decision 085):
//
// - rootPath is "<texture set>" for a set whose only stack is unnamed, "<texture set>/<stack>"
//   otherwise. The preset is the entry's `exportPreset`, else `defaultExportPreset`.
// - Filters: an absent member selects everything, a present empty list nothing. `dataPaths`
//   entries match a rootPath or its texture set; `outputMaps` entries match the map's
//   unexpanded `fileName` exactly; members combine with AND. `uvTiles` in the Default workflow is
//   not recorded and is refused.
// - Parameters per file: the preset map's `parameters`, then every matching `exportParameters`
//   rule in list order, each overriding the parameters it defines. fileFormat, bitDepth,
//   dithering and paddingAlgorithm must then be defined, and dilationDistance when the padding
//   needs it; sizeLog2 absent is the texture set's resolution. bitDepth must suit the format
//   (png: 8, 16; exr: 16f, 32f).
// - Presence: a documentMap whose channel the stack lacks (directly or through a recorded alias
//   pairing) makes its map absent, and a map whose channels are all `defaultMap white` is absent:
//   absent maps are skipped and listed in `skipped` (Painter writes neither). A map with a present
//   source and an absent documentMap, a map of `defaultMap black` only, an unbound mesh map and a
//   virtual map whose inputs the stack lacks are not recorded and are refused. A diagnosticMap
//   whose node is not in a stack is absent there; one whose node is in no exported stack is an
//   invalid configuration. A plan without any file is an invalid configuration.
// - Names: `$textureSet` is the set's name; under legacy colour management `$colorSpace` is
//   empty, and in the Default workflow `$udim` and `$uvTileName` are empty; a `( … )` group is
//   dropped when one of its wildcards is empty and written without its parentheses otherwise. An
//   empty wildcard outside a group, a group without wildcards, nested groups, `$mesh`,
//   `$project` and `$sceneMaterial` are not recorded and are refused. `/` separates
//   sub-folders. Two files whose paths are equal ignoring case are not recorded (Painter's
//   behaviour on a collision is unknown) and are refused naming both.
// - Channels: destChannels L, L+A, R+G+B or R+G+B+A. srcChannel L, R, G or B of a one-component
//   source reads its value; R, G or B of a three-component source reads that component; any
//   letter of a defaultMap reads its constant. L of a three-component source (an undocumented
//   mix) and A of any other source are refused.
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

/// A preset map Painter would not write for a stack (its sources are absent there).
struct SkippedMap {
    std::string textureSet;
    std::string stack;
    std::string rootPath;
    std::string preset;
    size_t mapIndex = 0;
    std::string fileName;
    std::string reason;
};

struct ExportPlan {
    std::string exportPath;
    /// In exportList order, then preset map order.
    std::vector<PlannedFile> files;
    std::vector<SkippedMap> skipped;
    /// Lower-case hex SHA-256 of the canonical JSON of `PlanJson` without its `hash` member.
    std::string hash;
};

/// Compiles `config` against `project` (see above).
[[nodiscard]] ExportPlan CompilePlan(const core::Project& project, const ExportConfig& config);
/// Parses and compiles the JSON text of a configuration.
[[nodiscard]] ExportPlan CompilePlan(const core::Project& project, std::string_view configJson);

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

/// The dry run: `list_project_textures(json_config)` on `project`.
[[nodiscard]] std::vector<StackFiles> ListProjectTextures(const core::Project& project, std::string_view configJson);

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
