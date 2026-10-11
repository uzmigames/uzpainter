#include "evaluator/arith.h"

#include "evaluator/hwmath.h"

#include <bit>
#include <cfenv>
#include <cmath>
#include <limits>

namespace uzp::evaluator::arith {

namespace {

/// float32 bits of the linear value of each sRGB8 code 0..255 (arith.h `Srgb8OperandTable`),
/// measured on the Tier 0 recording GPU by `uzp-evaluator-tests srgb8-hardware`.
constexpr uint32_t kSrgb8DecodeBits[256] = {
    0x00000000u, 0x39A00000u, 0x3A200000u, 0x3A700000u, 0x3AA00000u, 0x3AC80000u, 0x3AF00000u, 0x3B0C0000u,
    0x3B200000u, 0x3B340000u, 0x3B480000u, 0x3B5C0000u, 0x3B700000u, 0x3B840000u, 0x3B900000u, 0x3B9C0000u,
    0x3BAA0000u, 0x3BB80000u, 0x3BC60000u, 0x3BD60000u, 0x3BE60000u, 0x3BF60000u, 0x3C030000u, 0x3C0C0000u,
    0x3C160000u, 0x3C1F0000u, 0x3C290000u, 0x3C340000u, 0x3C3E0000u, 0x3C490000u, 0x3C550000u, 0x3C600000u,
    0x3C6C0000u, 0x3C7A0000u, 0x3C830000u, 0x3C8A0000u, 0x3C910000u, 0x3C980000u, 0x3C9F0000u, 0x3CA60000u,
    0x3CAE0000u, 0x3CB60000u, 0x3CBE0000u, 0x3CC60000u, 0x3CCE0000u, 0x3CD70000u, 0x3CE00000u, 0x3CE90000u,
    0x3CF20000u, 0x3CFC0000u, 0x3D030000u, 0x3D080000u, 0x3D0D0000u, 0x3D120000u, 0x3D170000u, 0x3D1C0000u,
    0x3D220000u, 0x3D280000u, 0x3D2D0000u, 0x3D330000u, 0x3D390000u, 0x3D3F0000u, 0x3D450000u, 0x3D4C0000u,
    0x3D520000u, 0x3D580000u, 0x3D600000u, 0x3D660000u, 0x3D6C0000u, 0x3D740000u, 0x3D7A0000u, 0x3D810000u,
    0x3D850000u, 0x3D880000u, 0x3D8C0000u, 0x3D900000u, 0x3D940000u, 0x3D980000u, 0x3D9C0000u, 0x3DA00000u,
    0x3DA40000u, 0x3DA90000u, 0x3DAD0000u, 0x3DB10000u, 0x3DB60000u, 0x3DBA0000u, 0x3DBF0000u, 0x3DC30000u,
    0x3DC80000u, 0x3DCD0000u, 0x3DD10000u, 0x3DD60000u, 0x3DDB0000u, 0x3DE00000u, 0x3DE50000u, 0x3DEA0000u,
    0x3DF00000u, 0x3DF40000u, 0x3DFA0000u, 0x3E000000u, 0x3E020000u, 0x3E050000u, 0x3E080000u, 0x3E0B0000u,
    0x3E0E0000u, 0x3E110000u, 0x3E140000u, 0x3E170000u, 0x3E1A0000u, 0x3E1D0000u, 0x3E200000u, 0x3E230000u,
    0x3E260000u, 0x3E290000u, 0x3E2C0000u, 0x3E300000u, 0x3E330000u, 0x3E360000u, 0x3E3A0000u, 0x3E3D0000u,
    0x3E400000u, 0x3E440000u, 0x3E470000u, 0x3E4B0000u, 0x3E4E0000u, 0x3E520000u, 0x3E560000u, 0x3E590000u,
    0x3E5D0000u, 0x3E610000u, 0x3E650000u, 0x3E680000u, 0x3E6C0000u, 0x3E700000u, 0x3E740000u, 0x3E780000u,
    0x3E7C0000u, 0x3E800000u, 0x3E820000u, 0x3E840000u, 0x3E860000u, 0x3E880000u, 0x3E8A0000u, 0x3E8D0000u,
    0x3E8F0000u, 0x3E910000u, 0x3E930000u, 0x3E950000u, 0x3E980000u, 0x3E9A0000u, 0x3E9C0000u, 0x3E9E0000u,
    0x3EA10000u, 0x3EA30000u, 0x3EA50000u, 0x3EA80000u, 0x3EAA0000u, 0x3EAD0000u, 0x3EAF0000u, 0x3EB20000u,
    0x3EB40000u, 0x3EB60000u, 0x3EB90000u, 0x3EBC0000u, 0x3EBE0000u, 0x3EC10000u, 0x3EC30000u, 0x3EC60000u,
    0x3EC80000u, 0x3ECB0000u, 0x3ECE0000u, 0x3ED10000u, 0x3ED30000u, 0x3ED60000u, 0x3ED90000u, 0x3EDB0000u,
    0x3EDE0000u, 0x3EE10000u, 0x3EE40000u, 0x3EE70000u, 0x3EEA0000u, 0x3EED0000u, 0x3EF00000u, 0x3EF20000u,
    0x3EF60000u, 0x3EF80000u, 0x3EFC0000u, 0x3EFE0000u, 0x3F010000u, 0x3F020000u, 0x3F040000u, 0x3F050000u,
    0x3F070000u, 0x3F090000u, 0x3F0A0000u, 0x3F0C0000u, 0x3F0D0000u, 0x3F0F0000u, 0x3F110000u, 0x3F120000u,
    0x3F140000u, 0x3F160000u, 0x3F170000u, 0x3F190000u, 0x3F1B0000u, 0x3F1C0000u, 0x3F1E0000u, 0x3F200000u,
    0x3F210000u, 0x3F230000u, 0x3F250000u, 0x3F270000u, 0x3F290000u, 0x3F2A0000u, 0x3F2C0000u, 0x3F2E0000u,
    0x3F300000u, 0x3F320000u, 0x3F330000u, 0x3F350000u, 0x3F370000u, 0x3F390000u, 0x3F3B0000u, 0x3F3D0000u,
    0x3F3F0000u, 0x3F410000u, 0x3F430000u, 0x3F450000u, 0x3F470000u, 0x3F490000u, 0x3F4B0000u, 0x3F4D0000u,
    0x3F4F0000u, 0x3F510000u, 0x3F530000u, 0x3F550000u, 0x3F570000u, 0x3F590000u, 0x3F5B0000u, 0x3F5D0000u,
    0x3F5F0000u, 0x3F610000u, 0x3F630000u, 0x3F650000u, 0x3F680000u, 0x3F6A0000u, 0x3F6C0000u, 0x3F6E0000u,
    0x3F700000u, 0x3F720000u, 0x3F740000u, 0x3F760000u, 0x3F7A0000u, 0x3F7C0000u, 0x3F7E0000u, 0x3F800000u,
};

/// float32 bits of the sRGB8 thresholds of codes 1..255 (arith.h `Srgb8Thresholds`), measured on
/// the Tier 0 recording GPU by `uzp-evaluator-tests srgb8-hardware`.
constexpr uint32_t kSrgb8ThresholdBits[255] = {
    0x39000000u, 0x39E00000u, 0x3A400000u, 0x3A880000u, 0x3AB00000u, 0x3AD80000u, 0x3B000000u, 0x3B140000u,
    0x3B280000u, 0x3B3C0000u, 0x3B500000u, 0x3B680000u, 0x3B7C0000u, 0x3B8A0000u, 0x3B960000u, 0x3BA40000u,
    0x3BB00000u, 0x3BC00000u, 0x3BCE0000u, 0x3BDC0000u, 0x3BEC0000u, 0x3BFE0000u, 0x3C080000u, 0x3C110000u,
    0x3C1A0000u, 0x3C240000u, 0x3C2E0000u, 0x3C380000u, 0x3C440000u, 0x3C500000u, 0x3C5A0000u, 0x3C660000u,
    0x3C740000u, 0x3C800000u, 0x3C860000u, 0x3C8D0000u, 0x3C940000u, 0x3C9B0000u, 0x3CA20000u, 0x3CAA0000u,
    0x3CB20000u, 0x3CBA0000u, 0x3CC20000u, 0x3CCA0000u, 0x3CD20000u, 0x3CDC0000u, 0x3CE40000u, 0x3CEE0000u,
    0x3CF60000u, 0x3D000000u, 0x3D050000u, 0x3D0A0000u, 0x3D0F0000u, 0x3D140000u, 0x3D1A0000u, 0x3D1F0000u,
    0x3D250000u, 0x3D2A0000u, 0x3D300000u, 0x3D360000u, 0x3D3C0000u, 0x3D420000u, 0x3D480000u, 0x3D4F0000u,
    0x3D550000u, 0x3D5C0000u, 0x3D620000u, 0x3D6A0000u, 0x3D700000u, 0x3D780000u, 0x3D7E0000u, 0x3D830000u,
    0x3D868000u, 0x3D8A0000u, 0x3D8E0000u, 0x3D920000u, 0x3D960000u, 0x3D9A0000u, 0x3D9E0000u, 0x3DA20000u,
    0x3DA60000u, 0x3DAB0000u, 0x3DAF0000u, 0x3DB30000u, 0x3DB80000u, 0x3DBC0000u, 0x3DC10000u, 0x3DC58000u,
    0x3DCA0000u, 0x3DCF0000u, 0x3DD40000u, 0x3DD90000u, 0x3DDE0000u, 0x3DE30000u, 0x3DE80000u, 0x3DED0000u,
    0x3DF20000u, 0x3DF80000u, 0x3DFD0000u, 0x3E010000u, 0x3E040000u, 0x3E068000u, 0x3E098000u, 0x3E0C8000u,
    0x3E0F0000u, 0x3E120000u, 0x3E150000u, 0x3E180000u, 0x3E1B0000u, 0x3E1E0000u, 0x3E210000u, 0x3E248000u,
    0x3E278000u, 0x3E2B0000u, 0x3E2E0000u, 0x3E310000u, 0x3E348000u, 0x3E380000u, 0x3E3B0000u, 0x3E3E8000u,
    0x3E420000u, 0x3E458000u, 0x3E490000u, 0x3E4C8000u, 0x3E500000u, 0x3E540000u, 0x3E578000u, 0x3E5B0000u,
    0x3E5F0000u, 0x3E630000u, 0x3E668000u, 0x3E6A0000u, 0x3E6E0000u, 0x3E720000u, 0x3E760000u, 0x3E7A0000u,
    0x3E7E0000u, 0x3E810000u, 0x3E830000u, 0x3E854000u, 0x3E878000u, 0x3E898000u, 0x3E8B8000u, 0x3E8D8000u,
    0x3E900000u, 0x3E920000u, 0x3E944000u, 0x3E968000u, 0x3E98C000u, 0x3E9B0000u, 0x3E9D8000u, 0x3E9F8000u,
    0x3EA20000u, 0x3EA48000u, 0x3EA68000u, 0x3EA90000u, 0x3EAB8000u, 0x3EAE0000u, 0x3EB08000u, 0x3EB28000u,
    0x3EB50000u, 0x3EB78000u, 0x3EBA0000u, 0x3EBD0000u, 0x3EBF8000u, 0x3EC20000u, 0x3EC48000u, 0x3EC70000u,
    0x3ECA0000u, 0x3ECC8000u, 0x3ECF0000u, 0x3ED20000u, 0x3ED48000u, 0x3ED78000u, 0x3EDA0000u, 0x3EDD0000u,
    0x3EDF8000u, 0x3EE28000u, 0x3EE58000u, 0x3EE80000u, 0x3EEB0000u, 0x3EEE0000u, 0x3EF10000u, 0x3EF40000u,
    0x3EF70000u, 0x3EFA0000u, 0x3EFD0000u, 0x3F000000u, 0x3F017000u, 0x3F02F000u, 0x3F04B000u, 0x3F063000u,
    0x3F07B000u, 0x3F097000u, 0x3F0AF000u, 0x3F0C7000u, 0x3F0E3000u, 0x3F0FB000u, 0x3F117000u, 0x3F12F000u,
    0x3F14B000u, 0x3F167000u, 0x3F17F000u, 0x3F19B000u, 0x3F1B7000u, 0x3F1D3000u, 0x3F1EF000u, 0x3F207000u,
    0x3F227000u, 0x3F23F000u, 0x3F25F000u, 0x3F27B000u, 0x3F297000u, 0x3F2B3000u, 0x3F2CF000u, 0x3F2EF000u,
    0x3F30B000u, 0x3F327000u, 0x3F347000u, 0x3F367000u, 0x3F383000u, 0x3F39F000u, 0x3F3BF000u, 0x3F3DF000u,
    0x3F3FF000u, 0x3F41B000u, 0x3F43B000u, 0x3F457000u, 0x3F477000u, 0x3F497000u, 0x3F4B7000u, 0x3F4D7000u,
    0x3F4F7000u, 0x3F517000u, 0x3F53B000u, 0x3F55B000u, 0x3F57F000u, 0x3F59F000u, 0x3F5BF000u, 0x3F5DF000u,
    0x3F5FF000u, 0x3F627000u, 0x3F647000u, 0x3F667000u, 0x3F68B000u, 0x3F6AF000u, 0x3F6CF000u, 0x3F6F3000u,
    0x3F717000u, 0x3F737000u, 0x3F75F000u, 0x3F77F000u, 0x3F7A7000u, 0x3F7C7000u, 0x3F7EF000u,
};

constexpr float kHalf = 0.5f;
constexpr float kOne = 1.0f;
constexpr float kTwo = 2.0f;

float Mul(float x, float y) { return x * y; }
float Add(float x, float y) { return x + y; }
float Sub(float x, float y) { return x - y; }

float HardLight(float a, float b) {
    const float twoA = Mul(kTwo, a);
    const float low = Mul(twoA, b);
    const float oneMinusA = Sub(kOne, a);
    const float x = Mul(-kTwo, oneMinusA);
    const float y = Sub(kOne, b);
    const float high = Fma(x, y, kOne);
    return b <= kHalf ? low : high;
}

float ColorBurn(float a, float b) {
    const float x = Sub(a, kOne);
    return Clamp01(Fma(x, hw::Rcp(b), kOne));
}

float ColorDodge(float a, float b) {
    const float t = Sub(kOne, b);
    const float m = Mul(a, hw::Rcp(t));
    return Fmax(Fmin(kOne, m), 0.0f);
}

float SoftLight(float a, float b) {
    // low = fma(2a, b, a a (1 - 2b)); high = fma(sqrt(a), 2b - 1, 2a (1 - b)).
    const float twoA = Mul(kTwo, a);
    const float twoB = Mul(kTwo, b);
    const float aa = Mul(a, a);
    const float oneMinusTwoB = Sub(kOne, twoB);
    const float low = Fma(twoA, b, Mul(aa, oneMinusTwoB));
    const float twoBMinusOne = Sub(twoB, kOne);
    const float oneMinusB = Sub(kOne, b);
    const float high = Fma(hw::Sqrt(a), twoBMinusOne, Mul(twoA, oneMinusB));
    return b <= kHalf ? low : high;
}

float LinearLight(float a, float b) {
    const float twoB = Mul(kTwo, b);
    const float low = Sub(Add(a, twoB), kOne);
    const float bMinusHalf = Sub(b, kHalf);
    const float high = Add(a, Mul(kTwo, bMinusHalf));
    return Clamp01(b <= kHalf ? low : high);
}

float VividLight(float a, float b) {
    const float twoB = Mul(kTwo, b);
    const float bMinusHalf = Sub(b, kHalf);
    const float twoBMinusHalf = Mul(kTwo, bMinusHalf);
    return b <= kHalf ? ColorBurn(a, twoB) : ColorDodge(a, twoBMinusHalf);
}

float PinLight(float a, float b) {
    const float twoB = Mul(kTwo, b);
    const float low = MinNan(a, twoB);
    const float high = MaxNan(a, Sub(twoB, kOne));
    return b <= kHalf ? low : high;
}

float Divide(float a, float b) {
    const float m = Mul(a, hw::Rcp(b));
    return Fmax(Fmin(m, kOne), 0.0f);
}

// ── Component modes (Tint, Saturation, Color, Value) ─────────────────────────

constexpr float kSix = 6.0f;
constexpr float kThree = 3.0f;

struct Hsv {
    float h = 0.0f;
    float s = 0.0f;
    float v = 0.0f;
};

float Less(float x, float y) { return x < y ? x : y; }

/// RGB to HSV on the hexcone (Hocevar's branch-free form): the largest component is v, the hue
/// fraction (q.w - q.y) / (6 d + e) is offset by the sector, s = d / (v + e); divisions through
/// the hardware reciprocal.
Hsv ToHsv(const std::array<float, 3>& c) {
    const float r = c[0];
    const float g = c[1];
    const float b = c[2];
    const bool gb = g >= b;
    const float p[4] = {gb ? g : b, gb ? b : g, gb ? 0.0f : -kOne, gb ? -kThird : kTwoThirds};
    const bool rp = r >= p[0];
    const float q[4] = {rp ? r : p[0], p[1], rp ? p[2] : p[3], rp ? p[0] : r};
    const float d = Sub(q[0], Less(q[3], q[1]));
    const float span = Add(Mul(kSix, d), kHsvEpsilon);
    Hsv out;
    out.h = std::fabs(Add(q[2], Mul(Sub(q[3], q[1]), hw::Rcp(span))));
    out.s = Mul(d, hw::Rcp(Add(q[0], kHsvEpsilon)));
    out.v = q[0];
    return out;
}

/// HSV to RGB: v (1 + (clamp(|6 fract(h + k) - 3| - 1, 0, 1) - 1) s), k = 1, 2/3, 1/3.
std::array<float, 3> FromHsv(const Hsv& c) {
    constexpr float k[3] = {1.0f, kTwoThirds, kThird};
    std::array<float, 3> out{};
    for (size_t i = 0; i < 3; ++i) {
        const float x = Add(c.h, k[i]);
        const float f = Sub(x, std::floor(x));
        const float p = std::fabs(Sub(Mul(f, kSix), kThree));
        const float t = Clamp01(Sub(p, kOne));
        out[i] = Mul(c.v, Add(kOne, Mul(Sub(t, kOne), c.s)));
    }
    return out;
}

std::array<float, 3> ComponentBlend(core::BlendingMode mode, const std::array<float, 3>& a,
                                    const std::array<float, 3>& b) {
    using M = core::BlendingMode;
    const Hsv lower = ToHsv(a);
    const Hsv upper = ToHsv(b);
    Hsv out = lower;
    if (mode == M::Tint || mode == M::Color) out.h = upper.h;
    if (mode == M::Saturation || mode == M::Color) out.s = upper.s;
    if (mode == M::Value) out.v = upper.v;
    out.v = Mul(kTwo, out.v);
    return FromHsv(out);
}

// ── Normal-map modes ─────────────────────────────────────────────────────────

using Vec3 = std::array<float, 3>;

/// The dot product of the normalisation: fma(z, z', fma(x, x', y y')).
float DotYxz(const Vec3& u, const Vec3& v) { return Fma(u[2], v[2], Fma(u[0], v[0], Mul(u[1], v[1]))); }
/// The dot product of reoriented normal mapping: fma(z, z', fma(y, y', x x')).
float DotXyz(const Vec3& u, const Vec3& v) { return Fma(u[2], v[2], Fma(u[1], v[1], Mul(u[0], v[0]))); }

Vec3 Normalise(const Vec3& v) {
    const float inv = hw::Rsqrt(DotYxz(v, v));
    return {Mul(v[0], inv), Mul(v[1], inv), Mul(v[2], inv)};
}

/// A colour in [0, 1] to a unit normal: 2c - 1 with z clamped to >= 0, normalised.
Vec3 DecodeNormal(const Vec3& c) {
    Vec3 n{};
    for (size_t i = 0; i < 3; ++i) n[i] = Sub(Mul(c[i], kTwo), kOne);
    n[2] = Fmax(n[2], 0.0f);
    return Normalise(n);
}

/// asin(t) for t in [0, 1/2]: the series kAsinSeries in t^2 (Horner), times t.
float AsinSmall(float t) {
    const float t2 = Mul(t, t);
    float sum = kAsinSeries[kAsinSeries.size() - 1];
    for (size_t i = kAsinSeries.size() - 1; i-- > 0;) sum = Add(Mul(sum, t2), kAsinSeries[i]);
    return Mul(sum, t);
}

/// sin(x) for x in [0, pi/2]: the series kSinSeries in x^2 (Horner), times x.
float SinSmall(float x) {
    const float x2 = Mul(x, x);
    float sum = kSinSeries[kSinSeries.size() - 1];
    for (size_t i = kSinSeries.size() - 1; i-- > 0;) sum = Add(Mul(sum, x2), kSinSeries[i]);
    return Mul(sum, x);
}

/// The unit normal n (z >= 0) rotated toward the flat normal (0, 0, 1) by the layer opacity:
/// spherical interpolation slerp((0, 0, 1), n, alpha) = n sin(alpha t) / sin t + (0, 0,
/// sin((1 - alpha) t) / sin t), t = acos(n.z), in float32 with fixed series (deterministic on
/// every backend; Painter's float32 evaluation of the same rotation is not reproduced exactly).
Vec3 TowardFlat(const Vec3& n, float alpha) {
    if (!(alpha < kOne)) return n;
    const float z = Clamp01(n[2]);
    const float sine = Sqrt(Mul(Sub(kOne, z), Add(kOne, z)));
    if (!(sine > 0.0f)) return n;
    const float angle = z >= kHalf ? Mul(kTwo, AsinSmall(Sqrt(Mul(Sub(kOne, z), kHalf))))
                                   : Sub(kHalfPi, AsinSmall(z));
    const float inv = Rcp(sine);
    const float wn = Mul(SinSmall(Mul(alpha, angle)), inv);
    const float wf = Mul(SinSmall(Mul(Sub(kOne, alpha), angle)), inv);
    return {Mul(n[0], wn), Mul(n[1], wn), Add(Mul(n[2], wn), wf)};
}

/// Reoriented normal mapping (approved source P-BARRE): t = base + (0, 0, 1), u = detail
/// (-1, -1, 1), r = t dot(t, u) - u t.z, evaluated as fma(t, dot, -(u t.z)) for x and y and as
/// t.z (dot - u.z) for z (the fitted operation order).
Vec3 Reoriented(const Vec3& base, const Vec3& detail) {
    const Vec3 t{base[0], base[1], Add(base[2], kOne)};
    const Vec3 u{-detail[0], -detail[1], detail[2]};
    const float d = DotXyz(t, u);
    return {Fma(t[0], d, -Mul(u[0], t[2])), Fma(t[1], d, -Mul(u[1], t[2])), Mul(t[2], Sub(d, u[2]))};
}

std::array<float, 3> NormalMapBlend(core::BlendingMode mode, const Vec3& a, const Vec3& b,
                                    float alpha) {
    using M = core::BlendingMode;
    const Vec3 lower = DecodeNormal(a);
    const Vec3 upper = TowardFlat(DecodeNormal(b), alpha);
    Vec3 r{};
    if (mode == M::NormalMapCombine) {
        r = {Add(lower[0], upper[0]), Add(lower[1], upper[1]), Mul(lower[2], upper[2])};
    } else if (mode == M::NormalMapDetail) {
        r = Reoriented(lower, upper);
    } else {
        r = Reoriented(upper, lower);
    }
    const Vec3 n = Normalise(r);
    return {Fma(n[0], kHalf, kHalf), Fma(n[1], kHalf, kHalf), Fma(n[2], kHalf, kHalf)};
}

}  // namespace

float Fma(float x, float y, float z) {
    return static_cast<float>(
        std::fma(static_cast<double>(x), static_cast<double>(y), static_cast<double>(z)));
}

float Rcp(float x) { return 1.0f / x; }

float Sqrt(float x) { return std::sqrt(x); }

float Fmin(float x, float y) { return std::fmin(x, y); }

float Fmax(float x, float y) { return std::fmax(x, y); }

float MinNan(float x, float y) {
    if (std::isnan(x) || std::isnan(y)) return std::numeric_limits<float>::quiet_NaN();
    return x < y ? x : y;
}

float MaxNan(float x, float y) {
    if (std::isnan(x) || std::isnan(y)) return std::numeric_limits<float>::quiet_NaN();
    return x > y ? x : y;
}

float Clamp01(float x) { return Fmin(Fmax(x, 0.0f), kOne); }

bool HasSeparableKernel(core::BlendingMode mode) {
    using M = core::BlendingMode;
    switch (mode) {
        case M::Normal: case M::Replace: case M::Disable: case M::Multiply: case M::Divide:
        case M::InverseDivide: case M::Darken: case M::Lighten: case M::LinearDodge:
        case M::Subtract: case M::InverseSubtract: case M::Difference: case M::Exclusion:
        case M::SignedAddition: case M::Overlay: case M::Screen: case M::LinearBurn:
        case M::ColorBurn: case M::ColorDodge: case M::SoftLight: case M::HardLight:
        case M::VividLight: case M::LinearLight: case M::PinLight:
            return true;
        case M::PassThrough: case M::Tint: case M::Saturation: case M::Color: case M::Value:
        case M::NormalMapCombine: case M::NormalMapDetail: case M::NormalMapInverseDetail:
            return false;
    }
    return false;
}

float BlendKernel(core::BlendingMode mode, float a, float b) {
    using M = core::BlendingMode;
    switch (mode) {
        case M::Normal: case M::Replace: return b;
        case M::Disable: return a;
        case M::Multiply: return Mul(a, b);
        case M::Divide: return Divide(a, b);
        case M::InverseDivide: return Divide(b, a);
        case M::Darken: return MinNan(a, b);
        case M::Lighten: return MaxNan(a, b);
        case M::LinearDodge: return Add(a, b);
        case M::Subtract: return Sub(a, b);
        case M::InverseSubtract: return Sub(b, a);
        case M::Difference: return std::fabs(Sub(a, b));
        case M::Exclusion: {
            const float aMinusHalf = Sub(a, kHalf);
            const float x = Mul(-kTwo, aMinusHalf);
            const float y = Sub(b, kHalf);
            return Fma(x, y, kHalf);
        }
        case M::SignedAddition: {
            const float twoB = Mul(kTwo, b);
            return Sub(Add(a, twoB), kOne);
        }
        case M::Screen: {
            const float x = -Sub(kOne, a);
            const float y = Sub(kOne, b);
            return Fma(x, y, kOne);
        }
        case M::LinearBurn: return Sub(Add(a, b), kOne);
        case M::Overlay: return HardLight(b, a);
        case M::ColorBurn: return ColorBurn(a, b);
        case M::ColorDodge: return ColorDodge(a, b);
        case M::SoftLight: return SoftLight(a, b);
        case M::HardLight: return HardLight(a, b);
        case M::VividLight: return VividLight(a, b);
        case M::LinearLight: return LinearLight(a, b);
        case M::PinLight: return PinLight(a, b);
        case M::PassThrough: case M::Tint: case M::Saturation: case M::Color: case M::Value:
        case M::NormalMapCombine: case M::NormalMapDetail: case M::NormalMapInverseDetail:
            break;
    }
    return std::numeric_limits<float>::quiet_NaN();
}

bool HasColourKernel(core::BlendingMode mode) {
    using M = core::BlendingMode;
    return mode == M::Tint || mode == M::Saturation || mode == M::Color || mode == M::Value ||
           mode == M::NormalMapCombine || mode == M::NormalMapDetail ||
           mode == M::NormalMapInverseDetail;
}

bool HasKernel(core::BlendingMode mode) { return HasSeparableKernel(mode) || HasColourKernel(mode); }

std::array<float, 3> BlendColour(core::BlendingMode mode, const std::array<float, 3>& a,
                                 const std::array<float, 3>& b, int channels, float alpha) {
    using M = core::BlendingMode;
    const bool normalMap =
        mode == M::NormalMapCombine || mode == M::NormalMapDetail || mode == M::NormalMapInverseDetail;
    if (channels == 1) return (mode == M::Value || normalMap) ? b : a;
    if (normalMap) return NormalMapBlend(mode, a, b, alpha);
    return ComponentBlend(mode, a, b);
}

// ── Storage ──────────────────────────────────────────────────────────────────

uint32_t WriteUnorm(float v, uint32_t bits) {
    float c = v >= 0.0f ? v : 0.0f;  // NaN compares false: 0
    c = c <= 1.0f ? c : 1.0f;
    const float scale = static_cast<float>(uint64_t{1} << (bits + 4));  // exact power of two
    const uint64_t j = static_cast<uint64_t>(c * scale);
    const uint64_t m = (uint64_t{1} << bits) - 1;
    const uint64_t bias = (uint64_t{1} << (bits + 3)) - 1;
    return static_cast<uint32_t>((j * m + bias) >> (bits + 4));
}

float UnormOperand(uint32_t code, uint32_t bits) {
    const double m = static_cast<double>((uint64_t{1} << bits) - 1);
    return static_cast<float>(static_cast<double>(code) / m);
}

double SrgbDecode(double encoded) {
    const double x = encoded > 0.0 ? encoded : 0.0;
    if (encoded <= 0.04045) return encoded / 12.92;
    return std::pow((x + 0.055) / 1.055, 2.4);
}

double SrgbEncode(double linear) {
    const double x = linear > 0.0 ? linear : 0.0;
    if (linear <= 0.0031308) return 12.92 * linear;
    return 1.055 * std::pow(x, 1.0 / 2.4) - 0.055;
}

double SignificandRound(double x, int bits) {
    int exponent = 0;
    const double mantissa = std::frexp(x, &exponent);
    const double scale = static_cast<double>(int64_t{1} << bits);
    return std::ldexp(std::nearbyint(mantissa * scale) / scale, exponent);
}

const std::array<float, 256>& Srgb8OperandTable() {
    static const std::array<float, 256> table = [] {
        std::array<float, 256> t{};
        for (uint32_t c = 0; c < 256; ++c) t[c] = std::bit_cast<float>(kSrgb8DecodeBits[c]);
        return t;
    }();
    return table;
}

const std::array<double, 256>& Srgb8Thresholds() {
    static const std::array<double, 256> table = [] {
        std::array<double, 256> t{};
        t[0] = 0.0;
        for (uint32_t k = 1; k < 256; ++k) {
            t[k] = static_cast<double>(std::bit_cast<float>(kSrgb8ThresholdBits[k - 1]));
        }
        return t;
    }();
    return table;
}

const std::array<float, 256>& Unorm8OperandTable() {
    static const std::array<float, 256> table = [] {
        std::array<float, 256> t{};
        for (uint32_t c = 0; c < 256; ++c) t[c] = UnormOperand(c, 8);
        return t;
    }();
    return table;
}

const std::vector<float>& Unorm16OperandTable() {
    static const std::vector<float> table = [] {
        std::vector<float> t(65536);
        for (uint32_t c = 0; c < 65536; ++c) t[c] = UnormOperand(c, 16);
        return t;
    }();
    return table;
}

float Srgb8Operand(uint32_t code) { return Srgb8OperandTable()[code & 0xFF]; }

uint32_t Srgb8Store(float v) {
    float c = v >= 0.0f ? v : 0.0f;
    c = c <= 1.0f ? c : 1.0f;
    const double value = static_cast<double>(c);
    const std::array<double, 256>& thresholds = Srgb8Thresholds();
    uint32_t code = 0;
    for (uint32_t k = 1; k < 256; ++k) {
        if (value >= thresholds[k]) code = k;
    }
    return code;
}

uint16_t HalfTowardZero(float v) {
    const uint32_t bits = std::bit_cast<uint32_t>(v);
    const uint16_t sign = static_cast<uint16_t>((bits >> 16) & 0x8000u);
    const uint32_t magnitude = bits & 0x7FFFFFFFu;
    if (magnitude >= 0x7F800000u) {
        // Infinity keeps its class; NaN keeps a quiet NaN payload.
        if (magnitude == 0x7F800000u) return static_cast<uint16_t>(sign | 0x7C00u);
        return static_cast<uint16_t>(sign | 0x7E00u);
    }
    if (magnitude >= 0x477FE000u) {  // >= 65504: the largest finite half (toward zero)
        return static_cast<uint16_t>(sign | 0x7BFFu);
    }
    if (magnitude < 0x38800000u) {  // below 2^-14: a subnormal half, step 2^-24
        const float scaled = std::bit_cast<float>(magnitude) * 16777216.0f;  // exact
        const uint32_t mantissa = static_cast<uint32_t>(scaled);
        return static_cast<uint16_t>(sign | mantissa);
    }
    const uint32_t exponent = (magnitude >> 23) - 127 + 15;
    const uint32_t mantissa = (magnitude >> 13) & 0x3FFu;
    return static_cast<uint16_t>(sign | (exponent << 10) | mantissa);
}

float HalfToFloat(uint16_t bits) {
    const uint32_t sign = (static_cast<uint32_t>(bits) & 0x8000u) << 16;
    const uint32_t exponent = (bits >> 10) & 0x1Fu;
    const uint32_t mantissa = bits & 0x3FFu;
    if (exponent == 0) {
        if (mantissa == 0) return std::bit_cast<float>(sign);
        const float value = static_cast<float>(mantissa) * 5.9604644775390625e-08f;  // 2^-24
        return std::bit_cast<float>(sign | std::bit_cast<uint32_t>(value));
    }
    if (exponent == 31) {
        return std::bit_cast<float>(sign | 0x7F800000u | (mantissa << 13));
    }
    return std::bit_cast<float>(sign | ((exponent + 112) << 23) | (mantissa << 13));
}

float Float32Store(float v) {
    if (std::isnan(v)) return std::bit_cast<float>(0x7FC00000u);
    return v;
}

float Float32Readout(float v, float base) {
    if (std::isnan(v)) return std::bit_cast<float>(0x7FC00000u);
    const float t = v - base;
    return t + base;
}

// ── Compositing of one texel ─────────────────────────────────────────────────

float Levels(float v, const LevelsComponent& levels) {
    float t = Mul(Sub(v, levels.inMin), hw::Rcp(Sub(levels.inMax, levels.inMin)));
    if (levels.clamp) t = Clamp01(t);
    if (levels.gamma != kOne) {
        const float p = hw::Pow(std::fabs(t), levels.gamma);
        t = t > 0.0f ? p : (t < 0.0f ? -p : Mul(t, p));
    }
    return Fma(t, Sub(levels.outMax, levels.outMin), levels.outMin);
}

std::array<float, 4> Composite(const CompositeInput& in) {
    using M = core::BlendingMode;
    std::array<float, 4> out{0.0f, 0.0f, 0.0f, 1.0f};
    const float opacityMask = Mul(in.opacity, in.mask);
    const float alphaS = Mul(opacityMask, in.src[3]);
    const float alphaB = in.acc[3];
    const bool colour = HasColourKernel(in.mode);
    // The normal-map modes take the opacity as a rotation of the upper normal (BlendColour) and
    // write their result as it is over an opaque backdrop.
    const bool rotates = colour && in.channels == 3 &&
                         (in.mode == M::NormalMapCombine || in.mode == M::NormalMapDetail ||
                          in.mode == M::NormalMapInverseDetail);
    std::array<float, 3> r{};
    if (colour) {
        const std::array<float, 3> a{in.acc[0], in.acc[1], in.acc[2]};
        const std::array<float, 3> b{in.src[0], in.src[1], in.src[2]};
        r = BlendColour(in.mode, a, b, in.channels, alphaB == 1.0f ? alphaS : kOne);
    } else {
        for (int i = 0; i < in.channels; ++i) {
            r[static_cast<size_t>(i)] =
                BlendKernel(in.mode, in.acc[static_cast<size_t>(i)], in.src[static_cast<size_t>(i)]);
        }
    }
    for (int i = 0; i < in.channels; ++i) {
        const float a = in.acc[static_cast<size_t>(i)];
        const float s = in.src[static_cast<size_t>(i)];
        float ri = r[static_cast<size_t>(i)];
        if (in.clampUnorm) ri = Clamp01(ri);
        float v = 0.0f;
        if (alphaB == 1.0f) {
            if (rotates) {
                v = ri;
            } else if (in.mode == M::Replace || in.effectMix) {
                const float d = Sub(ri, a);
                v = Add(a, Mul(d, alphaS));
            } else if (in.mode == M::ColorBurn) {
                // Painter's ColorBurn mixes with one rounding of a (1 - alpha) + r alpha.
                v = Fma(a, Sub(kOne, alphaS), Mul(ri, alphaS));
            } else {
                const float oneMinusAlpha = Sub(kOne, alphaS);
                const float ta = Mul(a, oneMinusAlpha);
                const float tr = Mul(ri, alphaS);
                v = Add(ta, tr);
            }
        } else if (alphaB == 0.0f) {
            v = s;
        } else {
            // W3C §5.1 with straight colours: Co = [(1 - as) ab Cb + as ((1 - ab) Cs + ab B)] / ao.
            const float oneMinusAlphaS = Sub(kOne, alphaS);
            const float oneMinusAlphaB = Sub(kOne, alphaB);
            const float backdrop = Mul(Mul(oneMinusAlphaS, alphaB), a);
            const float blended = Add(Mul(oneMinusAlphaB, s), Mul(alphaB, ri));
            const float alphaO = Add(alphaS, Mul(alphaB, oneMinusAlphaS));
            v = Mul(Add(backdrop, Mul(alphaS, blended)), Rcp(alphaO));
        }
        out[static_cast<size_t>(i)] = v;
    }
    if (alphaB == 1.0f) {
        out[3] = 1.0f;
    } else if (alphaB == 0.0f) {
        out[3] = alphaS;
    } else {
        out[3] = Add(alphaS, Mul(alphaB, Sub(kOne, alphaS)));
    }
    return out;
}

}  // namespace uzp::evaluator::arith
