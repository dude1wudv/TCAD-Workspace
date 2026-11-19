# R50 test engineering continuation r3

This is an independent continuation of the unchanged 64 test response identities and the original r2f prediction freeze. It does not refit models, regenerate predictions, modify any scientific gate, or implement the later oxide/boundary/delivery stages.

Two original test attempts must remain `FAILED`: alpha/30 degrees/seed 202610353/bit 0 and proton/0 degrees/seed 202610361/bit 0 at 0.25 um. Their available remote solver completion/exit information does not establish an original Windows runner/SSH exit. The root reconciliation explains and preserves each distinction. No exit code is synthesized. A retry is new collection evidence for the same canonical response; it is not a new event or replacement of an old archive.

`ALIASES` contains exactly two deterministic retry tags. The controller visits canonical order, reaudits and skips existing successes, fills the first retry gap, fills the second gap, then submits remaining cases in the original order. Only one attempt per new tag is permitted. Unknown failures, or either failed retry, stop further submission. Inputs for a retry are copied from its original archive with every byte hash identical except `project.json`; there only `name` may change. This retains device deck, parameters, G4 files, parent save points, mesh and provenance unchanged. Existing successes and failed originals are checked against their original r2f case freezes; new submissions are bound to r3 case freezes.

The narrow `finish.existing_test_attempts` adapter replaces the former success-only prefix rule with an exact two-failure rule, actual input archive/ledger bijection, prediction-before-submission checks and new-dispatch prefix checks. The original bundle/audit implementation still enforces actual runner success, manifest/SSH success, completion markers, input/result hashes and numerical gates for every eligible response. The previous r2f training audit is reused with its original one training retry alias.

The old scientific design remains byte frozen. A deep copy passed only to `run.record` changes its accounting ceiling to infinity because of the existing unlimited authorization. Every original, failed and retry solver cost stays in the unique global ledger. The plan records null budget/deadline, preserving the original 86400-second plans as history. No changes are made to old modules or frozen plans.

Before activation, root must provide an acceptance JSON with schema `dram-see-v3-r50-main-restart-r3-acceptance`, `approved: true`, exact design SHA, `source_sha256` returned by `sources()`, `reconciliation_sha256`, original `prediction_freeze_sha256`, absolute UTC `accepted_utc`, and a nonempty `evidence`. Reconciliation must have schema `dram-see-v3-r50-main-restart-r3-reconciliation`, `approved: true`, exact `failed_tags` and `aliases`, and a nonempty `files_sha256`. All referenced paths are project relative and hashed. Freeze additionally binds original prediction files, old source snapshots/evidence, all existing test raw archives and case freezes, unlimited authorization, the new controller/docs/tests, and the exact protected ledger bytes. Source snapshot and self-hash checks run again during execution.

Commands (only root may run freeze or execute against the real workspace):

```powershell
local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v3/r50-main/restart-r3/continue.py freeze --reconciliation <root-reconciliation.json> --acceptance <root-source-acceptance.json>
local_runtime/vdmos-analysis-venv/Scripts/python.exe -B experiments/dram-see-v3/r50-main/restart-r3/continue.py execute
```

Freeze and execute both acquire the existing local controller lock and use the existing unique-solver preflight. Execution uses the existing runner, serial dispatch, existing VM and single-thread solver settings. No standalone scheduler or wait-loop is introduced.

Outputs are in `local_runtime/dram-see-v3/physical-revisions/r50-main-restart-r3/`. New metrics and scores are independent of misleading historical canonical exports. `status.json` maps both training and test aliases to canonical slots while retaining original states. `test-result.json` has 64 canonical observations with actual ledger tags and a separate chronological raw-submission index including both preserved failed attempts. The terminal state is only `TEST_FINISHED_PENDING_EXTENSIONS`.

Validation uses isolated synthetic tests in `test_continue.py`; tests perform no solver/network calls and cannot establish real scientific completion. Root must separately audit corrected raw evidence, source acceptance, real preflight and eventual live outputs. The controller must not be represented as activated merely because these tests pass.
