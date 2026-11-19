"""Focused offline checks only; no TCAD or native SVisual invocation."""
import importlib.util
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
sp=importlib.util.spec_from_file_location('r4build',HERE/'build_interface.py')
b=importlib.util.module_from_spec(sp);exec(compile((HERE/'build_interface.py').read_bytes(),str(HERE/'build_interface.py'),'exec'),b.__dict__)


class FrozenMeshObservers(unittest.TestCase):
    def project(self,case):return b.OUTPUT_ROOT/'inputs'/('v4-source-interface-r4-'+case.lower()+'-b1-mesh')
    def reference(self,case):return b.R2_INPUTS/('v4-source-interface-r2-'+case.lower()+'-b1-mesh')
    def test_only_authorized_two_roles(self):
        self.assertEqual(b.contract()['candidate_roles'],[['A0',1,'mesh'],['A1',1,'mesh']])
        for role in [('A4',1,'mesh'),('A1',0,'mesh'),('A1',1,'base'),('A0',True,'mesh')]:
            with self.assertRaises(ValueError):b.check_role(*role)
    def test_global_budget_never_restarts(self):
        budget=b.contract()['global_budget']
        self.assertEqual(budget['maximum_tcad_attempts'],19)
        self.assertEqual(budget['prior_attempts_at_revision_freeze'],3)
        self.assertFalse(budget['new_budget_created'])
    def test_complete_candidate_checks(self):
        for case in ('A0','A1'):
            r=b.check_project(self.project(case));self.assertEqual(r['status'],'OFFLINE_INPUT_CHECK_PASSED')
            self.assertFalse(r['solver_started']);self.assertFalse(r['prior_failures_promoted'])
    def test_mesh_is_the_only_physical_variant(self):
        for case in ('A0','A1'):
            diff=b.physical_diff(case,self.reference(case))
            self.assertEqual(set(diff['physical_parameter_differences']),{'geometry_sha256','mesh_scale','variant'})
            self.assertEqual(diff['physical_parameter_differences']['mesh_scale'],{'base':1.,'mesh':.5})
            self.assertTrue(diff['source_and_r2_device_deck_byte_identical_to_base'])
            self.assertFalse(diff['changes_main_mesh_for_other_cases'])
    def test_r4_observation_removal_restores_full_r2_deck(self):
        for case in ('A0','A1'):
            self.assertEqual(b.strip_r4_observers(b.render_deck(case),case),(self.reference(case)/'device.cmd').read_text())
    def test_dynamic_output_does_not_force_new_time_points(self):
        for case in ('A0','A1'):
            deck=b.render_deck(case)
            self.assertEqual(deck.count(b.DYNAMIC_PLOT),1)
            self.assertNotIn('Intervals',deck);self.assertNotIn('MinSpacing',deck)
            injection=deck[deck.index('Transient(InitialTime=0.95e-9'):deck.index('Transient(InitialTime=1.05e-9')]
            self.assertIn(b.DYNAMIC_PLOT,injection)
            self.assertIn('MaxStep=4.9999999999999999e-13',injection)
            self.assertEqual(len(re.findall(r'Plot\(FilePrefix="gfield_\d" Time=',injection)),5)
            self.assertEqual(re.findall(r'Transient\([^)]*\)',deck),re.findall(r'Transient\([^)]*\)',(self.reference(case)/'device.cmd').read_text()))
    def test_no_source_or_named_parameter_changes(self):
        for case in ('A0','A1'):
            for name in ('geometry.scm','heavyion.par','source-spec.json'):
                self.assertEqual((self.project(case)/name).read_bytes(),(self.reference(case)/name).read_bytes())
        self.assertEqual(b.source_spec('A0')['tracks'],[])
        self.assertNotIn('HeavyIon("Ion',b.render_deck('A0'))
        source=b.source_spec('A1');self.assertEqual(source['source_total_fC'],1.)
        t=source['tracks'][0]
        self.assertEqual((t['start_um'],t['length_um'],t['time_s'],t['wt_hi_um'],t['s_hi_s']),([.425,.3,0.],.6,1e-9,.03,2e-12))
    def test_a0_undefined_centroid_is_not_requested(self):
        self.assertNotIn('Coordinates',b.current_plot('A0'))
        self.assertIn('Coordinates',b.current_plot('A1'))
        for case in ('A0','A1'):
            cur=b.current_plot(case)
            for token in ['Integrate(Semiconductor)','G_Plain','G_2DTotal','G_Total','Temperature','Area_Plain','Area_2DTotal']:
                self.assertIn(token,cur)
    def test_legacy_and_all_native_frames_are_required(self):
        c=b.contract();self.assertFalse(c['measurement']['window_can_pass_acceptance'])
        self.assertTrue(c['measurement']['all_frames_required'])
        self.assertEqual(c['audit_tolerances'],b.r3.contract()['audit_tolerances'])
        self.assertEqual(c['audit_tolerances']['source_relative'],.05)
        self.assertEqual(c['audit_tolerances']['refinement_charge_relative'],.02)
    def test_project_only_lists_fixed_outputs_no_wildcards(self):
        for case in ('A0','A1'):
            project=b.read_json(self.project(case)/'project.json')
            self.assertEqual([s['tool'] for s in project['steps']],['sde','sdevice'])
            names=project['steps'][1]['outputs']
            self.assertTrue(all('*' not in n and '?' not in n and 'gstep' not in n for n in names))
            self.assertEqual(len([n for n in names if n.startswith('gfield_')]),5)
            self.assertIn('transient_des.log',names);self.assertIn('access_device.plt',names)
    def test_duplicate_output_rejected(self):
        with self.assertRaises(ValueError):b.build(self.project('A0'),'A0',self.reference('A0'))
    def test_changed_input_is_rejected_without_running(self):
        work=b.OUTPUT_ROOT/'build-dev';work.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='tamper-',dir=work) as temporary:
            out=Path(temporary)/'v4-source-interface-r4-a0-b1-mesh-test'
            shutil.copytree(self.project('A0'),out)
            deck=out/'device.cmd';deck.write_text(deck.read_text().replace('NoOverwrite','NoOverwrite Intervals=200'))
            with self.assertRaisesRegex(ValueError,'hash differs'):b.check_project(out)
    def test_missing_required_source_field_rejected_by_frozen_source_validator(self):
        spec=b.source_spec('A1');del spec['tracks'][0]['q_fC']
        with self.assertRaises(ValueError):b.r2.validate_spec(spec)
    def test_nonzero_z_not_silently_projected(self):
        spec=b.source_spec('A1');spec['tracks'][0]['start_um'][2]=.1
        with self.assertRaisesRegex(ValueError,'Nonzero z'):b.r2.validate_spec(spec)


if __name__=='__main__':unittest.main()
