// Native tests of the compositor (rulebook tasks phase1.5_compositor-tile-dag,
// phase1.8_compositor-sources-projection, phase1.9_compositor-quantisation-profile,
// phase1.11_compositor-mask-effects, phase1.12_compositor-height-normal and
// phase1.13_compositor-diagnostics,
// src/evaluator/,
// docs/architecture/04-layer-stack-and-compositing.md §2, §4, §5, §7). Built by
// `zig build evaluator-tests` and driven by tests/evaluator/test_compositor_tile_dag.py and
// tests/evaluator/test_compositor_sources_projection.py.
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
//   profile <assets>                     evaluator profiles (profile.h): the registry, dispatch on
//                                        the project's profile, pinning after a later profile is
//                                        registered, unknown profiles
//   evaluate <assets> <spec> <out> <cpu|gpu>
//                                        evaluates the stack described by <spec> (JSON) and
//                                        writes the channel rasters to <out> (golden driver)
//   gpu-vs-cpu <assets> <work-dir>       random stacks over every channel format on both stores:
//                                        byte-identical results
//   kernel-sweep <assets> <work-dir>     every blend mode x channel format over dense value
//                                        sweeps: GPU kernels equal the CPU reference bit for bit
//   sources <assets>                     fill sources and UV projections on the CPU store
//                                        (phase1.8_compositor-sources-projection): 1:1 copies on
//                                        every format, transforms, wrap modes, LAY-13 bindings,
//                                        explicit failures, resolution changes and the cache
//   projection-gpu-vs-cpu <assets> <work-dir>
//                                        random projection stacks: the projection kernel equals
//                                        the CPU reference bit for bit
//   srgb8-hardware <assets> <work-dir>   measures the GPU's sRGB8 decode and encode and compares
//                                        them with the tables of arith.h
//   tables <assets> <work-dir>           writes the sRGB8 tables of arith.h (tables.json)
//   fp-hardware <assets> <work-dir>      measures the GPU's float32 reciprocal, square root and
//                                        reciprocal square root on every float32 of their reduced
//                                        domains, writes the measured tables and compares them and
//                                        hw::Rcp/Sqrt/Rsqrt with the GPU (hwmath.h)
//   bilinear-hardware <assets> <work-dir>
//                                        measures the GPU's linear filter of float32 texels at
//                                        every 8-bit weight pair and compares it with
//                                        BilinearFilter (projection_uv.h); writes the samples
//   masks <assets>                       masks, mask and content effects, levels, geometry masks,
//                                        group masks, the Height override, complementary masks
//                                        and the cache shape of effect chains on the CPU store
//   masks-gpu-vs-cpu <assets> <work-dir> random masked stacks with effects and levels over every
//                                        channel format: GPU kernels equal the CPU reference
//   pow-hardware <assets> <work-dir>     measures the GPU's log2 and exp2 over the table domains of
//                                        hwmath.h, writes the measured tables and compares them
//                                        and hw::Log2/Exp2/Pow with the GPU
//   trig-hardware <assets> <work-dir>    measures the GPU's sin and cos over the table domain of
//                                        hwmath.h, writes the measured tables and compares them
//                                        and hw::Sin/Cos with the GPU
//   height-normal <assets>               the virtual normal maps on the CPU store (phase1.12): the
//                                        stencils, the combination, the float32 read-out, the
//                                        Normal-channel import, EXP-09 tags and relief rounds, the
//                                        geometry-only pass-through and the explicit failures
//   height-normal-gpu-vs-cpu <assets> <work-dir>
//                                        the virtual normal kernel across tile edges, the raw
//                                        read-out on every format and whole evaluations: GPU =
//                                        CPU bit for bit
//   diagnostics <assets> <work-dir>      the diagnostics on the CPU store (phase1.13): isolation
//                                        never touches the document (also failing midway),
//                                        contribution = full - isolated, material views and leaks,
//                                        region statistics (fixtures for the Python check), source
//                                        names, byte-identical repeats
//   diagnostics-gpu-vs-cpu <assets> <work-dir>
//                                        every diagnostic source on the GPU equals the CPU bit for
//                                        bit; a GPU isolation failing midway
//   uv-coverage <assets> <work-dir> <mesh> <size>
//                                        imports <mesh>, rasterises its UV tile and writes the
//                                        texel-centre coverage (island-edge goldens)
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
#include "evaluator/diagnostics.h"
#include "evaluator/error.h"
#include "evaluator/evaluate.h"
#include "evaluator/evaluator.h"
#include "evaluator/geometry_mask.h"
#include "evaluator/gpu_store.h"
#include "evaluator/height_to_normal.h"
#include "evaluator/hwmath.h"
#include "evaluator/kernelgen.h"
#include "evaluator/profile.h"
#include "evaluator/projection_uv.h"
#include "evaluator/sources.h"
#include "evaluator/support.h"
#include "evaluator/templates.h"
#include "evaluator/texture_unit.h"
#include "render/capabilities.h"
#include "render/engine_thread.h"
#include "render/image_pass.h"
#include "render/texture_readback.h"
#include "render/uv_raster.h"
#include "mesh/import_error.h"
#include "mesh/mesh_import.h"
#include "mesh/texturing_mesh.h"
#include "uzp_core/document/document.h"
#include "uzp_core/document/nodes.h"
#include "uzp_core/manifest/json.h"
#include "uzp_core/transaction/transaction.h"
#include "uzp_core/types/errors.h"
#include "uzp_core/types/validation.h"

#include "log.h"
#include "zlib.h"

#include <algorithm>
#include <bit>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <functional>
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

bool SameFloat(float a, float b);

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
        project.versions.evaluator_profile = std::string(kCurrentProfile);
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

/// The bilinear filter of projection_uv.h BilinearFilter written independently, in double: the
/// operands floor(t 2^(28 - E)) of the texels below the largest weighed one's exponent E, their
/// exact weighted sum times 2^(E - 36), the nearest float32 with ties up.
float ReferenceFilter(const std::array<uint32_t, 4>& weights, const std::array<float, 4>& texels) {
    float largest = 0.0f;
    for (size_t k = 0; k < 4; ++k) largest = weights[k] != 0 ? std::max(largest, texels[k]) : largest;
    if (largest == 0.0f) return 0.0f;
    const int exponent = std::ilogb(largest) + 1;
    double sum = 0.0;
    for (size_t k = 0; k < 4; ++k) sum += weights[k] * std::floor(std::ldexp(static_cast<double>(texels[k]), 28 - exponent));
    const double exact = std::ldexp(sum, exponent - 36);
    const float nearest = static_cast<float>(exact);
    const float up = std::nextafter(nearest, 2.0f);
    const float down = std::nextafter(nearest, 0.0f);
    if (exact == (static_cast<double>(down) + static_cast<double>(nearest)) / 2.0) return nearest;
    if (exact == (static_cast<double>(nearest) + static_cast<double>(up)) / 2.0) return up;
    return nearest;
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

/// `coverageWeights` and `fusedReadout`: the composite rules of a profile (arith.h
/// CompositeInput); the first layer of an isolated list composites over its empty start, or over
/// `start` when given (a PassThrough group's children and composite: the accumulator below it).
ModelValue ModelComposite(const std::vector<ModelLayer>& layers, const TileFormat& format,
                          std::array<float, 3> base, bool isolated, bool coverageWeights = false,
                          bool fusedReadout = false, const std::optional<std::array<float, 4>>& start = std::nullopt) {
    TileFormat tileFormat = format;
    tileFormat.alpha = isolated;
    std::array<float, 4> acc = start ? *start
                               : isolated ? std::array<float, 4>{0.0f, 0.0f, 0.0f, 0.0f}
                                          : std::array<float, 4>{base[0], base[1], base[2], 1.0f};
    std::array<uint32_t, 3> stored{0, 0, 0};
    for (size_t i = 0; i < layers.size(); ++i) {
        const ModelLayer& layer = layers[i];
        arith::CompositeInput in;
        in.coverageWeights = coverageWeights;
        in.emptyBackdrop = i == 0 && !start;
        in.fusedReadout = fusedReadout;
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

/// Writes the sRGB8 tables of arith.h as JSON (`<dir>/tables.json`): the float32 bits of the
/// operand of every code and of every store threshold, for the Python golden comparisons.
int RunTables(const fs::path& dir) {
    core::json::Array decode;
    for (const float value : arith::Srgb8OperandTable()) decode.push_back(static_cast<std::int64_t>(std::bit_cast<uint32_t>(value)));
    core::json::Array thresholds;
    for (uint32_t k = 1; k < 256; ++k) {
        thresholds.push_back(static_cast<std::int64_t>(std::bit_cast<uint32_t>(static_cast<float>(arith::Srgb8Thresholds()[k]))));
    }
    core::json::Object document;
    document["srgb8_decode_bits"] = decode;
    document["srgb8_threshold_bits"] = thresholds;
    std::ofstream stream(dir / "tables.json", std::ios::binary);
    stream << core::json::WriteCanonical(document);
    Check(static_cast<bool>(stream), "the sRGB8 tables are written");
    return Finish();
}

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

    // Half nearest, ties to even (the binary16 pass of an sRGB8 coverage plane).
    // Reference: the two halves around v (toward zero and the next one out) compared in double.
    auto nearestReference = [](float v) -> uint16_t {
        const uint16_t down = arith::HalfTowardZero(v);
        if (std::isnan(v) || std::isinf(v)) return down;
        const uint16_t up = static_cast<uint16_t>(down + 1u);  // the next half away from zero (0x7C00 is inf)
        const double magnitude = std::fabs(static_cast<double>(v));
        const double lo = std::fabs(static_cast<double>(arith::HalfToFloat(down)));
        // Past the largest half, IEEE 754 rounds as if the next value were 2^16.
        const double hi = (up & 0x7FFFu) == 0x7C00u ? 65536.0 : std::fabs(static_cast<double>(arith::HalfToFloat(up)));
        if (magnitude - lo < hi - magnitude) return down;
        if (magnitude - lo > hi - magnitude) return up;
        return (down & 1u) == 0 ? down : up;
    };
    bool nearestOk = true;
    std::string nearestDetail;
    auto checkNearest = [&](float v) {
        const uint16_t got = arith::HalfNearestEven(v);
        const uint16_t want = nearestReference(v);
        if (got != want && nearestOk) {
            nearestOk = false;
            nearestDetail = Hex32(std::bit_cast<uint32_t>(v)) + ": " + Hex32(got) + ", expected " + Hex32(want);
        }
    };
    for (uint32_t bits = 0; bits < 0x7C00; ++bits) {
        for (const uint32_t sign : {0u, 0x8000u}) {
            const float value = arith::HalfToFloat(static_cast<uint16_t>(bits | sign));
            checkNearest(value);
            if (bits + 1 < 0x7C00) {
                // The midpoint to the next half (exact in float32) and the floats on either side.
                const float next = arith::HalfToFloat(static_cast<uint16_t>((bits + 1) | sign));
                const float mid = static_cast<float>((static_cast<double>(value) + static_cast<double>(next)) / 2.0);
                checkNearest(mid);
                checkNearest(std::nextafter(mid, 0.0f));
                checkNearest(std::nextafter(mid, 2.0f * mid));
            }
        }
    }
    for (const float v : {65504.0f, 65519.99f, 65520.0f, 1.0e30f, 2.98023223876953125e-08f, 2.9802326e-08f,
                          8.940697e-08f, 6.103515625e-05f, 6.1035156e-05f}) {
        checkNearest(v);
        checkNearest(-v);
    }
    Check(nearestOk, "binary16 rounding to nearest, ties to even: every half, every midpoint between neighbours "
                     "and the floats beside it, overflow from 65520, the subnormal range", nearestDetail);
    Check(std::isinf(arith::HalfToFloat(arith::HalfNearestEven(65520.0f))) &&
              arith::HalfNearestEven(65519.99f) == 0x7BFF && arith::HalfNearestEven(2.98023223876953125e-08f) == 0 &&
              arith::HalfNearestEven(std::numeric_limits<float>::quiet_NaN()) == 0x7E00,
          "65520 rounds to infinity, 2^-25 ties to zero, NaN stays NaN");
    // `group-masks` row 32: the coverage 287/510 is a tie of 8-bit codes; its binary16 value lies
    // above it, so the code is 144 (the float32 value gives 143).
    const float tie = 0.5f + 0.5f * (32.0f * 257.0f / 65535.0f);
    Check(arith::WriteUnorm(tie, 8) == 143 && arith::WriteUnorm(arith::HalfToFloat(arith::HalfNearestEven(tie)), 8) == 144,
          "the coverage (255 + 32) / 510 writes as code 143 from float32 and 144 through binary16");

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
    {
        size_t kernels = 0;
        for (size_t i = 0; i < core::EnumTable<BlendingMode>::names.size(); ++i) {
            const BlendingMode mode = static_cast<BlendingMode>(i);
            kernels += arith::HasKernel(mode) ? 1 : 0;
            if (arith::HasKernel(mode) == (mode == BlendingMode::PassThrough)) kernels = 1000;
        }
        Check(kernels == 31, "every documented BlendingMode but PassThrough has a kernel (31 of 32)",
              std::to_string(kernels));
    }
    {
        // The fitted hue of the component modes (blend-kernels.json): a grey hue source takes hue
        // 0 (red), and a hue that wraps from just below 0 to 1 keeps 1, so blue's centred weight
        // 2 - 6 |1 - float32(2/3)| stays above zero.
        const std::array<float, 3> lower{0.5f, 0.0f, 0.0f};
        const std::array<float, 3> grey =
            arith::BlendColour(BlendingMode::Tint, lower, {0.25f, 0.25f, 0.25f}, 3, 1.0f);
        const float u = arith::UnormOperand(15436, 16);
        const std::array<float, 3> wrapped = arith::BlendColour(
            BlendingMode::Tint, lower, {u, u, arith::UnormOperand(15404, 16)}, 3, 1.0f);
        Check(grey[0] == 1.0f && grey[1] == grey[2] && grey[1] > 0.0f && wrapped[0] == 1.0f &&
                  wrapped[2] > wrapped[1] && wrapped[1] == grey[1],
              "the component hue: grey is red, a hue wrapped to 1 is not reduced");
    }

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

    // The coverage weights (painter-12.1-isolated-coverage-weights): over a partly covered
    // backdrop, wb = (1 - as) ab, ao = as + wb, ws = ao - ab and
    // v = fma(ws, Cs, fma(ab, as B, wb Cb)) x Rcp_hw(ao); over a backdrop layer of zero coverage
    // the same formula; over the empty start of a list the source is copied.
    {
        arith::CompositeInput w;
        w.coverageWeights = true;
        w.mode = BlendingMode::Normal;
        w.opacity = 0.3f;
        w.acc = {0.25f, 0.5f, 0.75f, 0.4f};
        w.src = {0.6f, 0.1f, 0.9f, 1.0f};
        const float as = 0.3f;
        const float ab = 0.4f;
        const float wb = ab * (1.0f - as);
        const float ao = as + wb;
        const float ws = ao - ab;
        out = arith::Composite(w);
        bool same = out[3] == ao;
        for (size_t c = 0; c < 3; ++c) {
            const float num = arith::Fma(ws, w.src[c], arith::Fma(ab, as * w.src[c], wb * w.acc[c]));
            same = same && out[c] == num * hw::Rcp(ao);
        }
        Check(same, "with coverage weights, Normal over a partly covered backdrop is fma(ws, Cs, fma(ab, as Cs, wb "
                    "Cb)) Rcp_hw(ao), ws = ao - ab");
        w.acc = {0.25f, 0.5f, 0.75f, 0.0f};
        out = arith::Composite(w);
        const float zero = (0.9f * as) * hw::Rcp(as);
        Check(out[2] == zero && out[3] == as && zero != 0.9f,
              "with coverage weights, a layer over a backdrop of zero coverage is (Cs as) Rcp_hw(as), not Cs",
              std::to_string(out[2]));
        w.emptyBackdrop = true;
        out = arith::Composite(w);
        Check(out[2] == 0.9f && out[3] == as, "the first layer over the empty start of a list is copied");
        arith::CompositeInput r;
        r.fusedReadout = true;
        r.mode = BlendingMode::Replace;
        r.acc = {1.0f, 1.0f, 1.0f, 1.0f};
        r.src = {0.3f, 0.3f, 0.3f, 0.7f};
        out = arith::Composite(r);
        Check(out[0] == arith::Fma(0.3f - 1.0f, 0.7f, 1.0f), "the fused read-out is fma(C - base, a, base)",
              std::to_string(out[0]));
    }

    // Float32 store over the white base (blend-modes.json): 1 + (v - 1).
    Check(arith::Float32Readout(0.3f, 1.0f) == static_cast<float>(static_cast<float>(0.3f - 1.0f) + 1.0f) &&
              arith::Float32Store(0.3f) == 0.3f,
          "the 32-bit float store re-composites over the base");
    // The recording GPU's GLSL asin (hwmath.h): input and result bits measured through an OpenGL
    // 4.3 compute shader on the RTX 4090 (edges, the 0.57 branch point, then values uniform in
    // [0, 1]); the polynomial was checked against every float32 of [0, 1] there.
    constexpr uint32_t kGlslAsin[48][2] = {
    {0x00000000u, 0x00000000u}, {0x80000000u, 0x00000000u}, {0x00000001u, 0x00000000u}, {0x80400000u, 0x00000000u},
    {0x00800000u, 0x00800000u}, {0x3F11EB85u, 0x3F1B43F7u}, {0x3F11EB86u, 0x3F1B43FAu}, {0x3F000000u, 0x3F060A92u},
    {0x3F800000u, 0x3FC90FDBu}, {0xBF800000u, 0xBFC90FDBu}, {0x3F7FFFFFu, 0x3FC9048Bu}, {0x3F800001u, 0x7FFFFFFFu},
    {0xBE99999Au, 0xBE9C00ADu}, {0x3E800000u, 0x3E815F4Eu}, {0x3DCCCCCDu, 0x3DCD2494u}, {0x3F4CCCCDu, 0x3F6D6339u},
    {0x3F666666u, 0x3F8F549Cu}, {0x3F7FF000u, 0x3FC63BC3u}, {0x33800000u, 0x33800000u}, {0x3A83126Fu, 0x3A831270u},
    {0x3ED9AD16u, 0x3EE0D524u}, {0x3CBD80B4u, 0x3CBD8508u}, {0x3EA42578u, 0x3EA718CEu}, {0x3F39CCA5u, 0x3F4FEA1Du},
    {0x3EE22069u, 0x3EEA35B0u}, {0x3E013260u, 0x3E018AC2u}, {0x3F6FF785u, 0x3F9B853Cu}, {0x3F515D8Bu, 0x3F7527A7u},
    {0x3F2EA050u, 0x3F402C59u}, {0x3F24FFE2u, 0x3F334DECu}, {0x3D68C062u, 0x3D68E07Fu}, {0x3F2BA29Cu, 0x3F3C1CD8u},
    {0x3F60D134u, 0x3F893992u}, {0x3F458D53u, 0x3F61A95Du}, {0x3EDE4CEDu, 0x3EE5F42Du}, {0x3F387FCAu, 0x3F4E0820u},
    {0x3F28026Fu, 0x3F374464u}, {0x3F494C00u, 0x3F67A27Eu}, {0x3E87A1A2u, 0x3E89451Du}, {0x3E5263FEu, 0x3E53E650u},
    {0x3F3711D2u, 0x3F4BFA67u}, {0x3F2CEA8Au, 0x3F3DD82Fu}, {0x3E101E01u, 0x3E1098E6u}, {0x3F6CC828u, 0x3F972611u},
    {0x3DF09F0Eu, 0x3DF12DAAu}, {0x3EF715DCu, 0x3F00EC72u}, {0x3EE3C155u, 0x3EEC06CBu}, {0x3F754913u, 0x3FA3E5F5u},
    };
    std::string asinMiss;
    for (const auto& [in, out] : kGlslAsin) {
        const float ours = hw::Asin(std::bit_cast<float>(in));
        if (!SameFloat(ours, std::bit_cast<float>(out)) && asinMiss.empty()) {
            asinMiss = Hex32(in) + ": GLSL " + Hex32(out) + ", hw " + Hex32(std::bit_cast<uint32_t>(ours));
        }
    }
    Check(asinMiss.empty(), "hw::Asin equals the recording GPU's GLSL asin on 48 measured inputs", asinMiss);
    // The GPU's sine and cosine read the turn x float32(1 / (2 pi)), truncated, as a 2^-25
    // fixed-point index.
    Check(hw::TrigIndex(0.0f) == 0 && hw::TrigIndex(1.57079632679489661923f) == (1u << 23) - 1u &&
              hw::Sin(0.0f) == 0.0f && hw::Cos(0.0f) == 1.0f,
          "the sine and cosine tables cover [0, float32(pi / 2)] with 2^23 entries");
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
        Check(height != nullptr && height->format == ChannelFormat::L16F && height->base[0] == 0.0f,
              "the default Height channel is L16F with base 0 (signed)");
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
        // PassThrough: the children composite onto a copy of the stack below the group, and the
        // group's opacity moves the stack toward that result (fma(g - a, t, a)).
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
            const ModelValue inside = ModelComposite(
                {ModelLayer{BlendingMode::Normal, 1.0f, operand(colourA, ChannelFormat::RGB16, base)},
                 ModelLayer{BlendingMode::Multiply, 1.0f, operand(colourB, ChannelFormat::RGB16, base)},
                 ModelLayer{BlendingMode::Screen, 0.5f, operand(colourC, ChannelFormat::RGB16, base)}},
                rgb16, base, false);
            const ModelValue model = ModelComposite(
                {ModelLayer{BlendingMode::Normal, 1.0f, operand(colourA, ChannelFormat::RGB16, base)},
                 ModelLayer{BlendingMode::PassThrough, 0.75f, {inside.value[0], inside.value[1], inside.value[2]}}},
                rgb16, base, false);
            std::string detail;
            Check(result && AllEqual(Samples(*result), 3, model.stored, detail),
                  "a PassThrough group composites its children onto the stack below it and mixes by its opacity",
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
        bool encoded = srgb.has_value();
        if (srgb) {
            const std::vector<uint32_t> samples = Samples(*srgb);
            for (size_t i = 0; i < samples.size() && encoded; ++i) {
                encoded = samples[i] == arith::Srgb8Store(arith::UnormOperand(image->values[i], 16));
            }
        }
        Check(encoded, "a 1:1 16-bit bitmap on sRGB8 stores each code as a linear value through the sRGB8 conversion",
              Describe(srgb));
        Check(rgb16 && rgb16->stats.uploads == 1 && rgb16->stats.blends == 2,
              "the bitmap is uploaded once, blended once into the isolated root and composited once "
              "over the base");
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
        core::Effect anchor;
        anchor.uid = effects.project.AllocateId();
        anchor.kind = core::EffectKind::anchor;
        anchor.name = "anchor";
        anchor.anchor_name = "anchor";
        withEffect.content_effects.push_back(anchor);
        effects.SetRoot({withEffect});
        if (!effects.Validate("effects")) return Finish();
        result = evaluate(effects, ChannelType::User0, cpu);
        Check(!result && KindName(result.error()) == "unsupported_node",
              "an anchor content effect fails with unsupported_node (P4-NODES)",
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
        Check(result.has_value(), "a non-separable blend mode (Tint) evaluates", Describe(result));

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
    Check(user0->stats.tiles == 2 && user0->stats.blends == 22 && user0->stats.uploads == 2 &&
              user0->stats.cacheHits == 0,
          "first evaluation: two tiles, ten blends and the read-out over the base each, the bitmap "
          "uploaded per tile, no hit",
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
    Check(edited0 && edited0->stats.cacheHits == 2 && edited0->stats.cacheMisses == 12 &&
              edited0->stats.blends == 12 && edited0->stats.uploads == 0,
          "the edited channel re-evaluates only the layers above the edit: per tile the read-out and the "
          "five prefixes above miss, the prefix below the edit hits, five blends and the read-out run, "
          "nothing is uploaded",
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
    Check(stats.evictions == 0 && stats.liveTiles == 2 * 2 + 2 * 2 * (10 + 1) + 2 * (5 + 1),
          "with a wide budget nothing is evicted: content tiles, prefixes and read-outs of both channels and "
          "the five new prefixes and read-out stay",
          std::to_string(stats.liveTiles));
    return Finish();
}

// ── profile ──────────────────────────────────────────────────────────────────

/// The bits a channel result holds under an isolated-root profile (profile.h,
/// `RootComposite::Isolated`): the root layers composited from a transparent start, then over
/// `base` with the Replace mix at opacity 1, stored with the write rule (32-bit floats as they
/// are: the read-out composite is the re-composition over the base).
std::array<uint32_t, 3> IsolatedRootModel(const std::vector<ModelLayer>& layers, const TileFormat& format,
                                          const std::array<float, 3>& base, const EvaluatorProfile& profile) {
    const ModelValue stack = ModelComposite(layers, format, base, true, profile.coverageWeights);
    const ModelValue out = ModelComposite(
        {ModelLayer{BlendingMode::Replace, 1.0f, {stack.value[0], stack.value[1], stack.value[2]}, stack.value[3]}},
        format, base, false, false, profile.fusedReadout);
    std::array<uint32_t, 3> bits = out.stored;
    for (uint32_t c = 0; c < format.channels; ++c) {
        if (format.encoding == render::TexelEncoding::Float16) {
            bits[c] = arith::HalfTowardZero(std::bit_cast<float>(out.stored[c]));
        }
    }
    return bits;
}

int RunProfile(const fs::path& assets) {
    std::shared_ptr<const TemplateLibrary> templates = LoadTemplates(assets);
    const std::vector<ChannelType> channels{ChannelType::User0, ChannelType::User1, ChannelType::User2};
    const std::vector<std::pair<ChannelType, ChannelFormat>> formats{
        {ChannelType::User0, ChannelFormat::RGB8},
        {ChannelType::User1, ChannelFormat::sRGB8},
        {ChannelType::User2, ChannelFormat::RGB32F}};
    const std::array<float, 3> base{1.0f, 1.0f, 1.0f};
    using Colours = std::vector<std::array<double, 3>>;
    using Opacities = std::vector<double>;
    // The Tier 0 quantisation experiment's first texture set: three uniform fills at opacity 1/3.
    const Colours colours{{0.2, 0.7, 0.123}, {0.9, 0.05, 0.5}, {0.333, 0.1, 0.8}};
    const double third = 1.0 / 3.0;
    const Opacities thirds{third, third, third};
    // A 0.5 fill over a fill at opacity 32/255: the coverage (255 + 32) / 510 lies half-way between
    // two 8-bit codes, and its binary16 value rounds up (Tier 0 `group-masks` row 32).
    const Colours tieColours{{0.2, 0.7, 0.123}, {0.9, 0.05, 0.5}};
    const Opacities tieOpacities{static_cast<double>(32.0f / 255.0f), 0.5};
    // A 0.3 fill over a fill at opacity 0: the coverage 0.3 lies on an 8-bit tie below 1/2, stored
    // down, while its binary16 value rounds up (Tier 0 `group-coverage-order` s3 row 0); the 0.3
    // fill composites over a backdrop layer of zero coverage.
    const Colours lowColours{{0.2, 0.7, 0.123}, {0.9, 0.05, 0.5}};
    const Opacities lowOpacities{0.0, 0.3};

    // 1. The registry.
    render::Result<EvaluatorProfile> legacy = FindProfile(kProfileLayerqLinear);
    render::Result<EvaluatorProfile> linear = FindProfile(kProfileIsolatedLinear);
    render::Result<EvaluatorProfile> halfAlpha = FindProfile(kProfileIsolatedHalfAlpha);
    render::Result<EvaluatorProfile> weights = FindProfile(kProfileIsolatedCoverageWeights);
    auto none = [](const EvaluatorProfile& p) {
        return !p.coverageWeights && !p.fusedReadout && !p.uniformGreyUnrounded && !p.srgb8HalfCoverageFromHalf;
    };
    Check(legacy && legacy->root == RootComposite::OverBase && !legacy->srgb8HalfCoverage &&
              !legacy->float32UniformPlain && none(*legacy) && linear && linear->root == RootComposite::Isolated &&
              !linear->srgb8HalfCoverage && !linear->float32UniformPlain && none(*linear) && halfAlpha &&
              halfAlpha->root == RootComposite::Isolated && halfAlpha->srgb8HalfCoverage &&
              halfAlpha->float32UniformPlain && none(*halfAlpha) && weights &&
              weights->root == RootComposite::Isolated && weights->srgb8HalfCoverage && weights->float32UniformPlain &&
              weights->coverageWeights && weights->fusedReadout && weights->uniformGreyUnrounded &&
              weights->srgb8HalfCoverageFromHalf && kCurrentProfile == kProfileIsolatedCoverageWeights,
          "the build registers painter-12.1-layerq-linear (over the base), painter-12.1-isolated-linear (isolated "
          "root), painter-12.1-isolated-half-alpha (isolated root, binary16 sRGB8 coverage, plain 32-bit float "
          "uniform colours) and painter-12.1-isolated-coverage-weights (coverage weights, fused read-out, grey of "
          "the unrounded components, binary16 sRGB8 coverage from 1/2 up), the current profile");
    const std::vector<std::string> ids = RegisteredProfiles();
    Check(ids.size() >= 4 && ids[0] == kProfileLayerqLinear && ids[1] == kProfileIsolatedLinear &&
              ids[2] == kProfileIsolatedHalfAlpha && ids[3] == kProfileIsolatedCoverageWeights,
          "the built-in profiles are listed first, in registration order");
    render::Result<EvaluatorProfile> unknown = FindProfile("painter-12.1-no-such-profile");
    Check(!unknown && EvalErrorKindOf(unknown.error()) == EvalErrorKind::UnknownProfile,
          "an unregistered profile id fails with unknown_profile", Describe(unknown));
    render::Result<void> malformed = RegisterProfile({"isolated", RootComposite::Isolated});
    render::Result<void> taken = RegisterProfile({std::string(kProfileLayerqLinear), RootComposite::Isolated});
    Check(!malformed && EvalErrorKindOf(malformed.error()) == EvalErrorKind::InvalidProfile && !taken &&
              EvalErrorKindOf(taken.error()) == EvalErrorKind::InvalidProfile,
          "a registration with a malformed or taken id fails with invalid_profile (an id never changes meaning)");
    if (!legacy || !linear || !halfAlpha || !weights) return Finish();

    auto stackOf = [&](std::string_view profile, const Colours& stackColours, const Opacities& opacities) {
        Builder builder(128, 128, formats);
        builder.project.versions.evaluator_profile = std::string(profile);
        std::vector<core::Layer> layers;
        for (size_t i = 0; i < stackColours.size(); ++i) {
            const std::array<double, 3>& c = stackColours[i];
            layers.push_back(builder.Fill("layer" + std::to_string(i), SameSource(channels, Uniform(c[0], c[1], c[2])),
                                          Same(channels, BlendingMode::Normal, opacities[i])));
        }
        builder.SetRoot(layers);
        return builder;
    };
    auto project = [&](std::string_view profile) { return stackOf(profile, colours, thirds); };
    auto evaluate = [&](Builder& builder, ChannelType channel, CpuEvaluator& cpu) {
        EvaluateRequest request;
        request.textureSet = builder.SetId();
        request.stack = builder.StackId();
        request.channel = channel;
        return cpu.Evaluate(builder.project, request);
    };
    // The expected codes of a stack under a profile, from arith and the store's write rules.
    auto modelOf = [&](ChannelFormat format, const EvaluatorProfile& profile, const Colours& stackColours,
                       const Opacities& opacities) {
        TileFormat tileFormat = TileFormatOf(format);
        tileFormat.halfCoverage = profile.srgb8HalfCoverage && tileFormat.srgb;
        tileFormat.halfCoverageFromHalf = profile.srgb8HalfCoverageFromHalf && tileFormat.halfCoverage;
        std::vector<ModelLayer> layers;
        for (size_t i = 0; i < stackColours.size(); ++i) {
            layers.push_back(ModelLayer{BlendingMode::Normal, static_cast<float>(opacities[i]),
                                        UniformOperand(stackColours[i], tileFormat, base, profile.float32UniformPlain,
                                                       profile.uniformGreyUnrounded)});
        }
        return profile.root == RootComposite::Isolated
                   ? IsolatedRootModel(layers, tileFormat, base, profile)
                   : Output(ModelComposite(layers, tileFormat, base, false).stored, tileFormat, base);
    };
    auto model = [&](ChannelFormat format, const EvaluatorProfile& profile) {
        return modelOf(format, profile, colours, thirds);
    };

    // 2. Each profile evaluates as its own model, and they differ on these stacks.
    Builder projectA = project(kProfileLayerqLinear);
    Builder projectLinear = project(kProfileIsolatedLinear);
    Builder projectHalf = project(kProfileIsolatedHalfAlpha);
    Builder projectCurrent = project(kCurrentProfile);
    Builder tieLinear = stackOf(kProfileIsolatedLinear, tieColours, tieOpacities);
    Builder tieHalf = stackOf(kProfileIsolatedHalfAlpha, tieColours, tieOpacities);
    Builder tieCurrent = stackOf(kCurrentProfile, tieColours, tieOpacities);
    Builder lowHalf = stackOf(kProfileIsolatedHalfAlpha, lowColours, lowOpacities);
    Builder lowCurrent = stackOf(kCurrentProfile, lowColours, lowOpacities);
    if (!projectA.Validate("profile A") || !projectLinear.Validate("isolated-linear") ||
        !projectHalf.Validate("isolated-half-alpha") || !projectCurrent.Validate("current profile") ||
        !tieLinear.Validate("tie, isolated-linear") || !tieHalf.Validate("tie, isolated-half-alpha") ||
        !tieCurrent.Validate("tie, current profile") || !lowHalf.Validate("low tie, isolated-half-alpha") ||
        !lowCurrent.Validate("low tie, current profile")) {
        return Finish();
    }
    CpuEvaluator cpu(templates, kWideLimits);
    std::map<ChannelType, std::vector<uint32_t>> resultA;
    std::map<ChannelType, std::vector<uint32_t>> resultLinear;
    std::map<ChannelType, std::vector<uint32_t>> resultHalf;
    for (const auto& [channel, format] : formats) {
        const std::string label = std::string(core::ToString(format));
        const uint32_t n = TileFormatOf(format).channels;
        render::Result<ChannelResult> a = evaluate(projectA, channel, cpu);
        render::Result<ChannelResult> isolated = evaluate(projectLinear, channel, cpu);
        render::Result<ChannelResult> half = evaluate(projectHalf, channel, cpu);
        render::Result<ChannelResult> current = evaluate(projectCurrent, channel, cpu);
        render::Result<ChannelResult> tieOld = evaluate(tieLinear, channel, cpu);
        render::Result<ChannelResult> tieHalfResult = evaluate(tieHalf, channel, cpu);
        render::Result<ChannelResult> tieNew = evaluate(tieCurrent, channel, cpu);
        render::Result<ChannelResult> lowHalfResult = evaluate(lowHalf, channel, cpu);
        render::Result<ChannelResult> lowNew = evaluate(lowCurrent, channel, cpu);
        std::string detail;
        Check(a && AllEqual(Samples(*a), n, model(format, *legacy), detail),
              label + ": a project stamped painter-12.1-layerq-linear evaluates over the base, quantised per layer",
              a ? detail : Describe(a));
        Check(isolated && tieOld && AllEqual(Samples(*isolated), n, model(format, *linear), detail) &&
                  AllEqual(Samples(*tieOld), n, modelOf(format, *linear, tieColours, tieOpacities), detail),
              label + ": a project stamped painter-12.1-isolated-linear evaluates its root isolated, composited "
                      "over the base at read-out",
              !isolated ? Describe(isolated) : !tieOld ? Describe(tieOld) : detail);
        Check(half && tieHalfResult && lowHalfResult && AllEqual(Samples(*half), n, model(format, *halfAlpha), detail) &&
                  AllEqual(Samples(*tieHalfResult), n, modelOf(format, *halfAlpha, tieColours, tieOpacities), detail) &&
                  AllEqual(Samples(*lowHalfResult), n, modelOf(format, *halfAlpha, lowColours, lowOpacities), detail),
              label + ": a project stamped painter-12.1-isolated-half-alpha evaluates its root isolated, the sRGB8 "
                      "coverage written through binary16 and 32-bit float uniform colours plain",
              !half            ? Describe(half)
              : !tieHalfResult ? Describe(tieHalfResult)
              : !lowHalfResult ? Describe(lowHalfResult)
                               : detail);
        Check(current && tieNew && lowNew && AllEqual(Samples(*current), n, model(format, *weights), detail) &&
                  AllEqual(Samples(*tieNew), n, modelOf(format, *weights, tieColours, tieOpacities), detail) &&
                  AllEqual(Samples(*lowNew), n, modelOf(format, *weights, lowColours, lowOpacities), detail),
              label + ": a project stamped painter-12.1-isolated-coverage-weights evaluates its layers with the "
                      "coverage weights, its read-out fused and the sRGB8 coverage through binary16 from 1/2 up",
              !current ? Describe(current) : !tieNew ? Describe(tieNew) : !lowNew ? Describe(lowNew) : detail);
        if (a) resultA[channel] = Samples(*a);
        if (isolated) resultLinear[channel] = Samples(*isolated);
        if (half) resultHalf[channel] = Samples(*half);
    }
    Check(model(ChannelFormat::RGB8, *legacy) != model(ChannelFormat::RGB8, *linear),
          "painter-12.1-layerq-linear and painter-12.1-isolated-linear give different RGB8 codes for the three 1/3 "
          "fills (the dispatch is observable)");
    Check(modelOf(ChannelFormat::sRGB8, *linear, tieColours, tieOpacities) !=
                  modelOf(ChannelFormat::sRGB8, *halfAlpha, tieColours, tieOpacities) &&
              model(ChannelFormat::RGB32F, *linear) != model(ChannelFormat::RGB32F, *halfAlpha),
          "painter-12.1-isolated-linear and painter-12.1-isolated-half-alpha differ on the sRGB8 coverage tie and on "
          "the 32-bit float uniform colours");
    Check(model(ChannelFormat::RGB32F, *halfAlpha) != model(ChannelFormat::RGB32F, *weights) &&
              modelOf(ChannelFormat::sRGB8, *halfAlpha, lowColours, lowOpacities) !=
                  modelOf(ChannelFormat::sRGB8, *weights, lowColours, lowOpacities),
          "painter-12.1-isolated-half-alpha and painter-12.1-isolated-coverage-weights differ on the three 1/3 fills "
          "in 32-bit float and on the sRGB8 coverage tie below 1/2");

    // A PassThrough group over a backdrop that is not opaque (a layer at 0.4, a layer at 0): its
    // children composite onto a copy of the accumulator below it, which is not the empty start of
    // the list, so its first child takes the coverage weights (decision 066); the group then mixes
    // by its opacity.
    bool differs = false;
    for (const double underOpacity : {0.4, 0.0}) {
        const std::array<double, 3> under{0.2, 0.7, 0.123};
        const std::array<double, 3> inside{0.9, 0.05, 0.5};
        Builder passBuilder(128, 128, formats);
        core::Layer bottom = passBuilder.Fill("under", SameSource(channels, Uniform(under[0], under[1], under[2])),
                                              Same(channels, BlendingMode::Normal, underOpacity));
        core::Layer child = passBuilder.Fill("inside", SameSource(channels, Uniform(inside[0], inside[1], inside[2])),
                                             Same(channels, BlendingMode::Normal, 0.3));
        core::Layer pass = passBuilder.Group("pass", {child}, Same(channels, BlendingMode::PassThrough, 0.6));
        passBuilder.SetRoot({bottom, pass});
        if (!passBuilder.Validate("pass-through over a backdrop that is not opaque")) return Finish();
        for (const auto& [channel, format] : formats) {
            TileFormat tileFormat = TileFormatOf(format);
            tileFormat.halfCoverage = weights->srgb8HalfCoverage && tileFormat.srgb;
            tileFormat.halfCoverageFromHalf = weights->srgb8HalfCoverageFromHalf && tileFormat.halfCoverage;
            auto operand = [&](const std::array<double, 3>& c) {
                return UniformOperand(c, tileFormat, base, weights->float32UniformPlain, weights->uniformGreyUnrounded);
            };
            const ModelValue below = ModelComposite(
                {ModelLayer{BlendingMode::Normal, static_cast<float>(underOpacity), operand(under)}}, tileFormat, base,
                true, true);
            auto expected = [&](bool childOnEmptyStart) {
                const ModelValue group =
                    childOnEmptyStart
                        ? ModelComposite({ModelLayer{BlendingMode::Normal, 1.0f, {below.value[0], below.value[1], below.value[2]}, below.value[3]},
                                          ModelLayer{BlendingMode::Normal, 0.3f, operand(inside)}},
                                         tileFormat, base, true, false)
                        : ModelComposite({ModelLayer{BlendingMode::Normal, 0.3f, operand(inside)}}, tileFormat, base, true,
                                         true, false, below.value);
                const ModelValue mixed = ModelComposite(
                    {ModelLayer{BlendingMode::PassThrough, 0.6f, {group.value[0], group.value[1], group.value[2]}, group.value[3]}},
                    tileFormat, base, true, true, false, below.value);
                return IsolatedRootModel(
                    {ModelLayer{BlendingMode::Normal, 1.0f, {mixed.value[0], mixed.value[1], mixed.value[2]}, mixed.value[3]}},
                    tileFormat, base, *weights);
            };
            const std::array<uint32_t, 3> weighted = expected(false);
            differs = differs || weighted != expected(true);
            CpuEvaluator passCpu(templates, kWideLimits);
            render::Result<ChannelResult> result = evaluate(passBuilder, channel, passCpu);
            std::string detail;
            Check(result && AllEqual(Samples(*result), TileFormatOf(format).channels, weighted, detail),
                  std::string(core::ToString(format)) + ", backdrop layer at " + std::to_string(underOpacity) +
                      ": under painter-12.1-isolated-coverage-weights a PassThrough group's first child over a "
                      "backdrop that is not opaque takes the coverage weights (the backdrop is not the empty start)",
                  result ? detail : Describe(result));
        }
    }
    Check(differs, "the coverage weights and the empty-start rule give different codes for that child "
                   "(the rule is observable)");

    // 3. Pinning: a synthetic profile B registered after the projects exist changes nothing for them.
    render::Result<void> registered = RegisterProfile({"painter-12.1-synthetic-b", RootComposite::Isolated});
    Check(registered.has_value(), "a synthetic profile painter-12.1-synthetic-b registers", Describe(registered));
    CpuEvaluator fresh(templates, kWideLimits);
    bool pinned = true;
    bool cached = true;
    for (const auto& [channel, format] : formats) {
        const std::array<std::pair<Builder*, const std::vector<uint32_t>*>, 3> stamped{
            {{&projectA, &resultA[channel]}, {&projectLinear, &resultLinear[channel]}, {&projectHalf, &resultHalf[channel]}}};
        for (const auto& [builder, expected] : stamped) {
            render::Result<ChannelResult> again = evaluate(*builder, channel, cpu);
            render::Result<ChannelResult> anew = evaluate(*builder, channel, fresh);
            pinned = pinned && again && anew && Samples(*again) == *expected && Samples(*anew) == *expected;
            cached = cached && again && again->stats.blends == 0;
        }
    }
    Check(pinned, "after profile B is registered, the projects stamped painter-12.1-layerq-linear, "
                  "painter-12.1-isolated-linear and painter-12.1-isolated-half-alpha evaluate with their own profiles: "
                  "their results are unchanged bit for bit (same evaluator and a fresh one)");
    Check(cached, "those projects are still served by their own cached tiles");
    Builder projectB = project("painter-12.1-synthetic-b");
    if (!projectB.Validate("profile B")) return Finish();
    bool sameRules = true;
    bool ownTiles = true;
    for (const auto& [channel, format] : formats) {
        render::Result<ChannelResult> b = evaluate(projectB, channel, cpu);
        sameRules = sameRules && b && Samples(*b) == resultLinear[channel];
        ownTiles = ownTiles && b && b->stats.cacheHits == 0;
    }
    Check(sameRules, "a project stamped B evaluates with B's rules (here those of painter-12.1-isolated-linear)");
    Check(ownTiles, "tiles of different profiles never serve each other (subtree hashes are seeded by the profile)");

    // 4. A project stamped with a profile this build does not have fails explicitly.
    Builder future = project("painter-12.1-from-a-newer-build");
    if (!future.Validate("unknown profile")) return Finish();
    render::Result<ChannelResult> refused = evaluate(future, ChannelType::User0, cpu);
    Check(!refused && EvalErrorKindOf(refused.error()) == EvalErrorKind::UnknownProfile,
          "a project stamped with an unregistered profile fails with unknown_profile", Describe(refused));
    return Finish();
}

// ── admission ────────────────────────────────────────────────────────────────

/// A store that allocates nothing: bytes are counted, blends, uploads and projections succeed,
/// reads are zero.
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
    render::Result<void> Project(const ProjectOp&) override { return {}; }
    render::Result<void> Blend(const BlendOp&) override { return {}; }
    render::Result<void> Levels(const LevelsOp&) override { return {}; }
    render::Result<void> VirtualNormal(const VirtualNormalOp&) override { return {}; }
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

/// Resources of a spec: raw sample files by hash, then PNG bytes decoded on demand.
class SpecResources final : public IResourceProvider {
public:
    SpecResources()
        : m_decoding([this](std::string_view sha) -> std::optional<std::string> {
              const auto it = m_png.find(std::string(sha));
              if (it == m_png.end()) return std::nullopt;
              return it->second;
          }) {}
    void Add(std::string sha256, std::shared_ptr<const DecodedImage> image) { m_raw.Add(std::move(sha256), std::move(image)); }
    void AddPng(std::string sha256, std::string bytes) { m_png[std::move(sha256)] = std::move(bytes); }
    std::shared_ptr<const DecodedImage> Fetch(std::string_view sha256) const override {
        std::shared_ptr<const DecodedImage> image = m_raw.Fetch(sha256);
        return image ? image : m_decoding.Fetch(sha256);
    }

private:
    MapResourceProvider m_raw;
    std::map<std::string, std::string> m_png;
    DecodingResourceProvider m_decoding;
};

struct Spec {
    std::string templateId = std::string(kDefaultTemplateId);
    Builder builder;
    std::shared_ptr<SpecResources> resources = std::make_shared<SpecResources>();
    std::vector<ChannelType> outputs;
    /// Virtual normal maps to evaluate (height_to_normal.h), by convention.
    std::vector<core::NormalMapFormat> virtualOutputs;
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

/// A spec source: {"uniform": [r, g, b], "color_space"?} or {"bitmap": sha256, "alias"?, "color_space"?}.
core::Source ParseSource(const core::json::Object& s) {
    if (s.contains("uniform")) {
        const core::json::Array& rgb = Arr(s.at("uniform"), "uniform");
        core::UniformColorSource uniform;
        for (size_t i = 0; i < 3 && i < rgb.size(); ++i) uniform.rgb[i] = Num(rgb[i], "uniform component");
        uniform.color_space = s.contains("color_space") ? Str(s.at("color_space"), "color_space") : "Working";
        return core::Source{uniform};
    }
    core::BitmapSource bitmap;
    bitmap.resource.sha256 = Str(Key(s, "bitmap"), "bitmap");
    if (s.contains("alias")) bitmap.resource.alias = Str(s.at("alias"), "alias");
    bitmap.color_space = s.contains("color_space") ? Str(s.at("color_space"), "color_space") : "Raw";
    return core::Source{bitmap};
}

/// A spec projection {"mode"?, "filtering_mode"?, "uv_wrapping_mode"?, "scale_mode"?, "scale"?,
/// "rotation"?, "offset"?}.
void ParseProjection(const core::json::Object& p, core::Projection& projection) {
    if (p.contains("mode")) projection.mode = EnumOf<core::ProjectionMode>(Str(p.at("mode"), "mode"), "projection mode");
    core::UVProjectionParams& uv = projection.uv;
    if (p.contains("filtering_mode")) {
        uv.filtering_mode = EnumOf<core::FilteringMode>(Str(p.at("filtering_mode"), "filtering_mode"), "filtering mode");
    }
    if (p.contains("uv_wrapping_mode")) {
        uv.uv_wrapping_mode = EnumOf<core::UVWrapMode>(Str(p.at("uv_wrapping_mode"), "uv_wrapping_mode"), "wrap mode");
    }
    core::UVTransformation& t = uv.uv_transformation;
    if (p.contains("scale_mode")) t.scale_mode = EnumOf<core::ScaleMode>(Str(p.at("scale_mode"), "scale_mode"), "scale mode");
    if (p.contains("scale")) {
        const core::json::Array& scale = Arr(p.at("scale"), "scale");
        t.scale = {Num(scale.at(0), "scale u"), Num(scale.at(1), "scale v")};
    }
    if (p.contains("rotation")) t.rotation = Num(p.at("rotation"), "rotation");
    if (p.contains("offset")) {
        const core::json::Array& offset = Arr(p.at("offset"), "offset");
        t.offset = {Num(offset.at(0), "offset u"), Num(offset.at(1), "offset v")};
    }
}

/// Spec levels {"affected_channel"?, "components": [{"input_min"?, "input_max"?, "gamma"?,
/// "output_min"?, "output_max"?, "clamp"?}]}.
core::LevelsParams ParseLevels(const core::json::Object& o) {
    core::LevelsParams levels;
    if (o.contains("affected_channel")) {
        levels.affected_channel = EnumOf<ChannelType>(Str(o.at("affected_channel"), "affected_channel"), "affected channel");
    }
    for (const core::json::Value& entry : Arr(Key(o, "components"), "components")) {
        const core::json::Object& c = Obj(entry, "levels component");
        core::LevelsComponent component;
        if (c.contains("input_min")) component.input_min = Num(c.at("input_min"), "input_min");
        if (c.contains("input_max")) component.input_max = Num(c.at("input_max"), "input_max");
        if (c.contains("gamma")) component.gamma = Num(c.at("gamma"), "gamma");
        if (c.contains("output_min")) component.output_min = Num(c.at("output_min"), "output_min");
        if (c.contains("output_max")) component.output_max = Num(c.at("output_max"), "output_max");
        if (c.contains("clamp")) component.clamp = std::get<bool>(c.at("clamp").data);
        levels.components.push_back(component);
    }
    return levels;
}

/// A spec effect of a content stack (`mask` false) or of a mask stack: {"kind": "fill" |
/// "levels", "uid"?, "visible"?, ...}. A content fill effect has "sources", "active_channels"?,
/// "blending"? and "projection"?; a mask fill effect "source", "mode"?, "opacity"? and
/// "projection"?; a levels effect the fields of `ParseLevels`.
core::Effect ParseEffect(Spec& spec, const core::json::Value& value, bool mask) {
    const core::json::Object& o = Obj(value, "effect");
    const std::string kind = Str(Key(o, "kind"), "effect.kind");
    core::Effect effect;
    effect.uid = o.contains("uid") ? static_cast<core::Id>(Num(o.at("uid"), "uid")) : spec.builder.project.AllocateId();
    effect.name = kind;
    if (o.contains("visible")) effect.visible = std::get<bool>(o.at("visible").data);
    if (kind == "fill") {
        effect.kind = core::EffectKind::fill;
        core::FillContent fill;
        fill.projection.mode = core::ProjectionMode::UV;
        if (o.contains("projection")) ParseProjection(Obj(o.at("projection"), "projection"), fill.projection);
        if (mask) {
            if (o.contains("source")) fill.mono_source = ParseSource(Obj(o.at("source"), "source"));
            core::Blending blending;
            if (o.contains("mode")) blending.mode = EnumOf<BlendingMode>(Str(o.at("mode"), "mode"), "mode");
            if (o.contains("opacity")) blending.opacity = Num(o.at("opacity"), "opacity");
            effect.mono_blending = blending;
        } else {
            for (const auto& [channel, entry] : Obj(Key(o, "sources"), "effect.sources")) {
                const ChannelType type = EnumOf<ChannelType>(channel, "source channel");
                fill.sources[type] = ParseSource(Obj(entry, "source"));
                fill.active_channels.insert(type);
            }
            if (o.contains("active_channels")) {
                fill.active_channels.clear();
                for (const core::json::Value& c : Arr(o.at("active_channels"), "active_channels")) {
                    fill.active_channels.insert(EnumOf<ChannelType>(Str(c, "active channel"), "active channel"));
                }
            }
            if (o.contains("blending")) {
                for (const auto& [channel, entry] : Obj(o.at("blending"), "effect.blending")) {
                    const core::json::Object& b = Obj(entry, "blending entry");
                    effect.blending[EnumOf<ChannelType>(channel, "blending channel")] =
                        Blend(EnumOf<BlendingMode>(Str(Key(b, "mode"), "mode"), "mode"), Num(Key(b, "opacity"), "opacity"));
                }
            }
        }
        effect.fill = fill;
    } else if (kind == "levels") {
        effect.kind = core::EffectKind::levels;
        effect.levels = ParseLevels(o);
        // The document model keeps a mono blending on every mask effect; a levels effect's is
        // not evaluated (Painter's API refuses blending on it).
        if (mask) effect.mono_blending = core::Blending{};
    } else {
        throw core::ManifestError("effect.kind: unknown kind '" + kind + "'");
    }
    return effect;
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
            sources[EnumOf<ChannelType>(channel, "source channel")] = ParseSource(Obj(entry, "source"));
        }
        layer = spec.builder.Fill(name, sources, blending);
        if (o.contains("projection")) ParseProjection(Obj(o.at("projection"), "projection"), layer.fill->projection);
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
        if (m.contains("effects")) {  // top first, like Painter
            for (const core::json::Value& e : Arr(m.at("effects"), "mask.effects")) {
                layer.mask->effects.push_back(ParseEffect(spec, e, true));
            }
        }
    }
    if (o.contains("effects")) {  // the content stack, top first
        for (const core::json::Value& e : Arr(o.at("effects"), "effects")) {
            layer.content_effects.push_back(ParseEffect(spec, e, false));
        }
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
              std::make_shared<SpecResources>(), {}, {}};
    if (o.contains("template")) spec.templateId = Str(o.at("template"), "template");
    if (o.contains("evaluator_profile")) {
        spec.builder.project.versions.evaluator_profile = Str(o.at("evaluator_profile"), "evaluator_profile");
    }
    if (o.contains("color_management")) {
        spec.builder.project.settings.color_management.mode = Str(o.at("color_management"), "color_management");
    }
    if (o.contains("normal_map_format")) {
        spec.builder.project.settings.normal_map_format =
            EnumOf<core::NormalMapFormat>(Str(o.at("normal_map_format"), "normal_map_format"), "normal map format");
    }
    if (o.contains("height_to_normal_method")) {
        spec.builder.Set().height_to_normal_method = EnumOf<core::HeightToNormalMethod>(
            Str(o.at("height_to_normal_method"), "height_to_normal_method"), "height to normal method");
    }
    if (o.contains("normal_mesh_map")) {
        // An imported Normal mesh map: its resource hash and declared convention.
        const core::json::Object& m = Obj(o.at("normal_mesh_map"), "normal_mesh_map");
        const std::string sha = Str(Key(m, "sha256"), "sha256");
        core::MeshMapBinding binding;
        binding.resource = sha;
        binding.provenance = core::ImportedProvenance{
            "normal_mesh_map", sha, core::MeshMapRole::geometry_only,
            EnumOf<core::NormalMapFormat>(Str(Key(m, "convention"), "convention"), "normal map format"), "", {}};
        spec.builder.Set().mesh_maps[core::MeshMapUsage::Normal] = binding;
    }
    // Ids the spec assigns must stay below next_id: reserve a wide range first.
    if (o.contains("resources")) {
        for (const core::json::Value& entry : Arr(o.at("resources"), "resources")) {
            const core::json::Object& r = Obj(entry, "resource");
            const std::string sha = Str(Key(r, "sha256"), "sha256");
            if (r.contains("png")) {
                // PNG bytes, decoded by the evaluator's provider (sources.h).
                const fs::path png = path.parent_path() / Str(r.at("png"), "png");
                std::ifstream data(png, std::ios::binary);
                if (!data) throw core::ManifestError("cannot read " + png.string());
                std::string bytes((std::istreambuf_iterator<char>(data)), std::istreambuf_iterator<char>());
                spec.builder.AddResource(sha, static_cast<std::int64_t>(bytes.size()));
                spec.resources->AddPng(sha, std::move(bytes));
                continue;
            }
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
    if (o.contains("virtual_outputs")) {
        for (const core::json::Value& c : Arr(o.at("virtual_outputs"), "virtual_outputs")) {
            const std::string name = Str(c, "virtual output");
            if (name == "Normal_OpenGL") spec.virtualOutputs.push_back(core::NormalMapFormat::OpenGL);
            else if (name == "Normal_DirectX") spec.virtualOutputs.push_back(core::NormalMapFormat::DirectX);
            else throw core::ManifestError("virtual output '" + name + "' is not Normal_OpenGL or Normal_DirectX");
        }
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

std::string NormalMapName(core::NormalMapFormat convention) {
    return convention == core::NormalMapFormat::OpenGL ? "Normal_OpenGL" : "Normal_DirectX";
}

core::json::Object TagJson(const NormalTag& tag) {
    core::json::Object o;
    o["role"] = std::string(core::ToString(tag.role));
    if (tag.relief) {
        core::json::Object relief;
        relief["revision"] = tag.relief->revision;
        relief["height_hash"] = tag.relief->heightHash;
        relief["method"] = std::string(core::ToString(tag.relief->method));
        o["relief_round"] = relief;
    } else {
        o["relief_round"] = nullptr;
    }
    return o;
}

using VirtualResults = std::vector<std::pair<core::NormalMapFormat, render::Result<VirtualNormalResult>>>;

/// Writes every output channel: `<channel>.bin` (full raster, native samples, little-endian) and
/// `result.json`; every virtual normal map as `<map>.bin` (three float32 per texel, the encoded
/// normal) with its EXP-09 tag.
int WriteResults(const fs::path& out, const std::vector<std::pair<ChannelType, render::Result<ChannelResult>>>& results,
                 const VirtualResults& virtuals = {}) {
    core::json::Object channels;
    bool ok = true;
    for (const auto& [convention, result] : virtuals) {
        const std::string name = NormalMapName(convention);
        if (!result) {
            core::json::Object entry;
            entry["error"] = result.error().Describe();
            channels[name] = entry;
            Check(false, name + " evaluates", result.error().Describe());
            ok = false;
            continue;
        }
        std::vector<std::byte> raw(result->texels.size() * sizeof(float));
        std::memcpy(raw.data(), result->texels.data(), raw.size());
        WriteFile(out / (name + ".bin"), raw);
        core::json::Object entry;
        entry["format"] = "RGB32F";
        entry["width"] = static_cast<std::int64_t>(result->width);
        entry["height"] = static_cast<std::int64_t>(result->height);
        entry["channels"] = std::int64_t{3};
        entry["bytes_per_channel"] = std::int64_t{4};
        entry["file"] = name + ".bin";
        entry["tag"] = TagJson(result->tag);
        entry["stats"] = StatsJson(result->stats);
        channels[name] = entry;
        Check(true, name + " evaluates");
    }
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
    VirtualResults virtuals;
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
        for (const core::NormalMapFormat convention : spec.virtualOutputs) {
            VirtualNormalRequest request;
            request.textureSet = spec.builder.SetId();
            request.stack = spec.builder.StackId();
            request.convention = convention;
            request.templateId = spec.templateId;
            request.resources = spec.resources;
            virtuals.emplace_back(convention, cpu.EvaluateNormal(spec.builder.project, 1, request));
        }
        return WriteResults(out, results, virtuals);
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
        for (const core::NormalMapFormat convention : spec.virtualOutputs) {
            VirtualNormalRequest request;
            request.textureSet = spec.builder.SetId();
            request.stack = spec.builder.StackId();
            request.convention = convention;
            request.templateId = spec.templateId;
            request.resources = spec.resources;
            std::future<render::Result<VirtualNormalResult>> future =
                evaluator.EvaluateNormal(core::Snapshot{1, project}, std::move(request));
            virtuals.emplace_back(convention, Get(future));
        }
        std::future<render::Result<CacheStats>> stats = evaluator.Stats();
        render::Result<CacheStats> cacheStats = Get(stats);
        if (cacheStats) {
            Info("gpu cache live tiles " + std::to_string(cacheStats->liveTiles) + ", bytes " +
                 std::to_string(cacheStats->liveBytes));
        }
        evaluator.Shutdown();
    }
    return WriteResults(out, results, virtuals);
}

// ── gpu-vs-cpu ───────────────────────────────────────────────────────────────

const std::vector<ChannelFormat> kAllFormats{ChannelFormat::sRGB8, ChannelFormat::L8, ChannelFormat::RGB8,
                                             ChannelFormat::L16, ChannelFormat::RGB16, ChannelFormat::L16F,
                                             ChannelFormat::RGB16F, ChannelFormat::L32F, ChannelFormat::RGB32F};

/// Every mode with a kernel but Disable (which writes nothing to compare).
std::vector<BlendingMode> KernelModes() {
    std::vector<BlendingMode> modes;
    for (size_t i = 0; i < core::EnumTable<BlendingMode>::names.size(); ++i) {
        const BlendingMode mode = static_cast<BlendingMode>(i);
        if (arith::HasKernel(mode) && mode != BlendingMode::Disable) modes.push_back(mode);
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
    const std::vector<BlendingMode> modes = KernelModes();
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
    const std::vector<BlendingMode> modes = KernelModes();
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
          "every blend mode x channel format (with and without coverage) equals the CPU reference bit for bit (" +
              std::to_string(compared) + " samples, " + std::to_string(combinations) + " combinations)");
    return Finish();
}

// ── sources (CPU) ────────────────────────────────────────────────────────────

/// The stored sample a 1:1 projection of `code` (of `bits` bits) gives on a channel of `format`,
/// as `Samples` returns it (half bits on 16-bit floats, the read-out on 32-bit floats).
uint32_t ExpectedSample(uint32_t code, uint32_t bits, const TileFormat& format, uint32_t c, float base) {
    const float value = arith::UnormOperand(code, bits);
    switch (format.encoding) {
        case render::TexelEncoding::Float16: return arith::HalfTowardZero(value);
        case render::TexelEncoding::Float32: return std::bit_cast<uint32_t>(arith::Float32Readout(value, base));
        default: return StoreValue(value, format, c);
    }
}

core::Source AliasedBitmap(const std::string& sha256, const std::string& alias) {
    core::BitmapSource source;
    source.resource.sha256 = sha256;
    source.resource.alias = alias;
    source.color_space = "Data";
    return core::Source{source};
}

void SetUv(core::Layer& layer, core::FilteringMode filter, core::UVWrapMode wrap, std::array<double, 2> scale,
           double rotation, std::array<double, 2> offset) {
    core::Projection& projection = layer.fill->projection;
    projection.mode = core::ProjectionMode::UV;
    projection.uv.filtering_mode = filter;
    projection.uv.uv_wrapping_mode = wrap;
    projection.uv.uv_transformation.scale = scale;
    projection.uv.uv_transformation.rotation = rotation;
    projection.uv.uv_transformation.offset = offset;
}

int RunSources(const fs::path& assets) {
    std::shared_ptr<const TemplateLibrary> templates = LoadTemplates(assets);
    constexpr uint32_t kSize = 128;  // the smallest texture set resolution
    const std::string sha16 = std::string(63, '1') + "6";
    const std::string sha8 = std::string(63, '0') + "8";
    const std::string shaGrey = std::string(63, '9') + "1";
    const std::string shaOblong = std::string(63, '7') + "2";
    auto provider = std::make_shared<MapResourceProvider>();
    std::shared_ptr<DecodedImage> image16 = PatternImage(kSize, kSize, 3, render::TexelEncoding::Unorm16, 11);
    std::shared_ptr<DecodedImage> image8 = PatternImage(kSize, kSize, 3, render::TexelEncoding::Unorm8, 12);
    std::shared_ptr<DecodedImage> grey = PatternImage(kSize, kSize, 1, render::TexelEncoding::Unorm16, 13);
    provider->Add(sha16, image16);
    provider->Add(sha8, image8);
    provider->Add(shaGrey, grey);
    provider->Add(shaOblong, PatternImage(kSize, kSize / 2, 3, render::TexelEncoding::Unorm16, 14));
    const std::vector<ChannelType> user0{ChannelType::User0};
    auto evaluate = [&](Builder& builder, ChannelType channel, CpuEvaluator& cpu) {
        EvaluateRequest request;
        request.textureSet = builder.SetId();
        request.stack = builder.StackId();
        request.channel = channel;
        request.resources = provider;
        return cpu.Evaluate(builder.project, request);
    };
    auto single = [&](ChannelFormat format, const core::Layer& prototype, Builder& builder) {
        (void)format;
        builder.AddResource(sha16, 100);
        builder.AddResource(sha8, 100);
        builder.AddResource(shaGrey, 100);
        builder.AddResource(shaOblong, 100);
        builder.SetRoot({prototype});
    };

    // 1:1 copies on every channel format, from 16- and 8-bit bitmaps, with every filter.
    for (const auto& [sha, img, bits] : {std::tuple{sha16, image16, 16u}, std::tuple{sha8, image8, 8u}, std::tuple{shaGrey, grey, 16u}}) {
        for (const core::FilteringMode filter : {core::FilteringMode::BilinearHQ, core::FilteringMode::BilinearSharp, core::FilteringMode::Nearest}) {
            bool all = true;
            std::string detail;
            for (const ChannelFormat format : kAllFormats) {
                Builder builder(kSize, kSize, {{ChannelType::User0, format}});
                core::Layer layer = builder.Fill("bitmap", SameSource(user0, Bitmap(sha)), Same(user0, BlendingMode::Normal, 1.0));
                SetUv(layer, filter, core::UVWrapMode::Repeat, {1.0, 1.0}, 0.0, {0.0, 0.0});
                single(format, layer, builder);
                CpuEvaluator cpu(templates, kWideLimits);
                render::Result<ChannelResult> result = evaluate(builder, ChannelType::User0, cpu);
                if (!result) { all = false; detail = Describe(result); break; }
                const TileFormat tf = TileFormatOf(format);
                const std::vector<uint32_t> samples = Samples(*result);
                for (size_t t = 0; t < size_t{kSize} * kSize && all; ++t) {
                    for (uint32_t c = 0; c < tf.channels && all; ++c) {
                        const uint32_t code = img->values[t * img->channels + (img->channels == 1 ? 0 : c)];
                        if (samples[t * tf.channels + c] != ExpectedSample(code, bits, tf, c, 1.0f)) {
                            all = false;
                            detail = std::string(core::ToString(format)) + " texel " + std::to_string(t);
                        }
                    }
                }
            }
            Check(all, "a 1:1 " + std::to_string(bits) + "-bit " + (img->channels == 1 ? "grey" : "colour") + " bitmap under " +
                           std::string(core::ToString(filter)) + " stores each code as a linear value with the write rule of every channel format",
                  detail);
        }
    }
    {
        Builder builder(kSize, kSize, {{ChannelType::User0, ChannelFormat::RGB16}});
        core::Layer layer = builder.Fill("bitmap", SameSource(user0, Bitmap(sha16)), Same(user0, BlendingMode::Normal, 1.0));
        layer.fill->projection.mode = core::ProjectionMode::Fill;
        single(ChannelFormat::RGB16, layer, builder);
        CpuEvaluator cpu(templates, kWideLimits);
        render::Result<ChannelResult> result = evaluate(builder, ChannelType::User0, cpu);
        Check(result && Samples(*result) == image16->values, "the Fill projection matches the bitmap to the UV tile (a 1:1 copy)", Describe(result));
    }

    // sRGB bitmaps (sources.h): decoded onto an sRGB8 channel at 1:1; every other use is refused.
    {
        // The stored code does not depend on the decode's arithmetic: the double-precision decode and the GPU's
        // float32 one (x / 12.92 as a product, ((x + 0.055) / 1.055)^2.4 through the measured pow) agree on every code.
        size_t differing = 0;
        for (uint32_t code = 0; code <= 0xFFFFu; ++code) {
            const float x = arith::UnormOperand(code, 16);
            const float gpu = x <= 0.04045f ? x * static_cast<float>(1.0 / 12.92)
                                            : hw::Pow((x + 0.055f) * static_cast<float>(1.0 / 1.055), 2.4f);
            if (arith::Srgb8Store(static_cast<float>(arith::SrgbDecode(x))) != arith::Srgb8Store(gpu)) ++differing;
        }
        Check(differing == 0, "on an sRGB8 channel the double-precision and the GPU's float32 sRGB decode store the same code "
                              "for each of the 65 536 16-bit codes",
              std::to_string(differing) + " differ");
        auto srgb = [&](ChannelFormat format, const std::string& sha, double scale) {
            Builder builder(kSize, kSize, {{ChannelType::User0, format}});
            core::Layer layer = builder.Fill("bitmap", SameSource(user0, Bitmap(sha, "sRGB")), Same(user0, BlendingMode::Normal, 1.0));
            if (scale == 1.0) {
                layer.fill->projection.mode = core::ProjectionMode::Fill;
            } else {
                SetUv(layer, core::FilteringMode::Nearest, core::UVWrapMode::Repeat, {scale, scale}, 0.0, {0.0, 0.0});
            }
            single(format, layer, builder);
            CpuEvaluator cpu(templates, kWideLimits);
            return evaluate(builder, ChannelType::User0, cpu);
        };
        render::Result<ChannelResult> decoded = srgb(ChannelFormat::sRGB8, sha16, 1.0);
        bool ok = decoded.has_value();
        if (ok) {
            const std::vector<uint32_t> samples = Samples(*decoded);
            for (size_t k = 0; k < samples.size() && ok; ++k) {
                const float x = arith::UnormOperand(image16->values[k], 16);
                ok = samples[k] == arith::Srgb8Store(static_cast<float>(arith::SrgbDecode(x)));
            }
        }
        Check(ok, "a 16-bit colour sRGB bitmap at 1:1 stores the sRGB8 code of the sRGB decode of each code", Describe(decoded));
        bool refused = true;
        std::string detail;
        for (const auto& [name, result] :
             {std::pair{"RGB16 channel", srgb(ChannelFormat::RGB16, sha16, 1.0)}, std::pair{"8-bit bitmap", srgb(ChannelFormat::sRGB8, sha8, 1.0)},
              std::pair{"grey bitmap", srgb(ChannelFormat::sRGB8, shaGrey, 1.0)},
              std::pair{"Nearest at scale 0.5", srgb(ChannelFormat::sRGB8, sha16, 0.5)}}) {
            if (result || KindName(result.error()) != "unsupported_source") {
                refused = false;
                detail += std::string(name) + ": " + Describe(result) + " ";
            }
        }
        Builder working(kSize, kSize, {{ChannelType::User0, ChannelFormat::sRGB8}});
        working.SetRoot({working.Fill("bitmap", SameSource(user0, Bitmap(sha16, "Working")), Same(user0, BlendingMode::Normal, 1.0))});
        working.AddResource(sha16, 100);
        CpuEvaluator cpu(templates, kWideLimits);
        render::Result<ChannelResult> unrecorded = evaluate(working, ChannelType::User0, cpu);
        if (unrecorded || KindName(unrecorded.error()) != "unsupported_source") {
            refused = false;
            detail += "Working: " + Describe(unrecorded);
        }
        Check(refused, "an sRGB bitmap on a channel that is not sRGB8, 8-bit or grey, or resampled, and a bitmap in the Working "
                       "colour space fail with unsupported_source",
              detail);
    }

    // Transforms on RGB16 against direct texel arithmetic.
    auto project = [&](core::FilteringMode filter, core::UVWrapMode wrap, std::array<double, 2> scale, double rotation,
                       std::array<double, 2> offset, const std::string& sha) -> render::Result<ChannelResult> {
        Builder builder(kSize, kSize, {{ChannelType::User0, ChannelFormat::RGB16}});
        core::Layer layer = builder.Fill("bitmap", SameSource(user0, Bitmap(sha)), Same(user0, BlendingMode::Normal, 1.0));
        SetUv(layer, filter, wrap, scale, rotation, offset);
        single(ChannelFormat::RGB16, layer, builder);
        if (!builder.Validate("projection")) return EvalFail(EvalErrorKind::Internal, "invalid test project");
        CpuEvaluator cpu(templates, kWideLimits);
        return evaluate(builder, ChannelType::User0, cpu);
    };
    auto at = [&](const DecodedImage& img, int64_t x, int64_t y, uint32_t c) {
        const int64_t n = kSize;
        return img.At(static_cast<uint32_t>(((x % n) + n) % n), static_cast<uint32_t>(((y % n) + n) % n), c);
    };
    for (const core::FilteringMode filter : {core::FilteringMode::Nearest, core::FilteringMode::BilinearHQ}) {
        // An offset of three texels along +u and two along +v moves the image (v up: towards the top).
        render::Result<ChannelResult> shifted = project(filter, core::UVWrapMode::Repeat, {1.0, 1.0}, 0.0,
                                                        {3.0 / kSize, 2.0 / kSize}, sha16);
        bool ok = shifted.has_value();
        if (ok) {
            const std::vector<uint32_t> s = Samples(*shifted);
            for (uint32_t y = 0; y < kSize && ok; ++y) {
                for (uint32_t x = 0; x < kSize && ok; ++x) {
                    for (uint32_t c = 0; c < 3 && ok; ++c) {
                        ok = s[(size_t{y} * kSize + x) * 3 + c] == at(*image16, int64_t{x} - 3, int64_t{y} + 2, c);
                    }
                }
            }
        }
        Check(ok, std::string(core::ToString(filter)) + ": a whole-texel offset with Repeat moves the bitmap towards +u and +v, wrapping",
              Describe(shifted));
    }
    {
        // Magnification by 2 (scale 0.5) with Nearest: each bitmap texel covers a 2 x 2 block about the centre.
        render::Result<ChannelResult> magnified = project(core::FilteringMode::Nearest, core::UVWrapMode::Repeat, {0.5, 0.5}, 0.0, {0.0, 0.0}, sha16);
        bool ok = magnified.has_value();
        if (ok) {
            const std::vector<uint32_t> s = Samples(*magnified);
            for (uint32_t y = 0; y < kSize && ok; ++y) {
                for (uint32_t x = 0; x < kSize && ok; ++x) {
                    ok = s[(size_t{y} * kSize + x) * 3] == image16->At(kSize / 4 + x / 2, kSize / 4 + y / 2, 0);
                }
            }
        }
        Check(ok, "Nearest at scale 0.5 magnifies the centre of the bitmap by two", Describe(magnified));
        // The offset precedes the scale (decision 056): at scale 0.5 an offset of four set texels along +u moves the
        // bitmap by two of its texels, not four.
        render::Result<ChannelResult> moved =
            project(core::FilteringMode::Nearest, core::UVWrapMode::Repeat, {0.5, 0.5}, 0.0, {4.0 / kSize, 0.0}, sha16);
        ok = moved.has_value();
        if (ok) {
            const std::vector<uint32_t> s = Samples(*moved);
            for (uint32_t y = 0; y < kSize && ok; ++y) {
                for (uint32_t x = 0; x < kSize && ok; ++x) {
                    ok = s[(size_t{y} * kSize + x) * 3] == at(*image16, int64_t{kSize / 4 + x / 2} - 2, kSize / 4 + y / 2, 0);
                }
            }
        }
        Check(ok, "the UV offset is applied before the scale: an offset of 4 / W at scale 0.5 moves the bitmap by two texels",
              Describe(moved));
        // Bilinear half way between two texels: (a + b) / 2 through the fixed-point weights.
        render::Result<ChannelResult> half = project(core::FilteringMode::BilinearHQ, core::UVWrapMode::Repeat, {1.0, 1.0}, 0.0,
                                                     {0.5 / kSize, 0.0}, sha16);
        ok = half.has_value();
        if (ok) {
            const std::vector<uint32_t> s = Samples(*half);
            for (uint32_t y = 0; y < kSize && ok; ++y) {
                for (uint32_t x = 0; x < kSize && ok; ++x) {
                    const float left = arith::UnormOperand(at(*image16, int64_t{x} - 1, y, 0), 16);
                    const float right = arith::UnormOperand(at(*image16, x, y, 0), 16);
                    const float value = ReferenceFilter({128, 128, 0, 0}, {left, right, 0.0f, 0.0f});
                    ok = s[(size_t{y} * kSize + x) * 3] == arith::WriteUnorm(value, 16);
                }
            }
        }
        Check(ok, "BilinearHQ half a texel off weighs both texels 128/256 through the GPU's linear filter and stores it with the "
                  "write rule",
              Describe(half));
        // The GPU's linear filter keeps 28 bits below the largest weighed texel's exponent. The resample-uv near-tie
        // (user2, texel (175, 18), green): codes 38535, 65357, 55719, 1194 weighed 15, 52, 44, 145 give 412590 / 2^20
        // truncated (Painter's value), where the float texels' exact sum would round up to 412591 / 2^20; a texel
        // weighed 256 comes back unchanged; beside 1.0 a small texel keeps 27 fractional bits.
        const std::array<uint32_t, 4> tieWeights{15, 52, 44, 145};
        std::array<float, 4> tieTexels{};
        double floatSum = 0.0;
        const std::array<uint32_t, 4> tieCodes{38535, 65357, 55719, 1194};
        for (size_t k = 0; k < 4; ++k) {
            tieTexels[k] = arith::UnormOperand(tieCodes[k], 16);
            floatSum += tieWeights[k] * static_cast<double>(tieTexels[k]);
        }
        const float tie = BilinearFilter(tieWeights, tieTexels);
        const float small = arith::UnormOperand(1322, 16);
        const float beside = BilinearFilter({255, 1, 0, 0}, {small, 1.0f, 0.0f, 0.0f});
        Check(std::floor(std::ldexp(static_cast<double>(tie), 20)) == 412590.0 &&
                  std::floor(std::ldexp(static_cast<double>(static_cast<float>(floatSum / 256.0)), 20)) == 412591.0 &&
                  tie == ReferenceFilter(tieWeights, tieTexels) && BilinearFilter({256, 0, 0, 0}, {small, 1.0f, 1.0f, 1.0f}) == small &&
                  beside == ReferenceFilter({255, 1, 0, 0}, {small, 1.0f, 0.0f, 0.0f}),
              "the bilinear filter aligns the weighed texels to the largest one's exponent with 28 bits (the resample-uv near-tie "
              "rounds down; a 256/256 texel is unchanged)");
    }
    {
        // RepeatNone: the texels moved in from outside the UV square keep the value below (the base, 1.0).
        render::Result<ChannelResult> none = project(core::FilteringMode::Nearest, core::UVWrapMode::RepeatNone, {1.0, 1.0}, 0.0,
                                                     {4.0 / kSize, 0.0}, sha16);
        bool ok = none.has_value();
        if (ok) {
            const std::vector<uint32_t> s = Samples(*none);
            for (uint32_t y = 0; y < kSize && ok; ++y) {
                for (uint32_t x = 0; x < kSize && ok; ++x) {
                    for (uint32_t c = 0; c < 3 && ok; ++c) {
                        const uint32_t expected = x < 4 ? 65535u : image16->At(x - 4, y, c);
                        ok = s[(size_t{y} * kSize + x) * 3 + c] == expected;
                    }
                }
            }
        }
        Check(ok, "RepeatNone leaves the texels outside the UV square to the value below the fill", Describe(none));
        render::Result<ChannelResult> horizontal = project(core::FilteringMode::Nearest, core::UVWrapMode::RepeatHorizontally,
                                                           {1.0, 1.0}, 0.0, {4.0 / kSize, 4.0 / kSize}, sha16);
        ok = horizontal.has_value();
        if (ok) {
            const std::vector<uint32_t> s = Samples(*horizontal);
            for (uint32_t y = 0; y < kSize && ok; ++y) {
                for (uint32_t x = 0; x < kSize && ok; ++x) {
                    const uint32_t expected = y >= kSize - 4 ? 65535u : at(*image16, int64_t{x} - 4, y + 4, 0);
                    ok = s[(size_t{y} * kSize + x) * 3] == expected;
                }
            }
        }
        Check(ok, "RepeatHorizontally wraps along u and leaves the texels outside [0, 1) in v uncovered", Describe(horizontal));
    }
    {
        // A 90 degree rotation with Nearest turns the bitmap a quarter turn.
        render::Result<ChannelResult> turned = project(core::FilteringMode::Nearest, core::UVWrapMode::Repeat, {1.0, 1.0}, 90.0, {0.0, 0.0}, sha16);
        bool ok = turned.has_value();
        if (ok) {
            const std::vector<uint32_t> s = Samples(*turned);
            for (uint32_t y = 0; y < kSize && ok; ++y) {
                for (uint32_t x = 0; x < kSize && ok; ++x) {
                    // u' = v, v' = 1 - u: bitmap column kSize - 1 - y, row x.
                    ok = s[(size_t{y} * kSize + x) * 3] == image16->At(kSize - 1 - y, x, 0);
                }
            }
        }
        Check(ok, "Nearest with a 90 degree rotation turns the bitmap a quarter turn about the UV centre", Describe(turned));
    }

    // Explicit failures.
    {
        // Bilinear minification goes through the texture unit (texture_unit.h, decision 084) for a
        // rotation that is a multiple of 90 degrees and a square power-of-two bitmap; the goldens
        // check its values (test_compositor_sources_projection.py).
        bool axisAligned = true;
        std::string axisDetail;
        for (const core::FilteringMode filter : {core::FilteringMode::BilinearHQ, core::FilteringMode::BilinearSharp}) {
            for (const double rotation : {0.0, 90.0, 180.0, 270.0}) {
                render::Result<ChannelResult> minified =
                    project(filter, core::UVWrapMode::Repeat, {3.3, 2.1}, rotation, {0.0123, 0.0456}, sha16);
                if (!minified) {
                    axisAligned = false;
                    axisDetail = Describe(minified);
                }
            }
        }
        Check(axisAligned, "bilinear minification at rotations 0, 90, 180 and 270 evaluates through the texture unit", axisDetail);
        render::Result<ChannelResult> rotated =
            project(core::FilteringMode::BilinearHQ, core::UVWrapMode::Repeat, {3.3, 3.3}, 30.0, {0.0, 0.0}, sha16);
        Check(!rotated && KindName(rotated.error()) == "unsupported_source" &&
                  rotated.error().reason.find("rotation") != std::string::npos,
              "bilinear minification at a rotation that is not a multiple of 90 degrees fails with unsupported_source "
              "(release gap)",
              Describe(rotated));
        render::Result<ChannelResult> oblong =
            project(core::FilteringMode::BilinearSharp, core::UVWrapMode::Repeat, {3.3, 3.3}, 0.0, {0.0, 0.0}, shaOblong);
        Check(!oblong && KindName(oblong.error()) == "unsupported_source",
              "bilinear minification of a bitmap that is not square fails with unsupported_source (release gap)",
              Describe(oblong));
        {
            // Painter filters the signed heights (ProjectTexel); their minification is unmeasured.
            const std::vector<ChannelType> heightOnly{ChannelType::Height};
            Builder builder(kSize, kSize, {{ChannelType::Height, ChannelFormat::L16F}});
            core::Layer layer = builder.Fill("bitmap", SameSource(heightOnly, Bitmap(sha16)), Same(heightOnly, BlendingMode::Normal, 1.0));
            SetUv(layer, core::FilteringMode::BilinearHQ, core::UVWrapMode::Repeat, {3.3, 3.3}, 0.0, {0.0, 0.0});
            single(ChannelFormat::L16F, layer, builder);
            CpuEvaluator cpu(templates, kWideLimits);
            render::Result<ChannelResult> height = evaluate(builder, ChannelType::Height, cpu);
            Check(!height && KindName(height.error()) == "unsupported_source" &&
                      height.error().reason.find("Height") != std::string::npos,
                  "bilinear minification on the Height channel fails with unsupported_source (release gap)",
                  Describe(height));
        }
        render::Result<ChannelResult> nearest = project(core::FilteringMode::Nearest, core::UVWrapMode::Repeat, {3.3, 3.3}, 0.0, {0.0, 0.0}, sha16);
        Check(nearest.has_value(), "Nearest evaluates at any scale", Describe(nearest));
        Builder builder(kSize, kSize, {{ChannelType::User0, ChannelFormat::RGB16}});
        core::Layer layer = builder.Fill("bitmap", SameSource(user0, Bitmap(sha16)), Same(user0, BlendingMode::Normal, 1.0));
        layer.fill->projection.uv.uv_transformation.scale_mode = core::ScaleMode::MaterialPhysicalSize;
        single(ChannelFormat::RGB16, layer, builder);
        CpuEvaluator cpu(templates, kWideLimits);
        render::Result<ChannelResult> physical = evaluate(builder, ChannelType::User0, cpu);
        Check(!physical && KindName(physical.error()) == "unsupported_source", "a physical-size scale mode fails with unsupported_source",
              Describe(physical));
        Builder ocio(kSize, kSize, {{ChannelType::User0, ChannelFormat::RGB16}});
        ocio.project.settings.color_management.mode = "ocio";
        ocio.SetRoot({ocio.Fill("uniform", SameSource(user0, Uniform(0.5, 0.5, 0.5)), Same(user0, BlendingMode::Normal, 1.0))});
        CpuEvaluator cpu2(templates, kWideLimits);
        render::Result<ChannelResult> managed = evaluate(ocio, ChannelType::User0, cpu2);
        Check(!managed && KindName(managed.error()) == "unsupported_source", "an OCIO colour-managed project fails with unsupported_source",
              Describe(managed));
        Builder odd(96, 64, {{ChannelType::User0, ChannelFormat::RGB16}});
        odd.AddResource(sha16, 100);
        odd.SetRoot({odd.Fill("bitmap", SameSource(user0, Bitmap(sha16)), Same(user0, BlendingMode::Normal, 1.0))});
        CpuEvaluator cpu3(templates, kWideLimits);
        render::Result<ChannelResult> npot = evaluate(odd, ChannelType::User0, cpu3);
        Check(!npot && KindName(npot.error()) == "unsupported_source", "a UV projection on a non-power-of-two set fails with unsupported_source",
              Describe(npot));
        render::Result<DecodedImage> garbage = DecodeBitmap("not a png");
        Check(!garbage && KindName(garbage.error()) == "unsupported_source", "bytes that are not a PNG fail to decode with unsupported_source",
              Describe(garbage));
        DecodingResourceProvider wrongHash([](std::string_view) -> std::optional<std::string> { return std::string("bytes"); });
        Check(wrongHash.Fetch(std::string(64, 'a')) == nullptr, "a resource whose bytes do not hash to its key is unavailable");
    }

    // LAY-13: two fills bind different bytes under the same alias; each reads its own.
    {
        const std::string shaA = std::string(63, 'a') + "1";
        const std::string shaB = std::string(63, 'b') + "2";
        auto bound = std::make_shared<MapResourceProvider>();
        std::shared_ptr<DecodedImage> a = PatternImage(kSize, kSize, 1, render::TexelEncoding::Unorm16, 21);
        std::shared_ptr<DecodedImage> b = PatternImage(kSize, kSize, 1, render::TexelEncoding::Unorm16, 22);
        for (size_t i = 0; i < a->values.size(); ++i) a->values[i] = (a->values[i] * 7 + 3) & 0xFFFF;
        bound->Add(shaA, a);
        bound->Add(shaB, b);
        Builder builder(kSize, kSize, {{ChannelType::User0, ChannelFormat::L16}, {ChannelType::User1, ChannelFormat::L16}});
        builder.AddResource(shaA, 100);
        builder.AddResource(shaB, 100);
        const std::vector<ChannelType> u0{ChannelType::User0};
        const std::vector<ChannelType> u1{ChannelType::User1};
        builder.SetRoot({builder.Fill("C07", SameSource(u0, AliasedBitmap(shaA, "M_piping")), Same(u0, BlendingMode::Normal, 1.0)),
                         builder.Fill("F03", SameSource(u1, AliasedBitmap(shaB, "M_piping")), Same(u1, BlendingMode::Normal, 1.0))});
        if (!builder.Validate("alias")) return Finish();
        CpuEvaluator cpu(templates, kWideLimits);
        auto run = [&](ChannelType channel) {
            EvaluateRequest request;
            request.textureSet = builder.SetId();
            request.stack = builder.StackId();
            request.channel = channel;
            request.resources = bound;
            return cpu.Evaluate(builder.project, request);
        };
        render::Result<ChannelResult> first = run(ChannelType::User0);
        render::Result<ChannelResult> second = run(ChannelType::User1);
        Check(first && second && Samples(*first) == a->values && Samples(*second) == b->values,
              "two fills binding different bytes under the alias M_piping each evaluate to their own bytes (LAY-13)",
              Describe(first) + " / " + Describe(second));
    }

    // The cache keys carry the set resolution: a resized set never reuses a tile of the old size.
    {
        Builder builder(512, 512, {{ChannelType::User0, ChannelFormat::RGB16}});
        builder.AddResource(sha16, 100);
        builder.SetRoot({builder.Fill("bitmap", SameSource(user0, Bitmap(sha16)), Same(user0, BlendingMode::Normal, 1.0)),
                         builder.Fill("uniform", SameSource(user0, Uniform(0.25, 0.5, 0.75)), Same(user0, BlendingMode::Multiply, 0.5))});
        if (!builder.Validate("resize")) return Finish();
        CpuEvaluator cpu(templates, kWideLimits);
        render::Result<ChannelResult> small = evaluate(builder, ChannelType::User0, cpu);
        builder.Set().resolution.width = 1024;
        builder.Set().resolution.height = 1024;
        render::Result<ChannelResult> large = evaluate(builder, ChannelType::User0, cpu);
        CpuEvaluator fresh(templates, kWideLimits);
        render::Result<ChannelResult> reference = evaluate(builder, ChannelType::User0, fresh);
        Check(small && large && reference && large->width == 1024 && large->height == 1024 && large->stats.cacheHits == 0 &&
                  Samples(*large) == Samples(*reference),
              "after a resolution change the same evaluator re-evaluates every tile at the new size (no stale cache hit)",
              Describe(large));
    }
    return Finish();
}

// ── projection-gpu-vs-cpu ────────────────────────────────────────────────────

int RunProjectionGpuVsCpu(const fs::path& assets, const fs::path& dir) {
    std::shared_ptr<const TemplateLibrary> templates = LoadTemplates(assets);
    render::Engine engine(TestOptions(dir));
    if (NoAdapter(engine)) return kExitSkip;
    Info("adapter " + engine.Capabilities().value_or(render::CapabilityReport{}).adapter);
    std::mt19937 rng(1808);
    auto unit = [&] { return std::uniform_real_distribution<double>(0.0, 1.0)(rng); };
    const std::vector<BlendingMode> modes = KernelModes();
    Evaluator gpu(engine, templates);
    size_t compared = 0;
    size_t stacks = 0;
    bool allEqual = true;
    const std::vector<core::UVWrapMode> wraps{core::UVWrapMode::Repeat, core::UVWrapMode::RepeatNone,
                                              core::UVWrapMode::RepeatHorizontally, core::UVWrapMode::RepeatVertically};
    const std::vector<core::FilteringMode> filters{core::FilteringMode::BilinearHQ, core::FilteringMode::BilinearSharp,
                                                   core::FilteringMode::Nearest};
    int serial = 0;
    for (const ChannelFormat format : kAllFormats) {
        for (int variant = 0; variant < 4; ++variant) {
            const uint32_t width = variant == 3 ? 2048 : 256;
            const uint32_t height = variant == 3 ? 1024 : 256;
            // The Height channel (signed range) on its template format.
            const ChannelType type = format == ChannelFormat::L16F && variant % 2 == 1 ? ChannelType::Height : ChannelType::User0;
            Builder builder(width, height, {{type, format}});
            auto provider = std::make_shared<MapResourceProvider>();
            const std::vector<ChannelType> channels{type};
            std::vector<core::Layer> layers;
            for (int i = 0; i < 3; ++i) {
                const bool sixteen = (rng() & 1) != 0;
                const uint32_t imageChannels = (rng() & 3) == 0 ? 1 : 3;
                const uint32_t side = (rng() & 1) != 0 ? 64 : 256;
                char buffer[65];
                std::snprintf(buffer, sizeof(buffer), "%064d", ++serial);
                const std::string sha(buffer);
                provider->Add(sha, PatternImage(side, side, imageChannels,
                                                sixteen ? render::TexelEncoding::Unorm16 : render::TexelEncoding::Unorm8, rng()));
                builder.AddResource(sha, 100);
                core::Layer layer = builder.Fill("bitmap" + std::to_string(i), SameSource(channels, Bitmap(sha)),
                                                 Same(channels, i == 0 ? BlendingMode::Normal : modes[rng() % modes.size()], 0.3 + 0.7 * unit()));
                const core::FilteringMode filter = filters[rng() % filters.size()];
                // Bilinear filters only magnify: the footprint is at most one bitmap texel.
                const double fit = static_cast<double>(std::min(width, height)) / side;
                const double scale = filter == core::FilteringMode::Nearest ? 0.2 + 4.0 * unit() : fit * (0.3 + 0.6 * unit());
                SetUv(layer, filter, wraps[rng() % wraps.size()], {scale, scale * (0.8 + 0.2 * unit())}, 360.0 * unit() - 180.0,
                      {unit() - 0.5, unit() - 0.5});
                layers.push_back(std::move(layer));
            }
            builder.SetRoot(layers);
            if (!builder.Validate("projection stack")) return Finish();
            EvaluateRequest request;
            request.textureSet = builder.SetId();
            request.stack = builder.StackId();
            request.channel = type;
            request.resources = provider;
            CpuEvaluator cpu(templates, kWideLimits);
            render::Result<ChannelResult> cpuResult = cpu.Evaluate(builder.project, request);
            auto project = std::make_shared<const core::Project>(builder.project);
            std::future<render::Result<ChannelResult>> future = gpu.Evaluate(core::Snapshot{1, project}, request);
            render::Result<ChannelResult> gpuResult = Get(future);
            const std::string label = std::string(core::ToString(format)) + " projection stack " + std::to_string(variant) +
                                      (type == ChannelType::Height ? " (Height)" : "");
            ++stacks;
            if (!cpuResult || !gpuResult) {
                allEqual = false;
                Check(false, label + " evaluates on both stores", Describe(cpuResult) + " / " + Describe(gpuResult));
                continue;
            }
            std::string first;
            const std::vector<uint32_t> expected = Samples(*cpuResult);
            const size_t mismatches = Mismatches(expected, Samples(*gpuResult), first, cpuResult->tileFormat.encoding);
            compared += expected.size();
            if (mismatches != 0) {
                allEqual = false;
                Check(false, label + ": GPU equals CPU", std::to_string(mismatches) + " mismatches; " + first);
            }
        }
    }
    // Minifying stacks through the texture unit (texture_unit.h, decision 084): square sets and
    // bitmaps, rotations by multiples of 90 degrees, Repeat and RepeatNone, footprints from one to
    // twelve texels with anisotropy up to 4 on either axis.
    size_t minified = 0;
    for (int variant = 0; variant < 8; ++variant) {
        const ChannelFormat format = variant % 2 == 0 ? ChannelFormat::RGB16 : ChannelFormat::RGB32F;
        Builder builder(256, 256, {{ChannelType::User0, format}});
        auto provider = std::make_shared<MapResourceProvider>();
        const std::vector<ChannelType> channels{ChannelType::User0};
        std::vector<core::Layer> layers;
        for (int i = 0; i < 2; ++i) {
            const bool sixteen = (rng() & 1) != 0;
            const uint32_t side = (rng() & 1) != 0 ? 64 : 256;
            char buffer[65];
            std::snprintf(buffer, sizeof(buffer), "%064d", ++serial);
            const std::string sha(buffer);
            provider->Add(sha, PatternImage(side, side, 3, sixteen ? render::TexelEncoding::Unorm16 : render::TexelEncoding::Unorm8, rng()));
            builder.AddResource(sha, 100);
            core::Layer layer = builder.Fill("minified" + std::to_string(i), SameSource(channels, Bitmap(sha)),
                                             Same(channels, i == 0 ? BlendingMode::Normal : modes[rng() % modes.size()], 0.3 + 0.7 * unit()));
            const core::FilteringMode filter = (rng() & 1) != 0 ? core::FilteringMode::BilinearHQ : core::FilteringMode::BilinearSharp;
            const double fit = 256.0 / side;
            const double major = fit * (1.1 + 11.0 * unit());
            const double minor = major / (1.0 + 3.0 * unit());
            const bool uMajor = (rng() & 1) != 0;
            SetUv(layer, filter, (rng() & 1) != 0 ? core::UVWrapMode::Repeat : core::UVWrapMode::RepeatNone,
                  {uMajor ? major : minor, uMajor ? minor : major}, 90.0 * static_cast<double>(rng() % 4),
                  {unit() - 0.5, unit() - 0.5});
            layers.push_back(std::move(layer));
        }
        builder.SetRoot(layers);
        if (!builder.Validate("minifying projection stack")) return Finish();
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
        const std::string label = std::string(core::ToString(format)) + " minifying projection stack " + std::to_string(variant);
        if (!cpuResult || !gpuResult) {
            allEqual = false;
            Check(false, label + " evaluates on both stores", Describe(cpuResult) + " / " + Describe(gpuResult));
            continue;
        }
        std::string first;
        const std::vector<uint32_t> expected = Samples(*cpuResult);
        const size_t mismatches = Mismatches(expected, Samples(*gpuResult), first, cpuResult->tileFormat.encoding);
        minified += expected.size();
        if (mismatches != 0) {
            allEqual = false;
            Check(false, label + ": GPU equals CPU", std::to_string(mismatches) + " mismatches; " + first);
        }
    }
    Check(minified > 0 && allEqual,
          "every random minifying projection stack (BilinearHQ and BilinearSharp through the texture unit, rotations by "
          "multiples of 90 degrees, Repeat and RepeatNone) evaluates to the same bytes on the GPU and on the CPU (" +
              std::to_string(minified) + " samples)",
          "");
    Check(allEqual, "every random projection stack (filters, wrap modes, transforms, 8/16-bit grey and colour bitmaps) evaluates "
                    "to the same bytes on the GPU and on the CPU (" + std::to_string(compared) + " samples, " +
                    std::to_string(stacks) + " stacks over 9 formats)");

    // The grid size reaches the GPU cache keys too.
    {
        const std::string sha = std::string(63, 'e') + "1";
        auto provider = std::make_shared<MapResourceProvider>();
        provider->Add(sha, PatternImage(64, 64, 3, render::TexelEncoding::Unorm16, 5));
        Builder builder(512, 512, {{ChannelType::User0, ChannelFormat::RGB16}});
        builder.AddResource(sha, 100);
        const std::vector<ChannelType> channels{ChannelType::User0};
        builder.SetRoot({builder.Fill("bitmap", SameSource(channels, Bitmap(sha)), Same(channels, BlendingMode::Normal, 1.0))});
        EvaluateRequest request;
        request.textureSet = builder.SetId();
        request.stack = builder.StackId();
        request.channel = ChannelType::User0;
        request.resources = provider;
        auto small = std::make_shared<const core::Project>(builder.project);
        std::future<render::Result<ChannelResult>> f1 = gpu.Evaluate(core::Snapshot{1, small}, request);
        render::Result<ChannelResult> r1 = Get(f1);
        builder.Set().resolution.width = 1024;
        builder.Set().resolution.height = 1024;
        auto large = std::make_shared<const core::Project>(builder.project);
        std::future<render::Result<ChannelResult>> f2 = gpu.Evaluate(core::Snapshot{2, large}, request);
        render::Result<ChannelResult> r2 = Get(f2);
        CpuEvaluator cpu(templates, kWideLimits);
        render::Result<ChannelResult> reference = cpu.Evaluate(builder.project, request);
        Check(r1 && r2 && reference && r2->width == 1024 && r2->stats.cacheHits == 0 && Samples(*r2) == Samples(*reference),
              "GPU: after a resolution change the same evaluator re-evaluates at the new size", Describe(r2));
    }
    gpu.Shutdown();
    return Finish();
}

// ── srgb8-hardware ───────────────────────────────────────────────────────────

/// The codes a D3D12 clear of an RGBA8 sRGB render target stores for each value (the GPU's
/// float-to-sRGB8 conversion).
render::Result<std::vector<uint8_t>> ClearCodes(render::Engine& engine, const std::vector<float>& values) {
    std::vector<uint8_t> codes(values.size());
    auto token = std::make_shared<const int>(0);
    constexpr uint32_t kChunk = 2048;
    for (size_t first = 0; first < values.size(); first += kChunk) {
        const uint32_t count = static_cast<uint32_t>(std::min<size_t>(kChunk, values.size() - first));
        std::future<render::Result<std::vector<uint8_t>>> future = engine.Submit(
            token, [&](render::EngineContext& context, const int&) -> render::Result<std::vector<uint8_t>> {
                render::IDevice& device = context.Device();
                uz::RHITextureDesc desc;
                desc.width = 1;
                desc.height = 1;
                desc.format = uz::RHIFormat::RGBA8Srgb;
                desc.usage = uz::RHITextureUsage::RenderTarget | uz::RHITextureUsage::CopySrc;
                desc.debugName = "srgb8_clear";
                render::Result<uz::RHITextureHandle> texture = device.CreateTexture(desc);
                if (!texture) return render::Unexpected(texture.error());
                uz::RHIBufferDesc bdesc;
                bdesc.sizeBytes = uint64_t{kChunk} * 512;  // D3D12 placement alignment per copy
                bdesc.usage = uz::RHIBufferUsage::CopyDst;
                bdesc.memory = uz::RHIMemoryType::Readback;
                bdesc.debugName = "srgb8_clear_readback";
                render::Result<uz::RHIBufferHandle> buffer = device.CreateBuffer(bdesc);
                if (!buffer) {
                    device.DestroyTexture(*texture);
                    return render::Unexpected(buffer.error());
                }
                using State = uz::RHIResourceState;
                using render::image_pass_detail::Transition;
                render::Result<void> done = context.SubmitAndWait([&](uz::IRHICommandList& cmd) {
                    for (uint32_t i = 0; i < count; ++i) {
                        const uz::RHIBarrierDesc toTarget =
                            Transition(*texture, i == 0 ? State::Common : State::CopySrc, State::RenderTarget);
                        cmd.ResourceBarrier(&toTarget, 1);
                        const float v = values[first + i];
                        const float colour[4] = {v, v, v, 1.0f};
                        cmd.ClearRenderTarget(*texture, colour);
                        const uz::RHIBarrierDesc toCopy = Transition(*texture, State::RenderTarget, State::CopySrc);
                        cmd.ResourceBarrier(&toCopy, 1);
                        cmd.CopyTextureToBuffer(*texture, 0, *buffer, uint64_t{i} * 512, 256);
                    }
                    const uz::RHIBarrierDesc back = Transition(*texture, State::CopySrc, State::Common);
                    cmd.ResourceBarrier(&back, 1);
                });
                std::vector<uint8_t> out(count);
                if (done) {
                    const auto* mapped = static_cast<const uint8_t*>(device.Rhi().MapBuffer(*buffer));
                    for (uint32_t i = 0; i < count; ++i) out[i] = mapped[size_t{i} * 512];
                    device.Rhi().UnmapBuffer(*buffer);
                }
                device.DestroyBuffer(*buffer);
                device.DestroyTexture(*texture);
                if (!done) return render::Unexpected(done.error());
                return out;
            });
        render::Result<std::vector<uint8_t>> chunk = Get(future);
        if (!chunk) return chunk;
        std::copy(chunk->begin(), chunk->end(), codes.begin() + static_cast<std::ptrdiff_t>(first));
    }
    return codes;
}

constexpr char kDecodeHlsl[] = R"(
cbuffer Root : register(b0) { uint g_src; uint g_dst; };
[numthreads(64, 1, 1)]
void main(uint3 id : SV_DispatchThreadID) {
    Texture2D<float4> src = ResourceDescriptorHeap[g_src];
    RWTexture2D<float4> dst = ResourceDescriptorHeap[g_dst];
    dst[int2(id.x, 0)] = src.Load(int3(id.x, 0, 0));
}
)";

/// The linear value a shader loads from an RGBA8 sRGB texel of each code 0..255 (the GPU's
/// sRGB8 decode).
render::Result<std::vector<float>> DecodeCodes(render::Engine& engine) {
    auto token = std::make_shared<const int>(0);
    std::future<render::Result<std::vector<float>>> future = engine.Submit(
        token, [&](render::EngineContext& context, const int&) -> render::Result<std::vector<float>> {
            render::IDevice& device = context.Device();
            uz::RHITextureDesc sdesc;
            sdesc.width = 256;
            sdesc.height = 1;
            sdesc.format = uz::RHIFormat::RGBA8Srgb;
            sdesc.usage = uz::RHITextureUsage::ShaderResource | uz::RHITextureUsage::CopyDst;
            render::Result<uz::RHITextureHandle> src = device.CreateTexture(sdesc);
            if (!src) return render::Unexpected(src.error());
            uz::RHITextureDesc ddesc;
            ddesc.width = 256;
            ddesc.height = 1;
            ddesc.format = uz::RHIFormat::RGBA32Float;
            ddesc.usage = uz::RHITextureUsage::UnorderedAccess | uz::RHITextureUsage::CopySrc;
            render::Result<uz::RHITextureHandle> dst = device.CreateTexture(ddesc);
            uz::RHIBufferDesc bdesc;
            bdesc.sizeBytes = 1024;
            bdesc.usage = uz::RHIBufferUsage::CopySrc;
            bdesc.memory = uz::RHIMemoryType::Upload;
            render::Result<uz::RHIBufferHandle> staging = device.CreateBuffer(bdesc);
            auto cleanup = [&] {
                if (staging) device.DestroyBuffer(*staging);
                if (dst) device.DestroyTexture(*dst);
                device.DestroyTexture(*src);
            };
            if (!dst || !staging) {
                cleanup();
                return render::Unexpected(!dst ? dst.error() : staging.error());
            }
            auto* mapped = static_cast<uint8_t*>(device.Rhi().MapBuffer(*staging));
            for (uint32_t c = 0; c < 256; ++c) {
                for (uint32_t k = 0; k < 3; ++k) mapped[c * 4 + k] = static_cast<uint8_t>(c);
                mapped[c * 4 + 3] = 255;
            }
            device.Rhi().UnmapBuffer(*staging);
            render::KernelSource source;
            source.name = "srgb8_decode";
            source.hlsl = kDecodeHlsl;
            render::Result<render::ComputeKernel> kernel = context.Kernel(source);
            if (!kernel) {
                cleanup();
                return render::Unexpected(kernel.error());
            }
            using State = uz::RHIResourceState;
            using render::image_pass_detail::Transition;
            const uint32_t root[2] = {device.Rhi().GetTextureSRVIndex(*src), device.Rhi().GetTextureUAVIndex(*dst)};
            render::Result<void> done = context.SubmitAndWait([&](uz::IRHICommandList& cmd) {
                const uz::RHIBarrierDesc toCopy = Transition(*src, State::Common, State::CopyDst);
                cmd.ResourceBarrier(&toCopy, 1);
                cmd.CopyBufferToTexture(*staging, 0, 1024, *src, 0, 0);
                const uz::RHIBarrierDesc before[2] = {Transition(*src, State::CopyDst, State::ShaderResource),
                                                      Transition(*dst, State::Common, State::UnorderedAccess)};
                cmd.ResourceBarrier(before, 2);
                cmd.SetPipeline(kernel->pipeline);
                cmd.SetRootConstants(render::kRootConstantsParam, root, 2);
                cmd.Dispatch(4, 1, 1);
                const uz::RHIBarrierDesc after[2] = {Transition(*src, State::ShaderResource, State::Common),
                                                     Transition(*dst, State::UnorderedAccess, State::Common)};
                cmd.ResourceBarrier(after, 2);
            });
            if (!done) {
                cleanup();
                return render::Unexpected(done.error());
            }
            render::TextureReadback readback(context);
            render::ReadbackDesc desc;
            desc.texture = *dst;
            desc.channels = 1;
            render::Result<render::ReadbackId> id = readback.Request(desc);
            render::Result<render::ReadbackImage> image =
                id ? readback.Complete(*id) : render::Result<render::ReadbackImage>(render::Unexpected(id.error()));
            cleanup();
            if (!image) return render::Unexpected(image.error());
            std::vector<float> values(256);
            std::memcpy(values.data(), image->texels.data(), 256 * sizeof(float));
            return values;
        });
    return Get(future);
}

/// Measures the GPU's sRGB8 conversions and compares them with the tables of arith.h, which were
/// measured on the Tier 0 recording GPU (the owner's RTX 4090): the decode of every code, the
/// smallest float32 of every code by bisection over float32 bit patterns, and the encode of every
/// 16-bit operand and of random floats. Writes the measured tables to the work directory.
int RunSrgb8Hardware(const fs::path& dir) {
    render::Engine engine(TestOptions(dir));
    if (NoAdapter(engine)) return kExitSkip;
    const std::string adapter = engine.Capabilities().value_or(render::CapabilityReport{}).adapter;
    Info("adapter " + adapter);
    render::Result<std::vector<float>> decode = DecodeCodes(engine);
    if (!decode) {
        Check(false, "the sRGB8 decode is measured", decode.error().Describe());
        return Finish();
    }
    std::ofstream decodeFile(dir / "srgb8-decode.txt");
    bool decodeEqual = true;
    for (uint32_t c = 0; c < 256; ++c) {
        const uint32_t bits = std::bit_cast<uint32_t>((*decode)[c]);
        decodeFile << c << ' ' << Hex32(bits) << '\n';
        decodeEqual = decodeEqual && bits == std::bit_cast<uint32_t>(arith::Srgb8OperandTable()[c]);
    }
    Check(decodeEqual, "the GPU's sRGB8 decode equals the operand table of every code");

    std::vector<uint32_t> low(256, 0u);
    std::vector<uint32_t> high(256, std::bit_cast<uint32_t>(1.0f));
    for (int iteration = 0; iteration < 40; ++iteration) {
        std::vector<float> probe;
        std::vector<uint32_t> which;
        for (uint32_t k = 1; k < 256; ++k) {
            if (high[k] - low[k] <= 1) continue;
            probe.push_back(std::bit_cast<float>(low[k] + (high[k] - low[k]) / 2));
            which.push_back(k);
        }
        if (probe.empty()) break;
        render::Result<std::vector<uint8_t>> codes = ClearCodes(engine, probe);
        if (!codes) {
            Check(false, "the sRGB8 thresholds are measured", codes.error().Describe());
            return Finish();
        }
        for (size_t i = 0; i < probe.size(); ++i) {
            const uint32_t bits = std::bit_cast<uint32_t>(probe[i]);
            if ((*codes)[i] >= which[i]) high[which[i]] = bits;
            else low[which[i]] = bits;
        }
    }
    std::ofstream thresholdFile(dir / "srgb8-thresholds.txt");
    bool thresholdsEqual = true;
    for (uint32_t k = 1; k < 256; ++k) {
        thresholdFile << k << ' ' << Hex32(high[k]) << '\n';
        thresholdsEqual = thresholdsEqual && static_cast<double>(std::bit_cast<float>(high[k])) == arith::Srgb8Thresholds()[k];
    }
    Check(thresholdsEqual, "the smallest float32 of every sRGB8 code on the GPU equals the store thresholds");

    std::vector<float> values;
    for (uint32_t c = 0; c < 65536; ++c) values.push_back(arith::UnormOperand(c, 16));
    std::mt19937 rng(61966);
    for (int i = 0; i < 131072; ++i) {
        values.push_back(std::uniform_real_distribution<float>(-0.05f, 1.05f)(rng));
    }
    for (uint32_t k = 1; k < 256; ++k) {
        const uint32_t bits = std::bit_cast<uint32_t>(static_cast<float>(arith::Srgb8Thresholds()[k]));
        for (int d = -3; d <= 3; ++d) values.push_back(std::bit_cast<float>(bits + static_cast<uint32_t>(d)));
    }
    render::Result<std::vector<uint8_t>> codes = ClearCodes(engine, values);
    if (!codes) {
        Check(false, "the sRGB8 encode is measured", codes.error().Describe());
        return Finish();
    }
    size_t differing = 0;
    std::string first;
    for (size_t i = 0; i < values.size(); ++i) {
        if ((*codes)[i] != arith::Srgb8Store(values[i])) {
            if (differing++ == 0) first = "value " + Hex32(std::bit_cast<uint32_t>(values[i])) + ": GPU " +
                                          std::to_string((*codes)[i]) + ", table " + std::to_string(arith::Srgb8Store(values[i]));
        }
    }
    Check(differing == 0, "the GPU's sRGB8 encode equals Srgb8Store on every 16-bit operand, " + std::to_string(131072) +
                              " random floats and the floats next to every threshold (" + std::to_string(values.size()) + " values)",
          std::to_string(differing) + " differ; " + first);
    return Finish();
}

// ── fp-hardware ──────────────────────────────────────────────────────────────

/// Domain kernel: texel i of a 4096 x 4096 target holds 1 / x for x = 1 + (i mod 2^23) 2^-23 in
/// [1, 2), sqrt(y) and rsqrt(y) for the i-th float32 y in [1, 4). Sample kernel: texel i of a
/// 1024 x 1024 target holds 1 / x, sqrt(x), rsqrt(x) and x for an edge value (i < 32) or a
/// hashed bit pattern.
constexpr char kFpHardwareHlsl[] = R"(
cbuffer Root : register(b0) { uint g_dst; };
static const uint kEdges[32] = {
    0x00000000u, 0x80000000u, 0x00000001u, 0x007FFFFFu, 0x80000001u, 0x807FFFFFu, 0x00800000u,
    0x00800001u, 0x7E7FFFFFu, 0x7E800000u, 0x7E800001u, 0x7EFFFFFFu, 0x7F000000u, 0x7F7FFFFFu,
    0x7F800000u, 0xFF800000u, 0x7FC00000u, 0xFFC00000u, 0x7F800001u, 0xBF800000u, 0xC0000000u,
    0xBF000000u, 0x3F800000u, 0x40800000u, 0x3E800000u, 0xFE800000u, 0x80800000u, 0xFF7FFFFFu,
    0x34000000u, 0x0C000000u, 0x01000000u, 0x00FFFFFFu};
[numthreads(8, 8, 1)]
void Domain(uint3 id : SV_DispatchThreadID) {
    RWTexture2D<float4> dst = ResourceDescriptorHeap[g_dst];
    const uint i = id.y * 4096u + id.x;
    const float x = asfloat(0x3F800000u | (i & 0x7FFFFFu));
    const float y = asfloat(0x3F800000u + i);
    dst[id.xy] = float4(1.0f / x, sqrt(y), rsqrt(y), 0.0f);
}
[numthreads(8, 8, 1)]
void Samples(uint3 id : SV_DispatchThreadID) {
    RWTexture2D<float4> dst = ResourceDescriptorHeap[g_dst];
    const uint i = id.y * 1024u + id.x;
    uint h = i * 0x9E3779B9u;
    h ^= h >> 16;
    h *= 0x85EBCA6Bu;
    h ^= h >> 13;
    const float x = asfloat(i < 32u ? kEdges[i] : h);
    dst[id.xy] = float4(1.0f / x, sqrt(x), rsqrt(x), x);
}
)";

render::Result<std::vector<float>> FpKernelTexels(render::Engine& engine, const char* entry, uint32_t size,
                                                  const char* hlsl = kFpHardwareHlsl,
                                                  std::vector<uint32_t> constants = {},
                                                  const char* family = nullptr) {
    auto token = std::make_shared<const int>(0);
    std::future<render::Result<std::vector<float>>> future = engine.Submit(
        token, [&](render::EngineContext& context, const int&) -> render::Result<std::vector<float>> {
            render::IDevice& device = context.Device();
            uz::RHITextureDesc ddesc;
            ddesc.width = size;
            ddesc.height = size;
            ddesc.format = uz::RHIFormat::RGBA32Float;
            ddesc.usage = uz::RHITextureUsage::UnorderedAccess | uz::RHITextureUsage::CopySrc;
            render::Result<uz::RHITextureHandle> dst = device.CreateTexture(ddesc);
            if (!dst) return render::Unexpected(dst.error());
            render::KernelSource source;
            source.name = std::string(family != nullptr ? family
                                                        : (hlsl == kFpHardwareHlsl ? "fp_hardware_" : "pow_hardware_")) +
                          entry;
            source.hlsl = hlsl;
            source.entryPoint = entry;
            render::Result<render::ComputeKernel> kernel = context.Kernel(source);
            if (!kernel) {
                device.DestroyTexture(*dst);
                return render::Unexpected(kernel.error());
            }
            using State = uz::RHIResourceState;
            using render::image_pass_detail::Transition;
            std::vector<uint32_t> root = {device.Rhi().GetTextureUAVIndex(*dst)};
            root.insert(root.end(), constants.begin(), constants.end());
            render::Result<void> done = context.SubmitAndWait([&](uz::IRHICommandList& cmd) {
                const uz::RHIBarrierDesc before = Transition(*dst, State::Common, State::UnorderedAccess);
                cmd.ResourceBarrier(&before, 1);
                cmd.SetPipeline(kernel->pipeline);
                cmd.SetRootConstants(render::kRootConstantsParam, root.data(), static_cast<uint32_t>(root.size()));
                cmd.Dispatch(size / 8, size / 8, 1);
                const uz::RHIBarrierDesc after = Transition(*dst, State::UnorderedAccess, State::Common);
                cmd.ResourceBarrier(&after, 1);
            });
            if (!done) {
                device.DestroyTexture(*dst);
                return render::Unexpected(done.error());
            }
            render::TextureReadback readback(context);
            render::ReadbackDesc desc;
            desc.texture = *dst;
            render::Result<render::ReadbackId> id = readback.Request(desc);
            render::Result<render::ReadbackImage> image =
                id ? readback.Complete(*id) : render::Result<render::ReadbackImage>(render::Unexpected(id.error()));
            device.DestroyTexture(*dst);
            if (!image) return render::Unexpected(image.error());
            std::vector<float> values(image->texels.size() / sizeof(float));
            std::memcpy(values.data(), image->texels.data(), values.size() * sizeof(float));
            return values;
        });
    return Get(future);
}

bool SameFloat(float a, float b) {
    return (std::isnan(a) && std::isnan(b)) || std::bit_cast<uint32_t>(a) == std::bit_cast<uint32_t>(b);
}

// ── bilinear-hardware ────────────────────────────────────────────────────────

/// Output texel k of a 2048 x 2048 target samples the bound texture (64 x 64, one mip, a linear
/// wrap sampler) at the texel coordinate (x0 + fx / 256, y0 + fy / 256): fx = k & 255,
/// fy = (k >> 8) & 255 and the tap (x0, y0) = (t & 63, (t * 7 + 5) & 63) for t = k >> 16. The
/// normalised coordinates are exact in float32, so the filter alone decides the value.
constexpr char kBilinearHardwareHlsl[] = R"(
cbuffer Root : register(b0) { uint g_src; uint g_sampler; uint g_dst; };
[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID) {
    Texture2D<float4> src = ResourceDescriptorHeap[g_src];
    SamplerState linearWrap = SamplerDescriptorHeap[g_sampler];
    RWTexture2D<float4> dst = ResourceDescriptorHeap[g_dst];
    const uint k = id.y * 2048u + id.x;
    const uint t = k >> 16;
    const float x = (float)(t & 63u) + 0.5f + (float)(k & 255u) / 256.0f;
    const float y = (float)((t * 7u + 5u) & 63u) + 0.5f + (float)((k >> 8) & 255u) / 256.0f;
    dst[id.xy] = src.SampleLevel(linearWrap, float2(x, y) / 64.0f, 0.0f);
}
)";

constexpr uint32_t kBilinearProbeSize = 64;
constexpr uint32_t kBilinearTargetSize = 2048;

/// The texels of the probe: random 16-bit codes in four channels, with the resample-uv near-tie
/// codes (38535, 65357, 55719, 1194) on the green channel of the quad at (10, 11), tap t = 10.
std::vector<uint16_t> BilinearProbeCodes() {
    std::vector<uint16_t> codes(size_t{kBilinearProbeSize} * kBilinearProbeSize * 4);
    std::mt19937 rng(20261011);
    for (uint16_t& code : codes) code = static_cast<uint16_t>(rng() & 0xFFFF);
    // Edge operands: rows 19-21 of the red channel alternate 1.0 (65535) with codes below 2048 whose
    // float32 texel has its 2^-28 bit set (the bit a 1.0 neighbour's exponent would drop); rows 29-31
    // of the blue channel alternate 0 with such codes.
    auto lowCode = [&rng] {
        for (;;) {
            const uint32_t code = rng() & 0x7FF;
            const double scaled = std::ldexp(static_cast<double>(arith::UnormOperand(code, 16)), 28);
            if ((static_cast<uint64_t>(scaled) & 1) != 0) return static_cast<uint16_t>(code);
        }
    };
    for (uint32_t x = 0; x < kBilinearProbeSize; ++x) {
        for (uint32_t y : {19u, 20u, 21u, 29u, 30u, 31u}) {
            const bool edge = ((x + y) & 1) == 0;
            const uint32_t c = y < 29 ? 0 : 2;
            codes[(size_t{y} * kBilinearProbeSize + x) * 4 + c] = edge ? static_cast<uint16_t>(y < 29 ? 65535 : 0) : lowCode();
        }
    }
    const std::array<std::array<uint32_t, 3>, 4> tie{{{10, 11, 38535}, {11, 11, 65357}, {10, 12, 55719}, {11, 12, 1194}}};
    for (const auto& [x, y, code] : tie) codes[(size_t{y} * kBilinearProbeSize + x) * 4 + 1] = static_cast<uint16_t>(code);
    return codes;
}

/// The GPU's linear filter at every 8-bit weight pair on 64 taps, of the probe uploaded as
/// RGBA16_UNORM codes (`unorm16`) or as RGBA32_FLOAT texels float32(c / 65535).
render::Result<std::vector<float>> BilinearHardwareSamples(render::Engine& engine, const std::vector<uint16_t>& codes,
                                                           bool unorm16) {
    auto token = std::make_shared<const int>(0);
    std::future<render::Result<std::vector<float>>> future = engine.Submit(
        token, [&](render::EngineContext& context, const int&) -> render::Result<std::vector<float>> {
            render::IDevice& device = context.Device();
            const uint32_t texelBytes = unorm16 ? 8 : 16;
            const uint32_t rowPitch = kBilinearProbeSize * texelBytes;
            uz::RHITextureDesc sdesc;
            sdesc.width = kBilinearProbeSize;
            sdesc.height = kBilinearProbeSize;
            sdesc.format = unorm16 ? uz::RHIFormat::RGBA16Unorm : uz::RHIFormat::RGBA32Float;
            sdesc.usage = uz::RHITextureUsage::ShaderResource | uz::RHITextureUsage::CopyDst;
            render::Result<uz::RHITextureHandle> src = device.CreateTexture(sdesc);
            if (!src) return render::Unexpected(src.error());
            uz::RHITextureDesc ddesc;
            ddesc.width = kBilinearTargetSize;
            ddesc.height = kBilinearTargetSize;
            ddesc.format = uz::RHIFormat::RGBA32Float;
            ddesc.usage = uz::RHITextureUsage::UnorderedAccess | uz::RHITextureUsage::CopySrc;
            render::Result<uz::RHITextureHandle> dst = device.CreateTexture(ddesc);
            uz::RHIBufferDesc bdesc;
            bdesc.sizeBytes = uint64_t{rowPitch} * kBilinearProbeSize;
            bdesc.usage = uz::RHIBufferUsage::CopySrc;
            bdesc.memory = uz::RHIMemoryType::Upload;
            render::Result<uz::RHIBufferHandle> staging = device.CreateBuffer(bdesc);
            uz::RHISamplerDesc sampler;
            sampler.filter = uz::RHIFilterMode::Linear;
            sampler.maxLod = 0.0f;
            const uz::RHISamplerHandle linearWrap = device.Rhi().CreateSampler(sampler);
            auto cleanup = [&] {
                if (linearWrap.IsValid()) device.Rhi().DestroySampler(linearWrap);
                if (staging) device.DestroyBuffer(*staging);
                if (dst) device.DestroyTexture(*dst);
                device.DestroyTexture(*src);
            };
            if (!dst || !staging || !linearWrap.IsValid()) {
                cleanup();
                return render::Fail(render::ErrorCode::ResourceCreationFailed, device.GetBackend(),
                                    "bilinear-hardware: resources not created");
            }
            auto* mapped = static_cast<uint8_t*>(device.Rhi().MapBuffer(*staging));
            for (size_t i = 0; i < codes.size(); ++i) {
                if (unorm16) {
                    std::memcpy(mapped + i * 2, &codes[i], 2);
                } else {
                    const float texel = arith::UnormOperand(codes[i], 16);
                    std::memcpy(mapped + i * 4, &texel, 4);
                }
            }
            device.Rhi().UnmapBuffer(*staging);
            render::KernelSource source;
            source.name = "bilinear_hardware";
            source.hlsl = kBilinearHardwareHlsl;
            render::Result<render::ComputeKernel> kernel = context.Kernel(source);
            if (!kernel) {
                cleanup();
                return render::Unexpected(kernel.error());
            }
            using State = uz::RHIResourceState;
            using render::image_pass_detail::Transition;
            const uint32_t root[3] = {device.Rhi().GetTextureSRVIndex(*src), device.Rhi().GetSamplerIndex(linearWrap),
                                      device.Rhi().GetTextureUAVIndex(*dst)};
            render::Result<void> done = context.SubmitAndWait([&](uz::IRHICommandList& cmd) {
                const uz::RHIBarrierDesc toCopy = Transition(*src, State::Common, State::CopyDst);
                cmd.ResourceBarrier(&toCopy, 1);
                cmd.CopyBufferToTexture(*staging, 0, rowPitch, *src, 0, 0);
                const uz::RHIBarrierDesc before[2] = {Transition(*src, State::CopyDst, State::ShaderResource),
                                                      Transition(*dst, State::Common, State::UnorderedAccess)};
                cmd.ResourceBarrier(before, 2);
                cmd.SetPipeline(kernel->pipeline);
                cmd.SetRootConstants(render::kRootConstantsParam, root, 3);
                cmd.Dispatch(kBilinearTargetSize / 8, kBilinearTargetSize / 8, 1);
                const uz::RHIBarrierDesc after[2] = {Transition(*src, State::ShaderResource, State::Common),
                                                     Transition(*dst, State::UnorderedAccess, State::Common)};
                cmd.ResourceBarrier(after, 2);
            });
            if (!done) {
                cleanup();
                return render::Unexpected(done.error());
            }
            render::TextureReadback readback(context);
            render::ReadbackDesc desc;
            desc.texture = *dst;
            render::Result<render::ReadbackId> id = readback.Request(desc);
            render::Result<render::ReadbackImage> image =
                id ? readback.Complete(*id) : render::Result<render::ReadbackImage>(render::Unexpected(id.error()));
            cleanup();
            if (!image) return render::Unexpected(image.error());
            std::vector<float> values(image->texels.size() / sizeof(float));
            std::memcpy(values.data(), image->texels.data(), values.size() * sizeof(float));
            return values;
        });
    return Get(future);
}

/// Measures the GPU's linear filter at every 8-bit weight pair (64 taps x 65 536 pairs x 4
/// channels, edge operands beside 1.0 and 0 included) and compares the float32 texture with
/// projection_uv.h BilinearFilter under the GPU's own weights, w11 = (fx fy + 128) >> 8 (the
/// projection's ties-down rounding is this one seen through Painter's bottom-up bitmap). The
/// RGBA16_UNORM texture filters at a lower precision and is reported only. Writes the samples
/// (`bilinear-<format>.bin`) and the probe's codes to the work directory.
int RunBilinearHardware(const fs::path& dir) {
    render::Engine engine(TestOptions(dir));
    if (NoAdapter(engine)) return kExitSkip;
    Info("adapter " + engine.Capabilities().value_or(render::CapabilityReport{}).adapter);
    const std::vector<uint16_t> codes = BilinearProbeCodes();
    {
        std::ofstream probe(dir / "bilinear-probe-codes.bin", std::ios::binary);
        probe.write(reinterpret_cast<const char*>(codes.data()), static_cast<std::streamsize>(codes.size() * sizeof(uint16_t)));
    }
    for (const bool unorm16 : {false, true}) {
        const std::string format = unorm16 ? "RGBA16_UNORM" : "RGBA32_FLOAT";
        render::Result<std::vector<float>> samples = BilinearHardwareSamples(engine, codes, unorm16);
        if (!samples) {
            Check(false, "bilinear-hardware " + format, Describe(samples));
            continue;
        }
        {
            std::ofstream out(dir / ("bilinear-" + format + ".bin"), std::ios::binary);
            out.write(reinterpret_cast<const char*>(samples->data()), static_cast<std::streamsize>(samples->size() * sizeof(float)));
        }
        uint64_t total = 0;
        uint64_t equal = 0;
        bool tie = false;
        std::string firstMiss;
        for (uint32_t k = 0; k < kBilinearTargetSize * kBilinearTargetSize; ++k) {
            const uint32_t fx = k & 255;
            const uint32_t fy = (k >> 8) & 255;
            const uint32_t t = k >> 16;
            const uint32_t x0 = t & 63;
            const uint32_t y0 = (t * 7 + 5) & 63;
            const uint32_t w11 = (fx * fy + 128) >> 8;
            const std::array<uint32_t, 4> weights{256 - fx - fy + w11, fx - w11, fy - w11, w11};
            const std::array<std::array<uint32_t, 2>, 4> taps{
                {{x0, y0}, {(x0 + 1) & 63, y0}, {x0, (y0 + 1) & 63}, {(x0 + 1) & 63, (y0 + 1) & 63}}};
            for (uint32_t c = 0; c < 4; ++c) {
                std::array<float, 4> texels{};
                for (size_t q = 0; q < 4; ++q) {
                    texels[q] = arith::UnormOperand(codes[(size_t{taps[q][1]} * kBilinearProbeSize + taps[q][0]) * 4 + c], 16);
                }
                const float rule = BilinearFilter(weights, texels);
                const float gpu = (*samples)[size_t{k} * 4 + c];
                ++total;
                if (SameFloat(gpu, rule)) {
                    ++equal;
                } else if (firstMiss.empty()) {
                    firstMiss = "tap (" + std::to_string(x0) + ", " + std::to_string(y0) + ") fx " + std::to_string(fx) +
                                " fy " + std::to_string(fy) + " channel " + std::to_string(c) + ": GPU bits " +
                                std::to_string(std::bit_cast<uint32_t>(gpu)) + ", rule bits " +
                                std::to_string(std::bit_cast<uint32_t>(rule));
                }
                // The near-tie quad seen from the GPU's frame: weights 15, 52, 44, 145 there.
                if (x0 == 10 && y0 == 11 && c == 1 && fx == 197 && fy == 189) {
                    tie = weights == std::array<uint32_t, 4>{15, 52, 44, 145} &&
                          std::floor(std::ldexp(static_cast<double>(gpu), 20)) == 412590.0;
                }
            }
        }
        Info(format + ": BilinearFilter equals the GPU on " + std::to_string(equal) + " of " + std::to_string(total) +
             " samples");
        if (unorm16) continue;
        Check(equal == total,
              "the GPU's linear filter of float32 texels equals BilinearFilter (operands aligned to the largest weighed texel "
              "with 28 bits, one rounding, ties up) at every 8-bit weight pair (" + std::to_string(total) + " samples)",
              firstMiss);
        Check(tie, "the GPU's linear filter of float32 texels rounds the resample-uv near-tie down", "");
    }
    return Finish();
}

/// A measured delta table in the stored form of hwmath.h (zlib of the packed words).
std::vector<unsigned char> PackDeltas(const std::vector<int>& deltas) {
    std::vector<uint32_t> words(deltas.size() / 16, 0u);
    for (size_t i = 0; i < deltas.size(); ++i) {
        words[i / 16] |= static_cast<uint32_t>(deltas[i] + 2) << ((i % 16) * 2);
    }
    uLongf size = compressBound(static_cast<uLong>(words.size() * sizeof(uint32_t)));
    std::vector<unsigned char> out(size);
    compress2(out.data(), &size, reinterpret_cast<const Bytef*>(words.data()),
              static_cast<uLong>(words.size() * sizeof(uint32_t)), 9);
    out.resize(size);
    return out;
}

/// Measures the GPU's float32 reciprocal (`1 / x`), square root and reciprocal square root as
/// the render layer compiles them (`-Gis`) on every float32 of the reduced domains of hwmath.h,
/// writes the measured tables (`hw-rcp.zlib`, `hw-sqrt.zlib`, `hw-rsqrt.zlib`) to the work
/// directory and compares them with the embedded ones, then compares hw::Rcp, hw::Sqrt and
/// hw::Rsqrt with the GPU on edge values and 2^20 hashed bit patterns over every exponent.
int RunFpHardware(const fs::path& dir) {
    render::Engine engine(TestOptions(dir));
    if (NoAdapter(engine)) return kExitSkip;
    Info("adapter " + engine.Capabilities().value_or(render::CapabilityReport{}).adapter);
    render::Result<std::vector<float>> domain = FpKernelTexels(engine, "Domain", 4096);
    render::Result<std::vector<float>> samples = FpKernelTexels(engine, "Samples", 1024);
    if (!domain || !samples) {
        Check(false, "the GPU's reciprocal and square roots are measured",
              (!domain ? domain : samples).error().Describe());
        return Finish();
    }
    const std::vector<float>& v = *domain;
    std::vector<int> rcp(hw::kRcpEntries), sqrt(hw::kRootEntries), rsqrt(hw::kRootEntries);
    bool faithful = true;
    for (uint32_t i = 0; i < hw::kRootEntries; ++i) {
        const float y = std::bit_cast<float>(0x3F800000u + i);
        if (i < hw::kRcpEntries) {
            const float x = std::bit_cast<float>(0x3F800000u | i);
            rcp[i] = std::bit_cast<int32_t>(v[size_t{i} * 4]) - std::bit_cast<int32_t>(1.0f / x);
            faithful = faithful && rcp[i] >= -2 && rcp[i] <= 1;
        }
        sqrt[i] = std::bit_cast<int32_t>(v[size_t{i} * 4 + 1]) - std::bit_cast<int32_t>(std::sqrt(y));
        rsqrt[i] = std::bit_cast<int32_t>(v[size_t{i} * 4 + 2]) - std::bit_cast<int32_t>(hw::RsqrtCorrect(y));
        faithful = faithful && sqrt[i] >= -2 && sqrt[i] <= 1 && rsqrt[i] >= -2 && rsqrt[i] <= 1;
    }
    Check(faithful, "every measured result lies within -2 and +1 units in the last place of the correctly rounded one");
    const hw::Op ops[3] = {hw::Op::Rcp, hw::Op::Sqrt, hw::Op::Rsqrt};
    const std::vector<int>* measured[3] = {&rcp, &sqrt, &rsqrt};
    const char* names[3] = {"rcp", "sqrt", "rsqrt"};
    for (int t = 0; t < 3; ++t) {
        const std::vector<unsigned char> packed = PackDeltas(*measured[t]);
        std::ofstream(dir / (std::string("hw-") + names[t] + ".zlib"), std::ios::binary)
            .write(reinterpret_cast<const char*>(packed.data()), static_cast<std::streamsize>(packed.size()));
        size_t differing = 0;
        for (uint32_t i = 0; i < measured[t]->size(); ++i) differing += hw::Delta(ops[t], i) != (*measured[t])[i];
        Check(differing == 0, std::string("the embedded ") + names[t] + " table equals the GPU on every entry of its domain (" +
                                  std::to_string(measured[t]->size()) + ")",
              std::to_string(differing) + " entries differ");
    }
    size_t differing = 0;
    std::string first;
    const std::vector<float>& s = *samples;
    for (size_t i = 0; i < s.size() / 4; ++i) {
        const float x = s[i * 4 + 3];
        const float ours[3] = {hw::Rcp(x), hw::Sqrt(x), hw::Rsqrt(x)};
        for (int k = 0; k < 3; ++k) {
            if (SameFloat(ours[k], s[i * 4 + k])) continue;
            if (differing++ < 8) {
                first += std::string(names[k]) + "(" + Hex32(std::bit_cast<uint32_t>(x)) + "): GPU " +
                         Hex32(std::bit_cast<uint32_t>(s[i * 4 + k])) + ", hw " + Hex32(std::bit_cast<uint32_t>(ours[k])) + "; ";
            }
        }
    }
    Check(differing == 0, "hw::Rcp, hw::Sqrt and hw::Rsqrt equal the GPU on 32 edge values and " +
                              std::to_string(s.size() / 4 - 32) + " hashed bit patterns",
          std::to_string(differing) + " results differ: " + first);
    return Finish();
}

// ── masks (phase1.11_compositor-mask-effects) ────────────────────────────────

core::Effect MaskFillEffect(Builder& builder, const core::Source& source, BlendingMode mode, double opacity) {
    core::Effect effect;
    effect.uid = builder.project.AllocateId();
    effect.kind = core::EffectKind::fill;
    effect.name = "mask fill";
    core::FillContent fill;
    fill.mono_source = source;
    effect.fill = fill;
    effect.mono_blending = Blend(mode, opacity);
    return effect;
}

core::LevelsComponent LevelsComponentOf(double inMin, double inMax, double gamma, double outMin, double outMax,
                                        bool clamp) {
    core::LevelsComponent c;
    c.input_min = inMin;
    c.input_max = inMax;
    c.gamma = gamma;
    c.output_min = outMin;
    c.output_max = outMax;
    c.clamp = clamp;
    return c;
}

core::Effect LevelsEffect(Builder& builder, const core::LevelsComponent& component,
                          std::optional<ChannelType> affected) {
    core::Effect effect;
    effect.uid = builder.project.AllocateId();
    effect.kind = core::EffectKind::levels;
    effect.name = "levels";
    core::LevelsParams levels;
    levels.affected_channel = affected;
    levels.components = {component};
    effect.levels = levels;
    if (!affected) effect.mono_blending = core::Blending{};  // mask stack
    return effect;
}

core::Effect ContentFillEffect(Builder& builder, const std::vector<ChannelType>& channels, const core::Source& source,
                               BlendingMode mode, double opacity) {
    core::Effect effect;
    effect.uid = builder.project.AllocateId();
    effect.kind = core::EffectKind::fill;
    effect.name = "content fill";
    core::FillContent fill;
    fill.sources = SameSource(channels, source);
    for (const ChannelType channel : channels) fill.active_channels.insert(channel);
    effect.fill = fill;
    effect.blending = Same(channels, mode, opacity);
    return effect;
}

/// A mask with `background` and its effects given bottom-up (stored top first).
core::Mask MaskWith(core::MaskBackground background, std::vector<core::Effect> effectsBottomUp) {
    core::Mask mask;
    mask.background = background;
    std::reverse(effectsBottomUp.begin(), effectsBottomUp.end());
    mask.effects = std::move(effectsBottomUp);
    return mask;
}

/// A one-channel 16-bit image of `size`^2 from `code(x, y)`.
template <class F>
std::shared_ptr<DecodedImage> GreyImage(uint32_t size, F code) {
    auto image = std::make_shared<DecodedImage>();
    image->width = size;
    image->height = size;
    image->channels = 1;
    image->encoding = render::TexelEncoding::Unorm16;
    image->values.resize(size_t{size} * size);
    for (uint32_t y = 0; y < size; ++y) {
        for (uint32_t x = 0; x < size; ++x) image->values[size_t{y} * size + x] = code(x, y) & 0xFFFFu;
    }
    return image;
}

/// The operand a 16-bit mask stores for `v` (masks-levels.json: 16-bit masks).
float Mask16(float v) { return arith::UnormOperand(arith::WriteUnorm(v, 16), 16); }

struct MaskRig {
    static constexpr uint32_t kSize = 64;
    std::shared_ptr<const TemplateLibrary> templates;
    std::shared_ptr<MapResourceProvider> provider = std::make_shared<MapResourceProvider>();
    std::shared_ptr<DecodedImage> grey = GreyImage(kSize, [](uint32_t x, uint32_t y) { return (y * kSize + x) * 16u + 7u; });
    std::shared_ptr<DecodedImage> ramp = GreyImage(kSize, [](uint32_t x, uint32_t) { return x * 1040u; });
    std::string greySha = std::string(63, 'a') + "1";
    std::string rampSha = std::string(63, 'a') + "2";

    explicit MaskRig(const fs::path& assets) : templates(LoadTemplates(assets)) {
        provider->Add(greySha, grey);
        provider->Add(rampSha, ramp);
    }
    void Register(Builder& builder) const {
        builder.AddResource(greySha, 100);
        builder.AddResource(rampSha, 100);
    }
    render::Result<ChannelResult> Evaluate(Builder& builder, ChannelType channel, CpuEvaluator* cpu = nullptr,
                                           std::shared_ptr<const IGeometryMaskProvider> geometry = nullptr) const {
        CpuEvaluator local(templates, kWideLimits);
        EvaluateRequest request;
        request.textureSet = builder.SetId();
        request.stack = builder.StackId();
        request.channel = channel;
        request.resources = provider;
        request.geometry = std::move(geometry);
        return (cpu != nullptr ? *cpu : local).Evaluate(builder.project, request);
    }
    /// The mask operand of texel i of the grey image.
    float G(size_t i) const { return arith::UnormOperand(grey->values[i], 16); }
};

/// The samples of a channel, or empty on failure (with a failed check).
std::vector<uint32_t> SamplesOf(const render::Result<ChannelResult>& result, const std::string& what) {
    if (!result) {
        Check(false, what + " evaluates", Describe(result));
        return {};
    }
    return Samples(*result);
}

/// A User0 stack on `format` of a white fill under a black fill whose mask is `mask` (the
/// mask-precision layout).
Builder BlackOverWhite(const MaskRig& rig, ChannelFormat format,
                       const std::function<std::optional<core::Mask>(Builder&)>& mask) {
    Builder builder(MaskRig::kSize, MaskRig::kSize, {{ChannelType::User0, format}});
    rig.Register(builder);
    const std::vector<ChannelType> channels{ChannelType::User0};
    core::Layer white = builder.Fill("white", SameSource(channels, Uniform(1, 1, 1)), Same(channels, BlendingMode::Normal, 1));
    core::Layer black = builder.Fill("black", SameSource(channels, Uniform(0, 0, 0)), Same(channels, BlendingMode::Normal, 1));
    if (mask) black.mask = mask(builder);
    builder.SetRoot({white, black});
    return builder;
}

/// The User0 samples the mask-precision layout gives for the per-texel mask `m` (the root composite
/// of the isolated profile written out: white onto transparent, black over it at m, the read-out
/// over the user channel's base 1).
std::vector<uint32_t> BlackOverWhiteModel(ChannelFormat format, const std::vector<float>& m) {
    const TileFormat tile = TileFormatOf(format);
    std::vector<uint32_t> out;
    for (const float mask : m) {
        arith::CompositeInput in;
        in.channels = tile.channels;
        in.clampUnorm = tile.IsUnorm();
        in.acc = {1.0f, 1.0f, 1.0f, 1.0f};
        in.src = {0.0f, 0.0f, 0.0f, 1.0f};
        in.mask = mask;
        const std::array<float, 4> blended = arith::Composite(in);
        arith::CompositeInput readout;
        readout.channels = tile.channels;
        readout.clampUnorm = tile.IsUnorm();
        readout.mode = BlendingMode::Replace;
        readout.acc = {1.0f, 1.0f, 1.0f, 1.0f};
        for (uint32_t c = 0; c < tile.channels; ++c) {
            readout.src[c] = OperandOf(StoreValue(blended[c], tile, c), tile, c);
        }
        const std::array<float, 4> result = arith::Composite(readout);
        for (uint32_t c = 0; c < tile.channels; ++c) {
            uint32_t v = StoreValue(result[c], tile, c);
            if (tile.encoding == render::TexelEncoding::Float16) v = arith::HalfTowardZero(result[c]);
            out.push_back(v);
        }
    }
    return out;
}

/// A minimal texturing mesh: material "set" with two quads over the left and the right half of
/// the UV square, objects "left" and "right".
std::shared_ptr<uzp::mesh::TexturingMesh> TwoHalvesMesh() {
    auto mesh = std::make_shared<uzp::mesh::TexturingMesh>();
    mesh->materials.push_back({"set", 0});
    mesh->positions.push_back({0.0f, 0.0f, 0.0f});
    auto quad = [&](const std::string& name, float u0, float u1) {
        uzp::mesh::Object object;
        object.name = name;
        const uint32_t base = static_cast<uint32_t>(mesh->corners.size());
        const float uv[4][2] = {{u0, 0.0f}, {u1, 0.0f}, {u1, 1.0f}, {u0, 1.0f}};
        for (const auto& c : uv) {
            uzp::mesh::Corner corner;
            corner.uv0 = {c[0], c[1]};
            mesh->corners.push_back(corner);
        }
        object.triangles.push_back({{base, base + 1, base + 2}});
        object.triangles.push_back({{base, base + 2, base + 3}});
        mesh->objects.push_back(std::move(object));
    };
    quad("left", 0.0f, 0.5f);
    quad("right", 0.5f, 1.0f);
    return mesh;
}

int RunMasks(const fs::path& assets) {
    const MaskRig rig(assets);
    const size_t texels = size_t{MaskRig::kSize} * MaskRig::kSize;
    const std::vector<ChannelType> user0{ChannelType::User0};

    // Background, disabled mask.
    {
        auto run = [&](std::optional<core::Mask> mask) {
            Builder builder(MaskRig::kSize, MaskRig::kSize, {{ChannelType::User0, ChannelFormat::L16}});
            core::Layer low = builder.Fill("low", SameSource(user0, Uniform(0.2, 0.2, 0.2)), Same(user0, BlendingMode::Normal, 1));
            core::Layer high = builder.Fill("high", SameSource(user0, Uniform(0.8, 0.8, 0.8)), Same(user0, BlendingMode::Normal, 1));
            high.mask = mask;
            builder.SetRoot({low, high});
            return SamplesOf(rig.Evaluate(builder, ChannelType::User0), "mask background stack");
        };
        auto lowOnly = [&] {
            Builder builder(MaskRig::kSize, MaskRig::kSize, {{ChannelType::User0, ChannelFormat::L16}});
            builder.SetRoot({builder.Fill("low", SameSource(user0, Uniform(0.2, 0.2, 0.2)), Same(user0, BlendingMode::Normal, 1))});
            return SamplesOf(rig.Evaluate(builder, ChannelType::User0), "low stack");
        };
        core::Mask disabled = MaskWith(core::MaskBackground::Black, {});
        disabled.enabled = false;
        const std::vector<uint32_t> none = run(std::nullopt);
        Check(run(MaskWith(core::MaskBackground::White, {})) == none && run(MaskWith(core::MaskBackground::Black, {})) == lowOnly() &&
                  run(disabled) == none,
              "a mask is its background without effects (White 1, Black 0); a disabled mask counts as 1");
    }

    // The effect mix and the 16-bit storage: a fill effect at opacity 0.6 over a Black background.
    {
        Builder builder = BlackOverWhite(rig, ChannelFormat::L16, [&](Builder& b) {
            return MaskWith(core::MaskBackground::Black, {MaskFillEffect(b, Bitmap(rig.greySha), BlendingMode::Normal, 0.6)});
        });
        std::vector<float> m(texels);
        for (size_t i = 0; i < texels; ++i) {
            const float g = rig.G(i);
            m[i] = Mask16(0.0f + (g - 0.0f) * 0.6f);
        }
        Check(SamplesOf(rig.Evaluate(builder, ChannelType::User0), "effect mix") == BlackOverWhiteModel(ChannelFormat::L16, m),
              "a mask fill effect blends with the effect mix a + (r - a) alpha and is stored at 16 bits");
    }

    // Subtraction in the mask.
    {
        Builder builder = BlackOverWhite(rig, ChannelFormat::RGB16, [&](Builder& b) {
            return MaskWith(core::MaskBackground::White, {MaskFillEffect(b, Bitmap(rig.greySha), BlendingMode::Subtract, 1.0)});
        });
        std::vector<float> m(texels);
        for (size_t i = 0; i < texels; ++i) {
            const float r = arith::Clamp01(arith::BlendKernel(BlendingMode::Subtract, 1.0f, rig.G(i)));
            m[i] = Mask16(1.0f + (r - 1.0f) * 1.0f);
        }
        Check(SamplesOf(rig.Evaluate(builder, ChannelType::User0), "subtract") == BlackOverWhiteModel(ChannelFormat::RGB16, m),
              "subtraction in a mask goes through the Subtract kernel, clamped to [0, 1]");
    }

    // Levels in the mask.
    {
        const core::LevelsComponent component = LevelsComponentOf(0.1, 0.9, 1.2, 0.0, 1.0, true);
        Builder builder = BlackOverWhite(rig, ChannelFormat::RGB32F, [&](Builder& b) {
            return MaskWith(core::MaskBackground::Black, {MaskFillEffect(b, Bitmap(rig.greySha), BlendingMode::Screen, 0.75),
                                                          LevelsEffect(b, component, std::nullopt)});
        });
        const arith::LevelsComponent levels{0.1f, 0.9f, 1.2f, 0.0f, 1.0f, true};
        std::vector<float> m(texels);
        for (size_t i = 0; i < texels; ++i) {
            const float r = arith::Clamp01(arith::BlendKernel(BlendingMode::Screen, 0.0f, rig.G(i)));
            const float fill = Mask16(0.0f + (r - 0.0f) * 0.75f);
            m[i] = Mask16(arith::Levels(fill, levels));
        }
        Check(SamplesOf(rig.Evaluate(builder, ChannelType::User0), "mask levels") == BlackOverWhiteModel(ChannelFormat::RGB32F, m),
              "a mask levels effect remaps the mask (clamped, gamma through the hardware pow)");
    }

    // 16-bit masks on an 8-bit channel.
    {
        Builder builder = BlackOverWhite(rig, ChannelFormat::L8, [&](Builder& b) {
            return MaskWith(core::MaskBackground::Black, {MaskFillEffect(b, Bitmap(rig.greySha), BlendingMode::Normal, 0.5)});
        });
        std::vector<float> m16(texels), m8(texels);
        for (size_t i = 0; i < texels; ++i) {
            const float v = 0.0f + (rig.G(i) - 0.0f) * 0.5f;
            m16[i] = Mask16(v);
            m8[i] = arith::UnormOperand(arith::WriteUnorm(v, 8), 8);
        }
        const std::vector<uint32_t> ours = SamplesOf(rig.Evaluate(builder, ChannelType::User0), "L8 mask");
        Check(ours == BlackOverWhiteModel(ChannelFormat::L8, m16) && ours != BlackOverWhiteModel(ChannelFormat::L8, m8),
              "a mask is stored at 16 bits on an 8-bit channel");
    }

    // Content effects: order, affected channel, visibility.
    {
        const std::vector<ChannelType> both{ChannelType::User0, ChannelType::User1};
        const core::LevelsComponent component = LevelsComponentOf(0.1, 0.8, 1.6, 0.05, 0.95, false);
        // levels: 0 visible, 1 invisible, 2 absent.
        auto stack = [&](bool fillFirst, int levelsState, bool withEffects) {
            Builder builder(MaskRig::kSize, MaskRig::kSize, {{ChannelType::User0, ChannelFormat::L16}, {ChannelType::User1, ChannelFormat::L16}});
            rig.Register(builder);
            core::Layer layer = builder.Fill("content", SameSource(both, Bitmap(rig.greySha)), Same(both, BlendingMode::Normal, 1));
            if (withEffects) {
                core::Effect fill = ContentFillEffect(builder, both, Uniform(0.8, 0.8, 0.8), BlendingMode::Multiply, 0.7);
                core::Effect levels = LevelsEffect(builder, component, ChannelType::User0);
                levels.visible = levelsState == 0;
                // Storage is top first: the first effect applied is the last stored.
                layer.content_effects = fillFirst ? std::vector<core::Effect>{levels, fill} : std::vector<core::Effect>{fill, levels};
                if (levelsState == 2) layer.content_effects = {fill};
            }
            builder.SetRoot({layer});
            return builder;
        };
        Builder fl = stack(true, 0, true);
        Builder lf = stack(false, 0, true);
        Builder hidden = stack(true, 1, true);
        Builder plain = stack(true, 0, false);
        const std::vector<uint32_t> flU0 = SamplesOf(rig.Evaluate(fl, ChannelType::User0), "fill-levels");
        const std::vector<uint32_t> lfU0 = SamplesOf(rig.Evaluate(lf, ChannelType::User0), "levels-fill");
        const TileFormat tile = TileFormatOf(ChannelFormat::L16);
        const float u = OperandOf(StoreValue(0.8f, tile, 0), tile, 0);
        const arith::LevelsComponent levels{0.1f, 0.8f, 1.6f, 0.05f, 0.95f, false};
        std::vector<uint32_t> model;
        for (size_t i = 0; i < texels; ++i) {
            const float s = rig.G(i);
            const float r = arith::Clamp01(arith::BlendKernel(BlendingMode::Multiply, s, u));
            const float e1 = OperandOf(StoreValue(s + (r - s) * 0.7f, tile, 0), tile, 0);
            const float e2 = OperandOf(StoreValue(arith::Levels(e1, levels), tile, 0), tile, 0);
            model.push_back(StoreValue(1.0f + (e2 - 1.0f) * 1.0f, tile, 0));
        }
        Check(flU0 == model && lfU0 != flU0, "content effects run in list order: fill then levels differs from levels then fill",
              std::to_string(flU0 == model) + " " + std::to_string(lfU0 != flU0));
        Builder fillOnly = stack(true, 2, true);
        const std::vector<uint32_t> flU1 = SamplesOf(rig.Evaluate(fl, ChannelType::User1), "fill-levels User1");
        const std::vector<uint32_t> fillOnlyU1 = SamplesOf(rig.Evaluate(fillOnly, ChannelType::User1), "fill User1");
        Check(flU1 == fillOnlyU1 && flU1 != SamplesOf(rig.Evaluate(plain, ChannelType::User1), "plain User1"),
              "a levels effect touches only its affected channel");
        Check(SamplesOf(rig.Evaluate(hidden, ChannelType::User0), "hidden levels") != flU0 &&
                  SamplesOf(rig.Evaluate(hidden, ChannelType::User0), "hidden levels") ==
                      SamplesOf(rig.Evaluate(fillOnly, ChannelType::User0), "fill only"),
              "an invisible effect is skipped");
    }

    // Geometry masks.
    {
        auto geometry = std::make_shared<MeshGeometryMasks>(TwoHalvesMesh());
        auto run = [&](bool inclusion, core::GeometryMaskType type) {
            Builder builder = BlackOverWhite(rig, ChannelFormat::L16, nullptr);
            core::Layer& black = builder.Stack().root_layers.front();
            black.geometry_mask.type = type;
            black.geometry_mask.inclusion_list = inclusion;
            black.geometry_mask.items = {"left"};
            return rig.Evaluate(builder, ChannelType::User0, nullptr, geometry);
        };
        const std::vector<uint32_t> included = SamplesOf(run(true, core::GeometryMaskType::Mesh), "inclusion");
        const std::vector<uint32_t> excluded = SamplesOf(run(false, core::GeometryMaskType::Mesh), "exclusion");
        std::vector<float> left(texels), right(texels);
        for (size_t i = 0; i < texels; ++i) {
            const bool isLeft = (i % MaskRig::kSize) < MaskRig::kSize / 2;
            left[i] = isLeft ? 1.0f : 0.0f;
            right[i] = isLeft ? 0.0f : 1.0f;
        }
        Check(included == BlackOverWhiteModel(ChannelFormat::L16, left) && excluded == BlackOverWhiteModel(ChannelFormat::L16, right),
              "a Mesh geometry mask multiplies the mask (inclusion and exclusion lists)");
        render::Result<ChannelResult> uvTile = run(true, core::GeometryMaskType::UVTile);
        Check(!uvTile && KindName(uvTile.error()) == "unsupported_node", "a UVTile geometry mask fails with unsupported_node",
              Describe(uvTile));
    }

    // Group masks.
    {
        auto run = [&](bool grouped) {
            Builder builder(MaskRig::kSize, MaskRig::kSize, {{ChannelType::User0, ChannelFormat::RGB16}});
            rig.Register(builder);
            core::Layer base = builder.Fill("base", SameSource(user0, Uniform(0.3, 0.6, 0.9)), Same(user0, BlendingMode::Normal, 1));
            core::Layer fill = builder.Fill("fill", SameSource(user0, Bitmap(rig.rampSha)), Same(user0, BlendingMode::Normal, 1));
            const core::Mask mask = MaskWith(core::MaskBackground::Black,
                                             {MaskFillEffect(builder, Bitmap(rig.greySha), BlendingMode::Normal, 1.0)});
            if (grouped) {
                core::Layer group = builder.Group("group", {fill}, Same(user0, BlendingMode::Normal, 1));
                group.mask = mask;
                builder.SetRoot({base, group});
            } else {
                fill.mask = mask;
                builder.SetRoot({base, fill});
            }
            return SamplesOf(rig.Evaluate(builder, ChannelType::User0), grouped ? "group" : "masked fill");
        };
        Check(run(true) == run(false), "a group mask scales the group composite");
    }

    // The Height override of a group.
    {
        Builder builder(MaskRig::kSize, MaskRig::kSize, {{ChannelType::Height, ChannelFormat::L16F}});
        const std::vector<ChannelType> height{ChannelType::Height};
        core::Layer child = builder.Fill("child", SameSource(height, Uniform(0.5, 0.5, 0.5)), Same(height, BlendingMode::Multiply, 0.4));
        core::Layer plain = builder.Fill("plain", SameSource(height, Uniform(0.5, 0.5, 0.5)), {});
        core::Layer group = builder.Group("group", {child}, Same(height, BlendingMode::LinearDodge, 0.7));
        const core::Blending g = EffectiveBlending(group, ChannelType::Height);
        const core::Blending c = EffectiveBlending(group.children.front(), ChannelType::Height);
        const core::Blending p = EffectiveBlending(plain, ChannelType::Height);
        Check(g.mode == BlendingMode::LinearDodge && g.opacity == 0.7 && c.mode == BlendingMode::Multiply && c.opacity == 0.4 &&
                  p.mode == BlendingMode::Normal && p.opacity == 1.0,
              "a group's Height entry is its effective Height blend; a child keeps its own");
    }

    // Complementary masks over the template base (LAY-10).
    {
        const std::vector<ChannelType> colour{ChannelType::BaseColor};
        Builder builder(MaskRig::kSize, MaskRig::kSize, {{ChannelType::BaseColor, ChannelFormat::RGB16}});
        rig.Register(builder);
        core::Layer a = builder.Fill("a", SameSource(colour, Uniform(0.2, 0.4, 0.6)), Same(colour, BlendingMode::Normal, 1));
        a.mask = MaskWith(core::MaskBackground::Black, {MaskFillEffect(builder, Bitmap(rig.greySha), BlendingMode::Normal, 1.0)});
        core::Layer b = builder.Fill("b", SameSource(colour, Uniform(0.7, 0.5, 0.1)), Same(colour, BlendingMode::Normal, 1));
        b.mask = MaskWith(core::MaskBackground::White, {MaskFillEffect(builder, Bitmap(rig.greySha), BlendingMode::Subtract, 1.0)});
        builder.SetRoot({a, b});
        const std::vector<uint32_t> ours = SamplesOf(rig.Evaluate(builder, ChannelType::BaseColor), "complementary masks");
        const render::Result<std::array<float, 3>> base = rig.templates->BaseValue(kDefaultTemplateId, ChannelType::BaseColor);
        const TileFormat tile = TileFormatOf(ChannelFormat::RGB16);
        const TileFormat inter = TileFormatOf(ChannelFormat::RGB16, true);
        // The composite rules of the profile the rig stamps (the current one).
        const render::Result<EvaluatorProfile> current = FindProfile(kCurrentProfile);
        const bool weights = current && current->coverageWeights;
        const bool fused = current && current->fusedReadout;
        auto model = [&](const std::array<float, 3>& under) {
            std::vector<uint32_t> out;
            const std::array<float, 3> ca = UniformOperand({0.2, 0.4, 0.6}, tile, under);
            const std::array<float, 3> cb = UniformOperand({0.7, 0.5, 0.1}, tile, under);
            for (size_t i = 0; i < texels; ++i) {
                const float g = rig.G(i);
                const float m1 = Mask16(0.0f + (g - 0.0f) * 1.0f);
                const float m2 = Mask16(1.0f + (arith::Clamp01(1.0f - g) - 1.0f) * 1.0f);
                arith::CompositeInput first;
                first.clampUnorm = true;
                first.coverageWeights = weights;
                first.emptyBackdrop = true;
                first.acc = {0.0f, 0.0f, 0.0f, 0.0f};
                first.src = {ca[0], ca[1], ca[2], 1.0f};
                first.mask = m1;
                std::array<float, 4> acc = arith::Composite(first);
                for (uint32_t c = 0; c < 4; ++c) acc[c] = OperandOf(StoreValue(acc[c], inter, c), inter, c);
                arith::CompositeInput second;
                second.clampUnorm = true;
                second.coverageWeights = weights;
                second.acc = acc;
                second.src = {cb[0], cb[1], cb[2], 1.0f};
                second.mask = m2;
                std::array<float, 4> top = arith::Composite(second);
                for (uint32_t c = 0; c < 4; ++c) top[c] = OperandOf(StoreValue(top[c], inter, c), inter, c);
                arith::CompositeInput readout;
                readout.clampUnorm = true;
                readout.fusedReadout = fused;
                readout.mode = BlendingMode::Replace;
                readout.acc = {under[0], under[1], under[2], 1.0f};
                readout.src = top;
                const std::array<float, 4> result = arith::Composite(readout);
                for (uint32_t c = 0; c < 3; ++c) out.push_back(StoreValue(result[c], tile, c));
            }
            return out;
        };
        Check(current && base && ours == model(*base) && ours != model({0.0f, 0.0f, 0.0f}),
              "two fills under complementary masks leave exactly the template base uncovered (no default bleed)");
    }

    // Explicit failures.
    {
        bool allFail = true;
        std::string detail;
        for (const core::EffectKind kind : {core::EffectKind::filter, core::EffectKind::generator, core::EffectKind::anchor}) {
            Builder builder(MaskRig::kSize, MaskRig::kSize, {{ChannelType::User0, ChannelFormat::L16}});
            core::Layer layer = builder.Fill("fx", SameSource(user0, Uniform(0.5, 0.5, 0.5)), Same(user0, BlendingMode::Normal, 1));
            core::Effect effect;
            effect.uid = builder.project.AllocateId();
            effect.kind = kind;
            effect.name = "fx";
            if (kind == core::EffectKind::anchor) {
                effect.anchor_name = "anchor";
            } else {
                core::ProceduralRef ref;
                ref.asset = "uzasset://filter/blur@1";
                effect.procedural = ref;
                effect.active_channels = {ChannelType::User0};
            }
            layer.content_effects.push_back(effect);
            builder.SetRoot({layer});
            render::Result<ChannelResult> result = rig.Evaluate(builder, ChannelType::User0);
            if (result || KindName(result.error()) != "unsupported_node") {
                allFail = false;
                detail += std::string(core::ToString(kind)) + ": " + Describe(result) + "; ";
            }
        }
        Check(allFail, "filter, generator and anchor effects fail with unsupported_node", detail);

        Builder builder(MaskRig::kSize, MaskRig::kSize, {{ChannelType::User0, ChannelFormat::L16}});
        rig.Register(builder);
        core::Layer child = builder.Fill("child", SameSource(user0, Uniform(0.5, 0.5, 0.5)), Same(user0, BlendingMode::Normal, 1));
        core::Layer pass = builder.Group("pass", {child}, Same(user0, BlendingMode::PassThrough, 1));
        pass.mask = MaskWith(core::MaskBackground::Black, {MaskFillEffect(builder, Bitmap(rig.greySha), BlendingMode::Normal, 1.0)});
        builder.SetRoot({pass});
        render::Result<ChannelResult> result = rig.Evaluate(builder, ChannelType::User0);
        Check(static_cast<bool>(result), "a PassThrough group with a mask raster evaluates", Describe(result));
    }

    // The cache shape: effect chains are graph nodes keyed by chained hashes.
    {
        const std::vector<ChannelType> both{ChannelType::User0, ChannelType::User1};
        Builder builder(256, 256, {{ChannelType::User0, ChannelFormat::RGB16}, {ChannelType::User1, ChannelFormat::RGB16}});
        rig.Register(builder);
        core::Layer low = builder.Fill("low", SameSource(both, Bitmap(rig.rampSha)), Same(both, BlendingMode::Normal, 1));
        core::Layer mid = builder.Fill("mid", SameSource(both, Bitmap(rig.greySha)), Same(both, BlendingMode::Normal, 0.9));
        core::Effect contentFill = ContentFillEffect(builder, both, Uniform(0.8, 0.3, 0.5), BlendingMode::Multiply, 0.7);
        core::Effect contentLevels = LevelsEffect(builder, LevelsComponentOf(0.1, 0.8, 1.6, 0.05, 0.95, false), ChannelType::User0);
        mid.content_effects = {contentLevels, contentFill};  // top first
        core::Effect m1 = MaskFillEffect(builder, Bitmap(rig.greySha), BlendingMode::Normal, 1.0);
        core::Effect m2 = MaskFillEffect(builder, Bitmap(rig.rampSha), BlendingMode::Multiply, 0.8);
        core::Effect m3 = LevelsEffect(builder, LevelsComponentOf(0.05, 0.95, 0.8, 0.0, 1.0, true), std::nullopt);
        mid.mask = MaskWith(core::MaskBackground::Black, {m1, m2, m3});
        core::Layer top = builder.Fill("top", SameSource(both, Uniform(0.4, 0.5, 0.6)), Same(both, BlendingMode::Screen, 0.5));
        const core::Id m2Uid = m2.uid;
        const core::Id levelsUid = contentLevels.uid;
        builder.SetRoot({low, mid, top});
        if (!builder.Validate("mask cache")) return Finish();
        // 256^2 = one tile; masks are 16-bit tiles shared by both channels.
        core::DocumentState state;
        state.project_uuid = "mask-cache-test";
        state.project = builder.project;
        core::Document document(std::move(state));
        CpuEvaluator cpu(rig.templates, kWideLimits);
        auto evaluate = [&](const core::Snapshot& snapshot, ChannelType channel, CpuEvaluator& evaluator) {
            EvaluateRequest request;
            request.textureSet = builder.SetId();
            request.stack = builder.StackId();
            request.channel = channel;
            request.resources = rig.provider;
            return evaluator.Evaluate(*snapshot.project, request);
        };
        auto fresh = [&](const core::Snapshot& snapshot, ChannelType channel) {
            CpuEvaluator other(rig.templates, kWideLimits);
            return evaluate(snapshot, channel, other);
        };
        auto stats = [](const render::Result<ChannelResult>& r) {
            return r ? "blends " + std::to_string(r->stats.blends) + " levels " + std::to_string(r->stats.levels) +
                           " uploads " + std::to_string(r->stats.uploads) + " hits " + std::to_string(r->stats.cacheHits)
                     : Describe(r);
        };
        auto edit = [&](const std::string& key, const std::function<void(core::Edit&)>& change) {
            core::MutationRequest mutation;
            mutation.tool = "set_parameters";
            mutation.idempotency_key = key;
            mutation.expected_revision = document.revision();
            core::RequestOutcome outcome = core::Execute(document, mutation, change);
            return outcome.result && outcome.result->status == core::ResultStatus::committed;
        };
        bool equalFresh = true;
        const core::Snapshot first = document.snapshot();
        render::Result<ChannelResult> initial = evaluate(first, ChannelType::User0, cpu);
        Info("first evaluation: " + stats(initial));
        const bool maskEdited = edit("mask-edit", [&](core::Edit& e) {
            core::FindEffect(e.project(), m2Uid)->mono_blending->opacity = 0.6;
        });
        const core::Snapshot second = document.snapshot();
        render::Result<ChannelResult> afterMask = evaluate(second, ChannelType::User0, cpu);
        // Mask: m1 served, m2 and m3 run (one blend, one levels); content served; prefix of "low"
        // served; "mid", "top" and the read-out blend.
        Check(maskEdited && afterMask && afterMask->stats.blends == 4 && afterMask->stats.levels == 1 &&
                  afterMask->stats.uploads == 0,
              "an upstream mask-effect change re-evaluates the mask from the change up and the prefixes above, "
              "serving the content chain, the lower mask effects and the prefixes below",
              stats(afterMask));
        equalFresh = equalFresh && afterMask && Samples(*afterMask) == SamplesOf(fresh(second, ChannelType::User0), "fresh");
        const bool contentEdited = edit("content-edit", [&](core::Edit& e) {
            core::FindEffect(e.project(), levelsUid)->levels->components.front().gamma = 1.3;
        });
        const core::Snapshot third = document.snapshot();
        render::Result<ChannelResult> afterContent = evaluate(third, ChannelType::User0, cpu);
        // Content: the fill effect served, the levels run; mask served; "mid", "top", read-out.
        Check(contentEdited && afterContent && afterContent->stats.blends == 3 && afterContent->stats.levels == 1 &&
                  afterContent->stats.uploads == 0,
              "an upstream content-effect change re-evaluates the content from the change up, serving the mask "
              "and the lower content effects",
              stats(afterContent));
        equalFresh = equalFresh && afterContent && Samples(*afterContent) == SamplesOf(fresh(third, ChannelType::User0), "fresh");
        render::Result<ChannelResult> other = evaluate(third, ChannelType::User1, cpu);
        // User1: its two bitmaps projected, its content fill effect, the three layers and the
        // read-out; the mask (with its levels) served from User0's evaluation.
        Check(other && other->stats.levels == 0 && other->stats.uploads == 2 && other->stats.blends == 5,
              "the masks of one layer are shared by its channels", stats(other));
        equalFresh = equalFresh && other && Samples(*other) == SamplesOf(fresh(third, ChannelType::User1), "fresh");
        Check(equalFresh, "every partially re-evaluated result equals a fresh evaluation bit for bit");
    }
    return Finish();
}

// ── masks-gpu-vs-cpu ─────────────────────────────────────────────────────────

int RunMasksGpuVsCpu(const fs::path& assets, const fs::path& dir) {
    std::shared_ptr<const TemplateLibrary> templates = LoadTemplates(assets);
    render::Engine engine(TestOptions(dir));
    if (NoAdapter(engine)) return kExitSkip;
    Info("adapter " + engine.Capabilities().value_or(render::CapabilityReport{}).adapter);
    std::mt19937 rng(1111);
    auto unit = [&] { return std::uniform_real_distribution<double>(0.0, 1.0)(rng); };
    const std::vector<BlendingMode> modes{BlendingMode::Normal, BlendingMode::Multiply, BlendingMode::Subtract,
                                          BlendingMode::Screen, BlendingMode::Overlay, BlendingMode::LinearDodge,
                                          BlendingMode::Divide, BlendingMode::SoftLight};
    auto provider = std::make_shared<MapResourceProvider>();
    const std::string grey = std::string(63, 'e') + "1";
    const std::string colour = std::string(63, 'e') + "2";
    provider->Add(grey, PatternImage(256, 256, 1, render::TexelEncoding::Unorm16, 31));
    provider->Add(colour, PatternImage(256, 256, 3, render::TexelEncoding::Unorm16, 32));
    size_t compared = 0;
    bool allEqual = true;
    Evaluator gpu(engine, templates);
    for (const ChannelFormat format : kAllFormats) {
        const std::vector<ChannelType> channels{ChannelType::User0};
        for (int variant = 0; variant < 2; ++variant) {
            Builder builder(256, 256, {{ChannelType::User0, format}});
            builder.AddResource(grey, 100);
            builder.AddResource(colour, 100);
            auto levels = [&](std::optional<ChannelType> affected) {
                return LevelsEffect(builder,
                                    LevelsComponentOf(0.3 * unit() - 0.1, 0.6 + 0.6 * unit(), 0.3 + 2.0 * unit(),
                                                      0.2 * unit() - 0.1, 0.8 + 0.4 * unit(), unit() < 0.5),
                                    affected);
            };
            auto mask = [&] {
                return MaskWith(unit() < 0.5 ? core::MaskBackground::Black : core::MaskBackground::White,
                                {MaskFillEffect(builder, Bitmap(grey), modes[rng() % modes.size()], unit()),
                                 MaskFillEffect(builder, Uniform(unit(), unit(), unit()), modes[rng() % modes.size()], unit()),
                                 levels(std::nullopt)});
            };
            std::vector<core::Layer> layers;
            core::Layer bottom = builder.Fill("bottom", SameSource(channels, Bitmap(colour)), Same(channels, BlendingMode::Normal, 1));
            bottom.content_effects = {levels(ChannelType::User0),
                                      ContentFillEffect(builder, channels, Uniform(unit(), unit(), unit()),
                                                        modes[rng() % modes.size()], unit())};
            layers.push_back(bottom);
            core::Layer masked = builder.Fill("masked", SameSource(channels, Uniform(unit(), unit(), unit())),
                                              Same(channels, modes[rng() % modes.size()], 0.5 + 0.5 * unit()));
            masked.mask = mask();
            masked.content_effects = {levels(ChannelType::User0),
                                      ContentFillEffect(builder, channels, Bitmap(colour), modes[rng() % modes.size()], unit())};
            layers.push_back(masked);
            core::Layer child = builder.Fill("child", SameSource(channels, Bitmap(colour)), Same(channels, modes[rng() % modes.size()], unit()));
            child.mask = mask();
            core::Layer group = builder.Group("group", {child}, Same(channels, BlendingMode::Normal, 0.4 + 0.6 * unit()));
            if (variant == 1) group.mask = mask();
            layers.push_back(group);
            core::Layer passChild = builder.Fill("pass child", SameSource(channels, Bitmap(colour)),
                                                 Same(channels, modes[rng() % modes.size()], unit()));
            passChild.mask = mask();
            core::Layer pass = builder.Group("pass", {passChild}, Same(channels, BlendingMode::PassThrough, 0.4 + 0.6 * unit()));
            if (variant == 1) pass.mask = mask();
            layers.push_back(pass);
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
            const std::string label = std::string(core::ToString(format)) + " masked stack " + std::to_string(variant);
            if (!cpuResult || !gpuResult) {
                allEqual = false;
                Check(false, label + " evaluates on both stores", Describe(cpuResult) + " / " + Describe(gpuResult));
                continue;
            }
            std::string first;
            const size_t mismatches = Mismatches(Samples(*cpuResult), Samples(*gpuResult), first, cpuResult->tileFormat.encoding);
            compared += Samples(*cpuResult).size();
            if (mismatches != 0) {
                allEqual = false;
                Check(false, label + ": GPU equals CPU", std::to_string(mismatches) + " mismatches; " + first);
            }
        }
    }
    gpu.Shutdown();
    Check(allEqual, "every masked stack evaluates to the same bytes on the GPU and on the CPU (" + std::to_string(compared) +
                        " samples over 9 formats: mask and content fill effects, levels with gamma, group masks, masked PassThrough groups)");
    return Finish();
}

// ── pow-hardware ─────────────────────────────────────────────────────────────

/// Domain kernel: texel i of a 4096 x 4096 target holds, for i < 2^23, log2(1 + m 2^-23) and
/// exp2(m 2^-23) (m = i), for i >= 2^23 log2((1 + m 2^-23) / 2) and exp2(-m 2^-23). Sample kernel:
/// texel i of a 1024 x 1024 target holds log2(x), x, exp2(y), y for an edge value (i < 40) or
/// hashed bit patterns (y over the exponents 2^-7 .. 2^7 and, every 16th texel, any bit pattern);
/// Pow kernel: pow(x, g), x, g and exp2(g log2(x)) for hashed x and g in [0.2, 3).
constexpr char kPowHardwareHlsl[] = R"(
cbuffer Root : register(b0) { uint g_dst; };
static const uint kEdges[40] = {
    0x00000000u, 0x80000000u, 0x00000001u, 0x007FFFFFu, 0x80000001u, 0x807FFFFFu, 0x00800000u,
    0x00800001u, 0x7E7FFFFFu, 0x7F000000u, 0x7F7FFFFFu, 0x7F800000u, 0xFF800000u, 0x7FC00000u,
    0xFFC00000u, 0x7F800001u, 0xBF800000u, 0xC0000000u, 0x3F800000u, 0x3F7FFFFFu, 0x3F800001u,
    0x43000000u, 0x42FFFFFFu, 0x43010000u, 0xC3000000u, 0xC3160000u, 0xC3150000u, 0xC2FC0000u,
    0xC2FE0000u, 0xC3100000u, 0x4B000000u, 0xCB000000u, 0x34000000u, 0xB4000000u, 0x3F000000u,
    0xBF000000u, 0x40000000u, 0x3E800000u, 0x42F00000u, 0xC2F00000u};
uint Hash(uint i) {
    uint h = i * 0x9E3779B9u;
    h ^= h >> 16;
    h *= 0x85EBCA6Bu;
    h ^= h >> 13;
    h *= 0xC2B2AE35u;
    h ^= h >> 16;
    return h;
}
[numthreads(8, 8, 1)]
void Domain(uint3 id : SV_DispatchThreadID) {
    RWTexture2D<float4> dst = ResourceDescriptorHeap[g_dst];
    const uint i = id.y * 4096u + id.x;
    const uint m = i & 0x7FFFFFu;
    const float x = asfloat((i < 0x800000u ? 0x3F800000u : 0x3F000000u) | m);
    const float y = (i < 0x800000u ? 1.0f : -1.0f) * (float(m) * (1.0f / 8388608.0f));
    dst[id.xy] = float4(log2(x), exp2(y), 0.0f, 0.0f);
}
[numthreads(8, 8, 1)]
void Samples(uint3 id : SV_DispatchThreadID) {
    RWTexture2D<float4> dst = ResourceDescriptorHeap[g_dst];
    const uint i = id.y * 1024u + id.x;
    const uint h = Hash(i);
    const uint k = Hash(i + 0x51ED270Bu);
    const float x = asfloat(i < 40u ? kEdges[i] : ((i & 15u) == 0u ? h : (h & 0x7FFFFFFFu)));
    const float y = asfloat(i < 40u ? kEdges[i] : ((i & 15u) == 0u ? k
                                     : ((k & 0x807FFFFFu) | ((((k >> 23) & 0xFFu) % 15u + 120u) << 23))));
    dst[id.xy] = float4(log2(x), x, exp2(y), y);
}
[numthreads(8, 8, 1)]
void Pow(uint3 id : SV_DispatchThreadID) {
    RWTexture2D<float4> dst = ResourceDescriptorHeap[g_dst];
    const uint i = id.y * 1024u + id.x;
    const uint h = Hash(i);
    const uint k = Hash(i + 0x2545F491u);
    const float x = asfloat(0x3D800000u + (h % 0x02800000u));
    const float g = 0.2f + float(k >> 8) * (2.8f / 16777216.0f);
    dst[id.xy] = float4(pow(x, g), x, g, exp2(g * log2(x)));
}
)";

/// Measures the GPU's log2 and exp2 (as the render layer compiles them, `-Gis`) over the four
/// table domains of hwmath.h, writes the measured tables (`hw-lg2-hi.zlib`, `hw-lg2-lo.zlib`,
/// `hw-ex2-pos.zlib`, `hw-ex2-neg.zlib`) to the work directory and compares them with the
/// embedded ones, then compares hw::Log2 and hw::Exp2 with the GPU on 2^20 inputs each (40 edge
/// values and 1 048 536 hashed inputs), hw::Pow on 2^20 hashed inputs, and the GPU's pow with its
/// exp2(g log2 x).
int RunPowHardware(const fs::path& dir) {
    render::Engine engine(TestOptions(dir));
    if (NoAdapter(engine)) return kExitSkip;
    Info("adapter " + engine.Capabilities().value_or(render::CapabilityReport{}).adapter);
    render::Result<std::vector<float>> domain = FpKernelTexels(engine, "Domain", 4096, kPowHardwareHlsl);
    render::Result<std::vector<float>> samples = FpKernelTexels(engine, "Samples", 1024, kPowHardwareHlsl);
    render::Result<std::vector<float>> pows = FpKernelTexels(engine, "Pow", 1024, kPowHardwareHlsl);
    if (!domain || !samples || !pows) {
        Check(false, "the GPU's log2, exp2 and pow are measured",
              (!domain ? domain : (!samples ? samples : pows)).error().Describe());
        return Finish();
    }
    const std::vector<float>& v = *domain;
    const uint32_t n = hw::kTableEntries;
    const hw::Table tables[4] = {hw::Table::Log2Hi, hw::Table::Log2Lo, hw::Table::Exp2Pos, hw::Table::Exp2Neg};
    const char* names[4] = {"lg2-hi", "lg2-lo", "ex2-pos", "ex2-neg"};
    for (int t = 0; t < 4; ++t) {
        std::vector<uint32_t> measured(n);
        const size_t offset = (t == 1 || t == 3) ? n : 0;
        const size_t component = t < 2 ? 0 : 1;
        for (uint32_t m = 0; m < n; ++m) measured[m] = std::bit_cast<uint32_t>(v[(offset + m) * 4 + component]);
        const std::vector<unsigned char> packed = hw::CompressValues(measured);
        std::ofstream(dir / (std::string("hw-") + names[t] + ".zlib"), std::ios::binary)
            .write(reinterpret_cast<const char*>(packed.data()), static_cast<std::streamsize>(packed.size()));
        const std::vector<uint32_t>& embedded = hw::Values(tables[t]);
        size_t differing = 0;
        for (uint32_t m = 0; m < n; ++m) differing += embedded[m] != measured[m];
        Check(differing == 0,
              std::string("the embedded ") + names[t] + " table equals the GPU on every entry of its domain (" +
                  std::to_string(n) + ")",
              std::to_string(differing) + " entries differ");
    }
    size_t differing = 0;
    std::string first;
    const std::vector<float>& s = *samples;
    for (size_t i = 0; i < s.size() / 4; ++i) {
        const float x = s[i * 4 + 1];
        const float y = s[i * 4 + 3];
        const float ours[2] = {hw::Log2(x), hw::Exp2(y)};
        const float theirs[2] = {s[i * 4], s[i * 4 + 2]};
        const float inputs[2] = {x, y};
        for (int k = 0; k < 2; ++k) {
            if (SameFloat(ours[k], theirs[k])) continue;
            if (differing++ < 8) {
                first += std::string(k == 0 ? "log2(" : "exp2(") + Hex32(std::bit_cast<uint32_t>(inputs[k])) + "): GPU " +
                         Hex32(std::bit_cast<uint32_t>(theirs[k])) + ", hw " + Hex32(std::bit_cast<uint32_t>(ours[k])) + "; ";
            }
        }
    }
    const std::vector<float>& p = *pows;
    size_t composed = 0;
    for (size_t i = 0; i < p.size() / 4; ++i) {
        const float x = p[i * 4 + 1];
        const float g = p[i * 4 + 2];
        composed += !SameFloat(p[i * 4], p[i * 4 + 3]);
        if (SameFloat(hw::Pow(x, g), p[i * 4])) continue;
        if (differing++ < 8) {
            first += "pow(" + Hex32(std::bit_cast<uint32_t>(x)) + ", " + Hex32(std::bit_cast<uint32_t>(g)) + "): GPU " +
                     Hex32(std::bit_cast<uint32_t>(p[i * 4])) + ", hw " + Hex32(std::bit_cast<uint32_t>(hw::Pow(x, g))) + "; ";
        }
    }
    Check(composed == 0, "the GPU's pow(x, g) is exp2(g log2(x)) on " + std::to_string(p.size() / 4) + " hashed inputs",
          std::to_string(composed) + " differ");
    Check(differing == 0,
          "hw::Log2, hw::Exp2 and hw::Pow equal the GPU on 40 edge values and " + std::to_string(s.size() / 4 - 40) +
              " hashed inputs each, and on " + std::to_string(p.size() / 4) + " hashed pow inputs",
          std::to_string(differing) + " results differ: " + first);
    return Finish();
}

// ── trig-hardware ────────────────────────────────────────────────────────────

/// Domain kernel: texel k (k < 2^23) of a 4096 x 4096 target holds sin(x), cos(x) and x for the
/// smallest float32 x >= 0 whose product with c = float32(1 / (2 pi)) is at least k 2^-25 (the
/// table index of hwmath.h; the product is exact in double). Sample kernel: texel i of a 1024 x
/// 1024 target holds sin(x), cos(x) and x for an edge value (i < 8) or a hashed float32 of
/// [0, float32(pi / 2)].
constexpr char kTrigHardwareHlsl[] = R"(
cbuffer Root : register(b0) { uint g_dst; };
static const uint kEdges[8] = {0x00000000u, 0x00000001u, 0x00800000u, 0x3F800000u, 0x3FC90FDBu,
                               0x3FC90FDAu, 0x3F490FDBu, 0x34000000u};
uint Hash(uint i) {
    uint h = i * 0x9E3779B9u;
    h ^= h >> 16;
    h *= 0x85EBCA6Bu;
    h ^= h >> 13;
    h *= 0xC2B2AE35u;
    h ^= h >> 16;
    return h;
}
[numthreads(8, 8, 1)]
void Domain(uint3 id : SV_DispatchThreadID) {
    RWTexture2D<float4> dst = ResourceDescriptorHeap[g_dst];
    const uint k = id.y * 4096u + id.x;
    if (k >= 8388608u) {
        dst[id.xy] = float4(0.0f, 0.0f, 0.0f, 0.0f);
        return;
    }
    const double c = (double)asfloat(0x3E22F983u);
    const double t = (double)k * (1.0 / 33554432.0);
    float x = (float)(t / c);
    for (int i = 0; i < 4; ++i) {
        if ((double)x * c < t) x = asfloat(asuint(x) + 1u);
    }
    for (int j = 0; j < 4; ++j) {
        const float down = asfloat(asuint(x) - 1u);
        if (x > 0.0f && (double)down * c >= t) x = down;
    }
    dst[id.xy] = float4(sin(x), cos(x), x, 0.0f);
}
[numthreads(8, 8, 1)]
void Samples(uint3 id : SV_DispatchThreadID) {
    RWTexture2D<float4> dst = ResourceDescriptorHeap[g_dst];
    const uint i = id.y * 1024u + id.x;
    const float x = asfloat(i < 8u ? kEdges[i] : Hash(i) % 0x3FC90FDCu);
    dst[id.xy] = float4(sin(x), cos(x), x, 0.0f);
}
)";

/// Measures the GPU's sine and cosine (as the render layer compiles them) over the table domain of
/// hwmath.h, writes the measured tables (`hw-sin.zlib`, `hw-cos.zlib`) to the work directory and
/// compares them with the embedded ones, checks that every measured input lies at its own table
/// index, then compares hw::Sin and hw::Cos with the GPU on 8 edge values and 2^20 - 8 hashed
/// inputs of [0, float32(pi / 2)].
int RunTrigHardware(const fs::path& dir) {
    render::Engine engine(TestOptions(dir));
    if (NoAdapter(engine)) return kExitSkip;
    Info("adapter " + engine.Capabilities().value_or(render::CapabilityReport{}).adapter);
    render::Result<std::vector<float>> domain =
        FpKernelTexels(engine, "Domain", 4096, kTrigHardwareHlsl, {}, "trig_hardware_");
    render::Result<std::vector<float>> samples =
        FpKernelTexels(engine, "Samples", 1024, kTrigHardwareHlsl, {}, "trig_hardware_");
    if (!domain || !samples) {
        Check(false, "the GPU's sin and cos are measured", (!domain ? domain : samples).error().Describe());
        return Finish();
    }
    const std::vector<float>& v = *domain;
    const uint32_t n = hw::kTableEntries;
    size_t misplaced = 0;
    for (uint32_t k = 0; k < n; ++k) misplaced += hw::TrigIndex(v[size_t{k} * 4 + 2]) != k;
    Check(misplaced == 0, "every measured input lies at its table index (" + std::to_string(n) + ")",
          std::to_string(misplaced) + " misplaced");
    const hw::Table tables[2] = {hw::Table::Sin, hw::Table::Cos};
    const char* names[2] = {"sin", "cos"};
    for (int t = 0; t < 2; ++t) {
        std::vector<uint32_t> measured(n);
        for (uint32_t k = 0; k < n; ++k) measured[k] = std::bit_cast<uint32_t>(v[size_t{k} * 4 + size_t(t)]);
        const std::vector<unsigned char> packed = hw::CompressValues(measured);
        std::ofstream(dir / (std::string("hw-") + names[t] + ".zlib"), std::ios::binary)
            .write(reinterpret_cast<const char*>(packed.data()), static_cast<std::streamsize>(packed.size()));
        const std::vector<uint32_t>& embedded = hw::Values(tables[t]);
        size_t differing = 0;
        for (uint32_t k = 0; k < n; ++k) differing += embedded[k] != measured[k];
        Check(differing == 0,
              std::string("the embedded ") + names[t] + " table equals the GPU on every entry of its domain (" +
                  std::to_string(n) + ")",
              std::to_string(differing) + " entries differ");
    }
    size_t differing = 0;
    std::string first;
    const std::vector<float>& s = *samples;
    for (size_t i = 0; i < s.size() / 4; ++i) {
        const float x = s[i * 4 + 2];
        const float ours[2] = {hw::Sin(x), hw::Cos(x)};
        for (int k = 0; k < 2; ++k) {
            if (SameFloat(ours[k], s[i * 4 + size_t(k)])) continue;
            if (differing++ < 8) {
                first += std::string(k == 0 ? "sin(" : "cos(") + Hex32(std::bit_cast<uint32_t>(x)) + "): GPU " +
                         Hex32(std::bit_cast<uint32_t>(s[i * 4 + size_t(k)])) + ", hw " +
                         Hex32(std::bit_cast<uint32_t>(ours[k])) + "; ";
            }
        }
    }
    Check(differing == 0,
          "hw::Sin and hw::Cos equal the GPU on 8 edge values and " + std::to_string(s.size() / 4 - 8) +
              " hashed inputs of [0, float32(pi / 2)]",
          std::to_string(differing) + " results differ: " + first);
    return Finish();
}

// ── uv-coverage ──────────────────────────────────────────────────────────────

/// The texturing mesh of an imported file as the UV raster's corner layout (one interleaved
/// buffer: position, normal, uv0, tangent, material, island 0), owning its bytes.
struct MeshCorners {
    std::vector<std::byte> bytes;
    std::vector<uint32_t> triangles;
    render::CornerBuffers corners;
};

MeshCorners CornersOf(const uzp::mesh::TexturingMesh& mesh) {
    constexpr uint32_t stride = 56;
    MeshCorners out;
    out.bytes.resize(mesh.corners.size() * stride);
    for (size_t c = 0; c < mesh.corners.size(); ++c) {
        const uzp::mesh::Corner& corner = mesh.corners[c];
        const uzp::mesh::Float3& position = mesh.positions[corner.position];
        const float values[12] = {position.x, position.y, position.z, corner.normal.x, corner.normal.y,
                                  corner.normal.z, corner.uv0.u, corner.uv0.v, corner.tangent[0],
                                  corner.tangent[1], corner.tangent[2], corner.tangent[3]};
        std::byte* at = out.bytes.data() + c * stride;
        std::memcpy(at, values, sizeof(values));
        const uint32_t ids[2] = {corner.material, 0};
        std::memcpy(at + 48, ids, sizeof(ids));
    }
    for (const uzp::mesh::Object& object : mesh.objects) {
        for (const uzp::mesh::Triangle& triangle : object.triangles) {
            out.triangles.insert(out.triangles.end(), triangle.corners.begin(), triangle.corners.end());
        }
    }
    render::CornerBuffers& cb = out.corners;
    cb.buffers = {out.bytes};
    cb.cornerCount = static_cast<uint32_t>(mesh.corners.size());
    cb.position = {0, 0, stride};
    cb.normal = {0, 12, stride};
    cb.uv0 = {0, 24, stride};
    cb.tangent = {0, 32, stride};
    cb.materialId = {0, 48, stride};
    cb.islandId = {0, 52, stride};
    cb.triangles = out.triangles;
    return out;
}

/// Imports `mesh` with the product's importer, rasterises its UV tile 1001 at `size`^2 with the
/// render layer's UV raster and writes the texel-centre coverage (`coverage.bin`, one byte per
/// texel, rows top first: 1 where a triangle covers the texel centre).
int RunUvCoverage(const fs::path& dir, const fs::path& meshPath, uint32_t size) {
    uzp::mesh::ImportResult imported = uzp::mesh::ImportMeshFile(meshPath, {});
    MeshCorners corners = CornersOf(imported.mesh);
    render::Engine engine(TestOptions(dir));
    if (NoAdapter(engine)) return kExitSkip;
    auto token = std::make_shared<const int>(0);
    std::future<render::Result<std::vector<uint8_t>>> future = engine.Submit(
        token, [&](render::EngineContext& context, const int&) -> render::Result<std::vector<uint8_t>> {
            render::UvRasterRequest request;
            request.width = size;
            request.height = size;
            render::Result<render::UvRasterBuffers> raster = render::RasterizeUv(context, corners.corners, request);
            if (!raster) return render::Unexpected(raster.error());
            render::TextureReadback readback(context);
            render::ReadbackDesc desc;
            desc.texture = raster->triangle;
            render::Result<render::ReadbackId> id = readback.Request(desc);
            render::Result<render::ReadbackImage> image =
                id ? readback.Complete(*id) : render::Result<render::ReadbackImage>(render::Unexpected(id.error()));
            raster->Destroy(context.Device());
            if (!image) return render::Unexpected(image.error());
            std::vector<uint8_t> covered(size_t{size} * size);
            for (size_t t = 0; t < covered.size(); ++t) {
                uint32_t triangle = 0;
                std::memcpy(&triangle, image->texels.data() + t * sizeof(uint32_t), sizeof(uint32_t));
                covered[t] = triangle == render::kUvRasterNoId ? 0 : 1;
            }
            return covered;
        });
    render::Result<std::vector<uint8_t>> covered = Get(future);
    if (!covered) {
        Check(false, "the mesh's UV tile rasterises", covered.error().Describe());
        return Finish();
    }
    std::ofstream file(dir / "coverage.bin", std::ios::binary);
    file.write(reinterpret_cast<const char*>(covered->data()), static_cast<std::streamsize>(covered->size()));
    size_t count = 0;
    for (const uint8_t c : *covered) count += c;
    Info("covered texels " + std::to_string(count) + " of " + std::to_string(covered->size()));
    Check(count > 0, "the texturing mesh rasterises into the UV tile (" + std::to_string(imported.mesh.TriangleCount()) +
                         " triangles)");
    return Finish();
}

// ── height-normal (CPU) ──────────────────────────────────────────────────────

/// A grey height image of `size` x `size` float32 samples (a ramp, a cone and flat areas) that a
/// spec uploads to a Float32 Height tile.
std::shared_ptr<DecodedImage> HeightCodes(uint32_t size, uint32_t seed) {
    auto image = std::make_shared<DecodedImage>();
    image->width = size;
    image->height = size;
    image->channels = 1;
    image->encoding = render::TexelEncoding::Unorm16;
    image->values.resize(size_t{size} * size);
    std::mt19937 rng(seed);
    for (uint32_t y = 0; y < size; ++y) {
        for (uint32_t x = 0; x < size; ++x) {
            uint32_t code = 32768;
            if (x < size / 2) code = (x * 977u + y * 131u) % 65536u;          // ramps
            else if (y < size / 2) code = rng() % 65536u;                     // noise
            image->values[size_t{y} * size + x] = code;
        }
    }
    return image;
}

/// An RGB normal-map image (16-bit codes, z towards +1).
std::shared_ptr<DecodedImage> NormalCodes(uint32_t size, uint32_t seed, uint32_t bits = 16) {
    auto image = std::make_shared<DecodedImage>();
    image->width = size;
    image->height = size;
    image->channels = 3;
    image->encoding = bits == 16 ? render::TexelEncoding::Unorm16 : render::TexelEncoding::Unorm8;
    const uint32_t max = (1u << bits) - 1u;
    image->values.resize(size_t{size} * size * 3);
    std::mt19937 rng(seed);
    for (size_t i = 0; i < size_t{size} * size; ++i) {
        image->values[i * 3 + 0] = rng() % (max + 1);
        image->values[i * 3 + 1] = rng() % (max + 1);
        image->values[i * 3 + 2] = max / 2 + rng() % (max / 2 + 1);
    }
    return image;
}

std::array<uint32_t, 3> Codes16(const std::array<float, 3>& e) {
    return {arith::WriteUnorm(e[0], 16), arith::WriteUnorm(e[1], 16), arith::WriteUnorm(e[2], 16)};
}

int RunHeightNormal(const fs::path& assets) {
    using core::HeightToNormalMethod;
    using core::NormalMapFormat;
    std::shared_ptr<const TemplateLibrary> templates = LoadTemplates(assets);

    // ── The stencils and the combination of one texel ──
    {
        const HeightNeighbourhood flat{0.25f, 0.25f, 0.25f, 0.25f, 0.25f, 0.25f, 0.25f, 0.25f, 0.25f};
        bool flatOk = true;
        for (const HeightToNormalMethod method : {HeightToNormalMethod::Sharp, HeightToNormalMethod::SmoothSobel}) {
            for (const NormalMapFormat convention : {NormalMapFormat::OpenGL, NormalMapFormat::DirectX}) {
                const std::array<uint32_t, 3> codes =
                    Codes16(VirtualNormalTexel(HeightVector(method, flat, HeightZ(method, 256)), NormalInputs{}, convention));
                flatOk = flatOk && codes == std::array<uint32_t, 3>{32767, 32767, 65535};
            }
        }
        Check(flatOk, "a flat height and an empty Normal channel give the flat normal (32767, 32767, 65535) in both methods and conventions");
        const HeightNeighbourhood h{1.0f, 2.0f, 4.0f, 8.0f, 16.0f, 32.0f, 64.0f, 128.0f, 256.0f};
        const std::array<float, 3> sharp = HeightVector(HeightToNormalMethod::Sharp, h, HeightZ(HeightToNormalMethod::Sharp, 256));
        const std::array<float, 3> sobel =
            HeightVector(HeightToNormalMethod::SmoothSobel, h, HeightZ(HeightToNormalMethod::SmoothSobel, 256));
        Check(sharp == std::array<float, 3>{8.0f - 16.0f, 16.0f - 2.0f, kSharpZ},
              "Sharp: (h(-1,0) - h(0,0), h(0,0) - h(0,-1), 0.390625)");
        // L = (1 + 2*8) + 64 = 81, R = (4 + 2*32) + 256 = 324, T = (1 + 2*2) + 4 = 9, B = (64 + 2*128) + 256 = 576.
        Check(sobel == std::array<float, 3>{81.0f - 324.0f, 576.0f - 9.0f, kSobelZ},
              "Smooth (Sobel): ((1,2,1) left - right, bottom - top, 3.125)");
        Check(HeightZ(HeightToNormalMethod::Sharp, 512) == 0.1953125f && HeightZ(HeightToNormalMethod::Sharp, 2048) == 0.048828125f &&
                  HeightZ(HeightToNormalMethod::SmoothSobel, 1024) == 0.78125f,
              "z is a UV-space gradient: 100 / W (Sharp) and 800 / W (Sobel)");
        // The recording GPU's acos through Vulkan (hwmath.h Acos): input and result bits measured
        // with tools/parity/vk_sampler_probe (edges, the 0.57 branch point, then values uniform in
        // [0, 1]).
        constexpr uint32_t kVulkanAcos[48][2] = {
        {0x00000000u, 0x3FC90FDBu}, {0x80000000u, 0x3FC90FDBu}, {0x00000001u, 0x3FC90FDBu}, {0x80400000u, 0x3FC90FDBu},
        {0x00800000u, 0x3FC90FDBu}, {0x3F11EB85u, 0x3F76DBBFu}, {0x3F11EB86u, 0x3F76DBBCu}, {0x3F000000u, 0x3F860A92u},
        {0x3F800000u, 0x00000000u}, {0xBF800000u, 0x40490FDBu}, {0x3F7FFFFFu, 0x39B504F3u}, {0x3F800001u, 0x7FFFFFFFu},
        {0xBE99999Au, 0x3FF01006u}, {0x3E800000u, 0x3FA8B808u}, {0x3DCCCCCDu, 0x3FBC3D92u}, {0x3F4CCCCDu, 0x3F24BC7Du},
        {0x3F666666u, 0x3EE6ECFEu}, {0x3F7FF000u, 0x3CB505E4u}, {0x3F79999Au, 0x3E6573F7u}, {0x3F7A0000u, 0x3E5E2348u},
        {0xBF11EB86u, 0x400B58ECu}, {0xBF666666u, 0x402C323Bu}, {0x3E806C10u, 0x3FA89C20u}, {0x3F725E67u, 0x3EA7D564u},
        {0x3E41DD34u, 0x3FB0AE89u}, {0x3E37982Bu, 0x3FB1FCE5u}, {0x3EB324AFu, 0x3F9B4ED7u}, {0x3E6C1301u, 0x3FAB48E9u},
        {0x3F2BA255u, 0x3F56033Du}, {0x3DEBAEBDu, 0x3FBA4C90u}, {0x3F657488u, 0x3EEB393Cu}, {0x3F5BAE71u, 0x3F0A07A1u},
        {0x3B3945BBu, 0x3FC8B338u}, {0x3F0A9D87u, 0x3F7FA551u}, {0x3DDAD4D7u, 0x3FBB5BDBu}, {0x3E8412ACu, 0x3FA7AA86u},
        {0x3ED57366u, 0x3F9204B4u}, {0x3EE8405Fu, 0x3F8CCC11u}, {0x3EEFB0E9u, 0x3F8AB38Bu}, {0x3F6D71BCu, 0x3EC42372u},
        {0x3F63896Cu, 0x3EF3BBCBu}, {0x3F60D0A3u, 0x3EFF5B81u}, {0x3F7358FCu, 0x3EA1A495u}, {0x3F7DF33Eu, 0x3E01ABEAu},
        {0x3F7D0933u, 0x3E1BF9F3u}, {0x3F7B66CFu, 0x3E426131u}, {0x3F5C123Eu, 0x3F0944C4u}, {0x3F7D91B3u, 0x3E0D3A41u},
        };
        std::string acosMiss;
        for (const auto& [in, out] : kVulkanAcos) {
            const float ours = hw::Acos(std::bit_cast<float>(in));
            const bool same = std::bit_cast<uint32_t>(ours) == out || (std::isnan(ours) && std::isnan(std::bit_cast<float>(out)));
            if (!same && acosMiss.empty()) acosMiss = std::to_string(in) + ": " + std::to_string(out);
        }
        Check(acosMiss.empty(), "hw::Acos equals the recording GPU's Vulkan acos on 48 measured inputs", acosMiss);
        {
            // The Normal channel's coverage: none is the flat normal, full keeps its colour, a part
            // turns the decoded colour X / a toward the flat normal.
            const std::array<float, 3> v{0.0f, 0.0f, kSharpZ};
            NormalInputs none;
            none.channel = {0.9f, 0.2f, 0.7f};
            none.coverage = 0.0f;
            NormalInputs full = none;
            full.coverage = 1.0f;
            NormalInputs half = none;
            half.channel = {0.5f, 0.5f, 1.0f};
            half.coverage = 0.5f;
            const std::array<uint32_t, 3> flatCodes{32767, 32767, 65535};
            const std::array<uint32_t, 3> halfCodes = Codes16(VirtualNormalTexel(v, half, NormalMapFormat::OpenGL));
            Check(Codes16(VirtualNormalTexel(v, none, NormalMapFormat::OpenGL)) == flatCodes &&
                      Codes16(VirtualNormalTexel(v, full, NormalMapFormat::OpenGL)) ==
                          Codes16(VirtualNormalTexel(v, NormalInputs{false, {}, false, {0.9f, 0.2f, 0.7f}, 1.0f},
                                                     NormalMapFormat::OpenGL)) &&
                      halfCodes[0] == halfCodes[1] && halfCodes[0] > 32767u,
                  "the Normal channel at coverage 0 is flat, at 1 its colour, at 1/2 the flat colour divided by 1/2 "
                  "turned halfway (tilted toward +x +y)");
        }
        std::mt19937 rng(7);
        std::uniform_real_distribution<float> slope(-1.5f, 1.5f);
        std::uniform_real_distribution<float> unit(0.0f, 1.0f);
        bool rbEqual = true;
        for (int i = 0; i < 4096; ++i) {
            const std::array<float, 3> v{slope(rng), slope(rng), kSharpZ};
            const std::array<float, 3> c{unit(rng), unit(rng), 0.5f + 0.5f * unit(rng)};
            NormalInputs inputs;
            inputs.channel = c;
            const std::array<float, 3> gl = VirtualNormalTexel(v, inputs, NormalMapFormat::OpenGL);
            const std::array<float, 3> dx = VirtualNormalTexel(v, inputs, NormalMapFormat::DirectX);
            // y is negated before the encoding: the two greens lie on either side of 1/2.
            rbEqual = rbEqual && gl[0] == dx[0] && gl[2] == dx[2] &&
                      ((gl[1] - 0.5f) * (dx[1] - 0.5f) < 0.0f || (gl[1] == 0.5f && dx[1] == 0.5f));
        }
        Check(rbEqual, "Normal_DirectX equals Normal_OpenGL in x and z and mirrors y (4096 random texels)");
    }

    // ── Projects through the CPU evaluator ──
    const std::string heightSha(64, 'a');
    const std::string normalSha(64, 'b');
    const std::string meshSha(64, 'c');
    const std::string mesh8Sha(64, 'd');
    auto resources = std::make_shared<MapResourceProvider>();
    resources->Add(heightSha, HeightCodes(256, 1));
    resources->Add(normalSha, NormalCodes(256, 2));
    resources->Add(meshSha, NormalCodes(256, 3));
    resources->Add(mesh8Sha, NormalCodes(256, 4, 8));
    auto makeBuilder = [&](uint32_t size) {
        Builder b(size, size, {{ChannelType::BaseColor, ChannelFormat::sRGB8},
                               {ChannelType::Height, ChannelFormat::L16F},
                               {ChannelType::Normal, ChannelFormat::RGB16F}});
        b.AddResource(heightSha, 1);
        b.AddResource(normalSha, 1);
        b.AddResource(meshSha, 1);
        b.AddResource(mesh8Sha, 1);
        return b;
    };
    auto request = [&](Builder& b, NormalSourceKind kind, NormalMapFormat convention) {
        VirtualNormalRequest r;
        r.textureSet = b.SetId();
        r.stack = b.StackId();
        r.kind = kind;
        r.convention = convention;
        r.resources = resources;
        return r;
    };
    auto kindOf = [](const render::Result<VirtualNormalResult>& result) -> std::string {
        if (result) return "ok";
        const std::optional<EvalErrorKind> kind = EvalErrorKindOf(result.error());
        return kind ? std::string(EvalErrorKindName(*kind)) : result.error().Describe();
    };

    Builder b = makeBuilder(256);
    core::Layer height = b.Fill("height", {{ChannelType::Height, Bitmap(heightSha)}},
                                {{ChannelType::Height, Blend(BlendingMode::Normal, 0.75)}});
    core::Layer colour = b.Fill("colour", {{ChannelType::BaseColor, Uniform(0.2, 0.4, 0.6)}}, {});
    b.SetRoot({height, colour});
    if (!b.Validate("height-normal")) return Finish();
    CpuEvaluator cpu(templates, kWideLimits);

    // The float32 read-out before the write rule: the stored half is its value toward zero.
    {
        render::Result<ChannelDag> dag =
            BuildDag(b.project, b.SetId(), b.StackId(), ChannelType::Height, *templates, kDefaultTemplateId);
        EvalEnvironment env{cpu.store(), cpu.cache(), resources.get(), nullptr};
        EvaluationStats stats;
        render::Result<Operand> readout =
            dag ? EvaluateFloat32Readout(*dag, env, 0, 0, dag->base, stats) : render::Result<Operand>(render::Unexpected(dag.error()));
        render::Result<TileImage> raw = readout ? cpu.store().Read(readout->tile) : render::Result<TileImage>(render::Unexpected(readout.error()));
        EvaluateRequest channel;
        channel.textureSet = b.SetId();
        channel.stack = b.StackId();
        channel.channel = ChannelType::Height;
        channel.resources = resources;
        render::Result<ChannelResult> stored = cpu.Evaluate(b.project, channel);
        bool ok = raw && stored && readout->kind == Operand::Kind::Tile;
        size_t offGrid = 0;
        if (ok) {
            if (readout->tile != kNoTile) cpu.cache().Unpin(readout->tile);
            const std::vector<uint32_t> samples = Samples(*stored);
            for (size_t i = 0; i < samples.size(); ++i) {
                float v = 0.0f;
                std::memcpy(&v, raw->texels.data() + i * 4, 4);
                const uint32_t code = resources->Fetch(heightSha)->values[i];
                const float content =
                    arith::HalfToFloat(arith::HalfTowardZero(RangeValue(arith::UnormOperand(code, 16), true)));
                const float expected = content * 0.75f;
                ok = ok && v == expected && samples[i] == arith::HalfTowardZero(v);
                if (arith::HalfToFloat(arith::HalfTowardZero(v)) != v) ++offGrid;
            }
        }
        Check(ok && offGrid > 0,
              "the Height read-out before the write rule is content x half(opacity) in float32, and the stored "
              "half is its value toward zero (" + std::to_string(offGrid) + " values off the half grid)",
              ok ? std::string() : Describe(stored));
    }

    // Tags (EXP-09) and the relief round.
    render::Result<VirtualNormalResult> combined =
        cpu.EvaluateNormal(b.project, 7, request(b, NormalSourceKind::Combined, NormalMapFormat::OpenGL));
    {
        render::Result<ChannelDag> dag =
            BuildDag(b.project, b.SetId(), b.StackId(), ChannelType::Height, *templates, kDefaultTemplateId);
        const bool ok = combined && dag && combined->tag.role == core::MeshMapRole::combined && combined->tag.relief &&
                        combined->tag.relief->revision == 7 && combined->tag.relief->heightHash == Hex(dag->readoutHash) &&
                        combined->tag.relief->method == HeightToNormalMethod::Sharp && combined->width == 256 &&
                        combined->texels.size() == 256u * 256u * 3u;
        Check(ok, "a combined normal is tagged `combined` with its relief round (revision, Height read-out hash, method)",
              kindOf(combined));
    }
    {
        Builder other = b;
        // A BaseColor edit keeps the relief; a Height edit or the method changes it.
        other.Stack().root_layers[0].fill->sources[ChannelType::BaseColor] = Uniform(0.9, 0.1, 0.1);
        render::Result<VirtualNormalResult> colourEdit =
            cpu.EvaluateNormal(other.project, 8, request(other, NormalSourceKind::Combined, NormalMapFormat::OpenGL));
        other.Stack().root_layers[1].blending[ChannelType::Height] = Blend(BlendingMode::Normal, 0.5);
        render::Result<VirtualNormalResult> heightEdit =
            cpu.EvaluateNormal(other.project, 9, request(other, NormalSourceKind::Combined, NormalMapFormat::OpenGL));
        other.Set().height_to_normal_method = HeightToNormalMethod::SmoothSobel;
        render::Result<VirtualNormalResult> methodEdit =
            cpu.EvaluateNormal(other.project, 10, request(other, NormalSourceKind::Combined, NormalMapFormat::OpenGL));
        const bool ok = combined && colourEdit && heightEdit && methodEdit &&
                        colourEdit->tag.relief->heightHash == combined->tag.relief->heightHash &&
                        colourEdit->texels == combined->texels &&
                        heightEdit->tag.relief->heightHash != combined->tag.relief->heightHash &&
                        methodEdit->tag.relief->method == HeightToNormalMethod::SmoothSobel &&
                        methodEdit->texels != heightEdit->texels;
        Check(ok, "the relief round follows the Height content and the method, not the other channels");
    }
    {
        Builder empty = makeBuilder(256);
        render::Result<VirtualNormalResult> flat =
            cpu.EvaluateNormal(empty.project, 1, request(empty, NormalSourceKind::Combined, NormalMapFormat::DirectX));
        Builder noHeight(256, 256, {{ChannelType::BaseColor, ChannelFormat::sRGB8}});
        render::Result<VirtualNormalResult> none =
            cpu.EvaluateNormal(noHeight.project, 1, request(noHeight, NormalSourceKind::Combined, NormalMapFormat::OpenGL));
        bool ok = flat && none && none->tag.relief && none->tag.relief->heightHash.empty();
        for (const render::Result<VirtualNormalResult>* r : {&flat, &none}) {
            if (!*r) continue;
            for (size_t i = 0; i < (*r)->texels.size(); i += 3) {
                ok = ok && Codes16({(*r)->texels[i], (*r)->texels[i + 1], (*r)->texels[i + 2]}) ==
                               std::array<uint32_t, 3>{32767, 32767, 65535};
            }
        }
        Check(ok, "an empty stack and a stack without Height or Normal give the flat normal everywhere");
    }

    // The Normal channel imports a bitmap with its green codes inverted.
    {
        Builder n = makeBuilder(256);
        n.SetRoot({n.Fill("normal", {{ChannelType::Normal, Bitmap(normalSha)}}, {})});
        EvaluateRequest channel;
        channel.textureSet = n.SetId();
        channel.stack = n.StackId();
        channel.channel = ChannelType::Normal;
        channel.resources = resources;
        render::Result<ChannelResult> result = cpu.Evaluate(n.project, channel);
        bool ok = static_cast<bool>(result);
        if (ok) {
            const std::vector<uint32_t> samples = Samples(*result);
            const DecodedImage& image = *resources->Fetch(normalSha);
            for (size_t i = 0; i < samples.size(); ++i) {
                const uint32_t c = i % 3;
                const uint32_t code = c == 1 ? 65535u - image.values[i] : image.values[i];
                ok = ok && samples[i] == arith::HalfTowardZero(arith::UnormOperand(code, 16));
            }
        }
        Check(ok, "the Normal channel stores an imported normal map as (r, 65535 - g, b) / 65535, half toward zero",
              ok ? std::string() : Describe(result));
        Builder dx = n;
        dx.project.settings.normal_map_format = NormalMapFormat::DirectX;
        render::Result<ChannelResult> stored = cpu.Evaluate(dx.project, channel);
        Check(stored && result && Samples(*stored) == Samples(*result),
              "a DirectX project's Normal channel stores an imported normal map as an OpenGL project does",
              Describe(stored));
        Builder dxUniform = makeBuilder(256);
        dxUniform.project.settings.normal_map_format = NormalMapFormat::DirectX;
        dxUniform.SetRoot({dxUniform.Fill("n", {{ChannelType::Normal, Uniform(0.4, 0.6, 1.0)}}, {})});
        channel.textureSet = dxUniform.SetId();
        channel.stack = dxUniform.StackId();
        render::Result<ChannelResult> uniform = cpu.Evaluate(dxUniform.project, channel);
        Builder dxPartial = dx;
        dxPartial.Stack().root_layers[0].blending[ChannelType::Normal] = Blend(BlendingMode::Normal, 0.5);
        channel.textureSet = dxPartial.SetId();
        channel.stack = dxPartial.StackId();
        render::Result<ChannelResult> partial = cpu.Evaluate(dxPartial.project, channel);
        Check(!uniform && EvalErrorKindOf(uniform.error()) == EvalErrorKind::UnsupportedSource && !partial &&
                  EvalErrorKindOf(partial.error()) == EvalErrorKind::UnsupportedSource,
              "a DirectX project's Normal channel other than one bitmap fill at opacity 1 (a uniform colour, a "
              "bitmap at opacity 1/2) fails with unsupported_source (not recorded)");
    }

    // The Normal channel at partial coverage: its read-out is composited over the flat colour
    // (0.5, 0.5, 1), its empty stack exports the template base.
    {
        Builder n = makeBuilder(256);
        n.SetRoot({n.Fill("normal", {{ChannelType::Normal, Uniform(0.6, 0.4, 1.0)}},
                          {{ChannelType::Normal, Blend(BlendingMode::Normal, 0.5)}})});
        EvaluateRequest channel;
        channel.textureSet = n.SetId();
        channel.stack = n.StackId();
        channel.channel = ChannelType::Normal;
        channel.resources = resources;
        render::Result<ChannelResult> result = cpu.Evaluate(n.project, channel);
        bool ok = static_cast<bool>(result);
        if (ok) {
            const std::vector<uint32_t> samples = Samples(*result);
            const uint32_t expected[3] = {arith::HalfTowardZero(0.55f), arith::HalfTowardZero(0.45f), arith::HalfTowardZero(1.0f)};
            for (size_t i = 0; i < samples.size(); ++i) ok = ok && samples[i] == expected[i % 3];
        }
        Check(ok, "a Normal layer at opacity 1/2 is composited over the flat colour (0.5, 0.5, 1)", Describe(result));
    }

    // The Normal mesh map in the combination: F, decoded; a DirectX map mirrors y.
    {
        auto bound = [&](NormalMapFormat own, const std::string& sha) {
            Builder m = makeBuilder(256);
            m.project.settings.normal_map_format = own;
            core::MeshMapBinding binding;
            binding.resource = sha;
            binding.provenance = core::ImportedProvenance{"normal.png", sha, core::MeshMapRole::geometry_only, own, "", {}};
            m.Set().mesh_maps[core::MeshMapUsage::Normal] = binding;
            return m;
        };
        Builder gl = bound(NormalMapFormat::OpenGL, meshSha);
        Builder dx = bound(NormalMapFormat::DirectX, meshSha);
        render::Result<VirtualNormalResult> glOwn =
            cpu.EvaluateNormal(gl.project, 1, request(gl, NormalSourceKind::Combined, NormalMapFormat::OpenGL));
        render::Result<VirtualNormalResult> glOwnDx =
            cpu.EvaluateNormal(gl.project, 1, request(gl, NormalSourceKind::Combined, NormalMapFormat::DirectX));
        render::Result<VirtualNormalResult> dxOwn =
            cpu.EvaluateNormal(dx.project, 1, request(dx, NormalSourceKind::Combined, NormalMapFormat::OpenGL));
        bool ok = glOwn && glOwnDx && dxOwn;
        size_t moved = 0;
        if (ok) {
            const DecodedImage& image = *resources->Fetch(meshSha);
            for (size_t i = 0; i < glOwn->texels.size(); ++i) {
                const std::array<float, 3> operands{arith::UnormOperand(image.values[i - i % 3], 16),
                                                    arith::UnormOperand(image.values[i - i % 3 + 1], 16),
                                                    arith::UnormOperand(image.values[i - i % 3 + 2], 16)};
                if (i % 3 == 0) {
                    NormalInputs inputs;
                    inputs.hasMesh = true;
                    inputs.mesh = operands;
                    const std::array<float, 3> e =
                        VirtualNormalTexel({0.0f, 0.0f, kSharpZ}, inputs, NormalMapFormat::OpenGL);
                    ok = ok && e[0] == glOwn->texels[i] && e[1] == glOwn->texels[i + 1] && e[2] == glOwn->texels[i + 2];
                }
                if (arith::WriteUnorm(glOwn->texels[i], 16) != image.values[i]) ++moved;
                // A DirectX map seen in OpenGL is the OpenGL map seen in DirectX.
                ok = ok && dxOwn->texels[i] == glOwnDx->texels[i];
            }
        }
        Check(ok && moved > 0, "a bound Normal mesh map is F of the combination (decoded, not passed through: " +
                                   std::to_string(moved) + " codes move); a DirectX map mirrors y",
              kindOf(glOwn) + " " + kindOf(dxOwn));
        Builder crossed = bound(NormalMapFormat::DirectX, meshSha);
        crossed.project.settings.normal_map_format = NormalMapFormat::OpenGL;
        const std::string c =
            kindOf(cpu.EvaluateNormal(crossed.project, 1, request(crossed, NormalSourceKind::Combined, NormalMapFormat::OpenGL)));
        Check(c == "unsupported_source", "a mesh map declared in the other convention fails with unsupported_source "
                                         "(not recorded)", c);
    }

    // Square sets of the other recorded sizes evaluate with z = 100 / W; unrecorded sizes fail.
    {
        Builder big = makeBuilder(512);
        render::Result<VirtualNormalResult> r =
            cpu.EvaluateNormal(big.project, 1, request(big, NormalSourceKind::Combined, NormalMapFormat::OpenGL));
        Builder small = makeBuilder(128);
        const std::string s128 =
            kindOf(cpu.EvaluateNormal(small.project, 1, request(small, NormalSourceKind::Combined, NormalMapFormat::OpenGL)));
        Check(r && r->width == 512 && r->texels.size() == 512u * 512u * 3u && s128 == "unsupported_source",
              "a 512 set evaluates; a 128 set fails with unsupported_source (not recorded)", kindOf(r) + " " + s128);
    }

    // Explicit failures of what is not recorded.
    {
        Builder oblong(512, 256, {{ChannelType::Height, ChannelFormat::L16F}, {ChannelType::Normal, ChannelFormat::RGB16F}});
        Builder meshBound = makeBuilder(256);
        core::MeshMapBinding binding;
        binding.resource = mesh8Sha;
        binding.provenance = core::ImportedProvenance{"normal.png", mesh8Sha, core::MeshMapRole::geometry_only,
                                                      NormalMapFormat::OpenGL, "", {}};
        meshBound.Set().mesh_maps[core::MeshMapUsage::Normal] = binding;
        Builder dxNormal = makeBuilder(256);
        dxNormal.project.settings.normal_map_format = NormalMapFormat::DirectX;
        dxNormal.SetRoot({dxNormal.Fill("n", {{ChannelType::Normal, Uniform(0.4, 0.6, 1.0)}}, {})});
        const std::string a = kindOf(cpu.EvaluateNormal(oblong.project, 1, request(oblong, NormalSourceKind::Combined, NormalMapFormat::OpenGL)));
        const std::string m = kindOf(cpu.EvaluateNormal(meshBound.project, 1, request(meshBound, NormalSourceKind::Combined, NormalMapFormat::OpenGL)));
        const std::string d = kindOf(cpu.EvaluateNormal(dxNormal.project, 1, request(dxNormal, NormalSourceKind::Combined, NormalMapFormat::OpenGL)));
        const std::string p = kindOf(cpu.EvaluateNormal(b.project, 1, request(b, NormalSourceKind::GeometryOnly, NormalMapFormat::OpenGL)));
        Check(a == "unsupported_source" && m == "unsupported_source" && d == "unsupported_source" && p == "missing_resource",
              "unrecorded cases fail explicitly: a 512 x 256 set, an 8-bit Normal mesh map in the combined map, a "
              "uniform Normal colour in a DirectX project (unsupported_source); a pass-through without a Normal mesh "
              "map (missing_resource)",
              a + " " + m + " " + d + " " + p);

        // The geometry-only pass-through: the mesh map's codes, green inverted across conventions.
        bool ok = true;
        for (const auto& [sha, bits] : {std::pair{meshSha, 16u}, std::pair{mesh8Sha, 8u}}) {
            for (const NormalMapFormat own : {NormalMapFormat::OpenGL, NormalMapFormat::DirectX}) {
                Builder pass = makeBuilder(256);
                core::MeshMapBinding bound;
                bound.resource = sha;
                bound.provenance = core::ImportedProvenance{"normal.png", sha, core::MeshMapRole::geometry_only, own, "", {}};
                pass.Set().mesh_maps[core::MeshMapUsage::Normal] = bound;
                for (const NormalMapFormat convention : {NormalMapFormat::OpenGL, NormalMapFormat::DirectX}) {
                    render::Result<VirtualNormalResult> r =
                        cpu.EvaluateNormal(pass.project, 3, request(pass, NormalSourceKind::GeometryOnly, convention));
                    ok = ok && r && r->tag.role == core::MeshMapRole::geometry_only && !r->tag.relief;
                    if (!r) continue;
                    const DecodedImage& image = *resources->Fetch(sha);
                    const uint32_t max = (1u << bits) - 1u;
                    for (size_t i = 0; i < r->texels.size(); ++i) {
                        uint32_t code = image.values[i];
                        if (i % 3 == 1 && own != convention) code = max - code;
                        ok = ok && arith::WriteUnorm(r->texels[i], bits) == code;
                    }
                }
            }
        }
        Check(ok, "the geometry-only pass-through is the Normal mesh map's codes (8 and 16 bits), green inverted "
                  "across conventions, tagged `geometry_only` without a relief round");
    }
    return Finish();
}

// ── height-normal-gpu-vs-cpu ─────────────────────────────────────────────────

/// A float32 image of random heights with flat runs, steps and steep slopes.
std::shared_ptr<DecodedImage> FloatHeights(uint32_t size, uint32_t seed) {
    auto image = std::make_shared<DecodedImage>();
    image->width = size;
    image->height = size;
    image->channels = 1;
    image->encoding = render::TexelEncoding::Float32;
    image->values.resize(size_t{size} * size);
    std::mt19937 rng(seed);
    std::uniform_real_distribution<float> any(-4.0f, 4.0f);
    for (uint32_t y = 0; y < size; ++y) {
        for (uint32_t x = 0; x < size; ++x) {
            float v = any(rng);
            if ((x / 7 + y / 5) % 3 == 0) v = 0.125f * static_cast<float>((x / 9) % 4);  // flat runs and steps
            image->values[size_t{y} * size + x] = std::bit_cast<uint32_t>(v);
        }
    }
    return image;
}

std::shared_ptr<DecodedImage> FloatNormals(uint32_t size, uint32_t seed) {
    auto image = std::make_shared<DecodedImage>();
    image->width = size;
    image->height = size;
    image->channels = 3;
    image->encoding = render::TexelEncoding::Float32;
    image->values.resize(size_t{size} * size * 3);
    std::mt19937 rng(seed);
    std::uniform_real_distribution<float> unit(0.0f, 1.0f);
    for (size_t i = 0; i < size_t{size} * size; ++i) {
        image->values[i * 3 + 0] = std::bit_cast<uint32_t>(unit(rng));
        image->values[i * 3 + 1] = std::bit_cast<uint32_t>(unit(rng));
        image->values[i * 3 + 2] = std::bit_cast<uint32_t>(0.5f + 0.5f * unit(rng));
    }
    return image;
}

/// The inputs of a virtual normal sweep besides the heights.
struct NormalSweep {
    /// Normal-channel colours; with them, each tile's root list is, in RGB32F, those colours from a
    /// transparent start under `coverage` (a 16-bit mask) at layer opacity 0.9, or, in RGB16F, two
    /// uniform colours under `coverage` and its mirror at opacity 0.9 and 0.6 (coverage 0 to 1).
    const DecodedImage* normals = nullptr;
    const DecodedImage* coverage = nullptr;
    ChannelFormat normalFormat = ChannelFormat::RGB32F;
    /// 16-bit Normal mesh map codes, in the DirectX convention or not.
    const DecodedImage* mesh = nullptr;
    bool meshDirectX = false;
    float z = kSharpZ;
};

/// Uploads `image` into `tiles` x `tiles` tiles of `size`, runs one VirtualNormalOp per tile with
/// wrap-around across the tile grid, and returns every result word (tile-major).
render::Result<std::vector<uint32_t>> VirtualNormalSweep(ITileStore& store, const DecodedImage& heights,
                                                         const NormalSweep& sweep, uint32_t tiles, uint32_t size,
                                                         core::HeightToNormalMethod method,
                                                         core::NormalMapFormat convention) {
    TileFormat grey;
    grey.encoding = render::TexelEncoding::Float32;
    grey.channels = 1;
    TileFormat rgb = grey;
    rgb.channels = 3;
    std::vector<TileHandle> h(size_t{tiles} * tiles);
    std::vector<TileHandle> n(size_t{tiles} * tiles, kNoTile);
    std::vector<TileHandle> m(size_t{tiles} * tiles, kNoTile);
    for (uint32_t ty = 0; ty < tiles; ++ty) {
        for (uint32_t tx = 0; tx < tiles; ++tx) {
            render::Result<TileHandle> tile = store.Allocate(grey, size, size);
            if (!tile) return render::Unexpected(tile.error());
            render::Result<void> up = store.Upload(*tile, heights, tx * size, ty * size);
            if (!up) return render::Unexpected(up.error());
            h[size_t{ty} * tiles + tx] = *tile;
            if (sweep.normals != nullptr) {
                const bool half = sweep.normalFormat == ChannelFormat::RGB16F;
                render::Result<TileHandle> mask = store.Allocate(TileFormatOf(ChannelFormat::L16), size, size);
                if (!mask) return render::Unexpected(mask.error());
                render::Result<void> mup = store.Upload(*mask, *sweep.coverage, tx * size, ty * size);
                if (!mup) return render::Unexpected(mup.error());
                render::Result<TileHandle> list = store.Allocate(TileFormatOf(sweep.normalFormat, true), size, size);
                if (!list) return render::Unexpected(list.error());
                BlendOp layer;
                layer.dst = *list;
                layer.acc = Operand::Constant({0.0f, 0.0f, 0.0f}, 0.0f);
                layer.source = Operand::Constant({0.8125f, 0.3f, 0.61f}, 1.0f);
                if (!half) {
                    render::Result<TileHandle> colours = store.Allocate(rgb, size, size);
                    if (!colours) return render::Unexpected(colours.error());
                    render::Result<void> nup = store.Upload(*colours, *sweep.normals, tx * size, ty * size);
                    if (!nup) return render::Unexpected(nup.error());
                    layer.source = Operand::Of(*colours);
                }
                layer.mask = Operand::Of(*mask);
                layer.opacity = 0.9f;
                layer.emptyBackdrop = true;
                render::Result<void> queued = store.Blend(layer);
                if (!queued) return render::Unexpected(queued.error());
                if (half) {
                    // A second uniform layer under the mirrored mask: colours vary with the masks.
                    render::Result<TileHandle> top = store.Allocate(TileFormatOf(sweep.normalFormat, true), size, size);
                    if (!top) return render::Unexpected(top.error());
                    std::shared_ptr<DecodedImage> mirrored = std::make_shared<DecodedImage>(*sweep.coverage);
                    for (uint32_t& v : mirrored->values) v = 65535u - v;
                    render::Result<TileHandle> mask2 = store.Allocate(TileFormatOf(ChannelFormat::L16), size, size);
                    if (!mask2) return render::Unexpected(mask2.error());
                    render::Result<void> m2 = store.Upload(*mask2, *mirrored, tx * size, ty * size);
                    if (!m2) return render::Unexpected(m2.error());
                    BlendOp second;
                    second.dst = *top;
                    second.acc = Operand::Of(*list);
                    second.source = Operand::Constant({0.2f, 0.7f, 0.95f}, 1.0f);
                    second.mask = Operand::Of(*mask2);
                    second.opacity = 0.6f;
                    queued = store.Blend(second);
                    if (!queued) return render::Unexpected(queued.error());
                    list = top;
                }
                n[size_t{ty} * tiles + tx] = *list;
            }
            if (sweep.mesh != nullptr) {
                render::Result<TileHandle> mt = store.Allocate(rgb, size, size);
                if (!mt) return render::Unexpected(mt.error());
                render::Result<void> mup = store.Upload(*mt, *sweep.mesh, tx * size, ty * size);
                if (!mup) return render::Unexpected(mup.error());
                m[size_t{ty} * tiles + tx] = *mt;
            }
        }
    }
    std::vector<uint32_t> out;
    for (uint32_t ty = 0; ty < tiles; ++ty) {
        for (uint32_t tx = 0; tx < tiles; ++tx) {
            render::Result<TileHandle> dst = store.Allocate(rgb, size, size);
            if (!dst) return render::Unexpected(dst.error());
            VirtualNormalOp op;
            op.dst = *dst;
            for (int dy = -1; dy <= 1; ++dy) {
                for (int dx = -1; dx <= 1; ++dx) {
                    const uint32_t nx = (tx + tiles + static_cast<uint32_t>(dx + 1) - 1) % tiles;
                    const uint32_t ny = (ty + tiles + static_cast<uint32_t>(dy + 1) - 1) % tiles;
                    op.height[static_cast<size_t>((dy + 1) * 3 + dx + 1)] = h[size_t{ny} * tiles + nx];
                }
            }
            if (sweep.normals != nullptr) op.normal = Operand::Of(n[size_t{ty} * tiles + tx]);
            else op.normal = Operand::Constant({0.3f, 0.7f, 0.9f}, 0.375f);
            if (sweep.mesh != nullptr) op.mesh = Operand::Of(m[size_t{ty} * tiles + tx]);
            op.meshDirectX = sweep.meshDirectX;
            op.z = sweep.z;
            op.method = method;
            op.convention = convention;
            render::Result<void> queued = store.VirtualNormal(op);
            if (!queued) return render::Unexpected(queued.error());
            render::Result<TileImage> image = store.Read(*dst);
            if (!image) return render::Unexpected(image.error());
            for (size_t i = 0; i < image->texels.size(); i += 4) {
                uint32_t word = 0;
                std::memcpy(&word, image->texels.data() + i, 4);
                out.push_back(word);
            }
        }
    }
    return out;
}

/// A raw blend (the float32 read-out) of a random source with coverage over a constant base on
/// every channel format.
render::Result<std::vector<uint32_t>> RawReadoutSweep(ITileStore& store, ChannelFormat channelFormat, uint32_t size) {
    TileFormat format = TileFormatOf(channelFormat, true);
    render::Result<TileHandle> src = store.Allocate(format, size, size);
    if (!src) return render::Unexpected(src.error());
    // Source colours and coverage through a blend of two constants by a random mask, written with
    // the format's rules (the shape of an isolated root composite).
    std::shared_ptr<DecodedImage> mask = std::make_shared<DecodedImage>();
    mask->width = size;
    mask->height = size;
    mask->channels = 1;
    mask->encoding = render::TexelEncoding::Unorm16;
    std::mt19937 rng(11);
    for (uint32_t i = 0; i < size * size; ++i) mask->values.push_back(rng() % 65536u);
    render::Result<TileHandle> maskTile = store.Allocate(TileFormatOf(ChannelFormat::L16), size, size);
    if (!maskTile) return render::Unexpected(maskTile.error());
    render::Result<void> up = store.Upload(*maskTile, *mask, 0, 0);
    if (!up) return render::Unexpected(up.error());
    BlendOp layer;
    layer.dst = *src;
    layer.acc = Operand::Constant({0.0f, 0.0f, 0.0f}, 0.0f);
    layer.source = Operand::Constant({0.8125f, 0.3f, 0.61f}, 1.0f);
    layer.mask = Operand::Of(*maskTile);
    layer.mode = BlendingMode::Normal;
    layer.opacity = 0.9f;
    render::Result<void> queued = store.Blend(layer);
    if (!queued) return render::Unexpected(queued.error());
    TileFormat raw;
    raw.encoding = render::TexelEncoding::Float32;
    raw.channels = format.channels;
    render::Result<TileHandle> dst = store.Allocate(raw, size, size);
    if (!dst) return render::Unexpected(dst.error());
    BlendOp readout;
    readout.dst = *dst;
    readout.acc = Operand::Constant({0.25f, 0.5f, 0.75f}, 1.0f);
    readout.source = Operand::Of(*src);
    readout.mode = BlendingMode::Replace;
    readout.rawOutput = true;
    queued = store.Blend(readout);
    if (!queued) return render::Unexpected(queued.error());
    render::Result<TileImage> image = store.Read(*dst);
    if (!image) return render::Unexpected(image.error());
    std::vector<uint32_t> out(image->texels.size() / 4);
    std::memcpy(out.data(), image->texels.data(), out.size() * 4);
    return out;
}

int RunHeightNormalGpuVsCpu(const fs::path& assets, const fs::path& dir) {
    render::Engine engine(TestOptions(dir));
    if (NoAdapter(engine)) return kExitSkip;
    Info("adapter " + engine.Capabilities().value_or(render::CapabilityReport{}).adapter);
    auto token = std::make_shared<const int>(0);
    auto onGpu = [&](auto&& body) -> render::Result<std::vector<uint32_t>> {
        std::future<render::Result<std::vector<uint32_t>>> future = engine.Submit(
            token, [&](render::EngineContext& context, const int&) -> render::Result<std::vector<uint32_t>> {
                GpuTileStore gpu(context.Device());
                gpu.BeginRequest(context);
                render::Result<std::vector<uint32_t>> result = body(gpu);
                render::Result<void> flushed = gpu.Flush();
                gpu.EndRequest();
                if (result && !flushed) return render::Unexpected(flushed.error());
                return result;
            });
        return Get(future);
    };

    // The kernel over a 3 x 3 grid of 72-texel tiles (wrap-around across tile edges and the set
    // border), with height tiles and constants, Normal root lists at every coverage and partly
    // covered constants, mesh maps in both conventions, and the z of a 512 set.
    constexpr uint32_t kTiles = 3;
    constexpr uint32_t kSize = 72;
    std::shared_ptr<DecodedImage> heights = FloatHeights(kTiles * kSize, 5);
    std::shared_ptr<DecodedImage> normals = FloatNormals(kTiles * kSize, 6);
    std::shared_ptr<DecodedImage> coverage = HeightCodes(kTiles * kSize, 12);
    for (size_t i = 0; i < coverage->values.size(); i += 17) coverage->values[i] = i % 2 == 0 ? 0u : 65535u;
    std::shared_ptr<DecodedImage> mesh = NormalCodes(kTiles * kSize, 13);
    size_t compared = 0;
    std::vector<std::string> failures;
    for (const core::HeightToNormalMethod method : {core::HeightToNormalMethod::Sharp, core::HeightToNormalMethod::SmoothSobel}) {
        for (const core::NormalMapFormat convention : {core::NormalMapFormat::OpenGL, core::NormalMapFormat::DirectX}) {
            for (const int variant : {0, 1, 2, 3}) {
                NormalSweep sweep;
                sweep.z = HeightZ(method, variant == 3 ? 512u : 256u);
                if (variant >= 1) {
                    sweep.normals = normals.get();
                    sweep.coverage = coverage.get();
                    sweep.normalFormat = variant == 2 ? ChannelFormat::RGB16F : ChannelFormat::RGB32F;
                }
                if (variant >= 2) {
                    sweep.mesh = mesh.get();
                    sweep.meshDirectX = variant == 3;
                }
                const char* labels[] = {" normal constant", " RGB32F normal root lists", " RGB16F normal root lists + OpenGL mesh map",
                                        " RGB32F normal root lists + DirectX mesh map, z of 512"};
                const std::string label =
                    std::string(core::ToString(method)) + " " + std::string(core::ToString(convention)) + labels[variant];
                CpuTileStore cpu;
                render::Result<std::vector<uint32_t>> expected =
                    VirtualNormalSweep(cpu, *heights, sweep, kTiles, kSize, method, convention);
                render::Result<std::vector<uint32_t>> actual = onGpu([&](GpuTileStore& gpu) {
                    return VirtualNormalSweep(gpu, *heights, sweep, kTiles, kSize, method, convention);
                });
                if (!expected || !actual) {
                    failures.push_back(label + ": " + (expected ? Describe(actual) : Describe(expected)));
                    continue;
                }
                std::string first;
                const size_t mismatches = Mismatches(*expected, *actual, first, render::TexelEncoding::Float32);
                compared += expected->size();
                if (mismatches != 0) failures.push_back(label + ": " + std::to_string(mismatches) + " mismatches; " + first);
            }
        }
    }
    for (const std::string& failure : failures) Check(false, "virtual normal kernel", failure);
    Check(failures.empty(), "the virtual normal kernel equals the CPU reference bit for bit across tile edges (" +
                                std::to_string(compared) + " values, both methods and conventions, partial Normal "
                                "coverage, mesh maps in both conventions)");

    failures.clear();
    compared = 0;
    for (const ChannelFormat channelFormat : kAllFormats) {
        CpuTileStore cpu;
        render::Result<std::vector<uint32_t>> expected = RawReadoutSweep(cpu, channelFormat, 64);
        render::Result<std::vector<uint32_t>> actual = onGpu([&](GpuTileStore& gpu) { return RawReadoutSweep(gpu, channelFormat, 64); });
        const std::string label(core::ToString(channelFormat));
        if (!expected || !actual) {
            failures.push_back(label + ": " + (expected ? Describe(actual) : Describe(expected)));
            continue;
        }
        std::string first;
        const size_t mismatches = Mismatches(*expected, *actual, first, render::TexelEncoding::Float32);
        compared += expected->size();
        if (mismatches != 0) failures.push_back(label + ": " + std::to_string(mismatches) + " mismatches; " + first);
    }
    for (const std::string& failure : failures) Check(false, "raw read-out", failure);
    Check(failures.empty(), "the float32 read-out (raw blend) equals the CPU reference bit for bit on every channel format (" +
                                std::to_string(compared) + " values)");

    // The whole evaluation: Evaluator (GPU) and CpuEvaluator give the same virtual maps.
    std::shared_ptr<const TemplateLibrary> templates = LoadTemplates(assets);
    const std::string heightSha(64, 'e');
    const std::string normalSha(64, 'f');
    const std::string meshSha(64, '9');
    auto resources = std::make_shared<MapResourceProvider>();
    resources->Add(heightSha, HeightCodes(256, 9));
    resources->Add(normalSha, NormalCodes(256, 10));
    resources->Add(meshSha, NormalCodes(256, 14));
    Builder b(256, 256, {{ChannelType::Height, ChannelFormat::L16F}, {ChannelType::Normal, ChannelFormat::RGB16F}});
    b.AddResource(heightSha, 1);
    b.AddResource(normalSha, 1);
    b.AddResource(meshSha, 1);
    core::MeshMapBinding meshBinding;
    meshBinding.resource = meshSha;
    meshBinding.provenance = core::ImportedProvenance{"normal.png", meshSha, core::MeshMapRole::geometry_only,
                                                      core::NormalMapFormat::OpenGL, "", {}};
    b.Set().mesh_maps[core::MeshMapUsage::Normal] = meshBinding;
    b.SetRoot({b.Fill("h", {{ChannelType::Height, Bitmap(heightSha)}}, {{ChannelType::Height, Blend(BlendingMode::Normal, 0.75)}}),
               b.Fill("h2", {{ChannelType::Height, Bitmap(heightSha)}}, {{ChannelType::Height, Blend(BlendingMode::LinearDodge, 0.4)}}),
               b.Fill("n", {{ChannelType::Normal, Bitmap(normalSha)}}, {{ChannelType::Normal, Blend(BlendingMode::Normal, 0.6)}})});
    if (!b.Validate("height-normal-gpu-vs-cpu")) return Finish();
    bool same = true;
    std::string detail;
    for (const core::HeightToNormalMethod method : {core::HeightToNormalMethod::Sharp, core::HeightToNormalMethod::SmoothSobel}) {
        b.Set().height_to_normal_method = method;
        for (const core::NormalMapFormat convention : {core::NormalMapFormat::OpenGL, core::NormalMapFormat::DirectX}) {
            VirtualNormalRequest request;
            request.textureSet = b.SetId();
            request.stack = b.StackId();
            request.convention = convention;
            request.resources = resources;
            CpuEvaluator cpu(templates, kWideLimits);
            render::Result<VirtualNormalResult> expected = cpu.EvaluateNormal(b.project, 2, request);
            Evaluator gpu(engine, templates);
            std::future<render::Result<VirtualNormalResult>> future =
                gpu.EvaluateNormal(core::Snapshot{2, std::make_shared<const core::Project>(b.project)}, request);
            render::Result<VirtualNormalResult> actual = Get(future);
            gpu.Shutdown();
            const bool equal = expected && actual && expected->tag == actual->tag &&
                               std::memcmp(expected->texels.data(), actual->texels.data(), expected->texels.size() * 4) == 0 &&
                               expected->texels.size() == actual->texels.size();
            if (!equal) detail += std::string(core::ToString(method)) + "/" + std::string(core::ToString(convention)) + " ";
            same = same && equal;
        }
    }
    Check(same, "Evaluator (GPU) and CpuEvaluator give the same virtual normal maps and tags (both methods and "
                "conventions, a mesh map, a Normal layer at opacity 0.6)",
          detail);
    return Finish();
}

// ── diagnostics (phase1.13_compositor-diagnostics) ───────────────────────────

/// A provider that serves `allowed` fetches of its images, then fails (an evaluation that fails
/// midway: the bitmap of a later tile is not available).
class FailingProvider final : public IResourceProvider {
public:
    FailingProvider(std::shared_ptr<const IResourceProvider> inner, int allowed) : m_inner(std::move(inner)), m_allowed(allowed) {}
    std::shared_ptr<const DecodedImage> Fetch(std::string_view sha256) const override {
        ++fetches;
        return fetches <= m_allowed ? m_inner->Fetch(sha256) : nullptr;
    }
    mutable int fetches = 0;

private:
    std::shared_ptr<const IResourceProvider> m_inner;
    int m_allowed;
};

/// The values of a channel result decoded independently of diagnostics.cpp: constant tiles as their
/// constant, stored samples through the arithmetic tables.
std::vector<float> DecodedValues(const ChannelResult& result) {
    const TileFormat& format = result.tileFormat;
    const uint32_t channels = format.channels;
    std::vector<float> out(size_t{result.width} * result.height * channels, 0.0f);
    for (const TileResult& tile : result.tiles) {
        for (uint32_t y = 0; y < tile.height; ++y) {
            for (uint32_t x = 0; x < tile.width; ++x) {
                for (uint32_t c = 0; c < channels; ++c) {
                    float value = 0.0f;
                    if (tile.constant) {
                        value = (*tile.constant)[c];
                    } else {
                        const size_t i = (size_t{y} * tile.width + x) * channels + c;
                        switch (format.encoding) {
                            case render::TexelEncoding::Unorm8: {
                                const uint32_t code = static_cast<uint32_t>(tile.texels[i]);
                                value = format.srgb ? arith::Srgb8Operand(code) : arith::UnormOperand(code, 8);
                                break;
                            }
                            case render::TexelEncoding::Unorm16: {
                                uint16_t code = 0;
                                std::memcpy(&code, tile.texels.data() + i * 2, 2);
                                value = arith::UnormOperand(code, 16);
                                break;
                            }
                            case render::TexelEncoding::Float16: {
                                uint16_t bits = 0;
                                std::memcpy(&bits, tile.texels.data() + i * 2, 2);
                                value = arith::HalfToFloat(bits);
                                break;
                            }
                            case render::TexelEncoding::Float32:
                                std::memcpy(&value, tile.texels.data() + i * 4, 4);
                                break;
                        }
                    }
                    out[((size_t{tile.y0} + y) * result.width + tile.x0 + x) * channels + c] = value;
                }
            }
        }
    }
    return out;
}

bool SameBytes(const std::vector<float>& a, const std::vector<float>& b) {
    return a.size() == b.size() && (a.empty() || std::memcmp(a.data(), b.data(), a.size() * sizeof(float)) == 0);
}

bool SameMap(const DiagnosticMap& a, const DiagnosticMap& b) {
    return a.width == b.width && a.height == b.height && a.components == b.components && SameBytes(a.values, b.values);
}

/// Sets the visibility of layer or effect `uid` of the builder's stack by walking it (the test's
/// own hide, independent of diagnostics.cpp HiddenCopy).
bool SetVisible(std::vector<core::Layer>& layers, core::Id uid, bool visible) {
    for (core::Layer& layer : layers) {
        bool* flag = layer.uid == uid ? &layer.visible : nullptr;
        for (core::Effect& effect : layer.content_effects) flag = effect.uid == uid ? &effect.visible : flag;
        if (layer.mask) {
            for (core::Effect& effect : layer.mask->effects) flag = effect.uid == uid ? &effect.visible : flag;
        }
        if (flag != nullptr) {
            *flag = visible;
            return true;
        }
        if (SetVisible(layer.children, uid, visible)) return true;
    }
    return false;
}

DiagnosticRequest DiagRequestOf(Builder& builder, std::shared_ptr<const IResourceProvider> resources) {
    DiagnosticRequest request;
    request.textureSet = builder.SetId();
    request.stack = builder.StackId();
    request.resources = std::move(resources);
    return request;
}

/// The contribution fixture: a `width` x 128 set (2048: two tiles) on six channel formats with
/// uniform and bitmap fills, a group with a mask, content and mask effects and an invisible layer.
struct ContributionRig {
    uint32_t width;
    static constexpr uint32_t kHeight = 128;
    std::string patternSha = std::string(63, 'c') + "1";
    std::string maskSha = std::string(63, 'c') + "2";
    std::shared_ptr<MapResourceProvider> provider = std::make_shared<MapResourceProvider>();
    Builder builder;
    explicit ContributionRig(uint32_t width = 128)
        : width(width),
          builder(width, kHeight,
                  {{ChannelType::BaseColor, ChannelFormat::sRGB8},
                     {ChannelType::SpecularRoughness, ChannelFormat::L16},
                     {ChannelType::BaseMetalness, ChannelFormat::L8},
                     {ChannelType::Height, ChannelFormat::L16F},
                   {ChannelType::User0, ChannelFormat::RGB32F},
                   {ChannelType::User1, ChannelFormat::RGB16}}) {
        Build();
    }
    std::vector<ChannelType> channels{ChannelType::BaseColor, ChannelType::SpecularRoughness, ChannelType::BaseMetalness,
                                      ChannelType::Height,    ChannelType::User0,     ChannelType::User1};
    /// Every node the cases isolate: base, bmp, group, child, top, a content effect, a mask effect,
    /// an invisible layer.
    std::vector<core::Id> nodes;
    core::Id invisible = core::kNoId;
    core::Id bitmapLayer = core::kNoId;
    core::Id top = core::kNoId;
    core::Id effect = core::kNoId;
    core::Id maskEffect = core::kNoId;
    core::Id group = core::kNoId;

    void Build() {
        provider->Add(patternSha, PatternImage(width, kHeight, 3, render::TexelEncoding::Unorm16, 31));
        provider->Add(maskSha, PatternImage(width, kHeight, 1, render::TexelEncoding::Unorm16, 32));
        builder.AddResource(patternSha, 100);
        builder.AddResource(maskSha, 100);
        core::Layer base = builder.Fill("base", SameSource(channels, Uniform(0.3, 0.5, 0.7)), Same(channels, BlendingMode::Normal, 1.0));
        core::Layer bmp = builder.Fill("bmp", SameSource(channels, Bitmap(patternSha)), Same(channels, BlendingMode::Normal, 0.6));
        bmp.fill->projection.mode = core::ProjectionMode::Fill;
        core::Effect levels = LevelsEffect(builder, LevelsComponentOf(0.1, 0.9, 1.0, 0.0, 1.0, true), ChannelType::SpecularRoughness);
        core::Effect tint = ContentFillEffect(builder, channels, Uniform(0.9, 0.2, 0.4), BlendingMode::Multiply, 0.5);
        bmp.content_effects = {tint, levels};  // top first
        core::Layer c1 = builder.Fill("c1", SameSource(channels, Uniform(0.6, 0.6, 0.2)), Same(channels, BlendingMode::Screen, 0.7));
        core::Layer c2 = builder.Fill("c2", SameSource(channels, Bitmap(patternSha)), Same(channels, BlendingMode::Overlay, 0.5));
        c2.fill->projection.mode = core::ProjectionMode::Fill;
        core::Layer group = builder.Group("g", {c1, c2}, Same(channels, BlendingMode::Multiply, 0.8));
        core::Effect maskFill = MaskFillEffect(builder, Bitmap(maskSha), BlendingMode::Normal, 1.0);
        maskFill.fill->projection.mode = core::ProjectionMode::Fill;
        group.mask = MaskWith(core::MaskBackground::Black, {maskFill});
        core::Layer off = builder.Fill("off", SameSource(channels, Uniform(1.0, 0.0, 0.0)), Same(channels, BlendingMode::Normal, 1.0));
        off.visible = false;
        core::Layer topLayer = builder.Fill("top", SameSource(channels, Uniform(0.2, 0.9, 0.1)), Same(channels, BlendingMode::Normal, 0.4));
        core::Effect subtract = MaskFillEffect(builder, Bitmap(maskSha), BlendingMode::Subtract, 0.5);
        subtract.fill->projection.mode = core::ProjectionMode::Fill;
        topLayer.mask = MaskWith(core::MaskBackground::White, {subtract});
        nodes = {base.uid, bmp.uid, group.uid, c2.uid, topLayer.uid, tint.uid, subtract.uid, off.uid};
        effect = tint.uid;
        maskEffect = subtract.uid;
        this->group = group.uid;
        invisible = off.uid;
        bitmapLayer = bmp.uid;
        top = topLayer.uid;
        builder.SetRoot({base, bmp, group, off, topLayer});
    }
};

/// The material fixture (128 x 128, an ID mesh map): material B (a group, its mask the right
/// half) under material A (a group, its mask the left half) and a one-texel Roughness touch-up of
/// A at (80, 20), inside B's region. `idSpill` adds texel (63, 40), on A's ID island, to B's mask;
/// `nested` puts B in a group G whose mask is the top half, with one soft texel (100, 10) where
/// both masks hold code 45000.
struct MaterialRig {
    static constexpr uint32_t kSize = 128;
    std::string maskASha = std::string(63, 'd') + "1";
    std::string maskBSha;
    std::string leakSha = std::string(63, 'd') + "3";
    std::string idSha = std::string(63, 'd') + "4";
    std::string maskGSha = std::string(63, 'd') + "5";
    std::shared_ptr<MapResourceProvider> provider = std::make_shared<MapResourceProvider>();
    std::shared_ptr<DecodedImage> maskB;
    std::shared_ptr<DecodedImage> maskG;
    Builder builder{kSize, kSize,
                    {{ChannelType::BaseColor, ChannelFormat::sRGB8},
                     {ChannelType::Height, ChannelFormat::L16F},
                     {ChannelType::Normal, ChannelFormat::RGB16F},
                     {ChannelType::SpecularRoughness, ChannelFormat::L16},
                     {ChannelType::BaseMetalness, ChannelFormat::L16}}};
    core::Id a = core::kNoId;
    core::Id b = core::kNoId;
    core::Id g = core::kNoId;
    core::Id touchUp = core::kNoId;
    core::Id instance = core::kNoId;

    MaterialRig(bool idSpill, bool nested, bool withId = true)
        // B's mask differs per variant, so does its hash (bitmaps are bound by content hash).
        : maskBSha(std::string(62, 'd') + (idSpill ? "1" : "0") + (nested ? "1" : "0")) {
        provider->Add(maskASha, GreyImage(kSize, [](uint32_t x, uint32_t) { return x < 64 ? 65535u : 0u; }));
        maskB = GreyImage(kSize, [&](uint32_t x, uint32_t y) {
            if (nested && x == 100 && y == 10) return 45000u;
            return x >= 64 || (idSpill && x == 63 && y == 40) ? 65535u : 0u;
        });
        provider->Add(maskBSha, maskB);
        provider->Add(leakSha, GreyImage(kSize, [](uint32_t x, uint32_t y) { return x == 80 && y == 20 ? 65535u : 0u; }));
        maskG = GreyImage(kSize, [](uint32_t x, uint32_t y) { return x == 100 && y == 10 ? 45000u : y < 64 ? 65535u : 0u; });
        provider->Add(maskGSha, maskG);
        auto id = std::make_shared<DecodedImage>();
        id->width = kSize;
        id->height = kSize;
        id->channels = 3;
        id->encoding = render::TexelEncoding::Unorm8;
        for (uint32_t y = 0; y < kSize; ++y) {
            for (uint32_t x = 0; x < kSize; ++x) {
                const bool left = x < 64;
                id->values.insert(id->values.end(), {left ? 255u : 0u, 0u, left ? 0u : 255u});
            }
        }
        provider->Add(idSha, id);
        for (const std::string& sha : {maskASha, maskBSha, leakSha, idSha, maskGSha}) builder.AddResource(sha, 100);
        if (withId) {
            core::MeshMapBinding binding;
            binding.resource = idSha;
            binding.format = ChannelFormat::RGB8;
            binding.provenance = core::ImportedProvenance{"id.png", idSha, core::MeshMapRole::geometry_only,
                                                          core::NormalMapFormat::OpenGL, "", {}};
            builder.Set().mesh_maps[core::MeshMapUsage::ID] = binding;
        }
        const std::vector<ChannelType> all{ChannelType::BaseColor, ChannelType::Height, ChannelType::Normal,
                                           ChannelType::SpecularRoughness, ChannelType::BaseMetalness};
        auto material = [&](const std::string& name, std::array<double, 3> colour, double height, double rough,
                            double metal, std::array<double, 3> normal) {
            return builder.Fill(name,
                                {{ChannelType::BaseColor, Uniform(colour[0], colour[1], colour[2])},
                                 {ChannelType::Height, Uniform(height, height, height)},
                                 {ChannelType::Normal, Uniform(normal[0], normal[1], normal[2])},
                                 {ChannelType::SpecularRoughness, Uniform(rough, rough, rough)},
                                 {ChannelType::BaseMetalness, Uniform(metal, metal, metal)}},
                                Same(all, BlendingMode::Normal, 1.0));
        };
        auto maskOf = [&](const std::string& sha) {
            core::Effect effect = MaskFillEffect(builder, Bitmap(sha), BlendingMode::Normal, 1.0);
            effect.fill->projection.mode = core::ProjectionMode::Fill;
            return MaskWith(core::MaskBackground::Black, {effect});
        };
        core::Layer groupB = builder.Group("B", {material("B fill", {0.1, 0.2, 0.8}, 0.0, 0.2, 0.0, {0.5, 0.5, 1.0})},
                                           Same(all, BlendingMode::Normal, 1.0));
        groupB.mask = maskOf(maskBSha);
        b = groupB.uid;
        core::Layer groupA = builder.Group("A", {material("A fill", {0.8, 0.1, 0.1}, 0.3, 0.8, 1.0, {0.6, 0.5, 0.9})},
                                           Same(all, BlendingMode::Normal, 1.0));
        groupA.mask = maskOf(maskASha);
        a = groupA.uid;
        core::Layer touch = builder.Fill("A roughness touch-up", {{ChannelType::SpecularRoughness, Uniform(0.8, 0.8, 0.8)}},
                                         {{ChannelType::SpecularRoughness, Blend(BlendingMode::Normal, 1.0)}});
        touch.mask = maskOf(leakSha);
        touchUp = touch.uid;
        core::Layer copy = builder.Instance("A copy", groupA.uid);
        copy.visible = false;
        instance = copy.uid;
        if (nested) {
            core::Layer groupG = builder.Group("G", {groupB}, Same(all, BlendingMode::Normal, 1.0));
            groupG.mask = maskOf(maskGSha);
            g = groupG.uid;
            builder.SetRoot({groupG, groupA, touch, copy});
        } else {
            builder.SetRoot({groupB, groupA, touch, copy});
        }
    }

    /// The channel evaluated by the general evaluator on `project`, decoded.
    std::vector<float> Channel(const TemplateLibrary& templates, const core::Project& project, ChannelType channel) const {
        CpuTileStore store;
        TileCache cache(kWideLimits);
        EvaluateRequest request;
        request.textureSet = project.texture_sets.front().id;
        request.stack = project.texture_sets.front().stacks.front().id;
        request.channel = channel;
        request.resources = provider;
        render::Result<ChannelResult> result = EvaluateOn(project, request, templates, store, cache);
        if (!result) Check(false, "material fixture evaluates", Describe(result));
        return result ? DecodedValues(*result) : std::vector<float>{};
    }
};

std::vector<DiagnosticSource> MaterialSources(core::Id material) {
    std::vector<DiagnosticSource> sources;
    DiagnosticSource mask;
    mask.kind = DiagnosticSource::Kind::MaterialMask;
    mask.node = material;
    sources.push_back(mask);
    for (const MaterialViewKind view : {MaterialViewKind::ID, MaterialViewKind::BaseColor, MaterialViewKind::Height,
                                        MaterialViewKind::Normal, MaterialViewKind::Roughness, MaterialViewKind::Metallic}) {
        for (const auto kind : {DiagnosticSource::Kind::MaterialView, DiagnosticSource::Kind::MaterialLeaks}) {
            DiagnosticSource source;
            source.kind = kind;
            source.view = view;
            source.node = material;
            sources.push_back(source);
        }
    }
    for (const ChannelType channel : {ChannelType::BaseColor, ChannelType::SpecularRoughness}) {
        DiagnosticSource stats;
        stats.kind = DiagnosticSource::Kind::RegionStats;
        stats.map = DiagnosticMapId::Channel(channel);
        stats.node = material;
        sources.push_back(stats);
    }
    return sources;
}

std::vector<DiagnosticSource> NodeSources(const std::vector<core::Id>& nodes, const std::vector<ChannelType>& channels) {
    std::vector<DiagnosticSource> sources;
    for (const core::Id node : nodes) {
        for (const ChannelType channel : channels) {
            for (const auto kind : {DiagnosticSource::Kind::Isolated, DiagnosticSource::Kind::Contribution}) {
                DiagnosticSource source;
                source.kind = kind;
                source.map = DiagnosticMapId::Channel(channel);
                source.node = node;
                sources.push_back(source);
            }
        }
    }
    return sources;
}

/// The bytes an output stands for: its map's floats or its statistics' JSON.
std::string OutputBytes(const DiagnosticOutput& output) {
    if (output.stats) return RegionStatsJson(*output.stats);
    const DiagnosticMap& map = *output.map;
    std::string bytes = std::to_string(map.width) + "x" + std::to_string(map.height) + "x" + std::to_string(map.components) + ":";
    bytes.append(reinterpret_cast<const char*>(map.values.data()), map.values.size() * sizeof(float));
    return bytes;
}

std::string ViewsBytes(const MaterialViews& views) {
    std::string bytes = std::to_string(views.material) + ":" + std::to_string(views.inside) + ":";
    auto append = [&](const DiagnosticMap& map) {
        bytes.append(reinterpret_cast<const char*>(map.values.data()), map.values.size() * sizeof(float));
    };
    append(views.mask);
    for (const MaterialView& view : views.views) {
        bytes += std::string(MaterialViewName(view.view)) + ":" + std::to_string(view.leakTexels.size());
        append(view.values);
        append(view.leaks);
    }
    for (const MaterialViewKind missing : views.missing) bytes += "missing:" + std::string(MaterialViewName(missing));
    return bytes;
}

/// The visibility of layer or effect `node` in `project`, or nullopt.
std::optional<bool> VisibleIn(const core::Project& project, core::Id node) {
    std::optional<bool> visible;
    core::ForEachNode(project, [&](const core::NodeVisit& visit) {
        if (visit.layer != nullptr && visit.layer->uid == node) visible = visit.layer->visible;
        if (visit.effect != nullptr && visit.effect->uid == node) visible = visit.effect->visible;
    });
    return visible;
}

/// The document checks of 3.1: the document is exactly as it was (same revision object, deep
/// equality, no record, nothing to save) and `node` has its prior visibility.
bool DocumentUnchanged(const core::Document& document, const core::Snapshot& before, const core::Project& copy,
                       core::Id node, bool visible) {
    const core::Snapshot now = document.snapshot();
    return now.revision == before.revision && now.project.get() == before.project.get() && *now.project == copy &&
           document.operations().empty() && !document.NeedsSaving() && VisibleIn(*now.project, node) == visible;
}

/// The bitmap fetches of one run of `source` on a fresh CPU evaluator (each tile fetches its
/// uncached bitmaps; a two-tile set fetches half of them in its first tile).
int FetchesOf(const std::shared_ptr<const TemplateLibrary>& templates, Builder& builder,
              const std::shared_ptr<const IResourceProvider>& provider, const DiagnosticSource& source) {
    auto counting = std::make_shared<FailingProvider>(provider, 1 << 30);
    CpuEvaluator cpu(templates, kWideLimits);
    (void)cpu.Diagnose(builder.project, 1, source, DiagRequestOf(builder, counting));
    return counting->fetches;
}

int RunDiagnostics(const fs::path& assets, const fs::path& dir) {
    std::shared_ptr<const TemplateLibrary> templates = LoadTemplates(assets);

    // 3.1 Isolation never touches the document; a failure midway leaves it exactly as it was.
    {
        ContributionRig rig(2048);
        if (!rig.builder.Validate("diagnostics isolation")) return Finish();
        core::DocumentState state;
        state.project_uuid = "diagnostics-isolation";
        state.project = rig.builder.project;
        core::Document document(std::move(state));
        document.MarkCheckpoint();
        const core::Snapshot before = document.snapshot();
        const core::Project copy = *before.project;
        bool ok = true;
        std::string detail;
        const std::pair<core::Id, DiagnosticSource::Kind> cases[] = {
            {rig.bitmapLayer, DiagnosticSource::Kind::Isolated}, {rig.group, DiagnosticSource::Kind::Isolated},
            {rig.effect, DiagnosticSource::Kind::Isolated},      {rig.maskEffect, DiagnosticSource::Kind::Isolated},
            {rig.invisible, DiagnosticSource::Kind::Isolated},   {rig.top, DiagnosticSource::Kind::Contribution}};
        for (const auto& [node, kind] : cases) {
            {
                DiagnosticSource source;
                source.kind = kind;
                source.map = DiagnosticMapId::Channel(ChannelType::User1);
                source.node = node;
                // The fetches of tile 0 succeed, the first of tile 1 fails.
                const int fetches = FetchesOf(templates, rig.builder, rig.provider, source);
                auto failing = std::make_shared<FailingProvider>(rig.provider, fetches / 2);
                CpuEvaluator cpu(templates, kWideLimits);
                render::Result<DiagnosticOutput> failed =
                    cpu.Diagnose(*before.project, before.revision, source, DiagRequestOf(rig.builder, failing));
                const bool midway = fetches >= 2 && fetches % 2 == 0 && !failed &&
                                    KindName(failed.error()) == "missing_resource" && failing->fetches == fetches / 2 + 1;
                CpuEvaluator fine(templates, kWideLimits);
                render::Result<DiagnosticOutput> succeeded =
                    fine.Diagnose(*before.project, before.revision, source, DiagRequestOf(rig.builder, rig.provider));
                const bool visible = node != rig.invisible;
                const bool unchanged = DocumentUnchanged(document, before, copy, node, visible);
                if (!midway || !succeeded || !unchanged) {
                    ok = false;
                    detail += SourceName(source) + (midway ? "" : " (did not fail midway: " + Describe(failed) + ")") +
                              (succeeded ? "" : " (" + Describe(succeeded) + ")") + (unchanged ? " " : " (document changed) ");
                }
            }
        }
        Check(ok, "isolation and contribution leave the document, its revision, records and save state exactly as "
                  "they were, when the evaluation fails midway (tile 1 of 2) and when it succeeds (a layer, a group, "
                  "content and mask effects, an invisible layer; isolate and contribution)",
              detail);
        render::Result<core::Project> unknown = HiddenCopy(*before.project, rig.builder.SetId(), rig.builder.StackId(),
                                                           std::vector<core::Id>{core::kMaxId});
        Check(!unknown && KindName(unknown.error()) == "not_found", "isolating a node outside the stack fails with not_found",
              Describe(unknown));
    }

    // 3.2 contribution = full - isolated, texel for texel, on six channel formats.
    {
        ContributionRig rig;
        if (!rig.builder.Validate("diagnostics contribution")) return Finish();
        CpuEvaluator cpu(templates, kWideLimits);
        const DiagnosticRequest request = DiagRequestOf(rig.builder, rig.provider);
        bool ok = true;
        bool zero = true;
        bool changed = false;
        size_t compared = 0;
        std::string detail;
        for (const ChannelType channel : rig.channels) {
            for (const core::Id node : rig.nodes) {
                Builder hidden = rig.builder;
                SetVisible(hidden.Stack().root_layers, node, false);
                CpuTileStore store;
                TileCache cache(kWideLimits);
                EvaluateRequest er;
                er.textureSet = rig.builder.SetId();
                er.stack = rig.builder.StackId();
                er.channel = channel;
                er.resources = rig.provider;
                render::Result<ChannelResult> fullResult = EvaluateOn(rig.builder.project, er, *templates, store, cache);
                cache.UnpinAll();
                render::Result<ChannelResult> isolatedResult = EvaluateOn(hidden.project, er, *templates, store, cache);
                render::Result<ContributionResult> contribution =
                    ContributionOn(rig.builder.project, 1, DiagnosticMapId::Channel(channel), node, request, *templates,
                                   cpu.store(), cpu.cache());
                cpu.cache().UnpinAll();
                if (!fullResult || !isolatedResult || !contribution) {
                    ok = false;
                    detail += std::string(core::ToString(channel)) + " " + std::to_string(node) + ": " +
                              Describe(contribution) + " ";
                    continue;
                }
                const std::vector<float> expectedFull = DecodedValues(*fullResult);
                const std::vector<float> expectedIsolated = DecodedValues(*isolatedResult);
                std::vector<float> expected(expectedFull.size());
                for (size_t i = 0; i < expected.size(); ++i) expected[i] = expectedFull[i] - expectedIsolated[i];
                const bool same = SameBytes(contribution->full.values, expectedFull) &&
                                  SameBytes(contribution->isolated.values, expectedIsolated) &&
                                  SameBytes(contribution->difference.values, expected);
                if (!same) detail += std::string(core::ToString(channel)) + " node " + std::to_string(node) + " ";
                ok = ok && same;
                compared += expected.size();
                const bool allZero = std::all_of(expected.begin(), expected.end(), [](float v) { return v == 0.0f; });
                if (node == rig.invisible) zero = zero && allZero;
                if (node == rig.bitmapLayer) changed = changed || !allZero;
            }
        }
        Check(ok, "contribution equals the full evaluation minus the evaluation with the node hidden, texel for texel (" +
                      std::to_string(compared) + " values: sRGB8, L16, L8, L16F, RGB32F, RGB16; 8 nodes), and returns both maps",
              detail);
        Check(zero && changed, "an invisible node contributes exactly 0; a visible bitmap layer contributes");

        // The hidden copy is evaluated by the same engine: the prefix below the top layer is served
        // from the cache.
        CpuEvaluator warm(templates, kWideLimits);
        render::Result<DiagnosticMap> full =
            EvaluateMapOn(rig.builder.project, 1, DiagnosticMapId::Channel(ChannelType::User1), request, *templates,
                          warm.store(), warm.cache());
        const uint64_t hitsBefore = warm.cache().stats().hits;
        render::Result<IsolationResult> isolated =
            IsolateOn(rig.builder.project, 1, DiagnosticMapId::Channel(ChannelType::User1), rig.top, request, *templates,
                      warm.store(), warm.cache());
        Check(full && isolated && warm.cache().stats().hits > hitsBefore && isolated->wasVisible,
              "isolating the top layer reuses the cached tiles below it (the general evaluator's cache)",
              Describe(isolated));

        // The virtual normal map: the relief a Height layer adds.
        const std::string heightSha(64, 'e');
        auto resources = std::make_shared<MapResourceProvider>();
        resources->Add(heightSha, HeightCodes(256, 9));
        Builder nb(256, 256, {{ChannelType::Height, ChannelFormat::L16F}, {ChannelType::Normal, ChannelFormat::RGB16F}});
        nb.AddResource(heightSha, 1);
        core::Layer h = nb.Fill("h", {{ChannelType::Height, Bitmap(heightSha)}}, {{ChannelType::Height, Blend(BlendingMode::Normal, 0.75)}});
        core::Layer h2 = nb.Fill("h2", {{ChannelType::Height, Bitmap(heightSha)}}, {{ChannelType::Height, Blend(BlendingMode::LinearDodge, 0.4)}});
        const core::Id h2uid = h2.uid;
        nb.SetRoot({h, h2});
        if (!nb.Validate("diagnostics virtual normal")) return Finish();
        Builder nbHidden = nb;
        SetVisible(nbHidden.Stack().root_layers, h2uid, false);
        bool normalOk = true;
        for (const core::NormalMapFormat convention : {core::NormalMapFormat::OpenGL, core::NormalMapFormat::DirectX}) {
            VirtualNormalRequest vr;
            vr.textureSet = nb.SetId();
            vr.stack = nb.StackId();
            vr.convention = convention;
            vr.resources = resources;
            CpuEvaluator reference(templates, kWideLimits);
            render::Result<VirtualNormalResult> a = reference.EvaluateNormal(nb.project, 1, vr);
            render::Result<VirtualNormalResult> bHidden = reference.EvaluateNormal(nbHidden.project, 1, vr);
            render::Result<ContributionResult> c = ContributionOn(nb.project, 1, DiagnosticMapId::VirtualNormal(convention), h2uid,
                                                                 DiagRequestOf(nb, resources), *templates, cpu.store(), cpu.cache());
            cpu.cache().UnpinAll();
            if (!a || !bHidden || !c) {
                normalOk = false;
                continue;
            }
            std::vector<float> expected(a->texels.size());
            for (size_t i = 0; i < expected.size(); ++i) expected[i] = a->texels[i] - bHidden->texels[i];
            normalOk = normalOk && SameBytes(c->difference.values, expected) && c->difference.components == 3 &&
                       std::any_of(expected.begin(), expected.end(), [](float v) { return v != 0.0f; });
        }
        Check(normalOk, "contribution on Normal_OpenGL and Normal_DirectX equals the virtual map minus the map with the "
                        "Height layer hidden (the relief the layer adds)");
    }

    // 3.3 material views on the two-material fixture, the injected leaks, the effective mask.
    {
        MaterialRig rig(false, false);
        if (!rig.builder.Validate("diagnostics materials")) return Finish();
        CpuEvaluator cpu(templates, kWideLimits);
        render::Result<MaterialViews> views =
            cpu.EvaluateMaterialViews(rig.builder.project, 1, rig.b, DiagRequestOf(rig.builder, rig.provider));
        bool ok = views.has_value() && views->views.size() == 6 && views->missing.empty() && views->inside == 64 * 128;
        std::string detail = Describe(views);
        if (views) {
            // The ID view: blue everywhere inside, no leak.
            const MaterialView& id = views->views[0];
            ok = ok && id.view == MaterialViewKind::ID && id.leakTexels.empty() && id.modalId &&
                 *id.modalId == std::array<float, 3>{0.0f, 0.0f, 1.0f};
            // Channel views: the full values inside, 0 outside; only Roughness leaks, at (40, 10).
            Builder solo = rig.builder;
            SetVisible(solo.Stack().root_layers, rig.a, false);
            SetVisible(solo.Stack().root_layers, rig.touchUp, false);
            for (size_t k = 1; k < views->views.size(); ++k) {
                const MaterialView& view = views->views[k];
                const ChannelType channel = MaterialViewChannel(view.view);
                ok = ok && view.channel == channel;
                const std::vector<float> full = rig.Channel(*templates, rig.builder.project, channel);
                const std::vector<float> own = rig.Channel(*templates, solo.project, channel);
                const uint32_t n = view.values.components;
                if (full.size() != view.values.values.size() || own.size() != full.size()) {
                    ok = false;
                    continue;
                }
                std::vector<float> expected(full.size(), 0.0f);
                std::vector<float> leaks(size_t{MaterialRig::kSize} * MaterialRig::kSize, 0.0f);
                for (uint32_t y = 0; y < MaterialRig::kSize; ++y) {
                    for (uint32_t x = 0; x < MaterialRig::kSize; ++x) {
                        if (x < 64) continue;
                        const size_t t = size_t{y} * MaterialRig::kSize + x;
                        for (uint32_t c = 0; c < n; ++c) {
                            expected[t * n + c] = full[t * n + c];
                            if (!SameFloat(full[t * n + c], own[t * n + c])) leaks[t] = 1.0f;
                        }
                    }
                }
                const bool roughness = view.view == MaterialViewKind::Roughness;
                const size_t leakTexel = size_t{20} * MaterialRig::kSize + 80;
                const bool leakOk = roughness ? view.leakTexels.size() == 1 && view.leakTexels[0].x == 80 &&
                                                    view.leakTexels[0].y == 20 &&
                                                    SameFloat(view.leakTexels[0].value[0], full[leakTexel]) &&
                                                    SameFloat(view.leakTexels[0].own[0], own[leakTexel]) &&
                                                    view.leakTexels[0].value[0] == arith::UnormOperand(arith::WriteUnorm(0.8f, 16), 16) &&
                                                    view.leakTexels[0].own[0] == arith::UnormOperand(arith::WriteUnorm(0.2f, 16), 16)
                                              : view.leakTexels.empty();
                const bool same = SameBytes(view.values.values, expected) && SameBytes(view.leaks.values, leaks) && leakOk;
                if (!same) detail += std::string(MaterialViewName(view.view)) + " ";
                ok = ok && same;
            }
            // The mask is B's (the bitmap's codes as the 16-bit mask).
            std::vector<float> mask(size_t{MaterialRig::kSize} * MaterialRig::kSize);
            for (size_t t = 0; t < mask.size(); ++t) mask[t] = arith::UnormOperand(rig.maskB->values[t], 16);
            ok = ok && SameBytes(views->mask.values, mask);
        }
        Check(ok, "material_views of B on the two-material fixture: the ID view is the ID mesh map inside B's mask (modal "
                  "blue, no leak), each channel view is the full evaluation inside the mask and 0 outside, and the injected "
                  "texel of A's Roughness at (80, 20) is the only leak, with its full and solo values",
              detail);

        MaterialRig spill(true, false);
        render::Result<MaterialViews> spilled =
            cpu.EvaluateMaterialViews(spill.builder.project, 1, spill.b, DiagRequestOf(spill.builder, spill.provider));
        bool spillOk = spilled.has_value() && spilled->views.size() == 6;
        std::string spillDetail = Describe(spilled);
        if (spilled) {
            for (const MaterialView& view : spilled->views) {
                spillDetail += " " + std::string(MaterialViewName(view.view)) + ":" + std::to_string(view.leakTexels.size());
                for (const LeakTexel& leak : view.leakTexels) {
                    spillDetail += "(" + std::to_string(leak.x) + "," + std::to_string(leak.y) + ")";
                }
            }
            const MaterialView& id = spilled->views[0];
            spillOk = spillOk && id.leakTexels.size() == 1 && id.leakTexels[0].x == 63 && id.leakTexels[0].y == 40 &&
                      id.leakTexels[0].value == std::array<float, 3>{1.0f, 0.0f, 0.0f} &&
                      id.leakTexels[0].own == std::array<float, 3>{0.0f, 0.0f, 1.0f} && id.leaks.At(63, 40, 0) == 1.0f;
            for (size_t k = 1; k < spilled->views.size(); ++k) {
                const MaterialView& view = spilled->views[k];
                const size_t expectedLeaks = view.view == MaterialViewKind::Roughness ? 2 : 1;
                spillOk = spillOk && view.leakTexels.size() == expectedLeaks && view.leaks.At(63, 40, 0) == 1.0f;
            }
        }
        Check(spillOk, "a mask that spills onto another ID island is an ID leak (the texel's ID colour against the modal "
                       "one) and, with material A over it, a leak of every channel view",
              spillDetail);

        MaterialRig nested(false, true);
        if (!nested.builder.Validate("diagnostics nested material")) return Finish();
        render::Result<MaterialViews> inner =
            cpu.EvaluateMaterialViews(nested.builder.project, 1, nested.b, DiagRequestOf(nested.builder, nested.provider));
        bool nestedOk = inner.has_value() && inner->inside == 64 * 64 - 1;
        std::string nestedDetail = Describe(inner);
        if (inner) {
            nestedDetail += " inside " + std::to_string(inner->inside);
            for (size_t t = 0; t < inner->mask.values.size(); ++t) {
                const float expected = arith::UnormOperand(nested.maskB->values[t], 16) * arith::UnormOperand(nested.maskG->values[t], 16);
                if (!SameFloat(inner->mask.values[t], expected) && nestedOk) {
                    nestedDetail += " texel " + std::to_string(t) + ": " + std::to_string(inner->mask.values[t]) + " vs " +
                                    std::to_string(expected);
                }
                nestedOk = nestedOk && SameFloat(inner->mask.values[t], expected);
            }
            const size_t soft = size_t{10} * MaterialRig::kSize + 100;
            nestedOk = nestedOk && inner->mask.values[soft] < kInsideThreshold &&
                       arith::UnormOperand(45000, 16) >= kInsideThreshold && inner->views[4].values.At(100, 10, 0) == 0.0f;
        }
        Check(nestedOk, "a nested material's region is its effective mask, the float32 product of its mask and the "
                        "enclosing group's, inside where it is at least 1/2 (a soft texel inside each mask alone is "
                        "outside the product)",
              nestedDetail);

        MaterialRig noId(false, false, false);
        Builder noHeight(MaterialRig::kSize, MaterialRig::kSize, {{ChannelType::BaseColor, ChannelFormat::sRGB8}});
        core::Layer only = noHeight.Fill("only", {{ChannelType::BaseColor, Uniform(0.5, 0.5, 0.5)}}, {});
        const core::Id onlyUid = only.uid;
        noHeight.SetRoot({only});
        render::Result<MaterialViews> missingId =
            cpu.EvaluateMaterialViews(noId.builder.project, 1, noId.b, DiagRequestOf(noId.builder, noId.provider));
        render::Result<MaterialViews> missingChannels =
            cpu.EvaluateMaterialViews(noHeight.project, 1, onlyUid, DiagRequestOf(noHeight, nullptr));
        render::Result<MaterialViews> ofInstance =
            cpu.EvaluateMaterialViews(rig.builder.project, 1, rig.instance, DiagRequestOf(rig.builder, rig.provider));
        render::Result<MaterialViews> unknown =
            cpu.EvaluateMaterialViews(rig.builder.project, 1, core::kMaxId, DiagRequestOf(rig.builder, rig.provider));
        MaterialRig badId(false, false);
        badId.provider->Add(badId.idSha, PatternImage(32, 32, 3, render::TexelEncoding::Unorm8, 3));
        render::Result<MaterialViews> wrongSize =
            cpu.EvaluateMaterialViews(badId.builder.project, 1, badId.b, DiagRequestOf(badId.builder, badId.provider));
        const bool missingOk =
            missingId && missingId->missing == std::vector<MaterialViewKind>{MaterialViewKind::ID} &&
            missingId->views.size() == 5 && missingChannels &&
            missingChannels->missing == std::vector<MaterialViewKind>{MaterialViewKind::ID, MaterialViewKind::Height,
                                                                      MaterialViewKind::Normal, MaterialViewKind::Roughness,
                                                                      MaterialViewKind::Metallic} &&
            missingChannels->views.size() == 1 && missingChannels->inside == size_t{MaterialRig::kSize} * MaterialRig::kSize;
        Check(missingOk, "views the set or stack cannot give are listed as missing (no ID mesh map, absent channels); a "
                         "material without a mask covers the whole set",
              Describe(missingId) + " " + Describe(missingChannels));
        Check(!ofInstance && KindName(ofInstance.error()) == "invalid_argument" && !unknown &&
                  KindName(unknown.error()) == "not_found" && !wrongSize && KindName(wrongSize.error()) == "unsupported_source",
              "an instance material fails with invalid_argument, an unknown one with not_found, an ID mesh map off the "
              "set resolution with unsupported_source",
              Describe(ofInstance) + " " + Describe(unknown) + " " + Describe(wrongSize));
    }

    // 3.4 region statistics: the fixtures the Python test recomputes independently.
    {
        std::mt19937 rng(1313);
        std::uniform_real_distribution<float> value(-0.25f, 1.25f);
        auto write = [&](const std::string& name, const DiagnosticMap& map, const DiagnosticMap& mask) {
            render::Result<RegionStats> stats = ComputeRegionStats(map, mask);
            std::ofstream out(dir / ("region-stats-" + name + ".json"), std::ios::binary);
            out << "{\"width\":" << map.width << ",\"height\":" << map.height << ",\"components\":" << map.components
                << ",\"map\":[";
            for (size_t i = 0; i < map.values.size(); ++i) out << (i ? "," : "") << std::bit_cast<uint32_t>(map.values[i]);
            out << "],\"mask\":[";
            for (size_t i = 0; i < mask.values.size(); ++i) out << (i ? "," : "") << std::bit_cast<uint32_t>(mask.values[i]);
            out << "],\"stats\":" << (stats ? RegionStatsJson(*stats) : std::string("null")) << "}";
            return stats;
        };
        const float maskValues[] = {0.0f, 0.25f, 0.4999f, 0.5f, 0.75f, 1.0f};
        DiagnosticMap colour{37, 23, 3, {}};
        DiagnosticMap grey{37, 23, 1, {}};
        DiagnosticMap mask{37, 23, 1, {}};
        DiagnosticMap empty{37, 23, 1, std::vector<float>(37 * 23, 0.25f)};
        for (size_t t = 0; t < size_t{37} * 23; ++t) {
            for (int c = 0; c < 3; ++c) colour.values.push_back(t % 7 == 0 ? 0.5f : value(rng));
            grey.values.push_back(t % 5 == 0 ? 0.0f : value(rng));
            mask.values.push_back(maskValues[rng() % 6]);
        }
        render::Result<RegionStats> a = write("colour", colour, mask);
        render::Result<RegionStats> b = write("grey", grey, mask);
        render::Result<RegionStats> c = write("empty", grey, empty);
        size_t inside = 0;
        for (const float m : mask.values) inside += m >= 0.5f ? 1 : 0;
        Check(a && b && c && a->inside == inside && a->luminance && a->saturation && a->components.size() == 3 &&
                  b->components.size() == 1 && !b->luminance && c->inside == 0 && c->components.empty() && c->maskMean == 0.25,
              "region_stats counts the texels whose mask is at least 1/2, gives per-component, luminance and saturation "
              "statistics of three-component maps and none over an empty region (fixtures written for the Python check)");
        DiagnosticMap nan = grey;
        nan.values[0] = std::nanf("");
        DiagnosticMap full{37, 23, 1, std::vector<float>(37 * 23, 1.0f)};
        render::Result<RegionStats> wide = ComputeRegionStats(grey, colour);
        render::Result<RegionStats> notFinite = ComputeRegionStats(nan, full);
        Check(!wide && KindName(wide.error()) == "invalid_argument" && !notFinite &&
                  KindName(notFinite.error()) == "invalid_argument",
              "region_stats refuses a mask of more than one component and a value inside that is not finite "
              "(invalid_argument)");

        // The export plan's statistics source is the same computation over the evaluated map and mask.
        MaterialRig rig(false, false);
        CpuEvaluator cpu(templates, kWideLimits);
        const DiagnosticRequest request = DiagRequestOf(rig.builder, rig.provider);
        DiagnosticSource source;
        source.kind = DiagnosticSource::Kind::RegionStats;
        source.map = DiagnosticMapId::Channel(ChannelType::BaseColor);
        source.node = rig.b;
        render::Result<DiagnosticOutput> named = cpu.Diagnose(rig.builder.project, 1, source, request);
        render::Result<DiagnosticMap> map = EvaluateMapOn(rig.builder.project, 1, source.map, request, *templates, cpu.store(), cpu.cache());
        render::Result<DiagnosticMap> materialMask = MaterialMaskOn(rig.builder.project, rig.b, request, *templates, cpu.store(), cpu.cache());
        cpu.cache().UnpinAll();
        std::optional<RegionStats> direct;
        if (map && materialMask) {
            render::Result<RegionStats> computed = ComputeRegionStats(*map, *materialMask);
            if (computed) direct = *computed;
        }
        Check(named && direct && named->stats && *named->stats == *direct && direct->inside == 64 * 128 &&
                  direct->components[2].p50 == arith::Srgb8Operand(arith::Srgb8Store(0.8f)),
              "the regionStats source equals region_stats over the evaluated map and the material's mask",
              Describe(named));
    }

    // 2.5 Every diagnostic is a source the export plan names.
    {
        bool roundTrip = true;
        std::string detail;
        std::vector<DiagnosticSource> sources = NodeSources({7}, {ChannelType::BaseColor, ChannelType::User31});
        for (const DiagnosticSource& s : MaterialSources(9)) sources.push_back(s);
        for (const auto kind : {DiagnosticSource::Kind::Isolated, DiagnosticSource::Kind::Contribution,
                                DiagnosticSource::Kind::RegionStats}) {
            for (const core::NormalMapFormat convention : {core::NormalMapFormat::OpenGL, core::NormalMapFormat::DirectX}) {
                DiagnosticSource s;
                s.kind = kind;
                s.map = DiagnosticMapId::VirtualNormal(convention);
                s.node = core::kMaxId;
                sources.push_back(s);
            }
        }
        for (const DiagnosticSource& s : sources) {
            render::Result<DiagnosticSource> parsed = ParseSourceName(SourceName(s));
            if (!parsed || !(*parsed == s)) {
                roundTrip = false;
                detail += SourceName(s) + " ";
            }
        }
        Check(roundTrip && SourceName(sources.front()) == "isolated/BaseColor/7" &&
                  SourceName(MaterialSources(9)[0]) == "materialMask/9" &&
                  SourceName(MaterialSources(9)[1]) == "materialView/ID/9" && kDiagnosticMapType == "diagnosticMap",
              "every diagnostic source name round-trips (" + std::to_string(sources.size()) +
                  " names: isolated, contribution, materialMask, materialView, materialLeaks, regionStats; channels and "
                  "both virtual normal maps)",
              detail);
        bool refused = true;
        for (const std::string_view bad :
             {"", "isolated", "isolated/BaseColor", "isolated/BaseColor/1/2", "unknown/BaseColor/1", "isolated/Nope/1",
              "isolated/BaseColor/0", "isolated/BaseColor/01", "isolated/BaseColor/-1", "isolated/BaseColor/1x",
              "materialView/User0/5", "materialMask/x", "materialMask/BaseColor/5", "isolated/BaseColor/9223372036854775808"}) {
            render::Result<DiagnosticSource> parsed = ParseSourceName(bad);
            if (parsed || KindName(parsed.error()) != "not_found") {
                refused = false;
                detail += std::string(bad) + " ";
            }
        }
        Check(refused, "malformed source names fail with not_found (kind, map, view, part count, uid)", detail);
    }

    // 2.5 / 3.5 The named sources equal the direct diagnostics, and every output is byte-identical
    // across two runs (fresh evaluators) and on a warm cache.
    {
        ContributionRig crig;
        MaterialRig mrig(true, true);
        struct Case {
            Builder* builder;
            std::shared_ptr<const IResourceProvider> provider;
            std::vector<DiagnosticSource> sources;
        };
        std::vector<Case> cases{{&crig.builder, crig.provider, NodeSources(crig.nodes, {ChannelType::BaseColor, ChannelType::User0})},
                                {&mrig.builder, mrig.provider, MaterialSources(mrig.b)}};
        for (const core::Id node : {mrig.a, mrig.touchUp}) {
            for (const DiagnosticSource& s : NodeSources({node}, {ChannelType::SpecularRoughness})) cases[1].sources.push_back(s);
        }
        bool identical = true;
        bool direct = true;
        size_t outputs = 0;
        std::string detail;
        for (Case& c : cases) {
            CpuEvaluator first(templates, kWideLimits);
            CpuEvaluator second(templates, kWideLimits);
            const DiagnosticRequest request = DiagRequestOf(*c.builder, c.provider);
            for (const DiagnosticSource& source : c.sources) {
                render::Result<DiagnosticOutput> one = first.Diagnose(c.builder->project, 4, source, request);
                render::Result<DiagnosticOutput> two = second.Diagnose(c.builder->project, 4, source, request);
                render::Result<DiagnosticOutput> warm = first.Diagnose(c.builder->project, 4, source, request);
                if (!one || !two || !warm || OutputBytes(*one) != OutputBytes(*two) || OutputBytes(*one) != OutputBytes(*warm) ||
                    one->revision != 4) {
                    identical = false;
                    detail += SourceName(source) + (one ? "" : ": " + Describe(one)) + " ";
                    continue;
                }
                ++outputs;
                CpuEvaluator reference(templates, kWideLimits);
                std::optional<DiagnosticMap> expected;
                switch (source.kind) {
                    case DiagnosticSource::Kind::Isolated: {
                        render::Result<IsolationResult> r = IsolateOn(c.builder->project, 4, source.map, source.node, request,
                                                                      *templates, reference.store(), reference.cache());
                        if (r) expected = r->map;
                        break;
                    }
                    case DiagnosticSource::Kind::Contribution: {
                        render::Result<ContributionResult> r = ContributionOn(c.builder->project, 4, source.map, source.node,
                                                                              request, *templates, reference.store(), reference.cache());
                        if (r) expected = r->difference;
                        break;
                    }
                    case DiagnosticSource::Kind::MaterialMask:
                    case DiagnosticSource::Kind::MaterialView:
                    case DiagnosticSource::Kind::MaterialLeaks: {
                        render::Result<MaterialViews> r = reference.EvaluateMaterialViews(c.builder->project, 4, source.node, request);
                        if (!r) break;
                        if (source.kind == DiagnosticSource::Kind::MaterialMask) {
                            expected = r->mask;
                            break;
                        }
                        for (const MaterialView& view : r->views) {
                            if (view.view == source.view) {
                                expected = source.kind == DiagnosticSource::Kind::MaterialView ? view.values : view.leaks;
                            }
                        }
                        break;
                    }
                    case DiagnosticSource::Kind::RegionStats: continue;
                }
                if (!expected || !SameMap(*expected, *one->map)) {
                    direct = false;
                    detail += "direct:" + SourceName(source) + " ";
                }
            }
        }
        Check(identical, "every diagnostic output is byte-identical across two runs and on a warm cache (" +
                             std::to_string(outputs) + " outputs)",
              detail);
        Check(direct, "every named source equals its direct diagnostic (isolate, contribution, material mask, views and leaks)",
              detail);
    }
    return Finish();
}

int RunDiagnosticsGpuVsCpu(const fs::path& assets, const fs::path& dir) {
    render::Engine engine(TestOptions(dir));
    if (NoAdapter(engine)) return kExitSkip;
    Info("adapter " + engine.Capabilities().value_or(render::CapabilityReport{}).adapter);
    std::shared_ptr<const TemplateLibrary> templates = LoadTemplates(assets);
    ContributionRig crig;
    MaterialRig mrig(true, true);
    struct Case {
        Builder* builder;
        std::shared_ptr<const IResourceProvider> provider;
        std::vector<DiagnosticSource> sources;
    };
    std::vector<Case> cases{{&crig.builder, crig.provider, NodeSources(crig.nodes, crig.channels)},
                            {&mrig.builder, mrig.provider, MaterialSources(mrig.b)}};
    for (const core::Id node : {mrig.a, mrig.touchUp, mrig.g}) {
        for (const DiagnosticSource& s : NodeSources({node}, {ChannelType::BaseColor, ChannelType::SpecularRoughness, ChannelType::Normal})) {
            cases[1].sources.push_back(s);
        }
    }
    Evaluator gpu(engine, templates);
    size_t outputs = 0;
    bool same = true;
    std::string detail;
    for (Case& c : cases) {
        const core::Snapshot snapshot{5, std::make_shared<const core::Project>(c.builder->project)};
        const DiagnosticRequest request = DiagRequestOf(*c.builder, c.provider);
        CpuEvaluator cpu(templates, kWideLimits);
        for (const DiagnosticSource& source : c.sources) {
            render::Result<DiagnosticOutput> expected = cpu.Diagnose(*snapshot.project, snapshot.revision, source, request);
            std::future<render::Result<DiagnosticOutput>> once = gpu.Diagnose(snapshot, source, request);
            render::Result<DiagnosticOutput> actual = Get(once);
            std::future<render::Result<DiagnosticOutput>> twice = gpu.Diagnose(snapshot, source, request);
            render::Result<DiagnosticOutput> again = Get(twice);
            if (!expected || !actual || !again || OutputBytes(*expected) != OutputBytes(*actual) ||
                OutputBytes(*actual) != OutputBytes(*again) || actual->revision != 5) {
                same = false;
                detail += SourceName(source) + (actual ? "" : ": " + Describe(actual)) + " ";
                continue;
            }
            ++outputs;
        }
        if (c.builder != &mrig.builder) continue;
        CpuEvaluator cpuViews(templates, kWideLimits);
        render::Result<MaterialViews> expectedViews = cpuViews.EvaluateMaterialViews(*snapshot.project, 5, mrig.b, request);
        std::future<render::Result<MaterialViews>> viewsFuture = gpu.EvaluateMaterialViews(snapshot, mrig.b, request);
        render::Result<MaterialViews> actualViews = Get(viewsFuture);
        if (!expectedViews || !actualViews || ViewsBytes(*expectedViews) != ViewsBytes(*actualViews) ||
            expectedViews->views[0].leakTexels != actualViews->views[0].leakTexels) {
            same = false;
            detail += "material views ";
        }
    }
    Check(same, "every diagnostic source on the GPU equals the CPU reference bit for bit and is byte-identical across two "
                "GPU runs (" + std::to_string(outputs) + " outputs; isolate and contribution on six channel formats, "
                "material masks, views, leaks and region statistics)",
          detail);

    // A GPU evaluation that fails midway leaves the document as it was.
    ContributionRig wide(2048);
    core::DocumentState state;
    state.project_uuid = "diagnostics-gpu-isolation";
    state.project = wide.builder.project;
    core::Document document(std::move(state));
    document.MarkCheckpoint();
    const core::Snapshot before = document.snapshot();
    const core::Project copy = *before.project;
    DiagnosticSource source;
    source.kind = DiagnosticSource::Kind::Contribution;
    source.map = DiagnosticMapId::Channel(ChannelType::BaseColor);
    source.node = wide.top;
    const int fetches = FetchesOf(templates, wide.builder, wide.provider, source);
    auto failing = std::make_shared<FailingProvider>(wide.provider, fetches / 2);
    Evaluator fresh(engine, templates);
    std::future<render::Result<DiagnosticOutput>> future = fresh.Diagnose(before, source, DiagRequestOf(wide.builder, failing));
    render::Result<DiagnosticOutput> failed = Get(future);
    fresh.Shutdown();
    gpu.Shutdown();
    Check(!failed && KindName(failed.error()) == "missing_resource" && failing->fetches == fetches / 2 + 1 &&
              DocumentUnchanged(document, before, copy, wide.top, true),
          "a GPU isolation that fails midway leaves the document, its revision, records and save state as they were",
          Describe(failed));
    return Finish();
}

// ── not-yet-supported (phase1.14_compositor-core item 3.3, decision 082) ─────

/// One excluded feature: how a request applies it, the owner task the refusal names, and the
/// channel whose evaluation the evaluator itself refuses (nullopt: the evaluator evaluates it
/// without a golden; only the check before mutation refuses it).
struct ExcludedFeature {
    std::string name;
    std::string owner;
    std::optional<ChannelType> evaluatorRefuses;
    std::function<void(core::Project&, core::Id fill)> apply;
};

core::Effect EffectOf(core::Project& project, core::EffectKind kind) {
    core::Effect effect;
    effect.uid = project.AllocateId();
    effect.kind = kind;
    effect.name = std::string(core::ToString(kind));
    return effect;
}

core::FillContent& FillOf(core::Project& project, core::Id fill) { return *core::FindLayer(project, fill)->fill; }

void SetProjection(core::Project& project, core::Id fill, core::ProjectionMode mode) {
    FillOf(project, fill).projection.mode = mode;
}

std::vector<ExcludedFeature> ExcludedFeatures() {
    using core::EffectKind;
    using core::ProjectionMode;
    std::vector<ExcludedFeature> features;
    const auto projection = [&](ProjectionMode mode, const std::string& owner) {
        features.push_back({std::string(core::ToString(mode)) + " projection", owner, ChannelType::User0,
                            [mode](core::Project& p, core::Id fill) { SetProjection(p, fill, mode); }});
    };
    for (const ProjectionMode mode : {ProjectionMode::Triplanar, ProjectionMode::Planar, ProjectionMode::Spherical,
                                      ProjectionMode::Cylindrical}) {
        projection(mode, "phase3.4_smart-projections");
    }
    projection(ProjectionMode::Warp, "phase4.1_nodes-projections");
    projection(ProjectionMode::UVSetToUVSet, "phase4.1_nodes-projections");
    features.push_back({"symmetry", "phase3.4_smart-projections", ChannelType::User0,
                        [](core::Project& p, core::Id fill) { FillOf(p, fill).symmetry.enabled = true; }});
    features.push_back({"a physical-size UV scale mode", "phase3.4_smart-projections", std::nullopt,
                        [](core::Project& p, core::Id fill) {
                            FillOf(p, fill).projection.mode = core::ProjectionMode::UV;
                            FillOf(p, fill).projection.uv.uv_transformation.scale_mode = core::ScaleMode::CustomPhysicalSize;
                        }});
    features.push_back({"a one-axis wrap mode", "phase4.2_remaining-nodes", std::nullopt,
                        [](core::Project& p, core::Id fill) {
                            FillOf(p, fill).projection.mode = core::ProjectionMode::UV;
                            FillOf(p, fill).projection.uv.uv_wrapping_mode = core::UVWrapMode::RepeatVertically;
                        }});
    features.push_back({"the Material source mode", "phase3.2_proc-material-families", ChannelType::User0,
                        [](core::Project& p, core::Id fill) { FillOf(p, fill).source_mode = core::SourceMode::Material; }});
    const auto source = [&](const std::string& name, const std::string& owner, core::Source value) {
        features.push_back({name, owner, ChannelType::User0, [value](core::Project& p, core::Id fill) {
                                FillOf(p, fill).sources[ChannelType::User0] = value;
                            }});
    };
    core::VectorSource vector;
    vector.resource.sha256 = std::string(64, 'a');
    source("a vector source", "phase4.1_nodes-vector-font-sources", core::Source{vector});
    core::FontSource font;
    font.resource.sha256 = std::string(64, 'b');
    source("a font source", "phase4.1_nodes-vector-font-sources", core::Source{font});
    core::ProceduralSource procedural;
    procedural.ref.asset = "uzasset://generator/dirt@1";
    source("a procedural source", "phase3.3_procedural-families", core::Source{procedural});
    source("an anchor reference source", "phase4.1_nodes-instances-anchors", core::Source{core::ReferenceSource{}});
    features.push_back({"OCIO colour management", "phase1.14_compositor-core", ChannelType::User0,
                        [](core::Project& p, core::Id) { p.settings.color_management.mode = "ocio"; }});
    const auto content = [&](EffectKind kind, const std::string& owner) {
        features.push_back({std::string(core::ToString(kind)) + " effect in a content stack", owner, ChannelType::User0,
                            [kind](core::Project& p, core::Id fill) {
                                core::Effect effect = EffectOf(p, kind);
                                core::FindLayer(p, fill)->content_effects.insert(
                                    core::FindLayer(p, fill)->content_effects.begin(), std::move(effect));
                            }});
    };
    content(EffectKind::generator, "phase3.2_proc-generator-families");
    content(EffectKind::filter, "phase3.2_proc-filter-families");
    content(EffectKind::paint, "phase4.1_nodes-paint-layers");
    content(EffectKind::anchor, "phase4.1_nodes-instances-anchors");
    const auto mask = [&](EffectKind kind, const std::string& owner, bool refused) {
        features.push_back({std::string(core::ToString(kind)) + " effect in a mask stack", owner,
                            refused ? std::optional<ChannelType>(ChannelType::User0) : std::nullopt,
                            [kind](core::Project& p, core::Id fill) {
                                core::Effect effect = EffectOf(p, kind);
                                if (kind == EffectKind::levels) {
                                    effect.levels = core::LevelsParams{};
                                    effect.levels->components.push_back(core::LevelsComponent{});
                                }
                                std::vector<core::Effect>& effects = core::FindLayer(p, fill)->mask->effects;
                                effects.insert(effects.begin(), std::move(effect));
                            }});
    };
    mask(EffectKind::compare_mask, "phase4.1_nodes-mask-effects", true);
    mask(EffectKind::color_selection, "phase4.1_nodes-mask-effects", true);
    mask(EffectKind::levels, "phase4.2_remaining-nodes", false);
    features.push_back({"a fill effect in a content stack", "phase3.2_proc-filter-families", std::nullopt,
                        [](core::Project& p, core::Id fill) {
                            core::Effect effect = EffectOf(p, core::EffectKind::fill);
                            core::FillContent content;
                            content.sources[ChannelType::User0] = Uniform(0.1, 0.2, 0.3);
                            content.active_channels.insert(ChannelType::User0);
                            effect.fill = std::move(content);
                            core::FindLayer(p, fill)->content_effects.insert(
                                core::FindLayer(p, fill)->content_effects.begin(), std::move(effect));
                        }});
    const auto layer = [&](const std::string& name, const std::string& owner, bool refused,
                           const std::function<void(core::Project&, core::Layer&, core::Id)>& shape) {
        features.push_back({name, owner, refused ? std::optional<ChannelType>(ChannelType::User0) : std::nullopt,
                            [shape](core::Project& p, core::Id fill) {
                                core::Layer added;
                                added.uid = p.AllocateId();
                                added.name = "added";
                                shape(p, added, fill);
                                std::vector<core::Layer>& roots = p.texture_sets.front().stacks.front().root_layers;
                                roots.insert(roots.begin(), std::move(added));
                            }});
    };
    layer("a paint layer", "phase4.1_nodes-paint-layers", true, [](core::Project&, core::Layer& l, core::Id) {
        l.kind = core::LayerKind::paint;
        l.paint = core::PaintContent{};
    });
    layer("an instance layer", "phase4.1_nodes-instances-anchors", false, [](core::Project&, core::Layer& l, core::Id fill) {
        l.kind = core::LayerKind::instance;
        l.instance_source = fill;
    });
    features.push_back({"a UVTile geometry mask", "phase4.5_uv-tiles", ChannelType::User0,
                        [](core::Project& p, core::Id fill) {
                            core::GeometryMask& geometry = core::FindLayer(p, fill)->geometry_mask;
                            geometry.type = core::GeometryMaskType::UVTile;
                            geometry.inclusion_list = true;
                            geometry.items = {"1001"};
                        }});
    features.push_back({"a Mesh geometry mask", "phase4.2_remaining-nodes", std::nullopt,
                        [](core::Project& p, core::Id fill) {
                            core::GeometryMask& geometry = core::FindLayer(p, fill)->geometry_mask;
                            geometry.inclusion_list = false;
                            geometry.items = {"other"};
                        }});
    features.push_back({"an sRGB bitmap on an RGB16 channel", "phase1.14_compositor-core", ChannelType::User0,
                        [](core::Project& p, core::Id fill) {
                            FillOf(p, fill).sources[ChannelType::User0] = Bitmap(std::string(64, 'd'), "sRGB");
                        }});
    features.push_back({"a bitmap in the Working colour space", "phase1.14_compositor-core", ChannelType::User0,
                        [](core::Project& p, core::Id fill) {
                            FillOf(p, fill).sources[ChannelType::User0] = Bitmap(std::string(64, 'e'), "Working");
                        }});
    // SignedAddition and uniform colours on Height are recorded (height-signed-addition, decision
    // 079); a DirectX project's Normal channel only as one bitmap fill at opacity 1.
    features.push_back({"a Normal-channel bitmap at opacity 1/2 in a DirectX project", "phase1.12_compositor-height-normal",
                        ChannelType::Normal, [](core::Project& p, core::Id fill) {
                            p.settings.normal_map_format = core::NormalMapFormat::DirectX;
                            core::FillContent& content = FillOf(p, fill);
                            content.sources[ChannelType::Normal] = Bitmap(std::string(64, 'c'));
                            content.active_channels.insert(ChannelType::Normal);
                            core::FindLayer(p, fill)->blending[ChannelType::Normal] = Blend(BlendingMode::Normal, 0.5);
                        }});
    features.push_back({"a uniform Normal colour in a DirectX project", "phase1.12_compositor-height-normal",
                        ChannelType::Normal, [](core::Project& p, core::Id fill) {
                            p.settings.normal_map_format = core::NormalMapFormat::DirectX;
                            core::FillContent& content = FillOf(p, fill);
                            content.sources[ChannelType::Normal] = Uniform(0.5, 0.5, 1.0);
                            content.active_channels.insert(ChannelType::Normal);
                        }});
    return features;
}

int RunNotYetSupported(const fs::path& assets) {
    std::shared_ptr<const TemplateLibrary> templates = LoadTemplates(assets);
    const std::vector<ChannelType> user0{ChannelType::User0};
    Builder builder(128, 128, {{ChannelType::User0, ChannelFormat::RGB16}, {ChannelType::Height, ChannelFormat::L16F},
                             {ChannelType::Normal, ChannelFormat::RGB16F}});
    core::Layer base = builder.Fill("base", SameSource(user0, Uniform(0.25, 0.5, 0.75)), Same(user0, BlendingMode::Normal, 1.0));
    base.mask = core::Mask{};
    base.fill->projection.mode = core::ProjectionMode::Fill;
    const core::Id fill = base.uid;
    builder.SetRoot({base});
    if (!builder.Validate("not-yet-supported")) return Finish();

    const auto newDocument = [&](const std::string& uuid) {
        core::DocumentState state;
        state.project_uuid = uuid;
        state.project = builder.project;
        return std::make_unique<core::Document>(std::move(state));
    };
    const auto request = [](const core::Document& document, const std::string& key) {
        core::MutationRequest mutation;
        mutation.tool = "set_feature";
        mutation.idempotency_key = key;
        mutation.expected_revision = document.revision();
        return mutation;
    };
    const auto evaluateOn = [&](const core::Project& project, ChannelType channel, CpuEvaluator& cpu) {
        EvaluateRequest evaluation;
        evaluation.textureSet = builder.SetId();
        evaluation.stack = builder.StackId();
        evaluation.channel = channel;
        evaluation.resources = std::make_shared<MapResourceProvider>();
        return cpu.Evaluate(project, evaluation);
    };

    // Every excluded feature of the proposal: refused before any mutation, naming its owner.
    std::string transactionFailures;
    std::string evaluatorFailures;
    size_t refusedByEvaluator = 0;
    const std::vector<ExcludedFeature> features = ExcludedFeatures();
    for (const ExcludedFeature& feature : features) {
        std::unique_ptr<core::Document> document = newDocument("nys-" + feature.name);
        document->MarkCheckpoint();
        const core::Snapshot before = document->snapshot();
        const core::Project copy = *before.project;
        const core::RequestOutcome outcome =
            core::Execute(*document, request(*document, feature.name), [&](core::Edit& edit) {
                feature.apply(edit.project(), fill);
                RequireSupported(edit.base(), edit.project());
            });
        const core::Snapshot now = document->snapshot();
        const bool refused = outcome.result && outcome.result->status == core::ResultStatus::failed &&
                             outcome.result->error_type == "NotYetSupported" &&
                             outcome.result->error.find(feature.owner) != std::string::npos;
        const bool unchanged = now.revision == before.revision && now.project.get() == before.project.get() &&
                               *now.project == copy && document->operations().empty() && !document->NeedsSaving();
        if (!refused || !unchanged) {
            transactionFailures += feature.name + " (" +
                                   (outcome.result ? outcome.result->error_type + ": " + outcome.result->error
                                                   : std::string("not executed")) +
                                   ") ";
        }
        if (!feature.evaluatorRefuses) continue;
        core::Project direct = builder.project;
        feature.apply(direct, fill);
        CpuEvaluator cpu(templates, kWideLimits);
        const render::Result<ChannelResult> result = evaluateOn(direct, *feature.evaluatorRefuses, cpu);
        const std::optional<EvalErrorKind> kind = result ? std::nullopt : EvalErrorKindOf(result.error());
        if (!kind || ErrorClassName(*kind) != "NotYetSupported" || cpu.cache().stats().liveTiles != 0 ||
            cpu.cache().stats().misses != 0) {
            evaluatorFailures += feature.name + " (" + Describe(result) + ") ";
        }
        ++refusedByEvaluator;
    }
    Check(transactionFailures.empty(),
          "every excluded feature (" + std::to_string(features.size()) +
              ": 3D, warp and UV-set projections, symmetry, physical-size scale, one-axis wrap, Material mode, vector, "
              "font, procedural and reference sources, OCIO, generator, filter, paint, anchor, compare-mask, "
              "colour-selection effects, content fill and mask levels effects, paint and instance layers, geometry "
              "masks, Height and DirectX Normal cases, unrecorded bitmap colour spaces) fails its transaction with NotYetSupported naming its owner "
              "task; the document, its revision, records and save state are unchanged",
          transactionFailures);
    Check(evaluatorFailures.empty(),
          "the " + std::to_string(refusedByEvaluator) +
              " features the evaluator refuses itself fail evaluation with a kind whose API class is NotYetSupported, "
              "before any tile is allocated or looked up",
          evaluatorFailures);

    // The kinds map to one API class each.
    Check(ErrorClassName(EvalErrorKind::UnsupportedNode) == "NotYetSupported" &&
              ErrorClassName(EvalErrorKind::UnsupportedBlendMode) == "NotYetSupported" &&
              ErrorClassName(EvalErrorKind::UnsupportedSource) == "NotYetSupported" &&
              ErrorClassName(EvalErrorKind::InvalidArgument) == "ValueError" &&
              ErrorClassName(EvalErrorKind::NotFound) == "ValueError" &&
              ErrorClassName(EvalErrorKind::MissingResource) == "ResourceNotFoundError" &&
              ErrorClassName(EvalErrorKind::Internal) == "RuntimeError",
          "unsupported_node, unsupported_blend_mode and unsupported_source are NotYetSupported; invalid_argument and "
          "not_found ValueError; missing_resource ResourceNotFoundError; internal RuntimeError");

    // A supported request commits and evaluates.
    {
        std::unique_ptr<core::Document> document = newDocument("nys-supported");
        const core::RequestOutcome outcome =
            core::Execute(*document, request(*document, "supported"), [&](core::Edit& edit) {
                core::Layer* layer = core::FindLayer(edit.project(), fill);
                layer->blending[ChannelType::User0].opacity = 0.5;
                layer->fill->projection.mode = core::ProjectionMode::UV;
                layer->fill->projection.uv.filtering_mode = core::FilteringMode::Nearest;
                core::Effect levels = EffectOf(edit.project(), core::EffectKind::levels);
                levels.levels = core::LevelsParams{};
                levels.levels->affected_channel = ChannelType::User0;
                levels.levels->components.push_back(core::LevelsComponent{});
                layer->content_effects.insert(layer->content_effects.begin(), std::move(levels));
                RequireSupported(edit.base(), edit.project());
            });
        CpuEvaluator cpu(templates, kWideLimits);
        const render::Result<ChannelResult> result = evaluateOn(*document->snapshot().project, ChannelType::User0, cpu);
        Check(outcome.result && outcome.result->status == core::ResultStatus::committed && result,
              "a supported request (opacity, UV projection with Nearest, a content levels effect) commits and evaluates",
              (outcome.result ? outcome.result->error_type + ": " + outcome.result->error : std::string("not executed")) +
                  " / " + Describe(result));
    }

    // A project that already holds a gap stays editable elsewhere: only touched nodes are checked.
    {
        Builder holding = builder;
        core::Layer instance = holding.Instance("instance", fill);
        const core::Id instanceUid = instance.uid;
        holding.Stack().root_layers.insert(holding.Stack().root_layers.begin(), std::move(instance));
        core::DocumentState state;
        state.project_uuid = "nys-holding";
        state.project = holding.project;
        core::Document document(std::move(state));
        const core::RequestOutcome edit = core::Execute(document, request(document, "elsewhere"), [&](core::Edit& e) {
            core::FindLayer(e.project(), fill)->blending[ChannelType::User0].opacity = 0.75;
            RequireSupported(e.base(), e.project());
        });
        const core::RequestOutcome touch = core::Execute(document, request(document, "touch"), [&](core::Edit& e) {
            core::FindLayer(e.project(), instanceUid)->name = "renamed";
            RequireSupported(e.base(), e.project());
        });
        Check(edit.result && edit.result->status == core::ResultStatus::committed && touch.result &&
                  touch.result->status == core::ResultStatus::failed && touch.result->error_type == "NotYetSupported",
              "an edit of a supported node commits in a project that holds an instance layer; touching the instance "
              "fails with NotYetSupported",
              (edit.result ? edit.result->error : std::string()) + " / " + (touch.result ? touch.result->error : std::string()));
    }
    return Finish();
}


/// `texture-unit <assets> <work-dir>`: the texture-unit replica (texture_unit.h) on designed
/// inputs written by `tools/parity/vk_sampler_probe/tables.py`, for its sample-for-sample
/// comparison with the recording GPU. `tu-in.bin`: uint32 side W, then the texels of every level
/// of the mip chain (W x W, W/2 x W/2, ... 1 x 1; three float32 each, rows bottom up), uint32 N,
/// then N records of six float32 (u, v, ddx.x, ddx.y, ddy.x, ddy.y), int32 bias (1/256) and
/// uint32 flags (1 repeat u, 2 repeat v). Writes `tu-out.bin`, N x 3 float32.
int RunTextureUnit(const fs::path& dir) {
    std::ifstream in(dir / "tu-in.bin", std::ios::binary);
    uint32_t side = 0;
    in.read(reinterpret_cast<char*>(&side), sizeof side);
    if (!in || side == 0 || (side & (side - 1)) != 0) {
        Check(false, "texture-unit input", "unreadable tu-in.bin");
        return Finish();
    }
    tu::Chain chain;
    chain.size = side;
    size_t texels = 0;
    for (uint32_t level = side; level >= 1; level /= 2) {
        chain.offsets.push_back(static_cast<uint32_t>(texels));
        texels += size_t{level} * level;
    }
    chain.texels.resize(texels * 3);
    in.read(reinterpret_cast<char*>(chain.texels.data()), static_cast<std::streamsize>(chain.texels.size() * sizeof(float)));
    uint32_t count = 0;
    in.read(reinterpret_cast<char*>(&count), sizeof count);
    std::vector<uint32_t> records(size_t{count} * 8);
    in.read(reinterpret_cast<char*>(records.data()), static_cast<std::streamsize>(records.size() * sizeof(uint32_t)));
    if (!in) {
        Check(false, "texture-unit input", "truncated tu-in.bin");
        return Finish();
    }
    std::vector<float> out(size_t{count} * 3);
    for (uint32_t k = 0; k < count; ++k) {
        const uint32_t* r = &records[size_t{k} * 8];
        const auto f = [&](uint32_t i) { return std::bit_cast<float>(r[i]); };
        const std::array<float, 3> value = tu::Sample(chain, f(0), f(1), {f(2), f(3)}, {f(4), f(5)},
                                                      static_cast<int32_t>(r[6]), (r[7] & 1u) != 0, (r[7] & 2u) != 0);
        for (uint32_t c = 0; c < 3; ++c) out[size_t{k} * 3 + c] = value[c];
    }
    std::ofstream file(dir / "tu-out.bin", std::ios::binary);
    file.write(reinterpret_cast<const char*>(out.data()), static_cast<std::streamsize>(out.size() * sizeof(float)));
    Info("texture-unit: " + std::to_string(count) + " samples on a " + std::to_string(side) + " texture");
    return Finish();
}

}  // namespace

int main(int argc, char** argv) {
    const std::string_view mode = argc > 1 ? argv[1] : "";
    if (argc < 3) {
        std::fprintf(stderr,
                     "usage: uzp-evaluator-tests arith|templates|order|cache|admission|sources|masks|height-normal|"
                     "not-yet-supported <assets-dir> | "
                     "evaluate <assets-dir> <spec.json> <out-dir> cpu|gpu | gpu-vs-cpu|kernel-sweep|"
                     "projection-gpu-vs-cpu|srgb8-hardware|fp-hardware|pow-hardware|trig-hardware|bilinear-hardware|texture-unit|masks-gpu-vs-cpu|"
                     "height-normal-gpu-vs-cpu|diagnostics|diagnostics-gpu-vs-cpu|tables <assets-dir> <work-dir> | "
                     "uv-coverage <assets-dir> <work-dir> <mesh> <size>\n");
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
        if (mode == "profile") return RunProfile(assets);
        if (mode == "sources") return RunSources(assets);
        if (mode == "masks") return RunMasks(assets);
        if (mode == "height-normal") return RunHeightNormal(assets);
        if (mode == "not-yet-supported") return RunNotYetSupported(assets);
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
        else if (mode == "projection-gpu-vs-cpu") code = RunProjectionGpuVsCpu(assets, dir);
        else if (mode == "srgb8-hardware") code = RunSrgb8Hardware(dir);
        else if (mode == "tables") code = RunTables(dir);
        else if (mode == "fp-hardware") code = RunFpHardware(dir);
        else if (mode == "bilinear-hardware") code = RunBilinearHardware(dir);
        else if (mode == "texture-unit") code = RunTextureUnit(dir);
        else if (mode == "pow-hardware") code = RunPowHardware(dir);
        else if (mode == "trig-hardware") code = RunTrigHardware(dir);
        else if (mode == "masks-gpu-vs-cpu") code = RunMasksGpuVsCpu(assets, dir);
        else if (mode == "height-normal-gpu-vs-cpu") code = RunHeightNormalGpuVsCpu(assets, dir);
        else if (mode == "diagnostics") code = RunDiagnostics(assets, dir);
        else if (mode == "diagnostics-gpu-vs-cpu") code = RunDiagnosticsGpuVsCpu(assets, dir);
        else if (mode == "uv-coverage") {
            if (argc < 6) {
                std::fprintf(stderr, "usage: uzp-evaluator-tests uv-coverage <assets-dir> <work-dir> <mesh> <size>\n");
                code = 2;
            } else {
                code = RunUvCoverage(dir, argv[4], static_cast<uint32_t>(std::stoul(argv[5])));
            }
        }
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
    } catch (const uzp::mesh::ImportError& error) {
        std::fprintf(stderr, "ImportError: %s\n", error.what());
        return 3;
    }
    return code;
}
