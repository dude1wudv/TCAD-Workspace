"""Pinned original helpers for the unregistered multi-condition proton candidate."""
from __future__ import annotations
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
RUNTIME=ROOT/'local_runtime/dram-see-v4/continuous/proton'
ORIGINAL_BUILD=ROOT/'local_runtime/dram-see-v4/transport-probe/operations/cgoal-bcat-build-20261017t043911z'
MATRIX=ROOT/'experiments/dram-see-v4/course-plan-r13/finite-matrix.proposed.csv'
FIXED={
    'prepare':('experiments/dram-see-v4/continuous/proton/prepare.py','2295229d1e668ec3afbb605b74ba1abea1d88b777eb5a55762bc362a5c6d7cbf'),
    'couple':('experiments/dram-see-v4/continuous/proton/couple.py','497ba3950924f31823d3ac4ebd8d1fa854d53641dc2cfcc222d1c3154957dca8'),
    'bundle':('experiments/dram-see-v4/continuous/proton/source_bundle.py','b52c60fa3e34e4065874d1391f450ac8a02036c02d2e280f16873fe0d7b2e556'),
    'reference':('experiments/dram-see-v4/continuous/proton/source_reference.py','82a5b47c685c9156f212787999c07d21d1aee249b22b3f783f89cf499da4e4ec'),
    'math':('experiments/dram-see-v4/continuous/proton/source_feature_math.py','41a9edc18ba2e447c3b9c6a11c8d993eeb2d101ef73f78a34fe2785df7b20823'),
    'geometry':('experiments/dram-see-v4/s2-inputs-r1/geometry.py','f923a8638dcfc760d7932b03094bf44195e655b7ab1cb234ed7ee7a1d004377c'),
    'matrix':('experiments/dram-see-v4/course-plan-r13/finite-matrix.proposed.csv','8cabed1334f075725f03909e14de3c16516b35039f919f8a278df9808e7d2380'),
    'transport_parent':('experiments/dram-see-v4/nuclear-closure-r1/transport_material_r2.cc','57048e000b65f3c61b57b0c2a857fc41d6ce545a2e99545b66184ebb8d657fea'),
    'geometry_cpp':('experiments/dram-see-v4/continuous/proton/bcat_geometry.inc','340a99fe1593d95b17c26bc36c98d4f996c72db2a69c61289a4e2e6e0e8ef8c1'),
}
ORIGINAL_FILES={
    'transport_bcat.cc':'3954e216b0fca01610e213c9cc2242d225a7333156a44efd829343c83c1ababb',
    'task.sh':'9c1d643adca6eb238155833fb45be7badfd4228f25229cb9c2ffaa744635f27b',
    'environment.sh':'cef690b40a4ed61118a6f3c8457d4620dae0e42afca00caa9b8a4ae605da46fe',
    'dataset-inventory.json':'a3cccfcb8c6730d2378e25c1a6bc42d3aba0c7745625c87824779adce9f1c03e',
}


def require(ok,message):
    if not ok:raise ValueError(message)


def sha(raw):return hashlib.sha256(raw).hexdigest()
def encoded(value):return (json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,indent=2)+'\n').encode()
def parse(raw):return json.loads(raw,parse_constant=lambda value:(_ for _ in ()).throw(ValueError('Nonfinite JSON: '+value)))
def read(path):return parse(Path(path).read_bytes())
def ref(path):return dict(path=str(Path(path).resolve()),sha256=sha(Path(path).read_bytes()))


def pinned(path,digest):
    raw=Path(path).read_bytes();require(sha(raw)==digest,'Pinned original changed: '+str(path));return raw


def stable():
    return {name:dict(path=str(ROOT/path),sha256=digest) for name,(path,digest) in FIXED.items()
            if pinned(ROOT/path,digest) is not None}


def module(path,name,digest=None):
    path=Path(path).resolve();raw=path.read_bytes()
    require(digest is None or sha(raw)==digest,'Fixed executable identity changed: '+path.name)
    spec=importlib.util.spec_from_file_location(name,path);result=importlib.util.module_from_spec(spec)
    exec(compile(raw,str(path),'exec'),result.__dict__);result._loaded_source_sha256=sha(raw)
    return result


def load_originals():
    stable();loaded={};saved={key:sys.modules.get(key) for key in ('prepare','couple','source_reference')}
    try:
        for name in ('prepare','reference','couple','bundle','math','geometry'):
            relative,digest=FIXED[name];loaded[name]=module(ROOT/relative,'_proton_v2_original_'+name,digest)
            alias={'prepare':'prepare','reference':'source_reference','couple':'couple'}.get(name)
            if alias:sys.modules[alias]=loaded[name]
    finally:
        for name,prior in saved.items():
            if prior is None:sys.modules.pop(name,None)
            else:sys.modules[name]=prior
    stable();return loaded


ORIGINAL=load_originals()
P,C,B,R,M,G=(ORIGINAL[name] for name in ('prepare','couple','bundle','reference','math','geometry'))


def original_build_payload():
    """Read the previously compiled C++/environment, never run its task script."""
    P.complete_operation(ORIGINAL_BUILD,tuple(ORIGINAL_FILES))
    result={name:pinned(ORIGINAL_BUILD/'collected'/name,digest) for name,digest in ORIGINAL_FILES.items()}
    require(P.transport_source()==result['transport_bcat.cc'],'Generated C++ differs from the actual prior compiled source')
    return result


def write_package(output,files,kind,implementations=()):
    output=Path(output).resolve()
    require(output.is_relative_to(RUNTIME.resolve()) and not output.exists(),'New candidate directory required inside proton runtime')
    require(all(isinstance(name,str) and not Path(name).is_absolute() and '..' not in Path(name).parts
                and isinstance(raw,bytes) for name,raw in files.items()),'Invalid candidate file map')
    require(not {'input-manifest.json','input-hashes.sha256'}&set(files),'Reserved candidate manifest filename')
    manifest=dict(schema='continuous-proton-inputs-v2',kind=kind,version_id='v2-proton-bcat',
        files={name:sha(raw) for name,raw in sorted(files.items())},original_dependencies=stable(),
        implementations={Path(path).name:ref(path) for path in implementations},
        solver_dispatched=False,compiled=False,native_qualified=False,data_design_registered=False,
        meaning='Prepared immutable inputs only; original operation owns any future real execution')
    files=dict(files,**{'input-manifest.json':encoded(manifest)})
    files['input-hashes.sha256']=''.join(sha(raw)+'  '+name+'\n' for name,raw in sorted(files.items()) if name!='task.sh').encode()
    output.mkdir(parents=True)
    for name,raw in files.items():
        path=output/name;path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream:stream.write(raw)
    return output
