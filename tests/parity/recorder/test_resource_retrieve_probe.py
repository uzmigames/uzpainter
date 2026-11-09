"""The `resource-retrieve-cached-url` API probe (task phase3.1_assets3d-cutover; decision 112):
`Resource.retrieve` as the Assets3D layer-stack sync calls it on the URL of a mask resource cached
by an earlier sync. The request must validate as an observed probe job whose retrieves read only
versioned ids, and the recorder's Painter-side code must build an authored `from_project(name,
version)` id. Never launches Painter."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from tests.parity.recorder.test_raw_resource_identity import Identifier, runtime
from tools.parity.envelope.registry import current_envelope
from tools.parity.recorder.probes import (
    load_probe_job,
    manifest_symbol_problems,
    probe_job_from_manifest,
)
from tools.parity.recorder.session import RecorderError
from tools.parity.schemas import REPO_ROOT, load_json

STEM = "resource-retrieve-cached-url"
RESOURCE = "substance_painter.resource."
FROM_URL, FROM_PROJECT = f"{RESOURCE}ResourceID.from_url", f"{RESOURCE}ResourceID.from_project"
RETRIEVE = f"{RESOURCE}Resource.retrieve"


def probe_path() -> Path:
    manifests = REPO_ROOT / current_envelope(REPO_ROOT)["manifest_root"]
    for root in (manifests, manifests.with_name("requests")):
        path = root / "tier0" / "api-probes" / f"{STEM}.json"
        if path.is_file():
            return Path(path)
    raise AssertionError(f"{STEM} is neither requested nor admitted")


def steps(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = manifest["instruction_sequence"]["steps"]
    return found


def test_the_request_is_an_observed_legacy_probe_whose_retrieves_are_probes() -> None:
    path = probe_path()
    manifest = load_json(path)
    job = load_probe_job(path)  # validates against golden-public.json first
    assert job.golden_id == f"tier0/api-probes/{STEM}"
    assert manifest_symbol_problems(manifest) == []
    assert job.observed and not job.lifecycle and not job.exports
    assert not [s for s in manifest["applied_settings"] if s["name"] == "OCIO"]  # Legacy
    retrieves = [s["step"] for s in steps(manifest) if s["call"] == RETRIEVE]
    assert len(retrieves) == 4 and set(retrieves) <= {s.step for s in job.probe_steps}
    by_step = {s["step"]: s for s in steps(manifest)}
    sources = [by_step[by_step[r]["args"]["resource_step"]] for r in retrieves]
    assert [s["call"] for s in sources] == [FROM_URL, FROM_PROJECT, FROM_PROJECT, FROM_PROJECT]
    # The cached URL is the import's own; the authored ids name no imported identity.
    cached = by_step[sources[0]["args"]["resource_step"]]
    assert cached["call"] == f"{RESOURCE}import_project_resource"
    assert {k for s in sources[2:] for k in s["args"]} == {"name", "version"}


def edited(step_call: str, index: int, args: dict[str, Any]) -> dict[str, Any]:
    manifest: dict[str, Any] = copy.deepcopy(load_json(probe_path()))
    step = [s for s in steps(manifest) if s["call"] == step_call][index]
    step["args"] = args
    return manifest


@pytest.mark.parametrize(
    "args",
    [
        {"name": "mask_left_half"},  # unversioned: Painter-side retrieve refuses it
        {"name": "mask_left_half", "version": ""},
        {"name": "mask_left_half", "version": 1},
        {"name": "", "version": "v.image"},
    ],
)
def test_an_authored_query_needs_a_name_and_a_version(args: dict[str, Any]) -> None:
    with pytest.raises(RecorderError):
        probe_job_from_manifest(edited(FROM_PROJECT, 1, args))


@pytest.mark.parametrize(
    "args",
    [
        {"url": "resource://project0/mask_left_half"},  # not an import's URL
        {"resource_step": 4},  # a node step, not an import
        {"resource_step": 99},
    ],
)
def test_a_cached_url_must_be_an_imports_url(args: dict[str, Any]) -> None:
    with pytest.raises(RecorderError, match="versioned query"):
        probe_job_from_manifest(edited(FROM_URL, 0, args))


def test_retrieve_refuses_a_later_or_unversioned_source() -> None:
    manifest = edited(RETRIEVE, 0, {"resource_step": 16})
    with pytest.raises(RecorderError, match="versioned query"):
        probe_job_from_manifest(manifest)
    manifest = edited(RETRIEVE, 0, {"resource_step": 3})  # the import itself, not a query
    with pytest.raises(RecorderError, match="versioned query"):
        probe_job_from_manifest(manifest)


def test_painter_side_builds_the_authored_identity_in_the_current_context() -> None:
    ns = runtime()
    query = ns["host_read"](FROM_PROJECT, {"name": "uzp_absent", "version": "v.image"})
    assert ns["calls"] == [("uzp_absent", "v.image")]
    assert (query.context, query.name, query.version) == (
        "current-project-context",
        "uzp_absent",
        "v.image",
    )
    assert ns["PROBE_RESOURCES"][32] is query
    for bad in ({"name": "x", "version": ""}, {"name": "x", "version": "v", "extra": 1}):
        with pytest.raises(ValueError, match="name and version"):
            ns["host_read"](FROM_PROJECT, bad)


def test_painter_side_retrieves_a_url_query_with_its_version() -> None:
    ns = runtime()
    ns["PROBE_RESOURCES"][31] = Identifier("old-context", "public-input", "public-version")
    ns["CURRENT"]["step"] = 33
    ns["substance_painter"].resource.Resource.retrieve = lambda identifier: []
    assert ns["host_read"](RETRIEVE, {"resource_step": 31}) == []
