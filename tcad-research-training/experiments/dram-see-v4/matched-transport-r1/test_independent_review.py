"""Focused independent reproducer for matched run-record identity binding."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("matched_audit_identity_review", HERE / "audit_matched.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


class RunIdentityBindingReview(unittest.TestCase):
    def test_receipt_rejects_run_id_different_from_frozen_request_label(self):
        with tempfile.TemporaryDirectory(prefix="matched-run-identity-") as temp:
            root = Path(temp)
            here = root / "experiments/dram-see-v4/matched-transport-r1"
            here.mkdir(parents=True)
            shutil_geometry = HERE.parent / "source-interface-3d-r1/geometry-contract.json"
            contract = json.loads((HERE / "matched-contract.json").read_text(encoding="utf-8"))
            (here / "matched-contract.json").write_bytes((HERE / "matched-contract.json").read_bytes())
            geometry_path = root / contract["geometry_path"]
            geometry_path.parent.mkdir(parents=True)
            geometry_path.write_bytes(shutil_geometry.read_bytes())
            (here / "geometry-contract.json").write_bytes(shutil_geometry.read_bytes())
            folder = root / "run-folder"
            folder.mkdir()

            request = contract["requests"][0]
            required = {
                "task.sh", "run.sh", "exit-code.txt", "execution.log", "affinity.txt", "metadata.json",
                "status.json", "constructors.csv", "processes.csv", "hadronic-models.csv", "materials.csv",
                "elements.csv", "cuts.csv", "events.csv", "tracks.csv", "steps.csv", "birth-links.csv",
                "status-history.jsonl", "particles.csv", "material-energy.csv", "geometry-built.csv",
                "timings.csv", "geometry.hh", "geometry-contract.json", "matched-contract.json",
            }
            contents = {name: b"offline fixture\n" for name in required}
            contents.update({
                "request.json": json_bytes(request),
                "matched-contract.json": (here / "matched-contract.json").read_bytes(),
                "geometry-contract.json": (here / "geometry-contract.json").read_bytes(),
                "exit-code.txt": b"0\n",
            })
            for name, raw in contents.items():
                (folder / name).write_bytes(raw)
            input_names = {
                "task.sh", "run.sh", "request.json", "geometry.hh", "matched-contract.json",
                "geometry-contract.json",
            }
            input_hashes = {name: sha(contents[name]) for name in input_names}
            output_hashes = {name: sha(raw) for name, raw in contents.items()}
            archive_path = root / "results.tar"
            with tarfile.open(archive_path, "w") as archive:
                for name, raw in contents.items():
                    entry = tarfile.TarInfo(name)
                    entry.size = len(raw)
                    archive.addfile(entry, io.BytesIO(raw))

            operation_path = root / "operation.json"
            operation = {
                "schema": "dram-see-v4-transport-operation-v1",
                "label": "matched-init-h-r1",
                "ssh_exit_code": 0,
                "remote_exit_code": 0,
                "collection_exit_code": 0,
                "archive_sha256": sha(archive_path.read_bytes()),
                "input_sha256": input_hashes,
            }
            operation_path.write_bytes(json_bytes(operation))
            record = {
                "schema": "dram-see-v4-matched-run-r1",
                "run_id": "wrong-run-id",
                "mode": "init",
                "arm": "H",
                "runner_exit_code": 0,
                "remote_exit_code": 0,
                "collection_exit_code": 0,
                "request": request,
                "input_sha256": input_hashes,
                "output_sha256": output_hashes,
                "raw_archive": {"path": archive_path.relative_to(root).as_posix(),
                                "sha256": sha(archive_path.read_bytes())},
                "operation_evidence": {"path": operation_path.relative_to(root).as_posix(),
                                       "sha256": sha(operation_path.read_bytes())},
            }
            (folder / "record.json").write_bytes(json_bytes(record))
            report = {}
            with patch.object(audit, "ROOT", root), patch.object(audit, "HERE", here):
                with self.assertRaisesRegex(ValueError, "Run identity differs from frozen request label"):
                    audit._receipt(folder, report)


if __name__ == "__main__":
    unittest.main()
