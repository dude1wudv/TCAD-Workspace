"""New proton version wiring only; mathematical fixtures are never native runs."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import source_features_proton_v2 as S

F=S.F;T=S.B.T;G=T.G


class MultiConditionProtonCandidate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence=F.RUNTIME/'proton-v2-candidate-r1'
        cls.work=Path(tempfile.mkdtemp(prefix='UNIT_INPUT_ONLY_NOT_NATIVE-',dir=cls.evidence))
        cls.d3=F.ROOT/'local_runtime/dram-see-v4/continuous/device/projects/20261017T080307Z-v4-continuous-b1-d3-r3'
        cls.base=F.read(cls.d3/'model.proposed.json')
        (cls.work/'meaning.json').write_bytes(F.encoded(dict(native=False,synthetic_mathematical_inputs=True,not_training_data=True)))

    @classmethod
    def fixture(cls,gate,sn):
        model=copy.deepcopy(cls.base);model['geometry']['gate_top_depth_nm']=gate;model['doping']['sn_junction_depth_nm']=sn
        return model,F.G.describe_geometry(model,3)

    def test_01_all_nine_input_models_propagate_to_separate_headers_and_probes(self):
        digests=set()
        for gate in (70,80,90):
            for sn in (82,87,92):
                with self.subTest(gate=gate,sn=sn):
                    model,geometry=self.fixture(gate,sn)
                    contract,header,probes=G.construct(F.encoded(model),F.encoded(geometry),'UNIT_MODEL_NOT_NATIVE','UNIT_GEOMETRY_NOT_NATIVE')
                    self.assertEqual(contract['geometry'],geometry)
                    self.assertEqual(contract['device_parameters']['gate_top_depth_nm'],gate)
                    self.assertEqual(contract['device_parameters']['sn_junction_depth_nm'],sn)
                    self.assertIn(('const double gate_top='+format(gate/1000,'.17g')+';').encode(),header)
                    self.assertIn(F.sha(F.encoded(contract)).encode(),header)
                    self.assertIn((format(gate/1000-.001,'.17g')+' ').encode(),probes)
                    self.assertIn((format(gate/1000+.001,'.17g')+' ').encode(),probes)
                    self.assertEqual(geometry['doping']['a_sn_um'],sn/1000/(F.G.math.log(1450)**.5))
                    digests.add(F.sha(header))
        self.assertEqual(len(digests),9)
        low,_=self.fixture(70,82);high,_=self.fixture(90,92)
        self.assertEqual(F.G.material_at(low,.001,.001,.075),'GateVoid')
        self.assertEqual(F.G.material_at(high,.001,.001,.075),'SiO2')

    def test_02_wrong_geometry_or_doping_is_not_admitted_under_a_new_label(self):
        model,geometry=self.fixture(70,82)
        _,wrong=self.fixture(80,87)
        with self.assertRaisesRegex(ValueError,'D3 physical geometry/doping'):G.validate(model,wrong)
        changed=copy.deepcopy(geometry);changed['doping']['a_sn_um']=wrong['doping']['a_sn_um']
        with self.assertRaisesRegex(ValueError,'D3 physical geometry/doping'):G.validate(model,changed)
        changed=copy.deepcopy(model);changed['geometry']['active_width_nm']=40
        with self.assertRaisesRegex(ValueError,'material geometry'):G.validate(changed,geometry)

    def test_03_exact_original_matrix_and_all_holdouts_remain_protected(self):
        rows=F.B.conditions();self.assertEqual(len(rows),12)
        admitted=[];protected=[]
        for row in rows:
            seed=int(row['proposed_seeds'].split('|')[0])
            self.assertEqual(T.condition(row['condition_id'],seed),row)
            if row['split']=='train':
                self.assertEqual(T.condition(row['condition_id'],seed,development=True),row);admitted.append(row['condition_id'])
            else:
                with self.assertRaisesRegex(ValueError,'Final holdout'):T.condition(row['condition_id'],seed,development=True)
                protected.append(row['condition_id'])
        self.assertEqual(admitted,['proton-T01','proton-T02','proton-T03','proton-T04','proton-T05','proton-T06'])
        self.assertIn('proton-I01',protected);self.assertIn('proton-I02',protected)
        with self.assertRaisesRegex(ValueError,'Seed'):T.condition('proton-T03',61017081,development=True)
        with self.assertRaisesRegex(ValueError,'Unknown'):T.condition('RENAMED_FINAL',61017081,development=True)

    def test_04_candidate_build_reuses_actual_original_cpp_but_binds_real_d3_input_bytes(self):
        output=self.work/'build-g80-sn87-INPUTS_ONLY'
        T.prepare_build(self.d3/'model.proposed.json',self.d3/'geometry-contract.json',output)
        self.assertEqual(F.sha((output/'transport_bcat.cc').read_bytes()),F.ORIGINAL_FILES['transport_bcat.cc'])
        self.assertEqual((output/'device-geometry-contract.json').read_bytes(),(self.d3/'geometry-contract.json').read_bytes())
        semantic=G.validate_files(output)
        self.assertEqual((semantic['gate_top_depth_nm'],semantic['sn_junction_depth_nm']),(80,87))
        manifest=F.read(output/'input-manifest.json')
        self.assertFalse(manifest['solver_dispatched']);self.assertFalse(manifest['compiled']);self.assertFalse(manifest['native_qualified'])
        self.assertEqual((output/'task.sh').read_bytes(),(F.ORIGINAL_BUILD/'collected/task.sh').read_bytes())
        self.assertFalse((output/'transport_bcat').exists())
        with self.assertRaisesRegex(ValueError,'New candidate directory'):T.prepare_build(self.d3/'model.proposed.json',self.d3/'geometry-contract.json',output)
        (self.work/'prepared-build-path.txt').write_text(str(output),encoding='utf-8')

    def test_05_new_geometry_path_retains_point_late_and_zero_source_math(self):
        def step(sid,material,ion,time_ns):
            return dict(event_id='0',track_id='1',step_id=str(sid),parent_id='0',particle='proton',deposit_kind='point_zero_length',
                pre_material=material,edep_MeV=str(ion),niel_MeV='0',ionizing_MeV=str(ion),
                pre_x_um='-.1',pre_y_um='0',pre_z_um='.3',post_x_um='-.1',post_y_um='0',post_z_um='.3',
                pre_t_ns=str(time_ns),post_t_ns=str(time_ns))
        rows=[step(1,'G4_Si',.001,15),step(2,'G4_Si',0.,0),step(3,'G4_SILICON_DIOXIDE',.002,20)]
        sources,ledger=F.C.source_rows_from_steps(rows,0,15e-9)
        self.assertEqual(ledger['all_event_steps'],3);self.assertEqual(len(sources),1)
        self.assertEqual(sources[0][:3],sources[0][3:6]);self.assertGreater(sources[0][6],19.9e-9)
        fragments=F.C.represent(sources);self.assertEqual(len(fragments),1)
        self.assertEqual(fragments[0]['source_charge_fC'],sources[0][8])
        model,geometry=self.fixture(70,82);summary=S.pure_moments(sources,model,geometry)
        values=summary['source_features'];self.assertEqual(values['source_present'],1)
        self.assertGreater(values['M_t_fC_ps']/values['Q_Si_fC'],14999.)
        self.assertTrue(summary['all_late_rows_retained']);self.assertFalse(summary['native_source_qualified'])
        zero=S.pure_moments([],model,geometry)
        self.assertEqual(set(zero['source_features'].values()),{0.})
        self.assertTrue(all(value is None for value in zero['interpretation'].values()))
        model2,geometry2=self.fixture(70,92)
        same=S.pure_moments(sources,model2,geometry2)
        self.assertEqual(summary['source_features'],same['source_features'])
        self.assertNotEqual(summary['device_parameters']['sn_junction_depth_nm'],same['device_parameters']['sn_junction_depth_nm'])

    def test_06_no_old_s2_build_or_missing_original_event_becomes_v2_native_evidence(self):
        with self.assertRaises((ValueError,FileNotFoundError)):T.audit_build(F.ORIGINAL_BUILD)
        with self.assertRaises(FileNotFoundError):S.B.audit_transport_event(self.work/'MISSING_NATIVE_EVENT',0,F.ORIGINAL_BUILD)
        bad=self.work/'unknown-packet.json';bad.write_bytes(F.encoded(dict(schema='continuous-particle-source-features-v2',version_id='v2-proton-bcat',particle='alpha')))
        with self.assertRaisesRegex(ValueError,'Unknown'):S.verify(bad)
        model,geometry=self.fixture(80,87)
        with self.assertRaisesRegex(ValueError,'origin/epoch'):S.pure_moments([],model,geometry,epoch_s=16e-9)
        with self.assertRaisesRegex(ValueError,'record/kernel'):S.pure_moments([[0.]*11],model,geometry)

    def test_07_frozen_versions_registry_cpp_and_original_helpers_are_unchanged(self):
        before=F.read(self.evidence/'frozen-before.json')
        for path,item in before.items():self.assertEqual(F.sha(Path(path).read_bytes()),item['sha256'],path)
        contract=F.parse(S.contract_bytes())
        self.assertFalse(contract['registered_in_current_dispatcher'])
        self.assertFalse(contract['native_source_qualified'])
        self.assertEqual(F.read(HERE/'source-feature-versions.json')['default_version'],'v1-s2')
        self.assertEqual(len(F.read(HERE/'source-feature-versions.json')['versions']),2)


HERE=Path(__file__).resolve().parent
if __name__=='__main__':unittest.main()
