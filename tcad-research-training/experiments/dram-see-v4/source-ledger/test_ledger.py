import importlib.util
from pathlib import Path
import unittest
import math

spec=importlib.util.spec_from_file_location('ledger',Path(__file__).with_name('build_manifest.py'))
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

class LedgerTests(unittest.TestCase):
    def test_center_and_independent_gaussian_edge(self):
        bounds=[[0,1],[0,1],[0,1]]
        g,s,j,e=m.kernel_fractions([0,.3,.5],[0,.7,.5],1,1,bounds)
        self.assertAlmostEqual(g,1)
        self.assertAlmostEqual(s,.5,places=10)
        self.assertAlmostEqual(j,.5,places=10)
        self.assertLess(e,1e-10)
    def test_thick_long_chord_narrow_boundary(self):
        g,s,j,e=m.kernel_fractions([0,0,0],[5000,0,0],1,1,[[-5000,5000]]*3)
        expected=1-m.WIDTH_UM/(2*math.sqrt(math.pi)*5000)
        self.assertAlmostEqual(s,expected,places=11)
        self.assertLess(e,1e-10)
    def test_window_not_compressed(self):
        g,s,j,e=m.kernel_fractions([.5,.3,.5],[.5,.7,.5],20,21,[[0,1]]*3)
        self.assertAlmostEqual(g,1); self.assertAlmostEqual(s,1); self.assertEqual(j,0)
    def test_geometrical_outside(self):
        self.assertEqual(m.segment_interval([-2,.5,.5],[-1,.5,.5],[[0,1]]*3),(0,0))
        self.assertEqual(m.segment_interval([-.5,.5,.5],[1.5,.5,.5],[[0,1]]*3),(.25,.75))
    def test_native_3d_rejected(self):
        with self.assertRaisesRegex(ValueError,'Undefined 3D'):
            m.reject_2d({'dimensionality':'native_3d'})
    def test_point_positive_preserved(self):
        row=dict(event_id='0',track_id='1',parent_id='0',step_id='1',particle='proton',pdg='2212',step_um='0',ionizing_MeV='1',edep_MeV='1',niel_MeV='0',pre_t_ns='0',post_t_ns='0',pre_material='G4_Si',post_material='G4_Si',pre_volume='Si',post_volume='Si')
        for prefix in ('pre','post'):
            for axis in 'xyz': row[prefix+'_'+axis+'_um']='.5'
        entry=m.step_entry(row,'test',[[0,1]]*3)
        self.assertIsNone(entry['local_ionizing_deposition_density_MeV_per_um'])
        self.assertEqual(entry['account']['pending_point_kernel_fC'],m.Q_PER_MEV_FC)
        self.assertEqual(entry['account']['candidate_in_fC'],0)

if __name__=='__main__': unittest.main()
