"""Root acceptance of native pilot outputs; preserves complete curves and failures."""
import argparse
import csv
import importlib.util
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('_pilot_accept_control', HERE/'control.py')
c = importlib.util.module_from_spec(spec); sys.modules[spec.name]=c; spec.loader.exec_module(c)


def native_mesh(archive):
    report = json.loads(archive.read('mesh-resource-report.json'))
    c.require(report.get('passed') is True, 'Native mesh resource guard did not pass')
    c.require(archive.read('mesh-resource-report.json') == archive.read('mesh-resource-passed.json'), 'Guard success marker differs')
    c.require(report['mesh_sha256'] == archive.digest('cell_msh.tdr'), 'Guard belongs to another mesh')
    c.require(report['mesh_log_sha256'] == archive.digest('cell_msh.log'), 'Guard log differs')
    c.require(report['input_manifest_sha256'] == archive.digest('input-manifest.json'), 'Guard input differs')
    log = archive.read('transient_des.log').decode(errors='replace')
    tetra = re.findall(r'NumberOfTetrahedr(?:a|ons|on)\s*=\s*(\d+)', log)
    c.require(len(tetra) == 1 and int(tetra[0]) > 0, 'No unambiguous native tetrahedral volume mesh evidence')
    nodes = re.findall(r'Number of grid points is\s+(\d+)', log)
    c.require(len(nodes) == 1 and int(nodes[0]) > 0, 'Ambiguous native solver grid-point count')
    return dict(resource_guard=report, native_tetrahedra=int(tetra[0]), sdevice_grid_points=int(nodes[0]),
                mesh_sha256=archive.digest('cell_msh.tdr'),
                boundary_scope='Shared input face assignment plus successful native electrode initialization; no calibrated physical edge model')


def load(label, field_path):
    launch = c.STATE/'calls'/label/'execution.json'
    record = c.read(launch)
    c.require(record['kind']=='tcad' and record['state']=='COMPLETED', 'Call is not a completed TCAD operation')
    c.require(record['campaign_sha256']==c.sha(HERE/'campaign.json'), 'Call contract changed')
    field_path=Path(field_path).resolve(); field=c.read(field_path)
    validate_field_metadata(field)
    run = c.ROOT/'local_runtime/runs'/record['run_id']; project=c.ROOT/record['project']
    f=c.module(c.V4/'source-field-audit-3d-r1/audit_fields.py','_pilot_accept_fields')
    c.require(field['run_id']==run.name, 'Field evidence belongs to another run')
    c.require(field['audit_code_sha256']==c.sha(c.V4/'source-field-audit-3d-r1/audit_fields.py'), 'Field audit implementation changed')
    operation_record=(c.ROOT/field['extraction_record']['operation_record']).resolve()
    c.require(operation_record.is_relative_to(c.RT/'transport-probe/operations'), 'Unexpected field operation path')
    # Reproduce the actual acceptance rather than trusting a top-level passed bit.
    recomputed=f.audit(run,operation_record.parent,project)
    validate_field_metadata(recomputed)
    ignored={'frames_csv_path','frames_csv_sha256'}
    c.require({k:v for k,v in field.items() if k not in ignored} == recomputed,
              'Saved field audit does not reproduce from original native evidence')
    if 'frames_csv_path' in field:
        frames=Path(field['frames_csv_path']).resolve()
        c.require(frames.parent==field_path.parent and c.sha(frames)==field['frames_csv_sha256'], 'Saved field frame table changed')
    original = f.old
    detail={}
    manifest=original._manifest(run,detail)
    with original.Archive(run/'results.tar') as archive:
        original._provenance(archive,manifest,run,project,detail)
        p,source=f.check_builder_archive(archive,project)
        curves=original._curves(archive,detail)
        original._response(p,curves,detail)
        mesh=native_mesh(archive)
        c.require(p['case_id'].lower()+'-b1-3d'==record['role'], 'Archived role differs')
    c.require(field['archive_sha256']==detail['archive_sha256'] and field['manifest_sha256']==detail['manifest_sha256'], 'Field archive binding changed')
    return dict(record=record, field=field, field_path=field_path, run=run, project=project,
                parameters=p, source=source, curves=curves, detail=detail, mesh=mesh, launch=launch)


def validate_field_metadata(field):
    required={'frozen_readonly_dependencies','solver_manifest','original_solver_provenance',
              'frozen_3d_source_contract','complete_raw_curves','original_extraction_provenance',
              'native_geometry_doping_probes','accepted_BE_Writing_PLT_bijection',
              'native_3d_volume_field_gates','safe_original_archive_read'}
    c.require(field.get('schema')=='source-field-audit-3d-r1' and field.get('mode')=='full' and field.get('dimension')==3,
              'Wrong native field audit schema/mode/dimension')
    c.require(field.get('passed') is True and field.get('errors')==[], 'Native field audit contains a failure')
    checks=field.get('checks')
    c.require(isinstance(checks,dict) and set(checks)==required and all(v == {'passed': True} for v in checks.values()),
              'Native field audit has missing/failed checks')
    c.require(field.get('geometry_doping',{}).get('passed') is True, 'Native geometry doping evidence failed')


def csv_write(path, rows):
    with path.open('x',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def accept(label, field_path):
    folder=c.STATE/'audits'/label
    c.require(not folder.exists(),'Acceptance exists; preserve it and use a diagnosed new audit revision')
    folder.mkdir(parents=True)
    report=dict(schema='dram-see-v4-native-3d-pilot-acceptance-r1',created_utc=c.utc(),passed=False,
                errors=[],scientific_calibration_passed=False,numerical_convergence_validated=False,
                nuclear_joint_response_completed=False,upset_labels_generated=False,
                acceptance_code_sha256=c.sha(Path(__file__)))
    evidence = None
    value = None
    try:
        value=load(label,field_path); role=value['record']['role']
        report.update(role=role,run_id=value['run'].name,detail=value['detail'],mesh=value['mesh'],
                      field_evidence=c.reference(value['field_path']))
        evidence=[c.reference(value['launch']),c.reference(value['field_path']),c.reference(value['run']/'manifest.json')]
        for name in ('circuit','device'):
            csv_write(folder/(name+'-complete.csv'),value['curves'][name])
        if role=='a1-b1-3d':
            gate=c.read(c.STATE/'gates/a0-b1-3d.json');c.pilot_gate('a0-b1-3d')
            control=load(gate['label'],c.ROOT/gate['field_audit_path'])
            builder=c.module(c.V4/'source-interface-3d-r1/build_interface.py','_pilot_accept_builder')
            matching=builder.check_control(control['project'],value['project'])
            c.require(control['mesh']['mesh_sha256']==value['mesh']['mesh_sha256'], 'Actual native A0/A1 meshes differ')
            original=c.module(c.V4/'source-field-audit-3d-r1/audit_fields.py','_pilot_accept_sample').old
            rows=[]
            for row in value['curves']['circuit']:
                out={'time_s':row['time']}
                for key in ('v(sn)','v(bl)','v(ref)','v(wl)'):
                    zero=original.legacy.sample(control['curves']['circuit'],key,row['time'])
                    out[key]=row[key];out['control_'+key]=zero;out['delta_'+key]=row[key]-zero
                rows.append(out)
            csv_write(folder/'matched-a0-response.csv',rows)
            report.update(matching=matching,control_run_id=control['run'].name,
                          response_sampling='A1 accepted circuit samples; A0 voltage linearly sampled only for response comparison, never for source-field acceptance')
            evidence.append(c.reference(c.STATE/'gates/a0-b1-3d.json'))
        report['passed']=True
    except Exception as exc:
        report['passed']=False
        report['errors'].append(repr(exc))
    c.save(folder/'audit.json',report,new=True)
    if report['passed']:
        evidence.append(c.reference(folder/'audit.json'))
        c.save(c.STATE/'gates'/(role+'.json'),dict(schema='dram-see-v4-3d-pilot-gate-r1',role=role,label=label,
               passed=True,created_utc=c.utc(),campaign_sha256=c.sha(HERE/'campaign.json'),run_id=value['run'].name,
               field_audit_path=c.rel(value['field_path']),evidence=evidence),new=True)
    return report


if __name__=='__main__':
    import json
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('label');parser.add_argument('field_audit',type=Path)
    args=parser.parse_args();out=accept(args.label,args.field_audit);print(json.dumps(out,ensure_ascii=False,indent=2))
    raise SystemExit(0 if out['passed'] else 1)
