import ast
import datetime as dt
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import scheduler_observation as scheduler
import status_checker as checker
import telemetry_history as history


NOW = dt.datetime(2026, 11, 19, 18, 0, tzinfo=dt.timezone.utc)
GIB = 1024**3
LOG = """Computing BE-step from 3.0923e-08 s to 3.0924e-08 s (Stepsize: 9.0e-13 s)
Iteration   |Rhs|      factor     |step|     error   #inner  #iterative  time
    0      3.99e+05                                                      1.11
    4      1.28e-02   1.00e+00   4.05e-03   9.93e-01    0       190     16.18
Finished, because...
Error smaller than 1 ( 9.9340E-01 ).
Assembly time:        7.04 s
Solve time:      9.12 s
Total time:     16.18 s
Computing BE-step from 3.0924e-08 s to 3.0925e-08 s (Stepsize: 8.0e-13 s)
    30     1.68e-02   1.00e+00   4.25e-02   1.27e+01    0       195    112.11
Finished, because...
Maximum number of iterations reached.
Assembly time:       45.10 s
Solve time:     66.77 s
Total time:    112.11 s
Computing BE-step from 3.0924e-08 s to 3.0924e-08 s (Stepsize: 3.8725e-14 s)
    0      3.99e+05                                                      1.12
"""
PROTOCOL = {
    'transient': {'final_ns': 35, 'integrator': 'BE'},
    'write': {'WL2_edges_ns': [2, 2.1, 10, 10.1], 'WL1_edges_ns': [10.2, 10.3, 18, 18.1]},
    'hold': {'start_ns': 18.1, 'end_ns': 30},
    'read': {'driver_disconnect_ns': 30, 'WL1_edges_ns': [30.1, 30.2, 32, 32.1], 'sample_ns': 31.9},
    'source': {'required_source_rows': 0, 'node_count': 10734}, 'stored_bit': 1,
}


def json_file(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding='utf-8')
    return path


def space(total, used, available):
    return {'total_bytes': total * GIB, 'used_bytes': used * GIB, 'available_bytes': available * GIB}


def guest():
    return {
        'observed_at': NOW.isoformat(), 'cores': 11, 'cpu_percent': 45.6,
        'cpu_usage': {f'cpu{cpu}': cpu * 5 for cpu in range(11)}, 'load': [4, 3, 2],
        'memory': {'MemTotal': 28 * GIB, 'MemAvailable': 23 * GIB, 'SwapTotal': GIB, 'SwapFree': 0},
        'storage': space(87, 30, 55), 'license_seconds': {'lmgrd': 8100, 'snpslmd': 8000},
        'solvers': [], 'runs': {},
    }


def solver(cwd, cpus, engine='sdevice'):
    return {'cwd': cwd, 'engine': engine, 'pid': 123456789, 'affinity': ','.join(map(str, cpus)),
            'started_at': (NOW - dt.timedelta(hours=2)).isoformat(), 'cpu_percent': 99.8,
            'rss_bytes': 2 * GIB, 'hwm_bytes': 3 * GIB, 'threads': 3,
            'lm_license_file': '/srv/private'}


def manifest(root, run, cpus, layout, pool='pool-a', **fields):
    remote = '/home/synthetic/runs/' + run
    path = root / pool / 'runs' / run / 'manifest.json'
    json_file(path, {
        'run_id': run, 'remote_directory': remote, 'state': 'RUNNING', 'started_utc': (NOW - dt.timedelta(hours=2)).isoformat(),
        'parallel_policy': {'requested_threads': len(cpus), 'cpu_set': cpus, 'capacity': len(layout), 'cpu_sets': layout},
        **fields,
    })
    return remote, path


class PoolObservationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.runtime = self.root / 'runtime.json'

    def collect(self, sample):
        def fake_probe(command, **options):
            self.assertEqual(command[0], 'ssh')
            self.assertEqual(command[-1], '/usr/bin/python3 -')
            self.assertTrue(options['check'])
            code = options['input']
            ast.parse(code, feature_version=(3, 6))
            for command in ('lmstat', 'sdevice -v', 'doctor', '/proc/environ'):
                self.assertNotIn(command, code)
            return SimpleNamespace(stdout=json.dumps(sample))

        with patch.object(scheduler, 'probe_code', wraps=scheduler.probe_code) as code:
            source = scheduler.collect_snapshot(fake_probe, self.root, self.runtime)
            code.assert_called_once()
            self.candidates = code.call_args.args[0]
        return source, scheduler.project_snapshot(source, NOW)

    def test_concurrent_affinities_and_slot_fusion_for_multiple_layouts(self):
        for layout, name in (
            ([[i] for i in range(10)], '10×1 单核对照'),
            ([[i] for i in range(6)] + [[6, 7], [8, 9]], '6×1 + 2×2 混排调度'),
            ([[0, 1], [2, 3], [4, 5], [6, 7]], '4×2 双核队列'),
            ([[1, 2, 3, 4], [5, 6, 7, 8]], '2×4'),
            ([list(range(10))], '1×10'),
        ):
            with self.subTest(layout=layout):
                sample = guest()
                for i, cpus in enumerate(layout):
                    remote, _ = manifest(self.root, f'private-bench-d1-b1-{i}', cpus, layout)
                    sample['solvers'].append(solver(remote, cpus))
                source, projected = self.collect(sample)
                self.assertEqual(projected['label'], name)
                self.assertEqual(projected['active_groups'], len(layout))
                self.assertEqual(projected['active_slots'], sum(map(len, layout)))
                reserved = sorted(set(range(11)) - {cpu for cpus in layout for cpu in cpus})
                self.assertEqual(source['reserved_cpus'], reserved)
                self.assertEqual(projected['reserved_cpus'], reserved)
                self.assertEqual(projected['compute_cpu_count'], sum(map(len, layout)))
                self.assertEqual(projected['slots'][10]['state'], 'idle')
                self.assertEqual(projected['slots'][10]['usage_percent'], 50)
                for cpus in layout:
                    self.assertEqual(len({projected['slots'][cpu]['cluster'] for cpu in cpus}), 1)

    def test_partial_batch_preserves_configured_slots_and_root_override(self):
        sample = guest()
        remote, path = manifest(self.root, 'private-bench-d1-b1-rep2', [2], [[i] for i in range(10)])
        record = json.loads(path.read_text())
        record['parallel_policy'].pop('cpu_sets')
        json_file(path, record)
        sample['solvers'].append(solver(remote, [2]))
        with patch.dict(os.environ, {'TCAD_STATUS_POOL_ROOT': str(self.root), 'TCAD_STATUS_RUNTIME': str(self.runtime)}):
            source = scheduler.collect_snapshot(lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps(sample)))
        projected = scheduler.project_snapshot(source, NOW)
        self.assertEqual(projected['layout_widths'], [1] * 10)
        self.assertEqual(projected['active_slots'], 1)
        self.assertEqual(projected['tasks'][0]['label'], 'D1 · 性能对照 · 写 1 (#2)')

    def test_idle_profile_defines_cpu_reservation(self):
        layout = [[i] for i in range(6)] + [[6, 7], [8, 9]]
        json_file(self.root / 'connection-active.json',
                  {'local_state_root': str(self.root / 'pool-a'), 'cpu_sets': layout})
        _, projected = self.collect(guest())
        self.assertEqual((projected['slot_count'], projected['compute_cpu_count']), (11, 10))
        self.assertEqual(projected['reserved_cpus'], [10])

    def test_idle_pool_is_measured_even_with_previous_batch(self):
        remote, _ = manifest(self.root, 'private-collected', [0], [[0]], state='COLLECTED',
                             collection_verified=True, remote_exit_code=0, collection_exit_code=0,
                             tool_exit_codes={'sdevice': 0}, collected_utc=NOW.isoformat())
        self.assertTrue(remote)
        _, projected = self.collect(guest())
        self.assertEqual((projected['state'], projected['label'], projected['active_slots']), ('idle', '空闲池', 0))
        self.assertTrue(all(row['state'] == 'idle' for row in projected['slots']))
        self.assertEqual(projected['active_batch']['collected'], 1)

    def test_cpu_overlap_and_multiple_processes_are_counted_separately(self):
        sample = guest()
        first, _ = manifest(self.root, 'first', [0, 1], [[0, 1]])
        second, _ = manifest(self.root, 'second', [1], [[1]], pool='pool-b')
        sample['solvers'] = [solver(first, [0]), solver(first, [1], 'snmesh'), solver(second, [1], 'geant4')]
        _, projected = self.collect(sample)
        self.assertEqual(projected['active_solvers'], 3)
        self.assertEqual(projected['active_groups'], 2)
        self.assertEqual(projected['active_slots'], 2)
        self.assertEqual(len(projected['slots'][1]['task_ids']), 2)
        self.assertIsNone(projected['slots'][1]['task_id'])
        active = next(task for task in projected['tasks'] if task['cpu_set'] == [0, 1])
        self.assertEqual(active['rss_bytes'], 4 * GIB)
        self.assertEqual(active['processes'][0]['threads'], 3)

    def test_nested_cwd_and_absolute_argument_associate_every_process(self):
        sample = guest()
        remote, _ = manifest(self.root, 'transport-18', [1, 2], [[1, 2]], profile_id='E123', case_id='m1-r05-e123-p0')
        by_cwd = solver(remote + '/scratch', [1], 'geant4')
        by_argument = dict(solver('/tmp', [2], 'svisual'), paths=[remote + '/analysis/trace.txt'])
        similarly_named = solver(remote + '-extra', [3], 'sdevice')
        sample['solvers'] = [by_cwd, by_argument, similarly_named]
        source, projected = self.collect(sample)
        recognized = next(row for row in projected['tasks'] if row['kind'] == 'formal')
        self.assertEqual(recognized['device'], 'E123')
        self.assertEqual(recognized['case_id'], 'm1-r05-e123-p0')
        self.assertEqual(recognized['cpu_set'], [1, 2])
        self.assertEqual({item['engine'] for item in recognized['processes']}, {'geant4', 'svisual'})
        unmatched = next(row for row in projected['tasks'] if row['kind'] == 'unmatched')
        self.assertEqual(unmatched['cpu_set'], [3])
        self.assertNotIn(remote, json.dumps(source))

    def test_holdout_markers_shut_off_detail_reads_and_public_details(self):
        sample = guest()
        hr, _ = manifest(self.root, 'sensitive-identity-a', [0], [[0]], case_id='r06-hr-sealed')
        hp, _ = manifest(self.root, 'sensitive-identity-b', [1], [[1]])
        sealed, _ = manifest(self.root, 'sensitive-identity-c', [2], [[2]], sealed_intent=True)
        unknown = '/srv/unregistered/runs/hp-unknown'
        sample['solvers'] = [solver(directory, [cpu]) for cpu, directory in enumerate((hr, hp, sealed, unknown))]
        for directory in (hr, hp, sealed, unknown):
            sample['runs'][directory] = {'goal_time_ns': 77, 'parameters': {'stored_bit': 1, 'temperature_K': 999}}
        json_file(self.runtime, {'intents': {'private-assignment': {
            'run_id': 'sensitive-identity-b', 'scientific_admission': {'scientific_object': {'block': 'HP'}},
        }}})
        source, projected = self.collect(sample)
        self.assertTrue(all(self.candidates.get(directory) is False for directory in (hr, hp, sealed)))
        self.assertNotIn(unknown, self.candidates)
        self.assertEqual(projected['active_slots'], 4)
        self.assertEqual(projected['recent_runs'], [])
        for row in projected['tasks']:
            self.assertEqual(row['label'], '封存留出任务')
            self.assertEqual(set(row), {'id', 'label', 'kind', 'state', 'cpu_set'})
        encoded = json.dumps(source)
        for marker in ('sensitive-identity', 'private-assignment', '999', '/home/', '/srv/', '123456789'):
            self.assertNotIn(marker, encoded)

    def test_defensive_projection_of_private_snapshot_with_sealed_case(self):
        source = {'schema': scheduler.SCHEMA, 'observed_at': NOW.isoformat(), 'guest': guest(),
                  'tasks': [{'id': 'RUN-012345abcdef', 'case_id': 'r06-hp-secret', 'state': 'running',
                             'kind': 'formal', 'cpu_set': [1], 'started_at': NOW.isoformat()}]}
        source['recent_runs'] = source['tasks']
        projected = scheduler.project_snapshot(source, NOW)
        self.assertEqual(projected['tasks'][0]['kind'], 'sealed')
        self.assertEqual(projected['recent_runs'], [])
        self.assertNotIn('012345abcdef', json.dumps(projected))

    def test_backup_manifest_does_not_hide_canonical_collection(self):
        sample = guest()
        remote, path = manifest(self.root, 'real-bench-d1-b1-02', [2], [[2]], state='COLLECTED',
                                collection_verified=True, collection_exit_code=0, remote_exit_code=0,
                                tool_exit_codes={'sdevice': 0}, collected_utc=NOW.isoformat())
        backup = json.loads(path.read_text())
        backup.update(state='TRANSFER_OR_CONNECTION_FAILED', collection_verified=None)
        json_file(path.parent.with_name('private-backup') / 'manifest.json', backup)
        _, projected = self.collect(sample)
        self.assertIn(remote, self.candidates)
        self.assertEqual(projected['active_batch']['collected'], 1)
        self.assertEqual(projected['recent_runs'][0]['collection_result'], 'verified_success')

    def test_native_exit_collecting_and_archive_final_clock(self):
        sample = guest()
        remote, path = manifest(self.root, 'finished-native', [2], [[2]])
        sample['runs'][remote] = {'native_finished': True, 'finished_at': NOW.isoformat()}
        _, projected = self.collect(sample)
        self.assertEqual(projected['tasks'][0]['health'], 'collecting')
        self.assertEqual(projected['active_slots'], 0)
        current = json.loads(path.read_text())
        current.update(state='COLLECTED', collection_verified=True, collection_exit_code=0, remote_exit_code=0,
                       tool_exit_codes={'sdevice': 0}, collected_utc=NOW.isoformat())
        json_file(path, current)
        data = LOG[:LOG.index('Computing BE-step', 1)].encode()
        member = tarfile.TarInfo('transient_des.log')
        member.size = len(data)
        with tarfile.open(path.parent / 'results.tar', 'w') as archive:
            archive.addfile(member, io.BytesIO(data))
        _, projected = self.collect(guest())
        self.assertAlmostEqual(projected['recent_runs'][0]['final_time_ns'], 30.924)
        self.assertEqual(projected['recent_runs'][0]['collection_result'], 'verified_success')

    def test_overdue_collection_is_visible_in_task_recent_and_batch(self):
        sample = guest()
        remote, _ = manifest(self.root, 'finished-native', [2], [[2]])
        detail = {'native_finished': True, 'finished_at': (NOW - dt.timedelta(minutes=16)).isoformat()}
        sample['runs'][remote] = detail
        _, projected = self.collect(sample)
        self.assertEqual(projected['state'], 'uncollected')
        self.assertEqual(projected['active_batch']['uncollected'], 1)
        for task in (projected['tasks'][0], projected['recent_runs'][0]):
            self.assertEqual((task['state'], task['health'], task['health_reason']),
                             ('uncollected', 'collection_overdue', 'collection_overdue'))
            self.assertTrue(task['health_detail_zh'])
            self.assertTrue(task['health_detail_en'])
        detail['collection_alive'] = True
        _, projected = self.collect(sample)
        self.assertEqual(projected['tasks'][0]['state'], 'collecting')


class LogProjectionTests(unittest.TestCase):
    def test_short_deck_endpoint_overrides_full_protocol(self):
        deck = ('Transient(InitialTime=0 FinalTime=2e-9) { Coupled { Poisson } }\n'
                'Transient(InitialTime=2e-9 FinalTime=30.925e-9) { Coupled { Poisson } }')
        engineering = scheduler.parse_engineering(PROTOCOL, deck, LOG)
        goal = engineering['goal_time_ns']
        self.assertAlmostEqual(goal, 30.925)
        progress = scheduler.normalized_progress(
            {'simulation_time_ns': goal}, goal, engineering['whr'])
        self.assertEqual(progress['whr_phase'], 'read')
        self.assertEqual(progress['whr_segments'][-1], {'id': 'read', 'start_ns': 30, 'end_ns': goal})

    def test_native_attempt_clock_newton_timings_and_whr_phase(self):
        parsed = scheduler.parse_transient_log(LOG)
        self.assertAlmostEqual(parsed['simulation_time_ns'], 30.924)
        self.assertEqual(parsed['stepsize_s'], 3.8725e-14)
        self.assertEqual(parsed['newton_iterations'], 4)
        self.assertEqual(parsed['error'], 0.9934)
        self.assertEqual((parsed['assembly_s'], parsed['solve_s'], parsed['step_wall_s']), (7.04, 9.12, 16.18))
        engineering = scheduler.parse_engineering(PROTOCOL, 'Temperature = 300', LOG)
        progress = scheduler.normalized_progress(parsed, engineering['goal_time_ns'], engineering['whr'])
        self.assertEqual(progress['mode'], 'whr')
        self.assertEqual(progress['whr_phase'], 'read')
        self.assertEqual([segment['id'] for segment in progress['whr_segments']],
                         ['initialization', 'write_sn2', 'write_sn1', 'hold', 'read', 'tail'])
        self.assertEqual(engineering['parameters'], {
            'node_count': 10734, 'integrator': 'BE', 'temperature_K': 300,
            'stored_bit': 1, 'source_variant': 'particle_free_control',
        })

    def test_freshness_overrides_very_small_step_and_stale_snapshot_freezes(self):
        row = {
            'id': 'RUN-012345abcdef', 'kind': 'research', 'state': 'running', 'cpu_set': [0],
            'processes': [{'engine': 'sdevice', 'cpu_percent': 5}],
            'progress': dict(scheduler.parse_transient_log(LOG),
                             log_updated_at=(NOW - dt.timedelta(minutes=16)).isoformat()),
        }
        source = {'schema': scheduler.SCHEMA, 'observed_at': NOW.isoformat(), 'guest': guest(), 'tasks': [row]}
        stalled = scheduler.project_snapshot(source, NOW)['tasks'][0]
        self.assertEqual((stalled['health'], stalled['health_reason']), ('stalled', 'log_silent_low_cpu'))
        row['processes'] = [{'engine': 'sdevice', 'cpu_percent': 70}]
        busy = scheduler.project_snapshot(source, NOW)['tasks'][0]
        self.assertEqual((busy['health'], busy['health_reason']), ('fine_step', 'stepsize_below_1ps'))
        row['progress']['log_updated_at'] = NOW.isoformat()
        self.assertEqual(scheduler.project_snapshot(source, NOW)['tasks'][0]['health'], 'fine_step')
        stale = scheduler.project_snapshot(source, NOW + dt.timedelta(minutes=5))
        self.assertEqual(stale['tasks'][0]['state'], 'unknown')
        self.assertIsNone(stale['active_slots'])
        self.assertIsNone(stale['virtual_machine']['daemon_health']['lmgrd']['alive'])

    def test_phases_without_transient_clock(self):
        for engine, phase in (('sdevice', 'dc_init'), ('sde', 'mesh'), ('snmesh', 'mesh'), ('post', 'post')):
            self.assertEqual(scheduler.parse_transient_log('', engine)['phase'], phase)
        self.assertEqual(scheduler.parse_transient_log('Generating mesh')['phase'], 'mesh')

    def test_integrators_and_generic_simulation_time_ratio(self):
        for integrator in ('BE', 'TRBDF', 'TRBDF2', 'TR', 'BDF2', 'BankRose', 'Euler'):
            with self.subTest(integrator=integrator):
                parsed = scheduler.parse_transient_log(f'Computing {integrator}-step from 1e-9 s to 2e-9 s')
                projected = scheduler.normalized_progress(parsed, 5)
                self.assertEqual((projected['mode'], projected['current'], projected['target'], projected['unit']),
                                 ('ratio', 1, 5, 'ns'))

    def test_process_engine_recognizes_binaries_and_wrappers_without_misattributing_shell(self):
        examples = (
            ('sdevice', ['sdevice'], '/opt/bin/sdevice_exec', 'sdevice'),
            ('snmesh_exec', ['snmesh'], '', 'snmesh'),
            ('truncated', ['/opt/bin/svisual_exec_v2'], '', 'svisual'),
            ('truncated', ['/opt/bin/sprocess_exec'], '', 'sprocess'),
            ('bash', ['bash', '/opt/tools/transport_matrix.sh'], '/bin/bash', 'geant4'),
            ('g4_probe', ['/opt/bin/g4_probe'], '/opt/bin/g4_probe', 'geant4'),
            ('bash', ['bash', '-c', 'sdevice /tmp/native'], '/bin/bash', None),
            ('sshd', ['sshd', '/opt/transport_matrix.sh'], '/usr/sbin/sshd', None),
        )
        for comm, argv, exe, expected in examples:
            with self.subTest(comm=comm, argv=argv):
                self.assertEqual(scheduler.process_engine(comm, argv, exe), expected)

    def test_geant4_log_has_event_ratio_and_rate_without_a_simulation_clock(self):
        parsed = scheduler.parse_geant4_log('Event 25\n60 / 100 events\nCompleted 65 events\nElapsed: 10 s')
        progress = scheduler.normalized_progress(dict(parsed, engine='geant4', source='geant4_log'))
        self.assertEqual((progress['engine'], progress['stage_label'], progress['mode']),
                         ('geant4', 'Particle transport', 'ratio'))
        self.assertEqual((progress['current'], progress['target'], progress['unit'], progress['rate_per_hour']),
                         (65, 100, 'events', 23400))
        self.assertIsNone(progress['simulation_time_ns'])
        self.assertEqual(scheduler.normalized_progress(scheduler.parse_geant4_log('G4WT1 > Event 50'))['mode'], 'pulse')
        requested = scheduler.parse_geant4_log('/run/beamOn 500\nNumber of events: 500\nEvent 60')
        self.assertEqual((requested['current'], requested['target']), (60, 500))
        finished = scheduler.parse_geant4_log('Completed 20 events', finished=True)
        self.assertEqual((finished['current'], finished['target']), (20, 20))

    def test_progress_json_whitelist_size_and_log_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = json_file(root / 'progress.json', {
                'schema': 'tcad-task-progress-v1', 'engine': 'geant4', 'stage': 'transport',
                'mode': 'ratio', 'current': 42, 'target': 60, 'unit': 'events', 'rate_per_hour': 123,
                'stage_label': '/home/private', 'unexpected': 'ssh', 'stepsize_s': float('inf'),
                'simulation_time_ns': True,
            })
            progress = scheduler.normalized_progress(scheduler.read_task_progress(path))
            self.assertEqual((progress['source'], progress['engine'], progress['stage_label']),
                             ('progress_json', 'geant4', 'Particle transport'))
            self.assertEqual((progress['mode'], progress['current'], progress['target'], progress['rate_per_hour']),
                             ('ratio', 42, 60, 123))
            self.assertIsNone(progress['stepsize_s'])
            self.assertIsNone(progress['simulation_time_ns'])
            checker.check_public_payload(progress)
            encoded = path.read_bytes()
            path.write_bytes(encoded.ljust(64 * 1024, b' '))
            self.assertTrue(scheduler.read_task_progress(path))
            path.write_bytes(encoded.ljust(64 * 1024 + 1, b' '))
            self.assertEqual(scheduler.read_task_progress(path), {})
            old_log, new_log, new_out, preferred = (root / name for name in (
                'old.log', 'new.log', 'new.out', 'transient_des.log',
            ))
            for seconds, log in enumerate((old_log, new_log, new_out, preferred)):
                log.write_text(str(log), encoding='utf-8')
                stamp = 1000 + seconds
                os.utime(log, (stamp, stamp))
            self.assertEqual(scheduler.discovery_log(root), preferred)
            preferred.unlink()
            self.assertEqual(scheduler.discovery_log(root), new_log)
            old_log.unlink()
            new_log.unlink()
            self.assertEqual(scheduler.discovery_log(root), new_out)

    def test_bundled_guest_probe_uses_command_paths_and_prefers_progress_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc = root / 'proc'
            process = proc / '100'
            process.mkdir(parents=True)
            task = root / 'task'
            task.mkdir()
            remote = '/home/example/transport-run'
            (proc / 'stat').write_text('cpu 2 1 1 1 0 0 0 0\ncpu0 2 1 1 1 0 0 0 0\nbtime 100', encoding='utf-8')
            (proc / 'meminfo').write_text('MemTotal: 1024 kB\nMemAvailable: 512 kB', encoding='utf-8')
            (process / 'comm').write_text('transport_matri\n', encoding='utf-8')
            (process / 'stat').write_text('100 (transport_matri) S 1 ' + '0 ' * 18, encoding='utf-8')
            (process / 'status').write_text('Cpus_allowed_list: 0\nThreads: 2\nVmRSS: 10 kB', encoding='utf-8')
            (process / 'cmdline').write_bytes(f'transport_matrix_executable\0--macro={remote}/input/work.mac\0'.encode())
            progress_file = json_file(task / 'progress.json', {
                'schema': 'tcad-task-progress-v1', 'engine': 'geant4', 'stage': 'transport',
                'current': 42, 'target': 60, 'unit': 'events',
            })
            (task / 'events.log').write_text('25 / 60 events\nElapsed: 5 s', encoding='utf-8')
            probe = {}
            exec(scheduler.probe_code({remote: True}).rsplit('\n', 1)[0], probe)
            probe['Path'] = {'/proc': proc, remote: task}.__getitem__
            probe['fs_space'] = lambda path: {}

            def links(path):
                return '/opt/transport_matrix_executable' if path.endswith('exe') else '/tmp'

            def run_probe():
                output = io.StringIO()
                with (
                    patch.object(os, 'readlink', side_effect=links),
                    patch.object(os, 'sysconf', return_value=100, create=True),
                    patch.object(os, 'getloadavg', return_value=(0, 0, 0), create=True),
                    patch.object(scheduler.time, 'sleep'),
                    patch('sys.stdout', output),
                ):
                    probe['guest_probe']({remote: True})
                return json.loads(output.getvalue())

            sample = run_probe()
            self.assertEqual(sample['solvers'][0]['engine'], 'geant4')
            self.assertEqual(sample['runs'][remote]['progress']['current'], 42)
            self.assertEqual(sample['runs'][remote]['progress']['source'], 'progress_json')
            progress_file.unlink()
            sample = run_probe()
            self.assertEqual(sample['runs'][remote]['progress']['current'], 25)
            self.assertEqual(sample['runs'][remote]['progress']['rate_per_hour'], 18000)

    def test_busy_dc_and_mesh_use_the_longer_quiet_window(self):
        for phase in ('dc_init', 'mesh'):
            row = {'id': 'RUN-012345abcdef', 'kind': 'research', 'state': 'running', 'cpu_set': [0],
                   'processes': [{'engine': 'sdevice', 'cpu_percent': 75}],
                   'progress': {'phase': phase, 'log_updated_at': (NOW - dt.timedelta(minutes=20)).isoformat()}}
            source = {'schema': scheduler.SCHEMA, 'observed_at': NOW.isoformat(), 'guest': guest(), 'tasks': [row]}
            self.assertEqual(scheduler.project_snapshot(source, NOW)['tasks'][0]['health'], 'healthy')
            with patch.dict(os.environ, {'TCAD_STATUS_DC_MESH_QUIET_SECONDS': '1100'}):
                task = scheduler.project_snapshot(source, NOW)['tasks'][0]
            self.assertEqual(task['health_reason'], 'log_silent_high_cpu')
            row['processes'][0]['cpu_percent'] = 5
            task = scheduler.project_snapshot(source, NOW)['tasks'][0]
            self.assertEqual(task['health_reason'], 'log_silent_low_cpu')


class HistoryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'history.json'

    def test_downsampling_keeps_two_hours_and_288_five_minute_buckets(self):
        stamp = int(NOW.timestamp())
        rows = [[stamp - age, *([1] * 9)] for age in range(0, history.DAY_SECONDS + 1200, 20)]
        history.write_private_json(self.path, {'version': 1, 'system_recent': rows, 'system_5m': rows, 'tasks': {}})
        projected = history.update_history(self.path, {'generated_at': NOW.isoformat()})
        stored = history.load_history(self.path)
        self.assertEqual(len(stored['system_recent']), 360)
        self.assertEqual(len(stored['system_5m']), 288)
        self.assertEqual(len(projected['system_recent']), 120)
        self.assertEqual(projected['system_5m'][-1][0], stamp)
        self.assertTrue(all(row[0] > stamp - history.DAY_SECONDS for row in projected['system_5m']))

    def test_damaged_file_recovers_and_non_public_history_identity_is_dropped(self):
        self.path.write_bytes(b'\xffbroken')
        result = history.update_history(self.path, {'generated_at': NOW.isoformat()})
        self.assertEqual(len(result['system_5m']), 1)
        data = history.load_history(self.path)
        data['tasks']['r06-hr-private'] = [[int(NOW.timestamp()), 12, 3, 4]]
        history.write_private_json(self.path, data)
        self.assertEqual(history.load_history(self.path)['tasks'], {})
        if os.name == 'posix':
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o640)

    def test_rate_uses_real_elapsed_time_and_requires_continuous_stall_evidence(self):
        self.assertEqual(history.progress_rate([[0, 10], [120, 10.5], [240, 11]]), (15.0, False))
        self.assertEqual(history.progress_rate([[i, 10] for i in range(0, 1801, 120)]), (0.0, True))
        self.assertEqual(history.progress_rate([[0, 10], [1800, 10]]), (None, False))
        self.assertEqual(history.progress_rate([[0, 10], [120, 2], [240, 3]]), (30.0, False))

    def test_repeated_vm_snapshot_does_not_invent_progress_and_sealed_task_has_no_history(self):
        run = {'id': 'RUN-012345abcdef', 'state': 'running', 'kind': 'research', 'health': 'fine_step',
               'progress': {'simulation_time_ns': 30, 'phase': 'transient'}, 'rss_bytes': 10}
        sealed = {'id': 'RUN-123456abcdef', 'state': 'running', 'kind': 'sealed', 'progress': {'simulation_time_ns': 99}}
        scheduler_snapshot = {'observed_at': NOW.isoformat(), 'observation_stale': False, 'tasks': [run, sealed]}
        status = {'generated_at': NOW.isoformat(), 'simulation': {'scheduler': scheduler_snapshot}}
        history.update_history(self.path, status)
        status['generated_at'] = (NOW + dt.timedelta(seconds=20)).isoformat()
        result = history.update_history(self.path, status)
        self.assertEqual(list(result['tasks']), [run['id']])
        self.assertEqual(len(history.load_history(self.path)['tasks'][run['id']]), 1)
        self.assertIsNone(run['progress']['rate_ns_per_hour'])
        for seconds in range(120, 1801, 120):
            status['generated_at'] = scheduler_snapshot['observed_at'] = (NOW + dt.timedelta(seconds=seconds)).isoformat()
            history.update_history(self.path, status)
        self.assertEqual(run['health'], 'stalled')
        self.assertEqual(run['health_reason'], 'sim_time_frozen_30m')
        self.assertEqual(run['progress']['rate_ns_per_hour'], 0.0)
        saved = history.load_history(self.path)
        self.assertEqual(saved['tasks'][run['id']][-1][-1], 'sim_time_frozen_30m')

    def test_history_preserves_health_reason_and_busy_mesh_is_not_frozen(self):
        stamp = int(NOW.timestamp())
        task = {'id': 'RUN-012345abcdef', 'state': 'running', 'kind': 'research', 'cpu_percent': 70,
                'health': 'healthy', 'progress': {'phase': 'mesh', 'simulation_time_ns': 30}}
        history.write_private_json(self.path, {'version': 1, 'tasks': {
            task['id']: [[sample, 30, None, None] for sample in range(stamp - 1800, stamp, 120)],
        }})
        scheduler_snapshot = {'observed_at': NOW.isoformat(), 'observation_stale': False, 'tasks': [task]}
        status = {'generated_at': NOW.isoformat(), 'simulation': {'scheduler': scheduler_snapshot}}
        result = history.update_history(self.path, status)
        self.assertEqual(task['health'], 'healthy')
        self.assertEqual(result['task_fields'][-1], 'health_reason')
        self.assertIsNone(result['tasks'][task['id']][0][-1])
        task.update(state='uncollected', health='collection_overdue', health_reason='collection_overdue')
        result = history.update_history(self.path, status)
        self.assertEqual(result['tasks'][task['id']][-1][-1], 'collection_overdue')


class StatusProjectionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def source_paths(self):
        raw = {
            'schema': scheduler.SCHEMA, 'observed_at': NOW.isoformat(), 'guest': guest(),
            'tasks': [
                {'kind': 'research', 'id': 'RUN-012345abcdef', 'state': 'running', 'cpu_set': [0],
                 'cwd': '/srv/private', 'pid': 123456789, 'run_id': 'private-raw-id',
                 'parameters': {'temperature_K': 300, 'source_variant': 'ssh /home/private',
                                'lm_license_file': '/var/private'}},
                {'kind': 'sealed', 'id': 'RUN-fff345abcdef', 'state': 'running', 'cpu_set': [1],
                 'started_at': NOW.isoformat(), 'case_id': 'r06-hp-secret'},
            ],
            'batch': {'kind': 'research', 'running': 1, 'total': 1},
        }
        source = json_file(self.root / 'scheduler.json', raw)
        pause = json_file(self.root / 'pause.json', {'reason': 'ssh /var/private pid=123456789'})
        return source, pause

    def build(self):
        source, pause = self.source_paths()
        layout = {'server_root': space(169, 100, 19), 'vm_disk_growth': space(69, 28, 39)}
        system = {'memory': {'total_bytes': 31 * GIB, 'available_bytes': 8 * GIB}, 'storage': layout}
        empty = self.root / 'not-present'
        with (
            patch.object(checker, 'now_iso', return_value=NOW.isoformat()),
            patch.object(checker, 'load_scheduler', side_effect=lambda path: scheduler.load_scheduler(path, NOW)),
            patch.object(checker, 'system_metrics', return_value=system),
            patch.object(checker, 'systemd_state', side_effect=['offline', 'operational']),
            patch.object(checker, 'research_site_state', return_value='operational'),
            patch.object(checker, 'build_research', return_value={'schema_version': 1, 'available': True, 'cases': [
                {'case_id': f'r06-z-example-{i}'} for i in range(338)
            ]}),
        ):
            return checker.build_status(observation_path=empty, runtime_path=empty, runs_root=empty,
                                        pause_path=pause, scheduler_path=source)

    def test_distinct_storage_and_memory_fields_and_history_values(self):
        payload = self.build()
        vm = payload['simulation']['scheduler']['virtual_machine']
        self.assertEqual(vm['storage']['total_bytes'], 87 * GIB)
        self.assertEqual(vm['storage']['available_bytes'], 55 * GIB)
        self.assertEqual(vm['memory']['available_bytes'], 23 * GIB)
        self.assertEqual(payload['system']['memory']['available_bytes'], 8 * GIB)
        rows = history.update_history(self.root / 'history.json', payload)
        sample = dict(zip(rows['system_fields'], rows['system_5m'][0]))
        self.assertEqual([sample[k] for k in ('server_remaining_gib', 'vm_disk_growth_available_gib', 'vm_remaining_gib')], [19, 39, 55])
        self.assertEqual([sample[k] for k in ('server_available_memory_gib', 'vm_available_memory_gib')], [8, 23])
        self.assertEqual(vm['daemon_health']['snpslmd'], {'alive': True, 'elapsed_seconds': 8000})
        self.assertIn('调度维护', payload['simulation']['active_batch']['pause']['reason_zh'])

    def test_server_root_guard_and_overlay_requires_separate_mount(self):
        overlay = self.root / 'overlay'
        with (
            patch.object(checker.os.path, 'ismount', side_effect=[True, False]) as ismount,
            patch.object(checker, 'fs_space', side_effect=[space(169, 100, 19), space(69, 28, 39), space(169, 100, 19)]),
        ):
            available = checker.storage_metrics(overlay)
            missing = checker.storage_metrics(overlay)
        self.assertEqual(ismount.call_args.args, (overlay,))
        self.assertTrue(available['server_root']['low_space'])
        self.assertEqual(available['server_root']['warning_below_bytes'], 20 * GIB)
        self.assertEqual(available['vm_disk_growth']['available_bytes'], 39 * GIB)
        self.assertIsNone(missing['vm_disk_growth']['available_bytes'])

    def test_cli_outputs_and_mirrors_share_one_projection_and_pass_redaction(self):
        full = self.root / 'status.json'
        full_mirror = self.root / 'secondary' / 'status.json'
        live = self.root / 'live.json'
        live_mirror = self.root / 'secondary' / 'live.json'
        hpath = self.root / 'history.json'
        payload = self.build()
        cli = ['status_checker.py', '--output', str(full), '--mirror-output', str(full_mirror),
               '--live-output', str(live), '--live-mirror-output', str(live_mirror), '--history-path', str(hpath)]
        with patch('sys.argv', cli), patch.object(checker, 'build_status', return_value=payload) as builder:
            self.assertEqual(checker.main(), 0)
            builder.assert_called_once()
        self.assertEqual(full.read_bytes(), full_mirror.read_bytes())
        self.assertEqual(live.read_bytes(), live_mirror.read_bytes())
        status_doc, live_doc = (json.loads(path.read_text(encoding='utf-8')) for path in (full, live))
        self.assertEqual(status_doc['generated_at'], live_doc['generated_at'])
        self.assertEqual(status_doc['schema_version'], live_doc['schema_version'], 2)
        self.assertEqual(len(status_doc['research']['cases']), 338)
        self.assertNotIn('research', live_doc)
        self.assertNotIn('cases', live_doc['research_summary'])
        self.assertRegex(live_doc['research_hash'], r'^[a-f0-9]{64}$')
        self.assertEqual(live_doc['research_hash'], checker.build_live(status_doc, {})['research_hash'])
        self.assertLess(live.stat().st_size, full.stat().st_size)
        for path in (full, live):
            data = path.read_text(encoding='utf-8').lower()
            for marker in ('/home/', '/srv/', '/var/', 'run_id', 'pid', 'ssh', 'lm_license_file',
                           'r06-hp-secret', 'fff345abcdef', '123456789', 'private-raw-id'):
                self.assertNotIn(marker, data)

    def test_central_redaction_rejects_private_strings_and_keys(self):
        for value in ('/home/x', '／srv/private', 'run_id', 'pid', 'ssh', 'lm_license_file'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    checker.check_public_payload({'real_key': value})
                with self.assertRaises(ValueError):
                    checker.check_public_payload({value: 'placeholder'})

    def test_mirror_staging_failure_preserves_primary_and_cleans_temporary(self):
        target = self.root / 'status.json'
        target.write_text('previous', encoding='utf-8')
        blocked = self.root / 'file-instead-of-directory'
        blocked.touch()
        args = [
            'status_checker.py', '--output', str(target), '--mirror-output', str(blocked / 'status.json'),
            '--history-path', str(self.root / 'history.json'),
        ]
        payload = self.build()
        with patch('sys.argv', args), patch.object(checker, 'build_status', return_value=payload), patch('sys.stderr'):
            self.assertEqual(checker.main(), 1)
        self.assertEqual(target.read_text(encoding='utf-8'), 'previous')
        self.assertEqual(list(self.root.glob('*.tmp')), [])
