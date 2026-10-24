#include "procedural/snapshot_backend.h"

#include "store/snapshots.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"

#include <algorithm>
#include <bit>

namespace uzp::procedural {

namespace json = core::json;

namespace {

/// `std::unexpected<std::string>`, named through `std::expected` (seam.h `Refused`).
using Failure = std::expected<void, std::string>::unexpected_type;

size_t SampleBytes(ChannelFormat format) {
    switch (format) {
        case ChannelFormat::U8: return 1;
        case ChannelFormat::U16:
        case ChannelFormat::F16: return 2;
        case ChannelFormat::F32: return 4;
    }
    return 0;
}

size_t RasterBytes(const RasterSpec& spec) {
    return size_t{spec.resolution} * spec.resolution * spec.channels * SampleBytes(spec.format);
}

/// IEEE 754 half to float, exactly (every half is a float).
float HalfToFloat(uint16_t half) {
    const uint32_t sign = uint32_t{half & 0x8000u} << 16;
    const uint32_t exponent = (half >> 10) & 0x1Fu;
    uint32_t mantissa = half & 0x3FFu;
    uint32_t bits = 0;
    if (exponent == 0x1F) {
        bits = sign | 0x7F800000u | (mantissa << 13);  // inf, NaN (payload kept)
    } else if (exponent != 0) {
        bits = sign | ((exponent + 112) << 23) | (mantissa << 13);
    } else if (mantissa != 0) {  // subnormal: normalise
        uint32_t e = 113;
        while ((mantissa & 0x400u) == 0) {
            mantissa <<= 1;
            --e;
        }
        bits = sign | (e << 23) | ((mantissa & 0x3FFu) << 13);
    } else {
        bits = sign;  // signed zero
    }
    return std::bit_cast<float>(bits);
}

float Sample(const std::string& bytes, size_t index, ChannelFormat format) {
    const auto* p = reinterpret_cast<const unsigned char*>(bytes.data()) + index * SampleBytes(format);
    switch (format) {
        case ChannelFormat::U8: return static_cast<float>(p[0]) / 255.0f;
        case ChannelFormat::U16: return static_cast<float>(uint32_t{p[0]} | uint32_t{p[1]} << 8) / 65535.0f;
        case ChannelFormat::F16: return HalfToFloat(static_cast<uint16_t>(p[0] | p[1] << 8));
        case ChannelFormat::F32:
            return std::bit_cast<float>(uint32_t{p[0]} | uint32_t{p[1]} << 8 | uint32_t{p[2]} << 16 |
                                        uint32_t{p[3]} << 24);
    }
    return 0.0f;
}

std::optional<ChannelFormat> ParseFormat(std::string_view name) {
    for (const ChannelFormat f : {ChannelFormat::U8, ChannelFormat::U16, ChannelFormat::F16, ChannelFormat::F32}) {
        if (FormatName(f) == name) return f;
    }
    return std::nullopt;
}

const json::Value* MemberOf(const json::Value& value, std::string_view name) {
    const auto* object = std::get_if<json::Object>(&value.data);
    if (object == nullptr) return nullptr;
    const auto it = object->find(name);
    return it == object->end() ? nullptr : &it->second;
}

/// The output spec a stored signature names, or why it names none.
std::expected<RasterSpec, std::string> OutputOf(const json::Value& signature) {
    const json::Value* output = MemberOf(signature, "output");
    const json::Value* resolution = output ? MemberOf(*output, "resolution") : nullptr;
    const json::Value* format = output ? MemberOf(*output, "format") : nullptr;
    const json::Value* space = output ? MemberOf(*output, "colour_space") : nullptr;
    const json::Value* channels = output ? MemberOf(*output, "channels") : nullptr;
    if (!resolution || !resolution->IsInt() || !format || !format->IsString() || !space || !space->IsString() ||
        !channels || !channels->IsInt()) {
        return Failure(std::string("the signature names no output resolution, format, colour space and channels"));
    }
    const std::optional<ChannelFormat> parsed = ParseFormat(std::get<std::string>(format->data));
    const int64_t r = std::get<int64_t>(resolution->data);
    const int64_t c = std::get<int64_t>(channels->data);
    if (!parsed || r < 1 || r > store::kMaxPlaneEdge || c < 1 || c > 4) {
        return Failure(std::string("the signature's output is not a raster spec"));
    }
    return RasterSpec{static_cast<uint32_t>(r), *parsed, std::get<std::string>(space->data), static_cast<uint32_t>(c)};
}

/// The leaf paths where two signatures differ, in key order (`params.amount`, `output.resolution`).
void Differences(const json::Value& a, const json::Value& b, const std::string& path, std::vector<std::string>& out) {
    const auto* x = std::get_if<json::Object>(&a.data);
    const auto* y = std::get_if<json::Object>(&b.data);
    if (x == nullptr || y == nullptr) {
        if (!(a == b)) out.push_back(path);
        return;
    }
    std::vector<std::string> keys;
    for (const auto& [key, value] : *x) keys.push_back(key);
    for (const auto& [key, value] : *y) {
        if (!x->contains(key)) keys.push_back(key);
    }
    std::sort(keys.begin(), keys.end());
    for (const std::string& key : keys) {
        const auto i = x->find(key);
        const auto j = y->find(key);
        const std::string child = path.empty() ? key : path + "." + key;
        if (i == x->end() || j == y->end()) {
            out.push_back(child);
        } else {
            Differences(i->second, j->second, child, out);
        }
    }
}

/// Why `request`'s tile cannot be cut from its output, or empty.
std::optional<UnsupportedProcedural> TileRefusal(const ProceduralRequest& request) {
    const TileRect& t = request.tile;
    const bool whole = t.x == 0 && t.y == 0 && t.width == 0 && t.height == 0;
    if (whole) return std::nullopt;
    if (t.width != 0 && t.height != 0 && uint64_t{t.x} + t.width <= request.output.resolution &&
        uint64_t{t.y} + t.height <= request.output.resolution) {
        return std::nullopt;
    }
    UnsupportedProcedural refusal = Refuse(AssetName(request), kNoSnapshot);
    refusal.field = "tile";
    refusal.value = "[" + std::to_string(t.x) + ", " + std::to_string(t.y) + ", " + std::to_string(t.width) + ", " +
                    std::to_string(t.height) + "]";
    refusal.certified = "a non-empty rectangle inside the " + std::to_string(request.output.resolution) + " texel output";
    return refusal;
}

}  // namespace

std::optional<core::ChannelFormat> SnapshotPlaneFormat(const RasterSpec& spec) {
    using core::ChannelFormat;
    if (spec.channels != 1 && spec.channels != 3) return std::nullopt;
    const bool grey = spec.channels == 1;
    switch (spec.format) {
        case procedural::ChannelFormat::U8: return grey ? ChannelFormat::L8 : ChannelFormat::RGB8;
        case procedural::ChannelFormat::U16: return grey ? ChannelFormat::L16 : ChannelFormat::RGB16;
        case procedural::ChannelFormat::F16: return grey ? ChannelFormat::L16F : ChannelFormat::RGB16F;
        case procedural::ChannelFormat::F32: return grey ? ChannelFormat::L32F : ChannelFormat::RGB32F;
    }
    return std::nullopt;
}

std::expected<SnapshotBackend, std::string> SnapshotBackend::Load(store::ProjectStore& store,
                                                                 const core::Project& project) {
    SnapshotBackend backend;
    for (const store::SnapshotEntry& entry : store::ProjectSnapshots(project)) {
        const std::string problem = store::SnapshotProblem(entry, store.project_uuid());
        if (!problem.empty()) return Failure(entry.path + ": " + problem);
        const std::expected<RasterSpec, std::string> spec = OutputOf(entry.signature);
        if (!spec) return Failure(entry.path + ": " + spec.error());
        store::PlaneImage image;
        try {
            image = store.ReadPlane(project, entry.plane_id);
        } catch (const std::exception& error) {
            return Failure(entry.path + ": " + error.what());
        }
        const std::optional<core::ChannelFormat> format = SnapshotPlaneFormat(*spec);
        if (!format || image.format != *format || image.width != static_cast<int>(spec->resolution) ||
            image.height != static_cast<int>(spec->resolution) || image.texels.size() != RasterBytes(*spec)) {
            return Failure(entry.path + ": plane " + std::to_string(entry.plane_id) + " (" +
                                   std::to_string(image.width) + "x" + std::to_string(image.height) + " " +
                                   std::string(core::ToString(image.format)) +
                                   ") is not the raster the signature's output names");
        }
        backend.m_snapshots[entry.key] =
            Entry{entry.signature, SnapshotRaster{*spec, std::move(image.texels)}, entry.image_outputs};
    }
    return backend;
}

void SnapshotBackend::Add(const ProceduralRequest& request, SnapshotRaster raster,
                          std::optional<std::vector<std::string>> imageOutputs) {
    m_snapshots[SignatureHash(request)] = Entry{SignatureJson(request), std::move(raster), std::move(imageOutputs)};
}

ParityStatus SnapshotBackend::Status(const core::AssetUrl&) const {
    return ParityStatus::Unavailable(std::string(kSnapshotStatus));
}

bool SnapshotBackend::CanEvaluate(const ProceduralRequest& request) const {
    return !TileRefusal(request) && m_snapshots.contains(SignatureHash(request));
}

std::optional<UnsupportedProcedural> SnapshotBackend::Refusal(const ProceduralRequest& request) const {
    if (auto tile = TileRefusal(request)) return tile;
    if (m_snapshots.contains(SignatureHash(request))) return std::nullopt;
    UnsupportedProcedural refusal = Refuse(AssetName(request), kNoSnapshot);
    const json::Value wanted = SignatureJson(request);
    const json::Value* asset = MemberOf(wanted, "asset");
    std::vector<std::string> closest;
    for (const auto& [key, entry] : m_snapshots) {
        const json::Value* stored = MemberOf(entry.signature, "asset");
        if (stored == nullptr || !(*stored == *asset)) continue;
        std::vector<std::string> differences;
        Differences(wanted, entry.signature, "", differences);
        if (closest.empty() || differences.size() < closest.size()) closest = std::move(differences);
    }
    if (!closest.empty()) {
        refusal.field = closest.front();
        refusal.certified = std::to_string(closest.size()) + " field(s) differ from the closest stored signature";
    }
    return refusal;
}

std::expected<const SnapshotRaster*, UnsupportedProcedural> SnapshotBackend::Stored(
    const ProceduralRequest& request) const {
    const auto found = m_snapshots.find(SignatureHash(request));
    if (found == m_snapshots.end()) return Refused(*Refusal(request));
    return &found->second.raster;
}

std::expected<std::vector<std::string>, UnsupportedProcedural> SnapshotBackend::ImageOutputs(
    const ProceduralRequest& request) const {
    const auto found = m_snapshots.find(SignatureHash(request));
    if (found == m_snapshots.end()) return Refused(*Refusal(request));
    if (!found->second.imageOutputs) return Refused(Refuse(AssetName(request), kNoImageOutputs));
    return *found->second.imageOutputs;
}

RasterFuture SnapshotBackend::Evaluate(const ProceduralRequest& request, const InputImages&) {
    std::promise<render::Result<Raster>> promise;
    const std::optional<UnsupportedProcedural> refusal = Refusal(request);
    if (refusal) {
        promise.set_value(render::Fail(render::ErrorCode::RequestFailed, std::nullopt, refusal->Describe()));
        return promise.get_future();
    }
    const SnapshotRaster& stored = m_snapshots.at(SignatureHash(request)).raster;
    const uint32_t size = stored.spec.resolution;
    const TileRect& t = request.tile;
    const bool whole = t.width == 0 && t.height == 0;
    const uint32_t x0 = whole ? 0 : t.x;
    const uint32_t y0 = whole ? 0 : t.y;
    Raster out{whole ? size : t.width, whole ? size : t.height, stored.spec.channels, {}};
    out.texels.reserve(size_t{out.width} * out.height * out.channels);
    for (uint32_t y = y0; y < y0 + out.height; ++y) {
        for (uint32_t x = x0; x < x0 + out.width; ++x) {
            for (uint32_t c = 0; c < out.channels; ++c) {
                out.texels.push_back(Sample(stored.bytes, (size_t{y} * size + x) * out.channels + c, stored.spec.format));
            }
        }
    }
    promise.set_value(std::move(out));
    return promise.get_future();
}

core::Id RecordSnapshot(store::ProjectStore& store, core::Edit& edit, const ProceduralRequest& request,
                        std::string bytes, const std::optional<std::vector<std::string>>& imageOutputs) {
    const std::string asset = AssetName(request);
    if (request.tile.x != 0 || request.tile.y != 0 || request.tile.width != 0 || request.tile.height != 0) {
        throw core::ValueError("snapshot of " + asset + ": a snapshot is a whole texture; the request names a tile");
    }
    const std::optional<core::ChannelFormat> format = SnapshotPlaneFormat(request.output);
    if (!format) {
        throw core::ValueError("snapshot of " + asset + ": an output of " + std::to_string(request.output.channels) +
                               " channels has no plane format (1 or 3 channels are stored)");
    }
    if (request.output.resolution < 1 || request.output.resolution > store::kMaxPlaneEdge) {
        throw core::ValueError("snapshot of " + asset + ": resolution " + std::to_string(request.output.resolution) +
                               " is outside 1.." + std::to_string(store::kMaxPlaneEdge));
    }
    if (bytes.size() != RasterBytes(request.output)) {
        throw core::ValueError("snapshot of " + asset + ": " + std::to_string(bytes.size()) + " bytes, the output holds " +
                               std::to_string(RasterBytes(request.output)));
    }
    const int edge = static_cast<int>(request.output.resolution);
    return store.RecordSnapshot(edit, SignatureJson(request), store::PlaneImage{edge, edge, *format, std::move(bytes)},
                                imageOutputs);
}

}  // namespace uzp::procedural
