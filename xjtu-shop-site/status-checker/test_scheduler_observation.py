import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scheduler_observation import collected_state, load_scheduler, project_snapshot


NOW = dt.datetime(2026, 11, 18, 17, 0, tzinfo=dt.timezone.utc)


def snapshot():
    return {
        'schema': 'tcad-scheduler-observation-v1',
        'id': 'BENCH-012345abcdef', 'state': 'running',
        'observed_at': NOW.isoformat(), 'started_at': (NOW - dt.timedelta(minutes=30)).isoformat(),
        'capacity': 1, 'requested_threads': 10, 'cpu_set': list(range(10)),
        'guest': {'cores': 11, 'cpu_percent': 45.6, 'load_1m': 4.5,
                  'memory': {'MemTotal': 28 * 1024**3, 'MemAvailable': 23 * 1024**3},
                  'simulation_time_ns': 10.02, 'goal_time_ns': 35,
                  'parameters': {'temperature_K': 300, 'theta_deg': 0,
                                 'source_window_width_coord': 0.174,
                                 'device_geometry': 'mesh_dimensions_unavailable'}},
    }


class SchedulerObservationTests(unittest.TestCase):
    def test_ten_cores_are_one_task_with_eleventh_core_idle(self):
        result = project_snapshot(snapshot(), NOW)
        self.assertEqual(len(result['slots']), 11)
        self.assertEqual(result['slot_count'], 11)
        self.assertEqual(result['compute_cpu_count'], 10)
        self.assertEqual(result['reserved_cpus'], [10])
        self.assertEqual(result['active_slots'], 10)
        self.assertEqual(len(result['tasks']), 1)
        self.assertEqual({s['cluster'] for s in result['slots'][:10]}, {'BENCH-012345abcdef'})
        self.assertEqual(result['slots'][10]['state'], 'idle')
        self.assertIsNone(result['slots'][10]['task_id'])
        self.assertEqual(result['tasks'][0]['elapsed_seconds'], 1800)
        self.assertEqual(result['tasks'][0]['parameters']['theta_deg'], 0)
        self.assertEqual(result['tasks'][0]['parameters']['source_window_width_coord'], 0.174)

    def test_stale_observation_freezes_elapsed_and_marks_unknown(self):
        result = project_snapshot(snapshot(), NOW + dt.timedelta(minutes=5))
        self.assertTrue(result['observation_stale'])
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(result['tasks'][0]['elapsed_seconds'], 1800)
        self.assertTrue(all(s['state'] == 'unknown' for s in result['slots']))

    def test_memory_uses_vm_memavailable_and_hides_nonfinite_progress(self):
        source = snapshot()
        source['guest']['simulation_time_ns'] = float('nan')
        result = project_snapshot(source, NOW)
        memory = result['virtual_machine']['memory']
        self.assertEqual(memory['available_bytes'], 23 * 1024**3)
        self.assertEqual(memory['used_bytes'], 5 * 1024**3)
        self.assertIsNone(result['tasks'][0]['progress']['simulation_time_ns'])

    def test_public_payload_omits_extra_paths_identifiers_and_raw_logs(self):
        source = snapshot()
        source.update(run_id='private-run', command='private-command', path='/home/private')
        source['guest'].update(pid=123456, log='private-log', command='private-command')
        output = json.dumps(project_snapshot(source, NOW))
        for value in ('private-run', 'private-command', '/home/', 'private-log', '123456'):
            self.assertNotIn(value, output)
        self.assertTrue(project_snapshot(source, NOW)['replay']['available'])

    def test_terminal_requires_original_verified_collection(self):
        guest = {'native_finished': True, 'solver_alive': False}
        self.assertEqual(collected_state({'state': 'COLLECTED'}, guest), 'collecting')
        manifest = {'state': 'COLLECTED', 'collection_verified': True, 'remote_exit_code': 0,
                    'collection_exit_code': 0, 'tool_exit_codes': {'sdevice': 0}}
        self.assertEqual(collected_state(manifest, guest), 'completed')
        manifest['remote_exit_code'] = 143
        self.assertEqual(collected_state(manifest, guest), 'failed')
        manifest['state'] = 'FAILED_COLLECTED'
        self.assertEqual(collected_state(manifest, guest), 'failed')

    def test_finished_at_falls_back_to_mtime_and_grace_can_be_configured(self):
        guest = {'native_finished': True, 'finished_at': 'invalid',
                 'finished_mtime_at': (NOW - dt.timedelta(seconds=901)).isoformat()}
        self.assertEqual(collected_state({}, guest, NOW), 'uncollected')
        guest['collection_alive'] = True
        self.assertEqual(collected_state({}, guest, NOW), 'collecting')
        guest['collection_alive'] = False
        with patch.dict(os.environ, {'TCAD_STATUS_COLLECTION_GRACE_SECONDS': '1200'}):
            self.assertEqual(collected_state({}, guest, NOW), 'collecting')

    def test_invalid_allocation_and_missing_source(self):
        for cpus in (list(range(11)), [0, 0], [11], [True]):
            source = snapshot()
            source['cpu_set'] = cpus
            with self.assertRaises(ValueError):
                project_snapshot(source, NOW)
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(load_scheduler(Path(directory) / 'missing.json'))


if __name__ == '__main__':
    unittest.main()
