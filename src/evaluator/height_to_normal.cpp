#include "evaluator/height_to_normal.h"

#include <cstring>
#include <string>
#include <utility>
#include <variant>

#include "evaluator/arith.h"
#include "evaluator/dag.h"
#include "evaluator/error.h"
#include "evaluator/hash.h"
#include "evaluator/hwmath.h"

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
                                        core::NormalMapFormat convention) {
    const Vec3 heightNormal = arith::NormalNormalise(v);
    Vec3 mesh{0.0f, 0.0f, 1.0f};
    if (inputs.hasMesh) {
        mesh = arith::NormalDecode(inputs.mesh);
        if (inputs.meshDirectX) mesh[1] = -mesh[1];
    }
    const Vec3 base = arith::NormalNormalise(arith::NormalReoriented(mesh, heightNormal));
    const Vec3 detail = ChannelNormal(inputs.channel, inputs.coverage);
    const Vec3 n = arith::NormalNormalise(arith::NormalReoriented(base, detail));
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
    if (const auto binding = set->mesh_maps.find(core::MeshMapUsage::Normal); binding != set->mesh_maps.end()) {
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

    EvalEnvironment env{store, cache, request.resources.get(), request.geometry.get()};
    const TileGrid grid{width, height};
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
    const bool heightTiles = !heights.empty() && heights[0].kind == Operand::Kind::Tile;
    HashWriter readoutKey;
    readoutKey.Str("virtual-normal").Sub(heightDag ? heightDag->readoutHash : Digest{}).F32(heightConstant);
    readoutKey.Sub(normalDag ? normalDag->readoutHash : Digest{});
    readoutKey.U32(static_cast<uint32_t>(set->height_to_normal_method)).U32(static_cast<uint32_t>(request.convention));
    HashWriter meshKey;
    meshKey.Str("normal-mesh-map").Str(meshImage ? set->mesh_maps.at(core::MeshMapUsage::Normal).resource : std::string());
    const Digest meshDigest = meshKey.Finish();
    readoutKey.Sub(meshDigest).U32(meshDirectX ? 1u : 0u).F32(HeightZ(set->height_to_normal_method, width));
    const Digest key = readoutKey.Finish();
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
            render::Result<void> queued = store.VirtualNormal(op);
            if (!queued) return render::Unexpected(queued.error());
            render::Result<void> read = ReadInto(store, *dst, tx * kTileSize, ty * kTileSize, result);
            if (!read) return render::Unexpected(read.error());
        }
    }
    return result;
}

render::Result<bool> FlatZeroHeight(const core::Project& project, core::Id textureSet, core::Id stack,
                                    const TemplateLibrary& templates, std::string_view templateId) {
    const core::TextureSet* set = FindSet(project, textureSet);
    if (set == nullptr) {
        return EvalFail(EvalErrorKind::NotFound,
                        "texture set " + std::to_string(textureSet) + " is not in the project");
    }
    const core::Stack* found = FindStack(*set, stack);
    if (found == nullptr) {
        return EvalFail(EvalErrorKind::NotFound, "stack " + std::to_string(stack) + " is not in the texture set");
    }
    if (!found->channels.contains(core::ChannelType::Height)) return true;
    render::Result<ChannelDag> dag =
        BuildDag(project, textureSet, stack, core::ChannelType::Height, templates, templateId);
    if (!dag) return render::Unexpected(dag.error());
    return dag->root.layers.empty() && dag->base == Vec3{0.0f, 0.0f, 0.0f};
}

}  // namespace uzp::evaluator
