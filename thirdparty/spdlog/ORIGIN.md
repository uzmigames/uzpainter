# Origin of spdlog

| Field | Value |
|---|---|
| Upstream | https://github.com/gabime/spdlog |
| Release | `v1.17.0` |
| Tag commit | `79524ddd08a4ec981b7fea76afd08ee05f83755d` |
| Archive | https://github.com/gabime/spdlog/archive/refs/tags/v1.17.0.tar.gz |
| Archive SHA-256 | `d8862955c6d74e5846b3f580b1605d2428b11d97a410d86e2fb13e857cd3a744` |
| Archive root | `spdlog-1.17.0/` (stripped; paths below are relative to it) |
| Retrieved | 2026-10-10 |
| Importer | Rulebook task `phase0.2_vendor-thirdparty`, run with `python -m tools.vendoring.import_thirdparty` for UzmiGames |
| Version source | UzEngine commit `380c142e481d`: `runtime/thirdparty/README.md` (spdlog 1.17.0); `scripts/setup.ps1` clones tag `v1.17.0` |
| Licence | MIT (spdlog, `LICENSE`); bundled {fmt} under its MIT-style licence (`include/spdlog/fmt/bundled/fmt.license.rst`) |
| Licence files | `LICENSE`, `include/spdlog/fmt/bundled/fmt.license.rst` (verbatim) |
| Distribution role | shipped: compiled into `UzPainter.exe` |
| Selected features | Compiled library (`SPDLOG_COMPILED_LIB`) with the bundled {fmt} (`SPDLOG_FMT_EXTERNAL` undefined); the seven `src/*.cpp` units are compiled |
| Include directories | `thirdparty/spdlog/include` |

Every file below is byte-equal to the archive member at the same path; none was taken from a UzEngine tree. `MANIFEST.json` records the SHA-256 of each file.

## Licence inventory

- Status: confirmed against the pinned package (licence text, notices, hash, features, role)

## Selected files (113)

- `LICENSE` (1,323 bytes)
- `include/spdlog/async.h` (4,012 bytes)
- `include/spdlog/async_logger-inl.h` (2,817 bytes)
- `include/spdlog/async_logger.h` (2,556 bytes)
- `include/spdlog/cfg/argv.h` (1,219 bytes)
- `include/spdlog/cfg/env.h` (1,007 bytes)
- `include/spdlog/cfg/helpers-inl.h` (3,164 bytes)
- `include/spdlog/cfg/helpers.h` (714 bytes)
- `include/spdlog/common-inl.h` (2,046 bytes)
- `include/spdlog/common.h` (12,569 bytes)
- `include/spdlog/details/backtracer-inl.h` (2,000 bytes)
- `include/spdlog/details/backtracer.h` (1,161 bytes)
- `include/spdlog/details/circular_q.h` (3,377 bytes)
- `include/spdlog/details/console_globals.h` (603 bytes)
- `include/spdlog/details/file_helper-inl.h` (4,669 bytes)
- `include/spdlog/details/file_helper.h` (1,754 bytes)
- `include/spdlog/details/fmt_helper.h` (4,443 bytes)
- `include/spdlog/details/log_msg-inl.h` (1,392 bytes)
- `include/spdlog/details/log_msg.h` (1,200 bytes)
- `include/spdlog/details/log_msg_buffer-inl.h` (1,664 bytes)
- `include/spdlog/details/log_msg_buffer.h` (931 bytes)
- `include/spdlog/details/mpmc_blocking_q.h` (5,280 bytes)
- `include/spdlog/details/null_mutex.h` (930 bytes)
- `include/spdlog/details/os-inl.h` (16,986 bytes)
- `include/spdlog/details/os.h` (4,050 bytes)
- `include/spdlog/details/periodic_worker-inl.h` (616 bytes)
- `include/spdlog/details/periodic_worker.h` (1,809 bytes)
- `include/spdlog/details/registry-inl.h` (8,849 bytes)
- `include/spdlog/details/registry.h` (4,460 bytes)
- `include/spdlog/details/synchronous_factory.h` (751 bytes)
- `include/spdlog/details/tcp_client-windows.h` (7,065 bytes)
- `include/spdlog/details/tcp_client.h` (6,393 bytes)
- `include/spdlog/details/thread_pool-inl.h` (4,270 bytes)
- `include/spdlog/details/thread_pool.h` (3,515 bytes)
- `include/spdlog/details/udp_client-windows.h` (3,122 bytes)
- `include/spdlog/details/udp_client.h` (2,233 bytes)
- `include/spdlog/details/windows_include.h` (180 bytes)
- `include/spdlog/fmt/bin_to_hex.h` (7,362 bytes)
- `include/spdlog/fmt/bundled/args.h` (7,199 bytes)
- `include/spdlog/fmt/bundled/base.h` (105,054 bytes)
- `include/spdlog/fmt/bundled/chrono.h` (77,454 bytes)
- `include/spdlog/fmt/bundled/color.h` (24,145 bytes)
- `include/spdlog/fmt/bundled/compile.h` (20,493 bytes)
- `include/spdlog/fmt/bundled/core.h` (187 bytes)
- `include/spdlog/fmt/bundled/fmt.license.rst` (1,431 bytes)
- `include/spdlog/fmt/bundled/format-inl.h` (81,008 bytes)
- `include/spdlog/fmt/bundled/format.h` (162,666 bytes)
- `include/spdlog/fmt/bundled/os.h` (12,860 bytes)
- `include/spdlog/fmt/bundled/ostream.h` (5,027 bytes)
- `include/spdlog/fmt/bundled/printf.h` (19,991 bytes)
- `include/spdlog/fmt/bundled/ranges.h` (28,126 bytes)
- `include/spdlog/fmt/bundled/std.h` (23,532 bytes)
- `include/spdlog/fmt/bundled/xchar.h` (13,098 bytes)
- `include/spdlog/fmt/chrono.h` (467 bytes)
- `include/spdlog/fmt/compile.h` (475 bytes)
- `include/spdlog/fmt/fmt.h` (712 bytes)
- `include/spdlog/fmt/ostr.h` (470 bytes)
- `include/spdlog/fmt/ranges.h` (467 bytes)
- `include/spdlog/fmt/std.h` (557 bytes)
- `include/spdlog/fmt/xchar.h` (464 bytes)
- `include/spdlog/formatter.h` (463 bytes)
- `include/spdlog/fwd.h` (305 bytes)
- `include/spdlog/logger-inl.h` (6,742 bytes)
- `include/spdlog/logger.h` (13,353 bytes)
- `include/spdlog/mdc.h` (1,493 bytes)
- `include/spdlog/pattern_formatter-inl.h` (47,192 bytes)
- `include/spdlog/pattern_formatter.h` (3,754 bytes)
- `include/spdlog/sinks/android_sink.h` (4,717 bytes)
- `include/spdlog/sinks/ansicolor_sink-inl.h` (5,095 bytes)
- `include/spdlog/sinks/ansicolor_sink.h` (4,031 bytes)
- `include/spdlog/sinks/base_sink-inl.h` (1,804 bytes)
- `include/spdlog/sinks/base_sink.h` (1,600 bytes)
- `include/spdlog/sinks/basic_file_sink-inl.h` (1,387 bytes)
- `include/spdlog/sinks/basic_file_sink.h` (2,312 bytes)
- `include/spdlog/sinks/callback_sink.h` (1,705 bytes)
- `include/spdlog/sinks/daily_file_sink.h` (9,610 bytes)
- `include/spdlog/sinks/dist_sink.h` (2,373 bytes)
- `include/spdlog/sinks/dup_filter_sink.h` (3,225 bytes)
- `include/spdlog/sinks/hourly_file_sink.h` (7,279 bytes)
- `include/spdlog/sinks/kafka_sink.h` (4,445 bytes)
- `include/spdlog/sinks/mongo_sink.h` (4,003 bytes)
- `include/spdlog/sinks/msvc_sink.h` (1,988 bytes)
- `include/spdlog/sinks/null_sink.h` (1,240 bytes)
- `include/spdlog/sinks/ostream_sink.h` (1,222 bytes)
- `include/spdlog/sinks/qt_sinks.h` (12,697 bytes)
- `include/spdlog/sinks/ringbuffer_sink.h` (2,196 bytes)
- `include/spdlog/sinks/rotating_file_sink-inl.h` (6,087 bytes)
- `include/spdlog/sinks/rotating_file_sink.h` (3,348 bytes)
- `include/spdlog/sinks/sink-inl.h` (721 bytes)
- `include/spdlog/sinks/sink.h` (889 bytes)
- `include/spdlog/sinks/stdout_color_sinks-inl.h` (1,431 bytes)
- `include/spdlog/sinks/stdout_color_sinks.h` (1,780 bytes)
- `include/spdlog/sinks/stdout_sinks-inl.h` (4,344 bytes)
- `include/spdlog/sinks/stdout_sinks.h` (2,421 bytes)
- `include/spdlog/sinks/syslog_sink.h` (4,248 bytes)
- `include/spdlog/sinks/systemd_sink.h` (4,868 bytes)
- `include/spdlog/sinks/tcp_sink.h` (2,700 bytes)
- `include/spdlog/sinks/udp_sink.h` (1,850 bytes)
- `include/spdlog/sinks/win_eventlog_sink.h` (8,888 bytes)
- `include/spdlog/sinks/wincolor_sink-inl.h` (7,092 bytes)
- `include/spdlog/sinks/wincolor_sink.h` (2,688 bytes)
- `include/spdlog/spdlog-inl.h` (3,264 bytes)
- `include/spdlog/spdlog.h` (11,866 bytes)
- `include/spdlog/stopwatch.h` (1,865 bytes)
- `include/spdlog/tweakme.h` (6,610 bytes)
- `include/spdlog/version.h` (417 bytes)
- `src/async.cpp` (394 bytes)
- `src/bundled_fmtlib_format.cpp` (1,417 bytes)
- `src/cfg.cpp` (275 bytes)
- `src/color_sinks.cpp` (3,137 bytes)
- `src/file_sinks.cpp` (797 bytes)
- `src/spdlog.cpp` (1,134 bytes)
- `src/stdout_sinks.cpp` (2,014 bytes)

## Comparison with UzEngine's copy

UzEngine `runtime/thirdparty/spdlog` at commit `380c142e481d56fe16b045f63315b42359e86a7d`, read from the commit's blobs (`git cat-file`), compared byte for byte with the archive file at the same relative path.

| Result | Files |
|---|---|
| identical | 121 |
| line-endings | 3 |
| different | 0 |
| uzengine-only | 0 |
| selected but absent from UzEngine's tree | 0 |

Line endings only (equal after CRLF -> LF; UzEngine's blob stores LF where the upstream file has CRLF (`core.autocrlf=true` normalised the text on commit)):

- `INSTALL`
- `README.md`
- `cmake/spdlogConfig.cmake.in`

Identical files:

- `.git-blame-ignore-revs`
- `CMakeLists.txt`
- `LICENSE`
- `cmake/ide.cmake`
- `cmake/pch.h.in`
- `cmake/spdlog.pc.in`
- `cmake/spdlogCPack.cmake`
- `cmake/utils.cmake`
- `cmake/version.rc.in`
- `include/spdlog/async.h`
- `include/spdlog/async_logger-inl.h`
- `include/spdlog/async_logger.h`
- `include/spdlog/cfg/argv.h`
- `include/spdlog/cfg/env.h`
- `include/spdlog/cfg/helpers-inl.h`
- `include/spdlog/cfg/helpers.h`
- `include/spdlog/common-inl.h`
- `include/spdlog/common.h`
- `include/spdlog/details/backtracer-inl.h`
- `include/spdlog/details/backtracer.h`
- `include/spdlog/details/circular_q.h`
- `include/spdlog/details/console_globals.h`
- `include/spdlog/details/file_helper-inl.h`
- `include/spdlog/details/file_helper.h`
- `include/spdlog/details/fmt_helper.h`
- `include/spdlog/details/log_msg-inl.h`
- `include/spdlog/details/log_msg.h`
- `include/spdlog/details/log_msg_buffer-inl.h`
- `include/spdlog/details/log_msg_buffer.h`
- `include/spdlog/details/mpmc_blocking_q.h`
- `include/spdlog/details/null_mutex.h`
- `include/spdlog/details/os-inl.h`
- `include/spdlog/details/os.h`
- `include/spdlog/details/periodic_worker-inl.h`
- `include/spdlog/details/periodic_worker.h`
- `include/spdlog/details/registry-inl.h`
- `include/spdlog/details/registry.h`
- `include/spdlog/details/synchronous_factory.h`
- `include/spdlog/details/tcp_client-windows.h`
- `include/spdlog/details/tcp_client.h`
- `include/spdlog/details/thread_pool-inl.h`
- `include/spdlog/details/thread_pool.h`
- `include/spdlog/details/udp_client-windows.h`
- `include/spdlog/details/udp_client.h`
- `include/spdlog/details/windows_include.h`
- `include/spdlog/fmt/bin_to_hex.h`
- `include/spdlog/fmt/bundled/args.h`
- `include/spdlog/fmt/bundled/base.h`
- `include/spdlog/fmt/bundled/chrono.h`
- `include/spdlog/fmt/bundled/color.h`
- `include/spdlog/fmt/bundled/compile.h`
- `include/spdlog/fmt/bundled/core.h`
- `include/spdlog/fmt/bundled/fmt.license.rst`
- `include/spdlog/fmt/bundled/format-inl.h`
- `include/spdlog/fmt/bundled/format.h`
- `include/spdlog/fmt/bundled/os.h`
- `include/spdlog/fmt/bundled/ostream.h`
- `include/spdlog/fmt/bundled/printf.h`
- `include/spdlog/fmt/bundled/ranges.h`
- `include/spdlog/fmt/bundled/std.h`
- `include/spdlog/fmt/bundled/xchar.h`
- `include/spdlog/fmt/chrono.h`
- `include/spdlog/fmt/compile.h`
- `include/spdlog/fmt/fmt.h`
- `include/spdlog/fmt/ostr.h`
- `include/spdlog/fmt/ranges.h`
- `include/spdlog/fmt/std.h`
- `include/spdlog/fmt/xchar.h`
- `include/spdlog/formatter.h`
- `include/spdlog/fwd.h`
- `include/spdlog/logger-inl.h`
- `include/spdlog/logger.h`
- `include/spdlog/mdc.h`
- `include/spdlog/pattern_formatter-inl.h`
- `include/spdlog/pattern_formatter.h`
- `include/spdlog/sinks/android_sink.h`
- `include/spdlog/sinks/ansicolor_sink-inl.h`
- `include/spdlog/sinks/ansicolor_sink.h`
- `include/spdlog/sinks/base_sink-inl.h`
- `include/spdlog/sinks/base_sink.h`
- `include/spdlog/sinks/basic_file_sink-inl.h`
- `include/spdlog/sinks/basic_file_sink.h`
- `include/spdlog/sinks/callback_sink.h`
- `include/spdlog/sinks/daily_file_sink.h`
- `include/spdlog/sinks/dist_sink.h`
- `include/spdlog/sinks/dup_filter_sink.h`
- `include/spdlog/sinks/hourly_file_sink.h`
- `include/spdlog/sinks/kafka_sink.h`
- `include/spdlog/sinks/mongo_sink.h`
- `include/spdlog/sinks/msvc_sink.h`
- `include/spdlog/sinks/null_sink.h`
- `include/spdlog/sinks/ostream_sink.h`
- `include/spdlog/sinks/qt_sinks.h`
- `include/spdlog/sinks/ringbuffer_sink.h`
- `include/spdlog/sinks/rotating_file_sink-inl.h`
- `include/spdlog/sinks/rotating_file_sink.h`
- `include/spdlog/sinks/sink-inl.h`
- `include/spdlog/sinks/sink.h`
- `include/spdlog/sinks/stdout_color_sinks-inl.h`
- `include/spdlog/sinks/stdout_color_sinks.h`
- `include/spdlog/sinks/stdout_sinks-inl.h`
- `include/spdlog/sinks/stdout_sinks.h`
- `include/spdlog/sinks/syslog_sink.h`
- `include/spdlog/sinks/systemd_sink.h`
- `include/spdlog/sinks/tcp_sink.h`
- `include/spdlog/sinks/udp_sink.h`
- `include/spdlog/sinks/win_eventlog_sink.h`
- `include/spdlog/sinks/wincolor_sink-inl.h`
- `include/spdlog/sinks/wincolor_sink.h`
- `include/spdlog/spdlog-inl.h`
- `include/spdlog/spdlog.h`
- `include/spdlog/stopwatch.h`
- `include/spdlog/tweakme.h`
- `include/spdlog/version.h`
- `src/async.cpp`
- `src/bundled_fmtlib_format.cpp`
- `src/cfg.cpp`
- `src/color_sinks.cpp`
- `src/file_sinks.cpp`
- `src/spdlog.cpp`
- `src/stdout_sinks.cpp`

UzEngine patches: none under this library at the commit.
