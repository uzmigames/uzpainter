"""Toolchain probe report of `phase0.7_toolchain-probes` (item 2.7).

    python -m tools.toolchain.probes_report --work <scratch dir> [--out <report.md>]

Run on the owner's machine (decision 028: GPU checks run locally and their report is the
evidence). Builds `zig build painter` into `<work>/dist`, then records in one Markdown report:

- `UzPainter.exe selftest` on the GPU: the probe stages `dx12-ray-query`, `vulkan-availability`,
  `vulkan-ray-query` and `warp`, each with `completed` and `qualified` stated separately, the
  supported items, the executed checks, the reason of every unsupported item, the Vulkan
  physical devices and the hosted WARP lane;
- a run of a copy of the folder whose Vulkan loader is hidden (`hide_vulkan_loader`): the Vulkan
  probe reports `unavailable` and the DX12 hardware slice is unaffected.

Every scratch file stays under `<work>`; only the Markdown report is written to `--out` (default
`parity/reports/phase0/toolchain-probes.md`). Exit code 0 when every probe completed and the
hardware slice passed in both runs, 1 otherwise.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.toolchain.slice_report import run_selftest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "parity" / "reports" / "phase0" / "toolchain-probes.md"
PROBES = ("dx12-ray-query", "vulkan-availability", "vulkan-ray-query", "warp")
RAY_QUERY_EXTENSIONS = (
    "VK_KHR_acceleration_structure",
    "VK_KHR_deferred_host_operations",
    "VK_KHR_ray_query",
)


def hide_vulkan_loader(folder: Path) -> None:
    """Hides the system Vulkan loader from `UzPainter.exe` in `folder`: Windows searches the
    executable's folder first, and a file there named `vulkan-1.dll` that is not a DLL ends the
    search with an error, so the loader in `System32` is never reached."""
    (folder / "vulkan-1.dll").write_bytes(b"not a DLL: hides the system Vulkan loader\n")


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _yes(flag: bool) -> str:
    return "yes" if flag else "**no**"


def probes(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {p["probe"]: p for p in report["probes"]}


def _probe_section(probe: dict[str, Any]) -> list[str]:
    lines = [
        f"### `{probe['probe']}`",
        "",
        f"Backend `{probe['backend']}`; adapter {probe['adapter'] or '-'}; driver "
        f"{probe['driver'] or '-'}. Probe completed: {_yes(probe['completed'])}; qualified: "
        f"{_yes(probe['qualified'])}; verdict: **{probe['verdict']}**"
        + (f"; error: {_cell(probe['error'])}" if probe["error"] else "")
        + ".",
        "",
    ]
    if probe["supported"]:
        lines += ["Supported: " + ", ".join(f"`{s}`" for s in probe["supported"]) + ".", ""]
    if probe["executed_checks"]:
        lines += ["| Executed check | Result | Detail |", "|---|---|---|"]
        lines += [
            f"| {_cell(c['check'])} | {c['result']} | {_cell(c['detail'])} |"
            for c in probe["executed_checks"]
        ]
        lines.append("")
    if probe["unsupported"]:
        lines += ["| Unsupported item | Reason |", "|---|---|"]
        lines += [f"| {_cell(u['item'])} | {_cell(u['reason'])} |" for u in probe["unsupported"]]
    else:
        lines.append("Unsupported items: none.")
    lines.append("")
    if "hosted_warp_lane" in probe:
        lane = ", ".join(f"`{c}`" for c in probe["hosted_warp_lane"]) or "none"
        lines += [f"Hosted WARP lane (checks that passed on WARP): {lane}.", ""]
    return lines


def _device_rows(probe: dict[str, Any]) -> list[str]:
    rows = [
        "| Device | Type | Vulkan API | Driver | Extensions | "
        + " | ".join(f"`{e}`" for e in RAY_QUERY_EXTENSIONS)
        + " | `accelerationStructure` | `rayQuery` | Selected |",
        "|---|---|---|---|---|" + "---|" * (len(RAY_QUERY_EXTENSIONS) + 3),
    ]
    for device in probe["devices"]:
        facts = device["facts"]
        driver = f"{facts['driver_name']} {facts['driver_info']}".strip() or facts["driver_version"]
        has = [_yes(e in device["extensions"]) for e in RAY_QUERY_EXTENSIONS]
        features = [
            _yes(device["features"].get(f, False)) for f in ("accelerationStructure", "rayQuery")
        ]
        rows.append(
            f"| {facts['name']} | {facts['type']} | {facts['api_version']} | {_cell(driver)} "
            f"(`{facts['driver_version']}`) | {facts['extension_count']} | "
            + " | ".join(has + features)
            + f" | {facts['selected']} |"
        )
    return rows


def render(work: Path, gpu: tuple[int, dict[str, Any]], hidden: tuple[int, dict[str, Any]]) -> str:
    code, report = gpu
    env = report["environment"]
    stages = {s["name"]: s for s in report["stages"]}
    device = stages["dx12-device"]["details"]
    found = probes(report)
    build = int(env["os_build"].split(".")[2])
    windows = "Windows 11" if build >= 22000 else "Windows 10"
    lines = [
        "# Toolchain probes — owner's machine run",
        "",
        "Task `phase0.7_toolchain-probes` (child of P0-TOOLCHAIN, `docs/dag.md`), probes of "
        "`docs/architecture/13-engine-integration.md` §4.2: Vulkan availability, inline ray "
        "queries on DX12 and Vulkan, and WARP. Decision 028: GPU checks run locally; this report "
        "is the evidence. Generated by `python -m tools.toolchain.probes_report` on "
        f"{datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}. UzPainter's own results only; no "
        "Painter output.",
        "",
        f"`selftest` exit code {code}, result {report['result']}, DX12 hardware slice "
        f"{report['hardware_slice']}. Probe stages are never mandatory and never part of the "
        "hardware slice: a Vulkan or WARP result does not fail G0.",
        "",
        "## Machine",
        "",
        "| Item | Value |",
        "|---|---|",
        f"| OS build | {env['os_build']} ({windows} {env['os_display_version']}) |",
        f"| CPU | {env['cpu']} |",
        f"| DX12 adapter | {device['adapter']} (vendor {device['vendor_id']}, device "
        f"{device['device_id']}) |",
        f"| DX12 driver (user-mode driver version) | {device['driver_version']} |",
        f"| Feature level / highest shader model | {device['feature_level']} / "
        f"{device['shader_model']} |",
        f"| Agility SDK | `D3D12_SDK_VERSION` {device['agility_sdk_version']} |",
        f"| Zig / build | {env['zig']} / {env['build_mode']} |",
        "",
        "## Summary",
        "",
        "| Probe | Backend | Adapter | Driver | Completed | Qualified | Verdict |",
        "|---|---|---|---|---|---|---|",
    ]
    for name in PROBES:
        if name not in found:
            stage = stages.get(name, {"status": "absent", "reason": ""})
            lines.append(
                f"| `{name}` | - | - | - | **no** ({stage['status']}: "
                f"{_cell(stage['reason'])}) | **no** | - |"
            )
            continue
        p = found[name]
        lines.append(
            f"| `{name}` | {p['backend']} | {p['adapter'] or '-'} | {p['driver'] or '-'} | "
            f"{_yes(p['completed'])} | {_yes(p['qualified'])} | {p['verdict']} |"
        )
    lines += ["", "## Probe results", ""]
    for name in PROBES:
        if name in found:
            lines += _probe_section(found[name])
    if "vulkan-availability" in found and found["vulkan-availability"]["devices"]:
        lines += [
            "## Vulkan physical devices",
            "",
            "Every device of the Vulkan 1.2 instance; `Selected` is the one the vendored Vulkan "
            "backend picks for adapter index 0 (discrete first). The full extension and feature "
            "lists are in the `selftest` JSON report.",
            "",
            *_device_rows(found["vulkan-availability"]),
            "",
        ]
    h_code, h_report = hidden
    h_found = probes(h_report)
    h_vulkan = h_found.get("vulkan-availability")
    h_reason = "; ".join(u["reason"] for u in h_vulkan["unsupported"]) if h_vulkan else "-"
    lines += [
        "## Vulkan loader hidden",
        "",
        "A copy of the folder with a file named `vulkan-1.dll` that is not a DLL beside "
        "`UzPainter.exe` (Windows searches the executable's folder first, so the system loader "
        f"is never reached): `selftest` exit code {h_code}, result {h_report['result']}, DX12 "
        f"hardware slice {h_report['hardware_slice']}. `vulkan-availability`: completed "
        f"{_yes(bool(h_vulkan and h_vulkan['completed']))}, verdict "
        f"**{h_vulkan['verdict'] if h_vulkan else '-'}**, reason: {_cell(h_reason)}.",
        "",
        "## Reproduce",
        "",
        "```",
        "python -m tools.toolchain.probes_report --work <scratch folder>",
        "python -m pytest tests/toolchain/test_probes.py",
        "```",
        "",
    ]
    # Scratch paths of this machine are not part of the evidence.
    return "\n".join(lines).replace(str(work), "<work>")


def passed(run: tuple[int, dict[str, Any]]) -> bool:
    code, report = run
    found = probes(report)
    return (
        code == 0
        and report["hardware_slice"] == "passed"
        and all(name in found and found[name]["completed"] for name in PROBES)
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.toolchain.probes_report")
    parser.add_argument("--work", type=Path, required=True, help="scratch folder (recreated)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    zig = shutil.which("zig")
    if zig is None:
        print("zig is not on PATH", file=sys.stderr)
        return 1
    work = args.work.resolve()
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    subprocess.run(
        [zig, "build", "painter", "--prefix", str(work / "dist")],
        cwd=REPO_ROOT,
        check=True,
        timeout=3600,
    )
    bin_dir = work / "dist" / "bin"
    gpu = run_selftest(bin_dir / "UzPainter.exe", work / "run-gpu")

    hidden_copy = work / "vulkan-hidden"
    shutil.copytree(bin_dir, hidden_copy)
    hide_vulkan_loader(hidden_copy)
    hidden = run_selftest(hidden_copy / "UzPainter.exe", work / "run-vulkan-hidden")

    text = render(work, gpu, hidden)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"report written to {args.out}")
    return 0 if passed(gpu) and hidden[1]["hardware_slice"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
