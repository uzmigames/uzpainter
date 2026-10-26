// Native tests of the procedural backend seam, the HlslBackend host and the shared primitive
// library (src/procedural/, rulebook task phase3.1_proc-backend-seam items 2.1-2.3, 3.3 and
// 3.6 at the seam). Built by `zig build procedural-tests` and driven by
// tests/procedural/test_proc_backend_seam.py.
//
// Usage: uzp-procedural-tests <case> <work-dir>
//   seam            backend order, refusals before evaluation, no substitution (CPU)
//   domain          the certified-domain check, field by field (CPU)
//   primitives      the primitive library against public expectations (CPU)
//   kernels         every probe kernel compiled to DXIL and SPIR-V through the kernel cache;
//                   the cache key ignores parameter values (CPU, needs dxcompiler.dll)
//   gpu             every probe family on DX12 equal to the CPU reference bit for bit, twice,
//                   whole and by tile, and the seam's certified path end to end (GPU)
//   library <work-dir> <fixture-library> <shipped-library>
//                   the asset library: exact pins, the alias table, resource.search's query
//                   terms and the project's pins (CPU; item 2.4)
//   library-load <work-dir> <library>
//                   loads one library and prints `LOADED <records> <aliases>` (exit 0) or
//                   `REFUSED <reason>` (exit 1): the load checks (CPU)
//   assets-cli <work-dir> <fixture-library> <shipped-library>
//                   `UzPainter.exe assets list [--parity]` (RunAssetsCommand) on both libraries,
//                   a broken one and the usage errors (CPU; item 2.5)
//   admission <work-dir> <fixture-library>
//                   procedural edits through the seam on a stored project: refusals before
//                   mutation, a snapshot-served request, the certified path, and the same
//                   evaluation after save and reopen (CPU; items 3.1, 3.4, 3.6)
//   snapshot <work-dir>
//                   SnapshotBackend on stored projects (phase3.2_proc-snapshot-backend): the
//                   signature, exact-signature serving, each field mismatch unavailable, the
//                   `.uzp` planes through save/reopen, `inspect --verify` and `export-bundle`,
//                   and no copy into another project (CPU; items 2.1-2.4, 3.2-3.4)
//
// The families here are test probes with authored formulas: none is a Painter asset, and the
// one whose status is `exact` is a synthetic test double of the seam's certified path.
//
// Output: `PASS <check>` / `FAIL <check>: <detail>` / `INFO` lines.
// Exit code 0 when every check passed, 1 when one failed, 2 on a usage error, 77 when the case
// needs a DX12 hardware adapter and there is none.

#include "procedural/admission.h"
#include "procedural/asset_library.h"
#include "procedural/filter_observation_source.h"
#include "procedural/cli.h"
#include "procedural/hlsl_backend.h"
#include "procedural/primitives.h"
#include "procedural/seam.h"
#include "procedural/snapshot_backend.h"
#include "procedural/snapshot_recording.h"
#include "export/exr_writer.h"
#include "store/bundle_codec.h"

#include "render/engine_thread.h"
#include "render/kernel_cache.h"

#include "store/bundle.h"
#include "store/inspect.h"
#include "store/project_store.h"
#include "store/snapshots.h"
#include "store/filter_observations.h"
#include "uzp_core/document/document.h"
#include "uzp_core/operation/operation.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/manifest/manifest.h"
#include "uzp_core/types/project.h"
#include "uzp_core/types/errors.h"

#include <algorithm>
#include <bit>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iterator>
#include <limits>
#include <memory>
#include <random>
#include <string>
#include <string_view>
#include <vector>
#include "procedural/snapshot_source.h"
#include "../filter_observation_v2_fixture.h"  // decision 363: the authored V2 fixture
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

void Info(const std::string& text) {
    std::printf("INFO %s\n", text.c_str());
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
            first = "texel (" + std::to_string(texel % a.width) + ", " +
                    std::to_string(texel / a.width) + ") channel " +
                    std::to_string(i % a.channels) + ": " + Hex(Bits(a.texels[i])) + " against " +
                    Hex(Bits(b.texels[i]));
        }
    }
    return count == 0 ? std::string() : std::to_string(count) + " values differ, first at " + first;
}

// ── Probe families (authored test formulas, never Painter assets) ────────────

uzp::core::AssetUrl Url(std::string family, std::string id, std::string version) {
    return uzp::core::AssetUrl{std::move(family), std::move(id), std::move(version)};
}

float F(const Params& params, const std::string& name) {
    const ParamValue& v = params.at(name);
    if (const auto* d = std::get_if<double>(&v)) return static_cast<float>(*d);
    return static_cast<float>(std::get<int64_t>(v));
}

uint32_t U(const Params& params, const std::string& name) {
    const ParamValue& v = params.at(name);
    if (const auto* i = std::get_if<int64_t>(&v)) return static_cast<uint32_t>(*i);
    return static_cast<uint32_t>(std::get<double>(v));
}

/// Primitive codes of the noise probe.
enum NoiseCode : uint32_t {
    kPerlin1985 = 0,
    kPerlin2002 = 1,
    kSimplex = 2,
    kWorleyEuclidean = 3,
    kWorleyManhattan = 4,
    kWorleyChebyshev = 5,
    kFbm = 6,
    kSqrt = 7,
};

/// The probe's point of texel (x, y): ((x + 1/2) scale + ox, (y + 1/2) scale + oy, oz).
prim::Vec3 ProbePoint(int32_t x, int32_t y, float scale, float ox, float oy, float oz) {
    using namespace prim;
    const float px = Add(Mul(Add(static_cast<float>(x), 0.5f), scale), ox);
    const float py = Add(Mul(Add(static_cast<float>(y), 0.5f), scale), oy);
    return Vec3{px, py, oz};
}

/// The noise probe's texel: (value, second value, cell, 1) of the selected primitive.
std::array<float, 4> NoiseTexel(uint32_t code, prim::Vec3 p, uint32_t seed, uint32_t basis,
                                uint32_t octaves, float lacunarity, float gain) {
    using namespace prim;
    switch (code) {
        case kPerlin1985: return {Perlin1985(p, seed), 0.0f, 0.0f, 1.0f};
        case kPerlin2002: return {Perlin2002(p, seed), 0.0f, 0.0f, 1.0f};
        case kSimplex: return {Simplex3(p, seed), 0.0f, 0.0f, 1.0f};
        case kWorleyEuclidean:
        case kWorleyManhattan:
        case kWorleyChebyshev: {
            const WorleyResult r =
                Worley3(p, seed, static_cast<WorleyMetric>(code - kWorleyEuclidean));
            return {r.f1, r.f2, static_cast<float>(r.cell >> 8), 1.0f};
        }
        case kFbm:
            return {Fbm(static_cast<FbmBasis>(basis), p, seed, octaves, lacunarity, gain), 0.0f,
                    0.0f, 1.0f};
        default: {
            const float d = Add(Add(Mul(p.x, p.x), Mul(p.y, p.y)), Mul(p.z, p.z));
            return {SqrtRn(d), SqrtRn(p.x), SqrtRn(Sub(0.0f, p.x)), 1.0f};
        }
    }
}

constexpr std::string_view kNoiseBody = R"(
float4 ProcTexel(int2 texel) {
    const uint code = ProcParam(0);
    const float scale = asfloat(ProcParam(1));
    const float ox = asfloat(ProcParam(2));
    const float oy = asfloat(ProcParam(3));
    const float oz = asfloat(ProcParam(4));
    const uint basis = ProcParam(5);
    const uint octaves = ProcParam(6);
    const float lacunarity = asfloat(ProcParam(7));
    const float gain = asfloat(ProcParam(8));
    const float3 p = float3(Add(Mul(Add(float(texel.x), 0.5f), scale), ox),
                            Add(Mul(Add(float(texel.y), 0.5f), scale), oy), oz);
    if (code == 0u) return float4(Perlin1985(p, g_seed), 0.0f, 0.0f, 1.0f);
    if (code == 1u) return float4(Perlin2002(p, g_seed), 0.0f, 0.0f, 1.0f);
    if (code == 2u) return float4(Simplex3(p, g_seed), 0.0f, 0.0f, 1.0f);
    if (code >= 3u && code <= 5u) {
        const WorleyResult r = Worley3(p, g_seed, code - 3u);
        return float4(r.f1, r.f2, float(r.cell >> 8), 1.0f);
    }
    if (code == 6u) return float4(Fbm(basis, p, g_seed, octaves, lacunarity, gain), 0.0f, 0.0f, 1.0f);
    const float d = Add(Add(Mul(p.x, p.x), Mul(p.y, p.y)), Mul(p.z, p.z));
    return float4(SqrtRn(d), SqrtRn(p.x), SqrtRn(Sub(0.0f, p.x)), 1.0f);
}
)";

RasterRule F32Output(std::vector<uint32_t> resolutions, std::vector<uint32_t> channels) {
    return RasterRule{std::move(resolutions), {ChannelFormat::F32}, {"linear"}, std::move(channels)};
}

ParamRule Range(double low, double high) { return ParamRule{std::pair{low, high}, {}}; }

ParamRule Set(std::vector<int64_t> values) {
    ParamRule rule;
    for (const int64_t v : values) rule.set.push_back(v);
    return rule;
}

class NoiseProbe final : public IHlslFamily {
public:
    explicit NoiseProbe(ParityStatus status) {
        m_record.asset = Url("test-probe", "noise", "1");
        m_record.status = std::move(status);
        m_record.provenance = "tests/procedural/procedural_test.cpp (authored probe)";
        CertifiedDomain& d = m_record.domain;
        d.parameters["primitive"] = Set({0, 1, 2, 3, 4, 5, 6, 7});
        d.parameters["scale"] = Range(1.0 / 1024, 64.0);
        d.parameters["offset_x"] = Range(-4096.0, 4096.0);
        d.parameters["offset_y"] = Range(-4096.0, 4096.0);
        d.parameters["offset_z"] = Range(-4096.0, 4096.0);
        d.parameters["basis"] = Set({0, 1, 2, 3});
        d.parameters["octaves"] = Set({1, 2, 3, 4, 5, 6, 7, 8});
        d.parameters["lacunarity"] = Range(1.0, 4.0);
        d.parameters["gain"] = Range(0.0, 1.0);
        d.meshClasses = {"synthetic"};
        d.output = F32Output({8, 16, 33, 64, 128}, {4});
    }

    const FamilyRecord& Record() const override { return m_record; }

    std::vector<KernelPass> Plan(const ProceduralRequest& r) const override {
        KernelPass pass;
        pass.name = "noise_probe";
        pass.body = std::string(kNoiseBody);
        pass.params = {U(r.params, "primitive"), Bits(F(r.params, "scale")),
                       Bits(F(r.params, "offset_x")), Bits(F(r.params, "offset_y")),
                       Bits(F(r.params, "offset_z")), U(r.params, "basis"),
                       U(r.params, "octaves"), Bits(F(r.params, "lacunarity")),
                       Bits(F(r.params, "gain"))};
        return {pass};
    }

    Raster Reference(const ProceduralRequest& r, const InputImages&) const override {
        const TileRect tile = r.tile.width ? r.tile
                                           : TileRect{0, 0, r.output.resolution, r.output.resolution};
        Raster out{tile.width, tile.height, 4, {}};
        for (uint32_t y = 0; y < tile.height; ++y) {
            for (uint32_t x = 0; x < tile.width; ++x) {
                const prim::Vec3 p = ProbePoint(static_cast<int32_t>(tile.x + x),
                                                static_cast<int32_t>(tile.y + y),
                                                F(r.params, "scale"), F(r.params, "offset_x"),
                                                F(r.params, "offset_y"), F(r.params, "offset_z"));
                const auto t = NoiseTexel(U(r.params, "primitive"), p,
                                          static_cast<uint32_t>(r.seed), U(r.params, "basis"),
                                          U(r.params, "octaves"), F(r.params, "lacunarity"),
                                          F(r.params, "gain"));
                out.texels.insert(out.texels.end(), t.begin(), t.end());
            }
        }
        return out;
    }

private:
    FamilyRecord m_record;
};

constexpr std::string_view kMorphBody = R"(
float4 ProcTexel(int2 texel) {
    const uint op = ProcParam(0);
    const int radius = int(ProcParam(1));
    const uint footprint = ProcParam(2);
    const uint border = ProcParam(3);
    if (op == 0u) return Dilate(0u, texel, radius, footprint, border);
    return Erode(0u, texel, radius, footprint, border);
}
)";

constexpr std::string_view kBlurBody = R"(
float4 ProcTexel(int2 texel) {
    return BlurPass(0u, texel, 3u, ProcParam(0), ProcParam(1) != 0u, ProcParam(2));
}
)";

/// The image-operator probe: dilate, erode, box blur or Gaussian blur of input "image".
class ImageProbe final : public IHlslFamily {
public:
    ImageProbe() {
        m_record.asset = Url("test-probe", "image", "1");
        m_record.status = ParityStatus::Unavailable("authored test probe");
        m_record.provenance = "tests/procedural/procedural_test.cpp (authored probe)";
        CertifiedDomain& d = m_record.domain;
        d.parameters["op"] = Set({0, 1, 2, 3});
        d.parameters["radius"] = Set({0, 1, 2, 3, 5, 8});
        d.parameters["footprint"] = Set({0, 1});
        d.parameters["border"] = Set({0, 1});
        d.parameters["sigma"] = Range(0.25, 16.0);
        d.meshClasses = {"synthetic"};
        d.inputs["image"] = F32Output({16, 32, 37}, {1, 2, 4});
        d.inputs["image"].colourSpaces = {"linear"};
        d.output = F32Output({16, 32, 37}, {1, 2, 4});
    }

    const FamilyRecord& Record() const override { return m_record; }

    std::vector<float> Weights(const ProceduralRequest& r) const {
        const uint32_t radius = U(r.params, "radius");
        return U(r.params, "op") == 2 ? prim::BoxWeights(radius)
                                      : prim::GaussianWeights(F(r.params, "sigma"), radius);
    }

    std::vector<KernelPass> Plan(const ProceduralRequest& r) const override {
        const uint32_t op = U(r.params, "op");
        const uint32_t border = U(r.params, "border");
        if (op <= 1) {
            KernelPass pass{"morph_probe", std::string(kMorphBody),
                            {op, U(r.params, "radius"), U(r.params, "footprint"), border},
                            {PassInput{"image", -1}}};
            return {pass};
        }
        const std::vector<float> weights = Weights(r);
        const auto block = [&](bool horizontal) {
            std::vector<uint32_t> words = {static_cast<uint32_t>(weights.size()),
                                           horizontal ? 1u : 0u, border};
            for (const float w : weights) words.push_back(Bits(w));
            return words;
        };
        KernelPass horizontal{"blur_h_probe", std::string(kBlurBody), block(true),
                              {PassInput{"image", -1}}};
        KernelPass vertical{"blur_v_probe", std::string(kBlurBody), block(false),
                            {PassInput{"", 0}}};
        return {horizontal, vertical};
    }

    Raster Reference(const ProceduralRequest& r, const InputImages& inputs) const override {
        const Raster& image = inputs.at("image");
        const uint32_t op = U(r.params, "op");
        const auto border = static_cast<prim::Border>(U(r.params, "border"));
        const auto footprint = static_cast<prim::Footprint>(U(r.params, "footprint"));
        Raster whole;
        if (op == 0) whole = prim::Dilate(image, U(r.params, "radius"), footprint, border);
        else if (op == 1) whole = prim::Erode(image, U(r.params, "radius"), footprint, border);
        else whole = prim::SeparableBlur(image, Weights(r), border);
        // The output keeps the request's channels (the GPU reads its first channels back).
        const TileRect tile = r.tile.width ? r.tile
                                           : TileRect{0, 0, r.output.resolution, r.output.resolution};
        Raster out{tile.width, tile.height, r.output.channels, {}};
        for (uint32_t y = 0; y < tile.height; ++y) {
            for (uint32_t x = 0; x < tile.width; ++x) {
                for (uint32_t c = 0; c < r.output.channels; ++c) {
                    out.texels.push_back(
                        c < whole.channels
                            ? whole.texels[(size_t{tile.y + y} * whole.width + tile.x + x) *
                                               whole.channels + c]
                            : 0.0f);
                }
            }
        }
        return out;
    }

private:
    FamilyRecord m_record;
};

ProceduralRequest NoiseRequest(uint32_t primitive, uint32_t resolution, uint64_t seed) {
    ProceduralRequest r;
    r.asset = Url("test-probe", "noise", "1");
    r.params = {{"primitive", int64_t{primitive}}, {"scale", 0.37},       {"offset_x", -3.25},
                {"offset_y", 1.75},                {"offset_z", 0.5},     {"basis", int64_t{1}},
                {"octaves", int64_t{5}},           {"lacunarity", 2.0},   {"gain", 0.5}};
    r.meshClass = "synthetic";
    r.output = RasterSpec{resolution, ChannelFormat::F32, "linear", 4};
    r.seed = seed;
    return r;
}

Raster TestImage(uint32_t size, uint32_t channels, uint32_t seed) {
    std::mt19937 rng(seed);
    std::uniform_real_distribution<float> unit(-2.0f, 2.0f);
    Raster image{size, size, channels, {}};
    for (size_t i = 0; i < size_t{size} * size * channels; ++i) image.texels.push_back(unit(rng));
    // A subnormal, a negative zero and an exact tie, so the flush and the strict comparisons
    // are exercised.
    image.texels[0] = std::bit_cast<float>(0x00000F00u);
    image.texels[1] = -0.0f;
    image.texels[2] = image.texels[3];
    return image;
}

ProceduralRequest ImageRequest(uint32_t op, uint32_t radius, uint32_t footprint, uint32_t border,
                               uint32_t size, uint32_t channels) {
    ProceduralRequest r;
    r.asset = Url("test-probe", "image", "1");
    r.params = {{"op", int64_t{op}},           {"radius", int64_t{radius}},
                {"footprint", int64_t{footprint}}, {"border", int64_t{border}},
                {"sigma", 1.5}};
    r.meshClass = "synthetic";
    r.inputs["image"] = ImageInput{RasterSpec{size, ChannelFormat::F32, "linear", channels},
                                   std::string(64, 'a')};
    r.output = RasterSpec{size, ChannelFormat::F32, "linear", channels};
    return r;
}

// ── seam ─────────────────────────────────────────────────────────────────────

/// A snapshot backend test double: serves exactly the signatures it holds, and counts what it
/// evaluates.
class FakeSnapshots final : public IProceduralBackend {
public:
    std::map<std::string, Raster> rasters;  ///< By signature hash.
    int evaluations = 0;

    std::string_view Name() const override { return "snapshot"; }
    ParityStatus Status(const uzp::core::AssetUrl&) const override {
        return ParityStatus::Unavailable("snapshots are migration data");
    }
    bool CanEvaluate(const ProceduralRequest& request) const override {
        return rasters.contains(SignatureHash(request));
    }
    std::optional<UnsupportedProcedural> Refusal(const ProceduralRequest& request) const override {
        if (CanEvaluate(request)) return std::nullopt;
        return Refuse(AssetName(request), "no snapshot with this signature");
    }
    RasterFuture Evaluate(const ProceduralRequest& request, const InputImages&) override {
        ++evaluations;
        std::promise<render::Result<Raster>> promise;
        promise.set_value(rasters.at(SignatureHash(request)));
        return promise.get_future();
    }
};

/// A synthetic family the test declares `exact`, so the seam's certified path can be exercised.
class SyntheticExact final : public IHlslFamily {
public:
    mutable int plans = 0;
    mutable int references = 0;

    explicit SyntheticExact(uzp::core::AssetUrl asset = Url("test-synthetic", "ridge", "2")) {
        m_record.asset = std::move(asset);
        m_record.status.kind = ParityStatus::Kind::Exact;
        m_record.status.corpusIds = {"synthetic-calibration", "synthetic-held-out"};
        m_record.provenance = "tests/procedural/procedural_test.cpp (synthetic test double)";
        CertifiedDomain& d = m_record.domain;
        d.parameters["amount"] = Range(0.0, 1.0);
        d.parameters["bias"] = Range(-1.0, 1.0);
        d.parameters["mode"] = Set({0, 1});
        d.constraints = {LinearConstraint{{{"amount", 1.0}, {"bias", 1.0}}, 1.25}};
        d.anySeed = false;
        d.seeds = {7, 11};
        d.meshClasses = {"sphere", "bevelled-cube"};
        d.inputs["Curvature"] = RasterRule{{64}, {ChannelFormat::U16}, {"linear"}, {1}};
        d.output = F32Output({64}, {1});
    }

    const FamilyRecord& Record() const override { return m_record; }

    std::vector<KernelPass> Plan(const ProceduralRequest& r) const override {
        ++plans;
        KernelPass pass;
        pass.name = "synthetic_ridge";
        pass.body = R"(
float4 ProcTexel(int2 texel) {
    const float amount = asfloat(ProcParam(0));
    const float c = Ftz(ProcInput(0u, texel).x);
    return float4(Add(Mul(Perlin2002(float3(Mul(float(texel.x), 0.125f), Mul(float(texel.y), 0.125f), 0.0f), g_seed), amount), c), 0.0f, 0.0f, 0.0f);
}
)";
        pass.params = {Bits(F(r.params, "amount"))};
        pass.inputs = {PassInput{"Curvature", -1}};
        return {pass};
    }

    Raster Reference(const ProceduralRequest& r, const InputImages& inputs) const override {
        using namespace prim;
        ++references;
        const Raster& curvature = inputs.at("Curvature");
        Raster out{64, 64, 1, {}};
        for (uint32_t y = 0; y < 64; ++y) {
            for (uint32_t x = 0; x < 64; ++x) {
                const float n = Perlin2002(Vec3{Mul(static_cast<float>(x), 0.125f),
                                                Mul(static_cast<float>(y), 0.125f), 0.0f},
                                           static_cast<uint32_t>(r.seed));
                const float c = Ftz(curvature.texels[size_t{y} * 64 + x]);
                out.texels.push_back(Add(Mul(n, F(r.params, "amount")), c));
            }
        }
        return out;
    }

private:
    FamilyRecord m_record;
};

ProceduralRequest SyntheticRequest() {
    ProceduralRequest r;
    r.asset = Url("test-synthetic", "ridge", "2");
    r.params = {{"amount", 0.5}, {"bias", -0.25}, {"mode", int64_t{1}}};
    r.meshClass = "sphere";
    r.inputs["Curvature"] =
        ImageInput{RasterSpec{64, ChannelFormat::U16, "linear", 1}, std::string(64, 'c')};
    r.output = RasterSpec{64, ChannelFormat::F32, "linear", 1};
    r.seed = 7;
    return r;
}

Raster Curvature() {
    Raster image{64, 64, 1, {}};
    for (uint32_t i = 0; i < 64 * 64; ++i) image.texels.push_back(static_cast<float>(i % 97) / 96.0f);
    return image;
}

std::string Describe(const std::expected<IProceduralBackend*, UnsupportedProcedural>& selected) {
    return selected ? "served by " + std::string((*selected)->Name()) : selected.error().Describe();
}

int RunSeam() {
    auto synthetic = std::make_shared<SyntheticExact>();
    HlslBackend hlsl(nullptr);
    Check(hlsl.Register(synthetic).has_value(), "a certified synthetic family registers");
    Check(hlsl.Register(std::make_shared<NoiseProbe>(ParityStatus::Unavailable("probe")))
              .has_value(),
          "an uncertified probe family registers");
    Check(!hlsl.Register(std::make_shared<NoiseProbe>(ParityStatus::Unavailable("probe")))
               .has_value(),
          "a second family for the same pinned asset is refused");
    FakeSnapshots snapshots;
    ProceduralSeam seam(&snapshots, &hlsl);

    // An uncertified asset: no snapshot, no family. Refused, nothing evaluated, nothing else
    // served in its place (the probe and the synthetic family stay unplanned).
    ProceduralRequest unknown = SyntheticRequest();
    unknown.asset = Url("painter-generator", "metal-edge-wear", "1");
    const auto refused = seam.Select(unknown);
    Check(!refused && refused.error().reason == kNoBackend &&
              refused.error().asset == "uzasset://painter-generator/metal-edge-wear@1",
          "an asset with no snapshot and no family raises UnsupportedProcedural", Describe(refused));
    const auto evaluated = seam.Evaluate(unknown, {{"Curvature", Curvature()}});
    Check(!evaluated && snapshots.evaluations == 0 && synthetic->plans == 0 &&
              synthetic->references == 0,
          "the refusal evaluates nothing and substitutes no other asset");

    // A registered family whose status is not exact is never served by the seam.
    ProceduralRequest probe = NoiseRequest(kPerlin2002, 16, 3);
    const auto uncertified = seam.Select(probe);
    Check(!uncertified && uncertified.error().reason == kNotCertified &&
              uncertified.error().value == "unavailable",
          "a family whose status is unavailable is refused (family not certified)",
          Describe(uncertified));
    ProceduralRequest probeOther = probe;
    probeOther.asset.version = "2";
    const auto otherVersion = seam.Select(probeOther);
    Check(!otherVersion && otherVersion.error().reason == kNoBackend,
          "another version of a registered asset is not served by it", Describe(otherVersion));

    // The certified path: inside the domain the HLSL backend serves it.
    const ProceduralRequest inside = SyntheticRequest();
    const auto served = seam.Select(inside);
    Check(served && *served == &hlsl, "inside the domain the certified family is selected",
          Describe(served));
    Check(hlsl.Status(inside.asset).kind == ParityStatus::Kind::Exact &&
              hlsl.Status(unknown.asset).kind == ParityStatus::Kind::Unavailable,
          "status: exact for the certified family, unavailable for an unknown asset");

    // Snapshot first: a snapshot holding the exact signature wins over the family.
    Raster stored{64, 64, 1, std::vector<float>(64 * 64, 0.25f)};
    snapshots.rasters[SignatureHash(inside)] = stored;
    const auto first = seam.Select(inside);
    Check(first && *first == &snapshots, "a snapshot with the exact signature is tried first",
          Describe(first));
    snapshots.rasters.clear();

    // A GPU-less HLSL backend fails loudly, a missing image input fails loudly, and the CPU
    // reference lane serves the certified family.
    auto noGpu = seam.Evaluate(inside, {{"Curvature", Curvature()}});
    const render::Result<Raster> noGpuResult = noGpu ? noGpu->get() : render::Result<Raster>{};
    Check(noGpu && !noGpuResult &&
              noGpuResult.error().code == render::ErrorCode::GpuBackendUnavailable,
          "without a GPU engine the evaluation fails with gpu_backend_unavailable");
    RasterFuture missingFuture = hlsl.EvaluateCandidate(inside, {});
    const render::Result<Raster> missingResult = missingFuture.get();
    Check(!missingResult && missingResult.error().reason.find("Curvature is missing") != std::string::npos,
          "a missing mesh map fails the evaluation loudly",
          missingResult ? "evaluated" : missingResult.error().Describe());
    Raster wrong = Curvature();
    wrong.width = 32;
    const render::Result<Raster> invalid = hlsl.EvaluateReference(inside, {{"Curvature", wrong}});
    Check(!invalid && invalid.error().reason.find("Curvature is invalid") != std::string::npos,
          "an invalid mesh map (wrong size) fails the evaluation loudly",
          invalid ? "evaluated" : invalid.error().Describe());
    const render::Result<Raster> reference = hlsl.EvaluateReference(inside, {{"Curvature", Curvature()}});
    Check(reference && reference->width == 64 && reference->channels == 1,
          "the CPU reference lane evaluates the certified family",
          reference ? "" : reference.error().Describe());

    // Signatures: numbers by value, the tile excluded, every other field included.
    ProceduralRequest same = inside;
    same.params["mode"] = 1.0;
    same.tile = TileRect{0, 0, 32, 32};
    Check(SignatureHash(same) == SignatureHash(inside),
          "the signature compares numbers by value (1 == 1.0) and leaves the tile out");
    ProceduralRequest moved = inside;
    moved.inputs["Curvature"].sha256 = std::string(64, 'd');
    ProceduralRequest reseeded = inside;
    reseeded.seed = 11;
    Check(SignatureHash(moved) != SignatureHash(inside) &&
              SignatureHash(reseeded) != SignatureHash(inside),
          "the signature covers the input hashes and the seed");
    Info("signature " + Signature(inside));
    return Finish();
}

// ── domain (3.6 at the seam) ─────────────────────────────────────────────────

int RunDomain() {
    auto synthetic = std::make_shared<SyntheticExact>();
    HlslBackend hlsl(nullptr);
    (void)hlsl.Register(synthetic);
    FakeSnapshots snapshots;
    ProceduralSeam seam(&snapshots, &hlsl);
    const ProceduralRequest inside = SyntheticRequest();
    Check(!CheckDomain(inside, synthetic->Record().domain), "the reference request is inside");

    struct Outside {
        std::string what;
        ProceduralRequest request;
        std::string field;
        std::string value;
        std::string certified;
    };
    std::vector<Outside> cases;
    const auto add = [&](std::string what, auto edit, std::string field, std::string value,
                         std::string certified) {
        ProceduralRequest r = inside;
        edit(r);
        cases.push_back({std::move(what), std::move(r), std::move(field), std::move(value),
                         std::move(certified)});
    };
    add("a parameter one ulp above its range",
        [](ProceduralRequest& r) { r.params["amount"] = std::nextafter(1.0, 2.0); }, "params.amount",
        "1.0000000000000002", "[0, 1]");
    add("a parameter one ulp below its range",
        [](ProceduralRequest& r) { r.params["bias"] = std::nextafter(-1.0, -2.0); }, "params.bias",
        "-1.0000000000000002", "[-1, 1]");
    add("a set parameter outside its set", [](ProceduralRequest& r) { r.params["mode"] = int64_t{2}; },
        "params.mode", "2", "[0, 1]");
    add("a missing parameter", [](ProceduralRequest& r) { r.params.erase("bias"); }, "params.bias",
        "missing", "every declared parameter");
    add("an undeclared parameter", [](ProceduralRequest& r) { r.params["extra"] = 0.0; },
        "params.extra", "0", "not a parameter");
    add("a joint constraint exceeded by one ulp",
        [](ProceduralRequest& r) {
            r.params["amount"] = 1.0;
            r.params["bias"] = std::nextafter(0.25, 1.0);
        },
        "params", "{amount: 1, bias: 0.25000000000000006}", "1 amount + 1 bias <= 1.25");
    add("a seed next to the listed ones", [](ProceduralRequest& r) { r.seed = 8; }, "seed", "8",
        "[7, 11]");
    add("a seed above 32 bits", [](ProceduralRequest& r) { r.seed = 0x100000000ull; }, "seed",
        "4294967296", "[0, 4294967295]");
    add("an uncertified mesh class", [](ProceduralRequest& r) { r.meshClass = "hat-v6-low"; },
        "mesh.class", "\"hat-v6-low\"", "[\"sphere\", \"bevelled-cube\"]");
    add("two UV tiles", [](ProceduralRequest& r) { r.uvTiles = 2; }, "mesh.uv_tiles", "2", "1");
    add("a missing mesh map", [](ProceduralRequest& r) { r.inputs.erase("Curvature"); },
        "inputs.Curvature", "missing", "a declared input");
    add("an undeclared mesh map",
        [](ProceduralRequest& r) {
            r.inputs["AO"] = ImageInput{RasterSpec{64, ChannelFormat::U16, "linear", 1}, "x"};
        },
        "inputs.AO", "present", "not an input of the domain");
    add("a mesh map one resolution step above",
        [](ProceduralRequest& r) { r.inputs["Curvature"].spec.resolution = 128; },
        "inputs.Curvature.resolution", "128", "[64]");
    add("a mesh map in another format",
        [](ProceduralRequest& r) { r.inputs["Curvature"].spec.format = ChannelFormat::U8; },
        "inputs.Curvature.format", "\"u8\"", "[\"u16\"]");
    add("a mesh map in another colour space",
        [](ProceduralRequest& r) { r.inputs["Curvature"].spec.colourSpace = "srgb"; },
        "inputs.Curvature.colour_space", "\"srgb\"", "[\"linear\"]");
    add("an output resolution one step above",
        [](ProceduralRequest& r) { r.output.resolution = 128; }, "output.resolution", "128",
        "[64]");
    add("an output resolution one texel below",
        [](ProceduralRequest& r) { r.output.resolution = 63; }, "output.resolution", "63",
        "[64]");
    add("an output channel count outside",
        [](ProceduralRequest& r) { r.output.channels = 2; }, "output.channels", "2", "[1]");
    add("a preset the domain does not certify", [](ProceduralRequest& r) { r.preset = "Rusty"; },
        "preset", "\"Rusty\"", "[]");
    add("a tile outside the texture", [](ProceduralRequest& r) { r.tile = TileRect{48, 0, 32, 16}; },
        "tile", "[48, 0, 32, 16]", "a non-empty rectangle inside the 64 texel output");

    for (const Outside& c : cases) {
        const auto selected = seam.Select(c.request);
        const bool ok = !selected && selected.error().reason == kOutsideDomain &&
                        selected.error().field == c.field && selected.error().value == c.value &&
                        selected.error().certified == c.certified;
        Check(ok, "outside the domain: " + c.what, Describe(selected));
    }
    for (const Outside& c : cases) (void)seam.Evaluate(c.request, {{"Curvature", Curvature()}});
    Check(synthetic->plans == 0 && synthetic->references == 0 && snapshots.evaluations == 0,
          "no refused request is planned or evaluated by any backend (nothing clamped, nothing "
          "substituted)",
          std::to_string(synthetic->plans) + " plans, " + std::to_string(synthetic->references) +
              " references, " + std::to_string(snapshots.evaluations) + " snapshot evaluations");

    // The constraint is judged exactly: at the bound it holds, one ulp above it does not.
    ProceduralRequest bound = inside;
    bound.params["amount"] = 1.0;
    bound.params["bias"] = 0.25;
    Check(!CheckDomain(bound, synthetic->Record().domain),
          "a joint constraint met with equality is inside");
    ProceduralRequest tenths = inside;
    LinearConstraint tight{{{"amount", 1.0}, {"bias", 1.0}}, 0.3};
    CertifiedDomain exactDomain = synthetic->Record().domain;
    exactDomain.constraints = {tight};
    tenths.params["amount"] = 0.1;
    tenths.params["bias"] = 0.2;
    // Exactly, double(0.1) + double(0.2) = 0.3000000000000000166533453693773481063544750213623046875
    // and double(0.3) = 0.299999999999999988897769753748434595763683319091796875.
    Check(CheckDomain(tenths, exactDomain).has_value(),
          "the exact sum of 0.1 and 0.2 exceeds 0.3 (no rounding decides the constraint)");

    // A project snapshot with an out-of-domain request's exact signature is still served.
    const Outside& kept = cases.front();
    Raster stored{64, 64, 1, std::vector<float>(64 * 64, 0.75f)};
    snapshots.rasters[SignatureHash(kept.request)] = stored;
    auto snapshot = seam.Evaluate(kept.request, {});
    const render::Result<Raster> snapshotRaster = snapshot ? snapshot->get() : render::Result<Raster>{};
    Check(snapshot && snapshotRaster && *snapshotRaster == stored && snapshots.evaluations == 1 &&
              synthetic->plans == 0,
          "an out-of-domain request whose exact signature has a project snapshot is served by "
          "the snapshot, and only by it");
    ProceduralRequest near = kept.request;
    near.params["amount"] = std::nextafter(std::nextafter(1.0, 2.0), 2.0);
    Check(!seam.Select(near).has_value(), "a snapshot does not widen the domain to a nearby value");
    return Finish();
}

// ── primitives (3.3, CPU lane) ───────────────────────────────────────────────

int RunPrimitives() {
    using namespace prim;
    // SqrtRn is IEEE 754 squareRoot: compared with the host's correctly rounded sqrt.
    std::mt19937 rng(20261019);
    size_t sqrtMismatch = 0;
    std::string firstSqrt;
    const auto checkSqrt = [&](float x) {
        const float want = Ftz(std::sqrt(x));
        const float got = SqrtRn(x);
        const bool same = Bits(got) == Bits(want) || (std::isnan(got) && std::isnan(want));
        if (!same && sqrtMismatch++ == 0) firstSqrt = Hex(Bits(x)) + ": " + Hex(Bits(got)) + " against " + Hex(Bits(want));
    };
    for (uint32_t e = 1; e < 255; ++e) {
        for (int i = 0; i < 4096; ++i) checkSqrt(std::bit_cast<float>(e << 23 | (rng() & 0x7FFFFFu)));
        checkSqrt(std::bit_cast<float>(e << 23));
        checkSqrt(std::bit_cast<float>(e << 23 | 0x7FFFFFu));
    }
    for (const float x : {0.0f, -0.0f, INFINITY, 2.0f, 4.0f, 0.25f, 1e-30f, 3.4e38f}) checkSqrt(x);
    Check(sqrtMismatch == 0, "SqrtRn equals the correctly rounded IEEE square root (1.04 M values)",
          firstSqrt);
    Check(Bits(SqrtRn(-1.0f)) == 0x7FC00000u && Bits(SqrtRn(-0.0f)) == 0x80000000u,
          "SqrtRn: a negative input gives the quiet NaN, -0 gives -0");

    // Ftz flushes subnormal results to a zero of their sign and keeps everything else.
    Check(Bits(Ftz(std::bit_cast<float>(0x00000001u))) == 0u &&
              Bits(Ftz(std::bit_cast<float>(0x807FFFFFu))) == 0x80000000u &&
              Bits(Ftz(std::bit_cast<float>(0x00800000u))) == 0x00800000u &&
              Bits(Mul(1e-30f, 1e-15f)) == 0u,
          "Ftz flushes subnormals to signed zeros only");

    // The interpolants (Perlin 1985 and 2002): ends, centre and symmetry.
    bool fades = Fade1985(0.0f) == 0.0f && Fade1985(1.0f) == 1.0f && Fade1985(0.5f) == 0.5f &&
                 Fade2002(0.0f) == 0.0f && Fade2002(1.0f) == 1.0f && Fade2002(0.5f) == 0.5f;
    Check(fades, "the 1985 and 2002 interpolants are 0, 1/2 and 1 at 0, 1/2 and 1");
    // 2002's quintic has zero first and second derivatives at the ends: f(t) = O(t^3).
    const float small = 1.0f / 1024.0f;
    Check(Fade2002(small) < 11.0f * small * small * small && Fade1985(small) < 3.1f * small * small,
          "the 2002 interpolant is cubic at 0 (zero first and second derivatives), 1985's quadratic");

    // Gradient noise vanishes on the lattice (both papers), for every seed.
    bool lattice = true;
    for (int32_t i = -5; i <= 5; ++i) {
        for (uint32_t seed : {0u, 1u, 0xFFFFFFFFu}) {
            const Vec3 p{static_cast<float>(i), static_cast<float>(2 * i + 1),
                         static_cast<float>(-3 * i)};
            lattice = lattice && Perlin1985(p, seed) == 0.0f && Perlin2002(p, seed) == 0.0f;
        }
    }
    Check(lattice, "Perlin 1985 and 2002 noise are 0 at every lattice point");
    // Simplex noise vanishes at the origin: its own corner has offset 0 and the other three
    // are at squared distance 3/4, outside Gustavson's radius 0.6.
    Check(Simplex3(Vec3{}, 0) == 0.0f && Simplex3(Vec3{}, 12345) == 0.0f,
          "simplex noise is 0 at a simplex-lattice vertex");

    // Bounds over a sample: 2002 noise in [-1, 1] (|grad| <= 2 per axis pair, Perlin), 1985 in
    // [-sqrt(3), sqrt(3)] for cube gradients, simplex near [-1, 1] (Gustavson's scale).
    float max1985 = 0.0f, max2002 = 0.0f, maxSimplex = 0.0f;
    bool varies = false;
    std::uniform_real_distribution<float> coord(-64.0f, 64.0f);
    float previous = 0.0f;
    for (int i = 0; i < 20000; ++i) {
        const Vec3 p{coord(rng), coord(rng), coord(rng)};
        max1985 = std::max(max1985, std::fabs(Perlin1985(p, 9)));
        const float n = Perlin2002(p, 9);
        max2002 = std::max(max2002, std::fabs(n));
        maxSimplex = std::max(maxSimplex, std::fabs(Simplex3(p, 9)));
        varies = varies || (i > 0 && n != previous);
        previous = n;
    }
    Info("max |noise| over 20000 points: perlin1985 " + std::to_string(max1985) + ", perlin2002 " +
         std::to_string(max2002) + ", simplex3 " + std::to_string(maxSimplex));
    Check(max2002 <= 1.0f && max1985 <= 1.7320509f && maxSimplex <= 1.1f && max2002 > 0.3f &&
              maxSimplex > 0.3f && varies,
          "noise magnitudes stay inside the papers' bounds and the fields vary");
    Check(Perlin2002(Vec3{0.5f, 0.25f, 0.75f}, 1) != Perlin2002(Vec3{0.5f, 0.25f, 0.75f}, 2),
          "the seed changes the field");

    // Worley: F1 is 0 on a feature point, F2 >= F1, and the metric order M >= E >= C.
    const U3 offset = SeedOffset(42);
    bool worley = true;
    for (int32_t i = -3; i <= 3; ++i) {
        const U3 h = CellHash(i, 2 * i, -i, offset);
        const Vec3 feature{Add(static_cast<float>(i), Mul(static_cast<float>(h[0] >> 8), 0x1.0p-24f)),
                           Add(static_cast<float>(2 * i), Mul(static_cast<float>(h[1] >> 8), 0x1.0p-24f)),
                           Add(static_cast<float>(-i), Mul(static_cast<float>(h[2] >> 8), 0x1.0p-24f))};
        const WorleyResult r = Worley3(feature, 42, WorleyMetric::Euclidean);
        worley = worley && r.f1 == 0.0f && r.cell == h[0] && r.f2 > 0.0f;
    }
    Check(worley, "Worley F1 is 0 at a feature point, which names its cell");
    bool order = true;
    for (int i = 0; i < 5000; ++i) {
        const Vec3 p{coord(rng), coord(rng), coord(rng)};
        const WorleyResult e = Worley3(p, 5, WorleyMetric::Euclidean);
        const WorleyResult m = Worley3(p, 5, WorleyMetric::Manhattan);
        const WorleyResult c = Worley3(p, 5, WorleyMetric::Chebyshev);
        order = order && e.f2 >= e.f1 && m.f2 >= m.f1 && c.f2 >= c.f1 &&
                m.f1 >= e.f1 * (1.0f - 1e-6f) && e.f1 >= c.f1 * (1.0f - 1e-6f) && e.f1 <= 1.7320509f;
    }
    Check(order, "Worley: F2 >= F1, Manhattan >= Euclidean >= Chebyshev, F1 <= sqrt(3)");

    // fBm: one octave is the basis; zero gain keeps the first octave only.
    const Vec3 q{1.3f, -2.7f, 0.4f};
    Check(Fbm(FbmBasis::Perlin2002, q, 3, 1, 2.0f, 0.5f) == Perlin2002(q, 3) &&
              Fbm(FbmBasis::Simplex3, q, 3, 6, 2.0f, 0.0f) == Simplex3(q, 3) &&
              Fbm(FbmBasis::Perlin1985, q, 3, 2, 2.0f, 0.5f) ==
                  Add(Perlin1985(q, 3), Mul(0.5f, Perlin1985(Vec3{Mul(q.x, 2.0f), Mul(q.y, 2.0f), Mul(q.z, 2.0f)}, 4))),
          "fBm sums the octaves as defined (one octave, zero gain, two octaves)");

    // Morphology: radius 0 is the identity; an impulse dilates to the structuring element;
    // erosion is the dual of dilation (erode(f) = -dilate(-f)).
    Raster impulse{9, 9, 1, std::vector<float>(81, 0.0f)};
    impulse.texels[4 * 9 + 4] = 1.0f;
    const Raster square = Dilate(impulse, 2, Footprint::Square, Border::Clamp);
    const Raster disk = Dilate(impulse, 2, Footprint::Disk, Border::Clamp);
    bool shapes = true;
    for (int y = 0; y < 9; ++y) {
        for (int x = 0; x < 9; ++x) {
            const int dx = x - 4, dy = y - 4;
            const bool inSquare = std::abs(dx) <= 2 && std::abs(dy) <= 2;
            const bool inDisk = dx * dx + dy * dy <= 4;
            shapes = shapes && square.texels[size_t(y * 9 + x)] == (inSquare ? 1.0f : 0.0f) &&
                     disk.texels[size_t(y * 9 + x)] == (inDisk ? 1.0f : 0.0f);
        }
    }
    Check(shapes, "an impulse dilates to the 5x5 square and to the radius-2 disk");
    const Raster image = TestImage(16, 2, 77);
    Raster negated = image;
    for (float& v : negated.texels) v = -v;
    const Raster eroded = Erode(image, 3, Footprint::Disk, Border::Wrap);
    Raster dual = Dilate(negated, 3, Footprint::Disk, Border::Wrap);
    for (float& v : dual.texels) v = -v;
    Raster flushed = image;
    for (float& v : flushed.texels) v = Ftz(v);
    Check(FirstDifference(Dilate(image, 0, Footprint::Square, Border::Wrap), flushed).empty(),
          "dilation by radius 0 is the identity (subnormals flushed)");
    Check(FirstDifference(eroded, dual).empty(), "erosion is the dual of dilation",
          FirstDifference(eroded, dual));

    // Blur: an impulse's response is the outer product of the weights, rounded once; the
    // weights are symmetric and sum to 1 in double; the deterministic exponential matches.
    const std::vector<float> gauss = GaussianWeights(1.5, 4);
    bool symmetric = gauss.size() == 9;
    double total = 0.0;
    for (size_t k = 0; k < gauss.size(); ++k) {
        symmetric = symmetric && gauss[k] == gauss[gauss.size() - 1 - k];
        total += gauss[k];
    }
    const double e1 = std::exp(-1.0 / (2.0 * 1.5 * 1.5));
    Check(symmetric && std::fabs(total - 1.0) < 1e-6 &&
              std::fabs(double(gauss[3]) / double(gauss[4]) - e1) < 1e-6,
          "Gaussian weights are symmetric, sum to 1 and follow exp(-k^2 / 2 sigma^2)");
    Raster spike{9, 9, 1, std::vector<float>(81, 0.0f)};
    spike.texels[4 * 9 + 4] = 1.0f;
    const Raster response = SeparableBlur(spike, gauss, Border::Wrap);
    bool outer = true;
    for (int y = 0; y < 9; ++y) {
        for (int x = 0; x < 9; ++x) {
            outer = outer && response.texels[size_t(y * 9 + x)] == Mul(gauss[size_t(y)], gauss[size_t(x)]);
        }
    }
    Check(outer, "a blurred impulse is the outer product of the weights");
    Check(BoxWeights(0) == std::vector<float>{1.0f} &&
              BoxWeights(2) == std::vector<float>(5, static_cast<float>(1.0 / 5.0)),
          "box weights are float32(1 / (2r + 1))");

    // Pcg3d: changes every output word with one input bit (avalanche over a sample).
    size_t flips = 0, trials = 0;
    for (uint32_t i = 0; i < 256; ++i) {
        const U3 a = Pcg3d({i, 7u * i, 13u * i});
        const U3 b = Pcg3d({i ^ 1u, 7u * i, 13u * i});
        for (int c = 0; c < 3; ++c) flips += static_cast<size_t>(std::popcount(a[c] ^ b[c]));
        trials += 96;
    }
    const double rate = double(flips) / double(trials);
    Info("pcg3d single-bit avalanche rate " + std::to_string(rate));
    Check(rate > 0.40 && rate < 0.60, "pcg3d flips about half the output bits for one input bit");
    return Finish();
}

// ── kernels (2.2: generated HLSL through the render core's cache) ────────────

/// Number of `OpDecorate <id> NoContraction` instructions in a SPIR-V module (`precise`).
int NoContractionCount(const std::vector<uint8_t>& spirv) {
    std::vector<uint32_t> words(spirv.size() / 4);
    std::memcpy(words.data(), spirv.data(), words.size() * 4);
    int count = 0;
    for (size_t i = 5; i < words.size();) {
        const uint32_t length = words[i] >> 16;
        if (length == 0) break;
        if ((words[i] & 0xFFFF) == 71 && i + 2 < words.size() && words[i + 2] == 42) ++count;
        i += length;
    }
    return count;
}

int RunKernels(const fs::path& dir) {
    render::Result<std::unique_ptr<render::DxcKernelCompiler>> compiler =
        render::DxcKernelCompiler::Load(render::DefaultDxcompilerPath());
    Check(compiler.has_value(), "DXC loads", compiler ? "" : compiler.error().Describe());
    if (!compiler) return Finish();
    render::KernelCache cache(**compiler, dir / "kernel-cache");
    HlslBackend hlsl(nullptr);
    (void)hlsl.Register(std::make_shared<NoiseProbe>(ParityStatus::Unavailable("probe")));
    (void)hlsl.Register(std::make_shared<ImageProbe>());
    (void)hlsl.Register(std::make_shared<SyntheticExact>());

    std::vector<ProceduralRequest> requests = {NoiseRequest(kPerlin2002, 16, 1),
                                               ImageRequest(0, 2, 1, 0, 16, 2),
                                               ImageRequest(3, 3, 0, 1, 16, 2), SyntheticRequest()};
    size_t compiled = 0;
    for (const ProceduralRequest& request : requests) {
        auto kernels = hlsl.Kernels(request);
        Check(kernels.has_value(), "kernels planned for " + AssetName(request),
              kernels ? "" : kernels.error().Describe());
        if (!kernels) continue;
        for (const render::KernelSource& source : *kernels) {
            for (const render::KernelTarget target :
                 {render::KernelTarget::Dxil, render::KernelTarget::Spirv}) {
                render::Result<render::CompiledKernel> kernel = cache.Get(source, target);
                const std::string what = source.name + " (" +
                                         std::string(render::KernelTargetName(target)) + ")";
                Check(kernel.has_value() && !kernel->bytecode.empty(), "compiles: " + what,
                      kernel ? "" : kernel.error().Describe());
                if (!kernel) continue;
                ++compiled;
                if (target == render::KernelTarget::Spirv) {
                    const int precise = NoContractionCount(kernel->bytecode);
                    Check(precise > 0, "precise arithmetic reaches SPIR-V as NoContraction: " + what,
                          std::to_string(precise) + " decorations");
                }
                render::Result<render::CompiledKernel> again = cache.Get(source, target);
                Check(again && again->cacheHit && again->key == kernel->key &&
                          again->bytecode == kernel->bytecode,
                      "the second request is a cache hit by content hash: " + what);
            }
        }
    }
    Info("compiled " + std::to_string(compiled) + " kernels");

    // The cache key is the kernel's content: parameter values and seeds travel in buffers and
    // root constants, so editing them reuses the kernel; another body is another kernel.
    ProceduralRequest edited = NoiseRequest(kSimplex, 64, 99);
    edited.params["scale"] = 2.5;
    const std::string version = cache.CompilerVersion();
    const uint64_t a = render::KernelKey((*hlsl.Kernels(NoiseRequest(kPerlin2002, 16, 1)))[0],
                                         render::KernelTarget::Dxil, version);
    const uint64_t b = render::KernelKey((*hlsl.Kernels(edited))[0], render::KernelTarget::Dxil, version);
    const uint64_t c = render::KernelKey((*hlsl.Kernels(ImageRequest(0, 1, 0, 0, 16, 1)))[0],
                                         render::KernelTarget::Dxil, version);
    Check(a == b && a != c, "parameter and seed edits reuse the kernel; another family's body does not");
    return Finish();
}

// ── gpu (3.3 DX12 repeatability; 2.2 end to end) ─────────────────────────────

template <class T>
render::Result<T> Get(std::future<render::Result<T>>& future) {
    if (future.wait_for(std::chrono::seconds(300)) != std::future_status::ready) {
        return render::Fail(render::ErrorCode::RequestFailed, std::nullopt, "no result within 300 s");
    }
    return future.get();
}

int RunGpu(const fs::path& dir) {
    render::EngineOptions options;
    options.kernelCacheRoot = dir / "kernel-cache";
    render::Engine engine(options);
    if (engine.DeviceError()) {
        std::printf("SKIP no DX12 device: %s\n", engine.DeviceError()->Describe().c_str());
        return kExitSkip;
    }
    HlslBackend hlsl(&engine);
    (void)hlsl.Register(std::make_shared<NoiseProbe>(ParityStatus::Unavailable("probe")));
    (void)hlsl.Register(std::make_shared<ImageProbe>());
    (void)hlsl.Register(std::make_shared<SyntheticExact>());

    struct Case {
        std::string what;
        ProceduralRequest request;
        InputImages inputs;
    };
    std::vector<Case> cases;
    const char* noiseNames[] = {"perlin1985", "perlin2002", "simplex3", "worley euclidean",
                                "worley manhattan", "worley chebyshev", "fbm", "sqrt"};
    for (uint32_t code = 0; code <= kSqrt; ++code) {
        for (const uint64_t seed : {uint64_t{0}, uint64_t{0xFFFFFFFFu}}) {
            cases.push_back({std::string(noiseNames[code]) + " seed " + std::to_string(seed),
                             NoiseRequest(code, code == kSqrt ? 128 : 64, seed), {}});
        }
    }
    for (const uint32_t basis : {0u, 2u, 3u}) {
        ProceduralRequest r = NoiseRequest(kFbm, 33, 5);
        r.params["basis"] = int64_t{basis};
        r.params["octaves"] = int64_t{basis == 3 ? 3 : 8};
        r.params["lacunarity"] = 1.875;
        r.params["gain"] = 0.625;
        r.params["scale"] = 3.0;
        cases.push_back({"fbm basis " + std::to_string(basis), r, {}});
    }
    {
        ProceduralRequest r = NoiseRequest(kPerlin2002, 64, 1);
        r.params["scale"] = 1.0 / 1024;
        r.params["offset_x"] = -4000.0;
        r.params["offset_y"] = 4000.0;
        cases.push_back({"perlin2002 far from the origin at a fine scale", r, {}});
    }
    const char* opNames[] = {"dilate", "erode", "box blur", "gaussian blur"};
    for (uint32_t op = 0; op < 4; ++op) {
        for (const uint32_t border : {0u, 1u}) {
            const uint32_t channels = op % 2 == 0 ? 4 : 2;
            ProceduralRequest r = ImageRequest(op, op < 2 ? 3 : 5, border, border, 37, channels);
            cases.push_back({std::string(opNames[op]) + (border ? " clamp" : " wrap"), r,
                             {{"image", TestImage(37, channels, 100 + op)}}});
        }
    }
    {
        ProceduralRequest r = ImageRequest(1, 8, 1, 0, 32, 1);
        cases.push_back({"erode radius 8 disk, one channel", r, {{"image", TestImage(32, 1, 9)}}});
    }

    for (const Case& c : cases) {
        render::Result<Raster> reference = hlsl.EvaluateReference(c.request, c.inputs);
        RasterFuture first = hlsl.EvaluateCandidate(c.request, c.inputs);
        render::Result<Raster> gpu = Get(first);
        if (!reference || !gpu) {
            Check(false, "GPU equals CPU: " + c.what,
                  !reference ? reference.error().Describe() : gpu.error().Describe());
            continue;
        }
        Check(FirstDifference(*gpu, *reference).empty(), "GPU equals CPU bit for bit: " + c.what,
              FirstDifference(*gpu, *reference));
        RasterFuture second = hlsl.EvaluateCandidate(c.request, c.inputs);
        render::Result<Raster> again = Get(second);
        Check(again && FirstDifference(*again, *gpu).empty(),
              "DX12 repeats byte for byte: " + c.what,
              again ? FirstDifference(*again, *gpu) : again.error().Describe());
    }

    // A tile is the same texels as the whole texture.
    for (const Case& c : {cases[2], cases[cases.size() - 2]}) {
        ProceduralRequest tiled = c.request;
        tiled.tile = TileRect{5, 9, 19, 11};
        RasterFuture whole = hlsl.EvaluateCandidate(c.request, c.inputs);
        RasterFuture part = hlsl.EvaluateCandidate(tiled, c.inputs);
        render::Result<Raster> w = Get(whole);
        render::Result<Raster> t = Get(part);
        bool same = w && t && t->width == 19 && t->height == 11;
        for (uint32_t y = 0; same && y < 11; ++y) {
            for (uint32_t x = 0; same && x < 19; ++x) {
                for (uint32_t ch = 0; ch < t->channels; ++ch) {
                    same = same && Bits(t->texels[(size_t{y} * 19 + x) * t->channels + ch]) ==
                                       Bits(w->texels[(size_t{y + 9} * w->width + x + 5) * w->channels + ch]);
                }
            }
        }
        render::Result<Raster> reference = hlsl.EvaluateReference(tiled, c.inputs);
        Check(same && reference && FirstDifference(*t, *reference).empty(),
              "a tile equals the same texels of the whole texture and the CPU tile: " + c.what);
    }

    // The seam's certified path end to end on the GPU: the synthetic exact family, with its
    // mesh map, equals its CPU reference.
    ProceduralSeam seam(nullptr, &hlsl);
    const InputImages curvature = {{"Curvature", Curvature()}};
    auto served = seam.Evaluate(SyntheticRequest(), curvature);
    render::Result<Raster> seamRaster = served ? Get(*served) : render::Result<Raster>{};
    render::Result<Raster> seamReference = hlsl.EvaluateReference(SyntheticRequest(), curvature);
    Check(served && seamRaster && seamReference && FirstDifference(*seamRaster, *seamReference).empty(),
          "the seam serves a certified family on DX12 equal to its CPU reference",
          !served ? served.error().Describe()
                  : (!seamRaster ? seamRaster.error().Describe() : FirstDifference(*seamRaster, *seamReference)));
    return Finish();
}

// ── library (item 2.4) ───────────────────────────────────────────────────────

std::string Urls(const std::vector<const AssetRecord*>& records) {
    std::string out;
    for (const AssetRecord* record : records) {
        out += (out.empty() ? "" : " ") + uzp::core::FormatAssetUrl(record->asset);
    }
    return out;
}

std::string Describe(const std::expected<std::vector<const AssetRecord*>, SearchRefusal>& found) {
    if (found) return "found [" + Urls(*found) + "]";
    return (found.error().kind == SearchRefusal::Kind::NotYetSupported ? "NotYetSupported: "
                                                                       : "UnsupportedProcedural: ") +
           found.error().message;
}

bool Gap(const std::expected<std::vector<const AssetRecord*>, SearchRefusal>& found, std::string_view text) {
    return !found && found.error().kind == SearchRefusal::Kind::NotYetSupported &&
           found.error().message.find(text) != std::string::npos &&
           found.error().message.find("phase3.3_procedural-families") != std::string::npos;
}

/// A project with one fill whose BaseColor is a procedural source pinning `source`, and one
/// filter effect pinning `filter`.
uzp::core::Project PinningProject(const std::string& source, const std::string& filter) {
    uzp::core::Project project;
    uzp::core::TextureSet set;
    set.id = project.AllocateId();
    set.name = "set";
    uzp::core::Stack stack;
    stack.id = project.AllocateId();
    uzp::core::Layer layer;
    layer.uid = project.AllocateId();
    layer.kind = uzp::core::LayerKind::fill;
    uzp::core::FillContent fill;
    uzp::core::ProceduralSource procedural;
    procedural.ref.asset = source;
    fill.sources[uzp::core::ChannelType::BaseColor] = uzp::core::Source{procedural};
    layer.fill = fill;
    uzp::core::Effect effect;
    effect.uid = project.AllocateId();
    effect.kind = uzp::core::EffectKind::filter;
    effect.procedural = uzp::core::ProceduralRef{};
    effect.procedural->asset = filter;
    layer.content_effects.push_back(effect);
    stack.root_layers.push_back(layer);
    set.stacks.push_back(stack);
    project.texture_sets.push_back(set);
    return project;
}

int RunLibrary(const fs::path& fixture, const fs::path& shipped) {
    const auto shippedLibrary = AssetLibrary::Load(shipped);
    Check(shippedLibrary && shippedLibrary->aliases().empty() &&
              std::all_of(shippedLibrary->records().begin(), shippedLibrary->records().end(),
                          [](const AssetRecord& r) { return r.status.kind == ParityStatus::Kind::Unavailable; }),
          "the shipped library loads and holds no certified asset and no alias (no family is certified yet)",
          shippedLibrary ? std::to_string(shippedLibrary->records().size()) : shippedLibrary.error());
    const auto loaded = AssetLibrary::Load(fixture);
    Check(loaded.has_value(), "the fixture library loads", loaded ? "" : loaded.error());
    if (!loaded || !shippedLibrary) return Finish();
    const AssetLibrary& library = *loaded;
    Check(library.records().size() == 3 && library.aliases().size() == 1,
          "the fixture library holds three records and one alias");

    // Pins: the exact version or a refusal; no other version is substituted.
    const AssetRecord* ridge2 = library.Find(Url("test-generator", "ridge", "2"));
    Check(ridge2 != nullptr && ridge2->name == "Ridge (synthetic test probe)" &&
              ridge2->status.kind == ParityStatus::Kind::Exact &&
              ridge2->status.corpusIds == std::vector<std::string>{"synthetic-calibration", "synthetic-held-out"},
          "a pin resolves to its exact version with its UzPainter name, status and corpus ids");
    Check(ridge2 != nullptr && std::get<int64_t>(ridge2->defaults.at("mode")) == 1 &&
              ridge2->domain.parameters.size() == 3 && ridge2->domain.constraints.size() == 1 &&
              !ridge2->domain.anySeed && ridge2->domain.seeds == std::vector<uint64_t>{7, 11} &&
              ridge2->domain.inputs.at("Curvature").formats == std::vector<ChannelFormat>{ChannelFormat::U16},
          "the record's defaults (a boolean as an integer) and its certified domain are read");
    const auto missing = library.Resolve(Url("test-generator", "ridge", "3"));
    Check(!missing && missing.error().reason == kNotInLibrary && missing.error().field == "version" &&
              missing.error().value == "3" && missing.error().certified == "[1, 2]" &&
              missing.error().asset == "uzasset://test-generator/ridge@3",
          "a pin of a version the library does not hold is refused, naming the versions it holds",
          missing ? "resolved" : missing.error().Describe());
    const AssetRecord* soften = library.Find(Url("test-filter", "soften", "1"));
    Check(soften != nullptr && soften->status.kind == ParityStatus::Kind::Calibrated &&
              soften->status.residuals.size() == 1 && soften->status.residuals[0].unit == "ulp_f32",
          "a calibrated record keeps its residuals, one per unit");

    // resource.search: the library's own shelf, by UzPainter names.
    const auto all = library.Search("s:uzpainter");
    Check(all && Urls(*all) == "uzasset://test-filter/soften@1 uzasset://test-generator/ridge@1 "
                               "uzasset://test-generator/ridge@2",
          "s:uzpainter lists every asset of the library, sorted by URL", Describe(all));
    const auto generators = library.Search("s:uzpainter u:generator");
    Check(generators && generators->size() == 2, "s:uzpainter u:generator keeps the generators", Describe(generators));
    const auto byName = library.Search(R"(s:uzpainter n:Ridge\ (synthetic\ test\ probe)=)");
    Check(byName && Urls(*byName) == "uzasset://test-generator/ridge@2",
          "an exact UzPainter name with escaped blanks finds its asset", Describe(byName));
    const auto none = library.Search("s:uzpainter n:Nothing=");
    Check(none && none->empty(), "an exact name the library does not hold finds nothing on its own shelf",
          Describe(none));

    // Painter names: only through the alias table, only to a certified asset.
    const auto alias = library.Search(R"(s:starterassets u:generator n:Synthetic\ Edge\ Probe=)");
    Check(alias && Urls(*alias) == "uzasset://test-generator/ridge@2" && (*alias)[0]->name != "Synthetic Edge Probe",
          "a Painter name resolves through the alias table to the UzPainter asset, with its UzPainter name",
          Describe(alias));
    const auto anyShelf = library.Search(R"(n:Synthetic\ Edge\ Probe=)");
    Check(anyShelf && Urls(*anyShelf) == "uzasset://test-generator/ridge@2",
          "a Painter name without a shelf resolves through the alias table", Describe(anyShelf));
    const auto wrongUsage = library.Search(R"(s:starterassets u:filter n:Synthetic\ Edge\ Probe=)");
    Check(!wrongUsage && wrongUsage.error().kind == SearchRefusal::Kind::UnsupportedProcedural &&
              wrongUsage.error().procedural.reason == kNoCertifiedFamily &&
              wrongUsage.error().procedural.asset == "starterassets/filter/Synthetic Edge Probe",
          "the same Painter name under another usage is refused, not answered with the generator",
          Describe(wrongUsage));
    const auto unknown = library.Search("s:starterassets u:filter n:Blur=");
    Check(!unknown && unknown.error().kind == SearchRefusal::Kind::UnsupportedProcedural &&
              unknown.error().procedural.reason == kNoCertifiedFamily,
          "a Painter name with no alias raises UnsupportedProcedural (no certified family), no similar asset",
          Describe(unknown));
    const auto uzName = library.Search(R"(s:starterassets n:Ridge\ (synthetic\ test\ probe)=)");
    Check(!uzName && uzName.error().kind == SearchRefusal::Kind::UnsupportedProcedural,
          "a UzPainter name is not a Painter name: Painter's shelf does not answer it", Describe(uzName));

    // The terms outside the implemented grammar are release gaps.
    Check(Gap(library.Search("s:starterassets u:generator"), "without an exact name"),
          "listing a Painter shelf without an exact name is a release gap");
    Check(Gap(library.Search("u:generator"), "every shelf"), "listing every shelf is a release gap");
    Check(Gap(library.Search("n:Blur"), "not exact"), "a partial name is a release gap");
    Check(Gap(library.Search("Blur"), "is not s:, u: or n:"), "free text is a release gap");
    Check(Gap(library.Search("s:uzpainter s:starterassets"), "repeats"), "a repeated term is a release gap");
    Check(Gap(library.Search(R"(u:substance n:Paper\ Grainy=)"), "u:substance"),
          "a usage that is not a procedural usage of the library is a release gap");
    Check(Gap(library.Search("s:"), "has no value"), "a term without a value is a release gap");
    const auto empty = library.Search("");
    Check(Gap(empty, "every shelf"), "an empty query (every shelf) is a release gap", Describe(empty));

    // The project's pins.
    uzp::core::Project project =
        PinningProject("uzasset://test-generator/ridge@2", "uzasset://test-filter/soften@1");
    Check(PinnedAssets(project) ==
              std::vector<std::string>{"uzasset://test-filter/soften@1", "uzasset://test-generator/ridge@2"},
          "the project's pins are its procedural sources and effects, by full URL");
    Check(!CheckPins(project, library).has_value(), "every pin of the project resolves at its exact version");
    const uzp::core::Project other =
        PinningProject("uzasset://test-generator/ridge@9", "uzasset://test-filter/soften@1");
    const std::optional<UnsupportedProcedural> pin = CheckPins(other, library);
    Check(pin && pin->reason == kNotInLibrary && pin->asset == "uzasset://test-generator/ridge@9",
          "a pin of a version the library does not hold is refused", pin ? pin->Describe() : "resolved");
    Check(CheckPins(project, *shippedLibrary).has_value(), "the shipped library holds none of the fixture pins");
    return Finish();
}

int RunLibraryLoad(const fs::path& root) {
    const auto loaded = AssetLibrary::Load(root);
    if (!loaded) {
        std::printf("REFUSED %s\n", loaded.error().c_str());
        return 1;
    }
    std::printf("LOADED %zu %zu\n", loaded->records().size(), loaded->aliases().size());
    return 0;
}

// ── assets-cli (item 2.5) ────────────────────────────────────────────────────

struct CliRun {
    int status = 0;
    std::string out;
    std::string err;
    uzp::core::json::Value document;
};

std::string ReadAll(std::FILE* file) {
    std::fflush(file);
    std::rewind(file);
    std::string text;
    char buffer[4096];
    for (size_t n; (n = std::fread(buffer, 1, sizeof(buffer), file)) > 0;) text.append(buffer, n);
    return text;
}

CliRun Cli(std::vector<std::string> args) {
    CliRun run;
    std::FILE* out = std::tmpfile();
    std::FILE* err = std::tmpfile();
    run.status = RunAssetsCommand(args, out, err);
    run.out = ReadAll(out);
    run.err = ReadAll(err);
    std::fclose(out);
    std::fclose(err);
    if (run.out.starts_with("UZP_JSON:")) {
        try {
            run.document = uzp::core::json::Parse(std::string_view(run.out).substr(9));
        } catch (const uzp::core::json::ParseError&) {
        }
    }
    return run;
}

const uzp::core::json::Value* Field(const uzp::core::json::Value& value, std::string_view key) {
    if (!value.IsObject()) return nullptr;
    const auto& object = std::get<uzp::core::json::Object>(value.data);
    const auto it = object.find(key);
    return it == object.end() ? nullptr : &it->second;
}

const uzp::core::json::Array* Assets(const CliRun& run) {
    const uzp::core::json::Value* assets = Field(run.document, "assets");
    return assets != nullptr && assets->IsArray() ? &std::get<uzp::core::json::Array>(assets->data) : nullptr;
}

int RunAssetsCli(const fs::path& work, const fs::path& fixture, const fs::path& shipped) {
    namespace json = uzp::core::json;
    const std::string fixtureDir = fixture.generic_string();
    const CliRun plain = Cli({"assets", "list", "--library", fixtureDir});
    const json::Array* listed = Assets(plain);
    Check(plain.status == 0 && listed != nullptr && listed->size() == 3 &&
              *Field((*listed)[0], "asset") == json::Value("uzasset://test-filter/soften@1") &&
              *Field((*listed)[2], "name") == json::Value("Ridge (synthetic test probe)") &&
              Field((*listed)[0], "parity") == nullptr && Field((*listed)[0], "domain") == nullptr,
          "assets list prints every asset with its URL, UzPainter name and usage, sorted by URL", plain.out);
    Check(plain.out.find("Synthetic Edge Probe") == std::string::npos,
          "assets list shows no Painter name of the internal alias table");

    const CliRun parity = Cli({"assets", "list", "--parity", "--library", fixtureDir});
    const json::Array* rows = Assets(parity);
    const auto status = [&](size_t i) -> std::string {
        const json::Value* p = rows == nullptr ? nullptr : Field((*rows)[i], "parity");
        const json::Value* s = p == nullptr ? nullptr : Field(*p, "status");
        return s != nullptr && s->IsString() ? std::get<std::string>(s->data) : "";
    };
    Check(parity.status == 0 && rows != nullptr && rows->size() == 3 && status(0) == "calibrated" &&
              status(1) == "unavailable" && status(2) == "exact",
          "assets list --parity gives each asset's parity status (calibrated, unavailable, exact)", parity.out);
    const json::Value* calibrated = rows == nullptr ? nullptr : Field((*rows)[0], "parity");
    const json::Value* residuals = calibrated == nullptr ? nullptr : Field(*calibrated, "residuals");
    Check(residuals != nullptr && residuals->IsArray() && std::get<json::Array>(residuals->data).size() == 1 &&
              *Field(std::get<json::Array>(residuals->data)[0], "unit") == json::Value("ulp_f32") &&
              *Field(std::get<json::Array>(residuals->data)[0], "max") == json::Value(1) &&
              Field(*calibrated, "corpus_ids") != nullptr,
          "a calibrated asset lists its residuals per unit and its corpus ids", parity.out);
    const json::Value* unavailable = rows == nullptr ? nullptr : Field((*rows)[1], "parity");
    Check(unavailable != nullptr && Field(*unavailable, "reason") != nullptr,
          "an unavailable asset gives the reason", parity.out);
    const json::Value* domain = rows == nullptr ? nullptr : Field((*rows)[2], "domain");
    Check(domain != nullptr && Field(*domain, "parameters") != nullptr && Field(*domain, "output") != nullptr,
          "assets list --parity gives each asset's certified editable domain", parity.out);

    // The shipped records declare their domains before calibration (phase3.2 filter 2.6); none
    // is certified.
    const CliRun shippedRun = Cli({"assets", "list", "--parity", "--library", shipped.generic_string()});
    const json::Array* shippedRows = Assets(shippedRun);
    Check(shippedRun.status == 0 && shippedRows != nullptr &&
              std::all_of(shippedRows->begin(), shippedRows->end(),
                          [](const json::Value& row) {
                              const json::Value* p = Field(row, "parity");
                              return p != nullptr && Field(*p, "status") != nullptr &&
                                     *Field(*p, "status") == json::Value("unavailable") &&
                                     Field(row, "domain") != nullptr;
                          }),
          "the shipped library lists no certified asset, each with its declared domain", shippedRun.out);

    const fs::path broken = work / "broken-library";
    fs::create_directories(broken);
    {
        std::FILE* file = std::fopen((broken / "library.json").string().c_str(), "wb");
        std::fputs("{\"schema\": \"uzpainter/asset-library/1\", \"records\": [\"absent.json\"], \"aliases\": \"a.json\"}", file);
        std::fclose(file);
    }
    const CliRun refused = Cli({"assets", "list", "--library", broken.generic_string()});
    const json::Value* error = Field(refused.document, "error");
    Check(refused.status == 3 && *Field(refused.document, "status") == json::Value("host_error") &&
              error != nullptr && *Field(*error, "type") == json::Value("AssetLibraryError"),
          "a library that does not load is a host error (exit 3), nothing listed", refused.out);
    bool usage = true;
    for (const std::vector<std::string>& args :
         {std::vector<std::string>{"assets"}, {"assets", "show"}, {"assets", "list", "--parity", "--parity"},
          {"assets", "list", "--library"}, {"assets", "list", "--bogus"}}) {
        const CliRun bad = Cli(args);
        usage = usage && bad.status == 2 && bad.out.empty() && bad.err.starts_with("usage: UzPainter.exe assets list");
    }
    Check(usage, "a usage error prints the usage on stderr (exit 2)");
    return Finish();
}

// ── admission (items 3.1, 3.4 and 3.6 through a document edit) ───────────────

/// A project with one fill layer whose content stack holds one generator effect without a
/// procedural yet; `generator` receives its uid.
uzp::core::Project GeneratorProject(uzp::core::Id& generator) {
    uzp::core::Project project;
    project.versions.app_version = "0.0.0";
    project.versions.evaluator_profile = "painter-12.1-isolated-linear";
    uzp::core::TextureSet set;
    set.id = project.AllocateId();
    set.name = set.original_name = set.material_id = "set";
    set.uv_tiles = {uzp::core::UVTile{project.AllocateId(), 1001, {}}};
    uzp::core::Stack stack;
    stack.id = project.AllocateId();
    stack.channels[uzp::core::ChannelType::BaseColor] =
        uzp::core::Channel{uzp::core::ChannelFormat::sRGB8, "", {}};
    uzp::core::Layer layer;
    layer.uid = project.AllocateId();
    layer.kind = uzp::core::LayerKind::fill;
    layer.name = "fill";
    layer.fill = uzp::core::FillContent{};
    uzp::core::Effect effect;
    effect.uid = project.AllocateId();
    effect.kind = uzp::core::EffectKind::generator;
    effect.name = "ridge";
    generator = effect.uid;
    layer.content_effects.push_back(effect);
    stack.root_layers.push_back(layer);
    set.stacks.push_back(stack);
    project.texture_sets.push_back(set);
    return project;
}

const uzp::core::Effect* GeneratorOf(const uzp::core::Project& project) {
    return &project.texture_sets.at(0).stacks.at(0).root_layers.at(0).content_effects.at(0);
}

UseContext RidgeContext() {
    UseContext context;
    context.meshClass = "sphere";
    context.output = RasterSpec{64, ChannelFormat::F32, "linear", 1};
    context.inputs["Curvature"] = RasterSpec{64, ChannelFormat::U16, "linear", 1};
    context.seed = 7;
    return context;
}

/// The SHA-256 of the curvature map the admission case imports (set before the refusals).
std::string g_curvature;

uzp::core::ProceduralRef RidgeRef(std::string asset, uzp::core::json::Object params) {
    uzp::core::ProceduralRef ref;
    ref.asset = std::move(asset);
    ref.params = std::move(params);
    ref.image_inputs["Curvature"] = uzp::core::ResourceBinding{g_curvature, std::nullopt, {}};
    return ref;
}

int RunAdmission(const fs::path& work, const fs::path& fixture) {
    namespace core = uzp::core;
    namespace json = uzp::core::json;
    const auto loaded = AssetLibrary::Load(fixture);
    Check(loaded.has_value(), "the fixture library loads", loaded ? "" : loaded.error());
    if (!loaded) return Finish();
    const AssetLibrary& library = *loaded;
    auto ridge = std::make_shared<SyntheticExact>(Url("test-generator", "ridge", "2"));
    HlslBackend hlsl(nullptr);
    Check(hlsl.Register(ridge).has_value(), "the library's certified asset registers with the HLSL host");
    FakeSnapshots snapshots;
    ProceduralSeam seam(&snapshots, &hlsl);

    core::Id generator = core::kNoId;
    core::DocumentState initial;
    initial.project_uuid = "6f1c2a3e-0000-4000-8000-00000000a324";
    initial.project = GeneratorProject(generator);
    const fs::path file = work / "admission.uzp";
    fs::remove(file);
    auto store = uzp::store::ProjectStore::Create(file, initial);
    core::Document document(initial);
    store->Attach(document);
    int submits = 0;
    int keys = 0;
    const SubmitEdit submit = [&](const std::function<void(core::Edit&)>& call) {
        ++submits;
        const std::string key = "procedural-" + std::to_string(++keys);
        return store->Submit(document,
                             core::MutationRequest{"procedural_set", json::Object{{"key", key}}, key, document.revision()},
                             call);
    };
    const UseContext context = RidgeContext();

    // The curvature map the references bind: a project resource (its bytes are the raster's
    // float32 samples; the evaluation reads the decoded raster).
    const Raster curvature = Curvature();
    std::string bytes(reinterpret_cast<const char*>(curvature.texels.data()), curvature.texels.size() * sizeof(float));
    const auto imported = store->Submit(
        document, core::MutationRequest{"resource_import", json::Object{{"name", "curvature"}}, "import", 0},
        [&](core::Edit& edit) {
            const auto size = static_cast<std::int64_t>(bytes.size());
            g_curvature = store->StageResource(bytes, "application/octet-stream");
            core::ResourceMeta meta;
            meta.id = edit.AllocateId();
            meta.name = "curvature";
            meta.mime = "application/octet-stream";
            meta.size = size;
            meta.usage = "TEXTURE";
            meta.imported_at = "2026-10-20T00:00:00Z";
            edit.project().resources[g_curvature].push_back(meta);
        });
    Check(imported.result && imported.result->status == core::ResultStatus::committed && document.revision() == 1,
          "the curvature map is imported as a project resource (revision 1)");

    // 3.1 and 3.6: every refusal returns before a transaction opens, with nothing evaluated.
    const core::Project before = *document.snapshot().project;
    struct Refusal {
        std::string name;
        core::ProceduralRef ref;
        UseContext context;
        std::string_view reason;
        std::string field;
    };
    UseContext narrowInput = context;
    narrowInput.inputs["Curvature"].resolution = 32;
    UseContext largeOutput = context;
    largeOutput.output.resolution = 128;
    UseContext otherSeed = context;
    otherSeed.seed = 8;
    const double justAbove = std::nextafter(1.0, 2.0);
    const std::vector<Refusal> refusals{
        {"an asset the library holds with no snapshot and no certified family (3.1)",
         RidgeRef("uzasset://test-generator/ridge@1", {}), context, kNoBackend, ""},
        {"a pinned version the library does not hold", RidgeRef("uzasset://test-generator/ridge@3", {}), context,
         kNotInLibrary, "version"},
        {"a Painter asset with no snapshot and no family", RidgeRef("uzasset://painter-generator/metal-edge-wear@1", {}),
         context, kNotInLibrary, "version"},
        {"a parameter one ulp above its range (3.6)", RidgeRef("uzasset://test-generator/ridge@2", {{"amount", justAbove}}),
         context, kOutsideDomain, "params.amount"},
        {"a seed outside the listed seeds (3.6)", RidgeRef("uzasset://test-generator/ridge@2", {}), otherSeed,
         kOutsideDomain, "seed"},
        {"a mesh-map input of another resolution (3.6)", RidgeRef("uzasset://test-generator/ridge@2", {}), narrowInput,
         kOutsideDomain, "inputs.Curvature.resolution"},
        {"an output resolution outside the domain (3.6)", RidgeRef("uzasset://test-generator/ridge@2", {}), largeOutput,
         kOutsideDomain, "output.resolution"},
        {"a parameter the asset does not declare", RidgeRef("uzasset://test-generator/ridge@2", {{"gain", 1}}), context,
         kOutsideDomain, "params.gain"},
        {"a malformed vector parameter",
         RidgeRef("uzasset://test-generator/ridge@2", {{"amount", json::Array{}}}), context,
         "a vector needs 2 to 4 components", "params.amount"},
        {"a vector outside a scalar certified domain",
         RidgeRef("uzasset://test-generator/ridge@2", {{"amount", json::Array{0, 1}}}), context,
         kOutsideDomain, "params.amount"},
    };
    for (const Refusal& r : refusals) {
        const auto outcome = SetEffectProcedural(generator, r.ref, r.context, library, seam, submit);
        Check(!outcome && outcome.error().reason == r.reason && outcome.error().field == r.field && submits == 0 &&
                  document.revision() == 1 && *document.snapshot().project == before,
              "refused before mutation, the revision unchanged: " + r.name,
              outcome ? "admitted" : outcome.error().Describe());
    }
    Check(ridge->plans == 0 && ridge->references == 0 && snapshots.evaluations == 0 &&
              GeneratorOf(*document.snapshot().project)->procedural == std::nullopt,
          "no refused edit evaluates, plans or stores any asset in its place (no substitution, no clamping)");

    // 3.6: a snapshot of the project with the exact signature of an out-of-domain request is
    // still served, and the edit commits that request as given.
    const core::ProceduralRef outside = RidgeRef("uzasset://test-generator/ridge@2", {{"amount", justAbove}});
    const auto outsideRequest = RequestFor(outside, context, library);
    snapshots.rasters[SignatureHash(*outsideRequest)] = Raster{64, 64, 1, std::vector<float>(64 * 64, 0.5f)};
    const auto served = SetEffectProcedural(generator, outside, context, library, seam, submit);
    Check(served && served->result && served->result->status == core::ResultStatus::committed && submits == 1 &&
              document.revision() == 2 && GeneratorOf(*document.snapshot().project)->procedural == outside,
          "an out-of-domain request whose exact signature a snapshot holds is served and committed unclamped",
          served ? "" : served.error().Describe());
    snapshots.rasters.clear();

    // The certified path: the edit commits the pinned reference exactly.
    const core::ProceduralRef chosen = RidgeRef("uzasset://test-generator/ridge@2", {{"amount", 0.75}, {"mode", false}});
    const auto committed = SetEffectProcedural(generator, chosen, context, library, seam, submit);
    Check(committed && committed->result && committed->result->status == core::ResultStatus::committed &&
              document.revision() == 3 && GeneratorOf(*document.snapshot().project)->procedural == chosen,
          "inside the domain the edit commits the pinned reference as given",
          committed ? "" : committed.error().Describe());
    const auto request = RequestFor(chosen, context, library);
    Check(request && std::get<int64_t>(request->params.at("mode")) == 0 &&
              std::get<double>(request->params.at("bias")) == -0.25 &&
              std::get<double>(request->params.at("amount")) == 0.75,
          "the request holds the stored parameters over the record's defaults (a boolean as an integer)");
    if (!request) return Finish();
    const render::Result<Raster> before_save = hlsl.EvaluateReference(*request, {{"Curvature", Curvature()}});
    Check(before_save.has_value(), "the certified family evaluates the committed request on the CPU lane",
          before_save ? "" : before_save.error().Describe());

    // 3.4: save, close, reopen; the pin and its evaluation are identical.
    store->Save(document);
    store->Close();
    store.reset();
    auto reopened = uzp::store::ProjectStore::Open(file);
    core::Document again(std::move(reopened.state));
    reopened.store->Attach(again);
    const core::Project& project = *again.snapshot().project;
    const core::ProceduralRef* pinned = GeneratorOf(project)->procedural ? &*GeneratorOf(project)->procedural : nullptr;
    Check(pinned != nullptr && *pinned == chosen && PinnedAssets(project) ==
                                                         std::vector<std::string>{"uzasset://test-generator/ridge@2"},
          "the reopened project pins uzasset://test-generator/ridge@2 with the same parameters and inputs");
    Check(!CheckPins(project, library).has_value(), "every pin of the reopened project resolves at its exact version");
    if (pinned == nullptr || !request) return Finish();
    const auto reopenedRequest = RequestFor(*pinned, context, library);
    Check(reopenedRequest && Signature(*reopenedRequest) == Signature(*request),
          "the reopened request has the same signature");
    if (!reopenedRequest) return Finish();
    const auto readmitted = Admit(*reopenedRequest, library, seam);
    Check(readmitted && *readmitted == &hlsl, "the reopened request is admitted by the same certified family");
    const render::Result<Raster> after_save = hlsl.EvaluateReference(*reopenedRequest, {{"Curvature", Curvature()}});
    Check(before_save && after_save && FirstDifference(*before_save, *after_save).empty() &&
              before_save->texels.size() == 64 * 64,
          "evaluation after save and reopen is identical, bit for bit (RES-04)",
          before_save && after_save ? FirstDifference(*before_save, *after_save) : "no raster");
    const AssetLibrary empty;
    const std::optional<UnsupportedProcedural> unpinned = CheckPins(project, empty);
    Check(unpinned && unpinned->reason == kNotInLibrary,
          "a library without that version refuses the pin on reopen; no other version is used");
    reopened.store->Close();
    return Finish();
}

// ── snapshot (phase3.2_proc-snapshot-backend 2.1-2.4, 3.2-3.4) ──────────────

/// 64x64 u16 codes, little-endian: a pattern that is not constant and has no empty chunk.
std::string U16Pattern() {
    std::string bytes;
    for (uint32_t i = 0; i < 64 * 64; ++i) {
        const uint32_t code = (i * 7919u + 1u) & 0xFFFFu;
        bytes.push_back(static_cast<char>(code & 0xFF));
        bytes.push_back(static_cast<char>(code >> 8));
    }
    return bytes;
}

/// The half-float bits of sample `i` of the colour snapshot: 1 + m/1024 for most samples, with a
/// subnormal (2^-24) at sample 1 and a negative zero at sample 2.
uint16_t HalfBits(uint32_t i) {
    if (i == 1) return 0x0001;
    if (i == 2) return 0x8000;
    return static_cast<uint16_t>(0x3C00u + (i * 31u) % 1024u);
}

std::string HalfPattern() {
    std::string bytes;
    for (uint32_t i = 0; i < 64 * 64 * 3; ++i) {
        const uint16_t bits = HalfBits(i);
        bytes.push_back(static_cast<char>(bits & 0xFF));
        bytes.push_back(static_cast<char>(bits >> 8));
    }
    return bytes;
}

/// The snapshot case's request: a Painter-named asset that no library holds, at 64 texels.
ProceduralRequest DirtRequest(const uzp::core::ProjectSettings& settings) {
    ProceduralRequest r;
    r.asset = Url("painter-generator", "dirt", "1");
    r.params = {{"amount", 0.5}, {"invert", int64_t{0}}, {"mode", std::string("cavity")}};
    r.inputs["Curvature"] = ImageInput{RasterSpec{64, ChannelFormat::U16, "linear", 1}, g_curvature};
    r.meshClass = "sphere";
    r.output = RasterSpec{64, ChannelFormat::U16, "linear", 1};
    r.seed = 7;
    r.outputId = "output";
    r.settings = EvaluationSettings(settings);
    return r;
}

/// Imports the curvature map as a project resource (sets `g_curvature`).
bool ImportCurvature(uzp::store::ProjectStore& store, uzp::core::Document& document) {
    namespace core = uzp::core;
    const Raster curvature = Curvature();
    std::string bytes(reinterpret_cast<const char*>(curvature.texels.data()), curvature.texels.size() * sizeof(float));
    const auto imported = store.Submit(
        document, core::MutationRequest{"resource_import", core::json::Object{{"name", "curvature"}}, "import", document.revision()},
        [&](core::Edit& edit) {
            const auto size = static_cast<std::int64_t>(bytes.size());
            g_curvature = store.StageResource(bytes, "application/octet-stream");
            core::ResourceMeta meta;
            meta.id = edit.AllocateId();
            meta.name = "curvature";
            meta.mime = "application/octet-stream";
            meta.size = size;
            meta.usage = "TEXTURE";
            meta.imported_at = "2026-10-20T00:00:00Z";
            edit.project().resources[g_curvature].push_back(meta);
        });
    return imported.result && imported.result->status == uzp::core::ResultStatus::committed;
}

std::string Describe(const std::optional<UnsupportedProcedural>& refusal) {
    return refusal ? refusal->Describe() : "served";
}

const uzp::core::json::Value* Find(const uzp::core::json::Value& value, std::string_view key) {
    const auto* object = std::get_if<uzp::core::json::Object>(&value.data);
    if (object == nullptr) return nullptr;
    const auto it = object->find(key);
    return it == object->end() ? nullptr : &it->second;
}

/// The keys of a JSON object, in order.
std::vector<std::string> Keys(const uzp::core::json::Value* value) {
    std::vector<std::string> keys;
    if (value == nullptr || !value->IsObject()) return keys;
    for (const auto& [key, member] : std::get<uzp::core::json::Object>(value->data)) keys.push_back(key);
    return keys;
}

/// The snapshots `project` holds, loaded from `store`, each compared with the recorded bytes.
bool SameSnapshots(uzp::store::ProjectStore& store, const uzp::core::Project& project,
                   const std::vector<std::pair<ProceduralRequest, std::string>>& recorded, std::string& detail) {
    const auto loaded = SnapshotBackend::Load(store, project);
    if (!loaded) {
        detail = loaded.error();
        return false;
    }
    if (loaded->size() != recorded.size()) {
        detail = std::to_string(loaded->size()) + " snapshots";
        return false;
    }
    for (const auto& [request, bytes] : recorded) {
        const auto stored = loaded->Stored(request);
        if (!stored || (*stored)->bytes != bytes || (*stored)->spec != request.output) {
            detail = stored ? "the bytes or spec of " + SignatureHash(request) + " differ" : stored.error().Describe();
            return false;
        }
    }
    return true;
}

int RunSnapshot(const fs::path& work) {
    namespace core = uzp::core;
    namespace json = uzp::core::json;
    namespace store = uzp::store;

    // Project A, with the curvature map the requests bind.
    core::Id generator = core::kNoId;
    core::DocumentState initial;
    initial.project_uuid = "6f1c2a3e-0000-4000-8000-0000000a3270";
    initial.project = GeneratorProject(generator);
    const fs::path file = work / "snapshot-a.uzp";
    fs::remove(file);
    auto a = store::ProjectStore::Create(file, initial);
    core::Document document(initial);
    a->Attach(document);
    Check(ImportCurvature(*a, document), "project A imports the curvature map (revision 1)");
    int keys = 0;
    const auto submit = [&](store::ProjectStore& s, core::Document& d, const std::function<void(core::Edit&)>& call) {
        const std::string key = "snapshot-" + std::to_string(++keys);
        return s.Submit(d, core::MutationRequest{"procedural_snapshot", json::Object{{"key", key}}, key, d.revision()}, call);
    };
    const core::ProjectSettings settings = document.snapshot().project->settings;

    // 2.1: the signature names every field of 05 §4, canonically, and hashes its canonical text.
    const ProceduralRequest grey = DirtRequest(settings);
    ProceduralRequest colour = grey;
    colour.outputId = "colour";
    colour.output = RasterSpec{64, ChannelFormat::F16, "linear", 3};
    colour.params["offset"] = ParamVector{{1.0, 2.5}};
    colour.params["tint"] = ParamColor{"Linear sRGB", {0.25, 0.5, 1.0}, 0.75};
    const json::Value signature = SignatureJson(grey);
    Check(Keys(&signature) == std::vector<std::string>{"asset", "inputs", "mesh", "output", "params", "preset", "seed",
                                                       "settings", "version"} &&
              Keys(Find(signature, "output")) ==
                  std::vector<std::string>{"channels", "colour_space", "format", "id", "resolution"} &&
              Keys(Find(*Find(signature, "inputs"), "Curvature")) ==
                  std::vector<std::string>{"channels", "colour_space", "format", "resolution", "sha256"} &&
              Keys(Find(signature, "mesh")) == std::vector<std::string>{"class", "uv_tiles"} &&
              Keys(Find(signature, "settings")) ==
                  std::vector<std::string>{"color_management.config_hash", "color_management.io_rules_sha256",
                                           "color_management.mode", "color_management.working_space",
                                           "mesh_unit_scale", "normal_map_format", "tangent_space"} &&
              *Find(signature, "asset") == json::Value("uzasset://painter-generator/dirt") &&
              *Find(signature, "version") == json::Value("1"),
          "the signature names asset id, version, effective parameters, preset, seed, output id, resolution, format, "
          "colour space, channels, image inputs by hash, mesh and the project settings (2.1)",
          Signature(grey));
    Check(Signature(grey) == json::WriteCanonical(json::Parse(Signature(grey))) &&
              SignatureHash(grey) == uzp::core::Sha256Hex(Signature(grey)),
          "the signature is canonical JSON and its hash is the SHA-256 of that text (2.1)");
    ProceduralRequest byValue = grey;
    byValue.params["invert"] = 0.0;
    byValue.params["amount"] = 0.5;
    byValue.tile = TileRect{0, 0, 16, 16};
    ProceduralRequest nan = grey;
    nan.params["amount"] = std::nan("");
    ProceduralRequest nanText = grey;
    nanText.params["amount"] = std::string("nan");
    Check(SignatureHash(byValue) == SignatureHash(grey) && SignatureHash(nan) != SignatureHash(nanText) &&
              SignatureHash(nan) != SignatureHash(grey),
          "numbers compare by value (0 == 0.0), the tile is left out, a non-finite number is not its text (2.1)");

    // 2.3: both snapshots recorded in one commit, as raster planes with plane ids.
    const std::string greyBytes = U16Pattern();
    const std::string colourBytes = HalfPattern();
    core::Id greyPlane = core::kNoId;
    core::Id colourPlane = core::kNoId;
    const auto recorded = submit(*a, document, [&](core::Edit& edit) {
        greyPlane = RecordSnapshot(*a, edit, grey, greyBytes);
        colourPlane = RecordSnapshot(*a, edit, colour, colourBytes);
    });
    Check(recorded.result && recorded.result->status == core::ResultStatus::committed && document.revision() == 2 &&
              greyPlane != core::kNoId && colourPlane != core::kNoId && greyPlane != colourPlane,
          "two snapshots are recorded in one commit as raster planes with their own plane ids (2.3)",
          recorded.result ? json::WriteCanonical(recorded.result->ToJson()) : "no result");
    const std::vector<store::SnapshotEntry> entries = store::ProjectSnapshots(*document.snapshot().project);
    Check(entries.size() == 2 && entries[0].error.empty() && entries[1].error.empty() &&
              ((entries[0].key == SignatureHash(grey) && entries[1].key == SignatureHash(colour)) ||
               (entries[0].key == SignatureHash(colour) && entries[1].key == SignatureHash(grey))) &&
              entries[0].project_uuid == initial.project_uuid && entries[1].project_uuid == initial.project_uuid,
          "the manifest holds each signature under its SHA-256, with the project's uuid and its plane binding (2.3)");
    Check(a->ReadPlane(2, greyPlane).texels == greyBytes && a->ReadPlane(2, greyPlane).format == core::ChannelFormat::L16 &&
              a->ReadPlane(2, colourPlane).texels == colourBytes &&
              a->ReadPlane(2, colourPlane).format == core::ChannelFormat::RGB16F,
          "the planes hold the recorded texels unmodified (L16 and RGB16F)");
    const auto again = submit(*a, document, [&](core::Edit& edit) { RecordSnapshot(*a, edit, grey, greyBytes); });
    ProceduralRequest tiled = grey;
    tiled.tile = TileRect{0, 0, 8, 8};
    const auto tiledRecord = submit(*a, document, [&](core::Edit& edit) { RecordSnapshot(*a, edit, tiled, greyBytes); });
    ProceduralRequest rgba = grey;
    rgba.output.channels = 4;
    const auto rgbaRecord = submit(*a, document, [&](core::Edit& edit) { RecordSnapshot(*a, edit, rgba, greyBytes); });
    Check(again.result && again.result->status != core::ResultStatus::committed && tiledRecord.result &&
              tiledRecord.result->status != core::ResultStatus::committed && rgbaRecord.result &&
              rgbaRecord.result->status != core::ResultStatus::committed && document.revision() == 2,
          "a second snapshot of one signature, a tile and a 4-channel output are refused; nothing commits");

    // 2.2: served on the exact signature only, byte for byte; status is unavailable.
    auto loaded = SnapshotBackend::Load(*a, *document.snapshot().project);
    Check(loaded && loaded->size() == 2, "the project's snapshots load through their plane bindings",
          loaded ? "" : loaded.error());
    if (!loaded) return Finish();
    SnapshotBackend& snapshots = *loaded;
    const ParityStatus status = snapshots.Status(grey.asset);
    Check(status.kind == ParityStatus::Kind::Unavailable && status.reason == kSnapshotStatus,
          "SnapshotBackend.status is unavailable: a snapshot certifies no asset (2.2, decision 222)");
    const auto greyStored = snapshots.Stored(grey);
    const auto colourStored = snapshots.Stored(colour);
    Check(snapshots.CanEvaluate(grey) && snapshots.CanEvaluate(colour) && greyStored &&
              (*greyStored)->bytes == greyBytes && colourStored && (*colourStored)->bytes == colourBytes &&
              snapshots.CanEvaluate(byValue),
          "the exact signature is served, byte for byte (2.2)");
    const render::Result<Raster> whole = snapshots.Evaluate(grey, {}).get();
    bool codes = whole && whole->width == 64 && whole->height == 64 && whole->channels == 1;
    for (uint32_t i = 0; codes && i < 64 * 64; ++i) {
        const uint32_t code = (i * 7919u + 1u) & 0xFFFFu;
        codes = Bits(whole->texels[i]) == Bits(static_cast<float>(code) / 65535.0f);
    }
    Check(codes, "evaluate returns the stored u16 codes as code / 65535, every texel",
          whole ? "" : whole.error().Describe());
    const render::Result<Raster> half = snapshots.Evaluate(colour, {}).get();
    Check(half && half->channels == 3 && half->texels.size() == 64 * 64 * 3 && half->texels[0] == 1.0f &&
              Bits(half->texels[1]) == Bits(std::ldexp(1.0f, -24)) && Bits(half->texels[2]) == 0x80000000u &&
              half->texels[3] == 1.0f + static_cast<float>((3u * 31u) % 1024u) / 1024.0f,
          "evaluate widens the stored halves exactly (normal, subnormal, negative zero)");
    ProceduralRequest tile = grey;
    tile.tile = TileRect{8, 16, 4, 2};
    const render::Result<Raster> cut = snapshots.Evaluate(tile, {}).get();
    bool cropped = cut && cut->width == 4 && cut->height == 2 && whole;
    for (uint32_t y = 0; cropped && y < 2; ++y) {
        for (uint32_t x = 0; cropped && x < 4; ++x) {
            cropped = Bits(cut->texels[y * 4 + x]) == Bits(whole->texels[(16 + y) * 64 + 8 + x]);
        }
    }
    ProceduralRequest outside = grey;
    outside.tile = TileRect{60, 0, 8, 8};
    Check(cropped && !snapshots.CanEvaluate(outside) && snapshots.Refusal(outside)->field == "tile",
          "a tile is a copy of the stored texels; a tile outside the output is refused");

    // 3.2: each signature field changed in turn is unavailable; nothing is resampled or extrapolated.
    struct Mismatch {
        std::string name;
        std::function<void(ProceduralRequest&)> change;
        std::string field;
    };
    const auto setting = [&](const std::function<void(core::ProjectSettings&)>& change) {
        core::ProjectSettings changed = settings;
        change(changed);
        return EvaluationSettings(changed);
    };
    const std::vector<Mismatch> mismatches{
        {"a parameter value", [](ProceduralRequest& r) { r.params["amount"] = std::nextafter(0.5, 1.0); }, "params.amount"},
        {"a default parameter left out", [](ProceduralRequest& r) { r.params.erase("invert"); }, "params.invert"},
        {"a parameter added", [](ProceduralRequest& r) { r.params["gain"] = int64_t{1}; }, "params.gain"},
        {"a parameter of another type", [](ProceduralRequest& r) { r.params["mode"] = int64_t{1}; }, "params.mode"},
        {"the preset", [](ProceduralRequest& r) { r.preset = "Dusty"; }, "preset"},
        {"the seed", [](ProceduralRequest& r) { r.seed = 8; }, "seed"},
        {"a larger resolution (no resampling)", [](ProceduralRequest& r) { r.output.resolution = 128; }, "output.resolution"},
        {"a smaller resolution (no resampling)", [](ProceduralRequest& r) { r.output.resolution = 32; }, "output.resolution"},
        {"the channel format", [](ProceduralRequest& r) { r.output.format = ChannelFormat::F32; }, "output.format"},
        {"the colour space", [](ProceduralRequest& r) { r.output.colourSpace = "srgb"; }, "output.colour_space"},
        {"the channel count", [](ProceduralRequest& r) { r.output.channels = 3; }, "output.channels"},
        {"the output id", [](ProceduralRequest& r) { r.outputId = "height"; }, "output.id"},
        {"an image-input hash", [](ProceduralRequest& r) { r.inputs["Curvature"].sha256 = std::string(64, 'd'); },
         "inputs.Curvature.sha256"},
        {"an image-input resolution", [](ProceduralRequest& r) { r.inputs["Curvature"].spec.resolution = 32; },
         "inputs.Curvature.resolution"},
        {"an image-input colour space", [](ProceduralRequest& r) { r.inputs["Curvature"].spec.colourSpace = "srgb"; },
         "inputs.Curvature.colour_space"},
        {"an image input left out", [](ProceduralRequest& r) { r.inputs.clear(); }, "inputs.Curvature"},
        {"the mesh class", [](ProceduralRequest& r) { r.meshClass = "bevelled-cube"; }, "mesh.class"},
        {"the UV tiles", [](ProceduralRequest& r) { r.uvTiles = 2; }, "mesh.uv_tiles"},
        {"the asset version", [](ProceduralRequest& r) { r.asset.version = "2"; }, "version"},
        {"the project's normal map format",
         [&](ProceduralRequest& r) { r.settings = setting([](core::ProjectSettings& s) { s.normal_map_format = core::NormalMapFormat::DirectX; }); },
         "settings.normal_map_format"},
        {"the project's tangent space",
         [&](ProceduralRequest& r) { r.settings = setting([](core::ProjectSettings& s) { s.tangent_space = core::TangentSpace::PerFragment; }); },
         "settings.tangent_space"},
        {"the project's mesh unit scale",
         [&](ProceduralRequest& r) { r.settings = setting([](core::ProjectSettings& s) { s.mesh_unit_scale = 0.01; }); },
         "settings.mesh_unit_scale"},
        {"the project's colour management mode",
         [&](ProceduralRequest& r) { r.settings = setting([](core::ProjectSettings& s) { s.color_management.mode = "ocio"; }); },
         "settings.color_management.mode"},
        {"the project's OCIO configuration",
         [&](ProceduralRequest& r) { r.settings = setting([](core::ProjectSettings& s) { s.color_management.config_hash = std::string(64, 'e'); }); },
         "settings.color_management.config_hash"},
        {"the project's working colour space",
         [&](ProceduralRequest& r) { r.settings = setting([](core::ProjectSettings& s) { s.color_management.working_space = "ACEScg"; }); },
         "settings.color_management.working_space"},
        {"the project's colour rules",
         [&](ProceduralRequest& r) {
             r.settings = setting([](core::ProjectSettings& s) { s.color_management.io_rules.push_back(json::Object{{"pattern", "*"}}); });
         },
         "settings.color_management.io_rules_sha256"},
        {"another asset id (the project holds no snapshot of it)", [](ProceduralRequest& r) { r.asset.id = "dust"; }, ""},
    };
    const ProceduralSeam seam(&snapshots, nullptr);
    for (const Mismatch& m : mismatches) {
        ProceduralRequest changed = grey;
        m.change(changed);
        const std::optional<UnsupportedProcedural> refusal = snapshots.Refusal(changed);
        const auto selected = seam.Select(changed);
        const auto evaluated = seam.Evaluate(changed, {});
        Check(SignatureHash(changed) != SignatureHash(grey) && !snapshots.CanEvaluate(changed) && refusal &&
                  refusal->reason == kNoSnapshot && refusal->field == m.field && !snapshots.Stored(changed) &&
                  !selected && selected.error().reason == kNoBackend && !evaluated,
              "unavailable, the seam refuses and evaluates nothing: " + m.name + " (3.2)", Describe(refusal));
    }

    // Snapshots do not make assets editable: the exact signature is admitted, an edited parameter
    // is refused before the mutation commits (no certified family, an empty library).
    const AssetLibrary library;
    UseContext context;
    context.meshClass = "sphere";
    context.output = grey.output;
    context.inputs["Curvature"] = grey.inputs.at("Curvature").spec;
    context.seed = 7;
    context.outputId = "output";
    context.settings = EvaluationSettings(document.snapshot().project->settings);
    core::ProceduralRef ref;
    ref.asset = "uzasset://painter-generator/dirt@1";
    ref.params = {{"amount", 0.5}, {"invert", false}, {"mode", "cavity"}};
    ref.image_inputs["Curvature"] = core::ResourceBinding{g_curvature, std::nullopt, {}};
    const SubmitEdit edit = [&](const std::function<void(core::Edit&)>& call) { return submit(*a, document, call); };
    const auto served = SetEffectProcedural(generator, ref, context, library, seam, edit);
    Check(served && served->result && served->result->status == core::ResultStatus::committed && document.revision() == 3 &&
              GeneratorOf(*document.snapshot().project)->procedural == ref,
          "the exact signature is admitted through the snapshot and committed (revision 3)",
          served ? "" : served.error().Describe());
    core::ProceduralRef edited = ref;
    edited.params["amount"] = 0.6;
    const auto refused = SetEffectProcedural(generator, edited, context, library, seam, edit);
    Check(!refused && document.revision() == 3 && GeneratorOf(*document.snapshot().project)->procedural == ref,
          "a parameter edit of the snapshot-served source raises UnsupportedProcedural before the mutation commits",
          refused ? "admitted" : refused.error().Describe());

    // 3.3: save, close and reopen keep both snapshots bit-exact; inspect --verify passes.
    a->Save(document);
    a->Close();
    a.reset();
    const std::vector<std::pair<ProceduralRequest, std::string>> both{{grey, greyBytes}, {colour, colourBytes}};
    {
        auto reopened = store::ProjectStore::Open(file);
        core::Document opened(std::move(reopened.state));
        reopened.store->Attach(opened);
        std::string detail;
        Check(reopened.report.ok() && SameSnapshots(*reopened.store, *opened.snapshot().project, both, detail),
              "save and reopen keep both snapshots bit-exact (3.3)", detail);
        reopened.store->Close();
    }
    const json::Value inspected = store::Inspect(file, store::InspectOptions{std::nullopt, true, nullptr});
    const json::Value* verify = Find(inspected, "verify");
    const json::Value* listed = Find(inspected, "procedural_snapshots");
    bool rows = listed != nullptr && listed->IsArray() && std::get<json::Array>(listed->data).size() == 2;
    if (rows) {
        for (const json::Value& row : std::get<json::Array>(listed->data)) {
            const json::Value* plane = Find(row, "plane_id");
            rows = rows && plane != nullptr && plane->IsInt() && Find(row, "width") != nullptr &&
                   *Find(row, "width") == json::Value(64) && Find(row, "project_uuid") != nullptr &&
                   *Find(row, "project_uuid") == json::Value(initial.project_uuid);
        }
    }
    Check(verify != nullptr && Find(*verify, "ok") != nullptr && *Find(*verify, "ok") == json::Value(true) && rows,
          "inspect --verify passes and lists both snapshots with their plane ids (3.3)",
          verify ? json::WriteCanonical(*verify) : "no verify");

    // 2.3: export-bundle carries the snapshot planes; the bundle imports them bit-exact.
    const fs::path bundle = work / "snapshot-a-bundle";
    fs::remove_all(bundle);
    fs::remove(store::BundleImportTarget(bundle));
    const store::BundleSummary exported = store::ExportBundle(file, bundle);
    Check(exported.planes == 2 && fs::exists(bundle / ("planes/" + std::to_string(greyPlane) + ".png")) &&
              fs::exists(bundle / ("planes/" + std::to_string(colourPlane) + ".exr")),
          "export-bundle writes both snapshot planes (PNG for u16, EXR for half) (2.3)");
    {
        auto imported = store::ProjectStore::Open(bundle);
        core::Document opened(std::move(imported.state));
        imported.store->Attach(opened);
        std::string detail;
        Check(imported.store->project_uuid() == initial.project_uuid &&
                  SameSnapshots(*imported.store, *opened.snapshot().project, both, detail),
              "the imported bundle holds both snapshots bit-exact (2.3)", detail);
        imported.store->Close();
    }
    const json::Value importedVerify = store::Inspect(store::BundleImportTarget(bundle), store::InspectOptions{std::nullopt, true, nullptr});
    Check(Find(importedVerify, "verify") != nullptr && *Find(*Find(importedVerify, "verify"), "ok") == json::Value(true),
          "inspect --verify passes on the imported bundle");

    // 3.4: a bundle whose manifest carries a snapshot entry of another project is refused on
    // import (the manifest and its digest rewritten consistently, only the entry's uuid changed).
    const fs::path tampered = work / "snapshot-tampered-bundle";
    fs::remove_all(tampered);
    fs::remove(store::BundleImportTarget(tampered));
    fs::copy(bundle, tampered, fs::copy_options::recursive);
    const auto readText = [](const fs::path& path) {
        std::ifstream in(path, std::ios::binary);
        return std::string(std::istreambuf_iterator<char>(in), {});
    };
    const auto writeText = [](const fs::path& path, const std::string& text) {
        std::ofstream(path, std::ios::binary | std::ios::trunc) << text;
    };
    json::Value manifest = json::Parse(readText(tampered / "manifest.json"));
    for (auto& [key, entry] : std::get<json::Object>(std::get<json::Object>(manifest.data).at(std::string(store::kSnapshotsKey)).data)) {
        std::get<json::Object>(entry.data)["project_uuid"] = "6f1c2a3e-0000-4000-8000-0000000c3270";
    }
    const std::string manifestText = json::WriteCanonical(manifest);
    writeText(tampered / "manifest.json", manifestText);
    json::Value index = json::Parse(readText(tampered / "bundle.json"));
    std::get<json::Object>(index.data)["manifest_sha256"] = uzp::core::Sha256Hex(manifestText);
    writeText(tampered / "bundle.json", store::WriteIndented(index));
    std::string importError;
    try {
        auto opened = store::ProjectStore::Open(tampered);
        opened.store->Close();
    } catch (const std::exception& error) {
        importError = error.what();
    }
    Check(importError.find("recorded for project 6f1c2a3e-0000-4000-8000-0000000c3270") != std::string::npos &&
              !fs::exists(store::BundleImportTarget(tampered)),
          "a bundle carrying another project's snapshot entry is refused on import and leaves no file (3.4)",
          importError.empty() ? "imported" : importError);

    // 3.4: a snapshot is never copied into another project.
    core::Id otherGenerator = core::kNoId;
    core::DocumentState otherInitial;
    otherInitial.project_uuid = "6f1c2a3e-0000-4000-8000-0000000b3270";
    otherInitial.project = GeneratorProject(otherGenerator);
    const fs::path otherFile = work / "snapshot-b.uzp";
    fs::remove(otherFile);
    auto b = store::ProjectStore::Create(otherFile, otherInitial);
    core::Document other(otherInitial);
    b->Attach(other);
    Check(ImportCurvature(*b, other), "project B imports the same curvature map");
    const core::Project projectA = [&] {
        auto reopened = store::ProjectStore::Open(file);
        core::Project p = *core::Document(std::move(reopened.state)).snapshot().project;
        reopened.store->Close();
        return p;
    }();
    const json::Value copiedEntries = projectA.extra.at(std::string(store::kSnapshotsKey));
    const auto copied = submit(*b, other, [&](core::Edit& e) {
        e.project().extra[std::string(store::kSnapshotsKey)] = copiedEntries;
    });
    Check(copied.result && copied.result->status != core::ResultStatus::committed && other.revision() == 1 &&
              store::ProjectSnapshots(*other.snapshot().project).empty() &&
              json::WriteCanonical(copied.result->ToJson()).find("recorded for project " + initial.project_uuid) !=
                  std::string::npos,
          "committing project A's snapshot entries into project B is refused; B is unchanged (3.4)",
          copied.result ? json::WriteCanonical(copied.result->ToJson()) : "no result");
    core::Project grafted = *other.snapshot().project;
    grafted.extra[std::string(store::kSnapshotsKey)] = copiedEntries;
    const auto foreign = SnapshotBackend::Load(*b, grafted);
    Check(!foreign && foreign.error().find("recorded for project " + initial.project_uuid) != std::string::npos,
          "project B's snapshot backend refuses an entry recorded for project A (3.4)",
          foreign ? "loaded" : foreign.error());
    auto otherLoaded = SnapshotBackend::Load(*b, *other.snapshot().project);
    Check(otherLoaded && otherLoaded->size() == 0, "project B holds no snapshot");
    if (!otherLoaded) return Finish();
    const ProceduralSeam otherSeam(&*otherLoaded, nullptr);
    const auto copiedRef = SetEffectProcedural(otherGenerator, ref, context, library, otherSeam,
                                               [&](const std::function<void(core::Edit&)>& call) { return submit(*b, other, call); });
    Check(!copiedRef && other.revision() == 1 && GeneratorOf(*other.snapshot().project)->procedural == std::nullopt,
          "the layer's procedural copied into project B raises UnsupportedProcedural there: no snapshot came along (3.4)",
          copiedRef ? "admitted" : copiedRef.error().Describe());
    b->Close();
    return Finish();
}

#include "typed_params_cases.h"
#include "resolution_cases.h"
#include "snapshot_recording_cases.h"

}  // namespace

// ── observations (decision 362, phase3.1 item 2.6g) ──────────────────────────────────────────

/// The reserved observation family is refused on every procedural path, independently of any
/// registry or lookup and whatever its id and version.
int RunObservations() {
    const std::string hex(64, 'a');
    const std::string pin = "uzasset://observation/" + hex + "@1";
    Check(uzp::core::IsObservationPin(pin) && uzp::core::IsObservationAsset(pin), "a descriptor pin is recognized");
    const std::vector<std::string> malformedAssets = {
        "uzasset://observation/" + hex + "@2", "uzasset://observation/" + std::string(64, 'A') + "@1",
        "uzasset://observation/short@1", "uzasset://observation", "uzasset://observation@1"};
    for (const std::string& malformed : malformedAssets) {
        Check(uzp::core::IsObservationAsset(malformed) && !uzp::core::IsObservationPin(malformed),
              "a malformed member of the family is still of the family, and no pin", malformed);
        Check(ObservationRefusal(malformed).has_value(), "a malformed member of the family is refused", malformed);
    }
    Check(!uzp::core::IsObservationAsset("uzasset://observations/" + hex + "@1") &&
              !uzp::core::IsObservationAsset("uzasset://test-synthetic/observation@1") &&
              !ObservationRefusal(std::string("uzasset://test-synthetic/ridge@2")).has_value(),
          "only the family itself is reserved");

    ProceduralRequest reserved = SyntheticRequest();
    reserved.asset = Url("observation", hex, "1");
    const auto isReserved = [](const std::optional<UnsupportedProcedural>& refusal) {
        return refusal && refusal->reason == kObservationNotExecutable;
    };

    // HLSL: never registered, found, planned or evaluated (reference and candidate lanes).
    HlslBackend hlsl(nullptr);
    const auto registered = hlsl.Register(std::make_shared<SyntheticExact>(reserved.asset));
    Check(!registered && registered.error().find("reserved observation family") != std::string::npos,
          "a family pinned in the reserved family is not registered");
    auto synthetic = std::make_shared<SyntheticExact>();
    Check(hlsl.Register(synthetic).has_value(), "an ordinary family still registers");
    Check(isReserved(hlsl.Refusal(reserved)) && !hlsl.CanEvaluate(reserved), "the HLSL backend refuses the family");
    const auto kernels = hlsl.Kernels(reserved);
    Check(!kernels && kernels.error().reason == kObservationNotExecutable, "no kernel is planned for the family");
    const render::Result<Raster> reference = hlsl.EvaluateReference(reserved, {{"Curvature", Curvature()}});
    const render::Result<Raster> candidate =
        hlsl.EvaluateCandidate(reserved, {{"Curvature", Curvature()}}).get();
    Check(!reference && !candidate && synthetic->plans == 0 && synthetic->references == 0,
          "the reference and candidate lanes evaluate nothing for the family");

    // Snapshots: never added, served or described.
    SnapshotBackend snapshots;
    bool added = true;
    try {
        snapshots.Add(reserved, SnapshotRaster{RasterSpec{64, ChannelFormat::F32, "linear", 1}, std::string(64 * 64 * 4, '\0')});
    } catch (const uzp::core::ValueError&) {
        added = false;
    }
    Check(!added, "the snapshot backend does not add the family");
    Check(isReserved(snapshots.Refusal(reserved)) && !snapshots.CanEvaluate(reserved),
          "the snapshot backend refuses the family");
    const auto stored = snapshots.Stored(reserved);
    const auto metadata = snapshots.Metadata(reserved);
    Check(!stored && stored.error().reason == kObservationNotExecutable && !metadata &&
              metadata.error().reason == kObservationNotExecutable,
          "the snapshot backend serves no raster or metadata for the family");
    Check(!snapshots.Evaluate(reserved, {}).get(), "the snapshot backend evaluates nothing for the family");

    // The seam, the library and admission.
    ProceduralSeam seam(&snapshots, &hlsl);
    const auto selected = seam.Select(reserved);
    Check(!selected && selected.error().reason == kObservationNotExecutable, "the seam selects no backend", Describe(selected));
    const AssetLibrary library;
    const auto resolved = library.Resolve(reserved.asset);
    Check(library.Find(reserved.asset) == nullptr && !resolved && resolved.error().reason == kObservationNotExecutable,
          "the library neither finds nor resolves the family");
    uzp::core::ProceduralRef ref;
    ref.asset = "uzasset://observation/not-a-pin@x";
    const auto request = RequestFor(ref, UseContext{}, library);
    Check(!request && request.error().reason == kObservationNotExecutable,
          "admission refuses a malformed member of the family before parsing it");
    const auto admitted = Admit(reserved, library, seam);
    Check(!admitted && admitted.error().reason == kObservationNotExecutable, "admission refuses the family");
    return Finish();
}

/// Authored observations only: no captured identity, parameters or pixels enter this fixture.
int RunObservationSource(const fs::path& work) {
    namespace core = uzp::core;
    namespace json = core::json;
    namespace store = uzp::store;
    using json::Object;
    using json::Array;
    using json::Value;
    core::Id filterId = core::kNoId;
    core::DocumentState initial;
    initial.project_uuid = "6f1c2a3e-0000-4000-8000-0000000a3620";
    initial.project = GeneratorProject(filterId);
    auto backing = store::ProjectStore::Create(work / "observation-source.uzp", initial);
    core::Document document(initial);
    backing->Attach(document);
    const std::string meshBytes = "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n";
    const std::string meshHash = core::Sha256Hex(meshBytes);
    const auto descriptor = [](const char* role, Object parameters) {
        return Object{{"schema", std::string(store::kObservationDescriptorSchema)}, {"role", std::string(role)},
                      {"resource_id", Object{{"url", std::string("resource://authored/") + role + "?version=1"},
                                             {"context", std::string("authored")}, {"name", std::string(role)},
                                             {"version", std::string("1")}}},
                      {"parameters", std::move(parameters)}};
    };
    const Object hostDescriptor = descriptor("host", {{"amount", 1.0}});
    const Object filterDescriptor = descriptor("filter", {{"radius", 1.0}, {"zero", -0.0}});
    const std::string hostKey = store::ObservationKey(hostDescriptor);
    const std::string filterKey = store::ObservationKey(filterDescriptor);
    bool prospectiveRead = false;
    auto created = backing->Submit(document, {"observation-source-test", Object{}, "setup", document.revision()},
                                   [&](core::Edit& edit) {
        auto& project = edit.project();
        backing->StageResource(meshBytes, "model/obj");
        core::ResourceMeta meta;
        meta.id = edit.AllocateId();
        meta.name = "authored.obj";
        meta.mime = "model/obj";
        meta.usage = "MESH";
        meta.size = static_cast<std::int64_t>(meshBytes.size());
        project.resources[meshHash] = {meta};
        project.mesh.emplace();
        project.mesh->resource = meshHash;
        auto& host = project.texture_sets[0].stacks[0].root_layers[0];
        host.fill->active_channels = {core::ChannelType::BaseColor};
        core::ProceduralSource source;
        source.ref.asset = store::ObservationPin(hostKey);
        source.ref.params = {{"amount", std::int64_t{1}}};
        host.fill->sources[core::ChannelType::BaseColor] = core::Source{source};
        auto& filter = host.content_effects[0];
        filter.kind = core::EffectKind::filter;
        filter.procedural.emplace();
        filter.procedural->asset = store::ObservationPin(filterKey);
        filter.procedural->params = {{"radius", std::int64_t{1}}, {"zero", 0.0}};
        prospectiveRead = CurrentFilterObservationContext(*backing, project).has_value();
    });
    Check(created.result && created.result->status == core::ResultStatus::committed && prospectiveRead,
          "context reads staged mesh bytes inside Submit without another snapshot");
    if (!created.result || created.result->status != core::ResultStatus::committed) return Finish();
    core::Project base = *document.snapshot().project;
    const auto seal = [&](core::Project& project, Object rawFilter, bool includeObservations = true) {
        const std::string rawKey = store::ObservationKey(rawFilter);
        auto& host = project.texture_sets[0].stacks[0].root_layers[0];
        auto& filter = host.content_effects[0];
        filter.procedural->asset = store::ObservationPin(rawKey);
        const auto context = CurrentFilterObservationContext(*backing, project);
        Check(context.has_value(), "authored observation context constructs");
        if (!context) return;
        Object observed;
        if (includeObservations) {
            observed = {{"parameters", rawFilter.at("parameters")}, {"resource_id", rawFilter.at("resource_id")},
                        {"image_outputs", Array{}}};
        }
        const auto& set = project.texture_sets[0];
        const auto& stack = set.stacks[0];
        Object entry{
            {"schema", std::string(store::kObservationEntrySchema)}, {"project_uuid", backing->project_uuid()},
            {"role", std::string("filter")}, {"host_descriptor", hostKey}, {"filter_descriptor", rawKey},
            {"binding", Object{{"texture_set", set.id}, {"stack", stack.id}, {"host_uid", host.uid},
                               {"filter_uid", filter.uid}, {"node_stack", std::string("Content")},
                               {"effect_index", 0}, {"host_channel", std::string("BaseColor")},
                               {"host_reference", core::ProceduralRefToJson(
                                   std::get<core::ProceduralSource>(host.fill->sources.at(core::ChannelType::BaseColor).value).ref)},
                               {"filter_reference", core::ProceduralRefToJson(*filter.procedural)}}},
            {"context", *context}, {"context_sha256", store::ObservationKey(*context)},
            {"capture", Object{{"recorder", std::string("authored")}, {"envelope_id", std::string("authored")},
                               {"painter_build_id", std::string("authored")}, {"recipe_sha256", core::Sha256Hex("recipe")},
                               {"resource_query", std::string("authored")}, {"authored_inputs", Array{}},
                               {"receipts", Array{Object{{"condition", std::string("same_session")},
                                                         {"sha256", core::Sha256Hex("r1")}},
                                                  Object{{"condition", std::string("after_save_reopen")},
                                                         {"sha256", core::Sha256Hex("r2")}}}}}},
            {"observations", observed}};
        const std::string key = store::ObservationKey(entry);
        project.extra[std::string(store::kFilterObservationsKey)] = Object{
            {"schema", std::string(store::kFilterObservationsSchema)},
            {"descriptors", Object{{hostKey, hostDescriptor}, {rawKey, rawFilter}}},
            {"entries", Object{{key, entry}}},
            {"host_bindings", Object{{std::to_string(host.uid), Object{{"channel", std::string("BaseColor")},
                                                                       {"descriptor", hostKey}}}}},
            {"bindings", Object{{std::to_string(filter.uid), key}}}};
    };
    seal(base, filterDescriptor);
    const auto original = ObservedFilter(*backing, base, filterId);
    Check(original && original->parameters && original->resource_id && original->image_outputs &&
              original->image_outputs->empty() &&
              json::WriteCanonical(original->parameters->at("radius")) == json::WriteCanonical(Value(1.0)) &&
              std::signbit(std::get<double>(original->parameters->at("zero").data)),
          "raw parameter types and signed zero survive numeric core matching and empty output observation");
    const auto refused = [&](const char* name, const std::function<void(core::Project&)>& change) {
        core::Project altered = base;
        change(altered);
        Check(!ObservedFilter(*backing, altered, filterId), name);
    };
    refused("upstream content change makes observation stale", [](core::Project& p) {
        std::get<core::ProceduralSource>(p.texture_sets[0].stacks[0].root_layers[0].fill->sources.begin()->second.value)
            .ref.params["amount"] = 2;
    });
    Check(ObservedFilter(*backing, base, filterId).has_value(), "restored context matches the immutable observation");
    refused("complete reference extras are part of the binding", [](core::Project& p) {
        p.texture_sets[0].stacks[0].root_layers[0].content_effects[0].procedural->extra["changed"] = true;
    });
    refused("channel format changes invalidate context", [](core::Project& p) {
        p.texture_sets[0].stacks[0].channels.begin()->second.format = core::ChannelFormat::RGB16;
    });
    refused("position changes invalidate context", [](core::Project& p) {
        ++p.texture_sets[0].stacks[0].root_layers[0].uid;
    });
    refused("mesh identity changes invalidate context", [](core::Project& p) { p.mesh->resource = core::Sha256Hex("other"); });
    refused("mesh MIME changes invalidate context", [](core::Project& p) { p.resources.begin()->second[0].mime = "changed"; });
    refused("mesh size must match bytes", [](core::Project& p) { ++p.resources.begin()->second[0].size; });
    refused("conflicting mesh metadata refuses", [](core::Project& p) {
        auto meta = p.resources.begin()->second.front();
        meta.mime = "different";
        p.resources.begin()->second.push_back(meta);
    });
    refused("additional resource catalog entries refuse", [](core::Project& p) { p.resources[core::Sha256Hex("extra")] = {}; });
    refused("environment reference refuses", [&](core::Project& p) { p.display.environment.resource = meshHash; });
    refused("LUT reference refuses", [&](core::Project& p) { p.display.color_lut = meshHash; });
    refused("external mesh buffers refuse", [&](core::Project& p) {
        p.mesh->import_report["external_files"] = Array{Object{{"sha256", meshHash}}};
    });
    refused("mask refuses", [](core::Project& p) { p.texture_sets[0].stacks[0].root_layers[0].mask.emplace(); });
    refused("additional effects refuse", [](core::Project& p) {
        auto& effects = p.texture_sets[0].stacks[0].root_layers[0].content_effects;
        effects.push_back(effects.front());
    });
    refused("preset references refuse", [](core::Project& p) {
        p.texture_sets[0].stacks[0].root_layers[0].content_effects[0].procedural->preset = "authored";
    });
    refused("core boolean parameters refuse", [](core::Project& p) {
        p.texture_sets[0].stacks[0].root_layers[0].content_effects[0].procedural->params["radius"] = true;
    });
    refused("snapshot namespace must be validly empty", [](core::Project& p) { p.extra[std::string(store::kSnapshotsKey)] = nullptr; });
    refused("missing observation binding never falls back", [](core::Project& p) {
        std::get<Object>(std::get<Object>(p.extra.at(std::string(store::kFilterObservationsKey)).data).at("bindings").data).clear();
    });
    refused("absent namespace never falls back", [](core::Project& p) { p.extra.erase(std::string(store::kFilterObservationsKey)); });
    core::Project absent = base;
    seal(absent, filterDescriptor, false);
    const auto unobserved = ObservedFilter(*backing, absent, filterId);
    Check(unobserved && !unobserved->parameters && !unobserved->resource_id && !unobserved->image_outputs,
          "absent observations remain absent rather than empty");
    core::Project invalidRaw = base;
    Object badDescriptor = filterDescriptor;
    std::get<Object>(badDescriptor.at("parameters").data)["radius"] = true;
    seal(invalidRaw, badDescriptor);
    Check(!ObservedFilter(*backing, invalidRaw, filterId), "raw boolean observations refuse without coercion");
    core::Project numericMismatch = base;
    Object different = filterDescriptor;
    std::get<Object>(different.at("parameters").data)["radius"] = 2.0;
    seal(numericMismatch, different);
    Check(!ObservedFilter(*backing, numericMismatch, filterId), "numeric mismatch refuses after context resealing");
    core::Project emptySnapshots = base;
    emptySnapshots.extra[std::string(store::kSnapshotsKey)] = Object{};
    Check(CurrentFilterObservationContext(*backing, emptySnapshots).has_value(), "validly empty snapshots are permitted");
    Check(!ObservedFilter(*backing, base, filterId + 100), "another UID cannot borrow an observation");
    // Domain checks must refuse even before an entry exists, not merely because an old hash differs.
    const auto outsideDomain = [&](const char* name, const std::function<void(core::Project&)>& change) {
        core::Project altered = base;
        altered.extra.erase(std::string(store::kFilterObservationsKey));
        change(altered);
        Check(!CurrentFilterObservationContext(*backing, altered), name);
    };
    outsideDomain("V1 refuses masks before entry lookup", [](core::Project& p) {
        p.texture_sets[0].stacks[0].root_layers[0].mask.emplace();
    });
    outsideDomain("V1 refuses empty inclusion geometry mask before entry lookup", [](core::Project& p) {
        p.texture_sets[0].stacks[0].root_layers[0].geometry_mask.inclusion_list = true;
    });
    outsideDomain("V1 refuses nonempty exclusion geometry mask before entry lookup", [](core::Project& p) {
        p.texture_sets[0].stacks[0].root_layers[0].geometry_mask.items = {"authored"};
    });
    outsideDomain("V1 refuses instances before entry lookup", [](core::Project& p) {
        p.texture_sets[0].stacks[0].root_layers[0].instance_source = 99;
    });
    outsideDomain("V1 refuses anchor effects before entry lookup", [](core::Project& p) {
        p.texture_sets[0].stacks[0].root_layers[0].content_effects[0].anchor_name = "anchor";
    });
    outsideDomain("V1 refuses paint planes before entry lookup", [](core::Project& p) {
        auto& host = p.texture_sets[0].stacks[0].root_layers[0];
        host.kind = core::LayerKind::paint;
        host.paint.emplace();
        host.paint->planes[core::ChannelType::BaseColor] = 999;
    });
    outsideDomain("V1 refuses mono source before entry lookup", [](core::Project& p) {
        auto& fill = *p.texture_sets[0].stacks[0].root_layers[0].fill;
        fill.mono_source = fill.sources.begin()->second;
    });
    outsideDomain("V1 refuses material source before entry lookup", [](core::Project& p) {
        auto& fill = *p.texture_sets[0].stacks[0].root_layers[0].fill;
        fill.material_source = fill.sources.begin()->second;
    });
    outsideDomain("V1 refuses alternate source kinds before entry lookup", [](core::Project& p) {
        p.texture_sets[0].stacks[0].root_layers[0].fill->sources.begin()->second = core::Source{core::BitmapSource{}};
    });
    outsideDomain("V1 refuses external procedural inputs before entry lookup", [&](core::Project& p) {
        p.texture_sets[0].stacks[0].root_layers[0].content_effects[0].procedural->image_inputs["input"].sha256 = meshHash;
    });
    outsideDomain("V1 refuses mesh maps before entry lookup", [&](core::Project& p) {
        p.texture_sets[0].mesh_maps[core::MeshMapUsage::AO].resource = meshHash;
    });
    outsideDomain("V1 refuses extra resources before entry lookup", [](core::Project& p) {
        p.resources[core::Sha256Hex("extra")] = {};
    });
    outsideDomain("V1 refuses missing mesh bytes", [](core::Project& p) {
        auto metadata = p.resources.begin()->second;
        p.resources.clear();
        p.mesh->resource = core::Sha256Hex("not stored");
        p.resources[p.mesh->resource] = std::move(metadata);
    });
    outsideDomain("V1 refuses empty metadata", [](core::Project& p) { p.resources.begin()->second.clear(); });
    outsideDomain("V1 refuses empty MIME", [](core::Project& p) { p.resources.begin()->second[0].mime.clear(); });
    outsideDomain("V1 independently checks mesh size", [](core::Project& p) { ++p.resources.begin()->second[0].size; });
    outsideDomain("V1 requires metadata MIME consensus", [](core::Project& p) {
        auto meta = p.resources.begin()->second[0];
        meta.mime = "different";
        p.resources.begin()->second.push_back(meta);
    });
    outsideDomain("V1 refuses invalid core parameter types before entry lookup", [](core::Project& p) {
        p.texture_sets[0].stacks[0].root_layers[0].content_effects[0].procedural->params["radius"] = Array{};
    });
    bool prospectiveLookup = false;
    auto persisted = backing->Submit(document, {"observation-source-test", Object{}, "persist", document.revision()},
                                     [&](core::Edit& edit) {
        edit.project() = base;
        prospectiveLookup = ObservedFilter(*backing, edit.project(), filterId).has_value();
    });
    Check(persisted.result && persisted.result->status == core::ResultStatus::committed && prospectiveLookup,
          "sealed observation persists after prospective lookup inside Submit");
    backing->Save(document);
    backing->Close();
    auto reopened = store::ProjectStore::Open(work / "observation-source.uzp");
    core::Document reopenedDocument(std::move(reopened.state));
    const auto reopenedSnapshot = reopenedDocument.snapshot();
    const auto fresh = ObservedFilter(*reopened.store, *reopenedSnapshot.project, filterId);
    Check(reopened.report.ok() && fresh && original && fresh->entry_key == original->entry_key &&
              fresh->parameters &&
              json::WriteCanonical(fresh->parameters->at("radius")) == json::WriteCanonical(Value(1.0)) &&
              std::signbit(std::get<double>(fresh->parameters->at("zero").data)),
          "save reopen preserves entry key and raw double and signed zero for fresh lookup");
    reopened.store->Close();
    return Finish();
}

/// Decision 363: the V2 live lookup over a real snapshot-backed host, on the authored fixture.
int RunObservationSourceV2(const fs::path& work) {
    namespace core = uzp::core;
    namespace json = core::json;
    namespace store = uzp::store;
    namespace fx = uzp::v2fixture;
    using json::Object;
    using json::Value;
    const std::string plane = fx::PlaneObj();
    const Object descriptor = fx::FilterDescriptor();
    fx::SceneIds ids;
    core::DocumentState initial;
    initial.project_uuid = "6f1c2a3e-0000-4000-8000-0000000a3630";
    initial.project = fx::Scene(store::ObservationPin(store::ObservationKey(descriptor)), plane.size(), ids);
    store::CreateOptions options;
    options.resources = {store::PendingContent::Bytes{plane, "model/obj"}};
    const fs::path file = work / "observation-source-v2.uzp";
    auto backing = store::ProjectStore::Create(file, initial, options);
    core::Document document(initial);
    backing->Attach(document);
    int keys = 0;
    const auto submit = [&](const std::function<void(core::Edit&)>& call) {
        return backing->Submit(document,
                               {"observation-source-v2-test", Object{}, "v2-" + std::to_string(++keys), document.revision()},
                               call);
    };
    const auto committed = [](const core::RequestOutcome& outcome) {
        return outcome.result && outcome.result->status == core::ResultStatus::committed;
    };
    const auto hostOf = [](core::Project& project) -> core::Layer& { return project.texture_sets[0].stacks[0].root_layers[0]; };
    const auto hostRefOf = [&](core::Project& project) -> core::ProceduralRef& {
        return std::get<core::ProceduralSource>(hostOf(project).fill->sources.at(core::ChannelType::User0).value).ref;
    };
    // The provider's own request for the host with `amount`.
    const auto hostRequest = [&](const core::Project& project, double amount) {
        core::Project variant = project;
        hostRefOf(variant).params["amount"] = amount;
        core::Layer& host = hostOf(variant);
        auto request = SnapshotFillRequest(variant, variant.texture_sets[0], core::ChannelType::User0,
                                           core::ChannelFormat::L32F, *host.fill, hostRefOf(variant), host.uid, false);
        if (!request) throw std::runtime_error("host request: " + request.error());
        return *request;
    };

    // The host snapshot (the provider's exact request) and an inactive variant.
    std::string hostKey;
    std::string recordError;
    const auto recorded = submit([&](core::Edit& edit) {
        try {
            const ProceduralRequest host = hostRequest(edit.project(), 0.5);
            hostKey = SignatureHash(host);
            RecordSnapshot(*backing, edit, host, fx::Raster(1).texels, fx::Metadata(0.5));
            RecordSnapshot(*backing, edit, hostRequest(edit.project(), 0.25), fx::Raster(2).texels, fx::Metadata(0.25));
        } catch (const std::exception& error) {
            recordError = error.what();
            throw;
        }
    });
    Check(committed(recorded), "v2: the host snapshot and an inactive variant record", recordError);
    if (!committed(recorded)) return Finish();
    const core::Project scene = *document.snapshot().project;
    const auto context = CurrentFilterObservationContextV2(*backing, scene);
    Check(context.has_value(), "v2: the current context builds from one census", context ? std::string() : context.error());
    if (!context) return Finish();
    Check(json::WriteCanonical(*context) == json::WriteCanonical(fx::Context(*backing, scene)),
          "v2: the provider's context is the projection and the store's census");
    const std::string uuid = backing->project_uuid();
    const Object entry = fx::Entry(uuid, descriptor, *context, scene, hostKey);
    const Object space = fx::Namespace(descriptor, {entry}, ids.filter);
    const std::string structural = store::FilterObservationsProblem(space, uuid);
    Check(structural.empty(), "v2: the authored namespace is structurally valid", structural);
    const auto observe = submit([&](core::Edit& edit) { edit.project().extra[std::string(store::kFilterObservationsKey)] = space; });
    Check(committed(observe), "v2: the observation commits");
    if (!committed(observe)) return Finish();
    const core::Project observed = *document.snapshot().project;
    const auto works = [&](const core::Project& project) { return ObservedFilter(*backing, project, ids.filter).has_value(); };

    const auto found = ObservedFilter(*backing, observed, ids.filter);
    Check(found && found->parameters && found->resource_id && found->image_outputs && found->image_outputs->empty() &&
              json::WriteCanonical(found->parameters->at("radius")) == json::WriteCanonical(Value(1.0)) &&
              std::signbit(std::get<double>(found->parameters->at("zero").data)),
          "v2: a fresh lookup returns the raw observations, types and signed zero kept",
          found ? std::string() : found.error());

    // Stale current state refuses; the recorded state again is served.
    core::Project renamed = observed;
    hostOf(renamed).name = "renamed";
    Check(!works(renamed) && works(observed), "v2: an unrelated projection edit makes the lookup stale; the recorded state serves");
    // The host relation and roles.
    core::Project otherParams = observed;
    hostRefOf(otherParams).params["amount"] = 0.25;
    Check(!works(otherParams), "v2: host parameters of another (inactive) snapshot refuse");
    core::Project pinnedHost = observed;
    hostRefOf(pinnedHost).asset = store::ObservationPin(store::ObservationKey(descriptor));
    Check(!works(pinnedHost), "v2: a Filter observation pin never acts as the host");
    core::Project noPaint = observed;
    noPaint.texture_sets[0].stacks[0].root_layers[1].paint->planes[core::ChannelType::User0] = 999999;
    Check(!works(noPaint), "v2: an initial Paint layer holding content refuses");
    core::Project otherMime = observed;
    otherMime.resources.at(std::string(store::kFrozenHostPlaneMesh)).front().mime = "model/other";
    Check(!works(otherMime), "v2: resource metadata disagreeing with the stored bytes refuses");

    // Live rehash: corrupted bytes of the host plane, of the inactive snapshot's plane and of the
    // mesh refuse, and restoring them restores the lookup.
    const auto planeSha = [&](const std::string& key) {
        std::int64_t planeId = 0;
        for (const store::SnapshotEntry& snapshot : store::ProjectSnapshots(scene)) {
            if (snapshot.key == key) planeId = static_cast<std::int64_t>(snapshot.plane_id);
        }
        const auto& chunks = std::get<json::Array>(fx::ContextPlane(*context, planeId).at("chunks").data);
        return std::get<std::string>(std::get<json::Array>(chunks.front().data)[2].data);
    };
    std::string inactiveKey;
    for (const store::SnapshotEntry& snapshot : store::ProjectSnapshots(scene)) {
        if (snapshot.key != hostKey) inactiveKey = snapshot.key;
    }
    for (const auto& [label, sha] : {std::pair<std::string, std::string>{"the host plane", planeSha(hostKey)},
                                     {"the inactive snapshot plane", planeSha(inactiveKey)},
                                     {"the mesh resource", std::string(store::kFrozenHostPlaneMesh)}}) {
        std::string original;
        {
            store::Statement q(backing->container(), "SELECT data FROM blob WHERE sha256 = ?");
            q.Bind(1, sha);
            if (q.Step()) original = q.Blob(0);
        }
        store::Statement corrupt(backing->container(), "UPDATE blob SET data = ? WHERE sha256 = ?");
        corrupt.BindBlob(1, store::Compress("corrupt")).Bind(2, sha).Run();
        const bool refusedCorrupt = !works(observed);
        store::Statement restore(backing->container(), "UPDATE blob SET data = ? WHERE sha256 = ?");
        restore.BindBlob(1, original).Bind(2, sha).Run();
        Check(!original.empty() && refusedCorrupt && works(observed),
              "v2: corrupted bytes of " + label + " refuse; restored bytes serve again");
    }

    // A foreign store never serves this project's observations.
    core::DocumentState foreignState;
    foreignState.project_uuid = "6f1c2a3e-0000-4000-8000-0000000a3631";
    fx::SceneIds foreignIds;
    foreignState.project = fx::Scene(store::ObservationPin(store::ObservationKey(descriptor)), plane.size(), foreignIds);
    auto foreign = store::ProjectStore::Create(work / "observation-source-v2-foreign.uzp", foreignState, options);
    Check(!ObservedFilter(*foreign, observed, ids.filter), "v2: another store's uuid refuses");
    foreign->Close();

    // Partial observations keep absence distinct from empty.
    Object partial = entry;
    partial["observations"] = Object{{"parameters", descriptor.at("parameters")}};
    const auto partialCommit = submit([&](core::Edit& edit) {
        edit.project().extra[std::string(store::kFilterObservationsKey)] = fx::Namespace(descriptor, {partial}, ids.filter);
    });
    const auto partialFound = ObservedFilter(*backing, *document.snapshot().project, ids.filter);
    Check(committed(partialCommit) && partialFound && partialFound->parameters && !partialFound->resource_id &&
              !partialFound->image_outputs,
          "v2: an unobserved getter stays absent, never empty");
    const auto restored = submit([&](core::Edit& edit) { edit.project().extra[std::string(store::kFilterObservationsKey)] = space; });
    Check(committed(restored) && works(*document.snapshot().project), "v2: the complete entry serves again");

    // Inside Submit's callback (no store mutex held) the prospective lookup takes the locked
    // census once, without a deadlock; a rolled-back transaction changes nothing.
    const std::int64_t before = document.revision();
    bool prospective = false;
    const auto rolled = submit([&](core::Edit& edit) {
        prospective = ObservedFilter(*backing, edit.project(), ids.filter).has_value() &&
                      CurrentFilterObservationContextV2(*backing, edit.project()).has_value();
        throw std::runtime_error("refused after the prospective lookup");
    });
    Check(prospective && !committed(rolled) && document.revision() == before && works(*document.snapshot().project),
          "v2: the prospective lookup runs without a deadlock and a rollback changes nothing");

    // Save, close and reopen: a fresh lookup serves the persisted entry.
    backing->Save(document);
    backing->Close();
    auto reopened = store::ProjectStore::Open(file, store::OpenOptions{store::VerifyLevel::full, store::VersionPolicy::Current()});
    Check(reopened.report.ok() && ObservedFilter(*reopened.store, reopened.state.project, ids.filter).has_value(),
          "v2: after save and reopen a fresh lookup serves the persisted entry");
    reopened.store->Close();
    return Finish();
}

int main(int argc, char** argv) {
    if (argc < 3) {
        std::fprintf(stderr, "usage: uzp-procedural-tests seam | domain | primitives | kernels | gpu | library | library-load <work-dir> [...]\n");
        return 2;
    }
    const std::string_view mode = argv[1];
    const fs::path dir = argv[2];
    if (mode == "seam") return RunSeam();
    if (mode == "observations") return RunObservations();
    if (mode == "observation-source") return RunObservationSource(dir);
    if (mode == "observation-source-v2") return RunObservationSourceV2(dir);
    if (mode == "domain") return RunDomain();
    if (mode == "typed-params") return RunTypedParams();
    if (mode == "resolution") return RunResolution(dir);
    if (mode == "snapshot-recording") return RunSnapshotRecording(dir);
    if (mode == "snapshot-metadata") return RunSnapshotSourceMetadata(dir);
    if (mode == "primitives") return RunPrimitives();
    if (mode == "kernels") return RunKernels(dir);
    if (mode == "gpu") return RunGpu(dir);
    if (mode == "library" && argc == 5) return RunLibrary(argv[3], argv[4]);
    if (mode == "library-load" && argc == 4) return RunLibraryLoad(argv[3]);
    if (mode == "assets-cli" && argc == 5) return RunAssetsCli(dir, argv[3], argv[4]);
    if (mode == "admission" && argc == 4) return RunAdmission(dir, argv[3]);
    if (mode == "snapshot" && argc == 3) return RunSnapshot(dir);
    std::fprintf(stderr, "unknown case %.*s\n", static_cast<int>(mode.size()), mode.data());
    return 2;
}
