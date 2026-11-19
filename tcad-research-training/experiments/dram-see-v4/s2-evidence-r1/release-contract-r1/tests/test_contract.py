"""Focused offline checks for the frozen S2 first-four review contract."""
import hashlib
import importlib.util
import json
from pathlib import Path
from pathlib import PurePosixPath
import unittest


HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[3]
PACKAGE = ROOT / 'local_runtime/dram-see-v4/s2-release-contract-r1/20261017T033504Z/candidate-r1'
BRIDGE = ROOT / 'experiments/dram-see-v4/s2-evidence-r1/runner-integration-r1/geometry_bridge.py'
ROLES = ('B1-D2', 'B1-D3', 'B1-A0-main-b0', 'B1-A0-main-b1')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def role_file(role, name):
    return PACKAGE / 'roles' / role / name


class ReleaseContractTests(unittest.TestCase):
    def test_review_manifest_and_direct_references_are_closed(self):
        manifest = read(PACKAGE / 'review-manifest.json')['files_sha256']
        packaged_files = {
            p.relative_to(PACKAGE).as_posix()
            for p in PACKAGE.rglob('*') if p.is_file() and p.name != 'review-manifest.json'
        }
        self.assertEqual(set(manifest), packaged_files)
        for name, digest in manifest.items():
            self.assertEqual(sha(PACKAGE / name), digest, name)

        # Check only explicit path/hash bindings in this new review package;
        # do not walk or hash the accepted source candidate wholesale.
        def visit(value):
            if isinstance(value, dict):
                if set(value) == {'path', 'sha256'}:
                    target = ROOT / value['path']
                    self.assertTrue(target.is_file(), value['path'])
                    self.assertEqual(sha(target), value['sha256'], value['path'])
                else:
                    for child in value.values():
                        visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        for path in PACKAGE.rglob('*.json'):
            if path.name != 'review-manifest.json':
                visit(read(path))

    def test_role_order_ids_and_no_actual_run_or_local_directory(self):
        contract = read(PACKAGE / 'contract.json')
        self.assertEqual(contract['role_order'], list(ROLES))
        self.assertEqual([PurePosixPath(x['path']).parent.name for x in contract['roles']], list(ROLES))
        for role in ROLES:
            binding = read(role_file(role, 'role-contract.review.json'))
            expected = '20261017T033504Z-v4-s2-' + role.lower() + '-r1'
            self.assertEqual(contract['planned_run_ids'][role], expected)
            self.assertEqual(binding['planned_run_id'], expected)
            self.assertIsNone(binding['actual_run_id'])
            self.assertFalse(binding['execution_enabled'])
            self.assertFalse((ROOT / 'local_runtime/runs' / expected).exists())

    def test_independent_budget_requests_and_no_old_budget_transfer(self):
        budget = read(PACKAGE / 'budget.review.json')
        requests = budget['requests']
        self.assertEqual(len(requests), 8)
        ids = [item['request_id'] for item in requests]
        self.assertEqual(len(set(ids)), 8)
        self.assertTrue(all(item['request_id'].startswith(budget['budget_id'] + '-') for item in requests))
        execution = [r for r in requests if r['category'] == 'role_execution']
        geometry = [r for r in requests if r['category'] == 'native_geometry_extractions']
        fields = [r for r in requests if r['category'] == 'native_field_extractions']
        self.assertEqual(len(execution), 4)
        self.assertEqual(len(geometry), 2)
        self.assertEqual(len(fields), 2)
        self.assertEqual(sum(r['units']['sdevice'] for r in execution), 4)
        self.assertEqual(sum(r['units']['mesh_builds'] for r in execution), 2)
        self.assertEqual(sum(r['units'] for r in geometry), 2)
        self.assertEqual(sum(r['units'] for r in fields), 2)
        self.assertEqual(budget['proposed']['mesh_builds'], 2)
        self.assertEqual(budget['proposed']['sdevice'], 4)
        self.assertEqual(budget['proposed']['native_geometry_extractions'], 2)
        self.assertEqual(budget['proposed']['native_field_extractions'], 2)
        self.assertEqual(budget['proposed']['total_svisual'], 4)
        self.assertFalse(budget['approved'])
        self.assertEqual(budget['reservations'], 0)
        self.assertEqual(budget['consumed'], 0)
        self.assertEqual(budget['old_balance_transfer'], 0)
        self.assertFalse(budget['old_ledger_modified'])
        self.assertEqual(budget['old_ledger']['path'], 'local_runtime/dram-see-v4/nuclear-closure-r1/budget.json')

    def test_user_action_permission_is_distinct_from_release_gates(self):
        authorization = read(PACKAGE / 'authorization.json')
        missing = read(PACKAGE / 'missing-evidence.json')
        contract = read(PACKAGE / 'contract.json')
        self.assertIs(authorization['explicit_native_authorization'], True)
        self.assertIs(contract['user_action_permission_granted'], True)
        self.assertIs(missing['ready_for_native'], False)
        self.assertIs(missing['requires_reasking_same_user_permission'], False)
        self.assertEqual(missing['user_action_permission'], 'GRANTED')
        statuses = {item['id']: item['status'] for item in missing['items']}
        self.assertEqual(statuses['BUDGET'], 'UNAPPROVED')
        self.assertEqual(statuses['POLICY'], 'UNAPPROVED')
        self.assertEqual(statuses['RESOURCE'], 'MISSING_EVIDENCE')
        self.assertEqual(statuses['OWNER_RELEASE'], 'NOT_RELEASED')
        for role in ROLES:
            execution = read(role_file(role, 'execution-release.review.json'))
            binding = read(role_file(role, 'role-contract.review.json'))
            self.assertIs(execution['explicit_native_authorization'], True)
            self.assertIs(execution['execution_enabled'], False)
            self.assertEqual(execution['status'], 'NOT_RELEASED')
            self.assertIsNone(execution['budget_reservation_id'])
            self.assertIs(binding['owner_release_approved'], False)

    def test_d2_starts_without_future_d3_mesh_dependency(self):
        project = read(role_file('B1-D2', 'project.review.json'))
        resource = read(role_file('B1-D2', 'resource-policy.review.json'))
        geometry = project['s2_geometry']
        self.assertEqual(geometry['mode'], 'produce')
        self.assertEqual(geometry['run_id'], '20261017T033504Z-v4-s2-b1-d2-r1')
        self.assertEqual(geometry['producer_run_id'], geometry['run_id'])
        self.assertNotIn('source_run_directory', geometry)
        self.assertIn('before its own mesh exists', resource['first_role_rule'])

    def test_a0_reuses_d3_and_keeps_field_extractions_separate(self):
        d3 = read(role_file('B1-D3', 'role-contract.review.json'))
        labels = []
        for role in ROLES[2:]:
            binding = read(role_file(role, 'role-contract.review.json'))
            project = read(role_file(role, 'project.review.json'))
            extraction = read(role_file(role, 'field-extraction.review.json'))
            self.assertEqual(binding['producer_run_id'], d3['planned_run_id'])
            self.assertEqual(project['s2_geometry']['producer_run_id'], d3['planned_run_id'])
            self.assertEqual(extraction['source_solver_run_id'], binding['planned_run_id'])
            self.assertIsNone(extraction['budget_reservation_id'])
            labels.append(extraction['planned_operation_label'])
        self.assertEqual(len(set(labels)), 2)

    def test_geometry_bridge_rejects_review_project_before_native_admission(self):
        spec = importlib.util.spec_from_file_location('s2_review_geometry_bridge', BRIDGE)
        bridge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bridge)
        for role in ROLES:
            project = read(role_file(role, 'project.review.json'))
            with self.subTest(role=role), self.assertRaisesRegex(ValueError, 'Geometry integration is not released'):
                bridge.geometry_admit(role_file(role, 'project.review.json').parent, project, '0' * 64)


if __name__ == '__main__':
    unittest.main()
