#include "preview/environment.h"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <numbers>
#include <optional>
#include <span>

#include "render/disk_cache.h"
#include "tinyexr.h"
#include "uzp_core/manifest/sha256.h"

namespace uzp::preview {

namespace {

using Vec = std::array<double, 3>;

constexpr double kPi = std::numbers::pi;

Vec Normalised(const Vec& a) {
    const double length = std::sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2]);
    return {a[0] / length, a[1] / length, a[2] / length};
}
Vec Cross(const Vec& a, const Vec& b) {
    return {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]};
}
double Dot(const Vec& a, const Vec& b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }

/// The van der Corput radical inverse in base 2 of `i`, in [0, 1).
double RadicalInverse(uint32_t i) {
    i = (i << 16u) | (i >> 16u);
    i = ((i & 0x55555555u) << 1u) | ((i & 0xAAAAAAAAu) >> 1u);
    i = ((i & 0x33333333u) << 2u) | ((i & 0xCCCCCCCCu) >> 2u);
    i = ((i & 0x0F0F0F0Fu) << 4u) | ((i & 0xF0F0F0F0u) >> 4u);
    i = ((i & 0x00FF00FFu) << 8u) | ((i & 0xFF00FF00u) >> 8u);
    return static_cast<double>(i) * 0x1p-32;
}

/// The GGX half vector of sample (xi1, xi2) for alpha, in the frame where n = +Z.
Vec GgxHalfVector(double xi1, double xi2, double alpha) {
    const double a2 = alpha * alpha;
    const double phi = 2.0 * kPi * xi1;
    const double cosTheta = std::sqrt((1.0 - xi2) / (1.0 + (a2 - 1.0) * xi2));
    const double sinTheta = std::sqrt(std::max(0.0, 1.0 - cosTheta * cosTheta));
    return {sinTheta * std::cos(phi), sinTheta * std::sin(phi), cosTheta};
}

/// Smith's Lambda of the GGX distribution at cos(theta) = c.
double SmithLambda(double c, double alpha) {
    if (alpha == 0.0) return 0.0;
    const double c2 = c * c;
    const double tan2 = (1.0 - c2) / c2;
    return (-1.0 + std::sqrt(1.0 + alpha * alpha * tan2)) / 2.0;
}

/// The average of the source texels whose centres lie in each destination texel's footprint (the
/// texel under the destination centre when none does).
EnvironmentImage ResampleArea(const EnvironmentImage& source, uint32_t width, uint32_t height) {
    EnvironmentImage out{width, height, std::vector<float>(size_t{width} * height * 3)};
    const double sx = static_cast<double>(source.width) / width;
    const double sy = static_cast<double>(source.height) / height;
    for (uint32_t y = 0; y < height; ++y) {
        // Source rows whose centre (j + 1/2) lies in [y sy, (y + 1) sy).
        uint32_t y0 = static_cast<uint32_t>(std::ceil(y * sy - 0.5));
        uint32_t y1 = static_cast<uint32_t>(std::ceil((y + 1) * sy - 0.5));
        if (y1 <= y0) {
            y0 = std::min(source.height - 1, static_cast<uint32_t>((y + 0.5) * sy));
            y1 = y0 + 1;
        }
        for (uint32_t x = 0; x < width; ++x) {
            uint32_t x0 = static_cast<uint32_t>(std::ceil(x * sx - 0.5));
            uint32_t x1 = static_cast<uint32_t>(std::ceil((x + 1) * sx - 0.5));
            if (x1 <= x0) {
                x0 = std::min(source.width - 1, static_cast<uint32_t>((x + 0.5) * sx));
                x1 = x0 + 1;
            }
            double sum[3] = {0.0, 0.0, 0.0};
            for (uint32_t j = y0; j < y1; ++j) {
                for (uint32_t i = x0; i < x1; ++i) {
                    const float* texel = &source.rgb[(size_t{j} * source.width + i) * 3];
                    for (int c = 0; c < 3; ++c) sum[c] += texel[c];
                }
            }
            const double count = static_cast<double>(y1 - y0) * (x1 - x0);
            for (int c = 0; c < 3; ++c) {
                out.rgb[(size_t{y} * width + x) * 3 + c] = static_cast<float>(sum[c] / count);
            }
        }
    }
    return out;
}

/// The cumulative distribution of `weights`, from 0 to 1 (uniform when they sum to zero).
std::vector<float> Cdf(const std::vector<double>& weights) {
    double total = 0.0;
    for (const double w : weights) total += w;
    std::vector<float> cdf(weights.size() + 1, 0.0f);
    double sum = 0.0;
    for (size_t i = 0; i < weights.size(); ++i) {
        sum += weights[i];
        cdf[i + 1] = static_cast<float>(total > 0.0 ? sum / total : static_cast<double>(i + 1) / weights.size());
    }
    cdf.back() = 1.0f;
    return cdf;
}

ImportanceDistribution BuildImportance(const RadianceLevel& level) {
    ImportanceDistribution d{level.width, level.height, {}, {}};
    bool lit = false;
    for (const float value : level.rgb) lit = lit || value > 0.0f;
    std::vector<double> rows(level.height);
    std::vector<double> texels(level.width);
    d.conditionalCdf.reserve(size_t{level.height} * (level.width + 1));
    for (uint32_t y = 0; y < level.height; ++y) {
        const double sinTheta = std::sin(kPi * (y + 0.5) / level.height);
        double row = 0.0;
        for (uint32_t x = 0; x < level.width; ++x) {
            const float* texel = &level.rgb[(size_t{y} * level.width + x) * 3];
            const double mean = lit ? (static_cast<double>(texel[0]) + texel[1] + texel[2]) / 3.0 : 1.0;
            texels[x] = mean * sinTheta;
            row += texels[x];
        }
        rows[y] = row;
        const std::vector<float> cdf = Cdf(texels);
        d.conditionalCdf.insert(d.conditionalCdf.end(), cdf.begin(), cdf.end());
    }
    d.marginalCdf = Cdf(rows);
    return d;
}

std::expected<EnvironmentImage, std::string> Checked(EnvironmentImage image) {
    for (const float value : image.rgb) {
        if (!std::isfinite(value) || value < 0.0f) {
            return std::unexpected(std::string("environment: a texel is negative or not finite"));
        }
    }
    return image;
}

std::expected<EnvironmentImage, std::string> DecodeExr(std::string_view bytes) {
    float* rgba = nullptr;
    int width = 0;
    int height = 0;
    const char* error = nullptr;
    const int status = LoadEXRFromMemory(&rgba, &width, &height, reinterpret_cast<const unsigned char*>(bytes.data()),
                                         bytes.size(), &error);
    if (status != TINYEXR_SUCCESS) {
        std::string reason = error ? error : "unknown error";
        if (error) FreeEXRErrorMessage(error);
        return std::unexpected("environment: OpenEXR decode failed: " + reason);
    }
    EnvironmentImage image{static_cast<uint32_t>(width), static_cast<uint32_t>(height), {}};
    image.rgb.resize(size_t{image.width} * image.height * 3);
    for (size_t i = 0; i < size_t{image.width} * image.height; ++i) {
        for (int c = 0; c < 3; ++c) image.rgb[i * 3 + c] = rgba[i * 4 + c];
    }
    std::free(rgba);
    return Checked(std::move(image));
}

std::expected<EnvironmentImage, std::string> DecodeHdr(std::string_view bytes) {
    const auto fail = [](const std::string& why) {
        return std::unexpected("environment: Radiance HDR decode failed: " + why);
    };
    size_t pos = 0;
    const auto line = [&]() -> std::string_view {
        const size_t end = bytes.find('\n', pos);
        if (end == std::string_view::npos) return {};
        const std::string_view text = bytes.substr(pos, end - pos);
        pos = end + 1;
        return text;
    };
    bool rgbe = false;
    for (;;) {
        if (pos >= bytes.size()) return fail("no header end");
        const std::string_view text = line();
        if (text.empty()) break;
        if (text == "FORMAT=32-bit_rle_rgbe") rgbe = true;
        if (text.starts_with("FORMAT=") && !rgbe) return fail("format " + std::string(text.substr(7)));
    }
    const std::string resolution(line());
    int height = 0;
    int width = 0;
    char ySign = 0;
    char xSign = 0;
    if (std::sscanf(resolution.c_str(), "%cY %d %cX %d", &ySign, &height, &xSign, &width) != 4 || ySign != '-' ||
        xSign != '+' || width <= 0 || height <= 0) {
        return fail("only '-Y <h> +X <w>' resolutions are read, got '" + resolution + "'");
    }
    EnvironmentImage image{static_cast<uint32_t>(width), static_cast<uint32_t>(height), {}};
    image.rgb.resize(size_t{image.width} * image.height * 3);
    std::vector<uint8_t> scan(size_t{image.width} * 4);
    const auto byte = [&]() -> int {
        if (pos >= bytes.size()) return -1;
        return static_cast<uint8_t>(bytes[pos++]);
    };
    for (uint32_t y = 0; y < image.height; ++y) {
        const bool rle = image.width >= 8 && image.width < 32768 && pos + 4 <= bytes.size() &&
                         static_cast<uint8_t>(bytes[pos]) == 2 && static_cast<uint8_t>(bytes[pos + 1]) == 2 &&
                         ((static_cast<uint8_t>(bytes[pos + 2]) << 8) | static_cast<uint8_t>(bytes[pos + 3])) ==
                             static_cast<int>(image.width);
        if (rle) {
            pos += 4;
            for (uint32_t c = 0; c < 4; ++c) {
                uint32_t x = 0;
                while (x < image.width) {
                    int count = byte();
                    if (count <= 0) return fail("truncated run-length data");
                    if (count > 128) {
                        count -= 128;
                        const int value = byte();
                        if (value < 0 || x + static_cast<uint32_t>(count) > image.width) return fail("bad run");
                        for (int k = 0; k < count; ++k) scan[size_t{x++} * 4 + c] = static_cast<uint8_t>(value);
                    } else {
                        if (x + static_cast<uint32_t>(count) > image.width) return fail("bad literal run");
                        for (int k = 0; k < count; ++k) {
                            const int value = byte();
                            if (value < 0) return fail("truncated run-length data");
                            scan[size_t{x++} * 4 + c] = static_cast<uint8_t>(value);
                        }
                    }
                }
            }
        } else {
            if (pos + scan.size() > bytes.size()) return fail("truncated pixel data");
            std::memcpy(scan.data(), bytes.data() + pos, scan.size());
            pos += scan.size();
        }
        for (uint32_t x = 0; x < image.width; ++x) {
            const uint8_t* p = &scan[size_t{x} * 4];
            const float scale = p[3] == 0 ? 0.0f : std::ldexp(1.0f, static_cast<int>(p[3]) - (128 + 8));
            for (int c = 0; c < 3; ++c) image.rgb[(size_t{y} * image.width + x) * 3 + c] = p[c] * scale;
        }
    }
    return Checked(std::move(image));
}

// ── Persistent lighting (decision 253) ───────────────────────────────────────

/// The cap of the `lighting` area (an entry is about 2 MiB).
constexpr uint64_t kLightingCacheBytes = 256ull << 20;

render::CacheKey LightingKey(std::string_view sha256) {
    const std::string text = "uzp-lighting 1; " + render::BuildFingerprint() + "; mxcsr " +
                             std::to_string(render::FloatControlBits()) + "; environment " + std::string(sha256) +
                             "; levels " + std::to_string(kRadianceLevels) + " width " + std::to_string(kRadianceWidth) +
                             " prefilter " + std::to_string(kPrefilterSamples) + " brdf " +
                             std::to_string(kBrdfTableSize) + " samples " + std::to_string(kBrdfSamples);
    core::Sha256 hash;
    hash.Update(text);
    return hash.Finish();
}

/// The payload of `PrecomputeLighting`'s result: the SH coefficients, each level's width, height,
/// roughness and texels, the albedo table; 32-bit little-endian words. The importance distribution
/// is not stored: it is a function of level 0 alone, rebuilt on load (decision 251).
constexpr uint64_t LightingBytes() {
    uint64_t floats = 27 + uint64_t{kBrdfTableSize} * kBrdfTableSize * 3;
    for (uint32_t l = 0; l < kRadianceLevels; ++l) {
        floats += 3 + uint64_t{kRadianceWidth >> l} * (kRadianceWidth >> (l + 1)) * 3;
    }
    return floats * 4;
}

std::vector<std::byte> SerializeLighting(const EnvironmentLighting& lighting) {
    std::vector<std::byte> out;
    out.reserve(static_cast<size_t>(LightingBytes()));
    auto write = [&](const void* data, size_t bytes) {
        const auto* first = static_cast<const std::byte*>(data);
        out.insert(out.end(), first, first + bytes);
    };
    write(lighting.sh.data(), sizeof(lighting.sh));
    for (const RadianceLevel& level : lighting.radiance) {
        write(&level.width, 4);
        write(&level.height, 4);
        write(&level.roughness, 4);
        write(level.rgb.data(), level.rgb.size() * sizeof(float));
    }
    write(lighting.brdf.data(), lighting.brdf.size() * sizeof(float));
    return out;
}

/// The lighting of a payload `SerializeLighting` wrote; nullopt when its shape is not the
/// constants' (the key covers them, so only a damaged entry can differ).
std::optional<EnvironmentLighting> DeserializeLighting(std::span<const std::byte> payload) {
    size_t offset = 0;
    auto read = [&](void* data, size_t bytes) {
        if (offset + bytes > payload.size()) return false;
        std::memcpy(data, payload.data() + offset, bytes);
        offset += bytes;
        return true;
    };
    EnvironmentLighting lighting;
    if (!read(lighting.sh.data(), sizeof(lighting.sh))) return std::nullopt;
    for (uint32_t l = 0; l < kRadianceLevels; ++l) {
        RadianceLevel level;
        if (!read(&level.width, 4) || !read(&level.height, 4) || !read(&level.roughness, 4) ||
            level.width != kRadianceWidth >> l || level.height != kRadianceWidth >> (l + 1)) {
            return std::nullopt;
        }
        level.rgb.resize(size_t{level.width} * level.height * 3);
        if (!read(level.rgb.data(), level.rgb.size() * sizeof(float))) return std::nullopt;
        lighting.radiance.push_back(std::move(level));
    }
    lighting.brdf.resize(size_t{kBrdfTableSize} * kBrdfTableSize * 3);
    if (!read(lighting.brdf.data(), lighting.brdf.size() * sizeof(float)) || offset != payload.size()) {
        return std::nullopt;
    }
    lighting.importance = BuildImportance(lighting.radiance[0]);
    return lighting;
}

}  // namespace

std::expected<EnvironmentLighting, std::string> LightingOf(std::string_view sha256, std::string_view bytes) {
    render::DiskCache* disk = render::CacheArea("lighting", kLightingCacheBytes);
    const render::CacheKey key = disk != nullptr ? LightingKey(sha256) : render::CacheKey{};
    if (disk != nullptr) {
        if (std::optional<std::vector<std::byte>> payload = disk->Get(key, LightingBytes())) {
            if (std::optional<EnvironmentLighting> stored = DeserializeLighting(*payload)) return std::move(*stored);
        }
    }
    std::expected<EnvironmentImage, std::string> image = DecodeEnvironment(bytes);
    if (!image) return std::unexpected(image.error());
    EnvironmentLighting lighting = PrecomputeLighting(*image);
    if (disk != nullptr) disk->Put(key, SerializeLighting(lighting));
    return lighting;
}

std::expected<EnvironmentImage, std::string> DecodeEnvironment(std::string_view bytes) {
    if (bytes.size() >= 4 && static_cast<uint8_t>(bytes[0]) == 0x76 && static_cast<uint8_t>(bytes[1]) == 0x2F &&
        static_cast<uint8_t>(bytes[2]) == 0x31 && static_cast<uint8_t>(bytes[3]) == 0x01) {
        return DecodeExr(bytes);
    }
    if (bytes.starts_with("#?RADIANCE") || bytes.starts_with("#?RGBE")) return DecodeHdr(bytes);
    return std::unexpected(std::string("environment: unsupported encoding (OpenEXR and Radiance HDR are read)"));
}

EnvironmentImage UniformEnvironment(float r, float g, float b, uint32_t width, uint32_t height) {
    EnvironmentImage image{width, height, {}};
    image.rgb.reserve(size_t{width} * height * 3);
    for (size_t i = 0; i < size_t{width} * height; ++i) image.rgb.insert(image.rgb.end(), {r, g, b});
    return image;
}

std::array<double, 3> DirectionOf(double u, double v) {
    const double phi = 2.0 * kPi * (u - 0.25);
    const double theta = kPi * v;
    const double s = std::sin(theta);
    return {-std::sin(phi) * s, std::cos(theta), std::cos(phi) * s};
}

std::array<float, 3> SampleDirection(const EnvironmentImage& image, const std::array<double, 3>& d,
                                     double rotationDegrees) {
    double u = std::atan2(-d[0], d[2]) / (2.0 * kPi) + 0.25 + rotationDegrees / 360.0;
    u -= std::floor(u);
    const double v = std::acos(std::clamp(d[1], -1.0, 1.0)) / kPi;
    const double x = u * image.width - 0.5;
    const double y = std::clamp(v * image.height - 0.5, 0.0, static_cast<double>(image.height - 1));
    const double fx = std::floor(x);
    const double fy = std::floor(y);
    const double tx = x - fx;
    const double ty = y - fy;
    const auto column = [&](double c) {
        const int64_t w = image.width;
        return static_cast<uint32_t>(((static_cast<int64_t>(c) % w) + w) % w);
    };
    const uint32_t x0 = column(fx);
    const uint32_t x1 = column(fx + 1);
    const uint32_t y0 = static_cast<uint32_t>(fy);
    const uint32_t y1 = std::min(y0 + 1, image.height - 1);
    std::array<float, 3> out{};
    for (int c = 0; c < 3; ++c) {
        const auto at = [&](uint32_t px, uint32_t py) {
            return static_cast<double>(image.rgb[(size_t{py} * image.width + px) * 3 + c]);
        };
        const double top = at(x0, y0) + (at(x1, y0) - at(x0, y0)) * tx;
        const double bottom = at(x0, y1) + (at(x1, y1) - at(x0, y1)) * tx;
        out[c] = static_cast<float>(top + (bottom - top) * ty);
    }
    return out;
}

EnvironmentLighting PrecomputeLighting(const EnvironmentImage& image) {
    EnvironmentLighting lighting;

    // Area-resampled copies of the source at 512 x 256, 256 x 128, ...: level l >= 1 integrates
    // the copy at twice its own resolution, level 0 is the 512 x 256 copy itself.
    std::vector<EnvironmentImage> chain;
    for (uint32_t l = 0; l < kRadianceLevels; ++l) {
        chain.push_back(ResampleArea(image, kRadianceWidth >> l, kRadianceWidth >> (l + 1)));
    }

    for (uint32_t l = 0; l < kRadianceLevels; ++l) {
        RadianceLevel level;
        level.width = kRadianceWidth >> l;
        level.height = kRadianceWidth >> (l + 1);
        level.roughness = static_cast<float>(static_cast<double>(l) / (kRadianceLevels - 1));
        if (l == 0) {
            level.rgb = chain[0].rgb;
            lighting.radiance.push_back(std::move(level));
            continue;
        }
        const EnvironmentImage& source = chain[l - 1];
        const double alpha = static_cast<double>(level.roughness) * level.roughness;
        level.rgb.resize(size_t{level.width} * level.height * 3);
        for (uint32_t y = 0; y < level.height; ++y) {
            for (uint32_t x = 0; x < level.width; ++x) {
                const Vec n = DirectionOf((x + 0.5) / level.width, (y + 0.5) / level.height);
                const Vec up = std::abs(n[1]) < 0.999 ? Vec{0.0, 1.0, 0.0} : Vec{1.0, 0.0, 0.0};
                const Vec t = Normalised(Cross(up, n));
                const Vec b = Cross(n, t);
                double sum[3] = {0.0, 0.0, 0.0};
                double weight = 0.0;
                for (uint32_t i = 0; i < kPrefilterSamples; ++i) {
                    const Vec hl = GgxHalfVector((i + 0.5) / kPrefilterSamples, RadicalInverse(i), alpha);
                    const Vec h{hl[0] * t[0] + hl[1] * b[0] + hl[2] * n[0], hl[0] * t[1] + hl[1] * b[1] + hl[2] * n[1],
                                hl[0] * t[2] + hl[1] * b[2] + hl[2] * n[2]};
                    const double nh = Dot(n, h);
                    const Vec dir{2.0 * nh * h[0] - n[0], 2.0 * nh * h[1] - n[1], 2.0 * nh * h[2] - n[2]};
                    const double nl = Dot(n, dir);
                    if (nl <= 0.0) continue;
                    const std::array<float, 3> radiance = SampleDirection(source, Normalised(dir));
                    for (int c = 0; c < 3; ++c) sum[c] += radiance[c] * nl;
                    weight += nl;
                }
                for (int c = 0; c < 3; ++c) {
                    level.rgb[(size_t{y} * level.width + x) * 3 + c] = static_cast<float>(sum[c] / weight);
                }
            }
        }
        lighting.radiance.push_back(std::move(level));
    }
    lighting.importance = BuildImportance(lighting.radiance[0]);

    // SH projection over the 128 x 64 copy, each texel weighted by its solid angle.
    {
        const EnvironmentImage& source = chain[2];
        double coefficients[27] = {};
        for (uint32_t y = 0; y < source.height; ++y) {
            const double v = (y + 0.5) / source.height;
            const double solidAngle = (2.0 * kPi / source.width) * (kPi / source.height) * std::sin(kPi * v);
            for (uint32_t x = 0; x < source.width; ++x) {
                const Vec d = DirectionOf((x + 0.5) / source.width, v);
                const double basis[9] = {0.282095,
                                         0.488603 * d[1],
                                         0.488603 * d[2],
                                         0.488603 * d[0],
                                         1.092548 * d[0] * d[1],
                                         1.092548 * d[1] * d[2],
                                         0.315392 * (3.0 * d[2] * d[2] - 1.0),
                                         1.092548 * d[0] * d[2],
                                         0.546274 * (d[0] * d[0] - d[1] * d[1])};
                for (int i = 0; i < 9; ++i) {
                    for (int c = 0; c < 3; ++c) {
                        coefficients[i * 3 + c] +=
                            source.rgb[(size_t{y} * source.width + x) * 3 + c] * basis[i] * solidAngle;
                    }
                }
            }
        }
        const double band[9] = {kPi, 2.0 * kPi / 3.0, 2.0 * kPi / 3.0, 2.0 * kPi / 3.0, kPi / 4.0,
                                 kPi / 4.0, kPi / 4.0, kPi / 4.0, kPi / 4.0};
        for (int i = 0; i < 9; ++i) {
            for (int c = 0; c < 3; ++c) lighting.sh[i * 3 + c] = static_cast<float>(coefficients[i * 3 + c] * band[i]);
        }
    }

    // Directional albedo table: (A, B) of the split sum and D of Burley's diffuse lobe.
    lighting.brdf.resize(size_t{kBrdfTableSize} * kBrdfTableSize * 3);
    for (uint32_t row = 0; row < kBrdfTableSize; ++row) {
        const double roughness = static_cast<double>(row) / (kBrdfTableSize - 1);
        const double alpha = roughness * roughness;
        for (uint32_t col = 0; col < kBrdfTableSize; ++col) {
            const double nv = (col + 0.5) / kBrdfTableSize;
            const Vec v{std::sqrt(1.0 - nv * nv), 0.0, nv};
            double a = 0.0;
            double bias = 0.0;
            double diffuse = 0.0;
            for (uint32_t i = 0; i < kBrdfSamples; ++i) {
                const double xi1 = (i + 0.5) / kBrdfSamples;
                const double xi2 = RadicalInverse(i);
                const Vec h = GgxHalfVector(xi1, xi2, alpha);
                const double vh = Dot(v, h);
                const Vec l{2.0 * vh * h[0] - v[0], 2.0 * vh * h[1] - v[1], 2.0 * vh * h[2] - v[2]};
                const double nl = l[2];
                if (nl > 0.0 && vh > 0.0) {
                    const double g2 = 1.0 / (1.0 + SmithLambda(nv, alpha) + SmithLambda(nl, alpha));
                    const double visibility = g2 * vh / (h[2] * nv);
                    const double fc = std::pow(1.0 - vh, 5.0);
                    a += (1.0 - fc) * visibility;
                    bias += fc * visibility;
                }
                // Burley's lobe with cosine-weighted directions: the estimate of its albedo is the
                // mean of the lobe without its 1 / pi.
                const double r = std::sqrt(xi1);
                const double phi = 2.0 * kPi * xi2;
                const Vec ld{r * std::cos(phi), r * std::sin(phi), std::sqrt(1.0 - xi1)};
                const Vec hd = Normalised(Vec{v[0] + ld[0], v[1] + ld[1], v[2] + ld[2]});
                const double ldh = Dot(ld, hd);
                const double fd90 = 0.5 + 2.0 * roughness * ldh * ldh;
                diffuse += (1.0 + (fd90 - 1.0) * std::pow(1.0 - ld[2], 5.0)) *
                           (1.0 + (fd90 - 1.0) * std::pow(1.0 - nv, 5.0));
            }
            float* entry = &lighting.brdf[(size_t{row} * kBrdfTableSize + col) * 3];
            entry[0] = static_cast<float>(a / kBrdfSamples);
            entry[1] = static_cast<float>(bias / kBrdfSamples);
            entry[2] = static_cast<float>(diffuse / kBrdfSamples);
        }
    }
    return lighting;
}

std::array<float, 3> Irradiance(const EnvironmentLighting& lighting, const std::array<double, 3>& n) {
    const double basis[9] = {0.282095,
                             0.488603 * n[1],
                             0.488603 * n[2],
                             0.488603 * n[0],
                             1.092548 * n[0] * n[1],
                             1.092548 * n[1] * n[2],
                             0.315392 * (3.0 * n[2] * n[2] - 1.0),
                             1.092548 * n[0] * n[2],
                             0.546274 * (n[0] * n[0] - n[1] * n[1])};
    std::array<float, 3> out{};
    for (int c = 0; c < 3; ++c) {
        double sum = 0.0;
        for (int i = 0; i < 9; ++i) sum += lighting.sh[i * 3 + c] * basis[i];
        out[c] = static_cast<float>(sum);
    }
    return out;
}

std::array<float, 3> BrdfEntry(const EnvironmentLighting& lighting, uint32_t nv, uint32_t roughness) {
    const float* entry = &lighting.brdf[(size_t{roughness} * kBrdfTableSize + nv) * 3];
    return {entry[0], entry[1], entry[2]};
}

}  // namespace uzp::preview
