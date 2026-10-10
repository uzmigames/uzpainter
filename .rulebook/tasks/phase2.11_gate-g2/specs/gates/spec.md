## ADDED Requirements

### Requirement: G2 Joins Every Mandatory Phase 2 Item
Gate G2 SHALL be accepted only when G1, P2-TUNIC, P2-PREVIEW and P2-SUPERVISOR are accepted, and through them P2-MCP, P2-RECIPE and P2-BELT; no single work package MUST close it.

#### Scenario: Tunic passes but preview is open
Given Tunic v10 Tier 1 and dump-and-rebuild pass
When `phase2.3_realtime-preview` is not yet accepted
Then G2 stays open

### Requirement: G2 Pilot Parity Evidence
G2 MUST record that Belt v5 and Tunic v10 Tier 1 maps and dump-and-rebuild pass under the exception policy, that the Belt round completed through MCP with Python disabled, that worker-kill, lost-acknowledgement and stalled-fence recovery tests pass, and that captures are window-independent.

#### Scenario: Gate record written
Given every joined item accepted
When the gate record is written to `parity/reports/phase2/gate-g2.md`
Then it lists each piece of evidence with its hash, the exceptions relied on and the build hash, and contains no oracle data

### Requirement: Render Parity Excluded From G2
G2 MUST NOT include render parity, and its record MUST state that it cannot satisfy G5's render requirements.

#### Scenario: Viewport captures in G2
Given window-independent `painter_viewport` captures
When G2 is recorded
Then they are cited only as capture evidence, never as render parity
