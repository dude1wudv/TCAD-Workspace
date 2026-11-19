"""Synthetic counterexamples only; no native TCAD result is created by tests."""
import copy
import csv
import importlib.util
import io
import json
import math
from pathlib import Path
import tarfile
import tempfile
import tkinter
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('_test_field3d', HERE/'audit_fields.py')
a = importlib.util.module_from_spec(spec)
exec(compile((HERE/'audit_fields.py').read_bytes(), str(HERE/'audit_fields.py'), 'exec'), a.__dict__)


def source(case='A1'):
    tr = dict(track_id=1, source_name='Artificial1', start_um=[.425,.3,0.], direction=[0.,1.,0.],
              length_um=.6, q_fC=1., wt_hi_um=.03, time_s=1e-9, s_hi_s=2e-12, let_pC_per_um=.001/.6)
    return dict(case_id=case, synthetic=True, event_id='synthetic-offline-test-only',
                source_total_fC=1. if case=='A1' else 0., tracks=[tr] if case=='A1' else [])


def fixture(case='A1', shift_z=0., shift_time=0., amplitude=1., flat_z=False, observed_zero=False, dt=5e-13):
    s = source(case); tracks = copy.deepcopy(s['tracks'])
    for tr in tracks: tr['start_um'][2] += shift_z; tr['time_s'] += shift_time
    times = [0., 9.5e-10]+[9.5e-10+i*dt for i in range(1, round(1e-10/dt)+1)]+[4e-9]
    rows = [{'time':0., a.LEGACY:0.}]; frames=[]; values={}; logs=[]
    for i,(start,end) in enumerate(zip(times,times[1:]),1):
        source_rate = sum(.5*(math.erf((end-tr['time_s'])/(math.sqrt(2)*tr['s_hi_s']))-
                            math.erf((start-tr['time_s'])/(math.sqrt(2)*tr['s_hi_s'])))/(end-start)*tr['q_fC']
                          for tr in tracks)*amplitude
        rows.append({'time':end, a.LEGACY:source_rate/a.CONVERSION})
        if i in (1,len(times)-1):continue
        name=f'gstep_{i:04d}_access_des.tdr'
        frames.append(dict(source_file=name, accepted_index=i, start_s=start, end_s=end, dt_s=end-start))
        logs.extend([f'Computing BE-step from {start:.4e} s to {end:.4e} s (Stepsize: {end-start:.4e} s)',
                     'Error smaller than 1 ( 0.01 ).', f" Writing plot '{name}' (TDR format) ... done."])
        v={}; values[name]=v
        for scope in a.SCOPES:
            roi='Total' if scope=='SILICON_NO_WINDOW' else scope; box=a.C['rois_um6'][roi]
            v['ONE',scope]=math.prod(box[j+3]-box[j] for j in range(3))
            if case=='A0' and not observed_zero:continue
            if tracks:
                x0,y0,z0=tracks[0]['start_um']; w=.03
                fx=(math.erf((box[3]-x0)/w)-math.erf((box[0]-x0)/w))/2
                mx=x0*fx+w/(2*math.sqrt(math.pi))*(math.exp(-((box[0]-x0)/w)**2)-math.exp(-((box[3]-x0)/w)**2))
                fz=(box[5]-box[2]) if flat_z else (math.erf((box[5]-z0)/w)-math.erf((box[2]-z0)/w))/2
                mz=(box[5]+box[2])/2*fz if flat_z else z0*fz+w/(2*math.sqrt(math.pi))*(math.exp(-((box[2]-z0)/w)**2)-math.exp(-((box[5]-z0)/w)**2))
                low,high=max(y0,box[1]),min(y0+.6,box[4]); fy=max(0.,high-low)/.6
                moment=[fx*fy*fz,mx*fy*fz,fx*fy*fz*(low+high)/2,fx*fy*mz]
            else:moment=[0.]*4
            for role,value in zip(('G','XG','YG','ZG'),moment): v[role,scope]=value*source_rate/a.CONVERSION
        for axis,j in zip('XYZ',range(3)):
            v[axis,'-min']=a.C['rois_um6']['Total'][j]; v[axis,'-max']=a.C['rois_um6']['Total'][j+3]
    return frames,values,rows,s,'\n'.join(logs)


def measurement_csv(name, values):
    stream=io.StringIO(); writer=csv.writer(stream)
    writer.writerow(['source_file','field','native_field','scope','operation','raw_value','command_status'])
    for (role,scope),value in values.items():
        if scope in ('-min','-max'):writer.writerow([name,role,role,'SILICON_NO_WINDOW',scope,value,'OK'])
        else:writer.writerow([name,role,a.ROLES[role],scope,'integral',value,'OK'])
    return stream.getvalue()


class Audit3DTests(unittest.TestCase):
    def test_real_builder_contract_and_archived_input_binding(self):
        a.check_dependencies(); b=a.builder()
        self.assertEqual(b.contract()['rois_um6'],a.C['rois_um6'])
        for case in ('A0','A1'):
            files=b.expected_files(case,'v4-source-interface-3d-r1-'+case.lower()+'-b1-main')
            manifest=dict(files_sha256={n:b.sha(raw) for n,raw in files.items()},source_code_sha256=b.code_hashes())
            files['input-manifest.json']=b.encoded(manifest)
            with tempfile.TemporaryDirectory(dir=OUTPUT_TEST) as tmp:
                path=Path(tmp)/'inputs.tar'
                with tarfile.open(path,'w') as tar:
                    for name,raw in files.items():
                        info=tarfile.TarInfo(name);info.size=len(raw);tar.addfile(info,io.BytesIO(raw))
                with a.Archive(path) as archive:
                    p,s=a.check_builder_archive(archive)
                    self.assertEqual(p['case_id'],case)
                    self.assertEqual(s,b.source_spec(case))
            proof=a.offline_proof(b.source_spec(case));other=b.offline_proof(b.source_spec(case))
            for roi in a.C['rois_um6']:
                self.assertAlmostEqual(proof['rois'][roi]['q_fC'],other['rois'][roi]['q_fC'],places=13)

    def test_native_tcl_syntax_and_contract_windows(self):
        script=(HERE/'extract_fields.tcl').read_text()
        tcl=tkinter.Tcl();self.assertTrue(tcl.call('info','complete',script))
        windows=script[script.index('set windows {'):script.index('set stream [open source-case.txt')]
        tcl.eval(windows)
        raw=tcl.eval('set windows'); names=tcl.splitlist(raw)
        parsed={names[i]:[float(x) for x in tcl.splitlist(names[i+1])] for i in range(0,len(names),2)}
        self.assertEqual(parsed,a.C['rois_um6'])
        self.assertIn('foreach required {X Y Z}',script)
        self.assertIn('ZG SFA3D_ZG {<Z>*<HeavyIonGeneration>}',script)
        self.assertIn('structural_zero_not_measured_zero',script)

    def test_exact_volume_and_charge_oracle(self):
        proof=a.offline_proof(source())
        self.assertAlmostEqual(proof['domain_charge_fC'],1.,places=14)
        self.assertAlmostEqual(proof['rois']['CenterTube']['q_fC'],math.erf(1.)**2,places=14)
        self.assertAlmostEqual(proof['rois']['ZPositive']['q_fC'],.5,places=14)
        self.assertAlmostEqual(a.CONVERSION,1e-12*1.602176634e-19*1e15,places=28)

    def test_ideal_3d_fixture_passes_all_gates(self):
        frames,values,rows,s,log=fixture();out={}
        self.assertTrue(a.full_metrics(frames,values,rows,s,out))
        self.assertAlmostEqual(out['charge']['TDR_window_fC'],1.,places=12)
        self.assertAlmostEqual(out['roi_checks']['CenterTube']['observed_fraction'],math.erf(1.)**2,places=12)
        self.assertEqual(len(a.index_frames(log,rows,list(values))[0]),200)
        self.assertIsNone(a.summarize_snapshots(frames,values)[0]['centroid_z_um'])

    def test_zero_source_absence_stays_unknown_not_measured_zero(self):
        frames,values,rows,s,_=fixture('A0');out={}
        self.assertTrue(a.full_metrics(frames,values,rows,s,out))
        self.assertIsNone(out['zero_source']['measured_window_charge_fC'])
        self.assertFalse(out['zero_source']['native_zero_observed_all_frames'])
        row=a.summarize_snapshots(frames,values)[0]
        self.assertIsNone(row['G_SILICON_NO_WINDOW_raw']); self.assertIsNone(row['centroid_z_um'])
        name=next(iter(values));self.assertEqual(a.parse_measurements(measurement_csv(name,values[name]),[name],'A0')[name],values[name])

    def test_observed_zero_and_nonzero_A0(self):
        f,v,r,s,_=fixture('A0',observed_zero=True);out={};a.full_metrics(f,v,r,s,out)
        self.assertEqual(out['zero_source']['measured_window_charge_fC'],0.)
        v[next(iter(v))]['G','Total']=1.
        with self.assertRaisesRegex(ValueError,'A0 native'):a.full_metrics(f,v,r,s,{})

    def test_z_shift_is_detected(self):
        f,v,r,s,_=fixture(shift_z=.04)
        with self.assertRaisesRegex(ValueError,'XYZ centroid|ROI fraction'):a.full_metrics(f,v,r,s,{})

    def test_flat_extrusion_cannot_pass_by_total_or_overall_centroid(self):
        f,v,r,s,_=fixture(flat_z=True);out={}
        with self.assertRaisesRegex(ValueError,'ROI fraction|waveform'):a.full_metrics(f,v,r,s,out)
        self.assertAlmostEqual(out['charge']['TDR_window_fC'],1.,places=12)
        self.assertLess(out['roi_checks']['CenterTube']['observed_fraction'],.1)

    def test_wrong_time_and_amplitude_fail(self):
        for kwargs in ({'shift_time':2e-12},{'amplitude':2.}):
            with self.subTest(kwargs=kwargs):
                f,v,r,s,_=fixture(**kwargs)
                with self.assertRaises(ValueError):a.full_metrics(f,v,r,s,{})

    def test_missing_duplicate_frames_failed_steps_and_coarse_time_rejected(self):
        f,v,r,s,log=fixture();names=list(v)
        for text,files in [(log,names[1:]),(log,names+[names[0]]),(log.replace('Error smaller than 1 ( 0.01 ).',"Newton didn't converge",1),names)]:
            with self.assertRaises(ValueError):a.index_frames(text,r,files)
        f,v,r,s,log=fixture(dt=1e-12)
        with self.assertRaisesRegex(ValueError,'0.5 ps'):a.index_frames(log,r,list(v))

    def test_missing_zg_and_nonfinite_refused(self):
        _,values,_,_,_=fixture();name=next(iter(values));v=values[name]
        self.assertEqual(a.parse_measurements(measurement_csv(name,v),[name],'A1')[name],v)
        del v['ZG','CenterTube']
        with self.assertRaisesRegex(ValueError,'Missing native'):a.parse_measurements(measurement_csv(name,v),[name],'A1')
        v['ZG','CenterTube']=float('nan')
        with self.assertRaisesRegex(ValueError,'Nonfinite'):a.parse_measurements(measurement_csv(name,v),[name],'A1')

    def test_duplicate_deposition_and_unvalidated_real_track_refused(self):
        s=source();s['tracks']*=2
        with self.assertRaisesRegex(ValueError,'duplicate deposition'):a.offline_proof(s)
        s=source();s['synthetic']=False
        with self.assertRaisesRegex(ValueError,'not real events'):a.offline_proof(s)
        s=source();s['tracks'][0]['direction']=[0.,0.,1.]
        with self.assertRaisesRegex(ValueError,'frozen'):a.offline_proof(s)

    def test_wrong_native_volume_and_z_extent_refused(self):
        f,v,r,s,_=fixture()
        for values in v.values():values['ONE','SILICON_NO_WINDOW']*=2;values['Z','-max']=0.
        with self.assertRaisesRegex(ValueError,'volume differs|extent differs'):a.full_metrics(f,v,r,s,{})

    def test_archive_namespace_refuses_duplicate_or_traversal(self):
        for names in (['f','f'],['../escape']):
            with tempfile.TemporaryDirectory(dir=OUTPUT_TEST) as tmp:
                path=Path(tmp)/'bad.tar'
                with tarfile.open(path,'w') as tar:
                    for name in names:
                        info=tarfile.TarInfo(name); info.size=1;tar.addfile(info,io.BytesIO(b'x'))
                with self.assertRaises(ValueError):a.Archive(path)

    def test_unknown_extraction_exit_refused(self):
        with tempfile.TemporaryDirectory(dir=OUTPUT_TEST) as tmp:
            p=Path(tmp);(p/'field-extraction-record.json').write_text(json.dumps(dict(schema='dram-see-v4-native-field-extraction-receipt-r1',svisual_exit_code=None)))
            with self.assertRaisesRegex(ValueError,'Unknown/nonzero'):a.extraction_evidence(p,None,{})

    def test_duplicate_prepare_is_refused_before_any_write(self):
        with tempfile.TemporaryDirectory(dir=OUTPUT_TEST) as tmp:
            root=Path(tmp);(root/'exists').mkdir()
            with patch.object(a,'INPUTS',root),patch.object(a,'source_provenance',return_value=({'remote_directory':'/tmp/runs/r','run_id':'r'},{})):
                with self.assertRaisesRegex(ValueError,'never overwrite'):a.prepare('unused','exists')


OUTPUT_TEST=a.OUTPUT/'test-fixtures'
OUTPUT_TEST.mkdir(parents=True,exist_ok=True)
if __name__=='__main__':unittest.main(verbosity=2)
