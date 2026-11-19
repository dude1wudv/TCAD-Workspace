"""Focused tests of the declared BTBT mapping; no native or license calls."""
from pathlib import Path
import json
import math
import unittest
import physics_patch as patch

ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT/'local_runtime/dram-see-v4/s2-runner-integration-r1/20261016T155822Z/candidate-r2/roles'
ROLES = ('B1-D2','B1-D3','B1-A0-main-b0','B1-A0-main-b1')


def payload(role):
    folder = SOURCE/role
    return ((folder/'device.cmd').read_text(encoding='utf-8'),
            (folder/'physics.par').read_text(encoding='utf-8'),
            json.loads((folder/'physics-manifest.json').read_text(encoding='utf-8')),
            json.loads((folder/'model.proposed.json').read_text(encoding='utf-8')))


class PhysicsMapping(unittest.TestCase):
    def test_all_four_roles_have_same_explicit_physics_and_only_selector_changes(self):
        outputs = []
        for role in ROLES:
            old = payload(role); new = patch.apply(*old); outputs.append(new)
            self.assertEqual(new['device'].replace(patch.SELECTOR_NEW,patch.SELECTOR_OLD),old[0])
            self.assertEqual(new['model']['geometry'],old[3]['geometry'])
            self.assertEqual(new['model']['doping'],old[3]['doping'])
            self.assertEqual(new['model']['circuit'],old[3]['circuit'])
            self.assertEqual(new['model']['alpha'],old[3]['alpha'])
            self.assertEqual(new['manifest']['default_cards_sha256'],old[2]['default_cards_sha256'])
            self.assertFalse(new['manifest']['btbt_postprocessing'])
            self.assertFalse(new['manifest']['native_calibration'])
            self.assertFalse(new['manifest']['native_license_verified'])
        self.assertTrue(all(x['parameters']==outputs[0]['parameters'] for x in outputs))
        self.assertTrue(all(x['manifest']==outputs[0]['manifest'] for x in outputs))

    def test_uniform_field_prefactor_mapping_and_equilibrium_factor(self):
        new = patch.apply(*payload('B1-D2'))
        actual = patch.parameter_values(new['parameters'])
        reference = new['manifest']['reference_nonlocal']['parameters']
        self.assertGreater(reference['Ppath'],0)
        self.assertEqual(actual['Pgen'],2.5)
        self.assertEqual(actual['alpha'],0)
        for field in (1e5,5e5,1e6,2e6,1e7):
            reference_limit = reference['Apath']*field**2.5*math.exp(-reference['Bpath']/field)
            for suffix in ('gen','rec'):
                value = actual['A'+suffix]*field**actual['P'+suffix]*math.exp(-actual['B'+suffix]/field)
                self.assertEqual(value,reference_limit)
        # The model's alpha=0 detailed-balance factor, not an E1/E2-only source.
        n,p,ni = 1e8,1e12,1e10
        factor = (n*p-ni**2)/((n+ni)*(p+ni))*(1-abs(actual['alpha']))+actual['alpha']
        self.assertEqual(factor,0.)

    def test_unexpected_reference_or_repeated_application_is_rejected(self):
        old = payload('B1-D2')
        altered = dict(old[2]); altered['btbt_explicit_overrides'] = dict(old[2]['btbt_explicit_overrides'],Apath=8e14)
        with self.assertRaises(ValueError):
            patch.apply(old[0],old[1],altered,old[3])
        new = patch.apply(*old)
        with self.assertRaises(ValueError):
            patch.apply(new['device'],new['parameters'],new['manifest'],new['model'])


if __name__ == '__main__':
    unittest.main()
