#include "evaluator/cpu_store.h"

#include <algorithm>
#include <bit>
#include <cstring>
#include <exception>
#include <thread>
#include <vector>

#include <immintrin.h>

#include "evaluator/arith.h"
#include "evaluator/error.h"
#include "evaluator/height_to_normal.h"
#include "evaluator/projection_uv.h"

namespace uzp::evaluator {

namespace {

using render::TexelEncoding;

bool IsCoverage(const TileFormat& format, uint32_t plane) { return format.alpha && plane == 3; }

/// Runs `body(first, last)` over [0, count) split into contiguous ranges, one per hardware thread,
/// the calling thread taking the first (B19, decision 246). Every element is computed by the same
/// code from the same inputs and written by exactly one thread, so the result is the
/// single-threaded one bit for bit; each worker first takes the caller's MXCSR (rounding,
/// flush-to-zero, denormals-are-zero), the state the arithmetic runs under. An exception is
/// rethrown once every range has ended: the one of the first range that threw, which holds the
/// first element whose computation throws, as the single-threaded loop would have thrown it.
template <typename Body>
void ForEachRange(size_t count, const Body& body) {
    const size_t ranges = std::clamp<size_t>(std::thread::hardware_concurrency(), 1, std::max<size_t>(count, 1));
    if (ranges == 1) {
        body(size_t{0}, count);
        return;
    }
    const size_t step = (count + ranges - 1) / ranges;
    const unsigned int control = _mm_getcsr();
    std::vector<std::exception_ptr> failures(ranges);
    const auto run = [&](size_t range) {
        try {
            body(range * step, std::min(count, (range + 1) * step));
        } catch (...) {
            failures[range] = std::current_exception();
        }
    };
    std::vector<std::thread> workers;
    workers.reserve(ranges - 1);
    for (size_t range = 1; range < ranges && range * step < count; ++range) {
        try {
            workers.emplace_back([&run, control, range] {
                _mm_setcsr(control);
                run(range);
            });
        } catch (...) {
            run(range);  // no thread to start: this one computes the range
        }
    }
    run(0);
    for (std::thread& worker : workers) worker.join();
    for (const std::exception_ptr& failure : failures) {
        if (failure) std::rethrow_exception(failure);
    }
}

}  // namespace

float OperandOf(uint32_t stored, const TileFormat& format, uint32_t plane) {
    switch (format.encoding) {
        case TexelEncoding::Unorm8:
            if (format.srgb && !IsCoverage(format, plane)) return arith::Srgb8Operand(stored);
            return arith::Unorm8OperandTable()[stored & 0xFF];
        case TexelEncoding::Unorm16: return arith::Unorm16OperandTable()[stored & 0xFFFF];
        case TexelEncoding::Float16:
        case TexelEncoding::Float32: return std::bit_cast<float>(stored);
    }
    return 0.0f;
}

uint32_t StoreValue(float value, const TileFormat& format, uint32_t plane) {
    if (format.halfCoverage && IsCoverage(format, plane) && (!format.halfCoverageFromHalf || value >= 0.5f)) {
        value = arith::HalfToFloat(arith::HalfNearestEven(value));
    }
    switch (format.encoding) {
        case TexelEncoding::Unorm8:
            if (format.srgb && !IsCoverage(format, plane)) return arith::Srgb8Store(value);
            return arith::WriteUnorm(value, 8);
        case TexelEncoding::Unorm16: return arith::WriteUnorm(value, 16);
        case TexelEncoding::Float16:
            return std::bit_cast<uint32_t>(arith::HalfToFloat(arith::HalfTowardZero(value)));
        case TexelEncoding::Float32: return std::bit_cast<uint32_t>(arith::Float32Store(value));
    }
    return 0;
}

const CpuTileStore::Tile* CpuTileStore::Find(TileHandle tile) const {
    const auto it = m_tiles.find(tile);
    return it == m_tiles.end() ? nullptr : &it->second;
}

render::Result<TileHandle> CpuTileStore::Allocate(const TileFormat& format, uint32_t width,
                                                  uint32_t height) {
    if (width == 0 || height == 0 || width > kTileSize || height > kTileSize) {
        return EvalFail(EvalErrorKind::Internal,
                        "a tile is 1 to " + std::to_string(kTileSize) + " texels on each axis");
    }
    Tile tile;
    tile.format = format;
    tile.width = width;
    tile.height = height;
    tile.values.assign(size_t{width} * height * format.StoredChannels(), 0);
    const TileHandle handle = m_next++;
    m_bytes += TileBytes(format, width, height);
    m_tiles.emplace(handle, std::move(tile));
    return handle;
}

void CpuTileStore::Release(TileHandle tile) {
    const auto it = m_tiles.find(tile);
    if (it == m_tiles.end()) return;
    m_bytes -= TileBytes(it->second.format, it->second.width, it->second.height);
    m_tiles.erase(it);
}

render::Result<void> CpuTileStore::Upload(TileHandle handle, const DecodedImage& image,
                                          uint32_t x0, uint32_t y0) {
    const auto it = m_tiles.find(handle);
    if (it == m_tiles.end()) return EvalFail(EvalErrorKind::Internal, "upload into an unknown tile");
    Tile& tile = it->second;
    if (x0 + tile.width > image.width || y0 + tile.height > image.height) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        "the bitmap (" + std::to_string(image.width) + "x" +
                            std::to_string(image.height) + ") does not cover the tile window");
    }
    if (image.channels < tile.format.channels) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        "a bitmap with " + std::to_string(image.channels) +
                            " channels cannot fill a " + std::to_string(tile.format.channels) +
                            "-channel tile");
    }
    const bool sameDepth = image.encoding == tile.format.encoding;
    const bool codesToFloat32 = image.encoding == TexelEncoding::Unorm16 &&
                                tile.format.encoding == TexelEncoding::Float32;
    if (!sameDepth && !codesToFloat32) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        "bitmap conversion into this channel format is not part of this profile "
                        "(phase1.8_compositor-sources-projection)");
    }
    const uint32_t stored = tile.format.StoredChannels();
    ForEachRange(tile.height, [&](size_t first, size_t last) {
        for (auto y = static_cast<uint32_t>(first); y < last; ++y) {
            for (uint32_t x = 0; x < tile.width; ++x) {
                uint32_t* out = &tile.values[(size_t{y} * tile.width + x) * stored];
                for (uint32_t c = 0; c < tile.format.channels; ++c) {
                    const uint32_t sample = image.At(x0 + x, y0 + y, c);
                    out[c] = codesToFloat32
                                 ? std::bit_cast<uint32_t>(arith::UnormOperand(sample & 0xFFFF, 16))
                                 : sample;
                }
                if (stored == 4) {
                    for (uint32_t c = tile.format.channels; c < 3; ++c) out[c] = 0;
                    out[3] = StoreValue(1.0f, tile.format, 3);
                }
            }
        }
    });
    return {};
}

render::Result<void> CpuTileStore::Project(const ProjectOp& op) {
    const auto it = m_tiles.find(op.dst);
    if (it == m_tiles.end() || !op.image) {
        return EvalFail(EvalErrorKind::Internal, "projection into an unknown tile or of no bitmap");
    }
    Tile& tile = it->second;
    if (op.projection.MayUncover() && !tile.format.alpha) {
        return EvalFail(EvalErrorKind::Internal, "a projection that may uncover texels needs a coverage plane");
    }
    const DecodedImage& image = *op.image;
    const uint32_t stored = tile.format.StoredChannels();
    const tu::Chain* chain = nullptr;
    if (Minifies(op.projection, op.setWidth, op.setHeight, image)) {
        std::shared_ptr<const tu::Chain>& made =
            m_chains[op.imageKey + (image.encoding == render::TexelEncoding::Unorm16 ? "/16" : "/8")];
        if (!made) made = std::make_shared<const tu::Chain>(BitmapChain(image));
        chain = made.get();
    }
    ForEachRange(tile.height, [&](size_t first, size_t last) {
        for (auto y = static_cast<uint32_t>(first); y < last; ++y) {
            for (uint32_t x = 0; x < tile.width; ++x) {
                const ProjectedTexel texel = ProjectTexel(op.projection, image, op.x0 + x, op.y0 + y,
                                                          op.setWidth, op.setHeight, op.signedRange, chain);
                uint32_t* out = &tile.values[(size_t{y} * tile.width + x) * stored];
                for (uint32_t c = 0; c < tile.format.channels; ++c) {
                    out[c] = StoreValue(texel.covered ? texel.value[c] : 0.0f, tile.format, c);
                }
                if (stored == 4) {
                    for (uint32_t c = tile.format.channels; c < 3; ++c) out[c] = 0;
                    out[3] = StoreValue(texel.covered ? 1.0f : 0.0f, tile.format, 3);
                }
            }
        }
    });
    return {};
}

render::Result<void> CpuTileStore::Blend(const BlendOp& op) {
    const auto dstIt = m_tiles.find(op.dst);
    if (dstIt == m_tiles.end()) return EvalFail(EvalErrorKind::Internal, "blend into an unknown tile");
    Tile& dst = dstIt->second;
    const Tile* acc = op.acc.kind == Operand::Kind::Tile ? Find(op.acc.tile) : nullptr;
    const Tile* src = op.source.kind == Operand::Kind::Tile ? Find(op.source.tile) : nullptr;
    const Tile* mask = op.mask.kind == Operand::Kind::Tile ? Find(op.mask.tile) : nullptr;
    for (const Tile* input : {acc, src, mask}) {
        if (input != nullptr && (input->width != dst.width || input->height != dst.height)) {
            return EvalFail(EvalErrorKind::Internal, "blend operands differ in size");
        }
    }
    if ((op.acc.kind == Operand::Kind::Tile && acc == nullptr) ||
        (op.source.kind == Operand::Kind::Tile && src == nullptr) ||
        (op.mask.kind == Operand::Kind::Tile && mask == nullptr)) {
        return EvalFail(EvalErrorKind::Internal, "blend operand tile unknown");
    }
    if (!arith::HasComposite(op.mode)) {
        return EvalFail(EvalErrorKind::UnsupportedBlendMode,
                        std::string(core::ToString(op.mode)) +
                            " has no blend kernel (a group placement)");
    }
    if (op.rawOutput && (dst.format.encoding != TexelEncoding::Float32 || dst.format.alpha ||
                         (src != nullptr && src->format.channels != dst.format.channels))) {
        return EvalFail(EvalErrorKind::Internal,
                        "a raw blend writes a 32-bit float tile of the source's channel count");
    }
    const uint32_t stored = dst.format.StoredChannels();
    arith::CompositeInput in;
    in.mode = op.mode;
    in.opacity = op.opacity;
    // A raw blend clamps as the source's format would (the channel's own read-out does).
    in.clampUnorm = op.rawOutput && src != nullptr ? src->format.IsUnorm() : dst.format.IsUnorm();
    in.effectMix = op.effectMix;
    in.coverageWeights = op.coverageWeights;
    in.emptyBackdrop = op.emptyBackdrop;
    in.fusedReadout = op.fusedReadout;
    in.channels = dst.format.channels;
    auto load = [](const Tile& tile, size_t texel, std::array<float, 4>& out) {
        const uint32_t planes = tile.format.StoredChannels();
        const uint32_t* values = &tile.values[texel * planes];
        for (uint32_t c = 0; c < tile.format.channels; ++c) {
            out[c] = OperandOf(values[c], tile.format, c);
        }
        for (uint32_t c = tile.format.channels; c < 3; ++c) out[c] = 0.0f;
        out[3] = tile.format.alpha ? OperandOf(values[3], tile.format, 3) : 1.0f;
    };
    const size_t texels = size_t{dst.width} * dst.height;
    ForEachRange(texels, [&, operands = in](size_t first, size_t last) {
        arith::CompositeInput in = operands;  // each range its own operands
        for (size_t texel = first; texel < last; ++texel) {
            if (acc != nullptr) load(*acc, texel, in.acc);
            else in.acc = op.acc.value;
            if (src != nullptr) load(*src, texel, in.src);
            else in.src = op.source.value;
            if (op.sourceHalfTowardZero) {
                for (int c = 0; c < in.channels; ++c) {
                    const size_t i = static_cast<size_t>(c);
                    in.src[i] = arith::HalfToFloat(arith::HalfTowardZero(in.src[i]));
                }
            }
            if (mask != nullptr) {
                const uint32_t* values = &mask->values[texel * mask->format.StoredChannels()];
                in.mask = OperandOf(values[0], mask->format, 0);
            } else {
                in.mask = op.mask.value[0];
            }
            const std::array<float, 4> out = arith::Composite(in);
            uint32_t* values = &dst.values[texel * stored];
            for (uint32_t c = 0; c < dst.format.channels; ++c) {
                values[c] = StoreValue(out[c], dst.format, c);
            }
            if (stored == 4) {
                for (uint32_t c = dst.format.channels; c < 3; ++c) values[c] = 0;
                values[3] = dst.format.alpha ? StoreValue(out[3], dst.format, 3)
                                             : StoreValue(1.0f, dst.format, 3);
            }
        }
    });
    return {};
}

render::Result<void> CpuTileStore::Levels(const LevelsOp& op) {
    const auto dstIt = m_tiles.find(op.dst);
    const Tile* src = Find(op.src);
    if (dstIt == m_tiles.end() || src == nullptr) {
        return EvalFail(EvalErrorKind::Internal, "levels into or from an unknown tile");
    }
    Tile& dst = dstIt->second;
    if (src->width != dst.width || src->height != dst.height || !(src->format == dst.format)) {
        return EvalFail(EvalErrorKind::Internal, "levels operands differ in size or format");
    }
    const uint32_t stored = dst.format.StoredChannels();
    const size_t texels = size_t{dst.width} * dst.height;
    ForEachRange(texels, [&](size_t first, size_t last) {
        for (size_t texel = first; texel < last; ++texel) {
            const uint32_t* in = &src->values[texel * stored];
            uint32_t* out = &dst.values[texel * stored];
            for (uint32_t c = 0; c < stored; ++c) {
                if (c < dst.format.channels) {
                    const float v = OperandOf(in[c], dst.format, c);
                    out[c] = StoreValue(arith::Levels(v, op.components[c]), dst.format, c);
                } else {
                    out[c] = in[c];
                }
            }
        }
    });
    return {};
}

render::Result<void> CpuTileStore::VirtualNormal(const VirtualNormalOp& op) {
    const auto dstIt = m_tiles.find(op.dst);
    if (dstIt == m_tiles.end()) return EvalFail(EvalErrorKind::Internal, "virtual normal into an unknown tile");
    Tile& dst = dstIt->second;
    if (dst.format.encoding != TexelEncoding::Float32 || dst.format.channels != 3 || dst.format.alpha) {
        return EvalFail(EvalErrorKind::Internal, "a virtual normal tile is a three-channel 32-bit float tile");
    }
    std::array<const Tile*, 9> heights{};
    const bool heightTiles = op.height[4] != kNoTile;
    for (size_t i = 0; i < heights.size(); ++i) {
        if (!heightTiles) continue;
        heights[i] = Find(op.height[i]);
        if (heights[i] == nullptr || heights[i]->width != dst.width || heights[i]->height != dst.height ||
            heights[i]->format.encoding != TexelEncoding::Float32 || heights[i]->format.channels != 1) {
            return EvalFail(EvalErrorKind::Internal, "virtual normal height tiles: grey 32-bit float of the tile's size");
        }
    }
    const Tile* normal = op.normal.kind == Operand::Kind::Tile ? Find(op.normal.tile) : nullptr;
    if (op.normal.kind == Operand::Kind::Tile &&
        (normal == nullptr || normal->width != dst.width || normal->height != dst.height ||
         normal->format.channels != 3 || !normal->format.alpha || normal->format.srgb)) {
        return EvalFail(EvalErrorKind::Internal,
                        "virtual normal channel tile: a colour tile with coverage of the tile's size");
    }
    const Tile* mesh = op.mesh.kind == Operand::Kind::Tile ? Find(op.mesh.tile) : nullptr;
    if (op.mesh.kind == Operand::Kind::Tile &&
        (mesh == nullptr || mesh->width != dst.width || mesh->height != dst.height ||
         mesh->format.encoding != TexelEncoding::Float32 || mesh->format.channels != 3)) {
        return EvalFail(EvalErrorKind::Internal, "virtual normal mesh tile: three-channel 32-bit float of the tile's size");
    }
    const int width = static_cast<int>(dst.width);
    const int height = static_cast<int>(dst.height);
    // The height at (x + dx, y + dy), read from the neighbouring tile across a tile edge.
    auto at = [&](int x, int y) -> float {
        if (!heightTiles) return op.heightConstant;
        const int ox = x < 0 ? -1 : (x >= width ? 1 : 0);
        const int oy = y < 0 ? -1 : (y >= height ? 1 : 0);
        const Tile& tile = *heights[static_cast<size_t>((oy + 1) * 3 + ox + 1)];
        const int lx = x - ox * width;
        const int ly = y - oy * height;
        return std::bit_cast<float>(tile.values[static_cast<size_t>(ly) * dst.width + static_cast<size_t>(lx)]);
    };
    const uint32_t stored = dst.format.StoredChannels();
    ForEachRange(static_cast<size_t>(height), [&](size_t first, size_t last) {
        for (auto y = static_cast<int>(first); y < static_cast<int>(last); ++y) {
            for (int x = 0; x < width; ++x) {
                HeightNeighbourhood h{};
                for (int dy = -1; dy <= 1; ++dy) {
                    for (int dx = -1; dx <= 1; ++dx) h[static_cast<size_t>((dy + 1) * 3 + dx + 1)] = at(x + dx, y + dy);
                }
                const size_t texel = static_cast<size_t>(y) * dst.width + static_cast<size_t>(x);
                NormalInputs inputs;
                inputs.channel = {op.normal.value[0], op.normal.value[1], op.normal.value[2]};
                inputs.coverage = op.normal.value[3];
                if (normal != nullptr) {
                    const uint32_t* values = &normal->values[texel * normal->format.StoredChannels()];
                    for (uint32_t c = 0; c < 3; ++c) inputs.channel[c] = OperandOf(values[c], normal->format, c);
                    inputs.coverage = OperandOf(values[3], normal->format, 3);
                }
                inputs.hasMesh = mesh != nullptr;
                inputs.meshDirectX = op.meshDirectX;
                if (mesh != nullptr) {
                    const uint32_t* values = &mesh->values[texel * mesh->format.StoredChannels()];
                    for (uint32_t c = 0; c < 3; ++c) inputs.mesh[c] = std::bit_cast<float>(values[c]);
                }
                const std::array<float, 3> e =
                    VirtualNormalTexel(HeightVector(op.method, h, op.z), inputs, op.convention, op.component);
                uint32_t* out = &dst.values[texel * stored];
                for (uint32_t c = 0; c < 3; ++c) out[c] = std::bit_cast<uint32_t>(arith::Float32Store(e[c]));
                out[3] = std::bit_cast<uint32_t>(1.0f);
            }
        }
    });
    return {};
}

render::Result<TileImage> CpuTileStore::Read(TileHandle handle) {
    const Tile* tile = Find(handle);
    if (tile == nullptr) return EvalFail(EvalErrorKind::Internal, "read of an unknown tile");
    TileImage image;
    image.format = tile->format;
    image.width = tile->width;
    image.height = tile->height;
    const uint32_t stored = tile->format.StoredChannels();
    const uint32_t bytesPerChannel = tile->format.BytesPerChannel();
    image.texels.resize(size_t{tile->width} * tile->height * tile->format.channels * bytesPerChannel);
    std::byte* out = image.texels.data();
    for (size_t texel = 0; texel < size_t{tile->width} * tile->height; ++texel) {
        const uint32_t* values = &tile->values[texel * stored];
        for (uint32_t c = 0; c < tile->format.channels; ++c) {
            uint32_t bits = values[c];
            if (tile->format.encoding == TexelEncoding::Float16) {
                bits = arith::HalfTowardZero(std::bit_cast<float>(bits));
            }
            std::memcpy(out, &bits, bytesPerChannel);
            out += bytesPerChannel;
        }
    }
    return image;
}

}  // namespace uzp::evaluator
