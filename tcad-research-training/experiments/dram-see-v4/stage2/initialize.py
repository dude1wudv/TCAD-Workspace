"""Freeze accepted stage-2 limits and protect historical artifacts; no solver."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
V4 = HERE.parent

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def write(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('x', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write('\n')

def main():
    old = json.loads((V4 / 'planning-review.json').read_text(encoding='utf-8'))
    anchors = []
    for item in old['protected_anchors']:
        current = sha(ROOT / item['path'])
        if current != item['before_sha256']:
            raise ValueError('Historical anchor changed: ' + item['path'])
        anchors.append({'path': item['path'], 'sha256': current})
    protected = []
    for name in ('source-probe', 'transport-probe'):
        for p in sorted((V4 / name).rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts:
                protected.append({'path': p.relative_to(ROOT).as_posix(), 'sha256': sha(p)})
    snapshot = HERE / 'previous-documents'
    snapshot.mkdir(exist_ok=False)
    for name in ('README.md', 'mentor-response.md', 'work-items.md', 'plan.md'):
        shutil.copyfile(V4 / name, snapshot / name)
    write(HERE / 'protected-before.json', {'created_utc': datetime.now(timezone.utc).isoformat(),
          'anchors': anchors, 'old_probe_files': protected,
          'scope': 'Preexisting v3/report anchors plus all tracked-size old v4 probe files; raw archives remain immutable.'})
    geometry = {'geometry_id': 'v4-si10mm-nuclear-witness-r1',
                'world_half_um': [20000.0]*3,
                'silicon_bounds_um': [[-5000.0,5000.0]]*3,
                'material': 'G4_Si', 'production_cut_um': 10.0,
                'charged_max_step_um': 100.0,
                'source_um': [0.0,-5001.0,0.0], 'direction': [0.0,1.0,0.0],
                'energy_MeV': 100.0, 'angle_deg': 0.0,
                'scope': 'Independent macroscopic nuclear-mechanism diagnostic, not a DRAM device'}
    gh = hashlib.sha256(json.dumps(geometry, sort_keys=True, separators=(',',':')).encode()).hexdigest()
    requests = []
    specifications = [('witness-init-h-r1','init','H',40131401,0,'initialization'),
                      ('witness-init-e-r1','init','E',40131402,0,'initialization'),
                      ('witness-pilot-h-r1','witness','H',40131501,2,'pilot'),
                      ('witness-pilot-e-r1','witness','E',40131502,2,'pilot'),
                      ('witness-fixed-h-s1-r1','witness','H',40131601,64,'fixed'),
                      ('witness-fixed-h-s2-r1','witness','H',40131602,64,'fixed'),
                      ('witness-fixed-h-s3-r1','witness','H',40131603,64,'fixed'),
                      ('witness-fixed-e-s1-r1','witness','E',40131701,16,'fixed')]
    for label, mode, arm, seed, count, stage in specifications:
        requests.append(dict(label=label,mode=mode,arm=arm,seed=seed,event_count=count,
                             stage=stage,geometry_id=geometry['geometry_id'],geometry_sha256=gh,
                             energy_MeV=100.0,angle_deg=0.0))
    contract = dict(schema='dram-see-v4-nuclear-witness-contract-v1', geometry=geometry,
         geometry_sha256=gh, requests=requests, total_primary_events=212,
         implementation_revision='transport-witness-r1',
         physics={'H':'QGSP_BIC + ReplacePhysics(G4EmStandardPhysics_option4) + StepLimiterPhysics',
                  'E':'G4EmStandardPhysics_option4 + StepLimiterPhysics'},
         gate_order=['compile and offline auditor tests','H/E zero-event initialization and process audit',
                     'H/E 2-event format/time pilots','fixed H 3x64 and E 1x16, serial'],
         witness_rule='protonInelastic with actual type/subtype registration, traceable descendants and positive silicon ionizing deposition',
         selection_rule='First qualifying H event in frozen requests order, then numeric event_id; all fixed events retained even after a witness is found',
         events_for_probability=False, tcad_mapping=False, automatic_retry=False,
         expand_after_no_witness=False, solver_threads=1, cpu_affinity_count=1,
         csv_arithmetic_tolerances={'energy_abs_MeV':1e-12,'energy_relative':1e-9,'time_abs_ns':1e-9,
                                    'position_abs_um':1e-9,'direction_norm_abs':1e-10},
         neutron_tracking_cut='Standard QGSP_BIC 10 us; identify actual neutron process type 7 subtype 403; no added user killing',
         energy_scope='Recorded deposited/NIEL/ionizing component sums; not a closed nuclear rest-mass energy balance',
         failure_rule='Preserve failed/unknown attempts; block dependent stages; read-only reconcile unknown jobs before any new attempt')
    write(V4 / 'mechanism-witness' / 'witness-contract.json', contract)
    write(HERE / 'coordination.json', dict(schema='dram-see-v4-stage2-coordination-v1',
          updated_utc=datetime.now(timezone.utc).isoformat(), state='IMPLEMENTING',
          scheduler='root only', active_solver=None,
          completed=['live solver idle + shared lock free','historical anchors verified','new nuclear contract frozen'],
          pending=['nuclear implementation and audit','source ledger','2D generic revision and 19-request contract','90nm evidence'],
          excluded=['formal160 matrix','3D device response','space spectrum','new size batch','training'],
          old_heartbeat='not resumed', git_commit_push=False))
    print(json.dumps({'historical_anchors':len(anchors),'protected_old_probe_files':len(protected),
                     'contract':str(V4/'mechanism-witness/witness-contract.json'),'primaries':212}))

if __name__ == '__main__':
    main()
