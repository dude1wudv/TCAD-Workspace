"""Explicit R50 adaptation of original independent component inspection.

Never promotes failed raw data into a passed metrics bundle. See inspection.py.diff.
"""
import importlib.util
import json
import math
from pathlib import Path
import re
import tarfile
HERE = Path(__file__).resolve().parent
PRECHARGE_ERROR = 'Precharge error exceeds 10 uV'
_spec = importlib.util.spec_from_file_location('_r50_inspection_audit', HERE / 'audit.py')
A = importlib.util.module_from_spec(_spec)
exec(compile((HERE / 'audit.py').read_bytes(), str(HERE / 'audit.py'), 'exec'), A.__dict__)


def inspect_run(run_id, ledger_row=None):
    """Read-only diagnosis, retaining the unmodified audit and independent checks.

    Diagnostic values never receive NUMERICAL_CONTRACT_PASSED by substitution.
    The returned curve is private calculation input; the JSON record is explicit
    about failure and ineligibility for training even when the raw audit passes.
    """
    record = {'run_id': run_id, 'physical_revision_probe_only': True, 'diagnostic_only': True, 'training_or_prediction_eligible': False, 'checks': {}}
    def checked(name, action):
        try:
            result = action()
            record['checks'][name] = {'passed': True, 'result': result}
            return result
        except Exception as exc:
            record['checks'][name] = {'passed': False, 'error': repr(exc)}
            return None
    try:
        summary = A.audit(run_id, export=False)
        record.update(raw_audit_state='PASSED', raw_audit_status=summary['audit_status'], raw_audit_error=None)
    except Exception as exc:
        summary = None
        record.update(raw_audit_state='FAILED', raw_audit_status=None, raw_audit_error=repr(exc))
    run_folder, manifest = A.manifest_checked(run_id)  # strict COLLECTED/SSH0, never a recovery exception
    record.update(archive_sha256=A.sha(run_folder / 'results.tar'), manifest_sha256=A.sha(run_folder / 'manifest.json'),
                  inputs_archive_sha256=A.sha(run_folder / 'inputs.tar'), engineering_state=manifest['state'],
                  ssh_exit_code=manifest['ssh_exit_code'], runner_exit_code=(ledger_row or {}).get('runner_exit_code'))
    with tarfile.open(run_folder / 'results.tar') as archive:
        log = A.completion_checked(archive, manifest)
        p = json.loads(A.read(archive, 'parameters.json'))
        if p.get('schema') != 'dram-see-v3-precharge-r50':
            p, bridge = A.legacy_parameters(archive, p, run_id)
            record['legacy_bridge'] = bridge
        A.parameters_checked(p, archive)
        _, raw = A.parse_plt(A.read(archive, 'circuit.plt').decode())
        circuit = A.clean(raw)
        _, raw_device = A.parse_plt(A.read(archive, 'access_device.plt').decode())
        device = A.clean(raw_device)
        if p['reference_mode'] != 'offline':
            raise ValueError('This diagnosis only permits single offline signal/neutral branches')
        record.update(parameters=p, input_sha256=manifest['input_sha256'], matching_contract=A.matching_key(p),
                      matching_contract_sha256=p['matching_contract_sha256'])
        phases = checked('conservation', lambda: A.conservation(raw, {'access': device}, p))
        if phases is not None:
            _, balances, kcl, ports, closure = phases
            record['checks']['conservation']['result'] = {'BE_charge_checks': balances, 'max_kcl_A': kcl,
                                                         'port_integrals_fC': ports, 'four_terminal_closure': closure}
        hold = A.segment(raw, p['prestrike_s'], p['hold_end_s'], first=True)
        pre = A.segment(raw, p['hold_end_s'], p['precharge_end_s'], first=True)
        endpoint = pre[-1]
        def assertion(value, error):
            if not value:
                raise ValueError(error)
            return True
        checked('final_time', lambda: assertion(all(abs(rows[-1]['time'] - 4e-9) <= 1e-18 for rows in (circuit, device)), 'Incomplete 4 ns endpoint'))
        checked('initial_SN', lambda: assertion(abs(hold[0]['v(sn)'] - p['target_voltage_V']) <= .001, 'Initial SN target exceeds 1 mV'))
        checked('hold_waveform', lambda: assertion(all(max(abs(row['v(wl)']), abs(row['v(bl)'])) <= 1e-8 for row in hold[:-1]), 'Hold waveform differs'))
        checked('read_wordline', lambda: assertion(all(abs(row['v(wl)'] - 1.8 * min(1, max(0, (row['time'] - 3.05e-9) / .05e-9))) <= 1e-7 for row in circuit), 'Read wordline waveform differs'))
        checked('source', lambda: A.source_checked(archive, p, manifest, device, None))
        checked('restart', lambda: A.restart_checked(archive, p))
        hashes = checked('tdr_members', lambda: {name: A.sha_bytes(A.read(archive, name)) for name in
                     ('cell_msh.tdr', 'prestrike_access_des.tdr', 'strike_access_des.tdr', 'hold_access_des.tdr', 'final_access_des.tdr')})
        if hashes:
            record.update(tdr_sha256=hashes, mesh_sha256=hashes['cell_msh.tdr'])
        wall = re.search(r'wallclock:\s*([\d.]+) s', log)
        checked('wallclock', lambda: assertion(bool(wall) and math.isfinite(float(wall[1])) and float(wall[1]) > 0, 'Invalid solver wallclock'))
        record.update(solver_s=float(wall[1]) if wall else None, final_time_s=circuit[-1]['time'],
                      precharge={'time_s': endpoint['time'], 'target_V': .5, 'tolerance_V': 1e-5,
                                 'BL_V': endpoint['v(bl)'], 'REF_V': endpoint['v(ref)'],
                                 'BL_error_uV': (endpoint['v(bl)'] - .5) * 1e6, 'REF_error_uV': (endpoint['v(ref)'] - .5) * 1e6,
                                 'passed': abs(endpoint['v(bl)'] - .5) <= 1e-5 and abs(endpoint['v(ref)'] - .5) <= 1e-5,
                                 'exact_boundary_rows': [row for row in raw if abs(row['time'] - 3e-9) <= 1e-20]},
                      SN_2p8ns_V=A.sample(circuit, 'v(sn)', 2.8e-9), BL_4ns_V=A.sample(circuit, 'v(bl)', 4e-9),
                      REF_4ns_V=A.sample(circuit, 'v(ref)', 4e-9), SN_4ns_V=A.sample(circuit, 'v(sn)', 4e-9))
    others_passed = all(check['passed'] for check in record['checks'].values())
    record['independent_checks_passed'] = others_passed
    record['precharge_only_scientific_failure'] = (record['raw_audit_error'] == repr(ValueError(PRECHARGE_ERROR))
        and record['precharge']['passed'] is False and others_passed
        and (ledger_row or {}).get('state') == 'FAILED' and (ledger_row or {}).get('runner_exit_code') == 0
        and (ledger_row or {}).get('failure_reason') == repr(ValueError(PRECHARGE_ERROR)))
    return {'record': record, 'parameters': p, 'circuit': circuit, 'summary': summary}

