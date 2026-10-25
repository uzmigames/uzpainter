"""Which public symbols a Tier 0 replay exercises (task phase1.22_pyapi-cli-capabilities item 2.5,
decision 112).

The Tier 0 tests (`test_pyapi_tier0.py`, `test_pyapi_facade_tier0.py`,
`test_pyapi_lifecycle_tier0.py`) execute this file's source inside UzPainter's embedded
interpreter before their replay (`SOURCE`), mark each compared output with `mark(output_id)` and
return `stop()`: for each output id, the qualified public names of `substance_painter`,
`substance_painter_plugins` and `uzpainter` that the calls made for it exercised. A symbol is
exercised when

- a public function, method, property or constructor of it returned or raised an error other than
  a UzPainter refusal (`NotYetSupported`, its subclasses, `UnsupportedInUzPainter`): a refused call
  proves nothing;
- a native (pybind11) function or method of it returned;
- an instance-only dataclass field was read or assigned, including a public validation error
  but excluding UzPainter refusals and constructor assignments;
- an enum member of it was passed to, or returned by, such a call; an instance of a public class
  was returned by one, or an exception of a public class left one.

A call is attributed to the output marked (`mark`) when it is made, except on a thread started
under the trace (`threading.Thread.start`) that ended before `stop()`: an asynchronous operation's
worker, whose calls belong to the output current when the thread was started, whenever they run.
A thread it starts inherits that output, and so do the tasks it posts to the dispatcher thread
(`uzpainter.event.post`): the deliveries a worker queues belong to the output that started it.
A thread still running at `stop()` is a service thread (the texture-state notifier), which works
for whichever call waits on it: its calls keep the output marked when they are made, as calls on
the main and dispatcher threads do.

A capability manifest entry `supported` in context `any` cites the api-probe goldens whose
compared outputs exercised it (`tier_evidence`); the Tier 0 tests check that claim against this
trace, in both directions, on the owner's machine (decision 028).

Standard library only, and no import of the packages before `start()`: the source runs in the
embedded interpreter, where `tests` is not importable.
"""

from __future__ import annotations

import dataclasses
import enum
import functools
import importlib
import inspect
import sys
import threading
import types
from pathlib import Path
from typing import Any

# This file, as the replays execute it (where it has no `__file__`).
_FILE: str | None = globals().get("__file__")
SOURCE = Path(_FILE).read_text(encoding="utf-8") if _FILE else ""

ROOTS = ("substance_painter", "substance_painter_plugins", "uzpainter")
REFUSALS = ("NotYetSupported", "UnsupportedInUzPainter")
TOOL = 4  # a free sys.monitoring tool id (0, 1, 2 and 5 are named by CPython)
EVENTS = sys.monitoring.events

_code: dict[types.CodeType, set[str]] = {}  # Python callables and constructors
_receivers: dict[types.CodeType, dict[str, type]] = {}  # the class owning each method alias
_native: dict[int, set[str]] = {}  # native callables by id (kept alive by their modules)
_classes: dict[type, set[str]] = {}
_fields: dict[type, set[str]] = {}  # data attributes of a class, exercised with it
_instance_fields: dict[type, dict[str, set[str]]] = {}  # instance-only dataclass fields, by access
_ABSENT = object()
# Enum members and module-level objects: by id, or by (class, value) for a native enum, whose
# members the bindings create anew on every return.
_members: dict[Any, set[str]] = {}
_native_enums: set[type] = set()
# Code of the script and the recorder's Painter-side code: the values the API hands to it
# (callback and handler arguments) are scanned too.
USER_FILES = {"painter_side.py", "painter_probes.py"}
_keep: list[Any] = []
_names: set[str] = set()  # every public name indexed
_trace: dict[str, set[str]] = {}
_current = ["setup"]
_stack = threading.local()  # per thread: the open frames, and the worker tokens it runs under
_lock = threading.Lock()
# Threads started under the trace, by token: the output they were started for, and the thread.
_workers: list[tuple[str, threading.Thread]] = []
# Calls made for a worker: (token, output marked when made) -> names, resolved by `stop()`.
_deferred: dict[tuple[int, str], set[str]] = {}
_patched: list[tuple[Any, str, Any]] = []  # (owner, attribute, original) restored by `stop()`


def _add(index: dict[Any, set[str]], key: Any, name: str) -> None:
    index.setdefault(key, set()).add(name)
    _names.add(name)


def _is_enum(cls: type) -> bool:
    # A pybind11 enum, or a facade subclass of one whose metaclass derives from pybind11's.
    return issubclass(cls, enum.Enum) or (
        "__members__" in dir(cls)
        and any(meta.__name__ == "pybind11_type" for meta in type(cls).__mro__)
    )


def _index_python(function: Any, qualified: str, receiver: type | None = None) -> None:
    code = inspect.unwrap(function).__code__
    _add(_code, code, qualified)
    if receiver is not None:
        _receivers.setdefault(code, {})[qualified] = receiver


def _index_class(qualified: str, cls: type, depth: int) -> None:
    """Indexes a class under one of its public names (a re-exported class has several)."""
    _add(_classes, cls, qualified)
    _add(_native, id(cls), qualified)  # a constructor call returning (native classes included)
    _keep.append(cls)
    if dataclasses.is_dataclass(cls):
        for field in dataclasses.fields(cls):
            owner = next(
                (
                    base
                    for base in cls.__mro__
                    if field.name in vars(base).get("__annotations__", {})
                ),
                None,
            )
            if (
                not field.name.startswith("_")
                and field.name not in dir(cls)
                and owner is not None
                and (owner is cls or owner.__name__.startswith("_"))
            ):
                names = _instance_fields.setdefault(cls, {}).setdefault(field.name, set())
                names.add(f"{qualified}.{field.name}")
                _names.add(f"{qualified}.{field.name}")
    init = cls.__dict__.get("__init__")
    if isinstance(init, types.FunctionType):
        _index_python(init, qualified, cls)
    enum_class = _is_enum(cls)
    if enum_class:
        members: dict[str, Any] = getattr(cls, "__members__")  # noqa: B009 (pybind11 enums too)
        native = not issubclass(cls, enum.Enum)
        if native:
            _native_enums.add(cls)
        for name, member in members.items():
            _add(_members, (cls, int(member)) if native else id(member), f"{qualified}.{name}")
            _keep.append(member)
    for name, value in _members_of(cls):
        protocol = enum_class and (name in ("name", "value") or isinstance(value, cls))
        if protocol:
            continue
        if not _index_value(f"{qualified}.{name}", value, depth + 1, cls):
            _add(_fields, cls, f"{qualified}.{name}")  # a field, a slot or a constant


def _members_of(cls: type) -> list[tuple[str, Any]]:
    """The public members a class documents: its own, and those it inherits from a private base
    (a member inherited from a public class is documented there)."""
    members = []
    for name in sorted(dir(cls)):
        if name.startswith("_"):
            continue
        owner = next((k for k in cls.__mro__ if name in vars(k)), None)
        if owner is cls or (owner is not None and owner.__name__.startswith("_")):
            members.append((name, vars(owner)[name]))
    return members


def _index_value(qualified: str, value: Any, depth: int, receiver: type | None = None) -> bool:
    """Indexes a callable or a class; False for a data attribute."""
    if isinstance(value, staticmethod):
        receiver = None
        value = value.__func__
    elif isinstance(value, classmethod):
        value = value.__func__
    if isinstance(value, property):
        _names.add(qualified)
        for accessor in (value.fget, value.fset, value.fdel):
            if isinstance(accessor, types.FunctionType):
                _index_python(accessor, qualified, receiver)
            elif callable(accessor):
                # Native descriptor access has no CALL event; explicit accessor calls do.
                _index_value(qualified, accessor, depth, receiver)
        return True
    if inspect.isclass(value):
        if depth < 4:
            _index_class(qualified, value, depth)
        return True
    if isinstance(value, types.FunctionType):
        # A decorator's wrapper code is shared by every function it wraps: the wrapped one's
        # code identifies the call.
        _index_python(value, qualified, receiver)
        return True
    if callable(value) and not isinstance(value, enum.Enum):
        _add(_native, id(value), qualified)
        func = getattr(value, "__func__", None)
        if func is not None:
            _add(_native, id(func), qualified)
            _keep.append(func)
        _keep.append(value)
        return True
    return False


def _index_module(qualified: str, module: types.ModuleType) -> None:
    _names.add(qualified)
    for name in sorted(dir(module)):
        if name.startswith("_"):
            continue
        value = getattr(module, name)
        if isinstance(value, types.ModuleType):
            if value.__name__ == f"{qualified}.{name}":
                _index_module(value.__name__, value)
            continue
        primitive = isinstance(value, (int, float, str, bytes, tuple, list, dict, type(None)))
        if not _index_value(f"{qualified}.{name}", value, 0):
            _names.add(f"{qualified}.{name}")  # a constant such as logging.INFO
            if not primitive:
                _add(_members, id(value), f"{qualified}.{name}")  # an instance: DISPATCHER
                _keep.append(value)
                for member, attribute in _members_of(type(value)):
                    _index_value(f"{qualified}.{name}.{member}", attribute, 1)


def _token() -> int | None:
    """The token of the worker this thread is working for (its own, or a posted task's)."""
    tokens: list[int] | None = getattr(_stack, "tokens", None)
    return tokens[-1] if tokens else None


def _note(names: set[str]) -> None:
    token = _token()
    with _lock:
        if token is None:
            _trace.setdefault(_current[0], set()).update(names)
        else:
            _deferred.setdefault((token, _current[0]), set()).update(names)


def _working_for(token: int, function: Any, *args: Any) -> Any:
    """Runs `function` on this thread for the worker `token`."""
    tokens: list[int] | None = getattr(_stack, "tokens", None)
    if tokens is None:
        tokens = _stack.tokens = []
    tokens.append(token)
    try:
        return function(*args)
    finally:
        tokens.pop()


def _start_thread(original: Any, thread: threading.Thread) -> None:
    """`threading.Thread.start`: the thread works for its starter's worker, or for the output
    marked now."""
    token = _token()
    with _lock:
        output = _workers[token][0] if token is not None else _current[0]
        _workers.append((output, thread))
        started = len(_workers) - 1
    thread.run = functools.partial(_working_for, started, thread.run)  # type: ignore[method-assign]
    original(thread)


def _post(original: Any, task: Any) -> Any:
    """`uzpainter.event.post`: a task a worker posts runs for that worker."""
    token = _token()
    return original(task if token is None else functools.partial(_working_for, token, task))


def _patch(owner: Any, attribute: str, wrapper: Any) -> None:
    """Replaces `owner.attribute` with `wrapper(original, ...)` (a function, so that a method
    stays one) until `stop()`."""
    original = getattr(owner, attribute)
    _patched.append((owner, attribute, vars(owner).get(attribute, _ABSENT)))

    def patched(*args: Any) -> Any:
        return wrapper(original, *args)

    setattr(owner, attribute, patched)


def _field_access(original: Any, instance: Any, name: str, *args: Any) -> Any:
    """Record the named field only when its real read/write returns or raises a public error."""
    names: set[str] = set()
    for cls in type(instance).__mro__:
        names = _instance_fields.get(cls, {}).get(name, set())
        if names or name in vars(cls).get("__annotations__", {}):
            break
    # Inherited and unindexed constructors also assign fields as implementation details.
    # The intervening frame is _patch's wrapper.
    caller = sys._getframe(2).f_code
    if names and any(
        getattr(vars(cls).get("__init__"), "__code__", None) is caller
        for cls in type(instance).__mro__
    ):
        names = set()
    try:
        result = original(instance, name, *args)
    except BaseException as error:
        if not any(cls.__name__ in REFUSALS for cls in type(error).__mro__):
            _note(names)
        raise
    _note(names)
    return result


def _given_fields(value: Any) -> set[str]:
    """The fields of a public-class instance that hold a value other than the constructor's
    default: those the caller gave (a field left at its default is not exercised)."""
    try:
        defaults = {
            n: p.default
            for n, p in inspect.signature(type(value)).parameters.items()
            if p.default is not inspect.Parameter.empty
        }
    except (TypeError, ValueError):
        defaults = {}
    given = set()
    for qualified in _fields.get(type(value), set()):
        name = qualified.rsplit(".", 1)[1]
        try:
            current = getattr(value, name)
        except AttributeError:
            continue
        if name not in defaults or not bool(current == defaults[name]):
            given.add(qualified)
    return given


def _scan(value: Any, depth: int = 0) -> None:
    """Records the enum members and public-class instances in an argument or a returned value."""
    names = _members.get((type(value), int(value)) if type(value) in _native_enums else id(value))
    if names is not None:
        _note(names)
    cls_names = _classes.get(type(value))
    if cls_names is not None:
        _note(cls_names | _given_fields(value))
    if depth < 2 and isinstance(value, (list, tuple, set, frozenset)):
        for item in list(value)[:64]:
            _scan(item, depth + 1)
    elif depth < 2 and isinstance(value, dict):
        for key, item in list(value.items())[:64]:
            _scan(key, depth + 1)
            _scan(item, depth + 1)


def _frames() -> list[tuple[types.CodeType, list[Any]]]:
    stack = getattr(_stack, "frames", None)
    if stack is None:
        stack = _stack.frames = []
    return stack


def _on_start(code: types.CodeType, offset: int) -> Any:
    if code not in _code:
        if code.co_filename not in USER_FILES:
            return sys.monitoring.DISABLE
        frame = sys._getframe(1)
        for name in code.co_varnames[: code.co_argcount]:
            _scan(frame.f_locals.get(name))
        return None
    frame = sys._getframe(1)
    arguments = [frame.f_locals.get(n) for n in code.co_varnames[: code.co_argcount]]
    _frames().append((code, arguments))
    return None


def _finish(code: types.CodeType, raised: BaseException | None, value: Any = None) -> None:
    frames = _frames()
    if not frames or frames[-1][0] is not code:
        return
    _, arguments = frames.pop()
    if raised is not None and any(c.__name__ in REFUSALS for c in type(raised).__mro__):
        return
    # Private-base methods share code across public sibling classes. Only the receiver's
    # class (and its real aliases or public bases) exercised that method.
    receiver = arguments[0] if arguments else None
    owners = _receivers.get(code, {})
    _note(
        {
            name
            for name in _code[code]
            if name not in owners
            or (
                issubclass(receiver, owners[name])
                if isinstance(receiver, type)
                else isinstance(receiver, owners[name])
            )
        }
    )
    for argument in arguments:
        _scan(argument)
    if raised is not None:
        _scan(raised)
    else:
        _scan(value)


def _on_return(code: types.CodeType, offset: int, value: Any) -> Any:
    if code not in _code:
        return sys.monitoring.DISABLE
    _finish(code, None, value)
    return None


def _on_unwind(code: types.CodeType, offset: int, exception: BaseException) -> None:
    if code in _code:
        _finish(code, exception)


def _on_c_return(code: types.CodeType, offset: int, callable_: Any, arg0: Any) -> Any:
    names = _native.get(id(callable_))
    if names is not None:
        _note(names)
        _scan(arg0)  # the first argument, or the instance of a method
    return None


def _drop_shared_code() -> None:
    """Forgets code that several distinct public functions share (closures made by one factory):
    a call to it does not say which of them ran."""
    for code, names in list(_code.items()):
        if len({n.rsplit(".", 1)[1] for n in names}) > 1:
            owners = _receivers.get(code, {})
            if all(name in owners and name in _classes.get(owners[name], set()) for name in names):
                continue  # Shared constructors remain distinguishable by their instance.
            del _code[code]


def public_symbols() -> list[str]:
    """Every public name of the three packages: modules, their functions, classes and objects,
    class members (methods, properties, fields, slots, enum members) and module constants; not
    the enum protocol (`name`, `value`) nor names starting with an underscore."""
    if not _names:
        for root in ROOTS:
            _index_module(root, importlib.import_module(root))
        _drop_shared_code()
    return sorted(_names)


def start() -> None:
    """Indexes the public symbols of the three packages and starts recording."""
    public_symbols()
    # Patch descendants first: inherited originals must not capture a patched base wrapper.
    for cls in sorted(_instance_fields, key=lambda cls: len(cls.__mro__), reverse=True):
        _patch(cls, "__getattribute__", _field_access)
        _patch(cls, "__setattr__", _field_access)
    _patch(threading.Thread, "start", _start_thread)
    event = getattr(sys.modules.get("uzpainter"), "event", None)
    if callable(getattr(event, "post", None)):
        _patch(event, "post", _post)
    monitoring = sys.monitoring
    monitoring.use_tool_id(TOOL, "uzpainter-capability-trace")
    monitoring.register_callback(TOOL, EVENTS.PY_START, _on_start)
    monitoring.register_callback(TOOL, EVENTS.PY_RESUME, _on_start)
    monitoring.register_callback(TOOL, EVENTS.PY_RETURN, _on_return)
    monitoring.register_callback(TOOL, EVENTS.PY_YIELD, _on_return)
    monitoring.register_callback(TOOL, EVENTS.PY_UNWIND, _on_unwind)
    monitoring.register_callback(TOOL, EVENTS.C_RETURN, _on_c_return)
    monitoring.set_events(
        TOOL,
        EVENTS.PY_START
        | EVENTS.PY_RESUME
        | EVENTS.PY_RETURN
        | EVENTS.PY_YIELD
        | EVENTS.PY_UNWIND
        | EVENTS.CALL,  # with C_RETURN, which CALL controls
    )


def mark(output_id: str) -> None:
    """Attributes the calls from now on to `output_id`."""
    with _lock:
        _current[0] = output_id


def stop() -> dict[str, list[str]]:
    """Stops recording; the exercised symbols by output id."""
    sys.monitoring.set_events(TOOL, 0)
    sys.monitoring.free_tool_id(TOOL)
    while _patched:
        owner, attribute, original = _patched.pop()
        if original is _ABSENT:
            delattr(owner, attribute)
        else:
            setattr(owner, attribute, original)
    with _lock:
        for (token, marked), names in _deferred.items():
            started, thread = _workers[token]
            _trace.setdefault(marked if thread.is_alive() else started, set()).update(names)
        _deferred.clear()
        return {output: sorted(names) for output, names in sorted(_trace.items())}


# ── Host side (pytest) ──────────────────────────────────────────────────────────────────────────

# The committed trace of every Tier 0 replay: replay id -> {golden, symbols}. The Tier 0 tests keep
# it equal to what they trace; the conformance test checks the manifest's evidence against it.
TRACE_FILE = (
    Path(_FILE).resolve().parents[2] / "tools" / "capabilities" / "tier0-trace.json"
    if _FILE
    else Path()
)
UPDATE_VARIABLE = "UZP_UPDATE_TIER0_TRACE"


def traced(body: str) -> str:
    """A script body whose `result` holds compared outputs only, run under the trace: its
    `result` becomes `[result, trace]`, the whole run attributed to one output."""
    start = (
        "_TRACE = {'__name__': 'uzp_capability_trace'}\n"
        f"exec(compile({SOURCE!r}, 'capability_trace.py', 'exec'), _TRACE)\n"
        "_TRACE['start']()\n"
    )
    return start + body + "\nresult = [result, _TRACE['stop']()]\n"


# The replays' own bookkeeping (resetting the recorder, locating nodes): no compared output
# reads it.
BOOKKEEPING = "bookkeeping"


def exercised(trace: dict[str, list[str]], excluded: Any = ()) -> list[str]:
    """The symbols of every traced output that is compared: not in `excluded`, not bookkeeping.
    `setup` (the project's creation, saving and reopening) counts: every output depends on it."""
    skip = {*excluded, BOOKKEEPING}
    return sorted({s for output, names in trace.items() if output not in skip for s in names})


def load_trace() -> dict[str, dict[str, Any]]:
    import json

    data: dict[str, dict[str, Any]] = json.loads(TRACE_FILE.read_text(encoding="utf-8"))
    return data


def check_trace(replay: str, golden: str, symbols: list[str]) -> None:
    """Asserts that the committed trace of `replay` (a compared replay of `golden`) is `symbols`.
    With UZP_UPDATE_TIER0_TRACE=1 in the environment, records it instead."""
    import json
    import os

    entry = {"golden": golden, "symbols": symbols}
    data = load_trace() if TRACE_FILE.is_file() else {}
    if os.environ.get(UPDATE_VARIABLE) == "1":
        data[replay] = entry
        text = json.dumps(dict(sorted(data.items())), indent=1, sort_keys=True) + "\n"
        TRACE_FILE.write_text(text, encoding="utf-8")
        return
    committed = data.get(replay)
    recorded = set((committed or {}).get("symbols", []))
    assert committed == entry, (
        f"{replay}: the compared replay of {golden} exercised another symbol set than "
        f"{TRACE_FILE.name} records (added {sorted(set(symbols) - recorded)}, gone "
        f"{sorted(recorded - set(symbols))}); re-run with {UPDATE_VARIABLE}=1 and update the "
        "manifest's evidence (decision 112)"
    )
