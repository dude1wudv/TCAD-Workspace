"""Read-only material-r2 scope checks; no Geant4 execution or state writes."""
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile
import unittest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OLD=HERE.parent/'matched-transport-r1/transport_matched.cc'
NEW=HERE/'transport_material_r2.cc'
PROBE=HERE/'material_probe.cc'
FAILED=ROOT/'local_runtime/dram-see-v4/transport-probe/operations/nc-r1-init-h'
NATIVE_PROBE=ROOT/'local_runtime/dram-see-v4/transport-probe/operations/nc-r1-material-probe-r2'
OLD_SHA='0e510e397b5dd2ec03bcd14cb70d99dc33b59b469646d2920b0f4137a9161c27'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def block(text,start,end):
    if text.count(start)!=1 or text.count(end)!=1:raise ValueError('Ambiguous permitted block')
    return start+text.split(start,1)[1].split(end,1)[0]+end


def original_projection(text):
    helper=block(text,'// BEGIN CONTRACT_MATERIAL_R2:', '// END CONTRACT_MATERIAL_R2\n\n')
    metadata=block(text,'    // BEGIN MATERIAL_ORIGIN_R2:', '    // END MATERIAL_ORIGIN_R2\n')
    text=text.replace(helper,'').replace(metadata,'')
    new='''      auto material=std::string(s.material)=="G4_SILICON_DIOXIDE"
        ? contract_silicon_dioxide(n,s.density) : n->FindOrBuildMaterial(s.material);
      if (!material || std::abs(material->GetDensity()/(g/cm3)-s.density)>1e-9)
        throw std::runtime_error("Shared contract and instantiated material density differ");'''
    old='''      auto material=n->FindOrBuildMaterial(s.material);
      if (!material || std::abs(material->GetDensity()/(g/cm3)-s.density)>1e-9)
        throw std::runtime_error("Shared contract and native NIST material density differ");'''
    if text.count(new)!=1:raise ValueError('Material lookup no longer matches exact allowed edit')
    return text.replace(new,old)


class MaterialRevision(unittest.TestCase):
    def test_actual_native_probe_preserves_non_density_parameters_and_rejects_collision(self):
        receipt=json.loads((NATIVE_PROBE/'operation.json').read_text())
        self.assertEqual(receipt['state'],'COLLECTED_PENDING_AUDIT')
        self.assertEqual([receipt[k] for k in ('ssh_exit_code','remote_exit_code','collection_exit_code')],[0,0,0])
        self.assertEqual(sha(NATIVE_PROBE/'results.tar'),receipt['archive_sha256'])
        self.assertEqual(receipt['input_sha256']['material_probe.cc'],sha(PROBE))
        with tarfile.open(NATIVE_PROBE/'results.tar') as archive:
            members={m.name.removeprefix('./'):m for m in archive if m.isfile()}
            def read(name):return archive.extractfile(members[name]).read()
            self.assertEqual(read('material_probe.cc'),PROBE.read_bytes())
            for name,digest in receipt['input_sha256'].items():
                self.assertEqual(hashlib.sha256(read(name)).hexdigest(),digest)
            texts={mode:read(mode+'.txt').decode() for mode in ('nist','contract','collision')}
            for mode,text in texts.items():
                self.assertIn('MATERIAL_PROBE_R2_COMPLETED mode='+mode+' primaries=0',text)
                self.assertEqual(read(mode+'.txt'),(NATIVE_PROBE/'collected'/(mode+'.txt')).read_bytes())
            def rows(text,prefix):
                return [dict(word.split('=',1) for word in line.split()[1:]) for line in text.splitlines() if line.startswith(prefix+' ')]
            material={mode:[r for r in rows(text,'MATERIAL') if r['name']=='G4_SILICON_DIOXIDE'] for mode,text in texts.items()}
            nist,contract=material['nist'][0],material['contract'][0]
            self.assertNotEqual(float(nist['density_g_cm3']),float(contract['density_g_cm3']))
            self.assertAlmostEqual(float(contract['density_g_cm3']),2.2,places=12)
            for key in ('same_name_registrations','number_elements','mean_excitation_energy_eV','temperature_K','pressure_Pa','state'):
                self.assertEqual(nist[key],contract[key],key)
            self.assertEqual(contract['same_name_registrations'],'1')
            element={mode:[r for r in rows(text,'ELEMENT') if r['material']=='G4_SILICON_DIOXIDE'] for mode,text in texts.items()}
            for old,new in zip(element['nist'],element['contract']):
                for key in ('name','Z','mass_fraction','isotope_count'):self.assertEqual(old[key],new[key])
                self.assertAlmostEqual(float(old['atoms_relative_to_Si']),float(new['atoms_relative_to_Si']),places=12)
            self.assertEqual(rows(texts['nist'],'ISOTOPE'),rows(texts['contract'],'ISOTOPE'))
            self.assertIn('EXPECTED_COLLISION_REJECTION Contract SiO2 name already registered',texts['collision'])
            self.assertEqual(len(material['collision']),2)
            before,after=material['collision']
            self.assertEqual({k:v for k,v in before.items() if k!='origin'},
                             {k:v for k,v in after.items() if k!='origin'})
            request=json.loads(read('probe-request.json'))
            self.assertEqual(request['primaries'],0);self.assertFalse(request['run_manager_initialization'])

    def test_original_and_failed_archive_are_unchanged_and_zero_event(self):
        self.assertEqual(sha(OLD),OLD_SHA)
        receipt=json.loads((FAILED/'operation.json').read_text())
        self.assertEqual(sha(FAILED/'results.tar'),receipt['archive_sha256'])
        self.assertEqual([receipt[k] for k in ('ssh_exit_code','remote_exit_code','collection_exit_code')],[2,2,0])
        with tarfile.open(FAILED/'results.tar') as archive:
            members={m.name.removeprefix('./'):m for m in archive if m.isfile()}
            def read(name):return archive.extractfile(members[name]).read()
            self.assertEqual(read('transport_matched.cc'),OLD.read_bytes())
            state=json.loads(read('status.json'))
            self.assertEqual([state[k] for k in ('events_completed','tracks_completed','steps_recorded')],[0,0,0])
            self.assertFalse(state['beam_on_called'])
            rows=list(csv.DictReader(io.StringIO(read('geometry-built.csv').decode())))
            self.assertEqual([r['volume'] for r in rows],['World','R.Si'])
            self.assertAlmostEqual(float(rows[-1]['density_g_cm3']),2.33,places=12)

    def test_exact_difference_is_only_material_helper_lookup_and_origin(self):
        self.assertEqual(original_projection(NEW.read_text()).encode(),OLD.read_bytes())

    def test_unrelated_physics_change_is_detected_by_scope_guard(self):
        text=NEW.read_text().replace('p->SetDefaultCutValue(.01*um);','p->SetDefaultCutValue(.02*um);')
        self.assertNotEqual(original_projection(text).encode(),OLD.read_bytes())
        with self.assertRaises(ValueError):original_projection(NEW.read_text().replace('>1e-9)', '>1e-6)'))

    def test_probe_and_production_use_identical_material_constructor(self):
        start,end='// BEGIN CONTRACT_MATERIAL_R2:','// END CONTRACT_MATERIAL_R2\n\n'
        self.assertEqual(block(NEW.read_text(),start,end),block(PROBE.read_text(),start,end))

    def test_contract_density_stoichiometry_natural_elements_and_unique_name(self):
        text=NEW.read_text();helper=block(text,'// BEGIN CONTRACT_MATERIAL_R2:','// END CONTRACT_MATERIAL_R2\n\n')
        geometry=json.loads((HERE.parent/'source-interface-3d-r1/geometry-contract.json').read_text())
        oxide=[s for s in geometry['solids'] if s['id']=='R.Ox'][0]
        self.assertEqual((oxide['geant4_material'],oxide['density_g_cm3']),('G4_SILICON_DIOXIDE',2.2))
        self.assertIn('if (density_g_cm3!=2.2)',helper)
        self.assertIn('FindOrBuildElement("Si",true)',helper)
        self.assertIn('FindOrBuildElement("O",true)',helper)
        self.assertIn('owned->AddElement(silicon,1);',helper)
        self.assertIn('owned->AddElement(oxygen,2);',helper)
        self.assertIn('GetMaterial(name,false)',helper)
        self.assertIn('registered && registered!=owned',helper)
        self.assertIn('matches!=1',helper)
        self.assertLess(helper.index('registered && registered!=owned'),helper.index('new G4Material'))
        self.assertEqual(helper.count('new G4Material'),1)
        self.assertNotIn('FindOrBuildMaterial',helper)
        self.assertNotIn('new G4Element',helper)
        self.assertNotIn('FindOrBuildMaterial("G4_SILICON_DIOXIDE")',text)
        self.assertNotIn('SetMeanExcitationEnergy',text)
        self.assertNotIn('2.32',text)

    def test_metadata_distinguishes_contract_density_from_default_nist(self):
        metadata=block(NEW.read_text(),'    // BEGIN MATERIAL_ORIGIN_R2:', '    // END MATERIAL_ORIGIN_R2\n')
        self.assertIn('frozen shared geometry contract, not default NIST material density',metadata)
        self.assertIn('{"uses_default_NIST_oxide_density","false"}',metadata)
        self.assertIn('unchanged G4NistManager FindOrBuildMaterial',metadata)

    def test_probe_has_no_transport_and_reports_all_requested_native_properties(self):
        text=PROBE.read_text()
        for forbidden in ('#include "G4RunManager.hh"','new G4RunManager','BeamOn(','GeneratePrimaries(', 'SetMeanExcitationEnergy('):
            self.assertNotIn(forbidden,text)
        for required in ('"nist"','"contract"','"collision"','EXPECTED_COLLISION_REJECTION','same_name_registrations=',
                         'atoms_relative_to_Si=','mass_fraction=','natural_relative_abundance=',
                         'mean_excitation_energy_eV=','temperature_K=','pressure_Pa=','state='):
            self.assertIn(required,text)
        self.assertIn('probe::contract_silicon_dioxide(n,oxide->density)!=contract',text)

    def test_changed_cpp_has_balanced_lexical_delimiters(self):
        # A structural lexical check, not a claim of native C++ compilation/AST.
        pattern=r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''
        for path in (NEW,PROBE):
            cleaned=re.sub(pattern,' ',path.read_text());stack=[]
            for char in cleaned:
                if char in '({[':stack.append(char)
                elif char in ')}]':
                    self.assertTrue(stack,path.name)
                    self.assertEqual(stack.pop(),dict(zip(')}]','({['))[char],path.name)
            self.assertEqual(stack,[],path.name)


if __name__=='__main__':unittest.main()
