"""Root-review regressions for campaign/acceptance; all mutable paths are isolated."""
from contextlib import ExitStack
import copy
import csv
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import types
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
VALIDATION_DEV = ROOT / "local_runtime/dram-see-v4/nuclear-closure-r1/validation-dev"
sys.path.insert(0, str(HERE))
import common as c
import acceptance as a
import campaign as cp
import native_compile as nc
import supervisor as s
import transport as t
FROZEN_CONTRACT = c.read(HERE / "contract.json")


def sandbox(test, prefix="campaign-"):
    temp = tempfile.TemporaryDirectory(prefix=prefix, dir=VALIDATION_DEV)
    test.addCleanup(temp.cleanup)
    root = Path(temp.name) / "root"
    root.mkdir()
    rt = root / "local_runtime/dram-see-v4/nuclear-closure-r1"
    old = root / "local_runtime/dram-see-v4/transport-probe"
    here = root / "experiments/dram-see-v4/nuclear-closure-r1"
    geometry = root / "experiments/dram-see-v4/source-interface-3d-r1/geometry-contract.json"
    for path in (rt, old, here, geometry.parent):
        path.mkdir(parents=True, exist_ok=True)
    stack = ExitStack()
    test.addCleanup(stack.close)
    for name, value in (("ROOT", root), ("RT", rt), ("OLD_OPS", old),
                        ("HERE", here), ("GEOMETRY", geometry)):
        stack.enter_context(mock.patch.object(c, name, value))
    return root, rt, old, here, stack


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return path


def digest(path):
    return c.sha(path)


def test_contract():
    return copy.deepcopy(FROZEN_CONTRACT)


def curve_bundle(q_collected_fC=0.0, q_native_fC=0.0, control_role=""):
    times = [0.0, .95e-9, 4e-9]
    current = q_collected_fC / ((4e-9 - .95e-9) * 1e15)
    circuit = []
    for i, time in enumerate(times):
        circuit.append({"time": time, "v(sn)": .9, "v(bl)": .7, "v(ref)": .5, "v(wl)": 0.,
            "i(access,sn)": 0. if i < 2 else current, "i(rsn,sn)": 0., "i(access,bl)": 0.})
    native_current = -q_native_fC / (4e-9 * 1e15 * 1.602176634e-19 * 1e-12)
    device = [{"time": 0.0, "IntegrSemiconductor PMIRecombination": 0.0},
              {"time": 4e-9, "IntegrSemiconductor PMIRecombination": native_current}]
    return {"curves": {"circuit": circuit, "device": device},
        "parameters": {"control_role": control_role, "mesh_key": "m0", "common_mesh_manifest_sha256": "common",
            "pmi_binary_sha256": "pmi", "geometry_contract_sha256": "geometry", "dimension": 3,
            "stored_bit": 1, "source_windows_s": [[.98e-9, 1.02e-9]], "source_sha256": "event"},
        "field": {"mesh_sha256": "m0"}}


class AcceptanceBindingTests(unittest.TestCase):
    def test_published_gate_rejects_archive_bytes_changed_after_publication(self):
        root, rt, _, _, _ = sandbox(self, "archive-binding-")
        archive = root / "runs/native/results.tar"
        archive.parent.mkdir(parents=True)
        archive.write_bytes(b"original native archive bytes")
        manifest = write_json(root / "runs/native/manifest.json", {"state": "COLLECTED"})
        gate = {"schema": "nuclear-closure-role-gate-r1", "role": "a0-m0-t0", "passed": True,
            "acceptance_sha256": c.sha(Path(a.__file__)), "evidence": [c.ref(archive), c.ref(manifest)]}
        write_json(rt / "device/gates/a0-m0-t0.json", gate)
        self.assertEqual(a.gate("a0-m0-t0"), gate)
        archive.write_bytes(b"tampered archive bytes")
        with self.assertRaisesRegex(ValueError, "Evidence hash changed"):
            a.gate("a0-m0-t0")

    def test_real_backward_euler_kcl_uses_independent_right_endpoint_currents(self):
        _, _, _, _, stack = sandbox(self, "be-kcl-")
        stack.enter_context(mock.patch.object(c, "contract", return_value={"tolerances": {
            "kcl_charge_abs_fC": 1e-4, "kcl_relative": .01}}))
        times = [0., .95e-9, 1.8e-9, 4e-9]
        delta_v = [0., 0., .01, .03]
        signal_rows=[];control_rows=[]
        for i, time in enumerate(times):
            current = 0. if i < 2 else -1e-14 * (delta_v[i]-delta_v[i-1]) / (time-times[i-1])
            signal_rows.append({"time": time, "v(sn)": .9+delta_v[i], "v(bl)": .7, "v(ref)": .5, "v(wl)": 0.,
                "i(access,sn)": current, "i(rsn,sn)": 0., "i(access,bl)": 0.})
            control_rows.append({"time": time, "v(sn)": .9, "v(bl)": .7, "v(ref)": .5, "v(wl)": 0.,
                "i(access,sn)": 0., "i(rsn,sn)": 0., "i(access,bl)": 0.})
        result=a.circuit_balance({"circuit":signal_rows},{"circuit":control_rows})
        self.assertTrue(result["passed"], result)
        self.assertAlmostEqual(result["rows"][-1]["delta_storage_fC"], .3, places=12)
        self.assertAlmostEqual(result["rows"][-1]["delta_terminal_fC"], -.3, places=12)
        self.assertAlmostEqual(result["maximum_residual_fC"], 0., places=12)
        self.assertIn("BE-integrated", result["definition"])
        self.assertNotIn("i(cstore", result["definition"])
        signal_rows[-1]["i(access,sn)"] += 1e-6
        self.assertFalse(a.circuit_balance({"circuit":signal_rows},{"circuit":control_rows})["passed"])

    def test_generated_charge_two_percent_uses_left_reference_denominator(self):
        _, _, _, _, stack = sandbox(self, "q-left-")
        contract=test_contract()
        contract["numerical"]["comparisons"]=[["m0-t0","m1-t0"]]
        contract["tolerances"].update(refinement_voltage_abs_V=.001, refinement_voltage_relative=.05,
            refinement_charge_relative=.02, equivalent_charge_abs_fC=.0001, equivalent_voltage_abs_V=.00001,
            equivalent_generation_relative=.001, equivalent_current_abs_A=1e-12, equivalent_current_relative=.001)
        stack.enter_context(mock.patch.object(c, "contract", return_value=contract))
        data={
            "event-m0-t0":curve_bundle(0.,1.0,"a0-m0-t0"),
            "event-m1-t0":curve_bundle(0.,1.0202,"a0-m1-t0"),
            "a0-m0-t0":curve_bundle(0.,0.,""),
            "a0-m1-t0":curve_bundle(0.,0.,""),
        }
        for role,value in data.items():value["role"]=role
        data["event-m0-t0"]["parameters"]["mesh_key"]="m0";data["event-m0-t0"]["field"]["mesh_sha256"]="m0"
        data["event-m1-t0"]["parameters"]["mesh_key"]="m1";data["event-m1-t0"]["field"]["mesh_sha256"]="m1"
        data["a0-m0-t0"]["field"]["mesh_sha256"]="m0";data["a0-m1-t0"]["field"]["mesh_sha256"]="m1"
        for row in data["event-m0-t0"]["curves"]["circuit"]:row["v(sn)"]=.901
        for row in data["event-m1-t0"]["curves"]["circuit"]:row["v(sn)"]=.93
        stack.enter_context(mock.patch.object(a, "load", side_effect=lambda role:data[role]))
        stack.enter_context(mock.patch.object(c, "ref", return_value={"fixture":True}))
        report,_=a.compare_roles("event-m0-t0","event-m1-t0","refinement")
        native=report["metrics"]["native_generated_charge"]
        self.assertAlmostEqual(native["values_fC"][0],1.0,places=12)
        self.assertAlmostEqual(native["values_fC"][1],1.0202,places=12)
        self.assertAlmostEqual(native["limit_fC"],.02,places=12)
        self.assertFalse(native["passed"], "using max(|Qa|,|Qb|) would incorrectly pass this counterexample")
        voltage=report["metrics"]["v(sn)"]
        self.assertAlmostEqual(voltage["perturbation_peak_V"],.03,places=12)
        self.assertAlmostEqual(voltage["limit_V"],.0015,places=12,
            msg="voltage denominator remains the maximum of both paired perturbations")


class IdempotentPublicationTests(unittest.TestCase):
    def test_partial_matrix_publication_replays_identically_without_overwrite(self):
        _,rt,_,_,stack=sandbox(self,"matrix-recovery-")
        pairs=[["m0-t0","m0-t1"],["m1-t0","m1-t1"],["m0-t0","m1-t0"],["m0-t1","m1-t1"],["m0-t0","m1-t1"]]
        contract=test_contract();contract["numerical"]["comparisons"]=pairs
        stack.enter_context(mock.patch.object(c,"contract",return_value=contract))
        def compare(left,right,mode):
            return ({"left":left,"right":right,"mode":mode,"passed":True,"metrics":{"synthetic":0}},
                    [{"time_s":0.,"delta_v":0.}])
        stack.enter_context(mock.patch.object(a,"compare_roles",side_effect=compare))
        dest=rt/"device/matrix";dest.mkdir(parents=True)
        first="artificial-mixed--artificial-segmented"
        first_report,first_rows=compare("artificial-mixed","artificial-segmented","equivalent")
        a.json_verify_or_write(dest/(first+".json"),first_report)
        a.csv_verify_or_write(dest/(first+".csv"),first_rows)
        first_bytes=(dest/(first+".json")).read_bytes();first_mtime=(dest/(first+".csv")).stat().st_mtime_ns
        summary=a.complete_matrix()
        self.assertTrue(summary["passed"])
        self.assertEqual((dest/(first+".json")).read_bytes(),first_bytes)
        self.assertEqual((dest/(first+".csv")).stat().st_mtime_ns,first_mtime)
        self.assertTrue(a.complete_matrix()["passed"])
        bad=dest/(first+".json");changed=bad.read_bytes().replace(b'"passed": true',b'"passed": false')
        bad.write_bytes(changed)
        before=bad.read_bytes()
        with self.assertRaisesRegex(ValueError,"Stored comparison does not reproduce"):
            a.complete_matrix()
        self.assertEqual(bad.read_bytes(),before,"failed/changed evidence must not be silently replaced")

    def test_qualification_csv_is_reused_after_interrupted_summary_publication(self):
        _,rt,_,_,stack=sandbox(self,"qualification-recovery-")
        gate_refs=[]
        frames={}
        for role,values in (("qualification-zero",[(0.,10.,20.),(1.,10.,20.),(2.,10.,20.)]),
                            ("qualification-point",[(0.,10.,20.),(1.,11.,23.),(2.,10.,20.)])):
            gate=write_json(rt/"device/gates"/(role+".json"),{"passed":True,"role":role})
            gate_refs.append(c.ref(gate))
            path=rt/"device/fields"/role/"frames.csv";path.parent.mkdir(parents=True)
            with path.open("w",encoding="utf-8",newline="") as stream:
                writer=csv.DictWriter(stream,fieldnames=["end_s","N_raw","P_raw"]);writer.writeheader()
                writer.writerows([{"end_s":t,"N_raw":n,"P_raw":p} for t,n,p in values])
            frames[role]={"project":rt/"inputs"/role,"field":{"mesh_sha256":"same","frames_csv_path":str(path),"frames_csv_sha256":c.sha(path)}}
        def loader(path,name):
            if Path(path).name=="acceptance.py":return a
            if Path(path).name=="build_cases.py":return types.SimpleNamespace(check_control=mock.Mock(return_value={"passed":True}))
            raise AssertionError(path)
        stack.enter_context(mock.patch.object(c,"module",side_effect=loader))
        stack.enter_context(mock.patch.object(a,"load",side_effect=lambda role:frames[role]))
        result=cp.qualification();self.assertTrue(result["passed"])
        paired=rt/"pmi/paired-native-carriers.csv";original=paired.read_bytes();stamp=paired.stat().st_mtime_ns
        (rt/"pmi/qualification.json").unlink()
        self.assertTrue(cp.qualification()["passed"])
        self.assertEqual(paired.read_bytes(),original);self.assertEqual(paired.stat().st_mtime_ns,stamp)
        paired.write_bytes(original+b"tamper\n");tampered=paired.read_bytes()
        (rt/"pmi/qualification.json").unlink()
        with self.assertRaisesRegex(ValueError,"Stored comparison CSV does not reproduce"):
            cp.qualification()
        self.assertEqual(paired.read_bytes(),tampered)


class CampaignRecoveryTests(unittest.TestCase):
    def test_existing_successful_tcad_attempt_is_reconciled_without_resubmission(self):
        root,rt,_,here,stack=sandbox(self,"tcad-reconcile-")
        project=root/"projects/a0-m0-t0";project.mkdir(parents=True);(project/"input.dat").write_text("fixed inputs",encoding="utf-8")
        hashes={"input.dat":c.sha(project/"input.dat")};run=root/"local_runtime/runs/original-run"
        write_json(run/"manifest.json",{"state":"COLLECTED"})
        label="nc-r1-a0-m0-t0";attempt=write_json(rt/"attempts"/(label+".json"),{"role":"a0-m0-t0","input_hashes":hashes,
            "exit_code":0,"run_directory":"local_runtime/runs/original-run"})
        stack.enter_context(mock.patch.object(c,"contract",return_value=test_contract()))
        stack.enter_context(mock.patch.object(c,"module",return_value=types.SimpleNamespace(check_project=lambda p:{"passed":True})))
        with mock.patch.object(cp.subprocess,"Popen") as popen:
            result,path=cp.tcad("a0-m0-t0",project)
        self.assertEqual(result,run);self.assertEqual(path,attempt);popen.assert_not_called()

    def test_failed_or_unknown_tcad_attempt_blocks_without_resubmission(self):
        root,rt,_,_,stack=sandbox(self,"tcad-failed-")
        project=root/"projects/a0-m0-t0";project.mkdir(parents=True);(project/"input.dat").write_text("fixed inputs",encoding="utf-8")
        hashes={"input.dat":c.sha(project/"input.dat")};label="nc-r1-a0-m0-t0"
        write_json(rt/"attempts"/(label+".json"),{"role":"a0-m0-t0","input_hashes":hashes,"exit_code":None})
        stack.enter_context(mock.patch.object(c,"contract",return_value=test_contract()))
        stack.enter_context(mock.patch.object(c,"module",return_value=types.SimpleNamespace(check_project=lambda p:{"passed":True})))
        with mock.patch.object(cp.subprocess,"Popen") as popen:
            with self.assertRaisesRegex(ValueError,"outcome unknown/failed"):
                cp.tcad("a0-m0-t0",project)
        popen.assert_not_called()

    def test_min_step_parameter_echo_plus_pmi_failure_is_shared_unknown(self):
        root,rt,_,_,stack=sandbox(self,"minstep-classification-")
        role="a0-m0-t0";run=root/"local_runtime/runs/failed";run.mkdir(parents=True)
        write_json(run/"manifest.json",{"state":"FAILED_COLLECTED"})
        (run/"results.tar").write_bytes(b"fixture-only archive")
        attempt=write_json(rt/"attempts"/("nc-r1-"+role+".json"),{"role":role,"run_directory":"local_runtime/runs/failed"})
        class FixtureArchive:
            members={"execution.log":object(),"transient_des.log":object()}
            def __init__(self,path):pass
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,name):
                if name=="execution.log":return b"MinStep=1e-18\nPMI model load failed\n"
                return b"PMI model load failed\n"
        acceptance_module=types.SimpleNamespace(original=lambda:types.SimpleNamespace(Archive=FixtureArchive))
        stack.enter_context(mock.patch.dict(sys.modules,{"acceptance":acceptance_module}))
        result=cp.failure_cause(role,RuntimeError("synthetic fixture"))
        self.assertEqual(result["root_cause"],"UNCLASSIFIED_REQUIRES_DIAGNOSIS")
        self.assertIs(result["shared"],True)

    def test_shared_failure_pauses_remaining_roles_and_same_cause_twice_pauses(self):
        def execute_failure_case(same_cause_twice):
            root,rt,_,_,stack=sandbox(self,"shared-pause-")
            stack.enter_context(mock.patch.object(c,"contract",return_value=test_contract()))
            write_json(rt/"selected-event.json",{"event_id":4})
            source=types.SimpleNamespace(from_selected=lambda path:{"source":{"fixture":"event"},"ledger":{"fixture":"ledger"}})
            builder=types.SimpleNamespace(freeze_mesh=lambda event:{"mesh":"fixed"})
            def load_module(path,name):
                if Path(path).name=="event_source.py":return source
                if Path(path).name=="build_cases.py":return builder
                if Path(path).name=="acceptance.py":return a
                raise AssertionError(path)
            stack.enter_context(mock.patch.object(c,"module",side_effect=load_module))
            stack.enter_context(mock.patch.object(cp,"qualify"))
            stack.enter_context(mock.patch.object(c,"check_release"))
            first=mock.Mock(side_effect=RuntimeError("synthetic role failure"))
            stack.enter_context(mock.patch.object(cp,"role_run",first))
            if same_cause_twice:
                causes=[{"root_cause":"NATIVE_ENGINE_FAILURE","shared":False},
                        {"root_cause":"NATIVE_ENGINE_FAILURE","shared":False}]
            else:
                causes=[{"root_cause":"PMI_SHARED_FAILURE","shared":True}]
            stack.enter_context(mock.patch.object(cp,"failure_cause",side_effect=causes))
            stack.enter_context(mock.patch.object(s,"remote_probe",return_value={"active_solver_lines":[],"values":{"LOCK_FREE":1}}))
            stack.enter_context(mock.patch.object(s,"update_status"))
            return rt,stack,first
        rt,stack,role_run=execute_failure_case(False)
        cp.run();self.assertEqual(role_run.call_count,1)
        rows=json.loads((rt/"device/branch-failures.json").read_text(encoding="utf-8"))["failures"]
        self.assertTrue(any(r.get("reason")=="SHARED_DEPENDENCY_PAUSED" for r in rows[1:]))
        stack.close()
        rt,stack,role_run=execute_failure_case(True)
        cp.run();self.assertEqual(role_run.call_count,2)
        self.assertEqual([call.args[0] for call in role_run.call_args_list],["a0-m0-t0","a0-m0-t1"])
        rows=json.loads((rt/"device/branch-failures.json").read_text(encoding="utf-8"))["failures"]
        self.assertTrue(any(r.get("reason")=="SHARED_DEPENDENCY_PAUSED" for r in rows[2:]))


class NativeCompileReceiptTests(unittest.TestCase):
    def test_synthetic_native_probe_receipt_requires_all_fixed_vectors_and_never_rebuilds(self):
        root,rt,old,here,stack=sandbox(self,"native-probe-")
        source=here/"pmi_source.C";source.write_text("synthetic source fixture",encoding="utf-8")
        proof=rt/"pmi/build.json";op=old/"operations"/nc.LABEL;output=op/"collected";output.mkdir(parents=True)
        (op/"operation.json").write_bytes(b"fixture operation receipt")
        (op/"results.tar").write_bytes(b"fixture archive")
        (output/"pmi_nuclear_source.C").write_bytes(source.read_bytes())
        binary=output/"pmi_nuclear_source.so.linux64";binary.write_bytes(b"\x7fELF synthetic fixture")
        vectors=[{"name":f"fixed_{i}","expected_cm_minus3_s_minus1":float(i+1),"comparison_abs":0.,"comparison_relative":0.} for i in range(6)]
        write_json(output/"native-oracle-vectors.json",{"vectors":vectors})
        with (output/"native-oracle.csv").open("w",encoding="utf-8",newline="") as stream:
            writer=csv.DictWriter(stream,fieldnames=["name","actual"]);writer.writeheader()
            writer.writerows([{"name":v["name"],"actual":v["expected_cm_minus3_s_minus1"]} for v in vectors])
        for name in ("native-tool-header-sha256.txt","exported-symbols.txt","linked-libraries.txt"):(output/name).write_text("synthetic fixture evidence",encoding="utf-8")
        inputs=old/"inputs"/nc.LABEL;inputs.mkdir(parents=True)
        stack.enter_context(mock.patch.object(c,"check_release"))
        stack.enter_context(mock.patch.object(nc,"prepare",return_value=inputs))
        stack.enter_context(mock.patch.object(t,"assert_operation_complete"))
        operation=mock.Mock(return_value=op);stack.enter_context(mock.patch.object(s,"operation",operation))
        first=nc.ensure_compiled();self.assertEqual(first,binary)
        receipt=c.read(proof)
        self.assertTrue(receipt["compiled"]);self.assertFalse(receipt["qualified"])
        self.assertEqual(len(receipt["native_arithmetic"]),6)
        self.assertTrue(cp.pmi_binary().is_file())
        second=nc.ensure_compiled();self.assertEqual(second,binary);operation.assert_called_once()
        (op/"results.tar").write_bytes(b"archive changed")
        with self.assertRaisesRegex(ValueError,"Evidence hash changed"):
            nc.ensure_compiled()
        operation.assert_called_once()


if __name__=="__main__":unittest.main()
