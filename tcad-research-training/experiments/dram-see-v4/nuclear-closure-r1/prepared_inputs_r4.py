"""Reuse a complete, never-launched material-r2 package after preflight refusal."""
import hashlib
from pathlib import Path
import shlex
import common as c
import transport_material_r2 as t


def expected_inputs(label, build):
    r=t.request(label)
    if r['mode']!='init':t.require_initialization_gate()
    build=Path(build).resolve()
    t.assert_operation_complete(build)
    for name,path in [('transport_matched.cc',c.HERE/'transport_material_r2.cc'),
                      ('matched-contract.json',c.HERE/'transport-contract-material-r2.json'),
                      ('geometry-contract.json',c.GEOMETRY)]:
        c.require(c.sha(build/'collected'/name)==c.sha(path),'Build/source mismatch: '+name)
    c.require((build/'collected/geometry.hh').read_text()==t.header(t.contract()),'Header differs')
    names=('transport_matched','transport_matched.cc','geometry.hh','matched-contract.json',
           'geometry-contract.json','environment.sh','dataset-inventory.json','environment-spec.json')
    files={name:(build/'collected'/name).read_bytes() for name in names}
    files['request.json']=c.encoded(r)
    files['package-origin.json']=c.encoded(dict(build_operation_path=build.relative_to(c.ROOT).as_posix(),
        build_operation_sha256=c.sha(build/'operation.json'),control_sha256=c.sha(c.HERE/'transport_material_r2.py')))
    files['input-hashes.sha256']=''.join(hashlib.sha256(raw).hexdigest()+'  '+name+'\n'
        for name,raw in sorted(files.items())).encode()
    script='\n'.join(['set -euo pipefail','sha256sum -c input-hashes.sha256','source environment.sh',
        'chmod u+x transport_matched',
        "printf '%s  binary\\n' \"$(sha256sum transport_matched | cut -d ' ' -f1)\" > provenance.sha256",
        "printf '%s  environment\\n' \"$(sha256sum environment.sh | cut -d ' ' -f1)\" >> provenance.sha256",
        "printf '%s  dataset_inventory\\n' \"$(sha256sum dataset-inventory.json | cut -d ' ' -f1)\" >> provenance.sha256",
        './transport_matched '+shlex.quote(label),''])
    files['task.sh']=script.encode()
    return files


def reuse_or_prepare(label,build):
    folder=c.OLD_OPS/'inputs'/label
    c.require(not (c.RT/'attempts'/(label+'.json')).exists(), 'Attempt already exists; original-directory reconciliation only')
    c.require(not (c.OLD_OPS/'operations'/label).exists(), 'Original operation exists; do not launch again')
    if not folder.exists():return t.prepare(label,build)
    c.require(not folder.is_symlink() and folder.is_dir(),'Prepared input directory is not plain')
    expected=expected_inputs(label,build)
    c.require({p.name for p in folder.iterdir()}==set(expected),'Prepared input inventory differs')
    for name,raw in expected.items():
        path=folder/name
        c.require(path.is_file() and not path.is_symlink() and path.read_bytes()==raw,
                  'Prepared input bytes differ: '+name)
    proof=dict(schema='nuclear-closure-unlaunched-input-reconciliation-r4',label=label,
        input_sha256={name:hashlib.sha256(raw).hexdigest() for name,raw in sorted(expected.items())},
        build=c.ref(Path(build)/'operation.json'),no_attempt_or_operation=True,
        scope='Exact original material-r2 bytes reused after a preflight refusal; no submission performed here.')
    dest=c.RT/'prepared-input-recovery-r4'/(label+'.json')
    if dest.exists():c.require(c.read(dest)==proof,'Prepared input recovery proof changed')
    else:c.write(dest,proof)
    return folder
