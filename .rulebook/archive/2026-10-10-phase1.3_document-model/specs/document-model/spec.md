## ADDED Requirements

### Requirement: Document round trip with stable digest
A document serialised to its canonical JSON manifest and loaded back SHALL be equal to the original, and the manifest digest MUST be identical across runs, processes and machines.

#### Scenario: Round trip on two machines
Given the fixture documents of `tests/uzp_core/`
When each is serialised, reloaded and serialised again on the hosted CPU lane and in a local run on the owner's machine (decision 028)
Then the documents are equal and all four digests of each document are identical

### Requirement: GPU-free document core
The `uzp_core` library MUST NOT depend on the render layer or a GPU device, so that its tests run on the hosted CPU lane.

#### Scenario: Hosted lane
Given a hosted runner without a GPU
When the `uzp_core` test suite runs
Then it builds and passes without creating a GPU device
