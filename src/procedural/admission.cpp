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
        const auto parsed = ParamFromJson(value);
        if (!parsed) {
            UnsupportedProcedural refusal = Refuse(ref.asset, parsed.error());
            refusal.field = "params." + name;
            refusal.value = json::WriteCanonical(value);
            refusal.certified = "a finite scalar, a 2-4 component numeric vector or a tagged working-space color";
            return Refused(std::move(refusal));
        }
        request.params[name] = *parsed;
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
    if (context.content) {
        const std::string content(kContentInput);
        if (const auto bound = ref.image_inputs.find(content); bound != ref.image_inputs.end()) {
            UnsupportedProcedural refusal =
                Refuse(ref.asset, "the content input is the layer content at the filter's position, not a bound input");
            refusal.field = "inputs." + content;
            refusal.value = bound->second.sha256;
            refusal.certified = "the use context's content";
            return Refused(std::move(refusal));
        }
        request.inputs[content] = *context.content;
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

Params EvaluationSettings(const core::Project& project) {
    Params settings = EvaluationSettings(project.settings);
    settings["mesh.sha256"] = project.mesh ? project.mesh->resource : std::string();
    if (project.mesh) {
        json::Object geometry = project.mesh->import_report;
        // Match the evaluator's mesh identity: external buffers and import settings matter;
        // the source file's name and size are metadata, not geometry.
        geometry.erase("source");
        if (!geometry.empty()) settings["mesh.import_report_sha256"] = core::Sha256Hex(json::WriteCanonical(geometry));
    }
    return settings;
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
