#include "bake/opacity_baker.h"

#include <string>

#include "uzp_core/types/errors.h"

namespace uzp::bake {

void ValidateOpacity(const BakeRequest& request) {
    const std::string owner = UsageOwnerTask(MeshMapUsage::Opacity) + ", decision 341";
    if (request.detail.subsampling != 1) {
        throw core::NotYetSupported("Opacity SubSampling > 1 has no established resolve rule (" + owner + ")");
    }
    if (request.common.dilation_width != 0) {
        throw core::NotYetSupported("Opacity DilationWidth > 0 has no established padding rule (" + owner + ")");
    }
}

void PrepareOpacity(BakeResult& result) {
    result.opacity.assign(static_cast<std::size_t>(result.width) * result.height, 0.0f);
}

void WriteOpacity(BakeResult& result, std::size_t texel) { result.opacity[texel] = 1.0f; }

}  // namespace uzp::bake
