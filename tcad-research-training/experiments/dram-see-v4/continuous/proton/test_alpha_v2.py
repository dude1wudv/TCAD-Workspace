"""New v2 energy/coordinate/domain behavior only; no native dispatch or old suite."""
import csv
import importlib.util
import io
import json
import math
from pathlib import Path
import unittest
from copy import deepcopy
from datetime import datetime,timezone

HERE=Path(__file__).resolve().parent
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    exec(compile(Path(path).read_bytes(),str(path),'exec'),module.__dict__);return module
F=load(HERE/'source_features_v2.py','_test_alpha_v2_features');A,M,R=F.A,F.M,F.R
G=load(HERE.parent/'device/geometry.py','_test_alpha_v2_geometry')
ORIGINAL=F.ROOT/'local_runtime/dram-see-v4/continuous/device/source-feature-inputs-alpha-main-20261017T062254Z'
BASE=json.loads((ORIGINAL/'model.proposed.json').read_bytes())
GEOMETRY=json.loads((ORIGINAL/'geometry-contract.json').read_bytes())


class AlphaV2Tests(unittest.TestCase):
    def test_01_new_energies_against_original_independent_rk4(self):
        stopping=A.Stopping();source=F.ROOT/'experiments/dram-see-v4/course-plan-r13/evidence/alpha-csda-comparison.csv'
        rows=list(csv.DictReader(io.StringIO(source.read_text())))
        for original in rows:
            energy=float(original['energy_at_Si_surface_MeV']);length=float(original['length_um'])
            actual=stopping.integrate(energy,length)
            for key in ('exit_energy_MeV','electronic_deposition_MeV','nuclear_deposition_MeV'):
                self.assertAlmostEqual(actual[key],float(original[key]),delta=1e-11)
            self.assertAlmostEqual(actual['electronic_line_charge_fC'],float(original['untruncated_line_charge_fC']),delta=5e-10)
            self.assertLess(abs(actual['energy_balance_residual_MeV']),1e-11)
        # Exact-bin-crossing behavior: 3MeV at 30deg crosses no fabricated knots;
        # a longer mathematical ray crosses 2.75MeV with explicit segments.
        crossing=stopping.integrate(3.,2.)
        self.assertGreater(len(crossing['energy_intervals']),1)
        self.assertAlmostEqual(sum(v['length_um'] for v in crossing['energy_intervals']),2.,delta=1e-14)
        with self.assertRaisesRegex(ValueError,'range'):stopping.integrate(0.,1.)
        qs=[stopping.integrate(energy,1.)['electronic_line_charge_fC'] for energy in (3,5,7)]
        self.assertGreater(qs[0],qs[1]);self.assertGreater(qs[1],qs[2])

    def test_02_geometry_families_and_ray_transform(self):
        for gate in (70,80,90):
            for sn in (82,87,92):
                model=deepcopy(BASE);model['geometry']['gate_top_depth_nm']=gate;model['doping']['sn_junction_depth_nm']=sn
                geometry=G.describe_geometry(model,3)
                for angle in (0,30):
                    path=A.validate_inputs(model,geometry,A.make_request(3,angle),R)
                    self.assertAlmostEqual(path['length_um'],1/math.cos(math.radians(angle)),delta=1e-14)
                    self.assertAlmostEqual(path['exit_um'][2],1.,delta=1e-14)
                    self.assertAlmostEqual(sum(a*b for a,b in zip(path['direction'],path['transverse_u'])),0.,delta=1e-14)
                    self.assertEqual(path['material_proof_is_native_measurement'],False)
        mismatch=deepcopy(GEOMETRY);mismatch['doping']['a_sn_um']*=1.01
        with self.assertRaisesRegex(ValueError,'SN-junction'):A.validate_inputs(BASE,mismatch,A.make_request(5,0),R)
        miss=A.make_request(5,0);miss['position_um']=[0.,0.,0.]
        with self.assertRaises(ValueError):A.validate_inputs(BASE,GEOMETRY,miss,R)
        with self.assertRaisesRegex(ValueError,'misses'):A.ray_box([2,0,0],[0,0,1],[-1,-.25,0,1,.25,1])

    def test_03_transverse_only_rotated_raw_moments(self):
        length=.2;density=1.;angle=math.pi/6;direction=[-math.sin(angle),0.,math.cos(angle)]
        rows=[dict(path_um=s,electronic_pC_um=density/1000) for s in (0.,length)]
        result=M.ObliqueIntegral(rows,GEOMETRY,[-.2,0.,.4],direction,.05,R,1e-12,1e-10).integrate()
        expected=[density*length]+[density*d*length**2/2 for d in direction]
        for i,j in ((0,0),(0,1),(0,2),(1,1),(1,2),(2,2)):
            expected.append(density*(direction[i]*direction[j]*length**3/3+
                                      (int(i==j)-direction[i]*direction[j])*.05**2*length/2))
        for actual,want in zip(result['finite_si'],expected):self.assertAlmostEqual(actual,want,delta=2e-11)
        # Axial second moment must not acquire the isotropic longitudinal w²/2.
        xx,xy,xz,yy,yz,zz=result['finite_si'][4:]
        axial=direction[0]**2*xx+2*direction[0]*direction[2]*xz+direction[2]**2*zz
        self.assertAlmostEqual(axial,density*length**3/3,delta=2e-11)

    def test_04_oblique_finite_box_independent_track_frame(self):
        request=A.make_request(3,30);path=A.validate_inputs(BASE,GEOMETRY,request,R)
        rows,ledger=A.profile(A.Stopping(),3,path['length_um'])
        actual=M.source_moments(rows,GEOMETRY,request,path,R,clock=None,abs_tol=1e-12,rel_tol=1e-10)
        sn=-path['direction'][0];cs=path['direction'][2];x0=request['position_um'][0];w=request['width_um']
        fy=.5*R.erf_delta(-.25/w,.25/w)
        def line(s):
            lo=max((-1-x0+sn*s)/cs,-cs*s/sn)
            hi=min((1-x0+sn*s)/cs,(1-cs*s)/sn)
            return [A.line_density(s,rows)*fy*.5*R.erf_delta(lo/w,hi/w)]
        track=sum(R.integrate_vector(line,a['path_um'],b['path_um'],1e-12/len(rows),1e-10)[0]
                  for a,b in zip(rows,rows[1:]))
        self.assertAlmostEqual(actual['enclosing_box'][0],track,delta=2e-9)
        self.assertGreater(actual['outer_box_loss_fC'],0.);self.assertGreater(actual['non_silicon_loss_fC'],0.)
        self.assertLess(actual['finite_si'][0],ledger['tabulated_line_charge_fC'])
        self.assertLess(actual['finite_si'][1],0.);self.assertEqual(actual['finite_si'][2],0.)
        with self.assertRaisesRegex(ValueError,'clock'):M.source_moments(rows,GEOMETRY,request,path,R,clock={'accepted':[]})

    def test_05_s2_normal_origin_compatibility(self):
        old=json.loads((F.RUNTIME/'source-features-s2-alpha-main-r1/source-features.json').read_bytes())
        request=A.make_request(5,0);path=A.validate_inputs(BASE,GEOMETRY,request,R)
        rows,_=A.profile(A.Stopping(),5,path['length_um'])
        actual=M.source_moments(rows,GEOMETRY,request,path,R,clock=None)['raw_feature_moments']
        for key,value in zip(F.FEATURES[1:],actual):self.assertAlmostEqual(value,old['source_features'][key],delta=3e-9)
        self.assertEqual(request['position_um'],old['r0_um']);self.assertEqual(request['epoch_s'],old['epoch_s'])
        contract=json.loads(F.contract_bytes());self.assertEqual(contract['feature_order'],old['feature_contract']['feature_order'])
        self.assertEqual(contract['units'],old['feature_contract']['units'])

    def test_06_new_package_recompute_and_input_boundaries(self):
        output=F.RUNTIME/('alpha-v2-new-test-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        packet=F.build_alpha(ORIGINAL/'model.proposed.json',ORIGINAL/'geometry-contract.json',5,30,output)
        self.assertEqual(F.verify(output/'source-features.json',input_files={'heavyion.physics.inc':(output/'heavyion.physics.inc').read_bytes()}),packet)
        self.assertFalse(packet['native_source_qualified']);self.assertFalse(packet['data_design']['data_design_registered'])
        self.assertEqual(packet['source_conditions']['angle_deg'],30)
        with self.assertRaisesRegex(ValueError,'already exists'):F.build_alpha(ORIGINAL/'model.proposed.json',ORIGINAL/'geometry-contract.json',5,30,output)
        with self.assertRaisesRegex(ValueError,'clock'):F.alpha_packet(output,clock={})
        with self.assertRaisesRegex(ValueError,'subset'):F.verify(output/'source-features.json',input_files={'source.par':b'changed'})
        print('V2_INPUT_ONLY_TEST_PACKAGE='+str(output),flush=True)

    def test_07_normal_box_tiny_tail_is_analytic_not_clamped(self):
        request=A.make_request(5,0);path=A.validate_inputs(BASE,GEOMETRY,request,R)
        rows,ledger=A.profile(A.Stopping(),5,path['length_um'])
        result=M.source_moments(rows,GEOMETRY,request,path,R,clock=None)
        xmass=.5*R.erf_delta((-1+.052)/.05,(1+.052)/.05)
        ymass=.5*R.erf_delta(-.25/.05,.25/.05)
        expected=ledger['tabulated_line_charge_fC']*xmass*ymass
        self.assertAlmostEqual(result['enclosing_box'][0],expected,delta=3e-15)
        self.assertGreater(result['outer_box_loss_fC'],0)
        self.assertLess(result['outer_box_loss_fC'],2e-11)
        self.assertIsNotNone(result['normal_box_diagnostic'])
        self.assertNotEqual(result['normal_box_diagnostic']['adaptive_minus_analytic'][0],0)


if __name__=='__main__':unittest.main(verbosity=2)
