#pragma once

// Evaluator profiles (docs/architecture/04-layer-stack-and-compositing.md §4; ARC-04, PRJ-05,
// NFR-02, NFR-08): the quantisation points and blend spaces a project is evaluated with. Every
// project records its profile id (`versions.evaluator_profile`, `painter-12.1-<profile-id>`) and
// is evaluated with that profile, never with a newer one: a later profile gets a new id and the
// old one stays registered, so old projects keep their exports (parity/semantics/
// quantisation-profile.json states the measured profile and its residuals).
//
// Rules every profile of this build shares (arith.h): fp32 intermediates (integers only where
// the storage format is integer and the operation exactly representable), no FP16 substitute
// for 16-bit storage, the channel format's write rule after every layer, sRGB8 channels blended
// on the linear values of the recording GPU's sRGB8 conversions, no fast-math.

#include "render/backend.h"

#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace uzp::evaluator {

/// Where the root layers of a stack meet the channel's base value.
enum class RootComposite : uint8_t {
    /// Each root layer blends onto an accumulator that starts at the base and is stored in the
    /// channel format; a 32-bit float channel is re-composited over its base once at read-out
    /// (`1 + (v - 1)`). Profile painter-12.1-layerq-linear (provisional, superseded).
    OverBase,
    /// The root layers composite from a transparent start into an isolated intermediate, like a
    /// group: colour and coverage stored in the channel format after every layer. That
    /// intermediate is composited over the base once at read-out, `v = base + (C - base) a` (the
    /// `Replace` mix of arith::Composite at opacity 1), and stored with the channel's write rule.
    /// Profiles painter-12.1-isolated-linear and painter-12.1-isolated-half-alpha
    /// (quantisation-profile.json).
    Isolated,
};

struct EvaluatorProfile {
    std::string id;
    RootComposite root = RootComposite::Isolated;
    /// The coverage plane of an sRGB8 intermediate is written as the 8-bit UNORM code of its
    /// binary16 value (round to nearest even), not of its float32 value: the recording GPU
    /// passes the outputs of sRGB8 targets through binary16 (Tier 0 `group-masks` s2-s3: a
    /// coverage half-way between two codes is stored up or down as its binary16 value lies).
    /// Profile painter-12.1-isolated-half-alpha (quantisation-profile.json).
    bool srgb8HalfCoverage = false;
    /// A uniform colour on a 32-bit float channel is the float32 of the value. Without it the
    /// value is read back re-composited over the channel base, `1 + (v - 1)`, the rule of the
    /// earlier profiles (`group-masks` row 0 shows the plain value).
    bool float32UniformPlain = false;
};

/// The first, provisional profile (evaluator-profile.json): stamped into projects before the
/// quantisation experiment settled the profile; still registered and evaluated as it was.
inline constexpr std::string_view kProfileLayerqLinear = "painter-12.1-layerq-linear";
/// The profile the quantisation experiment settled (quantisation-profile.json); superseded by
/// painter-12.1-isolated-half-alpha, still registered and evaluated as it was.
inline constexpr std::string_view kProfileIsolatedLinear = "painter-12.1-isolated-linear";
/// The isolated root with the sRGB8 coverage written through binary16 and plain 32-bit float
/// uniform colours (phase1.10_compositor-float32-residual, quantisation-profile.json).
inline constexpr std::string_view kProfileIsolatedHalfAlpha = "painter-12.1-isolated-half-alpha";
/// The profile new projects are stamped with.
inline constexpr std::string_view kCurrentProfile = kProfileIsolatedHalfAlpha;

/// The registered profile `id`; `evaluator:unknown_profile` when the build has none of that id
/// (a project from a newer build, a typo, an empty field).
[[nodiscard]] render::Result<EvaluatorProfile> FindProfile(std::string_view id);

/// Registers a profile next to the built-in ones (a later profile of the build, a test's
/// synthetic one). Fails with `evaluator:invalid_profile` when the id does not have the form
/// `painter-12.1-<profile-id>` or is registered already: a registered id never changes meaning.
[[nodiscard]] render::Result<void> RegisterProfile(EvaluatorProfile profile);

/// The ids of every registered profile, built-in first, in registration order.
[[nodiscard]] std::vector<std::string> RegisteredProfiles();

}  // namespace uzp::evaluator
