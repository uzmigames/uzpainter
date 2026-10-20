#include "bake/baking_catalog.h"

namespace uzp::bake {

namespace {

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wc23-extensions"
constexpr char kBakingDefaults[] = {
#embed "../../assets/defaults/baking.json"
};
#pragma clang diagnostic pop

}  // namespace

std::string_view BakingDefaultsText() { return {kBakingDefaults, sizeof(kBakingDefaults)}; }

}  // namespace uzp::bake
