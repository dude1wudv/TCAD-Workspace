"""Exact allowlisted r4 mesh -> r5 main reuse; never rewrite historical evidence."""
import argparse
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(), str(path), 'exec'), obj.__dict__)
    return obj


api = module(HERE / 'audit_interface.py', '_r5_bridge_audit_helpers')
old, require, Checks, Archive = api.old, api.require, api.Checks, api.Archive


def registered(run, contract):
    run = Path(run).resolve()
    matches = [row for row in contract['reuse_roles'] if (ROOT / row['run_path']).resolve() == run]
    require(len(matches) == 1, 'Only an explicitly registered original r4 run can be reused')
    row = matches[0]
    require(row['case_id'] in ('A0', 'A1') and row['stored_bit'] == 1
            and row['original_variant'] == 'mesh' and row['canonical_variant'] == 'main'
            and row['run_id'] == run.name, 'Invalid registered alias or role')
    return row


def bound_report(row, path_key, hash_key):
    path = (ROOT / row[path_key]).resolve()
    require(old.sha_file(path) == row[hash_key], 'Registered report changed: ' + path_key)
    data = old.json_load(path.read_bytes()); api.accepted(data)
    return path, data


def physical_equivalence(archive, p, b, case):
    require(p['schema'] == 'dram-see-v4-source-interface-r4'
            and [p['case_id'], p['stored_bit'], p['variant']] == [case, 1, 'mesh'], 'Original r4 role differs')
    require(p['matching_contract_sha256'] == old.sha_bytes(old.encoded(p['matching_contract'])), 'Historical matching digest differs')
    require(all(p.get(k) == v for k, v in p['matching_contract'].items()), 'Historical matching fields conflict')
    common = dict(p['matching_contract']); common['variant'] = 'main'
    require(common == b.expected_common(1, 'main', p['geometry_sha256']), 'Alias changed additional physical/numerical parameters')
    geometry = archive.read('geometry.scm')
    require(geometry == b.render_geometry('main') and old.sha_bytes(geometry) == p['geometry_sha256'], 'Geometry differs across reuse bridge')
    source = old.json_load(archive.read('source-spec.json'))
    require(source == b.source_spec(case), 'Physical source differs across revisions')
    require(archive.read('heavyion.par').decode() == b.r2.render_parameters(source), 'HeavyIon parameter bytes differ')
    original = api.m.b.strip_r4_observers(archive.read('device.cmd').decode(), case)
    candidate = b.render_deck(case, 1, 'main')
    require(original == b.physical_deck(case, 1, 'main')
            == b.strip_observers(candidate, case, 1, 'main'), 'Circuit, physics, initialization or timing deck differs')
    old_contract = old.json_load(archive.read('source-contract.json')); new_contract = b.contract()
    for key in ('device', 'units', 'conversion', 'heavyion_parameters', 'audit_tolerances'):
        require(old_contract[key] == new_contract[key], 'Scientific/units contract differs: ' + key)
    # r5 explicitly labels the sigma already present in r4's identical formula.
    kernel = dict(new_contract['kernel'])
    require(kernel.pop('time_sigma_equals_s_hi', None) is True and kernel == old_contract['kernel'],
            'Physical temporal/spatial kernel differs across reuse bridge')
    for roi, bounds in old_contract['rois_um'].items():
        require(new_contract['rois_um'][roi] == bounds, 'Historical ROI changed')
    return dict(passed=True, original_variant='mesh', canonical_variant='main',
        canonical_matching_contract=common, canonical_matching_contract_sha256=old.sha_bytes(old.encoded(common)),
        geometry_sha256=p['geometry_sha256'], physical_deck_sha256=old.sha_bytes(original.encode()),
        source_spec_sha256=archive.digest('source-spec.json'), heavyion_sha256=archive.digest('heavyion.par'),
        historical_files_modified=False, label_only_alias=True,
        documentary_contract_additions={'kernel.time_sigma_equals_s_hi': True},
        actual_mesh_requirement='Original measured mesh hash retained; every new paired control/signal must match it exactly')


def load(run, reference_project=None, field_audit=None):
    run = Path(run).resolve(); out = api.report('dram-see-v4-source-interface-r5-reuse-audit')
    out['run_path'] = str(run); checks = Checks(out); result = {'summary': out}
    b = api.builder()
    row = checks.call('registered_original_role', lambda: registered(run, b.contract()))
    if row is None:
        return result
    def evidence():
        require(old.sha_file(run / 'manifest.json') == row['run_manifest_sha256']
                and old.sha_file(run / 'results.tar') == row['archive_sha256'], 'Original run or archive changed')
        project = (ROOT / row['project_path']).resolve()
        require(old.sha_file(project / 'input-manifest.json') == row['manifest_sha256'], 'Original input manifest changed')
        if reference_project is not None:
            require(Path(reference_project).resolve() == project, 'Reuse project must be the original registered r4 input')
        audit_path, previous = bound_report(row, 'audit_path', 'audit_sha256')
        comparison_path, comparison = bound_report(row, 'comparison_path', 'comparison_sha256')
        require(comparison['schema'] == 'dram-see-v4-mesh-diagnostic-comparison'
                and comparison['numerical_comparison_passed'] is True
                and comparison['prior_spatial_failures_promoted'] is False
                and comparison['main_grid_accepted'] is False, 'Historical comparison limits changed')
        require(comparison['audit_code_sha256'] == old.sha_file(api.V4 / 'stage2/compare_mesh_diagnostic.py')
                and comparison['integration_audit_sha256'] == old.sha_file(api.V4 / 'stage2/audit_mesh_diagnostic.py'), 'Frozen comparison implementation changed')
        for record in b.contract()['reuse_roles']:
            embedded = comparison['input_reports']['fine_' + record['case_id']]
            require(embedded['run_id'] == record['run_id'] and embedded['archive_sha256'] == record['archive_sha256']
                    and embedded['manifest_sha256'] == record['run_manifest_sha256'], 'Comparison uses different original r4 runs')
        field = None
        if row['case_id'] == 'A1':
            field, f = bound_report(row, 'field_audit_path', 'field_audit_sha256')
            require(field_audit is None or Path(field_audit).resolve() == field, 'Reuse field audit differs from registration')
            require(previous['native_field_audit']['sha256'] == row['field_audit_sha256'], 'Original source audit field binding differs')
        else:
            require(field_audit is None, 'A0 reuse does not invent a field audit')
        current = api.m.load(run, project, field)
        api.accepted(current['summary'])
        # Exact frozen original audit is re-evaluated, not promoted by editing passed flags.
        require(current['summary'] == previous, 'Original r4 audit no longer reproduces its registered report')
        result.update({key: value for key, value in current.items() if key != 'summary'})
        preserved = dict(out)
        out.update(current['summary'])
        for key in ('schema', 'checks', 'errors', 'audit_code_sha256', 'contract_sha256', 'limits'):
            out[key] = preserved[key]
        out['passed'] = False
        out['overall_source_interface_passed'] = False
        out['original_audit'] = dict(path=str(audit_path), sha256=row['audit_sha256'], schema=previous['schema'])
        out['historical_comparison'] = dict(path=str(comparison_path), sha256=row['comparison_sha256'],
            status=comparison['status'], prior_spatial_failures_promoted=False)
        with Archive(run / 'results.tar') as archive:
            bridge = physical_equivalence(archive, result['parameters'], b, row['case_id'])
            bridge.update(run_id=row['run_id'], bridge_code_sha256=old.sha_file(Path(__file__)),
                          registration_sha256=old.sha_bytes(old.encoded(row)))
            out['reuse_bridge'] = bridge
            out['canonical_matching_contract'] = bridge['canonical_matching_contract']
            out['canonical_matching_contract_sha256'] = bridge['canonical_matching_contract_sha256']
            if field:
                result['native_curves'] = api.field_frames(field, out, result['curves'], archive, revision='r1')
        result['proof'] = b.offline_proof(result['source'])
        # Preserve the native unwindowed result; never replace it with offline proof.
        rad = out['radiation']
        rad['legacy_generated_fC'] = rad.get('legacy_generated_fC', rad.get('generated_fC'))
        rad['generated_fC'] = rad['legacy_generated_fC']
        rad['target_domain_fC'] = result['proof']['domain_charge_fC']
        return True
    checks.call('frozen_reports_and_physical_alias', evidence)
    out['passed'] = not out['errors'] and len(out['checks']) == 2
    out['status'] = 'R4_ORIGINAL_REUSED_AS_R5_MAIN_CONTROL_AND_COMPARISONS_REQUIRED' if out['passed'] else 'FAILED_OR_INCOMPLETE'
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('run', type=Path)
    parser.add_argument('--project', type=Path); parser.add_argument('--field-audit', type=Path); parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(); bundle = load(args.run, args.project, args.field_audit); api.write(args.output, bundle)
    print(json.dumps({k: bundle['summary'].get(k) for k in ('passed', 'status', 'errors')}, ensure_ascii=False))
    raise SystemExit(0 if bundle['summary']['passed'] else 1)
