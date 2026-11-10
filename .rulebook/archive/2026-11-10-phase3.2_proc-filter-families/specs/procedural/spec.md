# Procedural — filter family

## ADDED Requirements

### Requirement: Filter Family Tier 2a
Sharpen, grayscale conversion and the Levels filter MUST each equal their Painter oracle over the Tier 2a certification matrix or be covered by an owner-approved exception; otherwise they MUST be listed as release gaps.

#### Scenario: Sharpen on hat v6 low
Given authored layer content on hat v6 low and a recorded Sharpen parameter set
When the Sharpen filter is evaluated at 2048
Then the output MUST equal the private Painter oracle or cite an approved exception

### Requirement: Filters Read Current Content
A filter effect SHALL compute from the layer content produced by the effects below it in the list and blend the result with its own mode and opacity.

#### Scenario: Filter above a fill effect
Given a layer with a fill effect followed by a grayscale filter
When the stack is evaluated
Then the filter input MUST be the content after the fill effect, and the result MUST blend with the filter's mode and opacity
