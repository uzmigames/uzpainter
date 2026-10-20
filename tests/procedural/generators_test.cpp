// Native tests of the procedural mesh-map generator families (src/procedural/generators.h,
// rulebook task phase3.2_proc-generator-families, decision 329). Built by
// `zig build proc-generator-tests` and driven by tests/procedural/test_proc_generator_families.py.
//
// Usage: uzp-proc-generator-tests <case> <work-dir> <shipped-library>
//   signals     the Curvature, Position, World Space Normals and Ambient Occlusion generators
//               against their published formulas, tiles, the joint rule and the seam's refusal
//               of the uncertified families (CPU; item 2.2)
//   wear        Dirt and Metal Edge Wear against their published formulas (base mask, disk
//               dilation, noise breakup, boxstep), the seed, the spread and tiles (CPU; item 2.3)
//   masks       Mask Builder (Legacy) and Mask Editor against their formulas: every source, the
//               noise mask, growth and shrinking, the weighted sum, tiles (CPU; item 2.4)
//   bind        mesh maps bound by usage from a texture set; a missing or invalid mesh map fails
//               evaluation loudly and nothing is substituted (CPU; test 3.2)
//   domain      a parameter, a seed, a mesh class, a mesh-map input and a resolution just outside
//               the declared domain are refused before mutation, nothing clamped or substituted
//               (CPU; test 3.4)
//   kernels     every family's kernels compiled to DXIL and SPIR-V (CPU, needs dxcompiler.dll)
//   gpu         every family on DX12 equal to its CPU reference bit for bit, whole and by tile,
//               and identical bytes across two runs (GPU; items 2.2-2.4, test 3.3)
//
// The shipped library is the repository's `assets/procedural/`. The mesh maps are authored
// (seeded uniform codes). No case compares against a Painter output: the families are not
// certified.
//
// Output: `PASS <check>` / `FAIL <check>: <detail>` / `INFO` lines.
// Exit code 0 when every check passed, 1 when one failed, 2 on a usage error, 77 when the case
// needs a DX12 hardware adapter and there is none.

#include "procedural/asset_library.h"
#include "procedural/generators.h"
#include "procedural/hlsl_backend.h"
#include "procedural/primitives.h"
#include "procedural/seam.h"

#include "evaluator/resources.h"
#include "render/engine_thread.h"
#include "render/kernel_cache.h"

#include "uzp_core/document/document.h"
#include "uzp_core/document/nodes.h"
#include "uzp_core/transaction/transaction.h"
#include "uzp_core/types/project.h"

#include <bit>
#include <cmath>
#include <chrono>
#include <cstdio>
#include <filesystem>
#include <functional>
#include <future>
#include <map>
#include <memory>
#include <optional>
#include <random>
#include <string>
#include <string_view>
#include <vector>
#include "../no_error_dialogs.h"

namespace {

using namespace uzp::procedural;
namespace fs = std::filesystem;
namespace render = uzp::render;
namespace core = uzp::core;
namespace evaluator = uzp::evaluator;
using core::MeshMapUsage;

constexpr int kExitSkip = 77;
constexpr uint32_t kSize = 1024;
int g_failures = 0;

void Check(bool ok, std::string_view name, const std::string& detail = {}) {
    if (ok) {
        std::printf("PASS %.*s\n", static_cast<int>(name.size()), name.data());
    } else {
        std::printf("FAIL %.*s: %s\n", static_cast<int>(name.size()), name.data(), detail.c_str());
        ++g_failures;
    }
    std::fflush(stdout);
}

int Finish() { return g_failures == 0 ? 0 : 1; }

uint32_t Bits(float value) { return std::bit_cast<uint32_t>(value); }

std::string Hex(uint32_t value) {
    char buf[16];
    std::snprintf(buf, sizeof(buf), "%08X", value);
    return buf;
}

/// The first texel where two rasters differ bit for bit, or empty.
std::string FirstDifference(const Raster& a, const Raster& b) {
    if (a.width != b.width || a.height != b.height || a.channels != b.channels ||
        a.texels.size() != b.texels.size()) {
        return "shapes differ: " + std::to_string(a.width) + "x" + std::to_string(a.height) + "x" +
               std::to_string(a.channels) + " against " + std::to_string(b.width) + "x" +
               std::to_string(b.height) + "x" + std::to_string(b.channels);
    }
    size_t count = 0;
    std::string first;
    for (size_t i = 0; i < a.texels.size(); ++i) {
        if (Bits(a.texels[i]) == Bits(b.texels[i])) continue;
        if (count++ == 0) {
            const size_t texel = i / a.channels;
            first = "texel (" + std::to_string(texel % a.width) + ", " + std::to_string(texel / a.width) +
                    ") channel " + std::to_string(i % a.channels) + ": " + Hex(Bits(a.texels[i])) +
                    " against " + Hex(Bits(b.texels[i]));
        }
    }
    return count == 0 ? std::string() : std::to_string(count) + " values differ, first at " + first;
}

/// The texels of `whole` inside `tile`.
Raster Crop(const Raster& whole, const TileRect& tile) {
    Raster out{tile.width, tile.height, whole.channels, {}};
    for (uint32_t y = 0; y < tile.height; ++y) {
        for (uint32_t x = 0; x < tile.width; ++x) {
            for (uint32_t c = 0; c < whole.channels; ++c) {
                out.texels.push_back(whole.texels[(size_t{tile.y + y} * whole.width + tile.x + x) * whole.channels + c]);
            }
        }
    }
    return out;
}

core::AssetUrl Url(std::string_view text) { return core::ParseAssetUrl(text); }

std::string Name(MeshMapUsage usage) { return std::string(core::ToString(usage)); }

// ── Authored mesh maps ───────────────────────────────────────────────────────

/// A decoded 16-bit image of seeded uniform codes.
std::shared_ptr<evaluator::DecodedImage> Codes(uint32_t size, uint32_t channels, uint32_t seed) {
    std::mt19937 random(seed);
    auto image = std::make_shared<evaluator::DecodedImage>();
    image->width = image->height = size;
    image->channels = channels;
    image->encoding = render::TexelEncoding::Unorm16;
    image->values.resize(size_t{size} * size * channels);
    for (uint32_t& v : image->values) v = random() % 65536;
    return image;
}

/// A texture set binding all five generator mesh maps (16-bit, `Raw`), and the resources that
/// hold their images.
struct MeshMaps {
    core::TextureSet set;
    evaluator::MapResourceProvider resources;
};

std::unique_ptr<MeshMaps> AuthoredMaps(uint32_t size, uint32_t seed) {
    auto maps = std::make_unique<MeshMaps>();
    maps->set.id = 1;
    maps->set.name = "authored";
    maps->set.resolution = core::Resolution{static_cast<int>(size), static_cast<int>(size), {}};
    uint32_t n = 0;
    for (const MeshMapUsage usage : {MeshMapUsage::AO, MeshMapUsage::Curvature, MeshMapUsage::Position,
                                     MeshMapUsage::Thickness, MeshMapUsage::WorldSpaceNormal}) {
        const bool vector = usage == MeshMapUsage::Position || usage == MeshMapUsage::WorldSpaceNormal;
        core::MeshMapBinding binding;
        binding.resource = "authored-" + Name(usage) + "-" + std::to_string(seed);
        binding.format = vector ? core::ChannelFormat::RGB16 : core::ChannelFormat::L16;
        binding.color_space = "Raw";
        maps->resources.Add(binding.resource, Codes(size, vector ? 3 : 1, seed * 16 + ++n));
        maps->set.mesh_maps[usage] = binding;
    }
    return maps;
}

/// A request of `record` inside its declared domain: the record's defaults, the `sphere` class,
/// one float32 `linear` channel at `bound`'s resolution, its mesh maps by usage.
ProceduralRequest GeneratorRequestOf(const AssetRecord& record, const BoundMeshMaps& bound, uint32_t size,
                                     uint64_t seed = 0) {
    ProceduralRequest request;
    request.asset = record.asset;
    request.params = record.defaults;
    request.meshClass = "sphere";
    request.output = RasterSpec{size, ChannelFormat::F32, "linear", 1};
    request.seed = seed;
    for (const MeshMapUsage usage : GeneratorUsages(record.asset)) {
        request.inputs[Name(usage)] = bound.inputs.at(Name(usage));
    }
    return request;
}

struct Fixture {
    AssetLibrary library;
    std::map<std::string, const AssetRecord*> records;  ///< By asset URL.
};

std::optional<Fixture> LoadFixture(const fs::path& shipped) {
    auto loaded = AssetLibrary::Load(shipped);
    Check(loaded.has_value(), "the shipped library loads", loaded ? "" : loaded.error());
    if (!loaded) return std::nullopt;
    Fixture fixture{std::move(*loaded), {}};
    bool all = true;
    for (const std::string_view asset : GeneratorAssets()) {
        const AssetRecord* record = fixture.library.Find(Url(asset));
        all = all && record != nullptr;
        fixture.records[std::string(asset)] = record;
    }
    Check(all, "the shipped library holds every generator record");
    if (!all) return std::nullopt;
    return fixture;
}

/// The bound mesh maps of an authored texture set (fails the check when binding fails).
std::optional<BoundMeshMaps> Bind(const MeshMaps& maps) {
    const std::vector<MeshMapUsage> all = {MeshMapUsage::AO, MeshMapUsage::Curvature, MeshMapUsage::Position,
                                           MeshMapUsage::Thickness, MeshMapUsage::WorldSpaceNormal};
    render::Result<BoundMeshMaps> bound = BindMeshMaps(maps.set, all, maps.resources);
    Check(bound.has_value(), "the authored mesh maps bind by usage", bound ? "" : bound.error().Describe());
    if (!bound) return std::nullopt;
    return std::move(*bound);
}

/// Every texel of `out` against `expected(x, y)`, bit for bit.
std::string Compare(const render::Result<Raster>& out, uint32_t size,
                    const std::function<float(uint32_t, uint32_t)>& expected) {
    if (!out) return out.error().Describe();
    if (out->width != size || out->height != size || out->channels != 1) return "not a " + std::to_string(size) + " mask";
    for (uint32_t y = 0; y < size; ++y) {
        for (uint32_t x = 0; x < size; ++x) {
            const float want = expected(x, y);
            const float got = out->texels[size_t{y} * size + x];
            if (Bits(want) != Bits(got)) {
                return "(" + std::to_string(x) + ", " + std::to_string(y) + "): " + Hex(Bits(got)) + " against " +
                       Hex(Bits(want));
            }
        }
    }
    return {};
}

// The published shaping, written out with plain float32 operations (the test compiles without
// contraction; the authored maps give no subnormal intermediate).
float Clamp01(float x) { return x > 0.0f ? (x < 1.0f ? x : 1.0f) : 0.0f; }
float Boxstep(float v, double low, double high) {
    return Clamp01((v - static_cast<float>(low)) * static_cast<float>(1.0 / (high - low)));
}
float Smooth(float t) { return (t * t) * (3.0f - 2.0f * t); }

// ── signals (item 2.2, CPU) ──────────────────────────────────────────────────

int RunSignals(const fs::path& shipped) {
    std::optional<Fixture> fixture = LoadFixture(shipped);
    if (!fixture) return Finish();
    HlslBackend hlsl(nullptr);
    const std::expected<void, std::string> registered = RegisterGeneratorFamilies(hlsl, fixture->library);
    Check(registered.has_value(), "every generator registers from its library record",
          registered ? "" : registered.error());
    if (!registered) return Finish();
    bool unavailable = true;
    for (const auto& [asset, record] : fixture->records) {
        unavailable = unavailable && hlsl.Status(record->asset).kind == ParityStatus::Kind::Unavailable;
    }
    Check(unavailable, "every generator carries its record's status: not certified");

    const std::unique_ptr<MeshMaps> maps = AuthoredMaps(kSize, 3);
    const std::optional<BoundMeshMaps> bound = Bind(*maps);
    if (!bound) return Finish();
    const auto at = [&](MeshMapUsage usage, uint32_t x, uint32_t y, uint32_t c) {
        const Raster& r = bound->images.at(Name(usage));
        return r.texels[(size_t{y} * r.width + x) * r.channels + c];
    };
    const auto evaluate = [&](std::string_view asset, const Params& changes) {
        ProceduralRequest request = GeneratorRequestOf(*fixture->records.at(std::string(asset)), *bound, kSize);
        for (const auto& [name, value] : changes) request.params[name] = value;
        return hlsl.EvaluateReference(request, bound->images);
    };

    // Curvature: Shape(2c - 1), or Shape(1 - 2c) when concave.
    {
        const auto out = evaluate(kCurvatureAsset, {});
        const std::string convex = Compare(out, kSize, [&](uint32_t x, uint32_t y) {
            return Boxstep(2.0f * at(MeshMapUsage::Curvature, x, y, 0) - 1.0f, 0, 1);
        });
        Check(convex.empty(), "Curvature at its defaults is the convex part clamp(2c - 1)", convex);
        const auto concave = evaluate(kCurvatureAsset, {{"mode", int64_t{1}}, {"low", 0.125}, {"high", 0.625},
                                                        {"smooth", int64_t{1}}, {"invert", int64_t{1}}});
        const std::string diff = Compare(concave, kSize, [&](uint32_t x, uint32_t y) {
            return 1.0f - Smooth(Boxstep(1.0f - 2.0f * at(MeshMapUsage::Curvature, x, y, 0), 0.125, 0.625));
        });
        Check(diff.empty(), "Curvature concave, boxstep [0.125, 0.625], smoothed and inverted", diff);
    }
    // Position: Shape(p[axis]) for each axis.
    for (const int64_t axis : {int64_t{0}, int64_t{1}, int64_t{2}}) {
        const auto out = evaluate(kPositionAsset, {{"axis", axis}, {"low", 0.25}, {"high", 0.75}});
        const std::string diff = Compare(out, kSize, [&](uint32_t x, uint32_t y) {
            return Boxstep(at(MeshMapUsage::Position, x, y, static_cast<uint32_t>(axis)), 0.25, 0.75);
        });
        Check(diff.empty(), "Position gradient along axis " + std::to_string(axis) + " boxstepped [0.25, 0.75]", diff);
    }
    // World Space Normals: Shape(+-(2 n[axis / 2] - 1)) for the six signed axes.
    for (int64_t axis = 0; axis < 6; ++axis) {
        const auto out = evaluate(kWorldNormalAsset, {{"axis", axis}, {"low", -0.5}, {"high", 0.75}});
        const std::string diff = Compare(out, kSize, [&](uint32_t x, uint32_t y) {
            const float n = at(MeshMapUsage::WorldSpaceNormal, x, y, static_cast<uint32_t>(axis / 2));
            return Boxstep(axis % 2 == 0 ? 2.0f * n - 1.0f : 1.0f - 2.0f * n, -0.5, 0.75);
        });
        Check(diff.empty(), "World Space Normals along signed axis " + std::to_string(axis) + " boxstepped [-0.5, 0.75]",
              diff);
    }
    // Ambient Occlusion: Shape(1 - ao).
    {
        const auto out = evaluate(kOcclusionAsset, {{"smooth", int64_t{1}}});
        const std::string diff = Compare(out, kSize, [&](uint32_t x, uint32_t y) {
            return Smooth(Boxstep(1.0f - at(MeshMapUsage::AO, x, y, 0), 0, 1));
        });
        Check(diff.empty(), "Ambient Occlusion is the smoothed occlusion 1 - ao", diff);
    }

    // A tile is the same texels as the whole texture.
    for (const std::string_view asset : {kCurvatureAsset, kPositionAsset, kWorldNormalAsset, kOcclusionAsset}) {
        ProceduralRequest request = GeneratorRequestOf(*fixture->records.at(std::string(asset)), *bound, kSize);
        const render::Result<Raster> whole = hlsl.EvaluateReference(request, bound->images);
        request.tile = TileRect{1000, 3, 24, 40};
        const render::Result<Raster> part = hlsl.EvaluateReference(request, bound->images);
        Check(whole && part && FirstDifference(*part, Crop(*whole, request.tile)).empty(),
              "a tile at the texture border equals the whole texture's texels: " + std::string(asset));
    }

    // The joint rule: every mesh map has the output's resolution; nothing is resampled.
    {
        ProceduralRequest request = GeneratorRequestOf(*fixture->records.at(std::string(kCurvatureAsset)), *bound, kSize);
        request.output.resolution = 2048;
        const std::optional<UnsupportedProcedural> refusal = hlsl.Refusal(request);
        Check(refusal && refusal->reason == kOutsideDomain && refusal->field == "inputs.Curvature.resolution" &&
                  refusal->value == "1024" && refusal->certified == "the output's resolution (2048)",
              "a mesh map at another resolution than the output is refused, not resampled",
              refusal ? refusal->Describe() : "admitted");
        Check(!hlsl.EvaluateReference(request, bound->images), "the candidate lane evaluates nothing for it");
    }

    // The seam never serves an uncertified family, and substitutes nothing.
    {
        ProceduralSeam seam(nullptr, &hlsl);
        const ProceduralRequest request =
            GeneratorRequestOf(*fixture->records.at(std::string(kOcclusionAsset)), *bound, kSize);
        const auto selected = seam.Select(request);
        Check(!selected && selected.error().reason == kNotCertified && selected.error().value == "unavailable",
              "the seam refuses the uncertified family inside its domain (family not certified)",
              selected ? "served" : selected.error().Describe());
        Check(!hlsl.CanEvaluate(request), "CanEvaluate is false for an uncertified family");
    }
    return Finish();
}

// ── wear (item 2.3, CPU) ─────────────────────────────────────────────────────

/// The disk maximum (`grow` > 0) or minimum of radius |grow| of a mask, clamped at the border.
std::vector<float> DiskMorph(const std::vector<float>& v, uint32_t size, int grow) {
    const int r = grow < 0 ? -grow : grow;
    std::vector<float> out(v.size());
    const auto clamp = [&](int64_t i) { return i < 0 ? 0 : (i >= size ? int64_t{size} - 1 : i); };
    for (int64_t y = 0; y < size; ++y) {
        for (int64_t x = 0; x < size; ++x) {
            float best = v[size_t(y) * size + size_t(x)];
            for (int dy = -r; dy <= r; ++dy) {
                for (int dx = -r; dx <= r; ++dx) {
                    if (dx * dx + dy * dy > r * r) continue;
                    const float s = v[size_t(clamp(y + dy)) * size + size_t(clamp(x + dx))];
                    if (grow >= 0 ? s > best : s < best) best = s;
                }
            }
            out[size_t(y) * size + size_t(x)] = best;
        }
    }
    return out;
}

/// fBm of Perlin 2002 noise (four octaves, lacunarity 2, gain 1/2) at the position x scale.
float NoiseAt(const Raster& position, uint32_t x, uint32_t y, float scale, uint32_t seed) {
    const float* p = &position.texels[(size_t{y} * position.width + x) * 3];
    return prim::Fbm(prim::FbmBasis::Perlin2002, prim::Vec3{p[0] * scale, p[1] * scale, p[2] * scale}, seed, 4, 2.0f,
                     0.5f);
}

int RunWear(const fs::path& shipped) {
    std::optional<Fixture> fixture = LoadFixture(shipped);
    if (!fixture) return Finish();
    HlslBackend hlsl(nullptr);
    if (!RegisterGeneratorFamilies(hlsl, fixture->library)) return Finish();
    const std::unique_ptr<MeshMaps> maps = AuthoredMaps(kSize, 11);
    const std::optional<BoundMeshMaps> bound = Bind(*maps);
    if (!bound) return Finish();
    const Raster& curvature = bound->images.at("Curvature");
    const Raster& ao = bound->images.at("AO");
    const Raster& position = bound->images.at("Position");
    const auto evaluate = [&](std::string_view asset, const Params& changes, uint64_t seed) {
        ProceduralRequest request = GeneratorRequestOf(*fixture->records.at(std::string(asset)), *bound, kSize, seed);
        for (const auto& [name, value] : changes) request.params[name] = value;
        return hlsl.EvaluateReference(request, bound->images);
    };
    const auto number = [](const Params& params, const std::string& name) {
        const ParamValue& v = params.at(name);
        return std::holds_alternative<double>(v) ? std::get<double>(v) : static_cast<double>(std::get<int64_t>(v));
    };
    // The published formula: the base mask, its disk dilation, the noise breakup, the boxstep.
    const auto expected = [&](std::string_view asset, const Params& changes, uint32_t seed) {
        Params p = fixture->records.at(std::string(asset))->defaults;
        for (const auto& [name, value] : changes) p[name] = value;
        const bool dirt = asset == kDirtAsset;
        std::vector<float> base(size_t{kSize} * kSize);
        for (size_t i = 0; i < base.size(); ++i) {
            const float c = curvature.texels[i];
            const float occlusion = 1.0f - ao.texels[i];
            base[i] = dirt ? Clamp01(static_cast<float>(number(p, "cavity_weight")) * Clamp01(1.0f - 2.0f * c) +
                                     static_cast<float>(number(p, "occlusion_weight")) * occlusion)
                           : Clamp01(Clamp01(2.0f * c - 1.0f) - static_cast<float>(number(p, "occlusion_protect")) * occlusion);
        }
        const std::vector<float> spread = DiskMorph(base, kSize, static_cast<int>(number(p, "spread")));
        const float scale = static_cast<float>(number(p, "noise_scale"));
        const float amount = static_cast<float>(number(p, "noise_amount"));
        std::vector<float> out(base.size());
        for (uint32_t y = 0; y < kSize; ++y) {
            for (uint32_t x = 0; x < kSize; ++x) {
                const size_t i = size_t{y} * kSize + x;
                out[i] = Boxstep(spread[i] + amount * NoiseAt(position, x, y, scale, seed), number(p, "low"),
                                 number(p, "high"));
            }
        }
        return out;
    };
    const auto matches = [&](const render::Result<Raster>& out, const std::vector<float>& want) {
        return Compare(out, kSize, [&](uint32_t x, uint32_t y) { return want[size_t{y} * kSize + x]; });
    };

    const Params dirtEdit = {{"cavity_weight", 0.5}, {"occlusion_weight", 0.25}, {"spread", int64_t{3}},
                             {"noise_scale", 24.0}, {"noise_amount", 0.5}, {"low", 0.125}, {"high", 0.5}};
    const Params edgeEdit = {{"occlusion_protect", 1.0}, {"spread", int64_t{2}}, {"noise_scale", 3.5},
                             {"noise_amount", 0.75}, {"low", 0.0}, {"high", 0.25}};
    for (const auto& [asset, edit] : {std::pair{kDirtAsset, dirtEdit}, std::pair{kEdgeWearAsset, edgeEdit}}) {
        const std::string name(asset);
        std::string diff = matches(evaluate(asset, {}, 0x1234u), expected(asset, {}, 0x1234u));
        Check(diff.empty(), name + " at its defaults equals base, dilation, noise breakup and boxstep", diff);
        diff = matches(evaluate(asset, edit, 77u), expected(asset, edit, 77u));
        Check(diff.empty(), name + " at an edited parameter set equals its formula", diff);
    }

    // The noise follows the seed; without noise the output does not depend on it.
    {
        const auto one = evaluate(kDirtAsset, {}, 1);
        const auto two = evaluate(kDirtAsset, {}, 2);
        Check(one && two && !FirstDifference(*one, *two).empty(), "Dirt's noise breakup changes with the seed");
        const Params quiet = {{"noise_amount", int64_t{0}}};
        const auto a = evaluate(kDirtAsset, quiet, 1);
        const auto b = evaluate(kDirtAsset, quiet, 2);
        Check(a && b && FirstDifference(*a, *b).empty(), "Dirt without noise does not depend on the seed");
    }
    // Spreading only grows the mask (the dilation is monotone).
    {
        const auto tight = evaluate(kDirtAsset, {{"noise_amount", int64_t{0}}, {"spread", int64_t{0}}}, 0);
        const auto wide = evaluate(kDirtAsset, {{"noise_amount", int64_t{0}}, {"spread", int64_t{4}}}, 0);
        bool grows = tight && wide;
        bool strictly = false;
        for (size_t i = 0; grows && i < tight->texels.size(); ++i) {
            grows = wide->texels[i] >= tight->texels[i];
            strictly = strictly || wide->texels[i] > tight->texels[i];
        }
        Check(grows && strictly, "Dirt's spread grows the mask and never shrinks it");
    }
    // Edge Wear with no protection, spread, noise or range is the Curvature generator's convex
    // part, bit for bit.
    {
        const auto edges = evaluate(kEdgeWearAsset,
                                    {{"occlusion_protect", int64_t{0}}, {"spread", int64_t{0}},
                                     {"noise_amount", int64_t{0}}, {"low", int64_t{0}}, {"high", int64_t{1}}},
                                    5);
        const auto convex = evaluate(kCurvatureAsset, {}, 5);
        Check(edges && convex && FirstDifference(*edges, *convex).empty(),
              "Edge Wear reduced to its edge detection equals the Curvature generator's convex part");
    }
    // A tile is the same texels as the whole texture.
    for (const std::string_view asset : {kDirtAsset, kEdgeWearAsset}) {
        ProceduralRequest request = GeneratorRequestOf(*fixture->records.at(std::string(asset)), *bound, kSize, 9);
        const render::Result<Raster> whole = hlsl.EvaluateReference(request, bound->images);
        request.tile = TileRect{2, 1000, 40, 24};
        const render::Result<Raster> part = hlsl.EvaluateReference(request, bound->images);
        Check(whole && part && FirstDifference(*part, Crop(*whole, request.tile)).empty(),
              "a tile at the texture border equals the whole texture's texels: " + std::string(asset));
    }
    return Finish();
}

// ── masks (item 2.4, CPU) ────────────────────────────────────────────────────

int RunMasks(const fs::path& shipped) {
    std::optional<Fixture> fixture = LoadFixture(shipped);
    if (!fixture) return Finish();
    HlslBackend hlsl(nullptr);
    if (!RegisterGeneratorFamilies(hlsl, fixture->library)) return Finish();
    const std::unique_ptr<MeshMaps> maps = AuthoredMaps(kSize, 13);
    const std::optional<BoundMeshMaps> bound = Bind(*maps);
    if (!bound) return Finish();
    const auto value = [&](const char* usage, size_t texel, uint32_t c) {
        const Raster& r = bound->images.at(usage);
        return r.texels[texel * r.channels + c];
    };
    const auto convex = [&](size_t i) { return Clamp01(2.0f * value("Curvature", i, 0) - 1.0f); };
    const auto cavity = [&](size_t i) { return Clamp01(1.0f - 2.0f * value("Curvature", i, 0)); };
    const auto occlusion = [&](size_t i) { return 1.0f - value("AO", i, 0); };
    const auto height = [&](size_t i) { return value("Position", i, 1); };
    const auto up = [&](size_t i) { return Clamp01(2.0f * value("WorldSpaceNormal", i, 1) - 1.0f); };
    const auto evaluate = [&](std::string_view asset, const Params& changes, uint64_t seed) {
        ProceduralRequest request = GeneratorRequestOf(*fixture->records.at(std::string(asset)), *bound, kSize, seed);
        for (const auto& [name, v] : changes) request.params[name] = v;
        return hlsl.EvaluateReference(request, bound->images);
    };
    const auto matches = [&](const render::Result<Raster>& out, const std::vector<float>& want) {
        return Compare(out, kSize, [&](uint32_t x, uint32_t y) { return want[size_t{y} * kSize + x]; });
    };
    const size_t texels = size_t{kSize} * kSize;

    // Mask Builder: each source boxstepped, without noise or growth.
    const std::vector<std::function<float(size_t)>> sources = {convex, cavity, occlusion, height, up};
    for (int64_t source = 0; source < 5; ++source) {
        std::vector<float> want(texels);
        for (size_t i = 0; i < texels; ++i) want[i] = Boxstep(sources[size_t(source)](i), 0.25, 0.875);
        const std::string diff =
            matches(evaluate(kMaskBuilderAsset, {{"source", source}, {"low", 0.25}, {"high", 0.875}}, 0), want);
        Check(diff.empty(), "Mask Builder source " + std::to_string(source) + " boxstepped [0.25, 0.875]", diff);
    }
    // Mask Builder: the noise mask mixed in, then grown or shrunk by a disk.
    for (const int64_t grow : {int64_t{2}, int64_t{-3}}) {
        const Params edit = {{"source", int64_t{2}}, {"noise_amount", 0.625}, {"noise_scale", 12.0},
                             {"noise_low", 0.375}, {"noise_high", 0.75}, {"grow", grow}};
        std::vector<float> mixed(texels);
        const Raster& position = bound->images.at("Position");
        for (uint32_t y = 0; y < kSize; ++y) {
            for (uint32_t x = 0; x < kSize; ++x) {
                const size_t i = size_t{y} * kSize + x;
                const float t = Boxstep(occlusion(i), 0, 1);
                const float m = Boxstep(0.5f * NoiseAt(position, x, y, 12.0f, 21u) + 0.5f, 0.375, 0.75);
                mixed[i] = t + 0.625f * (t * m - t);
            }
        }
        const std::string diff = matches(evaluate(kMaskBuilderAsset, edit, 21), DiskMorph(mixed, kSize, int(grow)));
        Check(diff.empty(), "Mask Builder with the noise mask and grow " + std::to_string(grow) + " equals its formula",
              diff);
    }
    // Mask Builder at its defaults is the Curvature generator's convex part, bit for bit.
    {
        const auto builder = evaluate(kMaskBuilderAsset, {}, 3);
        const auto curvature = evaluate(kCurvatureAsset, {}, 3);
        Check(builder && curvature && FirstDifference(*builder, *curvature).empty(),
              "Mask Builder at its defaults equals the Curvature generator at its defaults");
    }

    // Mask Editor: the weighted sum of the six terms, boxstepped, inverted.
    {
        const Params edit = {{"edges_weight", 0.5}, {"cavity_weight", -0.25}, {"occlusion_weight", 0.75},
                             {"height_weight", 1.0}, {"up_weight", -1.0}, {"thickness_weight", 0.375},
                             {"low", -0.5}, {"high", 1.5}, {"invert", int64_t{1}}};
        std::vector<float> want(texels);
        for (size_t i = 0; i < texels; ++i) {
            float sum = 0.5f * convex(i);
            sum = sum + -0.25f * cavity(i);
            sum = sum + 0.75f * occlusion(i);
            sum = sum + 1.0f * height(i);
            sum = sum + -1.0f * up(i);
            sum = sum + 0.375f * value("Thickness", i, 0);
            want[i] = 1.0f - Boxstep(sum, -0.5, 1.5);
        }
        const std::string diff = matches(evaluate(kMaskEditorAsset, edit, 0), want);
        Check(diff.empty(), "Mask Editor's weighted sum of the six terms, boxstepped [-0.5, 1.5] and inverted", diff);
        const auto editor = evaluate(kMaskEditorAsset, {}, 0);
        const auto curvature = evaluate(kCurvatureAsset, {}, 0);
        Check(editor && curvature && FirstDifference(*editor, *curvature).empty(),
              "Mask Editor at its defaults (edges only) equals the Curvature generator at its defaults");
    }
    // A tile is the same texels as the whole texture.
    for (const std::string_view asset : {kMaskBuilderAsset, kMaskEditorAsset}) {
        ProceduralRequest request = GeneratorRequestOf(*fixture->records.at(std::string(asset)), *bound, kSize, 4);
        const Params change = asset == kMaskBuilderAsset ? Params{{"grow", int64_t{-2}}, {"noise_amount", 0.5}}
                                                         : Params{{"up_weight", 0.5}};
        for (const auto& [name, v] : change) request.params[name] = v;
        const render::Result<Raster> whole = hlsl.EvaluateReference(request, bound->images);
        request.tile = TileRect{1020, 1010, 4, 14};
        const render::Result<Raster> part = hlsl.EvaluateReference(request, bound->images);
        Check(whole && part && FirstDifference(*part, Crop(*whole, request.tile)).empty(),
              "a tile at the texture border equals the whole texture's texels: " + std::string(asset));
    }
    return Finish();
}

// ── bind (test 3.2, CPU) ─────────────────────────────────────────────────────

int RunBind(const fs::path& shipped) {
    std::optional<Fixture> fixture = LoadFixture(shipped);
    if (!fixture) return Finish();
    HlslBackend hlsl(nullptr);
    if (!RegisterGeneratorFamilies(hlsl, fixture->library)) return Finish();
    const AssetRecord& curvature = *fixture->records.at(std::string(kCurvatureAsset));
    const std::vector<MeshMapUsage> usages = GeneratorUsages(curvature.asset);
    Check(usages == std::vector<MeshMapUsage>{MeshMapUsage::Curvature}, "Curvature reads the Curvature mesh map by usage");

    // The binding: the binding's hash, its spec, its codes as float32(code / 65535).
    std::unique_ptr<MeshMaps> maps = AuthoredMaps(kSize, 5);
    {
        const render::Result<BoundMeshMaps> bound = BindMeshMaps(maps->set, usages, maps->resources);
        const core::MeshMapBinding& binding = maps->set.mesh_maps.at(MeshMapUsage::Curvature);
        const std::shared_ptr<const evaluator::DecodedImage> image = maps->resources.Fetch(binding.resource);
        bool decoded = bound && bound->images.size() == 1 && bound->inputs.size() == 1;
        if (decoded) {
            const ImageInput& input = bound->inputs.at("Curvature");
            decoded = input.sha256 == binding.resource &&
                      input.spec == RasterSpec{kSize, ChannelFormat::U16, "Raw", 1};
            const Raster& raster = bound->images.at("Curvature");
            for (size_t i = 0; decoded && i < image->values.size(); ++i) {
                decoded = Bits(raster.texels[i]) == Bits(static_cast<float>(image->values[i]) / 65535.0f);
            }
        }
        Check(decoded, "the Curvature binding gives its hash, its spec (1024 u16 Raw x1) and float32(code / 65535)",
              bound ? "" : bound.error().Describe());
    }

    const auto failure = [&](const core::TextureSet& set, const evaluator::IResourceProvider& resources) {
        const render::Result<BoundMeshMaps> bound = BindMeshMaps(set, usages, resources);
        return bound ? std::string() : bound.error().Describe();
    };
    const auto names = [](const std::string& message, std::string_view text) {
        return message.find(text) != std::string::npos;
    };

    // A missing binding fails, naming the mesh map.
    {
        core::TextureSet set = maps->set;
        set.mesh_maps.erase(MeshMapUsage::Curvature);
        const std::string message = failure(set, maps->resources);
        Check(names(message, "request_failed") && names(message, "has no Curvature mesh map"),
              "a texture set without a Curvature binding fails loudly, naming it", message);
    }
    // A binding marked invalid after a mesh reload fails, naming the map and quoting its report.
    {
        core::TextureSet set = maps->set;
        core::MeshMapBinding& binding = set.mesh_maps.at(MeshMapUsage::Curvature);
        binding.invalid = true;
        binding.invalid_report = core::json::Object{{"reason", "mesh reloaded"}};
        const std::string message = failure(set, maps->resources);
        Check(names(message, "the Curvature mesh map of texture set authored is invalid") &&
                  names(message, "mesh reloaded"),
              "a Curvature binding marked invalid fails loudly, naming it with its report", message);
    }
    // An image the resources do not hold fails.
    {
        const evaluator::MapResourceProvider empty;
        const std::string message = failure(maps->set, empty);
        Check(names(message, "the Curvature mesh map of texture set authored") && names(message, "is not available"),
              "a Curvature image the resources do not hold fails loudly", message);
    }
    // An image whose size, channels or sample type are not the binding's fails.
    {
        evaluator::MapResourceProvider wrong;
        wrong.Add(maps->set.mesh_maps.at(MeshMapUsage::Curvature).resource, Codes(512, 1, 9));
        const std::string small = failure(maps->set, wrong);
        Check(names(small, "Curvature mesh map") && names(small, "is invalid: its image is 512x512x1"),
              "a Curvature image at another size than the set fails loudly, not resampled", small);
        evaluator::MapResourceProvider rgb;
        rgb.Add(maps->set.mesh_maps.at(MeshMapUsage::Curvature).resource, Codes(kSize, 3, 9));
        const std::string channels = failure(maps->set, rgb);
        Check(names(channels, "is invalid: its image is 1024x1024x3"),
              "a Curvature image with other channels than its binding fails loudly", channels);
        auto eight = Codes(kSize, 1, 9);
        eight->encoding = render::TexelEncoding::Unorm8;
        evaluator::MapResourceProvider bytes;
        bytes.Add(maps->set.mesh_maps.at(MeshMapUsage::Curvature).resource, eight);
        const std::string encoding = failure(maps->set, bytes);
        Check(names(encoding, "is invalid") && names(encoding, "u16"),
              "a Curvature image of another sample type than its binding fails loudly", encoding);
    }
    // A texture set that is not square fails.
    {
        core::TextureSet set = maps->set;
        set.resolution.height = 512;
        const std::string message = failure(set, maps->resources);
        Check(names(message, "is 1024x512"), "a non-square texture set fails loudly", message);
    }

    // Evaluation with a missing or invalid raster fails; nothing is evaluated or substituted.
    const render::Result<BoundMeshMaps> bound = BindMeshMaps(maps->set, usages, maps->resources);
    if (!bound) return Finish();
    const ProceduralRequest request = GeneratorRequestOf(curvature, *bound, kSize);
    {
        const render::Result<Raster> none = hlsl.EvaluateReference(request, {});
        Check(!none && none.error().code == render::ErrorCode::RequestFailed &&
                  names(none.error().Describe(), "image input Curvature is missing"),
              "evaluation without the Curvature raster fails (CPU lane)",
              none ? "evaluated" : none.error().Describe());
        RasterFuture future = hlsl.EvaluateCandidate(request, {});
        const render::Result<Raster> gpu = future.get();
        Check(!gpu && names(gpu.error().Describe(), "image input Curvature is missing"),
              "evaluation without the Curvature raster fails before any GPU work (candidate lane)",
              gpu ? "evaluated" : gpu.error().Describe());
        InputImages wrong = bound->images;
        wrong.at("Curvature").width = 512;
        const render::Result<Raster> invalid = hlsl.EvaluateReference(request, wrong);
        Check(!invalid && names(invalid.error().Describe(), "image input Curvature is invalid"),
              "evaluation with a Curvature raster of another size fails", invalid ? "evaluated" : invalid.error().Describe());
    }
    // The request carries no mesh map the reference binds itself.
    {
        core::ProceduralRef ref;
        ref.asset = std::string(kCurvatureAsset);
        ref.image_inputs["Curvature"] = core::ResourceBinding{"another-curvature", std::nullopt, {}};
        UseContext context;
        context.meshClass = "sphere";
        context.output = request.output;
        const auto refused = GeneratorRequest(ref, context, bound->inputs, fixture->library);
        Check(!refused && refused.error().field == "inputs.Curvature" && refused.error().value == "another-curvature",
              "a reference that binds a mesh map itself is refused: maps come from the texture set",
              refused ? "admitted" : refused.error().Describe());
        ref.image_inputs.clear();
        const auto built = GeneratorRequest(ref, context, bound->inputs, fixture->library);
        Check(built && built->inputs == bound->inputs && built->params == curvature.defaults,
              "the generator request carries the texture set's mesh maps and the record's defaults",
              built ? "" : built.error().Describe());
    }
    return Finish();
}

// ── domain (test 3.4, CPU) ───────────────────────────────────────────────────

/// A project with one fill layer whose content effect is a generator effect with no procedural
/// yet; `generator` receives its uid.
core::Project GeneratorProject(core::Id& generator) {
    core::Project project;
    project.versions.app_version = "0.0.0";
    project.versions.evaluator_profile = "painter-12.1-isolated-linear";
    core::TextureSet set;
    set.id = project.AllocateId();
    set.name = set.original_name = set.material_id = "set";
    set.uv_tiles = {core::UVTile{project.AllocateId(), 1001, {}}};
    core::Stack stack;
    stack.id = project.AllocateId();
    stack.channels[core::ChannelType::BaseColor] = core::Channel{core::ChannelFormat::sRGB8, "", {}};
    core::Layer layer;
    layer.uid = project.AllocateId();
    layer.kind = core::LayerKind::fill;
    layer.name = "fill";
    layer.fill = core::FillContent{};
    core::Effect effect;
    effect.uid = project.AllocateId();
    effect.kind = core::EffectKind::generator;
    effect.name = "dirt";
    generator = effect.uid;
    layer.content_effects.push_back(effect);
    stack.root_layers.push_back(layer);
    set.stacks.push_back(stack);
    project.texture_sets.push_back(set);
    return project;
}

/// A snapshot backend that admits every request: a stand-in for a project snapshot with the
/// request's exact signature, so that an admitted edit reaches its transaction.
class AdmitAll final : public IProceduralBackend {
public:
    std::string_view Name() const override { return "snapshot"; }
    ParityStatus Status(const core::AssetUrl&) const override { return ParityStatus::Unavailable("test"); }
    bool CanEvaluate(const ProceduralRequest&) const override { return true; }
    std::optional<UnsupportedProcedural> Refusal(const ProceduralRequest&) const override { return std::nullopt; }
    RasterFuture Evaluate(const ProceduralRequest&, const InputImages&) override {
        std::promise<render::Result<Raster>> promise;
        promise.set_value(render::Fail(render::ErrorCode::RequestFailed, std::nullopt, "not evaluated"));
        return promise.get_future();
    }
};

int RunDomain(const fs::path& shipped) {
    namespace json = core::json;
    std::optional<Fixture> fixture = LoadFixture(shipped);
    if (!fixture) return Finish();
    HlslBackend hlsl(nullptr);
    if (!RegisterGeneratorFamilies(hlsl, fixture->library)) return Finish();
    ProceduralSeam seam(nullptr, &hlsl);

    core::Id generator = core::kNoId;
    core::DocumentState initial;
    initial.project_uuid = "6f1c2a3e-0000-4000-8000-00000000a329";
    initial.project = GeneratorProject(generator);
    core::Document document(initial);
    const core::Project before = *document.snapshot().project;
    int keys = 0;
    int submits = 0;
    const SubmitEdit submit = [&](const std::function<void(core::Edit&)>& call) {
        ++submits;
        const std::string key = "generator-" + std::to_string(++keys);
        return core::Execute(document,
                             core::MutationRequest{"procedural_set", json::Object{{"key", key}}, key, document.revision()},
                             call);
    };

    const std::unique_ptr<MeshMaps> maps = AuthoredMaps(kSize, 17);
    const std::vector<MeshMapUsage> usages = GeneratorUsages(Url(kDirtAsset));
    const render::Result<BoundMeshMaps> bound = BindMeshMaps(maps->set, usages, maps->resources);
    Check(bound.has_value(), "Dirt's mesh maps bind by usage", bound ? "" : bound.error().Describe());
    if (!bound) return Finish();

    struct Case {
        std::string what;
        std::string field;
        std::string value;
        std::function<void(core::ProceduralRef&, UseContext&, std::map<std::string, ImageInput>&)> change;
    };
    const auto param = [](std::string name, json::Value value) {
        return [name, value](core::ProceduralRef& ref, UseContext&, std::map<std::string, ImageInput>&) {
            ref.params[name] = value;
        };
    };
    const double aboveOne = std::nextafter(1.0, 2.0);
    const double belowZero = std::nextafter(0.0, -1.0);
    std::vector<Case> cases = {
        {"a parameter one ulp above its range", "params.noise_amount", "", param("noise_amount", aboveOne)},
        {"a parameter one ulp below its range", "params.cavity_weight", "", param("cavity_weight", belowZero)},
        {"an enumerated parameter outside its set", "params.spread", "9", param("spread", int64_t{9})},
        {"low and high closer than the joint constraint allows", "params", "",
         [](core::ProceduralRef& ref, UseContext&, std::map<std::string, ImageInput>&) {
             ref.params["low"] = 0.5;
             ref.params["high"] = 0.5;
         }},
        {"a seed outside 32 bits", "seed", "4294967296",
         [](core::ProceduralRef&, UseContext& context, std::map<std::string, ImageInput>&) {
             context.seed = 0x100000000ull;
         }},
        {"a mesh class the domain does not declare", "mesh.class", "\"vehicle\"",
         [](core::ProceduralRef&, UseContext& context, std::map<std::string, ImageInput>&) {
             context.meshClass = "vehicle";
         }},
        {"a missing mesh-map input", "inputs.AO", "missing",
         [](core::ProceduralRef&, UseContext&, std::map<std::string, ImageInput>& inputs) { inputs.erase("AO"); }},
        {"a mesh-map input in half floats", "inputs.Curvature.format", "\"f16\"",
         [](core::ProceduralRef&, UseContext&, std::map<std::string, ImageInput>& inputs) {
             inputs.at("Curvature").spec.format = ChannelFormat::F16;
         }},
        {"a mesh-map input in another colour space", "inputs.Position.colour_space", "\"srgb\"",
         [](core::ProceduralRef&, UseContext&, std::map<std::string, ImageInput>& inputs) {
             inputs.at("Position").spec.colourSpace = "srgb";
         }},
        {"a mesh-map input at another resolution than the output", "inputs.AO.resolution", "2048",
         [](core::ProceduralRef&, UseContext&, std::map<std::string, ImageInput>& inputs) {
             inputs.at("AO").spec.resolution = 2048;
         }},
        {"an output resolution of 512", "output.resolution", "512",
         [](core::ProceduralRef&, UseContext& context, std::map<std::string, ImageInput>&) {
             context.output.resolution = 512;
         }},
        {"an output resolution of 8192", "output.resolution", "8192",
         [](core::ProceduralRef&, UseContext& context, std::map<std::string, ImageInput>&) {
             context.output.resolution = 8192;
         }},
    };
    const auto baseline = [&]() {
        core::ProceduralRef ref;
        ref.asset = std::string(kDirtAsset);
        UseContext context;
        context.meshClass = "sphere";
        context.output = RasterSpec{kSize, ChannelFormat::F32, "linear", 1};
        context.seed = 42;
        return std::pair{ref, context};
    };
    for (const Case& c : cases) {
        auto [ref, context] = baseline();
        std::map<std::string, ImageInput> inputs = bound->inputs;
        c.change(ref, context, inputs);
        const int submitted = submits;
        const auto refused = SetGeneratorEffect(generator, ref, context, inputs, fixture->library, seam, submit);
        const bool named = !refused && refused.error().reason == kOutsideDomain && refused.error().field == c.field &&
                           (c.value.empty() || refused.error().value == c.value);
        Check(named && submits == submitted && document.revision() == 0 && *document.snapshot().project == before,
              "outside the domain, refused before mutation with nothing clamped: " + c.what,
              refused ? "admitted" : refused.error().Describe());
        // The candidate lane refuses the same request: nothing is evaluated in its place.
        const auto request = GeneratorRequest(ref, context, inputs, fixture->library);
        Check(request && !hlsl.EvaluateReference(*request, bound->images),
              "the candidate lane evaluates nothing: " + c.what);
    }

    // Inside the domain the uncertified family is still refused before mutation.
    {
        auto [ref, context] = baseline();
        const auto refused = SetGeneratorEffect(generator, ref, context, bound->inputs, fixture->library, seam, submit);
        Check(!refused && refused.error().reason == kNotCertified && submits == 0 && document.revision() == 0,
              "inside the domain the uncertified Dirt is refused before mutation (family not certified)",
              refused ? "admitted" : refused.error().Describe());
    }
    // An admitted edit (a snapshot with the exact signature) commits the reference as given:
    // the mesh maps stay the texture set's, not the reference's.
    {
        AdmitAll snapshots;
        ProceduralSeam admitting(&snapshots, &hlsl);
        auto [ref, context] = baseline();
        ref.params["spread"] = int64_t{3};
        const auto committed =
            SetGeneratorEffect(generator, ref, context, bound->inputs, fixture->library, admitting, submit);
        core::Project now = *document.snapshot().project;
        const core::Effect* effect = core::FindEffect(now, generator);
        Check(committed && committed->result && committed->result->status == core::ResultStatus::committed &&
                  submits == 1 && document.revision() == 1 && effect != nullptr && effect->procedural &&
                  *effect->procedural == ref && effect->procedural->image_inputs.empty(),
              "an admitted generator edit commits the reference as given, with no mesh map stored in it",
              committed ? (committed->result ? committed->result->error : "not executed") : committed.error().Describe());
    }
    return Finish();
}

// ── kernels (items 2.2-2.4, CPU with dxcompiler) ─────────────────────────────

int RunKernels(const fs::path& dir, const fs::path& shipped) {
    std::optional<Fixture> fixture = LoadFixture(shipped);
    if (!fixture) return Finish();
    render::Result<std::unique_ptr<render::DxcKernelCompiler>> compiler =
        render::DxcKernelCompiler::Load(render::DefaultDxcompilerPath());
    Check(compiler.has_value(), "DXC loads", compiler ? "" : compiler.error().Describe());
    if (!compiler) return Finish();
    render::KernelCache cache(**compiler, dir / "kernel-cache");
    HlslBackend hlsl(nullptr);
    if (!RegisterGeneratorFamilies(hlsl, fixture->library)) return Finish();
    const std::unique_ptr<MeshMaps> maps = AuthoredMaps(kSize, 1);
    const std::optional<BoundMeshMaps> bound = Bind(*maps);
    if (!bound) return Finish();
    for (const std::string_view asset : GeneratorAssets()) {
        const ProceduralRequest request = GeneratorRequestOf(*fixture->records.at(std::string(asset)), *bound, kSize);
        auto kernels = hlsl.Kernels(request);
        Check(kernels && !kernels->empty(), "kernel passes planned for " + std::string(asset),
              kernels ? "" : kernels.error().Describe());
        if (!kernels) continue;
        for (const render::KernelSource& source : *kernels) {
            for (const render::KernelTarget target : {render::KernelTarget::Dxil, render::KernelTarget::Spirv}) {
                render::Result<render::CompiledKernel> kernel = cache.Get(source, target);
                Check(kernel && !kernel->bytecode.empty(),
                      "compiles: " + source.name + " (" + std::string(render::KernelTargetName(target)) + ")",
                      kernel ? "" : kernel.error().Describe());
            }
        }
    }
    return Finish();
}

// ── gpu (items 2.2-2.4 and test 3.3, DX12) ───────────────────────────────────

render::Result<Raster> Get(RasterFuture& future) {
    if (future.wait_for(std::chrono::seconds(300)) != std::future_status::ready) {
        return render::Fail(render::ErrorCode::RequestFailed, std::nullopt, "no result within 300 s");
    }
    return future.get();
}

/// The parameter sets the GPU case evaluates per asset: the defaults, then edits inside the
/// domain.
std::vector<std::pair<std::string, Params>> GpuCases(std::string_view asset) {
    std::vector<std::pair<std::string, Params>> cases = {{"defaults", {}}};
    if (asset == kCurvatureAsset) {
        cases.push_back({"concave smoothed inverted", {{"mode", int64_t{1}}, {"smooth", int64_t{1}}, {"invert", int64_t{1}},
                                                       {"low", 0.125}, {"high", 0.625}}});
    } else if (asset == kPositionAsset) {
        cases.push_back({"axis 0 [0.25, 0.75]", {{"axis", int64_t{0}}, {"low", 0.25}, {"high", 0.75}}});
    } else if (asset == kWorldNormalAsset) {
        cases.push_back({"axis -Z smoothed", {{"axis", int64_t{5}}, {"low", -0.5}, {"high", 0.75}, {"smooth", int64_t{1}}}});
    } else if (asset == kOcclusionAsset) {
        cases.push_back({"[0.1, 0.9] inverted", {{"low", 0.1}, {"high", 0.9}, {"invert", int64_t{1}}}});
    } else if (asset == kDirtAsset) {
        cases.push_back({"spread 3, noise 0.5", {{"spread", int64_t{3}}, {"noise_amount", 0.5}, {"noise_scale", 24.0},
                                                 {"cavity_weight", 0.5}, {"low", 0.125}, {"high", 0.5}}});
    } else if (asset == kMaskBuilderAsset) {
        cases.push_back({"height, noise, grow -2", {{"source", int64_t{3}}, {"noise_amount", 0.625}, {"noise_scale", 12.0},
                                                    {"noise_low", 0.375}, {"noise_high", 0.75}, {"grow", int64_t{-2}}}});
    } else if (asset == kMaskEditorAsset) {
        cases.push_back({"six weights inverted", {{"edges_weight", 0.5}, {"cavity_weight", -0.25}, {"occlusion_weight", 0.75},
                                                  {"height_weight", 1.0}, {"up_weight", -1.0}, {"thickness_weight", 0.375},
                                                  {"low", -0.5}, {"high", 1.5}, {"invert", int64_t{1}}}});
    } else if (asset == kEdgeWearAsset) {
        cases.push_back({"protect 1, spread 2", {{"occlusion_protect", 1.0}, {"spread", int64_t{2}},
                                                 {"noise_amount", 0.75}, {"noise_scale", 3.5}}});
    }
    return cases;
}

int RunGpu(const fs::path& dir, const fs::path& shipped) {
    std::optional<Fixture> fixture = LoadFixture(shipped);
    if (!fixture) return Finish();
    render::EngineOptions options;
    options.kernelCacheRoot = dir / "kernel-cache";
    render::Engine engine(options);
    if (engine.DeviceError()) {
        std::printf("SKIP no DX12 device: %s\n", engine.DeviceError()->Describe().c_str());
        return kExitSkip;
    }
    HlslBackend hlsl(&engine);
    if (!RegisterGeneratorFamilies(hlsl, fixture->library)) return Finish();
    const std::unique_ptr<MeshMaps> maps = AuthoredMaps(kSize, 7);
    const std::optional<BoundMeshMaps> bound = Bind(*maps);
    if (!bound) return Finish();
    for (const std::string_view asset : GeneratorAssets()) {
        for (const auto& [what, changes] : GpuCases(asset)) {
            ProceduralRequest request =
                GeneratorRequestOf(*fixture->records.at(std::string(asset)), *bound, kSize, 0x9E3779B9u);
            for (const auto& [name, value] : changes) request.params[name] = value;
            const std::string label = std::string(asset) + " " + what;
            const render::Result<Raster> reference = hlsl.EvaluateReference(request, bound->images);
            RasterFuture first = hlsl.EvaluateCandidate(request, bound->images);
            const render::Result<Raster> gpu = Get(first);
            Check(reference && gpu && FirstDifference(*gpu, *reference).empty(),
                  "DX12 equals the CPU reference bit for bit: " + label,
                  !reference ? reference.error().Describe()
                             : (!gpu ? gpu.error().Describe() : FirstDifference(*gpu, *reference)));
            RasterFuture second = hlsl.EvaluateCandidate(request, bound->images);
            const render::Result<Raster> again = Get(second);
            Check(gpu && again && FirstDifference(*again, *gpu).empty(),
                  "DX12 repeats: identical bytes across two runs: " + label,
                  !gpu || !again ? "a run failed" : FirstDifference(*again, *gpu));
            request.tile = TileRect{1017, 0, 7, 33};
            const render::Result<Raster> tileReference = hlsl.EvaluateReference(request, bound->images);
            RasterFuture tileFuture = hlsl.EvaluateCandidate(request, bound->images);
            const render::Result<Raster> tile = Get(tileFuture);
            Check(tileReference && tile && FirstDifference(*tile, *tileReference).empty(),
                  "a DX12 tile at the border equals the CPU tile: " + label);
        }
    }
    return Finish();
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 4) {
        std::fprintf(stderr, "usage: uzp-proc-generator-tests signals | wear | masks | bind | domain | kernels | gpu <work-dir> <shipped-library>\n");
        return 2;
    }
    const std::string_view mode = argv[1];
    const fs::path dir = argv[2];
    const fs::path shipped = argv[3];
    if (mode == "signals") return RunSignals(shipped);
    if (mode == "wear") return RunWear(shipped);
    if (mode == "masks") return RunMasks(shipped);
    if (mode == "bind") return RunBind(shipped);
    if (mode == "domain") return RunDomain(shipped);
    if (mode == "kernels") return RunKernels(dir, shipped);
    if (mode == "gpu") return RunGpu(dir, shipped);
    std::fprintf(stderr, "unknown case %.*s\n", static_cast<int>(mode.size()), mode.data());
    return 2;
}
