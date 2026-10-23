#include "bake/job_inputs.h"

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <memory>
#include <variant>

#include "bake/bake_publication.h"
#include "bake/baking_parameters.h"
#include "bake/baking_project.h"
#include "bake/mesh_inputs.h"
#include "mesh/mesh_import.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"

namespace uzp::bake {

using core::NotYetSupported;
using core::ValueError;

namespace {

/// The meshes a request points into.
struct OwnedMeshes {
    std::vector<BakeMesh> low;
    std::vector<BakeMesh> high;
    std::vector<BakeMesh> cage;
};

std::filesystem::path PathOfUtf8(const std::string& text) {
    return std::filesystem::path(std::u8string(text.begin(), text.end()));
}

std::string ReadFile(const std::filesystem::path& path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) throw ValueError("cannot read the mesh file " + path.generic_string());
    return std::string((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
}

/// A mesh file a bake parameter names (`file:///<absolute path>`), read with its glTF buffers.
mesh::TexturingMesh ReadNamedMesh(const std::string& url, const std::string& key, std::set<std::string>& read) {
    constexpr std::string_view kScheme = "file:///";
    if (url.compare(0, kScheme.size(), kScheme) != 0) {
        throw ValueError(key + ": '" + url + "' is not a file:/// URL of a mesh file");
    }
    const std::filesystem::path path = PathOfUtf8(url.substr(kScheme.size()));
    const std::string bytes = ReadFile(path);
    read.insert(core::Sha256Hex(bytes));
    const std::filesystem::path directory = path.parent_path();
    const mesh::ExternalFileReader beside = [&](const std::string&, const std::filesystem::path& relative) {
        std::string file = ReadFile(directory / relative);
        read.insert(core::Sha256Hex(file));
        return file;
    };
    const std::u8string name = path.filename().u8string();
    return ReadBakeMeshFile(bytes, std::string(name.begin(), name.end()), beside);
}

std::vector<std::string> Split(const std::string& joined) {
    std::vector<std::string> out;
    std::size_t start = 0;
    while (start <= joined.size()) {
        const std::size_t bar = joined.find('|', start);
        const std::string part = joined.substr(start, bar == std::string::npos ? std::string::npos : bar - start);
        if (!part.empty()) out.push_back(part);
        if (bar == std::string::npos) break;
        start = bar + 1;
    }
    return out;
}

}  // namespace

MeshMapUsage UsageNamed(const std::string& name) {
    for (int u = 0; u <= static_cast<int>(MeshMapUsage::Opacity); ++u) {
        const auto usage = static_cast<MeshMapUsage>(u);
        if (name == UsageName(usage)) return usage;
    }
    throw ValueError("no mesh map usage " + name);
}

PreparedBakes PrepareBakes(const core::Project& project, std::int64_t revision, const mesh::ResourceReader& read,
                           const std::vector<std::string>& texture_sets, const std::vector<MeshMapUsage>& usages) {
    std::vector<std::string> names = texture_sets;
    if (names.empty()) {
        for (const core::TextureSet& set : project.texture_sets) names.push_back(set.name);
    }
    if (names.empty()) throw ValueError("the project has no texture set to bake");
    for (std::size_t i = 0; i < names.size(); ++i) {
        if (std::find(names.begin(), names.begin() + static_cast<std::ptrdiff_t>(i), names[i]) !=
            names.begin() + static_cast<std::ptrdiff_t>(i)) {
            throw ValueError("texture set '" + names[i] + "' is named twice");
        }
    }
    const BakingSession session = LoadBakingSession(project);
    // Every texture set and usage is checked before the mesh is read.
    std::vector<std::vector<MeshMapUsage>> chosen;
    for (const std::string& name : names) {
        const auto set = std::find_if(project.texture_sets.begin(), project.texture_sets.end(),
                                      [&](const core::TextureSet& s) { return s.name == name; });
        if (set == project.texture_sets.end()) throw ValueError("the project has no texture set '" + name + "'");
        std::vector<MeshMapUsage> enabled = usages;
        if (enabled.empty()) {
            for (const std::string& baker : DefaultTextureSetState().enabled_bakers) enabled.push_back(UsageNamed(baker));
        }
        for (MeshMapUsage usage : enabled) (void)PublishedFormat(usage);
        chosen.push_back(std::move(enabled));
    }

    PreparedBakes prepared;
    if (!project.mesh) throw ValueError("the project has no mesh to bake");
    const mesh::ImportResult low = mesh::RederiveMesh(project, read);
    prepared.input_resources.insert(project.mesh->resource);
    for (const mesh::ExternalFile& file : low.external_files) {
        prepared.input_resources.insert(core::Sha256Hex(file.bytes));
    }
    const BoundingBox bounds = SceneBounds(low.mesh);
    for (std::size_t s = 0; s < names.size(); ++s) {
        const core::TextureSet& set = *std::find_if(project.texture_sets.begin(), project.texture_sets.end(),
                                                    [&](const core::TextureSet& t) { return t.name == names[s]; });
        const auto material = std::find_if(low.mesh.materials.begin(), low.mesh.materials.end(),
                                           [&](const mesh::Material& m) { return m.name == set.material_id; });
        if (material == low.mesh.materials.end()) {
            throw ValueError("the mesh has no material '" + set.material_id + "' for texture set '" + set.name + "'");
        }
        const BakingParameters parameters = session.parameters(set.name);
        const std::map<std::string, Property> common = parameters.common();
        auto owned = std::make_shared<OwnedMeshes>();
        owned->low = LowParts(low.mesh, material->index);
        BakeRequest base;
        base.input_revision = std::to_string(revision);
        base.usages = chosen[s];
        base.scale_to_internal = low.mesh.units.scale_to_internal;
        base.project_bounds = bounds;
        base.normal.tangent_space = project.settings.tangent_space;
        base.normal.format = project.settings.normal_map_format;
        if (!std::get<bool>(common.at("LowAsHigh").value())) {
            for (const std::string& url : Split(std::get<std::string>(common.at("HipolyMesh").value()))) {
                std::vector<BakeMesh> meshes = HighMeshes(ReadNamedMesh(url, "HipolyMesh", prepared.input_resources));
                for (BakeMesh& m : meshes) owned->high.push_back(std::move(m));
            }
            if (owned->high.empty()) {
                throw ValueError("texture set '" + set.name + "' has no high poly mesh (HipolyMesh) and LowAsHigh is off");
            }
        }
        const std::string cage_mode = std::get<EnumLabel>(common.at("CageMode").value()).label;
        if (cage_mode == "Automatic (experimental)") {
            throw NotYetSupported("CageMode 'Automatic (experimental)': its cage is not established against Painter "
                                  "(06-baking.md section 3; phase3.5_embree-bakers item 3.1, decision 323)");
        }
        if (cage_mode == "Custom file") {
            const std::string url = std::get<std::string>(common.at("CageMesh").value());
            if (url.empty()) throw ValueError("texture set '" + set.name + "' has CageMode Custom file and no CageMesh");
            owned->cage = CageParts(ReadNamedMesh(url, "CageMesh", prepared.input_resources), low.mesh, material->index);
        }
        BakeRequest request = RequestFromParameters(parameters, std::move(base)).request;
        for (const BakeMesh& m : owned->low) request.low.push_back(&m);
        for (const BakeMesh& m : owned->high) request.high.push_back(&m);
        for (const BakeMesh& m : owned->cage) request.cage.push_back(&m);
        prepared.sets.push_back({std::move(request), std::move(owned)});
    }
    return prepared;
}

}  // namespace uzp::bake
