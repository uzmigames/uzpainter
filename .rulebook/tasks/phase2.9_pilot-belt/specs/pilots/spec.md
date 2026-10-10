## ADDED Requirements

### Requirement: Belt v5 Maps Equal The Painter Goldens
Every Belt v5 map exported by UzPainter MUST equal the private Painter golden in native decoded values, unless an owner-approved exception in the register covers the difference.

#### Scenario: Belt v5 Tier 1
Given the Belt v5 stack JSON, resources and external mesh maps
When UzPainter rebuilds and exports the belt
Then each exported map equals the golden at native precision and two runs are byte-identical

### Requirement: Belt Round Completes Through MCP With Python Disabled
The complete Belt v5 round SHALL run through typed MCP tools against a supervisor started without `--allow-python`.

#### Scenario: Python-disabled round
Given a supervisor started without `--allow-python`
When the belt round (create, import, sync, save, export) runs through typed tools
Then it completes, `run_python` is never available, and the maps equal those of the Tier 1 run
