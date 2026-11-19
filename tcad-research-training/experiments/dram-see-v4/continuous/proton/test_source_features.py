"""New raw-moment mathematics / pre-TCAD dependency boundaries only.

Explicit synthetic source rows are not native transport or training samples.
The alpha table is the original ASTAR reference LUT, not a simulated response.
"""
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import source_features as F


class SourceFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiled=F.ROOT/'local_runtime/dram-see-v4/transport-probe/operations/cgoal-bcat-build-20261017t043911z/collected'
        cls.geometry=F.read_json(cls.compiled/'geometry-contract.json')
        cls.model=F.read_json(cls.compiled/'model-input.json')
        cls.A=F.alpha_reference();cls.profile=cls.A.load_profile()
        cls.origin=[-.052,0.,0.];cls.epoch=15e-9

    def test_gaussian_second_moment_halfspace_and_shift(self):
        width=.03;origin=-.052
        result=F.M.gaussian_moments(0.,20*width,0.,width,0.,F.R)
        self.assertAlmostEqual(result[0],.5,places=14)
        self.assertAlmostEqual(result[1],width/(2*math.sqrt(math.pi)),places=14)
        self.assertAlmostEqual(result[2],width**2/4,places=14)
        shifted=F.M.gaussian_moments(-20*width,20*width,0.,width,origin,F.R)
        self.assertAlmostEqual(shifted[1],-origin,places=14)
        self.assertAlmostEqual(shifted[2],origin**2+width**2/2,places=14)

    def test_proton_q_first_compatibility_boundary_point_and_late_rows(self):
        rows=[[-.052,0.,0.,-.052,0.,0.,self.epoch,self.epoch,.2,.03,2e-12],
              [-.07,0.,.13,.04,.02,.24,25e-9,25.004e-9,.4,.03,2e-12]]
        values=F.M.proton_moments(rows,self.geometry,self.origin,self.epoch,F.R,clock=None)
        mask=F.R.SiliconMask(self.geometry)
        previous=F.R.add_vectors([F.R.step_integral(row,mask,mask.domain,(-math.inf,math.inf)) for row in rows],5)
        self.assertAlmostEqual(values[0],previous[0],delta=2e-10)
        for i in range(3):self.assertAlmostEqual(values[i+1],previous[i+1]-self.origin[i]*previous[0],delta=2e-10)
        self.assertGreater(values[10],1000.)
        self.assertGreater(values[11],1e6)

    def test_proton_uniform_segment_second_cross_and_time_moments(self):
        q=.2;p0=[-.4,0.,.45];p1=[.4,0.,.55];dt=10000.
        row=p0+p1+[self.epoch,self.epoch+dt*1e-12,q,.03,2e-12]
        values=F.M.proton_moments([row],self.geometry,self.origin,self.epoch,F.R,clock=None)
        center=[(a+b)/2-o for a,b,o in zip(p0,p1,self.origin)];delta=[b-a for a,b in zip(p0,p1)]
        self.assertAlmostEqual(values[0],q,delta=2e-10)
        for value,(i,j) in zip(values[4:10],[(0,0),(0,1),(0,2),(1,1),(1,2),(2,2)]):
            expected=q*(center[i]*center[j]+delta[i]*delta[j]/12+(.03**2/2 if i==j else 0.))
            self.assertAlmostEqual(value,expected,delta=3e-10)
        self.assertAlmostEqual(values[10],q*dt/2,delta=2e-7)
        self.assertAlmostEqual(values[11],q*(dt**2/3+4),delta=2e-3)

    def test_alpha_original_q_first_and_no_longitudinal_blur(self):
        values=F.M.alpha_moments(self.profile,self.geometry,self.origin,self.epoch,F.R,self.A,clock=None)
        previous=self.A.spatial_expected(self.profile)
        self.assertAlmostEqual(values[0],previous['q_fC'],delta=2e-9)
        for i in range(3):self.assertAlmostEqual(values[i+1],previous['moments_fC_um'][i]-self.origin[i]*previous['q_fC'],delta=2e-9)
        self.assertEqual(values[10],0.)
        self.assertAlmostEqual(values[11],values[0]*.2**2,places=14)
        # An independent midpoint integral of the old alpha slice and LUT checks
        # that z^2 contains no added longitudinal Gaussian variance.
        n=40000;dz=1/n
        expected=math.fsum(self.A.line_charge_density((i+.5)*dz,self.profile)*
                          self.A._slice((i+.5)*dz,self.A.DOMAIN)[0]*((i+.5)*dz)**2*dz for i in range(n))
        self.assertAlmostEqual(values[9],expected,delta=2e-8)
        half=F.M.alpha_moments(self.profile,self.geometry,self.origin,self.epoch,F.R,self.A,amplitude=.5)
        for a,b in zip(half,values):self.assertAlmostEqual(2*a,b,delta=2e-9)

    def test_zero_and_clock_missing_semantics(self):
        zero=F.M.proton_moments([],self.geometry,self.origin,self.epoch,F.R,clock=None)
        self.assertEqual(zero,[0.]*12)
        self.assertIsNone(F.interpretation(zero,self.origin)['centroid_um'])
        self.assertIsNone(F.interpretation(zero,self.origin)['time_variance_ps2'])
        with self.assertRaisesRegex(ValueError,'BE clock'):
            F.M.proton_moments([],self.geometry,self.origin,self.epoch,F.R,clock={})
        with self.assertRaisesRegex(ValueError,'BE clock'):
            F.M.alpha_moments(self.profile,self.geometry,self.origin,self.epoch,F.R,self.A,clock={})
        with self.assertRaises(FileNotFoundError):F.alpha_packet(F.R.RUNTIME/'NO_SUCH_SOURCE_FEATURE_INPUT')

    def test_alpha_packet_read_allowlist_bit_sharing_and_tamper(self):
        with tempfile.TemporaryDirectory(prefix='UNIT_FIXTURE_NOT_NATIVE-source-features-',dir=F.R.RUNTIME) as tmp:
            folder=Path(tmp);src=folder/'source';src.mkdir()
            physical,parameters=self.A.render_source(self.profile,'Aalpha')
            inputs={'model.proposed.json':F.encoded(self.model),'geometry-contract.json':F.encoded(self.geometry),
                    'alpha-profile.csv':self.A.PROFILE.read_bytes(),'heavyion.physics.inc':physical.encode(),'source.par':parameters.encode()}
            for name,raw in inputs.items():(src/name).write_bytes(raw)
            output=folder/'source-features.json'
            with patch.dict(sys.modules,{'prepare':types.ModuleType('DEVICE_PREPARE_SENTINEL')}):
                before=sys.modules['prepare']
                packet=F.build_alpha(src,output)
                self.assertIs(sys.modules['prepare'],before)
            self.assertEqual(len(packet['source_features']),13)
            self.assertEqual(packet['source_conditions']['gate_top_depth_nm'],80)
            # Supplied current inputs may include either stored bit and unrelated
            # native-looking bytes. Only prescribed source filenames are read.
            for bit in (0,1):
                supplied=dict(inputs,**{'source-spec.json':F.encoded({'stored_bit':bit}),
                    'transient_des.log':b'NOT_A_REAL_NATIVE_LOG','HeavyIonGeneration.tdr':b'NOT_A_NATIVE_FIELD'})
                self.assertEqual(F.verify(output,input_files=supplied),packet)
            self.assertEqual(F.verify(output,input_files={'alpha-profile.csv':inputs['alpha-profile.csv']}),packet)
            wrong=dict(inputs);wrong['source.par']=b'changed kernel'
            with self.assertRaisesRegex(ValueError,'Current source input'):F.verify(output,input_files=wrong)
            changed=copy.deepcopy(packet);changed['source_features']['M_xx_fC_um2']+=1
            bad=folder/'tampered.json';bad.write_bytes(F.encoded(changed))
            with self.assertRaisesRegex(ValueError,'recomputation'):F.verify(bad)
            with self.assertRaises(FileExistsError):F.build_alpha(src,output)
            (src/'source.par').write_bytes(b'missing actual supported kernel')
            with self.assertRaisesRegex(ValueError,'source pair'):F.verify(output)

    def test_proton_dependency_namespace_restored(self):
        sentinels={name:types.ModuleType('DEVICE_'+name.upper()) for name in ('prepare','couple','source_reference')}
        with patch.dict(sys.modules,sentinels):
            with F.proton_modules() as (prepare,couple,bundle):
                self.assertIs(bundle.prepare,prepare);self.assertIs(couple.prepare,prepare)
                self.assertIs(bundle.REF,F.R)
                self.assertEqual(Path(prepare.__file__).resolve(),F.HERE/'prepare.py')
            for name,original in sentinels.items():self.assertIs(sys.modules[name],original)

    def test_alpha_zero_and_split_input_packets(self):
        with tempfile.TemporaryDirectory(prefix='UNIT_FIXTURE_NOT_NATIVE-feature-variants-',dir=F.R.RUNTIME) as tmp:
            packets={}
            for case in ('Aalpha','Z','split'):
                folder=Path(tmp)/case;folder.mkdir();prefix='' if case=='Aalpha' else case+'.'
                physical,parameters=self.A.render_source(self.profile,case)
                for name,raw in {'model.proposed.json':F.encoded(self.model),'geometry-contract.json':F.encoded(self.geometry),
                    'alpha-profile.csv':self.A.PROFILE.read_bytes(),prefix+'heavyion.physics.inc':physical.encode(),
                    prefix+'source.par':parameters.encode()}.items():(folder/name).write_bytes(raw)
                packets[case]=F.alpha_packet(folder)
            self.assertEqual(packets['Aalpha']['source_features'],packets['split']['source_features'])
            self.assertEqual(set(packets['Z']['source_features'].values()),{0.})
            self.assertEqual(packets['Z']['source_status'],'PRESCRIBED_STRUCTURAL_ZERO')
            self.assertIsNone(packets['Z']['interpretation']['covariance_um2'])


if __name__=='__main__':unittest.main()
