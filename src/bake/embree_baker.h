#pragma once

// `EmbreeBaker`, the CPU baker of the feasibility slice of phase3.1_baker-request-model
// (`docs/architecture/06-baking.md` §1-§4, decision 302): a deterministic ray-cast core on the
// vendored Embree 4.4.1 and the AO usage on it.
//
// Determinism: the BVH is built by one Embree thread; texels are cast in fixed 16 x 16 tiles that
// any number of workers take in any order, each texel's rays are addressed by texel index and
// sample id (`sampling.h`) and reduced in sample order in integers, and the per-tile counts are
// summed in tile order. The output bytes therefore do not depend on the worker count.
// Miss classes are kept: every texel has a `TexelClass` and every secondary ray a class of
// `RayClassCounts`; nothing is filled, dilated or repaired.

#include <cstdint>
#include <optional>
#include <string>

#include "bake/bake_request.h"
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

struct BakerConfig {
    /// Threads Embree uses to build the BVH (device `threads=`). Decision 302 pins 1.
    std::uint32_t embree_build_threads = 1;
    /// Replaces `DetectCpuFeatures()` (tests of the capability error).
    std::optional<CpuFeatures> cpu_features;
};

inline constexpr std::uint32_t kTileSize = 16;
inline constexpr std::uint32_t kMaxOutputSizeLog2 = 12;
inline constexpr const char* kQualifiedIsa = "avx2";
/// Embree's RTC_DEVICE_PROPERTY_VERSION of the pinned release.
inline constexpr long kPinnedEmbreeVersion = 40401;

class EmbreeBaker {
public:
    /// Never throws for an unqualified configuration: `caps().qualified` is false and `bake`
    /// raises `CapabilityError` before any work.
    explicit EmbreeBaker(BakerConfig config = {});
    ~EmbreeBaker();
    EmbreeBaker(const EmbreeBaker&) = delete;
    EmbreeBaker& operator=(const EmbreeBaker&) = delete;

    const Capabilities& caps() const { return caps_; }

    /// Bakes `request` synchronously. Raises `CapabilityError` (unqualified machine, usage,
    /// size or the `Automatic` cage release gap), `uzp::core::NotYetSupported` (custom cage) or
    /// `uzp::core::ValueError` (invalid request or mesh) before any ray is cast. Vertex normals
    /// that cancel under a texel are found while casting: `ValueError`, and no result.
    BakeResult bake(const BakeRequest& request);

private:
    BakerConfig config_;
    Capabilities caps_;
    const EmbreeApi* api_ = nullptr;
    RTCDevice device_ = nullptr;
};

}  // namespace uzp::bake
