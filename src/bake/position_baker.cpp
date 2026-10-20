#include "bake/position_baker.h"

#include <string>

#include "uzp_core/types/errors.h"

namespace uzp::bake {

namespace {

const char* ModeLabel(PositionMode mode) { return mode == PositionMode::AllAxis ? "All axis" : "One axis"; }

const char* AxisLabel(PositionAxis axis) {
    return axis == PositionAxis::X ? "X" : axis == PositionAxis::Y ? "Y" : "Z";
}

const char* NormalizationLabel(PositionNormalization normalization) {
    switch (normalization) {
        case PositionNormalization::BBox: return "BBox";
        case PositionNormalization::BSphere: return "BSphere";
        case PositionNormalization::None: return "None";
    }
    return "unknown";
}

const char* ScaleLabel(PositionNormalizationScale scale) {
    return scale == PositionNormalizationScale::PerMaterial ? "Per Material" : "Full Scene";
}

}  // namespace

void ValidatePosition(const BakeRequest& request) {
    const std::string owner = UsageOwnerTask(MeshMapUsage::Position) + ", decision 337";
    const PositionSettings& p = request.position;
    if (p.mode != PositionMode::AllAxis && p.mode != PositionMode::OneAxis) throw core::ValueError("invalid Position Mode");
    if (p.axis != PositionAxis::X && p.axis != PositionAxis::Y && p.axis != PositionAxis::Z) {
        throw core::ValueError("invalid Position Axis");
    }
    if (p.scale != PositionNormalizationScale::PerMaterial && p.scale != PositionNormalizationScale::FullScene) {
        throw core::ValueError("invalid Position NormalizationScale");
    }
    if (p.normalization == PositionNormalization::BBox || p.normalization == PositionNormalization::BSphere) {
        throw core::NotYetSupported(std::string("Position Normalization '") + NormalizationLabel(p.normalization) +
                                    "': which bounds it uses (the texture set's or the scene's, low or high meshes) "
                                    "and how a point maps to a value are not recorded; a Position golden settles it (" +
                                    owner + ")");
    }
    if (p.normalization != PositionNormalization::None) throw core::ValueError("invalid Position Normalization");
    if (request.detail.subsampling != 1) {
        throw core::NotYetSupported("Position SubSampling > 1 has no established resolve rule (" + owner + ")");
    }
    if (request.common.dilation_width != 0) {
        throw core::NotYetSupported("Position DilationWidth > 0 has no established padding rule (" + owner + ")");
    }
}

void PreparePosition(const BakeRequest& request, BakeResult& result) {
    PositionNormalizationRecord& record = result.position_normalization;
    record.settings = request.position;
    record.channels = request.position.mode == PositionMode::AllAxis ? 3u : 1u;
    record.scale_to_internal = request.scale_to_internal;
    record.bounds_applied = false;  // None: no bounds (the only normalisation admitted)
    result.position.assign(record.channels * static_cast<std::size_t>(result.width) * result.height, 0.0f);
}

void WritePosition(BakeResult& result, std::size_t texel, const Vec3d& point) {
    const PositionNormalizationRecord& record = result.position_normalization;
    const double scale = record.scale_to_internal;
    if (record.channels == 3) {
        result.position[3 * texel] = static_cast<float>(point.x * scale);
        result.position[3 * texel + 1] = static_cast<float>(point.y * scale);
        result.position[3 * texel + 2] = static_cast<float>(point.z * scale);
        return;
    }
    const PositionAxis axis = record.settings.axis;
    const double value = axis == PositionAxis::X ? point.x : axis == PositionAxis::Y ? point.y : point.z;
    result.position[texel] = static_cast<float>(value * scale);
}

core::json::Object PositionNormalizationJson(const PositionNormalizationRecord& record) {
    const PositionSettings& s = record.settings;
    return core::json::Object{
        {"usage", std::string("Position")},
        {"Mode", std::string(ModeLabel(s.mode))},
        {"Axis", std::string(AxisLabel(s.axis))},
        {"Normalization", std::string(NormalizationLabel(s.normalization))},
        {"NormalizationScale", std::string(ScaleLabel(s.scale))},
        {"channels", static_cast<std::int64_t>(record.channels)},
        {"sample_type", std::string("float32")},
        {"unit", std::string("centimetre")},
        {"scale_to_internal", record.scale_to_internal},
        {"bounds_applied", record.bounds_applied},
        {"bounds", core::json::Value{}},
        {"decision", std::string("337")},
    };
}

}  // namespace uzp::bake
