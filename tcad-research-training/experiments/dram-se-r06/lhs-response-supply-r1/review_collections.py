"""Review newly collected development S/T cases with the retained native reader."""

import argparse
from pathlib import Path
import re
import runpy
import sys
import tarfile

sys.path.insert(0, '/opt/tcad-autonomy/current')
import r06_gate as gate
import team_readout


def review(policy):
    work = Path(policy['workspace'])
    private = work / 'local_runtime/server-codex'
    prior = private / 'r06-lhs02-threshold-followup-r1/followup.py'
    gate.need(gate.sha(prior) == 'd4ec6fd3690c8c23763a8609c0063fabe74a80ae641f558038982307e01734e0',
              'Original review loader changed')
    reader = runpy.run_path(str(prior))['load_review']()
    output = private / 'r06-case-reconciliation-r1'
    output.mkdir(mode=0o700, exist_ok=True)
    reader['OUT'] = output
    contract = gate.read_reference(work, policy['scientific_gate']['contract'])
    manifest = gate.read_reference(work, contract['manifest'])
    gate.need(contract['manifest']['sha256'] == reader['PLAN_SHA'], 'Review plan changed')
    cases = {case['case_id']: case for case in manifest['cases'] if case['block'] in ('S', 'T')}
    state = Path(policy['state_dir'])
    intents = gate.read(state / 'runtime.json')['intents']
    observation = gate.read(state / 'observation.json')
    generator = reader['reference'](Path(__file__).resolve())
    for task, run, case_id in team_readout.candidates(observation, intents, None):
        acceptance = reader['ACCEPT'] / (case_id + '.json')
        pair_receipt = private / 'team-readout' / run / 'receipt.json'
        cache_receipt = reader['PAIR'].RUNS / run / 'key-cache-receipt.json'
        if case_id not in cases or acceptance.exists() or not (pair_receipt.is_file() and cache_receipt.is_file()):
            continue
        pair_sha = gate.read(pair_receipt)['pair_sha256']
        gate.need(re.fullmatch('[0-9a-f]{64}', pair_sha) is not None, 'Invalid native pair digest')
        hold = output / f'{run}-{pair_sha[:16]}-review-hold.json'
        if hold.is_file():
            continue
        try:
            evidence, record = reader['review'](cases[case_id], task, intents[task], intents,
                                               reader['reference'](reader['MANIFEST']), generator)
            gate.need(record['run_id'] == run and record['case_id'] == case_id, 'Reviewed identity changed')
        except (ValueError, KeyError, ArithmeticError) as error:
            reader['publish'](hold, dict(task=task, case_id=case_id, run_id=run, pair_sha256=pair_sha,
                                         reason=str(error), reviewer=generator))
            print('HOLD', case_id, error, flush=True)
            continue
        except (OSError, EOFError, tarfile.TarError) as error:
            print('RETRY', case_id, error, file=sys.stderr, flush=True)
            continue
        evidence_path = output / f'{run}-review.json'
        reader['publish'](evidence_path, evidence)
        record['evidence'] = [reader['reference'](evidence_path)]
        action = reader['publish'](acceptance, record)
        print(action, case_id, run, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy', required=True, type=Path)
    review(gate.read(parser.parse_args().policy))
