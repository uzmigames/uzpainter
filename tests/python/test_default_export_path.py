"""Native Documents policy and the facade's observed Painter default-path contract."""

from __future__ import annotations

import ctypes
import json
import uuid
from ctypes import wintypes
from pathlib import Path

from tests.python.conftest import Run


def documents_folder() -> Path:
    """Read Windows' Documents location without creating or verifying the directory."""
    folder_id = (ctypes.c_byte * 16).from_buffer_copy(
        uuid.UUID("FDD39AD0-238F-46AF-ADB4-6C85480369C7").bytes_le
    )
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    ole = ctypes.WinDLL("ole32", use_last_error=True)
    shell.SHGetKnownFolderPath.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole.CoTaskMemFree.restype = None
    address = ctypes.c_void_p()
    try:
        result = shell.SHGetKnownFolderPath(
            ctypes.byref(folder_id), 0x4000, None, ctypes.byref(address)
        )
        assert result == 0, f"SHGetKnownFolderPath failed: HRESULT {result:#x}"
        assert address.value is not None
        return Path(ctypes.wstring_at(address))
    finally:
        ole.CoTaskMemFree(address)


def test_default_export_path_is_host_documents_and_stable(facade: Run) -> None:
    documents = documents_folder()
    expected = documents / "Adobe" / "Adobe Substance 3D Painter" / "export"
    native_expected = documents / "UzPainter" / "export"
    report = facade(
        "EXPECTED = "
        + repr(expected.as_posix())
        + "\nNATIVE_EXPECTED = "
        + repr(str(native_expected))
        + "\n"
        + r"""
from pathlib import Path

samples = []
def sample():
    locations = [Path(EXPECTED).parents[1], Path(EXPECTED).parent, Path(EXPECTED),
                 Path(NATIVE_EXPECTED).parent, Path(NATIVE_EXPECTED)]
    def snapshot():
        return [(p.exists(), p.stat().st_mtime_ns if p.exists() else None) for p in locations]
    before = snapshot()
    value = export.get_default_export_path()
    native = uzpainter.export._default_export_path()
    assert snapshot() == before, "getter created or changed the export directory"
    assert isinstance(value, str) and Path(value).is_absolute()
    assert value == EXPECTED
    assert Path(native) == Path(NATIVE_EXPECTED)
    samples.append(value)

sample()
settings = project.Settings(default_texture_resolution=256,
                            default_save_path=WORK + "/ignored-save",
                            export_path=WORK + "/ignored-export")
project.create(PLANE, settings=settings)
sample()
missing_export_path = raises(export.export_project_textures, {})
assert missing_export_path is not None and missing_export_path.startswith("ValueError:")
project.save_as(WORK + "/saved.spp")
sample()
project.save()
sample()
project.close()
sample()
project.open(WORK + "/saved.spp")
sample()
project.close()
assert not os.path.exists(WORK + "/ignored-export")
assert not os.path.exists(WORK + "/ignored-save")
result = {"samples": samples, "missing_export_path": missing_export_path}
"""
    )
    assert report["status"] == "ok", json.dumps(report.get("error", report), indent=2)
    values = report["result"]["samples"]
    assert len(values) == 6 and len(set(values)) == 1


def test_facade_path_derives_redirected_documents_without_touching_disk(facade: Run) -> None:
    report = facade(
        r"""
from pathlib import Path
original = uzpainter.export._default_export_path
try:
    redirected = Path(WORK) / "redirected-\u00e1rea" / "Documents"
    uzpainter.export._default_export_path = lambda: str(redirected / "UzPainter" / "export")
    assert export.get_default_export_path() == (
        redirected / "Adobe" / "Adobe Substance 3D Painter" / "export"
    ).as_posix()
    assert not redirected.parent.exists(), "getter touched the redirected Documents path"
finally:
    uzpainter.export._default_export_path = original
"""
    )
    assert report["status"] == "ok", json.dumps(report.get("error", report), indent=2)
