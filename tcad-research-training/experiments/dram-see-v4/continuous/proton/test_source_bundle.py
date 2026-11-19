"""New request/ancestry binding checks only; fabricated rows are unit fixtures."""
import copy
import unittest
import source_bundle as B


class SourceBundleContract(unittest.TestCase):
    def fixture(self):
        tracks=[];steps=[]
        for tid,parent,energy,niel,creator,kind,token in [(1,0,.01,.002,'none',-1,'primary'),(2,1,.005,.001,'protonInelastic',4,'e0:t1:s1:n1')]:
            track=dict(event_id='0',track_id=str(tid),parent_id=str(parent),particle='proton' if tid==1 else 'Si28',
                pdg='2212' if tid==1 else '1000140280',creator_process=creator,creator_type=str(kind),creator_subtype='-1' if tid==1 else '121',
                step_count='1',birth_token=token,parent_step_id='0' if tid==1 else '1',
                direct_hadronic_child=str(int(tid==2)),creator_lineage_hadronic=str(int(tid==2)),em_from_hadronic_lineage='0',
                em_from_post_hadronic_primary='0',em_in_primary_hadronic_transition_step='0')
            for scope in ('all','si'):
                for field,value in [('edep',energy),('niel',niel),('ionizing',energy-niel)]:track[field+'_'+scope+'_MeV']=str(value)
            tracks.append(track)
            step=dict(event_id='0',track_id=str(tid),step_id='1',parent_id=str(parent),particle=track['particle'],pdg=track['pdg'],
                edep_MeV=str(energy),niel_MeV=str(niel),ionizing_MeV=str(energy-niel),pre_t_ns='0',post_t_ns='0.001',
                pre_material='G4_Si',pre_volume='R.Silicon',post_process_type='4' if tid==1 else '2',
                track_hadronic_before='0',track_hadronic_after='1' if tid==1 else '0',
                primary_hadronic_seen_before='0' if tid==1 else '1',primary_hadronic_seen_after='1',secondary_count='1' if tid==1 else '0')
            step.update({side+'_'+axis+'_um':'0' for side in ('pre','post') for axis in 'xyz'});steps.append(step)
        event=dict(event_id='0',event_complete='1',primary_count='1',track_count='2',step_count='2',si_step_count='2')
        for scope in ('all','si','world'):
            for field,value in [('edep',.015),('niel',.003),('ionizing',.012)]:event[field+'_'+scope+'_MeV']=str(0 if scope=='world' else value)
        births=[dict(event_id='0',birth_token='e0:t1:s1:n1',parent_track_id='1',parent_step_id='1',secondary_ordinal='1',child_track_id='2',
                     creator_process='protonInelastic',creator_type='4',creator_subtype='121',parent_hadronic_before='0',parent_hadronic_after='1')]
        return event,tracks,steps,births

    def test_only_s2_training_conditions_in_current_prepare_entry(self):
        for cid,seed in [('proton-T03',61017031),('proton-T04',61017041),('proton-T06',61017061)]:
            self.assertEqual(B.condition(cid,seed,True)['split'],'train')
        for cid,seed in [('proton-I02',61017081),('proton-E01',61017111)]:
            with self.assertRaisesRegex(ValueError,'holdout'):B.condition(cid,seed,True)
        for cid,seed in [('proton-T01',61017011),('proton-C01',61017121)]:
            with self.assertRaisesRegex(ValueError,'S2 only'):B.condition(cid,seed,True)

    def test_compiled_s2_semantics_cannot_be_renamed(self):
        folder=B.COMPILED/'collected'
        geometry=B.read_json(folder/'geometry-contract.json');model=B.read_json(folder/'model-input.json')
        self.assertEqual(B.validate_s2_geometry(geometry,model)['sn_junction_depth_nm'],87.)
        wrong=copy.deepcopy(model);wrong['geometry']['gate_top_depth_nm']=90
        with self.assertRaisesRegex(ValueError,'semantic'):B.validate_s2_geometry(geometry,wrong)
        wrong=copy.deepcopy(model);wrong['doping']['sn_junction_depth_nm']=82
        with self.assertRaisesRegex(ValueError,'semantic'):B.validate_s2_geometry(geometry,wrong)

    def test_native_beam_is_bound_to_surface_target(self):
        request=dict(theta_deg=30.,phi_deg=180.,target_um=[-.052,0.,0.],label='unit-fixture-not-native')
        metadata=dict(surface_position_um=[-.052,0.,0.],beam_direction=[-.5,0.,3**.5/2],
                      beam_position_um=[-.052+1/3**.5,0.,-1.],request_label=request['label'])
        self.assertEqual(B.native_beam(request,metadata)['beam_start_um'][2],-1.)
        wrong=copy.deepcopy(metadata);wrong['beam_direction'][0]=.5
        with self.assertRaisesRegex(ValueError,'beam setup'):B.native_beam(request,wrong)
        wrong=copy.deepcopy(metadata);wrong['request_label']='different-fixture'
        with self.assertRaisesRegex(ValueError,'label'):B.native_beam(request,wrong)

    def test_full_native_birth_chain_zero_length_retained(self):
        result=B.ancestry(*self.fixture())
        self.assertEqual(result['track_count'],2);self.assertEqual(result['step_count'],2)
        self.assertEqual(result['birth_link_count'],1);self.assertEqual(result['zero_length_positive_si_steps'],2)
        self.assertEqual(result['lineage'][1]['ancestor_track_ids'],[1])
        self.assertTrue(result['lineage'][1]['has_hadronic_creator_ancestry'])

    def test_missing_birth_wrong_parent_and_energy_rejected(self):
        event,tracks,steps,births=self.fixture()
        with self.assertRaisesRegex(ValueError,'one actual birth'):B.ancestry(event,tracks,steps,[])
        bad=copy.deepcopy(tracks);bad[1]['parent_id']='2'
        with self.assertRaises(ValueError):B.ancestry(event,bad,steps,births)
        bad=copy.deepcopy(steps);bad[1]['ionizing_MeV']='.005'
        with self.assertRaisesRegex(ValueError,'energy split'):B.ancestry(event,tracks,bad,births)

    def test_birth_ordinal_and_process_history_cannot_be_filled(self):
        event,tracks,steps,births=self.fixture()
        bad=copy.deepcopy(births);bad[0]['secondary_ordinal']='2'
        with self.assertRaisesRegex(ValueError,'birth token'):B.ancestry(event,tracks,steps,bad)
        bad=copy.deepcopy(steps);bad[0]['post_process_type']='2'
        with self.assertRaisesRegex(ValueError,'process history'):B.ancestry(event,tracks,bad,births)


if __name__=='__main__':unittest.main()
