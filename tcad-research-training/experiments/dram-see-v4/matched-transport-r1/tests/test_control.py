"""Offline geometry and request-contract counterexamples; no Geant4 execution."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('matched_control_test',HERE.parent/'control.py')
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.geometry = c.read(c.GEOMETRY)
        self.temporary = tempfile.TemporaryDirectory(prefix='offline-',dir=HERE)
        self.root = Path(self.temporary.name)
        self.geometry_path = self.root/'geometry-contract.json'

    def tearDown(self):
        self.temporary.cleanup()

    def make(self):
        self.geometry_path.write_text(json.dumps(self.geometry),encoding='utf-8')
        return c.make_contract(self.geometry_path)

    def test_six_calls_eight_primaries_and_frozen_seeds(self):
        value = self.make()
        self.assertEqual(len(value['requests']),6)
        self.assertEqual(sum(r['event_count'] for r in value['requests']),8)
        self.assertEqual([r['seed'] for r in value['requests']],
                         [40142001,40142002,40142101,40142102,40142103,40142104])
        self.assertEqual(value['retry_limit'],0)

    def test_entry_before_all_materials_and_miss_outside(self):
        value = self.make()
        normal,miss = value['requests'][2],value['requests'][4]
        self.assertEqual(normal['beam_position_um'],[.7,-1.005,0.])
        self.assertEqual(normal['surface_position_um'],[.7,0.,0.])
        self.assertEqual(miss['beam_position_um'],[1.85,-1.005,0.])
        self.assertIsNone(miss['surface_position_um'])
        self.assertEqual(value['world_half_um'],[10.85,11.2,10.5])

    def test_shared_extra_material_changes_transport_geometry(self):
        self.geometry['solids'].append(dict(id='R.Passivation',shape='cuboid',min_um=[0,-.1,-.5],
            max_um=[.85,-.05,.5],sde_material='Oxide',geant4_material='G4_SILICON_DIOXIDE',density_g_cm3=2.2))
        value=self.make()
        self.assertEqual(value['requests'][2]['surface_position_um'],[.7,-.1,0.])
        self.assertEqual(value['requests'][2]['beam_position_um'],[.7,-1.1,0.])
        self.assertEqual(len(value['geometry']['solids']),3)

    def test_real_overlap_rejected_but_touching_si_oxide_allowed(self):
        self.make()
        self.geometry['solids'][1]['max_um'][1]=.001
        with self.assertRaisesRegex(ValueError,'Overlapping'):
            self.make()

    def test_missing_z_rejected(self):
        self.geometry['solids'][0]['min_um'].pop()
        with self.assertRaisesRegex(ValueError,'three-dimensional'):
            self.make()

    def test_transformed_coordinates_rejected(self):
        self.geometry['coordinate_system']='drop-z'
        with self.assertRaisesRegex(ValueError,'untransformed'):
            self.make()

    def test_nonfinite_coordinates_rejected(self):
        self.geometry['solids'][0]['max_um'][2]=float('nan')
        with self.assertRaisesRegex(ValueError,'extents'):
            self.make()

    def test_duplicate_volume_id_rejected(self):
        self.geometry['solids'][1]['id']=self.geometry['solids'][0]['id']
        with self.assertRaisesRegex(ValueError,'duplicate'):
            self.make()

    def test_header_contains_both_materials_and_exact_request_labels(self):
        value=self.make()
        with patch.object(c,'sha',return_value='a'*64):
            text=c.header(value)
        self.assertIn('G4_SILICON_DIOXIDE',text)
        self.assertIn('G4_Si',text)
        for request in value['requests']:
            self.assertIn('"'+request['label']+'"',text)
        self.assertIn('geometry_sha256',text)

    def operation(self,label,request,code=None):
        folder=self.root/'operations'/label
        folder.mkdir(parents=True)
        (folder/'operation.json').write_text(json.dumps(dict(label=label,state='RUNNING',remote_exit_code=code)))
        inputs=self.root/'inputs'/label
        inputs.mkdir(parents=True)
        (inputs/'request.json').write_text(json.dumps(request))

    def test_unknown_operation_counts_as_consumed_without_retry(self):
        value=self.make(); self.operation(value['requests'][0]['label'],value['requests'][0])
        with patch.object(c,'contract',return_value=value), patch.object(c,'OLD_RUNTIME',self.root), patch.object(c,'ROOT',self.root):
            budget=c.budget_status()
        self.assertEqual(budget['invocation_reservations'],1)
        self.assertEqual(budget['requested_primary_events'],0)
        self.assertIsNone(budget['calls'][0]['remote_exit_code'])

    def test_duplicate_request_under_wrong_operation_identity_blocks(self):
        value=self.make();request=value['requests'][0]
        self.operation('matched-one',request);self.operation('matched-two',request)
        with patch.object(c,'contract',return_value=value), patch.object(c,'OLD_RUNTIME',self.root), patch.object(c,'ROOT',self.root):
            with self.assertRaisesRegex(ValueError,'identity differs'):
                c.budget_status()

    def test_out_of_contract_request_blocks(self):
        value=self.make();request=copy.deepcopy(value['requests'][0]);request['seed']+=1
        self.operation('matched-unapproved',request)
        with patch.object(c,'contract',return_value=value), patch.object(c,'OLD_RUNTIME',self.root), patch.object(c,'ROOT',self.root):
            with self.assertRaisesRegex(ValueError,'differs'):
                c.budget_status()


if __name__=='__main__':
    unittest.main()
