"""Service-user maintenance intake; no solver, model, or archive mutation."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from maintenance_inventory import inventory, read_doc
from maintenance_journal import intake


def tick(observation, ledger, runs, state):
    state = Path(state).absolute()
    if (state.resolve()!=state or not state.is_dir() or state.is_relative_to(Path(runs).resolve()) or
            (os.name=='posix' and (state.stat().st_uid!=os.getuid() or state.stat().st_mode & 0o077))):
        raise ValueError('private maintenance directory required')
    report=inventory(read_doc(observation),read_doc(ledger)['intents'],runs)
    dbpath=state/'maintenance.sqlite3'
    if dbpath.is_symlink() or (dbpath.exists() and not dbpath.is_file()): raise ValueError('unsafe database')
    db=sqlite3.connect(dbpath,timeout=3)
    try:
        added=intake(db,report)
    finally:
        db.close()
    summary={k:report[k] for k in ('counts','observed_at','selected_local_archive_bytes')}
    summary['schema']='tcad-maintenance-summary-v1'
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf8',dir=state,delete=False) as f:
        json.dump(summary,f,allow_nan=False); f.flush(); os.fsync(f.fileno())
    os.replace(f.name,state/'summary.json')
    return added

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    for arg in ('observation','ledger','runs','state'): ap.add_argument('--'+arg,type=Path,required=True)
    os.umask(0o077); a=ap.parse_args(); print('new stage events:',tick(a.observation,a.ledger,a.runs,a.state))
