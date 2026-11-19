"""Version dispatch boundaries only; no original mathematics suite or native task."""
import copy
import json
from pathlib import Path
import types
import unittest
from unittest.mock import patch
import source_feature_versions as D


class FixedFeatureVersions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packet_path=D.ROOT/'local_runtime/dram-see-v4/continuous/proton/source-features-s2-alpha-main-r1/source-features.json'
        cls.packet=json.loads(cls.packet_path.read_bytes())

    def test_original_alpha_full_dispatch_contract_and_explicit_proton_loader(self):
        raw=self.packet_path.read_bytes()
        result=D.verify(self.packet_path)
        self.assertEqual(result,self.packet)
        self.assertEqual(self.packet_path.read_bytes(),raw)
        info=D.version_info(result)
        self.assertEqual(info['version_id'],'v1-s2')
        self.assertEqual(info['verifier'],self.packet['implementations']['source_features.py'])
        expected=Path(self.packet['feature_contract_ref']['path']).read_bytes()
        self.assertEqual(D.contract_bytes(result),expected)
        self.assertEqual(D.contract_bytes(),expected)
        loaded=D.load_version('v1-s2',particle='proton')
        self.assertEqual(Path(loaded.__file__).resolve(),Path(info['verifier']['path']))
        self.assertTrue(callable(loaded.proton_modules))
        self.assertIn('proton_matrix',D.version_info(version_id='v1-s2',particle='proton')['dependencies'])

    def test_unknown_schema_contract_implementation_and_path_never_load(self):
        mutations=[('schema','unknown-source-features-v99'),('feature_contract_sha256','0'*64)]
        packets=[]
        for key,value in mutations:
            item=copy.deepcopy(self.packet);item[key]=value;packets.append(item)
        item=copy.deepcopy(self.packet);item['implementations']['source_features.py']['sha256']='0'*64;packets.append(item)
        item=copy.deepcopy(self.packet);item['implementations']['source_features.py']['path']='UNREGISTERED_PACKET_CODE.py';packets.append(item)
        with patch.object(D,'_load_verifier') as loader:
            for packet in packets:
                with self.assertRaisesRegex(ValueError,'[Uu]nregistered|not registered'):D.resolve_verifier(packet)
            with self.assertRaisesRegex(ValueError,'Unregistered'):D.load_version('v99',particle='proton')
            loader.assert_not_called()

    def test_live_and_backup_dependency_drift_rejected_without_modifying_files(self):
        fixed=D.registry();entry=fixed['versions'][0]
        snapshot_path=D.rooted(entry['dependency_snapshot']['repository_relative_path'])
        snapshot=json.loads(snapshot_path.read_bytes());item=snapshot['dependencies']['math']
        paths=[D.rooted(item['repository_relative_path']),snapshot_path.parent/item['backup_relative_path']]
        original_read=Path.read_bytes
        for changed in paths:
            def drift(path):
                raw=original_read(path)
                return raw+b'\n# MEMORY-ONLY UNIT MUTATION\n' if path.resolve()==changed.resolve() else raw
            before=original_read(changed)
            with patch.object(Path,'read_bytes',drift),patch.object(D,'_load_verifier') as loader:
                with self.assertRaisesRegex(ValueError,'dependency math identity changed'):D.resolve_verifier(self.packet)
                loader.assert_not_called()
            self.assertEqual(original_read(changed),before)

    def test_full_packet_equality_not_only_thirteen_values(self):
        incorrect=copy.deepcopy(self.packet);incorrect['uses_tcad_outputs']=True
        fake=types.SimpleNamespace(verify=lambda *args,**kwargs:incorrect)
        with patch.object(D,'_load_verifier',return_value=fake):
            with self.assertRaisesRegex(ValueError,'complete original packet'):D.verify(self.packet_path)


if __name__=='__main__':unittest.main()
