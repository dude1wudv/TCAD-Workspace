"""Isolated recovery checks for the pre-existing PMI ELF; never launches TCAD."""
import ast
import csv
import hashlib
import importlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO = Path(__file__).resolve().parents[3]
EXPERIMENTS = REPO / 'experiments/dram-see-v4/nuclear-closure-r1'
VALIDATION_ROOT = REPO / 'local_runtime/dram-see-v4/nuclear-closure-r1/pmi-build-r2/validation'
VALIDATION_ROOT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(EXPERIMENTS))
import common as c
import supervisor as supervisor
import transport as transport

native = importlib.import_module('native_compile_r2')


class Sandbox:
    """Copy only reviewed original evidence under a disposable fake ROOT."""
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pmi-r2-', dir=VALIDATION_ROOT)
        self.root = Path(self.temp.name) / 'root'
        self.here = self.root / 'experiments/dram-see-v4/nuclear-closure-r1'
        self.rt = self.root / 'local_runtime/dram-see-v4/nuclear-closure-r1'
        self.old = self.root / 'local_runtime/dram-see-v4/transport-probe'
        self.here.mkdir(parents=True, exist_ok=True)
        original = c.ROOT
        self.real_root = original
        real_here = original / 'experiments/dram-see-v4/nuclear-closure-r1'
        real_rt = original / 'local_runtime/dram-see-v4/nuclear-closure-r1'
        real_old = original / 'local_runtime/dram-see-v4/transport-probe'
        for rel in (
            'operations/nc-r1-pmi-build/operation.json',
            'operations/nc-r1-pmi-build/results.tar',
            'operations/nc-r1-pmi-build/collected',
            'inputs/nc-r1-pmi-build',
        ):
            src = real_old / rel
            dst = self.old / rel
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        for rel in (
            'attempts/nc-r1-pmi-build.json',
            'pmi-build-r2/native-library-resolution.json',
            'pmi-build-r2/diagnosis.json',
        ):
            src = real_rt / rel
            dst = self.rt / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        shutil.copy2(real_here / 'pmi-recovery-r2.json', self.here / 'pmi-recovery-r2.json')
        shutil.copy2(real_here / 'pmi_source.C', self.here / 'pmi_source.C')
        shutil.copy2(real_here / 'native_compile_r2.py', self.here / 'native_compile_r2.py')
        self.prior = (c.ROOT, c.HERE, c.RT, c.OLD_OPS)
        c.ROOT, c.HERE, c.RT, c.OLD_OPS = self.root, self.here, self.rt, self.old
        self.spec, self.paths, self.vectors = native.inspect_original()
        for row in self.vectors['vectors']:
            rel = row['native']['path']
            source = self.real_root / rel
            dest = self.root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)

    def close(self):
        c.ROOT, c.HERE, c.RT, c.OLD_OPS = self.prior
        self.temp.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class NativeCompileRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()

    def tearDown(self):
        self.box.close()
        for fixture in VALIDATION_ROOT.glob('mock-op-*'):
            if fixture.is_dir() and fixture.parent.resolve() == VALIDATION_ROOT.resolve():
                shutil.rmtree(fixture)

    def test_original_failure_proof_and_package_reuse_exact_elf(self):
        b = self.box
        op = c.read(b.paths['operation'])
        self.assertEqual([op['ssh_exit_code'], op['remote_exit_code'], op['collection_exit_code']], [78, 78, 0])
        self.assertEqual(b.paths['binary'].stat().st_size, 48064)
        package = native.package(b.spec, b.paths, b.vectors)
        self.assertEqual(package['pmi_nuclear_source.so.linux64'], b.paths['binary'].read_bytes())
        self.assertEqual(hashlib.sha256(package['pmi_nuclear_source.so.linux64']).hexdigest(), '5b40a51255082695f28966f51e4230d0895dc7c2df2d389f186be8f894a17cbd')
        self.assertIn('pmi_nuclear_source.so.linux64', package['expected-sha256.txt'].decode())

    def test_original_noncanonical_failure_exit_is_rejected(self):
        b = self.box
        for field in ('ssh_exit_code', 'remote_exit_code', 'collection_exit_code'):
            with self.subTest(field=field):
                op_path = b.paths['operation']
                op = c.read(op_path)
                op[field] = {'ssh_exit_code': 77, 'remote_exit_code': 79, 'collection_exit_code': 1}[field]
                c.write(op_path, op, exclusive=False)
                contract_path = b.here / 'pmi-recovery-r2.json'
                contract = c.read(contract_path)
                contract['original']['operation']['sha256'] = c.sha(op_path)
                c.write(contract_path, contract, exclusive=False)
                with self.assertRaisesRegex(ValueError, 'exits differ'):
                    native.inspect_original()
                # Reset between independent mutations while retaining the isolated fixture.
                real = b.real_root / 'local_runtime/dram-see-v4/transport-probe/operations/nc-r1-pmi-build/operation.json'
                shutil.copy2(real, op_path)
                contract = c.read(contract_path)
                contract['original']['operation']['sha256'] = c.sha(op_path)
                c.write(contract_path, contract, exclusive=False)

    def test_original_hash_tampering_is_rejected(self):
        b = self.box
        binary = b.paths['binary']
        binary.write_bytes(binary.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'Evidence hash changed'):
            native.inspect_original()

    def test_package_requires_scoped_sdk_ld_path_and_strict_ldd_for_both_elfs(self):
        script = native.package(self.box.spec, self.box.paths, self.box.vectors)['task.sh'].decode()
        self.assertLess(script.index('export LD_LIBRARY_PATH='), script.index('check_dependencies ./pmi_nuclear_source.so.linux64'))
        self.assertIn('ldd "$1"', script)
        self.assertIn('[ "$code" -ne 0 ] || grep -q \'not found\'', script)
        self.assertIn('check_dependencies ./source_probe', script)
        self.assertIn('libstdc++.so.6 => $SDK/lib/libstdc++.so.6', script)
        self.assertIn('libgcc_s.so.1 => $SDK/lib/libgcc_s.so.1', script)

    def _operation_with_output(self, corruption=None, operation=None):
        b = self.box
        if operation is None:
            operation = Path(tempfile.mkdtemp(prefix='mock-op-', dir=VALIDATION_ROOT))
        else:
            operation = Path(operation)
            operation.mkdir(parents=True, exist_ok=False)
        output = operation / 'collected'
        output.mkdir(parents=True)
        package = native.package(b.spec, b.paths, b.vectors)
        for name, raw in package.items():
            dest = output / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
        (output / 'exit-code.txt').write_text('0\n', encoding='utf-8')
        dep_text = (f'libstdc++.so.6 => {b.spec["sdk"]}/lib/libstdc++.so.6 (0x1)\n'
                    f'libgcc_s.so.1 => {b.spec["sdk"]}/lib/libgcc_s.so.1 (0x2)\n')
        for stem in ('linked-libraries', 'probe-linked-libraries'):
            (output / (stem + '.txt')).write_text(dep_text, encoding='utf-8')
            (output / (stem + '.stderr.txt')).write_text('', encoding='utf-8')
            (output / (stem + '.exit-code.txt')).write_text('0\n', encoding='utf-8')
        rows = [{'name': v['name'], 'actual': format(v['expected_cm_minus3_s_minus1'], '.17g')}
                for v in b.vectors['vectors']]
        if corruption:
            kind, index = corruption
            if kind == 'missing':
                rows.pop(index)
            elif kind == 'wrong':
                expected = float(b.vectors['vectors'][index]['expected_cm_minus3_s_minus1'])
                rows[index]['actual'] = '1000' if expected == 0 else '0'
            elif kind in ('ldd', 'probe-ldd'):
                stem = 'linked-libraries' if kind == 'ldd' else 'probe-linked-libraries'
                (output / (stem + '.exit-code.txt')).write_text('1\n', encoding='utf-8')
                (output / (stem + '.txt')).write_text('libstdc++.so.6 => not found\n', encoding='utf-8')
        with (output / 'native-oracle.csv').open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['name', 'actual'])
            writer.writeheader()
            writer.writerows(rows)
        import tarfile
        with tarfile.open(operation / 'results.tar', 'w') as archive:
            for path in sorted(p for p in output.rglob('*') if p.is_file()):
                archive.add(path, arcname='./' + path.relative_to(output).as_posix())
        c.write(operation / 'operation.json', dict(label=native.LABEL, state='COLLECTED_PENDING_AUDIT',
              ssh_exit_code=0, remote_exit_code=0, collection_exit_code=0,
              archive_sha256=c.sha(operation / 'results.tar')))
        return operation

    def test_each_missing_or_numerically_wrong_oracle_is_rejected(self):
        for index, vector in enumerate(self.box.vectors['vectors']):
            with self.subTest(missing=vector['name']):
                operation = self._operation_with_output(('missing', index))
                with mock.patch.object(transport, 'assert_operation_complete', lambda _: None):
                    with self.assertRaisesRegex(ValueError, 'six-probe identity'):
                        native.validate(operation, self.box.spec, self.box.paths, self.box.vectors)
            with self.subTest(wrong=vector['name']):
                operation = self._operation_with_output(('wrong', index))
                with mock.patch.object(transport, 'assert_operation_complete', lambda _: None):
                    with self.assertRaisesRegex(ValueError, 'Native arithmetic disagrees'):
                        native.validate(operation, self.box.spec, self.box.paths, self.box.vectors)

    def test_ldd_failure_blocks_validation_even_when_elf_and_oracles_exist(self):
        for kind in ('ldd', 'probe-ldd'):
            with self.subTest(kind=kind):
                operation = self._operation_with_output((kind, 0))
                with mock.patch.object(transport, 'assert_operation_complete', lambda _: None):
                    with self.assertRaisesRegex(ValueError, 'Dependency check did not succeed'):
                        native.validate(operation, self.box.spec, self.box.paths, self.box.vectors)

    def test_collected_output_tamper_is_rejected_against_unchanged_archive(self):
        operation = self._operation_with_output()
        output = operation / 'collected' / 'native-oracle.csv'
        output.write_bytes(output.read_bytes() + b'# modified after archive\n')
        with mock.patch.object(transport, 'assert_operation_complete', lambda _: None):
            with self.assertRaisesRegex(ValueError, 'Collected file differs from archive'):
                native.validate(operation, self.box.spec, self.box.paths, self.box.vectors)

    def test_results_archive_tamper_is_rejected_against_saved_receipt_hash(self):
        operation = self._operation_with_output()
        archive = operation / 'results.tar'
        archive.write_bytes(archive.read_bytes() + b'tampered')
        with mock.patch.object(transport, 'assert_operation_complete', lambda _: None):
            with self.assertRaisesRegex(ValueError, 'Operation archive mismatch'):
                native.validate(operation, self.box.spec, self.box.paths, self.box.vectors)

    def test_compiled_proof_remains_unqualified_and_does_not_launch_again(self):
        b = self.box
        self._operation_with_output(operation=b.old / 'operations' / native.LABEL)
        proof = b.rt / 'pmi/build.json'
        binary = b.paths['binary']
        proof.parent.mkdir(parents=True)
        c.write(proof, dict(schema='nuclear-closure-pmi-build-r2', compiled=True, qualified=False,
                            binary=c.ref(binary), evidence=[c.ref(b.paths['operation'])]))
        with mock.patch.object(c, 'check_release'), \
             mock.patch.object(transport, 'assert_operation_complete', lambda _: None), \
             mock.patch.object(supervisor, 'operation', side_effect=AssertionError('must not launch')):
            with self.assertRaisesRegex(ValueError, 'Compilation proof evidence inventory differs'):
                native.ensure_compiled()

    def test_qualified_flag_is_not_inferred_from_compilation(self):
        b = self.box
        proof = b.rt / 'pmi/build.json'
        proof.parent.mkdir(parents=True)
        c.write(proof, dict(schema='nuclear-closure-pmi-build-r2', compiled=True, qualified=True,
                            binary=c.ref(b.paths['binary']), evidence=[]))
        with mock.patch.object(c, 'check_release'):
            with self.assertRaisesRegex(ValueError, 'compilation-only proof'):
                native.ensure_compiled()

    def test_unknown_prior_attempt_is_rejected_without_popen(self):
        b = self.box
        label = native.LABEL
        attempt = b.rt / 'attempts' / (label + '.json')
        op = b.old / 'operations' / label
        attempt.parent.mkdir(parents=True, exist_ok=True)
        op.mkdir(parents=True, exist_ok=True)
        c.write(attempt, dict(kind='compile', label=label, state='FAILED_OR_UNKNOWN', exit_code=2))
        c.write(op / 'operation.json', dict(state='FAILED_COLLECTED', ssh_exit_code=2, remote_exit_code=2, collection_exit_code=0))
        with mock.patch.object(supervisor.subprocess, 'Popen', side_effect=AssertionError('must not Popen')):
            with self.assertRaisesRegex(ValueError, 'Prior attempt unknown/failed'):
                supervisor.operation(label, b.old / 'inputs' / label, 'compile', timeout=1800)

    def test_successful_saved_repair_operation_is_reconciled_without_popen(self):
        b = self.box
        label = native.LABEL
        native.prepare(b.spec, b.paths, b.vectors)
        attempt = b.rt / 'attempts' / (label + '.json')
        attempt.parent.mkdir(parents=True, exist_ok=True)
        c.write(attempt, dict(kind='compile', label=label, state='EXECUTED', exit_code=0))
        operation = self._operation_with_output(operation=b.old / 'operations' / label)
        with mock.patch.object(c, 'check_release'), \
             mock.patch.object(supervisor.subprocess, 'Popen', side_effect=AssertionError('must not Popen')), \
             mock.patch.object(transport, 'assert_operation_complete', lambda _: None):
            binary = native.ensure_compiled()
        proof = c.read(b.rt / 'pmi/build.json')
        self.assertTrue(proof['compiled'])
        self.assertFalse(proof['qualified'])
        self.assertEqual(binary.read_bytes(), b.paths['binary'].read_bytes())
        self.assertTrue(proof['original_binary_reused'])
        with mock.patch.object(c, 'check_release'), \
             mock.patch.object(supervisor, 'operation', side_effect=AssertionError('proof path must remain read only')), \
             mock.patch.object(supervisor.subprocess, 'Popen', side_effect=AssertionError('must not Popen')), \
             mock.patch.object(transport, 'assert_operation_complete', lambda _: None):
            again = native.ensure_compiled()
        self.assertEqual(again.read_bytes(), binary.read_bytes())

    def test_unknown_operation_without_attempt_is_not_adopted_or_relaunched(self):
        b = self.box
        op = b.old / 'operations' / native.LABEL
        op.mkdir(parents=True, exist_ok=True)
        c.write(op / 'operation.json', dict(state='FAILED_COLLECTED', ssh_exit_code=0, remote_exit_code=0, collection_exit_code=0))
        with mock.patch.object(supervisor.subprocess, 'Popen', side_effect=AssertionError('must not Popen')):
            with self.assertRaisesRegex(ValueError, 'exists outside ledger'):
                supervisor.operation(native.LABEL, b.old / 'inputs' / native.LABEL, 'compile')

    def test_r6_scheduler_ast_diff_is_limited_to_three_pmi_release_bindings(self):
        prior = ast.parse((EXPERIMENTS / 'continue_index_r5.py').read_text(encoding='utf-8'))
        current = ast.parse((EXPERIMENTS / 'continue_pmi_r6.py').read_text(encoding='utf-8'))
        substitutions = {
            'release-pmi-r6.json': 'release-audit-index-r5.json',
            'PMI recovery r6 not released': 'Indexed audit r5 not released',
            'native_compile_r2.py': 'native_compile.py',
        }
        actual = [node.value for node in ast.walk(current) if isinstance(node, ast.Constant)
                  and isinstance(node.value, str) and node.value in substitutions]
        self.assertEqual(sorted(actual), sorted(substitutions))

        class NormalizePMIBindings(ast.NodeTransformer):
            def visit_Constant(self, node):
                if isinstance(node.value, str) and node.value in substitutions:
                    return ast.copy_location(ast.Constant(substitutions[node.value]), node)
                return node

        normalized = NormalizePMIBindings().visit(current)
        self.assertEqual(ast.dump(prior, include_attributes=False), ast.dump(normalized, include_attributes=False))


if __name__ == '__main__':
    unittest.main(verbosity=2)
