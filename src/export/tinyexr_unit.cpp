// The one translation unit of tinyexr's implementation (`thirdparty/tinyexr/`, decision 089),
// over the vendored zlib instead of miniz. It is third-party code: build.zig compiles it with the
// third-party flags, not UzPainter's warning flags. `exr_writer.cpp` is its only user.

#include <zlib.h>

#define TINYEXR_USE_MINIZ 0
#define TINYEXR_IMPLEMENTATION
#include "tinyexr.h"
