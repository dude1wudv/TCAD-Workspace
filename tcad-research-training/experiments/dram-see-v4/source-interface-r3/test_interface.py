"""Offline r3 oracle and measurement-chain negative tests; no solver."""
import copy
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent


def module(path,name):
    import importlib.util
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(),str(path),'exec'),m.__dict__)
    return m


b=module(HERE/'build_interface.py','test_r3_builder')
o=module(HERE/'oracle.py','test_r3_oracle')
a=module(HERE/'audit_interface.py','test_r3_auditor')


def fixture():
    spec=b.source_spec();proof=b.offline_proof(spec)
    times=[0.]+[.95e-9+i*5e-13 for i in range(201)]+[4e-9]
    rows=[];prev=0.
    for t in times:
        # Independent CDF expression in a symmetric time region for test fixtures.
        average=(math.erf((t-1e-9)/(math.sqrt(2)*2e-12))-math.erf((prev-1e-9)/(math.sqrt(2)*2e-12)))/(2*(t-prev)) if t>prev else 0.
        row={'time':t}
        for role in ('IntegrSemiconductor','IntegrG_Plain','IntegrG_2DTotal'):
            row[role+' HeavyIonGeneration']=average/a.CONVERSION
        for roi,p in proof['rois'].items():
            row['IntegrG_'+roi+' HeavyIonGeneration']=p['q_fC']*average/a.CONVERSION
        row['IntegrG_Total X_HeavyIonGeneration']=.425
        row['IntegrG_Total Y_HeavyIonGeneration']=.6
        for roi in ['Plain','2DTotal']+list(a.C['rois_um']):
            rect=a.C['device']['silicon_bounds_um'] if roi in ('Plain','2DTotal') else a.C['rois_um'][roi]
            row['IntegrArea_'+roi+' LatticeTemperature']=300*(rect[2]-rect[0])*(rect[3]-rect[1])
        rows.append(row);prev=t
    return {'device':rows,'circuit':[{'time':r['time']} for r in rows]}, {'pulse_max_step_s':5e-13,'temperature_K':300.},spec,proof


class R3Tests(unittest.TestCase):
    def test_document_sigma_and_peak(self):
        sigma=2e-12;t0=1e-9
        peak=o.instantaneous(t0,t0,sigma)
        self.assertAlmostEqual(peak,1/(math.sqrt(2*math.pi)*sigma),delta=1e-4)
        self.assertAlmostEqual(o.instantaneous(t0+sigma,t0,sigma)/peak,math.exp(-.5),places=12)
        self.assertAlmostEqual(o.instantaneous(t0+5e-12,t0,sigma)/peak,.0439369336234074,places=12)
        self.assertGreater(abs(o.instantaneous(t0+sigma,t0,sigma)/peak-math.exp(-.25)),.1)

    def test_normalization_truncation_and_nonuniform_intervals(self):
        self.assertAlmostEqual(o.mass(0,1.,0.,.01),1.,places=14)
        self.assertAlmostEqual(o.mass(-1.,1.,0.,.01),1.,places=14)
        times=[0.,.993e-9,.995e-9,.998e-9,1e-9,1.001e-9,1.006e-9,1.02e-9,4e-9]
        rows=[{'time':times[0],'G':0.}]+[{'time':v,'G':o.step_average(u,v,1e-9,2e-12)} for u,v in zip(times,times[1:])]
        self.assertAlmostEqual(o.rectangular(rows,'G'),1.,places=13)
        trapezoid=sum((z['time']-u['time'])*(u['G']+z['G'])/2 for u,z in zip(rows,rows[1:]))
        self.assertGreater(abs(trapezoid-1),.01)  # Distinguishes a changed observer from data filling.
        with self.assertRaises(ValueError):o.step_average(1.,1.,0.,1.)

    def test_tail_erfc_and_independent_midpoint_quadrature(self):
        lo,hi=1.0145e-9,1.015e-9;n=10000
        dt=(hi-lo)/n
        numerical=sum(math.exp(-.5*((lo+(i+.5)*dt-1e-9)/2e-12)**2)/(math.sqrt(2*math.pi)*2e-12)*dt for i in range(n))
        self.assertAlmostEqual(o.mass(lo,hi,1e-9,2e-12)/numerical,1.,places=8)

    def test_native_five_tdr_ratios_are_step_averages_not_instant_samples(self):
        values=[4.73006836894e25,1.23728339439e27,7.53955856169e25,9.15595804656e21,2.21213721904e15]
        starts=[9.94758283899995e-10,9.99499999999999e-10,1.0045e-9,1.0095e-9,1.0145e-9]
        ends=[9.95e-10,9.99999999999999e-10,1.005e-9,1.01e-9,1.015e-9]
        rates=[o.step_average(x,y,1e-9,2e-12) for x,y in zip(starts,ends)]
        for v,r in zip(values,rates):self.assertAlmostEqual((r/rates[1])/(v/values[1]),1.,places=10)

    def test_synthetic_observer_positive_and_realistic_center_failure(self):
        curves,p,spec,proof=fixture();out={}
        self.assertTrue(a.check_source(curves,p,spec,proof,out))
        self.assertAlmostEqual(out['radiation']['generated_fC'],1.,places=12)
        # Native TDR center discrepancy must not be hidden by total normalization.
        for row in curves['device']:
            row['IntegrG_Center HeavyIonGeneration']=row['IntegrG_Total HeavyIonGeneration']*.783205
        out={}
        with self.assertRaisesRegex(ValueError,'ROI fraction differs: Center'):
            a.check_source(curves,p,spec,proof,out)
        self.assertGreater(out['radiation']['roi_fraction_checks']['Center']['abs_error'],.05)

    def test_diagnostic_path_never_replaces_failing_acceptance_roi(self):
        curves,p,spec,proof=fixture()
        for row in curves['device']:
            for roi in a.C['rois_um']:row['IntegrG_'+roi+' HeavyIonGeneration']=0.
        out={}
        with self.assertRaises(ValueError):a.check_source(curves,p,spec,proof,out)
        self.assertEqual(out['radiation']['generated_fC'],0.)
        self.assertAlmostEqual(out['radiation']['legacy_generated_fC'],1.,places=12)
        self.assertIn('3-coordinate native source charge exceeds frozen5% gate',out['source_gate_failures'])

    def test_missing_legacy_or_temperature_is_not_theoretical_filled(self):
        for key in ('IntegrSemiconductor HeavyIonGeneration','IntegrArea_Total LatticeTemperature'):
            curves,p,spec,proof=fixture()
            for row in curves['device']:del row[key]
            with self.assertRaises(ValueError):a.check_source(curves,p,spec,proof,{})

    def test_reuse_does_not_accept_failed_r2_A1_or_altered_match(self):
        out={}
        with patch.object(a.r2,'load_run',return_value={'summary':{'passed':False}}):
            with self.assertRaisesRegex(ValueError,'control audit failed'):a.reuse_control({},'not-a-run',out)
        bad={'summary':{'passed':True},'parameters':{'schema':'dram-see-v4-source-interface-r2','case_id':'A1','stored_bit':1,'variant':'base'}}
        with patch.object(a.r2,'load_run',return_value=bad):
            with self.assertRaisesRegex(ValueError,'Only a genuinely'):a.reuse_control({'parameters':{}},'not-a-run',{})
        bad['parameters'].update(case_id='A0',matching_contract_sha256='control',matching_contract={})
        with patch.object(a.r2,'load_run',return_value=bad):
            with self.assertRaisesRegex(ValueError,'matching'):a.reuse_control({'parameters':{'matching_contract_sha256':'different'}},'not-a-run',{})

    def test_candidate_changes_only_currentplot_and_preserves_global_budget(self):
        reference=b.ROOT/'local_runtime/dram-see-v4/source-interface-r2/inputs/v4-source-interface-r2-a1-b1-base'
        root=b.OUTPUT_ROOT/'audit-dev';root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root,prefix='builder-') as temp:
            project=Path(temp)/'v4-source-interface-r3-a1-b1-base-test'
            report=b.build(project,reference)
            self.assertEqual(report['global_budget_limit'],19);self.assertFalse(report['new_budget_created'])
            old=(reference/'device.cmd').read_text();new=(project/'device.cmd').read_text()
            self.assertEqual(old[:old.index('CurrentPlot {')],new[:new.index('CurrentPlot {')])
            self.assertEqual(old[old.index('\nMath {'):],new[new.index('\nMath {'):])
            self.assertIn('  Integrate(Semiconductor)',new)
            self.assertIn('\n Temperature(',new);self.assertNotIn('\n LatticeTemperature(',new)
            proof=b.read_json(project/'offline-source-check.json')
            self.assertNotIn('time_window_outside_fraction_upper_bound',proof)
            self.assertEqual(proof['temporal_mass_0_to_4ns_by_source'],{'Ion1':1.})
            self.assertEqual(new.count(' -0.5)'),18);self.assertEqual(new.count(' 0.5)]'),18)
            self.assertEqual((reference/'geometry.scm').read_bytes(),(project/'geometry.scm').read_bytes())
            with self.assertRaises(ValueError):b.build(project,reference)


if __name__=='__main__':unittest.main(verbosity=2)
