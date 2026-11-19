"""Reject false zero evidence and snapshot/full-frame confusion; no solver."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('mesh_diagnostic',Path(__file__).with_name('audit_mesh_diagnostic.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class MeshDiagnosticTests(unittest.TestCase):
    def test_missing_A0_field_does_not_become_numeric_zero(self):
        out={}
        with patch.object(m.r2,'cadence',return_value={'test_only':True}):
            m.source_curve({'device':[{'time':0.},{'time':4e-9}]},{'case_id':'A0'},m.b.source_spec('A0'),out)
        self.assertIsNone(out['radiation']['generated_fC'])
        self.assertIn('no_numeric_zero',out['radiation']['evidence'])
    def test_A0_nonzero_observation_is_failure(self):
        rows=[{'time':0.,'IntegrSemiconductor HeavyIonGeneration':0.},{'time':1e-9,'IntegrSemiconductor HeavyIonGeneration':1.}]
        with patch.object(m.r2,'cadence',return_value={}):
            with self.assertRaisesRegex(ValueError,'nonzero'):
                m.source_curve({'device':rows},{'case_id':'A0'},m.b.source_spec('A0'),{})
    def test_sourceful_spec_cannot_be_A0(self):
        with patch.object(m.r2,'cadence',return_value={}):
            with self.assertRaisesRegex(ValueError,'structurally source-free'):
                m.source_curve({'device':[{'time':0.}]},{'case_id':'A0'},m.b.source_spec('A1'),{})
    def test_A1_missing_legacy_fails(self):
        with patch.object(m.r2,'cadence',return_value={}):
            with self.assertRaisesRegex(ValueError,'Missing legacy'):
                m.source_curve({'device':[{'time':0.}]},{'case_id':'A1'},m.b.source_spec('A1'),{})
    def bind(self,report):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'audit.json';p.write_text(json.dumps(report))
            return m.field_binding(p,dict(run_id='right',archive_sha256='archive',manifest_sha256='manifest'))
    def test_snapshot_pass_never_satisfies_full_field_gate(self):
        with self.assertRaisesRegex(ValueError,'full-frame'):
            self.bind(dict(schema='source-field-audit-r1',mode='snapshots',passed=True,field_measurements_passed=False))
    def test_failed_native_field_gate_cannot_be_overridden(self):
        with self.assertRaisesRegex(ValueError,'failed or incomplete'):
            self.bind(dict(schema='source-field-audit-r1',mode='full',passed=False,field_measurements_passed=True))
    def test_wrong_original_run_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'another run'):
            self.bind(dict(schema='source-field-audit-r1',mode='full',passed=True,field_measurements_passed=True,
                           run_id='other',archive_sha256='archive',manifest_sha256='manifest'))

if __name__=='__main__':unittest.main()
