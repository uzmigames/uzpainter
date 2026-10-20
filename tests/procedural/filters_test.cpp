// Native tests of the procedural filter families (src/procedural/filters.h, rulebook task
// phase3.2_proc-filter-families, decision 328). Built by `zig build proc-filter-tests` and driven
// by tests/procedural/test_proc_filter_families.py.
//
// Usage: uzp-proc-filter-tests <case> <work-dir> <shipped-library>
//   families    Sharpen and grayscale conversion against their published formulas, the joint
//               rule, tiles, and the seam's refusal of the uncertified families (CPU; item 2.2)
//   levels      the Levels filter mapped onto the native levels effect: its parameters, its
//               arithmetic and its refusals (CPU; item 2.3)
//   effect-order
//               a filter effect computes from the content the effects below it produced and
//               blends with its own mode and opacity (CPU; test 3.2)
//   resolution-override
//               a resolution override on the source of a filter effect raises ValueError and
//               commits nothing; a generator keeps its own (CPU; item 2.4, test 3.3)
//   domain      a parameter, a seed, a mesh-map input, a content input and a resolution just
//               outside each declared domain are refused before mutation, nothing clamped or
//               substituted (CPU; test 3.5)
//   kernels     both families' kernels compiled to DXIL and SPIR-V (CPU, needs dxcompiler.dll)
//   gpu         both families on DX12 equal to their CPU reference bit for bit, whole and by
//               tile (GPU; item 2.2)
//
// The shipped library is the repository's `assets/procedural/`. No case compares against a
// Painter output: the families are not certified.
//
// Output: `PASS <check>` / `FAIL <check>: <detail>` / `INFO` lines.
// Exit code 0 when every check passed, 1 when one failed, 2 on a usage error, 77 when the case
// needs a DX12 hardware adapter and there is none.

#include "procedural/asset_library.h"
#include "procedural/filters.h"
#include "procedural/hlsl_backend.h"
#include "procedural/seam.h"

#include "evaluator/arith.h"
#include "render/engine_thread.h"
#include "render/kernel_cache.h"

#include "uzp_core/document/document.h"
#include "uzp_core/document/nodes.h"
#include "uzp_core/transaction/transaction.h"
#include "uzp_core/types/errors.h"
#include "uzp_core/types/validation.h"

#include <array>
#include <bit>
#include <charconv>
#include <cmath>
#include <chrono>
#include <cstdio>
#include <filesystem>
#include <functional>
#include <future>
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
            const size_t texel = i / a.channels;
            first = "texel (" + std::to_string(texel % a.width) + ", " + std::to_string(texel / a.width) +
                    ") channel " + std::to_string(i % a.channels) + ": " + Hex(Bits(a.texels[i])) +
                    " against " + Hex(Bits(b.texels[i]));
        }
    }
    return count == 0 ? std::string() : std::to_string(count) + " values differ, first at " + first;
}

uzp::core::AssetUrl Url(std::string_view text) { return uzp::core::ParseAssetUrl(text); }

/// Authored content: `channels` values per texel, each code / max of a seeded uniform code.
Raster Content(uint32_t size, uint32_t channels, uint32_t max, uint32_t seed) {
    std::mt19937 random(seed);
    Raster raster{size, size, channels, {}};
    raster.texels.resize(size_t{size} * size * channels);
    for (float& v : raster.texels) {
        v = static_cast<float>(random() % (max + 1)) / static_cast<float>(max);
    }
    return raster;
}

/// A filter request inside its declared domain: the record's defaults, seed 0, the `sphere`
/// class, the output at `resolution` and the content input of `content` with the given spec.
ProceduralRequest FilterRequest(const AssetRecord& record, const Raster& content, ChannelFormat contentFormat,
                                std::string colourSpace) {
    ProceduralRequest request;
    request.asset = record.asset;
    request.params = record.defaults;
    request.meshClass = "sphere";
    request.output = RasterSpec{content.width, ChannelFormat::F32, colourSpace, content.channels};
    request.inputs[std::string(kContentInput)] =
        ContentInput(content, RasterSpec{content.width, contentFormat, colourSpace, content.channels});
    request.seed = 0;
    return request;
}

struct Fixture {
    AssetLibrary library;
    const AssetRecord* sharpen = nullptr;
    const AssetRecord* grayscale = nullptr;
};

std::optional<Fixture> LoadFixture(const fs::path& shipped) {
    auto loaded = AssetLibrary::Load(shipped);
    Check(loaded.has_value(), "the shipped library loads", loaded ? "" : loaded.error());
    if (!loaded) return std::nullopt;
    Fixture fixture{std::move(*loaded), nullptr, nullptr};
    fixture.sharpen = fixture.library.Find(Url(kSharpenAsset));
    fixture.grayscale = fixture.library.Find(Url(kGrayscaleAsset));
    Check(fixture.sharpen != nullptr && fixture.grayscale != nullptr,
          "the shipped library holds the Sharpen and grayscale records");
    if (fixture.sharpen == nullptr || fixture.grayscale == nullptr) return std::nullopt;
    return fixture;
}

int64_t Wrap(int64_t v, int64_t size) { return ((v % size) + size) % size; }

/// Sharpen's published formula at one texel, written out with plain float32 operations (the
/// test compiles without contraction; the authored content holds no subnormal).
float SharpenAt(const Raster& f, int64_t x, int64_t y, uint32_t c, float amount) {
    const auto at = [&](int64_t px, int64_t py) {
        const int64_t w = f.width;
        return f.texels[(size_t(Wrap(py, w)) * f.width + size_t(Wrap(px, w))) * f.channels + c];
    };
    const float centre = at(x, y);
    const float laplacian = (((at(x - 1, y) + at(x + 1, y)) + at(x, y - 1)) + at(x, y + 1)) - 4.0f * centre;
    return centre - amount * laplacian;
}

/// The texels of `whole` inside `tile`.
Raster Crop(const Raster& whole, const TileRect& tile) {
    Raster out{tile.width, tile.height, whole.channels, {}};
    for (uint32_t y = 0; y < tile.height; ++y) {
        for (uint32_t x = 0; x < tile.width; ++x) {
            for (uint32_t c = 0; c < whole.channels; ++c) {
                const size_t at = (size_t{tile.y + y} * whole.width + tile.x + x) * whole.channels + c;
                out.texels.push_back(whole.texels[at]);
            }
        }
    }
    return out;
}

// ── families (item 2.2, CPU) ─────────────────────────────────────────────────

int RunFamilies(const fs::path& shipped) {
    std::optional<Fixture> fixture = LoadFixture(shipped);
    if (!fixture) return Finish();
    HlslBackend hlsl(nullptr);
    const std::expected<void, std::string> registered = RegisterFilterFamilies(hlsl, fixture->library);
    Check(registered.has_value(), "Sharpen and grayscale conversion register from their library records",
          registered ? "" : registered.error());
    if (!registered) return Finish();
    Check(hlsl.Status(fixture->sharpen->asset).kind == ParityStatus::Kind::Unavailable &&
              hlsl.Status(fixture->grayscale->asset).kind == ParityStatus::Kind::Unavailable,
          "both families carry their records' status: not certified");

    // Sharpen: the published formula, texel by texel, at the default and at another amount.
    const Raster mask = Content(1024, 1, 65535, 11);
    for (const double amount : {1.0, 2.75}) {
        ProceduralRequest request = FilterRequest(*fixture->sharpen, mask, ChannelFormat::U16, "linear");
        request.params["amount"] = amount;
        render::Result<Raster> out = hlsl.EvaluateReference(request, {{std::string(kContentInput), mask}});
        bool equal = out && out->width == 1024 && out->channels == 1;
        std::string first;
        for (int64_t y = 0; equal && y < 1024; ++y) {
            for (int64_t x = 0; equal && x < 1024; ++x) {
                const float expected = SharpenAt(mask, x, y, 0, static_cast<float>(amount));
                const float got = out->texels[size_t(y) * 1024 + size_t(x)];
                if (Bits(expected) != Bits(got)) {
                    equal = false;
                    first = "(" + std::to_string(x) + ", " + std::to_string(y) + "): " + Hex(Bits(got)) +
                            " against " + Hex(Bits(expected));
                }
            }
        }
        Check(equal, "Sharpen equals f - amount x Laplacian(f) with wrap-around, amount " + std::to_string(amount),
              out ? first : out.error().Describe());
    }
    {
        ProceduralRequest request = FilterRequest(*fixture->sharpen, mask, ChannelFormat::U16, "linear");
        request.params["amount"] = int64_t{0};
        render::Result<Raster> out = hlsl.EvaluateReference(request, {{std::string(kContentInput), mask}});
        Check(out && FirstDifference(*out, mask).empty(), "Sharpen at amount 0 is the content, bit for bit",
              out ? FirstDifference(*out, mask) : out.error().Describe());
        Raster flat{1024, 1024, 1, std::vector<float>(1024 * 1024, 0.375f)};
        ProceduralRequest flatRequest = FilterRequest(*fixture->sharpen, flat, ChannelFormat::U16, "linear");
        flatRequest.params["amount"] = 4.0;
        render::Result<Raster> flatOut = hlsl.EvaluateReference(flatRequest, {{std::string(kContentInput), flat}});
        Check(flatOut && FirstDifference(*flatOut, flat).empty(), "Sharpen leaves a constant content unchanged",
              flatOut ? FirstDifference(*flatOut, flat) : flatOut.error().Describe());
    }

    // Grayscale conversion: Y = (red R + green G) + blue B on the three channels.
    const Raster colour = Content(1024, 3, 255, 23);
    {
        ProceduralRequest request = FilterRequest(*fixture->grayscale, colour, ChannelFormat::U8, "srgb");
        render::Result<Raster> out = hlsl.EvaluateReference(request, {{std::string(kContentInput), colour}});
        const float red = static_cast<float>(0.2126);
        const float green = static_cast<float>(0.7152);
        const float blue = static_cast<float>(0.0722);
        bool equal = out && out->channels == 3 && out->texels.size() == colour.texels.size();
        for (size_t t = 0; equal && t < size_t{1024} * 1024; ++t) {
            const float* c = &colour.texels[t * 3];
            const float y = (red * c[0] + green * c[1]) + blue * c[2];
            equal = Bits(out->texels[t * 3]) == Bits(y) && Bits(out->texels[t * 3 + 1]) == Bits(y) &&
                    Bits(out->texels[t * 3 + 2]) == Bits(y);
        }
        Check(equal, "grayscale conversion equals the BT.709 luma sum on every channel at the defaults",
              out ? "" : out.error().Describe());
        request.params = {{"red", int64_t{0}}, {"green", int64_t{1}}, {"blue", int64_t{0}}};
        render::Result<Raster> green1 = hlsl.EvaluateReference(request, {{std::string(kContentInput), colour}});
        bool copies = green1.has_value();
        for (size_t t = 0; copies && t < size_t{1024} * 1024; ++t) {
            copies = Bits(green1->texels[t * 3]) == Bits(colour.texels[t * 3 + 1]);
        }
        Check(copies, "grayscale conversion with weights (0, 1, 0) copies the green channel");
    }

    // A tile is the same texels as the whole texture.
    for (const AssetRecord* record : {fixture->sharpen, fixture->grayscale}) {
        const bool sharpen = record == fixture->sharpen;
        const Raster& content = sharpen ? mask : colour;
        ProceduralRequest request = FilterRequest(*record, content, sharpen ? ChannelFormat::U16 : ChannelFormat::U8,
                                                  sharpen ? "linear" : "srgb");
        render::Result<Raster> whole = hlsl.EvaluateReference(request, {{std::string(kContentInput), content}});
        request.tile = TileRect{1000, 3, 24, 40};
        render::Result<Raster> part = hlsl.EvaluateReference(request, {{std::string(kContentInput), content}});
        Check(whole && part && FirstDifference(*part, Crop(*whole, request.tile)).empty(),
              "a tile at the texture border equals the whole texture's texels: " + record->name);
    }

    // The joint rule: the content has the output's resolution, channels and colour space.
    {
        const Raster small = Content(1024, 1, 65535, 5);
        ProceduralRequest request = FilterRequest(*fixture->sharpen, small, ChannelFormat::U16, "linear");
        request.output.resolution = 2048;
        const std::optional<UnsupportedProcedural> refusal = hlsl.Refusal(request);
        Check(refusal && refusal->reason == kOutsideDomain && refusal->field == "inputs.content.resolution" &&
                  refusal->value == "1024" && refusal->certified == "the output's resolution (2048)",
              "a content at another resolution than the output is refused, not resampled",
              refusal ? refusal->Describe() : "admitted");
        const render::Result<Raster> evaluated = hlsl.EvaluateReference(request, {{std::string(kContentInput), small}});
        Check(!evaluated, "the candidate lane evaluates nothing for it");
    }

    // The seam never serves an uncertified family, and substitutes nothing.
    {
        ProceduralSeam seam(nullptr, &hlsl);
        ProceduralRequest request = FilterRequest(*fixture->grayscale, colour, ChannelFormat::U8, "srgb");
        const auto selected = seam.Select(request);
        Check(!selected && selected.error().reason == kNotCertified && selected.error().value == "unavailable",
              "the seam refuses the uncertified family inside its domain (family not certified)",
              selected ? "served" : selected.error().Describe());
        HlslBackend gpu(nullptr);
        Check(RegisterFilterFamilies(gpu, fixture->library).has_value() && !gpu.CanEvaluate(request),
              "CanEvaluate is false for an uncertified family");
    }
    return Finish();
}

// ── levels (item 2.3, CPU) ───────────────────────────────────────────────────

int RunLevels(const fs::path& shipped) {
    std::optional<Fixture> fixture = LoadFixture(shipped);
    if (!fixture) return Finish();
    const AssetRecord* record = fixture->library.Find(Url(kLevelsAsset));
    Check(record != nullptr && record->status.kind == ParityStatus::Kind::Unavailable,
          "the shipped library holds the Levels filter's record, not certified");
    if (record == nullptr) return Finish();
    const Raster mask = Content(1024, 1, 65535, 41);
    const InputImages inputs = {{std::string(kContentInput), mask}};

    // The defaults map onto the identity component of the native levels effect.
    ProceduralRequest request = FilterRequest(*record, mask, ChannelFormat::U16, "linear");
    const auto defaults = LevelsFilterEffect(request, fixture->library);
    const uzp::core::LevelsComponent identity{};
    Check(defaults && defaults->components.size() == 1 && defaults->components[0] == identity &&
              !defaults->affected_channel,
          "the defaults map onto one native levels component (0, 1, gamma 1, 0, 1, no clamp)",
          defaults ? "" : defaults.error().Describe());
    const render::Result<Raster> unchanged = LevelsFilterReference(request, fixture->library, inputs);
    Check(unchanged && FirstDifference(*unchanged, mask).empty(),
          "the Levels filter at its defaults is the identity, bit for bit",
          unchanged ? FirstDifference(*unchanged, mask) : unchanged.error().Describe());

    // Every parameter reaches the native component; the lane is the native effect's arithmetic.
    request.params = {{"input_min", 0.125}, {"input_max", 0.875}, {"gamma", 2.2},
                      {"output_min", 0.25}, {"output_max", 0.75},  {"clamp", int64_t{1}}};
    const auto mapped = LevelsFilterEffect(request, fixture->library);
    Check(mapped && mapped->components.size() == 1 && mapped->components[0].input_min == 0.125 &&
              mapped->components[0].input_max == 0.875 && mapped->components[0].gamma == 2.2 &&
              mapped->components[0].output_min == 0.25 && mapped->components[0].output_max == 0.75 &&
              mapped->components[0].clamp,
          "every parameter maps onto the native component unchanged", mapped ? "" : mapped.error().Describe());
    for (const int64_t clamp : {int64_t{0}, int64_t{1}}) {
        request.params["clamp"] = clamp;
        const render::Result<Raster> out = LevelsFilterReference(request, fixture->library, inputs);
        const uzp::evaluator::arith::LevelsComponent native{0.125f, 0.875f, static_cast<float>(2.2), 0.25f, 0.75f,
                                                            clamp != 0};
        bool equal = out && out->texels.size() == mask.texels.size();
        for (size_t i = 0; equal && i < mask.texels.size(); ++i) {
            equal = Bits(out->texels[i]) == Bits(uzp::evaluator::arith::Levels(mask.texels[i], native));
        }
        Check(equal, "the Levels filter equals the native levels effect's arithmetic on every texel, clamp " +
                         std::to_string(clamp),
              out ? "" : out.error().Describe());
        if (clamp == 1 && out) {
            bool floor = true;
            for (size_t i = 0; i < mask.texels.size(); ++i) {
                if (mask.texels[i] < 0.125f) floor = floor && out->texels[i] == 0.25f;
            }
            Check(floor, "with clamp, content below input_min maps to output_min");
        }
    }

    // Refusals, before anything is evaluated; nothing is clamped or substituted.
    ProceduralRequest other = FilterRequest(*fixture->sharpen, mask, ChannelFormat::U16, "linear");
    const auto notLevels = LevelsFilterEffect(other, fixture->library);
    Check(!notLevels && notLevels.error().asset == std::string(kSharpenAsset),
          "another asset is not mapped onto the levels effect", notLevels ? "mapped" : notLevels.error().Describe());
    ProceduralRequest unpinned = FilterRequest(*record, mask, ChannelFormat::U16, "linear");
    unpinned.asset = Url("uzasset://filter/levels@2");
    const auto missing = LevelsFilterEffect(unpinned, fixture->library);
    Check(!missing && missing.error().reason == kNotInLibrary,
          "a Levels version the library does not hold is refused", missing ? "mapped" : missing.error().Describe());
    ProceduralRequest wide = FilterRequest(*record, mask, ChannelFormat::U16, "linear");
    wide.output.resolution = 2048;
    const auto joint = LevelsFilterEffect(wide, fixture->library);
    Check(!joint && joint.error().field == "inputs.content.resolution",
          "a content at another resolution than the output is refused", joint ? "mapped" : joint.error().Describe());
    Check(!LevelsFilterReference(wide, fixture->library, inputs), "the refused request evaluates nothing");

    // The Levels filter is no HLSL family: the seam has no backend for it.
    HlslBackend hlsl(nullptr);
    (void)RegisterFilterFamilies(hlsl, fixture->library);
    ProceduralSeam seam(nullptr, &hlsl);
    const auto selected = seam.Select(FilterRequest(*record, mask, ChannelFormat::U16, "linear"));
    Check(!selected && selected.error().reason == kNoBackend,
          "the seam serves no Levels filter (no snapshot and no certified family)",
          selected ? "served" : selected.error().Describe());
    return Finish();
}

// ── effect-order (test 3.2, CPU) ─────────────────────────────────────────────

/// The fill effect below the filter: a uniform colour blended over `base` with Multiply at
/// opacity 0.5 through the evaluator's effect mix, then stored as 8-bit codes (the content is
/// stored in the channel format after every effect, masks-levels.json `content-effect-order`).
Raster FillBelow(const Raster& base) {
    namespace arith = uzp::evaluator::arith;
    const float colour[3] = {0.25f, 0.5f, 0.75f};
    Raster out = base;
    for (size_t t = 0; t < size_t{base.width} * base.height; ++t) {
        arith::CompositeInput in;
        for (size_t c = 0; c < 3; ++c) {
            in.acc[c] = base.texels[t * 3 + c];
            in.src[c] = colour[c];
        }
        in.mode = uzp::core::BlendingMode::Multiply;
        in.opacity = 0.5f;
        in.effectMix = true;
        const std::array<float, 4> v = arith::Composite(in);
        for (size_t c = 0; c < 3; ++c) {
            out.texels[t * 3 + c] = static_cast<float>(arith::WriteUnorm(v[c], 8)) / 255.0f;
        }
    }
    return out;
}

int RunEffectOrder(const fs::path& shipped) {
    std::optional<Fixture> fixture = LoadFixture(shipped);
    if (!fixture) return Finish();
    HlslBackend hlsl(nullptr);
    if (!RegisterFilterFamilies(hlsl, fixture->library)) return Finish();
    const Raster base = Content(1024, 3, 255, 53);
    const Raster afterFill = FillBelow(base);
    const ProceduralRequest grey = FilterRequest(*fixture->grayscale, afterFill, ChannelFormat::U8, "srgb");
    const float red = static_cast<float>(0.2126);
    const float green = static_cast<float>(0.7152);
    const float blue = static_cast<float>(0.0722);
    const auto luma = [&](const float* c) { return (red * c[0] + green * c[1]) + blue * c[2]; };

    // A fill effect, then a grayscale filter at Normal 0.75: the filter reads the content after
    // the fill, and v = a + (Y - a) x 0.75 (the effect mix) over that same content.
    const render::Result<Raster> normal =
        FilterEffectReference(hlsl, fixture->library, grey, afterFill, uzp::core::BlendingMode::Normal, 0.75f);
    bool equal = normal && normal->channels == 3;
    for (size_t t = 0; equal && t < size_t{1024} * 1024; ++t) {
        const float* a = &afterFill.texels[t * 3];
        const float y = luma(a);
        for (size_t c = 0; equal && c < 3; ++c) {
            equal = Bits(normal->texels[t * 3 + c]) == Bits(a[c] + (y - a[c]) * 0.75f);
        }
    }
    Check(equal, "a grayscale filter above a fill effect computes from the content after the fill and blends "
                 "with its own Normal mode at opacity 0.75",
          normal ? "" : normal.error().Describe());

    const render::Result<Raster> multiply =
        FilterEffectReference(hlsl, fixture->library, grey, afterFill, uzp::core::BlendingMode::Multiply, 1.0f);
    equal = multiply.has_value();
    for (size_t t = 0; equal && t < size_t{1024} * 1024; ++t) {
        const float* a = &afterFill.texels[t * 3];
        const float y = luma(a);
        for (size_t c = 0; equal && c < 3; ++c) {
            equal = Bits(multiply->texels[t * 3 + c]) == Bits(a[c] + (a[c] * y - a[c]) * 1.0f);
        }
    }
    Check(equal, "the same filter blends with its own Multiply mode at opacity 1",
          multiply ? "" : multiply.error().Describe());

    // The order matters: the filter below the fill reads the base content instead.
    const ProceduralRequest greyBase = FilterRequest(*fixture->grayscale, base, ChannelFormat::U8, "srgb");
    const render::Result<Raster> first =
        FilterEffectReference(hlsl, fixture->library, greyBase, base, uzp::core::BlendingMode::Normal, 0.75f);
    const Raster filterThenFill = first ? FillBelow(*first) : Raster{};
    Check(normal && first && !FirstDifference(filterThenFill, *normal).empty(),
          "the filter below the fill gives another result than the filter above it");

    // A filter computes only from the content it was admitted on.
    const render::Result<Raster> stale =
        FilterEffectReference(hlsl, fixture->library, grey, base, uzp::core::BlendingMode::Normal, 0.75f);
    Check(!stale && stale.error().Describe().find("is not the content the request names") != std::string::npos,
          "a content raster other than the one the request names is refused",
          stale ? "evaluated" : stale.error().Describe());
    const render::Result<Raster> noKernel =
        FilterEffectReference(hlsl, fixture->library, grey, afterFill, uzp::core::BlendingMode::PassThrough, 1.0f);
    Check(!noKernel, "a blend mode without a kernel is refused");

    // The Levels filter blends the same way, over a mono content.
    const AssetRecord* levels = fixture->library.Find(Url(kLevelsAsset));
    const Raster mask = Content(1024, 1, 65535, 59);
    ProceduralRequest remap = FilterRequest(*levels, mask, ChannelFormat::U16, "linear");
    remap.params["output_max"] = 0.5;
    const render::Result<Raster> remapped =
        LevelsFilterReference(remap, fixture->library, {{std::string(kContentInput), mask}});
    const render::Result<Raster> blended =
        FilterEffectReference(hlsl, fixture->library, remap, mask, uzp::core::BlendingMode::Normal, 0.5f);
    equal = remapped && blended;
    for (size_t i = 0; equal && i < mask.texels.size(); ++i) {
        equal = Bits(blended->texels[i]) == Bits(mask.texels[i] + (remapped->texels[i] - mask.texels[i]) * 0.5f);
    }
    Check(equal, "a Levels filter effect blends its remapped content with its own mode and opacity",
          blended ? "" : blended.error().Describe());
    return Finish();
}

// ── resolution-override (item 2.4, test 3.3, CPU) ────────────────────────────

/// A project with one fill layer whose content effects are a Sharpen filter effect and a
/// generator effect, each with a procedural reference and no resolution override.
uzp::core::Project OverrideProject(uzp::core::Id& filter, uzp::core::Id& generator) {
    namespace core = uzp::core;
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
    for (const core::EffectKind kind : {core::EffectKind::filter, core::EffectKind::generator}) {
        const bool isFilter = kind == core::EffectKind::filter;
        core::Effect effect;
        effect.uid = project.AllocateId();
        effect.kind = kind;
        effect.name = isFilter ? "sharpen" : "ridge";
        core::ProceduralRef ref;
        ref.asset = isFilter ? std::string(kSharpenAsset) : std::string("uzasset://generator/ridge@1");
        effect.procedural = ref;
        (isFilter ? filter : generator) = effect.uid;
        layer.content_effects.push_back(effect);
    }
    stack.root_layers.push_back(layer);
    set.stacks.push_back(stack);
    project.texture_sets.push_back(set);
    return project;
}

/// A snapshot backend that admits every request: a stand-in for a project snapshot with the
/// request's exact signature, so that the edit reaches its transaction.
class AdmitAll final : public IProceduralBackend {
public:
    std::string_view Name() const override { return "snapshot"; }
    ParityStatus Status(const uzp::core::AssetUrl&) const override { return ParityStatus::Unavailable("test"); }
    bool CanEvaluate(const ProceduralRequest&) const override { return true; }
    std::optional<UnsupportedProcedural> Refusal(const ProceduralRequest&) const override { return std::nullopt; }
    RasterFuture Evaluate(const ProceduralRequest&, const InputImages&) override {
        std::promise<render::Result<Raster>> promise;
        promise.set_value(render::Fail(render::ErrorCode::RequestFailed, std::nullopt, "not evaluated"));
        return promise.get_future();
    }
};

int RunResolutionOverride(const fs::path& shipped) {
    namespace core = uzp::core;
    namespace json = uzp::core::json;
    std::optional<Fixture> fixture = LoadFixture(shipped);
    if (!fixture) return Finish();
    core::Id filter = core::kNoId;
    core::Id generator = core::kNoId;
    core::DocumentState initial;
    initial.project_uuid = "6f1c2a3e-0000-4000-8000-00000000a328";
    initial.project = OverrideProject(filter, generator);
    core::Document document(initial);
    int keys = 0;
    const auto request = [&]() {
        const std::string key = "override-" + std::to_string(++keys);
        return core::MutationRequest{"procedural_set", json::Object{{"key", key}}, key, document.revision()};
    };
    const auto overrideOf = [](core::Id uid) {
        return [uid](core::Edit& edit) {
            core::FindEffect(edit.project(), uid)->procedural->resolution_override = core::Resolution{512, 512, {}};
        };
    };
    const auto overridden = [&](core::Id uid) {
        core::Project now = *document.snapshot().project;
        return core::FindEffect(now, uid)->procedural->resolution_override.has_value();
    };

    // Setting a resolution override on the source of a filter effect raises ValueError; the
    // transaction commits nothing.
    const core::Project before = *document.snapshot().project;
    const core::RequestOutcome refused = core::Execute(document, request(), overrideOf(filter));
    Check(refused.result && refused.result->status == core::ResultStatus::failed &&
              refused.result->error_type == "ValueError" &&
              refused.result->error.find("the source of a filter effect has no resolution override") !=
                  std::string::npos,
          "a resolution override on a filter effect's source raises ValueError",
          refused.result ? refused.result->error_type + ": " + refused.result->error : "not executed");
    Check(document.revision() == 0 && *document.snapshot().project == before,
          "the refused edit commits nothing: the revision and the project are unchanged");

    // A generator's source keeps its override: the restriction is the filter effect's.
    const core::RequestOutcome kept = core::Execute(document, request(), overrideOf(generator));
    Check(kept.result && kept.result->status == core::ResultStatus::committed && document.revision() == 1 &&
              overridden(generator),
          "a generator effect's source accepts a resolution override",
          kept.result ? kept.result->error : "not executed");

    // A stored project with one does not validate (load and save validate).
    core::Project stored = *document.snapshot().project;
    core::FindEffect(stored, filter)->procedural->resolution_override = core::Resolution{1024, 1024, {}};
    bool raised = false;
    try {
        core::Validate(stored);
    } catch (const core::ValueError&) {
        raised = true;
    }
    Check(raised, "a project whose filter effect's source has a resolution override fails validation (ValueError)");

    // Through the procedural edit (decision 324 §10): even an admitted filter reference with an
    // override is refused by its transaction, with the revision unchanged.
    AdmitAll snapshots;
    HlslBackend hlsl(nullptr);
    (void)RegisterFilterFamilies(hlsl, fixture->library);
    ProceduralSeam seam(&snapshots, &hlsl);
    core::ProceduralRef ref;
    ref.asset = std::string(kSharpenAsset);
    ref.resolution_override = core::Resolution{512, 512, {}};
    UseContext context;
    context.meshClass = "sphere";
    context.output = RasterSpec{1024, ChannelFormat::F32, "linear", 1};
    int submits = 0;
    const SubmitEdit submit = [&](const std::function<void(core::Edit&)>& call) {
        ++submits;
        return core::Execute(document, request(), call);
    };
    const auto edited = SetEffectProcedural(filter, ref, context, fixture->library, seam, submit);
    Check(edited && submits == 1 && edited->result && edited->result->status == core::ResultStatus::failed &&
              edited->result->error_type == "ValueError" && document.revision() == 1 && !overridden(filter),
          "SetEffectProcedural with an override on a filter effect raises ValueError and commits nothing",
          edited ? (edited->result ? edited->result->error : "not executed") : edited.error().Describe());
    ref.resolution_override.reset();
    const auto plain = SetEffectProcedural(filter, ref, context, fixture->library, seam, submit);
    Check(plain && plain->result && plain->result->status != core::ResultStatus::failed && document.revision() == 1,
          "the same reference without an override is accepted (no change: a no-op)",
          plain ? (plain->result ? plain->result->error : "not executed") : plain.error().Describe());
    return Finish();
}

// ── domain (test 3.5, CPU) ───────────────────────────────────────────────────

/// Whether `text` reads back as exactly `value` (the refusal names the requested value, not a
/// clamped one).
bool SameNumber(const std::string& text, double value) {
    double parsed = 0.0;
    const auto [end, ec] = std::from_chars(text.data(), text.data() + text.size(), parsed);
    return ec == std::errc{} && end == text.data() + text.size() && parsed == value;
}

int RunDomain(const fs::path& shipped) {
    namespace core = uzp::core;
    namespace json = uzp::core::json;
    std::optional<Fixture> fixture = LoadFixture(shipped);
    if (!fixture) return Finish();
    HlslBackend hlsl(nullptr);
    if (!RegisterFilterFamilies(hlsl, fixture->library)) return Finish();
    ProceduralSeam seam(nullptr, &hlsl);

    core::Id filter = core::kNoId;
    core::Id generator = core::kNoId;
    core::DocumentState initial;
    initial.project_uuid = "6f1c2a3e-0000-4000-8000-00000000b328";
    initial.project = OverrideProject(filter, generator);
    core::Document document(initial);
    const core::Project before = *document.snapshot().project;
    int submits = 0;
    const SubmitEdit submit = [&](const std::function<void(core::Edit&)>& call) {
        ++submits;
        const std::string key = "domain-" + std::to_string(submits);
        return core::Execute(document,
                             core::MutationRequest{"procedural_set", json::Object{{"key", key}}, key,
                                                   document.revision()},
                             call);
    };

    const Raster mask = Content(1024, 1, 65535, 61);
    const Raster colour = Content(1024, 3, 255, 67);
    UseContext sharpen;
    sharpen.meshClass = "sphere";
    sharpen.output = RasterSpec{1024, ChannelFormat::F32, "linear", 1};
    sharpen.content = ContentInput(mask, RasterSpec{1024, ChannelFormat::U16, "linear", 1});
    UseContext grey = sharpen;
    grey.output = RasterSpec{1024, ChannelFormat::F32, "srgb", 3};
    grey.content = ContentInput(colour, RasterSpec{1024, ChannelFormat::U8, "srgb", 3});
    const auto refOf = [](std::string_view asset, json::Object params) {
        core::ProceduralRef ref;
        ref.asset = std::string(asset);
        ref.params = std::move(params);
        return ref;
    };
    const double aboveAmount = std::nextafter(4.0, 5.0);
    const double belowAmount = std::nextafter(0.0, -1.0);
    const double aboveRed = std::nextafter(1.0, 2.0);

    struct Case {
        std::string what;
        core::ProceduralRef ref;
        UseContext context;
        std::string field;
        std::optional<double> value;  ///< The requested number the refusal must name exactly.
    };
    std::vector<Case> cases;
    cases.push_back({"a parameter one ulp above its range", refOf(kSharpenAsset, {{"amount", aboveAmount}}), sharpen,
                     "params.amount", aboveAmount});
    cases.push_back({"a parameter one ulp below its range", refOf(kSharpenAsset, {{"amount", belowAmount}}), sharpen,
                     "params.amount", belowAmount});
    cases.push_back({"a grayscale weight one ulp above its range", refOf(kGrayscaleAsset, {{"red", aboveRed}}), grey,
                     "params.red", aboveRed});
    {
        UseContext c = sharpen;
        c.seed = 1;
        cases.push_back({"a seed outside the listed seed", refOf(kSharpenAsset, {}), c, "seed", 1.0});
    }
    {
        UseContext c = sharpen;
        c.inputs["Curvature"] = RasterSpec{1024, ChannelFormat::U16, "linear", 1};
        core::ProceduralRef ref = refOf(kSharpenAsset, {});
        ref.image_inputs["Curvature"] = core::ResourceBinding{std::string(64, 'a'), std::nullopt, {}};
        cases.push_back({"a mesh-map input the domain does not declare", ref, c, "inputs.Curvature", std::nullopt});
    }
    {
        UseContext c = sharpen;
        c.content = ContentInput(mask, RasterSpec{1024, ChannelFormat::U8, "linear", 1});
        cases.push_back({"a content input in another format", refOf(kSharpenAsset, {}), c, "inputs.content.format",
                         std::nullopt});
    }
    {
        UseContext c = sharpen;
        c.content = ContentInput(mask, RasterSpec{2048, ChannelFormat::U16, "linear", 1});
        cases.push_back({"a content input at another resolution than the output", refOf(kSharpenAsset, {}), c,
                         "inputs.content.resolution", 2048.0});
    }
    for (const uint32_t resolution : {512u, 8192u}) {
        UseContext c = sharpen;
        c.output.resolution = resolution;
        c.content->spec.resolution = resolution;
        cases.push_back({"an output resolution of " + std::to_string(resolution), refOf(kSharpenAsset, {}), c,
                         "output.resolution", double(resolution)});
    }
    {
        UseContext c = sharpen;
        c.meshClass = "plane";
        cases.push_back({"a mesh class outside the domain", refOf(kSharpenAsset, {}), c, "mesh.class", std::nullopt});
    }
    {
        UseContext c = sharpen;
        c.content.reset();
        cases.push_back({"a filter use without its content input", refOf(kSharpenAsset, {}), c, "inputs.content",
                         std::nullopt});
    }

    for (const Case& c : cases) {
        const auto edited = SetEffectProcedural(filter, c.ref, c.context, fixture->library, seam, submit);
        const bool refused = !edited && edited.error().reason == kOutsideDomain && edited.error().field == c.field &&
                             (!c.value || SameNumber(edited.error().value, *c.value));
        Check(refused && submits == 0 && document.revision() == 0 && *document.snapshot().project == before,
              "outside the domain, refused before mutation with nothing clamped: " + c.what,
              edited ? "admitted" : edited.error().Describe());
        // The candidate lanes refuse the same request: nothing is evaluated.
        const auto request = RequestFor(c.ref, c.context, fixture->library);
        if (request) {
            const render::Result<Raster> evaluated =
                hlsl.EvaluateReference(*request, {{std::string(kContentInput),
                                                   c.ref.asset == kSharpenAsset ? mask : colour}});
            Check(!evaluated && evaluated.error().Describe().find(std::string(kOutsideDomain)) != std::string::npos,
                  "the candidate lane evaluates nothing: " + c.what);
        }
    }

    // Inside the domain the uncertified family is still refused, and nothing is substituted.
    const auto inside = SetEffectProcedural(filter, refOf(kSharpenAsset, {{"amount", 4.0}}), sharpen,
                                            fixture->library, seam, submit);
    Check(!inside && inside.error().reason == kNotCertified && submits == 0 && document.revision() == 0,
          "inside the domain the uncertified Sharpen is refused before mutation (family not certified)",
          inside ? "admitted" : inside.error().Describe());
    core::ProceduralRef bound = refOf(kSharpenAsset, {});
    bound.image_inputs[std::string(kContentInput)] = core::ResourceBinding{std::string(64, 'b'), std::nullopt, {}};
    const auto rebound = RequestFor(bound, sharpen, fixture->library);
    Check(!rebound && rebound.error().field == "inputs.content",
          "a reference that binds its own content input is refused: the content is the layer's",
          rebound ? "admitted" : rebound.error().Describe());

    // The Levels filter: its domain refuses through the mapping; the edit has no backend at all.
    const AssetRecord* levels = fixture->library.Find(Url(kLevelsAsset));
    const ProceduralRequest base = FilterRequest(*levels, mask, ChannelFormat::U16, "linear");
    struct LevelsCase {
        std::string what;
        ProceduralRequest request;
        std::string field;
    };
    std::vector<LevelsCase> levelsCases;
    {
        ProceduralRequest r = base;
        r.params["gamma"] = std::nextafter(8.0, 9.0);
        levelsCases.push_back({"a gamma one ulp above its range", r, "params.gamma"});
    }
    {
        ProceduralRequest r = base;
        r.params["input_min"] = 0.5;
        r.params["input_max"] = 0.5;
        levelsCases.push_back({"input_min not below input_max (the joint constraint)", r, "params"});
    }
    {
        ProceduralRequest r = base;
        r.params["clamp"] = int64_t{2};
        levelsCases.push_back({"a clamp outside its set", r, "params.clamp"});
    }
    {
        ProceduralRequest r = base;
        r.seed = 1;
        levelsCases.push_back({"a seed outside the listed seed", r, "seed"});
    }
    {
        ProceduralRequest r = base;
        r.output.resolution = 512;
        levelsCases.push_back({"an output resolution of 512", r, "output.resolution"});
    }
    for (const LevelsCase& c : levelsCases) {
        const auto mapped = LevelsFilterEffect(c.request, fixture->library);
        Check(!mapped && mapped.error().reason == kOutsideDomain && mapped.error().field == c.field,
              "the Levels filter refuses outside its domain: " + c.what,
              mapped ? "mapped" : mapped.error().Describe());
    }
    UseContext levelsContext = sharpen;
    const auto levelsEdit =
        SetEffectProcedural(filter, refOf(kLevelsAsset, {}), levelsContext, fixture->library, seam, submit);
    Check(!levelsEdit && levelsEdit.error().reason == kNoBackend && submits == 0 && document.revision() == 0,
          "a Levels filter reference is refused before mutation: no backend serves it yet",
          levelsEdit ? "admitted" : levelsEdit.error().Describe());
    return Finish();
}

// ── kernels (item 2.2, CPU with dxcompiler) ──────────────────────────────────

int RunKernels(const fs::path& dir, const fs::path& shipped) {
    std::optional<Fixture> fixture = LoadFixture(shipped);
    if (!fixture) return Finish();
    render::Result<std::unique_ptr<render::DxcKernelCompiler>> compiler =
        render::DxcKernelCompiler::Load(render::DefaultDxcompilerPath());
    Check(compiler.has_value(), "DXC loads", compiler ? "" : compiler.error().Describe());
    if (!compiler) return Finish();
    render::KernelCache cache(**compiler, dir / "kernel-cache");
    HlslBackend hlsl(nullptr);
    if (!RegisterFilterFamilies(hlsl, fixture->library)) return Finish();
    const Raster mask = Content(1024, 1, 65535, 1);
    const Raster colour = Content(1024, 3, 255, 2);
    for (const ProceduralRequest& request :
         {FilterRequest(*fixture->sharpen, mask, ChannelFormat::U16, "linear"),
          FilterRequest(*fixture->grayscale, colour, ChannelFormat::U8, "srgb")}) {
        auto kernels = hlsl.Kernels(request);
        Check(kernels && kernels->size() == 1, "one kernel pass planned for " + AssetName(request),
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

// ── gpu (item 2.2, DX12) ─────────────────────────────────────────────────────

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
    if (!RegisterFilterFamilies(hlsl, fixture->library)) return Finish();
    const Raster mask = Content(1024, 1, 65535, 31);
    const Raster colour = Content(1024, 3, 255, 37);
    struct Case {
        std::string what;
        ProceduralRequest request;
        const Raster* content;
    };
    std::vector<Case> cases;
    for (const double amount : {1.0, 0.5, 4.0}) {
        ProceduralRequest r = FilterRequest(*fixture->sharpen, mask, ChannelFormat::U16, "linear");
        r.params["amount"] = amount;
        cases.push_back({"Sharpen amount " + std::to_string(amount), r, &mask});
    }
    {
        ProceduralRequest r = FilterRequest(*fixture->grayscale, colour, ChannelFormat::U8, "srgb");
        cases.push_back({"grayscale conversion at the defaults", r, &colour});
        r.params = {{"red", 0.5}, {"green", 0.25}, {"blue", 1.0}};
        cases.push_back({"grayscale conversion at weights (0.5, 0.25, 1)", r, &colour});
    }
    for (Case& c : cases) {
        const InputImages inputs = {{std::string(kContentInput), *c.content}};
        render::Result<Raster> reference = hlsl.EvaluateReference(c.request, inputs);
        RasterFuture future = hlsl.EvaluateCandidate(c.request, inputs);
        render::Result<Raster> gpu = Get(future);
        Check(reference && gpu && FirstDifference(*gpu, *reference).empty(),
              "DX12 equals the CPU reference bit for bit: " + c.what,
              !reference ? reference.error().Describe()
                         : (!gpu ? gpu.error().Describe() : FirstDifference(*gpu, *reference)));
        c.request.tile = TileRect{1017, 0, 7, 33};
        render::Result<Raster> tileReference = hlsl.EvaluateReference(c.request, inputs);
        RasterFuture tileFuture = hlsl.EvaluateCandidate(c.request, inputs);
        render::Result<Raster> tile = Get(tileFuture);
        Check(tileReference && tile && FirstDifference(*tile, *tileReference).empty(),
              "a DX12 tile at the border equals the CPU tile: " + c.what);
    }
    return Finish();
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 4) {
        std::fprintf(stderr,
                     "usage: uzp-proc-filter-tests families | levels | effect-order | resolution-override | "
                     "domain | kernels | gpu <work-dir> <shipped-library>\n");
        return 2;
    }
    const std::string_view mode = argv[1];
    const fs::path dir = argv[2];
    const fs::path shipped = argv[3];
    if (mode == "families") return RunFamilies(shipped);
    if (mode == "levels") return RunLevels(shipped);
    if (mode == "effect-order") return RunEffectOrder(shipped);
    if (mode == "resolution-override") return RunResolutionOverride(shipped);
    if (mode == "domain") return RunDomain(shipped);
    if (mode == "kernels") return RunKernels(dir, shipped);
    if (mode == "gpu") return RunGpu(dir, shipped);
    std::fprintf(stderr, "unknown case %.*s\n", static_cast<int>(mode.size()), mode.data());
    return 2;
}
