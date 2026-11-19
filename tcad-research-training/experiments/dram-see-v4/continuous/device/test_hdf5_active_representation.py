"""Only new active/origin identities; no topology scan or native qualification."""
import ast
import copy
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
RUNTIME = ROOT/'local_runtime/dram-see-v4/continuous/device/sdevice-edge-memory-analysis-r1/active-v16-observer-r1'
OLD = ROOT/'local_runtime/dram-see-v4/continuous/device/hdf5-observer-r1'
RAW = OLD/'raw-layout'
V16 = ROOT/'local_runtime/dram-see-v4/transport-probe/operations/cgoal-d3-tdr-v16-20261017t142300z/collected/mesh-v16.tdr'
ORIGIN_BINDING = ROOT/'local_runtime/dram-see-v4/continuous/device/projects/20261017T150025Z-v4-continuous-b1-d3-r11/metadata-source-binding.json'
spec = importlib.util.spec_from_file_location('tested_hdf5_active_representation', str(HERE/'hdf5_observer.py'))
H = importlib.util.module_from_spec(spec); spec.loader.exec_module(H)


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode('utf-8')


class ActiveRepresentationIdentities(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = json.loads((OLD/'actual-r1/audit.json').read_text(encoding='utf-8'))
        cls.prior_raw = ORIGIN_BINDING.read_bytes()
        cls.prior = json.loads(cls.prior_raw)
        cls.export = {name:json.loads((RAW/'hdf5-export'/file).read_text(encoding='utf-8')) for name,file in
                      (('manifest','raw-export-manifest.json'),('request','export-request.json'))}

    def cleanup(self, path):
        resolved = path.resolve()
        self.assertIn(RUNTIME.resolve(), resolved.parents)
        self.assertTrue(resolved.name.startswith('UNIT_FIXTURE_NOT_NATIVE-'))
        shutil.rmtree(str(resolved))

    def write(self, path, raw):
        if path.exists():
            path.unlink()  # Only this verified fixture file/hardlink; never overwrite original bytes.
        with path.open('xb') as stream:stream.write(raw)

    def fixture(self):
        root = Path(tempfile.mkdtemp(prefix='UNIT_FIXTURE_NOT_NATIVE-', dir=str(RUNTIME)))
        self.addCleanup(self.cleanup, root)
        for name in ('tdr-topology-identity.csv','tdr-region-status.json','tdr-geometry.csv','tdr-region-datasets.csv'):
            os.link(str(RAW/name), str(root/name))
        os.link(str(RAW/'cell_msh.tdr'), str(root/'scientific-origin-mesh.tdr'))
        os.link(str(V16), str(root/'cell_msh.tdr'))
        self.write(root/'metadata-origin-binding.json', self.prior_raw)
        binding = copy.deepcopy(self.prior)
        origin = binding['imports'].pop('cell_msh.tdr')
        binding['imports']['scientific-origin-mesh.tdr'] = origin
        binding['imports']['cell_msh.tdr'] = dict(owner='conversion',member='mesh-v16.tdr',
            sha256=self.prior['hdf5_sha256'],size_bytes=self.prior['hdf5_size_bytes'])
        binding.update(schema=H.ACTIVE_BINDING_SCHEMA,recipe='native-hdf5-v16-active-mesh-r1',
            mesh_representation=H.ACTIVE_REPRESENTATION,
            origin_mesh_file='scientific-origin-mesh.tdr',origin_mesh_sha256=self.prior['mesh_sha256'],
            origin_mesh_size_bytes=self.prior['mesh_size_bytes'],active_solver_mesh_file='cell_msh.tdr',
            active_solver_mesh_sha256=self.prior['hdf5_sha256'],active_solver_mesh_size_bytes=self.prior['hdf5_size_bytes'],
            mesh_sha256=self.prior['hdf5_sha256'],mesh_size_bytes=self.prior['hdf5_size_bytes'],
            origin_binding_file='metadata-origin-binding.json',origin_binding_sha256=hashlib.sha256(self.prior_raw).hexdigest())
        self.write(root/'metadata-source-binding.json',encoded(binding))
        run_id='UNIT_FIXTURE_NOT_NATIVE-current'
        path='/home/tcad/research-training/runs/'+run_id+'/cell_msh.tdr'
        context=dict(schema=H.ACTIVE_CONTEXT_SCHEMA,mesh_representation=H.ACTIVE_REPRESENTATION,
            geometry_observation_backend='native_hdf5_v16_export',origin='native_pipeline',synthetic=False,
            producer_run_id=run_id,mesh_sha256=self.prior['hdf5_sha256'],
            origin_mesh_sha256=self.prior['mesh_sha256'],active_solver_mesh_sha256=self.prior['hdf5_sha256'],
            metadata_source_binding_sha256=H.sha(root/'metadata-source-binding.json'),
            test_scope='UNIT_FIXTURE_NOT_NATIVE; not a registered source graph or native result')
        self.write(root/'observation-context.json',encoded(context))
        rows=[]
        for phase in ('BEFORE','AFTER'):
            self.write(root/('current-mesh-'+phase.lower()+'.json'),encoded(dict(
                schema='dram-see-v4-current-mesh-integrity-r1',phase=phase,run_id=run_id,path=path,sha256=self.prior['hdf5_sha256'])))
            rows.append(dict(phase=phase,path=path,sha256=self.prior['hdf5_sha256'],run_id=run_id,command_status='OK'))
        with (root/'mesh-identity.csv').open('x',encoding='utf-8',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=['phase','path','sha256','run_id','command_status'])
            writer.writeheader();writer.writerows(rows)
        return root

    def replace_json(self, root, name, change):
        value=json.loads((root/name).read_text(encoding='utf-8'));change(value)
        self.write(root/name,encoded(value))
        if name=='metadata-source-binding.json':
            self.replace_json(root,'observation-context.json',lambda row:row.update(
                metadata_source_binding_sha256=H.sha(root/name)))

    def test_actual_two_file_identity_and_original_metadata(self):
        root=self.fixture()
        identity=H._mesh_representation(root,self.export)
        self.assertEqual(identity['origin_mesh_sha256'],self.prior['mesh_sha256'])
        self.assertEqual(identity['active_solver_mesh_sha256'],self.prior['hdf5_sha256'])
        rows=H._metadata(root,self.export,self.audit['grid'],self.audit['datasets'],identity)
        self.assertEqual(rows,self.audit['original_tdx_identity'])
        self.assertNotEqual(rows[0]['path'],identity['current_mesh_identity'][0]['path'])

    def test_affected_legacy_metadata_uses_original_identity_only(self):
        identity=H._mesh_representation(RAW,self.export)
        self.assertEqual(identity,dict(mode='original_mesh',origin_mesh_sha256=self.prior['mesh_sha256']))
        self.assertEqual(H._metadata(RAW,self.export,self.audit['grid'],self.audit['datasets']),self.audit['original_tdx_identity'])

    def test_schema_pair_and_role_aliases_rejected(self):
        cases=[('metadata-source-binding.json','schema','dram-see-v4-metadata-hdf5-source-binding-r1'),
               ('observation-context.json','schema','dram-see-v4-hdf5-geometry-observation-context-r1'),
               ('metadata-source-binding.json','origin_mesh_file','cell_msh.tdr'),
               ('metadata-source-binding.json','mesh_sha256',self.prior['mesh_sha256']),
               ('metadata-source-binding.json','active_solver_mesh_sha256',self.prior['mesh_sha256'])]
        for name,key,value in cases:
            with self.subTest(name=name,key=key):
                root=self.fixture();self.replace_json(root,name,lambda row:row.update({key:value}))
                with self.assertRaises(ValueError):H._mesh_representation(root,self.export)

    def test_file_bytes_size_and_original_binding_rejected(self):
        for variant in ('active_is_origin','origin_is_active','size','origin_binding'):
            with self.subTest(variant=variant):
                root=self.fixture()
                if variant=='active_is_origin':
                    (root/'cell_msh.tdr').unlink();os.link(str(RAW/'cell_msh.tdr'),str(root/'cell_msh.tdr'))
                elif variant=='origin_is_active':
                    (root/'scientific-origin-mesh.tdr').unlink();os.link(str(V16),str(root/'scientific-origin-mesh.tdr'))
                elif variant=='size':
                    self.replace_json(root,'metadata-source-binding.json',lambda row:row.update(origin_mesh_size_bytes=True))
                else:self.replace_json(root,'metadata-origin-binding.json',lambda row:row.update(scientific_qualification=True))
                with self.assertRaises(ValueError):H._mesh_representation(root,self.export)

    def test_export_cannot_swap_original_and_converted_identity(self):
        for section,key in (('manifest','original_mesh_sha256'),('manifest','source_sha256'),('request','source_bytes')):
            with self.subTest(section=section,key=key):
                root=self.fixture();changed=copy.deepcopy(self.export)
                changed[section][key]=self.prior['hdf5_sha256'] if key=='original_mesh_sha256' else self.prior['mesh_sha256'] if key=='source_sha256' else 1
                with self.assertRaises(ValueError):H._mesh_representation(root,changed)

    def test_current_and_original_intervals_are_not_interchangeable(self):
        for variant in ('context','current_after','visual','metadata_sha','metadata_path','metadata_status'):
            with self.subTest(variant=variant):
                root=self.fixture()
                if variant=='context':self.replace_json(root,'observation-context.json',lambda row:row.update(mesh_sha256=self.prior['mesh_sha256']))
                elif variant=='current_after':self.replace_json(root,'current-mesh-after.json',lambda row:row.update(sha256=self.prior['mesh_sha256']))
                elif variant=='visual':self.write(root/'mesh-identity.csv',(root/'mesh-identity.csv').read_bytes().replace(self.prior['hdf5_sha256'].encode(),self.prior['mesh_sha256'].encode()))
                elif variant=='metadata_sha':self.write(root/'tdr-topology-identity.csv',(root/'tdr-topology-identity.csv').read_bytes().replace(self.prior['mesh_sha256'].encode(),self.prior['hdf5_sha256'].encode()))
                elif variant=='metadata_path':self.write(root/'tdr-topology-identity.csv',(root/'tdr-topology-identity.csv').read_bytes().replace(self.prior['metadata_original_path'].encode(),b'/different/original-owner/cell_msh.tdr'))
                else:self.replace_json(root,'tdr-region-status.json',lambda row:row.update(original_mesh_sha256=self.prior['hdf5_sha256']))
                with self.assertRaises(ValueError):H._metadata(root,self.export,self.audit['grid'],self.audit['datasets'])

    def test_new_source_keeps_python36_grammar_and_unchanged_numeric_helpers(self):
        source=(HERE/'hdf5_observer.py').read_text(encoding='utf-8')
        ast.parse(source,feature_version=(3,6))
        old=ast.parse((RUNTIME/'hdf5_observer-before.py').read_text(encoding='utf-8'))
        new=ast.parse(source)
        unchanged=('_schema','_binary','_records','_face','_point','_triangle','_range','load_export','observe')
        a={item.name:ast.dump(item,include_attributes=False) for item in old.body if isinstance(item,ast.FunctionDef)}
        b={item.name:ast.dump(item,include_attributes=False) for item in new.body if isinstance(item,ast.FunctionDef)}
        self.assertTrue(all(a[name]==b[name] for name in unchanged))


if __name__=='__main__':unittest.main(verbosity=2)
