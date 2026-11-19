"""Only new projection arithmetic/boundaries plus one fixed historic raw replay."""
import importlib.util
import json
import math
from pathlib import Path
import unittest
import shutil
from copy import deepcopy
from datetime import datetime,timezone

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('_test_r14_projection',HERE/'project.py')
P=importlib.util.module_from_spec(spec);exec(compile((HERE/'project.py').read_bytes(),str(HERE/'project.py'),'exec'),P.__dict__)
K,A=P.K,P.A
EPOCH=15e-9
BOX=dict(kind='arithmetic_rectangle',bounds_xz_um=[-.5,0.,.5,1.],outer_trench=None)


def term(**changes):
    value=dict(uid='ARITHMETIC_FIXTURE_NOT_NATIVE',p0_um=[.1,0.,.5],p1_um=[.1,0.,.5],
        t0_s=EPOCH,t1_s=EPOCH,charge_fC=1.,width_um=.03,sigma_s=2e-12)
    value.update(changes);return value


class ProjectionTests(unittest.TestCase):
    def test_01_point_normalization_width_once_and_G3_y_integral(self):
        source=term();mask=K.ResponseMask(BOX);window=[EPOCH-8e-12,EPOCH+8e-12]
        result=K.step_integrals(source,mask,window,[0,0,0],EPOCH)
        fraction=math.erf(.01/.03);time_fraction=math.erf(4/math.sqrt(2))
        self.assertAlmostEqual(result['accepted_fC'],fraction*time_fraction,delta=1e-13)
        x,z,time=.11,.49,EPOCH+.5e-12
        # Independent point-G3 density integrated numerically in physical y.
        def g3(y):
            spatial=math.exp(-((x-.1)**2+y*y+(z-.5)**2)/.03**2)/(math.pi**1.5*.03**3)
            temporal=math.exp(-((time-EPOCH)/2e-12)**2/2)/(math.sqrt(2*math.pi)*2e-12)
            return 1e-15/K.E_C*1e12*spatial*temporal
        n=200;dy=.02/n
        integral=dy/3*(g3(-.01)+g3(.01)+sum((4 if i%2 else 2)*g3(-.01+i*dy) for i in range(1,n)))
        projected=K.generation2d([source],mask,x,z,time,window)
        self.assertAlmostEqual(projected/(integral/.02),1.,delta=1e-11)
        self.assertAlmostEqual(sum(result[k] for k in ('outside_y_strip_fC','inside_strip_outside_xz_box_fC',
            'inside_strip_box_non_silicon_fC','response_silicon_outside_time_window_fC','accepted_fC')),1.,delta=1e-13)
        self.assertTrue(result['zero_length_preserved'])

    def test_02_correlated_segment_split_and_late_retention(self):
        source=term(p0_um=[-.1,-.04,.4],p1_um=[.1,.04,.6],t0_s=EPOCH-10e-12,t1_s=EPOCH+10e-12)
        left=deepcopy(source);right=deepcopy(source)
        center=[(a+b)/2 for a,b in zip(source['p0_um'],source['p1_um'])]
        left.update(uid='left',p1_um=center,t1_s=EPOCH,charge_fC=.5)
        right.update(uid='right',p0_um=center,t0_s=EPOCH,charge_fC=.5)
        window=[EPOCH-2e-12,EPOCH+3e-12]
        whole=K.integrate([source],BOX,window,[0,0,0],EPOCH)
        split=K.integrate([left,right],BOX,window,[0,0,0],EPOCH)
        for key,value in whole['totals'].items():self.assertAlmostEqual(value,split['totals'][key],delta=2e-10)
        self.assertEqual(whole['raw_deposition_outside_window_uids'],[source['uid']])
        self.assertGreater(whole['totals']['response_silicon_outside_time_window_fC'],0)
        self.assertGreater(whole['totals']['outside_y_strip_fC'],0)
        mask=K.ResponseMask(BOX)
        for x,z,t in [(-.02,.48,EPOCH-1e-12),(.03,.53,EPOCH+2e-12)]:
            a=K.generation2d([source],mask,x,z,t,window);b=K.generation2d([left,right],mask,x,z,t,window)
            self.assertAlmostEqual(a/b,1.,delta=1e-8)
            # Independent closed-form 4D segment Gaussian, then numeric y
            # integration; a midpoint-time approximation does not satisfy this.
            def g3(y):
                offset=[(v-c)/.03 for v,c in zip((x,y,z),source['p0_um'])]+[(t-source['t0_s'])/(math.sqrt(2)*2e-12)]
                delta=[(b-a)/.03 for a,b in zip(source['p0_um'],source['p1_um'])]+[(source['t1_s']-source['t0_s'])/(math.sqrt(2)*2e-12)]
                aa=sum(d*d for d in delta);bb=sum(o*d for o,d in zip(offset,delta));cc=sum(o*o for o in offset)
                root=math.sqrt(aa)
                integral=math.exp(-cc+bb*bb/aa)*math.sqrt(math.pi)/(2*root)*K.R.erf_delta(-bb/root,root-bb/root)
                return 1e-15/K.E_C*1e12/(math.pi**1.5*.03**3*math.sqrt(2*math.pi)*2e-12)*integral
            n=200;dy=.02/n
            independent=dy/3*(g3(-.01)+g3(.01)+sum((4 if i%2 else 2)*g3(-.01+i*dy) for i in range(1,n)))/.02
            self.assertAlmostEqual(a/independent,1.,delta=1e-8)

    def test_03_actual_BCAT_input_mask_against_independent_3D_strip(self):
        root=P.ROOT
        d2=root/'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/device-implementation/candidates/20261019T103816Z-v4-2d-a0-main-b0-input-r1'
        g3=root/'local_runtime/dram-see-v4/continuous/proton/s2-transport-p100-a0-seed61017041-r1/geometry-contract.json'
        response,binding=P.bcat_response(d2/'model.proposed.json',d2/'geometry-contract.json',d2/'dimensional-contract.json',A.read_json(g3))
        self.assertEqual(binding['effective_width_cm'],2e-6)
        source=term(p0_um=[0.,.005,.145],p1_um=[-.03,.02,.16],t0_s=EPOCH,t1_s=EPOCH+3e-12)
        window=[EPOCH-10e-12,EPOCH+10e-12];mask=K.ResponseMask(response)
        projected=K.step_integrals(source,mask,window,[-.052,0,0],EPOCH)
        geometry=A.read_json(g3);original_mask=K.R.SiliconMask(geometry)
        source_row=source['p0_um']+source['p1_um']+[source['t0_s'],source['t1_s'],source['charge_fC'],.03,2e-12]
        direct=K.R.step_integral(source_row,original_mask,[-1.,-.01,0.,1.,.01,1.],window)
        self.assertAlmostEqual(projected['accepted_fC'],direct[0],delta=2e-9)
        self.assertAlmostEqual(projected['accepted_Mx_absolute_fC_um'],direct[1],delta=2e-9)
        self.assertAlmostEqual(projected['accepted_Mz_absolute_fC_um'],direct[3],delta=2e-9)
        self.assertGreater(projected['inside_strip_box_non_silicon_fC'],0)
        self.assertEqual(K.generation2d([source],mask,0.,.1,EPOCH,window),0)

    def test_04_boundaries_zero_and_malformed_do_not_gain_charge(self):
        window=[EPOCH-1e-12,EPOCH+1e-12];mask=K.ResponseMask(BOX)
        inside=K.step_integrals(term(),mask,window,[0,0,0],EPOCH)
        edge=K.step_integrals(term(p0_um=[.1,.01,.5],p1_um=[.1,.01,.5]),mask,window,[0,0,0],EPOCH)
        outside=K.step_integrals(term(p0_um=[.1,.08,.5],p1_um=[.1,.08,.5]),mask,window,[0,0,0],EPOCH)
        self.assertGreater(inside['accepted_fC'],edge['accepted_fC']);self.assertGreater(edge['accepted_fC'],outside['accepted_fC'])
        self.assertGreater(outside['accepted_fC'],0)  # no hard rejection of Gaussian support crossing the strip
        zero=K.integrate([],BOX,window,[0,0,0],EPOCH)
        self.assertEqual(zero['totals']['accepted_fC'],0);self.assertIsNone(zero['centroids']['physical_x_um'])
        self.assertEqual(K.generation2d([],mask,.1,.5,EPOCH,window),0)
        with self.assertRaises(ValueError):K.step_integrals(term(charge_fC=-1),mask,window,[0,0,0],EPOCH)
        with self.assertRaises(ValueError):K.step_integrals(term(width_um=.02),mask,window,[0,0,0],EPOCH)
        with self.assertRaises(ValueError):K.step_integrals(term(),mask,[EPOCH,EPOCH],[0,0,0],EPOCH)

    def test_05_fixed_original_event_replay_full_provenance_and_no_overwrite(self):
        output=P.RUNTIME/('historical-event0-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        result=P.build_historical(output,[EPOCH-16e-12,EPOCH+16e-12],EPOCH)
        verified=P.verify(output)
        self.assertEqual(verified['ledger'],result['ledger'])
        source=A.read_json(output/'projection-source.json')
        self.assertEqual(source['context']['scope'],'HISTORICAL_PLANAR_KERNEL_REPLAY_NOT_R14_SOURCE')
        self.assertEqual(len(source['step_records']),int(source['original_event']['step_count']))
        self.assertEqual(len(source['context']['original_request_denominator']),1000)
        self.assertEqual(source['axis_map_physical_from_original_indices'],[0,2,1])
        for record in source['step_records']:
            self.assertEqual(record['physical_y_endpoints_um'][0],float(record['original_native_step']['pre_z_um']))
        self.assertFalse(result['contract']['native_source_qualified'])
        with self.assertRaisesRegex(ValueError,'new and inside'):P.build_historical(output,[EPOCH-16e-12,EPOCH+16e-12],EPOCH)
        print('ACTUAL_HISTORICAL_INPUT_ONLY_PROJECTION='+str(output),flush=True)

    def test_06_manifest_cannot_claim_native_and_unknown_files_reject(self):
        prior=P.RUNTIME/'historical-event0-20261019T105022167423Z'
        root=P.RUNTIME/('manifest-tamper-FIXTURE-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));root.mkdir()
        for path in prior.iterdir():
            if path.is_file():shutil.copyfile(path,root/path.name)
        manifest=A.read_json(root/'input-output-manifest.json');manifest['native_source_qualified']=True
        (root/'input-output-manifest.json').write_bytes(A.encoded(manifest))
        with self.assertRaisesRegex(ValueError,'manifest'):P.verify(root)
        manifest['native_source_qualified']=False;manifest['files']['unexpected.bin']=dict(sha256='0'*64,bytes=0)
        (root/'input-output-manifest.json').write_bytes(A.encoded(manifest))
        with self.assertRaisesRegex(ValueError,'manifest'):P.verify(root)
        (root/'ARITHMETIC_TAMPER_FIXTURE_NOT_NATIVE.json').write_bytes(A.encoded(dict(not_a_native_result=True,purpose='Manifest admission rejection')))


if __name__=='__main__':unittest.main(verbosity=2)
