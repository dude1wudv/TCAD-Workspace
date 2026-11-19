# Static r2 derivation of experiments/dram-see-v4/original-recovery-r1/continue.py
# Original SHA-256: 67dcaf038aca91bba33107968f3673a53a2264dfe5de4fba8e62942142cabdb8
"""One owner, two sequential frozen campaigns; no heartbeat and no retry."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import json
import msvcrt
import os
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'original-recovery-r1'))
import recovery_proof as proof
import release_guard

HERE = Path(__file__).resolve().parent
OWNER = proof.STATE / 'continuation-r2'
R1 = HERE.parent / 'original-recovery-r1'

def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)

def main():
    release_guard.check_release()
    proof.verify()
    resume = release_guard.preflight_resume()
    OWNER.mkdir(parents=True, exist_ok=True)
    path = OWNER / 'execution.json'
    lock = (proof.STATE / 'continuation/owner.lock').open('a+b')
    if lock.seek(0, 2) == 0: lock.write(b'0'); lock.flush()
    lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    record = None
    try:
        proof.require(not path.exists(), 'Continuation already has a saved attempt; inspect it, never restart automatically')
        record = dict(schema='dram-see-v4-recovered-serial-continuation-r1', owner_pid=os.getpid(),
                      started_utc=datetime.now(timezone.utc).isoformat(), state='STARTING',
                      release=release_guard.check_release(), recovery=proof.reference(proof.CONTRACT), resume=resume,
                      automatic_retry=False, stages=[], original_runner_exit_code=None, original_ssh_exit_code=None)
        save(path, record)
        for name, argv in [('two-dimensional', [HERE / 'campaign_runner.py', '--adopt', 'r5-a6-b1-time-r1']),
                           ('three-dimensional-and-fixed-transport', [R1 / 'pilot_runner.py'])]:
            release_guard.check_release()
            command = [sys.executable, '-B'] + [str(x) for x in argv]
            stage = dict(name=name, argv=command, started_utc=datetime.now(timezone.utc).isoformat(), exit_code=None)
            record['stages'].append(stage)
            with (OWNER / (name + '.stdout.log')).open('xb') as out, (OWNER / (name + '.stderr.log')).open('xb') as err:
                child = subprocess.Popen(command, cwd=proof.ROOT, stdout=out, stderr=err)
                stage['pid'] = child.pid; record.update(state='STAGE_RUNNING', active_stage=name, active_child_pid=child.pid)
                save(path, record)
                stage['exit_code'] = child.wait()
            stage['finished_utc'] = datetime.now(timezone.utc).isoformat()
            record['active_child_pid'] = None
            save(path, record)
            if stage['exit_code'] != 0:
                record.update(state='PAUSED_ON_RECORDED_FAILURE_NO_RETRY', finished_utc=datetime.now(timezone.utc).isoformat())
                save(path, record)
                return stage['exit_code']
            # The 3D child starts only after the 2D child exits, checks all 17
            # gates and acquires the original old-scheduler lock itself.
        record.update(state='APPROVED_CAMPAIGNS_COMPLETE', active_stage=None, finished_utc=datetime.now(timezone.utc).isoformat())
        save(path, record)
        return 0
    except Exception as exc:
        if record is not None:
            record.update(state='REQUIRES_ROOT_REVIEW_NO_RETRY', error=repr(exc),
                          finished_utc=datetime.now(timezone.utc).isoformat())
            save(path, record)
        raise
    finally:
        lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1); lock.close()

if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    raise SystemExit(main())
