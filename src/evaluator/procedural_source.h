#pragma once

#include <memory>
#include <string>

#include "evaluator/tile_store.h"
#include "uzp_core/types/project.h"

namespace uzp::evaluator {

/// An admitted raw procedural output, never a projected bitmap. Provenance names
/// its project plane; the raster digest is not a resource hash.
struct ProceduralImage {
    DecodedImage image;
    std::string signature;
    std::string rasterDigest;
    core::json::Object provenance;
    /// A material fill's channel rule, empty for any other source: `height` (`image` holds the
    /// signed values float32(2 x - 1) of the stored raster x), `l8`, `srgb8` or `normal` (item 2.16,
    /// `SnapshotSourceProvider::Resolve`). The digest `rasterDigest` stays the stored raster's.
    std::string materialRule;
};

class IProceduralSourceProvider {
public:
    virtual ~IProceduralSourceProvider() = default;
    virtual render::Result<std::shared_ptr<const ProceduralImage>> Resolve(
        const core::Project& project, const core::TextureSet& set, core::ChannelType channel,
        core::ChannelFormat format, const core::FillContent& fill, const core::ProceduralRef& ref,
        core::Id node, bool mask) const = 0;
    /// Rechecks authoritative bytes even when a tile/readout cache is warm.
    virtual bool Available(const ProceduralImage& image) const = 0;
};

}  // namespace uzp::evaluator
