// Native tests of the document model and the canonical manifest (`src/uzp_core/`, task
// phase1.1_docmodel-types-manifest). Built by `zig build uzp-core-tests` and driven by
// tests/uzp_core/test_document_model.py.
//
// Usage:
//   uzp-core-tests run [case]          run every native case (or one); exit 0 when all pass
//   uzp-core-tests fixture [reversed]  print the canonical manifest of the fixture project, built
//                                      with its maps filled in forward or reversed order
//   uzp-core-tests canonical <file>    load and validate a manifest, print its canonical form
//   uzp-core-tests digest <file>       load and validate a manifest, print its SHA-256 digest
//   uzp-core-tests json <file>         print the canonical form of any JSON text
// Errors print "<ErrorClass>: <message>" on stderr and exit 3 (ValueError, ManifestError,
// ParseError).

#include <algorithm>
#include <cstdio>
#include <fstream>
#include <functional>
#include <map>
#include <set>
#include <sstream>
#include <string>
#include <vector>

#include "uzp_core/manifest/json.h"
#include "uzp_core/manifest/manifest.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"
#include "uzp_core/types/project.h"
#include "uzp_core/types/receipt.h"
#include "uzp_core/types/resource_url.h"
#include "uzp_core/types/validation.h"

namespace {

using namespace uzp::core;

static_assert(NodeTypeOf(LayerKind::instance) == NodeType::InstanceLayer);
static_assert(NodeTypeOf(EffectKind::fill) == NodeType::FillEffect);
static_assert(NodeTypeOf(EffectKind::anchor) == NodeType::AnchorPointEffect);
static_assert(EffectKindOf(NodeType::CompareMaskEffect) == EffectKind::compare_mask);
static_assert(EnumTable<NodeType>::names.size() == 12);
static_assert(EnumTable<BlendingMode>::names.size() == 32);
static_assert(EnumTable<ChannelFormat>::names.size() == 9);

struct Failure {
    std::string message;
};

#define CHECK(cond)                                                                           \
    do {                                                                                      \
        if (!(cond)) throw Failure{std::string(__FILE__ ":") + std::to_string(__LINE__) + ": " #cond}; \
    } while (false)

template <typename E, typename F>
std::string ExpectThrow(F&& body, const char* what) {
    try {
        body();
    } catch (const E& error) {
        return error.what();
    }
    throw Failure{std::string("expected an exception: ") + what};
}

#define EXPECT_THROW(E, expr) ExpectThrow<E>([&] { expr; }, #expr)

std::string Hash(std::string_view bytes) { return Sha256Hex(bytes); }

// ── The fixture project: every node, effect and source kind, both mesh-map provenances ────────

Blending Blend(BlendingMode mode, double opacity) { return Blending{mode, opacity, {}}; }

Effect MakeEffect(Id uid, EffectKind kind, std::string name) {
    Effect effect;
    effect.uid = uid;
    effect.kind = kind;
    effect.name = std::move(name);
    return effect;
}

Layer MakeLayer(Id uid, LayerKind kind, std::string name) {
    Layer layer;
    layer.uid = uid;
    layer.kind = kind;
    layer.name = std::move(name);
    return layer;
}

ReferenceSource Ref(Id anchor) {
    ReferenceSource reference;
    reference.anchor = anchor;
    return reference;
}

ProceduralRef Procedural(std::string asset) {
    ProceduralRef ref;
    ref.asset = std::move(asset);
    return ref;
}

ResourceMeta Meta(Id id, std::string name, std::string mime, std::int64_t size, std::string usage) {
    ResourceMeta meta;
    meta.id = id;
    meta.name = std::move(name);
    meta.mime = std::move(mime);
    meta.size = size;
    meta.usage = std::move(usage);
    meta.origin = "import";
    meta.imported_at = "2026-10-10T00:00:00Z";
    meta.color_space = "sRGB";
    return meta;
}

/// Ids of the fixture are fixed so tests can address its nodes.
namespace fx {
constexpr Id kSet = 1, kStack = 2, kTile = 3;
constexpr Id kBase = 10, kPipingA = 11, kPipingB = 12, kPaint = 13, kGroup = 14, kChild = 15, kInstance = 16;
constexpr Id kFillFx = 20, kPaintFx = 21, kGenerator = 22, kFilter = 23, kLevels = 24, kAnchor = 25;
constexpr Id kMaskFill = 30, kCompare = 31, kColorSel = 32, kMaskLevels = 33, kMaskPaint = 34, kMaskGen = 35;
constexpr Id kResBitmap = 40, kResBitmapAlias = 41, kResVector = 42, kResFont = 43, kResMesh = 44;
constexpr Id kResAo = 45, kResNormal = 46, kResEnv = 47, kNext = 100;
}  // namespace fx

Project BuildFixture(bool reversed) {
    const std::string bitmap = Hash("bitmap bytes"), vector = Hash("svg bytes"), font = Hash("font bytes");
    const std::string mesh = Hash("mesh bytes"), ao = Hash("ao bytes"), normal = Hash("normal bytes");
    const std::string env = Hash("hdri bytes");

    Project p;
    p.versions.app_version = "0.0.0";
    p.versions.evaluator_profile = "painter-12.1-layerq-linear";
    p.versions.painter_reference = {"12.1.0", "tier0", {}};
    p.next_id = fx::kNext;
    p.settings.normal_map_format = NormalMapFormat::OpenGL;
    p.settings.tangent_space = TangentSpace::PerFragment;
    p.settings.default_resolution = {2048, 2048, {}};
    p.settings.mesh_unit_scale = 0.01;
    p.settings.color_management = {"legacy", "", "sRGB", json::Array{}, {}};
    p.mesh = MeshReference{mesh, json::Object{{"triangles", 128}}, {}};

    // Maps filled forward or reversed: the canonical manifest must not depend on it.
    std::vector<std::function<void()>> fills = {
        [&] { p.resources[bitmap] = {Meta(fx::kResBitmap, "M_piping", "image/png", 10, "TEXTURE"),
                                     Meta(fx::kResBitmapAlias, "Source_v10_M_piping", "image/png", 10, "TEXTURE")}; },
        [&] { p.resources[vector] = {Meta(fx::kResVector, "logo.svg", "image/svg+xml", 20, "TEXTURE")}; },
        [&] { p.resources[font] = {Meta(fx::kResFont, "font.ttf", "font/ttf", 30, "TEXTURE")}; },
        [&] { p.resources[mesh] = {Meta(fx::kResMesh, "tunic.fbx", "model/fbx", 40, "MESH")}; },
        [&] { p.resources[ao] = {Meta(fx::kResAo, "ao.png", "image/png", 50, "TEXTURE")}; },
        [&] { p.resources[normal] = {Meta(fx::kResNormal, "normal.png", "image/png", 60, "TEXTURE")}; },
        [&] { p.resources[env] = {Meta(fx::kResEnv, "studio.hdr", "image/vnd.radiance", 70, "ENVIRONMENT")}; },
        [&] { p.metadata["pipeline"] = json::Object{{"stage", "painting"}, {"version", 10}}; },
        [&] { p.metadata["assets3d"] = json::Object{{"asset", "tunic"}}; },
    };
    if (reversed) std::reverse(fills.begin(), fills.end());
    for (const auto& fill : fills) fill();

    p.display.environment = {env, 90.0, 0.5, 1.0, 0.0, {}};
    p.display.tone_mapping = ToneMapping::ACES;
    p.display.shader = {"pbr-metal-rough", Hash("shader"), json::Object{{"emissive_intensity", 1.0}}, {}};
    p.export_defaults = json::Object{{"padding", "infinite"}, {"bit_depth", 16}};

    TextureSet set;
    set.id = fx::kSet;
    set.name = "M_tunic";
    set.original_name = "M_tunic";
    set.material_id = "material-0";
    set.resolution = {2048, 2048, {}};
    set.uv_tiles = {UVTile{fx::kTile, 1001, {}}};
    MeshMapBinding ao_map;
    ao_map.resource = ao;
    ao_map.format = ChannelFormat::L16;
    ao_map.color_space = "Raw";
    BakedProvenance baked;
    baked.baker_version = "uzp-bake-1";
    baked.backend = BakerBackend::embree;
    baked.settings_hash = Hash("settings");
    baked.high_meshes = {Hash("high")};
    baked.mesh_hashes = {Hash("positions"), Hash("uvs"), Hash("normals"), Hash("triangles"), {}};
    baked.effective_normalization = json::Object{{"curvature_bounds", json::Array{-1.0, 1.0}}};
    ao_map.provenance = baked;
    MeshMapBinding normal_map;
    normal_map.resource = normal;
    normal_map.format = ChannelFormat::RGB16;
    normal_map.color_space = "Raw";
    normal_map.provenance = ImportedProvenance{"A3D/tunic/normal.png", normal, MeshMapRole::geometry_only,
                                               NormalMapFormat::OpenGL, "cm", {}};
    normal_map.invalid = true;
    normal_map.invalid_report = json::Object{{"changed_triangles", 12}};
    if (reversed) {
        set.mesh_maps[MeshMapUsage::Normal] = normal_map;
        set.mesh_maps[MeshMapUsage::AO] = ao_map;
    } else {
        set.mesh_maps[MeshMapUsage::AO] = ao_map;
        set.mesh_maps[MeshMapUsage::Normal] = normal_map;
    }
    set.bake_settings.common = json::Object{{"output_size", 2048}};
    set.bake_settings.per_baker["AO"] = json::Object{{"secondary_rays", 64}};

    Stack stack;
    stack.id = fx::kStack;
    const std::vector<std::pair<ChannelType, ChannelFormat>> channels = {
        {ChannelType::BaseColor, ChannelFormat::sRGB8}, {ChannelType::Roughness, ChannelFormat::L8},
        {ChannelType::Metallic, ChannelFormat::L8},     {ChannelType::Normal, ChannelFormat::RGB16F},
        {ChannelType::Height, ChannelFormat::L16F},     {ChannelType::User0, ChannelFormat::L32F},
    };
    for (std::size_t i = 0; i < channels.size(); ++i) {
        const auto& [type, format] = channels[reversed ? channels.size() - 1 - i : i];
        stack.channels[type] = Channel{format, type == ChannelType::User0 ? "dirt" : "", {}};
    }

    const auto uniform = [](double r, double g, double b) {
        return Source{UniformColorSource{{r, g, b}, "sRGB", {}}};
    };
    ProceduralRef grunge;
    grunge.asset = "uzasset://generator/position@1.0.0";
    grunge.params = json::Object{{"axis", "y"}, {"contrast", 0.25}};
    grunge.preset = "default";
    grunge.image_inputs["mask"] = ResourceBinding{bitmap, std::nullopt, {}};
    grunge.output_mapping["Roughness"] = "output";
    grunge.resolution_override = Resolution{512, 512, {}};

    // Base fill: uniform, bitmap (with alias), vector, font and procedural sources.
    Layer base;
    base.uid = fx::kBase;
    base.kind = LayerKind::fill;
    base.name = "Base";
    base.blending[ChannelType::BaseColor] = Blend(BlendingMode::Normal, 1.0);
    base.blending[ChannelType::Height] = Blend(BlendingMode::LinearDodge, 0.5);
    FillContent fill;
    fill.sources[ChannelType::BaseColor] = uniform(0.8, 0.2, 0.1);
    fill.sources[ChannelType::Height] = Source{BitmapSource{{bitmap, "Source_v10_M_piping", {}}, "Raw", {}}};
    fill.sources[ChannelType::User0] = Source{VectorSource{{vector, std::nullopt, {}}, json::Object{{"fill", "even-odd"}}, {}}};
    fill.sources[ChannelType::Metallic] = Source{FontSource{{font, std::nullopt, {}}, json::Object{{"text", "UZ"}}, {}}};
    fill.sources[ChannelType::Roughness] = Source{ProceduralSource{grunge}};
    fill.active_channels = {ChannelType::BaseColor, ChannelType::Height, ChannelType::Roughness,
                            ChannelType::Metallic, ChannelType::User0};
    fill.projection.mode = ProjectionMode::Triplanar;
    fill.projection.params = json::Object{{"hardness", 0.5}};
    fill.symmetry = {true, json::Object{{"axis", "x"}}, {}};
    base.fill = fill;
    base.geometry_mask = {GeometryMaskType::Mesh, true, {"body", "sleeves"}, {}};

    // Content effects of every kind except the mask-only ones, then a mask with every kind.
    Effect fill_fx = MakeEffect(fx::kFillFx, EffectKind::fill, "Tint");
    fill_fx.blending[ChannelType::BaseColor] = Blend(BlendingMode::Multiply, 0.3);
    fill_fx.fill = FillContent{};
    fill_fx.fill->sources[ChannelType::BaseColor] = uniform(0.5, 0.5, 0.5);
    fill_fx.fill->active_channels = {ChannelType::BaseColor};
    Effect paint_fx = MakeEffect(fx::kPaintFx, EffectKind::paint, "Touch-up");
    paint_fx.paint = PaintContent{{{ChannelType::BaseColor, 1001}, {ChannelType::Roughness, 1002}}, std::nullopt, {}};
    Effect generator = MakeEffect(fx::kGenerator, EffectKind::generator, "Position");
    generator.active_channels = {ChannelType::Roughness};
    generator.procedural = grunge;
    Effect filter = MakeEffect(fx::kFilter, EffectKind::filter, "Blur");
    filter.active_channels = {ChannelType::BaseColor};
    filter.procedural = Procedural("uzasset://filter/blur@2.1.0");
    filter.procedural->params = json::Object{{"radius", 3}};
    Effect levels = MakeEffect(fx::kLevels, EffectKind::levels, "Levels");
    levels.levels = LevelsParams{ChannelType::BaseColor, {LevelsComponent{}, LevelsComponent{}, LevelsComponent{}}, {}};
    Effect anchor = MakeEffect(fx::kAnchor, EffectKind::anchor, "Base anchor");
    anchor.anchor_name = "Base anchor";
    base.content_effects = {fill_fx, paint_fx, generator, filter, levels, anchor};

    Mask mask;
    mask.background = MaskBackground::Black;
    mask.blending = Blend(BlendingMode::Normal, 1.0);
    Effect mask_fill = MakeEffect(fx::kMaskFill, EffectKind::fill, "Mask fill");
    mask_fill.mono_blending = Blend(BlendingMode::Normal, 1.0);
    mask_fill.fill = FillContent{};
    mask_fill.fill->mono_source = uniform(1.0, 1.0, 1.0);
    Effect compare = MakeEffect(fx::kCompare, EffectKind::compare_mask, "Compare");
    compare.mono_blending = Blend(BlendingMode::Multiply, 1.0);
    compare.compare_mask = json::Object{{"operation", "greater"}, {"threshold", 0.5}};
    Effect color_sel = MakeEffect(fx::kColorSel, EffectKind::color_selection, "ID pick");
    color_sel.mono_blending = Blend(BlendingMode::Lighten, 1.0);
    color_sel.color_selection = json::Object{{"colors", json::Array{json::Array{1.0, 0.0, 0.0}}}, {"tolerance", 0.1}};
    Effect mask_levels = MakeEffect(fx::kMaskLevels, EffectKind::levels, "Mask levels");
    mask_levels.mono_blending = Blend(BlendingMode::Normal, 1.0);
    LevelsComponent curve;
    curve.gamma = 2.2;
    curve.clamp = true;
    mask_levels.levels = LevelsParams{std::nullopt, {curve}, {}};
    Effect mask_paint = MakeEffect(fx::kMaskPaint, EffectKind::paint, "Mask paint");
    mask_paint.mono_blending = Blend(BlendingMode::Normal, 1.0);
    mask_paint.paint = PaintContent{{}, 1003, {}};
    Effect mask_gen = MakeEffect(fx::kMaskGen, EffectKind::generator, "Edge wear");
    mask_gen.mono_blending = Blend(BlendingMode::Screen, 0.75);
    mask_gen.procedural = Procedural("uzasset://generator/edge-wear@1.0.0");
    mask_gen.procedural->mask_output = "mask";
    mask_gen.preset_ref = PresetRef{PresetKind::smart_mask, "uzasset://smart-mask/edges@1.0.0", {}};
    mask.effects = {mask_fill, compare, color_sel, mask_levels, mask_paint, mask_gen};
    base.mask = mask;

    // Two fills named M_piping (LAY-13): one binds the bitmap through its alias, one references
    // the anchor of Base with a channel mapping, then one with a single referenced channel.
    Layer piping_a = MakeLayer(fx::kPipingA, LayerKind::fill, "M_piping");
    piping_a.fill = FillContent{};
    piping_a.fill->sources[ChannelType::BaseColor] = Source{BitmapSource{{bitmap, "Source_v9_M_piping", {}}, "sRGB", {}}};
    Layer piping_b = MakeLayer(fx::kPipingB, LayerKind::fill, "M_piping");
    piping_b.fill = FillContent{};
    ReferenceSource mapped = Ref(fx::kAnchor);
    mapped.channel_mapping[ChannelType::BaseColor] = ChannelType::BaseColor;
    piping_b.fill->sources[ChannelType::BaseColor] = Source{mapped};
    ReferenceSource single = Ref(fx::kAnchor);
    single.referenced_channel = ChannelType::Roughness;
    single.alpha_matte = true;
    single.levels = LevelsParams{std::nullopt, {LevelsComponent{}}, {}};
    piping_b.fill->sources[ChannelType::Roughness] = Source{single};
    piping_b.fill->source_mode = SourceMode::Material;
    piping_b.fill->material_source = uniform(0.1, 0.1, 0.1);

    Layer paint = MakeLayer(fx::kPaint, LayerKind::paint, "Paint");
    paint.paint = PaintContent{{{ChannelType::BaseColor, 1004}}, std::nullopt, {}};
    paint.blending[ChannelType::BaseColor] = Blend(BlendingMode::Overlay, 0.4);

    Layer child = MakeLayer(fx::kChild, LayerKind::fill, "Leather");
    child.fill = FillContent{};
    child.fill->sources[ChannelType::Roughness] = uniform(0.6, 0.6, 0.6);
    Layer group = MakeLayer(fx::kGroup, LayerKind::group, "Smart leather");
    group.collapsed = true;
    group.children = {child};
    group.preset_ref = PresetRef{PresetKind::smart_material, "uzasset://smart-material/leather@3.0.0", {}};
    group.blending[ChannelType::BaseColor] = Blend(BlendingMode::PassThrough, 1.0);

    Layer instance = MakeLayer(fx::kInstance, LayerKind::instance, "Leather instance");
    instance.instance_source = fx::kGroup;

    stack.root_layers = {instance, group, paint, piping_b, piping_a, base};
    set.stacks = {stack};
    p.texture_sets = {set};
    return p;
}

// ── Cases ────────────────────────────────────────────────────────────────────────────────────

void Sha256Vectors() {
    CHECK(Hash("") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    CHECK(Hash("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    CHECK(Hash("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq") ==
          "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1");
    CHECK(Hash(std::string(1000000, 'a')) == "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0");
}

void JsonCanonicalForm() {
    CHECK(json::FormatDouble(1.0) == "1.0");
    CHECK(json::FormatDouble(0.1) == "0.1");
    CHECK(json::FormatDouble(-0.0) == "-0.0");
    CHECK(json::FormatDouble(123.456) == "123.456");
    CHECK(json::FormatDouble(1e15) == "1000000000000000.0");
    CHECK(json::FormatDouble(1e16) == "1e+16");
    CHECK(json::FormatDouble(0.0001) == "0.0001");
    CHECK(json::FormatDouble(0.00001) == "1e-05");
    CHECK(json::FormatDouble(1.5e300) == "1.5e+300");
    CHECK(json::FormatDouble(5e-324) == "5e-324");
    CHECK(json::FormatDouble(0.30000000000000004) == "0.30000000000000004");
    const json::Value value = json::Parse(R"( {"b": [1, 2.5, -0, true, null], "a": "é\n\u0001😀"} )");
    CHECK(json::WriteCanonical(value) == "{\"a\":\"\xc3\xa9\\n\\u0001\xf0\x9f\x98\x80\",\"b\":[1,2.5,0,true,null]}");
    EXPECT_THROW(json::ParseError, json::Parse(R"({"a": 1, "a": 2})"));
    EXPECT_THROW(json::ParseError, json::Parse(R"("\ud800")"));
    EXPECT_THROW(json::ParseError, json::Parse("\"\xc0\xaf\""));
    EXPECT_THROW(json::ParseError, json::Parse("1e400"));
    EXPECT_THROW(json::ParseError, json::Parse("9223372036854775808"));
    EXPECT_THROW(json::ParseError, json::Parse("[1] 2"));
    EXPECT_THROW(json::ParseError, json::Parse("[01]"));
}

/// 3.1: the fixture covers every kind and round-trips to an equal document and digest.
void FixtureRoundTrip() {
    const Project project = BuildFixture(false);
    std::set<NodeType> types;
    std::set<SourceKind> sources;
    for (const Layer& layer : project.texture_sets[0].stacks[0].root_layers) {
        const std::function<void(const Layer&)> visit = [&](const Layer& l) {
            types.insert(l.type());
            const auto add_fill = [&](const std::optional<FillContent>& fill) {
                if (!fill) return;
                for (const auto& [channel, source] : fill->sources) sources.insert(source.kind());
            };
            add_fill(l.fill);
            for (const Effect& e : l.content_effects) types.insert(e.type());
            if (l.mask) {
                for (const Effect& e : l.mask->effects) types.insert(e.type());
            }
            for (const Layer& c : l.children) visit(c);
        };
        visit(layer);
    }
    CHECK(types.size() == 12);
    CHECK(sources.size() == 6);
    std::set<MeshMapProvenanceKind> provenances;
    for (const auto& [usage, binding] : project.texture_sets[0].mesh_maps) provenances.insert(binding.provenance_kind());
    CHECK(provenances.size() == 2);

    const std::string text = SaveManifest(project);
    const Project loaded = LoadManifest(text);
    CHECK(loaded == project);
    CHECK(SaveManifest(loaded) == text);
    CHECK(ManifestDigest(loaded) == ManifestDigest(project));
    CHECK(ManifestDigest(project) == Hash(text));
}

/// 3.2: maps filled in another order give the same canonical bytes.
void DigestIndependentOfInsertionOrder() {
    CHECK(SaveManifest(BuildFixture(false)) == SaveManifest(BuildFixture(true)));
    CHECK(ManifestDigest(BuildFixture(false)) == ManifestDigest(BuildFixture(true)));
}

void CollectIds(const Layer& layer, std::vector<std::pair<Id, std::string>>& out) {
    out.emplace_back(layer.uid, layer.name);
    for (const Effect& e : layer.content_effects) out.emplace_back(e.uid, e.name);
    if (layer.mask) {
        for (const Effect& e : layer.mask->effects) out.emplace_back(e.uid, e.name);
    }
    for (const Layer& c : layer.children) CollectIds(c, out);
}

std::vector<std::pair<Id, std::string>> AllIds(const Project& p) {
    std::vector<std::pair<Id, std::string>> out;
    for (const auto& [hash, entries] : p.resources) {
        for (const ResourceMeta& m : entries) out.emplace_back(m.id, m.name);
    }
    for (const TextureSet& set : p.texture_sets) {
        out.emplace_back(set.id, set.name);
        for (const UVTile& tile : set.uv_tiles) out.emplace_back(tile.id, std::to_string(tile.udim));
        for (const Stack& stack : set.stacks) {
            out.emplace_back(stack.id, stack.name);
            for (const Layer& layer : stack.root_layers) CollectIds(layer, out);
        }
    }
    std::sort(out.begin(), out.end());
    return out;
}

/// 3.6: ids persist through the round trip; same-named nodes keep distinct ids; new ids continue
/// from next_id after reopening.
void IdsPersist() {
    Project project = BuildFixture(false);
    const Project loaded = LoadManifest(SaveManifest(project));
    CHECK(AllIds(loaded) == AllIds(project));
    CHECK(loaded.next_id == fx::kNext);
    std::vector<Id> piping;
    for (const Layer& layer : loaded.texture_sets[0].stacks[0].root_layers) {
        if (layer.name == "M_piping") piping.push_back(layer.uid);
    }
    CHECK(piping.size() == 2);
    CHECK(piping[0] != piping[1]);
    CHECK((piping == std::vector<Id>{fx::kPipingB, fx::kPipingA}));

    Project reopened = loaded;
    const Id added = InsertNode(reopened, InsertPosition::FromStack(fx::kSet, fx::kStack), NodeType::FillLayer, "M_piping");
    CHECK(added == fx::kNext);
    const Project again = LoadManifest(SaveManifest(reopened));
    CHECK(again.next_id == fx::kNext + 1);
    CHECK(again.texture_sets[0].stacks[0].root_layers.front().uid == added);
    CHECK(again.texture_sets[0].stacks[0].root_layers.front().name == "M_piping");
}

/// 3.5 and the spec scenario: rejected insertions leave the document unchanged.
void InsertionRules() {
    Project project = BuildFixture(false);
    const std::string before = SaveManifest(project);
    const auto rejected = [&](const InsertPosition& position, NodeType type, Id source = kNoId) {
        EXPECT_THROW(ValueError, InsertNode(project, position, type, "x", source));
        CHECK(SaveManifest(project) == before);
    };
    rejected(InsertPosition::Inside(fx::kBase, NodeStack::Content), NodeType::CompareMaskEffect);
    rejected(InsertPosition::Inside(fx::kBase, NodeStack::Content), NodeType::ColorSelectionEffect);
    rejected(InsertPosition::Above(fx::kLevels), NodeType::CompareMaskEffect);
    rejected(InsertPosition::Inside(fx::kBase, NodeStack::Mask), NodeType::GroupLayer);
    rejected(InsertPosition::Above(fx::kCompare), NodeType::GroupLayer);
    rejected(InsertPosition::Inside(fx::kBase, NodeStack::Content), NodeType::FillLayer);
    rejected(InsertPosition::FromStack(fx::kSet, fx::kStack), NodeType::LevelsEffect);
    rejected(InsertPosition::Inside(fx::kBase, NodeStack::Substack), NodeType::FillLayer);
    rejected(InsertPosition::Inside(fx::kPipingA, NodeStack::Mask), NodeType::FillEffect);  // no mask
    rejected(InsertPosition::Inside(fx::kLevels, NodeStack::Content), NodeType::FillEffect);
    rejected(InsertPosition::Above(fx::kBase), NodeType::FillEffect);
    rejected(InsertPosition::Above(999), NodeType::FillLayer);
    rejected(InsertPosition::FromStack(fx::kSet, 999), NodeType::FillLayer);
    rejected(InsertPosition::FromStack(fx::kSet, fx::kStack), NodeType::InstanceLayer);  // no source
    rejected(InsertPosition::FromStack(fx::kSet, fx::kStack), NodeType::InstanceLayer, fx::kAnchor);
    rejected(InsertPosition::FromStack(fx::kSet, fx::kStack), NodeType::FillLayer, fx::kGroup);

    const Id compare = InsertNode(project, InsertPosition::Inside(fx::kBase, NodeStack::Mask), NodeType::CompareMaskEffect, "cmp");
    CHECK(FindNodeType(project, compare) == NodeType::CompareMaskEffect);
    const Id below = InsertNode(project, InsertPosition::Below(fx::kCompare), NodeType::ColorSelectionEffect, "sel");
    CHECK(FindNodeType(project, below) == NodeType::ColorSelectionEffect);
    const Id sub = InsertNode(project, InsertPosition::Inside(fx::kGroup, NodeStack::Substack), NodeType::GroupLayer, "sub");
    CHECK(project.texture_sets[0].stacks[0].root_layers[1].children.front().uid == sub);
    const Id levels = InsertNode(project, InsertPosition::Inside(fx::kPipingA, NodeStack::Content), NodeType::LevelsEffect, "lv");
    CHECK(FindNodeType(project, levels) == NodeType::LevelsEffect);
    const Id anchor = InsertNode(project, InsertPosition::Above(fx::kLevels), NodeType::AnchorPointEffect, "a2");
    CHECK(FindNodeType(project, anchor) == NodeType::AnchorPointEffect);
    const Id instance = InsertNode(project, InsertPosition::Below(fx::kBase), NodeType::InstanceLayer, "inst", fx::kPipingA);
    CHECK(project.texture_sets[0].stacks[0].root_layers.back().uid == instance);
    for (const NodeType type : {NodeType::PaintLayer, NodeType::FillEffect, NodeType::PaintEffect,
                                NodeType::GeneratorEffect, NodeType::FilterEffect}) {
        const bool layer = IsLayerType(type);
        const Id id = InsertNode(project, layer ? InsertPosition::FromStack(fx::kSet, fx::kStack)
                                                : InsertPosition::Inside(fx::kPaint, NodeStack::Content),
                                 type, std::string(ToString(type)));
        CHECK(FindNodeType(project, id) == type);
    }
    CHECK(LoadManifest(SaveManifest(project)) == project);
}

/// Instance cycles and every anchor cycle raise ValueError; anchors used after they publish do
/// not.
void AnchorCycles() {
    // Base's fill effect references Base's own anchor, which comes after it: a cycle.
    Project p = BuildFixture(false);
    Layer& base = p.texture_sets[0].stacks[0].root_layers.back();
    base.content_effects[0].fill->sources[ChannelType::BaseColor] = Source{Ref(fx::kAnchor)};
    const std::string message = EXPECT_THROW(ValueError, Validate(p));
    CHECK(message.find("anchor reference cycle") != std::string::npos);

    // An effect after the anchor may use it.
    Project ok = BuildFixture(false);
    Layer& base_ok = ok.texture_sets[0].stacks[0].root_layers.back();
    Effect use = MakeEffect(99, EffectKind::fill, "use");
    use.fill = FillContent{};
    use.fill->sources[ChannelType::BaseColor] = Source{Ref(fx::kAnchor)};
    base_ok.content_effects.push_back(use);
    Validate(ok);

    // Two layers referencing each other's anchors.
    Project two = BuildFixture(false);
    auto& roots = two.texture_sets[0].stacks[0].root_layers;
    Layer& a = roots[4];  // M_piping (A)
    Effect anchor_a = MakeEffect(90, EffectKind::anchor, "A");
    anchor_a.anchor_name = "A";
    a.content_effects.push_back(anchor_a);
    roots.back().fill->sources[ChannelType::BaseColor] = Source{Ref(90)};
    Layer& b = roots[3];  // M_piping (B) references Base's anchor already
    CHECK(b.uid == fx::kPipingB);
    Validate(two);  // B -> Base, Base -> A: acyclic
    a.fill->sources[ChannelType::BaseColor] = Source{Ref(fx::kAnchor)};
    EXPECT_THROW(ValueError, Validate(two));  // A -> Base -> A
    EXPECT_THROW(ValueError, LoadManifest(json::WriteCanonical(ProjectToJson(two))));

    // An instance of its own group.
    Project inst = BuildFixture(false);
    Layer& group = inst.texture_sets[0].stacks[0].root_layers[1];
    Layer self = MakeLayer(91, LayerKind::instance, "self");
    self.instance_source = fx::kGroup;
    group.children.push_back(self);
    EXPECT_THROW(ValueError, Validate(inst));

    // A reference to something that is not an anchor.
    Project missing = BuildFixture(false);
    missing.texture_sets[0].stacks[0].root_layers[3].fill->sources[ChannelType::BaseColor] =
        Source{Ref(fx::kLevels)};
    EXPECT_THROW(ValueError, Validate(missing));
}

/// 2.1-2.5 constraints on hand-built documents.
void ModelConstraints() {
    // Decision 031: a project that does not set the tangent space uses Painter's default.
    CHECK(ProjectSettings{}.tangent_space == TangentSpace::PerVertex);
    const auto invalid = [](const std::function<void(Project&)>& edit) {
        Project p = BuildFixture(false);
        edit(p);
        EXPECT_THROW(ValueError, Validate(p));
        EXPECT_THROW(ValueError, SaveManifest(p));
    };
    invalid([](Project& p) { p.texture_sets[0].resolution.width = 3000; });
    invalid([](Project& p) { p.texture_sets[0].resolution = {64, 64, {}}; });
    invalid([](Project& p) { p.texture_sets[0].resolution = {16384, 16384, {}}; });
    invalid([](Project& p) { p.settings.default_resolution.height = 1000; });
    invalid([](Project& p) { p.texture_sets[0].uv_tiles.push_back(UVTile{50, 1002, {}}); });
    invalid([](Project& p) { p.texture_sets[0].uv_tiles[0].udim = 1002; });
    invalid([](Project& p) { p.texture_sets[0].stacks[0].root_layers[0].uid = fx::kBase; });  // duplicate id
    invalid([](Project& p) { p.next_id = fx::kInstance; });                                  // id not below next_id
    invalid([](Project& p) {  // compare mask in a content stack
        Effect compare = MakeEffect(92, EffectKind::compare_mask, "cmp");
        compare.compare_mask = json::Object{};
        p.texture_sets[0].stacks[0].root_layers.back().content_effects.push_back(compare);
    });
    invalid([](Project& p) {  // mask-stack effect with per-channel blending
        p.texture_sets[0].stacks[0].root_layers.back().mask->effects[0].blending[ChannelType::BaseColor] = Blending{};
    });
    invalid([](Project& p) {  // a paint plane bound twice
        p.texture_sets[0].stacks[0].root_layers[2].paint->planes[ChannelType::BaseColor] = 1001;
    });
    invalid([](Project& p) {  // a channel the stack does not have
        p.texture_sets[0].stacks[0].root_layers[2].blending[ChannelType::Opacity] = Blending{};
    });
    invalid([](Project& p) { p.texture_sets[0].stacks[0].root_layers[2].blending[ChannelType::BaseColor].opacity = 1.5; });
    invalid([](Project& p) {  // a binding to bytes that are not stored
        p.texture_sets[0].stacks[0].root_layers[4].fill->sources[ChannelType::BaseColor] =
            Source{BitmapSource{{Hash("missing"), std::nullopt, {}}, "sRGB", {}}};
    });
    invalid([](Project& p) { p.resources.begin()->second.push_back(p.resources.begin()->second.front()); });
    invalid([](Project& p) { p.texture_sets[0].stacks[0].root_layers[1].preset_ref->kind = PresetKind::smart_mask; });
    invalid([](Project& p) { p.texture_sets[0].stacks[0].root_layers[0].instance_source = kNoId; });
    invalid([](Project& p) { p.texture_sets[0].stacks[0].root_layers[2].fill = FillContent{}; });  // paint layer with a fill
    invalid([](Project& p) { p.texture_sets[0].stacks.push_back(p.texture_sets[0].stacks[0]); });  // reused ids, same name
    invalid([](Project& p) { p.texture_sets[0].mesh_maps.begin()->second.resource = "ABC"; });
    invalid([](Project& p) {
        p.texture_sets[0].stacks[0].root_layers.back().content_effects[1].procedural =
            Procedural("uzasset://generator/position@1.0.0");  // paint effect with a procedural
    });
    invalid([](Project& p) {
        p.texture_sets[0].stacks[0].root_layers.back().content_effects[2].procedural->asset = "uzasset://Bad/x";
    });

    // The UVTile workflow may carry several tiles.
    Project tiles = BuildFixture(false);
    tiles.settings.workflow = ProjectWorkflow::UVTile;
    tiles.texture_sets[0].uv_tiles.push_back(UVTile{50, 1012, {}});
    Validate(tiles);
    CHECK(LoadManifest(SaveManifest(tiles)) == tiles);
}

std::string Replace(std::string text, const std::string& from, const std::string& to) {
    const std::size_t at = text.find(from);
    if (at == std::string::npos) throw Failure{"fixture text lacks " + from};
    return text.replace(at, from.size(), to);
}

/// 3.3 and 3.4 at the reader: shape errors, the newer major and unknown keys.
void ManifestReader() {
    const std::string text = SaveManifest(BuildFixture(false));
    EXPECT_THROW(ManifestError, LoadManifest(Replace(text, "\"format\":\"RGB16F\"", "\"format\":\"RGB12\"")));
    EXPECT_THROW(ManifestError, LoadManifest(Replace(text, "\"format_version\":\"1.0.0\"", "\"format_version\":\"2.0.0\"")));
    EXPECT_THROW(ManifestError, LoadManifest(Replace(text, "\"format_version\":\"1.0.0\"", "\"format_version\":\"1.x\"")));
    EXPECT_THROW(ManifestError, LoadManifest(Replace(text, "\"schema\":\"uzpainter/manifest/1\"", "\"schema\":\"other\"")));
    EXPECT_THROW(ManifestError, LoadManifest(Replace(text, "\"kind\":\"paint\"", "\"kind\":\"sculpt\"")));
    EXPECT_THROW(ManifestError, LoadManifest(Replace(text, "\"next_id\":100", "\"next_id\":\"100\"")));
    EXPECT_THROW(ValueError, LoadManifest(Replace(text, "\"height\":2048,\"width\":2048},\"stacks\"",
                                                  "\"height\":3000,\"width\":3000},\"stacks\"")));
    EXPECT_THROW(json::ParseError,
                 LoadManifest(Replace(text, "\"channels\":{", "\"channels\":{\"BaseColor\":{\"format\":\"L8\",\"label\":\"\"},")));
    // A minor version newer than this one is read.
    const Project newer_minor = LoadManifest(Replace(text, "\"format_version\":\"1.0.0\"", "\"format_version\":\"1.7.0\""));
    CHECK(newer_minor.versions.format_version == "1.7.0");

    // Unknown keys at several levels survive load/save unchanged.
    std::string extended = Replace(text, "{\"display\":", "{\"future_top\":{\"z\":[1,2.5,\"x\"],\"a\":null},\"display\":");
    extended = Replace(extended, "\"uid\":10,", "\"uid\":10,\"future_layer\":\"kept\",");
    extended = Replace(extended, "\"uid\":24,", "\"uid\":24,\"future_effect\":{\"n\":1},");
    extended = Replace(extended, "\"rgb\":[0.8,0.2,0.1]", "\"rgb\":[0.8,0.2,0.1],\"future_source\":true");
    extended = Replace(extended, "\"painter_reference\":{", "\"painter_reference\":{\"future_ref\":0.5,");
    const Project loaded = LoadManifest(extended);
    const std::string saved = SaveManifest(loaded);
    CHECK(saved == json::WriteCanonical(json::Parse(extended)));
    CHECK(loaded.extra.at("future_top") == json::Parse(R"({"a":null,"z":[1,2.5,"x"]})"));
    CHECK(loaded.texture_sets[0].stacks[0].root_layers.back().extra.at("future_layer") == json::Value("kept"));
}

void ResourceUrls() {
    const std::string hash = Hash("bitmap bytes");
    const std::string url = FormatResourceUrl({"M piping/v10?", hash});
    CHECK(url == "resource://project/M%20piping%2Fv10%3F?version=" + hash);
    CHECK(ParseResourceUrl(url) == (ProjectResourceUrl{"M piping/v10?", hash}));
    CHECK(ParseResourceUrl("resource://project/M_piping?version=" + hash).name == "M_piping");
    EXPECT_THROW(ValueError, ParseResourceUrl("resource://project/M_piping?version=abc"));
    EXPECT_THROW(ValueError, ParseResourceUrl("resource://shelf/M_piping?version=" + hash));
    EXPECT_THROW(ValueError, ParseResourceUrl("resource://project/?version=" + hash));
    EXPECT_THROW(ValueError, ParseResourceUrl("resource://project/a%2?version=" + hash));
    EXPECT_THROW(ValueError, FormatResourceUrl({"", hash}));
    const AssetUrl asset{"generator", "edge-wear", "1.2.0+uzp.1"};
    CHECK(FormatAssetUrl(asset) == "uzasset://generator/edge-wear@1.2.0+uzp.1");
    CHECK(ParseAssetUrl("uzasset://generator/edge-wear@1.2.0+uzp.1") == asset);
    EXPECT_THROW(ValueError, ParseAssetUrl("uzasset://generator/edge-wear"));
    EXPECT_THROW(ValueError, ParseAssetUrl("uzasset://Generator/x@1"));
    EXPECT_THROW(ValueError, ParseAssetUrl("uzasset://generator@1/x"));
    EXPECT_THROW(ValueError, FormatAssetUrl({"generator", "", "1"}));
}

void ResultHeader() {
    ResultRecordHeader header{42, "painter-12.1-layerq-linear", std::string(kCompatProfile), "0.1.0",
                              {Hash("b"), Hash("a")}};
    json::Object receipt = HeaderToJson(header);
    receipt["export_path"] = "out/M_tunic_BaseColor.png";  // a receipt's own key
    const std::string text = json::WriteCanonical(receipt);
    CHECK(text.find("\"revision\":42") != std::string::npos);
    CHECK(text.find("\"resource_hashes\":[\"" + std::min(Hash("a"), Hash("b"))) != std::string::npos);
    const json::Value parsed = json::Parse(text);
    CHECK(HeaderFromJson(std::get<json::Object>(parsed.data)) == header);
    json::Object bad = receipt;
    bad["revision"] = -1;
    EXPECT_THROW(ManifestError, HeaderFromJson(bad));
    bad = receipt;
    bad["resource_hashes"] = json::Array{"xyz"};
    EXPECT_THROW(ManifestError, HeaderFromJson(bad));
    bad = receipt;
    bad.erase("compat_profile");
    EXPECT_THROW(ManifestError, HeaderFromJson(bad));
}

int Run(const std::string& only) {
    const std::vector<std::pair<const char*, void (*)()>> cases = {
        {"sha256_vectors", Sha256Vectors},
        {"json_canonical_form", JsonCanonicalForm},
        {"fixture_round_trip", FixtureRoundTrip},
        {"digest_independent_of_insertion_order", DigestIndependentOfInsertionOrder},
        {"ids_persist", IdsPersist},
        {"insertion_rules", InsertionRules},
        {"anchor_cycles", AnchorCycles},
        {"model_constraints", ModelConstraints},
        {"manifest_reader", ManifestReader},
        {"resource_urls", ResourceUrls},
        {"result_header", ResultHeader},
    };
    int failed = 0;
    int ran = 0;
    for (const auto& [name, body] : cases) {
        if (!only.empty() && only != name) continue;
        ++ran;
        try {
            body();
            std::printf("PASS %s\n", name);
        } catch (const Failure& failure) {
            ++failed;
            std::printf("FAIL %s: %s\n", name, failure.message.c_str());
        } catch (const std::exception& error) {
            ++failed;
            std::printf("FAIL %s: unexpected exception: %s\n", name, error.what());
        }
    }
    std::printf("%d cases, %d failed\n", ran, failed);
    return failed == 0 && ran > 0 ? 0 : 1;
}

std::string ReadFile(const char* path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) throw std::runtime_error(std::string("cannot read ") + path);
    std::ostringstream text;
    text << file.rdbuf();
    return text.str();
}

int Command(int argc, char** argv) {
    const std::string command = argc > 1 ? argv[1] : "";
    if (command == "run") return Run(argc > 2 ? argv[2] : "");
    if (command == "fixture") {
        const std::string out = SaveManifest(BuildFixture(argc > 2 && std::string(argv[2]) == "reversed"));
        std::fwrite(out.data(), 1, out.size(), stdout);
        return 0;
    }
    if (argc < 3 || (command != "canonical" && command != "digest" && command != "json")) {
        std::fprintf(stderr, "usage: uzp-core-tests run [case] | fixture [reversed] | canonical|digest|json <file>\n");
        return 2;
    }
    const std::string text = ReadFile(argv[2]);
    std::string out;
    if (command == "canonical") out = SaveManifest(LoadManifest(text));
    if (command == "digest") out = ManifestDigest(LoadManifest(text));
    if (command == "json") out = json::WriteCanonical(json::Parse(text));
    std::fwrite(out.data(), 1, out.size(), stdout);
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        return Command(argc, argv);
    } catch (const ValueError& error) {
        std::fprintf(stderr, "ValueError: %s\n", error.what());
    } catch (const ManifestError& error) {
        std::fprintf(stderr, "ManifestError: %s\n", error.what());
    } catch (const json::ParseError& error) {
        std::fprintf(stderr, "ParseError: %s\n", error.what());
    } catch (const std::exception& error) {
        std::fprintf(stderr, "Error: %s\n", error.what());
    }
    return 3;
}
