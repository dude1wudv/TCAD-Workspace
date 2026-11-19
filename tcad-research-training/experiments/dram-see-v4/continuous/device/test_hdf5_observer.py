"""New HDF5 reader rejection boundaries. Fixtures never imply native qualification."""
import ast
import copy
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
RUNTIME = ROOT / 'local_runtime/dram-see-v4/continuous/device/hdf5-observer-r1'
RAW = RUNTIME / 'raw-layout'
spec = importlib.util.spec_from_file_location('tested_hdf5_observer', HERE / 'hdf5_observer.py')
H = importlib.util.module_from_spec(spec); spec.loader.exec_module(H)


class Hdf5ObserverGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.decoded = json.loads((RUNTIME / 'schema-decoded-r1.json').read_text(encoding='utf-8'))
        cls.audit = json.loads((RUNTIME / 'actual-r1/audit.json').read_text(encoding='utf-8'))
        cls.output = json.loads((RUNTIME / 'actual-r1/output.json').read_text(encoding='utf-8'))
        cls.plan = json.loads((ROOT / 'local_runtime/dram-see-v4/continuous/device/gradient-mesh-r6-r1/projects/20261017T124649Z-v4-continuous-b1-d3-r9/measurement-plan.json').read_text(encoding='utf-8'))

    def fixture(self, exports=False):
        tmp = tempfile.TemporaryDirectory(prefix='UNIT_FIXTURE_NOT_NATIVE-', dir=str(RUNTIME))
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name)
        for source in RAW.iterdir():
            if source.is_file():
                os.link(str(source), str(path / source.name))
        if exports:
            (path / 'hdf5-export').mkdir()
            for source in (RAW / 'hdf5-export').iterdir():
                os.link(str(source), str(path / 'hdf5-export' / source.name))
        return path

    def replace(self, path, raw):
        # Detach only the new fixture hardlink before writing; originals stay unchanged.
        path.unlink()
        with path.open('xb') as stream:
            stream.write(raw)

    def replace_indexed_json(self, root, name, obj):
        path = root / name
        raw = (json.dumps(obj, indent=2) + '\n').encode('utf-8')
        self.replace(path, raw)
        index = json.loads((root / '_collection-members.json').read_text())
        index[name] = {'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        self.replace(root / '_collection-members.json', json.dumps(index).encode('utf-8'))

    def test_missing_duplicate_and_fake_exit_exports_rejected(self):
        for variant in ('missing', 'duplicate', 'boolean_exit'):
            with self.subTest(variant=variant):
                root = self.fixture(True); export = root / 'hdf5-export'
                m = json.loads((export / 'raw-export-manifest.json').read_text())
                if variant == 'missing': m['exports'].pop()
                elif variant == 'duplicate': m['exports'][1]['path'] = m['exports'][0]['path']
                else: m['all_native_exit_codes'][0] = False
                self.replace_indexed_json(export, 'raw-export-manifest.json', m)
                with self.assertRaises(ValueError): H.load_export(root)

    def test_raw_bytes_and_native_command_exit_rejected(self):
        root = self.fixture(True); export = root / 'hdf5-export'
        self.replace(export / 'dataset-01.bin', b'x' * 24)
        with self.assertRaisesRegex(ValueError, 'hash/size'): H.load_export(root)
        root = self.fixture(True); export = root / 'hdf5-export'
        rec = json.loads((export / 'dataset-00-command.json').read_text()); rec['exit_code'] = 137
        self.replace_indexed_json(export, 'dataset-00-command.json', rec)
        with self.assertRaisesRegex(ValueError, 'command/exit'): H.load_export(root)

    def test_strict_ddl_no_unknown_types_or_extra_tokens(self):
        ddl = (RAW / 'hdf5-export/dataset-00-stdout.txt').read_text()
        parsed = H.DDL(ddl).parse()
        self.assertEqual(parsed['datasets'][H.GEO + '/vertex']['shape'], [1807947])
        for bad in (ddl.replace('H5T_IEEE_F64LE', 'H5T_IEEE_F64BE', 1), ddl + 'unexpected', ddl[:-3]):
            with self.subTest(bad=bad[-30:]), self.assertRaises(ValueError): H.DDL(bad).parse()
        # Compound member types are checked after DDL parsing, independently.
        export = {'ddl': copy.deepcopy({'groups': self.decoded['groups'], 'datasets': self.decoded['datasets']})}
        export['ddl']['datasets'][H.GEO + '/vertex']['dtype']['members'].reverse()
        with self.assertRaisesRegex(ValueError, 'coordinate storage'): H._schema(export, self.plan)

    def test_actual_units_and_all_attributes_schema(self):
        export = {'ddl': copy.deepcopy({'groups': self.decoded['groups'], 'datasets': self.decoded['datasets']})}
        n, regions, fields = H._schema(export, self.plan)
        self.assertEqual((n, len(regions), len(fields)), (1807947, 13, 16))
        self.assertTrue(all(f['unit'] == ('um' if f['field'] == 'DelVorWeight' else 'cm^-3') for f in fields))
        for group, key, value in [(H.GEO, 'unit:name', 'cm'), (H.GEO + '/state_0/dataset_0', 'unit:name', 'cm^-3'),
                                  (H.GEO + '/state_0/dataset_1', 'conversion factor', 2.)]:
            changed = copy.deepcopy(export)
            changed['ddl']['groups'][group]['attributes'][key]['value'] = value
            with self.assertRaises(ValueError): H._schema(changed, self.plan)

    def test_complete_range_signed_net_and_tail_nonfinite(self):
        root = self.fixture(); path = root / 'field.bin'
        path.write_bytes(struct.pack('<3d', -1e17, 0., 1.449e20))
        self.assertEqual(H._range(path), dict(count=3, min=-1e17, max=1.449e20, nonzero=2))
        path.write_bytes(struct.pack('<d', 1.) * 65536 + struct.pack('<d', float('inf')))
        with self.assertRaisesRegex(ValueError, 'Nonfinite'): H._range(path)
        path.write_bytes(b'123')
        with self.assertRaisesRegex(ValueError, 'Truncated'): H._range(path)

    def test_connectivity_record_and_face_key_boundaries(self):
        root = self.fixture(); path = root / 'elements.bin'
        path.write_bytes(struct.pack('<5i', 5, 0, 1, 2, 3))
        self.assertEqual(list(H._records(path, 5)), [(5, 0, 1, 2, 3)])
        path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaisesRegex(ValueError, 'Truncated'): list(H._records(path, 5))
        n = 1 << 24  # Algorithm identity works above uint64 packing range; no point quota.
        self.assertEqual(H._face(3, 2, 1, n), H._face(1, 2, 3, n))
        self.assertNotEqual(H._face(1, 2, 3, n), H._face(1, 2, 4, n))

    def test_original_metadata_replay_and_duplicate_boundary_rejection(self):
        export = {'manifest': {'original_mesh_sha256': self.audit['original_mesh_sha256']}}
        identity = H._metadata(RAW, export, self.audit['grid'], self.audit['datasets'])
        self.assertEqual(identity[0]['sha256'], identity[1]['sha256'])
        root = self.fixture(); path = root / 'tdr-region-datasets.csv'
        content = path.read_text(); row = [line for line in content.splitlines() if 'NO_DATASETS' in line][0]
        self.replace(path, (content + row + '\n').encode('utf-8'))
        with self.assertRaisesRegex(ValueError, 'duplicate native boundary'): H._metadata(root, export, self.audit['grid'], self.audit['datasets'])

    def test_missing_or_mismatching_svisual_is_not_acceptance(self):
        root = self.fixture()
        with mock.patch.object(H, 'read_native', return_value=(self.output, copy.deepcopy(self.audit))):
            with self.assertRaises(FileNotFoundError): H.observe(self.plan, root)
        rows = []
        for axis, bounds in zip('XYZ', self.audit['grid']['bounds']):
            for op, value in zip(('min', 'max'), bounds):
                rows.append({'id': 'domain.'+axis+'.'+op, 'raw_value': repr(value), 'command_status': 'OK'})
        with (root / 'material-measurements.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=['id','raw_value','command_status']); writer.writeheader();writer.writerows(rows)
        with mock.patch.object(H, 'read_native', return_value=(self.output, copy.deepcopy(self.audit))):
            values, audit = H.observe(self.plan, root)
        self.assertEqual(len(values), 36);self.assertFalse(audit['scientific_qualification'])
        rows[0]['raw_value'] = str(float(rows[0]['raw_value']) + 2 * self.plan['comparison_policy']['coordinate_absolute_um'])
        with (root / 'material-measurements.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=['id','raw_value','command_status']); writer.writeheader();writer.writerows(rows)
        with mock.patch.object(H, 'read_native', return_value=(self.output, copy.deepcopy(self.audit))):
            with self.assertRaisesRegex(ValueError, 'corroboration differs'): H.observe(self.plan, root)

    def test_python36_grammar(self):
        ast.parse((HERE / 'hdf5_observer.py').read_text(encoding='utf-8'), feature_version=(3, 6))


if __name__ == '__main__':
    unittest.main(verbosity=2)
