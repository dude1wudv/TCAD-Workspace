"""Registration changes only: real input packets, fixed paths, no native work."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import source_feature_versions as D


class VersionTwoRegistration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        runtime=D.ROOT/'local_runtime/dram-see-v4/continuous'
        cls.evidence=runtime/'proton/source-feature-registration-v2-r1'
        cls.v1_path=runtime/'proton/source-features-s2-alpha-main-r1/source-features.json'
        cls.v2_path=runtime/'proton/alpha-v2-examples-r2/g70-sn82-e3-a30/source-features.json'
        cls.v1=json.loads(cls.v1_path.read_bytes())
        cls.v2=json.loads(cls.v2_path.read_bytes())
        cls.old_project=runtime/'device/UNIT_FIXTURE_NOT_NATIVE-proton-inputs-20261017T064729Z-78c05360/actual-pure-input-recomputation-only'

    def test_01_original_v1_recomputes_once_default_and_proton_registration_remain(self):
        before=self.v1_path.read_bytes()
        self.assertEqual(D.verify(self.v1_path),self.v1)
        self.assertEqual(self.v1_path.read_bytes(),before)
        self.assertEqual(D.version_info()['version_id'],'v1-s2')
        self.assertEqual(D.contract_bytes(),Path(self.v1['feature_contract_ref']['path']).read_bytes())
        info=D.version_info(version_id='v1-s2',particle='proton')
        self.assertEqual(info['verifier'],self.v1['implementations']['source_features.py'])
        self.assertIn('proton_matrix',info['dependencies'])
        self.assertTrue(callable(D.load_version('v1-s2',particle='proton').proton_modules))

    def test_02_registered_v2_recomputes_oblique_inputs_and_selects_own_contract(self):
        before=self.v2_path.read_bytes()
        inputs={name:Path(ref['path']).read_bytes() for name,ref in self.v2['inputs'].items()}
        self.assertEqual(D.verify(self.v2_path,input_files=inputs),self.v2)
        self.assertEqual(self.v2_path.read_bytes(),before)
        info=D.version_info(self.v2)
        self.assertEqual(info['version_id'],'v2-alpha-surface')
        self.assertEqual(info['verifier'],self.v2['implementations']['source_features_v2.py'])
        self.assertEqual(D.contract_bytes(self.v2),(self.v2_path.parent/'source-feature-contract.json').read_bytes())
        self.assertFalse(self.v2['native_source_qualified'])
        self.assertFalse(self.v2['data_design']['data_design_registered'])
        self.assertEqual(len(inputs),9)

    def test_03_unknown_tampered_or_cross_particle_selector_never_loads(self):
        mutations=[]
        for key,value in [('schema','unknown'),('feature_contract_sha256','0'*64),
                          ('version_id','v99'),('particle','proton')]:
            item=copy.deepcopy(self.v2);item[key]=value;mutations.append(item)
        item=copy.deepcopy(self.v2);item.pop('version_id');mutations.append(item)
        for key,value in [('sha256','0'*64),('path','PACKET_SELECTED_UNTRUSTED_CODE.py')]:
            item=copy.deepcopy(self.v2);item['implementations']['source_features_v2.py'][key]=value;mutations.append(item)
        item=copy.deepcopy(self.v2);item['implementations']['unexpected.py']={'path':'UNTRUSTED','sha256':'0'*64};mutations.append(item)
        item=copy.deepcopy(self.v2);item['feature_contract_ref']['path']='UNTRUSTED_CONTRACT.json';mutations.append(item)
        item=copy.deepcopy(self.v2);item['feature_contract']['units']['Q_Si_fC']='pC';mutations.append(item)
        item=copy.deepcopy(self.v1);item['particle']='proton';mutations.append(item)
        item=copy.deepcopy(self.v1);item['version_id']='v2-alpha-surface';mutations.append(item)
        with patch.object(D,'_load_verifier') as loader:
            for packet in mutations:
                with self.subTest(packet_schema=packet['schema'],particle=packet['particle']):
                    with self.assertRaises(ValueError):D.resolve_verifier(packet)
            for version,particle in [('v99','alpha'),('v2-alpha-surface','proton'),('v2-alpha-surface','neutron')]:
                with self.assertRaises(ValueError):D.load_version(version,particle=particle)
            loader.assert_not_called()

    def test_04_registered_v2_live_and_preserved_dependencies_reject_drift(self):
        entry=[e for e in D.registry()['versions'] if e['version_id']=='v2-alpha-surface'][0]
        manifest=D.rooted(entry['dependency_snapshot']['repository_relative_path'])
        snapshot=json.loads(manifest.read_bytes());original_read=Path.read_bytes
        paths=[]
        for name in ('math','astar'):
            item=snapshot['dependencies'][name]
            paths += [D.rooted(item['repository_relative_path']),manifest.parent/item['backup_relative_path']]
        for changed in paths:
            def drift(path):
                raw=original_read(path)
                return raw+b'\nUNIT_MUTATION_IN_MEMORY_ONLY\n' if path.resolve()==changed.resolve() else raw
            before=original_read(changed)
            with self.subTest(path=str(changed)),patch.object(Path,'read_bytes',drift),patch.object(D,'_load_verifier') as loader:
                with self.assertRaisesRegex(ValueError,'identity changed'):D.resolve_verifier(self.v2)
                loader.assert_not_called()
            self.assertEqual(original_read(changed),before)

    def test_05_input_subset_and_full_packet_tampering_reject(self):
        with self.assertRaisesRegex(ValueError,'input subset differs'):
            D.verify(self.v2_path,input_files={'source.par':b'CHANGED_SOURCE_INPUT'})
        actual_read=Path.read_bytes
        altered=copy.deepcopy(self.v2);altered['uses_tcad_outputs']=True
        altered_raw=json.dumps(altered).encode()
        def packet_drift(path):
            return altered_raw if path.resolve()==self.v2_path.resolve() else actual_read(path)
        with patch.object(Path,'read_bytes',packet_drift):
            with self.assertRaisesRegex(ValueError,'complete original-input recomputation'):D.verify(self.v2_path)
        self.assertEqual(json.loads(self.v2_path.read_bytes()),self.v2)

    def test_06_old_binding_checks_its_own_snapshots_without_executing_code(self):
        binding=json.loads((self.old_project/'source-feature-binding.json').read_bytes())
        old=binding['source_feature_version']
        names={'verifier':'source-feature-verifier-snapshot.py','dispatcher':'source-feature-dispatcher-snapshot.py',
               'registry':'source-feature-registry-snapshot.json','dependency_manifest':'source-feature-dependencies-snapshot.json'}
        saved={name:(self.old_project/file).read_bytes() for name,file in names.items()}
        current=D.version_info(self.v1)
        self.assertNotEqual(old['dispatcher']['sha256'],current['dispatcher']['sha256'])
        self.assertNotEqual(old['registry']['sha256'],current['registry']['sha256'])
        with patch.object(D,'_load_verifier') as loader:
            result=D.verify_version_snapshot(old,saved,self.v1)
            self.assertEqual(result['identity_source'],'historical_binding_snapshots')
            self.assertEqual(result['dispatcher_sha256'],old['dispatcher']['sha256'])
            self.assertFalse(result['snapshot_code_executed'])
            for packet in (self.v1,self.v2):
                info=D.version_info(packet)
                snapshots={name:Path(info[name]['path']).read_bytes() for name in names}
                result=D.verify_version_snapshot(info,snapshots,packet)
                self.assertEqual(result['identity_source'],'current_binding_snapshots')
            changed=copy.deepcopy(old);changed['dispatcher']['sha256']=current['dispatcher']['sha256']
            with self.assertRaisesRegex(ValueError,'snapshot differs'):D.verify_version_snapshot(changed,saved,self.v1)
            bad_saved=dict(saved);bad_saved['dispatcher']+=b'\nUNTRUSTED_SNAPSHOT_CODE\n'
            changed=copy.deepcopy(old);changed['dispatcher']['sha256']=D.sha(bad_saved['dispatcher'])
            with self.assertRaisesRegex(ValueError,'Unregistered historical'):D.verify_version_snapshot(changed,bad_saved,self.v1)
            mixed=dict(saved);mixed['dispatcher']=Path(current['dispatcher']['path']).read_bytes()
            changed=copy.deepcopy(old);changed['dispatcher']=dict(current['dispatcher'])
            with self.assertRaisesRegex(ValueError,'Unregistered historical'):D.verify_version_snapshot(changed,mixed,self.v1)
            loader.assert_not_called()

    def test_07_original_registration_all_dependencies_and_packets_preserved(self):
        before=json.loads((self.evidence/'preserved-before.json').read_bytes())
        for path,digest in before.items():self.assertEqual(D.sha(Path(path).read_bytes()),digest,path)
        original=json.loads((self.evidence/'before/source-feature-versions.json').read_bytes())
        self.assertEqual(D.registry()['versions'][0],original['versions'][0])
        self.assertEqual(D.registry()['default_version'],original['default_version'])
        self.assertEqual(len(D.version_info(version_id='v1-s2')['dependencies']),11)
        compatibility=D.semantic_compatibility()
        self.assertFalse(compatibility['automatic_data_or_native_admission'])
        for packet in (self.v1,self.v2):
            self.assertEqual(compatibility['feature_order'],packet['feature_contract']['feature_order'])
            self.assertEqual(compatibility['units'],packet['feature_contract']['units'])
            self.assertEqual(packet['r0_um'],compatibility['alpha_mixed_version_conditions']['r0_um'])
            self.assertEqual(packet['epoch_s'],compatibility['alpha_mixed_version_conditions']['epoch_s'])


if __name__=='__main__':unittest.main()
