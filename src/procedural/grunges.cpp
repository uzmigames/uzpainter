#include "procedural/grunges.h"

#include "procedural/primitives.h"

#include "uzp_core/document/nodes.h"
#include "uzp_core/types/errors.h"

#include <bit>
#include <cmath>
#include <memory>

namespace uzp::procedural {

namespace {

using NotRegistered = std::expected<void, std::string>::unexpected_type;
using WordsOrError = std::expected<std::vector<uint32_t>, std::string>;
/// `std::unexpected<std::string>` (the bare name is ambiguous with Zig's libc++, see seam.h).
using Error = WordsOrError::unexpected_type;

// ── The parameter block (the kernel's `ProcParam` words) ──────────────────────

enum Kind : uint32_t { kFbm = 0, kRidged = 1, kSpots = 2, kScratches = 3, kCracks = 4, kWeave = 5 };

enum Word : uint32_t {
    wKind = 0,
    wPeriodX = 1,  ///< Cells across the tile (the asset's period times `tiling`).
    wPeriodY = 2,
    wLayers = 3,   ///< Octaves (fBm, ridged) or layers (spots, scratches).
    wGain = 4,     ///< fBm amplitude ratio per octave.
    wNorm = 5,     ///< fBm: stretch / 2 / sum of amplitudes; ridged: 1 / sum of amplitudes.
    wSalt = 6,     ///< Added to the request seed.
    wFlipX = 7,
    wFlipY = 8,
    wShift = 9,      ///< balance - 1/2.
    wContrast = 10,  ///< 1 / (1 - 0.9 contrast).
    wInvert = 11,
    wBreakup = 12,  ///< Amount of the fBm break-up (0: none).
    wBreakupPeriod = 13,
    wBreakupOctaves = 14,
    wBreakupScale = 15,  ///< Break-up period / resolution.
    wBreakupNorm = 16,   ///< Break-up stretch / 2 / sum of amplitudes.
    wScaleX = 17,        ///< Period / resolution.
    wScaleY = 18,
    wA = 19,  ///< spots: jitter; scratches: half length; cracks: 1 / width; weave: tension.
    wB = 20,  ///< spots: hard-edge gain (0: soft); scratches: 1 / width^2; cracks: hardness.
    wC = 21,  ///< spots: density; scratches: keep probability.
    wD = 22,  ///< scratches: 1 / half length^2.
    wTableCount = 23,
    wTable = 24,  ///< spots: 8 values 1 / r^2; scratches: 16 (cos, sin) pairs.
};

constexpr uint32_t kBreakupSeed = 1000;  // the break-up's seed offset from the asset's seed
constexpr uint32_t kRadiusClasses = 8;
constexpr uint32_t kDirections = 16;

/// The fixed configuration of one asset (decision 331): UzPainter's own design, not fitted.
struct Shape {
    std::string_view id;
    Kind kind;
    uint32_t periodX;
    uint32_t periodY;
    uint32_t layers;
    double gain = 0.5;     ///< fBm and ridged.
    double stretch = 1.0;  ///< fBm: the spread of the normalised sum about 1/2.
    double breakup = 0.0;
    uint32_t breakupPeriod = 1;
    uint32_t breakupOctaves = 0;
    double jitter = 1.0;  ///< spots without a `disorder` parameter.
    double edge = 0.0;    ///< spots: 0 soft, else the hard-edge gain.
    double density = 1.0; ///< spots: presence probability; scratches: keep probability.
    double radiusMin = 0.0;  ///< spots, in cells.
    double radiusMax = 0.0;
    double halfLength = 0.0;  ///< scratches, in cells.
    double width = 0.0;       ///< scratches, in cells.
    uint32_t salt = 0;
};

// The inventory's assets (docs/analysis/proc-grunge-families/01-asset-inventory.md).
constexpr Shape kShapes[] = {
    {.id = "rock", .kind = kFbm, .periodX = 4, .periodY = 4, .layers = 6, .gain = 0.5, .stretch = 1.6, .salt = 0x1001},
    {.id = "stone-details", .kind = kRidged, .periodX = 8, .periodY = 8, .layers = 5, .gain = 0.5, .salt = 0x1002},
    {.id = "dirt-large", .kind = kFbm, .periodX = 2, .periodY = 2, .layers = 6, .gain = 0.6, .stretch = 1.8, .salt = 0x1003},
    {.id = "dirt-spots-small", .kind = kSpots, .periodX = 24, .periodY = 24, .layers = 2, .breakup = 0.6,
     .breakupPeriod = 3, .breakupOctaves = 4, .density = 0.85, .radiusMin = 0.12, .radiusMax = 0.32, .salt = 0x1004},
    {.id = "spots-bw-a", .kind = kSpots, .periodX = 10, .periodY = 10, .layers = 1, .edge = 6.0, .density = 0.7,
     .radiusMin = 0.18, .radiusMax = 0.45, .salt = 0x1005},
    {.id = "spots-bw-b", .kind = kSpots, .periodX = 14, .periodY = 14, .layers = 2, .edge = 6.0, .density = 0.6,
     .radiusMin = 0.15, .radiusMax = 0.4, .salt = 0x1006},
    {.id = "dirt-a", .kind = kSpots, .periodX = 6, .periodY = 6, .layers = 3, .breakup = 0.7, .breakupPeriod = 4,
     .breakupOctaves = 4, .density = 0.9, .radiusMin = 0.1, .radiusMax = 0.5, .salt = 0x1007},
    {.id = "scratches-fine", .kind = kScratches, .periodX = 20, .periodY = 20, .layers = 2, .density = 0.55,
     .halfLength = 0.8, .width = 0.03, .salt = 0x1008},
    {.id = "scratches", .kind = kScratches, .periodX = 10, .periodY = 10, .layers = 2, .density = 0.6,
     .halfLength = 0.9, .width = 0.04, .salt = 0x1009},
    {.id = "scratches-dirty", .kind = kScratches, .periodX = 14, .periodY = 14, .layers = 2, .breakup = 0.7,
     .breakupPeriod = 4, .breakupOctaves = 4, .density = 0.7, .halfLength = 0.85, .width = 0.06, .salt = 0x100A},
    {.id = "rust-fine", .kind = kSpots, .periodX = 40, .periodY = 40, .layers = 3, .breakup = 0.8, .breakupPeriod = 5,
     .breakupOctaves = 4, .jitter = 1.0, .density = 0.8, .radiusMin = 0.2, .radiusMax = 0.5, .salt = 0x100B},
    {.id = "humidity", .kind = kFbm, .periodX = 6, .periodY = 1, .layers = 6, .gain = 0.55, .stretch = 1.6, .salt = 0x100C},
    {.id = "map-a", .kind = kFbm, .periodX = 5, .periodY = 5, .layers = 7, .gain = 0.55, .stretch = 1.7, .breakup = 0.4,
     .breakupPeriod = 2, .breakupOctaves = 3, .salt = 0x100D},
    {.id = "map-b", .kind = kRidged, .periodX = 3, .periodY = 3, .layers = 6, .gain = 0.55, .salt = 0x100E},
    {.id = "spots-soft", .kind = kSpots, .periodX = 6, .periodY = 6, .layers = 1, .density = 1.0, .radiusMin = 0.3,
     .radiusMax = 0.5, .salt = 0x100F},
    {.id = "cracks-leather", .kind = kCracks, .periodX = 10, .periodY = 10, .layers = 1, .breakup = 0.6,
     .breakupPeriod = 4, .breakupOctaves = 3, .salt = 0x1010},
    {.id = "linen", .kind = kWeave, .periodX = 48, .periodY = 48, .layers = 1, .breakup = 0.25, .breakupPeriod = 8,
     .breakupOctaves = 2, .salt = 0x1011},
};

constexpr std::string_view kIds[] = {
    "rock",        "stone-details",  "dirt-large", "dirt-spots-small", "spots-bw-a", "spots-bw-b",
    "dirt-a",      "scratches-fine", "scratches",  "scratches-dirty",  "rust-fine",  "humidity",
    "map-a",       "map-b",          "spots-soft", "cracks-leather",   "linen",
};
static_assert(std::size(kIds) == std::size(kShapes));

const Shape* FindShape(std::string_view id) {
    for (const Shape& shape : kShapes) {
        if (shape.id == id) return &shape;
    }
    return nullptr;
}

uint32_t Bits(float value) { return std::bit_cast<uint32_t>(value); }
float Float(uint32_t bits) { return std::bit_cast<float>(bits); }
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
std::pair<double, double> DeterministicSinCos(double theta) {
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

/// The sum of the amplitudes 1, gain, gain^2, ... of `octaves` octaves, as the kernel forms them.
double AmplitudeSum(float gain, uint32_t octaves) {
    double sum = 0.0;
    float amplitude = 1.0f;
    for (uint32_t k = 0; k < octaves; ++k) {
        sum += amplitude;
        amplitude = prim::Mul(amplitude, gain);
    }
    return sum;
}

WordsOrError Words(const Shape& shape, const ProceduralRequest& request) {
    const Params& p = request.params;
    const auto need = [&](const std::string& name) -> std::expected<double, std::string> {
        if (std::optional<double> value = Number(p, name)) return *value;
        return std::expected<double, std::string>::unexpected_type("the request has no number " + name);
    };
    const std::expected<double, std::string> balance = need("balance");
    const std::expected<double, std::string> contrast = need("contrast");
    const std::expected<double, std::string> invert = need("invert");
    const std::expected<double, std::string> tiling = need("tiling");
    for (const auto* v : {&balance, &contrast, &invert, &tiling}) {
        if (!*v) return Error(v->error());
    }
    const double resolution = request.output.resolution;
    if (resolution <= 0.0) return Error(std::string("the request has no output resolution"));
    const uint32_t repeats = static_cast<uint32_t>(*tiling);
    if (static_cast<double>(repeats) != *tiling || repeats == 0) {
        return Error("tiling must be a whole number of repeats, not " + std::to_string(*tiling));
    }
    std::vector<uint32_t> w(wTable, 0u);
    w[wKind] = shape.kind;
    w[wPeriodX] = shape.periodX * repeats;
    w[wPeriodY] = shape.periodY * repeats;
    w[wLayers] = shape.layers;
    const float gain = static_cast<float>(shape.gain);
    w[wGain] = Bits(gain);
    const double amplitudes = AmplitudeSum(gain, shape.layers);
    w[wNorm] = FloatWord(shape.kind == kRidged ? 1.0 / amplitudes : shape.stretch * 0.5 / amplitudes);
    w[wSalt] = shape.salt;
    w[wFlipX] = Number(p, "flip_horizontal").value_or(0.0) != 0.0 ? 1u : 0u;
    w[wFlipY] = Number(p, "flip_vertical").value_or(0.0) != 0.0 ? 1u : 0u;
    w[wShift] = FloatWord(*balance - 0.5);
    w[wContrast] = FloatWord(1.0 / (1.0 - 0.9 * *contrast));
    w[wInvert] = *invert != 0.0 ? 1u : 0u;
    w[wBreakup] = FloatWord(shape.breakup);
    w[wBreakupPeriod] = shape.breakupPeriod * repeats;
    w[wBreakupOctaves] = shape.breakupOctaves;
    w[wBreakupScale] = FloatWord(double(w[wBreakupPeriod]) / resolution);
    w[wBreakupNorm] = FloatWord(shape.breakupOctaves == 0 ? 0.0 : 1.6 * 0.5 / AmplitudeSum(0.5f, shape.breakupOctaves));
    w[wScaleX] = FloatWord(double(w[wPeriodX]) / resolution);
    w[wScaleY] = FloatWord(double(w[wPeriodY]) / resolution);
    switch (shape.kind) {
        case kSpots: {
            const std::optional<double> disorder = Number(p, "disorder");
            w[wA] = FloatWord(disorder ? 0.5 + 0.5 * *disorder : shape.jitter);
            w[wB] = FloatWord(shape.edge);
            w[wC] = FloatWord(shape.density);
            w[wTableCount] = kRadiusClasses;
            for (uint32_t c = 0; c < kRadiusClasses; ++c) {
                const double r = shape.radiusMin + (shape.radiusMax - shape.radiusMin) * c / (kRadiusClasses - 1);
                w.push_back(FloatWord(1.0 / (r * r)));
            }
            break;
        }
        case kScratches: {
            const std::expected<double, std::string> variation = need("rotation_variation");
            if (!variation) return Error(variation.error());
            w[wA] = FloatWord(shape.halfLength);
            w[wB] = FloatWord(1.0 / (shape.width * shape.width));
            w[wC] = FloatWord(shape.density);
            w[wD] = FloatWord(1.0 / (shape.halfLength * shape.halfLength));
            w[wTableCount] = 2 * kDirections;
            for (uint32_t k = 0; k < kDirections; ++k) {
                const double degrees = *variation * (double(k) / kDirections - 0.5);
                const auto [sine, cosine] = DeterministicSinCos(degrees * (3.141592653589793 / 180.0));
                w.push_back(FloatWord(cosine));
                w.push_back(FloatWord(sine));
            }
            break;
        }
        case kCracks: {
            const std::expected<double, std::string> hardness = need("hardness");
            const std::expected<double, std::string> shapeParam = need("shape");
            if (!hardness) return Error(hardness.error());
            if (!shapeParam) return Error(shapeParam.error());
            w[wA] = FloatWord(1.0 / (0.02 + 0.10 * *shapeParam));
            w[wB] = FloatWord(*hardness);
            break;
        }
        case kWeave: {
            const std::expected<double, std::string> tension = need("tension_variation");
            if (!tension) return Error(tension.error());
            w[wA] = FloatWord(*tension);
            break;
        }
        case kFbm:
        case kRidged: break;
    }
    return w;
}

// ── The CPU reference (the kernel's mirror, operation for operation) ──────────

using prim::Add;
using prim::Lerp;
using prim::Mul;
using prim::Sub;

constexpr float kUnit24 = 0x1.0p-24f;
constexpr float kUnit8 = 0x1.0p-8f;

int32_t WrapIndex(int32_t i, int32_t n) { return ((i % n) + n) % n; }

prim::U3 Hash(int32_t i, int32_t j, uint32_t px, uint32_t py, const prim::U3& offset) {
    return prim::CellHash(WrapIndex(i, static_cast<int32_t>(px)), WrapIndex(j, static_cast<int32_t>(py)), 0, offset);
}

/// The high 24 bits of a hash in [0, 1).
float Unit(uint32_t h) { return Mul(static_cast<float>(h >> 8), kUnit24); }
/// The low 8 bits of a hash in [0, 1).
float Byte(uint32_t h) { return Mul(static_cast<float>(h & 255u), kUnit8); }
float Min1(float v) { return v > 1.0f ? 1.0f : v; }
float Clamp01(float v) { return v < 0.0f ? 0.0f : (v > 1.0f ? 1.0f : v); }

/// Perlin 2002's gradient on the z = 0 plane: u is x for h < 8, else y; v is y for h < 4, x for
/// h 12 or 14, else z (0 here, so its term is left out); signs from bits 0 and 1.
float Grad(uint32_t hash, float x, float y) {
    const uint32_t h = hash & 15u;
    const float u = h < 8u ? x : y;
    const float su = (h & 1u) == 0u ? u : -u;
    if (h >= 4u && h != 12u && h != 14u) return su;
    const float v = h < 4u ? y : x;
    return Add(su, (h & 2u) == 0u ? v : -v);
}

/// Periodic Perlin 2002 gradient noise on the z = 0 plane: periods px, py cells.
float Gradient(float x, float y, uint32_t px, uint32_t py, const prim::U3& offset) {
    const float fx = std::floor(x);
    const float fy = std::floor(y);
    const int32_t i = static_cast<int32_t>(fx);
    const int32_t j = static_cast<int32_t>(fy);
    const float u = Sub(x, fx);
    const float v = Sub(y, fy);
    const float u1 = Sub(u, 1.0f);
    const float v1 = Sub(v, 1.0f);
    const float n00 = Grad(Hash(i, j, px, py, offset)[0], u, v);
    const float n10 = Grad(Hash(i + 1, j, px, py, offset)[0], u1, v);
    const float n01 = Grad(Hash(i, j + 1, px, py, offset)[0], u, v1);
    const float n11 = Grad(Hash(i + 1, j + 1, px, py, offset)[0], u1, v1);
    const float a = prim::Fade2002(u);
    const float b = prim::Fade2002(v);
    return Lerp(Lerp(n00, n10, a), Lerp(n01, n11, a), b);
}

/// fBm of `Gradient`, lacunarity 2 (each octave doubles the coordinate and the periods), octave
/// k seeded seed + k; ridged sums (1 - |n|)^2.
float Fbm(float x, float y, uint32_t px, uint32_t py, uint32_t octaves, float gain, uint32_t seed, bool ridged) {
    float sum = 0.0f;
    float amplitude = 1.0f;
    for (uint32_t k = 0; k < octaves; ++k) {
        float n = Gradient(x, y, px, py, prim::SeedOffset(seed + k));
        if (ridged) {
            const float r = Sub(1.0f, std::fabs(n));
            n = Mul(r, r);
        }
        sum = Add(sum, Mul(amplitude, n));
        x = Mul(x, 2.0f);
        y = Mul(y, 2.0f);
        px *= 2u;
        py *= 2u;
        amplitude = Mul(amplitude, gain);
    }
    return sum;
}

float Spots(std::span<const uint32_t> w, float x, float y, uint32_t px, uint32_t py, uint32_t layers, uint32_t seed) {
    const float jitter = Float(w[wA]);
    const float edge = Float(w[wB]);
    const float density = Float(w[wC]);
    float best = 0.0f;
    for (uint32_t k = 0; k < layers; ++k) {
        const prim::U3 offset = prim::SeedOffset(seed + k);
        const float fx = std::floor(x);
        const float fy = std::floor(y);
        const int32_t i = static_cast<int32_t>(fx);
        const int32_t j = static_cast<int32_t>(fy);
        const float u = Sub(x, fx);
        const float v = Sub(y, fy);
        for (int32_t dy = -1; dy <= 1; ++dy) {
            for (int32_t dx = -1; dx <= 1; ++dx) {
                const prim::U3 h = Hash(i + dx, j + dy, px, py, offset);
                if (!(Unit(h[2]) < density)) continue;
                const float cx = Add(static_cast<float>(dx), Add(0.5f, Mul(jitter, Sub(Unit(h[0]), 0.5f))));
                const float cy = Add(static_cast<float>(dy), Add(0.5f, Mul(jitter, Sub(Unit(h[1]), 0.5f))));
                const float ox = Sub(cx, u);
                const float oy = Sub(cy, v);
                const float t = Mul(Add(Mul(ox, ox), Mul(oy, oy)), Float(w[wTable + (h[1] & 7u)]));
                if (!(t < 1.0f)) continue;
                const float s = Sub(1.0f, t);
                float value = edge > 0.0f ? Min1(Mul(s, edge)) : Mul(s, s);
                value = Mul(value, Add(0.5f, Mul(0.5f, Byte(h[0]))));
                if (value > best) best = value;
            }
        }
        x = Mul(x, 2.0f);
        y = Mul(y, 2.0f);
        px *= 2u;
        py *= 2u;
    }
    return best;
}

float Scratches(std::span<const uint32_t> w, float x, float y, uint32_t px, uint32_t py, uint32_t layers,
                uint32_t seed) {
    const float halfLength = Float(w[wA]);
    const float invWidth2 = Float(w[wB]);
    const float keep = Float(w[wC]);
    const float invLength2 = Float(w[wD]);
    float best = 0.0f;
    for (uint32_t k = 0; k < layers; ++k) {
        const prim::U3 offset = prim::SeedOffset(seed + k);
        const float fx = std::floor(x);
        const float fy = std::floor(y);
        const int32_t i = static_cast<int32_t>(fx);
        const int32_t j = static_cast<int32_t>(fy);
        const float u = Sub(x, fx);
        const float v = Sub(y, fy);
        for (int32_t dy = -1; dy <= 1; ++dy) {
            for (int32_t dx = -1; dx <= 1; ++dx) {
                const prim::U3 h = Hash(i + dx, j + dy, px, py, offset);
                if (!(Unit(h[2]) < keep)) continue;
                const float cx = Add(static_cast<float>(dx), Unit(h[0]));
                const float cy = Add(static_cast<float>(dy), Unit(h[1]));
                const uint32_t d = wTable + 2u * (h[1] & 15u);
                const float c = Float(w[d]);
                const float s = Float(w[d + 1]);
                const float rx = Sub(u, cx);
                const float ry = Sub(v, cy);
                const float along = Add(Mul(rx, c), Mul(ry, s));
                const float perp = Sub(Mul(ry, c), Mul(rx, s));
                const float clamped = along < -halfLength ? -halfLength : (along > halfLength ? halfLength : along);
                const float da = Sub(along, clamped);
                const float t = Mul(Add(Mul(da, da), Mul(perp, perp)), invWidth2);
                if (!(t < 1.0f)) continue;
                const float taper = Sub(1.0f, Mul(Mul(clamped, clamped), invLength2));
                const float sw = Sub(1.0f, t);
                float value = Mul(Mul(sw, sw), taper);
                value = Mul(value, Add(0.5f, Mul(0.5f, Byte(h[0]))));
                if (value > best) best = value;
            }
        }
        x = Mul(x, 2.0f);
        y = Mul(y, 2.0f);
        px *= 2u;
        py *= 2u;
    }
    return best;
}

float Cracks(std::span<const uint32_t> w, float x, float y, uint32_t px, uint32_t py, uint32_t seed) {
    const float invWidth = Float(w[wA]);
    const float hardness = Float(w[wB]);
    const prim::U3 offset = prim::SeedOffset(seed);
    const float fx = std::floor(x);
    const float fy = std::floor(y);
    const int32_t i = static_cast<int32_t>(fx);
    const int32_t j = static_cast<int32_t>(fy);
    const float u = Sub(x, fx);
    const float v = Sub(y, fy);
    float d1 = Float(0x7F800000u);
    float d2 = Float(0x7F800000u);
    for (int32_t dy = -1; dy <= 1; ++dy) {
        for (int32_t dx = -1; dx <= 1; ++dx) {
            const prim::U3 h = Hash(i + dx, j + dy, px, py, offset);
            const float ox = Sub(Add(static_cast<float>(dx), Unit(h[0])), u);
            const float oy = Sub(Add(static_cast<float>(dy), Unit(h[1])), v);
            const float d = Add(Mul(ox, ox), Mul(oy, oy));
            if (d < d1) {
                d2 = d1;
                d1 = d;
            } else if (d < d2) {
                d2 = d;
            }
        }
    }
    const float t = Mul(Sub(prim::SqrtRn(d2), prim::SqrtRn(d1)), invWidth);
    if (!(t < 1.0f)) return 0.0f;
    const float s = Sub(1.0f, t);
    return Lerp(Mul(s, s), Min1(Mul(s, 3.0f)), hardness);
}

float Weave(std::span<const uint32_t> w, float x, float y, uint32_t px, uint32_t py, uint32_t seed) {
    const float tension = Float(w[wA]);
    const float fx = std::floor(x);
    const float fy = std::floor(y);
    const int32_t i = WrapIndex(static_cast<int32_t>(fx), static_cast<int32_t>(px));
    const int32_t j = WrapIndex(static_cast<int32_t>(fy), static_cast<int32_t>(py));
    const float u = Sub(x, fx);
    const float v = Sub(y, fy);
    const prim::U3 offset = prim::SeedOffset(seed);
    const bool warpOnTop = ((i + j) & 1) == 0;
    const float warpThickness =
        Add(1.0f, Mul(tension, Sub(Unit(prim::CellHash(i, 0, 1, offset)[0]), 0.5f)));
    const float weftThickness =
        Add(1.0f, Mul(tension, Sub(Unit(prim::CellHash(0, j, 2, offset)[0]), 0.5f)));
    const float a = Sub(Mul(u, 2.0f), 1.0f);
    const float b = Sub(Mul(v, 2.0f), 1.0f);
    const float acrossWarp = Sub(1.0f, Mul(a, a));  // the warp's profile across its width (u)
    const float acrossWeft = Sub(1.0f, Mul(b, b));  // the weft's profile across its width (v)
    const float warp = Mul(Mul(acrossWarp, warpThickness),
                           warpOnTop ? Add(0.6f, Mul(0.4f, acrossWeft)) : Mul(0.4f, Sub(1.0f, acrossWeft)));
    const float weft = Mul(Mul(acrossWeft, weftThickness),
                           warpOnTop ? Mul(0.4f, Sub(1.0f, acrossWarp)) : Add(0.6f, Mul(0.4f, acrossWarp)));
    return warp > weft ? warp : weft;
}

// The kernel: the same functions over `ProcParam`, operation for operation (see GrungeTexel).
constexpr std::string_view kGrungeBody = R"(
float GW(uint i) { return asfloat(ProcParam(i)); }

int GWrap(int i, int n) { return ((i % n) + n) % n; }

uint3 GHash(int i, int j, uint px, uint py, uint3 offset) {
    return CellHash(GWrap(i, int(px)), GWrap(j, int(py)), 0, offset);
}

float GUnit(uint h) { return Mul(Hash24(h), asfloat(0x33800000u)); }
float GByte(uint h) { return Mul(float(h & 255u), asfloat(0x3B800000u)); }
float GMin1(float v) { return v > 1.0f ? 1.0f : v; }
float GClamp01(float v) { return v < 0.0f ? 0.0f : (v > 1.0f ? 1.0f : v); }

float GGrad(uint hash, float x, float y) {
    const uint h = hash & 15u;
    const float u = h < 8u ? x : y;
    const float su = (h & 1u) == 0u ? u : -u;
    if (h >= 4u && h != 12u && h != 14u) return su;
    const float v = h < 4u ? y : x;
    return Add(su, (h & 2u) == 0u ? v : -v);
}

float GGradient(float x, float y, uint px, uint py, uint3 offset) {
    const float fx = floor(x);
    const float fy = floor(y);
    const int i = int(fx);
    const int j = int(fy);
    const float u = Sub(x, fx);
    const float v = Sub(y, fy);
    const float u1 = Sub(u, 1.0f);
    const float v1 = Sub(v, 1.0f);
    const float n00 = GGrad(GHash(i, j, px, py, offset).x, u, v);
    const float n10 = GGrad(GHash(i + 1, j, px, py, offset).x, u1, v);
    const float n01 = GGrad(GHash(i, j + 1, px, py, offset).x, u, v1);
    const float n11 = GGrad(GHash(i + 1, j + 1, px, py, offset).x, u1, v1);
    const float a = Fade2002(u);
    const float b = Fade2002(v);
    return Lerp(Lerp(n00, n10, a), Lerp(n01, n11, a), b);
}

float GFbm(float x, float y, uint px, uint py, uint octaves, float gain, uint seed, bool ridged) {
    float sum = 0.0f;
    float amplitude = 1.0f;
    for (uint k = 0u; k < octaves; ++k) {
        float n = GGradient(x, y, px, py, SeedOffset(seed + k));
        if (ridged) {
            const float r = Sub(1.0f, abs(n));
            n = Mul(r, r);
        }
        sum = Add(sum, Mul(amplitude, n));
        x = Mul(x, 2.0f);
        y = Mul(y, 2.0f);
        px *= 2u;
        py *= 2u;
        amplitude = Mul(amplitude, gain);
    }
    return sum;
}

float GSpots(float x, float y, uint px, uint py, uint layers, uint seed) {
    const float jitter = GW(19u);
    const float edge = GW(20u);
    const float density = GW(21u);
    float best = 0.0f;
    for (uint k = 0u; k < layers; ++k) {
        const uint3 offset = SeedOffset(seed + k);
        const float fx = floor(x);
        const float fy = floor(y);
        const int i = int(fx);
        const int j = int(fy);
        const float u = Sub(x, fx);
        const float v = Sub(y, fy);
        for (int dy = -1; dy <= 1; ++dy) {
            for (int dx = -1; dx <= 1; ++dx) {
                const uint3 h = GHash(i + dx, j + dy, px, py, offset);
                if (!(GUnit(h.z) < density)) continue;
                const float cx = Add(float(dx), Add(0.5f, Mul(jitter, Sub(GUnit(h.x), 0.5f))));
                const float cy = Add(float(dy), Add(0.5f, Mul(jitter, Sub(GUnit(h.y), 0.5f))));
                const float ox = Sub(cx, u);
                const float oy = Sub(cy, v);
                const float t = Mul(Add(Mul(ox, ox), Mul(oy, oy)), GW(24u + (h.y & 7u)));
                if (!(t < 1.0f)) continue;
                const float s = Sub(1.0f, t);
                float value = edge > 0.0f ? GMin1(Mul(s, edge)) : Mul(s, s);
                value = Mul(value, Add(0.5f, Mul(0.5f, GByte(h.x))));
                if (value > best) best = value;
            }
        }
        x = Mul(x, 2.0f);
        y = Mul(y, 2.0f);
        px *= 2u;
        py *= 2u;
    }
    return best;
}

float GScratches(float x, float y, uint px, uint py, uint layers, uint seed) {
    const float halfLength = GW(19u);
    const float invWidth2 = GW(20u);
    const float keep = GW(21u);
    const float invLength2 = GW(22u);
    float best = 0.0f;
    for (uint k = 0u; k < layers; ++k) {
        const uint3 offset = SeedOffset(seed + k);
        const float fx = floor(x);
        const float fy = floor(y);
        const int i = int(fx);
        const int j = int(fy);
        const float u = Sub(x, fx);
        const float v = Sub(y, fy);
        for (int dy = -1; dy <= 1; ++dy) {
            for (int dx = -1; dx <= 1; ++dx) {
                const uint3 h = GHash(i + dx, j + dy, px, py, offset);
                if (!(GUnit(h.z) < keep)) continue;
                const float cx = Add(float(dx), GUnit(h.x));
                const float cy = Add(float(dy), GUnit(h.y));
                const uint d = 24u + 2u * (h.y & 15u);
                const float c = GW(d);
                const float s = GW(d + 1u);
                const float rx = Sub(u, cx);
                const float ry = Sub(v, cy);
                const float along = Add(Mul(rx, c), Mul(ry, s));
                const float perp = Sub(Mul(ry, c), Mul(rx, s));
                const float clamped = along < -halfLength ? -halfLength : (along > halfLength ? halfLength : along);
                const float da = Sub(along, clamped);
                const float t = Mul(Add(Mul(da, da), Mul(perp, perp)), invWidth2);
                if (!(t < 1.0f)) continue;
                const float taper = Sub(1.0f, Mul(Mul(clamped, clamped), invLength2));
                const float sw = Sub(1.0f, t);
                float value = Mul(Mul(sw, sw), taper);
                value = Mul(value, Add(0.5f, Mul(0.5f, GByte(h.x))));
                if (value > best) best = value;
            }
        }
        x = Mul(x, 2.0f);
        y = Mul(y, 2.0f);
        px *= 2u;
        py *= 2u;
    }
    return best;
}

float GCracks(float x, float y, uint px, uint py, uint seed) {
    const float invWidth = GW(19u);
    const float hardness = GW(20u);
    const uint3 offset = SeedOffset(seed);
    const float fx = floor(x);
    const float fy = floor(y);
    const int i = int(fx);
    const int j = int(fy);
    const float u = Sub(x, fx);
    const float v = Sub(y, fy);
    float d1 = asfloat(0x7F800000u);
    float d2 = asfloat(0x7F800000u);
    for (int dy = -1; dy <= 1; ++dy) {
        for (int dx = -1; dx <= 1; ++dx) {
            const uint3 h = GHash(i + dx, j + dy, px, py, offset);
            const float ox = Sub(Add(float(dx), GUnit(h.x)), u);
            const float oy = Sub(Add(float(dy), GUnit(h.y)), v);
            const float d = Add(Mul(ox, ox), Mul(oy, oy));
            if (d < d1) {
                d2 = d1;
                d1 = d;
            } else if (d < d2) {
                d2 = d;
            }
        }
    }
    const float t = Mul(Sub(SqrtRn(d2), SqrtRn(d1)), invWidth);
    if (!(t < 1.0f)) return 0.0f;
    const float s = Sub(1.0f, t);
    return Lerp(Mul(s, s), GMin1(Mul(s, 3.0f)), hardness);
}

float GWeave(float x, float y, uint px, uint py, uint seed) {
    const float tension = GW(19u);
    const float fx = floor(x);
    const float fy = floor(y);
    const int i = GWrap(int(fx), int(px));
    const int j = GWrap(int(fy), int(py));
    const float u = Sub(x, fx);
    const float v = Sub(y, fy);
    const uint3 offset = SeedOffset(seed);
    const bool warpOnTop = ((i + j) & 1) == 0;
    const float warpThickness = Add(1.0f, Mul(tension, Sub(GUnit(CellHash(i, 0, 1, offset).x), 0.5f)));
    const float weftThickness = Add(1.0f, Mul(tension, Sub(GUnit(CellHash(0, j, 2, offset).x), 0.5f)));
    const float a = Sub(Mul(u, 2.0f), 1.0f);
    const float b = Sub(Mul(v, 2.0f), 1.0f);
    const float acrossWarp = Sub(1.0f, Mul(a, a));
    const float acrossWeft = Sub(1.0f, Mul(b, b));
    const float warp = Mul(Mul(acrossWarp, warpThickness),
                           warpOnTop ? Add(0.6f, Mul(0.4f, acrossWeft)) : Mul(0.4f, Sub(1.0f, acrossWeft)));
    const float weft = Mul(Mul(acrossWeft, weftThickness),
                           warpOnTop ? Mul(0.4f, Sub(1.0f, acrossWarp)) : Add(0.6f, Mul(0.4f, acrossWarp)));
    return warp > weft ? warp : weft;
}

float4 ProcTexel(int2 texel) {
    const uint kind = ProcParam(0u);
    const uint px = ProcParam(1u);
    const uint py = ProcParam(2u);
    const uint layers = ProcParam(3u);
    const uint seed = g_seed + ProcParam(6u);
    float x = Mul(Add(float(texel.x), 0.5f), GW(17u));
    float y = Mul(Add(float(texel.y), 0.5f), GW(18u));
    if (ProcParam(7u) != 0u) x = Sub(float(px), x);
    if (ProcParam(8u) != 0u) y = Sub(float(py), y);
    float raw;
    if (kind == 0u || kind == 1u) {
        const float sum = GFbm(x, y, px, py, layers, GW(4u), seed, kind == 1u);
        raw = kind == 0u ? Add(Mul(sum, GW(5u)), 0.5f) : Mul(sum, GW(5u));
    } else if (kind == 2u) {
        raw = GSpots(x, y, px, py, layers, seed);
    } else if (kind == 3u) {
        raw = GScratches(x, y, px, py, layers, seed);
    } else if (kind == 4u) {
        raw = GCracks(x, y, px, py, seed);
    } else {
        raw = GWeave(x, y, px, py, seed);
    }
    if (GW(12u) > 0.0f) {
        const uint bp = ProcParam(13u);
        float bx = Mul(Add(float(texel.x), 0.5f), GW(15u));
        float by = Mul(Add(float(texel.y), 0.5f), GW(15u));
        if (ProcParam(7u) != 0u) bx = Sub(float(bp), bx);
        if (ProcParam(8u) != 0u) by = Sub(float(bp), by);
        const float b = GClamp01(Add(Mul(GFbm(bx, by, bp, bp, ProcParam(14u), 0.5f, seed + 1000u, false), GW(16u)), 0.5f));
        raw = Mul(raw, Lerp(1.0f, b, GW(12u)));
    }
    float value = GClamp01(Add(Mul(Sub(Add(raw, GW(9u)), 0.5f), GW(10u)), 0.5f));
    if (ProcParam(11u) != 0u) value = Sub(1.0f, value);
    return float4(value, 0.0f, 0.0f, 0.0f);
}
)";

/// A grunge asset registered from its library record.
class GrungeFamily final : public IHlslFamily {
public:
    GrungeFamily(const AssetRecord& record, const Shape& shape) : m_shape(shape) {
        m_record.asset = record.asset;
        m_record.domain = record.domain;
        m_record.status = record.status;
        m_record.provenance = core::json::WriteCanonical(record.json);
    }

    const FamilyRecord& Record() const override { return m_record; }

    std::vector<KernelPass> Plan(const ProceduralRequest& request) const override {
        // Inside the domain every parameter is present, so the words are always built; a
        // request outside it is refused before planning, and an empty plan fails evaluation.
        WordsOrError words = Words(m_shape, request);
        if (!words) return {};
        return {KernelPass{"grunge_" + std::string(m_shape.id), std::string(kGrungeBody), std::move(*words), {}}};
    }

    Raster Reference(const ProceduralRequest& request, const InputImages&) const override {
        const WordsOrError words = Words(m_shape, request);
        const TileRect tile = request.tile.width != 0 && request.tile.height != 0
                                  ? request.tile
                                  : TileRect{0, 0, request.output.resolution, request.output.resolution};
        if (!words) return Raster{};
        Raster out{tile.width, tile.height, 1, {}};
        out.texels.reserve(size_t{tile.width} * tile.height);
        const uint32_t seed = static_cast<uint32_t>(request.seed);
        for (uint32_t y = 0; y < tile.height; ++y) {
            for (uint32_t x = 0; x < tile.width; ++x) {
                out.texels.push_back(GrungeTexel(*words, static_cast<int32_t>(tile.x + x),
                                                 static_cast<int32_t>(tile.y + y), seed));
            }
        }
        return out;
    }

private:
    FamilyRecord m_record;
    const Shape& m_shape;
};

}  // namespace

std::span<const std::string_view> GrungeAssetIds() { return kIds; }

std::expected<void, std::string> RegisterGrungeFamilies(HlslBackend& hlsl, const AssetLibrary& library) {
    for (const Shape& shape : kShapes) {
        const std::string url = "uzasset://" + std::string(kGrungeFamily) + "/" + std::string(shape.id) + "@1";
        const AssetRecord* record = library.Find(core::ParseAssetUrl(url));
        if (record == nullptr) return NotRegistered("the asset library holds no record of " + url);
        if (std::expected<void, std::string> registered = hlsl.Register(std::make_shared<GrungeFamily>(*record, shape));
            !registered) {
            return registered;
        }
    }
    return {};
}

std::expected<std::vector<uint32_t>, std::string> GrungeWords(const ProceduralRequest& request) {
    if (request.asset.family != kGrungeFamily) {
        return Error(AssetName(request) + " is not a grunge asset");
    }
    const Shape* shape = FindShape(request.asset.id);
    if (shape == nullptr) return Error(AssetName(request) + " is not an asset of the grunge family");
    return Words(*shape, request);
}

float GrungeTexel(std::span<const uint32_t> w, int32_t texelX, int32_t texelY, uint32_t requestSeed) {
    const uint32_t kind = w[wKind];
    const uint32_t px = w[wPeriodX];
    const uint32_t py = w[wPeriodY];
    const uint32_t layers = w[wLayers];
    const uint32_t seed = requestSeed + w[wSalt];
    float x = Mul(Add(static_cast<float>(texelX), 0.5f), Float(w[wScaleX]));
    float y = Mul(Add(static_cast<float>(texelY), 0.5f), Float(w[wScaleY]));
    if (w[wFlipX] != 0u) x = Sub(static_cast<float>(px), x);
    if (w[wFlipY] != 0u) y = Sub(static_cast<float>(py), y);
    float raw = 0.0f;
    if (kind == kFbm || kind == kRidged) {
        const float sum = Fbm(x, y, px, py, layers, Float(w[wGain]), seed, kind == kRidged);
        raw = kind == kFbm ? Add(Mul(sum, Float(w[wNorm])), 0.5f) : Mul(sum, Float(w[wNorm]));
    } else if (kind == kSpots) {
        raw = Spots(w, x, y, px, py, layers, seed);
    } else if (kind == kScratches) {
        raw = Scratches(w, x, y, px, py, layers, seed);
    } else if (kind == kCracks) {
        raw = Cracks(w, x, y, px, py, seed);
    } else {
        raw = Weave(w, x, y, px, py, seed);
    }
    if (Float(w[wBreakup]) > 0.0f) {
        const uint32_t bp = w[wBreakupPeriod];
        float bx = Mul(Add(static_cast<float>(texelX), 0.5f), Float(w[wBreakupScale]));
        float by = Mul(Add(static_cast<float>(texelY), 0.5f), Float(w[wBreakupScale]));
        if (w[wFlipX] != 0u) bx = Sub(static_cast<float>(bp), bx);
        if (w[wFlipY] != 0u) by = Sub(static_cast<float>(bp), by);
        const float b = Clamp01(Add(
            Mul(Fbm(bx, by, bp, bp, w[wBreakupOctaves], 0.5f, seed + kBreakupSeed, false), Float(w[wBreakupNorm])),
            0.5f));
        raw = Mul(raw, Lerp(1.0f, b, Float(w[wBreakup])));
    }
    float value = Clamp01(Add(Mul(Sub(Add(raw, Float(w[wShift])), 0.5f), Float(w[wContrast])), 0.5f));
    if (w[wInvert] != 0u) value = Sub(1.0f, value);
    return value;
}

std::expected<core::RequestOutcome, UnsupportedProcedural> SetGrungeSource(
    core::Id node, std::optional<core::ChannelType> channel, const core::ProceduralRef& ref, const UseContext& context,
    const AssetLibrary& library, const ProceduralSeam& seam, const SubmitEdit& submit) {
    return SetFillProcedural(node, channel, ref, context, library, seam, submit);
}

}  // namespace uzp::procedural
