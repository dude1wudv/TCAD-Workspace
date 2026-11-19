"""Frozen r2 cleanup-origin adaptation; original r1 release remains unchanged."""
from pathlib import Path
import json
import sys

HERE = Path(__file__).resolve().parent
R1 = HERE.parent / 'original-recovery-r1'
sys.path.insert(0, str(R1))
import recovery_proof as proof

def check_release():
    proof.check_release()
    release = proof.read(HERE / 'release.json')
    proof.require(release.get('passed') is True, 'R2 implementation has not passed validation')
    for name, digest in release['files_sha256'].items():
        proof.require(proof.sha(proof.ROOT / name) == digest, 'R2 source changed: ' + name)
    for item in release['validation_evidence']:
        path = proof.ROOT / item['path']
        proof.require(proof.sha(path) == item['sha256'] and proof.read(path).get('passed') is True,
                      'R2 verification missing, changed or failed')
    return proof.reference(HERE / 'release.json')

def preflight_resume():
    check_release()
    contract = proof.read(HERE / 'resume-contract.json')
    proof.require(contract['adopt_label'] == 'r5-a6-b1-time-r1' and contract['new_solver_calls_for_resume'] == 0,
                  'Unexpected resume scope')
    for name in ('old_owner', 'failure', 'a6_gate', 'a6_outcome'):
        item = contract[name]; path = proof.ROOT / item['path']
        proof.require(proof.sha(path) == item['sha256'], 'Original resume evidence changed: ' + name)
    owner = proof.read(proof.ROOT / contract['old_owner']['path'])
    proof.require(owner['state'] == 'PAUSED_ON_RECORDED_FAILURE_NO_RETRY' and
                  len(owner['stages']) == 1 and owner['stages'][0]['exit_code'] == 1, 'Prior owner did not terminate in the reviewed failure')
    old = proof.module(R1 / 'campaign_runner.py', '_r2_prior_scheduler_identity')
    proof.require(not old.pid_alive(owner['owner_pid']) and not old.pid_alive(owner['stages'][0]['pid']),
                  'Previous continuation still alive; no second scheduler permitted')
    controller = proof.module(R1 / 'dispatch.py', '_r2_resume_gate')
    controller.check_gate('a6-b1-time')
    proof.require(proof.read(proof.ROOT / contract['a6_outcome']['path'])['passed'] is True,
                  'A6 has not passed; no resume')
    return proof.reference(HERE / 'resume-contract.json')
