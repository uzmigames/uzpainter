#pragma once

// The authored baking table `assets/defaults/baking.json` (phase3.1_baker-request-model items 2.8
// and 2.9, decision 323), embedded into the build (decision 147: `EmbedInputs` keys the object on
// the table's bytes).

#include <string_view>

namespace uzp::bake {

/// The bytes of `assets/defaults/baking.json`.
std::string_view BakingDefaultsText();

}  // namespace uzp::bake
