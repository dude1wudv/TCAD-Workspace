"""New representation-only input boundaries; never launch or fabricate a D3 success."""
import ast
import copy
import io
import json
from pathlib import Path
import unittest
import uuid

import case_contract
import evaluate
import geometry_bridge as bridge
import metadata_continuation as module

ROOT=Path(__file__).resolve().parents[4]
OUT=ROOT/'local_runtime/dram-see-v4/continuous/device/d3-v16-solver-recovery-r1'
R11=ROOT/'local_runtime/runs/20261017T150025Z-v4-continuous-b1-d3-r11'


class Overlay:
    def __init__(self,base,changes):self.base,self.changes=base,changes
    def read(self,name):return self.changes[name] if name in self.changes else self.base.read(name)
    def digest(self,name):return module.sha(self.changes[name]) if name in self.changes else self.base.digest(name)
    def size(self,name):return len(self.changes[name]) if name in self.changes else self.base.size(name)
    def exists(self,name):return name in self.changes or self.base.exists(name)
    def stream(self,name):return io.BytesIO(self.changes[name]) if name in self.changes else self.base.stream(name)


class ActiveSolverMeshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request=case_contract.validate(json.loads((OUT/'request-r6.json').read_text(encoding='utf-8')))
        cls.package=module.source_package(cls.request)
        cls.binding=cls.package['binding']
        cls.folder=OUT/('UNIT_FIXTURE_NOT_NATIVE-active-input-only-'+uuid.uuid4().hex[:12])
        cls.folder.mkdir()
        for name,raw in cls.package['files'].items():
            p=cls.folder/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        (cls.folder/'controlled-request.json').write_bytes(module.encoded(cls.request))
        (cls.folder/'SYNTHETIC_NOT_NATIVE').write_text('Representation input unit fixture; no current native results.\n',encoding='utf-8')
        # The copied r10 project supplies the unchanged scientific configuration.
        source=Path(cls.request['metadata_source_run'])
        with module.tarfile.open(str(source/'results.tar'),'r:*') as archive:
            reader=module.ArchiveReader(archive,module.mesh_module().members(archive))
            cls.cfg=module.obj(reader.read('project.json'))['s2_geometry']
        cls.cfg.update(mode='produce_from_metadata',run_id=cls.folder.name,producer_run_id=cls.folder.name,
            metadata_source_binding_sha256=module.sha(cls.package['files']['metadata-source-binding.json']),
            geometry_observation_backend=module.BACKEND,mesh_representation=module.ACTIVE_REPRESENTATION,
            origin_mesh_sha256=cls.binding['origin_mesh_sha256'],active_solver_mesh_sha256=cls.binding['active_solver_mesh_sha256'])
        module.stage(cls.folder,cls.cfg)
        cls.reader=module.FolderReader(cls.folder)
        (OUT/'staged-input-only.json').write_bytes(module.encoded(dict(path=str(cls.folder),
            metadata_source_binding_sha256=cls.cfg['metadata_source_binding_sha256'],origin_binding_sha256=cls.binding['origin_binding_sha256'],
            origin_mesh_sha256=cls.binding['origin_mesh_sha256'],active_solver_mesh_sha256=cls.binding['active_solver_mesh_sha256'],
            current_native_results=False)))

    def verify(self,changes=None,cfg=None,request=None):
        return module.verify(Overlay(self.reader,changes or {}),self.cfg if cfg is None else cfg,
                             self.request if request is None else request)

    def test_active_original_member_and_intact_original_graph(self):
        binding=self.verify()
        self.assertEqual(binding['schema'],module.ACTIVE_SCHEMA)
        self.assertEqual(binding['imports']['cell_msh.tdr'],dict(owner='conversion',member='mesh-v16.tdr',
            sha256=binding['active_solver_mesh_sha256'],size_bytes=binding['active_solver_mesh_size_bytes']))
        self.assertEqual(binding['imports'][module.ORIGIN_FILE]['member'],'cell_msh.tdr')
        self.assertNotEqual(self.reader.digest('cell_msh.tdr'),self.reader.digest(module.ORIGIN_FILE))
        origin=module.obj(self.reader.read(module.ORIGIN_BINDING_FILE))
        self.assertEqual(origin['mesh_sha256'],binding['origin_mesh_sha256'])
        self.assertEqual(origin['hdf5_sha256'],binding['active_solver_mesh_sha256'])
        self.assertEqual(binding['failed_step004']['exit_code'],137)
        self.assertEqual(binding['inherited_step_indices'],[1,2,3])
        self.assertFalse(any((self.folder/n).exists() for n in module.FORBIDDEN_CURRENT))
        self.assertFalse((self.folder/'geometry-validation.json').exists())

    def test_closed_request_and_no_hash_or_file_role_substitution(self):
        self.assertEqual(case_contract.validate(self.request),self.request)
        for update in ({'schema':case_contract.SCHEMA_METADATA_REUSE},{'continuation_recipe':case_contract.METADATA_RECIPE},
                       {'mesh_representation':'any_tdr'},{'active_solver_mesh_file':'arbitrary.tdr'}):
            with self.assertRaises(ValueError):case_contract.validate(dict(self.request,**update))
        with self.assertRaisesRegex(ValueError,'actual active mesh differs'):
            self.verify({'cell_msh.tdr':b'NOT_THE_NATIVE_CONVERTED_BYTES'})
        for key,value in (('origin_mesh_sha256',self.binding['active_solver_mesh_sha256']),
                          ('mesh_sha256',self.binding['origin_mesh_sha256']),('origin_mesh_file','cell_msh.tdr')):
            bad=copy.deepcopy(self.binding);bad[key]=value
            with self.assertRaisesRegex(ValueError,'exact registered r1 transform'):
                self.verify({'metadata-source-binding.json':module.encoded(bad)})

    def test_current_context_is_active_and_metadata_remains_original(self):
        context=dict(schema=evaluate.ACTIVE_HDF5_CONTEXT,mesh_representation=module.ACTIVE_REPRESENTATION,
            mesh_sha256=self.binding['active_solver_mesh_sha256'],origin_mesh_sha256=self.binding['origin_mesh_sha256'],
            active_solver_mesh_sha256=self.binding['active_solver_mesh_sha256'])
        evaluate.verify_active_context_identity(context,self.binding,self.cfg,context['mesh_sha256'])
        for key,value in (('schema',evaluate.HDF5_CONTEXT),('mesh_sha256',self.binding['origin_mesh_sha256']),
                          ('origin_mesh_sha256',self.binding['active_solver_mesh_sha256'])):
            with self.assertRaisesRegex(ValueError,'confused original and actual'):
                evaluate.verify_active_context_identity(dict(context,**{key:value}),self.binding,self.cfg,
                                                        self.binding['active_solver_mesh_sha256'])
        status=module.obj(self.reader.read('tdr-region-status.json'))
        self.assertEqual(status['original_mesh_sha256'],self.binding['origin_mesh_sha256'])
        with self.assertRaisesRegex(ValueError,'inherited member changed'):
            self.verify({'tdr-region-status.json':module.encoded(dict(status,original_mesh_sha256=self.binding['active_solver_mesh_sha256']))})

    def test_affected_original_r5_still_verifies_and_cannot_opt_in_silently(self):
        folder=ROOT/'local_runtime/dram-see-v4/continuous/device/projects'/R11.name
        cfg=json.loads((folder/'project.json').read_text(encoding='utf-8'))['s2_geometry']
        original=module.verify_folder(folder,cfg)
        self.assertEqual(original['schema'],module.SCHEMA)
        self.assertEqual(original['mesh_sha256'],self.binding['origin_mesh_sha256'])
        self.assertEqual(module.file_sha(folder/'metadata-source-binding.json'),self.binding['origin_binding_sha256'])
        with self.assertRaisesRegex(ValueError,'r1 cannot select'):
            module.verify_folder(folder,dict(cfg,mesh_representation=module.ACTIVE_REPRESENTATION))

    def test_failed_r11_is_not_a_completed_a0_producer_and_runtime_syntax(self):
        with self.assertRaisesRegex(ValueError,'origin/completion differs'):
            bridge.geometry_source_bundle(OUT/'NOT_A_RUN',dict(producer_run_id=R11.name,source_run_directory=str(R11)))
        for name in ('metadata_continuation.py','geometry_bridge.py','prepare_case.py','case_contract.py','evaluate.py'):
            ast.parse((Path(__file__).parent/name).read_text(encoding='utf-8'),filename=name,feature_version=(3,6))


if __name__=='__main__':unittest.main()
