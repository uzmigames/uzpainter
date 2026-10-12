// The recipe dump of the open project and the application's recipe host (recipe.h).

#include "python/recipe.h"

#include <memory>
#include <mutex>
#include <string>

#include "evaluator/templates.h"
#include "python/session.h"
#include "uzp_core/types/errors.h"

namespace uzp::python {

core::RecipeHost HostRecipe() {
    struct Library {
        std::once_flag once;
        std::unique_ptr<evaluator::TemplateLibrary> templates;
        std::string error;
    };
    auto library = std::make_shared<Library>();
    core::RecipeHost host;
    host.app_version = kAppVersion;
    host.base_value = [library](std::string_view template_id, core::ChannelType type) {
        std::call_once(library->once, [&] {
            try {
                library->templates = std::make_unique<evaluator::TemplateLibrary>(
                    evaluator::TemplateLibrary::Load(evaluator::TemplateLibrary::DefaultDirectory()));
            } catch (const std::exception& error) {
                library->error = error.what();
            }
        });
        if (!library->templates) throw core::ValueError("recipe: the project templates do not load: " + library->error);
        const render::Result<std::array<float, 3>> base = library->templates->BaseValue(template_id, type);
        if (!base) throw core::ValueError("recipe: " + base.error().reason);
        return *base;
    };
    return host;
}

core::json::Object DumpCurrentRecipe() {
    const core::Snapshot snapshot = Session::Get().Current()->document->snapshot();
    return core::DumpRecipe(*snapshot.project, snapshot.revision, HostRecipe());
}

}  // namespace uzp::python
