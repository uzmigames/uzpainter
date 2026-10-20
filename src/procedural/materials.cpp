#include "procedural/materials.h"

#include "procedural/primitives.h"

#include "uzp_core/document/nodes.h"
#include "uzp_core/types/errors.h"

#include <algorithm>
#include <bit>
#include <cmath>
#include <memory>

// ── The CPU lane of the kernel functions (shaders/proc_materials.hlsli) ───────

namespace uzp::procedural::material_kernel {

// The HLSL vocabulary the shared text uses, as C++ over the primitive library.
using uint = uint32_t;

struct uint3 {
    uint x;
    uint y;
    uint z;
};

struct float4 {
    float x;
    float y;
    float z;
    float w;
    constexpr float4(float a, float b, float c, float d) : x(a), y(b), z(c), w(d) {}
};

inline float asfloat(uint bits) { return std::bit_cast<float>(bits); }
inline uint asuint(float value) { return std::bit_cast<uint>(value); }
inline float Hash24(uint h) { return static_cast<float>(h >> 8); }

inline uint3 SeedOffset(uint seed) {
    const prim::U3 o = prim::SeedOffset(seed);
    return uint3{o[0], o[1], o[2]};
}

inline uint3 CellHash(int i, int j, int k, uint3 offset) {
    const prim::U3 h = prim::CellHash(i, j, k, prim::U3{offset.x, offset.y, offset.z});
    return uint3{h[0], h[1], h[2]};
}

using prim::Add;
using prim::Fade2002;
using prim::Lerp;
using prim::Mul;
using prim::SqrtRn;
using prim::Sub;

inline float MFloor(float x) { return std::floor(x); }

/// What the reference lane is evaluating: the parameter words, and the part of the fields pass a
/// two-pass output reads (`MInput`): `input` holds the fields of texels `originX` ... and
/// `originY` ... of the texture continued periodically, each computed at its wrapped position.
struct Lane {
    std::span<const uint32_t> words;
    const Raster* input = nullptr;
    int originX = 0;
    int originY = 0;
};
thread_local Lane t_lane;

inline uint MParam(uint i) { return t_lane.words[i]; }

/// The fields pass at texel (x, y), every value flushed: what the HLSL lane's
/// `Texel(0, x, y, BORDER_WRAP)` reads from the pass's whole texture.
inline float4 MInput(int x, int y) {
    const Raster& r = *t_lane.input;
    const size_t i = (size_t(y - t_lane.originY) * r.width + size_t(x - t_lane.originX)) * 4;
    return float4(prim::Ftz(r.texels[i]), prim::Ftz(r.texels[i + 1]), prim::Ftz(r.texels[i + 2]),
                  prim::Ftz(r.texels[i + 3]));
}

#include "procedural/shaders/proc_materials.hlsli"

}  // namespace uzp::procedural::material_kernel

namespace uzp::procedural {

namespace {

namespace mk = material_kernel;
namespace json = core::json;

using NotRegistered = std::expected<void, std::string>::unexpected_type;
using WordsOrError = std::expected<std::vector<uint32_t>, std::string>;
/// `std::unexpected<std::string>` (the bare name is ambiguous with Zig's libc++, see seam.h).
using Error = WordsOrError::unexpected_type;

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wc23-extensions"
constexpr char kMaterialsHlsl[] = {
#embed "shaders/proc_materials.hlsli"
};
#pragma clang diagnostic pop

/// What the HLSL lane adds around the shared text: its parameter, floor and input accessors and
/// the kernel's entry.
constexpr std::string_view kBodyHead = R"(
uint MParam(uint i) { return ProcParam(i); }
float MFloor(float x) { return floor(x); }
float4 MInput(int x, int y) { return Texel(0u, x, y, BORDER_WRAP); }
)";
constexpr std::string_view kBodyTail = R"(
float4 ProcTexel(int2 texel) { return MaterialTexel(texel.x, texel.y, g_seed); }
)";

std::string KernelBody() {
    std::string body(kBodyHead);
    body.append(kMaterialsHlsl, sizeof(kMaterialsHlsl));
    body += kBodyTail;
    return body;
}

enum Kind : uint32_t { kFelt = 0, kBurlap = 1, kLeatherGrain = 2, kLeatherPattern = 3 };

/// The fixed configuration of one asset (decision 334): its kind and its seed salt.
struct Shape {
    std::string_view id;
    Kind kind;
    uint32_t salt;
};

constexpr Shape kShapes[] = {
    {"felt", kFelt, 0x2001},
    {"burlap", kBurlap, 0x2002},
    {"leather-grain", kLeatherGrain, 0x2003},
    {"leather-pattern", kLeatherPattern, 0x2004},
};

constexpr std::string_view kIds[] = {"felt", "burlap", "leather-grain", "leather-pattern"};
static_assert(std::size(kIds) == std::size(kShapes));

/// The outputs in the kernel's numbering (`kMatOutput`).
constexpr std::string_view kOutputs[] = {"basecolor", "normal", "roughness", "metallic", "height", "ambient_occlusion"};
constexpr uint32_t kNormalOutput = 1;
constexpr uint32_t kOcclusionOutput = 5;
constexpr uint32_t kDirections = 16;

const Shape* FindShape(std::string_view id) {
    for (const Shape& shape : kShapes) {
        if (shape.id == id) return &shape;
    }
    return nullptr;
}

std::optional<uint32_t> OutputIndex(std::string_view id) {
    for (uint32_t i = 0; i < std::size(kOutputs); ++i) {
        if (kOutputs[i] == id) return i;
    }
    return std::nullopt;
}

bool TwoPass(uint32_t output) { return output == kNormalOutput || output == kOcclusionOutput; }

uint32_t Bits(float value) { return std::bit_cast<uint32_t>(value); }
uint32_t FloatWord(double value) { return Bits(static_cast<float>(value)); }

/// A parameter as a number (an integer or a number), or empty.
std::optional<double> Number(const Params& params, const std::string& name) {
    const auto it = params.find(name);
    if (it == params.end()) return std::nullopt;
    if (const auto* d = std::get_if<double>(&it->second)) return *d;
    if (const auto* i = std::get_if<int64_t>(&it->second)) return static_cast<double>(*i);
    return std::nullopt;
}

/// sin and cos of `theta` (radians) with IEEE double additions, multiplications and divisions
/// only, so every machine computes the same table: reduced to [-pi, pi], then 30 Taylor terms.
std::pair<double, double> SinCos(double theta) {
    constexpr double kPi = 3.141592653589793;
    while (theta > kPi) theta -= 2.0 * kPi;
    while (theta < -kPi) theta += 2.0 * kPi;
    double sine = 0.0;
    double cosine = 0.0;
    double term = 1.0;  // theta^n / n!
    for (int n = 0; n < 30; ++n) {
        if (n > 0) term = term * theta / n;
        switch (n % 4) {
            case 0: cosine += term; break;
            case 1: sine += term; break;
            case 2: cosine -= term; break;
            default: sine -= term; break;
        }
    }
    return {sine, cosine};
}

WordsOrError Words(const Shape& shape, const ProceduralRequest& request, uint32_t output) {
    const Params& p = request.params;
    std::string missing;
    const auto need = [&](const std::string& name) {
        const std::optional<double> value = Number(p, name);
        if (!value && missing.empty()) missing = name;
        return value.value_or(0.0);
    };
    const double tiling = need("tiling");
    const double colour[3] = {need("color_r"), need("color_g"), need("color_b")};
    const double variation = need("color_variation");
    const double roughness = need("roughness");
    const double roughnessVariation = need("roughness_variation");
    const double normalIntensity = need("normal_intensity");
    const double aoIntensity = need("ao_intensity");
    std::vector<uint32_t> w(mk::kMatTable, 0u);
    switch (shape.kind) {
        case kFelt: {
            const double density = need("fibre_density");
            const double alignment = need("fibre_alignment");
            w[mk::kMatA] = FloatWord(0.35 + 0.6 * density);
            w[mk::kMatB] = FloatWord(density);
            for (uint32_t k = 0; k < kDirections; ++k) {
                const double degrees = (1.0 - alignment) * 180.0 * (double(k) / kDirections - 0.5);
                const auto [sine, cosine] = SinCos(degrees * (3.141592653589793 / 180.0));
                w.push_back(FloatWord(cosine));
                w.push_back(FloatWord(sine));
            }
            break;
        }
        case kBurlap: {
            const double gap = need("gap");
            w[mk::kMatA] = FloatWord(1.0 / (0.5 * (1.0 - gap)));
            w[mk::kMatB] = FloatWord(need("irregularity"));
            w[mk::kMatC] = FloatWord(0.25 * need("fuzz"));
            break;
        }
        case kLeatherGrain: {
            w[mk::kMatA] = FloatWord(0.5 + 0.5 * need("irregularity"));
            w[mk::kMatB] = FloatWord(1.0 / (0.04 + 0.16 * need("groove_width")));
            w[mk::kMatC] = FloatWord(0.5 * need("pore_amount"));
            break;
        }
        case kLeatherPattern: {
            w[mk::kMatA] = FloatWord(need("crease_depth"));
            w[mk::kMatB] = FloatWord(need("wrinkles"));
            w[mk::kMatC] = FloatWord(need("grain_amount"));
            break;
        }
    }
    if (!missing.empty()) return Error("the request has no number " + missing);
    const uint32_t resolution = request.output.resolution;
    if (resolution == 0) return Error(std::string("the request has no output resolution"));
    const uint32_t repeats = static_cast<uint32_t>(tiling);
    if (static_cast<double>(repeats) != tiling || repeats == 0) {
        return Error("tiling must be a whole number of repeats, not " + std::to_string(tiling));
    }
    w[mk::kMatKind] = shape.kind;
    w[mk::kMatOutput] = output;
    w[mk::kMatTiling] = repeats;
    w[mk::kMatUnit] = FloatWord(double(repeats) / resolution);
    w[mk::kMatSalt] = shape.salt;
    for (uint32_t c = 0; c < 3; ++c) w[mk::kMatColour + c] = FloatWord(colour[c]);
    w[mk::kMatColourVariation] = FloatWord(variation);
    w[mk::kMatRoughness] = FloatWord(roughness);
    w[mk::kMatRoughnessVariation] = FloatWord(roughnessVariation);
    w[mk::kMatNormalGain] = FloatWord(normalIntensity * resolution / 256.0);
    w[mk::kMatAoIntensity] = FloatWord(aoIntensity);
    w[mk::kMatAoStep] = resolution / 512 == 0 ? 1u : resolution / 512;
    return w;
}

/// The words of `request` for its output, or for the fields pass.
WordsOrError RequestWords(const Shape& shape, const ProceduralRequest& request, bool fields) {
    const std::optional<uint32_t> output = OutputIndex(request.outputId);
    if (!output) return Error(AssetName(request) + " has no output \"" + request.outputId + "\"");
    return Words(shape, request, fields ? mk::kMatFieldsOutput : *output);
}

/// The fields pass over `tile` grown by `margin` texels on every side: each texel's fields
/// computed at its position wrapped into the texture, as the kernel's first pass writes them
/// and its second pass reads them (wrapping).
Raster FieldsAround(std::span<const uint32_t> fields, const TileRect& tile, uint32_t margin, uint32_t resolution,
                    uint32_t seed) {
    const int r = static_cast<int>(resolution);
    const int m = static_cast<int>(margin);
    Raster out{tile.width + 2 * margin, tile.height + 2 * margin, 4, {}};
    out.texels.reserve(size_t{out.width} * out.height * 4);
    mk::t_lane = mk::Lane{fields};
    for (uint32_t y = 0; y < out.height; ++y) {
        for (uint32_t x = 0; x < out.width; ++x) {
            const int wx = mk::MWrap(static_cast<int>(tile.x + x) - m, r);
            const int wy = mk::MWrap(static_cast<int>(tile.y + y) - m, r);
            const mk::float4 t = mk::MaterialTexel(wx, wy, seed);
            for (const float v : {t.x, t.y, t.z, t.w}) out.texels.push_back(v);
        }
    }
    mk::t_lane = mk::Lane{};
    return out;
}

/// The CPU reference texels of `words` over `tile` (`channels` per texel), reading `input` (the
/// fields from texel (tile.x - margin, tile.y - margin) on) for a two-pass output.
Raster Texels(std::span<const uint32_t> words, const TileRect& tile, uint32_t channels, uint32_t seed,
              const Raster* input, uint32_t margin = 0) {
    mk::t_lane = mk::Lane{words, input, static_cast<int>(tile.x) - static_cast<int>(margin),
                          static_cast<int>(tile.y) - static_cast<int>(margin)};
    Raster out{tile.width, tile.height, channels, {}};
    out.texels.reserve(size_t{tile.width} * tile.height * channels);
    for (uint32_t y = 0; y < tile.height; ++y) {
        for (uint32_t x = 0; x < tile.width; ++x) {
            const mk::float4 t =
                mk::MaterialTexel(static_cast<int>(tile.x + x), static_cast<int>(tile.y + y), seed);
            const float values[4] = {t.x, t.y, t.z, t.w};
            for (uint32_t c = 0; c < channels; ++c) out.texels.push_back(values[c]);
        }
    }
    mk::t_lane = mk::Lane{};
    return out;
}

/// A material asset registered from its library record.
class MaterialFamily final : public IHlslFamily {
public:
    MaterialFamily(const AssetRecord& record, const Shape& shape) : m_shape(shape), m_outputs(record) {
        m_record.asset = record.asset;
        m_record.domain = record.domain;
        m_record.status = record.status;
        m_record.provenance = json::WriteCanonical(record.json);
    }

    const FamilyRecord& Record() const override { return m_record; }

    std::optional<UnsupportedProcedural> JointRefusal(const ProceduralRequest& request) const override {
        return MaterialJointRefusal(request, m_outputs);
    }

    std::vector<KernelPass> Plan(const ProceduralRequest& request) const override {
        // Inside the domain every parameter and the output are present, so the words are always
        // built; a request outside it is refused before planning.
        const WordsOrError words = RequestWords(m_shape, request, false);
        if (!words) return {};
        const std::string name = "material_" + std::string(m_shape.id) + "_" + request.outputId;
        if (!TwoPass((*words)[mk::kMatOutput])) return {KernelPass{name, KernelBody(), *words, {}}};
        const WordsOrError fields = RequestWords(m_shape, request, true);
        return {KernelPass{"material_" + std::string(m_shape.id) + "_fields", KernelBody(), *fields, {}},
                KernelPass{name, KernelBody(), *words, {PassInput{{}, 0}}}};
    }

    Raster Reference(const ProceduralRequest& request, const InputImages&) const override {
        const WordsOrError words = RequestWords(m_shape, request, false);
        if (!words) return Raster{};
        const uint32_t resolution = request.output.resolution;
        const TileRect tile = request.tile.width != 0 && request.tile.height != 0
                                  ? request.tile
                                  : TileRect{0, 0, resolution, resolution};
        const uint32_t seed = static_cast<uint32_t>(request.seed);
        if (!TwoPass((*words)[mk::kMatOutput])) return Texels(*words, tile, request.output.channels, seed, nullptr);
        // The fields pass, then the output reading it, as the kernels; the fields are computed
        // only where the output reads them (the tile and the neighbours it reaches).
        const WordsOrError fields = RequestWords(m_shape, request, true);
        const uint32_t margin = std::max<uint32_t>(1, (*words)[mk::kMatAoStep]);
        const Raster pass0 = FieldsAround(*fields, tile, margin, resolution, seed);
        return Texels(*words, tile, request.output.channels, seed, &pass0, margin);
    }

private:
    FamilyRecord m_record;
    const Shape& m_shape;
    AssetRecord m_outputs;  ///< The record (its outputs).
};

std::string IdList(const AssetRecord& record) {
    std::string list;
    for (const AssetOutput& output : record.outputs) list += (list.empty() ? "" : ", ") + ("\"" + output.id + "\"");
    return "{" + list + "}";
}

const AssetOutput* FindOutput(const AssetRecord& record, std::string_view id) {
    for (const AssetOutput& output : record.outputs) {
        if (output.id == id) return &output;
    }
    return nullptr;
}

}  // namespace

std::span<const std::string_view> MaterialAssetIds() { return kIds; }

std::span<const std::string_view> MaterialOutputIds() { return kOutputs; }

std::optional<UnsupportedProcedural> MaterialJointRefusal(const ProceduralRequest& request,
                                                          const AssetRecord& record) {
    const AssetOutput* output = FindOutput(record, request.outputId);
    if (output == nullptr) {
        return UnsupportedProcedural{AssetName(request), std::string(kOutsideDomain), "output.id",
                                     "\"" + request.outputId + "\"", IdList(record)};
    }
    if (request.output.channels != output->channels) {
        return UnsupportedProcedural{AssetName(request), std::string(kOutsideDomain), "output.channels",
                                     std::to_string(request.output.channels),
                                     std::to_string(output->channels) + " (the " + output->id + " output)"};
    }
    if (request.output.colourSpace != output->colourSpace) {
        return UnsupportedProcedural{AssetName(request), std::string(kOutsideDomain), "output.colour_space",
                                     "\"" + request.output.colourSpace + "\"",
                                     "\"" + output->colourSpace + "\" (the " + output->id + " output)"};
    }
    return std::nullopt;
}

std::expected<void, std::string> RegisterMaterialFamilies(HlslBackend& hlsl, const AssetLibrary& library) {
    for (const Shape& shape : kShapes) {
        const std::string url = "uzasset://" + std::string(kMaterialFamily) + "/" + std::string(shape.id) + "@1";
        const AssetRecord* record = library.Find(core::ParseAssetUrl(url));
        if (record == nullptr) return NotRegistered("the asset library holds no record of " + url);
        bool complete = record->outputs.size() == std::size(kOutputs);
        for (const std::string_view id : kOutputs) complete = complete && FindOutput(*record, id) != nullptr;
        if (!complete) return NotRegistered(url + ": the record does not list the six material outputs");
        if (std::expected<void, std::string> registered = hlsl.Register(std::make_shared<MaterialFamily>(*record, shape));
            !registered) {
            return registered;
        }
    }
    return {};
}

std::expected<std::vector<uint32_t>, std::string> MaterialWords(const ProceduralRequest& request, bool fields) {
    if (request.asset.family != kMaterialFamily) return Error(AssetName(request) + " is not a material asset");
    const Shape* shape = FindShape(request.asset.id);
    if (shape == nullptr) return Error(AssetName(request) + " is not an asset of the material family");
    return RequestWords(*shape, request, fields);
}

std::array<float, 4> MaterialTexel(std::span<const uint32_t> words, int32_t x, int32_t y, uint32_t seed) {
    mk::t_lane = mk::Lane{words, nullptr};
    const mk::float4 t = mk::MaterialTexel(x, y, seed);
    mk::t_lane = mk::Lane{};
    return {t.x, t.y, t.z, t.w};
}

std::map<std::string, std::string> DefaultOutputMapping(const AssetRecord& record) {
    std::map<std::string, std::string> mapping;
    for (const AssetOutput& output : record.outputs) mapping[output.channel] = output.id;
    return mapping;
}

std::expected<std::vector<MaterialChannelRequest>, UnsupportedProcedural> MaterialRequests(
    const core::ProceduralRef& ref, const UseContext& context, const AssetLibrary& library) {
    using Fail = std::expected<std::vector<MaterialChannelRequest>, UnsupportedProcedural>::unexpected_type;
    if (ref.output_mapping.empty()) {
        UnsupportedProcedural refusal = Refuse(ref.asset, "a material source maps at least one channel");
        refusal.field = "output_mapping";
        refusal.value = "{}";
        refusal.certified = "a channel per output to evaluate (DefaultOutputMapping)";
        return Fail(std::move(refusal));
    }
    std::vector<MaterialChannelRequest> requests;
    for (const auto& [channelName, outputId] : ref.output_mapping) {
        const std::optional<core::ChannelType> channel = core::FromString<core::ChannelType>(channelName);
        if (!channel) {
            UnsupportedProcedural refusal = Refuse(ref.asset, "an output_mapping key is a channel");
            refusal.field = "output_mapping." + channelName;
            refusal.value = "\"" + outputId + "\"";
            refusal.certified = "a ChannelType name";
            return Fail(std::move(refusal));
        }
        UseContext use = context;
        use.outputId = outputId;
        std::expected<ProceduralRequest, UnsupportedProcedural> request = RequestFor(ref, use, library);
        if (!request) return Fail(request.error());
        if (const AssetRecord* record = library.Find(request->asset)) {
            const AssetOutput* output = FindOutput(*record, outputId);
            if (output == nullptr) {
                UnsupportedProcedural refusal = Refuse(AssetName(*request), kOutsideDomain);
                refusal.field = "output_mapping." + channelName;
                refusal.value = "\"" + outputId + "\"";
                refusal.certified = IdList(*record);
                return Fail(std::move(refusal));
            }
            request->output.channels = output->channels;
            request->output.colourSpace = output->colourSpace;
        }
        requests.push_back(MaterialChannelRequest{*channel, std::move(*request)});
    }
    return requests;
}

json::Object PhysicalScale::ToJson() const {
    const auto pair = [](const std::array<double, 2>& v) { return json::Array{json::Value(v[0]), json::Value(v[1])}; };
    json::Value requested = nullptr;
    if (requestedMeshUnitScale) requested = json::Value(*requestedMeshUnitScale);
    return json::Object{
        {"scale_mode", std::string(core::ToString(mode))},
        {"physical_size_cm", pair(physicalSizeCm)},
        {"size_from", sizeFrom},
        {"units", json::Object{{"source", unitsSource},
                               {"from", unitsFrom},
                               {"requested_mesh_unit_scale", std::move(requested)},
                               {"scale_to_internal", json::Value(cmPerFileUnit)}}},
        {"textures_per_file_unit", pair(texturesPerFileUnit)},
        {"uv", json::Object{{"texture_set", textureSet},
                            {"density_px_per_cm_p50", json::Value(densityPxPerCm)},
                            {"grid", json::Array{json::Value(grid[0]), json::Value(grid[1])}},
                            {"cm_per_uv", json::Value(cmPerUv)},
                            {"scale", pair(uvScale)}}},
    };
}

std::expected<PhysicalScale, std::string> EvaluatePhysicalScale(const core::UVTransformation& transformation,
                                                                const AssetRecord* material,
                                                                const core::MeshReference& mesh,
                                                                const core::TextureSet& set) {
    using Refusal = std::expected<PhysicalScale, std::string>::unexpected_type;
    PhysicalScale scale;
    scale.mode = transformation.scale_mode;
    switch (transformation.scale_mode) {
        case core::ScaleMode::Factors:
            return Refusal(std::string("the Factors scale mode is not a physical size: its scale is the repeat factors"));
        case core::ScaleMode::CustomPhysicalSize:
            for (const double side : transformation.scale) {
                if (!std::isfinite(side) || !(side > 0.0)) {
                    return Refusal("a CustomPhysicalSize scale is two finite positive centimetre values, not " +
                                   std::to_string(side));
                }
            }
            scale.physicalSizeCm = transformation.scale;
            scale.sizeFrom = "custom";
            break;
        case core::ScaleMode::MaterialPhysicalSize:
            if (material == nullptr || !material->physicalSizeCm) {
                return Refusal((material ? core::FormatAssetUrl(material->asset) : std::string("the source")) +
                               " has no physical size for the MaterialPhysicalSize scale mode");
            }
            scale.physicalSizeCm = *material->physicalSizeCm;
            scale.sizeFrom = "material";
            break;
    }
    // The project unit rule (12 §3): the import report's effective units.
    const auto member = [](const json::Object* object, std::string_view key) -> const json::Value* {
        if (object == nullptr) return nullptr;
        const auto it = object->find(key);
        return it == object->end() ? nullptr : &it->second;
    };
    const auto object = [](const json::Value* value) -> const json::Object* {
        return value != nullptr && value->IsObject() ? &std::get<json::Object>(value->data) : nullptr;
    };
    const auto number = [](const json::Value* value) -> std::optional<double> {
        if (value == nullptr || !value->IsNumber()) return std::nullopt;
        return value->IsInt() ? static_cast<double>(std::get<int64_t>(value->data)) : std::get<double>(value->data);
    };
    const json::Object* units = object(member(&mesh.import_report, "units"));
    const std::optional<double> cmPerUnit = number(member(units, "scale_to_internal"));
    const json::Value* from = member(units, "from");
    const json::Value* source = member(units, "source");
    if (units == nullptr || !cmPerUnit || !std::isfinite(*cmPerUnit) || !(*cmPerUnit > 0.0) || from == nullptr ||
        !from->IsString() || source == nullptr || !source->IsString()) {
        return Refusal(std::string("the mesh import report records no effective units (units.scale_to_internal)"));
    }
    scale.cmPerFileUnit = *cmPerUnit;
    scale.unitsFrom = std::get<std::string>(from->data);
    scale.unitsSource = std::get<std::string>(source->data);
    scale.requestedMeshUnitScale = number(member(units, "requested_mesh_unit_scale"));
    // The UV span from the certificate's texel density of the set.
    const json::Object* uv = object(member(object(member(&mesh.import_report, "certificate")), "uv"));
    const json::Object* grid = object(member(uv, "grid"));
    const std::optional<double> width = number(member(grid, "width"));
    const std::optional<double> height = number(member(grid, "height"));
    if (!width || !height || !(*width > 0.0) || !(*height > 0.0)) {
        return Refusal(std::string("the mesh import report has no certificate grid (certificate.uv.grid)"));
    }
    scale.textureSet = set.material_id;
    const json::Object* metrics = object(member(object(member(uv, "per_set")), set.material_id));
    const std::optional<double> density = number(member(object(member(metrics, "density_px_per_cm")), "p50"));
    if (!density || !std::isfinite(*density) || !(*density > 0.0)) {
        return Refusal("the mesh certificate has no texel density for texture set " + set.material_id);
    }
    scale.densityPxPerCm = *density;
    scale.grid = {static_cast<int64_t>(*width), static_cast<int64_t>(*height)};
    scale.cmPerUv = std::sqrt(*width * *height) / *density;
    for (size_t i = 0; i < 2; ++i) {
        scale.texturesPerFileUnit[i] = scale.cmPerFileUnit / scale.physicalSizeCm[i];
        scale.uvScale[i] = scale.cmPerUv / scale.physicalSizeCm[i];
    }
    return scale;
}

std::expected<core::RequestOutcome, UnsupportedProcedural> SetMaterialSource(
    core::Id layer, const core::ProceduralRef& ref, const UseContext& context, const AssetLibrary& library,
    const ProceduralSeam& seam, const SubmitEdit& submit) {
    const std::expected<std::vector<MaterialChannelRequest>, UnsupportedProcedural> requests =
        MaterialRequests(ref, context, library);
    if (!requests) return Refused(requests.error());
    for (const MaterialChannelRequest& channel : *requests) {
        const std::expected<IProceduralBackend*, UnsupportedProcedural> backend = Admit(channel.request, library, seam);
        if (!backend) return Refused(backend.error());
    }
    return submit([&](core::Edit& edit) {
        core::Layer* target = core::FindLayer(edit.project(), layer);
        if (target == nullptr) throw core::ValueError("no layer " + std::to_string(layer));
        if (target->kind != core::LayerKind::fill || !target->fill) {
            throw core::ValueError("layer " + std::to_string(layer) + " is not a fill layer");
        }
        target->fill->source_mode = core::SourceMode::Material;
        target->fill->material_source = core::Source{core::ProceduralSource{ref}};
    });
}

}  // namespace uzp::procedural
