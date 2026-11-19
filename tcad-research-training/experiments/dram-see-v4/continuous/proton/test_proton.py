"""Focused offline candidate checks; none are native qualification evidence."""
import json
import math
from pathlib import Path
import tempfile
import unittest
import couple
import prepare


class SourceRepresentation(unittest.TestCase):
    def source(self, p0=(0,0,0), p1=(0,0,0), duration=0, q=.01):
        return list(p0)+list(p1)+[15e-9,15e-9+duration,q,couple.WIDTH,couple.SIGMA]

    def test_point_not_discarded_and_charge_not_rescaled(self):
        rows=couple.represent([self.source()])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['segment_length_um'],0)
        self.assertEqual(rows[0]['source_charge_fC'],.01)
        self.assertAlmostEqual(rows[0]['tabulated_all_space_charge_fC'],.01,places=12)

    def test_oblique_spatial_and_temporal_subdivision_charge(self):
        source=self.source(p1=(.1,.2,.3),duration=5e-12,q=2.5)
        rows=couple.represent([source])
        self.assertGreater(len(rows),1)
        self.assertAlmostEqual(sum(r['source_charge_fC'] for r in rows),2.5,places=12)
        self.assertAlmostEqual(sum(r['tabulated_all_space_charge_fC'] for r in rows),2.5,places=7)
        for row in rows:
            self.assertLessEqual(row['source_time_span_s'],couple.SIGMA/8*(1+1e-10))
            self.assertAlmostEqual(sum(x*x for x in row['direction']),1)

    def test_long_segment_sampling_preserves_charge(self):
        f=couple.represent([self.source(p1=(0,0,2.))])[0]
        self.assertAlmostEqual(f['tabulated_all_space_charge_fC'],.01,places=12)

    def test_profile_convolution_matches_independent_midpoint_integral(self):
        length=.071; width=couple.WIDTH; n=40000
        for s in (-.08,0,.027,.071,.12):
            numerical=sum(math.exp(-((s-(i+.5)*length/n)/width)**2)/(math.sqrt(math.pi)*width)
                          for i in range(n))/n
            self.assertAlmostEqual(couple.profile(s,length,width),numerical,delta=1e-8)

    def test_split_time_centroid_preserved(self):
        source=self.source(p1=(0,0,.1),duration=8e-12,q=1.7)
        rows=couple.represent([source])
        centre=sum(r['temporal_center_s']*r['source_charge_fC'] for r in rows)/1.7
        self.assertAlmostEqual(centre,(source[6]+source[7])/2,delta=1e-21)

    def test_source_identity_zero_length_and_energy_conversion(self):
        row=dict(event_id='0',track_id='2',step_id='4',edep_MeV='.001',niel_MeV='.0001',ionizing_MeV='.0009',
                 pre_material='G4_Si',pre_t_ns='0',post_t_ns='0',particle='Si28',parent_id='1',deposit_kind='point_zero_length')
        row.update({prefix+a+'_um':'0' for prefix in ('pre_','post_') for a in 'xyz'})
        sources,ledger=couple.source_rows_from_steps([row],0,15e-9)
        self.assertEqual(len(sources),1)
        self.assertEqual(sources[0][:3],sources[0][3:6])
        self.assertAlmostEqual(sources[0][8],.0009*1e6/3.6*couple.E_CHARGE*1e15)
        with self.assertRaisesRegex(ValueError,'Duplicate'):couple.source_rows_from_steps([row,row],0,15e-9)
        bad=dict(row,ionizing_MeV='.0008')
        with self.assertRaisesRegex(ValueError,'ionizing'):couple.source_rows_from_steps([bad],0,15e-9)

    def test_empty_is_structural_source_absence(self):
        self.assertEqual(couple.represent([]),[])
        self.assertEqual(couple.render([]),('',''))

    def test_nonfinite_and_wrong_units_rejected(self):
        source=self.source();source[8]=float('nan')
        with self.assertRaises(ValueError):couple.represent([source])
        source=self.source();source[-2]=.05
        with self.assertRaises(ValueError):couple.represent([source])


class Preparation(unittest.TestCase):
    def test_source_mutation_preserves_native_provenance_and_ancestry(self):
        code=prepare.transport_source().decode()
        self.assertIn('No filtering by edep, particle, creator or material',code)
        self.assertIn('const G4Track*',code)
        self.assertIn('GetNonIonizingEnergyDeposit',code)
        self.assertIn('c.energy=std::stod(argv[6])',code)
        self.assertIn('GetProductionCut(j)/um-frozen::cut_um',code)
        self.assertNotIn('frozen::requests',code)

    def test_bcat_axes_and_actual_native_probe_input(self):
        contract,header,probes=prepare.geometry_package(prepare.DEFAULT_MODEL)
        self.assertIn('identity',contract['coordinate_transform'])
        self.assertEqual(contract['gate_transport_material'],'G4_Galactic')
        self.assertGreater(len(probes.splitlines()),1000)
        materials=set()
        for line in probes.decode().splitlines():
            x,y,z,material=line.split();materials.add(material)
            self.assertNotEqual(float(z),0.)
        self.assertEqual(materials,{'G4_Galactic','G4_Si','G4_SILICON_DIOXIDE'})
        self.assertIn(b'0.002',header)

    def test_original_failures_are_not_policy_inputs(self):
        source=Path(prepare.__file__).read_text(encoding='utf-8')
        self.assertNotIn('import supervisor',source)
        self.assertNotIn('release()',source)
        self.assertNotIn('budget_r12',source)
        self.assertNotIn('subprocess',source)


if __name__=='__main__':unittest.main()
