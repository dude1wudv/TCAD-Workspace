"""Material-r2 adapter regressions; all mutable paths stay under validation-dev."""
import ast
import copy
import csv
import hashlib
import json
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
VALIDATION_DEV=ROOT/"local_runtime/dram-see-v4/nuclear-closure-r1/validation-dev"
sys.path.insert(0,str(HERE))
import common as c
import supervisor as base_supervisor
import supervisor_material_r2 as sm
import transport_material_r2 as tm
import transport_audit_material_r2 as ta
import event_source_material_r2 as es
import continue_material_r2 as cm

BASE_CONTRACT=json.loads((HERE/"contract.json").read_text(encoding="utf-8"))
OLD_TRANSPORT=json.loads((HERE/"transport-contract.json").read_text(encoding="utf-8"))
MATERIAL_TRANSPORT=json.loads((HERE/"transport-contract-material-r2.json").read_text(encoding="utf-8"))
GEOMETRY_BYTES=(HERE.parent/"source-interface-3d-r1/geometry-contract.json").read_bytes()


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sandbox(test,prefix="material-r2-"):
    temp=tempfile.TemporaryDirectory(prefix=prefix,dir=VALIDATION_DEV)
    test.addCleanup(temp.cleanup)
    root=Path(temp.name)/"root";root.mkdir()
    rt=root/"local_runtime/dram-see-v4/nuclear-closure-r1"
    old=root/"local_runtime/dram-see-v4/transport-probe"
    here=root/"experiments/dram-see-v4/nuclear-closure-r1"
    geometry=root/"experiments/dram-see-v4/source-interface-3d-r1/geometry-contract.json"
    for path in (rt,old,here,geometry.parent):path.mkdir(parents=True,exist_ok=True)
    for name in ("contract.json","transport-contract.json","transport-contract-material-r2.json"):
        (here/name).write_bytes((HERE/name).read_bytes())
    geometry.write_bytes(GEOMETRY_BYTES)
    stack=ExitStack();test.addCleanup(stack.close)
    for name,value in (("ROOT",root),("RT",rt),("OLD_OPS",old),("HERE",here),("GEOMETRY",geometry)):
        stack.enter_context(mock.patch.object(c,name,value))
    return root,rt,old,here,geometry,stack


def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True)+"\n",encoding="utf-8")
    return path


class MaterialRequestTests(unittest.TestCase):
    def test_manifest_replaces_only_h_initialization_and_preserves_other_106_requests(self):
        old={row["label"]:row for row in OLD_TRANSPORT["requests"]}
        new={row["label"]:row for row in MATERIAL_TRANSPORT["requests"]}
        self.assertEqual(len(old),107);self.assertEqual(len(new),107)
        self.assertEqual(set(old)-set(new),{"nc-r1-init-h"})
        self.assertEqual(set(new)-set(old),{"nc-r1-init-h-c1"})
        self.assertEqual(sum(row["event_count"] for row in new.values()),1000008)
        self.assertEqual(MATERIAL_TRANSPORT["binary_call_limit"],107)
        self.assertTrue(all(old[label]==new[label] for label in set(old)-{"nc-r1-init-h"}))
        correction=new["nc-r1-init-h-c1"]
        self.assertEqual(correction["corrective_of"],"nc-r1-init-h")
        self.assertEqual({k:v for k,v in correction.items() if k not in ("label","corrective_of")},
            {k:v for k,v in old["nc-r1-init-h"].items() if k!="label"})
        sandbox(self)
        self.assertEqual(tm.request("nc-r1-init-h-c1"),correction)
        with self.assertRaisesRegex(ValueError,"Request outside preregistered manifest"):
            tm.request("nc-r1-init-h")

    def test_original_failure_plus_106_new_normal_requests_plus_correction_counts_exactly(self):
        _,rt,old,_,_,_=sandbox(self,"ledger-total-")
        attempt_dir=rt/"attempts";attempt_dir.mkdir(parents=True)
        prior=next(row for row in OLD_TRANSPORT["requests"] if row["label"]=="nc-r1-init-h")
        write_json(attempt_dir/(prior["label"]+".json"),{"label":prior["label"],"kind":"transport","request":prior,"corrective":False,"state":"FAILED_OR_UNKNOWN"})
        normal=[r for r in MATERIAL_TRANSPORT["requests"] if not r.get("corrective_of")]
        corrective=next(r for r in MATERIAL_TRANSPORT["requests"] if r.get("corrective_of"))
        self.assertEqual(len(normal),106)
        for row in normal:
            write_json(attempt_dir/(row["label"]+".json"),{"label":row["label"],"kind":"transport","request":row,"corrective":False,"state":"RESERVED"})
        write_json(attempt_dir/(corrective["label"]+".json"),{"label":corrective["label"],"kind":"transport","request":corrective,"corrective":True,"state":"RESERVED"})
        prior_op=old/"operations"/prior["label"]
        write_json(prior_op/"operation.json",{"state":"FAILED_COLLECTED","ssh_exit_code":2,"remote_exit_code":2,"collection_exit_code":0})
        with mock.patch.object(c,"contract",return_value=BASE_CONTRACT):
            result=sm.budget()
        self.assertEqual(result["transport_normal_calls"],107)
        self.assertEqual(result["transport_corrective_calls"],1)
        self.assertEqual(result["transport_unique_primaries_requested"],1000008)
        self.assertEqual(result["transport_replay_primaries"],0)
        self.assertEqual(result["reservations"],108)

    def test_material_supervisor_reuses_original_lock_remote_preflight_and_budget(self):
        self.assertIs(sm.ownership,base_supervisor.ownership)
        self.assertIs(sm.remote_probe,base_supervisor.remote_probe)
        self.assertIs(sm.preflight,base_supervisor.preflight)
        self.assertIs(sm.budget,base_supervisor.budget)
        self.assertEqual(sm.OWNER_LOCK,base_supervisor.OWNER_LOCK)


class CorrectiveRegistrationTests(unittest.TestCase):
    def _setup_original(self,test,receipt):
        root,rt,old,_,_,stack=sandbox(test,"corrective-")
        original=next(row for row in OLD_TRANSPORT["requests"] if row["label"]=="nc-r1-init-h")
        write_json(rt/"attempts"/(original["label"]+".json"),{"label":original["label"],"kind":"transport","request":original,"corrective":False,"state":"FAILED_OR_UNKNOWN"})
        write_json(old/"operations"/original["label"]/"operation.json",receipt)
        return root,rt,old,stack,original,next(row for row in MATERIAL_TRANSPORT["requests"] if row.get("corrective_of"))

    def test_corrective_allowed_only_after_exact_original_2_2_0_failure(self):
        _,rt,_,stack,_,correction=self._setup_original(self,{"state":"FAILED_COLLECTED","ssh_exit_code":2,"remote_exit_code":2,"collection_exit_code":0})
        inputs=rt.parent.parent/"inputs-correction";inputs.mkdir(parents=True)
        class ReachedPreflight(Exception):pass
        stack.enter_context(mock.patch.object(sm,"preflight",side_effect=ReachedPreflight))
        with self.assertRaises(ReachedPreflight):sm.operation(correction["label"],inputs,"transport",correction)
        self.assertFalse((rt/"attempts"/(correction["label"]+".json")).exists())

    def test_non_2_2_0_original_failure_never_reaches_preflight(self):
        bad_receipts=[
            {"state":"FAILED_COLLECTED","ssh_exit_code":2,"remote_exit_code":1,"collection_exit_code":0},
            {"state":"FAILED_COLLECTED","ssh_exit_code":2,"remote_exit_code":2,"collection_exit_code":2},
            {"state":"COLLECTED_PENDING_AUDIT","ssh_exit_code":0,"remote_exit_code":0,"collection_exit_code":0},
        ]
        for i,receipt in enumerate(bad_receipts):
            with self.subTest(receipt=receipt):
                _,rt,_,stack,_,correction=self._setup_original(self,receipt)
                inputs=rt.parent.parent/"inputs-correction";inputs.mkdir(parents=True)
                with mock.patch.object(sm,"preflight") as preflight, mock.patch.object(sm.subprocess,"Popen") as popen:
                    with self.assertRaisesRegex(ValueError,"Original failure not known"):
                        sm.operation(correction["label"],inputs,"transport",correction)
                preflight.assert_not_called();popen.assert_not_called()
                self.assertFalse((rt/"attempts"/(correction["label"]+".json")).exists())
                stack.close()

    def test_two_corrective_attempts_exhaust_global_cap_before_preflight(self):
        _,rt,_,stack,original,correction=self._setup_original(self,{"state":"FAILED_COLLECTED","ssh_exit_code":2,"remote_exit_code":2,"collection_exit_code":0})
        for label in ("synthetic-correction-a","synthetic-correction-b"):
            request={**correction,"label":label}
            write_json(rt/"attempts"/(label+".json"),{"label":label,"kind":"transport","request":request,"corrective":True,"state":"FAILED_OR_UNKNOWN"})
        inputs=rt.parent.parent/"inputs-correction";inputs.mkdir(parents=True)
        with mock.patch.object(sm,"preflight") as preflight, mock.patch.object(sm.subprocess,"Popen") as popen:
            with self.assertRaisesRegex(ValueError,"Correction allocation exhausted"):
                sm.operation(correction["label"],inputs,"transport",correction)
        preflight.assert_not_called();popen.assert_not_called()
        self.assertFalse((rt/"attempts"/(correction["label"]+".json")).exists())

    def test_unknown_existing_attempt_is_not_resubmitted(self):
        _,rt,old,stack,_,correction=self._setup_original(self,{"state":"FAILED_COLLECTED","ssh_exit_code":2,"remote_exit_code":2,"collection_exit_code":0})
        inputs=rt.parent.parent/"inputs-correction";inputs.mkdir(parents=True)
        write_json(rt/"attempts"/(correction["label"]+".json"),{"label":correction["label"],"kind":"transport","request":correction,"corrective":True,"state":"RUNNING"})
        write_json(old/"operations"/correction["label"]/"operation.json",{"state":"RUNNING","ssh_exit_code":None,"remote_exit_code":None,"collection_exit_code":None})
        with mock.patch.object(sm.subprocess,"Popen") as popen:
            with self.assertRaisesRegex(ValueError,"Prior attempt unknown/failed"):
                sm.operation(correction["label"],inputs,"transport",correction)
        popen.assert_not_called()


class MaterialAuditAndSourceTests(unittest.TestCase):
    def test_scientific_audit_ast_is_unchanged_outside_two_identity_functions(self):
        old_path=HERE/"transport_audit.py";new_path=HERE/"transport_audit_material_r2.py"
        old_tree=ast.parse(old_path.read_text(encoding="utf-8"));new_source=new_path.read_text(encoding="utf-8")
        normalized=new_source.replace("transport-contract-material-r2.json","transport-contract.json").replace("transport_material_r2.py","transport.py")
        new_tree=ast.parse(normalized)
        def functions(tree):return {node.name:node for node in tree.body if isinstance(node,ast.FunctionDef)}
        old_f,new_f=functions(old_tree),functions(new_tree)
        self.assertEqual(set(old_f),set(new_f))
        changed={name for name in old_f if ast.dump(old_f[name],include_attributes=False)!=ast.dump(new_f[name],include_attributes=False)}
        self.assertEqual(changed,set())
        old_top=[ast.dump(n,include_attributes=False) for n in old_tree.body if not isinstance(n,(ast.FunctionDef,ast.Import,ast.ImportFrom))]
        new_top=[ast.dump(n,include_attributes=False) for n in new_tree.body if not isinstance(n,(ast.FunctionDef,ast.Import,ast.ImportFrom))]
        self.assertEqual(old_top,new_top)

    def _source_fixture(self,test):
        root,rt,_,here,geometry,_=sandbox(test,"source-auditor-")
        request=next(r for r in MATERIAL_TRANSPORT["requests"] if r["arm"]=="H" and r["mode"]=="normal")
        run=rt/"transport/runs"/request["label"];run.mkdir(parents=True)
        raw={name:(geometry.read_bytes() if name=="geometry-contract.json" else b"fixture raw bytes: "+name.encode())
            for name in ("steps.csv","tracks.csv","birth-links.csv","events.csv","geometry-contract.json")}
        for name,data in raw.items():(run/name).write_bytes(data)
        manifest_hash=sha(here/"transport-contract-material-r2.json")
        record=write_json(run/"record.json",{"run_id":request["label"],"request":request,
            "runner_exit_code":0,"remote_exit_code":0,"collection_exit_code":0,
            "input_sha256":{"matched-contract.json":manifest_hash},"output_sha256":{n:sha(run/n) for n in raw},
            "raw_archive":{"path":"fixture/archive","sha256":"archive"}})
        audit_path=rt/"transport/audits"/request["label"]/"audit.json"
        auditor_file=here/"transport_audit_material_r2.py";auditor_file.write_bytes((HERE/"transport_audit_material_r2.py").read_bytes())
        old_auditor=here/"transport_audit.py";old_auditor.write_bytes((HERE/"transport_audit.py").read_bytes())
        witness={"event_id":0,"process":"protonInelastic","process_type":4,"parent_track_id":1,"parent_step_id":2,
            "process_subtype":121,"direct_child_track_ids":[3],"descendant_track_ids":[3]}
        audit={"schema":"dram-see-v4-nuclear-closure-transport-audit-r1","passed":True,"errors":[],
            "checks":{name:{"passed":True} for name in es.AUDIT_CHECKS},
            "audit_code_sha256":sha(auditor_file),"matched_contract_sha256":manifest_hash,
            "mechanism_summary":{"qualifying_witnesses":[witness]},
            "record_sha256":sha(record),"request":request,"run_id":request["label"],"run_dir":str(run.resolve())}
        write_json(audit_path,audit)
        selection={"record":c.ref(record),"audit":c.ref(audit_path),"request":request,"event_id":0,
            "witness":{**witness,"window_descendant_si_ionizing_MeV":.01,"window_descendant_step_ids":[[0,3,1]]}}
        selection_path=write_json(rt/"selected-event.json",selection)
        return root,rt,here,selection_path,audit,auditor_file,old_auditor

    def test_event_source_rejects_old_auditor_and_requires_material_auditor_identity(self):
        _,_,_,selection,audit,new_auditor,old_auditor=self._source_fixture(self)
        class StopAfterIdentity(Exception):pass
        with mock.patch.object(es,"_rows",side_effect=StopAfterIdentity):
            with self.assertRaises(StopAfterIdentity):es.from_selected(selection)
        audit["audit_code_sha256"]=sha(old_auditor)
        write_json(selection.parent/"transport/audits"/audit["run_id"]/"audit.json",audit)
        # Update selection's audit ref to the changed synthetic audit bytes.
        audit_path=selection.parent/"transport/audits"/audit["run_id"]/"audit.json"
        payload=json.loads(selection.read_text(encoding="utf-8"));payload["audit"]=c.ref(audit_path);write_json(selection,payload)
        with mock.patch.object(es,"_rows") as rows:
            with self.assertRaisesRegex(ValueError,"Selected transport auditor changed"):
                es.from_selected(selection)
        rows.assert_not_called()
        self.assertNotEqual(sha(new_auditor),sha(old_auditor))

    def test_event_source_requires_the_material_manifest_membership(self):
        _,_,here,selection,_,_,_=self._source_fixture(self)
        path=here/"transport-contract-material-r2.json"
        manifest=json.loads(path.read_text(encoding="utf-8"))
        old_request=OLD_TRANSPORT["requests"]
        selected=json.loads(selection.read_text(encoding="utf-8"))["request"]
        self.assertIn(selected,old_request)
        manifest["requests"]=[row for row in manifest["requests"] if row!=selected]
        write_json(path,manifest)
        with mock.patch.object(es,"_rows") as rows:
            with self.assertRaisesRegex(ValueError,"frozen material-r2 sequence"):
                es.from_selected(selection)
        rows.assert_not_called()

    def test_native_geometry_inventory_rejects_the_old_oxide_density(self):
        _,rt,_,_,_,_=sandbox(self,"density-audit-")
        folder=rt/"density-record";folder.mkdir(parents=True)
        geometry=json.loads((HERE.parent/"source-interface-3d-r1/geometry-contract.json").read_text(encoding="utf-8"))
        metadata={"geometry":geometry,"world_half_um":[1.,1.,1.],"max_step_um":.02,"mode":"init"}
        fields=["volume","material","min_x_um","min_y_um","min_z_um","max_x_um","max_y_um","max_z_um",
                "density_g_cm3","charged_max_step_um","overlap_check_passed"]
        rows=[]
        for solid in geometry["solids"]:
            rows.append({"volume":solid["id"],"material":solid["geant4_material"],
                **{f"min_{axis}_um":value for axis,value in zip("xyz",solid["min_um"])},
                **{f"max_{axis}_um":value for axis,value in zip("xyz",solid["max_um"])},
                "density_g_cm3":solid["density_g_cm3"],"charged_max_step_um":.02,"overlap_check_passed":1})
        rows.append({"volume":"World","material":"G4_Galactic","min_x_um":-1.,"min_y_um":-1.,"min_z_um":-1.,
            "max_x_um":1.,"max_y_um":1.,"max_z_um":1.,"density_g_cm3":"","charged_max_step_um":"","overlap_check_passed":1})
        def store_geometry():
            with (folder/"geometry-built.csv").open("w",encoding="utf-8",newline="") as stream:
                writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)
        store_geometry()
        with (folder/"timings.csv").open("w",encoding="utf-8",newline="") as stream:
            writer=csv.DictWriter(stream,fieldnames=["phase","wall_seconds","cpu_seconds","events","tracks","steps"]);writer.writeheader()
            writer.writerows([{"phase":phase,"wall_seconds":0,"cpu_seconds":0,"events":0,"tracks":0,"steps":0}
                for phase in ("initialization","inventory_initialization")])
        self.assertTrue(ta._geometry_cost(folder,metadata,{},{}))
        oxide=next(row for row in rows if row["volume"]=="R.Ox");oxide["density_g_cm3"]=2.0;store_geometry()
        with self.assertRaisesRegex(ValueError,"NIST density differs from shared material"):
            ta._geometry_cost(folder,metadata,{}, {})


class DeadlineRecoveryTests(unittest.TestCase):
    def test_expired_existing_48h_window_is_not_recreated_or_extended(self):
        _,rt,old,_,_,stack=sandbox(self,"deadline-")
        request=next(r for r in MATERIAL_TRANSPORT["requests"] if r["closure_stage"]=="N1")
        stack.enter_context(mock.patch.object(tm,"contract",return_value={"requests":MATERIAL_TRANSPORT["requests"],"stage_order":["P0","N1"]}))
        stack.enter_context(mock.patch.object(c,"contract",return_value=BASE_CONTRACT))
        stack.enter_context(mock.patch.object(tm,"check_release"))
        build=old/"operations"/tm.BUILD_LABEL;build.mkdir(parents=True)
        inputs=old/"inputs"/tm.BUILD_LABEL;inputs.mkdir(parents=True)
        stage=write_json(rt/"transport/stages/P0.json",{"passed":True,"qualifying_event_found":False,"audits":[]})
        window=write_json(rt/"transport/sampling-window.json",{"started_utc":"2026-01-01T00:00:00+00:00","deadline_utc":"2026-01-03T00:00:00+00:00"})
        original_window=window.read_bytes()
        operation=mock.Mock(return_value=build)
        stack.enter_context(mock.patch.object(sm,"operation",operation))
        stack.enter_context(mock.patch.object(tm,"compile_inputs",return_value=inputs))
        stack.enter_context(mock.patch.object(tm,"assert_operation_complete"))
        prepare=mock.Mock()
        stack.enter_context(mock.patch.object(tm,"prepare",prepare))
        stack.enter_context(mock.patch.object(sm,"update_status"))
        self.assertFalse(cm.transport_stage())
        self.assertEqual(window.read_bytes(),original_window)
        self.assertFalse((rt/"attempts"/(request["label"]+".json")).exists())
        prepare.assert_not_called()
        self.assertEqual(operation.call_count,1)
        self.assertEqual(operation.call_args.args[0],tm.BUILD_LABEL)


if __name__=="__main__":unittest.main()
