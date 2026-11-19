"""Synthetic offline counterexamples. No generated row represents a Geant4 run."""
import copy
import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('audit_witness',HERE.parent/'audit_witness.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)


def csv_file(folder,name,rows,columns=None):
    with (folder/name).open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns or list(rows[0]))
        writer.writeheader();writer.writerows(rows)


def fixture():
    def step(tid,parent,sid,particle,pdg,y0,y1,t0,t1,ke0,ke1,edep,process,kind,sub,
             secondary=0,before=0,after=0,volume='Si',length=None):
        row=dict(event_id=0,track_id=tid,parent_id=parent,step_id=sid,particle=particle,pdg=pdg,
                 step_um=abs(y1-y0) if length is None else length,edep_MeV=edep,niel_MeV=0.,ionizing_MeV=edep,
                 post_process=process,post_process_type=kind,post_process_subtype=sub,
                 primary_hadronic_seen_before=int(tid>1 or before),primary_hadronic_seen_after=int(tid>1 or after),
                 neutron_tracking_cut_step=0,pre_step_status=7 if sid==1 else 4,post_step_status=4,
                 chord_um=abs(y1-y0),track_hadronic_before=before,track_hadronic_after=after,secondary_count=secondary)
        for prefix,y,time,ke in [('pre_',y0,t0,ke0),('post_',y1,t1,ke1)]:
            row.update({prefix+'x_um':0.,prefix+'y_um':y,prefix+'z_um':0.,prefix+'dx':0.,prefix+'dy':1.,prefix+'dz':0.,
                        prefix+'ke_MeV':ke,prefix+'t_ns':time,prefix+'volume':volume,prefix+'material':'G4_Si' if volume=='Si' else 'G4_Galactic'})
        row['deposit_kind']='zero_ionizing' if edep==0 else 'point_zero_length' if row['step_um']==0 else 'point_zero_chord' if y0==y1 else 'finite_path'
        row['local_ionizing_MeV_per_um']=edep/row['step_um'] if row['step_um'] else None
        return row
    steps=[step(1,0,1,'proton',2212,-5001,-5000,0,1,100,100,0,'Transportation',1,91,volume='World'),
           step(1,0,2,'proton',2212,-5000,-4999,1,2,100,90,1,'protonInelastic',4,121,secondary=2,after=1),
           step(1,0,3,'proton',2212,-4999,-4998,2,3,90,0,1,'hIoni',2,2,secondary=1,before=1,after=1),
           step(2,1,1,'alpha',1000020040,-4999,-4998,2,3,5,0,2,'ionIoni',2,2,secondary=1),
           step(3,2,1,'e-',11,-4998,-4998,2.5,3,1,0,.1,'eIoni',2,2),
           step(4,1,1,'e-',11,-4998,-4997,2.5,3,1,0,.2,'eIoni',2,2),
           step(5,1,1,'e-',11,-4999,-4999,1.5,2,1,0,.3,'eIoni',2,2,length=1)]
    steps[0]['post_volume']='Si';steps[0]['post_material']='G4_Si';steps[0]['post_step_status']=1
    links=[]
    for parent,sid,ordinal,child,creator,ctype,csub,before,after in [
        (1,2,1,2,'protonInelastic',4,121,0,1),(1,2,2,5,'hIoni',2,2,0,1),
        (1,3,1,4,'hIoni',2,2,1,1),(2,1,1,3,'ionIoni',2,2,0,0)]:
        links.append(dict(event_id=0,birth_token=f'e0:t{parent}:s{sid}:n{ordinal}',parent_track_id=parent,parent_step_id=sid,
            secondary_ordinal=ordinal,child_track_id=child,creator_process=creator,creator_type=ctype,creator_subtype=csub,
            parent_hadronic_before=before,parent_hadronic_after=after))
    tracks=[]
    for tid in range(1,6):
        group=[s for s in steps if s['track_id']==tid];first,last=group[0],group[-1]
        link=next((b for b in links if b['child_track_id']==tid),None)
        row=dict(event_id=0,track_id=tid,parent_id=first['parent_id'],particle=first['particle'],pdg=first['pdg'],charge_e=2. if tid==2 else 1.,
            Z=0,A=0,mass_MeV=1.,creator_process=link['creator_process'] if link else 'none',creator_type=link['creator_type'] if link else -1,
            creator_subtype=link['creator_subtype'] if link else -1,track_length_um=sum(s['step_um'] for s in group),step_count=len(group),
            end_track_status=2,ended_by_neutron_tracking_cut=0,birth_token=link['birth_token'] if link else 'primary',parent_step_id=link['parent_step_id'] if link else 0,
            direct_hadronic_child=int(tid==2),creator_lineage_hadronic=int(tid in (2,3)),em_from_hadronic_lineage=int(tid==3),
            em_from_post_hadronic_primary=int(tid==4),em_in_primary_hadronic_transition_step=int(tid==5),
            termination_process=last['post_process'],termination_process_type=last['post_process_type'],termination_process_subtype=last['post_process_subtype'],
            termination_reason='natural_stop_or_absorption')
        for dest,src,st in [('birth_','pre_',first),('end_','post_',last)]:
            for suffix in ('ke_MeV','x_um','y_um','z_um','dx','dy','dz','t_ns','volume','material'):row[dest+suffix]=st[src+suffix]
        for region,ss in [('all',group),('si',[s for s in group if s['pre_volume']=='Si'])]:
            for field in ('edep','niel','ionizing'):row[field+'_'+region+'_MeV']=sum(s[field+'_MeV'] for s in ss)
        tracks.append(row)
    e=dict(event_id=0,primary_count=1,track_count=5,step_count=7,si_step_count=6,world_step_count=1,hadronic_step_count=1,primary_hadronic_step_count=1,
           primary_first_hadronic_step=2,primary_first_hadronic_process='protonInelastic',primary_first_hadronic_t_ns=2.,
           si_ionizing_primary_before_hadronic_MeV=0.,si_ionizing_primary_at_or_after_hadronic_MeV=2.,si_ionizing_nonprimary_MeV=2.6,
           neutron_tracking_cut_steps=0,neutron_tracking_cut_tracks=0,zero_si_ionizing=0,event_complete=1)
    for region,ss in [('all',steps),('si',[s for s in steps if s['pre_volume']=='Si']),('world',[s for s in steps if s['pre_volume']=='World'])]:
        for field in ('edep','niel','ionizing'):e[field+'_'+region+'_MeV']=sum(s[field+'_MeV'] for s in ss)
    processes=[]
    for particle,pdg,name,ptype,sub in [('proton',2212,'Transportation',1,91),('proton',2212,'protonInelastic',4,121),
                                     ('proton',2212,'hIoni',2,2),('alpha',1000020040,'ionIoni',2,2),('e-',11,'eIoni',2,2),
                                     ('neutron',2112,'nKiller',7,403)]:
        processes.append(dict(particle=particle,pdg=pdg,process=name,process_type=ptype,process_subtype=sub,is_neutron_killer=int(name=='nKiller')))
    return [e],tracks,steps,links,processes


class Counterexamples(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='offline-',dir=HERE)
        self.folder=Path(self.tmp.name)
        self.events,self.tracks,self.steps,self.links,self.processes=fixture()
        self.metadata={'events_requested':1,'energy_MeV':100,'beam_position_um':[0,-5001,0],'beam_direction':[0,1,0],'arm':'H','max_step_um':100}
        self.status={'tracks_completed':5,'steps_recorded':7}
    def tearDown(self):self.tmp.cleanup()
    def write(self):
        for name,rows in [('events.csv',self.events),('tracks.csv',self.tracks),('steps.csv',self.steps),('birth-links.csv',self.links),('processes.csv',self.processes)]:
            csv_file(self.folder,name,rows)
    def audit(self):
        self.write();report={}
        records=a._events(self.folder,self.metadata,self.status,report)
        a._mechanisms(self.folder,self.metadata,records,report)
        return report
    def rejected(self,phrase=None):
        with self.assertRaises(ValueError) as caught:self.audit()
        if phrase:self.assertIn(phrase,str(caught.exception))
    def test_traceable_witness_and_all_three_lineage_categories(self):
        r=self.audit()['mechanism_summary'];self.assertTrue(r['witness_found'])
        self.assertEqual(r['qualifying_witnesses'][0]['descendant_track_ids'],[2,3])
        self.assertAlmostEqual(r['qualifying_witnesses'][0]['descendant_si_ionizing_MeV'],2.1)
        for key in ('direct_hadronic_child','em_from_hadronic_lineage','em_from_post_hadronic_primary','em_in_primary_hadronic_transition_step'):
            self.assertEqual(r['ancestry_classification_counts'][key],1)
    def test_wrong_production_step_despite_close_position(self):
        self.links[0]['parent_step_id']=3;self.rejected('token')
    def test_duplicate_child_binding(self):
        self.links.append(copy.deepcopy(self.links[0]));self.rejected('Duplicate')
    def test_missing_secondary_binding(self):
        self.links.pop();self.rejected('every secondary')
    def test_parent_state_taken_from_end_of_track(self):
        self.links[0]['parent_hadronic_before']=1;self.rejected('different step')
    def test_primary_post_interaction_em_is_not_nuclear_lineage(self):
        self.tracks[3]['creator_lineage_hadronic']=1;self.rejected('classification mismatch')
    def test_transition_step_not_claimed_strictly_after(self):
        self.tracks[4]['em_from_post_hadronic_primary']=1;self.rejected('classification mismatch')
    def test_point_deposition_preserved_without_finite_let(self):
        r=self.audit()['mechanism_summary'];self.assertEqual(r['deposition_kind_counts']['point_zero_length'],1)
        self.assertEqual(r['deposition_kind_counts']['point_zero_chord'],1)
    def test_fabricated_finite_let_for_zero_length(self):
        self.steps[4]['local_ionizing_MeV_per_um']=.1;self.rejected('fabricated')
    def test_missing_zero_deposition_step(self):
        self.steps.pop(0);self.rejected()
    def test_missing_zero_event_denominator(self):
        self.metadata['events_requested']=2;self.rejected('Event IDs')
    def test_broken_energy_sum(self):
        self.events[0]['edep_si_MeV']+=.1;self.rejected()
    def test_fake_escape_reason(self):
        self.tracks[0]['termination_reason']='escaped_world';self.rejected('Terminal reason')
    def test_unknown_process_identity(self):
        self.processes[1]['process_subtype']=122;self.rejected('registry')
    def test_nkiller_false_flag_on_proton(self):
        self.steps[2]['neutron_tracking_cut_step']=1;self.rejected()
    def test_valid_nkiller_name_does_not_require_neutron_substring(self):
        # An explicit, synthetic neutron terminal step exercises the real identity branch.
        self.tracks=[t for t in self.tracks if t['track_id']!=3]
        self.steps=[s for s in self.steps if s['track_id']!=3]
        self.links=[b for b in self.links if b['child_track_id']!=3]
        track=next(t for t in self.tracks if t['track_id']==2)
        step=next(s for s in self.steps if s['track_id']==2)
        track.update(particle='neutron',pdg=2112,charge_e=0,ended_by_neutron_tracking_cut=1,
                     termination_process='nKiller',termination_process_type=7,termination_process_subtype=403,
                     termination_reason='reference_neutron_tracking_cut')
        step.update(particle='neutron',pdg=2112,post_process='nKiller',post_process_type=7,post_process_subtype=403,
                    neutron_tracking_cut_step=1,secondary_count=0)
        self.write();report={}
        a._mechanisms(self.folder,self.metadata,(self.events,self.tracks,self.steps),report)
        self.assertEqual(report['mechanism_summary']['termination_reason_counts']['reference_neutron_tracking_cut'],1)
    def test_unknown_exit_refused_before_any_science_check(self):
        record={'schema':'dram-see-v4-witness-run-v1','run_id':'synthetic','runner_exit_code':None,'remote_exit_code':0,'collection_exit_code':0}
        (self.folder/'record.json').write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError,'Unknown/nonzero'):
            a._receipt(self.folder,{})
    def test_nonzero_exit_refused(self):
        record={'schema':'dram-see-v4-witness-run-v1','run_id':'synthetic','runner_exit_code':0,'remote_exit_code':2,'collection_exit_code':0}
        (self.folder/'record.json').write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError,'Unknown/nonzero'):
            a._receipt(self.folder,{})
    def test_msc_displaced_endpoint_can_exceed_recorded_transport_step(self):
        step=self.steps[2]
        step['step_um']=.99999
        step['local_ionizing_MeV_per_um']=step['ionizing_MeV']/step['step_um']
        self.tracks[0]['track_length_um']=2.99999
        report=self.audit()
        diag=report['mechanism_summary']['path_endpoint_diagnostics']
        self.assertEqual(diag['chord_exceeds_recorded_step_count'],1)
        self.assertGreater(diag['records'][0]['chord_over_step'],1)
    def test_corrupt_endpoint_chord_still_rejected(self):
        self.steps[2]['chord_um']+=.01;self.rejected('Endpoint chord mismatch')
    def test_recorded_charged_step_limit_still_rejected(self):
        step=self.steps[2];step['step_um']=101.;step['local_ionizing_MeV_per_um']=step['ionizing_MeV']/101.
        self.tracks[0]['track_length_um']=103.;self.rejected('exceeds explicit limit')


if __name__=='__main__':unittest.main()
