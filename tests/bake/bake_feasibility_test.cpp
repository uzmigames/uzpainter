// Native tests of the CPU baker (`src/bake/`, phase3.1_baker-request-model, decisions 302 and
// 306). Built by `zig build bake-feasibility-tests` and driven by
// tests/bake/test_bake_feasibility.py. CPU only: no GPU is involved.
//
// Usage:
//   uzp-bake-feasibility-tests run [case]       run every native case (or one); exit 0 when all
//                                               pass, each prints "PASS <case>"
//   uzp-bake-feasibility-tests bake <fixture> <threads> [--embree-build-threads K] [--diagnostic]
//                                [--out FILE]   bake an authored fixture and print one JSON line:
//                                               the SHA-256 of the result bytes and the class
//                                               counts; --out writes the bytes; --diagnostic
//                                               allows an unqualified BVH build thread count
// Errors print "<ErrorClass>: <message>" on stderr and exit 3.

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <deque>
#include <fstream>
#include <functional>
#include <future>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <system_error>
#include <thread>
#include <utility>
#include <vector>

#include "bake/bake_request.h"
#include "bake/baker.h"
#include "bake/baking_parameters.h"
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

bool Contains(const std::string& text, const std::string& part) { return text.find(part) != std::string::npos; }

/// The synchronous form of a bake (every job waited for).
BakeResult Bake(EmbreeBaker& baker, const BakeRequest& request) { return BakeAndWait(baker, request); }

BakerConfig Config(std::uint32_t build_threads, bool diagnostic, std::optional<CpuFeatures> cpu = std::nullopt) {
    BakerConfig config;
    config.embree_build_threads = build_threads;
    config.allow_unqualified_build_threads_diagnostic = diagnostic;
    config.cpu_features = cpu;
    return config;
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
    request.low = {&low};
    request.threads = 4;
    return request;
}

constexpr std::uint64_t kTexels = 64 * 64;
constexpr std::uint64_t kCovered = 32 * 32;

bool IsHit(std::uint8_t cls) {
    return cls == static_cast<std::uint8_t>(TexelClass::StraightHit) ||
           cls == static_cast<std::uint8_t>(TexelClass::CageHit);
}

/// The conservation identities every result must satisfy.
void CheckConservation(const BakeResult& r) {
    const std::uint64_t texels = static_cast<std::uint64_t>(r.width) * r.height;
    const TexelClassCounts& t = r.texels;
    CHECK_EQ(t.uncovered + t.straight_hit + t.back_face_hit + t.centre_miss + t.cage_hit + t.hidden, texels);
    const SubsampleCounts& s = r.subsamples;
    CHECK_EQ(s.hit + s.back_face_hit + s.centre_miss + s.hidden, s.covered);
    CHECK_EQ(r.rays.escaped + r.rays.front_hit + r.rays.back_face_hit + r.rays.self_hit,
             s.hit * r.rays_per_texel);
    TexelClassCounts seen;
    std::uint64_t back = 0, self = 0, covered = 0, hits = 0;
    for (std::size_t i = 0; i < texels; ++i) {
        const auto cls = static_cast<TexelClass>(r.texel_class[i]);
        switch (cls) {
            case TexelClass::Uncovered: ++seen.uncovered; break;
            case TexelClass::StraightHit: ++seen.straight_hit; break;
            case TexelClass::BackFaceHit: ++seen.back_face_hit; break;
            case TexelClass::CentreMiss: ++seen.centre_miss; break;
            case TexelClass::CageHit: ++seen.cage_hit; break;
            case TexelClass::Hidden: ++seen.hidden; break;
        }
        CHECK_EQ(cls == TexelClass::Uncovered, r.coverage[i] == 0);
        CHECK(r.subsample_hits[i] <= r.coverage[i]);
        if (!IsHit(r.texel_class[i])) {
            // Nothing is filled: a texel without a hit carries no value, hit or ray count.
            CHECK_EQ(r.ao_raw[i], 0);
            CHECK_EQ(r.subsample_hits[i], 0);
            CHECK_EQ(r.back_face_rays[i], 0);
            CHECK_EQ(r.self_hit_rays[i], 0);
        } else {
            CHECK(r.subsample_hits[i] > 0);
        }
        // Dilation writes only outside the used surface.
        if (cls != TexelClass::Uncovered) CHECK_EQ(r.ao[i], r.ao_raw[i]);
        back += r.back_face_rays[i];
        self += r.self_hit_rays[i];
        covered += r.coverage[i];
        hits += r.subsample_hits[i];
    }
    CHECK_EQ(seen.uncovered, t.uncovered);
    CHECK_EQ(seen.straight_hit, t.straight_hit);
    CHECK_EQ(seen.back_face_hit, t.back_face_hit);
    CHECK_EQ(seen.centre_miss, t.centre_miss);
    CHECK_EQ(seen.cage_hit, t.cage_hit);
    CHECK_EQ(seen.hidden, t.hidden);
    CHECK_EQ(back, r.rays.back_face_hit);
    CHECK_EQ(self, r.rays.self_hit);
    CHECK_EQ(covered, s.covered);
    CHECK_EQ(hits, s.hit);
    if (r.dilation_width == 0) CHECK_EQ(r.dilated_texels, 0u);
}

/// The texel lies under the UV square [0.25, 0.75]² (its centre, row 0 at v = 1).
bool UnderPlaneUv(std::size_t index) {
    const double u = (index % 64 + 0.5) / 64.0;
    const double v = 1.0 - (index / 64 + 0.5) / 64.0;
    return u >= 0.25 && u <= 0.75 && v >= 0.25 && v <= 0.75;
}

// ── Slice-1 cases (decision 302), on the job API ─────────────────────────────────────────────

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
    const BakeResult r = Bake(baker, PlaneRequest(low));
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
    const BakeResult r = Bake(baker, request);
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
    const BakeResult r = Bake(baker, request);
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
    const BakeResult r = Bake(baker, request);
    CheckConservation(r);
    CHECK_EQ(r.texels.back_face_hit, kCovered);
    CHECK_EQ(r.texels.straight_hit, 0u);
    CHECK_EQ(r.rays.escaped + r.rays.front_hit + r.rays.back_face_hit + r.rays.self_hit, 0u);
    // IgnoreBackface: the same rays pass through the back face and find nothing: centre misses.
    request.detail.ignore_backface = true;
    const BakeResult ignored = Bake(baker, request);
    CheckConservation(ignored);
    CHECK_EQ(ignored.texels.centre_miss, kCovered);
    CHECK_EQ(ignored.texels.back_face_hit, 0u);
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
    request.low = {&low};
    request.threads = 4;
    const BakeResult zero = Bake(baker, request);
    CheckConservation(zero);
    std::printf("self_hit min_distance=0: self_hit=%llu of %llu rays\n",
                static_cast<unsigned long long>(zero.rays.self_hit),
                static_cast<unsigned long long>(zero.texels.straight_hit * kRays));
    CHECK(zero.rays.self_hit > 0);
    request.ao.min_distance = 1e-3f;
    const BakeResult offset = Bake(baker, request);
    CheckConservation(offset);
    CHECK_EQ(offset.rays.self_hit, 0u);
    CHECK_EQ(offset.texels.straight_hit, zero.texels.straight_hit);
}

void CaseCapabilityErrors() {
    // An unqualified ISA: refused before any work, the reason names the missing feature.
    CpuFeatures no_avx2;
    no_avx2.fma = no_avx2.bmi1 = no_avx2.bmi2 = no_avx2.lzcnt = no_avx2.f16c = no_avx2.os_ymm = true;
    EmbreeBaker unqualified(Config(1, false, no_avx2));
    CHECK(!unqualified.caps().qualified);
    CHECK(Contains(unqualified.caps().unqualified_reason, "AVX2"));
    const BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);
    std::string message = ExpectThrow<CapabilityError>([&] { unqualified.bake(PlaneRequest(low)); });
    CHECK(Contains(message, "AVX2"));

    EmbreeBaker baker;
    CHECK(baker.caps().qualified);
    CHECK(baker.caps().parity_status == "pending-evidence");
    CHECK(baker.caps().parity_owner_task == "phase3.4_baker-ao");
    CHECK(baker.caps().embree_version == "4.4.1");
    CHECK(baker.caps().usages.size() == 1 && baker.caps().usages[0] == MeshMapUsage::AO);

    BakeRequest request = PlaneRequest(low);
    request.usages = {MeshMapUsage::AO, MeshMapUsage::Thickness};
    message = ExpectThrow<CapabilityError>([&] { baker.bake(request); });
    CHECK(Contains(message, "phase3.4_baker-thickness"));

    request = PlaneRequest(low);
    request.usages = {MeshMapUsage::Normal};
    message = ExpectThrow<CapabilityError>([&] { baker.bake(request); });
    CHECK(Contains(message, "phase3.2_baker-normal"));

    request = PlaneRequest(low);
    request.detail.cage_mode = CageMode::Automatic;
    message = ExpectThrow<CapabilityError>([&] { baker.bake(request); });
    CHECK(Contains(message, "release gap"));

    request = PlaneRequest(low);
    request.detail.cage_mode = CageMode::CustomFile;  // no cage meshes: loading the file is open
    message = ExpectThrow<NotYetSupported>([&] { baker.bake(request); });
    CHECK(Contains(message, "phase3.1_baker-request-model item 2.5"));

    request = PlaneRequest(low);
    request.common.apply_diffusion = true;
    message = ExpectThrow<NotYetSupported>([&] { baker.bake(request); });
    CHECK(Contains(message, "phase3.1_baker-request-model item 2.7"));

    request = PlaneRequest(low);
    request.output_size_log2[0] = 13;
    ExpectThrow<CapabilityError>([&] { baker.bake(request); });

    request = PlaneRequest(low);
    request.high = {&low};  // LowAsHigh with a high mesh
    ExpectThrow<ValueError>([&] { baker.bake(request); });

    request = PlaneRequest(low);
    request.ao.min_distance = request.ao.max_distance;
    ExpectThrow<ValueError>([&] { baker.bake(request); });

    request = PlaneRequest(low);
    request.detail.subsampling = 3;
    ExpectThrow<ValueError>([&] { baker.bake(request); });

    request = PlaneRequest(low);
    request.detail.subsampling = 8;
    request.ao.secondary_rays = 1025;  // 1025 x 64 > 65535
    ExpectThrow<ValueError>([&] { baker.bake(request); });

    request = PlaneRequest(low);
    request.hidden_mask.assign(10, 1);
    ExpectThrow<ValueError>([&] { baker.bake(request); });
}

/// Decision 302 qualifies the serial BVH build only: any other build thread count is
/// unqualified, refused, and bakes only on the explicit diagnostic path.
void CaseBuildThreadsDiagnostic() {
    const BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);
    EmbreeBaker parallel(Config(8, false));
    CHECK(!parallel.caps().qualified);
    CHECK(parallel.caps().diagnostic_build_threads);
    CHECK(Contains(parallel.caps().unqualified_reason, "serial BVH build"));
    const std::string message = ExpectThrow<CapabilityError>([&] { parallel.bake(PlaneRequest(low)); });
    CHECK(Contains(message, "embree_build_threads 8"));

    EmbreeBaker diagnostic(Config(8, true));
    CHECK(!diagnostic.caps().qualified);
    const BakeResult r = Bake(diagnostic, PlaneRequest(low));
    CHECK(r.diagnostic_unqualified);
    CheckConservation(r);

    EmbreeBaker serial;
    CHECK(serial.caps().qualified && !serial.caps().diagnostic_build_threads);
    const BakeResult qualified = Bake(serial, PlaneRequest(low));
    CHECK(!qualified.diagnostic_unqualified);
    // The diagnostic flag on a qualified configuration changes nothing.
    EmbreeBaker flagged(Config(1, true));
    CHECK(flagged.caps().qualified);
    const BakeResult same = Bake(flagged, PlaneRequest(low));
    CHECK(!same.diagnostic_unqualified);
    CHECK(SerializeResult(same) == SerializeResult(qualified));

    // The diagnostic flag never lifts another reason (here the ISA).
    CpuFeatures no_avx2;
    no_avx2.fma = no_avx2.bmi1 = no_avx2.bmi2 = no_avx2.lzcnt = no_avx2.f16c = no_avx2.os_ymm = true;
    EmbreeBaker isa(Config(8, true, no_avx2));
    CHECK(!isa.caps().diagnostic_build_threads);
    ExpectThrow<CapabilityError>([&] { isa.bake(PlaneRequest(low)); });
}

BakeRequest SphereRequest(const BakeMesh& low, std::uint32_t log2) {
    BakeRequest request;
    request.texture_set = "fixture";
    request.input_revision = "fixture-r1";
    request.usages = {MeshMapUsage::AO};
    request.output_size_log2[0] = log2;
    request.output_size_log2[1] = log2;
    request.ao.secondary_rays = 32;
    request.ao.min_distance = 1e-4f;
    request.ao.max_distance = 2.0f;
    request.low = {&low};
    return request;
}

/// The determinism scene at 128², baked at 1, 4 and every hardware thread in one process.
void CaseThreadsInProcess() {
    EmbreeBaker baker;
    const BakeMesh low = fixtures::SphereOnGround();
    BakeRequest request = SphereRequest(low, 7);
    std::string reference;
    for (std::uint32_t threads : {1u, 4u, std::max(1u, std::thread::hardware_concurrency())}) {
        request.threads = threads;
        const BakeResult r = Bake(baker, request);
        CheckConservation(r);
        const std::string bytes = SerializeResult(r);
        if (reference.empty()) {
            reference = bytes;
        } else {
            CHECK(bytes == reference);
        }
    }
}

// ── Jobs: async, progress, cancellation, failure ─────────────────────────────────────────────

void CaseJobAsync() {
    EmbreeBaker baker;
    const BakeMesh low = fixtures::SphereOnGround(2, 8, 16);
    BakeRequest request = SphereRequest(low, 7);
    request.threads = 4;
    JobHandle job = baker.bake(request);
    JobHandle other = baker.bake(request);
    CHECK(job.valid() && other.valid());
    CHECK(job.id() != other.id());
    CHECK(job.wait() == JobStatus::Success);
    CHECK(other.wait() == JobStatus::Success);
    const JobProgress progress = job.progress();
    CHECK_EQ(progress.total_tiles, 64u);  // 128² in 16² tiles
    CHECK_EQ(progress.done_tiles, progress.total_tiles);
    CHECK(job.error_message().empty());
    // A published result stays published: cancelling afterwards changes nothing.
    CHECK(!job.cancel());
    CHECK(job.status() == JobStatus::Success);
    CHECK(SerializeResult(job.result()) == SerializeResult(other.result()));
    CheckConservation(job.result());
    // The job owns copies of its meshes: the caller's may go away while it runs.
    JobHandle copied;
    {
        const BakeMesh temporary = fixtures::SphereOnGround(2, 8, 16);
        copied = baker.bake(SphereRequest(temporary, 7));
    }
    CHECK(copied.wait() == JobStatus::Success);
    CHECK(SerializeResult(copied.result()) == SerializeResult(other.result()));
}

/// A job cancelled while it runs ends in `Cancel` and publishes nothing; the hook holds the
/// first finished tile until the cancel request is made, so the order is fixed.
void CaseJobCancel() {
    for (std::uint32_t threads : {1u, 4u}) {
        std::promise<void> reached;
        std::promise<void> cancelled;
        std::shared_future<void> cancelled_future = cancelled.get_future().share();
        std::atomic<bool> first{true};
        BakerConfig config;
        config.on_tile_done = [&](std::uint32_t) {
            if (first.exchange(false)) {
                reached.set_value();
                cancelled_future.wait();
            }
        };
        EmbreeBaker baker(config);
        const BakeMesh low = fixtures::SphereOnGround(2, 8, 16);
        BakeRequest request = SphereRequest(low, 8);
        request.threads = threads;
        JobHandle job = baker.bake(request);
        reached.get_future().wait();
        CHECK(job.status() == JobStatus::Running);
        CHECK(job.cancel());
        cancelled.set_value();
        CHECK(job.wait() == JobStatus::Cancel);
        CHECK(!job.cancel());
        const std::string message = ExpectThrow<JobCancelled>([&] { (void)job.result(); });
        CHECK(Contains(message, "nothing was published"));
        CHECK(job.error_message().empty());
        const JobProgress progress = job.progress();
        CHECK_EQ(progress.total_tiles, 256u);
        if (threads == 1) CHECK_EQ(progress.done_tiles, 1u);  // the worker stopped at the next tile
        CHECK_EQ(baker.live_embree_objects(), 0);
    }
    // Dropping the handle of a running job cancels it and waits for it.
    {
        EmbreeBaker baker;
        const BakeMesh low = fixtures::SphereOnGround(2, 8, 16);
        JobHandle job = baker.bake(SphereRequest(low, 9));
        job = JobHandle();
        CHECK_EQ(baker.live_embree_objects(), 0);
    }
}

/// A job that fails while casting (a custom cage that meets its low part) ends in `Fail`,
/// publishes nothing and keeps the error.
void CaseJobFail() {
    EmbreeBaker baker;
    const BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);
    BakeRequest request = PlaneRequest(low);
    request.detail.cage_mode = CageMode::CustomFile;
    request.cage = {&low};
    JobHandle job = baker.bake(request);
    CHECK(job.wait() == JobStatus::Fail);
    CHECK(Contains(job.error_message(), "the cage of low part 'low' meets triangle"));
    ExpectThrow<ValueError>([&] { (void)job.result(); });
    CHECK(!job.cancel());
    CHECK_EQ(baker.live_embree_objects(), 0);
}

/// SUP-023 finding 1: a worker that cannot be started fails the job; the workers already started
/// are joined (no `std::terminate`) and nothing is published.
void CaseWorkerSpawnFailure() {
    const BakeMesh low = fixtures::SphereOnGround(2, 8, 16);
    BakeRequest request = SphereRequest(low, 7);
    for (std::uint32_t failing : {0u, 1u, 3u, 7u}) {
        BakerConfig config;
        config.faults.worker_spawn_failure = failing;
        EmbreeBaker baker(config);
        request.threads = 8;
        JobHandle job = baker.bake(request);
        CHECK(job.wait() == JobStatus::Fail);
        CHECK(Contains(job.error_message(), "injected failure creating bake worker " + std::to_string(failing)));
        ExpectThrow<std::system_error>([&] { (void)job.result(); });
        CHECK_EQ(baker.live_embree_objects(), 0);
        // One worker needs no spawn: the same baker still bakes.
        request.threads = 1;
        CHECK(baker.bake(request).wait() == JobStatus::Success);
    }
}

/// SUP-031: a throwing tile callback takes the tile's error path (the first in tile order fails
/// the job), at one worker and at several, never escaping a worker thread.
void CaseTileCallbackThrows() {
    const BakeMesh low = fixtures::SphereOnGround(2, 8, 16);
    BakeRequest request = SphereRequest(low, 7);
    for (std::uint32_t threads : {1u, 4u, 8u}) {
        BakerConfig config;
        config.on_tile_done = [](std::uint32_t tile) {
            if (tile == 5 || tile == 40) throw std::runtime_error("callback failed at tile " + std::to_string(tile));
        };
        EmbreeBaker baker(config);
        request.threads = threads;
        JobHandle job = baker.bake(request);
        CHECK(job.wait() == JobStatus::Fail);
        CHECK(job.error_message() == "callback failed at tile 5");
        ExpectThrow<std::runtime_error>([&] { (void)job.result(); });
        CHECK_EQ(job.progress().done_tiles, 64u);
        CHECK_EQ(baker.live_embree_objects(), 0);
    }
}

/// SUP-023 finding 2: an Embree acquisition that fails at any step releases everything acquired
/// before it (the live count returns to 0) and fails the job.
void CaseEmbreeAcquisitionFailure() {
    const BakeMesh low = fixtures::Plane("low", -1, 1, -1, 1, 0);
    const BakeMesh high = fixtures::Plane("high", -1, 1, -1, 1, 0);
    const BakeMesh box = fixtures::Box("box", 10.0f, true);
    BakeRequest request = PlaneRequest(low);
    request.detail.low_as_high = false;
    request.high = {&high, &box};
    // 1 scene + 2 meshes x (geometry, vertex buffer, index buffer) = 7 acquisitions.
    const char* expected[] = {"rtcNewScene", "rtcNewGeometry failed for mesh 'high'", "(vertices) failed for mesh 'high'",
                              "(indices) failed for mesh 'high'", "rtcNewGeometry failed for mesh 'box'",
                              "(vertices) failed for mesh 'box'", "(indices) failed for mesh 'box'"};
    for (std::uint32_t n = 0; n < 7; ++n) {
        BakerConfig config;
        config.faults.embree_acquisition_failure = n;
        EmbreeBaker baker(config);
        JobHandle job = baker.bake(request);
        CHECK(job.wait() == JobStatus::Fail);
        CHECK(Contains(job.error_message(), expected[n]));
        ExpectThrow<CapabilityError>([&] { (void)job.result(); });
        CHECK_EQ(baker.live_embree_objects(), 0);
    }
    BakerConfig config;
    config.faults.embree_acquisition_failure = 7;  // past the last acquisition: no failure
    EmbreeBaker baker(config);
    CHECK(baker.bake(request).wait() == JobStatus::Success);
    CHECK_EQ(baker.live_embree_objects(), 0);
}

// ── The bevelled cube with highs ─────────────────────────────────────────────────────────────

constexpr double kBevel = 0.15;
constexpr std::uint32_t kAtlasW = 128;
constexpr std::uint32_t kAtlasH = 64;
constexpr std::uint64_t kIslandTexels = 24 * 24;
constexpr double kInf = std::numeric_limits<double>::infinity();

/// How far below the cube face plane the chamfered cube's surface lies under the face point with
/// in-face coordinates (s, t); infinite where the face's straight-down ray misses the hull.
double ChamferDepth(double s, double t) {
    const double m = 1.0 - kBevel;
    s = std::abs(s);
    t = std::abs(t);
    if (s > 1.0 || t > 1.0) return kInf;
    if (s > m && t > m && s + t > 2.0 - kBevel) return kInf;
    return std::max(0.0, s - m) + std::max(0.0, t - m);
}

/// In-island coordinates in [-1, 1] of sub-sample (i, j) of texel (x, y) of cell `cell`.
void IslandCoords(std::uint32_t cell, std::uint32_t x, std::uint32_t y, std::uint32_t k, std::uint32_t i,
                  std::uint32_t j, double& s, double& t) {
    const double x0 = (cell % 4) * 32.0 + 4.0;
    const double y0 = (cell / 4) * 32.0 + 4.0;
    s = -1.0 + 2.0 * (x + (i + 0.5) / k - x0) / 24.0;
    t = 1.0 - 2.0 * (y + (j + 0.5) / k - y0) / 24.0;
}

bool InIsland(std::uint32_t cell, std::uint32_t x, std::uint32_t y) {
    const std::uint32_t x0 = (cell % 4) * 32 + 4;
    const std::uint32_t y0 = (cell / 4) * 32 + 4;
    return x >= x0 && x < x0 + 24 && y >= y0 && y < y0 + 24;
}

struct Bevel {
    BakeMesh cube_low = fixtures::LowCube("cube_low");
    BakeMesh knob_low = fixtures::KnobLow("knob_low");
    BakeMesh cube_high = fixtures::ChamferedCube("cube_high", kBevel);
    BakeMesh knob_high = fixtures::KnobHigh("knob_high_ignorebf");
    BakeMesh decoy = fixtures::Decoy("decoy_high");

    BakeRequest Request(float max_depth) const {
        BakeRequest request;
        request.texture_set = "bevelled_cube";
        request.input_revision = "fixture-r1";
        request.usages = {MeshMapUsage::AO};
        request.output_size_log2[0] = fixtures::kAtlasWidthLog2;
        request.output_size_log2[1] = fixtures::kAtlasHeightLog2;
        request.detail.low_as_high = false;
        request.detail.max_height = 0.05f;
        request.detail.max_depth = max_depth;
        request.detail.filter_method = FilterMethod::ByMeshName;
        request.ao.secondary_rays = 4;
        request.ao.min_distance = 1e-4f;
        request.ao.max_distance = 1.0f;
        request.low = {&cube_low, &knob_low};
        request.high = {&cube_high, &knob_high, &decoy};
        request.threads = 4;
        return request;
    }
};

/// Hits of one cube face's island at `max_depth` with k x k sub-samples, from `ChamferDepth`.
std::uint64_t ExpectedFaceHits(std::uint32_t k, double max_depth, std::uint64_t* hit_texels) {
    std::uint64_t hits = 0;
    *hit_texels = 0;
    for (std::uint32_t y = 4; y < 28; ++y) {
        for (std::uint32_t x = 4; x < 28; ++x) {
            std::uint32_t texel_hits = 0;
            for (std::uint32_t j = 0; j < k; ++j) {
                for (std::uint32_t i = 0; i < k; ++i) {
                    double s = 0, t = 0;
                    IslandCoords(0, x, y, k, i, j, s, t);
                    if (ChamferDepth(s, t) <= max_depth) ++texel_hits;
                }
            }
            hits += texel_hits;
            if (texel_hits > 0) ++*hit_texels;
        }
    }
    return hits;
}

/// Matching by name: each low part sees only its own high mesh; the decoy over the cube's top
/// matches nothing; `_ignorebf` lets the knob's rays through its cover. Per cube face 480
/// straight hits and 96 centre misses (the chamfer bands deeper than max_depth 0.04).
void CaseMatchByName() {
    EmbreeBaker baker;
    std::string message;
    Bevel fixture;
    const BakeRequest request = fixture.Request(0.04f);
    const BakeResult r = Bake(baker, request);
    CheckConservation(r);
    std::uint64_t hit_texels = 0;
    CHECK_EQ(ExpectedFaceHits(1, 0.04, &hit_texels), 480u);
    CHECK_EQ(r.texels.straight_hit, 6 * 480u + kIslandTexels);
    CHECK_EQ(r.texels.centre_miss, 6 * 96u);
    CHECK_EQ(r.texels.back_face_hit, 0u);
    CHECK_EQ(r.texels.uncovered, kAtlasW * kAtlasH - 7 * kIslandTexels);
    // Texel by texel on every cube face.
    for (std::uint32_t f = 0; f < 6; ++f) {
        for (std::uint32_t y = 0; y < kAtlasH; ++y) {
            for (std::uint32_t x = 0; x < kAtlasW; ++x) {
                if (!InIsland(f, x, y)) continue;
                double s = 0, t = 0;
                IslandCoords(f, x, y, 1, 0, 0, s, t);
                const bool hit = ChamferDepth(s, t) <= 0.04;
                CHECK_EQ(r.texel_class[y * kAtlasW + x],
                         static_cast<std::uint8_t>(hit ? TexelClass::StraightHit : TexelClass::CentreMiss));
            }
        }
    }
    // Without the suffix the knob's cover stops its rays: back-face hits.
    Bevel plain;
    plain.knob_high.name = "knob_high";
    const BakeResult covered = Bake(baker, plain.Request(0.04f));
    CheckConservation(covered);
    CHECK_EQ(covered.texels.back_face_hit, kIslandTexels);
    CHECK_EQ(covered.texels.straight_hit, 6 * 480u);
    // A low part whose name pairs with no high mesh: its texels are centre misses.
    Bevel orphan;
    orphan.knob_high.name = "other_high";
    const BakeResult unmatched = Bake(baker, orphan.Request(0.04f));
    CheckConservation(unmatched);
    CHECK_EQ(unmatched.texels.centre_miss, 6 * 96u + kIslandTexels);
    // Other suffixes: the same pairing.
    Bevel renamed;
    renamed.cube_low.name = "cube.lo";
    renamed.knob_low.name = "knob.lo";
    renamed.cube_high.name = "cube.hi";
    renamed.knob_high.name = "knob.hi#bf";
    BakeRequest custom = renamed.Request(0.04f);
    custom.detail.low_suffix = ".lo";
    custom.detail.high_suffix = ".hi";
    custom.detail.ignore_backface_suffix = "#bf";
    CHECK(SerializeResult(Bake(baker, custom)) == SerializeResult(r));
    // A name that is only a suffix is refused before any work.
    Bevel bare;
    bare.knob_high.name = "_high_ignorebf";
    message = ExpectThrow<NotYetSupported>([&] { baker.bake(bare.Request(0.04f)); });
    CHECK(Contains(message, "only a suffix"));
    bare = Bevel();
    bare.cube_low.name = "_low";
    ExpectThrow<NotYetSupported>([&] { baker.bake(bare.Request(0.04f)); });
}

/// `FilterMethod::Always`: every high mesh is a candidate, so the decoy's back face stops the
/// top face's rays and the knob's cover stops the knob's (the suffix is not read).
/// `IgnoreBackface` lets both through: the by-name result again.
void CaseMatchAlways() {
    EmbreeBaker baker;
    Bevel fixture;
    BakeRequest request = fixture.Request(0.04f);
    request.detail.filter_method = FilterMethod::Always;
    const BakeResult r = Bake(baker, request);
    CheckConservation(r);
    CHECK_EQ(r.texels.back_face_hit, 2 * kIslandTexels);
    CHECK_EQ(r.texels.straight_hit, 5 * 480u);
    CHECK_EQ(r.texels.centre_miss, 5 * 96u);
    for (std::uint32_t y = 0; y < kAtlasH; ++y) {
        for (std::uint32_t x = 0; x < kAtlasW; ++x) {
            if (InIsland(fixtures::kTopFace, x, y) || InIsland(6, x, y)) {
                CHECK_EQ(r.texel_class[y * kAtlasW + x], static_cast<std::uint8_t>(TexelClass::BackFaceHit));
            }
        }
    }
    request.detail.ignore_backface = true;
    const BakeResult ignored = Bake(baker, request);
    CheckConservation(ignored);
    const BakeResult by_name = Bake(baker, fixture.Request(0.04f));
    CHECK_EQ(ignored.texels.straight_hit, by_name.texels.straight_hit);
    CHECK(ignored.texel_class == by_name.texel_class);
}

/// `LowAsHigh` with name matching: each low part is its own high mesh. A lid part facing down
/// over the cube's top stops the top's rays (and the cube stops 16 x 16 of the lid's) unless
/// the parts are matched by name.
void CaseLowAsHighMatching() {
    EmbreeBaker baker;
    const BakeMesh cube = fixtures::LowCube("cube_low");
    Float2 uv0, uv1;
    fixtures::IslandUv(7, uv0, uv1);
    const BakeMesh lid = fixtures::Plane("lid_low", -1.5f, 1.5f, -1.5f, 1.5f, 1.02f, true, uv0, uv1);
    BakeRequest request = Bevel().Request(0.04f);
    request.detail.low_as_high = true;
    request.high.clear();
    request.low = {&cube, &lid};
    request.detail.filter_method = FilterMethod::Always;
    const BakeResult always = Bake(baker, request);
    CheckConservation(always);
    CHECK_EQ(always.texels.back_face_hit, kIslandTexels + 16 * 16);
    CHECK_EQ(always.texels.straight_hit, 6 * kIslandTexels - 16 * 16);
    request.detail.filter_method = FilterMethod::ByMeshName;
    const BakeResult by_name = Bake(baker, request);
    CheckConservation(by_name);
    CHECK_EQ(by_name.texels.back_face_hit, 0u);
    CHECK_EQ(by_name.texels.straight_hit, 7 * kIslandTexels);
}

/// A custom cage (the low cube scaled by 1.1, in memory): every texel's ray runs from the cage
/// through the low surface into the chamfered high and is a cage hit; the cage's topology is
/// checked before any work.
void CaseCustomCage() {
    EmbreeBaker baker;
    Bevel fixture;
    const BakeMesh cage = fixtures::LowCube("cube_cage", 1.1f);
    BakeRequest request = fixture.Request(1.0f);
    request.low = {&fixture.cube_low};
    request.high = {&fixture.cube_high};
    request.detail.cage_mode = CageMode::CustomFile;
    request.cage = {&cage};
    const BakeResult r = Bake(baker, request);
    CheckConservation(r);
    CHECK_EQ(r.texels.cage_hit, 6 * kIslandTexels);
    CHECK_EQ(r.texels.straight_hit, 0u);
    CHECK_EQ(r.subsamples.hit, 6 * kIslandTexels);
    // Too short a reach: the deepest chamfer texels become centre misses, not hits.
    request.detail.max_depth = 0.0f;
    const BakeResult shallow = Bake(baker, request);
    CheckConservation(shallow);
    CHECK(shallow.texels.centre_miss > 0);
    CHECK_EQ(shallow.texels.cage_hit + shallow.texels.centre_miss, 6 * kIslandTexels);
    // Refusals before any work.
    BakeMesh wrong = cage;
    wrong.indices.pop_back();
    wrong.indices.pop_back();
    wrong.indices.pop_back();
    request.cage = {&wrong};
    ExpectThrow<ValueError>([&] { baker.bake(request); });
    request.cage = {&cage, &cage};
    ExpectThrow<ValueError>([&] { baker.bake(request); });
    request.detail.cage_mode = CageMode::DistanceBased;
    request.cage = {&cage};
    ExpectThrow<ValueError>([&] { baker.bake(request); });
}

/// The hidden mask: the top face's island is covered but hidden; no ray is cast there.
void CaseHiddenMask() {
    EmbreeBaker baker;
    Bevel fixture;
    BakeRequest request = fixture.Request(0.04f);
    request.hidden_mask.assign(kAtlasW * kAtlasH, 0);
    for (std::uint32_t y = 0; y < kAtlasH; ++y) {
        for (std::uint32_t x = 0; x < kAtlasW; ++x) {
            // The top face's whole cell, so uncovered texels are marked too: they stay Uncovered.
            if (x < 32 && y >= 32) request.hidden_mask[y * kAtlasW + x] = 1;
        }
    }
    const BakeResult r = Bake(baker, request);
    CheckConservation(r);
    CHECK_EQ(r.texels.hidden, kIslandTexels);
    CHECK_EQ(r.subsamples.hidden, kIslandTexels);
    CHECK_EQ(r.texels.straight_hit, 5 * 480u + kIslandTexels);
    CHECK_EQ(r.texels.centre_miss, 5 * 96u);
    CHECK_EQ(r.texels.uncovered, kAtlasW * kAtlasH - 7 * kIslandTexels);
    CHECK_EQ(r.rays.escaped + r.rays.front_hit + r.rays.back_face_hit + r.rays.self_hit,
             (5 * 480u + kIslandTexels) * 4u);
}

/// `SubSampling` 2 x 2 on the bevelled cube: every sub-sample of an island texel is covered,
/// and which ones hit follows the chamfer depth under each sub-sample; a texel with at least one
/// hit is a straight hit whose value averages only its hit sub-samples.
void CaseSubsamplingBevel() {
    EmbreeBaker baker;
    Bevel fixture;
    BakeRequest request = fixture.Request(0.07f);
    request.detail.subsampling = 2;
    const BakeResult r = Bake(baker, request);
    CheckConservation(r);
    CHECK_EQ(r.subsampling, 2u);
    CHECK_EQ(r.subsamples.covered, 7 * kIslandTexels * 4);
    std::uint64_t hit_texels = 0;
    const std::uint64_t face_hits = ExpectedFaceHits(2, 0.07, &hit_texels);
    CHECK_EQ(r.subsamples.hit, 6 * face_hits + 4 * kIslandTexels);
    CHECK_EQ(r.subsamples.centre_miss, 6 * (4 * kIslandTexels - face_hits));
    CHECK_EQ(r.texels.straight_hit, 6 * hit_texels + kIslandTexels);
    for (std::uint32_t f = 0; f < 6; ++f) {
        for (std::uint32_t y = 0; y < kAtlasH; ++y) {
            for (std::uint32_t x = 0; x < kAtlasW; ++x) {
                if (!InIsland(f, x, y)) continue;
                std::uint32_t expected = 0;
                for (std::uint32_t j = 0; j < 2; ++j) {
                    for (std::uint32_t i = 0; i < 2; ++i) {
                        double s = 0, t = 0;
                        IslandCoords(f, x, y, 2, i, j, s, t);
                        if (ChamferDepth(s, t) <= 0.07) ++expected;
                    }
                }
                const std::size_t index = y * kAtlasW + x;
                CHECK_EQ(r.coverage[index], 4);
                CHECK_EQ(r.subsample_hits[index], expected);
            }
        }
    }
    // SubSampling 1 is the centre sample exactly: the default request's bytes.
    request.detail.subsampling = 1;
    BakeRequest plain = fixture.Request(0.07f);
    CHECK(SerializeResult(Bake(baker, request)) == SerializeResult(Bake(baker, plain)));
}

/// Coverage accumulation on a UV triangle's diagonal edge: one low triangle (0,0)-(1,0)-(0,1)
/// at 8 x 8 with 4 x 4 sub-samples; sub-sample (i, j) of texel (x, y) is covered exactly when
/// 4x + i <= 4y + j (edges included).
void CaseSubsamplingCoverage() {
    EmbreeBaker baker;
    BakeMesh low;
    low.name = "triangle";
    low.positions = {{0, 0, 0}, {1, 0, 0}, {0, 1, 0}};
    low.normals = {{0, 0, 1}, {0, 0, 1}, {0, 0, 1}};
    low.uvs = {{0, 0}, {1, 0}, {0, 1}};
    low.indices = {0, 1, 2};
    const BakeMesh high = fixtures::Plane("ground", -1, 2, -1, 2, 0);
    BakeRequest request = PlaneRequest(low);
    request.output_size_log2[0] = 3;
    request.output_size_log2[1] = 3;
    request.detail.low_as_high = false;
    request.high = {&high};
    request.detail.subsampling = 4;
    request.ao.secondary_rays = 2;
    const BakeResult r = Bake(baker, request);
    CheckConservation(r);
    std::uint64_t covered = 0, texels = 0;
    for (std::uint32_t y = 0; y < 8; ++y) {
        for (std::uint32_t x = 0; x < 8; ++x) {
            std::uint32_t expected = 0;
            for (std::uint32_t j = 0; j < 4; ++j) {
                for (std::uint32_t i = 0; i < 4; ++i) expected += 4 * x + i <= 4 * y + j ? 1 : 0;
            }
            CHECK_EQ(r.coverage[y * 8 + x], expected);
            CHECK_EQ(r.subsample_hits[y * 8 + x], expected);
            covered += expected;
            texels += expected > 0 ? 1 : 0;
        }
    }
    CHECK_EQ(r.subsamples.covered, covered);
    CHECK_EQ(r.subsamples.hit, covered);
    CHECK_EQ(r.texels.straight_hit, texels);
    std::printf("subsampling_coverage: %llu of 1024 sub-samples covered, %llu texels\n",
                static_cast<unsigned long long>(covered), static_cast<unsigned long long>(texels));
}

/// `DilationWidth` 8: RAW is unchanged, the used surface is unchanged, and exactly the
/// `Uncovered` texels within 8 steps (8-neighbourhood, through uncovered texels) of a hit texel
/// are written, each pass the rounded mean of its valued neighbours.
void CaseDilation() {
    EmbreeBaker baker;
    Bevel fixture;
    BakeRequest request = fixture.Request(0.12f);
    const BakeResult raw = Bake(baker, request);
    request.common.dilation_width = 8;
    const BakeResult r = Bake(baker, request);
    CheckConservation(r);
    CHECK(r.ao_raw == raw.ao_raw);
    CHECK(r.texel_class == raw.texel_class);
    CHECK(r.ao_raw == raw.ao);
    // The reference: a breadth-first pass of the same rule, written independently.
    const std::size_t n = kAtlasW * kAtlasH;
    std::vector<std::int32_t> step(n, -1);
    std::vector<std::uint16_t> expected = raw.ao_raw;
    std::vector<std::size_t> frontier;
    for (std::size_t i = 0; i < n; ++i) {
        if (IsHit(raw.texel_class[i])) step[i] = 0;
    }
    std::uint64_t written = 0;
    for (std::int32_t pass = 1; pass <= 8; ++pass) {
        std::vector<std::pair<std::size_t, std::uint16_t>> fresh;
        for (std::size_t i = 0; i < n; ++i) {
            if (step[i] >= 0 || raw.texel_class[i] != static_cast<std::uint8_t>(TexelClass::Uncovered)) continue;
            const int x = static_cast<int>(i % kAtlasW), y = static_cast<int>(i / kAtlasW);
            std::uint64_t sum = 0, count = 0;
            for (int dy = -1; dy <= 1; ++dy) {
                for (int dx = -1; dx <= 1; ++dx) {
                    const int nx = x + dx, ny = y + dy;
                    if ((dx == 0 && dy == 0) || nx < 0 || ny < 0 || nx >= static_cast<int>(kAtlasW) ||
                        ny >= static_cast<int>(kAtlasH)) {
                        continue;
                    }
                    const std::size_t j = static_cast<std::size_t>(ny) * kAtlasW + static_cast<std::size_t>(nx);
                    if (step[j] >= 0 && step[j] < pass) {
                        sum += expected[j];
                        ++count;
                    }
                }
            }
            if (count) fresh.emplace_back(i, static_cast<std::uint16_t>((sum + count / 2) / count));
        }
        for (const auto& [i, value] : fresh) {
            expected[i] = value;
            step[i] = pass;
        }
        written += fresh.size();
    }
    CHECK(r.ao == expected);
    CHECK_EQ(r.dilated_texels, written);
    // The unused cell 7 is reached only up to 8 texels from the knob's island (x < 100) and from
    // cell 3's island above it (y < 36).
    for (std::uint32_t y = 36; y < 64; ++y) {
        for (std::uint32_t x = 100; x < 128; ++x) CHECK_EQ(step[y * kAtlasW + x], -1);
    }
    std::printf("dilation: %llu texels written\n", static_cast<unsigned long long>(written));
}

/// The bevelled cube with every new path on (matching by name, `_ignorebf`, 4 x 4 sub-samples,
/// dilation 8, a hidden texel band), at 1, 4 and every hardware thread: identical bytes.
BakeRequest BevelDeterminismRequest(const Bevel& fixture, std::vector<std::uint8_t>& mask) {
    BakeRequest request = fixture.Request(0.07f);
    request.detail.subsampling = 4;
    request.common.dilation_width = 8;
    request.ao.secondary_rays = 16;
    mask.assign(kAtlasW * kAtlasH, 0);
    for (std::uint32_t x = 0; x < kAtlasW; ++x) mask[10 * kAtlasW + x] = 1;
    request.hidden_mask = mask;
    return request;
}

void CaseBevelThreadsInProcess() {
    EmbreeBaker baker;
    Bevel fixture;
    std::vector<std::uint8_t> mask;
    BakeRequest request = BevelDeterminismRequest(fixture, mask);
    std::string reference;
    for (std::uint32_t threads : {1u, 4u, std::max(1u, std::thread::hardware_concurrency())}) {
        request.threads = threads;
        const BakeResult r = Bake(baker, request);
        CheckConservation(r);
        CHECK(r.texels.hidden > 0 && r.dilated_texels > 0);
        const std::string bytes = SerializeResult(r);
        if (reference.empty()) {
            reference = bytes;
        } else {
            CHECK(bytes == reference);
        }
    }
}

// ── The parameter model ──────────────────────────────────────────────────────────────────────

void CaseParameters() {
    BakingParameters params("bevelled_cube");
    CHECK(params.texture_set() == "bevelled_cube");
    const auto common = params.common();
    const auto ao = params.baker(MeshMapUsage::AO);
    for (const char* key : {"OutputSize", "DilationWidth", "ApplyDiffusion", "HipolyMesh", "LowAsHigh", "CageMode",
                            "CageMesh", "MaxHeight", "MaxDepth", "RelativeScale", "SmoothNormals", "IgnoreBackface",
                            "FilterMethod", "LowpolySuffix", "HipolySuffix", "BackfaceCullingSuffix", "SubSampling",
                            "SkewFaceBehavior", "OffsetMap"}) {
        CHECK(common.count(key) == 1);
    }
    CHECK_EQ(common.size(), 19u);
    for (const char* key : {"NbSecondary", "MinDistance", "MaxDistance", "MaxDistanceRelativeScale", "Spread",
                            "Distribution", "IgnoreBackfaceSecondary", "FilterMethodSecondary", "Attenuation",
                            "GroundPlane", "GroundOffset"}) {
        CHECK(ao.count(key) == 1);
    }
    CHECK_EQ(ao.size(), 11u);
    for (const PropertySpec& spec : PropertySpecs()) CHECK(!spec.description.empty() && !spec.source.empty());
    // Every usage but AO names its owner baker task.
    std::string message = ExpectThrow<NotYetSupported>([&] { params.baker(MeshMapUsage::Curvature); });
    CHECK(Contains(message, "phase3.4_baker-curvature"));
    message = ExpectThrow<NotYetSupported>([&] { params.baker(MeshMapUsage::Normal); });
    CHECK(Contains(message, "phase3.2_baker-normal"));

    // Documented facts answer; the rest is pending, never guessed.
    const Property& suffix = common.at("LowpolySuffix");
    CHECK(std::get<std::string>(suffix.value()) == "_low");
    CHECK(std::get<std::string>(common.at("HipolySuffix").value()) == "_high");
    CHECK(std::get<std::string>(common.at("BackfaceCullingSuffix").value()) == "_ignorebf");
    CHECK(suffix.label() == "Low poly mesh suffix");
    CHECK(common.at("SubSampling").label() == "Antialiasing");
    CHECK(common.at("FilterMethod").documented_option_labels() == std::vector<std::string>({"Always", "By mesh name"}));
    message = ExpectThrow<NotYetSupported>([&] { (void)common.at("OutputSize").value(); });
    CHECK(Contains(message, "item 2.9"));
    message = ExpectThrow<NotYetSupported>([&] { (void)common.at("MaxHeight").label(); });
    CHECK(Contains(message, "items 2.8 and 3.1"));
    ExpectThrow<NotYetSupported>([&] { (void)suffix.name(); });
    ExpectThrow<NotYetSupported>([&] { (void)suffix.widget_type(); });
    ExpectThrow<NotYetSupported>([&] { (void)suffix.properties(); });
    ExpectThrow<NotYetSupported>([&] { (void)common.at("FilterMethod").enum_values(); });
    ExpectThrow<NotYetSupported>([&] { (void)common.at("FilterMethod").enum_value("Always"); });

    // set(): typed, one transaction.
    BakingParameters::set({{common.at("OutputSize"), std::pair<std::int64_t, std::int64_t>{11, 10}},
                           {common.at("FilterMethod"), EnumLabel{"By mesh name"}},
                           {common.at("HipolySuffix"), std::string("_hi")},
                           {ao.at("GroundPlane"), true},
                           {ao.at("Distribution"), EnumLabel{"Cosine"}}});
    CHECK((std::get<std::pair<std::int64_t, std::int64_t>>(common.at("OutputSize").value()) ==
           std::pair<std::int64_t, std::int64_t>{11, 10}));
    CHECK(std::get<std::string>(common.at("HipolySuffix").value()) == "_hi");
    CHECK(std::get<bool>(ao.at("GroundPlane").value()));
    CHECK(std::get<EnumLabel>(params.common().at("FilterMethod").value()).label == "By mesh name");
    const auto unchanged = [&] {
        CHECK(std::get<EnumLabel>(common.at("FilterMethod").value()).label == "By mesh name");
        ExpectThrow<NotYetSupported>([&] { (void)common.at("DilationWidth").value(); });
    };
    // A wrong type, an unknown option of a complete list, a pending type and an undocumented
    // option each refuse the whole batch.
    ExpectThrow<ValueError>([&] {
        BakingParameters::set({{common.at("DilationWidth"), std::int64_t{8}}, {common.at("FilterMethod"), true}});
    });
    unchanged();
    ExpectThrow<ValueError>([&] {
        BakingParameters::set({{common.at("DilationWidth"), std::int64_t{8}},
                               {common.at("FilterMethod"), EnumLabel{"Sometimes"}}});
    });
    unchanged();
    message = ExpectThrow<NotYetSupported>([&] {
        BakingParameters::set({{common.at("DilationWidth"), std::int64_t{8}}, {common.at("SmoothNormals"), true}});
    });
    CHECK(Contains(message, "value type of SmoothNormals"));
    unchanged();
    ExpectThrow<NotYetSupported>([&] {
        BakingParameters::set({{common.at("DilationWidth"), std::int64_t{8}},
                               {ao.at("Distribution"), EnumLabel{"Uniform"}}});
    });
    unchanged();
    ExpectThrow<ValueError>([&] {
        BakingParameters::set({{common.at("DilationWidth"), std::int64_t{8}}, {common.at("DilationWidth"), std::int64_t{9}}});
    });
    unchanged();
    // A type only the key's meaning suggests (a distance) stays pending.
    message = ExpectThrow<NotYetSupported>([&] {
        BakingParameters::set({{common.at("DilationWidth"), std::int64_t{8}}, {ao.at("MaxDistance"), 2.0}});
    });
    CHECK(Contains(message, "value type of MaxDistance"));
    unchanged();
    ExpectThrow<ValueError>([&] {
        BakingParameters::set({{common.at("DilationWidth"), std::int64_t{8}}, {common.at("LowAsHigh"), 1.0}});
    });
    unchanged();
    // Across texture sets: one failure leaves both unchanged.
    BakingParameters second("second");
    const auto second_common = second.common();
    ExpectThrow<ValueError>([&] {
        BakingParameters::set({{second_common.at("IgnoreBackface"), true}, {common.at("IgnoreBackface"), std::int64_t{1}}});
    });
    ExpectThrow<NotYetSupported>([&] { (void)second_common.at("IgnoreBackface").value(); });
    BakingParameters::set({{second_common.at("IgnoreBackface"), true}});
    CHECK(std::get<bool>(second.common().at("IgnoreBackface").value()));
    ExpectThrow<NotYetSupported>([&] { (void)common.at("IgnoreBackface").value(); });
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
        {"build_threads_diagnostic", CaseBuildThreadsDiagnostic},
        {"threads_in_process", CaseThreadsInProcess},
        {"job_async", CaseJobAsync},
        {"job_cancel", CaseJobCancel},
        {"job_fail", CaseJobFail},
        {"worker_spawn_failure", CaseWorkerSpawnFailure},
        {"embree_acquisition_failure", CaseEmbreeAcquisitionFailure},
        {"tile_callback_throws", CaseTileCallbackThrows},
        {"match_by_name", CaseMatchByName},
        {"match_always", CaseMatchAlways},
        {"low_as_high_matching", CaseLowAsHighMatching},
        {"custom_cage", CaseCustomCage},
        {"hidden_mask", CaseHiddenMask},
        {"subsampling_bevel", CaseSubsamplingBevel},
        {"subsampling_coverage", CaseSubsamplingCoverage},
        {"dilation", CaseDilation},
        {"bevel_threads_in_process", CaseBevelThreadsInProcess},
        {"parameters", CaseParameters},
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
    const TexelClassCounts& t = r.texels;
    const SubsampleCounts& s = r.subsamples;
    return "{\"fixture\":\"" + fixture + "\",\"width\":" + u(r.width) + ",\"height\":" + u(r.height) +
           ",\"rays_per_texel\":" + u(r.rays_per_texel) + ",\"subsampling\":" + u(r.subsampling) +
           ",\"dilation_width\":" + u(r.dilation_width) + ",\"threads_used\":" + u(r.threads_used) +
           ",\"embree_build_threads\":" + u(embree_threads) + ",\"qualified\":" + (caps.qualified ? "true" : "false") +
           ",\"diagnostic\":" + (r.diagnostic_unqualified ? "true" : "false") + ",\"embree_version\":\"" +
           caps.embree_version + "\",\"isa\":\"" + caps.isa + "\",\"tasking\":\"" + caps.tasking_system +
           "\",\"parity_status\":\"" + caps.parity_status + "\",\"sha256\":\"" + sha +
           "\",\"texels\":{\"uncovered\":" + u(t.uncovered) + ",\"straight_hit\":" + u(t.straight_hit) +
           ",\"back_face_hit\":" + u(t.back_face_hit) + ",\"centre_miss\":" + u(t.centre_miss) +
           ",\"cage_hit\":" + u(t.cage_hit) + ",\"hidden\":" + u(t.hidden) + "},\"subsamples\":{\"covered\":" +
           u(s.covered) + ",\"hit\":" + u(s.hit) + ",\"back_face_hit\":" + u(s.back_face_hit) +
           ",\"centre_miss\":" + u(s.centre_miss) + ",\"hidden\":" + u(s.hidden) + "},\"rays\":{\"escaped\":" +
           u(r.rays.escaped) + ",\"front_hit\":" + u(r.rays.front_hit) + ",\"back_face_hit\":" +
           u(r.rays.back_face_hit) + ",\"self_hit\":" + u(r.rays.self_hit) + "},\"dilated_texels\":" +
           u(r.dilated_texels) + "}";
}

/// The `bake` command's fixtures: `scene` (the sphere on the ground at 256², 64 rays, low as
/// high), `scene_self` (the same with min_distance 0, where self hits occur) and `bevel` (the
/// bevelled cube with highs and every path of decision 306 on).
int BakeCommand(int argc, char** argv) {
    if (argc < 4) throw ValueError("bake needs <fixture> <threads>");
    const std::string fixture = argv[2];
    const auto threads = static_cast<std::uint32_t>(std::stoul(argv[3]));
    std::uint32_t embree_threads = kQualifiedEmbreeBuildThreads;
    bool diagnostic = false;
    std::string out;
    for (int i = 4; i < argc; ++i) {
        const std::string arg = argv[i];
        if (arg == "--embree-build-threads" && i + 1 < argc) {
            embree_threads = static_cast<std::uint32_t>(std::stoul(argv[++i]));
        } else if (arg == "--diagnostic") {
            diagnostic = true;
        } else if (arg == "--out" && i + 1 < argc) {
            out = argv[++i];
        } else {
            throw ValueError("unknown argument " + arg);
        }
    }
    BakerConfig config;
    config.embree_build_threads = embree_threads;
    config.allow_unqualified_build_threads_diagnostic = diagnostic;
    EmbreeBaker baker(config);
    const BakeMesh sphere = fixtures::SphereOnGround();
    const Bevel bevel;
    std::vector<std::uint8_t> mask;
    BakeRequest request;
    if (fixture == "scene" || fixture == "scene_self") {
        request = SphereRequest(sphere, 8);
        request.texture_set = fixture;
        request.ao.secondary_rays = 64;
        request.ao.min_distance = fixture == "scene" ? 1e-4f : 0.0f;
    } else if (fixture == "bevel") {
        request = BevelDeterminismRequest(bevel, mask);
    } else {
        throw ValueError("unknown fixture " + fixture);
    }
    request.threads = threads;
    const BakeResult r = BakeAndWait(baker, request);
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
    if (argc >= 2 && std::string(argv[1]) == "bake") return BakeCommand(argc, argv);
    std::fprintf(stderr, "usage: uzp-bake-feasibility-tests run [case] | bake <fixture> <threads> "
                         "[--embree-build-threads K] [--diagnostic] [--out FILE]\n");
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
