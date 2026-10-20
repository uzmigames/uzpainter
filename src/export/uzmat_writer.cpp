#include "export/uzmat_writer.h"

#include <array>
#include <filesystem>
#include <stdexcept>
#include <string_view>

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include "uzp_core/manifest/json.h"

namespace uzp::exporter {
namespace {
namespace json = core::json;

void Require(bool condition, const char* message) {
    if (!condition) throw std::invalid_argument(message);
}

void Utf8(std::string_view text) {
    try {
        (void)json::Parse(json::WriteCanonical(text));
    } catch (const json::ParseError& error) {
        throw std::invalid_argument(error.what());
    }
}

bool DeviceName(std::string_view component) {
    std::string base(component.substr(0, component.find('.')));
    while (!base.empty() && base.back() == ' ') base.pop_back();
    for (auto& c : base) if (c >= 'a' && c <= 'z') c = static_cast<char>(c - 'a' + 'A');
    if (base == "CON" || base == "PRN" || base == "AUX" || base == "NUL" ||
        base == "CONIN$" || base == "CONOUT$") return true;
    if (!base.starts_with("COM") && !base.starts_with("LPT")) return false;
    const auto digit = std::string_view(base).substr(3);
    return (digit.size() == 1 && digit[0] >= '1' && digit[0] <= '9') ||
           digit == "\xc2\xb9" || digit == "\xc2\xb2" || digit == "\xc2\xb3";
}

void Reference(std::string_view path, std::string_view suffix, bool basename = false) {
    Require(!path.empty() && path.size() <= 32767 && path.ends_with(suffix) && path.size() > suffix.size(),
            "material reference has a missing or invalid extension");
    Utf8(path);
    Require(path.find_first_of("\\:%?#<>\"|*") == std::string_view::npos,
            "material reference must be a local delivery path");
    for (const unsigned char c : path) {
        Require(c >= 32 && c != 127, "material reference contains a control character");
    }
    Require(!basename || path.find('/') == std::string_view::npos,
            ".uzmat must be at the mounted delivery root");
    std::size_t start = 0;
    while (start <= path.size()) {
        const auto slash = path.find('/', start);
        const auto part = path.substr(start, slash == std::string_view::npos ? slash : slash - start);
        Require(!part.empty() && part != "." && part != ".." && part.back() != '.' &&
                    part.back() != ' ', "material reference contains an unsafe path component");
        Require(!DeviceName(part), "material reference contains a reserved Windows device name");
        if (slash == std::string_view::npos) break;
        start = slash + 1;
    }
}

bool SamePath(const std::string& left, const std::string& right) {
    const auto wide = [](const std::string& text) {
        return std::filesystem::path(std::u8string(
            reinterpret_cast<const char8_t*>(text.data()), text.size())).native();
    };
    const auto a = wide(left), b = wide(right);
    return CompareStringOrdinal(a.data(), static_cast<int>(a.size()),
                                b.data(), static_cast<int>(b.size()), TRUE) == CSTR_EQUAL;
}

std::string_view Blend(UzMaterialBlend value) {
    switch (value) {
        case UzMaterialBlend::Opaque: return "Opaque";
        case UzMaterialBlend::Masked: return "Masked";
        case UzMaterialBlend::Translucent: return "Translucent";
        case UzMaterialBlend::Additive: return "Additive";
    }
    throw std::invalid_argument("unsupported material blend mode");
}

json::Object Sample(int id, const char* name, const std::string& path) {
    return {{"id", id}, {"type", "TextureSample"}, {"name", name},
            {"stringParams", json::Object{{"texturePath", path}}}};
}

std::string Serialize(const json::Object& object) {
    return json::WriteCanonical(object) + '\n';
}
}  // namespace

UzMaterial WriteUzMaterial(const UzMaterialSpec& spec) {
    Require(!spec.name.empty() && spec.name.find('\0') == std::string::npos,
            "material name must be nonempty and contain no NUL");
    Utf8(spec.name);
    Reference(spec.materialPath, ".uzmat", true);
    for (const auto* path : {&spec.albedo, &spec.normal, &spec.orm, &spec.emissive}) {
        Reference(*path, ".uztexture");
    }
    if (!spec.height.empty()) Reference(spec.height, ".uztexture");
    for (const auto* colour : {&spec.albedo, &spec.emissive}) {
        for (const auto* linear : {&spec.normal, &spec.orm, &spec.height}) {
            Require(linear->empty() || !SamePath(*colour, *linear),
                    "material cannot use one texture path for both sRGB and linear data");
        }
    }
    const auto blend = Blend(spec.blend);

    // TextureSample outputs are RGBA/R/G/B/A. ORM shares one expression across its pins.
    constexpr std::array<std::array<int, 2>, 7> sources{{
        {2, 0}, {4, 3}, {4, 2}, {3, 0}, {5, 0}, {2, 4}, {4, 1},
    }};
    json::Array inputs;
    for (std::size_t pin = 0; pin < sources.size(); ++pin) {
        inputs.emplace_back(json::Object{{"pin", static_cast<int>(pin)},
                                        {"srcExpr", sources[pin][0]}, {"srcPin", sources[pin][1]}});
    }
    json::Array expressions{
        json::Object{{"id", 1}, {"type", "PBROutput"}, {"inputs", std::move(inputs)}},
        Sample(2, "Albedo", spec.albedo), Sample(3, "Normal", spec.normal),
        Sample(4, "ORM", spec.orm), Sample(5, "Emissive", spec.emissive),
    };
    json::Object graph{
        {"version", 1}, {"name", spec.name}, {"domain", "Surface"},
        {"shadingModel", "DefaultLit"}, {"blendMode", blend}, {"twoSided", spec.twoSided},
        {"params", json::Object{
            {"baseColorTint", json::Array{1, 1, 1}}, {"roughnessMultiplier", 1},
            {"metallicMultiplier", 1}, {"normalStrength", 1}, {"emissiveMultiplier", 1},
            {"specularMultiplier", 1}, {"aoMultiplier", 1}}},
        {"expressions", std::move(expressions)},
    };
    // The scene loader overwrites graph ORM and multiplies graph emissive by these values.
    json::Object scene{
        {"material_graph", spec.materialPath}, {"albedo", spec.albedo}, {"normal", spec.normal},
        {"orm", spec.orm}, {"emissive", spec.emissive}, {"shadingModel", "DefaultLit"},
        {"blendMode", blend}, {"baseColorR", 1}, {"baseColorG", 1}, {"baseColorB", 1},
        {"roughnessMultiplier", 1}, {"metallicMultiplier", 1}, {"normalIntensity", 1},
        {"aoIntensity", 1}, {"specular", 0.5}, {"emissiveColorR", 1}, {"emissiveColorG", 1},
        {"emissiveColorB", 1}, {"emissiveIntensity", 1},
    };
    UzMaterial result{spec.materialPath, Serialize(graph), Serialize(scene), {}};
    if (!spec.height.empty()) {
        result.gaps.push_back({"height", spec.height,
                              "no verified height binding in the pinned UzEngine material format"});
    }
    if (spec.blend != UzMaterialBlend::Opaque) {
        result.gaps.push_back({"opacity", spec.albedo,
                              "SM5 does not consume albedo alpha as opacity"});
    }
    return result;
}

}  // namespace uzp::exporter
