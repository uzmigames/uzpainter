// Native tests of the CPU baker feasibility slice (`src/bake/`, phase3.1_baker-request-model,
// decision 302). Built by `zig build bake-feasibility-tests` and driven by
// tests/bake/test_bake_feasibility.py. CPU only: no GPU is involved.
//
// Usage:
//   uzp-bake-feasibility-tests run [case]       run every native case (or one); exit 0 when all
//                                               pass, each prints "PASS <case>"
//   uzp-bake-feasibility-tests bake <fixture> <threads> [--embree-build-threads K] [--out FILE]
//                                               bake an authored fixture and print one JSON line:
//                                               the SHA-256 of the result bytes and the class
//                                               counts; --out writes the bytes
// Errors print "<ErrorClass>: <message>" on stderr and exit 3.

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <functional>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include "bake/bake_request.h"
#include "bake/embree_baker.h"
#include "bake/sampling.h"
#include "bake_fixtures.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"

namespace {

using namespace uzp::bake;
using uzp::core::NotYetSupported;
using uzp::core::ValueError;

struct Failure : std::runtime_error {
    using std::runtime_error::runtime_error;
};

#define CHECK(cond)                                                                            \
    do {                                                                                       \
        if (!(cond)) throw Failure(std::string(__FILE__ ":") + std::to_string(__LINE__) + ": " #cond); \
    } while (0)

#define CHECK_EQ(a, b)                                                                         \
    do {                                                                                       \
        const auto va_ = (a);                                                                  \
        const auto vb_ = (b);                                                                  \
        if (!(va_ == vb_)) {                                                                   \
            throw Failure(std::string(__FILE__ ":") + std::to_string(__LINE__) + ": " #a " == " #b \
                          " (" + std::to_string(va_) + " vs " + std::to_string(vb_) + ")");    \
        }                                                                                      \
    } while (0)

template <typename Error>
std::string ExpectThrow(const std::function<void()>& fn) {
    try {
        fn();
    } catch (const Error& error) {
        return error.what();
    }
    throw Failure("the expected error was not raised");
}

constexpr std::uint32_t kRays = 32;

/// A request at 64 x 64 for the low plane [-1, 1]² (UV [0.25, 0.75]², 32 x 32 covered texels).
BakeRequest PlaneRequest(const BakeMesh& low) {
    BakeRequest request;
    request.texture_set = "fixture";
    request.input_revision = "fixture-r1";
    request.usages = {MeshMapUsage::AO};
    request.output_size_log2[0] = 6;
    request.output_size_log2[1] = 6;
    request.detail.max_height = 0.01f;
    request.detail.max_depth = 0.01f;
    request.ao.secondary_rays = kRays;
    request.ao.min_distance = 1e-4f;
    request.ao.max_distance = 100.0f;
    request.low = &low;
    request.threads = 4;
    return request;
}

constexpr std::uint64_t kTexels = 64 * 64;
constexpr std::uint64_t kCovered = 32 * 32;

/// The conservation identities every result must satisfy.
void CheckConservation(const BakeResult& r) {
    const std::uint64_t texels = static_cast<std::uint64_t>(r.width) * r.height;
    CHECK_EQ(r.texels.uncovered + r.texels.straight_hit + r.texels.back_face_hit + r.texels.centre_miss,
             texels);
    CHECK_EQ(r.rays.escaped + r.rays.front_hit + r.rays.back_face_hit + r.rays.self_hit,
             r.texels.straight_hit * r.rays_per_texel);
    TexelClassCounts seen;
    std::uint64_t back = 0, self = 0;
    for (std::size_t i = 0; i < texels; ++i) {
        const auto cls = static_cast<TexelClass>(r.texel_class[i]);
        switch (cls) {
            case TexelClass::Uncovered: ++seen.uncovered; break;
            case TexelClass::StraightHit: ++seen.straight_hit; break;
            case TexelClass::BackFaceHit: ++seen.back_face_hit; break;
            case TexelClass::CentreMiss: ++seen.centre_miss; break;
        }
        if (cls != TexelClass::StraightHit) {
            // Nothing is filled: a texel without a straight hit carries no value or ray count.
            CHECK_EQ(r.ao_raw[i], 0);
            CHECK_EQ(r.back_face_rays[i], 0);
            CHECK_EQ(r.self_hit_rays[i], 0);
        }
        back += r.back_face_rays[i];
        self += r.self_hit_rays[i];
    }
    CHECK_EQ(seen.uncovered, r.texels.uncovered);
    CHECK_EQ(seen.straight_hit, r.texels.straight_hit);
    CHECK_EQ(seen.back_face_hit, r.texels.back_face_hit);
    CHECK_EQ(seen.centre_miss, r.texels.centre_miss);
    CHECK_EQ(back, r.rays.back_face_hit);
    CHECK_EQ(self, r.rays.self_hit);
}

/// The texel lies under the UV square [0.25, 0.75]² (its centre, row 0 at v = 1).
bool UnderPlaneUv(std::size_t index) {
    const double u = (index % 64 + 0.5) / 64.0;
    const double v = 1.0 - (index / 64 + 0.5) / 64.0;
    return u >= 0.25 && u <= 0.75 && v >= 0.25 && v <= 0.75;
}

// ── Cases ────────────────────────────────────────────────────────────────────────────────────

void CaseSampling() {
    CHECK(RadicalInverse2(0) == 0.0);
    CHECK(RadicalInverse2(1) == 0.5);
    CHECK(RadicalInverse2(2) == 0.25);
    CHECK(RadicalInverse2(3) == 0.75);
    CHECK(RadicalInverse2(5) == 0.625);
    const Vec3d normals[] = {{0, 0, 1}, {0, 0, -1}, {1, 0, 0}, {0.6, 0.0, 0.8}, {0, -0.8, -0.6}};
    for (const Vec3d& n : normals) {
        for (Distribution d : {Distribution::Cosine, Distribution::Uniform}) {
            for (std::uint32_t s = 0; s < 64; ++s) {
                const Sample2 sample = TexelSample(12345, s, 64);
                CHECK(sample.u1 >= 0.0 && sample.u1 < 1.0 && sample.u2 >= 0.0 && sample.u2 < 1.0);
                const Vec3d dir = HemisphereDirection(d, sample, n);
                const double length = dir.x * dir.x + dir.y * dir.y + dir.z * dir.z;
                CHECK(length > 1.0 - 1e-12 && length < 1.0 + 1e-12);
                CHECK(dir.x * n.x + dir.y * n.y + dir.z * n.z >= -1e-12);
            }
        }
    }
    // A pure function of (texel, sample, count): the same arguments give the same bits.
    const Sample2 a = TexelSample(77, 5, 64);
    const Sample2 b = TexelSample(77, 5, 64);
    CHECK(std::memcmp(&a, &b, sizeof a) == 0);
    const Sample2 c = TexelSample(78, 5, 64);
    CHECK(a.u1 != c.u1 || a.u2 != c.u2);
}

void CaseOpenPlane() {
    EmbreeBaker baker;
    const BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);
    const BakeResult r = baker.bake(PlaneRequest(low));
    CheckConservation(r);
    CHECK_EQ(r.texels.straight_hit, kCovered);
    CHECK_EQ(r.texels.uncovered, kTexels - kCovered);
    CHECK_EQ(r.rays.escaped, kCovered * kRays);
    for (std::size_t i = 0; i < kTexels; ++i) {
        CHECK_EQ(r.texel_class[i], static_cast<std::uint8_t>(UnderPlaneUv(i) ? TexelClass::StraightHit
                                                                                : TexelClass::Uncovered));
        if (UnderPlaneUv(i)) CHECK_EQ(r.ao_raw[i], 65535);
    }
}

/// The low plane inside a box of half-size 10 (high = the plane and the box): every secondary
/// ray hits the box, a front face when it faces inward and a back face when it faces outward.
void CaseBox(bool inward) {
    EmbreeBaker baker;
    const BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);
    const BakeMesh high = fixtures::Plane("high", -1, 1, -1, 1, 0);
    const BakeMesh box = fixtures::Box("box", 10.0f, inward);
    BakeRequest request = PlaneRequest(low);
    request.detail.low_as_high = false;
    request.high = {&high, &box};
    const BakeResult r = baker.bake(request);
    CheckConservation(r);
    CHECK_EQ(r.texels.straight_hit, kCovered);
    CHECK_EQ(r.rays.escaped, 0u);
    CHECK_EQ(r.rays.self_hit, 0u);
    CHECK_EQ(inward ? r.rays.front_hit : r.rays.back_face_hit, kCovered * kRays);
    CHECK_EQ(inward ? r.rays.back_face_hit : r.rays.front_hit, 0u);
    for (std::size_t i = 0; i < kTexels; ++i) {
        if (!UnderPlaneUv(i)) continue;
        CHECK_EQ(r.ao_raw[i], 0);
        CHECK_EQ(r.back_face_rays[i], inward ? 0u : kRays);
    }
}

/// The high plane covers only x < 0: texels over x > 0 are centre misses, kept as a class.
void CaseCentreMiss() {
    EmbreeBaker baker;
    const BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);
    const BakeMesh high = fixtures::Plane("high_half", -1.5f, 0.0f, -1.5f, 1.5f, 0);
    BakeRequest request = PlaneRequest(low);
    request.detail.low_as_high = false;
    request.high = {&high};
    const BakeResult r = baker.bake(request);
    CheckConservation(r);
    CHECK_EQ(r.texels.straight_hit, kCovered / 2);
    CHECK_EQ(r.texels.centre_miss, kCovered / 2);
    CHECK_EQ(r.rays.escaped, kCovered / 2 * kRays);
    for (std::size_t i = 0; i < kTexels; ++i) {
        if (!UnderPlaneUv(i)) continue;
        const bool left = (i % 64 + 0.5) / 64.0 < 0.5;
        CHECK_EQ(r.texel_class[i], static_cast<std::uint8_t>(left ? TexelClass::StraightHit
                                                                  : TexelClass::CentreMiss));
    }
}

/// The high plane faces down: every primary ray meets its back face, kept as a class, and casts
/// no secondary ray.
void CaseBackFacePrimary() {
    EmbreeBaker baker;
    const BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);
    const BakeMesh high = fixtures::Plane("high_flipped", -1.5f, 1.5f, -1.5f, 1.5f, 0, true);
    BakeRequest request = PlaneRequest(low);
    request.detail.low_as_high = false;
    request.high = {&high};
    const BakeResult r = baker.bake(request);
    CheckConservation(r);
    CHECK_EQ(r.texels.back_face_hit, kCovered);
    CHECK_EQ(r.texels.straight_hit, 0u);
    CHECK_EQ(r.rays.escaped + r.rays.front_hit + r.rays.back_face_hit + r.rays.self_hit, 0u);
}

/// With `min_distance` 0 the secondary rays start exactly on their origin triangle; a hit on it
/// is counted as `self_hit`, never as occlusion by other geometry. With an offset there are none.
void CaseSelfHit() {
    EmbreeBaker baker;
    const BakeMesh low = fixtures::SphereOnGround(2, 8, 16);
    BakeRequest request;
    request.texture_set = "fixture";
    request.input_revision = "fixture-r1";
    request.usages = {MeshMapUsage::AO};
    request.output_size_log2[0] = 7;
    request.output_size_log2[1] = 7;
    request.ao.secondary_rays = kRays;
    request.ao.min_distance = 0.0f;
    request.ao.max_distance = 10.0f;
    request.low = &low;
    request.threads = 4;
    const BakeResult zero = baker.bake(request);
    CheckConservation(zero);
    std::printf("self_hit min_distance=0: self_hit=%llu of %llu rays\n",
                static_cast<unsigned long long>(zero.rays.self_hit),
                static_cast<unsigned long long>(zero.texels.straight_hit * kRays));
    CHECK(zero.rays.self_hit > 0);
    request.ao.min_distance = 1e-3f;
    const BakeResult offset = baker.bake(request);
    CheckConservation(offset);
    CHECK_EQ(offset.rays.self_hit, 0u);
    CHECK_EQ(offset.texels.straight_hit, zero.texels.straight_hit);
}

void CaseCapabilityErrors() {
    // An unqualified ISA: refused before any work, the reason names the missing feature.
    CpuFeatures no_avx2;
    no_avx2.fma = no_avx2.bmi1 = no_avx2.bmi2 = no_avx2.lzcnt = no_avx2.f16c = no_avx2.os_ymm = true;
    EmbreeBaker unqualified({.embree_build_threads = 1, .cpu_features = no_avx2});
    CHECK(!unqualified.caps().qualified);
    CHECK(unqualified.caps().unqualified_reason.find("AVX2") != std::string::npos);
    const BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);
    std::string message = ExpectThrow<CapabilityError>([&] { unqualified.bake(PlaneRequest(low)); });
    CHECK(message.find("AVX2") != std::string::npos);

    EmbreeBaker baker;
    CHECK(baker.caps().qualified);
    CHECK(baker.caps().parity_status == "pending-evidence");
    CHECK(baker.caps().embree_version == "4.4.1");
    CHECK(baker.caps().usages.size() == 1 && baker.caps().usages[0] == MeshMapUsage::AO);

    BakeRequest request = PlaneRequest(low);
    request.usages = {MeshMapUsage::AO, MeshMapUsage::Thickness};
    message = ExpectThrow<CapabilityError>([&] { baker.bake(request); });
    CHECK(message.find("phase3.4_baker-thickness") != std::string::npos);

    request = PlaneRequest(low);
    request.detail.cage_mode = CageMode::Automatic;
    message = ExpectThrow<CapabilityError>([&] { baker.bake(request); });
    CHECK(message.find("release gap") != std::string::npos);

    request = PlaneRequest(low);
    request.detail.cage_mode = CageMode::CustomFile;
    ExpectThrow<NotYetSupported>([&] { baker.bake(request); });

    request = PlaneRequest(low);
    request.output_size_log2[0] = 13;
    ExpectThrow<CapabilityError>([&] { baker.bake(request); });

    request = PlaneRequest(low);
    request.high = {&low};  // LowAsHigh with a high mesh
    ExpectThrow<ValueError>([&] { baker.bake(request); });

    request = PlaneRequest(low);
    request.ao.min_distance = request.ao.max_distance;
    ExpectThrow<ValueError>([&] { baker.bake(request); });
}

/// The determinism scene at 128², baked at 1, 4 and every hardware thread in one process.
void CaseThreadsInProcess() {
    EmbreeBaker baker;
    const BakeMesh low = fixtures::SphereOnGround();
    BakeRequest request;
    request.texture_set = "fixture";
    request.input_revision = "fixture-r1";
    request.usages = {MeshMapUsage::AO};
    request.output_size_log2[0] = 7;
    request.output_size_log2[1] = 7;
    request.ao.secondary_rays = 32;
    request.ao.min_distance = 1e-4f;
    request.ao.max_distance = 2.0f;
    request.low = &low;
    std::string reference;
    for (std::uint32_t threads : {1u, 4u, std::max(1u, std::thread::hardware_concurrency())}) {
        request.threads = threads;
        const BakeResult r = baker.bake(request);
        CheckConservation(r);
        const std::string bytes = SerializeResult(r);
        if (reference.empty()) {
            reference = bytes;
        } else {
            CHECK(bytes == reference);
        }
    }
}

const std::vector<std::pair<std::string, std::function<void()>>>& Cases() {
    static const std::vector<std::pair<std::string, std::function<void()>>> cases = {
        {"sampling", CaseSampling},
        {"open_plane", CaseOpenPlane},
        {"box_inward", [] { CaseBox(true); }},
        {"box_outward", [] { CaseBox(false); }},
        {"centre_miss", CaseCentreMiss},
        {"back_face_primary", CaseBackFacePrimary},
        {"self_hit", CaseSelfHit},
        {"capability_errors", CaseCapabilityErrors},
        {"threads_in_process", CaseThreadsInProcess},
    };
    return cases;
}

int Run(const char* only) {
    int failures = 0;
    bool found = false;
    for (const auto& [name, fn] : Cases()) {
        if (only && name != only) continue;
        found = true;
        try {
            fn();
            std::printf("PASS %s\n", name.c_str());
        } catch (const std::exception& error) {
            std::printf("FAIL %s: %s\n", name.c_str(), error.what());
            ++failures;
        }
    }
    if (!found) throw ValueError(std::string("no case named ") + (only ? only : ""));
    return failures == 0 ? 0 : 1;
}

std::string Json(const BakeResult& r, const Capabilities& caps, const std::string& fixture,
                 const std::string& sha, std::uint32_t embree_threads) {
    const auto u = [](std::uint64_t v) { return std::to_string(v); };
    return "{\"fixture\":\"" + fixture + "\",\"width\":" + u(r.width) + ",\"height\":" + u(r.height) +
           ",\"rays_per_texel\":" + u(r.rays_per_texel) + ",\"threads_used\":" + u(r.threads_used) +
           ",\"embree_build_threads\":" + u(embree_threads) + ",\"embree_version\":\"" +
           caps.embree_version + "\",\"isa\":\"" + caps.isa + "\",\"tasking\":\"" + caps.tasking_system +
           "\",\"parity_status\":\"" + caps.parity_status + "\",\"sha256\":\"" + sha +
           "\",\"texels\":{\"uncovered\":" + u(r.texels.uncovered) + ",\"straight_hit\":" +
           u(r.texels.straight_hit) + ",\"back_face_hit\":" + u(r.texels.back_face_hit) +
           ",\"centre_miss\":" + u(r.texels.centre_miss) + "},\"rays\":{\"escaped\":" +
           u(r.rays.escaped) + ",\"front_hit\":" + u(r.rays.front_hit) + ",\"back_face_hit\":" +
           u(r.rays.back_face_hit) + ",\"self_hit\":" + u(r.rays.self_hit) + "}}";
}

/// The `bake` command's fixtures: `scene` (the sphere on the ground at 256², 64 rays, low as
/// high) and `scene_self` (the same with min_distance 0, where self hits occur).
int Bake(int argc, char** argv) {
    if (argc < 4) throw ValueError("bake needs <fixture> <threads>");
    const std::string fixture = argv[2];
    const auto threads = static_cast<std::uint32_t>(std::stoul(argv[3]));
    std::uint32_t embree_threads = 1;
    std::string out;
    for (int i = 4; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--embree-build-threads" && i + 1 < argc) {
            embree_threads = static_cast<std::uint32_t>(std::stoul(argv[++i]));
        } else if (arg == "--out" && i + 1 < argc) {
            out = argv[++i];
        } else {
            throw ValueError("unknown argument " + arg);
        }
    }
    if (fixture != "scene" && fixture != "scene_self") throw ValueError("unknown fixture " + fixture);
    EmbreeBaker baker({.embree_build_threads = embree_threads, .cpu_features = std::nullopt});
    const BakeMesh low = fixtures::SphereOnGround();
    BakeRequest request;
    request.texture_set = fixture;
    request.input_revision = "fixture-r1";
    request.usages = {MeshMapUsage::AO};
    request.output_size_log2[0] = 8;
    request.output_size_log2[1] = 8;
    request.ao.secondary_rays = 64;
    request.ao.min_distance = fixture == "scene" ? 1e-4f : 0.0f;
    request.ao.max_distance = 2.0f;
    request.low = &low;
    request.threads = threads;
    const BakeResult r = baker.bake(request);
    CheckConservation(r);
    const std::string bytes = SerializeResult(r);
    if (!out.empty()) {
        std::ofstream file(out, std::ios::binary);
        file.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
        if (!file) throw std::runtime_error("cannot write " + out);
    }
    std::printf("%s\n", Json(r, baker.caps(), fixture, uzp::core::Sha256Hex(bytes), embree_threads).c_str());
    return 0;
}

int Command(int argc, char** argv) {
    if (argc >= 2 && std::string(argv[1]) == "run") return Run(argc >= 3 ? argv[2] : nullptr);
    if (argc >= 2 && std::string(argv[1]) == "bake") return Bake(argc, argv);
    std::fprintf(stderr, "usage: uzp-bake-feasibility-tests run [case] | bake <fixture> <threads> "
                         "[--embree-build-threads K] [--out FILE]\n");
    return 2;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        return Command(argc, argv);
    } catch (const CapabilityError& error) {
        std::fprintf(stderr, "CapabilityError: %s\n", error.what());
    } catch (const ValueError& error) {
        std::fprintf(stderr, "ValueError: %s\n", error.what());
    } catch (const NotYetSupported& error) {
        std::fprintf(stderr, "NotYetSupported: %s\n", error.what());
    } catch (const std::exception& error) {
        std::fprintf(stderr, "Error: %s\n", error.what());
    }
    return 3;
}
