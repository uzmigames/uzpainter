#include "bake/embree_baker.h"

#include <cpuid.h>
#include <xmmintrin.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <exception>
#include <limits>
#include <thread>
#include <vector>

#include "bake/sampling.h"
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

namespace {

std::string VersionText(long version) {
    return std::to_string(version / 10000) + "." + std::to_string(version / 100 % 100) + "." +
           std::to_string(version % 100);
}

std::string UsageOwnerTask(MeshMapUsage usage) {
    switch (usage) {
        case MeshMapUsage::Normal: return "phase3.2_baker-normal";
        case MeshMapUsage::WorldSpaceNormal: return "phase3.4_baker-world-space-normal";
        case MeshMapUsage::ID: return "phase3.4_baker-id";
        case MeshMapUsage::AO: return "phase3.4_baker-ao";
        case MeshMapUsage::Curvature: return "phase3.4_baker-curvature";
        case MeshMapUsage::Position: return "phase3.4_baker-position";
        case MeshMapUsage::Thickness: return "phase3.4_baker-thickness";
        case MeshMapUsage::Height: return "phase3.4_baker-height";
        case MeshMapUsage::BentNormals: return "phase3.4_baker-bent-normals";
        case MeshMapUsage::Opacity: return "phase3.4_baker-opacity";
    }
    return "phase3.5_embree-bakers";
}

}  // namespace

EmbreeBaker::EmbreeBaker(BakerConfig config) : config_(config) {
    caps_.usages = {MeshMapUsage::AO};
    caps_.max_output_size_log2 = kMaxOutputSizeLog2;
    caps_.determinism_class = "repeatable-on-one-build-and-cpu-isa";
    caps_.isa = kQualifiedIsa;
    caps_.parity_status = "pending-evidence";
    caps_.parity_owner_task = "phase3.4_baker-ao";

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
    api_ = LoadEmbree(reason);
    if (!api_) {
        caps_.unqualified_reason = reason;
        return;
    }
    const std::string device_config = "threads=" + std::to_string(config_.embree_build_threads) +
                                      ",isa=" + kQualifiedIsa + ",verbose=0";
    device_ = api_->newDevice(device_config.c_str());
    if (!device_) {
        caps_.unqualified_reason = "rtcNewDevice(\"" + device_config + "\") failed";
        return;
    }
    const long version =
        static_cast<long>(api_->getDeviceProperty(device_, RTC_DEVICE_PROPERTY_VERSION));
    const long tasking =
        static_cast<long>(api_->getDeviceProperty(device_, RTC_DEVICE_PROPERTY_TASKING_SYSTEM));
    caps_.embree_version = VersionText(version);
    caps_.tasking_system = tasking == 0   ? "internal"
                           : tasking == 1 ? "TBB"
                           : tasking == 2 ? "PPL"
                                          : std::to_string(tasking);
    if (version != kPinnedEmbreeVersion) {
        caps_.unqualified_reason = "Embree " + caps_.embree_version + " is not the pinned " +
                                   VersionText(kPinnedEmbreeVersion);
    } else if (api_->getDeviceProperty(device_, RTC_DEVICE_PROPERTY_BACKFACE_CULLING_ENABLED) != 0) {
        // Culling would hide the back-face hits this baker must count.
        caps_.unqualified_reason = "the Embree build culls back faces";
    } else if (api_->getDeviceProperty(device_, RTC_DEVICE_PROPERTY_TRIANGLE_GEOMETRY_SUPPORTED) ==
               0) {
        caps_.unqualified_reason = "the Embree build has no triangle geometry";
    } else {
        caps_.qualified = true;
    }
}

EmbreeBaker::~EmbreeBaker() {
    if (device_) api_->releaseDevice(device_);
}

// ── Request validation ───────────────────────────────────────────────────────────────────────

namespace {

bool Finite(Float3 v) { return std::isfinite(v.x) && std::isfinite(v.y) && std::isfinite(v.z); }

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

bool NonNegative(float v) { return std::isfinite(v) && v >= 0.0f; }

void ValidateRequest(const Capabilities& caps, const BakeRequest& request) {
    if (request.usages.empty()) throw ValueError("the request enables no usage");
    for (MeshMapUsage usage : request.usages) {
        if (std::find(caps.usages.begin(), caps.usages.end(), usage) == caps.usages.end()) {
            throw CapabilityError(std::string("the CPU baker does not bake ") + UsageName(usage) +
                                  " (owned by " + UsageOwnerTask(usage) + ")");
        }
    }
    for (std::uint32_t log2 : request.output_size_log2) {
        if (log2 > caps.max_output_size_log2) {
            throw CapabilityError("OutputSize 2^" + std::to_string(log2) + " exceeds 2^" +
                                  std::to_string(caps.max_output_size_log2));
        }
    }
    const DetailSettings& detail = request.detail;
    if (detail.cage_mode == CageMode::Automatic) {
        throw CapabilityError(
            "release gap: CageMode Automatic is not established against Painter "
            "(docs/architecture/06-baking.md section 3; phase3.1_baker-request-model item 2.5)");
    }
    if (detail.cage_mode == CageMode::CustomFile) {
        throw NotYetSupported("CageMode CustomFile (phase3.1_baker-request-model item 2.5)");
    }
    if (!NonNegative(detail.max_height) || !NonNegative(detail.max_depth) ||
        !(detail.max_height + detail.max_depth > 0.0f)) {
        throw ValueError("max_height and max_depth must be finite, >= 0 and not both 0");
    }
    const AoSettings& ao = request.ao;
    if (ao.secondary_rays == 0 || ao.secondary_rays > 65535) {
        throw ValueError("secondary_rays must be in [1, 65535]");
    }
    if (!NonNegative(ao.min_distance) || !std::isfinite(ao.max_distance) ||
        !(ao.min_distance < ao.max_distance)) {
        throw ValueError("AO distances need 0 <= min_distance < max_distance, finite");
    }
    if (!request.low) throw ValueError("the request has no low mesh");
    ValidateMesh(*request.low, true);
    if (detail.low_as_high) {
        if (!request.high.empty()) throw ValueError("LowAsHigh bakes the low mesh onto itself: no high mesh");
    } else {
        if (request.high.empty()) throw ValueError("the request has no high mesh and LowAsHigh is off");
        for (const BakeMesh* high : request.high) {
            if (!high) throw ValueError("the request has a null high mesh");
            ValidateMesh(*high, false);
        }
    }
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

double TexelU(std::uint32_t x, std::uint32_t width) { return (x + 0.5) / width; }
double TexelV(std::uint32_t y, std::uint32_t height) { return 1.0 - (y + 0.5) / height; }

constexpr std::uint32_t kNoTriangle = std::numeric_limits<std::uint32_t>::max();

/// Sets the SSE floating-point state the bake runs under (all exceptions masked, round to
/// nearest, flush-to-zero and denormals-are-zero off) and restores the caller's on exit, so the
/// BVH build and every casting thread, the calling one included, compute alike.
class FixedFpState {
public:
    FixedFpState() : saved_(_mm_getcsr()) { _mm_setcsr(0x1F80u); }
    ~FixedFpState() { _mm_setcsr(saved_); }
    FixedFpState(const FixedFpState&) = delete;
    FixedFpState& operator=(const FixedFpState&) = delete;

private:
    unsigned saved_;
};

/// The low triangle under each texel centre; the lowest triangle index wins where UV islands
/// overlap. Serial and in triangle order, so the map is a function of the mesh alone.
std::vector<std::uint32_t> RasterizeTexels(const BakeMesh& low, std::uint32_t width,
                                           std::uint32_t height) {
    std::vector<std::uint32_t> texel_tri(static_cast<std::size_t>(width) * height, kNoTriangle);
    const std::uint32_t triangles = static_cast<std::uint32_t>(low.indices.size() / 3);
    for (std::uint32_t tri = 0; tri < triangles; ++tri) {
        double u_min = 1.0, u_max = 0.0, v_min = 1.0, v_max = 0.0;
        for (int k = 0; k < 3; ++k) {
            const Float2 uv = low.uvs[low.indices[3 * tri + k]];
            u_min = std::min(u_min, static_cast<double>(uv.x));
            u_max = std::max(u_max, static_cast<double>(uv.x));
            v_min = std::min(v_min, static_cast<double>(uv.y));
            v_max = std::max(v_max, static_cast<double>(uv.y));
        }
        // Texel centres (x + 0.5) / W in [u_min, u_max] and 1 - (y + 0.5) / H in [v_min, v_max].
        const auto clamp_index = [](double value, std::uint32_t size) {
            return static_cast<std::int64_t>(std::clamp(value, 0.0, static_cast<double>(size - 1)));
        };
        const std::int64_t x0 = clamp_index(std::floor(u_min * width - 0.5), width);
        const std::int64_t x1 = clamp_index(std::ceil(u_max * width - 0.5), width);
        const std::int64_t y0 = clamp_index(std::floor((1.0 - v_max) * height - 0.5), height);
        const std::int64_t y1 = clamp_index(std::ceil((1.0 - v_min) * height - 0.5), height);
        for (std::int64_t y = y0; y <= y1; ++y) {
            for (std::int64_t x = x0; x <= x1; ++x) {
                const std::size_t index = static_cast<std::size_t>(y) * width + static_cast<std::size_t>(x);
                if (texel_tri[index] != kNoTriangle) continue;
                UvWeights weights;
                if (UvBarycentric(low, tri, TexelU(static_cast<std::uint32_t>(x), width),
                                  TexelV(static_cast<std::uint32_t>(y), height), weights)) {
                    texel_tri[index] = tri;
                }
            }
        }
    }
    return texel_tri;
}

// ── Embree scene ─────────────────────────────────────────────────────────────────────────────

class Scene {
public:
    Scene(const EmbreeApi& api, RTCDevice device, const std::vector<const BakeMesh*>& meshes)
        : api_(api), scene_(api.newScene(device)) {
        if (!scene_) throw CapabilityError("rtcNewScene failed");
        api_.setSceneFlags(scene_, RTC_SCENE_FLAG_ROBUST);
        api_.setSceneBuildQuality(scene_, RTC_BUILD_QUALITY_MEDIUM);
        for (std::size_t m = 0; m < meshes.size(); ++m) {
            const BakeMesh& mesh = *meshes[m];
            RTCGeometry geometry = api_.newGeometry(device, RTC_GEOMETRY_TYPE_TRIANGLE);
            if (!geometry) throw CapabilityError("rtcNewGeometry failed");
            auto* vertices = static_cast<float*>(api_.setNewGeometryBuffer(
                geometry, RTC_BUFFER_TYPE_VERTEX, 0, RTC_FORMAT_FLOAT3, 3 * sizeof(float),
                mesh.positions.size()));
            auto* indices = static_cast<unsigned*>(api_.setNewGeometryBuffer(
                geometry, RTC_BUFFER_TYPE_INDEX, 0, RTC_FORMAT_UINT3, 3 * sizeof(unsigned),
                mesh.indices.size() / 3));
            if (!vertices || !indices) {
                api_.releaseGeometry(geometry);
                throw CapabilityError("rtcSetNewGeometryBuffer failed for mesh '" + mesh.name + "'");
            }
            for (std::size_t i = 0; i < mesh.positions.size(); ++i) {
                vertices[3 * i] = mesh.positions[i].x;
                vertices[3 * i + 1] = mesh.positions[i].y;
                vertices[3 * i + 2] = mesh.positions[i].z;
            }
            std::copy(mesh.indices.begin(), mesh.indices.end(), indices);
            api_.commitGeometry(geometry);
            api_.attachGeometryByID(scene_, geometry, static_cast<unsigned>(m));
            api_.releaseGeometry(geometry);
        }
        api_.commitScene(scene_);
    }
    ~Scene() { api_.releaseScene(scene_); }
    Scene(const Scene&) = delete;
    Scene& operator=(const Scene&) = delete;
    RTCScene get() const { return scene_; }

private:
    const EmbreeApi& api_;
    RTCScene scene_;
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

// ── The bake ─────────────────────────────────────────────────────────────────────────────────

struct TileCounts {
    TexelClassCounts texels;
    RayClassCounts rays;
};

struct Context {
    const EmbreeApi& api;
    RTCScene scene;
    const BakeRequest& request;
    const BakeMesh& low;
    const std::vector<const BakeMesh*>& high;
    const std::vector<std::uint32_t>& texel_tri;
    BakeResult& result;
};

Vec3d Corner(const BakeMesh& mesh, std::uint32_t tri, int k) {
    return D(mesh.positions[mesh.indices[3 * tri + k]]);
}
Vec3d CornerNormal(const BakeMesh& mesh, std::uint32_t tri, int k) {
    return D(mesh.normals[mesh.indices[3 * tri + k]]);
}

void BakeTexel(const Context& ctx, std::uint32_t x, std::uint32_t y, TileCounts& counts) {
    BakeResult& out = ctx.result;
    const std::size_t index = static_cast<std::size_t>(y) * out.width + x;
    const std::uint32_t tri = ctx.texel_tri[index];
    if (tri == kNoTriangle) {
        out.texel_class[index] = static_cast<std::uint8_t>(TexelClass::Uncovered);
        ++counts.texels.uncovered;
        return;
    }
    // The low surface point under the texel centre.
    UvWeights w;
    UvBarycentric(ctx.low, tri, TexelU(x, out.width), TexelV(y, out.height), w);
    const Vec3d p = Blend(Corner(ctx.low, tri, 0), Corner(ctx.low, tri, 1), Corner(ctx.low, tri, 2),
                          w.w0, w.w1, w.w2);
    Vec3d n = Blend(CornerNormal(ctx.low, tri, 0), CornerNormal(ctx.low, tri, 1),
                    CornerNormal(ctx.low, tri, 2), w.w0, w.w1, w.w2);
    if (!Normalize(n)) {
        throw ValueError("the normals of low triangle " + std::to_string(tri) + " cancel at texel (" +
                         std::to_string(x) + ", " + std::to_string(y) + ")");
    }

    // Primary ray: from the distance-based cage `max_height` above the surface, down to
    // `max_depth` below it.
    const DetailSettings& detail = ctx.request.detail;
    const Vec3d down = Scale(n, -1.0);
    RTCRayHit primary = MakeRay(Add(p, Scale(n, detail.max_height)), down, 0.0f,
                                detail.max_height + detail.max_depth);
    ctx.api.intersect1(ctx.scene, &primary, nullptr);
    if (primary.hit.geomID == RTC_INVALID_GEOMETRY_ID) {
        out.texel_class[index] = static_cast<std::uint8_t>(TexelClass::CentreMiss);
        ++counts.texels.centre_miss;
        return;
    }
    const unsigned origin_geom = primary.hit.geomID;
    const unsigned origin_prim = primary.hit.primID;
    const BakeMesh& hit_mesh = *ctx.high[origin_geom];
    if (Dot(down, FaceNormal(hit_mesh, origin_prim)) >= 0.0) {
        out.texel_class[index] = static_cast<std::uint8_t>(TexelClass::BackFaceHit);
        ++counts.texels.back_face_hit;
        return;
    }
    out.texel_class[index] = static_cast<std::uint8_t>(TexelClass::StraightHit);
    ++counts.texels.straight_hit;

    // The high surface point (Embree's barycentrics: p = (1-u-v) p0 + u p1 + v p2).
    const double hu = primary.hit.u;
    const double hv = primary.hit.v;
    const double h0 = 1.0 - hu - hv;
    const Vec3d ph = Blend(Corner(hit_mesh, origin_prim, 0), Corner(hit_mesh, origin_prim, 1),
                           Corner(hit_mesh, origin_prim, 2), h0, hu, hv);
    Vec3d nh = Blend(CornerNormal(hit_mesh, origin_prim, 0), CornerNormal(hit_mesh, origin_prim, 1),
                     CornerNormal(hit_mesh, origin_prim, 2), h0, hu, hv);
    if (!Normalize(nh)) {
        throw ValueError("the normals of high triangle " + std::to_string(origin_prim) + " of '" +
                         hit_mesh.name + "' cancel at texel (" + std::to_string(x) + ", " +
                         std::to_string(y) + ")");
    }

    // AO secondary rays, in sample order.
    const AoSettings& ao = ctx.request.ao;
    std::uint64_t escaped = 0;
    std::uint32_t back = 0;
    std::uint32_t self = 0;
    for (std::uint32_t s = 0; s < ao.secondary_rays; ++s) {
        const Vec3d dir = HemisphereDirection(ao.distribution,
                                              TexelSample(index, s, ao.secondary_rays), nh);
        RTCRayHit ray = MakeRay(ph, dir, ao.min_distance, ao.max_distance);
        ctx.api.intersect1(ctx.scene, &ray, nullptr);
        if (ray.hit.geomID == RTC_INVALID_GEOMETRY_ID) {
            ++escaped;
            ++counts.rays.escaped;
        } else if (ray.hit.geomID == origin_geom && ray.hit.primID == origin_prim) {
            ++self;
            ++counts.rays.self_hit;
        } else if (Dot(dir, FaceNormal(*ctx.high[ray.hit.geomID], ray.hit.primID)) >= 0.0) {
            ++back;
            ++counts.rays.back_face_hit;
        } else {
            ++counts.rays.front_hit;
        }
    }
    out.ao_raw[index] = static_cast<std::uint16_t>((escaped * 65535u + ao.secondary_rays / 2) /
                                                   ao.secondary_rays);
    out.back_face_rays[index] = static_cast<std::uint16_t>(back);
    out.self_hit_rays[index] = static_cast<std::uint16_t>(self);
}

void Add(TexelClassCounts& a, const TexelClassCounts& b) {
    a.uncovered += b.uncovered;
    a.straight_hit += b.straight_hit;
    a.back_face_hit += b.back_face_hit;
    a.centre_miss += b.centre_miss;
}

void Add(RayClassCounts& a, const RayClassCounts& b) {
    a.escaped += b.escaped;
    a.front_hit += b.front_hit;
    a.back_face_hit += b.back_face_hit;
    a.self_hit += b.self_hit;
}

}  // namespace

BakeResult EmbreeBaker::bake(const BakeRequest& request) {
    if (!caps_.qualified) {
        throw CapabilityError("the CPU baker is not qualified on this configuration: " +
                              caps_.unqualified_reason);
    }
    ValidateRequest(caps_, request);
    const FixedFpState fp_state;

    BakeResult result;
    result.width = 1u << request.output_size_log2[0];
    result.height = 1u << request.output_size_log2[1];
    result.tile_size = kTileSize;
    result.rays_per_texel = request.ao.secondary_rays;
    const std::size_t texels = static_cast<std::size_t>(result.width) * result.height;
    result.ao_raw.assign(texels, 0);
    result.texel_class.assign(texels, 0);
    result.back_face_rays.assign(texels, 0);
    result.self_hit_rays.assign(texels, 0);

    const std::vector<const BakeMesh*> high =
        request.detail.low_as_high ? std::vector<const BakeMesh*>{request.low} : request.high;
    const Scene scene(*api_, device_, high);
    if (api_->getDeviceError(device_) != RTC_ERROR_NONE) {
        throw CapabilityError(std::string("Embree failed to build the scene: ") +
                              api_->getDeviceLastErrorMessage(device_));
    }
    const std::vector<std::uint32_t> texel_tri =
        RasterizeTexels(*request.low, result.width, result.height);

    const std::uint32_t tiles_x = (result.width + kTileSize - 1) / kTileSize;
    const std::uint32_t tiles_y = (result.height + kTileSize - 1) / kTileSize;
    const std::uint32_t tile_count = tiles_x * tiles_y;
    std::vector<TileCounts> tile_counts(tile_count);
    std::vector<std::exception_ptr> tile_errors(tile_count);
    const Context ctx{*api_, scene.get(), request, *request.low, high, texel_tri, result};

    std::uint32_t threads = request.threads;
    if (threads == 0) threads = std::max(1u, std::thread::hardware_concurrency());
    threads = std::min(threads, tile_count);
    result.threads_used = threads;
    // Embree keeps its error code per thread and device, so each worker reads its own.
    std::vector<RTCError> worker_errors(threads, RTC_ERROR_NONE);
    std::atomic<std::uint32_t> next{0};
    const auto worker = [&](std::uint32_t worker_index) {
        const FixedFpState fp_state;
        for (std::uint32_t tile = next.fetch_add(1); tile < tile_count; tile = next.fetch_add(1)) {
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
        }
        worker_errors[worker_index] = api_->getDeviceError(device_);
    };
    if (threads == 1) {
        worker(0);
    } else {
        std::vector<std::thread> pool;
        pool.reserve(threads);
        for (std::uint32_t i = 0; i < threads; ++i) pool.emplace_back(worker, i);
        for (std::thread& thread : pool) thread.join();
    }
    // The first failing tile in tile order, whatever thread met it first.
    for (const std::exception_ptr& error : tile_errors) {
        if (error) std::rethrow_exception(error);
    }
    for (RTCError error : worker_errors) {
        if (error != RTC_ERROR_NONE) {
            throw CapabilityError("Embree reported error " + std::to_string(error) +
                                  " while casting");
        }
    }
    for (const TileCounts& counts : tile_counts) {
        Add(result.texels, counts.texels);
        Add(result.rays, counts.rays);
    }
    return result;
}

}  // namespace uzp::bake
