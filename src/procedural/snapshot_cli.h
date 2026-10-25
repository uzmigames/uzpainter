#pragma once

#include <cstdio>
#include <string>
#include <vector>

namespace uzp::procedural {
int RunSnapshotCommand(const std::vector<std::string>& args, std::FILE* out, std::FILE* err);
/// `assets bind-snapshot <file.uzp> --request <bind.json>` (docs/procedural-snapshots.md).
int RunBindSnapshotCommand(const std::vector<std::string>& args, std::FILE* out, std::FILE* err);
}
