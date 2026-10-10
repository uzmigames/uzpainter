#pragma once

// Persistent 64-bit identities (`docs/architecture/03-project-model.md` §1): every node, texture
// set, stack, UV tile and resource entry carries an id that is written to the manifest and
// survives save/reopen. Ids come from the project's counter (`Project::next_id`), never from
// names, so two nodes with the same name keep distinct ids. Valid ids are 1..INT64_MAX (they
// stay exact in every JSON reader that holds signed 64-bit integers); 0 means "no id".

#include <cstdint>

namespace uzp::core {

using Id = std::uint64_t;

inline constexpr Id kNoId = 0;
inline constexpr Id kMaxId = 0x7FFF'FFFF'FFFF'FFFFull;

}  // namespace uzp::core
