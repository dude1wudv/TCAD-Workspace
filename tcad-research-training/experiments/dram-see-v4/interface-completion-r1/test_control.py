"""Focused dispatch/resource counterexamples; never creates a remote job."""
import importlib.util
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
def module(name):
    p=HERE/(name+'.py');s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
m=module('control');resources=module('resources')

class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.cp=self.root/'campaign.json';self.cp.write_text('{"frozen":true}')
        self.state=self.root/'state';self.state.mkdir()
        self.patches=[patch.object(m,'ROOT',self.root),patch.object(m,'CAMPAIGN',self.cp),patch.object(m,'STATE',self.state)]
        for p in self.patches:p.start()
        self.old=[self.record('old'+str(i),historical=True) for i in range(5)]
        self.c=dict(maximum_global_attempts=26,maximum_new_attempts=21,reserve_attempts=4,
                    historical_records=[dict(path=str(p.relative_to(self.root)),sha256=m.sha(p)) for p in self.old],
                    roles=[dict(role_id='a4-b1-main'),dict(role_id='a5-b1-main')])
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def record(self,name,historical=False,**changes):
        p=self.root/(name+'.json')
        d=dict(label=name,state='RUNNER_EXITED',runner_exit_code=0,ssh_exit_code=0,runner_manifest_state='COLLECTED',
               role_id=name,repair_ticket=None)
        if not historical:d.update(campaign_sha256=m.sha(self.cp),budget_category='primary')
        if not historical and changes.get('runner_exit_code',0)!=0:
            run_id=changes.get('run_id','failed-'+name)
            remote_exit=changes.get('ssh_exit_code',changes['runner_exit_code'])
            run=self.root/'local_runtime/runs'/run_id;run.mkdir(parents=True,exist_ok=True)
            archive=run/'results.tar';payload=str(remote_exit).encode('ascii')
            with tarfile.open(archive,'w') as tar:
                info=tarfile.TarInfo('exit-code.txt');info.size=len(payload);tar.addfile(info,io.BytesIO(payload))
            archive_sha=hashlib.sha256(archive.read_bytes()).hexdigest()
            (run/'manifest.json').write_text(json.dumps(dict(state='FAILED_COLLECTED',ssh_exit_code=remote_exit,
                results_sha256=archive_sha)))
            d.update(run_id=run_id,result_archive_sha256=archive_sha,runner_manifest_state='FAILED_COLLECTED',ssh_exit_code=remote_exit)
        d.update(changes);p.write_text(json.dumps(d));return p
    def test_historical_five_retained_and_primary_allowed(self):
        self.assertEqual(m.validate_history(self.old,self.c,'a4-b1-main','primary'),[])
    def test_primary_duplicate_is_not_automatic_retry(self):
        p=self.record('first',role_id='a4-b1-main',runner_exit_code=1)
        with self.assertRaisesRegex(ValueError,'already attempted'):m.validate_history(self.old+[p],self.c,'a4-b1-main','primary')
    def test_cumulative_26_counts_failures(self):
        p=[self.record('new'+str(i),runner_exit_code=1) for i in range(21)]
        with self.assertRaisesRegex(ValueError,'Cumulative26'):m.validate_history(self.old+p,self.c,'a4-b1-main','primary')
    def test_unknown_exit_and_collection_block(self):
        for i,changes in enumerate([dict(state='RUNNING',runner_exit_code=None),dict(ssh_exit_code=None),dict(runner_manifest_state='FAILED_OR_DISCONNECTED')]):
            values={'runner_exit_code':1};values.update(changes)
            p=self.record('unknown'+str(i),**values)
            with self.assertRaisesRegex(ValueError,'unknown'):m.validate_history(self.old+[p],self.c,'a4-b1-main','primary')

    def test_verified_known_failure_counts_and_allows_independent_role(self):
        p=self.record('known-failure',role_id='a4-b1-main',runner_exit_code=3,ssh_exit_code=3)
        self.assertEqual(m.validate_history(self.old+[p],self.c,'a5-b1-main','primary'),[json.loads(p.read_text())])

    def test_ssh_255_is_not_a_known_remote_failure(self):
        p=self.record('ssh-255',role_id='a4-b1-main',runner_exit_code=1,ssh_exit_code=255)
        with self.assertRaisesRegex(ValueError,'remote/collection state unknown'):
            m.validate_history(self.old+[p],self.c,'a5-b1-main','primary')

    def test_missing_remote_exit_is_not_a_known_failure(self):
        p=self.record('missing-remote-exit',role_id='a4-b1-main',runner_exit_code=3,ssh_exit_code=None)
        with self.assertRaisesRegex(ValueError,'remote/collection state unknown'):
            m.validate_history(self.old+[p],self.c,'a5-b1-main','primary')

    def test_tampered_failure_archive_is_not_counted_as_reconciled(self):
        p=self.record('archive-tamper',role_id='a4-b1-main',runner_exit_code=4,ssh_exit_code=4)
        run=self.root/'local_runtime/runs'/'failed-archive-tamper'
        (run/'results.tar').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError,'archive hash differs'):
            m.validate_history(self.old+[p],self.c,'a5-b1-main','primary')
    def test_history_mutation_blocked(self):
        self.old[0].write_text('{}')
        with self.assertRaisesRegex(ValueError,'Historical'):m.validate_history(self.old,self.c,'a4-b1-main','primary')
    def test_unregistered_new_revision_blocked(self):
        p=self.record('foreign',campaign_sha256='bad')
        with self.assertRaisesRegex(ValueError,'Unregistered'):m.validate_history(self.old+[p],self.c,'a4-b1-main','primary')
    def test_reuse_role_cannot_consume_primary(self):
        with self.assertRaisesRegex(ValueError,'not a primary'):m.validate_history(self.old,self.c,'a0-b1-main','primary')
    def ticket(self,**change):
        failed=self.record('failedproof',passed=False)
        checks=self.record('offlinechecks',passed=True)
        d=dict(role_id='a4-b1-main',root_cause='known',repair_description='bounded repair',automatic_retry=False,
               max_additional_attempts=1,same_root_cause_consecutive_failures=1,
               failed_evidence=[dict(path=failed.name,sha256=m.sha(failed))],
               offline_checks=[dict(path=checks.name,sha256=m.sha(checks))])
        d.update(change);return dict(record=d,sha256='unique-ticket',path='ticket.json')
    def test_reserved_attempt_needs_known_failure_and_checks(self):
        with self.assertRaisesRegex(ValueError,'ticket required'):m.validate_history(self.old,self.c,'a4-b1-main','reserve')
        self.assertEqual(m.validate_history(self.old,self.c,'a4-b1-main','reserve',self.ticket()),[])
    def test_reserve_four_cap_and_two_same_cause_stop(self):
        p=[self.record('r'+str(i),budget_category='reserve') for i in range(4)]
        with self.assertRaisesRegex(ValueError,'Four corrective'):m.validate_history(self.old+p,self.c,'a4-b1-main','reserve',self.ticket())
        with self.assertRaisesRegex(ValueError,'Two consecutive'):m.validate_history(self.old,self.c,'a4-b1-main','reserve',self.ticket(same_root_cause_consecutive_failures=2))
    def test_missing_or_changed_dependency(self):
        with self.assertRaisesRegex(ValueError,'missing'):m.check_gate('a4-b1-main')
        g=self.state/'gates';g.mkdir();ev=self.record('evidence',passed=True)
        d=dict(schema='dram-see-v4-completion-role-gate-r1',role_id='a4-b1-main',passed=True,campaign_sha256=m.sha(self.cp),
               evidence=[dict(path=ev.name,sha256=m.sha(ev),requires_pass=True)])
        (g/'a4-b1-main.json').write_text(json.dumps(d));self.assertEqual(m.check_gate('a4-b1-main')['role_id'],'a4-b1-main')
        ev.write_text('{"passed":false}')
        with self.assertRaisesRegex(ValueError,'digest changed'):m.check_gate('a4-b1-main')

class ResourceTests(unittest.TestCase):
    def test_floor_budget_and_active_process_stop(self):
        G=resources.GiB;c=dict(default_resource_forecast=dict(remote_peak_multiplier=3,local_peak_multiplier=4),local_reserve_GiB=80,remote_minimum_free_after_peak_GiB=8)
        self.assertTrue(resources.assess(200*G,0,12*G,G,c,[])['passed'])
        self.assertFalse(resources.assess(200*G,0,10*G,G,c,[])['passed'])
        self.assertFalse(resources.assess(200*G,78*G,50*G,G,c,[])['passed'])
        self.assertFalse(resources.assess(200*G,0,50*G,G,c,['ACTIVE native'])['passed'])

if __name__=='__main__':unittest.main()
