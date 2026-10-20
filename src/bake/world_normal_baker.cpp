#include "bake/world_normal_baker.h"

#include <string>

#include "uzp_core/types/errors.h"

namespace uzp::bake {

void ValidateWorldSpaceNormal(const BakeRequest& request) {
    const std::string owner = UsageOwnerTask(MeshMapUsage::WorldSpaceNormal);
    if (request.detail.subsampling != 1) {
        throw core::NotYetSupported("WorldSpaceNormal SubSampling > 1 has no established resolve rule (" + owner +
                                    ", decision 337)");
    }
    if (request.common.dilation_width != 0) {
        throw core::NotYetSupported("WorldSpaceNormal DilationWidth > 0 has no established padding rule (" + owner +
                                    ", decision 337)");
    }
}

void PrepareWorldSpaceNormal(BakeResult& result) {
    result.world_normal.assign(3 * static_cast<std::size_t>(result.width) * result.height, 0.0f);
}

void WriteWorldSpaceNormal(BakeResult& result, std::size_t texel, const Vec3d& normal) {
    result.world_normal[3 * texel] = static_cast<float>(normal.x);
    result.world_normal[3 * texel + 1] = static_cast<float>(normal.y);
    result.world_normal[3 * texel + 2] = static_cast<float>(normal.z);
}

}  // namespace uzp::bake
