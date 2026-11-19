"""S2 original-archive audit adapter; no launches, writes or native receipts.

Scientific field gates are reused unchanged from the frozen S2 implementation.
Observed facts, execution authority and geometry qualification are separate.
"""
import argparse
import json
from pathlib import Path
import re
import tarfile

import evidence as E

B, Archive, require, sha = E.B, E.Archive, E.require, E.sha


def _observations(report):
    require(not report['observation_gaps'], 'Required original observations unavailable: '+', '.join(report['observation_gaps']))
    f=report['facts']
    for key in ('ssh_exit_code','remote_exit_code','collection_exit_code','tool_exit_code'):
        require(f[key]['evidence_kind']=='observed' and type(f[key]['value']) is int and f[key]['value']==0,
                'Unknown/nonzero original '+key)
    require(f['tool_version']['value']=='W-2024.09','Unexpected installed native tool version')
    require(f['native_compute_threads']['value']==1,'Native numerical threading differs')
    require(f['tool_affinity']['value']['threads']==1,'Native process thread observation differs')


def _release(archive, solver_report, extraction_report, synthetic):
    release=E.object_json(archive.read('execution-release.json'),'execution release')
    require(release.get('schema')=='s2-execution-release-r1' and release.get('status')=='RELEASED', 'Missing released execution contract')
    require(release.get('execution_enabled') is True and release.get('explicit_native_authorization') is True,'Unapproved execution release')
    require(release.get('scheduler')=='root' and type(release.get('threads')) is int and release['threads']==1
            and type(release.get('cpu_count')) is int and release['cpu_count']==1,'Scheduler/core/thread mismatch')
    require(release.get('budget_id') and release.get('budget_reservation_id') and
            re.fullmatch(r'[a-f0-9]{64}',release.get('budget_ledger_sha256','')),'Missing budget reservation binding')
    require(release.get('synthetic') is synthetic,'Execution release origin mismatch')
    interface=E.mapping(release.get('interface_sha256'),'released interface hashes')
    for name in ('evidence.py','audit.py'):
        require(interface.get(name)==sha(E.HERE/name),'Audit interface version is not released: '+name)
    require(release.get('expected_runner_sha256')==solver_report['producer_sha256'] and
            re.fullmatch(r'[a-f0-9]{64}',release.get('expected_runner_sha256','')),'Solver producer version mismatch')
    require(release.get('expected_operation_sha256')==extraction_report['producer_sha256'] and
            re.fullmatch(r'[a-f0-9]{64}',release.get('expected_operation_sha256','')),'Extractor producer version mismatch')
    for report in (solver_report,extraction_report):
        require(report['facts']['shared_lock']['value']['lock_path']==release.get('shared_lock_path'),'Wrong shared lock path')
    # Native authority is supplied as an immutable input; never inferred from a
    # successful solver exit or a file called project.json.
    authority_name=release.get('authorization_evidence_file')
    require(authority_name and archive.digest(authority_name)==release.get('authorization_evidence_sha256'),'Missing human authorization evidence binding')
    authority=E.object_json(archive.read(authority_name),'authorization evidence')
    roles=authority.get('role_ids')
    require(isinstance(roles,list) and roles and all(isinstance(x,str) and x for x in roles)
            and len(set(roles))==len(roles),'Authorization roles must be an explicit unique list')
    require(authority.get('synthetic') is synthetic and authority.get('explicit_native_authorization') is True
            and release.get('role_id') in roles, 'Authority scope/origin mismatch')
    return release


def _geometry(archive, release, spec, synthetic):
    report=E.object_json(archive.read('geometry-validation.json'),'geometry validation')
    require(report.get('schema')=='s2-native-geometry-validation-r1' and report.get('synthetic') is synthetic,
            'Nominal CAD contract is not native geometry qualification')
    require(report.get('origin')==('synthetic_fixture' if synthetic else 'native_pipeline'),'Geometry provenance mismatch')
    checks=E.mapping(report.get('checks'),'geometry checks')
    require(all(checks.get(k) is True for k in ('materials','contacts','doping','units')),'Native geometry/material/contact/doping gate missing or failed')
    require(report.get('mesh_sha256')==archive.digest('cell_msh.tdr'),'Geometry/actual mesh identity mismatch')
    expected=E.mapping(report.get('evidence_sha256'),'geometry evidence hashes')
    require(all(k in expected for k in ('material-measurements.csv','contact-measurements.csv','doping-measurements.csv')),'Geometry has no measured evidence inventory')
    for name,digest in expected.items():
        require(archive.digest(name)==digest,'Native geometry evidence changed: '+name)
        require(archive.members[name].size>0,'Empty native geometry evidence')
    if spec['case']=='A0':
        require(release.get('d3_mesh_sha256')==report['mesh_sha256'] and release.get('d3_producer_run_id'),
                'A0 does not bind the accepted D3 mesh producer')
    return report


def _analyze(solver, extraction, package, synthetic):
    solver,extraction,package=map(Path,(solver,extraction,package))
    out=dict(schema='s2-evidence-field-audit-r1',passed=False,native_qualified=False,
             circuit_audit_passed=False,overall_source_interface_passed=False,
             synthetic=synthetic,is_tcad_result=False,native_calls=0,errors=[])
    try:
        sr=E.inspect(solver,'solver'); er=E.inspect(extraction,'extraction')
        out['observations']={'solver':sr,'extraction':er}
        origin='synthetic_fixture' if synthetic else 'native_pipeline'
        require(sr['origin']==er['origin']==origin and sr['synthetic'] is synthetic and er['synthetic'] is synthetic,
                'Synthetic/historical/unknown provenance cannot qualify as native')
        _observations(sr); _observations(er)
        B.OLD.check_dependencies()
        require(solver.name==sr['identity'],'Solver directory/run identity mismatch')
        with Archive(solver/'results.tar') as sa, Archive(extraction/'results.tar') as ea:
            require('ENGINEERING_RUN_COMPLETED' in sa.read('execution.log').decode().splitlines(),'Solver wrapper did not complete')
            require('FIELD_AUDIT_COMPLETED mandatory_errors=0' in ea.read('svisual.log').decode().splitlines(),'Extractor native completion missing')
            require('NATIVE_FIELD_POSTPROCESS_COMPLETED' in ea.read('execution.log').decode().splitlines(),'Extraction operation completion missing')
            release=_release(sa,sr,er,synthetic)
            spec=E.object_json(sa.read('source-spec.json'),'source specification'); B.validate_spec(spec)
            require(E.object_json(ea.read('source-spec.json'),'extractor source specification')==spec,'Extracted bit/case/variant differs')
            require(type(release.get('stored_bit')) is int and release['stored_bit']==spec['stored_bit'] and release.get('source_case')==spec['case']
                    and release.get('numerical_variant')==spec['numerical_variant'],'Release/source identity differs')
            _geometry(sa,release,spec,synthetic)
            device=sa.read('device.cmd').decode()
            if spec['case']=='A0':
                require(re.search(r'\bHeavyIon\s*\(',device) is None,'A0 has an active source')
                require(release.get('activated_source_include_files')==[],'A0 declares activated includes')
            else:
                prefix='' if spec['case']=='Aalpha' else spec['case']+'.'
                includes=[prefix+'heavyion.physics.inc',prefix+'source.par']
                require(release.get('activated_source_include_files')==includes,'Activated source include inventory differs')
                require(all(sa.digest(n)==sha(package/n) for n in includes),'Actual source differs from reviewed source')
            for name in ('source-contract.json','field-contract.json','alpha-reference.json','alpha-profile.csv'):
                require(sa.digest(name)==sha(package/name),'Source contract/reference bytes changed: '+name)
            for name in ('field-contract.json','extract_fields.tcl','windows.tcldata'):
                require(ea.digest(name)==sha(package/name),'Extractor contract changed: '+name)
            require(ea.digest('extract_fields.tcl')==sha(B.HERE/'extract_fields.tcl'),'Executed field extractor differs from frozen code')
            source=E.object_json(sa.read('source-contract.json'),'source contract')
            for name,digest in E.mapping(source.get('dependency_sha256'),'source dependencies').items():
                require(sha(B.A.ROOT/name)==digest,'Frozen scientific dependency changed: '+name)
            files=ea.read('tdr-files.txt').decode().splitlines()
            expected={name for name in sa.members if B.FRAME.fullmatch(name)}
            require(len(files)==len(expected) and set(files)==expected,'Native frame inventory omitted/duplicated files')
            require(not any(n.lower().endswith('.tdr') for n in ea.members),'Extractor copied source TDR payload')
            hashes={n:sa.digest(n) for n in files}; sizes={n:sa.members[n].size for n in files}
            require(ea.read('tdr-sha256.txt').decode()==''.join(hashes[n]+'  '+n+'\n' for n in files),'Original TDR hash inventory differs')
            directory=ea.read('source-directory.txt').decode().strip()
            require(re.fullmatch(r'(/[A-Za-z0-9_.-]+)+',directory) and directory==sr['remote_directory'],'Wrong original source directory')
            require(ea.read('source-case.txt').decode().strip()==spec['case'],'Source case inventory differs')
            references=B.OLD.verify_reference_checks(ea.read('source-reference-checks.csv').decode(),files,hashes,sizes,directory)
            raw=ea.read('field-measurements.csv').decode(); inventory=ea.read('field-inventory.csv').decode()
            B.PRIOR.check_cleanup(raw,files,'exact_deleted_object_name',inventory)
            status=dict(line.split('=',1) for line in ea.read('diagnostic-status.txt').decode().splitlines() if '=' in line)
            require(status.get('schema')=='s2-native-field-extraction-r1' and status.get('dimension')=='3'
                    and status.get('integration')=='volume_um3' and status.get('mandatory_command_errors')=='0','Bad extractor status')
            require(status.get('files_requested')==status.get('files_completed')==str(len(files)),'Incomplete native frame count')
            require(status.get('reference_mode')=='referenced_original_tdr_not_copied'
                    and status.get('memory_release')=='plot_then_dataset_per_frame'
                    and status.get('cleanup_success')=='exact_deleted_object_name','Invalid source-reference/cleanup mode')
            log=sa.read('transient_des.log').decode()
            require('Sentaurus Device simulation finished' in log,'SDevice completion missing')
            _, raw_rows=B.OLD.old.parse_plt(sa.read('access_device.plt').decode())
            rows,duplicates=B.clean_source_times(raw_rows)
            mapping=B.index_frames(log,rows,files,spec); mapping['PLT_duplicate_handling']=duplicates
            values=B.parse_measurements(raw,files,spec)
            metadata=B.verify_inventory_metadata(inventory,ea.read('tdr-state-metadata.csv').decode(),files,values)
            reference=json.loads((package/'alpha-reference.json').read_text(encoding='utf-8'))
            reproduced=B.A.source_expected(source['model_snapshot'])
            reproduced['cad_binding']=B.A.cad_binding(source['model_snapshot'],reproduced)
            reproduced['cad_discretization_bound']=True
            require(reference==reproduced,'Independent reference reproduction differs')
            metrics=B.measurements_metrics(mapping,values,rows,spec,reference)
            require(metrics['passed'],'; '.join(metrics['failures']))
            for folder,report in ((solver,sr),(extraction,er)):
                require(sha(folder/'results.tar')==report['archive_sha256'] and sha(folder/report['manifest_name'])==report['manifest_sha256'],
                        'Immutable evidence changed during analysis')
            out.update(passed=True,status='SYNTHETIC_ARCHIVE_PARSE_ONLY' if synthetic else 'NATIVE_FIELD_GATES_ONLY',
                       numerical_gates=metrics,mapping=mapping,metadata_check=metadata,original_reference_checks=references,
                       field_measurements_passed=not synthetic and spec['case'] not in ('A0','Z'))
    except (ValueError,OSError,KeyError,TypeError,IndexError,ZeroDivisionError,UnicodeError,tarfile.TarError) as exc:
        out['errors'].append(str(exc)); out['status']='REFUSED_MISSING_OR_INVALID_EVIDENCE'
    return out


def audit_native(solver, extraction, package):
    return _analyze(solver,extraction,package,False)


def audit_fixture(solver, extraction, package):
    """Isolated parser test only: impossible to grant native qualification."""
    solver,extraction,package=map(Path,(solver,extraction,package))
    require(solver.parent==extraction.parent==package.parent,'Fixture directories do not share isolation root')
    require('UNIT_FIXTURE_NOT_NATIVE' in solver.parent.name,'Synthetic test root not explicitly isolated')
    marker=E.object_json((solver.parent/'fixture-manifest.json').read_text(),'synthetic fixture marker')
    require(marker.get('synthetic') is True,'Missing explicit synthetic fixture marker')
    return _analyze(solver,extraction,package,True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for flag in ('solver','extraction','package'): p.add_argument('--'+flag,required=True,type=Path)
    args=p.parse_args()
    result=audit_native(args.solver,args.extraction,args.package)
    print(json.dumps(result,indent=2,allow_nan=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
