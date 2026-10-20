#include "procedural/admission.h"

#include "uzp_core/document/nodes.h"
#include "uzp_core/manifest/sha256.h"
#include "uzp_core/types/errors.h"

namespace uzp::procedural {

namespace json = core::json;

std::expected<ProceduralRequest, UnsupportedProcedural> RequestFor(const core::ProceduralRef& ref,
                                                                   const UseContext& context,
                                                                   const AssetLibrary& library) {
    ProceduralRequest request;
    try {
        request.asset = core::ParseAssetUrl(ref.asset);
    } catch (const core::ValueError&) {
        return Refused(Refuse(ref.asset, "not a pinned asset URL (uzasset://<family>/<id>@<version>)"));
    }
    if (const AssetRecord* record = library.Find(request.asset)) request.params = record->defaults;
    for (const auto& [name, value] : ref.params) {
        if (value.IsBool()) {
            request.params[name] = int64_t{std::get<bool>(value.data) ? 1 : 0};
        } else if (value.IsInt()) {
            request.params[name] = std::get<int64_t>(value.data);
        } else if (value.IsDouble()) {
            request.params[name] = std::get<double>(value.data);
        } else if (value.IsString()) {
            request.params[name] = std::get<std::string>(value.data);
        } else {
            UnsupportedProcedural refusal = Refuse(ref.asset, "a parameter value is a number, a boolean or a string");
            refusal.field = "params." + name;
            refusal.value = json::WriteCanonical(value);
            refusal.certified = "a number, a boolean or a string";
            return Refused(std::move(refusal));
        }
    }
    request.preset = ref.preset;
    for (const auto& [name, binding] : ref.image_inputs) {
        const auto spec = context.inputs.find(name);
        if (spec == context.inputs.end()) {
            UnsupportedProcedural refusal = Refuse(ref.asset, "an image input without its spec in the use context");
            refusal.field = "inputs." + name;
            refusal.value = binding.sha256;
            refusal.certified = "a bound input whose resolution, format, colour space and channels are known";
            return Refused(std::move(refusal));
        }
        request.inputs[name] = ImageInput{spec->second, binding.sha256};
    }
    request.meshClass = context.meshClass;
    request.uvTiles = context.uvTiles;
    request.output = context.output;
    request.tile = context.tile;
    request.seed = context.seed;
    request.outputId = context.outputId;
    request.settings = context.settings;
    return request;
}

Params EvaluationSettings(const core::ProjectSettings& settings) {
    const core::ColorManagement& colour = settings.color_management;
    return Params{
        {"normal_map_format", std::string(core::ToString(settings.normal_map_format))},
        {"tangent_space", std::string(core::ToString(settings.tangent_space))},
        {"mesh_unit_scale", settings.mesh_unit_scale},
        {"color_management.mode", colour.mode},
        {"color_management.config_hash", colour.config_hash},
        {"color_management.working_space", colour.working_space},
        {"color_management.io_rules_sha256", core::Sha256Hex(json::WriteCanonical(colour.io_rules))},
    };
}

std::expected<IProceduralBackend*, UnsupportedProcedural> Admit(const ProceduralRequest& request,
                                                               const AssetLibrary& library,
                                                               const ProceduralSeam& seam) {
    std::expected<IProceduralBackend*, UnsupportedProcedural> selected = seam.Select(request);
    if (selected) return selected;
    if (library.Find(request.asset) == nullptr) return Refused(library.Resolve(request.asset).error());
    return selected;
}

std::expected<core::RequestOutcome, UnsupportedProcedural> SetEffectProcedural(
    core::Id effect, const core::ProceduralRef& ref, const UseContext& context, const AssetLibrary& library,
    const ProceduralSeam& seam, const SubmitEdit& submit) {
    const std::expected<ProceduralRequest, UnsupportedProcedural> request = RequestFor(ref, context, library);
    if (!request) return Refused(request.error());
    const std::expected<IProceduralBackend*, UnsupportedProcedural> backend = Admit(*request, library, seam);
    if (!backend) return Refused(backend.error());
    return submit([&](core::Edit& edit) {
        core::Effect* target = core::FindEffect(edit.project(), effect);
        if (target == nullptr) throw core::ValueError("no effect " + std::to_string(effect));
        if (target->kind != core::EffectKind::generator && target->kind != core::EffectKind::filter) {
            throw core::ValueError("effect " + std::to_string(effect) + " is not a generator or filter effect");
        }
        target->procedural = ref;
    });
}

}  // namespace uzp::procedural
