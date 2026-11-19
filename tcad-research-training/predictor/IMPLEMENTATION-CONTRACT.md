# Implementation contract, 2026-11-16

Local implementation of `../plans/dram-se-ddr5-lpddr5/PREDICTOR-TRAINING.md`.
No server mutation, solver launch, native-data fit, or historical-data import.
Only explicitly synthetic fixtures may take small optimizer steps in unit tests.

Ownership: main owns dataset/splits/features/pipeline/CLI/docs; model agent owns
`mechanism.py`, `models.py`, `losses.py`, `tests/test_models.py`; ingest agent owns
`ingest.py`, `tests/test_ingest.py`. No recursive delegation.

## Numeric model API

Use numpy and PyTorch; CPU. Device matrices already standardized using only the
training side. They include state for R/calibration; F does not have state.
Physical scalars remain separate, in ns, fF, fC, V; C_fF / tau_ns = g_uS.

`MechanismCalibrator.fit(control_x, controls, response_x, responses)`:
controls are dictionaries with `control_id`, `profile_id`, `state`,
`time_ns`, `voltage_V`, `reference_voltage_V`, `capacitance_fF`,
`mechanism_validated=True`; their time describes an identified RC relaxation.
responses are dictionaries with `response_id`, `profile_id`, `state`,
`time_ns` (relative to injection), `delta_voltage_V` (null values permitted),
`generated_charge_fC`, `source_duration_ns`, `capacitance_fF`,
`mechanism_validated=True`. Inputs are training-side only, main pipeline audits
all IDs. Fit a shared ridge mapping of log(tau_ns) using controls, then signed
collection gain from irradiated responses and known input C. Do not fit a
profile-ID lookup. Reject absent identifiable calibration with a meaningful
error, not fabricated constants. Preserve skipped calibration reasons.
`predict(device_x)` returns dict of numpy arrays `tau_ns`, `gain`;
`to_dict()` / `from_dict(payload)` roundtrip with calibration source IDs.

`rectangular_response(time_ns, duration_ns, tau_ns)` gives causal unit-charge
RC response (dimensionless), including duration->0 impulse limit. This is a
documented local approximation, not a universal radiation pulse model.

`ResponseNet(input_dim, hidden=(64,64), residual_bins=4, mode="hybrid", window_ns=None)`:
forward `(x, x_off, *, time_ns, capacitance_fF, tau_ns, gain,
generated_charge_fC, source_duration_ns)`, tensors shapes x=(B,D), times=(T,)
or (B,T), physical scalars=(B,). Returns dict:
`delta_voltage_V` (B,T), `capacitor_charge_fC` (B,T),
`port_charge_fC` (B,), `margin_V` (B,), `upset_logit` (B,),
`residual_coefficients` (B,4). Hybrid mode: baseline rectangular source plus
causal piecewise-constant residual-current bases; residual neural coefficients
use r(x)-r(x_off). Both waveform and port-charge increment are signed, no
artificial collection bound. Margin is an absolute readout auxiliary head;
upset is independent valid binary head (no unknown third class).
Modes `mechanism_only`, `plain` also supported for ablation. A plain MLP need
not force zero-source equality. No fixed Qcrit, no energy monotonicity.

`CrossSectionNet(input_dim, hidden=(32,32), sigma_scale=1e-12)`:
forward(x) returns (B,2) positive sigma via scaled softplus. sigma_scale must
come from the training side, never test labels.

Loss helpers: `masked_huber(pred,target,mask,scale=1.0)` valid count normalized,
`masked_bce(logits,target,mask)`, `proxy_cross_section_loss(pred,target,mask,scale,weights)`,
`poisson_count_loss(sigma,count,exposure,mask)`. Missing targets can contain NaN;
mask BEFORE arithmetic so invalid labels never poison gradients. Empty masks
return differentiable zero. Poisson exposure = fluence * N_bits, only where
the count-model contract says appropriate. Zero counts do not get pseudocounts.

## Snapshot and extraction API

UTF-8 JSON/JSONL. Manifest uses `schema_version:1`, `plan_id:"dram-se-ddr5-lpddr5"`,
`simulation_revision:"0.4"`, `kind:"native_simulation"` or `"synthetic_fixture"`,
`conditions_file`, `primaries_file`, `development:{responses_file,controls_file,counts_file}`,
`sealed:{...}`. These are relative files in the snapshot directory; never open
sealed label files in preparation/training. A manifest may also declare
`sample_times_ns` (strictly increasing, relative to injection).

Condition: `condition_id, profile_id, cohort` (development/new_combination/
high_energy/device_extrapolation), `domain` (one route/model per snapshot),
`features` numeric pre-simulation fields incl `incident_energy_MeV`,
`gate_length_nm`, `capacitance_fF`, `theta_deg`, `phi_deg`; `categories`
incl `particle:"proton", structure_family`; `source_area_cm2, n_bits`,
`area_normalization_validated`, `primary_count` (all distinct emitted primary),
`source_distribution:"uniform"`, `count_model:"poisson"` only if justified.

Primary index: `primary_id, condition_id, source_primary_id` (global provenance,
not seed), `source_features` numeric incl `generated_charge_fC`,
`deposited_energy_MeV,source_duration_ns`, `source_off` (complete mapped source),
`pool_member: true`, `sampling:"random"/"enriched"`, `source_hash`.
Same source in multiple conditions has distinct primary_id but same source_primary_id.
Full pool includes zero-deposition events. F cannot receive source_features.

Response: `response_id, primary_id, state, bit_id, status` (valid/unresolved/failed),
`labels` dict (`delta_voltage_V` array, `port_charge_fC`, `margin_V`, `upset`;
missing => null), `masks` optional per-head; `source_hash,run_id`,
`mechanism_validated`, `supersedes` optional prior response_id.
Only explicit valid binary upset labels count as actual physical labels.
Controls: `control_id,profile_id,cohort,state`, RC fields above, source_hash/run_id.
Native count: `count_id,condition_id,state,bit_errors,fluence_cm2,n_bits,count_model`,
`source_primary_ids`, `source_hash`; separate from proxy estimates.

`ingest.py` implements pure CSV/DF-ISE parsing and trace extraction, plus
`build_snapshot(intake_manifest_path, output_dir)`. Intake has identical
conditions/primaries/development tables; response rows may have `trace` and
`control_trace` specs `{path,format:"csv"/"dfise",time_column,voltage_column,
current_column?, time_unit:"s"/"ns",voltage_unit:"V"/"mV",current_unit:"A"/"uA"}`,
`injection_time_ns`, `port_current_sign` +/-1, `charge_window_ns:[start,end]`.
Root intake `sample_times_ns` is frozen target grid; derive voltage DELTA from
signal minus matched control, charge from signed integral of their current
difference. Do not invent binary upset or margin from a voltage threshold.
Only export development labels; copy label-free condition/primary metadata;
sealed labels are left as external untouched references and MUST NOT be read.
No raw-file glob import; paths and source hashes explicitly declared. Return
manifest path. Preserve provenance and omissions. Refuse old v3/v4 generation
when claimed as this r0.4 snapshot. Read-only original runner archives.

Implemented intake extensions: each `trace` and `control_trace` spec requires
its own `sha256`; root declared hashes are also checked. Paired response rows
require `matching_control:{profile_id,state,protocol_id}` consistent with the
condition/response. See `SCHEMA.md` for the complete input contract.

Ready A proxy rows require a complete R `training_footprint` with
`condition_ids,profile_ids,source_primary_ids,source_control_ids`; F verifies
all target identities are outside that footprint before consuming a label.
Pending proxies may omit the footprint and never create supervision.

The final R probability temperature uses existing three-fold random OOF
predictions and is marked `estimated_oof_for_refit`, not independently
validated. It does not retroactively change F's frozen OOF proxy labels.
