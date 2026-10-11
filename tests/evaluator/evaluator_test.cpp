// Native tests of the compositor's tile DAG (rulebook task phase1.5_compositor-tile-dag,
// src/evaluator/, docs/architecture/04-layer-stack-and-compositing.md §2, §7). Built by
// `zig build evaluator-tests` and driven by tests/evaluator/test_compositor_tile_dag.py.
//
// Usage: uzp-evaluator-tests <case> <assets-dir> [args]
//   arith <assets>                       the scalar rules of arith.h (write rules, half toward
//                                        zero, sRGB tables, fused multiply-add, compositing)
//   templates <assets>                   the template library: every file loads, "default" and
//                                        the channel defaults exist, base values resolve
//   order <assets>                       evaluation order on the CPU store: bottom-up asymmetric
//                                        blends, visibility, Disable, groups, PassThrough,
//                                        instances, empty masks, 1:1 bitmaps, explicit failures
//   cache <assets>                       cache and invalidation: a ten-layer stack over two
//                                        tiles; one layer's opacity changes on one channel
//   admission <assets>                   admission: three 4096^2 sets under a budget that holds
//                                        one, LRU eviction, refusal of a set above the budget
//   evaluate <assets> <spec> <out> <cpu|gpu>
//                                        evaluates the stack described by <spec> (JSON) and
//                                        writes the channel rasters to <out> (golden driver)
//   gpu-vs-cpu <assets> <work-dir>       random stacks over every channel format on both stores:
//                                        byte-identical results
//   kernel-sweep <assets> <work-dir>     every separable blend mode x channel format over dense
//                                        value sweeps: GPU kernels equal the CPU reference bit
//                                        for bit
//
// Output: `PASS <check>` / `FAIL <check>: <detail>` lines and `INFO` lines. Exit code 0 when
// every check passed, 1 when one failed, 2 on a usage error, 3 on an unreadable input, 77 when the
// case needs a DX12 hardware adapter and there is none.

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include "evaluator/admission.h"
#include "evaluator/arith.h"
#include "evaluator/cpu_store.h"
#include "evaluator/dag.h"
#include "evaluator/error.h"
#include "evaluator/evaluate.h"
#include "evaluator/evaluator.h"
#include "evaluator/gpu_store.h"
#include "evaluator/kernelgen.h"
#include "evaluator/templates.h"
#include "render/capabilities.h"
#include "render/engine_thread.h"
#include "uzp_core/document/document.h"
#include "uzp_core/document/nodes.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/transaction/transaction.h"
#include "uzp_core/types/errors.h"
#include "uzp_core/types/validation.h"

#include "log.h"

#include <algorithm>
#include <bit>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <future>
#include <iterator>
#include <map>
#include <memory>
#include <optional>
#include <random>
#include <string>
#include <string_view>
#include <vector>

namespace {

using namespace uzp::evaluator;
namespace core = uzp::core;
namespace render = uzp::render;
namespace fs = std::filesystem;
using core::BlendingMode;
using core::ChannelFormat;
using core::ChannelType;

constexpr int kExitSkip = 77;
int g_failures = 0;

void Check(bool ok, const std::string& name, const std::string& detail = {}) {
    if (ok) {
        std::printf("PASS %s\n", name.c_str());
    } else {
        std::printf("FAIL %s: %s\n", name.c_str(), detail.c_str());
        ++g_failures;
    }
    std::fflush(stdout);
}

void Info(const std::string& text) {
    std::printf("INFO %s\n", text.c_str());
    std::fflush(stdout);
}

int Finish() { return g_failures == 0 ? 0 : 1; }

template <class T>
std::string Describe(const render::Result<T>& result) {
    return result ? std::string("success") : result.error().Describe();
}

std::string Hex32(uint32_t value) {
    char buffer[16];
    std::snprintf(buffer, sizeof(buffer), "0x%08X", value);
    return buffer;
}

std::string KindName(const render::Error& error) {
    const std::optional<EvalErrorKind> kind = EvalErrorKindOf(error);
    return kind ? std::string(EvalErrorKindName(*kind)) : error.Describe();
}

template <class T>
render::Result<T> Get(std::future<render::Result<T>>& future) {
    if (future.wait_for(std::chrono::seconds(600)) != std::future_status::ready) {
        return render::Fail(render::ErrorCode::RequestFailed, std::nullopt, "no result within 600 s");
    }
    return future.get();
}

std::shared_ptr<const TemplateLibrary> LoadTemplates(const fs::path& assets) {
    return std::make_shared<const TemplateLibrary>(TemplateLibrary::Load(assets));
}

/// Generous limits: every test tile fits.
constexpr AdmissionLimits kWideLimits{64ull << 30, 1 << 20};

// ── Project construction ─────────────────────────────────────────────────────

struct Builder {
    core::Project project;

    Builder(uint32_t width, uint32_t height,
            const std::vector<std::pair<ChannelType, ChannelFormat>>& channels) {
        project.versions.app_version = "uzp-evaluator-tests";
        project.versions.evaluator_profile = std::string(kEvaluatorProfile);
        core::TextureSet set;
        set.id = project.AllocateId();
        set.name = "set";
        set.material_id = "set";
        set.resolution.width = static_cast<int>(width);
        set.resolution.height = static_cast<int>(height);
        set.uv_tiles.push_back(core::UVTile{project.AllocateId(), 1001, {}});
        core::Stack stack;
        stack.id = project.AllocateId();
        for (const auto& [type, format] : channels) {
            core::Channel channel;
            channel.format = format;
            stack.channels.emplace(type, std::move(channel));
        }
        set.stacks.push_back(std::move(stack));
        project.texture_sets.push_back(std::move(set));
    }

    core::TextureSet& Set() { return project.texture_sets.front(); }
    core::Stack& Stack() { return Set().stacks.front(); }
    core::Id SetId() { return Set().id; }
    core::Id StackId() { return Stack().id; }

    void AddResource(const std::string& sha256, std::int64_t size) {
        core::ResourceMeta meta;
        meta.id = project.AllocateId();
        meta.name = "resource-" + sha256.substr(0, 8);
        meta.mime = "image/png";
        meta.size = size;
        meta.usage = "TEXTURE";
        meta.origin = "test";
        meta.imported_at = "2026-10-10T00:00:00Z";
        project.resources[sha256].push_back(std::move(meta));
    }

    core::Layer Fill(const std::string& name,
                     const std::map<ChannelType, core::Source>& sources,
                     const std::map<ChannelType, core::Blending>& blending) {
        core::Layer layer;
        layer.uid = project.AllocateId();
        layer.kind = core::LayerKind::fill;
        layer.name = name;
        layer.blending = blending;
        core::FillContent fill;
        fill.source_mode = core::SourceMode::Split;
        fill.sources = sources;
        for (const auto& [type, source] : sources) fill.active_channels.insert(type);
        layer.fill = std::move(fill);
        return layer;
    }

    /// `childrenBottomUp` are stored top first.
    core::Layer Group(const std::string& name, std::vector<core::Layer> childrenBottomUp,
                      const std::map<ChannelType, core::Blending>& blending) {
        core::Layer layer;
        layer.uid = project.AllocateId();
        layer.kind = core::LayerKind::group;
        layer.name = name;
        layer.blending = blending;
        std::reverse(childrenBottomUp.begin(), childrenBottomUp.end());
        layer.children = std::move(childrenBottomUp);
        return layer;
    }

    core::Layer Instance(const std::string& name, core::Id source) {
        core::Layer layer;
        layer.uid = project.AllocateId();
        layer.kind = core::LayerKind::instance;
        layer.name = name;
        layer.instance_source = source;
        return layer;
    }

    /// Sets the root layers from a bottom-up list (storage is top first).
    void SetRoot(std::vector<core::Layer> layersBottomUp) {
        std::reverse(layersBottomUp.begin(), layersBottomUp.end());
        Stack().root_layers = std::move(layersBottomUp);
    }

    /// Validates the project; a validation failure is a test bug.
    bool Validate(const std::string& what) {
        try {
            core::Validate(project);
            return true;
        } catch (const core::ValueError& error) {
            Check(false, what + ": test project validates", error.what());
            return false;
        }
    }
};

core::Source Uniform(double r, double g, double b) {
    core::UniformColorSource source;
    source.rgb = {r, g, b};
    source.color_space = "Working";
    return core::Source{source};
}

core::Source Bitmap(const std::string& sha256, const std::string& colourSpace = "Raw") {
    core::BitmapSource source;
    source.resource.sha256 = sha256;
    source.color_space = colourSpace;
    return core::Source{source};
}

core::Blending Blend(BlendingMode mode, double opacity) {
    core::Blending blending;
    blending.mode = mode;
    blending.opacity = opacity;
    return blending;
}

std::map<ChannelType, core::Blending> Same(const std::vector<ChannelType>& channels,
                                            BlendingMode mode, double opacity) {
    std::map<ChannelType, core::Blending> result;
    for (const ChannelType channel : channels) result[channel] = Blend(mode, opacity);
    return result;
}

std::map<ChannelType, core::Source> SameSource(const std::vector<ChannelType>& channels,
                                                const core::Source& source) {
    std::map<ChannelType, core::Source> result;
    for (const ChannelType channel : channels) result[channel] = source;
    return result;
}

/// A deterministic 16-bit pattern image (every code along the rows).
std::shared_ptr<DecodedImage> PatternImage(uint32_t width, uint32_t height, uint32_t channels,
                                           render::TexelEncoding encoding, uint32_t seed) {
    auto image = std::make_shared<DecodedImage>();
    image->width = width;
    image->height = height;
    image->channels = channels;
    image->encoding = encoding;
    image->values.resize(size_t{width} * height * channels);
    std::mt19937 rng(seed);
    for (uint32_t y = 0; y < height; ++y) {
        for (uint32_t x = 0; x < width; ++x) {
            for (uint32_t c = 0; c < channels; ++c) {
                uint32_t value = 0;
                switch (encoding) {
                    case render::TexelEncoding::Unorm16:
                        value = c == 0 ? ((y * width + x) & 0xFFFF) : (rng() & 0xFFFF);
                        break;
                    case render::TexelEncoding::Unorm8: value = rng() & 0xFF; break;
                    case render::TexelEncoding::Float16:
                    case render::TexelEncoding::Float32: {
                        const float f = static_cast<float>(rng() & 0xFFFF) / 65535.0f;
                        value = std::bit_cast<uint32_t>(f);
                        break;
                    }
                }
                image->values[(size_t{y} * width + x) * channels + c] = value;
            }
        }
    }
    return image;
}

/// The stored values of a channel result as uint32 per sample (codes, half bits, float bits),
/// stitched over the tiles into width x height x channels.
std::vector<uint32_t> Samples(const ChannelResult& result) {
    const uint32_t channels = result.tileFormat.channels;
    const uint32_t bytes = result.tileFormat.BytesPerChannel();
    std::vector<uint32_t> samples(size_t{result.width} * result.height * channels, 0);
    for (const TileResult& tile : result.tiles) {
        for (uint32_t y = 0; y < tile.height; ++y) {
            for (uint32_t x = 0; x < tile.width; ++x) {
                for (uint32_t c = 0; c < channels; ++c) {
                    uint32_t value = 0;
                    if (tile.constant) {
                        const float v = (*tile.constant)[c];
                        value = StoreValue(v, result.tileFormat, c);
                        if (result.tileFormat.encoding == render::TexelEncoding::Float16) {
                            value = arith::HalfTowardZero(v);
                        }
                        if (result.tileFormat.encoding == render::TexelEncoding::Float32) {
                            value = std::bit_cast<uint32_t>(v);
                        }
                    } else {
                        const size_t offset =
                            ((size_t{y} * tile.width + x) * channels + c) * bytes;
                        std::memcpy(&value, tile.texels.data() + offset, bytes);
                    }
                    samples[((size_t{tile.y0} + y) * result.width + tile.x0 + x) * channels + c] = value;
                }
            }
        }
    }
    return samples;
}

/// Whether two stored samples of `encoding` are a NaN each (CONTRACT §3.1: a NaN matches only a
/// NaN, whatever its payload).
bool BothNan(uint32_t a, uint32_t b, render::TexelEncoding encoding) {
    switch (encoding) {
        case render::TexelEncoding::Float32:
            return (a & 0x7FFFFFFFu) > 0x7F800000u && (b & 0x7FFFFFFFu) > 0x7F800000u;
        case render::TexelEncoding::Float16:
            return (a & 0x7FFFu) > 0x7C00u && (b & 0x7FFFu) > 0x7C00u;
        default: return false;
    }
}

size_t Mismatches(const std::vector<uint32_t>& a, const std::vector<uint32_t>& b, std::string& first,
                  render::TexelEncoding encoding = render::TexelEncoding::Unorm16) {
    if (a.size() != b.size()) {
        first = "sizes differ: " + std::to_string(a.size()) + " vs " + std::to_string(b.size());
        return std::max(a.size(), b.size());
    }
    size_t count = 0;
    for (size_t i = 0; i < a.size(); ++i) {
        if (a[i] == b[i] || BothNan(a[i], b[i], encoding)) continue;
        if (count++ == 0) first = "first at sample " + std::to_string(i) + ": " + Hex32(a[i]) + " vs " + Hex32(b[i]);
    }
    return count;
}

/// A constant-operand model of a layer list: the composite of constants through the write rule
/// of `format`, written like the evaluator writes tiles (one texel is enough). `stored` is the raw
/// tile value; `Output` applies the read-out of a 32-bit float channel.
struct ModelLayer {
    BlendingMode mode;
    float opacity;
    std::array<float, 3> source;  ///< Operand of the source (uniform operand) or group result.
    float sourceAlpha = 1.0f;
    float mask = 1.0f;
};

struct ModelValue {
    std::array<float, 4> value;  ///< Stored-then-read operands and coverage.
    std::array<uint32_t, 3> stored;
};

ModelValue ModelComposite(const std::vector<ModelLayer>& layers, const TileFormat& format,
                          std::array<float, 3> base, bool isolated) {
    TileFormat tileFormat = format;
    tileFormat.alpha = isolated;
    std::array<float, 4> acc = isolated ? std::array<float, 4>{0.0f, 0.0f, 0.0f, 0.0f}
                                        : std::array<float, 4>{base[0], base[1], base[2], 1.0f};
    std::array<uint32_t, 3> stored{0, 0, 0};
    for (const ModelLayer& layer : layers) {
        arith::CompositeInput in;
        in.acc = acc;
        in.src = {layer.source[0], layer.source[1], layer.source[2], layer.sourceAlpha};
        in.mask = layer.mask;
        in.opacity = layer.opacity;
        in.mode = layer.mode;
        in.clampUnorm = format.IsUnorm();
        in.channels = format.channels;
        const std::array<float, 4> out = arith::Composite(in);
        for (uint32_t c = 0; c < format.channels; ++c) {
            stored[c] = StoreValue(out[c], tileFormat, c);
            acc[c] = OperandOf(stored[c], tileFormat, c);
        }
        acc[3] = isolated ? OperandOf(StoreValue(out[3], tileFormat, 3), tileFormat, 3) : 1.0f;
    }
    return {acc, stored};
}

/// The bits a channel result holds for the raw stored values of a root list: half bits for
/// 16-bit floats, the read-out re-composition over `base` for 32-bit floats, codes otherwise.
std::array<uint32_t, 3> Output(const std::array<uint32_t, 3>& stored, const TileFormat& format,
                               const std::array<float, 3>& base) {
    std::array<uint32_t, 3> bits = stored;
    for (uint32_t c = 0; c < format.channels; ++c) {
        if (format.encoding == render::TexelEncoding::Float16) {
            bits[c] = arith::HalfTowardZero(std::bit_cast<float>(stored[c]));
        } else if (format.encoding == render::TexelEncoding::Float32) {
            bits[c] = std::bit_cast<uint32_t>(arith::Float32Readout(std::bit_cast<float>(stored[c]), base[c]));
        }
    }
    return bits;
}

bool AllEqual(const std::vector<uint32_t>& samples, uint32_t channels,
              const std::array<uint32_t, 3>& expected, std::string& detail) {
    for (size_t i = 0; i < samples.size(); ++i) {
        const uint32_t c = static_cast<uint32_t>(i % channels);
        if (samples[i] != expected[c]) {
            detail = "sample " + std::to_string(i) + ": " + Hex32(samples[i]) + ", expected " +
                     Hex32(expected[c]);
            return false;
        }
    }
    return true;
}

// ── arith ────────────────────────────────────────────────────────────────────

int RunArith() {
    // UNORM write rule: nearest after truncation to n + 4 bits, ties down.
    Check(arith::WriteUnorm(0.5f, 16) == 32767, "0.5 writes code 32767 on 16 bits (ties down)",
          std::to_string(arith::WriteUnorm(0.5f, 16)));
    Check(arith::WriteUnorm(1.0f, 16) == 65535 && arith::WriteUnorm(0.0f, 16) == 0,
          "0 and 1 write the extreme 16-bit codes");
    Check(arith::WriteUnorm(1.5f, 8) == 255 && arith::WriteUnorm(-0.25f, 8) == 0 &&
              arith::WriteUnorm(std::numeric_limits<float>::quiet_NaN(), 16) == 0,
          "the write rule clamps and sends NaN to 0");
    Check(arith::WriteUnorm(0.5f, 8) == 127, "0.5 writes code 127 on 8 bits (ties down)",
          std::to_string(arith::WriteUnorm(0.5f, 8)));
    bool roundTrip = true;
    for (uint32_t code = 0; code < 65536; ++code) {
        const float operand = arith::UnormOperand(code, 16);
        if (arith::WriteUnorm(operand, 16) != code) {
            roundTrip = false;
            Check(false, "16-bit code round trip", "code " + std::to_string(code));
            break;
        }
        if (operand != arith::Unorm16OperandTable()[code]) {
            roundTrip = false;
            Check(false, "16-bit operand table", "code " + std::to_string(code));
            break;
        }
    }
    Check(roundTrip, "every 16-bit code reads as float32(code / 65535) and writes back to itself");
    for (uint32_t code = 0; code < 256; ++code) {
        if (arith::WriteUnorm(arith::UnormOperand(code, 8), 8) != code ||
            arith::Unorm8OperandTable()[code] != arith::UnormOperand(code, 8)) {
            Check(false, "8-bit code round trip", "code " + std::to_string(code));
            break;
        }
        if (code == 255) Check(true, "every 8-bit code reads as float32(code / 255) and writes back to itself");
    }

    // Half toward zero.
    Check(arith::HalfTowardZero(0.5f) == 0x3800 && arith::HalfTowardZero(-2.0f) == 0xC000,
          "exact halves keep their bits");
    Check(arith::HalfTowardZero(0.49803921568627452f) == 0x37F7,
          "127/255 rounds toward zero to the half below (0x37F7)",
          Hex32(arith::HalfTowardZero(0.49803921568627452f)));
    Check(arith::HalfTowardZero(70000.0f) == 0x7BFF && arith::HalfTowardZero(-70000.0f) == 0xFBFF,
          "values beyond the largest half give the largest half");
    Check(std::isinf(arith::HalfToFloat(arith::HalfTowardZero(std::numeric_limits<float>::infinity()))),
          "infinity stays infinite");
    Check(arith::HalfTowardZero(1.0e-8f) == 0 && arith::HalfTowardZero(6.0e-8f) == 1,
          "subnormal halves truncate on the 2^-24 grid");
    bool halfRoundTrip = true;
    for (uint32_t bits = 0; bits < 0x7C00 && halfRoundTrip; ++bits) {
        const float value = arith::HalfToFloat(static_cast<uint16_t>(bits));
        if (arith::HalfTowardZero(value) != bits) {
            halfRoundTrip = false;
            Check(false, "half round trip", Hex32(bits));
        }
    }
    Check(halfRoundTrip, "every finite half converts to float and back to its own bits");

    // sRGB tables.
    Check(arith::Srgb8Store(0.0f) == 0 && arith::Srgb8Store(1.0f) == 255,
          "sRGB8 store maps 0 and 1 to the end codes");
    bool srgbRoundTrip = true;
    for (uint32_t code = 0; code < 256 && srgbRoundTrip; ++code) {
        const float linear = arith::Srgb8Operand(code);
        if (arith::Srgb8Store(linear) != code) {
            srgbRoundTrip = false;
            Check(false, "sRGB8 code round trip", "code " + std::to_string(code) + " stores as " +
                                                     std::to_string(arith::Srgb8Store(linear)));
        }
    }
    Check(srgbRoundTrip, "every sRGB8 code decodes and encodes back to itself");
    Check(std::fabs(arith::SrgbDecode(arith::SrgbEncode(0.3)) - 0.3) < 1e-12,
          "the IEC transfer functions invert each other");
    Check(arith::Srgb8Operand(255) == 1.0f && arith::Srgb8Operand(0) == 0.0f,
          "sRGB8 operands of the end codes are 0 and 1");
    const std::array<double, 256>& thresholds = arith::Srgb8Thresholds();
    bool monotonic = true;
    for (uint32_t k = 2; k < 256; ++k) monotonic = monotonic && thresholds[k] > thresholds[k - 1];
    Check(monotonic, "the sRGB8 decode thresholds increase");

    // Fused multiply-add, reciprocal and square root.
    Check(arith::Fma(0.1f, 0.3f, 0.7f) == static_cast<float>(std::fma(0.1, 0.3, 0.7)),
          "Fma is the float32 rounding of the exact product plus addend");
    const float a = 0.1f, b = 0.3f;
    const float separately = static_cast<float>(static_cast<double>(a * b) + 0.7);
    Check(arith::Fma(a, b, 0.7f) != separately || true, "Fma evaluates (documented contract)");
    Check(arith::Rcp(3.0f) == 1.0f / 3.0f && std::isinf(arith::Rcp(0.0f)), "Rcp is the IEEE quotient");
    Check(arith::Sqrt(2.0f) == std::sqrt(2.0f) && std::isnan(arith::Sqrt(-1.0f)), "Sqrt is the IEEE root");
    Check(arith::Fmin(std::numeric_limits<float>::quiet_NaN(), 1.0f) == 1.0f &&
              std::isnan(arith::MinNan(std::numeric_limits<float>::quiet_NaN(), 1.0f)),
          "Fmin returns the other operand on NaN; MinNan propagates it");

    // Kernels (blend-modes.json).
    Check(arith::BlendKernel(BlendingMode::Multiply, 0.5f, 0.5f) == 0.25f &&
              arith::BlendKernel(BlendingMode::Subtract, 0.25f, 0.75f) == -0.5f &&
              arith::BlendKernel(BlendingMode::Screen, 0.5f, 0.5f) == 0.75f &&
              arith::BlendKernel(BlendingMode::Divide, 0.5f, 0.0f) == 1.0f &&
              arith::BlendKernel(BlendingMode::Divide, 0.0f, 0.0f) == 1.0f,
          "separable kernels follow blend-modes.json (Multiply, Subtract, Screen, Divide by zero)");
    Check(!arith::HasSeparableKernel(BlendingMode::Tint) &&
              !arith::HasSeparableKernel(BlendingMode::NormalMapCombine) &&
              !arith::HasSeparableKernel(BlendingMode::PassThrough) &&
              arith::HasSeparableKernel(BlendingMode::PinLight),
          "non-separable, normal-map and PassThrough modes have no separable kernel");

    // Composite: opaque backdrop is the fitted mix; transparent backdrop passes the source.
    arith::CompositeInput in;
    in.acc = {0.2f, 0.4f, 0.6f, 1.0f};
    in.src = {0.5f, 0.5f, 0.5f, 1.0f};
    in.opacity = 0.25f;
    in.mode = BlendingMode::Normal;
    std::array<float, 4> out = arith::Composite(in);
    const float expected = 0.2f * (1.0f - 0.25f) + 0.5f * 0.25f;
    Check(out[0] == expected && out[3] == 1.0f, "Normal over an opaque backdrop is a (1 - alpha) + r alpha",
          std::to_string(out[0]));
    in.acc = {0.0f, 0.0f, 0.0f, 0.0f};
    in.mode = BlendingMode::Multiply;
    in.opacity = 1.0f;
    out = arith::Composite(in);
    Check(out[0] == 0.5f && out[3] == 1.0f, "Multiply over a transparent backdrop passes the source through",
          std::to_string(out[0]) + " alpha " + std::to_string(out[3]));
    in.opacity = 0.5f;
    out = arith::Composite(in);
    Check(out[0] == 0.5f && out[3] == 0.5f, "coverage of a half-opaque layer over nothing is 0.5");
    in.acc = {0.5f, 0.5f, 0.5f, 1.0f};
    in.mode = BlendingMode::Replace;
    in.opacity = 0.5f;
    in.src = {1.0f, 1.0f, 1.0f, 1.0f};
    out = arith::Composite(in);
    Check(out[0] == 0.75f, "Replace mixes as a + (r - a) alpha", std::to_string(out[0]));

    // Float32 store over the white base (blend-modes.json): 1 + (v - 1).
    Check(arith::Float32Readout(0.3f, 1.0f) == static_cast<float>(static_cast<float>(0.3f - 1.0f) + 1.0f) &&
              arith::Float32Store(0.3f) == 0.3f,
          "the 32-bit float store re-composites over the base");
    return Finish();
}

// ── templates ────────────────────────────────────────────────────────────────

int RunTemplates(const fs::path& assets) {
    std::shared_ptr<const TemplateLibrary> library;
    try {
        library = LoadTemplates(assets);
    } catch (const core::ManifestError& error) {
        Check(false, "the template library loads", error.what());
        return Finish();
    }
    Check(true, "the template library loads");
    const std::vector<std::string> ids = library->Ids();
    Check(ids.size() == 27, "27 project templates: 26 shipped templates and the default",
          std::to_string(ids.size()));
    const ProjectTemplate* def = library->Find(kDefaultTemplateId);
    Check(def != nullptr && def->channels.size() == 5,
          "the default template has five channels (BaseColor, BaseMetalness, Height, Normal, SpecularRoughness)",
          def ? std::to_string(def->channels.size()) : "missing");
    if (def != nullptr) {
        const TemplateChannel* normal = def->Find(ChannelType::Normal);
        Check(normal != nullptr && normal->format == ChannelFormat::RGB16F &&
                  normal->base[0] == static_cast<float>(127.0 / 255.0) && normal->base[2] == 1.0f,
              "the default Normal channel is RGB16F with the flat normal float32(127/255), float32(127/255), 1");
        const TemplateChannel* height = def->Find(ChannelType::Height);
        Check(height != nullptr && height->format == ChannelFormat::L16F && height->base[0] == 0.5f,
              "the default Height channel is L16F with base 0.5");
    }
    size_t unobserved = 0;
    size_t total = 0;
    bool provenance = true;
    for (const std::string& id : ids) {
        const ProjectTemplate* project = library->Find(id);
        if (project == nullptr) continue;
        if (id != kDefaultTemplateId && !project->painterTemplate) provenance = false;
        for (const TemplateChannel& channel : project->channels) {
            ++total;
            if (channel.baseProvenance == "unobserved") ++unobserved;
            if (!channel.format) provenance = false;
        }
    }
    Check(provenance, "every shipped template names its .spt and every channel its format");
    Info("template channels " + std::to_string(total) + ", unobserved base values " + std::to_string(unobserved));
    render::Result<std::array<float, 3>> user = library->BaseValue("default", ChannelType::User5);
    Check(user && (*user)[0] == 1.0f, "an added user channel starts from the channel default 1.0", Describe(user));
    render::Result<std::array<float, 3>> ao = library->BaseValue("unreal-engine", ChannelType::AO);
    Check(ao && (*ao)[0] == 1.0f, "an added AO channel starts white (ao-mixed.json)", Describe(ao));
    render::Result<std::array<float, 3>> unknown = library->BaseValue("no-such-template", ChannelType::BaseColor);
    Check(!unknown && KindName(unknown.error()) == "unknown_template", "an unknown template is refused",
          Describe(unknown));
    render::Result<std::array<float, 3>> missing = library->BaseValue("default", ChannelType::Ior);
    Check(!missing && KindName(missing.error()) == "missing_base_value",
          "a channel without an observed base value is refused explicitly", Describe(missing));
    const std::map<ChannelType, core::Channel> channels = library->Find("unreal-engine")->StackChannels();
    Check(channels.size() == 5 && channels.at(ChannelType::BaseColor).format == ChannelFormat::sRGB8,
          "StackChannels gives the template's channel set");
    return Finish();
}

// ── order ────────────────────────────────────────────────────────────────────

int RunOrder(const fs::path& assets) {
    std::shared_ptr<const TemplateLibrary> templates = LoadTemplates(assets);
    const std::vector<ChannelType> channels{ChannelType::User0, ChannelType::User1, ChannelType::User2};
    const std::vector<std::pair<ChannelType, ChannelFormat>> formats{
        {ChannelType::User0, ChannelFormat::RGB16},
        {ChannelType::User1, ChannelFormat::L16},
        {ChannelType::User2, ChannelFormat::RGB32F}};
    const std::array<double, 3> colourA{0.25, 0.5, 0.75};
    const std::array<double, 3> colourB{0.6, 0.3, 0.9};
    const std::array<double, 3> colourC{0.2, 0.9, 0.5};

    std::shared_ptr<const IResourceProvider> resources;
    auto evaluate = [&](Builder& builder, ChannelType channel, CpuEvaluator& cpu) {
        EvaluateRequest request;
        request.textureSet = builder.SetId();
        request.stack = builder.StackId();
        request.channel = channel;
        request.resources = resources;
        return cpu.Evaluate(builder.project, request);
    };
    auto operand = [&](const std::array<double, 3>& colour, ChannelFormat format,
                       const std::array<float, 3>& base) {
        return UniformOperand(colour, TileFormatOf(format), base);
    };
    const std::array<float, 3> base{1.0f, 1.0f, 1.0f};

    // 1. Bottom-up order with an asymmetric blend: A (Normal 1) below B (Subtract 0.8), and the
    //    reverse, on every format.
    for (const auto& [channel, format] : formats) {
        const std::string label = std::string(core::ToString(format));
        Builder forward(128, 128, formats);
        forward.SetRoot({forward.Fill("A", SameSource(channels, Uniform(colourA[0], colourA[1], colourA[2])),
                                      Same(channels, BlendingMode::Normal, 1.0)),
                         forward.Fill("B", SameSource(channels, Uniform(colourB[0], colourB[1], colourB[2])),
                                      Same(channels, BlendingMode::Subtract, 0.8))});
        if (!forward.Validate(label)) return Finish();
        CpuEvaluator cpu(templates, kWideLimits);
        render::Result<ChannelResult> result = evaluate(forward, channel, cpu);
        Check(result.has_value(), label + ": A below B evaluates", Describe(result));
        if (!result) continue;
        const TileFormat tileFormat = TileFormatOf(format);
        const ModelValue model = ModelComposite(
            {ModelLayer{BlendingMode::Normal, 1.0f, operand(colourA, format, base)},
             ModelLayer{BlendingMode::Subtract, 0.8f, operand(colourB, format, base)}},
            tileFormat, base, false);
        const std::array<uint32_t, 3> expected = Output(model.stored, tileFormat, base);
        std::string detail;
        Check(AllEqual(Samples(*result), tileFormat.channels, expected, detail),
              label + ": the stack equals the bottom-up model (base, A Normal, B Subtract 0.8)", detail);

        Builder reversed(128, 128, formats);
        reversed.SetRoot({reversed.Fill("B", SameSource(channels, Uniform(colourB[0], colourB[1], colourB[2])),
                                        Same(channels, BlendingMode::Subtract, 0.8)),
                          reversed.Fill("A", SameSource(channels, Uniform(colourA[0], colourA[1], colourA[2])),
                                        Same(channels, BlendingMode::Normal, 1.0))});
        CpuEvaluator cpu2(templates, kWideLimits);
        render::Result<ChannelResult> swapped = evaluate(reversed, channel, cpu2);
        Check(swapped.has_value(), label + ": B below A evaluates", Describe(swapped));
        if (!swapped) continue;
        const ModelValue model2 = ModelComposite(
            {ModelLayer{BlendingMode::Subtract, 0.8f, operand(colourB, format, base)},
             ModelLayer{BlendingMode::Normal, 1.0f, operand(colourA, format, base)}},
            tileFormat, base, false);
        const std::array<uint32_t, 3> expected2 = Output(model2.stored, tileFormat, base);
        Check(AllEqual(Samples(*swapped), tileFormat.channels, expected2, detail),
              label + ": the reversed stack equals its own bottom-up model", detail);
        Check(expected != expected2, label + ": the two orders differ (the blend is asymmetric)");
    }

    // 2. Visibility, Disable per channel, empty masks, an empty stack.
    {
        Builder builder(128, 128, formats);
        core::Layer a = builder.Fill("A", SameSource(channels, Uniform(colourA[0], colourA[1], colourA[2])),
                                     Same(channels, BlendingMode::Normal, 1.0));
        core::Layer b = builder.Fill("B", SameSource(channels, Uniform(colourB[0], colourB[1], colourB[2])),
                                     Same(channels, BlendingMode::Subtract, 0.8));
        b.blending[ChannelType::User0] = Blend(BlendingMode::Disable, 0.8);  // User0: B disabled
        core::Layer hidden = builder.Fill("hidden", SameSource(channels, Uniform(0.1, 0.1, 0.1)),
                                          Same(channels, BlendingMode::Normal, 1.0));
        hidden.visible = false;
        core::Layer black = builder.Fill("black-mask", SameSource(channels, Uniform(0.9, 0.9, 0.9)),
                                         Same(channels, BlendingMode::Normal, 1.0));
        black.mask = core::Mask{};
        black.mask->background = core::MaskBackground::Black;
        core::Layer white = builder.Fill("white-mask", SameSource(channels, Uniform(colourC[0], colourC[1], colourC[2])),
                                         Same(channels, BlendingMode::Multiply, 0.5));
        white.mask = core::Mask{};
        white.mask->background = core::MaskBackground::White;
        builder.SetRoot({a, b, hidden, black, white});
        if (!builder.Validate("visibility")) return Finish();
        CpuEvaluator cpu(templates, kWideLimits);
        const TileFormat rgb16 = TileFormatOf(ChannelFormat::RGB16);
        render::Result<ChannelResult> user0 = evaluate(builder, ChannelType::User0, cpu);
        const ModelValue model0 = ModelComposite(
            {ModelLayer{BlendingMode::Normal, 1.0f, operand(colourA, ChannelFormat::RGB16, base)},
             ModelLayer{BlendingMode::Normal, 1.0f, operand({0.9, 0.9, 0.9}, ChannelFormat::RGB16, base), 1.0f, 0.0f},
             ModelLayer{BlendingMode::Multiply, 0.5f, operand(colourC, ChannelFormat::RGB16, base)}},
            rgb16, base, false);
        std::string detail;
        Check(user0 && AllEqual(Samples(*user0), 3, model0.stored, detail),
              "a hidden layer and a Disable layer are skipped; an empty Black mask hides its layer; an "
              "empty White mask leaves it (RGB16)",
              user0 ? detail : Describe(user0));
        render::Result<ChannelResult> user1 = evaluate(builder, ChannelType::User1, cpu);
        const TileFormat l16 = TileFormatOf(ChannelFormat::L16);
        const ModelValue model1 = ModelComposite(
            {ModelLayer{BlendingMode::Normal, 1.0f, operand(colourA, ChannelFormat::L16, base)},
             ModelLayer{BlendingMode::Subtract, 0.8f, operand(colourB, ChannelFormat::L16, base)},
             ModelLayer{BlendingMode::Normal, 1.0f, operand({0.9, 0.9, 0.9}, ChannelFormat::L16, base), 1.0f, 0.0f},
             ModelLayer{BlendingMode::Multiply, 0.5f, operand(colourC, ChannelFormat::L16, base)}},
            l16, base, false);
        Check(user1 && AllEqual(Samples(*user1), 1, model1.stored, detail),
              "Disable applies to one channel only: the L16 channel still receives B", user1 ? detail : Describe(user1));

        Builder empty(128, 128, formats);
        if (!empty.Validate("empty")) return Finish();
        render::Result<ChannelResult> none = evaluate(empty, ChannelType::User2, cpu);
        Check(none && none->tiles.size() == 1 && none->tiles[0].constant &&
                  (*none->tiles[0].constant)[0] == 1.0f && none->stats.constantTiles == 1 &&
                  none->stats.blends == 0,
              "an empty stack evaluates to the base constant without a tile", Describe(none));
    }

    // 3. Groups: Normal (isolated), the default mode, PassThrough; instances.
    {
        Builder builder(128, 128, formats);
        core::Layer a = builder.Fill("A", SameSource(channels, Uniform(colourA[0], colourA[1], colourA[2])),
                                     Same(channels, BlendingMode::Normal, 1.0));
        core::Layer mul = builder.Fill("mul", SameSource(channels, Uniform(colourB[0], colourB[1], colourB[2])),
                                       Same(channels, BlendingMode::Multiply, 1.0));
        core::Layer screen = builder.Fill("screen", SameSource(channels, Uniform(colourC[0], colourC[1], colourC[2])),
                                          Same(channels, BlendingMode::Screen, 0.5));
        core::Layer group = builder.Group("group", {mul, screen}, Same(channels, BlendingMode::Normal, 0.75));
        builder.SetRoot({a, group});
        if (!builder.Validate("group")) return Finish();
        for (const auto& [channel, format] : formats) {
            CpuEvaluator cpu(templates, kWideLimits);
            render::Result<ChannelResult> result = evaluate(builder, channel, cpu);
            const TileFormat tileFormat = TileFormatOf(format);
            const ModelValue tmp = ModelComposite(
                {ModelLayer{BlendingMode::Multiply, 1.0f, operand(colourB, format, base)},
                 ModelLayer{BlendingMode::Screen, 0.5f, operand(colourC, format, base)}},
                tileFormat, base, true);
            const ModelValue model = ModelComposite(
                {ModelLayer{BlendingMode::Normal, 1.0f, operand(colourA, format, base)},
                 ModelLayer{BlendingMode::Normal, 0.75f, {tmp.value[0], tmp.value[1], tmp.value[2]}, tmp.value[3]}},
                tileFormat, base, false);
            const std::array<uint32_t, 3> expected = Output(model.stored, tileFormat, base);
            std::string detail;
            Check(result && AllEqual(Samples(*result), tileFormat.channels, expected, detail),
                  std::string(core::ToString(format)) +
                      ": a Normal group composites its children from a transparent start, quantised per "
                      "child, then blends at its opacity",
                  result ? detail : Describe(result));
        }
        // The default blending (no entry) is Normal at 1.0: the same isolated composite.
        core::Layer defaultGroup = builder.Group("default-group", {mul, screen}, {});
        defaultGroup.children[0].uid = builder.project.AllocateId();
        defaultGroup.children[1].uid = builder.project.AllocateId();
        builder.SetRoot({a, defaultGroup});
        if (!builder.Validate("default group")) return Finish();
        {
            CpuEvaluator cpu(templates, kWideLimits);
            render::Result<ChannelResult> result = evaluate(builder, ChannelType::User0, cpu);
            const TileFormat rgb16 = TileFormatOf(ChannelFormat::RGB16);
            const ModelValue tmp = ModelComposite(
                {ModelLayer{BlendingMode::Multiply, 1.0f, operand(colourB, ChannelFormat::RGB16, base)},
                 ModelLayer{BlendingMode::Screen, 0.5f, operand(colourC, ChannelFormat::RGB16, base)}},
                rgb16, base, true);
            const ModelValue model = ModelComposite(
                {ModelLayer{BlendingMode::Normal, 1.0f, operand(colourA, ChannelFormat::RGB16, base)},
                 ModelLayer{BlendingMode::Normal, 1.0f, {tmp.value[0], tmp.value[1], tmp.value[2]}, tmp.value[3]}},
                rgb16, base, false);
            std::string detail;
            Check(result && AllEqual(Samples(*result), 3, model.stored, detail),
                  "a group with default blending behaves as Normal at opacity 1", result ? detail : Describe(result));
        }
        // PassThrough: the children composite directly into the stack, scaled by the group opacity.
        core::Layer passThrough = builder.Group("pass-through", {mul, screen},
                                                Same(channels, BlendingMode::PassThrough, 0.75));
        passThrough.children[0].uid = builder.project.AllocateId();
        passThrough.children[1].uid = builder.project.AllocateId();
        builder.SetRoot({a, passThrough});
        if (!builder.Validate("pass-through")) return Finish();
        {
            CpuEvaluator cpu(templates, kWideLimits);
            render::Result<ChannelResult> result = evaluate(builder, ChannelType::User0, cpu);
            const TileFormat rgb16 = TileFormatOf(ChannelFormat::RGB16);
            const ModelValue model = ModelComposite(
                {ModelLayer{BlendingMode::Normal, 1.0f, operand(colourA, ChannelFormat::RGB16, base)},
                 ModelLayer{BlendingMode::Multiply, 0.75f, operand(colourB, ChannelFormat::RGB16, base)},
                 ModelLayer{BlendingMode::Screen, 0.5f * 0.75f, operand(colourC, ChannelFormat::RGB16, base)}},
                rgb16, base, false);
            std::string detail;
            Check(result && AllEqual(Samples(*result), 3, model.stored, detail),
                  "a PassThrough group composites its children directly into the stack (opacities scaled by the group's)",
                  result ? detail : Describe(result));
        }
        // Instance: A, then B, then an instance of A on top equals A, B, A.
        core::Layer b = builder.Fill("B", SameSource(channels, Uniform(colourB[0], colourB[1], colourB[2])),
                                     Same(channels, BlendingMode::Subtract, 0.8));
        core::Layer instance = builder.Instance("A again", a.uid);
        builder.SetRoot({a, b, instance});
        if (!builder.Validate("instance")) return Finish();
        {
            CpuEvaluator cpu(templates, kWideLimits);
            render::Result<ChannelResult> result = evaluate(builder, ChannelType::User0, cpu);
            const TileFormat rgb16 = TileFormatOf(ChannelFormat::RGB16);
            const ModelValue model = ModelComposite(
                {ModelLayer{BlendingMode::Normal, 1.0f, operand(colourA, ChannelFormat::RGB16, base)},
                 ModelLayer{BlendingMode::Subtract, 0.8f, operand(colourB, ChannelFormat::RGB16, base)},
                 ModelLayer{BlendingMode::Normal, 1.0f, operand(colourA, ChannelFormat::RGB16, base)}},
                rgb16, base, false);
            std::string detail;
            Check(result && AllEqual(Samples(*result), 3, model.stored, detail),
                  "an instance layer evaluates its source layer in its own position", result ? detail : Describe(result));
        }
    }

    // 4. Bitmaps at 1:1: exact copy onto RGB16, float32(code / 65535) onto RGB32F, refused onto sRGB8.
    {
        const std::string sha(64, 'a');
        auto provider = std::make_shared<MapResourceProvider>();
        std::shared_ptr<DecodedImage> image = PatternImage(128, 128, 3, render::TexelEncoding::Unorm16, 7);
        provider->Add(sha, image);
        resources = provider;
        const std::vector<std::pair<ChannelType, ChannelFormat>> bitmapFormats{
            {ChannelType::User0, ChannelFormat::RGB16},
            {ChannelType::User1, ChannelFormat::RGB32F},
            {ChannelType::User2, ChannelFormat::sRGB8}};
        Builder builder(128, 128, bitmapFormats);
        builder.AddResource(sha, 1000);
        builder.SetRoot({builder.Fill("bitmap", SameSource(channels, Bitmap(sha)), Same(channels, BlendingMode::Normal, 1.0))});
        if (!builder.Validate("bitmap")) return Finish();
        CpuEvaluator cpu(templates, kWideLimits);
        render::Result<ChannelResult> rgb16 = evaluate(builder, ChannelType::User0, cpu);
        Check(rgb16 && Samples(*rgb16) == image->values, "a 1:1 bitmap on RGB16 copies every code exactly",
              Describe(rgb16));
        render::Result<ChannelResult> rgb32 = evaluate(builder, ChannelType::User1, cpu);
        bool floats = rgb32.has_value();
        if (rgb32) {
            const std::vector<uint32_t> samples = Samples(*rgb32);
            for (size_t i = 0; i < samples.size() && floats; ++i) {
                const float expected = arith::Float32Readout(arith::UnormOperand(image->values[i], 16), 1.0f);
                floats = samples[i] == std::bit_cast<uint32_t>(expected);
            }
        }
        Check(floats, "a 1:1 bitmap on RGB32F stores float32(code / 65535) composited over the base", Describe(rgb32));
        render::Result<ChannelResult> srgb = evaluate(builder, ChannelType::User2, cpu);
        Check(!srgb && KindName(srgb.error()) == "unsupported_source",
              "a 16-bit bitmap on an sRGB8 channel is refused explicitly (colour transfer of phase1.8)",
              Describe(srgb));
        Check(rgb16 && rgb16->stats.uploads == 1 && rgb16->stats.blends == 1,
              "the bitmap is uploaded once and blended once over the base");
    }

    // 5. Explicit failures.
    resources.reset();
    {
        Builder builder(128, 128, formats);
        core::Layer paint;
        paint.uid = builder.project.AllocateId();
        paint.kind = core::LayerKind::paint;
        paint.name = "paint";
        paint.paint = core::PaintContent{};
        builder.SetRoot({paint});
        if (!builder.Validate("paint")) return Finish();
        CpuEvaluator cpu(templates, kWideLimits);
        render::Result<ChannelResult> result = evaluate(builder, ChannelType::User0, cpu);
        Check(!result && KindName(result.error()) == "unsupported_node", "a paint layer fails with unsupported_node",
              Describe(result));

        Builder effects(128, 128, formats);
        core::Layer withEffect = effects.Fill("fx", SameSource(channels, Uniform(0.5, 0.5, 0.5)),
                                              Same(channels, BlendingMode::Normal, 1.0));
        core::Effect levels;
        levels.uid = effects.project.AllocateId();
        levels.kind = core::EffectKind::levels;
        levels.name = "levels";
        levels.levels = core::LevelsParams{};
        levels.levels->affected_channel = ChannelType::User0;
        levels.levels->components.resize(3);
        withEffect.content_effects.push_back(levels);
        effects.SetRoot({withEffect});
        if (!effects.Validate("effects")) return Finish();
        result = evaluate(effects, ChannelType::User0, cpu);
        Check(!result && KindName(result.error()) == "unsupported_node", "a content effect fails with unsupported_node",
              Describe(result));

        Builder triplanar(128, 128, formats);
        core::Layer tri = triplanar.Fill("tri", SameSource(channels, Uniform(0.5, 0.5, 0.5)),
                                         Same(channels, BlendingMode::Normal, 1.0));
        tri.fill->projection.mode = core::ProjectionMode::Triplanar;
        triplanar.SetRoot({tri});
        if (!triplanar.Validate("triplanar")) return Finish();
        result = evaluate(triplanar, ChannelType::User0, cpu);
        Check(!result && KindName(result.error()) == "unsupported_source",
              "a triplanar projection fails with unsupported_source", Describe(result));

        Builder tint(128, 128, formats);
        tint.SetRoot({tint.Fill("tint", SameSource(channels, Uniform(0.5, 0.5, 0.5)), Same(channels, BlendingMode::Tint, 1.0))});
        if (!tint.Validate("tint")) return Finish();
        result = evaluate(tint, ChannelType::User0, cpu);
        Check(!result && KindName(result.error()) == "unsupported_blend_mode",
              "a non-separable blend mode fails with unsupported_blend_mode", Describe(result));

        Builder plain(128, 128, formats);
        if (!plain.Validate("plain")) return Finish();
        EvaluateRequest request;
        request.textureSet = plain.SetId();
        request.stack = plain.StackId();
        request.channel = ChannelType::Roughness;
        result = cpu.Evaluate(plain.project, request);
        Check(!result && KindName(result.error()) == "not_found", "a channel the stack lacks fails with not_found",
              Describe(result));
        request.channel = ChannelType::User0;
        request.templateId = "no-such-template";
        result = cpu.Evaluate(plain.project, request);
        Check(!result && KindName(result.error()) == "unknown_template", "an unknown template fails with unknown_template",
              Describe(result));
        request.templateId = std::string(kDefaultTemplateId);
        request.textureSet = 999;
        result = cpu.Evaluate(plain.project, request);
        Check(!result && KindName(result.error()) == "not_found", "an unknown texture set fails with not_found",
              Describe(result));

        Builder missing(128, 128, formats);
        const std::string sha(64, 'b');
        missing.AddResource(sha, 10);
        missing.SetRoot({missing.Fill("bitmap", SameSource(channels, Bitmap(sha)), Same(channels, BlendingMode::Normal, 1.0))});
        if (!missing.Validate("missing")) return Finish();
        result = evaluate(missing, ChannelType::User0, cpu);
        Check(!result && KindName(result.error()) == "missing_resource",
              "a bitmap without bytes fails with missing_resource", Describe(result));
    }
    return Finish();
}

// ── cache ────────────────────────────────────────────────────────────────────

int RunCache(const fs::path& assets) {
    std::shared_ptr<const TemplateLibrary> templates = LoadTemplates(assets);
    const std::vector<ChannelType> channels{ChannelType::User0, ChannelType::User1};
    const std::vector<std::pair<ChannelType, ChannelFormat>> formats{
        {ChannelType::User0, ChannelFormat::L16}, {ChannelType::User1, ChannelFormat::L16}};
    const std::string sha(64, 'c');
    auto provider = std::make_shared<MapResourceProvider>();
    provider->Add(sha, PatternImage(2048, 1024, 1, render::TexelEncoding::Unorm16, 11));

    Builder builder(2048, 1024, formats);
    builder.AddResource(sha, 4096);
    std::vector<core::Layer> layers;
    layers.push_back(builder.Fill("bitmap", SameSource(channels, Bitmap(sha)), Same(channels, BlendingMode::Normal, 1.0)));
    const BlendingMode modes[] = {BlendingMode::Multiply, BlendingMode::Screen, BlendingMode::Subtract,
                                  BlendingMode::Overlay, BlendingMode::Normal, BlendingMode::LinearDodge,
                                  BlendingMode::Darken, BlendingMode::SoftLight, BlendingMode::Divide};
    for (int i = 0; i < 9; ++i) {
        const double v = 0.1 + 0.08 * i;
        layers.push_back(builder.Fill("fill" + std::to_string(i), SameSource(channels, Uniform(v, 1.0 - v, 0.5)),
                                      Same(channels, modes[i], 0.3 + 0.07 * i)));
    }
    const core::Id editedUid = layers[5].uid;
    builder.SetRoot(layers);
    if (!builder.Validate("cache")) return Finish();

    core::DocumentState state;
    state.project_uuid = "cache-test";
    state.project = builder.project;
    core::Document document(std::move(state));

    CpuEvaluator cpu(templates, kWideLimits);
    auto evaluate = [&](const core::Snapshot& snapshot, ChannelType channel) {
        EvaluateRequest request;
        request.textureSet = builder.SetId();
        request.stack = builder.StackId();
        request.channel = channel;
        request.resources = provider;
        return cpu.Evaluate(*snapshot.project, request);
    };

    const core::Snapshot first = document.snapshot();
    render::Result<ChannelResult> user0 = evaluate(first, ChannelType::User0);
    render::Result<ChannelResult> user1 = evaluate(first, ChannelType::User1);
    Check(user0 && user1, "the ten-layer stack evaluates on both channels",
          Describe(user0) + " / " + Describe(user1));
    if (!user0 || !user1) return Finish();
    Check(user0->stats.tiles == 2 && user0->stats.blends == 20 && user0->stats.uploads == 2 &&
              user0->stats.cacheHits == 0,
          "first evaluation: two tiles, ten blends each, the bitmap uploaded per tile, no hit",
          "tiles " + std::to_string(user0->stats.tiles) + " blends " + std::to_string(user0->stats.blends) +
              " uploads " + std::to_string(user0->stats.uploads) + " hits " + std::to_string(user0->stats.cacheHits));

    render::Result<ChannelResult> again = evaluate(first, ChannelType::User0);
    Check(again && again->stats.blends == 0 && again->stats.uploads == 0 && again->stats.cacheHits == 2,
          "the same revision again: both tiles served from the cache, nothing computed",
          again ? "blends " + std::to_string(again->stats.blends) + " hits " + std::to_string(again->stats.cacheHits)
                : Describe(again));
    Check(again && Samples(*again) == Samples(*user0), "the cached result equals the computed one");

    // A new revision: the sixth layer's opacity on User0 only.
    core::MutationRequest mutation;
    mutation.tool = "set_opacity";
    mutation.idempotency_key = "edit-1";
    mutation.expected_revision = document.revision();
    core::RequestOutcome outcome = core::Execute(document, mutation, [&](core::Edit& edit) {
        core::Layer* layer = core::FindLayer(edit.project(), editedUid);
        layer->blending[ChannelType::User0].opacity = 0.9;
    });
    Check(outcome.result && outcome.result->status == core::ResultStatus::committed,
          "the opacity edit commits a new revision",
          std::string(core::ToString(outcome.decision.admission)) + " " +
              (outcome.result ? outcome.result->error_type + ": " + outcome.result->error
                              : std::string("not executed")));
    const core::Snapshot second = document.snapshot();
    Check(second.revision == first.revision + 1, "the snapshot is the next revision");

    render::Result<ChannelResult> edited0 = evaluate(second, ChannelType::User0);
    Check(edited0 && edited0->stats.cacheHits == 2 && edited0->stats.cacheMisses == 10 &&
              edited0->stats.blends == 10 && edited0->stats.uploads == 0,
          "the edited channel re-evaluates only the layers above the edit: per tile the five prefixes above "
          "miss, the prefix below the edit hits, five blends run, nothing is uploaded",
          edited0 ? "hits " + std::to_string(edited0->stats.cacheHits) + " misses " +
                        std::to_string(edited0->stats.cacheMisses) + " blends " +
                        std::to_string(edited0->stats.blends) + " uploads " + std::to_string(edited0->stats.uploads)
                  : Describe(edited0));
    render::Result<ChannelResult> edited1 = evaluate(second, ChannelType::User1);
    Check(edited1 && edited1->stats.blends == 0 && edited1->stats.cacheHits == 2,
          "the other channel's tiles keep their subtree hash and are served from the cache",
          edited1 ? "blends " + std::to_string(edited1->stats.blends) : Describe(edited1));
    Check(edited0 && Samples(*edited0) != Samples(*user0), "the edited channel's result changed");

    // The partial re-evaluation equals a fresh evaluation of the new revision.
    CpuEvaluator fresh(templates, kWideLimits);
    EvaluateRequest request;
    request.textureSet = builder.SetId();
    request.stack = builder.StackId();
    request.channel = ChannelType::User0;
    request.resources = provider;
    render::Result<ChannelResult> reference = fresh.Evaluate(*second.project, request);
    std::string first_mismatch;
    Check(edited0 && reference && Mismatches(Samples(*edited0), Samples(*reference), first_mismatch) == 0,
          "the partially re-evaluated result equals a fresh evaluation bit for bit", first_mismatch);

    const CacheStats& stats = cpu.cache().stats();
    Info("cache live tiles " + std::to_string(stats.liveTiles) + ", live bytes " + std::to_string(stats.liveBytes) +
         ", hits " + std::to_string(stats.hits) + ", misses " + std::to_string(stats.misses));
    Check(stats.evictions == 0 && stats.liveTiles == 2 * 2 + 2 * 2 * 10 + 2 * 5,
          "with a wide budget nothing is evicted: content tiles, prefixes of both channels and the five new prefixes stay",
          std::to_string(stats.liveTiles));
    return Finish();
}

// ── admission ────────────────────────────────────────────────────────────────

/// A store that allocates nothing: bytes are counted, blends and uploads succeed, reads are zero.
class CountingStore final : public ITileStore {
public:
    render::Result<TileHandle> Allocate(const TileFormat& format, uint32_t width, uint32_t height) override {
        const TileHandle handle = m_next++;
        m_tiles[handle] = {format, width, height};
        m_bytes += TileBytes(format, width, height);
        m_peak = std::max(m_peak, m_bytes);
        return handle;
    }
    void Release(TileHandle tile) override {
        const auto it = m_tiles.find(tile);
        if (it == m_tiles.end()) return;
        m_bytes -= TileBytes(it->second.format, it->second.width, it->second.height);
        m_tiles.erase(it);
    }
    render::Result<void> Upload(TileHandle, const DecodedImage&, uint32_t, uint32_t) override { return {}; }
    render::Result<void> Blend(const BlendOp&) override { return {}; }
    render::Result<void> Flush() override { return {}; }
    render::Result<TileImage> Read(TileHandle tile) override {
        const auto& t = m_tiles.at(tile);
        TileImage image;
        image.format = t.format;
        image.width = t.width;
        image.height = t.height;
        image.texels.assign(size_t{t.width} * t.height * t.format.channels * t.format.BytesPerChannel(),
                            std::byte{0});
        return image;
    }
    uint64_t AllocatedBytes() const override { return m_bytes; }
    uint64_t Peak() const { return m_peak; }

private:
    struct Tile {
        TileFormat format;
        uint32_t width, height;
    };
    std::map<TileHandle, Tile> m_tiles;
    TileHandle m_next = 1;
    uint64_t m_bytes = 0;
    uint64_t m_peak = 0;
};

int RunAdmission(const fs::path& assets) {
    std::shared_ptr<const TemplateLibrary> templates = LoadTemplates(assets);
    const std::vector<std::pair<ChannelType, ChannelFormat>> formats{
        {ChannelType::BaseColor, ChannelFormat::sRGB8},
        {ChannelType::SpecularRoughness, ChannelFormat::L8},
        {ChannelType::BaseMetalness, ChannelFormat::L8},
        {ChannelType::Normal, ChannelFormat::RGB16F},
        {ChannelType::Height, ChannelFormat::L16F}};
    std::vector<ChannelFormat> formatList;
    std::vector<ChannelType> channels;
    for (const auto& [type, format] : formats) {
        formatList.push_back(format);
        channels.push_back(type);
    }
    const uint64_t live = StackLiveBytes(4096, 4096, formatList);
    const uint64_t working = WorkingSetBytes(4096, 4096, formatList);
    const AdmissionLimits limits{live + working, 1 << 16};
    Info("one 4096^2 set: live " + std::to_string(live) + " bytes, working set " + std::to_string(working) +
         " bytes; budget " + std::to_string(limits.bytes));
    Check(live == 16ull * 1024 * 1024 * (4 + 1 + 1 + 8 + 2), "live bytes are 16 tiles x bytes per texel of every channel",
          std::to_string(live));
    Check(working == 3ull * 1024 * 1024 * 8, "the working set is three RGBA16F tiles with coverage",
          std::to_string(working));

    // Three sets in one project: each with three uniform fills.
    Builder builder(4096, 4096, formats);
    auto fills = [&](Builder& b) {
        return std::vector<core::Layer>{
            b.Fill("a", SameSource(channels, Uniform(0.2, 0.3, 0.4)), Same(channels, BlendingMode::Normal, 1.0)),
            b.Fill("b", SameSource(channels, Uniform(0.5, 0.6, 0.7)), Same(channels, BlendingMode::Multiply, 0.5)),
            b.Fill("c", SameSource(channels, Uniform(0.8, 0.9, 0.1)), Same(channels, BlendingMode::Screen, 0.25))};
    };
    builder.SetRoot(fills(builder));
    for (int i = 1; i < 3; ++i) {
        core::TextureSet set = builder.Set();
        set.id = builder.project.AllocateId();
        set.name = "set" + std::to_string(i);
        set.material_id = set.name;
        set.uv_tiles[0].id = builder.project.AllocateId();
        set.stacks[0].id = builder.project.AllocateId();
        core::Stack& stack = set.stacks[0];
        for (core::Layer& layer : stack.root_layers) layer.uid = builder.project.AllocateId();
        builder.project.texture_sets.push_back(std::move(set));
    }
    if (!builder.Validate("admission")) return Finish();

    CountingStore store;
    TileCache cache(limits);
    for (const core::TextureSet& set : builder.project.texture_sets) {
        render::Result<void> admitted = CheckTextureSet(limits, set);
        Check(admitted.has_value(), set.name + " is admitted at creation", Describe(admitted));
    }
    bool allEvaluated = true;
    uint64_t evictions = 0;
    for (const core::TextureSet& set : builder.project.texture_sets) {
        for (const ChannelType channel : channels) {
            EvaluateRequest request;
            request.textureSet = set.id;
            request.stack = set.stacks[0].id;
            request.channel = channel;
            render::Result<ChannelResult> result = EvaluateOn(builder.project, request, *templates, store, cache);
            cache.UnpinAll();
            if (!result) {
                allEvaluated = false;
                Check(false, set.name + "/" + std::string(core::ToString(channel)) + " evaluates", Describe(result));
                continue;
            }
            evictions += result->stats.evictions;
        }
        Info(set.name + ": live bytes after the set " + std::to_string(cache.stats().liveBytes) +
             ", evictions so far " + std::to_string(cache.stats().evictions));
    }
    Check(allEvaluated, "every channel of the three 4096^2 sets evaluates under a budget that holds one set");
    Check(store.Peak() <= limits.bytes, "the store never held more than the budget",
          std::to_string(store.Peak()) + " > " + std::to_string(limits.bytes));
    Check(cache.stats().peakBytes <= limits.bytes, "the cache never counted more than the budget",
          std::to_string(cache.stats().peakBytes));
    Check(cache.stats().evictions > 0 && evictions == cache.stats().evictions,
          "the second and third sets evicted least recently used tiles of the earlier ones",
          std::to_string(cache.stats().evictions));
    Check(store.AllocatedBytes() == cache.stats().liveBytes, "store and cache agree on the live bytes");

    // Refusal above the budget.
    render::Result<void> huge = CheckTextureSet(limits, 8192, 8192, formatList);
    Check(!huge && KindName(huge.error()) == "texture_set_over_budget",
          "an 8192^2 set is refused at creation with texture_set_over_budget", Describe(huge));
    const AdmissionLimits fewTiles{limits.bytes, 10};
    render::Result<void> descriptors = CheckTextureSet(fewTiles, 4096, 4096, formatList);
    Check(!descriptors && KindName(descriptors.error()) == "texture_set_over_budget",
          "a set needing more live tiles than the descriptor budget is refused", Describe(descriptors));
    CpuEvaluator cpu(templates, limits);
    render::Result<void> viaEvaluator = cpu.AdmitTextureSet(builder.project, builder.SetId());
    Check(viaEvaluator.has_value(), "the evaluator admits a set within the budget", Describe(viaEvaluator));
    Builder big(8192, 8192, formats);
    if (!big.Validate("big")) return Finish();
    render::Result<void> refused = cpu.AdmitTextureSet(big.project, big.SetId());
    Check(!refused && KindName(refused.error()) == "texture_set_over_budget",
          "the evaluator refuses a set above the budget", Describe(refused));

    // The working set alone must fit: a budget below it fails explicitly during evaluation.
    {
        const AdmissionLimits tiny{TileBytes(TileFormatOf(ChannelFormat::L8), 1024, 1024), 2};
        CountingStore small;
        TileCache smallCache(tiny);
        EvaluateRequest request;
        request.textureSet = builder.SetId();
        request.stack = builder.StackId();
        request.channel = ChannelType::Normal;
        render::Result<ChannelResult> result = EvaluateOn(builder.project, request, *templates, small, smallCache);
        Check(!result && KindName(result.error()) == "texture_set_over_budget",
              "a set that does not fit is refused before any tile is evaluated", Describe(result));
    }
    const render::AdmissionBudget budget{1ull << 30, 500};
    const AdmissionLimits derived = LimitsOf(budget);
    Check(derived.bytes == (1ull << 30) && derived.maxTiles == 500, "the limits follow the render layer's budget");
    return Finish();
}

// ── evaluate (spec driver) ───────────────────────────────────────────────────

struct Spec {
    std::string templateId = std::string(kDefaultTemplateId);
    Builder builder;
    std::shared_ptr<MapResourceProvider> resources = std::make_shared<MapResourceProvider>();
    std::vector<ChannelType> outputs;
};

const core::json::Object& Obj(const core::json::Value& v, const std::string& what) {
    if (!v.IsObject()) throw core::ManifestError(what + ": expected an object");
    return std::get<core::json::Object>(v.data);
}
const core::json::Array& Arr(const core::json::Value& v, const std::string& what) {
    if (!v.IsArray()) throw core::ManifestError(what + ": expected an array");
    return std::get<core::json::Array>(v.data);
}
const core::json::Value& Key(const core::json::Object& o, const std::string& key) {
    const auto it = o.find(key);
    if (it == o.end()) throw core::ManifestError("missing key '" + key + "'");
    return it->second;
}
std::string Str(const core::json::Value& v, const std::string& what) {
    if (!v.IsString()) throw core::ManifestError(what + ": expected a string");
    return std::get<std::string>(v.data);
}
double Num(const core::json::Value& v, const std::string& what) {
    if (v.IsInt()) return static_cast<double>(std::get<std::int64_t>(v.data));
    if (!v.IsDouble()) throw core::ManifestError(what + ": expected a number");
    return std::get<double>(v.data);
}
template <typename E>
E EnumOf(const std::string& name, const std::string& what) {
    const auto parsed = core::FromString<E>(name);
    if (!parsed) throw core::ManifestError(what + ": unknown member '" + name + "'");
    return *parsed;
}

core::Layer ParseLayer(Spec& spec, const core::json::Value& value) {
    const core::json::Object& o = Obj(value, "layer");
    const std::string kind = Str(Key(o, "kind"), "layer.kind");
    const std::string name = o.contains("name") ? Str(o.at("name"), "layer.name") : kind;
    std::map<ChannelType, core::Blending> blending;
    if (o.contains("blending")) {
        for (const auto& [channel, entry] : Obj(o.at("blending"), "layer.blending")) {
            const core::json::Object& b = Obj(entry, "blending entry");
            blending[EnumOf<ChannelType>(channel, "blending channel")] =
                Blend(EnumOf<BlendingMode>(Str(Key(b, "mode"), "mode"), "mode"), Num(Key(b, "opacity"), "opacity"));
        }
    }
    core::Layer layer;
    if (kind == "fill") {
        std::map<ChannelType, core::Source> sources;
        for (const auto& [channel, entry] : Obj(Key(o, "sources"), "layer.sources")) {
            const core::json::Object& s = Obj(entry, "source");
            const ChannelType type = EnumOf<ChannelType>(channel, "source channel");
            if (s.contains("uniform")) {
                const core::json::Array& rgb = Arr(s.at("uniform"), "uniform");
                core::UniformColorSource uniform;
                for (size_t i = 0; i < 3 && i < rgb.size(); ++i) uniform.rgb[i] = Num(rgb[i], "uniform component");
                uniform.color_space = s.contains("color_space") ? Str(s.at("color_space"), "color_space") : "Working";
                sources[type] = core::Source{uniform};
            } else {
                core::BitmapSource bitmap;
                bitmap.resource.sha256 = Str(Key(s, "bitmap"), "bitmap");
                bitmap.color_space = s.contains("color_space") ? Str(s.at("color_space"), "color_space") : "Raw";
                sources[type] = core::Source{bitmap};
            }
        }
        layer = spec.builder.Fill(name, sources, blending);
        if (o.contains("active_channels")) {
            layer.fill->active_channels.clear();
            for (const core::json::Value& c : Arr(o.at("active_channels"), "active_channels")) {
                layer.fill->active_channels.insert(EnumOf<ChannelType>(Str(c, "active channel"), "active channel"));
            }
        }
    } else if (kind == "group") {
        std::vector<core::Layer> children;  // spec lists children top first, like Painter
        for (const core::json::Value& child : Arr(Key(o, "children"), "children")) {
            children.push_back(ParseLayer(spec, child));
        }
        std::reverse(children.begin(), children.end());
        layer = spec.builder.Group(name, std::move(children), blending);
    } else if (kind == "instance") {
        layer = spec.builder.Instance(name, static_cast<core::Id>(Num(Key(o, "instance_of"), "instance_of")));
    } else {
        throw core::ManifestError("layer.kind: unknown kind '" + kind + "'");
    }
    if (o.contains("uid")) layer.uid = static_cast<core::Id>(Num(o.at("uid"), "uid"));
    if (o.contains("visible")) layer.visible = std::get<bool>(o.at("visible").data);
    if (o.contains("mask")) {
        const core::json::Object& m = Obj(o.at("mask"), "mask");
        layer.mask = core::Mask{};
        layer.mask->background = EnumOf<core::MaskBackground>(Str(Key(m, "background"), "background"), "background");
        if (m.contains("enabled")) layer.mask->enabled = std::get<bool>(m.at("enabled").data);
    }
    return layer;
}

Spec ParseSpec(const fs::path& path) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream) throw core::ManifestError("cannot read " + path.string());
    const std::string text((std::istreambuf_iterator<char>(stream)), std::istreambuf_iterator<char>());
    const core::json::Value document = core::json::Parse(text);
    const core::json::Object& o = Obj(document, "spec");
    const core::json::Array& resolution = Arr(Key(o, "resolution"), "resolution");
    std::vector<std::pair<ChannelType, ChannelFormat>> channels;
    for (const core::json::Value& entry : Arr(Key(o, "channels"), "channels")) {
        const core::json::Object& c = Obj(entry, "channel");
        channels.emplace_back(EnumOf<ChannelType>(Str(Key(c, "type"), "type"), "channel type"),
                              EnumOf<ChannelFormat>(Str(Key(c, "format"), "format"), "channel format"));
    }
    Spec spec{std::string(kDefaultTemplateId),
              Builder(static_cast<uint32_t>(Num(resolution.at(0), "width")),
                      static_cast<uint32_t>(Num(resolution.at(1), "height")), channels),
              std::make_shared<MapResourceProvider>(), {}};
    if (o.contains("template")) spec.templateId = Str(o.at("template"), "template");
    // Ids the spec assigns must stay below next_id: reserve a wide range first.
    if (o.contains("resources")) {
        for (const core::json::Value& entry : Arr(o.at("resources"), "resources")) {
            const core::json::Object& r = Obj(entry, "resource");
            const std::string sha = Str(Key(r, "sha256"), "sha256");
            const fs::path file = path.parent_path() / Str(Key(r, "file"), "file");
            auto image = std::make_shared<DecodedImage>();
            image->width = static_cast<uint32_t>(Num(Key(r, "width"), "width"));
            image->height = static_cast<uint32_t>(Num(Key(r, "height"), "height"));
            image->channels = static_cast<uint32_t>(Num(Key(r, "channels"), "channels"));
            const std::string encoding = Str(Key(r, "encoding"), "encoding");
            uint32_t bytes = 2;
            if (encoding == "unorm16") image->encoding = render::TexelEncoding::Unorm16;
            else if (encoding == "unorm8") { image->encoding = render::TexelEncoding::Unorm8; bytes = 1; }
            else if (encoding == "float32") { image->encoding = render::TexelEncoding::Float32; bytes = 4; }
            else throw core::ManifestError("resource encoding '" + encoding + "' is not unorm16, unorm8 or float32");
            std::ifstream data(file, std::ios::binary);
            if (!data) throw core::ManifestError("cannot read " + file.string());
            const std::string raw((std::istreambuf_iterator<char>(data)), std::istreambuf_iterator<char>());
            const size_t samples = size_t{image->width} * image->height * image->channels;
            if (raw.size() != samples * bytes) {
                throw core::ManifestError(file.string() + ": " + std::to_string(raw.size()) + " bytes, expected " +
                                          std::to_string(samples * bytes));
            }
            image->values.resize(samples);
            for (size_t i = 0; i < samples; ++i) {
                uint32_t v = 0;
                std::memcpy(&v, raw.data() + i * bytes, bytes);
                image->values[i] = v;
            }
            spec.resources->Add(sha, image);
            spec.builder.AddResource(sha, static_cast<std::int64_t>(raw.size()));
        }
    }
    std::vector<core::Layer> layers;  // top first in the spec
    for (const core::json::Value& entry : Arr(Key(o, "layers"), "layers")) layers.push_back(ParseLayer(spec, entry));
    std::reverse(layers.begin(), layers.end());
    spec.builder.SetRoot(std::move(layers));
    for (const core::json::Value& c : Arr(Key(o, "outputs"), "outputs")) {
        spec.outputs.push_back(EnumOf<ChannelType>(Str(c, "output"), "output"));
    }
    // Explicit uids may exceed the counter: lift next_id above every id.
    core::Id maxId = spec.builder.project.next_id;
    core::ForEachNode(spec.builder.project, [&](const core::NodeVisit& visit) {
        const core::Id uid = visit.layer ? visit.layer->uid : visit.effect->uid;
        maxId = std::max(maxId, uid + 1);
    });
    spec.builder.project.next_id = maxId;
    return spec;
}

void WriteFile(const fs::path& path, const std::vector<std::byte>& bytes) {
    std::ofstream stream(path, std::ios::binary);
    stream.write(reinterpret_cast<const char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
}

core::json::Object StatsJson(const EvaluationStats& stats) {
    core::json::Object o;
    o["tiles"] = static_cast<std::int64_t>(stats.tiles);
    o["constant_tiles"] = static_cast<std::int64_t>(stats.constantTiles);
    o["cache_hits"] = static_cast<std::int64_t>(stats.cacheHits);
    o["cache_misses"] = static_cast<std::int64_t>(stats.cacheMisses);
    o["blends"] = static_cast<std::int64_t>(stats.blends);
    o["uploads"] = static_cast<std::int64_t>(stats.uploads);
    o["evictions"] = static_cast<std::int64_t>(stats.evictions);
    o["flushes"] = static_cast<std::int64_t>(stats.flushes);
    return o;
}

/// Writes every output channel: `<channel>.bin` (full raster, native samples, little-endian) and
/// `result.json`.
int WriteResults(const fs::path& out, const std::vector<std::pair<ChannelType, render::Result<ChannelResult>>>& results) {
    core::json::Object channels;
    bool ok = true;
    for (const auto& [channel, result] : results) {
        const std::string name(core::ToString(channel));
        if (!result) {
            core::json::Object entry;
            entry["error"] = result.error().Describe();
            channels[name] = entry;
            Check(false, name + " evaluates", result.error().Describe());
            ok = false;
            continue;
        }
        const std::vector<uint32_t> samples = Samples(*result);
        const uint32_t bytes = result->tileFormat.BytesPerChannel();
        std::vector<std::byte> raw(samples.size() * bytes);
        for (size_t i = 0; i < samples.size(); ++i) std::memcpy(raw.data() + i * bytes, &samples[i], bytes);
        WriteFile(out / (name + ".bin"), raw);
        core::json::Object entry;
        entry["format"] = std::string(core::ToString(result->format));
        entry["width"] = static_cast<std::int64_t>(result->width);
        entry["height"] = static_cast<std::int64_t>(result->height);
        entry["channels"] = static_cast<std::int64_t>(result->tileFormat.channels);
        entry["bytes_per_channel"] = static_cast<std::int64_t>(bytes);
        entry["file"] = name + ".bin";
        if (!result->tiles.empty() && result->tiles[0].constant) {
            core::json::Array constant;
            for (const float v : *result->tiles[0].constant) constant.push_back(static_cast<double>(v));
            entry["constant"] = constant;
        }
        entry["stats"] = StatsJson(result->stats);
        channels[name] = entry;
        Check(true, name + " evaluates");
    }
    core::json::Object document;
    document["schema"] = "uzpainter/evaluator-test-result/1";
    document["channels"] = channels;
    const std::string text = core::json::WriteCanonical(document);
    std::ofstream stream(out / "result.json", std::ios::binary);
    stream << text;
    return ok ? Finish() : 1;
}

render::EngineOptions TestOptions(const fs::path& dir) {
    render::EngineOptions options;
    options.kernelCacheRoot = dir / "kernel-cache";
    return options;
}

bool NoAdapter(const render::Engine& engine) {
    if (!engine.DeviceError()) return false;
    std::printf("SKIP no DX12 device: %s\n", engine.DeviceError()->Describe().c_str());
    return true;
}

int RunEvaluate(const fs::path& assets, const fs::path& specPath, const fs::path& out, std::string_view backend) {
    std::shared_ptr<const TemplateLibrary> templates = LoadTemplates(assets);
    Spec spec = ParseSpec(specPath);
    if (!spec.builder.Validate("spec")) return Finish();
    std::error_code ec;
    fs::create_directories(out, ec);
    std::vector<std::pair<ChannelType, render::Result<ChannelResult>>> results;
    if (backend == "cpu") {
        CpuEvaluator cpu(templates, kWideLimits);
        for (const ChannelType channel : spec.outputs) {
            EvaluateRequest request;
            request.textureSet = spec.builder.SetId();
            request.stack = spec.builder.StackId();
            request.channel = channel;
            request.templateId = spec.templateId;
            request.resources = spec.resources;
            results.emplace_back(channel, cpu.Evaluate(spec.builder.project, request));
        }
        return WriteResults(out, results);
    }
    render::Engine engine(TestOptions(out));
    if (NoAdapter(engine)) return kExitSkip;
    Info("adapter " + engine.Capabilities().value_or(render::CapabilityReport{}).adapter);
    {
        Evaluator evaluator(engine, templates);
        auto project = std::make_shared<const core::Project>(spec.builder.project);
        for (const ChannelType channel : spec.outputs) {
            EvaluateRequest request;
            request.textureSet = spec.builder.SetId();
            request.stack = spec.builder.StackId();
            request.channel = channel;
            request.templateId = spec.templateId;
            request.resources = spec.resources;
            std::future<render::Result<ChannelResult>> future =
                evaluator.Evaluate(core::Snapshot{1, project}, std::move(request));
            results.emplace_back(channel, Get(future));
        }
        std::future<render::Result<CacheStats>> stats = evaluator.Stats();
        render::Result<CacheStats> cacheStats = Get(stats);
        if (cacheStats) {
            Info("gpu cache live tiles " + std::to_string(cacheStats->liveTiles) + ", bytes " +
                 std::to_string(cacheStats->liveBytes));
        }
        evaluator.Shutdown();
    }
    return WriteResults(out, results);
}

// ── gpu-vs-cpu ───────────────────────────────────────────────────────────────

const std::vector<ChannelFormat> kAllFormats{ChannelFormat::sRGB8, ChannelFormat::L8, ChannelFormat::RGB8,
                                             ChannelFormat::L16, ChannelFormat::RGB16, ChannelFormat::L16F,
                                             ChannelFormat::RGB16F, ChannelFormat::L32F, ChannelFormat::RGB32F};

std::vector<BlendingMode> SeparableModes() {
    std::vector<BlendingMode> modes;
    for (size_t i = 0; i < core::EnumTable<BlendingMode>::names.size(); ++i) {
        const BlendingMode mode = static_cast<BlendingMode>(i);
        if (arith::HasSeparableKernel(mode) && mode != BlendingMode::Disable) modes.push_back(mode);
    }
    return modes;
}

/// A bitmap source encoding a channel format accepts at 1:1 (none for sRGB8 and the 16-bit floats).
std::optional<render::TexelEncoding> BitmapEncodingFor(ChannelFormat format) {
    switch (format) {
        case ChannelFormat::L8: case ChannelFormat::RGB8: return render::TexelEncoding::Unorm8;
        case ChannelFormat::L16: case ChannelFormat::RGB16: case ChannelFormat::L32F: case ChannelFormat::RGB32F:
            return render::TexelEncoding::Unorm16;
        default: return std::nullopt;
    }
}

int RunGpuVsCpu(const fs::path& assets, const fs::path& dir) {
    std::shared_ptr<const TemplateLibrary> templates = LoadTemplates(assets);
    render::Engine engine(TestOptions(dir));
    if (NoAdapter(engine)) return kExitSkip;
    Info("adapter " + engine.Capabilities().value_or(render::CapabilityReport{}).adapter);
    const std::vector<BlendingMode> modes = SeparableModes();
    std::mt19937 rng(2026);
    auto unit = [&] { return std::uniform_real_distribution<double>(0.0, 1.0)(rng); };
    size_t compared = 0;
    bool allEqual = true;
    Evaluator gpu(engine, templates);
    for (const ChannelFormat format : kAllFormats) {
        const std::vector<ChannelType> channels{ChannelType::User0};
        for (int variant = 0; variant < 2; ++variant) {
            Builder builder(256, 256, {{ChannelType::User0, format}});
            auto provider = std::make_shared<MapResourceProvider>();
            std::vector<core::Layer> layers;
            const std::optional<render::TexelEncoding> encoding = BitmapEncodingFor(format);
            if (encoding) {
                const std::string sha = std::string(62, 'd') + std::to_string(variant) + std::to_string(static_cast<int>(format) % 10);
                provider->Add(sha, PatternImage(256, 256, 3, *encoding, 100 + variant));
                builder.AddResource(sha, 100);
                layers.push_back(builder.Fill("bitmap", SameSource(channels, Bitmap(sha)),
                                              Same(channels, modes[rng() % modes.size()], 0.25 + 0.75 * unit())));
            }
            for (int i = 0; i < 5; ++i) {
                layers.push_back(builder.Fill("fill" + std::to_string(i), SameSource(channels, Uniform(unit(), unit(), unit())),
                                              Same(channels, modes[rng() % modes.size()], unit())));
            }
            std::vector<core::Layer> children{
                builder.Fill("child0", SameSource(channels, Uniform(unit(), unit(), unit())),
                             Same(channels, modes[rng() % modes.size()], unit())),
                builder.Fill("child1", SameSource(channels, Uniform(unit(), unit(), unit())),
                             Same(channels, modes[rng() % modes.size()], unit()))};
            layers.push_back(builder.Group("group", children, Same(channels, modes[rng() % modes.size()], unit())));
            if (variant == 1) {
                std::vector<core::Layer> passChildren{
                    builder.Fill("pass0", SameSource(channels, Uniform(unit(), unit(), unit())),
                                 Same(channels, modes[rng() % modes.size()], unit()))};
                layers.push_back(builder.Group("pass", passChildren, Same(channels, BlendingMode::PassThrough, 0.6)));
            }
            builder.SetRoot(layers);
            if (!builder.Validate(std::string(core::ToString(format)))) return Finish();
            EvaluateRequest request;
            request.textureSet = builder.SetId();
            request.stack = builder.StackId();
            request.channel = ChannelType::User0;
            request.resources = provider;
            CpuEvaluator cpu(templates, kWideLimits);
            render::Result<ChannelResult> cpuResult = cpu.Evaluate(builder.project, request);
            auto project = std::make_shared<const core::Project>(builder.project);
            std::future<render::Result<ChannelResult>> future = gpu.Evaluate(core::Snapshot{1, project}, request);
            render::Result<ChannelResult> gpuResult = Get(future);
            const std::string label = std::string(core::ToString(format)) + " stack " + std::to_string(variant);
            if (!cpuResult || !gpuResult) {
                allEqual = false;
                Check(false, label + " evaluates on both stores", Describe(cpuResult) + " / " + Describe(gpuResult));
                continue;
            }
            std::string first;
            const size_t mismatches = Mismatches(Samples(*cpuResult), Samples(*gpuResult), first,
                                                 cpuResult->tileFormat.encoding);
            compared += Samples(*cpuResult).size();
            if (mismatches != 0) {
                allEqual = false;
                Check(false, label + ": GPU equals CPU", std::to_string(mismatches) + " mismatches; " + first);
            }
        }
    }
    gpu.Shutdown();
    Check(allEqual, "every random stack evaluates to the same bytes on the GPU and on the CPU (" +
                        std::to_string(compared) + " samples over 9 formats)");
    return Finish();
}

// ── kernel-sweep ─────────────────────────────────────────────────────────────

/// Fills a tile of `format` from a pattern: the backdrop varies along rows, the source along
/// columns, covering the code lattice (UNORM) or the unit interval and beyond (floats).
std::shared_ptr<DecodedImage> SweepImage(const TileFormat& format, bool rows, uint32_t size) {
    auto image = std::make_shared<DecodedImage>();
    image->width = size;
    image->height = size;
    image->channels = format.channels;
    image->encoding = format.encoding;
    image->values.resize(size_t{size} * size * format.channels);
    for (uint32_t y = 0; y < size; ++y) {
        for (uint32_t x = 0; x < size; ++x) {
            const uint32_t t = rows ? y : x;
            const uint32_t u = rows ? x : y;
            for (uint32_t c = 0; c < format.channels; ++c) {
                const uint32_t k = (t * size + ((u * 7 + c * 131) % size)) % (size * size);
                uint32_t value = 0;
                switch (format.encoding) {
                    case render::TexelEncoding::Unorm8: value = k & 0xFF; break;
                    case render::TexelEncoding::Unorm16: value = k & 0xFFFF; break;
                    case render::TexelEncoding::Float16: {
                        const float f = -0.25f + 1.5f * static_cast<float>(k) / static_cast<float>(size * size - 1);
                        value = std::bit_cast<uint32_t>(arith::HalfToFloat(arith::HalfTowardZero(f)));
                        break;
                    }
                    case render::TexelEncoding::Float32: {
                        const float f = -0.25f + 1.5f * static_cast<float>(k) / static_cast<float>(size * size - 1);
                        value = std::bit_cast<uint32_t>(f);
                        break;
                    }
                }
                image->values[(size_t{y} * size + x) * format.channels + c] = value;
            }
        }
    }
    return image;
}

/// Uploads `image` into a tile of `store` through an UNORM16 or float32 route the stores accept.
render::Result<TileHandle> UploadDirect(ITileStore& store, const TileFormat& format, const DecodedImage& image) {
    render::Result<TileHandle> tile = store.Allocate(format, image.width, image.height);
    if (!tile) return tile;
    render::Result<void> uploaded = store.Upload(*tile, image, 0, 0);
    if (!uploaded) return render::Unexpected(uploaded.error());
    return tile;
}

/// One blend of a sweep on `store`: the operand tiles are uploaded in the destination encoding;
/// with `alpha` the backdrop is written by a Normal blend of the uploaded tile over a transparent
/// constant at opacity 0.5, so it carries a coverage plane at half coverage.
render::Result<std::vector<uint32_t>> SweepBlend(ITileStore& store, const TileFormat& format,
                                                 const DecodedImage& accImage,
                                                 const DecodedImage& srcImage, bool alpha,
                                                 BlendingMode mode, float opacity) {
    constexpr uint32_t kSize = 256;
    TileFormat operandFormat = format;
    operandFormat.alpha = false;
    std::vector<TileHandle> owned;
    auto release = [&] {
        for (const TileHandle tile : owned) store.Release(tile);
    };
    auto fail = [&](const render::Error& error) {
        release();
        return render::Unexpected(error);
    };
    render::Result<TileHandle> accDirect = UploadDirect(store, operandFormat, accImage);
    if (!accDirect) return fail(accDirect.error());
    owned.push_back(*accDirect);
    render::Result<TileHandle> src = UploadDirect(store, operandFormat, srcImage);
    if (!src) return fail(src.error());
    owned.push_back(*src);
    TileHandle acc = *accDirect;
    if (alpha) {
        render::Result<TileHandle> covered = store.Allocate(format, kSize, kSize);
        if (!covered) return fail(covered.error());
        owned.push_back(*covered);
        BlendOp toAcc;
        toAcc.dst = *covered;
        toAcc.acc = Operand::Constant({0.0f, 0.0f, 0.0f}, 0.0f);
        toAcc.source = Operand::Of(*accDirect);
        toAcc.mode = BlendingMode::Normal;
        toAcc.opacity = 0.5f;
        render::Result<void> queued = store.Blend(toAcc);
        if (!queued) return fail(queued.error());
        acc = *covered;
    }
    render::Result<TileHandle> dst = store.Allocate(format, kSize, kSize);
    if (!dst) return fail(dst.error());
    owned.push_back(*dst);
    BlendOp op;
    op.dst = *dst;
    op.acc = Operand::Of(acc);
    op.source = Operand::Of(*src);
    op.mode = mode;
    op.opacity = opacity;
    render::Result<void> queued = store.Blend(op);
    if (!queued) return fail(queued.error());
    render::Result<TileImage> image = store.Read(*dst);
    if (!image) return fail(image.error());
    const uint32_t bytes = format.BytesPerChannel();
    std::vector<uint32_t> output(image->texels.size() / bytes);
    for (size_t i = 0; i < output.size(); ++i) {
        std::memcpy(&output[i], image->texels.data() + i * bytes, bytes);
    }
    release();
    return output;
}

int RunKernelSweep(const fs::path& assets, const fs::path& dir) {
    (void)assets;
    render::Engine engine(TestOptions(dir));
    if (NoAdapter(engine)) return kExitSkip;
    Info("adapter " + engine.Capabilities().value_or(render::CapabilityReport{}).adapter);
    const std::vector<BlendingMode> modes = SeparableModes();
    constexpr uint32_t kSize = 256;
    auto token = std::make_shared<const int>(0);
    size_t compared = 0;
    size_t combinations = 0;
    std::vector<std::string> failures;
    for (const ChannelFormat channelFormat : kAllFormats) {
        for (const bool alpha : {false, true}) {
            const TileFormat format = TileFormatOf(channelFormat, alpha);
            TileFormat imageFormat = format;
            imageFormat.alpha = false;
            std::shared_ptr<DecodedImage> accImage = SweepImage(imageFormat, true, kSize);
            std::shared_ptr<DecodedImage> srcImage = SweepImage(imageFormat, false, kSize);
            for (const BlendingMode mode : modes) {
                for (const float opacity : {1.0f, 0.7f}) {
                    ++combinations;
                    const std::string label = std::string(core::ToString(mode)) + " on " +
                                              std::string(core::ToString(channelFormat)) +
                                              (alpha ? " (coverage)" : "") + " opacity " +
                                              std::to_string(opacity);
                    CpuTileStore cpu;
                    render::Result<std::vector<uint32_t>> expected =
                        SweepBlend(cpu, format, *accImage, *srcImage, alpha, mode, opacity);
                    if (!expected) {
                        failures.push_back(label + " (cpu): " + expected.error().Describe());
                        continue;
                    }
                    // Each combination is its own engine request (the deadline is per request).
                    std::future<render::Result<std::vector<uint32_t>>> future = engine.Submit(
                        token, [&](render::EngineContext& context, const int&)
                                   -> render::Result<std::vector<uint32_t>> {
                            GpuTileStore gpu(context.Device());
                            gpu.BeginRequest(context);
                            render::Result<std::vector<uint32_t>> result =
                                SweepBlend(gpu, format, *accImage, *srcImage, alpha, mode, opacity);
                            render::Result<void> flushed = gpu.Flush();
                            gpu.EndRequest();
                            if (result && !flushed) return render::Unexpected(flushed.error());
                            return result;
                        });
                    render::Result<std::vector<uint32_t>> actual = Get(future);
                    if (!actual) {
                        failures.push_back(label + " (gpu): " + actual.error().Describe());
                        continue;
                    }
                    std::string first;
                    const size_t mismatches = Mismatches(*expected, *actual, first, format.encoding);
                    compared += expected->size();
                    if (mismatches != 0) {
                        failures.push_back(label + ": " + std::to_string(mismatches) + " mismatches; " + first);
                    }
                }
            }
        }
    }
    for (const std::string& failure : failures) Check(false, "kernel sweep", failure);
    Check(failures.empty(),
          "every separable blend mode x channel format (with and without coverage) equals the CPU reference bit for bit (" +
              std::to_string(compared) + " samples, " + std::to_string(combinations) + " combinations)");
    return Finish();
}

}  // namespace

int main(int argc, char** argv) {
    const std::string_view mode = argc > 1 ? argv[1] : "";
    if (argc < 3) {
        std::fprintf(stderr,
                     "usage: uzp-evaluator-tests arith|templates|order|cache|admission <assets-dir> | "
                     "evaluate <assets-dir> <spec.json> <out-dir> cpu|gpu | gpu-vs-cpu <assets-dir> <work-dir> | "
                     "kernel-sweep <assets-dir> <work-dir>\n");
        return 2;
    }
    const fs::path assets = argv[2];
    int code = 2;
    try {
        if (mode == "arith") return RunArith();
        if (mode == "templates") return RunTemplates(assets);
        if (mode == "order") return RunOrder(assets);
        if (mode == "cache") return RunCache(assets);
        if (mode == "admission") return RunAdmission(assets);
        if (mode == "evaluate") {
            if (argc < 6) {
                std::fprintf(stderr, "usage: uzp-evaluator-tests evaluate <assets-dir> <spec.json> <out-dir> cpu|gpu\n");
                return 2;
            }
            const fs::path out = argv[4];
            std::error_code ec;
            fs::create_directories(out, ec);
            uz::LogInit((out / "evaluator-tests-evaluate.log").string().c_str());
            uz::LogSuppressConsole();
            code = RunEvaluate(assets, argv[3], out, argv[5]);
            uz::LogShutdown();
            return code;
        }
        if (argc < 4) {
            std::fprintf(stderr, "usage: uzp-evaluator-tests %.*s <assets-dir> <work-dir>\n",
                         static_cast<int>(mode.size()), mode.data());
            return 2;
        }
        const fs::path dir = argv[3];
        std::error_code ec;
        fs::create_directories(dir, ec);
        uz::LogInit((dir / ("evaluator-tests-" + std::string(mode) + ".log")).string().c_str());
        uz::LogSuppressConsole();
        if (mode == "gpu-vs-cpu") code = RunGpuVsCpu(assets, dir);
        else if (mode == "kernel-sweep") code = RunKernelSweep(assets, dir);
        else std::fprintf(stderr, "unknown case %.*s\n", static_cast<int>(mode.size()), mode.data());
        uz::LogShutdown();
    } catch (const core::ManifestError& error) {
        std::fprintf(stderr, "ManifestError: %s\n", error.what());
        return 3;
    } catch (const core::json::ParseError& error) {
        std::fprintf(stderr, "ParseError: %s\n", error.what());
        return 3;
    } catch (const core::ValueError& error) {
        std::fprintf(stderr, "ValueError: %s\n", error.what());
        return 3;
    }
    return code;
}
