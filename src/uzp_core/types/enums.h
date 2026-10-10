#pragma once

// Enumerations of the document model and their manifest spellings.
//
// Members that mirror a documented Painter enum keep the documented member names (Painter 12.1.0
// Python API documentation, approved source A-PYDOC, `docs/approved-sources.md`): `ChannelType`
// and `MeshMapUsage` list the members recorded with their documentation page in
// `tools/parity/recorder/documented_symbols.json`; `ChannelFormat`, `BlendingMode`, `NodeType`,
// `NormalMapFormat`, `TangentSpace`, `ProjectWorkflow`, `MaskBackground`, `ProjectionMode`,
// `FilteringMode`, `UVWrapMode` and `ScaleMode` list the members `docs/architecture/03-…`,
// `04-…` and the documentation name. Enumerations without a Painter counterpart (`LayerKind`,
// `EffectKind`, `SourceKind`, ...) use the lower-case spellings of `04-…` §1 and `03-…` §4.
//
// Each enum's values are contiguous from 0 in the order of its name table.

#include <array>
#include <cstddef>
#include <optional>
#include <string_view>

namespace uzp::core {

template <typename E>
struct EnumTable;  // specialised below: `static constexpr std::array<std::string_view, N> names`

template <typename E>
constexpr std::string_view ToString(E value) {
    return EnumTable<E>::names[static_cast<std::size_t>(value)];
}

template <typename E>
constexpr std::optional<E> FromString(std::string_view name) {
    for (std::size_t i = 0; i < EnumTable<E>::names.size(); ++i) {
        if (EnumTable<E>::names[i] == name) return static_cast<E>(i);
    }
    return std::nullopt;
}

#define UZP_ENUM_TABLE(E, ...)                                                       \
    template <>                                                                      \
    struct EnumTable<E> {                                                            \
        static constexpr auto names = std::to_array<std::string_view>({__VA_ARGS__}); \
    }

enum class NormalMapFormat { OpenGL, DirectX };
UZP_ENUM_TABLE(NormalMapFormat, "OpenGL", "DirectX");

enum class TangentSpace { PerVertex, PerFragment };
UZP_ENUM_TABLE(TangentSpace, "PerVertex", "PerFragment");

enum class ProjectWorkflow { Default, UVTile, TextureSetPerUVTile };
UZP_ENUM_TABLE(ProjectWorkflow, "Default", "UVTile", "TextureSetPerUVTile");

enum class ChannelType {
    AO, Anisotropylevel, BaseColor, BaseMetalness, BaseWeight, Displacement, EmissionColor,
    Emissive, Height, Metallic, Normal, Opacity, Roughness, Scattering, SpecularColor,
    SpecularRoughness, SpecularWeight, User0, User1, User2, User3, User4, User5, User6, User7,
};
UZP_ENUM_TABLE(ChannelType, "AO", "Anisotropylevel", "BaseColor", "BaseMetalness", "BaseWeight",
               "Displacement", "EmissionColor", "Emissive", "Height", "Metallic", "Normal",
               "Opacity", "Roughness", "Scattering", "SpecularColor", "SpecularRoughness",
               "SpecularWeight", "User0", "User1", "User2", "User3", "User4", "User5", "User6",
               "User7");

/// The nine Painter channel formats (`03-project-model.md` §2).
enum class ChannelFormat { sRGB8, L8, RGB8, L16, RGB16, L16F, RGB16F, L32F, RGB32F };
UZP_ENUM_TABLE(ChannelFormat, "sRGB8", "L8", "RGB8", "L16", "RGB16", "L16F", "RGB16F", "L32F",
               "RGB32F");

enum class MeshMapUsage {
    AO, BentNormals, Curvature, Height, ID, Normal, Opacity, Position, Thickness, WorldSpaceNormal,
};
UZP_ENUM_TABLE(MeshMapUsage, "AO", "BentNormals", "Curvature", "Height", "ID", "Normal", "Opacity",
               "Position", "Thickness", "WorldSpaceNormal");

/// The 32 documented blending modes (`04-layer-stack-and-compositing.md` §3).
enum class BlendingMode {
    Normal, PassThrough, Disable, Replace, Multiply, Divide, InverseDivide, Darken, Lighten,
    LinearDodge, Subtract, InverseSubtract, Difference, Exclusion, SignedAddition, Overlay, Screen,
    LinearBurn, ColorBurn, ColorDodge, SoftLight, HardLight, VividLight, LinearLight, PinLight,
    Tint, Saturation, Color, Value, NormalMapCombine, NormalMapDetail, NormalMapInverseDetail,
};
UZP_ENUM_TABLE(BlendingMode, "Normal", "PassThrough", "Disable", "Replace", "Multiply", "Divide",
               "InverseDivide", "Darken", "Lighten", "LinearDodge", "Subtract", "InverseSubtract",
               "Difference", "Exclusion", "SignedAddition", "Overlay", "Screen", "LinearBurn",
               "ColorBurn", "ColorDodge", "SoftLight", "HardLight", "VividLight", "LinearLight",
               "PinLight", "Tint", "Saturation", "Color", "Value", "NormalMapCombine",
               "NormalMapDetail", "NormalMapInverseDetail");

/// The twelve documented node types: four layers and eight effects.
enum class NodeType {
    FillLayer, PaintLayer, GroupLayer, InstanceLayer, FillEffect, PaintEffect, GeneratorEffect,
    FilterEffect, LevelsEffect, CompareMaskEffect, ColorSelectionEffect, AnchorPointEffect,
};
UZP_ENUM_TABLE(NodeType, "FillLayer", "PaintLayer", "GroupLayer", "InstanceLayer", "FillEffect",
               "PaintEffect", "GeneratorEffect", "FilterEffect", "LevelsEffect",
               "CompareMaskEffect", "ColorSelectionEffect", "AnchorPointEffect");

/// The stacks a node holds (documented `NodeStack`): a group's sub-layers, a layer's content
/// effects, a layer's mask effects.
enum class NodeStack { Substack, Content, Mask };
UZP_ENUM_TABLE(NodeStack, "Substack", "Content", "Mask");

enum class LayerKind { fill, paint, group, instance };
UZP_ENUM_TABLE(LayerKind, "fill", "paint", "group", "instance");

enum class EffectKind { fill, paint, generator, filter, levels, compare_mask, color_selection, anchor };
UZP_ENUM_TABLE(EffectKind, "fill", "paint", "generator", "filter", "levels", "compare_mask",
               "color_selection", "anchor");

enum class MaskBackground { Black, White };
UZP_ENUM_TABLE(MaskBackground, "Black", "White");

enum class SourceMode { Split, Material };
UZP_ENUM_TABLE(SourceMode, "Split", "Material");

enum class GeometryMaskType { Mesh, UVTile };
UZP_ENUM_TABLE(GeometryMaskType, "Mesh", "UVTile");

/// The documented projection modes plus `Warp` and `UVSetToUVSet` (release gaps until their
/// goldens exist, `04-…` §5).
enum class ProjectionMode { Fill, UV, Triplanar, Planar, Spherical, Cylindrical, Warp, UVSetToUVSet };
UZP_ENUM_TABLE(ProjectionMode, "Fill", "UV", "Triplanar", "Planar", "Spherical", "Cylindrical",
               "Warp", "UVSetToUVSet");

enum class FilteringMode { BilinearHQ, BilinearSharp, Nearest };
UZP_ENUM_TABLE(FilteringMode, "BilinearHQ", "BilinearSharp", "Nearest");

enum class UVWrapMode { RepeatNone, RepeatHorizontally, RepeatVertically, Repeat };
UZP_ENUM_TABLE(UVWrapMode, "RepeatNone", "RepeatHorizontally", "RepeatVertically", "Repeat");

enum class ScaleMode { Factors, MaterialPhysicalSize, CustomPhysicalSize };
UZP_ENUM_TABLE(ScaleMode, "Factors", "MaterialPhysicalSize", "CustomPhysicalSize");

enum class SourceKind { uniform_color, bitmap, vector, font, procedural, reference };
UZP_ENUM_TABLE(SourceKind, "uniform_color", "bitmap", "vector", "font", "procedural", "reference");

/// Smart presets expand into editable nodes and keep this reference for provenance only.
enum class PresetKind { smart_material, smart_mask };
UZP_ENUM_TABLE(PresetKind, "smart_material", "smart_mask");

enum class ToneMapping { Linear, ACES };
UZP_ENUM_TABLE(ToneMapping, "Linear", "ACES");

enum class MeshMapProvenanceKind { imported, baked };
UZP_ENUM_TABLE(MeshMapProvenanceKind, "imported", "baked");

enum class MeshMapRole { geometry_only, combined };
UZP_ENUM_TABLE(MeshMapRole, "geometry_only", "combined");

enum class BakerBackend { embree, dx12_rt, vulkan_rt };
UZP_ENUM_TABLE(BakerBackend, "embree", "dx12_rt", "vulkan_rt");

#undef UZP_ENUM_TABLE

/// The documented node type of a layer or effect kind (the tables share their order).
constexpr NodeType NodeTypeOf(LayerKind kind) { return static_cast<NodeType>(kind); }
constexpr NodeType NodeTypeOf(EffectKind kind) {
    return static_cast<NodeType>(static_cast<int>(kind) + static_cast<int>(NodeType::FillEffect));
}

/// True for the layer node types (fill, paint, group, instance layers).
constexpr bool IsLayerType(NodeType type) { return type < NodeType::FillEffect; }

/// The layer or effect kind of a node type.
constexpr LayerKind LayerKindOf(NodeType type) { return static_cast<LayerKind>(type); }
constexpr EffectKind EffectKindOf(NodeType type) {
    return static_cast<EffectKind>(static_cast<int>(type) - static_cast<int>(NodeType::FillEffect));
}

}  // namespace uzp::core
