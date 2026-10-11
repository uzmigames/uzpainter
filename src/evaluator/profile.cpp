#include "evaluator/profile.h"

#include <mutex>

#include "evaluator/error.h"

namespace uzp::evaluator {

namespace {

constexpr std::string_view kIdPrefix = "painter-12.1-";

struct Registry {
    std::mutex mutex;
    std::vector<EvaluatorProfile> profiles{
        EvaluatorProfile{std::string(kProfileLayerqLinear), RootComposite::OverBase},
        EvaluatorProfile{std::string(kProfileIsolatedLinear), RootComposite::Isolated},
        EvaluatorProfile{std::string(kProfileIsolatedHalfAlpha), RootComposite::Isolated, true, true},
        EvaluatorProfile{std::string(kProfileIsolatedCoverageWeights), RootComposite::Isolated, true, true,
                         true, true, true, true},
    };
};

Registry& TheRegistry() {
    static Registry registry;
    return registry;
}

}  // namespace

render::Result<EvaluatorProfile> FindProfile(std::string_view id) {
    Registry& registry = TheRegistry();
    std::lock_guard lock(registry.mutex);
    for (const EvaluatorProfile& profile : registry.profiles) {
        if (profile.id == id) return profile;
    }
    return EvalFail(EvalErrorKind::UnknownProfile,
                    "evaluator profile '" + std::string(id) + "' is not registered in this build");
}

render::Result<void> RegisterProfile(EvaluatorProfile profile) {
    if (!profile.id.starts_with(kIdPrefix) || profile.id.size() == kIdPrefix.size()) {
        return EvalFail(EvalErrorKind::InvalidProfile,
                        "profile id '" + profile.id + "' is not painter-12.1-<profile-id>");
    }
    Registry& registry = TheRegistry();
    std::lock_guard lock(registry.mutex);
    for (const EvaluatorProfile& existing : registry.profiles) {
        if (existing.id == profile.id) {
            return EvalFail(EvalErrorKind::InvalidProfile,
                            "profile '" + profile.id + "' is registered already");
        }
    }
    registry.profiles.push_back(std::move(profile));
    return {};
}

std::vector<std::string> RegisteredProfiles() {
    Registry& registry = TheRegistry();
    std::lock_guard lock(registry.mutex);
    std::vector<std::string> ids;
    ids.reserve(registry.profiles.size());
    for (const EvaluatorProfile& profile : registry.profiles) ids.push_back(profile.id);
    return ids;
}

}  // namespace uzp::evaluator
