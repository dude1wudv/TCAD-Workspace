"""Maintenance intake is metadata-only, idempotent and scoped to immutable runs."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from maintenance_inventory import inventory
from maintenance_journal import intake


class IntakeTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        self.runs = Path(t.name).resolve() / 'runs'; self.f = self.runs / 'a'; self.f.mkdir(parents=True)
        self.m = dict(run_id='a', state='COLLECTED', remote_exit_code=0, collection_verified=True, parallel_slot_released=True)
        self.save(); (self.f / 'results.tar').write_bytes(b'abc')
        self.view = dict(id='t', backend='tcad', run_id='a', occupied=False, collected=True, success=True, slot=1)
        self.obs = dict(utc='2026-01-01T00:00:00Z', runs=[self.view]); self.intents = {'t':dict(backend='tcad', run_id='a')}
        self.db = sqlite3.connect(':memory:'); self.addCleanup(self.db.close)

    def save(self):
        (self.f/'manifest.json').write_text(json.dumps(self.m), encoding='utf8')

    def scan(self):
        return inventory(self.obs, self.intents, self.runs)

    def test_marker_presence_never_permits_deletion(self):
        for marker, stage in [(None, 'find_or_extract_readout'), ('retention-ready.json','verify_extraction_handoff'),
                              ('retention.json','inspect_retained_result'), ('gdrive-offload.json','inspect_backup_receipt')]:
            if marker: (self.f/marker).write_bytes(b'not a receipt')
            r = self.scan(); self.assertEqual(r['counts'],{stage:1}); self.assertEqual(r['cleanup_authorizations'],0)
            self.assertEqual(r['selected_local_archive_bytes'],{stage:3})
        self.assertEqual((self.f/'results.tar').read_bytes(), b'abc')

    def test_conflict_and_nonrelease(self):
        self.m['remote_exit_code'] = False; self.save(); self.assertEqual(self.scan()['counts'], {'manifest_review':1})
        self.view['occupied'] = True; self.assertEqual(self.scan()['counts'], {'await_release':1})
        self.view['run_id'] = '../a'; r=self.scan(); self.assertEqual(r['counts'], {'identity_review':1}); self.assertEqual(intake(self.db,r),0)

    def test_replay_late_and_changed_stage(self):
        first=self.scan(); self.assertEqual(intake(self.db,first),1); self.assertEqual(intake(self.db,first),0)
        (self.f/'retention-ready.json').touch(); self.obs['utc']='2026-01-01T00:01:00Z'; self.assertEqual(intake(self.db,self.scan()),1)
        self.assertEqual(intake(self.db,first),0); self.obs['runs']=[]; self.assertEqual(intake(self.db,self.scan()),0)
        self.assertEqual(list(self.db.execute('SELECT stage, generation FROM runs')), [('verify_extraction_handoff',2)])

    def test_slot_reuse_and_run_collision(self):
        self.view['occupied']=True; self.assertEqual(intake(self.db,self.scan()),0)
        self.obs['runs'].append(dict(self.view,id='other',run_id='b')); self.intents['other']=dict(backend='tcad',run_id='b')
        self.assertEqual(intake(self.db,self.scan()),0); self.assertEqual(self.db.execute('SELECT COUNT(*) FROM runs').fetchone(), (2,))
        self.obs['runs'][1]['run_id']='a'; self.intents['other']['run_id']='a'
        with self.assertRaisesRegex(ValueError,'duplicate observed run'): self.scan()

    def test_bad_manifest_does_not_abort_batch(self):
        (self.f/'manifest.json').write_bytes(b'invalid'); self.assertEqual(self.scan()['counts'], {'metadata_review':1})
