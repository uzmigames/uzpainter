#pragma once

// Errors of the document model. The Python binding maps `ValueError` to Python's `ValueError`
// (the error Painter's documentation names for invalid insertions, mask-stack channel
// arguments and anchor cycles; `docs/architecture/04-layer-stack-and-compositing.md` §1-§2,
// `10-python-api.md` §5) and `ManifestError` to `ProjectError`.

#include <stdexcept>
#include <string>

namespace uzp::core {

/// A model rule is violated: the operation is rejected and the document is unchanged.
class ValueError : public std::invalid_argument {
public:
    using std::invalid_argument::invalid_argument;
};

/// A manifest cannot be read: malformed JSON, a missing or mistyped key, an unknown enum
/// member or an unsupported `format_version`. The message starts with the JSON path.
class ManifestError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

}  // namespace uzp::core
