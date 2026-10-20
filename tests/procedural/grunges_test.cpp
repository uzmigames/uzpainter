// Native tests of the grunge and noise family (src/procedural/grunges.h, rulebook task
// phase3.2_proc-grunge-families, decision 331). Built by `zig build proc-grunge-tests` and driven
// by tests/procedural/test_proc_grunge_families.py.
//
// Usage: uzp-proc-grunge-tests <case> <work-dir> <shipped-library>
//   families  every inventoried asset registers from its record, evaluates on the CPU lane with
//             its seed and parameters, answers a tile with the whole texture's texels, and is
//             refused by the seam as uncertified (CPU; item 2.3)
//   tiling    the texture continued past its border is the texture itself, bit for bit, for
//             every asset at several tilings, flips and resolutions (CPU; test 3.2)
//   seeds     two seeds give two different textures on the CPU lane (CPU; test 3.3, our half)
//   domain    a parameter, a seed, a mesh-map input, a resolution and an output format just
//             outside each asset's domain are refused before mutation, naming the field, with
//             nothing clamped; inside it the uncertified asset is refused as such; an admitted
//             grunge source commits the reference as given (CPU; test 3.4)
//   kernels   every asset's kernel compiled to DXIL and SPIR-V (CPU, needs dxcompiler.dll)
//   gpu       every asset on DX12 equal to its CPU reference bit for bit, whole and by tile; the
//             same seed twice gives the same bytes, and two seeds differ (GPU; items 2.3, 3.3)
//
// The shipped library is the repository's `assets/procedural/`. No case compares against a
// Painter output: the assets are not certified.
//
// Output: `PASS <check>` / `FAIL <check>: <detail>` / `INFO` lines.
// Exit code 0 when every check passed, 1 when one failed, 2 on a usage error, 77 when the case
// needs a DX12 hardware adapter and there is none.

#include "procedural/asset_library.h"
#include "procedural/grunges.h"
#include "procedural/hlsl_backend.h"
#include "procedural/seam.h"

#include "render/engine_thread.h"
#include "render/kernel_cache.h"

#include "uzp_core/document/document.h"
#include "uzp_core/document/nodes.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/transaction/transaction.h"
#include "uzp_core/types/project.h"

#include <bit>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <functional>
#include <future>
#include <optional>
#include <string>
#include <string_view>
#include <vector>
#include "../no_error_dialogs.h"

namespace {

using namespace uzp::procedural;
namespace fs = std::filesystem;
namespace render = uzp::render;

constexpr int kExitSkip = 77;
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
            first = "texel (" + std::to_string(i % a.width) + ", " + std::to_string(i / a.width) + "): " +
                    Hex(Bits(a.texels[i])) + " against " + Hex(Bits(b.texels[i]));
        }
    }
    return count == 0 ? std::string() : std::to_string(count) + " values differ, first at " + first;
}

/// How many texels of two equal-shaped rasters differ.
size_t Differing(const Raster& a, const Raster& b) {
    size_t count = 0;
    for (size_t i = 0; i < a.texels.size() && i < b.texels.size(); ++i) {
        if (Bits(a.texels[i]) != Bits(b.texels[i])) ++count;
    }
    return count;
}

std::string Url(std::string_view id) { return "uzasset://grunge/" + std::string(id) + "@1"; }

struct Fixture {
    AssetLibrary library;
    std::vector<const AssetRecord*> records;  ///< In `GrungeAssetIds()` order.
};

std::optional<Fixture> LoadFixture(const fs::path& shipped) {
    auto loaded = AssetLibrary::Load(shipped);
    Check(loaded.has_value(), "the shipped library loads", loaded ? "" : loaded.error());
    if (!loaded) return std::nullopt;
    Fixture fixture{std::move(*loaded), {}};
    for (const std::string_view id : GrungeAssetIds()) {
        const AssetRecord* record = fixture.library.Find(uzp::core::ParseAssetUrl(Url(id)));
        if (record == nullptr) {
            Check(false, "the shipped library holds every inventoried grunge asset", "no record of " + Url(id));
            return std::nullopt;
        }
        fixture.records.push_back(record);
    }
    return fixture;
}

/// A request inside the record's domain: its defaults, the `sphere` class, a mono float32
/// linear output at `resolution`, and `seed`.
ProceduralRequest Request(const AssetRecord& record, uint32_t resolution, uint64_t seed) {
    ProceduralRequest request;
    request.asset = record.asset;
    request.params = record.defaults;
    request.meshClass = "sphere";
    request.output = RasterSpec{resolution, ChannelFormat::F32, "linear", 1};
    request.seed = seed;
    return request;
}

/// Mean, minimum and maximum of a raster's values.
struct Stats {
    double mean = 0.0;
    float min = 0.0f;
    float max = 0.0f;
};

Stats StatsOf(const Raster& raster) {
    Stats s;
    if (raster.texels.empty()) return s;
    s.min = s.max = raster.texels.front();
    double sum = 0.0;
    for (const float v : raster.texels) {
        sum += v;
        if (v < s.min) s.min = v;
        if (v > s.max) s.max = v;
    }
    s.mean = sum / static_cast<double>(raster.texels.size());
    return s;
}

/// A parameter value as a number.
double NumberOf(const ParamValue& value) {
    if (const auto* d = std::get_if<double>(&value)) return *d;
    if (const auto* i = std::get_if<int64_t>(&value)) return static_cast<double>(*i);
    return 0.0;
}

/// A request with one parameter changed (an integer or a number, as the record's default).
ProceduralRequest With(ProceduralRequest request, const std::string& name, double value) {
    if (std::holds_alternative<int64_t>(request.params.at(name)) && value == static_cast<double>(int64_t(value))) {
        request.params[name] = static_cast<int64_t>(value);
    } else {
        request.params[name] = value;
    }
    return request;
}

/// The tile used by the CPU checks (the whole 1024 texture is the GPU case's job).
constexpr TileRect kProbe{448, 448, 128, 128};

// ── families (item 2.3) ──────────────────────────────────────────────────────

int RunFamilies(const fs::path& shipped) {
    std::optional<Fixture> fixture = LoadFixture(shipped);
    if (!fixture) return Finish();
    HlslBackend hlsl(nullptr);
    const std::expected<void, std::string> registered = RegisterGrungeFamilies(hlsl, fixture->library);
    Check(registered.has_value(), "every inventoried grunge asset registers from its library record",
          registered ? "" : registered.error());
    if (!registered) return Finish();
    ProceduralSeam seam(nullptr, &hlsl);
    bool allRanges = true;
    bool allVary = true;
    bool allInvert = true;
    bool allTiles = true;
    bool allParams = true;
    bool allRefused = true;
    std::string detail;
    for (const AssetRecord* record : fixture->records) {
        const std::string name = uzp::core::FormatAssetUrl(record->asset);
        ProceduralRequest request = Request(*record, 1024, 7);
        request.tile = kProbe;
        const render::Result<Raster> base = hlsl.EvaluateReference(request, {});
        if (!base || base->texels.size() != size_t{kProbe.width} * kProbe.height || base->channels != 1) {
            allRanges = false;
            detail += name + ": " + (base ? "wrong shape" : base.error().Describe()) + "; ";
            continue;
        }
        const Stats stats = StatsOf(*base);
        std::printf("INFO %s defaults: mean %.4f min %.4f max %.4f\n", name.c_str(), stats.mean, stats.min, stats.max);
        if (stats.min < 0.0f || stats.max > 1.0f) {
            allRanges = false;
            detail += name + " leaves [0, 1]; ";
        }
        if (!(stats.max > stats.min)) {
            allVary = false;
            detail += name + " is constant; ";
        }
        // invert is 1 - value, exactly.
        const render::Result<Raster> inverted = hlsl.EvaluateReference(With(request, "invert", 1), {});
        bool exact = inverted && inverted->texels.size() == base->texels.size();
        for (size_t i = 0; exact && i < base->texels.size(); ++i) {
            exact = Bits(inverted->texels[i]) == Bits(1.0f - base->texels[i]);
        }
        if (!exact) {
            allInvert = false;
            detail += name + ": invert is not 1 - value; ";
        }
        // A tile equals the same texels of the whole texture, and GrungeTexel at any position.
        const std::expected<std::vector<uint32_t>, std::string> words = GrungeWords(request);
        ProceduralRequest corner = request;
        corner.tile = TileRect{1017, 0, 7, 9};
        const render::Result<Raster> tile = hlsl.EvaluateReference(corner, {});
        bool tiled = words && tile && tile->texels.size() == 63;
        for (uint32_t y = 0; tiled && y < 9; ++y) {
            for (uint32_t x = 0; tiled && x < 7; ++x) {
                tiled = Bits(tile->texels[y * 7 + x]) ==
                        Bits(GrungeTexel(*words, static_cast<int32_t>(1017 + x), static_cast<int32_t>(y), 7));
            }
        }
        for (uint32_t y = 0; tiled && y < kProbe.height; y += 17) {
            for (uint32_t x = 0; tiled && x < kProbe.width; x += 13) {
                tiled = Bits(base->texels[y * kProbe.width + x]) ==
                        Bits(GrungeTexel(*words, static_cast<int32_t>(kProbe.x + x), static_cast<int32_t>(kProbe.y + y), 7));
            }
        }
        if (!tiled) {
            allTiles = false;
            detail += name + ": a tile differs from the texture's texels; ";
        }
        // Every parameter of the domain changes the texture somewhere (no parameter is ignored).
        for (const auto& [param, rule] : record->domain.parameters) {
            if (param == "invert") continue;
            double other = 0.0;
            const double current = NumberOf(request.params.at(param));
            if (rule.range) {
                other = current == rule.range->second ? rule.range->first : rule.range->second;
            } else {
                other = NumberOf(rule.set.back()) == current ? NumberOf(rule.set.front()) : NumberOf(rule.set.back());
            }
            const render::Result<Raster> changed = hlsl.EvaluateReference(With(request, param, other), {});
            if (!changed || Differing(*changed, *base) == 0) {
                allParams = false;
                detail += name + ": " + param + " changes nothing; ";
            }
        }
        // The seam serves no uncertified asset.
        const auto selected = seam.Select(Request(*record, 1024, 7));
        if (selected || selected.error().reason != kNotCertified) {
            allRefused = false;
            detail += name + ": " + (selected ? std::string("served") : selected.error().Describe()) + "; ";
        }
    }
    Check(allRanges, "every grunge asset evaluates its defaults on the CPU lane, inside [0, 1]", detail);
    Check(allVary, "no grunge asset is constant at its defaults", detail);
    Check(allInvert, "invert gives 1 - value bit for bit for every grunge asset", detail);
    Check(allTiles, "a tile of every grunge asset equals the same texels of the whole texture", detail);
    Check(allParams, "every declared parameter of every grunge asset changes its texture", detail);
    Check(allRefused, "the seam refuses every uncertified grunge asset inside its domain (family not certified)",
          detail);

    // The family's own refusals.
    ProceduralRequest foreign = Request(*fixture->records.front(), 1024, 0);
    foreign.asset = uzp::core::ParseAssetUrl("uzasset://filter/sharpen@1");
    Check(!GrungeWords(foreign).has_value(), "GrungeWords refuses an asset outside the family");
    ProceduralRequest missing = Request(*fixture->records.front(), 1024, 0);
    missing.params.erase("balance");
    Check(!GrungeWords(missing).has_value(), "GrungeWords refuses a request without a declared parameter");
    Check(!hlsl.EvaluateReference(missing, {}).has_value(),
          "the CPU lane refuses a request outside the domain before evaluating it");
    return Finish();
}

// ── tiling (test 3.2) ────────────────────────────────────────────────────────

/// Whether the texel coordinate (x + 1/2) P / R is exact in float32 for every texel of two tiles.
bool CoordinatesExact(uint32_t period, uint32_t resolution) {
    const float scale = static_cast<float>(double(period) / resolution);
    for (int64_t x = -int64_t{resolution}; x < 2 * int64_t{resolution}; ++x) {
        const float c = (static_cast<float>(x) + 0.5f) * scale;
        if (static_cast<double>(c) != (double(x) + 0.5) * period / resolution) return false;
    }
    return true;
}

int RunTiling(const fs::path& shipped) {
    std::optional<Fixture> fixture = LoadFixture(shipped);
    if (!fixture) return Finish();
    struct Variant {
        std::string what;
        uint32_t resolution;
        std::vector<std::pair<std::string, double>> params;
    };
    const std::vector<Variant> variants = {
        {"defaults at 1024", 1024, {}},
        {"tiling 3, balance 0.3, contrast 0.6 at 1024", 1024, {{"tiling", 3}, {"balance", 0.3}, {"contrast", 0.6}}},
        {"tiling 8, invert at 2048", 2048, {{"tiling", 8}, {"invert", 1}}},
        {"tiling 5 at 4096", 4096, {{"tiling", 5}}},
    };
    bool periodic = true;
    bool exactCoordinates = true;
    std::string detail;
    size_t compared = 0;
    for (const AssetRecord* record : fixture->records) {
        const std::string name = uzp::core::FormatAssetUrl(record->asset);
        std::vector<Variant> own = variants;
        if (record->domain.parameters.contains("flip_horizontal")) {
            own.push_back({"flipped both ways, tiling 2 at 1024", 1024,
                           {{"tiling", 2}, {"flip_horizontal", 1}, {"flip_vertical", 1}}});
        }
        if (record->domain.parameters.contains("disorder")) own.push_back({"disorder 1 at 1024", 1024, {{"disorder", 1}}});
        if (record->domain.parameters.contains("rotation_variation")) {
            own.push_back({"rotation variation 90 at 1024", 1024, {{"rotation_variation", 90}}});
        }
        for (const Variant& variant : own) {
            ProceduralRequest request = Request(*record, variant.resolution, 12345);
            for (const auto& [param, value] : variant.params) request = With(request, param, value);
            if (std::optional<UnsupportedProcedural> outside = CheckDomain(request, record->domain)) {
                periodic = false;
                detail += name + " " + variant.what + ": " + outside->Describe() + "; ";
                continue;
            }
            const std::expected<std::vector<uint32_t>, std::string> words = GrungeWords(request);
            if (!words) {
                periodic = false;
                detail += name + ": " + words.error() + "; ";
                continue;
            }
            const int32_t r = static_cast<int32_t>(variant.resolution);
            // The periods are words 1, 2 (pattern) and 13 (break-up) of the block.
            for (const uint32_t period : {(*words)[1], (*words)[2], (*words)[13]}) {
                if (!CoordinatesExact(period, variant.resolution)) {
                    exactCoordinates = false;
                    detail += name + " " + variant.what + ": period " + std::to_string(period) + " inexact; ";
                }
            }
            // Bands along the four borders, every texel of them, plus a lattice of interior texels.
            std::vector<std::pair<int32_t, int32_t>> texels;
            for (int32_t i = 0; i < r; ++i) {
                for (const int32_t band : {0, 1, r - 2, r - 1}) {
                    texels.push_back({band, i});
                    texels.push_back({i, band});
                }
            }
            for (int32_t y = 3; y < r; y += r / 16) {
                for (int32_t x = 5; x < r; x += r / 16) texels.push_back({x, y});
            }
            const uint32_t seed = 12345;
            for (const auto& [x, y] : texels) {
                const uint32_t at = Bits(GrungeTexel(*words, x, y, seed));
                const std::pair<int32_t, int32_t> copies[] = {{x + r, y}, {x, y + r}, {x + r, y + r}, {x - r, y}, {x, y - r}};
                for (const auto& [cx, cy] : copies) {
                    ++compared;
                    if (Bits(GrungeTexel(*words, cx, cy, seed)) != at) {
                        if (periodic) {
                            detail += name + " " + variant.what + ": texel (" + std::to_string(x) + ", " +
                                      std::to_string(y) + ") against (" + std::to_string(cx) + ", " +
                                      std::to_string(cy) + "); ";
                        }
                        periodic = false;
                    }
                }
            }
        }
    }
    std::printf("INFO %zu texel pairs compared\n", compared);
    Check(exactCoordinates,
          "every texel coordinate (x + 1/2) P / R of every grunge asset is exact in float32 over three tiles", detail);
    Check(periodic,
          "every grunge asset wraps seamlessly: the texture continued one tile past each border is the texture "
          "itself, bit for bit",
          detail);

    // The CPU lane's texture is that continued field: its last column's right neighbour is its
    // first column (checked on the whole texture of one asset per kind).
    bool wraps = true;
    HlslBackend hlsl(nullptr);
    if (!RegisterGrungeFamilies(hlsl, fixture->library)) return Finish();
    for (const std::string_view id : {"rock", "stone-details", "spots-bw-a", "scratches", "cracks-leather", "linen"}) {
        const AssetRecord* record = fixture->library.Find(uzp::core::ParseAssetUrl(Url(id)));
        ProceduralRequest request = Request(*record, 1024, 99);
        request.tile = TileRect{0, 0, 1024, 2};
        const std::expected<std::vector<uint32_t>, std::string> words = GrungeWords(request);
        const render::Result<Raster> rows = hlsl.EvaluateReference(request, {});
        if (!words || !rows) {
            wraps = false;
            continue;
        }
        for (int32_t y = 0; y < 2; ++y) {
            wraps = wraps && Bits(GrungeTexel(*words, 1024, y, 99)) == Bits(rows->texels[size_t(y) * 1024]) &&
                    Bits(GrungeTexel(*words, -1, y, 99)) == Bits(rows->texels[size_t(y) * 1024 + 1023]);
        }
    }
    Check(wraps, "the CPU lane's first column is the continuation of its last, for one asset of each pattern kind");
    return Finish();
}

// ── seeds (test 3.3, our half) ───────────────────────────────────────────────

int RunSeeds(const fs::path& shipped) {
    std::optional<Fixture> fixture = LoadFixture(shipped);
    if (!fixture) return Finish();
    HlslBackend hlsl(nullptr);
    if (!RegisterGrungeFamilies(hlsl, fixture->library)) return Finish();
    bool differ = true;
    bool repeat = true;
    std::string detail;
    for (const AssetRecord* record : fixture->records) {
        ProceduralRequest a = Request(*record, 1024, 30095);
        a.tile = kProbe;
        ProceduralRequest b = a;
        b.seed = 30096;
        const render::Result<Raster> first = hlsl.EvaluateReference(a, {});
        const render::Result<Raster> again = hlsl.EvaluateReference(a, {});
        const render::Result<Raster> other = hlsl.EvaluateReference(b, {});
        if (!first || !again || !other) {
            differ = repeat = false;
            continue;
        }
        const size_t changed = Differing(*first, *other);
        std::printf("INFO %s: seeds 30095 and 30096 differ on %zu of %zu texels\n",
                    uzp::core::FormatAssetUrl(record->asset).c_str(), changed, first->texels.size());
        if (changed == 0) {
            differ = false;
            detail += uzp::core::FormatAssetUrl(record->asset) + "; ";
        }
        repeat = repeat && FirstDifference(*first, *again).empty();
    }
    Check(differ, "two seeds give two different textures for every grunge asset (CPU lane)", detail);
    Check(repeat, "the same seed repeats bit for bit on the CPU lane for every grunge asset");
    return Finish();
}

// ── kernels ──────────────────────────────────────────────────────────────────

int RunKernels(const fs::path& dir, const fs::path& shipped) {
    std::optional<Fixture> fixture = LoadFixture(shipped);
    if (!fixture) return Finish();
    render::Result<std::unique_ptr<render::DxcKernelCompiler>> compiler =
        render::DxcKernelCompiler::Load(render::DefaultDxcompilerPath());
    Check(compiler.has_value(), "DXC loads", compiler ? "" : compiler.error().Describe());
    if (!compiler) return Finish();
    render::KernelCache cache(**compiler, dir / "kernel-cache");
    HlslBackend hlsl(nullptr);
    if (!RegisterGrungeFamilies(hlsl, fixture->library)) return Finish();
    bool planned = true;
    bool compiled = true;
    std::string detail;
    for (const AssetRecord* record : fixture->records) {
        auto kernels = hlsl.Kernels(Request(*record, 1024, 0));
        if (!kernels || kernels->size() != 1) {
            planned = false;
            detail += uzp::core::FormatAssetUrl(record->asset) + (kernels ? "" : ": " + kernels.error().Describe()) + "; ";
            continue;
        }
        for (const render::KernelTarget target : {render::KernelTarget::Dxil, render::KernelTarget::Spirv}) {
            render::Result<render::CompiledKernel> kernel = cache.Get(kernels->front(), target);
            if (!kernel || kernel->bytecode.empty()) {
                compiled = false;
                detail += kernels->front().name + " (" + std::string(render::KernelTargetName(target)) +
                          "): " + (kernel ? "empty" : kernel.error().Describe()) + "; ";
            }
        }
    }
    Check(planned, "one kernel pass planned for every grunge asset", detail);
    Check(compiled, "every grunge kernel compiles to DXIL and SPIR-V", detail);
    return Finish();
}

// ── gpu (items 2.3, 3.3; DX12) ───────────────────────────────────────────────

render::Result<Raster> Get(RasterFuture& future) {
    if (future.wait_for(std::chrono::seconds(300)) != std::future_status::ready) {
        return render::Fail(render::ErrorCode::RequestFailed, std::nullopt, "no result within 300 s");
    }
    return future.get();
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
    if (!RegisterGrungeFamilies(hlsl, fixture->library)) return Finish();
    for (const AssetRecord* record : fixture->records) {
        const std::string name = uzp::core::FormatAssetUrl(record->asset);
        ProceduralRequest request = Request(*record, 1024, 24464);
        if (record->domain.parameters.contains("tiling")) request = With(request, "tiling", 2);
        if (record->domain.parameters.contains("contrast")) request = With(request, "contrast", 0.5);
        const render::Result<Raster> reference = hlsl.EvaluateReference(request, {});
        RasterFuture future = hlsl.EvaluateCandidate(request, {});
        const render::Result<Raster> gpu = Get(future);
        Check(reference && gpu && FirstDifference(*gpu, *reference).empty(),
              "DX12 equals the CPU reference bit for bit over the whole 1024 texture: " + name,
              !reference ? reference.error().Describe()
                         : (!gpu ? gpu.error().Describe() : FirstDifference(*gpu, *reference)));
        // 3.3: the same seed repeats byte-identically on DX12; another seed differs.
        RasterFuture againFuture = hlsl.EvaluateCandidate(request, {});
        const render::Result<Raster> again = Get(againFuture);
        Check(gpu && again && gpu->texels.size() == again->texels.size() &&
                  std::memcmp(gpu->texels.data(), again->texels.data(), gpu->texels.size() * sizeof(float)) == 0,
              "the same seed repeats byte-identically on DX12: " + name);
        ProceduralRequest otherSeed = request;
        otherSeed.seed = 24465;
        RasterFuture otherFuture = hlsl.EvaluateCandidate(otherSeed, {});
        const render::Result<Raster> other = Get(otherFuture);
        const size_t changed = gpu && other ? Differing(*gpu, *other) : 0;
        Check(changed > 0, "two seeds give two different textures on DX12: " + name,
              std::to_string(changed) + " texels differ");
        if (gpu && other) {
            std::printf("INFO %s: seeds 24464 and 24465 differ on %zu of %zu texels on DX12\n", name.c_str(), changed,
                        gpu->texels.size());
        }
        ProceduralRequest corner = request;
        corner.tile = TileRect{1017, 0, 7, 33};
        const render::Result<Raster> tileReference = hlsl.EvaluateReference(corner, {});
        RasterFuture tileFuture = hlsl.EvaluateCandidate(corner, {});
        const render::Result<Raster> tile = Get(tileFuture);
        Check(tileReference && tile && FirstDifference(*tile, *tileReference).empty(),
              "a DX12 tile at the border equals the CPU tile: " + name);
    }
    return Finish();
}

// ── domain (test 3.4) ────────────────────────────────────────────────────────

namespace core = uzp::core;

/// A project with one fill layer in a stack holding a Roughness channel, and in the layer's mask
/// one fill effect; `layer` and `maskFill` receive their uids.
core::Project GrungeProject(core::Id& layer, core::Id& maskFill) {
    core::Project project;
    project.versions.app_version = "0.0.0";
    project.versions.evaluator_profile = "painter-12.1-isolated-linear";
    core::TextureSet set;
    set.id = project.AllocateId();
    set.name = set.original_name = set.material_id = "set";
    set.uv_tiles = {core::UVTile{project.AllocateId(), 1001, {}}};
    core::Stack stack;
    stack.id = project.AllocateId();
    stack.channels[core::ChannelType::Roughness] = core::Channel{core::ChannelFormat::L16, "", {}};
    core::Layer fill;
    fill.uid = project.AllocateId();
    fill.kind = core::LayerKind::fill;
    fill.name = "fill";
    fill.fill = core::FillContent{};
    layer = fill.uid;
    core::Effect effect;
    effect.uid = project.AllocateId();
    effect.kind = core::EffectKind::fill;
    effect.name = "grunge";
    effect.mono_blending = core::Blending{};
    effect.fill = core::FillContent{};
    maskFill = effect.uid;
    fill.mask = core::Mask{};
    fill.mask->effects.push_back(effect);
    stack.root_layers.push_back(fill);
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
    if (!RegisterGrungeFamilies(hlsl, fixture->library)) return Finish();
    ProceduralSeam seam(nullptr, &hlsl);

    core::Id layer = core::kNoId;
    core::Id maskFill = core::kNoId;
    core::DocumentState initial;
    initial.project_uuid = "6f1c2a3e-0000-4000-8000-00000000a331";
    initial.project = GrungeProject(layer, maskFill);
    core::Document document(initial);
    const core::Project before = *document.snapshot().project;
    int keys = 0;
    int submits = 0;
    const SubmitEdit submit = [&](const std::function<void(core::Edit&)>& call) {
        ++submits;
        const std::string key = "grunge-" + std::to_string(++keys);
        return core::Execute(document,
                             core::MutationRequest{"procedural_set", json::Object{{"key", key}}, key, document.revision()},
                             call);
    };

    struct Case {
        std::string what;
        std::string field;
        std::string value;
        std::function<void(core::ProceduralRef&, UseContext&)> change;
    };
    const auto param = [](std::string name, json::Value value) {
        return [name, value](core::ProceduralRef& ref, UseContext&) { ref.params[name] = value; };
    };
    const double aboveOne = std::nextafter(1.0, 2.0);
    const double belowZero = std::nextafter(0.0, -1.0);
    const std::string hash(64, 'a');
    for (const AssetRecord* record : fixture->records) {
        const std::string name = core::FormatAssetUrl(record->asset);
        std::vector<Case> cases = {
            {"a parameter one ulp above its range", "params.balance", "", param("balance", aboveOne)},
            {"a parameter one ulp below its range", "params.contrast", "", param("contrast", belowZero)},
            {"an invert outside its set", "params.invert", "2", param("invert", int64_t{2})},
            {"a tiling of 9 repeats", "params.tiling", "9", param("tiling", int64_t{9})},
            {"a tiling of 0 repeats", "params.tiling", "0", param("tiling", int64_t{0})},
            {"a fractional tiling", "params.tiling", "2.5", param("tiling", 2.5)},
            {"a recorded parameter with no counterpart", "params.brush_pattern", "", param("brush_pattern", int64_t{1})},
            {"a seed outside 32 bits", "seed", "4294967296",
             [](core::ProceduralRef&, UseContext& context) { context.seed = 0x100000000ull; }},
            {"a mesh class the domain does not declare", "mesh.class", "\"vehicle\"",
             [](core::ProceduralRef&, UseContext& context) { context.meshClass = "vehicle"; }},
            {"two UV tiles", "mesh.uv_tiles", "2", [](core::ProceduralRef&, UseContext& context) { context.uvTiles = 2; }},
            {"a mesh-map input, which no grunge reads", "inputs.AO", "present",
             [hash](core::ProceduralRef& ref, UseContext& context) {
                 ref.image_inputs["AO"] = core::ResourceBinding{hash, std::nullopt, {}};
                 context.inputs["AO"] = RasterSpec{1024, ChannelFormat::U16, "raw", 1};
             }},
            {"an output resolution of 512", "output.resolution", "512",
             [](core::ProceduralRef&, UseContext& context) { context.output.resolution = 512; }},
            {"an output resolution of 8192", "output.resolution", "8192",
             [](core::ProceduralRef&, UseContext& context) { context.output.resolution = 8192; }},
            {"an output in half floats", "output.format", "\"f16\"",
             [](core::ProceduralRef&, UseContext& context) { context.output.format = ChannelFormat::F16; }},
            {"an sRGB output", "output.colour_space", "\"srgb\"",
             [](core::ProceduralRef&, UseContext& context) { context.output.colourSpace = "srgb"; }},
            {"a three-channel output", "output.channels", "3",
             [](core::ProceduralRef&, UseContext& context) { context.output.channels = 3; }},
        };
        // The asset's own parameters: a ranged one one ulp past its top, an enumerated one outside
        // its set.
        for (const auto& [p, rule] : record->domain.parameters) {
            if (p == "balance" || p == "contrast" || p == "invert" || p == "tiling") continue;
            if (rule.range) {
                cases.push_back({"its own parameter " + p + " one ulp above its range", "params." + p, "",
                                 param(p, std::nextafter(rule.range->second, rule.range->second + 1.0))});
            } else {
                cases.push_back({"its own parameter " + p + " outside its set", "params." + p, "2", param(p, int64_t{2})});
            }
        }
        const auto baseline = [&]() {
            core::ProceduralRef ref;
            ref.asset = name;
            UseContext context;
            context.meshClass = "sphere";
            context.output = RasterSpec{1024, ChannelFormat::F32, "linear", 1};
            context.seed = 42;
            return std::pair{ref, context};
        };
        for (const Case& c : cases) {
            auto [ref, context] = baseline();
            c.change(ref, context);
            const int submitted = submits;
            const auto refused = SetGrungeSource(maskFill, std::nullopt, ref, context, fixture->library, seam, submit);
            const bool named = !refused && refused.error().reason == kOutsideDomain &&
                               refused.error().field == c.field && (c.value.empty() || refused.error().value == c.value);
            Check(named && submits == submitted && document.revision() == 0 && *document.snapshot().project == before,
                  "outside the domain, refused before mutation with nothing clamped: " + name + ", " + c.what,
                  refused ? "admitted" : refused.error().Describe());
            // The candidate lane refuses the same request: nothing is evaluated in its place.
            const auto request = RequestFor(ref, context, fixture->library);
            Check(request && !hlsl.EvaluateReference(*request, {}).has_value(),
                  "the candidate lane evaluates nothing: " + name + ", " + c.what);
        }
        // Inside the domain the uncertified asset is still refused before mutation.
        {
            auto [ref, context] = baseline();
            const auto refused = SetGrungeSource(maskFill, std::nullopt, ref, context, fixture->library, seam, submit);
            Check(!refused && refused.error().reason == kNotCertified && submits == 0 && document.revision() == 0,
                  "inside the domain the uncertified grunge is refused before mutation (family not certified): " + name,
                  refused ? "admitted" : refused.error().Describe());
        }
    }
    // An admitted edit (a snapshot with the exact signature) commits the reference as given: the
    // mono source of the mask's fill effect, then the Roughness source of the fill layer.
    {
        AdmitAll snapshots;
        ProceduralSeam admitting(&snapshots, &hlsl);
        core::ProceduralRef ref;
        ref.asset = core::FormatAssetUrl(fixture->records.front()->asset);
        ref.params["tiling"] = json::Value(int64_t{3});
        UseContext context;
        context.meshClass = "sphere";
        context.output = RasterSpec{1024, ChannelFormat::F32, "linear", 1};
        const auto mono = SetGrungeSource(maskFill, std::nullopt, ref, context, fixture->library, admitting, submit);
        const auto channel =
            SetGrungeSource(layer, core::ChannelType::Roughness, ref, context, fixture->library, admitting, submit);
        const core::Project now = *document.snapshot().project;
        const core::Layer* fill = core::FindLayer(now, layer);
        const auto stored = [&](const std::optional<core::Source>& source) {
            return source && std::get_if<core::ProceduralSource>(&source->value) != nullptr &&
                   std::get<core::ProceduralSource>(source->value).ref == ref;
        };
        const bool monoStored = fill != nullptr && fill->mask && fill->mask->effects.size() == 1 &&
                                fill->mask->effects.front().fill && stored(fill->mask->effects.front().fill->mono_source);
        const bool channelStored = fill != nullptr && fill->fill && fill->fill->sources.size() == 1 &&
                                   fill->fill->sources.contains(core::ChannelType::Roughness) &&
                                   stored(fill->fill->sources.at(core::ChannelType::Roughness));
        const auto committed = [](const auto& outcome) {
            return outcome && outcome->result && outcome->result->status == core::ResultStatus::committed;
        };
        Check(committed(mono) && committed(channel) && submits == 2 && document.revision() == 2 && monoStored &&
                  channelStored,
              "an admitted grunge source commits the reference as given, as a mask fill's source and a channel's",
              !mono      ? mono.error().Describe()
              : !channel ? channel.error().Describe()
              : !committed(mono) || !committed(channel)
                  ? std::string("not committed: ") + (mono->result ? mono->result->error : "") + " / " +
                        (channel->result ? channel->result->error : "")
                  : "not stored as given");
    }
    return Finish();
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 4) {
        std::fprintf(stderr,
                     "usage: uzp-proc-grunge-tests families | tiling | seeds | domain | kernels | gpu <work-dir> "
                     "<shipped-library>\n");
        return 2;
    }
    const std::string_view mode = argv[1];
    const fs::path dir = argv[2];
    const fs::path shipped = argv[3];
    if (mode == "families") return RunFamilies(shipped);
    if (mode == "tiling") return RunTiling(shipped);
    if (mode == "seeds") return RunSeeds(shipped);
    if (mode == "domain") return RunDomain(shipped);
    if (mode == "kernels") return RunKernels(dir, shipped);
    if (mode == "gpu") return RunGpu(dir, shipped);
    std::fprintf(stderr, "unknown case %.*s\n", static_cast<int>(mode.size()), mode.data());
    return 2;
}
