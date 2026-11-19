"""Explicit particle input routing for independent source-segment frames.

This is a local input generator, not a solver runner or operation scheduler.
The original bridge owns the closed, fixed-hash runtime loaders. A0 retains
its separately sealed source_segment_frames_operating_2d.py CLI.
"""
import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
ENTRY_SCHEMA = 'dram-see-v4-source-segment-frames-input-entry-r1'
LEGACY_PREPARE_SHA = '11871ba56912d0010fe11528d6d1046c7d874d1a5c4d29d35b01bbb51f682f5f'
ENTRY_FILE = 'prepare_source_segment_frames_case.py'
SCHEMA_2D_ALPHA_SEGMENT_FRAMES = 'dram-see-v4-source-segment-frames-alpha-request-r1'
SCHEMA_2D_ALPHA_SEGMENT_FRAMES_CONTROL = 'dram-see-v4-source-segment-frames-alpha-control-request-r1'
SCHEMA_2D_PROTON_SEGMENT_FRAMES = 'dram-see-v4-source-segment-frames-proton-request-r1'
SCHEMA_2D_PROTON_SEGMENT_FRAMES_REFINEMENT = 'dram-see-v4-source-segment-frames-proton-refinement-request-r1'
SCHEMA_2D_PROTON_SEGMENT_FRAMES_CONTROL = 'dram-see-v4-source-segment-frames-proton-control-request-r1'
_ROUTES = {
    SCHEMA_2D_ALPHA_SEGMENT_FRAMES: (
        'source_segment_frames_alpha_2d.py', 'geometry_source_segment_frames_alpha_module',
        'dram-see-v4-source-segment-frames-alpha-2d-r1'),
    SCHEMA_2D_ALPHA_SEGMENT_FRAMES_CONTROL: (
        'source_segment_frames_alpha_controls_2d.py', 'geometry_source_segment_frames_alpha_control_module',
        'dram-see-v4-source-segment-frames-alpha-controls-2d-r1'),
    SCHEMA_2D_PROTON_SEGMENT_FRAMES: (
        'source_segment_frames_proton_2d.py', 'geometry_source_segment_frames_proton_module',
        'dram-see-v4-source-segment-frames-proton-2d-r1'),
    SCHEMA_2D_PROTON_SEGMENT_FRAMES_REFINEMENT: (
        'source_segment_frames_proton_refinement_2d.py', 'geometry_source_segment_frames_proton_refinement_module',
        'dram-see-v4-source-segment-frames-proton-refinement-2d-r1'),
    SCHEMA_2D_PROTON_SEGMENT_FRAMES_CONTROL: (
        'source_segment_frames_proton_controls_2d.py', 'geometry_source_segment_frames_proton_controls_module',
        'dram-see-v4-source-segment-frames-proton-control-2d-r1'),
}
_PURE = None


def require(ok, message):
    if not ok:
        raise ValueError('Source segment frame input entry: '+message)


def contract_api():
    """Pure explicit schema namespace; does not import an old case validator."""
    return SimpleNamespace(
        SCHEMA_2D_ALPHA_SEGMENT_FRAMES=SCHEMA_2D_ALPHA_SEGMENT_FRAMES,
        SCHEMA_2D_ALPHA_SEGMENT_FRAMES_CONTROL=SCHEMA_2D_ALPHA_SEGMENT_FRAMES_CONTROL,
        SCHEMA_2D_PROTON_SEGMENT_FRAMES=SCHEMA_2D_PROTON_SEGMENT_FRAMES,
        SCHEMA_2D_PROTON_SEGMENT_FRAMES_REFINEMENT=SCHEMA_2D_PROTON_SEGMENT_FRAMES_REFINEMENT,
        SCHEMA_2D_PROTON_SEGMENT_FRAMES_CONTROL=SCHEMA_2D_PROTON_SEGMENT_FRAMES_CONTROL)


def pure_helpers():
    """Reuse only fixed 11871 raw_json/digest functions, in a new namespace.

    Importing that historical module would bind its old role namespace and all
    transitive runtime imports. Its two exact pure function ASTs need only json
    and hashlib; no old prepare/validator is imported, modified or called.
    """
    global _PURE
    path=HERE/'prepare_case.py'
    require(path.is_file() and not path.is_symlink(), 'fixed original pure helper source missing/linked')
    raw=path.read_bytes()
    require(hashlib.sha256(raw).hexdigest()==LEGACY_PREPARE_SHA, 'fixed original pure helper source changed')
    if _PURE is None:
        tree=ast.parse(raw, filename=str(path))
        wanted=['raw_json','digest']
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in wanted]
        require([n.name for n in nodes]==wanted, 'closed original pure helper functions differ')
        namespace={'json':json,'hashlib':hashlib,'__name__':'_fixed_source_frame_prepare_pure_helpers'}
        for node in nodes:
            # This constructor form also works in the guest Python 3.6 grammar.
            try: module=ast.Module(body=[node],type_ignores=[])
            except TypeError: module=ast.Module(body=[node])
            exec(compile(module,str(path),'exec'),namespace)
        _PURE=SimpleNamespace(raw_json=namespace['raw_json'],digest=namespace['digest'])
    return _PURE


def encoded(value):
    return pure_helpers().raw_json(value)


def digest(raw):
    return pure_helpers().digest(raw)


def reference(path):
    path=Path(path)
    require(path.is_file() and not path.is_symlink(), 'implementation missing/linked: '+str(path))
    raw=path.read_bytes()
    return dict(file=path.name,sha256=hashlib.sha256(raw).hexdigest(),size_bytes=len(raw))


def route(schema):
    require(isinstance(schema,str) and schema in _ROUTES,
        'unknown/old particle request schema; A0 uses its sealed operating CLI')
    filename,loader,branch=_ROUTES[schema]
    return dict(request_schema=schema,runtime_file=filename,bridge_loader=loader,branch=branch)


def bridge_api():
    path=HERE/'geometry_bridge.py'
    require(path.is_file() and not path.is_symlink(), 'original local bridge missing/linked')
    spec=importlib.util.spec_from_file_location('_source_segment_frames_original_bridge',str(path))
    module=importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(),str(path),'exec'),module.__dict__)
    return module


def runtime_for(schema):
    selected=route(schema);bridge=bridge_api()
    loader=getattr(bridge,selected['bridge_loader'],None)
    require(callable(loader), 'PENDING_BRIDGE_ROUTE: '+selected['bridge_loader'])
    runtime=loader()
    expected=(HERE/selected['runtime_file']).resolve()
    require(Path(runtime.__file__).resolve()==expected and not expected.is_symlink(), 'closed bridge runtime path differs')
    require(runtime.REQUEST_SCHEMA==schema and runtime.BRANCH==selected['branch'], 'bridge runtime schema/branch differs')
    own=reference(Path(__file__))
    require(getattr(runtime,'ENTRYPOINT_SHA',None)==own['sha256'], 'runtime has not bound this exact input entry')
    return runtime,selected,reference(Path(bridge.__file__))


def preview(request):
    """Schema/role preview only. It does not read matched A0, source or labels."""
    require(isinstance(request,dict), 'request object required')
    runtime,selected,bridge=runtime_for(request.get('schema'))
    validated=runtime.validate_request(request)
    role=runtime.role_id(validated)
    return dict(schema=ENTRY_SCHEMA,status='INPUT_ROUTE_PREVIEW_ONLY',request=validated,role_id=role,
        route=selected,input_entry=reference(Path(__file__)),renderer=reference(Path(runtime.__file__)),
        bridge=bridge,matched_native_inputs_replayed=False,native_calls=0,new_project_created=False,
        native_qualified=False,training_admitted=False)


def verify_prepared_entry(project,runtime,selected,run_id):
    """Check the actual newly frozen input entry; never repair a manifest."""
    project=Path(project).resolve();entry=project/ENTRY_FILE
    require(entry.is_file() and not entry.is_symlink() and entry.read_bytes()==Path(__file__).read_bytes(),
        'new input did not freeze the actual unified entry bytes')
    manifest=json.loads((project/'input-manifest.json').read_text(encoding='utf-8'))
    context=json.loads((project/'execution-context.json').read_text(encoding='utf-8'))
    binding=json.loads((project/'input-generation-binding.json').read_text(encoding='utf-8'))
    hashes=manifest.get('files_sha256',{})
    require(manifest.get('run_id')==context.get('run_id')==run_id
        and context.get('input_manifest_sha256')==digest((project/'input-manifest.json').read_bytes()),
        'new input manifest/context identity differs')
    for name in (ENTRY_FILE,selected['runtime_file'],'input-generation-binding.json'):
        require(hashes.get(name)==digest((project/name).read_bytes()), 'actual generator identity not frozen: '+name)
    require((project/selected['runtime_file']).read_bytes()==Path(runtime.__file__).read_bytes(), 'actual renderer bytes differ')
    require(binding.get('entry_kind')=='unified_prepare'
        and binding.get('entry_file')==ENTRY_FILE and binding.get('entry_sha256')==hashes[ENTRY_FILE]
        and binding.get('renderer_file')==selected['runtime_file']
        and binding.get('renderer_sha256')==hashes[selected['runtime_file']]
        and binding.get('request_schema')==selected['request_schema']
        and binding.get('source_branch')==selected['branch'], 'actual unified generation binding differs')
    return dict(input_manifest_sha256=digest((project/'input-manifest.json').read_bytes()),
        input_generation_binding_sha256=hashes['input-generation-binding.json'],input_entry_sha256=hashes[ENTRY_FILE],
        actual_entry_bytes_frozen=True,manifest_rewritten_by_entry=False)


def prepare(request,run_id,runner=None,output=None):
    """Delegate to one explicit fixed runtime, with the actual entry identity."""
    require(isinstance(request,dict), 'request object required')
    require(isinstance(run_id,str) and re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*',run_id) is not None,
        'explicit new run ID required')
    runtime,selected,bridge=runtime_for(request.get('schema'))
    validated=runtime.validate_request(request)
    result=runtime.prepare(validated,run_id,runner=runner,output=output,input_entry=__file__)
    require(isinstance(result,dict), 'explicit runtime prepare result required')
    result=dict(result)
    if result.get('project') is not None:
        checked=verify_prepared_entry(result['project'],runtime,selected,run_id)
    else:
        checked=dict(actual_entry_bytes_frozen=False,reason='Runtime returned missing-input/pending result; no project claimed')
    result['unified_input_entry']=dict(schema=ENTRY_SCHEMA,route=selected,
        input_entry=reference(Path(__file__)),renderer=reference(Path(runtime.__file__)),bridge=bridge,
        closure=checked,native_calls=0)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',type=Path,required=True)
    parser.add_argument('--run-id')
    parser.add_argument('--runner',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--preview',action='store_true')
    args=parser.parse_args()
    try:
        request=json.loads(args.request.read_text(encoding='utf-8-sig'))
        if args.preview:
            value=preview(request)
        else:
            require(args.run_id is not None, '--run-id required for explicit prepare')
            value=prepare(request,args.run_id,args.runner,args.output)
        print(encoded(value).decode('utf-8'));return 0
    except (OSError,ValueError,KeyError,TypeError,UnicodeError,ArithmeticError) as exc:
        print(json.dumps(dict(schema=ENTRY_SCHEMA,status='REFUSED_OR_PENDING_INPUT_ROUTE',
            error=dict(type=type(exc).__name__,message=str(exc)),native_calls=0,native_qualified=False,
            training_admitted=False),ensure_ascii=False));return 2


if __name__=='__main__':
    raise SystemExit(main())
