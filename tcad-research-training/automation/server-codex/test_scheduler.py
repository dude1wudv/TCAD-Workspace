"""Deterministic asynchronous engine tests; no SSH or solver is executed."""
import concurrent.futures
import copy
import json
from pathlib import Path
import subprocess
import threading
import time
import unittest
from unittest import mock
import test_runtime as fixtures
import scheduler_engine as module


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.h=fixtures.RuntimeTests(methodName='runTest')
        self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.h.policy['pool_switching']={'min_profile_dwell_seconds':0,'max_profile_ready_wait_seconds':0}
        self.engines=[]

    def sample(self, records, profiles):
        runs={};leases=[]
        for key,record in records.items():
            intent=next(item for engine in self.engines for task_id,item in engine.intents.items() if task_id==key)
            state=record['state'];alive=state=='RUNNING'
            identity=record.get('process_identity') or dict(run_id=intent['run_id'],pid=100+intent['slot'],
                start_ticks=1000,boot_id='fixture',cwd=record['remote_directory'],script_sha256=record.get('script_sha256'))
            runs[key]=dict(status='RUNNING' if alive else 'FINISHED',alive=alive,
                           remote_exit_code=record.get('remote_exit_code'),identity=identity,rss_kib=1048576 if alive else 0)
            if record.get('parallel_slot_released') is not True:
                leases.append(dict(state='ACTIVE',policy=record['parallel_policy'],identity=identity,script_sha256=record.get('script_sha256')))
        return dict(ok=True,observed_at=time.time(),boot_id='fixture',runs=runs,leases=leases,
                    locks=[],locks_verified=True,processes_with_solver_names=[],telemetry=dict(
                    mem_available_gib=28-sum(item['rss_kib'] for item in runs.values())/1048576,
                    mem_total_gib=28,host_disk_free_gib=100,remote_disk_free_gib=100,
                    backing_disk_free_gib=100,license_daemons_alive=True,license_feature_available=None))

    def engine(self, read_only=False):
        engine=module.SchedulerEngine(self.h.policy,self.h.ready,read_only=read_only)
        self.engines.append(engine);self.addCleanup(engine.close)
        engine.probe.probe=self.sample
        return engine

    def wait_channel(self,engine):
        for command,future in list(engine.channel.operations.values()):future.result(timeout=3)

    def fill(self,engine,count):
        for _ in range(count*3+3):
            engine.tick();self.wait_channel(engine)
            if len(self.h.runs())==count:
                return engine.tick(allow_submit=False)
        self.fail('Original channel did not dispatch expected jobs')

    def test_read_only_disables_inherited_storage_and_offload_workers(self):
        engine=self.engine(read_only=True)
        engine.policy.update(result_retention_enabled=True,result_gdrive_offload_enabled=True)
        self.assertFalse(engine.can_submit())
        views={'fixture':dict(backend='tcad',collected=True,success=True)}
        with mock.patch.object(module.runtime.subprocess,'Popen',side_effect=AssertionError('Read-only started storage worker')):
            engine._maintain_results(views);engine._offload_results(views)

    def test_blocked_runner_does_not_block_tick_or_queue_edits(self):
        for i in range(10):self.h.task('job-'+str(i))
        engine=self.engine();started=threading.Event();release=threading.Event()
        original=self.h.fake_runner
        def blocked(argv,**kwargs):
            if 'run' in argv:
                started.set()
                if not release.wait(3):raise AssertionError('Fixture release was never signalled')
            return original(argv,**kwargs)
        self.h.mock_runner.side_effect=blocked;self.addCleanup(release.set)
        begin=time.monotonic();observation=engine.tick()
        self.assertLess(time.monotonic()-begin,.5)
        self.assertTrue(started.wait(1));self.assertEqual(len(engine.channel.operations),1)
        self.h.task('arrived-during-runner-wait')
        second=engine.tick(allow_submit=False)
        self.assertEqual(len(engine.channel.operations),1)
        self.assertEqual(second['scheduler']['last_decision']['primary_reason'],'original_runner_busy')
        durable=fixtures.runtime.read_json(self.h.base/'state/runtime.json')
        self.assertEqual(len(durable['intents']),1)
        release.set();self.wait_channel(engine)

    def test_full_pool_collects_and_refills_original_slot(self):
        for i in range(10):self.h.task('task-'+str(i))
        engine=self.engine();full=self.fill(engine,9)
        self.assertEqual(full['running_count'],9)
        self.assertEqual(len(self.h.runs()),9)
        first=next(iter(engine.intents));old=self.h.finish(first)
        engine.tick(allow_submit=False);self.wait_channel(engine)
        observation=engine.tick();self.wait_channel(engine)
        self.assertEqual(len(self.h.runs()),10)
        new=next(item for key,item in engine.intents.items() if key not in {run['id'] for run in full['runs']})
        self.assertEqual(new['slot'],old['slot'])
        self.assertTrue(any(event['type']=='collected' for event in observation['events']))
        self.assertFalse(any(command=='status' for _,command,_ in self.h.calls))

    def test_new_archive_verification_never_blocks_live_scheduler_tick(self):
        self.h.task('one');engine=self.engine();self.fill(engine,1);self.h.finish('one')
        entered=threading.Event();release=threading.Event();self.addCleanup(release.set)
        verify=engine._verify_collection;original_digest=module.runtime.file_digest
        def blocked(intent,payload):
            entered.set();release.wait(3);return verify(intent,payload)
        def no_archive_on_main(path):
            if Path(path).name=='results.tar':raise AssertionError('Main loop tried to hash a new archive')
            return original_digest(path)
        with mock.patch.object(engine,'_verify_collection',side_effect=blocked):
            engine.tick(allow_submit=False);self.assertTrue(entered.wait(1))
            with mock.patch.object(module.runtime,'file_digest',side_effect=no_archive_on_main):
                started=time.monotonic();observation=engine.tick(allow_submit=False)
            self.assertLess(time.monotonic()-started,.5)
            self.assertEqual(observation['scheduler']['tasks']['one']['task_state'],'COLLECTING')
            release.set();self.wait_channel(engine)
        self.assertTrue(engine.tick(allow_submit=False)['runs'][0]['collected'])

    def test_new_diagnostics_stay_under_scheduler(self):
        self.h.task('one');engine=self.engine();observation=self.fill(engine,1)
        self.assertIn('one',observation['scheduler']['tasks'])
        self.assertEqual(observation['scheduler']['tasks']['one']['task_state'],'RUNNING')
        for run in observation['runs']:
            self.assertFalse({'task_state','remote_observation_fresh','remote_observed_at'} & run.keys())
        self.assertNotIn('read_only',observation)
        self.assertNotIn('fresh_max_age_seconds',observation)

    def test_observing_legacy_intent_does_not_add_identity_keys(self):
        self.h.task('one');engine=self.engine();self.fill(engine,1)
        engine.intents['one'].pop('scheduler',None);engine._save()
        original=json.loads(json.dumps(engine.intents['one']))
        reader=self.engine(read_only=True);reader.tick(allow_submit=False)
        self.assertEqual(reader.intents['one'],original)
        self.assertNotIn('scheduler',reader.intents['one'])

    def test_read_only_preserves_file_set_bytes_and_mtimes(self):
        self.h.task('one');engine=self.engine();self.fill(engine,1)
        def files():
            return {str(path.relative_to(self.h.base)):(path.read_bytes(),path.stat().st_mtime_ns)
                    for path in self.h.base.rglob('*') if path.is_file()}
        before=files();calls=len(self.h.calls)
        reader=self.engine(read_only=True);result=reader.tick(allow_submit=False)
        self.assertEqual(files(),before)
        self.assertEqual(len(self.h.calls),calls)
        self.assertTrue(result['scheduler']['read_only'])

    def test_unknown_remote_blocks_submission_without_ghost_intent(self):
        self.h.task('one');engine=self.engine()
        engine.probe.probe=lambda *_:dict(ok=False,runs={},error={'kind':'endpoint_unavailable'})
        observation=engine.tick()
        self.assertIs(observation['discovery_uncertain'],True)
        self.assertEqual(self.h.calls,[]);self.assertEqual(engine.intents,{})

    def test_unregistered_gate_lock_blocks_submission(self):
        self.h.task('one');engine=self.engine();original=engine.probe.probe
        def locked(*args):
            value=original(*args);value['locks']=[dict(path='/fixture/pool/.solver.lock',mode='WRITE',pid=777)];return value
        engine.probe.probe=locked;observation=engine.tick()
        self.assertIs(observation['discovery_uncertain'],True)
        self.assertEqual(self.h.calls,[])

    def test_quarantine_preserves_slot_and_allows_healthy_backfill(self):
        self.h.task('bad');self.h.task('healthy');engine=self.engine();self.fill(engine,2)
        self.h.task('backfill');self.h.finish('bad');original=self.h.fake_runner
        bad_run=engine.intents['bad']['run_id']
        def corrupt(argv,**kwargs):
            if 'collect' in argv and bad_run in argv:
                return subprocess.CompletedProcess(argv,1,'','Successful run missing required output')
            return original(argv,**kwargs)
        self.h.mock_runner.side_effect=corrupt
        engine.tick(allow_submit=False);self.wait_channel(engine)
        observation=engine.tick();self.wait_channel(engine)
        self.assertEqual(observation['scheduler']['tasks']['bad']['task_state'],'QUARANTINED')
        self.assertTrue(next(run for run in observation['runs'] if run['id']=='bad')['occupied'])
        self.assertIn('backfill',engine.intents)
        self.assertNotEqual(engine.intents['bad']['slot'],engine.intents['backfill']['slot'])
        record=fixtures.runtime.read_json(self.h.record_path('tcad',bad_run))
        self.assertIs(record['parallel_slot_released'],False)

    def test_persisted_cancel_attempt_recovers_same_original_id(self):
        self.h.task('one');engine=self.engine();self.fill(engine,1)
        original=self.h.fake_runner;cancels=[]
        def cancelled(argv,**kwargs):
            if 'cancel' in argv:
                cancels.append(list(argv));return subprocess.CompletedProcess(argv,0,json.dumps({'execution_outcome':'UNCONFIRMED'}),'')
            return original(argv,**kwargs)
        self.h.mock_runner.side_effect=cancelled
        engine.cancel_task('one','operator authorized stop')
        engine.intents['one']['scheduler']['cancel_invoked']=True
        engine.tick(allow_submit=False);self.wait_channel(engine);engine.tick(allow_submit=False)
        self.assertEqual(len(cancels),1)
        self.assertIn(engine.intents['one']['run_id'],cancels[0])
        self.assertTrue(engine.intents['one']['scheduler']['cancel_manual_attention'])
        engine.tick(allow_submit=False);self.assertEqual(len(cancels),1)
        with self.assertRaises(ValueError):engine.cancel_task('one','different reason')


class ResourceAndChannelTests(unittest.TestCase):
    def sample(self):
        return dict(ok=True,observed_at=time.time(),telemetry=dict(mem_available_gib=12,
                    host_disk_free_gib=30,remote_disk_free_gib=20,backing_disk_free_gib=30,
                    license_daemons_alive=True,license_feature_available=None))

    def test_memory_reserves_only_unmeasured_part_of_live_estimates(self):
        admission=module.admission_module.ResourceAdmissionController({})
        sample=self.sample();sample['telemetry']['mem_available_gib']=7
        verdict=admission.evaluate({'backend':'tcad'},4,sample,[dict(backend='tcad',width=1,rss_kib=1048576)])
        self.assertFalse(verdict['allowed']);self.assertEqual(verdict['blocking_dimension'],'memory')
        sample['telemetry']['mem_available_gib']=8
        self.assertTrue(admission.evaluate({'backend':'tcad'},4,sample,[dict(backend='tcad',width=1,rss_kib=1048576)])['allowed'])

    def test_memory_license_backing_and_freshness_are_independent(self):
        admission=module.admission_module.ResourceAdmissionController({'resources':{'require_backing_disk':True}})
        for field,value,dimension in [('mem_available_gib',4,'memory'),('license_daemons_alive',False,'license'),('backing_disk_free_gib',.1,'backing_disk')]:
            sample=self.sample();sample['telemetry'][field]=value
            self.assertEqual(admission.evaluate({'backend':'tcad'},1,sample)['blocking_dimension'],dimension)
        sample=self.sample();sample['observed_at']-=31
        self.assertEqual(admission.evaluate({'backend':'tcad'},1,sample)['blocking_dimension'],'telemetry')
        sample=self.sample();sample['telemetry']['license_daemons_alive']=False
        self.assertTrue(admission.evaluate({'backend':'geant4'},1,sample)['allowed'])

    def test_channel_accepts_only_one_total_operation_and_closes(self):
        pool=module.collector.AsyncCollectorPool();release=threading.Event();self.addCleanup(release.set)
        self.addCleanup(pool.close)
        with mock.patch.object(module.collector,'invoke',side_effect=lambda *args:(release.wait(2),{'ok':True})[1]):
            self.assertTrue(pool.submit('a','collect',[],'.',{},1))
            self.assertFalse(pool.submit('b','run',[],'.',{},1))
            release.set();pool.operations['a'][1].result(timeout=2)
            self.assertEqual(pool.completed('a'),('collect',{'ok':True}))
            self.assertTrue(pool.submit('b','run',[],'.',{},1))
            pool.operations['b'][1].result(timeout=2)
        pool.close();self.assertFalse(pool.submit('c','collect',[],'.',{},1))


if __name__=='__main__':unittest.main()


class ReadOnlyProbeTests(unittest.TestCase):
    def probe(self,observed_at,backing_path=None):
        import tempfile
        import scheduler_probe
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        root=Path(self.folder.name)
        probe=scheduler_probe.BatchRemoteProbe(dict(state_dir=str(root),workspace=str(Path(__file__).resolve().parents[2]),
                                                      resources={"backing_disk_path": backing_path}),read_only=True)
        record=dict(run_id='fixture',remote_directory='/fixture',script_sha256='0'*64,
                    process_identity=dict(pid=123,start_ticks=10,boot_id='fixture',cwd='/fixture',run_id='fixture',script_sha256='0'*64,private_metadata='x'*200000),
                    private_manifest='y'*200000)
        reply=dict(ok=True,observed_at=observed_at,runs={},telemetry={})
        with mock.patch.object(scheduler_probe.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(reply),'')) as invoke:
            result=probe.probe({'fixture':record},{'tcad':{'cfg':dict(ssh_target='fixture-only',runtime_entry='/usr/bin/env',remote_root='/fixture')}})
        self.assertEqual(list(root.iterdir()),[])
        return result,invoke.call_args.args[0]

    def test_identity_projection_is_bounded_and_readonly_disables_mux_writes(self):
        result,argv=self.probe(time.time())
        self.assertTrue(result['ok']);self.assertIn('ControlMaster=no',argv);self.assertIn('UpdateHostKeys=no',argv)
        self.assertLess(len(argv[-1]),50000);self.assertNotIn('private_manifest',argv[-1]);self.assertNotIn('private_metadata',argv[-1])

    def test_stale_sample_does_not_refresh_remote_facts(self):
        result,argv=self.probe(time.time()-600)
        self.assertFalse(result['ok']);self.assertIsNone(result['observed_at']);self.assertEqual(result['runs'],{})

    def test_missing_backing_mount_does_not_report_the_server_filesystem_as_vm_space(self):
        import scheduler_probe
        with mock.patch.object(scheduler_probe.os.path, "ismount", return_value=False):
            result, _ = self.probe(time.time(), "/fixture/not-mounted")
        self.assertTrue(result["ok"])
        self.assertIsNone(result["telemetry"]["backing_disk_free_gib"])


class DurableArchiveVerificationTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        import hashlib
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name);(self.root/'state').mkdir()
        self.archive=self.root/'results.tar';self.archive.write_bytes(b'original-archive')
        self.record=dict(state='COLLECTED_PENDING_AUDIT',collection_verified=True,results_sha256=hashlib.sha256(self.archive.read_bytes()).hexdigest())
        self.intent=dict(backend='tcad',run_id='fixture')

    def runtime(self,read_only=False):
        engine=module.runtime.Runtime.__new__(module.runtime.Runtime)
        engine.state_dir=self.root/'state';engine._archive_cache={};engine.read_only=read_only
        return engine

    def receipt(self,engine):return engine._receipt(self.intent,self.record,self.root/'manifest.json')

    def test_restart_reuses_exact_verified_stat_without_rehash_or_readonly_write(self):
        self.assertTrue(self.receipt(self.runtime()))
        memo=self.root/'state/verified-archives.json';before=(memo.read_bytes(),memo.stat().st_mtime_ns)
        with mock.patch.object(module.runtime,'file_digest',side_effect=AssertionError('Verified archive was rehashed')):
            self.assertTrue(self.receipt(self.runtime(read_only=True)))
        self.assertEqual(before,(memo.read_bytes(),memo.stat().st_mtime_ns))

    def test_changed_archive_never_inherits_previous_verification(self):
        self.assertTrue(self.receipt(self.runtime()))
        self.archive.write_bytes(b'tampered-archive')
        self.assertFalse(self.receipt(self.runtime(read_only=True)))
