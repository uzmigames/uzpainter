# Origin of pybind11

| Field | Value |
|---|---|
| Upstream | https://github.com/pybind/pybind11 |
| Release | `v3.1.0` |
| Tag commit | `97bf890db679505a14dfe547a5e77bb2bd05dc90` |
| Archive | https://github.com/pybind/pybind11/archive/refs/tags/v3.1.0.tar.gz |
| Archive SHA-256 | `ef712655692a2e9bf7bb7874c022564a45f91d847ddee987e720cd9e28849665` |
| Archive root | `pybind11-3.1.0/` (stripped; paths below are relative to it) |
| Retrieved | 2026-10-10 |
| Importer | Rulebook task `phase0.7_toolchain-cpython`, run with `python -m tools.vendoring.import_thirdparty` for UzmiGames |
| Version source | UzPainter's selection: the newest pybind11 release on the retrieval date (tag `v3.1.0`, published 2026-08-06; `docs/architecture/10-python-api.md` §1) |
| Licence | BSD-3-Clause (`LICENSE`) |
| Licence files | `LICENSE` (verbatim) |
| Distribution role | shipped: header-only, compiled into `UzPainter.exe` (the `uzpainter` module and the embedding) |
| Selected features | The headers `include/pybind11/` (embedding through `pybind11/embed.h`); no CMake files, tests, docs or the `pybind11` Python package |
| Include directories | `thirdparty/pybind11/include` |

Every file below is byte-equal to the archive member at the same path; none was taken from a UzEngine tree. `MANIFEST.json` records the SHA-256 of each file.

## Licence inventory

- Status: confirmed against the pinned package (licence text, notices, hash, features, role)

## Selected files (56)

- `LICENSE` (1,684 bytes)
- `include/pybind11/attr.h` (26,479 bytes)
- `include/pybind11/buffer_info.h` (7,838 bytes)
- `include/pybind11/cast.h` (96,849 bytes)
- `include/pybind11/chrono.h` (8,605 bytes)
- `include/pybind11/common.h` (120 bytes)
- `include/pybind11/complex.h` (3,055 bytes)
- `include/pybind11/conduit/README.txt` (298 bytes)
- `include/pybind11/conduit/pybind11_conduit_v1.h` (4,153 bytes)
- `include/pybind11/conduit/pybind11_platform_abi_id.h` (3,991 bytes)
- `include/pybind11/conduit/wrap_include_python_h.h` (2,069 bytes)
- `include/pybind11/critical_section.h` (1,610 bytes)
- `include/pybind11/detail/argument_vector.h` (13,896 bytes)
- `include/pybind11/detail/class.h` (32,465 bytes)
- `include/pybind11/detail/common.h` (63,589 bytes)
- `include/pybind11/detail/cpp_conduit.h` (2,545 bytes)
- `include/pybind11/detail/descr.h` (8,228 bytes)
- `include/pybind11/detail/dynamic_raw_ptr_cast_if_possible.h` (1,176 bytes)
- `include/pybind11/detail/exception_translation.h` (2,593 bytes)
- `include/pybind11/detail/function_record_pyobject.h` (7,772 bytes)
- `include/pybind11/detail/function_ref.h` (3,729 bytes)
- `include/pybind11/detail/holder_caster_foreign_helpers.h` (3,927 bytes)
- `include/pybind11/detail/init.h` (23,967 bytes)
- `include/pybind11/detail/internals.h` (45,731 bytes)
- `include/pybind11/detail/native_enum_data.h` (8,403 bytes)
- `include/pybind11/detail/pybind11_namespace_macros.h` (3,574 bytes)
- `include/pybind11/detail/struct_smart_holder.h` (16,425 bytes)
- `include/pybind11/detail/type_caster_base.h` (72,331 bytes)
- `include/pybind11/detail/typeid.h` (1,625 bytes)
- `include/pybind11/detail/using_smart_holder.h` (540 bytes)
- `include/pybind11/detail/value_and_holder.h` (3,733 bytes)
- `include/pybind11/eigen.h` (316 bytes)
- `include/pybind11/eigen/common.h` (378 bytes)
- `include/pybind11/eigen/matrix.h` (32,590 bytes)
- `include/pybind11/eigen/tensor.h` (18,640 bytes)
- `include/pybind11/embed.h` (10,226 bytes)
- `include/pybind11/eval.h` (4,800 bytes)
- `include/pybind11/functional.h` (5,111 bytes)
- `include/pybind11/gil.h` (6,945 bytes)
- `include/pybind11/gil_safe_call_once.h` (13,103 bytes)
- `include/pybind11/gil_simple.h` (1,185 bytes)
- `include/pybind11/iostream.h` (10,438 bytes)
- `include/pybind11/native_enum.h` (2,723 bytes)
- `include/pybind11/numpy.h` (94,985 bytes)
- `include/pybind11/operators.h` (9,103 bytes)
- `include/pybind11/options.h` (2,734 bytes)
- `include/pybind11/pybind11.h` (181,286 bytes)
- `include/pybind11/pytypes.h` (104,244 bytes)
- `include/pybind11/stl.h` (24,742 bytes)
- `include/pybind11/stl/filesystem.h` (4,074 bytes)
- `include/pybind11/stl_bind.h` (30,067 bytes)
- `include/pybind11/subinterpreter.h` (19,423 bytes)
- `include/pybind11/trampoline_self_life_support.h` (2,673 bytes)
- `include/pybind11/type_caster_pyobject_ptr.h` (1,929 bytes)
- `include/pybind11/typing.h` (8,785 bytes)
- `include/pybind11/warnings.h` (2,368 bytes)

## Comparison with UzEngine's copy

UzEngine's tree at the commit has no pybind11, so there is nothing to compare.
