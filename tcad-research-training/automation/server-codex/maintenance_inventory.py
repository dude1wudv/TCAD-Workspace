"""Read-only maintenance triage. Marker presence selects a check, never authorizes cleanup."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import stat


def read_doc(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024**2:
        raise ValueError('unsafe metadata')
    doc = json.loads(path.read_bytes())
    if not isinstance(doc, dict):
        raise ValueError('expected object')
    return doc


def regular_size(path):
    try:
        st = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(st.st_mode):
        raise ValueError('unexpected archive or marker type')
    return st.st_size


def triage(view, intent, runs):
    rid = view.get('run_id')
    if (not isinstance(rid, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,220}', rid)
            or rid != intent.get('run_id') or not isinstance(intent.get('backend'), str)
            or view.get('backend') != intent['backend']):
        return 'identity_review', 0
    if view.get('occupied') is not False:
        return 'await_release', 0
    if not view.get('collected') is True or not view.get('success') is True:
        return 'diagnose_or_reconcile', 0
    if intent['backend'] != 'tcad':
        return 'unsupported_format', 0
    folder = runs / rid
    if folder.resolve() != folder:
        raise ValueError('redirected run directory')
    manifest = read_doc(folder / 'manifest.json')
    if (manifest.get('run_id') != rid or manifest.get('state') != 'COLLECTED'
            or type(manifest.get('remote_exit_code')) is not int or manifest['remote_exit_code'] != 0
            or manifest.get('collection_verified') is not True or manifest.get('parallel_slot_released') is not True):
        return 'manifest_review', 0
    sizes = {k: regular_size(folder / k) for k in ('results.tar', 'results.raw.tar.gz')}
    total = sum(x for x in sizes.values() if x is not None)
    for marker, stage in [('gdrive-offload.json', 'inspect_backup_receipt'),
                          ('retention.json', 'inspect_retained_result'),
                          ('retention-ready.json', 'verify_extraction_handoff')]:
        if regular_size(folder / marker) is not None:
            return stage, total
    return 'find_or_extract_readout', total


def inventory(observation, intents, runs):
    # Provision the original runs root explicitly; never follow a path suggested by a log/model.
    runs = Path(runs).absolute()
    if runs.resolve() != runs or not runs.is_dir() or runs.name != 'runs':
        raise ValueError('expected original runs root')
    counts, sizes = Counter(), Counter()
    rows = []
    seen, seen_runs = set(), set()
    for view in observation['runs']:
        task = view['id']
        if task in seen:
            raise ValueError('duplicate observed task')
        seen.add(task)
        try:
            stage, size = triage(view, intents.get(task, {}), runs)
        except (ValueError, OSError, RuntimeError):
            stage, size = 'metadata_review', 0
        rid = view.get('run_id')
        if stage != 'identity_review':
            if rid in seen_runs:
                raise ValueError('duplicate observed run identity')
            seen_runs.add(rid)
        counts[stage] += 1
        sizes[stage] += size
        rows.append(dict(task=task, run_id=rid, stage=stage))
    return dict(schema='tcad-maintenance-inventory-v1', observed_at=observation['utc'],
                generated_at=datetime.now(timezone.utc).isoformat(), counts=dict(counts),
                selected_local_archive_bytes=dict(sizes), cleanup_authorizations=0, rows=rows)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    for field in ('observation', 'ledger', 'runs'):
        ap.add_argument('--' + field, type=Path, required=True)
    ap.add_argument('--summary', action='store_true', help='omit private identities')
    args = ap.parse_args()
    result = inventory(read_doc(args.observation), read_doc(args.ledger)['intents'], args.runs)
    if args.summary:
        del result['rows']
    print(json.dumps(result, ensure_ascii=False))
