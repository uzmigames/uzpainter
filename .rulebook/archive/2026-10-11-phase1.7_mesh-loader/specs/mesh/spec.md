## ADDED Requirements

### Requirement: Mesh fixtures accepted
The mesh module SHALL pass every fixture of `docs/architecture/12-mesh-import.md` §9 before gate G1 can accept it.

#### Scenario: Full §9 run
Given all three children of `phase1.7_mesh-loader` are accepted
When the §9 fixture set runs
Then every import, certificate, reload and normal-convention fixture passes and the results are recorded for G1

### Requirement: UzEngine only as an external consumer
The normal-convention fixture MUST exercise UzEngine only by running UzEngine's own executable on exported maps; no UzPainter code SHALL link or call UzEngine code.

#### Scenario: UzEngine leg of the fixture
Given the normal map produced by the production loader and tangents
When the fixture shades it in UzEngine
Then UzEngine's own executable is launched as a separate process and UzPainter's build references no UzEngine artifact
