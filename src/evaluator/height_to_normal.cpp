#include "evaluator/height_to_normal.h"

#include <algorithm>
#include <bit>
#include <cstddef>
#include <cstring>
#include <string>
#include <string_view>
#include <utility>
#include <variant>

#include "evaluator/arith.h"
#include "evaluator/dag.h"
#include "evaluator/error.h"
#include "evaluator/hash.h"
#include "evaluator/hwmath.h"
#include "evaluator/result_cache.h"

namespace uzp::evaluator {

namespace {

using core::HeightToNormalMethod;
using Vec3 = std::array<float, 3>;

// Single IEEE float32 operations (the sources are compiled with contraction off, arith.h).
float Add(float a, float b) { return a + b; }
float Sub(float a, float b) { return a - b; }
float Mul(float a, float b) { return a * b; }

/// (a + 2 b) + c: one (1, 2, 1) row or column of the Sobel stencil.
float Smooth(float a, float b, float c) { return Add(Add(a, Mul(2.0f, b)), c); }

/// The unit normal u turned toward (0, 0, 1) by the coverage a (see the header): t = a acos(z),
/// (u.x k, u.y k, cos(t)), k = sin(t) rsqrt(fma(-z, z, 1)), z = u.z clamped to [0, 1].
Vec3 TowardFlatAcos(const Vec3& u, float a) {
    if (!(a < 1.0f)) return u;
    const float z = arith::Clamp01(u[2]);
    const float w = arith::Fma(-z, z, 1.0f);
    if (!(w > 0.0f)) return u;
    const float turned = Mul(a, hw::Acos(z));
    const float k = Mul(hw::Sin(turned), hw::Rsqrt(w));
    return {Mul(u[0], k), Mul(u[1], k), hw::Cos(turned)};
}

/// The channel normal C of the Normal channel's colour `x` at coverage `a` (see the header): the
/// full coverage decodes `x` as it is.
Vec3 ChannelNormal(const Vec3& x, float a) {
    if (!(a > 0.0f)) return {0.0f, 0.0f, 1.0f};
    if (!(a < 1.0f)) return arith::NormalDecode(x);
    const float inverse = hw::Rcp(a);
    return TowardFlatAcos(arith::NormalDecode({Mul(x[0], inverse), Mul(x[1], inverse), Mul(x[2], inverse)}), a);
}

/// The set widths whose height-to-normal scaling is recorded (decision 079).
bool RecordedResolution(uint32_t width) { return width == 256 || width == 512 || width == 1024 || width == 2048; }

const core::TextureSet* FindSet(const core::Project& project, core::Id set) {
    for (const core::TextureSet& candidate : project.texture_sets) {
        if (candidate.id == set) return &candidate;
    }
    return nullptr;
}

const core::Stack* FindStack(const core::TextureSet& set, core::Id stack) {
    for (const core::Stack& candidate : set.stacks) {
        if (candidate.id == stack) return &candidate;
    }
    return nullptr;
}

/// Unpins every tile it holds when it goes out of scope.
class Pins {
public:
    explicit Pins(TileCache& cache) : m_cache(cache) {}
    ~Pins() {
        for (const TileHandle tile : m_tiles) m_cache.Unpin(tile);
    }
    Pins(const Pins&) = delete;
    Pins& operator=(const Pins&) = delete;
    void Hold(const Operand& operand) {
        if (operand.kind == Operand::Kind::Tile) m_tiles.push_back(operand.tile);
    }

private:
    TileCache& m_cache;
    std::vector<TileHandle> m_tiles;
};

void Accumulate(EvaluationStats& total, const EvaluationStats& part) {
    total.cacheHits += part.cacheHits;
    total.cacheMisses += part.cacheMisses;
    total.blends += part.blends;
    total.levels += part.levels;
    total.uploads += part.uploads;
    total.evictions += part.evictions;
    total.flushes += part.flushes;
}

/// Reads a 32-bit float tile of three channels into `out` at its place in the set.
render::Result<void> ReadInto(ITileStore& store, TileHandle tile, uint32_t x0, uint32_t y0,
                              VirtualNormalResult& out) {
    render::Result<TileImage> image = store.Read(tile);
    if (!image) return render::Unexpected(image.error());
    for (uint32_t y = 0; y < image->height; ++y) {
        for (uint32_t x = 0; x < image->width; ++x) {
            for (uint32_t c = 0; c < 3; ++c) {
                float value = 0.0f;
                std::memcpy(&value, image->texels.data() + ((size_t{y} * image->width + x) * 3 + c) * sizeof(float),
                            sizeof(float));
                out.texels[((size_t{y0 + y} * out.width) + x0 + x) * 3 + c] = value;
            }
        }
    }
    return {};
}

/// The convention of a bound Normal mesh map: an imported map's declared one, else the project's.
core::NormalMapFormat MeshConvention(const core::Project& project, const core::MeshMapBinding& map) {
    return map.provenance_kind() == core::MeshMapProvenanceKind::imported
               ? std::get<core::ImportedProvenance>(map.provenance).declared_convention
               : project.settings.normal_map_format;
}

/// The bound Normal mesh map's bytes, or `missing_resource`.
render::Result<std::shared_ptr<const DecodedImage>> MeshImage(const core::MeshMapBinding& map,
                                                              const VirtualNormalRequest& request) {
    if (request.resources == nullptr) {
        return EvalFail(EvalErrorKind::MissingResource, "no resource provider for the Normal mesh map");
    }
    std::shared_ptr<const DecodedImage> image = request.resources->Fetch(map.resource);
    if (!image) {
        return EvalFail(EvalErrorKind::MissingResource, "Normal mesh map " + map.resource + " is not available");
    }
    return image;
}

/// The geometry-only pass-through: the bound Normal mesh map's codes as their operands, green
/// inverted when the requested convention differs from the map's.
render::Result<VirtualNormalResult> PassThrough(const core::Project& project, const core::TextureSet& set,
                                                const VirtualNormalRequest& request) {
    const auto binding = set.mesh_maps.find(core::MeshMapUsage::Normal);
    if (binding == set.mesh_maps.end()) {
        return EvalFail(EvalErrorKind::MissingResource,
                        "texture set " + std::to_string(set.id) + " has no Normal mesh map to pass through");
    }
    render::Result<std::shared_ptr<const DecodedImage>> fetched = MeshImage(binding->second, request);
    if (!fetched) return render::Unexpected(fetched.error());
    const std::shared_ptr<const DecodedImage>& image = *fetched;
    const bool unorm = image->encoding == render::TexelEncoding::Unorm16 ||
                       image->encoding == render::TexelEncoding::Unorm8;
    if (!unorm || image->channels < 3 || image->width != static_cast<uint32_t>(set.resolution.width) ||
        image->height != static_cast<uint32_t>(set.resolution.height)) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        "the Normal mesh map must be an 8- or 16-bit RGB image at the set resolution "
                        "(a pass-through does not resample)");
    }
    const core::NormalMapFormat own = MeshConvention(project, binding->second);
    const uint32_t bits = image->encoding == render::TexelEncoding::Unorm16 ? 16u : 8u;
    const uint32_t max = (1u << bits) - 1u;
    VirtualNormalResult result;
    result.kind = NormalSourceKind::GeometryOnly;
    result.convention = request.convention;
    result.width = image->width;
    result.height = image->height;
    result.texels.resize(size_t{image->width} * image->height * 3);
    for (uint32_t y = 0; y < image->height; ++y) {
        for (uint32_t x = 0; x < image->width; ++x) {
            for (uint32_t c = 0; c < 3; ++c) {
                uint32_t code = image->At(x, y, c) & max;
                if (c == 1 && own != request.convention) code = max - code;
                result.texels[(size_t{y} * image->width + x) * 3 + c] = arith::UnormOperand(code, bits);
            }
        }
    }
    result.tag.role = core::MeshMapRole::geometry_only;
    return result;
}

/// What the virtual normal reads of the Height or Normal channel `dag` (null: no such channel).
/// Its read-out hash is zero unless its root list is isolated with layers, so the profile, the
/// isolation, whether the list is empty and the base it reads as are written beside it: a
/// profile whose root list is not isolated fails, an empty Height stack reads as its base, and
/// neither may share a key with another channel's result (decision 253).
void WriteChannelInputs(HashWriter& writer, const ChannelDag* dag) {
    if (dag == nullptr) {
        writer.U32(0);
        return;
    }
    writer.U32(1).Sub(dag->readoutHash).Str(dag->profile.id).U32(dag->root.isolated ? 1u : 0u);
    writer.U64(dag->root.layers.size());
    for (const float component : dag->base) writer.F32(component);
}

}  // namespace

float HeightZ(HeightToNormalMethod method, uint32_t width) {
    const float scale = 256.0f / static_cast<float>(width);
    return Mul(method == HeightToNormalMethod::Sharp ? kSharpZ : kSobelZ, scale);
}

std::array<float, 3> HeightVector(HeightToNormalMethod method, const HeightNeighbourhood& h, float z) {
    // h[(dy + 1) 3 + dx + 1]
    if (method == HeightToNormalMethod::Sharp) {
        return {Sub(h[3], h[4]), Sub(h[4], h[1]), z};
    }
    const float left = Smooth(h[0], h[3], h[6]);
    const float right = Smooth(h[2], h[5], h[8]);
    const float top = Smooth(h[0], h[1], h[2]);
    const float bottom = Smooth(h[6], h[7], h[8]);
    return {Sub(left, right), Sub(bottom, top), z};
}

std::array<float, 3> VirtualNormalTexel(const std::array<float, 3>& v, const NormalInputs& inputs,
                                        core::NormalMapFormat convention, VirtualNormalComponent component) {
    const Vec3 heightNormal = arith::NormalNormalise(v);
    if (component == VirtualNormalComponent::Height) return heightNormal;
    const Vec3 detail = ChannelNormal(inputs.channel, inputs.coverage);
    if (component == VirtualNormalComponent::Channel) return detail;
    Vec3 mesh{0.0f, 0.0f, 1.0f};
    if (inputs.hasMesh) {
        mesh = arith::NormalDecode(inputs.mesh);
        if (inputs.meshDirectX) mesh[1] = -mesh[1];
    }
    const Vec3 base = arith::NormalNormalise(arith::NormalReoriented(mesh, heightNormal));
    const Vec3 n = arith::NormalNormalise(arith::NormalReoriented(base, detail));
    const float y = convention == core::NormalMapFormat::DirectX ? -n[1] : n[1];
    return {arith::Fma(n[0], 0.5f, 0.5f), arith::Fma(y, 0.5f, 0.5f), arith::Fma(n[2], 0.5f, 0.5f)};
}

std::array<float, 3> MeshOnPaddedNormal(const std::array<float, 3>& mesh, bool meshDirectX,
                                        const std::array<float, 3>& heightNormal,
                                        const std::array<float, 3>& channelNormal, core::NormalMapFormat convention) {
    Vec3 f = arith::NormalDecode(mesh);
    if (meshDirectX) f[1] = -f[1];
    const Vec3 base = arith::NormalNormalise(arith::NormalReoriented(f, heightNormal));
    const Vec3 n = arith::NormalNormalise(arith::NormalReoriented(base, channelNormal));
    const float y = convention == core::NormalMapFormat::DirectX ? -n[1] : n[1];
    return {arith::Fma(n[0], 0.5f, 0.5f), arith::Fma(y, 0.5f, 0.5f), arith::Fma(n[2], 0.5f, 0.5f)};
}

render::Result<VirtualNormalResult> EvaluateVirtualNormalOn(const core::Project& project, std::int64_t revision,
                                                            const VirtualNormalRequest& request,
                                                            const TemplateLibrary& templates, ITileStore& store,
                                                            TileCache& cache) {
    const core::TextureSet* set = FindSet(project, request.textureSet);
    if (set == nullptr) {
        return EvalFail(EvalErrorKind::NotFound,
                        "texture set " + std::to_string(request.textureSet) + " is not in the project");
    }
    const core::Stack* stack = FindStack(*set, request.stack);
    if (stack == nullptr) {
        return EvalFail(EvalErrorKind::NotFound, "stack " + std::to_string(request.stack) + " is not in the texture set");
    }
    render::Result<void> admitted = CheckTextureSet(cache.limits(), *set);
    if (!admitted) return render::Unexpected(admitted.error());
    if (request.kind == NormalSourceKind::GeometryOnly) return PassThrough(project, *set, request);

    const uint32_t width = static_cast<uint32_t>(set->resolution.width);
    const uint32_t height = static_cast<uint32_t>(set->resolution.height);
    if (width != height || !RecordedResolution(width)) {
        return EvalFail(EvalErrorKind::UnsupportedSource,
                        "the height-to-normal scaling is recorded on square sets of 256, 512, 1024 and 2048 "
                        "texels only (phase1.12_compositor-height-normal)");
    }
    // The bound Normal mesh map: F of the combination, recorded as a 16-bit RGB image at the set
    // resolution.
    std::shared_ptr<const DecodedImage> meshImage;
    bool meshDirectX = false;
    if (const auto binding = set->mesh_maps.find(core::MeshMapUsage::Normal);
        binding != set->mesh_maps.end() && !request.withoutMesh) {
        render::Result<std::shared_ptr<const DecodedImage>> fetched = MeshImage(binding->second, request);
        if (!fetched) return render::Unexpected(fetched.error());
        meshImage = *fetched;
        if (meshImage->encoding != render::TexelEncoding::Unorm16 || meshImage->channels < 3 ||
            meshImage->width != width || meshImage->height != height) {
            return EvalFail(EvalErrorKind::UnsupportedSource,
                            "a Normal mesh map in the virtual normal maps is recorded as a 16-bit RGB "
                            "image at the set resolution only (phase1.12_compositor-height-normal)");
        }
        const core::NormalMapFormat own = MeshConvention(project, binding->second);
        if (own != project.settings.normal_map_format) {
            return EvalFail(EvalErrorKind::UnsupportedSource,
                            "a Normal mesh map in a convention other than the project's is not recorded in "
                            "the virtual normal maps (phase1.12_compositor-height-normal)");
        }
        meshDirectX = own == core::NormalMapFormat::DirectX;
    }
    const bool hasHeight = stack->channels.contains(core::ChannelType::Height);
    const bool hasNormal = stack->channels.contains(core::ChannelType::Normal);
    std::optional<ChannelDag> heightDag;
    std::optional<ChannelDag> normalDag;
    if (hasHeight) {
        render::Result<ChannelDag> dag = BuildDag(project, set->id, stack->id, core::ChannelType::Height,
                                                  templates, request.templateId);
        if (!dag) return render::Unexpected(dag.error());
        heightDag = std::move(*dag);
    }
    if (hasNormal) {
        render::Result<ChannelDag> dag = BuildDag(project, set->id, stack->id, core::ChannelType::Normal,
                                                  templates, request.templateId);
        if (!dag) return render::Unexpected(dag.error());
        normalDag = std::move(*dag);
    }
    // A stack without a Height channel has no relief: a flat height.
    constexpr float heightConstant = 0.0f;

    VirtualNormalResult result;
    result.kind = NormalSourceKind::Combined;
    result.convention = request.convention;
    result.width = width;
    result.height = height;
    result.texels.resize(size_t{result.width} * result.height * 3);
    result.tag.role = core::MeshMapRole::combined;
    result.tag.relief = ReliefRound{revision, heightDag ? Hex(heightDag->readoutHash) : std::string(),
                                    set->height_to_normal_method};

    HashWriter readoutKey;
    readoutKey.Str("virtual-normal");
    if (request.component != VirtualNormalComponent::Combined) {
        readoutKey.Str("raw-normal-component").U32(static_cast<uint32_t>(request.component));
    }
    WriteChannelInputs(readoutKey, heightDag ? &*heightDag : nullptr);
    readoutKey.F32(heightConstant);
    WriteChannelInputs(readoutKey, normalDag ? &*normalDag : nullptr);
    readoutKey.U32(static_cast<uint32_t>(set->height_to_normal_method)).U32(static_cast<uint32_t>(request.convention));
    HashWriter meshKey;
    meshKey.Str("normal-mesh-map").Str(meshImage ? set->mesh_maps.at(core::MeshMapUsage::Normal).resource : std::string());
    const Digest meshDigest = meshKey.Finish();
    readoutKey.Sub(meshDigest).U32(meshDirectX ? 1u : 0u).F32(HeightZ(set->height_to_normal_method, width));
    Digest key = readoutKey.Finish();
    const TileGrid grid{width, height};
    // Held by this tile cache: read there (result_cache.h). A padded Height is never persisted.
    render::DiskCache* persistent = request.heightPadding || request.component != VirtualNormalComponent::Combined
                                        ? nullptr : cache.persistent();
    if (persistent != nullptr && cache.Contains(CacheKey{stack->id, CacheKind::Readout, key, 0, 0})) persistent = nullptr;
    if (persistent != nullptr) {
        const ChannelDag* dags[] = {heightDag ? &*heightDag : nullptr, normalDag ? &*normalDag : nullptr};
        if (std::optional<std::vector<float>> stored = LoadVirtualNormal(*persistent, key, width, height, dags,
                                                                         request.resources.get(),
                                                                         request.geometry.get())) {
            result.texels = std::move(*stored);
            result.stats.tiles = grid.Count();
            result.stats.cacheHits = grid.Count();
            result.stats.persistentHits = grid.Count();
            return result;
        }
    }

    EvalEnvironment env{store, cache, request.resources.get(), request.geometry.get()};
    Pins pins(cache);
    // Every tile's height read-out first: the stencils read across tile edges.
    std::vector<Operand> heights(grid.Count(), Operand::Constant({heightConstant, heightConstant, heightConstant}, 1.0f));
    if (heightDag) {
        for (uint32_t ty = 0; ty < grid.TilesY(); ++ty) {
            for (uint32_t tx = 0; tx < grid.TilesX(); ++tx) {
                EvaluationStats stats;
                render::Result<Operand> readout = EvaluateFloat32Readout(*heightDag, env, tx, ty, heightDag->base, stats);
                if (!readout) return render::Unexpected(readout.error());
                pins.Hold(*readout);
                Accumulate(result.stats, stats);
                heights[size_t{ty} * grid.TilesX() + tx] = *readout;
            }
        }
    }
    if (request.heightPadding) {
        // The diagnostic measure export (decision 308): the whole set's read-out, padded, in tiles
        // keyed by the padded content, and the result keyed by it too.
        std::vector<float> whole(size_t{width} * height);
        for (uint32_t ty = 0; ty < grid.TilesY(); ++ty) {
            for (uint32_t tx = 0; tx < grid.TilesX(); ++tx) {
                const Operand& tile = heights[size_t{ty} * grid.TilesX() + tx];
                const uint32_t x0 = tx * kTileSize;
                const uint32_t y0 = ty * kTileSize;
                if (tile.kind != Operand::Kind::Tile) {
                    for (uint32_t y = 0; y < grid.TileHeight(ty); ++y) {
                        std::fill_n(whole.begin() + static_cast<std::ptrdiff_t>(size_t{y0 + y} * width + x0),
                                    grid.TileWidth(tx), tile.value[0]);
                    }
                    continue;
                }
                render::Result<TileImage> image = store.Read(tile.tile);
                if (!image) return render::Unexpected(image.error());
                if (image->format.encoding != render::TexelEncoding::Float32 || image->format.channels != 1) {
                    return EvalFail(EvalErrorKind::Internal, "the Height read-out is a grey 32-bit float tile");
                }
                for (uint32_t y = 0; y < image->height; ++y) {
                    std::memcpy(&whole[size_t{y0 + y} * width + x0],
                                image->texels.data() + size_t{y} * image->width * sizeof(float),
                                size_t{image->width} * sizeof(float));
                }
            }
        }
        request.heightPadding(whole);
        if (whole.size() != size_t{width} * height) {
            return EvalFail(EvalErrorKind::Internal, "the Height padding changed the set's size");
        }
        HashWriter padded;
        padded.Str("padded-height").Sub(key).Bytes(
            std::string_view(reinterpret_cast<const char*>(whole.data()), whole.size() * sizeof(float)));
        key = padded.Finish();
        DecodedImage image;
        image.width = width;
        image.height = height;
        image.channels = 1;
        image.encoding = render::TexelEncoding::Float32;
        image.values.reserve(whole.size());
        for (const float value : whole) image.values.push_back(std::bit_cast<uint32_t>(value));
        TileFormat format;
        format.encoding = render::TexelEncoding::Float32;
        format.channels = 1;
        for (uint32_t ty = 0; ty < grid.TilesY(); ++ty) {
            for (uint32_t tx = 0; tx < grid.TilesX(); ++tx) {
                const CacheKey heightKey{stack->id, CacheKind::Content, key, tx, ty};
                std::optional<TileHandle> tile = cache.Lookup(heightKey);
                if (!tile) {
                    render::Result<TileHandle> allocated =
                        cache.Allocate(heightKey, format, grid.TileWidth(tx), grid.TileHeight(ty), store);
                    if (!allocated) return render::Unexpected(allocated.error());
                    render::Result<void> uploaded = store.Upload(*allocated, image, tx * kTileSize, ty * kTileSize);
                    if (!uploaded) {
                        cache.Unpin(*allocated);
                        return render::Unexpected(uploaded.error());
                    }
                    tile = *allocated;
                }
                pins.Hold(Operand::Of(*tile));
                heights[size_t{ty} * grid.TilesX() + tx] = Operand::Of(*tile);
            }
        }
    }
    const bool heightTiles = !heights.empty() && heights[0].kind == Operand::Kind::Tile;
    for (uint32_t ty = 0; ty < grid.TilesY(); ++ty) {
        for (uint32_t tx = 0; tx < grid.TilesX(); ++tx) {
            ++result.stats.tiles;
            const CacheKey tileKey{stack->id, CacheKind::Readout, key, tx, ty};
            if (const std::optional<TileHandle> cached = cache.Lookup(tileKey)) {
                pins.Hold(Operand::Of(*cached));
                ++result.stats.cacheHits;
                render::Result<void> read = ReadInto(store, *cached, tx * kTileSize, ty * kTileSize, result);
                if (!read) return render::Unexpected(read.error());
                continue;
            }
            ++result.stats.cacheMisses;
            TileFormat format;
            format.encoding = render::TexelEncoding::Float32;
            format.channels = 3;
            render::Result<TileHandle> dst =
                cache.Allocate(tileKey, format, grid.TileWidth(tx), grid.TileHeight(ty), store);
            if (!dst) return render::Unexpected(dst.error());
            pins.Hold(Operand::Of(*dst));
            Operand normal = Operand::Constant(kFlatNormalColour, 1.0f);
            if (normalDag && !normalDag->root.layers.empty()) {
                EvaluationStats stats;
                render::Result<Operand> list = EvaluateIsolatedRoot(*normalDag, env, tx, ty, stats);
                if (!list) return render::Unexpected(list.error());
                pins.Hold(*list);
                Accumulate(result.stats, stats);
                normal = *list;
            }
            Operand mesh = Operand::Constant(kFlatNormalColour, 1.0f);
            if (meshImage) {
                // The mesh map's window as UNORM operands, cached by its content hash.
                const CacheKey meshKey{stack->id, CacheKind::Content, meshDigest, tx, ty};
                std::optional<TileHandle> tile = cache.Lookup(meshKey);
                if (!tile) {
                    TileFormat meshFormat;
                    meshFormat.encoding = render::TexelEncoding::Float32;
                    meshFormat.channels = 3;
                    render::Result<TileHandle> allocated =
                        cache.Allocate(meshKey, meshFormat, grid.TileWidth(tx), grid.TileHeight(ty), store);
                    if (!allocated) return render::Unexpected(allocated.error());
                    render::Result<void> uploaded = store.Upload(*allocated, *meshImage, tx * kTileSize, ty * kTileSize);
                    if (!uploaded) {
                        cache.Unpin(*allocated);
                        return render::Unexpected(uploaded.error());
                    }
                    tile = *allocated;
                }
                pins.Hold(Operand::Of(*tile));
                mesh = Operand::Of(*tile);
            }
            VirtualNormalOp op;
            op.dst = *dst;
            op.heightConstant = heights[size_t{ty} * grid.TilesX() + tx].value[0];
            if (heightTiles) {
                for (int dy = -1; dy <= 1; ++dy) {
                    for (int dx = -1; dx <= 1; ++dx) {
                        const uint32_t nx = (tx + grid.TilesX() + static_cast<uint32_t>(dx + 1) - 1) % grid.TilesX();
                        const uint32_t ny = (ty + grid.TilesY() + static_cast<uint32_t>(dy + 1) - 1) % grid.TilesY();
                        op.height[static_cast<size_t>((dy + 1) * 3 + dx + 1)] = heights[size_t{ny} * grid.TilesX() + nx].tile;
                    }
                }
            }
            op.z = HeightZ(set->height_to_normal_method, width);
            op.normal = normal;
            op.mesh = mesh;
            op.meshDirectX = meshDirectX;
            op.method = set->height_to_normal_method;
            op.convention = request.convention;
            op.component = request.component;
            render::Result<void> queued = store.VirtualNormal(op);
            if (!queued) return render::Unexpected(queued.error());
            render::Result<void> read = ReadInto(store, *dst, tx * kTileSize, ty * kTileSize, result);
            if (!read) return render::Unexpected(read.error());
        }
    }
    if (persistent != nullptr) StoreVirtualNormal(*persistent, key, result);
    return result;
}

}  // namespace uzp::evaluator
