"""Recipe A recorded with read-only F context boundaries (decision 363); a factory only.

The instruction sequence is `source_substance_control.booleans_filter_request`'s, unchanged (its
typed hash is `filter_context_contract.A_RECIPE_SHA256`); only the golden's identity, description
and the settings the protocol cannot read differ. The context readbacks are recorded by
`tools/parity/recorder/filter_context_run.py`, never authored as steps.
"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

from tools.parity.filter_context_contract import A_RECIPE_SHA256, MISSING_SETTINGS, typed
from tools.parity.tier0_semantics.source_substance_control import booleans_filter_request

NAME = "filter-context-a"
GOLDEN_ID = "tier0/api-probes/" + NAME


def request() -> dict[str, Any]:
    """The public request of recipe A with F context readbacks; no authored value is added."""
    result = deepcopy(booleans_filter_request())
    if hashlib.sha256(typed(result["instruction_sequence"])).hexdigest() != A_RECIPE_SHA256:
        raise ValueError("recipe A changed; the F context golden records it unchanged only")
    result["golden_id"] = GOLDEN_ID
    result["description"] = (
        "Recipe A (the booleans/FilterEffectNode control) unchanged, recorded with read-only "
        "documented getter readbacks of the F context after project creation, after setup "
        "step 6, before step 16 in both rounds and after the save/close/reopen with fresh "
        "handles. No effective project setting is claimed: tangent space, workflow and mesh "
        "unit scale are not readable through the documented API and stay unverified."
    )
    result["uncontrolled_settings"] = list(MISSING_SETTINGS)
    return result
