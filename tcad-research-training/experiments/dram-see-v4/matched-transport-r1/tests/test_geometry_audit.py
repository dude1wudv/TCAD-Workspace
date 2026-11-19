"""Counterexamples for new constructed-geometry and native-cost acceptance."""
import copy
import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('matched_geometry_audit',HERE.parent/'audit_matched.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)


class GeometryCostTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='offline-',dir=HERE)
        self.folder=Path(self.temporary.name)
        self.contract=json.loads((HERE.parent/'matched-contract.json').read_text(encoding='utf-8'))
        self.metadata=dict(geometry=self.contract['geometry'],world_half_um=self.contract['world_half_um'],
                           max_step_um=.02,mode='normal')
        self.status=dict(events_completed=2,tracks_completed=2,steps_recorded=5)
        self.geometry=[]
        for s in self.contract['geometry']['solids']:
            row=dict(volume=s['id'],material=s['geant4_material'],density_g_cm3=s['density_g_cm3'],
                     charged_max_step_um=.02,overlap_check_passed=1)
            for i,axis in enumerate('xyz'):
                row['min_'+axis+'_um']=s['min_um'][i];row['max_'+axis+'_um']=s['max_um'][i]
            self.geometry.append(row)
        world=dict(volume='World',material='G4_Galactic',density_g_cm3=1e-25,charged_max_step_um='',overlap_check_passed=1)
        for i,axis in enumerate('xyz'):
            world['min_'+axis+'_um']=-self.contract['world_half_um'][i]
            world['max_'+axis+'_um']=self.contract['world_half_um'][i]
        self.geometry.append(world)
        self.timings=[]
        for phase in ['initialization','inventory_initialization','event_loop','inventory_events']:
            active=phase in ('event_loop','inventory_events')
            self.timings.append(dict(phase=phase,wall_seconds=1.,cpu_seconds=.5,events=2 if active else 0,
                                     tracks=2 if active else 0,steps=5 if active else 0))

    def tearDown(self):
        self.temporary.cleanup()

    def check(self):
        for name,rows in [('geometry-built.csv',self.geometry),('timings.csv',self.timings)]:
            with (self.folder/name).open('w',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=rows[0].keys());writer.writeheader();writer.writerows(rows)
        return a._geometry_cost(self.folder,self.metadata,self.status,{})

    def test_matching_constructed_geometry_and_cost(self):
        self.assertTrue(self.check())

    def test_z_coordinate_shift_rejected(self):
        self.geometry[0]['min_z_um']+=.01
        with self.assertRaisesRegex(ValueError,'bounds differ'): self.check()

    def test_missing_oxide_rejected(self):
        self.geometry.pop(1)
        with self.assertRaisesRegex(ValueError,'Missing, duplicate'): self.check()

    def test_native_density_mismatch_rejected(self):
        self.geometry[0]['density_g_cm3']=2.4
        with self.assertRaisesRegex(ValueError,'density differs'): self.check()

    def test_native_overlap_rejected(self):
        self.geometry[0]['overlap_check_passed']=0
        with self.assertRaisesRegex(ValueError,'overlap failed'): self.check()

    def test_wrong_event_timing_denominator_rejected(self):
        self.timings[2]['events']=1
        with self.assertRaisesRegex(ValueError,'count differs'): self.check()

    def test_missing_initialization_cost_rejected(self):
        self.timings.pop(0)
        with self.assertRaisesRegex(ValueError,'cost phases'): self.check()


if __name__=='__main__': unittest.main()
