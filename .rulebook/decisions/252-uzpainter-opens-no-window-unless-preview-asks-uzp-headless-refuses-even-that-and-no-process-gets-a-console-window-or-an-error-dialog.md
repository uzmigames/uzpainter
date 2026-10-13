# 252. UzPainter opens no window unless `--preview` asks; `UZP_HEADLESS=1` refuses even that, and no process gets a console window or an error dialog

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase2.1_preview-viewport-window, phase2.1_supervisor-ipc-worker

## Context

The owner (2026-10-13): "tem que ter a opção headless pra não abrir janela quando as LLM tiverem usando". While agents drive UzPainter through MCP, `run`, the Assets3D adapter, captures, exports and the tests, no window of any kind may appear.

What the investigation measured on Windows 11 build 26200 (the default terminal is Windows Terminal):

- **One window path.** Only the preview creates a window (`PlatformWindow::Create` in `src/preview/preview.cpp`). Two things reach it: `--preview <file>`, and `--worker --preview`, which the supervisor passes when it was started with `--mcp --preview`. Nothing stopped an agent from asking for it.
- **Consoles.** `UzPainter.exe` is a console-subsystem program with no manifest. A console child started with no creation flags by a process that has no console (a GUI MCP host, `pythonw`, `DETACHED_PROCESS`) gets a new console with a window. Three spawns had that gap:
  - the supervisor's worker spawn (`CREATE_NEW_PROCESS_GROUP` only);
  - the adapter's `subprocess.run` calls in `client.py` and `layer_stack.py`;
  - the layer-stack script's own spawn of the client (`python.exe`, no flags).
- **`CREATE_NO_WINDOW` cannot be unconditional.** It gives the child a windowless console of its own, at about 12 ms per spawn. But such a child cannot write to its parent's console: it exits 120 and the text is lost. The worker's stdout and stderr are the supervisor's stderr, so a supervisor run by hand in a terminal would lose the worker's log.
- **Error dialogs.** Only the worker turned the Windows error dialogs off. In every other role, a fault, or `abort()` with no SIGABRT handler (UCRT's `__fastfail`), reached Windows Error Reporting under the launcher's error mode. A DLL that fails to load before `main()` shows a box that only the parent's error mode prevents, and the adapter waited on that child with no timeout.
- **Tests.** Seven preview tests opened real windows on the owner's desktop. One of them, the decision-227 anti-flicker test, moves its window topmost and samples the screen.
- **Private desktop.** A window on a private desktop (`CreateDesktopW`) is created, shown, painted, resized and closed exactly as on the owner's desktop, also from another process. Only the screen cannot be read there.

The model panel's votes (one round; Grok returned HTTP 503):

| Claim | GPT | Kimi |
|---|---|---|
| 1 Both an environment variable `UZP_HEADLESS=1` (inherited, set once per agent host) and a `--headless` option; a window path is a usage error before anything is opened | PARTLY | AGREE |
| 2 The worker gets `CREATE_NO_WINDOW` only when the supervisor has no console; the adapter always starts UzPainter windowless and under the no-dialog error mode | PARTLY | PARTLY |
| 3 Embed a manifest whose only setting is `consoleAllocationPolicy` `detached` | PARTLY | PARTLY |
| 4a Turn the error dialogs off in `main()` for every role | PARTLY | PARTLY |
| 4b Preview tests on a private desktop; a regression test of a session started without a console | DISAGREE | PARTLY |

Refinements adopted:

- **Claim 1** (Kimi):
  - The message names the switch.
  - `--headless` is accepted only before a command, or among the options of `--mcp` and `--preview`. After `run <script>` it belongs to the script.
- **Claim 2:**
  - (Kimi, GPT) The adapter changes its own error mode only for the call and restores it afterwards. Existing error-mode bits are kept everywhere.
  - (GPT) `GetConsoleProcessList` returns 0 only when it fails. Any failure takes the windowless flag.
- **Claim 3** (GPT): with no console, a child's own console-subsystem children each get a console of their own. UzPainter's own spawns carry `CREATE_NO_WINDOW`. A user script that starts console programs is outside this guarantee.
- **Claim 4a:**
  - (Kimi) Only `_CALL_REPORTFAULT` is cleared. `_WRITE_ABORT_MSG` acts only in the debug CRT.
  - (Kimi) `_set_error_mode(_OUT_TO_STDERR)` is dropped: a console program's `assert` already writes to stderr.
  - `_CrtSetReportMode` is a no-op with the release CRT.
  - (GPT) Load-time DLL failures happen before `main()`. The parent's error mode covers them: the adapter's, and the tests' `pytest_configure`.
- **Claim 4b:**
  - (Kimi) The window recorder is desktop-scoped. The positive test therefore records on the private desktop, where the preview opens. The negative test records on the owner's desktop, where an agent's session runs.
  - (GPT) A console window belongs to conhost or Windows Terminal, outside the process tree. So every UzPainter process also reports its own console from inside. `GetConsoleWindow()` must be NULL: that means a windowless console, or none.
  - (GPT) The screen-sampling test runs only when the owner asks for it (`UZP_SCREEN_TESTS=1`). Skipping it only under headless is not enough.

## Decision

1. **The switch.** No role opens a window unless `--preview` asks for one.
   - `UZP_HEADLESS=1` refuses the preview as a usage error (exit 2) before anything is opened. The message names the switch and this decision.
     - `--preview <file>` refuses before the project or a device (`src/preview/cli.cpp`, `Headless()`).
     - `--mcp --preview` refuses before any worker starts (`python/uzpainter_supervisor/main.py`).
     - `--worker --preview` refuses before the worker creates its pipe (`src/supervisor/worker.cpp`).
   - A leading `--headless`, or `--headless` among `--mcp`'s or `--preview`'s options, sets the variable for the process. Children inherit it: the worker, scripts and their own spawns.
2. **No console window.**
   - **Manifest.** `src/UzPainter.manifest` is embedded through `win32_manifest` (`build.zig`). Its only setting is `consoleAllocationPolicy` `detached`. Started without a console and without flags, `UzPainter.exe` gets no console at all; started from a console, it inherits that console. Windows before 11 24H2 ignores the setting. The manifest has no DPI or supportedOS entries, so outputs do not change.
   - **Worker spawn.** `uzpainter_supervisor.worker.creation_flags()` adds `CREATE_NO_WINDOW` to the worker's process group when the supervisor has no console.
   - **Adapter.**
     - `client.run_painter` starts `UzPainter.exe` with `CREATE_NO_WINDOW`, every standard handle redirected, and the no-dialog error mode for the call.
     - `layer_stack.py` hands the script's own `execute()` the interpreter's `pythonw.exe` (`client.windowless_python`). That is a GUI-subsystem program, which Windows never gives a console.
3. **No error dialog.** `main()` sets these for every role:
   - `SetErrorMode(GetErrorMode() | SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX)`;
   - `WerSetFlags(WER_FAULT_REPORTING_NO_UI)`;
   - `_set_abort_behavior(0, _CALL_REPORTFAULT)`.

   The worker keeps its crash handler and its SIGABRT-to-minidump path, so minidumps are still written.
4. **Tests keep windows off the owner's screen.**
   - `tests/desktop.py` provides `PrivateDesktop`, which starts a process on a desktop nobody sees, and `WindowRecorder`, which records every top-level window shown on a desktop through an out-of-context WinEvent hook.
   - The preview window and settling tests open their windows on a private desktop, with `UZP_HEADLESS` cleared for that child.
   - The anti-flicker test reads the screen. It is skipped unless `UZP_SCREEN_TESTS=1` is set and `UZP_HEADLESS=1` is not.
   - `tests/conftest.py` sets the no-dialog error mode for every program a test starts.

## Consequences

- `tests/supervisor/test_headless.py` checks three things:
  - every refusal (seven command lines);
  - the error mode and the switch reaching `run` (started with `CREATE_DEFAULT_ERROR_MODE`) and an `--mcp --headless` worker;
  - a session started from a parent without a console: MCP with `run_python`, a `base_color` capture, a worker killed and relaunched, an adapter call, and a bare `run` with no creation flags (on 24H2 and later). No process of that tree shows a window, and each reports `GetConsoleWindow()` NULL.
- On the Vulkan worker, the recorder saw 0 windows shown on the whole desktop during the session. Each process reported its console:

  | Process | Console |
  |---|---|
  | Both workers | a windowless one of their own (1 console process, from `CREATE_NO_WINDOW`) |
  | The adapter's `run` | the same |
  | The bare `run` | none (0, from the manifest) |

- `test_standalone_preview_opens_and_closes` proves that an explicit preview still opens its window. The same recorder, on the private desktop, sees that window.
- Owner-only:
  - Set `UZP_HEADLESS=1` in the agent hosts' environments (`.claude/settings.json` `env`, the Codex configuration, the MCP server entries).
  - Run the anti-flicker test by hand with `UZP_SCREEN_TESTS=1`.
- A user script that itself starts console programs from a session without a console may still open their console windows. UzPainter's guarantee covers its own processes.
