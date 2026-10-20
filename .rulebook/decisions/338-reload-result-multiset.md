# 338. ReloadResourcesEnded's result list is compared as a multiset with multiplicity; the order of its entries is unclaimed, because Painter varies it across processes for the same request

Date: 2026-10-20. Status: accepted (Claude and Codex, SUP-221; joint technical decision within the delegated technical scope). This is not an owner exception: it defines what the comparison claims for an output whose order Painter does not fix.
Related: phase1.24_python-api-facade item 4.1; decisions 297, 332 and 336; goldens `tier0/api-probes/p22b-host-resources` (r2 s20) and the all-origins reload-order controls recorded on 2026-10-20 (reload-order-all-recording2).

## Context

- `p22b-host-resources` r2 s20 reloads two resources at once. Painter reported `[checker-reload, checker]`, and the facade reported `[checker, checker-reload]`. That single recording could not settle the order.
- The approved documentation of `reload_modified_resources_async` and `ReloadResourcesEnded` promises a list of the successful reloads. It says nothing about their order.
- The dedicated all-origins controls ran the same request, step, condition and content in separate Painter processes. They recorded different orders of the same entries (the two completed `zam` r1 s8 permutations). Painter's own order is therefore not a stable behaviour that can be reproduced. It varies between runs. The pairwise analysis of the 13 admitted runs (5 goldens) found 84 complete paired multiset comparisons, all equal, and 20 ordered-list mismatches (tmp/scratch/closure/reload-order-analysis/all-origins-pairwise.json).

## Decision

1. **Result list.** `ReloadResourcesEnded`'s list of `ReloadedResourceResult` entries is compared as a multiset with multiplicity. Every entry must be present the same number of times, with equal fields. A missing, duplicated or changed entry, or a changed old or new resource, fails.
2. **Everything else exact.** The order of the events around it, and any errors, are compared exactly, in order. Contexts are normalised only by the existing rule (decision 107).
3. **Raw orders kept.** Painter's recorded orders and UzPainter's orders stay in the raw outputs and the reports. The entry order is reported as unclaimed, not as parity.
4. **Not an exception.** Nothing is excluded. The comparison claims exactly what the documentation and the recordings fix: which reloads happened, and how many times each.

## Consequences

- The `after_save_reopen s20/events` exclusion of `p22b-host-resources` is replaced by this comparison. It no longer names phase1.24 item 4.1 as its owner.
- Codex's defect tests (missing, duplicate, changed old/new result) must fail under the rule. That checks the rule is not a blanket.
