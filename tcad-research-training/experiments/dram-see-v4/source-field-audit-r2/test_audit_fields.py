"""Focused offline counterexamples; generated fixtures are not TCAD evidence."""
import copy
import csv
import io
import json
import math
from pathlib import Path
import tempfile
import tkinter
import unittest
import importlib.util

HERE=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('_field_r2_tests',HERE/'audit_fields.py');a=importlib.util.module_from_spec(s)
exec(compile((HERE/'audit_fields.py').read_bytes(),str(HERE/'audit_fields.py'),'exec'),a.__dict__)


def proof_for(spec):
    rois={}
    for roi,(xmin,ymin,xmax,ymax) in a.C['rois_um'].items():
        parts=[]
        for tr in spec['tracks']:
            x,y=tr['start_um'][:2];w,L=tr['wt_hi_um'],tr['length_um'];q=tr['q_fC']
            if tr['direction'][:2]==[0.,1.]:
                low,high=max(y,ymin),min(y+L,ymax)
                longitudinal=max(0.,high-low)/L
                transverse=(math.erf((xmax-x)/w)-math.erf((xmin-x)/w))/2
                fraction=longitudinal*transverse
                xm=longitudinal*(x*transverse+w/(2*math.sqrt(math.pi))*(math.exp(-((xmin-x)/w)**2)-math.exp(-((xmax-x)/w)**2)))
                ym=fraction*(low+high)/2
            else:
                fraction,xm,ym=a.r3.b.r2.rectangle_moments(tr,[xmin,ymin,xmax,ymax],512)
            parts.append({'source_name':tr['source_name'],'q_fC':q*fraction,'fraction':fraction,'x_moment_fC_um':q*xm,'y_moment_fC_um':q*ym})
        charge=sum(t['q_fC'] for t in parts)
        rois[roi]={'tracks':parts,'q_fC':charge}
    return {'domain_charge_fC':rois['Total']['q_fC'],'rois':rois}


def fixture(case,wrong_source=None,dt=.5e-12):
    spec=a.r3.b.r2.make_spec(case);proof=proof_for(spec)
    measured=wrong_source if wrong_source is not None else spec;mp=proof_for(measured)
    count=round(.1e-9/dt);times=[0.,.95e-9]+[.95e-9+i*dt for i in range(1,count+1)]+[4e-9]
    trmap={t['source_name']:t for t in measured['tracks']}
    rows=[{'time':0.,a.LEGACY:0.}];frames=[];values={};logs=[]
    for i,(start,end) in enumerate(zip(times,times[1:]),1):
        rates={name:(math.erf((end-tr['time_s'])/(math.sqrt(2)*tr['s_hi_s']))-math.erf((start-tr['time_s'])/(math.sqrt(2)*tr['s_hi_s'])))/(2*(end-start)) for name,tr in trmap.items()}
        total=sum(t['q_fC']*rates[t['source_name']] for t in mp['rois']['Total']['tracks'])
        rows.append({'time':end,a.LEGACY:total/a.CONVERSION})
        if i==1 or i==len(times)-1:continue
        name=f'gstep_{i:04d}_access_des.tdr'
        frames.append({'source_file':name,'accepted_index':i,'start_s':start,'end_s':end,'dt_s':end-start})
        logs.extend([f'Computing BE-step from {start:.4e} s to {end:.4e} s (Stepsize: {end-start:.4e} s)',
                     'Error smaller than 1 ( 0.01 ).',f" Writing plot '{name}' (TDR format) ... done."])
        v={};values[name]=v
        for scope in a.SCOPES:
            roi='Total' if scope=='SILICON_NO_WINDOW' else scope
            for role,key in [('G','q_fC'),('XG','x_moment_fC_um'),('YG','y_moment_fC_um')]:
                v[role,scope]=sum(t[key]*rates[t['source_name']] for t in mp['rois'][roi]['tracks'])/a.CONVERSION
            rect=a.C['rois_um'][roi];v['ONE',scope]=(rect[2]-rect[0])*(rect[3]-rect[1])
    return frames,values,rows,spec,proof,'\n'.join(logs)


class FieldTests(unittest.TestCase):
    def test_real_builder_contract_roles_and_independent_spatial_proofs(self):
        b=a.module(HERE.parent/'source-interface-r5/build_interface.py','_field_r2_builder_fixture')
        c=b.contract()
        self.assertEqual(c['rois_um'],a.C['rois_um']);self.assertEqual(c['audit_tolerances'],a.T)
        self.assertEqual(c['additional_roi_gate_cases'],a.C['local_source_roi_cases'])
        self.assertEqual(c['additional_rois'],a.C['local_source_rois'])
        for case,bit,variant in c['primary_roles']:
            b.check_role(case,bit,variant)
            if case=='A0':continue
            i,v,r,s,p,_=fixture(case,dt=c['variants'][variant]['pulse_max_step_s'])
            actual=b.offline_proof(b.source_spec(case))
            for roi in a.C['rois_um']:
                self.assertAlmostEqual(actual['rois'][roi]['q_fC'],p['rois'][roi]['q_fC'],places=11)
            self.assertTrue(a.full_metrics(i,v,r,s,actual,{}))

    def test_tcl_only_adds_declared_windows_to_native_verified_script(self):
        old=(HERE.parent/'source-field-audit-r1/extract_fields_bounded_r2.tcl').read_text()
        new=(HERE/'extract_fields.tcl').read_text()
        self.assertTrue(tkinter.Tcl().call('info','complete',new))
        new='\n'.join(old.split('\n')[:2]+new.split('\n')[2:])
        new=new.replace('    SourceLeft {0.295 0 0.355 1.2}\n    SourceRight {0.495 0 0.555 1.2}\n','')
        new=new.replace('schema=source-field-audit-r2-extraction','schema=source-field-audit-r1-extraction')
        self.assertEqual(old,new)
        self.assertEqual(a.checked_extractor(next(iter(a.EXTRACTORS)),HERE/'extract_fields.tcl'),'extract_fields.tcl')

    def test_every_source_role_analytic_fixture_and_A3_half_charge(self):
        for case in a.C['source_case_ids']:
            with self.subTest(case=case):
                i,v,r,s,p,_=fixture(case);out={};self.assertTrue(a.full_metrics(i,v,r,s,p,out))
                self.assertAlmostEqual(out['charge']['TDR_window_fC'],.5 if case=='A3' else 1.,places=10)
                self.assertEqual(('SourceLeft' in out['gated_rois']),case in ['A5','A6','A7'])
        with self.assertRaises(ValueError):a.gating_rois('A0')

    def test_A3_rejects_compensated_clipped_charge(self):
        wrong=a.r3.b.r2.make_spec('A3');wrong['tracks'][0]['q_fC']=2.
        i,v,r,s,p,_=fixture('A3',wrong)
        with self.assertRaisesRegex(ValueError,'domain target'):a.full_metrics(i,v,r,s,p,{})

    def test_A5_rejects_coincident_tracks(self):
        wrong=a.r3.b.r2.make_spec('A5')
        for tr in wrong['tracks']:tr['start_um'][0]=.425
        i,v,r,s,p,_=fixture('A5',wrong);out={}
        with self.assertRaises(ValueError):a.full_metrics(i,v,r,s,p,out)
        self.assertTrue(any('SourceLeft' in err or 'SourceRight' in err for err in out['field_gate_failures']))

    def test_A6_local_double_time_delay_and_wrong_order(self):
        i,v,r,s,p,_=fixture('A6');out={};a.full_metrics(i,v,r,s,p,out)
        self.assertAlmostEqual(out['A6_local_delay']['observed_s'],1e-11,delta=1e-15)
        for wrong in ('same','reverse'):
            source=a.r3.b.r2.make_spec('A6')
            if wrong=='same':source['tracks'][1]['time_s']=1e-9
            else:source['tracks'][0]['time_s'],source['tracks'][1]['time_s']=1.01e-9,1e-9
            i,v,r,s,p,_=fixture('A6',source);out={}
            with self.assertRaises(ValueError):a.full_metrics(i,v,r,s,p,out)
            self.assertTrue(any('delay differs' in err for err in out['field_gate_failures']))

    def test_all_effective_roi_centroids_are_observed(self):
        i,v,r,s,p,_=fixture('A6')
        for values in v.values():values['XG','SourceLeft']=.38*values['G','SourceLeft']
        with self.assertRaisesRegex(ValueError,'centroid exceeds0.01um: SourceLeft'):a.full_metrics(i,v,r,s,p,{})
        i,v,r,s,p,_=fixture('A1')
        for values in v.values():values['YG','Low']=.45*values['G','Low']
        with self.assertRaisesRegex(ValueError,'centroid exceeds0.01um: Low'):a.full_metrics(i,v,r,s,p,{})

    def test_new_rois_do_not_add_gates_to_other_cases(self):
        i,v,r,s,p,_=fixture('A1')
        for values in v.values():
            for roi in ('SourceLeft','SourceRight'):
                for field in ('G','XG','YG'):values[field,roi]=0.
        self.assertTrue(a.full_metrics(i,v,r,s,p,{}))

    def test_missing_frames_duplicate_failed_BE_and_time_profile(self):
        for dt,count in [(.5e-12,200),(.25e-12,400)]:
            i,v,r,s,p,log=fixture('A6',dt=dt)
            indexed,boundary=a.index_frames(log,r,list(v),True);self.assertEqual(len(indexed),count);self.assertFalse(boundary)
            with self.assertRaisesRegex(ValueError,'Missing/extra'):a.index_frames(log,r,list(v)[1:],True)
            with self.assertRaises(ValueError):a.index_frames(log.replace('Error smaller than 1 ( 0.01 ).',"Newton didn't converge",1),r,list(v),True)

    def test_missing_moment_nonfinite_and_cleanup_name(self):
        i,v,r,s,p,_=fixture('A1');name=next(iter(v));one=v[name]
        def text(values):
            b=io.StringIO();w=csv.writer(b);w.writerow(['source_file','field','native_field','scope','operation','raw_value','command_status'])
            for (role,scope),value in values.items():w.writerow([name,role,a.ROLES[role],scope,'integral',value,'OK'])
            return b.getvalue()
        self.assertEqual(a.parse_measurements(text(one),[name])[name],one)
        del one['XG','SourceLeft']
        with self.assertRaises(ValueError):a.parse_measurements(text(one),[name])
        one['XG','SourceLeft']=float('nan')
        with self.assertRaises(ValueError):a.parse_measurements(text(one),[name])
        raw='source_file,field,native_field,scope,operation,raw_value,command_status\nf.tdr,,Plot_f,,remove_plots,Wrong,OK\nf.tdr,,f,,remove_datasets,f,OK\n'
        inv='source_file,dataset,object_type,native_name\nf.tdr,f,plot,Plot_f\nf.tdr,f,geometry,f\n'
        with self.assertRaises(ValueError):a.check_cleanup(raw,['f.tdr'],'exact_deleted_object_name',inv)

    def test_outside_charge_and_complete_native_frame_columns(self):
        i,v,r,s,p,_=fixture('A6');r[-1][a.LEGACY]=.02/a.CONVERSION/(r[-1]['time']-r[-2]['time'])
        out={};a.full_metrics(i,v,r,s,p,out)
        self.assertAlmostEqual(out['charge']['legacy_outside_window_fC'],.02,places=12)
        frames=a.summarize_snapshots(i,v)
        for roi in a.C['rois_um']:
            for field in a.ROLES:self.assertIn(field+'_'+roi+'_raw',frames[0])


if __name__=='__main__':unittest.main(verbosity=2)
