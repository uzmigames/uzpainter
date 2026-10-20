#include "bake/embree_baker.h"

#include <cpuid.h>
#include <xmmintrin.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <exception>
#include <limits>
#include <system_error>
#include <thread>
#include <type_traits>
#include <vector>

#include "bake/sampling.h"
#include "bake/mesh_inputs.h"
#include "bake/height_baker.h"
#include "bake/id_baker.h"
#include "bake/opacity_baker.h"
#include "bake/position_baker.h"
#include "bake/thickness_baker.h"
#include "bake/world_normal_baker.h"
#include "mesh/tangents.h"
#include "uzp_core/types/errors.h"

namespace uzp::bake {

using core::NotYetSupported;
using core::ValueError;

// ── Qualification ────────────────────────────────────────────────────────────────────────────

CpuFeatures DetectCpuFeatures() {
    CpuFeatures features;
    unsigned a = 0, b = 0, c = 0, d = 0;
    if (__get_cpuid(1, &a, &b, &c, &d)) {
        features.fma = (c >> 12) & 1u;
        features.f16c = (c >> 29) & 1u;
        const bool osxsave = (c >> 27) & 1u;
        const bool avx = (c >> 28) & 1u;
        if (osxsave && avx) {
            unsigned xcr0_lo = 0, xcr0_hi = 0;
            __asm__ volatile("xgetbv" : "=a"(xcr0_lo), "=d"(xcr0_hi) : "c"(0));
            features.os_ymm = (xcr0_lo & 0x6u) == 0x6u;
        }
    }
    if (__get_cpuid_count(7, 0, &a, &b, &c, &d)) {
        features.bmi1 = (b >> 3) & 1u;
        features.avx2 = (b >> 5) & 1u;
        features.bmi2 = (b >> 8) & 1u;
    }
    if (__get_cpuid(0x80000001u, &a, &b, &c, &d)) features.lzcnt = (c >> 5) & 1u;
    return features;
}

std::string UnqualifiedIsaReason(const CpuFeatures& features) {
    std::string missing;
    const auto need = [&](bool present, const char* name) {
        if (!present) missing += (missing.empty() ? "" : ", ") + std::string(name);
    };
    need(features.avx2, "AVX2");
    need(features.fma, "FMA");
    need(features.bmi1, "BMI1");
    need(features.bmi2, "BMI2");
    need(features.lzcnt, "LZCNT");
    need(features.f16c, "F16C");
    need(features.os_ymm, "OS YMM state");
    if (missing.empty()) return {};
    return "the CPU lacks " + missing + " of the qualified ISA " + kQualifiedIsa;
}

/// The Embree API and device a baker and its running jobs share, and the count of the Embree
/// objects they hold.
struct EmbreeBaker::Core {
    const EmbreeApi* api = nullptr;
    RTCDevice device = nullptr;
    std::atomic<std::int64_t> live_objects{0};

    Core() = default;
    Core(const Core&) = delete;
    Core& operator=(const Core&) = delete;
    ~Core() {
        if (device) api->releaseDevice(device);
    }
};

namespace {

std::string VersionText(long version) {
    return std::to_string(version / 10000) + "." + std::to_string(version / 100 % 100) + "." +
           std::to_string(version % 100);
}

}  // namespace

EmbreeBaker::EmbreeBaker(BakerConfig config) : config_(std::move(config)), core_(std::make_shared<Core>()) {
    caps_.usages = {MeshMapUsage::AO, MeshMapUsage::Normal, MeshMapUsage::WorldSpaceNormal, MeshMapUsage::Position,
                    MeshMapUsage::ID, MeshMapUsage::Thickness, MeshMapUsage::Height, MeshMapUsage::Opacity};
    caps_.max_output_size_log2 = kMaxOutputSizeLog2;
    caps_.determinism_class = "repeatable-on-one-build-and-cpu-isa";
    caps_.isa = kQualifiedIsa;
    caps_.parity_status = "pending-evidence";
    caps_.parity_owner_task = "phase3.4_baker-ao";
    caps_.parity_owner_tasks = {{MeshMapUsage::AO, "phase3.4_baker-ao"},
                                {MeshMapUsage::Normal, "phase3.2_baker-normal"}};
    for (MeshMapUsage usage : {MeshMapUsage::WorldSpaceNormal, MeshMapUsage::Position, MeshMapUsage::ID,
                               MeshMapUsage::Thickness, MeshMapUsage::Height, MeshMapUsage::Opacity}) {
        caps_.parity_owner_tasks[usage] = UsageOwnerTask(usage);
    }

    const CpuFeatures features = config_.cpu_features ? *config_.cpu_features : DetectCpuFeatures();
    std::string reason = UnqualifiedIsaReason(features);
    if (!reason.empty()) {
        caps_.unqualified_reason = reason;
        return;
    }
    if (config_.embree_build_threads == 0) {
        caps_.unqualified_reason = "embree_build_threads must be at least 1";
        return;
    }
    core_->api = LoadEmbree(reason);
    if (!core_->api) {
        caps_.unqualified_reason = reason;
        return;
    }
    const EmbreeApi& api = *core_->api;
    const std::string device_config = "threads=" + std::to_string(config_.embree_build_threads) +
                                      ",isa=" + kQualifiedIsa + ",verbose=0";
    core_->device = api.newDevice(device_config.c_str());
    if (!core_->device) {
        caps_.unqualified_reason = "rtcNewDevice(\"" + device_config + "\") failed";
        return;
    }
    RTCDevice device = core_->device;
    const long version = static_cast<long>(api.getDeviceProperty(device, RTC_DEVICE_PROPERTY_VERSION));
    const long tasking =
        static_cast<long>(api.getDeviceProperty(device, RTC_DEVICE_PROPERTY_TASKING_SYSTEM));
    caps_.embree_version = VersionText(version);
    caps_.tasking_system = tasking == 0   ? "internal"
                           : tasking == 1 ? "TBB"
                           : tasking == 2 ? "PPL"
                                          : std::to_string(tasking);
    if (version != kPinnedEmbreeVersion) {
        caps_.unqualified_reason = "Embree " + caps_.embree_version + " is not the pinned " +
                                   VersionText(kPinnedEmbreeVersion);
    } else if (tasking != kPinnedEmbreeTasking) {
        caps_.unqualified_reason = "Embree's tasking system " + caps_.tasking_system +
                                   " is not the pinned package's (TBB)";
    } else if (api.getDeviceProperty(device, RTC_DEVICE_PROPERTY_BACKFACE_CULLING_ENABLED) != 0) {
        // Culling would hide the back-face hits this baker must count.
        caps_.unqualified_reason = "the Embree build culls back faces";
    } else if (api.getDeviceProperty(device, RTC_DEVICE_PROPERTY_TRIANGLE_GEOMETRY_SUPPORTED) == 0) {
        caps_.unqualified_reason = "the Embree build has no triangle geometry";
    } else if (api.getDeviceProperty(device, RTC_DEVICE_PROPERTY_FILTER_FUNCTION_SUPPORTED) == 0) {
        // Name matching and IgnoreBackface reject hits in a filter function.
        caps_.unqualified_reason = "the Embree build has no filter functions";
    } else if (config_.embree_build_threads != kQualifiedEmbreeBuildThreads) {
        // Decision 302 qualifies the serial BVH build only (decision 306).
        caps_.unqualified_reason = "embree_build_threads " + std::to_string(config_.embree_build_threads) +
                                   " is not the qualified serial BVH build (1 thread, decision 302)";
        caps_.diagnostic_build_threads = true;
    } else {
        caps_.qualified = true;
    }
}

EmbreeBaker::~EmbreeBaker() = default;

std::int64_t EmbreeBaker::live_embree_objects() const { return core_->live_objects.load(); }

// ── Request validation ───────────────────────────────────────────────────────────────────────

namespace {

bool Finite(Float3 v) { return std::isfinite(v.x) && std::isfinite(v.y) && std::isfinite(v.z); }
bool Finite(mesh::Float3 v) { return std::isfinite(v.x) && std::isfinite(v.y) && std::isfinite(v.z); }

bool HasUsage(const BakeRequest& request, MeshMapUsage usage) {
    return std::find(request.usages.begin(), request.usages.end(), usage) != request.usages.end();
}

void ValidateTangents(const BakeMesh& mesh) {
    if (mesh.corner_tangents.empty()) return;
    if (mesh.corner_tangents.size() != mesh.indices.size()) {
        throw ValueError("Normal needs one tangent per triangle corner");
    }
    for (const auto& t : mesh.corner_tangents) {
        if (!std::isfinite(t[0]) || !std::isfinite(t[1]) || !std::isfinite(t[2]) ||
            (t[0] == 0.0f && t[1] == 0.0f && t[2] == 0.0f) ||
            (t[3] != 1.0f && t[3] != -1.0f)) {
            throw ValueError("Normal tangents need finite nonzero xyz and sign +1 or -1");
        }
    }
}

void ValidateMesh(const BakeMesh& mesh, bool needs_uvs) {
    const std::string what = "mesh '" + mesh.name + "'";
    const std::size_t count = mesh.positions.size();
    if (count == 0 || mesh.indices.empty() || mesh.indices.size() % 3 != 0) {
        throw ValueError(what + " needs vertices and a multiple of three indices");
    }
    if (mesh.normals.size() != count) throw ValueError(what + " needs one normal per vertex");
    if (needs_uvs && mesh.uvs.size() != count) throw ValueError(what + " needs one UV per vertex");
    for (std::size_t i = 0; i < count; ++i) {
        const Float3 n = mesh.normals[i];
        if (!Finite(mesh.positions[i]) || !Finite(n) || n.x * n.x + n.y * n.y + n.z * n.z == 0.0f) {
            throw ValueError(what + " vertex " + std::to_string(i) +
                             " has a non-finite position or a zero normal");
        }
        if (needs_uvs && !(std::isfinite(mesh.uvs[i].x) && std::isfinite(mesh.uvs[i].y))) {
            throw ValueError(what + " vertex " + std::to_string(i) + " has a non-finite UV");
        }
    }
    for (std::uint32_t index : mesh.indices) {
        if (index >= count) throw ValueError(what + " has an index out of range");
    }
}

void ValidateCage(const BakeMesh& cage, const BakeMesh& low) {
    const std::string what = "cage '" + cage.name + "' of low part '" + low.name + "'";
    if (cage.positions.size() != low.positions.size() || cage.indices != low.indices) {
        throw ValueError(what + " needs the low part's vertex count and indices");
    }
    for (std::size_t i = 0; i < cage.positions.size(); ++i) {
        if (!Finite(cage.positions[i])) {
            throw ValueError(what + " vertex " + std::to_string(i) + " has a non-finite position");
        }
    }
}

bool StripSuffix(std::string& name, const std::string& suffix) {
    if (suffix.empty() || name.size() < suffix.size() ||
        name.compare(name.size() - suffix.size(), suffix.size(), suffix) != 0) {
        return false;
    }
    name.resize(name.size() - suffix.size());
    return true;
}

bool NonNegative(float v) { return std::isfinite(v) && v >= 0.0f; }

/// Checks `request` before any work and returns its effective distances (decision 311).
DistanceRecord ValidateRequest(const Capabilities& caps, const BakeRequest& request) {
    const bool has_ao = HasUsage(request, MeshMapUsage::AO);
    const bool has_normal = HasUsage(request, MeshMapUsage::Normal);
    if (request.usages.empty()) throw ValueError("the request enables no usage");
    for (MeshMapUsage usage : request.usages) {
        if (std::find(caps.usages.begin(), caps.usages.end(), usage) == caps.usages.end()) {
            throw CapabilityError(std::string("the CPU baker does not bake ") + UsageName(usage) +
                                  " (owned by " + UsageOwnerTask(usage) + ")");
        }
    }
    if (HasUsage(request, MeshMapUsage::WorldSpaceNormal)) ValidateWorldSpaceNormal(request);
    if (HasUsage(request, MeshMapUsage::Position)) ValidatePosition(request);
    if (HasUsage(request, MeshMapUsage::ID)) ValidateId(request);
    if (HasUsage(request, MeshMapUsage::Thickness)) ValidateThickness(request);
    if (HasUsage(request, MeshMapUsage::Height)) ValidateHeight(request);
    if (HasUsage(request, MeshMapUsage::Opacity)) ValidateOpacity(request);
    for (std::uint32_t log2 : request.output_size_log2) {
        if (log2 > caps.max_output_size_log2) {
            throw CapabilityError("OutputSize 2^" + std::to_string(log2) + " exceeds 2^" +
                                  std::to_string(caps.max_output_size_log2));
        }
    }
    if (request.common.apply_diffusion) {
        throw NotYetSupported(
            "ApplyDiffusion: the diffusion of the dilated texels is not established; one fixture baked "
            "with diffusion on and off settles it (owner phase3.5_embree-bakers, decisions 311 and 323)");
    }
    const DetailSettings& detail = request.detail;
    if (detail.cage_mode == CageMode::Automatic) {
        throw CapabilityError(
            "release gap: CageMode Automatic is not established against Painter "
            "(docs/architecture/06-baking.md section 3; capability manifest substance_painter.baking.bake_async "
            "cage-mode:automatic; owner phase3.5_embree-bakers, decision 323)");
    }
    if (!NonNegative(detail.max_height) || !NonNegative(detail.max_depth)) {
        throw ValueError("max_height and max_depth must be finite and >= 0");
    }
    const AoSettings& ao = request.ao;
    if (has_ao && (!NonNegative(ao.min_distance) || !std::isfinite(ao.max_distance) ||
        !(ao.min_distance < ao.max_distance))) {
        throw ValueError("AO distances need 0 <= min_distance < max_distance, finite");
    }
    // In mesh units: absolute distances over the unit scale, relative ones times the box size.
    const DistanceRecord distances = EffectiveDistances(request);
    if (detail.cage_mode == CageMode::DistanceBased && !(distances.max_height + distances.max_depth > 0.0f)) {
        throw ValueError("the distance-based cage needs max_height + max_depth > 0 (in mesh units)");
    }
    if (has_ao && !(distances.ao_min_distance < distances.ao_max_distance)) {
        throw ValueError("AO distances need min_distance < max_distance in mesh units");
    }
    const std::uint32_t k = detail.subsampling;
    if (k != 1 && k != 2 && k != 4 && k != 8) throw ValueError("subsampling must be 1, 2, 4 or 8");
    if (has_ao && (ao.secondary_rays == 0 || static_cast<std::uint64_t>(ao.secondary_rays) * k * k > 65535)) {
        throw ValueError("secondary_rays must be >= 1 and secondary_rays x subsampling^2 <= 65535");
    }
    if (has_normal) {
        if (k != 1) throw NotYetSupported("Normal SubSampling > 1 has no established resolve rule (phase3.2_baker-normal)");
        if (request.common.dilation_width != 0) {
            throw NotYetSupported("Normal DilationWidth > 0 has no established padding rule (phase3.2_baker-normal)");
        }
        if (request.normal.tangent_space != core::TangentSpace::PerVertex &&
            request.normal.tangent_space != core::TangentSpace::PerFragment) {
            throw ValueError("invalid Normal tangent space");
        }
        if (request.normal.format != core::NormalMapFormat::OpenGL &&
            request.normal.format != core::NormalMapFormat::DirectX) {
            throw ValueError("invalid Normal map format");
        }
    }
    if (request.low.empty()) throw ValueError("the request has no low mesh part");
    for (const BakeMesh* low : request.low) {
        if (!low) throw ValueError("the request has a null low mesh part");
        ValidateMesh(*low, true);
        if (has_normal) {
            if (!low->normal_frame_supported) {
                throw NotYetSupported("Normal with a nonidentity object transform is not established (phase3.2_baker-normal)");
            }
            ValidateTangents(*low);
        }
    }
    if (detail.low_as_high) {
        if (!request.high.empty()) throw ValueError("LowAsHigh bakes the low parts onto themselves: no high mesh");
    } else {
        if (request.high.empty()) throw ValueError("the request has no high mesh and LowAsHigh is off");
        for (const BakeMesh* high : request.high) {
            if (!high) throw ValueError("the request has a null high mesh");
            ValidateMesh(*high, false);
        }
    }
    if (detail.filter_method == FilterMethod::ByMeshName && !detail.low_as_high) {
        // A name that is only a suffix pairs with nothing a documented rule settles (decision 306).
        const auto refuse_empty = [](const std::string& name, std::string base) {
            if (base.empty()) {
                throw NotYetSupported("matching mesh '" + name +
                                      "' by name: the name is only a suffix (phase3.1_baker-request-model item 2.4)");
            }
        };
        for (const BakeMesh* low : request.low) {
            std::string base = low->name;
            StripSuffix(base, detail.low_suffix);
            refuse_empty(low->name, base);
        }
        for (const BakeMesh* high : request.high) {
            std::string base = high->name;
            StripSuffix(base, detail.ignore_backface_suffix);
            StripSuffix(base, detail.high_suffix);
            refuse_empty(high->name, base);
        }
    }
    if (detail.cage_mode == CageMode::CustomFile) {
        if (request.cage.size() != request.low.size()) {
            throw ValueError("CageMode CustomFile needs one cage per low part (CageParts builds them from the cage file)");
        }
        for (std::size_t i = 0; i < request.cage.size(); ++i) {
            if (!request.cage[i]) throw ValueError("the request has a null cage");
            ValidateCage(*request.cage[i], *request.low[i]);
        }
    } else if (!request.cage.empty()) {
        throw ValueError("cage meshes need CageMode CustomFile");
    }
    const std::size_t texels = (std::size_t{1} << request.output_size_log2[0]) << request.output_size_log2[1];
    if (!request.hidden_mask.empty() && request.hidden_mask.size() != texels) {
        throw ValueError("the hidden mask needs one byte per texel");
    }
    return distances;
}

// ── The job's own copy of the request ────────────────────────────────────────────────────────

struct JobInputs {
    /// Its distances are the effective mesh-unit distances; its mesh pointers point into the
    /// vectors below.
    BakeRequest request;
    DistanceRecord distances;
    std::vector<BakeMesh> low;
    std::vector<BakeMesh> high;
    std::vector<BakeMesh> cage;
};

std::vector<BakeMesh> CopyMeshes(const std::vector<const BakeMesh*>& meshes) {
    std::vector<BakeMesh> copies;
    copies.reserve(meshes.size());
    for (const BakeMesh* mesh : meshes) copies.push_back(*mesh);
    return copies;
}

std::vector<const BakeMesh*> Pointers(const std::vector<BakeMesh>& meshes) {
    std::vector<const BakeMesh*> pointers;
    pointers.reserve(meshes.size());
    for (const BakeMesh& mesh : meshes) pointers.push_back(&mesh);
    return pointers;
}

std::shared_ptr<const JobInputs> CopyInputs(const BakeRequest& request, const DistanceRecord& distances) {
    auto inputs = std::make_shared<JobInputs>();
    inputs->request = request;
    inputs->distances = distances;
    inputs->request.detail.max_height = distances.max_height;
    inputs->request.detail.max_depth = distances.max_depth;
    inputs->request.ao.min_distance = distances.ao_min_distance;
    inputs->request.ao.max_distance = distances.ao_max_distance;
    inputs->low = CopyMeshes(request.low);
    if (HasUsage(request, MeshMapUsage::Normal)) {
        for (BakeMesh& low : inputs->low) {
            EnsureNormalTangents(low);
            ValidateTangents(low);
        }
    }
    inputs->high = CopyMeshes(request.high);
    inputs->cage = CopyMeshes(request.cage);
    inputs->request.low = Pointers(inputs->low);
    inputs->request.high = Pointers(inputs->high);
    inputs->request.cage = Pointers(inputs->cage);
    return inputs;
}

// ── Geometry helpers (double precision, fixed operation order) ────────────────────────────────

Vec3d D(Float3 v) { return {v.x, v.y, v.z}; }
Vec3d Add(Vec3d a, Vec3d b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
Vec3d Sub(Vec3d a, Vec3d b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
Vec3d Scale(Vec3d a, double s) { return {a.x * s, a.y * s, a.z * s}; }
double Dot(Vec3d a, Vec3d b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
Vec3d Cross(Vec3d a, Vec3d b) {
    return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x};
}
Vec3d Blend(Vec3d a, Vec3d b, Vec3d c, double wa, double wb, double wc) {
    return Add(Add(Scale(a, wa), Scale(b, wb)), Scale(c, wc));
}
bool Normalize(Vec3d& v) {
    const double length = std::sqrt(Dot(v, v));
    if (!(length > 0.0)) return false;
    v = Scale(v, 1.0 / length);
    return true;
}

/// Front-face normal (unnormalised) of triangle `tri`.
Vec3d FaceNormal(const BakeMesh& mesh, std::uint32_t tri) {
    const Vec3d p0 = D(mesh.positions[mesh.indices[3 * tri]]);
    const Vec3d p1 = D(mesh.positions[mesh.indices[3 * tri + 1]]);
    const Vec3d p2 = D(mesh.positions[mesh.indices[3 * tri + 2]]);
    return Cross(Sub(p1, p0), Sub(p2, p0));
}

double Edge(Float2 a, Float2 b, double px, double py) {
    return (static_cast<double>(b.x) - a.x) * (py - a.y) - (static_cast<double>(b.y) - a.y) * (px - a.x);
}

struct UvWeights {
    double w0 = 0.0, w1 = 0.0, w2 = 0.0;
};

/// Barycentric weights of the UV point (px, py) in triangle `tri`; false when it lies outside
/// (edges included) or the UV triangle is degenerate. Either UV winding is accepted.
bool UvBarycentric(const BakeMesh& mesh, std::uint32_t tri, double px, double py, UvWeights& out) {
    const Float2 a = mesh.uvs[mesh.indices[3 * tri]];
    const Float2 b = mesh.uvs[mesh.indices[3 * tri + 1]];
    const Float2 c = mesh.uvs[mesh.indices[3 * tri + 2]];
    const double area = Edge(a, b, c.x, c.y);
    if (area == 0.0) return false;
    const double e0 = Edge(b, c, px, py) / area;
    const double e1 = Edge(c, a, px, py) / area;
    const double e2 = Edge(a, b, px, py) / area;
    if (e0 < 0.0 || e1 < 0.0 || e2 < 0.0) return false;
    out = {e0, e1, e2};
    return true;
}

Vec3d Corner(const BakeMesh& mesh, std::uint32_t tri, int k) {
    return D(mesh.positions[mesh.indices[3 * tri + k]]);
}
Vec3d CornerNormal(const BakeMesh& mesh, std::uint32_t tri, int k) {
    return D(mesh.normals[mesh.indices[3 * tri + k]]);
}
Vec3d BlendCorners(const BakeMesh& mesh, std::uint32_t tri, const UvWeights& w) {
    return Blend(Corner(mesh, tri, 0), Corner(mesh, tri, 1), Corner(mesh, tri, 2), w.w0, w.w1, w.w2);
}
Vec3d BlendNormals(const BakeMesh& mesh, std::uint32_t tri, const UvWeights& w) {
    return Blend(CornerNormal(mesh, tri, 0), CornerNormal(mesh, tri, 1), CornerNormal(mesh, tri, 2),
                 w.w0, w.w1, w.w2);
}

/// Sets the SSE floating-point state the bake runs under (all exceptions masked, round to
/// nearest, flush-to-zero and denormals-are-zero off) and restores the caller's on exit, so the
/// BVH build and every casting thread compute alike.
class FixedFpState {
public:
    FixedFpState() : saved_(_mm_getcsr()) { _mm_setcsr(0x1F80u); }
    ~FixedFpState() { _mm_setcsr(saved_); }
    FixedFpState(const FixedFpState&) = delete;
    FixedFpState& operator=(const FixedFpState&) = delete;

private:
    unsigned saved_;
};

// ── Texel candidates ─────────────────────────────────────────────────────────────────────────

/// The low triangles whose UV bounding box, grown by one texel, meets each texel: a superset of
/// the triangles that can contain any of its sub-samples. Built serially in (part, triangle)
/// order, so each texel's list is ascending in the global triangle index and the first triangle
/// that contains a sub-sample is the lowest one.
struct TexelCandidates {
    std::vector<std::uint32_t> part_first;  // global index of each part's first triangle
    std::vector<std::uint32_t> offsets;     // per texel, into `triangles`
    std::vector<std::uint32_t> triangles;   // global triangle indices
};

TexelCandidates BuildCandidates(const std::vector<const BakeMesh*>& low, std::uint32_t width,
                                std::uint32_t height) {
    TexelCandidates out;
    struct Range {
        std::int64_t x0, x1, y0, y1;
    };
    std::vector<Range> ranges;
    std::uint32_t total = 0;
    for (const BakeMesh* part : low) {
        out.part_first.push_back(total);
        const auto triangles = static_cast<std::uint32_t>(part->indices.size() / 3);
        for (std::uint32_t tri = 0; tri < triangles; ++tri) {
            double u_min = 1e300, u_max = -1e300, v_min = 1e300, v_max = -1e300;
            for (int k = 0; k < 3; ++k) {
                const Float2 uv = part->uvs[part->indices[3 * tri + k]];
                u_min = std::min(u_min, static_cast<double>(uv.x));
                u_max = std::max(u_max, static_cast<double>(uv.x));
                v_min = std::min(v_min, static_cast<double>(uv.y));
                v_max = std::max(v_max, static_cast<double>(uv.y));
            }
            // Texel x spans u in [x / W, (x + 1) / W]; texel y spans v in [1 - (y + 1) / H, 1 - y / H].
            const auto clamp_index = [](double value, std::uint32_t size) {
                return static_cast<std::int64_t>(std::clamp(value, 0.0, static_cast<double>(size - 1)));
            };
            const auto lo = [](double value) { return std::floor(value) - 1.0; };
            const auto hi = [](double value) { return std::floor(value) + 1.0; };
            Range range{clamp_index(lo(u_min * width), width), clamp_index(hi(u_max * width), width),
                        clamp_index(lo((1.0 - v_max) * height), height),
                        clamp_index(hi((1.0 - v_min) * height), height)};
            if (u_max < 0.0 || u_min > 1.0 || v_max < 0.0 || v_min > 1.0) range = {1, 0, 1, 0};
            ranges.push_back(range);
        }
        total += triangles;
    }
    const std::size_t texels = static_cast<std::size_t>(width) * height;
    out.offsets.assign(texels + 1, 0);
    for (const Range& r : ranges) {
        for (std::int64_t y = r.y0; y <= r.y1; ++y) {
            for (std::int64_t x = r.x0; x <= r.x1; ++x) ++out.offsets[static_cast<std::size_t>(y) * width + x + 1];
        }
    }
    for (std::size_t i = 0; i < texels; ++i) out.offsets[i + 1] += out.offsets[i];
    out.triangles.resize(out.offsets[texels]);
    std::vector<std::uint32_t> fill(out.offsets.begin(), out.offsets.end() - 1);
    for (std::uint32_t tri = 0; tri < ranges.size(); ++tri) {
        const Range& r = ranges[tri];
        for (std::int64_t y = r.y0; y <= r.y1; ++y) {
            for (std::int64_t x = r.x0; x <= r.x1; ++x) {
                out.triangles[fill[static_cast<std::size_t>(y) * width + x]++] = tri;
            }
        }
    }
    return out;
}

// ── Name matching (decision 306) ─────────────────────────────────────────────────────────────

/// Which high meshes each low part's primary rays may hit, and which high meshes' back faces
/// they pass through.
struct Matching {
    std::vector<std::vector<std::uint8_t>> allowed;  // [part][high]
    std::vector<std::uint8_t> part_filtered;         // the part's rays need the filter
    std::vector<std::uint8_t> ignore_back;           // [high]
    bool any_filter = false;
};

Matching MatchMeshes(const BakeRequest& request, const std::vector<const BakeMesh*>& high) {
    const DetailSettings& detail = request.detail;
    const bool by_name = detail.filter_method == FilterMethod::ByMeshName;
    Matching m;
    std::vector<std::string> high_base(high.size());
    m.ignore_back.assign(high.size(), detail.ignore_backface ? 1 : 0);
    for (std::size_t h = 0; h < high.size(); ++h) {
        high_base[h] = high[h]->name;
        if (by_name) {
            if (StripSuffix(high_base[h], detail.ignore_backface_suffix)) m.ignore_back[h] = 1;
            StripSuffix(high_base[h], detail.high_suffix);
        }
    }
    const bool any_ignore = std::find(m.ignore_back.begin(), m.ignore_back.end(), 1) != m.ignore_back.end();
    for (std::size_t p = 0; p < request.low.size(); ++p) {
        std::vector<std::uint8_t> allowed(high.size(), 1);
        if (by_name) {
            if (detail.low_as_high) {
                // Each part is its own high mesh.
                for (std::size_t h = 0; h < high.size(); ++h) allowed[h] = h == p ? 1 : 0;
            } else {
                std::string base = request.low[p]->name;
                StripSuffix(base, detail.low_suffix);
                for (std::size_t h = 0; h < high.size(); ++h) allowed[h] = high_base[h] == base ? 1 : 0;
            }
        }
        const bool all = std::find(allowed.begin(), allowed.end(), 0) == allowed.end();
        m.part_filtered.push_back(!all || any_ignore ? 1 : 0);
        m.any_filter = m.any_filter || m.part_filtered.back();
        m.allowed.push_back(std::move(allowed));
    }
    return m;
}

// ── Embree scene (RAII from the first acquisition) ───────────────────────────────────────────

struct SceneRelease {
    const EmbreeApi* api;
    std::atomic<std::int64_t>* live;
    void operator()(std::remove_pointer_t<RTCScene>* scene) const noexcept {
        api->releaseScene(scene);
        live->fetch_sub(1);
    }
};
struct GeometryRelease {
    const EmbreeApi* api;
    std::atomic<std::int64_t>* live;
    void operator()(std::remove_pointer_t<RTCGeometry>* geometry) const noexcept {
        api->releaseGeometry(geometry);
        live->fetch_sub(1);
    }
};
using ScenePtr = std::unique_ptr<std::remove_pointer_t<RTCScene>, SceneRelease>;
using GeometryPtr = std::unique_ptr<std::remove_pointer_t<RTCGeometry>, GeometryRelease>;

class Scene {
public:
    /// Every object acquired is owned by a handle as soon as it exists, so a failure at any step
    /// (including an injected one) releases everything acquired so far.
    Scene(EmbreeBaker::Core& core, const std::vector<const BakeMesh*>& meshes, bool filter,
          const FaultInjection& faults)
        : scene_(nullptr, SceneRelease{core.api, &core.live_objects}) {
        const EmbreeApi& api = *core.api;
        std::uint32_t acquisition = 0;
        const auto injected = [&] {
            return faults.embree_acquisition_failure && *faults.embree_acquisition_failure == acquisition++;
        };
        RTCScene scene = injected() ? nullptr : api.newScene(core.device);
        if (!scene) throw CapabilityError("rtcNewScene failed");
        core.live_objects.fetch_add(1);
        scene_.reset(scene);
        api.setSceneFlags(scene, filter ? static_cast<RTCSceneFlags>(RTC_SCENE_FLAG_ROBUST |
                                                                     RTC_SCENE_FLAG_FILTER_FUNCTION_IN_ARGUMENTS)
                                        : RTC_SCENE_FLAG_ROBUST);
        api.setSceneBuildQuality(scene, RTC_BUILD_QUALITY_MEDIUM);
        for (std::size_t m = 0; m < meshes.size(); ++m) {
            const BakeMesh& mesh = *meshes[m];
            RTCGeometry raw = injected() ? nullptr : api.newGeometry(core.device, RTC_GEOMETRY_TYPE_TRIANGLE);
            if (!raw) throw CapabilityError("rtcNewGeometry failed for mesh '" + mesh.name + "'");
            core.live_objects.fetch_add(1);
            const GeometryPtr geometry(raw, GeometryRelease{core.api, &core.live_objects});
            auto* vertices = injected() ? nullptr
                                        : static_cast<float*>(api.setNewGeometryBuffer(
                                              raw, RTC_BUFFER_TYPE_VERTEX, 0, RTC_FORMAT_FLOAT3,
                                              3 * sizeof(float), mesh.positions.size()));
            if (!vertices) throw CapabilityError("rtcSetNewGeometryBuffer (vertices) failed for mesh '" + mesh.name + "'");
            auto* indices = injected() ? nullptr
                                       : static_cast<unsigned*>(api.setNewGeometryBuffer(
                                             raw, RTC_BUFFER_TYPE_INDEX, 0, RTC_FORMAT_UINT3,
                                             3 * sizeof(unsigned), mesh.indices.size() / 3));
            if (!indices) throw CapabilityError("rtcSetNewGeometryBuffer (indices) failed for mesh '" + mesh.name + "'");
            for (std::size_t i = 0; i < mesh.positions.size(); ++i) {
                vertices[3 * i] = mesh.positions[i].x;
                vertices[3 * i + 1] = mesh.positions[i].y;
                vertices[3 * i + 2] = mesh.positions[i].z;
            }
            std::copy(mesh.indices.begin(), mesh.indices.end(), indices);
            api.commitGeometry(raw);
            api.attachGeometryByID(scene, raw, static_cast<unsigned>(m));  // the scene retains it
        }
        api.commitScene(scene);
    }
    RTCScene get() const { return scene_.get(); }

private:
    ScenePtr scene_;
};

RTCRayHit MakeRay(Vec3d origin, Vec3d direction, float tnear, float tfar) {
    RTCRayHit rh{};
    rh.ray.org_x = static_cast<float>(origin.x);
    rh.ray.org_y = static_cast<float>(origin.y);
    rh.ray.org_z = static_cast<float>(origin.z);
    rh.ray.dir_x = static_cast<float>(direction.x);
    rh.ray.dir_y = static_cast<float>(direction.y);
    rh.ray.dir_z = static_cast<float>(direction.z);
    rh.ray.tnear = tnear;
    rh.ray.tfar = tfar;
    rh.ray.mask = 0xFFFFFFFFu;
    rh.hit.geomID = RTC_INVALID_GEOMETRY_ID;
    rh.hit.primID = RTC_INVALID_GEOMETRY_ID;
    rh.hit.instID[0] = RTC_INVALID_GEOMETRY_ID;
    return rh;
}

/// The ray query context of a filtered primary ray (Embree passes it back to the filter).
struct PrimaryQuery {
    RTCRayQueryContext context;  // first member: the filter casts back from it
    const std::uint8_t* allowed = nullptr;
    const std::uint8_t* ignore_back = nullptr;
    const std::vector<const BakeMesh*>* high = nullptr;
};

/// Rejects hits on high meshes the low part does not match and, where `IgnoreBackface` or the
/// `_ignorebf` suffix applies, back-face hits (our winding, not Embree's `Ng`).
void PrimaryFilter(const RTCFilterFunctionNArguments* args) {
    const auto* query = reinterpret_cast<const PrimaryQuery*>(args->context);
    for (unsigned i = 0; i < args->N; ++i) {
        if (args->valid[i] != -1) continue;
        const unsigned geom = RTCHitN_geomID(args->hit, args->N, i);
        if (!query->allowed[geom]) {
            args->valid[i] = 0;
            continue;
        }
        if (query->ignore_back[geom]) {
            const unsigned prim = RTCHitN_primID(args->hit, args->N, i);
            const Vec3d dir{RTCRayN_dir_x(args->ray, args->N, i), RTCRayN_dir_y(args->ray, args->N, i),
                            RTCRayN_dir_z(args->ray, args->N, i)};
            if (Dot(dir, FaceNormal(*(*query->high)[geom], prim)) >= 0.0) args->valid[i] = 0;
        }
    }
}

// ── The bake ─────────────────────────────────────────────────────────────────────────────────

struct TileCounts {
    TexelClassCounts texels;
    SubsampleCounts subsamples;
    RayClassCounts rays;
};

struct Context {
    const EmbreeApi& api;
    RTCScene scene;
    const BakeRequest& request;
    const std::vector<const BakeMesh*>& high;
    const TexelCandidates& candidates;
    const Matching& matching;
    BakeResult& result;
};

std::string TexelText(std::uint32_t x, std::uint32_t y) {
    return "texel (" + std::to_string(x) + ", " + std::to_string(y) + ")";
}

std::uint16_t EncodeNormal(float x) {
    const float encoded = std::clamp(x * 0.5f + 0.5f, 0.0f, 1.0f);
    return static_cast<std::uint16_t>(std::floor(encoded * 65535.0f + 0.5f));
}

Float3 TangentNormal(const BakeMesh& low, std::uint32_t tri, const UvWeights& w,
                     core::TangentSpace mode, Vec3d high_normal) {
    const mesh::Frame frame = InterpolateBakeFrame(
        low, tri, {static_cast<float>(w.w0), static_cast<float>(w.w1), static_cast<float>(w.w2)}, mode);
    const float determinant = mesh::v3::Dot(frame.t, mesh::v3::Cross(frame.b, frame.n));
    if (!Finite(frame.t) || !Finite(frame.b) || !Finite(frame.n) ||
        !std::isfinite(determinant) || determinant == 0.0f) {
        throw ValueError("Normal has a singular or non-finite interpolated tangent frame");
    }
    const mesh::Float3 normal = mesh::ToTangentSpace(
        frame, {static_cast<float>(high_normal.x), static_cast<float>(high_normal.y),
                static_cast<float>(high_normal.z)});
    if (!Finite(normal) || !(mesh::v3::Dot(normal, normal) > 0.0f)) {
        throw ValueError("Normal tangent transform produced a zero or non-finite normal");
    }
    return {normal.x, normal.y, normal.z};
}

/// The first hit of a secondary ray from `origin` along `dir` in [tnear, tfar], classed as AO's rays
/// are (decision 302 §4) against the origin triangle (`origin_geom`, `origin_prim`): a Thickness ray.
SecondaryHit CastSecondary(const Context& ctx, const Vec3d& origin, const Vec3d& dir, float tnear, float tfar,
                           unsigned origin_geom, unsigned origin_prim) {
    RTCRayHit ray = MakeRay(origin, dir, tnear, tfar);
    ctx.api.intersect1(ctx.scene, &ray, nullptr);
    if (ray.hit.geomID == RTC_INVALID_GEOMETRY_ID) return {ThicknessRayClass::Escaped, 0.0f};
    ThicknessRayClass cls = ThicknessRayClass::FrontHit;
    if (ray.hit.geomID == origin_geom && ray.hit.primID == origin_prim) {
        cls = ThicknessRayClass::SelfHit;
    } else if (Dot(dir, FaceNormal(*ctx.high[ray.hit.geomID], ray.hit.primID)) >= 0.0) {
        cls = ThicknessRayClass::BackFaceHit;
    }
    return {cls, ray.ray.tfar};
}

void BakeTexel(const Context& ctx, std::uint32_t x, std::uint32_t y, TileCounts& counts) {
    BakeResult& out = ctx.result;
    const BakeRequest& request = ctx.request;
    const DetailSettings& detail = request.detail;
    const AoSettings& ao = request.ao;
    const std::size_t index = static_cast<std::size_t>(y) * out.width + x;
    const bool has_ao = !out.ao_raw.empty();
    const bool has_normal = !out.normal_raw.empty();
    const std::uint32_t k = detail.subsampling;
    const bool hidden = !request.hidden_mask.empty() && request.hidden_mask[index] != 0;
    const bool cage = detail.cage_mode == CageMode::CustomFile;
    const std::uint32_t first = ctx.candidates.offsets[index];
    const std::uint32_t last = ctx.candidates.offsets[index + 1];

    std::uint32_t covered = 0, hits = 0, back_hits = 0;
    std::uint64_t escaped = 0;
    std::uint32_t back_rays = 0, self_rays = 0;
    for (std::uint32_t j = 0; j < k; ++j) {
        for (std::uint32_t i = 0; i < k; ++i) {
            const std::uint32_t sub = j * k + i;
            const double u = (x + (i + 0.5) / k) / out.width;
            const double v = 1.0 - (y + (j + 0.5) / k) / out.height;
            // The lowest (part, triangle) that contains the sub-sample.
            std::uint32_t part = 0, tri = 0;
            UvWeights w;
            bool found = false;
            for (std::uint32_t c = first; c < last && !found; ++c) {
                const std::uint32_t global = ctx.candidates.triangles[c];
                part = static_cast<std::uint32_t>(
                    std::upper_bound(ctx.candidates.part_first.begin(), ctx.candidates.part_first.end(), global) -
                    ctx.candidates.part_first.begin() - 1);
                tri = global - ctx.candidates.part_first[part];
                found = UvBarycentric(*request.low[part], tri, u, v, w);
            }
            if (!found) continue;
            ++covered;
            if (hidden) continue;

            // The primary ray: distance-based from `max_height` above the low surface down to
            // `max_depth` below it, or from the custom cage through the low surface to
            // `max_depth` beyond it.
            const BakeMesh& low = *request.low[part];
            const Vec3d p = BlendCorners(low, tri, w);
            Vec3d origin, dir;
            float tfar = 0.0f;
            double surface_t = detail.max_height;  // the low point's distance along the ray
            if (cage) {
                origin = BlendCorners(*request.cage[part], tri, w);
                dir = Sub(p, origin);
                const double length = std::sqrt(Dot(dir, dir));
                surface_t = length;
                if (!Normalize(dir)) {
                    throw ValueError("the cage of low part '" + low.name + "' meets triangle " +
                                     std::to_string(tri) + " at " + TexelText(x, y));
                }
                tfar = static_cast<float>(length + detail.max_depth);
            } else {
                Vec3d n = BlendNormals(low, tri, w);
                if (!Normalize(n)) {
                    throw ValueError("the normals of low triangle " + std::to_string(tri) + " of '" + low.name +
                                     "' cancel at " + TexelText(x, y));
                }
                origin = Add(p, Scale(n, detail.max_height));
                dir = Scale(n, -1.0);
                tfar = detail.max_height + detail.max_depth;
            }
            RTCRayHit primary = MakeRay(origin, dir, 0.0f, tfar);
            if (ctx.matching.part_filtered[part]) {
                PrimaryQuery query;
                rtcInitRayQueryContext(&query.context);
                query.allowed = ctx.matching.allowed[part].data();
                query.ignore_back = ctx.matching.ignore_back.data();
                query.high = &ctx.high;
                RTCIntersectArguments args;
                rtcInitIntersectArguments(&args);
                args.flags = static_cast<RTCRayQueryFlags>(args.flags | RTC_RAY_QUERY_FLAG_INVOKE_ARGUMENT_FILTER);
                args.filter = PrimaryFilter;
                args.context = &query.context;
                ctx.api.intersect1(ctx.scene, &primary, &args);
            } else {
                ctx.api.intersect1(ctx.scene, &primary, nullptr);
            }
            if (primary.hit.geomID == RTC_INVALID_GEOMETRY_ID) {
                ++counts.subsamples.centre_miss;
                continue;
            }
            const unsigned origin_geom = primary.hit.geomID;
            const unsigned origin_prim = primary.hit.primID;
            const BakeMesh& hit_mesh = *ctx.high[origin_geom];
            if (Dot(dir, FaceNormal(hit_mesh, origin_prim)) >= 0.0) {
                ++back_hits;
                ++counts.subsamples.back_face_hit;
                continue;
            }
            ++hits;
            ++counts.subsamples.hit;

            // The high surface point (Embree's barycentrics: p = (1-u-v) p0 + u p1 + v p2).
            const UvWeights hw{1.0 - static_cast<double>(primary.hit.u) - primary.hit.v, primary.hit.u,
                               primary.hit.v};
            const Vec3d ph = BlendCorners(hit_mesh, origin_prim, hw);
            Vec3d nh = BlendNormals(hit_mesh, origin_prim, hw);
            if (!Normalize(nh)) {
                throw ValueError("the normals of high triangle " + std::to_string(origin_prim) + " of '" +
                                 hit_mesh.name + "' cancel at " + TexelText(x, y));
            }

            if (has_normal) {
                const Float3 normal = TangentNormal(low, tri, w, request.normal.tangent_space, nh);
                out.normal_raw[3 * index] = EncodeNormal(normal.x);
                const std::uint16_t green = EncodeNormal(normal.y);
                out.normal_raw[3 * index + 1] = request.normal.format == core::NormalMapFormat::DirectX
                    ? static_cast<std::uint16_t>(65535u - green) : green;
                out.normal_raw[3 * index + 2] = EncodeNormal(normal.z);
            }
            if (!out.world_normal.empty()) WriteWorldSpaceNormal(out, index, nh);
            if (!out.position.empty()) WritePosition(out, index, ph);
            if (!out.id_labels.empty()) WriteId(out, index, origin_geom);
            if (!out.opacity.empty()) WriteOpacity(out, index);
            if (!out.height_map.empty()) WriteHeight(out, index, surface_t - primary.ray.tfar);
            if (!out.thickness_ray_class.empty()) {
                CastThickness(out, index, ph, nh, [&](const Vec3d& o, const Vec3d& d, float tnear, float tfar_) {
                    return CastSecondary(ctx, o, d, tnear, tfar_, origin_geom, origin_prim);
                });
            }
            if (!has_ao) continue;
            // AO secondary rays, in sample order; one Hammersley set over the texel's sub-samples.
            const std::uint32_t texel_rays = ao.secondary_rays * k * k;
            for (std::uint32_t s = 0; s < ao.secondary_rays; ++s) {
                const Vec3d ray_dir = HemisphereDirection(
                    ao.distribution, TexelSample(index, sub * ao.secondary_rays + s, texel_rays), nh);
                RTCRayHit ray = MakeRay(ph, ray_dir, ao.min_distance, ao.max_distance);
                ctx.api.intersect1(ctx.scene, &ray, nullptr);
                if (ray.hit.geomID == RTC_INVALID_GEOMETRY_ID) {
                    ++escaped;
                    ++counts.rays.escaped;
                } else if (ray.hit.geomID == origin_geom && ray.hit.primID == origin_prim) {
                    ++self_rays;
                    ++counts.rays.self_hit;
                } else if (Dot(ray_dir, FaceNormal(*ctx.high[ray.hit.geomID], ray.hit.primID)) >= 0.0) {
                    ++back_rays;
                    ++counts.rays.back_face_hit;
                } else {
                    ++counts.rays.front_hit;
                }
            }
        }
    }
    counts.subsamples.covered += covered;
    out.coverage[index] = static_cast<std::uint8_t>(covered);
    TexelClass cls;
    if (covered == 0) {
        cls = TexelClass::Uncovered;
        ++counts.texels.uncovered;
    } else if (hidden) {
        cls = TexelClass::Hidden;
        ++counts.texels.hidden;
        counts.subsamples.hidden += covered;
    } else if (hits > 0) {
        cls = cage ? TexelClass::CageHit : TexelClass::StraightHit;
        ++(cage ? counts.texels.cage_hit : counts.texels.straight_hit);
        out.subsample_hits[index] = static_cast<std::uint8_t>(hits);
        if (has_ao) {
            const std::uint64_t rays = static_cast<std::uint64_t>(hits) * ao.secondary_rays;
            out.ao_raw[index] = static_cast<std::uint16_t>((escaped * 65535u + rays / 2) / rays);
            out.back_face_rays[index] = static_cast<std::uint16_t>(back_rays);
            out.self_hit_rays[index] = static_cast<std::uint16_t>(self_rays);
        }
    } else if (back_hits > 0) {
        cls = TexelClass::BackFaceHit;
        ++counts.texels.back_face_hit;
    } else {
        cls = TexelClass::CentreMiss;
        ++counts.texels.centre_miss;
    }
    out.texel_class[index] = static_cast<std::uint8_t>(cls);
}

void Add(TexelClassCounts& a, const TexelClassCounts& b) {
    a.uncovered += b.uncovered;
    a.straight_hit += b.straight_hit;
    a.back_face_hit += b.back_face_hit;
    a.centre_miss += b.centre_miss;
    a.cage_hit += b.cage_hit;
    a.hidden += b.hidden;
}

void Add(SubsampleCounts& a, const SubsampleCounts& b) {
    a.covered += b.covered;
    a.hit += b.hit;
    a.back_face_hit += b.back_face_hit;
    a.centre_miss += b.centre_miss;
    a.hidden += b.hidden;
}

void Add(RayClassCounts& a, const RayClassCounts& b) {
    a.escaped += b.escaped;
    a.front_hit += b.front_hit;
    a.back_face_hit += b.back_face_hit;
    a.self_hit += b.self_hit;
}

/// `DilationWidth`: `width` passes; each pass gives every `Uncovered` texel that has a valued
/// 8-neighbour the rounded mean of its valued neighbours of the previous pass (all of a pass is
/// read before any of it is written, so the order of the scan never matters). Valued texels are
/// the hit texels and those already dilated; texels of the used surface without a hit (centre
/// misses, back-face hits, hidden texels) are never written and never spread. RAW is untouched.
std::uint64_t Dilate(BakeResult& r, std::uint32_t width, const JobControl& control) {
    r.ao = r.ao_raw;
    const std::size_t texels = static_cast<std::size_t>(r.width) * r.height;
    std::vector<std::uint8_t> valued(texels, 0);
    for (std::size_t i = 0; i < texels; ++i) {
        const auto cls = static_cast<TexelClass>(r.texel_class[i]);
        valued[i] = cls == TexelClass::StraightHit || cls == TexelClass::CageHit;
    }
    std::uint64_t dilated = 0;
    std::vector<std::pair<std::size_t, std::uint16_t>> fresh;
    for (std::uint32_t pass = 0; pass < width && !control.stop_requested(); ++pass) {
        fresh.clear();
        for (std::uint32_t y = 0; y < r.height; ++y) {
            for (std::uint32_t x = 0; x < r.width; ++x) {
                const std::size_t i = static_cast<std::size_t>(y) * r.width + x;
                if (valued[i] || static_cast<TexelClass>(r.texel_class[i]) != TexelClass::Uncovered) continue;
                std::uint64_t sum = 0;
                std::uint32_t count = 0;
                for (int dy = -1; dy <= 1; ++dy) {
                    for (int dx = -1; dx <= 1; ++dx) {
                        const std::int64_t nx = static_cast<std::int64_t>(x) + dx;
                        const std::int64_t ny = static_cast<std::int64_t>(y) + dy;
                        if ((dx == 0 && dy == 0) || nx < 0 || ny < 0 || nx >= r.width || ny >= r.height) continue;
                        const std::size_t n = static_cast<std::size_t>(ny) * r.width + static_cast<std::size_t>(nx);
                        if (!valued[n]) continue;
                        sum += r.ao[n];
                        ++count;
                    }
                }
                if (count > 0) fresh.emplace_back(i, static_cast<std::uint16_t>((sum + count / 2) / count));
            }
        }
        if (fresh.empty()) break;
        for (const auto& [i, value] : fresh) {
            r.ao[i] = value;
            valued[i] = 1;
        }
        dilated += fresh.size();
    }
    return dilated;
}

/// Threads that are joined however their owner is left, so a failed spawn never meets a
/// joinable `std::thread` in a destructor (`std::terminate`).
class JoiningThreads {
public:
    JoiningThreads() = default;
    JoiningThreads(const JoiningThreads&) = delete;
    JoiningThreads& operator=(const JoiningThreads&) = delete;
    ~JoiningThreads() {
        for (std::thread& thread : threads_) {
            if (thread.joinable()) thread.join();
        }
    }
    void reserve(std::size_t count) { threads_.reserve(count); }
    template <typename Fn>
    void spawn(Fn&& fn) {
        threads_.emplace_back(std::forward<Fn>(fn));
    }

private:
    std::vector<std::thread> threads_;
};

BakeResult RunBake(EmbreeBaker::Core& core, const BakerConfig& config, const JobInputs& inputs,
                   JobControl& control) {
    const FixedFpState fp_state;
    const BakeRequest& request = inputs.request;
    const EmbreeApi& api = *core.api;
    const bool has_ao = HasUsage(request, MeshMapUsage::AO);
    const bool has_normal = HasUsage(request, MeshMapUsage::Normal);
    const bool has_id = HasUsage(request, MeshMapUsage::ID);

    BakeResult result;
    result.width = 1u << request.output_size_log2[0];
    result.height = 1u << request.output_size_log2[1];
    result.tile_size = kTileSize;
    result.rays_per_texel = has_ao ? request.ao.secondary_rays : 0;
    result.subsampling = request.detail.subsampling;
    result.dilation_width = request.common.dilation_width;
    result.distances = inputs.distances;
    const std::size_t texels = static_cast<std::size_t>(result.width) * result.height;
    if (has_ao) {
        result.ao_raw.assign(texels, 0);
        result.back_face_rays.assign(texels, 0);
        result.self_hit_rays.assign(texels, 0);
    }
    if (has_normal) {
        result.normal_raw.assign(3 * texels, 0);
        result.tangent_space = request.normal.tangent_space;
        result.normal_format = request.normal.format;
    }
    if (HasUsage(request, MeshMapUsage::WorldSpaceNormal)) PrepareWorldSpaceNormal(result);
    if (HasUsage(request, MeshMapUsage::Position)) PreparePosition(request, result);
    if (HasUsage(request, MeshMapUsage::Thickness)) PrepareThickness(request, result);
    if (HasUsage(request, MeshMapUsage::Height)) PrepareHeight(request, result);
    if (HasUsage(request, MeshMapUsage::Opacity)) PrepareOpacity(result);
    result.texel_class.assign(texels, 0);
    result.coverage.assign(texels, 0);
    result.subsample_hits.assign(texels, 0);

    const std::vector<const BakeMesh*> high = request.detail.low_as_high ? request.low : request.high;
    if (has_id) PrepareId(high, result);
    const Matching matching = MatchMeshes(request, high);
    const Scene scene(core, high, matching.any_filter, config.faults);
    if (api.getDeviceError(core.device) != RTC_ERROR_NONE) {
        throw CapabilityError(std::string("Embree failed to build the scene: ") +
                              api.getDeviceLastErrorMessage(core.device));
    }
    const TexelCandidates candidates = BuildCandidates(request.low, result.width, result.height);

    const std::uint32_t tiles_x = (result.width + kTileSize - 1) / kTileSize;
    const std::uint32_t tiles_y = (result.height + kTileSize - 1) / kTileSize;
    const std::uint32_t tile_count = tiles_x * tiles_y;
    control.set_total_tiles(tile_count);
    std::vector<TileCounts> tile_counts(tile_count);
    std::vector<std::exception_ptr> tile_errors(tile_count);
    const Context ctx{api, scene.get(), request, high, candidates, matching, result};

    std::uint32_t threads = request.threads;
    if (threads == 0) threads = std::max(1u, std::thread::hardware_concurrency());
    threads = std::min(threads, tile_count);
    result.threads_used = threads;
    // Embree keeps its error code per thread and device, so each worker reads its own.
    std::vector<RTCError> worker_errors(threads, RTC_ERROR_NONE);
    std::atomic<std::uint32_t> next{0};
    std::atomic<bool> abandon{false};  // a later worker could not be started
    const auto worker = [&](std::uint32_t worker_index) {
        const FixedFpState worker_fp_state;
        for (;;) {
            if (control.stop_requested() || abandon.load()) break;
            const std::uint32_t tile = next.fetch_add(1);
            if (tile >= tile_count) break;
            try {
                const std::uint32_t x0 = (tile % tiles_x) * kTileSize;
                const std::uint32_t y0 = (tile / tiles_x) * kTileSize;
                const std::uint32_t x1 = std::min(x0 + kTileSize, result.width);
                const std::uint32_t y1 = std::min(y0 + kTileSize, result.height);
                for (std::uint32_t y = y0; y < y1; ++y) {
                    for (std::uint32_t x = x0; x < x1; ++x) BakeTexel(ctx, x, y, tile_counts[tile]);
                }
            } catch (...) {
                tile_errors[tile] = std::current_exception();
            }
            control.tile_done();
            // The callback's errors take the tile's error path: nothing may escape a worker.
            try {
                if (config.on_tile_done) config.on_tile_done(tile);
            } catch (...) {
                if (!tile_errors[tile]) tile_errors[tile] = std::current_exception();
            }
        }
        worker_errors[worker_index] = api.getDeviceError(core.device);
    };
    if (threads == 1) {
        worker(0);
    } else {
        JoiningThreads pool;  // declared after everything the workers use: joined first
        pool.reserve(threads);
        try {
            for (std::uint32_t i = 0; i < threads; ++i) {
                if (config.faults.worker_spawn_failure && *config.faults.worker_spawn_failure == i) {
                    throw std::system_error(std::make_error_code(std::errc::resource_unavailable_try_again),
                                            "injected failure creating bake worker " + std::to_string(i));
                }
                pool.spawn([&worker, i] { worker(i); });
            }
        } catch (...) {
            abandon.store(true);
            throw;  // `pool` joins the started workers on the way out
        }
    }
    if (control.stop_requested()) return {};  // a cancelled job publishes nothing
    // The first failing tile in tile order, whatever thread met it first.
    for (const std::exception_ptr& error : tile_errors) {
        if (error) std::rethrow_exception(error);
    }
    for (RTCError error : worker_errors) {
        if (error != RTC_ERROR_NONE) {
            throw CapabilityError("Embree reported error " + std::to_string(error) + " while casting");
        }
    }
    for (const TileCounts& counts : tile_counts) {
        Add(result.texels, counts.texels);
        Add(result.subsamples, counts.subsamples);
        Add(result.rays, counts.rays);
    }
    if (HasUsage(request, MeshMapUsage::Thickness)) CountThickness(result);
    if (has_ao) result.dilated_texels = Dilate(result, request.common.dilation_width, control);
    if (has_normal) result.normal = result.normal_raw;
    return result;
}

}  // namespace

JobHandle EmbreeBaker::bake(const BakeRequest& request) {
    bool diagnostic = false;
    if (!caps_.qualified) {
        if (!(caps_.diagnostic_build_threads && config_.allow_unqualified_build_threads_diagnostic)) {
            throw CapabilityError("the CPU baker is not qualified on this configuration: " +
                                  caps_.unqualified_reason);
        }
        diagnostic = true;
    }
    // Tangent generation inherits the same floating-point state as the texel workers.
    std::optional<FixedFpState> fp_state;
    if (HasUsage(request, MeshMapUsage::Normal)) fp_state.emplace();
    const DistanceRecord distances = ValidateRequest(caps_, request);
    std::shared_ptr<const JobInputs> inputs = CopyInputs(request, distances);
    return JobHandle::Start([core = core_, config = config_, inputs, diagnostic](JobControl& control) {
        BakeResult result = RunBake(*core, config, *inputs, control);
        result.diagnostic_unqualified = diagnostic;
        return result;
    });
}

}  // namespace uzp::bake
