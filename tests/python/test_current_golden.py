"""A replay follows a promoted envelope and never accepts a stale or missing golden."""

from pathlib import Path

import pytest

from tests.python import current_golden
from tools.parity.verdict import ResolvedGolden


def test_manifest_resolves_again_after_promotion(monkeypatch: pytest.MonkeyPatch) -> None:
    current = "old"

    def resolve(golden_id: str) -> ResolvedGolden:
        return ResolvedGolden(golden_id, Path(current), {"marker": current}, current, False)

    monkeypatch.setattr(current_golden, "resolve_golden", resolve)
    assert current_golden.current_manifest("tier0/test")["marker"] == "old"
    current = "new"
    assert current_golden.current_manifest("tier0/test")["marker"] == "new"


def test_manifest_refuses_missing_current_golden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(current_golden, "resolve_golden", lambda _: None)
    with pytest.raises(AssertionError, match="missing from the current oracle envelope"):
        current_golden.current_manifest("tier0/test")


def test_manifest_refuses_stale_golden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        current_golden,
        "resolve_golden",
        lambda key: ResolvedGolden(key, Path("old"), {}, "old", True),
    )
    with pytest.raises(AssertionError, match="stale oracle envelope old"):
        current_golden.current_manifest("tier0/test")
