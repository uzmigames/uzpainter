#pragma once

// The compositor's diagnostics (docs/architecture/04-layer-stack-and-compositing.md §8; LAY-09,
// LAY-14, EXP-04, DIA-01; task phase1.13_compositor-diagnostics, decisions 075 and 076): exports
// of the general evaluator, never a separate evaluation path.
//
// - `isolate(node)`: a map evaluated with one node (a layer, group, instance or effect) hidden.
//   The node is hidden in a private copy of the revision, the copy-on-write a transaction edits,
//   which is never committed: the document, its revision, its operation records and its save state
//   are untouched at every instant, so the prior visibility is restored atomically on success and
//   on a failure at any tile (LAY-09).
// - `contribution(node)`: the full map minus the isolated map, one float32 subtraction per sample
//   (a signed float32 map, never clamped).
// - `material_views(material)`: a material is a fill layer or group of the stack. Its region is
//   its effective mask, the float32 product of its own mask and the mask of every enclosing group
//   from the material outward (each mask as the engine evaluates it, 16 bits), inside where it is
//   at least `kInsideThreshold` (a 16-bit mask code of at least 32768). The ID view is the texture
//   set's ID mesh map inside the region; its leaks are the texels whose ID colour differs from the
//   region's modal ID colour. The BaseColor, Height, Normal, Roughness and Metallic views are the
//   full evaluation inside the region (Roughness and Metallic read Painter 12.1's channels
//   SpecularRoughness and BaseMetalness); their leaks are the texels whose full value differs
//   (bitwise) from the material's solo evaluation, the stack with every layer that is neither the
//   material, an enclosing group nor inside the material hidden: another material shows there
//   (LAY-14). A view the set or stack cannot give is listed as missing.
// - `region_stats(map, mask)`: statistics of a map over the texels inside a mask (DIA-01).
//
// A map is a document channel or a virtual normal map (height_to_normal.h, with its refusals);
// its values are float32 operands: the decoded stored values, constant tiles as their constant,
// so an exporter writes them with its own write rule. The evaluations run on the store (GPU or
// CPU, identical bit for bit); the differences, masking, leak comparisons and statistics run on
// the CPU over the read-back values, so both stores give the same diagnostic bytes. All the
// evaluations of one diagnostic read one revision. Every diagnostic is a source the export plan
// names (`DiagnosticSource`, `srcMapType` "diagnosticMap", EXP-04, decision 076).

#include "evaluator/admission.h"
#include "evaluator/evaluate.h"
#include "evaluator/geometry_mask.h"
#include "evaluator/resources.h"
#include "evaluator/templates.h"
#include "evaluator/tile_store.h"
#include "render/backend.h"

#include <array>
#include <cstdint>
#include <memory>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <vector>

#include "uzp_core/types/enums.h"
#include "uzp_core/types/ids.h"
#include "uzp_core/types/project.h"

namespace uzp::evaluator {

/// A texel is inside a mask when its value is at least this (it belongs more to the material
/// than not; decision 075).
inline constexpr float kInsideThreshold = 0.5f;

/// A map a diagnostic reads: a document channel or a virtual normal map.
struct DiagnosticMapId {
    enum class Kind : uint8_t { Channel, VirtualNormal };
    Kind kind = Kind::Channel;
    core::ChannelType channel = core::ChannelType::BaseColor;
    /// VirtualNormal: Normal_OpenGL or Normal_DirectX.
    core::NormalMapFormat convention = core::NormalMapFormat::OpenGL;

    static DiagnosticMapId Channel(core::ChannelType type) { return {Kind::Channel, type, {}}; }
    static DiagnosticMapId VirtualNormal(core::NormalMapFormat convention) {
        return {Kind::VirtualNormal, core::ChannelType::Normal, convention};
    }
    friend bool operator==(const DiagnosticMapId&, const DiagnosticMapId&) = default;
};

/// A ChannelType name, "Normal_OpenGL" or "Normal_DirectX".
[[nodiscard]] std::string MapName(const DiagnosticMapId& map);
/// The map a name gives; `evaluator:not_found` for any other name.
[[nodiscard]] render::Result<DiagnosticMapId> ParseMapName(std::string_view name);

/// A float32 raster, rows top first, `components` values per texel.
struct DiagnosticMap {
    uint32_t width = 0;
    uint32_t height = 0;
    uint32_t components = 0;
    std::vector<float> values;

    [[nodiscard]] float At(uint32_t x, uint32_t y, uint32_t c) const {
        return values[(size_t{y} * width + x) * components + c];
    }
    friend bool operator==(const DiagnosticMap&, const DiagnosticMap&) = default;
};

/// The values of a channel result (evaluate.h): every stored sample as its operand, constant
/// tiles as their constant.
[[nodiscard]] DiagnosticMap MapOf(const ChannelResult& result);

struct MaterialViews;

/// What every diagnostic evaluates: the stack, its template and the inputs of its sources.
struct DiagnosticRequest {
    core::Id textureSet = core::kNoId;
    core::Id stack = core::kNoId;
    std::string templateId{kDefaultTemplateId};
    /// The bytes of bitmap sources and mesh maps; may be null when there are none.
    std::shared_ptr<const IResourceProvider> resources;
    /// The rasters of `Mesh` geometry masks; may be null when the stack has none.
    std::shared_ptr<const IGeometryMaskProvider> geometry;
    /// The material views `MaterialViewsOn` already gave for one material of the same revision, or
    /// null: `EvaluateDiagnosticOn` reads that material's MaterialMask, and the MaterialView and
    /// MaterialLeaks of every view they hold, from them instead of computing them again (each is
    /// what a computation would give, bit for bit; B19, decision 246).
    std::shared_ptr<const MaterialViews> materialViews;
    std::shared_ptr<const IProceduralSourceProvider> procedurals{};
};

/// A copy of `project` with every node of `nodes` (layers or effects of the stack, at any depth)
/// hidden. Fails with `evaluator:not_found` naming a node that is not in the stack.
[[nodiscard]] render::Result<core::Project> HiddenCopy(const core::Project& project, core::Id textureSet,
                                                       core::Id stack, std::span<const core::Id> nodes);

/// `map` of revision `revision` of `project` evaluated on `store` with `cache` (EvaluateOn, or
/// EvaluateVirtualNormalOn for a virtual normal map), with the failures of those.
[[nodiscard]] render::Result<DiagnosticMap> EvaluateMapOn(const core::Project& project, std::int64_t revision,
                                                          const DiagnosticMapId& map,
                                                          const DiagnosticRequest& request,
                                                          const TemplateLibrary& templates, ITileStore& store,
                                                          TileCache& cache);

struct IsolationResult {
    core::Id node = core::kNoId;
    /// The node was visible in the revision (an invisible node isolates to the full map).
    bool wasVisible = true;
    DiagnosticMap map;
};

/// `map` evaluated with `node` hidden.
[[nodiscard]] render::Result<IsolationResult> IsolateOn(const core::Project& project, std::int64_t revision,
                                                        const DiagnosticMapId& map, core::Id node,
                                                        const DiagnosticRequest& request,
                                                        const TemplateLibrary& templates, ITileStore& store,
                                                        TileCache& cache);

struct ContributionResult {
    core::Id node = core::kNoId;
    DiagnosticMap full;
    DiagnosticMap isolated;
    /// full - isolated, one float32 subtraction per sample.
    DiagnosticMap difference;
};

/// The full map, the map with `node` hidden and their difference.
[[nodiscard]] render::Result<ContributionResult> ContributionOn(const core::Project& project,
                                                                std::int64_t revision,
                                                                const DiagnosticMapId& map, core::Id node,
                                                                const DiagnosticRequest& request,
                                                                const TemplateLibrary& templates,
                                                                ITileStore& store, TileCache& cache);

/// The views of material_views (LAY-14), in their order.
enum class MaterialViewKind : uint8_t { ID, BaseColor, Height, Normal, Roughness, Metallic };

/// "ID", "BaseColor", "Height", "Normal", "Roughness", "Metallic".
[[nodiscard]] std::string_view MaterialViewName(MaterialViewKind view);
/// The channel a view other than ID reads: BaseColor, Height, Normal, SpecularRoughness or
/// BaseMetalness (Painter 12.1's OpenPBR names; its templates have no legacy Roughness or Metallic
/// channel).
[[nodiscard]] core::ChannelType MaterialViewChannel(MaterialViewKind view);
[[nodiscard]] std::optional<MaterialViewKind> ParseMaterialView(std::string_view name);

/// A texel inside the region where another material shows.
struct LeakTexel {
    uint32_t x = 0;
    uint32_t y = 0;
    /// The view's value there and the material's own (the solo value, or the modal ID colour);
    /// unused components 0.
    std::array<float, 3> value{};
    std::array<float, 3> own{};
    friend bool operator==(const LeakTexel&, const LeakTexel&) = default;
};

struct MaterialView {
    MaterialViewKind view = MaterialViewKind::ID;
    /// The channel the view reads (MaterialViewChannel); unused by the ID view.
    core::ChannelType channel = core::ChannelType::BaseColor;
    /// The view's map inside the region, 0 outside.
    DiagnosticMap values;
    /// One component: 1 at a leak, else 0.
    DiagnosticMap leaks;
    /// The leaks, rows top first.
    std::vector<LeakTexel> leakTexels;
    /// ID view with a texel inside: the modal ID colour of the region.
    std::optional<std::array<float, 3>> modalId;
};

struct MaterialViews {
    core::Id material = core::kNoId;
    /// The effective mask (one component).
    DiagnosticMap mask;
    /// Texels inside the region.
    uint64_t inside = 0;
    /// The views the set and stack give, in MaterialViewKind order.
    std::vector<MaterialView> views;
    /// The views they cannot give (no ID mesh map, a channel the stack lacks).
    std::vector<MaterialViewKind> missing;
};

/// The material views of `material`. Fails with `evaluator:not_found` when it is not a layer of
/// the stack, `unsupported_node` for an instance layer (its solo is undefined: name its source),
/// `unsupported_source` for an ID mesh map that is not an 8- or 16-bit RGB image at the set
/// resolution, `missing_resource` for its missing bytes, and with the evaluations' failures.
[[nodiscard]] render::Result<MaterialViews> MaterialViewsOn(const core::Project& project, std::int64_t revision,
                                                            core::Id material, const DiagnosticRequest& request,
                                                            const TemplateLibrary& templates, ITileStore& store,
                                                            TileCache& cache);

/// The effective mask of `material` alone (MaterialViews::mask).
[[nodiscard]] render::Result<DiagnosticMap> MaterialMaskOn(const core::Project& project, core::Id material,
                                                           const DiagnosticRequest& request,
                                                           const TemplateLibrary& templates, ITileStore& store,
                                                           TileCache& cache);

/// Statistics of one value over a region, in double: min, max, mean (the correctly rounded sum
/// divided by the count) and the percentiles of the linear rule (Hyndman and Fan's definition 7,
/// numpy's default): h = (n - 1) q, v = x[floor h] + (h - floor h) (x[floor h + 1] - x[floor h])
/// over the sorted values.
struct ValueStats {
    double min = 0.0;
    double max = 0.0;
    double mean = 0.0;
    double p10 = 0.0;
    double p50 = 0.0;
    double p90 = 0.0;
    friend bool operator==(const ValueStats&, const ValueStats&) = default;
};

struct RegionStats {
    /// Texels of the map and texels inside the mask.
    uint64_t texels = 0;
    uint64_t inside = 0;
    /// inside / texels (the thresholded coverage) and the mean mask value (the weighted one).
    double coverage = 0.0;
    double maskMean = 0.0;
    /// Per component; empty when no texel is inside.
    std::vector<ValueStats> components;
    /// Three-component maps with a texel inside: the luminance ((r + g) + b) / 3 and the HSV
    /// saturation (max - min) / max (0 where max <= 0) of each texel, in double.
    std::optional<ValueStats> luminance;
    std::optional<ValueStats> saturation;
    friend bool operator==(const RegionStats&, const RegionStats&) = default;
};

/// The statistics of `map` over the texels where `mask` (one component, the map's size) is
/// inside. Fails with `evaluator:unsupported_source` when the sizes differ, the mask has more than
/// one component, or a mask value or a value inside is not finite.
[[nodiscard]] render::Result<RegionStats> ComputeRegionStats(const DiagnosticMap& map, const DiagnosticMap& mask);

/// The canonical JSON of region statistics (the export plan's statistics source): fixed key
/// order, every double as the shortest text that reads back to it.
[[nodiscard]] std::string RegionStatsJson(const RegionStats& stats);

/// The export plan's `srcMapType` of diagnostics (EXP-04, decision 076); `srcMapName` is
///   isolated/<map>/<node>           the map with the node hidden
///   contribution/<map>/<node>       full - isolated
///   materialMask/<material>         the effective mask
///   materialView/<view>/<material>  the view inside the region
///   materialLeaks/<view>/<material> 1 at a leak, else 0
///   regionStats/<map>/<material>    the map's statistics inside the material's region (a
///                                   statistics source: RegionStatsJson, not a raster)
/// with <map> a MapName, <view> a MaterialViewName and the uids in decimal.
inline constexpr std::string_view kDiagnosticMapType = "diagnosticMap";

struct DiagnosticSource {
    enum class Kind : uint8_t { Isolated, Contribution, MaterialMask, MaterialView, MaterialLeaks, RegionStats };
    Kind kind = Kind::Isolated;
    /// Isolated, Contribution, RegionStats.
    DiagnosticMapId map;
    /// MaterialView, MaterialLeaks.
    MaterialViewKind view = MaterialViewKind::ID;
    core::Id node = core::kNoId;
    friend bool operator==(const DiagnosticSource&, const DiagnosticSource&) = default;
};

/// The `srcMapName` of a source.
[[nodiscard]] std::string SourceName(const DiagnosticSource& source);
/// The source a `srcMapName` names; `evaluator:not_found` for a malformed name, an unknown kind,
/// map or view, or a uid that is not a positive decimal id.
[[nodiscard]] render::Result<DiagnosticSource> ParseSourceName(std::string_view name);

struct DiagnosticOutput {
    DiagnosticSource source;
    /// The revision the diagnostic was evaluated from.
    std::int64_t revision = 0;
    /// Every kind but RegionStats.
    std::optional<DiagnosticMap> map;
    /// RegionStats.
    std::optional<RegionStats> stats;
};

/// Evaluates the named diagnostic of revision `revision` of `project` on `store` with `cache`;
/// a material view the set or stack cannot give fails with `evaluator:not_found`.
[[nodiscard]] render::Result<DiagnosticOutput> EvaluateDiagnosticOn(const core::Project& project,
                                                                    std::int64_t revision,
                                                                    const DiagnosticSource& source,
                                                                    const DiagnosticRequest& request,
                                                                    const TemplateLibrary& templates,
                                                                    ITileStore& store, TileCache& cache);

}  // namespace uzp::evaluator
