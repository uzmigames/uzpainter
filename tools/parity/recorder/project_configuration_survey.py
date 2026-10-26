"""Private UI selector survey in a newly owned Painter; never a Filter capture or admission.

Runtime needs separate coordinator release. The only authored scene is the public plane
with recipe A's OpenGL/128 creation arguments. Configuration mode navigates and cancels;
it never applies settings, exports, saves a project, or attaches to an existing Painter.

Sources: A-PYDOC project module and A-HELP-GUIDE, retrieved 2026-10-25:
https://experienceleague.adobe.com/en/docs/substance-3d-dev/painter-python/api/substancepainter-package/project
https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/interface/project-configuration
Decision 029 admits out-of-process UI Automation and private screenshots. Project UUID
checks supplement, never replace, the launcher's process/start identity and UI HWND/PID guards.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import ntpath
import subprocess
import sys
import time
import traceback
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Protocol

from tools.parity.preserve_diagnostic_evidence import file_fingerprint, private_path
from tools.parity.recorder.launcher import PainterLauncher, endpoint_answers
from tools.parity.recorder.painter_ui import PainterUi, menu_label
from tools.parity.recorder.session import HttpTransport, IdentityChanged, PainterSession
from tools.parity.schemas import REPO_ROOT

COLLAB = Path("E:/UzmiGames/Assets3D/Docs/Colaboracao/scripts/collab.py")
COLLAB_ROOT = COLLAB.parent.parent
MCP_BRIDGE = (
    "E:/UzmiGames/Assets3D/Tools/SubstancePainterMCP/.venv/Scripts/substance-painter-mcp.exe"
)
PLANE = REPO_ROOT / "parity/fixtures/meshes/plane.obj"
PLANE_SHA256 = "7d3c5f616c2abf4b06050434fa943d19dcb15ec998245a211d1d4ca7e95197fe"
BUILDERS = {
    "zig",
    "clang",
    "clang++",
    "clang-cl",
    "lld",
    "lld-link",
    "link",
    "cl",
    "cmake",
    "ninja",
    "msbuild",
}
GIB = 1024**3
CREATE = "substance_painter.project.create"
CREATE_ARGS = {"mesh": "plane", "normal_map_format": "OpenGL", "default_texture_resolution": 128}
OWNERSHIP_MARKER = "UZP_SURVEY_OWNERSHIP_LOST"
PHYSICAL_SIZE_SECTION = (
    "QApplication.ProjectSettingsDialog.scroll_area.qt_scrollarea_viewport."
    "scroll_area_content.advanced_settings_section.content.physical_size_section"
)
PHYSICAL_SIZE_TITLE = PHYSICAL_SIZE_SECTION + ".groupTitle.titleButton"


class OwnershipLost(ValueError):
    """Positive evidence of changed ownership; preserve process and any owned lock."""


def require_owned(ok: bool, reason: str) -> None:
    if not ok:
        raise OwnershipLost(reason)


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


@dataclass(frozen=True)
class Request:
    painter_exe: Path
    output_prefix: Path
    configuration: bool = False
    min_free_memory_gib: float = 8.0
    min_commit_headroom_gib: float = 16.0
    physical_size: bool = False


@dataclass(frozen=True)
class Host:
    physical_free: int
    commit_free: int
    processes: list[dict[str, Any]]


def host_state() -> Host:
    class Memory(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
            (name, ctypes.c_ulonglong)
            for name in (
                "total_physical",
                "free_physical",
                "total_commit",
                "free_commit",
                "total_virtual",
                "free_virtual",
                "extended",
            )
        ]

    memory = Memory()
    memory.length = ctypes.sizeof(memory)
    require(
        bool(ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory))),
        "memory query failed",
    )
    command = (
        "@(Get-CimInstance Win32_Process | ForEach-Object { "
        "[pscustomobject]@{pid=[int]$_.ProcessId;name=$_.Name;image_path=$_.ExecutablePath;"
        "started=if ($_.CreationDate) {$_.CreationDate.ToUniversalTime().ToString('o')} "
        "else {$null}} }) | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    processes = json.loads(result.stdout)
    require(type(processes) is list, "process census unavailable")
    return Host(int(memory.free_physical), int(memory.free_commit), processes)


def painters(host: Host) -> list[dict[str, Any]]:
    def known_bridge(process: dict[str, Any]) -> bool:
        path = process.get("image_path")
        return (
            str(process["name"]).lower() == "substance-painter-mcp.exe"
            and isinstance(path, str)
            and ntpath.normcase(ntpath.normpath(path))
            == ntpath.normcase(ntpath.normpath(MCP_BRIDGE))
        )

    # Missing paths and unfamiliar Painter-like names remain conservative blockers.
    return [
        p for p in host.processes if "painter" in str(p["name"]).lower() and not known_bridge(p)
    ]


def resources_available(host: Host, request: Request) -> None:
    for threshold in (request.min_free_memory_gib, request.min_commit_headroom_gib):
        require(math.isfinite(threshold) and threshold > 0, "invalid memory threshold")
    require(host.physical_free >= request.min_free_memory_gib * GIB, "insufficient physical memory")
    require(
        host.commit_free >= request.min_commit_headroom_gib * GIB, "insufficient commit headroom"
    )
    require(
        not any(Path(str(p["name"])).stem.lower() in BUILDERS for p in host.processes),
        "native builder active",
    )


class Evidence:
    def __init__(self, prefix: Path, stack: ExitStack, *, physical_size: bool = False) -> None:
        prefix = private_path(prefix, REPO_ROOT)
        require(
            prefix.parent.is_dir() and bool(prefix.name), "existing private output parent required"
        )
        self.paths: dict[str, Path] = {}
        self.handles: dict[str, BinaryIO] = {}
        artifacts = [
            ("report", ".report.json"),
            ("log", ".events.jsonl"),
            ("main", ".main.json"),
            ("main_image", ".main.png"),
            ("menu", ".menu.json"),
            ("configuration", ".configuration.json"),
            ("configuration_image", ".configuration.png"),
        ]
        if physical_size:
            artifacts += [
                ("physical_size", ".physical-size.json"),
                ("physical_size_image", ".physical-size.png"),
            ]
        for name, suffix in artifacts:
            path = private_path(prefix.with_name(prefix.name + suffix), REPO_ROOT)
            self.paths[name] = path
            self.handles[name] = stack.enter_context(path.open("xb"))

    def json(self, name: str, value: Any) -> None:
        data = (json.dumps(value, ensure_ascii=True, sort_keys=True) + "\n").encode()
        require(self.handles[name].write(data) == len(data), "short evidence write")
        self.handles[name].flush()

    def log(self, event: str, **fields: Any) -> None:
        self.json("log", {"event": event, **fields})

    def image(self, name: str, ui: PainterUi, handle: int) -> None:
        frame, _ = ui.print_window(handle)
        frame.save(self.handles[name], format="PNG")
        self.handles[name].flush()


class LogSink(Protocol):
    def log(self, event: str, **fields: Any) -> None: ...


class Lock:
    def __init__(
        self,
        evidence: LogSink,
        *,
        owner: str = "Astra/uzpainter-project-config-survey",
        task: str = "Codex private authored Project Configuration UI selector survey",
    ) -> None:
        require(
            owner.split("/", 1)[0] in {"Astra", "Claude", "Todos"}, "canonical lock owner required"
        )
        self.evidence = evidence
        self.owner = owner
        self.task = task
        self.token: str | None = None

    def command(self, action: str) -> dict[str, Any]:
        args = [str(COLLAB), "--root", str(COLLAB_ROOT), "lock", action, "--resource", "painter"]
        if action == "acquire":
            args += [
                "--owner",
                self.owner,
                "--task",
                self.task,
            ]
        elif action == "release":
            require(self.token is not None, "no owned lock token")
            args += ["--owner", self.owner, "--token", str(self.token)]
        # The canonical CLI receives its arguments via stdin, never a token in OS argv.
        wrapper = (
            "import json,runpy,sys; sys.argv=json.load(sys.stdin); "
            "runpy.run_path(sys.argv[0],run_name='__main__')"
        )
        result = subprocess.run(
            [sys.executable, "-c", wrapper],
            input=json.dumps(args),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.evidence.log(
            "lock",
            action=action,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
        envelope = json.loads(result.stdout)
        require(type(envelope) is dict, "invalid lock envelope")
        reply = envelope.get("result")
        if action == "acquire" and isinstance(reply, dict) and isinstance(reply.get("token"), str):
            self.token = reply["token"]
        require(result.returncode == 0 and envelope.get("ok") is True, "lock CLI refused")
        require(set(envelope) == {"ok", "result"} and type(reply) is dict, "invalid lock reply")
        assert isinstance(reply, dict)
        return reply

    def acquire(self) -> None:
        require(self.command("status").get("occupied") is False, "Painter lock occupied")
        result = self.command("acquire")
        require(
            self.token is not None and result.get("owner") == self.owner,
            "lock acquisition incomplete",
        )
        require(
            result.get("resource_committed") is True and result.get("canonical_committed") is True,
            "lock audit incomplete",
        )
        self.verify()

    def verify(self) -> None:
        require(self.token is not None, "Painter lock not owned")
        assert self.token is not None
        state = self.command("status")
        require_owned(
            state.get("occupied") is True
            and state.get("owner") == self.owner
            and state.get("token_hash") == hashlib.sha256(self.token.encode()).hexdigest(),
            "Painter lock ownership changed",
        )

    def release(self) -> None:
        if self.token is not None:
            self.verify()
            result = self.command("release")
            require(
                result.get("released") == "painter"
                and result.get("resource_committed") is True
                and result.get("canonical_committed") is True,
                "lock release incomplete",
            )
            self.token = None


class OwnedTransport:
    def __init__(
        self, raw: HttpTransport, launcher: PainterLauncher, lock: Lock, started: str
    ) -> None:
        self.raw, self.launcher, self.lock, self.started = raw, launcher, lock, started
        self.project_uuid: str | None = None
        self.closed_expected = False

    def claim_created(self) -> str:
        """Claim only the UUID captured by the recorder's own CREATE operation."""
        self.closed_expected = False
        try:
            marker = self.run("dict(uzp_recorder['OWN_PROJECT_CREATION'])")
            require_owned(
                isinstance(marker, dict)
                and marker.get("pending") is True
                and isinstance(marker.get("uuid"), str)
                and bool(marker["uuid"]),
                "owned creation UUID unavailable",
            )
            self.project_uuid = marker["uuid"]
            self.verify()
        except Exception as error:
            raise OwnershipLost("created project identity unavailable or changed") from error
        assert self.project_uuid is not None
        return self.project_uuid

    def verify_process(self) -> None:
        host = host_state()
        current = painters(host)
        require_owned(
            len(current) == 1
            and current[0]["pid"] == self.launcher.pid
            and current[0]["started"] == self.started,
            "Painter process identity changed",
        )

    def verify(self) -> None:
        self.lock.verify()
        self.verify_process()
        require_owned(
            self.raw.run("__import__('os').getpid()") == self.launcher.pid,
            "remote endpoint belongs to another process",
        )
        if self.project_uuid is not None:
            require_owned(
                self.raw.run(
                    "str(__import__('substance_painter.project',fromlist=['get_uuid']).get_uuid())"
                )
                == self.project_uuid,
                "owned project changed",
            )
        if self.closed_expected:
            require_owned(
                self.raw.run(
                    "__import__('substance_painter.project',fromlist=['is_open']).is_open()"
                )
                is False,
                "another project opened after owned close",
            )

    def run(self, code: str) -> Any:
        self.verify()
        condition = f"__import__('os').getpid() == {self.launcher.pid}"
        if self.project_uuid is not None:
            condition += (
                " and str(__import__('substance_painter.project',fromlist=['get_uuid'])"
                f".get_uuid()) == {self.project_uuid!r}"
            )
        if self.closed_expected:
            condition += (
                " and not __import__('substance_painter.project',fromlist=['is_open']).is_open()"
            )
        # Check again in the request that executes the operation, not only a prior request.
        try:
            compile(code, "<owned-painter>", "eval")
        except SyntaxError:
            guarded = f"if not ({condition}):\n    raise RuntimeError({OWNERSHIP_MARKER!r})\n{code}"
        else:
            guarded = (
                f"({code}) if ({condition}) else "
                f"(_ for _ in ()).throw(RuntimeError({OWNERSHIP_MARKER!r}))"
            )
        try:
            return self.raw.run(guarded)
        except Exception as error:
            if OWNERSHIP_MARKER in str(error):
                raise OwnershipLost("ownership changed inside remote request") from error
            raise


def close_owned(
    launcher: PainterLauncher, session: PainterSession | None, owned: OwnedTransport
) -> None:
    owned.verify()
    if owned.project_uuid is not None:
        require(session is not None, "owned project has no session")
        assert session is not None
        try:
            session.verify_identity()
        except IdentityChanged as error:
            raise OwnershipLost("Painter session identity changed") from error
        # UUID and PID stay in the SAME request that closes the project.
        session.call("close_project")
        owned.project_uuid = None
        owned.closed_expected = True
        session.wait_closed(timeout_s=15)
    else:
        require_owned(
            owned.run("__import__('substance_painter.project',fromlist=['is_open']).is_open()")
            is False,
            "unclaimed project in owned process",
        )
    owned.verify()
    launcher.stop()


def cleanup_owned(
    launcher: PainterLauncher,
    session: PainterSession | None,
    owned: OwnedTransport | None,
    lock: Lock,
    report: dict[str, Any],
    *,
    preserve: bool = False,
) -> None:
    """Close only owned projects; retain process and lock on positive ownership loss."""
    try:
        if preserve:
            raise OwnershipLost("ownership loss already observed; cleanup withheld")
        if owned is not None:
            close_owned(launcher, session, owned)
        else:
            launcher.stop()
        report["cleanup"] = "owned_process_stopped"
    except OwnershipLost:
        preserve = True
        report["status"] = "refused"
        report["cleanup_error"] = traceback.format_exc()
    except Exception:
        report["status"] = "refused"
        report["cleanup_error"] = traceback.format_exc()
        try:
            if owned is not None:
                owned.verify_process()
            launcher.end_process()
            report["cleanup"] = "owned_process_stopped_after_failure"
        except Exception:
            preserve = True
            report["process_stop_error"] = traceback.format_exc()
    if preserve:
        report["cleanup"] = "ownership_blocker_no_close_or_termination"
        report["preserved_process"] = True
        try:
            lock.verify()
            report["preserved_lock"] = True
        except Exception:
            report["preserved_lock"] = False
            report["lock_ownership_error"] = traceback.format_exc()
    else:
        try:
            lock.release()
        except Exception:
            report["status"] = "refused"
            report["lock_release_error"] = traceback.format_exc()


def unique(items: list[Any], reason: str) -> Any:
    require(len(items) == 1, reason)
    return items[0]


def visible_values(root: Any) -> list[dict[str, Any]]:
    values = []
    for element in [root, *root.descendants()]:
        if not element.is_visible():
            continue
        info = element.element_info
        row: dict[str, Any] = {
            "label": element.window_text(),
            "type": info.control_type,
            "automation_id": info.automation_id,
            "enabled": bool(element.is_enabled()),
        }
        for field, interface, attribute in (
            ("value", "iface_value", "CurrentValue"),
            ("toggle", "iface_toggle", "CurrentToggleState"),
            ("selected", "iface_selection_item", "CurrentIsSelected"),
        ):
            try:
                row[field] = getattr(getattr(element, interface), attribute)
            except Exception as error:
                row[field] = {"unavailable": repr(error).split("(", 1)[0]}
        values.append(row)
    return values


def navigation_state(ui: PainterUi, element: Any) -> dict[str, Any]:
    """Read coordinate/ownership diagnostics and UIA pattern availability; never navigate."""
    from ctypes import wintypes

    import win32gui
    import win32process  # type: ignore[import-untyped]

    def observed(read: Any) -> Any:
        try:
            return read()
        except Exception as error:
            return {"unavailable": repr(error).split("(", 1)[0]}

    def window(handle: int) -> dict[str, Any]:
        if not handle:
            return {"hwnd": 0}
        return {
            "hwnd": handle,
            "pid": win32process.GetWindowThreadProcessId(handle)[1],
            "root": win32gui.GetAncestor(handle, 2),
            "rect": list(win32gui.GetWindowRect(handle)),
            "class": win32gui.GetClassName(handle),
            "enabled": bool(win32gui.IsWindowEnabled(handle)),
            "visible": bool(win32gui.IsWindowVisible(handle)),
        }

    box = element.rectangle()
    point = ((box.left + box.right) // 2, (box.top + box.bottom) // 2)
    ancestry = []
    current = element
    reached_main = False
    for _ in range(32):
        if current is None:
            break
        handle = int(current.handle or 0)
        ancestry.append(
            {
                "hwnd": handle,
                "pid": current.process_id(),
                "control_type": current.element_info.control_type,
                "class": current.element_info.class_name,
            }
        )
        if handle == ui.window.handle:
            reached_main = True
            break
        current = current.parent()

    def dpi() -> dict[str, Any]:
        user = ctypes.windll.user32
        user.GetDpiForWindow.argtypes, user.GetDpiForWindow.restype = [wintypes.HWND], wintypes.UINT
        user.GetThreadDpiAwarenessContext.argtypes = []
        user.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        user.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user.GetAwarenessFromDpiAwarenessContext.restype = ctypes.c_int
        context = user.GetThreadDpiAwarenessContext()
        return {
            "window_dpi": user.GetDpiForWindow(ui.window.handle),
            "thread_context": context,
            "thread_awareness": user.GetAwarenessFromDpiAwarenessContext(context),
        }

    hit = win32gui.WindowFromPoint(point)
    return {
        "element_rect": [box.left, box.top, box.right, box.bottom],
        "point": list(point),
        "ancestry": ancestry,
        "ancestry_reaches_main": reached_main,
        "main": window(ui.window.handle),
        "client_rect": list(win32gui.GetClientRect(ui.window.handle)),
        "client_screen_origin": list(win32gui.ClientToScreen(ui.window.handle, (0, 0))),
        "foreground": observed(lambda: window(win32gui.GetForegroundWindow())),
        "hit": observed(lambda: window(hit)),
        "hit_root": observed(lambda: window(win32gui.GetAncestor(hit, 2))),
        "last_active_popup": observed(
            lambda: window(win32gui.GetLastActivePopup(ui.window.handle))
        ),
        "dpi": observed(dpi),
        "patterns": {
            "expand_collapse": observed(lambda: element.iface_expand_collapse is not None),
            "invoke": observed(lambda: element.iface_invoke is not None),
        },
    }


def desktop_state() -> dict[str, Any]:
    """Observe desktop availability without changing desktops, focus, or input state."""
    from ctypes import wintypes

    state: dict[str, Any] = {
        "available": False,
        "reason": "desktop_state_unavailable",
        "desktop": None,
        "foreground_hwnd": 0,
        "foreground_pid": 0,
        "foreground_process": None,
    }
    try:
        user = ctypes.WinDLL("user32", use_last_error=True)
        user.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        user.OpenInputDesktop.restype = ctypes.c_void_p
        user.GetUserObjectInformationW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user.GetUserObjectInformationW.restype = wintypes.BOOL
        user.CloseDesktop.argtypes = [ctypes.c_void_p]
        user.CloseDesktop.restype = wintypes.BOOL
        user.GetForegroundWindow.argtypes = []
        user.GetForegroundWindow.restype = wintypes.HWND
        user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user.GetWindowThreadProcessId.restype = wintypes.DWORD
        desktop = user.OpenInputDesktop(0, False, 0x0001)  # DESKTOP_READOBJECTS
        if not desktop:
            state["reason"] = "input_desktop_unavailable"
            return state
        try:
            name = ctypes.create_unicode_buffer(256)
            needed = wintypes.DWORD()
            readable = bool(
                user.GetUserObjectInformationW(
                    desktop, 2, name, ctypes.sizeof(name), ctypes.byref(needed)
                )
            )  # UOI_NAME
        finally:
            closed_desktop = bool(user.CloseDesktop(desktop))
        if not closed_desktop:
            state["reason"] = "desktop_handle_close_failed"
            return state
        if not readable:
            state["reason"] = "input_desktop_name_unavailable"
            return state
        # Do not write arbitrary desktop names (which may contain user information).
        state["desktop"] = "Default" if name.value == "Default" else "non-default"
        if name.value != "Default":
            state["reason"] = "input_desktop_not_default"
            return state
        hwnd = user.GetForegroundWindow()
        state["foreground_hwnd"] = int(hwnd or 0)
        pid = wintypes.DWORD()
        if not hwnd or not user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) or not pid.value:
            state["reason"] = "foreground_identity_unavailable"
            return state
        state["foreground_pid"] = int(pid.value)
        matches = [p for p in host_state().processes if p.get("pid") == pid.value]
        if len(matches) != 1 or not isinstance(matches[0].get("name"), str):
            state["reason"] = "foreground_process_unavailable"
            return state
        process = ntpath.basename(matches[0]["name"]).casefold()
        if not process:
            state["reason"] = "foreground_process_unavailable"
            return state
        state["foreground_process"] = process
        if process == "lockapp.exe":
            state["reason"] = "lock_screen_foreground"
            return state
        state.update(available=True, reason="available")
    except Exception:
        # Diagnostics never expose exception text or OS account information.
        state["reason"] = "desktop_state_unavailable"
    return state


def owned_cancel(dialog: Any, pid: int) -> Any:
    return unique(
        [
            w
            for w in dialog.descendants()
            if w.element_info.control_type == "Button"
            and menu_label(w.window_text()) == "Cancel"
            and w.is_visible()
            and w.is_enabled()
            and w.process_id() == pid
        ],
        "one owned Cancel button required",
    )


def physical_size_leaves(dialog: Any, pid: int) -> list[Any]:
    """Visible content leaves of the observed section; title chrome is not content."""
    section = unique(
        [
            w
            for w in dialog.descendants()
            if w.element_info.automation_id == PHYSICAL_SIZE_SECTION
            and w.is_visible()
            and w.process_id() == pid
        ],
        "one owned Physical size section required",
    )
    leaves: list[Any] = []

    def visit(element: Any, depth: int) -> None:
        require(depth < 32, "Physical size ancestry is too deep")
        if not element.is_visible():
            return
        require(element.process_id() == pid, "foreign Physical size content")
        identity = element.element_info.automation_id
        if isinstance(identity, str) and identity.startswith(PHYSICAL_SIZE_SECTION + ".groupTitle"):
            return
        children = [child for child in element.children() if child.is_visible()]
        if children:
            for child in children:
                visit(child, depth + 1)
        elif element.element_info.control_type not in {"Pane", "Group", "Window"}:
            leaves.append(element)

    for child in section.children():
        visit(child, 0)
    return leaves


def configuration_survey(
    ui: PainterUi, owned: OwnedTransport, evidence: Evidence, *, physical_size: bool = False
) -> None:
    def guard() -> None:
        owned.verify()
        require(ui.window.process_id() == owned.launcher.pid, "UI window process changed")
        state = desktop_state()
        evidence.log("desktop_availability", state=state)
        require(state["available"] is True, "UI navigation refused: " + state["reason"])

    dialog = None
    cancel = None
    try:
        guard()
        # Labels are discovered in the actual UI before any navigation; no guessed IDs.
        edit = ui.menu_item("Edit")
        require(edit.process_id() == owned.launcher.pid, "foreign Edit menu")
        evidence.log("navigation", phase="before_front", state=navigation_state(ui, edit))
        guard()
        ui.front()
        guard()
        edit = ui.menu_item("Edit")
        require(edit.process_id() == owned.launcher.pid, "foreign Edit menu after foreground")
        evidence.log("navigation", phase="after_front", state=navigation_state(ui, edit))
        guard()
        ui.click(edit)
        time.sleep(ui.settle_s)
        guard()
        containers = ui.menu_containers()
        evidence.json(
            "menu", [ui.survey(c) for c in containers if c.process_id() == owned.launcher.pid]
        )
        item = ui.menu_item("Project Configuration")
        require(item.process_id() == owned.launcher.pid, "foreign configuration menu")
        guard()
        ui.click_menu_item(item)
        deadline = time.monotonic() + 10
        while True:
            guard()
            matches = {
                w.handle: w
                for w in [*ui.window.children(), *ui.desktop.windows(process=owned.launcher.pid)]
                if w.is_visible()
                and menu_label(w.window_text()).casefold() == "project configuration"
            }
            if matches:
                dialog = unique(list(matches.values()), "ambiguous configuration dialog")
                break
            require(time.monotonic() < deadline, "configuration dialog missing")
            time.sleep(0.2)
        require(
            dialog.process_id() == owned.launcher.pid and dialog.handle != ui.window.handle,
            "foreign configuration dialog",
        )
        evidence.json(
            "configuration", {"tree": ui.survey(dialog), "values": visible_values(dialog)}
        )
        evidence.image("configuration_image", ui, dialog.handle)
        cancel = owned_cancel(dialog, owned.launcher.pid)
        if physical_size:
            guard()
            require(
                dialog.process_id() == owned.launcher.pid, "configuration dialog process changed"
            )
            title = unique(
                [
                    w
                    for w in dialog.descendants()
                    if w.element_info.control_type == "Button"
                    and w.element_info.automation_id == PHYSICAL_SIZE_TITLE
                    and menu_label(w.window_text()) == "Physical size"
                    and w.is_visible()
                    and w.is_enabled()
                    and w.process_id() == owned.launcher.pid
                ],
                "one owned Physical size title required",
            )
            before = physical_size_leaves(dialog, owned.launcher.pid)
            if not before:
                guard()
                require(
                    dialog.process_id() == owned.launcher.pid,
                    "configuration dialog process changed",
                )
                ui.click(title, owner=dialog.handle)
                deadline = time.monotonic() + 10
                while True:
                    guard()
                    require(
                        dialog.process_id() == owned.launcher.pid,
                        "configuration dialog process changed",
                    )
                    if physical_size_leaves(dialog, owned.launcher.pid):
                        break
                    require(
                        time.monotonic() < deadline, "Physical size content did not become visible"
                    )
                    time.sleep(0.2)
            guard()
            require(
                dialog.process_id() == owned.launcher.pid, "configuration dialog process changed"
            )
            evidence.json(
                "physical_size",
                {
                    "expanded_by_click": not bool(before),
                    "tree": ui.survey(dialog),
                    "values": visible_values(dialog),
                },
            )
            evidence.image("physical_size_image", ui, dialog.handle)
    finally:
        if dialog is not None and cancel is not None:
            guard()
            if physical_size:
                require(
                    dialog.process_id() == owned.launcher.pid,
                    "configuration dialog process changed",
                )
                cancel = owned_cancel(dialog, owned.launcher.pid)
                guard()
            ui.click(cancel, owner=dialog.handle)
            deadline = time.monotonic() + 10
            while dialog.is_visible():
                guard()
                require(time.monotonic() < deadline, "Cancel did not close configuration")
                time.sleep(0.2)
            evidence.log("configuration_cancelled")


def survey(request: Request) -> dict[str, Any]:
    require(
        not request.physical_size or request.configuration, "physical size requires configuration"
    )
    with ExitStack() as stack:
        evidence = Evidence(request.output_prefix, stack, physical_size=request.physical_size)
        report: dict[str, Any] = {
            "schema": "uzpainter/project-configuration-selector-survey/1",
            "status": "refused",
            "stage": "preflight",
            "not_filter_capture": True,
        }
        lock = Lock(
            evidence,
            task="Codex Project Configuration UI selector survey; "
            f"run={request.output_prefix.name}",
        )
        launcher = PainterLauncher(request.painter_exe, ready_timeout_s=120, stop_timeout_s=15)
        session = None
        owned = None
        preserve = False
        try:
            require(request.painter_exe.is_file(), "Painter executable unavailable")
            require(file_fingerprint(PLANE)[0] == PLANE_SHA256, "public plane hash differs")
            host = host_state()
            evidence.log(
                "host_preflight",
                physical_free=host.physical_free,
                commit_free=host.commit_free,
                processes=host.processes,
            )
            resources_available(host, request)
            require(not painters(host), "existing Painter process")
            require(not endpoint_answers(), "existing Painter endpoint")
            report["stage"] = "lock"
            lock.acquire()
            host = host_state()
            resources_available(host, request)
            require(not painters(host) and not endpoint_answers(), "Painter appeared before launch")
            report["stage"] = "launch"
            launcher.start(environment={"OCIO": None, "PAINTER_ACE_CONFIG": None})
            current = unique(painters(host_state()), "one newly owned Painter required")
            require(
                current["pid"] == launcher.pid
                and isinstance(current["started"], str)
                and bool(current["started"]),
                "owned Painter unavailable",
            )
            raw = HttpTransport(timeout_s=10)
            owned = OwnedTransport(raw, launcher, lock, current["started"])
            owned.closed_expected = True
            owned.verify()
            session = PainterSession(owned)
            identity = session.connect()
            require(
                identity.colour_management
                == {"mode": "legacy", "OCIO": None, "PAINTER_ACE_CONFIG": None},
                "Legacy child environment not observed",
            )
            report["stage"] = "create"
            session.call(
                "apply_step", step=1, call=CREATE, args=CREATE_ARGS, resolved={"mesh": str(PLANE)}
            )
            owned.claim_created()
            session.wait_ready(timeout_s=120)
            owned.verify()
            report["stage"] = "ui"
            resources_available(host_state(), request)
            owned.verify()
            ui = PainterUi(pid=launcher.pid, timeout_s=10)
            require(ui.window.process_id() == launcher.pid, "UI window process differs")
            before = session.state()
            needs_saving_before = owned.run(
                "__import__('substance_painter.project',fromlist=['needs_saving']).needs_saving()"
            )
            require(type(needs_saving_before) is bool, "needs_saving is not a boolean")
            evidence.log("ui_before", needs_saving=needs_saving_before)
            evidence.json(
                "main",
                {
                    "tree": ui.survey(ui.window),
                    "project_uuid": owned.project_uuid,
                    "pid": launcher.pid,
                    "started": owned.started,
                    "template": session.call("template_capture"),
                },
            )
            owned.verify()
            evidence.image("main_image", ui, ui.window.handle)
            if request.configuration:
                configuration_survey(ui, owned, evidence, physical_size=request.physical_size)
            owned.verify()
            after = session.state()
            needs_saving_after = owned.run(
                "__import__('substance_painter.project',fromlist=['needs_saving']).needs_saving()"
            )
            evidence.log("ui_after", needs_saving=needs_saving_after)
            require(
                before.is_open == after.is_open
                and before.file_path == after.file_path
                and after.ready
                and type(needs_saving_after) is bool
                and needs_saving_after == needs_saving_before,
                "project state changed during UI survey",
            )
            report["status"] = "complete"
        except Exception as error:
            report["error"] = traceback.format_exc()
            preserve = isinstance(error, OwnershipLost)
        finally:
            report["stage_at_cleanup"] = report["stage"]
            cleanup_owned(launcher, session, owned, lock, report, preserve=preserve)
            evidence.json("report", report)
        return {
            "status": report["status"],
            "report_sha256": file_fingerprint(evidence.paths["report"])[0],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--painter-exe", type=Path, required=True)
    parser.add_argument("--output-prefix", type=Path, required=True)
    parser.add_argument("--configuration", action="store_true")
    parser.add_argument("--physical-size", action="store_true")
    parser.add_argument("--min-free-memory-gib", type=float, default=8.0)
    parser.add_argument("--min-commit-headroom-gib", type=float, default=16.0)
    args = parser.parse_args()
    try:
        result = survey(Request(**vars(args)))
    except Exception:
        result = {"status": "refused"}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
