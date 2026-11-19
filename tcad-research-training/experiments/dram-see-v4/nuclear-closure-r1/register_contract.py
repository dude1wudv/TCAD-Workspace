"""Materialize the user-approved finite manifest once. No remote operations."""
import copy
import common as c


def values():
    old = c.read(c.HERE.parent/'matched-transport-r1/matched-contract.json')
    transport = copy.deepcopy(old)
    requests = []
    for r in old['requests']:
        r = copy.deepcopy(r)
        r['label'] = 'nc-r1-' + r['mode'] + '-' + r['arm'].lower()
        r['closure_stage'] = 'P0'
        requests.append(r)
    normal = next(r for r in requests if r['mode']=='normal' and r['arm']=='H')
    for index, count in enumerate([1000, 9000] + [10000]*99):
        r = copy.deepcopy(normal)
        r.update(label=f'nc-r1-h-{index:03d}', seed=50150001+index,
                 event_count=count, stage='fixed',
                 closure_stage='N1' if index==0 else 'N2' if index==1 else 'N3' if index<11 else 'N4')
        requests.append(r)
    transport.update(requests=requests, total_primary_events=1000008,
                     binary_call_limit=107, retry_limit=2,
                     closure_revision='nuclear-closure-r1',
                     scope='Fixed natural nuclear witness stages in the identical representative device geometry; no rate inference')
    roles = ['qualification-zero', 'qualification-point', 'a0-m0-t0',
             'artificial-line', 'artificial-point', 'artificial-mixed', 'artificial-segmented',
             'event-m0-t0', 'a0-m0-t1', 'event-m0-t1',
             'a0-m1-t0', 'event-m1-t0', 'a0-m1-t1', 'event-m1-t1']
    value = dict(schema='dram-see-v4-nuclear-closure-contract-r1', revision=1,
      goal='One geometry-matched natural nuclear event with all-event joint 3D source, matched A0 response, native field and numerical-sensitivity acceptance',
      geometry=c.ref(c.GEOMETRY), primary_roles=roles,
      budgets=dict(tcad_primary=14, tcad_corrective=4, tcad_total=18,
        transport_primary_calls=107, transport_corrective_calls=2,
        transport_unique_primaries=1000008, transport_replay_primaries=20000,
        natural_sampling_dispatch_hours=48, storage_GiB=160,
        minimum_remote_free_GiB=8, minimum_local_free_GiB=20,
        minimum_remote_available_memory_GiB=4),
      transport=dict(stage_order=['P0','N1','N2','N3','N4'],
        complete_started_stage_before_witness_selection=True,
        selection='first frozen request order, then numeric event_id; native protonInelastic ancestry with positive descendant Si ionization during 0<=device_t<=4ns',
        no_biasing=True, no_seed_search=True, no_thick_target_relocation=True,
        probability_claims=False, deadline_blocks_new_submissions_only=True),
      source=dict(spatial_w_um=0.03, temporal_sigma_s=2e-12,
        silicon_eV_per_pair=3.6, elementary_charge_C=1.602176634e-19,
        device_time_offset_s=1e-9, device_window_s=[0,4e-9],
        kernel='normalized isotropic spatial Gaussian convolved uniformly over original endpoint chord and correlated original step times; zero chord has point spatial support',
        zero_length_positive_energy='retain as point; never invent length',
        clipping='Si only, spatial/window/other-material allocations explicit, no renormalization',
        source_sign='negative PMI net recombination; native qualification mandatory',
        model_assumptions_not_calibration=True),
      numerical=dict(mesh_scales={'m0':1.0,'m1':0.75},
        time_scales={'t0':1.0,'t1':0.5},pulse_max_step_s=5e-13,
        readout_max_step_s=5e-12,readout_window_s=[3e-9,4e-9],
        shared_native_checkpoints='explicit TurningPoints with nested time grid; all accepted points retained',
        comparisons=[['m0-t0','m0-t1'],['m1-t0','m1-t1'],
                     ['m0-t0','m1-t0'],['m0-t1','m1-t1'],['m0-t0','m1-t1']]),
      tolerances=dict(offline_charge_abs_fC=1e-6,offline_charge_relative=0.001,
        native_source_relative=0.05,centroid_abs_um=0.01,time_centroid_abs_s=5e-13,
        roi_fraction_abs=0.05,partition_relative=0.05,be_waveform_relative=0.05,
        equivalent_charge_abs_fC=1e-4,equivalent_voltage_abs_V=1e-5,
        equivalent_current_abs_A=1e-12,equivalent_current_relative=0.001,
        equivalent_generation_relative=0.001,
        refinement_charge_relative=0.02,refinement_voltage_abs_V=0.001,
        refinement_voltage_relative=0.05,kcl_charge_abs_fC=1e-4,kcl_relative=0.01),
      exclusions=['no training','no persistent upset labels','no calibrated 90nm claim','no probability or environment rate','no installing software','no git commit/push','no external messages'],
      old_plan=dict(status='SUPERSEDED_PARTIAL',roles_passed=15,roles_total=17,
        new_calls=16,including_history=21,reserve_used=0,
        fine_a1_passed=False,continue_old_a5=False,
        failed_outcome=c.ref(c.ROOT/'local_runtime/dram-see-v4/interface-completion-r1/outcomes/r5-a1-b1-fine-r1.json')))
    return value, transport


def main():
    a,b=values()
    for filename,value in [('contract.json',a),('transport-contract.json',b)]:
        p=c.HERE/filename
        if p.exists():
            c.require(c.read(p)==value,'Existing contract differs: '+filename)
        else:c.write(p,value)
    print('CONTRACTS_MATERIALIZED_NO_EXECUTION')


if __name__=='__main__':main()
