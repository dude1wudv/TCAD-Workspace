"""Focused input-only tests. No native solver or fabricated successful D3."""
import copy
import io
import json
from pathlib import Path
import tarfile
import unittest
import uuid
from unittest import mock

import case_contract
import geometry_bridge as bridge
import mesh_continuation as mesh

ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT/'local_runtime/runs/20261017T124649Z-v4-continuous-b1-d3-r9'
OUT = ROOT/'local_runtime/dram-see-v4/continuous/device/d3-mesh-continuation-design-r1'


class MeshContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Reuse the already verified real archive. This fixture construction does
        # not repeat the complete archive/index audit; source_package performed it
        # in the recorded real-prefix audit before these new boundary checks.
        cls.request = dict(schema=case_contract.SCHEMA_MESH_REUSE,kind='dc',dimension=3,
            gate_top_depth_nm=80,sn_junction_depth_nm=87,variant='main',
            mesh_policy=case_contract.GRADIENT_MESH_R6,mesh_source_run=str(SOURCE))
        with tarfile.open(str(SOURCE/'results.tar'),'r:*') as archive:
            listing = mesh.members(archive)
            get = lambda name:mesh.raw_member(archive,listing,name)
            index_raw = get('_collection-members.json'); index = mesh.obj(index_raw)
            original_input_raw = (SOURCE/'inputs.tar').read_bytes()
            manifest_raw = (SOURCE/'manifest.json').read_bytes(); manifest = mesh.obj(manifest_raw)
            original_inputs = mesh.original_inputs(original_input_raw,manifest)
            files = {name:original_inputs[name] for name in mesh.IDENTICAL_INPUTS}
            files.update({mesh.PREFIX+name:get(name) for name in mesh.PROOF_MEMBERS})
            files.update({mesh.PREFIX+'manifest.json':manifest_raw,mesh.PREFIX+'inputs.tar':original_input_raw,
                          mesh.PREFIX+'_collection-members.json':index_raw})
            for name in mesh.IMPORTED_OUTPUTS:
                if name != 'cell_msh.tdr':files[name]=get(name)
        cls.binding = dict(schema=mesh.SCHEMA,origin='native_pipeline',synthetic=False,source_run_id=SOURCE.name,
            source_run_directory=str(SOURCE),source_manifest_sha256=mesh.sha(manifest_raw),
            source_archive_sha256='186f477331ad8a0a0a929a2c3ab84d2f877d64277fb9df79383e9c369429bc39',
            source_archive_size_bytes=75458560,source_inputs_archive_sha256=mesh.sha(original_input_raw),
            source_collection_index_sha256=mesh.sha(index_raw),source_input_manifest_sha256=mesh.sha(original_inputs['input-manifest.json']),
            inherited_step_indices=[1,2],actual_step_indices=[3,4,5,6],source_remote_exit_code=255,source_state='FAILED_COLLECTED',
            identical_inputs_sha256={name:mesh.sha(original_inputs[name]) for name in mesh.IDENTICAL_INPUTS},
            imports={name:dict(member=name,sha256=index[name]['sha256'],size_bytes=index[name]['size']) for name in mesh.IMPORTED_OUTPUTS},
            proofs_sha256={name:mesh.sha(raw) for name,raw in files.items() if name.startswith(mesh.PREFIX)},
            mesh_sha256=index['cell_msh.tdr']['sha256'],mesh_size_bytes=index['cell_msh.tdr']['size'],
            interpretation='Inherited successful native prefix only; no completed geometry or electrical qualification')
        files['mesh-source-binding.json']=mesh.json_bytes(cls.binding)
        cls.files=files
        cls.cfg=mesh.obj(original_inputs['project.json'])['s2_geometry']
        cls.cfg.update(mode='produce_from_mesh',run_id='UNIT_FIXTURE_NOT_NATIVE-prefix-continuation',
                       producer_run_id='UNIT_FIXTURE_NOT_NATIVE-prefix-continuation',
                       mesh_source_binding_sha256=mesh.sha(files['mesh-source-binding.json']))

    def verify(self,files=None,request=None,cfg=None):
        files=self.files if files is None else files
        hashes={name:mesh.sha(raw) for name,raw in files.items()}
        hashes['cell_msh.tdr']=self.binding['mesh_sha256']
        return mesh.verify_packet(files.__getitem__,hashes.__getitem__,self.cfg if cfg is None else cfg,
                                  self.request if request is None else request)

    def test_original_prefix_binding_and_closed_request(self):
        self.assertEqual(case_contract.validate(self.request),self.request)
        self.assertEqual(self.verify(),self.binding)
        self.assertEqual(self.binding['source_remote_exit_code'],255)
        self.assertNotIn('step-001-sde-exit-code.txt',self.files)
        self.assertNotIn('geometry-validation.json',self.files)
        bad=dict(self.request,command='snmesh')
        with self.assertRaisesRegex(ValueError,'Unknown'):case_contract.validate(bad)
        for key,value in (('sn_junction_depth_nm',82),('gate_top_depth_nm',70),('variant','mesh')):
            bad=dict(self.request);bad[key]=value
            with self.assertRaisesRegex(ValueError,'cannot change'):self.verify(request=bad)

    def test_changed_science_or_coherently_rehashed_capture_rejected(self):
        files=dict(self.files);files['device.cmd']+=b'\n'
        with self.assertRaisesRegex(ValueError,'scientific input changed'):self.verify(files)
        files=dict(self.files);name=mesh.PREFIX+'step-002-snmesh-process-observation.json'
        row=mesh.obj(files[name]);row['observed_threads']='2';files[name]=mesh.json_bytes(row)
        binding=copy.deepcopy(self.binding);binding['proofs_sha256'][name]=mesh.sha(files[name])
        files['mesh-source-binding.json']=mesh.json_bytes(binding)
        cfg=dict(self.cfg,mesh_source_binding_sha256=mesh.sha(files['mesh-source-binding.json']))
        with self.assertRaisesRegex(ValueError,'proof/index mismatch'):self.verify(files,cfg=cfg)

    def test_stage_uses_frozen_manifest_and_imports_no_current_prefix_exits(self):
        folder=OUT/('UNIT_FIXTURE_NOT_NATIVE-staged-original-prefix-'+uuid.uuid4().hex[:12])
        folder.mkdir(exist_ok=False)
        for name,raw in self.files.items():
            p=folder/name;p.parent.mkdir(exist_ok=True,parents=True);p.write_bytes(raw)
        (folder/'controlled-request.json').write_bytes(mesh.json_bytes(self.request))
        (folder/'INPUT_INHERITANCE_ONLY_NOT_A_NATIVE_RUN.txt').write_text('Only inherited original r9 bytes; no current native result.\n')
        original_read=Path.read_bytes
        def no_mutable_manifest(path):
            if path == SOURCE/'manifest.json':raise AssertionError('Staging reopened the mutable original manifest')
            return original_read(path)
        with mock.patch.object(mesh,'source_package',side_effect=AssertionError('Staging repeated full source audit')), \
                mock.patch.object(Path,'read_bytes',no_mutable_manifest):
            mesh.stage(folder,self.cfg)
        self.assertEqual((folder/(mesh.PREFIX+'manifest.json')).read_bytes(),self.files[mesh.PREFIX+'manifest.json'])
        self.assertEqual(mesh.file_sha(folder/'cell_msh.tdr'),self.binding['mesh_sha256'])
        sources=bridge.geometry_exit_sources(folder,complete=False)
        for row in sources.values():
            self.assertEqual(row['source_kind'],'inherited_original_native_prefix')
            self.assertEqual(row['source_run_id'],SOURCE.name)
        (folder/'step-001-sde-exit-code.txt').write_bytes(b'0\n')
        with self.assertRaisesRegex(ValueError,'masquerade'):mesh.verify_folder(folder,self.cfg)
        # Preserve this rejected injected file in this clearly labelled fixture.
        bridge.geometry_validate_parameter_contract(folder,self.cfg,self.request,mesh.obj(self.files['model.proposed.json']))

    def test_incomplete_source_cannot_be_a_successful_composite(self):
        manifest=mesh.obj(self.files[mesh.PREFIX+'manifest.json'])
        with self.assertRaisesRegex(ValueError,'no completed'):mesh.validate_completed(None,None,manifest,self.cfg,b'')
        bad=copy.deepcopy(manifest);bad.update(state='COLLECTED',remote_exit_code=0)
        with self.assertRaisesRegex(ValueError,'only four actual'):mesh.validate_completed(None,None,bad,self.cfg,b'')

    def test_current_hash_provider_requires_actual_safe_provider_fields(self):
        fields=['schema','source_path','source_sha256','source_bytes','tcl_patchlevel','package_name','package_version',
                'backend','safe_interpreter','unsafe_commands_visible','package_unknown_empty','known_vectors_verified',
                'chunk_bytes','maximum_supported_file_bytes','algorithm_representation_limit_not_resource_quota']
        values=['dram-see-v4-tdx-sha256-provider-r1',
            '/usr/synopsys/sentaurus/W-2024.09/tcad/W-2024.09/lib/tcllib1.16/sha1/sha256.tcl',
            '107ef278e9752467718d0cfaf7dac868f31b7c91ff80fbc4700a07eac939dee1','24595','8.6.12','sha256','1.0.3',
            'tcl','1','','1','empty abc','65536','536870911','1']
        raw=(','.join(fields)+'\n'+','.join(values)+'\n').encode()
        self.assertEqual(bridge.geometry_validate_hash_provider(raw)['backend'],'tcl')
        with self.assertRaisesRegex(ValueError,'provider evidence'):bridge.geometry_validate_hash_provider(raw.replace(b',tcl,1,',b',exec,1,'))


if __name__=='__main__':unittest.main(verbosity=2)
