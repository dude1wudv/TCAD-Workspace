"""Isolated source mathematics and raw-evidence binding tests; no native execution."""
import copy
import csv
import math
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import common as c
import source_kernel as k
import event_source as e

DEV = c.RT / 'source-dev'
ALL = [[-math.inf] * 3, [math.inf] * 3]
TIME = [-math.inf, math.inf]


def step(uid='s1', r0=(.4, .4, .1), r1=None, t0=1e-9, t1=None, q=1.):
    r1 = r0 if r1 is None else r1
    return dict(uid=uid, r0_um=list(r0), r1_um=list(r1), t0_s=t0,
                t1_s=t0 if t1 is None else t1, charge_fC=q, w_um=.03,
                sigma_s=2e-12, kind='point' if r0 == r1 else 'segment', provenance={'synthetic': True})


def source(*rows):
    return dict(schema=k.SCHEMA, geometry_sha256=c.sha(c.GEOMETRY), steps=list(rows), provenance={'kind': 'test'})


class KernelTests(unittest.TestCase):
    def close(self, a, b, rel=1e-9, absolute=1e-12):
        self.assertLessEqual(abs(a-b), absolute + rel * max(abs(a), abs(b)))

    def test_canonical_order_and_negative_zero(self):
        a, b = step('b'), step('a', r0=(0., .1, .2), q=2.)
        b['r0_um'][0] = -0.
        self.assertEqual(k.native_bytes(source(a,b)), k.native_bytes(source(b,a)))
        self.assertEqual(c.encoded(k.canonical_source(source(a,b))), c.encoded(k.canonical_source(source(b,a))))
        self.assertNotIn(b'-0 ', k.native_bytes(source(b)))

    def test_invalid_source_rejected(self):
        for key, value in [('charge_fC',0),('charge_fC',-1),('t0_s',math.nan),('w_um',.02),('sigma_s',1e-12),('kind','segment')]:
            with self.subTest(key=key,value=value), self.assertRaises(ValueError):
                s=step();s[key]=value;k.validate_source(source(s))
        with self.assertRaises(ValueError): k.validate_source(source(step(),step()))
        s=source(step());s['geometry_sha256']='0'*64
        with self.assertRaises(ValueError): k.validate_source(s)

    def test_empty_zero_source(self):
        s=source()
        self.assertEqual(k.generation(s,[0,0,0],0),0.)
        self.assertEqual(k.average_generation(s,[0,0,0],[0,1e-12]),0.)
        self.assertEqual(k.integrated(s,ALL,TIME)['charge_fC'],0.)
        self.assertEqual(k.native_bytes(s),b'NUCLEAR_CLOSURE_SOURCE_V1 0\n')

    def test_point_density_units(self):
        s=source(step(q=2.))
        expected=2e-15/k.E_C * 1e12 / (math.pi**1.5 * .03**3 * math.sqrt(2*math.pi)*2e-12)
        self.close(k.generation(s,[.4,.4,.1],1e-9),expected)
        self.close(k.generation(s,[.43,.4,.1],1e-9),expected/math.e)

    def test_point_be_average_exact(self):
        s=source(step())
        lo,hi=1e-9-2e-12,1e-9+2e-12
        mass=math.erf(1/math.sqrt(2))
        expected=1e-15/k.E_C*1e12/(math.pi**1.5*.03**3)*(mass/(hi-lo))
        self.close(k.average_generation(s,[.4,.4,.1],[lo,hi]),expected)

    def test_nonpositive_be_interval_rejected(self):
        for interval in ([1.,1.],[2.,1.],[-math.inf,1.]):
            with self.assertRaises(ValueError): k.average_generation(source(step()),[0,0,0],interval)

    def test_point_total_and_moments(self):
        result=k.integrated(source(step(q=3.)),ALL,TIME)
        self.close(result['charge_fC'],3.)
        for x,y in zip(result['centroid_um'],[.4,.4,.1]):self.close(x,y)
        self.close(result['time_centroid_s'],1e-9,absolute=1e-22)

    def test_correlated_line_total_and_moments(self):
        s=source(step(r0=(.1,.2,-.3),r1=(.7,.8,.4),t0=1e-9,t1=1.02e-9,q=4.))
        result=k.integrated(s,ALL,TIME)
        self.close(result['charge_fC'],4.)
        for x,y in zip(result['centroid_um'],[.4,.5,.05]):self.close(x,y)
        self.close(result['time_centroid_s'],1.01e-9,absolute=1e-22)

    def test_boundary_halves_without_renormalization(self):
        s=source(step(r0=(0.,0.,0.),t0=1e-9,q=8.))
        r=k.integrated(s,[[0,0,0],[math.inf]*3],[1e-9,math.inf])
        self.close(r['charge_fC'],.5)
        self.assertFalse(r['renormalized'])

    def test_disjoint_partition(self):
        s=source(step(r0=(-.1,.2,.1),r1=(.2,.7,.4),t0=.99e-9,t1=1.03e-9))
        total=0
        for xs in [(-math.inf,.05),(.05,math.inf)]:
            for ts in [(-math.inf,1.01e-9),(1.01e-9,math.inf)]:
                total+=k.integrated(s,[[xs[0],-math.inf,-math.inf],[xs[1],math.inf,math.inf]],ts)['charge_fC']
        self.close(total,1.)

    def test_segment_subdivision_equivalent(self):
        whole=source(step(r0=(.2,.3,-.1),r1=(.6,.7,.3),t0=1e-9,t1=1.02e-9,q=2.))
        split=source(step('a',(.2,.3,-.1),(.4,.5,.1),1e-9,1.01e-9,1.),
                     step('b',(.4,.5,.1),(.6,.7,.3),1.01e-9,1.02e-9,1.))
        xyz=[.41,.49,.12];window=[1.008e-9,1.012e-9]
        self.close(k.generation(whole,xyz,1.01e-9),k.generation(split,xyz,1.01e-9))
        self.close(k.average_generation(whole,xyz,window),k.average_generation(split,xyz,window))
        box=[[.1,.2,-.2],[.45,.55,.15]]
        self.close(k.integrated(whole,box,window)['charge_fC'],k.integrated(split,box,window)['charge_fC'])

    def test_zero_chord_preserves_time_interval(self):
        s=source(step(t0=1e-9,t1=1.1e-9))
        self.assertEqual(k.canonical_source(s)['steps'][0]['kind'],'point')
        self.close(k.integrated(s,ALL,TIME)['time_centroid_s'],1.05e-9,absolute=1e-22)

    def test_long_delay_narrow_window(self):
        s=source(step(t0=1e-9,t1=1e-6,q=1.))
        result=k.integrated(s,ALL,[2e-9,3e-9])
        self.close(result['charge_fC'],1e-9/(1e-6-1e-9),rel=1e-8)

    def test_density_against_independent_midpoint_u(self):
        row=step(r0=(.3,.35,.01),r1=(.5,.55,.21),t0=1e-9,t1=1.006e-9)
        xyz=[.42,.45,.11];t=1.003e-9;n=30000
        integral=math.fsum(math.exp(-sum(((xyz[j]-(row['r0_um'][j]+(i+.5)/n*(row['r1_um'][j]-row['r0_um'][j])))/.03)**2 for j in range(3))
                  -.5*((t-(row['t0_s']+(i+.5)/n*(row['t1_s']-row['t0_s'])))/2e-12)**2) for i in range(n))/n
        expected=1e-15/k.E_C*1e12*integral/(math.pi**1.5*.03**3*math.sqrt(2*math.pi)*2e-12)
        self.close(k.generation(source(row),xyz,t),expected,rel=1e-8)

    def test_be_mass_additive_under_retry_partition(self):
        s=source(step(r0=(.3,.35,.01),r1=(.5,.55,.21),t0=1e-9,t1=1.006e-9))
        xyz=[.4,.45,.11];a,b,d=1e-9,1.001e-9,1.008e-9
        total=k.average_generation(s,xyz,[a,d])*(d-a)
        split=k.average_generation(s,xyz,[a,b])*(b-a)+k.average_generation(s,xyz,[b,d])*(d-b)
        self.close(total,split)

    def test_native_render_exclusive_and_does_not_mutate(self):
        s=source(step());before=copy.deepcopy(s)
        with tempfile.TemporaryDirectory(dir=DEV) as tmp:
            p=Path(tmp)/'sources.dat';r=k.write_native(s,p)
            self.assertEqual(r['sha256'],c.sha(p))
            with self.assertRaises(FileExistsError): k.write_native(s,p)
        self.assertEqual(s,before)


class EventBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=DEV);self.addCleanup(self.tmp.cleanup)
        self.rt=Path(self.tmp.name)/'runtime';self.rt.mkdir()
        self.patch=mock.patch.object(c,'RT',self.rt);self.patch.start();self.addCleanup(self.patch.stop)
        self.request=next(r for r in c.read(c.HERE/'transport-contract.json')['requests'] if r['arm']=='H' and r['event_count']>0)
        self.run=self.rt/'transport/runs'/self.request['label'];self.run.mkdir(parents=True)
        self.rows=[]
        for tid,sid,ion,material,time in [(1,1,.1,'G4_Si',0.),(2,1,.2,'G4_Si',.01),(2,2,.3,'G4_Si',8.),(2,3,.4,'G4_SILICON_DIOXIDE',.02),(2,4,0.,'G4_Si',.03)]:
            self.rows.append(dict(event_id=0,track_id=tid,step_id=sid,particle='proton' if tid==1 else 'alpha',
                post_process='protonInelastic' if tid==1 else 'ionIoni',post_process_type=4 if tid==1 else 2,post_process_subtype=121 if tid==1 else 2,
                pre_material=material,pre_t_ns=time,post_t_ns=time,ionizing_MeV=ion,edep_MeV=ion,niel_MeV=0,
                pre_x_um=.4,pre_y_um=.4,pre_z_um=.1,post_x_um=.4,post_y_um=.4,post_z_um=.1,step_um=0,deposit_kind='point'))
        self.tracks=[dict(event_id=0,track_id=1,parent_id=0,creator_process='none',birth_token='primary'),
                     dict(event_id=0,track_id=2,parent_id=1,creator_process='protonInelastic',birth_token='token')]
        self.links=[dict(event_id=0,parent_track_id=1,parent_step_id=1,child_track_id=2,creator_process='protonInelastic',creator_type=4,creator_subtype=121,birth_token='token')]
        self.witness=dict(event_id=0,parent_track_id=1,parent_step_id=1,process='protonInelastic',process_type=4,process_subtype=121,
                          direct_child_track_ids=[2],descendant_track_ids=[2],descendant_si_ionizing_MeV=.5)
        self.refresh()

    def csv(self,name,rows):
        with (self.run/name).open('w',newline='',encoding='utf-8') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)

    def refresh(self):
        self.csv('steps.csv',self.rows);self.csv('tracks.csv',self.tracks);self.csv('birth-links.csv',self.links)
        self.csv('events.csv',[dict(event_id=0,event_complete=1,step_count=len(self.rows),track_count=len(self.tracks),ionizing_all_MeV=1.,ionizing_si_MeV=.6)])
        (self.run/'geometry-contract.json').write_bytes(c.GEOMETRY.read_bytes())
        record=dict(run_id=self.request['label'],request=self.request,runner_exit_code=0,remote_exit_code=0,collection_exit_code=0,
            input_sha256={'geometry-contract.json':c.sha(c.GEOMETRY)},output_sha256={n:c.sha(self.run/n) for n in ('steps.csv','tracks.csv','birth-links.csv','events.csv')},raw_archive={'fixture':True})
        c.write(self.run/'record.json',record,exclusive=False)
        audit=dict(schema='dram-see-v4-nuclear-closure-transport-audit-r1',passed=True,errors=[],checks={n:{'passed':True} for n in e.AUDIT_CHECKS},
            record_sha256=c.sha(self.run/'record.json'),request=self.request,run_id=self.request['label'],run_dir=str(self.run),
            audit_code_sha256=c.sha(c.HERE/'transport_audit.py'),mechanism_summary={'qualifying_witnesses':[self.witness]})
        c.write(self.rt/'audit.json',audit,exclusive=False)
        selection=dict(record=c.ref(self.run/'record.json'),audit=c.ref(self.rt/'audit.json'),event_id=0,request=self.request,
            witness={**self.witness,'window_descendant_si_ionizing_MeV':.2,'window_descendant_step_ids':[[0,2,1]]})
        self.selection=self.rt/'selected-event.json';c.write(self.selection,selection,exclusive=False)

    def test_complete_event_retains_primary_and_late_and_ledger(self):
        result=e.from_selected(self.selection);s,l=result['source'],result['ledger']
        self.assertEqual(len(s['steps']),3)
        self.assertTrue(any(x['t0_s']>4e-9 for x in s['steps']))
        self.assertTrue(any(x['provenance']['track_id']==1 for x in s['steps']))
        self.assertEqual(len(l['raw_step_ledger']),5)
        self.assertAlmostEqual(l['total_si_charge_fC'],.6*1e6/3.6*k.E_C*1e15)
        self.assertAlmostEqual(sum(l['kernel_allocation'].values()),l['total_si_charge_fC'])
        self.assertFalse(l['birth_energy_added']);self.assertFalse(l['renormalized'])

    def test_changed_raw_hash_rejected(self):
        with (self.run/'steps.csv').open('a') as stream:stream.write('\n')
        with self.assertRaisesRegex(ValueError,'member changed'):e.from_selected(self.selection)

    def test_unknown_exit_rejected(self):
        p=self.run/'record.json';v=c.read(p);v['runner_exit_code']=None;c.write(p,v,False)
        a=c.read(self.rt/'audit.json');a['record_sha256']=c.sha(p);c.write(self.rt/'audit.json',a,False)
        s=c.read(self.selection);s['record']=c.ref(p);s['audit']=c.ref(self.rt/'audit.json');c.write(self.selection,s,False)
        with self.assertRaisesRegex(ValueError,'Unknown/nonzero'):e.from_selected(self.selection)

    def test_false_lineage_rejected(self):
        self.tracks[1]['parent_id']=0;self.refresh()
        with self.assertRaisesRegex(ValueError,'birth-link'):e.from_selected(self.selection)

    def test_missing_strict_check_rejected(self):
        p=self.rt/'audit.json';a=c.read(p);a['checks'].pop('serial_affinity');c.write(p,a,False)
        s=c.read(self.selection);s['audit']=c.ref(p);c.write(self.selection,s,False)
        with self.assertRaisesRegex(ValueError,'incomplete'):e.from_selected(self.selection)

    def test_window_witness_step_binding_rejected(self):
        s=c.read(self.selection);s['witness']['window_descendant_step_ids']=[[0,2,2]];c.write(self.selection,s,False)
        with self.assertRaisesRegex(ValueError,'step IDs'):e.from_selected(self.selection)


if __name__ == '__main__':
    DEV.mkdir(parents=True,exist_ok=True)
    unittest.main(verbosity=2)
