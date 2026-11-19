import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from input_parameters import read_input_parameters


def digest(data):
    return hashlib.sha256(data).hexdigest()


class InputParameterTests(unittest.TestCase):
    def make_fixture(self, request=None, *, project_inside=True, archive_inside=True,
                     temperature="Temperature = 300\n", stored_pattern="00"):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        workspace = base / "workspace"
        workspace.mkdir()
        project = workspace / "frozen-run" if project_inside else base / "outside-project"
        project.mkdir()
        archive = workspace / "source.tar" if archive_inside else base / "outside-source.tar"

        request_bytes = json.dumps(
            request or {"incident_energy_MeV": 1.0, "theta_deg": 17.5, "phi_deg": -30.0},
            separators=(",", ":"), allow_nan=True,
        ).encode("utf-8")
        with tarfile.open(archive, mode="w", format=tarfile.USTAR_FORMAT) as bundle:
            member = tarfile.TarInfo("request.json")
            member.size = len(request_bytes)
            bundle.addfile(member, io.BytesIO(request_bytes))

        device = project / "device.cmd"
        provenance = project / "provenance.json"
        native_manifest = project / "native-event-manifest.json"
        device.write_text(temperature, encoding="utf-8")
        provenance.write_text(json.dumps({"stored_pattern": stored_pattern}), encoding="utf-8")
        native_manifest.write_text(json.dumps({
            "source": {
                "archive": str(archive),
                "native_members": {"request.json": {"sha256": digest(request_bytes)}},
            },
        }), encoding="utf-8")
        checksums = {
            name: digest((project / name).read_bytes())
            for name in ("device.cmd", "provenance.json", "native-event-manifest.json")
        }
        (project / "SHA256SUMS.json").write_text(json.dumps(checksums), encoding="utf-8")
        manifest = {
            "project_directory": str(project),
            # A plan value, if present, must never override parameters in frozen inputs.
            "parameters": {"energy_MeV": 5.0},
        }
        return workspace, project, archive, manifest

    def test_extracts_actual_archived_request_and_frozen_device_values(self):
        workspace, _, _, manifest = self.make_fixture()
        result = read_input_parameters(manifest, workspace_root=workspace)
        self.assertEqual(result, {
            "temperature_K": 300,
            "stored_bit": 0,
            "energy_MeV": 1.0,
            "theta_deg": 17.5,
            "phi_deg": -30.0,
        })
        self.assertNotEqual(result["energy_MeV"], manifest["parameters"]["energy_MeV"])

    def test_missing_or_hash_mismatched_frozen_files_leave_their_values_unknown(self):
        affected_fields = {
            "device.cmd": ("temperature_K",),
            "provenance.json": ("stored_bit",),
            "native-event-manifest.json": ("energy_MeV", "theta_deg", "phi_deg"),
        }
        for filename, fields in affected_fields.items():
            for mode in ("missing", "modified"):
                with self.subTest(filename=filename, mode=mode):
                    workspace, project, _, manifest = self.make_fixture()
                    source = project / filename
                    if mode == "missing":
                        source.unlink()
                    else:
                        source.write_bytes(source.read_bytes() + b" ")
                    result = read_input_parameters(manifest, workspace_root=workspace)
                    for field in fields:
                        self.assertNotIn(field, result)

    def test_external_project_and_external_archive_are_not_used(self):
        workspace, _, _, outside_manifest = self.make_fixture(project_inside=False)
        self.assertEqual(read_input_parameters(outside_manifest, workspace_root=workspace), {})

        workspace, _, _, manifest = self.make_fixture(archive_inside=False)
        result = read_input_parameters(manifest, workspace_root=workspace)
        self.assertEqual(result.get("temperature_K"), 300)
        self.assertEqual(result.get("stored_bit"), 0)
        for field in ("energy_MeV", "theta_deg", "phi_deg"):
            self.assertNotIn(field, result)

    def test_boolean_and_nonfinite_request_values_are_not_projected(self):
        workspace, _, _, manifest = self.make_fixture(request={
            "incident_energy_MeV": True,
            "theta_deg": float("nan"),
            "phi_deg": 12.0,
            "unlisted_value": 99.0,
        })
        result = read_input_parameters(manifest, workspace_root=workspace)
        self.assertNotIn("energy_MeV", result)
        self.assertNotIn("theta_deg", result)
        self.assertEqual(result.get("phi_deg"), 12.0)
        self.assertNotIn("unlisted_value", result)

    def test_temperature_is_unknown_when_multiple_values_are_present(self):
        for text in (
            "Temperature = 300\nTemperature = 310\n",
            "Temperature = 300 Temperature = 310\n",
        ):
            with self.subTest(text=text):
                workspace, _, _, manifest = self.make_fixture(temperature=text)
                result = read_input_parameters(manifest, workspace_root=workspace)
                self.assertNotIn("temperature_K", result)

    def test_invalid_native_member_digest_and_oversized_request_are_not_projected(self):
        workspace, project, archive, manifest = self.make_fixture()
        native_path = project / "native-event-manifest.json"
        native = json.loads(native_path.read_text(encoding="utf-8"))
        native["source"]["native_members"]["request.json"]["sha256"] = "0" * 64
        native_path.write_text(json.dumps(native), encoding="utf-8")
        sums_path = project / "SHA256SUMS.json"
        sums = json.loads(sums_path.read_text(encoding="utf-8"))
        sums["native-event-manifest.json"] = digest(native_path.read_bytes())
        sums_path.write_text(json.dumps(sums), encoding="utf-8")
        result = read_input_parameters(manifest, workspace_root=workspace)
        for field in ("energy_MeV", "theta_deg", "phi_deg"):
            self.assertNotIn(field, result)

        workspace, project, archive, manifest = self.make_fixture(request={"incident_energy_MeV": 1.0})
        oversized = b"{" + b" " * (64 * 1024) + b"}"
        with tarfile.open(archive, mode="w", format=tarfile.USTAR_FORMAT) as bundle:
            member = tarfile.TarInfo("request.json")
            member.size = len(oversized)
            bundle.addfile(member, io.BytesIO(oversized))
        native_path = project / "native-event-manifest.json"
        native = json.loads(native_path.read_text(encoding="utf-8"))
        native["source"]["native_members"]["request.json"]["sha256"] = digest(oversized)
        native_path.write_text(json.dumps(native), encoding="utf-8")
        sums_path = project / "SHA256SUMS.json"
        sums = json.loads(sums_path.read_text(encoding="utf-8"))
        sums["native-event-manifest.json"] = digest(native_path.read_bytes())
        sums_path.write_text(json.dumps(sums), encoding="utf-8")
        result = read_input_parameters(manifest, workspace_root=workspace)
        for field in ("energy_MeV", "theta_deg", "phi_deg"):
            self.assertNotIn(field, result)

    def test_unknown_stored_pattern_does_not_guess_bit(self):
        workspace, _, _, manifest = self.make_fixture(stored_pattern="01")
        result = read_input_parameters(manifest, workspace_root=workspace)
        self.assertNotIn("stored_bit", result)


if __name__ == "__main__":
    unittest.main()
