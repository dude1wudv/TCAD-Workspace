# R50 test engineering continuation r4

This adapter loads the immutable r3 controller into a private namespace. Its source root is `restart-r3/continue.py` SHA256 `8a1e9c6bbc9b2e4b31776f6e3efc2ff24c213d0f2fefbdfadb746b1948754257`; r3 plan SHA256 is `ed0bce1f2420e3a8f1df303afcfc36daa062a8bd4261ce61e50747a1e4ec645d`. The explicit `source-manifest.json` names that chain and all upstream/new files. Frozen source files and upstream plans are never edited.

Only one additional engineering retry is implemented: canonical `v3-r50-main-l025-proton-a30-s202610371-b1` maps to `v3-r50-main-retry-r4-l025-proton-a30-s202610371-b1`. Root must first adjudicate and preserve its original attempt as `FAILED` using actual collected evidence. This source does not infer scientific failure or solver completion from the fact that the controller exited. It synthesizes no exit code. The previous two r3 retry aliases must already be truly `VERIFIED` and are reused without resubmission. The original three `FAILED` rows remain immutable.

The adapter changes five explicit core extension points in its private namespace: runtime output directory, exact alias map, case-freeze routing, current plan validation, and progress writer. The original r3 input byte comparison/preparation, `record`, true runner/SSH/raw audits, matching, prediction validator, ledger protection and cost accounting remain the inherited implementations. The outer freeze/execute wrappers only add version binding and routing for two prior generations. No global source-module file is modified.

Case ownership is derived from frozen submission membership, not trusted from a mutable row's `execution_freeze`. Cases present in r3's protected ledger snapshot retain r2f case freezes. Actual later r3 submissions retain r3 case freezes, including both completed retry aliases and the newly failed canonical response. New r4 submissions bind to r4 case freezes. `prior_case_plans` is frozen and rederived against the protected snapshot; the common checker then verifies the selected plan SHA, exact case, source map, actual inputs and row provenance. Each inherited retry still compares every input byte with its original archive, allowing only the deterministic project name to change.

All original model/prediction bytes remain frozen under r2f with prediction SHA256 `f0384066be6d42bb71dad6fd8e4e1a2f474e6f9f45d918da759ca0274a4cff9e`. Actual metadata/archive identity, prediction-before-submission chronology and all successful physical audits remain required. Unknown failures stop submission. Exactly 64 canonical test scores and 32 independent test events are preserved, with a separate raw attempt index and all three original failed rows. Twenty-five verified logical test responses imply 39 pending calls: the one new retry and 38 never-submitted cases, in unchanged order. The count is recomputed from accepted real state, not assumed from this document.

Budget/deadline behavior inherits the reviewed r3 implementation: unlimited project authorization, no new time/solver ceiling, all costs in the one global ledger, the original science design still byte frozen. One controller lock and original unique-solver preflight remain mandatory. Runtime outputs are exclusively `physical-revisions/r50-main-restart-r4/`; completion is only `TEST_FINISHED_PENDING_EXTENSIONS`.

Root reconciliation uses schema `dram-see-v3-r50-main-restart-r4-reconciliation`, `approved: true`, the exact ordered three-element `failed_tags`, full three-entry `aliases`, and nonempty `files_sha256`. Root acceptance uses schema `dram-see-v3-r50-main-restart-r4-acceptance`, `approved: true`, exact `design_sha256`, the complete `sources()` map, `reconciliation_sha256`, `prediction_freeze_sha256`, absolute UTC `accepted_utc`, and nonempty `evidence`. Freeze binds the files/acceptance, all prior test archives including successful aliases, source snapshots and exact protected ledger bytes. Existing aliases are required, while pre-existing submission of the new r4 alias is rejected.

Root-only real commands:

```powershell
local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v3/r50-main/restart-r4/continue.py freeze --reconciliation <root-r4-reconciliation.json> --acceptance <root-r4-acceptance.json>
local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v3/r50-main/restart-r4/continue.py execute
```

The builder performs only local source edits and isolated tests. Tests cannot establish real collection, a successful new retry, scientific gate completion, or remaining extension/delivery completion. Those require root review and actual evidence.
