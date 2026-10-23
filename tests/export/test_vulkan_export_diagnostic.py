"""Real export files through CPU, DX12 and qualified Vulkan (decision 310).

Native test seam only: this does not enable the product Vulkan factory or claim Painter parity.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.export.test_export_encoders import TEMPLATES, config, spec


def test_cpu_export_backend_bundle(export_tests: Path, tmp_path: Path) -> None:
    """CPU lane validates the diagnostic command and project/resource identity without GPU."""
    source = spec(tmp_path / "source")
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(config(tmp_path / "files")), encoding="utf-8")
    proc = subprocess.run(
        [str(export_tests), "export-backend", "cpu", str(TEMPLATES), str(source), str(cfg_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = json.loads(proc.stdout)
    assert "error" not in result, result
    assert result["backend"] == "cpu"
    assert result["revision"] == 1
    assert len(result["project_sha256"]) == 64
    assert result["evaluator_profile"]
    assert "texturing_mesh" in result["resource_hashes"]
    assert len(result["files"]) == 3
    for entry in result["files"]:
        assert hashlib.sha256(Path(entry["path"]).read_bytes()).hexdigest() == entry["sha256"]


@pytest.mark.skipif(os.environ.get("UZP_NO_GPU") == "1", reason="UZP_NO_GPU=1")
@pytest.mark.parametrize("bit_depth", ["8", "16"])
def test_export_files_equal_cpu_dx12_vulkan(
    export_tests: Path, tmp_path: Path, bit_depth: str
) -> None:
    """Bitmap projection, sRGB decode, L16 and half Height reach real PNG/EXR files.

    Compare all bytes, including headers, and validate each reported hash against disk.
    Vulkan must identify its adapter and backend; no CPU fallback can satisfy the test.
    """
    source = spec(tmp_path / "source")
    expected: dict[str, bytes] | None = None
    for repeat, backend in itertools.product(range(2), ("cpu", "dx12", "vulkan")):
        folder = tmp_path / f"{backend}-{repeat}"
        folder.mkdir()
        cfg = config(folder / "files", bitDepth=bit_depth)
        cfg_path = folder / "config.json"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        proc = subprocess.run(
            [
                str(export_tests),
                "export-backend",
                backend,
                str(TEMPLATES),
                str(source),
                str(cfg_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
        )
        output = proc.stdout + proc.stderr
        if proc.returncode == 77:
            pytest.skip(f"{backend} unavailable: {output.strip()}")
        assert proc.returncode == 0, output
        result: dict[str, Any] = json.loads(proc.stdout)
        assert "error" not in result, result
        assert result["backend"] == backend
        if backend != "cpu":
            assert result["adapter"], result
            assert result["driver"], result
        result["build_sha256"] = hashlib.sha256(export_tests.read_bytes()).hexdigest()
        (folder / "bundle.json").write_text(json.dumps(result), encoding="utf-8")
        files: dict[str, bytes] = {}
        for entry in result["written"]:
            data = Path(entry["path"]).read_bytes()
            assert len(data) == entry["size"]
            assert hashlib.sha256(data).hexdigest() == entry["sha256"]
            assert entry["relativePath"] not in files
            files[entry["relativePath"]] = data
        assert len(files) == 3, result
        assert {Path(name).suffix for name in files} == {".png", ".exr"}
        if expected is None:
            expected = files
        else:
            assert files.keys() == expected.keys()
            for name, data in files.items():
                assert data == expected[name], f"{backend}: {name} differs from CPU export"
        print(f"PASS {backend}: {len(files)} real exported files, PNG {bit_depth} and EXR 32f")
