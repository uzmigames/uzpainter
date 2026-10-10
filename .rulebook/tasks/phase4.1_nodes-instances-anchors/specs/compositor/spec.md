## ADDED Requirements

### Requirement: Instance Layers Equal to Painter
An instance layer SHALL evaluate its source layer's subtree at the instance's position with the instance's own blending and masks, follow later edits of the source, and produce output equal to the Tier 0 goldens.

#### Scenario: Edited source propagates
Given an instance of a fill layer placed above a group
When the source layer's roughness value is changed and Roughness is exported at 16 bit
Then the instance's contribution reflects the new value and the decoded values equal the private Painter golden exactly

### Requirement: Anchors and Reference Sources Equal to Painter
An anchor effect SHALL publish the layer's current content under its name, and a `reference` source SHALL read it with the documented channel mapping, referenced channel, alpha matte and levels, with output equal to the Tier 0 goldens.

#### Scenario: Anchor used in a mask
Given an anchor on a height layer and a mask whose fill effect references that anchor with levels
When the masked channel is exported at 16 bit
Then the decoded values equal the private Painter golden exactly

### Requirement: Acyclic Anchor Graph
Anchor references MUST form an acyclic graph; an operation that would create a cycle SHALL raise `ValueError` before mutation.

#### Scenario: Cycle refused
Given layer A references an anchor on layer B
When an agent makes layer B reference an anchor on layer A
Then the call raises `ValueError` and the project revision is unchanged

### Requirement: Instance Insertion Rules
Instance layers MUST be insertable only in the layer hierarchy; insertion into an effect stack SHALL raise the documented error before mutation.

#### Scenario: Instance into a mask stack
Given a layer's mask stack
When an agent tries to insert an instance there
Then the call raises the documented error and the project revision is unchanged
