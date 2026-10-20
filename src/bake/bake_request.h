#pragma once

// The bake request model of the CPU baker (phase3.1_baker-request-model,
// `docs/architecture/06-baking.md` §1-§4; decisions 302 and 306). One request bakes one texture
// set: its low mesh parts, its high meshes (or the low parts themselves with `LowAsHigh`), an
// optional custom cage, the enabled usages and their settings. Only what the baker implements is
// modelled; everything else is refused before any work. Parity with Painter's bakers is NOT
// claimed: every usage here is `pending-evidence`.

#include <array>
#include <cstdint>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

#include "uzp_core/types/enums.h"

namespace uzp::bake {

struct Float2 {
    float x = 0.0f;
    float y = 0.0f;
};

struct Float3 {
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
};

/// An indexed triangle mesh. Triangles are counter-clockwise when seen from their front side
/// (the side `cross(p1 - p0, p2 - p0)` points to). `normals` are per vertex; `uvs` are per vertex
/// and required on the low mesh parts only. `name` drives name matching (`FilterMethod`).
struct BakeMesh {
    std::string name;
    std::vector<Float3> positions;
    std::vector<Float3> normals;
    std::vector<Float2> uvs;
    std::vector<std::uint32_t> indices;
    /// MikkTSpace tangent xyz and sign, one per index/corner (not per vertex).
    std::vector<std::array<float, 4>> corner_tangents;
    bool normal_frame_supported = true;
};

/// Painter's ten `MeshMapUsage` bakers (`06-baking.md` §2). CPU: AO, Normal, WorldSpaceNormal, Position, ID,
/// Thickness, Height and Opacity.
enum class MeshMapUsage {
    Normal,
    WorldSpaceNormal,
    ID,
    AO,
    Curvature,
    Position,
    Thickness,
    Height,
    BentNormals,
    Opacity,
};

const char* UsageName(MeshMapUsage usage);

/// The task that owns the baker of `usage` (`phase3.2_baker-normal`, `phase3.4_baker-*`).
std::string UsageOwnerTask(MeshMapUsage usage);

/// `CageMode`. `CustomFile` takes one cage mesh per low part (`BakeRequest::cage`), which
/// `CageParts` (`mesh_inputs.h`) builds from a cage file.
enum class CageMode { DistanceBased, Automatic, CustomFile };

/// `FilterMethod` (Painter's "Match"): which high meshes a low part's primary rays may hit.
enum class FilterMethod { Always, ByMeshName };

/// AO `Distribution` of the secondary rays over the hemisphere.
enum class Distribution { Uniform, Cosine };

/// Common settings: `DilationWidth` (texels) and `ApplyDiffusion`.
struct CommonSettings {
    std::uint32_t dilation_width = 0;
    bool apply_diffusion = false;
};

/// Detail (high-poly) settings. The distance-based primary ray starts `max_height` above the low
/// surface along its normal and searches down to `max_depth` below it; a custom cage ray starts on
/// the cage and searches to `max_depth` beyond the low surface (decision 306). The distances are
/// in the project's unit (centimetres) or, with `relative_to_bounding_box` (`RelativeScale`),
/// fractions of the project mesh's bounding-box size (decision 311).
struct DetailSettings {
    bool low_as_high = true;
    CageMode cage_mode = CageMode::DistanceBased;
    float max_height = 0.01f;
    float max_depth = 0.01f;
    bool relative_to_bounding_box = false;
    /// `IgnoreBackface`: primary rays pass through the back faces of every high mesh.
    bool ignore_backface = false;
    FilterMethod filter_method = FilterMethod::Always;
    /// Name-matching suffixes, read only with `FilterMethod::ByMeshName` (decision 306).
    std::string low_suffix = "_low";
    std::string high_suffix = "_high";
    std::string ignore_backface_suffix = "_ignorebf";
    /// `SubSampling`: k x k primary samples per texel, k in {1, 2, 4, 8} (1 = None).
    std::uint32_t subsampling = 1;
};

/// AO settings: `secondary_rays` per primary hit (`NbSecondary`), occluders searched from
/// `min_distance` to `max_distance` along each ray: centimetres or, with
/// `relative_to_bounding_box` (`MaxDistanceRelativeScale`), fractions of the bounding-box size.
struct AoSettings {
    std::uint32_t secondary_rays = 64;
    float min_distance = 0.0f;
    float max_distance = 1.0f;
    bool relative_to_bounding_box = false;
    Distribution distribution = Distribution::Cosine;
};

struct NormalSettings {
    core::TangentSpace tangent_space = core::TangentSpace::PerVertex;
    core::NormalMapFormat format = core::NormalMapFormat::OpenGL;
};

/// Position `Mode`, `Axis`, `Normalization` and `NormalizationScale` (decision 337), by Painter's
/// labels: "All axis" / "One axis", "X" / "Y" / "Z", "BBox" / "BSphere" / "None" and
/// "Per Material" / "Full Scene". The defaults are Painter's (`assets/defaults/baking.json`).
enum class PositionMode { AllAxis, OneAxis };
enum class PositionAxis { X, Y, Z };
enum class PositionNormalization { BBox, BSphere, None };
enum class PositionNormalizationScale { PerMaterial, FullScene };

struct PositionSettings {
    PositionMode mode = PositionMode::AllAxis;
    PositionAxis axis = PositionAxis::X;
    PositionNormalization normalization = PositionNormalization::BSphere;
    PositionNormalizationScale scale = PositionNormalizationScale::FullScene;
};

/// ID `ColorSource` and `ColorGenerator` (decision 337), by Painter's labels: "Vertex color",
/// "Material color", "File ID", "Mesh ID / Polygroup" and "Submesh"; "Random", "Hue shift" and
/// "Grayscale". The defaults are Painter's (`assets/defaults/baking.json`).
enum class IdColorSource { VertexColor, MaterialColor, FileId, MeshId, Submesh };
enum class IdColorGenerator { Random, HueShift, Grayscale };

struct IdSettings {
    IdColorSource source = IdColorSource::MaterialColor;
    /// Absent: the label map only, without colours (an evidence request no parameter makes).
    std::optional<IdColorGenerator> generator = IdColorGenerator::HueShift;
};

/// Thickness `MaximizeRange` ("Normalization") (decision 341), by Painter's labels: "Relative to ray
/// distances", "Relative to min/max (per UV tile)" and "None".
enum class ThicknessNormalization { RelativeToRayDistances, RelativeToMinMax, None };

/// Thickness settings (decision 341): `secondary_rays` inward rays per primary hit (`NbSecondary`)
/// over the hemisphere opposite the high normal, by `distribution`, each searched from
/// `min_distance` to `max_distance`: centimetres or, with `relative_to_bounding_box`
/// (`MaxDistanceRelativeScale`), fractions of the bounding-box size. The defaults are Painter's
/// (`assets/defaults/baking.json`).
struct ThicknessSettings {
    std::uint32_t secondary_rays = 64;
    float min_distance = 1e-5f;
    float max_distance = 0.1f;
    bool relative_to_bounding_box = true;
    Distribution distribution = Distribution::Cosine;
    /// Absent: the per-ray evidence only, no thickness value (an evidence request no parameter makes).
    std::optional<ThicknessNormalization> normalization = ThicknessNormalization::RelativeToMinMax;
};

/// Height `MaximizeRange` ("Normalization") and `Divisor` ("Scaling divisor") (decision 341), by
/// Painter's labels: "Relative to ray distances", "Relative to low mesh (per UV tile)",
/// "Relative to min/max (per UV tile)" and "Manual". The defaults are Painter's
/// (`assets/defaults/baking.json`).
enum class HeightNormalization { RelativeToRayDistances, RelativeToLowMesh, RelativeToMinMax, Manual };

struct HeightSettings {
    /// Absent: the signed distance only, unnormalised (an evidence request no parameter makes).
    std::optional<HeightNormalization> normalization = HeightNormalization::RelativeToLowMesh;
    float divisor = 1.0f;
};

/// An axis-aligned box in mesh units (`lower` <= `upper` on every axis).
struct BoundingBox {
    Float3 lower;
    Float3 upper;
};

/// What "the size of the bounding box" a relative distance is a fraction of means. Adobe's page
/// says only that a distance of 1 equals the size of the project mesh's bounding box; which size
/// is not established (decision 311), so a request names it and the parameter model never does.
enum class BoxSizeMetric { Diagonal, LargestExtent };

/// One bake: one texture set, its meshes, the enabled usages and their settings.
struct BakeRequest {
    std::string texture_set;
    std::string input_revision;
    std::vector<MeshMapUsage> usages;
    /// The mesh's `units.scale_to_internal` (centimetres per mesh unit, `12-mesh-import.md` §3):
    /// an absolute distance d is d / scale_to_internal mesh units. Required (0 = not given).
    double scale_to_internal = 0.0;
    /// The project mesh's bounding box (every texture set's parts, mesh units) and its size
    /// metric: required when a distance is relative to the bounding box.
    std::optional<BoundingBox> project_bounds;
    std::optional<BoxSizeMetric> box_size_metric;
    /// `OutputSize`: log2 of the width and height.
    std::uint32_t output_size_log2[2] = {8, 8};
    CommonSettings common;
    DetailSettings detail;
    AoSettings ao;
    NormalSettings normal;
    PositionSettings position;
    IdSettings id;
    HeightSettings height;
    ThicknessSettings thickness;
    /// The texture set's low mesh parts. Where UV islands overlap, the lowest part index, then
    /// the lowest triangle index, wins.
    std::vector<const BakeMesh*> low;
    /// Empty when `detail.low_as_high`.
    std::vector<const BakeMesh*> high;
    /// `CageMode::CustomFile`: one cage per low part, with the part's vertex count and indices.
    std::vector<const BakeMesh*> cage;
    /// Empty, or one byte per texel (row-major, row 0 at v = 1): non-zero texels are hidden.
    std::vector<std::uint8_t> hidden_mask;
    /// Ray-casting workers; 0 = every hardware thread. Never changes the output bytes.
    std::uint32_t threads = 0;
};

/// What the baker can do on this machine (`06-baking.md` §1).
struct Capabilities {
    std::vector<MeshMapUsage> usages;
    std::uint32_t max_output_size_log2 = 0;
    /// Repeatable on one build and one qualified CPU/ISA configuration, whatever the thread count.
    std::string determinism_class;
    std::string isa;
    std::string embree_version;
    std::string tasking_system;
    bool qualified = false;
    /// Why the configuration is not qualified (empty when it is).
    std::string unqualified_reason;
    /// True when the only reason is a BVH build thread count other than the qualified serial
    /// build: such a baker bakes only on the explicit diagnostic path (decision 306).
    bool diagnostic_build_threads = false;
    /// Parity status of every usage: never `supported` until Tier 2b evidence exists.
    std::string parity_status;
    std::string parity_owner_task;
    /// Per-usage owners; parity_owner_task retains the legacy AO owner.
    std::map<MeshMapUsage, std::string> parity_owner_tasks;
};

/// The machine, the Embree build or the request is outside what the baker is qualified for.
/// Raised before any work; nothing is produced.
class CapabilityError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

/// Classes of a texel. Every texel has exactly one; only `StraightHit` and `CageHit` texels carry
/// a baked value. With `SubSampling` the class aggregates the texel's sub-samples (decision 306).
enum class TexelClass : std::uint8_t {
    Uncovered = 0,    // no sub-sample of the texel lies in a UV triangle of the low parts
    StraightHit = 1,  // a distance-based primary ray hit the front face of a high triangle
    BackFaceHit = 2,  // no front hit; a primary ray's first hit was the back face of a high triangle
    CentreMiss = 3,   // no primary ray found a high triangle within the cage distances
    CageHit = 4,      // a custom-cage primary ray hit the front face of a high triangle
    Hidden = 5,       // covered, but marked by the request's hidden mask: no ray is cast
};

/// Classes of an AO secondary ray, counted per texel and per bake. Every ray has exactly one.
struct RayClassCounts {
    std::uint64_t escaped = 0;        // no hit in [min_distance, max_distance]
    std::uint64_t front_hit = 0;      // first hit is the front face of another triangle
    std::uint64_t back_face_hit = 0;  // first hit is the back face of another triangle
    std::uint64_t self_hit = 0;       // first hit is the ray's own origin triangle
};

struct TexelClassCounts {
    std::uint64_t uncovered = 0;
    std::uint64_t straight_hit = 0;
    std::uint64_t back_face_hit = 0;
    std::uint64_t centre_miss = 0;
    std::uint64_t cage_hit = 0;
    std::uint64_t hidden = 0;
};

/// Sub-sample coverage accumulation (`SubSampling`): `covered` = `hit` + `back_face_hit` +
/// `centre_miss` + `hidden`.
struct SubsampleCounts {
    std::uint64_t covered = 0;
    std::uint64_t hit = 0;
    std::uint64_t back_face_hit = 0;
    std::uint64_t centre_miss = 0;
    std::uint64_t hidden = 0;
};

/// The distances a bake used, recorded with its maps (`06-baking.md` §3, decision 311): the
/// request's unit scale, whether each group was relative, the bounding-box size (mesh units; 0
/// when no distance was relative) and the effective distances in mesh units.
struct DistanceRecord {
    double scale_to_internal = 0.0;
    bool detail_relative = false;
    bool ao_relative = false;
    BoxSizeMetric box_size_metric = BoxSizeMetric::Diagonal;  // meaningful when box_size > 0
    double box_size = 0.0;
    float max_height = 0.0f;
    float max_depth = 0.0f;
    float ao_min_distance = 0.0f;
    float ao_max_distance = 0.0f;
};

/// The size of the project mesh's bounding box under the request's metric (mesh units), which a
/// distance relative to the bounding box is a fraction of. Raises `uzp::core::ValueError` (no or
/// invalid box) or `NotYetSupported` (no size metric).
double BoundingBoxSize(const BakeRequest& request);

/// The effective mesh-unit distances of `request`: absolute distances divided by
/// `scale_to_internal`, relative ones multiplied by the bounding-box size. Raises
/// `uzp::core::ValueError` (no or invalid scale, no or invalid box) or `NotYetSupported` (a
/// relative distance without a size metric).
DistanceRecord EffectiveDistances(const BakeRequest& request);

/// The normalisation a Position bake applied (`baked.effective_normalization`, decision 337).
/// With `Normalization` None a value is the mesh-unit coordinate times `scale_to_internal`, in
/// centimetres, and no bounds apply, so `NormalizationScale` has no effect (`bounds_applied` false).
struct PositionNormalizationRecord {
    PositionSettings settings;
    std::uint32_t channels = 0;
    double scale_to_internal = 0.0;
    bool bounds_applied = false;
};

/// The class of a Thickness ray (decision 341), stored per ray: `NotCast` on a texel without a hit
/// (no ray is cast); otherwise the classes of decision 302 §4.
enum class ThicknessRayClass : std::uint8_t { NotCast = 0, Escaped = 1, FrontHit = 2, BackFaceHit = 3, SelfHit = 4 };

/// What a Thickness bake cast (decision 341): the settings, the unit scale, the bounding-box size
/// (mesh units; 0 when the distances are absolute), the effective mesh-unit distances and the
/// totals of the inward rays by class, apart from AO's `BakeResult::rays`.
struct ThicknessRecord {
    ThicknessSettings settings;
    double scale_to_internal = 0.0;
    double box_size = 0.0;
    float min_distance = 0.0f;
    float max_distance = 0.0f;
    RayClassCounts rays;
};

/// What a Height bake applied (`baked.effective_normalization`, decision 341): the settings, the
/// unit scale (a value is the mesh-unit distance times `scale_to_internal`, in centimetres) and
/// whether a normalisation or the divisor was applied (neither is, until a golden settles them).
struct HeightNormalizationRecord {
    HeightSettings settings;
    double scale_to_internal = 0.0;
    bool normalization_applied = false;
    bool divisor_applied = false;
};

/// The baked AO map, its RAW map and its evidence maps (`06-baking.md` §4), row 0 at the top
/// (v = 1). `ao_raw` is the escaped fraction of the rays of a texel's hit sub-samples,
/// round(65535 * escaped / (hits * rays)) in integers; every other texel holds 0 and is told
/// apart only by `texel_class`: nothing is filled or repaired. `ao` is `ao_raw` dilated by
/// `DilationWidth` into `Uncovered` texels only. `coverage` and `subsample_hits` count a texel's
/// covered and hit sub-samples; `back_face_rays` and `self_hit_rays` are per-texel ray counts.
struct BakeResult {
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    std::uint32_t tile_size = 0;
    std::uint32_t threads_used = 0;
    std::uint32_t rays_per_texel = 0;  // secondary rays per hit sub-sample
    std::uint32_t subsampling = 1;
    std::uint32_t dilation_width = 0;
    std::vector<std::uint16_t> ao;
    std::vector<std::uint16_t> ao_raw;
    /// RGB16 interleaved, zero on non-hit texels; no negative-Z repair.
    std::vector<std::uint16_t> normal_raw;
    std::vector<std::uint16_t> normal;
    /// WorldSpaceNormal (decision 337): the unit high normal at the hit, in the meshes' scene frame,
    /// as float32 xyz interleaved, signed and unencoded (the channel format and value mapping wait
    /// on the Tier 2b goldens); zero on non-hit texels.
    std::vector<float> world_normal;
    /// Position (decision 337): the high surface point at the hit, `position_normalization.channels`
    /// float32 per texel (xyz for All axis, the axis for One axis); zero on non-hit texels.
    std::vector<float> position;
    PositionNormalizationRecord position_normalization;
    /// ID (decision 337): per texel the label of the high mesh the hit is on, its index in the
    /// request plus one (0 on non-hit texels), and the mesh names in label order.
    std::vector<std::uint16_t> id_labels;
    std::vector<std::string> id_label_meshes;
    /// Opacity (decision 341): per texel the opacity of the high surface at the hit, float32 in
    /// [0, 1] and unencoded; a bake mesh carries no transparency input, so a hit is 1. Zero on
    /// non-hit texels.
    std::vector<float> opacity;
    /// Height (decision 341): per texel the signed distance from the low surface to the high
    /// surface along the primary ray, positive where the high surface lies in front of the low one
    /// (towards the ray's origin), in centimetres, float32 and unnormalised; zero on non-hit texels.
    std::vector<float> height_map;
    HeightNormalizationRecord height_normalization;
    /// Thickness (decision 341): the per-ray evidence, `thickness.settings.secondary_rays` slots per
    /// texel. `thickness_ray_class` holds each inward ray's class and `thickness_ray_distance` the
    /// distance of its first hit in centimetres (float32; 0 when it escapes or was not cast). No
    /// per-texel thickness value exists: how the rays combine is not recorded.
    std::vector<std::uint8_t> thickness_ray_class;
    std::vector<float> thickness_ray_distance;
    ThicknessRecord thickness;
    core::TangentSpace tangent_space = core::TangentSpace::PerVertex;
    core::NormalMapFormat normal_format = core::NormalMapFormat::OpenGL;
    std::vector<std::uint8_t> texel_class;
    std::vector<std::uint8_t> coverage;
    std::vector<std::uint8_t> subsample_hits;
    std::vector<std::uint16_t> back_face_rays;
    std::vector<std::uint16_t> self_hit_rays;
    TexelClassCounts texels;
    SubsampleCounts subsamples;
    RayClassCounts rays;
    std::uint64_t dilated_texels = 0;
    DistanceRecord distances;
    /// Baked on the explicit diagnostic path of an unqualified BVH build thread count: never
    /// evidence (decision 306). Not part of the canonical bytes.
    bool diagnostic_unqualified = false;
};

/// The canonical bytes of a result (little-endian; AO-only keeps `UZPBAKE3`; Normal uses
/// `UZPBAKE4` with usage flags, mode, format and RGB maps before the existing sizes/maps/counts,
/// then the distance record; each geometry map present, and only then, follows as a tagged block:
/// `WSN1` for WorldSpaceNormal, `POS1` for Position, `IDM1` for ID, `OPA1` for Opacity, `HGT1` for
/// Height, `THK1` for Thickness): what the
/// determinism proof compares across thread counts.
/// `threads_used` is not part of it.
std::string SerializeResult(const BakeResult& result);

}  // namespace uzp::bake
