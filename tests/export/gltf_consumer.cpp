#include "../no_error_dialogs.h"

#include <array>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <memory>
#include <span>
#include <stdexcept>
#include <string>
#include <vector>

#include "fastgltf/core.hpp"
#include "fastgltf/tools.hpp"
#include "spng.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/manifest/sha256.h"

namespace {
namespace fs = std::filesystem;
namespace json = uzp::core::json;
constexpr std::size_t kResourceLimit = 256 * 1024 * 1024;

void Require(bool condition, const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}

fs::path Utf8Path(std::string_view text) {
    return fs::path(std::u8string(reinterpret_cast<const char8_t*>(text.data()), text.size()));
}

std::string Read(const fs::path& path, std::size_t limit) {
    const auto size = fs::file_size(path);
    Require(size <= limit, "resource exceeds fixture size limit");
    std::ifstream stream(path, std::ios::binary);
    Require(stream.good(), "cannot open resource");
    std::string bytes(static_cast<std::size_t>(size), '\0');
    stream.read(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    Require(stream.good(), "cannot read resource");
    return bytes;
}

const json::Object& Object(const json::Value& value) {
    Require(value.IsObject(), "expected JSON object");
    return std::get<json::Object>(value.data);
}

std::vector<std::string> Preflight(const json::Object& document, std::string_view key,
                                 const fs::path& root) {
    const auto it = document.find(key);
    Require(it != document.end() && it->second.IsArray(), "missing external resources");
    std::vector<std::string> uris;
    for (const auto& item : std::get<json::Array>(it->second.data)) {
        const auto& object = Object(item);
        const auto uri = object.find("uri");
        Require(uri != object.end() && uri->second.IsString(), "external resource URI required");
        const auto& name = std::get<std::string>(uri->second.data);
        Require(!name.empty() && name.find_first_of("\\:%?#") == std::string::npos &&
                    name.find('\0') == std::string::npos,
                "unsafe resource URI");
        const auto relative = Utf8Path(name);
        Require(!relative.is_absolute() && !relative.has_root_path(), "absolute resource URI");
        for (const auto& part : relative) Require(part != ".." && part != ".", "traversal resource URI");
        const auto resolved = fs::canonical(root / relative);
        auto resource_part = resolved.begin();
        for (const auto& root_part : root) {
            Require(resource_part != resolved.end() && *resource_part == root_part,
                    "resource escapes asset directory");
            ++resource_part;
        }
        Require(fs::is_regular_file(resolved) && fs::file_size(resolved) <= kResourceLimit,
                "invalid or oversized resource");
        uris.push_back(name);
    }
    Require(!uris.empty(), "empty resource list");
    return uris;
}

std::span<const std::byte> Bytes(const fastgltf::DataSource& source) {
    if (const auto* data = std::get_if<fastgltf::sources::Array>(&source)) return {data->bytes.data(), data->bytes.size()};
    if (const auto* data = std::get_if<fastgltf::sources::Vector>(&source)) return {data->bytes.data(), data->bytes.size()};
    throw std::runtime_error("resource was not loaded into memory");
}

const fastgltf::Accessor& Accessor(const fastgltf::Asset& asset, std::size_t index,
                                 fastgltf::AccessorType type, std::size_t element_size) {
    const auto& accessor = asset.accessors.at(index);
    Require(accessor.type == type && !accessor.normalized && !accessor.sparse && accessor.bufferViewIndex &&
                accessor.count > 0, "unsupported accessor layout");
    const auto& view = asset.bufferViews.at(*accessor.bufferViewIndex);
    const auto bytes = Bytes(asset.buffers.at(view.bufferIndex).data);
    Require(view.byteOffset <= bytes.size() && view.byteLength <= bytes.size() - view.byteOffset,
            "buffer view out of bounds");
    const std::size_t stride = view.byteStride ? *view.byteStride : element_size;
    Require(stride >= element_size && accessor.byteOffset <= view.byteLength,
            "invalid accessor offset or stride");
    const auto available = view.byteLength - accessor.byteOffset;
    Require(available >= element_size && accessor.count - 1 <= (available - element_size) / stride,
            "accessor out of bounds");
    return accessor;
}

json::Object Mesh(const fastgltf::Asset& asset) {
    Require(asset.meshes.size() == 1 && asset.materials.size() == 1 && asset.nodes.size() == 1 &&
                asset.scenes.size() == 1 && asset.skins.empty() && asset.animations.empty(),
            "fixture requires one mesh, material, node and scene");
    Require(asset.scenes[0].nodeIndices.size() == 1 && asset.scenes[0].nodeIndices[0] == 0 &&
                asset.nodes[0].meshIndex && *asset.nodes[0].meshIndex == 0 && asset.nodes[0].children.empty(),
            "scene does not bind fixture mesh");
    Require(asset.meshes[0].primitives.size() == 1, "fixture requires one primitive");
    const auto& primitive = asset.meshes[0].primitives[0];
    Require(primitive.type == fastgltf::PrimitiveType::Triangles && primitive.indicesAccessor &&
                primitive.materialIndex && *primitive.materialIndex == 0 && primitive.targets.empty(),
            "fixture requires indexed triangles with material zero");
    const auto attribute = [&](std::string_view name, fastgltf::AccessorType type, std::size_t size)
        -> const fastgltf::Accessor& {
        const auto it = primitive.findAttribute(name);
        Require(it != primitive.attributes.end(), "missing mesh attribute: " + std::string(name));
        const auto& result = Accessor(asset, it->accessorIndex, type, size);
        Require(result.componentType == fastgltf::ComponentType::Float, "float attributes required");
        return result;
    };
    const auto& positions = attribute("POSITION", fastgltf::AccessorType::Vec3, 12);
    const auto& normals = attribute("NORMAL", fastgltf::AccessorType::Vec3, 12);
    const auto& uvs = attribute("TEXCOORD_0", fastgltf::AccessorType::Vec2, 8);
    Require(positions.count == normals.count && positions.count == uvs.count, "attribute counts differ");
    std::array<double, 3> minimum{INFINITY, INFINITY, INFINITY};
    std::array<double, 3> maximum{-INFINITY, -INFINITY, -INFINITY};
    fastgltf::iterateAccessor<fastgltf::math::fvec3>(asset, positions, [&](const auto& value) {
        for (std::size_t axis = 0; axis < 3; ++axis) {
            Require(std::isfinite(value[axis]), "nonfinite position");
            minimum[axis] = std::min(minimum[axis], static_cast<double>(value[axis]));
            maximum[axis] = std::max(maximum[axis], static_cast<double>(value[axis]));
        }
    });
    fastgltf::iterateAccessor<fastgltf::math::fvec3>(asset, normals, [](const auto& value) {
        for (std::size_t axis = 0; axis < 3; ++axis) Require(std::isfinite(value[axis]), "nonfinite normal");
    });
    fastgltf::iterateAccessor<fastgltf::math::fvec2>(asset, uvs, [](const auto& value) {
        for (std::size_t axis = 0; axis < 2; ++axis) Require(std::isfinite(value[axis]), "nonfinite UV");
    });
    const auto component = asset.accessors.at(*primitive.indicesAccessor).componentType;
    const std::size_t size = component == fastgltf::ComponentType::UnsignedByte ? 1 :
                             component == fastgltf::ComponentType::UnsignedShort ? 2 :
                             component == fastgltf::ComponentType::UnsignedInt ? 4 : 0;
    Require(size != 0, "unsigned indices required");
    const auto& indices = Accessor(asset, *primitive.indicesAccessor, fastgltf::AccessorType::Scalar, size);
    Require(indices.count % 3 == 0, "incomplete triangle");
    fastgltf::iterateAccessor<std::uint32_t>(asset, indices, [&](std::uint32_t index) {
        Require(index < positions.count, "vertex index out of bounds");
    });
    return {{"vertices", static_cast<std::uint64_t>(positions.count)},
            {"triangles", static_cast<std::uint64_t>(indices.count / 3)},
            {"normals", static_cast<std::uint64_t>(normals.count)},
            {"texcoords", static_cast<std::uint64_t>(uvs.count)},
            {"boundsMin", json::Array{minimum[0], minimum[1], minimum[2]}},
            {"boundsMax", json::Array{maximum[0], maximum[1], maximum[2]}}};
}

void PngCheck(int result) {
    Require(result == 0, std::string("PNG: ") + spng_strerror(result));
}

json::Object Binding(const fastgltf::Asset& asset, const fastgltf::TextureInfo& info,
                     const std::vector<std::string>& image_uris) {
    Require(info.texCoordIndex == 0 && !info.transform, "fixture requires TEXCOORD_0 without transform");
    const auto& texture = asset.textures.at(info.textureIndex);
    Require(texture.imageIndex.has_value(), "texture image missing");
    const auto image_index = *texture.imageIndex;
    const auto bytes = Bytes(asset.images.at(image_index).data);
    std::unique_ptr<spng_ctx, decltype(&spng_ctx_free)> context(spng_ctx_new(0), &spng_ctx_free);
    Require(context != nullptr, "cannot allocate PNG decoder");
    PngCheck(spng_set_image_limits(context.get(), 16384, 16384));
    PngCheck(spng_set_png_buffer(context.get(), bytes.data(), bytes.size()));
    spng_ihdr header{};
    PngCheck(spng_get_ihdr(context.get(), &header));
    const int channels = header.color_type == 0 ? 1 : header.color_type == 2 ? 3 :
                         header.color_type == 4 ? 2 : header.color_type == 6 ? 4 : 0;
    Require(channels != 0 && (header.bit_depth == 8 || header.bit_depth == 16),
            "fixture requires gray, gray-alpha, RGB or RGBA PNG at 8 or 16 bits");
    std::size_t decoded_size = 0;
    PngCheck(spng_decoded_image_size(context.get(), SPNG_FMT_RAW, &decoded_size));
    Require(decoded_size <= 512 * 1024 * 1024, "PNG exceeds decoded fixture limit");
    std::vector<std::byte> decoded(decoded_size);
    PngCheck(spng_decode_image(context.get(), decoded.data(), decoded.size(), SPNG_FMT_RAW, 0));
    PngCheck(spng_decode_chunks(context.get()));
    return {{"image", image_uris.at(image_index)},
            {"sha256", uzp::core::Sha256Hex({reinterpret_cast<const char*>(bytes.data()), bytes.size()})},
            {"width", static_cast<std::uint64_t>(header.width)},
            {"height", static_cast<std::uint64_t>(header.height)},
            {"channels", channels}, {"bit_depth", static_cast<int>(header.bit_depth)},
            {"texcoord", static_cast<std::uint64_t>(info.texCoordIndex)}};
}

json::Value Consume(const fs::path& path) {
    const auto root = fs::canonical(path).parent_path();
    const auto text = Read(path, 16 * 1024 * 1024);
    const auto document = json::Parse(text);
    const auto& object = Object(document);
    for (const auto key : {"extensionsUsed", "extensionsRequired"}) {
        const auto it = object.find(key);
        Require(it == object.end() || (it->second.IsArray() && std::get<json::Array>(it->second.data).empty()),
                "extensions unsupported by fixture");
    }
    // Check every URI before the parser can resolve even the first external resource.
    Preflight(object, "buffers", root);
    const auto image_uris = Preflight(object, "images", root);
    auto data = fastgltf::GltfDataBuffer::FromBytes(reinterpret_cast<const std::byte*>(text.data()), text.size());
    Require(data.error() == fastgltf::Error::None, "cannot initialize glTF input");
    fastgltf::Parser parser;
    auto loaded = parser.loadGltf(data.get(), root, fastgltf::Options::LoadExternalBuffers |
                                                  fastgltf::Options::LoadExternalImages);
    Require(loaded.error() == fastgltf::Error::None, std::string(fastgltf::getErrorMessage(loaded.error())));
    const auto& asset = loaded.get();
    const auto validation = fastgltf::validate(asset);
    Require(validation == fastgltf::Error::None, std::string(fastgltf::getErrorMessage(validation)));
    auto mesh = Mesh(asset);
    const auto& material = asset.materials[0];
    const auto& pbr = material.pbrData;
    Require(pbr.baseColorTexture && pbr.metallicRoughnessTexture && material.normalTexture &&
                material.occlusionTexture && material.emissiveTexture, "five material bindings required");
    json::Object bindings{{"baseColor", Binding(asset, *pbr.baseColorTexture, image_uris)},
                          {"metallicRoughness", Binding(asset, *pbr.metallicRoughnessTexture, image_uris)},
                          {"normal", Binding(asset, *material.normalTexture, image_uris)},
                          {"occlusion", Binding(asset, *material.occlusionTexture, image_uris)},
                          {"emissive", Binding(asset, *material.emissiveTexture, image_uris)}};
    const auto& base = pbr.baseColorFactor;
    const auto& emission = material.emissiveFactor;
    const char* alpha = material.alphaMode == fastgltf::AlphaMode::Blend ? "BLEND" :
                        material.alphaMode == fastgltf::AlphaMode::Mask ? "MASK" : "OPAQUE";
    return json::Object{
        {"consumer", json::Object{{"loader", "fastgltf"}, {"version", "0.9.1"},
                                  {"validator", "fastgltf::validate"}}},
        {"mesh", std::move(mesh)}, {"bindings", std::move(bindings)},
        {"material", json::Object{{"baseColorFactor", json::Array{base[0], base[1], base[2], base[3]}},
                                  {"metallicFactor", pbr.metallicFactor}, {"roughnessFactor", pbr.roughnessFactor},
                                  {"emissiveFactor", json::Array{emission[0], emission[1], emission[2]}},
                                  {"alphaMode", alpha}, {"normalScale", material.normalTexture->scale},
                                  {"occlusionStrength", material.occlusionTexture->strength}}}};
}
}  // namespace

int main(int argc, char** argv) {
    try {
        Require(argc == 2, "usage: uzp-gltf-consumer <asset.gltf>");
        std::cout << json::WriteCanonical(Consume(Utf8Path(argv[1]))) << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::cout << json::WriteCanonical(json::Object{{"error", error.what()}}) << '\n';
        return 1;
    }
}
