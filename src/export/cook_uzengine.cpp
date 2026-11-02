// `UzPainter.exe cook-uzengine` (cli.h; decision 380, task phase3.3_uze-png-cook-cli): a texture
// set exported as PNG turned into the UzEngine delivery through the native preset's own code. The
// targets (binding, format, colour space, mip class, negative-Z policy, file names) are read from
// the shipped `uzengine` preset; each texture is cooked by write.h `CookUzEngineDerivative` and the
// material written by `WriteUzEngineMaterial`, the functions `EncodeExport` cooks the preset with.
// What this file adds is the input side only: decoding and checking the PNGs.

#include "export/cli.h"

#include "export/config.h"
#include "export/plan.h"
#include "export/preset_aliases.h"
#include "export/publish.h"
#include "export/receipt.h"
#include "export/write.h"
#include "spng.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"

#include <algorithm>
#include <array>
#include <bit>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <map>
#include <memory>
#include <optional>
#include <stdexcept>

namespace uzp::exporter {

namespace {

namespace fs = std::filesystem;
namespace json = core::json;

constexpr const char* kCookUsage =
    "usage: UzPainter.exe cook-uzengine --set <name> --out <dir> --normal-convention opengl|directx\n"
    "           --albedo <png> --normal <png> (--orm <png> | --ao <png> --roughness <png> --metallic <png>)\n"
    "           [--emissive <png>] [--height <png>] [--specularweight <png>]\n";

constexpr std::string_view kVerb = "cook-uzengine";

/// A refused input: its reason is printed and nothing is written.
class Refusal : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

/// A decoded input PNG.
struct InputPng {
    std::string path;
    std::string sha256;
    uint32_t bitDepth = 8;
    /// "L", "LA", "RGB" or "RGBA": the PNG's colour type.
    std::string channels;
    /// R, G, B, A at 16 bits: a grey PNG as R = G = B, a missing alpha as 65535, an 8-bit code as
    /// code * 257 (mips.h `Rgba16Image`).
    Rgba16Image image;
};

struct SpngFree {
    void operator()(spng_ctx* ctx) const { spng_ctx_free(ctx); }
};

/// The PNG at `path` (UTF-8), refused unless it is an 8- or 16-bit grey, grey+alpha, RGB or RGBA
/// image without a tRNS chunk. Colour chunks (gAMA, iCCP, sRGB, cHRM) are not applied: the codes
/// are read as they are stored.
InputPng ReadPng(const std::string& flag, const std::string& path) {
    const std::string what = flag + " " + path;
    std::ifstream stream(Utf8Path(path), std::ios::binary);
    if (!stream) throw Refusal(what + ": cannot read the file");
    const std::string bytes((std::istreambuf_iterator<char>(stream)), std::istreambuf_iterator<char>());
    std::unique_ptr<spng_ctx, SpngFree> ctx(spng_ctx_new(0));
    if (!ctx) throw std::runtime_error("cannot create a PNG decoder");
    spng_ihdr ihdr{};
    if (spng_set_png_buffer(ctx.get(), bytes.data(), bytes.size()) != 0 || spng_get_ihdr(ctx.get(), &ihdr) != 0) {
        throw Refusal(what + ": not a PNG file");
    }
    if (ihdr.color_type == SPNG_COLOR_TYPE_INDEXED) {
        throw Refusal(what + ": a palette PNG; the input contract is 8- or 16-bit grey, RGB or RGBA");
    }
    if (ihdr.bit_depth != 8 && ihdr.bit_depth != 16) {
        throw Refusal(what + ": " + std::to_string(ihdr.bit_depth) +
                      "-bit samples; the input contract is 8- or 16-bit");
    }
    spng_trns trns{};
    if (spng_get_trns(ctx.get(), &trns) == 0) {
        throw Refusal(what + ": a tRNS transparency chunk; opacity must be an alpha channel");
    }
    const bool sixteen = ihdr.bit_depth == 16;
    const int format = sixteen ? SPNG_FMT_RGBA16 : SPNG_FMT_RGBA8;
    size_t size = 0;
    if (spng_decoded_image_size(ctx.get(), format, &size) != 0) throw Refusal(what + ": cannot size the image");
    std::vector<unsigned char> decoded(size);
    if (const int e = spng_decode_image(ctx.get(), decoded.data(), size, format, 0)) {
        throw Refusal(what + ": cannot decode: " + spng_strerror(e));
    }
    InputPng png;
    png.path = path;
    png.sha256 = core::Sha256Hex(bytes);
    png.bitDepth = ihdr.bit_depth;
    switch (ihdr.color_type) {
        case SPNG_COLOR_TYPE_GRAYSCALE: png.channels = "L"; break;
        case SPNG_COLOR_TYPE_GRAYSCALE_ALPHA: png.channels = "LA"; break;
        case SPNG_COLOR_TYPE_TRUECOLOR: png.channels = "RGB"; break;
        default: png.channels = "RGBA"; break;
    }
    png.image.width = ihdr.width;
    png.image.height = ihdr.height;
    const size_t samples = size_t{ihdr.width} * ihdr.height * 4;
    png.image.rgba.resize(samples);
    for (size_t i = 0; i < samples; ++i) {
        if (sixteen) {
            // SPNG_FMT_RGBA16 is host-endian.
            uint16_t value = 0;
            std::memcpy(&value, decoded.data() + i * 2, 2);
            png.image.rgba[i] = value;
        } else {
            png.image.rgba[i] = static_cast<uint16_t>(decoded[i] * 257u);
        }
    }
    return png;
}

bool OpaqueAlpha(const Rgba16Image& image) {
    for (size_t i = 3; i < image.rgba.size(); i += 4) {
        if (image.rgba[i] != 65535) return false;
    }
    return true;
}

void RequireOpaque(const std::string& flag, const InputPng& png) {
    if (!OpaqueAlpha(png.image)) {
        throw Refusal(flag + " " + png.path + ": its alpha is not 1 everywhere; only the albedo alpha carries "
                      "opacity, and this map has no alpha in the UzEngine preset");
    }
}

void RequireGrey(const std::string& flag, const InputPng& png) {
    const std::vector<uint16_t>& v = png.image.rgba;
    for (size_t i = 0; i < v.size(); i += 4) {
        if (v[i] != v[i + 1] || v[i] != v[i + 2]) {
            const size_t t = i / 4;
            throw Refusal(flag + " " + png.path + ": not a grey map (R = G = B), first at texel (" +
                          std::to_string(t % png.image.width) + ", " + std::to_string(t / png.image.width) + ")");
        }
    }
}

/// `text` with every `$textureSet` replaced by `set`; any other `$` token is a malformed preset.
std::string Expand(std::string text, const std::string& set) {
    constexpr std::string_view token = "$textureSet";
    for (size_t at = text.find(token); at != std::string::npos; at = text.find(token, at + set.size())) {
        text.replace(at, token.size(), set);
    }
    if (text.find('$') != std::string::npos && set.find('$') == std::string::npos) {
        throw std::runtime_error("the shipped uzengine preset names \"" + text + "\", which this verb cannot expand");
    }
    return text;
}

std::string DecodedSha256(const Rgba16Image& image) {
    // Little-endian uint16 samples, R, G, B, A per texel, rows top first.
    std::string bytes;
    bytes.reserve(image.rgba.size() * 2);
    for (const uint16_t v : image.rgba) {
        bytes.push_back(static_cast<char>(v & 0xFF));
        bytes.push_back(static_cast<char>(v >> 8));
    }
    return core::Sha256Hex(bytes);
}

json::Array Gaps(const std::vector<std::pair<std::string, std::string>>& gaps) {
    json::Array out;
    for (const auto& [channel, gap] : gaps) out.push_back(json::Object{{"channel", channel}, {"gap", gap}});
    return out;
}

/// One cooked texture of the delivery, before anything is written.
struct Cooked {
    std::string role;
    UzTextureOutput output;
    EncodedUzTexture texture;
    uint32_t width = 0;
    uint32_t height = 0;
    std::vector<std::pair<std::string, std::string>> gaps;
};

struct Arguments {
    std::string set;
    std::string out;
    std::string convention;
    std::map<std::string, std::string> maps;
};

/// The parsed arguments, or nullopt for a usage error.
std::optional<Arguments> Parse(const std::vector<std::string>& args) {
    static const std::vector<std::string> kMaps{"albedo", "normal",    "orm",      "ao",
                                                "roughness", "metallic", "emissive", "height",
                                                "specularweight"};
    Arguments parsed;
    for (size_t i = 1; i < args.size(); i += 2) {
        if (i + 1 >= args.size() || !args[i].starts_with("--") || args[i + 1].empty()) return std::nullopt;
        const std::string key = args[i].substr(2);
        const std::string& value = args[i + 1];
        std::string* into = nullptr;
        if (key == "set") into = &parsed.set;
        else if (key == "out") into = &parsed.out;
        else if (key == "normal-convention") into = &parsed.convention;
        else if (std::find(kMaps.begin(), kMaps.end(), key) != kMaps.end()) into = &parsed.maps[key];
        if (into == nullptr || !into->empty()) return std::nullopt;
        *into = value;
    }
    const auto has = [&](const char* key) { return parsed.maps.contains(key); };
    const bool separate = has("ao") || has("roughness") || has("metallic");
    if (parsed.set.empty() || parsed.out.empty() || (parsed.convention != "opengl" && parsed.convention != "directx") ||
        !has("albedo") || !has("normal") || has("orm") == separate ||
        (separate && !(has("ao") && has("roughness") && has("metallic")))) {
        return std::nullopt;
    }
    return parsed;
}

int Cook(const Arguments& a, std::FILE* out) {
    // The set name is the stem of every file name: one path component, checked again as a delivery
    // path by WriteUzMaterial.
    if (a.set.find_first_of("/\\:") != std::string::npos || a.set == "." || a.set == "..") {
        throw Refusal("--set " + a.set + ": a texture set name is one file-name stem, without '/', '\\' or ':'");
    }
    const ShippedPreset preset = LoadShippedPreset(DefaultPresetDirectory(), "uzengine");
    if (!preset.spec.uzengine || !preset.spec.uzengine->material) {
        throw std::runtime_error("the shipped uzengine preset has no UzEngine targets");
    }
    const UzEngineTargets& targets = *preset.spec.uzengine;
    const auto target = [&](const std::string& role) -> const UzEngineTexture& {
        for (const UzEngineTexture& t : targets.textures) {
            if (t.map == "$textureSet_" + role) return t;
        }
        throw std::runtime_error("the shipped uzengine preset has no map $textureSet_" + role);
    };

    // 1. Every input decoded and checked against the contract.
    std::map<std::string, InputPng> inputs;
    for (const auto& [role, path] : a.maps) inputs.emplace(role, ReadPng("--" + role, path));
    const InputPng& albedo = inputs.at("albedo");
    const uint32_t width = albedo.image.width;
    const uint32_t height = albedo.image.height;
    for (const auto& [role, png] : inputs) {
        if (png.image.width != width || png.image.height != height) {
            throw Refusal("--" + role + " " + png.path + " is " + std::to_string(png.image.width) + "x" +
                          std::to_string(png.image.height) + " and --albedo is " + std::to_string(width) + "x" +
                          std::to_string(height) + "; every map of a set has one size");
        }
        if (role != "albedo") RequireOpaque("--" + role, png);
        if (role != "albedo" && role != "normal" && role != "orm" && role != "emissive") RequireGrey("--" + role, png);
    }
    if (!std::has_single_bit(width) || !std::has_single_bit(height)) {
        throw Refusal("the set is " + std::to_string(width) + "x" + std::to_string(height) +
                      "; the UzEngine mip chain needs a power of two on both sides (mips.h)");
    }
    const InputPng& normalPng = inputs.at("normal");
    if (normalPng.channels == "L" || normalPng.channels == "LA") {
        throw Refusal("--normal " + normalPng.path + ": a grey PNG; a normal map is RGB");
    }

    // 2. The canonical images the preset's textures are cooked from.
    std::map<std::string, Rgba16Image> images;
    images["albedo"] = albedo.image;
    Rgba16Image normal = normalPng.image;
    if (a.convention == "opengl") {
        // The preset stores Normal_DirectX (green = -v, phase0.9 §8): an OpenGL map's green mirrored.
        for (size_t i = 1; i < normal.rgba.size(); i += 4) normal.rgba[i] = static_cast<uint16_t>(65535 - normal.rgba[i]);
    }
    images["normal"] = std::move(normal);
    if (inputs.contains("orm")) {
        images["orm"] = inputs.at("orm").image;
    } else {
        Rgba16Image orm{width, height, std::vector<uint16_t>(size_t{width} * height * 4, 65535)};
        const char* sources[3] = {"ao", "roughness", "metallic"};
        for (size_t c = 0; c < 3; ++c) {
            const std::vector<uint16_t>& grey = inputs.at(sources[c]).image.rgba;
            for (size_t t = 0; t < size_t{width} * height; ++t) orm.rgba[t * 4 + c] = grey[t * 4];
        }
        images["orm"] = std::move(orm);
    }
    const bool emissiveGiven = inputs.contains("emissive");
    if (emissiveGiven) {
        images["emissive"] = inputs.at("emissive").image;
    } else {
        // What the preset cooks for a black emissive channel: (0, 0, 0) with alpha 1.
        Rgba16Image black{width, height, std::vector<uint16_t>(size_t{width} * height * 4, 0)};
        for (size_t i = 3; i < black.rgba.size(); i += 4) black.rgba[i] = 65535;
        images["emissive"] = std::move(black);
    }
    for (const char* role : {"height", "specularweight"}) {
        if (inputs.contains(role)) images[role] = inputs.at(role).image;
    }
    const bool albedoAlpha = !OpaqueAlpha(images.at("albedo"));

    // 3. Every texture cooked through the preset's derivative cook, then the material.
    std::vector<Cooked> cooked;
    for (const char* role : {"albedo", "normal", "orm", "emissive", "height", "specularweight"}) {
        if (!images.contains(role)) continue;
        const UzEngineTexture& t = target(role);
        Cooked c;
        c.role = role;
        c.width = width;
        c.height = height;
        c.output.relativePath = Expand(t.map, a.set) + ".uztexture";
        c.output.path = c.output.relativePath;
        c.output.negativeZ = t.negativeZ;
        c.output.binding = t.binding;
        c.output.format = t.format;
        c.output.srgb = t.srgb;
        c.output.mips = t.mips;
        c.output.canonical = inputs.contains(role) ? inputs.at(role).path : std::string("(") + role + ")";
        const std::string_view r = role;
        const FileLayout layout = r == "albedo" ? (albedoAlpha ? FileLayout::RGBA : FileLayout::RGB)
                                  : (r == "height" || r == "specularweight") ? FileLayout::L
                                                                              : FileLayout::RGB;
        render::Result<EncodedUzTexture> texture =
            CookUzEngineDerivative(c.output, "--" + std::string(role), images.at(role), layout);
        if (!texture) throw Refusal(texture.error().reason);
        c.texture = std::move(*texture);
        if (r == "albedo" && albedoAlpha) c.gaps.emplace_back("Opacity", kSm5OpacityGap);
        if (c.output.binding == "heightmap") c.gaps.emplace_back("Height", kHeightGap);
        if (r == "specularweight") c.gaps.emplace_back("SpecularWeight", kSpecularWeightGap);
        if (c.output.binding.empty() && c.gaps.empty()) c.gaps.emplace_back(t.map, kNoSlotGap);
        cooked.push_back(std::move(c));
    }
    const UzEngineMaterial& m = *targets.material;
    const auto derivative = [&](const std::string& map) -> std::string {
        if (map.empty()) return {};
        for (const Cooked& c : cooked) {
            if (Expand(map, a.set) + ".uztexture" == c.output.relativePath) return c.output.relativePath;
        }
        return {};
    };
    UzMaterialOutput planned;
    planned.textureSet = a.set;
    planned.preset = preset.id;
    planned.fileName = m.fileName;
    planned.relativePath = Expand(m.fileName, a.set) + ".uzmat";
    planned.albedo = derivative(m.albedo);
    planned.normal = derivative(m.normal);
    planned.orm = derivative(m.orm);
    planned.emissive = derivative(m.emissive);
    planned.height = derivative(m.height);
    EncodedUzMaterial material;
    try {
        material = WriteUzEngineMaterial(planned, albedoAlpha);
    } catch (const std::invalid_argument& e) {
        throw Refusal("--set " + a.set + ": " + e.what());
    }

    // 4. Written only now, textures in preset order and the material last.
    const fs::path root = Utf8Path(a.out);
    std::error_code error;
    fs::create_directories(root, error);
    if (error) throw std::runtime_error("cannot create " + a.out + ": " + error.message());
    const auto write = [&](const std::string& relativePath, const std::string& bytes) {
        const fs::path path = root / Utf8Path(relativePath);
        std::ofstream stream(path, std::ios::binary | std::ios::trunc);
        stream.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
        stream.close();
        if (!stream) throw std::runtime_error("cannot write " + Utf8String(path));
    };
    for (const Cooked& c : cooked) write(c.output.relativePath, c.texture.bytes);
    write(planned.relativePath, material.bytes);

    // 5. The receipt.
    json::Array inputList;
    for (const char* role : {"albedo", "normal", "orm", "ao", "roughness", "metallic", "emissive", "height",
                             "specularweight"}) {
        const std::string_view r = role;
        const bool colour = r == "albedo" || r == "emissive";
        if (!inputs.contains(role)) {
            if (r == "emissive") {
                inputList.push_back(json::Object{{"map", "emissive"},
                                                 {"path", nullptr},
                                                 {"synthesized", "black (0, 0, 0): no --emissive given"}});
            }
            continue;
        }
        const InputPng& png = inputs.at(role);
        json::Object entry{{"map", std::string(role)},
                           {"path", png.path},
                           {"sha256", png.sha256},
                           {"bit_depth", static_cast<std::int64_t>(png.bitDepth)},
                           {"channels", png.channels},
                           {"colour_space", colour ? "sRGB" : "linear"},
                           {"decoded_rgba16_sha256", DecodedSha256(png.image)}};
        if (r == "normal") {
            entry["convention"] = a.convention;
            entry["stored_convention"] = "directx";
            entry["green_mirrored"] = a.convention == "opengl";
        }
        inputList.push_back(std::move(entry));
    }
    json::Array files;
    for (const Cooked& c : cooked) {
        json::Object meta{{"binding", c.output.binding.empty() ? json::Value(nullptr) : json::Value(c.output.binding)},
                          {"format", c.texture.format},
                          {"srgb", c.output.srgb},
                          {"size", json::Array{static_cast<std::int64_t>(c.width), static_cast<std::int64_t>(c.height)}},
                          {"mips", static_cast<std::int64_t>(c.texture.mips)},
                          {"mip_filter", std::string(DerivativeMipsName(c.output.mips))},
                          {"layout", std::string(FileLayoutName(c.texture.layout))},
                          {"encoder", c.texture.encoder},
                          {"encoder_settings", c.texture.settings}};
        if (c.output.mips == DerivativeMips::masked_colour) meta["alpha_coverage_threshold"] = MipOptions{}.alphaThreshold;
        if (c.output.mips == DerivativeMips::normal) {
            meta["negative_z"] = json::Object{{"policy", std::string(NegativeZPolicyName(c.texture.policy))},
                                              {"texels", static_cast<std::int64_t>(c.texture.negativeTexels)}};
        }
        files.push_back(json::Object{{"path", c.output.relativePath},
                                     {"format", "uztexture"},
                                     {"bytes", static_cast<std::int64_t>(c.texture.bytes.size())},
                                     {"sha256", core::Sha256Hex(c.texture.bytes)},
                                     {"colour_space", c.output.srgb ? "sRGB" : "linear"},
                                     {"uztexture", std::move(meta)},
                                     {"consumer_gaps", Gaps(c.gaps)}});
    }
    std::vector<std::pair<std::string, std::string>> materialGaps;
    for (const std::array<std::string, 3>& g : material.gaps) materialGaps.emplace_back(g[0], g[2] + " (" + g[1] + ")");
    materialGaps.emplace_back("blend", kBlendGap);
    json::Value inlineMaterial = json::Parse(material.inlineMaterial);
    const std::string opacity = albedoAlpha ? "albedo alpha"
                                : albedo.channels == "RGBA" || albedo.channels == "LA"
                                    ? "1: the albedo alpha is 1 everywhere"
                                    : "1: the albedo PNG has no alpha";
    files.push_back(json::Object{{"path", planned.relativePath},
                                 {"format", "uzmat"},
                                 {"bytes", static_cast<std::int64_t>(material.bytes.size())},
                                 {"sha256", core::Sha256Hex(material.bytes)},
                                 {"uzmat", json::Object{{"blend", material.blend},
                                                        {"two_sided", false},
                                                        {"opacity", opacity},
                                                        {"albedo", planned.albedo},
                                                        {"normal", planned.normal},
                                                        {"orm", planned.orm},
                                                        {"emissive", planned.emissive},
                                                        {"height", planned.height.empty() ? json::Value(nullptr)
                                                                                          : json::Value(planned.height)},
                                                        {"inline_material", std::move(inlineMaterial)}}},
                                 {"consumer_gaps", Gaps(materialGaps)}});
    const std::string text = json::WriteCanonical(json::Object{
        {"verb", std::string(kVerb)},
        {"set", a.set},
        {"out", Utf8String(root)},
        {"preset", preset.id},
        {"inputs", std::move(inputList)},
        {"files", std::move(files)},
    });
    std::fprintf(out, "%s\n", text.c_str());
    return kCliOk;
}

}  // namespace

bool IsCookUzEngineCommand(std::string_view verb) { return verb == kVerb; }

int RunCookUzEngineCommand(const std::vector<std::string>& args, std::FILE* out, std::FILE* err) {
    const std::optional<Arguments> parsed = Parse(args);
    if (!parsed) {
        std::fprintf(err, "%s", kCookUsage);
        return kCliUsage;
    }
    try {
        return Cook(*parsed, out);
    } catch (const Refusal& e) {
        std::fprintf(err, "UzPainter.exe cook-uzengine: refused: %s; nothing was written\n", e.what());
    } catch (const core::ManifestError& e) {
        std::fprintf(err, "UzPainter.exe cook-uzengine: %s\n", e.what());
    } catch (const core::ValueError& e) {
        std::fprintf(err, "UzPainter.exe cook-uzengine: ValueError: %s\n", e.what());
    } catch (const std::exception& e) {
        std::fprintf(err, "UzPainter.exe cook-uzengine: %s\n", e.what());
    }
    return kCliFailed;
}

}  // namespace uzp::exporter
