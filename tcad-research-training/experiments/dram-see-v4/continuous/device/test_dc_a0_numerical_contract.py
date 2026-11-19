"""F1: real input bytes + actual A0 generator, never a native success fixture."""
import hashlib
import json
from pathlib import Path
import tarfile
import unittest
import uuid

import case_contract
import dc_continuation
import geometry_bridge as bridge
import numerics_patch
import prepare_case

ROOT=Path(__file__).resolve().parents[4]
OUT=ROOT/'local_runtime/dram-see-v4/continuous/device/d3-dc-geometry-checkpoint-r2'
SOURCE=ROOT/'local_runtime/runs/20261017T154137Z-v4-continuous-b1-d3-r12/results.tar'
SOURCE_NAMES=('physics-manifest.json','physics.par','Silicon.par','Oxide.par','geometry-contract.json',
              'model.proposed.json','numerical-method.json')+bridge.GEOMETRY_MESH_POLICY_FILES


class DCA0NumericalContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tarfile.open(SOURCE,'r:*') as archive:
            cls.producer={n:archive.extractfile(n).read() for n in SOURCE_NAMES}
        cls.request=dict(schema=case_contract.SCHEMA,kind='transient',dimension=3,gate_top_depth_nm=80,
            sn_junction_depth_nm=87,variant='main',stored_bit=0,source_case='A0',
            d3_source_run='UNIT_FIXTURE_NOT_NATIVE_NO_COMPLETED_DC')
        cls.payload=prepare_case.transient_payload(json.loads(cls.producer['model.proposed.json']),cls.request,
            {'unit_input_only':True,'not_a_native_producer_binding':True},cls.producer)
        cls.folder=OUT/('UNIT_FIXTURE_NOT_NATIVE-mixed-inputs-'+uuid.uuid4().hex[:10]);cls.folder.mkdir()
        for n,raw in cls.payload.items():(cls.folder/n).write_bytes(raw)
        (cls.folder/'SYNTHETIC_NOT_NATIVE').write_text('Generated input comparison only; no native result or successful producer.\n',encoding='utf-8')

    def test_actual_a0_generator_keeps_mixed_contract_and_original_dc_proof(self):
        source_raw=self.producer['numerical-method.json'];mixed=self.payload['numerical-method.json']
        self.assertEqual(json.loads(source_raw),numerics_patch.contract(3,mixed=False))
        self.assertEqual(json.loads(mixed),numerics_patch.contract(3,mixed=True))
        self.assertNotEqual(source_raw,mixed)
        self.assertIn(b'Transient=BE Method=Blocked SubMethod=ILS(set=1)',self.payload['device.cmd'])
        bridge.geometry_compare_dc_a0_inputs(self.folder,self.producer)
        self.assertEqual((self.folder/'numerical-method.json').read_bytes(),mixed)
        self.assertEqual(self.producer['numerical-method.json'],source_raw)
        # The fixed completed-DC verifier keeps its original numerical identity
        # via the scientific input set and full original inputs.tar audit.
        scientific=set(dc_continuation.metadata_module().mesh_module().IDENTICAL_INPUTS)-set(dc_continuation.metadata_module().CHANGED_IMPLEMENTATIONS)
        self.assertIn('numerical-method.json',scientific)
        self.assertNotIn('numerical-method.json',dc_continuation.RUNTIME_FILES)
        self.assertEqual(hashlib.sha256((Path(__file__).parent/'dc_continuation.py').read_bytes()).hexdigest(),
                         'cb4de15e60acc39255b532268d1974ea65d092b370ad5025faf41e25eb8f11c2')

    def test_role_specific_numerics_does_not_relax_shared_physics_or_mesh(self):
        for name in ('physics.par','model.proposed.json','geometry-contract.json','mesh-policy.json'):
            with self.subTest(name=name):
                path=self.folder/name;original=path.read_bytes()
                try:
                    path.write_bytes(original+b'\nUNIT_FIXTURE_CHANGED_SHARED_INPUT\n')
                    with self.assertRaisesRegex(ValueError,'A0 input differs from completed DC: '+name):
                        bridge.geometry_compare_dc_a0_inputs(self.folder,self.producer)
                finally:path.write_bytes(original)


if __name__=='__main__':unittest.main()
