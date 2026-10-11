## ADDED Requirements

### Requirement: Clean-room lobe fits with residuals
Every formula choice and fitted constant of the render feasibility prototype MUST be recorded in `parity/semantics/iray.json` with a public source from `07-preview-and-render-parity.md` §3.1 and its residual against the admitted Iray references.

#### Scenario: Fit without public source is rejected
Given a lobe fit entry that names no public source
When the fits are reviewed
Then the entry is not published

### Requirement: Noise floor combines Iray and UzPainter error
The noise-floor report MUST give, per analytic fixture and material region, Iray's run-to-run difference, Iray's Monte-Carlo error at S and UzPainter's own error at S, with mean signed Δ and its standard error and the downsampled statistics, as numbers only.

#### Scenario: Wrong lobe is distinguishable from noise
Given the prototype with an intentionally wrong lobe
When it is compared with the references
Then its mean signed Δ lies outside the measured noise floor

### Requirement: Ray-tracing support recorded on the owner's GPU
The report MUST record whether the owner's GPU supports DXR Tier 1.1 and the Vulkan ray-query extensions required by the path tracer.

#### Scenario: Probe recorded
Given the owner's machine
When the probes run
Then the report lists the DXR ray-tracing tier and the presence of `VK_KHR_acceleration_structure`, `VK_KHR_deferred_host_operations` and `VK_KHR_ray_query`
