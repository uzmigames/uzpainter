## ADDED Requirements

### Requirement: Documented Symbols Only
The `substance_painter` facade SHALL expose only symbols documented in Painter's public API documentation, each traceable to its documentation anchor, and MUST NOT expose private Painter names.

#### Scenario: Script probes a private symbol
Given a script running against the facade
When it accesses `substance_painter._private_helper`
Then `AttributeError` is raised as for any unknown attribute

### Requirement: Output-Changing Quirks Reproduced
The facade SHALL reproduce Painter's observable quirks that change output, each matching its Tier 0 API-probe golden exactly.

#### Scenario: Active channels assigned after set_source
Given a fill layer whose base-colour source was set through the facade
When the script assigns `active_channels` afterwards
Then the fill's sources are reset to the channel defaults, exactly as the Tier 0 golden records

#### Scenario: Channel argument in a mask stack
Given a mask stack context
When the script calls `set_source` with a channel instead of `None`
Then `ValueError` is raised and the revision is unchanged

### Requirement: Desktop-Only Symbols Raise
Each desktop-only symbol MUST raise `UnsupportedInUzPainter` naming the symbol, the reason and an alternative.

#### Scenario: Main window requested
Given a script running headless
When it calls `substance_painter.ui.get_main_window()`
Then `UnsupportedInUzPainter` is raised with the reason that the call changes no texture, render or script-visible state

### Requirement: Inert Context Kept As State
Selection, selection type, collapsed state, active stack, UI mode and application menu SHALL be stored as state whose readback returns what was set, and MUST NOT affect evaluation or export except where Painter reads them.

#### Scenario: Selection round trip
Given two layers
When a script sets the selected nodes to the second layer and reads them back
Then the readback returns the second layer and exported maps are byte-identical to an export without the selection change

### Requirement: Whitelisted JavaScript Evaluation
`js.evaluate` SHALL accept only the documented `alg.*` whitelist with JSON-literal arguments and MUST raise `UnsupportedInUzPainter` before mutation for any other expression.

#### Scenario: Arbitrary expression
Given an open project
When a script calls `js.evaluate("alg.project.close(); 1+1")`
Then `UnsupportedInUzPainter` is raised and the revision is unchanged

### Requirement: Colour Configuration Explicit
The facade SHALL preserve the project's declared colour-management configuration and MUST fail before evaluation when the configuration is not a pinned, tested profile.

#### Scenario: Unpinned OCIO configuration
Given a project created with an OCIO configuration that is not a pinned profile
When an evaluation is requested
Then the request fails with an explicit unsupported-configuration error before any evaluation runs

### Requirement: Grouped Modification Does Not Roll Back
`layerstack.ScopedModification` SHALL batch evaluation invalidation and MUST NOT roll back calls committed inside it when an exception is raised.

#### Scenario: Exception inside the scope
Given a `ScopedModification` block that adds a layer and then raises
When the block exits
Then the added layer remains committed
