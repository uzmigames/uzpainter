// Native tests of the UzEngine texture path (`src/export/bc_encoder`, `mips`, `uztexture_writer`;
// task phase3.1_uze-uztexture-writer items 3.1-3.7, decision 315).
// Built by `zig build uzp-texture-tests` and driven by tests/export/test_uze_texture.py. CPU only.
//
// Usage:
//   uzp-texture-tests run [case]   run every case (or one); exit 0 when all pass

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <functional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "export/bc_encoder.h"
#include "export/mips.h"
#include "export/uztexture_writer.h"
#include "uze_texture_check.h"
#include "uzp_core/manifest/sha256.h"

namespace {

using namespace uzp::exporter;
using namespace uzp::exporter::testing;

struct Failure {
    std::string message;
};

#define CHECK(cond)                                                                                     \
    do {                                                                                                \
        if (!(cond)) throw Failure{std::string(__FILE__ ":") + std::to_string(__LINE__) + ": " #cond}; \
    } while (false)

constexpr BcFormat kAllFormats[] = {BcFormat::Bc1, BcFormat::Bc1Srgb, BcFormat::Bc3,
                                    BcFormat::Bc3Srgb, BcFormat::Bc4, BcFormat::Bc5,
                                    BcFormat::Bc7, BcFormat::Bc7Srgb};

std::string Hash(const std::vector<uint8_t>& bytes) {
    return uzp::core::Sha256Hex(
        std::string_view(reinterpret_cast<const char*>(bytes.data()), bytes.size()));
}

uint16_t ToCode(double v) {
    return static_cast<uint16_t>(std::clamp(std::floor(v * 65535.0 + 0.5), 0.0, 65535.0));
}

/// Gradients, a sharp edge and LCG noise: every block holds several distinct texels.
Rgba16Image AuthoredRgba16(uint32_t width, uint32_t height) {
    Rgba16Image image{width, height, std::vector<uint16_t>(uint64_t{width} * height * 4)};
    uint64_t state = 0x2545F4914F6CDD1DULL;
    for (uint32_t y = 0; y < height; ++y) {
        for (uint32_t x = 0; x < width; ++x) {
            state = state * 6364136223846793005ULL + 1442695040888963407ULL;
            uint16_t* t = image.rgba.data() + (uint64_t{y} * width + x) * 4;
            t[0] = ToCode(width > 1 ? double(x) / (width - 1) : 0.5);
            t[1] = ToCode(height > 1 ? double(y) / (height - 1) : 0.5);
            t[2] = static_cast<uint16_t>(state >> 48);
            t[3] = x < width / 2 ? ToCode(0.5 + 0.5 * std::sin(x * 0.3) * std::cos(y * 0.2)) : 65535;
        }
    }
    return image;
}

/// The hemisphere bump: n = (u, v, sqrt(1 - u^2 - v^2)) inside the unit disk, (0, 0, 1) outside.
Rgba16Image HemisphereNormals(uint32_t size) {
    Rgba16Image image{size, size, std::vector<uint16_t>(uint64_t{size} * size * 4)};
    for (uint32_t y = 0; y < size; ++y) {
        for (uint32_t x = 0; x < size; ++x) {
            const double u = (x + 0.5) / size * 2.0 - 1.0;
            const double v = (y + 0.5) / size * 2.0 - 1.0;
            const double r2 = u * u + v * v;
            const double nx = r2 < 1.0 ? u : 0.0;
            const double ny = r2 < 1.0 ? v : 0.0;
            const double nz = r2 < 1.0 ? std::sqrt(1.0 - r2) : 1.0;
            uint16_t* t = image.rgba.data() + (uint64_t{y} * size + x) * 4;
            t[0] = ToCode(nx * 0.5 + 0.5);
            t[1] = ToCode(ny * 0.5 + 0.5);
            t[2] = ToCode(nz * 0.5 + 0.5);
            t[3] = 65535;
        }
    }
    return image;
}

// ── 3.1 Encoder determinism ─────────────────────────────────────────────────────────────────

void CaseEncoderDeterminism() {
    const uint32_t maxThreads = ResolveBcThreads(0);
    std::printf("  hardware threads: %u\n", maxThreads);
    for (auto [w, h] : {std::pair<uint32_t, uint32_t>{256, 256}, {260, 134}, {3, 5}}) {
        const Rgba8Image image = QuantizeTo8(AuthoredRgba16(w, h));
        for (BcFormat format : kAllFormats) {
            const std::vector<uint8_t> first = EncodeBc(EtcpakEncoder(), image, format, 1);
            CHECK(first.size() == BcEncodedSize(format, w, h));
            CHECK(EncodeBc(EtcpakEncoder(), image, format, 1) == first);
            for (uint32_t threads : {4u, maxThreads, 7u, 1000u})
                CHECK(EncodeBc(EtcpakEncoder(), image, format, threads) == first);
            std::printf("  %ux%u %-8s %s\n", w, h, std::string(BcFormatName(format)).c_str(),
                        Hash(first).c_str());
        }
    }
    // The spec scenario: an authored RGBA16 image cooked as BC7 sRGB, one worker against the
    // maximum, the whole `.uztexture` file.
    const Rgba16Image albedo = AuthoredRgba16(256, 256);
    const UzTextureSpec spec{"albedo", uz::TextureFormat::BC7, true, {MipClass::Colour, 0.5}};
    const std::vector<uint8_t> one = CookUzTexture(EtcpakEncoder(), albedo, spec, 1).bytes;
    for (uint32_t threads : {1u, 4u, maxThreads})
        CHECK(CookUzTexture(EtcpakEncoder(), albedo, spec, threads).bytes == one);
    std::printf("  albedo.uztexture BC7_SRGB %s\n", Hash(one).c_str());
}

/// Channel order and block layout: a constant image decodes back to its colour.
void CaseEncoderChannels() {
    Rgba8Image image{8, 8, {}};
    for (int i = 0; i < 64; ++i) image.rgba.insert(image.rgba.end(), {200, 100, 50, 180});
    for (BcFormat format : kAllFormats) {
        const Rgba8Image back = DecodeBc(format, EncodeBc(EtcpakEncoder(), image, format, 1), 8, 8);
        // BC1 and BC3 store RGB endpoints as 5:6:5 (200 -> 206 after expansion).
        const bool rgb565 = format == BcFormat::Bc1 || format == BcFormat::Bc1Srgb ||
                            format == BcFormat::Bc3 || format == BcFormat::Bc3Srgb;
        const int tolerance = rgb565 ? 8 : 2;
        for (uint64_t i = 0; i < 64; ++i) {
            const uint8_t* t = back.rgba.data() + i * 4;
            CHECK(std::abs(t[0] - 200) <= tolerance);
            if (format == BcFormat::Bc4) continue;
            CHECK(std::abs(t[1] - 100) <= tolerance);
            if (format == BcFormat::Bc5) continue;
            CHECK(std::abs(t[2] - 50) <= tolerance);
            if (format == BcFormat::Bc3 || format == BcFormat::Bc3Srgb || format == BcFormat::Bc7 ||
                format == BcFormat::Bc7Srgb)
                CHECK(std::abs(t[3] - 180) <= 2);
        }
    }
}

// ── 3.2 Colour mips ─────────────────────────────────────────────────────────────────────────

double RefDecode(uint16_t code) {
    const double v = code / 65535.0;
    return v <= 0.04045 ? v / 12.92 : std::pow((v + 0.055) / 1.055, 2.4);
}

uint16_t RefEncode(double linear) {
    const double v = linear <= 0.0031308 ? 12.92 * linear
                                         : 1.055 * std::pow(linear, 1.0 / 2.4) - 0.055;
    return ToCode(v);
}

/// The declared filter, computed independently: the 2x2 box of the level above in linear
/// light (std::pow transfer), re-encoded to the nearest 16-bit sRGB code; alpha the rounded
/// integer mean.
Rgba16Image RefColourLevel(const Rgba16Image& src) {
    Rgba16Image dst{std::max(1u, src.width / 2), std::max(1u, src.height / 2), {}};
    dst.rgba.resize(uint64_t{dst.width} * dst.height * 4);
    for (uint32_t y = 0; y < dst.height; ++y) {
        for (uint32_t x = 0; x < dst.width; ++x) {
            const uint32_t xs[2] = {std::min(2 * x, src.width - 1), std::min(2 * x + 1, src.width - 1)};
            const uint32_t ys[2] = {std::min(2 * y, src.height - 1), std::min(2 * y + 1, src.height - 1)};
            for (uint32_t c = 0; c < 4; ++c) {
                double linear = 0.0;
                uint32_t codes = 0;
                for (uint32_t sy : ys)
                    for (uint32_t sx : xs) {
                        const uint16_t code = src.rgba[(uint64_t{sy} * src.width + sx) * 4 + c];
                        linear += RefDecode(code);
                        codes += code;
                    }
                dst.rgba[(uint64_t{y} * dst.width + x) * 4 + c] =
                    c < 3 ? RefEncode(linear / 4.0) : static_cast<uint16_t>((codes + 2) / 4);
            }
        }
    }
    return dst;
}

/// The authored sRGB ramp: R the 8-bit codes 0..255 along x, G a 16-bit ramp along y, B the
/// 8-bit codes 255..0, A a ramp.
Rgba16Image SrgbRamp() {
    Rgba16Image image{256, 16, std::vector<uint16_t>(256 * 16 * 4)};
    for (uint32_t y = 0; y < 16; ++y)
        for (uint32_t x = 0; x < 256; ++x) {
            uint16_t* t = image.rgba.data() + (uint64_t{y} * 256 + x) * 4;
            t[0] = static_cast<uint16_t>(x * 257);
            t[1] = static_cast<uint16_t>(y * 4369);
            t[2] = static_cast<uint16_t>((255 - x) * 257);
            t[3] = static_cast<uint16_t>(x * 257);
        }
    return image;
}

void CaseColourMips() {
    const Rgba16Image ramp = SrgbRamp();
    const std::vector<Rgba16Image> chain = GenerateMipChain(ramp, {MipClass::Colour, 0.5});
    CHECK(chain.size() == 9);
    CHECK(chain[0].rgba == ramp.rgba);
    uint64_t gammaDiffers = 0;
    Rgba16Image ref = ramp;
    for (size_t level = 1; level < chain.size(); ++level) {
        ref = RefColourLevel(ref);
        CHECK(chain[level].width == std::max(1u, 256u >> level));
        CHECK(chain[level].height == std::max(1u, 16u >> level));
        uint64_t mismatches = 0;
        for (size_t i = 0; i < ref.rgba.size(); ++i) mismatches += chain[level].rgba[i] != ref.rgba[i];
        std::printf("  level %zu: %ux%u, %llu codes differ from the reference\n", level,
                    chain[level].width, chain[level].height,
                    static_cast<unsigned long long>(mismatches));
        CHECK(mismatches == 0);
        // The 8-bit level the encoder sees is round(code / 257) of the same codes.
        const Rgba8Image q = QuantizeTo8(chain[level]);
        for (size_t i = 0; i < ref.rgba.size(); ++i)
            CHECK(q.rgba[i] == static_cast<uint8_t>(std::floor(ref.rgba[i] / 257.0 + 0.5)));
        // The filter runs in linear light: it is not the mean of the encoded codes.
        const Rgba16Image& above = chain[level - 1];
        for (uint32_t x = 0; x < chain[level].width && level == 1; ++x) {
            const uint32_t sum = above.rgba[(2 * x) * 4] + above.rgba[(2 * x + 1) * 4] +
                                 above.rgba[(above.width + 2 * x) * 4] +
                                 above.rgba[(above.width + 2 * x + 1) * 4];
            gammaDiffers += chain[level].rgba[x * 4] != (sum + 2) / 4;
        }
    }
    CHECK(gammaDiffers > 0);
    // The transfer function itself: the Newton x^2.4 against std::pow, and the encode round trip.
    double worst = 0.0;
    for (uint32_t c = 0; c < 65536; ++c) {
        worst = std::max(worst, std::fabs(SrgbDecode16(static_cast<uint16_t>(c)) - RefDecode(static_cast<uint16_t>(c))));
        CHECK(SrgbEncode16(SrgbDecode16(static_cast<uint16_t>(c))) == c);
    }
    std::printf("  max |decode - pow decode| = %.3g\n", worst);
    CHECK(worst < 1e-15);
}

// ── 3.3 Normal mips ─────────────────────────────────────────────────────────────────────────

void CaseNormalMips() {
    const std::vector<Rgba16Image> chain =
        GenerateMipChain(HemisphereNormals(128), {MipClass::Normal, 0.5});
    CHECK(chain.size() == 8);
    const double bound16 = std::sqrt(3.0) / 65535.0;
    const double bound8 = std::sqrt(3.0) * (1.0 / 255.0 + 1.0 / 65535.0);
    for (size_t level = 0; level < chain.size(); ++level) {
        const Rgba16Image& l16 = chain[level];
        const Rgba8Image l8 = QuantizeTo8(l16);
        double worst16 = 0.0;
        double worst8 = 0.0;
        uint64_t tilted = 0;
        for (uint64_t i = 0; i < uint64_t{l16.width} * l16.height; ++i) {
            double n16[3];
            double n8[3];
            for (int c = 0; c < 3; ++c) {
                n16[c] = l16.rgba[i * 4 + c] / 65535.0 * 2.0 - 1.0;
                n8[c] = l8.rgba[i * 4 + c] / 255.0 * 2.0 - 1.0;
            }
            CHECK(n16[2] >= 0.0);
            tilted += l16.rgba[i * 4 + 2] != 65535;
            worst16 = std::max(worst16, std::fabs(std::sqrt(n16[0] * n16[0] + n16[1] * n16[1] + n16[2] * n16[2]) - 1.0));
            worst8 = std::max(worst8, std::fabs(std::sqrt(n8[0] * n8[0] + n8[1] * n8[1] + n8[2] * n8[2]) - 1.0));
        }
        std::printf("  level %zu: %ux%u, max |len - 1| 16-bit %.3g (bound %.3g), 8-bit %.3g (bound %.3g)\n",
                    level, l16.width, l16.height, worst16, bound16, worst8, bound8);
        CHECK(worst16 <= bound16);
        CHECK(worst8 <= bound8);
        if (level + 1 < chain.size()) CHECK(tilted > 0);
    }
}

// ── 3.4 Alpha coverage ──────────────────────────────────────────────────────────────────────

Rgba16Image MaskedAlbedo() {
    Rgba16Image image{256, 256, std::vector<uint16_t>(256 * 256 * 4)};
    for (uint32_t y = 0; y < 256; ++y)
        for (uint32_t x = 0; x < 256; ++x) {
            uint16_t* t = image.rgba.data() + (uint64_t{y} * 256 + x) * 4;
            t[0] = static_cast<uint16_t>(x * 257);
            t[1] = static_cast<uint16_t>(y * 257);
            t[2] = 40000;
            t[3] = ToCode(0.5 + 0.5 * std::sin(x * 0.4) * std::sin(y * 0.3));
        }
    return image;
}

void CaseAlphaCoverage() {
    const Rgba16Image base = MaskedAlbedo();
    const double threshold = 0.7;
    const std::vector<Rgba16Image> chain =
        GenerateMipChain(base, {MipClass::MaskedColour, threshold});
    const std::vector<Rgba16Image> colour = GenerateMipChain(base, {MipClass::Colour, threshold});
    const uint64_t baseCovered = CoveredTexels(base, threshold);
    const uint64_t baseTexels = 256 * 256;
    std::printf("  level 0 coverage %.6f\n", double(baseCovered) / baseTexels);
    uint64_t plainDrift = 0;
    for (size_t level = 1; level < chain.size(); ++level) {
        const uint64_t texels = uint64_t{chain[level].width} * chain[level].height;
        const uint64_t target = (2 * baseCovered * texels + baseTexels) / (2 * baseTexels);
        const uint64_t covered = CoveredTexels(chain[level], threshold);
        const uint64_t plain = CoveredTexels(colour[level], threshold);
        const uint64_t error = covered > target ? covered - target : target - covered;
        const uint64_t plainError = plain > target ? plain - target : target - plain;
        plainDrift = std::max(plainDrift, plainError);
        std::printf("  level %zu: %llu texels, target %llu, covered %llu (plain box %llu)\n", level,
                    static_cast<unsigned long long>(texels), static_cast<unsigned long long>(target),
                    static_cast<unsigned long long>(covered), static_cast<unsigned long long>(plain));
        CHECK(error == 0);
        // RGB is the colour filter; only alpha is rescaled.
        for (uint64_t i = 0; i < texels; ++i)
            for (int c = 0; c < 3; ++c) CHECK(chain[level].rgba[i * 4 + c] == colour[level].rgba[i * 4 + c]);
    }
    // Without preservation the box filter loses the coverage: the test image exercises it.
    CHECK(plainDrift > 1);
}

// ── 3.5 Negative-Z normals ──────────────────────────────────────────────────────────────────

void CaseNegativeZ() {
    Rgba16Image normal = HemisphereNormals(64);
    CHECK(FindNegativeZ(normal).count == 0);
    const UzTextureSpec bc5{"normal", uz::TextureFormat::BC5, false, {MipClass::Normal, 0.5}};
    CHECK(!CookUzTexture(EtcpakEncoder(), normal, bc5, 0).bytes.empty());

    normal.rgba[(uint64_t{9} * 64 + 5) * 4 + 2] = 32767;  // Z = -1/65535
    const NegativeZ found = FindNegativeZ(normal);
    CHECK(found.count == 1 && found.firstX == 5 && found.firstY == 9);
    bool refused = false;
    try {
        (void)CookUzTexture(EtcpakEncoder(), normal, bc5, 0);
    } catch (const NegativeZNormal& e) {
        refused = e.found.count == 1 && std::string(e.what()).find("1 texel(s)") != std::string::npos;
        std::printf("  refused: %s\n", e.what());
    }
    CHECK(refused);
    // The RGB route keeps the sign of Z.
    const UzTextureSpec rgba{"normal", uz::TextureFormat::Uncompressed_RGBA8, false, {MipClass::Normal, 0.5}};
    const ReadUzTexture read = ParseUzTexture(CookUzTexture(EtcpakEncoder(), normal, rgba, 0).bytes);
    CHECK(read.header.format == static_cast<uint32_t>(uz::TextureFormat::Uncompressed_RGBA8));
    CHECK(read.blobs[0][(uint64_t{9} * 64 + 5) * 4 + 2] < 128);
}

// ── 3.6 Layout ──────────────────────────────────────────────────────────────────────────────

void CaseNormalColourSpace() {
    const Rgba16Image normal = HemisphereNormals(4);
    for (const uz::TextureFormat format : {uz::TextureFormat::Uncompressed_RGBA8,
                                          uz::TextureFormat::BC1, uz::TextureFormat::BC3,
                                          uz::TextureFormat::BC7}) {
        UzTextureSpec spec{"normal", format, true, {MipClass::Normal, 0.5}};
        // An invalid mip option also proves rejection precedes mip generation.
        for (double threshold : {0.5, -1.0}) {
            spec.mips.alphaThreshold = threshold;
            bool refused = false;
            try {
                (void)CookUzTexture(EtcpakEncoder(), normal, spec, 1);
            } catch (const std::invalid_argument& e) {
                refused = std::string(e.what()) ==
                          "CookUzTexture: normal maps must be linear, not sRGB";
            }
            CHECK(refused);
        }
        spec.mips.alphaThreshold = 0.5;
        spec.srgb = false;
        const ReadUzTexture linear = ParseUzTexture(CookUzTexture(EtcpakEncoder(), normal, spec, 1).bytes);
        CHECK(linear.header.flags == 0 && linear.header.mipCount == 3);
        spec.srgb = true;
        spec.mips.mapClass = MipClass::Colour;
        const ReadUzTexture colour = ParseUzTexture(CookUzTexture(EtcpakEncoder(), AuthoredRgba16(4, 4), spec, 1).bytes);
        CHECK(colour.header.flags == uz::kUzTextureFlag_sRGB && colour.header.mipCount == 3);
    }
}

void CaseUzTextureLayout() {
    struct Layout {
        const char* binding;
        uz::TextureFormat format;
        bool srgb;
        MipClass mapClass;
        uint32_t width;
        uint32_t height;
    };
    for (const Layout& c : {Layout{"height", uz::TextureFormat::BC4, false, MipClass::Linear, 64, 32},
                            Layout{"albedo", uz::TextureFormat::BC7, true, MipClass::Colour, 16, 64},
                            Layout{"orm", uz::TextureFormat::BC7, false, MipClass::Linear, 32, 32},
                            Layout{"emissive", uz::TextureFormat::BC1, true, MipClass::Colour, 8, 8},
                            Layout{"normal", uz::TextureFormat::BC5, false, MipClass::Normal, 4, 2},
                            Layout{"ui", uz::TextureFormat::Uncompressed_RGBA8, true, MipClass::Colour, 2, 1}}) {
        const Rgba16Image canonical = c.mapClass == MipClass::Normal ? HemisphereNormals(4) : AuthoredRgba16(c.width, c.height);
        Rgba16Image input = canonical;
        if (c.mapClass == MipClass::Normal) {  // 4x2 from the 4x4 hemisphere: its top rows
            input.height = 2;
            input.rgba.resize(4 * 2 * 4);
        }
        const UzTexture tex = CookUzTexture(EtcpakEncoder(), input, {c.binding, c.format, c.srgb, {c.mapClass, 0.5}}, 0);
        // The raw bytes: "UZTX" first, the header fields little-endian.
        CHECK(tex.bytes.size() > 64 && tex.bytes[0] == 'U' && tex.bytes[1] == 'T' && tex.bytes[2] == 'X' && tex.bytes[3] == 'Z');
        const ReadUzTexture read = ParseUzTexture(tex.bytes);
        const uint32_t mips = FullMipCount(c.width, c.height);
        CHECK(read.header.magic == uz::kUzTextureMagic);
        CHECK(read.header.version == uz::kUzTextureVersion);
        CHECK(read.header.width == c.width && read.header.height == c.height);
        CHECK(read.header.mipCount == mips);
        CHECK(read.header.format == static_cast<uint32_t>(c.format));
        CHECK(read.header.flags == (c.srgb ? uz::kUzTextureFlag_sRGB : 0u));
        CHECK(uz::TextureFormatToRHI(static_cast<uz::TextureFormat>(read.header.format), c.srgb) != uz::RHIFormat::Unknown);
        uint64_t offset = 64 + 24 * uint64_t{mips};
        CHECK(tex.metadata.binding == c.binding && tex.metadata.format == c.format && tex.metadata.srgb == c.srgb);
        CHECK(tex.metadata.mips.size() == mips);
        for (uint32_t level = 0; level < mips; ++level) {
            const uint32_t w = std::max(1u, c.width >> level);
            const uint32_t h = std::max(1u, c.height >> level);
            const uint64_t size = c.format == uz::TextureFormat::Uncompressed_RGBA8
                                      ? uint64_t{w} * h * 4
                                      : uint64_t{(w + 3) / 4} * ((h + 3) / 4) *
                                            (c.format == uz::TextureFormat::BC1 || c.format == uz::TextureFormat::BC4 ? 8 : 16);
            CHECK(read.mips[level].offset == offset && read.mips[level].size == size);
            CHECK(read.mips[level].width == w && read.mips[level].height == h);
            CHECK(tex.metadata.mips[level].offset == offset && tex.metadata.mips[level].size == size);
            offset += size;
        }
        CHECK(offset == tex.bytes.size());
        std::printf("  %-8s %-5s %ux%u: %u mips, %zu bytes, flags %u\n", c.binding,
                    c.format == uz::TextureFormat::Uncompressed_RGBA8 ? "RGBA8" : "BC",
                    c.width, c.height, mips, tex.bytes.size(), read.header.flags);
    }
    // Refusals before any byte is written.
    auto throws = [](const std::function<void()>& f) {
        try {
            f();
        } catch (const std::invalid_argument&) {
            return true;
        }
        return false;
    };
    const std::vector<std::vector<uint8_t>> one{std::vector<uint8_t>(16)};
    CHECK(throws([&] { (void)WriteUzTextureFile("n", uz::TextureFormat::BC5, true, 4, 4, one); }));
    CHECK(throws([&] { (void)WriteUzTextureFile("h", uz::TextureFormat::BC4, true, 4, 4, {std::vector<uint8_t>(8)}); }));
    CHECK(throws([&] { (void)WriteUzTextureFile("a", uz::TextureFormat::BC7, false, 4, 4, {std::vector<uint8_t>(8)}); }));
    CHECK(throws([&] { (void)WriteUzTextureFile("a", uz::TextureFormat::BC7, false, 4, 4, {one[0], one[0], one[0], one[0]}); }));
    CHECK(throws([&] { (void)WriteUzTextureFile("a", static_cast<uz::TextureFormat>(6), false, 4, 4, one); }));
    CHECK(throws([&] { (void)GenerateMipChain(AuthoredRgba16(6, 4), {MipClass::Linear, 0.5}); }));
    // The reader refuses a damaged file.
    std::vector<uint8_t> bad = WriteUzTextureFile("a", uz::TextureFormat::BC7, false, 4, 4, one).bytes;
    bad[0x18] = 2;  // a flag bit other than sRGB
    bool rejected = false;
    try {
        (void)ParseUzTexture(bad);
    } catch (const UzTextureReadError&) {
        rejected = true;
    }
    CHECK(rejected);
}

// ── 3.7 Lossy-derivative report ─────────────────────────────────────────────────────────────

void ReportLossy(const char* map, BcFormat bc, const UzTextureSpec& spec, const Rgba16Image& canonical) {
    const std::vector<Rgba16Image> chain = GenerateMipChain(canonical, spec.mips);
    const ReadUzTexture read = ParseUzTexture(CookUzTexture(EtcpakEncoder(), canonical, spec, 0).bytes);
    const char* names[4] = {"R", "G", "B", "A"};
    const int channels = bc == BcFormat::Bc4 ? 1 : bc == BcFormat::Bc5 ? 2 : 4;
    for (uint32_t level = 0; level < read.header.mipCount; ++level) {
        // Level 0 against the canonical map itself, deeper levels against their 16-bit chain level.
        const Rgba16Image& reference = level == 0 ? canonical : chain[level];
        const Rgba8Image decoded = DecodeBc(bc, read.blobs[level], read.mips[level].width, read.mips[level].height);
        const std::array<ChannelError, 4> errors = LossyDerivativeError(reference, decoded);
        for (int c = 0; c < channels; ++c) {
            std::printf("  LOSSY-DERIVATIVE map=%s format=%s mip=%u channel=%s max=%.6f mean=%.6f p99=%.6f\n",
                        map, std::string(BcFormatName(bc)).c_str(), level, names[c], errors[c].max,
                        errors[c].mean, errors[c].p99);
            CHECK(std::isfinite(errors[c].max) && errors[c].mean <= errors[c].max && errors[c].p99 <= errors[c].max);
            if (level == 0) CHECK(errors[c].max < 0.25);
        }
    }
}

void CaseLossyDerivative() {
    Rgba16Image orm{256, 256, std::vector<uint16_t>(256 * 256 * 4)};
    for (uint32_t y = 0; y < 256; ++y)
        for (uint32_t x = 0; x < 256; ++x) {
            uint16_t* t = orm.rgba.data() + (uint64_t{y} * 256 + x) * 4;
            t[0] = ToCode(0.6 + 0.4 * std::cos(x * 0.05) * std::cos(y * 0.07));  // AO
            t[1] = ToCode(double(x + y) / 510.0);                               // roughness
            t[2] = (x / 32 + y / 32) % 2 ? 65535 : 0;                            // metallic
            t[3] = 65535;
        }
    std::printf("  lossy-derivative contract (decoded BC against the canonical map; not authoring equality)\n");
    ReportLossy("orm", BcFormat::Bc7, {"orm", uz::TextureFormat::BC7, false, {MipClass::Linear, 0.5}}, orm);
    Rgba16Image height = orm;
    for (uint64_t i = 0; i < 256 * 256; ++i) height.rgba[i * 4] = height.rgba[i * 4 + 1];
    ReportLossy("height", BcFormat::Bc4, {"height", uz::TextureFormat::BC4, false, {MipClass::Linear, 0.5}}, height);
}

const std::vector<std::pair<std::string, std::function<void()>>>& Cases() {
    static const std::vector<std::pair<std::string, std::function<void()>>> cases = {
        {"encoder_determinism", CaseEncoderDeterminism},
        {"encoder_channels", CaseEncoderChannels},
        {"colour_mips", CaseColourMips},
        {"normal_mips", CaseNormalMips},
        {"alpha_coverage", CaseAlphaCoverage},
        {"negative_z", CaseNegativeZ},
        {"uztexture_layout", CaseUzTextureLayout},
        {"normal_colour_space", CaseNormalColourSpace},
        {"lossy_derivative", CaseLossyDerivative},
    };
    return cases;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2 || std::string(argv[1]) != "run") {
        std::fprintf(stderr, "usage: uzp-texture-tests run [case]\n");
        return 2;
    }
    const std::string only = argc > 2 ? argv[2] : "";
    int failed = 0;
    int ran = 0;
    for (const auto& [name, run] : Cases()) {
        if (!only.empty() && name != only) continue;
        ++ran;
        std::printf("CASE %s\n", name.c_str());
        try {
            run();
            std::printf("PASS %s\n", name.c_str());
        } catch (const Failure& f) {
            ++failed;
            std::printf("FAIL %s: %s\n", name.c_str(), f.message.c_str());
        } catch (const std::exception& e) {
            ++failed;
            std::printf("FAIL %s: exception %s\n", name.c_str(), e.what());
        }
        std::fflush(stdout);
    }
    if (ran == 0) {
        std::fprintf(stderr, "unknown case %s\n", only.c_str());
        return 2;
    }
    return failed == 0 ? 0 : 1;
}
