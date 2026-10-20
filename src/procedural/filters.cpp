#include "procedural/filters.h"

#include "procedural/primitives.h"

#include "evaluator/arith.h"

#include "uzp_core/manifest/sha256.h"

#include <array>
#include <bit>
#include <memory>

namespace uzp::procedural {

namespace {

using NotRegistered = std::expected<void, std::string>::unexpected_type;

/// The float32 rounding of a parameter (an integer or a number).
float FloatParam(const Params& params, const std::string& name) {
    const ParamValue& value = params.at(name);
    if (const auto* d = std::get_if<double>(&value)) return static_cast<float>(*d);
    return static_cast<float>(std::get<int64_t>(value));
}

/// A parameter as a number (an integer or a number).
double NumberParam(const Params& params, const std::string& name) {
    const ParamValue& value = params.at(name);
    if (const auto* d = std::get_if<double>(&value)) return *d;
    return static_cast<double>(std::get<int64_t>(value));
}

uint32_t Bits(float value) { return std::bit_cast<uint32_t>(value); }

render::Unexpected Failed(std::string reason) {
    return render::Fail(render::ErrorCode::RequestFailed, std::nullopt, std::move(reason));
}

/// The tile a request evaluates (the whole texture for an empty rectangle).
TileRect TileOf(const ProceduralRequest& request) {
    if (request.tile.width != 0 && request.tile.height != 0) return request.tile;
    return TileRect{0, 0, request.output.resolution, request.output.resolution};
}

const std::string kContent(kContentInput);

// Sharpen (filters.h): g = f - amount x L(f), the four-neighbour Laplacian summed left, right,
// up, down, then minus 4 f; the content wraps at the texture border.
constexpr std::string_view kSharpenBody = R"(
float SharpenValue(float c, float l, float r, float u, float d, float amount) {
    const float laplacian = Sub(Add(Add(Add(l, r), u), d), Mul(4.0f, c));
    return Sub(c, Mul(amount, laplacian));
}

float4 ProcTexel(int2 texel) {
    const float amount = asfloat(ProcParam(0u));
    const float4 c = Texel(0u, texel.x, texel.y, BORDER_WRAP);
    const float4 l = Texel(0u, texel.x - 1, texel.y, BORDER_WRAP);
    const float4 r = Texel(0u, texel.x + 1, texel.y, BORDER_WRAP);
    const float4 u = Texel(0u, texel.x, texel.y - 1, BORDER_WRAP);
    const float4 d = Texel(0u, texel.x, texel.y + 1, BORDER_WRAP);
    return float4(SharpenValue(c.x, l.x, r.x, u.x, d.x, amount),
                  SharpenValue(c.y, l.y, r.y, u.y, d.y, amount),
                  SharpenValue(c.z, l.z, r.z, u.z, d.z, amount),
                  SharpenValue(c.w, l.w, r.w, u.w, d.w, amount));
}
)";

// Grayscale conversion (filters.h): Y = (red R + green G) + blue B on the three channels.
constexpr std::string_view kGrayscaleBody = R"(
float4 ProcTexel(int2 texel) {
    const float4 c = Texel(0u, texel.x, texel.y, BORDER_WRAP);
    const float y = Add(Add(Mul(asfloat(ProcParam(0u)), c.x), Mul(asfloat(ProcParam(1u)), c.y)),
                        Mul(asfloat(ProcParam(2u)), c.z));
    return float4(y, y, y, 0.0f);
}
)";

/// A filter family registered from its library record.
class FilterFamily : public IHlslFamily {
public:
    explicit FilterFamily(const AssetRecord& record) {
        m_record.asset = record.asset;
        m_record.domain = record.domain;
        m_record.status = record.status;
        m_record.provenance = core::json::WriteCanonical(record.json);
    }

    const FamilyRecord& Record() const override { return m_record; }

    std::optional<UnsupportedProcedural> JointRefusal(const ProceduralRequest& request) const override {
        return FilterJointRefusal(request);
    }

private:
    FamilyRecord m_record;
};

class SharpenFamily final : public FilterFamily {
public:
    using FilterFamily::FilterFamily;

    std::vector<KernelPass> Plan(const ProceduralRequest& request) const override {
        return {KernelPass{"filter_sharpen", std::string(kSharpenBody),
                           {Bits(FloatParam(request.params, "amount"))},
                           {PassInput{kContent, -1}}}};
    }

    Raster Reference(const ProceduralRequest& request, const InputImages& inputs) const override {
        const Raster& f = inputs.at(kContent);
        const float amount = FloatParam(request.params, "amount");
        const TileRect tile = TileOf(request);
        Raster out{tile.width, tile.height, request.output.channels, {}};
        out.texels.reserve(size_t{tile.width} * tile.height * out.channels);
        constexpr prim::Border kWrap = prim::Border::Wrap;
        for (uint32_t y = 0; y < tile.height; ++y) {
            for (uint32_t x = 0; x < tile.width; ++x) {
                const int64_t px = int64_t{tile.x} + x;
                const int64_t py = int64_t{tile.y} + y;
                for (uint32_t c = 0; c < out.channels; ++c) {
                    const float centre = prim::Texel(f, px, py, c, kWrap);
                    const float left = prim::Texel(f, px - 1, py, c, kWrap);
                    const float right = prim::Texel(f, px + 1, py, c, kWrap);
                    const float up = prim::Texel(f, px, py - 1, c, kWrap);
                    const float down = prim::Texel(f, px, py + 1, c, kWrap);
                    const float laplacian = prim::Sub(
                        prim::Add(prim::Add(prim::Add(left, right), up), down), prim::Mul(4.0f, centre));
                    out.texels.push_back(prim::Sub(centre, prim::Mul(amount, laplacian)));
                }
            }
        }
        return out;
    }
};

class GrayscaleFamily final : public FilterFamily {
public:
    using FilterFamily::FilterFamily;

    std::vector<KernelPass> Plan(const ProceduralRequest& request) const override {
        return {KernelPass{"filter_grayscale", std::string(kGrayscaleBody),
                           {Bits(FloatParam(request.params, "red")), Bits(FloatParam(request.params, "green")),
                            Bits(FloatParam(request.params, "blue"))},
                           {PassInput{kContent, -1}}}};
    }

    Raster Reference(const ProceduralRequest& request, const InputImages& inputs) const override {
        const Raster& f = inputs.at(kContent);
        const float red = FloatParam(request.params, "red");
        const float green = FloatParam(request.params, "green");
        const float blue = FloatParam(request.params, "blue");
        const TileRect tile = TileOf(request);
        Raster out{tile.width, tile.height, request.output.channels, {}};
        out.texels.reserve(size_t{tile.width} * tile.height * out.channels);
        constexpr prim::Border kWrap = prim::Border::Wrap;
        for (uint32_t y = 0; y < tile.height; ++y) {
            for (uint32_t x = 0; x < tile.width; ++x) {
                const int64_t px = int64_t{tile.x} + x;
                const int64_t py = int64_t{tile.y} + y;
                const float grey = prim::Add(prim::Add(prim::Mul(red, prim::Texel(f, px, py, 0, kWrap)),
                                                       prim::Mul(green, prim::Texel(f, px, py, 1, kWrap))),
                                             prim::Mul(blue, prim::Texel(f, px, py, 2, kWrap)));
                for (uint32_t c = 0; c < out.channels; ++c) out.texels.push_back(grey);
            }
        }
        return out;
    }
};

}  // namespace

std::optional<UnsupportedProcedural> FilterJointRefusal(const ProceduralRequest& request) {
    const auto it = request.inputs.find(kContent);
    if (it == request.inputs.end()) return std::nullopt;
    const RasterSpec& content = it->second.spec;
    const RasterSpec& output = request.output;
    const std::string where = "inputs." + kContent;
    const auto outside = [&](std::string field, std::string value, std::string certified) {
        return UnsupportedProcedural{AssetName(request), std::string(kOutsideDomain), where + "." + field,
                                     std::move(value), "the output's " + field + " (" + certified + ")"};
    };
    if (content.resolution != output.resolution) {
        return outside("resolution", std::to_string(content.resolution), std::to_string(output.resolution));
    }
    if (content.channels != output.channels) {
        return outside("channels", std::to_string(content.channels), std::to_string(output.channels));
    }
    if (content.colourSpace != output.colourSpace) {
        return outside("colour_space", "\"" + content.colourSpace + "\"", "\"" + output.colourSpace + "\"");
    }
    return std::nullopt;
}

std::expected<void, std::string> RegisterFilterFamilies(HlslBackend& hlsl, const AssetLibrary& library) {
    for (const std::string_view url : {kSharpenAsset, kGrayscaleAsset}) {
        const AssetRecord* record = library.Find(core::ParseAssetUrl(url));
        if (record == nullptr) return NotRegistered("the asset library holds no record of " + std::string(url));
        std::shared_ptr<const IHlslFamily> family;
        if (url == kSharpenAsset) {
            family = std::make_shared<SharpenFamily>(*record);
        } else {
            family = std::make_shared<GrayscaleFamily>(*record);
        }
        if (std::expected<void, std::string> registered = hlsl.Register(std::move(family)); !registered) {
            return registered;
        }
    }
    return {};
}

std::expected<core::LevelsParams, UnsupportedProcedural> LevelsFilterEffect(const ProceduralRequest& request,
                                                                          const AssetLibrary& library) {
    // Another asset is refused as such; another version of the Levels filter by the library.
    const core::AssetUrl levels = core::ParseAssetUrl(kLevelsAsset);
    if (request.asset.family != levels.family || request.asset.id != levels.id) {
        return Refused(Refuse(AssetName(request), "not the Levels filter (" + std::string(kLevelsAsset) + ")"));
    }
    const std::expected<const AssetRecord*, UnsupportedProcedural> record = library.Resolve(request.asset);
    if (!record) return Refused(record.error());
    if (std::optional<UnsupportedProcedural> refusal = CheckDomain(request, (*record)->domain)) {
        return Refused(*refusal);
    }
    if (std::optional<UnsupportedProcedural> refusal = FilterJointRefusal(request)) return Refused(*refusal);
    core::LevelsComponent component;
    component.input_min = NumberParam(request.params, "input_min");
    component.input_max = NumberParam(request.params, "input_max");
    component.gamma = NumberParam(request.params, "gamma");
    component.output_min = NumberParam(request.params, "output_min");
    component.output_max = NumberParam(request.params, "output_max");
    component.clamp = NumberParam(request.params, "clamp") != 0.0;
    core::LevelsParams params;
    params.components = {component};
    return params;
}

render::Result<Raster> LevelsFilterReference(const ProceduralRequest& request, const AssetLibrary& library,
                                             const InputImages& inputs) {
    const std::expected<core::LevelsParams, UnsupportedProcedural> levels = LevelsFilterEffect(request, library);
    if (!levels) return Failed(levels.error().Describe());
    if (std::optional<std::string> invalid = CheckInputs(request, inputs)) return Failed(*invalid);
    // The float32 parameters of the native effect, converted as the evaluator converts them.
    const core::LevelsComponent& c = levels->components.front();
    const evaluator::arith::LevelsComponent native{static_cast<float>(c.input_min), static_cast<float>(c.input_max),
                                                   static_cast<float>(c.gamma), static_cast<float>(c.output_min),
                                                   static_cast<float>(c.output_max), c.clamp};
    const Raster& f = inputs.at(kContent);
    const TileRect tile = TileOf(request);
    Raster out{tile.width, tile.height, f.channels, {}};
    out.texels.reserve(size_t{tile.width} * tile.height * f.channels);
    for (uint32_t y = 0; y < tile.height; ++y) {
        for (uint32_t x = 0; x < tile.width; ++x) {
            const size_t at = (size_t{tile.y + y} * f.width + tile.x + x) * f.channels;
            for (uint32_t ch = 0; ch < f.channels; ++ch) {
                out.texels.push_back(evaluator::arith::Levels(f.texels[at + ch], native));
            }
        }
    }
    return out;
}

ImageInput ContentInput(const Raster& content, const RasterSpec& spec) {
    const std::string_view bytes(reinterpret_cast<const char*>(content.texels.data()),
                                 content.texels.size() * sizeof(float));
    return ImageInput{spec, core::Sha256Hex(bytes)};
}

render::Result<Raster> FilterEffectReference(const HlslBackend& hlsl, const AssetLibrary& library,
                                             const ProceduralRequest& request, const Raster& content,
                                             core::BlendingMode mode, float opacity) {
    namespace arith = evaluator::arith;
    const auto input = request.inputs.find(kContent);
    if (input == request.inputs.end()) return Failed(AssetName(request) + ": the request has no content input");
    const std::string sha256 = ContentInput(content, input->second.spec).sha256;
    if (sha256 != input->second.sha256) {
        return Failed(AssetName(request) + ": the content raster (SHA-256 " + sha256 +
                      ") is not the content the request names (" + input->second.sha256 + ")");
    }
    if (content.channels != 1 && content.channels != 3) {
        return Failed("a filter effect blends one or three channels, not " + std::to_string(content.channels));
    }
    if (!arith::HasKernel(mode)) return Failed(std::string(core::ToString(mode)) + " has no blend kernel");
    const InputImages inputs = {{kContent, content}};
    const core::AssetUrl levels = core::ParseAssetUrl(kLevelsAsset);
    const bool isLevels = request.asset.family == levels.family && request.asset.id == levels.id;
    render::Result<Raster> filtered =
        isLevels ? LevelsFilterReference(request, library, inputs) : hlsl.EvaluateReference(request, inputs);
    if (!filtered) return filtered;
    const TileRect tile = TileOf(request);
    if (filtered->channels != content.channels || filtered->width != tile.width || filtered->height != tile.height) {
        return Failed(AssetName(request) + ": the filter's output does not have the content's channels over the tile");
    }
    Raster out{tile.width, tile.height, content.channels, {}};
    out.texels.reserve(filtered->texels.size());
    for (uint32_t y = 0; y < tile.height; ++y) {
        for (uint32_t x = 0; x < tile.width; ++x) {
            const size_t below = (size_t{tile.y + y} * content.width + tile.x + x) * content.channels;
            const size_t above = (size_t{y} * tile.width + x) * content.channels;
            arith::CompositeInput in;
            for (uint32_t c = 0; c < content.channels; ++c) {
                in.acc[c] = content.texels[below + c];
                in.src[c] = filtered->texels[above + c];
            }
            in.opacity = opacity;
            in.mode = mode;
            in.effectMix = true;
            in.channels = static_cast<int>(content.channels);
            const std::array<float, 4> v = arith::Composite(in);
            for (uint32_t c = 0; c < content.channels; ++c) out.texels.push_back(v[c]);
        }
    }
    return out;
}

}  // namespace uzp::procedural
