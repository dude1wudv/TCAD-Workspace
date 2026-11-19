"""Focused source inheritance checks; no solver, SSH or successful D3 fixture."""
import ast
import copy
import io
import json
from pathlib import Path
import unittest
import uuid
from unittest import mock

import case_contract
import evaluate
import geometry_bridge as bridge
import metadata_continuation as metadata
import native_scripts
import visual_patch

ROOT=Path(__file__).resolve().parents[4]
OUT=ROOT/'local_runtime/dram-see-v4/continuous/device/d3-metadata-hdf5-continuation-r1'


class OverlayReader:
    """Fault injection over already verified original bytes, without new receipts."""
    def __init__(self,base,changes):self.base,self.changes=base,changes
    def read(self,name):return self.changes[name] if name in self.changes else self.base.read(name)
    def digest(self,name):return metadata.sha(self.changes[name]) if name in self.changes else self.base.digest(name)
    def size(self,name):return len(self.changes[name]) if name in self.changes else self.base.size(name)
    def exists(self,name):return name in self.changes or self.base.exists(name)
    def stream(self,name):return io.BytesIO(self.changes[name]) if name in self.changes else self.base.stream(name)


class MetadataContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request=case_contract.validate(json.loads((OUT/'request-r5.json').read_text()))
        cls.package=metadata.source_package(cls.request)
        cls.folder=OUT/('UNIT_FIXTURE_NOT_NATIVE-inherited-only-'+uuid.uuid4().hex[:12])
        cls.folder.mkdir()
        for name,raw in cls.package['files'].items():
            path=cls.folder/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        (cls.folder/'controlled-request.json').write_bytes(metadata.encoded(cls.request))
        (cls.folder/'SYNTHETIC_NOT_NATIVE').write_text('Input inheritance unit fixture. No current native result or qualification.\n')
        # Configuration is a local test identity; source owners remain their true originals.
        source=Path(cls.request['metadata_source_run'])
        with metadata.tarfile.open(str(source/'results.tar'),'r:*') as archive:
            original=metadata.ArchiveReader(archive,metadata.mesh_module().members(archive))
            cls.cfg=metadata.obj(original.read('project.json'))['s2_geometry']
        cls.cfg.update(mode='produce_from_metadata',run_id=cls.folder.name,producer_run_id=cls.folder.name,
            metadata_source_binding_sha256=metadata.sha(cls.package['files']['metadata-source-binding.json']),
            geometry_observation_backend=metadata.BACKEND)
        original_read=Path.read_bytes
        receipts={Path(node['directory'])/('manifest.json' if key=='metadata' else 'operation.json')
                  for key,node in cls.package['binding']['nodes'].items()}
        def frozen(path):
            if path in receipts:raise AssertionError('Staging reopened a mutable source receipt')
            return original_read(path)
        with mock.patch.object(Path,'read_bytes',frozen):metadata.stage(cls.folder,cls.cfg)
        cls.reader=metadata.FolderReader(cls.folder)
        (OUT/'focused-staged-input-reference.json').write_bytes(metadata.encoded(dict(
            path=str(cls.folder),source_binding_sha256=cls.cfg['metadata_source_binding_sha256'],
            original_source_verification_only=True,current_native_results=False)))

    def verify(self,changes=None,cfg=None,request=None):
        return metadata.verify(OverlayReader(self.reader,changes or {}),self.cfg if cfg is None else cfg,
                               self.request if request is None else request)

    def test_closed_request_and_exact_physical_identity(self):
        self.assertEqual(case_contract.validate(self.request),self.request)
        for extra in ({'command':'tdx'},{'native_step_start_index':4},{'continuation_recipe':'arbitrary'}):
            with self.assertRaises(ValueError):case_contract.validate(dict(self.request,**extra))
        for key,value in (('gate_top_depth_nm',70),('sn_junction_depth_nm',82),('variant','mesh')):
            with self.assertRaisesRegex(ValueError,'physics/numerics changed'):
                self.verify(request=dict(self.request,**{key:value}))
        with self.assertRaisesRegex(ValueError,'scientific input changed'):
            self.verify({'device.cmd':self.reader.read('device.cmd')+b'\n'})

    def test_frozen_graph_and_no_current_prefix_or_converter(self):
        binding=self.verify()
        self.assertEqual(binding['failed_step004']['exit_code'],137)
        self.assertEqual(binding['inherited_step_indices'],[1,2,3])
        self.assertEqual(binding['actual_step_indices'],[5,6])
        self.assertFalse(any((self.folder/name).exists() for name in metadata.FORBIDDEN_CURRENT))
        self.assertFalse((self.folder/'geometry-validation.json').exists())
        sources=bridge.geometry_exit_sources(self.folder,complete=False)
        self.assertEqual({r['source_kind'] for r in sources.values()},{'inherited_original_native_prefix'})
        # Current 005 is deliberately absent, so an inherited graph alone cannot finalize.
        with self.assertRaises(ValueError):bridge.geometry_exit_sources(self.folder)
        frozen=metadata.obj(self.reader.read('metadata-source-bindings/manifest.json'))
        with self.assertRaisesRegex(ValueError,'completed original collection'):
            metadata.validate_completed(self.reader,frozen,self.cfg,io.BytesIO(b''))
        with self.assertRaisesRegex(ValueError,'Synthetic'):
            bridge.geometry_source_bundle(self.folder,dict(producer_run_id=self.folder.name,source_run_directory=str(self.folder)))

    def test_coherently_rehashed_import_still_requires_original_index(self):
        name='hdf5-export/dataset-00-command.json'
        bad=metadata.obj(self.reader.read(name));bad['exit_code']=9
        raw=metadata.encoded(bad);binding=copy.deepcopy(self.package['binding'])
        binding['imports'][name].update(sha256=metadata.sha(raw),size_bytes=len(raw))
        with self.assertRaisesRegex(ValueError,'original collection index mismatch'):
            self.verify({name:raw,'metadata-source-binding.json':metadata.encoded(binding)})
        bad=copy.deepcopy(self.package['binding']);bad['imports'].pop('hdf5-export/dataset-33-stderr.txt')
        with self.assertRaisesRegex(ValueError,'incomplete original HDF5 collection'):
            self.verify({'metadata-source-binding.json':metadata.encoded(bad)})
        bad=copy.deepcopy(self.package['binding'])
        bad['imports']['tdx-metadata-exit-code.txt']['member']='step-003-tdx-exit-code.txt'
        with self.assertRaisesRegex(ValueError,'relabelled'):
            self.verify({'metadata-source-binding.json':metadata.encoded(bad)})

    def test_metadata_interval_keeps_its_original_owner(self):
        rows=self.reader.read('tdr-topology-identity.csv')
        changed=rows.replace(self.package['binding']['metadata_original_path'].encode(),b'/different/owner/cell_msh.tdr')
        reader=OverlayReader(self.reader,{'tdr-topology-identity.csv':changed})
        source_cfg=metadata.obj(self.reader.read('metadata-source-bindings/project.json'))['s2_geometry']
        with self.assertRaisesRegex(ValueError,'interval/path differs'):
            metadata.validate_metadata_interval(reader,source_cfg,self.package['mesh_sha256'])
        self.assertFalse((self.folder/'metadata-source-bindings/tdx-source-after.json').exists())

    def test_explicit_backend_and_original_measurement_program(self):
        plan=metadata.obj(self.reader.read('measurement-plan.json'))
        original=visual_patch.apply(native_scripts.render_svisual(plan)).encode()
        self.assertEqual(original,self.reader.read('measure-geometry.tcl'))
        modified=visual_patch.apply_in_process_identity(original.decode())
        self.assertNotIn('exec sha256sum',modified)
        self.assertIn('geometry-hash-provider.csv',modified)
        with self.assertRaisesRegex(ValueError,'Unknown native geometry backend'):
            evaluate.compare(plan,self.folder,'automatic_fallback')
        for name in ('metadata_continuation.py','geometry_bridge.py','prepare_case.py','case_contract.py','evaluate.py'):
            ast.parse((Path(__file__).parent/name).read_text(encoding='utf-8'),filename=name,feature_version=(3,6))


if __name__=='__main__':unittest.main()
