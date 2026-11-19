"""Bounded R50-main natural-language mapping; stdout only, never dispatch.

This adapts the original frozen Chinese template without importing its CLI,
common, controller, runner, transport or GUI modules. No runtime/results read.
"""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
SCHEMA = 'dram-see-v3-r50-main'
REVISION = 'r50-main-r1'
DESIGN_SHA = '6d52749bb8b9716b13b5ff1aa562a3ee331e3d7a062f32287c23710a5d1cf740'
PLAN_SHA = 'c2f08d68394b669b0ab7edb6727523743cd00a93647e132756421d40a8d9db67'
PARSER_SHA = '583d047b33279f56c6abcdb411da50791b584e330d3302917328b754590c47b9'
ACTIVE_MANIFEST_SHA = '21456da4b28881ae21ad586c683a30aed9395e3c2be85e6c22a8f771349410d2'
SOURCE_NAMES = (
    'experiments/dram-see-v3/design.py',
    'experiments/dram-see-v3/r50-main/design.json',
    'experiments/dram-see-v3/r50-main/plan.md',
    'experiments/dram-see-v3/r50-main/controller.py',
    'experiments/dram-see-v3/r50-main/finish.py',
    'experiments/dram-see-v3/run.py',
    'experiments/dram-see-v3/r50-main/demo.py',
    'experiments/dram-see-v3/r50-main/demo-implementation.md',
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rel(path):
    return Path(path).resolve().relative_to(ROOT).as_posix()


def canonical_sha(value):
    """UTF-8 JSON, sorted keys, compact separators, no NaN; array order retained."""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf8')).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def pure_functions(path, names, scope):
    """Load only named function ASTs as exact bytes from verified source."""
    nodes = [n for n in ast.parse(Path(path).read_bytes()).body if isinstance(n, ast.FunctionDef) and n.name in names]
    require(len(nodes) == len(names) and {n.name for n in nodes} == set(names), 'Pure adapter function inventory changed')
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), scope)
    return scope


def source_check():
    active_path = HERE / 'source-manifest.json'
    require(sha(active_path) == ACTIVE_MANIFEST_SHA, 'Active first-segment source manifest changed')
    active = json.loads(active_path.read_bytes())
    require(active.get('schema') == SCHEMA + '-source-manifest' and active.get('physical_revision') == REVISION
            and len(active['files_sha256']) == 29, 'Expected exactly29 active dependency files')
    protected = {**active['files_sha256'], rel(active_path): sha(active_path)}
    manifest_path = HERE / 'demo-source-manifest.json'
    manifest = json.loads(manifest_path.read_bytes())
    require(manifest.get('schema') == SCHEMA + '-demo-sources' and manifest.get('physical_revision') == REVISION,
            'Wrong demo source manifest')
    require(manifest.get('protected_active_sources_sha256') == protected, 'Active30 protection inventory differs')
    require(set(manifest.get('files_sha256', {})) == set(SOURCE_NAMES), 'Demo dependency inventory differs')
    require(all(name not in protected or protected[name] == digest for name,digest in manifest['files_sha256'].items()),
            'Demo manifest attempts to override protected active source bytes')
    for name, expected in {**protected, **manifest['files_sha256']}.items():
        require(sha(ROOT / name) == expected, 'Frozen demo/active source changed: ' + name)
    for path, expected in ((HERE/'design.json', DESIGN_SHA), (HERE/'plan.md', PLAN_SHA), (BASE/'design.py', PARSER_SHA)):
        require(sha(path) == expected, 'Frozen design/plan/parser version changed')
    return {'files_sha256': manifest['files_sha256'], 'protected_active_sources_sha256': protected,
            'manifest_sha256': sha(manifest_path), 'manifest': rel(manifest_path)}


def contracts():
    evidence = source_check()
    design = json.loads((HERE / 'design.json').read_bytes())
    require(design.get('schema') == SCHEMA and design.get('physical_revision') == REVISION
            and design['independent_event_count'] == 64 and design['tcad_paired_response_count'] == 128
            and design['physical_change']['precharge_resistance_on_ohm'] == {'old':100,'new':50}
            and design['physical_change']['precharge_resistance_off_ohm'] == 1e20,
            'Frozen R50 identity or scope changed')
    tree = ast.parse((BASE / 'design.py').read_bytes())
    constants = [node.value for node in tree.body if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == 'CANONICAL_REQUEST' for t in node.targets)]
    require(len(constants) == 1, 'Original canonical request is ambiguous')
    text = ast.literal_eval(constants[0])
    parser = pure_functions(BASE / 'design.py', ('events', 'parse_request'), {'math': math, 're': re})
    tag = pure_functions(BASE / 'run.py', ('safe_tag',), {})['safe_tag']
    scope = {'BASE':BASE, 'C':SimpleNamespace(safe_tag=tag), 'rel':rel, 'design':lambda: design}
    pure_functions(HERE / 'controller.py', ('control_tag','neutral_tag','event_tag','refined_tag','event_path','target_event','cases'), scope)
    r = SimpleNamespace(**{name:scope[name] for name in ('control_tag','neutral_tag','event_tag','event_path')}, design=lambda:design)
    follow = pure_functions(HERE / 'finish.py', ('cases',), {'R':r,'rel':rel})
    first, later = scope['cases'](design), follow['cases']()
    require(parser['parse_request'](text) == design['events'], 'Original template does not map exactly to frozen R50 events')
    return SimpleNamespace(design=design, canonical=text, parse=parser['parse_request'],
                           first=first, later=later, r=r, sources=evidence)


def preview(text=None):
    c = contracts(); text = c.canonical if text is None else text
    require(isinstance(text, str), 'Request must be explicit text')
    events = c.parse(text)  # Original grammar, values, units and errors unchanged.
    require(events == c.design['events'], 'Request differs from frozen64 event list')
    # Only the pilot/train event roles and fixed test cases enter main128.
    # Physical source-isolation and numerical event roles are not main samples.
    main = [row for row in c.first if row['role'] == 'event' and row['stage'] in ('pilot','train')] + c.later
    require(len(main) == 128 and len({row['tag'] for row in main}) == 128, 'Controller main128 recipe inventory differs')
    indexed = {row['tag']:(index+1,row) for index,row in enumerate(main)}
    responses = []
    for event in events:
        for bit in (0,1):
            tag = c.r.event_tag(event,bit); order, case = indexed[tag]
            require(case['event'] == event and case['kwargs']['bit'] == bit and case['kwargs']['length'] == event['gate_length_um'], 'Controller event/bit/length mapping differs')
            require(case['parent_tag'] == c.r.control_tag(event['gate_length_um'],bit)
                    and case['matching_tags'] == [c.r.control_tag(event['gate_length_um'],bit),c.r.neutral_tag(event['gate_length_um'])], 'Matched R50 prerequisite mapping differs')
            responses.append({'response_id':tag,'event_label':event['label'],'stored_bit':bit,'split':event['split'],
                'condition_id':event['condition_id'],'replicate':event['replicate'],'seed':event['seed'],
                'state':'PLANNED_MAPPING_ONLY_NO_RESULT_INSPECTION','stage':case['stage'],'main_dispatch_sequence':order,
                'model_identity':{'schema':SCHEMA,'physical_revision':REVISION,'physical_revision_probe_only':False,
                    'precharge_resistance_on_ohm':50,'precharge_resistance_off_ohm':1e20},
                'main_parameters':{'gate_length_um':event['gate_length_um'],'particle':event['particle'],'energy_MeV':event['energy_MeV'],
                    'angle_deg':event['angle_deg'],'seed':event['seed'],'stored_bit':bit,'oxide_nm':5.,'step_scale':1.,'mesh_scale':1.,'reference_mode':'offline'},
                'source_event_path':rel(c.r.event_path(event)), 'planned_case':case,
                'dispatch_policy':'NO_DISPATCH_INTERFACE; actual frozen model/predictions must precede holdout/extrapolation TCAD submission' if event['split']!='train'
                                  else 'NO_DISPATCH_INTERFACE; actual references/pilot/numerical gates are checked only by the separately accepted controller'})
    require({row['response_id'] for row in responses} == set(indexed), 'References/variants leaked into main slots')
    result={'schema':SCHEMA+'-bounded-request-preview','physical_revision':REVISION,'generated_utc':datetime.now(timezone.utc).isoformat(),
        'request_text':text,'original_canonical_request':c.canonical,'request_parser_sha256':PARSER_SHA,
        'design_sha256':DESIGN_SHA,'plan_sha256':PLAN_SHA,'original_grammar_unchanged':True,
        'mapping_state':'FIXED_DESIGN_MAPPING_VERIFIED_NOT_SOLVER_OR_COURSE_COMPLETION',
        'planned_independent_events':64,'planned_bit_responses':128,'split_event_counts':{split:sum(e['split']==split for e in events) for split in ('train','holdout','extrapolation')},
        'events':events,'responses':responses,'events_canonical_sha256':canonical_sha(events),
        'responses_canonical_sha256':canonical_sha(responses),'source_evidence':c.sources,
        'physical_revision_explanation':'Rpre signal and physical reference100->50ohm is already authorized/frozen in R50 plan; the old bounded request itself does not request or authorize that physical change',
        'excluded_from_main_denominator':{'first_reference_cases':20,'pilot_physical_isolation_cases':2,'preregistered_refinement_cases':6,
            'oxide_new_cases':14,'oxide_new_independent_events':0,'boundary_rule':c.design['numerical']['selection'],
            'old100ohm_or_probe_responses_reused':False},
        'budget_scope':'24h is original shared86400s cumulative solver budget, not a new allowance; no budget or deadline extension',
        'new_submission_deadline_utc':c.design['authorization']['new_submission_deadline_utc'],
        'new_solver_calls':0,'new_g4_calls':0,'new_inputs':0,'queue_mutations':0,'raw_archives_read':False,
        'actual_student_demonstration':'PENDING_REAL_STUDENT_EVIDENCE','teacher_review':'PENDING_REAL_TEACHER_EVIDENCE',
        'scope':'Bounded template mapping only; no source generation, simulation evidence, calibration, autonomous semantics or course pass'}
    require(source_check() == c.sources, 'Source changed during request mapping')
    return result


def rejection_examples(canonical):
    return [
        ('ambiguous','扫描几个尺寸'),
        ('length_outside_design',canonical.replace('0.45','0.50',1)),
        ('budget_changed',canonical.replace('24小时','48小时')),
        ('replicate_count_changed',canonical.replace('4个独立','6个独立')),
        ('angle_changed',canonical.replace('0、30度','0、45度')),
        ('energy_changed',canonical.replace('5 MeV','10 MeV')),
        ('missing_units',canonical.replace('5 MeV','5')),
        ('unknown_physical_edit',canonical+'把预充改为100欧姆。'),
        ('early_holdout_solve',canonical+'立即求解0.25 um留出响应。'),
        ('early_extrapolation_solve','跳过预测冻结，立即运行0.45 um外推响应。'),
    ]


def audit(text=None):
    mapping = preview(text); c = contracts(); rejected=[]
    for kind, request in rejection_examples(c.canonical):
        try:
            c.parse(request)
        except ValueError as exc:
            rejected.append({'kind':kind,'request':request,'error':str(exc),'new_solver_calls':0})
        else:
            raise ValueError('The frozen parser unexpectedly accepted rejection example: '+kind)
    return {'schema':SCHEMA+'-bounded-request-audit','physical_revision':REVISION,
        'generated_utc':datetime.now(timezone.utc).isoformat(),'state':'SOFTWARE_MAPPING_AUDIT_ONLY',
        'request_text':mapping['request_text'],'events_exactly_equal_frozen_design':True,'events':64,'responses':128,
        'events_canonical_sha256':mapping['events_canonical_sha256'],'responses_canonical_sha256':mapping['responses_canonical_sha256'],
        'split_event_counts':mapping['split_event_counts'],'design_sha256':DESIGN_SHA,'plan_sha256':PLAN_SHA,
        'source_evidence':mapping['source_evidence'],'rejections':rejected,'new_solver_calls':0,'new_g4_calls':0,'queue_mutations':0,
        'actual_student_demonstration':'PENDING_REAL_STUDENT_EVIDENCE','course_complete':False}


def locate(event_label, bit, text=None):
    """Return a completed-archive review route, without claiming it exists."""
    require(type(bit) is int and bit in (0,1), 'Need exactly stored bit0 or bit1')
    mapping=preview(text)
    rows=[r for r in mapping['responses'] if r['event_label']==event_label and r['stored_bit']==bit]
    require(len(rows)==1, 'Not a fixed R50 main event label; control/neutral/physical/probe/old tags are not accepted')
    row=rows[0]
    return {'schema':SCHEMA+'-bounded-evidence-route','physical_revision':REVISION,'response':row,
        'actual_result_status':'NOT_INSPECTED; no completion or run ID inferred from a planned slot',
        'ledger_path':'local_runtime/dram-see-v3/ledger.json','exact_ledger_key':row['response_id'],
        'steps':['Find only this exact R50 key in the unique global ledger; keep failed/missing/running as recorded.',
            'Only VERIFIED runner0 with matching R50 schema/revision/bit/geometry/source may supply scientific observations; never read running raw.',
            'For an actually completed row, use its exact run_id and inputs/results/manifest SHA, then the independent R50 audit and delivery review.',
            'Show paired same-event bit, matched R50 control/neutral, thresholds and uncertainty from an accepted snapshot; not from this mapping preview.',
            'For holdout/extrapolation, actual prediction freeze and input timestamps must be independently verified before claiming a valid score.'],
        'review_entry':'experiments/dram-see-v3/r50-main/delivery.py (explicit documented read-only review after source acceptance)',
        'native_scope':'Only the two frozen R50 native targets have their own capture/visual-review route; this lookup creates no image.',
        'new_solver_calls':0,'raw_archives_read':False,'actual_student_demonstration':'PENDING_REAL_STUDENT_EVIDENCE',
        'source_evidence':mapping['source_evidence'],'design_sha256':DESIGN_SHA}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    for name in ('preview','audit','locate'):
        command=sub.add_parser(name)
        command.add_argument('--text',help='Exact original bounded request; omitted uses canonical template')
        if name=='preview':command.add_argument('--compact',action='store_true',help='Print counts and mapping hashes without128 rows')
        if name=='locate':
            command.add_argument('--event-label',required=True)
            command.add_argument('--bit',required=True,type=int,choices=(0,1))
    args=parser.parse_args()
    try:
        result=preview(args.text) if args.action=='preview' else audit(args.text) if args.action=='audit' else locate(args.event_label,args.bit,args.text)
        if args.action=='preview' and args.compact:
            result={k:v for k,v in result.items() if k not in ('events','responses')}
    except (ValueError,KeyError,OSError) as exc:
        print(json.dumps({'state':'REJECTED_NO_DISPATCH','error':str(exc),'new_solver_calls':0,'new_inputs':0,'queue_mutations':0},ensure_ascii=False),file=sys.stderr)
        return 2
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    return 0


if __name__=='__main__':
    sys.exit(main())
