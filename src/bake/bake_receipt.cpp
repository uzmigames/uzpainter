#include "bake/bake_receipt.h"

#include <bit>

#include "bake/embree_baker.h"
#include "bake/height_baker.h"
#include "bake/position_baker.h"
#include "bake/thickness_baker.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"

namespace uzp::bake {

using core::json::Array;
using core::json::Object;
using core::json::Value;

namespace {

void Put(std::string& out, std::uint64_t value, int bytes) {
    for (int i = 0; i < bytes; ++i) out.push_back(static_cast<char>((value >> (8 * i)) & 0xFFu));
}
void PutFloat(std::string& out, float value) { Put(out, std::bit_cast<std::uint32_t>(value), 4); }

Value Optional(const std::optional<std::string>& text) { return text ? Value(*text) : Value(nullptr); }

Value Number(float value) { return Value(static_cast<double>(value)); }

}  // namespace

std::string MeshContentHash(const BakeMesh& mesh) {
    std::string bytes;
    Put(bytes, mesh.positions.size(), 8);
    Put(bytes, mesh.normals.size(), 8);
    Put(bytes, mesh.uvs.size(), 8);
    Put(bytes, mesh.indices.size(), 8);
    Put(bytes, mesh.corner_tangents.size(), 8);
    for (const Float3& p : mesh.positions) {
        PutFloat(bytes, p.x);
        PutFloat(bytes, p.y);
        PutFloat(bytes, p.z);
    }
    for (const Float3& n : mesh.normals) {
        PutFloat(bytes, n.x);
        PutFloat(bytes, n.y);
        PutFloat(bytes, n.z);
    }
    for (const Float2& uv : mesh.uvs) {
        PutFloat(bytes, uv.x);
        PutFloat(bytes, uv.y);
    }
    for (std::uint32_t index : mesh.indices) Put(bytes, index, 4);
    for (const auto& t : mesh.corner_tangents) {
        for (float c : t) PutFloat(bytes, c);
    }
    return core::Sha256Hex(bytes);
}

core::MeshHashes LowMeshHashes(const BakeRequest& request) {
    std::string positions, uvs, normals, triangulation;
    for (const BakeMesh* part : request.low) {
        Put(positions, part->positions.size(), 8);
        for (const Float3& p : part->positions) {
            PutFloat(positions, p.x);
            PutFloat(positions, p.y);
            PutFloat(positions, p.z);
        }
        Put(uvs, part->uvs.size(), 8);
        for (const Float2& uv : part->uvs) {
            PutFloat(uvs, uv.x);
            PutFloat(uvs, uv.y);
        }
        Put(normals, part->indices.size(), 8);
        for (std::uint32_t index : part->indices) {
            const Float3 n = part->normals.at(index);
            PutFloat(normals, n.x);
            PutFloat(normals, n.y);
            PutFloat(normals, n.z);
        }
        Put(triangulation, part->indices.size(), 8);
        for (std::uint32_t index : part->indices) Put(triangulation, index, 4);
    }
    core::MeshHashes hashes;
    hashes.positions = core::Sha256Hex(positions);
    hashes.uvs = core::Sha256Hex(uvs);
    hashes.corner_normals = core::Sha256Hex(normals);
    hashes.triangulation = core::Sha256Hex(triangulation);
    return hashes;
}

Object SettingsJson(const BakeRequest& request) {
    const auto e = [](auto value) { return Value(static_cast<std::int64_t>(value)); };
    Array usages;
    for (MeshMapUsage usage : request.usages) usages.emplace_back(UsageName(usage));
    Value bounds(nullptr);
    if (request.project_bounds) {
        const BoundingBox& b = *request.project_bounds;
        bounds = Array{Number(b.lower.x), Number(b.lower.y), Number(b.lower.z),
                       Number(b.upper.x), Number(b.upper.y), Number(b.upper.z)};
    }
    const DetailSettings& d = request.detail;
    const AoSettings& ao = request.ao;
    const ThicknessSettings& th = request.thickness;
    return Object{
        {"usages", usages},
        {"output_size_log2", Array{e(request.output_size_log2[0]), e(request.output_size_log2[1])}},
        {"scale_to_internal", Value(request.scale_to_internal)},
        {"project_bounds", bounds},
        {"box_size_metric", request.box_size_metric ? e(*request.box_size_metric) : Value(nullptr)},
        {"common", Object{{"dilation_width", e(request.common.dilation_width)},
                          {"apply_diffusion", request.common.apply_diffusion}}},
        {"detail", Object{{"low_as_high", d.low_as_high},
                          {"cage_mode", e(d.cage_mode)},
                          {"max_height", Number(d.max_height)},
                          {"max_depth", Number(d.max_depth)},
                          {"relative_to_bounding_box", d.relative_to_bounding_box},
                          {"ignore_backface", d.ignore_backface},
                          {"filter_method", e(d.filter_method)},
                          {"low_suffix", d.low_suffix},
                          {"high_suffix", d.high_suffix},
                          {"ignore_backface_suffix", d.ignore_backface_suffix},
                          {"subsampling", e(d.subsampling)}}},
        {"ao", Object{{"secondary_rays", e(ao.secondary_rays)},
                      {"min_distance", Number(ao.min_distance)},
                      {"max_distance", Number(ao.max_distance)},
                      {"relative_to_bounding_box", ao.relative_to_bounding_box},
                      {"distribution", e(ao.distribution)}}},
        {"normal", Object{{"tangent_space", e(request.normal.tangent_space)}, {"format", e(request.normal.format)}}},
        {"position", Object{{"mode", e(request.position.mode)},
                            {"axis", e(request.position.axis)},
                            {"normalization", e(request.position.normalization)},
                            {"scale", e(request.position.scale)}}},
        {"id", Object{{"source", e(request.id.source)},
                      {"generator", request.id.generator ? e(*request.id.generator) : Value(nullptr)}}},
        {"height", Object{{"normalization", request.height.normalization ? e(*request.height.normalization) : Value(nullptr)},
                          {"divisor", Number(request.height.divisor)}}},
        {"thickness", Object{{"secondary_rays", e(th.secondary_rays)},
                             {"min_distance", Number(th.min_distance)},
                             {"max_distance", Number(th.max_distance)},
                             {"relative_to_bounding_box", th.relative_to_bounding_box},
                             {"distribution", e(th.distribution)},
                             {"normalization", th.normalization ? e(*th.normalization) : Value(nullptr)}}},
        {"neutral_fallback", request.neutral_fallback},
    };
}

std::string SettingsHash(const BakeRequest& request) {
    return core::Sha256Hex(core::json::WriteCanonical(Value(SettingsJson(request))));
}

BakeReceipt BuildReceipt(const BakeRequest& request, const BakeResult& result, const Capabilities& caps,
                         const ReceiptContext& context) {
    if (context.build_hash.empty()) throw core::ValueError("a bake receipt needs the build's hash");
    BakeReceipt receipt;
    receipt.job_id = context.job_id;
    receipt.texture_set = request.texture_set;
    receipt.input_revision = request.input_revision;
    receipt.status = JobStatus::Success;
    receipt.settings_hash = SettingsHash(request);
    receipt.parity_status = caps.parity_status;
    receipt.header = context.header;
    receipt.tools.backend_version = caps.embree_version;
    receipt.tools.isa_or_gpu = caps.isa;
    receipt.tools.build_hash = context.build_hash;

    for (const BakeMesh* low : request.low) receipt.inputs.low_mesh_hashes.push_back(MeshContentHash(*low));
    const std::vector<const BakeMesh*>& high = request.detail.low_as_high ? request.low : request.high;
    const std::vector<std::vector<std::size_t>> matched = MatchedHighMeshes(request);
    for (std::size_t p = 0; p < request.low.size(); ++p) {
        ReceiptPart part;
        part.name = request.low[p]->name;
        for (std::size_t h : matched[p]) part.high_meshes.push_back(MeshContentHash(*high[h]));
        if (request.detail.cage_mode == CageMode::CustomFile) {
            part.cage.sha256 = MeshContentHash(*request.cage.at(p));
        } else {
            part.cage.frontal = request.detail.max_height;
            part.cage.rear = request.detail.max_depth;
            part.cage.relative = request.detail.relative_to_bounding_box;
        }
        receipt.inputs.parts.push_back(std::move(part));
    }
    if (!request.hidden_mask.empty()) {
        receipt.inputs.hidden_mask = core::Sha256Hex(std::string_view(
            reinterpret_cast<const char*>(request.hidden_mask.data()), request.hidden_mask.size()));
    }

    for (MeshMapUsage usage : request.usages) {
        ReceiptUsage entry;
        entry.account = AccountUsage(request, result, usage);
        if (const std::optional<MapImage> map = CompatibleMap(result, usage)) {
            entry.map_sha256 = core::Sha256Hex(EncodeMapFile(*map));
            entry.raw_sha256 = core::Sha256Hex(EncodeMapFile(*RawMap(result, usage)));
        }
        if (usage == MeshMapUsage::Position) entry.effective_normalization = PositionNormalizationJson(result.position_normalization);
        if (usage == MeshMapUsage::Height) entry.effective_normalization = HeightNormalizationJson(result.height_normalization);
        if (usage == MeshMapUsage::Thickness) entry.effective_normalization = ThicknessRecordJson(result.thickness);
        receipt.usages.push_back(std::move(entry));
    }
    return receipt;
}

Object ReceiptJson(const BakeReceipt& receipt) {
    Object out = core::HeaderToJson(receipt.header);
    out["job_id"] = Value(receipt.job_id);
    out["texture_set"] = receipt.texture_set;
    out["input_revision"] = receipt.input_revision;
    out["status"] = JobStatusName(receipt.status);
    out["settings_hash"] = receipt.settings_hash;
    out["parity_status"] = receipt.parity_status;
    const ReceiptTools& t = receipt.tools;
    out["tools"] = Object{{"baker_version", t.baker_version},
                          {"backend", std::string(core::ToString(t.backend))},
                          {"backend_version", t.backend_version},
                          {"isa_or_gpu", t.isa_or_gpu},
                          {"build_hash", t.build_hash}};
    Array lows(receipt.inputs.low_mesh_hashes.begin(), receipt.inputs.low_mesh_hashes.end());
    Array parts;
    for (const ReceiptPart& part : receipt.inputs.parts) {
        const Value cage = part.cage.sha256 ? Value(*part.cage.sha256)
                                            : Value(Object{{"frontal", Number(part.cage.frontal)},
                                                           {"rear", Number(part.cage.rear)},
                                                           {"relative", part.cage.relative}});
        parts.emplace_back(Object{{"name", part.name},
                                  {"high_meshes", Array(part.high_meshes.begin(), part.high_meshes.end())},
                                  {"cage", cage}});
    }
    out["inputs"] = Object{{"low_mesh_hashes", lows}, {"parts", parts}, {"hidden_mask", Optional(receipt.inputs.hidden_mask)}};
    Array usages;
    for (const ReceiptUsage& u : receipt.usages) {
        const UsageAccount& a = u.account;
        Array usage_parts;
        for (const PartCounts& part : a.parts) {
            usage_parts.emplace_back(Object{
                {"name", part.name},
                {"hits", Value(part.hits)},
                {"misses", Value(part.misses)},
                {"z_negative_texels", part.z_negative_texels ? Value(*part.z_negative_texels) : Value(nullptr)}});
        }
        const UsedSurfaceCounts& s = a.used_surface;
        usages.emplace_back(Object{
            {"usage", UsageName(a.usage)},
            {"map", Optional(u.map_sha256)},
            {"raw", Optional(u.raw_sha256)},
            {"coverage", Object{{"centre_texels", Value(a.coverage.centre_texels)},
                                {"conservative_texels", Value(a.coverage.conservative_texels)}}},
            {"used_surface", Object{{"hit_straight", Value(s.hit_straight)},
                                    {"hit_cage", Value(s.hit_cage)},
                                    {"miss", Value(s.miss)},
                                    {"hidden", Value(s.hidden)},
                                    {"ring_extended", Value(s.ring_extended)},
                                    {"ring_no_hit_neighbour", Value(s.ring_no_hit_neighbour)},
                                    {"repaired", Value(s.repaired)}}},
            {"fallback_texels", Value(a.fallback_texels)},
            {"padding_texels", Value(a.padding_texels)},
            {"changed_used_texels", Value(a.changed_used_texels)},
            {"surface_modified", a.surface_modified},
            {"fidelity_evidence", FidelityEvidenceName(a.fidelity_evidence)},
            {"parts", usage_parts},
            {"effective_normalization", u.effective_normalization},
        });
    }
    out["usages"] = usages;
    return out;
}

std::string ReceiptBytes(const BakeReceipt& receipt) { return core::json::WriteCanonical(Value(ReceiptJson(receipt))); }

}  // namespace uzp::bake
