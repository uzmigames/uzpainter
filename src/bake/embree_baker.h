#pragma once

// `EmbreeBaker`, the CPU baker of phase3.1_baker-request-model (`docs/architecture/06-baking.md`
// §1-§4, decisions 302 and 306): a deterministic ray-cast core on the vendored Embree 4.4.1 and
// the AO usage on it, behind `IBaker`.
//
// Determinism: the BVH is built by one Embree thread; texels are cast in fixed 16 x 16 tiles that
// any number of workers take in any order, each texel's sub-samples and rays are addressed by
// texel index, sub-sample and sample id (`sampling.h`) and reduced in sample order in integers,
// the per-tile counts are summed in tile order and dilation runs serially after the cast. The
// output bytes therefore do not depend on the worker count.
// Miss classes are kept: every texel has a `TexelClass`, every sub-sample and every secondary ray
// a class; nothing inside the used surface is filled, dilated or repaired.

#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <string>

#include "bake/bake_request.h"
#include "bake/baker.h"
#include "bake/embree_api.h"

namespace uzp::bake {

/// The CPU features the qualified ISA (Embree's AVX2 kernels) needs.
struct CpuFeatures {
    bool avx2 = false;
    bool fma = false;
    bool bmi1 = false;
    bool bmi2 = false;
    bool lzcnt = false;
    bool f16c = false;
    bool os_ymm = false;  // the OS saves the YMM state (OSXSAVE and XCR0 bits 1-2)
};

CpuFeatures DetectCpuFeatures();

/// Why `features` cannot run the qualified ISA; empty when it can.
std::string UnqualifiedIsaReason(const CpuFeatures& features);

/// Deterministic failure seams for tests (decision 306): nothing here is set in production.
struct FaultInjection {
    /// Creating the worker thread with this index (0-based, workers beyond the first) throws
    /// `std::system_error`, as an exhausted OS would.
    std::optional<std::uint32_t> worker_spawn_failure;
    /// The Embree acquisition with this index (0-based, per bake, in order: `rtcNewScene`, then
    /// per high mesh `rtcNewGeometry` and its vertex and index buffers) returns null.
    std::optional<std::uint32_t> embree_acquisition_failure;
};

/// The serial BVH build decision 302 qualifies.
inline constexpr std::uint32_t kQualifiedEmbreeBuildThreads = 1;

struct BakerConfig {
    /// Threads Embree uses to build the BVH (device `threads=`). Only 1 is qualified; any other
    /// value leaves the baker unqualified (decision 306).
    std::uint32_t embree_build_threads = kQualifiedEmbreeBuildThreads;
    /// Lets a baker that is unqualified only by `embree_build_threads` bake anyway, every result
    /// marked `diagnostic_unqualified` (the measurement path of decision 302 §1).
    bool allow_unqualified_build_threads_diagnostic = false;
    /// Replaces `DetectCpuFeatures()` (tests of the capability error).
    std::optional<CpuFeatures> cpu_features;
    FaultInjection faults;
    /// Called by the worker after each tile it finishes (tests of cancellation).
    std::function<void(std::uint32_t tile)> on_tile_done;
};

inline constexpr std::uint32_t kTileSize = 16;
inline constexpr std::uint32_t kMaxOutputSizeLog2 = 12;
// The Embree pin lives in build.zig (`bake_flags`, item 2.1, decision 311).
#if !defined(UZP_EMBREE_PINNED_VERSION) || !defined(UZP_EMBREE_PINNED_ISA) || !defined(UZP_EMBREE_PINNED_TASKING)
#error "src/bake is built with build.zig's bake_flags, which pin the Embree package"
#endif
inline constexpr const char* kQualifiedIsa = UZP_EMBREE_PINNED_ISA;
/// Embree's RTC_DEVICE_PROPERTY_VERSION of the pinned release.
inline constexpr long kPinnedEmbreeVersion = UZP_EMBREE_PINNED_VERSION;
/// Embree's RTC_DEVICE_PROPERTY_TASKING_SYSTEM of the pinned package (1 = TBB).
inline constexpr long kPinnedEmbreeTasking = UZP_EMBREE_PINNED_TASKING;

class EmbreeBaker final : public IBaker {
public:
    /// Never throws for an unqualified configuration: `caps().qualified` is false and `bake`
    /// raises `CapabilityError` before any work.
    explicit EmbreeBaker(BakerConfig config = {});
    ~EmbreeBaker() override;
    EmbreeBaker(const EmbreeBaker&) = delete;
    EmbreeBaker& operator=(const EmbreeBaker&) = delete;

    Capabilities caps() const override { return caps_; }

    /// Raises `CapabilityError` (unqualified machine, Embree build, usage, size or the
    /// `Automatic` cage release gap), `uzp::core::NotYetSupported` (`ApplyDiffusion`, a relative
    /// distance without a box size metric) or `uzp::core::ValueError` (invalid request, mesh, unit
    /// scale or bounds; a custom cage without one cage per low part) before any
    /// work; otherwise copies the request's meshes and starts the job. A job fails on vertex
    /// normals or a cage that cancel under a texel, an Embree failure or a worker that cannot
    /// be started: `Fail`, and no result.
    JobHandle bake(const BakeRequest& request) override;

    /// Embree scenes and geometries this baker holds right now (every bake releases its own).
    std::int64_t live_embree_objects() const;

    struct Core;

private:
    BakerConfig config_;
    Capabilities caps_;
    std::shared_ptr<Core> core_;
};

}  // namespace uzp::bake
