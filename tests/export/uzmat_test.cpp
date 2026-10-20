// CPU-only JSON driver of UzPainter's material writer; no engine dependency.
#include "../no_error_dialogs.h"

#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <variant>

#include "export/uzmat_writer.h"
#include "uzp_core/manifest/json.h"

namespace json = uzp::core::json;

int main(int argc, char** argv) {
    try {
        if (argc != 2) throw std::invalid_argument("expected one JSON request path");
        std::ifstream stream(argv[1], std::ios::binary);
        if (!stream) throw std::invalid_argument("cannot read request");
        const std::string text{std::istreambuf_iterator<char>(stream), {}};
        const auto request = json::Parse(text);
        const auto& object = std::get<json::Object>(request.data);
        const auto string = [&](const char* key) {
            return std::get<std::string>(object.at(key).data);
        };
        uzp::exporter::UzMaterialSpec spec;
        spec.name = string("name");
        spec.materialPath = string("materialPath");
        spec.albedo = string("albedo");
        spec.normal = string("normal");
        spec.orm = string("orm");
        spec.emissive = string("emissive");
        if (object.contains("height")) spec.height = string("height");
        if (object.contains("blend")) {
            spec.blend = static_cast<uzp::exporter::UzMaterialBlend>(
                std::get<std::int64_t>(object.at("blend").data));
        }
        if (object.contains("twoSided")) spec.twoSided = std::get<bool>(object.at("twoSided").data);
        if (object.contains("invalidUtf8Name")) spec.name = std::string(1, static_cast<char>(0xff));
        if (object.contains("invalidUtf8Height")) {
            spec.height = "maps/" + std::string(1, static_cast<char>(0xff)) + ".uztexture";
        }
        const auto result = uzp::exporter::WriteUzMaterial(spec);
        json::Array gaps;
        for (const auto& gap : result.gaps) {
            gaps.emplace_back(json::Object{{"binding", gap.binding}, {"path", gap.path},
                                          {"reason", gap.reason}});
        }
        const json::Object output{
            {"materialPath", result.materialPath}, {"bytes", result.bytes},
            {"inlineMaterial", result.inlineMaterial}, {"gaps", std::move(gaps)},
        };
        std::cout << json::WriteCanonical(output) << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::cout << json::WriteCanonical(json::Object{{"error", error.what()}}) << '\n';
        return 1;
    }
}
