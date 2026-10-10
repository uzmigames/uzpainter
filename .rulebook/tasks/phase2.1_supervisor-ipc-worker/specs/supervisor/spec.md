## ADDED Requirements

### Requirement: Supervisor Holds No GPU Device Or Document
The supervisor process SHALL NOT initialise a GPU device, hold an editable copy of the document or execute user Python; these MUST live only in the worker process it launches.

#### Scenario: Supervisor started by an MCP client
Given an AI client launches `UzPainter.exe --mcp --gpu-backend dx12`
When the supervisor starts its worker and a project is opened
Then only the worker process creates the DX12 device and opens the project store

### Requirement: Handshake Mismatch Is Fatal
The supervisor MUST treat any difference between the requested and the reported protocol version, GPU backend or Python policy in the worker handshake as a fatal supervisor error and MUST NOT fall back silently.

#### Scenario: Worker reports a different backend
Given a supervisor started with `--gpu-backend vulkan`
When the worker handshake reports `"gpu_backend":"dx12"`
Then the supervisor raises a fatal error and admits no call to that worker

### Requirement: Worker Faults Do Not End The Session
When the worker dies, aborts, reports device removal or loss, or times out on a GPU wait, the supervisor SHALL keep the MCP session open, relaunch the worker on the project's last committed revision with the same backend and Python policy, and record the recovery time.

#### Scenario: Device removal injected on DX12
Given a worker evaluating a project on DX12
When the test hook calls `ID3D12Device5::RemoveDevice`
Then the job fails with `device_removed`, the worker exits, the supervisor relaunches it on the last committed revision and the MCP session stays connected

#### Scenario: Supervisor dies first
Given a running worker connected to its supervisor
When the supervisor process is killed
Then the worker detects the broken pipe and exits without committing anything further

### Requirement: Unavailable Backend Fails Before Mutation
A worker whose requested GPU backend cannot create a device SHALL still start and MUST fail every GPU-dependent operation with `gpu_backend_unavailable {backend, reason}` before mutating anything, while GPU-free operations remain available.

#### Scenario: Vulkan unavailable
Given a supervisor started with `--gpu-backend vulkan` on a machine without a usable Vulkan device
When a client requests an export and then a project save
Then the export fails with `gpu_backend_unavailable` without committing a revision, and the save succeeds

### Requirement: Python Disabled At The Pipe
A worker launched without `--allow-python` MUST reject the `run_python` method at the IPC boundary with `python_disabled`.

#### Scenario: run_python sent to a Python-disabled worker
Given a worker started without `--allow-python`
When a `run_python` request arrives on its pipe
Then the worker returns `error.code = "python_disabled"` and executes no Python
