#pragma once

// The evaluation DAG of one (texture set, stack, channel) (docs/architecture/04-layer-stack-and-
// compositing.md §2, §7): built from a revision snapshot, independent of tiles, with the subtree
// hash of every node output, so that the cache (admission.h) serves unchanged subtrees and only
// what changed is re-evaluated.
//
// Order (04 §2): the accumulator starts at the channel's base value; root layers are walked
// bottom-up (storage keeps Painter's top-first order); an invisible layer or a layer in `Disable`
// for the channel is skipped; a fill layer contributes its source for the channel when the
// channel is active on it; a group composites its visible children from a transparent start
// into an isolated intermediate and that intermediate is blended with the group's mode and
// opacity (Painter's default group mode behaves so, Tier 0 `group-masks`: the default-mode group
// equals the `Normal` group texel for texel); a `PassThrough` group composites its children
// directly into the accumulator (the children's opacities scaled by the group's; a documented
// mode that Painter 12.1.0's API cannot set, so a hypothesis until phase0.7_tier0-semantics-ui-
// cases records it); an instance layer evaluates its source layer in its own position.
//
// Outside this profile (explicit `evaluator:unsupported_*` failures, the capability manifest's
// release gaps): paint layers, content and mask effects, geometry masks, `Material` source mode,
// procedural, vector, font and reference sources, the non-separable and normal-map blend modes.

#include "evaluator/formats.h"
#include "evaluator/hash.h"
#include "evaluator/templates.h"
#include "render/backend.h"

#include <array>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "uzp_core/types/enums.h"
#include "uzp_core/types/ids.h"
#include "uzp_core/types/layers.h"
#include "uzp_core/types/project.h"

namespace uzp::evaluator {

/// The evaluator profile this build implements (parity/semantics/evaluator-profile.json,
/// provisional): per-layer quantisation to the channel format, sRGB8 blended on linear values.
inline constexpr std::string_view kEvaluatorProfile = "painter-12.1-layerq-linear";

/// What a fill layer contributes to the channel.
struct DagSource {
    enum class Kind : uint8_t { Uniform, Bitmap };
    Kind kind = Kind::Uniform;
    /// Uniform: the colour as the channel stores it, read back as an operand (blend-modes.json
    /// `uniform_operand`; a grey channel takes the mean of the three components).
    std::array<float, 3> uniform{0.0f, 0.0f, 0.0f};
    /// Bitmap: the resource hash.
    std::string sha256;
    /// Hash of the content (source, channel, format, profile).
    Digest hash{};
};

struct DagList;

struct DagLayer {
    /// The layer the content belongs to (the instanced layer for an instance).
    core::Id uid = core::kNoId;
    core::BlendingMode mode = core::BlendingMode::Normal;
    float opacity = 1.0f;
    /// The constant mask: 1 without a mask or with a disabled one, the background of an empty
    /// mask stack (White 1, Black 0).
    float mask = 1.0f;
    std::optional<DagSource> source;   ///< Fill layer.
    std::unique_ptr<DagList> group;    ///< Group (isolated intermediate).
    /// Hash of this layer's contribution (content, mode, opacity, mask).
    Digest hash{};
    /// Hash of the accumulator after this layer (chained from the list start).
    Digest prefixHash{};
};

/// A layer list: the stack's root layers or a group's children, bottom-up, only the layers that
/// contribute to the channel.
struct DagList {
    /// The stack id (root list) or the group uid.
    core::Id owner = core::kNoId;
    /// Composited from a transparent start (a group) or from the channel base (the root).
    bool isolated = false;
    std::vector<DagLayer> layers;
    /// Hash of the start of the chain.
    Digest startHash{};
};

struct ChannelDag {
    core::Id textureSet = core::kNoId;
    core::Id stack = core::kNoId;
    core::ChannelType channel = core::ChannelType::BaseColor;
    core::ChannelFormat format = core::ChannelFormat::sRGB8;
    TileFormat tileFormat;
    /// The channel's base value (template), the backdrop of the bottom layer and the result of
    /// an empty stack.
    std::array<float, 3> base{0.0f, 0.0f, 0.0f};
    TileGrid grid;
    std::string templateId;
    DagList root;
};

/// Builds the DAG of `channel` of `stack` of `textureSet` in `project`, with the base values of
/// `templateId`. Fails with `evaluator:not_found`, `unknown_template`, `missing_base_value`,
/// `unsupported_node`, `unsupported_source` or `unsupported_blend_mode`.
[[nodiscard]] render::Result<ChannelDag> BuildDag(const core::Project& project,
                                                  core::Id textureSet, core::Id stack,
                                                  core::ChannelType channel,
                                                  const TemplateLibrary& templates,
                                                  std::string_view templateId);

/// The operand of a uniform colour on a channel of `format` with base `base` (blend-modes.json
/// `uniform_operand`): each component (the mean of the three on a grey channel) stored with the
/// channel's write rule and read back.
[[nodiscard]] std::array<float, 3> UniformOperand(const std::array<double, 3>& colour,
                                                  const TileFormat& format,
                                                  const std::array<float, 3>& base);

}  // namespace uzp::evaluator
