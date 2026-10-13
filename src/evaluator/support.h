#pragma once

// The compositor's Phase 1 support boundary as a check before mutation (decisions 081, 082;
// `docs/architecture/10-python-api.md` §3, `04-layer-stack-and-compositing.md` §2). A request that
// adds or changes a node using a feature outside the implemented subset fails with
// `core::NotYetSupported` before anything is committed; the message names the node, the feature
// and the task that owns it. The features are those `tools/capabilities/compositor-capabilities.json`
// lists as `release-gap`: the kinds, sources and projections the evaluator refuses
// (`unsupported_*`, whose API class is also `NotYetSupported`, `ErrorClassName`) and the ones it
// evaluates without a Tier 0 golden (instance layers, `Mesh` geometry masks, the one-axis wrap
// modes, content-stack fill effects, mask-stack levels, a DirectX project's Normal channel beyond
// one bitmap fill at opacity 1). Under OCIO with Painter's substance config the bitmap uses
// Session O records also need the image's kind and size (sources.h `OcioBitmapRecorded`): given a
// reader of PNG headers, the check refuses them from the header before mutation, as the
// evaluation would (decision 240), in the nodes a request touches and in every node of a texture
// set whose resolution or channels it changes. Both relate a node to its set, which a native
// Transaction may change in either order (a resize and a rebind to the new size): only the state
// that commits is checked, so a call inside one runs the check without the reader and its commit
// runs it with the reader (python/session.cpp). Other refusals that need decoded bitmaps, the whole
// stack or the virtual normal maps (legacy bilinear minification outside the texture unit's
// measured domain, the legacy image rules of sources.h, height-to-normal resolutions, Normal mesh
// maps, several DirectX Normal layers) are raised by the evaluation request, with the same class,
// before any tile is allocated.

#include <functional>
#include <optional>
#include <string>
#include <string_view>

#include "evaluator/sources.h"
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

/// The shape of a resource's PNG by its SHA-256 (`BitmapShapeOf` of its bytes), or nullopt when its
/// bytes are not at hand. An empty reader checks no image and no set change: the check of a call
/// inside a native Transaction, whose commit checks them.
using BitmapShapes = std::function<std::optional<BitmapShape>(std::string_view sha256)>;

/// The first release gap of the node `uid` of `project` (a layer, or an effect of a content or
/// mask stack), or nullopt when the node lies inside the supported subset or does not exist. With
/// `shapes`, under OCIO a bitmap whose image is not a use Session O records is a gap too.
[[nodiscard]] std::optional<SupportGap> NodeGap(const core::Project& project, core::Id uid,
                                                const BitmapShapes& shapes = {});

/// The first release gap `after` introduces relative to `before`: a colour-management mode other
/// than legacy, then every created or modified node in ascending id order, then, with `shapes`
/// under OCIO, an OCIO bitmap use that a change of a texture set's resolution or channels makes
/// unrecorded in a node the request does not touch (a use that was recorded before). Other nodes
/// the request does not touch are not checked, so a project that already holds a gap stays
/// editable elsewhere.
[[nodiscard]] std::optional<SupportGap> FirstNewGap(const core::Project& before, const core::Project& after,
                                                    const BitmapShapes& shapes = {});

/// Throws `core::NotYetSupported` with `FirstNewGap(before, after, shapes)` when there is one. An
/// API call runs it on its transaction's working copy (`Edit::base()`, `Edit::project()`), so a
/// refused request commits nothing; a native Transaction runs it with `shapes` once more on its
/// final working copy before it commits.
void RequireSupported(const core::Project& before, const core::Project& after, const BitmapShapes& shapes = {});

}  // namespace uzp::evaluator
