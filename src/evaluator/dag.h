#pragma once

// The evaluation DAG of one (texture set, stack, channel) (docs/architecture/04-layer-stack-and-
// compositing.md §2, §7): built from a revision snapshot, independent of tiles, with the subtree
// hash of every node output, so that the cache (admission.h) serves unchanged subtrees and only
// what changed is re-evaluated.
//
// Order (04 §2): the accumulator starts at the channel's base value (profile.h: under the
// settled profile the root layers composite from a transparent start like a group and the result
// is composited over the base at read-out); root layers are walked bottom-up (storage keeps Painter's top-first order); an invisible layer or a layer in `Disable`
// for the channel is skipped; a fill layer contributes its source for the channel when the
// channel is active on it; a group composites its visible children from a transparent start
// into an isolated intermediate and that intermediate is blended with the group's mode and
// opacity (Painter's default group mode behaves so, Tier 0 `group-masks`: the default-mode group
// equals the `Normal` group texel for texel); a `PassThrough` group composites its children onto
// a copy of the accumulator below it, each child stored in the channel format, and moves the
// accumulator toward that result by the group's opacity and mask, fma(g - a, t, a) (phase1.11,
// Tier 0 `semantics-ui/group-passthrough-masks`: set through Painter's UI, the runtime member is
// `Passthrough`); an instance layer evaluates its source layer in its own position.
//
// Fill sources (phase1.8_compositor-sources-projection, sources.h): uniform colours and bitmaps
// under the `Fill` and `UV` projections (projection_uv.h), in `Split` source mode; a channel
// contributes only when it is active on the fill (toggling a channel keeps its source).
//
// Masks and effects (phase1.11_compositor-mask-effects, parity/semantics/masks-levels.json): a
// layer's or group's mask is mono and stored at 16 bits: it starts from its background (White 1,
// Black 0) and runs its visible effects bottom-up, a fill effect blending its source with its own
// mode and opacity through the effect mix v = a + (r - a) alpha, a levels effect remapping the
// value (arith::Levels); a disabled mask counts as 1; a `Mesh` geometry mask (geometry_mask.h)
// multiplies the result. Content effects run in list order on a fill layer's own content for the
// channel: a fill effect blends its source for the channel (when the channel is active on it)
// with its per-channel mode and opacity through the layer mix a (1 - alpha) + r alpha (decision
// 346; masks keep the effect mix), a levels effect remaps the channel it affects, the recorded
// Blur (`kRecordedBlurAsset`) rounds the content toward zero to binary16; the content is stored
// in the channel format after every effect.
//
// Paint layers (phase4.1_nodes-paint-layers, decision 348): an empty one, with no plane and no
// content effect, is transparent and contributes nothing.
//
// Outside this profile (explicit `evaluator:unsupported_*` failures, the capability manifest's
// release gaps): paint plane content, content effects on a paint layer, paint effects, generator and filter effects other than the recorded
// Blur (P3-PROC), compare-mask,
// colour-selection and anchor effects (P4-NODES), `UVTile` geometry masks, content effects on a
// group, `Material` source mode, procedural, vector,
// font and reference sources, the 3D projections, symmetry, physical-size UV scale modes,
// bilinear minification outside the texture unit's domain (texture_unit.h), OCIO colour management
// outside what Session O records (sources.h).

#include "evaluator/arith.h"
#include "evaluator/formats.h"
#include "evaluator/geometry_mask.h"
#include "evaluator/hash.h"
#include "evaluator/profile.h"
#include "evaluator/projection_uv.h"
#include "evaluator/templates.h"
#include "render/backend.h"
#include "evaluator/procedural_source.h"

#include <array>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "uzp_core/types/enums.h"
#include "uzp_core/types/ids.h"
#include "uzp_core/types/layers.h"
#include "uzp_core/types/project.h"

namespace uzp::evaluator {

/// What a fill layer contributes to the channel (sources.h states the colour rules).
struct DagSource {
    enum class Kind : uint8_t { Uniform, Bitmap, Procedural };
    Kind kind = Kind::Uniform;
    std::shared_ptr<const ProceduralImage> procedural;
    /// Uniform: the colour as the channel stores it, read back as an operand (blend-modes.json
    /// `uniform_operand`; a grey channel takes the mean of the three components).
    std::array<float, 3> uniform{0.0f, 0.0f, 0.0f};
    /// Bitmap: the content hash the node binds (LAY-13: the alias plays no part) and the
    /// projection that samples it.
    std::string sha256;
    UvProjection projection;
    /// The Height channel maps bitmap values to [-1, 1] (sources.h).
    bool signedRange = false;
    /// The Normal channel imports a bitmap with its green codes inverted (max - g;
    /// blend-modes.json `blend-normal-channel-import`, height_to_normal.h) and samples it as a
    /// 16-bit texture (evaluate.cpp `NormalTexture`, decision 226).
    bool invertGreen = false;
    /// The Normal channel is RGB16F in an OpenGL project, the channel P20-A records: only there is
    /// an 8-bit bitmap's bilinear magnification recorded (evaluate.cpp `CheckNormalTexture`,
    /// decision 249).
    bool p20aNormal = false;
    /// An sRGB bitmap (sources.h): its codes are decoded with the sRGB transfer function onto an
    /// sRGB8 channel, or with `l8Material` onto an L8 BaseColor, Specular or Emissive.
    bool srgbDecode = false;
    /// An sRGB bitmap on an L8 BaseColor, Specular or Emissive (sources.h, decision 208): a grey
    /// image at 1:1, checked at evaluation, whose 8-bit codes decode through a binary16.
    bool l8Material = false;
    /// Where P20-A records it (a mask source, an L8 or an L16F channel; decision 218): a colour
    /// image read by this one-channel tile is the R16F texture of its mean (evaluate.cpp
    /// `GreyTexture`), checked at evaluation. Elsewhere a colour image on a one-channel tile is
    /// refused there.
    bool greyTexture = false;
    /// Under OCIO with Painter's substance config (sources.h): the one recorded use this bitmap
    /// must be, checked against the image at evaluation (decision 190). `Srgb8Fill`: an 8-bit
    /// colour image in sRGB on an sRGB8 channel at 1:1, decoded as under legacy; `Raw8Fill`: an
    /// 8-bit colour image in Raw on an sRGB8 channel at 1:1 (`OcioRawDecoded`); `Grey16Mask`: a
    /// 16-bit grey image in a linear space as a mask source at 1:1, read as under legacy.
    enum class Ocio : uint8_t { None, Srgb8Fill, Raw8Fill, Grey16Mask };
    Ocio ocio = Ocio::None;
    /// Hash of the content (source, projection, channel, format, profile, OCIO use).
    Digest hash{};
};

/// The starter-asset Blur filter in the one configuration Tier 0 `effect-order` records (decision
/// 346): the asset at its default parameters (no parameter set), blended Normal at opacity 1 on an
/// RGB16 or sRGB8 channel of a 256 x 256 set under legacy colour management. There its output is
/// the content rounded toward zero to binary16. This is not a Blur implementation: every other
/// filter, parameter, blending, format, resolution and colour management fails with
/// `unsupported_node`, the family is uncertified and no alias names it.
inline constexpr std::string_view kRecordedBlurAsset = "uzasset://filter/blur@1";
inline constexpr uint32_t kRecordedBlurResolution = 256;

/// One effect of a mask or of a fill layer's content stack, bottom-up.
struct DagEffect {
    /// RecordedBlur: the content filter `kRecordedBlurAsset` in its recorded configuration.
    enum class Kind : uint8_t { Fill, Levels, RecordedBlur };
    Kind kind = Kind::Fill;
    core::Id uid = core::kNoId;
    /// Fill: the effect's mode and opacity (the channel's, or the mono blending of a mask effect).
    core::BlendingMode mode = core::BlendingMode::Normal;
    float opacity = 1.0f;
    /// Fill: the source (in a mask, sampled into the 16-bit mask format).
    std::optional<DagSource> source;
    /// Levels: one component per channel component (a mask or a grey channel uses the first).
    std::array<arith::LevelsComponent, 3> levels{};
    /// Hash of the value after this effect (chained from the chain's start).
    Digest hash{};
};

/// A geometry mask of type `Mesh`: the raster the provider rasterises (geometry_mask.h).
struct DagGeometry {
    GeometryMaskQuery query;
    Digest hash{};
};

/// A mask that is not a constant: its background, its effects bottom-up and the geometry mask
/// that multiplies the result. The mask is independent of the channel (one raster for every
/// channel of the layer).
struct DagMask {
    float background = 1.0f;
    std::vector<DagEffect> effects;
    std::optional<DagGeometry> geometry;
    /// Hash of the mask after the geometry mask (the mask the layer blends with).
    Digest hash{};
};

/// The format masks are stored in (masks-levels.json: 16-bit precision on every channel format).
inline constexpr core::ChannelFormat kMaskFormat = core::ChannelFormat::L16;

struct DagList;

struct DagLayer {
    /// The layer the content belongs to (the instanced layer for an instance).
    core::Id uid = core::kNoId;
    core::BlendingMode mode = core::BlendingMode::Normal;
    float opacity = 1.0f;
    /// The constant mask: 1 without a mask or with a disabled one, the background of an empty
    /// mask stack (White 1, Black 0). Ignored when `maskStack` is set.
    float mask = 1.0f;
    /// A mask with effects or a geometry mask.
    std::optional<DagMask> maskStack;
    std::optional<DagSource> source;   ///< Fill layer.
    /// Fill layer: the content effects that touch the channel, bottom-up (applied to `source`).
    std::vector<DagEffect> effects;
    std::unique_ptr<DagList> group;    ///< Group (isolated intermediate).
    /// Hash of this layer's contribution (content after its effects, mode, opacity, mask).
    Digest hash{};
    /// Hash of the accumulator after this layer (chained from the list start).
    Digest prefixHash{};
};

/// A layer list: the stack's root layers or a group's children, bottom-up, only the layers that
/// contribute to the channel.
struct DagList {
    /// The stack id (root list) or the group uid.
    core::Id owner = core::kNoId;
    /// Composited from a transparent start (a group) or from the channel base (the root).
    bool isolated = false;
    /// A PassThrough group's children: composited onto a copy of the enclosing accumulator below
    /// the group (its tile format and coverage), not from a transparent start.
    bool fromBackdrop = false;
    std::vector<DagLayer> layers;
    /// Hash of the start of the chain.
    Digest startHash{};
};

struct ChannelDag {
    core::Id textureSet = core::kNoId;
    core::Id stack = core::kNoId;
    core::ChannelType channel = core::ChannelType::BaseColor;
    core::ChannelFormat format = core::ChannelFormat::sRGB8;
    TileFormat tileFormat;
    /// The channel's base value (template), the backdrop of the bottom layer and the result of
    /// an empty stack.
    std::array<float, 3> base{0.0f, 0.0f, 0.0f};
    /// What an isolated root with layers is composited over at read-out: `base`, except on the
    /// Normal channel, whose layers composite over the flat normal (0.5, 0.5, 1) while its empty
    /// stack exports the template base 127/255 (height-to-normal.json
    /// height-normal-channel-coverage).
    std::array<float, 3> readoutBase{0.0f, 0.0f, 0.0f};
    TileGrid grid;
    std::string templateId;
    /// The project's evaluator profile (profile.h): the root list is isolated under
    /// `RootComposite::Isolated` and composited over `readoutBase` at read-out.
    EvaluatorProfile profile;
    DagList root;
    /// Hash of the root list composited over the base (Isolated profiles; the read-out tile).
    Digest readoutHash{};
};

/// Builds the DAG of `channel` of `stack` of `textureSet` in `project`, with the base values of
/// `templateId` and the profile the project records (`versions.evaluator_profile`). Fails with
/// `evaluator:unknown_profile`, `not_found`, `unknown_template`, `missing_base_value`,
/// `unsupported_node`, `unsupported_source` or `unsupported_blend_mode`.
[[nodiscard]] render::Result<ChannelDag> BuildDag(const core::Project& project,
                                                  core::Id textureSet, core::Id stack,
                                                  core::ChannelType channel,
                                                  const TemplateLibrary& templates,
                                                  std::string_view templateId,
                                                  const IProceduralSourceProvider* procedurals = nullptr);

/// The mask of layer `uid` of `frame`'s stack (at any depth; an instance's is its source's, as the
/// channel DAGs hold it) in a node with only `uid`, `mask` and `maskStack` set: the mask does not
/// depend on the channel, so `frame` (any channel's DAG of that stack) gives only the grid and the
/// profile, and the hashes equal those of every channel DAG holding the layer (one cached raster).
/// The layer's own visibility plays no part. Fails with `evaluator:not_found` when the layer is
/// not in the stack, and with the failures of the mask's effects (`unsupported_*`).
[[nodiscard]] render::Result<DagLayer> BuildLayerMask(const core::Project& project, const ChannelDag& frame,
                                                      core::Id uid);

/// Checks authoritative procedural inputs before any memory or persistent cache hit.
[[nodiscard]] bool ProceduralInputsAvailable(const ChannelDag& dag, const IProceduralSourceProvider* provider);

/// The blending of `layer` on `channel`: its own entry, or Normal at opacity 1 when it has none.
/// A group's entry is the blending of its composite on that channel; its `Height` entry is the
/// per-group Height blend override of LAY-03 (the children keep their own entries), and this is
/// the effective Height blend of any layer.
[[nodiscard]] core::Blending EffectiveBlending(const core::Layer& layer, core::ChannelType channel);

/// The operand of a uniform colour on a channel of `format` with base `base` (blend-modes.json
/// `uniform_operand`): each component (the mean of the three on a grey channel) stored with the
/// channel's write rule and read back; on a 32-bit float channel the float32 value when
/// `float32Plain` (EvaluatorProfile::float32UniformPlain), else `1 + (v - 1)` over `base`. The
/// grey mean is taken of the components as given when `greyUnrounded`
/// (EvaluatorProfile::uniformGreyUnrounded), else of their float32 values.
[[nodiscard]] std::array<float, 3> UniformOperand(const std::array<double, 3>& colour,
                                                  const TileFormat& format,
                                                  const std::array<float, 3>& base,
                                                  bool float32Plain = false,
                                                  bool greyUnrounded = false);

}  // namespace uzp::evaluator
