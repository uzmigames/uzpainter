#pragma once

// The compositor's Phase 1 support boundary as a check before mutation (decisions 081, 082;
// `docs/architecture/10-python-api.md` §3, `04-layer-stack-and-compositing.md` §2). A request that
// adds or changes a node using a feature outside the implemented subset fails with
// `core::NotYetSupported` before anything is committed; the message names the node, the feature
// and the task that owns it. The features are those `tools/capabilities/compositor-capabilities.json`
// lists as `release-gap`: the kinds, sources and projections the evaluator refuses
// (`unsupported_*`, whose API class is also `NotYetSupported`, `ErrorClassName`) and the ones it
// evaluates without a Tier 0 golden (instance layers, `Mesh` geometry masks, the one-axis wrap
// modes, content-stack fill effects, mask-stack levels, SignedAddition and uniform colours on
// Height). Refusals that need decoded bitmaps or the virtual normal maps (bilinear minification,
// height-to-normal resolutions) are raised by the evaluation request, with the same class, before
// any tile is allocated.

#include <optional>
#include <string>

#include "uzp_core/types/project.h"

namespace uzp::evaluator {

/// A release gap a node uses: the feature and its owner task.
struct SupportGap {
    core::Id node = core::kNoId;
    std::string feature;
    std::string owner;

    /// `node=<uid>: <feature> is a release gap (<owner>)`.
    [[nodiscard]] std::string Describe() const;
};

/// The first release gap of the node `uid` of `project` (a layer, or an effect of a content or
/// mask stack), or nullopt when the node lies inside the supported subset or does not exist.
[[nodiscard]] std::optional<SupportGap> NodeGap(const core::Project& project, core::Id uid);

/// The first release gap `after` introduces relative to `before`: a colour-management mode other
/// than legacy, then every created or modified node in ascending id order. Nodes the request does
/// not touch are not checked, so a project that already holds a gap stays editable elsewhere.
[[nodiscard]] std::optional<SupportGap> FirstNewGap(const core::Project& before, const core::Project& after);

/// Throws `core::NotYetSupported` with `FirstNewGap(before, after)` when there is one. An API call
/// runs it on its transaction's working copy (`Edit::base()`, `Edit::project()`), so a refused
/// request commits nothing.
void RequireSupported(const core::Project& before, const core::Project& after);

}  // namespace uzp::evaluator
