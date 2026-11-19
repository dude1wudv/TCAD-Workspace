"""Check real all-step time/file coverage without claiming native field extraction."""
import argparse
import importlib.util
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[3]
path=ROOT/'experiments/dram-see-v4/source-field-audit-r1/audit_fields.py'
spec=importlib.util.spec_from_file_location('_native_field_audit',path)
f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    run=a.run.resolve();output=a.output.resolve()
    f.require(output.is_relative_to(ROOT/'local_runtime/dram-see-v4/source-interface-r4/audit-dev'),'Output scope differs')
    output.mkdir(parents=True,exist_ok=False)
    result=dict(schema='dram-see-v4-real-frame-index-check',passed=False,field_measurement_verified=False,
                auditor_sha256=f.old.sha_file(path),errors=[])
    try:
        manifest=f.old._manifest(run,result)
        with f.Archive(run/'results.tar') as archive:
            f.old._provenance(archive,manifest,run,None,result)
            curves=f.old._curves(archive,result)
            files=[name for name in archive.members if re.fullmatch(r'gstep_[0-9]+_access_des\.tdr',name)]
            index,boundary=f.index_frames(archive.read('transient_des.log').decode(),curves['device'],files,True)
        result.update(passed=True,all_TDR_frames=len(files),integrated_intervals=len(index),boundary_frames=boundary,
                      accepted_intervals=index,window_start_s=index[0]['start_s'],window_end_s=index[-1]['end_s'],
                      direct_TDR_timestamp_verified=False)
    except (ValueError,OSError,KeyError,TypeError) as exc:
        result['errors'].append(str(exc))
    (output/'frame-index.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({k:result.get(k) for k in ('passed','all_TDR_frames','integrated_intervals','window_start_s','window_end_s','errors')},ensure_ascii=False))
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
