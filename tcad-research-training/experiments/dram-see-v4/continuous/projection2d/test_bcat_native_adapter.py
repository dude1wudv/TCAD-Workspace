"""Pure format/identity checks; no forged native operation or BCAT event result."""
import importlib.util
import math
from pathlib import Path
import unittest
from copy import deepcopy
from datetime import datetime,timezone

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('_test_strict_bcat',HERE/'bcat_native_adapter.py')
N=importlib.util.module_from_spec(spec);exec(compile((HERE/'bcat_native_adapter.py').read_bytes(),str(HERE/'bcat_native_adapter.py'),'exec'),N.__dict__)
A=N.A


class BCATAdapterChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.F=A.v1();cls.scope=cls.F.proton_modules();cls.P,_,cls.B=cls.scope.__enter__()
        folder=N.BUILD/'collected'
        cls.geometry=A.read_json(folder/'geometry-contract.json');cls.model=A.read_json(folder/'model-input.json')
        request_path=N.ROOT/'local_runtime/dram-see-v4/continuous/proton/s2-transport-p100-a0-seed61017041-r1/request.json'
        cls.request=A.read_json(request_path);cls.columns=N.export_headers(folder/'transport_bcat.cc')

    @classmethod
    def tearDownClass(cls):cls.scope.__exit__(None,None,None)

    def metadata_fixture(self):
        q=self.request;g=self.geometry
        return dict(schema='v4-matched-transport-r1',units=deepcopy(N.UNITS),geometry=deepcopy(g),geometry_id=self.model['model_id'],
            mode='normal',arm='H',primary_particle='proton',seed=q['seed'],events_requested=q['event_count'],energy_MeV=q['energy_MeV'],
            angle_deg=q['theta_deg'],request_label=q['label'],requested_threads=1,multithreaded_run_manager=False,
            run_manager='G4RunManager',geant4_version_number=1073,user_track_killing=False,standard_neutron_time_limit_ns=10000,
            step_limiter_charged_only=True,output_precision_digits=17,production_cut_um=g['production_cut_um'],max_step_um=g['max_step_um'],
            surface_position_um=[-.052,0.,0.],beam_position_um=[-.052,0.,-1.],beam_direction=[0.,0.,1.])

    def test_01_actual_compile_export_columns_and_explicit_units(self):
        folder,receipt=self.P.complete_operation(N.BUILD,('transport_bcat.cc','compile-exit-code.txt','geometry-contract.json'))
        self.assertEqual(receipt['operation_task_exit_code'],0)
        self.assertIn('pre_y_um',self.columns['steps.csv']);self.assertIn('birth_token',self.columns['tracks.csv'])
        condition,beam=N.validate_metadata(self.request,self.metadata_fixture(),self.geometry,self.model,self.B)
        self.assertEqual(condition['split'],'train');self.assertEqual(beam['direction'],[0,0,1])
        for units in (None,dict(length='nm',time='ns',energy='MeV',charge='eplus',direction='unit_vector')):
            bad=self.metadata_fixture();bad['units']=units
            with self.assertRaisesRegex(ValueError,'units'):N.validate_metadata(self.request,bad,self.geometry,self.model,self.B)

    def test_02_planar_and_final_condition_reject_before_event_read(self):
        old=dict(schema='dram-see-v4-shared-geometry-3d-r1',coordinate_transform='old planar axes')
        with self.assertRaisesRegex(ValueError,'planar'):N.validate_metadata(self.request,self.metadata_fixture(),old,self.model,self.B)
        request=deepcopy(self.request);request.update(energy_MeV=150.)
        meta=self.metadata_fixture();meta['energy_MeV']=150.
        with self.assertRaisesRegex(ValueError,'Final'):N.validate_metadata(request,meta,self.geometry,self.model,self.B)
        request=deepcopy(self.request);request.update(energy_MeV=50.,theta_deg=30.)
        meta=self.metadata_fixture();meta.update(energy_MeV=50.,angle_deg=30.)
        with self.assertRaisesRegex(ValueError,'Final'):N.validate_metadata(request,meta,self.geometry,self.model,self.B)

    def population_fixture(self):
        event={k:'0' for k in self.columns['events.csv']};event.update(event_id='0',primary_count='1',track_count='1',step_count='1',world_step_count='1',event_complete='1')
        track={k:'0' for k in self.columns['tracks.csv']};track.update(event_id='0',track_id='1',parent_id='0',step_count='1')
        step={k:'0' for k in self.columns['steps.csv']};step.update(event_id='0',track_id='1',parent_id='0',step_id='1',pre_volume='World',pre_material='G4_Galactic',
            pre_z_um='-1',post_z_um='0',step_um='1',chord_um='1',deposit_kind='zero_ionizing',local_ionizing_MeV_per_um='0')
        material=[]
        for scope,tid in [('event','0'),('track','1')]:
            for name in set(N.VOLUMES.values()):
                material.append(dict(scope=scope,event_id='0',track_id=tid,material=name,step_count=('1' if name=='G4_Galactic' else '0'),edep_MeV='0',niel_MeV='0',ionizing_MeV='0'))
        tables={'events.csv':[event],'tracks.csv':[track],'steps.csv':[step],'birth-links.csv':[],'material-energy.csv':material}
        status=dict(schema='v4-matched-transport-status-r1',state='COMPLETED',events_requested=1,events_completed=1,tracks_completed=1,steps_recorded=1)
        return tables,status

    def test_03_denominator_zero_step_and_material_ledger_preserved(self):
        tables,status=self.population_fixture();events,groups=N.validate_population(tables,status,1,self.B)
        self.assertEqual(len(events),1);self.assertEqual(groups[0]['steps.csv'][0]['deposit_kind'],'zero_ionizing')
        for mutate in (lambda t:t['events.csv'].append(deepcopy(t['events.csv'][0])),lambda t:t['steps.csv'].clear(),
                       lambda t:t['material-energy.csv'].pop(),lambda t:t['steps.csv'][0].update(chord_um='.8')):
            bad=deepcopy(tables);mutate(bad)
            with self.assertRaises(ValueError):N.validate_population(bad,status,1,self.B)

    def test_04_missing_column_and_missing_real_operation_fail_explicitly(self):
        output=N.RUNTIME/('bcat-format-FIXTURE-NOT-NATIVE-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));output.mkdir(parents=True)
        path=output/'missing-column.csv';path.write_text(','.join(self.columns['steps.csv'][:-1])+'\n')
        with self.assertRaisesRegex(ValueError,'columns'):N.exact_csv(path,self.columns['steps.csv'])
        absent=N.RUNTIME/'UNCREATED-NOT-NATIVE-OPERATION'
        with self.assertRaises(FileNotFoundError):N.audit(absent,15e-9)
        self.assertFalse(absent.exists())


if __name__=='__main__':unittest.main(verbosity=2)
