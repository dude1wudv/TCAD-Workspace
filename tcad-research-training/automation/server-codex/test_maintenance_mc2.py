import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import maintenance_mc2 as mc


class Mc2Tests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup); self.root=Path(tmp.name).resolve()
        self.reader=self.root/mc.READER; self.reader.parent.mkdir(parents=True); self.reader.write_text('# fixture')
        self.contract=self.reader.with_name('contract.json'); self.contract.write_text(json.dumps(dict(run_root='runs',tasks={'t':dict(input='inputs/t',hashes={})})))
        for name,path in [('SOURCE_SHA',self.reader),('CONTRACT_SHA',self.contract)]:
            p=patch.object(mc,name,mc.storage.sha(path)); p.start(); self.addCleanup(p.stop)
        self.f=self.root/'runs/r'; self.f.mkdir(parents=True)
        self.m=dict(run_id='r',collection_verified=True,parallel_slot_released=True,remote_exit_code=0,state='COLLECTED',
                    project_directory=str(self.root/'inputs/t'),input_sha256={},results_sha256='archive')
        (self.f/'manifest.json').write_text(json.dumps(self.m)); self.cache=self.root/'local_runtime/dram-se-r04/maintenance-r'
        for n in ('archive.py','numeric.py'): self.reader.with_name(n).touch()

    def test_no_original_or_outside_allowlist(self):
        with patch.object(mc.subprocess,'run',side_effect=AssertionError('invoked')):
            for task,rid in [('t','r'),('other','r'),('t','../r')]:
                with self.assertRaises(ValueError): mc.capture(self.root,task,rid)
        self.assertFalse(self.cache.exists())

    def test_bound_output_and_no_overwrite(self):
        (self.f/'results.tar').touch()
        def emit(argv,**kw):
            self.assertEqual(argv[-2:],['--output-dir',str(self.cache)]); self.cache.mkdir(parents=True)
            proof=dict(run_id='r',task_id='t',input_sha256={},manifest_sha256=mc.storage.sha(self.f/'manifest.json'),archive_sha256='archive')
            hashes={n:mc.storage.sha(self.reader.with_name(n)) for n in ('extract.py','archive.py','numeric.py','contract.json')}
            e=self.cache/'extraction.json'; e.write_text(json.dumps(dict(schema='dram-se-r04-mc2-response-observation-r1',status='observations_only_requires_scientific_interpretation',synthetic=False,provenance=proof,mc2_reader_sha256=hashes)))
            (self.cache/'receipt.json').write_text(json.dumps(dict(schema='dram-se-r04-mc2-observation-cache-r1',is_scientific_acceptance=False,extraction_sha256=mc.storage.sha(e),provenance=proof,mc2_reader_sha256=hashes)))
        with patch.object(mc.subprocess,'run',side_effect=emit) as run:
            self.assertFalse(mc.capture(self.root,'t','r')['cleanup_authorized'])
            with self.assertRaisesRegex(ValueError,'cache exists'): mc.capture(self.root,'t','r')
            self.assertEqual(run.call_count,1)
        self.assertFalse((self.f/'retention-ready.json').exists())
