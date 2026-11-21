"""Publish at most one bounded, hash-pinned development wave under the controller lock.

Producers stage proposals only. No solver, resource decision, scientific override or ledger.
"""
import re
from pathlib import Path

ANCHORS = {'D0-nominal', 'D1-short-channel', 'D2-narrow-fin', 'D3-low-acceptor'}


def prepare(policy, gate, proposals):
    """Print a deterministic wave for explicit staged files; do not mutate anything."""
    work = Path(policy['workspace'])
    contract = gate.read_reference(work, policy['scientific_gate']['contract'])
    gate.need(1 <= len(proposals) <= 13, 'one wave accepts 1..13 proposal files')
    entries, seen = [], set()
    for name in proposals:
        path = gate.path_at(work, name)
        ref = {'path': name, 'sha256': gate.sha(path)}
        blob = gate.read_reference(work, ref)
        gate.need(blob.get('schema') == 'tcad-work-items-v1' and len(blob['tasks']) == 1, 'one task per staged file')
        task = blob['tasks'][0]
        key = task['id']
        gate.need(isinstance(key, str) and re.fullmatch(r'r06-[a-z0-9-]{1,115}', key) and key not in seen, 'invalid or duplicate wave identity')
        seen.add(key)
        adm = gate.matching_admission(work, contract, task, 'production')
        entries.append({'proposal': ref, 'admission_sha256': adm['_verified_binding']['sha256']})
    return {'schema': 'tcad-r06-development-wave-v1', 'entries': entries}


def publish(policy, runtime, gate, write):
    """Caller owns controller.lock and has reconciled. Repeating a wave is a no-op."""
    work = Path(policy['workspace'])
    queue_path = Path(policy['queue_file'])
    report = {'published': [], 'existing': [], 'blocked': {}}
    need = gate.need
    need(policy.get('planner_mode') == 'disabled' and 'scientific_gate' in policy,
         'wave publication requires sole queue ownership and scientific gate')
    wave = gate.read_reference(work, policy['month_one_wave'])
    entries = wave.get('entries')
    need(wave.get('schema') == 'tcad-r06-development-wave-v1' and isinstance(entries, list)
         and 1 <= len(entries) <= 13, 'expected one wave of 1..13 real proposals')
    original = gate.sha(queue_path)
    queue = gate.read(queue_path)
    need(queue.get('schema') == 'tcad-work-items-v1' and isinstance(queue.get('tasks'), list), 'invalid original queue')
    known = {t['id']: t for t in queue['tasks']}
    need(len(known) == len(queue['tasks']), 'ambiguous original task ID')
    contract = gate.read_reference(work, policy['scientific_gate']['contract'])
    seen = set()
    for idx, entry in enumerate(entries):
        key = 'entry-' + str(idx)
        try:
            task = gate.read_reference(work, entry['proposal'])
            need(task.get('schema') == 'tcad-work-items-v1' and len(task['tasks']) == 1, 'need one staged proposal')
            task = dict(task['tasks'][0])
            key = task['id']
            need(set(task) <= {'id','backend','project','depends_on','requires','priority','repair_of','repair_reason'}, 'unrecognized proposal field or adoption request')
            need(isinstance(key, str) and re.fullmatch(r'r06-[a-z0-9-]{1,115}', key), 'invalid task identity')
            need(key not in seen, 'duplicate wave identity')
            seen.add(key)
            expected = entry['admission_sha256']
            need(isinstance(expected,str) and re.fullmatch('[0-9a-f]{64}', expected), 'invalid admission digest')
            task['wave_admission_sha256'] = expected
            if key in known or key in runtime.intents:
                need(known.get(key) == task, 'original identity already claimed; not replaced')
                report['existing'].append(key)
                continue
            admission = gate.matching_admission(work, contract, task, 'production')
            need(admission.get('profile_id') in ANCHORS and (
                (task['backend'] == 'tcad' and admission.get('block') in ('S','R','T') and admission.get('scope') == 'development_production') or
                (task['backend'] == 'geant4' and admission.get('scope') == 'transport_pool')
            ), 'outside first development wave')
            # Publication is NOT admission. Leave heavy hashes, exact replay, dependency,
            # width and resource checks to Runtime; don't repeat them on the heartbeat.
            need(admission.get('manifest_sha256') == contract['manifest']['sha256'], 'wrong frozen manifest')
            need(not admission.get('training_freeze'), 'sealed transport outside development wave')
            queue['tasks'].append(task)
            known[key] = task
            report['published'].append(key)
        except (KeyError, ValueError, OSError, TypeError, IndexError, AttributeError) as exc:
            report['blocked'][str(key)] = str(exc)[:200]
    if report['published']:
        need(gate.sha(queue_path) == original and runtime.can_submit(), 'queue changed or publication paused')
        write(queue_path, queue)
    return report
