#include "bake/bake_accounting.h"

#include <algorithm>
#include <bit>
#include <cmath>
#include <fstream>
#include <stdexcept>
#include <system_error>

#include "export/png_writer.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"

namespace uzp::bake {

using core::NotYetSupported;
using core::ValueError;

namespace {

bool HasUsage(const BakeRequest& request, MeshMapUsage usage) {
    return std::find(request.usages.begin(), request.usages.end(), usage) != request.usages.end();
}

bool IsHitClass(std::uint8_t cls) {
    return cls == static_cast<std::uint8_t>(TexelClass::StraightHit) ||
           cls == static_cast<std::uint8_t>(TexelClass::CageHit);
}

bool IsMissClass(std::uint8_t cls) {
    return cls == static_cast<std::uint8_t>(TexelClass::CentreMiss) ||
           cls == static_cast<std::uint8_t>(TexelClass::BackFaceHit);
}

void PutLe32(std::string& out, std::uint32_t value) {
    for (int i = 0; i < 4; ++i) out.push_back(static_cast<char>((value >> (8 * i)) & 0xFFu));
}

MapImage U16Image(const BakeResult& r, std::uint32_t channels, const std::vector<std::uint16_t>& samples) {
    MapImage image{r.width, r.height, channels, {}, samples, {}};
    return image;
}

MapImage F32Image(const BakeResult& r, std::uint32_t channels, const std::vector<float>& samples) {
    MapImage image{r.width, r.height, channels, {}, {}, samples};
    return image;
}

MapImage Mask(const BakeResult& r, std::vector<std::uint8_t> samples) {
    MapImage image{r.width, r.height, 1, std::move(samples), {}, {}};
    return image;
}

std::optional<MapImage> MapOf(const BakeResult& r, MeshMapUsage usage, bool raw) {
    const std::size_t texels = static_cast<std::size_t>(r.width) * r.height;
    const auto need = [&](std::size_t size) {
        if (size == 0 || size % texels != 0) {
            throw ValueError(std::string("the result holds no ") + UsageName(usage) + " map");
        }
    };
    switch (usage) {
        case MeshMapUsage::AO:
            need(r.ao_raw.size());
            return U16Image(r, 1, raw ? r.ao_raw : r.ao);
        case MeshMapUsage::Normal:
            need(r.normal_raw.size());
            return U16Image(r, 3, raw ? r.normal_raw : r.normal);
        case MeshMapUsage::WorldSpaceNormal:
            need(r.world_normal.size());
            return F32Image(r, 3, r.world_normal);
        case MeshMapUsage::Position:
            need(r.position.size());
            return F32Image(r, r.position_normalization.channels, r.position);
        case MeshMapUsage::ID:
            need(r.id_labels.size());
            return U16Image(r, 1, r.id_labels);
        case MeshMapUsage::Opacity:
            need(r.opacity.size());
            return F32Image(r, 1, r.opacity);
        case MeshMapUsage::Height:
            need(r.height_map.size());
            return F32Image(r, 1, r.height_map);
        case MeshMapUsage::Thickness:
            need(r.thickness_ray_class.size());
            return std::nullopt;
        case MeshMapUsage::Curvature:
        case MeshMapUsage::BentNormals: break;
    }
    throw ValueError(std::string("the result holds no ") + UsageName(usage) + " map");
}

/// The compatible map differs from RAW at texel `i`.
bool Changed(const BakeResult& r, MeshMapUsage usage, std::size_t i) {
    if (usage == MeshMapUsage::AO) return r.ao[i] != r.ao_raw[i];
    if (usage == MeshMapUsage::Normal) {
        for (std::size_t c = 0; c < 3; ++c) {
            if (r.normal[3 * i + c] != r.normal_raw[3 * i + c]) return true;
        }
    }
    return false;  // the other maps have no dilation and no fallback: the map is RAW
}

}  // namespace

std::vector<std::uint8_t> ConservativeCoverage(const std::vector<const BakeMesh*>& low, std::uint32_t width,
                                               std::uint32_t height) {
    std::vector<std::uint8_t> out(static_cast<std::size_t>(width) * height, 0);
    const double w = width, h = height;
    for (const BakeMesh* part : low) {
        const std::size_t triangles = part->indices.size() / 3;
        for (std::size_t tri = 0; tri < triangles; ++tri) {
            // Texel units: x right, y down from the top row (row 0 at v = 1).
            double px[3], py[3];
            for (int k = 0; k < 3; ++k) {
                const Float2 uv = part->uvs[part->indices[3 * tri + k]];
                px[k] = static_cast<double>(uv.x) * w;
                py[k] = (1.0 - static_cast<double>(uv.y)) * h;
            }
            const double area = (px[1] - px[0]) * (py[2] - py[0]) - (py[1] - py[0]) * (px[2] - px[0]);
            if (area == 0.0) continue;  // the baker never samples a degenerate UV triangle
            const double min_x = std::min({px[0], px[1], px[2]}), max_x = std::max({px[0], px[1], px[2]});
            const double min_y = std::min({py[0], py[1], py[2]}), max_y = std::max({py[0], py[1], py[2]});
            if (max_x <= 0.0 || min_x >= w || max_y <= 0.0 || min_y >= h) continue;
            // The box axes: texel x overlaps (min_x, max_x) when x < max_x and x + 1 > min_x.
            const auto x0 = static_cast<std::int64_t>(std::max(0.0, std::floor(min_x)));
            const auto x1 = static_cast<std::int64_t>(std::min(w, std::ceil(max_x))) - 1;
            const auto y0 = static_cast<std::int64_t>(std::max(0.0, std::floor(min_y)));
            const auto y1 = static_cast<std::int64_t>(std::min(h, std::ceil(max_y))) - 1;
            // The edge axes: the texel's projection interval must overlap the triangle's openly.
            double nx[3], ny[3], t_min[3], t_max[3];
            for (int e = 0; e < 3; ++e) {
                const int f = (e + 1) % 3;
                nx[e] = py[f] - py[e];
                ny[e] = -(px[f] - px[e]);
                t_min[e] = t_max[e] = px[0] * nx[e] + py[0] * ny[e];
                for (int k = 1; k < 3; ++k) {
                    const double t = px[k] * nx[e] + py[k] * ny[e];
                    t_min[e] = std::min(t_min[e], t);
                    t_max[e] = std::max(t_max[e], t);
                }
            }
            for (std::int64_t y = y0; y <= y1; ++y) {
                for (std::int64_t x = x0; x <= x1; ++x) {
                    bool overlaps = true;
                    for (int e = 0; e < 3 && overlaps; ++e) {
                        const double centre = (static_cast<double>(x) + 0.5) * nx[e] + (static_cast<double>(y) + 0.5) * ny[e];
                        const double radius = 0.5 * (std::fabs(nx[e]) + std::fabs(ny[e]));
                        overlaps = centre + radius > t_min[e] && centre - radius < t_max[e];
                    }
                    if (overlaps) out[static_cast<std::size_t>(y) * width + static_cast<std::size_t>(x)] = 1;
                }
            }
        }
    }
    return out;
}

void ValidateFallback(const BakeRequest& request) {
    if (!request.neutral_fallback) return;
    for (MeshMapUsage usage : request.usages) {
        if (usage != MeshMapUsage::Normal) {
            throw NotYetSupported(std::string("the neutral fallback of ") + UsageName(usage) +
                                  ": no neutral value is established for it; only Normal's flat tangent normal is "
                                  "(phase3.3_baker-evidence-publication, decision 347)");
        }
    }
}

std::array<std::uint16_t, 3> NeutralNormalCodes(core::NormalMapFormat format) {
    // floor(e * 65535 + 0.5) of e = 0.5 (x and y) and 1 (z); DirectX complements green.
    const std::uint16_t half = 32768;
    return {half, format == core::NormalMapFormat::DirectX ? static_cast<std::uint16_t>(65535u - half) : half, 65535};
}

std::uint64_t ApplyNeutralFallback(BakeResult& result) {
    const std::array<std::uint16_t, 3> neutral = NeutralNormalCodes(result.normal_format);
    std::uint64_t count = 0;
    for (std::size_t i = 0; i < result.used_surface.size(); ++i) {
        if (!result.used_surface[i] || IsHitClass(result.texel_class[i])) continue;
        for (std::size_t c = 0; c < 3; ++c) result.normal[3 * i + c] = neutral[c];
        ++count;
    }
    return count;
}

const char* FidelityEvidenceName(FidelityEvidence evidence) {
    switch (evidence) {
        case FidelityEvidence::UsedSurfaceAsBaked: return "used_surface_as_baked";
        case FidelityEvidence::ContainsFallback: return "contains_fallback";
        case FidelityEvidence::DiagnosticOnly: return "diagnostic_only";
    }
    return "unknown";
}

UsageAccount AccountUsage(const BakeRequest& request, const BakeResult& result, MeshMapUsage usage) {
    if (!HasUsage(request, usage)) throw ValueError(std::string("the request did not bake ") + UsageName(usage));
    (void)MapOf(result, usage, true);  // the usage's map is in the result
    const std::size_t texels = static_cast<std::size_t>(result.width) * result.height;
    if (result.used_surface.size() != texels || result.texel_part.size() != texels ||
        result.texel_class.size() != texels) {
        throw std::logic_error("the result carries no used-surface evidence");
    }
    UsageAccount a;
    a.usage = usage;
    for (const BakeMesh* part : request.low) a.parts.push_back({part->name, 0, 0, std::nullopt});
    const bool normal = usage == MeshMapUsage::Normal;
    if (normal) {
        for (PartCounts& part : a.parts) part.z_negative_texels = 0;
    }
    const bool fallback = normal && request.neutral_fallback;
    for (std::size_t i = 0; i < texels; ++i) {
        const std::uint8_t cls = result.texel_class[i];
        const bool sampled = cls != static_cast<std::uint8_t>(TexelClass::Uncovered);
        const bool used = result.used_surface[i] != 0;
        if (sampled) {
            if (!used) throw std::logic_error("a sampled texel lies outside the conservative used surface");
            ++a.coverage.centre_texels;
            PartCounts& part = a.parts.at(result.texel_part[i]);
            if (IsHitClass(cls)) {
                ++part.hits;
                if (normal && result.normal_raw[3 * i + 2] < 32768) ++*part.z_negative_texels;
            } else if (IsMissClass(cls)) {
                ++part.misses;
            }
        }
        if (!used) {
            ++a.padding_texels;
            continue;
        }
        ++a.coverage.conservative_texels;
        switch (static_cast<TexelClass>(cls)) {
            case TexelClass::StraightHit: ++a.used_surface.hit_straight; break;
            case TexelClass::CageHit: ++a.used_surface.hit_cage; break;
            case TexelClass::CentreMiss:
            case TexelClass::BackFaceHit: ++a.used_surface.miss; break;
            case TexelClass::Hidden: ++a.used_surface.hidden; break;
            case TexelClass::Uncovered:
                if (usage == MeshMapUsage::AO && result.extension[i]) {
                    ++a.used_surface.ring_extended;
                } else {
                    ++a.used_surface.ring_no_hit_neighbour;
                }
                break;
        }
        if (fallback && !IsHitClass(cls)) ++a.fallback_texels;
        if (Changed(result, usage, i)) ++a.changed_used_texels;
    }
    if (a.used_surface.Total() != a.coverage.conservative_texels) {
        throw std::logic_error("the used-surface classes do not sum to the conservative coverage");
    }
    if (normal && a.fallback_texels != result.fallback_texels) {
        throw std::logic_error("the fallback count disagrees with the texels the baker set");
    }
    a.surface_modified = a.fallback_texels > 0 || a.used_surface.repaired > 0;
    if (result.diagnostic_unqualified || a.used_surface.repaired > 0) {
        a.fidelity_evidence = FidelityEvidence::DiagnosticOnly;
    } else if (a.fallback_texels > 0) {
        a.fidelity_evidence = FidelityEvidence::ContainsFallback;
    }
    return a;
}

std::optional<MapImage> CompatibleMap(const BakeResult& result, MeshMapUsage usage) {
    return MapOf(result, usage, false);
}

std::optional<MapImage> RawMap(const BakeResult& result, MeshMapUsage usage) { return MapOf(result, usage, true); }

std::string EncodeMapFile(const MapImage& image) {
    const std::size_t samples = static_cast<std::size_t>(image.width) * image.height * image.channels;
    if (!image.f32.empty()) {
        if (image.f32.size() != samples) throw ValueError("the float map has the wrong sample count");
        std::string out("UZPF32\0\0", 8);
        PutLe32(out, image.width);
        PutLe32(out, image.height);
        PutLe32(out, image.channels);
        out.reserve(out.size() + 4 * samples);
        for (float value : image.f32) PutLe32(out, std::bit_cast<std::uint32_t>(value));
        return out;
    }
    exporter::PngImage png;
    png.width = image.width;
    png.height = image.height;
    png.channels = image.channels;
    if (!image.u16.empty()) {
        png.bitDepth = 16;
        png.samples = image.u16;
    } else {
        png.bitDepth = 8;
        png.samples.assign(image.u8.begin(), image.u8.end());
    }
    return exporter::EncodePng(png);
}

const char* MapFileExtension(const MapImage& image) { return image.f32.empty() ? ".png" : ".f32"; }

std::string EvidenceDirectory(const BakeRequest& request) {
    return "cache/bake/" + core::Sha256Hex(request.texture_set + "\n" + request.input_revision).substr(0, 16);
}

std::vector<EvidenceFile> EvidenceFiles(const BakeRequest& request, const BakeResult& result) {
    const std::size_t texels = static_cast<std::size_t>(result.width) * result.height;
    std::vector<std::uint8_t> hit(texels, 0), coverage(texels, 0), miss(texels, 0);
    for (std::size_t i = 0; i < texels; ++i) {
        const std::uint8_t cls = result.texel_class[i];
        hit[i] = cls == static_cast<std::uint8_t>(TexelClass::StraightHit) ? 1
                 : cls == static_cast<std::uint8_t>(TexelClass::CageHit)   ? 2
                                                                            : 0;
        coverage[i] = static_cast<std::uint8_t>((cls != static_cast<std::uint8_t>(TexelClass::Uncovered) ? 1 : 0) |
                                                (result.used_surface[i] ? 2 : 0));
        miss[i] = IsMissClass(cls) ? 1 : 0;
    }
    std::vector<EvidenceFile> files;
    const auto add = [&](const std::string& path, std::string bytes) {
        std::string sha = core::Sha256Hex(bytes);
        files.push_back({path, std::move(bytes), std::move(sha)});
    };
    const std::string directory = EvidenceDirectory(request);
    for (MeshMapUsage usage : request.usages) {
        const std::string base = directory + "/" + UsageName(usage) + "/";
        if (const std::optional<MapImage> map = CompatibleMap(result, usage)) {
            add(base + "map" + MapFileExtension(*map), EncodeMapFile(*map));
            const std::optional<MapImage> raw = RawMap(result, usage);
            add(base + "raw" + MapFileExtension(*raw), EncodeMapFile(*raw));
        }
        add(base + "hit.png", EncodeMapFile(Mask(result, hit)));
        add(base + "coverage.png", EncodeMapFile(Mask(result, coverage)));
        add(base + "miss.png", EncodeMapFile(Mask(result, miss)));
        const bool extended = usage == MeshMapUsage::AO;
        add(base + "extension.png",
            EncodeMapFile(Mask(result, extended ? result.extension : std::vector<std::uint8_t>(texels, 0))));
    }
    return files;
}

void WriteEvidence(const std::filesystem::path& root, const std::vector<EvidenceFile>& files) {
    for (const EvidenceFile& file : files) {
        const std::filesystem::path path = root / std::filesystem::path(file.path);
        std::error_code error;
        std::filesystem::create_directories(path.parent_path(), error);
        if (error) throw ValueError("cannot create " + path.parent_path().string() + ": " + error.message());
        std::filesystem::path temporary = path;
        temporary += ".tmp";
        {
            std::ofstream out(temporary, std::ios::binary | std::ios::trunc);
            out.write(file.bytes.data(), static_cast<std::streamsize>(file.bytes.size()));
            if (!out) throw ValueError("cannot write " + temporary.string());
        }
        std::filesystem::rename(temporary, path, error);
        if (error) throw ValueError("cannot move " + temporary.string() + " over " + path.string() + ": " + error.message());
    }
}

}  // namespace uzp::bake
