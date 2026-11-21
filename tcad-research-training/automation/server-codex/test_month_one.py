import json
from types import SimpleNamespace
from unittest import mock
import sys
import month_one_wave as wave
from pathlib import Path
import shutil
import tempfile
import unittest

import month_one
import r06_gate as gate


class MonthOneIndexTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        folder = Path('plans') / gate.PLAN
        source = Path(__file__).resolve().parents[2] / folder
        target = self.root / folder
        target.mkdir(parents=True)
        shutil.copyfile(source / 'month-one-cases-r06.json', target / 'month-one-cases-r06.json')
        contract = folder / 'r06-gate/contract.json'
        (self.root / contract).parent.mkdir()
        shutil.copyfile(source / 'r06-gate/contract.json', self.root / contract)
        self.admissions = self.root / folder / 'r06-gate/production-admissions'
        self.admissions.mkdir()
        self.policy = dict(workspace=self.root, state_dir=self.root, queue_file=self.root / 'queue.json',
                           scientific_gate=dict(contract={'path':contract.as_posix(), 'sha256':gate.sha(self.root / contract)},
                                                deferred_task_ids=['old1','old2','old3']))
        reasons = ['scientific_gate_pending'] * 4 + ['pool_profile_waiting_for_idle'] * 3 + ['dependencies_pending']
        ids = ['old1','old2','old3','repair','a','b','transport','p0']
        self.put('observation.json', dict(utc='2026-11-21T01:18:00Z',pending_tasks=[dict(id=i,reason=r) for i,r in zip(ids,reasons)]))
        self.put('runtime.json', {'intents': {}})
        self.put('queue.json', {'tasks': [dict(id=i, backend='geant4' if i=='transport' else 'tcad',project='frozen') for i in ids]})
        self.cid = 'r06-s-d0-nominal-p08-b1'
        self.admission = dict(task_id='repair',case_id=self.cid,project='frozen',manifest_sha256=gate.sha(target / 'month-one-cases-r06.json'))
        self.put(self.admissions / 'repair.json', self.admission)

    def put(self, name, data):
        (self.root / name).write_text(json.dumps(data), encoding='utf8')

    def test_full_replay_read_only(self):
        before = {p:p.stat().st_mtime_ns for p in self.root.rglob('*') if p.is_file()}
        result = month_one.project(self.policy, gate)
        self.assertEqual(result['plan_cases'], 396)
        self.assertEqual(sum(result['case_states'].values()), 396)
        self.assertEqual(result['pending_reasons_at_observation'], dict(legacy_deferred=3, scientific_gate_pending=1, pool_profile_waiting_for_idle=3, dependencies_pending=1))
        self.assertEqual(result['case_states']['proposed'], 1)
        self.assertEqual(before, {p:p.stat().st_mtime_ns for p in self.root.rglob('*') if p.is_file()})

    def test_case_and_mismatched_proposal(self):
        row = month_one.project(self.policy, gate, self.cid)['cases'][0]
        self.assertEqual(row['attempts'][0]['observed_reason'], 'scientific_gate_pending')
        self.put(self.admissions / 'repair.json', dict(self.admission,project='other'))
        self.assertEqual(month_one.project(self.policy, gate, self.cid)['cases'][0]['state'], 'not_bound')
        with self.assertRaisesRegex(ValueError, 'Unknown frozen case'):
            month_one.project(self.policy, gate, '../../outside')

    def test_frozen_intent_precedes_pending_and_unbound_observation(self):
        self.put('runtime.json', {'intents': {'repair':dict(run_id='original',scientific_admission=dict(case_id=self.cid))}})
        self.put('observation.json',dict(utc='2000-01-01T00:00:00Z',runs=[dict(id='repair',run_id='other',status='running')]))
        result = month_one.project(self.policy, gate, self.cid)
        self.assertFalse(result['observation_fresh'])
        self.assertEqual(result['cases'][0]['state'], 'claimed')
        self.assertIsNone(result['cases'][0]['attempts'][0]['observed_status'])

    def staged(self):
        def ref(path):
            return dict(path=path.relative_to(self.root).as_posix(), sha256=gate.sha(path))
        task = dict(id='r06-real-candidate', backend='tcad', project='frozen')
        self.put('staged.json', dict(schema='tcad-work-items-v1', tasks=[task]))
        adm = self.admissions / (task['id'] + '.json')
        self.put(adm, dict(self.admission, task_id=task['id'], profile_id='D0-nominal', backend='tcad',
                           block='S', scope='development_production', schema='tcad-r06-production-admission-v1',
                           owner=gate.OWNER, plan_id=gate.PLAN, revision='r0.6', created_at='frozen'))
        entry = dict(proposal=ref(self.root/'staged.json'), admission_sha256=gate.sha(adm))
        self.put('wave.json', dict(schema='tcad-r06-development-wave-v1', entries=[{'proposal':{}},entry]))
        self.put('queue.json', dict(schema='tcad-work-items-v1', tasks=[]))
        self.policy.update(planner_mode='disabled',month_one_wave=ref(self.root/'wave.json'))
        return SimpleNamespace(intents={},can_submit=lambda:True), adm

    def test_wave_is_idempotent_and_one_bad_entry_does_not_block_sibling(self):
        runtime, adm = self.staged()
        result = wave.publish(self.policy,runtime,gate,self.put)
        self.assertEqual(result['published'], ['r06-real-candidate'])
        self.assertIn('entry-0',result['blocked'])
        again = wave.publish(self.policy,runtime,gate,mock.Mock(side_effect=AssertionError('rewrote queue')))
        self.assertEqual(again['existing'], result['published'])
        task = gate.read(self.policy['queue_file'])['tasks'][0]
        adm.write_bytes(adm.read_bytes()+b' ')
        contract = gate.read_reference(self.root,self.policy['scientific_gate']['contract'])
        with self.assertRaisesRegex(ValueError,'changed since wave'):
            gate.matching_admission(self.root,contract,task,'production')

    def test_prepare_pins_inputs_but_does_not_publish(self):
        self.staged()
        prepared = wave.prepare(self.policy,gate,['staged.json'])
        self.assertEqual(prepared['entries'], gate.read(self.root/'wave.json')['entries'][1:])
        self.assertEqual(gate.read(self.policy['queue_file'])['tasks'], [])
        with self.assertRaisesRegex(ValueError,'duplicate'):
            wave.prepare(self.policy,gate,['staged.json','staged.json'])

    def test_paused_wave_does_not_write(self):
        runtime, _ = self.staged()
        runtime.can_submit = lambda:False
        with self.assertRaisesRegex(ValueError,'paused'):
            wave.publish(self.policy,runtime,gate,mock.Mock(side_effect=AssertionError('paused write')))
        self.assertFalse(gate.read(self.policy['queue_file'])['tasks'])

    def test_exact_interpreter_replay_and_failed_reproduction(self):
        source = self.root/'verifier.py'
        source.write_text('def validate_selection(f,s):\n    assert f["draw"] == s["draw"], "draw mismatch"\n')
        version = sys.version.split()[0]
        s = dict(design={'python_version':version},draw='original')
        with mock.patch.object(gate, 'sys', SimpleNamespace(version='0.0.0')):
            with self.assertRaisesRegex(ValueError,'not configured'):
                gate.replay_selection(source,gate.sha(source),{},s,{})
            opts = {version:sys.executable}
            gate.replay_selection(source,gate.sha(source),{'draw':'original'},s,opts)
            with self.assertRaisesRegex(ValueError,'draw mismatch'):
                gate.replay_selection(source,gate.sha(source),{'draw':'replacement'},s,opts)
            with self.assertRaisesRegex(ValueError,'verifier changed'):
                gate.replay_selection(source,'0'*64,{'draw':'original'},s,opts)

    def test_manifest_tamper_is_not_projected(self):
        path = self.root / 'plans' / gate.PLAN / 'month-one-cases-r06.json'
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'missing or changed'):
            month_one.project(self.policy, gate)
