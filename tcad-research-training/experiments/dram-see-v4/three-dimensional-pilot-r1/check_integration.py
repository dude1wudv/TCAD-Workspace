"""Offline integration only: build nothing, dispatch nothing, record exact inputs."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tarfile
from datetime import datetime, timezone

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def module(path,name):
    spec=importlib.util.spec_from_file_location(name,path);obj=importlib.util.module_from_spec(spec)
    sys.modules[name]=obj;exec(compile(path.read_bytes(),str(path),'exec'),obj.__dict__);return obj


def main(output):
    output=output.resolve()
    assert output.is_relative_to(ROOT/'local_runtime/dram-see-v4/three-dimensional-pilot-r1/validation')
    output.mkdir(parents=True,exist_ok=False)
    report=dict(schema='dram-see-v4-pilot-offline-integration-r1',passed=False,
                created_utc=datetime.now(timezone.utc).isoformat(),checks={},errors=[],new_solver_calls=0,
                native_execution_verified=False,synthetic_archive_not_experimental_evidence=True)
    try:
        b=module(HERE.parent/'source-interface-3d-r1/build_interface.py','_integrated_builder')
        f=module(HERE.parent/'source-field-audit-3d-r1/audit_fields.py','_integrated_fields')
        t=module(HERE.parent/'matched-transport-r1/control.py','_integrated_transport')
        old=module(HERE.parent/'interface-completion-r1/campaign_runner.py','_integrated_old')
        old.check_release();report['checks']['old_source_and_historical_evidence_unchanged']=True
        projects={case:ROOT/'local_runtime/dram-see-v4/source-interface-3d-r1/inputs'/('v4-source-interface-3d-r1-'+case.lower()+'-b1-main') for case in ('A0','A1')}
        for case,path in projects.items():
            report['checks'][case+'_frozen_input']=b.check_project(path)
            # The synthetic archive contains only exact candidate input bytes.
            # It cannot pass a native run audit and is explicitly labelled.
            archive=output/('synthetic-'+case+'-inputs-only.tar')
            with tarfile.open(archive,'w') as tar:
                for p in path.iterdir():
                    if p.is_file():tar.add(p,arcname=p.name,recursive=False)
            with f.Archive(archive) as tar:
                p,s=f.check_builder_archive(tar,path)
                assert p['case_id']==case and s['case_id']==case
            report['checks'][case+'_field_contract_matches_builder']=True
        report['checks']['matching_3d_A0_A1']=b.check_control(projects['A0'],projects['A1'])
        contract=t.contract()
        assert contract['geometry_sha256']==b.sha(b.GEOMETRY_CONTRACT.read_bytes())
        assert len(contract['requests'])==6 and sum(r['event_count'] for r in contract['requests'])==8
        build=ROOT/'local_runtime/dram-see-v4/matched-transport-r1/inputs/matched-build-r1'
        assert (build/'geometry.hh').read_text(encoding='utf-8')==t.header(contract)
        for name,source in [('geometry-contract.json',b.GEOMETRY_CONTRACT),('matched-contract.json',t.HERE/'matched-contract.json'),('transport_matched.cc',t.HERE/'transport_matched.cc')]:
            assert (build/name).read_bytes()==source.read_bytes(),name
        report['checks']['same_geometry_transport_package_and_fixed_budget']=True
        for path in [HERE/'control.py',HERE/'campaign_runner.py',HERE/'acceptance.py',HERE/'report.py']:
            compile(path.read_bytes(),str(path),'exec')
        report['checks']['orchestration_python_compilation']=True
        report['source_sha256']={}
        for folder in [HERE,HERE.parent/'source-interface-3d-r1',HERE.parent/'source-field-audit-3d-r1',HERE.parent/'matched-transport-r1']:
            for p in sorted(folder.iterdir()):
                if p.is_file():report['source_sha256'][p.relative_to(ROOT).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
        report['passed']=True
    except Exception as exc:
        report['errors'].append(repr(exc))
    (output/'evidence.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'errors':report['errors'],'evidence':str(output/'evidence.json')},ensure_ascii=False,indent=2))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path)
    raise SystemExit(main(parser.parse_args().output))
