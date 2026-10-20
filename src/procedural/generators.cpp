#include "procedural/generators.h"

#include "procedural/primitives.h"

#include "uzp_core/document/nodes.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/types/errors.h"

#include <bit>
#include <functional>
#include <memory>

namespace uzp::procedural {

namespace {

using NotRegistered = std::expected<void, std::string>::unexpected_type;
using core::MeshMapUsage;

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

/// An enumerated parameter (the domain lists integers; 1.0 equals 1).
int64_t IntParam(const Params& params, const std::string& name) {
    return static_cast<int64_t>(NumberParam(params, name));
}

/// float32(1 / (high - low)) of two ranged parameters, computed once on the host.
float InverseWidth(const Params& params, const std::string& low, const std::string& high) {
    return static_cast<float>(1.0 / (NumberParam(params, high) - NumberParam(params, low)));
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

std::string Name(MeshMapUsage usage) { return std::string(core::ToString(usage)); }

// ── The shared shaping (generators.h), on both sides ─────────────────────────

constexpr std::string_view kHelpersHlsl = R"(
float GenClamp01(float x) { return x > 0.0f ? (x < 1.0f ? x : 1.0f) : 0.0f; }

float GenBoxstep(float v, float low, float inv) { return GenClamp01(Mul(Sub(v, low), inv)); }

// Boxstep from parameter words first (low) and first + 1 (inverse width), then smoothstep when
// word first + 2 is set, then 1 - t when word first + 3 is set.
float GenShape(float v, uint first) {
    float t = GenBoxstep(v, asfloat(ProcParam(first)), asfloat(ProcParam(first + 1u)));
    if (ProcParam(first + 2u) != 0u) t = Fade1985(t);
    if (ProcParam(first + 3u) != 0u) t = Sub(1.0f, t);
    return t;
}
)";

float Clamp01(float x) { return x > 0.0f ? (x < 1.0f ? x : 1.0f) : 0.0f; }

float Boxstep(float v, float low, float inv) { return Clamp01(prim::Mul(prim::Sub(v, low), inv)); }

struct Shaping {
    float low = 0.0f;
    float inv = 1.0f;
    uint32_t smooth = 0;
    uint32_t invert = 0;

    [[nodiscard]] std::vector<uint32_t> Words() const { return {Bits(low), Bits(inv), smooth, invert}; }
    [[nodiscard]] float Apply(float v) const {
        float t = Boxstep(v, low, inv);
        if (smooth != 0) t = prim::Fade1985(t);
        if (invert != 0) t = prim::Sub(1.0f, t);
        return t;
    }
};

Shaping ShapingOf(const Params& params) {
    return Shaping{FloatParam(params, "low"), InverseWidth(params, "low", "high"),
                   static_cast<uint32_t>(IntParam(params, "smooth") != 0),
                   static_cast<uint32_t>(IntParam(params, "invert") != 0)};
}

/// Writes `value(px, py)` for every texel of the request's tile.
Raster OverTile(const ProceduralRequest& request, const std::function<float(int64_t, int64_t)>& value) {
    const TileRect tile = TileOf(request);
    Raster out{tile.width, tile.height, request.output.channels, {}};
    out.texels.reserve(size_t{tile.width} * tile.height);
    for (uint32_t y = 0; y < tile.height; ++y) {
        for (uint32_t x = 0; x < tile.width; ++x) {
            out.texels.push_back(value(int64_t{tile.x} + x, int64_t{tile.y} + y));
        }
    }
    return out;
}

constexpr prim::Border kClamp = prim::Border::Clamp;

/// A generator registered from its library record.
class GeneratorFamily : public IHlslFamily {
public:
    explicit GeneratorFamily(const AssetRecord& record) {
        m_record.asset = record.asset;
        m_record.domain = record.domain;
        m_record.status = record.status;
        m_record.provenance = core::json::WriteCanonical(record.json);
    }

    const FamilyRecord& Record() const override { return m_record; }

    std::optional<UnsupportedProcedural> JointRefusal(const ProceduralRequest& request) const override {
        return GeneratorJointRefusal(request);
    }

private:
    FamilyRecord m_record;
};

// ── The four mesh-map generators (item 2.2) ──────────────────────────────────

enum class Signal : uint8_t { Curvature, Position, WorldNormal, Occlusion };

/// `SignalValue(m, selector)`: the scalar a signal family shapes, from the mesh-map texel `m`.
std::string_view SignalHlsl(Signal signal) {
    switch (signal) {
        case Signal::Curvature:
            return R"(
float SignalValue(float4 m, uint s) { return s == 0u ? Sub(Mul(2.0f, m.x), 1.0f) : Sub(1.0f, Mul(2.0f, m.x)); }
)";
        case Signal::Position:
            return R"(
float SignalValue(float4 m, uint s) { return s == 0u ? m.x : (s == 1u ? m.y : m.z); }
)";
        case Signal::WorldNormal:
            return R"(
float SignalValue(float4 m, uint s) {
    const uint a = s >> 1u;
    const float c = a == 0u ? m.x : (a == 1u ? m.y : m.z);
    return (s & 1u) == 0u ? Sub(Mul(2.0f, c), 1.0f) : Sub(1.0f, Mul(2.0f, c));
}
)";
        case Signal::Occlusion:
            return R"(
float SignalValue(float4 m, uint s) { return Sub(1.0f, m.x); }
)";
    }
    return {};
}

constexpr std::string_view kSignalBody = R"(
float4 ProcTexel(int2 texel) {
    const float4 m = Texel(0u, texel.x, texel.y, BORDER_CLAMP);
    return float4(GenShape(SignalValue(m, ProcParam(0u)), 1u), 0.0f, 0.0f, 0.0f);
}
)";

class SignalFamily final : public GeneratorFamily {
public:
    SignalFamily(const AssetRecord& record, Signal signal) : GeneratorFamily(record), m_signal(signal) {}

    std::vector<KernelPass> Plan(const ProceduralRequest& request) const override {
        std::vector<uint32_t> words = {Selector(request.params)};
        const std::vector<uint32_t> shaping = ShapingOf(request.params).Words();
        words.insert(words.end(), shaping.begin(), shaping.end());
        std::string body(kHelpersHlsl);
        body += SignalHlsl(m_signal);
        body += kSignalBody;
        return {KernelPass{"generator_" + Record().asset.id, std::move(body), std::move(words),
                           {PassInput{Input(), -1}}}};
    }

    Raster Reference(const ProceduralRequest& request, const InputImages& inputs) const override {
        const Raster& map = inputs.at(Input());
        const uint32_t s = Selector(request.params);
        const Shaping shaping = ShapingOf(request.params);
        return OverTile(request, [&](int64_t x, int64_t y) {
            const auto c = [&](uint32_t channel) { return prim::Texel(map, x, y, channel, kClamp); };
            return shaping.Apply(Value(c, s));
        });
    }

private:
    std::string Input() const {
        switch (m_signal) {
            case Signal::Curvature: return Name(MeshMapUsage::Curvature);
            case Signal::Position: return Name(MeshMapUsage::Position);
            case Signal::WorldNormal: return Name(MeshMapUsage::WorldSpaceNormal);
            case Signal::Occlusion: return Name(MeshMapUsage::AO);
        }
        return {};
    }

    uint32_t Selector(const Params& params) const {
        switch (m_signal) {
            case Signal::Curvature: return static_cast<uint32_t>(IntParam(params, "mode"));
            case Signal::Position:
            case Signal::WorldNormal: return static_cast<uint32_t>(IntParam(params, "axis"));
            case Signal::Occlusion: return 0;
        }
        return 0;
    }

    /// The CPU mirror of `SignalValue`.
    template <class Channel>
    float Value(const Channel& c, uint32_t s) const {
        switch (m_signal) {
            case Signal::Curvature:
                return s == 0 ? prim::Sub(prim::Mul(2.0f, c(0)), 1.0f) : prim::Sub(1.0f, prim::Mul(2.0f, c(0)));
            case Signal::Position: return c(s);
            case Signal::WorldNormal: {
                const float n = c(s >> 1);
                return (s & 1) == 0 ? prim::Sub(prim::Mul(2.0f, n), 1.0f) : prim::Sub(1.0f, prim::Mul(2.0f, n));
            }
            case Signal::Occlusion: return prim::Sub(1.0f, c(0));
        }
        return 0.0f;
    }

    Signal m_signal;
};

// ── Shared passes: morphology and noise (items 2.3, 2.4) ─────────────────────

/// A disk dilation (word 1 set) or erosion of radius word 0 of input 0, clamped at the border.
constexpr std::string_view kMorphologyBody = R"(
float4 ProcTexel(int2 texel) {
    const float v = Morph(0u, texel, int(ProcParam(0u)), FOOTPRINT_DISK, BORDER_CLAMP, ProcParam(1u) != 0u).x;
    return float4(v, 0.0f, 0.0f, 0.0f);
}
)";

KernelPass MorphologyPass(std::string name, uint32_t radius, bool dilate, int32_t input) {
    return KernelPass{std::move(name), std::string(kMorphologyBody), {radius, dilate ? 1u : 0u}, {PassInput{{}, input}}};
}

Raster Morphology(const Raster& image, uint32_t radius, bool dilate) {
    return dilate ? prim::Dilate(image, radius, prim::Footprint::Disk, kClamp)
                  : prim::Erode(image, radius, prim::Footprint::Disk, kClamp);
}

/// The breakup noise: fBm of Perlin 2002 noise (four octaves, lacunarity 2, gain 1/2, the
/// request's seed) at the position-map texel `p` x `scale`.
constexpr std::string_view kNoiseHlsl = R"(
float GenNoise(float4 p, float scale) {
    return Fbm(FBM_PERLIN2002, float3(Mul(p.x, scale), Mul(p.y, scale), Mul(p.z, scale)), g_seed, 4u, 2.0f, 0.5f);
}
)";

float Noise(const Raster& position, int64_t x, int64_t y, float scale, uint32_t seed) {
    const prim::Vec3 p{prim::Mul(prim::Texel(position, x, y, 0, kClamp), scale),
                       prim::Mul(prim::Texel(position, x, y, 1, kClamp), scale),
                       prim::Mul(prim::Texel(position, x, y, 2, kClamp), scale)};
    return prim::Fbm(prim::FbmBasis::Perlin2002, p, seed, 4, 2.0f, 0.5f);
}

/// Writes `value(x, y)` for every texel of the whole `resolution` texture (an earlier pass).
Raster Whole(uint32_t resolution, const std::function<float(int64_t, int64_t)>& value) {
    Raster out{resolution, resolution, 1, {}};
    out.texels.reserve(size_t{resolution} * resolution);
    for (uint32_t y = 0; y < resolution; ++y) {
        for (uint32_t x = 0; x < resolution; ++x) out.texels.push_back(value(x, y));
    }
    return out;
}

// ── Dirt and Metal Edge Wear (item 2.3) ──────────────────────────────────────

enum class Wear : uint8_t { Dirt, EdgeWear };

// Pass 0 of Dirt: the weighted cavity clamp(1 - 2c) and occlusion 1 - ao, clamped.
constexpr std::string_view kDirtBaseBody = R"(
float4 ProcTexel(int2 texel) {
    const float c = Texel(0u, texel.x, texel.y, BORDER_CLAMP).x;
    const float ao = Texel(1u, texel.x, texel.y, BORDER_CLAMP).x;
    const float cavity = GenClamp01(Sub(1.0f, Mul(2.0f, c)));
    const float v = GenClamp01(Add(Mul(asfloat(ProcParam(0u)), cavity), Mul(asfloat(ProcParam(1u)), Sub(1.0f, ao))));
    return float4(v, 0.0f, 0.0f, 0.0f);
}
)";

// Pass 0 of Metal Edge Wear: the convex edges clamp(2c - 1) less occlusion_protect x (1 - ao).
constexpr std::string_view kEdgeBaseBody = R"(
float4 ProcTexel(int2 texel) {
    const float c = Texel(0u, texel.x, texel.y, BORDER_CLAMP).x;
    const float ao = Texel(1u, texel.x, texel.y, BORDER_CLAMP).x;
    const float edge = GenClamp01(Sub(Mul(2.0f, c), 1.0f));
    const float v = GenClamp01(Sub(edge, Mul(asfloat(ProcParam(0u)), Sub(1.0f, ao))));
    return float4(v, 0.0f, 0.0f, 0.0f);
}
)";

// Pass 2 of both: the spread mask plus noise_amount x noise, boxstepped from low to high.
constexpr std::string_view kBreakupBody = R"(
float4 ProcTexel(int2 texel) {
    const float base = Texel(0u, texel.x, texel.y, BORDER_CLAMP).x;
    const float4 p = Texel(1u, texel.x, texel.y, BORDER_CLAMP);
    const float v = Add(base, Mul(asfloat(ProcParam(1u)), GenNoise(p, asfloat(ProcParam(0u)))));
    return float4(GenBoxstep(v, asfloat(ProcParam(2u)), asfloat(ProcParam(3u))), 0.0f, 0.0f, 0.0f);
}
)";

class WearFamily final : public GeneratorFamily {
public:
    WearFamily(const AssetRecord& record, Wear wear) : GeneratorFamily(record), m_wear(wear) {}

    std::vector<KernelPass> Plan(const ProceduralRequest& request) const override {
        const Params& p = request.params;
        const std::string id = Record().asset.id;
        std::string base(kHelpersHlsl);
        base += m_wear == Wear::Dirt ? kDirtBaseBody : kEdgeBaseBody;
        std::vector<uint32_t> baseWords;
        if (m_wear == Wear::Dirt) {
            baseWords = {Bits(FloatParam(p, "cavity_weight")), Bits(FloatParam(p, "occlusion_weight"))};
        } else {
            baseWords = {Bits(FloatParam(p, "occlusion_protect"))};
        }
        std::string breakup(kHelpersHlsl);
        breakup += kNoiseHlsl;
        breakup += kBreakupBody;
        return {
            KernelPass{"generator_" + id + "_base", std::move(base), std::move(baseWords),
                       {PassInput{Name(MeshMapUsage::Curvature), -1}, PassInput{Name(MeshMapUsage::AO), -1}}},
            MorphologyPass("generator_" + id + "_spread", static_cast<uint32_t>(IntParam(p, "spread")), true, 0),
            KernelPass{"generator_" + id + "_breakup", std::move(breakup),
                       {Bits(FloatParam(p, "noise_scale")), Bits(FloatParam(p, "noise_amount")),
                        Bits(FloatParam(p, "low")), Bits(InverseWidth(p, "low", "high"))},
                       {PassInput{{}, 1}, PassInput{Name(MeshMapUsage::Position), -1}}},
        };
    }

    Raster Reference(const ProceduralRequest& request, const InputImages& inputs) const override {
        const Params& p = request.params;
        const Raster& curvature = inputs.at(Name(MeshMapUsage::Curvature));
        const Raster& ao = inputs.at(Name(MeshMapUsage::AO));
        const Raster& position = inputs.at(Name(MeshMapUsage::Position));
        const float w0 = FloatParam(p, m_wear == Wear::Dirt ? "cavity_weight" : "occlusion_protect");
        const float w1 = m_wear == Wear::Dirt ? FloatParam(p, "occlusion_weight") : 0.0f;
        const Raster base = Whole(request.output.resolution, [&](int64_t x, int64_t y) {
            const float c = prim::Texel(curvature, x, y, 0, kClamp);
            const float occlusion = prim::Sub(1.0f, prim::Texel(ao, x, y, 0, kClamp));
            if (m_wear == Wear::Dirt) {
                const float cavity = Clamp01(prim::Sub(1.0f, prim::Mul(2.0f, c)));
                return Clamp01(prim::Add(prim::Mul(w0, cavity), prim::Mul(w1, occlusion)));
            }
            const float edge = Clamp01(prim::Sub(prim::Mul(2.0f, c), 1.0f));
            return Clamp01(prim::Sub(edge, prim::Mul(w0, occlusion)));
        });
        const Raster spread = Morphology(base, static_cast<uint32_t>(IntParam(p, "spread")), true);
        const float scale = FloatParam(p, "noise_scale");
        const float amount = FloatParam(p, "noise_amount");
        const float low = FloatParam(p, "low");
        const float inv = InverseWidth(p, "low", "high");
        const auto seed = static_cast<uint32_t>(request.seed);
        return OverTile(request, [&](int64_t x, int64_t y) {
            const float v = prim::Add(prim::Texel(spread, x, y, 0, kClamp),
                                      prim::Mul(amount, Noise(position, x, y, scale, seed)));
            return Boxstep(v, low, inv);
        });
    }

private:
    Wear m_wear;
};

// ── Mask Builder (Legacy) and Mask Editor (item 2.4) ─────────────────────────

// The mesh-map terms both read, from input slots 0 (curvature), 1 (AO), 2 (position) and 3
// (world space normal).
constexpr std::string_view kTermsHlsl = R"(
float GenConvex(float c) { return GenClamp01(Sub(Mul(2.0f, c), 1.0f)); }
float GenCavity(float c) { return GenClamp01(Sub(1.0f, Mul(2.0f, c))); }
float GenUp(float4 n) { return GenClamp01(Sub(Mul(2.0f, n.y), 1.0f)); }
)";

float Convex(float c) { return Clamp01(prim::Sub(prim::Mul(2.0f, c), 1.0f)); }
float Cavity(float c) { return Clamp01(prim::Sub(1.0f, prim::Mul(2.0f, c))); }
float Up(float ny) { return Clamp01(prim::Sub(prim::Mul(2.0f, ny), 1.0f)); }

// Mask Builder pass 0: the selected source (convex edges, cavities, occlusion, height, upward
// normal), boxstepped.
constexpr std::string_view kBuilderSourceBody = R"(
float4 ProcTexel(int2 texel) {
    const float c = Texel(0u, texel.x, texel.y, BORDER_CLAMP).x;
    const float ao = Texel(1u, texel.x, texel.y, BORDER_CLAMP).x;
    const float4 p = Texel(2u, texel.x, texel.y, BORDER_CLAMP);
    const float4 n = Texel(3u, texel.x, texel.y, BORDER_CLAMP);
    const uint source = ProcParam(0u);
    float s = GenConvex(c);
    if (source == 1u) s = GenCavity(c);
    else if (source == 2u) s = Sub(1.0f, ao);
    else if (source == 3u) s = p.y;
    else if (source == 4u) s = GenUp(n);
    return float4(GenBoxstep(s, asfloat(ProcParam(1u)), asfloat(ProcParam(2u))), 0.0f, 0.0f, 0.0f);
}
)";

// Mask Builder pass 1: the noise mask Boxstep(0.5 N + 0.5) from noise_low to noise_high, mixed in
// by noise_amount: Lerp(t, t x mask, noise_amount).
constexpr std::string_view kBuilderNoiseBody = R"(
float4 ProcTexel(int2 texel) {
    const float t = Texel(0u, texel.x, texel.y, BORDER_CLAMP).x;
    const float4 p = Texel(1u, texel.x, texel.y, BORDER_CLAMP);
    const float n = Add(Mul(0.5f, GenNoise(p, asfloat(ProcParam(0u)))), 0.5f);
    const float m = GenBoxstep(n, asfloat(ProcParam(2u)), asfloat(ProcParam(3u)));
    return float4(Lerp(t, Mul(t, m), asfloat(ProcParam(1u))), 0.0f, 0.0f, 0.0f);
}
)";

// Mask Editor pass 0: the weighted sum of the convex edges, cavities, occlusion, height and
// upward normal, in that order.
constexpr std::string_view kEditorTermsBody = R"(
float4 ProcTexel(int2 texel) {
    const float c = Texel(0u, texel.x, texel.y, BORDER_CLAMP).x;
    const float ao = Texel(1u, texel.x, texel.y, BORDER_CLAMP).x;
    const float4 p = Texel(2u, texel.x, texel.y, BORDER_CLAMP);
    const float4 n = Texel(3u, texel.x, texel.y, BORDER_CLAMP);
    float sum = Mul(asfloat(ProcParam(0u)), GenConvex(c));
    sum = Add(sum, Mul(asfloat(ProcParam(1u)), GenCavity(c)));
    sum = Add(sum, Mul(asfloat(ProcParam(2u)), Sub(1.0f, ao)));
    sum = Add(sum, Mul(asfloat(ProcParam(3u)), p.y));
    sum = Add(sum, Mul(asfloat(ProcParam(4u)), GenUp(n)));
    return float4(sum, 0.0f, 0.0f, 0.0f);
}
)";

// Mask Editor pass 1: plus thickness_weight x thickness, boxstepped from low to high, inverted
// when `invert`.
constexpr std::string_view kEditorLevelsBody = R"(
float4 ProcTexel(int2 texel) {
    const float s = Add(Texel(0u, texel.x, texel.y, BORDER_CLAMP).x,
                        Mul(asfloat(ProcParam(0u)), Texel(1u, texel.x, texel.y, BORDER_CLAMP).x));
    float t = GenBoxstep(s, asfloat(ProcParam(1u)), asfloat(ProcParam(2u)));
    if (ProcParam(3u) != 0u) t = Sub(1.0f, t);
    return float4(t, 0.0f, 0.0f, 0.0f);
}
)";

std::vector<PassInput> TermInputs() {
    return {PassInput{Name(MeshMapUsage::Curvature), -1}, PassInput{Name(MeshMapUsage::AO), -1},
            PassInput{Name(MeshMapUsage::Position), -1}, PassInput{Name(MeshMapUsage::WorldSpaceNormal), -1}};
}

class MaskBuilderFamily final : public GeneratorFamily {
public:
    using GeneratorFamily::GeneratorFamily;

    std::vector<KernelPass> Plan(const ProceduralRequest& request) const override {
        const Params& p = request.params;
        const int64_t grow = IntParam(p, "grow");
        std::string source(kHelpersHlsl);
        source += kTermsHlsl;
        source += kBuilderSourceBody;
        std::string noise(kHelpersHlsl);
        noise += kNoiseHlsl;
        noise += kBuilderNoiseBody;
        return {
            KernelPass{"generator_mask_builder_source", std::move(source),
                       {static_cast<uint32_t>(IntParam(p, "source")), Bits(FloatParam(p, "low")),
                        Bits(InverseWidth(p, "low", "high"))},
                       TermInputs()},
            KernelPass{"generator_mask_builder_noise", std::move(noise),
                       {Bits(FloatParam(p, "noise_scale")), Bits(FloatParam(p, "noise_amount")),
                        Bits(FloatParam(p, "noise_low")), Bits(InverseWidth(p, "noise_low", "noise_high"))},
                       {PassInput{{}, 0}, PassInput{Name(MeshMapUsage::Position), -1}}},
            MorphologyPass("generator_mask_builder_grow", static_cast<uint32_t>(grow < 0 ? -grow : grow), grow >= 0, 1),
        };
    }

    Raster Reference(const ProceduralRequest& request, const InputImages& inputs) const override {
        const Params& p = request.params;
        const Raster& curvature = inputs.at(Name(MeshMapUsage::Curvature));
        const Raster& ao = inputs.at(Name(MeshMapUsage::AO));
        const Raster& position = inputs.at(Name(MeshMapUsage::Position));
        const Raster& normal = inputs.at(Name(MeshMapUsage::WorldSpaceNormal));
        const int64_t source = IntParam(p, "source");
        const float low = FloatParam(p, "low");
        const float inv = InverseWidth(p, "low", "high");
        const uint32_t resolution = request.output.resolution;
        const Raster shaped = Whole(resolution, [&](int64_t x, int64_t y) {
            const float c = prim::Texel(curvature, x, y, 0, kClamp);
            float s = Convex(c);
            if (source == 1) s = Cavity(c);
            else if (source == 2) s = prim::Sub(1.0f, prim::Texel(ao, x, y, 0, kClamp));
            else if (source == 3) s = prim::Texel(position, x, y, 1, kClamp);
            else if (source == 4) s = Up(prim::Texel(normal, x, y, 1, kClamp));
            return Boxstep(s, low, inv);
        });
        const float scale = FloatParam(p, "noise_scale");
        const float amount = FloatParam(p, "noise_amount");
        const float noiseLow = FloatParam(p, "noise_low");
        const float noiseInv = InverseWidth(p, "noise_low", "noise_high");
        const auto seed = static_cast<uint32_t>(request.seed);
        const Raster broken = Whole(resolution, [&](int64_t x, int64_t y) {
            const float t = prim::Texel(shaped, x, y, 0, kClamp);
            const float n = prim::Add(prim::Mul(0.5f, Noise(position, x, y, scale, seed)), 0.5f);
            return prim::Lerp(t, prim::Mul(t, Boxstep(n, noiseLow, noiseInv)), amount);
        });
        const int64_t grow = IntParam(p, "grow");
        const Raster grown = Morphology(broken, static_cast<uint32_t>(grow < 0 ? -grow : grow), grow >= 0);
        return OverTile(request, [&](int64_t x, int64_t y) { return prim::Texel(grown, x, y, 0, kClamp); });
    }
};

class MaskEditorFamily final : public GeneratorFamily {
public:
    using GeneratorFamily::GeneratorFamily;

    std::vector<KernelPass> Plan(const ProceduralRequest& request) const override {
        const Params& p = request.params;
        std::string terms(kHelpersHlsl);
        terms += kTermsHlsl;
        terms += kEditorTermsBody;
        std::string levels(kHelpersHlsl);
        levels += kEditorLevelsBody;
        return {
            KernelPass{"generator_mask_editor_terms", std::move(terms),
                       {Bits(FloatParam(p, "edges_weight")), Bits(FloatParam(p, "cavity_weight")),
                        Bits(FloatParam(p, "occlusion_weight")), Bits(FloatParam(p, "height_weight")),
                        Bits(FloatParam(p, "up_weight"))},
                       TermInputs()},
            KernelPass{"generator_mask_editor_levels", std::move(levels),
                       {Bits(FloatParam(p, "thickness_weight")), Bits(FloatParam(p, "low")),
                        Bits(InverseWidth(p, "low", "high")), static_cast<uint32_t>(IntParam(p, "invert") != 0)},
                       {PassInput{{}, 0}, PassInput{Name(MeshMapUsage::Thickness), -1}}},
        };
    }

    Raster Reference(const ProceduralRequest& request, const InputImages& inputs) const override {
        const Params& p = request.params;
        const Raster& curvature = inputs.at(Name(MeshMapUsage::Curvature));
        const Raster& ao = inputs.at(Name(MeshMapUsage::AO));
        const Raster& position = inputs.at(Name(MeshMapUsage::Position));
        const Raster& normal = inputs.at(Name(MeshMapUsage::WorldSpaceNormal));
        const Raster& thickness = inputs.at(Name(MeshMapUsage::Thickness));
        const float we = FloatParam(p, "edges_weight");
        const float wc = FloatParam(p, "cavity_weight");
        const float wo = FloatParam(p, "occlusion_weight");
        const float wh = FloatParam(p, "height_weight");
        const float wu = FloatParam(p, "up_weight");
        const float wt = FloatParam(p, "thickness_weight");
        const float low = FloatParam(p, "low");
        const float inv = InverseWidth(p, "low", "high");
        const bool invert = IntParam(p, "invert") != 0;
        return OverTile(request, [&](int64_t x, int64_t y) {
            const float c = prim::Texel(curvature, x, y, 0, kClamp);
            float sum = prim::Mul(we, Convex(c));
            sum = prim::Add(sum, prim::Mul(wc, Cavity(c)));
            sum = prim::Add(sum, prim::Mul(wo, prim::Sub(1.0f, prim::Texel(ao, x, y, 0, kClamp))));
            sum = prim::Add(sum, prim::Mul(wh, prim::Texel(position, x, y, 1, kClamp)));
            sum = prim::Add(sum, prim::Mul(wu, Up(prim::Texel(normal, x, y, 1, kClamp))));
            const float s = prim::Add(sum, prim::Mul(wt, prim::Texel(thickness, x, y, 0, kClamp)));
            const float t = Boxstep(s, low, inv);
            return invert ? prim::Sub(1.0f, t) : t;
        });
    }
};

// ── The registry ─────────────────────────────────────────────────────────────

struct Entry {
    std::string_view asset;
    std::vector<MeshMapUsage> usages;
    std::function<std::shared_ptr<const IHlslFamily>(const AssetRecord&)> make;
};

const std::vector<Entry>& Registry() {
    static const std::vector<Entry> entries = [] {
        const auto signal = [](Signal s) {
            return [s](const AssetRecord& r) -> std::shared_ptr<const IHlslFamily> {
                return std::make_shared<SignalFamily>(r, s);
            };
        };
        const auto wear = [](Wear w) {
            return [w](const AssetRecord& r) -> std::shared_ptr<const IHlslFamily> {
                return std::make_shared<WearFamily>(r, w);
            };
        };
        return std::vector<Entry>{
            {kCurvatureAsset, {MeshMapUsage::Curvature}, signal(Signal::Curvature)},
            {kPositionAsset, {MeshMapUsage::Position}, signal(Signal::Position)},
            {kWorldNormalAsset, {MeshMapUsage::WorldSpaceNormal}, signal(Signal::WorldNormal)},
            {kOcclusionAsset, {MeshMapUsage::AO}, signal(Signal::Occlusion)},
            {kDirtAsset, {MeshMapUsage::AO, MeshMapUsage::Curvature, MeshMapUsage::Position}, wear(Wear::Dirt)},
            {kEdgeWearAsset, {MeshMapUsage::AO, MeshMapUsage::Curvature, MeshMapUsage::Position},
             wear(Wear::EdgeWear)},
            {kMaskBuilderAsset,
             {MeshMapUsage::AO, MeshMapUsage::Curvature, MeshMapUsage::Position, MeshMapUsage::WorldSpaceNormal},
             [](const AssetRecord& r) -> std::shared_ptr<const IHlslFamily> {
                 return std::make_shared<MaskBuilderFamily>(r);
             }},
            {kMaskEditorAsset,
             {MeshMapUsage::AO, MeshMapUsage::Curvature, MeshMapUsage::Position, MeshMapUsage::Thickness,
              MeshMapUsage::WorldSpaceNormal},
             [](const AssetRecord& r) -> std::shared_ptr<const IHlslFamily> {
                 return std::make_shared<MaskEditorFamily>(r);
             }},
        };
    }();
    return entries;
}

const std::vector<std::string_view>& AssetNames() {
    static const std::vector<std::string_view> names = [] {
        std::vector<std::string_view> out;
        for (const Entry& entry : Registry()) out.push_back(entry.asset);
        return out;
    }();
    return names;
}

/// The sample type and channel count of a mesh-map binding's format.
std::pair<ChannelFormat, uint32_t> FormatOf(core::ChannelFormat format) {
    switch (format) {
        case core::ChannelFormat::L8: return {ChannelFormat::U8, 1};
        case core::ChannelFormat::sRGB8:
        case core::ChannelFormat::RGB8: return {ChannelFormat::U8, 3};
        case core::ChannelFormat::L16: return {ChannelFormat::U16, 1};
        case core::ChannelFormat::RGB16: return {ChannelFormat::U16, 3};
        case core::ChannelFormat::L16F: return {ChannelFormat::F16, 1};
        case core::ChannelFormat::RGB16F: return {ChannelFormat::F16, 3};
        case core::ChannelFormat::L32F: return {ChannelFormat::F32, 1};
        case core::ChannelFormat::RGB32F: return {ChannelFormat::F32, 3};
    }
    return {ChannelFormat::F32, 0};
}

render::TexelEncoding EncodingOf(ChannelFormat format) {
    switch (format) {
        case ChannelFormat::U8: return render::TexelEncoding::Unorm8;
        case ChannelFormat::U16: return render::TexelEncoding::Unorm16;
        case ChannelFormat::F16: return render::TexelEncoding::Float16;
        case ChannelFormat::F32: return render::TexelEncoding::Float32;
    }
    return render::TexelEncoding::Float32;
}

}  // namespace

std::span<const std::string_view> GeneratorAssets() { return AssetNames(); }

std::vector<core::MeshMapUsage> GeneratorUsages(const core::AssetUrl& asset) {
    for (const Entry& entry : Registry()) {
        const core::AssetUrl url = core::ParseAssetUrl(entry.asset);
        if (url.family == asset.family && url.id == asset.id) return entry.usages;
    }
    return {};
}

std::optional<UnsupportedProcedural> GeneratorJointRefusal(const ProceduralRequest& request) {
    for (const auto& [name, input] : request.inputs) {
        if (input.spec.resolution == request.output.resolution) continue;
        return UnsupportedProcedural{AssetName(request), std::string(kOutsideDomain), "inputs." + name + ".resolution",
                                     std::to_string(input.spec.resolution),
                                     "the output's resolution (" + std::to_string(request.output.resolution) + ")"};
    }
    return std::nullopt;
}

std::expected<void, std::string> RegisterGeneratorFamilies(HlslBackend& hlsl, const AssetLibrary& library) {
    for (const Entry& entry : Registry()) {
        const AssetRecord* record = library.Find(core::ParseAssetUrl(entry.asset));
        if (record == nullptr) return NotRegistered("the asset library holds no record of " + std::string(entry.asset));
        if (std::expected<void, std::string> registered = hlsl.Register(entry.make(*record)); !registered) {
            return registered;
        }
    }
    return {};
}

RasterSpec MeshMapSpec(const core::MeshMapBinding& binding, uint32_t resolution) {
    const auto [format, channels] = FormatOf(binding.format);
    return RasterSpec{resolution, format, binding.color_space, channels};
}

render::Result<BoundMeshMaps> BindMeshMaps(const core::TextureSet& set, std::span<const core::MeshMapUsage> usages,
                                           const evaluator::IResourceProvider& resources) {
    if (set.resolution.width != set.resolution.height || set.resolution.width <= 0) {
        return Failed("texture set " + set.name + " is " + std::to_string(set.resolution.width) + "x" +
                      std::to_string(set.resolution.height) + ": a generator reads square mesh maps only");
    }
    const auto resolution = static_cast<uint32_t>(set.resolution.width);
    BoundMeshMaps bound;
    for (const MeshMapUsage usage : usages) {
        const std::string name = Name(usage);
        const std::string what = "the " + name + " mesh map of texture set " + set.name;
        const auto binding = set.mesh_maps.find(usage);
        if (binding == set.mesh_maps.end()) return Failed("texture set " + set.name + " has no " + name + " mesh map");
        const core::MeshMapBinding& map = binding->second;
        if (map.invalid) {
            return Failed(what + " is invalid" +
                          (map.invalid_report ? ": " + core::json::WriteCanonical(core::json::Value(*map.invalid_report))
                                              : std::string()));
        }
        const RasterSpec spec = MeshMapSpec(map, resolution);
        const std::shared_ptr<const evaluator::DecodedImage> image = resources.Fetch(map.resource);
        if (!image) return Failed(what + ": its image " + map.resource + " is not available");
        if (image->width != resolution || image->height != resolution || image->channels != spec.channels ||
            image->encoding != EncodingOf(spec.format) ||
            image->values.size() != size_t{resolution} * resolution * spec.channels) {
            return Failed(what + " is invalid: its image is " + std::to_string(image->width) + "x" +
                          std::to_string(image->height) + "x" + std::to_string(image->channels) +
                          ", the binding declares " + std::to_string(resolution) + "x" + std::to_string(resolution) +
                          "x" + std::to_string(spec.channels) + " " + std::string(FormatName(spec.format)));
        }
        Raster raster{resolution, resolution, spec.channels, {}};
        raster.texels.reserve(image->values.size());
        const bool unorm = spec.format == ChannelFormat::U8 || spec.format == ChannelFormat::U16;
        const float max = spec.format == ChannelFormat::U8 ? 255.0f : 65535.0f;
        for (const uint32_t value : image->values) {
            raster.texels.push_back(unorm ? static_cast<float>(value) / max : std::bit_cast<float>(value));
        }
        bound.inputs[name] = ImageInput{spec, map.resource};
        bound.images[name] = std::move(raster);
    }
    return bound;
}

std::expected<ProceduralRequest, UnsupportedProcedural> GeneratorRequest(
    const core::ProceduralRef& ref, const UseContext& context, const std::map<std::string, ImageInput>& meshMaps,
    const AssetLibrary& library) {
    for (const auto& [name, binding] : ref.image_inputs) {
        if (!core::FromString<MeshMapUsage>(name)) continue;
        UnsupportedProcedural refusal = Refuse(ref.asset, "a generator reads its mesh maps by usage from the texture set");
        refusal.field = "inputs." + name;
        refusal.value = binding.sha256;
        refusal.certified = "the texture set's " + name + " mesh map";
        return Refused(std::move(refusal));
    }
    std::expected<ProceduralRequest, UnsupportedProcedural> request = RequestFor(ref, context, library);
    if (!request) return request;
    for (const auto& [name, input] : meshMaps) request->inputs[name] = input;
    return request;
}

std::expected<core::RequestOutcome, UnsupportedProcedural> SetGeneratorEffect(
    core::Id effect, const core::ProceduralRef& ref, const UseContext& context,
    const std::map<std::string, ImageInput>& meshMaps, const AssetLibrary& library, const ProceduralSeam& seam,
    const SubmitEdit& submit) {
    const std::expected<ProceduralRequest, UnsupportedProcedural> request =
        GeneratorRequest(ref, context, meshMaps, library);
    if (!request) return Refused(request.error());
    const std::expected<IProceduralBackend*, UnsupportedProcedural> backend = Admit(*request, library, seam);
    if (!backend) return Refused(backend.error());
    return submit([&](core::Edit& edit) {
        core::Effect* target = core::FindEffect(edit.project(), effect);
        if (target == nullptr) throw core::ValueError("no effect " + std::to_string(effect));
        if (target->kind != core::EffectKind::generator) {
            throw core::ValueError("effect " + std::to_string(effect) + " is not a generator effect");
        }
        target->procedural = ref;
    });
}

}  // namespace uzp::procedural
