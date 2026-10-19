#pragma once

// The bake request model of the CPU baker feasibility slice (phase3.1_baker-request-model,
// `docs/architecture/06-baking.md` §1-§4; decision 302). One request bakes one texture set:
// its low mesh, its high meshes (or the low mesh itself with `LowAsHigh`), the enabled usages and
// their settings. Only what this slice implements is modelled; everything else is refused before
// any work. Parity with Painter's bakers is NOT claimed: every usage here is `pending-evidence`.

#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

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
/// and required on the low mesh only.
struct BakeMesh {
    std::string name;
    std::vector<Float3> positions;
    std::vector<Float3> normals;
    std::vector<Float2> uvs;
    std::vector<std::uint32_t> indices;
};

/// Painter's ten `MeshMapUsage` bakers (`06-baking.md` §2). This slice bakes `AO` only.
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

/// `CageMode`: only the distance-based cage is implemented here.
enum class CageMode { DistanceBased, Automatic, CustomFile };

/// AO `Distribution` of the secondary rays over the hemisphere.
enum class Distribution { Uniform, Cosine };

/// Detail (high-poly) settings, distances in mesh units (absolute, not relative to the bounding
/// box). The primary ray starts `max_height` above the low surface along its normal and searches
/// down to `max_depth` below it.
struct DetailSettings {
    bool low_as_high = true;
    CageMode cage_mode = CageMode::DistanceBased;
    float max_height = 0.01f;
    float max_depth = 0.01f;
};

/// AO settings: `secondary_rays` per texel (`NbSecondary`), occluders searched from
/// `min_distance` to `max_distance` along each ray (mesh units).
struct AoSettings {
    std::uint32_t secondary_rays = 64;
    float min_distance = 0.0f;
    float max_distance = 1.0f;
    Distribution distribution = Distribution::Cosine;
};

/// One bake: one texture set, its meshes, the enabled usages and their settings.
struct BakeRequest {
    std::string texture_set;
    std::string input_revision;
    std::vector<MeshMapUsage> usages;
    /// `OutputSize`: log2 of the width and height.
    std::uint32_t output_size_log2[2] = {8, 8};
    DetailSettings detail;
    AoSettings ao;
    const BakeMesh* low = nullptr;
    /// Empty when `detail.low_as_high`.
    std::vector<const BakeMesh*> high;
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
    /// Parity status of every usage: never `supported` until Tier 2b evidence exists.
    std::string parity_status;
    std::string parity_owner_task;
};

/// The machine, the Embree build or the request is outside what the baker is qualified for.
/// Raised before any work; nothing is produced.
class CapabilityError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

/// Classes of a texel (the primary ray from the low surface to the high meshes). Every texel has
/// exactly one class; only `StraightHit` texels carry a baked value.
enum class TexelClass : std::uint8_t {
    Uncovered = 0,    // the texel centre lies in no UV triangle of the low mesh
    StraightHit = 1,  // the primary ray hit the front face of a high triangle
    BackFaceHit = 2,  // the primary ray's first hit was the back face of a high triangle
    CentreMiss = 3,   // the primary ray found no high triangle within the cage distances
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
};

/// The RAW AO map and its evidence maps (`06-baking.md` §4), row 0 at the top (v = 1).
/// `ao_raw` is the escaped fraction of a `StraightHit` texel's rays, round(65535 * escaped / rays)
/// in integers; every other texel holds 0 and is told apart only by `texel_class`: nothing is
/// filled or dilated. `back_face_rays` and `self_hit_rays` are per-texel ray counts.
struct BakeResult {
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    std::uint32_t tile_size = 0;
    std::uint32_t threads_used = 0;
    std::uint32_t rays_per_texel = 0;
    std::vector<std::uint16_t> ao_raw;
    std::vector<std::uint8_t> texel_class;
    std::vector<std::uint16_t> back_face_rays;
    std::vector<std::uint16_t> self_hit_rays;
    TexelClassCounts texels;
    RayClassCounts rays;
};

/// The canonical bytes of a result (little-endian; magic, sizes, the four maps, then the counts):
/// what the determinism proof compares across thread counts. `threads_used` is not part of it.
std::string SerializeResult(const BakeResult& result);

}  // namespace uzp::bake
