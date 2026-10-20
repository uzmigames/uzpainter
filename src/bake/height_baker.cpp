#include "bake/height_baker.h"

#include <cmath>
#include <string>

#include "uzp_core/types/errors.h"

namespace uzp::bake {

namespace {

const char* NormalizationLabel(HeightNormalization normalization) {
    switch (normalization) {
        case HeightNormalization::RelativeToRayDistances: return "Relative to ray distances";
        case HeightNormalization::RelativeToLowMesh: return "Relative to low mesh (per UV tile)";
        case HeightNormalization::RelativeToMinMax: return "Relative to min/max (per UV tile)";
        case HeightNormalization::Manual: return "Manual";
    }
    return "unknown";
}

/// What nothing recorded fixes for each normalisation.
const char* Unrecorded(HeightNormalization normalization) {
    switch (normalization) {
        case HeightNormalization::RelativeToRayDistances:
            return "which of the frontal and rear distances bounds each sign and where zero falls";
        case HeightNormalization::RelativeToLowMesh: return "what range the low mesh gives each UV tile";
        case HeightNormalization::RelativeToMinMax:
            return "which texels the per-UV-tile minimum and maximum span and where zero falls";
        case HeightNormalization::Manual: return "what range Manual reads";
    }
    return "its mapping";
}

}  // namespace

void ValidateHeight(const BakeRequest& request) {
    const std::string owner = UsageOwnerTask(MeshMapUsage::Height) + ", decision 341";
    const HeightSettings& h = request.height;
    if (!(std::isfinite(h.divisor) && h.divisor > 0.0f)) throw core::ValueError("Height Divisor must be finite and > 0");
    if (h.normalization) {
        const HeightNormalization normalization = *h.normalization;
        if (normalization != HeightNormalization::RelativeToRayDistances &&
            normalization != HeightNormalization::RelativeToLowMesh &&
            normalization != HeightNormalization::RelativeToMinMax && normalization != HeightNormalization::Manual) {
            throw core::ValueError("invalid Height MaximizeRange");
        }
        throw core::NotYetSupported(std::string("Height MaximizeRange '") + NormalizationLabel(normalization) + "': " +
                                    Unrecorded(normalization) +
                                    ", and how Divisor composes with it, are not recorded; a Height golden settles "
                                    "it (" + owner + ")");
    }
    if (request.detail.subsampling != 1) {
        throw core::NotYetSupported("Height SubSampling > 1 has no established resolve rule (" + owner + ")");
    }
    if (request.common.dilation_width != 0) {
        throw core::NotYetSupported("Height DilationWidth > 0 has no established padding rule (" + owner + ")");
    }
}

void PrepareHeight(const BakeRequest& request, BakeResult& result) {
    HeightNormalizationRecord& record = result.height_normalization;
    record.settings = request.height;
    record.scale_to_internal = request.scale_to_internal;
    record.normalization_applied = false;  // no normalisation is admitted
    record.divisor_applied = false;
    result.height_map.assign(static_cast<std::size_t>(result.width) * result.height, 0.0f);
}

void WriteHeight(BakeResult& result, std::size_t texel, double distance) {
    result.height_map[texel] = static_cast<float>(distance * result.height_normalization.scale_to_internal);
}

core::json::Object HeightNormalizationJson(const HeightNormalizationRecord& record) {
    const HeightSettings& s = record.settings;
    return core::json::Object{
        {"usage", std::string("Height")},
        {"MaximizeRange", s.normalization ? core::json::Value(std::string(NormalizationLabel(*s.normalization)))
                                          : core::json::Value{}},
        {"Divisor", static_cast<double>(s.divisor)},
        {"normalization_applied", record.normalization_applied},
        {"divisor_applied", record.divisor_applied},
        {"signed", true},
        {"sample_type", std::string("float32")},
        {"unit", std::string("centimetre")},
        {"scale_to_internal", record.scale_to_internal},
        {"range", core::json::Value{}},
        {"decision", std::string("341")},
    };
}

}  // namespace uzp::bake
