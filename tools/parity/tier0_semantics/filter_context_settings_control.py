"""Recipe A recorded with F context boundaries and bound read-only Project Configuration UI
observations at each boundary (docs/filter-observations-v2.md, effective F settings); a factory
only.

The instruction sequence is recipe A's, unchanged (`filter_context_contract.A_RECIPE_SHA256`); only
the golden's identity and description differ from `filter_context_control`. The UI panels are
recorded by `tools/parity/recorder/filter_context_run.py` and `settings_panel.py`, never authored as
steps; no setting is changed or claimed by this request.
"""

from __future__ import annotations

from typing import Any

from tools.parity.tier0_semantics import filter_context_control as context

NAME = "filter-context-settings-a"
GOLDEN_ID = "tier0/api-probes/" + NAME


def request() -> dict[str, Any]:
    """The public request of recipe A with F context boundaries and bound settings panels."""
    result = context.request()
    result["golden_id"] = GOLDEN_ID
    result["description"] = (
        "Recipe A (the booleans/FilterEffectNode control) unchanged, recorded with read-only "
        "documented getter readbacks of the F context and, at each of the same five boundaries, "
        "read-only observations of the Project Configuration panel (Physical size expanded, then "
        "cancelled) bound to the owned process, window and project. No setting is changed; the "
        "API alone cannot read tangent space, workflow or mesh unit scale."
    )
    return result
