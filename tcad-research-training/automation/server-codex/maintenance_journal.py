"""Private, replay-safe intake. No solver, storage or model execution authority."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3

from maintenance_inventory import inventory, read_doc


def instant(value):
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.utcoffset() is None:
        raise ValueError('naive observation time')
    return stamp.astimezone(timezone.utc).isoformat(timespec='microseconds')


def intake(db, report):
    """Persist the latest *observed* stage per run; enqueue stage transitions once.

    A missing run is not a completion. Identity anomalies have no eligible run
    key and are reported separately by inventory. Events are hints to recheck
    original evidence, not authorization for external actions.
    """
    observed = instant(report['observed_at'])
    with db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, task TEXT NOT NULL UNIQUE, '
                   'stage TEXT NOT NULL, observed TEXT NOT NULL, generation INTEGER NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS events (run_id TEXT NOT NULL, generation INTEGER NOT NULL, '
                   'stage TEXT NOT NULL, observed TEXT NOT NULL, PRIMARY KEY(run_id, generation))')
        added = 0
        for row in report['rows']:
            rid, task, stage = row['run_id'], row['task'], row['stage']
            if stage == 'identity_review':
                continue
            prev = db.execute('SELECT task, stage, observed, generation FROM runs WHERE run_id=?', (rid,)).fetchone()
            if prev and prev[0] != task:
                raise ValueError('run identity rebound to another task')
            if prev and observed < prev[2]:
                continue
            if prev and observed == prev[2] and stage != prev[1]:
                # Files may advance after an observation; wait for a newer tick.
                continue
            if prev and prev[1] == stage:
                db.execute('UPDATE runs SET observed=? WHERE run_id=? AND observed<?', (observed, rid, observed))
                continue
            generation = prev[3] + 1 if prev else 1
            db.execute('INSERT INTO runs VALUES(?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET '
                       'stage=excluded.stage, observed=excluded.observed, generation=excluded.generation',
                       (rid, task, stage, observed, generation))
            if stage != 'await_release':
                db.execute('INSERT INTO events VALUES(?,?,?,?)', (rid, generation, stage, observed))
                added += 1
    return added


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for field in ('observation', 'ledger', 'runs', 'private-state'):
        ap.add_argument('--' + field, type=Path, required=True)
    args = ap.parse_args()
    folder = args.private_state.absolute()
    # Require a pre-provisioned private directory outside the run tree.
    if (folder != folder.resolve() or not folder.is_dir() or folder.is_relative_to(args.runs.resolve())
            or (os.name == 'posix' and (folder.stat().st_uid != os.getuid() or folder.stat().st_mode & 0o077))):
        ap.error('expected an owner-only private state directory outside the run tree')
    path = folder / 'maintenance.sqlite3'
    if path.is_symlink() or (path.exists() and not path.is_file()):
        ap.error('unsafe journal path')
    os.umask(0o077)
    report = inventory(read_doc(args.observation), read_doc(args.ledger)['intents'], args.runs)
    db = sqlite3.connect(path, timeout=5)
    try:
        added = intake(db, report)
    finally:
        db.close()
    print(json.dumps(dict(observed_at=report['observed_at'], counts=report['counts'],
                          new_stage_events=added, cleanup_authorizations=0)))


if __name__ == '__main__':
    main()
