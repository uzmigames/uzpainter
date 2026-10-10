// Native tests of the render layer's GPU image passes (rulebook task phase1.3_core-image-passes):
// jump-flood dilation (src/render/dilation.h), resampling (resample.h) and mip generation
// (mips.h), each compared bit for bit with its CPU reference (tests/render/reference/). Run by
// uzp-render-tests.exe (render_core_test.cpp dispatches here) and driven by
// tests/render/test_core_image_passes.py.
//
//   image-reference  CPU only: the references against the published fits and each other
//   image-dilation   dilation of two islands and of random masks on DX12
//   image-resample   identity copies, up- and down-sampling of every filter and colour mode
//   image-mips       sRGB-aware, linear, normal and alpha-coverage mip chains
//   image-repeat     every pass twice on the same input: byte-identical outputs

#include "image_passes_test.h"

#include "reference/image_reference.h"
#include "render/capabilities.h"
#include "render/dilation.h"
#include "render/engine_thread.h"
#include "render/image_pass.h"
#include "render/mips.h"
#include "render/resample.h"
#include "render/texture_readback.h"

#include <algorithm>
#include <bit>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <functional>
#include <future>
#include <memory>
#include <optional>
#include <random>
#include <string>
#include <utility>
#include <vector>

namespace {

using namespace uzp::render;
namespace ref = uzp::render::reference;
namespace fs = std::filesystem;

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
std::string Describe(const Result<T>& result) {
    return result ? std::string("success") : result.error().Describe();
}

std::string Size(uint32_t w, uint32_t h) { return std::to_string(w) + "x" + std::to_string(h); }

// ── Formats and synthetic images ─────────────────────────────────────────────

ref::Encoding RefEncoding(TexelEncoding encoding) {
    switch (encoding) {
        case TexelEncoding::Unorm8: return ref::Encoding::Unorm8;
        case TexelEncoding::Unorm16: return ref::Encoding::Unorm16;
        case TexelEncoding::Float16: return ref::Encoding::Float16;
        case TexelEncoding::Float32: return ref::Encoding::Float32;
    }
    return ref::Encoding::Unorm8;
}

ref::Colour RefColour(ColourMode mode) {
    switch (mode) {
        case ColourMode::Linear: return ref::Colour::Linear;
        case ColourMode::Srgb: return ref::Colour::Srgb;
        case ColourMode::Normal: return ref::Colour::Normal;
    }
    return ref::Colour::Linear;
}

const char* ColourName(ColourMode mode) {
    switch (mode) {
        case ColourMode::Linear: return "linear";
        case ColourMode::Srgb: return "sRGB";
        case ColourMode::Normal: return "normal";
    }
    return "?";
}

const char* FilterName(ResampleFilter filter) {
    switch (filter) {
        case ResampleFilter::Nearest: return "Nearest";
        case ResampleFilter::Bilinear: return "Bilinear";
        case ResampleFilter::Box: return "Box";
    }
    return "?";
}

ref::Image Blank(uz::RHIFormat format, uint32_t w, uint32_t h) {
    const ImagePassFormat layout = *ImagePassFormatOf(format);
    return ref::MakeImage(w, h, layout.channels, RefEncoding(layout.encoding));
}

/// A float value of the normal range, held exactly by the encoding (halves rounded).
uint32_t FloatValue(float value, ref::Encoding encoding) {
    return encoding == ref::Encoding::Float16 ? ref::RoundToHalfBits(value)
                                              : std::bit_cast<uint32_t>(value);
}

/// Random values: codes for unorm, floats in [1/1024, 1] for float encodings (no denormals).
ref::Image RandomImage(uz::RHIFormat format, uint32_t w, uint32_t h, uint32_t seed) {
    ref::Image image = Blank(format, w, h);
    std::mt19937 rng(seed);
    const bool unorm = ref::IsUnorm(image.encoding);
    const uint32_t m = unorm ? ref::UnormMax(image.encoding) : 0;
    for (uint32_t& value : image.values) {
        if (unorm) {
            value = rng() % (m + 1);
        } else {
            const float v = static_cast<float>(1 + rng() % 1024) / 1024.0f;
            value = FloatValue(v, image.encoding);
        }
    }
    return image;
}

/// A smooth bumpy normal field (z > 0) in four channels, alpha a ramp.
ref::Image NormalImage(uz::RHIFormat format, uint32_t w, uint32_t h) {
    ref::Image image = Blank(format, w, h);
    const bool unorm = ref::IsUnorm(image.encoding);
    const double m = unorm ? ref::UnormMax(image.encoding) : 1.0;
    for (uint32_t y = 0; y < h; ++y) {
        for (uint32_t x = 0; x < w; ++x) {
            const double nx = 0.6 * std::sin(x * 0.37 + y * 0.11);
            const double ny = 0.6 * std::cos(y * 0.29 - x * 0.07);
            const double nz = std::sqrt(std::max(0.05, 1.0 - nx * nx - ny * ny));
            const double len = std::sqrt(nx * nx + ny * ny + nz * nz);
            const double n[3] = {nx / len, ny / len, nz / len};
            for (uint32_t c = 0; c < 3; ++c) {
                image.At(x, y, c) = unorm ? static_cast<uint32_t>(std::lround((n[c] * 0.5 + 0.5) * m))
                                          : FloatValue(static_cast<float>(n[c]), image.encoding);
            }
            const double alpha = (x + y) / static_cast<double>(w + h);
            image.At(x, y, 3) = unorm ? static_cast<uint32_t>(std::lround(alpha * m))
                                      : FloatValue(static_cast<float>(alpha + 0.001), image.encoding);
        }
    }
    return image;
}

/// An albedo with an alpha mask of leaves: alpha codes spread over the whole range.
ref::Image FoliageImage(uint32_t w, uint32_t h, uint32_t seed) {
    ref::Image image = ref::MakeImage(w, h, 4, ref::Encoding::Unorm8);
    std::mt19937 rng(seed);
    for (uint32_t y = 0; y < h; ++y) {
        for (uint32_t x = 0; x < w; ++x) {
            const double leaf = 0.5 + 0.5 * std::sin(x * 0.9) * std::cos(y * 0.7) +
                                0.25 * std::sin((x + 2.0 * y) * 0.31);
            image.At(x, y, 0) = rng() % 256;
            image.At(x, y, 1) = 64 + rng() % 128;
            image.At(x, y, 2) = rng() % 64;
            image.At(x, y, 3) =
                static_cast<uint32_t>(std::clamp(std::lround(leaf * 255.0), 0L, 255L));
        }
    }
    return image;
}

/// First mismatch between two images, or empty.
std::string Diff(const ref::Image& got, const ref::Image& want) {
    if (got.width != want.width || got.height != want.height || got.channels != want.channels) {
        return "size " + Size(got.width, got.height) + " vs " + Size(want.width, want.height);
    }
    size_t mismatches = 0;
    std::string first;
    for (uint32_t y = 0; y < got.height; ++y) {
        for (uint32_t x = 0; x < got.width; ++x) {
            for (uint32_t c = 0; c < got.channels; ++c) {
                if (got.At(x, y, c) == want.At(x, y, c)) continue;
                if (mismatches++ == 0) {
                    char buf[160];
                    std::snprintf(buf, sizeof(buf), "first at (%u, %u) channel %u: %08X vs %08X",
                                  x, y, c, got.At(x, y, c), want.At(x, y, c));
                    first = buf;
                }
            }
        }
    }
    return mismatches == 0 ? std::string()
                           : std::to_string(mismatches) + " values differ; " + first;
}

// ── GPU helpers ──────────────────────────────────────────────────────────────

struct Snapshot {
    int unused = 0;
};

EngineOptions Options(const fs::path& dir) {
    EngineOptions options;
    options.kernelCacheRoot = dir / "kernel-cache";
    return options;
}

bool NoAdapter(const Engine& engine) {
    if (!engine.DeviceError()) return false;
    std::printf("SKIP no DX12 device: %s\n", engine.DeviceError()->Describe().c_str());
    return true;
}

/// Runs `work` as one engine request and returns its result.
template <class T>
Result<T> Run(Engine& engine, std::function<Result<T>(EngineContext&)> work) {
    auto future = engine.Submit(std::make_shared<const Snapshot>(),
                                [work = std::move(work)](EngineContext& context,
                                                         const Snapshot&) { return work(context); });
    if (future.wait_for(std::chrono::seconds(300)) != std::future_status::ready) {
        return Fail(ErrorCode::RequestFailed, std::nullopt, "no result within 300 s");
    }
    return future.get();
}

const uz::RHITextureUsage kAllUsage =
    uz::RHITextureUsage::ShaderResource | uz::RHITextureUsage::UnorderedAccess |
    uz::RHITextureUsage::CopySrc | uz::RHITextureUsage::CopyDst;

/// Textures created in one request, destroyed with it.
class Textures {
public:
    explicit Textures(IDevice& device) : m_device(device) {}
    ~Textures() {
        for (const uz::RHITextureHandle texture : m_textures) m_device.DestroyTexture(texture);
    }
    Textures(const Textures&) = delete;
    Textures& operator=(const Textures&) = delete;

    Result<uz::RHITextureHandle> Create(uz::RHIFormat format, uint32_t w, uint32_t h,
                                        uint16_t mips = 1) {
        uz::RHITextureDesc desc;
        desc.width = w;
        desc.height = h;
        desc.mipLevels = mips;
        desc.format = format;
        desc.usage = kAllUsage;
        desc.debugName = "image_pass_test";
        Result<uz::RHITextureHandle> texture = m_device.CreateTexture(desc);
        if (texture) m_textures.push_back(*texture);
        return texture;
    }

private:
    IDevice& m_device;
    std::vector<uz::RHITextureHandle> m_textures;
};

/// Uploads `image` into mip `mip` (rows at the 256-byte pitch D3D12's copy footprint uses);
/// the texture is left in `Common`.
Result<void> Upload(EngineContext& context, uz::RHITextureHandle texture, const ref::Image& image,
                    uint32_t mip = 0) {
    IDevice& device = context.Device();
    const std::vector<std::byte> bytes = ref::ToBytes(image);
    const size_t rowBytes = bytes.size() / image.height;
    const uint64_t pitch = ReadbackRowPitch(rowBytes);
    uz::RHIBufferDesc desc;
    desc.sizeBytes = pitch * image.height;
    desc.usage = uz::RHIBufferUsage::CopySrc;
    desc.memory = uz::RHIMemoryType::Upload;
    desc.debugName = "image_pass_test_upload";
    Result<uz::RHIBufferHandle> buffer = device.CreateBuffer(desc);
    if (!buffer) return Unexpected(buffer.error());
    auto* mapped = static_cast<std::byte*>(device.Rhi().MapBuffer(*buffer));
    if (!mapped) {
        device.DestroyBuffer(*buffer);
        return Fail(ErrorCode::RequestFailed, Backend::Dx12, "upload buffer not mapped");
    }
    for (uint32_t y = 0; y < image.height; ++y) {
        std::memcpy(mapped + pitch * y, bytes.data() + rowBytes * y, rowBytes);
    }
    device.Rhi().UnmapBuffer(*buffer);
    const uz::RHIBufferHandle source = *buffer;
    Result<void> done = context.SubmitAndWait([&](uz::IRHICommandList& cmd) {
        const uz::RHIBarrierDesc toCopy{texture, uz::RHIBufferHandle::Invalid(),
                                        uz::RHIResourceState::Common,
                                        uz::RHIResourceState::CopyDst};
        cmd.ResourceBarrier(&toCopy, 1);
        cmd.CopyBufferToTexture(source, 0, static_cast<uint32_t>(pitch), texture, mip, 0);
        const uz::RHIBarrierDesc back{texture, uz::RHIBufferHandle::Invalid(),
                                      uz::RHIResourceState::CopyDst,
                                      uz::RHIResourceState::Common};
        cmd.ResourceBarrier(&back, 1);
    });
    device.DestroyBuffer(source);
    return done;
}

/// Reads mip `mip` of `texture` back as a reference image of `format`'s layout.
Result<ref::Image> Download(EngineContext& context, uz::RHITextureHandle texture,
                            uz::RHIFormat format, uint32_t mip = 0) {
    TextureReadback readback(context);
    ReadbackDesc desc;
    desc.texture = texture;
    desc.mipLevel = mip;
    Result<ReadbackId> id = readback.Request(desc);
    if (!id) return Unexpected(id.error());
    Result<ReadbackImage> image = readback.Complete(*id);
    if (!image) return Unexpected(image.error());
    const ImagePassFormat layout = *ImagePassFormatOf(format);
    return ref::FromBytes(image->width, image->height, layout.channels,
                          RefEncoding(layout.encoding), image->texels);
}

std::vector<uint8_t> CoveredMask(const ref::Image& mask) {
    std::vector<uint8_t> covered(size_t{mask.width} * mask.height);
    for (uint32_t y = 0; y < mask.height; ++y) {
        for (uint32_t x = 0; x < mask.width; ++x) {
            covered[size_t{y} * mask.width + x] = mask.At(x, y, 0) != 0 ? 1 : 0;
        }
    }
    return covered;
}

/// Two islands in an R8Unorm mask: a disc and an L-shaped block.
ref::Image IslandMask(uint32_t w, uint32_t h) {
    ref::Image mask = ref::MakeImage(w, h, 1, ref::Encoding::Unorm8);
    for (uint32_t y = 0; y < h; ++y) {
        for (uint32_t x = 0; x < w; ++x) {
            const double dx = x - 24.0;
            const double dy = y - 30.0;
            const bool disc = dx * dx + dy * dy <= 12.5 * 12.5;
            const bool block = (x >= 60 && x < 80 && y >= 40 && y < 48) ||
                               (x >= 72 && x < 80 && y >= 18 && y < 48);
            mask.At(x, y, 0) = disc || block ? 255 : 0;
        }
    }
    return mask;
}

ref::Image RandomMask(uint32_t w, uint32_t h, uint32_t seed, uint32_t percent) {
    ref::Image mask = ref::MakeImage(w, h, 1, ref::Encoding::Unorm8);
    std::mt19937 rng(seed);
    for (uint32_t& value : mask.values) value = rng() % 100 < percent ? 1 + rng() % 255 : 0;
    return mask;
}

// ── GPU pass runners (one request each) ──────────────────────────────────────

Result<ref::Image> GpuDilate(Engine& engine, uz::RHIFormat format, const ref::Image& colour,
                             const ref::Image& mask, uint32_t maxDistance) {
    return Run<ref::Image>(engine, [&](EngineContext& context) -> Result<ref::Image> {
        Textures textures(context.Device());
        Result<uz::RHITextureHandle> c = textures.Create(format, colour.width, colour.height);
        Result<uz::RHITextureHandle> m = textures.Create(uz::RHIFormat::R8Unorm, mask.width,
                                                         mask.height);
        Result<uz::RHITextureHandle> o = textures.Create(format, colour.width, colour.height);
        if (!c || !m || !o) return Unexpected((!c ? c : !m ? m : o).error());
        if (Result<void> up = Upload(context, *c, colour); !up) return Unexpected(up.error());
        if (Result<void> up = Upload(context, *m, mask); !up) return Unexpected(up.error());
        DilationDesc desc;
        desc.colour = *c;
        desc.coverage = *m;
        desc.output = *o;
        desc.maxDistance = maxDistance;
        if (Result<void> done = Dilate(context, desc); !done) return Unexpected(done.error());
        return Download(context, *o, format);
    });
}

Result<ref::Image> GpuResample(Engine& engine, uz::RHIFormat format, const ref::Image& source,
                               uint32_t w, uint32_t h, const ResampleOptions& options) {
    return Run<ref::Image>(engine, [&](EngineContext& context) -> Result<ref::Image> {
        Textures textures(context.Device());
        Result<uz::RHITextureHandle> s = textures.Create(format, source.width, source.height);
        Result<uz::RHITextureHandle> d = textures.Create(format, w, h);
        if (!s || !d) return Unexpected((!s ? s : d).error());
        if (Result<void> up = Upload(context, *s, source); !up) return Unexpected(up.error());
        if (Result<void> done = Resample(context, *s, *d, options); !done) {
            return Unexpected(done.error());
        }
        return Download(context, *d, format);
    });
}

Result<std::vector<ref::Image>> GpuMips(Engine& engine, uz::RHIFormat format,
                                        const ref::Image& base, uint16_t levels,
                                        const MipOptions& options) {
    return Run<std::vector<ref::Image>>(
        engine, [&](EngineContext& context) -> Result<std::vector<ref::Image>> {
            Textures textures(context.Device());
            Result<uz::RHITextureHandle> t = textures.Create(format, base.width, base.height,
                                                             levels);
            if (!t) return Unexpected(t.error());
            if (Result<void> up = Upload(context, *t, base); !up) return Unexpected(up.error());
            if (Result<void> done = GenerateMips(context, *t, options); !done) {
                return Unexpected(done.error());
            }
            std::vector<ref::Image> chain;
            for (uint32_t k = 0; k < levels; ++k) {
                Result<ref::Image> level = Download(context, *t, format, k);
                if (!level) return Unexpected(level.error());
                chain.push_back(std::move(*level));
            }
            return chain;
        });
}

uint16_t FullChain(uint32_t w, uint32_t h) {
    uint16_t levels = 1;
    while ((std::max(w, h) >> levels) > 0) ++levels;
    return levels;
}

// ── image-reference (CPU) ────────────────────────────────────────────────────

int RunReference() {
    bool painter = true;
    for (uint64_t s = 0; s <= 256ull * 65535ull && painter; ++s) {
        painter = ref::WriteRatio(s, 256, 16) == ref::PainterBilinearStore16(s);
    }
    Check(painter,
          "the write rule equals the resampling.json BilinearHQ storage formula for every 16-bit "
          "weighted sum");

    bool tiesDown = true;
    for (uint32_t c = 0; c < 255; ++c) tiesDown &= ref::WriteRatio(2 * c + 1, 2, 8) == c;
    for (uint32_t c = 0; c < 65535; c += 97) tiesDown &= ref::WriteRatio(2 * c + 1, 2, 16) == c;
    Check(tiesDown, "the write rule rounds a value halfway between codes down");
    bool exactCodes = true;
    for (uint32_t c = 0; c <= 255; ++c) {
        exactCodes &= ref::WriteValue(static_cast<float>(c) / 255.0f, 8) == c;
    }
    for (uint32_t c = 0; c <= 65535; ++c) {
        exactCodes &= ref::WriteValue(static_cast<float>(c) / 65535.0f, 16) == c;
    }
    Check(exactCodes, "the float-to-UNORM write rule maps every code's value back to the code");

    bool srgb = true;
    for (uint32_t c = 0; c < 256; ++c) srgb &= ref::SrgbEncode(ref::SrgbDecode(c)) == c;
    for (uint32_t c = 1; c < 256; ++c) srgb &= ref::SrgbDecode(c) > ref::SrgbDecode(c - 1);
    Check(srgb, "sRGB encode inverts decode for every 8-bit code; decode is increasing");

    Check(JumpFloodSteps(96, 80, 8) == std::vector<uint32_t>{1, 8, 4, 2, 1},
          "jump-flood steps for an 8-texel limit are 1, 8, 4, 2, 1");
    Check(JumpFloodSteps(96, 80, kUnlimitedDistance) ==
              std::vector<uint32_t>{1, 64, 32, 16, 8, 4, 2, 1},
          "unlimited jump flooding on 96x80 steps 1, 64, ..., 1");
    Check(JumpFloodSteps(96, 80, 0).empty() && JumpFloodSteps(1, 1, kUnlimitedDistance).empty(),
          "a zero limit or a single texel needs no step");
    Check(MipExtent(45, 1) == 22 && MipExtent(45, 5) == 1 && MipExtent(45, 9) == 1 &&
              MipExtent(64, 6) == 1,
          "mip extents are max(1, extent >> level)");
    Check(AlphaCutoffCode(0.5f, TexelEncoding::Unorm8) == 128 &&
              AlphaCutoffCode(0.5f, TexelEncoding::Unorm16) == 32768 &&
              AlphaCutoffCode(1e-9f, TexelEncoding::Unorm8) == 1,
          "the alpha cutoff code is ceil(cutoff M), at least 1");

    // Jump flooding against the exact nearest covered texel on the island masks.
    const ref::Image mask = IslandMask(96, 80);
    const std::vector<uint8_t> covered = CoveredMask(mask);
    const ref::Image colour = RandomImage(uz::RHIFormat::RGBA8Unorm, 96, 80, 7);
    for (const uint32_t limit : {8u, kUnlimitedDistance}) {
        const std::string diff = Diff(ref::DilateJumpFlood(colour, covered, limit),
                                      ref::DilateBruteForce(colour, covered, limit));
        Check(diff.empty(),
              "jump flooding equals the nearest covered texel on the two islands (limit " +
                  (limit == kUnlimitedDistance ? std::string("unlimited") : std::to_string(limit)) +
                  ")",
              diff);
    }
    size_t randomMismatches = 0;
    for (uint32_t seed = 1; seed <= 4; ++seed) {
        const std::vector<uint8_t> cov = CoveredMask(RandomMask(128, 128, seed, 2));
        const ref::Image rc = RandomImage(uz::RHIFormat::RGBA8Unorm, 128, 128, seed);
        const ref::Image jfa = ref::DilateJumpFlood(rc, cov, kUnlimitedDistance);
        const ref::Image brute = ref::DilateBruteForce(rc, cov, kUnlimitedDistance);
        for (size_t i = 0; i < jfa.values.size(); i += 4) {
            randomMismatches += std::equal(jfa.values.begin() + i, jfa.values.begin() + i + 4,
                                           brute.values.begin() + i)
                                    ? 0
                                    : 1;
        }
    }
    Info("jump flooding vs exact nearest on four random 2 % masks (128x128): " +
         std::to_string(randomMismatches) + " of 65536 texels differ");
    return Finish();
}

// ── image-dilation ───────────────────────────────────────────────────────────

constexpr uz::RHIFormat kDilationFormats[] = {uz::RHIFormat::RGBA8Unorm,
                                              uz::RHIFormat::RGBA16Unorm,
                                              uz::RHIFormat::RGBA16Float, uz::RHIFormat::R32Float};

int RunDilation(const fs::path& dir) {
    Engine engine(Options(dir));
    if (NoAdapter(engine)) return kExitSkip;
    const ref::Image mask = IslandMask(96, 80);
    const std::vector<uint8_t> covered = CoveredMask(mask);

    bool allEqual = true;
    bool allBrute = true;
    bool untouched = true;
    for (const uz::RHIFormat format : kDilationFormats) {
        const std::string name(FormatName(format));
        const ref::Image colour = RandomImage(format, 96, 80, 11);
        Result<ref::Image> gpu = GpuDilate(engine, format, colour, mask, 8);
        Check(gpu.has_value(), name + ": dilation runs", Describe(gpu));
        if (!gpu) {
            allEqual = allBrute = untouched = false;
            continue;
        }
        const std::string vsJfa = Diff(*gpu, ref::DilateJumpFlood(colour, covered, 8));
        const std::string vsBrute = Diff(*gpu, ref::DilateBruteForce(colour, covered, 8));
        Check(vsJfa.empty(), name + ": two islands, distance 8, equal the CPU jump-flood reference",
              vsJfa);
        Check(vsBrute.empty(), name + ": two islands, distance 8, equal the nearest covered texel",
              vsBrute);
        allEqual &= vsJfa.empty();
        allBrute &= vsBrute.empty();
        // Covered texels and texels farther than 8 from both islands keep their colour.
        size_t changed = 0;
        size_t filled = 0;
        for (uint32_t y = 0; y < 80; ++y) {
            for (uint32_t x = 0; x < 96; ++x) {
                uint32_t nearest = 0xFFFFFFFFu;
                for (uint32_t i = 0; i < covered.size(); ++i) {
                    if (!covered[i]) continue;
                    const int64_t dx = int64_t{x} - i % 96;
                    const int64_t dy = int64_t{y} - i / 96;
                    nearest = std::min<uint32_t>(nearest, static_cast<uint32_t>(dx * dx + dy * dy));
                }
                bool same = true;
                for (uint32_t c = 0; c < colour.channels; ++c) same &= gpu->At(x, y, c) == colour.At(x, y, c);
                if (nearest == 0 || nearest > 64) {
                    changed += same ? 0 : 1;
                } else {
                    ++filled;
                }
            }
        }
        Check(changed == 0, name + ": covered texels and texels beyond 8 texels stay unchanged",
              std::to_string(changed) + " changed");
        untouched &= changed == 0;
        Info(name + ": " + std::to_string(filled) + " texels within distance 8 filled");
    }
    Check(allEqual && allBrute && untouched,
          "dilation on synthetic islands equals the CPU nearest-covered-texel reference");

    // Unlimited distance: every texel takes its nearest island's colour.
    const ref::Image colour = RandomImage(uz::RHIFormat::RGBA8Unorm, 96, 80, 12);
    Result<ref::Image> unlimited =
        GpuDilate(engine, uz::RHIFormat::RGBA8Unorm, colour, mask, kUnlimitedDistance);
    const std::string unlimitedDiff =
        unlimited ? Diff(*unlimited, ref::DilateBruteForce(colour, covered, kUnlimitedDistance))
                  : Describe(unlimited);
    Check(unlimited && unlimitedDiff.empty(),
          "unlimited dilation fills every texel with its nearest island's colour", unlimitedDiff);

    // Random masks: the GPU runs exactly the CPU jump-flood arithmetic.
    bool randomEqual = true;
    for (uint32_t seed = 1; seed <= 3; ++seed) {
        const ref::Image random = RandomMask(128, 112, seed, 2);
        const std::vector<uint8_t> cov = CoveredMask(random);
        const ref::Image rc = RandomImage(uz::RHIFormat::RGBA16Unorm, 128, 112, seed + 20);
        for (const uint32_t limit : {5u, kUnlimitedDistance}) {
            Result<ref::Image> gpu = GpuDilate(engine, uz::RHIFormat::RGBA16Unorm, rc, random, limit);
            const std::string diff =
                gpu ? Diff(*gpu, ref::DilateJumpFlood(rc, cov, limit)) : Describe(gpu);
            if (!diff.empty()) Info("random mask " + std::to_string(seed) + ": " + diff);
            randomEqual &= diff.empty();
        }
    }
    Check(randomEqual, "dilation of random masks equals the CPU jump-flood reference exactly");

    Result<ref::Image> none = GpuDilate(engine, uz::RHIFormat::RGBA8Unorm, colour, mask, 0);
    Check(none && Diff(*none, colour).empty(), "distance 0 copies the colour unchanged",
          none ? Diff(*none, colour) : Describe(none));

    Result<int> invalid = Run<int>(engine, [](EngineContext& context) -> Result<int> {
        Textures textures(context.Device());
        Result<uz::RHITextureHandle> c = textures.Create(uz::RHIFormat::RGBA8Unorm, 16, 16);
        Result<uz::RHITextureHandle> m = textures.Create(uz::RHIFormat::R8Unorm, 8, 8);
        Result<uz::RHITextureHandle> o = textures.Create(uz::RHIFormat::RGBA8Unorm, 16, 16);
        if (!c || !m || !o) return Unexpected((!c ? c : !m ? m : o).error());
        Result<void> done = Dilate(context, DilationDesc{*c, *m, *o, 4});
        if (done) return 0;
        return done.error().code == ErrorCode::RequestFailed ? 1 : 2;
    });
    Check(invalid && *invalid == 1, "a coverage mask of another size is rejected with request_failed",
          Describe(invalid));
    return Finish();
}

// ── image-resample ───────────────────────────────────────────────────────────

struct ResampleCase {
    uz::RHIFormat format;
    ColourMode colour;
};

constexpr ResampleCase kResampleCases[] = {
    {uz::RHIFormat::RGBA8Unorm, ColourMode::Linear},  {uz::RHIFormat::RGBA16Unorm, ColourMode::Linear},
    {uz::RHIFormat::R16Unorm, ColourMode::Linear},    {uz::RHIFormat::RG8Unorm, ColourMode::Linear},
    {uz::RHIFormat::RGBA16Float, ColourMode::Linear}, {uz::RHIFormat::R32Float, ColourMode::Linear},
    {uz::RHIFormat::RG16Float, ColourMode::Linear},   {uz::RHIFormat::RGBA32Float, ColourMode::Linear},
    {uz::RHIFormat::RGBA8Unorm, ColourMode::Srgb},    {uz::RHIFormat::R8Unorm, ColourMode::Srgb},
    {uz::RHIFormat::RGBA16Unorm, ColourMode::Normal}, {uz::RHIFormat::RGBA8Unorm, ColourMode::Normal},
    {uz::RHIFormat::RGBA16Float, ColourMode::Normal},
};

int RunResample(const fs::path& dir) {
    Engine engine(Options(dir));
    if (NoAdapter(engine)) return kExitSkip;
    constexpr uint32_t kW = 37;
    constexpr uint32_t kH = 29;
    const std::pair<uint32_t, uint32_t> sizes[] = {{64, 48}, {16, 11}, {37, 58}, {5, 3}, {111, 29}};

    bool identity = true;
    bool scaled = true;
    for (const ResampleCase& rc : kResampleCases) {
        const std::string name = std::string(FormatName(rc.format)) + " " + ColourName(rc.colour);
        const ref::Image source = rc.colour == ColourMode::Normal
                                      ? NormalImage(rc.format, kW, kH)
                                      : RandomImage(rc.format, kW, kH, 31);
        for (const ResampleFilter filter :
             {ResampleFilter::Nearest, ResampleFilter::Bilinear, ResampleFilter::Box}) {
            const ResampleOptions same{filter, ResampleWrap::Clamp, rc.colour};
            Result<ref::Image> copy = GpuResample(engine, rc.format, source, kW, kH, same);
            const std::string copyDiff = copy ? Diff(*copy, source) : Describe(copy);
            Check(copyDiff.empty(), name + " " + FilterName(filter) + ": identity size is bit-exact",
                  copyDiff);
            identity &= copyDiff.empty();
            for (const ResampleWrap wrap : {ResampleWrap::Clamp, ResampleWrap::Repeat}) {
                if (wrap == ResampleWrap::Repeat && filter != ResampleFilter::Bilinear) continue;
                const ResampleOptions options{filter, wrap, rc.colour};
                std::string failures;
                for (const auto& [w, h] : sizes) {
                    Result<ref::Image> gpu = GpuResample(engine, rc.format, source, w, h, options);
                    const ref::Image want =
                        ref::Resample(source, w, h, static_cast<ref::Filter>(filter),
                                      static_cast<ref::Wrap>(wrap), RefColour(rc.colour));
                    const std::string diff = gpu ? Diff(*gpu, want) : Describe(gpu);
                    if (!diff.empty()) failures += Size(w, h) + ": " + diff + "; ";
                }
                Check(failures.empty(),
                      name + " " + FilterName(filter) +
                          (wrap == ResampleWrap::Repeat ? " repeat" : " clamp") +
                          ": up- and down-sampling equal the CPU reference",
                      failures);
                scaled &= failures.empty();
            }
        }
    }
    Check(identity, "resampling at identity size is bit-exact for every format and filter");
    Check(scaled,
          "up- and down-sampling equal the CPU reference for every format, filter and colour mode");

    Result<int> invalid = Run<int>(engine, [](EngineContext& context) -> Result<int> {
        Textures textures(context.Device());
        Result<uz::RHITextureHandle> s = textures.Create(uz::RHIFormat::RGBA16Float, 16, 16);
        Result<uz::RHITextureHandle> d = textures.Create(uz::RHIFormat::RGBA16Float, 8, 8);
        if (!s || !d) return Unexpected((!s ? s : d).error());
        Result<void> done =
            Resample(context, *s, *d, {ResampleFilter::Box, ResampleWrap::Clamp, ColourMode::Srgb});
        if (done) return 0;
        return done.error().code == ErrorCode::RequestFailed ? 1 : 2;
    });
    Check(invalid && *invalid == 1, "sRGB filtering of a float format is rejected with request_failed",
          Describe(invalid));
    return Finish();
}

// ── image-mips ───────────────────────────────────────────────────────────────

std::string ChainDiff(const Result<std::vector<ref::Image>>& gpu,
                      const std::vector<ref::Image>& want) {
    if (!gpu) return Describe(gpu);
    if (gpu->size() != want.size()) return "level count differs";
    std::string failures;
    for (size_t k = 0; k < want.size(); ++k) {
        const std::string diff = Diff((*gpu)[k], want[k]);
        if (!diff.empty()) failures += "level " + std::to_string(k) + ": " + diff + "; ";
    }
    return failures;
}

/// The largest deviation from unit length of the stored normals of a chain's levels >= 1.
double WorstUnitError(const std::vector<ref::Image>& chain) {
    double worst = 0.0;
    for (size_t k = 1; k < chain.size(); ++k) {
        const ref::Image& level = chain[k];
        const bool unorm = ref::IsUnorm(level.encoding);
        const double m = unorm ? ref::UnormMax(level.encoding) : 1.0;
        for (uint32_t y = 0; y < level.height; ++y) {
            for (uint32_t x = 0; x < level.width; ++x) {
                double sq = 0.0;
                for (uint32_t c = 0; c < 3; ++c) {
                    const uint32_t v = level.At(x, y, c);
                    const double n = unorm ? 2.0 * v / m - 1.0 : std::bit_cast<float>(v);
                    sq += n * n;
                }
                worst = std::max(worst, std::abs(std::sqrt(sq) - 1.0));
            }
        }
    }
    return worst;
}

int RunMips(const fs::path& dir) {
    Engine engine(Options(dir));
    if (NoAdapter(engine)) return kExitSkip;

    // sRGB-aware chains: decode, filter, encode per level.
    for (const auto& [w, h] : {std::pair<uint32_t, uint32_t>{64, 40}, {45, 27}}) {
        const ref::Image base = RandomImage(uz::RHIFormat::RGBA8Unorm, w, h, 41);
        const uint16_t levels = FullChain(w, h);
        const auto gpu = GpuMips(engine, uz::RHIFormat::RGBA8Unorm, base, levels,
                                 MipOptions{ColourMode::Srgb, false, 0.5f});
        const std::string diff =
            ChainDiff(gpu, ref::MipChain(base, levels, ref::Colour::Srgb, 0));
        Check(diff.empty(),
              "sRGB8 " + Size(w, h) + ": every level of the " + std::to_string(levels) +
                  "-level chain equals the CPU decode-filter-encode reference",
              diff);
    }

    // Linear chains of unorm and float formats, odd sizes included.
    for (const uz::RHIFormat format : {uz::RHIFormat::RGBA16Unorm, uz::RHIFormat::R16Float,
                                       uz::RHIFormat::RGBA32Float, uz::RHIFormat::RG8Unorm}) {
        const ref::Image base = RandomImage(format, 45, 27, 43);
        const uint16_t levels = FullChain(45, 27);
        const auto gpu = GpuMips(engine, format, base, levels, MipOptions{});
        const std::string diff =
            ChainDiff(gpu, ref::MipChain(base, levels, ref::Colour::Linear, 0));
        Check(diff.empty(),
              std::string(FormatName(format)) + " 45x27: the linear chain equals the CPU reference",
              diff);
    }

    // Normal chains: renormalised, unit length at storage precision.
    for (const uz::RHIFormat format : {uz::RHIFormat::RGBA16Unorm, uz::RHIFormat::RGBA8Unorm,
                                       uz::RHIFormat::RGBA16Float}) {
        const std::string name(FormatName(format));
        const ref::Image base = NormalImage(format, 64, 48);
        const uint16_t levels = FullChain(64, 48);
        const auto gpu = GpuMips(engine, format, base, levels,
                                 MipOptions{ColourMode::Normal, false, 0.5f});
        const std::string diff =
            ChainDiff(gpu, ref::MipChain(base, levels, ref::Colour::Normal, 0));
        Check(diff.empty(), name + ": the normal chain equals the CPU renormalising reference",
              diff);
        if (!gpu) continue;
        // Quantisation moves each component by at most 1.125 codes (half a code plus the
        // n + 4 bit truncation), i.e. 2.25 / M in [-1, 1]; half floats by 2^-11 relative.
        double bound = 0.0;
        const ImagePassFormat layout = *ImagePassFormatOf(format);
        if (layout.encoding == TexelEncoding::Float16) {
            bound = std::sqrt(3.0) * std::ldexp(1.0, -11) + 1e-6;
        } else {
            const double m = layout.encoding == TexelEncoding::Unorm8 ? 255.0 : 65535.0;
            bound = std::sqrt(3.0) * 1.125 / m + 1e-6;
        }
        const double worst = WorstUnitError(*gpu);
        Check(worst <= bound, name + ": normal mips are unit length at storage precision",
              "worst |length - 1| " + std::to_string(worst) + " > " + std::to_string(bound));
        Info(name + ": worst |length - 1| = " + std::to_string(worst) + " (bound " +
             std::to_string(bound) + ")");
    }

    // Alpha coverage at the test cutoff 0.5 (code 128), with linear and sRGB colour.
    const ref::Image foliage = FoliageImage(64, 64, 47);
    const uint32_t cutoff = AlphaCutoffCode(0.5f, TexelEncoding::Unorm8);
    const uint16_t levels = FullChain(64, 64);
    const uint64_t count0 = ref::CoveredTexels(foliage, cutoff);
    for (const ColourMode colour : {ColourMode::Linear, ColourMode::Srgb}) {
        const auto gpu =
            GpuMips(engine, uz::RHIFormat::RGBA8Unorm, foliage, levels, MipOptions{colour, true, 0.5f});
        const std::string diff =
            ChainDiff(gpu, ref::MipChain(foliage, levels, RefColour(colour), cutoff));
        Check(diff.empty(),
              std::string("alpha coverage (") + ColourName(colour) +
                  "): the chain equals the CPU coverage-preserving reference",
              diff);
        if (!gpu || colour != ColourMode::Linear) continue;
        std::string drift;
        for (uint32_t k = 1; k < levels; ++k) {
            const ref::Image& level = (*gpu)[k];
            const uint64_t texels = uint64_t{level.width} * level.height;
            const uint64_t target = (2 * count0 * texels + 4096 - 1) / (2 * 4096);
            const uint64_t got = ref::CoveredTexels(level, cutoff);
            Info("level " + std::to_string(k) + ": covered " + std::to_string(got) + " of " +
                 std::to_string(texels) + ", target " + std::to_string(target));
            if (got != target) drift += "level " + std::to_string(k) + "; ";
        }
        Check(drift.empty(), "alpha coverage at the test cutoff is preserved on every level",
              drift);
    }
    const std::vector<ref::Image> plain = ref::MipChain(foliage, levels, ref::Colour::Linear, 0);
    Info("without preservation level 3 covers " + std::to_string(ref::CoveredTexels(plain[3], cutoff)) +
         " of 64 texels (level 0: " + std::to_string(count0) + " of 4096)");
    return Finish();
}

// ── image-repeat ─────────────────────────────────────────────────────────────

int RunRepeat(const fs::path& dir) {
    Engine engine(Options(dir));
    if (NoAdapter(engine)) return kExitSkip;
    const ref::Image mask = RandomMask(128, 96, 5, 3);
    const ref::Image colour = RandomImage(uz::RHIFormat::RGBA16Float, 128, 96, 6);
    const ref::Image albedo = RandomImage(uz::RHIFormat::RGBA8Unorm, 128, 96, 8);
    const ref::Image normals = NormalImage(uz::RHIFormat::RGBA16Unorm, 128, 96);
    const ref::Image foliage = FoliageImage(128, 96, 9);

    struct Pass {
        std::string name;
        std::function<Result<std::vector<ref::Image>>()> run;
    };
    auto single = [](Result<ref::Image> image) -> Result<std::vector<ref::Image>> {
        if (!image) return Unexpected(image.error());
        return std::vector<ref::Image>{std::move(*image)};
    };
    const std::vector<Pass> passes = {
        {"dilation", [&] { return single(GpuDilate(engine, uz::RHIFormat::RGBA16Float, colour, mask,
                                                   kUnlimitedDistance)); }},
        {"bilinear resampling", [&] {
             return single(GpuResample(engine, uz::RHIFormat::RGBA8Unorm, albedo, 301, 77,
                                       {ResampleFilter::Bilinear, ResampleWrap::Repeat,
                                        ColourMode::Srgb}));
         }},
        {"box resampling", [&] {
             return single(GpuResample(engine, uz::RHIFormat::RGBA16Float, colour, 45, 31,
                                       {ResampleFilter::Box, ResampleWrap::Clamp,
                                        ColourMode::Linear}));
         }},
        {"normal mips", [&] {
             return GpuMips(engine, uz::RHIFormat::RGBA16Unorm, normals, FullChain(128, 96),
                            {ColourMode::Normal, false, 0.5f});
         }},
        {"sRGB alpha-coverage mips", [&] {
             return GpuMips(engine, uz::RHIFormat::RGBA8Unorm, foliage, FullChain(128, 96),
                            {ColourMode::Srgb, true, 0.5f});
         }},
    };
    bool all = true;
    for (const Pass& pass : passes) {
        Result<std::vector<ref::Image>> first = pass.run();
        Result<std::vector<ref::Image>> second = pass.run();
        bool same = first && second && first->size() == second->size();
        for (size_t i = 0; same && i < first->size(); ++i) {
            same = ref::ToBytes((*first)[i]) == ref::ToBytes((*second)[i]);
        }
        Check(same, pass.name + ": two runs give byte-identical output",
              first && second ? "outputs differ" : Describe(first) + " / " + Describe(second));
        all &= same;
    }
    Check(all, "every image pass produces byte-identical output across two runs");
    return Finish();
}

}  // namespace

int RunImagePassCase(std::string_view mode, const fs::path& dir) {
    if (mode == "image-reference") return RunReference();
    if (mode == "image-dilation") return RunDilation(dir);
    if (mode == "image-resample") return RunResample(dir);
    if (mode == "image-mips") return RunMips(dir);
    if (mode == "image-repeat") return RunRepeat(dir);
    return -1;
}
