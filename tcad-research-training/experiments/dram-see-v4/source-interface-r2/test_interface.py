"""Offline negative tests. Generated fields below are explicitly synthetic fixtures."""
import copy
import io
import json
import math
from pathlib import Path
import tarfile
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


def module(path,name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name,path)
    result = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(),str(path),'exec'),result.__dict__)
    return result


b = module(HERE/'build_interface.py','r2_test_builder')
a = module(HERE/'audit_interface.py','r2_test_audit')


def fixture(case,step=5e-13):
    """Manufactured rows for parser/decision tests, never an engineering run."""
    spec = b.make_spec(case)
    proof = b.offline_check(spec)
    count = round((1.05e-9-.95e-9)/step)
    times = [0.] + [.95e-9+i*step for i in range(count+1)] + [4e-9]
    rows = []
    for t in times:
        row = {'time':t}
        for roi in a.C['rois_um']:
            rate,x,y = a.expected_profile(spec,proof,roi,t)
            row['IntegrG_'+roi+' HeavyIonGeneration'] = rate/a.CONVERSION
            if roi == 'Total' and spec['tracks']:
                row['IntegrG_Total X_HeavyIonGeneration'] = x if x is not None else 0.
                row['IntegrG_Total Y_HeavyIonGeneration'] = y if y is not None else 0.
        rows.append(row)
    return spec,proof,{'device':rows,'circuit':[{'time':r['time']} for r in rows]},{'pulse_max_step_s':step}


class InterfaceTests(unittest.TestCase):
    def test_frozen_sequence_and_variants(self):
        c = b.contract()
        self.assertEqual(len(c['run_sequence']),19)
        self.assertEqual(len(set(map(tuple,c['run_sequence']))),19)
        self.assertEqual(c['audit_tolerances']['refinement_charge_relative'],.02)
        self.assertEqual(c['audit_tolerances']['refinement_voltage_abs_V'],.001)
        self.assertEqual(c['audit_tolerances']['refinement_voltage_relative'],.05)
        for role in c['run_sequence']:
            b.check_role(*role)
        with self.assertRaises(ValueError):
            b.check_role('A6',0,'base')

    def test_all_offline_integrals_and_partition_ledger(self):
        for case in b.contract()['case_ids']:
            p = b.offline_check(b.make_spec(case))
            expected = 0. if case == 'A0' else .5 if case == 'A3' else 1.
            self.assertAlmostEqual(p['domain_charge_fC'],expected,places=8)
            self.assertAlmostEqual(p['outside_domain_fC'],.5 if case == 'A3' else 0.,places=8)
            for group in b.contract()['partitions']:
                self.assertAlmostEqual(sum(p['rois'][r]['q_fC'] for r in group),p['domain_charge_fC'],places=7)

    def test_tilt_rotation_independently(self):
        s = b.make_spec('A2')
        p = b.offline_check(s)
        self.assertAlmostEqual(p['rois']['Total']['centroid_x_um'],.425,places=10)
        self.assertAlmostEqual(p['rois']['Total']['centroid_y_um'],.6,places=10)
        self.assertGreater(p['rois']['UpperLeft']['q_fC'],10*p['rois']['LowerLeft']['q_fC'])
        tr = s['tracks'][0]
        x,y = tr['start_um'][:2]
        dx,dy = tr['direction'][:2]
        peak = b.generation(s,x+.3*dx,y+.3*dy,1e-9)
        off = b.generation(s,x+.3*dx-.03*dy,y+.3*dy+.03*dx,1e-9)
        self.assertAlmostEqual(off/peak,math.exp(-1),places=10)
        self.assertEqual(b.generation(s,x-.01*dx,y-.01*dy,1e-9),0.)

    def test_a3_half_charge_and_centroid_are_not_renormalized(self):
        p = b.offline_check(b.make_spec('A3'))
        self.assertEqual(p['source_total_fC'],1.)
        self.assertAlmostEqual(p['domain_charge_fC'],.5,places=12)
        self.assertAlmostEqual(p['rois']['Total']['centroid_x_um'],.03/math.sqrt(math.pi),places=12)

    def test_split_charge_and_pointwise_field_away_from_endpoints(self):
        single = b.make_spec('A1')
        for case in ('A8S2','A8S4'):
            split = b.make_spec(case)
            self.assertAlmostEqual(sum(t['q_fC'] for t in split['tracks']),1.)
            for x in (.4,.425,.44):
                for y in (.32,.49,.68,.87):
                    self.assertAlmostEqual(b.generation(single,x,y,1e-9)/b.generation(split,x,y,1e-9),1.,places=12)
            bad = copy.deepcopy(split)
            bad['tracks'][0]['let_pC_per_um'] *= 2
            with self.assertRaises(ValueError):
                b.validate_spec(bad,frozen=False)

    def test_order_is_only_input_order(self):
        s5,s7 = b.make_spec('A5'),b.make_spec('A7')
        self.assertEqual(s5['tracks'],list(reversed(s7['tracks'])))
        for x in (.325,.425,.525):
            self.assertEqual(b.generation(s5,x,.6,1e-9),b.generation(s7,x,.6,1e-9))

    def test_reject_undefined_3d_and_duplicate_energy_ownership(self):
        for mutate in (lambda s:s.update(dimension=3),lambda s:s.update(synthetic=False),
                       lambda s:s['tracks'][0]['start_um'].__setitem__(2,.1),
                       lambda s:s['tracks'][0]['direction'].__setitem__(2,.2),
                       lambda s:s['tracks'][1].update(source_step_ids=s['tracks'][0]['source_step_ids']),
                       lambda s:s['tracks'][0].update(time_s=float('nan'))):
            source = b.make_spec('A5'); mutate(source)
            with self.assertRaises(ValueError):
                b.validate_spec(source,frozen=False)

    def test_synthetic_spatial_temporal_fixture_passes(self):
        for case in ('A1','A2','A3','A5','A6','A8S4'):
            s,p,curves,params = fixture(case)
            result = {}
            self.assertTrue(a.audit_source(curves,params,s,p,result))
            self.assertAlmostEqual(result['radiation']['generated_fC'],p['domain_charge_fC'],places=8)

    def test_overlap_bug_is_rejected_despite_correct_total(self):
        source,proof,_,params = fixture('A5')
        _,_,wrong,_ = fixture('A1')
        with self.assertRaisesRegex(ValueError,'ROI fraction|waveform'):
            a.audit_source(wrong,params,source,proof,{})

    def test_ignored_delay_is_rejected(self):
        source,proof,_,params = fixture('A6')
        _,_,wrong,_ = fixture('A5')
        with self.assertRaisesRegex(ValueError,'waveform|temporal'):
            a.audit_source(wrong,params,source,proof,{})

    def test_centroid_shift_rejected_without_changing_total(self):
        s,p,curves,params = fixture('A1')
        for r in curves['device']:
            r['IntegrG_Total X_HeavyIonGeneration'] += .1
        with self.assertRaisesRegex(ValueError,'centroid'):
            a.audit_source(curves,params,s,p,{})

    def test_output_spacing_and_missing_spatial_fields_rejected(self):
        s,p,curves,params = fixture('A1',1e-12)
        params['pulse_max_step_s'] = 5e-13
        with self.assertRaisesRegex(ValueError,'spacing'):
            a.audit_source(curves,params,s,p,{})
        s,p,curves,params = fixture('A1')
        for row in curves['device']:
            del row['IntegrG_Center HeavyIonGeneration']
        with self.assertRaisesRegex(ValueError,'Missing native ROI'):
            a.audit_source(curves,params,s,p,{})

    def test_a0_absence_is_not_measured_zero(self):
        s,p,curves,params = fixture('A0')
        curves['device'] = [{'time':row['time']} for row in curves['device']]
        out = {}
        self.assertTrue(a.audit_source(curves,params,s,p,out))
        self.assertIsNone(out['radiation']['generated_fC'])
        self.assertFalse(out['radiation']['numerical_zero_observed'])
        self.assertTrue(out['radiation']['source_disabled_deck_verified'])

    def test_exact_observed_integr_prefix_and_centroid_names(self):
        names = ['time'] + ['IntegrG_'+r+' HeavyIonGeneration' for r in a.C['rois_um']]
        names += ['IntegrG_Total X_HeavyIonGeneration','IntegrG_Total Y_HeavyIonGeneration']
        expected = {'rois':{r:'IntegrG_'+r+' HeavyIonGeneration' for r in a.C['rois_um']},
                    'centroid':{'x':'IntegrG_Total X_HeavyIonGeneration','y':'IntegrG_Total Y_HeavyIonGeneration'}}
        self.assertEqual(a.resolve_fields(names,True),expected)
        # Regression: the original automatic scan raised before consulting this map.
        self.assertEqual(a.resolve_fields(names,True,expected),expected)
        with self.assertRaisesRegex(ValueError,'Duplicate raw dataset'):
            a.resolve_fields(names+[names[1]],True)

    def test_field_maps_reject_partial_swapped_wrong_quantity_and_loose_aliases(self):
        _,_,curves,_ = fixture('A1')
        names = list(curves['device'][0])
        expected = a.resolve_fields(names,True)
        for mutate in (lambda m:m['rois'].pop('Center'),
                       lambda m:m['centroid'].__setitem__('x',m['centroid']['y']),
                       lambda m:m['rois'].__setitem__('Total',m['centroid']['x']),
                       lambda m:m['rois'].__setitem__('Left',m['rois']['Right']),
                       lambda m:m['rois'].__setitem__('Total','IntegrG_Total ElectricField')):
            bad = copy.deepcopy(expected); mutate(bad)
            with self.assertRaises(ValueError):
                a.resolve_fields(names,True,bad)
        for wrong in ('FakeIntegrG_Total HeavyIonGeneration','IntegrG_TotalExtra HeavyIonGeneration',
                      'G_Total HeavyIonGeneration','IntegrG_Total HeavyIonGeneration X'):
            corrupt = [wrong if k == 'IntegrG_Total HeavyIonGeneration' else k for k in names]
            with self.assertRaisesRegex(ValueError,'Unknown native generation'):
                a.resolve_fields(corrupt,True)
            bad = copy.deepcopy(expected); bad['rois']['Total'] = wrong
            with self.assertRaises(ValueError):
                a.resolve_fields(corrupt,True,bad)
        with self.assertRaisesRegex(ValueError,'omits observed'):
            a.resolve_fields(names,False,{'rois':{},'centroid':{}})

    def test_declared_unknown_execution_code_fails_before_physics(self):
        root = b.OUTPUT_ROOT/'audit-dev'; root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root,prefix='unknown-exit-') as d:
            p = Path(d)
            (p/'manifest.json').write_text(json.dumps({'run_id':p.name,'state':'COLLECTED','ssh_exit_code':None}))
            result = a.audit(p)
            self.assertFalse(result['passed'])
            self.assertIn('actual integer 0',result['errors'][0]['error'])

    def test_archive_traversal_and_links_rejected_without_extraction(self):
        root = b.OUTPUT_ROOT/'audit-dev'; root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root,prefix='bad-tar-') as d:
            for name,kind in [('../outside',tarfile.REGTYPE),('link',tarfile.SYMTYPE)]:
                file = Path(d)/('bad-'+str(len(name))+'.tar')
                with tarfile.open(file,'w') as tf:
                    info = tarfile.TarInfo(name); info.type=kind; info.size=0; info.linkname='outside'
                    tf.addfile(info,io.BytesIO())
                with self.assertRaises(ValueError):
                    with a.Archive(file):
                        pass

    def test_actual_project_generation_and_immutable_inputs(self):
        root = b.OUTPUT_ROOT/'audit-dev'; root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root,prefix='build-') as d:
            for case,bit,variant in [('A2',1,'base'),('A6',1,'time'),('A5',1,'mesh'),('A4',0,'base')]:
                out = Path(d)/('v4-source-interface-r2-'+case.lower()+'-b'+str(bit)+'-'+variant)
                result = b.build(out,case,bit,variant)
                self.assertEqual(result['status'],'OFFLINE_INPUT_CHECK_PASSED')
                deck = (out/'device.cmd').read_text()
                self.assertEqual(deck.count('Integrate(Name='),9)
                self.assertEqual(deck.count('Coordinates'),1)
                self.assertEqual(deck.count('Plot(FilePrefix="gfield_'),5)
                self.assertIn('CurrentPlot(IntegrationUnit=um Digits=12)',deck)
                self.assertIn('MaxStep='+b.number(b.contract()['variants'][variant]['pulse_max_step_s']),deck)
                self.assertNotIn('CurrentPlot (Time',deck)  # accepted samples retained
                with self.assertRaises(ValueError):
                    b.build(out,case,bit,variant)
                (out/'device.cmd').write_text(deck+'\n* mutation\n')
                with self.assertRaisesRegex(ValueError,'hash/file mismatch'):
                    b.check_project(out)


if __name__ == '__main__':
    unittest.main(verbosity=2)
