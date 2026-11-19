"""Offline checks only. Fixtures are retained in this revision's audit-dev tree."""
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import unittest
import uuid

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('source_3d_under_test', HERE/'build_interface.py')
b = importlib.util.module_from_spec(spec)
exec(compile((HERE/'build_interface.py').read_bytes(), str(HERE/'build_interface.py'), 'exec'), b.__dict__)
guard_spec=importlib.util.spec_from_file_location('guard_under_test',HERE/'mesh_resource_guard.py')
guard=importlib.util.module_from_spec(guard_spec)
exec(compile((HERE/'mesh_resource_guard.py').read_bytes(),str(HERE/'mesh_resource_guard.py'),'exec'),guard.__dict__)


class InterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = b.OUTPUT_ROOT/'audit-dev'/('tests-'+uuid.uuid4().hex)
        cls.base.mkdir(parents=True)
        cls.a0 = cls.base/'v4-source-interface-3d-r1-a0-b1-main'
        cls.a1 = cls.base/'v4-source-interface-3d-r1-a1-b1-main'
        cls.before = {p:hashlib.sha256((b.ROOT/p).read_bytes()).hexdigest() for p in b.contract()['frozen_dependency_sha256']}
        b.build(cls.a0, 'A0'); b.build(cls.a1, 'A1')

    @classmethod
    def tearDownClass(cls):
        after = {p:hashlib.sha256((b.ROOT/p).read_bytes()).hexdigest() for p in cls.before}
        if cls.before != after:
            raise AssertionError('An inherited input/code was changed')

    def mutation(self, transform):
        s = copy.deepcopy(b.source_spec('A1')); transform(s)
        with self.assertRaises(ValueError): b.validate_spec(s)

    def test_01_a0_structural_zero(self):
        p = b.offline_proof(b.source_spec('A0'))
        self.assertEqual(p['source_total_fC'], 0)
        self.assertEqual(p['rois']['Total']['tracks'], [])
        self.assertIsNone(p['rois']['Total']['centroid_z_um'])
        self.assertFalse(p['is_tcad_result'])
        self.assertNotIn('HeavyIon("', b.render_deck('A0'))

    def test_02_a1_charge_centroid(self):
        p = b.offline_proof(b.source_spec('A1'))
        self.assertAlmostEqual(p['domain_charge_fC'], 1., places=13)
        for axis, value in zip('xyz', [.425, .6, 0.]):
            self.assertAlmostEqual(p['rois']['Total']['centroid_'+axis+'_um'], value, places=14)
        self.assertAlmostEqual(p['rois']['Total']['time_centroid_s'], 1e-9, places=22)

    def test_03_partitions_and_tube(self):
        p = b.offline_proof(b.source_spec('A1'))['rois']
        for partition in b.contract()['partitions']:
            self.assertAlmostEqual(sum(p[k]['q_fC'] for k in partition), p['Total']['q_fC'], places=13)
        self.assertAlmostEqual(p['ZNegative']['q_fC'], .5, places=13)
        self.assertAlmostEqual(p['CenterTube']['q_fC'], math.erf(1)**2, places=13)

    def test_04_sigma_is_two_ps(self):
        self.assertAlmostEqual(b.oracle.time_density(1e-9,1e-9,2e-12)/(1/(math.sqrt(2*math.pi)*2e-12)), 1., places=14)
        self.assertAlmostEqual(b.oracle.time_mass(.95e-9,1.05e-9,1e-9,2e-12), 1., places=14)

    def test_05_independent_midpoint_volume_integral(self):
        a = b.source_spec('A1')['tracks'][0]
        # Independent midpoint integration of the native 3D radial formula at y=.6.
        n, lo, hi = 800, -.24, .24
        h = (hi-lo)/n
        one = sum(math.exp(-((lo+(i+.5)*h)/.03)**2) for i in range(n))*h
        volume_integral = one*one*.6/(math.pi*.03**2*.6)
        self.assertAlmostEqual(volume_integral, 1., places=12)
        peak = b.generation(b.source_spec('A1'),.425,.6,0,1e-9)
        expected = 1e-15/1.602176634e-19*1e12/(math.pi*.03**2*.6)/(math.sqrt(2*math.pi)*2e-12)
        self.assertAlmostEqual(peak/expected, 1., places=13)

    def test_06_reject_2d(self): self.mutation(lambda s:s.update(dimension=2))
    def test_07_reject_real(self): self.mutation(lambda s:s.update(synthetic=False))
    def test_08_reject_projection(self): self.mutation(lambda s:s.update(projection='drop-z'))
    def test_09_reject_zero_length(self): self.mutation(lambda s:s['tracks'][0].update(length_um=0))
    def test_10_reject_wrong_charge(self): self.mutation(lambda s:s['tracks'][0].update(q_fC=2))
    def test_11_reject_duplicate_allocation(self): self.mutation(lambda s:s['tracks'].append(copy.deepcopy(s['tracks'][0])))
    def test_12_reject_missing_field(self): self.mutation(lambda s:s['tracks'][0].pop('wt_hi_um'))
    def test_13_reject_wrong_sigma(self): self.mutation(lambda s:s['tracks'][0].update(s_hi_s=4e-12))
    def test_14_reject_nan(self): self.mutation(lambda s:s['tracks'][0].update(time_s=float('nan')))
    def test_15_reject_unregistered_z(self): self.mutation(lambda s:s['tracks'][0].update(start_um=[.425,.3,.1]))

    def test_16_allowed_roles(self):
        for args in [('A4',1,'main'),('A1',0,'main'),('A1',1,'fine'),('A1',True,'main')]:
            with self.assertRaises(ValueError): b.check_role(*args)

    def test_17_same_mesh_and_control(self):
        self.assertEqual((self.a0/'geometry.scm').read_bytes(),(self.a1/'geometry.scm').read_bytes())
        self.assertEqual(b.check_control(self.a0,self.a1)['status'],'OFFLINE_MATCHED_CONTROL_PASSED')

    def test_18_circuit_unchanged(self):
        for case in ('A0','A1'):
            old = (b.ROOT/b.contract()['references'][case]/'device.cmd').read_text()
            new = b.render_deck(case)
            self.assertEqual(new[new.index('\nSystem {'):],old[old.index('\nSystem {'):])
            self.assertIn('AreaFactor=1',new)
            self.assertIn('capacitance=1e-14',new)
            self.assertIn('CoordinateSystem { AsIs }',new)

    def test_19_full_accepted_outputs_no_new_times(self):
        for case in ('A0','A1'):
            deck=b.render_deck(case)
            self.assertEqual(deck.count(b.contract()['measurement']['dynamic_plot_command']),1)
            self.assertNotIn('Intervals',deck)
            self.assertEqual(deck.count('Plot(FilePrefix="gfield_'),5)

    def test_20_geometry_3d_and_plane_normal(self):
        text=b.render_geometry().decode()
        self.assertEqual(text.count('sdegeo:create-cuboid'),2)
        self.assertNotIn('find-edge-id',text)
        self.assertNotIn('create-rectangle',text)
        self.assertEqual(text.count('find-face-id'),4)
        self.assertNotIn('MaxLenInt',text)
        for plane in b.geometry_contract()['doping']['source_drain']['baselines']:
            lo,hi=plane['min_um'],plane['max_um']
            # First +z and second +x edges produce +y by a cross product.
            e1=[0,0,hi[2]-lo[2]]; e2=[hi[0]-lo[0],0,0]
            self.assertGreater(e1[2]*e2[0],0)
        core=next(w for w in b.contract()['mesh']['windows'] if w['name']=='SourceCore')
        self.assertLessEqual(core['max_size_um'][2],.01)

    def test_21_source_3d_components_once(self):
        deck=b.render_deck('A1')
        self.assertEqual(deck.count('HeavyIon("Ion1")'),1)
        self.assertIn('Direction=(0,1,0)',deck)
        self.assertIn('StartPoint=(0.42499999999999999,0.29999999999999999,0)',deck)

    def test_22_no_old_runtime_write(self):
        with self.assertRaises(ValueError): b.build(b.ROOT/'local_runtime/dram-see-v4/source-interface-r5/bad','A0')
        with self.assertRaises(ValueError): b.build(self.a0,'A0')

    def test_23_tampered_hash_even_rewritten_manifest(self):
        path=self.base/('v4-source-interface-3d-r1-a1-b1-main-tamper-'+uuid.uuid4().hex)
        b.build(path,'A1')
        deck=(path/'device.cmd').read_bytes().replace(b'AreaFactor=1',b'AreaFactor=2')
        (path/'device.cmd').write_bytes(deck)
        m=b.read_json(path/'input-manifest.json');m['files_sha256']['device.cmd']=b.sha(deck)
        (path/'input-manifest.json').write_bytes(b.encoded(m))
        with self.assertRaises(ValueError): b.check_project(path)

    def test_24_no_thickness_normalization(self):
        self.assertNotIn('effective_thickness_um',b.expected_common())
        self.assertEqual(b.contract()['conversion']['um3_to_cm3'],1e-12)
        self.assertEqual(b.contract()['device']['area_factor'],1.)

    def test_25_guard_vertex_proxy_not_device_nodes(self):
        self.assertEqual(guard.mesh_vertices('Optimizing elements...done. (103498 vertices)\n'),103498)
        for bad in ('Number of grid points is 103112.\n','Optimizing elements...done. (0 vertices)\n',
                    'Optimizing elements...done. (1 vertices)\nOptimizing elements...done. (2 vertices)\n'):
            with self.assertRaises(ValueError): guard.mesh_vertices(bad)

    def test_26_guard_fail_closed_for_space_memory(self):
        p=b.contract()['resource_guard']; gib=1024**3
        good=guard.estimate(100000,p,100*gib,8*gib)
        self.assertTrue(good['passed']);self.assertIsNone(good['sdevice_grid_points'])
        self.assertIsNone(good['peak_memory_estimate_bytes'])
        self.assertFalse(guard.estimate(100000,p,8*gib,8*gib)['passed'])
        self.assertFalse(guard.estimate(100000,p,100*gib,3*gib)['passed'])
        self.assertFalse(guard.estimate(500000,p,28*gib,8*gib)['passed'])

    def test_27_same_sde_guard_precedes_device(self):
        files=b.expected_files('A0','v4-source-interface-3d-r1-a0-b1-main')
        geometry=files['geometry.scm'].decode();project=json.loads(files['project.json'])
        self.assertLess(geometry.index('sde:build-mesh'),geometry.index('system:command'))
        self.assertIn('(sde:error "Mesh resource guard blocked SDevice',geometry)
        self.assertEqual(project['steps'][0]['tool'],'sde')
        self.assertIn('mesh-resource-passed.json',project['steps'][0]['outputs'])
        self.assertEqual(project['steps'][1]['tool'],'sdevice')

    def test_28_guard_memory_record(self):
        self.assertEqual(guard.available_memory('MemAvailable: 123456 kB\n'),123456*1024)
        with self.assertRaises(ValueError):guard.available_memory('MemFree: 123456 kB\n')


if __name__=='__main__':
    unittest.main(verbosity=2)
