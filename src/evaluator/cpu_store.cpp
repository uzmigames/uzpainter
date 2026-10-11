#include "evaluator/cpu_store.h"

#include <bit>
#include <cstring>

#include "evaluator/arith.h"
#include "evaluator/error.h"

namespace uzp::evaluator {

namespace {

using render::TexelEncoding;

bool IsCoverage(const TileFormat& format, uint32_t plane) { return format.alpha && plane == 3; }

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
    for (uint32_t y = 0; y < tile.height; ++y) {
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
    if (!arith::HasSeparableKernel(op.mode)) {
        return EvalFail(EvalErrorKind::UnsupportedBlendMode,
                        std::string(core::ToString(op.mode)) +
                            " has no kernel in this build (phase1.10_compositor-blend-kernels)");
    }
    const uint32_t stored = dst.format.StoredChannels();
    arith::CompositeInput in;
    in.mode = op.mode;
    in.opacity = op.opacity;
    in.clampUnorm = dst.format.IsUnorm();
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
    for (size_t texel = 0; texel < texels; ++texel) {
        if (acc != nullptr) load(*acc, texel, in.acc);
        else in.acc = op.acc.value;
        if (src != nullptr) load(*src, texel, in.src);
        else in.src = op.source.value;
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
