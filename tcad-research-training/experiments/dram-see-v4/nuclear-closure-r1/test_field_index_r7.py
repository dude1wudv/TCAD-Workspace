"""Focused parser and adapter checks for the R7 native field-frame index."""
import ast
import importlib
import json
import tarfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = ROOT / 'experiments/dram-see-v4/nuclear-closure-r1'
import sys
sys.path.insert(0, str(HERE))

import common as c
field = importlib.import_module('field_audit_index_r7')


RHS_SUCCESS = 'Finished, because |RHS| is less than 1.0000e-10.'
WRITING = "Writing plot '{}' (TDR format) ... done."


def be(start, end, step=None):
    if step is None:
        step = end - start
    return f'Computing BE-step from {start:.8g} s to {end:.8g} s (Stepsize: {step:.8g} s)'


def accepted_log(name, start=0., end=1., sentence=RHS_SUCCESS):
    return '\n'.join((be(start, end), sentence, WRITING.format(name)))


class NativeFieldIndexR7Tests(unittest.TestCase):
    def test_exact_rhs_finish_binds_frame_to_its_precise_step(self):
        name = 'gstep_b003_0000_access_des.tdr'
        index, boundary = field.native_index_frames(accepted_log(name),
            [{'time': 0.}, {'time': 1.}], [name])
        self.assertEqual(boundary, [])
        self.assertEqual(len(index), 1)
        self.assertEqual(index[0]['source_file'], name)
        self.assertEqual(index[0]['accepted_index'], 1)
        self.assertEqual(index[0]['start_s'], 0.)
        self.assertEqual(index[0]['end_s'], 1.)

    def test_near_match_and_unknown_rhs_sentences_are_not_success(self):
        name = 'gstep_b003_0000_access_des.tdr'
        for sentence in (
            'Finished, because |RHS| is less than 1.0000e-11.',
            'Finished, because |RHS| is less than 1.0000e-10',
            'Finished, because |Rhs| is less than 1.0000e-10.',
            'Finished because |RHS| is less than 1.0000e-10.',
        ):
            with self.subTest(sentence=sentence):
                with self.assertRaisesRegex(ValueError, 'successful BE step'):
                    field.native_index_frames(accepted_log(name, sentence=sentence),
                        [{'time': 0.}, {'time': 1.}], [name])

    def test_rejection_after_success_still_blocks_frame(self):
        name = 'gstep_b003_0000_access_des.tdr'
        log = '\n'.join((be(0., 1.), RHS_SUCCESS, 'Time step rejected', WRITING.format(name)))
        with self.assertRaisesRegex(ValueError, 'successful BE step'):
            field.native_index_frames(log, [{'time': 0.}, {'time': 1.}], [name])

    def test_failed_step_does_not_leak_success_into_the_next_step(self):
        rejected = 'unrequested-rejected.tdr'
        target = 'gstep_b003_0001_access_des.tdr'
        log = '\n'.join((be(0., 1.), 'Time step rejected', WRITING.format(rejected),
                         be(1., 2.), RHS_SUCCESS, WRITING.format(target)))
        index, _ = field.native_index_frames(log,
            [{'time': 0.}, {'time': 1.}, {'time': 2.}], [target])
        self.assertEqual(len(index), 1)
        self.assertEqual(index[0]['accepted_index'], 2)
        self.assertEqual(index[0]['source_file'], target)

    def test_duplicate_missing_and_ambiguous_frame_logs_are_rejected(self):
        name = 'gstep_b003_0000_access_des.tdr'
        duplicate = accepted_log(name) + '\n' + WRITING.format(name)
        with self.assertRaisesRegex(ValueError, 'more than once'):
            field.native_index_frames(duplicate, [{'time': 0.}, {'time': 1.}], [name])
        with self.assertRaisesRegex(ValueError, 'Missing real TDR Writing record'):
            field.native_index_frames(accepted_log(name), [{'time': 0.}, {'time': 1.}],
                                     [name, 'gstep_b003_0001_access_des.tdr'])
        times = [{'time': 0.}, {'time': 1e-10}, {'time': 2e-10}]
        coarse = '\n'.join((
            'Computing BE-step from 0 s to 0 s (Stepsize: 0 s)',
            RHS_SUCCESS, WRITING.format(name)))
        with self.assertRaisesRegex(ValueError, 'missing or ambiguous'):
            field.native_index_frames(coarse, times, [name])

    def test_old_success_phrases_keep_the_same_index_output(self):
        prior = field.libraries().prior
        rows = [{'time': 0.}, {'time': 1.}, {'time': 2.}]
        for sentence in ('Error smaller than 1', 'Rhs smaller than 1'):
            with self.subTest(sentence=sentence):
                name = 'gstep_b003_0001_access_des.tdr'
                log = accepted_log(name, 1., 2., sentence)
                new = field.native_index_frames(log, rows, [name])
                old = prior.index_frames(log, rows, [name])
                self.assertEqual(new, old)

    def test_source_window_prefix_and_expected_accepted_step_are_mandatory(self):
        rows = [{'time': 0.}, {'time': 1.}, {'time': 2.}]
        params = dict(source_windows_s=[[0., 2.]], time_blocks=[dict(index=3,
            active_source=True, initial_s=0., final_s=2., max_step_s=1.)])
        names = ['gstep_b003_0000_access_des.tdr', 'gstep_b003_0001_access_des.tdr']
        log = '\n'.join((accepted_log(names[0], 0., 1.), accepted_log(names[1], 1., 2.)))
        index, _ = field.index_frames(log, rows, names, params)
        self.assertEqual([x['accepted_index'] for x in index], [1, 2])
        wrong_prefix = ['gstep_b004_0000_access_des.tdr', names[1]]
        wrong_log = '\n'.join((accepted_log(wrong_prefix[0], 0., 1.), accepted_log(wrong_prefix[1], 1., 2.)))
        with self.assertRaisesRegex(ValueError, 'Frame block prefix'):
            field.index_frames(wrong_log, rows, wrong_prefix, params)
        missing_step_log = accepted_log(names[0], 0., 1.)
        with self.assertRaisesRegex(ValueError, 'Missing/extra source-window'):
            field.index_frames(missing_step_log, rows, [names[0]], params)

    def test_real_completed_source_archive_reproduces_all_69_frames_including_0000(self):
        attempt_path = ROOT / 'local_runtime/dram-see-v4/nuclear-closure-r1/attempts/nc-r1-qualification-zero.json'
        attempt = json.loads(attempt_path.read_text(encoding='utf-8'))
        self.assertEqual(attempt['state'], 'EXECUTED')
        self.assertEqual(attempt['exit_code'], 0)
        run = ROOT / attempt['run_directory']
        manifest, report = field.source_provenance(run)
        self.assertEqual(manifest['state'], 'COLLECTED')
        self.assertEqual(report['frame_count'], 69)
        with tarfile.open(run / 'results.tar') as archive:
            archived = {Path(m.name.removeprefix('./')).name for m in archive.getmembers()
                        if m.isfile() and m.name.endswith('_access_des.tdr') and
                        Path(m.name.removeprefix('./')).name.startswith('gstep_')}
        indexed = {row['source_file'] for row in report['accepted_intervals']}
        self.assertEqual(len(indexed), 69)
        self.assertEqual(indexed, archived)
        self.assertIn('gstep_b003_0000_access_des.tdr', indexed)
        self.assertEqual(len({row['accepted_index'] for row in report['accepted_intervals']}), 69)

    def test_science_functions_and_adapter_bindings_remain_ast_stable(self):
        base = ast.parse((HERE / 'field_audit.py').read_text(encoding='utf-8'))
        revised = ast.parse((HERE / 'field_audit_index_r7.py').read_text(encoding='utf-8'))
        def functions(tree):
            return {node.name: ast.dump(node, include_attributes=False) for node in tree.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        old, new = functions(base), functions(revised)
        self.assertEqual({name for name in old if old[name] != new.get(name)}, {'index_frames'})
        self.assertNotIn('native_index_frames', old)
        self.assertIn('native_index_frames', new)

        def dump(path):
            return ast.parse(path.read_text(encoding='utf-8'))
        def normalize(tree, replacements, module_names=None):
            module_names = module_names or {}
            class Bindings(ast.NodeTransformer):
                def visit_Constant(self, node):
                    if isinstance(node.value, str) and node.value in replacements:
                        return ast.copy_location(ast.Constant(replacements[node.value]), node)
                    return node
                def visit_Import(self, node):
                    for alias in node.names:
                        if alias.name in module_names:
                            alias.name = module_names[alias.name]
                    return node
                def visit_ImportFrom(self, node):
                    if node.module in module_names:
                        node.module = module_names[node.module]
                    return node
            return ast.dump(Bindings().visit(tree), include_attributes=False)

        def assert_only_bindings(base_name, revised_name, replacements, module_names=None):
            before, after = dump(HERE / base_name), dump(HERE / revised_name)
            revised_values = [node.value for node in ast.walk(after) if isinstance(node, ast.Constant)
                              and isinstance(node.value, str) and node.value in replacements]
            self.assertEqual(set(revised_values), set(replacements))
            self.assertEqual(ast.dump(before, include_attributes=False), normalize(after, replacements, module_names))

        assert_only_bindings('acceptance.py', 'acceptance_field_r7.py',
                             {'field_audit_index_r7.py': 'field_audit.py'})
        assert_only_bindings('campaign_index_r5.py', 'campaign_field_r7.py', {
            'acceptance_field_r7.py': 'acceptance.py', 'field_audit_index_r7.py': 'field_audit.py'},
            {'acceptance_field_r7': 'acceptance'})
        assert_only_bindings('continue_pmi_r6.py', 'continue_fields_r7.py', {
            'release-fields-r7.json': 'release-pmi-r6.json',
            'Field-index r7 not released': 'PMI recovery r6 not released',
            'campaign_field_r7.py': 'campaign_index_r5.py'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
